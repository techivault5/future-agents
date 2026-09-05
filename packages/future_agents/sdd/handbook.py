"""The SDD handbook — a full technical PDF generated from the live system.

Tables of languages, personas, constitution rules and configuration are pulled
from the modules themselves, and every code listing is sliced out of the real
source file by symbol name. The document therefore cannot drift from the code:
regenerate it and it is correct again.

    python scripts/generate_handbook.py --output docs/spec-driven-delivery.pdf
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from future_agents.sdd import languages, personas
from future_agents.sdd.config import SpecKitConfig

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[2]

INK = colors.HexColor("#12161c")
MUTED = colors.HexColor("#5b6672")
ACCENT = colors.HexColor("#1f6feb")
RULE = colors.HexColor("#d5dae0")
CODE_BG = colors.HexColor("#f5f7f9")
BAND = colors.HexColor("#eef2f6")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm

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


# ── Source extraction ─────────────────────────────────────────────────────────


def source_of(module: str, symbol: str, dedent: bool = True) -> str:
    """Slice a class or function out of a real source file, by name.

    `module` is relative to the sdd package, e.g. "clarify" or "core/events".
    A listing that cannot be found is loud, not silent — a renamed symbol should
    break the build rather than quietly print nothing.
    """
    path = PACKAGE_ROOT / f"{module}.py"
    if not path.is_file():
        path = REPO_ROOT / "packages" / "future_agents" / f"{module}.py"
    text = path.read_text()
    tree = ast.parse(text)

    target: Optional[ast.AST] = None
    parts = symbol.split(".")
    scope: Any = tree
    for part in parts:
        target = None
        for node in ast.iter_child_nodes(scope):
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == part
            ):
                target = node
                break
        if target is None:
            raise LookupError(f"{module}.py has no symbol {symbol!r}")
        scope = target

    lines = text.splitlines()
    start = min([target.lineno, *(d.lineno for d in getattr(target, "decorator_list", []))]) - 1
    end = target.end_lineno or start + 1
    block = lines[start:end]
    if dedent:
        block = [line[len(block[0]) - len(block[0].lstrip()) :] for line in block]
    return "\n".join(block).rstrip()


def clip(text: str, max_lines: int = 46) -> str:
    """Keep a listing to one page; say so when it is trimmed."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines] + ["    # … (see the source file for the rest)"])


# ── Styles ────────────────────────────────────────────────────────────────────


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    s: dict[str, ParagraphStyle] = {}
    s["title"] = ParagraphStyle(
        "title",
        parent=base["Title"],
        fontName=FONTS.sans_bold,
        fontSize=30,
        leading=35,
        textColor=INK,
        spaceAfter=6,
    )
    s["subtitle"] = ParagraphStyle(
        "subtitle",
        parent=base["Normal"],
        fontName=FONTS.sans,
        fontSize=13,
        leading=18,
        textColor=MUTED,
        alignment=TA_CENTER,
    )
    s["h1"] = ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName=FONTS.sans_bold,
        fontSize=19,
        leading=23,
        textColor=INK,
        spaceBefore=2,
        spaceAfter=10,
    )
    s["h2"] = ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName=FONTS.sans_bold,
        fontSize=13.5,
        leading=17,
        textColor=INK,
        spaceBefore=13,
        spaceAfter=5,
    )
    s["h3"] = ParagraphStyle(
        "h3",
        parent=base["Heading3"],
        fontName=FONTS.sans_bold,
        fontSize=11,
        leading=14,
        textColor=ACCENT,
        spaceBefore=9,
        spaceAfter=3,
    )
    s["body"] = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName=FONTS.sans,
        fontSize=9.6,
        leading=14.2,
        textColor=INK,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    s["bullet"] = ParagraphStyle(
        "bullet",
        parent=s["body"],
        leftIndent=11,
        bulletIndent=2,
        spaceAfter=3,
        alignment=0,
    )
    s["caption"] = ParagraphStyle(
        "caption",
        parent=base["Normal"],
        fontName=FONTS.sans_italic,
        fontSize=8.2,
        leading=11,
        textColor=MUTED,
        spaceAfter=8,
    )
    s["code"] = ParagraphStyle(
        "code",
        parent=base["Code"],
        fontName=FONTS.mono,
        fontSize=7.0,
        leading=8.6,
        textColor=INK,
        backColor=CODE_BG,
        borderPadding=6,
        spaceBefore=3,
        spaceAfter=8,
    )
    s["cell"] = ParagraphStyle(
        "cell",
        parent=base["Normal"],
        fontName=FONTS.sans,
        fontSize=7.8,
        leading=10.2,
        textColor=INK,
    )
    s["cellhead"] = ParagraphStyle(
        "cellhead",
        parent=s["cell"],
        fontName=FONTS.sans_bold,
        textColor=colors.white,
    )
    s["cellcode"] = ParagraphStyle(
        "cellcode",
        parent=s["cell"],
        fontName=FONTS.mono,
        fontSize=7.0,
        leading=9.4,
    )
    s["toc1"] = ParagraphStyle(
        "toc1",
        fontName=FONTS.sans_bold,
        fontSize=10.5,
        leading=17,
        textColor=INK,
    )
    s["toc2"] = ParagraphStyle(
        "toc2",
        fontName=FONTS.sans,
        fontSize=9,
        leading=13,
        leftIndent=14,
        textColor=MUTED,
    )
    return s


STYLES = _styles()


# ── Flowable helpers ──────────────────────────────────────────────────────────


def _markup(value: str) -> str:
    """Prepare inline markup: transliterate, then point Courier at the real mono."""
    return sanitize(value).replace("face='Courier'", f"face='{FONTS.mono}'")


def h1(text: str) -> Paragraph:
    return Paragraph(_markup(text), STYLES["h1"])


def h2(text: str) -> Paragraph:
    return Paragraph(_markup(text), STYLES["h2"])


def h3(text: str) -> Paragraph:
    return Paragraph(_markup(text), STYLES["h3"])


def p(text: str) -> Paragraph:
    return Paragraph(_markup(text), STYLES["body"])


def bullets(items: list[str]) -> list[Paragraph]:
    bullet = "•" if FONTS.unicode else "*"
    return [Paragraph(_markup(item), STYLES["bullet"], bulletText=bullet) for item in items]


def caption(text: str) -> Paragraph:
    return Paragraph(_markup(text), STYLES["caption"])


def code(text: str, language: str = "python") -> list[Any]:
    del language  # single mono style; kept for call-site readability
    return [Preformatted(sanitize(clip(text)), STYLES["code"])]


def listing(module: str, symbol: str, note: str = "") -> list[Any]:
    out: list[Any] = []
    if note:
        out.append(caption(f"{note} — <font face='Courier'>{module}.py :: {symbol}</font>"))
    else:
        out.append(caption(f"<font face='Courier'>{module}.py :: {symbol}</font>"))
    out.extend(code(source_of(module, symbol)))
    return out


def table(
    rows: list[list[str]],
    widths: Optional[list[float]] = None,
    mono_columns: tuple[int, ...] = (),
    header: bool = True,
) -> Table:
    """A table whose cells wrap — plain strings would overflow the page."""
    body: list[list[Any]] = []
    for r, row in enumerate(rows):
        cells: list[Any] = []
        for c, value in enumerate(row):
            if header and r == 0:
                style = STYLES["cellhead"]
            elif c in mono_columns:
                style = STYLES["cellcode"]
            else:
                style = STYLES["cell"]
            cells.append(Paragraph(_markup(str(value)), style))
        body.append(cells)

    available = PAGE_W - 2 * MARGIN
    if widths:
        total = sum(widths)
        col_widths = [available * w / total for w in widths]
    else:
        col_widths = [available / len(rows[0])] * len(rows[0])

    t = Table(body, colWidths=col_widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, RULE),
        ("BOX", (0, 0), (-1, -1), 0.5, RULE),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ]
    t.setStyle(TableStyle(style))
    return t


def callout(title: str, text: str) -> Table:
    inner = [
        [Paragraph(_markup(f"<b>{title}</b><br/>{text}"), STYLES["cell"])],
    ]
    t = Table(inner, colWidths=[PAGE_W - 2 * MARGIN], hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BAND),
                ("BOX", (0, 0), (-1, -1), 0.5, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def flow(text: str) -> Preformatted:
    return Preformatted(sanitize(text), STYLES["code"])


# ── Document template ─────────────────────────────────────────────────────────


class Handbook(BaseDocTemplate):
    """Two templates: a bare cover, then numbered body pages with a rule."""

    def __init__(self, path: str, title: str, **kwargs: Any) -> None:
        super().__init__(path, pagesize=A4, title=title, author="future-agents", **kwargs)
        frame = Frame(
            MARGIN, MARGIN + 8 * mm, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN - 12 * mm, id="body"
        )
        cover = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, id="cover")
        self.addPageTemplates(
            [
                PageTemplate(id="cover", frames=[cover]),
                PageTemplate(id="body", frames=[frame], onPage=self._decorate),
            ]
        )
        self.doc_title = title

    def _decorate(self, canvas: Any, _doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(FONTS.sans, 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, PAGE_H - MARGIN + 3 * mm, self.doc_title)
        canvas.drawRightString(
            PAGE_W - MARGIN, PAGE_H - MARGIN + 3 * mm, "future-agents · spec-driven delivery"
        )
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - MARGIN + 1.5 * mm, PAGE_W - MARGIN, PAGE_H - MARGIN + 1.5 * mm)
        canvas.line(MARGIN, MARGIN + 6 * mm, PAGE_W - MARGIN, MARGIN + 6 * mm)
        canvas.drawCentredString(PAGE_W / 2, MARGIN + 1.5 * mm, str(canvas.getPageNumber()))
        canvas.restoreState()

    def afterFlowable(self, flowable: Any) -> None:
        """Feed headings into the table of contents."""
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        if style == "h1":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))
        elif style == "h2":
            self.notify("TOCEntry", (1, flowable.getPlainText(), self.page))


def _cover(title: str, subtitle: str) -> list[Any]:
    config = SpecKitConfig.load(root=REPO_ROOT)
    facts = [
        ["Project", config.project.name],
        ["Pipeline", "intake → clarify → spec → plan → tasks → work → QA → deliver → harvest"],
        [
            "Default persona",
            f"{personas.DEFAULT_PERSONA.title} ({personas.DEFAULT_PERSONA.years_experience}y)",
        ],
        ["Languages covered", f"{len(languages.TOOLCHAINS)} toolchains, detected not assumed"],
        ["Package", "packages/future_agents/sdd/"],
        ["Generated", date.today().isoformat()],
    ]
    return [
        Spacer(1, 58 * mm),
        Paragraph(_markup(title), STYLES["title"]),
        Spacer(1, 4 * mm),
        Paragraph(_markup(subtitle), STYLES["subtitle"]),
        Spacer(1, 18 * mm),
        table(facts, widths=[1, 3.2], header=False),
        Spacer(1, 14 * mm),
        caption(
            "Every table and code listing in this document is generated from the source it "
            "describes. Regenerate with <font face='Courier'>python scripts/generate_handbook.py</font>."
        ),
        NextPageTemplate("body"),
        PageBreak(),
    ]


