from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlmodel import Session, select

from ..db import get_session
from ..models import PrintLog

router = APIRouter(prefix='/api/history', tags=['history'])


def _filters(since, until, project_id, operator):
    def utc(value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    since, until = utc(since), utc(until)
    if since and until and since > until:
        raise HTTPException(400, 'Start time must not be after end time')
    filters = []
    if since: filters.append(PrintLog.ts >= since)
    if until: filters.append(PrintLog.ts < until)
    if project_id is not None: filters.append(PrintLog.project_id == project_id)
    if operator is not None: filters.append(PrintLog.operator == operator)
    return filters


@router.get('', response_model=List[PrintLog])
def list_history(
    limit: int = Query(100, ge=1, le=1000),
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    project_id: Optional[int] = None, operator: Optional[str] = None,
    session: Session = Depends(get_session),
) -> List[PrintLog]:
    return session.exec(select(PrintLog).where(*_filters(since,until,project_id,operator))
                        .order_by(PrintLog.ts.desc(), PrintLog.id.desc()).limit(limit)).all()


@router.get('/summary')
def history_summary(
    since: Optional[datetime] = None, until: Optional[datetime] = None,
    project_id: Optional[int] = None, operator: Optional[str] = None,
    session: Session = Depends(get_session),
):
    filters = _filters(since,until,project_id,operator)
    # Group in SQL over the whole period, never over the paginated recent list.
    # Stable IDs keep renamed employees together and namesakes separate.
    identity = case((PrintLog.operator_employee_id.is_not(None), PrintLog.operator_employee_id),
                    else_=PrintLog.operator)
    grouped = select(
        func.max(PrintLog.id).label('latest_id'),
        func.count(PrintLog.id).label('attempts'),
        func.sum(case((PrintLog.status == 'ok', 1), else_=0)).label('sent'),
        func.sum(case((PrintLog.status == 'error', 1), else_=0)).label('errors'),
        func.sum(case((PrintLog.status == 'uncertain', 1), else_=0)).label('uncertain'),
        func.max(PrintLog.ts).label('last_at'),
    ).where(*filters).group_by(identity, PrintLog.operator_employee_id.is_not(None),
                              PrintLog.operator_source, PrintLog.operator_verified).subquery()
    statement = select(PrintLog, grouped.c.attempts, grouped.c.sent, grouped.c.errors,
                       grouped.c.uncertain, grouped.c.last_at).join(grouped, PrintLog.id == grouped.c.latest_id)
    operators=[]
    totals=dict(attempts=0,sent=0,errors=0,uncertain=0)
    for latest, attempts, sent, errors, uncertain, last_at in session.exec(statement):
        counts=dict(attempts=attempts,sent=sent or 0,errors=errors or 0,uncertain=uncertain or 0)
        for field in totals: totals[field]+=counts[field]
        operators.append(dict(operator=latest.operator,operator_source=latest.operator_source,
                              operator_verified=latest.operator_verified,
                              operator_employee_id=latest.operator_employee_id,last_at=last_at,**counts))
    operators.sort(key=lambda row: (-row['sent'], row['operator'], row['operator_source']))
    return dict(totals=totals,operators=operators)
