from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.api import cart
from app.models import CartItem, PrintLog, Project
from test_cart_jobs import db


def test_required_project_cannot_print_manual_operator(db, monkeypatch):
    session, _ = db
    project = session.exec(select(Project)).one()
    assert hasattr(project, 'require_rfid')
    project.require_rfid = True
    session.add(project)
    session.commit()
    monkeypatch.delenv('RFID_API_URL', raising=False)
    with patch.object(cart, 'render_and_send') as send:
        with pytest.raises(HTTPException) as error:
            cart.print_all(cart.PrintAllRequest(sid='sid', operator='Manual'), session)
        assert error.value.status_code == 503
    send.assert_not_called()
    assert all(row.status == 'queued' and not row.claim_token for row in session.exec(select(CartItem)).all())
    assert session.exec(select(PrintLog)).all() == []


def require_project(session):
    project = session.exec(select(Project)).one()
    project.require_rfid = True
    session.add(project)
    session.commit()
    return project


def test_direct_and_integration_cannot_bypass(db, monkeypatch):
    from app.api import print as direct, integrations
    from app.models import ApiKey, Label
    session, _ = db
    require_project(session)
    monkeypatch.delenv('RFID_API_URL', raising=False)
    label = session.exec(select(Label)).first()
    key = ApiKey(name='client', prefix='prefix', key_hash='hash')
    actions = [
        lambda: direct.submit_print(direct.PrintRequest(label_id=label.id, operator='Manual'), session),
        lambda: integrations._api_print(integrations.ApiPrintRequest(discipline_id=label.discipline_id, cable='1.0'), session, key),
        lambda: integrations._api_print_batch(integrations.ApiBatchPrintRequest(discipline_id=label.discipline_id, cable='1.*'), session, key),
    ]
    with patch.object(direct, 'render_and_send') as direct_send, patch.object(integrations, 'render_and_send') as api_send:
        for action in actions:
            with pytest.raises(HTTPException) as error:
                action()
            assert error.value.status_code == 503
    direct_send.assert_not_called()
    api_send.assert_not_called()


def test_verified_identity_overrides_manual_and_claim_blocks_overlap(db):
    from app import rfid
    from sqlmodel import Session
    session, engine = db
    project = require_project(session)
    project_id = project.id
    def lookup(code):
        assert code == '001234'
        with Session(engine) as other:
            with pytest.raises(HTTPException) as exc:
                cart.print_all(cart.PrintAllRequest(sid='sid', rfid_code=code), other)
            assert exc.value.status_code == 409
        return rfid.OperatorIdentity('Jane Worker', 'rfid', True, 'employee-123')
    with patch.object(rfid, 'resolve_employee', side_effect=lookup), patch.object(cart, 'render_and_send') as send:
        result = cart.print_all(cart.PrintAllRequest(sid='sid', operator='Wrong name', rfid_code='001234'), session)
    assert result.ok == 2
    assert all(call.args[4] == 'Jane Worker' for call in send.call_args_list)
    logs = session.exec(select(PrintLog)).all()
    assert all(log.operator == 'Jane Worker' and log.operator_verified and log.operator_source == 'rfid' for log in logs)
    assert all(log.operator_employee_id == 'employee-123' for log in logs)
    assert all(log.project_id == project_id and log.project_name == 'P' for log in logs)


def test_mixed_project_policy_checks_every_queued_label(db, monkeypatch):
    from app.models import DataHall, Discipline, Label
    session, _ = db
    project = Project(name='Second', require_rfid=True)
    session.add(project); session.commit()
    hall = DataHall(name='Second hall', project_id=project.id)
    session.add(hall); session.commit()
    disc = Discipline(name='Second disc', data_hall_id=hall.id)
    session.add(disc); session.commit()
    label = Label(discipline_id=disc.id, left_text='Second')
    session.add(label); session.commit()
    cart.add_to_cart(cart.AddRequest(sid='sid', label_id=label.id), session)
    monkeypatch.delenv('RFID_API_URL', raising=False)
    assert cart.print_policy('sid', session) == {'requires_rfid': True, 'configured': False}
    with patch.object(cart, 'render_and_send') as send:
        with pytest.raises(HTTPException):
            cart.print_all(cart.PrintAllRequest(sid='sid', operator='Manual'), session)
    send.assert_not_called()
    assert all(row.status == 'queued' for row in session.exec(select(CartItem)).all())


