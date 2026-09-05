"""The runbook — what the person woken at 3am reads.

Every alert this system creates names a runbook anchor, so the runbook has to
exist and has to answer the only question that matters at that hour: *what do I
do now?* It is generated from the same plan the alerts are, which is what keeps
the two from drifting: rename an objective and its section moves with it.

Deliberately short. A runbook nobody finishes reading during an incident is
decoration.
"""

from __future__ import annotations

from typing import Optional

from future_agents.sdd.models import ObservabilityPlan, Spec


def render_runbook(plan: ObservabilityPlan, spec: Optional[Spec] = None) -> str:
    title = spec.title if spec else "Service"
    lines: list[str] = [
        f"# Runbook — {title}",
        "",
        "Generated with the delivery. Every alert links to a section here by id.",
        "",
        f"- **Telemetry:** {plan.telemetry_stack or 'not set'}",
        f"- **Dashboards:** {', '.join(d.path for d in plan.dashboards) or 'none'}",
        f"- **Health:** {'; '.join(plan.health_checks) or 'none defined'}",
        "",
        "## First five minutes",
        "",
        "1. Confirm the blast radius on the dashboard: is one component or everything?",
        "2. Check the error budget burn — a fast burn is an outage, a slow burn is a trend.",
        "3. Compare against the last deploy: if it correlates, roll back before debugging.",
        "4. Follow one failing trace end to end; the failing span names the dependency.",
        "5. If the cause is not obvious in five minutes, escalate rather than dig alone.",
        "",
    ]

    if plan.slos:
        lines.append("## Objectives and what to do when they burn")
        lines.append("")
    for slo in plan.slos:
        alerts = plan.alerts_for(slo.id)
        lines.extend(
            [
                f"### {slo.id.lower()} — {slo.kind}",
                "",
                f"- **Objective:** {slo.render()}",
                f"- **Measures:** {slo.statement or '—'}",
                f"- **Signals:** {', '.join(slo.signal_ids) or 'none'}",
                f"- **Error budget:** {slo.error_budget:.4%} of events over {slo.window_days} days",
            ]
        )
        for alert in alerts:
            lines.append(
                f"- **{alert.severity.upper()}** `{alert.name}` — {alert.condition} "
                f"→ {alert.channel}"
            )
        lines.extend(
            [
                "",
                _diagnosis_for(slo.kind),
                "",
            ]
        )

    if plan.signals:
        lines.extend(
            ["## Signals", "", "| Id | Signal | Instrument | Read it with |", "|---|---|---|---|"]
        )
        for signal in plan.signals:
            lines.append(
                f"| {signal.id} | `{signal.name}` | {signal.instrument} | "
                f"`{signal.query or 'trace search'}` |"
            )
        lines.append("")

    if plan.redactions:
        lines.extend(
            [
                "## Never log",
                "",
                ", ".join(f"`{field}`" for field in plan.redactions),
                "",
                "If one of these appears in a log line, treat it as an incident of its own:",
                "rotate what leaked, then fix the emitter.",
                "",
            ]
        )

    if plan.gaps:
        lines.extend(["## Known blind spots", ""])
        lines.extend(f"- {gap}" for gap in plan.gaps)
        lines.append("")

    return "\n".join(lines)


def _diagnosis_for(kind: str) -> str:
    """The first thing worth checking, per objective kind."""
    return {
        "latency": (
            "Latency burns usually come from a dependency, not from this code: check "
            "the p95 of each outbound call before reading the diff."
        ),
        "availability": (
            "Availability burns are either a bad deploy or a dependency that is down. "
            "Rule out the deploy first — it is the one you can undo."
        ),
        "correctness": (
            "Correctness burns do not self-heal and are worse the longer they run. Stop "
            "the writer before repairing the data, or the repair races the bug."
        ),
        "freshness": (
            "Freshness burns mean an upstream job did not land. Check the schedule and "
            "the last successful run before rerunning anything downstream."
        ),
        "saturation": (
            "Saturation burns are capacity, not correctness: shed or scale first, then "
            "find out what changed the arrival rate."
        ),
    }.get(kind, "Check the dashboard, the last deploy, and one failing trace.")
