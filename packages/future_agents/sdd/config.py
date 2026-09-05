"""`spec-kit-enterprise.yaml` — the single rulebook, loaded and validated.

Config is the control plane: governance, engine routing, memory, CI/CD and QA
policy in one file so agents, CI and the API cannot hold different opinions.
`${VAR}` values resolve from the environment — literal secrets are rejected at
load time rather than lint time.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from future_agents.sdd.constitution import Constitution

_ENV_REF = re.compile(r"^\$\{([A-Z0-9_]+)(?::-(.*))?\}$")
_SECRET_KEY = re.compile(r"(api_?key|token|secret|password|credential)", re.IGNORECASE)

DEFAULT_CONFIG_PATHS = (
    Path("data/config/spec_kit/spec-kit-enterprise.yaml"),
    Path(".specify/spec-kit-enterprise.yaml"),
    Path("spec-kit-enterprise.yaml"),
)


class ConfigError(ValueError):
    """The rulebook is missing, malformed, or carries an inline secret."""


class ProjectConfig(BaseModel):
    name: str = "unnamed"
    description: str = ""
    owner: str = ""


class GovernanceConfig(BaseModel):
    runtime_stack: str = ""
    banned_practices: list[str] = Field(default_factory=list)
    required_practices: list[str] = Field(default_factory=list)
    security_boundaries: list[str] = Field(default_factory=list)
    escalation_triggers: list[str] = Field(default_factory=list)
    stack_terms: list[str] = Field(default_factory=list)
    enforce_test_parity: bool = True
    enforce_spec_purity: bool = True


class RoleConfig(BaseModel):
    engine: str
    purpose: str = ""
    fallback: str = ""
    max_tokens: int = 8192
    temperature: float = 0.2


class AgentsConfig(BaseModel):
    mcp_gateway_uri: str = ""
    default_engine: str = "claude-opus-5"
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    # domain keyword → engine, consulted before the role default
    intent_routes: dict[str, str] = Field(default_factory=dict)


class RetrievalConfig(BaseModel):
    max_context_injection: int = 3
    min_score: float = 0.15
    prefer_failures: bool = True  # negative cases teach more than successes
    scope_boost: float = 1.4  # a case from this repo outranks a foreign one
    scope_strict: bool = False  # True → foreign cases are not retrieved at all


class LessonConfig(BaseModel):
    """Semantic memory: pitfalls that recurred, kept as rules with a half-life."""

    enabled: bool = True
    promote_after: int = 2  # a pitfall seen in N distinct cases becomes a lesson
    half_life_days: float = 120.0  # confidence halves over this span without a hit
    dormant_after_days: float = 365.0  # unseen this long → stops being injected
    max_injected: int = 5  # ceiling on lessons pushed into one plan
    min_confidence: float = 0.2


class AnswerBookConfig(BaseModel):
    """Procedural memory: what a human already told us, so we stop re-asking."""

    enabled: bool = True
    reuse_blocking: bool = False  # blocking unknowns are re-asked even if known
    max_age_days: float = 180.0  # older answers are stale; ask again
    scope_strict: bool = True  # an answer from another repo is not this repo's


class MemoryHubConfig(BaseModel):
    enabled: bool = True
    case_studies_path: str = "docs/memory/cases"
    index_path: str = ""
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    lessons: LessonConfig = Field(default_factory=LessonConfig)
    answers: AnswerBookConfig = Field(default_factory=AnswerBookConfig)
    recency_half_life_days: float = 90.0  # retrieval prefers recent cases
    max_cases: int = 500  # beyond this, consolidation prunes old successes
    sanitize_on_write: bool = True  # memory is a prompt-injection persistence vector


class ClarificationConfig(BaseModel):
    """Where the escalation ladder's rungs sit."""

    ready_threshold: float = 0.75  # ≥ → spec straight away
    meeting_threshold: float = 0.45  # < → a human conversation, not a form
    max_rounds: int = 2  # async rounds before escalating to a meeting
    max_questions_per_round: int = 6
    meeting_attendees: list[str] = Field(default_factory=list)
    meeting_duration_minutes: int = 30
    auto_assume_low_risk: bool = True  # answer low-risk unknowns from context

    @field_validator("meeting_threshold")
    @classmethod
    def _ordered(cls, v: float, info: Any) -> float:
        ready = info.data.get("ready_threshold", 0.75)
        if v >= ready:
            raise ValueError("meeting_threshold must be below ready_threshold")
        return v


