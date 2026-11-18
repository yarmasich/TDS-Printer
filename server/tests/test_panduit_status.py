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


def counter_reply(value=1234, *, request_id=123, community=b'sample', exception=None, raw=None, oid=None,
                  exception_body=b''):
    """A prtMarkerLifeCount.1.1 answer: Counter32, an SNMPv2 exception or raw bytes."""
    if exception is not None:
        field = device._tlv(exception, exception_body)
    else:
        data = raw if raw is not None else device._integer(value)[2:]
        field = device._tlv(0x41, data)
    item = device._tlv(0x30, device._tlv(6, oid or device._COUNTER_OID) + field)
    body = device._integer(request_id) + device._integer(0) * 2 + device._tlv(0x30, item)
    return device._tlv(0x30, device._integer(1) + device._tlv(4, community) + device._tlv(0xa2, body))


def is_counter(request):
    return device._COUNTER_OID in request


def panduit_exchange(status, counter=None):
    """Fake `_exchange` answering the status GET and the counter GET separately.

    `status`/`counter` are reply packets or exceptions to raise. A missing
    counter answers noSuchObject, as a model without the counter would.
    """
    counter = counter_reply(exception=0x80) if counter is None else counter
    def answer(ip, port, request):
        value = counter if is_counter(request) else status
        if isinstance(value, BaseException):
            raise value
        return value
    return MagicMock(side_effect=answer)


def status_reads(exchange):
    return sum(not is_counter(call.args[2]) for call in exchange.call_args_list)


def read(**kwargs):
    return device.device_status(9, '192.0.2.4', 'DP4300H', port=1161, community_override='sample', **kwargs)


@pytest.mark.parametrize('status, flags, expected', [
    (3, b'\x00', 'ready'), (4, b'\x00', 'busy'), (5, b'\x00', 'busy'),
    (1, b'\x00', 'unknown'), (2, b'\x00', 'unknown'), (3, b'', 'unknown'),
    (3, b'\x00\x01', 'unknown'),
    (4, b'\x40', 'no_media'), (3, b'\x08', 'cover_open'), (3, b'\x48', 'cover_open'),
    (3, b'\x44\x80', 'no_media'), (3, b'\x04', 'error'), (3, b'\x10', 'error'),
    (3, b'\x02', 'error'), (3, b'\x01', 'error'),
])
def test_status_mapping(monkeypatch, status, flags, expected):
    exchange = panduit_exchange(reply(status, flags))
    monkeypatch.setattr(device, '_exchange', exchange)
    snapshot = read()
    assert snapshot == dict(state=expected, media_type='unknown', media_width_mm=None,
                            checked_at=snapshot['checked_at'], warnings=[], counter=None)
    status_request, counter_request = (call.args for call in exchange.call_args_list)
    assert status_request == ('192.0.2.4', 1161, device._get_request(123, b'sample', 1, device._PANDUIT_OIDS))
    # The counter is its own SNMPv2c GET, sent only after the status answer.
    assert counter_request == ('192.0.2.4', 1161, device._get_request(123, b'sample', 1, (device._COUNTER_OID,)))


# RFC 2790 bits, MSB first. Only lowPaper, lowToner and overduePreventMaint are
# warnings; they never change the state hrPrinterStatus gives.
@pytest.mark.parametrize('flags, warnings', [
    (b'\x80', ['media_low']), (b'\x20', ['ribbon_low']), (b'\x00\x02', ['maintenance_due']),
    (b'\xa0\x02', ['media_low', 'ribbon_low', 'maintenance_due']),
])
@pytest.mark.parametrize('status, state', [(3, 'ready'), (4, 'busy'), (5, 'busy'), (1, 'unknown')])
def test_warning_bits_alone_keep_the_printer_status(monkeypatch, flags, warnings, status, state):
    monkeypatch.setattr(device, '_exchange', panduit_exchange(reply(status, flags)))
    snapshot = read(fresh=True)
    assert (snapshot['state'], snapshot['warnings']) == (state, warnings)


