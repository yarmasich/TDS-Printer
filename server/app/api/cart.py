"""Per-tablet cart of labels queued for printing.

Each tablet generates an opaque ``session_id`` in localStorage and passes it
to every cart endpoint as the ``sid`` query/body parameter. Items are tied
to a real ``Label`` row by id; the discipline's template decides how each
gets printed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import exists, update
from sqlalchemy.orm import aliased
from sqlmodel import Session, delete, select

from ..db import get_session
from ..models import CartItem, DataHall, Discipline, Label, PrintLog, Printer, Project, Template
from ..printer import PrintError, render_and_send

logger = logging.getLogger("tds.cart")
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
    status: str = "queued"
    error: str = ""


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
        status=item.status, error=item.error,
        added_at=item.added_at.isoformat(timespec="seconds"),
    )


@router.get("", response_model=List[CartItemDTO])
def list_cart(sid: str = Query(...), db: Session = Depends(get_session)) -> List[CartItemDTO]:
    _expire_claims(db, sid)
    rows = db.exec(
        select(CartItem, Label, Discipline, DataHall, Project)
        .outerjoin(Label, CartItem.label_id == Label.id)
        .outerjoin(Discipline, Label.discipline_id == Discipline.id)
        .outerjoin(DataHall, Discipline.data_hall_id == DataHall.id)
        .outerjoin(Project, DataHall.project_id == Project.id)
        .where(CartItem.session_id == sid)
        .order_by(CartItem.added_at, CartItem.id)
    ).all()

    out: List[CartItemDTO] = []
    for item, label, disc, hall, proj in rows:
        tmpl = db.get(Template, disc.template_id) if disc and disc.template_id else None
        out.append(CartItemDTO(
            id=item.id,
            label_id=label.id if label else None,
            discipline_name=disc.name if disc else "?",
            project_name=proj.name if proj else "?",
            data_hall_name=hall.name if hall else "?",
            left_text=item.left_text,
            right_text=item.right_text,
            template_name=tmpl.name if tmpl else None,
            status=item.status, error=item.error,
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


def _expire_claims(db: Session, sid: str) -> None:
    """An interrupted send is NEVER returned to the automatic retry queue.

    Workers renew all remaining claims before each bounded send. Five minutes
    without progress is an interrupted job, requiring physical label review.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.execute(update(CartItem).where(
        CartItem.session_id == sid, CartItem.status == "printing",
        (CartItem.claimed_at < cutoff) | CartItem.claimed_at.is_(None),
    ).values(status="uncertain", claim_token="", claimed_at=None,
             error="Printing was interrupted. Check the physical labels before removing or adding again."))
    db.commit()


def _lock_cart(db: Session, sid: str) -> None:
    # Serialize a check+mutation against the atomic claim UPDATE. SQLite's
    # deferred read transaction otherwise allows a worker to claim after check.
    if db.get_bind().dialect.name == "sqlite":
        connection = db.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    if db.exec(select(CartItem.id).where(
        CartItem.session_id == sid, CartItem.status == "printing"
    ).limit(1)).first() is not None:
        db.rollback()
        raise HTTPException(409, "This cart is currently printing. Wait for it to finish.")


@router.delete("/{item_id}")
def remove_item(
    item_id: int, sid: str = Query(...), db: Session = Depends(get_session)
) -> dict:
    _expire_claims(db, sid)
    _lock_cart(db, sid)
    item = db.get(CartItem, item_id)
    if not item or item.session_id != sid:
        db.rollback()
        raise HTTPException(404, "Cart item not found")
    db.delete(item)
    db.commit()
    return {"deleted": item_id}


@router.delete("")
def clear_cart(sid: str = Query(...), db: Session = Depends(get_session)) -> dict:
    _expire_claims(db, sid)
    _lock_cart(db, sid)
    n = db.exec(delete(CartItem).where(CartItem.session_id == sid)).rowcount or 0
    db.commit()
    return {"cleared": n}


class PrintAllResult(BaseModel):
    ok: int
    errors: List[dict]
    log_ids: List[int]


