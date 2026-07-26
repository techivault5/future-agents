"""Storage backends — swap freely, the manager only sees this protocol.

    InMemoryBackend  — dict; fastest, ephemeral, zero deps (tests, browser-ish)
    SqliteBackend    — stdlib sqlite3 + FTS5 keyword index; local-first, durable
    GraphBackend     — adjacency wrapper over any backend; Kuzu/Cypher export

Local-first by default: nothing here talks to a cloud service. `GraphBackend`
emits Cypher so a memory graph can be lifted into Kuzu, Neo4j or FalkorDB when
you outgrow the embedded store.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from projects.finance_advisor.memory.types import MemoryRecord, MemoryType


@runtime_checkable
class MemoryBackend(Protocol):
    """Minimal persistence surface a memory store must provide."""

    def put(self, record: MemoryRecord) -> None:
        """Insert or replace a record."""
        ...

    def get(self, record_id: str) -> MemoryRecord | None:
        """Fetch one record by id, or None."""
        ...

    def delete(self, record_id: str) -> bool:
        """Remove a record; True when it existed."""
        ...

    def scan(
        self,
        subject: str | None = None,
        types: Iterable[MemoryType] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        """Return candidate records for ranking, filtered cheaply."""
        ...

    def count(self) -> int:
        """Total records held."""
        ...


class InMemoryBackend:
    """Dict-backed store. Ephemeral, ordered, dependency-free."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    def put(self, record: MemoryRecord) -> None:
        """Insert or replace a record."""
        self._records[record.id] = record

    def get(self, record_id: str) -> MemoryRecord | None:
        """Fetch one record by id, or None."""
        return self._records.get(record_id)

    def delete(self, record_id: str) -> bool:
        """Remove a record; True when it existed."""
        return self._records.pop(record_id, None) is not None

    def scan(
        self,
        subject: str | None = None,
        types: Iterable[MemoryType] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        """Return candidate records for ranking, filtered cheaply."""
        wanted_types = set(types) if types else None
        wanted_tags = set(tags) if tags else None
        out = []
        for rec in self._records.values():
            if subject and rec.subject != subject:
                continue
            if wanted_types and rec.type not in wanted_types:
                continue
            if wanted_tags and not wanted_tags & set(rec.tags):
                continue
            out.append(rec)
        return out

    def count(self) -> int:
        """Total records held."""
        return len(self._records)


class SqliteBackend:
    """Durable local store: one file, stdlib only, FTS5 keyword index.

    Vectors are stored as JSON alongside the row — fine up to tens of
    thousands of memories, which is far past what one person's finances need.
    Point `path` at ":memory:" for an ephemeral database.
    """

    def __init__(self, path: str | Path = "data/memory.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mem_subject_type ON memories(subject, type);
            """
        )
        try:
            self._conn.executescript(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(id UNINDEXED, content);"
            )
            self._fts = True
        except sqlite3.OperationalError:  # FTS5 not compiled in
            self._fts = False
        self._conn.commit()

    def put(self, record: MemoryRecord) -> None:
        """Insert or replace a record (and its FTS row when available)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO memories (id, subject, type, content, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.id,
                record.subject,
                record.type.value,
                record.content,
                record.model_dump_json(),
            ),
        )
        if self._fts:
            self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (record.id,))
            self._conn.execute(
                "INSERT INTO memories_fts (id, content) VALUES (?, ?)",
                (record.id, record.content),
            )
        self._conn.commit()

    def get(self, record_id: str) -> MemoryRecord | None:
        """Fetch one record by id, or None."""
        row = self._conn.execute(
            "SELECT payload FROM memories WHERE id = ?", (record_id,)
        ).fetchone()
        return MemoryRecord.model_validate_json(row["payload"]) if row else None

    def delete(self, record_id: str) -> bool:
        """Remove a record; True when it existed."""
        cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (record_id,))
        if self._fts:
            self._conn.execute("DELETE FROM memories_fts WHERE id = ?", (record_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def scan(
        self,
        subject: str | None = None,
        types: Iterable[MemoryType] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        """Return candidate records for ranking, filtered in SQL where possible."""
        sql = "SELECT payload FROM memories"
        clauses: list[str] = []
        params: list[str] = []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        type_list = [t.value for t in types] if types else []
        if type_list:
            clauses.append(f"type IN ({','.join('?' * len(type_list))})")
            params.extend(type_list)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        rows = self._conn.execute(sql, params).fetchall()
        records = [MemoryRecord.model_validate_json(r["payload"]) for r in rows]
        if tags:
            wanted = set(tags)
            records = [r for r in records if wanted & set(r.tags)]
        return records

    def keyword_search(self, query: str, limit: int = 20) -> list[MemoryRecord]:
        """FTS5 keyword search; falls back to LIKE when FTS5 is unavailable."""
        if self._fts:
            try:
                rows = self._conn.execute(
                    "SELECT m.payload FROM memories_fts f JOIN memories m ON m.id = f.id "
                    "WHERE memories_fts MATCH ? LIMIT ?",
                    (query, limit),
                ).fetchall()
                return [MemoryRecord.model_validate_json(r["payload"]) for r in rows]
            except sqlite3.OperationalError:
                pass  # malformed MATCH expression, fall through to LIKE
        rows = self._conn.execute(
            "SELECT payload FROM memories WHERE content LIKE ? LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [MemoryRecord.model_validate_json(r["payload"]) for r in rows]

    def count(self) -> int:
        """Total records held."""
        return int(self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"])

    def close(self) -> None:
        """Close the underlying sqlite connection."""
        self._conn.close()


class GraphBackend:
    """Entity/relation layer over any backend, with Cypher export.

    Keeps an in-process adjacency index so neighbour queries stay O(1); the
    records themselves live in the wrapped backend, so durability is whatever
    that backend provides.
    """

    def __init__(self, inner: MemoryBackend | None = None) -> None:
        self.inner = inner or InMemoryBackend()
        self._edges: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        for rec in self.inner.scan():
            self._index(rec)

    def _index(self, record: MemoryRecord) -> None:
        for rel in record.relations:
            self._edges[record.id].append((rel.predicate, rel.target, rel.weight))

    def put(self, record: MemoryRecord) -> None:
        """Store the record and index its relations."""
        self.inner.put(record)
        self._edges.pop(record.id, None)
        self._index(record)

    def get(self, record_id: str) -> MemoryRecord | None:
        """Fetch one record by id, or None."""
        return self.inner.get(record_id)

    def delete(self, record_id: str) -> bool:
        """Remove a record and its outgoing edges."""
        self._edges.pop(record_id, None)
        return self.inner.delete(record_id)

    def scan(
        self,
        subject: str | None = None,
        types: Iterable[MemoryType] | None = None,
        tags: Iterable[str] | None = None,
    ) -> list[MemoryRecord]:
        """Delegate candidate selection to the wrapped backend."""
        return self.inner.scan(subject=subject, types=types, tags=tags)

    def count(self) -> int:
        """Total records held."""
        return self.inner.count()

    def neighbors(self, record_id: str, predicate: str | None = None) -> list[tuple[str, str]]:
        """(predicate, target) pairs leaving `record_id`, optionally filtered."""
        edges = self._edges.get(record_id, [])
        return [(p, t) for p, t, _ in edges if predicate is None or p == predicate]

    def to_cypher(self) -> list[str]:
        """Serialise the graph as Cypher for Kuzu / Neo4j / FalkorDB import."""
        statements: list[str] = []
        for rec in self.inner.scan():
            props = json.dumps({"id": rec.id, "content": rec.redacted().content})
            statements.append(f"MERGE (m:Memory {{id: '{rec.id}'}}) SET m += {props};")
            for predicate, target, weight in self._edges.get(rec.id, []):
                safe = predicate.upper().replace(" ", "_").replace("-", "_")
                statements.append(
                    f"MERGE (e:Entity {{name: '{target}'}}) "
                    f"WITH e MATCH (m:Memory {{id: '{rec.id}'}}) "
                    f"MERGE (m)-[:{safe} {{weight: {weight}}}]->(e);"
                )
        return statements
