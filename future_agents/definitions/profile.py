"""Agent Profile — structured extraction of any agent's information into
a normalized, human-readable profile with standardized columns.

The ProfileExtractor reads an agent's definition (and runtime metrics)
and produces an AgentProfile with columns like:
  - Identity, Do's, Don'ts, How to Interact, Hard Skills, Soft Skills,
    Tools, Prompts, Dependencies, Strengths, Weaknesses, Metrics, etc.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from future_agents.definitions.schema import (
    AgentDefinition,
    ConstraintDef,
    InteractionMode,
    SkillLevel,
)


# ── Profile Column Models ────────────────────────────────────────


class ProfileIdentity(BaseModel):
    """Who this agent is."""
    name: str
    type: str
    version: str
    domain: str
    description: str
    tags: list[str] = Field(default_factory=list)
    author: str = ""


class ProfileDo(BaseModel):
    """A thing this agent SHOULD do."""
    action: str
    source: str  # Where this was derived from (skill, prompt, trait, etc.)
    priority: str = "normal"  # critical, high, normal, low


class ProfileDont(BaseModel):
    """A thing this agent must NOT do."""
    restriction: str
    source: str  # constraint name, policy, etc.
    enforcement: str = "strict"  # strict, warn, log
    reason: str = ""


class ProfileSkill(BaseModel):
    """A hard skill / technical capability."""
    name: str
    description: str
    intent: str
    level: str
    inputs: list[dict[str, str]] = Field(default_factory=list)
    outputs: list[dict[str, str]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    examples: list[dict] = Field(default_factory=list)


class ProfileSoftSkill(BaseModel):
    """A soft skill / behavioral trait."""
    trait: str
    category: str  # communication, personality, work_style
    description: str = ""


class ProfileTool(BaseModel):
    """A tool or integration available to the agent."""
    name: str
    description: str
    endpoint: str = ""
    auth_required: bool = False


class ProfileInteraction(BaseModel):
    """How to interact with this agent."""
    modes: list[str] = Field(default_factory=list)
    input_format: str = ""
    output_format: str = ""
    max_concurrent: int = 0
    timeout_seconds: int = 0
    retry_max: int = 0
    retry_backoff: str = ""
    tips: list[str] = Field(default_factory=list)


class ProfilePrompt(BaseModel):
    """A prompt template associated with the agent."""
    name: str
    role: str
    description: str = ""
    template_preview: str = ""  # First 200 chars
    variables: list[str] = Field(default_factory=list)


class ProfileDependency(BaseModel):
    """An agent this one depends on."""
    agent_type: str
    required: bool
    capabilities_needed: list[str] = Field(default_factory=list)


class ProfileStrength(BaseModel):
    """Something this agent is particularly good at."""
    area: str
    evidence: str


class ProfileWeakness(BaseModel):
    """An area where this agent could improve."""
    area: str
    detail: str
    suggestion: str = ""


class ProfileMetrics(BaseModel):
    """Runtime performance metrics."""
    success_rate: float = 0.0
    execution_count: int = 0
    total_skills: int = 0
    expert_skills: int = 0
    advanced_skills: int = 0
    constraints_count: int = 0
    prompts_count: int = 0
    dependencies_count: int = 0
    tools_count: int = 0


# ── The Complete Agent Profile ───────────────────────────────────


class AgentProfile(BaseModel):
    """Complete extracted profile of an agent, organized into columns.

    This is the normalized output produced by the ProfileExtractor.
    Every field is a "column" that gives a specific view of the agent.
    """

    # ── Column 1: Identity ──
    identity: ProfileIdentity

    # ── Column 2: Do's ──
    dos: list[ProfileDo] = Field(default_factory=list)

    # ── Column 3: Don'ts ──
    donts: list[ProfileDont] = Field(default_factory=list)

    # ── Column 4: How to Interact ──
    interaction: ProfileInteraction = Field(default_factory=ProfileInteraction)

    # ── Column 5: Hard Skills (technical capabilities) ──
    skills: list[ProfileSkill] = Field(default_factory=list)

    # ── Column 6: Soft Skills (traits, communication style) ──
    soft_skills: list[ProfileSoftSkill] = Field(default_factory=list)

    # ── Column 7: Tools ──
    tools: list[ProfileTool] = Field(default_factory=list)

    # ── Column 8: Prompts ──
    prompts: list[ProfilePrompt] = Field(default_factory=list)

    # ── Column 9: Dependencies ──
    dependencies: list[ProfileDependency] = Field(default_factory=list)

    # ── Column 10: Strengths ──
    strengths: list[ProfileStrength] = Field(default_factory=list)

    # ── Column 11: Weaknesses / Growth Areas ──
    weaknesses: list[ProfileWeakness] = Field(default_factory=list)

    # ── Column 12: Metrics ──
    metrics: ProfileMetrics = Field(default_factory=ProfileMetrics)

    # ── Metadata ──
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_table(self) -> str:
        """Render the profile as a human-readable text table."""
        lines: list[str] = []
        w = 72  # width

        def heading(title: str) -> None:
            lines.append("")
            lines.append(f"{'=' * w}")
            lines.append(f"  {title}")
            lines.append(f"{'=' * w}")

        def row(label: str, value: str) -> None:
            lines.append(f"  {label:.<30s} {value}")

        # Identity
        heading(f"AGENT PROFILE: {self.identity.name}")
        row("Type", self.identity.type)
        row("Version", self.identity.version)
        row("Domain", self.identity.domain)
        row("Tags", ", ".join(self.identity.tags) or "none")
        lines.append(f"\n  {self.identity.description}")

        # Do's
        heading("DO's")
        for d in self.dos:
            priority_tag = f" [{d.priority}]" if d.priority != "normal" else ""
            lines.append(f"  + {d.action}{priority_tag}")
            lines.append(f"    (from: {d.source})")

        # Don'ts
        heading("DON'Ts")
        for d in self.donts:
            lines.append(f"  - {d.restriction}  [{d.enforcement}]")
            if d.reason:
                lines.append(f"    Reason: {d.reason}")

        # How to Interact
        heading("HOW TO INTERACT")
        row("Modes", ", ".join(self.interaction.modes))
        row("Input format", self.interaction.input_format)
        row("Output format", self.interaction.output_format)
        row("Max concurrent", str(self.interaction.max_concurrent))
        row("Timeout", f"{self.interaction.timeout_seconds}s")
        row("Retries", f"{self.interaction.retry_max}x ({self.interaction.retry_backoff})")
        if self.interaction.tips:
            lines.append("\n  Tips:")
            for tip in self.interaction.tips:
                lines.append(f"    * {tip}")

        # Hard Skills
        heading("SKILLS (Hard / Technical)")
        for s in self.skills:
            inputs = ", ".join(i.get("name", "") for i in s.inputs) or "none"
            lines.append(f"  [{s.level:^12s}]  {s.name}")
            lines.append(f"    intent:  {s.intent}")
            lines.append(f"    desc:    {s.description}")
            lines.append(f"    inputs:  {inputs}")

        # Soft Skills
        heading("SOFT SKILLS")
        for s in self.soft_skills:
            lines.append(f"  [{s.category:^15s}]  {s.trait}")
            if s.description:
                lines.append(f"    {s.description}")

        # Tools
        heading("TOOLS")
        if self.tools:
            for t in self.tools:
                lines.append(f"  - {t.name}: {t.description}")
        else:
            lines.append("  (no external tools)")

        # Prompts
        heading("PROMPTS")
        for p in self.prompts:
            vars_str = ", ".join(p.variables) if p.variables else "none"
            lines.append(f"  [{p.role:^9s}]  {p.name}")
            lines.append(f"    vars: {vars_str}")
            if p.template_preview:
                preview = p.template_preview[:120].replace("\n", " ")
                lines.append(f"    preview: {preview}...")

        # Dependencies
        heading("DEPENDENCIES")
        if self.dependencies:
            for dep in self.dependencies:
                req = "REQUIRED" if dep.required else "optional"
                caps = ", ".join(dep.capabilities_needed) or "any"
                lines.append(f"  - {dep.agent_type} ({req}) — needs: {caps}")
        else:
            lines.append("  (no dependencies)")

        # Strengths
        heading("STRENGTHS")
        for s in self.strengths:
            lines.append(f"  + {s.area}")
            lines.append(f"    {s.evidence}")

        # Weaknesses / Growth Areas
        heading("GROWTH AREAS")
        if self.weaknesses:
            for w_ in self.weaknesses:
                lines.append(f"  ~ {w_.area}: {w_.detail}")
                if w_.suggestion:
                    lines.append(f"    Suggestion: {w_.suggestion}")
        else:
            lines.append("  (no identified weaknesses)")

        # Metrics
        heading("METRICS")
        row("Success rate", f"{self.metrics.success_rate:.0%}")
        row("Executions", str(self.metrics.execution_count))
        row("Total skills", str(self.metrics.total_skills))
        row("Expert-level skills", str(self.metrics.expert_skills))
        row("Constraints", str(self.metrics.constraints_count))
        row("Prompts", str(self.metrics.prompts_count))
        row("Dependencies", str(self.metrics.dependencies_count))

        lines.append(f"\n{'=' * w}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary (all columns)."""
        return self.model_dump(mode="json")

    def column_names(self) -> list[str]:
        """Return the list of all profile column names."""
        return [
            "identity",
            "dos",
            "donts",
            "interaction",
            "skills",
            "soft_skills",
            "tools",
            "prompts",
            "dependencies",
            "strengths",
            "weaknesses",
            "metrics",
        ]


