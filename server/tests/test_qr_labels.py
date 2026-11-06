"""QR images and the actual Brother raster must carry identical pixels."""
import io
from unittest.mock import patch

import pytest
import zxingcpp
from PIL import Image, ImageChops, ImageOps
from pydantic import ValidationError

from app.models import Printer
from app.printer import PrintError, build_print_job
from app.qr_labels import QrLabelRequest, render_bitmap, preview_png
from app.printer_brother import build_qr_job
from app.schemas import PrinterInput


def request(**kw):
    return QrLabelRequest(**dict(printer_id=1, scan=' A&B/Я-123 ', code='PALLET 123', **kw))


@pytest.mark.parametrize('media,width,wire_width,quality', [('DK-2246',1200,104,True),('DK-2205',696,62,False)])
def test_preview_and_wire_are_identical_and_scan_exactly(media,width,wire_width,quality):
    req=request(media=media, description="Hall | Fiber")
    bitmap=render_bitmap(req)
    assert bitmap.mode == '1' and bitmap.width == width
    assert zxingcpp.read_barcode(bitmap).text == req.scan
    png=Image.open(io.BytesIO(preview_png(req)))
    assert ImageChops.difference(bitmap,png).getbbox() is None
    with patch.object(Image.Image,'resize', side_effect=AssertionError('no resampling')):
        wire=build_qr_job(req, Printer(name='B',ip='unused',model='QL-1110NWBc',protocol='brother_ql'))
    first=wire.index(b'\x67\x00\xa2')
    header=wire[:first]
    assert header.count(b'\x1b\x40') == 1
    assert header.count(b'\x1b\x69\x21\x01') == 1
    assert b'\x1b\x69\x53' not in header
    assert header.index(b'\x1b\x40') < header.index(b'\x1b\x69\x21\x01')
    assert header.rindex(b'\x1b\x69\x61\x01') < header.index(b'\x1b\x69\x21\x01') < header.index(b'\x1b\x69\x7a')
    info=header[header.index(b'\x1b\x69\x7a')+3:]
    assert bool(info[0] & 0x40) is quality
    assert info[0] & ~0x40 == 0x8e  # recovery and media validity bits unchanged
    assert info[1:4] == bytes([0x0a,wire_width,0])
    assert b'\x1b\x69\x41\x01' in header
    assert b'\x1b\x69\x4d\x40' in header  # auto cut
    assert wire.endswith(b'\x1a')
    rows=[]; pos=first
    while wire[pos:pos+3] == b'\x67\x00\xa2':
        rows.append(wire[pos+3:pos+165]); pos+=165
    assert pos == len(wire)-1 and len(rows) == bitmap.height
    # Raster is inverted and mirrored over the full 1296-dot head.
    full=Image.frombytes('1',(1296,len(rows)),b''.join(rows))
    full=ImageOps.invert(full.convert('L')).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    pixels=full.crop((1296-width-56,0,1296-56,len(rows))).convert('1')
    assert ImageChops.difference(bitmap,pixels).getbbox() is None
    assert zxingcpp.read_barcode(pixels).text == req.scan


@pytest.mark.parametrize('changes',[{'scan':''},{'scan':'a\n'},{'scan':'я'*257},{'media':'102'},{'length_mm':float('inf')}])
def test_invalid_requests_rejected(changes):
    with pytest.raises(ValidationError): QrLabelRequest(printer_id=1,**{'scan':'s',**changes})


def test_dense_qr_and_caption_never_shrink_or_truncate():
    with pytest.raises(PrintError,match='fit'):
        render_bitmap(QrLabelRequest(printer_id=1,media='DK-2205',length_mm=30,scan='x'*512))
    with pytest.raises(PrintError,match='fit'):
        render_bitmap(QrLabelRequest(printer_id=1,scan='s',code='W'*80))


def test_brother_profile_and_protocol_isolation():
    device=PrinterInput(name='B',ip='unused',model='QL-1110NWBc')
    assert device.protocol == 'brother_ql' and device.dpi == 300
    with pytest.raises(ValidationError): PrinterInput(name='P',ip='unused',protocol='brother_ql')
    from app.models import Template
    with pytest.raises(PrintError,match='QR'):
        build_print_job(Template(name='T',printer_id=1,bytes_per_row=20,height=100),Printer(**device.model_dump()),'a','b')
    with pytest.raises(PrintError,match='Brother'):
        build_qr_job(request(),Printer(name='P',ip='unused'))