@pytest.mark.parametrize('failure', [403, 503])
def test_lookup_failure_releases_claim_without_printing(db, failure):
    from app import rfid
    session, _ = db
    require_project(session)
    with patch.object(rfid, 'resolve_employee', side_effect=HTTPException(failure, 'Verification failed')), patch.object(cart, 'render_and_send') as send:
        with pytest.raises(HTTPException) as exc:
            cart.print_all(cart.PrintAllRequest(sid='sid', rfid_code='001'), session)
        assert exc.value.status_code == failure
    send.assert_not_called()
    assert all(row.status == 'queued' and not row.claim_token for row in session.exec(select(CartItem)).all())


@pytest.mark.parametrize('url, valid', [('', False), ('http://service.example/lookup', False), ('https://service.example/lookup', True), ('https://user:pass@service.example', False), ('http://127.0.0.1:8000/lookup', True), ('http://[::1]/lookup', True), ('ftp://localhost', False)])
def test_configuration_transport_policy(monkeypatch, url, valid):
    from app import rfid
    monkeypatch.setenv('RFID_API_URL', url)
    assert rfid.configured() is valid


def test_lookup_protocol_preserves_zeros_and_does_not_follow_redirects(monkeypatch):
    from app import rfid
    import json
    from unittest.mock import MagicMock
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    monkeypatch.setenv('RFID_API_TOKEN', 'secret')
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(directory_payload()).encode()
    opener = MagicMock()
    opener.open.return_value = response
    with patch.object(rfid, 'build_opener', return_value=opener) as build:
        assert rfid.resolve_full_name(' 001234\r\n') == 'Jane Worker'
    request = opener.open.call_args.args[0]
    from urllib.parse import parse_qs, urlsplit
    assert request.method == 'GET' and request.data is None
    assert parse_qs(urlsplit(request.full_url).query) == {'rfid': ['001234'], 'active': ['true'], 'limit': ['2'], 'offset': ['0']}
    assert request.get_header('Authorization') == 'Bearer secret'
    assert opener.open.call_args.kwargs['timeout'] == 5
    assert build.call_args.args[0].redirect_request(None, None, 302, '', {}, 'https://elsewhere') is None


@pytest.mark.parametrize('payload,status', [(b'{}',503), (b'{"full_name":123}',503), (b'{"full_name":" "}',503), (b'not json',503), (b'x'*16385,503)])
def test_invalid_directory_response_fails_closed(monkeypatch, payload, status):
    from app import rfid
    from unittest.mock import MagicMock
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = payload
    with patch.object(rfid, 'build_opener') as build:
        build.return_value.open.return_value = response
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_full_name('001234')
        assert exc.value.status_code == status
        assert '001234' not in exc.value.detail


def test_template_only_print_requires_admin(db):
    from app.api import print as direct
    from app.models import Template
    session, _ = db
    template = session.exec(select(Template)).one()
    with patch.object(direct, 'render_and_send') as send:
        with pytest.raises(HTTPException) as exc:
            direct.submit_print(direct.PrintRequest(template_id=template.id), session)
        assert exc.value.status_code == 401
    send.assert_not_called()


def test_label_text_override_requires_admin(db):
    from app.api import print as direct
    from app.models import Label
    session, _ = db
    label = session.exec(select(Label)).first()
    with patch.object(direct, 'render_and_send') as send:
        with pytest.raises(HTTPException) as exc:
            direct.submit_print(direct.PrintRequest(label_id=label.id, left_text='Protected label text'), session)
        assert exc.value.status_code == 401
    send.assert_not_called()


