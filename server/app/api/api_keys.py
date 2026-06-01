"""Admin CRUD for machine-to-machine API keys.

The plaintext key is returned **once**, at creation — afterwards only its
metadata (name, prefix, enabled, timestamps) is ever exposed. All routes are
admin-only (mounted with ``require_admin`` in ``main.py``).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth_apikey import generate_key
from ..db import get_session
from ..models import ApiKey

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


class ApiKeyDTO(BaseModel):
    """Safe view — never includes the secret."""
    id: int
    name: str
    prefix: str
    enabled: bool
    created_at: datetime
    last_used_at: Optional[datetime]


class ApiKeyCreated(ApiKeyDTO):
    """Returned only from POST — carries the plaintext key once."""
    key: str


class CreateApiKeyRequest(BaseModel):
    name: str


class UpdateApiKeyRequest(BaseModel):
    enabled: bool


def _dto(k: ApiKey) -> ApiKeyDTO:
    return ApiKeyDTO(
        id=k.id,
        name=k.name,
        prefix=k.prefix,
        enabled=k.enabled,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
    )


@router.get("", response_model=List[ApiKeyDTO])
def list_keys(session: Session = Depends(get_session)) -> List[ApiKeyDTO]:
    keys = session.exec(select(ApiKey).order_by(ApiKey.created_at.desc())).all()
    return [_dto(k) for k in keys]


@router.post("", response_model=ApiKeyCreated)
def create_key(
    req: CreateApiKeyRequest, session: Session = Depends(get_session)
) -> ApiKeyCreated:
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    if session.exec(select(ApiKey).where(ApiKey.name == name)).first():
        raise HTTPException(409, f"An API key named '{name}' already exists")

    plaintext, prefix, key_hash = generate_key()
    key = ApiKey(name=name, prefix=prefix, key_hash=key_hash)
    session.add(key)
    session.commit()
    session.refresh(key)
    return ApiKeyCreated(**_dto(key).model_dump(), key=plaintext)


@router.put("/{key_id}", response_model=ApiKeyDTO)
def update_key(
    key_id: int, req: UpdateApiKeyRequest, session: Session = Depends(get_session)
) -> ApiKeyDTO:
    key = session.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API key not found")
    key.enabled = req.enabled
    session.add(key)
    session.commit()
    session.refresh(key)
    return _dto(key)


@router.delete("/{key_id}")
def delete_key(key_id: int, session: Session = Depends(get_session)) -> dict:
    key = session.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "API key not found")
    session.delete(key)
    session.commit()
    return {"deleted": key_id}
