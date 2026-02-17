"""Capability Agent — manages organizational capabilities."""

from __future__ import annotations

from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.capability import Capability, CapabilityLevel
from future_agents.models.feedback import ExecutionOutcome


class CapabilityAgent(BaseAgent):
    """Manages the organization's capability inventory.

    Handles:
    - Registering new capabilities
    - Tracking capability usage and proficiency levels
    - Identifying capability gaps
    - Auto-leveling based on usage patterns
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._capabilities_db: dict[str, Capability] = {}

    @property
    def agent_type(self) -> str:
        return "capability"

    @property
    def capabilities(self) -> list[str]:
        return [
            "capability.register",
            "capability.query",
            "capability.gap_analysis",
            "capability.usage_tracking",
        ]

    async def _execute(self, context: TaskContext) -> TaskResult:
        intent = context.intent
        params = context.parameters

        if intent == "capability.register":
            return await self._register_capability(context, params)
        elif intent == "capability.query":
            return await self._query_capabilities(context, params)
        elif intent == "capability.gap_analysis":
            return await self._gap_analysis(context, params)
        elif intent == "capability.record_usage":
            return await self._record_usage(context, params)
        else:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Unknown intent: {intent}"],
            )

    async def _register_capability(
        self, context: TaskContext, params: dict
    ) -> TaskResult:
        cap = Capability(
            name=params["name"],
            description=params.get("description", ""),
            domain=params.get("domain", "general"),
            level=CapabilityLevel(params.get("level", "novice")),
            tags=params.get("tags", []),
            dependencies=params.get("dependencies", []),
        )
        self._capabilities_db[cap.id] = cap

        await self.emit(
            "capability.registered",
            {"capability_id": cap.id, "name": cap.name, "domain": cap.domain},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"capability_id": cap.id, "capability": cap.model_dump(mode="json")},
        )

    async def _query_capabilities(
        self, context: TaskContext, params: dict
    ) -> TaskResult:
        domain = params.get("domain")
        level = params.get("level")
        tag = params.get("tag")

        results = list(self._capabilities_db.values())
        if domain:
            results = [c for c in results if c.domain == domain]
        if level:
            results = [c for c in results if c.level == CapabilityLevel(level)]
        if tag:
            results = [c for c in results if tag in c.tags]

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"capabilities": [c.model_dump(mode="json") for c in results]},
        )

    async def _gap_analysis(self, context: TaskContext, params: dict) -> TaskResult:
        required = params.get("required_capabilities", [])
        gaps = []
        for cap_name in required:
            matches = [c for c in self._capabilities_db.values() if c.name == cap_name]
            if not matches:
                gaps.append({"name": cap_name, "status": "missing"})
            else:
                best = max(matches, key=lambda c: c.success_rate)
                if best.level.value in ("novice", "intermediate") or best.success_rate < 0.6:
                    gaps.append({
                        "name": cap_name,
                        "status": "weak",
                        "current_level": best.level.value,
                        "success_rate": best.success_rate,
                    })

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"gaps": gaps, "total_required": len(required), "gap_count": len(gaps)},
            suggestions=[f"Address gap: {g['name']}" for g in gaps],
        )

    async def _record_usage(self, context: TaskContext, params: dict) -> TaskResult:
        cap_id = params.get("capability_id", "")
        success = params.get("success", True)

        cap = self._capabilities_db.get(cap_id)
        if not cap:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Capability not found: {cap_id}"],
            )

        old_level = cap.level
        cap.record_usage(success)

        data: dict[str, Any] = {
            "capability_id": cap_id,
            "new_usage_count": cap.usage_count,
            "new_success_rate": cap.success_rate,
        }
        if cap.level != old_level:
            data["leveled_up"] = True
            data["new_level"] = cap.level.value
            await self.emit("capability.leveled_up", data)

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data=data,
        )

    async def assess_self(self) -> dict[str, Any]:
        caps = list(self._capabilities_db.values())
        level_dist = {}
        for cap in caps:
            level_dist[cap.level.value] = level_dist.get(cap.level.value, 0) + 1
        return {
            "total_capabilities": len(caps),
            "level_distribution": level_dist,
            "avg_success_rate": (
                sum(c.success_rate for c in caps) / len(caps) if caps else 0
            ),
            "domains": list(set(c.domain for c in caps)),
        }
