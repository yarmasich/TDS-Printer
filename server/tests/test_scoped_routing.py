from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlmodel import SQLModel, Session, create_engine
from app.api import scoped_integrations
from app.db import get_session
from app.auth_apikey import generate_key
from app.models import ApiKey, Integration, Printer, Project

@pytest.fixture
def scope(tmp_path):
    engine=create_engine(f'sqlite:///{tmp_path}/scoped.db',connect_args={'check_same_thread':False})
    SQLModel.metadata.create_all(engine)
    raw,prefix,digest=generate_key(); legacy,lp,ld=generate_key()
    iid=str(uuid4()); project=str(uuid4())
    with Session(engine) as s:
        s.add(Integration(id=iid,name='FloorHub'))
        s.add_all([ApiKey(name='scoped',prefix=prefix,key_hash=digest,integration_id=iid,scopes=['policy.read','policy.write','print']),ApiKey(name='old',prefix=lp,key_hash=ld),Printer(name='Cable',ip='192.0.2.1',protocol='epl2'),Printer(name='QR',ip='192.0.2.2',protocol='brother_ql',model='QL-1110NWBc'),Project(name='Bound')]);s.commit()
    app=FastAPI(); app.include_router(scoped_integrations.router)
    def sessions():
        with Session(engine) as s:yield s
    app.dependency_overrides[get_session]=sessions
    with TestClient(app) as c:yield c,engine,{'X-API-Key':raw},project,legacy
    engine.dispose()

def policy(project,**changes):
    return {'external_project_id':project,'revision':0,'tds_project_id':1,'cable_labels':{'printer_ids':[1],'default_printer_id':1},'qr_labels':{'printer_ids':[2],'default_printer_id':2},**changes}

def test_policy_configuration_and_revision(scope):
    c,_,h,p,_=scope
    config=c.get('/api/v1/integrations/configuration',headers=h)
    assert config.status_code==200
    assert config.json()['printers'][0]['purposes']==['cable_labels']
    path=f'/api/v1/integrations/projects/{p}/policy'
    assert c.get(path,headers=h).json()['revision']==0
    assert c.put(path,headers=h,json=policy(p)).json()['revision']==1
    assert c.put(path,headers=h,json=policy(p)).status_code==409
    allowed=c.get(f'/api/v1/integrations/projects/{p}/printers?purpose=cable_labels',headers=h).json()
    assert [x['id'] for x in allowed['printers']]==[1]
    assert 'ip' not in allowed['printers'][0]

@pytest.mark.parametrize('change',[{'cable_labels':{'printer_ids':[2],'default_printer_id':2}}, {'cable_labels':{'printer_ids':[1,1],'default_printer_id':1}}, {'cable_labels':{'printer_ids':[1],'default_printer_id':2}}, {'tds_project_id':999}, {'unknown':1}])
def test_invalid_policy_atomic(scope,change):
    c,_,h,p,_=scope;path=f'/api/v1/integrations/projects/{p}/policy'
    assert c.put(path,headers=h,json=policy(p,**change)).status_code in (400,422)
    assert c.get(path,headers=h).json()['revision']==0

def test_legacy_key_cannot_read_scoped(scope):
    c,_,_,_,legacy=scope
    assert c.get('/api/v1/integrations/configuration',headers={'X-API-Key':legacy}).status_code==403

from unittest.mock import patch
from app.models import DataHall, Discipline, Label, Template, PrintLog, IntegrationPrintRequest, PolicyAudit, ProjectPrinterAssignment
from app.api import integrations, qr_labels, printers as printer_api
from app.auth_admin import require_admin
from sqlmodel import select


def prepare_labels(engine, count=2):
    with Session(engine) as s:
        s.add(Template(id=1,name='Frozen template',printer_id=1,bytes_per_row=64,height=100))
        s.add(DataHall(id=1,project_id=1,name='Hall'))
        s.add(Discipline(id=1,data_hall_id=1,name='NET',template_id=1))
        s.add_all([Label(discipline_id=1,left_text=f'CBL#{i}.1',right_text=f'CBL#{i}.1') for i in range(1,count+1)])
        s.commit()


def send(c,h,p,token='intent',**changes):
    return c.post(f'/api/v1/integrations/projects/{p}/cable-labels',headers={**h,'Idempotency-Key':token},json={'printer_id':None,'cables':['1.1','2.1'],'discipline':'NET','data_hall':'Hall',**changes})


