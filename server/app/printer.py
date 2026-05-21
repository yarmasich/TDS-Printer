"""Print engine — port of ``PandaRawPrinter.buildPrintJob`` from the Android
smali to Python.

Pipeline (matches the existing app byte-for-byte except for the small bits
that depended on Android Graphics specifics — text metrics use PIL which
gives equivalent results for the bundled TTFs):

    template + left/right text
        ↓ PIL renders bitmap (white bg, black text)
        ↓ optional mirror_mode → rotate 180°
        ↓ bitmap_to_mono_raster → 1-bit MSB-first bytes, bytes_per_row × height
        ↓ wrap with Panduit header `^Q73,3 …\nQ0,0,<bpr>,<h>\n` and footer `\nE\n`
        ↓ raw TCP send to printer.ip:printer.port
"""
from __future__ import annotations

import logging
import socket
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .models import Printer, Template

log = logging.getLogger("tds.printer")

FONTS_DIR = Path(__file__).parent / "fonts"

# Mapping (name, style) → bundled TTF filename.
_FONT_FILES: dict[tuple[str, str], str] = {
    ("Microsoft Sans Serif", "Bold"): "microsoft_sans_serif_bold.ttf",
    ("Microsoft Sans Serif", "Regular"): "microsoft_sans_serif_regular.ttf",
    ("Calibri", "Bold"): "calibri_bold.ttf",
    ("Calibri", "Regular"): "calibri_regular.ttf",
}

DPI = 203                  # Panduit MP-series thermal print head, typical
PT_TO_PX = DPI / 72.0      # 1 pt at 203 dpi ≈ 2.82 px

# Panduit print-code preamble; copied verbatim from PandaRawPrinter.smali.
_HEADER_TMPL = (
    "^Q73,3\n^W106\n^AT\n^H17\n^S2\n^E16\n^M0\n^B0\n^O0\n^R15\n"
    "~Q+0\n^D0\n^P1\n^L\nQ0,0,{bpr},{h}\n"
)
_FOOTER = b"\nE\n"


class PrintError(Exception):
    pass


# ────────────────────────── rendering ────────────────────────────────

def _load_font(name: str, style: str, size_pt: float) -> ImageFont.FreeTypeFont:
    fname = _FONT_FILES.get((name, style)) or _FONT_FILES.get((name, "Regular"))
    if not fname:
        # last resort — DejaVu ships with Pillow on most systems
        return ImageFont.load_default()
    return ImageFont.truetype(str(FONTS_DIR / fname), max(6, int(round(size_pt * PT_TO_PX))))


def _draw_text_block(
    img: Image.Image,
    text: str,
    *,
    x0: float, y0: float, x1: float, y1: float,
    font: ImageFont.FreeTypeFont,
    h_align: str, v_align: str,
    y_offset: float,
    mirror: bool,
) -> None:
    """Render multi-line ``text`` inside ``(x0,y0)-(x1,y1)`` with the given
    alignment. When ``mirror`` is True, the block is drawn upside-down
    (rotated 180° around its own centre) — matches Android's drawMirrorText.
    """
    if not text:
        return

    lines = text.split("\n")
    # measure each line — use textbbox so descenders are included
    measured = []
    for line in lines:
        bbox = font.getbbox(line)
        measured.append((line, bbox[2] - bbox[0], bbox[3] - bbox[1]))

    line_gap = max(2, int(font.size * 0.15))
    total_h = sum(h for _, _, h in measured) + line_gap * (len(measured) - 1)

    rect_w = x1 - x0
    rect_h = y1 - y0

    if v_align == "TOP":
        cur_y = y0
    elif v_align == "BOTTOM":
        cur_y = y1 - total_h
    else:
        cur_y = y0 + (rect_h - total_h) / 2
    cur_y += y_offset

    if not mirror:
        draw = ImageDraw.Draw(img)
        for line, w, h in measured:
            if h_align == "LEFT":
                cur_x = x0
            elif h_align == "RIGHT":
                cur_x = x1 - w
            else:
                cur_x = x0 + (rect_w - w) / 2
            draw.text((cur_x, cur_y), line, font=font, fill=0)
            cur_y += h + line_gap
        return

    # Mirror: render the whole block to a side-buffer, rotate 180°,
    # paste onto the main canvas at the rect origin.
    pad = 4
    buf = Image.new("L", (max(1, int(rect_w)) + pad * 2,
                          max(1, int(rect_h)) + pad * 2), 255)
    bdraw = ImageDraw.Draw(buf)
    by = pad + (cur_y - y0)  # mirror within the block's own coord frame
    for line, w, h in measured:
        if h_align == "LEFT":
            bx = pad
        elif h_align == "RIGHT":
            bx = pad + (rect_w - w)
        else:
            bx = pad + (rect_w - w) / 2
        bdraw.text((bx, by), line, font=font, fill=0)
        by += h + line_gap
    buf = buf.rotate(180)
    img.paste(buf, (int(x0) - pad, int(y0) - pad), mask=Image.eval(buf, lambda v: 255 - v))


