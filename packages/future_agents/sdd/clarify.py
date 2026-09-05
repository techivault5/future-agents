"""Intent clarification — the gate that keeps underspecified work out.

Most agent pipelines fail here: they accept a vague objective and hallucinate
the missing half. This stage scores intent, asks only what changes the outcome,
converts low-risk unknowns into recorded assumptions, and escalates to a live
human meeting when the remaining unknowns are too tangled for a form.

Ladder: auto-assume → async questions → meeting → blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from future_agents.sdd.config import ClarificationConfig, SpecKitConfig
from future_agents.sdd.models import (
    Assumption,
    ClarificationOutcome,
    ClarificationResult,
    MeetingRequest,
    MeetingStatus,
    Objective,
    Question,
    QuestionTopic,
)

# Words that promise a property without defining it. Each one costs confidence.
VAGUE_TERMS = (
    "fast",
    "faster",
    "slow",
    "scalable",
    "robust",
    "secure",
    "simple",
    "seamless",
    "better",
    "improve",
    "improved",
    "optimize",
    "optimise",
    "modern",
    "clean",
    "efficient",
    "user-friendly",
    "intuitive",
    "soon",
    "asap",
    "several",
    "some",
    "various",
    "etc",
    "tbd",
    "flexible",
    "reliable",
)

_METRIC_HINT = re.compile(
    r"(\d+\s*(%|percent|ms|s\b|sec|min|hour|day|req/s|rps|qps|users?|records?|gb|mb))"
    r"|p9[059]|sla|slo|latency budget",
    re.IGNORECASE,
)
_DATA_WORDS = ("data", "report", "dashboard", "sync", "export", "import", "metrics", "records")
_INTEGRATION_WORDS = ("integrate", "connect", "webhook", "api", "third-party", "vendor", "sso")
_SOURCE_HINT = re.compile(
    r"\bfrom\s+[A-Z][\w.-]+|\b(postgres|snowflake|s3|kafka|salesforce)\b", re.I
)
_DANGLING_REF = re.compile(r"^(it|this|that|they|these|those)\b", re.IGNORECASE)
_SPLIT_HINT = re.compile(r"\b(and also|as well as|plus,|additionally|then also)\b", re.IGNORECASE)


@dataclass
class Signal:
    """One detected gap in the objective."""

    topic: QuestionTopic
    question: str
    why: str
    weight: float  # confidence cost, 0..1
    blocking: bool = False
    evidence: str = ""
    options: tuple[str, ...] = ()
    default_assumption: str = ""


Detector = Callable[[Objective, "ClarifierContext"], list[Signal]]


@dataclass
class ClarifierContext:
    text: str  # objective + context + raw inputs, lower-cased
    raw: str  # same, original case
    config: SpecKitConfig


class IntentClarifier:
    """Scores an objective and produces the questions worth a human's time."""

    def __init__(self, config: Optional[SpecKitConfig] = None) -> None:
        self.config = config or SpecKitConfig()
        self.settings: ClarificationConfig = self.config.clarification
        self._detectors: list[Detector] = [
            _detect_vague_terms,
            _detect_missing_metric,
            _detect_missing_acceptance,
            _detect_missing_data_source,
            _detect_missing_integration_target,
            _detect_dangling_reference,
            _detect_multi_objective,
            _detect_escalation_trigger,
            _detect_open_ended,
        ]

    def assess(
        self,
        objective: Objective,
        prior: Optional[ClarificationResult] = None,
        round_number: int = 1,
    ) -> ClarificationResult:
        """Run detectors, fold in already-answered questions, decide the rung."""
        answered = _answered_map(prior)
        ctx = _context(objective, answered, self.config)
        signals = [s for detector in self._detectors for s in detector(objective, ctx)]
        signals = _dedupe(signals)

        questions: list[Question] = []
        assumptions: list[Assumption] = []
        penalty = 0.0

        for signal in signals:
            existing = answered.get(_signal_key(signal))
            if existing is not None:
                questions.append(existing)
                continue
            if (
                self.settings.auto_assume_low_risk
                and not signal.blocking
                and signal.default_assumption
            ):
                assumptions.append(
                    Assumption(
                        statement=signal.default_assumption,
                        basis=f"auto-assumed: {signal.why}",
                        risk="low" if signal.weight < 0.12 else "medium",
                    )
                )
                penalty += signal.weight * 0.5
                continue
            penalty += signal.weight
            questions.append(
                Question(
                    text=signal.question,
                    topic=signal.topic,
                    blocking=signal.blocking,
                    why_it_matters=signal.why,
                    evidence=signal.evidence,
                    options=list(signal.options),
                )
            )

        confidence = round(max(0.0, min(1.0, 1.0 - penalty)) * _structure_bonus(objective), 3)
        open_questions = [q for q in questions if not q.answered]
        blocking_open = [q for q in open_questions if q.blocking]

        outcome, rationale = self._decide(confidence, open_questions, blocking_open, round_number)
        result = ClarificationResult(
            objective_id=objective.id,
            outcome=outcome,
            confidence=confidence,
            questions=questions[: max(1, self.settings.max_questions_per_round)]
            if outcome is ClarificationOutcome.ASYNC_QUESTIONS
            else questions,
            assumptions=assumptions,
            rationale=rationale,
            round_number=round_number,
        )
        if outcome is ClarificationOutcome.MEETING_REQUIRED:
            result.meeting = self._meeting(objective, result, blocking_open or open_questions)
        return result

    def apply_answers(
        self,
        objective: Objective,
        result: ClarificationResult,
        answers: dict[str, str],
        answered_by: str = "human",
    ) -> ClarificationResult:
        """Record answers and re-assess. Answers fold into the objective context."""
        now = datetime.now(timezone.utc)
        for question in result.questions:
            if question.id in answers and answers[question.id].strip():
                question.answer = answers[question.id].strip()
                question.answered_by = answered_by
                question.answered_at = now
        return self.assess(objective, prior=result, round_number=result.round_number + 1)

    def record_meeting(
        self,
        objective: Objective,
        result: ClarificationResult,
        notes: str,
        answers: Optional[dict[str, str]] = None,
    ) -> ClarificationResult:
        """Close a meeting: notes become context, answers close the questions."""
        if result.meeting:
            result.meeting.status = MeetingStatus.HELD
            result.meeting.notes = notes
        objective.context = f"{objective.context}\n{notes}".strip()
        return self.apply_answers(objective, result, answers or {}, answered_by="meeting")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _decide(
        self,
        confidence: float,
        open_questions: list[Question],
        blocking_open: list[Question],
        round_number: int,
    ) -> tuple[ClarificationOutcome, str]:
        s = self.settings
        if confidence >= s.ready_threshold and not blocking_open:
            return ClarificationOutcome.READY, f"confidence {confidence} ≥ {s.ready_threshold}"
        if not open_questions:
            return ClarificationOutcome.READY, "no open questions remain"
        if confidence < s.meeting_threshold:
            return (
                ClarificationOutcome.MEETING_REQUIRED,
                f"confidence {confidence} < {s.meeting_threshold}: too tangled for async",
            )
        if round_number > s.max_rounds and blocking_open:
            return (
                ClarificationOutcome.MEETING_REQUIRED,
                f"{len(blocking_open)} blocking unknowns survived {s.max_rounds} async rounds",
            )
        return (
            ClarificationOutcome.ASYNC_QUESTIONS,
            f"{len(open_questions)} unknowns answerable without a meeting",
        )

    def _meeting(
        self,
        objective: Objective,
        result: ClarificationResult,
        questions: list[Question],
    ) -> MeetingRequest:
        s = self.settings
        attendees = list(s.meeting_attendees)
        if objective.submitted_by and objective.submitted_by not in attendees:
            attendees.insert(0, objective.submitted_by)
        return MeetingRequest(
            objective_id=objective.id,
            title=f"Clarify: {_short(objective.statement)}",
            reason=result.rationale,
            agenda=[q.text for q in questions],
            question_ids=[q.id for q in questions],
            required_attendees=attendees,
            duration_minutes=s.meeting_duration_minutes,
        )