def test_batch_snapshot_audit_and_rotation_replay(scope):
    c,engine,h,p,_=scope
    prepare_labels(engine)
    assert c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p)).status_code==200
    calls=[]
    def hardware(template,printer,*args):
        calls.append((template.name,printer.name,printer.protocol))
        if len(calls)==1:
            with Session(engine) as s:
                stored=s.get(Printer,1);stored.name='Renamed';s.add(stored)
                template=s.get(Template,1);template.name='Changed';s.add(template);s.commit()
    with patch.object(integrations,'render_and_send',side_effect=hardware):
        response=send(c,h,p)
        assert response.status_code==200 and response.json()['printed']==2
        assert calls==[('Frozen template','Cable','epl2')]*2
        raw,prefix,digest=generate_key()
        with Session(engine) as s:
            first=s.exec(select(ApiKey).where(ApiKey.name=='scoped')).one()
            s.add(ApiKey(name='rotated',prefix=prefix,key_hash=digest,integration_id=first.integration_id,scopes=first.scopes))
            first.enabled=False;s.add(first);s.commit()
        replay=send(c,{'X-API-Key':raw},p)
        assert replay.json()==response.json() and replay.headers['X-Idempotent-Replay']=='true'
        assert len(calls)==2
        assert send(c,{'X-API-Key':raw},p,cables=['1.1']).status_code==409
    with Session(engine) as s:
        logs=s.exec(select(PrintLog)).all()
        assert len(logs)==2
        assert all(x.external_project_id==p and x.print_purpose=='cable_labels' and x.project_id==1 for x in logs)
        assert s.exec(select(PolicyAudit)).one().after['revision']==1


@pytest.mark.parametrize('changes,code',[({'printer_id':2},403),({'printer_id':999},403),({'data_hall':'wrong'},404),({'discipline':'wrong'},404)])
def test_denied_print_never_touches_hardware(scope,changes,code):
    c,e,h,p,_=scope;prepare_labels(e)
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p))
    with patch.object(integrations,'render_and_send',side_effect=AssertionError('No denied send')):
        assert send(c,h,p,**changes).status_code==code


def test_missing_policy_default_binding_and_token_fail_closed(scope):
    c,e,h,p,_=scope;prepare_labels(e)
    assert send(c,h,p).status_code==400
    req=policy(p,tds_project_id=None,cable_labels={'printer_ids':[1],'default_printer_id':None})
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=req)
    assert send(c,h,p,token='new').json()['detail']['code']=='default_missing'
    assert send(c,h,p,token='binding',printer_id=1).json()['detail']['code']=='binding_missing'
    assert c.post(f'/api/v1/integrations/projects/{p}/cable-labels',headers=h,json={'cables':['1.1'],'discipline':'NET','data_hall':'Hall'}).status_code==400


def test_scoped_credentials_block_every_legacy_machine_route(scope):
    c,_,h,_,_=scope
    c.app.include_router(integrations.router);c.app.include_router(qr_labels.integration_router)
    with patch.object(integrations,'render_and_send',side_effect=AssertionError('Forbidden legacy')):
        assert c.get('/api/v1/printers?ping=false',headers=h).status_code==403
        assert c.get('/api/v1/printer-catalog',headers=h).status_code==403
        assert c.post('/api/v1/print',headers=h,json={'cable':'1.1'}).status_code==403
        assert c.post('/api/v1/print-batch',headers=h,json={'cables':['1.1']}).status_code==403
        for route in qr_labels.integration_router.routes:
            # Dependency authorization runs even with invalid QR request bodies.
            if 'POST' in route.methods:
                assert c.post(route.path,headers=h,json={}).status_code==403


def test_capability_changes_hide_default_and_block_send(scope):
    c,e,h,p,_=scope;prepare_labels(e)
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p))
    with Session(e) as s:
        printer=s.get(Printer,1);printer.protocol='unknown';s.add(printer);s.commit()
    allowed=c.get(f'/api/v1/integrations/projects/{p}/printers?purpose=cable_labels',headers=h).json()
    assert allowed['default_printer_id'] is None and allowed['invalid_default'] and not allowed['printers']
    assert send(c,h,p).json()['detail']['code']=='printer_not_allowed'


