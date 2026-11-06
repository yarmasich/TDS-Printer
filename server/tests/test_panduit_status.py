"""The verified Panduit snapshot requires one correlated SNMPv2c GET."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app import printer_device_status as device


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    device._cache.clear()
    monkeypatch.setattr(device.socket, 'socket', MagicMock(side_effect=AssertionError('Unexpected network')))
    monkeypatch.setattr(device.secrets, 'randbelow', lambda _: 122)


def reply(status=3, flags=b'\0', *, model=b'Panduit DP4300H label printer',
          device_type=device._HR_DEVICE_PRINTER, flags_tag=4, request_id=123):
    fields = (device._tlv(4, model), device._tlv(6, device_type),
              device._integer(status), device._tlv(flags_tag, flags))
    items = b''.join(device._tlv(0x30, device._tlv(6, oid) + field)
                     for oid, field in zip(device._PANDUIT_OIDS, fields))
    body = device._integer(request_id) + device._integer(0) * 2 + device._tlv(0x30, items)
    return device._tlv(0x30, device._integer(1) + device._tlv(4, b'sample') + device._tlv(0xa2, body))


def read(**kwargs):
    return device.device_status(9, '192.0.2.4', 'DP4300H', port=1161, community_override='sample', **kwargs)


@pytest.mark.parametrize('status, flags, expected', [
    (3, b'\x00', 'ready'), (4, b'\x00', 'busy'), (5, b'\x00', 'busy'),
    (1, b'\x00', 'unknown'), (2, b'\x00', 'unknown'), (3, b'', 'unknown'),
    (3, b'\x80', 'unknown'), (3, b'\x20', 'unknown'), (3, b'\x00\x01', 'unknown'),
    (4, b'\x40', 'no_media'), (3, b'\x08', 'cover_open'), (3, b'\x48', 'cover_open'),
    (3, b'\x44\x80', 'no_media'), (3, b'\x04', 'error'), (3, b'\x10', 'error'),
    (3, b'\x02', 'error'), (3, b'\x01', 'error'),
])
def test_status_mapping(monkeypatch, status, flags, expected):
    exchange = MagicMock(return_value=reply(status, flags))
    monkeypatch.setattr(device, '_exchange', exchange)
    snapshot = read()
    assert snapshot == dict(state=expected, media_type='unknown', media_width_mm=None,
                            checked_at=snapshot['checked_at'])
    exchange.assert_called_once_with('192.0.2.4', 1161, device._get_request(123, b'sample', 1, device._PANDUIT_OIDS))


@pytest.mark.parametrize('packet', [
    reply(model=b'Other'), reply(device_type=b'wrong'), reply(flags_tag=0x80),
    reply(flags_tag=0x81), reply(request_id=124), reply()[:-1], reply()+b'extra',
    reply(flags=b'\x00'*3), reply(status=99), b'x'*4097,
])
def test_unverified_snapshot(monkeypatch, packet):
    monkeypatch.setattr(device, '_exchange', lambda *args: packet)
    assert read()['state'] == 'unknown'


def test_timeout_and_no_probe_when_disabled(monkeypatch):
    assert read(enabled=False)['state'] == 'unknown'
    assert device.device_status(5, '', 'DP4300H')['state'] == 'unknown'
    assert device.device_status(5, '192.0.2.4', 'DP4300M') is None
    assert device.print_snapshot(SimpleNamespace(model='DP4300H'))['counter'] is None
    exchange = MagicMock(side_effect=TimeoutError())
    monkeypatch.setattr(device, '_exchange', exchange)
    assert read(fresh=True)['state'] == 'unknown'
    exchange.assert_called_once()


def test_print_preflight_bypasses_display_cache(monkeypatch):
    exchange = MagicMock(side_effect=[reply(flags=b'\x08'), reply()])
    monkeypatch.setattr(device, '_exchange', exchange)
    assert read()['state'] == 'cover_open'
    assert read()['state'] == 'cover_open'
    assert read(fresh=True)['state'] == 'ready'
    assert exchange.call_count == 2
