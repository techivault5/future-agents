"""Base worker — abstract foundation for all scheduled workers."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class WorkerStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class WorkerResult:
    """Outcome of one worker execution cycle."""

    worker_id: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseWorker(ABC):
    """Abstract base for all scheduled in-process workers.

    Each concrete worker implements ``run()`` with its domain logic.
    The scheduler calls ``execute()`` which wraps ``run()`` with timing,
    status tracking, and error isolation.
    """

    def __init__(
        self,
        worker_id: str | None = None,
        interval_seconds: int = 300,
        enabled: bool = True,
    ) -> None:
        self.worker_id = worker_id or f"{self.worker_type}_{uuid4().hex[:8]}"
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self.status = WorkerStatus.IDLE
        self.run_count = 0
        self.error_count = 0
        self.last_run: datetime | None = None
        self.last_result: WorkerResult | None = None

    @property
    @abstractmethod
    def worker_type(self) -> str:
        """Unique type identifier for this worker class."""
        ...

    @property
    def next_run(self) -> datetime | None:
        if self.last_run is None:
            return datetime.now(timezone.utc)
        return self.last_run + timedelta(seconds=self.interval_seconds)

    @property
    def seconds_until_next_run(self) -> float:
        if self.next_run is None:
            return 0.0
        delta = (self.next_run - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)

    @abstractmethod
    async def run(self) -> WorkerResult:
        """Core work logic — implement in subclasses."""
        ...

    async def on_start(self) -> None:
        """Called once before the worker loop begins."""

    async def on_stop(self) -> None:
        """Called when the worker loop is stopping."""

    async def execute(self) -> WorkerResult:
        """Run one cycle with timing, status tracking, and error isolation."""
        if not self.enabled:
            return WorkerResult(
                worker_id=self.worker_id, success=False, errors=["Worker is disabled"]
            )

        self.status = WorkerStatus.RUNNING
        start = datetime.now(timezone.utc)
        try:
            result = await self.run()
        except Exception as exc:
            logger.exception("Worker %s raised an exception", self.worker_id)
            self.error_count += 1
            self.status = WorkerStatus.ERROR
            return WorkerResult(worker_id=self.worker_id, success=False, errors=[str(exc)])

        end = datetime.now(timezone.utc)
        result.duration_ms = (end - start).total_seconds() * 1000

        self.run_count += 1
        self.last_run = start
        self.last_result = result
        self.status = WorkerStatus.IDLE if result.success else WorkerStatus.ERROR

        logger.info(
            "Worker %s finished (success=%s, %.1f ms)",
            self.worker_id,
            result.success,
            result.duration_ms,
        )
        return result

    def get_status(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "status": self.status.value,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "run_count": self.run_count,
            "error_count": self.error_count,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }
