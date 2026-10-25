"""Minimum glyph size must retain its physical size on native 600-DPI heads."""
import pytest
from PIL import ImageOps

from app.models import Template
from app.printer import render_label_bitmap


@pytest.mark.parametrize('size_pt', [1, 1.5, 2])
@pytest.mark.parametrize('spacing', [0, 1])
def test_small_font_ink_scales_with_head_dpi(size_pt, spacing):
    template = Template(name='DPI', printer_id=1, bytes_per_row=80, height=100,
                        left_left=10, left_right=600, left_top=10, left_bottom=90,
                        left_pt=size_pt, right_pt=size_pt, letter_spacing_px=spacing)
    boxes = [ImageOps.invert(render_label_bitmap(template, 'MMMMMMMMMM', '', scale=scale)).getbbox()
             for scale in (1, 2)]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    assert 1.7 <= widths[1] / widths[0] <= 2.3
    assert 1.7 <= heights[1] / heights[0] <= 2.3