def test_malformed_http_fails_closed(monkeypatch):
    from app import rfid
    from http.client import BadStatusLine
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example')
    with patch.object(rfid, 'build_opener') as build:
        build.return_value.open.side_effect = BadStatusLine('001234')
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_full_name('001234')
        assert exc.value.status_code == 503
        assert '001234' not in exc.value.detail


from test_integration_idempotency import setup


@pytest.mark.parametrize('path', ['/print', '/print-batch'])
def test_rfid_api_replay_audit_and_no_plaintext_storage(setup, path):
    import json
    from app import rfid
    from app.api import integrations
    from app.models import IntegrationPrintRequest
    from sqlmodel import Session
    client, payload, _, engine = setup
    with Session(engine) as session:
        require_project(session)
    payload = {**payload, 'rfid_code': '001234'}
    with patch.object(rfid, 'resolve_employee', return_value=rfid.OperatorIdentity('Jane Worker', 'rfid', True, 'employee-123')) as lookup, patch.object(integrations, 'render_and_send') as send:
        first = client.post('/api/v1' + path, json=payload, headers={'Idempotency-Key': 'rfid-job'})
        replay = client.post('/api/v1' + path, json=payload, headers={'Idempotency-Key': 'rfid-job'})
        changed = client.post('/api/v1' + path, json={**payload, 'rfid_code': '002345'}, headers={'Idempotency-Key': 'rfid-job'})
    assert first.status_code == replay.status_code == 200, first.text
    assert changed.status_code == 409
    assert send.call_count == lookup.call_count == 1
    assert send.call_args.args[4] == 'Jane Worker'
    with Session(engine) as session:
        log = session.exec(select(PrintLog)).one()
        assert log.operator == 'Jane Worker' and log.operator_source == 'rfid' and log.operator_verified
        assert log.project_id and log.project_name == 'P'
        assert log.operator_employee_id == 'employee-123'
        stored = session.exec(select(IntegrationPrintRequest)).one()
        assert '001234' not in json.dumps(stored.model_dump(mode='json'))
        assert '001234' not in json.dumps(log.model_dump(mode='json'))


def test_project_toggle_is_admin_only_and_persists(db):
    from app.api import projects
    from app.auth_admin import require_admin
    from app.db import get_session
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    session, engine = db
    project_id = session.exec(select(Project)).one().id
    app = FastAPI()
    app.include_router(projects.router)
    def sessions():
        with Session(engine) as current:
            yield current
    app.dependency_overrides[get_session] = sessions
    with TestClient(app) as client:
        assert client.patch(f'/api/projects/{project_id}', json={'require_rfid': True}).status_code in (401, 503)
        app.dependency_overrides[require_admin] = lambda: 'admin'
        response = client.patch(f'/api/projects/{project_id}', json={'require_rfid': True})
        assert response.status_code == 200 and response.json()['require_rfid'] is True
        assert client.get('/api/projects').json()[0]['require_rfid'] is True
        assert client.patch(f'/api/projects/{project_id}', json={'require_rfid': None}).status_code == 422


def directory_payload(**overrides):
    employee = dict(employee_id='employee-123', rfid='001234', full_name=' Jane Worker ', active=True)
    employee.update(overrides)
    return dict(items=[employee], total=1, limit=2, offset=0)


@pytest.fixture(autouse=True)
def clear_directory_cooldown(monkeypatch):
    monkeypatch.setenv('RFID_API_TOKEN', 'test-directory-key')
    from app import rfid
    rfid._cooldowns.clear()
    yield
    rfid._cooldowns.clear()


@pytest.mark.parametrize('raw,normalized', [('00:12-ab', '0012AB'), ('00+12/ab$^=|~', '0012AB'), (' 00 12-ab\r\n', '0012AB'), ('0'*64, '0'*64)])
def test_normalize_card(raw, normalized):
    from app.rfid import normalize_card
    assert normalize_card(raw) == normalized


