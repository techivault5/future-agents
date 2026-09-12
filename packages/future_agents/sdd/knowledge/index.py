"""Repository index — what exists, where it lives, and what each place is for.

Built from the repository itself: module docstrings, symbol names, directory
shapes and the instruction files a team already wrote. It is deliberately
lexical (TF-IDF over paths, symbols and docs) rather than embedding-based, so
it builds in seconds, runs offline, and gives the same answer twice. An
embedding backend can replace `search()` without touching anything else.
"""

from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from future_agents.sdd.models import RepoMatch
from future_agents.sdd.repos.languages import IGNORED_DIRS, RepoProfile, detect_repo

# A directory holding hundreds of same-shaped files is a data set, not a design.
BULK_THRESHOLD = 60
BULK_SAMPLE = 5
DEFAULT_MAX_FILES = 4000
CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".scala",
    ".ex",
    ".exs",
    ".dart",
    ".sh",
    ".sql",
    ".tf",
    ".r",
}
DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
CONFIG_SUFFIXES = {".yaml", ".yml", ".toml", ".json", ".ini", ".cfg"}

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
    "is",
    "are",
    "be",
    "that",
    "this",
    "it",
    "as",
    "by",
    "from",
    "we",
    "our",
    "def",
    "class",
    "self",
    "return",
    "import",
    "none",
    "true",
    "false",
    "str",
    "int",
    "list",
    "dict",
    "new",
    "add",
    "get",
    "set",
    "use",
    "using",
    "must",
}

# One cheap symbol pattern per non-Python language. Python uses the AST.
SYMBOL_PATTERNS: dict[str, tuple[tuple[str, str], ...]] = {
    "typescript": (
        (r"^\s*export\s+(?:async\s+)?function\s+(\w+)", "function"),
        (r"^\s*export\s+(?:abstract\s+)?class\s+(\w+)", "class"),
        (r"^\s*export\s+(?:interface|type)\s+(\w+)", "type"),
    ),
    "javascript": (
        (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", "function"),
        (r"^\s*(?:export\s+)?class\s+(\w+)", "class"),
    ),
    "go": ((r"^func\s+(?:\([^)]*\)\s*)?(\w+)", "function"), (r"^type\s+(\w+)", "type")),
    "rust": (
        (r"^\s*(?:pub\s+)?fn\s+(\w+)", "function"),
        (r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)", "type"),
    ),
    "java": (
        (r"^\s*(?:public|protected)\s+(?:final\s+)?class\s+(\w+)", "class"),
        (r"^\s*(?:public|protected)\s+\w[\w<>\[\]]*\s+(\w+)\s*\(", "method"),
    ),
    "kotlin": (
        (r"^\s*(?:open\s+|data\s+)?class\s+(\w+)", "class"),
        (r"^\s*fun\s+(\w+)", "function"),
    ),
    "csharp": (
        (r"^\s*(?:public|internal)\s+(?:sealed\s+)?class\s+(\w+)", "class"),
        (r"^\s*(?:public|internal)\s+[\w<>\[\]]+\s+(\w+)\s*\(", "method"),
    ),
    "ruby": ((r"^\s*class\s+(\w+)", "class"), (r"^\s*def\s+(\w+)", "function")),
    "php": (
        (r"^\s*(?:final\s+)?class\s+(\w+)", "class"),
        (r"^\s*(?:public\s+)?function\s+(\w+)", "function"),
    ),
    "swift": (
        (r"^\s*(?:public\s+)?(?:final\s+)?(?:class|struct|enum)\s+(\w+)", "type"),
        (r"^\s*(?:public\s+)?func\s+(\w+)", "function"),
    ),
    "scala": ((r"^\s*(?:case\s+)?class\s+(\w+)", "class"), (r"^\s*def\s+(\w+)", "function")),
    "elixir": ((r"^\s*defmodule\s+([\w.]+)", "module"), (r"^\s*def\s+(\w+)", "function")),
    "dart": (
        (r"^\s*class\s+(\w+)", "class"),
        (r"^\s*\w[\w<>]*\s+(\w+)\s*\(", "function"),
    ),
    "cpp": (
        (r"^\s*class\s+(\w+)", "class"),
        (r"^[\w:<>*&\s]+\s(\w+)\s*\([^;]*\)\s*\{", "function"),
    ),
    "terraform": (
        (r'^\s*resource\s+"([\w-]+)"', "resource"),
        (r'^\s*module\s+"([\w-]+)"', "module"),
    ),
    "sql": ((r"(?i)^\s*create\s+(?:or\s+replace\s+)?(?:table|view)\s+(\w+)", "table"),),
    "shell": ((r"^\s*(\w+)\s*\(\)\s*\{", "function"),),
}

# What a directory is for, decided by name. Used for placement, not decoration.
DIR_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tests", ("test", "tests", "spec", "specs", "__tests__", "testdata")),
    ("docs", ("doc", "docs", "documentation", "adr")),
    ("config", ("config", "configs", "conf", "settings", ".github", "deploy")),
    ("data", ("data", "fixtures", "assets", "seeds", "datasets")),
    ("scripts", ("script", "scripts", "bin", "tools", "cmd")),
    ("generated", ("build", "dist", "target", "out", "generated", "vendor", "node_modules")),
    ("examples", ("example", "examples", "samples", "demo")),
    ("web", ("web", "static", "public", "assets")),
)


