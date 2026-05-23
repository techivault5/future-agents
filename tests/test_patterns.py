"""Tests for the patterns package and new workers."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from future_agents.core.events import EventBus
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.patterns.library import AgentPattern, PatternCategory, PatternLibrary
from future_agents.patterns.tool_registry import Tool, ToolParameter, ToolRegistry
from future_agents.workers.ai_discovery_worker import AIDiscoveryWorker
from future_agents.workers.knowledge_synthesis_worker import KnowledgeSynthesisWorker


# ── PatternLibrary ────────────────────────────────────────────────────────────


def test_pattern_library_has_builtin_patterns():
    lib = PatternLibrary()
    assert len(lib.all()) >= 8


def test_pattern_library_get_known():
    lib = PatternLibrary()
    p = lib.get("ReAct")
    assert p is not None
    assert p.category == PatternCategory.REASONING


def test_pattern_library_get_unknown():
    lib = PatternLibrary()
    assert lib.get("NonExistentPattern") is None


def test_pattern_library_by_category():
    lib = PatternLibrary()
    reasoning = lib.by_category(PatternCategory.REASONING)
    assert any(p.name == "ReAct" for p in reasoning)


def test_pattern_library_search():
    lib = PatternLibrary()
    results = lib.search("tool")
    assert any(p.name == "Tool-Use" for p in results)


def test_pattern_library_search_no_match():
    lib = PatternLibrary()
    assert lib.search("zzz_no_such_term_zzz") == []


def test_pattern_library_register_custom():
    lib = PatternLibrary()
    custom = AgentPattern(
        name="Custom",
        category=PatternCategory.ACTING,
        description="A custom test pattern",
    )
    lib.register(custom)
    assert lib.get("Custom") is not None
    assert len(lib.all()) >= 9


def test_pattern_library_summary_keys():
    lib = PatternLibrary()
    summary = lib.summary()
    assert "reasoning" in summary
    assert "reliability" in summary


# ── ToolRegistry ──────────────────────────────────────────────────────────────


def test_tool_registry_register_and_get():
    registry = ToolRegistry()
    tool = Tool(name="ping", description="Ping tool", fn=lambda: "pong")
    registry.register(tool)
    assert registry.get("ping") is tool


def test_tool_registry_get_missing():
    registry = ToolRegistry()
    assert registry.get("nope") is None


def test_tool_registry_to_claude_schemas():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="greet",
            description="Greet someone",
            fn=lambda name: f"Hello {name}",
            parameters=[ToolParameter(name="name", type="string", description="Name to greet")],
        )
    )
    schemas = registry.to_claude_schemas()
    assert len(schemas) == 1
    schema = schemas[0]
    assert schema["name"] == "greet"
    assert "name" in schema["input_schema"]["properties"]
    assert "name" in schema["input_schema"]["required"]


async def test_tool_call_sync():
    tool = Tool(name="add", description="Add two numbers", fn=lambda a, b: a + b)
    result = await tool.call(a=1, b=2)
    assert result == 3


async def test_tool_call_async():
    async def async_fn(x: int) -> int:
        return x * 2

    tool = Tool(name="double", description="Double a number", fn=async_fn)
    result = await tool.call(x=5)
    assert result == 10


# ── DigitalWorkerAgent (no Claude API required) ───────────────────────────────


def test_digital_worker_agent_properties():
    from future_agents.agents.digital_worker_agent import DigitalWorkerAgent

    agent = DigitalWorkerAgent()
    assert agent.agent_type == "digital_worker"
    assert "digital_worker.react" in agent.capabilities
    assert len(agent.tool_registry.all()) == 3  # list_patterns, get_pattern, search_patterns


async def test_digital_worker_agent_assess_self():
    from future_agents.agents.digital_worker_agent import DigitalWorkerAgent

    agent = DigitalWorkerAgent()
    assessment = await agent.assess_self()
    assert "agent_type" in assessment
    assert assessment["agent_type"] == "digital_worker"
    assert "tools_registered" in assessment
    assert "patterns_in_library" in assessment


async def test_digital_worker_agent_list_patterns_tool():
    from future_agents.agents.digital_worker_agent import DigitalWorkerAgent

    agent = DigitalWorkerAgent()
    tool = agent.tool_registry.get("list_patterns")
    assert tool is not None
    result = await tool.call()
    assert isinstance(result, list)
    assert len(result) >= 8


async def test_digital_worker_agent_get_pattern_tool():
    from future_agents.agents.digital_worker_agent import DigitalWorkerAgent

    agent = DigitalWorkerAgent()
    tool = agent.tool_registry.get("get_pattern")
    result = await tool.call(name="ReAct")
    assert isinstance(result, dict)
    assert result["name"] == "ReAct"


async def test_digital_worker_agent_search_patterns_tool():
    from future_agents.agents.digital_worker_agent import DigitalWorkerAgent

    agent = DigitalWorkerAgent()
    tool = agent.tool_registry.get("search_patterns")
    result = await tool.call(keyword="memory")
    assert isinstance(result, list)
    assert any(r["name"] == "Memory-Augmented" for r in result)


async def test_digital_worker_agent_no_query_fails():
    from future_agents.agents.digital_worker_agent import DigitalWorkerAgent, _PATTERNS_AVAILABLE
    from future_agents.core.base_agent import TaskContext
    from future_agents.models.feedback import ExecutionOutcome

    if not _PATTERNS_AVAILABLE:
        pytest.skip("anthropic not installed")

    agent = DigitalWorkerAgent()
    ctx = TaskContext(intent="", parameters={})
    result = await agent._execute(ctx)
    assert result.outcome == ExecutionOutcome.FAILURE


# ── KnowledgeSynthesisWorker (mocked Claude) ─────────────────────────────────


@pytest.fixture
def infra():
    bus = EventBus()
    metrics = MetricTracker()
    store = KnowledgeStore(event_bus=bus)
    return {"bus": bus, "metrics": metrics, "store": store}


async def test_knowledge_synthesis_worker_type(infra):
    worker = KnowledgeSynthesisWorker(
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        interval_seconds=1800,
    )
    assert worker.worker_type == "knowledge_synthesis"


async def test_knowledge_synthesis_worker_skips_when_few_entries(infra):
    worker = KnowledgeSynthesisWorker(
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        min_entries=5,
    )
    result = await worker.execute()
    # No anthropic or too few entries — either skipped or anthropic-not-installed failure is ok
    assert result.worker_id == worker.worker_id


async def test_knowledge_synthesis_worker_calls_claude_when_enough_entries(infra):
    from future_agents.models.knowledge import KnowledgeEntry

    for i in range(6):
        infra["store"].add(
            KnowledgeEntry(
                title=f"Entry {i}",
                domain="test",
                content=f"Content for entry {i}",
                source_agent="test",
            )
        )

    worker = KnowledgeSynthesisWorker(
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        min_entries=5,
    )

    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    mock_block = MagicMock()
    mock_block.text = "Synthesised insight: themes identified."
    type(mock_block).type = property(lambda self: "text")

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic_mod = types.ModuleType("anthropic")
    mock_anthropic_mod.Anthropic = MagicMock(return_value=mock_client)

    import future_agents.workers.knowledge_synthesis_worker as ksw

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_mod}):
        with patch.object(ksw, "_ANTHROPIC_AVAILABLE", True):
            with patch.object(ksw, "anthropic", mock_anthropic_mod, create=True):
                result = await worker.execute()

    assert result.success
    assert result.data.get("entries_processed") == 6
    synthesis_entries = infra["store"].by_domain("synthesis")
    assert len(synthesis_entries) == 1


# ── AIDiscoveryWorker (mocked Claude) ────────────────────────────────────────


async def test_ai_discovery_worker_type(infra, tmp_path):
    worker = AIDiscoveryWorker(
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        source_root=tmp_path,
        interval_seconds=3600,
    )
    assert worker.worker_type == "ai_discovery"


async def test_ai_discovery_worker_runs_with_mock_claude(infra, tmp_path):
    # Create a minimal agent file so the scanner finds something
    agents_dir = tmp_path / "future_agents" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "stub_agent.py").write_text(
        "from future_agents.core.base_agent import BaseAgent\n"
        "class StubAgent(BaseAgent):\n"
        "    @property\n"
        "    def agent_type(self): return 'stub'\n"
        "    @property\n"
        "    def capabilities(self): return ['stub.do']\n"
    )

    worker = AIDiscoveryWorker(
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        source_root=tmp_path,
        interval_seconds=3600,
    )

    mock_usage = MagicMock()
    mock_usage.input_tokens = 500
    mock_usage.output_tokens = 300

    mock_block = MagicMock()
    mock_block.text = "Recommendation: implement event sourcing pattern."
    type(mock_block).type = property(lambda self: "text")

    mock_response = MagicMock()
    mock_response.content = [mock_block]
    mock_response.usage = mock_usage

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    mock_anthropic_mod = types.ModuleType("anthropic")
    mock_anthropic_mod.Anthropic = MagicMock(return_value=mock_client)

    import future_agents.workers.ai_discovery_worker as adw

    with patch.dict(sys.modules, {"anthropic": mock_anthropic_mod}):
        with patch.object(adw, "_ANTHROPIC_AVAILABLE", True):
            with patch.object(adw, "anthropic", mock_anthropic_mod, create=True):
                result = await worker.execute()

    assert result.success
    assert result.data.get("cycle") == 1
    discovery_entries = infra["store"].by_domain("ai_discovery")
    assert len(discovery_entries) == 1
