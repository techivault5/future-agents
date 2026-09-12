"""Repository awareness — what a repo is written in, and what shape it must have.

from future_agents.sdd.repos import detect_repo, RepoScaffolder
"""

from future_agents.sdd.repos.languages import (
    BY_LANGUAGE,
    GENERIC,
    TOOLCHAINS,
    LanguageSignal,
    LayoutEntry,
    RepoProfile,
    Toolchain,
    detect_repo,
    language_matrix,
    toolchain_for,
)
from future_agents.sdd.repos.scaffold import (
    FORBIDDEN,
    RepoScaffolder,
    ScaffoldAction,
    ScaffoldPlan,
)

__all__ = [
    "BY_LANGUAGE",
    "FORBIDDEN",
    "GENERIC",
    "LanguageSignal",
    "LayoutEntry",
    "RepoProfile",
    "RepoScaffolder",
    "ScaffoldAction",
    "ScaffoldPlan",
    "TOOLCHAINS",
    "Toolchain",
    "detect_repo",
    "language_matrix",
    "toolchain_for",
]
