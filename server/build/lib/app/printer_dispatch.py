"""Bounded, process-safe transport serialization for a single application host.

This is not a persisted FIFO spooler. Callers wait up to 30 seconds before any
network I/O; a timeout is safe to retry. The OS owns the lock for the lifetime
of the open descriptor, so paused workers never lose their slot and crashed
workers never leave a stale lease. Jobs are never replayed by this module.

All workers must share TDS_PRINTER_LOCK_DIR (defaults beside the SQLite DB).
Use a local filesystem on Linux/macOS. Separate hosts and DNS aliases for the
same physical printer are outside this guarantee: configure a consistent IP.
Lock files must not be removed while workers run, even when apparently idle.
"""
from contextlib import contextmanager
from hashlib import sha256
from ipaddress import ip_address
import os
from pathlib import Path
import time


class PrinterBusy(Exception):
    """The caller has not sent any bytes; it timed out waiting for the slot."""


def endpoint_key(host: str, port: int) -> str:
    host = host.strip().lower().rstrip('.')
    try:
        host = ip_address(host).compressed
    except ValueError:
        pass
    return sha256(f'{host}:{int(port)}'.encode()).hexdigest()


def _lock_directory() -> Path:
    configured = os.environ.get('TDS_PRINTER_LOCK_DIR')
    if configured:
        return Path(configured)
    from .db import DATA_DIR, engine
    database = engine.url.database
    root = Path(database).resolve().parent if engine.dialect.name == 'sqlite' and database and database != ':memory:' else DATA_DIR
    return root / 'printer-locks'


@contextmanager
def printer_slot(host: str, port: int, *, wait_timeout: float = 30.0):
    # Imported lazily: unsupported hosts fail closed instead of sending unlocked.
    import fcntl

    directory = _lock_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (endpoint_key(host, port) + '.lock')
    deadline = time.monotonic() + max(0, wait_timeout)
    # Never unlink: another worker may already have the same inode open.
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PrinterBusy('Printer is busy. Nothing was sent; retry after the current job finishes.')
                time.sleep(min(0.05, remaining))
        yield
    finally:
        # Closing also releases flock after any body exception.
        os.close(fd)
