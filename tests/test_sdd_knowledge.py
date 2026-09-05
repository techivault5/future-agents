"""Repository knowledge — index, conventions, retrieval and placement."""

from __future__ import annotations

from pathlib import Path

import pytest
from future_agents.sdd import (
    DeliveryPipeline,
    MemoryHub,
    Objective,
    RepoIndex,
    RepoKnowledge,
    SpecKitConfig,
)
from future_agents.sdd.config import MemoryHubConfig
from future_agents.sdd.knowledge.conventions import ROOT_SENTINEL, Conventions
from future_agents.sdd.models import Requirement

AGENTS_MD = """# AGENTS.md

## Where do I put a new thing?

| You are adding | It goes in | Also do |
|---|---|---|
| A new agent type | `src/agents/<name>_agent.py` | Subclass BaseAgent; add tests |
| A scheduled worker | `src/workers/` | Register it in the scheduler |
| A guide or doc | `docs/` | Never at the repo root |

**Never put code at the repo root.** Root is for manifests only.

- `.env` is never committed; `.env.example` always is.
- Never add generated files to `dist/`.
"""


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "src" / "agents").mkdir(parents=True)
    (tmp_path / "src" / "workers").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "node_modules" / "left-pad").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text(AGENTS_MD)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "sample"\n')
    (tmp_path / "src" / "agents" / "invoice_agent.py").write_text(
        '"""Invoice agent — reads supplier invoices and extracts totals."""\n\n\n'
        "class InvoiceAgent:\n"
        '    """Extract totals from a supplier invoice."""\n\n'
        "    def extract_total(self, document: str) -> float:\n"
        '        """Return the invoice total."""\n'
        "        return 0.0\n"
    )
    (tmp_path / "src" / "workers" / "nightly_sync.py").write_text(
        '"""Nightly sync worker — pulls supplier records on a schedule."""\n\n\n'
        "def run_sync() -> None:\n"
        "    pass\n"
    )
    (tmp_path / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1;\n")
    return tmp_path


@pytest.fixture
def knowledge(sample_repo: Path) -> RepoKnowledge:
    return RepoKnowledge.build(sample_repo)


# ── Index ─────────────────────────────────────────────────────────────────────


def test_index_finds_symbols_and_docs(knowledge: RepoKnowledge) -> None:
    note = knowledge.index.files["src/agents/invoice_agent.py"]
    assert note.language == "python"
    assert note.doc.startswith("Invoice agent")
    assert {s.name for s in note.symbols} >= {"InvoiceAgent", "InvoiceAgent.extract_total"}


def test_index_skips_dependency_directories(knowledge: RepoKnowledge) -> None:
    assert not any(path.startswith("node_modules") for path in knowledge.index.files)


def test_index_identifies_source_roots_and_kinds(knowledge: RepoKnowledge) -> None:
    assert knowledge.index.source_roots() == ["src"]
    assert knowledge.index.directories["tests"].kind == "tests"
    assert knowledge.index.directories["docs"].kind == "docs"


def test_search_ranks_the_relevant_file_first(knowledge: RepoKnowledge) -> None:
    matches = knowledge.index.search("supplier invoice totals")
    assert matches and matches[0].path == "src/agents/invoice_agent.py"


def test_search_can_demand_a_name_match(knowledge: RepoKnowledge) -> None:
    loose = knowledge.index.search("schedule supplier records")
    strict = knowledge.index.search("schedule supplier records", require_name_overlap=2)
    assert len(strict) <= len(loose)


def test_index_round_trips_through_json(knowledge: RepoKnowledge, tmp_path: Path) -> None:
    path = knowledge.index.save(tmp_path / "index.json")
    restored = RepoIndex.load(path)

    assert set(restored.files) == set(knowledge.index.files)
    assert restored.search("supplier invoice totals")


def test_bulk_directories_are_sampled_not_indexed_whole(tmp_path: Path) -> None:
    bulk = tmp_path / "data" / "roles"
    bulk.mkdir(parents=True)
    for i in range(120):
        (bulk / f"role-{i:03d}.yaml").write_text(f"name: role {i}\n")
    index = RepoIndex.build(tmp_path)

    assert index.directories["data/roles"].bulk
    assert index.directories["data/roles"].file_count == 120
    indexed = [p for p in index.files if p.startswith("data/roles")]
    assert len(indexed) < 10


# ── Conventions ───────────────────────────────────────────────────────────────


def test_conventions_read_the_repos_own_table(knowledge: RepoKnowledge) -> None:
    rule = knowledge.conventions.best_rule("a new agent type for invoices")
    assert rule is not None
    assert rule.destination == "src/agents/<name>_agent.py"
    assert rule.source == "AGENTS.md"


def test_conventions_capture_the_root_prohibition(knowledge: RepoKnowledge) -> None:
    root_rules = [p for p in knowledge.conventions.prohibitions if ROOT_SENTINEL in p.paths]
    assert root_rules
    assert knowledge.conventions.forbids("newthing.py")
    assert not knowledge.conventions.forbids("src/agents/newthing.py")


def test_prose_with_slashes_is_not_mistaken_for_a_path(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "- Never store plaintext; hash with bcrypt/argon2.\n- Never commit `.env` files.\n"
    )
    conventions = Conventions.load(tmp_path)
    paths = [p for prohibition in conventions.prohibitions for p in prohibition.paths]
    assert "bcrypt/argon2" not in paths
    assert ".env" in paths


# ── Placement ─────────────────────────────────────────────────────────────────


def test_placement_follows_the_written_rule(knowledge: RepoKnowledge) -> None:
    decision = knowledge.advise("Add a new agent type that reads purchase orders")

    assert decision.target_path.startswith("src/agents/")
    assert decision.approach == "new-module"
    assert "AGENTS.md" in decision.rationale
    assert decision.confidence >= 0.8


def test_placement_names_tests_and_docs(knowledge: RepoKnowledge) -> None:
    decision = knowledge.advise("Add a new agent type that reads purchase orders")
    assert decision.test_path.startswith("tests/")
    assert decision.docs_path.startswith("docs")


def test_placement_offers_alternatives_with_tradeoffs(knowledge: RepoKnowledge) -> None:
    decision = knowledge.advise("Extract totals from supplier invoices more accurately")

    assert decision.alternatives
    assert all(option.tradeoff for option in decision.alternatives)
    assert {o.approach for o in [*decision.alternatives, decision]} & {"extend", "new-module"}


def test_placement_prefers_extending_the_closest_existing_code(knowledge: RepoKnowledge) -> None:
    decision = knowledge.advise("Extract totals from supplier invoices more accurately")
    paths = [decision.target_path, *(o.path for o in decision.alternatives)]
    assert any("invoice_agent.py" in path for path in paths)


def test_placement_reports_where_it_must_not_go(knowledge: RepoKnowledge) -> None:
    decision = knowledge.advise("Add a new agent type that reads purchase orders")
    reasons = " ".join(zone.reason for zone in decision.forbidden)

    assert decision.forbidden
    assert "root" in reasons.lower()
    assert any(zone.source.endswith(".md") for zone in decision.forbidden)


def test_index_files_are_not_chosen_as_extension_targets(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text('"""Invoice tooling package."""\n')
    (tmp_path / "src" / "invoice_tools.py").write_text(
        '"""Invoice tools — parse supplier invoice documents."""\n\n\n'
        "def parse_invoice(text: str) -> dict:\n"
        "    return {}\n"
    )
    knowledge = RepoKnowledge.build(tmp_path)

    decision = knowledge.advise("parse supplier invoice documents faster")
    assert not decision.target_path.endswith("__init__.py")


def test_duplicate_risk_is_strict_about_name_matches(knowledge: RepoKnowledge) -> None:
    close = Requirement(id="REQ-001", statement="Extract the invoice total from a supplier invoice")
    far = Requirement(id="REQ-002", statement="Send a weekly digest email to finance")

    assert knowledge.duplicate_risk(close)
    assert not knowledge.duplicate_risk(far)


def test_context_explains_what_already_exists(knowledge: RepoKnowledge) -> None:
    context = knowledge.context("supplier invoice totals")
    assert context.matches
    assert any("reuse before adding" in note for note in context.notes)


def test_stats_describe_the_repository(knowledge: RepoKnowledge) -> None:
    stats = knowledge.stats()
    assert stats["files_indexed"] >= 3
    assert "AGENTS.md" in stats["convention_sources"]
    assert stats["placement_rules"] >= 3


# ── Pipeline integration ──────────────────────────────────────────────────────


@pytest.fixture
def pipeline(sample_repo: Path, tmp_path: Path) -> DeliveryPipeline:
    config = SpecKitConfig.load(root=Path.cwd())
    config.memory_hub = MemoryHubConfig(case_studies_path=str(tmp_path / "cases"))
    return DeliveryPipeline(config, memory=MemoryHub(config.memory_hub), repo_root=str(sample_repo))


def run_objective(pipeline: DeliveryPipeline, statement: str, **kwargs) -> object:
    state = pipeline.start(
        Objective(
            statement=statement,
            context="Finance operations review.",
            submitted_by="dana",
            constraints=["no new production env vars"],
            **kwargs,
        )
    )
    answer = "The supplier portal is the source; finance signs off; baseline 4h, target 1h."
    if state.awaiting_human:
        state = pipeline.answer(state, {q.id: answer for q in state.pending_questions()})
    return state


def test_plan_carries_a_placement_per_requirement(pipeline: DeliveryPipeline) -> None:
    state = run_objective(
        pipeline,
        "Add a purchase-order agent so that finance stops keying orders by hand",
        raw_inputs=["Dana: the agent must read a purchase order and extract line items"],
    )

    assert state.plan is not None
    assert state.plan.placements
    assert all(p.target_path for p in state.plan.placements)
    assert all(p.requirement_id for p in state.plan.placements)


def test_tasks_carry_their_target_and_test_paths(pipeline: DeliveryPipeline) -> None:
    state = run_objective(
        pipeline,
        "Add a purchase-order agent so that finance stops keying orders by hand",
        raw_inputs=["Dana: the agent must read a purchase order and extract line items"],
    )

    code_tasks = [t for t in state.tasks.tasks if t.title.startswith("Implement")]
    test_tasks = [t for t in state.tasks.tasks if t.kind.value == "test"]
    assert any(t.artifacts and t.artifacts[0].startswith("src/") for t in code_tasks)
    assert any(t.artifacts and t.artifacts[0].startswith("tests/") for t in test_tasks)


def test_task_description_says_where_it_may_not_go(pipeline: DeliveryPipeline) -> None:
    state = run_objective(
        pipeline,
        "Add a purchase-order agent so that finance stops keying orders by hand",
        raw_inputs=["Dana: the agent must read a purchase order and extract line items"],
    )
    described = "\n".join(t.description for t in state.tasks.tasks)

    assert "Goes in:" in described
    assert "Do not put it in:" in described


def test_duplicate_work_becomes_a_spec_note_and_a_plan_risk(pipeline: DeliveryPipeline) -> None:
    state = run_objective(
        pipeline,
        "Extract the invoice total from every supplier invoice automatically",
        raw_inputs=["Dana: the extractor must read the supplier invoice total"],
    )

    assert state.spec is not None and state.plan is not None
    assert any("already be covered" in note for note in state.spec.context_notes)
    assert any(risk.source == "repo-knowledge" for risk in state.plan.risks)


def test_components_get_a_target_directory(pipeline: DeliveryPipeline) -> None:
    state = run_objective(
        pipeline,
        "Add a purchase-order agent so that finance stops keying orders by hand",
        raw_inputs=["Dana: the agent must read a purchase order and extract line items"],
    )
    assert any(component.target_path for component in state.plan.components)


def test_pipeline_without_a_repo_root_still_runs(tmp_path: Path) -> None:
    config = SpecKitConfig.load(root=Path.cwd())
    config.memory_hub = MemoryHubConfig(case_studies_path=str(tmp_path / "cases"))
    pipeline = DeliveryPipeline(config, memory=MemoryHub(config.memory_hub))

    state = run_objective(
        pipeline,
        "Add a purchase-order agent so that finance stops keying orders by hand",
        raw_inputs=["Dana: the agent must read a purchase order and extract line items"],
    )

    assert pipeline.knowledge is None
    assert state.plan is not None and state.plan.placements == []
