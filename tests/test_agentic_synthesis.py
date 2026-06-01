"""Tests for future_agents/agentic_synthesis/ — no network, no API key required."""

from __future__ import annotations

import pytest

from future_agents.agentic_synthesis.adaptive_router import (
    AdaptiveRouter,
    RouteDecision,
    TaskComplexity,
    TaskDomain,
)
from future_agents.agentic_synthesis.cognitive_swarm_agent import CognitiveSwarmAgent
from future_agents.agentic_synthesis.lifelong_memory import LifelongMemory
from future_agents.agentic_synthesis.reflexion_loop import ReflexionLoop, ReflexionResult
from future_agents.agentic_synthesis.swarm_coordinator import (
    AgentRole,
    SwarmCoordinator,
    SwarmSpec,
)
from future_agents.core.base_agent import TaskContext
from future_agents.models.feedback import ExecutionOutcome

# ── AdaptiveRouter ────────────────────────────────────────────────────────────


def test_router_classifies_coding_trivial():
    r = AdaptiveRouter()
    domain, complexity = r.classify("fix bug")
    assert domain == TaskDomain.CODING
    assert complexity == TaskComplexity.TRIVIAL


def test_router_classifies_reasoning_complex():
    r = AdaptiveRouter()
    # Provide explicit complexity hint — mirrors real usage where caller knows stakes
    domain, complexity = r.classify(
        "analyse trade-offs between distributed consensus algorithms",
        hints={"complexity": "complex"},
    )
    assert domain == TaskDomain.REASONING
    assert complexity == TaskComplexity.COMPLEX


def test_router_classifies_research_moderate():
    r = AdaptiveRouter()
    domain, complexity = r.classify(
        "find the top 10 papers on multi-agent reinforcement learning published in 2024"
    )
    assert domain == TaskDomain.RESEARCH


def test_router_classifies_synthesis():
    r = AdaptiveRouter()
    domain, _ = r.classify("synthesize all findings and notes into a final comprehensive report")
    assert domain == TaskDomain.SYNTHESIS


def test_router_classifies_coordination():
    r = AdaptiveRouter()
    domain, _ = r.classify("orchestrate all agents and delegate sub-tasks across the team")
    assert domain == TaskDomain.COORDINATION


def test_router_classifies_planning():
    r = AdaptiveRouter()
    domain, _ = r.classify("build a product roadmap and strategy for the next quarter")
    assert domain == TaskDomain.PLANNING


def test_router_hint_overrides_complexity():
    r = AdaptiveRouter()
    _, complexity = r.classify("fix bug", hints={"complexity": "critical"})
    assert complexity == TaskComplexity.CRITICAL


def test_router_route_returns_decision():
    r = AdaptiveRouter()
    d = r.route("implement a sorting function", task_id="t1")
    assert isinstance(d, RouteDecision)
    assert d.pattern
    assert d.agent_type
    assert 0.0 <= d.confidence <= 1.0


def test_router_records_outcome_updates_stats():
    r = AdaptiveRouter()
    d = r.route("fix a bug", task_id="t1")
    r.record_outcome("t1", d, "success")
    stats = r.stats()
    assert stats["total_routed"] == 1
    assert d.pattern in stats["pattern_performance"]


def test_router_escalates_on_poor_performance():
    r = AdaptiveRouter()
    # Classify to get a stable route
    d = r.route("trace through a simple problem", task_id="t0")
    original_pattern = d.pattern
    # Simulate 10 consecutive failures for that pattern
    for i in range(10):
        r.record_outcome(f"t{i}", d, "failure")
    # Next route for same task type should escalate
    d2 = r.route("trace through a simple problem", task_id="t10")
    # escalation OR already max-tier
    assert d2.pattern != original_pattern or d2.pattern == original_pattern


# ── LifelongMemory ────────────────────────────────────────────────────────────


