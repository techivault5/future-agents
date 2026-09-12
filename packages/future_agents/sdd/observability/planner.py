"""Derive the observability plan from the spec — the same way code is derived.

The rule this module exists to enforce: **a feature is not designed until you can
say how you would know it is broken.** So every plan carries signals, objectives,
alerts and a runbook, derived deterministically from the requirements rather than
left to whoever remembers.

How each piece is decided:

* **Signals** — every component earns throughput, latency and error instruments
  plus a span, because those three answer "is it running, is it slow, is it
  failing" and nothing cheaper does. Labels are bounded and screened against the
  forbidden list: unbounded cardinality is the classic way an observability bill
  becomes an incident of its own.
* **Objectives** — each MUST requirement earns one, and its *kind* is read from
  the acceptance criteria: a criterion that mentions a deadline becomes latency,
  one that mentions freshness becomes freshness, one phrased as a prohibition
  becomes correctness, and everything else is availability.
* **Alerts** — multi-window burn rate, not thresholds. A fast burn pages, a slow
  burn opens a ticket. Both name the runbook, because an alert with no next step
  is a siren.
* **Gaps are recorded, not hidden.** Anything that could not be derived — a
  requirement with no measurable criterion, a component with no home in the repo
  — lands in `gaps` and reaches the plan as a risk.
"""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.config import ObservabilityConfig
from future_agents.sdd.models import (
    Alert,
    Component,
    Dashboard,
    ObservabilityPlan,
    Priority,
    ServiceLevelObjective,
    Signal,
    SignalKind,
    Spec,
)
from future_agents.sdd.observability.catalog import stack_summary
from future_agents.sdd.repos.languages import Toolchain

#: "within 800ms", "under 2 seconds", "in less than 5 minutes"
_LATENCY = re.compile(
    # Deadlines are phrased half a dozen ways, including as prohibitions
    # ("must not take more than 30 seconds") — all of them are one promise.
    r"\b(?:within|under|below|less than|at most|faster than|"
    r"(?:no|not)(?:\s+\w+){0,2}\s+(?:more than|longer than|exceed(?:ing)?))\s+"
    r"(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?)\b",
    re.IGNORECASE,
)

_FRESHNESS = re.compile(
    r"\b(nightly|daily|hourly|weekly|every \d+ (?:minutes?|hours?)|up[- ]to[- ]date|"
    r"refreshed|stale|lag)\b",
    re.IGNORECASE,
)

_CORRECTNESS = re.compile(
    r"\b(must not|never|no duplicate|exactly once|idempotent|consistent|reconcile|"
    r"match(?:es)?|balance|accurate)\b",
    re.IGNORECASE,
)

_SATURATION = re.compile(
    r"\b(queue|backlog|concurren|throughput|rate limit|capacity|scale|batch)\b",
    re.IGNORECASE,
)

#: What each objective kind actually measures, in one line an on-call reads.
_SLI = {
    "latency": "share of requests served inside the deadline",
    "availability": "share of requests that succeed",
    "correctness": "share of records that reconcile",
    "freshness": "share of intervals where data arrived on time",
    "saturation": "share of time the queue stayed inside its ceiling",
}

_UNIT_MS = {
    "ms": 1,
    "millisecond": 1,
    "milliseconds": 1,
    "s": 1000,
    "sec": 1000,
    "secs": 1000,
    "second": 1000,
    "seconds": 1000,
    "m": 60_000,
    "min": 60_000,
    "mins": 60_000,
    "minute": 60_000,
    "minutes": 60_000,
}


