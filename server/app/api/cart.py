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


def _item_to_dto(item: CartItem, db: Session) -> CartItemDTO:
    """Build a CartItemDTO for a single cart item using its FK chain."""
    label = db.get(Label, item.label_id) if item.label_id else None
    disc = db.get(Discipline, label.discipline_id) if label else None
    hall = db.get(DataHall, disc.data_hall_id) if disc else None
    proj = db.get(Project, hall.project_id) if hall else None
    tmpl = db.get(Template, disc.template_id) if disc and disc.template_id else None
    return CartItemDTO(
        id=item.id,
        label_id=label.id if label else None,
        discipline_name=disc.name if disc else "?",
        project_name=proj.name if proj else "?",
        data_hall_name=hall.name if hall else "?",
        left_text=item.left_text,
        right_text=item.right_text,
        template_name=tmpl.name if tmpl else None,
        added_at=item.added_at.isoformat(timespec="seconds"),
    )


@router.get("", response_model=List[CartItemDTO])
def list_cart(sid: str = Query(...), db: Session = Depends(get_session)) -> List[CartItemDTO]:
    rows = db.exec(
        select(CartItem, Label, Discipline, DataHall, Project)
        .join(Label, CartItem.label_id == Label.id)
        .join(Discipline, Label.discipline_id == Discipline.id)
        .join(DataHall, Discipline.data_hall_id == DataHall.id)
        .join(Project, DataHall.project_id == Project.id)
        .where(CartItem.session_id == sid)
        .order_by(CartItem.added_at, CartItem.id)
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
            left_text=item.left_text,
            right_text=item.right_text,
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
    return _item_to_dto(item, db)


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
    printed_item_ids: List[int] = []

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

        # Use the snapshotted text from the cart item, not the live label.
        left = item.left_text
        right = item.right_text
        log = PrintLog(
            template_name=tmpl.name,
            printer_ip=f"{printer.ip}:{printer.port}",
            operator=req.operator,
            reason=req.reason,
            left_text=left,
            right_text=right,
        )
        try:
            render_and_send(tmpl, printer, left, right, req.operator, req.reason)
        except PrintError as e:
            log.status = "error"
            log.error = str(e)
            errors.append({"item_id": item.id, "error": str(e)})
            db.add(log)
            db.commit()
            db.refresh(log)
            log_ids.append(log.id)
            continue
        db.add(log)
        db.commit()
        db.refresh(log)
        log_ids.append(log.id)
        printed_item_ids.append(item.id)
        ok += 1

    # Drop only the items we actually printed — keeps failures in the cart so
    # the operator can retry / remove them without re-printing what worked.
    if req.clear_after and printed_item_ids:
        db.exec(delete(CartItem).where(CartItem.id.in_(printed_item_ids)))
        db.commit()

    return PrintAllResult(ok=ok, errors=errors, log_ids=log_ids)
