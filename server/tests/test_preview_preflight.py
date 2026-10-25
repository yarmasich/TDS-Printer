"""A preview must reject native printer clipping before an operator prints."""
from io import BytesIO
from unittest.mock import patch
import pytest
from PIL import Image
from app.models import Printer, Template
from app.printer import PrintError
from app.calibration import render_preview_png

@pytest.mark.parametrize('dpi,model', [(300, 'DP4300H'), (600, 'DP4600H')])
def test_preview_checks_native_bounds_without_calibration_even_when_cropped(dpi, model):
    template = Template(name='Custom', printer_id=1, bytes_per_row=20, height=100)
    bitmap = Image.new('L', (160 * dpi // 300, 100 * dpi // 300), 255)
    bitmap.putpixel((20, 99 * dpi // 300), 0)
    blank = BytesIO(); Image.new('L', (160, 100), 255).save(blank, 'PNG')
    printer = Printer(name='P', ip='unused', model=model, dpi=dpi)
    with patch('app.printer_jscript.render_label_bitmap', return_value=bitmap), patch('app.calibration.render_label_png', return_value=blank.getvalue()):
        with pytest.raises(PrintError, match='material height'):
            render_preview_png(template, 'A', '', printer=printer, crop=True)


def test_preview_rejects_catalog_material_without_model_profile():
    template = Template(name='T', printer_id=1, material_sku='R200X150V1T', bytes_per_row=160, height=638)
    printer = Printer(name='P', ip='unused', model='custom')
    with pytest.raises(PrintError, match='Panduit model profile'):
        render_preview_png(template, '', '', printer=printer)
