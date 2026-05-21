"""Per-tablet cart of labels queued for printing.

Each tablet generates an opaque ``session_id`` in localStorage and passes it
to every cart endpoint as the ``sid`` query/body parameter. Items are tied
to a real ``Label`` row by id; the discipline's template decides how each
gets printed.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, delete, select

from ..db import get_session
from ..models import CartItem, DataHall, Discipline, Label, PrintLog, Printer, Project, Template
from ..printer import PrintError, render_and_send

router = APIRouter(prefix="/api/cart", tags=["cart"])


class CartItemDTO(BaseModel):
    id: int
    label_id: Optional[int]
    discipline_name: str
    project_name: str
    data_hall_name: str
    left_text: str
    right_text: str
    template_name: Optional[str] = None
    added_at: str


class AddRequest(BaseModel):
    sid: str
    label_id: int


class PrintAllRequest(BaseModel):
    sid: str
    operator: str = ""
    reason: str = ""
    clear_after: bool = True


@router.get("", response_model=List[CartItemDTO])
def list_cart(sid: str = Query(...), db: Session = Depends(get_session)) -> List[CartItemDTO]:
    rows = db.exec(
        select(CartItem, Label, Discipline, DataHall, Project)
        .join(Label, CartItem.label_id == Label.id)
        .join(Discipline, Label.discipline_id == Discipline.id)
        .join(DataHall, Discipline.data_hall_id == DataHall.id)
        .join(Project, DataHall.project_id == Project.id)
        .where(CartItem.session_id == sid)
        .order_by(CartItem.added_at)
    ).all()

    out: List[CartItemDTO] = []
    for item, label, disc, hall, proj in rows:
        tmpl = db.get(Template, disc.template_id) if disc.template_id else None
        out.append(CartItemDTO(
            id=item.id,
            label_id=label.id,
            discipline_name=disc.name,
            project_name=proj.name,
            data_hall_name=hall.name,
            left_text=label.left_text,
            right_text=label.right_text,
            template_name=tmpl.name if tmpl else None,
            added_at=item.added_at.isoformat(timespec="seconds"),
        ))
    return out


@router.post("", response_model=CartItemDTO)
def add_to_cart(req: AddRequest, db: Session = Depends(get_session)) -> CartItemDTO:
    label = db.get(Label, req.label_id)
    if not label:
        raise HTTPException(404, "Label not found")
    # snapshot current text so cart still works if the label is later edited
    item = CartItem(
        session_id=req.sid,
        label_id=label.id,
        left_text=label.left_text,
        right_text=label.right_text,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return list_cart(sid=req.sid, db=db)[-1]


@router.delete("/{item_id}")
def remove_item(
    item_id: int, sid: str = Query(...), db: Session = Depends(get_session)
) -> dict:
    item = db.get(CartItem, item_id)
    if not item or item.session_id != sid:
        raise HTTPException(404, "Cart item not found")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}


@router.delete("")
def clear_cart(sid: str = Query(...), db: Session = Depends(get_session)) -> dict:
    n = db.exec(delete(CartItem).where(CartItem.session_id == sid)).rowcount or 0
    db.commit()
    return {"cleared": n}


class PrintAllResult(BaseModel):
    ok: int
    errors: List[dict]
    log_ids: List[int]


@router.post("/print", response_model=PrintAllResult)
def print_all(
    req: PrintAllRequest, db: Session = Depends(get_session)
) -> PrintAllResult:
    items = db.exec(
        select(CartItem).where(CartItem.session_id == req.sid)
        .order_by(CartItem.added_at)
    ).all()
    if not items:
        raise HTTPException(400, "Cart is empty")

    ok = 0
    errors: List[dict] = []
    log_ids: List[int] = []

    for item in items:
        label = db.get(Label, item.label_id) if item.label_id else None
        if not label:
            errors.append({"item_id": item.id, "error": "label no longer exists"})
            continue
        disc = db.get(Discipline, label.discipline_id)
        if not disc or not disc.template_id:
            errors.append({"item_id": item.id, "error": f"discipline '{disc.name if disc else '?'}' has no template"})
            continue
        tmpl = db.get(Template, disc.template_id)
        printer = db.get(Printer, tmpl.printer_id) if tmpl else None
        if not (tmpl and printer):
            errors.append({"item_id": item.id, "error": "template or printer missing"})
            continue

        log = PrintLog(
            template_name=tmpl.name,
            printer_ip=f"{printer.ip}:{printer.port}",
            operator=req.operator,
            reason=req.reason,
            left_text=label.left_text,
            right_text=label.right_text,
        )
        try:
            render_and_send(tmpl, printer, label.left_text, label.right_text,
                            req.operator, req.reason)
        except PrintError as e:
            log.status = "error"
            log.error = str(e)
            errors.append({"item_id": item.id, "error": str(e)})
            db.add(log); db.commit(); db.refresh(log)
            log_ids.append(log.id)
            continue
        db.add(log); db.commit(); db.refresh(log)
        log_ids.append(log.id)
        ok += 1

    if req.clear_after and ok and not errors:
        db.exec(delete(CartItem).where(CartItem.session_id == req.sid))
        db.commit()

    return PrintAllResult(ok=ok, errors=errors, log_ids=log_ids)
