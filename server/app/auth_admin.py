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


def _env_value(key: str, *, strip_outer: bool = True) -> str:
    """Read env; strip accidental quotes from ``.env`` copy-paste."""
    raw = os.getenv(key, "")
    if not raw:
        return ""
    val = raw.strip() if strip_outer else raw
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    return val


def _credentials() -> Optional[tuple[str, str, str]]:
    user = _env_value("ADMIN_USERNAME")
    # Do not strip spaces inside passwords — only CR/LF from the line end.
    password = os.getenv("ADMIN_PASSWORD", "").strip("\r\n")
    if password.startswith('"') and password.endswith('"') and len(password) >= 2:
        password = password[1:-1]
    elif password.startswith("'") and password.endswith("'") and len(password) >= 2:
        password = password[1:-1]
    secret = _env_value("ADMIN_JWT_SECRET")
    if not user or not password or not secret:
        return None
    return user, password, secret


def _eq_str(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def admin_auth_configured() -> bool:
    return _credentials() is not None


def verify_admin_login(username: str, password: str) -> bool:
    cfg = _credentials()
    if not cfg:
        return False
    expected_user, expected_pass, _ = cfg
    return _eq_str(username.strip(), expected_user) and _eq_str(password, expected_pass)


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
