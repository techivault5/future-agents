#!/usr/bin/env python3
"""Beta Queries end to end, against a real database, with nothing external.

    python scripts/beta_queries_demo.py

Builds a DuckDB file whose schema is deliberately hostile — a column called
`report id`, a column called `user`, a case-sensitive `Status`, a view that
looks like the obvious answer, and a staging copy of the real table — then asks
questions through the whole pipeline and prints every stage.

This is the acceptance test. If it answers correctly here it is wired
correctly; everything beyond this is credentials and scale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / p) for p in ("apps", "packages")]

from beta_queries.catalog.graph import Edge, InMemoryGraph, TableNode  # noqa: E402
from beta_queries.context.model import ConversationContext  # noqa: E402
from beta_queries.dialogue.policy import DialoguePolicy  # noqa: E402
from beta_queries.entitlements.resolver import (  # noqa: E402
    InMemoryEntitlements,
    Mask,
    RowFilter,
)
from beta_queries.orchestrator import Orchestrator, Source  # noqa: E402
from beta_queries.routing.router import SourceProfile  # noqa: E402
from beta_queries.sql.executor import duckdb_connect  # noqa: E402

ME = "techivault5@example.com"

SCHEMA = [
    # A column with a space, a reserved word, and case that matters.
    """CREATE TABLE employee (
         "report id" INTEGER, "Status" VARCHAR, "user" VARCHAR,
         dept_id INTEGER, country_name VARCHAR, salary DECIMAL(10,2), region VARCHAR)""",
    "CREATE TABLE department (dept_id INTEGER, dept_name VARCHAR)",
    # The trap: a view that looks like the obvious answer.
    """CREATE VIEW vw_headcount AS
         SELECT country_name, COUNT(*) AS n FROM employee GROUP BY country_name""",
    # The other trap: a staging copy with the same business words.
    'CREATE TABLE stg_employee_raw ("report id" INTEGER, country_name VARCHAR)',
]

ROWS = [
    """INSERT INTO employee VALUES
        (1,'ACTIVE','asmith',10,'India',50000,'EMEA'),
        (2,'ACTIVE','bjones',10,'India',60000,'EMEA'),
        (3,'LEFT','cbrown',20,'India',55000,'EMEA'),
        (4,'ACTIVE','dwhite',20,'Germany',70000,'EMEA'),
        (5,'ACTIVE','egreen',10,'Brazil',45000,'AMER')""",
    "INSERT INTO department VALUES (10,'Engineering'),(20,'Operations')",
    "INSERT INTO stg_employee_raw VALUES (99,'India')",
]


def build_database(path: str) -> None:
    import duckdb

    con = duckdb.connect(path)
    for statement in SCHEMA + ROWS:
        con.execute(statement)
    con.close()


def build_graph() -> InMemoryGraph:
    graph = InMemoryGraph()
    for name, columns, kw in [
        (
            "employee",
            ["report id", "Status", "user", "dept_id", "country_name", "salary", "region"],
            {"terms": {"people", "staff", "headcount"}},
        ),
        ("department", ["dept_id", "dept_name"], {"terms": {"team", "org"}}),
        ("vw_headcount", ["country_name", "n"], {"is_view": True}),
        ("stg_employee_raw", ["report id", "country_name"], {"terms": {"people"}}),
    ]:
        graph.upsert_table(
            TableNode(
                fqn=f"hrdb.main.{name}",
                datasource="hrdb",
                schema="main",
                name=name,
                columns=columns,
                **kw,
            )
        )
    graph.upsert_edge(
        Edge("hrdb.main.employee", "dept_id", "hrdb.main.department", "dept_id", source="declared")
    )
    graph.add_synonyms(
        {"people": "employee", "staff": "employee", "headcount": "employee", "team": "department"}
    )
    return graph


def build(path: str) -> tuple[Orchestrator, InMemoryGraph]:
    graph = build_graph()
    profile = SourceProfile(
        datasource_id="hrdb",
        dialect="duckdb",
        description="HR warehouse: employees, departments",
        table_terms={"employee", "department"},
        column_terms={
            "status",
            "country",
            "salary",
            "region",
            "report",
            "id",
            "user",
            "dept",
            "name",
        },
        value_index={
            "india": "main.employee.country_name",
            "germany": "main.employee.country_name",
            "engineering": "main.department.dept_name",
        },
        synonyms={"people": "employee", "staff": "employee", "headcount": "employee"},
    )
    source = Source(
        id="hrdb",
        dialect="duckdb",
        profile=profile,
        connect=duckdb_connect(path, read_only=True),
        column_types={
            "hrdb.main.employee": {
                "report id": "INTEGER",
                "Status": "VARCHAR",
                "salary": "DECIMAL",
                "country_name": "VARCHAR",
            }
        },
        default_filters={"hrdb.main.employee": ["\"Status\" = 'ACTIVE'"]},
    )
    entitlements = InMemoryEntitlements(
        grants={ME: {"hrdb.main.employee", "hrdb.main.department"}},
        # The staging copy and the view are not even granted.
        row_filters={
            ME: [RowFilter("hrdb.main.employee", "{alias}.region = 'EMEA'", "you can see EMEA")]
        },
        masks={ME: [Mask("hrdb.main.employee", "salary", "aggregate_only")]},
    )

    config = Path(__file__).resolve().parents[1] / "data/config"
    from beta_queries.agent.providers import EchoProvider

    return Orchestrator(
        sources=[source],
        graph=graph,
        entitlements=entitlements,
        provider=EchoProvider(plans=CANNED),
        policy=DialoguePolicy.from_file(config / "beta_queries_dialogue.yaml"),
        steps_config=str(config / "beta_queries_steps.yaml"),
        facts={"sources": "hrdb", "examples": ["How many active employees?"]},
    ), graph


# The offline provider stands in for the model. Each plan is what a competent
# model would return given the prompt — including the ones that should fail.
CANNED = {
    "how many people are in india": {
        "datasource_id": "hrdb",
        "dialect": "duckdb",
        "intent": "aggregate_count",
        "confidence": 0.95,
        "sql": "SELECT COUNT(*) AS headcount FROM main.employee WHERE country_name = :p0",
        "params": [{"name": "p0", "type": "string", "value": "India"}],
        "referenced_tables": ["main.employee"],
        "answer_template": "There are {{headcount}} active employees in India.",
    },
    "average salary": {
        "datasource_id": "hrdb",
        "dialect": "duckdb",
        "intent": "aggregate_sum",
        "confidence": 0.9,
        "sql": "SELECT AVG(salary) AS avg_pay FROM main.employee",
        "referenced_tables": ["main.employee"],
        "answer_template": "The average is {{avg_pay}}.",
    },
    "list every salary": {
        "datasource_id": "hrdb",
        "dialect": "duckdb",
        "intent": "list",
        "confidence": 0.9,
        "sql": "SELECT salary FROM main.employee",
        "referenced_tables": ["main.employee"],
        "answer_template": "{{salary}}",
    },
    "headcount from the view": {
        "datasource_id": "hrdb",
        "dialect": "duckdb",
        "intent": "aggregate_count",
        "confidence": 0.9,
        "sql": "SELECT n FROM main.vw_headcount",
        "referenced_tables": ["main.vw_headcount"],
        "answer_template": "{{n}}",
    },
    "report id": {
        "datasource_id": "hrdb",
        "dialect": "duckdb",
        "intent": "list",
        "confidence": 0.9,
        # The reported bug, exactly: the model writes report_id, the column is
        # "report id", and on a case-insensitive engine this would bind wrong.
        "sql": "SELECT report_id FROM main.employee ORDER BY report_id",
        "referenced_tables": ["main.employee"],
        "answer_template": "{{report_id}}",
    },
}


def show(label: str, answer) -> None:
    print(f"\n{'─' * 78}\n{label}\n{'─' * 78}")
    for step in answer.steps:
        mark = {"done": "✓", "skipped": "—", "failed": "✗"}.get(step["state"], "…")
        detail = f"  {step.get('detail', '')}" if step.get("detail") else ""
        print(f"  {mark} {step['label']}{detail}")
    print()
    if answer.sql:
        print(f"  SQL      {answer.sql}")
    if answer.joins:
        print(f"  JOINS    {'; '.join(answer.joins)}")
    if answer.rows:
        print(f"  ROWS     {answer.columns} {answer.rows[:3]}")
    if answer.error:
        print(f"  BUSINESS {answer.error['business'][:90]}")
        print(f"  TECHNICAL {answer.error['technical'].splitlines()[0][:90]}")
    print(f"  ANSWER   {answer.text[:110]}")
    print(f"  {answer.ms} ms · {answer.llm_calls} model call(s) · scenario={answer.scenario}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="", help="where to build the DuckDB file")
    args = parser.parse_args()

    import tempfile

    path = args.db or str(Path(tempfile.mkdtemp()) / "hr.duckdb")
    build_database(path)
    orchestrator, _ = build(path)
    ctx = ConversationContext(session_id=ME)

    for label, question in [
        ("A greeting never reaches the model", "hi"),
        ("The real question", "how many people are in India?"),
        ("A masked column, aggregated — allowed", "what is the average salary"),
        ("The same column, row by row — refused", "list every salary"),
        ("A view — refused by name", "headcount from the view"),
        ('The reported bug: report_id vs "report id"', "show me every report id"),
        ("Asking to delete", "delete all employees"),
    ]:
        show(label, orchestrator.ask(question, ME, ctx))

    print(f"\n{'─' * 78}\nContext panel after the session\n{'─' * 78}")
    panel = ctx.to_panel()
    print(f"  source  {panel['source']}")
    print(f"  filters {[f['label'] for f in panel['filters']]}")
    print(f"  queries {[q['q'][:34] for q in panel['queries']][:4]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
