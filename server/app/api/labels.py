"""Label search.

After the refactor, labels live under a discipline (FK). The search endpoint
filters by ``project_id`` and / or ``discipline_id`` (typical workflow:
the operator picks a project and a discipline on the main page, then types
a cable number).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from ..auth_station import OperatorCredentials, resolve_operator
from ..db import get_session
from ..models import DataHall, Discipline, Label, Project
from ..search import cable_query_pattern, parse_batch_query, validate_query

router = APIRouter(prefix="/api/labels", tags=["labels"])


class SearchHit(BaseModel):
    label_id: int
    discipline_id: int
    discipline_name: str
    project_name: str
    data_hall_name: str
    sheet_name: str
    row_idx: int
    left_text: str
    right_text: str
    matched_left: bool
    matched_right: bool


class SearchResponse(BaseModel):
    query: str
    expanded: List[str]
    hits: List[SearchHit]
    total: int
    truncated: bool = False
    offset: int = 0


class BundleDTO(BaseModel):
    bundle: str
    count: int


@router.get("/count")
def count(session: Session = Depends(get_session)) -> dict:
    n = session.exec(select(func.count()).select_from(Label)).one()
    return {"labels": n}


@router.get("/bundles", response_model=List[BundleDTO])
def bundles(
    discipline_id: int, session: Session = Depends(get_session)
) -> List[BundleDTO]:
    """Distinct bundles (with label counts) in a discipline — for the picker."""
    rows = session.exec(
        select(Label.bundle, func.count())
        .where(Label.discipline_id == discipline_id, Label.bundle.is_not(None))
        .group_by(Label.bundle)
    ).all()
    out = [BundleDTO(bundle=b, count=c) for b, c in rows if b]
    # Numeric order when the bundle is a plain number; text otherwise.
    out.sort(key=lambda x: (0, int(x.bundle)) if x.bundle.isdigit() else (1, x.bundle))
    return out


@router.get("/by-bundle", response_model=SearchResponse)
def by_bundle(
    discipline_id: int, bundle: str, session: Session = Depends(get_session)
) -> SearchResponse:
    """Every label of one bundle, in sheet order — same shape as /search so the
    Print page can reuse its results list."""
    stmt = (
        select(Label, Discipline, DataHall, Project)
        .join(Discipline, Label.discipline_id == Discipline.id)
        .join(DataHall, Discipline.data_hall_id == DataHall.id)
        .join(Project, DataHall.project_id == Project.id)
        .where(Discipline.id == discipline_id, Label.bundle == bundle)
        .order_by(Label.row_idx)
    )
    rows = session.exec(stmt).all()
    hits = [
        _hit(label=l, disc=d, hall=h, proj=p, matched_left=True, matched_right=True)
        for l, d, h, p in rows
    ]
    return SearchResponse(query=f"BUNDLE #{bundle}", expanded=[], hits=hits, total=len(hits))


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., description="cable id, text, range '45.5-7' or list '45.5,6,7'"),
    project_id: Optional[int] = None,
    data_hall_id: Optional[int] = None,
    discipline_id: Optional[int] = None,
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> SearchResponse:
    try:
        queries = parse_batch_query(q)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    stmt = select(Label, Discipline, DataHall, Project).join(
        Discipline, Label.discipline_id == Discipline.id
    ).join(
        DataHall, Discipline.data_hall_id == DataHall.id
    ).join(
        Project, DataHall.project_id == Project.id
    )
    if discipline_id is not None:
        stmt = stmt.where(Discipline.id == discipline_id)
    if data_hall_id is not None:
        stmt = stmt.where(DataHall.id == data_hall_id)
    if project_id is not None:
        stmt = stmt.where(Project.id == project_id)

    candidates = session.exec(stmt.order_by(Label.id)).all()

    # One row → one hit. We OR the matched_left/matched_right flags across
    # all expanded query tokens so a batch like ``45.5-7`` collapses to a
    # single hit per cable row that already contains several of the matches.
    matches: dict[int, dict] = {}  # ordered by first appearance

    for single in queries:
        ok, single = validate_query(single)
        if not ok:
            continue
        pat = cable_query_pattern(single)
        for label, disc, hall, proj in candidates:
            existing = matches.get(label.id)
            ml = existing["matched_left"] if existing else False
            mr = existing["matched_right"] if existing else False

            if not ml and label.left_text and pat.search(label.left_text):
                ml = True
            if not mr and label.right_text and pat.search(label.right_text):
                mr = True

            if not (ml or mr):
                continue
            if existing:
                existing["matched_left"] = ml
                existing["matched_right"] = mr
            else:
                matches[label.id] = {
                    "label": label, "disc": disc, "hall": hall, "proj": proj,
                    "matched_left": ml, "matched_right": mr,
                }

    total = len(matches)
    hits = [_hit(**m) for m in list(matches.values())[offset:offset + limit]]
    return SearchResponse(query=q, expanded=queries, hits=hits, total=total,
                          truncated=offset + len(hits) < total, offset=offset)


def _hit(
    label: Label, disc: Discipline, hall: DataHall, proj: Project,
    matched_left: bool, matched_right: bool,
) -> SearchHit:
    return SearchHit(
        label_id=label.id,
        discipline_id=disc.id,
        discipline_name=disc.name,
        project_name=proj.name,
        data_hall_name=hall.name,
        sheet_name=label.sheet_name,
        row_idx=label.row_idx,
        left_text=label.left_text,
        right_text=label.right_text,
        matched_left=matched_left,
        matched_right=matched_right,
    )


@router.get('/{label_id}/preview')
def label_preview(label_id: int, session: Session = Depends(get_session), credentials: OperatorCredentials = None):
    """Operator preview of a stored label only; no draft input or printer send."""
    import base64
    import re
    from ..models import Printer, Template
    from ..calibration import render_preview_png
    from ..label_geometry import is_turn_tell_300
    from ..materials import get_material
    from ..printer import PrintError

    station = resolve_operator(session, credentials)
    label = session.get(Label, label_id)
    if not label:
        raise HTTPException(404, 'Label not found')
    discipline = session.get(Discipline, label.discipline_id)
    template = session.get(Template, discipline.template_id) if discipline and discipline.template_id else None
    if not template:
        raise HTTPException(400, 'No template assigned to this discipline')
    printer = session.get(Printer, station.printer_id if station else template.printer_id)
    if not printer:
        raise HTTPException(400, 'No printer assigned to this template')
    try:
        png = render_preview_png(template, label.left_text or '', label.right_text or '', printer=printer)
    except PrintError as exc:
        raise HTTPException(400, str(exc)) from exc
    width = template.bytes_per_row * 8
    areas = []
    turn = is_turn_tell_300(template)
    for i, name in enumerate(('Left', 'Right')):
        side = ('right' if i == 0 else 'left') if turn else name.lower()
        x0, x1 = getattr(template, side+'_left'), getattr(template, side+'_right')
        y0, y1 = getattr(template, side+'_top'), getattr(template, side+'_bottom')
        areas.append(dict(label=name, x=width-x1 if turn else x0, y=y0,
                          width=max(1,x1-x0), height=max(1,y1-y0)))
    material = None
    sku = template.material_sku.strip().upper()
    match = re.fullmatch(r'R(\d{3})X(\d{3})V(\d+)T', sku)
    colors = {'1':'#ffffff', '2':'#0072c6', '3':'#2e8b57', '7':'#c8102e', '8':'#ffd400'}
    if match and match[3] in colors:
        try:
            stock = get_material(sku)
            if stock.supported:
                material = dict(width_mm=round(int(match[1])*0.254,3),
                                height_mm=round(int(match[2])*0.254,3),
                                print_height_mm=stock.print_height_mm, color=colors[match[3]])
        except KeyError:
            pass
    return dict(image='data:image/png;base64,'+base64.b64encode(png).decode('ascii'),
                width=width, height=template.height, material_sku=sku,
                areas=areas, material=material)
