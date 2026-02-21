#!/usr/bin/env python3
"""Demo: Speech, Listen, and Learning in Action.

Shows agents:
  - Broadcasting and announcing
  - Listening and receiving
  - Teaching each other
  - Learning from experience
  - Generating insights and evolution proposals
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from future_agents.system import AgentSystem

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
logger = logging.getLogger("demo")


def section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def show(label: str, data: dict) -> None:
    print(f"  {label}:")
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ("task_id", "duration_ms"):
                continue
            val = json.dumps(v, indent=4, default=str) if isinstance(v, (dict, list)) else v
            print(f"    {k}: {val}")
    else:
        print(f"    {data}")
    print()


async def main() -> None:
    # ── Boot the system ──────────────────────────────────────────
    section("1. Booting Agent System with Speech/Listen/Learn")

    agents_dir = Path(__file__).resolve().parent.parent / "agents"
    system = AgentSystem(definitions_dir=agents_dir)
    await system.start()

    print(f"  System ready with {len(system.registry.agents)} agents")
    print(f"  Conversation ledger: {system.conversation_ledger.size} entries")
    print()

    # ── Execute some tasks to build experience ───────────────────
    section("2. Executing Tasks (Building Experience)")

    # Register some capabilities
    tasks = [
        ("capability.register", {"name": "Python", "domain": "engineering", "tags": ["language"]}),
        ("capability.register", {"name": "Machine Learning", "domain": "data-science", "tags": ["ai"]}),
        ("capability.register", {"name": "API Design", "domain": "engineering", "tags": ["architecture"]}),
        ("policy.define", {"name": "Code Review Required", "scope": "engineering", "rules": [
            {"rule": "All PRs need at least 1 review", "action": "require_approval"}
        ]}),
        ("skills.register", {"name": "FastAPI", "category": "framework", "proficiency": 0.8}),
    ]

    for intent, params in tasks:
        result = await system.ask(intent, params)
        status = "OK" if result["outcome"] == "success" else "FAIL"
        print(f"  [{status}] {intent}")

    # Also trigger some intentional failures for learning contrast
    fail_result = await system.ask("capability.register", {})  # Missing required "name"
    print(f"  [EXPECTED FAIL] capability.register (no name) -> {fail_result['outcome']}")

    # ── Check the conversation ledger ────────────────────────────
    section("3. Conversation Ledger (Agent Speech Acts)")

    convo = await system.conversation(limit=20)
    messages = convo["data"].get("messages", [])
    print(f"  Total speech acts: {convo['data'].get('count', 0)}")
    for msg in messages[:10]:
        print(f"    [{msg['type']:>10}] {msg['speaker']:>20} -> {msg.get('recipient') or '*':>20}: {msg['text'][:60]}")

    stats = convo["data"].get("stats", {})
    if stats:
        print(f"\n  Conversation stats:")
        print(f"    Total: {stats.get('total', 0)}")
        print(f"    By speaker: {json.dumps(stats.get('by_speaker', {}))}")
        print(f"    By type: {json.dumps(stats.get('by_type', {}))}")

    # ── Teach an agent ───────────────────────────────────────────
    section("4. Teaching Agents")

    teach_result = await system.teach(
        agent_type="capability",
        text="When registering capabilities, always check for duplicates first to avoid redundancy.",
        topic="capability.best_practice",
        content={"priority": "high", "category": "data_quality"},
    )
    show("Teaching result", teach_result)

    teach_result2 = await system.teach(
        agent_type="policy",
        text="Policies should have clear ownership and expiration dates for governance compliance.",
        topic="policy.governance",
        content={"compliance_standard": "ISO27001"},
    )
    show("Teaching result", teach_result2)

    # ── Trigger learning cycle ───────────────────────────────────
    section("5. Learning Cycle (Analyze + Evolve)")

    # Execute more tasks to build up enough data for pattern detection
    for i in range(3):
        await system.ask("capability.register", {
            "name": f"Skill_{i}",
            "domain": "engineering",
        })

    learn_result = await system.learn()
    show("Learning results", learn_result)

    # Show per-agent learning details
    for agent_result in learn_result["data"].get("results", []):
        agent_id = agent_result.get("agent_id", "?")
        memories = agent_result.get("memories", 0)
        insights = agent_result.get("new_insights", 0)
        evolutions = agent_result.get("new_evolutions", 0)
        print(f"    Agent {agent_id}: {memories} memories, {insights} insights, {evolutions} evolutions")

    # ── Run a second learning cycle to see growth ────────────────
    section("6. Second Learning Cycle (Compound Learning)")

    # Execute more tasks
    for i in range(3):
        await system.ask("capability.register", {
            "name": f"Advanced_Skill_{i}",
            "domain": "data-science",
        })

    learn_result2 = await system.learn()
    print(f"  Agents processed: {learn_result2['data'].get('agents_processed', 0)}")
    print(f"  Total insights: {learn_result2['data'].get('total_insights', 0)}")
    print(f"  Total evolutions: {learn_result2['data'].get('total_evolutions', 0)}")

    # ── System status with learning stats ────────────────────────
    section("7. System Status (with Learning & Conversation)")

    status = await system.status()
    status_data = status["data"]
    print(f"  Agents: {status_data.get('agent_count', 0)}")

    convo_stats = status_data.get("conversation", {})
    if convo_stats:
        print(f"  Conversation total: {convo_stats.get('total', 0)}")
        print(f"  By type: {json.dumps(convo_stats.get('by_type', {}))}")

    learning = status_data.get("master_learning", {})
    if learning:
        print(f"  Master memories: {learning.get('total_memories', 0)}")
        print(f"  Memory types: {json.dumps(learning.get('by_type', {}))}")
        print(f"  Avg confidence: {learning.get('avg_confidence', 0):.2f}")

    # ── Final conversation log ───────────────────────────────────
    section("8. Final Conversation Log (Last 15 Acts)")

    final_convo = await system.conversation(limit=15)
    for msg in final_convo["data"].get("messages", []):
        tags = ", ".join(msg.get("tags", [])[:3])
        print(f"  [{msg['type']:>10}] {msg['speaker']:>12} | {msg['text'][:55]:<55} | {tags}")

    # ── Shutdown ─────────────────────────────────────────────────
    section("Done!")
    await system.stop()
    print("  System shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
