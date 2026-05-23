"""Admin login (env credentials) and JWT guard for mutating / setup APIs."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALGORITHM = "HS256"
TOKEN_HOURS = 12

_bearer = HTTPBearer(auto_error=False)


def _credentials() -> Optional[tuple[str, str, str]]:
    user = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    secret = os.getenv("ADMIN_JWT_SECRET", "").strip()
    if not user or not password or not secret:
        return None
    return user, password, secret


def admin_auth_configured() -> bool:
    return _credentials() is not None


def verify_admin_login(username: str, password: str) -> bool:
    cfg = _credentials()
    if not cfg:
        return False
    expected_user, expected_pass, _ = cfg
    user_ok = secrets.compare_digest(username.strip(), expected_user)
    pass_ok = secrets.compare_digest(password, expected_pass)
    return user_ok and pass_ok


def create_admin_token(username: str) -> str:
    cfg = _credentials()
    if not cfg:
        raise HTTPException(503, "Admin auth is not configured on the server")
    _, _, secret = cfg
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    return jwt.encode(
        {"sub": username, "exp": exp, "scope": "admin"},
        secret,
        algorithm=ALGORITHM,
    )


def decode_admin_token(token: str) -> dict:
    cfg = _credentials()
    if not cfg:
        raise HTTPException(503, "Admin auth is not configured on the server")
    _, _, secret = cfg
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(401, "Invalid or expired session") from e
    if payload.get("scope") != "admin":
        raise HTTPException(401, "Invalid token scope")
    return payload


async def require_admin(
    creds: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(_bearer)
    ] = None,
) -> str:
    if not admin_auth_configured():
        raise HTTPException(
            503,
            "Set ADMIN_USERNAME, ADMIN_PASSWORD, and ADMIN_JWT_SECRET on the server",
        )
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(401, "Admin login required")
    payload = decode_admin_token(creds.credentials)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, "Invalid token")
    return str(sub)