def test_admin_provisioning_preserves_old_keys_and_namespaces(scope):
    c,e,h,p,_=scope
    c.app.include_router(scoped_integrations.admin_router,dependencies=[__import__('fastapi').Depends(require_admin)])
    assert c.get('/api/integrations').status_code==401
    c.app.dependency_overrides[require_admin]=lambda: 'admin'
    response=c.post('/api/integrations',json={'name':'Second'});assert response.status_code==200
    iid=response.json()['id']
    assert c.post(f'/api/integrations/{iid}/keys',json={'name':'bad','scopes':['legacy_print']}).status_code==422
    assert c.post(f'/api/integrations/{iid}/keys',json={'name':'bad','scopes':[]}).status_code==422
    created=c.post(f'/api/integrations/{iid}/keys',json={'name':'second-scoped','scopes':['policy.read','print']}).json()
    assert 'key' in created and created['integration_id']==iid
    assert c.get('/api/v1/integrations/configuration',headers={'X-API-Key':created['key']}).status_code==200
    listing=c.get('/api/integrations').json()
    assert created['key'] not in str(listing) and 'key_hash' not in str(listing)
    with Session(e) as s:
        assert s.exec(select(ApiKey).where(ApiKey.name=='old')).one().scopes==['legacy_catalog','legacy_print']


def test_assignment_blocks_deletion_and_stable_printer_identity(scope):
    c,e,h,p,_=scope
    c.app.include_router(printer_api.router);c.app.dependency_overrides[require_admin]=lambda:'admin'
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p))
    assert c.delete('/api/printers/1').status_code==409
    with Session(e) as s:
        printer=s.get(Printer,1);printer.name='New name';s.add(printer);s.commit()
    allowed=c.get(f'/api/v1/integrations/projects/{p}/printers?purpose=cable_labels',headers=h).json()
    assert allowed['printers'][0]['id']==1 and allowed['printers'][0]['name']=='New name'


def test_reserved_unknown_never_resends(scope):
    c,e,h,p,_=scope;prepare_labels(e)
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p))
    with patch.object(integrations,'render_and_send',side_effect=RuntimeError('unexpected interruption')):
        with pytest.raises(RuntimeError):send(c,h,p)
    with patch.object(integrations,'render_and_send',side_effect=AssertionError('Never resend')):
        assert send(c,h,p).json()['detail']['code']=='in_progress_or_unknown'


def test_project_namespace_and_scope_separation(scope):
    c,e,h,p,_=scope
    prepare_labels(e)
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p))
    raw,prefix,digest=generate_key(); iid=str(uuid4())
    with Session(e) as s:
        s.add(Integration(id=iid,name='Other integration'));s.commit()
        s.add(ApiKey(name='other',prefix=prefix,key_hash=digest,integration_id=iid,scopes=['policy.read','print']));s.commit()
    other={'X-API-Key':raw}
    assert c.get(f'/api/v1/integrations/projects/{p}/policy',headers=other).json()['revision']==0
    assert send(c,other,p).json()['detail']['code']=='policy_missing'
    assert c.put(f'/api/v1/integrations/projects/{p}/policy',headers=other,json=policy(p)).status_code==403
    with Session(e) as s:
        key=s.exec(select(ApiKey).where(ApiKey.name=='scoped')).one();key.scopes=['policy.read','print','legacy_print'];s.add(key);s.commit()
    assert c.get('/api/v1/integrations/configuration',headers=h).status_code==403


def test_tds_integer_binding_not_project_name(scope):
    c,e,h,p,_=scope;prepare_labels(e)
    with Session(e) as s:
        s.add(Project(id=2,name='Other'));s.add(DataHall(id=2,project_id=2,name='Hall'))
        s.add(Discipline(id=2,data_hall_id=2,name='NET',template_id=1));s.add(Label(discipline_id=2,left_text='CBL#99.1'));s.commit()
    c.put(f'/api/v1/integrations/projects/{p}/policy',headers=h,json=policy(p,tds_project_id=2))
    with patch.object(integrations,'render_and_send') as hardware:
        result=send(c,h,p,cables=['1.1'])
        assert result.json()['printed']==0 and result.json()['results'][0]['status']=='not_found'
        hardware.assert_not_called()
        assert send(c,h,p,token='bound',cables=['99.1']).json()['printed']==1
    with Session(e) as s:
        log=s.exec(select(PrintLog).where(PrintLog.status=='ok')).one()
        assert log.project_id==2


def test_denied_attempt_audit(scope):
    c,e,h,p,_=scope
    assert send(c,h,p).status_code==400
    with Session(e) as s:
        log=s.exec(select(PrintLog)).one()
        assert log.status=='denied' and log.print_purpose=='cable_labels' and log.external_project_id==p
        assert log.error=='policy_missing' and log.printer_ip==''


def configure_panduit(scope, model):
    client, engine, headers, project, _ = scope
    with Session(engine) as session:
        printer = session.get(Printer, 1)
        printer.model = model
        printer.snmp_port = 1161
        printer.snmp_community = 'test-only-read-community'
        session.commit()
    response = client.put(f'/api/v1/integrations/projects/{project}/policy',
                          headers=headers, json=policy(project))
    assert response.status_code == 200


