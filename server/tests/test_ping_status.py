"""The kiosk status pill reads the printer's own state, not only its TCP port.

A DP4600H with its head open still accepts TCP on 9100, so a reachability-only
pill says "online" while the next job is held. The ping now carries the SNMP
state the print preflight acts on.
"""
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import select

from app import printer_device_status as device
from app.api import printers
from app.models import Printer
from app.printer import PING_BUSY as BUSY
from tests.test_cart_jobs import db  # noqa: F401  (shared fixture with one printer)
from tests.test_panduit_status import reply


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    device._cache.clear()
    monkeypatch.setattr(device.socket, 'socket', MagicMock(side_effect=AssertionError('Unexpected network')))
    monkeypatch.setattr(device.secrets, 'randbelow', lambda _: 122)


def panduit(session, model='DP4600H'):
    printer = session.exec(select(Printer)).first()
    printer.model, printer.snmp_community = model, 'sample'  # what reply() answers with
    session.add(printer)
    session.commit()
    return printer


def ping(session, printer, tcp):
    with patch.object(printers, 'ping_printer', return_value=tcp):
        return printers.ping(printer.id, session)


@pytest.mark.parametrize('cover, flags, expected', [
    (5, b'\x00', 'cover_open'), (6, b'\x40', 'no_media'), (6, b'\x00', 'ready'),
])
def test_reachable_panduit_reports_its_own_state(db, monkeypatch, cover, flags, expected):
    s, _ = db
    printer = panduit(s)
    monkeypatch.setattr(device, '_exchange', lambda *a: reply(3, flags, cover=cover,
                                                              model=b'Panduit DP4600H label printer'))
    result = ping(s, printer, (True, 4.0, ''))
    assert result.ok and result.device_status['state'] == expected


def test_status_is_read_while_this_server_is_printing(db, monkeypatch):
    # SNMP never touches the raw 9100 socket, so a busy slot is no reason to skip it.
    s, _ = db
    printer = panduit(s)
    monkeypatch.setattr(device, '_exchange', lambda *a: reply(1, b'B', cover=6,
                                                              model=b'Panduit DP4600H label printer'))
    result = ping(s, printer, (False, None, BUSY))
    assert result.device_status['state'] == 'no_media'


def test_an_unreachable_printer_is_not_asked_over_snmp(db, monkeypatch):
    s, _ = db
    printer = panduit(s)
    exchange = MagicMock()
    monkeypatch.setattr(device, '_exchange', exchange)
    result = ping(s, printer, (False, None, 'refused'))
    exchange.assert_not_called()
    assert result.device_status is None


def test_tablets_polling_one_printer_share_a_status_read(db, monkeypatch):
    s, _ = db
    printer = panduit(s)
    exchange = MagicMock(return_value=reply(3, b'\x00', model=b'Panduit DP4600H label printer'))
    monkeypatch.setattr(device, '_exchange', exchange)
    for _ in range(3):
        ping(s, printer, (True, 4.0, ''))
    assert exchange.call_count == 1


def test_a_printer_without_snmp_status_keeps_the_plain_ping(db):
    s, _ = db
    printer = s.exec(select(Printer)).first()  # model 'custom'
    result = ping(s, printer, (True, 4.0, ''))
    assert result.ok and result.device_status is None
