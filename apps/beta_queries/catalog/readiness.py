"""Is this datasource ready to answer questions yet?

A database connected at 10am is useless until 5am tomorrow if the only crawl
is the nightly one. So registration starts a crawl immediately, and the catalog
becomes **progressively** useful rather than all-or-nothing:

    structure      table and column names — routing and identifier resolution
                   already work. Minutes.
    joins          multi-table questions work.
    values         "India" resolves to a literal rather than a guess.
    descriptions   best routing on names nobody could read. Slowest.

Each phase that lands unlocks a class of question, so the honest answer to "can
you answer this yet" is per-phase, not a single boolean.

Someone who asks while a sync is running gets one of three things, chosen by
how much work is actually left rather than by guesswork:

    wait      structure is done and the rest is close — narrate it and carry on
    partial   usable but incomplete — answer, and say so with a chip
    queue     not usable yet — take the question, and notify when it is

Blocking silently is the one option that is never right: the user cannot tell
a slow system from a broken one.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

# Ordered: each unlocks more than the last.
PHASES = ("structure", "joins", "values", "descriptions")

# What a phase makes possible, for the chip shown alongside a partial answer.
UNLOCKS = {
    "structure": "table and column names",
    "joins": "questions spanning more than one table",
    "values": "matching words in your question to values in the data",
    "descriptions": "finding tables whose names don't say what they hold",
}

READY = "ready"
PARTIAL = "partial"
SYNCING = "syncing"
FAILED = "failed"
UNKNOWN = "unknown"

# How long a caller will wait for a sync before we stop narrating and either
# answer partially or queue. Well inside a chat's patience, and outside the
# 2s budget on purpose: this is not the budgeted path.
DEFAULT_WAIT_BUDGET_SECONDS = 8.0

# Below this, the observed rate is noise rather than a rate.
MIN_ETA_SAMPLE_SECONDS = 2.0


@dataclass
class Readiness:
    datasource: str
    status: str = UNKNOWN
    phase: str = ""
    completed: list[str] = field(default_factory=list)
    tables_seen: int = 0
    tables_total: int = 0
    started_at: float = 0.0
    updated_at: float = 0.0
    error: str = ""

    @property
    def pct(self) -> int:
        if not self.tables_total:
            return 0
        return min(100, int(100 * self.tables_seen / self.tables_total))

    @property
    def can_route(self) -> bool:
        """Routing and identifier resolution need names and nothing more."""
        return "structure" in self.completed

    @property
    def can_join(self) -> bool:
        return "joins" in self.completed

    @property
    def elapsed(self) -> float:
        return max(0.0, (self.updated_at or time.time()) - self.started_at)

    def eta_seconds(self) -> float | None:
        """Extrapolated from the rate so far. None when there is nothing to go on.

        A rate measured over the first fraction of a second is not a rate —
        it extrapolates to "done already" and would tell a caller to wait for
        something that has barely started. Below the minimum sample the honest
        answer is "I don't know yet", which routes to queue rather than wait.
        """
        if self.status in (READY, FAILED) or not self.tables_seen or not self.tables_total:
            return None
        if self.elapsed < MIN_ETA_SAMPLE_SECONDS:
            return None
        rate = self.tables_seen / self.elapsed
        if rate <= 0:
            return None
        return max(0.0, (self.tables_total - self.tables_seen) / rate)

    def missing(self) -> list[str]:
        return [p for p in PHASES if p not in self.completed]

    def describe(self) -> str:
        if self.status == READY:
            return f"{self.datasource} is ready"
        if self.status == FAILED:
            return f"{self.datasource} could not be read: {self.error}"
        if self.status == UNKNOWN:
            return f"{self.datasource} has not been read yet"
        return (
            f"reading {self.datasource} — {self.phase}, "
            f"{self.tables_seen} of ~{self.tables_total or '?'} tables"
        )


class ReadinessStore:
    """Shared through the KV, so every process gives the same answer."""

    def __init__(self, kv: Any, ttl_seconds: int = 7 * 24 * 3600) -> None:
        self.kv = kv
        self.ttl = ttl_seconds

    @staticmethod
    def _key(datasource: str) -> str:
        return f"bq:readiness:{datasource}"

    def get(self, datasource: str) -> Readiness:
        raw = self.kv.get(self._key(datasource))
        if not raw:
            return Readiness(datasource=datasource)
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return Readiness(datasource=datasource)
        known = set(Readiness.__dataclass_fields__)
        return Readiness(**{k: v for k, v in data.items() if k in known})

    def put(self, readiness: Readiness) -> Readiness:
        readiness.updated_at = time.time()
        self.kv.set(self._key(readiness.datasource), json.dumps(asdict(readiness)), ex=self.ttl)
        return readiness

    # ── the crawl reports in through these ──────────────────────────────────

    def begin(self, datasource: str, tables_total: int = 0) -> Readiness:
        return self.put(
            Readiness(
                datasource=datasource,
                status=SYNCING,
                phase="structure",
                tables_total=tables_total,
                started_at=time.time(),
            )
        )

    def advance(self, datasource: str, phase: str, seen: int = 0, total: int = 0) -> Readiness:
        state = self.get(datasource)
        state.status = SYNCING if state.status == UNKNOWN else state.status
        state.phase = phase
        if seen:
            state.tables_seen = seen
        if total:
            state.tables_total = total
        return self.put(state)

    def completed_phase(self, datasource: str, phase: str) -> Readiness:
        state = self.get(datasource)
        if phase not in state.completed:
            state.completed.append(phase)
        # Structure alone is enough to be useful, which is the whole reason the
        # phases are ordered the way they are.
        state.status = READY if set(PHASES) <= set(state.completed) else PARTIAL
        return self.put(state)

    def failed(self, datasource: str, error: str) -> Readiness:
        state = self.get(datasource)
        state.status = FAILED
        state.error = error
        return self.put(state)


@dataclass
class Decision:
    action: str  # ready | wait | partial | queue | failed
    readiness: Readiness
    reason: str = ""
    caveat: str = ""
    eta_seconds: float | None = None

    @property
    def can_answer(self) -> bool:
        return self.action in ("ready", "wait", "partial")


def decide(
    readiness: Readiness,
    wait_budget: float = DEFAULT_WAIT_BUDGET_SECONDS,
    needs_joins: bool = False,
) -> Decision:
    """What to do about a question asked against this datasource, right now."""
    if readiness.status == READY:
        return Decision("ready", readiness)

    if readiness.status == FAILED:
        return Decision("failed", readiness, reason=readiness.error)

    if readiness.status == UNKNOWN:
        return Decision("queue", readiness, reason="that database has not been read yet")

    eta = readiness.eta_seconds()

    if not readiness.can_route:
        # Without names there is nothing to route on, and guessing is worse
        # than waiting. If it is nearly there, wait; otherwise take the
        # question and come back to them.
        if eta is not None and eta <= wait_budget:
            return Decision("wait", readiness, reason="names are nearly ready", eta_seconds=eta)
        return Decision("queue", readiness, reason="still reading the table names", eta_seconds=eta)

    if needs_joins and not readiness.can_join:
        if eta is not None and eta <= wait_budget:
            return Decision("wait", readiness, reason="relationships nearly ready", eta_seconds=eta)
        return Decision(
            "partial",
            readiness,
            reason="relationships are not mapped yet",
            caveat=f"I'm still mapping how {readiness.datasource}'s tables relate, "
            "so I've answered from one table only.",
            eta_seconds=eta,
        )

    missing = [UNLOCKS[p] for p in readiness.missing() if p in UNLOCKS]
    return Decision(
        "partial",
        readiness,
        reason="usable but incomplete",
        caveat=(
            f"I'm still reading {readiness.datasource} — I answered from what I "
            f"have. Not finished yet: {', '.join(missing)}."
        )
        if missing
        else "",
        eta_seconds=eta,
    )
