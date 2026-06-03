from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import Printer, Template

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=List[Template])
def list_templates(session: Session = Depends(get_session)) -> List[Template]:
    return session.exec(select(Template).order_by(Template.name)).all()


@router.get("/{template_id}", response_model=Template)
def get_template(template_id: int, session: Session = Depends(get_session)) -> Template:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    return t


@router.post("", response_model=Template)
def create_template(t: Template, session: Session = Depends(get_session)) -> Template:
    if not session.get(Printer, t.printer_id):
        raise HTTPException(400, f"Printer {t.printer_id} does not exist")
    if t.api_printer_id is not None and not session.get(Printer, t.api_printer_id):
        raise HTTPException(400, f"API printer {t.api_printer_id} does not exist")
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


@router.put("/{template_id}", response_model=Template)
def update_template(
    template_id: int, patch: Template, session: Session = Depends(get_session)
) -> Template:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    data = patch.model_dump(exclude_unset=True, exclude={"id"})
    if "printer_id" in data and not session.get(Printer, data["printer_id"]):
        raise HTTPException(400, f"Printer {data['printer_id']} does not exist")
    if data.get("api_printer_id") is not None and not session.get(Printer, data["api_printer_id"]):
        raise HTTPException(400, f"API printer {data['api_printer_id']} does not exist")
    for k, v in data.items():
        setattr(t, k, v)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


@router.delete("/{template_id}")
def delete_template(template_id: int, session: Session = Depends(get_session)) -> dict:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    session.delete(t)
    session.commit()
    return {"deleted": template_id}
