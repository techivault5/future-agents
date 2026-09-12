"""The workforce — pluggable agents and skills.

    workforce = Workforce.load("data/config/spec_kit/workforce.yaml")
    workforce.bind("claude_coder", my_handler)
    dispatcher = Dispatcher(workforce, language="python")

Specs are data so a team can add an agent in a pull request; handlers are code
bound at runtime. The dispatcher explains every choice it makes.
"""

from future_agents.sdd.workforce.dispatch import (
    Candidate,
    Dispatcher,
    NoAgentAvailable,
    ScoreWeights,
)
from future_agents.sdd.workforce.registry import (
    ANY,
    AgentHandler,
    AgentHealth,
    AgentSpec,
    SkillHandler,
    SkillSpec,
    WorkContext,
    Workforce,
)
from future_agents.sdd.workforce.skills import (
    CallableSkill,
    McpSkill,
    ShellSkill,
    SimulatedSkill,
    SkillError,
    shell_skill,
)

__all__ = [
    "ANY",
    "AgentHandler",
    "AgentHealth",
    "AgentSpec",
    "CallableSkill",
    "Candidate",
    "Dispatcher",
    "McpSkill",
    "NoAgentAvailable",
    "ScoreWeights",
    "ShellSkill",
    "SimulatedSkill",
    "SkillError",
    "SkillHandler",
    "SkillSpec",
    "WorkContext",
    "Workforce",
    "shell_skill",
]
