"""cab JScript framing (DP4300H / DP4600H — OEM rebrand of cab Produkttechnik).

Pipeline per the cab JScript Programming Manual (Edition 05/2025):

    d ASC;TDSIMG               # download an ASCII-hex 1-bit bitmap into RAM
    <WIDTH_HEX> <HEIGHT_HEX>   # 4-hex BE pixel dimensions
    80 NN <hex bytes>          # one or more "direct" scanline chunks (NN ≤ 0x7F)
    ...
    m m                        # measurement = millimetres
    J                          # job start
    S l1;0,0,<H>,<H+gap>,<W>   # label setup: gap-detected label of W×H mm
    I:img;0,0,0;TDSIMG         # place TDSIMG at (0,0) with rotation 0
    A 1                        # print 1 copy

The 1-bit MSB-first raster from ``bitmap_to_mono_raster`` is exactly what
the ASCII-hex format expects (top-to-bottom, left-to-right, bit 7 of byte 0
is the top-left pixel) — we just wrap each scanline in the ``80 NN`` "direct
data" frame the manual documents at p. 44.

Geometry assumptions for v1:

* DPI is fixed at 300 (matches DP4300H / DP4600H).
* Inter-label gap is fixed at 3 mm (typical Panduit T100X025 cassettes).

If you start seeing physical misalignment, surface DPI and gap on the
``Printer`` row instead of hard-coding them here.
"""
from __future__ import annotations

from PIL import Image

from .label_geometry import is_turn_tell_300
from .models import Template
from .printer import bitmap_to_mono_raster, render_label_bitmap

# DP4300H native resolution. Same on DP4600H.
_DPI = 300
# Distance between the trailing edge of one label and the leading edge of the
# next. Used in the S command's 4th parameter (total_height).
_GAP_MM = 3.0
# DP4300H physical printhead width per the spec sheet. cab's JScript parser
# rejects ``S … wd>printhead`` with "No label size" — TSC silently accepts
# oversize values, cab does not. Panduit Turn-Tell carriers are 4.25" (108 mm)
# but the printable rectangle on those labels still fits under the 4" head, so
# clamping ``wd`` here just drops the empty right-edge padding from the S
# declaration. The full bitmap raster is still transmitted unchanged.
_PRINTHEAD_MM = 104
# Canonical Turn-Tell carrier height per panduit.ts (4.25" × 2.125" @ 300 DPI:
# 160 BPR × 638 px = 108 × 54 mm). Some templates in the DB ship a taller
# bitmap (e.g. 860 px = 73 mm) with empty padding at the top — the text rects
# still sit on the canonical Turn-Tell ladder. cab uses ``dy`` to decide how
# far to advance after ``A 1``, so feeding it the over-padded pixel height
# makes it eject extra blank carriers between prints. Hard-code the physical
# pitch for Turn-Tell instead.
_TURN_TELL_LABEL_MM = 54
# Maximum bytes per "direct data" chunk; 0x80 is the start-byte, so up to 0x7F follow.
_MAX_DIRECT_CHUNK = 0x7F


def _px_to_mm(px: int) -> float:
    return round(px / _DPI * 25.4, 2)


def _px_to_mm_int(px: int) -> int:
    """For the S command. cab JScript in ``m m`` mode rejects decimal dots
    (",`" is reserved as the parameter separator) — examples in the manual
    are always integer mm. ±1 mm is within the gap-sensor tolerance.
    """
    return round(px / _DPI * 25.4)


def _ascii_hex_raster(raster: bytes, bytes_per_row: int, height: int) -> str:
    """Encode a 1-bit MSB-first raster as the cab ASCII-hex graphic format.

    Width/height come first as 4-hex big-endian, then each scanline becomes
    one or more ``80 NN <hex>`` direct-data chunks. CRs separate lines.
    The manual allows spaces freely; we add none to keep the wire small.
    """
    width = bytes_per_row * 8
    out: list[str] = [f"{width:04X}{height:04X}"]

    for y in range(height):
        row = raster[y * bytes_per_row : (y + 1) * bytes_per_row]
        parts: list[str] = []
        offset = 0
        remaining = bytes_per_row
        while remaining > 0:
            chunk = min(_MAX_DIRECT_CHUNK, remaining)
            parts.append(f"80{chunk:02X}{row[offset:offset + chunk].hex().upper()}")
            offset += chunk
            remaining -= chunk
        out.append("".join(parts))
    return "\r\n".join(out) + "\r\n"


def build_jscript_job(template: Template, left_text: str, right_text: str) -> bytes:
    bitmap = render_label_bitmap(template, left_text, right_text)

    # Turn-Tell templates encode the carrier "upside down" relative to cab's
    # default feed: text lives in the bottom half of the bitmap and each block
    # is flipped 180° (see label_geometry.text_rect — that's the geometry TSC
    # expects). The cleanest fix for cab is to rotate the bitmap 180° around
    # its own centre in PIL — that move (a) shifts the text into the top half
    # so it lands at the leading edge and (b) un-rotates the per-block flip.
    # We don't use JScript's ``O R`` here because that pivots around the
    # *declared* label centre, not the bitmap's, which shifts the print
    # whenever ``ho`` doesn't match the bitmap's physical height.
    if is_turn_tell_300(template):
        bitmap = bitmap.transpose(Image.Transpose.ROTATE_180)

    raster = bitmap_to_mono_raster(bitmap, template.bytes_per_row, template.height)

    width_px = template.bytes_per_row * 8
    height_px = template.height
    width_mm = min(_px_to_mm_int(width_px), _PRINTHEAD_MM)
    if is_turn_tell_300(template):
        # Bitmap may be taller than the physical carrier (operator-added
        # padding). ``dy`` drives the motor advance after ``A 1``, so we feed
        # cab the canonical Turn-Tell pitch; any raster rows past the label
        # edge are silently clipped (and are blank padding anyway).
        height_mm = _TURN_TELL_LABEL_MM
    else:
        height_mm = _px_to_mm_int(height_px)
    pitch_mm = height_mm + int(round(_GAP_MM))

    download = "d ASC;TDSIMG\r\n" + _ascii_hex_raster(
        raster, template.bytes_per_row, height_px
    )
    job = (
        "m m\r\n"
        "J\r\n"
        f"S l1;0,0,{height_mm},{pitch_mm},{width_mm}\r\n"
        "I:img;0,0,0;TDSIMG\r\n"
        "A 1\r\n"
    )
    return (download + job).encode("ascii")
