from datetime import datetime
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select
from openpyxl import Workbook

from app.models import CartItem, DataHall, Discipline, Import, Label, Project
from app.importer import InvalidWorkbookError, scan_labels_dir
from app.api.projects import delete_discipline, DisciplinePatch, DisciplineIn, create_discipline
from app.api.imports import delete_import

@pytest.fixture
def import_engine():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()

def workbook(path, text='CBL#1.1'):
    wb = Workbook()
    wb.active.append([text, text])
    wb.save(path)
    wb.close()

def tree(tmp_path):
    directory = tmp_path / 'P' / 'H' / 'D'
    directory.mkdir(parents=True)
    return directory

def test_scan_commits_empty_directories(import_engine, tmp_path):
    tree(tmp_path)
    with Session(import_engine) as session:
        assert scan_labels_dir(session, tmp_path).disciplines_created == 1
    with Session(import_engine) as session:
        assert len(session.exec(select(Discipline)).all()) == 1

def test_failed_late_scan_restores_all_previous_data(import_engine, tmp_path):
    directory = tree(tmp_path)
    workbook(directory / 'a.xlsx', 'original')
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
    workbook(directory / 'a.xlsx', 'replacement')
    (directory / 'z.xlsx').write_bytes(b'broken workbook')
    with Session(import_engine) as session:
        with pytest.raises(InvalidWorkbookError):
            scan_labels_dir(session, tmp_path, wipe=True)
    with Session(import_engine) as session:
        assert [label.left_text for label in session.exec(select(Label)).all()] == ['original']
        assert len(session.exec(select(Import)).all()) == 1

@pytest.mark.parametrize('operation', ['import', 'discipline', 'wipe'])
def test_delete_removes_queued_cart_dependencies(import_engine, tmp_path, operation):
    directory = tree(tmp_path)
    workbook(directory / 'a.xlsx')
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
        label = session.exec(select(Label)).one()
        session.add(CartItem(session_id='s', label_id=label.id))
        session.commit()
        if operation == 'import':
            delete_import(label.import_id, session)
        elif operation == 'discipline':
            delete_discipline(label.discipline_id, session)
        else:
            scan_labels_dir(session, tmp_path, wipe=True)
        assert session.exec(select(CartItem)).all() == []
        assert len(session.exec(select(Import)).all()) == (1 if operation == 'wipe' else 0)

@pytest.mark.parametrize('status', ['printing', 'uncertain'])
@pytest.mark.parametrize('operation', ['import', 'discipline', 'wipe'])
def test_deletion_rejects_active_jobs(import_engine, tmp_path, status, operation):
    directory = tree(tmp_path)
    workbook(directory / 'a.xlsx')
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
        label = session.exec(select(Label)).one()
        item = CartItem(session_id='s', label_id=label.id, status=status)
        session.add(item)
        session.commit()
        with pytest.raises(HTTPException) as exc:
            if operation == 'import': delete_import(label.import_id, session)
            elif operation == 'discipline': delete_discipline(label.discipline_id, session)
            else: scan_labels_dir(session, tmp_path, wipe=True)
        assert exc.value.status_code == 409

@pytest.mark.parametrize('field', ['name', 'color', 'bundle_mode'])
def test_patch_rejects_required_null(field):
    with pytest.raises(ValueError):
        DisciplinePatch(**{field: None})

def test_create_missing_template_returns_4xx(import_engine):
    with Session(import_engine) as session:
        p = Project(name='P'); session.add(p); session.commit()
        h = DataHall(project_id=p.id, name='H'); session.add(h); session.commit()
        with pytest.raises(HTTPException) as exc:
            create_discipline(DisciplineIn(data_hall_id=h.id, name='D', template_id=999), session)
        assert 400 <= exc.value.status_code < 500


def test_upload_server_owned_filename_and_invalid_workbook(import_engine, tmp_path):
    import asyncio
    from io import BytesIO
    from app.api.import_ import upload
    directory = tree(tmp_path)
    workbook(directory / 'a.xlsx')
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
        discipline = session.exec(select(Discipline)).one()
        victim = tmp_path / 'victim.xlsx'
        victim.write_bytes(b'keep me')
        data = (directory / 'a.xlsx').read_bytes()
        result = asyncio.run(upload(discipline.id, UploadFile(filename=str(victim), file=BytesIO(data)), session))
        assert result['rows'] == 1
        assert victim.read_bytes() == b'keep me'
        with pytest.raises(HTTPException) as exc:
            asyncio.run(upload(discipline.id, UploadFile(filename='broken.xlsx', file=BytesIO(b'bad')), session))
        assert exc.value.status_code == 400
        assert len(session.exec(select(Import)).all()) == 2


