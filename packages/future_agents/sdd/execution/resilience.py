"""Resilience — the difference between a system that survives and one that doesn't.

Four small mechanisms, each doing one job:

* `retry` — transient failures get another go, with backoff and a cap.
* `CircuitBreaker` — a dependency that keeps failing stops being called.
* `BudgetGuard` — time, tasks, attempts and engine calls have hard ceilings.
* `LoopDetector` — an agent repeating the same failing action is stopped.

None of them hide a failure: every one of them records what it did.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, TypeVar

from pydantic import BaseModel, Field

from future_agents.sdd.models import Budget, Evidence

T = TypeVar("T")


class BudgetExceeded(RuntimeError):
    """A hard ceiling was reached. The run stops and says which one."""


class CircuitOpen(RuntimeError):
    """The dependency is failing; calls are refused until it cools down."""


def retry(
    fn: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
    on_attempt: Optional[Callable[[int, BaseException], None]] = None,
) -> T:
    """Exponential backoff. The last failure is raised, never swallowed."""
    last: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return fn()
        except retry_on as exc:
            last = exc
            if on_attempt:
                on_attempt(attempt, exc)
            if attempt >= attempts:
                break
            sleep(min(base_delay * (2 ** (attempt - 1)), max_delay))
    assert last is not None
    raise last


class CircuitBreaker(BaseModel):
    """Closed → open after N failures → half-open after the cooldown."""

    name: str = "dependency"
    threshold: int = 3
    cooldown_seconds: float = 60.0
    failures: int = 0
    opened_at: Optional[datetime] = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        elapsed = (datetime.now(timezone.utc) - self.opened_at).total_seconds()
        return "half-open" if elapsed >= self.cooldown_seconds else "open"

    def before(self) -> None:
        if self.state == "open":
            raise CircuitOpen(f"{self.name} is unavailable (cooling down)")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = datetime.now(timezone.utc)

    def call(self, fn: Callable[[], T]) -> T:
        self.before()
        try:
            result = fn()
        except Exception:
            self.failure()
            raise
        self.success()
        return result

    def reopen_at(self) -> Optional[datetime]:
        if self.opened_at is None:
            return None
        return self.opened_at + timedelta(seconds=self.cooldown_seconds)


class BudgetGuard:
    """Charges a budget as work happens, and stops the run when it runs out."""

    def __init__(self, budget: Optional[Budget] = None) -> None:
        self.budget = budget or Budget()
        self._started = time.monotonic()

    def tick(self) -> None:
        """Update elapsed time and raise if any ceiling has been crossed."""
        self.budget.spent_seconds = time.monotonic() - self._started
        breached = self.budget.exhausted()
        if breached:
            raise BudgetExceeded(breached)

    def charge_task(self, attempts: int = 1) -> None:
        self.budget.charge(tasks=1, attempts=attempts)
        self.tick()

    def charge_engine_call(self, calls: int = 1) -> None:
        self.budget.charge(engine_calls=calls)
        self.tick()

    def remaining(self) -> dict[str, float]:
        budget = self.budget
        return {
            "seconds": max(0.0, budget.max_seconds - budget.spent_seconds),
            "tasks": max(0, budget.max_tasks - budget.spent_tasks),
            "engine_calls": max(0, budget.max_engine_calls - budget.spent_engine_calls),
        }


class LoopDetector(BaseModel):
    """Stops an agent that keeps doing the identical failing thing."""

    limit: int = 3
    seen: dict[str, int] = Field(default_factory=dict)

    def signature(self, evidence: Evidence) -> str:
        return f"{evidence.command}|{evidence.exit_code}|{evidence.output_digest}"

    def observe(self, evidence: Evidence) -> bool:
        """True when this exact failure has now happened too many times."""
        if evidence.passed:
            return False
        key = self.signature(evidence)
        self.seen[key] = self.seen.get(key, 0) + 1
        return self.seen[key] >= self.limit

    def report(self) -> list[str]:
        counts = Counter(self.seen)
        return [f"{count}× {key}" for key, count in counts.most_common(3) if count > 1]
