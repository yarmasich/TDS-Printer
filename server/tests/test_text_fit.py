"""Preflight must reject text that would silently clip on the printed label."""
import pytest
from PIL import ImageChops
from app.models import Template
from app.printer import PrintError, render_label_bitmap, render_label_png


def label(**patch):
    values = dict(name='Fit', printer_id=1, bytes_per_row=80, height=160,
                  left_left=20, left_right=300, left_top=20, left_bottom=140,
                  right_left=330, right_right=610, right_top=20, right_bottom=140,
                  left_pt=12, right_pt=12)
    return Template(**{**values, **patch})


@pytest.mark.parametrize('scale', [1, 2])
@pytest.mark.parametrize('patch,text', [
    ({}, 'W' * 30),
    ({}, 'Line\n' * 12),
    ({'left_offset': 130}, 'Cable'),
    ({'left_offset': -130}, 'Cable'),
    ({'mirror_legend': True}, 'Line\nLine\nLine'),
    ({'scale_x': 1.5}, 'W' * 8),
])
def test_overflow_is_rejected_before_clipping(scale, patch, text):
    with pytest.raises(PrintError, match='Left label.*fit'):
        render_label_bitmap(label(**patch), text, '', scale=scale)


def test_right_error_uses_operator_side():
    with pytest.raises(PrintError, match='Right label.*fit'):
        render_label_png(label(), '', 'W' * 30)


@pytest.mark.parametrize('align', ['LEFT', 'CENTER', 'RIGHT'])
@pytest.mark.parametrize('vertical', ['TOP', 'CENTER', 'BOTTOM'])
@pytest.mark.parametrize('mirror', [False, True])
def test_valid_ink_stays_inside_both_print_areas(align, vertical, mirror):
    t = label(h_align=align, v_align=vertical, mirror_legend=mirror, scale_x=1.12)
    img = render_label_bitmap(t, 'Cable', 'Cable')
    for x0, x1 in [(20, 300), (330, 610)]:
        box = ImageChops.invert(img.crop((x0 - 5, 0, x1 + 5, 160))).getbbox()
        assert box is not None
        assert box[0] >= 4 and box[2] <= x1 - x0 + 6
        assert box[1] >= 19 and box[3] <= 141


def test_nonempty_text_cannot_print_in_unconfigured_side():
    with pytest.raises(PrintError, match='Right label.*fit'):
        render_label_bitmap(label(right_left=0, right_right=0, right_top=0, right_bottom=0), '', 'Cable')


@pytest.mark.parametrize('scale', [1, 2])
def test_turn_tell_110_percent_mirror_with_negative_offset_still_fits(scale):
    from app.materials import get_material, template_geometry
    t = Template(name='R200X150', printer_id=1,
                 **template_geometry(get_material('R200X150V1T')))
    t.left_pt = t.right_pt = 6
    t.scale_x = 1.1
    t.mirror_legend = True
    t.left_offset = t.right_offset = -2
    image = render_label_bitmap(t, 'TEXT+12345', 'TEXT+12345', scale=scale)
    assert ImageChops.invert(image).getbbox() is not None