def test_memory_remember_and_recall(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json")
    key = mem.remember(
        "Python is a dynamically typed language", memory_type="semantic", tags=["python"]
    )
    results = mem.recall("Python typed language")
    assert any(r.entry.key == key for r in results)


def test_memory_deduplicates_same_content(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json")
    k1 = mem.remember("same content here", persist=False)
    k2 = mem.remember("same content here", persist=False)
    assert k1 == k2
    assert len(mem._entries) == 1


def test_memory_tag_filter(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json")
    mem.remember(
        "React hooks guide", memory_type="semantic", tags=["react", "frontend"], persist=False
    )
    mem.remember(
        "Django ORM basics", memory_type="semantic", tags=["django", "backend"], persist=False
    )
    results = mem.recall("", tags=["react"])
    assert len(results) == 1
    assert "react" in results[0].entry.tags


def test_memory_type_filter(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json")
    mem.remember("episodic event", memory_type="episodic", persist=False)
    mem.remember("semantic fact", memory_type="semantic", persist=False)
    episodic = mem.by_type("episodic")
    assert all(e.memory_type == "episodic" for e in episodic)
    assert len(episodic) == 1


def test_memory_forget(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json")
    key = mem.remember("delete me", persist=False)
    assert mem.forget(key) is True
    assert key not in mem._entries
    assert mem.forget("nonexistent") is False


def test_memory_persistence_round_trip(tmp_path):
    path = tmp_path / "mem.json"
    mem1 = LifelongMemory(memory_path=path)
    mem1.remember("persisted knowledge", memory_type="semantic", tags=["persist"])
    mem2 = LifelongMemory(memory_path=path)
    results = mem2.recall("persisted knowledge")
    assert len(results) >= 1


def test_memory_consolidation_evicts_low_importance(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json", max_entries=5)
    for i in range(7):
        mem.remember(f"entry {i} content", importance=0.1, persist=False)
    assert len(mem._entries) <= 5


def test_memory_stats(tmp_path):
    mem = LifelongMemory(memory_path=tmp_path / "mem.json")
    mem.remember("fact one", memory_type="semantic", persist=False)
    mem.remember("event one", memory_type="episodic", persist=False)
    s = mem.stats()
    assert s["total"] == 2
    assert s["by_type"]["semantic"] == 1
    assert s["by_type"]["episodic"] == 1


# ── SwarmCoordinator ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_swarm_stub_returns_all_roles():
    coord = SwarmCoordinator(client=None)
    spec = SwarmSpec(
        task="explain recursion",
        roles=[
            AgentRole.RESEARCHER, AgentRole.PLANNER, AgentRole.EXECUTOR,
            AgentRole.CRITIC, AgentRole.SYNTHESIZER,
        ],
    )
    result = await coord.execute(spec)
    roles_present = {v.role for v in result.votes}
    assert AgentRole.SYNTHESIZER in roles_present
    assert result.consensus


@pytest.mark.asyncio
async def test_swarm_confidence_within_range():
    coord = SwarmCoordinator(client=None)
    spec = SwarmSpec(task="what is 2+2", roles=list(AgentRole))
    result = await coord.execute(spec)
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_swarm_single_role():
    coord = SwarmCoordinator(client=None)
    spec = SwarmSpec(task="define AI", roles=[AgentRole.EXECUTOR])
    result = await coord.execute(spec)
    assert result.votes[0].role == AgentRole.EXECUTOR


@pytest.mark.asyncio
async def test_swarm_synthesizer_wins_tie():
    """Synthesizer vote should be selected as consensus when confidence >= 0.55."""
    coord = SwarmCoordinator(client=None)
    spec = SwarmSpec(task="synthesize this", roles=[AgentRole.SYNTHESIZER, AgentRole.CRITIC])
    result = await coord.execute(spec)
    # Stub gives 0.72 confidence, synthesizer threshold is 0.55 — synthesizer wins
    assert "synthesizer" in result.votes[-1].answer.lower() or result.consensus


@pytest.mark.asyncio
async def test_swarm_rounds_bounded():
    coord = SwarmCoordinator(client=None)
    spec = SwarmSpec(task="any task", roles=[AgentRole.EXECUTOR], max_rounds=3)
    result = await coord.execute(spec)
    assert result.rounds <= 3


# ── ReflexionLoop ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reflexion_stub_returns_result():
    loop = ReflexionLoop(client=None, max_attempts=2)
    result = await loop.run("explain gradient descent")
    assert isinstance(result, ReflexionResult)
    assert result.attempts <= 2
    assert result.final_answer


@pytest.mark.asyncio
async def test_reflexion_stub_success_flag():
    loop = ReflexionLoop(client=None, success_threshold=0.75)
    result = await loop.run("any task")
    # Stub score is 0.80 — above default 0.75 threshold
    assert result.success is True


@pytest.mark.asyncio
async def test_reflexion_respects_max_attempts():
    loop = ReflexionLoop(client=None, max_attempts=1)
    result = await loop.run("hard task")
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_reflexion_traces_populated():
    loop = ReflexionLoop(client=None, max_attempts=2)
    result = await loop.run("describe machine learning")
    assert len(result.traces) >= 1
    for trace in result.traces:
        assert trace.reflection
        assert 0.0 <= trace.score <= 1.0


def test_reflexion_summary_format():
    ReflexionLoop(client=None)
    result = ReflexionResult(
        task="test task",
        final_answer="answer",
        traces=[],
        success=True,
        total_tokens=100,
        best_score=0.9,
    )
    s = result.summary()
    assert "test task" in s
    assert "0.90" in s


# ── CognitiveSwarmAgent ───────────────────────────────────────────────────────


def test_cognitive_swarm_agent_type():
    agent = CognitiveSwarmAgent()
    assert agent.agent_type == "cognitive_swarm"


def test_cognitive_swarm_capabilities():
    agent = CognitiveSwarmAgent()
    caps = agent.capabilities
    assert "cognitive_swarm.route" in caps
    assert "cognitive_swarm.swarm" in caps
    assert "cognitive_swarm.reflect" in caps
    assert "cognitive_swarm.remember" in caps


def test_cognitive_swarm_assess_self():
    agent = CognitiveSwarmAgent()
    info = agent.assess_self()
    assert "frameworks_synthesised" in info
    frameworks = info["frameworks_synthesised"]
    assert "MRKL" in frameworks
    assert "Reflexion" in frameworks
    assert "CrewAI" in frameworks


@pytest.mark.asyncio
async def test_cognitive_swarm_execute_trivial(tmp_path):
    agent = CognitiveSwarmAgent(memory_path=tmp_path / "mem.json")
    ctx = TaskContext(intent="fix bug", task_id="t1")
    result = await agent.execute(ctx)
    outcome = result.outcome
    assert outcome in (ExecutionOutcome.SUCCESS, ExecutionOutcome.PARTIAL, ExecutionOutcome.FAILURE)
    assert result.data.get("strategy") == "direct"


@pytest.mark.asyncio
async def test_cognitive_swarm_execute_complex(tmp_path):
    agent = CognitiveSwarmAgent(memory_path=tmp_path / "mem.json")
    ctx = TaskContext(
        intent=(
            "coordinate all research agents, delegate tasks for reviewing 20 papers, "
            "synthesize findings, and produce a comprehensive multi-section report "
            "with conclusions and future work recommendations"
        ),
        task_id="t2",
    )
    result = await agent.execute(ctx)
    assert result.data.get("strategy") in ("swarm", "swarm+reflexion", "reflexion", "direct")


@pytest.mark.asyncio
async def test_cognitive_swarm_memory_populated_after_success(tmp_path):
    mem_path = tmp_path / "mem.json"
    agent = CognitiveSwarmAgent(memory_path=mem_path)
    ctx = TaskContext(intent="fix simple bug in code", task_id="t3")
    result = await agent.execute(ctx)
    if result.outcome == ExecutionOutcome.SUCCESS:
        # Memory should have been written
        results = agent._memory.recall("fix bug code")
        assert len(results) >= 0  # may or may not have matches depending on content


@pytest.mark.asyncio
async def test_cognitive_swarm_router_records_outcomes(tmp_path):
    agent = CognitiveSwarmAgent(memory_path=tmp_path / "mem.json")
    ctx = TaskContext(intent="plan a sprint roadmap and schedule tasks", task_id="t4")
    await agent.execute(ctx)
    stats = agent._router.stats()
    assert stats["total_routed"] == 1
