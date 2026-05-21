"""List & delete uploaded XLSX files (and their labels)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from ..db import get_session
from ..models import DataHall, Discipline, Import, Label, Project

router = APIRouter(prefix="/api/imports", tags=["imports"])


class ImportDTO(BaseModel):
    id: int
    discipline_id: int
    discipline_name: str
    data_hall_name: str
    project_name: str
    filename: str
    uploaded_at: str
    sheets: int
    rows: int
    skipped: int


@router.get("", response_model=List[ImportDTO])
def list_imports(
    discipline_id: Optional[int] = None,
    project_id: Optional[int] = None,
    session: Session = Depends(get_session),
) -> List[ImportDTO]:
    stmt = (
        select(Import, Discipline, DataHall, Project)
        .join(Discipline, Import.discipline_id == Discipline.id)
        .join(DataHall, Discipline.data_hall_id == DataHall.id)
        .join(Project, DataHall.project_id == Project.id)
        .order_by(Import.uploaded_at.desc())
    )
    if discipline_id is not None:
        stmt = stmt.where(Discipline.id == discipline_id)
    if project_id is not None:
        stmt = stmt.where(Project.id == project_id)

    out: List[ImportDTO] = []
    for imp, disc, hall, proj in session.exec(stmt).all():
        out.append(ImportDTO(
            id=imp.id,
            discipline_id=disc.id,
            discipline_name=disc.name,
            data_hall_name=hall.name,
            project_name=proj.name,
            filename=imp.filename,
            uploaded_at=imp.uploaded_at.isoformat(timespec="seconds"),
            sheets=imp.sheets,
            rows=imp.rows,
            skipped=imp.skipped,
        ))
    return out


@router.delete("/{import_id}")
def delete_import(import_id: int, session: Session = Depends(get_session)) -> dict:
    """Delete the import and all labels attached to it.

    Bulk-deletes labels first (single statement that hits the DB immediately),
    so by the time SQLAlchemy emits ``DELETE FROM import`` the FK has nothing
    to complain about. With ``PRAGMA foreign_keys=ON`` SQLite checks the
    constraint per-statement, so order matters here.
    """
    imp = session.get(Import, import_id)
    if not imp:
        raise HTTPException(404, "Import not found")
    result = session.exec(delete(Label).where(Label.import_id == import_id))
    n_labels = result.rowcount or 0
    session.delete(imp)
    session.commit()
    return {"deleted": import_id, "labels_removed": n_labels}
