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
          device_type=device._HR_DEVICE_PRINTER, flags_tag=4, request_id=123, cover=6):
    # cover=None answers noSuchInstance, as a model without a prtCoverTable row does.
    cover_field = bytes([0x81, 0]) if cover is None else device._integer(cover)
    fields = (device._tlv(4, model), device._tlv(6, device_type),
              device._integer(status), device._tlv(flags_tag, flags), cover_field)
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
    assert device.device_status(5, '192.0.2.4', 'DP4300HD') is None
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


@pytest.mark.parametrize('configured,reported,expected', [
    ('DP4300M', b'Panduit DP4300M label printer', 'no_media'),
    ('DP4300M', b'Panduit DP4300H label printer', 'unknown'),
    ('DP4600H', b'Panduit DP4600H label printer', 'no_media'),
    ('DP4300H', b'Panduit DP4600H label printer', 'unknown'),
    ('DP4600H', b'Panduit DP4300H label printer', 'unknown'),
])
def test_status_requires_exact_configured_model(monkeypatch, configured, reported, expected):
    monkeypatch.setattr(device, '_exchange', lambda *args: reply(flags=b'\x40', model=reported))
    assert device.device_status(9, '192.0.2.4', configured, community_override='sample')['state'] == expected


def test_cache_isolated_after_model_change_and_default_community(monkeypatch):
    monkeypatch.setenv('BROTHER_SNMP_COMMUNITY', 'brother-only')
    response = reply(model=b'Panduit DP4600H label printer').replace(b'sample', b'public')
    exchange = MagicMock(return_value=response)
    monkeypatch.setattr(device, '_exchange', exchange)
    assert device.device_status(9, '192.0.2.4', 'DP4600H')['state'] == 'ready'
    assert device.device_status(9, '192.0.2.4', 'DP4300H')['state'] == 'unknown'
    assert exchange.call_count == 2
    for call in exchange.call_args_list:
        assert call.args[2] == device._get_request(123, b'public', 1, device._PANDUIT_OIDS)


def test_4600h_unexpected_device_index_and_malformed_fields(monkeypatch):
    packet = reply(model=b'Panduit DP4600H label printer')
    index_oid = device._PANDUIT_OIDS[1]
    for malformed in (packet.replace(index_oid, index_oid[:-1] + b'\x02'),
                      reply(model=b'Panduit DP4600H label printer', device_type=b'wrong'),
                      reply(model=b'Panduit DP4600H label printer', flags=b'\x04'*3)):
        monkeypatch.setattr(device, '_exchange', lambda *args: malformed)
        assert device.device_status(9, '192.0.2.4', 'DP4600H', community_override='sample', fresh=True)['state'] == 'unknown'


# Captured live from a DP4600H (cab firmware) on 2026-11-17. With the printhead
# open it kept reporting idle, no error flags and "Ready" on its own display —
# prtCoverStatus (5 interlockOpen / 6 interlockClosed) was the only signal.
@pytest.mark.parametrize('status, flags, cover, expected', [
    (3, b'\x00', 5, 'cover_open'),   # head open, panel "Ready"
    (3, b'\x00', 6, 'ready'),        # head closed, panel "Ready"
    (4, b'\x00', 6, 'busy'),         # panel "Printing"
    (1, b'B', 6, 'no_media'),         # panel "Error - Out of paper" (0x42)
    (1, b'B', 5, 'cover_open'),       # out of paper, head opened to reload
])
def test_dp4600h_live_captures(monkeypatch, status, flags, cover, expected):
    monkeypatch.setattr(device, '_exchange', lambda *args: reply(
        status, flags, cover=cover, model=b'Panduit DP4600H label printer'))
    assert device.device_status(9, '192.0.2.4', 'DP4600H', community_override='sample',
                                fresh=True)['state'] == expected


@pytest.mark.parametrize('cover', [3, 5])  # coverOpen, interlockOpen
def test_open_cover_outranks_a_supply_warning(monkeypatch, cover):
    monkeypatch.setattr(device, '_exchange', lambda *args: reply(3, b'\x80', cover=cover))
    assert read(fresh=True)['state'] == 'cover_open'


@pytest.mark.parametrize('flags, expected', [(b'\x00', 'ready'), (b'\x40', 'no_media')])
def test_a_model_without_a_cover_row_keeps_its_flag_reading(monkeypatch, flags, expected):
    monkeypatch.setattr(device, '_exchange', lambda *args: reply(3, flags, cover=None))
    assert read(fresh=True)['state'] == expected
