"""Bootstrap defaults from ``default_templates.txt`` on first run.

We seed only when the ``Template`` table is empty — that's our "virgin
DB" marker. A user who wipes all templates on purpose will get them
back on the next restart; that's easier to explain (and to undo) than
a one-shot flag in another table.

File format is the Android app's ``PANDUIT_TEMPLATE_EXPORT_V1``: a
header line, ``count=N``, then ``template_i_name=...`` /
``template_i_data=<pipe-separated fields>`` pairs. Field order is
locked to the columns of ``Template`` (+ printer ``ip``/``port`` up
front), see ``_FIELDS`` below.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from .models import HAlign, Printer, Template, VAlign

log = logging.getLogger(__name__)

DEFAULTS_FILE = Path(__file__).resolve().parent / "default_templates.txt"

_FIELDS: List[str] = [
    "ip", "port", "bytes_per_row", "height",
    "left_top", "left_bottom", "left_left", "left_right",
    "right_top", "right_bottom", "right_left", "right_right",
    "gap_top", "gap_bottom", "gap_left", "gap_right",
    "left_text", "right_text",
    "left_pt", "right_pt",
    "h_align", "v_align", "mirror_mode",
    "font_name", "font_style",
    "left_offset", "right_offset",
]

_FLOAT_FIELDS = (
    "left_top", "left_bottom", "left_left", "left_right",
    "right_top", "right_bottom", "right_left", "right_right",
    "gap_top", "gap_bottom", "gap_left", "gap_right",
    "left_pt", "right_pt", "left_offset", "right_offset",
)


def _parse(text: str) -> List[Tuple[str, Dict[str, str]]]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0] != "PANDUIT_TEMPLATE_EXPORT_V1":
        raise ValueError("not a PANDUIT_TEMPLATE_EXPORT_V1 file")
    kv: Dict[str, str] = {}
    for ln in lines[1:]:
        if "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        kv[k.strip()] = v.strip()
    count = int(kv.get("count", "0"))
    out: List[Tuple[str, Dict[str, str]]] = []
    for i in range(count):
        name = kv.get(f"template_{i}_name")
        data = kv.get(f"template_{i}_data")
        if not name or not data:
            continue
        parts = data.split("|")
        if len(parts) != len(_FIELDS):
            raise ValueError(
                f"template_{i}_data has {len(parts)} fields, expected {len(_FIELDS)}"
            )
        out.append((name, dict(zip(_FIELDS, parts))))
    return out


def _coerce(d: Dict[str, str]) -> Dict[str, object]:
    return {
        "ip": d["ip"],
        "port": int(d["port"]),
        "bytes_per_row": int(d["bytes_per_row"]),
        "height": int(d["height"]),
        **{f: float(d[f]) for f in _FLOAT_FIELDS},
        "left_text": d["left_text"],
        "right_text": d["right_text"],
        "h_align": HAlign(d["h_align"]),
        "v_align": VAlign(d["v_align"]),
        "mirror_mode": d["mirror_mode"].strip().lower() == "true",
        "font_name": d["font_name"],
        "font_style": d["font_style"],
    }


def seed_defaults_if_empty(engine: Engine) -> int:
    """Create default printers + templates on a virgin DB.

    Returns the number of templates inserted (0 if DB already had any
    template, or the defaults file is missing).
    """
    if not DEFAULTS_FILE.is_file():
        return 0
    with Session(engine) as db:
        if db.exec(select(Template).limit(1)).first():
            return 0
        entries = _parse(DEFAULTS_FILE.read_text(encoding="utf-8"))
        if not entries:
            return 0

        # One Printer per (ip, port) — multiple templates can share it.
        # Reuse an existing 'imported-{ip}' printer if it somehow exists
        # already (e.g. templates were deleted but printers weren't).
        printers_by_addr: Dict[Tuple[str, int], Printer] = {}
        for _name, raw in entries:
            f = _coerce(raw)
            addr = (f["ip"], f["port"])
            if addr in printers_by_addr:
                continue
            p_name = f"imported-{f['ip']}"
            existing = db.exec(
                select(Printer).where(Printer.name == p_name)
            ).first()
            if existing:
                printers_by_addr[addr] = existing
            else:
                printer = Printer(name=p_name, ip=f["ip"], port=f["port"])
                db.add(printer)
                db.flush()  # need printer.id for the Template FK
                printers_by_addr[addr] = printer

        for name, raw in entries:
            f = _coerce(raw)
            printer = printers_by_addr[(f["ip"], f["port"])]
            db.add(Template(
                name=name,
                printer_id=printer.id,
                bytes_per_row=f["bytes_per_row"],
                height=f["height"],
                left_top=f["left_top"], left_bottom=f["left_bottom"],
                left_left=f["left_left"], left_right=f["left_right"],
                right_top=f["right_top"], right_bottom=f["right_bottom"],
                right_left=f["right_left"], right_right=f["right_right"],
                gap_top=f["gap_top"], gap_bottom=f["gap_bottom"],
                gap_left=f["gap_left"], gap_right=f["gap_right"],
                left_text=f["left_text"], right_text=f["right_text"],
                left_pt=f["left_pt"], right_pt=f["right_pt"],
                h_align=f["h_align"], v_align=f["v_align"],
                mirror_mode=f["mirror_mode"],
                font_name=f["font_name"], font_style=f["font_style"],
                left_offset=f["left_offset"], right_offset=f["right_offset"],
            ))
        db.commit()
        log.info("Seeded %d default template(s) from %s", len(entries), DEFAULTS_FILE.name)
        return len(entries)
