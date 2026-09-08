"""Printer/template boundary regressions; all storage and rendering stay local."""
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import printers, templates, print as print_api
from app.auth_admin import require_admin
from app.db import get_session
from app.models import DataHall, Discipline, Printer, PrintLog, Project, Template
from app.printer import PrintError, build_print_job, render_label_bitmap, render_label_png


@pytest.fixture
def render_api():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def enable_fks(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Printer(id=1, name='Desk', ip='127.0.0.1'))
        session.commit()
    app = FastAPI()
    app.include_router(templates.router)
    app.include_router(printers.router)
    app.include_router(print_api.router)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[require_admin] = lambda: 'test'
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, engine
    engine.dispose()


def template_payload(**patch):
    return dict(name='Label', printer_id=1, bytes_per_row=80, height=100,
                left_left=20, left_right=300, left_top=10, left_bottom=90,
                left_pt=12, **patch)


@pytest.mark.parametrize('patch', [
    {'h_align': 'DIAGONAL'}, {'v_align': 'DIAGONAL'}, {'height': -1},
    {'bytes_per_row': 0}, {'height': 1000000}, {'left_pt': 0},
    {'scale_x': 1000000}, {'font_name': 'Unknown'}, {'font_style': 'Unknown'},
    {'left_right': 10}, {'left_bottom': 5}, {'gap_left': 300},
])
def test_invalid_template_is_rejected_before_commit(render_api, patch):
    client, engine = render_api
    payload = {**template_payload(), **patch}
    response = client.post('/api/templates', json=payload)
    assert response.status_code == 422, response.text
    with Session(engine) as session:
        assert session.exec(select(Template)).all() == []


@pytest.mark.parametrize('route', ['/api/templates', '/api/print/preview-draft', '/api/print/test'])
def test_nonfinite_geometry_rejected(render_api, route):
    import json
    client, _ = render_api
    payload = {**template_payload(), 'left_top': float('nan')}
    if route != '/api/templates':
        payload = {'template': payload, 'printer_id': 1}
    response = client.post(route, content=json.dumps(payload), headers={'Content-Type': 'application/json'})
    assert response.status_code == 422, response.text


@pytest.mark.parametrize('patch', [
    {'protocol': 'JScript'}, {'dpi': -1}, {'dpi': 0}, {'port': -1},
    {'port': 65536}, {'ip': ''}, {'name': ''},
])
def test_invalid_printer_is_rejected(render_api, patch):
    client, _ = render_api
    response = client.post('/api/printers', json={
        'name': 'Other', 'ip': 'printer.lan', **patch,
    })
    assert response.status_code == 422, response.text


def test_template_partial_update_validates_merged_row_and_keeps_original(render_api):
    client, engine = render_api
    created = client.post('/api/templates', json={**template_payload(), 'id': 99})
    assert created.status_code == 200, created.text
    ident = created.json()['id']
    valid = client.put(f'/api/templates/{ident}', json={'left_pt': 7, 'id': ident})
    assert valid.status_code == 200, valid.text
    invalid = client.put(f'/api/templates/{ident}', json={'left_left': 301})
    assert invalid.status_code == 422, invalid.text
    null = client.put(f'/api/templates/{ident}', json={'height': None})
    assert null.status_code == 422, null.text
    with Session(engine) as session:
        row = session.get(Template, ident)
        assert row.left_left == 20
        assert row.left_pt == 7


def test_printer_partial_update_validates_merged_row(render_api):
    client, _ = render_api
    response = client.put('/api/printers/1', json={'notes': 'Updated', 'id': 1})
    assert response.status_code == 200, response.text
    response = client.put('/api/printers/1', json={'protocol': 'invalid'})
    assert response.status_code == 422, response.text
    assert client.get('/api/printers/1').json()['protocol'] == 'epl2'


def test_draft_preview_accepts_blank_name_and_no_selected_printer(render_api):
    client, _ = render_api
    response = client.post('/api/print/preview-draft', json={
        'template': {**template_payload(), 'name': '', 'printer_id': 0, 'id': None},
    })
    assert response.status_code == 200, response.text
    assert Image.open(BytesIO(response.content)).size == (640, 100)


@pytest.mark.parametrize('route', ['/api/print/preview-draft', '/api/print/test'])
def test_draft_endpoints_validate_alignment(render_api, route):
    client, _ = render_api
    response = client.post(route, json={
        'template': {**template_payload(), 'h_align': 'INVALID'}, 'printer_id': 1,
    })
    assert response.status_code == 422, response.text


