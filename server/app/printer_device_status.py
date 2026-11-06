"""Read-only Brother SNMP snapshots. Never touches the raster/printing socket.

Brother developer FAQ specifies this fixed OID for QL-1110NWB. Its octet value
uses the ESC/P reference docp100367, pp90–91 (not the raster status layout).
A ready snapshot is not print completion or a guarantee of remaining paper.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import os
import secrets
import socket
from threading import Lock
from time import monotonic

# BER encoding of 1.3.6.1.4.1.2435.3.3.9.1.6.1.0; no caller-defined OIDs.
_STATUS_OID = bytes.fromhex('2b06010401930303030901060100')
# Fixed Printer-MIB prtMarkerLifeCount. A global counter, not a job receipt.
_COUNTER_OID = bytes.fromhex('2b060102012b0a0201040101')
_HEADER = bytes.fromhex('802042344430')
_MODELS = {'QL-1110NWB', 'QL-1110NWBc'}
_TIMEOUT = 0.5
_CACHE_TTL = 5.0
_CACHE_LIMIT = 1024
_REQUEST_LIMIT = 32
_cache = OrderedDict()
_inflight = set()
_lock = Lock()


def _tlv(tag, value):
    size = len(value)
    length = bytes([size]) if size < 128 else bytes([0x82]) + size.to_bytes(2, 'big')
    if size >= 128 and size < 256:
        length = bytes([0x81, size])
    return bytes([tag]) + length + value


def _integer(value):
    data = value.to_bytes(max(1, (value.bit_length() + 7) // 8), 'big')
    if data[0] & 0x80:
        data = b'\x00' + data
    return _tlv(2, data)


class _Reader:
    """Small, strict definite-length BER reader for a single fixed SNMP reply."""
    def __init__(self, data):
        self.data, self.pos = data, 0

    def value(self, tag):
        if self.pos + 2 > len(self.data) or self.data[self.pos] != tag:
            raise ValueError('Unexpected BER field')
        self.pos += 1
        size = self.data[self.pos]
        self.pos += 1
        if size & 0x80:
            count = size & 0x7f
            if count not in (1, 2) or self.pos + count > len(self.data):
                raise ValueError('Invalid BER length')
            raw = self.data[self.pos:self.pos + count]
            self.pos += count
            size = int.from_bytes(raw, 'big')
            if raw[0] == 0 or size < 128:
                raise ValueError('Noncanonical BER length')
        end = self.pos + size
        if end > len(self.data):
            raise ValueError('Truncated BER')
        value = self.data[self.pos:end]
        self.pos = end
        return value

    def integer(self):
        data = self.value(2)
        if not data or len(data) > 4 or data[0] & 0x80:
            raise ValueError('Invalid nonnegative integer')
        if len(data) > 1 and data[0] == 0 and not data[1] & 0x80:
            raise ValueError('Noncanonical integer')
        return int.from_bytes(data, 'big')

    def done(self):
        if self.pos != len(self.data):
            raise ValueError('Trailing BER fields')


def _request(request_id, community, oid=_STATUS_OID):
    if oid not in (_STATUS_OID, _COUNTER_OID):
        raise ValueError("Unsupported OID")
    binding = _tlv(0x30, _tlv(6, oid) + _tlv(5, b''))
    pdu = _tlv(0xa0, _integer(request_id) + _integer(0) + _integer(0) + _tlv(0x30, binding))
    return _tlv(0x30, _integer(0) + _tlv(4, community) + pdu)


def _response(data, request_id, community, oid=_STATUS_OID):
    if oid not in (_STATUS_OID, _COUNTER_OID):
        raise ValueError("Unsupported OID")
    if len(data) > 4096:
        raise ValueError('Oversized response')
    outer = _Reader(data)
    message = _Reader(outer.value(0x30)); outer.done()
    if message.integer() != 0 or message.value(4) != community:
        raise ValueError('Unexpected SNMP identity')
    pdu = _Reader(message.value(0xa2)); message.done()
    if pdu.integer() != request_id or pdu.integer() != 0 or pdu.integer() != 0:
        raise ValueError('SNMP request mismatch or error')
    bindings = _Reader(pdu.value(0x30)); pdu.done()
    binding = _Reader(bindings.value(0x30)); bindings.done()
    if binding.value(6) != oid:
        raise ValueError('Unexpected OID')
    if oid == _COUNTER_OID:
        raw = binding.value(0x41); binding.done()
        if not raw or len(raw) > 5 or raw[0] & 0x80:
            raise ValueError('Invalid Counter32')
        if len(raw) > 1 and raw[0] == 0 and not raw[1] & 0x80:
            raise ValueError('Noncanonical Counter32')
        counter = int.from_bytes(raw, 'big')
        if counter > 0xffffffff:
            raise ValueError('Counter32 overflow')
        return counter
    status = binding.value(4); binding.done()
    if len(status) != 32:
        raise ValueError('Invalid status size')
    return status


def _unknown():
    return dict(state='unknown', media_width_mm=None, media_type='unknown',
                checked_at=datetime.now(timezone.utc).isoformat())


def parse_status(data):
    result = _unknown()
    if len(data) != 32 or data[:6] != _HEADER:
        return result
    # Reject unknown modes/phases/reserved bits instead of guessing readiness.
    if any(data[i] for i in (6, 7, 12, 15, 16, 19, 20, 21, 22, 23, *range(24, 32))):
        return result
    if data[18] not in (0, 2):
        return result
    error1, error2 = data[8], data[9]
    if error1 & ~0x35 or error2 & ~0xd7:
        return result
    media = {0: 'none', 10: 'continuous', 11: 'die_cut'}.get(data[11])
    if media is None:
        return result
    width, length = data[10], (data[13] << 8) | data[17]
    result.update(media_type=media, media_width_mm=width or None)
    if error2 & 0x10:
        result['state'] = 'cover_open'
    elif error1 & 1 or media == 'none':
        result['state'] = 'no_media'
    elif error1 & ~0x10 or error2 or data[18] == 2:
        result['state'] = 'error'
    elif error1 & 0x10:
        result['state'] = 'busy'
    elif width and ((media == 'continuous' and length == 0) or (media == 'die_cut' and length > 0)):
        result['state'] = 'ready'
    return result


def _probe_value(ip, community, port=161, oid=_STATUS_OID):
    # Numeric configured addresses avoid unbounded DNS resolution in status polling.
    address = ipaddress.ip_address(ip)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    request_id = secrets.randbelow(0x7ffffffe) + 1
    deadline = monotonic() + _TIMEOUT
    def remaining():
        budget = deadline - monotonic()
        if budget <= 0:
            raise TimeoutError('Status deadline exceeded')
        return budget
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(remaining())
        sock.connect((str(address), port))  # Connected UDP accepts only this peer.
        sock.settimeout(remaining())
        sock.send(_request(request_id, community, oid))
        sock.settimeout(remaining())
        packet = sock.recv(4097)
    return _response(packet, request_id, community, oid)


def _probe(ip, community, port=161):
    return parse_status(_probe_value(ip, community, port))


def print_snapshot(printer):
    """Uncached independent GETs; unsupported counter never hides paper errors.

    At most two .5s probes. No secrets or raw SNMP values leave this module.
    """
    result = {'status': _unknown(), 'counter': None}
    if printer.model not in _MODELS or not printer.snmp_enabled:
        return result
    community = (printer.snmp_community if printer.snmp_community is not None
                 else os.getenv('BROTHER_SNMP_COMMUNITY', 'public')).encode('utf-8')
    if not community or len(community) > 128:
        return result
    try:
        result['status'] = _probe(printer.ip, community, printer.snmp_port)
    except (OSError, ValueError, OverflowError):
        pass
    try:
        result['counter'] = _probe_value(printer.ip, community, printer.snmp_port, _COUNTER_OID)
    except (OSError, ValueError, OverflowError):
        pass
    return result


def device_status(printer_id, ip, model, *, enabled=True, port=161, community_override=None):
    if model not in _MODELS:
        return None
    if not enabled:
        return _unknown()
    community = (community_override if community_override is not None else os.getenv('BROTHER_SNMP_COMMUNITY', 'public')).encode('utf-8')
    if not community or len(community) > 128:
        return _unknown()
    key = (printer_id, ip, model, port, community)
    with _lock:
        cached = _cache.get(key)
        if cached is not None and monotonic() - cached[0] < _CACHE_TTL:
            _cache.move_to_end(key)
            return dict(cached[1])
        if key in _inflight:
            return _unknown()
        _inflight.add(key)
    result = _unknown()
    try:
        result = _probe(ip, community) if port == 161 else _probe(ip, community, port)
    except (OSError, ValueError, OverflowError):
        pass  # Disabled/blocked SNMP is unknown, never a fabricated ready state.
    finally:
        with _lock:
            _inflight.discard(key)
            _cache[key] = (monotonic(), result)
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_LIMIT:
                _cache.popitem(last=False)
    return dict(result)


from dataclasses import dataclass, field


@dataclass(frozen=True)
class DeviceStatusConfig:
    printer_id: int
    ip: str
    model: str
    enabled: bool = True
    port: int = 161
    community: str | None = field(default=None, repr=False)

    @classmethod
    def from_printer(cls, printer):
        return cls(printer.id, printer.ip, printer.model, printer.snmp_enabled,
                   printer.snmp_port, printer.snmp_community)


def device_statuses(printers):
    """Detached authorized profiles only; <=4s socket budget (32 / 4 * .5s)."""
    profiles = [p if isinstance(p, DeviceStatusConfig) else DeviceStatusConfig(*p) for p in printers]
    statuses = {p.printer_id: None for p in profiles}
    candidates = sorted(profiles, key=lambda p: p.printer_id)[:_REQUEST_LIMIT]
    def probe(p):
        return device_status(p.printer_id, p.ip, p.model, enabled=p.enabled,
                             port=p.port, community_override=p.community)
    if candidates:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = executor.map(probe, candidates)
            statuses.update((p.printer_id, result) for p, result in zip(candidates, results))
    return statuses
