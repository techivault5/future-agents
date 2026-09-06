"""Project documents — the record a delivery leaves behind, in the repository.

One folder per delivery, always the same shape, so anyone landing on it six
months later finds the same things in the same places:

    docs/projects/<slug>/
      README.md              what this is, who asked, where it stands
      01-objective.md        the ask, its provenance, what was clarified
      02-semantics.md        the vocabulary, the capabilities, the thought process
      03-architecture.md     components, placement, diagrams, risks
      04-work-breakdown.md   the tracked items and their GitHub issues
      05-implementation.md   what actually ran, with evidence
      06-qa.md               checks, coverage, findings, verdict
      07-observability.md    signals, objectives, alerts, runbook
      08-metrics.md          every metric and the question it answers
      09-decisions.md        what was decided, and what it cost to decide it
      10-changelog.md        the run, event by event

Every file is generated from run state, so none of it can quietly drift from
what happened; a section with nothing to say says that, rather than being
omitted, because an empty QA section and a missing one mean very different
things.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import (
    MetricSet,
    RunState,
    SemanticModel,
    WorkBreakdown,
)
from future_agents.sdd.project_docs.mermaid import (
    method_diagram,
    structure_diagram,
    traceability_diagram,
)
from future_agents.sdd.project_docs.sections import (
    architecture_md,
    changelog_md,
    decisions_md,
    implementation_md,
    metrics_md,
    objective_md,
    observability_md,
    qa_md,
    readme_md,
    semantics_md,
    slug_for,
    work_breakdown_md,
)

__all__ = [
    "DocumentSet",
    "ProjectDocs",
    "method_diagram",
    "slug_for",
    "structure_diagram",
    "traceability_diagram",
]


class DocumentSet(BaseModel):
    """The rendered folder: relative path → markdown."""

    slug: str
    root: str  # e.g. docs/projects/refund-tooling
    files: dict[str, str] = Field(default_factory=dict)

    def paths(self) -> list[str]:
        return [f"{self.root}/{name}" for name in sorted(self.files)]

    def write(self, repo_root: str | Path) -> list[Path]:
        """Write the set under a repository. Returns what was written."""
        base = Path(repo_root) / self.root
        base.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for name, body in sorted(self.files.items()):
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
            written.append(target)
        return written


class ProjectDocs:
    """Builds the document set for one run."""

    def __init__(self, directory: str = "docs/projects") -> None:
        self.directory = directory.rstrip("/")

    def build(
        self,
        state: RunState,
        *,
        semantics: Optional[SemanticModel] = None,
        breakdown: Optional[WorkBreakdown] = None,
        metrics: Optional[MetricSet] = None,
        issue_refs: Optional[dict[str, str]] = None,
    ) -> DocumentSet:
        spec = state.spec
        slug = slug_for(spec.title if spec else state.objective.statement)
        root = f"{self.directory}/{slug}"
        files = {
            "README.md": readme_md(state, semantics, breakdown, metrics, root),
            "01-objective.md": objective_md(state),
            "02-semantics.md": semantics_md(state, semantics),
            "03-architecture.md": architecture_md(state, semantics),
            "04-work-breakdown.md": work_breakdown_md(state, breakdown, issue_refs or {}),
            "05-implementation.md": implementation_md(state),
            "06-qa.md": qa_md(state),
            "07-observability.md": observability_md(state),
            "08-metrics.md": metrics_md(state, metrics, breakdown),
            "09-decisions.md": decisions_md(state, semantics),
            "10-changelog.md": changelog_md(state),
        }
        return DocumentSet(slug=slug, root=root, files=files)

    def write(
        self,
        state: RunState,
        repo_root: str | Path,
        **kwargs: object,
    ) -> list[Path]:
        document_set = self.build(state, **kwargs)  # type: ignore[arg-type]
        written = document_set.write(repo_root)
        self._refresh_index(repo_root, document_set, state)
        return written

    # ── The index ─────────────────────────────────────────────────────────────

    def _refresh_index(self, repo_root: str | Path, docs: DocumentSet, state: RunState) -> None:
        """One line per project, appended in place rather than rewritten.

        Rewriting the index from disk would drop anything a human added, so an
        existing entry is replaced by id and everything else is left alone.
        """
        index = Path(repo_root) / self.directory / "index.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "# Projects",
            "",
            "Every delivery this system has run, newest last.",
            "",
            "| Project | Status | Requested by | Coverage | Run |",
            "|---|---|---|---|---|",
        ]
        verdict = state.qa.verdict.value.upper() if state.qa else "—"
        coverage = f"{state.qa.coverage:.0%}" if state.qa else "—"
        requested = state.objective.submitted_by or "unknown"
        row = (
            f"| [{docs.slug}]({docs.slug}/README.md) | {verdict} | {requested} | "
            f"{coverage} | `{state.id}` |"
        )

        existing = index.read_text().splitlines() if index.is_file() else []
        body = [
            line
            for line in existing
            if line.startswith("|")
            and not line.startswith("| Project")
            and not line.startswith("|---")
            and f"`{state.id}`" not in line
            and f"[{docs.slug}]" not in line
        ]
        index.write_text("\n".join(header + body + [row]) + "\n")
