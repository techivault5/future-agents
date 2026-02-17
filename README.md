# future-agents

A self-improving multi-agent system for managing organizational capabilities, processes, policies, skills, and knowledge — with continuous learning built into its core.

## Architecture

```
┌────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                         │
│    Router → Planner → Executor → Evaluator             │
└──────────────────────┬─────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────┐
│                  AGENT REGISTRY                         │
│  Capability │ Process │ Policy │ Skills │ Knowledge     │
└──────────────────────┬─────────────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────────────┐
│              SHARED INFRASTRUCTURE                      │
│  Knowledge Store │ Event Bus │ Sync Engine │ Metrics    │
└────────────────────────────────────────────────────────┘
```

### Key components

| Component | Purpose |
|---|---|
| **Orchestrator** | Routes tasks to agents, plans multi-step workflows, evaluates outcomes |
| **Agent Registry** | Lifecycle management, discovery by type/capability, health checks |
| **Capability Agent** | Tracks what the org can do, auto-levels based on usage |
| **Process Agent** | Manages SOPs/workflows, tracks completion rates |
| **Policy Agent** | Defines rules, checks compliance, reports violations |
| **Skills Agent** | Maps skills/titles, defines growth paths, identifies gaps |
| **Knowledge Agent** | Versioned knowledge base, search, staleness auditing |
| **Sync Engine** | Continuous improvement loop — analyzes feedback, proposes improvements |
| **Event Bus** | Async pub/sub for inter-agent communication |
| **Metric Tracker** | Counters, gauges, time series across the system |

### Self-improvement loop

Every task execution produces feedback that flows through the Sync Engine:

```
Execute → Collect Feedback → Analyze Patterns → Propose Improvements → Apply → Sync
```

## Quick start

```bash
pip install -e .
python -m examples.demo
```

## Usage

```python
import asyncio
from future_agents.system import AgentSystem

async def main():
    system = AgentSystem()
    await system.start()

    # Register a capability
    await system.handle("capability.register", {
        "name": "Python Development",
        "domain": "engineering",
        "level": "intermediate",
    })

    # Define a policy
    await system.handle("policy.define", {
        "name": "Code Review Required",
        "rules": [{"condition": "deploying code", "action": "must have review", "severity": "high"}],
    })

    # Define a process
    await system.handle("process.define", {
        "name": "Feature Workflow",
        "domain": "engineering",
        "steps": [
            {"name": "Design", "description": "Technical design"},
            {"name": "Implement", "description": "Write code"},
            {"name": "Review", "description": "Peer review"},
        ],
    })

    # Register skills and growth paths
    await system.handle("skill.register", {
        "name": "Python", "category": "technical", "proficiency": 0.6,
    })

    # Run improvement cycle
    await system.run_sync_cycle()

    # Check system health
    health = await system.health()
    print(health)

    await system.stop()

asyncio.run(main())
```

## Project structure

```
future_agents/
├── core/
│   ├── base_agent.py       # Abstract base agent with lifecycle hooks
│   ├── events.py           # Pub/sub event bus
│   ├── orchestrator.py     # Task routing and multi-step planning
│   └── registry.py         # Agent lifecycle and discovery
├── agents/
│   ├── capability_agent.py # Organizational capability management
│   ├── process_agent.py    # Workflow/SOP management
│   ├── policy_agent.py     # Policy enforcement and compliance
│   ├── skills_agent.py     # Skills, titles, and growth paths
│   └── knowledge_agent.py  # Knowledge base management
├── infrastructure/
│   ├── knowledge_store.py  # Versioned knowledge storage
│   ├── metric_tracker.py   # Performance metrics
│   └── sync_engine.py      # Continuous improvement loop
├── models/
│   ├── capability.py       # Capability domain model
│   ├── process.py          # Process/workflow domain model
│   ├── policy.py           # Policy domain model
│   ├── skill.py            # Skill and growth path models
│   ├── feedback.py         # Execution feedback model
│   └── knowledge.py        # Knowledge entry model
└── system.py               # Top-level system factory
```
