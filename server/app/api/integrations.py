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

import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from ..auth_apikey import require_api_key
from ..db import get_session
from ..models import ApiKey, DataHall, Discipline, Label, PrintLog, Printer, Project, Template
from ..printer import PrintError, ping_printer, render_and_send
from ..search import cable_query_pattern, parse_batch_query, validate_query

# Cap on how many labels one batch request may print, to keep a single call
# from monopolising the printer (each send is synchronous).
MAX_BATCH = 500

router = APIRouter(prefix="/api/v1", tags=["integrations"])


class ApiPrintRequest(BaseModel):
    # Accept the wire name ``printer_id`` (FloorHub's field) while keeping the
    # Python attribute ``printer`` — so code never confuses this *string code*
    # with the integer ``template.printer_id`` FK. ``printer`` is also accepted.
    model_config = ConfigDict(populate_by_name=True)

    cable: str = Field(..., description="Cable number or text, e.g. '1.1'")
    # Scope — provide discipline_id, OR discipline (+ project / data_hall) by name.
    discipline_id: Optional[int] = None
    project: Optional[str] = None
    data_hall: Optional[str] = None
    discipline: Optional[str] = None
    reason: str = ""
    copies: int = Field(1, ge=1, le=50)
    printer: Optional[str] = Field(
        None,
        alias="printer_id",
        description="Logical printer code (= printer name), e.g. 'WS1'. Sent as "
        "'printer_id'. Set by the calling workstation; overrides the template's "
        "printer so one discipline can print to any desk. Omit → template "
        "default. Unknown → 404.",
    )


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


class PrinterStatusDTO(BaseModel):
    name: str
    ip: str
    port: int
    protocol: str
    # Populated only when ``ping`` is on; null otherwise.
    online: Optional[bool] = None
    ms: Optional[float] = None
    error: str = ""


@router.get("/printers", response_model=List[PrinterStatusDTO])
def api_printers(
    ping: bool = Query(True, description="TCP-ping each printer (false = config only, fast)"),
    name: Optional[str] = Query(None, description="Filter to a single printer by exact name"),
    session: Session = Depends(get_session),
    key: ApiKey = Security(require_api_key),
) -> List[PrinterStatusDTO]:
    """Printer roster with live online status for external dashboards.

    With ``ping=true`` (default) each printer is TCP-connect probed (~2 s
    timeout each, checked serially) — keep that in mind when polling many
    printers. Use ``ping=false`` for a fast config-only listing.
    """
    stmt = select(Printer).order_by(Printer.name)
    if name:
        stmt = stmt.where(Printer.name == name)
    printers = session.exec(stmt).all()

    out: List[PrinterStatusDTO] = []
    for p in printers:
        dto = PrinterStatusDTO(name=p.name, ip=p.ip, port=p.port, protocol=p.protocol)
        if ping:
            ok, ms, err = ping_printer(p.ip, p.port)
            dto.online, dto.ms, dto.error = ok, ms, err
        out.append(dto)
    return out


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


def _match_cable(labels: List[Label], cable: str) -> tuple[str, List[Label]]:
    """Match a cable query against a pre-fetched label list.

    Returns ``(status, hits)`` where status is ``"invalid"`` (bad query) or
    ``"ok"`` (then ``hits`` may be 0, 1 or many — the caller decides). Pure /
    non-raising so it can drive both the single and batch endpoints.
    """
    ok, normalised = validate_query(cable)
    if not ok:
        return "invalid", []
    pat = cable_query_pattern(normalised)
    hits = [
        lb
        for lb in labels
        if (lb.left_text and pat.search(lb.left_text))
        or (lb.right_text and pat.search(lb.right_text))
    ]
    return "ok", hits


def _candidates(hits: List[Label], limit: int = 20) -> List[dict]:
    return [
        CandidateDTO(
            label_id=lb.id,
            left_text=lb.left_text,
            right_text=lb.right_text,
            sheet_name=lb.sheet_name,
            row_idx=lb.row_idx,
        ).model_dump()
        for lb in hits[:limit]
    ]


