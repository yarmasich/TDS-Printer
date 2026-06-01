"""External machine-to-machine print API (versioned, API-key protected).

An external app prints a label by **cable number** plus enough scope to find
exactly one match — typically a ``discipline_id``, or a ``project`` +
``discipline`` name pair. We look the cable up the same way the operator UI
does (``search.cable_query_pattern``), resolve the discipline's bound
template, render and send. Every print is recorded in ``PrintLog`` with the
API key's name as the operator, so API prints show up in history alongside
manual ones.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Security
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..auth_apikey import require_api_key
from ..db import get_session
from ..models import ApiKey, DataHall, Discipline, Label, PrintLog, Printer, Project, Template
from ..printer import PrintError, render_and_send
from ..search import cable_query_pattern, validate_query

router = APIRouter(prefix="/api/v1", tags=["integrations"])


class ApiPrintRequest(BaseModel):
    cable: str = Field(..., description="Cable number or text, e.g. '1.1'")
    # Scope — provide discipline_id, OR discipline (+ project / data_hall) by name.
    discipline_id: Optional[int] = None
    project: Optional[str] = None
    data_hall: Optional[str] = None
    discipline: Optional[str] = None
    reason: str = ""
    copies: int = Field(1, ge=1, le=50)


class ApiPrintResponse(BaseModel):
    ok: bool
    log_ids: List[int]
    label_id: int
    left_text: str
    right_text: str
    template_name: str
    printer: str
    copies: int


class CandidateDTO(BaseModel):
    label_id: int
    left_text: str
    right_text: str
    sheet_name: str
    row_idx: int


def _resolve_discipline(req: ApiPrintRequest, session: Session) -> Discipline:
    """Find exactly one discipline from the request's scope fields."""
    if req.discipline_id is not None:
        disc = session.get(Discipline, req.discipline_id)
        if not disc:
            raise HTTPException(404, f"Discipline {req.discipline_id} not found")
        return disc

    if not req.discipline:
        raise HTTPException(
            400, "Provide 'discipline_id', or 'discipline' (with 'project' to disambiguate)"
        )

    stmt = (
        select(Discipline)
        .join(DataHall, Discipline.data_hall_id == DataHall.id)
        .join(Project, DataHall.project_id == Project.id)
        .where(Discipline.name == req.discipline)
    )
    if req.project:
        stmt = stmt.where(Project.name == req.project)
    if req.data_hall:
        stmt = stmt.where(DataHall.name == req.data_hall)

    matches = session.exec(stmt).all()
    if not matches:
        raise HTTPException(404, f"No discipline named '{req.discipline}' in that scope")
    if len(matches) > 1:
        raise HTTPException(
            409,
            f"'{req.discipline}' is ambiguous ({len(matches)} matches) — "
            "add 'project' and/or 'data_hall' to narrow it.",
        )
    return matches[0]


def _resolve_label(disc: Discipline, cable: str, session: Session) -> Label:
    """Find the single label in this discipline matching the cable query."""
    ok, normalised = validate_query(cable)
    if not ok:
        raise HTTPException(400, f"Invalid cable query: {cable!r}")
    pat = cable_query_pattern(normalised)

    labels = session.exec(
        select(Label).where(Label.discipline_id == disc.id)
    ).all()
    hits = [
        lb
        for lb in labels
        if (lb.left_text and pat.search(lb.left_text))
        or (lb.right_text and pat.search(lb.right_text))
    ]
    if not hits:
        raise HTTPException(404, f"No label matching '{cable}' in discipline '{disc.name}'")
    if len(hits) > 1:
        candidates = [
            CandidateDTO(
                label_id=lb.id,
                left_text=lb.left_text,
                right_text=lb.right_text,
                sheet_name=lb.sheet_name,
                row_idx=lb.row_idx,
            ).model_dump()
            for lb in hits[:20]
        ]
        raise HTTPException(
            409,
            {
                "message": f"'{cable}' matches {len(hits)} labels in '{disc.name}' — "
                "narrow the query or print by label_id.",
                "candidates": candidates,
            },
        )
    return hits[0]


@router.post("/print", response_model=ApiPrintResponse)
def api_print(
    req: ApiPrintRequest,
    session: Session = Depends(get_session),
    key: ApiKey = Security(require_api_key),
) -> ApiPrintResponse:
    disc = _resolve_discipline(req, session)
    if not disc.template_id:
        raise HTTPException(
            400, f"Discipline '{disc.name}' has no template assigned"
        )
    template = session.get(Template, disc.template_id)
    if not template:
        raise HTTPException(500, "Discipline points at a missing template")
    printer = session.get(Printer, template.printer_id)
    if not printer:
        raise HTTPException(500, "Template points at a missing printer")

    label = _resolve_label(disc, req.cable, session)
    left, right = label.left_text, label.right_text
    operator = f"api:{key.name}"
    reason = req.reason or "API"

    log_ids: List[int] = []
    for _ in range(req.copies):
        log = PrintLog(
            template_name=template.name,
            printer_ip=f"{printer.ip}:{printer.port}",
            operator=operator,
            reason=reason,
            left_text=left,
            right_text=right,
        )
        try:
            render_and_send(template, printer, left, right, operator, reason)
        except PrintError as e:
            log.status = "error"
            log.error = str(e)
            session.add(log)
            session.commit()
            session.refresh(log)
            raise HTTPException(
                502,
                {
                    "message": f"Print failed: {e}",
                    "log_ids": log_ids + [log.id],
                    "printed": len(log_ids),
                },
            )
        session.add(log)
        session.commit()
        session.refresh(log)
        log_ids.append(log.id)

    return ApiPrintResponse(
        ok=True,
        log_ids=log_ids,
        label_id=label.id,
        left_text=left,
        right_text=right,
        template_name=template.name,
        printer=f"{printer.ip}:{printer.port}",
        copies=req.copies,
    )
