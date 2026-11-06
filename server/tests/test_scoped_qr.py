import base64
import io
from unittest.mock import Mock
import pytest
from PIL import Image
from sqlmodel import Session
from app.api import scoped_qr as qr
from app.models import Printer
from test_scoped_routing import scope, policy

@pytest.fixture
def ready(scope):
    client,engine,headers,project,_=scope
    with Session(engine) as s:
        p=s.get(Printer,2);p.dpi=300;s.add(p);s.commit()
    assert client.put(f'/api/v1/integrations/projects/{project}/policy',headers=headers,json=policy(project)).status_code==200
    return client,headers,f'/api/v1/integrations/projects/{project}/qr-labels'

def data(**changes):
    return dict(printer_id=2,media='DK-2205',length_mm=60,scan='00:ABC',code='Cable 01',description='DH30 | Fiber',reference='preparation:test',**changes)

def test_preview_send_replay_and_fingerprint(ready,monkeypatch):
    c,h,path=ready;send=Mock();monkeypatch.setattr(qr,'send_brother_job',send)
    preview=c.post(path+'/preview',headers=h,json=data());assert preview.status_code==200
    plain,image,digest=qr.bitmap(qr.ScopedQrPreview(**data()))
    decoded=Image.open(io.BytesIO(base64.b64decode(preview.json()['png_base64'])))
    assert decoded.tobytes()==image.tobytes() and digest==preview.json()['fingerprint']
    body={**data(),'expected_fingerprint':digest}
    headers={**h,'Idempotency-Key':'test-one'}
    result=c.post(path,headers=headers,json=body);assert result.status_code==200,result.text
    assert c.post(path,headers=headers,json=body).json()==result.json();assert send.call_count==1
    mismatch=c.post(path,headers={**h,'Idempotency-Key':'new'},json={**body,'expected_fingerprint':'0'*64});assert mismatch.status_code==409
    assert send.call_count==1
    conflict=c.post(path,headers=headers,json={**body,'expected_fingerprint':'1'*64})
    assert conflict.status_code==409 and conflict.json()['detail']['code']=='key_conflict'
    assert send.call_count==1

def test_assignment_and_required_media(ready,monkeypatch):
    c,h,path=ready;send=Mock();monkeypatch.setattr(qr,'send_brother_job',send)
    assert c.post(path+'/preview',headers=h,json={**data(),'printer_id':1}).status_code==403
    body=data();del body['media'];assert c.post(path+'/preview',headers=h,json=body).status_code==422
    send.assert_not_called()

@pytest.mark.parametrize('length',[30,60,200])
def test_preview_and_raster_share_bitmap(length,monkeypatch):
    from app import printer_brother
    req=qr.ScopedQrPreview(**{**data(),'length_mm':length,'description':'','code':''})
    plain,image,digest=qr.bitmap(req)
    captured=[]
    def convert(raster,images,*args,**kwargs):captured.extend(images);return b'fake'
    monkeypatch.setattr(printer_brother,'convert',convert)
    p=Printer(name='QR',ip='192.0.2.1',protocol='brother_ql',model='QL-1110NWBc',dpi=300)
    printer_brother.build_qr_job(plain,p)
    assert captured[0].tobytes()==image.tobytes()


def test_qr_status_probes_only_assigned_printer(ready,monkeypatch):
    from app import printer_reachability as reach, printer_device_status as device
    c,h,path=ready
    probe=Mock(return_value={2:True})
    monkeypatch.setattr(reach,'printer_statuses',probe)
    hardware = Mock(return_value={2: {'state': 'no_media'}})
    monkeypatch.setattr(device, 'device_statuses', hardware)
    result=c.get(path.replace('/qr-labels','/printers')+'?purpose=qr_labels&ping=true',headers=h)
    assert result.status_code==200
    assert result.json()['printers'][0]['online'] is True
    assert [p[0] for p in probe.call_args.args[0]]==[2]
    assert [p.printer_id for p in hardware.call_args.args[0]] == [2]
    assert result.json()['printers'][0]['device_status']['state'] == 'no_media'
    hardware.reset_mock()
    c.get(path.replace('/qr-labels','/printers')+'?purpose=qr_labels',headers=h)
    hardware.assert_not_called()


def test_caption_fit_is_checked_before_printing(ready,monkeypatch):
    c,h,path=ready;send=Mock();monkeypatch.setattr(qr,'send_brother_job',send)
    result=c.post(path+'/preview',headers=h,json={**data(),'code':'Cable '*100})
    assert result.status_code in (400,422)
    send.assert_not_called()

@pytest.mark.parametrize('observation',['counter_advanced','unconfirmed'])
def test_observation_replayed_without_new_hardware(ready,monkeypatch,observation):
    c,h,path=ready;send=Mock(return_value=observation);monkeypatch.setattr(qr,'send_brother_job',send)
    digest=c.post(path+'/preview',headers=h,json=data()).json()['fingerprint']
    headers={**h,'Idempotency-Key':'observed'};body={**data(),'expected_fingerprint':digest}
    result=c.post(path,headers=headers,json=body)
    assert result.status_code==200 and result.json()['print_observation']==observation
    assert result.json()['code']=='sent'
    assert c.post(path,headers=headers,json=body).json()==result.json()
    assert send.call_count==1 and send.call_args.kwargs['media']=='DK-2205'


