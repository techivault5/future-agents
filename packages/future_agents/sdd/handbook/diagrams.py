"""Architecture diagrams, drawn as vectors.

A small layout toolkit — swimlanes, boxes, numbered badges, elbow arrows — and
the four diagrams the handbook uses. Everything is reportlab `Drawing` output,
so the same figure goes into the PDF as vector art and exports to SVG or PNG for
slides and READMEs without being redrawn.

Coordinates are millimetres measured from the *top* left, because that is how a
person describes a layout. The renderer flips to PDF space at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm

from future_agents.sdd.handbook.fonts import FONTS, sanitize

Side = Literal["left", "right", "top", "bottom"]

INK = colors.HexColor("#12161c")
MUTED = colors.HexColor("#5b6672")
RULE = colors.HexColor("#c9d1d9")
ACCENT = colors.HexColor("#1f6feb")
GREEN = colors.HexColor("#1a7f4b")
AMBER = colors.HexColor("#a15c00")
RED = colors.HexColor("#b3261e")

LANE_TINTS = (
    colors.HexColor("#f2f4f7"),
    colors.HexColor("#eef6ef"),
    colors.HexColor("#eef3fb"),
    colors.HexColor("#faf3ec"),
)
BOX_FILL = colors.white
BOX_ALT = colors.HexColor("#eef3fb")
BOX_WARN = colors.HexColor("#fdf3f2")


@dataclass
class Node:
    """A box on the diagram. Coordinates are mm from the top-left."""

    x: float
    y: float
    w: float
    h: float
    title: str
    subtitle: str = ""
    badge: str = ""
    fill: colors.Color = BOX_FILL
    stroke: colors.Color = RULE
    accent: Optional[colors.Color] = None
    font_size: float = 6.6

    def anchor(self, side: Side) -> tuple[float, float]:
        if side == "left":
            return self.x, self.y + self.h / 2
        if side == "right":
            return self.x + self.w, self.y + self.h / 2
        if side == "top":
            return self.x + self.w / 2, self.y
        return self.x + self.w / 2, self.y + self.h


@dataclass
class Arrow:
    start: tuple[float, float]
    end: tuple[float, float]
    waypoints: list[tuple[float, float]] = field(default_factory=list)
    label: str = ""
    color: colors.Color = MUTED
    dashed: bool = False
    badge: str = ""


@dataclass
class Lane:
    """A vertical swimlane (`x`, `w`) or a horizontal band (`y`, `h`)."""

    title: str
    tint: colors.Color
    x: float = 0.0
    w: float = 0.0
    y: float = 0.0
    h: float = 0.0
    horizontal: bool = False


@dataclass
class Zone:
    """A labelled region other boxes sit inside — a VPC, a pool, a state store."""

    x: float
    y: float
    w: float
    h: float
    title: str
    tint: colors.Color
    stroke: colors.Color
    dashed: bool = True


@dataclass
class Caption:
    x: float
    y: float
    text: str
    size: float = 5.8
    color: colors.Color = MUTED
    anchor: str = "start"
    bold: bool = False


class Diagram:
    """Build a figure, then render it once."""

    def __init__(self, width: float, height: float, title: str = "") -> None:
        self.width = width
        self.height = height
        self.title = title
        self.lanes: list[Lane] = []
        self.zones: list[Zone] = []
        self.nodes: list[Node] = []
        self.arrows: list[Arrow] = []
        self.captions: list[Caption] = []

    # ── Authoring ─────────────────────────────────────────────────────────────

    def lane(self, x: float, w: float, title: str, tint: Optional[colors.Color] = None) -> Lane:
        """A vertical swimlane."""
        shade = tint or LANE_TINTS[len(self.lanes) % len(LANE_TINTS)]
        lane = Lane(title=title, tint=shade, x=x, w=w)
        self.lanes.append(lane)
        return lane

    def band(self, y: float, h: float, title: str, tint: Optional[colors.Color] = None) -> Lane:
        """A horizontal band — the right shape when the flow runs left to right."""
        shade = tint or LANE_TINTS[len(self.lanes) % len(LANE_TINTS)]
        lane = Lane(title=title, tint=shade, y=y, h=h, horizontal=True)
        self.lanes.append(lane)
        return lane

    def zone(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        tint: Optional[colors.Color] = None,
        stroke: Optional[colors.Color] = None,
        dashed: bool = True,
    ) -> Zone:
        """A boundary: everything drawn inside it belongs to it."""
        region = Zone(
            x=x,
            y=y,
            w=w,
            h=h,
            title=title,
            tint=tint or colors.Color(1, 1, 1, 0.55),
            stroke=stroke or ACCENT,
            dashed=dashed,
        )
        self.zones.append(region)
        return region

    def node(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        subtitle: str = "",
        **kwargs,
    ) -> Node:
        box = Node(x=x, y=y, w=w, h=h, title=title, subtitle=subtitle, **kwargs)
        self.nodes.append(box)
        return box

    def caption(self, x: float, y: float, text: str, **kwargs) -> Caption:
        item = Caption(x=x, y=y, text=text, **kwargs)
        self.captions.append(item)
        return item

    def connect(
        self,
        source: Node,
        target: Node,
        from_side: Side = "right",
        to_side: Side = "left",
        label: str = "",
        badge: str = "",
        color: colors.Color = MUTED,
        dashed: bool = False,
        detour: Optional[float] = None,
    ) -> Arrow:
        """An elbow arrow between two boxes. `detour` offsets the middle leg."""
        start = source.anchor(from_side)
        end = target.anchor(to_side)
        waypoints = _route(start, end, from_side, to_side, detour)
        arrow = Arrow(
            start=start,
            end=end,
            waypoints=waypoints,
            label=label,
            color=color,
            dashed=dashed,
            badge=badge,
        )
        self.arrows.append(arrow)
        return arrow

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self) -> Drawing:
        drawing = Drawing(self.width * mm, self.height * mm)

        for lane in self.lanes:
            if lane.horizontal:
                drawing.add(
                    Rect(
                        0,
                        self._y(lane.y + lane.h),
                        self.width * mm,
                        lane.h * mm,
                        fillColor=lane.tint,
                        strokeColor=None,
                    )
                )
                # Right-aligned: the left of a band is where the flow starts, and
                # a title there collides with the first arrow that crosses in.
                drawing.add(
                    String(
                        (self.width - 2.5) * mm,
                        self._y(lane.y + 4.6),
                        sanitize(lane.title.upper()),
                        fontName=FONTS.sans_bold,
                        fontSize=6.0,
                        fillColor=MUTED,
                        textAnchor="end",
                    )
                )
                continue
            drawing.add(
                Rect(
                    lane.x * mm,
                    0,
                    lane.w * mm,
                    self.height * mm,
                    fillColor=lane.tint,
                    strokeColor=None,
                )
            )
            drawing.add(
                String(
                    (lane.x + lane.w / 2) * mm,
                    self._y(6.0),
                    sanitize(lane.title),
                    fontName=FONTS.sans_bold,
                    fontSize=7.2,
                    fillColor=MUTED,
                    textAnchor="middle",
                )
            )

        for region in self.zones:
            box = Rect(
                region.x * mm,
                self._y(region.y + region.h),
                region.w * mm,
                region.h * mm,
                rx=2.0 * mm,
                ry=2.0 * mm,
                fillColor=region.tint,
                strokeColor=region.stroke,
                strokeWidth=0.8,
            )
            if region.dashed:
                box.strokeDashArray = (2.5, 2.0)
            drawing.add(box)
            drawing.add(
                String(
                    (region.x + 3.0) * mm,
                    self._y(region.y + 4.6),
                    sanitize(region.title),
                    fontName=FONTS.sans_bold,
                    fontSize=6.0,
                    fillColor=region.stroke,
                    textAnchor="start",
                )
            )

        for arrow in self.arrows:
            self._draw_arrow(drawing, arrow)
        for box in self.nodes:
            self._draw_node(drawing, box)
        for item in self.captions:
            drawing.add(
                String(
                    item.x * mm,
                    self._y(item.y),
                    sanitize(item.text),
                    fontName=FONTS.sans_bold if item.bold else FONTS.sans,
                    fontSize=item.size,
                    fillColor=item.color,
                    textAnchor=item.anchor,
                )
            )
        return drawing

    def save_svg(self, path: str | Path) -> Path:
        from reportlab.graphics import renderSVG

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        renderSVG.drawToFile(self.render(), str(target))
        return target

    def save_png(self, path: str | Path, scale: float = 3.0) -> Optional[Path]:
        """Raster export for READMEs and slides.

        Needs a renderPM backend (`pip install rlPyCairo`). Without one this
        returns None rather than failing a build — the SVG is always available.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        drawing = self.render()
        drawing.scale(scale, scale)
        drawing.width *= scale
        drawing.height *= scale
        try:
            from reportlab.graphics import renderPM

            renderPM.drawToFile(drawing, str(target), fmt="PNG", bg=0xFFFFFF)
        except Exception:  # no raster backend on this machine
            return None
        return target

    # ── Internal ──────────────────────────────────────────────────────────────

    def _y(self, y: float) -> float:
        """Millimetres from the top → PDF points from the bottom."""
        return (self.height - y) * mm

    def _draw_node(self, drawing: Drawing, box: Node) -> None:
        drawing.add(
            Rect(
                box.x * mm,
                self._y(box.y + box.h),
                box.w * mm,
                box.h * mm,
                rx=1.6 * mm,
                ry=1.6 * mm,
                fillColor=box.fill,
                strokeColor=box.stroke,
                strokeWidth=0.7,
            )
        )
        if box.accent is not None:
            drawing.add(
                Rect(
                    box.x * mm,
                    self._y(box.y + box.h),
                    1.1 * mm,
                    box.h * mm,
                    fillColor=box.accent,
                    strokeColor=None,
                )
            )

        lines = _wrap(box.title, box.w - 6, box.font_size, FONTS.sans_bold)
        sub_size = box.font_size - 1.0
        sub_lines = _wrap(box.subtitle, box.w - 6, sub_size, FONTS.sans) if box.subtitle else []
        total = len(lines) * (box.font_size + 1.1) + len(sub_lines) * (box.font_size + 0.2)
        cursor = box.y + (box.h - total / (mm / mm) / 2.83) / 2 + box.font_size / 2.83

        for line in lines:
            drawing.add(
                String(
                    (box.x + box.w / 2) * mm,
                    self._y(cursor),
                    line,
                    fontName=FONTS.sans_bold,
                    fontSize=box.font_size,
                    fillColor=INK,
                    textAnchor="middle",
                )
            )
            cursor += (box.font_size + 1.1) / 2.83
        for line in sub_lines:
            drawing.add(
                String(
                    (box.x + box.w / 2) * mm,
                    self._y(cursor),
                    line,
                    fontName=FONTS.sans,
                    fontSize=box.font_size - 1.0,
                    fillColor=MUTED,
                    textAnchor="middle",
                )
            )
            cursor += (box.font_size + 0.2) / 2.83

        if box.badge:
            self._draw_badge(drawing, box.x, box.y, box.badge)

    def _draw_badge(self, drawing: Drawing, x: float, y: float, text: str) -> None:
        radius = 2.6
        drawing.add(
            Circle(
                x * mm,
                self._y(y),
                radius * mm,
                fillColor=ACCENT,
                strokeColor=colors.white,
                strokeWidth=0.8,
            )
        )
        drawing.add(
            String(
                x * mm,
                self._y(y) - 1.4 * mm,
                str(text),
                fontName=FONTS.sans_bold,
                fontSize=5.6,
                fillColor=colors.white,
                textAnchor="middle",
            )
        )

    def _draw_arrow(self, drawing: Drawing, arrow: Arrow) -> None:
        points = [arrow.start, *arrow.waypoints, arrow.end]
        dash = (2, 2) if arrow.dashed else None
        for first, second in zip(points, points[1:]):
            line = Line(
                first[0] * mm,
                self._y(first[1]),
                second[0] * mm,
                self._y(second[1]),
                strokeColor=arrow.color,
                strokeWidth=0.9,
            )
            if dash:
                line.strokeDashArray = dash
            drawing.add(line)

        self._draw_head(drawing, points[-2], points[-1], arrow.color)

        if arrow.label:
            # Sit the label above the line, never on it: an obscured arrowhead
            # makes the direction of a flow ambiguous.
            mid = _midpoint(points)
            width = _text_width(arrow.label, 5.6, FONTS.sans) / mm + 3
            drawing.add(
                Rect(
                    (mid[0] - width / 2) * mm,
                    self._y(mid[1] - 1.4),
                    width * mm,
                    4.4 * mm,
                    rx=0.8 * mm,
                    ry=0.8 * mm,
                    fillColor=colors.white,
                    strokeColor=RULE,
                    strokeWidth=0.5,
                )
            )
            drawing.add(
                String(
                    mid[0] * mm,
                    self._y(mid[1] - 2.5),
                    sanitize(arrow.label),
                    fontName=FONTS.sans,
                    fontSize=5.6,
                    fillColor=INK,
                    textAnchor="middle",
                )
            )
        if arrow.badge:
            mid = _midpoint(points)
            self._draw_badge(drawing, mid[0], mid[1] + 3.4, arrow.badge)

    def _draw_head(
        self,
        drawing: Drawing,
        previous: tuple[float, float],
        tip: tuple[float, float],
        color: colors.Color,
    ) -> None:
        size = 1.7
        dx, dy = tip[0] - previous[0], tip[1] - previous[1]
        if abs(dx) >= abs(dy):
            direction = 1 if dx > 0 else -1
            points = [
                tip[0] * mm,
                self._y(tip[1]),
                (tip[0] - direction * size * 1.6) * mm,
                self._y(tip[1] - size),
                (tip[0] - direction * size * 1.6) * mm,
                self._y(tip[1] + size),
            ]
        else:
            direction = 1 if dy > 0 else -1
            points = [
                tip[0] * mm,
                self._y(tip[1]),
                (tip[0] - size) * mm,
                self._y(tip[1] - direction * size * 1.6),
                (tip[0] + size) * mm,
                self._y(tip[1] - direction * size * 1.6),
            ]
        drawing.add(Polygon(points, fillColor=color, strokeColor=color))


