"""FinanceMemorySDK — the single object an integration needs.

    from finance_advisor.memory import FinanceMemorySDK

    sdk = FinanceMemorySDK()                       # in-memory + hashing embedder
    sdk = FinanceMemorySDK(store="sqlite")         # durable local file
    sdk = FinanceMemorySDK(store="graph")          # entity/relation memory

    sdk.remember("take_home=180000", tags=["profile"], sensitive=True)
    sdk.recall("how much do I earn")
    sdk.skill("loans").advise(principal=3_500_000, annual_rate_pct=8.6, months=240)
    sdk.runtimes()                                 # local-inference matrix
    sdk.capabilities()                             # what this machine can run

The JavaScript SDK (`sdk/js/finance-memory.mjs`) mirrors this surface method for
method, so the same integration code shape works in a browser page or a VS Code
extension, and memories move between them via `export()` / `import_records()`.
"""

from __future__ import annotations

from pathlib import Path

from finance_advisor.memory.backends import (
    GraphBackend,
    InMemoryBackend,
    MemoryBackend,
    SqliteBackend,
)
from finance_advisor.memory.embeddings import Embedder, HashingEmbedder
from finance_advisor.memory.manager import MemoryManager
from finance_advisor.memory.runtimes import (
    Capabilities,
    detect_available,
    matrix_as_dicts,
)
from finance_advisor.memory.skills import SKILLS, skill_catalog
from finance_advisor.memory.types import MemoryType

STORES = ("memory", "sqlite", "graph")


def build_backend(store: str = "memory", path: str | Path | None = None) -> MemoryBackend:
    """Construct a backend by name: memory | sqlite | graph."""
    if store == "memory":
        return InMemoryBackend()
    if store == "sqlite":
        return SqliteBackend(path or "data/memory.db")
    if store == "graph":
        inner = SqliteBackend(path) if path else InMemoryBackend()
        return GraphBackend(inner)
    raise ValueError(f"unknown store {store!r}; expected one of {STORES}")


class FinanceMemorySDK:
    """Memory + finance skills + local-runtime introspection in one facade."""

    def __init__(
        self,
        store: str = "memory",
        path: str | Path | None = None,
        embedder: Embedder | None = None,
        subject: str = "user",
    ) -> None:
        self.memory = MemoryManager(
            backend=build_backend(store, path),
            embedder=embedder or HashingEmbedder(),
            subject=subject,
        )
        self._skills: dict[str, object] = {}

    # ── memory ───────────────────────────────────────────────────────────

    def remember(
        self,
        content: str,
        type: str | MemoryType = MemoryType.SEMANTIC,
        tags: list[str] | None = None,
        importance: float = 0.5,
        sensitive: bool = False,
    ) -> dict:
        """Write a memory; `type` accepts the enum or its string name."""
        record = self.memory.remember(
            content,
            type=MemoryType(type) if isinstance(type, str) else type,
            tags=tags,
            importance=importance,
            sensitive=sensitive,
        )
        return record.redacted().model_dump(mode="json", exclude={"embedding"})

    def recall(self, query: str, limit: int = 5, type: str | None = None) -> list[dict]:
        """Ranked recall; returns redacted records with their score components."""
        types = [MemoryType(type)] if type else None
        return [
            {
                "content": hit.record.redacted().content,
                "type": hit.record.type.value,
                "tags": hit.record.tags,
                "score": hit.score,
                "similarity": hit.similarity,
                "keyword": hit.keyword,
                "recency": hit.recency,
            }
            for hit in self.memory.recall(query, types=types, limit=limit)
        ]

    def context(self, query: str, limit: int = 5) -> str:
        """Prompt-ready, redacted memory block for the given query."""
        return self.memory.context_block(query, limit=limit)

    def profile(self) -> dict[str, str]:
        """Durable profile facts learned so far."""
        return self.memory.profile()

    def consolidate(self, min_occurrences: int = 3) -> int:
        """Promote recurring episodes into semantic facts; returns count created."""
        return len(self.memory.consolidate(min_occurrences=min_occurrences))

    def forget(self) -> int:
        """Apply TTL and low-value pruning; returns count removed."""
        return self.memory.forget()

    def stats(self) -> dict:
        """Store composition, embedder and backend in use."""
        return self.memory.stats()

    def export(self) -> list[dict]:
        """Portable redacted dump for backup or hand-off to the JS SDK."""
        return self.memory.export()

    def import_records(self, items: list[dict]) -> int:
        """Load records exported by this or the JavaScript SDK."""
        return self.memory.import_records(items)

    # ── skills ───────────────────────────────────────────────────────────

    def skill(self, name: str):
        """Get a memory-bound skill: loans | mutual_funds | crypto | capital_gains | taxes."""
        if name not in SKILLS:
            raise KeyError(f"unknown skill {name!r}; available: {sorted(SKILLS)}")
        if name not in self._skills:
            self._skills[name] = SKILLS[name](self.memory)
        return self._skills[name]

    def advise(self, skill: str, **kwargs: object) -> dict:
        """Run a skill and attach the memory context that informed it."""
        result = self.skill(skill).advise(**kwargs)
        result["memory_context"] = self.context(skill, limit=3)
        return result

    @staticmethod
    def skills() -> list[dict]:
        """Catalog of skills and what each covers."""
        return skill_catalog()

    # ── local runtimes ───────────────────────────────────────────────────

    @staticmethod
    def runtimes() -> list[dict]:
        """The CPU / GPU / NPU / Metal / browser runtime comparison matrix."""
        return matrix_as_dicts()

    @staticmethod
    def capabilities() -> Capabilities:
        """What this machine can actually run, plus a recommended embedder."""
        return detect_available()