@pytest.mark.parametrize('flags, cover, state, warnings', [
    (b'\xc0', 6, 'no_media', ['media_low']),           # noPaper + lowPaper
    (b'\x30', 6, 'error', ['ribbon_low']),             # noToner + lowToner
    (b'\x28', 6, 'cover_open', ['ribbon_low']),        # doorOpen + lowToner
    (b'\x20', 5, 'cover_open', ['ribbon_low']),        # interlock open + lowToner
    (b'\x04\x02', 6, 'error', ['maintenance_due']),   # jammed + overduePreventMaint
])
def test_a_fault_keeps_priority_and_carries_its_warnings(monkeypatch, flags, cover, state, warnings):
    monkeypatch.setattr(device, '_exchange', panduit_exchange(reply(3, flags, cover=cover)))
    snapshot = read(fresh=True)
    assert (snapshot['state'], snapshot['warnings']) == (state, warnings)


@pytest.mark.parametrize('flags, warnings', [
    (b'\x00\x80', []),                 # inputTrayMissing
    (b'\x00\x01', []),                 # undefined in RFC 2790
    (b'\x20\x08', ['ribbon_low']),     # outputFull beside a warning
    (b'\x80\x04', ['media_low']),      # inputTrayEmpty beside a warning
])
def test_any_other_bit_is_unknown_never_ready(monkeypatch, flags, warnings):
    monkeypatch.setattr(device, '_exchange', panduit_exchange(reply(3, flags)))
    snapshot = read(fresh=True)
    assert (snapshot['state'], snapshot['warnings']) == ('unknown', warnings)


@pytest.mark.parametrize('flags', [b'\x80', b'\x20', b'\x00\x02'])
def test_warnings_never_hold_a_print(monkeypatch, flags):
    printer = SimpleNamespace(id=9, ip='192.0.2.4', model='DP4600H', name='WS1', snmp_enabled=True,
                              snmp_port=1161, snmp_community='sample')
    monkeypatch.setattr(device, '_exchange', panduit_exchange(
        reply(3, flags, model=b'Panduit DP4600H label printer'), counter_reply(77)))
    assert device.print_fault_state(printer) is None
    assert device.print_preflight(printer) == (None, 77)


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
    answers = iter([reply(flags=b'\x08'), reply()])
    exchange = MagicMock(side_effect=lambda ip, port, request: (
        counter_reply(exception=0x80) if is_counter(request) else next(answers)))
    monkeypatch.setattr(device, '_exchange', exchange)
    assert read()['state'] == 'cover_open'
    assert read()['state'] == 'cover_open'
    assert read(fresh=True)['state'] == 'ready'
    assert status_reads(exchange) == 2


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
    exchange = panduit_exchange(response, counter_reply(5, community=b'public'))
    monkeypatch.setattr(device, '_exchange', exchange)
    assert device.device_status(9, '192.0.2.4', 'DP4600H')['counter'] == 5
    unverified = device.device_status(9, '192.0.2.4', 'DP4300H')
    # A device that is not the configured model is never asked for a counter.
    assert (unverified['state'], unverified['counter']) == ('unknown', None)
    assert exchange.call_count == 3 and status_reads(exchange) == 2
    for call in exchange.call_args_list:
        oids = (device._COUNTER_OID,) if is_counter(call.args[2]) else device._PANDUIT_OIDS
        assert call.args[2] == device._get_request(123, b'public', 1, oids)


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


# prtMarkerLifeCount.1.1 is read in its own GET after the status answer. Every
# failure is a null counter; none can change the state already read.
@pytest.mark.parametrize('counter, expected', [
    (counter_reply(0), 0), (counter_reply(1234), 1234), (counter_reply(0xffffffff), 0xffffffff),
    (counter_reply(raw=b'\x00\xff'), 255),
    (counter_reply(exception=0x80), None),                  # noSuchObject
    (counter_reply(exception=0x81), None),                  # noSuchInstance
    (TimeoutError('silent'), None), (OSError('unreachable'), None),
    (counter_reply(raw=b''), None), (counter_reply(raw=b'\x80'), None),
    (counter_reply(raw=b'\x00\x01'), None),                 # noncanonical
    (counter_reply(raw=b'\x01\x00\x00\x00\x00'), None),     # over Counter32
    (counter_reply(request_id=124), None), (counter_reply(community=b'other'), None),
    (counter_reply(oid=device._PANDUIT_OIDS[0]), None),
    (counter_reply()[:-1], None), (counter_reply() + b'\0', None),
    (reply(), None),                                       # a status answer, not a counter
    (bytes([0x30, 0x81, 0x00]), None),
])
@pytest.mark.parametrize('flags, state', [(b'\x00', 'ready'), (b'\x08', 'cover_open'), (b'\x20', 'ready')])
def test_counter_value_or_none_never_changes_the_state(monkeypatch, counter, expected, flags, state):
    monkeypatch.setattr(device, '_exchange', panduit_exchange(reply(3, flags), counter))
    snapshot = read(fresh=True)
    assert snapshot['counter'] == expected
    assert snapshot['state'] == state
    assert snapshot['warnings'] == (['ribbon_low'] if flags == b'\x20' else [])