def _resolve_label(disc: Discipline, cable: str, session: Session) -> Label:
    """Find the single label in this discipline matching the cable query."""
    labels = session.exec(
        select(Label).where(Label.discipline_id == disc.id)
    ).all()
    status, hits = _match_cable(labels, cable)
    if status == "invalid":
        raise HTTPException(400, f"Invalid cable query: {cable!r}")
    if not hits:
        raise HTTPException(404, f"No label matching '{cable}' in discipline '{disc.name}'")
    if len(hits) > 1:
        raise HTTPException(
            409,
            {
                "message": f"'{cable}' matches {len(hits)} labels in '{disc.name}' — "
                "narrow the query or print by label_id.",
                "candidates": _candidates(hits),
            },
        )
    return hits[0]


GROUP_RE = re.compile(r"\d+\.\*?")           # whole-group query: "20." / "20.*"
_CABLE_TOKEN_RE = re.compile(r"#\s*\|?\s*([\d.]+)")


def _cable_token(text: str) -> Optional[str]:
    """Best-effort cable id from a label cell (``...CBL#20.3...`` → ``20.3``)."""
    m = _CABLE_TOKEN_RE.search(text or "")
    return m.group(1) if m else None


def _print_label(
    label: Label, template: Template, printer: Printer,
    operator: str, reason: str, session: Session,
) -> tuple[Optional[int], Optional[str]]:
    """Render+send one label, log it, return ``(log_id, error)``."""
    log = PrintLog(
        template_name=template.name,
        printer_ip=f"{printer.ip}:{printer.port}",
        operator=operator,
        reason=reason,
        left_text=label.left_text,
        right_text=label.right_text,
    )
    try:
        render_and_send(template, printer, label.left_text, label.right_text, operator, reason)
    except PrintError as e:
        log.status = "error"
        log.error = str(e)
        session.add(log)
        session.commit()
        session.refresh(log)
        return log.id, str(e)
    session.add(log)
    session.commit()
    session.refresh(log)
    return log.id, None


def _resolve_api_printer(
    template: Template, printer_code: Optional[str], session: Session
) -> Printer:
    """Pick the physical printer for an API job.

    Precedence:
      1. the request's ``printer`` code — the calling workstation's choice,
         matched against ``Printer.name``. An unknown code is a **404** (a typo
         must never silently print on the wrong desk);
      2. the template's ``printer_id`` (its default printer).

    This keeps the physical printer *out* of the discipline: one discipline can
    print to any workstation's printer, chosen per-request, without being bound
    to it.
    """
    code = (printer_code or "").strip()
    if code:
        printer = session.exec(select(Printer).where(Printer.name == code)).first()
        if not printer:
            raise HTTPException(404, f"Unknown printer {code!r}")
        return printer
    printer = session.get(Printer, template.printer_id)
    if not printer:
        raise HTTPException(500, "Template points at a missing printer")
    return printer


def _discipline_printer(
    disc: Discipline, session: Session, printer_code: Optional[str] = None
) -> tuple[Template, Printer]:
    """Resolve a discipline's template + the printer to use for API jobs.

    The template decides *how* to render (geometry / font); the printer is
    picked by ``_resolve_api_printer`` — a per-request ``printer`` code wins
    over the template's default ``printer_id``.
    """
    if not disc.template_id:
        raise HTTPException(400, f"Discipline '{disc.name}' has no template assigned")
    template = session.get(Template, disc.template_id)
    if not template:
        raise HTTPException(500, "Discipline points at a missing template")
    printer = _resolve_api_printer(template, printer_code, session)
    return template, printer


@router.post("/print", response_model=ApiPrintResponse)
def api_print(
    req: ApiPrintRequest,
    session: Session = Depends(get_session),
    key: ApiKey = Security(require_api_key),
) -> ApiPrintResponse:
    disc = _resolve_discipline(req, session)
    template, printer = _discipline_printer(disc, session, req.printer)

    label = _resolve_label(disc, req.cable, session)
    left, right = label.left_text, label.right_text
    operator = f"api:{key.name}"
    reason = req.reason or "API"

    log_ids: List[int] = []
    for _ in range(req.copies):
        log_id, err = _print_label(label, template, printer, operator, reason, session)
        if err:
            raise HTTPException(
                502,
                {
                    "message": f"Print failed: {err}",
                    "log_ids": log_ids + ([log_id] if log_id else []),
                    "printed": len(log_ids),
                },
            )
        log_ids.append(log_id)

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


