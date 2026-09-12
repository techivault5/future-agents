"""The constitution — global guardrails every stage is bound by.

Rules are data, not prose, so a gate can *evaluate* them. `render_markdown()`
emits the prose form for agents that only read text (and for exposure as an
MCP resource), which keeps the two from drifting apart.
"""

from __future__ import annotations

import difflib
import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import Plan, Spec, TaskGraph, TaskKind


class Severity(str, Enum):
    ERROR = "error"  # fails the gate
    WARN = "warn"  # recorded, does not fail


class Violation(BaseModel):
    rule: str
    severity: Severity = Severity.ERROR
    detail: str = ""
    subject: str = ""  # artifact id / requirement id / file

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"[{self.severity.value}] {self.rule}: {self.detail}"


class Constitution(BaseModel):
    """Non-negotiable rules. Loaded from `spec-kit-enterprise.yaml` governance."""

    runtime_stack: str = ""
    banned_practices: list[str] = Field(default_factory=list)
    required_practices: list[str] = Field(default_factory=list)
    security_boundaries: list[str] = Field(default_factory=list)
    # Test parity: every MUST requirement needs at least one test task.
    enforce_test_parity: bool = True
    # Spec purity: the functional spec must not name the tech stack.
    enforce_spec_purity: bool = True
    stack_terms: list[str] = Field(default_factory=list)
    escalation_triggers: list[str] = Field(default_factory=list)
    anti_rewrite_rules: list[str] = Field(default_factory=list)
    max_component_fanout: int = 12
    # Observability: a feature nobody can see failing is not finished. The gate
    # warns by default and can be made blocking per project.
    require_observability: bool = True
    require_slo_for_must: bool = True
    require_signal_per_component: bool = True
    require_runbook: bool = True
    observability_is_blocking: bool = False

    # ── Gates ─────────────────────────────────────────────────────────────────

    def check_spec(self, spec: Spec) -> list[Violation]:
        out: list[Violation] = []
        for req in spec.requirements:
            if not req.acceptance_criteria:
                out.append(
                    Violation(
                        rule="acceptance-criteria-required",
                        detail=f"{req.id} has no Given/When/Then criteria",
                        subject=req.id,
                    )
                )
            if self.enforce_spec_purity:
                hit = self._stack_leak(req.statement)
                if hit:
                    out.append(
                        Violation(
                            rule="spec-purity",
                            severity=Severity.WARN,
                            detail=f"{req.id} names implementation detail '{hit}'",
                            subject=req.id,
                        )
                    )
        for question in spec.open_questions:
            if question.blocking and not question.answered:
                out.append(
                    Violation(
                        rule="no-blocking-unknowns",
                        detail=f"unanswered blocking question: {question.text}",
                        subject=question.id,
                    )
                )
        return out

    def check_plan(self, plan: Plan, spec: Optional[Spec] = None) -> list[Violation]:
        out: list[Violation] = []
        if spec is not None and plan.spec_hash != spec.content_hash():
            out.append(
                Violation(
                    rule="stale-plan",
                    detail="plan was drawn from a different spec revision — replan",
                    subject=plan.id,
                )
            )
        blob = " ".join(
            [plan.architecture, plan.test_strategy, *(c.responsibility for c in plan.components)]
        ).lower()
        for banned in self.banned_practices:
            if self._mentions(blob, banned):
                out.append(
                    Violation(
                        rule="banned-practice",
                        detail=banned,
                        subject=plan.id,
                    )
                )
        if len(plan.components) > self.max_component_fanout:
            out.append(
                Violation(
                    rule="component-fanout",
                    severity=Severity.WARN,
                    detail=f"{len(plan.components)} components exceeds {self.max_component_fanout}",
                    subject=plan.id,
                )
            )
        if not plan.test_strategy:
            out.append(Violation(rule="test-strategy-required", subject=plan.id))
        out.extend(self._check_observability(plan, spec))
        return out

    def _check_observability(self, plan: Plan, spec: Optional[Spec]) -> list[Violation]:
        """Monitoring is part of the design, so a plan without it is incomplete.

        Severity is configurable because teams adopt this at different speeds:
        a warning still reaches the delivery record and the risk register, while
        `observability_is_blocking` makes an unwatched feature fail the gate.
        """
        if not self.require_observability:
            return []
        level = Severity.ERROR if self.observability_is_blocking else Severity.WARN
        out: list[Violation] = []
        obs = plan.observability
        if obs is None:
            return [
                Violation(
                    rule="observability-required",
                    severity=level,
                    detail="the plan says nothing about how this is watched in production",
                    subject=plan.id,
                )
            ]

        if self.require_signal_per_component:
            for component in plan.components:
                if not obs.signals_for(component.name):
                    out.append(
                        Violation(
                            rule="observability-signal-per-component",
                            severity=level,
                            detail=f"{component.name} emits nothing — it would fail invisibly",
                            subject=component.name,
                        )
                    )
        if self.require_slo_for_must and spec is not None:
            for req in spec.requirements:
                if req.priority.value != "must":
                    continue
                if obs.slo_for(req.id) is None:
                    out.append(
                        Violation(
                            rule="observability-slo-for-must",
                            severity=level,
                            detail=f"{req.id} has no objective — 'working' is undefined for it",
                            subject=req.id,
                        )
                    )
        for slo in obs.slos:
            if not obs.alerts_for(slo.id):
                out.append(
                    Violation(
                        rule="observability-alert-per-slo",
                        severity=level,
                        detail=f"{slo.id} can be missed without anyone being told",
                        subject=slo.id,
                    )
                )
        if self.require_runbook:
            unlinked = [a.id for a in obs.alerts if not a.runbook]
            if unlinked:
                out.append(
                    Violation(
                        rule="observability-runbook-required",
                        severity=level,
                        detail=(f"{', '.join(unlinked[:3])} would page someone with no next step"),
                        subject=obs.id,
                    )
                )
        return out

    def check_tasks(self, graph: TaskGraph, spec: Spec) -> list[Violation]:
        out: list[Violation] = []
        if not self.enforce_test_parity:
            return out
        tested = {
            rid
            for task in graph.tasks
            if task.kind is TaskKind.TEST
            for rid in task.requirement_ids
        }
        for req in spec.requirements:
            if req.priority.value == "must" and req.id not in tested:
                out.append(
                    Violation(
                        rule="test-parity",
                        detail=f"{req.id} has no test task",
                        subject=req.id,
                    )
                )
        if self.require_observability and self.require_signal_per_component:
            instrumented = {
                task.component
                for task in graph.tasks
                if task.kind is TaskKind.OBSERVABILITY and task.component
            }
            coded = {
                task.component
                for task in graph.tasks
                if task.kind is TaskKind.CODE and task.component
            }
            for component in sorted(coded - instrumented):
                out.append(
                    Violation(
                        rule="observability-task-required",
                        severity=(
                            Severity.ERROR if self.observability_is_blocking else Severity.WARN
                        ),
                        detail=f"{component} is built but never instrumented",
                        subject=component,
                    )
                )
        for task in graph.tasks:
            if task.kind is TaskKind.CODE and not task.requirement_ids:
                out.append(
                    Violation(
                        rule="untraceable-task",
                        severity=Severity.WARN,
                        detail=f"{task.id} traces to no requirement",
                        subject=task.id,
                    )
                )
        return out

    def requires_escalation(self, text: str) -> list[str]:
        """Escalation triggers matched in free text (auth, payments, PII, …)."""
        low = text.lower()
        return [t for t in self.escalation_triggers if t.lower() in low]

    # ── CI/CD diff gate ───────────────────────────────────────────────────────

    def diff_gate(self, golden: str, proposed: str) -> "PatchDecision":
        """Allow additive patches to a golden pipeline; reject topology rewrites.

        `golden` is the approved template, `proposed` what an agent produced.
        Removing or reordering existing structural lines is a rewrite.
        """
        golden_lines = golden.splitlines()
        proposed_lines = proposed.splitlines()
        matcher = difflib.SequenceMatcher(None, golden_lines, proposed_lines)

        added: list[str] = []
        removed: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("delete", "replace"):
                removed.extend(golden_lines[i1:i2])
            if tag in ("insert", "replace"):
                added.extend(proposed_lines[j1:j2])

        structural = [line for line in removed if _is_topology(line)]
        if structural:
            return PatchDecision(
                allowed=False,
                reason="proposed change removes golden pipeline topology",
                removed_topology=structural,
                added_lines=added,
            )
        return PatchDecision(
            allowed=True,
            reason="additive patch",
            removed_topology=[],
            added_lines=added,
            removed_lines=removed,
        )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render_markdown(self) -> str:
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {i}" for i in items) if items else "- (none)"

        return "\n".join(
            [
                "# Constitution",
                "",
                "## Runtime",
                f"- {self.runtime_stack or '(unspecified)'}",
                "",
                "## Banned practices",
                bullets(self.banned_practices),
                "",
                "## Required practices",
                bullets(self.required_practices),
                "",
                "## Security boundaries",
                bullets(self.security_boundaries),
                "",
                "## CI/CD",
                bullets(self.anti_rewrite_rules),
                "",
                "## Escalate to a human when the work touches",
                bullets(self.escalation_triggers),
                "",
                "## Gates",
                f"- Test parity enforced: {self.enforce_test_parity}",
                f"- Spec purity enforced: {self.enforce_spec_purity}",
                f"- Observability required: {self.require_observability}"
                + (" (blocking)" if self.observability_is_blocking else " (warns)"),
                f"- Objective per MUST requirement: {self.require_slo_for_must}",
                f"- Signal per component: {self.require_signal_per_component}",
                f"- Runbook per alert: {self.require_runbook}",
                "",
            ]
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _stack_leak(self, text: str) -> str:
        low = text.lower()
        return next((term for term in self.stack_terms if self._mentions(low, term)), "")

    @staticmethod
    def _mentions(haystack: str, needle: str) -> bool:
        # Banned practices are written as sentences; match on their content words
        # so "No direct database connections from API route handlers." still
        # fires on "database connection in the route handler".
        words = [w for w in re.findall(r"[a-z]{4,}", needle.lower()) if w not in _FILLER]
        if not words:
            return needle.lower() in haystack
        if len(words) <= 2:
            return all(w in haystack for w in words)
        hits = sum(1 for w in words if w in haystack)
        return hits >= max(2, int(len(words) * 0.6))


_FILLER = {"never", "always", "must", "should", "from", "with", "into", "does", "this", "that"}

_TOPOLOGY_TOKENS = ("jobs:", "runs-on:", "needs:", "uses:", "on:", "steps:", "strategy:")


def _is_topology(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    return any(tok in stripped for tok in _TOPOLOGY_TOKENS)


class PatchDecision(BaseModel):
    allowed: bool
    reason: str
    added_lines: list[str] = Field(default_factory=list)
    removed_lines: list[str] = Field(default_factory=list)
    removed_topology: list[str] = Field(default_factory=list)

    def patch_summary(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "added": len(self.added_lines),
            "removed": len(self.removed_lines),
            "reason": self.reason,
        }
