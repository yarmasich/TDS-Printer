"""Admin key listings, throttled liveness and the policy display name."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as sa_create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from app import auth_apikey
from app.api import api_keys, scoped_integrations
from app.auth_admin import require_admin
from app.auth_apikey import LAST_USED_RESOLUTION, generate_key, touch_last_used
from app.db import get_session
from app.models import ApiKey, Integration, PolicyAudit, Printer, Project, ProjectPrintPolicy


@pytest.fixture
def admin(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/keys.db', connect_args={'check_same_thread': False})
    SQLModel.metadata.create_all(engine)
    scoped_raw, scoped_prefix, scoped_digest = generate_key()
    legacy_raw, legacy_prefix, legacy_digest = generate_key()
    iid = str(uuid4())
    with Session(engine) as s:
        s.add(Integration(id=iid, name='FloorHub'))
        s.add_all([
            ApiKey(name='scoped', prefix=scoped_prefix, key_hash=scoped_digest, integration_id=iid,
                   scopes=['policy.read', 'policy.write', 'print']),
            ApiKey(name='legacy', prefix=legacy_prefix, key_hash=legacy_digest),
            Printer(name='Cable', ip='192.0.2.1', protocol='epl2'),
            Project(name='Bound'),
        ])
        s.commit()
    app = FastAPI()
    app.include_router(api_keys.router, dependencies=[Depends(require_admin)])
    app.include_router(scoped_integrations.admin_router, dependencies=[Depends(require_admin)])
    app.include_router(scoped_integrations.router)

    def sessions():
        with Session(engine) as s:
            yield s
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[require_admin] = lambda: 'admin'
    with TestClient(app) as c:
        yield c, engine, {'X-API-Key': scoped_raw}, {'X-API-Key': legacy_raw}, iid
    engine.dispose()


def body(project, **changes):
    return {'external_project_id': project, 'revision': 0, 'tds_project_id': 1,
            'cable_labels': {'printer_ids': [1], 'default_printer_id': 1},
            'qr_labels': {'printer_ids': [], 'default_printer_id': None}, **changes}


# ---------------------------------------------------------------- listings

def test_key_list_splits_legacy_and_scoped_keys(admin):
    c, _, _, _, iid = admin
    legacy = c.get('/api/api-keys?kind=legacy').json()
    scoped = c.get('/api/api-keys?kind=scoped').json()
    every = c.get('/api/api-keys').json()
    assert [k['name'] for k in legacy] == ['legacy'] and legacy[0]['integration_id'] is None
    assert [k['name'] for k in scoped] == ['scoped'] and scoped[0]['integration_id'] == iid
    assert sorted(k['name'] for k in every) == ['legacy', 'scoped']
    assert c.get('/api/api-keys?kind=other').status_code == 422
    assert 'key_hash' not in str(every)


def test_integration_listing_shows_key_metadata_for_disable_and_revoke(admin):
    c, _, _, _, _ = admin
    key = c.get('/api/integrations').json()[0]['keys'][0]
    assert {'id', 'prefix', 'scopes', 'enabled', 'created_at', 'last_used_at'} <= key.keys()
    assert c.put(f"/api/api-keys/{key['id']}", json={'enabled': False}).json()['enabled'] is False
    assert c.get('/api/integrations').json()[0]['keys'][0]['enabled'] is False
    assert c.delete(f"/api/api-keys/{key['id']}").status_code == 200
    assert c.get('/api/integrations').json()[0]['keys'] == []


def test_split_listing_does_not_change_what_auth_accepts(admin):
    c, _, scoped, legacy, _ = admin
    assert c.get('/api/v1/integrations/configuration', headers=scoped).status_code == 200
    assert c.get('/api/v1/integrations/configuration', headers=legacy).status_code == 403


# ------------------------------------------------------------ last used

def test_last_used_written_once_per_resolution(admin):
    c, engine, scoped, _, _ = admin
    writes = []
    real = auth_apikey.touch_last_used
    with patch.object(auth_apikey, 'touch_last_used', side_effect=lambda *a, **k: writes.append(real(*a, **k)) or writes[-1]):
        for _ in range(3):
            assert c.get('/api/v1/integrations/configuration', headers=scoped).status_code == 200
    assert writes == [True, False, False]
    with Session(engine) as s:
        assert s.exec(select(ApiKey).where(ApiKey.name == 'scoped')).one().last_used_at is not None


def test_last_used_refreshes_after_resolution_and_handles_naive_values(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/touch.db')
    SQLModel.metadata.create_all(engine)
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    with Session(engine) as s:
        key = ApiKey(name='k', prefix='p', key_hash='h')
        s.add(key); s.commit(); s.refresh(key)
        assert touch_last_used(s, key, now) is True
        assert touch_last_used(s, key, now + LAST_USED_RESOLUTION - timedelta(seconds=1)) is False
        assert touch_last_used(s, key, now + LAST_USED_RESOLUTION) is True
        # A naive stored value is read as UTC.
        key.last_used_at = now.replace(tzinfo=None)
        assert touch_last_used(s, key, now + timedelta(minutes=1)) is False
        assert touch_last_used(s, key, now + LAST_USED_RESOLUTION) is True
    with Session(engine) as s:
        stored = s.get(ApiKey, 1).last_used_at
        assert stored.replace(tzinfo=timezone.utc) == now + LAST_USED_RESOLUTION
    engine.dispose()


def test_failed_liveness_write_never_fails_authentication(admin):
    c, engine, scoped, _, _ = admin
    with patch.object(Session, 'commit', side_effect=OperationalError('UPDATE', {}, Exception('locked'))):
        assert c.get('/api/v1/integrations/configuration', headers=scoped).status_code == 200
    with Session(engine) as s:
        assert s.exec(select(ApiKey).where(ApiKey.name == 'scoped')).one().last_used_at is None


# ---------------------------------------------------- project display name

def test_configuration_advertises_project_name_support(admin):
    c, _, scoped, _, _ = admin
    assert 'policy.external_project_name' in c.get('/api/v1/integrations/configuration', headers=scoped).json()['capabilities']


def test_policy_name_is_stored_kept_cleared_and_kept_out_of_machine_policy(admin):
    c, engine, h, _, _ = admin
    project = str(uuid4())
    path = f'/api/v1/integrations/projects/{project}/policy'
    saved = c.put(path, headers=h, json=body(project, external_project_name='  Nscale Loughton  '))
    assert saved.status_code == 200
    # The machine contract is unchanged: strict callers parse these replies.
    assert 'external_project_name' not in saved.json()
    assert 'external_project_name' not in c.get(path, headers=h).json()
    listed = lambda: c.get('/api/integrations').json()[0]['policies'][0]['external_project_name']
    assert listed() == 'Nscale Loughton'
    # An older caller that never sends the field keeps the stored name.
    assert c.put(path, headers=h, json=body(project, revision=1)).status_code == 200
    assert listed() == 'Nscale Loughton'
    assert c.put(path, headers=h, json=body(project, revision=2, external_project_name='   ')).status_code == 200
    assert listed() is None
    assert c.put(path, headers=h, json=body(project, revision=3, external_project_name='Renamed')).status_code == 200
    assert c.put(path, headers=h, json=body(project, revision=4, external_project_name=None)).status_code == 200
    assert listed() is None
    with Session(engine) as s:
        audits = s.exec(select(PolicyAudit).order_by(PolicyAudit.id)).all()
        assert audits[0].after['external_project_name'] == 'Nscale Loughton'
        assert 'external_project_name' not in audits[1].after


def test_policy_name_is_optional_and_bounded(admin):
    c, _, h, _, _ = admin
    project = str(uuid4())
    path = f'/api/v1/integrations/projects/{project}/policy'
    assert c.put(path, headers=h, json=body(project, external_project_name='x' * 201)).status_code == 422
    assert c.put(path, headers=h, json=body(project, external_project_name=7)).status_code == 422
    assert c.get(path, headers=h).json()['revision'] == 0
    assert c.put(path, headers=h, json=body(project, external_project_name='x' * 200)).status_code == 200
    other = str(uuid4())
    assert c.put(f'/api/v1/integrations/projects/{other}/policy', headers=h, json=body(other)).status_code == 200
    names = {p['external_project_id']: p['external_project_name'] for p in c.get('/api/integrations').json()[0]['policies']}
    assert names == {project: 'x' * 200, other: None}
    # Other unknown fields are still refused.
    assert c.put(path, headers=h, json=body(project, revision=1, unknown=1)).status_code == 422


# -------------------------------------------------------------- migration

def _alembic(monkeypatch, tmp_path):
    import app.db as db
    engine = sa_create_engine(f'sqlite:///{tmp_path}/migrate.db')
    monkeypatch.setattr(db, 'engine', engine)
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'alembic'))
    return engine, cfg


def _columns(engine):
    return {c['name'] for c in inspect(engine).get_columns('projectprintpolicy')}


def test_migration_adds_nullable_name_and_round_trips(monkeypatch, tmp_path):
    engine, cfg = _alembic(monkeypatch, tmp_path)
    command.upgrade(cfg, '8c41f0a2d7e5')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO integration VALUES ('i','test','2026-11-20')")
        c.exec_driver_sql("INSERT INTO projectprintpolicy(id,integration_id,external_project_id,revision) VALUES ('p','i','external',1)")
    command.upgrade(cfg, 'head')
    assert 'external_project_name' in _columns(engine)
    with engine.begin() as c:
        assert c.exec_driver_sql('SELECT external_project_name FROM projectprintpolicy').scalar() is None
        c.exec_driver_sql("UPDATE projectprintpolicy SET external_project_name='Named'")
    command.downgrade(cfg, '8c41f0a2d7e5')
    assert 'external_project_name' not in _columns(engine)
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT external_project_id FROM projectprintpolicy').scalar() == 'external'
    command.upgrade(cfg, 'head')
    assert 'external_project_name' in _columns(engine)
    engine.dispose()


def test_migration_is_idempotent_when_column_already_exists(monkeypatch, tmp_path):
    engine, cfg = _alembic(monkeypatch, tmp_path)
    command.upgrade(cfg, 'head')
    # Re-running this revision against a table that already has the column is a no-op.
    command.stamp(cfg, '8c41f0a2d7e5')
    command.upgrade(cfg, 'f3b9e2c71a58')
    assert 'external_project_name' in _columns(engine)
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar() == 'f3b9e2c71a58'
    engine.dispose()


def test_model_matches_migrated_column():
    column = ProjectPrintPolicy.__table__.c.external_project_name
    assert column.nullable and column.type.length == 200
