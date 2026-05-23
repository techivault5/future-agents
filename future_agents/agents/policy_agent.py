"""Policy Agent — manages and enforces organizational policies."""

from __future__ import annotations

from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.feedback import ExecutionOutcome
from future_agents.models.policy import Policy, PolicyRule, PolicyScope, PolicyStatus


class PolicyAgent(BaseAgent):
    """Manages organizational policies and compliance.

    Handles:
    - Defining and versioning policies
    - Checking actions against applicable policies
    - Tracking compliance rates
    - Recommending policy updates based on violation patterns
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._policies: dict[str, Policy] = {}

    @property
    def agent_type(self) -> str:
        return "policy"

    @property
    def capabilities(self) -> list[str]:
        return [
            "policy.define",
            "policy.check",
            "policy.query",
            "policy.compliance_report",
        ]

    async def _execute(self, context: TaskContext) -> TaskResult:
        intent = context.intent
        params = context.parameters

        handlers = {
            "policy.define": self._define_policy,
            "policy.check": self._check_policy,
            "policy.query": self._query_policies,
            "policy.compliance_report": self._compliance_report,
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

    async def _define_policy(self, context: TaskContext, params: dict) -> TaskResult:
        rules = [
            PolicyRule(
                condition=r["condition"],
                action=r["action"],
                severity=r.get("severity", "medium"),
                auto_enforce=r.get("auto_enforce", False),
            )
            for r in params.get("rules", [])
        ]

        policy = Policy(
            name=params["name"],
            description=params.get("description", ""),
            scope=PolicyScope(params.get("scope", "global")),
            scope_target=params.get("scope_target"),
            status=PolicyStatus.ACTIVE,
            rules=rules,
            tags=params.get("tags", []),
        )
        self._policies[policy.id] = policy

        await self.emit(
            "policy.defined",
            {"policy_id": policy.id, "name": policy.name, "rule_count": len(rules)},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"policy_id": policy.id, "policy": policy.model_dump(mode="json")},
        )

    async def _check_policy(self, context: TaskContext, params: dict) -> TaskResult:
        action_context = params.get("context", {})
        domain = params.get("domain")
        agent_id = params.get("agent_id")

        # Find applicable policies
        applicable = []
        for policy in self._policies.values():
            if policy.status != PolicyStatus.ACTIVE:
                continue
            if policy.scope == PolicyScope.GLOBAL:
                applicable.append(policy)
            elif policy.scope == PolicyScope.DOMAIN and policy.scope_target == domain:
                applicable.append(policy)
            elif policy.scope == PolicyScope.AGENT and policy.scope_target == agent_id:
                applicable.append(policy)

        violations = []
        for policy in applicable:
            violated_rules = policy.check(action_context)
            if violated_rules:
                policy.record_violation()
                violations.append(
                    {
                        "policy_id": policy.id,
                        "policy_name": policy.name,
                        "violated_rules": [
                            {"condition": r.condition, "action": r.action, "severity": r.severity}
                            for r in violated_rules
                        ],
                    }
                )
                await self.emit(
                    "policy.violated",
                    {"policy_id": policy.id, "policy_name": policy.name},
                )

        compliant = len(violations) == 0
        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "compliant": compliant,
                "policies_checked": len(applicable),
                "violations": violations,
            },
        )

    async def _query_policies(self, context: TaskContext, params: dict) -> TaskResult:
        scope = params.get("scope")
        status = params.get("status")
        results = list(self._policies.values())
        if scope:
            results = [p for p in results if p.scope == PolicyScope(scope)]
        if status:
            results = [p for p in results if p.status == PolicyStatus(status)]

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"policies": [p.model_dump(mode="json") for p in results]},
        )

    async def _compliance_report(self, context: TaskContext, params: dict) -> TaskResult:
        report = []
        for policy in self._policies.values():
            if policy.status != PolicyStatus.ACTIVE:
                continue
            report.append(
                {
                    "policy_id": policy.id,
                    "name": policy.name,
                    "compliance_rate": policy.compliance_rate,
                    "checks": policy.checks_count,
                    "violations": policy.violations_count,
                    "scope": policy.scope.value,
                }
            )

        overall = sum(r["compliance_rate"] for r in report) / len(report) if report else 1.0

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "overall_compliance": overall,
                "policies": report,
                "total_active": len(report),
            },
        )

    async def assess_self(self) -> dict[str, Any]:
        active = [p for p in self._policies.values() if p.status == PolicyStatus.ACTIVE]
        return {
            "total_policies": len(self._policies),
            "active_policies": len(active),
            "overall_compliance": (
                sum(p.compliance_rate for p in active) / len(active) if active else 1.0
            ),
            "total_checks": sum(p.checks_count for p in active),
            "total_violations": sum(p.violations_count for p in active),
        }
