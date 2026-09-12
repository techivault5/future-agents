"""Observability — the scope every feature carries, not a follow-up ticket.

The rule the whole package exists to enforce: **a feature is not designed until
you can say how you would know it is broken.** So the pipeline derives, from the
same spec the code comes from:

* **signals** — throughput, latency, errors and a span per component, with
  bounded labels;
* **objectives** — one per MUST requirement, its kind read from the acceptance
  criteria (a deadline makes it latency, a prohibition makes it correctness);
* **alerts** — multi-window burn rate, a fast page and a slow ticket, each
  naming its runbook section;
* **a runbook and a dashboard** — generated with the delivery, from the plan;
* **instrumentation tasks** — real units in the DAG, so telemetry is work that
  is scheduled, executed and verified rather than assumed.

The gates make it stick: the constitution rejects a plan whose MUST requirements
have no objective, and QA reports how much of the instrumentation actually ran.
None of it is a prompt asking a model to "remember monitoring".
"""

from __future__ import annotations

from future_agents.sdd.models import (
    Alert,
    Dashboard,
    ObservabilityPlan,
    ServiceLevelObjective,
    Signal,
    SignalKind,
)
from future_agents.sdd.observability.catalog import (
    OTEL_ENVIRONMENT,
    TelemetryStack,
    stack_summary,
    telemetry_for,
)
from future_agents.sdd.observability.planner import ObservabilityPlanner
from future_agents.sdd.observability.runbook import render_runbook

__all__ = [
    "OTEL_ENVIRONMENT",
    "Alert",
    "Dashboard",
    "ObservabilityPlan",
    "ObservabilityPlanner",
    "ServiceLevelObjective",
    "Signal",
    "SignalKind",
    "TelemetryStack",
    "render_runbook",
    "stack_summary",
    "telemetry_for",
]
