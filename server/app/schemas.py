"""Validated API inputs, separate from SQLModel table constructors.

Table models intentionally stay persistence-only: Pydantic must reject malformed
values before they reach SQLAlchemy, including on draft and partial-update paths.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model, model_validator

from .models import HAlign, VAlign

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Coordinate = Annotated[float, Field(ge=-4096, le=4096, allow_inf_nan=False)]
PointSize = Annotated[float, Field(gt=0, le=144, allow_inf_nan=False)]
MAX_DESIGN_PIXELS = 4_000_000
MAX_RENDER_PIXELS = MAX_DESIGN_PIXELS * 4  # 600 DPI is twice the 300-DPI design grid.


class InputModel(BaseModel):
    # Ignore read-only fields (notably id) in existing frontend payloads.
    model_config = ConfigDict(from_attributes=True, extra='ignore', allow_inf_nan=False)

    @model_validator(mode='before')
    @classmethod
    def serializable_nonfinite_inputs(cls, value):
        # Nonstandard JSON parsers can accept NaN/Infinity. Keep validation-error
        # inputs JSON-safe too, so FastAPI can return 422 rather than fail at 500.
        if isinstance(value, dict):
            return {
                k: str(v) if isinstance(v, float) and not math.isfinite(v) else v
                for k, v in value.items()
            }
        return value


class TemplateInput(InputModel):
    """Render configuration; a new draft can have no name/printer selected yet."""
    name: str = Field('', max_length=200)
    printer_id: int = Field(0, ge=0)
    bytes_per_row: int = Field(..., ge=1, le=512)
    height: int = Field(..., ge=1, le=4096)
    left_top: Coordinate = 0
    left_bottom: Coordinate = 0
    left_left: Coordinate = 0
    left_right: Coordinate = 0
    right_top: Coordinate = 0
    right_bottom: Coordinate = 0
    right_left: Coordinate = 0
    right_right: Coordinate = 0
    gap_top: Coordinate = 0
    gap_bottom: Coordinate = 0
    gap_left: Coordinate = 0
    gap_right: Coordinate = 0
    left_text: str = Field('TEXT+12345', max_length=4096)
    right_text: str = Field('TEXT+12345', max_length=4096)
    left_pt: PointSize = 7
    right_pt: PointSize = 7
    h_align: HAlign = HAlign.CENTER
    v_align: VAlign = VAlign.CENTER
    font_name: Literal['Microsoft Sans Serif', 'Calibri'] = 'Microsoft Sans Serif'
    font_style: Literal['Bold', 'Regular'] = 'Bold'
    left_offset: Coordinate = 0
    right_offset: Coordinate = 0
    scale_x: float = Field(1, ge=1, le=1.5, allow_inf_nan=False)
    mirror_legend: bool = False

    @model_validator(mode='after')
    def valid_geometry(self):
        if self.bytes_per_row * 8 * self.height > MAX_DESIGN_PIXELS:
            raise ValueError(f'Bitmap exceeds {MAX_DESIGN_PIXELS} pixels in the design grid')
        for side in ('left', 'right'):
            left, right, top, bottom = (
                getattr(self, f'{side}_{edge}') for edge in ('left', 'right', 'top', 'bottom')
            )
            # Legacy/minimal templates use all-zero coordinates for an unset
            # side. Keep that default usable, but reject inverted configured areas.
            if left == right == top == bottom == 0:
                continue
            if right - self.gap_right <= left + self.gap_left:
                raise ValueError(f'{side} text area must have positive width after padding')
            if bottom - self.gap_bottom <= top + self.gap_top:
                raise ValueError(f'{side} text area must have positive height after padding')
            if not (0 <= left + self.gap_left < right - self.gap_right <= self.bytes_per_row * 8):
                raise ValueError(f'{side} text area must fit within the bitmap width')
            if not (0 <= top + self.gap_top < bottom - self.gap_bottom <= self.height):
                raise ValueError(f'{side} text area must fit within the bitmap height')
        return self


class TemplateCreate(TemplateInput):
    name: Name
    printer_id: int = Field(..., ge=1)


class PrinterInput(InputModel):
    name: Name
    ip: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]
    port: int = Field(9100, ge=1, le=65535)
    notes: str = Field('', max_length=4096)
    protocol: Literal['epl2', 'jscript'] = 'epl2'
    dpi: Literal[203, 300, 600] = 300


class PatchInput(InputModel):
    @model_validator(mode='before')
    @classmethod
    def reject_explicit_null(cls, value):
        if isinstance(value, dict):
            for name in cls.model_fields:
                if name in value and value[name] is None:
                    raise ValueError(f'{name} cannot be null')
        return value


def _partial_model(name: str, full: type[BaseModel]) -> type[BaseModel]:
    """Keep field constraints in sync; cross-field checks run after merging."""
    fields = {}
    for field_name, info in full.model_fields.items():
        field = deepcopy(info)
        field.default = None
        fields[field_name] = (info.annotation | None, field)
    return create_model(name, __base__=PatchInput, **fields)


TemplatePatch = _partial_model('TemplatePatch', TemplateCreate)
PrinterPatch = _partial_model('PrinterPatch', PrinterInput)