def render_label_bitmap(
    template: Template, left_text: str, right_text: str
) -> Image.Image:
    """Render the printable bitmap. Returns a 1-bit-ready ``L`` mode PIL image."""
    width = template.bytes_per_row * 8
    height = template.height
    img = Image.new("L", (width, height), 255)  # white

    h_align = template.h_align.value if hasattr(template.h_align, "value") else str(template.h_align)
    v_align = template.v_align.value if hasattr(template.v_align, "value") else str(template.v_align)

    # Left block
    _draw_text_block(
        img, left_text,
        x0=template.left_left + template.gap_left,
        y0=template.left_top + template.gap_top,
        x1=template.left_right - template.gap_right,
        y1=template.left_bottom - template.gap_bottom,
        font=_load_font(template.font_name, template.font_style, template.left_pt),
        h_align=h_align, v_align=v_align,
        y_offset=template.left_offset,
        mirror=template.mirror_mode,
    )
    # Right block
    _draw_text_block(
        img, right_text,
        x0=template.right_left + template.gap_left,
        y0=template.right_top + template.gap_top,
        x1=template.right_right - template.gap_right,
        y1=template.right_bottom - template.gap_bottom,
        font=_load_font(template.font_name, template.font_style, template.right_pt),
        h_align=h_align, v_align=v_align,
        y_offset=template.right_offset,
        mirror=template.mirror_mode,
    )
    return img


# ────────────────────────── raster pack ──────────────────────────────

def bitmap_to_mono_raster(img: Image.Image, bytes_per_row: int, height: int) -> bytes:
    """Pack a grayscale PIL image into 1-bit MSB-first raster bytes.

    Threshold at mid-grey: pixels darker than 128 print (bit=1), lighter
    are blank (bit=0). Output is exactly ``bytes_per_row * height`` bytes.
    """
    width = bytes_per_row * 8
    if img.mode != "L":
        img = img.convert("L")
    if img.size != (width, height):
        # resize if mismatch (shouldn't happen if template is consistent)
        img = img.resize((width, height))

    px = img.load()
    out = bytearray(bytes_per_row * height)
    for y in range(height):
        row_base = y * bytes_per_row
        byte = 0
        bit_pos = 7
        col_byte = 0
        for x in range(width):
            if px[x, y] < 128:  # dark → print
                byte |= 1 << bit_pos
            bit_pos -= 1
            if bit_pos < 0:
                out[row_base + col_byte] = byte
                col_byte += 1
                byte = 0
                bit_pos = 7
    return bytes(out)


def build_print_job(template: Template, left_text: str, right_text: str) -> bytes:
    """End-to-end: render → mono raster → wrap with Panduit header/footer."""
    bitmap = render_label_bitmap(template, left_text, right_text)
    raster = bitmap_to_mono_raster(bitmap, template.bytes_per_row, template.height)
    header = _HEADER_TMPL.format(bpr=template.bytes_per_row, h=template.height).encode("ascii")
    return header + raster + _FOOTER


# ────────────────────────── send ─────────────────────────────────────

def send_to_printer(ip: str, port: int, payload: bytes, *, timeout: float = 10.0) -> None:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.sendall(payload)
    except OSError as e:
        raise PrintError(f"send to {ip}:{port} failed: {e}") from e


def ping_printer(ip: str, port: int, *, timeout: float = 2.0) -> tuple[bool, Optional[float], str]:
    """Quick TCP-connect reachability check.

    Returns ``(ok, latency_ms, error_message)``. A successful connect means
    the printer is on the network and has port ``port`` open — for raw-9100
    printers that's a solid "online" signal. We don't send any bytes so the
    printer state isn't disturbed.
    """
    import time
    start = time.perf_counter()
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            pass
    except OSError as e:
        return False, None, str(e)
    return True, round((time.perf_counter() - start) * 1000, 1), ""


# ────────────────────────── public API ───────────────────────────────

def render_and_send(
    template: Template,
    printer: Printer,
    left_text: str,
    right_text: str,
    operator: str,
    reason: str,
) -> None:
    """Real implementation — formerly a stub. Raises ``PrintError`` on failure."""
    payload = build_print_job(template, left_text, right_text)
    log.info(
        "print %s → %s:%d (%d bytes) L=%r R=%r op=%r reason=%r",
        template.name, printer.ip, printer.port, len(payload),
        left_text[:40], right_text[:40], operator, reason,
    )
    send_to_printer(printer.ip, printer.port, payload)


def render_label_png(template: Template, left_text: str, right_text: str) -> bytes:
    """Render the same bitmap and return PNG bytes — for the preview endpoint."""
    img = render_label_bitmap(template, left_text, right_text)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
