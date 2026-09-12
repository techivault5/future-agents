#!/usr/bin/env python3
"""Generate the spec-driven delivery handbook (PDF).

    python scripts/generate_handbook.py
    python scripts/generate_handbook.py --output /tmp/handbook.pdf

Tables and code listings are read from the live modules and source files, so
regenerating after a change keeps the document correct by construction.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages"))

from future_agents.sdd.handbook import build_handbook, handbook_stats  # noqa: E402
from future_agents.sdd.handbook.figures import export_all  # noqa: E402

DEFAULT_OUTPUT = REPO_ROOT / "docs" / "spec-driven-delivery-handbook.pdf"
DEFAULT_DIAGRAMS = REPO_ROOT / "docs" / "diagrams"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--diagrams",
        nargs="?",
        const=str(DEFAULT_DIAGRAMS),
        help="also export every figure as SVG (and PNG where a raster backend exists)",
    )
    args = parser.parse_args(argv)

    path = build_handbook(args.output)
    stats = handbook_stats()
    size_kb = path.stat().st_size // 1024
    print(f"wrote {path} ({size_kb} KB)")
    print(
        f"  {stats['chapters']} chapters · {stats['patterns']} patterns · "
        f"{stats['toolchains']} toolchains · {stats['personas']} personas · "
        f"{stats['listings']} code listings"
    )
    if args.diagrams:
        written = export_all(args.diagrams)
        print(f"  {len(written)} diagram files → {args.diagrams}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
