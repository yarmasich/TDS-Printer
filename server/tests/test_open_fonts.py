import hashlib
import json
import pytest
from PIL import ImageOps
from app.printer import _load_font, FONTS_DIR, render_label_bitmap
from app.schemas import TemplateInput
from app.models import Template

@pytest.mark.parametrize('name',['PT Sans','PT Sans Narrow','IBM Plex Mono','Carlito','Cousine','PT Serif','IBM Plex Serif','B612 Mono'])
@pytest.mark.parametrize('style',['Regular','Bold'])
def test_downloaded_fonts_are_loaded_and_rendered(name,style):
    font=_load_font(name,style,8)
    assert font.getname()[0] == name
    t=Template(name='Fonts',printer_id=1,bytes_per_row=100,height=160,
       left_left=10,left_right=380,left_top=10,left_bottom=150,
       right_left=410,right_right=790,right_top=10,right_bottom=150,
       font_name=name,font_style=style,left_pt=8,right_pt=8,auto_fit=True,letter_spacing_px=1)
    TemplateInput.model_validate(t)
    im=render_label_bitmap(t,'Кабель 123 ABC','Cable 456',scale=2)
    assert ImageOps.invert(im).getbbox()

def test_download_manifest_checksums_and_licenses():
    for entry in json.loads((FONTS_DIR/'open-fonts-sources.json').read_text()):
        data=(FONTS_DIR/entry['file']).read_bytes()
        assert hashlib.sha256(data).hexdigest()==entry['sha256']
        if entry['file'].endswith('.txt'):
            assert b'SIL OPEN FONT LICENSE' in data
