"""The worker loop — a ticket comes off the queue and a run comes back.

This is what makes the system autonomous rather than interactive: a process
claims work, drives the pipeline, persists the run, and either completes the
item or hands it back for another attempt. It heartbeats while it works, so a
worker that dies does not strand a ticket, and it refuses to start a second run
for a ticket that already has one.

    worker = TicketWorker(pipeline_factory, store, queue, audit)
    worker.work_once("worker-1")     # claim, run, persist, complete
    worker.recover()                 # reclaim anything a dead worker was holding
"""

from __future__ import annotations

import socket
import time
from typing import Callable, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.execution.resilience import BudgetExceeded
from future_agents.sdd.models import Objective, RunState, Stage
from future_agents.sdd.pipeline import DeliveryPipeline
from future_agents.sdd.store.audit import AuditLog
from future_agents.sdd.store.queue import WorkItem, WorkQueue
from future_agents.sdd.store.run_store import RunStore

#: Built fresh per ticket so one run's state never leaks into the next.
PipelineFactory = Callable[[Objective], DeliveryPipeline]


class WorkOutcome(BaseModel):
    """What happened to one claimed ticket."""

    item_id: str = ""
    run_id: str = ""
    stage: str = ""
    accepted: bool = False
    awaiting_human: bool = False
    requeued: bool = False
    dead: bool = False
    error: str = ""
    seconds: float = 0.0
    notes: list[str] = Field(default_factory=list)

    @property
    def worked(self) -> bool:
        return bool(self.item_id)


class TicketWorker:
    """Claims tickets, runs them, and leaves a durable trail either way."""

    def __init__(
        self,
        pipeline_factory: PipelineFactory,
        store: RunStore,
        queue: WorkQueue,
        audit: Optional[AuditLog] = None,
        lease_seconds: int = 900,
    ) -> None:
        self.pipeline_factory = pipeline_factory
        self.store = store
        self.queue = queue
        self.audit = audit or AuditLog(store.root)
        self.lease_seconds = lease_seconds

    # ── One ticket ────────────────────────────────────────────────────────────

    def work_once(self, worker_id: str = "") -> WorkOutcome:
        """Claim the next ticket and drive it as far as it goes."""
        owner = worker_id or default_worker_id()
        item = self.queue.claim(owner, ttl_seconds=self.lease_seconds)
        if item is None:
            return WorkOutcome()

        self.audit.record(owner, "claimed", subject=item.id, detail=item.objective.statement[:120])
        started = time.perf_counter()

        existing = self.store.exists_for(item.external_key)
        if existing:
            self.queue.complete(item.id, run_id=existing)
            self.audit.record(owner, "deduplicated", subject=item.id, detail=f"run {existing}")
            return WorkOutcome(
                item_id=item.id,
                run_id=existing,
                notes=[f"ticket already handled by run {existing}"],
                seconds=time.perf_counter() - started,
            )

        try:
            state = self._run(item, owner)
        except BudgetExceeded as exc:
            return self._fail(item, owner, f"budget: {exc}", started)
        except Exception as exc:  # a crashed run must not take the worker with it
            return self._fail(item, owner, f"{type(exc).__name__}: {exc}", started)

        self.store.save(state, owner=owner)
        self.store.release(state.id, owner)
        outcome = WorkOutcome(
            item_id=item.id,
            run_id=state.id,
            stage=state.stage.value,
            accepted=bool(state.delivery and state.delivery.accepted),
            awaiting_human=state.awaiting_human,
            seconds=time.perf_counter() - started,
        )

        if state.stage is Stage.BLOCKED:
            self._fail(item, owner, self._last_reason(state), started)
            outcome.requeued = True
            outcome.error = self._last_reason(state)
            return outcome

        # A run waiting on a human is not a failure and must not burn attempts:
        # it stays associated with the ticket until the answers arrive.
        self.queue.complete(item.id, run_id=state.id)
        self.audit.record(
            owner,
            "delivered" if outcome.accepted else "paused",
            subject=state.id,
            detail=f"stage {state.stage.value}",
            accepted=outcome.accepted,
            awaiting_human=outcome.awaiting_human,
        )
        return outcome

    def work(
        self, worker_id: str = "", max_items: int = 10, idle_sleep: float = 0.0
    ) -> list[WorkOutcome]:
        """Drain up to `max_items`, stopping when the queue runs dry."""
        owner = worker_id or default_worker_id()
        outcomes: list[WorkOutcome] = []
        for _ in range(max(1, max_items)):
            outcome = self.work_once(owner)
            if not outcome.worked:
                if idle_sleep:
                    time.sleep(idle_sleep)
                break
            outcomes.append(outcome)
        return outcomes

    # ── Recovery ──────────────────────────────────────────────────────────────

    def recover(self, stale_after_seconds: float = 3600) -> list[str]:
        """Reclaim work a dead worker was holding; quarantine what keeps dying."""
        recovered: list[str] = []
        for item in self.queue.pending():
            if item.status == "claimed" and item.claimable:  # the lease has expired
                self.queue.fail(item.id, "worker lease expired")
                self.audit.record("watchdog", "reclaimed", subject=item.id, detail=item.owner)
                recovered.append(item.id)
        for record in self.store.stuck(stale_after_seconds):
            self.audit.record(
                "watchdog", "stalled", subject=record.run_id, detail=f"stage {record.stage}"
            )
            recovered.append(record.run_id)
        return recovered

    def resume(self, run_id: str, answers: dict[str, str], answered_by: str = "human") -> RunState:
        """Continue a run that stopped for a human, and persist the result."""
        state = self.store.load(run_id)
        pipeline = self.pipeline_factory(state.objective)
        state = pipeline.answer(state, answers, answered_by=answered_by)
        self.store.save(state)
        self.audit.record(
            f"human:{answered_by}", "answered", subject=run_id, detail=f"{len(answers)} answer(s)"
        )
        return state

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self, item: WorkItem, owner: str) -> RunState:
        pipeline = self.pipeline_factory(item.objective)
        state = pipeline.start(item.objective)
        state.owner = owner
        self.store.claim(state.id, owner, ttl_seconds=self.lease_seconds)
        self.queue.heartbeat(item.id, owner, ttl_seconds=self.lease_seconds)
        return state

    def _fail(self, item: WorkItem, owner: str, reason: str, started: float) -> WorkOutcome:
        updated = self.queue.fail(item.id, reason)
        dead = bool(updated and updated.status == "dead")
        self.audit.record(
            owner, "quarantined" if dead else "failed", subject=item.id, detail=reason[:200]
        )
        return WorkOutcome(
            item_id=item.id,
            error=reason,
            requeued=not dead,
            dead=dead,
            seconds=time.perf_counter() - started,
        )

    @staticmethod
    def _last_reason(state: RunState) -> str:
        return state.events[-1].message if state.events else "blocked"


def default_worker_id() -> str:
    """Host plus process — enough to tell two workers apart in the audit log."""
    import os

    return f"{socket.gethostname()}:{os.getpid()}"
