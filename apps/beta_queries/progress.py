"""Progress steps — the narration the user sees while a question is answered.

Every string is configuration, not code, and none of it comes from the model.
The model responds at ~900 ms; the first step has to render at ~50 ms, so the
narration is driven by the stage machine and only ever *describes* what the
orchestrator already did.

Steps render in three states — `running`, `done`, `skipped` — and a step that
was skipped says why. "Retrieval — skipped, template hit" is the line that
explains a 70 ms answer, and it is the most convincing thing in the UI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml

    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

DEFAULT_STEPS: list[dict[str, str]] = [
    {
        "id": "entitlements",
        "running": "Checking what you can access…",
        "done": "{n} data sources available",
    },
    {"id": "route", "running": "Looking for the right data source…", "done": "Using {datasource}"},
    {
        "id": "schema",
        "running": "Reading table definitions…",
        "done": "{n} tables, {joins} joins resolved",
    },
    {"id": "filters", "running": "Working out the filters…", "done": "{n} filters applied"},
    {"id": "generate", "running": "Writing the query…", "done": "Query written"},
    {"id": "guard", "running": "Checking the query…", "done": "Passed {n} safety checks"},
    {"id": "execute", "running": "Running it…", "done": "{rows} rows in {ms} ms"},
    {"id": "answer", "running": "Summarising…", "done": "Done"},
]


@dataclass
class Step:
    id: str
    label: str
    state: str = "running"  # running | done | skipped | failed
    detail: str = ""
    ms: int | None = None

    def as_event(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "label": self.label, "state": self.state}
        if self.detail:
            out["detail"] = self.detail
        if self.ms is not None:
            out["ms"] = self.ms
        return out


class StepMachine:
    """Emits one event per state change. Wire `sink` to your SSE channel."""

    def __init__(self, config: list[dict[str, str]] | None = None, sink=None) -> None:
        self.config = {s["id"]: s for s in (config or DEFAULT_STEPS)}
        self.order = [s["id"] for s in (config or DEFAULT_STEPS)]
        self.sink = sink
        self.steps: list[Step] = []
        self._t0: dict[str, float] = {}

    @classmethod
    def from_file(cls, path: str | Path, sink=None) -> "StepMachine":
        if not HAS_YAML:
            raise RuntimeError("PyYAML is required to load step configuration")
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls(config=data.get("steps") or DEFAULT_STEPS, sink=sink)

    def _emit(self, step: Step) -> Step:
        self.sink(step.as_event()) if self.sink else None
        return step

    def start(self, step_id: str, **fmt: Any) -> Step:
        spec = self.config.get(step_id, {})
        label = spec.get("running", step_id).format(**fmt) if fmt else spec.get("running", step_id)
        step = Step(id=step_id, label=label, state="running")
        self.steps.append(step)
        self._t0[step_id] = time.perf_counter()
        return self._emit(step)

    def done(self, step_id: str, **fmt: Any) -> Step:
        spec = self.config.get(step_id, {})
        template = spec.get("done", "")
        try:
            detail = template.format(**fmt) if template else ""
        except (KeyError, IndexError):
            # A missing placeholder must never break the response — the step
            # simply renders without its detail line.
            detail = template
        step = self._find(step_id) or Step(id=step_id, label=spec.get("running", step_id))
        step.state = "done"
        step.detail = detail
        if step_id in self._t0:
            step.ms = int((time.perf_counter() - self._t0[step_id]) * 1000)
        if step not in self.steps:
            self.steps.append(step)
        return self._emit(step)

    def skip(self, step_id: str, why: str) -> Step:
        spec = self.config.get(step_id, {})
        step = self._find(step_id) or Step(id=step_id, label=spec.get("running", step_id))
        step.state = "skipped"
        step.detail = why
        step.ms = 0
        if step not in self.steps:
            self.steps.append(step)
        return self._emit(step)

    def fail(self, step_id: str, why: str) -> Step:
        step = self._find(step_id) or Step(id=step_id, label=step_id)
        step.state = "failed"
        step.detail = why
        if step not in self.steps:
            self.steps.append(step)
        return self._emit(step)

    def _find(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    @property
    def total_ms(self) -> int:
        return sum(s.ms or 0 for s in self.steps)

    def trace(self) -> list[dict[str, Any]]:
        return [s.as_event() for s in self.steps]
