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
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages"))

from future_agents.sdd import (  # noqa: E402
    AuditLog,
    DeliveryPipeline,
    DispatchBackend,
    Dispatcher,
    IntakeSource,
    MasterOrchestrator,
    MemoryHub,
    Objective,
    RepoKnowledge,
    RepoScaffolder,
    RunState,
    RunStore,
    SpecKitConfig,
    TicketWorker,
    ToolchainBackend,
    Workforce,
    WorkQueue,
    detect_repo,
    get_persona,
    language_matrix,
    load_state,
    objective_from_payload,
    persona_catalog,
    save_state,
)

DEFAULT_STATE_DIR = ".spec-kit/runs"
DEFAULT_QUEUE_DIR = REPO_ROOT / ".spec-kit/state"
DEFAULT_WORKFORCE = REPO_ROOT / "data/config/spec_kit/workforce.yaml"


def _pipeline(args: argparse.Namespace) -> DeliveryPipeline:
    config = SpecKitConfig.load(getattr(args, "config", None), root=REPO_ROOT)
    return DeliveryPipeline(
        config,
        memory=MemoryHub(config.memory_hub, root=REPO_ROOT),
        persona=get_persona(getattr(args, "persona", None)),
        repo_root=getattr(args, "repo", None),
    )


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


def cmd_detect(args: argparse.Namespace) -> int:
    profile = detect_repo(args.path)
    chain = profile.toolchain()
    print(f"{args.path}: {profile.summary()}")
    print(f"  monorepo: {profile.monorepo}  ci: {profile.has_ci}  tests: {profile.has_tests}")
    print(f"  toolchain: {chain.display_name}")
    for name, command in chain.commands().items():
        print(f"    {name:9s} {command}")
    print(f"  dependency policy: {chain.pin_rule}")
    missing = RepoScaffolder(get_persona(args.persona)).validate(args.path, profile)
    print(f"  missing structure: {', '.join(missing) if missing else 'none'}")
    return 0


def cmd_scaffold(args: argparse.Namespace) -> int:
    scaffolder = RepoScaffolder(get_persona(args.persona))
    plan = scaffolder.plan(
        args.path, language=args.language, name=args.name or "", description=args.description or ""
    )
    print(plan.summary())
    for action in plan.actions:
        mark = "+" if action.action == "create" else "="
        print(f"  {mark} {action.path:52s} {action.purpose}")
    written = scaffolder.apply(plan, dry_run=not args.write)
    verb = "wrote" if args.write else "would write"
    print(f"\n{verb} {len(written)} entries")
    if not args.write:
        print("re-run with --write to create them")
    return 0


def cmd_program(args: argparse.Namespace) -> int:
    config = SpecKitConfig.load(args.config, root=REPO_ROOT)
    orchestrator = MasterOrchestrator(
        config,
        memory=MemoryHub(config.memory_hub, root=REPO_ROOT),
        persona=get_persona(args.persona),
    )
    for spec in args.repo:
        name, _, path = spec.partition("=")
        if not path:
            raise SystemExit(f"--repo expects name=path, got: {spec}")
        depends = [d for d in (args.depends or []) if d.startswith(f"{name}:")]
        orchestrator.register(
            name,
            path,
            keywords=[name, *name.split("-")],
            depends_on=[d.split(":", 1)[1] for d in depends],
        )
    for row in orchestrator.inventory():
        missing = row["missing_structure"] or "none"
        print(f"  {row['name']:22s} {row['language']:12s} missing: {missing}")

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
    program = orchestrator.start(objective)
    print(f"\nprogram {program.id} — waves: {program.waves}")
    for repo, state in program.runs.items():
        print(f"  {repo:22s} {state.stage.value}")
    for repo, why in program.skipped.items():
        print(f"  {repo:22s} skipped — {why}")
    if program.questions:
        print("\nopen questions (answer once for the whole program):")
        for question in program.questions:
            print(f"  {'!' if question.blocking else '·'} {question.id}  {question.text}")
    if program.meeting:
        print(f"\nmeeting requested: {program.meeting.title}")
    for blocker in program.blockers():
        print(f"  blocker: {blocker}")
    return 0


