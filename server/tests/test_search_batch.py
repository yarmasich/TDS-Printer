from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

from app.models import ApiKey, DataHall, Discipline, Label, Printer, Project, Template
from app.api import integrations, labels
from app.printer import PrintError
from app.search import parse_batch_query, validate_query


@pytest.fixture
def data():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        p = Printer(name="P", ip="192.0.2.1")
        project = Project(name="Project")
        session.add_all([p, project]); session.commit()
        t = Template(name="T", printer_id=p.id, bytes_per_row=20, height=100)
        h = DataHall(name="H", project_id=project.id)
        session.add_all([t, h]); session.commit()
        d = Discipline(name="D", data_hall_id=h.id, template_id=t.id)
        session.add(d); session.commit()
        key = ApiKey(name="test", prefix="test", key_hash="not-a-key")
        yield session, d, key
    engine.dispose()


def add(session, d, text, bundle=None):
    row = Label(discipline_id=d.id, left_text=text, right_text=text, bundle=bundle)
    session.add(row); session.commit()
    return row.id


def batch(data, **kwargs):
    s, d, key = data
    return integrations.api_print_batch(integrations.ApiBatchPrintRequest(discipline_id=d.id, **kwargs), s, key)


@pytest.mark.parametrize("query, expected", [
    ("1.1,1.2,1.5", ["1.1", "1.2", "1.5"]),
    ("45.5,6,7", ["45.5", "45.6", "45.7"]),
    ("1.5-1.8", ["1.5", "1.6", "1.7", "1.8"]),
    ("1.5-8", ["1.5", "1.6", "1.7", "1.8"]),
    ("SERVER ROOM", ["SERVER ROOM"]),
])
def test_documented_query_forms(query, expected):
    assert parse_batch_query(query) == expected


def test_bounds_before_allocating_range():
    with pytest.raises(ValueError):
        parse_batch_query("1.1-10000")


def test_text_search_preserves_spaces():
    assert validate_query("SERVER ROOM") == (True, "SERVER ROOM")


def test_search_reports_truncation(data):
    s, d, _ = data
    for i in range(3): add(s, d, f"CBL#1.{i}")
    result = labels.search(q="1.*", project_id=None, data_hall_id=None, discipline_id=d.id, limit=2, offset=0, session=s)
    assert result.total == 3
    assert result.truncated is True
    assert len(result.hits) == 2


def test_overlapping_groups_print_each_label_once(data):
    s, d, _ = data
    a = add(s, d, "CBL#1.1"); b = add(s, d, "CBL#1.2")
    with patch.object(integrations, "render_and_send") as send:
        result = batch(data, cables=["1.*", "1.1"])
    assert result.printed == 2
    assert send.call_count == 2
    assert {r.label_id for r in result.results} == {a, b}


def test_individual_cable_in_bundle_mode_is_not_whole_bundle(data):
    s, d, _ = data
    d.bundle_mode = True; s.add(d); s.commit()
    a = add(s, d, "CBL#1.1", "1"); add(s, d, "CBL#1.2", "1")
    with patch.object(integrations, "render_and_send") as send:
        result = batch(data, cable="1.1")
    assert result.printed == send.call_count == 1
    assert result.results[0].label_id == a


def test_missing_bundle_is_reported(data):
    s, d, _ = data
    d.bundle_mode = True; s.add(d); s.commit()
    add(s, d, "CBL#1.1", "1")
    with patch.object(integrations, "render_and_send"):
        result = batch(data, cables=["1.*", "999.*"])
    assert not result.ok
    assert any(r.status == "not_found" and "999" in r.cable for r in result.results)


@pytest.mark.parametrize("bundle_mode", [False, True])
def test_actual_label_limit_checked_before_any_print(data, bundle_mode):
    s, d, _ = data
    d.bundle_mode = bundle_mode; s.add(d)
    s.add_all([Label(discipline_id=d.id, left_text=f"CBL#1.{i}", bundle="1") for i in range(501)])
    s.commit()
    with patch.object(integrations, "render_and_send") as send:
        with pytest.raises(HTTPException) as err:
            batch(data, cable="1.*")
    assert err.value.status_code == 400
    send.assert_not_called()


def test_group_abort_reports_every_selected_label(data):
    s, d, _ = data
    for i in range(3): add(s, d, f"CBL#1.{i}")
    with patch.object(integrations, "render_and_send", side_effect=PrintError("offline")):
        result = batch(data, cable="1.*", stop_on_error=True)
    assert [r.status for r in result.results] == ["error", "skipped", "skipped"]


def test_individual_partial_failure_keeps_log_and_continues(data):
    s, d, _ = data
    add(s, d, "CBL#1.1"); add(s, d, "CBL#1.2")
    with patch.object(integrations, "render_and_send", side_effect=[PrintError("offline"), None]):
        result = batch(data, cables=["1.1", "1.2"])
    assert result.printed == 1
    assert not result.ok
    assert [r.status for r in result.results] == ["error", "printed"]
