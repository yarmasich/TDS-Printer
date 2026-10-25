"""Raw-TCP print engine — protocol-agnostic facade.

Pipeline:

    template + left/right text
        → PIL bitmap (printer raster coordinates) — shared
        → 1-bit MSB-first raster                  — shared
        → protocol-specific framing               — see printer_epl2 / printer_jscript
        → TCP :9100

The framing modules pick which dialect to speak (TSC EPL2 vs cab JScript).
Dispatch happens in ``build_print_job`` based on ``Printer.protocol``.
"""
from __future__ import annotations

import logging
import math
import socket
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .label_geometry import is_turn_tell_300, text_rect
from .models import Printer, Template
from .schemas import MAX_RENDER_PIXELS, PrinterInput, TemplateInput

log = logging.getLogger("tds.printer")

FONTS_DIR = Path(__file__).parent / "fonts"

_FONT_FILES: dict[tuple[str, str], str] = {
    ("Microsoft Sans Serif", "Bold"): "microsoft_sans_serif_bold.ttf",
    ("Microsoft Sans Serif", "Regular"): "microsoft_sans_serif_regular.ttf",
    ("Calibri", "Bold"): "calibri_bold.ttf",
    ("Calibri", "Regular"): "calibri_regular.ttf",
    ("PT Sans", "Regular"): "PT_Sans-Web-Regular.ttf",
    ("PT Sans", "Bold"): "PT_Sans-Web-Bold.ttf",
    ("PT Sans Narrow", "Regular"): "PT_Sans-Narrow-Web-Regular.ttf",
    ("PT Sans Narrow", "Bold"): "PT_Sans-Narrow-Web-Bold.ttf",
    ("IBM Plex Mono", "Regular"): "IBMPlexMono-Regular.ttf",
    ("IBM Plex Mono", "Bold"): "IBMPlexMono-Bold.ttf",
    ("Carlito", "Regular"): "Carlito-Regular.ttf",
    ("Carlito", "Bold"): "Carlito-Bold.ttf",
    ("Cousine", "Regular"): "Cousine-Regular.ttf",
    ("Cousine", "Bold"): "Cousine-Bold.ttf",
    ("PT Serif", "Regular"): "PT_Serif-Web-Regular.ttf",
    ("PT Serif", "Bold"): "PT_Serif-Web-Bold.ttf",
    ("IBM Plex Serif", "Regular"): "IBMPlexSerif-Regular.ttf",
    ("IBM Plex Serif", "Bold"): "IBMPlexSerif-Bold.ttf",
    ("B612 Mono", "Regular"): "B612Mono-Regular.ttf",
    ("B612 Mono", "Bold"): "B612Mono-Bold.ttf",
}

# EasyMark page is 300 DPI; thermal head uses 203 DPI for point sizes.
_FONT_DPI = 203

class PrintError(Exception):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


def _align_value(field) -> str:
    return field.value if hasattr(field, "value") else str(field)


def _load_font(name: str, style: str, size_pt: float, *, scale: float = 1.0) -> ImageFont.FreeTypeFont:
    fname = _FONT_FILES.get((name, style)) or _FONT_FILES.get((name, "Regular"))
    pt_to_px = _FONT_DPI / 72.0
    if not fname:
        return ImageFont.load_default()
    return ImageFont.truetype(
        # The legacy six-pixel minimum is in the 300-DPI design grid.
        # Scale that floor too, or small fonts shrink physically at 600 DPI.
        str(FONTS_DIR / fname), max(round(6 * scale), int(round(size_pt * pt_to_px * scale)))
    )


class _SpacedFont:
    """Use the same baseline and advances for measuring and painting tracking."""
    def __init__(self, base, spacing):
        self.base, self.spacing, self.size = base, spacing, base.size
    def getmetrics(self):
        return self.base.getmetrics()
    def glyphs(self, text):
        x = 0.0
        for char in text:
            yield char, x
            x += self.base.getlength(char) + self.spacing
    def getlength(self, text):
        return sum(self.base.getlength(c) for c in text) + max(0, len(text)-1)*self.spacing
    def getbbox(self, text, **kwargs):
        boxes = [(x+b[0], b[1], x+b[2], b[3]) for c,x in self.glyphs(text)
                 if (b := self.base.getbbox(c, anchor="ls")) and b[2] > b[0] and b[3] > b[1]]
        if not boxes:
            return (0,0,0,0)
        return (math.floor(min(b[0] for b in boxes)), 0,
                math.ceil(max(b[2] for b in boxes)), math.ceil(max(b[3] for b in boxes)-min(b[1] for b in boxes)))
    def draw(self, draw, xy, text):
        top = min((self.base.getbbox(c, anchor="ls")[1] for c in text if c.strip()), default=0)
        for char, x in self.glyphs(text):
            draw.text((xy[0]+x, xy[1]-top), char, font=self.base, fill=0, anchor="ls")