class Symbol(BaseModel):
    name: str
    kind: str  # class | function | method | type | module | resource | table
    line: int = 0
    doc: str = ""


class FileNote(BaseModel):
    path: str  # repo-relative, posix
    language: str = ""
    kind: str = "code"  # code | docs | config | data | other
    lines: int = 0
    doc: str = ""  # module docstring / first heading
    symbols: list[Symbol] = Field(default_factory=list)

    @property
    def directory(self) -> str:
        parent = str(Path(self.path).parent)
        return "" if parent == "." else parent


class DirNote(BaseModel):
    path: str
    kind: str = "source"
    file_count: int = 0
    languages: list[str] = Field(default_factory=list)
    purpose: str = ""
    bulk: bool = False  # hundreds of same-shaped files: a data set, not a design


class RepoIndex(BaseModel):
    """A lexical map of a repository, cheap to build and to cache."""

    root: str
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    profile: Optional[RepoProfile] = None
    files: dict[str, FileNote] = Field(default_factory=dict)
    directories: dict[str, DirNote] = Field(default_factory=dict)
    truncated: bool = False

    # ── Build ─────────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        root: str | Path,
        profile: Optional[RepoProfile] = None,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> "RepoIndex":
        root_path = Path(root).resolve()
        index = cls(root=str(root_path), profile=profile or detect_repo(root_path))
        seen = 0

        for directory, paths in _walk(root_path):
            rel_dir = _rel(root_path, directory)
            suffixes = Counter(p.suffix for p in paths)
            bulk = len(paths) >= BULK_THRESHOLD and len(suffixes) <= 2
            chosen = sorted(paths)[:BULK_SAMPLE] if bulk else paths

            for path in chosen:
                if seen >= max_files:
                    index.truncated = True
                    break
                note = _read_file(root_path, path)
                if note is None:
                    continue
                index.files[note.path] = note
                seen += 1

            index.directories[rel_dir] = DirNote(
                path=rel_dir,
                kind=_dir_kind(rel_dir),
                file_count=len(paths),
                languages=sorted({_language(p) for p in paths if _language(p)}),
                purpose=_dir_purpose(root_path, directory),
                bulk=bulk,
            )
            if index.truncated:
                break

        index._reindex()
        return index

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 6,
        kinds: Iterable[str] = (),
        require_name_overlap: int = 0,
    ) -> list[RepoMatch]:
        """TF-IDF over path segments, symbol names and docs.

        `require_name_overlap` demands that many query words appear in the *path
        or symbol name*, not merely in prose. Docs alone match almost anything;
        a name match is what makes "this already exists" believable.
        """
        terms = _tokens(query)
        if not terms:
            return []
        wanted = set(kinds)
        scores: dict[str, float] = defaultdict(float)
        for term in terms:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for path, count in self._postings.get(term, {}).items():
                scores[path] += (1 + math.log(count)) * idf

        term_set = set(terms)
        matches: list[RepoMatch] = []
        for path, score in scores.items():
            note = self.files[path]
            if wanted and note.kind not in wanted:
                continue
            symbol = _best_symbol(note, terms)
            if require_name_overlap and len(term_set & _name_tokens(note)) < require_name_overlap:
                continue
            matches.append(
                RepoMatch(
                    path=path,
                    symbol=symbol.name if symbol else "",
                    kind=symbol.kind if symbol else note.kind,
                    score=round(score / (self._norm.get(path) or 1.0), 4),
                    excerpt=(symbol.doc if symbol and symbol.doc else note.doc)[:200],
                    reason="name and documentation overlap",
                )
            )
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]

    def symbols_named(self, name: str) -> list[RepoMatch]:
        low = name.lower()
        out = [
            RepoMatch(
                path=note.path,
                symbol=symbol.name,
                kind=symbol.kind,
                score=1.0,
                excerpt=symbol.doc[:200],
                reason="exact symbol name",
            )
            for note in self.files.values()
            for symbol in note.symbols
            if symbol.name.lower() == low
        ]
        return out

    # ── Views ─────────────────────────────────────────────────────────────────

    def directories_of_kind(self, kind: str) -> list[DirNote]:
        return sorted(
            (d for d in self.directories.values() if d.kind == kind and not d.bulk),
            key=lambda d: d.file_count,
            reverse=True,
        )

    def source_roots(self) -> list[str]:
        """Top-level directories that actually hold code, busiest first."""
        counts: Counter[str] = Counter()
        for note in self.files.values():
            if note.kind != "code" or "/" not in note.path:
                continue
            head = note.path.split("/", 1)[0]
            if _dir_kind(head) in {"source", "root"}:
                counts[head] += 1
        return [path for path, _ in counts.most_common(3)]

    def stats(self) -> dict[str, object]:
        return {
            "root": self.root,
            "files_indexed": len(self.files),
            "directories": len(self.directories),
            "symbols": sum(len(f.symbols) for f in self.files.values()),
            "languages": sorted({f.language for f in self.files.values() if f.language}),
            "bulk_directories": [d.path for d in self.directories.values() if d.bulk][:10],
            "truncated": self.truncated,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.model_dump(mode="json"), indent=1))
        return target

    @classmethod
    def load(cls, path: str | Path) -> "RepoIndex":
        index = cls.model_validate(json.loads(Path(path).read_text()))
        index._reindex()
        return index

    # ── Internal ──────────────────────────────────────────────────────────────

    def _reindex(self) -> None:
        postings: dict[str, dict[str, int]] = defaultdict(dict)
        norms: dict[str, float] = {}
        for path, note in self.files.items():
            counts = Counter(_tokens(_document(note)))
            if not counts:
                continue
            for term, count in counts.items():
                postings[term][path] = count
            norms[path] = math.sqrt(sum(c * c for c in counts.values())) or 1.0
        total = max(len(self.files), 1)
        object.__setattr__(self, "_postings", postings)
        object.__setattr__(self, "_norm", norms)
        object.__setattr__(
            self,
            "_idf",
            {term: math.log(1 + total / len(paths)) for term, paths in postings.items()},
        )

    model_config = {"extra": "allow"}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _walk(root: Path) -> Iterable[tuple[Path, list[Path]]]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        files: list[Path] = []
        for entry in entries:
            if entry.is_dir():
                if (
                    entry.name in IGNORED_DIRS
                    or entry.name.endswith((".egg-info", ".dist-info"))
                    or (entry.name.startswith(".") and entry.name != ".github")
                ):
                    continue
                stack.append(entry)
            elif entry.is_file() and not entry.name.startswith("."):
                files.append(entry)
        # Empty directories still say what a repo is shaped like (tests/, docs/).
        yield current, files


