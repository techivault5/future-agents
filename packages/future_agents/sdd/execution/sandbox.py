"""Blast radius — what a task is allowed to touch, checked before and after.

Placement said where the change goes; the sandbox turns that into a fence. A
backend that writes outside its allowed paths has its result rejected, whatever
it claims to have done. This is the difference between an agent that made a
change and an agent that was *permitted* to make that change.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import ForbiddenZone, PlacementDecision, TaskUnit

#: Never writable by any task, in any repository, regardless of configuration.
HARD_DENY = (
    ".git/*",
    ".env",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "*.tfstate",
    "terraform.tfvars",
    "credentials.json",
    "secrets.json",
    "node_modules/*",
    "vendor/*",
    ".venv/*",
)


class SandboxViolation(RuntimeError):
    """A change reached outside its fence."""


class WorkspacePolicy(BaseModel):
    """The paths one task may write, and the ones nothing may write."""

    task_id: str = ""
    allowed: list[str] = Field(default_factory=list)  # globs; empty = repo-wide
    denied: list[str] = Field(default_factory=list)
    reasons: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def for_task(
        cls,
        task: TaskUnit,
        placement: Optional[PlacementDecision] = None,
        forbidden: Iterable[ForbiddenZone] = (),
        extra_allowed: Iterable[str] = (),
    ) -> "WorkspacePolicy":
        allowed: list[str] = [p for p in task.artifacts if p]
        reasons: dict[str, str] = {}
        if placement:
            for path in (placement.target_path, placement.test_path):
                if path and path not in allowed:
                    allowed.append(path)
            # A module may need siblings: allow its directory, not the whole tree.
            for path in list(allowed):
                if "/" in path:
                    allowed.append(f"{path.rsplit('/', 1)[0]}/*")

        denied = list(HARD_DENY)
        for zone in forbidden:
            pattern = zone.path if zone.path not in {"", "<root>"} else "*"
            candidate = (
                pattern if any(ch in pattern for ch in "*?[") else f"{pattern.rstrip('/')}/*"
            )
            if zone.path == "<root>":
                candidate = "<root>"
            denied.append(candidate)
            reasons[candidate] = zone.reason

        allowed.extend(extra_allowed)
        return cls(
            task_id=task.id,
            allowed=sorted(set(a for a in allowed if a)),
            denied=sorted(set(denied)),
            reasons=reasons,
        )

    # ── Checking ──────────────────────────────────────────────────────────────

    def violation(self, path: str) -> str:
        """Why this path is not writable, or an empty string when it is."""
        candidate = _normalise(path)
        if not candidate:
            return "empty path"
        if ".." in Path(candidate).parts or candidate.startswith("/"):
            return "path escapes the repository"

        for pattern in self.denied:
            if pattern == "<root>":
                if "/" not in candidate:
                    return self.reasons.get(pattern, "the repository root is not writable")
                continue
            if fnmatch.fnmatch(candidate, pattern) or candidate.startswith(pattern.rstrip("*")):
                return self.reasons.get(pattern, f"denied by {pattern}")

        if not self.allowed:
            return ""
        for pattern in self.allowed:
            if candidate == pattern or fnmatch.fnmatch(candidate, pattern):
                return ""
        return f"outside the paths planned for {self.task_id or 'this task'}"

    def check(self, paths: Iterable[str]) -> list[str]:
        """Every violation among these paths, as human-readable lines."""
        return [f"{path}: {reason}" for path in paths if (reason := self.violation(path))]

    def enforce(self, paths: Iterable[str]) -> None:
        problems = self.check(paths)
        if problems:
            raise SandboxViolation("; ".join(problems[:5]))

    def describe(self) -> str:
        allowed = ", ".join(self.allowed[:4]) or "the whole repository"
        return f"may write {allowed}; {len(self.denied)} denied patterns"


def _normalise(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned
