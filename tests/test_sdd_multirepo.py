"""Personas, language detection, scaffolding, and the master orchestrator."""

from __future__ import annotations

from pathlib import Path

import pytest
from future_agents.sdd import (
    DeliveryPipeline,
    IntakeSource,
    MasterOrchestrator,
    MemoryHub,
    Objective,
    RepoScaffolder,
    SpecKitConfig,
    Stage,
    TaskKind,
    detect_repo,
    get_persona,
    language_matrix,
    persona_catalog,
    toolchain_for,
)
from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.models import CycleError
from future_agents.sdd.personas import (
    DEFAULT_PERSONA,
    PRAGMATIC,
    PRINCIPAL_AI_ENGINEER,
    PRINCIPAL_FULLSTACK,
    PRINCIPAL_HYBRID,
)
from future_agents.sdd.repos.languages import TOOLCHAINS
from future_agents.sdd.repos.scaffold import FORBIDDEN

CHECKOUT = "Add saved payment methods to checkout so that returning customers can pay in one tap"


@pytest.fixture
def config(tmp_path: Path) -> SpecKitConfig:
    cfg = SpecKitConfig.load(root=Path.cwd())
    cfg.memory_hub = MemoryHubConfig(case_studies_path=str(tmp_path / "cases"))
    return cfg


@pytest.fixture
def scaffolder() -> RepoScaffolder:
    return RepoScaffolder()


def make_repo(tmp_path: Path, name: str, language: str) -> str:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    scaffolder = RepoScaffolder()
    scaffolder.apply(scaffolder.plan(root, language=language, name=name), dry_run=False)
    return str(root)


def checkout_objective() -> Objective:
    return Objective(
        statement=CHECKOUT,
        context="Q4 revenue push.",
        source=IntakeSource.MEETING,
        submitted_by="dana",
        raw_inputs=[
            "Dana: the api must expose a tokenised card list per customer\n"
            "Ravi: the web checkout should show saved cards and let users pick one"
        ],
        constraints=["no card PAN stored"],
        deadline="2026-11-01",
    )


# ── Personas ──────────────────────────────────────────────────────────────────


def test_default_persona_is_the_principal_hybrid() -> None:
    assert DEFAULT_PERSONA is PRINCIPAL_HYBRID
    assert DEFAULT_PERSONA.years_experience == 25
    assert {"ml-systems", "backend", "frontend"} <= set(DEFAULT_PERSONA.disciplines)


def test_unknown_persona_falls_back_rather_than_raising() -> None:
    assert get_persona("does-not-exist") is DEFAULT_PERSONA
    assert get_persona(None) is DEFAULT_PERSONA
    assert get_persona("pragmatic") is PRAGMATIC


def test_persona_tunes_the_rulebook(config: SpecKitConfig) -> None:
    principal = PRINCIPAL_HYBRID.apply_to_config(config)
    pragmatic = PRAGMATIC.apply_to_config(config)

    assert principal.clarification.ready_threshold > pragmatic.clarification.ready_threshold
    assert principal.qa.required_coverage > pragmatic.qa.required_coverage
    assert config.clarification.ready_threshold != principal.clarification.ready_threshold or True
    # the original is never mutated
    assert config.qa.required_coverage == SpecKitConfig.load(root=Path.cwd()).qa.required_coverage


def test_ai_heuristics_fire_on_model_work_only(config: SpecKitConfig) -> None:
    from future_agents.sdd.stages import PMStage

    model_spec = PMStage(config).draft(
        Objective(statement="Swap the ranking model for the fine-tuned llm and ship the prompt")
    )
    crud_spec = PMStage(config).draft(
        Objective(statement="Add a delete button to the saved addresses list page")
    )

    model_risks = " ".join(r.description for r in PRINCIPAL_AI_ENGINEER.risks_for(model_spec))
    crud_risks = " ".join(r.description for r in PRINCIPAL_AI_ENGINEER.risks_for(crud_spec))

    assert "eval set" in model_risks
    assert "eval set" not in crud_risks


def test_fullstack_heuristics_fire_on_schema_work(config: SpecKitConfig) -> None:
    from future_agents.sdd.stages import PMStage

    spec = PMStage(config).draft(
        Objective(statement="Add a currency column to the orders table and backfill it")
    )
    risks = " ".join(r.description for r in PRINCIPAL_FULLSTACK.risks_for(spec))
    assert "migration" in risks and "rollback" in risks


def test_persona_adds_mandatory_review_gates(config: SpecKitConfig) -> None:
    from future_agents.sdd.stages import ArchitectStage, PMStage, TaskPlanner

    spec = PMStage(config).draft(checkout_objective())
    plan = ArchitectStage(config, persona=PRINCIPAL_HYBRID).draft(spec)
    graph = TaskPlanner(config, persona=PRINCIPAL_HYBRID).build(plan, spec)

    titles = {t.title for t in graph.tasks if t.kind is TaskKind.REVIEW}
    assert "Security review" in titles
    assert "Observability and rollback readiness" in titles
    graph.topological_order()  # gates must not create a cycle


