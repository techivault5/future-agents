"""Skill runners — the four shapes a capability can take.

A skill is invoked with a `WorkContext` and returns `Evidence`. Whether it shells
out, calls a Python function, drives an MCP tool or delegates to a coding agent
is an implementation detail the pipeline never sees.

Every runner is responsible for the same three things: stay inside its timeout,
never touch a forbidden path, and return evidence that says what actually
happened — including when it failed.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from typing import Callable, Optional

from future_agents.sdd.models import Evidence
from future_agents.sdd.workforce.registry import SkillSpec, WorkContext

MAX_OUTPUT = 4000


class SkillError(RuntimeError):
    """The skill could not run at all — distinct from the work failing."""


class SkillNotApplicable(SkillError):
    """This skill has nothing to do here. The caller should try another."""


class CallableSkill:
    """Wraps a plain function. The seam tests and in-process agents use."""

    def __init__(self, spec: SkillSpec, fn: Callable[[WorkContext], Evidence]) -> None:
        self.spec = spec
        self._fn = fn

    def run(self, context: WorkContext) -> Evidence:
        started = time.perf_counter()
        try:
            evidence = self._fn(context)
        except Exception as exc:  # a skill crash is a failed attempt, not a crash
            return Evidence(
                kind="command",
                summary=f"{self.spec.id} raised {type(exc).__name__}",
                exit_code=1,
                output_excerpt=str(exc)[:MAX_OUTPUT],
                produced_by=self.spec.id,
            )
        evidence.produced_by = evidence.produced_by or self.spec.id
        elapsed = time.perf_counter() - started
        evidence.summary = evidence.summary or f"{self.spec.id} ({elapsed:.1f}s)"
        return evidence


class ShellSkill:
    """Runs a command in the repository, and captures what it printed.

    The command template may reference context fields — `{repo_root}`,
    `{target}`, `{commands[test]}` — and is executed without a shell, so a
    template cannot smuggle in a second command.
    """

    def __init__(self, spec: SkillSpec, command: Optional[str] = None) -> None:
        self.spec = spec
        self.command = command or spec.command
        if not self.command:
            raise SkillError(f"skill {spec.id} has no command")

    def run(self, context: WorkContext) -> Evidence:
        rendered = self.render(context)
        if not rendered.strip():
            # The toolchain has no such command (no typechecker, no build step).
            # That is "not applicable", which must never look like a failure.
            raise SkillNotApplicable(f"{self.spec.id}: no command for this toolchain")
        started = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, never shell=True
                shlex.split(rendered),
                cwd=context.repo_root or None,
                capture_output=True,
                text=True,
                timeout=min(self.spec.timeout_seconds, context.timeout_seconds),
                check=False,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            output = f"timed out after {self.spec.timeout_seconds}s"
            exit_code = 124
        except (OSError, ValueError) as exc:
            output = f"could not start: {exc}"
            exit_code = 127

        return Evidence(
            kind="command",
            summary=f"{rendered} → exit {exit_code} in {time.perf_counter() - started:.1f}s",
            command=rendered,
            exit_code=exit_code,
            output_digest=Evidence.digest(output),
            output_excerpt=output[-MAX_OUTPUT:],
            criterion_ids=list(context.task.criterion_ids),
            produced_by=self.spec.id,
        )

    def render(self, context: WorkContext) -> str:
        target = context.target_paths[0] if context.target_paths else ""
        try:
            return self._format(context, target)
        except KeyError:  # the template names a command this toolchain lacks
            return ""

    def _format(self, context: WorkContext, target: str) -> str:
        return self.command.format(
            repo_root=context.repo_root or ".",
            target=target,
            targets=" ".join(context.target_paths),
            task_id=context.task.id,
            title=context.task.title,
            **context.commands,
        )


class McpSkill:
    """An MCP tool, invoked through a caller the host provides.

    The registry never talks to a gateway itself: the host passes in an
    `invoke(tool_name, arguments) -> str` and keeps its own auth and transport.
    """

    def __init__(
        self,
        spec: SkillSpec,
        invoke: Callable[[str, dict], str],
        tool: Optional[str] = None,
    ) -> None:
        self.spec = spec
        self._invoke = invoke
        self.tool = tool or spec.mcp_tool
        if not self.tool:
            raise SkillError(f"skill {spec.id} names no MCP tool")

    def run(self, context: WorkContext) -> Evidence:
        arguments = {
            "task_id": context.task.id,
            "title": context.task.title,
            "description": context.task.description,
            "repo_root": context.repo_root,
            "target_paths": context.target_paths,
            "forbidden_paths": context.forbidden_paths,
            "attempt": context.attempt,
        }
        try:
            output = self._invoke(self.tool, arguments)
            exit_code = 0
        except Exception as exc:
            output = f"{type(exc).__name__}: {exc}"
            exit_code = 1
        return Evidence(
            kind="command",
            summary=f"mcp:{self.tool} → exit {exit_code}",
            command=f"mcp:{self.tool}",
            exit_code=exit_code,
            output_digest=Evidence.digest(output),
            output_excerpt=output[-MAX_OUTPUT:],
            criterion_ids=list(context.task.criterion_ids),
            produced_by=self.spec.id,
        )


class SimulatedSkill:
    """Records what would have happened. Its evidence can never pass QA."""

    def __init__(self, spec: Optional[SkillSpec] = None) -> None:
        self.spec = spec or SkillSpec(id="simulated", name="Simulated work")

    def run(self, context: WorkContext) -> Evidence:
        return Evidence(
            kind="simulated",
            summary=f"[dry-run] {context.task.title}",
            exit_code=0,
            criterion_ids=list(context.task.criterion_ids),
            produced_by=self.spec.id,
        )


def shell_skill(
    skill_id: str,
    command: str,
    kinds: Optional[list[str]] = None,
    writes: bool = False,
    timeout_seconds: float = 600.0,
) -> tuple[SkillSpec, ShellSkill]:
    """Convenience for the common case: one command, one skill."""
    spec = SkillSpec(
        id=skill_id,
        name=skill_id.replace("_", " "),
        command=command,
        kinds=kinds or [],
        writes=writes,
        timeout_seconds=timeout_seconds,
    )
    return spec, ShellSkill(spec)
