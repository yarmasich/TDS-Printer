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
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from ..db import get_session
from ..importer import (
    ImportStats,
    InvalidWorkbookError,
    import_workbook_into_discipline,
    remove_discipline_imports,
    scan_labels_dir,
)
from ..import_limits import ImportLimitError, ImportLimits, copy_upload
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
    try:
        return _stats_dict(scan_labels_dir(session, path, wipe=wipe))
    except ImportLimitError as exc:
        raise HTTPException(413, str(exc)) from exc
    except InvalidWorkbookError as exc:
        raise HTTPException(400, "Invalid XLSX workbook in scan") from exc


@router.post("/upload")
async def upload(
    discipline_id: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    replace: Annotated[bool, Form(
        description="Remove the discipline's earlier imports and their labels in the same "
        "transaction. A file that fails to import leaves them in place.")] = False,
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Expected an .xlsx file")
    d = session.get(Discipline, discipline_id)
    if not d:
        raise HTTPException(404, "Discipline not found")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tds-upload-"))
    try:
        tmp_path = tmp_dir / "upload.xlsx"
        with tmp_path.open("wb") as out:
            copy_upload(file.file, out, ImportLimits.from_env())
        replaced = remove_discipline_imports(session, d) if replace else (0, 0)
        stats = import_workbook_into_discipline(
            session, tmp_path, d, display_filename=file.filename,
        )
        stats.replaced_imports, stats.labels_removed = replaced
        session.commit()
        return _stats_dict(stats)
    except ImportLimitError as exc:
        session.rollback()
        raise HTTPException(413, str(exc)) from exc
    except InvalidWorkbookError as exc:
        session.rollback()
        raise HTTPException(400, "Invalid XLSX workbook") from exc
    except Exception:
        session.rollback()
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _stats_dict(s: ImportStats) -> dict:
    return {
        "files": s.files,
        "sheets": s.sheets,
        "rows": s.rows,
        "skipped": s.skipped,
        "trunk_rows": s.trunk_rows,
        "duplicate_legs": s.duplicate_legs,
        "replaced_imports": s.replaced_imports,
        "labels_removed": s.labels_removed,
        "disciplines_created": s.disciplines_created,
    }
