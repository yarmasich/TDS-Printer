from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api import cart, stations
from app.api import print as direct
from app.auth_admin import create_admin_token
from app.db import get_session
from app.login_limits import LoginLimiter
from app.main import app
from app.models import Label, PrintLog, Printer, Station, Project
from test_cart_jobs import db


@pytest.fixture
def client(db, monkeypatch):
    session, engine = db
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'admin-password')
    monkeypatch.setenv('ADMIN_JWT_SECRET', 'test-secret-with-enough-entropy-123456789')
    monkeypatch.setattr(stations, 'login_limiter', LoginLimiter())
    def override():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def admin():
    return {'Authorization': 'Bearer ' + create_admin_token('admin')}


def create(client, username='first', printer_id=1, enabled=True):
    response = client.post('/api/stations', headers=admin(), json={
        'username': username, 'display_name': username.title(), 'password': 'password123',
        'printer_id': printer_id, 'enabled': enabled})
    assert response.status_code == 200, response.text
    return response.json()


def login(client, username='first', password='password123'):
    result = client.post('/api/station-auth/login', json={'username': username, 'password': password})
    assert result.status_code == 200, result.text
    return {'Authorization': 'Bearer ' + result.json()['access_token']}


def test_login_scope_and_password_privacy(client, db):
    created = create(client)
    assert set(created) == {'id', 'username', 'display_name', 'printer_id', 'printer_name', 'enabled'}
    headers = login(client)
    assert client.get('/api/station-auth/me', headers=headers).json() == created
    assert client.get('/api/stations', headers=headers).status_code == 401
    assert client.get('/api/station-auth/me', headers=admin()).status_code == 401
    assert client.post('/api/stations', headers=headers, json={}).status_code == 401
    rows = client.get('/api/stations', headers=admin()).json()
    assert rows == [created]
    row = db[0].exec(select(Station)).one()
    assert row.password_hash != 'password123'
    assert 'password123' not in row.password_hash
    failed = client.post('/api/station-auth/login', json={'username':'first','password':'wrong'})
    assert failed.status_code == 401


def test_cart_namespace_and_every_endpoint_is_guarded(client):
    assert client.get('/api/station-auth/status').json() == {'required': False}
    assert len(client.get('/api/cart', params={'sid':'sid'}).json()) == 2
    create(client)
    create(client, 'second')
    first, second = login(client), login(client, 'second')
    assert client.get('/api/station-auth/status').json() == {'required': True}
    assert client.get('/api/cart', params={'sid':'sid'}, headers=first).json() == []
    item = client.post('/api/cart', headers=first, json={'sid':'sid','label_id':1}).json()
    assert len(client.get('/api/cart', headers=first, params={'sid':'sid'}).json()) == 1
    assert client.get('/api/cart', headers=second, params={'sid':'sid'}).json() == []
    assert client.delete(f"/api/cart/{item['id']}", headers=second, params={'sid':'sid'}).status_code == 404
    assert client.delete('/api/cart', headers=second, params={'sid':'sid'}).json() == {'cleared':0}
    routes = [('GET','/api/cart?sid=sid',None),('GET','/api/cart/print-policy?sid=sid',None),
              ('POST','/api/cart',{'sid':'sid','label_id':1}),('DELETE','/api/cart?sid=sid',None),
              ('DELETE',f"/api/cart/{item['id']}?sid=sid",None),
              ('POST','/api/cart/print',{'sid':'sid'}),('POST','/api/print',{'label_id':1})]
    with patch.object(cart,'render_and_send') as send, patch.object(direct,'render_and_send') as direct_send:
        for method, url, body in routes:
            result = client.request(method,url,json=body)
            assert result.status_code == 401, (url,result.text)
    send.assert_not_called(); direct_send.assert_not_called()
    # Admin retains its old cart, without reaching any station's cart by spelling its namespace.
    assert len(client.get('/api/cart', headers=admin(), params={'sid':'sid'}).json()) == 2
    assert client.get('/api/cart', headers=admin(), params={'sid':'station:1:anything'}).status_code == 400


