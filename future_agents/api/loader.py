"""Agent data loader — reads index and YAML definitions from disk."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Resolve agents/ relative to this package's location in the repo
_REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = _REPO_ROOT / "agents"
INDEX_FILE = AGENTS_DIR / "agents_index.json"


@lru_cache(maxsize=1)
def load_index() -> list[dict[str, Any]]:
    """Load the full agents index (cached after first read)."""
    if not INDEX_FILE.exists():
        logger.warning("agents_index.json not found at %s", INDEX_FILE)
        return []
    with INDEX_FILE.open() as f:
        return json.load(f)


def load_agent_yaml(agent_id: str) -> dict[str, Any] | None:
    """Locate and load the YAML file for a given agent ID."""
    # Search all subdirectories for the agent file
    matches = list(AGENTS_DIR.rglob(f"{agent_id}.yaml"))
    if not matches:
        return None
    with matches[0].open() as f:
        return yaml.safe_load(f)


def search_index(
    *,
    query: str | None = None,
    role: str | None = None,
    type_filter: str | None = None,
    seniority: str | None = None,
    industry: str | None = None,
    cloud: str | None = None,
    stack: str | None = None,
    profile: str | None = None,
) -> list[dict[str, Any]]:
    """Filter the index by any combination of fields."""
    agents = load_index()
    results = []
    q = query.lower() if query else None

    for a in agents:
        if q and q not in a.get("name", "").lower() and q not in a.get("role", "").lower():
            continue
        if role and role.lower() not in a.get("role", "").lower():
            continue
        if type_filter and a.get("type", "").lower() != type_filter.lower():
            continue
        if seniority and a.get("seniority", "").lower() != seniority.lower():
            continue
        if industry and industry.lower() not in a.get("industry_focus", "").lower():
            continue
        if cloud and cloud.lower() != a.get("cloud_preference", "").lower():
            continue
        if stack and stack.lower() not in a.get("primary_stack", "").lower():
            continue
        if profile and a.get("guardrails_profile", "").lower() != profile.lower():
            continue
        results.append(a)

    return results


def get_stats() -> dict[str, Any]:
    """Compute marketplace statistics from the index."""
    agents = load_index()
    stats: dict[str, Any] = {
        "total_agents": len(agents),
        "technical": 0,
        "non_technical": 0,
        "voice": 0,
        "seniority_breakdown": {},
        "top_roles": [],
        "guardrails_profiles": {},
    }
    role_counts: dict[str, int] = {}

    for a in agents:
        t = a.get("type", "")
        if t == "technical":
            stats["technical"] += 1
        elif t == "non-technical":
            stats["non_technical"] += 1
        elif t == "voice":
            stats["voice"] += 1

        sen = a.get("seniority", "unknown")
        stats["seniority_breakdown"][sen] = stats["seniority_breakdown"].get(sen, 0) + 1

        role = a.get("role", "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1

        gp = a.get("guardrails_profile", "standard")
        stats["guardrails_profiles"][gp] = stats["guardrails_profiles"].get(gp, 0) + 1

    stats["top_roles"] = sorted(
        [{"role": r, "count": c} for r, c in role_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:20]

    return stats


def get_categories() -> list[dict[str, Any]]:
    """Return unique role categories with counts."""
    agents = load_index()
    cats: dict[str, dict[str, Any]] = {}

    for a in agents:
        role = a.get("role", "unknown")
        t = a.get("type", "unknown")
        key = f"{t}:{role}"
        if key not in cats:
            cats[key] = {"category": role, "type": t, "count": 0, "roles": set()}
        cats[key]["count"] += 1
        if a.get("seniority"):
            cats[key]["roles"].add(a["seniority"])

    result = []
    for c in cats.values():
        result.append({**c, "roles": sorted(c["roles"])})

    return sorted(result, key=lambda x: x["count"], reverse=True)