def _toc() -> list[Any]:
    toc = TableOfContents()
    toc.levelStyles = [STYLES["toc1"], STYLES["toc2"]]
    return [Paragraph("Contents", STYLES["h1"]), Spacer(1, 4 * mm), toc, PageBreak()]


# ── Chapters ──────────────────────────────────────────────────────────────────


def ch_summary() -> list[Any]:
    return [
        h1("1 · What this system is"),
        p(
            "This is an automated delivery system. A human states an objective — in a meeting, a "
            "ticket, a chat message — and the system turns it into a specification, a technical "
            "plan, a dependency-ordered graph of test-first tasks, executed work, a QA verdict "
            "and a delivery record. When something is genuinely unclear it stops and asks; when "
            "the unknowns are too tangled for a form it asks for a meeting, arrives with an "
            "agenda, and resumes from the notes."
        ),
        p(
            "It is not a chatbot wrapped around a repository. Every stage is deterministic on its "
            "own: it derives its artifact from the upstream one by explicit rules. A language "
            "model, when configured, enriches free-text fields — it is an accelerator, never the "
            "source of truth. That is what makes runs reproducible, testable in CI, and safe to "
            "dry-run before anything touches a repository."
        ),
        h2("1.1 The loop"),
        flow(
            "  human objective\n"
            "        │\n"
            "        ▼\n"
            "  ┌──────────┐   confidence < threshold    ┌───────────────────┐\n"
            "  │ CLARIFY  │ ─────────────────────────►  │ questions / meeting│\n"
            "  └────┬─────┘  ◄───────────────────────── └───────────────────┘\n"
            "       │ ready                                    answers\n"
            "       ▼\n"
            "  SPEC ─► PLAN ─► TASKS ─► WORK ─► QA ─► DELIVER ─► HARVEST\n"
            "   │       ▲                                            │\n"
            "   │       └──────────── past pitfalls ◄────────────────┘\n"
            "   └── REQ ids ────────► criteria ────► tests ────► coverage"
        ),
        caption("The clarification gate and the memory loop are the two feedback edges."),
        h2("1.2 What it does that a plain agent does not"),
        table(
            [
                ["Property", "How it is enforced", "Where"],
                [
                    "Refuses to build on a guess",
                    "Intent is scored; blocking unknowns fail the gate closed",
                    "clarify.py, constitution.py",
                ],
                [
                    "Asks a human at the right level",
                    "Ladder: auto-assume → async questions → meeting → blocked",
                    "clarify.py",
                ],
                [
                    "Every requirement is traceable",
                    "REQ-001 → REQ-001-AC-001 → T-007 → QA check",
                    "models.py, stages.py",
                ],
                [
                    "Tests exist before code",
                    "The implement task depends on its test task; parity is a gate",
                    "stages.py, constitution.py",
                ],
                [
                    "Works in any language",
                    "19 detected toolchains supply install/test/lint/build commands",
                    "languages.py",
                ],
                [
                    "Works at a stated seniority",
                    "Personas tune thresholds, add gates, inject heuristics as risks",
                    "personas.py",
                ],
                [
                    "Spans repositories",
                    "Dependency waves, one merged question set for the whole program",
                    "master.py",
                ],
                [
                    "Learns from failures",
                    "Cases are harvested; failures outrank successes in retrieval",
                    "memory_hub.py",
                ],
                [
                    "Never silently assumes",
                    "Assumption ledger surfaces on the delivery record",
                    "models.py, stages.py",
                ],
            ],
            widths=[1.3, 2.6, 1.4],
            mono_columns=(2,),
        ),
        h2("1.3 Reading this document"),
        p(
            "Chapters 2–6 are the core pipeline. Chapters 7–9 cover seniority, languages and "
            "repository structure. Chapters 10–14 cover execution, QA, memory, routing and "
            "multi-repo orchestration. Chapters 15–17 are operational: configuration, the CLI and "
            "API, and the pattern catalog. Chapters 18–20 cover extension, testing and honest "
            "limits."
        ),
        PageBreak(),
    ]


def ch_philosophy() -> list[Any]:
    return [
        h1("2 · The philosophy: agents as compilers"),
        p(
            "A compiler does not guess what you meant. It parses source into an intermediate "
            "representation, and each pass is bounded by the one before it. Spec-driven delivery "
            "applies that shape to human intent: each artifact constrains the next, and a pass "
            "that cannot proceed fails loudly instead of inventing its input."
        ),
        table(
            [
                ["Artifact", "Answers", "Bounded by", "Fails when"],
                [
                    "Objective",
                    "What does a human want?",
                    "nothing — the only un-derived input",
                    "never; it is raw intent",
                ],
                [
                    "ClarificationResult",
                    "Do we understand it?",
                    "objective + prior answers",
                    "blocking unknowns remain",
                ],
                [
                    "Spec",
                    "What and why?",
                    "the clarification outcome",
                    "a requirement has no acceptance criterion",
                ],
                [
                    "Plan",
                    "How?",
                    "the spec's content hash",
                    "the spec changed underneath it (stale-plan)",
                ],
                [
                    "TaskGraph",
                    "In what order?",
                    "the plan's content hash",
                    "a MUST requirement has no test task",
                ],
                [
                    "WorkResult[]",
                    "What happened?",
                    "the task graph",
                    "a task fails; dependents block",
                ],
                [
                    "QAReport",
                    "Did it work?",
                    "spec criteria + work results",
                    "coverage below the required bar",
                ],
                [
                    "Delivery",
                    "Can we ship it?",
                    "the QA verdict + open questions",
                    "not accepted; assumptions surfaced",
                ],
                [
                    "MemoryCase",
                    "What did we learn?",
                    "the whole run",
                    "never; a failed run is the most valuable case",
                ],
            ],
            widths=[1.15, 1.35, 1.4, 1.5],
        ),
        h2("2.1 Determinism first, model second"),
        p(
            "Every stage produces its artifact without calling a model. Requirements are extracted "
            "with modal-verb, imperative and transcript-attribution rules; components are grouped "
            "by domain keywords; the task graph is generated from the spec's shape. An engine, "
            "when configured, is asked to improve free-text fields only — a summary, an "
            "architecture paragraph. If the engine is missing, slow, or throws, the run continues "
            "and the structure is identical."
        ),
        callout(
            "Why this matters",
            "A pipeline whose structure depends on a model cannot be tested, cannot be replayed, "
            "and cannot be reasoned about when it goes wrong. Here, the model is the accelerator "
            "and the rules are the contract — so the entire system runs offline in CI, and the "
            "same objective produces the same graph every time.",
        ),
        h2("2.2 Content hashes and staleness"),
        p(
            "Each artifact fingerprints its own semantic content, excluding provenance fields "
            "(ids, timestamps, confidence). A plan records the spec hash it was drawn from; if "
            "the spec is revised, the plan is stale and the constitution says so rather than "
            "letting the run continue on a superseded premise."
        ),
        *listing("models", "Hashable", "Fingerprinting excludes provenance, not content"),
        *listing("constitution", "Constitution.check_plan", "The stale-plan gate, among others"),
        PageBreak(),
    ]


def ch_architecture() -> list[Any]:
    return [
        h1("3 · Architecture"),
        h2("3.1 Module map"),
        table(
            [
                ["Module", "Responsibility", "Key types"],
                [
                    "models.py",
                    "The IR artifacts and the run state",
                    "Objective, Spec, Plan, TaskGraph, RunState",
                ],
                [
                    "clarify.py",
                    "Intent scoring, questions, meetings",
                    "IntentClarifier, Signal, Question",
                ],
                [
                    "constitution.py",
                    "Executable governance gates",
                    "Constitution, Violation, PatchDecision",
                ],
                ["config.py", "The rulebook loader", "SpecKitConfig, ConfigError"],
                [
                    "personas.py",
                    "Seniority, heuristics, review gates",
                    "Persona, Heuristic, ReviewGate",
                ],
                [
                    "languages.py",
                    "Toolchains and repo detection",
                    "Toolchain, RepoProfile, detect_repo",
                ],
                ["scaffold.py", "Required repository structure", "RepoScaffolder, ScaffoldPlan"],
                [
                    "router.py",
                    "Role/intent → engine, with fallback",
                    "EngineRouter, Engine, NullEngine",
                ],
                ["memory_hub.py", "Case-based reasoning", "MemoryHub, MemoryCase, RetrievalReport"],
                [
                    "stages.py",
                    "PM, Architect, Planner, Worker, QA, Delivery",
                    "PMStage … DeliveryStage",
                ],
                ["pipeline.py", "The stage machine over one RunState", "DeliveryPipeline"],
                ["master.py", "Many repos, one objective", "MasterOrchestrator, ProgramRun"],
                ["handbook.py", "This document, generated from the code", "build_handbook"],
            ],
            widths=[1.05, 2.1, 2.0],
            mono_columns=(0, 2),
        ),
        h2("3.2 Control flow"),
        flow(
            "DeliveryPipeline.start(objective)\n"
            "  ├─ IntentClarifier.assess ............... score intent, produce questions\n"
            "  │    └─ READY? no  → return RunState(stage=CLARIFY)   ← human answers here\n"
            "  ├─ PMStage.draft ........................ Spec  + constitution.check_spec\n"
            "  ├─ MemoryHub.retrieve ................... past pitfalls for this objective\n"
            "  ├─ ArchitectStage.draft ................. Plan  + constitution.check_plan\n"
            "  │    └─ persona.risks_for(spec) ......... 25 years, as risks\n"
            "  ├─ TaskPlanner.build .................... TaskGraph + constitution.check_tasks\n"
            "  │    ├─ test task ◄── implement task .... test-first by graph shape\n"
            "  │    ├─ structure task (if repo incomplete)\n"
            "  │    └─ persona.gate_tasks .............. security / migration / eval / perf …\n"
            "  ├─ WorkerStage.execute .................. topological order, failures block deps\n"
            "  ├─ QAStage.verify ....................... BDD + AAA, fences, coverage, verdict\n"
            "  ├─ DeliveryStage.package ................ accepted? assumptions? residuals?\n"
            "  └─ MemoryHub.harvest .................... one case, pitfalls first"
        ),
        h2("3.3 Where a human enters"),
        p(
            "Exactly three places, and never in the middle of a stage: answering clarification "
            "questions, holding a clarification meeting, and reading the delivery record. The run "
            "state serialises to JSON at any point, so a run can wait days for a meeting and "
            "resume in a different process."
        ),
        *listing("pipeline", "DeliveryPipeline._build", "The stage machine, gate by gate"),
        PageBreak(),
    ]