def _paint_line(draw, xy, text, font):
    if isinstance(font, _SpacedFont):
        font.draw(draw, xy, text)
    else:
        draw.text(xy, text, font=font, fill=0, anchor="lt")


def _wrap_to_width(
    text: str, font: ImageFont.FreeTypeFont, max_width: float
) -> list[str]:
    out: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            out.append("")
            continue
        words = paragraph.split(" ")
        cur = ""
        for word in words:
            candidate = f"{cur} {word}" if cur else word
            if font.getlength(candidate) <= max_width or not cur:
                cur = candidate
            else:
                out.append(cur)
                cur = word
        if cur:
            out.append(cur)
    return out


def _line_heights(
    font: ImageFont.FreeTypeFont,
    measured: list[tuple[str, tuple[int, int, int, int]]],
) -> list[int]:
    ascent, descent = font.getmetrics()
    min_h = max(ascent + descent, int(font.size * 0.85))
    return [max(bbox[3] - bbox[1], min_h) for _, bbox in measured]


def _measure_block(
    font: ImageFont.FreeTypeFont,
    text: str,
    rect_w: float,
    rect_h: float,
    scale: float = 1.0,
    line_spacing: float | None = None,
) -> tuple[list[tuple[str, tuple[int, int, int, int]]], int, float]:
    lines = _wrap_to_width(text, font, rect_w)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    measured = [
        (line, font.getbbox(line, anchor="lt") if isinstance(font, _SpacedFont) else probe.textbbox((0, 0), line, font=font, anchor="lt"))
        for line in lines
    ]
    if not measured:
        return measured, 0, 0.0
    # Pillow allocates a mask for an entire line before clipping to our canvas.
    # A long unbroken identifier at a large point size must not bypass the
    # bitmap allocation limit through that intermediate mask.
    for _, bbox in measured:
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if width > 8192 or width * height > MAX_RENDER_PIXELS:
            raise PrintError("Text line is too wide to render; shorten it or reduce the font size")

    heights = _line_heights(font, measured)
    if line_spacing is not None:
        return measured, line_spacing, sum(heights) + line_spacing * max(0, len(measured)-1)
    line_gap = max(round(2 * scale), int(font.size * 0.15))
    ink_h = sum(heights)
    n_lines = len(measured)
    if rect_h < 100 * scale and n_lines > 1:
        line_gap = max(1, min(line_gap, round(2 * scale)))
    if n_lines > 1 and ink_h < rect_h:
        line_gap = min(line_gap, max(1, int((rect_h - ink_h) / (n_lines - 1))))
    total_h = ink_h + line_gap * (n_lines - 1)
    if total_h > rect_h and n_lines > 1:
        line_gap = max(1, int((rect_h - ink_h) / (n_lines - 1)))
        total_h = ink_h + line_gap * (n_lines - 1)
    return measured, line_gap, total_h


def _validate_text_fit(
    measured: list[tuple[str, tuple[int, int, int, int]]],
    *, font: ImageFont.FreeTypeFont, rect_w: float, rect_h: float,
    h_align: str, v_align: str, y_offset: float, line_gap: int,
    total_h: float, scale_x: float,
) -> None:
    """Check glyph bounds before either page or temporary-buffer clipping.

    Use actual ink heights rather than the font's line-box height: descender
    space may extend past an edge without losing any printed pixels. Rotation
    preserves containment, so mirrored copies are checked in their own halves.
    """
    if v_align == "TOP":
        y = y_offset
    elif v_align == "BOTTOM":
        y = rect_h - total_h + y_offset
    else:
        y = max(0.0, (rect_h - total_h) / 2) + y_offset
    for (line, bbox), line_h in zip(measured, _line_heights(font, measured)):
        if line.strip():
            w = bbox[2] - bbox[0]
            x = 0 if h_align == "LEFT" else rect_w - w if h_align == "RIGHT" else (rect_w - w) / 2
            # One device pixel accommodates Pillow's fractional coordinate
            # rounding; this is not a printable overflow allowance in mm.
            if (w * scale_x > rect_w + 1 or x + bbox[0] < -1
                    or x + bbox[2] > rect_w + 1
                    or y + bbox[1] < -1 or y + bbox[3] > rect_h + 1):
                raise PrintError(
                    "Text does not fit in the print area. Reduce font size or character width, "
                    "shorten the text, or adjust text insets/offsets. "
                    "Repeated text must fit in each half of the area."
                )
        y += line_h + line_gap


