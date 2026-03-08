"""Guardrails profiles and skills — expose the combined_guardrails.yaml via API.

Developers can query which profiles exist, what rules they enforce, and which
guardrails patterns apply to any given agent's profile.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from future_agents.api import loader

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])


@router.get("")
def get_guardrails_overview() -> dict:
    """Overview of all guardrails metadata, profiles, and skills."""
    data = loader.load_guardrails()
    if not data:
        return {"error": "Guardrails config not found"}

    profiles = data.get("profiles", {})
    skills = data.get("skills", [])

    return {
        "metadata": data.get("metadata", {}),
        "profiles": {
            name: {
                "description": cfg.get("description", ""),
                "inherits": cfg.get("inherits", []),
                "overrides": cfg.get("overrides", {}),
            }
            for name, cfg in profiles.items()
        },
        "skills": [
            {
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "description": s.get("description", ""),
                "enabled": s.get("enabled", True),
                "severity": s.get("severity", "warn"),
                "action": s.get("action", "warn"),
                "ask_human_on_violation": s.get("ask_human_on_violation", False),
                "pattern_count": len(s.get("patterns", [])),
            }
            for s in skills
        ],
        "profile_count": len(profiles),
        "skill_count": len(skills),
    }


@router.get("/profiles")
def list_profiles() -> dict:
    """All guardrails profiles with their full rule configurations."""
    data = loader.load_guardrails()
    return data.get("profiles", {})


@router.get("/profiles/{profile_name}")
def get_profile(profile_name: str) -> dict:
    """Get a specific guardrails profile by name."""
    data = loader.load_guardrails()
    profiles = data.get("profiles", {})
    if profile_name not in profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Profile '{profile_name}' not found. Available: {list(profiles.keys())}",
        )
    return {
        "name": profile_name,
        **profiles[profile_name],
    }


@router.get("/skills")
def list_skills() -> list:
    """All guardrails enforcement skills with their patterns and configs."""
    data = loader.load_guardrails()
    return data.get("skills", [])


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str) -> dict:
    """Get a specific guardrails skill with all its patterns."""
    data = loader.load_guardrails()
    skills = data.get("skills", [])
    for s in skills:
        if s.get("id", "").upper() == skill_id.upper():
            return s
    raise HTTPException(
        status_code=404,
        detail=f"Skill '{skill_id}' not found. Available: {[s.get('id') for s in skills]}",
    )


@router.get("/agents/{agent_id}")
def get_agent_guardrails(agent_id: str) -> dict:
    """Return the effective guardrails rules that apply to a specific agent.

    Resolves the agent's guardrails_profile to its full rule set.
    """
    agent = loader.load_agent_yaml(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    profile_name = agent.get("guardrails_profile", "standard")
    data = loader.load_guardrails()
    profiles = data.get("profiles", {})
    profile = profiles.get(profile_name, profiles.get("standard", {}))

    # Resolve inheritance chain
    resolved_overrides: dict = {}
    for parent in profile.get("inherits", []):
        parent_cfg = profiles.get(parent, {})
        resolved_overrides.update(parent_cfg.get("overrides", {}))
    resolved_overrides.update(profile.get("overrides", {}))

    return {
        "agent_id": agent_id,
        "agent_name": agent.get("name", agent_id),
        "profile": profile_name,
        "human_input_required": agent.get("human_input_required", False),
        "package_policy": agent.get("package_policy", "semver-minor-auto-upgrade"),
        "effective_rules": resolved_overrides,
        "profile_description": profile.get("description", ""),
        "inherits": profile.get("inherits", []),
        "skills_applied": [
            s.get("id") for s in data.get("skills", []) if s.get("enabled", True)
        ],
    }