# ── Profile Extractor ────────────────────────────────────────────


class ProfileExtractor:
    """Reads an agent definition (+ optional runtime metrics) and produces
    a fully structured AgentProfile.

    This is the intelligence layer — it doesn't just copy fields, it
    *derives* information:
    - Do's are inferred from skills, personality, and prompts
    - Don'ts are inferred from constraints and enforcement levels
    - Soft skills are extracted from personality traits and tone
    - Strengths/weaknesses are computed from skill levels and coverage
    """

    def extract(
        self,
        definition: AgentDefinition,
        runtime_metrics: dict[str, Any] | None = None,
    ) -> AgentProfile:
        """Extract a complete profile from an agent definition."""
        metrics = runtime_metrics or {}

        return AgentProfile(
            identity=self._extract_identity(definition),
            dos=self._extract_dos(definition),
            donts=self._extract_donts(definition),
            interaction=self._extract_interaction(definition),
            skills=self._extract_skills(definition),
            soft_skills=self._extract_soft_skills(definition),
            tools=self._extract_tools(definition),
            prompts=self._extract_prompts(definition),
            dependencies=self._extract_dependencies(definition),
            strengths=self._extract_strengths(definition, metrics),
            weaknesses=self._extract_weaknesses(definition, metrics),
            metrics=self._extract_metrics(definition, metrics),
        )

    # ── Column extractors ────────────────────────────────────────

    def _extract_identity(self, defn: AgentDefinition) -> ProfileIdentity:
        return ProfileIdentity(
            name=defn.name,
            type=defn.type,
            version=defn.version,
            domain=defn.domain,
            description=defn.description,
            tags=defn.tags,
            author=defn.author,
        )

    def _extract_dos(self, defn: AgentDefinition) -> list[ProfileDo]:
        """Derive DO's from skills, prompts, personality, and custom instructions."""
        dos: list[ProfileDo] = []

        # From skills — each skill is something the agent SHOULD do
        for skill in defn.skills:
            dos.append(ProfileDo(
                action=f"{skill.name}: {skill.description}",
                source=f"skill:{skill.intent}",
                priority="high" if skill.level in (SkillLevel.ADVANCED, SkillLevel.EXPERT) else "normal",
            ))

        # From system prompt — parse responsibilities
        system_prompt = defn.get_prompt("system")
        if system_prompt:
            for line in system_prompt.template.split("\n"):
                line = line.strip().lstrip("- ").lstrip("* ")
                if line.startswith("Your responsibilit"):
                    continue
                # Lines that start with action words from the prompt
                if line and any(line.startswith(w) for w in [
                    "Register", "Track", "Define", "Manage", "Check", "Generate",
                    "Capture", "Maintain", "Ensure", "Identify", "Monitor",
                    "Analyze", "Report", "Prioritize", "UNDERSTAND", "DELEGATE",
                    "COORDINATE", "SYNTHESIZE", "MONITOR",
                ]):
                    dos.append(ProfileDo(
                        action=line,
                        source="system_prompt",
                        priority="high",
                    ))

        # From personality custom instructions
        if defn.personality.custom_instructions:
            dos.append(ProfileDo(
                action=defn.personality.custom_instructions,
                source="personality:custom_instructions",
                priority="normal",
            ))

        # From personality traits
        trait_actions = {
            "data-driven": "Base all assessments on data and metrics",
            "precise": "Provide exact, unambiguous information",
            "systematic": "Follow structured, repeatable approaches",
            "structured": "Organize outputs in clear structures",
            "thorough": "Cover all relevant aspects comprehensively",
            "optimization-focused": "Continuously look for improvement opportunities",
            "encouraging": "Frame feedback constructively and positively",
            "evidence-based": "Support claims with concrete evidence",
            "growth-oriented": "Focus on development and progression",
            "accurate": "Ensure factual correctness in all outputs",
            "organized": "Keep information well-structured and indexed",
            "proactive": "Anticipate needs and act before being asked",
            "strict": "Enforce rules without exceptions",
            "transparent": "Make all decisions and reasoning visible",
            "decisive": "Make clear decisions quickly",
            "coordinating": "Ensure smooth collaboration between agents",
        }
        for trait in defn.personality.traits:
            if trait.lower() in trait_actions:
                dos.append(ProfileDo(
                    action=trait_actions[trait.lower()],
                    source=f"personality:trait:{trait}",
                    priority="normal",
                ))

        return dos

    def _extract_donts(self, defn: AgentDefinition) -> list[ProfileDont]:
        """Derive DON'Ts from constraints and system prompt."""
        donts: list[ProfileDont] = []

        # From constraints — each constraint is a DON'T
        for constraint in defn.constraints:
            donts.append(ProfileDont(
                restriction=constraint.description,
                source=f"constraint:{constraint.name}",
                enforcement=constraint.enforcement,
                reason=constraint.condition if constraint.condition else "",
            ))

        # From system prompt — look for negative instructions
        system_prompt = defn.get_prompt("system")
        if system_prompt:
            for line in system_prompt.template.split("\n"):
                line = line.strip().lstrip("- ").lstrip("* ")
                if any(line.lower().startswith(w) for w in [
                    "never ", "do not ", "don't ", "avoid ", "must not ",
                ]):
                    donts.append(ProfileDont(
                        restriction=line,
                        source="system_prompt",
                        enforcement="strict",
                    ))

        # Derive implicit DON'Ts from personality
        tone_donts = {
            "formal": "Don't use casual or slang language",
            "professional": "Don't use overly casual tone or emojis",
            "technical": "Don't oversimplify technical concepts",
        }
        if defn.personality.tone in tone_donts:
            donts.append(ProfileDont(
                restriction=tone_donts[defn.personality.tone],
                source="personality:tone",
                enforcement="warn",
            ))

        verbosity_donts = {
            "minimal": "Don't include unnecessary detail or explanation",
            "concise": "Don't be verbose or rambling",
            "detailed": "Don't omit relevant details for brevity",
        }
        if defn.personality.verbosity in verbosity_donts:
            donts.append(ProfileDont(
                restriction=verbosity_donts[defn.personality.verbosity],
                source="personality:verbosity",
                enforcement="warn",
            ))

        return donts

    def _extract_interaction(self, defn: AgentDefinition) -> ProfileInteraction:
        """Extract how to interact with this agent."""
        interaction = defn.interaction
        retry = interaction.retry_policy

        tips: list[str] = []

        # Derive interaction tips from the definition
        if InteractionMode.CONVERSATIONAL in interaction.modes:
            tips.append("Supports multi-turn conversations — you can follow up")
        if InteractionMode.EVENT_DRIVEN in interaction.modes:
            tips.append("Reacts to events — can be triggered by other agents")
        if InteractionMode.STREAMING in interaction.modes:
            tips.append("Supports streaming — results may arrive incrementally")

        if interaction.max_concurrent > 20:
            tips.append("High concurrency — safe to send many requests in parallel")
        elif interaction.max_concurrent <= 5:
            tips.append("Low concurrency — avoid overwhelming with parallel requests")

        if interaction.timeout_seconds <= 15:
            tips.append("Fast responses expected — keep inputs concise")
        elif interaction.timeout_seconds >= 60:
            tips.append("Long-running tasks supported — complex inputs are okay")

        # Tips from personality
        if defn.personality.verbosity == "detailed":
            tips.append("Expects detailed inputs — provide full context")
        elif defn.personality.verbosity == "minimal":
            tips.append("Prefers minimal inputs — be brief and direct")

        if defn.personality.tone == "formal":
            tips.append("Uses formal communication style")

        # Tips from skills
        required_input_count = sum(
            1 for skill in defn.skills
            for inp in skill.inputs
            if inp.required
        )
        if required_input_count > 0:
            tips.append(f"Has {required_input_count} required input fields across all skills — check schema before calling")

        return ProfileInteraction(
            modes=[m.value for m in interaction.modes],
            input_format=interaction.input_format,
            output_format=interaction.output_format,
            max_concurrent=interaction.max_concurrent,
            timeout_seconds=interaction.timeout_seconds,
            retry_max=retry.max_retries,
            retry_backoff=f"{retry.backoff_seconds}s x{retry.backoff_multiplier}",
            tips=tips,
        )

    def _extract_skills(self, defn: AgentDefinition) -> list[ProfileSkill]:
        """Extract hard skills from the agent's skill definitions."""
        return [
            ProfileSkill(
                name=skill.name,
                description=skill.description,
                intent=skill.intent,
                level=skill.level.value,
                inputs=[
                    {"name": p.name, "type": p.type.value, "required": str(p.required)}
                    for p in skill.inputs
                ],
                outputs=[
                    {"name": p.name, "type": p.type.value, "description": p.description}
                    for p in skill.outputs
                ],
                tags=skill.tags,
                examples=[
                    {"description": ex.description, "input": ex.input, "output": ex.expected_output}
                    for ex in skill.examples
                ],
            )
            for skill in defn.skills
        ]

    def _extract_soft_skills(self, defn: AgentDefinition) -> list[ProfileSoftSkill]:
        """Extract soft skills from personality, tone, and communication style."""
        soft: list[ProfileSoftSkill] = []

        # Tone as a soft skill
        tone_descriptions = {
            "professional": "Maintains a professional and respectful tone in all communications",
            "formal": "Uses formal language and structured communication",
            "casual": "Uses approachable, conversational language",
            "technical": "Communicates with technical precision and domain terminology",
        }
        soft.append(ProfileSoftSkill(
            trait=f"{defn.personality.tone.title()} Communication",
            category="communication",
            description=tone_descriptions.get(defn.personality.tone, ""),
        ))

        # Verbosity as a soft skill
        verbosity_descriptions = {
            "minimal": "Delivers only essential information, no extras",
            "concise": "Balances brevity with completeness",
            "detailed": "Provides comprehensive, thorough responses",
            "verbose": "Gives exhaustive detail on every aspect",
        }
        soft.append(ProfileSoftSkill(
            trait=f"{defn.personality.verbosity.title()} Output Style",
            category="communication",
            description=verbosity_descriptions.get(defn.personality.verbosity, ""),
        ))

        # Each personality trait
        trait_categories = {
            "data-driven": ("work_style", "Makes decisions based on data and metrics, not assumptions"),
            "precise": ("work_style", "Focuses on accuracy and exactness in all outputs"),
            "systematic": ("work_style", "Follows structured, methodical approaches"),
            "structured": ("work_style", "Organizes work and outputs in clear frameworks"),
            "thorough": ("work_style", "Ensures comprehensive coverage of all aspects"),
            "optimization-focused": ("work_style", "Constantly seeks ways to improve processes"),
            "encouraging": ("interpersonal", "Provides positive, constructive feedback"),
            "evidence-based": ("analytical", "Supports all claims with concrete evidence"),
            "growth-oriented": ("interpersonal", "Focuses on development and improvement paths"),
            "accurate": ("analytical", "Prioritizes factual correctness above all"),
            "organized": ("work_style", "Keeps information well-structured and accessible"),
            "proactive": ("work_style", "Anticipates needs and takes initiative"),
            "strict": ("interpersonal", "Enforces rules firmly and consistently"),
            "transparent": ("interpersonal", "Makes reasoning and decisions visible to all"),
            "decisive": ("leadership", "Makes clear decisions promptly when needed"),
            "coordinating": ("leadership", "Facilitates smooth collaboration between parties"),
            "cautious": ("work_style", "Takes careful, measured approaches to decisions"),
            "helpful": ("interpersonal", "Goes above and beyond to assist and support"),
        }
        for trait in defn.personality.traits:
            trait_lower = trait.lower()
            if trait_lower in trait_categories:
                cat, desc = trait_categories[trait_lower]
            else:
                cat, desc = "personality", ""
            soft.append(ProfileSoftSkill(
                trait=trait.title(),
                category=cat,
                description=desc,
            ))

        return soft

    def _extract_tools(self, defn: AgentDefinition) -> list[ProfileTool]:
        """Extract tools from the definition."""
        return [
            ProfileTool(
                name=tool.name,
                description=tool.description,
                endpoint=tool.endpoint,
                auth_required=tool.auth_required,
            )
            for tool in defn.tools
        ]

    def _extract_prompts(self, defn: AgentDefinition) -> list[ProfilePrompt]:
        """Extract prompt templates."""
        return [
            ProfilePrompt(
                name=prompt.name,
                role=prompt.role,
                description=prompt.description,
                template_preview=prompt.template[:200],
                variables=prompt.variables,
            )
            for prompt in defn.prompts
        ]

    def _extract_dependencies(self, defn: AgentDefinition) -> list[ProfileDependency]:
        return [
            ProfileDependency(
                agent_type=dep.agent_type,
                required=dep.required,
                capabilities_needed=dep.capabilities_needed,
            )
            for dep in defn.dependencies
        ]

    def _extract_strengths(
        self, defn: AgentDefinition, metrics: dict[str, Any]
    ) -> list[ProfileStrength]:
        """Derive strengths from skill levels, coverage, and runtime data."""
        strengths: list[ProfileStrength] = []

        # Expert/advanced skills are strengths
        expert_skills = [s for s in defn.skills if s.level in (SkillLevel.EXPERT, SkillLevel.ADVANCED)]
        if expert_skills:
            names = ", ".join(s.name for s in expert_skills)
            strengths.append(ProfileStrength(
                area="Advanced/Expert Skills",
                evidence=f"Has {len(expert_skills)} advanced+ skill(s): {names}",
            ))

        # Broad skill coverage
        if len(defn.skills) >= 5:
            strengths.append(ProfileStrength(
                area="Broad Capability Coverage",
                evidence=f"Handles {len(defn.skills)} distinct skills across multiple intents",
            ))

        # Good success rate
        success_rate = metrics.get("success_rate", 0)
        exec_count = metrics.get("execution_count", 0)
        if exec_count >= 5 and success_rate >= 0.9:
            strengths.append(ProfileStrength(
                area="High Reliability",
                evidence=f"{success_rate:.0%} success rate over {exec_count} executions",
            ))

        # Well-defined constraints = disciplined agent
        if len(defn.constraints) >= 2:
            strengths.append(ProfileStrength(
                area="Well-Governed",
                evidence=f"Operates under {len(defn.constraints)} explicit constraints/guardrails",
            ))

        # Rich prompt library
        if len(defn.prompts) >= 3:
            strengths.append(ProfileStrength(
                area="Rich Prompt Library",
                evidence=f"Has {len(defn.prompts)} specialized prompt templates for different situations",
            ))

        # Has examples
        skills_with_examples = [s for s in defn.skills if s.examples]
        if skills_with_examples:
            strengths.append(ProfileStrength(
                area="Well-Documented Skills",
                evidence=f"{len(skills_with_examples)} skill(s) have concrete usage examples",
            ))

        return strengths

    def _extract_weaknesses(
        self, defn: AgentDefinition, metrics: dict[str, Any]
    ) -> list[ProfileWeakness]:
        """Derive weaknesses and growth areas from gaps in the definition."""
        weaknesses: list[ProfileWeakness] = []

        # No system prompt
        if not defn.get_prompt("system"):
            weaknesses.append(ProfileWeakness(
                area="Missing System Prompt",
                detail="No system prompt defined — agent identity may be unclear",
                suggestion="Add a 'system' prompt that defines the agent's role and responsibilities",
            ))

        # Skills without examples
        no_examples = [s for s in defn.skills if not s.examples]
        if no_examples:
            names = ", ".join(s.name for s in no_examples[:3])
            weaknesses.append(ProfileWeakness(
                area="Skills Lacking Examples",
                detail=f"{len(no_examples)} skill(s) have no examples: {names}",
                suggestion="Add concrete input/output examples for each skill",
            ))

        # All basic-level skills
        basic_only = all(s.level == SkillLevel.BASIC for s in defn.skills) if defn.skills else False
        if basic_only and defn.skills:
            weaknesses.append(ProfileWeakness(
                area="Low Skill Depth",
                detail="All skills are at basic level",
                suggestion="Develop skills to intermediate/advanced through usage and evidence",
            ))

        # No constraints
        if not defn.constraints:
            weaknesses.append(ProfileWeakness(
                area="No Constraints Defined",
                detail="Agent has no behavioral guardrails",
                suggestion="Add constraints to prevent undesired behaviors",
            ))

        # No dependencies declared
        if not defn.dependencies:
            weaknesses.append(ProfileWeakness(
                area="No Dependencies Declared",
                detail="Agent doesn't declare any dependencies on other agents",
                suggestion="Declare dependencies for better system-level coordination",
            ))

        # No tools
        if not defn.tools:
            weaknesses.append(ProfileWeakness(
                area="No External Tools",
                detail="Agent has no external tool integrations",
                suggestion="Consider adding tools for external APIs or data sources",
            ))

        # Low success rate
        success_rate = metrics.get("success_rate", 0)
        exec_count = metrics.get("execution_count", 0)
        if exec_count >= 5 and success_rate < 0.7:
            weaknesses.append(ProfileWeakness(
                area="Low Success Rate",
                detail=f"Only {success_rate:.0%} success rate over {exec_count} executions",
                suggestion="Review failure patterns and improve error handling",
            ))

        return weaknesses

    def _extract_metrics(
        self, defn: AgentDefinition, metrics: dict[str, Any]
    ) -> ProfileMetrics:
        return ProfileMetrics(
            success_rate=metrics.get("success_rate", 0),
            execution_count=metrics.get("execution_count", 0),
            total_skills=len(defn.skills),
            expert_skills=len([s for s in defn.skills if s.level == SkillLevel.EXPERT]),
            advanced_skills=len([s for s in defn.skills if s.level == SkillLevel.ADVANCED]),
            constraints_count=len(defn.constraints),
            prompts_count=len(defn.prompts),
            dependencies_count=len(defn.dependencies),
            tools_count=len(defn.tools),
        )
