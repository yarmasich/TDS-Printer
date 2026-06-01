"""API-key auth for machine-to-machine access (external apps).

Separate from the admin JWT in ``auth_admin``: external systems send a static
key in the ``X-API-Key`` header rather than logging in. Keys live in the
``apikey`` table; we store only a SHA-256 hash and verify with a constant-time
compare. Issuing / revoking keys is done from the admin UI.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated, Optional, Tuple

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlmodel import Session, select

from .db import get_session
from .models import ApiKey

PREFIX = "tdsk"          # token namespace, e.g. ``tdsk_ab12cd34_<secret>``
PREFIX_LEN = 13          # stored display prefix: ``tdsk_ab12cd34``

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def generate_key() -> Tuple[str, str, str]:
    """Mint a new key. Returns ``(plaintext, prefix, sha256_hex)``.

    The plaintext is shown to the admin once and never stored. ``prefix`` is
    the leading, non-secret slice kept for display / lookup narrowing.
    """
    body = secrets.token_urlsafe(32)
    ident = secrets.token_hex(4)               # 8 hex chars for the display prefix
    plaintext = f"{PREFIX}_{ident}_{body}"
    prefix = plaintext[:PREFIX_LEN]
    return plaintext, prefix, hash_key(plaintext)


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def require_api_key(
    presented: Annotated[Optional[str], Security(_api_key_header)] = None,
    session: Session = Depends(get_session),
) -> ApiKey:
    """Validate ``X-API-Key`` and return the matching enabled ``ApiKey``.

    Touches ``last_used_at`` on success so the admin UI can show liveness.
    """
    if not presented:
        raise HTTPException(401, "Missing X-API-Key header")

    presented = presented.strip()
    digest = hash_key(presented)
    prefix = presented[:PREFIX_LEN]

    # Narrow by prefix (indexed), then constant-time compare the hash so a
    # forged prefix can't be probed by timing.
    candidates = session.exec(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.enabled == True)  # noqa: E712
    ).all()
    match = next(
        (k for k in candidates if secrets.compare_digest(k.key_hash, digest)),
        None,
    )
    if match is None:
        raise HTTPException(401, "Invalid or revoked API key")

    match.last_used_at = datetime.now(timezone.utc)
    session.add(match)
    session.commit()
    return match
