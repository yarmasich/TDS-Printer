"""A leg discipline names the discipline that holds its trunk labels."""
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.projects import DisciplinePatch, delete_discipline, list_disciplines, update_discipline
from app.models import DataHall, Discipline, Project


@pytest.fixture
def s():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        nscale, xai = Project(name='Nscale'), Project(name='XAI')
        session.add_all([nscale, xai]); session.commit()
        hall, other = DataHall(name='8k&16k', project_id=nscale.id), DataHall(name='DH26', project_id=xai.id)
        session.add_all([hall, other]); session.commit()
        session.add_all([Discipline(name='16K-EW-LS', data_hall_id=hall.id),
                         Discipline(name='16K-EW-LS-Trunk', data_hall_id=hall.id),
                         Discipline(name='AS-T1', data_hall_id=other.id)])
        session.commit()
        yield session
    engine.dispose()


def by_name(s, name):
    return s.exec(select(Discipline).where(Discipline.name == name)).one()


def link(s, legs, trunks):
    return update_discipline(legs.id, DisciplinePatch(trunk_discipline_id=trunks), s)


def test_a_leg_discipline_links_its_trunk_discipline(s):
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    link(s, legs, trunks.id)
    dto = {d.name: d for d in list_disciplines(session=s)}['16K-EW-LS']
    assert (dto.trunk_discipline_id, dto.trunk_discipline_name) == (trunks.id, '16K-EW-LS-Trunk')


def test_an_explicit_null_unlinks(s):
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    link(s, legs, trunks.id)
    link(s, legs, None)
    assert s.get(Discipline, legs.id).trunk_discipline_id is None


@pytest.mark.parametrize('target, reason', [
    ('self', 'itself'), ('AS-T1', 'same project'), (999, 'not found'),
])
def test_only_another_discipline_of_the_same_project_can_hold_trunks(s, target, reason):
    legs = by_name(s, '16K-EW-LS')
    target_id = legs.id if target == 'self' else target if isinstance(target, int) else by_name(s, target).id
    with pytest.raises(HTTPException) as exc:
        link(s, legs, target_id)
    assert exc.value.status_code == 400 and reason in exc.value.detail


def test_trunks_are_one_level_deep(s):
    # A trunk discipline that itself points at trunks would make "leg + trunk"
    # ambiguous; chains are refused in both directions.
    legs, trunks, other = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk'), Discipline(name='X', data_hall_id=by_name(s, '16K-EW-LS').data_hall_id)
    s.add(other); s.commit()
    link(s, legs, trunks.id)
    with pytest.raises(HTTPException) as exc:
        link(s, trunks, other.id)  # the trunk discipline cannot become a leg discipline
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        link(s, other, legs.id)  # nor can a leg discipline serve as someone's trunks
    assert s.get(Discipline, trunks.id).trunk_discipline_id is None


def test_deleting_the_trunk_discipline_unlinks_its_legs(s):
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    link(s, legs, trunks.id)
    delete_discipline(trunks.id, s)
    s.expire_all()
    assert s.get(Discipline, legs.id).trunk_discipline_id is None


def test_linked_legs_report_labels_without_a_trunk_number(s):
    from app.models import Label
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    s.add_all([Label(discipline_id=legs.id, left_text='a', trunk_no='1', leg_no='1'),
               Label(discipline_id=legs.id, left_text='b'), Label(discipline_id=legs.id, left_text='c'),
               Label(discipline_id=trunks.id, left_text='TRUNK 1', trunk_no='1')])
    s.commit()
    counts = lambda: {d.name: d.missing_trunk_count for d in list_disciplines(session=s)}
    assert counts()['16K-EW-LS'] == 0  # not linked: nothing to warn about
    link(s, legs, trunks.id)
    assert counts() == {'16K-EW-LS': 2, '16K-EW-LS-Trunk': 0, 'AS-T1': 0}


def test_a_new_discipline_is_created_with_its_role(s):
    from app.api.projects import DisciplineIn, create_discipline
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    hall = legs.data_hall_id
    # Trunk labels for existing legs: the legs point at the new discipline.
    new_trunks = create_discipline(DisciplineIn(data_hall_id=hall, name='GPU-MS-Trunk', trunks_for_id=legs.id), s)
    assert by_name(s, '16K-EW-LS').trunk_discipline_id == new_trunks.id
    # Leg labels whose trunks an existing discipline holds.
    new_legs = create_discipline(DisciplineIn(data_hall_id=hall, name='GPU-MS', trunk_discipline_id=trunks.id), s)
    assert new_legs.trunk_discipline_id == trunks.id


@pytest.mark.parametrize('body,message', [
    ({'trunks_for_id': 'AS-T1'}, 'same project'),             # another project's legs
    ({'trunk_discipline_id': 'self-legs'}, 'already links'),  # legs cannot hold trunks
    ({'trunks_for_id': 'linked-legs'}, 'unlink it first'),    # never moves an existing link
])
def test_an_invalid_role_creates_nothing(s, body, message):
    from app.api.projects import DisciplineIn, create_discipline
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    link(s, legs, trunks.id)
    ids = {'AS-T1': by_name(s, 'AS-T1').id, 'self-legs': legs.id, 'linked-legs': legs.id}
    field, target = next(iter(body.items()))
    before = len(s.exec(select(Discipline)).all())
    with pytest.raises(HTTPException) as exc:
        create_discipline(DisciplineIn(data_hall_id=legs.data_hall_id, name='New', **{field: ids[target]}), s)
    assert message in exc.value.detail
    assert len(s.exec(select(Discipline)).all()) == before
    assert by_name(s, '16K-EW-LS').trunk_discipline_id == trunks.id


def test_one_discipline_cannot_take_both_roles():
    from pydantic import ValidationError
    from app.api.projects import DisciplineIn
    with pytest.raises(ValidationError):
        DisciplineIn(data_hall_id=1, name='X', trunk_discipline_id=1, trunks_for_id=2)


def test_renaming_keeps_the_trunk_link_and_refuses_a_taken_name(s):
    legs, trunks = by_name(s, '16K-EW-LS'), by_name(s, '16K-EW-LS-Trunk')
    link(s, legs, trunks.id)
    renamed = update_discipline(trunks.id, DisciplinePatch(name='  16K-EW-LS-T  '), s)
    assert renamed.name == '16K-EW-LS-T'
    assert by_name(s, '16K-EW-LS').trunk_discipline_id == trunks.id
    with pytest.raises(HTTPException) as exc:
        update_discipline(trunks.id, DisciplinePatch(name='16K-EW-LS'), s)
    assert exc.value.status_code == 409
