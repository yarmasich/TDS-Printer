"""Explicit QL-1110NWBc adapter. SENT means transport success, not physical output."""
import socket
import time

from PIL import Image
from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

from . import printer_device_status
from .models import Printer
from .printer import PrintError
from .printer_dispatch import PrinterBusy, printer_slot
from .qr_labels import MEDIA, QrLabelRequest, render_bitmap


def require_brother(printer: Printer) -> None:
    if printer.protocol != 'brother_ql' or printer.model != 'QL-1110NWBc' or printer.dpi != 300:
        raise PrintError('QR labels require a Brother QL-1110NWBc profile at 300 dpi')


class _WriteOnlyRaster(BrotherQLRaster):
    def add_status_information(self):
        # This transport does not interpret replies. Never request status.
        pass

    def add_initialize(self):
        super().add_initialize()
        self._notification_pending = True

    def add_switch_mode(self):
        super().add_switch_mode()
        # Brother Raster Command Reference: ESC i ! 01 = do not notify.
        # convert switches mode before AND after init; only the latter is valid here.
        if getattr(self, '_notification_pending', False):
            self.data += b'\x1b\x69\x21\x01'
            self._notification_pending = False


def build_qr_job(req: QrLabelRequest, printer: Printer, *, image: Image.Image | None = None) -> bytes:
    require_brother(printer)
    if image is None:
        image = render_bitmap(req)
    elif image.height != round(req.length_mm * 300 / 25.4):
        raise PrintError('Invalid packing bitmap height')
    label, width, _ = MEDIA[req.media]
    if image.mode != '1' or image.width != width:
        raise PrintError('Invalid QR raster geometry')
    raster = _WriteOnlyRaster('QL-1110NWB')  # Explicit model alias; no fallback.
    raster.exception_on_warning = True
    try:
        return bytes(convert(raster, [image], label, rotate=0, dither=False,
                             compress=False, cut=True, dpi_600=False,
                             # Both supported continuous rolls use speed priority at 300 dpi.
                             hq=False))
    except Exception as exc:
        raise PrintError(f'Brother raster encoding failed: {exc}') from exc


class PrinterNotReady(PrintError):
    """Known preflight failure: no print bytes were sent."""


def _media_matches(status, media):
    # Only 62mm has been validated against physical hardware for observation.
    return (media == 'DK-2205' and status['state'] == 'ready'
            and status['media_width_mm'] == 62 and status['media_type'] == 'continuous')


def _preflight(printer, media):
    try:
        sample = printer_device_status.print_snapshot(printer)
    except Exception as exc:
        raise PrinterNotReady('Could not check printer. Nothing was sent.') from exc
    status = sample['status']
    wrong_width = (status['media_width_mm'] is not None and
                   ((media == 'DK-2205' and status['media_width_mm'] != 62) or
                    (media == 'DK-2246' and status['media_width_mm'] == 62)))
    if status['state'] in {'no_media', 'cover_open', 'error', 'busy'} or status['media_type'] == 'die_cut' or wrong_width:
        raise PrinterNotReady('Printer not ready. Check paper, cover and selected roll. Nothing was sent.')
    return sample


def _observe(printer, media, baseline):
    # Global counter only: external clients and late jobs cannot be attributed.
    # Never changes transport success into failure, never retries print bytes.
    try:
        if baseline['counter'] is None or not _media_matches(baseline['status'], media):
            return 'unconfirmed'
        deadline = time.monotonic() + 8
        changed_at = None
        while time.monotonic() < deadline:
            sample = printer_device_status.print_snapshot(printer)
            now = time.monotonic()
            if now > deadline or sample['counter'] is None:
                return 'unconfirmed'
            delta = sample['counter'] - baseline['counter']
            if delta not in (0, 1) or sample['status']['state'] in {'no_media', 'cover_open', 'error'}:
                return 'unconfirmed'
            if delta == 1:
                if changed_at is None:
                    changed_at = now
                if now - changed_at >= 1.5 and _media_matches(sample['status'], media):
                    return 'counter_advanced'
            elif changed_at is not None:
                return 'unconfirmed'
            time.sleep(min(.5, max(0, deadline - time.monotonic())))
    except Exception:
        # Telemetry must not invalidate successful TCP delivery or leak secrets.
        pass
    return 'unconfirmed'


def send_brother_job(printer: Printer, payload: bytes, *, queue_timeout: float = 30,
                     drain_timeout: float = 2, media: str | None = None) -> str | None:
    require_brother(printer)
    if not payload:
        raise PrintError('Empty Brother print job')
    started = False
    try:
        with printer_slot(printer.ip, printer.port, wait_timeout=queue_timeout):
            baseline = _preflight(printer, media) if media is not None else None
            connection = socket.create_connection((printer.ip, printer.port), timeout=10)
            try:
                started = True  # sendall can fail after sending an unknown byte count.
                connection.sendall(payload)
                connection.shutdown(socket.SHUT_WR)
                deadline = time.monotonic() + max(0, drain_timeout)
                while (remaining := deadline - time.monotonic()) > 0:
                    connection.settimeout(min(0.2, remaining))
                    try:
                        if not connection.recv(4096):
                            break
                    except socket.timeout:
                        continue
                    # A reset after send may mean that the device aborted the job.
                    # Propagate other errors conservatively as UNCERTAIN as well.
            finally:
                connection.close()
            return _observe(printer, media, baseline) if baseline is not None else None
    except (OSError, ImportError, PrinterBusy) as exc:
        outcome = 'Outcome unknown; check physical label before retrying.' if started else 'Nothing sent.'
        raise PrintError(f'Brother transport: {exc}. {outcome}', uncertain=started) from exc
