"""Master orchestrator — one objective across many repositories.

Real work rarely lands in one repo: an API change needs a client change needs a
pipeline change. The master orchestrator profiles each registered repository,
routes an objective to the ones it actually touches, orders them into waves by
their declared dependencies, and runs a full delivery pipeline in each.

The part that matters for a human: clarification questions from every repo are
**merged and de-duplicated into one question set**, so nobody is asked the same
thing five times. One answer sheet (or one meeting) unblocks the whole program.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.config import SpecKitConfig
from future_agents.sdd.memory_hub import MemoryHub
from future_agents.sdd.models import (
    ClarificationOutcome,
    CycleError,
    MeetingRequest,
    Objective,
    Question,
    RunState,
    Stage,
)
from future_agents.sdd.personas import DEFAULT_PERSONA, Persona, get_persona
from future_agents.sdd.pipeline import DeliveryPipeline
from future_agents.sdd.repos.languages import RepoProfile, detect_repo
from future_agents.sdd.repos.scaffold import RepoScaffolder, ScaffoldPlan
from future_agents.sdd.stages import WorkerBackend


class RepoTarget(BaseModel):
    """A repository the orchestrator can dispatch work to."""

    name: str
    path: str
    profile: RepoProfile
    persona_id: str = DEFAULT_PERSONA.id
    keywords: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    enabled: bool = True

    def matches(self, text: str) -> float:
        """How strongly this objective looks like this repo's work."""
        low = text.lower()
        score = 0.0
        if self.name.lower() in low:
            score += 3.0
        score += sum(1.0 for keyword in self.keywords if keyword.lower() in low)
        if self.profile.primary_language in low:
            score += 0.5
        return score


class ProgramEvent(BaseModel):
    repo: str
    message: str
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProgramRun(BaseModel):
    """One objective, fanned out across repositories."""

    id: str
    objective: Objective
    waves: list[list[str]] = Field(default_factory=list)
    runs: dict[str, RunState] = Field(default_factory=dict)
    questions: list[Question] = Field(default_factory=list)  # merged, de-duplicated
    question_map: dict[str, list[str]] = Field(default_factory=dict)  # merged id → per-repo ids
    meeting: Optional[MeetingRequest] = None
    events: list[ProgramEvent] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)  # repo → why

    @property
    def awaiting_human(self) -> bool:
        return bool(self.questions)

    def stage_of(self, repo: str) -> str:
        state = self.runs.get(repo)
        return state.stage.value if state else "not started"

    def blockers(self) -> list[str]:
        out = []
        for repo, state in self.runs.items():
            if state.stage is Stage.BLOCKED:
                last = state.events[-1].message if state.events else "blocked"
                out.append(f"{repo}: {last}")
            elif state.qa and state.qa.verdict.value != "pass":
                out.append(f"{repo}: QA {state.qa.verdict.value}")
        return out

    def report(self) -> dict[str, object]:
        return {
            "program": self.id,
            "objective": self.objective.statement,
            "waves": self.waves,
            "repos": {
                repo: {
                    "stage": state.stage.value,
                    "requirements": len(state.spec.requirements) if state.spec else 0,
                    "tasks": len(state.tasks.tasks) if state.tasks else 0,
                    "qa": state.qa.verdict.value if state.qa else None,
                    "accepted": state.delivery.accepted if state.delivery else False,
                    "case": state.case_id,
                }
                for repo, state in self.runs.items()
            },
            "skipped": self.skipped,
            "open_questions": [q.text for q in self.questions],
            "meeting": self.meeting.title if self.meeting else None,
            "blockers": self.blockers(),
        }