def test_counter_exception_value_must_be_empty(monkeypatch):
    malformed = counter_reply(exception=0x80, exception_body=b'\0')
    monkeypatch.setattr(device, '_exchange', panduit_exchange(reply(), malformed))
    real = device._Reader
    seen = []
    def reader(data):
        seen.append(data)
        return real(data)
    monkeypatch.setattr(device, '_Reader', reader)
    snapshot = read(fresh=True)
    assert (snapshot['state'], snapshot['counter']) == ('ready', None)
    # The packet itself is well formed: only the non-empty exception value fails.
    assert any(data.startswith(device._tlv(6, device._COUNTER_OID)) for data in seen)


def test_counter_is_cached_with_the_status(monkeypatch):
    exchange = panduit_exchange(reply(3, b'\x20'), counter_reply(42))
    monkeypatch.setattr(device, '_exchange', exchange)
    clock = [0]
    monkeypatch.setattr(device, 'monotonic', lambda: clock[0])
    first = read()
    first['warnings'].append('caller-edit')
    cached = read()
    assert (cached['state'], cached['warnings'], cached['counter']) == ('ready', ['ribbon_low'], 42)
    assert exchange.call_count == 2  # one status GET + one counter GET for both reads
    clock[0] = 5
    assert read()['counter'] == 42 and exchange.call_count == 4


def test_a_silent_printer_is_not_asked_for_a_counter(monkeypatch):
    # A dropped status GET already used its budget: no second 0.5 s wait.
    exchange = panduit_exchange(TimeoutError('silent'), counter_reply(42))
    monkeypatch.setattr(device, '_exchange', exchange)
    snapshot = read(fresh=True)
    assert (snapshot['state'], snapshot['counter'], snapshot['warnings']) == ('unknown', None, [])
    assert exchange.call_count == 1


def test_snmp_off_reads_no_counter(monkeypatch):
    exchange = panduit_exchange(reply(), counter_reply(42))
    monkeypatch.setattr(device, '_exchange', exchange)
    off = read(enabled=False)
    assert (off['state'], off['warnings'], off['counter']) == ('unknown', [], None)
    printer = SimpleNamespace(id=9, ip='192.0.2.4', model='DP4300H', name='WS1', snmp_enabled=False,
                              snmp_port=1161, snmp_community='sample')
    assert device.print_preflight(printer) == (None, None)
    assert device.print_counter(printer) is None
    exchange.assert_not_called()


def test_after_counter_is_one_counter_get(monkeypatch):
    exchange = panduit_exchange(AssertionError('No status read after the sends'), counter_reply(1240))
    monkeypatch.setattr(device, '_exchange', exchange)
    printer = SimpleNamespace(id=9, ip='192.0.2.4', model='DP4300H', name='WS1', snmp_enabled=True,
                              snmp_port=1161, snmp_community='sample')
    assert device.print_counter(printer) == 1240
    exchange.assert_called_once_with('192.0.2.4', 1161, device._get_request(123, b'sample', 1, (device._COUNTER_OID,)))


def test_counter_timeout_stays_inside_its_own_budget(monkeypatch):
    # The counter GET gets its own <=0.5 s socket deadline, like the status GET.
    sock = MagicMock(); sock.__enter__.return_value = sock
    sock.recv.side_effect = [reply(), TimeoutError()]
    monkeypatch.setattr(device.socket, 'socket', MagicMock(return_value=sock))
    snapshot = read(fresh=True)
    assert (snapshot['state'], snapshot['counter']) == ('ready', None)
    assert sock.send.call_count == 2
    assert all(0 < call.args[0] <= device._TIMEOUT for call in sock.settimeout.call_args_list)
