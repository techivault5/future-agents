"""Backends — where a task stops being a plan and becomes work.

`DispatchBackend` is the one that matters: it asks the dispatcher who should do
a task, builds the context that agent is allowed to see, runs it under a
sandbox, a timeout, a budget and a loop detector, retries a failure with the
error attached, and returns evidence of what actually ran.

`ToolchainBackend` needs no agents at all: it runs the repository's own
commands (its test command for a test task, its lint/format for review) and is
the honest floor — real execution with zero LLM involvement.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from future_agents.sdd.execution.resilience import (
    BudgetExceeded,
    BudgetGuard,
    CircuitBreaker,
    CircuitOpen,
    LoopDetector,
)
from future_agents.sdd.execution.sandbox import WorkspacePolicy
from future_agents.sdd.models import (
    Evidence,
    ForbiddenZone,
    Plan,
    Spec,
    TaskKind,
    TaskStatus,
    TaskUnit,
    WorkResult,
)
from future_agents.sdd.repos.languages import GENERIC, Toolchain
from future_agents.sdd.workforce.dispatch import Dispatcher, NoAgentAvailable
from future_agents.sdd.workforce.registry import WorkContext, Workforce
from future_agents.sdd.workforce.skills import (
    CallableSkill,
    ShellSkill,
    SimulatedSkill,
    SkillError,
    SkillNotApplicable,
)

#: Which toolchain command a task kind runs when nothing better is configured.
KIND_COMMANDS: dict[str, tuple[str, ...]] = {
    TaskKind.TEST.value: ("test",),
    TaskKind.CODE.value: ("build", "typecheck"),
    TaskKind.REVIEW.value: ("lint", "format"),
    TaskKind.INFRA.value: ("install",),
    TaskKind.DOC.value: (),
}


class ToolchainBackend:
    """Runs the repository's own commands. No agents, no models, real exit codes."""

    def __init__(
        self,
        repo_root: str,
        toolchain: Optional[Toolchain] = None,
        timeout_seconds: float = 900.0,
    ) -> None:
        self.repo_root = repo_root
        self.toolchain = toolchain or GENERIC
        self.timeout_seconds = timeout_seconds

    def __call__(self, task: TaskUnit, spec: Spec) -> WorkResult:
        commands = self.toolchain.commands()
        names = KIND_COMMANDS.get(task.kind.value, ())
        wanted = [commands[name] for name in names if name in commands]
        if not wanted:
            return WorkResult(
                task_id=task.id,
                status=TaskStatus.SKIPPED,
                summary=f"no toolchain command for a {task.kind.value} task",
            )

        evidence: list[Evidence] = []
        for command in wanted:
            spec_, runner = _adhoc_shell(f"toolchain:{task.kind.value}", command)
            del spec_
            evidence.append(
                runner.run(
                    WorkContext(
                        task=task,
                        spec=spec,
                        repo_root=self.repo_root,
                        commands=commands,
                        timeout_seconds=self.timeout_seconds,
                    )
                )
            )

        ok = all(item.passed for item in evidence)
        return WorkResult(
            task_id=task.id,
            status=TaskStatus.DONE if ok else TaskStatus.FAILED,
            summary="; ".join(item.summary for item in evidence)[:400],
            evidence=evidence,
            criterion_ids=list(task.criterion_ids) if ok and task.kind is TaskKind.TEST else [],
            error="" if ok else next(i.output_excerpt for i in evidence if not i.passed)[:800],
        )


