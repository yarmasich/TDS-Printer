"""Dedicated contract for ACT-supplied, one-bit Inventory packing labels."""
import base64
import binascii
import hashlib
import json

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from .printer import PrintError
from .qr_labels import MEDIA, QrLabelRequest

PACKING_WIDTH = MEDIA['DK-2246'][1]
PACKING_ROW_BYTES = PACKING_WIDTH // 8
MAX_PACKING_LENGTH_MM = 1000
MAX_PACKING_SCAN_BYTES = 2000
MAX_BITMAP_BASE64 = 4 * ((PACKING_ROW_BYTES * round(MAX_PACKING_LENGTH_MM * 300 / 25.4) + 2) // 3)


class PackingBitmapRequest(BaseModel):
    # Do not inherit QrLabelRequest: its unconditional 512-byte validator must
    # remain exclusive to the general and Preparation label paths.
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    printer_id: int = Field(gt=0)
    media: Literal['DK-2246']
    length_mm: float = Field(ge=30, le=MAX_PACKING_LENGTH_MM, allow_inf_nan=False)
    scan: str = Field(min_length=1, max_length=MAX_PACKING_SCAN_BYTES)
    code: str = Field(default='', max_length=80)
    description: Literal[''] = ''
    reference: str = Field(max_length=200, pattern=r'^inventory-packing:(box|pallet):[^:]+$')
    bitmap_1bpp_base64: str = Field(max_length=MAX_BITMAP_BASE64, repr=False)
    layout: None = None

    @field_validator('scan', 'code', 'reference')
    @classmethod
    def printable_text(cls, value):
        return QrLabelRequest.printable_text(value)

    @field_validator('scan')
    @classmethod
    def scan_bytes(cls, value):
        if len(value.encode('utf-8')) > MAX_PACKING_SCAN_BYTES:
            raise ValueError('Packing QR payload must fit within 2000 UTF-8 bytes')
        return value


def packing_bitmap(req: PackingBitmapRequest):
    height = round(req.length_mm * 300 / 25.4)
    expected_bytes = height * PACKING_ROW_BYTES
    encoded = req.bitmap_1bpp_base64
    if len(encoded) != 4 * ((expected_bytes + 2) // 3):
        raise PrintError('Bitmap length does not match the label')
    try:
        pixels = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PrintError('Invalid packing bitmap encoding') from exc
    if len(pixels) != expected_bytes:
        raise PrintError('Bitmap length does not match the label')
    image = Image.frombytes('1', (PACKING_WIDTH, height), pixels)
    context = ['inventory-packing-bitmap-1', req.printer_id, req.media, req.reference,
               req.scan, image.width, image.height]
    header = json.dumps(context, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    digest = hashlib.sha256(header + b'\n' + pixels).hexdigest()
    return image, digest
