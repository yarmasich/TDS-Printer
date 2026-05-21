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


@router.get("/count")
def count(session: Session = Depends(get_session)) -> dict:
    n = session.exec(select(func.count()).select_from(Label)).one()
    return {"labels": n}


@router.get("/search", response_model=SearchResponse)
def search(
    q: str = Query(..., description="cable id, text, range '45.5-7' or list '45.5,6,7'"),
    project_id: Optional[int] = None,
    data_hall_id: Optional[int] = None,
    discipline_id: Optional[int] = None,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = Depends(get_session),
) -> SearchResponse:
    queries = parse_batch_query(q)

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

    candidates = session.exec(stmt).all()

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
                if len(matches) >= limit:
                    continue
                matches[label.id] = {
                    "label": label, "disc": disc, "hall": hall, "proj": proj,
                    "matched_left": ml, "matched_right": mr,
                }

    hits = [_hit(**m) for m in matches.values()]
    return SearchResponse(query=q, expanded=queries, hits=hits, total=len(hits))


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
