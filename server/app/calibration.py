"""Physical corrections: positive X moves right, positive Y moves down the feed raster.

Calibration belongs to the actual printer + SKU, never to a shared template.
Translation occurs after the Turn-Tell orientation transform. No ink may be lost.
"""
from io import BytesIO
from PIL import Image, ImageOps
from .models import Printer
from .printer import PrintError, render_label_png
from .schemas import MaterialCalibration, PrinterInput


def apply_calibration(bitmap, template, printer: Printer, *, dpi: int):
    raw = printer.material_calibrations.get(template.material_sku.strip().upper())
    if not raw or not template.material_sku:
        return bitmap
    try:
        correction = MaterialCalibration.model_validate(raw)
    except ValueError as exc:
        raise PrintError('Invalid calibration; update the printer/material profile') from exc
    dx = round(correction.x_mm * dpi / 25.4)
    dy = round(correction.y_mm * dpi / 25.4)
    if not dx and not dy:
        return bitmap
    if printer.protocol != 'jscript' or printer.model == 'custom':
        raise PrintError('Calibration requires a Panduit model profile')
    ink = ImageOps.invert(bitmap).getbbox()
    if ink and (ink[0]+dx < 0 or ink[1]+dy < 0 or ink[2]+dx > bitmap.width or ink[3]+dy > bitmap.height):
        raise PrintError('Calibration moves text outside the raster; reduce the correction before printing')
    shifted = Image.new('L', bitmap.size, 255)
    shifted.paste(bitmap, (dx,dy))
    return shifted


def render_preview_png(template, left, right, *, printer=None, crop=False):
    # Full carrier must be retained when a physical correction is present;
    # cropping would change the coordinate origin and hide clipping.
    if printer:
        try:
            settings = PrinterInput.model_validate(printer, from_attributes=True)
            printer = Printer(**{**printer.model_dump(), **settings.model_dump()})
        except ValueError as exc:
            raise PrintError(f'Invalid printer settings: {exc}') from exc
    calibrated = bool(printer and printer.material_calibrations.get(template.material_sku.strip().upper()))
    png = render_label_png(template, left, right, crop=crop and not calibrated)
    if not calibrated:
        return png
    bitmap = Image.open(BytesIO(png)).convert('L')
    shifted = apply_calibration(bitmap, template, printer, dpi=300)
    # Match physical bounds enforced by the JScript job at native resolution.
    from .printer_profiles import PROFILES
    profile = PROFILES.get(printer.model)
    ink = ImageOps.invert(shifted).getbbox()
    if profile and ink and ink[2] > profile[1] * 300 / profile[0]:
        raise PrintError('Calibration moves text outside the printable width; reduce the correction')
    if template.media_height_mm > 0 and ink and ink[3] > round(template.media_height_mm * 300 / 25.4):
        raise PrintError('Calibration moves text outside the material height; reduce the correction')
    buf=BytesIO(); shifted.save(buf,format='PNG')
    return buf.getvalue()
