"""Durable replay tests; only mocked printer transport is invoked."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import integrations
from app.auth_apikey import require_api_key
from app.db import get_session
from app.models import ApiKey, DataHall, Discipline, Label, Printer, Project, Template
from app.printer import PrintError


@pytest.fixture
def setup(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/replay.db", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        p, project = Printer(name="P", ip="192.0.2.1"), Project(name="P")
        s.add_all([p, project]); s.commit()
        t = Template(name="T", printer_id=p.id, bytes_per_row=20, height=100)
        h = DataHall(name="H", project_id=project.id)
        s.add_all([t, h]); s.commit()
        d = Discipline(name="D", data_hall_id=h.id, template_id=t.id)
        s.add(d); s.commit()
        s.add(Label(discipline_id=d.id, left_text="CBL#1.1")); s.commit()
        payload = {"discipline_id": d.id, "cable": "1.1"}
    key = ApiKey(name="test", prefix="test", key_hash="credential-one")
    app = FastAPI()
    app.include_router(integrations.router)
    def sessions():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[require_api_key] = lambda: key
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, payload, key, engine
    engine.dispose()


@pytest.mark.parametrize("path", ["/print", "/print-batch"])
def test_completed_replay_and_changed_payload(setup, path):
    client, payload, _, _ = setup
    with patch.object(integrations, "render_and_send") as send:
        first = client.post('/api/v1' + path, json=payload, headers={"Idempotency-Key": "job"})
        replay = client.post('/api/v1' + path, json=payload, headers={"Idempotency-Key": "job"})
        changed = client.post('/api/v1' + path, json={**payload, "reason": "different"}, headers={"Idempotency-Key": "job"})
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert changed.status_code == 409
    assert send.call_count == 1


def test_interruption_survives_new_session_and_blocks_retry(setup):
    client, payload, _, _ = setup
    with patch.object(integrations, "render_and_send", side_effect=RuntimeError("process interrupted")) as send:
        assert client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"}).status_code == 500
        assert client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"}).status_code == 409
    assert send.call_count == 1


def test_inflight_competing_request_cannot_send(setup):
    client, payload, _, _ = setup
    calls = []
    def during_send(*args):
        calls.append(True)
        if len(calls) > 1:
            return
        competing = client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"})
        assert competing.status_code == 409
    with patch.object(integrations, "render_and_send", side_effect=during_send) as send:
        assert client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"}).status_code == 200
    assert send.call_count == 1


def test_uncertain_error_replays_original_failure(setup):
    client, payload, _, _ = setup
    with patch.object(integrations, "render_and_send", side_effect=PrintError("partial write", uncertain=True)) as send:
        first = client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"})
        replay = client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"})
    assert first.status_code == replay.status_code == 502
    assert first.json() == replay.json()
    assert send.call_count == 1


def test_key_scope_and_no_header_compatibility(setup):
    client, payload, key, _ = setup
    with patch.object(integrations, "render_and_send") as send:
        for _ in range(2):
            assert client.post('/api/v1/print', json=payload).status_code == 200
        assert client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"}).status_code == 200
        key.key_hash = 'credential-two'
        assert client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": "job"}).status_code == 200
    assert send.call_count == 4


@pytest.mark.parametrize('value', ['', ' ', 'x' * 201])
def test_invalid_key_never_sends(setup, value):
    client, payload, _, _ = setup
    with patch.object(integrations, "render_and_send") as send:
        assert client.post('/api/v1/print', json=payload, headers={"Idempotency-Key": value}).status_code == 400
    send.assert_not_called()


def test_failure_saving_completed_response_never_reprints(setup):
    from app.models import IntegrationPrintRequest
    client, payload, _, _ = setup
    original_commit = Session.commit
    def commit(session):
        if any(isinstance(row, IntegrationPrintRequest) and row.state == 'completed' for row in session.dirty):
            raise RuntimeError('database unavailable after send')
        return original_commit(session)
    with patch.object(Session, 'commit', commit), patch.object(integrations, 'render_and_send') as send:
        assert client.post('/api/v1/print', json=payload, headers={'Idempotency-Key': 'job'}).status_code == 500
        assert client.post('/api/v1/print', json=payload, headers={'Idempotency-Key': 'job'}).status_code == 409
    assert send.call_count == 1


def test_missing_reservation_table_fails_before_send(setup):
    from app.models import IntegrationPrintRequest
    client, payload, _, engine = setup
    IntegrationPrintRequest.__table__.drop(engine)
    with patch.object(integrations, 'render_and_send') as send:
        assert client.post('/api/v1/print', json=payload, headers={'Idempotency-Key': 'job'}).status_code == 500
    send.assert_not_called()


def test_key_cannot_be_reused_across_endpoints(setup):
    client, payload, _, _ = setup
    with patch.object(integrations, 'render_and_send') as send:
        assert client.post('/api/v1/print', json=payload, headers={'Idempotency-Key': 'job'}).status_code == 200
        assert client.post('/api/v1/print-batch', json=payload, headers={'Idempotency-Key': 'job'}).status_code == 409
    assert send.call_count == 1
