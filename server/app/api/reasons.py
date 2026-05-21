from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Reason

router = APIRouter(prefix="/api/reasons", tags=["reasons"])


@router.get("", response_model=List[Reason])
def list_reasons(session: Session = Depends(get_session)) -> List[Reason]:
    return session.exec(select(Reason).order_by(Reason.sort_order, Reason.text)).all()


@router.post("", response_model=Reason)
def create_reason(r: Reason, session: Session = Depends(get_session)) -> Reason:
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


@router.delete("/{reason_id}")
def delete_reason(reason_id: int, session: Session = Depends(get_session)) -> dict:
    r = session.get(Reason, reason_id)
    if not r:
        raise HTTPException(404, "Reason not found")
    session.delete(r)
    session.commit()
    return {"deleted": reason_id}
