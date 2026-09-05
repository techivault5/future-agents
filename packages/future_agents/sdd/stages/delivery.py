"""Delivery stage — what shipped, what is still assumed, what stayed open."""

from __future__ import annotations

from future_agents.sdd.models import Delivery, QAVerdict, RunState


class DeliveryStage:
    """Packages the run: what shipped, what is still assumed, what stayed open."""

    role = "delivery_agent"

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
        return Delivery(
            spec_id=spec.id if spec else "",
            accepted=accepted,
            coverage=qa.coverage if qa else 0.0,
            artifacts=artifacts,
            unconfirmed_assumptions=[
                a for a in (spec.assumptions if spec else []) if not a.confirmed
            ],
            residual_questions=[q for q in (spec.open_questions if spec else []) if not q.answered],
            notes="; ".join(qa.summary_lines()) if qa else "no QA report",
        )
