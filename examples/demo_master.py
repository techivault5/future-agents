"""Demo — Master Agent with definition-driven agents.

Shows the complete system:
  - Agents loaded from JSON definition files
  - Master Agent discovering and delegating to all agents
  - Multi-agent workflows
  - Agent catalog generation
  - System status reporting

Run with: python -m examples.demo_master
"""

import asyncio
import json
from pathlib import Path

from future_agents.system import AgentSystem

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFINITIONS_DIR = PROJECT_ROOT / "agents"


def pp(data: dict, indent: int = 2) -> None:
    """Pretty-print a dict."""
    print(json.dumps(data, indent=indent, default=str))


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


async def main() -> None:
    # ── Boot the system from definition files ─────────────────
    system = AgentSystem(definitions_dir=DEFINITIONS_DIR)
    await system.start()
    print("=== Agent System Started (definition-driven + Master Agent) ===")

    # ── 1. Discover all agents ────────────────────────────────
    section("1. DISCOVER ALL AGENTS")
    result = await system.discover()
    for agent in result["data"]["agents"]:
        skills_count = len(agent.get("skills", agent.get("capabilities", [])))
        domain = agent.get("domain", "n/a")
        name = agent.get("name", agent.get("type", "unknown"))
        print(f"  [{agent.get('type', '?'):12s}]  {name:25s}  domain={domain:15s}  skills={skills_count}")

    # ── 2. Print the agent catalog (what the Master sees) ─────
    section("2. MASTER AGENT'S VIEW (catalog)")
    catalog = system.get_agent_catalog()
    # Just print first 40 lines to keep output manageable
    for line in catalog.split("\n")[:40]:
        print(f"  {line}")
    print("  ...")

    # ── 3. Route tasks through the Master Agent ───────────────
    section("3. ROUTE TASKS VIA MASTER AGENT")

    print("\n  >> Register a capability (Master routes to Capability Agent)")
    result = await system.ask("capability.register", {
        "name": "Machine Learning",
        "description": "Build and deploy ML models",
        "domain": "engineering",
        "level": "advanced",
        "tags": ["ml", "ai", "data-science"],
    })
    cap_id = result["data"]["result"]["capability_id"]
    print(f"     Delegated to: {result['data']['agent_type']}")
    print(f"     Result: capability_id={cap_id}")

    print("\n  >> Define a policy (Master routes to Policy Agent)")
    result = await system.ask("policy.define", {
        "name": "ML Model Validation",
        "description": "All ML models must pass validation before deployment",
        "scope": "domain",
        "scope_target": "engineering",
        "rules": [
            {
                "condition": "deploying ML model",
                "action": "must pass accuracy threshold",
                "severity": "critical",
                "auto_enforce": True,
            },
        ],
        "tags": ["ml", "validation"],
    })
    print(f"     Delegated to: {result['data']['agent_type']}")
    print(f"     Result: policy_id={result['data']['result']['policy_id']}")

    print("\n  >> Register a skill (Master routes to Skills Agent)")
    result = await system.ask("skill.register", {
        "name": "PyTorch",
        "description": "Deep learning framework proficiency",
        "category": "technical",
        "proficiency": 0.4,
    })
    skill_id = result["data"]["result"]["skill_id"]
    print(f"     Delegated to: {result['data']['agent_type']}")
    print(f"     Result: skill_id={skill_id}")

    print("\n  >> Add skill evidence (Master routes to Skills Agent)")
    result = await system.ask("skill.add_evidence", {
        "skill_id": skill_id,
        "description": "Built a CNN image classifier with 95% accuracy",
        "proficiency_delta": 0.1,
    })
    print(f"     New proficiency: {result['data']['result']['new_proficiency']}")

    print("\n  >> Add knowledge (Master routes to Knowledge Agent)")
    result = await system.ask("knowledge.add", {
        "title": "ML Deployment Checklist",
        "content": "1. Validate model accuracy. 2. Check for bias. 3. Test edge cases. 4. Deploy canary. 5. Monitor metrics.",
        "domain": "engineering",
        "tags": ["ml", "deployment", "checklist"],
    })
    print(f"     Delegated to: {result['data']['agent_type']}")
    print(f"     Result: entry_id={result['data']['result']['entry_id']}")

    # ── 4. Execute a multi-agent workflow ─────────────────────
    section("4. MULTI-AGENT WORKFLOW")
    print("  Workflow: 'Onboard New ML Capability'")
    print("  Steps: register capability -> define process -> check compliance -> add knowledge\n")

    result = await system.workflow("Onboard New ML Capability", [
        {
            "intent": "capability.register",
            "parameters": {
                "name": "NLP Processing",
                "description": "Natural language processing and text analysis",
                "domain": "engineering",
                "level": "intermediate",
                "tags": ["nlp", "text", "ai"],
            },
        },
        {
            "intent": "process.define",
            "parameters": {
                "name": "NLP Model Development",
                "domain": "engineering",
                "steps": [
                    {"name": "Data Collection", "description": "Gather training data"},
                    {"name": "Preprocessing", "description": "Clean and tokenize text"},
                    {"name": "Training", "description": "Train the NLP model"},
                    {"name": "Evaluation", "description": "Evaluate model performance"},
                    {"name": "Deployment", "description": "Deploy to production"},
                ],
            },
        },
        {
            "intent": "policy.check",
            "parameters": {
                "context": {"action": "deploying NLP model"},
                "domain": "engineering",
            },
        },
        {
            "intent": "knowledge.add",
            "parameters": {
                "title": "NLP Best Practices",
                "content": "Use pre-trained embeddings. Fine-tune on domain data. Monitor for drift.",
                "domain": "engineering",
                "tags": ["nlp", "best-practices"],
            },
        },
    ])

    wf_data = result["data"]
    print(f"  Outcome: {result['outcome']}")
    print(f"  Steps completed: {wf_data['steps_completed']}/{wf_data['total_steps']}")
    for step in wf_data["results"]:
        agent = step.get("agent", "n/a")
        print(f"    Step {step['step']}: {step['intent']:30s}  [{step['status']}]  agent={agent}")

    # ── 5. Record some capability usage for metrics ───────────
    section("5. CAPABILITY USAGE TRACKING")
    for i in range(10):
        await system.ask("capability.record_usage", {
            "capability_id": cap_id,
            "success": i % 4 != 0,
        })
    result = await system.ask("capability.query", {"domain": "engineering"})
    for cap in result["data"]["result"]["capabilities"]:
        print(f"  {cap['name']:25s}  level={cap['level']:15s}  "
              f"usage={cap['usage_count']}  success={cap['success_rate']:.2f}")

    # ── 6. Run the improvement cycle ──────────────────────────
    section("6. SYNC ENGINE (improvement cycle)")
    cycle = await system.run_sync_cycle()
    print(f"  Improvements found: {cycle['improvements_found']}")
    print(f"  Auto-applied:       {cycle['auto_applied']}")
    print(f"  Needs review:       {cycle['needs_review']}")

    # ── 7. Full system status via Master Agent ────────────────
    section("7. SYSTEM STATUS (via Master Agent)")
    result = await system.status()
    status = result["data"]
    print(f"  Total agents: {status['agent_count']}")
    for agent_info in status["agents"]:
        name = agent_info.get("name", agent_info["type"])
        version = agent_info.get("version", "n/a")
        skills = agent_info.get("skills", "n/a")
        print(
            f"    {name:25s}  v{version:6s}  "
            f"skills={skills!s:3s}  "
            f"success_rate={agent_info['success_rate']:.2f}  "
            f"executions={agent_info['execution_count']}"
        )

    improvements = status.get("improvements", {})
    print(f"\n  Improvements: {improvements.get('applied', 0)} applied, "
          f"{improvements.get('proposed', 0)} pending")

    await system.stop()
    print(f"\n{'=' * 60}")
    print("=== Agent System Stopped ===")


if __name__ == "__main__":
    asyncio.run(main())
