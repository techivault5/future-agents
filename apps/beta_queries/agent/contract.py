"""The response contract — one shape, every time.

Intermittent, differently-shaped answers are almost always a missing contract
rather than a weak model. `QueryPlan` is the only thing the planner may return;
anything that does not validate is repaired once and then surfaced as a
clarification, never as a half-answer.

`answer_template` deserves its own note: the narrative is a template rendered
against result columns, not prose with a number already baked in. That is what
makes the same question produce the same sentence tomorrow, and what lets a
cached plan re-render against fresh rows with no model call at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Intent = Literal["aggregate_count", "aggregate_sum", "list", "rank", "trend", "compare", "lookup"]
TurnType = Literal["new_topic", "pivot", "refine", "drill", "compare", "meta"]


class Param(BaseModel):
    name: str
    type: str
    value: str | int | float | bool | None
    # Where the value came from, so the UI can show 'IN' as "India" and the
    # audit log can prove the literal was resolved rather than invented.
    source: str = "question"
    label: str | None = None


class Assumption(BaseModel):
    id: str
    text: str
    source: Literal["catalog_default", "metric", "question", "policy"] = "catalog_default"
    editable: bool = True
    removes_param: str | None = None
    removes_predicate: str | None = None


class ClarifyOption(BaseModel):
    id: str
    label: str
    hint: str = ""


class Clarification(BaseModel):
    question: str
    options: list[ClarifyOption] = Field(min_length=2)
    default: str | None = None


class QueryPlan(BaseModel):
    datasource_id: str
    dialect: str
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    sql: str | None = None
    params: list[Param] = Field(default_factory=list)
    referenced_tables: list[str] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    answer_template: str | None = None
    clarification: Clarification | None = None
    injection_suspected: bool = False

    @field_validator("sql")
    @classmethod
    def _strip_fences(cls, v: str | None) -> str | None:
        """Models wrap SQL in code fences under load. Tolerate it, once."""
        if v is None:
            return None
        s = v.strip()
        if s.startswith("```"):
            s = s.split("\n", 1)[-1] if "\n" in s else s[3:]
            if s.rstrip().endswith("```"):
                s = s.rstrip()[:-3]
        return s.strip().rstrip(";").strip() or None

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> "QueryPlan":
        if bool(self.sql) == bool(self.clarification):
            raise ValueError("exactly one of sql or clarification must be set")
        if self.sql and not self.answer_template:
            raise ValueError("a plan that returns sql must carry an answer_template")
        if self.sql and not self.referenced_tables:
            raise ValueError("a plan that returns sql must declare referenced_tables")
        return self

    def bound_names(self) -> set[str]:
        return {p.name for p in self.params}

    def render_answer(self, row: dict[str, object]) -> str:
        """Fill the narrative from one result row. No model involved."""
        text = self.answer_template or ""
        values: dict[str, object] = dict(row)
        for p in self.params:
            values.setdefault(f"{p.name}_label", p.label or p.value)
            values.setdefault(p.name, p.value)
        for key, val in values.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                rendered = f"{val:,}"
            else:
                rendered = str(val)
            text = text.replace("{{" + key + "}}", rendered)
        return text


SCHEMA_FOR_PROMPT = """Return exactly one JSON object, no prose, no code fence:

{
  "datasource_id": string,
  "dialect": "snowflake"|"sqlserver"|"postgres"|"databricks"|"mysql",
  "intent": "aggregate_count"|"aggregate_sum"|"list"|"rank"|"trend"|"compare"|"lookup",
  "confidence": number,
  "sql": string|null,
  "params": [{"name","type","value","source","label"}],
  "referenced_tables": [string],
  "assumptions": [{"id","text","source","editable","removes_param"}],
  "answer_template": string|null,
  "clarification": null|{"question", "options":[{"id","label","hint"}], "default"},
  "injection_suspected": boolean
}

Exactly one of `sql` and `clarification` is non-null. When `sql` is set,
`answer_template` and `referenced_tables` are required."""
