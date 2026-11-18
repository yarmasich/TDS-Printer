"""Project / DataHall / Discipline tree CRUD."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, delete, func, select, update

from ..auth_admin import require_admin
from ..auth_station import require_reader
from ..db import get_session
from ..importer import begin_label_mutation, delete_labels
from ..models import DataHall, Discipline, Import, Label, Printer, Project, Template

router = APIRouter(prefix="/api", tags=["projects"])


def _commit(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "Name already exists or referenced record is in use") from exc


class NamedInput(BaseModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def valid_name(cls, value):
        if value is None or not value.strip():
            raise ValueError("Name must not be empty")
        return value.strip()


# ─────────── Project ───────────

class ProjectIn(NamedInput):
    name: str


@router.get("/projects", response_model=List[Project], dependencies=[Depends(require_reader)])
def list_projects(session: Session = Depends(get_session)) -> List[Project]:
    return session.exec(select(Project).order_by(Project.name)).all()


@router.post("/projects", response_model=Project, dependencies=[Depends(require_admin)])
def create_project(body: ProjectIn, session: Session = Depends(get_session)) -> Project:
    p = Project(name=body.name.strip())
    session.add(p)
    _commit(session)
    session.refresh(p)
    return p


class ProjectPatch(BaseModel):
    require_rfid: bool


@router.patch("/projects/{project_id}", response_model=Project, dependencies=[Depends(require_admin)])
def update_project(project_id: int, body: ProjectPatch, session: Session = Depends(get_session)) -> Project:
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.require_rfid = body.require_rfid
    session.add(project)
    _commit(session)
    session.refresh(project)
    return project


@router.delete("/projects/{project_id}", dependencies=[Depends(require_admin)])
def delete_project(project_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        begin_label_mutation(session)
        p = session.get(Project, project_id)
        if not p:
            raise HTTPException(404, "Project not found")
        # cascade by hand: halls → disciplines → labels
        halls = session.exec(select(DataHall).where(DataHall.project_id == project_id)).all()
        for h in halls:
            _delete_hall(session, h)
        session.delete(p)
        _commit(session)
        return {"deleted": project_id}
    except Exception:
        session.rollback()
        raise


# ─────────── DataHall ───────────

class HallIn(NamedInput):
    project_id: int
    name: str


@router.get("/halls", response_model=List[DataHall], dependencies=[Depends(require_reader)])
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
    _commit(session)
    session.refresh(h)
    return h


@router.delete("/halls/{hall_id}", dependencies=[Depends(require_admin)])
def delete_hall(hall_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        begin_label_mutation(session)
        h = session.get(DataHall, hall_id)
        if not h:
            raise HTTPException(404, "Data hall not found")
        _delete_hall(session, h)
        _commit(session)
        return {"deleted": hall_id}
    except Exception:
        session.rollback()
        raise


def _delete_hall(session: Session, h: DataHall) -> None:
    discs = session.exec(select(Discipline).where(Discipline.data_hall_id == h.id)).all()
    for d in discs:
        _delete_discipline(session, d)
    session.delete(h)
    session.flush()


# ─────────── Discipline ───────────

class DisciplineIn(NamedInput):
    data_hall_id: int
    name: str
    template_id: Optional[int] = None
    color: str = "FFFFFF"
    bundle_mode: bool = False
    # Its role, set with it: leg labels whose trunks another discipline holds, or the trunk
    # labels of an existing leg discipline. At most one; both link in the same commit.
    trunk_discipline_id: Optional[int] = None
    trunks_for_id: Optional[int] = None

    @model_validator(mode="after")
    def one_role(self):
        if self.trunk_discipline_id is not None and self.trunks_for_id is not None:
            raise ValueError("A discipline holds leg labels or trunk labels, not both")
        return self


class DisciplinePatch(NamedInput):
    name: Optional[str] = None
    template_id: Optional[int] = None
    color: Optional[str] = None
    bundle_mode: Optional[bool] = None
    # An explicit null unlinks.
    trunk_discipline_id: Optional[int] = None

    @field_validator("color", "bundle_mode")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class DisciplineDTO(BaseModel):
    id: int
    data_hall_id: int
    data_hall_name: str = ""
    name: str
    template_id: Optional[int]
    template_name: Optional[str] = None
    printer_id: Optional[int] = None
    printer_ids: list[int] = []
    printer_name: Optional[str] = None
    color: str
    label_count: int
    bundle_mode: bool = False
    trunk_discipline_id: Optional[int] = None
    trunk_discipline_name: Optional[str] = None
    # Leg labels with no Trunk#: their trunk cannot print. Counted only for linked legs.
    missing_trunk_count: int = 0


@router.get("/disciplines", response_model=List[DisciplineDTO], dependencies=[Depends(require_reader)])
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
        missing = session.exec(
            select(func.count()).select_from(Label).where(Label.discipline_id == d.id, Label.trunk_no.is_(None))
        ).one() if d.trunk_discipline_id else 0
        tmpl = session.get(Template, d.template_id) if d.template_id else None
        printer = session.get(Printer, tmpl.printer_id) if tmpl else None
        out.append(DisciplineDTO(
            id=d.id, data_hall_id=d.data_hall_id,
            data_hall_name=halls.get(d.data_hall_id, ""), name=d.name,
            template_id=d.template_id,
            template_name=tmpl.name if tmpl else None,
            printer_id=printer.id if printer else None,
            printer_ids=(tmpl.printer_ids or [tmpl.printer_id]) if tmpl else [],
            printer_name=printer.name if printer else None,
            color=d.color, label_count=n, bundle_mode=d.bundle_mode,
            trunk_discipline_id=d.trunk_discipline_id,
            trunk_discipline_name=trunk.name if (trunk := session.get(Discipline, d.trunk_discipline_id)
                                                 if d.trunk_discipline_id else None) else None,
            missing_trunk_count=missing,
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
    if body.template_id is not None and not session.get(Template, body.template_id):
        raise HTTPException(400, "Template not found")
    d = Discipline(
        data_hall_id=body.data_hall_id,
        name=body.name.strip(),
        template_id=body.template_id,
        color=body.color,
        bundle_mode=body.bundle_mode,
    )
    session.add(d)
    try:
        if body.trunk_discipline_id is not None or body.trunks_for_id is not None:
            session.flush()  # the new id, so the link is checked by the same rules as an edit
            if body.trunk_discipline_id is not None:
                _check_trunk_link(session, d, body.trunk_discipline_id)
                d.trunk_discipline_id = body.trunk_discipline_id
            else:
                legs = session.get(Discipline, body.trunks_for_id)
                if legs is None:
                    raise HTTPException(400, "Leg discipline not found")
                if legs.trunk_discipline_id is not None:
                    # Creating must not silently move an existing link.
                    raise HTTPException(400, f"'{legs.name}' already links its trunk labels; unlink it first")
                _check_trunk_link(session, legs, d.id)
                legs.trunk_discipline_id = d.id
                session.add(legs)
        _commit(session)
    except IntegrityError as exc:  # a duplicate name surfaces at the flush
        session.rollback()
        raise HTTPException(409, "Name already exists or referenced record is in use") from exc
    except Exception:
        session.rollback()
        raise
    session.refresh(d)
    return d


@router.put("/disciplines/{discipline_id}", response_model=Discipline, dependencies=[Depends(require_admin)])
def update_discipline(
    discipline_id: int, patch: DisciplinePatch, session: Session = Depends(get_session)
) -> Discipline:
    d = session.get(Discipline, discipline_id)
    if not d:
        raise HTTPException(404, "Discipline not found")
    if patch.template_id is not None and not session.get(Template, patch.template_id):
        raise HTTPException(400, "Template not found")
    if patch.trunk_discipline_id is not None:
        _check_trunk_link(session, d, patch.trunk_discipline_id)
    for k, v in patch.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    session.add(d)
    _commit(session)
    session.refresh(d)
    return d


@router.delete("/disciplines/{discipline_id}", dependencies=[Depends(require_admin)])
def delete_discipline(
    discipline_id: int, session: Session = Depends(get_session), force: bool = False
) -> dict:
    try:
        begin_label_mutation(session)
        d = session.get(Discipline, discipline_id)
        if not d:
            raise HTTPException(404, "Discipline not found")
        try:
            _delete_discipline(session, d, force=force)
        except HTTPException as exc:
            # A blocking cart belongs to one tablet and admins cannot reach it,
            # so point at the escape hatch — only this route offers it.
            if exc.status_code == 409 and not force:
                raise HTTPException(409, f"{exc.detail} Delete again with force=true "
                                         "to clear the items that are no longer in flight.") from None
            raise
        _commit(session)
        return {"deleted": discipline_id}
    except Exception:
        session.rollback()
        raise


def _check_trunk_link(session: Session, legs: Discipline, trunk_id: int) -> None:
    """Trunks live one level deep in the same project, so "leg + trunk" has
    exactly one answer."""
    trunks = session.get(Discipline, trunk_id)
    if trunks is None:
        raise HTTPException(400, "Trunk discipline not found")
    if trunks.id == legs.id:
        raise HTTPException(400, "A discipline cannot hold its own trunk labels; pick the trunk discipline instead of itself")
    project = lambda d: session.get(DataHall, d.data_hall_id).project_id
    if project(trunks) != project(legs):
        raise HTTPException(400, "Trunk labels must come from a discipline in the same project")
    if trunks.trunk_discipline_id is not None:
        raise HTTPException(400, f"'{trunks.name}' already links its own trunk labels and cannot hold trunks")
    if session.exec(select(Discipline.id).where(Discipline.trunk_discipline_id == legs.id)).first() is not None:
        raise HTTPException(400, f"'{legs.name}' holds trunk labels for another discipline and cannot link trunks itself")


def _delete_discipline(session: Session, d: Discipline, *, force: bool = False) -> None:
    # Leg disciplines lose their trunks with it; their own labels stay.
    session.exec(update(Discipline).where(Discipline.trunk_discipline_id == d.id).values(trunk_discipline_id=None))
    delete_labels(session, Label.discipline_id == d.id, force=force)
    session.exec(delete(Import).where(Import.discipline_id == d.id))
    session.delete(d)
    session.flush()
