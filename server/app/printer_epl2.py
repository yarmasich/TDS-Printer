"""Legacy Android EZPL wire format, retained under the historical `epl2` key.

Despite that persisted name, ^Q/^L/Q/E are EZPL commands, not EPL2.
Do not change this framing: existing installations rely on its offsets/feed.
New TDP43ME profiles use printer_ezpl with explicit geometry and bounds checks.
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
