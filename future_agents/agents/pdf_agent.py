"""PDF Agent — creates beautiful, structured PDFs with inclusive background imagery.

Each chapter page has a full-bleed background photo (diverse, inclusive people),
professional layout, chapter headers, and consistent branding. Uses ReportLab.

Image strategy (in order):
  1. Fetch from Unsplash API (if UNSPLASH_ACCESS_KEY env var set)
  2. Fetch from Pexels API   (if PEXELS_API_KEY env var set)
  3. Fall back to a generated gradient background
"""

from __future__ import annotations

import io
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any

from future_agents.core.base_agent import BaseAgent, TaskContext, TaskResult
from future_agents.models.feedback import ExecutionOutcome

logger = logging.getLogger(__name__)

# ── Theme definitions ─────────────────────────────────────────────────────────
PDF_THEMES = {
    "professional": {
        "primary": (0.08, 0.28, 0.62),  # deep blue
        "secondary": (0.13, 0.59, 0.95),
        "accent": (0.95, 0.61, 0.07),
        "text": (0.12, 0.12, 0.12),
        "light": (0.96, 0.97, 1.0),
    },
    "health": {
        "primary": (0.05, 0.45, 0.25),
        "secondary": (0.18, 0.70, 0.45),
        "accent": (0.90, 0.36, 0.36),
        "text": (0.10, 0.15, 0.10),
        "light": (0.93, 0.98, 0.95),
    },
    "corporate": {
        "primary": (0.12, 0.12, 0.25),
        "secondary": (0.30, 0.30, 0.55),
        "accent": (0.90, 0.65, 0.10),
        "text": (0.10, 0.10, 0.15),
        "light": (0.96, 0.96, 0.98),
    },
    "tech": {
        "primary": (0.05, 0.25, 0.45),
        "secondary": (0.00, 0.60, 0.80),
        "accent": (0.20, 0.85, 0.60),
        "text": (0.08, 0.08, 0.12),
        "light": (0.93, 0.97, 1.0),
    },
}

# People categories for Unsplash/Pexels search queries
PEOPLE_QUERIES = {
    "professionals": "diverse professionals office team collaboration",
    "healthcare": "diverse doctors nurses healthcare team smiling",
    "community": "diverse community people smiling together",
    "technology": "diverse tech professionals working team",
    "education": "diverse students teachers education learning",
    "leadership": "diverse leadership business professionals meeting",
    "general": "diverse people team collaboration smiling inclusion",
}


