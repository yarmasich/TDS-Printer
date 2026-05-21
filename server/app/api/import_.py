"""Import endpoints.

* ``POST /api/import/scan`` — server-side: walks a directory tree on the
  server filesystem and auto-creates Project / DataHall / Discipline rows
  along the way.
* ``POST /api/import/upload`` — accepts one .xlsx and ingests it into an
  existing discipline by id.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from ..db import get_session
from ..importer import (
    ImportStats,
    import_workbook_into_discipline,
    scan_labels_dir,
)
from ..models import Discipline

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/scan")
def scan(
    root: str = Form(..., description="absolute path on the server to a Labels/ tree"),
    wipe: bool = Form(False),
    session: Session = Depends(get_session),
) -> dict:
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(400, f"Not a directory: {path}")
    return _stats_dict(scan_labels_dir(session, path, wipe=wipe))


@router.post("/upload")
async def upload(
    discipline_id: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Expected an .xlsx file")
    d = session.get(Discipline, discipline_id)
    if not d:
        raise HTTPException(404, "Discipline not found")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tds-upload-"))
    try:
        tmp_path = tmp_dir / file.filename
        with tmp_path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return _stats_dict(import_workbook_into_discipline(
            session, tmp_path, d, display_filename=file.filename,
        ))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _stats_dict(s: ImportStats) -> dict:
    return {
        "files": s.files,
        "sheets": s.sheets,
        "rows": s.rows,
        "skipped": s.skipped,
        "disciplines_created": s.disciplines_created,
    }
