"""Fonts for the handbook — one registration, shared by the prose and the diagrams.

The core PDF fonts are Latin-1 only: an arrow or a box-drawing character comes
out as the wrong glyph. Prefer a Unicode TTF; when none is installed, fall back
to the core fonts and transliterate to ASCII instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# The core PDF fonts are Latin-1 only: an arrow or a box-drawing character comes
# out as the wrong glyph. Prefer a Unicode TTF; when none is installed, fall back
# to the core fonts and transliterate the diagrams to ASCII instead.
_FONT_DIRS = (
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
    Path("/usr/share/fonts/TTF"),
    Path("/Library/Fonts"),
    Path("C:/Windows/Fonts"),
)
_FONT_FILES = {
    "sans": ("DejaVuSans.ttf",),
    "sans_bold": ("DejaVuSans-Bold.ttf",),
    "sans_italic": ("DejaVuSans-Oblique.ttf", "DejaVuSans-Italic.ttf"),
    "mono": ("DejaVuSansMono.ttf",),
}
_COVERAGE_PROBE = "→▼►─│┌└✓✗≥…"

_ASCII_MAP = {
    "→": "->",
    "←": "<-",
    "▼": "v",
    "▲": "^",
    "►": ">",
    "◄": "<",
    "─": "-",
    "│": "|",
    "┌": "+",
    "┐": "+",
    "└": "+",
    "┘": "+",
    "├": "+",
    "┤": "+",
    "┬": "+",
    "┴": "+",
    "┼": "+",
    "✓": "[ok]",
    "✗": "[x]",
    "≥": ">=",
    "≤": "<=",
    "≠": "!=",
    "…": "...",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "•": "*",
}


class _Fonts:
    """Which font family the document is actually able to draw with."""

    def __init__(self) -> None:
        self.sans = "Helvetica"
        self.sans_bold = "Helvetica-Bold"
        self.sans_italic = "Helvetica-Oblique"
        self.mono = "Courier"
        self.unicode = False
        self._register()

    def _find(self, names: tuple[str, ...]) -> Optional[Path]:
        for directory in _FONT_DIRS:
            for name in names:
                candidate = directory / name
                if candidate.is_file():
                    return candidate
        return None

    def _register(self) -> None:
        found = {key: self._find(names) for key, names in _FONT_FILES.items()}
        if not found["sans"] or not found["mono"]:
            return
        try:
            pdfmetrics.registerFont(TTFont("SDDSans", str(found["sans"])))
            pdfmetrics.registerFont(
                TTFont("SDDSans-Bold", str(found["sans_bold"] or found["sans"]))
            )
            pdfmetrics.registerFont(
                TTFont("SDDSans-Italic", str(found["sans_italic"] or found["sans"]))
            )
            pdfmetrics.registerFont(TTFont("SDDMono", str(found["mono"])))
        except Exception:  # a broken font file must not fail the build
            return
        face = pdfmetrics.getFont("SDDMono").face
        if any(ord(ch) not in face.charToGlyph for ch in _COVERAGE_PROBE):
            return  # registered but incomplete — transliterate instead
        pdfmetrics.registerFontFamily(
            "SDDSans", normal="SDDSans", bold="SDDSans-Bold", italic="SDDSans-Italic"
        )
        self.sans, self.sans_bold = "SDDSans", "SDDSans-Bold"
        self.sans_italic, self.mono = "SDDSans-Italic", "SDDMono"
        self.unicode = True


FONTS = _Fonts()


def sanitize(value: str) -> str:
    """Transliterate glyphs the active font cannot draw."""
    if FONTS.unicode:
        return value
    for source, replacement in _ASCII_MAP.items():
        value = value.replace(source, replacement)
    return value
