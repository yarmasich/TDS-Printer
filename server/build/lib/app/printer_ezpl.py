"""Panduit TDP43ME EZPL bitmap jobs over the existing raw TCP transport.

EZPL Programmer's Manual Rev.I: ^Q (mm feed/gap), ^W (mm width),
Qx,y,width,height (binary bitmap, width in bytes), E (print one format).
No cab-specific Turn-Tell rotation or historical Android offset is applied.
Physical alignment and firmware feed precision require a hardware test.
"""
from __future__ import annotations

import math
from PIL import ImageOps
from .models import Printer, Template
from .printer import PrintError, bitmap_to_mono_raster, render_label_bitmap
from .printer_profiles import PROFILES


def prepare_ezpl_bitmap(template: Template, printer: Printer, left_text: str, right_text: str):
    if printer.model != 'TDP43ME' or printer.dpi != 300:
        raise PrintError('EZPL requires the TDP43ME 300 dpi model profile')
    bitmap = render_label_bitmap(template, left_text, right_text)
    from .calibration import apply_calibration
    bitmap = apply_calibration(bitmap, template, printer, dpi=300)
    max_dots = PROFILES['TDP43ME'][1]
    height_mm = template.media_height_mm or template.height * 25.4 / 300
    if not math.isfinite(height_mm) or not 12 <= height_mm <= 762:
        raise PrintError('TDP43ME material height must be between 12 and 762 mm')
    if not math.isfinite(template.media_gap_mm) or template.media_gap_mm < 0:
        raise PrintError('Invalid EZPL material gap')
    width_mm = min(bitmap.width, max_dots) * 25.4 / 300
    # Use the same rounded command geometry for preflight and framing.
    height_mm = round(height_mm, 3)
    width_mm = round(width_mm, 3)
    ink = ImageOps.invert(bitmap).getbbox()
    max_height = round(height_mm * 300 / 25.4)
    if ink and ink[2] > max_dots:
        raise PrintError('Text exceeds TDP43ME printable width; printing was not sent')
    if ink and ink[3] > max_height:
        raise PrintError('Text exceeds the configured material height; printing was not sent')
    # Discard only verified-white padding, never scale text to hide overflow.
    bitmap = bitmap.crop((0, 0, min(bitmap.width, max_dots), min(bitmap.height, max_height)))
    if bitmap.width % 8 or bitmap.height < 1:
        raise PrintError('Invalid EZPL raster dimensions')
    return bitmap, width_mm, height_mm


def build_ezpl_job(template: Template, printer: Printer, left_text: str, right_text: str) -> bytes:
    bitmap, width_mm, height_mm = prepare_ezpl_bitmap(template, printer, left_text, right_text)
    bpr, height = bitmap.width // 8, bitmap.height
    gap_mm = round(template.media_gap_mm, 3)
    # Zero offsets: calibration is baked into the bitmap; do not add ^R15.
    header = (
        f'^Q{height_mm:g},{gap_mm:g}\n^W{width_mm:g}\n'
        '^AT\n^H17\n^S2\n^E0\n^M0\n^B0\n^O0\n^R0\n'
        f'~Q+0\n^D0\n^P1\n^L\nQ0,0,{bpr},{height}\n'
    ).encode('ascii')
    return header + bitmap_to_mono_raster(bitmap, bpr, height) + b'\nE\n'
