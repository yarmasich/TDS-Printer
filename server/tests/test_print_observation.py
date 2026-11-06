from contextlib import contextmanager
from unittest.mock import Mock
import pytest
from app import printer_brother as transport, printer_device_status as snmp
from app.models import Printer
from app.printer import PrintError

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(snmp.socket,'socket',Mock(side_effect=AssertionError('Unexpected network')))

def snapshot(counter=10,state='ready',width=62):
    return {'counter':counter,'status':{'state':state,'media_width_mm':width,'media_type':'continuous'}}

def device():
    return Printer(name='Test',ip='192.0.2.1',model='QL-1110NWBc',protocol='brother_ql')

@pytest.fixture
def harness(monkeypatch):
    events=[]
    @contextmanager
    def slot(*a,**k):
        events.append('lock');yield;events.append('unlock')
    sock=Mock();sock.recv.return_value=b''
    sock.sendall.side_effect=lambda *a:events.append('send')
    connect=Mock(return_value=sock)
    monkeypatch.setattr(transport,'printer_slot',slot)
    monkeypatch.setattr(transport.socket,'create_connection',connect)
    now=[0.]
    monkeypatch.setattr(transport.time,'monotonic',lambda:now[0])
    monkeypatch.setattr(transport.time,'sleep',lambda n:now.__setitem__(0,now[0]+n))
    def install(values):
        it=iter(values);last=values[-1]
        def probe(*a):
            events.append('probe');return next(it,last)
        monkeypatch.setattr(snmp,'print_snapshot',probe)
    return events,connect,install

@pytest.mark.parametrize('state,width',[('no_media',62),('cover_open',62),('error',62),('busy',62),('ready',103)])
def test_preflight_denies_before_bytes(harness,state,width):
    events,connect,install=harness;install([snapshot(state=state,width=width)])
    with pytest.raises(PrintError) as err:transport.send_brother_job(device(),b'raster',media='DK-2205')
    assert not err.value.uncertain
    connect.assert_not_called()

def test_counter_observation_under_lock(harness):
    events,connect,install=harness;install([snapshot(),snapshot(),snapshot(11)])
    assert transport.send_brother_job(device(),b'raster',media='DK-2205')=='counter_advanced'
    assert events==['lock','probe','send',*(['probe']*5),'unlock']
    connect.return_value.sendall.assert_called_once()

@pytest.mark.parametrize('before,after',[(snapshot(),snapshot()),(snapshot(None),snapshot(11)),(snapshot(),snapshot(12)),(snapshot(),snapshot(0)),(snapshot(4294967295),snapshot(0)),(snapshot(),snapshot(11,state='no_media')),(snapshot(state='unknown'),snapshot(11))])
def test_uncertain_samples_never_claim_observation(harness,before,after):
    events,connect,install=harness;install([before,after])
    assert transport.send_brother_job(device(),b'raster',media='DK-2205')=='unconfirmed'
    connect.return_value.sendall.assert_called_once()
    assert events[-1]=='unlock' and events.count('probe')<=20

def test_disabled_snapshot_no_network():
    p=device();p.snmp_enabled=False
    result=snmp.print_snapshot(p)
    assert result['counter'] is None and result['status']['state']=='unknown'

def counter_response(value,oid=None,tag=0x41,request=123):
    bind=snmp._tlv(0x30,snmp._tlv(6,oid or snmp._COUNTER_OID)+snmp._tlv(tag,value))
    pdu=snmp._tlv(0xa2,snmp._integer(request)+snmp._integer(0)+snmp._integer(0)+snmp._tlv(0x30,bind))
    return snmp._tlv(0x30,snmp._integer(0)+snmp._tlv(4,b'public')+pdu)

@pytest.mark.parametrize('raw,expected',[(b'\x00',0),(b'\x7f',127),(b'\x00\x80',128),(b'\x00\xff\xff\xff\xff',4294967295)])
def test_counter32_response(raw,expected):
    assert snmp._response(counter_response(raw),123,b'public',snmp._COUNTER_OID)==expected

@pytest.mark.parametrize('raw',[b'',b'\x80',b'\x00\x01',b'\x01\x00\x00\x00\x00'])
def test_counter32_invalid(raw):
    with pytest.raises(ValueError):snmp._response(counter_response(raw),123,b'public',snmp._COUNTER_OID)

def test_counter_identity_and_tag():
    for kwargs in [{'request':124},{'oid':b'wrong'},{'tag':2}]:
        with pytest.raises(ValueError):snmp._response(counter_response(b'\x01',**kwargs),123,b'public',snmp._COUNTER_OID)

@pytest.mark.parametrize('error',[OSError,ValueError,RuntimeError])
def test_observation_exception_does_not_invalidate_send(harness,monkeypatch,error):
    events,connect,install=harness
    monkeypatch.setattr(snmp,'print_snapshot',Mock(side_effect=[snapshot(),error('failure')]))
    assert transport.send_brother_job(device(),b'raster',media='DK-2205')=='unconfirmed'
    connect.return_value.sendall.assert_called_once()

def test_preflight_exception_is_not_sent(harness,monkeypatch):
    events,connect,install=harness
    monkeypatch.setattr(snmp,'print_snapshot',Mock(side_effect=RuntimeError('failure')))
    with pytest.raises(transport.PrinterNotReady):transport.send_brother_job(device(),b'raster',media='DK-2205')
    connect.assert_not_called()

def test_late_prior_and_current_increments_do_not_count(harness):
    # A stable single global increment can still belong to another job. Never proof.
    events,connect,install=harness;install([snapshot(),snapshot(11),snapshot(12)])
    assert transport.send_brother_job(device(),b'raster',media='DK-2205')=='unconfirmed'

@pytest.mark.parametrize('width',[102,103,104])
def test_unverified_large_roll_not_blocked(harness,width):
    events,connect,install=harness;install([snapshot(width=width)])
    assert transport.send_brother_job(device(),b'raster',media='DK-2246')=='unconfirmed'
    connect.return_value.sendall.assert_called_once()

def test_counter_failure_keeps_status_and_cache(monkeypatch):
    monkeypatch.setattr(snmp,'_probe',lambda *a:snapshot()['status'])
    monkeypatch.setattr(snmp,'_probe_value',Mock(side_effect=TimeoutError()))
    before=dict(snmp._cache)
    sample=snmp.print_snapshot(device())
    assert sample['status']['state']=='ready' and sample['counter'] is None
    assert dict(snmp._cache)==before