def test_disable_password_reset_and_deleted_station_revoke(client, db):
    created = create(client)
    headers = login(client)
    url = f"/api/stations/{created['id']}"
    assert client.patch(url,headers=admin(),json={'enabled':False}).status_code == 200
    assert client.get('/api/station-auth/me',headers=headers).status_code == 401
    assert client.get('/api/cart?sid=sid').status_code == 401
    assert client.get('/api/station-auth/status').json()['required'] is True
    client.patch(url,headers=admin(),json={'enabled':True})
    assert client.get('/api/station-auth/me',headers=headers).status_code == 401
    headers = login(client)
    client.patch(url,headers=admin(),json={'password':'replacement123'})
    assert client.get('/api/station-auth/me',headers=headers).status_code == 401
    fresh = login(client,password='replacement123')
    assert client.get('/api/station-auth/me',headers=fresh).status_code == 200
    session = db[0]
    row = session.get(Station,created['id']); session.delete(row); session.commit()
    assert client.get('/api/station-auth/me',headers=fresh).status_code == 401


def test_live_assignment_controls_direct_and_cart_snapshot_audit(client, db):
    session, _ = db
    printer = Printer(name='Station printer',ip='192.0.2.2')
    session.add(printer); session.commit(); session.refresh(printer)
    created = create(client)
    headers = login(client)
    client.patch(f"/api/stations/{created['id']}",headers=admin(),json={'printer_id':printer.id,'display_name':'Desk A'})
    assert client.get('/api/station-auth/me',headers=headers).json()['printer_name'] == 'Station printer'
    sent_printers = []
    with patch.object(direct,'render_and_send', side_effect=lambda *args: sent_printers.append(args[1].id)) as send:
        result = client.post('/api/print',headers=headers,json={'label_id':1,'operator':'Alice','reason':'Repair'})
    assert result.status_code == 200, result.text
    assert sent_printers == [printer.id]
    # Changing custom text remains admin-only even with a valid station session.
    assert client.post('/api/print',headers=headers,json={'label_id':1,'left_text':'override'}).status_code == 401
    client.post('/api/cart',headers=headers,json={'sid':'sid','label_id':1})
    with patch.object(cart,'render_and_send') as send:
        result = client.post('/api/cart/print',headers=headers,json={'sid':'sid','operator':'Alice'})
    assert result.status_code == 200, result.text
    assert send.call_args.args[1].id == printer.id
    session.expire_all()
    logs = session.exec(select(PrintLog)).all()
    assert len(logs) == 2
    assert all(log.station_id == created['id'] and log.station_name == 'Desk A' and log.printer_name == printer.name for log in logs)
    assert all(log.operator == 'Alice' for log in logs)
    client.patch(f"/api/stations/{created['id']}",headers=admin(),json={'display_name':'Renamed'})
    session.expire_all()
    assert all(log.station_name == 'Desk A' for log in session.exec(select(PrintLog)).all())
    # No physical send can be selected via a client printer override.
    assert client.delete(f'/api/printers/{printer.id}',headers=admin()).status_code == 409


def test_station_login_does_not_replace_required_rfid(client, db, monkeypatch):
    create(client); headers = login(client)
    session = db[0]
    project = session.exec(select(Project)).one(); project.require_rfid = True
    session.add(project); session.commit()
    monkeypatch.delenv('RFID_API_URL',raising=False)
    client.post('/api/cart',headers=headers,json={'sid':'sid','label_id':1})
    assert client.get('/api/cart/print-policy?sid=sid',headers=headers).json()['requires_rfid']
    with patch.object(cart,'render_and_send') as send, patch.object(direct,'render_and_send') as direct_send:
        assert client.post('/api/cart/print',headers=headers,json={'sid':'sid','operator':'Manual'}).status_code == 503
        assert client.post('/api/print',headers=headers,json={'label_id':1,'operator':'Manual'}).status_code == 503
    send.assert_not_called(); direct_send.assert_not_called()


