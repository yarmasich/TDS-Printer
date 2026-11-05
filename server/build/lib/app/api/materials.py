from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from ..materials import Material, get_material, search_materials, template_geometry

router=APIRouter(prefix='/api/materials',tags=['materials'])


class MaterialSearch(BaseModel):
    items: list[Material]
    total: int


@router.get('',response_model=MaterialSearch)
def search(q: str=Query('',max_length=100),supported_only: bool=False,limit: int=Query(50,ge=1,le=100)):
    return search_materials(q,supported_only=supported_only,limit=limit)


@router.get('/{sku}')
def detail(sku: str):
    try: m=get_material(sku)
    except KeyError: raise HTTPException(404,'Material SKU not found')
    return {'material':m,'geometry':template_geometry(m) if m.supported else None}
