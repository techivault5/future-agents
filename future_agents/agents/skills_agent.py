"""Skills Agent — manages skills, titles, and growth paths."""

from __future__ import annotations

from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.feedback import ExecutionOutcome
from future_agents.models.skill import GrowthPath, Skill, SkillCategory, TitleLevel


class SkillsAgent(BaseAgent):
    """Manages organizational skills taxonomy and career growth.

    Handles:
    - Registering and categorizing skills
    - Defining growth paths and title ladders
    - Tracking skill progression with evidence
    - Identifying skill gaps for target titles
    - Recommending development priorities
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._skills: dict[str, Skill] = {}
        self._growth_paths: dict[str, GrowthPath] = {}

    @property
    def agent_type(self) -> str:
        return "skills"

    @property
    def capabilities(self) -> list[str]:
        return [
            "skill.register",
            "skill.query",
            "skill.add_evidence",
            "growth_path.define",
            "growth_path.assess",
            "growth_path.gaps",
        ]

    async def _execute(self, context: TaskContext) -> TaskResult:
        handlers = {
            "skill.register": self._register_skill,
            "skill.query": self._query_skills,
            "skill.add_evidence": self._add_evidence,
            "growth_path.define": self._define_growth_path,
            "growth_path.assess": self._assess_growth,
            "growth_path.gaps": self._find_gaps,
        }
        handler = handlers.get(context.intent)
        if not handler:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Unknown intent: {context.intent}"],
            )
        return await handler(context, context.parameters)

    async def _register_skill(self, context: TaskContext, params: dict) -> TaskResult:
        skill = Skill(
            name=params["name"],
            description=params.get("description", ""),
            category=SkillCategory(params.get("category", "technical")),
            proficiency=params.get("proficiency", 0.0),
            related_capabilities=params.get("related_capabilities", []),
            prerequisites=params.get("prerequisites", []),
        )
        self._skills[skill.id] = skill

        await self.emit(
            "skill.registered",
            {"skill_id": skill.id, "name": skill.name, "category": skill.category.value},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"skill_id": skill.id, "skill": skill.model_dump(mode="json")},
        )

    async def _query_skills(self, context: TaskContext, params: dict) -> TaskResult:
        category = params.get("category")
        min_proficiency = params.get("min_proficiency", 0.0)
        results = list(self._skills.values())
        if category:
            results = [s for s in results if s.category == SkillCategory(category)]
        results = [s for s in results if s.proficiency >= min_proficiency]
        results.sort(key=lambda s: s.proficiency, reverse=True)

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"skills": [s.model_dump(mode="json") for s in results]},
        )

    async def _add_evidence(self, context: TaskContext, params: dict) -> TaskResult:
        skill_id = params.get("skill_id", "")
        skill = self._skills.get(skill_id)
        if not skill:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Skill not found: {skill_id}"],
            )

        description = params.get("description", "")
        delta = params.get("proficiency_delta", 0.05)
        skill.add_evidence(description, delta)

        await self.emit(
            "skill.evidence_added",
            {"skill_id": skill_id, "new_proficiency": skill.proficiency},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "skill_id": skill_id,
                "new_proficiency": skill.proficiency,
                "evidence_count": len(skill.evidence),
            },
        )

    async def _define_growth_path(self, context: TaskContext, params: dict) -> TaskResult:
        levels = [
            TitleLevel(
                title=lvl["title"],
                level=lvl["level"],
                required_skills=lvl.get("required_skills", {}),
                required_capabilities=lvl.get("required_capabilities", []),
                description=lvl.get("description", ""),
            )
            for lvl in params.get("levels", [])
        ]

        path = GrowthPath(
            name=params["name"],
            domain=params.get("domain", "general"),
            levels=levels,
        )
        self._growth_paths[path.id] = path

        await self.emit(
            "growth_path.defined",
            {"path_id": path.id, "name": path.name, "level_count": len(levels)},
        )

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"path_id": path.id, "path": path.model_dump(mode="json")},
        )

    async def _assess_growth(self, context: TaskContext, params: dict) -> TaskResult:
        path_id = params.get("path_id", "")
        path = self._growth_paths.get(path_id)
        if not path:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Growth path not found: {path_id}"],
            )

        # Build current skill proficiency map
        skills_map = {sid: s.proficiency for sid, s in self._skills.items()}
        cap_list = list(params.get("capabilities", []))

        current = path.current_level(skills_map, cap_list)
        next_level = path.next_level(skills_map, cap_list)

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "current_level": current.model_dump() if current else None,
                "next_level": next_level.model_dump() if next_level else None,
                "path_name": path.name,
            },
        )

    async def _find_gaps(self, context: TaskContext, params: dict) -> TaskResult:
        path_id = params.get("path_id", "")
        target_level_num = params.get("target_level")
        path = self._growth_paths.get(path_id)
        if not path:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Growth path not found: {path_id}"],
            )

        target = None
        if target_level_num is not None:
            for level in path.levels:
                if level.level == target_level_num:
                    target = level
                    break
        else:
            # Default to next level
            skills_map = {sid: s.proficiency for sid, s in self._skills.items()}
            target = path.next_level(skills_map, [])

        if not target:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.SUCCESS,
                data={"message": "No target level found or already at maximum"},
            )

        skills_map = {sid: s.proficiency for sid, s in self._skills.items()}
        gaps = path.skill_gaps(target, skills_map)

        # Enrich gaps with skill names
        enriched_gaps = []
        for skill_id, deficit in gaps.items():
            skill = self._skills.get(skill_id)
            enriched_gaps.append(
                {
                    "skill_id": skill_id,
                    "skill_name": skill.name if skill else "unknown",
                    "current": skills_map.get(skill_id, 0.0),
                    "required": skills_map.get(skill_id, 0.0) + deficit,
                    "deficit": deficit,
                }
            )

        enriched_gaps.sort(key=lambda g: g["deficit"], reverse=True)

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "target_title": target.title,
                "target_level": target.level,
                "gaps": enriched_gaps,
                "total_gaps": len(enriched_gaps),
            },
            suggestions=[f"Develop skill: {g['skill_name']}" for g in enriched_gaps[:3]],
        )

    async def assess_self(self) -> dict[str, Any]:
        skills = list(self._skills.values())
        category_dist = {}
        for s in skills:
            category_dist[s.category.value] = category_dist.get(s.category.value, 0) + 1
        return {
            "total_skills": len(skills),
            "category_distribution": category_dist,
            "avg_proficiency": (sum(s.proficiency for s in skills) / len(skills) if skills else 0),
            "growth_paths": len(self._growth_paths),
        }
