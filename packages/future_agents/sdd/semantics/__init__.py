"""The semantic layer — the vocabulary a delivery is reasoned in.

Most deliveries do not fail on syntax. They fail because "refund" meant a
reversal to one person and a credit note to another, and nobody noticed until
the ledger disagreed. This layer sits between the spec and the plan and does
three things:

1. **Resolves terms.** Every noun, verb and constraint in the ask is pinned to a
   canonical concept, with its synonyms folded in and the evidence that named
   it. Repo knowledge is consulted, so the codebase's own words win over the
   ticket's paraphrase.
2. **Names capabilities.** Actor + action + entity, one per requirement:
   "support refunds an order". A requirement that cannot be phrased this way is
   not yet a requirement, and says so.
3. **Shows its work.** `trace` records each hop — what was read, what it
   produced, on what evidence — because a decomposition nobody can audit is a
   decomposition nobody can correct.

Ambiguity is an output, not an error. A term with two live readings becomes a
recorded ambiguity that the clarifier can turn into a question and the architect
carries as a risk, rather than a coin flip made silently at 2am.
"""

from __future__ import annotations

from future_agents.sdd.models import (
    Capability,
    Concept,
    ConceptKind,
    SemanticModel,
)
from future_agents.sdd.semantics.builder import SemanticLayer
from future_agents.sdd.semantics.glossary import (
    AMBIGUOUS_TERMS,
    DOMAIN_HINTS,
    canonicalise,
    singular,
)

__all__ = [
    "AMBIGUOUS_TERMS",
    "DOMAIN_HINTS",
    "Capability",
    "Concept",
    "ConceptKind",
    "SemanticLayer",
    "SemanticModel",
    "canonicalise",
    "singular",
]