def ch_clarification() -> list[Any]:
    from future_agents.sdd.clarify import VAGUE_TERMS

    detector_rows = [
        ["Detector", "Fires when", "Cost", "Blocking"],
        [
            "vague terms",
            "an unmeasurable adjective appears (fast, robust, TBD…)",
            "0.14 each, max 3",
            "no",
        ],
        ["missing metric", "a change objective states no baseline or target", "0.22", "yes"],
        ["missing acceptance", "no observable outcome is stated", "0.16", "no — assumed"],
        ["missing data source", "data/report work names no system of record", "0.20", "yes"],
        ["missing integration target", "integration work names no counterparty", "0.18", "yes"],
        ["dangling reference", "the objective opens with it / this / they", "0.25", "yes"],
        ["multi-objective", "'and also', 'as well as' — two deliverables in one", "0.12", "no"],
        [
            "escalation trigger",
            "auth, payment, PII, PHI, migration, prod credential",
            "0.20",
            "yes",
        ],
        ["open-ended", "ends in '?' or is shorter than six words", "0.20–0.22", "yes"],
    ]
    return [
        h1("4 · Intent clarification"),
        p(
            "This is the stage that separates a delivery system from a code generator. Most agent "
            "pipelines accept an underspecified objective and confidently build the wrong thing. "
            "Here, intent is scored before anything is built, and the system asks only what would "
            "change the outcome."
        ),
        h2("4.1 Detectors"),
        table(detector_rows, widths=[1.2, 3.0, 0.85, 0.65]),
        caption(
            f"The vague-term lexicon currently holds {len(VAGUE_TERMS)} entries: "
            + ", ".join(VAGUE_TERMS[:14])
            + ", …"
        ),
        h2("4.2 The score"),
        flow(
            "confidence = clamp(1 − Σ signal_weights, 0, 1) × structure_bonus\n"
            "\n"
            "structure_bonus = 0.85\n"
            "                + 0.05 if the objective carries constraints\n"
            "                + 0.05 if it carries raw inputs (transcript, ticket)\n"
            "                + 0.05 if it carries a deadline          (capped at 1.0)\n"
            "\n"
            "an auto-assumed unknown costs half its weight — recorded, not free"
        ),
        p(
            "Well-formed intake earns confidence back: an objective that arrives with constraints, "
            "a transcript and a date is a better-specified objective, and the score says so."
        ),
        h2("4.3 The escalation ladder"),
        table(
            [
                ["Rung", "Condition", "What happens"],
                [
                    "auto-assume",
                    "a low-risk unknown with a sensible default",
                    "an Assumption is recorded and surfaced at delivery",
                ],
                [
                    "async questions",
                    "confidence between the two thresholds",
                    "a question set the human answers in their own time",
                ],
                [
                    "meeting",
                    "confidence &lt; meeting_threshold, or blocking unknowns survive max_rounds",
                    "a MeetingRequest with agenda, attendees, duration",
                ],
                [
                    "blocked",
                    "a human stops the work, or the gate cannot be satisfied",
                    "the run stops with the reason recorded",
                ],
            ],
            widths=[0.8, 2.0, 2.6],
        ),
        *listing("clarify", "IntentClarifier._decide", "The ladder, in code"),
        h2("4.4 Meetings"),
        p(
            "A meeting request is never a bare 'please clarify'. It carries the reason the system "
            "escalated, one agenda line per open question, the requester plus the configured "
            "attendees, and a duration. Closing it is a single call: the notes become objective "
            "context, the answers close the questions, and the run continues from where it stopped."
        ),
        *listing("clarify", "IntentClarifier.record_meeting"),
        *listing("clarify", "IntentClarifier._meeting"),
        h2("4.5 Worked example"),
        flow(
            '>>> pipeline.start(Objective(statement="Make the dashboard faster", submitted_by="sam"))\n'
            "\n"
            "stage: clarify        intent: meeting_required (confidence 0.119)\n"
            "  ·  'faster' is not measurable — what number or observable state counts as done?\n"
            "  !  What is the current baseline and the target number?\n"
            "  !  Which system of record supplies this data, and how fresh must it be?\n"
            "  !  What problem does this solve, and for whom?\n"
            "  assumed [medium] The requester verifies the outcome on the primary interface.\n"
            "\n"
            ">>> pipeline.hold_meeting(state, 'Ops owns sign-off. Baseline 3.2s.', answers)\n"
            "\n"
            "stage: done           intent: ready (confidence 0.782)\n"
            "  QA PASS — 1/1 behaviours verified          delivery: ACCEPTED"
        ),
        *listing("clarify", "_detect_missing_metric", "One detector, end to end"),
        PageBreak(),
    ]


def ch_artifacts() -> list[Any]:
    return [
        h1("5 · The IR artifacts"),
        h2("5.1 Traceability identifiers"),
        p(
            "The single most valuable structural decision in the system: every requirement gets a "
            "stable id, every acceptance criterion hangs off that id, every task references the "
            "requirements and criteria it serves, and QA measures coverage over those ids. "
            "Coverage becomes computable rather than asserted."
        ),
        flow(
            "REQ-002                     a requirement\n"
            "└── REQ-002-AC-001          an acceptance criterion (Given / When / Then)\n"
            "     ├── T-005  [test]      the test task that covers it\n"
            "     ├── T-006  [code]      the implementation, depending on T-005\n"
            "     └── QA check           verified = test task done AND code tasks done"
        ),
        h2("5.2 Requirement and criterion"),
        *listing("models", "Requirement"),
        *listing("models", "AcceptanceCriterion"),
        h2("5.3 Spec"),
        *listing("models", "Spec"),
        h2("5.4 Plan"),
        *listing("models", "Plan"),
        h2("5.5 The task graph"),
        p(
            "Kahn's algorithm with a stable queue: the same graph always produces the same order, "
            "which matters when a run is replayed. A cycle raises rather than silently dropping "
            "tasks — a dropped task is a requirement that quietly never ships."
        ),
        *listing("models", "TaskGraph.topological_order"),
        h2("5.6 Run state"),
        p(
            "The pipeline holds no state of its own. Everything lives in the RunState, which is a "
            "Pydantic model and therefore JSON on demand — the reason a run can pause for a "
            "meeting and resume in another process, another day, another machine."
        ),
        *listing("models", "RunState"),
        PageBreak(),
    ]


def ch_constitution() -> list[Any]:
    config = SpecKitConfig.load(root=REPO_ROOT)
    constitution = config.constitution()
    rules = [["Rule", "Severity", "What it catches"]]
    rules += [
        ["acceptance-criteria-required", "error", "a requirement with nothing to verify"],
        ["no-blocking-unknowns", "error", "building on an unanswered blocking question"],
        ["spec-purity", "warn", "a functional spec naming the tech stack"],
        ["stale-plan", "error", "a plan drawn from a superseded spec revision"],
        ["banned-practice", "error", "a plan brushing a governance ban"],
        ["test-strategy-required", "error", "a plan with no stated test approach"],
        ["component-fanout", "warn", "a design fragmented past the configured limit"],
        ["test-parity", "error", "a MUST requirement with no test task"],
        ["untraceable-task", "warn", "a code task that serves no requirement"],
    ]
    return [
        h1("6 · The constitution and its gates"),
        p(
            "The constitution is data, not prose, so a gate can evaluate it. The markdown form "
            "that agents read is rendered from the same object, which is why the two cannot drift "
            "apart. Errors fail a stage closed; warnings are recorded and the run continues."
        ),
        h2("6.1 Rules"),
        table(rules, widths=[1.5, 0.7, 2.8], mono_columns=(0,)),
        h2("6.2 The current governance set"),
        table(
            [["Setting", "Value"]]
            + [
                ["runtime_stack", constitution.runtime_stack or "—"],
                ["banned_practices", "<br/>".join(constitution.banned_practices) or "—"],
                ["security_boundaries", "<br/>".join(constitution.security_boundaries) or "—"],
                ["escalation_triggers", ", ".join(constitution.escalation_triggers) or "—"],
                ["stack_terms (spec purity)", ", ".join(constitution.stack_terms) or "—"],
                ["enforce_test_parity", str(constitution.enforce_test_parity)],
                ["enforce_spec_purity", str(constitution.enforce_spec_purity)],
            ],
            widths=[1.1, 3.6],
        ),
        caption("Read live from data/config/spec_kit/spec-kit-enterprise.yaml at generation time."),
        h2("6.3 The spec gate"),
        *listing("constitution", "Constitution.check_spec"),
        h2("6.4 The task gate — test parity"),
        *listing("constitution", "Constitution.check_tasks"),
        h2("6.5 Banned-practice matching"),
        p(
            "Bans are written as sentences ('No direct database connections from API route "
            "handlers.'), but they must fire on prose that says the same thing differently. The "
            "matcher extracts content words and requires a supermajority to hit, which catches "
            "paraphrase without firing on every mention of the word 'database'."
        ),
        *listing("constitution", "Constitution._mentions"),
        h2("6.6 The CI/CD diff gate"),
        p(
            "Agents rewrite pipelines. The golden template is the approved shape; a proposed "
            "change may add steps but may not remove a topology line — a job, a needs edge, a "
            "runner, a uses, a steps or strategy block. The gate is a structural diff, not a "
            "prompt instruction, so it holds regardless of which engine produced the change."
        ),
        *listing("constitution", "Constitution.diff_gate"),
        flow(
            "$ python scripts/spec_kit.py diff-gate --proposed .github/workflows/ci.yml\n"
            "{'allowed': False, 'added': 4, 'removed': 9,\n"
            " 'reason': 'proposed change removes golden pipeline topology'}\n"
            "  removed topology: jobs:\n"
            "  removed topology: needs: lint"
        ),
        PageBreak(),
    ]


