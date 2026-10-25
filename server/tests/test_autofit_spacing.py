import pytest
from PIL import ImageOps
from pydantic import ValidationError
from app.models import Template
from app.printer import render_label_bitmap, PrintError, _load_font, _SpacedFont, _measure_block
from app.schemas import TemplateInput

def template(**kw):
    return Template(**dict(dict(name='Fit',printer_id=1,bytes_per_row=80,height=200,
        left_left=20,left_right=300,left_top=20,left_bottom=180,
        right_left=330,right_right=610,right_top=20,right_bottom=180,
        left_pt=16,right_pt=16),**kw))

@pytest.mark.parametrize('scale',[1,2])
@pytest.mark.parametrize('mirror',[False,True])
def test_autofit_long_text_fits_both_mirror_halves(scale,mirror):
    text='Cable destination\nLong source\nRack 21'
    t=template(auto_fit=True,min_font_pt=4,mirror_legend=mirror,letter_spacing_px=1,line_spacing_px=2)
    with pytest.raises(PrintError): render_label_bitmap(template(mirror_legend=mirror),text,text,scale=scale)
    image=render_label_bitmap(t,text,text,scale=scale)
    assert ImageOps.invert(image).getbbox()
    assert t.left_pt==16 # fitting never mutates the saved maximum


def test_minimum_is_a_hard_limit():
    with pytest.raises(PrintError,match='minimum'):
        render_label_bitmap(template(auto_fit=True,min_font_pt=8),'W'*200,'')


def test_short_text_is_unchanged_when_autofit_enabled():
    assert render_label_bitmap(template(),'Hi','').tobytes()==render_label_bitmap(template(auto_fit=True),'Hi','').tobytes()


def test_spacing_measurement_matches_baseline_paint():
    font=_SpacedFont(_load_font('Calibri','Regular',12),3)
    text='Agjp 123'
    from PIL import Image, ImageDraw
    im=Image.new('L',(600,150),255)
    font.draw(ImageDraw.Draw(im),(20,20),text)
    ink=ImageOps.invert(im).getbbox(); box=font.getbbox(text)
    assert abs(ink[0]-(20+box[0]))<=1
    assert abs(ink[2]-(20+box[2]))<=1
    assert abs(ink[3]-(20+box[3]))<=1


def test_explicit_line_spacing_is_not_silently_compressed():
    font=_load_font('Calibri','Regular',6)
    _, gap, total=_measure_block(font,'A\nB',200,50,line_spacing=20)
    assert gap==20
    assert total>=20

@pytest.mark.parametrize('patch',[{'letter_spacing_px':-1},{'line_spacing_px':-1},{'min_font_pt':0},{'letter_spacing_px':float('nan')}])
def test_spacing_validation(patch):
    with pytest.raises(ValidationError): TemplateInput(bytes_per_row=80,height=200,**patch)
