"""Agent data loader — reads index and YAML definitions from disk.

The agents_index.json only contains 5 fields (id, name, role, type, seniority).
A richer in-memory index is built at startup by scanning YAML files so that
industry/cloud/stack/profile/tags filters work correctly.
"""

from __future__ import annotations

import json
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = _REPO_ROOT / "agents"
INDEX_FILE = AGENTS_DIR / "agents_index.json"
SKILLS_FILE = _REPO_ROOT / "skills" / "combined_guardrails.yaml"
TEMPLATES_DIR = _REPO_ROOT / "templates" / "project-structures"

# Rich index: id → full dict (populated by build_rich_index in background)
_rich_index: dict[str, dict[str, Any]] = {}
_rich_index_ready = threading.Event()


# ── Basic index (5 fields from JSON) ─────────────────────────────────────────

@lru_cache(maxsize=1)
def load_index() -> list[dict[str, Any]]:
    """Load the 5-field agents index (cached after first read)."""
    if not INDEX_FILE.exists():
        logger.warning("agents_index.json not found at %s", INDEX_FILE)
        return []
    with INDEX_FILE.open() as f:
        return json.load(f)


# ── Rich index (all YAML fields — built in background at startup) ─────────────

def build_rich_index() -> None:
    """Scan all agent YAML files and build a rich in-memory index.

    Runs in a background thread.  Takes ~10-20 s for 10,000 files.
    Filters that require non-index fields (industry, cloud, stack, profile, tags)
    will silently return no results until this is ready.
    """
    global _rich_index
    logger.info("Building rich agent index from YAML files…")
    rich: dict[str, dict[str, Any]] = {}

    for yaml_path in AGENTS_DIR.rglob("agent-*.yaml"):
        try:
            data = yaml.safe_load(yaml_path.open())
            if data and isinstance(data, dict):
                aid = data.get("id", "")
                if aid:
                    rich[aid] = data
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping %s: %s", yaml_path, exc)

    # Also pick up voice agents
    for yaml_path in AGENTS_DIR.rglob("voice-*.yaml"):
        try:
            data = yaml.safe_load(yaml_path.open())
            if data and isinstance(data, dict):
                aid = data.get("id", "")
                if aid:
                    rich[aid] = data
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skipping %s: %s", yaml_path, exc)

    _rich_index = rich
    _rich_index_ready.set()
    logger.info("Rich index ready: %d agents indexed", len(rich))


def start_rich_index_build() -> None:
    """Kick off rich-index build in a daemon thread (call once at startup)."""
    t = threading.Thread(target=build_rich_index, daemon=True, name="rich-index-builder")
    t.start()


def get_rich_record(agent_id: str) -> dict[str, Any] | None:
    """Return rich record from in-memory index or None if not ready yet."""
    return _rich_index.get(agent_id)


# ── YAML loader ───────────────────────────────────────────────────────────────

def load_agent_yaml(agent_id: str) -> dict[str, Any] | None:
    """Load the YAML file for a given agent ID.

    Checks rich index first (already parsed) then falls back to disk search.
    """
    if agent_id in _rich_index:
        return _rich_index[agent_id]
    matches = list(AGENTS_DIR.rglob(f"{agent_id}.yaml"))
    if not matches:
        return None
    with matches[0].open() as f:
        return yaml.safe_load(f)


