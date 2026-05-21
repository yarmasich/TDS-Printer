from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from ..db import get_session
from ..models import Discipline, Label, PrintLog, Printer, Template
from ..printer import PrintError, render_and_send, render_label_png

router = APIRouter(prefix="/api/print", tags=["print"])


@router.get("/preview")
def preview(
    template_id: Optional[int] = Query(None),
    label_id: Optional[int] = Query(None),
    left_text: str = "",
    right_text: str = "",
    session: Session = Depends(get_session),
):
    """Render the same bitmap that would go to the printer, return PNG.

    Pass either ``label_id`` (uses the discipline's template + label's text)
    or ``template_id`` + ``left_text``/``right_text``.
    """
    if label_id is not None:
        label = session.get(Label, label_id)
        if not label:
            raise HTTPException(404, "Label not found")
        disc = session.get(Discipline, label.discipline_id)
        if not disc or not disc.template_id:
            raise HTTPException(400, "Discipline has no template assigned")
        tmpl = session.get(Template, disc.template_id)
        if not tmpl:
            raise HTTPException(500, "Discipline points at a missing template")
        left = left_text or label.left_text
        right = right_text or label.right_text
    elif template_id is not None:
        tmpl = session.get(Template, template_id)
        if not tmpl:
            raise HTTPException(404, "Template not found")
        left = left_text or tmpl.left_text
        right = right_text or tmpl.right_text
    else:
        raise HTTPException(400, "Provide label_id or template_id")
    png = render_label_png(tmpl, left, right)
    return Response(content=png, media_type="image/png")


class PrintRequest(BaseModel):
    """Either supply ``label_id`` (uses the discipline's bound template) OR
    ``template_id`` + ``left_text`` / ``right_text``."""
    label_id: Optional[int] = None
    template_id: Optional[int] = None
    left_text: str = ""
    right_text: str = ""
    operator: str = ""
    reason: str = ""


@router.post("")
def submit_print(req: PrintRequest, session: Session = Depends(get_session)) -> dict:
    template: Template
    left = req.left_text
    right = req.right_text

    if req.label_id is not None:
        label = session.get(Label, req.label_id)
        if not label:
            raise HTTPException(404, "Label not found")
        disc = session.get(Discipline, label.discipline_id)
        if not disc or not disc.template_id:
            raise HTTPException(
                400,
                f"Discipline '{disc.name if disc else '?'}' has no template assigned. "
                "Go to Admin and pick one.",
            )
        template = session.get(Template, disc.template_id)
        if not template:
            raise HTTPException(500, "Discipline points at a missing template")
        # If the caller didn't override, use the label's own text.
        left = left or label.left_text
        right = right or label.right_text
    elif req.template_id is not None:
        template = session.get(Template, req.template_id)
        if not template:
            raise HTTPException(404, "Template not found")
    else:
        raise HTTPException(400, "Provide either label_id or template_id")

    printer = session.get(Printer, template.printer_id)
    if not printer:
        raise HTTPException(500, "Template points at a missing printer")

    log = PrintLog(
        template_name=template.name,
        printer_ip=f"{printer.ip}:{printer.port}",
        operator=req.operator,
        reason=req.reason,
        left_text=left,
        right_text=right,
    )
    try:
        render_and_send(template, printer, left, right, req.operator, req.reason)
    except PrintError as e:
        log.status = "error"
        log.error = str(e)
        session.add(log)
        session.commit()
        raise HTTPException(502, f"Print failed: {e}")

    session.add(log)
    session.commit()
    session.refresh(log)
    return {"ok": True, "log_id": log.id}
