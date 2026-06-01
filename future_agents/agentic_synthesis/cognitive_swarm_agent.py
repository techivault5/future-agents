"""CognitiveSwarmAgent — adaptive meta-agent synthesising all agentic AI capabilities.

Novel synthesis of 9 frameworks:
  MRKL      → AdaptiveRouter: modular expert routing per task type
  CrewAI    → SwarmCoordinator: specialist role crews
  MetaGPT   → SwarmCoordinator: structured company roles
  AutoGen   → SwarmCoordinator: multi-agent conversation
  Reflexion → ReflexionLoop: verbal RL self-improvement
  MemGPT    → LifelongMemory: tiered memory management
  Voyager   → LifelongMemory: persistent cross-session skill library
  BabyAGI   → AdaptiveRouter: task priority + complexity awareness
  LangGraph → CognitiveSwarmAgent: stateful execution with dynamic routing

Decision logic per complexity:
  TRIVIAL / SIMPLE  → direct single-call answer
  MODERATE          → ReflexionLoop (self-improving single agent)
  COMPLEX           → SwarmCoordinator (parallel 5-role crew)
  CRITICAL          → SwarmCoordinator + ReflexionLoop (maximum quality)
"""

from __future__ import annotations

from typing import Any

from future_agents.agentic_synthesis.adaptive_router import AdaptiveRouter, TaskComplexity
from future_agents.agentic_synthesis.lifelong_memory import LifelongMemory
from future_agents.agentic_synthesis.reflexion_loop import ReflexionLoop, ReflexionResult
from future_agents.agentic_synthesis.swarm_coordinator import (
    AgentRole,
    SwarmCoordinator,
    SwarmResult,
    SwarmSpec,
)
from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.core.events import EventBus
from future_agents.models.feedback import ExecutionOutcome

try:
    import anthropic as _anthropic
    _SDK_OK = True
except ImportError:
    _SDK_OK = False


