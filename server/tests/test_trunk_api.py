"""The external API prints a leg, its trunk, or both — each on its own printer."""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.api import integrations
from app.auth_apikey import require_api_key
from app.db import get_session
from app.models import ApiKey, DataHall, Discipline, Label, Printer, Project, Template


@pytest.fixture
def api(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/api.db", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        legs_p, trunks_p, project = Printer(name="Legs", ip="192.0.2.1"), Printer(name="Trunks", ip="192.0.2.2"), Project(name="Nscale")
        s.add_all([legs_p, trunks_p, project]); s.commit()
        leg_t = Template(name="R200x150", printer_id=legs_p.id, bytes_per_row=20, height=100)
        trunk_t = Template(name="S200X400VATY", printer_id=trunks_p.id, bytes_per_row=20, height=100)
        hall = DataHall(name="8k&16k", project_id=project.id)
        s.add_all([leg_t, trunk_t, hall]); s.commit()
        trunks = Discipline(name="16K-EW-LS-Trunk", data_hall_id=hall.id, template_id=trunk_t.id)
        s.add(trunks); s.commit()
        legs = Discipline(name="16K-EW-LS", data_hall_id=hall.id, template_id=leg_t.id, trunk_discipline_id=trunks.id)
        s.add(legs); s.commit()
        s.add(Label(discipline_id=trunks.id, left_text="TRUNK 1 | CBL# | 1", trunk_no="1"))
        for leg in (1, 2):  # leg text carries no number, as in the real file
            s.add(Label(discipline_id=legs.id, left_text=f"EH1A | swp33s{leg} / SU1 | 16K-EW-LS | ", trunk_no="1", leg_no=str(leg)))
        s.commit()
        ids = {"legs": legs.id, "trunks": trunks.id}
    app = FastAPI()
    app.include_router(integrations.router)
    def sessions():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[require_api_key] = lambda: ApiKey(name="test", prefix="test", key_hash="k")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, ids, engine
    engine.dispose()


def sent(send):
    return [(call.args[2].split(" / ")[0], call.args[1].name) for call in send.call_args_list]


def print_one(client, ids, **body):
    with patch.object(integrations, "render_and_send") as send:
        response = client.post("/api/v1/print", json={"discipline_id": ids["legs"], "cable": "1.2", **body})
    return response, sent(send)


def test_a_leg_without_a_number_in_its_text_is_found_by_its_columns(api):
    client, ids, _ = api
    response, labels = print_one(client, ids)
    assert response.status_code == 200
    assert labels == [("EH1A | swp33s2", "Legs")]


def test_with_trunk_prints_both_on_their_own_printers(api):
    client, ids, _ = api
    response, labels = print_one(client, ids, trunk="with")
    assert response.status_code == 200
    assert labels == [("EH1A | swp33s2", "Legs"), ("TRUNK 1 | CBL# | 1", "Trunks")]
    body = response.json()
    assert [p["role"] for p in body["printed"]] == ["leg", "trunk"]
    assert body["left_text"].startswith("EH1A | swp33s2")  # top level still the leg


def test_trunk_only_prints_just_the_trunk(api):
    client, ids, _ = api
    response, labels = print_one(client, ids, trunk="only")
    assert response.status_code == 200 and labels == [("TRUNK 1 | CBL# | 1", "Trunks")]
    assert response.json()["left_text"] == "TRUNK 1 | CBL# | 1"


def test_copies_apply_to_each_label(api):
    client, ids, _ = api
    _, labels = print_one(client, ids, trunk="with", copies=2)
    assert [printer for _, printer in labels] == ["Legs", "Legs", "Trunks", "Trunks"]


def test_a_missing_trunk_refuses_before_sending(api):
    client, ids, engine = api
    with Session(engine) as s:
        legs = s.get(Discipline, ids["legs"]); legs.trunk_discipline_id = None; s.add(legs); s.commit()
    response, labels = print_one(client, ids, trunk="with")
    assert response.status_code == 409 and "no trunk labels linked" in response.json()["detail"]
    assert labels == []


def batch(client, ids, **body):
    with patch.object(integrations, "render_and_send") as send:
        response = client.post("/api/v1/print-batch", json={"discipline_id": ids["legs"], "cables": ["1.1", "1.2"], **body})
    return response.json(), sent(send)


def test_batch_with_trunk_prints_the_trunk_once(api):
    client, ids, _ = api
    body, labels = batch(client, ids, trunk="with")
    assert labels == [("EH1A | swp33s1", "Legs"), ("EH1A | swp33s2", "Legs"), ("TRUNK 1 | CBL# | 1", "Trunks")]
    assert [(r["role"], r["trunk_no"], r["status"]) for r in body["results"]] == [
        ("leg", "1", "printed"), ("leg", "1", "printed"), ("trunk", "1", "printed")]
    assert body["ok"] is True and body["printed"] == 3


def test_batch_trunk_only_prints_distinct_trunks(api):
    client, ids, _ = api
    body, labels = batch(client, ids, trunk="only")
    assert labels == [("TRUNK 1 | CBL# | 1", "Trunks")]
    assert [(r["role"], r["status"]) for r in body["results"]] == [("trunk", "printed")]


def test_batch_without_trunk_is_unchanged(api):
    client, ids, _ = api
    body, labels = batch(client, ids)
    assert [printer for _, printer in labels] == ["Legs", "Legs"]
    assert [r["role"] for r in body["results"]] == ["leg", "leg"]
