"""Agent Definition Schema — the complete declarative spec for any agent.

An AgentDefinition is the single source of truth for what an agent is,
what it can do, how it communicates, and how it should behave. Agents can
be defined in YAML files and loaded at runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────

class InteractionMode(str, Enum):
    """How callers can interact with this agent."""
    REQUEST_RESPONSE = "request_response"  # Synchronous call/return
    STREAMING = "streaming"  # Streamed output
    EVENT_DRIVEN = "event_driven"  # Reacts to events
    CONVERSATIONAL = "conversational"  # Multi-turn dialogue


class SkillLevel(str, Enum):
    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class ParameterType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    LIST = "list"
    DICT = "dict"
    ANY = "any"


# ── Nested Definition Components ─────────────────────────────────

class ParameterDef(BaseModel):
    """Definition of a single input/output parameter."""
    name: str
    type: ParameterType = ParameterType.STRING
    description: str = ""
    required: bool = True
    default: str | int | float | bool | list | dict | None = None
    examples: list[str] = Field(default_factory=list)


class SkillDef(BaseModel):
    """A skill this agent possesses — a discrete unit of work it can perform."""
    name: str
    description: str
    intent: str  # The intent string used to invoke this skill (e.g. "capability.register")
    inputs: list[ParameterDef] = Field(default_factory=list)
    outputs: list[ParameterDef] = Field(default_factory=list)
    examples: list[SkillExample] = Field(default_factory=list)
    level: SkillLevel = SkillLevel.INTERMEDIATE
    tags: list[str] = Field(default_factory=list)


class SkillExample(BaseModel):
    """A concrete example of invoking a skill."""
    description: str
    input: dict = Field(default_factory=dict)
    expected_output: dict = Field(default_factory=dict)


# Fix forward reference
SkillDef.model_rebuild()


class PromptTemplate(BaseModel):
    """A prompt template used by the agent."""
    name: str  # e.g. "system", "task_execution", "error_recovery"
    role: str = "system"  # system, user, assistant
    template: str  # The actual prompt text, supports {variable} placeholders
    variables: list[str] = Field(default_factory=list)  # Expected placeholder names
    description: str = ""


class InteractionDef(BaseModel):
    """How this agent can be interacted with."""
    modes: list[InteractionMode] = Field(
        default_factory=lambda: [InteractionMode.REQUEST_RESPONSE]
    )
    input_format: str = "json"  # json, text, structured
    output_format: str = "json"
    max_concurrent: int = 10
    timeout_seconds: int = 300
    retry_policy: RetryPolicy = Field(default_factory=lambda: RetryPolicy())


class RetryPolicy(BaseModel):
    """Retry behavior for failed interactions."""
    max_retries: int = 3
    backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retryable_errors: list[str] = Field(default_factory=lambda: ["timeout", "rate_limit"])


# Fix forward reference
InteractionDef.model_rebuild()


class ConstraintDef(BaseModel):
    """A behavioral constraint / guardrail for the agent."""
    name: str
    description: str
    enforcement: str = "strict"  # strict (block), warn, log
    condition: str = ""  # When this constraint applies


class PersonalityDef(BaseModel):
    """The agent's communication style and behavior profile."""
    tone: str = "professional"  # professional, casual, formal, technical
    verbosity: str = "concise"  # minimal, concise, detailed, verbose
    traits: list[str] = Field(default_factory=list)  # e.g. ["precise", "helpful", "cautious"]
    custom_instructions: str = ""  # Free-form behavioral instructions


class DependencyDef(BaseModel):
    """A dependency on another agent."""
    agent_type: str  # The agent type this depends on
    required: bool = True  # Whether the system fails without this dependency
    capabilities_needed: list[str] = Field(default_factory=list)


class ToolDef(BaseModel):
    """An external tool or API the agent can use."""
    name: str
    description: str
    endpoint: str = ""  # URL or function path
    auth_required: bool = False
    parameters: list[ParameterDef] = Field(default_factory=list)


# ── Top-Level Agent Definition ───────────────────────────────────

class AgentDefinition(BaseModel):
    """Complete declarative specification for an agent.

    This is the single source of truth. An agent definition file
    contains everything needed to understand, instantiate, and
    interact with an agent.
    """

    # ── Identity ──
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str  # Human-readable name
    type: str  # Machine identifier (e.g. "capability", "policy")
    version: str = "1.0.0"
    description: str = ""
    domain: str = "general"  # Business domain this agent serves
    tags: list[str] = Field(default_factory=list)

    # ── Skills (what it can do) ──
    skills: list[SkillDef] = Field(default_factory=list)

    # ── Prompts (how it thinks) ──
    prompts: list[PromptTemplate] = Field(default_factory=list)

    # ── Interaction (how to talk to it) ──
    interaction: InteractionDef = Field(default_factory=InteractionDef)

    # ── Personality (how it communicates) ──
    personality: PersonalityDef = Field(default_factory=PersonalityDef)

    # ── Constraints (what it must/must not do) ──
    constraints: list[ConstraintDef] = Field(default_factory=list)

    # ── Dependencies (what it needs) ──
    dependencies: list[DependencyDef] = Field(default_factory=list)

    # ── Tools (external integrations) ──
    tools: list[ToolDef] = Field(default_factory=list)

    # ── Metadata ──
    author: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def intents(self) -> list[str]:
        """All intent strings this agent handles."""
        return [s.intent for s in self.skills]

    @property
    def capability_names(self) -> list[str]:
        """All capability names derived from skills."""
        return [s.intent for s in self.skills]

    def get_skill(self, intent: str) -> SkillDef | None:
        """Look up a skill by its intent string."""
        for skill in self.skills:
            if skill.intent == intent:
                return skill
        return None

    def get_prompt(self, name: str) -> PromptTemplate | None:
        """Look up a prompt template by name."""
        for prompt in self.prompts:
            if prompt.name == name:
                return prompt
        return None

    def render_prompt(self, name: str, **variables: str) -> str | None:
        """Render a prompt template with variables."""
        template = self.get_prompt(name)
        if not template:
            return None
        text = template.template
        for key, value in variables.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text
