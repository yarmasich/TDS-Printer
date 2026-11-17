"""The legacy external print API holds a job the printer says it cannot print.

`/api/v1/print` and `/api/v1/print-batch` used to send blind. A DP4600H with
its head open accepts the bytes, so the caller saw a success for a label that
may come out later or never.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import printer_device_status as device
from app.api import integrations
from app.auth_apikey import require_api_key
from app.db import get_session
from app.models import ApiKey, DataHall, Discipline, Label, Printer, PrintLog, Project, Template
from tests.test_panduit_status import reply


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    # No global socket guard here: TestClient needs real sockets for its event
    # loop. Every test replaces `_exchange`, so no SNMP packet leaves the process.
    device._cache.clear()
    monkeypatch.setattr(device.secrets, 'randbelow', lambda _: 122)


@pytest.fixture
def api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        # community 'sample' is what reply() answers with
        p = Printer(name="P", ip="192.0.2.1", model="DP4600H", snmp_community="sample")
        project = Project(name="P")
        s.add_all([p, project]); s.commit()
        t = Template(name="T", printer_id=p.id, bytes_per_row=20, height=100)
        h = DataHall(name="H", project_id=project.id)
        s.add_all([t, h]); s.commit()
        d = Discipline(name="D", data_hall_id=h.id, template_id=t.id)
        s.add(d); s.commit()
        s.add_all([Label(discipline_id=d.id, left_text="CBL#1.1"), Label(discipline_id=d.id, left_text="CBL#1.2")])
        s.commit()
        discipline_id = d.id
    app = FastAPI()
    app.include_router(integrations.router)
    def sessions():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[require_api_key] = lambda: ApiKey(name="test", prefix="test", key_hash="k")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, discipline_id, engine
    engine.dispose()


def snmp(monkeypatch, *, status=3, flags=b'\0', cover=6, error=None):
    answer = reply(status, flags, cover=cover, model=b'Panduit DP4600H label printer')
    exchange = MagicMock(side_effect=error) if error else MagicMock(return_value=answer)
    monkeypatch.setattr(device, '_exchange', exchange)
    return exchange


def logs(engine):
    with Session(engine) as s:
        return [log.status for log in s.exec(select(PrintLog)).all()]


def test_single_print_is_held_and_names_the_printer_state(api, monkeypatch):
    client, disc, engine = api
    snmp(monkeypatch, cover=5)
    with patch.object(integrations, 'render_and_send') as send:
        response = client.post('/api/v1/print', json={'discipline_id': disc, 'cable': '1.1', 'copies': 3})
    send.assert_not_called()
    # The documented 502 shape, so existing callers keep working.
    assert response.status_code == 502
    detail = response.json()['detail']
    assert detail['printer_state'] == 'cover_open' and detail['printed'] == 0
    assert 'cover is open' in detail['message']
    assert logs(engine) == ['error']  # one refusal, not one per copy


def test_single_print_asks_the_printer_once_for_all_copies(api, monkeypatch):
    client, disc, _ = api
    exchange = snmp(monkeypatch)
    with patch.object(integrations, 'render_and_send') as send:
        response = client.post('/api/v1/print', json={'discipline_id': disc, 'cable': '1.1', 'copies': 3})
    assert response.status_code == 200 and send.call_count == 3
    assert exchange.call_count == 1


def test_single_print_proceeds_when_the_state_is_unknown(api, monkeypatch):
    client, disc, _ = api
    snmp(monkeypatch, error=TimeoutError('silent'))
    with patch.object(integrations, 'render_and_send') as send:
        response = client.post('/api/v1/print', json={'discipline_id': disc, 'cable': '1.1'})
    assert response.status_code == 200 and send.call_count == 1


def test_batch_holds_every_label_without_sending(api, monkeypatch):
    client, disc, engine = api
    exchange = snmp(monkeypatch, status=1, flags=b'B')  # "Error - Out of paper", as captured live
    with patch.object(integrations, 'render_and_send') as send:
        response = client.post('/api/v1/print-batch', json={'discipline_id': disc, 'cables': ['1.1', '1.2']})
    send.assert_not_called()
    body = response.json()
    # Still the documented 200 with per-cable results and only documented statuses.
    assert response.status_code == 200 and body['ok'] is False and body['printed'] == 0
    assert body['printer_state'] == 'no_media'
    assert [r['status'] for r in body['results']] == ['error', 'error']
    assert all('no labels' in r['error'] for r in body['results'])
    assert exchange.call_count == 1
    assert logs(engine) == ['error', 'error']


def test_batch_stop_on_error_skips_the_rest_of_a_held_job(api, monkeypatch):
    client, disc, _ = api
    snmp(monkeypatch, cover=5)
    with patch.object(integrations, 'render_and_send'):
        body = client.post('/api/v1/print-batch', json={'discipline_id': disc, 'cables': ['1.1', '1.2'],
                                                        'stop_on_error': True}).json()
    assert [r['status'] for r in body['results']] == ['error', 'skipped']


def test_a_healthy_batch_carries_no_printer_state(api, monkeypatch):
    client, disc, _ = api
    snmp(monkeypatch)
    with patch.object(integrations, 'render_and_send'):
        body = client.post('/api/v1/print-batch', json={'discipline_id': disc, 'cables': ['1.1', '1.2']}).json()
    assert body['ok'] is True and body['printed'] == 2 and body['printer_state'] is None