class CognitiveSwarmAgent(BaseAgent):
    """Meta-agent that dynamically routes tasks to the optimal agentic strategy.

    Integrates:
    - AdaptiveRouter   — picks pattern + agent type per task
    - LifelongMemory   — retrieves relevant cross-session context
    - SwarmCoordinator — parallel specialist crew for complex tasks
    - ReflexionLoop    — iterative verbal RL for moderate/critical tasks
    """

    agent_type = "cognitive_swarm"

    @property
    def capabilities(self) -> list[str]:
        return [
            "cognitive_swarm.route",
            "cognitive_swarm.reflect",
            "cognitive_swarm.swarm",
            "cognitive_swarm.remember",
            "cognitive_swarm.forget",
            "cognitive_swarm.stats",
        ]

    def __init__(
        self,
        agent_id: str | None = None,
        event_bus: EventBus | None = None,
        memory_path=None,
    ) -> None:
        super().__init__(agent_id=agent_id, event_bus=event_bus)
        self._router = AdaptiveRouter()
        self._memory = LifelongMemory(memory_path=memory_path)
        self._client = _anthropic.Anthropic() if _SDK_OK else None
        self._swarm = SwarmCoordinator(client=self._client)
        self._reflexion = ReflexionLoop(client=self._client)

    # ── BaseAgent interface ───────────────────────────────────────────────────

    async def _execute(self, context: TaskContext) -> TaskResult:
        task = context.intent
        params = context.parameters or {}

        # Recall relevant memories to enrich context
        memories = self._memory.recall(task, top_k=3)
        mem_ctx: dict[str, Any] = {
            f"memory_{i}": m.entry.content[:200] for i, m in enumerate(memories)
        }

        decision = self._router.route(task, task_id=context.task_id, hints=params.get("hints", {}))
        result_data: dict[str, Any] = {
            "route": decision.rationale,
            "pattern": decision.pattern,
            "domain": decision.domain.value,
            "complexity": decision.complexity.value,
        }

        output = ""
        outcome = ExecutionOutcome.SUCCESS

        try:
            if decision.complexity in (TaskComplexity.TRIVIAL, TaskComplexity.SIMPLE):
                output = await self._direct(task, mem_ctx)
                result_data["strategy"] = "direct"

            elif decision.complexity == TaskComplexity.MODERATE:
                ref: ReflexionResult = await self._reflexion.run(task, context=mem_ctx)
                output = ref.final_answer
                result_data.update({
                    "strategy": "reflexion",
                    "attempts": ref.attempts,
                    "best_score": ref.best_score,
                    "tokens": ref.total_tokens,
                })
                if not ref.success:
                    outcome = ExecutionOutcome.PARTIAL

            elif decision.complexity == TaskComplexity.COMPLEX:
                swarm: SwarmResult = await self._run_swarm(task, mem_ctx)
                output = swarm.consensus
                result_data.update({
                    "strategy": "swarm",
                    "rounds": swarm.rounds,
                    "confidence": swarm.confidence,
                    "dissenting": len(swarm.dissenting_views),
                })

            else:  # CRITICAL: swarm feeds reflexion for maximum quality
                swarm = await self._run_swarm(task, mem_ctx)
                ref = await self._reflexion.run(
                    task,
                    evaluation_criteria="accuracy, completeness, safety, edge-case coverage",
                    context={"swarm_answer": swarm.consensus[:400], **mem_ctx},
                )
                output = ref.final_answer
                result_data.update({
                    "strategy": "swarm+reflexion",
                    "swarm_confidence": swarm.confidence,
                    "reflexion_score": ref.best_score,
                    "tokens": ref.total_tokens,
                })
                if not ref.success:
                    outcome = ExecutionOutcome.PARTIAL

        except Exception as exc:
            output = f"Execution error: {exc}"
            outcome = ExecutionOutcome.FAILURE
            result_data["error"] = str(exc)

        # Store successful results in episodic memory
        if outcome == ExecutionOutcome.SUCCESS and output:
            self._memory.remember(
                content=f"Task: {task[:100]}\nResult: {output[:200]}",
                memory_type="episodic",
                tags=["task", decision.domain.value],
                importance=0.6,
            )

        self._router.record_outcome(
            task_id=context.task_id, decision=decision, outcome=outcome.value
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=outcome,
            data={"output": output, **result_data},
        )

    def assess_self(self) -> dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "sdk_available": _SDK_OK,
            "router_stats": self._router.stats(),
            "memory_stats": self._memory.stats(),
            "patterns_used": [
                "AdaptiveRouter", "ReflexionLoop", "SwarmCoordinator", "LifelongMemory",
            ],
            "frameworks_synthesised": [
                "MRKL", "CrewAI", "MetaGPT", "AutoGen", "Reflexion",
                "MemGPT", "Voyager", "BabyAGI", "LangGraph",
            ],
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _direct(self, task: str, context: dict) -> str:
        if self._client is None:
            return f"[stub direct: {task[:60]}]"
        ctx_str = "\n".join(f"  {k}: {v}" for k, v in context.items()) if context else ""
        try:
            resp = self._client.messages.create(
                model="claude-opus-4-7",
                max_tokens=512,
                thinking={"type": "adaptive"},
                messages=[{
                    "role": "user",
                    "content": f"Task: {task}\n{ctx_str}\n\nAnswer concisely.",
                }],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        except Exception as exc:
            return f"Direct error: {exc}"

    async def _run_swarm(self, task: str, context: dict) -> SwarmResult:
        return await self._swarm.execute(SwarmSpec(
            task=task,
            roles=[
                AgentRole.RESEARCHER, AgentRole.PLANNER, AgentRole.EXECUTOR,
                AgentRole.CRITIC, AgentRole.SYNTHESIZER,
            ],
            context=context,
            max_rounds=2,
            consensus_threshold=0.65,
        ))
