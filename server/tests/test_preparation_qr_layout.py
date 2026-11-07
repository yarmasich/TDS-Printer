import base64
import hashlib
import io
import json
from unittest.mock import Mock

import pytest
import zxingcpp
from PIL import Image, ImageOps
from pydantic import ValidationError

from app.api import scoped_qr as qr
from app.preparation_qr_layout import APP, PreparationLayout, TextElement
from test_scoped_qr import ready, data
from test_scoped_routing import scope


def layout():
    return {'version': 1, 'elements': [
        {'kind': 'text', 'x_mm': 1, 'y_mm': 1, 'width_mm': 53, 'font_mm': 5, 'text': 'A-01 • Кабель'},
        {'kind': 'qr', 'x_mm': 2, 'y_mm': 12, 'size_mm': 30},
    ]}


@pytest.mark.parametrize('alignment', ['left', 'center', 'right'])
def test_custom_preview_matches_wire_and_rejects_stale_digests(ready, monkeypatch, alignment):
    c, h, path = ready
    send = Mock(return_value='unconfirmed')
    monkeypatch.setattr(qr, 'send_brother_job', send)
    body = {**data(), 'code': '', 'description': '', 'scan': ' A&B/Я-123 ', 'layout': layout()}
    if alignment != 'left':
        body['layout']['version'] = 2
        body['layout']['elements'][0]['align'] = alignment
    preview = c.post(path + '/preview', headers=h, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()['layout_version'] == body['layout']['version']
    png = Image.open(io.BytesIO(base64.b64decode(preview.json()['png_base64'])))
    assert png.size == (696, 709)
    assert zxingcpp.read_barcode(png).text == body['scan']
    body['expected_fingerprint'] = preview.json()['fingerprint']
    headers = {**h, 'Idempotency-Key': 'custom-print'}
    printed = c.post(path, headers=headers, json=body)
    assert printed.status_code == 200 and printed.json()['layout_version'] == body['layout']['version']
    assert c.post(path, headers=headers, json=body).json() == printed.json()

    # Decode the uncompressed Brother raster frames passed to the mock transport.
    wire = send.call_args.args[1]
    frames = wire[wire.index(b'\x67\x00\xa2'):-1]
    assert len(frames) == 165 * png.height
    rows = b''.join(frames[i + 3:i + 165] for i in range(0, len(frames), 165))
    head = Image.frombytes('1', (1296, png.height), rows)
    sheet = ImageOps.invert(head.convert('L')).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    actual = sheet.crop((544, 0, 1240, png.height)).convert('1')
    assert actual.tobytes() == png.tobytes()

    changed = layout()
    # A wider field has identical ink but a distinct layout.
    changed['elements'][0]['width_mm'] = 54
    for index, change in enumerate([{'reference': 'preparation:other'}, {'scan': 'different'}, {'layout': changed}]):
        stale = c.post(path, headers={**h, 'Idempotency-Key': f'stale-{index}'}, json={**body, **change})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'fingerprint_mismatch'
    assert send.call_count == 1


@pytest.mark.parametrize(('change', 'hint'), [
    ({'media': 'DK-2246'}, '62 mm'),
    ({'reference': 'inventory-packing:box:abc'}, 'Preparation'),
    ({'bitmap_1bpp_base64': 'AA=='}, 'without a packing bitmap'),
    ({'text': 'line\nbreak'}, 'single line'),
    ({'text': '😀'}, 'font'),
    ({'text': 'a' * 200}, 'Widen'),
    ({'text': 'foo', 'x_mm': 20}, 'width'),
    ({'qr': {'x_mm': 39}}, 'inside'),
    ({'qr': {'y_mm': 32}}, 'inside'),
    ({'qr': {'y_mm': 1}}, 'overlapping'),
    ({'qr': {'size_mm': 8}}, 'QR size'),
])
def test_layout_errors_never_contact_hardware(ready, monkeypatch, change, hint):
    c, h, path = ready
    send = Mock()
    monkeypatch.setattr(qr, 'send_brother_job', send)
    payload = {**data(), 'layout': layout()}
    if 'text' in change:
        payload['layout']['elements'][0].update(change)
    elif 'qr' in change:
        payload['layout']['elements'][1].update(change['qr'])
    else:
        payload.update(change)
    preview = c.post(path + '/preview', headers=h, json=payload)
    assert preview.status_code == 422 and preview.json()['detail']['code'] == 'layout_invalid'
    assert hint in preview.json()['detail']['message']
    sent = c.post(path, headers={**h, 'Idempotency-Key': 'invalid'},
                  json={**payload, 'expected_fingerprint': '0' * 64})
    assert sent.status_code == 422 and sent.json()['detail'] == preview.json()['detail']
    send.assert_not_called()


@pytest.mark.parametrize(('name', 'low', 'high'), [
    ('x_mm', 0, 58.9), ('y_mm', 0, 200), ('width_mm', 4, 58.9), ('font_mm', 2, 12), ('size_mm', 8, 55),
])
def test_numeric_bounds_and_grid(name, low, high):
    from app.preparation_qr_layout import QrElement

    el = layout()['elements'][1 if name == 'size_mm' else 0]
    schema = QrElement if name == 'size_mm' else TextElement
    for valid in [low, high, low + .1]:
        assert schema(**{**el, name: valid})
    for invalid in [round(low - .1, 1), round(high + .1, 1), low + .01, str(low), True, float('nan'), float('inf')]:
        with pytest.raises(ValidationError):
            schema(**{**el, name: invalid})


def test_text_and_element_bounds():
    text, qr_el = layout()['elements']
    for n in [1, 200]:
        assert TextElement(**{**text, 'text': 'я' * n})
    for n in [0, 201]:
        with pytest.raises(ValidationError):
            TextElement(**{**text, 'text': 'я' * n})
    for count in [1, 12]:
        assert PreparationLayout(version=1, elements=[qr_el] + [text] * count)
    for elements in [[qr_el], [text, text], [qr_el, qr_el], [qr_el] + [text] * 13]:
        with pytest.raises(ValidationError):
            PreparationLayout(version=1, elements=elements)


def test_legacy_preparation_golden_and_font_coverage():
    payload = data()
    request = qr.ScopedQrPreview(**payload)
    plain, _, digest = qr.bitmap(request)
    assert plain.model_dump(mode='json') == request.model_dump(mode='json') == payload
    assert request.model_dump_json() == ('{"printer_id":2,"media":"DK-2205","length_mm":60.0,"scan":"00:ABC",'
                                         '"code":"Cable 01","description":"DH30 | Fiber","reference":"preparation:test"}')
    assert digest == '5fa5f533413e5f2d872683959eed65201a877b150459eed7181142aa2d7252c9'
    send = qr.ScopedQrSend(**payload, expected_fingerprint=digest)
    endpoint = '/integrations/projects/00000000-0000-0000-0000-000000000001/qr-labels'
    canonical = json.dumps({'endpoint': endpoint, 'request': send.model_dump(mode='json')},
                           sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    assert hashlib.sha256(canonical.encode()).hexdigest() == '601bac73a673fcefc86fd761ad316286f8a6565277dc7d1dbb02b5e01be7cb08'
    coverage = json.loads((APP / 'data/carlito-coverage.json').read_text())
    assert hashlib.sha256((APP / 'fonts' / coverage['font']).read_bytes()).hexdigest() == coverage['sha256']


def test_content_size_limit_applies_to_compact_utf8(monkeypatch):
    from app import preparation_qr_layout as renderer

    model = PreparationLayout(**layout())
    size = len(model.model_dump_json().encode('utf-8'))
    assert renderer.MAX_LAYOUT_BYTES == 16 * 1024
    for limit in [size, size + 1]:
        monkeypatch.setattr(renderer, 'MAX_LAYOUT_BYTES', limit)
        assert PreparationLayout(**layout())
    monkeypatch.setattr(renderer, 'MAX_LAYOUT_BYTES', size - 1)
    with pytest.raises(ValidationError, match='16 KiB'):
        PreparationLayout(**layout())


def test_touching_text_boxes_are_allowed_but_intersecting_ink_is_rejected():
    payload = layout()
    text = payload['elements'][0]
    text.update(text='A', width_mm=4, font_mm=2)
    payload['elements'].append({**text, 'x_mm': 5})
    request = qr.ScopedQrPreview(**data(), layout=payload)
    assert qr.bitmap(request)[1].mode == '1'
    payload['elements'][2]['x_mm'] = 1
    with pytest.raises(qr.LayoutError, match='overlapping'):
        qr.bitmap(qr.ScopedQrPreview(**data(), layout=payload))


def test_left_alignment_keeps_historical_custom_hash_and_request():
    original = layout()
    expected = qr.ScopedQrPreview(**data(), layout=original)
    explicit = layout()
    explicit['elements'][0]['align'] = 'left'
    request = qr.ScopedQrPreview(**data(), layout=explicit)
    assert request.model_dump_json() == expected.model_dump_json()
    assert 'align' not in request.model_dump_json()
    assert qr.bitmap(request)[2] == '272caec4f6d4ad1db00afdd105682473422e1467abada56aa9227e0a7b541508'


@pytest.mark.parametrize('alignment', ['left', 'center', 'right'])
def test_alignment_places_ink_within_field(alignment):
    from PIL import ImageDraw, ImageFont
    from app.preparation_qr_layout import dots

    template = layout()
    template['version'] = 2
    el = template['elements'][0]
    el.update(text='ABC', align=alignment)
    _, image, _ = qr.bitmap(qr.ScopedQrPreview(**data(), layout=template))
    ink = ImageOps.invert(image.convert('L')).crop((0, 0, image.width, dots(10)))
    left, top, right, bottom = ink.getbbox()
    font = ImageFont.truetype(str(APP / 'fonts/Carlito-Regular.ttf'), dots(el['font_mm']))
    text_box = ImageDraw.Draw(image).textbbox((0, 0), el['text'], font=font, anchor='lt')
    spare = dots(el['width_mm']) - (text_box[2] - text_box[0])
    expected_offset = {'left': 0, 'center': spare // 2, 'right': spare}[alignment]
    # Compare complete raster to left to include glyph bearing, not merely its box.
    el['align'] = 'left'
    _, original, _ = qr.bitmap(qr.ScopedQrPreview(**data(), layout=template))
    original_ink = ImageOps.invert(original.convert('L')).crop((0, 0, image.width, dots(10)))
    assert left == original_ink.getbbox()[0] + expected_offset
    assert right <= dots(el['x_mm']) + dots(el['width_mm'])
    assert ink.crop((left, top, right, bottom)).tobytes() == original_ink.crop(original_ink.getbbox()).tobytes()


def test_alignment_version_and_unknown_values_rejected():
    for align in ['center', 'right', 'justify']:
        template = layout()
        template['elements'][0]['align'] = align
        with pytest.raises(ValidationError):
            PreparationLayout(**template)
    template['version'] = 2
    with pytest.raises(ValidationError):
        PreparationLayout(**template)


def test_aligned_ink_overlap_checked_at_its_shifted_position():
    template = layout()
    template['version'] = 2
    el = template['elements'][0]
    el.update(text='X', align='right', y_mm=12)
    # Wide text box overlaps QR on the left, but the actual ink is at the right.
    assert qr.bitmap(qr.ScopedQrPreview(**data(), layout=template))[1].mode == '1'
    el['align'] = 'center'
    with pytest.raises(qr.LayoutError, match='overlapping'):
        qr.bitmap(qr.ScopedQrPreview(**data(), layout=template))