def test_legacy_bad_template_preview_and_print_are_handled(render_api):
    client, engine = render_api
    with Session(engine) as session:
        row = Template(**{**template_payload(), 'height': -1})
        session.add(row)
        session.commit()
        session.refresh(row)
        ident = row.id
    preview = client.get('/api/print/preview', params={'template_id': ident})
    assert preview.status_code == 400, preview.text
    printed = client.post('/api/print', json={'template_id': ident})
    assert printed.status_code == 502, printed.text
    with Session(engine) as session:
        logs = session.exec(select(PrintLog)).all()
        assert len(logs) == 1
        assert logs[0].status == 'error'
        assert 'height' in logs[0].error


@pytest.mark.parametrize('patch', [{'height': -1}, {'bytes_per_row': 0}, {'scale_x': float('inf')}])
def test_renderer_rejects_legacy_invalid_values(patch):
    with pytest.raises(PrintError):
        render_label_bitmap(Template(**{**template_payload(), **patch}), 'TEST', '')


def test_font_loading_failure_is_a_print_error(monkeypatch):
    def missing_font(*_):
        raise OSError('font resource unavailable')
    monkeypatch.setattr('app.printer._load_font', missing_font)
    with pytest.raises(PrintError, match='font resource unavailable'):
        render_label_bitmap(Template(**template_payload()), 'TEST', '')


def test_unknown_existing_protocol_fails_before_framing():
    with pytest.raises(PrintError, match='protocol'):
        build_print_job(Template(**template_payload()), Printer(name='Bad', ip='unused', protocol='invalid'), 'TEST', '')


def test_stretch_preserves_left_and_right_anchors():
    boxes = {}
    for align in ['LEFT', 'CENTER', 'RIGHT']:
        img = render_label_bitmap(Template(**{**template_payload(), 'h_align': align, 'scale_x': 1.12}), 'TEST', '')
        boxes[align] = ImageChops.invert(img).getbbox()
    assert boxes['LEFT'][0] == 20
    assert boxes['RIGHT'][2] == 300
    assert boxes['LEFT'][0] < boxes['CENTER'][0] < boxes['RIGHT'][0]


def test_duplicate_names_return_conflict_and_leave_session_usable(render_api):
    client, _ = render_api
    assert client.post('/api/templates', json=template_payload()).status_code == 200
    assert client.post('/api/templates', json=template_payload()).status_code == 409
    assert client.post('/api/printers', json={'name': 'Desk', 'ip': 'other'}).status_code == 409
    second = client.post('/api/templates', json={**template_payload(), 'name': 'Second'}).json()
    assert client.put(f"/api/templates/{second['id']}", json={'name': 'Label'}).status_code == 409
    assert client.post('/api/printers', json={'name': 'Second', 'ip': 'other'}).status_code == 200
    assert client.put('/api/printers/2', json={'name': 'Desk'}).status_code == 409
    assert client.get('/api/templates').status_code == 200


def test_referenced_deletes_return_conflict_without_breaking_links(render_api):
    client, engine = render_api
    created = client.post('/api/templates', json=template_payload()).json()
    ident = created['id']
    with Session(engine) as session:
        p = Project(name='Project')
        session.add(p); session.commit(); session.refresh(p)
        h = DataHall(name='Hall', project_id=p.id)
        session.add(h); session.commit(); session.refresh(h)
        session.add(Discipline(name='Discipline', data_hall_id=h.id, template_id=ident))
        session.commit()
    assert client.delete('/api/printers/1').status_code == 409
    assert client.delete(f'/api/templates/{ident}').status_code == 409
    with Session(engine) as session:
        assert session.get(Template, ident).printer_id == 1
        assert session.get(Printer, 1) is not None


def test_missing_printer_reference_rejected_on_create_and_update(render_api):
    client, _ = render_api
    missing = client.post('/api/templates', json={**template_payload(), 'printer_id': 999})
    assert missing.status_code == 400
    created = client.post('/api/templates', json=template_payload()).json()
    assert client.put(f"/api/templates/{created['id']}", json={'printer_id': 999}).status_code == 400


@pytest.fixture(autouse=True)
def forbid_printer_network(monkeypatch):
    def forbidden(*_, **__):
        raise AssertionError('Tests must not contact a real printer')
    monkeypatch.setattr('app.printer.socket.create_connection', forbidden)


def test_connect_failure_is_safe_to_retry(monkeypatch):
    from app.printer import send_to_printer
    def refused(*_, **__):
        raise ConnectionRefusedError('refused')
    monkeypatch.setattr('app.printer.socket.create_connection', refused)
    with pytest.raises(PrintError) as caught:
        send_to_printer('unused', 9100, b'job')
    assert caught.value.uncertain is False


