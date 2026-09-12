"""Conventions — the placement rules a team already wrote down.

`CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` and friends usually already answer
"where does a new X go?" and "what must never happen here?". Parsing them beats
inventing a placement policy: the repository's own words win, and every decision
can name the file and line that produced it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field

INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "docs/architecture.md",
    "docs/ARCHITECTURE.md",
    "README.md",
)

# "| You are adding | It goes in | Also do |" — the table shape teams write.
_WHERE_HEADERS = ("goes in", "location", "where", "put it", "lives in", "destination")
_SUBJECT_HEADERS = ("adding", "you are", "thing", "what", "item", "kind")

_PROHIBITION = re.compile(
    r"(never|do not|don'?t|must not|forbidden|no code|avoid)\s+(?P<rest>.{4,160})",
    re.IGNORECASE,
)
_PATHISH = re.compile(r"`([^`]+)`|(\b[\w.\-/]+/[\w.\-/*]*)")
_STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "in",
    "on",
    "at",
    "with",
    "new",
    "add",
    "adding",
    "you",
    "are",
    "it",
    "goes",
    "into",
    "your",
    "any",
}


class PlacementRule(BaseModel):
    """'A new X goes in Y' — lifted verbatim from the repo's own instructions."""

    subject: str
    destination: str
    note: str = ""
    source: str = ""
    keywords: list[str] = Field(default_factory=list)

    def score(self, text: str) -> float:
        """How strongly a requirement looks like this rule's subject."""
        words = set(_tokens(text))
        if not words or not self.keywords:
            return 0.0
        overlap = words & set(self.keywords)
        return len(overlap) / len(self.keywords)


#: A prohibition on the repository root itself, where paths carry no directory.
ROOT_SENTINEL = "<root>"


class Prohibition(BaseModel):
    """'Never put code at the repo root' — a place a change must not go."""

    text: str
    paths: list[str] = Field(default_factory=list)
    source: str = ""

    def applies_to(self, path: str) -> bool:
        candidate = path.strip("/")
        for pattern in self.paths:
            if pattern == ROOT_SENTINEL:
                if "/" not in candidate:
                    return True
                continue
            cleaned = pattern.strip("/`")
            if not cleaned:
                continue
            if cleaned.endswith("/"):
                segment = cleaned.rstrip("/")
                if candidate.startswith(segment) or f"/{segment}/" in f"/{candidate}/":
                    return True
            if candidate == cleaned or candidate.startswith(f"{cleaned}/"):
                return True
        return False


class Conventions(BaseModel):
    """Everything the repository says about where things go."""

    rules: list[PlacementRule] = Field(default_factory=list)
    prohibitions: list[Prohibition] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @classmethod
    def load(
        cls,
        root: str | Path,
        extra_files: Iterable[str] = (),
        known_dirs: Iterable[str] = (),
    ) -> "Conventions":
        """Read the repo's instruction files. `known_dirs` sharpens path detection."""
        root_path = Path(root)
        conventions = cls()
        roots = {d.split("/", 1)[0] for d in known_dirs if d} | _DEFAULT_ROOTS
        for name in (*INSTRUCTION_FILES, *extra_files):
            path = root_path / name
            if not path.is_file():
                continue
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            conventions.sources.append(name)
            conventions.rules.extend(_parse_tables(text, name))
            conventions.prohibitions.extend(_parse_prohibitions(text, name, roots))
        return conventions

    def best_rule(self, text: str, minimum: float = 0.25) -> Optional[PlacementRule]:
        scored = [(rule, rule.score(text)) for rule in self.rules]
        scored = [(rule, score) for rule, score in scored if score >= minimum]
        if not scored:
            return None
        return max(scored, key=lambda pair: pair[1])[0]

    def matching_rules(
        self, text: str, limit: int = 3, minimum: float = 0.2
    ) -> list[PlacementRule]:
        scored = [(rule, rule.score(text)) for rule in self.rules]
        scored = [pair for pair in scored if pair[1] >= minimum]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [rule for rule, _ in scored[:limit]]

    def forbids(self, path: str) -> list[Prohibition]:
        return [p for p in self.prohibitions if p.applies_to(path)]


