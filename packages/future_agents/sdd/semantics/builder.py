"""Spec → semantic model: concepts, capabilities, and the trace that explains both.

The pipeline is deterministic here for the same reason every other stage is: a
vocabulary that changes between runs is not a vocabulary. An engine may later
enrich a definition; it never decides what a concept *is*.
"""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.knowledge import RepoKnowledge
from future_agents.sdd.models import (
    Capability,
    Concept,
    ConceptKind,
    SemanticModel,
    Spec,
)
from future_agents.sdd.semantics.glossary import (
    ACTION_VERBS,
    ACTOR_WORDS,
    AMBIGUOUS_TERMS,
    canonicalise,
    content_words,
    domain_of,
    is_modifier,
    singular,
)

#: Constraint language: a bound on the work rather than a thing being built.
_CONSTRAINT = re.compile(
    r"\b(within|under|no more than|at most|nightly|daily|hourly|weekly|gdpr|pci|hipaa|soc ?2|"
    r"encrypted|audit|retention|sla|slo|compliance|approval)\b",
    re.IGNORECASE,
)

_MEASURE = re.compile(
    r"\b(rate|count|total|percentage|percent|latency|duration|throughput|volume|score|ratio)\b",
    re.IGNORECASE,
)

_SYSTEM = re.compile(
    r"\b(snowflake|postgres|mysql|kafka|s3|redis|stripe|salesforce|jira|slack|github|bigquery|"
    r"dynamodb|sqs|sns|airflow|dbt|kubernetes|datadog|prometheus)\b",
    re.IGNORECASE,
)


