"""Re-uploading a discipline's workbook replaces its labels instead of doubling them.

Each upload used to append an import, so re-importing a corrected file left two
copies of every leg and every API query for it came back ambiguous.
"""
import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.import_ import upload
from app.models import CartItem, DataHall, Discipline, Import, Label, PrintLog, Project

HEADER = ['A-Leg', 'Z-Leg', 'Trunk#', 'Leg #']


@pytest.fixture
def s():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name='Nscale'); session.add(project); session.commit()
        hall = DataHall(name='8k&16k', project_id=project.id); session.add(hall); session.commit()
        legs = Discipline(name='16K-EW-LS', data_hall_id=hall.id)
        other = Discipline(name='8K-IBLFSP', data_hall_id=hall.id)
        session.add_all([legs, other]); session.commit()
        yield session, legs, other
    engine.dispose()


def xlsx(rows) -> bytes:
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    out = BytesIO(); wb.save(out); wb.close()
    return out.getvalue()


def legs_file(*legs, text='swp'):
    return xlsx([HEADER] + [[f'{text}{t}s{l}', f'CNR {t}.{l}', t, l] for t, l in legs])


def send(session, disc, content, name='legs.xlsx', **form):
    return asyncio.run(upload(disc.id, UploadFile(filename=name, file=BytesIO(content)), session, **form))


def texts(session, disc):
    return sorted(l.left_text for l in session.exec(select(Label).where(Label.discipline_id == disc.id)).all())


def test_replace_swaps_every_earlier_import_for_the_new_file(s):
    session, legs, other = s
    send(session, legs, legs_file((1, 1), (1, 2)))
    send(session, legs, legs_file((1, 1), (1, 2)))  # the duplicate import seen in production
    send(session, other, legs_file((9, 9)))
    result = send(session, legs, legs_file((1, 1), (1, 2), (1, 3), text='new'), name='fixed.xlsx', replace=True)
    assert (result['replaced_imports'], result['labels_removed'], result['rows']) == (2, 4, 3)
    assert texts(session, legs) == ['new1s1', 'new1s2', 'new1s3']
    assert [i.filename for i in session.exec(select(Import).where(Import.discipline_id == legs.id)).all()] == ['fixed.xlsx']
    assert texts(session, other) == ['swp9s9']  # another discipline is never touched


def test_a_failing_replacement_keeps_the_old_labels(s):
    session, legs, _ = s
    send(session, legs, legs_file((1, 1), (1, 2)))
    with pytest.raises(HTTPException) as exc:
        send(session, legs, b'not a workbook', name='broken.xlsx', replace=True)
    assert exc.value.status_code == 400
    assert texts(session, legs) == ['swp1s1', 'swp1s2']
    assert len(session.exec(select(Import)).all()) == 1


def test_without_replace_an_upload_still_appends(s):
    session, legs, _ = s
    send(session, legs, legs_file((1, 1)))
    result = send(session, legs, legs_file((1, 1)))
    assert (result['replaced_imports'], result['labels_removed']) == (0, 0)
    assert texts(session, legs) == ['swp1s1', 'swp1s1']
    assert len(session.exec(select(Import)).all()) == 2


def test_replace_on_a_discipline_without_imports_just_imports(s):
    session, legs, _ = s
    result = send(session, legs, legs_file((1, 1)), replace=True)
    assert (result['replaced_imports'], result['labels_removed'], result['rows']) == (0, 0, 1)


def test_replace_keeps_print_history_and_refuses_a_live_print(s):
    session, legs, _ = s
    send(session, legs, legs_file((1, 1), (1, 2)))
    first, second = session.exec(select(Label).order_by(Label.id)).all()
    session.add(PrintLog(left_text=first.left_text, right_text=first.right_text, template_name='T', printer_ip='x'))
    session.add(CartItem(session_id='kiosk', label_id=first.id, left_text=first.left_text))
    session.add(CartItem(session_id='kiosk', label_id=second.id, left_text=second.left_text, status='uncertain'))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        send(session, legs, legs_file((1, 1), text='new'), replace=True)
    assert exc.value.status_code == 409  # an unsettled print outcome blocks it, as on delete
    assert texts(session, legs) == ['swp1s1', 'swp1s2']
    session.delete(session.exec(select(CartItem).where(CartItem.status == 'uncertain')).one()); session.commit()
    send(session, legs, legs_file((1, 1), text='new'), replace=True)
    assert texts(session, legs) == ['new1s1']
    assert session.exec(select(CartItem)).all() == []  # the queued item went with its label
    assert [log.left_text for log in session.exec(select(PrintLog)).all()] == ['swp1s1']


def test_repeated_trunk_and_leg_pairs_are_counted(s):
    session, legs, _ = s
    wb = Workbook()
    wb.active.append(HEADER)
    for row in (['a', 'a', 1, 1], ['b', 'b', 1, 2], ['c', 'c', 1, 1], ['d', 'd', 1, 1], ['e', 'e', 2, None]):
        wb.active.append(row)
    sheet = wb.create_sheet('More')
    sheet.append(HEADER)
    sheet.append(['f', 'f', 1, 2])
    sheet.append(['g', 'g', 2, None])  # no leg number: not a pair
    out = BytesIO(); wb.save(out); wb.close()
    result = send(session, legs, out.getvalue())
    # 1.1 twice more, 1.2 once more on the second sheet; every row still imported.
    assert (result['duplicate_legs'], result['rows']) == (3, 7)
    assert send(session, legs, legs_file((1, 1), (1, 2)), replace=True)['duplicate_legs'] == 0