class MasterOrchestrator:
    """Registers repositories and drives an objective across all of them."""

    def __init__(
        self,
        config: Optional[SpecKitConfig] = None,
        memory: Optional[MemoryHub] = None,
        backend: Optional[WorkerBackend] = None,
        persona: Optional[Persona] = None,
    ) -> None:
        self.config = config or SpecKitConfig()
        self.memory = memory or MemoryHub(self.config.memory_hub)
        self.backend = backend
        self.persona = persona or DEFAULT_PERSONA
        self.targets: dict[str, RepoTarget] = {}
        self._pipelines: dict[str, DeliveryPipeline] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        path: str | Path,
        persona_id: Optional[str] = None,
        keywords: Optional[Iterable[str]] = None,
        depends_on: Optional[Iterable[str]] = None,
    ) -> RepoTarget:
        profile = detect_repo(path)
        target = RepoTarget(
            name=name,
            path=str(path),
            profile=profile,
            persona_id=persona_id or self.persona.id,
            keywords=list(keywords or []),
            depends_on=list(depends_on or []),
        )
        self.targets[name] = target
        self._pipelines[name] = DeliveryPipeline(
            self.config,
            memory=self.memory,
            backend=self.backend,
            persona=get_persona(target.persona_id),
            repo_root=target.path,
            profile=profile,
        )
        return target

    def pipeline_for(self, name: str) -> DeliveryPipeline:
        return self._pipelines[name]

    def inventory(self) -> list[dict[str, object]]:
        return [
            {
                "name": t.name,
                "path": t.path,
                "language": t.profile.primary_language,
                "languages": [s.language for s in t.profile.languages[:4]],
                "monorepo": t.profile.monorepo,
                "has_ci": t.profile.has_ci,
                "persona": t.persona_id,
                "depends_on": t.depends_on,
                "missing_structure": RepoScaffolder(get_persona(t.persona_id)).validate(t.path),
            }
            for t in self.targets.values()
        ]

    # ── Structure ─────────────────────────────────────────────────────────────

    def scaffold(self, name: str, dry_run: bool = True) -> tuple[ScaffoldPlan, list[str]]:
        target = self.targets[name]
        scaffolder = RepoScaffolder(get_persona(target.persona_id))
        plan = scaffolder.plan(target.path, profile=target.profile, name=target.name)
        return plan, scaffolder.apply(plan, dry_run=dry_run)

    def scaffold_all(self, dry_run: bool = True) -> dict[str, list[str]]:
        return {name: self.scaffold(name, dry_run)[1] for name in self.targets}

    # ── Routing ───────────────────────────────────────────────────────────────

    def route(
        self, objective: Objective, repos: Optional[Iterable[str]] = None
    ) -> list[RepoTarget]:
        """Explicit list wins; otherwise keyword/language match; otherwise all."""
        if repos:
            return [self.targets[r] for r in repos if r in self.targets]
        text = " ".join([objective.statement, objective.context, *objective.raw_inputs])
        scored = [(t, t.matches(text)) for t in self.targets.values() if t.enabled]
        hits = [t for t, score in scored if score > 0]
        return hits or [t for t, _ in scored]

    def waves(self, targets: list[RepoTarget]) -> list[list[str]]:
        """Order repos by their declared dependencies; raises on a cycle."""
        names = {t.name for t in targets}
        pending = {t.name: {d for d in t.depends_on if d in names} for t in targets}
        waves: list[list[str]] = []
        while pending:
            ready = sorted(name for name, deps in pending.items() if not deps)
            if not ready:
                raise CycleError(f"cycle in repo dependencies: {', '.join(sorted(pending))}")
            waves.append(ready)
            for name in ready:
                del pending[name]
            for deps in pending.values():
                deps.difference_update(ready)
        return waves

    # ── Execution ─────────────────────────────────────────────────────────────

    def start(
        self,
        objective: Objective,
        repos: Optional[Iterable[str]] = None,
    ) -> ProgramRun:
        targets = self.route(objective, repos)
        program = ProgramRun(
            id=f"prog-{objective.id.split('-')[-1]}",
            objective=objective,
            waves=self.waves(targets),
        )
        self._run_waves(program, targets)
        self._merge_questions(program)
        return program

    def answer(
        self, program: ProgramRun, answers: dict[str, str], answered_by: str = "human"
    ) -> ProgramRun:
        """Answer the merged question set; every affected repo resumes.

        Answers are grouped per repo and applied in one call: re-assessing a run
        mints fresh question ids, so answering one at a time would strand the rest.
        """
        by_repo: dict[str, dict[str, str]] = {}
        for merged_id, answer in answers.items():
            for repo_question in program.question_map.get(merged_id, []):
                repo, _, question_id = repo_question.partition(":")
                by_repo.setdefault(repo, {})[question_id] = answer

        for repo, repo_answers in by_repo.items():
            state = program.runs.get(repo)
            if state is None:
                continue
            program.runs[repo] = self._pipelines[repo].answer(
                state, repo_answers, answered_by=answered_by
            )
            program.events.append(
                ProgramEvent(repo=repo, message=f"answered {len(repo_answers)} question(s)")
            )
        self._resume_blocked_waves(program)
        self._merge_questions(program)
        return program

    def hold_meeting(
        self,
        program: ProgramRun,
        notes: str,
        answers: Optional[dict[str, str]] = None,
    ) -> ProgramRun:
        """One meeting closes the program's questions in every repo at once."""
        for repo, state in list(program.runs.items()):
            if not state.awaiting_human:
                continue
            repo_answers = {
                question_id.split(":", 1)[1]: answer
                for merged_id, answer in (answers or {}).items()
                for question_id in program.question_map.get(merged_id, [])
                if question_id.startswith(f"{repo}:")
            }
            program.runs[repo] = self._pipelines[repo].hold_meeting(state, notes, repo_answers)
            program.events.append(ProgramEvent(repo=repo, message="meeting recorded"))
        if program.meeting:
            program.meeting.notes = notes
        self._resume_blocked_waves(program)
        self._merge_questions(program)
        return program

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_waves(self, program: ProgramRun, targets: list[RepoTarget]) -> None:
        by_name = {t.name: t for t in targets}
        for wave in program.waves:
            for name in wave:
                target = by_name[name]
                blocker = self._unmet_dependency(program, target)
                if blocker:
                    program.skipped[name] = blocker
                    program.events.append(ProgramEvent(repo=name, message=blocker))
                    continue
                objective = self._repo_objective(program.objective, target)
                state = self._pipelines[name].start(objective)
                program.runs[name] = state
                program.events.append(ProgramEvent(repo=name, message=f"stage {state.stage.value}"))

    def _resume_blocked_waves(self, program: ProgramRun) -> None:
        """Repos skipped behind a dependency get their turn once it clears."""
        for wave in program.waves:
            for name in wave:
                if name in program.runs or name not in program.skipped:
                    continue
                target = self.targets[name]
                if self._unmet_dependency(program, target):
                    continue
                del program.skipped[name]
                state = self._pipelines[name].start(self._repo_objective(program.objective, target))
                program.runs[name] = state
                program.events.append(
                    ProgramEvent(repo=name, message=f"resumed — stage {state.stage.value}")
                )

    def _unmet_dependency(self, program: ProgramRun, target: RepoTarget) -> str:
        for dependency in target.depends_on:
            if dependency not in self.targets:
                continue
            state = program.runs.get(dependency)
            if state is None:
                return f"waiting on {dependency}"
            if state.stage in (Stage.BLOCKED, Stage.CLARIFY):
                return f"waiting on {dependency} ({state.stage.value})"
        return ""

    def _repo_objective(self, objective: Objective, target: RepoTarget) -> Objective:
        """A per-repo copy carrying that repo's toolchain as context."""
        chain = target.profile.toolchain()
        copy = objective.model_copy(deep=True)
        copy.id = f"{objective.id}-{target.name}"
        copy.metadata = {
            **objective.metadata,
            "repo": target.name,
            "language": chain.language,
            "test_command": chain.test,
        }
        copy.constraints = [
            *objective.constraints,
            f"Repository {target.name} is {chain.display_name}; tests run with "
            f"`{chain.test or 'no configured test command'}`.",
            f"Dependency ranges: {chain.pin_rule}" if chain.pin_rule else "",
        ]
        copy.constraints = [c for c in copy.constraints if c]
        return copy

    def _merge_questions(self, program: ProgramRun) -> None:
        """One question per distinct unknown, whichever repos raised it."""
        merged: dict[str, Question] = {}
        mapping: dict[str, list[str]] = {}
        meeting: Optional[MeetingRequest] = None

        for repo, state in program.runs.items():
            for question in state.pending_questions():
                key = question.text.strip().lower()
                if key not in merged:
                    merged[key] = question.model_copy(deep=True)
                    mapping[merged[key].id] = []
                merged_id = merged[key].id
                merged[key].blocking = merged[key].blocking or question.blocking
                mapping[merged_id].append(f"{repo}:{question.id}")
            clarification = state.clarification
            if (
                meeting is None
                and clarification
                and clarification.outcome is ClarificationOutcome.MEETING_REQUIRED
                and clarification.meeting
            ):
                meeting = clarification.meeting.model_copy(deep=True)

        program.questions = list(merged.values())
        program.question_map = mapping
        if meeting and program.questions:
            meeting.title = f"Clarify program: {program.objective.statement[:48]}"
            meeting.agenda = [q.text for q in program.questions]
            meeting.question_ids = [q.id for q in program.questions]
            program.meeting = meeting
        else:
            program.meeting = None


ProgramSink = Callable[[ProgramEvent], None]
