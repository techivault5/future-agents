"""Repository knowledge — retrieval and placement for spec-driven delivery.

    knowledge = RepoKnowledge.build(".")
    knowledge.context("weekly churn report")     # what already exists
    knowledge.advise(requirement)                # where it goes, and where it must not

Everything is lexical and offline: an index of symbols and docs, the placement
rules the team already wrote in `AGENTS.md`/`CLAUDE.md`, and the language
toolchain's layout. Swap `RepoIndex.search` for an embedding store and nothing
else changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from future_agents.sdd.knowledge.conventions import Conventions, PlacementRule, Prohibition
from future_agents.sdd.knowledge.index import DirNote, FileNote, RepoIndex, Symbol
from future_agents.sdd.knowledge.placement import PlacementAdvisor
from future_agents.sdd.models import (
    ForbiddenZone,
    PlacementDecision,
    RepoContext,
    RepoMatch,
    Requirement,
    Spec,
)
from future_agents.sdd.repos.languages import RepoProfile, Toolchain


class RepoKnowledge:
    """One object the pipeline holds: the index, the conventions, the advisor."""

    def __init__(
        self,
        index: RepoIndex,
        conventions: Optional[Conventions] = None,
        toolchain: Optional[Toolchain] = None,
    ) -> None:
        self.index = index
        self.conventions = conventions or Conventions()
        self.toolchain = toolchain
        self.advisor = PlacementAdvisor(index, self.conventions, toolchain)

    @classmethod
    def build(
        cls,
        root: str | Path,
        profile: Optional[RepoProfile] = None,
        max_files: int = 4000,
    ) -> "RepoKnowledge":
        index = RepoIndex.build(root, profile=profile, max_files=max_files)
        conventions = Conventions.load(root, known_dirs=index.directories.keys())
        toolchain = index.profile.toolchain() if index.profile else None
        return cls(index, conventions, toolchain)

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def context(self, query: str, limit: int = 5) -> RepoContext:
        """What the repository already knows that bears on this piece of work."""
        matches = self.index.search(query, limit=limit)
        notes: list[str] = []
        code = [m for m in matches if m.kind not in {"docs", "config"}]
        if code:
            notes.append(
                f"{len(code)} existing implementation(s) touch this area — reuse before adding"
            )
        for rule in self.conventions.matching_rules(query, limit=2):
            notes.append(f"convention: {rule.subject} → {rule.destination} ({rule.source})")
        return RepoContext(query=query, matches=matches, notes=notes)

    def duplicate_risk(self, requirement: Requirement, threshold: float = 0.35) -> list[RepoMatch]:
        """Existing code close enough that the requirement may already be met.

        Deliberately strict: two query words must appear in the path or symbol
        name. A weak prose match reported as a duplicate is noise, and noise here
        trains people to ignore the warning that matters.
        """
        return [
            match
            for match in self.index.search(
                requirement.statement, limit=2, kinds=("code",), require_name_overlap=2
            )
            if match.score >= threshold
        ]

    # ── Placement ─────────────────────────────────────────────────────────────

    def advise(self, requirement: Requirement | str) -> PlacementDecision:
        return self.advisor.advise(requirement)

    def plan_placements(self, spec: Spec) -> list[PlacementDecision]:
        return [self.advisor.advise(requirement) for requirement in spec.requirements]

    def forbidden_zones(self) -> list[ForbiddenZone]:
        return self.advisor.forbidden_zones()

    # ── Introspection ─────────────────────────────────────────────────────────

    def stats(self) -> dict[str, object]:
        return {
            **self.index.stats(),
            "convention_sources": self.conventions.sources,
            "placement_rules": len(self.conventions.rules),
            "prohibitions": len(self.conventions.prohibitions),
        }


__all__ = [
    "Conventions",
    "DirNote",
    "FileNote",
    "PlacementAdvisor",
    "PlacementRule",
    "Prohibition",
    "RepoIndex",
    "RepoKnowledge",
    "Symbol",
]