class SemanticLayer:
    """Builds the shared vocabulary, and records how it got there."""

    def __init__(self, knowledge: Optional[RepoKnowledge] = None) -> None:
        # The repository's own words outrank the ticket's paraphrase: code that
        # already says `credit_note` settles what the team means by it.
        self.knowledge = knowledge

    def build(self, spec: Spec) -> SemanticModel:
        blob = " ".join(
            [spec.title, spec.summary, *(r.statement for r in spec.requirements)]
        ).strip()
        model = SemanticModel(spec_id=spec.id, domain=domain_of(blob))
        model.trace.append(
            f"read {len(spec.requirements)} requirement(s) from {spec.id}; "
            f"domain reads as '{model.domain}'"
        )

        counter = _Counter()
        self._extract_concepts(spec, model, counter)
        self._fold_repo_vocabulary(model)
        self._detect_ambiguity(spec, model)
        self._name_capabilities(spec, model, counter)
        self._build_relations(model)

        model.glossary = {c.canonical: c.definition for c in model.concepts if c.definition}
        model.trace.append(
            f"resolved {len(model.concepts)} concept(s) into {len(model.capabilities)} "
            f"capability(ies); {len(model.ambiguities)} term(s) still ambiguous"
        )
        return model

    # ── Concepts ──────────────────────────────────────────────────────────────

    def _extract_concepts(self, spec: Spec, model: SemanticModel, counter: "_Counter") -> None:
        """One concept per distinct term, with every requirement that used it."""
        seen: dict[str, Concept] = {}
        for requirement in spec.requirements:
            text = " ".join(
                [requirement.statement, *(ac.render() for ac in requirement.acceptance_criteria)]
            )
            for word in content_words(text):
                canonical = canonicalise(word)
                if not canonical or len(canonical) < 3 or is_modifier(word):
                    continue
                kind = self._kind_of(word, text)
                concept = seen.get(canonical)
                if concept is None:
                    concept = Concept(
                        id=counter.concept(),
                        term=word,
                        canonical=canonical,
                        kind=kind,
                        evidence=[requirement.id],
                        requirement_ids=[requirement.id],
                        confidence=0.5,
                    )
                    seen[canonical] = concept
                    model.concepts.append(concept)
                    continue
                if requirement.id not in concept.requirement_ids:
                    concept.requirement_ids.append(requirement.id)
                    concept.evidence.append(requirement.id)
                if word.lower() != concept.term.lower() and word.lower() not in concept.synonyms:
                    concept.synonyms.append(word.lower())
                # A term used in several requirements is load-bearing, not noise.
                concept.confidence = min(0.95, concept.confidence + 0.15)

        # Terms that appeared once, in one requirement, are usually incidental
        # prose. They stay, but they stay honest about how thin the evidence is.
        for concept in model.concepts:
            if len(concept.requirement_ids) == 1 and not concept.synonyms:
                concept.confidence = min(concept.confidence, 0.5)
        model.trace.append(
            f"extracted {len(model.concepts)} term(s); "
            f"{sum(1 for c in model.concepts if len(c.requirement_ids) > 1)} recur across "
            "requirements and carry more weight"
        )

    @staticmethod
    def _kind_of(word: str, context: str) -> ConceptKind:
        low = word.lower()
        if _SYSTEM.fullmatch(low) or _SYSTEM.search(low):
            return ConceptKind.SYSTEM
        if low in ACTOR_WORDS:
            return ConceptKind.ACTOR
        if singular(low) in ACTION_VERBS or low in ACTION_VERBS:
            return ConceptKind.ACTION
        if _MEASURE.fullmatch(low):
            return ConceptKind.MEASURE
        if _CONSTRAINT.fullmatch(low):
            return ConceptKind.CONSTRAINT
        return ConceptKind.ENTITY

    def _fold_repo_vocabulary(self, model: SemanticModel) -> None:
        """Let the codebase define its own words where it already has.

        A concept the repository can point at is grounded; one it cannot is a
        proposal. Saying which is which is more useful than pretending both are
        equally solid.
        """
        if self.knowledge is None:
            return
        grounded = 0
        for concept in model.concepts:
            if concept.kind not in (ConceptKind.ENTITY, ConceptKind.SYSTEM):
                continue
            try:
                context = self.knowledge.context(concept.canonical)
            except Exception:  # noqa: BLE001 - retrieval must never fail a build
                continue
            if not context.matches:
                continue
            best = context.matches[0]
            concept.confidence = min(0.95, concept.confidence + 0.2)
            concept.definition = concept.definition or (
                f"already present in this repository as {best.render()}"
            )
            concept.evidence.append(best.path)
            grounded += 1
        if grounded:
            model.trace.append(
                f"grounded {grounded} concept(s) in existing code — the repository's "
                "own naming wins over the ticket's paraphrase"
            )

    def _detect_ambiguity(self, spec: Spec, model: SemanticModel) -> None:
        """A word with two live readings, and nothing in the spec settling it."""
        settled_blob = " ".join(
            [
                spec.summary,
                *(ac.render() for r in spec.requirements for ac in r.acceptance_criteria),
                *spec.context_notes,
                *(a.statement for a in spec.assumptions),
            ]
        ).lower()
        for concept in model.concepts:
            readings = AMBIGUOUS_TERMS.get(concept.canonical)
            if not readings:
                continue
            # A criterion that names one reading has already made the choice.
            decided = [r for r in readings if _mentions_reading(settled_blob, r)]
            if len(decided) == 1:
                concept.definition = concept.definition or decided[0]
                concept.confidence = min(0.95, concept.confidence + 0.1)
                continue
            concept.ambiguous = True
            concept.readings = list(readings)
            concept.confidence = min(concept.confidence, 0.4)
            model.ambiguities.append(
                f"'{concept.canonical}' could mean {readings[0]} or {readings[1]} — "
                f"used by {', '.join(concept.requirement_ids[:3])}"
            )
        if model.ambiguities:
            model.trace.append(
                f"{len(model.ambiguities)} term(s) carry more than one reading and were "
                "recorded rather than guessed"
            )

    # ── Capabilities ──────────────────────────────────────────────────────────

    def _name_capabilities(self, spec: Spec, model: SemanticModel, counter: "_Counter") -> None:
        """Actor + action + entity, one per requirement — or an honest gap."""
        for requirement in spec.requirements:
            actor = self._pick(model, requirement, ConceptKind.ACTOR)
            action = self._pick(model, requirement, ConceptKind.ACTION)
            entity = self._pick(model, requirement, ConceptKind.ENTITY)
            if action is None and entity is None:
                model.ambiguities.append(
                    f"{requirement.id} names neither an action nor a thing — it cannot be "
                    "phrased as a capability yet"
                )
                continue
            actor_name = actor.canonical if actor else "the system"
            action_name = action.canonical if action else "supports"
            entity_name = entity.canonical if entity else "the change"
            capability = Capability(
                id=counter.capability(),
                statement=f"{actor_name} {action_name} {entity_name}".strip(),
                actor=actor_name,
                action=action_name,
                entity=entity_name,
                concept_ids=[c.id for c in (actor, action, entity) if c is not None],
                requirement_ids=[requirement.id],
                outcome=_outcome_of(requirement.statement),
            )
            model.capabilities.append(capability)
        model.trace.append(
            f"named {len(model.capabilities)} capability(ies) as actor + action + entity, "
            "so one requirement cannot silently become four unrelated tickets"
        )

    @staticmethod
    def _pick(model: SemanticModel, requirement, kind: ConceptKind) -> Optional[Concept]:
        """The concept this requirement is actually about, not the loudest one.

        Ranking by confidence alone lets a term that recurs elsewhere hijack a
        requirement it barely touches — "refund" winning the capability for a
        reconciliation requirement. The requirement's own sentence decides
        first, in the order the words appear; its criteria are the fallback.
        """
        candidates = {
            c.canonical: c
            for c in model.concepts
            if kind is c.kind and requirement.id in c.requirement_ids
        }
        if not candidates:
            return None
        for source in (
            requirement.statement,
            " ".join(ac.render() for ac in requirement.acceptance_criteria),
        ):
            for word in content_words(source):
                concept = candidates.get(canonicalise(word))
                if concept is not None:
                    return concept
        return max(candidates.values(), key=lambda c: c.confidence)

    def _build_relations(self, model: SemanticModel) -> None:
        """Which entities the actions touch — the smallest useful graph."""
        for capability in model.capabilities:
            if capability.action and capability.entity:
                relation = f"{capability.action} acts-on {capability.entity}"
                if relation not in model.relations:
                    model.relations.append(relation)
            if capability.actor and capability.entity:
                relation = f"{capability.actor} owns-outcome-of {capability.entity}"
                if relation not in model.relations:
                    model.relations.append(relation)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mentions_reading(blob: str, reading: str) -> bool:
    """Does the spec already contain the distinguishing words of one reading?

    The bar is two words, not one: "payment" appearing anywhere would otherwise
    settle "refund" as a payment reversal, which is exactly the coin flip this
    is here to prevent.
    """
    words = [w for w in content_words(reading) if len(w) > 3]
    if not words:
        return False
    hits = sum(1 for word in words if word in blob)
    return hits >= (2 if len(words) >= 3 else 1)


def _outcome_of(statement: str) -> str:
    match = re.search(r"\bso that\b(.+)$", statement, re.IGNORECASE)
    return match.group(1).strip().rstrip(".") if match else ""


class _Counter:
    def __init__(self) -> None:
        self._concepts = 0
        self._capabilities = 0

    def concept(self) -> str:
        self._concepts += 1
        return f"C-{self._concepts:03d}"

    def capability(self) -> str:
        self._capabilities += 1
        return f"CAP-{self._capabilities:03d}"
