from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import ConfigDict
from typing import Literal
from .. import printer_device_status
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy import update
from sqlmodel import Session, select

from ..auth_admin import require_admin
from ..auth_station import require_reader
from ..db import get_session
from ..models import PrintLog, Printer, Template, Station, ProjectPrinterAssignment
from ..printer import PrintError, ping_printer, render_and_send
from ..schemas import MaterialCalibration, PrinterInput, PrinterPatch

class RedactedPrinterRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={'detail': 'Invalid printer settings'})
        return handler


class PrinterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    ip: str
    port: int
    notes: str
    protocol: str
    dpi: int
    model: str
    material_calibrations: dict
    snmp_enabled: bool
    snmp_port: int
    snmp_version: Literal['1', '2c'] = '1'
    snmp_community_configured: bool = False
    snmp_source: Literal['inherited', 'custom'] = 'inherited'
    qr_media_id: str
    qr_label_length_mm: int


def public_printer(printer):
    result = PrinterRead.model_validate(printer)
    result.snmp_version = '2c' if printer.model in printer_device_status.PANDUIT_SNMP_DESCRIPTIONS else '1'
    result.snmp_community_configured = printer.snmp_community is not None
    result.snmp_source = 'custom' if result.snmp_community_configured else 'inherited'
    return result


router = APIRouter(prefix="/api/printers", tags=["printers"], route_class=RedactedPrinterRoute)


def _commit(session: Session, detail: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, detail) from exc


class PingResult(BaseModel):
    printer_id: int
    ok: bool
    ms: Optional[float] = None
    error: str = ""


class TestPrintResult(BaseModel):
    ok: bool
    log_id: Optional[int] = None
    template_used: Optional[str] = None
    detail: str = ""


@router.get("", response_model=List[PrinterRead], dependencies=[Depends(require_admin)])
def list_printers(session: Session = Depends(get_session)) -> List[Printer]:
    return [public_printer(p) for p in session.exec(select(Printer).order_by(Printer.name)).all()]


# Important: declare this BEFORE the catch-all ``/{printer_id}`` so FastAPI
# doesn't try to parse "ping-all" as an int.
@router.get("/ping-all", response_model=List[PingResult], dependencies=[Depends(require_admin)])
def ping_all(session: Session = Depends(get_session)) -> List[PingResult]:
    """Ping every printer. Used by the admin page to render status badges."""
    out: List[PingResult] = []
    for p in session.exec(select(Printer)).all():
        ok, ms, err = ping_printer(p.ip, p.port)
        out.append(PingResult(printer_id=p.id, ok=ok, ms=ms, error=err))
    return out


@router.get("/{printer_id}", response_model=PrinterRead, dependencies=[Depends(require_admin)])
def get_printer(printer_id: int, session: Session = Depends(get_session)) -> Printer:
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    return public_printer(p)


@router.post("", response_model=PrinterRead, dependencies=[Depends(require_admin)])
def create_printer(p: PrinterInput, session: Session = Depends(get_session)) -> Printer:
    row = Printer(**p.persistence_values())
    session.add(row)
    _commit(session, "Printer name already exists")
    session.refresh(row)
    return public_printer(row)


@router.put("/{printer_id}", response_model=PrinterRead, dependencies=[Depends(require_admin)])
def update_printer(
    printer_id: int, patch: PrinterPatch, session: Session = Depends(get_session)
) -> Printer:
    existing = session.get(Printer, printer_id)
    if not existing:
        raise HTTPException(404, "Printer not found")
    try:
        updated = PrinterInput.model_validate({**existing.model_dump(), **patch.model_dump(exclude_unset=True)})
    except ValidationError as exc:
        raise HTTPException(422, "Invalid printer settings") from None
    if (existing.protocol == 'brother_ql') != (updated.protocol == 'brother_ql'):
        if (session.exec(select(Template.id).where(Template.printer_id == printer_id)).first() is not None
                or session.exec(select(Station.id).where(Station.printer_id == printer_id)).first() is not None):
            raise HTTPException(409, 'Reassign cable templates and stations before changing to or from Brother')
    # Calibration is edited through its dedicated pair endpoint, never through
    # a potentially stale full printer form. Changing hardware invalidates it.
    updated.material_calibrations = {sku: MaterialCalibration.model_validate(value) for sku, value in existing.material_calibrations.items()}
    if updated.model != existing.model or updated.ip != existing.ip or updated.port != existing.port:
        updated.material_calibrations = {}
    # Pair saves and settings edits must both compare their read snapshot.
    # In particular, assigning {} to an originally empty ORM field would not
    # issue an UPDATE for it, leaving a concurrently saved correction attached
    # to newly selected hardware.
    snapshot = {name: getattr(existing, name) for name in PrinterInput.model_fields}
    try:
        result = session.execute(
            update(Printer).where(
                Printer.id == printer_id,
                *(getattr(Printer, name) == value for name, value in snapshot.items()),
            ).values(**updated.persistence_values()).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "Printer settings or calibration changed elsewhere; reload and try again")
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Printer name already exists") from exc
    session.refresh(existing)
    return public_printer(existing)


