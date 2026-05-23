"""Worker Scheduler — manages and runs registered workers on their schedules."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from future_agents.workers.base_worker import BaseWorker, WorkerResult

logger = logging.getLogger(__name__)


class WorkerScheduler:
    """Runs a collection of workers, each in its own asyncio task.

    Workers are independent — one failure does not affect others.
    A small random jitter on startup prevents all workers from firing
    at the same instant.

    Usage::

        scheduler = WorkerScheduler()
        scheduler.register(CodeImprovementWorker(...))
        scheduler.register(PatternDiscoveryWorker(...))
        scheduler.register(AgentGathererWorker(...))

        await scheduler.start()      # launches all worker loops
        ...
        await scheduler.stop()       # cancels all tasks gracefully
    """

    def __init__(self) -> None:
        self._workers: dict[str, BaseWorker] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, worker: BaseWorker) -> None:
        """Add a worker.  Can be called before or after start()."""
        self._workers[worker.worker_id] = worker
        logger.info(
            "Registered worker %s (type=%s, interval=%ds)",
            worker.worker_id,
            worker.worker_type,
            worker.interval_seconds,
        )
        if self._running:
            self._launch_task(worker)

    def deregister(self, worker_id: str) -> None:
        """Remove a worker and cancel its task if running."""
        task = self._tasks.pop(worker_id, None)
        if task:
            task.cancel()
        self._workers.pop(worker_id, None)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise all workers and launch their loops."""
        self._running = True
        for worker in self._workers.values():
            await worker.on_start()
            self._launch_task(worker)
        logger.info("WorkerScheduler started with %d workers", len(self._workers))

    async def stop(self) -> None:
        """Cancel all worker tasks and call on_stop hooks."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        for worker in self._workers.values():
            await worker.on_stop()
        self._tasks.clear()
        logger.info("WorkerScheduler stopped")

    # ── Manual trigger ────────────────────────────────────────────────────────

    async def run_now(self, worker_id: str) -> WorkerResult | None:
        """Trigger one execution of a specific worker immediately."""
        worker = self._workers.get(worker_id)
        if not worker:
            logger.warning("run_now: worker not found: %s", worker_id)
            return None
        return await worker.execute()

    # ── Status ────────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "worker_count": len(self._workers),
            "workers": {wid: w.get_status() for wid, w in self._workers.items()},
        }

    # ── Private ───────────────────────────────────────────────────────────────

    def _launch_task(self, worker: BaseWorker) -> None:
        task = asyncio.create_task(
            self._worker_loop(worker),
            name=f"worker-{worker.worker_id}",
        )
        self._tasks[worker.worker_id] = task

    async def _worker_loop(self, worker: BaseWorker) -> None:
        """Run a worker repeatedly, sleeping between executions."""
        # Spread startup to avoid thundering-herd on initialisation
        jitter = random.uniform(0.5, min(15.0, worker.interval_seconds * 0.1))
        await asyncio.sleep(jitter)

        while self._running:
            await worker.execute()
            try:
                await asyncio.sleep(worker.interval_seconds)
            except asyncio.CancelledError:
                break