@router.post("/print", response_model=PrintAllResult)
def print_all(req: PrintAllRequest, db: Session = Depends(get_session)) -> PrintAllResult:
    _expire_claims(db, req.sid)
    token = uuid4().hex
    active = aliased(CartItem)
    # One SQLite write statement both checks the session and claims every
    # queued item. Concurrent workers cannot pass this condition together.
    claimed = db.execute(update(CartItem).where(
        CartItem.session_id == req.sid, CartItem.status == "queued",
        ~exists(select(active.id).where(active.session_id == req.sid, active.status == "printing")),
    ).values(status="printing", claim_token=token,
             claimed_at=datetime.now(timezone.utc), error=""),
        execution_options={"synchronize_session": False})
    count = claimed.rowcount
    db.commit()
    if not count:
        if db.exec(select(CartItem.id).where(
            CartItem.session_id == req.sid, CartItem.status == "printing"
        ).limit(1)).first() is not None:
            raise HTTPException(409, "This cart is already printing.")
        raise HTTPException(400, "No queued labels. Check any uncertain items before adding them again.")

    ids = list(db.exec(select(CartItem.id).where(CartItem.claim_token == token)
                       .order_by(CartItem.added_at, CartItem.id)).all())
    ok, errors, log_ids = 0, [], []
    current_id = None
    try:
        for item_id in ids:
            current_id = item_id
            # Renew only our remaining claim; never revive an expired claim.
            db.execute(update(CartItem).where(
                CartItem.claim_token == token, CartItem.status == "printing"
            ).values(claimed_at=datetime.now(timezone.utc)))
            db.commit()
            item = db.get(CartItem, item_id)
            if not item or item.status != "printing" or item.claim_token != token:
                errors.append({"item_id": item_id, "error": "Print claim interrupted; item was not resent."})
                continue
            log = PrintLog(operator=req.operator, reason=req.reason,
                           left_text=item.left_text, right_text=item.right_text)
            error, uncertain = None, False
            try:
                label = db.get(Label, item.label_id) if item.label_id else None
                disc = db.get(Discipline, label.discipline_id) if label else None
                tmpl = db.get(Template, disc.template_id) if disc and disc.template_id else None
                printer = db.get(Printer, tmpl.printer_id) if tmpl else None
                if not (label and disc and tmpl and printer):
                    raise PrintError("Label, template or printer is missing; check the discipline settings.")
                log.template_name = tmpl.name
                log.printer_ip = f"{printer.ip}:{printer.port}"
                render_and_send(tmpl, printer, item.left_text, item.right_text, req.operator, req.reason)
            except PrintError as exc:
                error, uncertain = str(exc), exc.uncertain
            except Exception as exc:
                # Unknown failures may occur after sending. Conservatively
                # hold this item for operator review instead of printing twice.
                logger.exception("Unexpected cart print failure for item %s", item_id)
                error, uncertain = f"Unexpected print failure: {exc}", True

            if error:
                item.status = "uncertain" if uncertain else "queued"
                item.error = error
                log.status = item.status if uncertain else "error"
                log.error = error
                errors.append({"item_id": item_id, "error": error, "uncertain": uncertain})
                db.add(item)
            else:
                # Durable progress per label: a later failure cannot return a
                # successfully sent item to the queue.
                if req.clear_after:
                    db.delete(item)
                else:
                    item.status = "printed"
                    db.add(item)
                ok += 1
            db.add(log)
            db.commit()
            db.refresh(log)
            log_ids.append(log.id)
            current_id = None
    except Exception as exc:
        db.rollback()
        # If persistence failed after the send, retain the durable claim as
        # uncertain. An unavailable database leaves it to _expire_claims.
        try:
            if current_id is not None:
                db.execute(update(CartItem).where(CartItem.id == current_id,
                    CartItem.claim_token == token).values(status="uncertain",
                    error="Print outcome could not be saved. Check physical labels."))
            db.execute(update(CartItem).where(CartItem.claim_token == token,
                CartItem.status == "printing").values(status="queued", claim_token="", claimed_at=None))
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(503, "Printing interrupted while saving progress. Refresh the cart and check uncertain labels.") from exc

    # clear_after=false explicitly preserves successful labels for another run.
    db.execute(update(CartItem).where(CartItem.claim_token == token,
        CartItem.status == "printed").values(status="queued"))
    db.execute(update(CartItem).where(CartItem.claim_token == token).values(claim_token="", claimed_at=None))
    db.commit()
    logger.info("print_all sid=%s: ok=%d, errors=%d", req.sid, ok, len(errors))
    return PrintAllResult(ok=ok, errors=errors, log_ids=log_ids)
