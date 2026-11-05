"""Explicit QL-1110NWBc adapter. SENT means transport success, not physical output."""
import socket
import time

from brother_ql.conversion import convert
from brother_ql.raster import BrotherQLRaster

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


def build_qr_job(req: QrLabelRequest, printer: Printer) -> bytes:
    require_brother(printer)
    image = render_bitmap(req)
    label, width, _ = MEDIA[req.media]
    if image.mode != '1' or image.width != width:
        raise PrintError('Invalid QR raster geometry')
    raster = _WriteOnlyRaster('QL-1110NWB')  # Explicit model alias; no fallback.
    raster.exception_on_warning = True
    try:
        return bytes(convert(raster, [image], label, rotate=0, dither=False,
                             compress=False, cut=True, dpi_600=False))
    except Exception as exc:
        raise PrintError(f'Brother raster encoding failed: {exc}') from exc


def send_brother_job(printer: Printer, payload: bytes, *, queue_timeout: float = 30,
                     drain_timeout: float = 2) -> None:
    require_brother(printer)
    if not payload:
        raise PrintError('Empty Brother print job')
    started = False
    try:
        with printer_slot(printer.ip, printer.port, wait_timeout=queue_timeout):
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
    except (OSError, ImportError, PrinterBusy) as exc:
        outcome = 'Outcome unknown; check physical label before retrying.' if started else 'Nothing sent.'
        raise PrintError(f'Brother transport: {exc}. {outcome}', uncertain=started) from exc