def ch_personas() -> list[Any]:
    rows = [["Persona", "Yrs", "Ready", "Coverage", "Heuristics", "Mandatory gates"]]
    for persona in personas.PERSONAS.values():
        rows.append(
            [
                f"<b>{persona.title}</b><br/><font face='Courier' size='6.5'>{persona.id}</font>",
                str(persona.years_experience),
                str(persona.ready_threshold if persona.ready_threshold is not None else "—"),
                str(persona.required_coverage if persona.required_coverage is not None else "—"),
                str(len(persona.heuristics)),
                "<br/>".join(g.name for g in persona.gates),
            ]
        )

    heuristic_rows = [["Heuristic", "Fires on", "Severity"]]
    for heuristic in personas.PRINCIPAL_HYBRID.heuristics:
        heuristic_rows.append(
            [
                heuristic.text,
                ", ".join(heuristic.applies_to) if heuristic.applies_to else "always",
                heuristic.severity,
            ]
        )

    return [
        h1("7 · Personas: working at 25 years of experience"),
        p(
            "A persona is not a tone of voice. It is a set of behavioural changes: how much "
            "confidence the system demands before it starts building, which review gates are "
            "mandatory in the task graph, what coverage it will accept, and which hard-won rules "
            "enter the plan as explicit risks. The default is the principal hybrid — one engineer "
            "who has carried both the model pager and the request-path pager."
        ),
        h2("7.1 The catalog"),
        table(rows, widths=[1.5, 0.35, 0.45, 0.55, 0.5, 1.8]),
        h2("7.2 What a persona actually changes"),
        table(
            [
                ["Effect", "Mechanism", "Consequence"],
                [
                    "Interrogation depth",
                    "ready_threshold / meeting_threshold",
                    "a principal asks more before building",
                ],
                [
                    "Coverage bar",
                    "qa.required_coverage",
                    "1.0 for principals, 0.8 for the pragmatic profile",
                ],
                [
                    "Mandatory review",
                    "gate_tasks() appends REVIEW units",
                    "security, migration, eval, perf, observability, ADR",
                ],
                [
                    "Design constraints",
                    "risks_for() appends plan risks",
                    "experience becomes a constraint, not advice",
                ],
                [
                    "Engine choice",
                    "engine_overrides per role",
                    "a harder role gets a stronger model",
                ],
            ],
            widths=[1.0, 1.5, 2.3],
        ),
        *listing("personas", "Persona.apply_to_config"),
        *listing("personas", "Persona.gate_tasks"),
        h2("7.3 The heuristics of the default persona"),
        p(
            f"{len(personas.PRINCIPAL_HYBRID.heuristics)} rules, each with the keywords that make "
            "it relevant. A heuristic that fires becomes a Risk on the plan with "
            "<font face='Courier'>source=persona:principal_hybrid</font>, so a reviewer can see "
            "exactly why it is there."
        ),
        table(heuristic_rows, widths=[3.6, 1.4, 0.55]),
        h2("7.4 Selection"),
        flow(
            "python scripts/spec_kit.py --persona principal_ai_engineer run --statement '…'\n"
            "python scripts/spec_kit.py --persona pragmatic run --statement '…'   # internal tool\n"
            "\n"
            "DeliveryPipeline(config, persona=get_persona('principal_fullstack'))\n"
            "MasterOrchestrator(config, persona=PRINCIPAL_HYBRID)      # per-repo override too"
        ),
        callout(
            "Unknown persona ids do not raise",
            "get_persona() falls back to the principal hybrid. A typo in a config file should "
            "degrade to the strictest sensible default, never crash a delivery run or silently "
            "drop every gate.",
        ),
        PageBreak(),
    ]


def ch_languages() -> list[Any]:
    matrix = languages.language_matrix()
    rows = [["Language", "Detected by", "Test", "Lint", "Pin"]]
    for chain, row in zip(languages.TOOLCHAINS, matrix):
        rows.append(
            [
                chain.display_name,
                ", ".join(chain.manifests[:2]) or ", ".join(chain.extensions[:2]),
                row["test"],
                row["lint"],
                row["pin_style"],
            ]
        )

    pin_rows = [["Language", "Dependency policy"]]
    pin_rows += [[c.display_name, c.pin_rule] for c in languages.TOOLCHAINS]

    return [
        h1("8 · Any language: the toolchain matrix"),
        p(
            "A repository is profiled from evidence — its manifests and its file extensions — "
            "never assumed. Each language carries the commands a contributor actually runs, the "
            "layout its ecosystem expects, and the dependency-pinning policy the guardrails "
            "enforce for it. Nothing in the pipeline hard-codes 'pytest': every stage asks the "
            "toolchain."
        ),
        h2(f"8.1 The {len(languages.TOOLCHAINS)} toolchains"),
        table(rows, widths=[0.9, 1.5, 1.6, 1.5, 0.5], mono_columns=(1, 2, 3, 4)),
        h2("8.2 Dependency policy per ecosystem"),
        p(
            "The guardrails rule 'no exact pins' is correct for application dependencies in "
            "Python and npm, and wrong for Go, Maven and Terraform providers, where exact pinning "
            "is the ecosystem's design. The matrix encodes the difference so the rule is applied "
            "with judgement rather than uniformly."
        ),
        table(pin_rows, widths=[0.9, 4.2]),
        h2("8.3 Detection"),
        p(
            "A manifest is stronger evidence than a pile of files: a repo with one "
            "<font face='Courier'>go.mod</font> and four hundred JSON fixtures is a Go repo. "
            "Manifests score 50, files score 1, and TypeScript never loses to JavaScript merely "
            "because both carry a package.json."
        ),
        *listing("languages", "detect_repo"),
        h2("8.4 A polyglot repository"),
        p(
            "Secondary languages are kept, not discarded. The scaffolder emits an extra CI "
            "workflow per significant secondary toolchain, and the profile exposes every detected "
            "language so a plan can name the right commands for the part of the repo it touches."
        ),
        flow(
            "$ python scripts/spec_kit.py detect --path .\n"
            ".: python — detected: python(184), javascript(2), shell(2), sql(1)\n"
            "  monorepo: True  ci: True  tests: True\n"
            "  toolchain: Python\n"
            "    install   pip install -e '.[dev]'\n"
            "    format    ruff format .\n"
            "    lint      ruff check .\n"
            "    test      pytest -q\n"
            "  dependency policy: compatible-release ranges; exact pins only for build tooling\n"
            "  missing structure: docs/architecture.md, docs/runbook.md, docs/adr/0001-…md"
        ),
        h2("8.5 Adding a language"),
        p(
            "One <font face='Courier'>Toolchain</font> entry. No other module changes — detection, "
            "scaffolding, CI generation, the plan's test strategy and the task descriptions all "
            "read from it."
        ),
        *code(
            "Toolchain(\n"
            '    language="zig",\n'
            '    display_name="Zig",\n'
            '    manifests=("build.zig",),\n'
            '    extensions=(".zig",),\n'
            '    package_manager="zig",\n'
            '    install="zig build --fetch",\n'
            '    test="zig build test",\n'
            '    format="zig fmt .",\n'
            '    build="zig build -Doptimize=ReleaseSafe",\n'
            '    pin_style="exact",\n'
            '    pin_rule="dependencies pinned by hash in build.zig.zon",\n'
            '    layout=_common("src", "tests"),\n'
            '    manifest_file="build.zig",\n'
            "    manifest_template='const std = @import(\"std\");\\n',\n"
            ")"
        ),
        PageBreak(),
    ]


def ch_structure() -> list[Any]:
    from future_agents.sdd.scaffold import FORBIDDEN

    universal = [
        ["Entry", "Why it is required"],
        ["README.md", "what this is and the exact commands to run it"],
        [".gitignore", "secrets and build output never reach the remote"],
        [".env.example", "every variable the app reads, with REPLACE_ME placeholders"],
        ["docs/architecture.md", "the shape of the system and its trust boundaries"],
        ["docs/runbook.md", "what breaks, how you see it, how you undo it"],
        ["docs/adr/0001-…md", "decisions that are expensive to reverse"],
        [".github/workflows/ci.yml", "lint → test → guardrails, in the golden topology"],
        ["&lt;language manifest&gt;", "a correct starter manifest when the repo has none"],
        ["&lt;source&gt; / &lt;tests&gt;", "the layout that language's ecosystem expects"],
    ]
    layout_rows = [["Language", "Source", "Tests", "Extra"]]
    for chain in languages.TOOLCHAINS:
        dirs = [e.path for e in chain.layout if e.kind == "dir"]
        files = [
            e.path
            for e in chain.layout
            if e.kind == "file" and e.path not in {"README.md", ".gitignore", ".env.example"}
        ]
        source = next(
            (d for d in dirs if d not in {"docs"} and "test" not in d and "spec" not in d), "—"
        )
        tests = next((d for d in dirs if "test" in d.lower() or "spec" in d.lower()), "—")
        extra = ", ".join([d for d in dirs if d not in {source, tests, "docs"}] + files) or "—"
        layout_rows.append([chain.display_name, source, tests, extra])

    return [
        h1("9 · Repository structure"),
        p(
            "Every repository the system touches must have the same governance surface, whatever "
            "language it is written in. The scaffolder computes what is missing without touching "
            "disk, and writes only the gaps — it never overwrites, and it never creates a "
            "forbidden file."
        ),
        h2("9.1 The universal surface"),
        table(universal, widths=[1.2, 3.5], mono_columns=(0,)),
        h2("9.2 Per-language layout"),
        table(layout_rows, widths=[0.9, 1.1, 1.1, 2.0], mono_columns=(1, 2, 3)),
        h2("9.3 Never created"),
        p(
            "The scaffolder refuses these regardless of what a plan or an engine asks for: "
            + ", ".join(f"<font face='Courier'>{name}</font>" for name in FORBIDDEN)
            + ". A `.env.example` is always written; a `.env` never is."
        ),
        h2("9.4 The generated CI workflow"),
        p(
            "Built from the detected toolchain's own commands, in the golden topology — three "
            "jobs wired with <font face='Courier'>needs</font>, so the diff gate can later "
            "protect it from being flattened."
        ),
        *listing("scaffold", "_ci_workflow"),
        h2("9.5 Planning and applying"),
        *listing("scaffold", "RepoScaffolder.plan"),
        h2("9.6 Monorepos"),
        p(
            "A monorepo keeps its source under <font face='Courier'>packages/</font> or "
            "<font face='Courier'>apps/</font>, not <font face='Courier'>src/</font>. The "
            "validator accepts any conventional root rather than littering an established "
            "repository with an empty directory it does not want."
        ),
        *listing("scaffold", "_satisfied"),
        h2("9.7 As a delivery gate"),
        p(
            "When a pipeline is given a repo root, the planner asks the scaffolder what is "
            "missing and, if anything is, adds an INFRA task naming the gaps — the structure work "
            "becomes part of the delivery instead of a lint failure three weeks later."
        ),
        flow(
            "$ python scripts/spec_kit.py scaffold --path ../new-service --language go --write\n"
            "go: 10 to create, 0 already present\n"
            "  + go.mod                    go modules manifest\n"
            "  + cmd                       entrypoints\n"
            "  + internal                  source\n"
            "  + docs                      architecture notes and runbooks\n"
            "  + README.md                 what this is, how to run it\n"
            "  + .env.example              every env var with REPLACE_ME placeholders\n"
            "  + .gitignore                never commit secrets or build output\n"
            "  + docs/architecture.md      the shape of the system\n"
            "  + docs/runbook.md           what breaks, how you see it, how you undo it\n"
            "  + .github/workflows/ci.yml  lint → test → guardrails, the golden topology"
        ),
        PageBreak(),
    ]


