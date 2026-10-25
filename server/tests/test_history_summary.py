from datetime import datetime, timezone, timedelta
import pytest
from fastapi import HTTPException
from sqlmodel import SQLModel, Session, create_engine
from app.models import PrintLog
from app.api.history import list_history, history_summary


def test_summary_counts_full_period_and_keeps_verified_identity_separate():
    engine=create_engine('sqlite://');SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        now=datetime(2026,10,25,12,tzinfo=timezone.utc)
        for _ in range(205): s.add(PrintLog(ts=now,operator='Alex',operator_source='rfid',operator_verified=True,project_id=3,project_name='X',status='ok'))
        s.add(PrintLog(ts=now,operator='Alex',project_id=3,status='uncertain'))
        s.add(PrintLog(ts=now,operator='Alex',project_id=4,status='error'))
        s.commit()
        filters=dict(since=datetime(2026,10,25,tzinfo=timezone.utc),until=datetime(2026,10,26,tzinfo=timezone.utc),project_id=3,operator=None)
        summary=history_summary(session=s,**filters)
        assert summary['totals']==dict(attempts=206,sent=205,errors=0,uncertain=1)
        assert len(summary['operators'])==2
        assert len(list_history(limit=20,session=s,**filters))==20
        filters['since']=filters['until']
        assert history_summary(session=s,**filters)['totals']['attempts']==0


def test_history_rejects_reversed_period():
    with pytest.raises(HTTPException) as exc:
        history_summary(since=datetime(2026,10,26),until=datetime(2026,10,25),project_id=None,operator=None,session=None)
    assert exc.value.status_code==400


def test_history_normalizes_offset_filters_to_utc():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(PrintLog(ts=datetime(2026, 10, 25, 12, tzinfo=timezone.utc), status='ok'))
        session.commit()
        offset = timezone(timedelta(hours=-5))
        filters = dict(since=datetime(2026, 10, 25, 7, tzinfo=offset),
                       until=datetime(2026, 10, 25, 8, tzinfo=offset),
                       project_id=None, operator=None, session=session)
        assert history_summary(**filters)['totals']['sent'] == 1
        assert len(list_history(limit=20, **filters)) == 1


def test_employee_identity_survives_rename_and_separates_namesakes():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for employee_id, name in [('employee-1', 'Old Name'), ('employee-1', 'Alex'), ('employee-2', 'Alex')]:
            session.add(PrintLog(operator=name, operator_employee_id=employee_id,
                                 operator_source='rfid', operator_verified=True, status='ok'))
        session.commit()
        result = history_summary(since=None, until=None, project_id=None, operator=None, session=session)
        assert result['totals']['sent'] == 3
        people = {row['operator_employee_id']: row for row in result['operators']}
        assert len(people) == 2
        assert people['employee-1']['sent'] == 2
        assert people['employee-1']['operator'] == 'Alex'
        assert people['employee-2']['sent'] == 1
