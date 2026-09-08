from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from app.api import cart
from app.models import CartItem, DataHall, Discipline, Label, Printer, PrintLog, Project, Template
from app.printer import PrintError


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/cart.db")
    @event.listens_for(engine, "connect")
    def fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        p=Printer(name="P",ip="192.0.2.1"); proj=Project(name="P")
        s.add_all([p,proj]); s.commit()
        t=Template(name="T",printer_id=p.id,bytes_per_row=20,height=100)
        h=DataHall(project_id=proj.id,name="H"); s.add_all([t,h]); s.commit()
        d=Discipline(data_hall_id=h.id,name="D",template_id=t.id)
        s.add(d); s.commit()
        for i in range(2):
            lb=Label(discipline_id=d.id,left_text=f"CBL#1.{i}")
            s.add(lb); s.commit()
            cart.add_to_cart(cart.AddRequest(sid="sid",label_id=lb.id),s)
        yield s, engine
    engine.dispose()


def test_overlapping_request_cannot_claim_same_cart(db):
    s, engine=db
    seen=[]
    def send(*args):
        seen.append(args[2])
        with Session(engine) as other:
            with patch.object(cart, "render_and_send"):
                with pytest.raises(HTTPException) as exc:
                    cart.print_all(cart.PrintAllRequest(sid="sid"),other)
            assert exc.value.status_code == 409
    with patch.object(cart,"render_and_send",side_effect=send):
        result=cart.print_all(cart.PrintAllRequest(sid="sid"),s)
    assert result.ok == len(seen) == 2
    assert s.exec(select(CartItem)).all() == []


def test_success_is_durable_before_later_unexpected_error(db):
    s,_=db
    with patch.object(cart,"render_and_send",side_effect=[None,ValueError("render exploded")]):
        result=cart.print_all(cart.PrintAllRequest(sid="sid"),s)
    assert result.ok == 1
    remaining=s.exec(select(CartItem)).all()
    assert len(remaining)==1
    assert remaining[0].status == "uncertain"
    with patch.object(cart,"render_and_send") as send:
        with pytest.raises(HTTPException):
            cart.print_all(cart.PrintAllRequest(sid="sid"),s)
    send.assert_not_called()


def test_safe_failure_can_retry_without_reprinting_success(db):
    s,_=db
    with patch.object(cart,"render_and_send",side_effect=[None,PrintError("offline")]):
        result=cart.print_all(cart.PrintAllRequest(sid="sid"),s)
    assert result.ok == 1
    remaining=s.exec(select(CartItem)).all()
    assert len(remaining)==1 and remaining[0].status == "queued"
    with patch.object(cart,"render_and_send") as send:
        result=cart.print_all(cart.PrintAllRequest(sid="sid"),s)
    assert result.ok == send.call_count == 1


def test_uncertain_send_is_not_automatically_retried(db):
    s,_=db
    with patch.object(cart,"render_and_send",side_effect=PrintError("partial write", uncertain=True)):
        result=cart.print_all(cart.PrintAllRequest(sid="sid"),s)
    assert result.ok == 0
    assert all(row.status=="uncertain" for row in s.exec(select(CartItem)).all())


def test_active_cart_cannot_be_cleared_or_removed(db):
    s,engine=db
    ident=s.exec(select(CartItem)).first().id
    def send(*_):
        with Session(engine) as other:
            for action in (lambda: cart.clear_cart("sid",other), lambda: cart.remove_item(ident,"sid",other)):
                with pytest.raises(HTTPException) as exc: action()
                assert exc.value.status_code == 409
    with patch.object(cart,"render_and_send",side_effect=send):
        cart.print_all(cart.PrintAllRequest(sid="sid"),s)


def test_interrupted_claim_becomes_uncertain_not_queued(db):
    s,_=db
    for row in s.exec(select(CartItem)).all():
        row.status="printing"
        row.claim_token="interrupted"
        row.claimed_at=datetime.now(timezone.utc)-timedelta(minutes=10)
        s.add(row)
    s.commit()
    rows=cart.list_cart("sid",s)
    assert all(row.status=="uncertain" for row in rows)


def test_preserved_cart_can_be_explicitly_printed_again(db):
    s,_=db
    with patch.object(cart,"render_and_send"):
        cart.print_all(cart.PrintAllRequest(sid="sid",clear_after=False),s)
    assert len(cart.list_cart("sid",s))==2
    assert all(row.status=="queued" for row in cart.list_cart("sid",s))


def test_orphaned_uncertain_snapshot_remains_visible(db):
    s,_=db
    item=CartItem(session_id="sid", label_id=None, left_text="Legacy snapshot", status="uncertain")
    s.add(item); s.commit()
    ident=item.id
    assert any(row.id==ident and row.status=="uncertain" for row in cart.list_cart("sid",s))
