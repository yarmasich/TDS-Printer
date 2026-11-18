"""Packing-only limits and pixel transport, with no physical printer I/O."""
import base64
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import qrcode
import zxingcpp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import Field, ValidationError, model_serializer
from qrcode.util import MODE_8BIT_BYTE, QRData

from app.api import scoped_qr as qr
from app.models import Printer
from app import printer_brother
from app.qr_labels import QrLabelRequest
from app.preparation_qr_layout import PreparationLayout
from test_scoped_qr import data, packing_data, ready
from test_scoped_routing import scope


MAX_HEIGHT = round(1000 * 300 / 25.4)
MAX_ENCODED = 4 * ((150 * MAX_HEIGHT + 2) // 3)


def long_payload(scan='x' * 2000):
    image = Image.new('1', (1200, MAX_HEIGHT), 1)
    return {**packing_data(image), 'length_mm': 1000, 'scan': scan}


@pytest.mark.parametrize('scan', ['x' * 2000, 'я' * 1000])
def test_maximum_packing_request_bypasses_general_limits(scan):
    from app.packing_bitmap import PackingBitmapRequest

    body = long_payload(scan)
    request = qr.ScopedQrPreview(**body)
    plain, image, digest = qr.bitmap(request)
    assert isinstance(plain, PackingBitmapRequest)
    assert plain.scan == scan and plain.length_mm == 1000
    assert image.mode == '1' and image.size == (1200, MAX_HEIGHT)
    assert len(body['bitmap_1bpp_base64']) == qr.MAX_BITMAP_BASE64 == MAX_ENCODED == 2362200
    assert len(digest) == 64


@pytest.mark.parametrize('patch', [{'scan': 'a' * 513}, {'scan': 'я' * 257}, {'length_mm': 201}])
@pytest.mark.parametrize('kind', ['general', 'preparation', '62mm', 'nonbitmap-packing'])
def test_other_qr_requests_keep_legacy_limits(patch, kind):
    body = data()
    if kind in ('general', 'nonbitmap-packing'):
        body['media'] = 'DK-2246'
    if kind == 'nonbitmap-packing':
        body.update(reference='inventory-packing:box:one', description='')
    if kind == 'preparation':
        body['layout'] = {'version': 1, 'elements': [
            {'kind': 'text', 'text': 'A', 'x_mm': 1, 'y_mm': 1, 'width_mm': 50, 'font_mm': 5},
            {'kind': 'qr', 'x_mm': 2, 'y_mm': 12, 'size_mm': 30},
        ]}
    with pytest.raises(ValidationError):
        qr.ScopedQrPreview(**{**body, **patch})
    with pytest.raises(ValidationError):
        QrLabelRequest(**{**data(), **patch})


@pytest.mark.parametrize('change', [
    {'scan': 'a' * 2001}, {'scan': 'я' * 1001}, {'length_mm': 1000.01},
    {'length_mm': float('inf')}, {'media': 'DK-2205'},
    {'reference': 'preparation:one'}, {'reference': 'inventory-packing:box:'},
    {'reference': 'inventory-packing:box:one:two'}, {'reference': 'inventory-packing:boxes:one'},
    {'description': 'caption'}, {'description': ' '}, {'code': 'c' * 81},
    {'reference': 'inventory-packing:box:' + 'x' * 200},
    {'scan': 'line\nbreak'}, {'code': 'line\tbreak'},
    {'reference': 'inventory-packing:box:bad\x00'}, {'unexpected': True},
    {'bitmap_1bpp_base64': 'A' * (MAX_ENCODED + 1)},
    {'layout': {'version': 1, 'elements': [
        {'kind': 'text', 'text': 'A', 'x_mm': 1, 'y_mm': 1, 'width_mm': 50, 'font_mm': 5},
        {'kind': 'qr', 'x_mm': 2, 'y_mm': 12, 'size_mm': 30},
    ]}},
])
def test_extended_packing_contract_is_strict(change):
    with pytest.raises(ValidationError):
        qr.ScopedQrPreview(**{**long_payload(), **change})


def test_dedicated_contract_requires_bitmap_and_no_layout():
    from app.packing_bitmap import PackingBitmapRequest

    body = long_payload()
    del body['bitmap_1bpp_base64']
    with pytest.raises(ValidationError):
        PackingBitmapRequest(**body)
    with pytest.raises(ValidationError):
        PackingBitmapRequest(**{**long_payload(), 'layout': {'version': 1}})


def test_existing_packing_serialization_and_fingerprint_stay_unchanged():
    image = Image.new('1', (1200, 601), 1)
    body = packing_data(image)
    request = qr.ScopedQrPreview(**body)
    assert request.model_dump(mode='json') == body
    canonical = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
    assert request.model_dump_json() == canonical
    context = ['inventory-packing-bitmap-1', 2, 'DK-2246', body['reference'], body['scan'], 1200, 601]
    header = json.dumps(context, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    digest = hashlib.sha256(header + b'\n' + image.tobytes()).hexdigest()
    assert qr.bitmap(request)[2] == digest
    sent = {**body, 'expected_fingerprint': digest}
    assert qr.ScopedQrSend(**sent).model_dump(mode='json') == sent
    assert qr.RENDERER_VERSION == 'preparation-qr-1'


def test_maximum_length_actual_brother_raster_preserves_all_rows():
    body = long_payload()
    request, image, _ = qr.bitmap(qr.ScopedQrPreview(**body))
    image.putpixel((0, 0), 0)
    image.putpixel((1199, MAX_HEIGHT - 1), 0)
    device = Printer(name='QR', ip='unused', protocol='brother_ql', model='QL-1110NWBc', dpi=300)
    wire = printer_brother.build_qr_job(request, device, image=image)
    frames = wire[wire.index(b'\x67\x00\xa2'):-1]
    assert len(frames) == 165 * MAX_HEIGHT
    rows = b''.join(frames[p + 3:p + 165] for p in range(0, len(frames), 165))
    head = Image.frombytes('1', (1296, MAX_HEIGHT), rows)
    sheet = ImageOps.invert(head.convert('L')).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    assert sheet.crop((40, 0, 1240, MAX_HEIGHT)).convert('1').tobytes() == image.tobytes()


@pytest.mark.parametrize('size', [(1200, MAX_HEIGHT - 1), (1192, MAX_HEIGHT)])
def test_long_bitmap_wrong_geometry_never_reaches_raster_encoder(size, monkeypatch):
    request, _, _ = qr.bitmap(qr.ScopedQrPreview(**long_payload()))
    device = Printer(name='QR', ip='unused', protocol='brother_ql', model='QL-1110NWBc', dpi=300)
    encode = Mock()
    monkeypatch.setattr(printer_brother, 'convert', encode)
    with pytest.raises(qr.PrintError):
        printer_brother.build_qr_job(request, device, image=Image.new('1', size, 1))
    encode.assert_not_called()


def test_packing_request_cannot_render_without_supplied_bitmap():
    from app.packing_bitmap import PackingBitmapRequest

    request = PackingBitmapRequest(**long_payload())
    device = Printer(name='QR', ip='unused', protocol='brother_ql', model='QL-1110NWBc', dpi=300)
    with pytest.raises(qr.PrintError, match='supplied bitmap'):
        printer_brother.build_qr_job(request, device)


def test_long_packing_fingerprint_checked_before_any_hardware(ready, monkeypatch):
    c, h, path = ready
    raster = Mock()
    send = Mock()
    monkeypatch.setattr(qr, 'build_qr_job', raster)
    monkeypatch.setattr(qr, 'send_brother_job', send)
    body = {**long_payload(), 'expected_fingerprint': '0' * 64}
    response = c.post(path, headers={**h, 'Idempotency-Key': 'long-mismatch'}, json=body)
    assert response.status_code == 409, response.text[:500]
    assert response.json()['detail']['code'] == 'fingerprint_mismatch'
    raster.assert_not_called()
    send.assert_not_called()


def test_dense_maximum_length_preview_stays_within_json_limit_and_decodes(ready):
    c, h, path = ready
    scan = 'FH3 P-000042; Pallet: PLT-42; Project: XAI; Discipline: Fiber; Cables: '
    scan += ', '.join(f'{n:05d}' for n in range(400))
    scan = scan[:2000]
    assert len(scan.encode('utf-8')) == 2000
    image = Image.new('1', (1200, MAX_HEIGHT), 1)
    symbol = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=6)
    symbol.add_data(QRData(scan.encode(), mode=MODE_8BIT_BYTE), optimize=0)
    symbol.make(fit=True)
    qr_image = symbol.make_image().get_image().convert('1')
    assert qr_image.width <= 1128
    image.paste(qr_image, (36, 36))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(Path(qr.__file__).parents[1] / 'fonts/Carlito-Regular.ttf'), 40)
    # Spread realistic dense identifiers over the full label height.
    lines = [scan[i:i + 48] for i in range(0, len(scan), 48)]
    pitch = (MAX_HEIGHT - qr_image.height - 100) // len(lines)
    for index, line in enumerate(lines):
        draw.text((36, qr_image.height + 72 + index * pitch), line, font=font, fill=0)
    body = {**packing_data(image), 'length_mm': 1000, 'scan': scan}
    response = c.post(path + '/preview', headers=h, json=body)
    assert response.status_code == 200, response.text[:500]
    assert len(response.content) <= qr.MAX_PREVIEW_JSON == 256 * 1024
    preview = Image.open(io.BytesIO(base64.b64decode(response.json()['png_base64'])))
    assert preview.tobytes() == image.tobytes()
    decoded = zxingcpp.read_barcode(preview)
    assert decoded is not None and decoded.text == scan


