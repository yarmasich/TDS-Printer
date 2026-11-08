"""Resolve the intersection of template and station printers."""
from sqlmodel import Session, select

from .models import Printer, StationPrinter, Template
from .printer import PrintError


def allowed_printers(db: Session, station_id: int) -> dict[int, Printer]:
    printers = db.exec(
        select(Printer).join(StationPrinter).where(StationPrinter.station_id == station_id)
        .order_by(Printer.name, Printer.id)
    )
    return {printer.id: Printer.model_validate(printer.model_dump()) for printer in printers}


def select_printer(db: Session, allowed: dict[int, Printer] | None, template: Template,
                   default: int | None = None, choice: int | None = None) -> Printer:
    candidates = template.printer_ids or [template.printer_id]
    if allowed is None:
        target = template.printer_id if choice is None else choice
        if target not in candidates:
            raise PrintError("Selected printer is not configured for this template.")
        printer = db.get(Printer, target)
        if not printer:
            raise PrintError("Template points at a missing printer")
        return printer
    eligible = {key: printer for key, printer in allowed.items()
                if key in candidates and printer.protocol != "brother_ql"}
    if choice is not None:
        if choice not in eligible:
            raise PrintError("Selected printer is not allowed on this station for this template.")
        return eligible[choice]
    if not eligible:
        raise PrintError("Template printer is not allowed on this station.")
    if len(eligible) == 1:
        return next(iter(eligible.values()))
    if default in eligible:
        return eligible[default]
    raise PrintError(f"Choose a printer for template '{template.name}'.")
