"""Demo — shows the full agent system in action.

Run with: python -m examples.demo
"""

import asyncio
import json

from future_agents.system import AgentSystem


def pp(data: dict) -> None:
    """Pretty-print a dict."""
    print(json.dumps(data, indent=2, default=str))


async def main() -> None:
    system = AgentSystem()
    await system.start()
    print("=== Agent System Started ===\n")

    # ── 1. Register capabilities ──────────────────────────────────
    print("── Registering capabilities ──")
    result = await system.handle("capability.register", {
        "name": "Python Development",
        "description": "Write production Python code",
        "domain": "engineering",
        "level": "intermediate",
        "tags": ["python", "backend"],
    })
    python_cap_id = result["data"]["capability_id"]
    print(f"  Registered: Python Development (id={python_cap_id})")

    result = await system.handle("capability.register", {
        "name": "Data Analysis",
        "description": "Analyze datasets and produce insights",
        "domain": "analytics",
        "level": "novice",
        "tags": ["data", "analytics"],
    })
    print(f"  Registered: Data Analysis (id={result['data']['capability_id']})")

    # ── 2. Define a policy ────────────────────────────────────────
    print("\n── Defining policies ──")
    result = await system.handle("policy.define", {
        "name": "Code Review Required",
        "description": "All code changes must be reviewed before deployment",
        "scope": "domain",
        "scope_target": "engineering",
        "rules": [
            {
                "condition": "when deploying code changes",
                "action": "must have at least one approved review",
                "severity": "high",
                "auto_enforce": True,
            },
            {
                "condition": "when modifying security-sensitive code",
                "action": "must have security team review",
                "severity": "critical",
            },
        ],
        "tags": ["engineering", "quality"],
    })
    print(f"  Defined: Code Review Required (id={result['data']['policy_id']})")

    # ── 3. Define a process ───────────────────────────────────────
    print("\n── Defining processes ──")
    result = await system.handle("process.define", {
        "name": "Feature Development Workflow",
        "description": "Standard process for developing a new feature",
        "domain": "engineering",
        "steps": [
            {"name": "Requirements Gathering", "description": "Collect and document requirements"},
            {"name": "Design", "description": "Create technical design document"},
            {"name": "Implementation", "description": "Write the code", "required_capabilities": ["Python Development"]},
            {"name": "Code Review", "description": "Get peer review", "required_policies": ["code_review"]},
            {"name": "Testing", "description": "Write and run tests"},
            {"name": "Deployment", "description": "Deploy to production"},
        ],
        "tags": ["engineering", "sdlc"],
    })
    process_id = result["data"]["process_id"]
    print(f"  Defined: Feature Development Workflow (id={process_id})")

    # ── 4. Register skills and a growth path ──────────────────────
    print("\n── Registering skills ──")
    result = await system.handle("skill.register", {
        "name": "Python",
        "description": "Python programming language proficiency",
        "category": "technical",
        "proficiency": 0.6,
    })
    python_skill_id = result["data"]["skill_id"]
    print(f"  Registered: Python (id={python_skill_id}, proficiency=0.6)")

    result = await system.handle("skill.register", {
        "name": "System Design",
        "description": "Ability to design large-scale systems",
        "category": "technical",
        "proficiency": 0.3,
    })
    design_skill_id = result["data"]["skill_id"]
    print(f"  Registered: System Design (id={design_skill_id}, proficiency=0.3)")

    print("\n── Defining growth path ──")
    result = await system.handle("growth_path.define", {
        "name": "Engineering IC Track",
        "domain": "engineering",
        "levels": [
            {
                "title": "Junior Engineer",
                "level": 1,
                "required_skills": {python_skill_id: 0.3},
                "description": "Entry-level engineering role",
            },
            {
                "title": "Mid-level Engineer",
                "level": 2,
                "required_skills": {python_skill_id: 0.6, design_skill_id: 0.3},
                "description": "Independent contributor",
            },
            {
                "title": "Senior Engineer",
                "level": 3,
                "required_skills": {python_skill_id: 0.8, design_skill_id: 0.6},
                "description": "Technical leader",
            },
        ],
    })
    path_id = result["data"]["path_id"]
    print(f"  Defined: Engineering IC Track (id={path_id})")

    # ── 5. Assess growth and find gaps ────────────────────────────
    print("\n── Growth assessment ──")
    result = await system.handle("growth_path.assess", {
        "path_id": path_id,
        "capabilities": [],
    })
    current = result["data"].get("current_level")
    next_lvl = result["data"].get("next_level")
    print(f"  Current level: {current['title'] if current else 'None'}")
    print(f"  Next level:    {next_lvl['title'] if next_lvl else 'Max reached'}")

    result = await system.handle("growth_path.gaps", {
        "path_id": path_id,
        "target_level": 3,
    })
    print(f"  Gaps to Senior Engineer:")
    for gap in result["data"].get("gaps", []):
        print(f"    - {gap['skill_name']}: {gap['current']:.1f} → {gap['required']:.1f} (deficit: {gap['deficit']:.1f})")

    # ── 6. Add knowledge ──────────────────────────────────────────
    print("\n── Adding knowledge ──")
    result = await system.handle("knowledge.add", {
        "title": "Python Best Practices",
        "domain": "engineering",
        "content": "Use type hints, write tests, follow PEP 8, use virtual environments.",
        "tags": ["python", "best-practices"],
    })
    print(f"  Added: Python Best Practices (id={result['data']['entry_id']})")

    # ── 7. Record capability usage (triggers auto-leveling) ───────
    print("\n── Recording capability usage ──")
    for i in range(15):
        await system.handle("capability.record_usage", {
            "capability_id": python_cap_id,
            "success": i % 3 != 0,  # 67% success rate
        })
    result = await system.handle("capability.query", {"domain": "engineering"})
    cap = result["data"]["capabilities"][0]
    print(f"  Python Development: level={cap['level']}, usage={cap['usage_count']}, "
          f"success_rate={cap['success_rate']:.2f}")

    # ── 8. Execute a process ──────────────────────────────────────
    print("\n── Executing process ──")
    result = await system.handle("process.execute", {"process_id": process_id})
    print(f"  Completed {result['data']['steps_completed']}/{result['data']['steps_completed']} steps")

    # ── 9. Run sync cycle (improvement loop) ──────────────────────
    print("\n── Running sync cycle ──")
    cycle = await system.run_sync_cycle()
    print(f"  Improvements found: {cycle['improvements_found']}")
    print(f"  Auto-applied:       {cycle['auto_applied']}")
    print(f"  Needs review:       {cycle['needs_review']}")

    # ── 10. System health check ───────────────────────────────────
    print("\n── System health ──")
    health = await system.health()
    print(f"  Registered agents: {len(health['agents'])}")
    for agent_id, info in health["agents"].items():
        print(f"    {info['type']:12s}  success_rate={info['success_rate']:.2f}  "
              f"executions={info['execution_count']}")

    print(f"\n  Pending improvements: {health['pending_improvements']}")
    print(f"  Applied improvements: {health['applied_improvements']}")

    await system.stop()
    print("\n=== Agent System Stopped ===")


if __name__ == "__main__":
    asyncio.run(main())