def _paint_measured_lines(
    draw: ImageDraw.ImageDraw,
    measured: list[tuple[str, tuple[int, int, int, int]]],
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rect_w: float,
    rect_h: float,
    font: ImageFont.FreeTypeFont,
    h_align: str,
    v_align: str,
    y_offset: float,
    line_gap: int,
    total_h: float,
) -> None:
    if v_align == "TOP":
        cur_y = y0
    elif v_align == "BOTTOM":
        cur_y = y1 - total_h
    else:
        cur_y = y0 + max(0.0, (rect_h - total_h) / 2)
    cur_y += y_offset

    heights = _line_heights(font, measured)
    for (line, bbox), line_h in zip(measured, heights):
        w = bbox[2] - bbox[0]
        if h_align == "LEFT":
            cur_x = x0
        elif h_align == "RIGHT":
            cur_x = x1 - w
        else:
            cur_x = x0 + (rect_w - w) / 2
        _paint_line(draw, (cur_x, cur_y), line, font)
        cur_y += line_h + line_gap


def _stretch_ink_horizontal(
    im: Image.Image, scale_x: float, h_align: str = "CENTER"
) -> Image.Image:
    """Widen ink while preserving the selected horizontal anchor."""
    if scale_x <= 1.0:
        return im
    inv = Image.eval(im, lambda v: 255 - v)
    bbox = inv.getbbox()
    if not bbox:
        return im
    crop = im.crop(bbox)
    new_w = max(1, int(round(crop.width * scale_x)))
    stretched = crop.resize((new_w, crop.height), Image.Resampling.LANCZOS)
    out = Image.new("L", im.size, 255)
    if h_align == "LEFT":
        paste_x = bbox[0]
    elif h_align == "RIGHT":
        paste_x = bbox[2] - new_w
    else:
        paste_x = (im.width - new_w) // 2
    paste_y = bbox[1]
    out.paste(stretched, (paste_x, paste_y))
    return out


def _paint_lines_on_buffer(
    buf: Image.Image,
    measured: list[tuple[str, tuple[int, int, int, int]]],
    *,
    pad: int,
    rect_w: float,
    rect_h: float,
    font: ImageFont.FreeTypeFont,
    h_align: str,
    v_align: str,
    y_offset: float,
    y0: float,
    line_gap: int,
    total_h: float,
) -> None:
    if v_align == "TOP":
        cur_y = y0
    elif v_align == "BOTTOM":
        cur_y = y0 + rect_h - total_h
    else:
        cur_y = y0 + max(0.0, (rect_h - total_h) / 2)
    cur_y += y_offset

    bdraw = ImageDraw.Draw(buf)
    by = pad + (cur_y - y0)
    heights = _line_heights(font, measured)
    for (line, bbox), line_h in zip(measured, heights):
        w = bbox[2] - bbox[0]
        if h_align == "LEFT":
            bx = pad
        elif h_align == "RIGHT":
            bx = pad + (rect_w - w)
        else:
            bx = pad + (rect_w - w) / 2
        _paint_line(bdraw, (bx, by), line, font)
        by += line_h + line_gap


