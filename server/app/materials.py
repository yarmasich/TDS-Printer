"""Read-only stock catalog. Dimensions are physical millimetres, not printer dots."""
import json
import math
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel


class Material(BaseModel):
    sku: str
    printer_type: str
    cut_type: str
    rows: int
    columns: int
    page_width_mm: float
    page_height_mm: float
    left_margin_mm: float
    top_margin_mm: float
    print_width_mm: float
    print_height_mm: float
    column_pitch_mm: float
    pitch_mm: float
    gap_mm: float
    supported: bool = False
    limitation: str = ''


def _geometry(m: Material) -> dict:
    px = lambda mm: mm * 300 / 25.4
    return dict(
        material_sku=m.sku,
        bytes_per_row=math.ceil(round(px(m.page_width_mm), 8) / 8),
        height=round(px(m.page_height_mm)),
        left_left=px(m.left_margin_mm), left_right=px(m.left_margin_mm+m.print_width_mm),
        right_left=px(m.left_margin_mm+m.column_pitch_mm),
        right_right=px(m.left_margin_mm+m.column_pitch_mm+m.print_width_mm),
        left_top=px(m.top_margin_mm), right_top=px(m.top_margin_mm),
        left_bottom=px(m.top_margin_mm+m.print_height_mm),
        right_bottom=px(m.top_margin_mm+m.print_height_mm),
        gap_top=0, gap_bottom=0, gap_left=0, gap_right=0,
        media_height_mm=m.page_height_mm, media_gap_mm=m.gap_mm,
    )


@lru_cache(maxsize=1)
def catalog() -> dict[str, Material]:
    from .schemas import TemplateInput
    data=json.loads((Path(__file__).parent/'data/materials.json').read_text())
    result={}
    for item in data['items']:
        m=Material(**item)
        if m.printer_type != 'Thermal' or m.cut_type != 'Die':
            m.limitation='Reference only: requires a different printer or media sensing mode.'
        elif (m.rows,m.columns) != (1,2):
            m.limitation='Reference only: this editor prints two labels in one row.'
        elif abs(m.pitch_mm-m.page_height_mm-m.gap_mm) > 0.03:
            m.limitation='Reference only: feed dimensions need verification.'
        else:
            try:
                TemplateInput(**_geometry(m))
                m.supported=True
            except ValueError:
                m.limitation='Reference only: geometry exceeds the supported canvas.'
        result[m.sku.upper()]=m
    return result


def get_material(sku: str) -> Material:
    return catalog()[sku.strip().upper()]


def search_materials(q: str, *, supported_only: bool=False, limit: int=50) -> dict:
    q=q.strip().upper()
    matches=[m for m in catalog().values() if q in m.sku.upper() and (not supported_only or m.supported)]
    matches.sort(key=lambda m:(m.sku.upper()!=q,not m.supported,m.sku))
    return {'items':matches[:max(1,min(limit,2000))], 'total':len(matches)}


def template_geometry(m: Material) -> dict:
    if not m.supported: raise ValueError(m.limitation)
    return _geometry(m)