@pytest.mark.parametrize('raw', [None, '', '--- ', 'a'*65, 'a'*257, '12€', '１２', 'ß', 'a\x00'])
def test_invalid_card_does_not_call_directory(monkeypatch, raw):
    from app import rfid
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    with patch.object(rfid, 'build_opener') as build:
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_employee(raw)
        assert exc.value.status_code == 403
        build.assert_not_called()


@pytest.mark.parametrize('changes,status', [({'active': False},403), ({'active': 1},403), ({'rfid': None},503), ({'rfid': 'different'},503), ({'employee_id': ''},503), ({'employee_id': None},503), ({'full_name': ' '},503)])
def test_directory_employee_validation(monkeypatch, changes, status):
    import json
    from unittest.mock import MagicMock
    from app import rfid
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(directory_payload(**changes)).encode()
    with patch.object(rfid, 'build_opener') as build:
        build.return_value.open.return_value = response
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_employee('001234')
        assert exc.value.status_code == status


@pytest.mark.parametrize('total,items,status', [(0, [],403), (2, [],403), (1, [],503), (True, [],503), (-1, [],503)])
def test_directory_cardinality(monkeypatch, total, items, status):
    import json
    from unittest.mock import MagicMock
    from app import rfid
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(dict(total=total, items=items)).encode()
    with patch.object(rfid, 'build_opener') as build:
        build.return_value.open.return_value = response
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_employee('001234')
        assert exc.value.status_code == status


def test_directory_429_cooldown_never_retries_automatically(monkeypatch):
    from app import rfid
    from urllib.error import HTTPError
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    with patch.object(rfid.time, 'monotonic', return_value=100), patch.object(rfid, 'build_opener') as build:
        build.return_value.open.side_effect = HTTPError('https://directory.example', 429, 'Busy', {'Retry-After': '10'}, None)
        for _ in range(2):
            with pytest.raises(HTTPException) as exc:
                rfid.resolve_employee('001234')
            assert exc.value.status_code == 503
            assert exc.value.headers == {'Retry-After': '10'}
        assert build.return_value.open.call_count == 1


@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 500, 503])
def test_directory_http_failures_are_safe_unavailable(monkeypatch, status):
    from app import rfid
    from urllib.error import HTTPError
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/lookup')
    with patch.object(rfid, 'build_opener') as build:
        build.return_value.open.side_effect = HTTPError('https://directory.example', status, '001234 secret', {}, None)
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_employee('001234')
        assert exc.value.status_code == 503
        assert '001234' not in exc.value.detail and 'secret' not in exc.value.detail


def test_normalized_directory_card_returns_stable_identity(monkeypatch):
    import json
    from unittest.mock import MagicMock
    from app import rfid
    monkeypatch.setenv('RFID_API_URL', 'https://directory.example/api/v1/external/employees')
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = json.dumps(directory_payload(rfid='00:12-ab')).encode()
    with patch.object(rfid, 'build_opener') as build:
        build.return_value.open.return_value = response
        identity = rfid.resolve_employee('00 12ab')
    assert identity.employee_id == 'employee-123'
    assert identity.name == 'Jane Worker'
    assert identity.audit()['operator_employee_id'] == 'employee-123'
    assert identity.verified and identity.source == 'rfid'


@pytest.mark.parametrize('token', [None, '', '   '])
def test_missing_directory_key_is_not_configured_and_never_calls_network(monkeypatch, token):
    from app import rfid
    monkeypatch.setenv('RFID_API_URL', 'https://attendance.example/acme/api/v1/external/employees')
    if token is None:
        monkeypatch.delenv('RFID_API_TOKEN', raising=False)
    else:
        monkeypatch.setenv('RFID_API_TOKEN', token)
    assert rfid.configured() is False
    with patch.object(rfid, 'build_opener') as build:
        with pytest.raises(HTTPException) as exc:
            rfid.resolve_employee('001234')
        assert exc.value.status_code == 503
        assert exc.value.detail == 'RFID verification is not configured on the server.'
    build.assert_not_called()
