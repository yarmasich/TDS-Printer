from contextlib import contextmanager
from unittest.mock import Mock, patch
import socket

import pytest
from app.models import Printer
from app.printer import PrintError
from app.printer_brother import send_brother_job


def device(): return Printer(name='B',ip='192.0.2.1',model='QL-1110NWBc',protocol='brother_ql')


def test_send_half_closes_and_drains_while_holding_endpoint_lock():
    events=[]
    @contextmanager
    def slot(host,port,**kw):
        assert (host,port)==('192.0.2.1',9100)
        events.append('lock'); yield; events.append('unlock')
    s=Mock()
    for name in ['sendall','shutdown','close']:
        getattr(s,name).side_effect=lambda *args,n=name:events.append(n)
    s.recv.side_effect=lambda n:events.append('recv') or b''
    with patch('app.printer_brother.printer_slot',slot),patch('app.printer_brother.socket.create_connection',return_value=s):
        send_brother_job(device(),b'payload')
    assert events==['lock','sendall','shutdown','recv','close','unlock']
    s.shutdown.assert_called_once_with(socket.SHUT_WR)


@pytest.mark.parametrize('stage,uncertain',[('connect',False),('sendall',True),('shutdown',True)])
def test_errors_classify_attempt_without_retry(tmp_path,monkeypatch,stage,uncertain):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR',str(tmp_path))
    s=Mock(); s.recv.return_value=b''
    with patch('app.printer_brother.socket.create_connection',return_value=s) as connect:
        if stage=='connect':connect.side_effect=OSError('offline')
        else:getattr(s,stage).side_effect=socket.timeout('partial')
        with pytest.raises(PrintError) as err:send_brother_job(device(),b'payload')
        assert err.value.uncertain is uncertain
        assert connect.call_count==1


def test_drain_deadline_is_absolute_for_endless_peer(tmp_path,monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR',str(tmp_path))
    now=[0.0]
    s=Mock()
    def recv(n): now[0]+=0.25; return b'reply'
    s.recv.side_effect=recv
    with patch('app.printer_brother.socket.create_connection',return_value=s),patch('app.printer_brother.time.monotonic',side_effect=lambda:now[0]):
        send_brother_job(device(),b'payload',drain_timeout=1)
    assert s.recv.call_count==4
    assert all(call.args[0]<=0.25 for call in s.settimeout.call_args_list)


def test_reset_during_drain_is_uncertain(tmp_path,monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR',str(tmp_path))
    s=Mock();s.recv.side_effect=ConnectionResetError('reset')
    with patch('app.printer_brother.socket.create_connection',return_value=s),pytest.raises(PrintError) as err:
        send_brother_job(device(),b'payload')
    assert err.value.uncertain


def test_busy_or_unavailable_lock_never_connects(tmp_path,monkeypatch):
    from app.printer_dispatch import printer_slot
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR',str(tmp_path))
    with printer_slot(device().ip,9100),patch('app.printer_brother.socket.create_connection') as connect:
        with pytest.raises(PrintError) as err:send_brother_job(device(),b'p',queue_timeout=0)
        assert not err.value.uncertain
        connect.assert_not_called()
    with patch('app.printer_brother.printer_slot',side_effect=OSError('no permission')),patch('app.printer_brother.socket.create_connection') as connect:
        with pytest.raises(PrintError) as err:send_brother_job(device(),b'p')
        assert not err.value.uncertain
        connect.assert_not_called()
