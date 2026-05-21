from typing import List

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import PrintLog

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=List[PrintLog])
def list_history(
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> List[PrintLog]:
    return session.exec(
        select(PrintLog).order_by(PrintLog.ts.desc()).limit(limit)
    ).all()