class PDFAgent(BaseAgent):
    """Creates inclusive, beautifully structured PDFs with chapter imagery.

    Capabilities:
    - pdf.create  — build full PDF from chapters
    - pdf.export  — confirm file and return metadata
    """

    def __init__(self, output_dir: str = "output/pdf", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._image_cache: dict[str, bytes] = {}

    @property
    def agent_type(self) -> str:
        return "pdf"

    @property
    def capabilities(self) -> list[str]:
        return ["pdf.create", "pdf.export"]

    async def _execute(self, context: TaskContext) -> TaskResult:
        handlers = {
            "pdf.create": self._create_pdf,
            "pdf.export": self._export_pdf,
        }
        handler = handlers.get(context.intent)
        if not handler:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"Unknown intent: {context.intent}"],
            )
        return await handler(context)

    # ── Image fetching ────────────────────────────────────────────────────────

    def _fetch_unsplash(self, query: str, width: int = 1600, height: int = 900) -> bytes | None:
        key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
        if not key:
            return None
        try:
            url = (
                f"https://api.unsplash.com/photos/random"
                f"?query={urllib.parse.quote(query)}"
                f"&orientation=landscape&w={width}&h={height}"
            )
            req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {key}"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                import json

                data = json.loads(resp.read())
                img_url = data["urls"]["regular"]
            req2 = urllib.request.Request(img_url)
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                return resp2.read()
        except Exception as exc:
            logger.debug("Unsplash fetch failed: %s", exc)
            return None

    def _fetch_pexels(self, query: str) -> bytes | None:
        key = os.environ.get("PEXELS_API_KEY", "")
        if not key:
            return None
        try:
            import urllib.parse

            url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page=1&orientation=landscape"
            req = urllib.request.Request(url, headers={"Authorization": key})
            with urllib.request.urlopen(req, timeout=8) as resp:
                import json

                data = json.loads(resp.read())
                photos = data.get("photos", [])
                if not photos:
                    return None
                img_url = photos[0]["src"]["large2x"]
            req2 = urllib.request.Request(img_url)
            with urllib.request.urlopen(req2, timeout=15) as resp2:
                return resp2.read()
        except Exception as exc:
            logger.debug("Pexels fetch failed: %s", exc)
            return None

    def _make_gradient_background(self, w: int, h: int, theme: dict) -> bytes:
        """Generate a gradient background image as JPEG bytes using PIL."""
        try:
            from PIL import Image, ImageDraw

            img = Image.new("RGB", (w, h))
            draw = ImageDraw.Draw(img)
            p1 = theme["primary"]
            p2 = theme["light"]
            for y in range(h):
                r = int((p1[0] + (p2[0] - p1[0]) * y / h) * 255)
                g = int((p1[1] + (p2[1] - p1[1]) * y / h) * 255)
                b = int((p1[2] + (p2[2] - p1[2]) * y / h) * 255)
                draw.line([(0, y), (w, y)], fill=(r, g, b))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception:
            return b""

    def _get_chapter_image(self, query: str, theme: dict, chapter_idx: int) -> bytes | None:
        cache_key = f"{query}_{chapter_idx}"
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        img_bytes = self._fetch_unsplash(query) or self._fetch_pexels(query)
        if not img_bytes:
            img_bytes = self._make_gradient_background(1600, 900, theme)

        if img_bytes:
            self._image_cache[cache_key] = img_bytes
        return img_bytes

    # ── ReportLab helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _draw_overlay(canvas, width, height, alpha: float = 0.55):
        """Draw a semi-transparent dark overlay over the background image."""
        canvas.setFillColorRGB(0, 0, 0, alpha=alpha)
        canvas.rect(0, 0, width, height, fill=1, stroke=0)

    @staticmethod
    def _draw_chapter_header_stripe(canvas, y: float, width: float, color_rgb: tuple, height: float = 4):
        canvas.setFillColorRGB(*color_rgb)
        canvas.rect(0, y, width, height, fill=1, stroke=0)

    # ── PDF creation ──────────────────────────────────────────────────────────

    async def _create_pdf(self, context: TaskContext) -> TaskResult:
        """Build a complete, beautiful, inclusive PDF.

        Parameters:
            title          (str): Document title
            subtitle       (str): Optional subtitle
            author         (str): Author name
            organization   (str): Organization
            people_type    (str): professionals|healthcare|community|technology|education|leadership|general
            color_theme    (str): professional|health|corporate|tech
            chapters       (list[dict]): Each has:
                             - title (str)
                             - content (str)
                             - sections (list[dict]): {heading, content}
                             - bullets (list[str])
                             - image_query (str): override image search per chapter
            conclusion     (str): Closing content
            output_name    (str): Filename without extension
        """
        try:
            from reportlab.lib import colors
            from reportlab.lib.colors import Color, HexColor, black, white
            from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import cm, mm
            from reportlab.pdfgen import canvas as rl_canvas
            from reportlab.platypus import (
                KeepTogether,
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
            from reportlab.platypus.flowables import HRFlowable
        except ImportError:
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=["reportlab not installed. Run: pip install reportlab"],
            )

        try:
            from PIL import Image
        except ImportError:
            pass

        p = context.parameters
        title = p.get("title", "Professional Report")
        subtitle = p.get("subtitle", "")
        author = p.get("author", "Document Agent")
        organization = p.get("organization", "")
        people_type = p.get("people_type", "professionals")
        theme_name = p.get("color_theme", "professional")
        chapters = p.get("chapters", [])
        conclusion = p.get("conclusion", "")
        output_name = p.get("output_name", title.lower().replace(" ", "_")[:40])

        theme = PDF_THEMES.get(theme_name, PDF_THEMES["professional"])
        default_query = PEOPLE_QUERIES.get(people_type, PEOPLE_QUERIES["general"])

        page_w, page_h = A4

        # Pre-fetch chapter images (one per chapter + cover)
        chapter_images: list[bytes | None] = []
        cover_img = self._get_chapter_image(default_query, theme, 0)
        for i, chap in enumerate(chapters):
            q = chap.get("image_query", default_query)
            img = self._get_chapter_image(q, theme, i + 1)
            chapter_images.append(img)

        out_path = self._output_dir / f"{output_name}.pdf"

        # ── Canvas-based renderer (for image backgrounds) ─────────────────
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas as rl_canvas

        io.BytesIO()
        c = rl_canvas.Canvas(str(out_path), pagesize=A4)
        c.setTitle(title)
        c.setAuthor(author)
        c.setSubject(subtitle)

        primary = theme["primary"]
        secondary = theme["secondary"]
        accent = theme["accent"]
        text_color = theme["text"]
        light = theme["light"]

        def draw_image_bg(canvas_obj, img_bytes: bytes | None, width, height):
            if not img_bytes:
                r, g, b = light
                canvas_obj.setFillColorRGB(r, g, b)
                canvas_obj.rect(0, 0, width, height, fill=1, stroke=0)
                return
            try:
                from PIL import Image as PILImage

                pil_img = PILImage.open(io.BytesIO(img_bytes)).convert("RGB")
                pil_img = pil_img.resize((int(width), int(height)), PILImage.LANCZOS)
                tmp = io.BytesIO()
                pil_img.save(tmp, format="JPEG", quality=82)
                tmp.seek(0)
                from reportlab.lib.utils import ImageReader

                img_reader = ImageReader(tmp)
                canvas_obj.drawImage(img_reader, 0, 0, width, height, preserveAspectRatio=False, mask=None)
            except Exception as exc:
                logger.debug("Image draw failed: %s", exc)
                r, g, b = light
                canvas_obj.setFillColorRGB(r, g, b)
                canvas_obj.rect(0, 0, width, height, fill=1, stroke=0)

        def draw_page_number(canvas_obj, page_num, total=None):
            canvas_obj.saveState()
            canvas_obj.setFillColorRGB(*text_color, alpha=0.5)
            canvas_obj.setFont("Helvetica", 8)
            txt = f"Page {page_num}" + (f" of {total}" if total else "")
            canvas_obj.drawCentredString(page_w / 2, 1.0 * cm, txt)
            canvas_obj.restoreState()

        def draw_footer_bar(canvas_obj, doc_title, org):
            canvas_obj.saveState()
            canvas_obj.setFillColorRGB(*primary)
            canvas_obj.rect(0, 0, page_w, 1.8 * cm, fill=1, stroke=0)
            canvas_obj.setFillColorRGB(1, 1, 1)
            canvas_obj.setFont("Helvetica", 8)
            canvas_obj.drawString(1 * cm, 0.7 * cm, doc_title)
            if org:
                canvas_obj.drawRightString(page_w - 1 * cm, 0.7 * cm, org)
            canvas_obj.restoreState()

        def draw_header_bar(canvas_obj, chapter_name=""):
            canvas_obj.saveState()
            canvas_obj.setFillColorRGB(*primary)
            canvas_obj.rect(0, page_h - 1.2 * cm, page_w, 1.2 * cm, fill=1, stroke=0)
            canvas_obj.setFillColorRGB(1, 1, 1)
            canvas_obj.setFont("Helvetica-Bold", 9)
            canvas_obj.drawString(1 * cm, page_h - 0.85 * cm, chapter_name)
            canvas_obj.setFont("Helvetica", 8)
            canvas_obj.drawRightString(page_w - 1 * cm, page_h - 0.85 * cm, title)
            canvas_obj.restoreState()

        page_num = 0

        # ── COVER PAGE ───────────────────────────────────────────────
        page_num += 1
        draw_image_bg(c, cover_img, page_w, page_h)
        # Dark overlay for readability
        c.setFillColorRGB(0, 0, 0, alpha=0.58)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

        # Accent stripe at top
        c.setFillColorRGB(*accent)
        c.rect(0, page_h - 0.8 * cm, page_w, 0.8 * cm, fill=1, stroke=0)

        # Title
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 38)
        c.drawCentredString(page_w / 2, page_h * 0.58, title)

        if subtitle:
            c.setFont("Helvetica-Oblique", 20)
            c.setFillColorRGB(*[min(x + 0.3, 1.0) for x in accent])
            c.drawCentredString(page_w / 2, page_h * 0.50, subtitle)

        # Divider
        c.setStrokeColorRGB(*accent)
        c.setLineWidth(2)
        c.line(page_w * 0.2, page_h * 0.44, page_w * 0.8, page_h * 0.44)

        c.setFillColorRGB(0.85, 0.85, 0.85)
        c.setFont("Helvetica", 13)
        c.drawCentredString(page_w / 2, page_h * 0.38, f"By {author}")
        if organization:
            c.setFont("Helvetica-Oblique", 11)
            c.drawCentredString(page_w / 2, page_h * 0.33, organization)

        from datetime import datetime as dt

        c.setFont("Helvetica", 10)
        c.drawCentredString(page_w / 2, page_h * 0.27, dt.now().strftime("%B %Y"))

        # Bottom accent bar
        c.setFillColorRGB(*primary)
        c.rect(0, 0, page_w, 1.5 * cm, fill=1, stroke=0)

        c.showPage()

        # ── TABLE OF CONTENTS PAGE ───────────────────────────────────
        page_num += 1
        c.setFillColorRGB(*light)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        draw_header_bar(c, "Table of Contents")
        draw_footer_bar(c, title, organization)
        draw_page_number(c, page_num)

        c.setFillColorRGB(*primary)
        c.setFont("Helvetica-Bold", 24)
        c.drawString(2 * cm, page_h - 3 * cm, "Table of Contents")

        c.setStrokeColorRGB(*accent)
        c.setLineWidth(3)
        c.line(2 * cm, page_h - 3.4 * cm, page_w - 2 * cm, page_h - 3.4 * cm)

        toc_y = page_h - 4.5 * cm
        toc_items = (
            [("Introduction", 3)]
            + [(chap.get("title", f"Chapter {i + 1}"), i + 4) for i, chap in enumerate(chapters)]
            + ([("Conclusion", len(chapters) + 4)] if conclusion else [])
        )

        for idx_t, (toc_title, pg_num_approx) in enumerate(toc_items):
            c.setFillColorRGB(*primary)
            c.setFont("Helvetica-Bold", 11)
            label = f"{idx_t + 1}.  {toc_title}"
            c.drawString(2.5 * cm, toc_y, label)
            c.setFont("Helvetica", 9)
            c.setFillColorRGB(*text_color, alpha=0.5)
            # Dots
            dots = "." * 55
            c.drawString(11 * cm, toc_y, dots)
            c.setFillColorRGB(*secondary)
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(page_w - 2.5 * cm, toc_y, str(pg_num_approx))
            toc_y -= 1.1 * cm

        c.showPage()

        # ── INTRODUCTION PAGE ─────────────────────────────────────────
        page_num += 1
        c.setFillColorRGB(*light)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        draw_header_bar(c, "Introduction")
        draw_footer_bar(c, title, organization)
        draw_page_number(c, page_num)

        # Chapter name banner (image strip at top, below header)
        banner_h = 6 * cm
        if cover_img:
            try:
                from PIL import Image as PILImage

                pil_img = PILImage.open(io.BytesIO(cover_img)).convert("RGB")
                pil_img = pil_img.resize((int(page_w), int(banner_h * 1.5)), PILImage.LANCZOS)
                tmp = io.BytesIO()
                pil_img.save(tmp, format="JPEG", quality=75)
                tmp.seek(0)
                from reportlab.lib.utils import ImageReader

                ir = ImageReader(tmp)
                c.drawImage(ir, 0, page_h - 1.2 * cm - banner_h, page_w, banner_h, preserveAspectRatio=False, mask=None)
                c.setFillColorRGB(0, 0, 0, alpha=0.5)
                c.rect(0, page_h - 1.2 * cm - banner_h, page_w, banner_h, fill=1, stroke=0)
            except Exception:
                pass

        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(page_w / 2, page_h - 1.2 * cm - banner_h + 2.5 * cm, "Introduction")

        intro_text = p.get("introduction", f"This report provides a comprehensive overview of {title}.")
        self._draw_body_text(c, intro_text, 2 * cm, page_h - 1.2 * cm - banner_h - 1.5 * cm, page_w - 4 * cm, theme)
        c.showPage()

        # ── CHAPTER PAGES ─────────────────────────────────────────────
        for chap_idx, chapter in enumerate(chapters):
            chap_title = chapter.get("title", f"Chapter {chap_idx + 1}")
            chap_content = chapter.get("content", "")
            chap_sections = chapter.get("sections", [])
            chap_bullets = chapter.get("bullets", [])
            chap_img = chapter_images[chap_idx]

            # ── Chapter title page (image + overlay) ────────────────
            page_num += 1
            draw_image_bg(c, chap_img, page_w, page_h)
            c.setFillColorRGB(0, 0, 0, alpha=0.60)
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

            # Accent top stripe
            c.setFillColorRGB(*accent)
            c.rect(0, page_h - 0.8 * cm, page_w, 0.8 * cm, fill=1, stroke=0)

            # Chapter number badge
            badge_x, badge_y = 2 * cm, page_h * 0.55
            c.setFillColorRGB(*accent)
            c.circle(badge_x, badge_y, 1.0 * cm, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 14)
            c.drawCentredString(badge_x, badge_y - 0.15 * cm, str(chap_idx + 1))

            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica", 11)
            c.drawString(3.5 * cm, badge_y + 0.3 * cm, "CHAPTER")

            c.setFont("Helvetica-Bold", 32)
            c.drawString(3.5 * cm, badge_y - 0.9 * cm, chap_title)

            c.setStrokeColorRGB(*accent)
            c.setLineWidth(2)
            c.line(3.5 * cm, badge_y - 1.3 * cm, page_w - 2 * cm, badge_y - 1.3 * cm)

            if chap_content:
                preview = chap_content[:180] + ("..." if len(chap_content) > 180 else "")
                c.setFont("Helvetica-Oblique", 11)
                c.setFillColorRGB(0.85, 0.85, 0.85)
                c.drawString(3.5 * cm, badge_y - 2.0 * cm, preview)

            c.setFillColorRGB(*primary)
            c.rect(0, 0, page_w, 1.5 * cm, fill=1, stroke=0)
            draw_page_number(c, page_num)
            c.showPage()

            # ── Chapter content page(s) ──────────────────────────────
            page_num += 1
            c.setFillColorRGB(*light)
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
            draw_header_bar(c, chap_title)
            draw_footer_bar(c, title, organization)
            draw_page_number(c, page_num)

            content_y = page_h - 2.5 * cm

            if chap_content:
                content_y = self._draw_body_text(c, chap_content, 2 * cm, content_y, page_w - 4 * cm, theme)

            # Subsections
            for sec in chap_sections:
                sec_heading = sec.get("heading", "")
                sec_content = sec.get("content", "")
                if content_y < 5 * cm:
                    c.showPage()
                    page_num += 1
                    c.setFillColorRGB(*light)
                    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
                    draw_header_bar(c, chap_title)
                    draw_footer_bar(c, title, organization)
                    draw_page_number(c, page_num)
                    content_y = page_h - 2.5 * cm

                c.setFillColorRGB(*secondary)
                c.setFont("Helvetica-Bold", 14)
                c.drawString(2 * cm, content_y, sec_heading)
                content_y -= 0.4 * cm
                c.setStrokeColorRGB(*accent)
                c.setLineWidth(1)
                c.line(2 * cm, content_y, page_w - 2 * cm, content_y)
                content_y -= 0.5 * cm

                if sec_content:
                    content_y = self._draw_body_text(c, sec_content, 2 * cm, content_y, page_w - 4 * cm, theme)

            # Bullets
            for bullet in chap_bullets:
                if content_y < 5 * cm:
                    c.showPage()
                    page_num += 1
                    c.setFillColorRGB(*light)
                    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
                    draw_header_bar(c, chap_title)
                    draw_footer_bar(c, title, organization)
                    draw_page_number(c, page_num)
                    content_y = page_h - 2.5 * cm
                c.setFillColorRGB(*accent)
                c.circle(2.3 * cm, content_y + 0.15 * cm, 0.12 * cm, fill=1, stroke=0)
                c.setFillColorRGB(*text_color)
                c.setFont("Helvetica", 10)
                c.drawString(2.7 * cm, content_y, bullet)
                content_y -= 0.65 * cm

            c.showPage()

        # ── CONCLUSION ──────────────────────────────────────────────
        if conclusion:
            page_num += 1
            c.setFillColorRGB(*light)
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
            draw_header_bar(c, "Conclusion")
            draw_footer_bar(c, title, organization)
            draw_page_number(c, page_num)

            c.setFillColorRGB(*primary)
            c.setFont("Helvetica-Bold", 26)
            c.drawString(2 * cm, page_h - 3 * cm, "Conclusion")
            c.setStrokeColorRGB(*accent)
            c.setLineWidth(3)
            c.line(2 * cm, page_h - 3.4 * cm, page_w - 2 * cm, page_h - 3.4 * cm)
            self._draw_body_text(c, conclusion, 2 * cm, page_h - 4.5 * cm, page_w - 4 * cm, theme)
            c.showPage()

        c.save()

        size_kb = out_path.stat().st_size // 1024
        logger.info("PDF saved: %s (%d KB, %d pages)", out_path, size_kb, page_num)
        await self.emit("pdf.created", {"path": str(out_path), "pages": page_num})

        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={
                "file_path": str(out_path),
                "size_kb": size_kb,
                "page_count": page_num,
                "title": title,
                "theme": theme_name,
                "people_type": people_type,
                "chapters": [c.get("title", "") for c in chapters],
                "image_source": (
                    "unsplash/pexels"
                    if os.environ.get("UNSPLASH_ACCESS_KEY") or os.environ.get("PEXELS_API_KEY")
                    else "generated_gradient"
                ),
            },
        )

    def _draw_body_text(self, c, text: str, x: float, y: float, width: float, theme: dict) -> float:
        """Draw wrapped body text and return the new y position."""
        from reportlab.lib.units import cm

        c.setFillColorRGB(*theme["text"])
        c.setFont("Helvetica", 10.5)
        line_height = 0.55 * cm
        words = text.split()
        lines: list[str] = []
        current_line = ""
        char_limit = int(width / (0.22 * cm))

        for word in words:
            test = (current_line + " " + word).strip()
            if len(test) <= char_limit:
                current_line = test
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        for line in lines:
            if y < 3 * cm:
                break
            c.drawString(x, y, line)
            y -= line_height

        return y - 0.4 * cm

    async def _export_pdf(self, context: TaskContext) -> TaskResult:
        file_path = context.parameters.get("file_path", "")
        path = Path(file_path)
        if not path.exists():
            return TaskResult(
                task_id=context.task_id,
                agent_id=self.agent_id,
                outcome=ExecutionOutcome.FAILURE,
                errors=[f"File not found: {file_path}"],
            )
        return TaskResult(
            task_id=context.task_id,
            agent_id=self.agent_id,
            outcome=ExecutionOutcome.SUCCESS,
            data={"file_path": str(path), "size_bytes": path.stat().st_size, "ready": True},
        )

    async def assess_self(self) -> dict[str, Any]:
        files = list(self._output_dir.glob("*.pdf"))
        has_unsplash = bool(os.environ.get("UNSPLASH_ACCESS_KEY"))
        has_pexels = bool(os.environ.get("PEXELS_API_KEY"))
        return {
            "output_dir": str(self._output_dir),
            "pdfs_created": len(files),
            "available_themes": list(PDF_THEMES.keys()),
            "people_types": list(PEOPLE_QUERIES.keys()),
            "image_source": "api" if (has_unsplash or has_pexels) else "gradient_fallback",
            "unsplash_configured": has_unsplash,
            "pexels_configured": has_pexels,
        }