def test_send_failure_may_have_printed(monkeypatch):
    from unittest.mock import MagicMock
    from app.printer import send_to_printer
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.sendall.side_effect = TimeoutError('timed out after partial send')
    monkeypatch.setattr('app.printer.socket.create_connection', lambda *_, **__: connection)
    with pytest.raises(PrintError) as caught:
        send_to_printer('unused', 9100, b'job')
    assert caught.value.uncertain is True


@pytest.mark.parametrize('patch', [
    {'left_left': -4096, 'left_right': 4096},
    {'left_bottom': 4096}, {'gap_top': -4096},
])
def test_text_buffers_cannot_expand_beyond_canvas(render_api, patch):
    client, _ = render_api
    response = client.post('/api/templates', json={**template_payload(), **patch})
    assert response.status_code == 422, response.text


def test_extreme_unbroken_text_is_rejected_before_allocating_glyph_mask():
    # Pillow creates a mask for the whole line, even if its output is clipped.
    with pytest.raises(PrintError, match='line'):
        render_label_bitmap(Template(**{**template_payload(), 'left_pt': 144}), 'W' * 4096, '')


@pytest.mark.parametrize('name,geometry', [
    ('R200X225V1T', dict(bytes_per_row=156, height=862, left_top=480, left_bottom=670,
     left_left=20, left_right=600, right_top=480, right_bottom=670, right_left=648,
     right_right=1228, gap_top=20, gap_bottom=20, gap_left=20, gap_right=20)),
    ('R200X150V1T', dict(bytes_per_row=160, height=638, left_top=169, left_bottom=319,
     left_left=38, left_right=638, right_top=169, right_bottom=319, right_left=661,
     right_right=1261)),
    ('R150X150V1T', dict(bytes_per_row=160, height=638, left_top=169, left_bottom=319,
     left_left=188, left_right=638, right_top=169, right_bottom=319, right_left=661,
     right_right=1111)),
    ('S200X400', dict(bytes_per_row=156, height=1238, left_top=550, left_bottom=850,
     left_left=0, left_right=624, right_top=600, right_bottom=800, right_left=624,
     right_right=1200, gap_top=10, gap_bottom=10, gap_left=0, gap_right=10)),
])
def test_shipped_presets_render_at_300_and_600_dpi(name, geometry):
    template = Template(name=name, printer_id=1, **geometry)
    for scale in (1, 2):
        img = render_label_bitmap(template, 'CBL#1.1', 'CBL#1.2', scale=scale)
        assert img.size == (geometry['bytes_per_row'] * 8 * scale, geometry['height'] * scale)
        assert ImageChops.invert(img).getbbox() is not None
    assert Image.open(BytesIO(render_label_png(template, 'CBL#1.1', 'CBL#1.2'))).size == (
        geometry['bytes_per_row'] * 8, geometry['height'])


def test_jscript_600_dpi_payload_uses_doubled_raster_dimensions():
    t = Template(**template_payload())
    p = Printer(name='Cab', ip='unused', protocol='jscript', dpi=600)
    job = build_print_job(t, p, 'TEST', '')
    assert job.startswith(b'd ASC;TDSIMG\r\n050000C8')  # 1280 by 200 pixels


def test_unset_side_with_negative_padding_cannot_allocate_huge_buffer():
    # All-zero side coordinates remain compatible defaults; negative shared
    # padding must still respect the renderer's intermediate allocation cap.
    t = Template(name='Draft', printer_id=1, bytes_per_row=1, height=1,
                 gap_left=-4096, gap_right=-4096, gap_top=-4096, gap_bottom=-4096,
                 mirror_legend=True)
    with pytest.raises(PrintError, match='text area'):
        render_label_bitmap(t, 'TEST', '')


def test_legacy_r200_page_size_repair_previews_and_saves(render_api):
    client, _ = render_api
    payload = dict(name='R200X150', printer_id=1, bytes_per_row=156, height=862,
                   left_left=70, left_right=638, left_top=170, left_bottom=325,
                   right_left=661, right_right=1261, right_top=170, right_bottom=325,
                   left_text='LEFT', right_text='RIGHT', mirror_legend=True)
    response = client.post('/api/print/preview-draft', json={'template': payload, 'crop': True})
    assert response.status_code == 422
    assert 'right text area must fit' in response.text
    payload.update(bytes_per_row=160, height=638)
    response = client.post('/api/print/preview-draft', json={'template': payload, 'crop': True})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/png'
    with Image.open(BytesIO(response.content)) as image:
        assert image.getextrema()[0] < 255
    saved = client.post('/api/templates', json=payload)
    assert saved.status_code in (200, 201), saved.text
    assert saved.json()['right_right'] == 1261
    assert saved.json()['mirror_legend'] is True