class CICDConfig(BaseModel):
    enforce_golden_pattern: bool = True
    golden_template_uri: str = ""
    golden_template_path: str = ""
    rules: list[str] = Field(default_factory=list)


class QACommunicationConfig(BaseModel):
    verbosity: str = "summary_only"  # summary_only | verbose
    max_summary_lines: int = 8


class QAConfig(BaseModel):
    enforce_bdd: bool = True
    enforce_aaa: bool = True
    acceptance_criteria_rules: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    required_coverage: float = 1.0  # fraction of MUST criteria that must verify
    ephemeral_environment: bool = True
    communication: QACommunicationConfig = Field(default_factory=QACommunicationConfig)


class SpecKitConfig(BaseModel):
    version: str = "1.0"
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    memory_hub: MemoryHubConfig = Field(default_factory=MemoryHubConfig)
    clarification: ClarificationConfig = Field(default_factory=ClarificationConfig)
    cicd: CICDConfig = Field(default_factory=CICDConfig)
    qa: QAConfig = Field(default_factory=QAConfig)

    # ── Loading ───────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path | None = None, root: str | Path = ".") -> "SpecKitConfig":
        """Load the rulebook. Falls back to built-in defaults when absent."""
        candidates = [Path(path)] if path else [Path(root) / p for p in DEFAULT_CONFIG_PATHS]
        for candidate in candidates:
            if candidate.is_file():
                return cls.from_yaml(candidate.read_text())
        if path:
            raise ConfigError(f"config not found: {path}")
        return cls()

    @classmethod
    def from_yaml(cls, text: str) -> "SpecKitConfig":
        try:
            raw = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:  # pragma: no cover - message passthrough
            raise ConfigError(f"invalid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a mapping")
        return cls.model_validate(_resolve(raw, trail=""))

    # ── Derived views ─────────────────────────────────────────────────────────

    def constitution(self) -> Constitution:
        g = self.governance
        return Constitution(
            runtime_stack=g.runtime_stack,
            banned_practices=g.banned_practices,
            required_practices=g.required_practices,
            security_boundaries=g.security_boundaries,
            escalation_triggers=g.escalation_triggers,
            stack_terms=g.stack_terms,
            enforce_test_parity=g.enforce_test_parity,
            enforce_spec_purity=g.enforce_spec_purity,
            anti_rewrite_rules=self.cicd.rules,
        )

    def engine_for(self, role: str) -> str:
        cfg = self.agents.roles.get(role)
        return cfg.engine if cfg else self.agents.default_engine

    def golden_template(self, root: str | Path = ".") -> Optional[str]:
        if not self.cicd.golden_template_path:
            return None
        path = Path(root) / self.cicd.golden_template_path
        return path.read_text() if path.is_file() else None


def _resolve(node: Any, trail: str) -> Any:
    """Recursively expand `${VAR}` and refuse literal secrets."""
    if isinstance(node, dict):
        return {k: _resolve(v, f"{trail}.{k}" if trail else str(k)) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, f"{trail}[{i}]") for i, v in enumerate(node)]
    if isinstance(node, str):
        match = _ENV_REF.match(node.strip())
        if match:
            name, default = match.group(1), match.group(2)
            value = os.environ.get(name, default)
            if value is None:
                raise ConfigError(f"{trail}: environment variable {name} is not set")
            return value
        leaf = trail.rsplit(".", 1)[-1]
        if _SECRET_KEY.search(leaf) and node.strip():
            raise ConfigError(
                f"{trail}: inline secret — use ${{ENV_VAR}} or a secrets manager instead"
            )
    return node