def test_initial_import_migration_preserves_populated_cart(monkeypatch):
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import inspect, text
    import app.db as db
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def configure(connection, _): connection.execute('PRAGMA foreign_keys=ON')
    monkeypatch.setattr(db, 'engine', engine)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(config, 'eb677bd2f0fc')
    with engine.begin() as connection:
        for model in [Project(id=1, name='P'), DataHall(id=1, project_id=1, name='H'),
                      Discipline(id=1, data_hall_id=1, name='D'), Label(id=1, discipline_id=1),
                      CartItem(id=1, session_id='s', label_id=1)]:
            columns = {c['name'] for c in inspect(connection).get_columns(model.__tablename__)}
            data = {key: value.isoformat() if isinstance(value, datetime) else value
                    for key, value in model.model_dump().items() if key in columns}
            connection.execute(text('INSERT INTO ' + model.__tablename__ + ' (' + ','.join(data) + ') VALUES (' + ','.join(':' + key for key in data) + ')'), data)
    command.upgrade(config, '232e2ff8080e')
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('SELECT label_id FROM cartitem').scalar() == 1
    command.upgrade(config, 'head')
    command.check(config)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
        assert connection.exec_driver_sql('SELECT label_id, status, claim_token FROM cartitem').one() == (1, 'queued', '')
    engine.dispose()


def test_duplicate_project_name_is_conflict(import_engine):
    from app.api.projects import ProjectIn, create_project
    with Session(import_engine) as session:
        create_project(ProjectIn(name='P'), session)
        with pytest.raises(HTTPException) as exc:
            create_project(ProjectIn(name=' P '), session)
        assert exc.value.status_code == 409
        assert len(session.exec(select(Project)).all()) == 1


@pytest.mark.parametrize('level', ['hall', 'project'])
def test_parent_deletion_handles_all_dependencies(import_engine, tmp_path, level):
    from app.api.projects import delete_hall, delete_project
    directory = tree(tmp_path)
    workbook(directory / 'a.xlsx')
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
        label = session.exec(select(Label)).one()
        session.add(CartItem(session_id='s', label_id=label.id))
        session.commit()
        if level == 'hall': delete_hall(session.exec(select(DataHall.id)).one(), session)
        else: delete_project(session.exec(select(Project.id)).one(), session)
        for model in [CartItem, Label, Import, Discipline, DataHall]:
            assert session.exec(select(model)).all() == []


def test_parent_active_job_rolls_back_already_deleted_sibling(import_engine, tmp_path):
    from app.api.projects import delete_project
    first = tree(tmp_path)
    second = first.parent / 'Z'; second.mkdir()
    workbook(first / 'a.xlsx'); workbook(second / 'a.xlsx')
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
        labels = session.exec(select(Label).order_by(Label.id)).all()
        session.add(CartItem(session_id='s', label_id=labels[-1].id, status='uncertain'))
        session.commit()
        project_id = session.exec(select(Project.id)).one()
        with pytest.raises(HTTPException) as exc:
            delete_project(project_id, session)
        assert exc.value.status_code == 409
        assert len(session.exec(select(Label)).all()) == 2
        assert len(session.exec(select(Discipline)).all()) == 2


def test_workbook_helper_does_not_commit_callers_transaction(import_engine, tmp_path):
    from app.importer import import_workbook_into_discipline
    directory = tree(tmp_path)
    with Session(import_engine) as session:
        scan_labels_dir(session, tmp_path)
        discipline = session.exec(select(Discipline)).one()
        workbook(directory / 'a.xlsx')
        import_workbook_into_discipline(session, directory / 'a.xlsx', discipline)
        session.rollback()
    with Session(import_engine) as session:
        assert session.exec(select(Import)).all() == []
        assert session.exec(select(Label)).all() == []