@router.delete("/{printer_id}", dependencies=[Depends(require_admin)])
def delete_printer(printer_id: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    if session.exec(select(Template.id).where(Template.printer_id == printer_id)).first() is not None:
        raise HTTPException(409, "Printer has templates assigned; reassign them before deleting")
    if session.exec(select(Station.id).where(Station.printer_id == printer_id)).first() is not None:
        raise HTTPException(409, "Printer has stations assigned; reassign them before deleting")
    if session.exec(select(ProjectPrinterAssignment.id).where(ProjectPrinterAssignment.printer_id == printer_id)).first() is not None:
        raise HTTPException(409, "Printer is assigned to integration projects; remove assignments before deleting")
    session.delete(p)
    _commit(session, "Printer is still referenced and cannot be deleted")
    return {"deleted": printer_id}


@router.get("/{printer_id}/ping", response_model=PingResult, dependencies=[Depends(require_reader)])
def ping(printer_id: int, session: Session = Depends(get_session)) -> PingResult:
    """TCP-connect check. Fast (~2s timeout) and does not send any bytes."""
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    ok, ms, err = ping_printer(p.ip, p.port)
    return PingResult(printer_id=printer_id, ok=ok, ms=ms, error=err)


@router.post(
    "/{printer_id}/test-print",
    response_model=TestPrintResult,
    dependencies=[Depends(require_admin)],
)
def test_print(
    printer_id: int, session: Session = Depends(get_session)
) -> TestPrintResult:
    """Render a real label and send it to this printer to verify protocol.

    Picks the first template bound to this printer — that's the only way to
    get correct raster dimensions without asking the operator. If the printer
    has no template assigned yet, returns 400 (assign one in Admin → Templates).
    """
    printer = session.get(Printer, printer_id)
    if not printer:
        raise HTTPException(404, "Printer not found")

    if printer.protocol == 'brother_ql':
        raise HTTPException(400, 'Use Admin → QR labels to preview and send a Brother test label')
    template = session.exec(
        select(Template).where(Template.printer_id == printer_id).order_by(Template.id)
    ).first()
    if not template:
        raise HTTPException(
            400,
            f"No template is bound to '{printer.name}'. Create one in Admin → "
            "Templates so we know the label geometry to test with.",
        )

    left = f"TEST {printer.protocol.upper()}"
    right = printer.name[:20]
    log = PrintLog(
        template_name=template.name,
        printer_ip=f"{printer.ip}:{printer.port}",
        printer_name=printer.name,
        operator="admin",
        reason="TEST PRINTER",
        left_text=left,
        right_text=right,
    )
    try:
        render_and_send(template, printer, left, right, "admin", "TEST PRINTER")
    except PrintError as e:
        log.status = "uncertain" if e.uncertain else "error"
        log.error = str(e)
        session.add(log)
        session.commit()
        raise HTTPException(502, f"Test print failed: {e}")

    session.add(log)
    session.commit()
    session.refresh(log)
    return TestPrintResult(ok=True, log_id=log.id, template_used=template.name)


@router.put("/{printer_id}/calibration/{sku}", response_model=PrinterRead, dependencies=[Depends(require_admin)])
def save_calibration(printer_id: int, sku: str, correction: MaterialCalibration, session: Session = Depends(get_session)):
    from ..materials import get_material
    printer = session.get(Printer, printer_id)
    if not printer:
        raise HTTPException(404, "Printer not found")
    if printer.model == "custom" or printer.protocol not in ("jscript", "ezpl"):
        raise HTTPException(400, "Select a Panduit model profile before calibrating")
    try:
        material = get_material(sku)
    except KeyError as exc:
        raise HTTPException(404, "Material not found") from exc
    if not material.supported:
        raise HTTPException(400, material.limitation)
    # Compare-and-swap prevents concurrent saves for different SKUs from losing
    # each other's corrections. A concurrent hardware edit must also conflict.
    old = printer.material_calibrations
    result = session.execute(
        update(Printer).where(
            Printer.id == printer_id, Printer.material_calibrations == old,
            Printer.model == printer.model, Printer.ip == printer.ip, Printer.port == printer.port,
        ).values(material_calibrations={**old, material.sku: correction.model_dump()})
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Printer calibration changed elsewhere; reload and try again")
    _commit(session, "Could not save calibration")
    session.refresh(printer)
    return public_printer(printer)


@router.get("/{printer_id}/status", dependencies=[Depends(require_admin)])
def printer_status(printer_id: int, session: Session = Depends(get_session)):
    printer = session.get(Printer, printer_id)
    if printer is None:
        raise HTTPException(404, "Printer not found")
    config = printer_device_status.DeviceStatusConfig.from_printer(printer)
    ip, port = printer.ip, printer.port
    metadata = public_printer(printer)
    online, _, error = ping_printer(ip, port)
    connection_state = 'reachable' if online else ('busy' if error == 'Printer busy; status check skipped' else 'unreachable')
    status = printer_device_status.device_status(config.printer_id, config.ip, config.model,
        enabled=config.enabled, port=config.port, community_override=config.community)
    return dict(printer_id=printer_id, online=online, connection_state=connection_state, device_status=status,
        snmp_enabled=metadata.snmp_enabled, snmp_port=metadata.snmp_port,
        snmp_version=metadata.snmp_version, snmp_source=metadata.snmp_source,
        qr_defaults={'media_id': metadata.qr_media_id, 'label_length_mm': metadata.qr_label_length_mm})
