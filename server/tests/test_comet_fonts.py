"""The supplied desktop fonts must work in the actual raster pipeline."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import ImageOps
from app.printer import FONTS_DIR, _FONT_FILES, _load_font, render_label_bitmap
from app.models import Template
from app.schemas import TemplateInput

CASES = [(name, style, file) for (name, style), file in _FONT_FILES.items() if file.startswith('Comet-')]

@pytest.mark.parametrize('name,style,file', CASES)
def test_supplied_font_is_loaded_and_printable(name, style, file):
    font = _load_font(name, style, 8)
    assert Path(font.path).name == file  # No silent regular/default fallback.
    template = Template(name='Font test', printer_id=1, bytes_per_row=100, height=160,
                        left_left=10, left_right=380, left_top=10, left_bottom=150,
                        right_left=410, right_right=790, right_top=10, right_bottom=150,
                        font_name=name, font_style=style, left_pt=8, right_pt=8,
                        auto_fit=True, letter_spacing_px=1)
    TemplateInput.model_validate(template)
    for scale in (1, 2):
        bitmap = render_label_bitmap(template, 'CBL# 0012-AB', 'RU03 / PORT 48', scale=scale)
        ink = ImageOps.invert(bitmap)
        assert ink.crop((0, 0, 400*scale, 160*scale)).getbbox()
        assert ink.crop((400*scale, 0, 800*scale, 160*scale)).getbbox()

def test_supplied_font_sources_and_checksums():
    sources = json.loads((FONTS_DIR/'comet-fonts-sources.json').read_text())
    assert {e['file'] for e in sources} == {file for _, _, file in CASES}
    for entry in sources:
        assert hashlib.sha256((FONTS_DIR/entry['file']).read_bytes()).hexdigest() == entry['sha256']

def test_font_menu_matches_renderer():
    root = Path(__file__).resolve().parents[2]
    catalog = json.loads((root/'frontend/src/data/fontCatalog.json').read_text())
    assert {(name, style) for name, styles in catalog.items() for style in styles} == set(_FONT_FILES)
