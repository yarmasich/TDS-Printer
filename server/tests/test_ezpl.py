from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image
from app.models import Printer, Template
from app.schemas import PrinterInput
from app.printer import PrintError, build_print_job
from app.calibration import render_preview_png


def template(**kw):
    return Template(name='Custom', printer_id=1, bytes_per_row=160, height=200, **kw)


def printer(**kw):
    return Printer(name='TDP', ip='unused', model='TDP43ME', **kw)


def test_tdp43me_profile_forces_ezpl_300():
    p=PrinterInput(name='TDP', ip='unused', model='TDP43ME', protocol='jscript', dpi=600)
    assert (p.protocol,p.dpi)==('ezpl',300)


def test_ezpl_framing_uses_material_feed_and_binary_raster():
    bitmap=Image.new('L',(1280,200),255); bitmap.putpixel((0,0),0)
    with patch('app.printer_ezpl.render_label_bitmap',return_value=bitmap):
        job=build_print_job(template(media_height_mm=12.5,media_gap_mm=2.5),printer(),'','')
    header,raster=job.split(b'Q0,0,156,148\n',1)
    assert header.startswith(b'^Q12.5,2.5\n^W105.664\n')
    assert b'^R0\n' in header
    assert raster[0]==128 and raster[-3:]==b'\nE\n'
    assert len(raster)==156*148+3


@pytest.mark.parametrize('pixel,settings,message', [((1248,2),{},'printable width'),((1,190),{'media_height_mm':12},'material height')])
def test_ezpl_rejects_clipping_in_print_and_preview(pixel,settings,message):
    bitmap=Image.new('L',(1280,200),255); bitmap.putpixel(pixel,0)
    with patch('app.printer_ezpl.render_label_bitmap',return_value=bitmap):
        with pytest.raises(PrintError,match=message): build_print_job(template(**settings),printer(),'','')
        with pytest.raises(PrintError,match=message): render_preview_png(template(**settings),'','',printer=printer())


def test_ezpl_keeps_native_orientation_and_applies_calibration():
    from app.printer_ezpl import prepare_ezpl_bitmap
    bitmap=Image.new('L',(1280,200),255); bitmap.putpixel((10,10),0)
    t=template(material_sku='TEST')
    p=printer(protocol='ezpl',material_calibrations={'TEST':{'x_mm':0.254,'y_mm':0.254}})
    with patch('app.printer_ezpl.render_label_bitmap',return_value=bitmap):
        result,_,_=prepare_ezpl_bitmap(t,p,'','')
    assert result.getpixel((13,13))==0
    assert result.getpixel((10,10))==255


def test_ezpl_custom_profile_rejected():
    with pytest.raises(PrintError,match='TDP43ME'):
        build_print_job(template(),Printer(name='P',ip='unused',protocol='ezpl'),'','')


def test_legacy_epl2_header_unchanged():
    job=build_print_job(template(),Printer(name='P',ip='unused',protocol='epl2'),'','')
    assert job.startswith(b'^Q73,3\n^W106\n^AT\n^H17\n^S2\n^E16\n^M0\n^B0\n^O0\n^R15\n')
    assert b'Q0,0,160,200\n' in job


@pytest.mark.parametrize('height', [11.99, 762.01])
def test_ezpl_rejects_unsupported_physical_length(height):
    with pytest.raises(PrintError,match='between 12 and 762'):
        build_print_job(template(media_height_mm=height),printer(),'','')
