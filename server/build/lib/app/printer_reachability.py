"""Opt-in TCP reachability only; never sends printer commands or label bytes."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import socket
from threading import Lock
from time import monotonic

from .printer_dispatch import PrinterBusy, printer_slot

_CACHE_TTL = 15.0
_CACHE_LIMIT = 1024
_REQUEST_LIMIT = 32
_cache: OrderedDict[tuple[int, str, int], tuple[float, bool | None]] = OrderedDict()
_inflight: set[tuple[int, str, int]] = set()
_lock = Lock()


def printer_status(printer_id: int, ip: str, port: int) -> bool | None:
    key = (printer_id, ip, port)
    with _lock:
        cached = _cache.get(key)
        if cached is not None and monotonic() - cached[0] < _CACHE_TTL:
            _cache.move_to_end(key)
            return cached[1]
        if key in _inflight:
            return None
        _inflight.add(key)
    status = None
    try:
        # A print already holding the slot wins immediately. A subsequent print
        # has its existing 30s queue budget to wait for this <=1s connection.
        with printer_slot(ip, port, wait_timeout=0):
            try:
                with socket.create_connection((ip, port), timeout=1.0):
                    pass
                status = True
            except OSError:
                status = False
    except PrinterBusy:
        status = None
    except Exception:
        # Unexpected failures must not misrepresent a printer as offline.
        status = None
    finally:
        with _lock:
            _inflight.discard(key)
            _cache[key] = (monotonic(), status)
            _cache.move_to_end(key)
            while len(_cache) > _CACHE_LIMIT:
                _cache.popitem(last=False)
    return status


def printer_statuses(printers: list[tuple[int, str, int]]) -> dict[int, bool | None]:
    """Accept detached authorized assigned printer addresses, with bounded request work."""
    statuses = {pid: None for pid, _, _ in printers}
    candidates = sorted(printers, key=lambda printer: printer[0])[:_REQUEST_LIMIT]
    if candidates:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = executor.map(lambda args: printer_status(*args), candidates)
            statuses.update((printer[0], status) for printer, status in zip(candidates, results))
    return statuses
