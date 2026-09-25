"""The real setup: several databases, the real crawl, the real entrypoint.

Every earlier test built its catalog by hand, with tables named after the
words people use. That hid four things this file now pins down, all found by
crawling three badly named databases the way an office laptop would:

- The production read path did not exist. `Neo4jGraph` could write and had
  none of the methods the orchestrator calls; the Redis profile had no reader.
- Table selection ignored routing's own finding. Routing knew "India" lives
  in `t_emp_m.country_name`, then ranked `t_emp_m` at zero because its name
  shares no word with "people".
- Column values never reached the prompt. The field existed; nothing filled it.
- An undecided status column became an empty filter, and the compiler
  rejected every question on the table trying to parse ''.
"""

from __future__ import annotations

import json
import os

import pytest
import yaml

duckdb = pytest.importorskip("duckdb")
crawl_cli = pytest.importorskip("scripts.beta_queries_crawl", reason="crawl script")
ask_cli = pytest.importorskip("scripts.beta_queries_ask", reason="ask script")

from beta_queries.agent.providers import EchoProvider  # noqa: E402
from beta_queries.app_factory import LOCAL_PRINCIPAL, build_orchestrator  # noqa: E402
from beta_queries.catalog.graph import Edge, Neo4jGraph, TableNode  # noqa: E402
from beta_queries.catalog.load import (  # noqa: E402
    CatalogNotLoaded,
    load_catalog,
    load_graph_from_neo4j,
)

DATABASES = {
    "hr": [
        "CREATE TABLE t_emp_m (emp_id INTEGER PRIMARY KEY, full_name VARCHAR, "
        "country_name VARCHAR, emp_status VARCHAR, dept_id INTEGER)",
        "CREATE TABLE t_dept (dept_id INTEGER PRIMARY KEY, dept_name VARCHAR)",
        "INSERT INTO t_dept VALUES (1,'Engineering'),(2,'Finance')",
        "INSERT INTO t_emp_m VALUES (1,'A','India','ACTIVE',1),(2,'B','India','ACTIVE',2),"
        "(3,'C','India','TERMINATED',1),(4,'D','Germany','ACTIVE',2)",
    ],
    "sales": [
        "CREATE TABLE fct_orders (order_id INTEGER PRIMARY KEY, region_cd VARCHAR, "
        "amount DECIMAL(10,2), order_status VARCHAR)",
        "INSERT INTO fct_orders VALUES (1,'EMEA',100.00,'SHIPPED'),(2,'APAC',250.50,'SHIPPED'),"
        "(3,'EMEA',75.25,'CANCELLED')",
    ],
    "finance": [
        "CREATE TABLE gl_ledger (entry_id INTEGER PRIMARY KEY, account_type VARCHAR, "
        "amount DECIMAL(12,2))",
        "INSERT INTO gl_ledger VALUES (1,'OPEX',5000),(2,'CAPEX',12000),(3,'OPEX',4500)",
    ],
}

SOURCES = {
    "version": 1,
    "defaults": {"profile_values": True, "max_distinct": 500, "sample_limit": 25},
    "sources": [
        {
            "id": "hrdb",
            "dialect": "duckdb",
            "dsn_env": "BQ_DSN_HRDB",
            "description": "HR: employees by country",
            "synonyms": {"people": "emp"},
        },
        {
            "id": "salesdb",
            "dialect": "duckdb",
            "dsn_env": "BQ_DSN_SALESDB",
            "description": "Sales orders by region",
            "synonyms": {"revenue": "amount"},
        },
        {
            "id": "financedb",
            "dialect": "duckdb",
            "dsn_env": "BQ_DSN_FINANCEDB",
            "description": "General ledger spend",
            "synonyms": {"spend": "amount"},
        },
    ],
}


def _plan(ds, sql, value, template, table):
    return {
        "datasource_id": ds,
        "dialect": "duckdb",
        "intent": "aggregate_sum",
        "confidence": 0.9,
        "sql": sql,
        "params": [{"name": "p0", "type": "string", "value": value}],
        "referenced_tables": [table],
        "answer_template": template,
    }


PLANS = {
    "how many people are in india": _plan(
        "hrdb",
        "SELECT COUNT(*) AS n FROM main.t_emp_m WHERE country_name = :p0",
        "India",
        "{{n}}",
        "main.t_emp_m",
    ),
    "total revenue in emea": _plan(
        "salesdb",
        "SELECT SUM(amount) AS r FROM main.fct_orders WHERE region_cd = :p0",
        "EMEA",
        "{{r}}",
        "main.fct_orders",
    ),
    "total opex spend": _plan(
        "financedb",
        "SELECT SUM(amount) AS s FROM main.gl_ledger WHERE account_type = :p0",
        "OPEX",
        "{{s}}",
        "main.gl_ledger",
    ),
}


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """Three databases, crawled by the real crawl script."""
    for name, statements in DATABASES.items():
        con = duckdb.connect(str(tmp_path / f"{name}.duckdb"))
        for s in statements:
            con.execute(s)
        con.close()
    monkeypatch.setenv("BQ_DSN_HRDB", str(tmp_path / "hr.duckdb"))
    monkeypatch.setenv("BQ_DSN_SALESDB", str(tmp_path / "sales.duckdb"))
    monkeypatch.setenv("BQ_DSN_FINANCEDB", str(tmp_path / "finance.duckdb"))
    config = tmp_path / "sources.yaml"
    config.write_text(yaml.safe_dump(SOURCES, sort_keys=False))
    catalog = tmp_path / "catalog"
    assert crawl_cli.main(["--config", str(config), "--out", str(catalog)]) == 0
    return config, catalog


