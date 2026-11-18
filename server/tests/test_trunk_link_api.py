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
