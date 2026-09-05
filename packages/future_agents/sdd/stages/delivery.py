"""Delivery stage — what shipped, what is still assumed, what stayed open."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from future_agents.sdd.models import Delivery, QAVerdict, RunState
from future_agents.sdd.observability import render_runbook


class DeliveryStage:
    """Packages the run: what shipped, what is still assumed, what stayed open."""

    role = "delivery_agent"

    def __init__(self, repo_root: Optional[str] = None, write_runbook: bool = True) -> None:
        # The runbook is written where the alerts point, so a delivery cannot
        # ship alerts that reference a file nobody generated.
        self.repo_root = repo_root
        self.write_runbook = write_runbook

    def package(self, state: RunState) -> Delivery:
        spec = state.spec
        qa = state.qa
        accepted = bool(
            qa
            and qa.verdict is QAVerdict.PASS
            and not (state.clarification and state.clarification.open_blocking)
        )
        artifacts = sorted(
            {f for result in state.work_results for f in result.changed_files}
            | {t for result in state.work_results for t in result.tests_added}
        )

        obs = state.plan.observability if state.plan else None
        runbook_path = ""
        slo_summary: list[str] = []
        if obs is not None:
            runbook_path = obs.runbook_path
            slo_summary = [slo.render() for slo in obs.slos]
            artifacts = sorted(set(artifacts) | {d.path for d in obs.dashboards if d.path})
            written = self._emit_runbook(obs, spec)
            if written:
                artifacts = sorted(set(artifacts) | {str(written)})

        return Delivery(
            spec_id=spec.id if spec else "",
            accepted=accepted,
            coverage=qa.coverage if qa else 0.0,
            artifacts=artifacts,
            runbook_path=runbook_path,
            slo_summary=slo_summary,
            unconfirmed_assumptions=[
                a for a in (spec.assumptions if spec else []) if not a.confirmed
            ],
            residual_questions=[q for q in (spec.open_questions if spec else []) if not q.answered],
            notes="; ".join(qa.summary_lines()) if qa else "no QA report",
        )

    def _emit_runbook(self, obs, spec) -> Optional[Path]:
        if not (self.write_runbook and self.repo_root and obs.runbook_path):
            return None
        target = Path(self.repo_root) / obs.runbook_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_runbook(obs, spec))
        except OSError:
            return None  # a read-only workspace must not fail the delivery
        return target
