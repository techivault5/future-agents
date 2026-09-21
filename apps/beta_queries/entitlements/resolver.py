"""Entitlements — what this person may read, resolved once per request.

Three properties make this the first stage rather than the last:

    the model never sees an unentitled table. Filtering at retrieval means
    there is no vocabulary for it to leak, no name to hallucinate, and no
    prompt-injection path to a table the asker cannot read.

    deny beats allow, always. A person in two groups, one granting and one
    denying, is denied. Any other resolution order is a way to widen access by
    joining a group.

    the snapshot is short-lived. Sixty seconds, because a revoked grant that
    lingers for an hour is an incident, and one that lingers for a minute is a
    cache.

This is one of three layers. Retrieval filtering here, AST authorisation in the
guard, and the execution principal at the database — because the first two are
code we wrote and the third is the one the database enforces.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_SNAPSHOT_TTL = 60


@dataclass(frozen=True)
class RowFilter:
    """A predicate the compiler injects whether or not the model asked for it."""

    table: str  # fqn
    expression: str  # rendered against the table's alias
    rationale: str = ""
    # Row-level security is not the user's to dismiss, so it is never editable
    # and never rendered as a removable chip.
    source: str = "policy"


@dataclass(frozen=True)
class Mask:
    """A column this person may aggregate but not read."""

    table: str
    column: str
    strategy: str = "redact"  # redact | hash | partial | aggregate_only
    rationale: str = ""

    @property
    def aggregate_only(self) -> bool:
        return self.strategy == "aggregate_only"


@dataclass
class GrantSet:
    """Everything the request is allowed to touch, and under what conditions."""

    principal: str
    datasources: set[str] = field(default_factory=set)
    tables: set[str] = field(default_factory=set)  # fqns, already deny-filtered
    denied_columns: set[str] = field(default_factory=set)  # "fqn.column"
    row_filters: list[RowFilter] = field(default_factory=list)
    masks: list[Mask] = field(default_factory=list)
    resolved_at: float = 0.0

    def may_read(self, fqn: str) -> bool:
        return fqn in self.tables

    def filters_for(self, fqn: str) -> list[RowFilter]:
        return [f for f in self.row_filters if f.table == fqn]

    def masks_for(self, fqn: str) -> list[Mask]:
        return [m for m in self.masks if m.table == fqn]

    def entitled_relnames(self, datasource: str) -> set[str]:
        """The guard and the identifier catalog key on `schema.table`, not fqn."""
        prefix = f"{datasource}."
        return {t[len(prefix) :] for t in self.tables if t.startswith(prefix)}

    def hash(self) -> str:
        """`ent_hash` — two people with identical access share cached plans.

        Includes the filters and masks, not just the table list: two people who
        can see the same tables through different row filters must never share
        a cached plan, or one of them sees the other's rows.
        """
        payload = {
            "tables": sorted(self.tables),
            "denied": sorted(self.denied_columns),
            "filters": sorted(f"{f.table}|{f.expression}" for f in self.row_filters),
            "masks": sorted(f"{m.table}.{m.column}|{m.strategy}" for m in self.masks),
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


class EntitlementResolver(Protocol):
    def resolve(self, principal: str) -> GrantSet: ...


class InMemoryEntitlements:
    """The reference implementation, and what the tests and demo run against.

    Where entitlements really live — Entra groups, an RBAC table, SQL Server
    roles — is still an open question, so everything downstream is built
    against this and the real resolver swaps in behind the same Protocol.
    """

    def __init__(
        self,
        grants: dict[str, Iterable[str]] | None = None,
        denies: dict[str, Iterable[str]] | None = None,
        row_filters: dict[str, Sequence[RowFilter]] | None = None,
        masks: dict[str, Sequence[Mask]] | None = None,
        denied_columns: dict[str, Iterable[str]] | None = None,
    ) -> None:
        self.grants = {k: set(v) for k, v in (grants or {}).items()}
        self.denies = {k: set(v) for k, v in (denies or {}).items()}
        self.row_filters = {k: list(v) for k, v in (row_filters or {}).items()}
        self.masks = {k: list(v) for k, v in (masks or {}).items()}
        self.denied_columns = {k: set(v) for k, v in (denied_columns or {}).items()}

    def resolve(self, principal: str) -> GrantSet:
        allowed = set(self.grants.get(principal, set()))
        # Deny beats allow. Applied last so no ordering of grants can widen it.
        allowed -= self.denies.get(principal, set())
        return GrantSet(
            principal=principal,
            datasources={t.split(".", 1)[0] for t in allowed},
            tables=allowed,
            denied_columns=set(self.denied_columns.get(principal, set())),
            row_filters=list(self.row_filters.get(principal, [])),
            masks=list(self.masks.get(principal, [])),
        )


# The grant closure as a traversal: a person's access is a path, which is why
# it belongs in the graph next to the catalog rather than in application code.
GRANT_CLOSURE = """
MATCH (u:User {id: $principal})-[:MEMBER_OF*0..4]->(g)-[grant:GRANTED]->(t:Table)
WHERE NOT (u)-[:DENIED]->(t)
RETURN DISTINCT t.fqn AS fqn,
       grant.row_filter    AS row_filter,
       grant.filter_reason AS filter_reason,
       grant.denied_columns AS denied_columns,
       grant.masks          AS masks
