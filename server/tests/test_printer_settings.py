from unittest.mock import patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from app.api import printers
from app.auth_admin import require_admin
from app.db import get_session
from app.models import Printer
from app import printer_device_status as status
from app.api.scoped_integrations import catalog
from app.schemas import PrinterInput, PrinterPatch

SECRET = 'test-only-community'

@pytest.fixture
def setup(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path}/settings.db', connect_args={'check_same_thread': False}, hide_parameters=True)
    SQLModel.metadata.create_all(engine)
    app = FastAPI(); app.include_router(printers.router)
    def sessions():
        with Session(engine) as session: yield session
    app.dependency_overrides[get_session] = sessions
    with TestClient(app) as client:
        assert client.get('/api/printers/1/status').status_code == 401
        app.dependency_overrides[require_admin] = lambda: None
        yield client, engine
    engine.dispose()


@pytest.mark.parametrize('model,version', [('QL-1110NWBc', '1'), ('DP4300H', '2c'), ('DP4600H', '2c')])
def test_secret_round_trip_redaction_and_reset(setup, model, version):
    client, engine = setup
    response = client.post('/api/printers', json=dict(name='Configured', ip='192.0.2.1', model=model, snmp_community=SECRET))
    assert response.status_code == 200, response.text
    assert SECRET not in response.text and 'snmp_community"' not in response.text
    data = response.json(); pid = data['id']
    assert data['snmp_source'] == 'custom' and data['snmp_community_configured']
    assert data['snmp_version'] == version
    assert data['qr_media_id'] == 'DK-2246'
    with Session(engine) as session:
        printer = session.get(Printer, pid)
        assert printer.snmp_community == SECRET
        assert SECRET not in repr(printer)
        assert SECRET not in str(printer)
        assert SECRET not in repr(PrinterInput.model_validate(printer))
        assert not any(k.startswith('snmp') for k in catalog(printer))
        assert catalog(printer)['qr_defaults'] == ({'media_id':'DK-2246', 'label_length_mm':60} if model == 'QL-1110NWBc' else None)
    assert client.put(f'/api/printers/{pid}', json={'notes':'changed'}).status_code == 200
    with Session(engine) as session: assert session.get(Printer, pid).snmp_community == SECRET
    for path in ('/api/printers', f'/api/printers/{pid}'):
        assert SECRET not in client.get(path).text
    with patch.object(printers, 'ping_printer', return_value=(True, 1, '')), patch.object(status, 'device_status', return_value=status._unknown()) as probe:
        result = client.get(f'/api/printers/{pid}/status')
        assert result.status_code == 200 and SECRET not in result.text
        assert result.json()['snmp_version'] == version
        assert probe.call_args.kwargs['community_override'] == SECRET
    assert client.put(f'/api/printers/{pid}', json={'snmp_community':None}).json()['snmp_source'] == 'inherited'
    with Session(engine) as session: assert session.get(Printer, pid).snmp_community is None
    assert client.get('/api/printers/999/status').status_code == 404


@pytest.mark.parametrize('payload', [
    {'snmp_community': ''}, {'snmp_community': 'x'*129},
    {'snmp_community': {'secret': SECRET}}, {'snmp_community': SECRET, 'port': 0},
    {'snmp_community': SECRET, 'protocol':'brother_ql', 'model':'custom'},
])
def test_validation_never_echoes_body(setup,payload):
    client,_ = setup
    pid=client.post('/api/printers',json={'name':'P','ip':'192.0.2.1'}).json()['id']
    for response in (client.post('/api/printers', json={'name':'new','ip':'192.0.2.1',**payload}),
                     client.put(f'/api/printers/{pid}',json=payload)):
        assert response.status_code == 422
        assert response.json() == {'detail':'Invalid printer settings'}


def test_config_disable_override_port_cache_and_legacy(monkeypatch):
    status._cache.clear(); status._inflight.clear()
    monkeypatch.setenv('BROTHER_SNMP_COMMUNITY','inherited-test')
    with patch.object(status,'_probe',return_value=status._unknown()) as probe:
        assert status.device_status(1,'192.0.2.1','QL-1110NWBc',enabled=False)['state']=='unknown'
        probe.assert_not_called()
        status.device_status(1,'192.0.2.1','QL-1110NWBc',port=1161,community_override=SECRET)
        probe.assert_called_once_with('192.0.2.1',SECRET.encode(),1161)
        status.device_status(1,'192.0.2.1','QL-1110NWBc',port=1161,community_override=SECRET)
        assert probe.call_count == 1
        status.device_status(1,'192.0.2.1','QL-1110NWBc',port=1162,community_override=SECRET)
        assert probe.call_count == 2
        statuses=status.device_statuses([(2,'192.0.2.2','QL-1110NWBc'),status.DeviceStatusConfig(3,'192.0.2.3','QL-1110NWBc',False)])
        assert set(statuses)=={2,3}
        assert SECRET not in repr(status.DeviceStatusConfig(1,'ip','model',community=SECRET))