def _workforce(args: argparse.Namespace) -> Workforce:
    path = Path(getattr(args, "workforce", "") or DEFAULT_WORKFORCE)
    return Workforce.load(path) if path.is_file() else Workforce()


def _worker(args: argparse.Namespace) -> TicketWorker:
    """A worker whose pipeline dispatches to the declared workforce."""
    config = SpecKitConfig.load(args.config, root=REPO_ROOT)
    memory = MemoryHub(config.memory_hub, root=REPO_ROOT)
    workforce = _workforce(args)
    repo_root = getattr(args, "repo", None) or str(REPO_ROOT)
    profile = detect_repo(repo_root)
    toolchain = profile.toolchain()

    def factory(_objective):
        dispatcher = Dispatcher(workforce, language=profile.primary_language)
        backend = DispatchBackend(
            dispatcher,
            repo_root=repo_root,
            toolchain=toolchain,
            fallback=ToolchainBackend(repo_root, toolchain),
        )
        return DeliveryPipeline(
            config,
            memory=memory,
            backend=backend,
            persona=get_persona(args.persona),
            repo_root=repo_root,
            profile=profile,
        )

    state_dir = Path(getattr(args, "queue_dir", "") or DEFAULT_QUEUE_DIR)
    return TicketWorker(factory, RunStore(state_dir), WorkQueue(state_dir), AuditLog(state_dir))


def cmd_enqueue(args: argparse.Namespace) -> int:
    payload = (
        json.loads(Path(args.payload).read_text())
        if args.payload
        else {
            "title": args.statement or "",
            "description": args.context or "",
            "system": args.system or "cli",
            "id": args.id or "",
            "author": args.by,
        }
    )
    objective = objective_from_payload(payload, system=args.system or "")
    queue = WorkQueue(Path(getattr(args, "queue_dir", "") or DEFAULT_QUEUE_DIR))
    item = queue.enqueue(objective, priority=args.priority)
    removed = objective.metadata.get("removed_by_sanitizer") or []
    print(f"{item.id}  {objective.external.key or '(no external id)'}  {objective.statement[:70]}")
    if removed:
        print(f"  sanitiser removed: {', '.join(removed)}")
    print(f"  queue: {queue.stats()}")
    return 0


