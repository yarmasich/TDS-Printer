from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..db import get_session
from ..models import Discipline, Printer, Template
from ..schemas import TemplateCreate, TemplatePatch

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _commit(session: Session, detail: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, detail) from exc


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
def create_template(t: TemplateCreate, session: Session = Depends(get_session)) -> Template:
    if not session.get(Printer, t.printer_id):
        raise HTTPException(400, f"Printer {t.printer_id} does not exist")
    row = Template(**t.model_dump())
    session.add(row)
    _commit(session, "Template name already exists or its printer is no longer available")
    session.refresh(row)
    return row


@router.put("/{template_id}", response_model=Template)
def update_template(
    template_id: int, patch: TemplatePatch, session: Session = Depends(get_session)
) -> Template:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    try:
        updated = TemplateCreate.model_validate({**t.model_dump(), **patch.model_dump(exclude_unset=True)})
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not session.get(Printer, updated.printer_id):
        raise HTTPException(400, f"Printer {updated.printer_id} does not exist")
    for k, v in updated.model_dump().items():
        setattr(t, k, v)
    session.add(t)
    _commit(session, "Template name already exists or its printer is no longer available")
    session.refresh(t)
    return t


@router.delete("/{template_id}")
def delete_template(template_id: int, session: Session = Depends(get_session)) -> dict:
    t = session.get(Template, template_id)
    if not t:
        raise HTTPException(404, "Template not found")
    if session.exec(select(Discipline.id).where(Discipline.template_id == template_id)).first() is not None:
        raise HTTPException(409, "Template is assigned to a discipline; unassign it before deleting")
    session.delete(t)
    _commit(session, "Template is still referenced and cannot be deleted")
    return {"deleted": template_id}