@pytest.mark.parametrize('fault', ['cover_open', 'no_media', 'error'])
@pytest.mark.parametrize('model', ['DP4300H', 'DP4600H'])
def test_panduit_fault_audited_before_send_and_replayed(scope, fault, model):
    client, engine, headers, project, _ = scope
    prepare_labels(engine)
    configure_panduit(scope, model)
    with patch.object(scoped_integrations.printer_device_status, 'device_status',
                      return_value={'state': fault}) as probe, patch.object(integrations, 'render_and_send') as transport:
        response = send(client, headers, project)
        assert response.status_code == 400 and response.json()['detail']['code'] == 'printer_fault'
        probe.assert_called_once_with(1, '192.0.2.1', model, enabled=True, port=1161,
                                      community_override='test-only-read-community', fresh=True)
        with Session(engine) as session:
            log = session.exec(select(PrintLog)).one()
            assert (log.status, log.error) == ('denied', 'printer_fault')
        probe.return_value = {'state': 'ready'}
        replay = send(client, headers, project)
        assert replay.status_code == 400 and replay.json() == response.json()
        assert replay.headers['X-Idempotent-Replay'] == 'true'
        assert probe.call_count == 1
        transport.assert_not_called()
        assert send(client, headers, project, token='new-attempt').json()['printed'] == 2
        assert probe.call_count == 2 and transport.call_count == 2


@pytest.mark.parametrize('state', ['busy', 'unknown'])
@pytest.mark.parametrize('model', ['DP4300H', 'DP4600H'])
def test_panduit_only_probes_for_matched_labels(scope, state, model):
    client, engine, headers, project, _ = scope
    prepare_labels(engine)
    configure_panduit(scope, model)
    with patch.object(scoped_integrations.printer_device_status, 'device_status',
                      return_value={'state': state}) as probe, patch.object(integrations, 'render_and_send') as transport:
        assert send(client, headers, project, token='missing', cables=['99.1']).json()['printed'] == 0
        probe.assert_not_called()
        transport.assert_not_called()
        assert send(client, headers, project).json()['printed'] == 2
        assert probe.call_count == 1 and transport.call_count == 2


@pytest.mark.parametrize('model', ['DP4300H', 'DP4600H'])
def test_scoped_cable_status_uses_saved_config_only_when_requested(scope, model):
    client, _, headers, project, _ = scope
    configure_panduit(scope, model)
    path = f'/api/v1/integrations/projects/{project}/printers?purpose=cable_labels'
    device = scoped_integrations.printer_device_status
    snapshot = {**device._unknown(), 'state': 'busy'}
    with patch.object(device, 'device_statuses', return_value={1: snapshot}) as probes, patch.object(
            scoped_integrations.printer_reachability, 'printer_statuses', return_value={1: True}):
        assert 'device_status' not in client.get(path, headers=headers).json()['printers'][0]
        probes.assert_not_called()
        response = client.get(path + '&ping=true', headers=headers)
        assert response.json()['printers'][0]['device_status'] == snapshot
        config, = probes.call_args.args[0]
        assert config.printer_id == 1 and config.port == 1161 and config.community == 'test-only-read-community'
        assert config.community not in response.text and config.ip not in response.text


def test_switch_to_unsupported_profile_retains_settings_and_skips_probes(scope):
    client, engine, headers, project, _ = scope
    prepare_labels(engine)
    configure_panduit(scope, 'DP4600H')
    client.app.include_router(printer_api.router)
    client.app.dependency_overrides[require_admin] = lambda: 'admin'
    updated = client.put('/api/printers/1', json={'model': 'DP4300HD'})
    assert updated.status_code == 200
    assert updated.json()['snmp_enabled'] and updated.json()['snmp_community_configured']
    assert updated.json()['snmp_port'] == 1161
    device = scoped_integrations.printer_device_status
    with patch.object(device, 'device_statuses') as polling, patch.object(device, 'device_status') as preflight, patch.object(
            scoped_integrations.printer_reachability, 'printer_statuses', return_value={1: True}), patch.object(integrations, 'render_and_send'):
        listing = client.get(f'/api/v1/integrations/projects/{project}/printers?purpose=cable_labels&ping=true', headers=headers)
        assert 'device_status' not in listing.json()['printers'][0]
        assert send(client, headers, project).json()['printed'] == 2
        polling.assert_not_called()
        preflight.assert_not_called()
