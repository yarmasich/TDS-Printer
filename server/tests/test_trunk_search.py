"""Legs are found by the workbook's Trunk# / Leg # columns, not only by text.

The newest 16K-EW-LS leg labels read "... SU1 | 16K-EW-LS |" with no number,
so a text search for "1.5" can never find leg 5 of trunk 1.
"""
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.labels import search
from app.models import DataHall, Discipline, Label, Project


@pytest.fixture
def s():
    engine = create_engine('sqlite://')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        p = Project(name='Nscale'); session.add(p); session.commit()
        h = DataHall(name='8k&16k', project_id=p.id); session.add(h); session.commit()
        legs = Discipline(name='16K-EW-LS', data_hall_id=h.id)
        trunks = Discipline(name='16K-EW-LS-Trunk', data_hall_id=h.id)
        plain = Discipline(name='8K-IBLFSP', data_hall_id=h.id)
        session.add_all([legs, trunks, plain]); session.commit()
        for t in (1, 2):
            session.add(Label(discipline_id=trunks.id, left_text=f'EH1A - CNR\nSU1 | 16K-EW-LS | CBL# | {t} | 361ft',
                              right_text='CNR - EH1A', trunk_no=str(t)))
            for leg in (1, 2, 3, 4, 10):
                session.add(Label(discipline_id=legs.id, left_text=f'EH1A | swp{t}s{leg} / SU1 | 16K-EW-LS | ',
                                  right_text=f'CNR | swp{t}s{leg}', trunk_no=str(t), leg_no=str(leg)))
        session.add(Label(discipline_id=plain.id, left_text='CBL# | 1.2', right_text='CBL# | 1.2'))
        session.commit()
        yield session, legs, trunks, plain
    engine.dispose()


def found(session, q, discipline=None):
    result = search(q=q, discipline_id=discipline.id if discipline else None, limit=500, offset=0, session=session)
    return [(h.discipline_name, h.trunk_no, h.leg_no) for h in result.hits]


def test_a_leg_is_found_by_trunk_and_leg_number(s):
    session, legs, _, _ = s
    assert found(session, '1.2', legs) == [('16K-EW-LS', '1', '2')]
    assert found(session, '1.10', legs) == [('16K-EW-LS', '1', '10')]  # not 1.1


def test_lists_and_ranges_expand_over_legs(s):
    session, legs, _, _ = s
    assert [leg for _, _, leg in found(session, '1.2,3', legs)] == ['2', '3']
    assert [leg for _, _, leg in found(session, '2.2-4', legs)] == ['2', '3', '4']


def test_a_group_is_every_leg_of_the_trunk(s):
    session, legs, _, _ = s
    assert [leg for _, _, leg in found(session, '1.*', legs)] == ['1', '2', '3', '4', '10']


def test_a_bare_number_is_the_trunk_label_itself(s):
    # As a bare "20" finds #20 and not #20.1, a bare "1" is trunk 1, not its legs.
    session, legs, trunks, _ = s
    assert found(session, '1', trunks) == [('16K-EW-LS-Trunk', '1', None)]
    assert found(session, '1', legs) == []


def test_text_search_still_finds_files_without_columns(s):
    session, _, _, plain = s
    assert found(session, '1.2', plain) == [('8K-IBLFSP', None, None)]
    hits = found(session, '1.2')  # whole project: the leg by column, the plain label by text
    assert ('16K-EW-LS', '1', '2') in hits and ('8K-IBLFSP', None, None) in hits


def test_free_text_does_not_match_numbers_in_columns(s):
    session, legs, _, _ = s
    assert [leg for _, _, leg in found(session, 'swp1s3', legs)] == ['3']


def test_a_leg_discipline_also_searches_its_linked_trunks(s):
    # Operators no longer pick the trunk discipline: it is reached through the
    # legs. A bare number is the trunk label; "N.*" is the whole trunk.
    session, legs, trunks, _ = s
    legs.trunk_discipline_id = trunks.id; session.add(legs); session.commit()
    assert found(session, '1', legs) == [('16K-EW-LS-Trunk', '1', None)]
    assert found(session, '1.2', legs) == [('16K-EW-LS', '1', '2')]
    group = found(session, '1.*', legs)
    assert ('16K-EW-LS-Trunk', '1', None) in group and len(group) == 6  # 5 legs + their trunk


def test_an_unlinked_discipline_searches_only_itself(s):
    session, legs, _, _ = s
    assert found(session, '1', legs) == []
