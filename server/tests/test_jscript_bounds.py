"""Wire geometry must never silently discard rendered ink."""
from unittest.mock import patch

import pytest
from PIL import Image

from app.models import Printer, Template
from app.printer import PrintError, build_print_job


@pytest.mark.parametrize('model,dpi', [('custom', 300), ('DP4300H', 300), ('DP4600H', 600)])
def test_implicit_height_rejects_ink_beyond_commanded_feed(model, dpi):
    scale = dpi // 300
    template = Template(name='Custom', printer_id=1, bytes_per_row=20, height=100)
    bitmap = Image.new('L', (160 * scale, 100 * scale), 255)
    bitmap.putpixel((20, 99 * scale), 0)
    with patch('app.printer_jscript.render_label_bitmap', return_value=bitmap):
        with pytest.raises(PrintError, match='material height'):
            build_print_job(template, Printer(name='P', ip='unused', protocol='jscript', model=model, dpi=dpi), 'A', '')


def test_implicit_turn_tell_height_rejects_ink_in_padded_rows():
    template = Template(name='R200X150', printer_id=1, bytes_per_row=160, height=860)
    bitmap = Image.new('L', (1280, 860), 255)
    bitmap.putpixel((100, 10), 0)  # Rotation puts ink below the 54mm carrier.
    with patch('app.printer_jscript.render_label_bitmap', return_value=bitmap):
        with pytest.raises(PrintError, match='material height'):
            build_print_job(template, Printer(name='P', ip='unused', model='DP4300H'), 'A', '')


def test_custom_width_rejects_ink_beyond_declared_width():
    template = Template(name='Custom', printer_id=1, bytes_per_row=160, height=100)
    bitmap = Image.new('L', (1280, 100), 255)
    bitmap.putpixel((1260, 20), 0)
    with patch('app.printer_jscript.render_label_bitmap', return_value=bitmap):
        with pytest.raises(PrintError, match='printable width'):
            build_print_job(template, Printer(name='P', ip='unused', protocol='jscript'), 'A', '')


def test_blank_padding_beyond_legacy_bounds_remains_allowed():
    template = Template(name='Custom', printer_id=1, bytes_per_row=160, height=100)
    bitmap = Image.new('L', (1280, 100), 255)
    bitmap.putpixel((20, 20), 0)
    with patch('app.printer_jscript.render_label_bitmap', return_value=bitmap):
        job = build_print_job(template, Printer(name='P', ip='unused', protocol='jscript'), 'A', '')
    assert b'S l1;0,0,8,11,104\r\n' in job