def test_long_packing_send_replay_retains_full_scan_without_bitmap_in_history(ready, scope, monkeypatch):
    from sqlmodel import Session, select
    from app.models import IntegrationPrintRequest, PrintLog
    from app.packing_bitmap import PackingBitmapRequest

    c, h, path = ready
    body = long_payload('я' * 1000)
    preview = c.post(path + '/preview', headers=h, json=body)
    assert preview.status_code == 200
    body['expected_fingerprint'] = preview.json()['fingerprint']
    send = Mock(return_value='unconfirmed')
    build = Mock(wraps=printer_brother.build_qr_job)
    monkeypatch.setattr(qr, 'send_brother_job', send)
    monkeypatch.setattr(qr, 'build_qr_job', build)
    headers = {**h, 'Idempotency-Key': 'long-packing-replay'}
    result = c.post(path, headers=headers, json=body)
    assert result.status_code == 200, result.text[:500]
    assert result.json()['scan'] == body['scan']
    assert result.json()['bitmap_fingerprint'] == body['expected_fingerprint']
    assert c.post(path, headers=headers, json=body).json() == result.json()
    assert send.call_count == build.call_count == 1
    assert isinstance(build.call_args.args[0], PackingBitmapRequest)
    assert build.call_args.kwargs['image'].size == (1200, MAX_HEIGHT)
    with Session(scope[1]) as session:
        log = session.get(PrintLog, result.json()['log_id'])
        reservation = session.exec(select(IntegrationPrintRequest)).one()
        assert log.qr_scan == body['scan'] and len(log.qr_scan.encode()) == 2000
        canonical = json.dumps({'endpoint': path.removeprefix('/api/v1'),
                                'request': qr.ScopedQrSend(**body).model_dump(mode='json')},
                               sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        assert reservation.request_hash == hashlib.sha256(canonical.encode()).hexdigest()
        assert 'bitmap_1bpp_base64' not in reservation.model_dump_json()
        assert reservation.response_body == result.json()


@pytest.fixture
def historical_scoped_models():
    # Exact pre-extension inherited envelope (HEAD before this packing change).
    # The scoped endpoint already required media and length despite base defaults.
    class HistoricalPreview(QrLabelRequest):
        media: str = Field(..., pattern=r'^DK-(2205|2246)$')
        length_mm: float = Field(..., ge=30, le=200, allow_inf_nan=False)
        layout: PreparationLayout | None = None
        bitmap_1bpp_base64: str | None = Field(
            default=None, max_length=4 * ((150 * round(200 * 300 / 25.4) + 2) // 3), repr=False)

        @model_serializer(mode='wrap')
        def serialize_request(self, handler):
            fields = handler(self)
            if self.bitmap_1bpp_base64 is None:
                fields.pop('bitmap_1bpp_base64', None)
            if self.layout is None:
                fields.pop('layout', None)
            return fields

    class HistoricalSend(HistoricalPreview):
        expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')

    return HistoricalPreview, HistoricalSend


def test_scoped_field_inventory_and_general_defaults_match_historical_contract(historical_scoped_models):
    old_preview, old_send = historical_scoped_models
    assert set(qr.ScopedQrPreview.model_fields) == set(old_preview.model_fields)
    assert set(qr.ScopedQrSend.model_fields) == set(old_send.model_fields)
    assert QrLabelRequest(printer_id=2, scan='ABC').model_dump() == {
        'printer_id': 2, 'media': 'DK-2246', 'length_mm': 60, 'scan': 'ABC',
        'code': '', 'description': '', 'reference': '',
    }


@pytest.mark.parametrize('missing', ['media', 'length_mm'])
def test_scoped_required_fields_match_historical_contract(historical_scoped_models, missing):
    old_preview, old_send = historical_scoped_models
    payload = {'printer_id': 2, 'media': 'DK-2246', 'length_mm': 60, 'scan': 'ABC'}
    del payload[missing]
    for model in [old_preview, qr.ScopedQrPreview, old_send, qr.ScopedQrSend]:
        fields = dict(payload)
        if 'expected_fingerprint' in model.model_fields:
            fields['expected_fingerprint'] = '0' * 64
        with pytest.raises(ValidationError) as error:
            model(**fields)
        assert any(issue['loc'] == (missing,) and issue['type'] == 'missing'
                   for issue in error.value.errors())


@pytest.mark.parametrize('layout_version', [None, 1, 2])
@pytest.mark.parametrize('optional_fields', ['omitted', 'specified'])
@pytest.mark.parametrize('explicit_nulls', [False, True])
def test_general_and_preparation_serialization_hash_matches_historical_shape(
        historical_scoped_models, layout_version, optional_fields, explicit_nulls):
    old_preview, old_send = historical_scoped_models
    payload = {'printer_id': 2, 'media': 'DK-2205' if layout_version else 'DK-2246',
               'length_mm': 60, 'scan': ' A&B/Я-123 '}
    if optional_fields == 'specified':
        payload.update(code=' C-01 ', description=' DH30 | Кабель ', reference='preparation:test')
    if layout_version is not None:
        text = {'kind': 'text', 'text': 'A-01', 'x_mm': 1, 'y_mm': 1,
                'width_mm': 50, 'font_mm': 5}
        if layout_version == 2:
            text['align'] = 'left'
        payload['layout'] = {'version': layout_version, 'elements': [text,
            {'kind': 'qr', 'x_mm': 2, 'y_mm': 12, 'size_mm': 30}]}
    if explicit_nulls:
        payload['bitmap_1bpp_base64'] = None
        if layout_version is None:
            payload['layout'] = None
    current = qr.ScopedQrPreview(**payload)
    historical = old_preview(**payload)
    assert current.model_dump() == historical.model_dump()
    assert current.model_dump(mode='json') == historical.model_dump(mode='json')
    assert current.model_dump_json() == historical.model_dump_json()
    if optional_fields == 'omitted':
        assert all(current.model_dump()[field] == '' for field in ('code', 'description', 'reference'))
    fingerprint = '0123456789abcdef' * 4
    current_send = qr.ScopedQrSend(**payload, expected_fingerprint=fingerprint)
    historical_send = old_send(**payload, expected_fingerprint=fingerprint)
    assert current_send.model_dump_json() == historical_send.model_dump_json()
    endpoint = '/integrations/projects/00000000-0000-0000-0000-000000000001/qr-labels'
    def canonical_hash(model):
        canonical = json.dumps({'endpoint': endpoint, 'request': model.model_dump(mode='json')},
                               sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
    assert canonical_hash(current_send) == canonical_hash(historical_send)
