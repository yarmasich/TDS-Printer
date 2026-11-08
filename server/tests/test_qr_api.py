from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import qr_labels, integrations, printers, templates, stations, history
from app.auth_admin import require_admin
from app.auth_apikey import require_api_key, generate_key
from app.db import get_session
from app.models import ApiKey, Printer, PrintLog, Template, Station
from app.printer import PrintError, ping_printer
from app.schemas import PrinterPatch, TemplateCreate, TemplatePatch


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('TDS_PRINTER_LOCK_DIR',str(tmp_path/'locks'))
    engine=create_engine(f'sqlite:///{tmp_path}/qr.db',connect_args={'check_same_thread':False})
    SQLModel.metadata.create_all(engine)
    raw,prefix,digest=generate_key()
    with Session(engine) as s:
        s.add_all([Printer(name='B',ip='192.0.2.1',model='QL-1110NWBc',protocol='brother_ql'),
                   Printer(name='P',ip='192.0.2.2'),ApiKey(name='Integration',prefix=prefix,key_hash=digest)])
        s.commit()
    app=FastAPI()
    app.include_router(qr_labels.router)
    app.include_router(qr_labels.integration_router)
    app.include_router(history.router,dependencies=[])
    def sessions():
        with Session(engine) as s:yield s
    app.dependency_overrides[get_session]=sessions
    app.dependency_overrides[require_admin]=lambda:'admin'
    with TestClient(app,raise_server_exceptions=False) as client:
        yield client,engine,raw,app
    engine.dispose()


def payload(**kw): return dict(printer_id=1,scan='  ITEM/Я&123  ',code='ITEM',reference='inventory:item:17',**kw)


@pytest.mark.parametrize('path', ['/api/qr-labels','/api/v1/qr-labels'])
def test_preview_no_network_and_print_idempotent(setup,path):
    client,engine,key,_=setup
    headers={'X-API-Key':key,'Idempotency-Key':'uuid'}
    with patch.object(qr_labels,'send_brother_job') as send:
        preview=client.post(path+'/preview',json=payload(),headers=headers)
        assert preview.status_code==200 and preview.headers['content-type']=='image/png'
        send.assert_not_called()
        def check_sending(*args):
            with Session(engine) as s:
                assert s.exec(select(PrintLog)).one().status=='sending'
        send.side_effect=check_sending
        first=client.post(path,json=payload(),headers=headers)
        replay=client.post(path,json=payload(),headers=headers)
        changed=client.post(path,json={**payload(),'code':'changed'},headers=headers)
        assert first.status_code==replay.status_code==200
        assert first.json()==replay.json() and first.json()['code']=='sent'
        assert first.json()['scan']==payload()['scan']
        assert changed.status_code==409 and changed.json()['detail']['code']=='key_conflict'
        assert send.call_count==1
    with Session(engine) as s:
        log=s.exec(select(PrintLog)).one()
        assert log.qr_scan==payload()['scan'] and log.label_kind=='qr'
        assert log.media_code=='DK-2246' and log.printer_model=='QL-1110NWBc'
        assert log.source_reference=='inventory:item:17' and log.status=='ok'
        assert len(s.exec(select(ApiKey)).all())==1 # synthetic admin credential never saved


@pytest.mark.parametrize('path',['/api/qr-labels','/api/v1/qr-labels'])
@pytest.mark.parametrize('token',[None,'','a b','x'*201])
def test_required_valid_key_never_sends(setup,path,token):
    client,_,key,_=setup
    headers={'X-API-Key':key}
    if token is not None:headers['Idempotency-Key']=token
    with patch.object(qr_labels,'send_brother_job') as send:
        assert client.post(path,json=payload(),headers=headers).status_code in (400,428)
        send.assert_not_called()


def test_auth_and_wrong_protocol(setup):
    client,_,key,app=setup
    assert client.post('/api/v1/qr-labels/preview',json=payload()).status_code==401
    assert client.post('/api/v1/qr-labels',json=payload(),headers={'X-API-Key':'invalid'}).status_code==401
    app.dependency_overrides.pop(require_admin)
    with patch('app.auth_admin.admin_auth_configured',return_value=True):
        assert client.post('/api/qr-labels/preview',json=payload()).status_code==401
    with patch.object(qr_labels,'send_brother_job') as send:
        response=client.post('/api/v1/qr-labels',json={**payload(),'printer_id':2},headers={'X-API-Key':key,'Idempotency-Key':'wrong'})
        assert response.status_code==400
        send.assert_not_called()


@pytest.mark.parametrize('uncertain,code',[(False,'error_not_sent'),(True,'uncertain')])
def test_error_replay_and_explicit_new_attempt(setup,uncertain,code):
    client,engine,key,_=setup
    headers={'X-API-Key':key,'Idempotency-Key':'err'}
    with patch.object(qr_labels,'send_brother_job',side_effect=PrintError('failure',uncertain=uncertain)) as send:
        first=client.post('/api/v1/qr-labels',json=payload(),headers=headers)
        replay=client.post('/api/v1/qr-labels',json=payload(),headers=headers)
        assert first.status_code==replay.status_code==502
        assert first.json()==replay.json() and first.json()['detail']['code']==code
        assert send.call_count==1
    with Session(engine) as s:
        assert s.exec(select(PrintLog)).one().status==('uncertain' if uncertain else 'error')


def test_crash_keeps_visible_attempt_and_reserved_key(setup):
    client,engine,key,_=setup
    headers={'X-API-Key':key,'Idempotency-Key':'interrupted'}
    with patch.object(qr_labels,'send_brother_job',side_effect=RuntimeError('crash')) as send:
        assert client.post('/api/v1/qr-labels',json=payload(),headers=headers).status_code==500
        replay=client.post('/api/v1/qr-labels',json=payload(),headers=headers)
        assert replay.status_code==409 and replay.json()['detail']['code']=='in_progress_or_unknown'
        assert send.call_count==1
    with Session(engine) as s:assert s.exec(select(PrintLog)).one().status=='sending'
    assert client.get('/api/history').json()[0]['status']=='sending'
    counts=client.get('/api/history/summary').json()['totals']
    assert counts['sent']==0 and counts['uncertain']==1


def test_protocol_bind_and_change_guards(setup):
    _,engine,_,_=setup
    with Session(engine) as s:
        with pytest.raises(HTTPException):
            templates.create_template(TemplateCreate(name='T',printer_id=1,bytes_per_row=20,height=100),s)
        with pytest.raises(HTTPException):
            stations.create_station(stations.StationCreate(username='test',display_name='S',password='password1',printer_ids=[1]),s)
        s.rollback()
        t=Template(name='T',printer_id=2,bytes_per_row=20,height=100)
        s.add(t);s.commit();s.refresh(t)
        with pytest.raises(HTTPException):templates.update_template(t.id,TemplatePatch(printer_id=1),s)
        s.rollback()
        with pytest.raises(HTTPException) as err:printers.update_printer(2,PrinterPatch(model='QL-1110NWBc'),s)
        assert err.value.status_code==409
        t=s.get(Template,t.id)
        with pytest.raises(HTTPException):integrations._resolve_api_printer(t,'B',s)


def test_ping_obeys_existing_endpoint_lock(setup):
    from app.printer_dispatch import printer_slot
    with printer_slot('192.0.2.1',9100),patch('socket.create_connection') as connect:
        ok,_,message=ping_printer('192.0.2.1',9100)
        assert not ok and 'busy' in message.lower()
        connect.assert_not_called()
    with patch('app.printer_dispatch.printer_slot',side_effect=OSError('denied')):
        assert ping_printer('192.0.2.1',9100)[0] is False
