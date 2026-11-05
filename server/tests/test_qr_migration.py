from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_qr_audit_upgrade_and_downgrade_preserve_existing_history(monkeypatch,tmp_path):
    import app.db as db
    engine=create_engine(f'sqlite:///{tmp_path}/migration.db')
    monkeypatch.setattr(db,'engine',engine)
    root=Path(__file__).resolve().parents[1]
    cfg=Config(str(root/'alembic.ini'))
    cfg.set_main_option('script_location',str(root/'alembic'))
    command.upgrade(cfg,'c8d1e4f63a20')
    with engine.begin() as c:
        c.exec_driver_sql("INSERT INTO printlog (id,ts,template_name,printer_ip,operator,reason,left_text,right_text,status,error) VALUES (1,'2026-11-04','Panduit','unused','op','','left','right','ok','')")
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        assert c.exec_driver_sql('SELECT label_kind,qr_scan,left_text FROM printlog').one()==('cable','','left')
    command.downgrade(cfg,'c8d1e4f63a20')
    assert 'qr_scan' not in {col['name'] for col in inspect(engine).get_columns('printlog')}
    with engine.connect() as c:assert c.exec_driver_sql('SELECT left_text FROM printlog').scalar()=='left'
    engine.dispose()
