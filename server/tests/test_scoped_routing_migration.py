"""Upgrade/downgrade only disposable SQLite, never installed data."""
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError


def migrate_engine(monkeypatch,tmp_path):
    import app.db as db
    engine=create_engine(f'sqlite:///{tmp_path}/routing.db')
    monkeypatch.setattr(db,'engine',engine)
    root=Path(__file__).resolve().parents[1]
    cfg=Config(str(root/'alembic.ini'));cfg.set_main_option('script_location',str(root/'alembic'))
    return engine,cfg


def test_upgrade_legacy_keys_and_schema_constraints(monkeypatch,tmp_path):
    engine,cfg=migrate_engine(monkeypatch,tmp_path)
    command.upgrade(cfg,'e91b2c7d0436')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO apikey(id,name,prefix,key_hash,enabled,created_at) VALUES (1,'old','tdsk_test','digest',1,'2026-11-04')")
    command.upgrade(cfg,'head')
    with engine.begin() as c:
        row=c.exec_driver_sql('SELECT integration_id,scopes FROM apikey').one()
        assert row[0] is None and json.loads(row[1])==['legacy_catalog','legacy_print']
        c.exec_driver_sql("INSERT INTO integration VALUES ('i','test','2026-11-04')")
        c.exec_driver_sql("INSERT INTO projectprintpolicy(id,integration_id,external_project_id,revision) VALUES ('p','i','external',1)")
    with pytest.raises(IntegrityError),engine.begin() as c:
        c.exec_driver_sql("INSERT INTO projectprintpolicy(id,integration_id,external_project_id,revision) VALUES ('p2','i','external',1)")
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO printer(id,name,ip,port,notes,protocol,dpi,model,material_calibrations) VALUES (1,'test','unused',9100,'','epl2',300,'custom','{}')")
        c.exec_driver_sql("INSERT INTO projectprinterassignment(id,policy_id,purpose,printer_id) VALUES (1,'p','cable_labels',1)")
    with pytest.raises(IntegrityError),engine.begin() as c:
        c.exec_driver_sql("INSERT INTO projectprinterassignment(id,policy_id,purpose,printer_id) VALUES (2,'p','cable_labels',1)")
    with pytest.raises(IntegrityError),engine.begin() as c:
        c.exec_driver_sql("INSERT INTO projectprinterassignment(id,policy_id,purpose,printer_id) VALUES (3,'p','unsupported',1)")
    assert inspect(engine).get_foreign_keys('projectprinterassignment')
    with engine.connect() as c:
        c.exec_driver_sql('PRAGMA foreign_keys=ON')
        with pytest.raises(IntegrityError):
            c.exec_driver_sql("INSERT INTO projectprinterassignment(id,policy_id,purpose,printer_id) VALUES (4,'missing','cable_labels',1)")
        c.rollback()
        with pytest.raises(IntegrityError):
            c.exec_driver_sql("INSERT INTO projectprinterassignment(id,policy_id,purpose,printer_id) VALUES (5,'p','cable_labels',999)")
        c.rollback()
    command.downgrade(cfg,'e91b2c7d0436')
    assert 'integration_id' not in {c['name'] for c in inspect(engine).get_columns('apikey')}
    with engine.connect() as c:assert c.exec_driver_sql('SELECT name FROM apikey').scalar()=='old'
    engine.dispose()


def test_fresh_schema_and_safe_downgrade_with_permanent_reservation(monkeypatch,tmp_path):
    engine,cfg=migrate_engine(monkeypatch,tmp_path)
    command.upgrade(cfg,'head')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO integrationprintrequest(credential_hash,idempotency_key,request_hash,created_at,state) VALUES ('integration:i','token','digest','2026-11-04','reserved')")
    with pytest.raises(RuntimeError,match='permanent scoped print reservations'):
        command.downgrade(cfg,'e91b2c7d0436')
    assert 'integration' in inspect(engine).get_table_names()
    engine.dispose()


def test_downgrade_cannot_turn_scoped_credentials_into_legacy_keys(monkeypatch,tmp_path):
    engine,cfg=migrate_engine(monkeypatch,tmp_path)
    command.upgrade(cfg,'head')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO integration VALUES ('i','test','2026-11-04')")
        c.exec_driver_sql("INSERT INTO apikey(id,name,prefix,key_hash,enabled,created_at,integration_id,scopes) VALUES (1,'scoped','tdsk_test','digest',1,'2026-11-04','i','[\"print\"]')")
    with pytest.raises(RuntimeError,match='scoped credentials'):
        command.downgrade(cfg,'e91b2c7d0436')
    with engine.connect() as c:
        assert json.loads(c.exec_driver_sql('SELECT scopes FROM apikey').scalar())==['print']
    engine.dispose()
