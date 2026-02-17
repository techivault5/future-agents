"""Demo — Master Agent extracts full profiles from every agent.

Shows the profile extraction system:
  - Profile a single agent (all columns)
  - Profile all agents at once
  - Human-readable table output
  - Structured JSON output

Run with: python -m examples.demo_profiles
"""

import asyncio
import json
from pathlib import Path

from future_agents.system import AgentSystem

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFINITIONS_DIR = PROJECT_ROOT / "agents"


def section(title: str) -> None:
    print(f"\n{'#' * 70}")
    print(f"#  {title}")
    print(f"{'#' * 70}")


async def main() -> None:
    system = AgentSystem(definitions_dir=DEFINITIONS_DIR)
    await system.start()
    print("=== System started — profiling agents ===\n")

    # ── 1. Profile a single agent (table format) ─────────────
    section("1. SINGLE AGENT PROFILE: Capability Agent (table view)")
    result = await system.profile(agent_type="capability", output_format="table")
    print(result["data"]["table"])

    # ── 2. Profile another agent (table format) ──────────────
    section("2. SINGLE AGENT PROFILE: Skills Agent (table view)")
    result = await system.profile(agent_type="skills", output_format="table")
    print(result["data"]["table"])

    # ── 3. Profile the Policy Agent (table format) ───────────
    section("3. SINGLE AGENT PROFILE: Policy Agent (table view)")
    result = await system.profile(agent_type="policy", output_format="table")
    print(result["data"]["table"])

    # ── 4. Profile all agents — show summary of columns ──────
    section("4. ALL AGENT PROFILES — Column Summary")
    result = await system.profile_all(output_format="columns")
    profiles = result["data"]["profiles"]

    print(f"\n  Agents profiled: {result['data']['count']}")
    print(f"  Columns per profile: {result['data']['columns']}")

    for p in profiles:
        profile = p["profile"]
        identity = profile["identity"]
        print(f"\n  {'─' * 60}")
        print(f"  {identity['name']} (type: {p['agent_type']})")
        print(f"  {'─' * 60}")
        print(f"    Do's:          {len(profile['dos'])}")
        print(f"    Don'ts:        {len(profile['donts'])}")
        print(f"    Hard Skills:   {len(profile['skills'])}")
        print(f"    Soft Skills:   {len(profile['soft_skills'])}")
        print(f"    Tools:         {len(profile['tools'])}")
        print(f"    Prompts:       {len(profile['prompts'])}")
        print(f"    Dependencies:  {len(profile['dependencies'])}")
        print(f"    Strengths:     {len(profile['strengths'])}")
        print(f"    Weaknesses:    {len(profile['weaknesses'])}")

    # ── 5. Detailed comparison — do's and don'ts across agents ─
    section("5. CROSS-AGENT COMPARISON: Do's and Don'ts")
    for p in profiles:
        name = p["profile"]["identity"]["name"]
        print(f"\n  {name}")
        print(f"  {'.' * 50}")
        print(f"  DO:")
        for do in p["profile"]["dos"][:4]:
            action = do["action"][:80]
            print(f"    + {action}")
        if len(p["profile"]["dos"]) > 4:
            print(f"    ... and {len(p['profile']['dos']) - 4} more")
        print(f"  DON'T:")
        for dont in p["profile"]["donts"]:
            restriction = dont["restriction"][:80]
            print(f"    - {restriction}  [{dont['enforcement']}]")

    # ── 6. Full text report for all agents ────────────────────
    section("6. FULL TEXT REPORT (all agents)")
    result = await system.profile_all(output_format="full")
    # Print just the first agent's full table to keep output manageable
    if result["data"]["profiles"]:
        first = result["data"]["profiles"][0]
        print(f"\n  Showing: {first['agent_type']}")
        print(first["table"])
        remaining = result["data"]["count"] - 1
        if remaining > 0:
            print(f"\n  ... and {remaining} more agent profiles available")

    await system.stop()
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
