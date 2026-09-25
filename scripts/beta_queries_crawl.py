#!/usr/bin/env python3
"""Crawl the Beta Queries datasources declared in the sources config.

    python scripts/beta_queries_crawl.py --config data/config/beta_queries_sources.yaml
    python scripts/beta_queries_crawl.py --source hrdb --no-profile --dry-run

Writes one JSON catalog per datasource under --out (default: .bq-catalog/).
Drivers are imported lazily and only for the dialects actually crawled, so this
runs with nothing installed when --dry-run is passed.

Credentials come from the environment variable named by each source's
`dsn_env`. Nothing here reads, writes or prints a credential.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / p) for p in ("apps", "packages")]

import yaml  # noqa: E402
from beta_queries.catalog import crawler  # noqa: E402
from beta_queries.sql.connect import connect  # noqa: E402


def _encode(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(type(obj).__name__)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crawl Beta Queries datasources.")
    ap.add_argument("--config", default="data/config/beta_queries_sources.yaml")
    ap.add_argument("--source", action="append", help="crawl only these ids")
    ap.add_argument("--out", default=".bq-catalog")
    ap.add_argument("--no-profile", action="store_true", help="skip value sampling")
    ap.add_argument(
        "--dry-run", action="store_true", help="print the plan and the SQL, connect to nothing"
    )
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    defaults = cfg.get("defaults", {})
    sources = [s for s in cfg["sources"] if not args.source or s["id"] in args.source]
    if not sources:
        print("no sources selected", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0

    for src in sources:
        dsn_env = src["dsn_env"]
        dsn = os.environ.get(dsn_env)
        if args.dry_run:
            state = "set" if dsn else f"MISSING ({dsn_env})"
            print(f"{src['id']:<12} {src['dialect']:<11} dsn: {state}")
            continue
        if not dsn:
            print(f"{src['id']}: {dsn_env} is not set — skipped", file=sys.stderr)
            failures += 1
            continue

        options = crawler.ProfileOptions(
            max_distinct=defaults.get("max_distinct", 500),
            sample_limit=defaults.get("sample_limit", 25),
            max_value_len=defaults.get("max_value_len", 64),
        )
        connection = connect(src["dialect"], dsn)
        try:
            result = crawler.crawl(
                src["id"],
                src["dialect"],
                crawler.dbapi_runner(connection),
                description=(src.get("description") or "").strip(),
                profile=not args.no_profile and defaults.get("profile_values", True),
                options=options,
                synonyms=src.get("synonyms") or {},
                subject_areas=src.get("subject_areas") or [],
            )
        finally:
            connection.close()

        (out / f"{src['id']}.catalog.json").write_text(
            json.dumps(dataclasses.asdict(result.datasource), default=_encode, indent=2)
        )
        (out / f"{src['id']}.profile.json").write_text(
            json.dumps(dataclasses.asdict(result.profile), default=_encode, indent=2)
        )
        print(result.summary)
        for err in result.errors:
            print(f"  ! {err}", file=sys.stderr)
        failures += bool(result.errors)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