"""


class GraphEntitlements:
    """Resolve the grant closure from Neo4j.

    Takes a `run(cypher, params) -> rows` callable for the same reasons the
    crawler and the graph do: no driver import here, and every statement is
    testable against a fake.
    """

    def __init__(self, run: Callable[[str, dict[str, Any]], Sequence[Any]]) -> None:
        self.run = run

    def resolve(self, principal: str) -> GrantSet:
        grants = GrantSet(principal=principal)
        for row in self.run(GRANT_CLOSURE, {"principal": principal}):
            data = row if isinstance(row, dict) else dict(row)
            fqn = data["fqn"]
            grants.tables.add(fqn)
            grants.datasources.add(fqn.split(".", 1)[0])
            if data.get("row_filter"):
                grants.row_filters.append(
                    RowFilter(
                        table=fqn,
                        expression=data["row_filter"],
                        rationale=data.get("filter_reason") or "",
                    )
                )
            for column in data.get("denied_columns") or []:
                grants.denied_columns.add(f"{fqn}.{column}")
            for mask in data.get("masks") or []:
                grants.masks.append(
                    Mask(
                        table=fqn,
                        column=mask.get("column", ""),
                        strategy=mask.get("strategy", "redact"),
                        rationale=mask.get("rationale", ""),
                    )
                )
        return grants


class CachedEntitlements:
    """A 60-second snapshot in front of whatever the real resolver is.

    Entitlement resolution is on the critical path of every question, and a
    grant closure traversal is 10–40 ms. The TTL is short on purpose: this is
    a cache, not a copy, and a revoked grant must stop working in seconds.
    """

    def __init__(
        self,
        inner: EntitlementResolver,
        kv: Any,
        ttl_seconds: int = DEFAULT_SNAPSHOT_TTL,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.inner = inner
        self.kv = kv
        self.ttl = ttl_seconds
        import time

        self.clock = clock or time.time

    def resolve(self, principal: str) -> GrantSet:
        key = "bq:ent:" + hashlib.sha256(principal.strip().lower().encode()).hexdigest()[:32]
        raw = self.kv.get(key)
        if raw:
            try:
                return _from_json(json.loads(raw))
            except (ValueError, TypeError, KeyError):
                # A corrupt snapshot must never widen access — drop it and
                # resolve properly rather than guessing at what it meant.
                self.kv.delete(key)

        grants = self.inner.resolve(principal)
        grants.resolved_at = self.clock()
        self.kv.set(key, json.dumps(_to_json(grants)), ex=self.ttl)
        return grants

    def invalidate(self, principal: str) -> None:
        """Called when a grant changes — revocation should not wait for a TTL."""
        key = "bq:ent:" + hashlib.sha256(principal.strip().lower().encode()).hexdigest()[:32]
        self.kv.delete(key)


def _to_json(grants: GrantSet) -> dict[str, Any]:
    return {
        "principal": grants.principal,
        "datasources": sorted(grants.datasources),
        "tables": sorted(grants.tables),
        "denied_columns": sorted(grants.denied_columns),
        "row_filters": [
            {"table": f.table, "expression": f.expression, "rationale": f.rationale}
            for f in grants.row_filters
        ],
        "masks": [
            {"table": m.table, "column": m.column, "strategy": m.strategy, "rationale": m.rationale}
            for m in grants.masks
        ],
        "resolved_at": grants.resolved_at,
    }


def _from_json(data: dict[str, Any]) -> GrantSet:
    return GrantSet(
        principal=data["principal"],
        datasources=set(data.get("datasources", [])),
        tables=set(data.get("tables", [])),
        denied_columns=set(data.get("denied_columns", [])),
        row_filters=[RowFilter(**f) for f in data.get("row_filters", [])],
        masks=[Mask(**m) for m in data.get("masks", [])],
        resolved_at=data.get("resolved_at", 0.0),
    )
