from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep
from unittest.mock import MagicMock

import pytest
from app import printer_device_status as device


def status(**changes):
    data = bytearray(32)
    data[:6] = device._HEADER
    data[10], data[11] = 62, 10
    for offset, value in changes.items():
        data[int(offset)] = value
    return bytes(data)


def response(payload=None, request_id=123, community=b'public', oid=None, error=0, tag=0xa2):
    binding = device._tlv(0x30, device._tlv(6, oid or device._STATUS_OID) + device._tlv(4, payload or status()))
    pdu = device._tlv(tag, device._integer(request_id) + device._integer(error) + device._integer(0) + device._tlv(0x30, binding))
    return device._tlv(0x30, device._integer(0) + device._tlv(4, community) + pdu)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    device._cache.clear(); device._inflight.clear()
    monkeypatch.delenv('BROTHER_SNMP_COMMUNITY', raising=False)
    # No test may contact physical hardware, even after an assertion failure.
    monkeypatch.setattr(device.socket, 'socket', MagicMock(side_effect=AssertionError('Unexpected network')))


@pytest.mark.parametrize('changes,state', [({},'ready'),({'8':16},'busy'),({'8':1},'no_media'),
    ({'9':16},'cover_open'),({'8':4},'error'),({'9':1},'error'),({'18':2},'error'),
    ({'8':2},'unknown'),({'19':1},'unknown'),({'22':3},'unknown'),({'18':1},'unknown'),
    ({'4':67},'unknown'),({'11':99},'unknown'),({'10':0},'unknown'),({'13':1},'unknown'),
    ({'11':0,'10':0},'no_media'),({'10':104},'ready'),({'11':11,'17':29},'ready')])
def test_hardware_packet(changes,state):
    result=device.parse_status(status(**changes))
    assert result['state']==state
    assert result['checked_at'].endswith('+00:00')
    assert set(result)=={'state','media_type','media_width_mm','checked_at'}


def test_unknown_frame_and_media():
    assert device.parse_status(b'')['state']=='unknown'
    assert device.parse_status(status()+b'\0')['state']=='unknown'
    assert device.parse_status(status())['media_width_mm']==62
    assert device.parse_status(status())['media_type']=='continuous'
    assert device.parse_status(status(**{'11':11,'17':29}))['media_type']=='die_cut'


def test_strict_response():
    assert device._response(response(),123,b'public')==status()
    for packet in [response(request_id=124), response(community=b'other'),response(oid=b'wrong'),
                   response(error=1),response(tag=0xa0),response(payload=b'x'),
                   response()+b'\0',response()[:-1],b'\x30\x80',b'\x30\x81\x01\0']:
        with pytest.raises(ValueError): device._response(packet,123,b'public')


def test_get_only_socket_and_no_print_channel(monkeypatch):
    sock=MagicMock();sock.__enter__.return_value=sock
    sock.recv.return_value=response()
    factory=MagicMock(return_value=sock)
    monkeypatch.setattr(device.socket,'socket',factory)
    monkeypatch.setattr(device.secrets,'randbelow',lambda _:122)
    result=device.device_status(1,'192.0.2.1','QL-1110NWBc')
    assert result['state']=='ready'
    sock.connect.assert_called_once_with(('192.0.2.1',161))
    assert len(sock.settimeout.call_args_list) == 3
    assert all(0 < call.args[0] <= .5 for call in sock.settimeout.call_args_list)
    sock.send.assert_called_once_with(device._request(123,b'public'))
    # Only GET PDU in request. No initialization, status or raster commands.
    packet=sock.send.call_args.args[0]
    root=device._Reader(packet); message=device._Reader(root.value(0x30))
    assert message.integer()==0 and message.value(4)==b'public'
    assert message.value(0xa0)
    sock.recv.assert_called_once_with(4097)


def test_timeout_unknown_and_model_restriction(monkeypatch):
    probe=MagicMock(side_effect=TimeoutError())
    monkeypatch.setattr(device,'_probe',probe)
    assert device.device_status(1,'192.0.2.1','QL-1110NWBc')['state']=='unknown'
    assert device.device_status(2,'192.0.2.1','other') is None
    assert probe.call_count==1
    monkeypatch.setenv('BROTHER_SNMP_COMMUNITY','')
    assert device.device_status(3,'192.0.2.1','QL-1110NWBc')['state']=='unknown'
    assert probe.call_count==1


def test_cache_preserves_timestamp_and_bounded(monkeypatch):
    probe=MagicMock(return_value=device.parse_status(status()))
    monkeypatch.setattr(device,'_probe',probe)
    clock=[0];monkeypatch.setattr(device,'monotonic',lambda:clock[0])
    first=device.device_status(1,'192.0.2.1','QL-1110NWBc')
    first['state']='error'
    assert device.device_status(1,'192.0.2.1','QL-1110NWBc')['state']=='ready'
    assert probe.call_count==1
    clock[0]=5
    assert device.device_status(1,'192.0.2.1','QL-1110NWBc')['checked_at']==first['checked_at']
    assert probe.call_count==2
    for pid in range(1030): device.device_status(pid,'192.0.2.1','QL-1110NWBc')
    assert len(device._cache)==1024


def test_bounded_requests_and_independent_timeout(monkeypatch):
    def probe(ip, community):
        if ip=='192.0.2.1':
            sleep(.05)
            raise TimeoutError()
        return device.parse_status(status())
    monkeypatch.setattr(device,'_probe',probe)
    started=monotonic()
    result=device.device_statuses([(i,'192.0.2.1' if i==0 else '192.0.2.2','QL-1110NWBc') for i in range(35)])
    assert monotonic()-started<1
    assert result[0]['state']=='unknown' and result[1]['state']=='ready'
    assert result[31] is not None and result[32] is None


def test_singleflight(monkeypatch):
    from threading import Event
    started,release=Event(),Event()
    def probe(*args):
        started.set();assert release.wait(2)
        return device.parse_status(status())
    monkeypatch.setattr(device,'_probe',probe)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(device.device_status,1,'192.0.2.1','QL-1110NWBc')
        assert started.wait(1)
        try: assert pool.submit(device.device_status,1,'192.0.2.1','QL-1110NWBc').result(1)['state']=='unknown'
        finally: release.set()
        assert first.result(1)['state']=='ready'