def _orchestrator(estate, provider=None):
    config, catalog = estate
    orch, _ = build_orchestrator(config, catalog, provider=provider or EchoProvider(plans=PLANS))
    return orch


# ── loading ──────────────────────────────────────────────────────────────────


def test_the_crawl_output_loads(estate):
    _, catalog_dir = estate
    catalog = load_catalog(catalog_dir)
    assert set(catalog.datasources) == {"hrdb", "salesdb", "financedb"}
    assert catalog.values["hrdb.main.t_emp_m"]["country_name"][:1]
    assert catalog.summary("hrdb")["value_index"] > 0


def test_an_empty_catalog_refuses_rather_than_routing_nothing(tmp_path):
    with pytest.raises(CatalogNotLoaded, match="run"):
        load_catalog(tmp_path / "nowhere")


def test_pii_values_never_load_even_if_a_file_carries_them(estate):
    """The crawl already skips PII; this is the loader's own lock."""
    _, catalog_dir = estate
    path = catalog_dir / "hrdb.catalog.json"
    raw = json.loads(path.read_text())
    for table in raw["tables"]:
        for col in table["columns"]:
            if col["name"] == "full_name":
                col["sample_values"], col["is_pii"] = ["Ada Lovelace"], True
    path.write_text(json.dumps(raw))

    catalog = load_catalog(catalog_dir)
    assert "full_name" not in catalog.values.get("hrdb.main.t_emp_m", {})


def test_an_undecided_status_filter_is_reported_not_applied(estate):
    _, catalog_dir = estate
    catalog = load_catalog(catalog_dir)
    assert "salesdb.main.fct_orders" not in catalog.default_filters
    assert catalog.pending_filters["salesdb.main.fct_orders"]


# ── answering across three sources ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("question", "source", "value"),
    [
        ("how many people are in india", "hrdb", 2),
        ("total revenue in emea", "salesdb", 175.25),
        ("total opex spend", "financedb", 9500),
    ],
)
def test_each_question_reaches_its_own_database(estate, question, source, value):
    answer = _orchestrator(estate).ask(question, LOCAL_PRINCIPAL)
    assert answer.datasource == source
    assert answer.error is None, answer.error
    assert float(answer.rows[0][0]) == pytest.approx(value)


def test_a_value_alone_finds_a_table_whose_name_shares_no_word_with_the_question(estate):
    """The day-one case: badly named tables, and no synonyms written yet.

    Synonyms are stripped so the value is the only signal. Routing knows
    "india" lives in t_emp_m.country_name; table selection used to discard
    that and rank t_emp_m at zero.
    """
    orch = _orchestrator(estate)
    source = orch.sources["hrdb"]
    source.profile.synonyms = {}

    ranked = orch.candidates_for("how many people are in india", source)
    top = next((c for c in ranked if c.fqn == "hrdb.main.t_emp_m"), None)
    assert top is not None, "the table holding the named value was not considered"
    assert top.score > 0 and ranked[0].fqn == top.fqn


def test_column_values_reach_the_prompt(estate):
    recorder = ask_cli.RecordingProvider(EchoProvider(plans=PLANS))
    _orchestrator(estate, recorder).ask("how many people are in india", LOCAL_PRINCIPAL)
    prompt = recorder.calls[0][1]
    assert "e.g." in prompt and "India" in prompt
    assert "{alias}" not in prompt, "a template placeholder was shown to the model"


def test_pinning_skips_routing(estate):
    answer = _orchestrator(estate).ask(
        "total revenue in emea", LOCAL_PRINCIPAL, datasource="salesdb"
    )
    assert answer.datasource == "salesdb" and answer.error is None


def test_pinning_to_an_unknown_source_is_refused_cleanly(estate):
    answer = _orchestrator(estate).ask("total revenue in emea", LOCAL_PRINCIPAL, datasource="nope")
    assert answer.scenario == "out_of_scope"


def test_a_filter_decided_in_the_config_is_applied(estate, tmp_path):
    config, catalog = estate
    data = yaml.safe_load(config.read_text())
    for src in data["sources"]:
        if src["id"] == "salesdb":
            src["default_filters"] = {"main.fct_orders": "order_status = 'SHIPPED'"}
    decided = tmp_path / "decided.yaml"
    decided.write_text(yaml.safe_dump(data))

    orch, _ = build_orchestrator(decided, catalog, provider=EchoProvider(plans=PLANS))
    answer = orch.ask("total revenue in emea", LOCAL_PRINCIPAL)
    assert float(answer.rows[0][0]) == pytest.approx(100.00)


