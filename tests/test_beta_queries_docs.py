"""A script printed in a document must be the script that ships.

`SETUP.md` and `QA-AGENT.md` both print a runnable script in full, so they can
be shared on their own. A printed copy that has drifted from the real file is
worse than no copy: it looks authoritative and it does not work. These tests
are the only thing keeping the two in step.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The bundle renames these to the root, so look in both layouts — otherwise
# the guard silently skips exactly where a drifted copy would do most harm:
# on someone else's machine.
PAIRS = [
    (("docs/beta-queries-setup.md", "SETUP.md"), "scripts/beta_queries_bootstrap.py"),
    (("docs/beta-queries-qa-agent.md", "QA-AGENT.md"), "scripts/beta_queries_qa.py"),
]


def _find(candidates: tuple[str, ...]) -> Path | None:
    return next((ROOT / c for c in candidates if (ROOT / c).exists()), None)


def _first_python_block(markdown: str) -> str:
    blocks = re.findall(r"```python\n(.*?)```", markdown, re.S)
    assert blocks, "no python block in the document"
    return blocks[0]


@pytest.mark.parametrize(("docs", "script"), PAIRS)
def test_the_printed_script_is_the_shipped_script(docs: tuple[str, ...], script: str) -> None:
    doc_path, script_path = _find(docs), ROOT / script
    if doc_path is None or not script_path.exists():
        pytest.skip(f"{docs[0]} or {script} not present in this copy")
    doc = doc_path.name

    printed = _first_python_block(doc_path.read_text()).rstrip("\n")
    shipped = script_path.read_text().rstrip("\n")
    assert printed == shipped, (
        f"{doc} prints a copy of {script} that has drifted. "
        f"Regenerate the document rather than editing the block by hand."
    )
