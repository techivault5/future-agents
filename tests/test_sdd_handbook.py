"""The handbook must stay generated from the code, and must actually build."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from future_agents.sdd import handbook


def test_source_extraction_returns_the_real_code() -> None:
    listing = handbook.source_of("clarify", "IntentClarifier._decide")
    assert listing.startswith("def _decide(")
    assert "ClarificationOutcome.MEETING_REQUIRED" in listing


def test_source_extraction_is_loud_about_a_renamed_symbol() -> None:
    with pytest.raises(LookupError):
        handbook.source_of("clarify", "IntentClarifier.no_such_method")


def test_every_listing_in_every_chapter_resolves() -> None:
    """A renamed symbol should break this test, not silently empty the document."""
    for chapter in handbook.CHAPTERS:
        chapter()  # raises LookupError if any listing target has moved


def test_long_listings_are_clipped_not_overflowed() -> None:
    clipped = handbook.clip("\n".join(f"line {i}" for i in range(200)), max_lines=10)
    assert len(clipped.splitlines()) == 11
    assert "see the source file" in clipped


def test_code_lines_fit_the_page() -> None:
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.platypus import Preformatted

    limit = (handbook.PAGE_W - 2 * handbook.MARGIN) - 14
    for chapter in handbook.CHAPTERS:
        for flowable in chapter():
            items = getattr(flowable, "_content", [flowable])
            for item in items:
                if not isinstance(item, Preformatted):
                    continue
                for line in item.lines:
                    text = line if isinstance(line, str) else "".join(line)
                    width = stringWidth(text, handbook.FONTS.mono, 7.0)
                    assert width <= limit, f"{chapter.__name__}: {text[:60]}"


def test_ascii_fallback_covers_the_diagram_glyphs() -> None:
    original = handbook.FONTS.unicode
    handbook.FONTS.unicode = False
    try:
        rendered = handbook.sanitize("a → b ▼ │ └ ✓ ≥ …")
        assert not any(ord(ch) > 127 for ch in rendered), rendered
    finally:
        handbook.FONTS.unicode = original


def test_stats_reflect_the_live_system() -> None:
    from future_agents.sdd import personas
    from future_agents.sdd.repos import languages

    stats = handbook.handbook_stats()
    assert stats["chapters"] == len(handbook.CHAPTERS)
    assert stats["toolchains"] == len(languages.TOOLCHAINS)
    assert stats["personas"] == len(personas.PERSONAS)
    assert stats["patterns"] >= 15
    assert stats["listings"] >= 30


def test_handbook_builds_a_real_pdf(tmp_path: Path) -> None:
    path = handbook.build_handbook(tmp_path / "handbook.pdf")
    data = path.read_bytes()

    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    assert pages >= 30, f"only {pages} pages — the document lost content"


# ── Diagrams ──────────────────────────────────────────────────────────────────


def test_every_figure_builds_and_fits_the_page() -> None:

    from future_agents.sdd.handbook.figures import FIGURES

    frame = handbook.PAGE_W - 2 * handbook.MARGIN
    for name, build in FIGURES.items():
        figure = build()
        drawing = figure.render()
        assert drawing.width <= frame, f"{name} is wider than the text frame"
        assert drawing.height > 0
        assert figure.nodes, f"{name} has no boxes"


def test_figures_export_as_svg(tmp_path: Path) -> None:
    from future_agents.sdd.handbook.figures import export_all

    written = export_all(tmp_path)
    svgs = [p for p in written if p.suffix == ".svg"]

    assert len(svgs) >= 4
    for path in svgs:
        assert path.read_text().lstrip().startswith("<?xml")


def test_arrows_point_at_real_boxes() -> None:
    """An arrow that ends nowhere is a diagram that lies about the flow."""
    from future_agents.sdd.handbook.figures import FIGURES

    for name, build in FIGURES.items():
        figure = build()
        anchors = {
            (round(x, 2), round(y, 2))
            for node in figure.nodes
            for x, y in (node.anchor(side) for side in ("left", "right", "top", "bottom"))
        }
        for arrow in figure.arrows:
            assert (round(arrow.end[0], 2), round(arrow.end[1], 2)) in anchors, name
            assert (round(arrow.start[0], 2), round(arrow.start[1], 2)) in anchors, name
