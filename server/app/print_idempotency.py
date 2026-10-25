"""At-most-once integration attempts, including across workers and restarts."""
import hashlib
import json
from typing import Callable

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from .models import ApiKey, IntegrationPrintRequest


def run_print_request(
    endpoint: str, request: BaseModel, key: ApiKey, token: str | None,
    session: Session, operation: Callable,
):
    if token is None:
        return operation()
    if not token.strip() or len(token) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise HTTPException(400, "Idempotency-Key must be 1–200 visible ASCII characters without spaces")
    canonical = json.dumps(
        {"endpoint": endpoint, "request": request.model_dump(mode="json")},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    scope = (key.key_hash, token)
    reservation = IntegrationPrintRequest(
        credential_hash=scope[0], idempotency_key=token, request_hash=digest,
    )
    session.add(reservation)
    try:
        # The unique primary key arbitrates concurrent requests. No physical
        # send is allowed until this reservation is durably committed.
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.get(IntegrationPrintRequest, scope)
        if existing is None:
            raise
        if existing.request_hash != digest:
            raise HTTPException(409, "Idempotency-Key was already used for a different request")
        if existing.state != "completed":
            raise HTTPException(409, "Print attempt is in progress or its outcome is unknown; inspect printer/history before any new attempt")
        return JSONResponse(existing.response_body, status_code=existing.status_code, headers=existing.response_headers)

    try:
        result = operation()
        body, status, headers = result.model_dump(mode="json"), 200, None
    except HTTPException as exc:
        body, status, headers = {"detail": exc.detail}, exc.status_code, exc.headers
    # Unexpected errors (including DB/logging failures after a send) deliberately
    # leave the committed reservation intact. Never release or retry it.
    reservation.state = "completed"
    reservation.response_body = body
    reservation.status_code = status
    reservation.response_headers = headers
    session.add(reservation)
    session.commit()
    return JSONResponse(body, status_code=status, headers=headers)
