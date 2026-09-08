from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth_admin import require_admin
from ..db import get_session
from ..models import PrintLog, Printer, Template
from ..printer import PrintError, ping_printer, render_and_send
from ..schemas import PrinterInput, PrinterPatch

router = APIRouter(prefix="/api/printers", tags=["printers"])


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


@router.get("", response_model=List[Printer], dependencies=[Depends(require_admin)])
def list_printers(session: Session = Depends(get_session)) -> List[Printer]:
    return session.exec(select(Printer).order_by(Printer.name)).all()


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


@router.get("/{printer_id}", response_model=Printer, dependencies=[Depends(require_admin)])
def get_printer(printer_id: int, session: Session = Depends(get_session)) -> Printer:
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    return p


@router.post("", response_model=Printer, dependencies=[Depends(require_admin)])
def create_printer(p: PrinterInput, session: Session = Depends(get_session)) -> Printer:
    row = Printer(**p.model_dump())
    session.add(row)
    _commit(session, "Printer name already exists")
    session.refresh(row)
    return row


@router.put("/{printer_id}", response_model=Printer, dependencies=[Depends(require_admin)])
def update_printer(
    printer_id: int, patch: PrinterPatch, session: Session = Depends(get_session)
) -> Printer:
    existing = session.get(Printer, printer_id)
    if not existing:
        raise HTTPException(404, "Printer not found")
    try:
        updated = PrinterInput.model_validate({**existing.model_dump(), **patch.model_dump(exclude_unset=True)})
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    for k, v in updated.model_dump().items():
        setattr(existing, k, v)
    session.add(existing)
    _commit(session, "Printer name already exists")
    session.refresh(existing)
    return existing


@router.delete("/{printer_id}", dependencies=[Depends(require_admin)])
def delete_printer(printer_id: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    if session.exec(select(Template.id).where(Template.printer_id == printer_id)).first() is not None:
        raise HTTPException(409, "Printer has templates assigned; reassign them before deleting")
    session.delete(p)
    _commit(session, "Printer is still referenced and cannot be deleted")
    return {"deleted": printer_id}


@router.get("/{printer_id}/ping", response_model=PingResult)
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
        operator="admin",
        reason="TEST PRINTER",
        left_text=left,
        right_text=right,
    )
    try:
        render_and_send(template, printer, left, right, "admin", "TEST PRINTER")
    except PrintError as e:
        log.status = "error"
        log.error = str(e)
        session.add(log)
        session.commit()
        raise HTTPException(502, f"Test print failed: {e}")

    session.add(log)
    session.commit()
    session.refresh(log)
    return TestPrintResult(ok=True, log_id=log.id, template_used=template.name)