def ch_execution() -> list[Any]:
    return [
        h1("10 · Task graph and execution"),
        h2("10.1 How the graph is built"),
        table(
            [
                ["Unit", "Kind", "Depends on", "Why it exists"],
                [
                    "Scaffold &lt;component&gt;",
                    "code",
                    "—",
                    "one unit per component, so work can start in parallel",
                ],
                [
                    "Test REQ-n",
                    "test",
                    "the component scaffold",
                    "the criterion is expressed as a test before code exists",
                ],
                [
                    "Implement REQ-n",
                    "code",
                    "its test task",
                    "test-first enforced by graph shape, not by discipline",
                ],
                [
                    "Create missing structure",
                    "infra",
                    "—",
                    "only when the repo lacks required entries",
                ],
                [
                    "Guardrails and constitution review",
                    "review",
                    "every code task",
                    "the standing gate before delivery",
                ],
                [
                    "Persona gates",
                    "review",
                    "the guardrails review",
                    "security, migration, eval, perf, observability, ADR",
                ],
                [
                    "Document the delivered behaviour",
                    "doc",
                    "review + gates",
                    "docs and runbook ship with the change",
                ],
            ],
            widths=[1.5, 0.6, 1.3, 2.2],
        ),
        *listing("stages", "TaskPlanner.build"),
        h2("10.2 Execution order and failure propagation"),
        p(
            "Tasks run in topological order. A failing task marks its dependents BLOCKED rather "
            "than failing the whole run — the rest of the graph still produces useful work, and "
            "QA reports precisely which criteria went unverified as a result. A backend that "
            "raises is a task failure, never a pipeline crash."
        ),
        *listing("stages", "WorkerStage.execute"),
        h2("10.3 Backends"),
        p(
            "The default backend records what would happen. A real backend is one function: shell "
            "out to a coding agent, run the repo's own test command, open a pull request. The "
            "criterion ids it claims are what QA verifies against, so a backend must claim only "
            "what it actually exercised."
        ),
        *listing("stages", "dry_run_backend"),
        *code(
            "import subprocess\n"
            "from future_agents.sdd import TaskStatus, WorkResult\n"
            "\n"
            "def shell_backend(task, spec):\n"
            "    # the repo's own command, from the detected toolchain\n"
            "    command = {\n"
            '        "test": ["go", "test", "./..."],\n'
            '        "code": ["make", "build"],\n'
            "    }.get(task.kind.value)\n"
            "    if command is None:\n"
            "        return WorkResult(task_id=task.id, status=TaskStatus.SKIPPED)\n"
            "\n"
            "    result = subprocess.run(command, capture_output=True, text=True, timeout=900)\n"
            "    ok = result.returncode == 0\n"
            "    return WorkResult(\n"
            "        task_id=task.id,\n"
            "        status=TaskStatus.DONE if ok else TaskStatus.FAILED,\n"
            "        summary=task.title,\n"
            "        # claim coverage only for a test task that actually passed\n"
            '        criterion_ids=task.criterion_ids if ok and task.kind.value == "test" else [],\n'
            "        log_excerpt=result.stdout[-2000:],\n"
            '        error="" if ok else result.stderr[-2000:],\n'
            "    )\n"
            "\n"
            "pipeline = DeliveryPipeline(config, backend=shell_backend, repo_root='.')"
        ),
        callout(
            "The honest limit",
            "Delivery is only as real as the backend wired behind it. Everything upstream — the "
            "spec, the plan, the graph, the gates, the QA arithmetic — is real regardless; the "
            "dry-run backend simply does no work, and says so in every result it returns.",
        ),
        PageBreak(),
    ]


def ch_qa() -> list[Any]:
    return [
        h1("11 · QA orchestration"),
        p(
            "QA is not a log reader. It builds a behaviour check for every in-scope acceptance "
            "criterion, decides verification from evidence in the work results, computes coverage "
            "over MUST criteria, and reports in a fixed, short format."
        ),
        h2("11.1 BDD and AAA scaffolding"),
        flow(
            "criterion  REQ-002-AC-001\n"
            "  Given    a week of usage data\n"
            "  When     the churn report runs\n"
            "  Then     at-risk accounts are listed\n"
            "\n"
            "test skeleton\n"
            "  Arrange: a week of usage data\n"
            "  Act:     the churn report runs\n"
            "  Assert:  at-risk accounts are listed"
        ),
        h2("11.2 Verification rule"),
        flow(
            "verified(criterion) =\n"
            "      ∃ test task covering it whose WorkResult.status == DONE\n"
            "  AND ∀ code tasks covering it: WorkResult.status == DONE\n"
            "\n"
            "coverage = |verified MUST criteria| / |MUST criteria|\n"
            "\n"
            "verdict = BLOCKED  if there are no checks at all\n"
            "        = FAIL     if any blocker finding, or coverage < required_coverage\n"
            "        = PASS     otherwise"
        ),
        *listing("stages", "QAStage.verify"),
        h2("11.3 Scope fences"),
        p(
            "Criteria matching a configured fence are dropped before checks are built and listed "
            "in <font face='Courier'>out_of_scope_ignored</font>. They can never become findings, "
            "so the QA agent cannot halt a pipeline over load testing that was never in scope — "
            "the failure mode that makes teams turn automated QA off."
        ),
        *listing("stages", "QAStage._out_of_scope"),
        h2("11.4 The reporting protocol"),
        p(
            "Verbosity is <font face='Courier'>summary_only</font> by default: a verdict line, the "
            "verified behaviours, then the first blocker. Logs stay in the artifact, out of the "
            "channel, unless someone asks for them."
        ),
        *listing("models", "QAReport.summary_lines"),
        flow(
            "QA PASS — 3/3 behaviours verified\n"
            "✓ account managers can call at-risk customers\n"
            "✓ the report pulls from Snowflake every Monday 09:00\n"
            "✓ flag any account whose usage dropped 20% or more"
        ),
        h2("11.5 Ephemeral environments"),
        p(
            "When <font face='Courier'>qa.ephemeral_environment</font> is set, the report records "
            "the environment as ephemeral and marks it cleaned when the verdict is written — the "
            "teardown is part of the protocol, not an afterthought a human remembers."
        ),
        PageBreak(),
    ]


def ch_memory() -> list[Any]:
    return [
        h1("12 · The memory hub"),
        p(
            "Agents that forget repeat the same mistake every sprint. After every run the "
            "harvester compresses what happened into a case: the objective, the problem, the "
            "solution, and — the part that earns its keep — the pitfalls. Cases are markdown on "
            "disk, so they are reviewable, diffable and greppable, with a JSON index for retrieval."
        ),
        h2("12.1 Where pitfalls come from"),
        table(
            [
                ["Source", "Becomes"],
                [
                    "a blocking question that had to be asked",
                    "'Intent gap — X had to be asked; answer: Y'",
                ],
                ["a clarification meeting", "'Needed a live meeting: &lt;reason&gt;'"],
                ["an in-scope QA finding", "'QA blocker: &lt;summary&gt;'"],
                ["a failed task", "'Task T-00n failed: &lt;error&gt;'"],
            ],
            widths=[1.5, 3.2],
        ),
        *listing("memory_hub", "_pitfalls"),
        h2("12.2 Retrieval, biased toward failure"),
        p(
            "Matching is keyword overlap (Jaccard) with a 1.5× boost for cases whose outcome was "
            "not a success. A case that records a pitfall changes the next plan; a success case "
            "rarely does. The top-k matches are injected into the plan as "
            "<font face='Courier'>historical_warnings</font> and as risks with "
            "<font face='Courier'>source=memory</font>."
        ),
        *listing("memory_hub", "MemoryHub.retrieve"),
        h2("12.3 Harvest"),
        *listing("memory_hub", "MemoryHub.harvest"),
        h2("12.4 The case format"),
        *code(
            "# Weekly churn report for sales\n"
            "\n"
            "- **Outcome:** failure\n"
            "- **Tags:** meeting_transcript, reporting, qa-fail\n"
            "- **Recorded:** 2026-09-05\n"
            "\n"
            "## Objective\n"
            "Sales must get a weekly churn report so that account managers can call at-risk customers\n"
            "\n"
            "## Problem\n"
            "3 requirements derived from a meeting_transcript submitted by dana.\n"
            "\n"
            "## Solution\n"
            "2 components: core (1 req), reporting (2 req). Runtime: Python 3.11+\n"
            "\n"
            "## Pitfalls & hard lessons\n"
            "- Intent gap — 'Which system of record supplies this data?' had to be asked;\n"
            "  answer: Snowflake, refreshed nightly at 02:00\n"
            "- QA blocker: REQ-003-AC-001 not verified — no passing test task"
        ),
        h2("12.5 Swapping in a vector store"),
        p(
            "Retrieval is deliberately behind one method. A semantic store (Chroma, pgvector, a "
            "hosted index) replaces <font face='Courier'>MemoryHub.retrieve</font> without any "
            "other module noticing; the markdown cases remain the durable, reviewable record."
        ),
        PageBreak(),
    ]


