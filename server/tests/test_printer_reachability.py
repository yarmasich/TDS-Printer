from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from unittest.mock import Mock, MagicMock

import pytest
from app import printer_reachability as reach
from app.printer_dispatch import PrinterBusy
from test_scoped_routing import scope, policy

@pytest.fixture(autouse=True)
def reset(monkeypatch):
    reach._cache.clear()
    reach._inflight.clear()
    monkeypatch.setattr(reach.socket, 'create_connection', MagicMock())
    @contextmanager
    def slot(*args, **kwargs):
        assert kwargs == {'wait_timeout': 0}
        yield
    monkeypatch.setattr(reach, 'printer_slot', slot)

@pytest.mark.parametrize('error,expected', [(None, True), (OSError('offline'), False), (RuntimeError('other'), None), (PrinterBusy('busy'), None)])
def test_connection_only(error, expected):
    reach.socket.create_connection.side_effect = error
    assert reach.printer_status(1, '192.0.2.1', 9100) is expected
    reach.socket.create_connection.assert_called_once_with(('192.0.2.1', 9100), timeout=1.0)
    reach.socket.create_connection.return_value.__enter__.return_value.send.assert_not_called()

def test_busy_skips_socket(monkeypatch):
    @contextmanager
    def busy(*args, **kwargs):
        raise PrinterBusy('busy')
        yield
    monkeypatch.setattr(reach, 'printer_slot', busy)
    assert reach.printer_status(1, 'host', 9100) is None
    reach.socket.create_connection.assert_not_called()

def test_cache_ttl_address_and_size(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(reach, 'monotonic', lambda: now[0])
    assert reach.printer_status(1, 'host', 9100) is True
    assert reach.printer_status(1, 'host', 9100) is True
    assert reach.socket.create_connection.call_count == 1
    reach.printer_status(1, 'changed', 9100)
    reach.printer_status(1, 'changed', 9101)
    assert reach.socket.create_connection.call_count == 3
    now[0] = 15.0
    reach.printer_status(1, 'host', 9100)
    assert reach.socket.create_connection.call_count == 4
    for pid in range(1025):
        reach.printer_status(pid, 'other', 9100)
    assert len(reach._cache) == 1024
    assert (0, 'other', 9100) not in reach._cache

def test_singleflight(monkeypatch):
    started, release = Event(), Event()
    def connect(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return MagicMock()
    monkeypatch.setattr(reach.socket, 'create_connection', connect)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(reach.printer_status, 1, 'host', 9100)
        assert started.wait(2)
        try:
            assert pool.submit(reach.printer_status, 1, 'host', 9100).result(1) is None
        finally:
            release.set()
        assert first.result(1) is True

def test_sorted_cap(monkeypatch):
    probe = Mock(return_value=True)
    monkeypatch.setattr(reach, 'printer_status', probe)
    statuses = reach.printer_statuses([(pid, 'host', 9100) for pid in reversed(range(35))])
    assert sorted(call.args[0] for call in probe.call_args_list) == list(range(32))
    assert statuses[31] is True and statuses[32] is None and statuses[34] is None

def test_scoped_opt_in_only_assigned_cable(scope, monkeypatch):
    c, _, headers, project, _ = scope
    c.put(f'/api/v1/integrations/projects/{project}/policy', headers=headers, json=policy(project))
    base = f'/api/v1/integrations/projects/{project}/printers'
    probe = Mock(return_value={1: False})
    monkeypatch.setattr(reach, 'printer_statuses', probe)
    for query in ('purpose=cable_labels', 'purpose=cable_labels&ping=false', 'purpose=qr_labels&ping=false'):
        response = c.get(f'{base}?{query}', headers=headers)
        assert response.status_code == 200
        assert response.json()['printers'][0]['online'] is None
    probe.assert_not_called()
    result = c.get(f'{base}?purpose=cable_labels&ping=true', headers=headers).json()
    assert result['printers'][0]['online'] is False
    probe.assert_called_once_with([(1, '192.0.2.1', 9100)])
    assert not {'ip', 'port', 'error', 'latency_ms'} & result['printers'][0].keys()
    probe.reset_mock()
    from uuid import uuid4
    assert c.get(f'/api/v1/integrations/projects/{uuid4()}/printers?purpose=cable_labels&ping=true', headers=headers).json()['printers'] == []
    assert not probe.called or probe.call_args.args == ([],)

def test_four_workers_and_print_queue_budget(monkeypatch):
    from threading import Lock
    from app import printer_dispatch
    from inspect import signature
    assert signature(printer_dispatch.printer_slot).parameters['wait_timeout'].default == 30.0
    lock, four_started, release = Lock(), Event(), Event()
    active = [0, 0]
    def probe(*args):
        with lock:
            active[0] += 1
            active[1] = max(active)
            if active[0] == 4:
                four_started.set()
        assert release.wait(2)
        with lock:
            active[0] -= 1
        return True
    monkeypatch.setattr(reach, 'printer_status', probe)
    with ThreadPoolExecutor(1) as pool:
        task = pool.submit(reach.printer_statuses, [(pid, 'host', 9100) for pid in range(32)])
        try:
            assert four_started.wait(2)
            assert active[1] == 4
        finally:
            release.set()
        assert all(task.result(2).values())
    assert active[1] == 4

def test_incompatible_assignment_is_not_probed(scope, monkeypatch):
    from app.models import Printer
    from sqlmodel import Session
    c, engine, headers, project, _ = scope
    c.put(f'/api/v1/integrations/projects/{project}/policy', headers=headers, json=policy(project))
    with Session(engine) as session:
        printer = session.get(Printer, 1)
        printer.protocol = 'brother_ql'
        session.add(printer)
        session.commit()
    probe = Mock()
    monkeypatch.setattr(reach, 'printer_statuses', probe)
    result = c.get(f'/api/v1/integrations/projects/{project}/printers?purpose=cable_labels&ping=true', headers=headers).json()
    assert result['printers'] == []
    probe.assert_not_called()


def test_slot_setup_oserror_is_unknown(monkeypatch):
    @contextmanager
    def unavailable(*args, **kwargs):
        raise PermissionError('lock directory unavailable')
        yield
    monkeypatch.setattr(reach, 'printer_slot', unavailable)
    assert reach.printer_status(1, 'host', 9100) is None
    reach.socket.create_connection.assert_not_called()