def _draw_text_block(
    img: Image.Image,
    text: str,
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    font: ImageFont.FreeTypeFont,
    h_align: str,
    v_align: str,
    y_offset: float,
    rotate_180: bool = False,
    scale_x: float = 1.0,
    scale: float = 1.0,
    line_spacing: float | None = None,
) -> None:
    if not text:
        return

    rect_w = x1 - x0
    rect_h = y1 - y0
    if rect_w * rect_h > MAX_RENDER_PIXELS or rect_w > 8192 or rect_h > 8192:
        raise PrintError("The text area is too large to render")
    wrap_w = rect_w / scale_x if scale_x > 1.0 else rect_w
    measured, line_gap, total_h = _measure_block(font, text, wrap_w, rect_h, scale, line_spacing)
    _validate_text_fit(
        measured, font=font, rect_w=rect_w, rect_h=rect_h,
        h_align=h_align, v_align=v_align, y_offset=y_offset,
        line_gap=line_gap, total_h=total_h, scale_x=scale_x,
    )

    if not rotate_180 and scale_x <= 1.0:
        _paint_measured_lines(
            ImageDraw.Draw(img),
            measured,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            rect_w=rect_w,
            rect_h=rect_h,
            font=font,
            h_align=h_align,
            v_align=v_align,
            y_offset=y_offset,
            line_gap=line_gap,
            total_h=total_h,
        )
        return

    pad = max(4, round(4 * scale))
    buf = Image.new(
        "L",
        (max(1, int(rect_w)) + pad * 2, max(1, int(round(rect_h))) + pad * 2),
        255,
    )
    _paint_lines_on_buffer(
        buf,
        measured,
        pad=pad,
        rect_w=rect_w,
        rect_h=rect_h,
        font=font,
        h_align=h_align,
        v_align=v_align,
        y_offset=y_offset,
        y0=y0,
        line_gap=line_gap,
        total_h=total_h,
    )
    if scale_x > 1.0:
        buf = _stretch_ink_horizontal(buf, scale_x, h_align)
    block = (
        buf.transpose(Image.Transpose.ROTATE_180) if rotate_180 else buf
    )
    img.paste(
        block,
        (int(round(x0)) - pad, int(round(y0)) - pad),
        mask=Image.eval(block, lambda v: 255 - v),
    )


def render_label_bitmap(
    template: Template, left_text: str, right_text: str, *, scale: float = 1.0
) -> Image.Image:
    """Validate persisted as well as draft settings before allocating a bitmap."""
    try:
        validated = TemplateInput.model_validate(template, from_attributes=True)
        if not math.isfinite(scale) or not 0 < scale <= 2:
            raise ValueError("Render scale must be positive and at most 2 (600 DPI)")
        width = round(validated.bytes_per_row * scale) * 8
        height = round(validated.height * scale)
        if width < 1 or height < 1 or width * height > MAX_RENDER_PIXELS:
            raise ValueError("Scaled bitmap dimensions are outside the supported limits")
        if len(left_text) > 4096 or len(right_text) > 4096:
            raise ValueError("Label text must be at most 4096 characters per side")
        return _render_label_bitmap(validated, left_text, right_text, scale=scale)
    except (ValueError, OSError, OverflowError, Image.DecompressionBombError) as exc:
        raise PrintError(f"Cannot render label: {exc}") from exc


