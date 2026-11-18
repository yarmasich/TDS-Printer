"""Which labels a print request means: a leg, its trunk, or both.

A leg discipline points at the discipline holding its trunk labels
(Discipline.trunk_discipline_id); a leg and its trunk share Label.trunk_no,
read from the workbooks' `Trunk#` column. Legs and trunks print on different
stock, so callers route each label by its own discipline's template.
"""
from __future__ import annotations

from typing import Literal

from sqlmodel import Session, select

from .models import Discipline, Label

TrunkMode = Literal["none", "with", "only"]


class TrunkLookupError(Exception):
    """A requested trunk cannot be resolved; nothing should be printed."""

    def __init__(self, status: int, message: str, code: str = "trunk_lookup_failed"):
        super().__init__(message)
        self.status = status
        self.message = message
        # Machine code for scoped integrations, which never echo the message.
        self.code = code


def trunk_label(session: Session, leg: Label) -> Label:
    discipline = session.get(Discipline, leg.discipline_id)
    if discipline is None or discipline.trunk_discipline_id is None:
        name = discipline.name if discipline else "?"
        raise TrunkLookupError(409, f"Discipline '{name}' has no trunk labels linked", "trunk_not_linked")
    if not leg.trunk_no:
        raise TrunkLookupError(409, "This label has no trunk number; re-import its workbook with the Trunk# column",
                               "trunk_number_missing")
    trunks = session.get(Discipline, discipline.trunk_discipline_id)
    rows = session.exec(select(Label).where(
        Label.discipline_id == discipline.trunk_discipline_id,
        Label.trunk_no == leg.trunk_no, Label.leg_no.is_(None),
    ).order_by(Label.id).limit(2)).all()
    if not rows:
        raise TrunkLookupError(404, f"No trunk label {leg.trunk_no} in '{trunks.name}'", "trunk_label_not_found")
    if len(rows) > 1:
        # Printing either would be a guess about which physical trunk it is.
        raise TrunkLookupError(409, f"Trunk {leg.trunk_no} appears more than once in '{trunks.name}'",
                               "trunk_label_ambiguous")
    return rows[0]


def labels_for(session: Session, leg: Label, mode: TrunkMode) -> list[Label]:
    """The labels to print, leg first. Raises before anything is queued."""
    if mode == "none":
        return [leg]
    trunk = trunk_label(session, leg)
    return [trunk] if mode == "only" else [leg, trunk]
