"""Bounded QR label layout shared by PNG preview and Brother raster output."""
import io
from pathlib import Path
from typing import Literal
import unicodedata

import qrcode
from qrcode.util import QRData, MODE_8BIT_BYTE
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .printer import PrintError

# Product width and firmware media width are different for DK-2246.
# Pinned brother_ql-inventree 1.3: label 103 -> media width 104, 1200 dots.
MEDIA = {'DK-2246': ('103', 1200, 104), 'DK-2205': ('62', 696, 62)}


class QrLabelRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    printer_id: int = Field(gt=0)
    media: Literal['DK-2246', 'DK-2205'] = 'DK-2246'
    length_mm: float = Field(default=60, ge=30, le=200, allow_inf_nan=False)
    scan: str = Field(min_length=1, max_length=512)
    code: str = Field(default='', max_length=80)
    description: str = Field(default='', max_length=240)
    reference: str = Field(default='', max_length=200)

    @field_validator('scan', 'code', 'description', 'reference')
    @classmethod
    def printable_text(cls, value):
        # Preserve exact payload, including leading/trailing spaces. No normalization.
        if any(unicodedata.category(c) in ('Cc', 'Cs') for c in value):
            raise ValueError('Control characters and invalid Unicode are not supported')
        return value

    @field_validator('scan')
    @classmethod
    def scan_bytes(cls, value):
        if len(value.encode('utf-8')) > 512:
            raise ValueError('QR payload must fit within 512 UTF-8 bytes')
        return value


def render_bitmap(req: QrLabelRequest) -> Image.Image:
    if req.media == 'DK-2205':
        req = req.model_copy(update={'code': ' '.join(req.code.split()),
                                    'description': ' '.join(req.description.split())})
        if req.code or req.description:
            return render_captioned_62(req)
    width = MEDIA[req.media][1]
    height = round(req.length_mm * 300 / 25.4)
    margin, gap = 24, 16
    font_root = Path(__file__).parent / 'fonts'
    code_font = ImageFont.truetype(str(font_root / 'Carlito-Bold.ttf'), 40)
    desc_font = ImageFont.truetype(str(font_root / 'Carlito-Regular.ttf'), 30)
    image = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(image)
    lines = []
    if req.code:
        lines.append((req.code, code_font, 48))
    if req.description:
        current = ''
        # Wrap at characters as well as spaces: never silently drop long identifiers.
        for char in req.description:
            candidate = current + char
            if draw.textlength(candidate, font=desc_font) > width - margin * 2:
                if not current:
                    raise PrintError('Description cannot fit this label')
                lines.append((current, desc_font, 38))
                current = char
            else:
                current = candidate
        if current:
            lines.append((current, desc_font, 38))
    for text, font, _ in lines:
        if draw.textlength(text, font=font) > width - margin * 2:
            raise PrintError('Caption cannot fit this label; shorten it or select wider media')
    text_height = sum(line[2] for line in lines)
    available = min(width - margin * 2, height - margin * 2 - text_height - (gap if lines else 0))
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(QRData(req.scan.encode('utf-8'), mode=MODE_8BIT_BYTE), optimize=0)
    qr.make(fit=True)
    modules = len(qr.get_matrix())
    scale = available // modules
    if scale < 4:
        raise PrintError('QR cannot fit at the minimum module size; increase label length or reduce payload')
    qr.box_size = scale
    qr_image = qr.make_image(fill_color='black', back_color='white').get_image().convert('1')
    total = qr_image.height + text_height + (gap if lines else 0)
    top = (height - total) // 2
    image.paste(qr_image, ((width - qr_image.width) // 2, top))
    y = top + qr_image.height + (gap if lines else 0)
    for text, font, line_height in lines:
        draw.text((width // 2, y), text, font=font, fill=0, anchor='mt')
        y += line_height
    return image


def wrap_caption(text, font, draw, max_width):
    """Word wrapping with a character fallback; never discard identifier text."""
    lines = []
    current = ''
    for word in text.split():
        candidate = f'{current} {word}' if current else word
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ''
        for char in word:
            candidate = current + char
            if draw.textlength(candidate, font=font) > max_width:
                if not current:
                    raise PrintError('Caption cannot fit this label')
                lines.append(current)
                current = char
            else:
                current = candidate
    if current:
        lines.append(current)
    return lines


def render_captioned_62(req: QrLabelRequest) -> Image.Image:
    width = MEDIA[req.media][1]
    height = round(req.length_mm * 300 / 25.4)
    margin, gap = 20, 8
    image = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(image)
    fonts = Path(__file__).parent / 'fonts'
    code_font = ImageFont.truetype(str(fonts / 'Carlito-Bold.ttf'), 96)
    desc_font = ImageFont.truetype(str(fonts / 'Carlito-Regular.ttf'), 72)
    printable = width - 2 * margin
    codes = wrap_caption(req.code, code_font, draw, printable)
    descriptions = wrap_caption(req.description, desc_font, draw, printable)
    code_pitch = sum(code_font.getmetrics()) + 4
    desc_pitch = sum(desc_font.getmetrics()) + 4
    text_height = len(codes) * code_pitch + len(descriptions) * desc_pitch
    gaps = gap * (bool(codes) + bool(descriptions))
    available_height = height - 2 * margin - text_height - gaps
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(QRData(req.scan.encode('utf-8'), mode=MODE_8BIT_BYTE), optimize=0)
    qr.make(fit=True)
    modules = len(qr.get_matrix())
    # Cap includes the four-module quiet zone. Dense payloads may exceed the cap,
    # but never the printable area, to preserve the four-dot module minimum.
    scale = min(int(printable * .65), available_height) // modules
    if scale < 4:
        if 4 * modules > min(printable, available_height):
            raise PrintError('QR and captions cannot fit; increase label length or shorten captions')
        scale = 4
    qr.box_size = scale
    qr_image = qr.make_image(fill_color='black', back_color='white').get_image().convert('1')
    y = (height - text_height - gaps - qr_image.height) // 2
    for line in codes:
        draw.text((width // 2, y), line, font=code_font, fill=0, anchor='mt')
        y += code_pitch
    if codes:
        y += gap
    image.paste(qr_image, ((width - qr_image.width) // 2, y))
    y += qr_image.height + (gap if descriptions else 0)
    for line in descriptions:
        draw.text((width // 2, y), line, font=desc_font, fill=0, anchor='mt')
        y += desc_pitch
    return image


def preview_png(req: QrLabelRequest) -> bytes:
    output = io.BytesIO()
    render_bitmap(req).save(output, format='PNG')
    return output.getvalue()