def _render_label_bitmap(
    template: Template, left_text: str, right_text: str, *, scale: float = 1.0
) -> Image.Image:
    """Bitmap in printer raster space (preview == print).

    ``scale`` renders at N× the template's 300-DPI design grid so a higher-DPI
    head prints the same *physical* size — glyphs, rects and offsets all scale
    together, giving native (non-blocky) detail rather than a pixel-doubled
    upscale. ``scale=1.0`` is byte-for-byte identical to the un-scaled render.
    """
    bytes_per_row = round(template.bytes_per_row * scale)
    width = bytes_per_row * 8
    height = round(template.height * scale)
    img = Image.new("L", (width, height), 255)
    h_align = _align_value(template.h_align)
    v_align = _align_value(template.v_align)
    # Turn-Tell detection reads the template's native geometry — compute it
    # before scaling so a 2× render still gets the column-swap / Y-flip.
    turn_tell = is_turn_tell_300(template)
    scale_x = max(1.0, float(getattr(template, "scale_x", 1.0) or 1.0))
    mirror = bool(getattr(template, "mirror_legend", False))

    for cable_left, text, pt, y_offset in (
        (True, left_text, template.left_pt, template.left_offset),
        (False, right_text, template.right_pt, template.right_offset),
    ):
        x0, y0, x1, y1 = text_rect(template, cable_left=cable_left, scale=scale)
        y_offset = y_offset * scale

        # Mirror mode prints the same text twice, stacked HEAD-TO-HEAD at the
        # rect's centre seam, so a folded self-laminating wrap reads right-way-up
        # from both sides (the two tops meet at the fold). Bottom half head-up,
        # top half head-down. Turn-Tell bitmaps get a whole-page 180° rotation
        # later (build_jscript_job / render_label_png) which preserves the
        # head-to-head meeting — so the per-copy rotation here is independent of
        # ``turn_tell``. Off = one copy (which does follow ``turn_tell``).
        if mirror:
            ymid = (y0 + y1) / 2
            copies = ((ymid, y1, False), (y0, ymid, True))
        else:
            copies = ((y0, y1, turn_tell),)

        line_spacing = None if template.line_spacing_px is None else template.line_spacing_px * scale
        def candidate_font(size):
            loaded = _load_font(template.font_name, template.font_style, size, scale=scale)
            return _SpacedFont(loaded, template.letter_spacing_px * scale) if template.letter_spacing_px else loaded
        font = candidate_font(pt)
        if template.auto_fit and text.strip():
            if template.min_font_pt > pt:
                raise PrintError("Auto Fit minimum must not exceed either label's font size")
            sizes = [pt]
            current = pt
            while current > template.min_font_pt:
                current = max(template.min_font_pt, round(current - .5, 4))
                sizes.append(current)
            for size in sizes:
                font = candidate_font(size)
                try:
                    for cy0, cy1, _ in copies:
                        measured, gap, total = _measure_block(font, text, (x1-x0)/scale_x, cy1-cy0, scale, line_spacing)
                        _validate_text_fit(measured, font=font, rect_w=x1-x0, rect_h=cy1-cy0,
                            h_align=h_align,v_align=v_align,y_offset=y_offset,line_gap=gap,total_h=total,scale_x=scale_x)
                    break
                except PrintError:
                    if size == template.min_font_pt:
                        side = "Left" if cable_left else "Right"
                        raise PrintError(f"{side} label: Text cannot fit at the Auto Fit minimum ({size:g} pt). Shorten text, reduce spacing or lower the minimum.")

        for cy0, cy1, flip in copies:
            try:
                _draw_text_block(
                    img,
                    text,
                    x0=x0,
                    y0=cy0,
                    x1=x1,
                    y1=cy1,
                    font=font,
                    h_align=h_align,
                    v_align=v_align,
                    y_offset=y_offset,
                    rotate_180=flip,
                    scale_x=scale_x,
                    scale=scale,
                    line_spacing=line_spacing,
                )
            except PrintError as exc:
                side = "Left" if cable_left else "Right"
                raise PrintError(f"{side} label: {exc}") from exc

    return img


def bitmap_to_mono_raster(img: Image.Image, bytes_per_row: int, height: int) -> bytes:
    """Pack PIL bitmap → 1-bit MSB-first raster (row 0 = top of image)."""
    width = bytes_per_row * 8
    if img.mode != "L":
        img = img.convert("L")
    if img.size != (width, height):
        img = img.resize((width, height))

    px = img.load()
    out = bytearray(bytes_per_row * height)
    for y in range(height):
        row_base = y * bytes_per_row
        byte = 0
        bit_pos = 7
        col_byte = 0
        for x in range(width):
            if px[x, y] < 128:
                byte |= 1 << bit_pos
            bit_pos -= 1
            if bit_pos < 0:
                out[row_base + col_byte] = byte
                col_byte += 1
                byte = 0
                bit_pos = 7
    return bytes(out)


def validate_print_settings(template: Template, printer: Printer) -> Printer:
    """Shared printer/material preflight for preview and wire generation."""
    try:
        settings = PrinterInput.model_validate(printer, from_attributes=True)
        printer = Printer(**{**printer.model_dump(), **settings.model_dump()})
    except ValueError as exc:
        raise PrintError(f"Invalid printer settings: {exc}") from exc
    if template.material_sku:
        from .materials import get_material
        try:
            material = get_material(template.material_sku)
        except KeyError as exc:
            raise PrintError("Unknown material SKU; select a material from the catalog") from exc
        if not material.supported:
            raise PrintError(material.limitation)
        if printer.model == 'custom' or printer.protocol != 'jscript':
            raise PrintError("Catalog materials require a Panduit model profile in Admin → Printers")
    return printer