def test_a_missing_dsn_is_reported_not_silently_dropped(estate, monkeypatch):
    config, catalog = estate
    monkeypatch.delenv("BQ_DSN_FINANCEDB")
    _, report = build_orchestrator(config, catalog, provider=EchoProvider(plans=PLANS))
    assert "BQ_DSN_FINANCEDB" in report.skipped["financedb"]


def test_check_exits_zero_when_ready_and_nonzero_when_not(estate, monkeypatch, capsys):
    config, catalog = estate
    assert ask_cli.main(["--check", "--config", str(config), "--catalog", str(catalog)]) == 0
    monkeypatch.delenv("BQ_DSN_HRDB")
    assert ask_cli.main(["--check", "--config", str(config), "--catalog", str(catalog)]) == 1
    assert "BQ_DSN_HRDB" in capsys.readouterr().out


# ── Neo4j: the read path mirrors the write path ─────────────────────────────


def test_what_neo4j_is_given_is_what_neo4j_is_read_back_as():
    """Record exactly what Neo4jGraph writes, serve it back through the reader.

    If the read query and the write query ever disagree on a property name,
    this fails — which is the drift that left the read path unbuilt before.
    """
    written: list[tuple[str, dict]] = []
    writer = Neo4jGraph(lambda cypher, params: written.append((cypher, params)) or [])
    writer.upsert_table(
        TableNode(
            fqn="hrdb.main.t_emp_m",
            datasource="hrdb",
            schema="main",
            name="t_emp_m",
            columns=["emp_id", "dept_id"],
            terms={"employee"},
            metrics={"headcount"},
            bi_assets=3,
        )
    )
    writer.upsert_table(
        TableNode(
            fqn="hrdb.main.t_dept",
            datasource="hrdb",
            schema="main",
            name="t_dept",
            columns=["dept_id", "dept_name"],
        )
    )
    writer.upsert_edge(
        Edge(
            left="hrdb.main.t_emp_m",
            left_column="dept_id",
            right="hrdb.main.t_dept",
            right_column="dept_id",
            source="declared",
        )
    )

    tables = [p for c, p in written if "HAS_COLUMN" in c]
    edges = [p for c, p in written if "JOINS" in c]
    table_keys = (
        "fqn",
        "schema",
        "name",
        "is_view",
        "row_estimate",
        "terms",
        "bi_assets",
        "metrics",
        "columns",
    )
    edge_keys = (
        "left",
        "right",
        "left_column",
        "right_column",
        "source",
        "cardinality",
        "confidence",
    )

    def run(cypher, _params):
        # A faithful fake: every table written comes back, keyed exactly as
        # READ_TABLES names them, with datasource from the relationship.
        if "HAS_TABLE" in cypher:
            return [
                {**{k: t[k] for k in table_keys}, "datasource": t["datasource"]} for t in tables
            ]
        return [{k: e[k] for k in edge_keys} for e in edges]

    loaded = load_graph_from_neo4j(run)
    emp = loaded.table("hrdb.main.t_emp_m")
    assert emp is not None
    assert (emp.datasource, emp.columns, emp.metrics, emp.bi_assets) == (
        "hrdb",
        ["emp_id", "dept_id"],
        {"headcount"},
        3,
    )
    plan = loaded.join_plan(["hrdb.main.t_emp_m", "hrdb.main.t_dept"])
    assert len(plan.steps) == 1 and plan.steps[0].source == "declared"


def test_the_orchestrator_can_actually_use_what_the_loader_returns(estate):
    """Every method the orchestrator calls exists on the loaded graph."""
    graph = load_catalog(estate[1]).graph
    for method in ("candidate_tables", "join_plan", "table", "tables"):
        assert callable(getattr(graph, method, None)), method
    assert os.environ.get("BQ_DSN_HRDB")


# ── connecting: problems found by --check, not by a failed question ─────────


def test_probe_names_the_package_that_actually_exists(monkeypatch):
    """`.[snowflake]` is not an extra; telling someone to install it cannot work."""
    import builtins

    from beta_queries.sql.connect import INSTALL, probe

    real_import = builtins.__import__

    def no_drivers(name, *a, **kw):
        if name.split(".")[0] in {"snowflake", "psycopg", "databricks", "mysql", "pyodbc"}:
            raise ImportError(name=name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_drivers)
    for dialect in ("snowflake", "postgres", "databricks", "mysql", "sqlserver"):
        message = probe(dialect, "{}")
        assert INSTALL[dialect] in message, (dialect, message)
    assert ".[snowflake]" not in probe("snowflake", "{}")


def test_probe_reports_an_unreachable_database_and_a_working_one(tmp_path):
    from beta_queries.sql.connect import probe

    good = tmp_path / "ok.duckdb"
    duckdb.connect(str(good)).close()
    assert probe("duckdb", str(good)) == ""
    assert probe("duckdb", str(tmp_path / "missing" / "x.duckdb")).startswith("cannot connect")