def test_62_caption_layout_and_quiet_zone():
    from PIL import ImageFont, ImageDraw
    from pathlib import Path
    from app.qr_labels import wrap_caption
    req=QrLabelRequest(printer_id=1,media='DK-2205',scan=' A&B/Я-123 ',code='1',description='DH3556 | R.T1-T2')
    bitmap=render_bitmap(req)
    ink=ImageOps.invert(bitmap.convert('L'))
    # Three separated ink bands: prominent code, QR, readable description.
    rows=[y for y in range(bitmap.height) if ink.crop((0,y,bitmap.width,y+1)).getbbox()]
    bands=[]
    for y in rows:
        if not bands or y>bands[-1][-1]+1: bands.append([y])
        else: bands[-1].append(y)
    assert len(bands)==3
    assert len(bands[0])>=55 and len(bands[2])>=45
    import qrcode
    from qrcode.util import QRData, MODE_8BIT_BYTE
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,border=4,box_size=1)
    qr.add_data(QRData(req.scan.encode(),mode=MODE_8BIT_BYTE),optimize=0);qr.make(fit=True)
    modules=len(qr.get_matrix())
    scale=int((bitmap.width-40)*.65)//modules
    assert modules*scale<=int((bitmap.width-40)*.65)
    assert len(bands[1])==(modules-8)*scale
    assert bands[1][0]-bands[0][-1]>4*scale
    assert bands[2][0]-bands[1][-1]>4*scale
    assert zxingcpp.read_barcode(bitmap).text==req.scan
    font=ImageFont.truetype(str(Path(__file__).parents[1]/'app/fonts/Carlito-Bold.ttf'),72)
    wrapped=wrap_caption('W'*80,font,ImageDraw.Draw(bitmap),648)
    assert ''.join(wrapped)=='W'*80
    long=QrLabelRequest(printer_id=1,media='DK-2205',length_mm=100,scan='s',code='CABLE-IDENTIFIER-1234567890')
    assert zxingcpp.read_barcode(render_bitmap(long)).text=='s'


@pytest.mark.parametrize('code,description',[('1',''),('','Hall | Fiber'),('1','Hall | Fiber')])
def test_62_caption_variants(code,description):
    req=QrLabelRequest(printer_id=1,media='DK-2205',scan='exact',code=code,description=description)
    assert zxingcpp.read_barcode(render_bitmap(req)).text=='exact'


def test_62_dense_caption_and_short_label():
    req=QrLabelRequest(printer_id=1,media='DK-2205',scan='x'*512,code='1',description='Hall | Fiber')
    assert zxingcpp.read_barcode(render_bitmap(req)).text==req.scan
    with pytest.raises(PrintError,match='fit'):
        render_bitmap(req.model_copy(update={'length_mm':30}))


def test_62_blank_captions_match_captionless():
    req=QrLabelRequest(printer_id=1,media='DK-2205',scan=' exact ')
    assert render_bitmap(req).tobytes()==render_bitmap(req.model_copy(update={'code':'  ','description':'  '})).tobytes()


@pytest.mark.parametrize('media,expected',[
    ('DK-2246','3a5a7051515595b2538a5be23b8b7d50caeb37153552d951acf4e34992b8e78b'),
    ('DK-2205','691dbc2f768279cfa651a5d444e747ba2058d3e3b7eb24bbd48f3a2c55d874da'),
])
def test_unchanged_captionless_pixels(media,expected):
    import hashlib
    req=QrLabelRequest(printer_id=1,media=media,scan=' exact ')
    assert hashlib.sha256(render_bitmap(req).tobytes()).hexdigest()==expected


def test_readable_long_preparation_caption_at_standard_length():
    req=QrLabelRequest(printer_id=1,media='DK-2205',scan='FH:CABLE:12345678-1234-1234-1234-123456789012',code='123456',description='DH3556 | 16K-BE-CN-L-SPARE')
    assert zxingcpp.read_barcode(render_bitmap(req)).text==req.scan
    with pytest.raises(PrintError,match='increase label length'):
        render_bitmap(req.model_copy(update={'code':'W'*80,'description':'W'*240}))
