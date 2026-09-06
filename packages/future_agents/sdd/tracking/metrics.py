"""A metric per work item — and the question each one answers.

The rule: **no metric without a question, and no question without a source.** A
number that cannot say what decision it would change is a chart, and charts are
how dashboards fill up while nobody learns anything.

Four families, and they are not interchangeable:

* **delivery** — how the work went (cycle time, attempts, rework). Read from the
  run itself, so it costs nothing and cannot be gamed by the thing it measures.
* **quality** — did it actually work (criteria verified, blockers, coverage).
  Read from QA evidence, never from a claim.
* **reliability** — the objectives it now runs under, straight from the
  observability plan, so the issue and the alert cannot disagree.
* **product** — did the outcome the asker wanted move. This one usually cannot
  be bound automatically: the honest output is a named metric with an *unbound*
  source, so a human sees the gap instead of a fabricated proxy.
"""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.models import (
    Budget,
    MetricKind,
    MetricSet,
    MetricSpec,
    ObservabilityPlan,
    QAReport,
    RunState,
    WorkBreakdown,
    WorkItem,
    WorkItemKind,
)


class MetricPlanner:
    """Every tracked item gets numbers; the run fills in what it can."""

    def build(
        self,
        breakdown: WorkBreakdown,
        *,
        qa: Optional[QAReport] = None,
        observability: Optional[ObservabilityPlan] = None,
        state: Optional[RunState] = None,
    ) -> MetricSet:
        counter = _Counter()
        metrics = MetricSet()
        root = breakdown.root()

        for item in breakdown.items:
            metrics.specs.extend(self._delivery(item, counter, state))
            metrics.specs.extend(self._quality(item, counter, qa))
            metrics.specs.extend(self._reliability(item, counter, observability))
            metrics.specs.extend(self._product(item, counter))

        if root is not None:
            metrics.specs.extend(self._cost(root, counter, state))
        return metrics

    # ── Delivery ──────────────────────────────────────────────────────────────

    def _delivery(
        self, item: WorkItem, counter: "_Counter", state: Optional[RunState]
    ) -> list[MetricSpec]:
        specs = [
            MetricSpec(
                id=counter.next(),
                name="cycle time",
                kind=MetricKind.DELIVERY,
                question="How long did this take from ask to delivered?",
                work_item_id=item.id,
                requirement_ids=list(item.requirement_ids),
                source="run",
                query="delivery.created_at - objective.created_at",
                unit="s",
                direction="down",
                value=_cycle_seconds(state) if item.kind is WorkItemKind.EPIC else None,
            )
        ]
        if item.task_ids and state is not None:
            tasks = set(item.task_ids)
            attempts = sum(r.attempts for r in state.work_results if r.task_id in tasks)
            # One task retried twice and twenty tasks run once are both "20
            # attempts"; the epic needs the ratio, a leaf needs the count.
            if item.kind is WorkItemKind.EPIC:
                ran = sum(1 for r in state.work_results if r.task_id in tasks) or len(tasks)
                specs.append(
                    MetricSpec(
                        id=counter.next(),
                        name="rework rate",
                        kind=MetricKind.DELIVERY,
                        question="How many tries did the average task take?",
                        work_item_id=item.id,
                        source="run",
                        query="sum(attempts) ÷ tasks run",
                        unit="×",
                        direction="down",
                        target=1.0,
                        value=round(attempts / ran, 2) if ran else None,
                    )
                )
            else:
                specs.append(
                    MetricSpec(
                        id=counter.next(),
                        name="attempts",
                        kind=MetricKind.DELIVERY,
                        question=(
                            "Did this need re-running? Repeats point at a flaky step "
                            "or a bad brief."
                        ),
                        work_item_id=item.id,
                        source="run",
                        query="sum(work_result.attempts) for the item's tasks",
                        unit="",
                        direction="down",
                        target=1,
                        value=float(attempts) if attempts else None,
                    )
                )
        return specs

    # ── Quality ───────────────────────────────────────────────────────────────

    def _quality(
        self, item: WorkItem, counter: "_Counter", qa: Optional[QAReport]
    ) -> list[MetricSpec]:
        if not item.criterion_ids:
            return []
        verified = None
        if qa is not None:
            covered = [c for c in qa.checks if c.criterion_id in set(item.criterion_ids)]
            if covered:
                verified = round(sum(1 for c in covered if c.verified) / len(covered), 3)
        return [
            MetricSpec(
                id=counter.next(),
                name="criteria verified",
                kind=MetricKind.QUALITY,
                question="What share of this item's acceptance criteria is proved by evidence?",
                work_item_id=item.id,
                requirement_ids=list(item.requirement_ids),
                source="qa",
                query="verified checks ÷ checks, from passing evidence only",
                unit="",
                direction="up",
                target=1.0,
                value=verified,
            )
        ]

    # ── Reliability ───────────────────────────────────────────────────────────

    def _reliability(
        self,
        item: WorkItem,
        counter: "_Counter",
        observability: Optional[ObservabilityPlan],
    ) -> list[MetricSpec]:
        if observability is None or not item.slo_ids:
            return []
        specs: list[MetricSpec] = []
        for slo_id in item.slo_ids:
            slo = next((s for s in observability.slos if s.id == slo_id), None)
            if slo is None:
                continue
            signal = observability.signal(slo.signal_ids[0]) if slo.signal_ids else None
            specs.append(
                MetricSpec(
                    id=counter.next(),
                    name=f"{slo.kind} objective ({slo.id})",
                    kind=MetricKind.RELIABILITY,
                    question=f"Is {slo.sli} holding above the objective in production?",
                    work_item_id=item.id,
                    requirement_ids=[slo.requirement_id] if slo.requirement_id else [],
                    source="observability",
                    query=signal.query if signal and signal.query else f"burn_rate({slo.id}, 30d)",
                    unit="",
                    direction="up",
                    target=slo.objective,
                )
            )
        return specs

    # ── Product ───────────────────────────────────────────────────────────────

    def _product(self, item: WorkItem, counter: "_Counter") -> list[MetricSpec]:
        """The outcome the asker actually wanted, named even when unbound.

        Binding it needs a data source only the team has, so the metric is
        created with `source="unbound"`: visible, assignable, and impossible to
        mistake for something already being measured.
        """
        if not item.outcome or item.kind in (WorkItemKind.CHORE, WorkItemKind.DOCS):
            return []
        return [
            MetricSpec(
                id=counter.next(),
                name=_outcome_metric_name(item.outcome),
                kind=MetricKind.PRODUCT,
                question=f"Did this move the outcome that was asked for — {item.outcome}?",
                work_item_id=item.id,
                requirement_ids=list(item.requirement_ids),
                source="unbound",
                query="",
                direction="up",
            )
        ]

    # ── Cost ──────────────────────────────────────────────────────────────────

    def _cost(
        self, root: WorkItem, counter: "_Counter", state: Optional[RunState]
    ) -> list[MetricSpec]:
        budget: Optional[Budget] = state.budget if state else None
        return [
            MetricSpec(
                id=counter.next(),
                name="engine calls",
                kind=MetricKind.COST,
                question="What did delivering this cost in model calls?",
                work_item_id=root.id,
                source="run",
                query="budget.spent_engine_calls",
                direction="down",
                target=float(budget.max_engine_calls) if budget else None,
                value=float(budget.spent_engine_calls) if budget else None,
            ),
            MetricSpec(
                id=counter.next(),
                name="run seconds",
                kind=MetricKind.COST,
                question="How much machine time did it take?",
                work_item_id=root.id,
                source="run",
                query="budget.spent_seconds",
                unit="s",
                direction="down",
                target=float(budget.max_seconds) if budget else None,
                value=float(budget.spent_seconds) if budget else None,
            ),
        ]


def refresh_values(metrics: MetricSet, state: RunState) -> MetricSet:
    """Re-read what the run can answer. Anything else keeps its last value."""
    qa = state.qa
    for metric in metrics.specs:
        if metric.source == "run" and metric.name == "cycle time":
            metric.value = _cycle_seconds(state) or metric.value
        elif metric.source == "run" and metric.name == "engine calls":
            metric.value = float(state.budget.spent_engine_calls)
        elif metric.source == "run" and metric.name == "run seconds":
            metric.value = float(state.budget.spent_seconds)
        elif metric.source == "qa" and qa is not None:
            metric.value = qa.coverage if metric.value is None else metric.value
    return metrics


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cycle_seconds(state: Optional[RunState]) -> Optional[float]:
    if state is None or state.delivery is None:
        return None
    started = state.objective.created_at
    finished = state.delivery.created_at
    if started.tzinfo is None or finished.tzinfo is None:
        return None
    return round(max(0.0, (finished - started).total_seconds()), 3)


def _outcome_metric_name(outcome: str) -> str:
    """A readable name from the "so that" clause, not a slugified sentence."""
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9-]+", outcome.lower())][:6]
    return " ".join(words) or "outcome"


class _Counter:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"M-{self._n:03d}"
