"""Pure-Pillow local renderer. No external API calls.

Renders 1080x1080 PNG cards for three pillar templates:
  P1: warm mustard background, optional line-figure at top, serif quote, handle
  P2: deep burgundy background, bold gold serif quote, handle
  P3: mustard background, section tag + divider, serif quote, divider, handle

Config keys (under image_generator.pillow_local in config.json):
  fonts_dir (str): Path to directory with .ttf files. Defaults to fonts/
                   alongside the repo root.
  output_dir (str): Default output directory. Defaults to /tmp.
"""

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .base import ImageGenerator

# Palette constants
_MUSTARD = (240, 201, 104)
_BURGUNDY = (58, 31, 43)
_WARM_BROWN = (62, 46, 30)
_GOLD = (212, 162, 68)

_CANVAS = 1080


class PillowLocalAdapter(ImageGenerator):
    """Pillow-based local card renderer. Ships as the default adapter."""

    def __init__(self, config: dict):
        super().__init__(config)
        pg_cfg = config.get("pillow_local", {})
        fonts_override = pg_cfg.get("fonts_dir", "")
        if fonts_override:
            self._fonts_dir = Path(fonts_override).expanduser()
        else:
            # Default: fonts/ at the repo root (two levels up from this file)
            self._fonts_dir = Path(__file__).parent.parent / "fonts"
        self._output_dir = Path(pg_cfg.get("output_dir", "/tmp")).expanduser()

    @property
    def name(self) -> str:
        return "pillow_local"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _font(self, filename: str, size: int) -> ImageFont.FreeTypeFont:
        path = self._fonts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Font not found: {path}")
        return ImageFont.truetype(str(path), size=size)

    def _font_path(self, filename: str) -> str:
        path = self._fonts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Font not found: {path}")
        return str(path)

    @staticmethod
    def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list:
        """Word-wrap text so each line fits within max_width pixels."""
        words = text.split()
        lines: list = []
        current: list = []
        for word in words:
            candidate = " ".join(current + [word])
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
        return lines

    def _fit_font(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font_path: str,
        max_width: int,
        max_height: int,
        start: int = 84,
        minimum: int = 36,
    ) -> tuple:
        """Binary-search for the largest font size where text fits in both dimensions."""
        best, best_lines = minimum, []
        size = start
        while size >= minimum:
            font = ImageFont.truetype(font_path, size=size)
            lines = self._wrap(draw, text, font, max_width)
            heights = [
                draw.textbbox((0, 0), ln, font=font)[3] - draw.textbbox((0, 0), ln, font=font)[1]
                for ln in lines
            ]
            if not heights:
                size -= 2
                continue
            total_h = int(heights[0] * 1.15 * (len(lines) - 1)) + heights[-1]
            if total_h <= max_height:
                best, best_lines = size, lines
                break
            size -= 2
        if not best_lines:
            font = ImageFont.truetype(font_path, size=minimum)
            best_lines = self._wrap(draw, text, font, max_width)
        return best, best_lines

    # ------------------------------------------------------------------
    # Per-pillar renderers
    # ------------------------------------------------------------------

    def _render_p1(self, quote: str, handle: str, figure_path: Optional[str], output: str):
        img = Image.new("RGB", (_CANVAS, _CANVAS), _MUSTARD)
        draw = ImageDraw.Draw(img)

        fig_bottom_y = 120
        if figure_path and Path(figure_path).exists():
            fig = Image.open(figure_path).convert("RGBA")
            target_h = int(_CANVAS * 0.28)
            ratio = target_h / fig.height
            fig_w, fig_h = int(fig.width * ratio), target_h
            fig_resized = fig.resize((fig_w, fig_h), Image.Resampling.LANCZOS)
            x = (_CANVAS - fig_w) // 2
            img.paste(fig_resized, (x, 60), fig_resized if fig_resized.mode == "RGBA" else None)
            fig_bottom_y = 60 + fig_h

        handle_y_top = _CANVAS - 120
        text_top = fig_bottom_y + 80
        text_height = (handle_y_top - 80) - text_top
        fp = self._font_path("Cormorant-Bold.ttf")
        size, lines = self._fit_font(draw, quote, fp, int(_CANVAS * 0.78), text_height, start=92, minimum=42)
        qfont = ImageFont.truetype(fp, size=size)

        lh = [draw.textbbox((0, 0), ln, font=qfont)[3] - draw.textbbox((0, 0), ln, font=qfont)[1] for ln in lines]
        total_h = int(lh[0] * 1.2 * (len(lines) - 1)) + lh[-1] if lh else 0
        y = text_top + (text_height - total_h) // 2
        for ln in lines:
            b = draw.textbbox((0, 0), ln, font=qfont)
            x = (_CANVAS - (b[2] - b[0])) // 2
            draw.text((x, y - b[1]), ln, font=qfont, fill=_WARM_BROWN)
            y += int((b[3] - b[1]) * 1.2)

        hfont = self._font("Inter-Regular.ttf", 24)
        b = draw.textbbox((0, 0), handle, font=hfont)
        draw.text(((_CANVAS - (b[2] - b[0])) // 2, _CANVAS - 70), handle, font=hfont, fill=_WARM_BROWN)
        img.save(output, "PNG", optimize=True)

    def _render_p2(self, quote: str, handle: str, output: str):
        img = Image.new("RGB", (_CANVAS, _CANVAS), _BURGUNDY)
        draw = ImageDraw.Draw(img)

        text_top = 140
        handle_y_top = _CANVAS - 120
        text_height = (handle_y_top - 80) - text_top
        fp = self._font_path("PlayfairDisplay.ttf")
        size, lines = self._fit_font(draw, quote, fp, int(_CANVAS * 0.78), text_height, start=110, minimum=48)
        qfont = ImageFont.truetype(fp, size=size)

        lh = [draw.textbbox((0, 0), ln, font=qfont)[3] - draw.textbbox((0, 0), ln, font=qfont)[1] for ln in lines]
        total_h = int(lh[0] * 1.15 * (len(lines) - 1)) + lh[-1] if lh else 0
        y = text_top + (text_height - total_h) // 2
        for ln in lines:
            b = draw.textbbox((0, 0), ln, font=qfont)
            x = (_CANVAS - (b[2] - b[0])) // 2
            draw.text((x, y - b[1]), ln, font=qfont, fill=_GOLD)
            y += int((b[3] - b[1]) * 1.15)

        hfont = self._font("Inter-Regular.ttf", 24)
        b = draw.textbbox((0, 0), handle, font=hfont)
        draw.text(((_CANVAS - (b[2] - b[0])) // 2, _CANVAS - 70), handle, font=hfont, fill=_GOLD)
        img.save(output, "PNG", optimize=True)

    def _render_p3(self, quote: str, handle: str, output: str):
        img = Image.new("RGB", (_CANVAS, _CANVAS), _MUSTARD)
        draw = ImageDraw.Draw(img)

        tfont = self._font("Inter-Regular.ttf", 26)
        tag_text = "IA practica"
        b = draw.textbbox((0, 0), tag_text, font=tfont)
        tag_y = 110
        draw.text(((_CANVAS - (b[2] - b[0])) // 2, tag_y), tag_text, font=tfont, fill=_WARM_BROWN)
        div_y = tag_y + (b[3] - b[1]) + 28
        div_w = 100
        draw.line(
            [((_CANVAS - div_w) // 2, div_y), ((_CANVAS + div_w) // 2, div_y)],
            fill=_WARM_BROWN, width=2,
        )

        handle_y_top = _CANVAS - 120
        text_top = div_y + 80
        text_height = (handle_y_top - 80 - 80) - text_top
        fp = self._font_path("Cormorant-Bold.ttf")
        size, lines = self._fit_font(draw, quote, fp, int(_CANVAS * 0.78), text_height, start=88, minimum=42)
        qfont = ImageFont.truetype(fp, size=size)

        lh = [draw.textbbox((0, 0), ln, font=qfont)[3] - draw.textbbox((0, 0), ln, font=qfont)[1] for ln in lines]
        total_h = int(lh[0] * 1.2 * (len(lines) - 1)) + lh[-1] if lh else 0
        y = text_top + (text_height - total_h) // 2
        for ln in lines:
            b = draw.textbbox((0, 0), ln, font=qfont)
            x = (_CANVAS - (b[2] - b[0])) // 2
            draw.text((x, y - b[1]), ln, font=qfont, fill=_WARM_BROWN)
            y += int((b[3] - b[1]) * 1.2)

        second_div_y = y + 30
        draw.line(
            [((_CANVAS - div_w) // 2, second_div_y), ((_CANVAS + div_w) // 2, second_div_y)],
            fill=_WARM_BROWN, width=2,
        )

        hfont = self._font("Inter-Regular.ttf", 24)
        b = draw.textbbox((0, 0), handle, font=hfont)
        draw.text(((_CANVAS - (b[2] - b[0])) // 2, _CANVAS - 70), handle, font=hfont, fill=_WARM_BROWN)
        img.save(output, "PNG", optimize=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate(self, spec: dict) -> dict:
        """Render a card image locally using Pillow.

        Required spec keys:
            pillar (str): "P1", "P2", or "P3".
            quote (str): The quote text.
            handle (str): Handle shown at the bottom (e.g. "@your-handle").

        Optional spec keys:
            figure_path (str): Path to figure PNG (P1 only).
            output_path (str): Destination path. Defaults to
                {output_dir}/card_{pillar}.png.

        Returns:
            GenerateResult with status, adapter, image_path, width, height.
        """
        pillar = spec.get("pillar", "P2")
        quote = spec.get("quote", "")
        handle = spec.get("handle", "")
        figure_path = spec.get("figure_path")
        output_path = spec.get("output_path") or str(self._output_dir / f"card_{pillar}.png")

        try:
            if pillar == "P1":
                self._render_p1(quote, handle, figure_path, output_path)
            elif pillar == "P2":
                self._render_p2(quote, handle, output_path)
            elif pillar == "P3":
                self._render_p3(quote, handle, output_path)
            else:
                return {
                    "status": "error",
                    "adapter": self.name,
                    "error": f"Unknown pillar: {pillar!r}. Expected P1, P2, or P3.",
                }

            img = Image.open(output_path)
            return {
                "status": "ok",
                "adapter": self.name,
                "image_path": output_path,
                "width": img.width,
                "height": img.height,
                "pillar": pillar,
            }
        except Exception as exc:
            return {"status": "error", "adapter": self.name, "error": str(exc)}
