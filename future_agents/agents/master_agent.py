"""Master Agent — the central brain that can talk to any agent in the system.

The Master Agent is the single entry point for all external requests.
It discovers available agents, understands their capabilities through
their definitions, routes tasks intelligently, coordinates multi-agent
workflows, and synthesizes results.
"""

from __future__ import annotations

import logging
from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.core.events import EventBus
from future_agents.core.protocol.messages import (
    AgentMessage,
    DelegationRequest,
    DelegationResponse,
    MessageRole,
    MessageType,
)
from future_agents.core.registry import AgentRegistry
from future_agents.definitions.defined_agent import DefinedAgent
from future_agents.definitions.profile import AgentProfile, ProfileExtractor
from future_agents.infrastructure.metric_tracker import MetricTracker
from future_agents.infrastructure.sync_engine import SyncEngine
from future_agents.models.feedback import ExecutionOutcome

logger = logging.getLogger(__name__)


class MasterAgent(BaseAgent):
    """The Master Agent — discovers, routes to, and coordinates all other agents.

    Capabilities:
    1. **Discovery** — Knows every agent, their skills, inputs/outputs, and constraints
    2. **Routing** — Matches intents to the best agent based on skills and metrics
    3. **Delegation** — Sends structured delegation requests with full context
    4. **Workflow** — Chains multiple agents for complex multi-step tasks
    5. **Synthesis** — Combines results from multiple agents
    6. **Monitoring** — Tracks system health and feeds the improvement loop

    The Master Agent never executes domain logic itself — it always delegates.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        sync_engine: SyncEngine | None = None,
        metrics: MetricTracker | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__(agent_id="master", event_bus=event_bus)
        self.registry = registry
        self.sync_engine = sync_engine
        self.metrics = metrics or MetricTracker()
        self._conversation_history: list[AgentMessage] = []
        self._profile_extractor = ProfileExtractor()

    @property
    def agent_type(self) -> str:
        return "master"

    @property
    def capabilities(self) -> list[str]:
        return [
            "master.route",
            "master.discover",
            "master.workflow",
            "master.ask",
            "master.status",
            "master.profile",
            "master.profile_all",
        ]

    # ── Core execution ──────────────────────────────────────────

    async def _execute(self, context: TaskContext) -> TaskResult:
        handlers = {
            "master.route": self._route_task,
            "master.discover": self._discover_agents,
            "master.workflow": self._execute_workflow,
            "master.ask": self._ask_agent,
            "master.status": self._system_status,
            "master.profile": self._profile_agent,
            "master.profile_all": self._profile_all_agents,
        }

        # If the intent doesn't start with "master.", try to route it
        handler = handlers.get(context.intent)
        if not handler:
            return await self._route_task(context)

        return await handler(context)

    # ── Discovery ───────────────────────────────────────────────

    async def _discover_agents(self, context: TaskContext) -> TaskResult:
        """List all agents with their full descriptions."""
        domain_filter = context.parameters.get("domain")
        capability_filter = context.parameters.get("capability")

        descriptions = []
        for agent_id, agent in self.registry.agents.items():
            if agent_id == self.agent_id:
                continue  # Skip self

            if isinstance(agent, DefinedAgent):
                desc = agent.describe()
            else:
                desc = {
                    "id": agent.agent_id,
                    "type": agent.agent_type,
                    "capabilities": agent.capabilities,
                    "metrics": {
                        "success_rate": agent.success_rate,
                        "execution_count": agent._execution_count,
                    },
                }

            # Apply filters
            if domain_filter and desc.get("domain") != domain_filter:
                continue
            if capability_filter:
                caps = desc.get("capabilities", [])
                skills = desc.get("skills", [])
                skill_intents = [s["intent"] for s in skills] if skills else []
                if capability_filter not in caps and capability_filter not in skill_intents:
                    continue

            descriptions.append(desc)

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"agents": descriptions, "count": len(descriptions)},
        )

    # ── Routing ─────────────────────────────────────────────────

    async def _route_task(self, context: TaskContext) -> TaskResult:
        """Route a task to the best agent for the intent."""
        intent = context.parameters.get("intent", context.intent)
        parameters = context.parameters.get("parameters", context.parameters)

        # Remove routing meta-params
        if "intent" in parameters:
            parameters = dict(parameters)
            parameters.pop("intent", None)
            parameters.pop("parameters", None)

        # Find the best agent
        target = self._find_best_agent(intent)
        if not target:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"No agent available for intent: {intent}"],
                suggestions=self._suggest_alternatives(intent),
            )

        self.metrics.increment("master.delegations", labels={"intent": intent})

        # Delegate
        if isinstance(target, DefinedAgent):
            response = await self._delegate_to_defined(target, intent, parameters)
        else:
            response = await self._delegate_to_base(target, intent, parameters)

        # Feed the sync engine
        if self.sync_engine and response:
            feedback = target.generate_feedback(
                TaskResult(
                    task_id=context.task_id,
                    agent_id=target.agent_id,
                    outcome=(
                        ExecutionOutcome.SUCCESS if response.success
                        else ExecutionOutcome.FAILURE
                    ),
                    data=response.data,
                    errors=response.errors,
                )
            )
            self.sync_engine.add_feedback(feedback)

        if response and response.success:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.SUCCESS,
                data={
                    "delegated_to": target.agent_id,
                    "agent_type": target.agent_type,
                    "result": response.data,
                },
                suggestions=response.suggestions,
            )
        else:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                data={"delegated_to": target.agent_id},
                errors=response.errors if response else ["Delegation failed"],
            )

    # ── Workflow execution ──────────────────────────────────────

    async def _execute_workflow(self, context: TaskContext) -> TaskResult:
        """Execute a multi-step workflow across multiple agents."""
        workflow_name = context.parameters.get("name", "unnamed")
        steps = context.parameters.get("steps", [])

        if not steps:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=["Workflow has no steps"],
            )

        step_results: list[dict[str, Any]] = []
        all_success = True
        accumulated_data: dict[str, Any] = {}

        for i, step in enumerate(steps):
            step_intent = step.get("intent", "")
            step_params = dict(step.get("parameters", {}))

            # Inject results from previous steps
            step_params["_workflow_context"] = accumulated_data

            target = self._find_best_agent(step_intent)
            if not target:
                step_results.append({
                    "step": i + 1,
                    "intent": step_intent,
                    "status": "skipped",
                    "error": f"No agent for intent: {step_intent}",
                })
                all_success = False
                continue

            if isinstance(target, DefinedAgent):
                response = await self._delegate_to_defined(target, step_intent, step_params)
            else:
                response = await self._delegate_to_base(target, step_intent, step_params)

            if response and response.success:
                step_results.append({
                    "step": i + 1,
                    "intent": step_intent,
                    "agent": target.agent_id,
                    "status": "completed",
                    "data": response.data,
                })
                accumulated_data[f"step_{i + 1}"] = response.data
            else:
                step_results.append({
                    "step": i + 1,
                    "intent": step_intent,
                    "agent": target.agent_id,
                    "status": "failed",
                    "errors": response.errors if response else [],
                })
                all_success = False
                # Continue workflow even if a step fails (best-effort)

        await self.emit("master.workflow_completed", {
            "name": workflow_name,
            "steps": len(steps),
            "success": all_success,
        })

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS if all_success else ExecutionOutcome.PARTIAL,
            data={
                "workflow": workflow_name,
                "results": step_results,
                "success": all_success,
                "steps_completed": len([r for r in step_results if r["status"] == "completed"]),
                "total_steps": len(steps),
            },
        )

    # ── Ask agent ───────────────────────────────────────────────

    async def _ask_agent(self, context: TaskContext) -> TaskResult:
        """Route a natural-language question to a specific agent type."""
        agent_type = context.parameters.get("agent_type", "")
        question = context.parameters.get("question", "")

        agents = self.registry.find_by_type(agent_type)
        if not agents:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"No agent of type '{agent_type}' found"],
                suggestions=[
                    f"Available types: {list(set(a.agent_type for a in self.registry.agents.values()))}"
                ],
            )

        target = agents[0]

        # Create a message
        msg = AgentMessage(
            type=MessageType.REQUEST,
            role=MessageRole.MASTER,
            sender=self.agent_id,
            recipient=target.agent_id,
            intent=f"{agent_type}.query",
            content={"question": question},
            text=question,
        )

        self._conversation_history.append(msg)

        if isinstance(target, DefinedAgent):
            response = await target.handle_message(msg)
            self._conversation_history.append(response)
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.SUCCESS,
                data={
                    "agent": target.agent_id,
                    "answer": response.content,
                    "text": response.text,
                },
            )
        else:
            # Fallback for non-defined agents
            task_ctx = TaskContext(
                intent=f"{agent_type}.query",
                parameters={"question": question},
            )
            result = await target.execute(task_ctx)
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=result.outcome,
                data={"agent": target.agent_id, "answer": result.data},
            )

    # ── System status ───────────────────────────────────────────

    async def _system_status(self, context: TaskContext) -> TaskResult:
        """Get comprehensive system status."""
        agent_statuses: list[dict[str, Any]] = []

        for agent_id, agent in self.registry.agents.items():
            if agent_id == self.agent_id:
                continue

            status: dict[str, Any] = {
                "id": agent_id,
                "type": agent.agent_type,
                "success_rate": agent.success_rate,
                "execution_count": agent._execution_count,
            }

            if isinstance(agent, DefinedAgent):
                status["name"] = agent.definition.name
                status["version"] = agent.definition.version
                status["skills"] = len(agent.definition.skills)
                status["domain"] = agent.definition.domain

            assessment = await agent.assess_self()
            status["assessment"] = assessment
            agent_statuses.append(status)

        improvements = {}
        if self.sync_engine:
            imps = self.sync_engine.improvements
            improvements = {
                "proposed": len([i for i in imps if i.status == "proposed"]),
                "applied": len([i for i in imps if i.status == "applied"]),
                "total": len(imps),
            }

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "agents": agent_statuses,
                "agent_count": len(agent_statuses),
                "improvements": improvements,
                "metrics": self.metrics.summary(),
            },
        )

    # ── Agent profiling ─────────────────────────────────────────

    async def _profile_agent(self, context: TaskContext) -> TaskResult:
        """Extract a structured profile for a single agent.

        Reads the agent's definition and runtime metrics, then produces
        a normalized profile with columns: do's, don'ts, how to interact,
        hard skills, soft skills, tools, prompts, dependencies, strengths,
        weaknesses, metrics.
        """
        agent_type = context.parameters.get("agent_type", "")
        agent_id = context.parameters.get("agent_id", "")
        output_format = context.parameters.get("format", "full")  # full, table, columns

        # Find the target agent
        target = None
        if agent_id:
            target = self.registry.get(agent_id)
        elif agent_type:
            agents = self.registry.find_by_type(agent_type)
            agents = [a for a in agents if a.agent_id != self.agent_id]
            target = agents[0] if agents else None

        if not target:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Agent not found: type='{agent_type}' id='{agent_id}'"],
                suggestions=[
                    f"Available types: {[a.agent_type for a in self.registry.agents.values() if a.agent_id != self.agent_id]}"
                ],
            )

        profile = self._extract_profile(target)

        # Choose output format
        if output_format == "table":
            data: dict[str, Any] = {
                "agent_type": target.agent_type,
                "table": profile.to_table(),
            }
        elif output_format == "columns":
            data = {
                "agent_type": target.agent_type,
                "columns": profile.column_names(),
                "profile": profile.to_dict(),
            }
        else:
            data = {
                "agent_type": target.agent_type,
                "profile": profile.to_dict(),
                "table": profile.to_table(),
            }

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data=data,
        )

    async def _profile_all_agents(self, context: TaskContext) -> TaskResult:
        """Extract structured profiles for ALL agents in the system.

        Returns a list of profiles, one per agent, each with all columns.
        """
        output_format = context.parameters.get("format", "full")
        domain_filter = context.parameters.get("domain")

        profiles: list[dict[str, Any]] = []
        tables: list[str] = []

        for agent_id, agent in self.registry.agents.items():
            if agent_id == self.agent_id:
                continue

            # Apply domain filter
            if domain_filter and isinstance(agent, DefinedAgent):
                if agent.definition.domain != domain_filter:
                    continue

            profile = self._extract_profile(agent)

            summary = {
                "agent_type": agent.agent_type,
                "agent_id": agent_id,
                "profile": profile.to_dict(),
            }

            if output_format in ("full", "table"):
                table_text = profile.to_table()
                summary["table"] = table_text
                tables.append(table_text)

            profiles.append(summary)

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "profiles": profiles,
                "count": len(profiles),
                "columns": AgentProfile.model_fields.keys().__iter__().__class__.__name__
                    if False else [  # Just list the column names
                    "identity", "dos", "donts", "interaction", "skills",
                    "soft_skills", "tools", "prompts", "dependencies",
                    "strengths", "weaknesses", "metrics",
                ],
                "combined_table": "\n\n".join(tables) if tables else "",
            },
        )

    def _extract_profile(self, agent: BaseAgent) -> AgentProfile:
        """Extract an AgentProfile from any agent (defined or legacy)."""
        runtime_metrics = {
            "success_rate": agent.success_rate,
            "execution_count": agent._execution_count,
        }

        if isinstance(agent, DefinedAgent):
            return self._profile_extractor.extract(agent.definition, runtime_metrics)
        else:
            # For legacy agents without definitions, build a minimal definition
            from future_agents.definitions.schema import (
                AgentDefinition,
                PersonalityDef,
                SkillDef,
                SkillLevel,
            )
            defn = AgentDefinition(
                name=f"{agent.agent_type.title()} Agent",
                type=agent.agent_type,
                description=f"Legacy {agent.agent_type} agent (no definition file)",
                skills=[
                    SkillDef(
                        name=cap.replace(".", " ").title(),
                        description=f"Capability: {cap}",
                        intent=cap,
                        level=SkillLevel.INTERMEDIATE,
                    )
                    for cap in agent.capabilities
                ],
                personality=PersonalityDef(tone="professional", verbosity="concise"),
            )
            return self._profile_extractor.extract(defn, runtime_metrics)

    # ── Agent catalog (for prompts) ─────────────────────────────

    def build_agent_catalog(self) -> str:
        """Build a text catalog of all agents for use in prompts."""
        lines: list[str] = []
        for agent_id, agent in self.registry.agents.items():
            if agent_id == self.agent_id:
                continue

            if isinstance(agent, DefinedAgent):
                desc = agent.describe()
                lines.append(f"\n## {desc['name']} (type: {desc['type']})")
                lines.append(f"   Domain: {desc['domain']}")
                lines.append(f"   Description: {desc['description']}")
                lines.append(f"   Skills:")
                for skill in desc["skills"]:
                    inputs_str = ", ".join(
                        f"{p['name']}:{p['type']}" + ("*" if p["required"] else "")
                        for p in skill["inputs"]
                    )
                    lines.append(f"     - {skill['intent']}: {skill['description']}")
                    if inputs_str:
                        lines.append(f"       Inputs: ({inputs_str})")
            else:
                lines.append(f"\n## {agent.agent_type} (id: {agent_id})")
                lines.append(f"   Capabilities: {', '.join(agent.capabilities)}")

        return "\n".join(lines)

    # ── Internal helpers ────────────────────────────────────────

    def _find_best_agent(self, intent: str) -> BaseAgent | None:
        """Find the best agent for an intent using multiple strategies."""
        # Strategy 1: Exact capability match
        agent = self.registry.best_agent_for(intent)
        if agent and agent.agent_id != self.agent_id:
            return agent

        # Strategy 2: Match by type prefix (e.g. "capability.register" -> "capability")
        prefix = intent.split(".")[0] if "." in intent else intent
        agents = self.registry.find_by_type(prefix)
        agents = [a for a in agents if a.agent_id != self.agent_id]
        if agents:
            return max(agents, key=lambda a: (a.success_rate, a._execution_count))

        # Strategy 3: Search all DefinedAgents for matching skill intents
        for agent_id, agent in self.registry.agents.items():
            if agent_id == self.agent_id:
                continue
            if isinstance(agent, DefinedAgent):
                if agent.definition.get_skill(intent):
                    return agent

        return None

    async def _delegate_to_defined(
        self, agent: DefinedAgent, intent: str, parameters: dict
    ) -> DelegationResponse:
        """Delegate to a DefinedAgent using the protocol."""
        delegation = DelegationRequest(
            from_agent=self.agent_id,
            to_agent=agent.agent_id,
            intent=intent,
            parameters=parameters,
        )
        return await agent.handle_delegation(delegation)

    async def _delegate_to_base(
        self, agent: BaseAgent, intent: str, parameters: dict
    ) -> DelegationResponse:
        """Delegate to a plain BaseAgent using TaskContext."""
        context = TaskContext(intent=intent, parameters=parameters)
        result = await agent.execute(context)
        return DelegationResponse(
            delegation_id=context.task_id,
            agent_id=agent.agent_id,
            success=result.outcome == ExecutionOutcome.SUCCESS,
            data=result.data,
            errors=result.errors,
            suggestions=result.suggestions,
            duration_ms=result.duration_ms,
        )

    def _suggest_alternatives(self, intent: str) -> list[str]:
        """Suggest alternative intents when routing fails."""
        all_intents: list[str] = []
        for agent in self.registry.agents.values():
            if agent.agent_id == self.agent_id:
                continue
            if isinstance(agent, DefinedAgent):
                all_intents.extend(agent.definition.intents)
            else:
                all_intents.extend(agent.capabilities)

        # Simple prefix matching
        prefix = intent.split(".")[0] if "." in intent else intent
        suggestions = [i for i in all_intents if i.startswith(prefix)]
        if not suggestions:
            suggestions = [f"Available intents: {', '.join(sorted(set(all_intents)))[:500]}"]
        return suggestions

    async def assess_self(self) -> dict[str, Any]:
        return {
            "registered_agents": len(self.registry.agents) - 1,  # Exclude self
            "total_delegations": self.metrics.get_counter("master.delegations"),
            "conversation_length": len(self._conversation_history),
            "success_rate": self.success_rate,
        }