def ch_routing() -> list[Any]:
    config = SpecKitConfig.load(root=REPO_ROOT)
    rows = [["Role", "Engine", "Fallback", "Purpose"]]
    for name, role in config.agents.roles.items():
        rows.append(
            [name, role.engine, role.fallback or config.agents.default_engine, role.purpose]
        )
    return [
        h1("13 · Engine routing and MCP"),
        p(
            "The pipeline never names a model inline. It asks the router, which resolves role → "
            "engine from the rulebook, lets an intent keyword override it, and falls back when an "
            "engine is unavailable. Changing vendor or model is a configuration edit, and a "
            "failing engine degrades to deterministic behaviour instead of taking the run down."
        ),
        h2("13.1 Current role map"),
        table(rows, widths=[0.95, 1.15, 1.15, 2.2], mono_columns=(0, 1, 2)),
        caption(
            "Read live from the rulebook. Intent routes: "
            + (", ".join(f"{k} → {v}" for k, v in config.agents.intent_routes.items()) or "none")
        ),
        h2("13.2 Resolution order"),
        flow(
            "1. intent keyword match ....... 'terraform' in the task intent → claude-opus-5\n"
            "2. role default ............... agents.roles[role].engine\n"
            "3. role fallback .............. agents.roles[role].fallback\n"
            "4. agents.default_engine\n"
            "5. NullEngine ................. deterministic; the stage's own rules stand"
        ),
        *listing("router", "EngineRouter.run"),
        h2("13.3 Engines"),
        p(
            "An engine is anything with a <font face='Courier'>name</font> and a "
            "<font face='Courier'>complete(call)</font>. Three ship: NullEngine (the default, "
            "returns nothing), CallableEngine (any function — the seam tests and custom backends "
            "use), and AnthropicEngine (optional <font face='Courier'>ai</font> extra)."
        ),
        *listing("router", "AnthropicEngine"),
        callout(
            "Model identifiers",
            "The rulebook uses the current Claude family — claude-opus-5 for architecture and "
            "review, claude-sonnet-5 for PM/worker/QA, claude-haiku-4-5-20251001 for "
            "documentation and harvesting. Pin the id and record it with the output: a silently "
            "upgraded model is an unversioned dependency, which is exactly what the principal AI "
            "persona's heuristics say.",
        ),
        h2("13.4 MCP exposure"),
        p(
            "The gateway URI lives in the rulebook, and the resources an agent needs are already "
            "addressable: the constitution as markdown, the golden CI template, the language "
            "matrix, the persona catalog and the memory cases. The API surfaces each of these as "
            "an endpoint, so an MCP server is a thin adapter rather than a second source of truth."
        ),
        table(
            [
                ["Resource", "Endpoint", "CLI"],
                ["constitution", "GET /api/sdd/constitution", "spec_kit.py constitution"],
                [
                    "golden CI template",
                    "config: cicd.golden_template_path",
                    "spec_kit.py diff-gate",
                ],
                ["language matrix", "GET /api/sdd/languages", "spec_kit.py languages"],
                ["persona catalog", "GET /api/sdd/personas", "spec_kit.py personas"],
                ["memory cases", "GET /api/sdd/cases", "spec_kit.py cases"],
            ],
            widths=[1.1, 2.0, 1.6],
            mono_columns=(1, 2),
        ),
        PageBreak(),
    ]


def ch_master() -> list[Any]:
    return [
        h1("14 · The master orchestrator"),
        p(
            "Real work rarely lands in one repository: an API change needs a client change needs "
            "a pipeline change. The master orchestrator profiles every registered repository, "
            "routes an objective to the ones it actually touches, orders them into waves by their "
            "declared dependencies, and runs a full delivery pipeline in each — each with its own "
            "language, its own toolchain and, if you want, its own persona."
        ),
        h2("14.1 The part that matters to a human"),
        callout(
            "One question set for the whole program",
            "Five repositories each raise 'which system of record supplies this data?'. The "
            "orchestrator merges questions by text, keeps one, and remembers which repo asked "
            "what. The human answers once — or attends one meeting — and every affected repo "
            "resumes. Without this, multi-repo automation is a machine for generating duplicate "
            "questions.",
        ),
        *listing("master", "MasterOrchestrator._merge_questions"),
        h2("14.2 Registration and inventory"),
        *listing("master", "MasterOrchestrator.register"),
        flow(
            "orchestrator.register('checkout-api',   '../checkout-api',\n"
            "                      keywords=['api', 'checkout', 'payment'])\n"
            "orchestrator.register('web-app',        '../web-app',\n"
            "                      keywords=['ui', 'web', 'checkout'],\n"
            "                      depends_on=['checkout-api'])\n"
            "orchestrator.register('platform-infra', '../platform-infra',\n"
            "                      persona_id='staff_platform',\n"
            "                      keywords=['infra', 'deploy'])\n"
            "\n"
            "checkout-api    go          missing: none\n"
            "web-app         typescript  missing: none\n"
            "platform-infra  terraform   missing: ['docs/runbook.md']"
        ),
        h2("14.3 Routing and waves"),
        p(
            "An explicit repo list always wins. Otherwise the objective is scored against each "
            "repo's name, keywords and language; if nothing matches, every repo is in scope "
            "rather than silently none. Waves come from the declared dependency edges, and a "
            "cycle raises instead of deadlocking."
        ),
        *listing("master", "MasterOrchestrator.waves"),
        h2("14.4 Dependency behaviour"),
        p(
            "A repo whose dependency is still clarifying or blocked is skipped with the reason "
            "recorded, and picked up automatically once the dependency reaches a usable state — "
            "so a program converges over successive answer rounds rather than needing to be "
            "restarted."
        ),
        *listing("master", "MasterOrchestrator._resume_blocked_waves"),
        h2("14.5 Per-repo context"),
        p(
            "Each repository receives its own copy of the objective, carrying that repo's "
            "language, test command and dependency policy as constraints — which is why the Go "
            "repo's plan says <font face='Courier'>go test ./...</font> and the TypeScript repo's "
            "says <font face='Courier'>npm test</font> from the same human sentence."
        ),
        *listing("master", "MasterOrchestrator._repo_objective"),
        h2("14.6 A program run"),
        flow(
            "$ python scripts/spec_kit.py program \\\n"
            "    --repo checkout-api=../checkout-api \\\n"
            "    --repo web-app=../web-app \\\n"
            "    --depends web-app:checkout-api \\\n"
            "    --source meeting_transcript --by dana --input notes.txt \\\n"
            "    --statement 'Add saved payment methods to checkout'\n"
            "\n"
            "program prog-5a75e8f6 — waves: [['checkout-api'], ['web-app']]\n"
            "  checkout-api           clarify\n"
            "  web-app                skipped — waiting on checkout-api (clarify)\n"
            "\n"
            "open questions (answer once for the whole program):\n"
            "  ! q-1c9f  Which external system is on the other side, and who owns its credentials?\n"
            "  ! q-77a2  This touches payment — who signs off before it ships?\n"
            "\n"
            "# after two answer rounds\n"
            "  checkout-api  done  3 requirements  13 tasks  QA pass  accepted\n"
            "  web-app       done  3 requirements  13 tasks  QA pass  accepted"
        ),
        h2("14.7 The program report"),
        *listing("master", "ProgramRun.report"),
        PageBreak(),
    ]


def ch_configuration() -> list[Any]:
    path = REPO_ROOT / "data" / "config" / "spec_kit" / "spec-kit-enterprise.yaml"
    text = path.read_text() if path.is_file() else "# not found"
    sections = [
        ["Section", "Key", "Meaning"],
        ["project", "name / description / owner", "identity for reports and cases"],
        ["governance", "runtime_stack", "the default stack when no repo is attached"],
        ["governance", "banned_practices", "matched against plans; a hit fails the plan gate"],
        ["governance", "escalation_triggers", "words that force a named human approver"],
        ["governance", "stack_terms", "implementation words a functional spec must avoid"],
        ["governance", "enforce_test_parity / spec_purity", "toggle the two structural gates"],
        ["agents", "mcp_gateway_uri", "where the MCP gateway lives"],
        ["agents", "default_engine", "used when a role names none"],
        ["agents", "roles.&lt;role&gt;.engine / fallback", "per-role model, with a fallback"],
        ["agents", "intent_routes", "keyword → engine, checked before the role default"],
        ["memory_hub", "case_studies_path", "where markdown cases are written"],
        ["memory_hub", "retrieval.max_context_injection", "how many past cases enter a plan"],
        ["memory_hub", "retrieval.prefer_failures", "weight failures above successes"],
        ["clarification", "ready_threshold", "confidence at which the system starts building"],
        ["clarification", "meeting_threshold", "below this, a meeting instead of a form"],
        ["clarification", "max_rounds", "async rounds before escalating"],
        ["clarification", "auto_assume_low_risk", "turn low-risk unknowns into assumptions"],
        ["clarification", "meeting_attendees / duration", "who is invited, for how long"],
        ["cicd", "enforce_golden_pattern", "run the diff gate"],
        ["cicd", "golden_template_path", "the approved pipeline shape"],
        ["qa", "enforce_bdd / enforce_aaa", "Given-When-Then and Arrange-Act-Assert"],
        ["qa", "out_of_scope", "fences QA may never fail a run over"],
        ["qa", "required_coverage", "fraction of MUST criteria that must verify"],
        ["qa", "communication.verbosity", "summary_only keeps logs out of the channel"],
    ]
    return [
        h1("15 · Configuration reference"),
        p(
            "One rulebook, loaded by every surface — pipeline, CLI, API and CI. "
            "<font face='Courier'>${VAR}</font> and <font face='Courier'>${VAR:-default}</font> "
            "resolve from the environment at load time, and a literal value under a key that "
            "looks like a secret is rejected with a ConfigError rather than being caught later by "
            "a scanner."
        ),
        h2("15.1 Every key"),
        table(sections, widths=[0.85, 1.6, 2.6], mono_columns=(1,)),
        h2("15.2 Secret handling"),
        *listing("config", "_resolve"),
        h2("15.3 The rulebook in full"),
        caption("data/config/spec_kit/spec-kit-enterprise.yaml"),
        *code(text),
        PageBreak(),
    ]