class ObservabilityPlanner:
    """Spec + components + toolchain → the plan for watching what gets built."""

    def __init__(
        self,
        config: Optional[ObservabilityConfig] = None,
        toolchain: Optional[Toolchain] = None,
    ) -> None:
        self.config = config or ObservabilityConfig()
        self.toolchain = toolchain

    def build(self, spec: Spec, components: list[Component]) -> ObservabilityPlan:
        cfg = self.config
        plan = ObservabilityPlan(
            telemetry_stack=stack_summary(
                self.toolchain.language if self.toolchain else None,
                self.toolchain.display_name if self.toolchain else "",
            ),
            runbook_path=f"{cfg.runbook_dir}/{_slug(spec.title)}.md",
        )

        counter = _Counter()
        for component in components:
            plan.signals.extend(self._component_signals(component, counter))
            plan.trace_spans.append(f"{_snake(component.name)}.handle")

        for requirement in spec.requirements:
            if requirement.priority is not Priority.MUST and cfg.require_slo_for_must:
                continue
            objectives = self._objectives(spec, requirement.id, counter, plan)
            if not objectives:
                plan.gaps.append(
                    f"{requirement.id} has no measurable acceptance criterion — "
                    "no objective could be derived from it"
                )
                continue
            plan.slos.extend(objectives)
            for slo in objectives:
                plan.alerts.extend(self._alerts(slo, counter, plan.runbook_path))

        plan.log_fields = self._log_fields(spec)
        plan.redactions = self._redactions(spec)
        plan.health_checks = self._health_checks(components)
        plan.dashboards = [self._dashboard(spec, plan)]
        plan.gaps.extend(self._cardinality_gaps(plan))
        if not components:
            plan.gaps.append("no components to instrument — the plan carries no code")
        return plan

    # ── Signals ───────────────────────────────────────────────────────────────

    def _component_signals(self, component: Component, counter: "_Counter") -> list[Signal]:
        name = _snake(component.name)
        labels = self._labels(["outcome", "component"])
        where = component.target_path
        return [
            Signal(
                id=counter.signal(),
                name=f"{name}_requests_total",
                kind=SignalKind.METRIC,
                instrument="counter",
                component=component.name,
                requirement_ids=list(component.requirement_ids),
                description=f"Work handled by {component.name} — the denominator of every ratio",
                unit="1",
                labels=labels,
                emitted_from=where,
                query=f"sum(rate({name}_requests_total[5m]))",
            ),
            Signal(
                id=counter.signal(),
                name=f"{name}_errors_total",
                kind=SignalKind.METRIC,
                instrument="counter",
                component=component.name,
                requirement_ids=list(component.requirement_ids),
                description=f"Failures in {component.name}, by cause class",
                unit="1",
                labels=self._labels(["reason", "component"]),
                emitted_from=where,
                query=f"sum(rate({name}_errors_total[5m]))",
            ),
            Signal(
                id=counter.signal(),
                name=f"{name}_duration_seconds",
                kind=SignalKind.METRIC,
                instrument="histogram",
                component=component.name,
                requirement_ids=list(component.requirement_ids),
                description=f"How long {component.name} takes, as a distribution not a mean",
                unit="s",
                labels=labels,
                emitted_from=where,
                query=(
                    "histogram_quantile(0.95, sum by (le) "
                    f"(rate({name}_duration_seconds_bucket[5m])))"
                ),
            ),
            Signal(
                id=counter.signal(),
                name=f"{name}.handle",
                kind=SignalKind.TRACE,
                instrument="span",
                component=component.name,
                requirement_ids=list(component.requirement_ids),
                description=(
                    f"One span per unit of work in {component.name}, carrying the "
                    "correlation id so a slow request can be followed end to end"
                ),
                emitted_from=where,
            ),
        ]

    def _labels(self, wanted: list[str]) -> list[str]:
        """Bounded, screened labels. Cardinality is a design decision here."""
        allowed = [label for label in wanted if label not in self.config.forbidden_labels]
        return allowed[: self.config.max_labels_per_metric]

    # ── Objectives ────────────────────────────────────────────────────────────

    def _objectives(
        self,
        spec: Spec,
        requirement_id: str,
        counter: "_Counter",
        plan: ObservabilityPlan,
    ) -> list[ServiceLevelObjective]:
        """The objectives one requirement earns — usually one, at most two.

        A requirement that promises both a deadline and a guarantee ("recorded
        within 2 seconds, and never double-counted") is making two different
        promises, and one number cannot say whether both are kept. Fast and
        wrong still reads as green on a latency objective.
        """
        requirement = spec.requirement(requirement_id)
        if requirement is None or not requirement.acceptance_criteria:
            return []

        # The requirement's own words decide first. Criteria are shared prose and
        # often mention a deadline belonging to a sibling requirement, which
        # would otherwise make every objective a latency objective.
        kinds = self._classify(requirement.statement)
        if not kinds:
            kinds = self._classify(" ".join(ac.render() for ac in requirement.acceptance_criteria))
        if not kinds:
            kinds = [("availability", None)]

        signals = self._signals_for_requirement(plan, requirement_id)
        return [
            ServiceLevelObjective(
                id=counter.slo(),
                requirement_id=requirement_id,
                kind=kind,
                statement=requirement.statement,
                sli=_SLI[kind],
                signal_ids=[s.id for s in signals],
                objective=self.config.default_availability,
                window_days=self.config.window_days,
                threshold_ms=threshold_ms,
            )
            for kind, threshold_ms in kinds[:2]
        ]

    def _classify(self, blob: str) -> list[tuple[str, Optional[int]]]:
        """Every promise the text makes, strongest evidence first.

        A numeric deadline is the least ambiguous thing prose can carry, so it
        leads; a prohibition or a reconciliation claim is a separate promise
        rather than a competing reading of the same one.
        """
        found: list[tuple[str, Optional[int]]] = []
        latency = _LATENCY.search(blob)
        if latency:
            found.append(("latency", _to_ms(latency.group(1), latency.group(2))))
        correctness = _CORRECTNESS.search(blob)
        # "must not exceed 2 seconds" is a deadline wearing a prohibition's
        # words, so a correctness phrase that sits right on top of the latency
        # phrase is the same promise, not a second one.
        if correctness and not (latency and abs(correctness.start() - latency.start()) < 16):
            found.append(("correctness", None))
        # Freshness ranks below correctness: late data is recoverable, wrong
        # data is not, and only two objectives per requirement are kept.
        if _FRESHNESS.search(blob):
            found.append(("freshness", None))
        if _SATURATION.search(blob):
            found.append(("saturation", None))
        return found

    @staticmethod
    def _signals_for_requirement(plan: ObservabilityPlan, requirement_id: str) -> list[Signal]:
        return [s for s in plan.signals if requirement_id in s.requirement_ids]

    # ── Alerts ────────────────────────────────────────────────────────────────

    def _alerts(
        self,
        slo: ServiceLevelObjective,
        counter: "_Counter",
        runbook: str,
    ) -> list[Alert]:
        """Two windows: burn it fast and someone wakes; burn it slowly and it queues."""
        cfg = self.config
        return [
            Alert(
                id=counter.alert(),
                name=f"{slo.id} fast burn",
                slo_id=slo.id,
                signal_ids=list(slo.signal_ids),
                severity="page",
                condition=(
                    f"burn_rate({slo.id}, {cfg.fast_burn_window}) > {cfg.fast_burn_rate} "
                    f"— {slo.sli} failing far faster than the budget allows"
                ),
                burn_rate=cfg.fast_burn_rate,
                window=cfg.fast_burn_window,
                for_minutes=5,
                channel=cfg.page_channel,
                runbook=f"{runbook}#{slo.id.lower()}",
            ),
            Alert(
                id=counter.alert(),
                name=f"{slo.id} slow burn",
                slo_id=slo.id,
                signal_ids=list(slo.signal_ids),
                severity="ticket",
                condition=(
                    f"burn_rate({slo.id}, {cfg.slow_burn_window}) > {cfg.slow_burn_rate} "
                    f"— {slo.sli} degrading steadily"
                ),
                burn_rate=cfg.slow_burn_rate,
                window=cfg.slow_burn_window,
                for_minutes=30,
                channel=cfg.ticket_channel,
                runbook=f"{runbook}#{slo.id.lower()}",
            ),
        ]

    # ── Context ───────────────────────────────────────────────────────────────

    def _log_fields(self, spec: Spec) -> list[str]:
        """Structured fields every log line carries, so logs join to traces."""
        fields = ["timestamp", "level", "service", "trace_id", "span_id", "correlation_id"]
        fields.extend(f"requirement_id={r.id}" for r in spec.requirements[:3])
        return fields

    def _redactions(self, spec: Spec) -> list[str]:
        """Fields that must never reach a log line — the default list plus context."""
        out = list(self.config.redact_fields)
        blob = f"{spec.title} {spec.summary}".lower()
        for term, extra in (
            ("payment", ["card_number", "cvv"]),
            ("card", ["card_number", "cvv"]),
            ("pii", ["name", "address", "date_of_birth"]),
            ("health", ["diagnosis", "patient_id"]),
            ("phi", ["diagnosis", "patient_id"]),
        ):
            if term in blob:
                out.extend(extra)
        return sorted(dict.fromkeys(out))

    def _health_checks(self, components: list[Component]) -> list[str]:
        if not components:
            return []
        checks = ["GET /healthz — process is up and its dependencies answer"]
        checks.append("GET /readyz — dependencies (db, queue, upstreams) reachable before traffic")
        if self.toolchain and self.toolchain.test:
            checks.append(f"post-deploy smoke: {self.toolchain.test}")
        return checks

    def _dashboard(self, spec: Spec, plan: ObservabilityPlan) -> Dashboard:
        panels = [f"{slo.id}: {slo.sli} vs objective, with error budget burn" for slo in plan.slos]
        panels.extend(
            f"{component}: throughput, p95 latency, error rate"
            for component in sorted({s.component for s in plan.signals if s.component})
        )
        panels.append("Saturation: queue depth, concurrency, dependency latency")
        return Dashboard(
            name=f"{spec.title} — service health",
            path=f"{self.config.dashboard_dir}/{_slug(spec.title)}.json",
            audience="on-call",
            panels=panels,
        )

    def _cardinality_gaps(self, plan: ObservabilityPlan) -> list[str]:
        gaps: list[str] = []
        for signal in plan.signals:
            over = [label for label in signal.labels if label in self.config.forbidden_labels]
            if over:
                gaps.append(f"{signal.id} carries unbounded label(s): {', '.join(over)}")
            if len(signal.labels) > self.config.max_labels_per_metric:
                gaps.append(
                    f"{signal.id} has {len(signal.labels)} labels, over the "
                    f"{self.config.max_labels_per_metric} budget"
                )
        return gaps


class _Counter:
    """Stable, readable ids: OBS-001, SLO-001, ALERT-001."""

    def __init__(self) -> None:
        self._signals = 0
        self._slos = 0
        self._alerts = 0

    def signal(self) -> str:
        self._signals += 1
        return f"OBS-{self._signals:03d}"

    def slo(self) -> str:
        self._slos += 1
        return f"SLO-{self._slos:03d}"

    def alert(self) -> str:
        self._alerts += 1
        return f"ALERT-{self._alerts:03d}"


def _to_ms(value: str, unit: str) -> int:
    return int(float(value) * _UNIT_MS.get(unit.lower(), 1000))


def _snake(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_") or "component"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower())[:48].strip("-") or "feature"