# ── Search ────────────────────────────────────────────────────────────────────

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
    skills: str | None = None,
) -> list[dict[str, Any]]:
    """Filter agents by any combination of fields.

    Uses the rich index when available (all fields), otherwise falls back to
    the basic 5-field index (industry/cloud/stack/profile/skills filters are
    skipped silently until the rich index is ready).
    """
    needs_rich = any([industry, cloud, stack, profile, skills])
    use_rich = _rich_index_ready.is_set() and needs_rich

    if use_rich:
        agents: list[dict[str, Any]] = list(_rich_index.values())
    else:
        agents = load_index()

    results = []
    q = query.lower() if query else None
    skills_q = skills.lower() if skills else None

    for a in agents:
        name = (a.get("name") or "").lower()
        role_val = (a.get("role") or "").lower()

        if q and q not in name and q not in role_val:
            continue
        if role and role.lower() not in role_val:
            continue
        if type_filter and (a.get("type") or "").lower() != type_filter.lower():
            continue
        if seniority and (a.get("seniority") or "").lower() != seniority.lower():
            continue

        # Rich-index-only filters
        if use_rich:
            if industry and industry.lower() not in (a.get("industry_focus") or "").lower():
                continue
            if cloud and cloud.lower() != (a.get("cloud_preference") or "").lower():
                continue
            if stack and stack.lower() not in (a.get("primary_stack") or "").lower():
                continue
            if profile and (a.get("guardrails_profile") or "standard").lower() != profile.lower():
                continue
            if skills_q:
                agent_skills = " ".join(a.get("skills") or []).lower()
                if skills_q not in agent_skills:
                    continue

        results.append(a)

    return results


def recommend_agents(task: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return agents whose skills best match the task description.

    Requires the rich index to be ready; returns [] otherwise.
    """
    if not _rich_index_ready.is_set():
        return []

    task_lower = task.lower()
    scored: list[tuple[int, dict[str, Any]]] = []

    for a in _rich_index.values():
        agent_skills = [s.lower() for s in (a.get("skills") or [])]
        agent_tools = [t.lower() for t in (a.get("tools") or [])]
        role_words = (a.get("role") or "").replace("-", " ").lower()
        desc = (a.get("description") or "").lower()

        score = 0
        for skill in agent_skills:
            for word in skill.replace("-", " ").split():
                if word in task_lower and len(word) > 3:
                    score += 2
        for tool in agent_tools:
            if tool.lower() in task_lower:
                score += 1
        for word in role_words.split():
            if word in task_lower and len(word) > 3:
                score += 1
        for word in desc.split():
            if word in task_lower and len(word) > 4:
                score += 1

        if score > 0:
            scored.append((score, a))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [a for _, a in scored[:limit]]


# ── Stats / Categories ────────────────────────────────────────────────────────

def get_stats() -> dict[str, Any]:
    """Compute marketplace statistics (uses rich index when available)."""
    agents = list(_rich_index.values()) if _rich_index_ready.is_set() else load_index()
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
    agents = list(_rich_index.values()) if _rich_index_ready.is_set() else load_index()
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

    result = [
        {**c, "roles": sorted(c["roles"])} for c in cats.values()
    ]
    return sorted(result, key=lambda x: x["count"], reverse=True)


# ── System Agents (capability / knowledge / master / policy / process / skills) ─

_SYSTEM_AGENT_NAMES = ["capability", "knowledge", "master", "policy", "process", "skills"]


@lru_cache(maxsize=1)
def load_system_agents() -> list[dict[str, Any]]:
    """Load the 6 live system-agent definitions from agents/*.json."""
    agents = []
    for name in _SYSTEM_AGENT_NAMES:
        path = AGENTS_DIR / f"{name}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                data["_id"] = name
                agents.append(data)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not load system agent %s: %s", name, exc)
    return agents


# ── Guardrails Skills ─────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_guardrails() -> dict[str, Any]:
    """Load the combined guardrails skill file."""
    if not SKILLS_FILE.exists():
        return {}
    with SKILLS_FILE.open() as f:
        return yaml.safe_load(f) or {}


# ── Project Templates ─────────────────────────────────────────────────────────

def load_templates() -> list[dict[str, Any]]:
    """List available project-structure templates with their file trees."""
    if not TEMPLATES_DIR.exists():
        return []
    templates = []
    for tdir in sorted(TEMPLATES_DIR.iterdir()):
        if not tdir.is_dir():
            continue
        files = [
            str(p.relative_to(tdir))
            for p in sorted(tdir.rglob("*"))
            if not p.name.startswith(".")
        ]
        templates.append({
            "name": tdir.name,
            "path": str(tdir),
            "file_count": len(files),
            "files": files[:50],  # cap for API response size
        })
    return templates