def ch_operations() -> list[Any]:
    cli_rows = [
        ["Command", "What it does"],
        [
            "run --statement … [--input f] [--repo path]",
            "intake an objective and drive it as far as it can go",
        ],
        ["answer --state f --answer ID=text", "answer open questions and resume"],
        ["meeting --state f --notes-file f", "record a clarification meeting and resume"],
        ["status --state f", "print a saved run"],
        ["program --repo name=path --statement …", "one objective across many repositories"],
        ["detect --path .", "profile a repo: language, toolchain, structure gaps"],
        ["scaffold --path . [--language X] --write", "create the structure a repo is missing"],
        ["cases [--query …]", "browse or search the memory hub"],
        ["personas / languages", "list seniority profiles and toolchains"],
        ["constitution", "render governance as markdown (MCP resource)"],
        ["diff-gate --proposed f", "check a pipeline change against the golden template"],
    ]
    api_rows = [
        ["Method / path", "Purpose"],
        ["POST /api/sdd/objectives", "intake — wire a meeting-notes webhook here"],
        ["GET /api/sdd/runs/{id}/questions", "what the system needs from a human"],
        ["POST /api/sdd/runs/{id}/answers", "answer and resume"],
        ["POST /api/sdd/runs/{id}/meeting", "record a meeting and resume"],
        ["POST /api/sdd/programs", "run one objective across many repositories"],
        ["POST /api/sdd/programs/{id}/answers", "one answer sheet for the whole program"],
        ["POST /api/sdd/repos/detect", "profile a repository"],
        ["POST /api/sdd/repos/scaffold", "plan or write missing structure"],
        ["GET /api/sdd/cases", "search the memory hub"],
        ["GET /api/sdd/personas · /languages", "catalogs"],
        ["GET /api/sdd/constitution", "governance as markdown"],
        ["POST /api/sdd/cicd/diff-gate", "golden-pattern check"],
    ]
    return [
        h1("16 · Operating the system"),
        h2("16.1 Command line"),
        table(cli_rows, widths=[1.9, 3.0], mono_columns=(0,)),
        h2("16.2 HTTP"),
        p("Served by <font face='Courier'>uvicorn future_agents.api.main:app</font>."),
        table(api_rows, widths=[1.7, 3.0], mono_columns=(0,)),
        h2("16.3 Python"),
        *code(
            "from future_agents.sdd import (\n"
            "    DeliveryPipeline, MasterOrchestrator, Objective, SpecKitConfig, get_persona,\n"
            ")\n"
            "\n"
            "config = SpecKitConfig.load()\n"
            "pipeline = DeliveryPipeline(\n"
            "    config,\n"
            "    persona=get_persona('principal_hybrid'),\n"
            "    repo_root='.',              # tasks use this repo's toolchain and structure\n"
            "    backend=shell_backend,      # real work; omit for a dry run\n"
            ")\n"
            "\n"
            "state = pipeline.start(Objective(\n"
            "    statement='Sales must get a weekly churn report so that AMs can call at-risk accounts',\n"
            "    source=IntakeSource.MEETING,\n"
            "    submitted_by='dana',\n"
            "    raw_inputs=[transcript_text],\n"
            "    constraints=['no new production env vars'],\n"
            "    deadline='2026-10-01',\n"
            "))\n"
            "\n"
            "if state.awaiting_human:\n"
            "    for question in state.pending_questions():\n"
            "        print(('!' if question.blocking else '·'), question.id, question.text)\n"
            "    state = pipeline.answer(state, collect_answers())\n"
            "\n"
            "print(state.qa.summary_lines())\n"
            "print(state.delivery.accepted, state.delivery.unconfirmed_assumptions)\n"
            "save_state(state, '.spec-kit/runs')"
        ),
        h2("16.4 In CI"),
        *code(
            "# .github/workflows/spec-kit.yml\n"
            "name: spec-kit\n"
            "\n"
            "on:\n"
            "  pull_request:\n"
            "\n"
            "jobs:\n"
            "  structure:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - run: python scripts/spec_kit.py detect --path .\n"
            "      - run: python scripts/spec_kit.py diff-gate --proposed .github/workflows/ci.yml"
        ),
        h2("16.5 Intake from a meeting tool"),
        p(
            "The API is the integration point: post the transcript as "
            "<font face='Courier'>raw_inputs</font> with "
            "<font face='Courier'>source=meeting_transcript</font>, then surface the returned "
            "questions wherever the team already is. If the response carries a meeting request, "
            "put it on a calendar — the agenda is already written."
        ),
        *code(
            "POST /api/sdd/objectives\n"
            "{\n"
            '  "statement": "Add saved payment methods to checkout",\n'
            '  "source": "meeting_transcript",\n'
            '  "submitted_by": "dana",\n'
            '  "raw_inputs": ["Dana: the api must expose a tokenised card list …"],\n'
            '  "constraints": ["no card PAN stored"],\n'
            '  "deadline": "2026-11-01"\n'
            "}\n"
            "\n"
            "200 OK\n"
            "{\n"
            '  "run_id": "run-0ddf86a9", "stage": "clarify", "awaiting_human": true,\n'
            '  "confidence": 0.54, "outcome": "async_questions",\n'
            '  "questions": [{"id": "q-1c9f", "text": "Which external system …", "blocking": true}],\n'
            '  "meeting": null\n'
            "}",
            language="json",
        ),
        PageBreak(),
    ]


PATTERNS = [
    (
        "IR pipeline",
        "Free-form intent produces inconsistent output and cannot be reviewed.",
        "Pass intent through typed artifacts, each bounding the next; a stage may only read its "
        "immediate input.",
        "models.py, pipeline.py",
        "More upfront structure; a genuinely trivial task still walks the whole pipeline.",
    ),
    (
        "Fail-closed gate",
        "An agent fills a gap with a plausible guess and the error surfaces three stages later.",
        "A gate returns violations; an error-severity violation stops the stage with the reason "
        "recorded on the run.",
        "constitution.py, pipeline._block",
        "Runs stop more often — which is the point, but it needs a human in the loop.",
    ),
    (
        "Confidence-scored intent",
        "'Is this clear enough?' is a judgement call made differently every time.",
        "Detectors emit weighted signals; confidence is arithmetic; thresholds live in config.",
        "clarify.IntentClarifier",
        "Heuristic detectors are approximate; the score is a prior, not a truth.",
    ),
    (
        "Escalation ladder",
        "Either the agent asks nothing, or it asks everything and becomes exhausting.",
        "Four rungs — auto-assume, async questions, meeting, blocked — chosen by score and by how "
        "many rounds have already failed to resolve it.",
        "clarify._decide",
        "Thresholds need tuning per team; too high and every objective becomes a meeting.",
    ),
    (
        "Assumption ledger",
        "Silent defaults are indistinguishable from decisions.",
        "Every unknown resolved without a human becomes an Assumption record, surfaced on the "
        "delivery.",
        "models.Assumption, DeliveryStage",
        "The delivery record grows; that is the honest cost of not asking.",
    ),
    (
        "Traceability ids",
        "'Is this requirement covered?' can only be answered by reading everything.",
        "REQ → AC → task → QA check, by id, all the way through.",
        "models.py, stages.py",
        "Ids must be stable across re-planning; renumbering breaks history.",
    ),
    (
        "Content-hash staleness",
        "An upstream artifact is revised and downstream work silently continues on the old one.",
        "Each artifact fingerprints its semantic content; a downstream artifact stores the hash it "
        "was built from and the gate compares.",
        "models.Hashable, constitution.check_plan",
        "Any edit invalidates downstream work, including a cosmetic one.",
    ),
    (
        "Test-first by graph shape",
        "'Write tests' is advice, and advice is skipped under time pressure.",
        "The implement task depends on its test task; test parity is also a gate on the graph.",
        "stages.TaskPlanner.build",
        "Rigid for exploratory spikes — use the pragmatic persona there.",
    ),
    (
        "Scope fence",
        "An automated QA agent invents requirements and blocks releases over them.",
        "Configured fences are removed before checks are built, so they cannot become findings.",
        "stages.QAStage._out_of_scope, qa.out_of_scope",
        "A real gap inside a fence is invisible; fences must be reviewed like code.",
    ),
    (
        "Summary-only reporting",
        "Verbose agent output trains humans to ignore it.",
        "A fixed short format: verdict, verified behaviours, first blocker. Logs live in the "
        "artifact.",
        "models.QAReport.summary_lines",
        "Debugging needs one extra hop to the full record.",
    ),
    (
        "Case-based memory",
        "The same mistake is made in three sprints by three people.",
        "Harvest each run into a markdown case; retrieve the closest before planning; weight "
        "failures above successes.",
        "memory_hub.py",
        "Keyword retrieval is shallow; cases need occasional pruning.",
    ),
    (
        "Router with fallback",
        "A model id hard-coded in a stage makes vendor change a refactor, and an outage an incident.",
        "Role and intent resolve to an engine through config, with a fallback and a deterministic "
        "null engine at the end of the chain.",
        "router.EngineRouter",
        "Silent degradation must be visible — hence the routing history.",
    ),
    (
        "Deterministic core, model enrichment",
        "A pipeline whose structure depends on a model cannot be tested or replayed.",
        "Rules produce the structure; the engine only improves free text; empty output is a valid "
        "response.",
        "stages.py",
        "Heuristic extraction is blunter than a good model on messy input.",
    ),
    (
        "Persona as configuration",
        "'Act like a senior engineer' in a prompt changes tone, not behaviour.",
        "A persona tunes thresholds, adds review tasks and injects heuristics as plan risks.",
        "personas.py",
        "Heuristic keyword matching can fire a gate on an unrelated word.",
    ),
    (
        "Toolchain matrix",
        "Automation that assumes one language fails on the second repository.",
        "Detect the repo; read every command, layout and dependency policy from a Toolchain entry.",
        "languages.py",
        "A new ecosystem needs an entry before the system understands it.",
    ),
    (
        "Idempotent scaffold",
        "Structure generators overwrite work and cannot be run twice.",
        "Plan what is missing, write only that, treat conventional alternatives as satisfying the "
        "requirement, and never create a forbidden file.",
        "scaffold.py",
        "Cannot repair a wrong-but-present file; it only fills gaps.",
    ),
    (
        "Dependency waves",
        "Multi-repo work fans out in the wrong order and the client ships against a missing API.",
        "Declared repo dependencies produce ordered waves; a repo whose dependency is unresolved "
        "is skipped and resumed later.",
        "master.waves, master._resume_blocked_waves",
        "Dependencies are declared, not inferred — a wrong edge is a wrong order.",
    ),
    (
        "Merged question set",
        "Five repos ask a human the same question five times.",
        "Questions are merged by text across repos, answered once, and fanned back out by a "
        "question map.",
        "master._merge_questions",
        "Two repos can mean subtly different things by the same sentence.",
    ),
    (
        "Resumable run state",
        "A pipeline that pauses for a human dies with the process.",
        "All state lives in one serialisable model; the pipeline is stateless machinery over it.",
        "models.RunState, save_state / load_state",
        "State migrations become a real concern as the schema evolves.",
    ),
]


def ch_patterns() -> list[Any]:
    out: list[Any] = [
        h1("17 · Pattern catalog"),
        p(
            "The design patterns this system is built from, each with the failure it prevents and "
            "the price it charges. They are reusable outside this codebase — most of them are "
            "answers to problems every agentic delivery system meets."
        ),
    ]
    for index, (name, problem, solution, where, cost) in enumerate(PATTERNS, start=1):
        out.append(
            KeepTogether(
                [
                    h3(f"17.{index} {name}"),
                    table(
                        [
                            ["Problem", problem],
                            ["Solution", solution],
                            ["In code", f"<font face='Courier'>{where}</font>"],
                            ["Trade-off", cost],
                        ],
                        widths=[0.6, 4.4],
                        header=False,
                    ),
                    Spacer(1, 4 * mm),
                ]
            )
        )
    out.append(PageBreak())
    return out


