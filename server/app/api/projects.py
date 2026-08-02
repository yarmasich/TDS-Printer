"""Project / DataHall / Discipline tree CRUD."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from ..auth_admin import require_admin
from ..db import get_session
from ..models import DataHall, Discipline, Label, Printer, Project, Template

router = APIRouter(prefix="/api", tags=["projects"])


# ─────────── Project ───────────

class ProjectIn(BaseModel):
    name: str


@router.get("/projects", response_model=List[Project])
def list_projects(session: Session = Depends(get_session)) -> List[Project]:
    return session.exec(select(Project).order_by(Project.name)).all()


@router.post("/projects", response_model=Project, dependencies=[Depends(require_admin)])
def create_project(body: ProjectIn, session: Session = Depends(get_session)) -> Project:
    p = Project(name=body.name.strip())
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


@router.delete("/projects/{project_id}", dependencies=[Depends(require_admin)])
def delete_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    # cascade by hand: halls → disciplines → labels
    halls = session.exec(select(DataHall).where(DataHall.project_id == project_id)).all()
    for h in halls:
        _delete_hall(session, h)
    session.delete(p)
    session.commit()
    return {"deleted": project_id}


# ─────────── DataHall ───────────

class HallIn(BaseModel):
    project_id: int
    name: str


@router.get("/halls", response_model=List[DataHall])
def list_halls(
    project_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> List[DataHall]:
    stmt = select(DataHall)
    if project_id is not None:
        stmt = stmt.where(DataHall.project_id == project_id)
    return session.exec(stmt.order_by(DataHall.name)).all()


@router.post("/halls", response_model=DataHall, dependencies=[Depends(require_admin)])
def create_hall(body: HallIn, session: Session = Depends(get_session)) -> DataHall:
    if not session.get(Project, body.project_id):
        raise HTTPException(404, "Project not found")
    h = DataHall(project_id=body.project_id, name=body.name.strip())
    session.add(h)
    session.commit()
    session.refresh(h)
    return h


@router.delete("/halls/{hall_id}", dependencies=[Depends(require_admin)])
def delete_hall(hall_id: int, session: Session = Depends(get_session)) -> dict:
    h = session.get(DataHall, hall_id)
    if not h:
        raise HTTPException(404, "Data hall not found")
    _delete_hall(session, h)
    session.commit()
    return {"deleted": hall_id}


def _delete_hall(session: Session, h: DataHall) -> None:
    discs = session.exec(select(Discipline).where(Discipline.data_hall_id == h.id)).all()
    for d in discs:
        _delete_discipline(session, d)
    session.delete(h)


# ─────────── Discipline ───────────

class DisciplineIn(BaseModel):
    data_hall_id: int
    name: str
    template_id: Optional[int] = None
    color: str = "FFFFFF"
    bundle_mode: bool = False


class DisciplinePatch(BaseModel):
    name: Optional[str] = None
    template_id: Optional[int] = None
    color: Optional[str] = None
    bundle_mode: Optional[bool] = None


class DisciplineDTO(BaseModel):
    id: int
    data_hall_id: int
    data_hall_name: str = ""
    name: str
    template_id: Optional[int]
    template_name: Optional[str] = None
    printer_id: Optional[int] = None
    printer_name: Optional[str] = None
    color: str
    label_count: int
    bundle_mode: bool = False


@router.get("/disciplines", response_model=List[DisciplineDTO])
def list_disciplines(
    data_hall_id: Optional[int] = None,
    project_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> List[DisciplineDTO]:
    stmt = select(Discipline)
    if data_hall_id is not None:
        stmt = stmt.where(Discipline.data_hall_id == data_hall_id)
    elif project_id is not None:
        hall_ids = [h.id for h in session.exec(
            select(DataHall).where(DataHall.project_id == project_id)
        ).all()]
        if not hall_ids:
            return []
        stmt = stmt.where(Discipline.data_hall_id.in_(hall_ids))
    rows = session.exec(stmt).all()
    # Preload hall names so same-named disciplines in different halls are
    # distinguishable (e.g. "DH23 / AS-T1" vs "DH26 / AS-T1" in the import UI).
    hall_ids = {d.data_hall_id for d in rows}
    halls = {
        h.id: h.name
        for h in session.exec(select(DataHall).where(DataHall.id.in_(hall_ids))).all()
    } if hall_ids else {}
    out = []
    for d in rows:
        n = session.exec(
            select(func.count()).select_from(Label).where(Label.discipline_id == d.id)
        ).one()
        tmpl = session.get(Template, d.template_id) if d.template_id else None
        printer = session.get(Printer, tmpl.printer_id) if tmpl else None
        out.append(DisciplineDTO(
            id=d.id, data_hall_id=d.data_hall_id,
            data_hall_name=halls.get(d.data_hall_id, ""), name=d.name,
            template_id=d.template_id,
            template_name=tmpl.name if tmpl else None,
            printer_id=printer.id if printer else None,
            printer_name=printer.name if printer else None,
            color=d.color, label_count=n, bundle_mode=d.bundle_mode,
        ))
    # Group by hall, then by discipline name — keeps the two halls' identical
    # names apart in the dropdown instead of interleaving them.
    out.sort(key=lambda x: (x.data_hall_name, x.name))
    return out


@router.post("/disciplines", response_model=Discipline, dependencies=[Depends(require_admin)])
def create_discipline(
    body: DisciplineIn, session: Session = Depends(get_session)
) -> Discipline:
    if not session.get(DataHall, body.data_hall_id):
        raise HTTPException(404, "Data hall not found")
    d = Discipline(
        data_hall_id=body.data_hall_id,
        name=body.name.strip(),
        template_id=body.template_id,
        color=body.color,
        bundle_mode=body.bundle_mode,
    )
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


@router.put("/disciplines/{discipline_id}", response_model=Discipline, dependencies=[Depends(require_admin)])
def update_discipline(
    discipline_id: int, patch: DisciplinePatch, session: Session = Depends(get_session)
) -> Discipline:
    d = session.get(Discipline, discipline_id)
    if not d:
        raise HTTPException(404, "Discipline not found")
    for k, v in patch.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


@router.delete("/disciplines/{discipline_id}", dependencies=[Depends(require_admin)])
def delete_discipline(
    discipline_id: int, session: Session = Depends(get_session)
) -> dict:
    d = session.get(Discipline, discipline_id)
    if not d:
        raise HTTPException(404, "Discipline not found")
    _delete_discipline(session, d)
    session.commit()
    return {"deleted": discipline_id}


def _delete_discipline(session: Session, d: Discipline) -> None:
    for lbl in session.exec(select(Label).where(Label.discipline_id == d.id)).all():
        session.delete(lbl)
    session.delete(d)
