"""Architecture as mermaid — diagrams that live in the repo and stay true.

Mermaid because it is text: it diffs in review, renders in GitHub without a
plugin, and is regenerated from the plan on every run, so the picture cannot
drift from the code the way an exported PNG always does.

Three views, because one diagram cannot answer three questions:

* **structure** — what the change adds, where it lives, what it talks to.
* **traceability** — requirement → capability → component → file → signal, which
  is the chain an auditor walks.
* **method** — the steps this delivery actually went through, with the gates
  that could have stopped it.
"""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.models import (
    ConceptKind,
    ObservabilityPlan,
    Plan,
    SemanticModel,
    Spec,
)


def structure_diagram(
    plan: Optional[Plan],
    semantics: Optional[SemanticModel] = None,
    observability: Optional[ObservabilityPlan] = None,
) -> str:
    """What gets built, where it goes, and what it depends on."""
    if plan is None or not plan.components:
        return "```mermaid\nflowchart LR\n  none[No plan drawn yet]\n```"

    lines = ["```mermaid", "flowchart LR"]
    lines.append("  subgraph change[This change]")
    for component in plan.components:
        node = _id(component.name)
        where = component.target_path or "path not decided"
        lines.append(f'    {node}["{_esc(component.name)}<br/><small>{_esc(where)}</small>"]')
    lines.append("  end")

    systems = [c for c in semantics.concepts if c.kind is ConceptKind.SYSTEM] if semantics else []
    if systems:
        lines.append("  subgraph external[External systems]")
        for concept in systems:
            lines.append(f'    {_id(concept.canonical)}[("{_esc(concept.canonical)}")]')
        lines.append("  end")
        for component in plan.components:
            for concept in systems:
                lines.append(f"  {_id(component.name)} --> {_id(concept.canonical)}")

    for component in plan.components:
        for dependency in component.depends_on:
            lines.append(f"  {_id(component.name)} --> {_id(dependency)}")

    if observability is not None and observability.slos:
        lines.append("  subgraph watch[Watched by]")
        for slo in observability.slos[:6]:
            lines.append(f'    {_id(slo.id)}["{slo.id} {_esc(slo.kind)}"]')
        lines.append("  end")
        for component in plan.components:
            for slo in observability.slos[:6]:
                lines.append(f"  {_id(component.name)} -.-> {_id(slo.id)}")

    lines.append("```")
    return "\n".join(lines)


def traceability_diagram(
    spec: Spec,
    plan: Optional[Plan],
    semantics: Optional[SemanticModel] = None,
    observability: Optional[ObservabilityPlan] = None,
) -> str:
    """Requirement → capability → component → file → objective, per requirement."""
    lines = ["```mermaid", "flowchart TD"]
    for requirement in spec.requirements[:8]:
        req = _id(requirement.id)
        label = _esc(_short(requirement.statement))
        lines.append(f'  {req}["{requirement.id}<br/><small>{label}</small>"]')

        capability = semantics.capability_for(requirement.id) if semantics else None
        if capability is not None:
            cap = _id(capability.id)
            lines.append(f'  {cap}(["{capability.id} {_esc(capability.statement)}"])')
            lines.append(f"  {req} --> {cap}")
            head = cap
        else:
            head = req

        placement = plan.placement_for(requirement.id) if plan else None
        if placement is not None and placement.target_path:
            path = _id(placement.target_path)
            lines.append(f'  {path}["{_esc(placement.target_path)}"]')
            lines.append(f"  {head} --> {path}")
            head = path

        for criterion in requirement.acceptance_criteria[:2]:
            node = _id(criterion.id)
            lines.append(f'  {node}{{"{criterion.id}"}}')
            lines.append(f"  {head} --> {node}")

        slo = observability.slo_for(requirement.id) if observability else None
        if slo is not None:
            node = _id(slo.id)
            lines.append(f'  {node}[/"{slo.id} {_esc(slo.kind)}"/]')
            lines.append(f"  {head} -.-> {node}")
    lines.append("```")
    return "\n".join(lines)


def method_diagram(stages: list[str], gates: Optional[list[str]] = None) -> str:
    """The steps this delivery went through, and what could have stopped it."""
    lines = ["```mermaid", "flowchart LR"]
    previous: Optional[str] = None
    for stage in stages:
        node = _id(stage)
        lines.append(f'  {node}["{_esc(stage)}"]')
        if previous:
            lines.append(f"  {previous} --> {node}")
        previous = node
    for gate in gates or []:
        node = _id(f"gate {gate}")
        lines.append(f'  {node}{{"{_esc(gate)}"}}')
        lines.append(f"  {node} -.->|blocks| {_id(stages[0]) if stages else node}")
    lines.append("```")
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _id(text: str) -> str:
    """A mermaid-safe node id. Stable, so diffs stay readable across runs."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "node")).strip("_").lower()
    return f"n_{slug}" or "n_node"


def _esc(text: str) -> str:
    """Quotes and pipes break mermaid labels; nothing else needs escaping."""
    return re.sub(r"\s+", " ", (text or "")).replace('"', "'").replace("|", "/")


def _short(text: str, limit: int = 60) -> str:
    flat = re.sub(r"\s+", " ", (text or "").strip())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
