"""Agentic Synthesis — novel meta-agent combining best-of-breed agentic AI patterns.

Synthesised from:
  MRKL          → AdaptiveRouter  (modular expert routing)
  CrewAI         → SwarmCoordinator  (role-based parallel crews)
  MetaGPT        → SwarmCoordinator  (structured company roles)
  AutoGen        → SwarmCoordinator  (multi-agent conversation)
  Reflexion      → ReflexionLoop  (verbal RL self-improvement)
  MemGPT         → LifelongMemory  (tiered memory management)
  Voyager        → LifelongMemory  (cross-session skill library)
  BabyAGI        → AdaptiveRouter  (task queue + priority)
  LangGraph      → CognitiveSwarmAgent  (stateful execution graph)
"""

from future_agents.agentic_synthesis.adaptive_router import (
    AdaptiveRouter,
    RouteDecision,
    TaskComplexity,
    TaskDomain,
)
from future_agents.agentic_synthesis.cognitive_swarm_agent import CognitiveSwarmAgent
from future_agents.agentic_synthesis.lifelong_memory import (
    LifelongMemory,
    MemoryEntry,
    MemorySearchResult,
)
from future_agents.agentic_synthesis.reflexion_loop import (
    ReflexionLoop,
    ReflexionResult,
    ReflexionTrace,
)
from future_agents.agentic_synthesis.swarm_coordinator import (
    AgentRole,
    SwarmCoordinator,
    SwarmResult,
    SwarmSpec,
)

__all__ = [
    "AdaptiveRouter", "RouteDecision", "TaskComplexity", "TaskDomain",
    "LifelongMemory", "MemoryEntry", "MemorySearchResult",
    "AgentRole", "SwarmCoordinator", "SwarmResult", "SwarmSpec",
    "ReflexionLoop", "ReflexionResult", "ReflexionTrace",
    "CognitiveSwarmAgent",
]