def build_print_job(
    template: Template, printer: Printer, left_text: str, right_text: str
) -> bytes:
    """Pick the framing dialect based on ``printer.protocol`` and return wire bytes.

    Lazy imports keep ``printer_epl2`` / ``printer_jscript`` free to import
    rendering helpers from this module without a circular dependency.
    """
    printer = validate_print_settings(template, printer)
    if printer.protocol == "jscript":
        from .printer_jscript import build_jscript_job

        return build_jscript_job(template, printer, left_text, right_text)
    if printer.protocol != "epl2":
        raise PrintError(f"Unsupported printer protocol: {printer.protocol}")
    # TSC EPL2 (TDP-43ME — the Android-ported engine).
    from .printer_epl2 import build_epl2_job

    return build_epl2_job(template, left_text, right_text)


def send_to_printer(
    ip: str, port: int, payload: bytes, *, timeout: float = 10.0,
    queue_timeout: float = 30.0,
) -> None:
    from .printer_dispatch import PrinterBusy, printer_slot

    entered = False
    try:
        with printer_slot(ip, port, wait_timeout=queue_timeout):
            entered = True
            _send_locked(ip, port, payload, timeout=timeout)
    except PrinterBusy as exc:
        raise PrintError(str(exc)) from exc
    except (OSError, ImportError) as exc:
        # Fail closed if the shared lock cannot be obtained. Socket errors are
        # already classified by _send_locked, including ambiguous sendall.
        raise PrintError(
            f"Printer coordination failed: {exc}" if entered else
            f"Printer coordination unavailable; nothing was sent: {exc}",
            uncertain=entered,
        ) from exc


def _send_locked(ip: str, port: int, payload: bytes, *, timeout: float) -> None:
    try:
        connection = socket.create_connection((ip, port), timeout=timeout)
    except (OSError, OverflowError) as exc:
        raise PrintError(f"connect to {ip}:{port} failed: {exc}") from exc
    try:
        with connection as s:
            s.sendall(payload)
    except OSError as exc:
        # sendall cannot report how many bytes reached the printer. Never
        # imply that retrying this job is guaranteed not to produce a duplicate.
        raise PrintError(f"send to {ip}:{port} failed: {exc}. Outcome unknown; check physical labels before retrying.", uncertain=True) from exc


def ping_printer(ip: str, port: int, *, timeout: float = 2.0) -> tuple[bool, Optional[float], str]:
    import time

    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            pass
    except (OSError, OverflowError) as e:
        return False, None, str(e)
    return True, round((time.perf_counter() - start) * 1000, 1), ""


def render_and_send(
    template: Template,
    printer: Printer,
    left_text: str,
    right_text: str,
    operator: str,
    reason: str,
) -> None:
    payload = build_print_job(template, printer, left_text, right_text)
    log.info(
        "print %s → %s:%d (%d bytes) %s %dx%d turn_tell=%s L=%r R=%r op=%r reason=%r",
        template.name,
        printer.ip,
        printer.port,
        len(payload),
        printer.protocol,
        template.bytes_per_row * 8,
        template.height,
        is_turn_tell_300(template),
        left_text[:40],
        right_text[:40],
        operator,
        reason,
    )
    send_to_printer(printer.ip, printer.port, payload)


def render_label_png(
    template: Template,
    left_text: str,
    right_text: str,
    *,
    crop: bool = False,
) -> bytes:
    img = render_label_bitmap(template, left_text, right_text)
    if crop:
        l = text_rect(template, cable_left=True)
        r = text_rect(template, cable_left=False)
        x0 = max(0, int(min(l[0], r[0])))
        x1 = min(img.width, int(max(l[2], r[2])))
        y0 = max(0, int(min(l[1], r[1])))
        y1 = min(img.height, int(max(l[3], r[3])))
        if x1 > x0 and y1 > y0:
            img = img.crop((x0, y0, x1, y1))
    if is_turn_tell_300(template):
        # The raw bitmap is rendered in TSC-feed orientation: each text block
        # flipped 180° and left/right swapped (see label_geometry.text_rect),
        # so it prints right-side-up after TSC's bottom-up feed. For an
        # operator looking at the schematic preview that's two upside-down
        # blocks in the wrong sides. A 180° rotation in PIL puts the bitmap
        # back into operator-readable orientation — cable-left text in the
        # visually-left label, right-side-up — without touching the print
        # path (which still consumes the original bitmap via render_label_bitmap).
        img = img.transpose(Image.Transpose.ROTATE_180)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