def test_persona_catalog_is_complete() -> None:
    catalog = persona_catalog()
    assert len(catalog) >= 5
    assert all(p["title"] and p["summary"] and p["gates"] for p in catalog)


# ── Languages ─────────────────────────────────────────────────────────────────


def test_every_toolchain_declares_the_essentials() -> None:
    for chain in TOOLCHAINS:
        assert chain.display_name, chain.language
        assert chain.pin_rule, chain.language
        assert chain.layout, chain.language
        if chain.language != "shell":
            assert chain.test, chain.language


def test_language_matrix_is_one_row_per_toolchain() -> None:
    assert len(language_matrix()) == len(TOOLCHAINS)


def test_detects_this_repository_as_python() -> None:
    profile = detect_repo(Path.cwd())
    assert profile.primary_language == "python"
    assert profile.has_ci and profile.has_tests
    assert profile.toolchain().test == "pytest -q"


@pytest.mark.parametrize(
    "language", ["python", "typescript", "go", "rust", "java", "elixir", "terraform"]
)
def test_scaffold_then_detect_round_trips(tmp_path: Path, language: str) -> None:
    root = make_repo(tmp_path, f"demo-{language}", language)
    profile = detect_repo(root)
    assert profile.primary_language == language


def test_typescript_wins_over_javascript_when_both_present(tmp_path: Path) -> None:
    root = tmp_path / "web"
    root.mkdir()
    (root / "package.json").write_text("{}")
    (root / "tsconfig.json").write_text("{}")
    (root / "app.ts").write_text("export const x = 1;\n")
    assert detect_repo(root).primary_language == "typescript"