# ── Geometry helpers ──────────────────────────────────────────────────────────


def _route(
    start: tuple[float, float],
    end: tuple[float, float],
    from_side: Side,
    to_side: Side,
    detour: Optional[float],
) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    if from_side in ("left", "right") and to_side in ("left", "right"):
        mid = detour if detour is not None else (sx + ex) / 2
        return [] if abs(sy - ey) < 0.4 else [(mid, sy), (mid, ey)]
    if from_side in ("top", "bottom") and to_side in ("top", "bottom"):
        mid = detour if detour is not None else (sy + ey) / 2
        return [] if abs(sx - ex) < 0.4 else [(sx, mid), (ex, mid)]
    if from_side in ("left", "right"):
        return [(ex, sy)]
    return [(sx, ey)]


def _midpoint(points: list[tuple[float, float]]) -> tuple[float, float]:
    longest, best = 0.0, (points[0], points[1])
    for first, second in zip(points, points[1:]):
        length = abs(second[0] - first[0]) + abs(second[1] - first[1])
        if length > longest:
            longest, best = length, (first, second)
    return ((best[0][0] + best[1][0]) / 2, (best[0][1] + best[1][1]) / 2)


def _text_width(text: str, size: float, font: str) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    return stringWidth(sanitize(text), font, size)


def _wrap(text: str, width_mm: float, size: float, font: str) -> list[str]:
    if not text:
        return []
    words = sanitize(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_width(candidate, size, font) <= width_mm * mm or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]