def _rel(root: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return str(path)
    return "" if str(rel) == "." else rel.as_posix()


def _language(path: Path) -> str:
    from future_agents.sdd.repos.languages import TOOLCHAINS

    for chain in TOOLCHAINS:
        if path.suffix in chain.extensions:
            return chain.language
    return ""


def _file_kind(path: Path) -> str:
    if path.suffix in CODE_SUFFIXES:
        return "code"
    if path.suffix in DOC_SUFFIXES:
        return "docs"
    if path.suffix in CONFIG_SUFFIXES:
        return "config"
    return "other"


def _dir_kind(rel_dir: str) -> str:
    parts = [p.lower() for p in rel_dir.split("/") if p]
    for kind, names in DIR_KINDS:
        if any(part in names for part in parts):
            return kind
    return "source" if parts else "root"


def _dir_purpose(root: Path, directory: Path) -> str:
    for name in ("README.md", "readme.md", "__init__.py"):
        candidate = directory / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(errors="ignore")[:4000]
        except OSError:
            continue
        if name.endswith(".py"):
            # The text is truncated for speed, so it may not parse; the docstring
            # is the first thing in the file either way.
            match = re.match(r'\s*(?:"""|\'\'\')(.+)', text)
            if match:
                return match.group(1).strip()[:160]
        else:
            for line in text.splitlines():
                stripped = line.strip().lstrip("#").strip()
                if stripped and not stripped.startswith(("!", "[")):
                    return stripped[:160]
    return ""


def _read_file(root: Path, path: Path) -> Optional[FileNote]:
    kind = _file_kind(path)
    language = _language(path)
    try:
        if path.stat().st_size > 400_000:
            return None
        text = path.read_text(errors="ignore")
    except OSError:
        return None

    note = FileNote(
        path=_rel(root, path),
        language=language,
        kind=kind,
        lines=text.count("\n") + 1,
    )
    if kind == "docs":
        note.doc = _first_heading(text)
        return note
    if kind != "code":
        return note

    if language == "python":
        note.doc, note.symbols = _python_symbols(text)
    else:
        note.doc = _leading_comment(text)
        note.symbols = _regex_symbols(text, language)
    return note


def _python_symbols(text: str) -> tuple[str, list[Symbol]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "", []
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    symbols: list[Symbol] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append(
                Symbol(name=node.name, kind="class", line=node.lineno, doc=_docline(node))
            )
            symbols.extend(
                Symbol(
                    name=f"{node.name}.{child.name}",
                    kind="method",
                    line=child.lineno,
                    doc=_docline(child),
                )
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not child.name.startswith("_")
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(
                Symbol(name=node.name, kind="function", line=node.lineno, doc=_docline(node))
            )
    return (doc[0][:200] if doc else ""), symbols


def _docline(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    return doc.strip().splitlines()[0][:200] if doc.strip() else ""


def _regex_symbols(text: str, language: str) -> list[Symbol]:
    patterns = SYMBOL_PATTERNS.get(language)
    if not patterns:
        return []
    symbols: list[Symbol] = []
    for number, line in enumerate(text.splitlines()[:2000], start=1):
        for pattern, kind in patterns:
            match = re.match(pattern, line)
            if match:
                symbols.append(Symbol(name=match.group(1), kind=kind, line=number))
                break
    return symbols[:200]


def _leading_comment(text: str) -> str:
    for line in text.splitlines()[:8]:
        stripped = line.strip()
        if stripped.startswith(("//", "#", "--", "/*", "*")):
            cleaned = stripped.lstrip("/#-*").strip()
            if len(cleaned) > 10:
                return cleaned[:200]
    return ""


def _first_heading(text: str) -> str:
    for line in text.splitlines()[:40]:
        if line.startswith("#"):
            return line.lstrip("#").strip()[:200]
    return ""


def _document(note: FileNote) -> str:
    parts = [note.path.replace("/", " ").replace("_", " ").replace("-", " "), note.doc]
    parts.extend(_split_identifier(s.name) + " " + s.doc for s in note.symbols[:60])
    return " ".join(parts)


def _split_identifier(name: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", name.replace("_", " ").replace(".", " "))
    return f"{name} {spaced}"


def _tokens(text: str) -> list[str]:
    return [
        _stem(word) for word in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if word not in _STOP
    ]


def stem(word: str) -> str:
    """Crude, symmetric suffix stripping — applied to index and query alike.

    Linguistic accuracy does not matter here; agreement between the two sides
    does. Without it, "invoices" never finds `invoice_agent.py`.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


#: The memory hub shares this vocabulary so both sides stem identically.
_stem = stem


def _name_tokens(note: FileNote) -> set[str]:
    """Words that appear in the path or in any symbol name — not in prose."""
    words = set(_tokens(note.path.replace("/", " ")))
    for symbol in note.symbols[:60]:
        words.update(_tokens(_split_identifier(symbol.name)))
    return words


def _best_symbol(note: FileNote, terms: list[str]) -> Optional[Symbol]:
    best: Optional[Symbol] = None
    best_score = 0
    term_set = set(terms)
    for symbol in note.symbols:
        score = len(term_set & set(_tokens(_split_identifier(symbol.name) + " " + symbol.doc)))
        if score > best_score:
            best, best_score = symbol, score
    return best
