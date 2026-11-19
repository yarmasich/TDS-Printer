"""Leg and trunk workbooks carry their link in columns, not in the label text.

The 16K-EW-LS leg file prints "SU1 | 16K-EW-LS |" with no cable number, so a
leg can only be tied to its trunk through the `Trunk#` / `Leg #` columns, which
the importer used to discard (it read the first two columns only, and imported
the header row as a label).
"""
import pytest
from openpyxl import Workbook
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.importer import import_workbook_into_discipline
from app.models import DataHall, Discipline, Label, Project

LEG_HEADER = ['A-Leg', 'Z-Leg', None, None, None, 'A-Trunk', 'Z-Trunk', 'A_RACK', 'Z_RACK',
              'Discipline', 'Trunk#', 'Leg #', 'SU']
TRUNK_HEADER = ['A-Trunk', 'Z-Trunk', 'Discipline', 'Trunk#', 'SU']


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        project = Project(name='Nscale'); s.add(project); s.commit()
        hall = DataHall(name='8k&16k', project_id=project.id); s.add(hall); s.commit()
        yield s
    engine.dispose()


def discipline(s, name):
    d = Discipline(name=name, data_hall_id=s.exec(select(DataHall)).one().id)
    s.add(d); s.commit()
    return d


def workbook(path, rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    wb.save(path); wb.close()
    return path


def labels(s, d):
    return s.exec(select(Label).where(Label.discipline_id == d.id).order_by(Label.row_idx)).all()


def leg(a, z, trunk, leg_no):
    return [a, z, None, None, None, None, None, 'EH1A-R08', 'CNR-N1-R01', '16K-EW-LS', trunk, leg_no, 1]


def test_leg_rows_keep_their_trunk_and_leg_numbers(session, tmp_path):
    d = discipline(session, '16K-EW-LS')
    path = workbook(tmp_path / 'legs.xlsx', [
        LEG_HEADER,
        leg('EH1A-R08 | swp33s1', 'CNR-N1-R01 | swp1s1', 1, 1),
        leg('EH1A-R08 | swp33s2', 'CNR-N1-R01 | swp1s2', 1, 2),
        leg('EH1A-R08 | swp34s1', 'CNR-N1-R02 | swp1s1', 2, 1),
    ])
    import_workbook_into_discipline(session, path, d); session.commit()
    rows = labels(session, d)
    assert [(r.left_text, r.trunk_no, r.leg_no) for r in rows] == [
        ('EH1A-R08 | swp33s1', '1', '1'), ('EH1A-R08 | swp33s2', '1', '2'), ('EH1A-R08 | swp34s1', '2', '1')]


def test_the_header_row_is_not_a_label(session, tmp_path):
    d = discipline(session, '16K-EW-LS-Trunk')
    path = workbook(tmp_path / 'trunks.xlsx', [
        TRUNK_HEADER,
        ['EH1A-R08 - CNR-N1-R01\nSU1 | 16K-EW-LS | CBL# | 1 | 361ft', 'CNR-N1-R01 - EH1A-R08', '16K-EW-LS', 1, 1],
    ])
    stats = import_workbook_into_discipline(session, path, d); session.commit()
    rows = labels(session, d)
    assert [r.left_text for r in rows] == ['EH1A-R08 - CNR-N1-R01\nSU1 | 16K-EW-LS | CBL# | 1 | 361ft']
    assert (rows[0].trunk_no, rows[0].leg_no) == ('1', None)
    assert stats.rows == 1 and stats.skipped == 1


def test_trunk_rows_in_a_leg_workbook_are_left_out(session, tmp_path):
    # The 16K-EW-HL leg file puts each trunk's own label above its legs, with no
    # Trunk# / Leg #; "324.*" then matched it too and the trunk lookup refused.
    d = discipline(session, '16K-EW-HL')
    trunk = 'EH1A-R01 - EH1A-R08\nSU1 | 16K-EW-HL | CBL# | 1 | 46ft'
    path = workbook(tmp_path / 'legs.xlsx', [
        LEG_HEADER,
        [trunk, 'EH1A-R08 - EH1A-R01\nSU1 | 16K-EW-HL | CBL# | 1 | 46ft'] + [None] * 11,
        leg('EH1A-R01 | swp1s2\nCBL# | 1.1', 'EH1A-R08 | swp1s1\nCBL# | 1.1', 1, 1),
        leg('SU1 | 16K-EW-HL |', 'SU1 | 16K-EW-HL |', 1, 2),
        # Still a label: a leg row whose link cells are blank, or that names a leg.
        leg('CBL# | 2.1', 'CBL# | 2.1', None, None),
        leg('no number here', 'Z', None, None),
    ])
    stats = import_workbook_into_discipline(session, path, d); session.commit()
    assert [r.left_text for r in labels(session, d)] == [
        'EH1A-R01 | swp1s2\nCBL# | 1.1', 'SU1 | 16K-EW-HL |', 'CBL# | 2.1', 'no number here']
    assert (stats.rows, stats.trunk_rows, stats.skipped) == (4, 1, 2)


def test_a_trunk_workbook_keeps_its_trunk_rows(session, tmp_path):
    # Without a Leg # column the workbook is a trunk book; a blank Trunk# stays a label.
    d = discipline(session, '16K-EW-HL-Trunk')
    path = workbook(tmp_path / 'trunks.xlsx', [
        TRUNK_HEADER, ['SU1 | CBL# | 1 | 46ft', 'Z', 'D', 1, 1], ['SU1 | CBL# | 2 | 46ft', 'Z', 'D', None, 1]])
    stats = import_workbook_into_discipline(session, path, d); session.commit()
    assert [r.trunk_no for r in labels(session, d)] == ['1', None]
    assert stats.trunk_rows == 0


def test_excel_numbers_read_as_plain_text(session, tmp_path):
    # openpyxl hands back 7 or 7.0 depending on how the cell was typed.
    d = discipline(session, 'D')
    path = workbook(tmp_path / 'f.xlsx', [TRUNK_HEADER, ['A', 'Z', 'D', 7.0, 1], ['A2', 'Z2', 'D', '12', 1]])
    import_workbook_into_discipline(session, path, d); session.commit()
    assert [r.trunk_no for r in labels(session, d)] == ['7', '12']


def test_a_workbook_without_trunk_columns_imports_as_before(session, tmp_path):
    d = discipline(session, '8K-IBLFSP')
    path = workbook(tmp_path / 'plain.xlsx', [['CBL# | 1.1', 'CBL# | 1.1'], ['CBL# | 1.2', 'CBL# | 1.2']])
    import_workbook_into_discipline(session, path, d); session.commit()
    rows = labels(session, d)
    assert [r.left_text for r in rows] == ['CBL# | 1.1', 'CBL# | 1.2']
    assert all(r.trunk_no is None and r.leg_no is None for r in rows)


def test_migration_adds_the_link_and_keeps_existing_rows(monkeypatch, tmp_path):
    from alembic import command
    from test_scoped_routing_migration import migrate_engine
    engine, cfg = migrate_engine(monkeypatch, tmp_path)
    command.upgrade(cfg, '39d48e7c15a2')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO project(id,name) VALUES (1,'P')")
        c.exec_driver_sql("INSERT INTO datahall(id,project_id,name) VALUES (1,1,'H')")
        c.exec_driver_sql("INSERT INTO discipline(id,data_hall_id,name,color,bundle_mode) VALUES (1,1,'Legs','FFFFFF',0),(2,1,'Trunks','FFFFFF',0)")
        c.exec_driver_sql("INSERT INTO label(id,discipline_id,sheet_name,source_file,row_idx,left_text,right_text) VALUES (1,1,'S','f',2,'L','R')")
    command.upgrade(cfg, 'head')
    with engine.begin() as c:
        assert c.exec_driver_sql('SELECT left_text,trunk_no,leg_no FROM label').one() == ('L', None, None)
        assert c.exec_driver_sql('SELECT trunk_discipline_id FROM discipline WHERE id=1').scalar() is None
        c.exec_driver_sql('UPDATE discipline SET trunk_discipline_id=2 WHERE id=1')
        c.exec_driver_sql('PRAGMA foreign_keys=ON')
    with engine.begin() as c:
        c.exec_driver_sql('PRAGMA foreign_keys=ON')
        with pytest.raises(Exception):  # the link is a real foreign key
            c.exec_driver_sql('UPDATE discipline SET trunk_discipline_id=99 WHERE id=1')
    command.downgrade(cfg, '39d48e7c15a2')
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT left_text FROM label').scalar() == 'L'
        assert c.exec_driver_sql('SELECT count(*) FROM discipline').scalar() == 2
    engine.dispose()
