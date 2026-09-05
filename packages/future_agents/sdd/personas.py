"""Personas — the seniority and discipline the pipeline works at.

A persona is not flavour text. It changes what the system does: how hard it
interrogates intent before building, which review gates are mandatory, which
heuristics enter the plan as constraints, and which extra artifacts (ADR,
rollback plan, eval set, runbook) the task graph must contain.

The default is `principal_hybrid` — ~25 years across AI/ML systems and
full-stack delivery, which is the profile that catches both "this model change
has no eval set" and "this endpoint has no rollback".
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.models import Risk, Spec, TaskKind, TaskUnit


class Heuristic(BaseModel):
    """One hard-won rule. `applies_to` keywords decide when it fires."""

    text: str
    applies_to: tuple[str, ...] = ()  # empty = always
    severity: str = "medium"  # low | medium | high

    def matches(self, blob: str) -> bool:
        if not self.applies_to:
            return True
        low = blob.lower()
        return any(keyword in low for keyword in self.applies_to)


class ReviewGate(BaseModel):
    """An extra review task the persona insists on before delivery."""

    name: str
    description: str
    applies_to: tuple[str, ...] = ()

    def matches(self, blob: str) -> bool:
        if not self.applies_to:
            return True
        low = blob.lower()
        return any(keyword in low for keyword in self.applies_to)


class Persona(BaseModel):
    """Seniority profile applied to a whole run."""

    id: str
    title: str
    years_experience: int = 10
    disciplines: list[str] = Field(default_factory=list)
    summary: str = ""
    # Confidence a principal demands before building. Higher = asks more first.
    ready_threshold: Optional[float] = None
    meeting_threshold: Optional[float] = None
    max_clarification_rounds: Optional[int] = None
    required_coverage: Optional[float] = None
    heuristics: list[Heuristic] = Field(default_factory=list)
    gates: list[ReviewGate] = Field(default_factory=list)
    engine_overrides: dict[str, str] = Field(default_factory=dict)

    # ── Effects ───────────────────────────────────────────────────────────────

    def apply_to_config(self, config: SpecKitConfig) -> SpecKitConfig:
        """Return a copy of the rulebook as this persona would set it."""
        tuned = config.model_copy(deep=True)
        if self.ready_threshold is not None:
            tuned.clarification.ready_threshold = self.ready_threshold
        if self.meeting_threshold is not None:
            tuned.clarification.meeting_threshold = self.meeting_threshold
        if self.max_clarification_rounds is not None:
            tuned.clarification.max_rounds = self.max_clarification_rounds
        if self.required_coverage is not None:
            tuned.qa.required_coverage = self.required_coverage
        for role, engine in self.engine_overrides.items():
            if role in tuned.agents.roles:
                tuned.agents.roles[role].engine = engine
        return tuned

    def risks_for(self, spec: Spec) -> list[Risk]:
        """Experience, expressed as risks on the plan rather than advice in a prompt."""
        blob = " ".join(
            [spec.title, spec.summary, *(r.statement for r in spec.requirements)]
        ).lower()
        return [
            Risk(
                description=h.text,
                severity=h.severity,
                mitigation="address in the task graph or record why it does not apply",
                source=f"persona:{self.id}",
            )
            for h in self.heuristics
            if h.matches(blob)
        ]

    def gate_tasks(self, spec: Spec, depends_on: list[str], start_index: int) -> list[TaskUnit]:
        """Mandatory review units this persona adds before delivery."""
        blob = " ".join(
            [spec.title, spec.summary, *(r.statement for r in spec.requirements)]
        ).lower()
        tasks: list[TaskUnit] = []
        index = start_index
        for gate in self.gates:
            if not gate.matches(blob):
                continue
            index += 1
            tasks.append(
                TaskUnit(
                    id=f"T-{index:03d}",
                    title=gate.name,
                    description=gate.description,
                    kind=TaskKind.REVIEW,
                    requirement_ids=[r.id for r in spec.requirements],
                    depends_on=list(depends_on),
                    engine="",
                )
            )
        return tasks


# ── Built-in personas ─────────────────────────────────────────────────────────

_AI_HEURISTICS = [
    Heuristic(
        text="Define the eval set and the acceptance bar before touching the model or prompt — "
        "'it looks better' is not a result.",
        applies_to=("model", "prompt", "llm", "embedding", "rag", "agent", "inference", "ml"),
        severity="high",
    ),
    Heuristic(
        text="Pin the model id and record it with the output; a silently upgraded model is an "
        "unversioned dependency.",
        applies_to=("model", "llm", "prompt", "inference", "agent"),
        severity="high",
    ),
    Heuristic(
        text="Cap context and cost per request, and log both — token spend is a production "
        "resource like memory.",
        applies_to=("llm", "prompt", "agent", "rag", "context", "token"),
    ),
    Heuristic(
        text="Treat retrieved documents and tool output as untrusted input: they can carry "
        "instructions.",
        applies_to=("rag", "retrieval", "agent", "tool", "scrape", "webhook", "mcp"),
        severity="high",
    ),
    Heuristic(
        text="Non-determinism needs a seed, a snapshot, or a tolerance — never an exact-match "
        "assertion on generated text.",
        applies_to=("model", "llm", "generate", "prompt", "agent"),
    ),
    Heuristic(
        text="Measure the baseline before optimising; a speedup with no baseline is a story.",
        applies_to=("performance", "latency", "optimi", "faster", "throughput", "scale"),
    ),
]

_FULLSTACK_HEURISTICS = [
    Heuristic(
        text="Every schema change ships with a migration and a tested rollback path.",
        applies_to=("schema", "migration", "database", "table", "column", "index"),
        severity="high",
    ),
    Heuristic(
        text="An API change is a contract change: version it, or keep the old shape working.",
        applies_to=("api", "endpoint", "contract", "payload", "response", "graphql", "grpc"),
        severity="high",
    ),
    Heuristic(
        text="Validate at the boundary, encode on output — never trust a client-side check.",
        applies_to=("input", "form", "api", "upload", "user", "request", "endpoint"),
        severity="high",
    ),
    Heuristic(
        text="Anything crossing the network needs a timeout, a retry policy with backoff, and an "
        "idempotency key if it writes.",
        applies_to=("http", "api", "request", "webhook", "integration", "queue", "sync"),
    ),
    Heuristic(
        text="Ship it observable: a log line, a metric and an alert threshold, decided before "
        "release, not after the incident.",
    ),
    Heuristic(
        text="Feature-flag anything that changes behaviour for existing users; the rollback is "
        "the flag, not a redeploy.",
        applies_to=("release", "rollout", "behaviour", "behavior", "ui", "migration", "flow"),
    ),
    Heuristic(
        text="Cache with an explicit key, TTL and invalidation trigger — an unowned cache becomes "
        "a stale-data bug.",
        applies_to=("cache", "redis", "memoi", "performance", "latency"),
    ),
    Heuristic(
        text="N+1 queries and unbounded result sets are the two defects that reach production "
        "most often: paginate and check the query count.",
        applies_to=("query", "list", "database", "orm", "report", "export", "search"),
    ),
]

_DELIVERY_HEURISTICS = [
    Heuristic(
        text="Write the runbook entry with the change: what breaks, how you see it, "
        "how you undo it.",
        severity="medium",
    ),
    Heuristic(
        text="Record the decision as an ADR when the choice would be expensive to reverse.",
        applies_to=("architecture", "framework", "database", "protocol", "vendor", "platform"),
    ),
    Heuristic(
        text="Secrets come from the environment or a manager, are never logged, and rotate "
        "without a code change.",
        applies_to=("secret", "key", "token", "credential", "auth", "password"),
        severity="high",
    ),
]

_GATES = {
    "security": ReviewGate(
        name="Security review",
        description="Authn/authz path, input validation, secret handling, dependency audit.",
        applies_to=("auth", "login", "payment", "pii", "phi", "token", "secret", "upload", "admin"),
    ),
    "data": ReviewGate(
        name="Data migration and rollback review",
        description="Migration is reversible, backfill is chunked, rollback is tested.",
        applies_to=("migration", "schema", "backfill", "database", "table"),
    ),
    "eval": ReviewGate(
        name="Model evaluation gate",
        description="Eval set exists, baseline recorded, acceptance bar met, model id pinned.",
        applies_to=("model", "prompt", "llm", "rag", "agent", "ml", "embedding"),
    ),
    "perf": ReviewGate(
        name="Performance budget check",
        description="Latency/throughput budget stated and measured against the baseline.",
        applies_to=("latency", "performance", "throughput", "scale", "faster", "load"),
    ),
    "observability": ReviewGate(
        name="Observability and rollback readiness",
        description="Logs, metrics, alert thresholds and the rollback path are in place.",
    ),
    "docs": ReviewGate(
        name="ADR and runbook",
        description="Decision recorded, runbook updated, README reflects the new behaviour.",
    ),
}

PRINCIPAL_AI_ENGINEER = Persona(
    id="principal_ai_engineer",
    title="Principal AI Engineer",
    years_experience=25,
    disciplines=["ml-systems", "llm-applications", "data-engineering", "evaluation"],
    summary=(
        "Builds AI systems that survive contact with production: evaluated, versioned, "
        "cost-bounded, and safe with untrusted input."
    ),
    ready_threshold=0.8,
    meeting_threshold=0.5,
    required_coverage=1.0,
    heuristics=_AI_HEURISTICS + _DELIVERY_HEURISTICS,
    gates=[_GATES["eval"], _GATES["security"], _GATES["observability"], _GATES["docs"]],
)

PRINCIPAL_FULLSTACK = Persona(
    id="principal_fullstack",
    title="Principal Full-Stack Engineer",
    years_experience=25,
    disciplines=["backend", "frontend", "api-design", "databases", "release-engineering"],
    summary=(
        "Ships end-to-end changes with contracts, migrations, observability and a rollback "
        "that has actually been tried."
    ),
    ready_threshold=0.78,
    meeting_threshold=0.48,
    required_coverage=1.0,
    heuristics=_FULLSTACK_HEURISTICS + _DELIVERY_HEURISTICS,
    gates=[_GATES["security"], _GATES["data"], _GATES["observability"], _GATES["docs"]],
)

PRINCIPAL_HYBRID = Persona(
    id="principal_hybrid",
    title="Principal AI + Full-Stack Engineer",
    years_experience=25,
    disciplines=[
        "ml-systems",
        "llm-applications",
        "backend",
        "frontend",
        "api-design",
        "databases",
        "platform",
        "release-engineering",
    ],
    summary=(
        "One person who has carried both pagers: model behaviour and the request path. "
        "Interrogates intent hard, then ships with evals, contracts, observability and a "
        "rollback."
    ),
    ready_threshold=0.8,
    meeting_threshold=0.5,
    max_clarification_rounds=2,
    required_coverage=1.0,
    heuristics=_AI_HEURISTICS + _FULLSTACK_HEURISTICS + _DELIVERY_HEURISTICS,
    gates=list(_GATES.values()),
)

STAFF_PLATFORM = Persona(
    id="staff_platform",
    title="Staff Platform / SRE",
    years_experience=18,
    disciplines=["infrastructure", "ci-cd", "reliability", "observability"],
    summary="Owns the paved road: pipelines, environments, and the blast radius of a change.",
    ready_threshold=0.75,
    heuristics=_DELIVERY_HEURISTICS
    + [
        Heuristic(
            text="Infrastructure changes are planned, reviewed and applied — never applied from a "
            "laptop.",
            applies_to=("terraform", "infrastructure", "cluster", "deploy", "pipeline"),
            severity="high",
        ),
        Heuristic(
            text="Patch the pipeline, never rewrite its topology; the golden template is the "
            "contract.",
            applies_to=("ci", "cd", "pipeline", "workflow", "deploy"),
            severity="high",
        ),
    ],
    gates=[_GATES["observability"], _GATES["security"], _GATES["docs"]],
)

PRAGMATIC = Persona(
    id="pragmatic",
    title="Senior Engineer (pragmatic)",
    years_experience=8,
    disciplines=["general"],
    summary="Lighter gates for internal tools and prototypes where the blast radius is small.",
    ready_threshold=0.7,
    meeting_threshold=0.4,
    required_coverage=0.8,
    heuristics=_DELIVERY_HEURISTICS,
    gates=[_GATES["docs"]],
)

PERSONAS: dict[str, Persona] = {
    p.id: p
    for p in (
        PRINCIPAL_HYBRID,
        PRINCIPAL_AI_ENGINEER,
        PRINCIPAL_FULLSTACK,
        STAFF_PLATFORM,
        PRAGMATIC,
    )
}

DEFAULT_PERSONA = PRINCIPAL_HYBRID


def get_persona(persona_id: str | None) -> Persona:
    """Look up a persona; unknown ids fall back to the principal hybrid."""
    if not persona_id:
        return DEFAULT_PERSONA
    return PERSONAS.get(persona_id, DEFAULT_PERSONA)


def persona_catalog() -> list[dict[str, object]]:
    """Catalog for docs, API and UI — one source of truth."""
    return [
        {
            "id": p.id,
            "title": p.title,
            "years_experience": p.years_experience,
            "disciplines": p.disciplines,
            "summary": p.summary,
            "heuristics": len(p.heuristics),
            "gates": [g.name for g in p.gates],
        }
        for p in PERSONAS.values()
    ]