# ──────────────────────────── batch print ────────────────────────────

class ApiBatchPrintRequest(BaseModel):
    # ``printer_id`` on the wire → ``printer`` attribute (see ApiPrintRequest).
    model_config = ConfigDict(populate_by_name=True)

    # Provide a list of cables and/or a single range/list string. Each entry
    # may itself be a range ("1.1-50") or list ("1.1,1.2,1.5") — expanded the
    # same way the operator search box does.
    cables: List[str] = Field(default_factory=list, description="e.g. ['1.1','1.2','1.5-1.8']")
    cable: Optional[str] = Field(None, description="Single range/list, e.g. '1.1-50'")
    bundle: Optional[str] = Field(
        None,
        description="Explicit bundle number to print (discipline must have bundle "
        "mode on). Usually unnecessary: for a bundle-mode discipline the normal "
        "group query 'N.*' in cables/cable already means BUNDLE #N.",
    )
    # Scope — same as the single-print endpoint.
    discipline_id: Optional[int] = None
    project: Optional[str] = None
    data_hall: Optional[str] = None
    discipline: Optional[str] = None
    reason: str = ""
    printer: Optional[str] = Field(
        None,
        alias="printer_id",
        description="Logical printer code (= printer name), e.g. 'WS1'. Sent as "
        "'printer_id'. Set by the calling workstation; overrides the template's "
        "printer. Whole batch prints to it. Omit → template default. Unknown → 404.",
    )
    stop_on_error: bool = Field(
        False, description="Stop the batch on the first printer/send error (default: continue)"
    )


class BatchItemResult(BaseModel):
    cable: str
    # printed | not_found | ambiguous | invalid | error | skipped
    status: str
    label_id: Optional[int] = None
    log_id: Optional[int] = None
    error: str = ""
    candidates: Optional[List[dict]] = None


class ApiBatchPrintResponse(BaseModel):
    ok: bool                 # True only if every requested cable printed
    requested: int
    printed: int
    discipline: str
    printer: str
    results: List[BatchItemResult]


def _expand_cables(req: ApiBatchPrintRequest) -> List[str]:
    """Flatten cables[] + cable into individual queries, de-duped, order-preserved."""
    raw: List[str] = [c for c in req.cables]
    if req.cable:
        raw.append(req.cable)
    out: List[str] = []
    seen: set[str] = set()
    for entry in raw:
        entry = entry.strip()
        if not entry:
            continue
        for q in parse_batch_query(entry):
            if q not in seen:
                seen.add(q)
                out.append(q)
    return out


def _requested_bundles(req: ApiBatchPrintRequest, bundle_mode: bool) -> List[str]:
    """Bundle numbers to print for this request.

    Explicit ``bundle`` wins. Otherwise, for a **bundle-mode** discipline, the
    caller's usual group query ``N.*`` / ``N.`` / ``N`` (in ``cables``/``cable``)
    is read as bundle N — so ACT keeps sending its normal format and ``1.*``
    simply means BUNDLE #1. Non-bundle disciplines return [] (cable path).
    """
    if req.bundle:
        return [req.bundle.strip()]
    if not bundle_mode:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for entry in list(req.cables) + ([req.cable] if req.cable else []):
        m = re.match(r"\s*#?\s*(\d+)", entry or "")
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def _print_bundles(
    bundle_nums: List[str], req: ApiBatchPrintRequest, disc: Discipline,
    template: Template, printer: Printer, key: ApiKey, session: Session,
) -> ApiBatchPrintResponse:
    """Print every label tagged with any of ``bundle_nums`` in this discipline."""
    labels = session.exec(
        select(Label)
        .where(Label.discipline_id == disc.id, Label.bundle.in_(bundle_nums))
        .order_by(Label.row_idx)
    ).all()
    if not labels:
        raise HTTPException(
            404,
            f"No labels for bundle(s) {', '.join(bundle_nums)} in "
            f"discipline '{disc.name}'",
        )
    operator = f"api:{key.name}"
    reason = req.reason or f"API bundle {','.join(bundle_nums)}"
    results: List[BatchItemResult] = []
    printed = 0
    problems = False
    aborted = False
    for label in labels:
        tok = _cable_token(label.left_text) or f"#{label.bundle}"
        if aborted:
            results.append(BatchItemResult(cable=tok, status="skipped"))
            problems = True
            continue
        log_id, err = _print_label(label, template, printer, operator, reason, session)
        if err:
            results.append(BatchItemResult(
                cable=tok, status="error", label_id=label.id, log_id=log_id, error=err
            ))
            problems = True
            if req.stop_on_error:
                aborted = True
        else:
            printed += 1
            results.append(BatchItemResult(
                cable=tok, status="printed", label_id=label.id, log_id=log_id
            ))
    return ApiBatchPrintResponse(
        ok=not problems, requested=len(labels), printed=printed,
        discipline=disc.name, printer=f"{printer.ip}:{printer.port}", results=results,
    )


