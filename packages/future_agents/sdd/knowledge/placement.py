"""Placement — where a requirement's code, tests and docs go, and where they must not.

Four sources of evidence, in the order they are trusted:

1. the repository's own written rules ("a new agent type goes in …"),
2. code that already does something similar — extend it rather than duplicate it,
3. the language toolchain's conventional layout,
4. the domain word in the requirement itself.

Every decision names the evidence that produced it, carries the forbidden zones
it had to avoid, and offers the alternatives it rejected with their trade-offs —
because "where does this go?" usually has more than one defensible answer.
"""

from __future__ import annotations

import re
from typing import Optional

from future_agents.sdd.knowledge.conventions import Conventions, PlacementRule
from future_agents.sdd.knowledge.index import RepoIndex
from future_agents.sdd.models import (
    ForbiddenZone,
    PlacementDecision,
    PlacementOption,
    RepoMatch,
    Requirement,
)
from future_agents.sdd.repos.languages import GENERIC, Toolchain

# Places a change never belongs, whatever the repository says.
ALWAYS_FORBIDDEN: tuple[tuple[str, str], ...] = (
    ("node_modules", "vendored dependencies are not edited"),
    ("vendor", "vendored dependencies are not edited"),
    ("dist", "build output is generated, not written"),
    ("build", "build output is generated, not written"),
    ("target", "build output is generated, not written"),
    (".venv", "a virtual environment is not source"),
    ("__pycache__", "bytecode is generated"),
    (".git", "version control internals"),
)

_DOMAIN_WORDS = re.compile(r"[a-z][a-z0-9]{3,}")
_GENERIC_WORDS = {
    "should",
    "must",
    "will",
    "system",
    "user",
    "users",
    "data",
    "make",
    "need",
    "needs",
    "want",
    "able",
    "when",
    "then",
    "given",
    "with",
    "from",
    "that",
    "this",
    "have",
    "into",
    "such",
    "each",
    "also",
    "team",
    "customer",
    "customers",
    "report",
    "value",
    "state",
    "thing",
    "work",
    "using",
}


