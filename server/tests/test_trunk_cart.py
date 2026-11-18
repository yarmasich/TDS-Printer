"""The cart adds a leg, its trunk, or both — and prints each on its own printer.

Legs and trunks use different label stock (Turn-Tell vs 2" x 4"
self-laminating), so "together" means one job across two printers.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import cart
from app.models import CartItem, DataHall, Discipline, Label, Printer, Project, Template


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/trunk.db")
    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        leg_printer, trunk_printer = Printer(name="Legs", ip="192.0.2.1"), Printer(name="Trunks", ip="192.0.2.2")
        project = Project(name="Nscale")
        s.add_all([leg_printer, trunk_printer, project]); s.commit()
        leg_t = Template(name="R200x150", printer_id=leg_printer.id, bytes_per_row=20, height=100)
        trunk_t = Template(name="S200X400VATY", printer_id=trunk_printer.id, bytes_per_row=20, height=100)
        hall = DataHall(project_id=project.id, name="8k&16k")
        s.add_all([leg_t, trunk_t, hall]); s.commit()
        trunks = Discipline(data_hall_id=hall.id, name="16K-EW-LS-Trunk", template_id=trunk_t.id)
        s.add(trunks); s.commit()
        legs = Discipline(data_hall_id=hall.id, name="16K-EW-LS", template_id=leg_t.id, trunk_discipline_id=trunks.id)
        s.add(legs); s.commit()
        s.add_all([Label(discipline_id=trunks.id, left_text="TRUNK 1", trunk_no="1"),
                   Label(discipline_id=trunks.id, left_text="TRUNK 2", trunk_no="2")])
        for leg in (1, 2):
            s.add(Label(discipline_id=legs.id, left_text=f"LEG 1.{leg}", trunk_no="1", leg_no=str(leg)))
        s.add(Label(discipline_id=legs.id, left_text="OLD LEG", trunk_no=None))
        s.commit()
        yield s, legs, trunks
    engine.dispose()


def label(s, text):
    return s.exec(select(Label).where(Label.left_text == text)).one()


def add(s, text, trunk="none"):
    return cart.add_to_cart(cart.AddRequest(sid="tablet", label_id=label(s, text).id, trunk=trunk), s)


def cart_texts(s):
    rows = s.exec(select(CartItem).where(CartItem.session_id == "tablet").order_by(CartItem.id)).all()
    return [r.left_text for r in rows]


def test_with_trunk_adds_the_leg_and_its_trunk(db):
    s, _, _ = db
    add(s, "LEG 1.1", "with")
    assert cart_texts(s) == ["LEG 1.1", "TRUNK 1"]


def test_trunk_only_adds_just_the_trunk(db):
    s, _, _ = db
    add(s, "LEG 1.2", "only")
    assert cart_texts(s) == ["TRUNK 1"]


def test_a_trunk_already_in_the_cart_is_not_added_twice(db):
    # Adding all 36 legs of a trunk "with trunk" must queue one trunk label.
    s, _, _ = db
    add(s, "LEG 1.1", "with")
    add(s, "LEG 1.2", "with")
    add(s, "LEG 1.2", "only")
    assert cart_texts(s) == ["LEG 1.1", "TRUNK 1", "LEG 1.2"]


def test_the_default_adds_only_the_leg(db):
    s, _, _ = db
    add(s, "LEG 1.1")
    assert cart_texts(s) == ["LEG 1.1"]


@pytest.mark.parametrize("text, setup, message", [
    ("OLD LEG", None, "no trunk number"),
    ("LEG 1.1", "unlink", "no trunk labels linked"),
    ("LEG 1.1", "drop_trunk", "No trunk label 1"),
])
def test_a_missing_trunk_refuses_and_adds_nothing(db, text, setup, message):
    s, legs, trunks = db
    if setup == "unlink":
        legs.trunk_discipline_id = None; s.add(legs); s.commit()
    if setup == "drop_trunk":
        s.delete(label(s, "TRUNK 1")); s.commit()
    with pytest.raises(HTTPException) as exc:
        add(s, text, "with")
    assert exc.value.status_code in (404, 409) and message in exc.value.detail
    assert cart_texts(s) == []


def test_together_prints_each_label_on_its_own_printer(db):
    s, _, _ = db
    add(s, "LEG 1.1", "with")
    with patch.object(cart, "render_and_send") as send:
        result = cart.print_all(cart.PrintAllRequest(sid="tablet"), s)
    assert result.ok == 2
    sent = {call.args[2]: call.args[1].name for call in send.call_args_list}
    assert sent == {"LEG 1.1": "Legs", "TRUNK 1": "Trunks"}