@router.post("/print-batch", response_model=ApiBatchPrintResponse)
def api_print_batch(
    req: ApiBatchPrintRequest,
    session: Session = Depends(get_session),
    key: ApiKey = Security(require_api_key),
) -> ApiBatchPrintResponse:
    """Print many cables of ONE discipline in a single call.

    Expands ranges/lists (``'1.1-50'`` → 50 cables), prints each, and returns a
    per-cable report. Cables that don't resolve to exactly one label are
    reported (``not_found`` / ``ambiguous``) and skipped — they don't abort the
    run unless ``stop_on_error`` is set (which only applies to printer/send
    failures, not lookup misses).
    """
    disc = _resolve_discipline(req, session)
    template, printer = _discipline_printer(disc, session, req.printer)

    # Bundle selection: explicit `bundle`, or — for a bundle-mode discipline —
    # the caller's usual group query "N.*" read as bundle N (ACT sends its
    # normal format, no change on their side). Empty → normal cable path.
    bundle_nums = _requested_bundles(req, disc.bundle_mode)
    if bundle_nums:
        return _print_bundles(bundle_nums, req, disc, template, printer, key, session)

    queries = _expand_cables(req)
    if not queries:
        raise HTTPException(400, "Provide 'cables' and/or 'cable'")
    if len(queries) > MAX_BATCH:
        raise HTTPException(
            400, f"Batch too large: {len(queries)} cables (max {MAX_BATCH})"
        )

    labels = session.exec(select(Label).where(Label.discipline_id == disc.id)).all()
    operator = f"api:{key.name}"
    reason = req.reason or "API batch"

    results: List[BatchItemResult] = []
    printed = 0
    aborted = False
    problems = False

    for q in queries:
        if aborted:
            results.append(BatchItemResult(cable=q, status="skipped"))
            problems = True
            continue

        status, hits = _match_cable(labels, q)
        if status == "invalid":
            results.append(BatchItemResult(cable=q, status="invalid"))
            problems = True
            continue
        if not hits:
            results.append(BatchItemResult(cable=q, status="not_found"))
            problems = True
            continue

        # A group query ("20.*") legitimately resolves to many labels — print
        # them all. A plain query matching >1 label is ambiguous and skipped.
        is_group = bool(GROUP_RE.fullmatch(q))
        if len(hits) > 1 and not is_group:
            results.append(
                BatchItemResult(cable=q, status="ambiguous", candidates=_candidates(hits))
            )
            problems = True
            continue

        for label in hits:
            cable_label = (_cable_token(label.left_text) or q) if is_group else q
            log_id, err = _print_label(label, template, printer, operator, reason, session)
            if err:
                results.append(
                    BatchItemResult(cable=cable_label, status="error", label_id=label.id, log_id=log_id, error=err)
                )
                problems = True
                if req.stop_on_error:
                    aborted = True
                    break
            else:
                printed += 1
                results.append(
                    BatchItemResult(cable=cable_label, status="printed", label_id=label.id, log_id=log_id)
                )

    return ApiBatchPrintResponse(
        ok=not problems,
        requested=len(queries),
        printed=printed,
        discipline=disc.name,
        printer=f"{printer.ip}:{printer.port}",
        results=results,
    )
