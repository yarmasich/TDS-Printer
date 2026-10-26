"""Station credentials and live authorization for operator routes."""
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Annotated, Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from .auth_admin import ALGORITHM, TOKEN_HOURS, _env_value, decode_admin_token
from .models import Station

OperatorCredentials = Annotated[Optional[HTTPAuthorizationCredentials], Depends(HTTPBearer(auto_error=False))]


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256':
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _secret() -> str:
    secret = _env_value('ADMIN_JWT_SECRET')
    if not secret:
        raise HTTPException(503, 'Station authentication is not configured')
    return secret


def create_station_token(station: Station) -> str:
    return jwt.encode({'sub': str(station.id), 'scope': 'station', 'version': station.session_version,
                       'exp': datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)},
                      _secret(), algorithm=ALGORITHM)


def stations_required(db: Session) -> bool:
    return db.exec(select(Station.id).limit(1)).first() is not None


def resolve_operator(db: Session, credentials, *, station_only: bool = False) -> Optional[Station]:
    # Direct function callers have no bearer; HTTP calls always use FastAPI's bearer extraction.
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        if station_only or stations_required(db):
            raise HTTPException(401, 'Station login required')
        return None
    if credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Invalid session')
    try:
        payload = jwt.decode(credentials.credentials, _secret(), algorithms=[ALGORITHM], options={'require': ['exp', 'sub', 'scope']})
    except jwt.PyJWTError as exc:
        raise HTTPException(401, 'Invalid or expired session') from exc
    if payload.get('scope') == 'admin' and not station_only:
        decode_admin_token(credentials.credentials)
        return None
    if payload.get('scope') != 'station':
        raise HTTPException(401, 'Station login required')
    try:
        station_id = int(payload['sub'])
    except (ValueError, TypeError):
        raise HTTPException(401, 'Invalid session')
    station = db.get(Station, station_id, populate_existing=True)
    if not station or not station.enabled or payload.get('version') != station.session_version:
        raise HTTPException(401, 'Station session revoked; log in again')
    return station


def cart_sid(sid: str, station: Optional[Station]) -> str:
    if station:
        return 'station:' + str(station.id) + ':' + hashlib.sha256(sid.encode()).hexdigest()
    # Prevent legacy/admin callers from selecting a station namespace verbatim.
    if sid.startswith('station:'):
        raise HTTPException(400, 'Invalid cart session')
    return sid


def station_audit(station: Optional[Station]) -> dict:
    return {'station_id': station.id, 'station_name': station.display_name} if station else {}