def test_preflight_rejection_replayed_and_new_token_can_retry(ready,monkeypatch):
    c,h,path=ready
    send=Mock(side_effect=qr.PrinterNotReady('No paper'));monkeypatch.setattr(qr,'send_brother_job',send)
    digest=c.post(path+'/preview',headers=h,json=data()).json()['fingerprint']
    body={**data(),'expected_fingerprint':digest};headers={**h,'Idempotency-Key':'no-paper'}
    result=c.post(path,headers=headers,json=body)
    assert result.status_code==409 and result.json()['detail']['code']=='printer_not_ready'
    assert c.post(path,headers=headers,json=body).json()==result.json() and send.call_count==1
    send.side_effect=None;send.return_value='counter_advanced'
    assert c.post(path,headers={**h,'Idempotency-Key':'new-paper'},json=body).status_code==200
    assert send.call_count==2


def packing_data(image):
    return {**data(), 'media': 'DK-2246', 'length_mm': image.height * 25.4 / 300,
            'description': '', 'reference': 'inventory-packing:box:box-1',
            'bitmap_1bpp_base64': base64.b64encode(image.tobytes()).decode('ascii')}


def test_packing_preview_and_actual_wire(ready, monkeypatch):
    from PIL import ImageDraw, ImageOps
    import qrcode
    import zxingcpp

    c, h, path = ready
    image = Image.new('1', (1200, 601), 1)
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 5, 392, 19), fill=0)
    image.paste(qrcode.make('00:ABC').get_image(), (735, 93))
    payload = packing_data(image)
    send = Mock(return_value='unconfirmed')
    monkeypatch.setattr(qr, 'send_brother_job', send)

    preview = c.post(path + '/preview', headers=h, json=payload)
    assert preview.status_code == 200
    digest = preview.json()['fingerprint']
    png = Image.open(io.BytesIO(base64.b64decode(preview.json()['png_base64'])))
    assert png.size == image.size and png.tobytes() == image.tobytes()
    body = {**payload, 'expected_fingerprint': digest}
    headers = {**h, 'Idempotency-Key': 'packing-wire'}
    result = c.post(path, headers=headers, json=body)
    assert result.status_code == 200 and result.json()['bitmap_fingerprint'] == digest
    assert c.post(path, headers=headers, json=body).json() == result.json()
    wire = send.call_args.args[1]
    first = wire.index(b'\x67\x00\xa2')
    frames = wire[first:-1]
    assert len(frames) == 165 * image.height
    rows = b''.join(frames[pos + 3:pos + 165] for pos in range(0, len(frames), 165))
    head = Image.frombytes('1', (1296, image.height), rows)
    sheet = ImageOps.invert(head.convert('L')).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    printed = sheet.crop((40, 0, 1240, image.height)).convert('1')
    assert printed.tobytes() == image.tobytes()
    assert zxingcpp.read_barcode(printed).text == payload['scan']

    image.putpixel((0, 0), 0)
    changed = {**body, **packing_data(image)}
    conflict = c.post(path, headers=headers, json=changed)
    assert conflict.json()['detail']['code'] == 'key_conflict'
    for modified in [changed, {**body, 'reference': 'inventory-packing:pallet:p1'},
                     {**body, 'scan': 'different'}]:
        rejected = c.post(path, headers={**h, 'Idempotency-Key': modified['reference'] + modified['scan']},
                          json=modified)
        assert rejected.json()['detail']['code'] == 'fingerprint_mismatch'
    assert send.call_count == 1


@pytest.mark.parametrize('height', [600, 601, 2361, 2362])
def test_packing_geometry_and_preview_bounds(ready, height):
    c, h, path = ready
    img = Image.new('1', (1200, height), 1)
    payload = packing_data(img)
    response = c.post(path + '/preview', headers=h, json=payload)
    assert response.status_code == 200 and len(response.content) <= 256 * 1024
    png = Image.open(io.BytesIO(base64.b64decode(response.json()['png_base64'])))
    assert png.size == img.size and png.tobytes() == img.tobytes()


def test_packing_rejects_invalid_images_and_oversized_preview(ready):
    import random

    c, h, path = ready
    noisy = Image.frombytes('1', (1200, 2362), random.Random(21).randbytes(150 * 2362))
    body = packing_data(noisy)
    enc = body['bitmap_1bpp_base64']
    assert len(enc) == 472400
    for changes in [{}, {'media': 'DK-2205'}, {'reference': 'preparation:test'},
                    {'description': 'caption'}, {'bitmap_1bpp_base64': enc[:-1] + '!'},
                    {'length_mm': 60}, {'bitmap_1bpp_base64': enc[:-4]}]:
        res = c.post(path + '/preview', headers=h, json={**body, **changes})
        assert res.status_code == 400
    res = c.post(path + '/preview', headers=h, json={**body, 'bitmap_1bpp_base64': enc + 'A'})
    assert res.status_code == 422


def test_historical_send_body_serializes_without_new_field():
    old_body = {**data(), 'expected_fingerprint': '0' * 64}
    assert qr.ScopedQrSend(**old_body).model_dump(mode='json') == old_body


def test_strict_height_only_applies_to_supplied_bitmaps(monkeypatch):
    from app import printer_brother

    req = qr.QrLabelRequest(**{**data(), 'length_mm': 50.5})
    device = Printer(name='QR', ip='unused', protocol='brother_ql', model='QL-1110NWBc', dpi=300)
    # A legacy renderer returning a different height still uses its original rows.
    image = Image.new('1', (696, 598), 1)
    monkeypatch.setattr(printer_brother, 'render_bitmap', lambda req: image)
    encode = Mock(return_value=b'wire')
    monkeypatch.setattr(printer_brother, 'convert', encode)
    assert printer_brother.build_qr_job(req, device) == b'wire'
    assert encode.call_args.args[1] == [image]
    with pytest.raises(qr.PrintError, match='bitmap height'):
        printer_brother.build_qr_job(req, device, image=image)
    assert encode.call_count == 1
