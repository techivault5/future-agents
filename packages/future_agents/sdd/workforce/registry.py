"""The workforce — every agent and skill the system can hand work to.

Specs are data (declarable in YAML, shippable in a repo, reviewable in a PR);
handlers are code, bound at runtime. That split is what makes the workforce
pluggable: a team adds an agent by writing six lines of YAML and registering one
callable, and nothing in the pipeline changes.

An agent is *who* does the work. A skill is *what* it can do — a shell command,
a Python callable, an MCP tool, a Claude Code skill. Agents declare the skills
they can invoke; the dispatcher matches tasks to agents, and agents to skills.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from pydantic import BaseModel, Field

from future_agents.sdd.models import Evidence, Spec, TaskUnit

#: A handler receives the task and its context and returns evidence of work done.
AgentHandler = Callable[["WorkContext"], list[Evidence]]
SkillHandler = Callable[["WorkContext"], Evidence]

ANY = "*"


class WorkContext(BaseModel):
    """Everything a handler is allowed to know about the work it was given."""

    task: TaskUnit
    spec: Optional[Spec] = None
    repo_root: str = ""
    target_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    commands: dict[str, str] = Field(default_factory=dict)  # from the toolchain
    attempt: int = 1
    previous_error: str = ""
    agent_id: str = ""
    skill_id: str = ""
    timeout_seconds: float = 900.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


class SkillSpec(BaseModel):
    """A capability: what it does, when it applies, and how it is invoked."""

    id: str
    name: str = ""
    description: str = ""
    kinds: list[str] = Field(default_factory=list)  # task kinds, empty = any
    triggers: list[str] = Field(default_factory=list)  # keywords in the task text
    languages: list[str] = Field(default_factory=lambda: [ANY])
    command: str = ""  # for shell skills, a template over {…} context fields
    mcp_tool: str = ""  # for MCP-backed skills
    timeout_seconds: float = 600.0
    writes: bool = False  # does it change files?

    def applies_to(self, task: TaskUnit, language: str = "") -> bool:
        if self.kinds and task.kind.value not in self.kinds:
            return False
        if language and ANY not in self.languages and language not in self.languages:
            return False
        if not self.triggers:
            return True
        blob = f"{task.title} {task.description}".lower()
        return any(trigger.lower() in blob for trigger in self.triggers)


class AgentSpec(BaseModel):
    """Who does the work, what it is good at, and how much of it at once."""

    id: str
    name: str = ""
    description: str = ""
    kinds: list[str] = Field(default_factory=list)  # empty = any task kind
    languages: list[str] = Field(default_factory=lambda: [ANY])
    domains: list[str] = Field(default_factory=list)  # api, data, ui, security …
    skills: list[str] = Field(default_factory=list)
    engine: str = ""
    persona_id: str = ""
    max_concurrency: int = 1
    cost_hint: float = 1.0  # relative; lower is cheaper
    priority: int = 5  # tie-break; lower wins
    enabled: bool = True

    def can_take(self, task: TaskUnit, language: str = "") -> bool:
        if not self.enabled:
            return False
        if self.kinds and task.kind.value not in self.kinds:
            return False
        if language and ANY not in self.languages and language not in self.languages:
            return False
        return True

    def domain_overlap(self, task: TaskUnit) -> float:
        if not self.domains:
            return 0.0
        blob = f"{task.title} {task.description} {task.component}".lower()
        hits = sum(1 for domain in self.domains if domain.lower() in blob)
        return hits / len(self.domains)


class AgentHealth(BaseModel):
    """What actually happened when this agent worked — the routing signal."""

    agent_id: str
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    in_flight: int = 0
    total_seconds: float = 0.0
    disabled_until: Optional[datetime] = None
    last_error: str = ""

    @property
    def attempts(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        """Laplace-smoothed, so one lucky success does not win the routing table."""
        return (self.successes + 1) / (self.attempts + 2)

    @property
    def mean_seconds(self) -> float:
        return self.total_seconds / self.attempts if self.attempts else 0.0

    def available(self, spec: AgentSpec, now: Optional[datetime] = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        if self.disabled_until and moment < self.disabled_until:
            return False
        return self.in_flight < max(1, spec.max_concurrency)


class Workforce:
    """The registry: specs, handlers and health, in one place."""

    def __init__(self) -> None:
        self.agents: dict[str, AgentSpec] = {}
        self.skills: dict[str, SkillSpec] = {}
        self.health: dict[str, AgentHealth] = {}
        self._agent_handlers: dict[str, AgentHandler] = {}
        self._skill_handlers: dict[str, SkillHandler] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register_agent(self, spec: AgentSpec, handler: Optional[AgentHandler] = None) -> AgentSpec:
        self.agents[spec.id] = spec
        self.health.setdefault(spec.id, AgentHealth(agent_id=spec.id))
        if handler is not None:
            self._agent_handlers[spec.id] = handler
        return spec

    def register_skill(self, spec: SkillSpec, handler: Optional[SkillHandler] = None) -> SkillSpec:
        self.skills[spec.id] = spec
        if handler is not None:
            self._skill_handlers[spec.id] = handler
        return spec

    def bind(self, agent_id: str, handler: AgentHandler) -> None:
        """Attach code to a spec that was declared in YAML."""
        if agent_id not in self.agents:
            raise KeyError(f"unknown agent {agent_id!r}")
        self._agent_handlers[agent_id] = handler

    def bind_skill(self, skill_id: str, handler: SkillHandler) -> None:
        if skill_id not in self.skills:
            raise KeyError(f"unknown skill {skill_id!r}")
        self._skill_handlers[skill_id] = handler

    def handler_for(self, agent_id: str) -> Optional[AgentHandler]:
        return self._agent_handlers.get(agent_id)

    def skill_handler_for(self, skill_id: str) -> Optional[SkillHandler]:
        return self._skill_handlers.get(skill_id)

    def bound(self, agent_id: str) -> bool:
        return agent_id in self._agent_handlers

    # ── Declarative loading ───────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> "Workforce":
        """Read agents and skills from YAML. Handlers are bound separately."""
        workforce = cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        for entry in data.get("skills", []) or []:
            workforce.register_skill(SkillSpec.model_validate(entry))
        for entry in data.get("agents", []) or []:
            workforce.register_agent(AgentSpec.model_validate(entry))
        return workforce

    def merge(self, other: "Workforce") -> "Workforce":
        """Combine registries — a team's file plus the built-ins."""
        for spec in other.agents.values():
            self.register_agent(spec, other.handler_for(spec.id))
        for spec in other.skills.values():
            self.register_skill(spec, other.skill_handler_for(spec.id))
        return self

    # ── Matching ──────────────────────────────────────────────────────────────

    def candidates(self, task: TaskUnit, language: str = "") -> list[AgentSpec]:
        return [
            spec
            for spec in self.agents.values()
            if spec.can_take(task, language)
            and self.health.setdefault(spec.id, AgentHealth(agent_id=spec.id)).available(spec)
        ]

    def skills_for(
        self, task: TaskUnit, agent: Optional[AgentSpec] = None, language: str = ""
    ) -> list[SkillSpec]:
        allowed = set(agent.skills) if agent and agent.skills else set(self.skills)
        return [
            spec
            for skill_id, spec in self.skills.items()
            if skill_id in allowed and spec.applies_to(task, language)
        ]

    # ── Outcomes ──────────────────────────────────────────────────────────────

    def start(self, agent_id: str) -> None:
        self.health.setdefault(agent_id, AgentHealth(agent_id=agent_id)).in_flight += 1

    def finish(
        self,
        agent_id: str,
        ok: bool,
        seconds: float = 0.0,
        error: str = "",
        breaker_threshold: int = 3,
        cooldown_seconds: int = 300,
    ) -> AgentHealth:
        """Record what happened, and trip the breaker on a repeat offender."""
        from datetime import timedelta

        health = self.health.setdefault(agent_id, AgentHealth(agent_id=agent_id))
        health.in_flight = max(0, health.in_flight - 1)
        health.total_seconds += seconds
        if ok:
            health.successes += 1
            health.consecutive_failures = 0
        else:
            health.failures += 1
            health.consecutive_failures += 1
            health.last_error = error[:300]
            if health.consecutive_failures >= breaker_threshold:
                health.disabled_until = datetime.now(timezone.utc) + timedelta(
                    seconds=cooldown_seconds
                )
        return health

    def stats(self) -> dict[str, Any]:
        return {
            "agents": len(self.agents),
            "skills": len(self.skills),
            "bound": sum(1 for a in self.agents if self.bound(a)),
            "health": {
                agent_id: {
                    "success_rate": round(h.success_rate, 3),
                    "attempts": h.attempts,
                    "in_flight": h.in_flight,
                    "disabled": bool(h.disabled_until),
                }
                for agent_id, h in self.health.items()
                if h.attempts or h.in_flight
            },
        }