class PlacementAdvisor:
    """Answers 'where does this go?' with evidence, alternatives and fences."""

    def __init__(
        self,
        index: RepoIndex,
        conventions: Optional[Conventions] = None,
        toolchain: Optional[Toolchain] = None,
    ) -> None:
        self.index = index
        self.conventions = conventions or Conventions()
        self.toolchain = toolchain or (index.profile.toolchain() if index.profile else GENERIC)

    # ── Public API ────────────────────────────────────────────────────────────

    def advise(self, requirement: Requirement | str, requirement_id: str = "") -> PlacementDecision:
        text = requirement.statement if isinstance(requirement, Requirement) else str(requirement)
        req_id = requirement_id or (requirement.id if isinstance(requirement, Requirement) else "")

        reuse = self._reuse_candidates(text)
        options = self._options(text, reuse)
        chosen = (
            options[0]
            if options
            else PlacementOption(
                path=self._default_dir(),
                approach="new-module",
                rationale="toolchain default layout",
            )
        )

        decision = PlacementDecision(
            requirement_id=req_id,
            target_path=chosen.path,
            test_path=self._test_path(chosen.path, text),
            docs_path=self._docs_path(),
            approach=chosen.approach,
            rationale=chosen.rationale,
            confidence=round(min(1.0, chosen.score), 3),
            alternatives=options[1:4],
            reuse=reuse[:3],
            conventions=[
                f"{rule.subject} → {rule.destination} ({rule.source})"
                for rule in self.conventions.matching_rules(text)
            ],
        )
        decision.forbidden = self.forbidden_zones(decision.target_path)
        return decision

    def forbidden_zones(self, candidate: str = "") -> list[ForbiddenZone]:
        """Where this change must not land, and the rule that says so."""
        zones = [
            ForbiddenZone(path=path, reason=reason, source="built-in")
            for path, reason in ALWAYS_FORBIDDEN
            if path in self.index.directories
            or path in {d.split("/")[0] for d in self.index.directories}
        ]
        zones.extend(
            ForbiddenZone(path=", ".join(p.paths), reason=p.text, source=p.source)
            for p in self.conventions.prohibitions
        )
        for note in self.index.directories.values():
            if note.kind == "generated" and not any(z.path == note.path for z in zones):
                zones.append(
                    ForbiddenZone(
                        path=note.path, reason="generated output, not source", source="repo scan"
                    )
                )
        zones.extend(self._bulk_zones())
        if candidate:
            violated = self.conventions.forbids(candidate)
            for prohibition in violated:
                zones.insert(
                    0,
                    ForbiddenZone(
                        path=candidate,
                        reason=f"chosen path violates: {prohibition.text}",
                        source=prohibition.source,
                    ),
                )
        return _dedupe_zones(zones)[:8]

    def _bulk_zones(self) -> list[ForbiddenZone]:
        """One zone per data tree, not one per directory — fifty lines help nobody."""
        groups: dict[str, tuple[int, int]] = {}
        for note in self.index.directories.values():
            if not note.bulk:
                continue
            root = "/".join(note.path.split("/")[:2]) or note.path
            count, dirs = groups.get(root, (0, 0))
            groups[root] = (count + note.file_count, dirs + 1)
        return [
            ForbiddenZone(
                path=f"{root}/",
                reason=f"bulk data ({files} files across {dirs} directories) — code goes elsewhere",
                source="repo scan",
            )
            for root, (files, dirs) in sorted(groups.items(), key=lambda kv: -kv[1][0])[:2]
        ]

    # ── Evidence ──────────────────────────────────────────────────────────────

    def _reuse_candidates(self, text: str) -> list[RepoMatch]:
        """Existing code worth reading before writing. One name match minimum."""
        matches = self.index.search(text, limit=6, kinds=("code",), require_name_overlap=1)
        return [m for m in matches if m.score > 0.1]

    def _options(self, text: str, reuse: list[RepoMatch]) -> list[PlacementOption]:
        options: list[PlacementOption] = []

        rule = self.conventions.best_rule(text)
        if rule is not None:
            options.append(
                PlacementOption(
                    path=_resolve(rule, text, self._suffix()),
                    approach="new-module",
                    rationale=f"the repo's own rule: '{rule.subject}' → {rule.destination}"
                    f" ({rule.source})",
                    tradeoff="none — this is the documented convention",
                    score=0.9,
                )
            )

        if reuse:
            # Extending a package's __init__/index file is almost never right:
            # prefer the nearest real module.
            best = next((m for m in reuse if not _is_index(m.path)), reuse[0])
            directory = _parent(best.path)
            options.append(
                PlacementOption(
                    path=best.path if _is_module(best.path) else directory,
                    approach="extend",
                    rationale=f"{best.path} already covers this area"
                    + (f" ({best.symbol})" if best.symbol else ""),
                    tradeoff="grows an existing file; check it stays cohesive",
                    score=min(0.85, 0.45 + best.score),
                )
            )
            if directory:
                options.append(
                    PlacementOption(
                        path=f"{directory}/{_slug(text)}{self._suffix()}",
                        approach="new-module",
                        rationale=f"a sibling of {best.path}, which is the closest existing work",
                        tradeoff="one more file to discover; keeps the existing one small",
                        score=min(0.8, 0.4 + best.score),
                    )
                )

        default_dir = self._default_dir()
        options.append(
            PlacementOption(
                path=f"{default_dir}/{_slug(text)}{self._suffix()}" if default_dir else _slug(text),
                approach="new-module",
                rationale=f"{self.toolchain.display_name} layout: source lives in {default_dir}",
                tradeoff="no existing code to reuse; verify nothing similar exists first",
                score=0.5,
            )
        )
        if default_dir and "/" in default_dir:
            root = default_dir.split("/", 1)[0]
            options.append(
                PlacementOption(
                    path=f"{root}/{_slug(text)}",
                    approach="new-package",
                    rationale="a separate package when this is a bounded concern of its own",
                    tradeoff="more structure than a small change deserves",
                    score=0.3,
                )
            )

        options = [o for o in options if o.path]
        for option in options:
            if self.conventions.forbids(option.path):
                option.score *= 0.2
                option.tradeoff = f"{option.tradeoff}; conflicts with a written rule".strip("; ")
        options.sort(key=lambda o: o.score, reverse=True)
        return _dedupe_options(options)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _default_dir(self) -> str:
        roots = self.index.source_roots()
        if roots:
            return roots[0]
        for entry in self.toolchain.layout:
            if entry.kind == "dir" and entry.purpose == "source":
                return entry.path
        return "src"

    def _test_path(self, target: str, text: str) -> str:
        test_dirs = self.index.directories_of_kind("tests")
        stem = _slug(text)
        if test_dirs:
            base = test_dirs[0].path
        else:
            base = next(
                (e.path for e in self.toolchain.layout if e.purpose == "test suite"), "tests"
            )
        glob = self.toolchain.test_glob or "tests/test_*.py"
        name = glob.rsplit("/", 1)[-1]
        if "*" in name:
            filename = name.replace("*", stem)
        else:
            filename = f"test_{stem}{self._suffix()}"
        return f"{base}/{filename}"

    def _docs_path(self) -> str:
        docs = self.index.directories_of_kind("docs")
        return f"{docs[0].path}/" if docs else "docs/"

    def _suffix(self) -> str:
        return self.toolchain.extensions[0] if self.toolchain.extensions else ".txt"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _resolve(rule: PlacementRule, text: str, suffix: str) -> str:
    """Fill a rule's `<placeholder>`, and name the file when it names a directory."""
    destination = re.sub(r"<[^>]+>", _slug(text), rule.destination.strip("`"))
    if destination.endswith("/") or not _is_module(destination):
        return f"{destination.rstrip('/')}/{_slug(text)}{suffix}"
    return destination


def _slug(text: str) -> str:
    words = [w for w in _DOMAIN_WORDS.findall(text.lower()) if w not in _GENERIC_WORDS]
    return "_".join(words[:3]) or "change"


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _is_module(path: str) -> bool:
    return "." in path.rsplit("/", 1)[-1]


def _is_index(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith(("__init__.", "index.", "mod.")) or name in {"lib.rs", "main.go"}


def _dedupe_options(options: list[PlacementOption]) -> list[PlacementOption]:
    seen: set[str] = set()
    out: list[PlacementOption] = []
    for option in options:
        if option.path in seen:
            continue
        seen.add(option.path)
        out.append(option)
    return out


def _dedupe_zones(zones: list[ForbiddenZone]) -> list[ForbiddenZone]:
    seen: set[tuple[str, str]] = set()
    out: list[ForbiddenZone] = []
    for zone in zones:
        key = (zone.path, zone.reason[:40])
        if key in seen:
            continue
        seen.add(key)
        out.append(zone)
    return out
