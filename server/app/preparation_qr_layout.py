"""Freeform Preparation labels, in millimetres from the printable top-left."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Union

import qrcode
from PIL import Image, ImageDraw, ImageFont
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_serializer, model_validator
from qrcode.util import MODE_8BIT_BYTE, QRData

from .printer import PrintError
from .qr_labels import MEDIA, QrLabelRequest

APP = Path(__file__).parent
MAX_LAYOUT_BYTES = 16 * 1024


def tenth_mm(value: float) -> float:
    if Decimal(str(value)) % Decimal('0.1'):
        raise ValueError('Positions and sizes must use a 0.1 mm grid')
    return value


Millimetres = Annotated[float, Field(strict=True, allow_inf_nan=False), AfterValidator(tenth_mm)]


class PositionedElement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    x_mm: Millimetres = Field(ge=0, le=58.9)
    y_mm: Millimetres = Field(ge=0, le=200)


class QrElement(PositionedElement):
    kind: Literal['qr']
    size_mm: Millimetres = Field(ge=8, le=55)


class TextElement(PositionedElement):
    kind: Literal['text']
    width_mm: Millimetres = Field(ge=4, le=58.9)
    font_mm: Millimetres = Field(ge=2, le=12)
    text: str = Field(min_length=1, max_length=200)
    align: Literal['left', 'center', 'right'] = 'left'

    @model_serializer(mode='wrap')
    def serialize_alignment(self, handler):
        fields = handler(self)
        if self.align == 'left':
            fields.pop('align', None)
        return fields


class PreparationLayout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1, 2]
    elements: list[Annotated[Union[QrElement, TextElement], Field(discriminator='kind')]] = Field(min_length=2, max_length=13)

    @model_validator(mode='after')
    def validate_elements(self):
        if sum(isinstance(el, QrElement) for el in self.elements) != 1:
            raise ValueError('Provide one QR and 1 to 12 text fields')
        if self.version == 1 and any(isinstance(el, TextElement) and el.align != 'left' for el in self.elements):
            raise ValueError('Centered and right-aligned fields require layout version 2')
        if len(self.model_dump_json().encode('utf-8')) > MAX_LAYOUT_BYTES:
            raise ValueError('Resolved layout exceeds 16 KiB')
        return self


class LayoutError(PrintError):
    """A safe, bounded explanation for the operator; contains no request text."""


@lru_cache(maxsize=1)
def font_codepoints() -> frozenset[int]:
    # The ranges are generated from the bundled font's best Unicode cmap. Its
    # SHA-256 is checked in tests so replacing the font requires updating them.
    metadata = json.loads((APP / 'data/carlito-coverage.json').read_text())
    points = set()
    for pair in metadata['ranges']:
        first, last = (int(value, 16) for value in pair.split('-'))
        points.update(range(first, last + 1))
    return frozenset(points)


def dots(mm: float) -> int:
    return round(mm * 300 / 25.4)


def qr_image(scan: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=1)
    qr.add_data(QRData(scan.encode('utf-8'), mode=MODE_8BIT_BYTE), optimize=0)
    qr.make(fit=True)
    qr.box_size = size // len(qr.get_matrix())
    if qr.box_size < 4:
        raise LayoutError('Increase the QR size so the code can be scanned.')
    return qr.make_image(fill_color='black', back_color='white').get_image().convert('1')


def check_box(box, occupied, width, height):
    left, top, right, bottom = box
    if left < 0 or top < 0 or right > width or bottom > height:
        raise LayoutError('Move the object inside the printable label or increase the cut length.')
    for x1, y1, x2, y2 in occupied:
        if left < x2 and x1 < right and top < y2 and y1 < bottom:
            raise LayoutError('Separate overlapping fields and leave the QR area clear.')
    occupied.append(box)


def render_preparation_layout(req: QrLabelRequest, layout: PreparationLayout):
    if req.media != 'DK-2205' or not re.fullmatch(r'preparation:[^:]+', req.reference):
        raise LayoutError('Use a Preparation cable and 62 mm DK-2205 media for this layout.')
    width, height = MEDIA[req.media][1], dots(req.length_mm)
    image = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(image)
    occupied = []
    for el in layout.elements:
        x, y = dots(el.x_mm), dots(el.y_mm)
        if isinstance(el, QrElement):
            if round(el.x_mm + el.size_mm, 1) > 58.9 or round(el.y_mm + el.size_mm, 1) > req.length_mm:
                raise LayoutError('Move the QR inside the printable label or increase the cut length.')
            size = dots(el.size_mm)
            check_box((x, y, x + size, y + size), occupied, width, height)
            qr = qr_image(req.scan, size)
            gap = (size - qr.width) // 2
            image.paste(qr, (x + gap, y + gap))
            continue
        if any(unicodedata.category(ch).startswith('C') or ch in '\u2028\u2029' for ch in el.text):
            raise LayoutError('Use a single line of printable characters for each field.')
        if not el.text.strip() or any(ord(ch) not in font_codepoints() for ch in el.text):
            raise LayoutError('A field is empty or contains characters the label font cannot print.')
        font = ImageFont.truetype(str(APP / 'fonts/Carlito-Regular.ttf'), dots(el.font_mm))
        left, top, right, bottom = draw.textbbox((0, 0), el.text, font=font, anchor='lt')
        if right - left > dots(el.width_mm):
            raise LayoutError('Widen the field or decrease its font size to fit the entire value.')
        if round(el.x_mm + el.width_mm, 1) > 58.9 or x + dots(el.width_mm) > width:
            raise LayoutError('Move the field or reduce its width to fit the printable label.')
        spare = dots(el.width_mm) - (right - left)
        offset = {'left': 0, 'center': spare // 2, 'right': spare}[el.align]
        x += offset
        check_box((x, y, x + right - left, y + bottom - top), occupied, width, height)
        draw.text((x - left, y - top), el.text, font=font, fill=0, anchor='lt')
    context = ['preparation-layout-1', req.model_dump(mode='json'), layout.model_dump(mode='json'),
               image.mode, width, height]
    header = json.dumps(context, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('ascii')
    return image, hashlib.sha256(header + b'\n' + image.tobytes()).hexdigest()