def test_concurrent_secret_edit_conflicts(setup):
    client,engine=setup
    pid=client.post('/api/printers',json={'name':'P','ip':'192.0.2.1'}).json()['id']
    with Session(engine) as old, Session(engine) as new:
        snapshot=old.get(Printer,pid)
        printers.update_printer(pid,PrinterPatch(snmp_community=SECRET),new)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            printers.update_printer(pid,PrinterPatch(notes='stale'),old)
        assert exc.value.status_code==409


def test_migration_preserves_existing_printer(monkeypatch,tmp_path):
    from test_scoped_routing_migration import migrate_engine
    from alembic import command
    engine,cfg=migrate_engine(monkeypatch,tmp_path)
    command.upgrade(cfg,'e4f7a2c9b601')
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO printer(name,ip,port,notes,protocol,dpi,model,material_calibrations) VALUES ('P','unused',9100,'note','epl2',300,'custom','{}')")
    command.upgrade(cfg,'head')
    with engine.connect() as conn:
        row=conn.exec_driver_sql('SELECT name,notes,snmp_enabled,snmp_port,snmp_community,qr_media_id,qr_label_length_mm,material_calibrations FROM printer').one()
        assert tuple(row)==('P','note',1,161,None,'DK-2246',60,'{}')
    command.downgrade(cfg,'e4f7a2c9b601')
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT name,notes FROM printer').one()==('P','note')
    engine.dispose()


def test_invalid_persisted_community_does_not_leak():
    from app.models import Template
    from app.printer import validate_print_settings, PrintError
    printer=Printer(name='P',ip='unused',snmp_community=SECRET*20)
    with pytest.raises(PrintError) as exc:
        validate_print_settings(Template(name='T',printer_id=1,bytes_per_row=10,height=10),printer)
    assert str(exc.value)=='Invalid printer settings'
    assert exc.value.__suppress_context__ is True


def test_calibration_and_catalog_exclude_secret(setup):
    from app.api import integrations
    from app.auth_apikey import generate_key
    from app.models import ApiKey
    client,engine=setup
    pid=client.post('/api/printers',json=dict(name='Panduit',ip='192.0.2.1',model='DP4300H',snmp_community=SECRET)).json()['id']
    result=client.put(f'/api/printers/{pid}/calibration/R200X150V1T',json={'x_mm':1,'y_mm':0})
    assert result.status_code==200,result.text
    assert SECRET not in result.text and 'snmp_community"' not in result.text
    client.app.include_router(integrations.router)
    key,prefix,digest=generate_key()
    with Session(engine) as session:
        session.add(ApiKey(name='test',prefix=prefix,key_hash=digest));session.commit()
    result=client.get('/api/v1/printer-catalog',headers={'X-API-Key':key})
    assert result.status_code==200
    assert SECRET not in result.text and 'snmp_' not in result.text


@pytest.mark.parametrize('name',['snmp_enabled','snmp_port','qr_media_id','qr_label_length_mm'])
def test_nonnullable_settings_reject_null(setup,name):
    client,_=setup
    pid=client.post('/api/printers',json={'name':'P','ip':'192.0.2.1'}).json()['id']
    response=client.put(f'/api/printers/{pid}',json={name:None,'snmp_community':SECRET})
    assert response.status_code==422 and SECRET not in response.text


def test_database_errors_hide_parameters(caplog):
    import app.db as db
    from sqlalchemy import text
    from sqlalchemy.exc import StatementError
    assert db.engine.hide_parameters is True
    engine=create_engine('sqlite://',hide_parameters=True)
    with engine.connect() as conn,pytest.raises(StatementError) as exc:
        conn.execute(text('SELECT * FROM nonexistent WHERE value=:community'),{'community':SECRET})
    assert SECRET not in str(exc.value)
    assert SECRET not in caplog.text
    engine.dispose()


@pytest.mark.parametrize('online,error,expected', [
    (True, '', 'reachable'),
    (False, 'Printer busy; status check skipped', 'busy'),
    (False, 'Connection refused', 'unreachable'),
])
def test_admin_status_connection_state(setup,online,error,expected):
    client,_=setup
    pid=client.post('/api/printers',json={'name':'P','ip':'192.0.2.1'}).json()['id']
    with patch.object(printers,'ping_printer',return_value=(online,None,error)):
        response=client.get(f'/api/printers/{pid}/status')
    assert response.status_code==200
    assert response.json()['connection_state']==expected
    assert response.json()['online'] is online
    assert response.json()['device_status'] is None
    assert 'error' not in response.json()
