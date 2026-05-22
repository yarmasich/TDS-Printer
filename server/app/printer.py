"""Panduit raw-TCP print engine.

Pipeline:

    template + left/right text
        → PIL bitmap (printer raster coordinates)
        → 1-bit MSB-first raster
        → Panduit job header + TCP
"""
from __future__ import annotations

import logging
import socket
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .label_geometry import is_turn_tell_300, text_rect
from .models import Printer, Template

log = logging.getLogger("tds.printer")

FONTS_DIR = Path(__file__).parent / "fonts"

_FONT_FILES: dict[tuple[str, str], str] = {
    ("Microsoft Sans Serif", "Bold"): "microsoft_sans_serif_bold.ttf",
    ("Microsoft Sans Serif", "Regular"): "microsoft_sans_serif_regular.ttf",
    ("Calibri", "Bold"): "calibri_bold.ttf",
    ("Calibri", "Regular"): "calibri_regular.ttf",
}

_HEADER_TMPL = (
    "^Q73,3\n^W106\n^AT\n^H17\n^S2\n^E16\n^M0\n^B0\n^O0\n^R15\n"
    "~Q+0\n^D0\n^P1\n^L\nQ0,0,{bpr},{h}\n"
)
_FOOTER = b"\nE\n"

# EasyMark page is 300 DPI; thermal head uses 203 DPI for point sizes.
_FONT_DPI = 203


class PrintError(Exception):
    pass


def _align_value(field) -> str:
    return field.value if hasattr(field, "value") else str(field)


def _load_font(name: str, style: str, size_pt: float) -> ImageFont.FreeTypeFont:
    fname = _FONT_FILES.get((name, style)) or _FONT_FILES.get((name, "Regular"))
    pt_to_px = _FONT_DPI / 72.0
    if not fname:
        return ImageFont.load_default()
    return ImageFont.truetype(
        str(FONTS_DIR / fname), max(6, int(round(size_pt * pt_to_px)))
    )


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
    font: ImageFont.FreeTypeFont, text: str, rect_w: float, rect_h: float
) -> tuple[list[tuple[str, tuple[int, int, int, int]]], int, float]:
    lines = _wrap_to_width(text, font, rect_w)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    measured = [
        (line, probe.textbbox((0, 0), line, font=font, anchor="lt"))
        for line in lines
    ]
    if not measured:
        return measured, 0, 0.0

    heights = _line_heights(font, measured)
    line_gap = max(2, int(font.size * 0.15))
    ink_h = sum(heights)
    n_lines = len(measured)
    if rect_h < 100 and n_lines > 1:
        line_gap = max(1, min(line_gap, 2))
    if n_lines > 1 and ink_h < rect_h:
        line_gap = min(line_gap, max(1, int((rect_h - ink_h) / (n_lines - 1))))
    total_h = ink_h + line_gap * (n_lines - 1)
    if total_h > rect_h and n_lines > 1:
        line_gap = max(1, int((rect_h - ink_h) / (n_lines - 1)))
        total_h = ink_h + line_gap * (n_lines - 1)
    return measured, line_gap, total_h


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
        draw.text((cur_x, cur_y), line, font=font, fill=0, anchor="lt")
        cur_y += line_h + line_gap


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
) -> None:
    if not text:
        return

    rect_w = x1 - x0
    rect_h = y1 - y0
    measured, line_gap, total_h = _measure_block(font, text, rect_w, rect_h)

    if not rotate_180:
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

    pad = 4
    buf = Image.new(
        "L",
        (max(1, int(rect_w)) + pad * 2, max(1, int(round(rect_h))) + pad * 2),
        255,
    )
    if v_align == "TOP":
        cur_y = y0
    elif v_align == "BOTTOM":
        cur_y = y1 - total_h
    else:
        cur_y = y0 + max(0.0, (rect_h - total_h) / 2)
    cur_y += y_offset

    bdraw = ImageDraw.Draw(buf)
    by = pad + (cur_y - y0)
    for line, bbox in measured:
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if h_align == "LEFT":
            bx = pad
        elif h_align == "RIGHT":
            bx = pad + (rect_w - w)
        else:
            bx = pad + (rect_w - w) / 2
        bdraw.text((bx, by), line, font=font, fill=0)
        by += h + line_gap

    block = buf.transpose(Image.Transpose.ROTATE_180)
    img.paste(
        block,
        (int(round(x0)) - pad, int(round(y0)) - pad),
        mask=Image.eval(block, lambda v: 255 - v),
    )


def render_label_bitmap(
    template: Template, left_text: str, right_text: str
) -> Image.Image:
    """Bitmap in printer raster space (preview == print)."""
    width = template.bytes_per_row * 8
    height = template.height
    img = Image.new("L", (width, height), 255)
    h_align = _align_value(template.h_align)
    v_align = _align_value(template.v_align)
    rotate_180 = is_turn_tell_300(template)

    for cable_left, text, pt, y_offset in (
        (True, left_text, template.left_pt, template.left_offset),
        (False, right_text, template.right_pt, template.right_offset),
    ):
        x0, y0, x1, y1 = text_rect(template, cable_left=cable_left)
        _draw_text_block(
            img,
            text,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            font=_load_font(template.font_name, template.font_style, pt),
            h_align=h_align,
            v_align=v_align,
            y_offset=y_offset,
            rotate_180=rotate_180,
        )

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


def build_print_job(template: Template, left_text: str, right_text: str) -> bytes:
    bitmap = render_label_bitmap(template, left_text, right_text)
    raster = bitmap_to_mono_raster(bitmap, template.bytes_per_row, template.height)
    header = _HEADER_TMPL.format(
        bpr=template.bytes_per_row, h=template.height
    ).encode("ascii")
    return header + raster + _FOOTER


def send_to_printer(ip: str, port: int, payload: bytes, *, timeout: float = 10.0) -> None:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.sendall(payload)
    except OSError as e:
        raise PrintError(f"send to {ip}:{port} failed: {e}") from e


def ping_printer(ip: str, port: int, *, timeout: float = 2.0) -> tuple[bool, Optional[float], str]:
    import time

    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            pass
    except OSError as e:
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
    payload = build_print_job(template, left_text, right_text)
    log.info(
        "print %s → %s:%d (%d bytes) %dx%d turn_tell=%s L=%r R=%r op=%r reason=%r",
        template.name,
        printer.ip,
        printer.port,
        len(payload),
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
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
