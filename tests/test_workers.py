"""Smoke tests for the scheduled worker system."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from future_agents.core.events import EventBus
from future_agents.core.registry import AgentRegistry
from future_agents.definitions.factory import AgentFactory
from future_agents.infrastructure.knowledge_store import KnowledgeStore
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import SyncEngine
from future_agents.workers import (
    AgentGathererWorker,
    CodeImprovementWorker,
    PatternDiscoveryWorker,
    WorkerScheduler,
    WorkerStatus,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def infra():
    bus = EventBus()
    metrics = MetricTracker()
    store = KnowledgeStore(event_bus=bus)
    registry = AgentRegistry(event_bus=bus)
    engine = SyncEngine(
        registry=registry,
        knowledge_store=store,
        metrics=metrics,
        event_bus=bus,
    )
    return {
        "bus": bus,
        "metrics": metrics,
        "store": store,
        "registry": registry,
        "engine": engine,
    }


@pytest.fixture
def code_worker(infra, tmp_path):
    return CodeImprovementWorker(
        sync_engine=infra["engine"],
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        source_root=tmp_path,
        interval_seconds=60,
    )


@pytest.fixture
def pattern_worker(infra):
    return PatternDiscoveryWorker(
        registry=infra["registry"],
        sync_engine=infra["engine"],
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        interval_seconds=120,
    )


@pytest.fixture
def gatherer_worker(infra, tmp_path):
    return AgentGathererWorker(
        registry=infra["registry"],
        factory=AgentFactory(event_bus=infra["bus"]),
        sync_engine=infra["engine"],
        knowledge_store=infra["store"],
        metrics=infra["metrics"],
        event_bus=infra["bus"],
        definitions_dir=tmp_path / "agents",
        interval_seconds=180,
    )


# ── BaseWorker contract ───────────────────────────────────────────────────────


def test_worker_types_are_unique(code_worker, pattern_worker, gatherer_worker):
    types = {code_worker.worker_type, pattern_worker.worker_type, gatherer_worker.worker_type}
    assert len(types) == 3


def test_worker_initial_state(code_worker):
    assert code_worker.status == WorkerStatus.IDLE
    assert code_worker.run_count == 0
    assert code_worker.error_count == 0
    assert code_worker.last_run is None


def test_worker_get_status_keys(code_worker):
    status = code_worker.get_status()
    for key in ("worker_id", "worker_type", "status", "enabled",
                "interval_seconds", "run_count", "error_count",
                "last_run", "next_run"):
        assert key in status


# ── Execution ─────────────────────────────────────────────────────────────────


async def test_code_improvement_worker_runs(code_worker):
    result = await code_worker.execute()
    assert result.success
    assert result.worker_id == code_worker.worker_id
    assert code_worker.run_count == 1
    assert code_worker.status == WorkerStatus.IDLE
    assert result.duration_ms > 0


async def test_pattern_discovery_worker_runs(pattern_worker):
    result = await pattern_worker.execute()
    assert result.success
    assert "patterns_found" in result.data
    assert "anti_patterns_found" in result.data


async def test_agent_gatherer_worker_runs(gatherer_worker):
    result = await gatherer_worker.execute()
    assert result.success
    assert "gaps_found" in result.data
    assert "registered_agents" in result.data


async def test_disabled_worker_returns_failure(code_worker):
    code_worker.enabled = False
    result = await code_worker.execute()
    assert not result.success
    assert result.errors


# ── WorkerScheduler ───────────────────────────────────────────────────────────


def test_scheduler_register(code_worker):
    scheduler = WorkerScheduler()
    scheduler.register(code_worker)
    status = scheduler.get_status()
    assert status["worker_count"] == 1
    assert code_worker.worker_id in status["workers"]


async def test_scheduler_run_now(code_worker):
    scheduler = WorkerScheduler()
    scheduler.register(code_worker)
    result = await scheduler.run_now(code_worker.worker_id)
    assert result is not None
    assert result.success


async def test_scheduler_run_now_unknown_id(code_worker):
    scheduler = WorkerScheduler()
    scheduler.register(code_worker)
    result = await scheduler.run_now("does_not_exist")
    assert result is None


async def test_scheduler_start_stop(code_worker):
    scheduler = WorkerScheduler()
    scheduler.register(code_worker)
    await scheduler.start()
    assert scheduler._running
    # Give the jitter sleep a moment then stop
    await asyncio.sleep(0.05)
    await scheduler.stop()
    assert not scheduler._running


# ── AgentSystem integration ───────────────────────────────────────────────────


async def test_agent_system_has_workers():
    from future_agents.system import AgentSystem

    system = AgentSystem()
    await system.start()
    try:
        status = system.worker_status()
        assert status["worker_count"] == 3
        types = {w["worker_type"] for w in status["workers"].values()}
        assert types == {"code_improvement", "pattern_discovery", "agent_gatherer"}
    finally:
        await system.stop()


async def test_agent_system_run_worker():
    from future_agents.system import AgentSystem

    system = AgentSystem()
    await system.start()
    try:
        worker_id = next(iter(system.scheduler._workers))
        result = await system.run_worker(worker_id)
        assert result is not None
        assert result["success"] is True
    finally:
        await system.stop()