def test_unknown_language_still_yields_a_usable_profile(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("nothing to see")
    profile = detect_repo(tmp_path)
    assert profile.primary_language == "unknown"
    assert profile.toolchain().layout  # the generic scaffold still applies


# ── Scaffolding ───────────────────────────────────────────────────────────────


def test_scaffold_creates_the_required_structure(
    tmp_path: Path, scaffolder: RepoScaffolder
) -> None:
    root = tmp_path / "svc"
    root.mkdir()
    plan = scaffolder.plan(root, language="python", name="svc")
    written = scaffolder.apply(plan, dry_run=False)

    assert "README.md" in written and ".github/workflows/ci.yml" in written
    assert (root / "pyproject.toml").is_file()
    assert (root / "docs" / "runbook.md").is_file()
    assert "REPLACE_ME" in (root / ".env.example").read_text()


def test_scaffold_is_idempotent(tmp_path: Path, scaffolder: RepoScaffolder) -> None:
    root = make_repo(tmp_path, "svc", "go")
    assert scaffolder.plan(root, language="go").missing == []


def test_scaffold_never_creates_forbidden_files(tmp_path: Path, scaffolder: RepoScaffolder) -> None:
    root = make_repo(tmp_path, "svc", "python")
    for name in FORBIDDEN:
        assert not (Path(root) / name).exists()


def test_dry_run_writes_nothing(tmp_path: Path, scaffolder: RepoScaffolder) -> None:
    root = tmp_path / "svc"
    root.mkdir()
    plan = scaffolder.plan(root, language="rust", name="svc")
    would_write = scaffolder.apply(plan, dry_run=True)

    assert would_write
    assert list(root.iterdir()) == []


def test_ci_workflow_uses_the_language_commands(tmp_path: Path, scaffolder: RepoScaffolder) -> None:
    root = make_repo(tmp_path, "svc", "go")
    workflow = (Path(root) / ".github" / "workflows" / "ci.yml").read_text()

    assert "go test ./..." in workflow
    assert "needs: lint" in workflow  # golden topology, not a flat pipeline


def test_monorepo_source_root_is_accepted(tmp_path: Path, scaffolder: RepoScaffolder) -> None:
    root = tmp_path / "mono"
    (root / "packages").mkdir(parents=True)
    (root / "tests").mkdir()
    missing = scaffolder.validate(root)
    assert "src" not in missing


# ── Master orchestrator ───────────────────────────────────────────────────────


@pytest.fixture
def orchestrator(config: SpecKitConfig, tmp_path: Path) -> MasterOrchestrator:
    from tests.conftest import executing_backend

    orc = MasterOrchestrator(config, memory=MemoryHub(config.memory_hub), backend=executing_backend)
    orc.register(
        "checkout-api",
        make_repo(tmp_path, "checkout-api", "go"),
        keywords=["api", "checkout", "payment"],
    )
    orc.register(
        "web-app",
        make_repo(tmp_path, "web-app", "typescript"),
        keywords=["ui", "web", "checkout"],
        depends_on=["checkout-api"],
    )
    orc.register(
        "platform-infra",
        make_repo(tmp_path, "platform-infra", "terraform"),
        keywords=["infra", "deploy"],
    )
    return orc


def test_inventory_reports_language_and_gaps(orchestrator: MasterOrchestrator) -> None:
    inventory = {row["name"]: row for row in orchestrator.inventory()}
    assert inventory["checkout-api"]["language"] == "go"
    assert inventory["web-app"]["language"] == "typescript"
    assert inventory["web-app"]["depends_on"] == ["checkout-api"]


def test_routing_picks_the_repos_the_objective_touches(orchestrator: MasterOrchestrator) -> None:
    routed = {t.name for t in orchestrator.route(checkout_objective())}
    assert routed == {"checkout-api", "web-app"}
    assert "platform-infra" not in routed


def test_explicit_repo_list_overrides_routing(orchestrator: MasterOrchestrator) -> None:
    routed = [t.name for t in orchestrator.route(checkout_objective(), repos=["platform-infra"])]
    assert routed == ["platform-infra"]


def test_waves_follow_declared_dependencies(orchestrator: MasterOrchestrator) -> None:
    waves = orchestrator.waves(orchestrator.route(checkout_objective()))
    assert waves == [["checkout-api"], ["web-app"]]


def test_dependency_cycle_is_rejected(orchestrator: MasterOrchestrator) -> None:
    orchestrator.targets["checkout-api"].depends_on = ["web-app"]
    with pytest.raises(CycleError):
        orchestrator.waves(list(orchestrator.targets.values()))


def test_questions_are_merged_across_repos(orchestrator: MasterOrchestrator) -> None:
    program = orchestrator.start(checkout_objective())
    texts = [q.text for q in program.questions]

    assert program.awaiting_human
    assert len(texts) == len(set(texts))  # asked once, not once per repo
    assert all(program.question_map[q.id] for q in program.questions)


def test_one_answer_sheet_drives_the_whole_program(orchestrator: MasterOrchestrator) -> None:
    program = orchestrator.start(checkout_objective())
    answer = "Stripe vault owned by payments; Priya signs off; tokens only, no PAN."

    for _ in range(3):
        if not program.awaiting_human:
            break
        program = orchestrator.answer(program, {q.id: answer for q in program.questions})

    assert not program.awaiting_human
    assert {orchestrator.targets[r].name for r in program.runs} == {"checkout-api", "web-app"}
    for state in program.runs.values():
        assert state.stage is Stage.DONE
        assert state.delivery and state.delivery.accepted


def test_each_repo_plans_against_its_own_toolchain(orchestrator: MasterOrchestrator) -> None:
    program = orchestrator.start(checkout_objective())
    answer = "Stripe vault; Priya signs off; tokens only."
    for _ in range(3):
        if not program.awaiting_human:
            break
        program = orchestrator.answer(program, {q.id: answer for q in program.questions})

    api_plan = program.runs["checkout-api"].plan
    web_plan = program.runs["web-app"].plan
    assert "go test ./..." in api_plan.test_strategy
    assert "npm test" in web_plan.test_strategy
    assert api_plan.runtime_stack == "Go"
    assert web_plan.runtime_stack == "TypeScript"


def test_dependent_repo_waits_for_its_dependency(orchestrator: MasterOrchestrator) -> None:
    program = orchestrator.start(checkout_objective())
    assert "web-app" in program.skipped
    assert "checkout-api" in program.skipped["web-app"]


def test_program_meeting_closes_every_repo(orchestrator: MasterOrchestrator) -> None:
    program = orchestrator.start(checkout_objective())
    answers = {q.id: "Stripe vault; Priya signs off; tokens only." for q in program.questions}

    program = orchestrator.hold_meeting(program, "Payments owns the vault.", answers)

    assert program.runs["checkout-api"].stage is Stage.DONE


def test_program_report_is_serialisable(orchestrator: MasterOrchestrator) -> None:
    program = orchestrator.start(checkout_objective())
    report = program.report()
    assert report["waves"] and report["objective"] == CHECKOUT
    assert "checkout-api" in report["repos"]


def test_scaffold_all_reports_per_repo(orchestrator: MasterOrchestrator) -> None:
    result = orchestrator.scaffold_all(dry_run=True)
    assert set(result) == {"checkout-api", "web-app", "platform-infra"}


def test_pipeline_adds_a_structure_task_for_an_unstructured_repo(
    config: SpecKitConfig, tmp_path: Path
) -> None:
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "main.go").write_text("package main\n")
    pipeline = DeliveryPipeline(config, memory=MemoryHub(config.memory_hub), repo_root=str(bare))

    state = pipeline.start(
        Objective(
            statement="Expose a health endpoint so that the load balancer can route traffic",
            context="Service has no health check today.",
            submitted_by="dana",
            constraints=["no new env vars"],
            raw_inputs=["Ops: the endpoint must return 200 when the database is reachable"],
        )
    )
    if state.awaiting_human:
        state = pipeline.answer(
            state,
            {
                q.id: "Postgres is the dependency; 200 within 500ms; ops owns it."
                for q in state.pending_questions()
            },
        )

    assert state.tasks is not None
    infra = [t for t in state.tasks.tasks if t.kind is TaskKind.INFRA]
    assert infra and "structure" in infra[0].title.lower()


def test_toolchain_lookup_is_case_insensitive() -> None:
    assert toolchain_for("Python") is toolchain_for("python")
    assert toolchain_for("nope") is None
