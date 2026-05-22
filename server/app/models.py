"""SQLModel tables.

Hierarchy::

    Printer ←── Template ←── Discipline ←── DataHall ←── Project
                                ↑
                              Label

A Template is a reusable ZPL/raster config that targets one Printer. A
Discipline is bound to one Template — that's how we know *how* to print a
given label. Labels are owned by a Discipline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint


def _utcnow() -> datetime:
    """Timezone-aware UTC ``now`` — replaces deprecated ``datetime.utcnow``."""
    return datetime.now(timezone.utc)


class HAlign(str, Enum):
    LEFT = "LEFT"
    CENTER = "CENTER"
    RIGHT = "RIGHT"


class VAlign(str, Enum):
    TOP = "TOP"
    CENTER = "CENTER"
    BOTTOM = "BOTTOM"


# ──────────────────────────── printer / template ────────────────────────────

class Printer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    ip: str
    port: int = 9100
    notes: str = ""


class Template(SQLModel, table=True):
    """Reusable print config — references a printer; configures bitmap rendering.

    Field names match the Android app's ``PrintSettings`` (and the on-disk
    ``PANDUIT_TEMPLATE_EXPORT_V1`` order in ``default_templates.txt``):
    each ``*_top``/``*_bottom``/``*_left``/``*_right`` is one **edge** of
    that text rectangle (not x/y/width/height).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    printer_id: int = Field(foreign_key="printer.id")

    # Bitmap geometry
    bytes_per_row: int
    height: int

    # Left text rectangle (edges, px)
    left_top: float = 0
    left_bottom: float = 0
    left_left: float = 0
    left_right: float = 0

    # Right text rectangle (edges, px)
    right_top: float = 0
    right_bottom: float = 0
    right_left: float = 0
    right_right: float = 0

    # Inter-rect padding (px)
    gap_top: float = 0
    gap_bottom: float = 0
    gap_left: float = 0
    gap_right: float = 0

    # Default text — shown when no override comes from the cable row
    left_text: str = "TEXT+12345"
    right_text: str = "TEXT+12345"

    # Typography
    left_pt: float = 7
    right_pt: float = 7
    h_align: HAlign = HAlign.CENTER
    v_align: VAlign = VAlign.CENTER
    font_name: str = "Microsoft Sans Serif"
    font_style: str = "Bold"

    # Per-side baseline offsets (px), useful for fine vertical alignment
    left_offset: float = 0
    right_offset: float = 0


# ──────────────────────────── project hierarchy ────────────────────────────

class Project(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)


class DataHall(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str


class Discipline(SQLModel, table=True):
    """One discipline (subfolder with .xlsx in the original CLI layout)."""
    __table_args__ = (UniqueConstraint("data_hall_id", "name"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    data_hall_id: int = Field(foreign_key="datahall.id", index=True)
    name: str
    template_id: Optional[int] = Field(default=None, foreign_key="template.id")
    color: str = "FFFFFF"


class Import(SQLModel, table=True):
    """One XLSX upload. Owns a batch of ``Label`` rows.

    Lets the UI list uploaded files per discipline and delete them as a
    unit (which cascades the labels via ``Label.import_id``).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    discipline_id: int = Field(foreign_key="discipline.id", index=True)
    filename: str
    uploaded_at: datetime = Field(default_factory=_utcnow, index=True)
    sheets: int = 0
    rows: int = 0
    skipped: int = 0


class Label(SQLModel, table=True):
    """One label row from an imported workbook."""
    id: Optional[int] = Field(default=None, primary_key=True)
    discipline_id: int = Field(foreign_key="discipline.id", index=True)
    import_id: Optional[int] = Field(
        default=None, foreign_key="import.id", index=True
    )
    sheet_name: str = ""
    source_file: str = ""
    row_idx: int = 0
    left_text: str = ""
    right_text: str = ""


# ──────────────────────────── shared lists / logs ────────────────────────────

class Reason(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str = Field(unique=True)
    sort_order: int = 0


class AuthName(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)


class CartItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    label_id: Optional[int] = Field(default=None, foreign_key="label.id")
    added_at: datetime = Field(default_factory=_utcnow)
    left_text: str = ""
    right_text: str = ""


class PrintLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=_utcnow, index=True)
    template_name: str = ""
    printer_ip: str = ""
    operator: str = ""
    reason: str = ""
    left_text: str = ""
    right_text: str = ""
    status: str = "ok"
    error: str = ""