def cmd_work(args: argparse.Namespace) -> int:
    worker = _worker(args)
    outcomes = worker.work(worker_id=args.worker or "", max_items=args.max_items)
    if not outcomes:
        print("nothing to do")
        return 0
    for outcome in outcomes:
        state = "awaiting human" if outcome.awaiting_human else outcome.stage
        mark = "ok" if outcome.accepted else ("dead" if outcome.dead else state)
        print(f"{outcome.item_id}  run={outcome.run_id or '-'}  {mark}  {outcome.seconds:.1f}s")
        if outcome.error:
            print(f"  error: {outcome.error[:160]}")
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    root = Path(getattr(args, "queue_dir", "") or DEFAULT_QUEUE_DIR)
    queue, store = WorkQueue(root), RunStore(root)
    print(f"queue: {queue.stats()}")
    for item in queue.pending():
        owner = f" held by {item.owner}" if item.owner else ""
        print(f"  {item.id}  p{item.priority}  try {item.attempts}/{item.max_attempts}{owner}")
        print(f"      {item.objective.statement[:88]}")
    dead = queue.dead_letter()
    if dead:
        print("\ndead letter:")
        for item in dead:
            print(f"  {item.id}  {item.objective.statement[:70]}")
            for reason in item.reasons[-2:]:
                print(f"      {reason[:100]}")
    stuck = store.stuck()
    if stuck:
        print("\nstalled runs:")
        for record in stuck:
            print(f"  {record.run_id}  stage {record.stage}  since {record.updated_at.isoformat()}")
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    workforce = _workforce(args)
    print(f"{len(workforce.agents)} agents, {len(workforce.skills)} skills")
    for spec in workforce.agents.values():
        health = workforce.health.get(spec.id)
        bound = "bound" if workforce.bound(spec.id) else "declared"
        print(f"  {spec.id:20s} {bound:9s} kinds={','.join(spec.kinds) or 'any':22s} {spec.engine}")
        print(f"      skills: {', '.join(spec.skills) or '—'}")
        if health and health.attempts:
            print(f"      {health.successes}/{health.attempts} successes")
    if args.task:
        from future_agents.sdd.models import TaskKind, TaskUnit

        task = TaskUnit(id="T-000", title=args.task, kind=TaskKind(args.kind))
        print(f"\nfor '{args.task}' ({args.kind}):")
        for line in Dispatcher(workforce, language=args.language).explain(task):
            print(f"  {line}")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    recovered = _worker(args).recover()
    print(f"reclaimed {len(recovered)}: {', '.join(recovered) or 'nothing'}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    knowledge = RepoKnowledge.build(args.path)
    stats = knowledge.stats()
    print(f"{args.path}")
    for key in ("files_indexed", "directories", "symbols", "truncated"):
        print(f"  {key:16s} {stats[key]}")
    print(f"  {'languages':16s} {', '.join(stats['languages'])}")
    print(f"  {'source roots':16s} {', '.join(knowledge.index.source_roots())}")
    print(f"  {'conventions':16s} {', '.join(stats['convention_sources'])}")
    print(f"  {'placement rules':16s} {stats['placement_rules']}")
    if stats["bulk_directories"]:
        print(f"  {'bulk data dirs':16s} {', '.join(stats['bulk_directories'][:4])} …")
    if args.query:
        print(f"\ncontext for: {args.query}")
        context = knowledge.context(args.query)
        for match in context.matches:
            target = f"{match.path}::{match.symbol}" if match.symbol else match.path
            print(f"  {match.score:6.3f}  {target}")
            if match.excerpt:
                print(f"          {match.excerpt[:96]}")
        for note in context.notes:
            print(f"  note: {note}")
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    knowledge = RepoKnowledge.build(args.path)
    decision = knowledge.advise(args.what)
    print(f"{args.what}\n")
    how = f"[{decision.approach}, confidence {decision.confidence}]"
    print(f"  goes in   {decision.target_path}   {how}")
    print(f"  because   {decision.rationale}")
    print(f"  tests     {decision.test_path}")
    print(f"  docs      {decision.docs_path}")
    if decision.reuse:
        print("\n  read first:")
        for match in decision.reuse:
            print(f"    - {match.render()}")
    if decision.alternatives:
        print("\n  other approaches:")
        for option in decision.alternatives:
            print(f"    - {option.path} [{option.approach}]")
            print(f"        {option.rationale}")
            print(f"        trade-off: {option.tradeoff}")
    if decision.forbidden:
        print("\n  must not go in:")
        for zone in decision.forbidden:
            print(f"    ✗ {zone.path or '(repo root)'} — {zone.reason} [{zone.source}]")
    if decision.conventions:
        print("\n  rules consulted:")
        for rule in decision.conventions:
            print(f"    · {rule}")
    return 0


def cmd_personas(_args: argparse.Namespace) -> int:
    for persona in persona_catalog():
        print(f"{persona['id']:24s} {persona['years_experience']:>3}y  {persona['title']}")
        print(f"  {persona['summary']}")
        print(f"  gates: {', '.join(persona['gates'])}")
        print(f"  heuristics: {persona['heuristics']}")
    return 0


def cmd_languages(_args: argparse.Namespace) -> int:
    for row in language_matrix():
        print(f"{row['language']:16s} test: {row['test']:38s} pin: {row['pin_style']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spec-driven delivery pipeline")
    parser.add_argument("--config", help="path to spec-kit-enterprise.yaml")
    parser.add_argument("--state-dir", default=DEFAULT_STATE_DIR)
    parser.add_argument(
        "--persona",
        default=None,
        help="seniority profile driving the run (see `personas`)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="intake an objective and drive it as far as it can go")
    run.add_argument("--statement", required=True)
    run.add_argument("--context", default="")
    run.add_argument("--source", default="chat", choices=[s.value for s in IntakeSource])
    run.add_argument("--by", default="unknown")
    run.add_argument("--input", action="append", help="file of raw intake (transcript, ticket)")
    run.add_argument("--constraint", action="append")
    run.add_argument("--deadline")
    run.add_argument("--repo", help="repo root, so tasks use its toolchain and structure")
    run.set_defaults(func=cmd_run)

    detect = sub.add_parser("detect", help="profile a repository: language, toolchain, gaps")
    detect.add_argument("--path", default=".")
    detect.set_defaults(func=cmd_detect)

    scaffold = sub.add_parser("scaffold", help="create the structure a repo is missing")
    scaffold.add_argument("--path", default=".")
    scaffold.add_argument("--language", help="override detection")
    scaffold.add_argument("--name")
    scaffold.add_argument("--description")
    scaffold.add_argument("--write", action="store_true", help="actually create the entries")
    scaffold.set_defaults(func=cmd_scaffold)

    program = sub.add_parser("program", help="run one objective across many repositories")
    program.add_argument("--repo", action="append", required=True, metavar="name=path")
    program.add_argument("--depends", action="append", metavar="name:dependency")
    program.add_argument("--statement", required=True)
    program.add_argument("--context", default="")
    program.add_argument("--source", default="chat", choices=[s.value for s in IntakeSource])
    program.add_argument("--by", default="unknown")
    program.add_argument("--input", action="append")
    program.add_argument("--constraint", action="append")
    program.add_argument("--deadline")
    program.set_defaults(func=cmd_program)

    index = sub.add_parser("index", help="index a repo: symbols, conventions, gaps")
    index.add_argument("--path", default=".")
    index.add_argument("--query", help="also show what the repo knows about this")
    index.set_defaults(func=cmd_index)

    where = sub.add_parser("where", help="where does a change go — and where must it not")
    where.add_argument("--what", required=True, help="the change, in a sentence")
    where.add_argument("--path", default=".")
    where.set_defaults(func=cmd_where)

    enqueue = sub.add_parser("enqueue", help="put a ticket on the queue")
    enqueue.add_argument("--payload", help="JSON file: a GitHub/Jira/Linear/Slack payload")
    enqueue.add_argument("--statement", help="or state the work directly")
    enqueue.add_argument("--context", default="")
    enqueue.add_argument("--system", help="github | jira | linear | slack | transcript")
    enqueue.add_argument("--id", help="external ticket id, for de-duplication")
    enqueue.add_argument("--by", default="unknown")
    enqueue.add_argument("--priority", type=int, default=5)
    enqueue.add_argument("--queue-dir")
    enqueue.set_defaults(func=cmd_enqueue)

    work = sub.add_parser("work", help="claim tickets and run them")
    work.add_argument("--worker", help="worker id (default: host:pid)")
    work.add_argument("--max-items", type=int, default=1)
    work.add_argument("--repo", help="repository the work happens in")
    work.add_argument("--workforce", help="workforce.yaml (default: data/config/spec_kit)")
    work.add_argument("--queue-dir")
    work.set_defaults(func=cmd_work)

    queue_cmd = sub.add_parser("queue", help="what is waiting, held, dead or stalled")
    queue_cmd.add_argument("--queue-dir")
    queue_cmd.set_defaults(func=cmd_queue)

    agents = sub.add_parser("agents", help="the workforce, and who would take a task")
    agents.add_argument("--workforce")
    agents.add_argument("--task", help="explain routing for this task title")
    agents.add_argument(
        "--kind", default="code", choices=["code", "test", "review", "doc", "infra"]
    )
    agents.add_argument("--language", default="python")
    agents.set_defaults(func=cmd_agents)

    recover = sub.add_parser("recover", help="reclaim work a dead worker was holding")
    recover.add_argument("--queue-dir")
    recover.add_argument("--repo")
    recover.add_argument("--workforce")
    recover.set_defaults(func=cmd_recover)

    personas = sub.add_parser("personas", help="list the seniority profiles")
    personas.set_defaults(func=cmd_personas)

    languages = sub.add_parser("languages", help="list the supported toolchains")
    languages.set_defaults(func=cmd_languages)

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
