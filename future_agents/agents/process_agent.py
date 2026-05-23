"""Process Agent — manages organizational workflows and SOPs."""

from __future__ import annotations

from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.feedback import ExecutionOutcome
from future_agents.models.process import Process, ProcessStatus, ProcessStep


class ProcessAgent(BaseAgent):
    """Manages organizational processes and workflows.

    Handles:
    - Defining and versioning processes
    - Executing process workflows step-by-step
    - Tracking process performance metrics
    - Recommending process optimizations
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._processes: dict[str, Process] = {}

    @property
    def agent_type(self) -> str:
        return "process"

    @property
    def capabilities(self) -> list[str]:
        return [
            "process.define",
            "process.execute",
            "process.query",
            "process.optimize",
        ]

    async def _execute(self, context: TaskContext) -> TaskResult:
        intent = context.intent
        params = context.parameters

        handlers = {
            "process.define": self._define_process,
            "process.execute": self._execute_process,
            "process.query": self._query_processes,
            "process.optimize": self._optimize,
        }
        handler = handlers.get(intent)
        if not handler:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Unknown intent: {intent}"],
            )
        return await handler(context, params)

    async def _define_process(self, context: TaskContext, params: dict) -> TaskResult:
        steps = [
            ProcessStep(
                order=i + 1,
                name=s["name"],
                description=s.get("description", ""),
                responsible_agent=s.get("responsible_agent"),
                required_capabilities=s.get("required_capabilities", []),
                required_policies=s.get("required_policies", []),
                is_optional=s.get("is_optional", False),
            )
            for i, s in enumerate(params.get("steps", []))
        ]

        process = Process(
            name=params["name"],
            description=params.get("description", ""),
            domain=params.get("domain", "general"),
            steps=steps,
            tags=params.get("tags", []),
            trigger_conditions=params.get("trigger_conditions", []),
            status=ProcessStatus.ACTIVE,
        )
        self._processes[process.id] = process

        await self.emit(
            "process.defined",
            {"process_id": process.id, "name": process.name, "step_count": len(steps)},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"process_id": process.id, "process": process.model_dump(mode="json")},
        )

    async def _execute_process(self, context: TaskContext, params: dict) -> TaskResult:
        process_id = params.get("process_id", "")
        process = self._processes.get(process_id)
        if not process:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Process not found: {process_id}"],
            )

        # Simulate step-by-step execution tracking
        completed_steps = 0
        step_results = []
        for step in sorted(process.steps, key=lambda s: s.order):
            step_results.append(
                {
                    "step": step.order,
                    "name": step.name,
                    "status": "completed",
                    "responsible_agent": step.responsible_agent,
                }
            )
            completed_steps += 1

        process.record_execution(completed_steps)

        await self.emit(
            "process.executed",
            {
                "process_id": process_id,
                "steps_completed": completed_steps,
                "total_steps": len(process.steps),
            },
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "process_id": process_id,
                "steps_completed": completed_steps,
                "step_results": step_results,
                "avg_completion_rate": process.avg_completion_rate,
            },
        )

    async def _query_processes(self, context: TaskContext, params: dict) -> TaskResult:
        domain = params.get("domain")
        status = params.get("status")
        results = list(self._processes.values())
        if domain:
            results = [p for p in results if p.domain == domain]
        if status:
            results = [p for p in results if p.status == ProcessStatus(status)]

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"processes": [p.model_dump(mode="json") for p in results]},
        )

    async def _optimize(self, context: TaskContext, params: dict) -> TaskResult:
        suggestions = []
        for process in self._processes.values():
            if process.execution_count >= 3 and process.avg_completion_rate < 0.8:
                suggestions.append(
                    {
                        "process_id": process.id,
                        "name": process.name,
                        "avg_completion_rate": process.avg_completion_rate,
                        "suggestion": "Review failing steps; consider splitting or adding prerequisites",
                    }
                )
            # Flag processes with unused optional steps
            optional_steps = [s for s in process.steps if s.is_optional]
            if len(optional_steps) > len(process.steps) * 0.5:
                suggestions.append(
                    {
                        "process_id": process.id,
                        "name": process.name,
                        "suggestion": "Too many optional steps — consider splitting into separate processes",
                    }
                )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"suggestions": suggestions},
            suggestions=[s["suggestion"] for s in suggestions],
        )

    async def assess_self(self) -> dict[str, Any]:
        processes = list(self._processes.values())
        return {
            "total_processes": len(processes),
            "active_processes": len([p for p in processes if p.status == ProcessStatus.ACTIVE]),
            "avg_completion_rate": (
                sum(p.avg_completion_rate for p in processes) / len(processes) if processes else 0
            ),
            "total_executions": sum(p.execution_count for p in processes),
        }
