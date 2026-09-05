#!/usr/bin/env python3
"""Spec Kit CLI — drive the spec-driven delivery pipeline from a terminal.

    python scripts/spec_kit.py run --statement "Weekly churn report for sales" \
        --source meeting_transcript --input notes.txt
    python scripts/spec_kit.py answer --state .spec-kit/runs/run-x.json \
        --answer q-123="p95 under 800ms"
    python scripts/spec_kit.py meeting --state … --notes-file notes.md
    python scripts/spec_kit.py status --state …
    python scripts/spec_kit.py cases --query "churn report"
    python scripts/spec_kit.py constitution
    python scripts/spec_kit.py diff-gate --proposed .github/workflows/ci.yml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages"))

from future_agents.sdd import (  # noqa: E402
    DeliveryPipeline,
    IntakeSource,
    MemoryHub,
    Objective,
    RunState,
    SpecKitConfig,
    load_state,
    save_state,
)

DEFAULT_STATE_DIR = ".spec-kit/runs"


def _pipeline(args: argparse.Namespace) -> DeliveryPipeline:
    config = SpecKitConfig.load(getattr(args, "config", None), root=REPO_ROOT)
    return DeliveryPipeline(config, memory=MemoryHub(config.memory_hub, root=REPO_ROOT))


def _kv(pairs: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if not value:
            raise SystemExit(f"--answer expects ID=text, got: {pair}")
        out[key.strip()] = value.strip()
    return out


def _report(state: RunState, state_path: Path) -> int:
    print(f"run {state.id} — stage {state.stage.value}")
    print(f"state: {state_path}")

    clarification = state.clarification
    if clarification:
        print(f"intent confidence {clarification.confidence} ({clarification.outcome.value})")
        for assumption in clarification.assumptions:
            print(f"  assumed [{assumption.risk}] {assumption.statement}")
    pending = state.pending_questions()
    if pending:
        print("\nopen questions:")
        for question in pending:
            mark = "!" if question.blocking else "·"
            print(f"  {mark} {question.id}  {question.text}")
            if question.options:
                print(f"      options: {', '.join(question.options)}")
    if clarification and clarification.meeting:
        meeting = clarification.meeting
        print(f"\nmeeting requested — {meeting.title} ({meeting.duration_minutes}m)")
        print(f"  reason: {meeting.reason}")
        print(f"  attendees: {', '.join(meeting.required_attendees) or 'unassigned'}")
        for item in meeting.agenda:
            print(f"  - {item}")

    if state.spec:
        print(f"\nspec: {len(state.spec.requirements)} requirement(s)")
        for requirement in state.spec.requirements:
            print(f"  {requirement.id} [{requirement.priority.value}] {requirement.statement}")
    if state.plan and state.plan.historical_warnings:
        print("\nmemory warnings:")
        for warning in state.plan.historical_warnings:
            print(f"  ! {warning}")
    if state.tasks:
        print(f"\ntasks: {len(state.tasks.tasks)}")
    if state.qa:
        print()
        for line in state.qa.summary_lines():
            print(f"  {line}")
    if state.delivery:
        print(f"\ndelivery: {'ACCEPTED' if state.delivery.accepted else 'NOT ACCEPTED'}")
        for assumption in state.delivery.unconfirmed_assumptions:
            print(f"  unconfirmed: {assumption.statement}")
    return 0 if state.stage.value in ("done", "clarify") else 1


def cmd_run(args: argparse.Namespace) -> int:
    raw_inputs = [Path(p).read_text() for p in args.input or []]
    objective = Objective(
        statement=args.statement,
        context=args.context or "",
        source=IntakeSource(args.source),
        submitted_by=args.by,
        raw_inputs=raw_inputs,
        constraints=args.constraint or [],
        deadline=args.deadline,
    )
    pipeline = _pipeline(args)
    state = pipeline.start(objective)
    return _report(state, save_state(state, args.state_dir))


def cmd_answer(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    pipeline = _pipeline(args)
    state = pipeline.answer(state, _kv(args.answer), answered_by=args.by)
    return _report(state, save_state(state, args.state_dir))


def cmd_meeting(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    pipeline = _pipeline(args)
    notes = Path(args.notes_file).read_text() if args.notes_file else (args.notes or "")
    state = pipeline.hold_meeting(state, notes, _kv(args.answer or []))
    return _report(state, save_state(state, args.state_dir))


def cmd_status(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    return _report(state, Path(args.state))


def cmd_cases(args: argparse.Namespace) -> int:
    config = SpecKitConfig.load(args.config, root=REPO_ROOT)
    hub = MemoryHub(config.memory_hub, root=REPO_ROOT)
    if args.query:
        report = hub.retrieve(args.query)
        if not report.matches:
            print("no matching cases")
            return 0
        for match in report.matches:
            print(f"{match.case.id}  {match.score}  [{match.case.outcome}]  {match.case.title}")
            for pitfall in match.case.pitfalls:
                print(f"    - {pitfall}")
        return 0
    print(hub.stats())
    for case in hub.all_cases()[:20]:
        print(f"{case.id}  [{case.outcome}]  {case.title}")
    return 0


def cmd_constitution(args: argparse.Namespace) -> int:
    print(SpecKitConfig.load(args.config, root=REPO_ROOT).constitution().render_markdown())
    return 0


def cmd_diff_gate(args: argparse.Namespace) -> int:
    config = SpecKitConfig.load(args.config, root=REPO_ROOT)
    golden = (
        Path(args.golden).read_text() if args.golden else config.golden_template(root=REPO_ROOT)
    )
    if golden is None:
        print("no golden template configured (cicd.golden_template_path)")
        return 2
    decision = config.constitution().diff_gate(golden, Path(args.proposed).read_text())
    print(decision.patch_summary())
    for line in decision.removed_topology:
        print(f"  removed topology: {line.strip()}")
    return 0 if decision.allowed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spec-driven delivery pipeline")
    parser.add_argument("--config", help="path to spec-kit-enterprise.yaml")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="intake an objective and drive it as far as it can go")
    run.add_argument("--statement", required=True)
    run.add_argument("--context", default="")
    run.add_argument("--source", default="chat", choices=[s.value for s in IntakeSource])
    run.add_argument("--by", default="unknown")
    run.add_argument("--input", action="append", help="file of raw intake (transcript, ticket)")
    run.add_argument("--constraint", action="append")
    run.add_argument("--deadline")
    run.set_defaults(func=cmd_run)

    answer = sub.add_parser("answer", help="answer open questions and resume")
    answer.add_argument("--state", required=True)
    answer.add_argument("--answer", action="append", required=True, metavar="ID=text")
    answer.add_argument("--by", default="human")
    answer.set_defaults(func=cmd_answer)

    meeting = sub.add_parser("meeting", help="record a clarification meeting and resume")
    meeting.add_argument("--state", required=True)
    meeting.add_argument("--notes")
    meeting.add_argument("--notes-file")
    meeting.add_argument("--answer", action="append", metavar="ID=text")
    meeting.set_defaults(func=cmd_meeting)

    status = sub.add_parser("status", help="print a saved run")
    status.add_argument("--state", required=True)
    status.set_defaults(func=cmd_status)

    cases = sub.add_parser("cases", help="browse or search the memory hub")
    cases.add_argument("--query")
    cases.set_defaults(func=cmd_cases)

    constitution = sub.add_parser("constitution", help="render the constitution as markdown")
    constitution.set_defaults(func=cmd_constitution)

    diff = sub.add_parser("diff-gate", help="check a pipeline change against the golden template")
    diff.add_argument("--proposed", required=True)
    diff.add_argument("--golden")
    diff.set_defaults(func=cmd_diff_gate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
