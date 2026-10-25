"""Transport locks never touch hardware and are shared across processes."""
import multiprocessing
import os
import time
from unittest.mock import patch

import pytest

from app import printer_dispatch
from app.printer import PrintError, send_to_printer


def _hold_lock(directory, ready):
    os.environ['TDS_PRINTER_LOCK_DIR'] = directory
    with printer_dispatch.printer_slot('Printer.EXAMPLE.', 9100, wait_timeout=1):
        ready.send(True)
        time.sleep(30)


def test_endpoint_normalization():
    assert printer_dispatch.endpoint_key('Printer.EXAMPLE.', 9100) == printer_dispatch.endpoint_key('printer.example', 9100)
    assert printer_dispatch.endpoint_key('2001:0db8:0:0::1', 9100) == printer_dispatch.endpoint_key('2001:db8::1', 9100)
    assert printer_dispatch.endpoint_key('printer.example', 9100) != printer_dispatch.endpoint_key('printer.example', 9101)


def test_process_serialization_timeout_and_crash_release(tmp_path, monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR', str(tmp_path))
    ctx = multiprocessing.get_context('spawn')
    ready, child_ready = ctx.Pipe(duplex=False)
    worker = ctx.Process(target=_hold_lock, args=(str(tmp_path), child_ready))
    worker.start()
    try:
        assert ready.poll(10), 'child failed to acquire lock'
        assert ready.recv()
        with pytest.raises(printer_dispatch.PrinterBusy):
            with printer_dispatch.printer_slot('printer.example', 9100, wait_timeout=0.05):
                pytest.fail('concurrent sender entered')
        # A busy device must not delay a different device or port.
        with printer_dispatch.printer_slot('other', 9100, wait_timeout=0):
            pass
        with printer_dispatch.printer_slot('printer.example', 9101, wait_timeout=0):
            pass
        worker.terminate()
        worker.join(10)
        assert not worker.is_alive()
        with printer_dispatch.printer_slot('printer.example', 9100, wait_timeout=0.2):
            pass
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(10)


def test_busy_transport_does_not_connect_or_report_uncertain(tmp_path, monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR', str(tmp_path))
    with printer_dispatch.printer_slot('printer', 9100):
        with patch('socket.create_connection') as connect:
            with pytest.raises(PrintError) as error:
                send_to_printer('printer', 9100, b'job', queue_timeout=0)
            assert not error.value.uncertain
            connect.assert_not_called()


def test_partial_send_releases_slot_but_is_never_retried(tmp_path, monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR', str(tmp_path))
    with patch('socket.create_connection') as connect:
        connect.return_value.__enter__.return_value.sendall.side_effect = OSError('partial')
        with pytest.raises(PrintError) as error:
            send_to_printer('printer', 9100, b'job')
        assert error.value.uncertain
        assert connect.call_count == 1
    with printer_dispatch.printer_slot('printer', 9100, wait_timeout=0):
        pass


def test_cleanup_failure_after_send_is_uncertain(tmp_path, monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR', str(tmp_path))
    original_close = os.close

    def failing_close(fd):
        original_close(fd)
        raise OSError('cleanup failed')

    with patch('socket.create_connection') as connect, patch.object(printer_dispatch.os, 'close', side_effect=failing_close):
        with pytest.raises(PrintError) as error:
            send_to_printer('printer', 9100, b'job')
        assert error.value.uncertain
        connect.return_value.__enter__.return_value.sendall.assert_called_once_with(b'job')


@pytest.mark.parametrize('route', ['direct', 'draft', 'printer', 'integration'])
def test_non_cart_routes_preserve_uncertain_log(route):
    from fastapi import HTTPException
    from sqlmodel import Session, SQLModel, create_engine, select
    from app.api import print as print_api, printers, integrations
    from app.models import DataHall, Discipline, Label, Printer, PrintLog, Project, Template
    from app.rfid import OperatorIdentity

    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        device = Printer(name='P', ip='192.0.2.1')
        session.add(device)
        session.commit()
        template = Template(name='T', printer_id=device.id, bytes_per_row=20, height=100, left_bottom=50, left_right=80, right_bottom=50, right_left=80, right_right=160)
        session.add(template)
        session.commit()
        session.refresh(template)
        project = Project(name='Project')
        session.add(project); session.commit()
        hall = DataHall(project_id=project.id, name='Hall')
        session.add(hall); session.commit()
        disc = Discipline(data_hall_id=hall.id, name='Discipline', template_id=template.id)
        session.add(disc); session.commit()
        label = Label(discipline_id=disc.id)
        session.add(label); session.commit()
        session.refresh(template)
        error = PrintError('Outcome unknown; check physical labels before retrying.', uncertain=True)
        if route == 'integration':
            with patch.object(integrations, 'render_and_send', side_effect=error):
                integrations._print_label(label, template, device, '', '', session, OperatorIdentity('', 'api'))
        else:
            module = printers if route == 'printer' else print_api
            with patch.object(module, 'render_and_send', side_effect=error), pytest.raises(HTTPException):
                if route == 'direct':
                    print_api.submit_print(print_api.PrintRequest(label_id=label.id), session)
                elif route == 'draft':
                    print_api.test_print(print_api.TestPrintRequest(template=template.model_dump(), printer_id=device.id), session)
                else:
                    printers.test_print(device.id, session)
        assert session.exec(select(PrintLog)).one().status == 'uncertain'
    engine.dispose()
