"""Orchestrator — routes tasks, plans multi-step workflows, and evaluates outcomes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from future_agents.core.base_agent import TaskContext, TaskResult
from future_agents.core.events import Event, EventBus
from future_agents.core.registry import AgentRegistry
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import SyncEngine
from future_agents.models.feedback import ExecutionOutcome

logger = logging.getLogger(__name__)


@dataclass
class PlanStep:
    """A single step in a multi-step execution plan."""

    order: int
    intent: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)  # Step orders this depends on
    result: TaskResult | None = None


@dataclass
class ExecutionPlan:
    """A multi-step plan created by the orchestrator."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    original_intent: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "pending"  # pending, executing, completed, failed


class Orchestrator:
    """Central orchestrator that coordinates the entire agent system.

    Responsibilities:
    1. **Router** — Match intents to the best agent
    2. **Planner** — Break complex tasks into multi-step plans
    3. **Executor** — Execute plans step-by-step with dependency tracking
    4. **Evaluator** — Assess outcomes and feed back into the sync engine

    The orchestrator is the single entry point for all task execution.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        sync_engine: SyncEngine,
        metrics: MetricTracker,
        event_bus: EventBus,
    ) -> None:
        self.registry = registry
        self.sync_engine = sync_engine
        self.metrics = metrics
        self.event_bus = event_bus

    async def handle(self, intent: str, parameters: dict[str, Any] | None = None) -> TaskResult:
        """Main entry point — route a single task to the right agent and execute it."""
        context = TaskContext(intent=intent, parameters=parameters or {})

        # Find the best agent for this intent
        agent = self.registry.best_agent_for(intent)
        if not agent:
            # Try matching by prefix (e.g. "capability.register" -> "capability" agents)
            prefix = intent.split(".")[0] if "." in intent else intent
            agents = self.registry.find_by_type(prefix)
            agent = agents[0] if agents else None

        if not agent:
            logger.warning("No agent found for intent: %s", intent)
            self.metrics.increment("orchestrator.unroutable", labels={"intent": intent})
            return TaskResult(
                task_id=context.task_id,
                agent_id="orchestrator",
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"No agent available for intent: {intent}"],
            )

        self.metrics.increment("orchestrator.tasks_routed", labels={"intent": intent})
        result = await agent.execute(context)

        # Generate and store feedback
        feedback = agent.generate_feedback(result)
        self.sync_engine.add_feedback(feedback)

        # Track metrics
        self.metrics.record(
            "orchestrator.task_duration",
            result.duration_ms,
            labels={"intent": intent, "agent": agent.agent_id},
        )
        self.metrics.increment(
            f"orchestrator.outcome.{result.outcome.value}",
            labels={"intent": intent},
        )

        await self.event_bus.emit(
            Event(
                type="orchestrator.task_completed",
                source="orchestrator",
                data={
                    "task_id": context.task_id,
                    "intent": intent,
                    "agent_id": agent.agent_id,
                    "outcome": result.outcome.value,
                },
            )
        )

        return result

    async def execute_plan(self, plan: ExecutionPlan) -> list[TaskResult]:
        """Execute a multi-step plan in dependency order."""
        plan.status = "executing"
        results: dict[int, TaskResult] = {}
        all_results: list[TaskResult] = []

        for step in sorted(plan.steps, key=lambda s: s.order):
            # Check dependencies
            for dep in step.depends_on:
                dep_result = results.get(dep)
                if dep_result and dep_result.outcome == ExecutionOutcome.FAILURE:
                    step.result = TaskResult(
                        task_id=uuid4().hex[:12],
                        agent_id="orchestrator",
                        outcome=ExecutionOutcome.SKIPPED,
                        errors=[f"Dependency step {dep} failed"],
                    )
                    results[step.order] = step.result
                    all_results.append(step.result)
                    continue

            # Merge data from dependency results into parameters
            merged_params = dict(step.parameters)
            for dep in step.depends_on:
                dep_result = results.get(dep)
                if dep_result and dep_result.data:
                    merged_params[f"_step_{dep}_result"] = dep_result.data

            result = await self.handle(step.intent, merged_params)
            step.result = result
            results[step.order] = result
            all_results.append(result)

        # Determine overall plan status
        outcomes = [r.outcome for r in all_results]
        if all(o == ExecutionOutcome.SUCCESS for o in outcomes):
            plan.status = "completed"
        elif any(o == ExecutionOutcome.FAILURE for o in outcomes):
            plan.status = "failed"
        else:
            plan.status = "completed"

        return all_results

    def create_plan(self, intent: str, steps: list[dict[str, Any]]) -> ExecutionPlan:
        """Create an execution plan from a list of step definitions."""
        plan_steps = [
            PlanStep(
                order=i + 1,
                intent=s["intent"],
                parameters=s.get("parameters", {}),
                depends_on=s.get("depends_on", []),
            )
            for i, s in enumerate(steps)
        ]
        return ExecutionPlan(
            original_intent=intent,
            steps=plan_steps,
        )

    async def system_health(self) -> dict[str, Any]:
        """Get comprehensive system health report."""
        registry_health = await self.registry.health_check()
        metrics_summary = self.metrics.summary()
        improvements = self.sync_engine.improvements

        return {
            "agents": registry_health,
            "metrics": metrics_summary,
            "pending_improvements": len([i for i in improvements if i.status == "proposed"]),
            "applied_improvements": len([i for i in improvements if i.status == "applied"]),
        }
