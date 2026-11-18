"""Kiosk printing asks a Panduit printer for its state before sending.

A printer that buffers a job while its cover is open reports the send as a
success, so the cart would drop the row and the label could appear later or
never. Only a recognised fault holds a job; an unknown state never does.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app import printer_device_status as device
from app.api import cart, print as print_api
from app.models import CartItem, DataHall, Discipline, Label, Printer, PrintLog, Template
from tests.test_cart_jobs import db  # noqa: F401  (shared cart fixture)
from tests.test_panduit_status import reply, status_reads


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    device._cache.clear()
    monkeypatch.setattr(device.socket, 'socket', MagicMock(side_effect=AssertionError('Unexpected network')))
    monkeypatch.setattr(device.secrets, 'randbelow', lambda _: 122)


def panduit(session, **fields):
    printer = session.exec(select(Printer)).first()
    printer.model = 'DP4300H'
    printer.snmp_community = 'sample'  # what reply() answers with
    for key, value in fields.items():
        setattr(printer, key, value)
    session.add(printer)
    session.commit()
    return printer


def snmp(monkeypatch, *, status=3, flags=b'\0', cover=6, error=None):
    exchange = MagicMock(side_effect=error) if error else MagicMock(return_value=reply(status, flags, cover=cover))
    monkeypatch.setattr(device, '_exchange', exchange)
    return exchange


@pytest.mark.parametrize('flags, wording', [
    (b'\x08', 'cover is open'), (b'\x40', 'no labels'), (b'\x04', 'fault'),
])
def test_cart_holds_every_label_while_the_printer_reports_a_fault(db, monkeypatch, flags, wording):
    s, _ = db
    panduit(s)
    snmp(monkeypatch, flags=flags)
    with patch.object(cart, 'render_and_send') as send:
        result = cart.print_all(cart.PrintAllRequest(sid='sid'), s)
    send.assert_not_called()
    assert result.ok == 0 and len(result.errors) == 2
    assert all(not e['uncertain'] and wording in e['error'] for e in result.errors)
    rows = s.exec(select(CartItem)).all()
    # Nothing reached the printer, so the rows are safe to print again.
    assert [r.status for r in rows] == ['queued', 'queued']
    assert all(r.claim_token == '' for r in rows)


@pytest.mark.parametrize('kwargs', [
    dict(status=3, flags=b'\0'),          # ready
    dict(status=4, flags=b'\0'),          # busy with another job
    dict(status=3, flags=b'\x80'),        # low-paper warning: ready, never held
    dict(error=TimeoutError('silent')),   # SNMP blocked or switched off on the device
])
def test_cart_prints_unless_a_fault_is_recognised(db, monkeypatch, kwargs):
    s, _ = db
    panduit(s)
    snmp(monkeypatch, **kwargs)
    with patch.object(cart, 'render_and_send') as send:
        result = cart.print_all(cart.PrintAllRequest(sid='sid'), s)
    assert result.ok == send.call_count == 2


def test_cart_asks_each_printer_once_per_job(db, monkeypatch):
    s, _ = db
    panduit(s)
    exchange = snmp(monkeypatch)
    with patch.object(cart, 'render_and_send'):
        cart.print_all(cart.PrintAllRequest(sid='sid'), s)
    # One status GET per job (plus its separate counter GET), not one per label.
    assert status_reads(exchange) == 1


@pytest.mark.parametrize('fields', [dict(snmp_enabled=False), dict(model='custom')])
def test_printers_without_panduit_snmp_are_never_asked(db, monkeypatch, fields):
    s, _ = db
    panduit(s, **fields)
    exchange = snmp(monkeypatch, flags=b'\x08')
    with patch.object(cart, 'render_and_send') as send:
        result = cart.print_all(cart.PrintAllRequest(sid='sid'), s)
    exchange.assert_not_called()
    assert result.ok == send.call_count == 2


def test_a_faulted_printer_does_not_hold_labels_for_a_healthy_one(db, monkeypatch):
    s, _ = db
    faulted = panduit(s)
    healthy = Printer(name='Healthy', ip='192.0.2.2', model='custom')
    s.add(healthy); s.commit()
    template = Template(name='T2', printer_id=healthy.id, bytes_per_row=20, height=100)
    hall = s.exec(select(DataHall)).first()
    s.add(template); s.commit()
    discipline = Discipline(data_hall_id=hall.id, name='D2', template_id=template.id)
    s.add(discipline); s.commit()
    label = Label(discipline_id=discipline.id, left_text='CBL#2.1')
    s.add(label); s.commit()
    cart.add_to_cart(cart.AddRequest(sid='sid', label_id=label.id), s)
    snmp(monkeypatch, flags=b'\x08')
    with patch.object(cart, 'render_and_send') as send:
        result = cart.print_all(cart.PrintAllRequest(sid='sid'), s)
    assert send.call_count == result.ok == 1
    assert send.call_args.args[1].id == healthy.id
    held = s.exec(select(CartItem)).all()
    assert len(held) == 2 and all(r.status == 'queued' for r in held)
    assert {r.printer_name: (r.sent, r.failed) for r in result.printers}.get('Healthy') == (1, 0)
    assert faulted.name in result.errors[0]['error']


def test_single_print_refuses_while_the_printer_reports_a_fault(db, monkeypatch):
    s, _ = db
    panduit(s)
    snmp(monkeypatch, flags=b'\x08')
    label = s.exec(select(Label)).first()
    with patch.object(print_api, 'render_and_send') as send:
        with pytest.raises(HTTPException) as exc:
            print_api.submit_print(print_api.PrintRequest(label_id=label.id), s, None)
    send.assert_not_called()
    assert 'cover is open' in exc.value.detail
    log = s.exec(select(PrintLog)).one()
    assert log.status == 'error' and 'cover is open' in log.error


def test_single_print_proceeds_when_the_state_is_unknown(db, monkeypatch):
    s, _ = db
    panduit(s)
    snmp(monkeypatch, error=TimeoutError('silent'))
    label = s.exec(select(Label)).first()
    with patch.object(print_api, 'render_and_send') as send:
        assert print_api.submit_print(print_api.PrintRequest(label_id=label.id), s, None)['ok']
    send.assert_called_once()


def test_cart_holds_labels_while_the_printhead_is_open(db, monkeypatch):
    # The DP4600H reports idle with no error flags while its head is open.
    s, _ = db
    panduit(s)
    snmp(monkeypatch, status=3, flags=b'\x00', cover=5)
    with patch.object(cart, 'render_and_send') as send:
        result = cart.print_all(cart.PrintAllRequest(sid='sid'), s)
    send.assert_not_called()
    assert result.ok == 0
    assert all('cover is open' in e['error'] for e in result.errors)