class DispatchBackend:
    """Hands a task to the best available agent, under every guard we have."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        repo_root: str = "",
        plan: Optional[Plan] = None,
        forbidden: Optional[list[ForbiddenZone]] = None,
        toolchain: Optional[Toolchain] = None,
        guard: Optional[BudgetGuard] = None,
        max_attempts: int = 2,
        timeout_seconds: float = 900.0,
        fallback: Optional[Callable[[TaskUnit, Spec], WorkResult]] = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.repo_root = repo_root
        self.plan = plan
        self.forbidden = forbidden or []
        self.toolchain = toolchain or GENERIC
        self.guard = guard or BudgetGuard()
        self.max_attempts = max(1, max_attempts)
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback
        self.breakers: dict[str, CircuitBreaker] = {}
        self.assignments: list = []

    # ── Execution ─────────────────────────────────────────────────────────────

    def __call__(self, task: TaskUnit, spec: Spec) -> WorkResult:
        self.guard.tick()
        placement = (
            self.plan.placement_for(task.requirement_ids[0])
            if (self.plan and task.requirement_ids)
            else None
        )
        policy = WorkspacePolicy.for_task(task, placement, self.forbidden)
        detector = LoopDetector()

        try:
            assignment = self.dispatcher.assign(task, spec)
        except NoAgentAvailable as exc:
            if self.fallback:
                return self.fallback(task, spec)
            return WorkResult(task_id=task.id, status=TaskStatus.BLOCKED, error=str(exc))

        self.assignments.append(assignment)
        breaker = self.breakers.setdefault(
            assignment.agent_id, CircuitBreaker(name=assignment.agent_id)
        )
        evidence: list[Evidence] = []
        previous_error = ""
        started = time.perf_counter()
        status = TaskStatus.FAILED

        for attempt in range(1, self.max_attempts + 1):
            assignment.attempts = attempt
            context = WorkContext(
                task=task,
                spec=spec,
                repo_root=self.repo_root,
                target_paths=policy.allowed,
                forbidden_paths=policy.denied,
                commands=self.toolchain.commands(),
                attempt=attempt,
                previous_error=previous_error,
                agent_id=assignment.agent_id,
                skill_id=assignment.skill_id,
                timeout_seconds=self.timeout_seconds,
            )
            try:
                produced = breaker.call(lambda: self._run(assignment, context))
            except CircuitOpen as exc:
                evidence.append(_failure(task, f"circuit open: {exc}", assignment.agent_id))
                break
            except BudgetExceeded:
                raise
            except SkillNotApplicable as exc:
                # Nothing this agent can run applies here. Not a failure.
                if self.fallback:
                    self.dispatcher.record(assignment, ok=True, seconds=0.0)
                    return self.fallback(task, spec)
                return WorkResult(
                    task_id=task.id,
                    status=TaskStatus.SKIPPED,
                    summary=str(exc),
                    agent_id=assignment.agent_id,
                )
            except SkillError as exc:
                evidence.append(_failure(task, f"skill error: {exc}", assignment.agent_id))
                break

            evidence.extend(produced)
            self.guard.charge_task(attempts=1)

            failed = [item for item in produced if not item.passed]
            if not failed:
                status = TaskStatus.DONE
                break
            previous_error = failed[-1].output_excerpt[:1500]
            if any(detector.observe(item) for item in failed):
                evidence.append(
                    _failure(task, "identical failure repeated — stopping", assignment.agent_id)
                )
                break

        changed = sorted({path for item in evidence for path in _changed_paths(item)})
        violations = policy.check(changed)
        if violations:
            status = TaskStatus.FAILED
            evidence.append(
                _failure(
                    task, "sandbox violation: " + "; ".join(violations[:3]), assignment.agent_id
                )
            )

        seconds = time.perf_counter() - started
        self.dispatcher.record(assignment, ok=status is TaskStatus.DONE, seconds=seconds)

        return WorkResult(
            task_id=task.id,
            status=status,
            summary=f"{assignment.agent_id} via {assignment.skill_id or 'handler'} "
            f"({assignment.attempts} attempt(s))",
            agent_id=assignment.agent_id,
            engine=task.engine,
            evidence=evidence,
            attempts=assignment.attempts,
            changed_files=changed,
            criterion_ids=list(task.criterion_ids)
            if status is TaskStatus.DONE and task.kind is TaskKind.TEST
            else [],
            error="" if status is TaskStatus.DONE else previous_error[:800],
            duration_ms=round(seconds * 1000, 3),
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, assignment, context: WorkContext) -> list[Evidence]:
        """Agent handler first; otherwise the first skill that can actually run."""
        workforce: Workforce = self.dispatcher.workforce
        handler = workforce.handler_for(assignment.agent_id)
        if handler is not None:
            produced = handler(context)
            return list(produced) if isinstance(produced, list) else [produced]

        agent = workforce.agents.get(assignment.agent_id)
        candidates = workforce.skills_for(context.task, agent, self.dispatcher.language)
        if assignment.skill_id and assignment.skill_id in workforce.skills:
            chosen = workforce.skills[assignment.skill_id]
            candidates = [chosen] + [s for s in candidates if s.id != chosen.id]

        last_error: Optional[SkillNotApplicable] = None
        for spec in candidates:
            skill_handler = workforce.skill_handler_for(spec.id)
            if skill_handler is not None:
                assignment.skill_id = spec.id
                return [CallableSkill(spec, skill_handler).run(context)]
            if spec.command:
                try:
                    evidence = ShellSkill(spec).run(context)
                except SkillNotApplicable as exc:
                    last_error = exc
                    continue
                assignment.skill_id = spec.id
                return [evidence]

        if last_error is not None:
            raise last_error
        return [SimulatedSkill(candidates[0] if candidates else None).run(context)]


class CompositeBackend:
    """Try backends in order; the first that does not skip wins."""

    def __init__(self, *backends: Callable[[TaskUnit, Spec], WorkResult]) -> None:
        self.backends = backends

    def __call__(self, task: TaskUnit, spec: Spec) -> WorkResult:
        last: Optional[WorkResult] = None
        for backend in self.backends:
            result = backend(task, spec)
            last = result
            if result.status is not TaskStatus.SKIPPED:
                return result
        return last or WorkResult(task_id=task.id, status=TaskStatus.SKIPPED)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _adhoc_shell(skill_id: str, command: str):
    from future_agents.sdd.workforce.skills import shell_skill

    return shell_skill(skill_id, command)


def _failure(task: TaskUnit, message: str, produced_by: str = "") -> Evidence:
    return Evidence(
        kind="command",
        summary=message[:200],
        exit_code=1,
        output_excerpt=message[:2000],
        criterion_ids=list(task.criterion_ids),
        produced_by=produced_by,
    )


def _changed_paths(evidence: Evidence) -> list[str]:
    if evidence.path:
        return [evidence.path]
    return []