# ── Parsing ───────────────────────────────────────────────────────────────────


def _parse_tables(text: str, source: str) -> list[PlacementRule]:
    """Read markdown tables whose header says 'goes in' / 'where'."""
    rules: list[PlacementRule] = []
    rows: list[list[str]] = []
    header: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            header, rows = [], []
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue  # the separator row
        if not header:
            header = [c.lower() for c in cells]
            continue
        rows.append(cells)

        where_index = _column(header, _WHERE_HEADERS)
        subject_index = _column(header, _SUBJECT_HEADERS)
        if where_index is None or subject_index is None or where_index >= len(cells):
            continue
        subject = _clean(cells[subject_index])
        destination = _first_path(cells[where_index]) or _clean(cells[where_index])
        if not subject or not destination:
            continue
        note = " ".join(
            _clean(cells[i]) for i in range(len(cells)) if i not in {where_index, subject_index}
        )
        rules.append(
            PlacementRule(
                subject=subject,
                destination=destination,
                note=note[:200],
                source=source,
                keywords=_tokens(subject),
            )
        )
    return rules


def _parse_prohibitions(text: str, source: str, roots: set[str]) -> list[Prohibition]:
    out: list[Prohibition] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*# ").strip()
        if len(line) < 8 or line.startswith("|"):
            continue
        if not _PROHIBITION.search(line):
            continue
        paths = _paths(line, roots)
        if _mentions_root(line):
            paths.insert(0, ROOT_SENTINEL)
        if not paths:
            continue
        out.append(Prohibition(text=_clean(line)[:200], paths=paths[:4], source=source))
    return out


def _mentions_root(line: str) -> bool:
    low = line.lower()
    return ("root" in low or "top level" in low or "top-level" in low) and (
        "code" in low or "file" in low or "put" in low
    )


def _column(header: list[str], needles: tuple[str, ...]) -> Optional[int]:
    for index, cell in enumerate(header):
        if any(needle in cell for needle in needles):
            return index
    return None


#: Directory names that make a slash-separated token a real path rather than
#: prose like "pytest/ruff/make" or "bcrypt/argon2".
_DEFAULT_ROOTS = {
    "src",
    "lib",
    "app",
    "apps",
    "packages",
    "tests",
    "test",
    "spec",
    "docs",
    "scripts",
    "data",
    "web",
    "templates",
    "examples",
    "modules",
    "environments",
    "config",
    "configs",
    "internal",
    "cmd",
    "models",
    "dags",
    "notebooks",
    ".github",
    ".venv",
    "node_modules",
    "vendor",
    "build",
    "dist",
    "target",
}
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,6}$")


def _looks_like_path(candidate: str, roots: set[str]) -> bool:
    if not candidate or " " in candidate:
        return False
    if candidate.endswith("/"):
        return True
    if candidate.startswith("."):
        return True
    head = candidate.split("/", 1)[0]
    if head in roots:
        return True
    # A slash-joined phrase is only a path when something in it looks like a file.
    return "/" in candidate and bool(_EXTENSION.search(candidate))


def _paths(line: str, roots: set[str] = _DEFAULT_ROOTS) -> list[str]:
    found: list[str] = []
    for backticked, bare in _PATHISH.findall(line):
        candidate = (backticked or bare).strip()
        if _looks_like_path(candidate, roots) and candidate not in found:
            found.append(candidate)
    return found[:4]


def _first_path(cell: str) -> str:
    paths = _paths(cell)
    return paths[0] if paths else ""


def _clean(cell: str) -> str:
    return re.sub(r"[*`]", "", cell).strip()


def _tokens(text: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-z][a-z0-9]{2,}", _clean(text).lower()) if word not in _STOP
    ]
