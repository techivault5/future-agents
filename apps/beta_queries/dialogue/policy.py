"""Dialogue policy — scenario in, one response shape out.

This is the module that makes the chat surface feel like one system rather
than thirty ad-hoc behaviours. Every scenario the classifier can produce, plus
the ones raised downstream (no rows, ambiguous, blocked, timed out), maps to
exactly one `mode`, and the wording lives in
`data/config/beta_queries_dialogue.yaml` where a product owner can edit it.

Two properties are worth defending:

    consistency   the same scenario produces the same shape every time, with
                  no model call. A chat surface that answers "hi" differently
                  each time reads as unreliable even when its SQL is perfect.
    no dead ends  every refusal, deflection and repair carries suggestions, so
                  a turn that cannot be answered still ends somewhere useful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

# Modes that reach the model. Everything else is answered from state, the
# catalog, or this file — which is why most turns cost nothing.
MODEL_MODES = frozenset({"run_query"})
# Modes that execute SQL (the standing plan, or a new one).
EXECUTING_MODES = frozenset({"run_query", "reuse_plan"})

DEFAULT_SCENARIOS: dict[str, dict[str, Any]] = {
    "new_topic": {"mode": "run_query"},
    "refine": {"mode": "run_query"},
    "pivot": {"mode": "reuse_plan"},
    "drill": {"mode": "run_query"},
    "rollup": {"mode": "reuse_plan"},
    "compare": {"mode": "run_query"},
    "rank": {"mode": "run_query"},
    "trend": {"mode": "run_query"},
    "repeat": {"mode": "reuse_plan"},
    "amend": {"mode": "reuse_plan"},
    "undo": {"mode": "reuse_plan"},
    "meta": {"mode": "answer_from_state", "text": "{explanation}"},
    "explain_sql": {"mode": "answer_from_state", "text": "Here is the query."},
    "schema_question": {"mode": "catalog_answer", "text": "{summary}"},
    "capability": {"mode": "catalog_answer", "text": "I answer questions about your data."},
    "help": {"mode": "catalog_answer", "text": "Ask the way you would ask a colleague."},
    "reset": {"mode": "command", "text": "Cleared."},
    "export": {"mode": "command", "text": "Exporting {rows} rows."},
    "feedback": {"mode": "command", "text": "Noted, thank you."},
    "greeting": {"mode": "acknowledge", "text": "Hello. Ask me about your data."},
    "thanks": {"mode": "acknowledge", "text": "Any time."},
    "identity": {"mode": "deflect", "text": "I'm a text-to-SQL assistant."},
    "chitchat": {"mode": "deflect", "text": "That's outside my data."},
    "unsupported_write": {"mode": "refuse", "text": "I can only read."},
    "injection": {"mode": "refuse", "text": "Ask me about your data.", "log": "security"},
    "abuse": {"mode": "deflect", "text": "Tell me what you expected and I'll show my working."},
    "unresolved_reference": {"mode": "repair", "text": "Nothing to apply that to yet."},
    "multi_intent": {"mode": "clarify", "text": "That's {n} questions. Which first?"},
    "language_other": {"mode": "repair", "text": "I can only read English questions."},
    "empty": {"mode": "repair", "text": "Nothing came through."},
    "gibberish": {"mode": "repair", "text": "I couldn't read that as a question."},
    "out_of_scope": {"mode": "refuse", "text": "Nothing you can access covers that."},
    "ambiguous_source": {"mode": "clarify", "text": "Which source do you mean?"},
    "ambiguous_intent": {"mode": "clarify", "text": "I couldn't turn that into a query."},
    "view_not_queryable": {
        "mode": "answer_from_state",
        "text": "{view} is a view; I query the tables underneath it.",
    },
    "ambiguous_column": {"mode": "clarify", "text": "Which column do you mean?"},
    "no_rows": {"mode": "answer_from_state", "text": "No rows matched."},
    "policy_blocked": {"mode": "refuse", "text": "You can see aggregates, not rows."},
    "execution_error": {"mode": "repair", "text": "The query failed: {error}."},
    "timeout": {"mode": "repair", "text": "That took too long and was cancelled."},
}

DEFAULT_SUGGESTIONS = [
    "How many active employees are there?",
    "Show headcount by department",
    "What data can I ask about?",
]


@dataclass
class Reply:
    scenario: str
    mode: str
    text: str = ""
    suggestions: list[str] = field(default_factory=list)
    # Set when the turn should be recorded somewhere other than the normal log.
    log: str | None = None

    @property
    def calls_model(self) -> bool:
        return self.mode in MODEL_MODES

    @property
    def executes_sql(self) -> bool:
        return self.mode in EXECUTING_MODES

    def as_event(self) -> dict[str, Any]:
        out: dict[str, Any] = {"scenario": self.scenario, "mode": self.mode}
        if self.text:
            out["text"] = self.text
        if self.suggestions:
            out["suggestions"] = self.suggestions
        return out


class DialoguePolicy:
    """The scenario → response map, loaded once and then pure."""

    def __init__(
        self,
        scenarios: dict[str, dict[str, Any]] | None = None,
        fallback_suggestions: list[str] | None = None,
        suggestions_max: int = 3,
    ) -> None:
        self.scenarios = dict(DEFAULT_SCENARIOS)
        if scenarios:
            for name, spec in scenarios.items():
                self.scenarios[name] = {**self.scenarios.get(name, {}), **spec}
        self.fallback_suggestions = fallback_suggestions or list(DEFAULT_SUGGESTIONS)
        self.suggestions_max = suggestions_max

    @classmethod
    def from_file(cls, path: str | Path) -> DialoguePolicy:
        if not HAS_YAML:  # pragma: no cover - yaml is a declared dependency
            return cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        defaults = data.get("defaults") or {}
        return cls(
            scenarios=data.get("scenarios") or {},
            fallback_suggestions=defaults.get("fallback_suggestions"),
            suggestions_max=int(defaults.get("suggestions_max", 3)),
        )

    # ── the one entry point ─────────────────────────────────────────────────

    def respond(self, scenario: str, facts: dict[str, Any] | None = None) -> Reply:
        """Map a scenario to its reply. Unknown scenarios repair, never crash."""
        spec = self.scenarios.get(scenario)
        if spec is None:
            return Reply(
                scenario=scenario,
                mode="repair",
                text="I'm not sure what to do with that. Try asking about your data.",
                suggestions=self.fallback_suggestions[: self.suggestions_max],
            )

        data = dict(facts or {})
        text = self._render(spec.get("text", ""), data)
        reply = Reply(
            scenario=scenario,
            mode=spec.get("mode", "repair"),
            text=text,
            log=spec.get("log"),
        )
        if reply.mode not in EXECUTING_MODES or not text:
            reply.suggestions = self._suggestions(spec, data)
        return reply

    # ── internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _render(template: str, facts: dict[str, Any]) -> str:
        """Fill placeholders; drop any sentence whose placeholder is missing.

        Dropping the sentence rather than the turn is deliberate: a missing
        fact should cost the user a detail, never an answer.
        """
        if not template:
            return ""
        text = " ".join(template.split())
        sentences = [s.strip() for s in _split_sentences(text) if s.strip()]
        kept: list[str] = []
        for sentence in sentences:
            try:
                kept.append(sentence.format(**facts))
            except (KeyError, IndexError):
                continue
        return " ".join(kept)

    def _suggestions(self, spec: dict[str, Any], facts: dict[str, Any]) -> list[str]:
        source = spec.get("suggestions_from")
        items: list[str] = []
        if source and isinstance(facts.get(source), list):
            items = [str(x) for x in facts[source]]
        elif spec.get("suggestions"):
            items = [str(x) for x in spec["suggestions"]]
        if not items and spec.get("mode") in ("refuse", "deflect", "repair", "acknowledge"):
            items = list(self.fallback_suggestions)
        return items[: self.suggestions_max]


def _split_sentences(text: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in ".!?" and len(buf.strip()) > 1:
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return out