# ── Detectors ─────────────────────────────────────────────────────────────────


def _detect_vague_terms(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    found = [t for t in VAGUE_TERMS if re.search(rf"\b{re.escape(t)}\b", ctx.text)]
    signals: list[Signal] = []
    for term in found[:3]:
        signals.append(
            Signal(
                topic=QuestionTopic.ACCEPTANCE,
                question=(
                    f"'{term}' is not measurable — what number or observable state counts as done?"
                ),
                why="an unmeasurable target cannot be verified by QA",
                weight=0.14,
                evidence=term,
            )
        )
    return signals


def _detect_missing_metric(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    wants_change = any(w in ctx.text for w in ("improve", "reduce", "increase", "optimi", "faster"))
    if _METRIC_HINT.search(ctx.raw):
        return []
    if not wants_change:
        return [
            Signal(
                topic=QuestionTopic.ACCEPTANCE,
                question="What is the success metric for this work?",
                why="delivery cannot be judged without one",
                weight=0.1,
                default_assumption="Success = all acceptance criteria verified by QA.",
            )
        ]
    return [
        Signal(
            topic=QuestionTopic.ACCEPTANCE,
            question="What is the current baseline and the target number?",
            why="a change objective without a baseline cannot be shown to have worked",
            weight=0.22,
            blocking=True,
        )
    ]


def _detect_missing_acceptance(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    if any(
        w in ctx.text for w in ("so that", "acceptance", "definition of done", "when ", "then ")
    ):
        return []
    return [
        Signal(
            topic=QuestionTopic.ACCEPTANCE,
            question="Who observes the result, and what do they see when it works?",
            why="acceptance criteria are derived from the observable outcome",
            weight=0.16,
            default_assumption="The requester verifies the outcome on the primary interface.",
        )
    ]


def _detect_missing_data_source(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    if not any(w in ctx.text for w in _DATA_WORDS):
        return []
    if _SOURCE_HINT.search(ctx.raw):
        return []
    return [
        Signal(
            topic=QuestionTopic.DATA,
            question="Which system of record supplies this data, and how fresh must it be?",
            why="the wrong source produces a plausible, wrong result",
            weight=0.2,
            blocking=True,
        )
    ]


def _detect_missing_integration_target(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    if not any(w in ctx.text for w in _INTEGRATION_WORDS):
        return []
    named = re.search(r"\b(with|to|into)\s+[A-Z][\w.-]{2,}", ctx.raw)
    if named:
        return []
    return [
        Signal(
            topic=QuestionTopic.INTEGRATION,
            question="Which external system is on the other side, and who owns its credentials?",
            why="integration work cannot start without the counterparty and its auth path",
            weight=0.18,
            blocking=True,
        )
    ]


def _detect_dangling_reference(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    if not _DANGLING_REF.match(objective.statement.strip()):
        return []
    return [
        Signal(
            topic=QuestionTopic.SCOPE,
            question="What does the opening pronoun refer to?",
            why="the subject of the objective is undefined",
            weight=0.25,
            blocking=True,
            evidence=_short(objective.statement, 60),
        )
    ]


def _detect_multi_objective(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    if not _SPLIT_HINT.search(objective.statement):
        return []
    return [
        Signal(
            topic=QuestionTopic.SCOPE,
            question=("This reads as more than one deliverable — ship together or split?"),
            why="bundled deliverables hide their own dependencies and slip together",
            weight=0.12,
            options=("ship together", "split into separate specs"),
            default_assumption="Deliverables ship together as one spec.",
        )
    ]


def _detect_escalation_trigger(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    triggers = ctx.config.constitution().requires_escalation(ctx.text)
    if not triggers:
        return []
    return [
        Signal(
            topic=QuestionTopic.OWNERSHIP,
            question=f"This touches {', '.join(triggers[:3])} — who signs off before it ships?",
            why="constitution requires a named human approver for this class of change",
            weight=0.2,
            blocking=True,
            evidence=", ".join(triggers),
        )
    ]


def _detect_open_ended(objective: Objective, ctx: ClarifierContext) -> list[Signal]:
    statement = objective.statement.strip()
    if statement.endswith("?"):
        return [
            Signal(
                topic=QuestionTopic.SCOPE,
                question="Is this a question to answer or work to deliver?",
                why="a research answer and a shipped change are different pipelines",
                weight=0.2,
                blocking=True,
                options=("answer the question", "deliver the change"),
            )
        ]
    if len(statement.split()) < 6:
        return [
            Signal(
                topic=QuestionTopic.SCOPE,
                question="What problem does this solve, and for whom?",
                why="a short objective leaves scope entirely to the agent",
                weight=0.22,
                blocking=True,
                evidence=statement,
            )
        ]
    return []


# ── Helpers ───────────────────────────────────────────────────────────────────


def _context(
    objective: Objective, answered: dict[str, Question], config: SpecKitConfig
) -> ClarifierContext:
    parts = [
        objective.statement,
        objective.context,
        *objective.raw_inputs,
        *objective.constraints,
        *(q.answer or "" for q in answered.values()),
    ]
    raw = "\n".join(p for p in parts if p)
    return ClarifierContext(text=raw.lower(), raw=raw, config=config)


def _answered_map(prior: Optional[ClarificationResult]) -> dict[str, Question]:
    if not prior:
        return {}
    return {_question_key(q): q for q in prior.questions if q.answered}


def _signal_key(signal: Signal) -> str:
    return f"{signal.topic.value}:{signal.evidence or signal.question[:40]}"


def _question_key(question: Question) -> str:
    return f"{question.topic.value}:{question.evidence or question.text[:40]}"


def _dedupe(signals: list[Signal]) -> list[Signal]:
    seen: set[str] = set()
    out: list[Signal] = []
    for signal in signals:
        key = _signal_key(signal)
        if key in seen:
            continue
        seen.add(key)
        out.append(signal)
    return out


def _structure_bonus(objective: Objective) -> float:
    """Well-formed intake earns back a little confidence."""
    bonus = 0.85
    if objective.constraints:
        bonus += 0.05
    if objective.raw_inputs:
        bonus += 0.05
    if objective.deadline:
        bonus += 0.05
    return min(1.0, bonus)


def _short(text: str, limit: int = 48) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