def test_validation_and_login_limiter(client, monkeypatch):
    create(client)
    assert client.patch('/api/stations/1',headers=admin(),json={'printer_id':999}).status_code == 422
    assert client.patch('/api/stations/1',headers=admin(),json={'enabled':None}).status_code == 422
    assert client.patch('/api/stations/1',headers=admin(),json={'username':' '}).status_code == 422
    assert client.post('/api/stations',headers=admin(),json={'username':'first','display_name':'Duplicate','password':'password123','printer_id':1}).status_code == 409
    monkeypatch.setattr(stations,'login_limiter',LoginLimiter(per_client=1))
    login(client)
    result = client.post('/api/station-auth/login',json={'username':'first','password':'password123'})
    assert result.status_code == 429 and int(result.headers['Retry-After']) > 0


def test_operator_preview_uses_assigned_printer(client, db):
    session = db[0]
    printer = Printer(name='Preview printer',ip='192.0.2.2',dpi=600)
    session.add(printer); session.commit(); session.refresh(printer)
    create(client,printer_id=printer.id)
    headers = login(client)
    captured = []
    def render(*args, **kwargs):
        captured.append((kwargs['printer'].id,kwargs['printer'].dpi))
        return b'png'
    with patch('app.calibration.render_preview_png',side_effect=render):
        assert client.get('/api/labels/1/preview').status_code == 401
        response = client.get('/api/labels/1/preview',headers=headers)
    assert response.status_code == 200
    assert captured == [(printer.id,600)]


def test_external_api_remains_key_authenticated_and_rfid_free(client, db, monkeypatch):
    from app.api import integrations
    from app.auth_apikey import require_api_key
    from app.models import ApiKey
    create(client)
    project = db[0].exec(select(Project)).one(); project.require_rfid = True
    db[0].add(project); db[0].commit()
    monkeypatch.delenv('RFID_API_URL',raising=False)
    assert client.post('/api/v1/print',json={'discipline_id':1,'cable':'1.0'}).status_code == 401
    app.dependency_overrides[require_api_key] = lambda: ApiKey(name='external',prefix='ext',key_hash='external-key')
    try:
        with patch.object(integrations,'render_and_send') as send:
            response = client.post('/api/v1/print',json={'discipline_id':1,'cable':'1.0'})
        assert response.status_code == 200, response.text
        assert send.call_count == 1
    finally:
        del app.dependency_overrides[require_api_key]


def test_running_cart_keeps_printer_and_station_snapshot(client, db):
    session, engine = db
    other_printer = Printer(name='Other',ip='192.0.2.2')
    session.add(other_printer); session.commit(); session.refresh(other_printer)
    other_id = other_printer.id
    created = create(client)
    headers = login(client)
    for label_id in (1,2):
        client.post('/api/cart',headers=headers,json={'sid':'job','label_id':label_id})
    sent = []
    def during_send(template, printer, *args):
        sent.append((printer.id,printer.ip,printer.name,dict(printer.material_calibrations)))
        if len(sent) == 1:
            with Session(engine) as other:
                station = other.get(Station,created['id'])
                station.printer_id = other_id; station.display_name = 'Changed'
                original = other.get(Printer,1)
                original.ip = '192.0.2.99'; original.name = 'Changed printer'
                original.material_calibrations = {'test':{'x':1}}
                other.add_all([station,original]); other.commit()
    with patch.object(cart,'render_and_send',side_effect=during_send):
        response = client.post('/api/cart/print',headers=headers,json={'sid':'job'})
    assert response.status_code == 200 and response.json()['ok'] == 2
    assert sent == [(1,'192.0.2.1','P',{}),(1,'192.0.2.1','P',{})]
    session.expire_all()
    logs = session.exec(select(PrintLog)).all()
    assert all(log.station_name == 'First' and log.printer_name == 'P' for log in logs)
    assert client.get('/api/station-auth/me',headers=headers).json()['printer_id'] == other_id
