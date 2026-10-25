"""Printer settings must not overwrite corrections saved during an edit."""
import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.api.printers import save_calibration, update_printer
from app.models import Printer
from app.schemas import MaterialCalibration, PrinterPatch


@pytest.mark.parametrize('initial', [{}, {'R200X150V1T': {'x_mm': 1, 'y_mm': 0}}])
def test_hardware_edit_conflicts_with_concurrent_calibration(tmp_path, initial):
    engine = create_engine(f'sqlite:///{tmp_path}/race.db')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as setup:
        printer = Printer(name='P', ip='old-host', model='DP4300H', protocol='jscript',
                          material_calibrations=initial)
        setup.add(printer)
        setup.commit()
        printer_id = printer.id
    with Session(engine) as edit, Session(engine) as calibration:
        # Keep the object alive in the identity map to model a request that has
        # read settings before another request saves a correction.
        stale = edit.get(Printer, printer_id)
        save_calibration(printer_id, 'R200X150V1T', MaterialCalibration(x_mm=2), calibration)
        with pytest.raises(HTTPException) as exc:
            update_printer(printer_id, PrinterPatch(ip='new-host'), edit)
        assert exc.value.status_code == 409
        edit.refresh(stale)
        assert stale.ip == 'old-host'
        assert stale.material_calibrations['R200X150V1T']['x_mm'] == 2
    engine.dispose()


def test_printer_rename_conflict_is_reported(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/duplicate.db')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = Printer(name='One', ip='host')
        session.add(first)
        session.add(Printer(name='Two', ip='host'))
        session.commit()
        with pytest.raises(HTTPException) as exc:
            update_printer(first.id, PrinterPatch(name='Two'), session)
        assert exc.value.status_code == 409
    engine.dispose()
