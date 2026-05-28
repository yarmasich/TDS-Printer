"""TSC EPL2 framing (TDP-43ME-class printers).

The header was reverse-engineered from the Android ``PandaRawPrinter.buildPrintJob``
smali for the original kiosk app:

    ^Q73,3 ^W106 ^AT ^H17 ^S2 ^E16 ^M0 ^B0 ^O0 ^R15 ~Q+0 ^D0 ^P1 ^L
    Q0,0,<bpr>,<h>
    <1-bit MSB-first raster (bpr * h bytes)>
    E

This is the EPL2 / Eltron-compatible dialect TSC printers use on TCP :9100.
"""
from __future__ import annotations

from .models import Template
from .printer import bitmap_to_mono_raster, render_label_bitmap

_HEADER_TMPL = (
    "^Q73,3\n^W106\n^AT\n^H17\n^S2\n^E16\n^M0\n^B0\n^O0\n^R15\n"
    "~Q+0\n^D0\n^P1\n^L\nQ0,0,{bpr},{h}\n"
)
_FOOTER = b"\nE\n"


def build_epl2_job(template: Template, left_text: str, right_text: str) -> bytes:
    bitmap = render_label_bitmap(template, left_text, right_text)
    raster = bitmap_to_mono_raster(bitmap, template.bytes_per_row, template.height)
    header = _HEADER_TMPL.format(
        bpr=template.bytes_per_row, h=template.height
    ).encode("ascii")
    return header + raster + _FOOTER