def ch_extending() -> list[Any]:
    return [
        h1("18 · Extending the system"),
        h2("18.1 Add a language"),
        p("One entry in <font face='Courier'>TOOLCHAINS</font> — see §8.5. Nothing else changes."),
        h2("18.2 Add a persona"),
        *code(
            "from future_agents.sdd.personas import Heuristic, Persona, ReviewGate, PERSONAS\n"
            "\n"
            "EMBEDDED = Persona(\n"
            '    id="principal_embedded",\n'
            '    title="Principal Embedded Engineer",\n'
            "    years_experience=25,\n"
            '    disciplines=["firmware", "rtos", "hardware-interfaces"],\n'
            "    ready_threshold=0.85,          # silicon does not forgive a vague spec\n"
            "    required_coverage=1.0,\n"
            "    heuristics=[\n"
            "        Heuristic(\n"
            '            text="Every ISR has a stated worst-case execution time.",\n'
            '            applies_to=("interrupt", "isr", "timer", "dma"),\n'
            '            severity="high",\n'
            "        ),\n"
            "    ],\n"
            "    gates=[\n"
            "        ReviewGate(\n"
            '            name="Memory and timing review",\n'
            '            description="Stack depth, heap use and worst-case timing are bounded.",\n'
            "        ),\n"
            "    ],\n"
            ")\n"
            "PERSONAS[EMBEDDED.id] = EMBEDDED"
        ),
        h2("18.3 Add a clarification detector"),
        p(
            "A detector is a function from an objective and its context to signals. Register it on "
            "the clarifier and it participates in scoring immediately."
        ),
        *code(
            "from future_agents.sdd.clarify import IntentClarifier, Signal\n"
            "from future_agents.sdd.models import QuestionTopic\n"
            "\n"
            "def detect_missing_retention(objective, ctx):\n"
            '    if "store" not in ctx.text and "retain" not in ctx.text:\n'
            "        return []\n"
            '    if any(w in ctx.text for w in ("retention", "delete after", "ttl")):\n'
            "        return []\n"
            "    return [\n"
            "        Signal(\n"
            "            topic=QuestionTopic.DATA,\n"
            '            question="How long is this data kept, and what deletes it?",\n'
            '            why="undeclared retention becomes a compliance finding",\n'
            "            weight=0.18,\n"
            "            blocking=True,\n"
            "        )\n"
            "    ]\n"
            "\n"
            "clarifier = IntentClarifier(config)\n"
            "clarifier._detectors.append(detect_missing_retention)"
        ),
        h2("18.4 Add a governance rule"),
        p(
            "Add a method to <font face='Courier'>Constitution</font> returning "
            "<font face='Courier'>Violation</font> objects, and call it from the matching stage "
            "transition in <font face='Courier'>DeliveryPipeline._build</font>. Error severity "
            "stops the run; warn severity is recorded."
        ),
        h2("18.5 Add a stage"),
        p(
            "Stages are plain classes with one method that takes upstream artifacts and returns "
            "the next one. Add the artifact to <font face='Courier'>RunState</font>, add the enum "
            "member to <font face='Courier'>Stage</font>, and wire it into the machine between the "
            "two stages it belongs between. Keep it deterministic; let the engine enrich only free "
            "text."
        ),
        h2("18.6 Replace the memory backend"),
        p(
            "Implement <font face='Courier'>retrieve()</font> against a vector store and keep the "
            "markdown cases as the durable record — see §12.5."
        ),
        PageBreak(),
    ]


def ch_testing() -> list[Any]:
    return [
        h1("19 · Testing"),
        p(
            "The whole pipeline runs offline and deterministically, which is what makes it "
            "testable at all. Two suites cover it: "
            "<font face='Courier'>tests/test_sdd.py</font> for the core pipeline and "
            "<font face='Courier'>tests/test_sdd_multirepo.py</font> for personas, languages, "
            "scaffolding and the orchestrator."
        ),
        table(
            [
                ["Area", "What is asserted"],
                [
                    "Clarification",
                    "well-formed intent is ready; vague intent escalates to a meeting; answers raise confidence; low-risk unknowns become assumptions; escalation triggers block",
                ],
                [
                    "Config",
                    "env references resolve; inline secrets are rejected; thresholds must be ordered",
                ],
                [
                    "Constitution",
                    "missing criteria, blocking unknowns, stale plans, banned practices, test parity; the diff gate allows additive patches and blocks rewrites",
                ],
                [
                    "IR models",
                    "content hashes ignore provenance and track content; topological order is stable; cycles raise",
                ],
                [
                    "Stages",
                    "requirement extraction and ids; memory warnings reach the plan; test-before-code; failure blocks dependents; fences; coverage arithmetic",
                ],
                [
                    "Personas",
                    "thresholds and coverage change; gates appear in the graph; AI heuristics fire only on model work; unknown ids fall back",
                ],
                [
                    "Languages",
                    "every toolchain declares the essentials; scaffold → detect round-trips for seven languages; TS beats JS; unknown still profiles",
                ],
                [
                    "Scaffolding",
                    "required structure is created; idempotent; dry-run writes nothing; forbidden files never appear; CI uses the language's commands",
                ],
                [
                    "Orchestrator",
                    "routing, waves, cycle rejection, merged questions, one answer sheet drives every repo, per-repo toolchains",
                ],
            ],
            widths=[0.9, 4.1],
        ),
        h2("19.1 Running them"),
        *code(
            "pytest -q                                    # whole repo\n"
            "pytest -q tests/test_sdd.py                  # core pipeline\n"
            "pytest -q tests/test_sdd_multirepo.py        # personas, languages, orchestration\n"
            "ruff check packages/future_agents/ apps/ scripts/\n"
            "ruff format --check packages/future_agents/ apps/ scripts/\n"
            "python packages/guardrails/guardrails_engine.py . --mode block"
        ),
        h2("19.2 Testing your own backend"),
        p(
            "Use <font face='Courier'>CallableEngine</font> for the model seam and a fake backend "
            "for the work seam; both are single functions, so a full delivery run in a test is "
            "fast and has no network."
        ),
        *code(
            "def failing_backend(task, spec):\n"
            "    if task.id == 'T-001':\n"
            "        return WorkResult(task_id=task.id, status=TaskStatus.FAILED, error='boom')\n"
            "    return WorkResult(task_id=task.id, status=TaskStatus.DONE)\n"
            "\n"
            "results = WorkerStage(failing_backend).execute(graph, spec)\n"
            "assert any(r.status is TaskStatus.BLOCKED for r in results)"
        ),
        PageBreak(),
    ]


def ch_limits() -> list[Any]:
    return [
        h1("20 · Limits, and what to build next"),
        p(
            "Stated plainly, because a system that oversells itself gets switched off the first "
            "time it is believed."
        ),
        table(
            [
                ["Limit", "Consequence", "Mitigation today"],
                [
                    "Requirement extraction is heuristic",
                    "a rambling transcript yields noisy requirements",
                    "attach an engine to pm_agent; edit the spec before planning",
                ],
                [
                    "Memory retrieval is keyword-based",
                    "a semantically similar case can be missed",
                    "tag cases; swap in a vector store behind retrieve()",
                ],
                [
                    "dry_run_backend does no work",
                    "delivery is simulated until a backend is wired",
                    "wire a shell/agent backend (§10.3)",
                ],
                [
                    "Detectors are keyword-driven",
                    "an unusual phrasing can slip past a gate",
                    "add a detector (§18.3); gates still catch the artifact",
                ],
                [
                    "API runs live in memory",
                    "a restart loses in-flight runs",
                    "save_state / load_state; persist per run",
                ],
                [
                    "Repo dependencies are declared",
                    "a wrong edge produces a wrong order",
                    "keep the graph small and reviewed",
                ],
                [
                    "One engine call per free-text field",
                    "prose quality varies with the engine",
                    "the structure never does — that is the point",
                ],
            ],
            widths=[1.2, 1.7, 2.1],
        ),
        h2("20.1 The next things worth building"),
        *bullets(
            [
                "<b>A real worker backend</b> in this repo: shell out per task kind, run the "
                "detected toolchain's test command, and open a pull request per component.",
                "<b>Semantic memory</b>: embeddings behind <font face='Courier'>retrieve()</font>, "
                "with the markdown cases unchanged as the reviewable record.",
                "<b>Persistence for programs</b>: the multi-repo run state on disk, so a program "
                "survives a restart the way a single run already does.",
                "<b>Cost and latency accounting</b> per run, which the AI persona's own heuristics "
                "demand of anything it ships.",
                "<b>An MCP server</b> exposing the constitution, golden templates, language matrix "
                "and cases directly — the API already serves each of them.",
            ]
        ),
        h2("20.2 Where to start reading the code"),
        table(
            [
                ["If you want to understand…", "Read"],
                ["how a run flows", "pipeline.py — DeliveryPipeline._build"],
                ["why it stops and asks", "clarify.py — IntentClarifier.assess and _decide"],
                ["what the artifacts are", "models.py, top to bottom"],
                ["how governance is enforced", "constitution.py"],
                ["how seniority changes behaviour", "personas.py"],
                ["how any language is supported", "languages.py"],
                ["how many repos are coordinated", "master.py"],
            ],
            widths=[1.6, 3.1],
            mono_columns=(1,),
        ),
        Spacer(1, 6 * mm),
        callout(
            "One sentence",
            "The system refuses to build on a guess, asks a human at the right level of ceremony, "
            "ships with tests and gates appropriate to a principal engineer, works in whatever "
            "language the repository is written in, coordinates several repositories at once, and "
            "writes down what it learned so the next run starts better informed.",
        ),
    ]


CHAPTERS = (
    ch_summary,
    ch_philosophy,
    ch_architecture,
    ch_clarification,
    ch_artifacts,
    ch_constitution,
    ch_personas,
    ch_languages,
    ch_structure,
    ch_execution,
    ch_qa,
    ch_memory,
    ch_routing,
    ch_master,
    ch_configuration,
    ch_operations,
    ch_patterns,
    ch_extending,
    ch_testing,
    ch_limits,
)

TITLE = "Spec-Driven Delivery"
SUBTITLE = (
    "An automated system that clarifies intent, plans, builds, verifies and delivers — "
    "in any language, across many repositories, at a principal engineer's standard."
)


def build_handbook(output: str | Path = "docs/spec-driven-delivery-handbook.pdf") -> Path:
    """Render the handbook. Returns the path written."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    story: list[Any] = []
    story.extend(_cover(TITLE, SUBTITLE))
    story.extend(_toc())
    for chapter in CHAPTERS:
        story.extend(chapter())

    doc = Handbook(str(path), TITLE)
    # multiBuild resolves the table of contents' page numbers.
    doc.multiBuild(story)
    return path


def handbook_stats() -> dict[str, int]:
    """Cheap introspection used by the tests and the CLI."""
    return {
        "chapters": len(CHAPTERS),
        "patterns": len(PATTERNS),
        "toolchains": len(languages.TOOLCHAINS),
        "personas": len(personas.PERSONAS),
        "listings": sum(
            1
            for chapter in CHAPTERS
            for line in inspect.getsource(chapter).splitlines()
            if "listing(" in line
        ),
    }
