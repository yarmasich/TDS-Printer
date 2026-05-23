from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth_admin import require_admin
from ..db import get_session
from ..models import Printer
from ..printer import ping_printer

router = APIRouter(prefix="/api/printers", tags=["printers"])


class PingResult(BaseModel):
    printer_id: int
    ok: bool
    ms: Optional[float] = None
    error: str = ""


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
def create_printer(p: Printer, session: Session = Depends(get_session)) -> Printer:
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.put("/{printer_id}", response_model=Printer, dependencies=[Depends(require_admin)])
def update_printer(
    printer_id: int, patch: Printer, session: Session = Depends(get_session)
) -> Printer:
    existing = session.get(Printer, printer_id)
    if not existing:
        raise HTTPException(404, "Printer not found")
    for k, v in patch.model_dump(exclude_unset=True, exclude={"id"}).items():
        setattr(existing, k, v)
    session.add(existing)
    session.commit()
    session.refresh(existing)
    return existing


@router.delete("/{printer_id}", dependencies=[Depends(require_admin)])
def delete_printer(printer_id: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    session.delete(p)
    session.commit()
    return {"deleted": printer_id}


@router.get("/{printer_id}/ping", response_model=PingResult)
def ping(printer_id: int, session: Session = Depends(get_session)) -> PingResult:
    """TCP-connect check. Fast (~2s timeout) and does not send any bytes."""
    p = session.get(Printer, printer_id)
    if not p:
        raise HTTPException(404, "Printer not found")
    ok, ms, err = ping_printer(p.ip, p.port)
    return PingResult(printer_id=printer_id, ok=ok, ms=ms, error=err)
