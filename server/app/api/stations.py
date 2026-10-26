"""Admin station provisioning and separate operator sign-in."""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from ..auth_admin import require_admin
from ..auth_station import (OperatorCredentials, create_station_token, hash_password,
                            verify_password, resolve_operator, stations_required)
from ..db import get_session
from ..login_limits import LoginLimiter
from ..models import Printer, Station

router = APIRouter(prefix='/api/stations', tags=['stations'], dependencies=[Depends(require_admin)])
auth_router = APIRouter(prefix='/api/station-auth', tags=['station-auth'])
login_limiter = LoginLimiter()

class StationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=256)
    printer_id: int
    enabled: bool = True

class StationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str | None = Field(default=None, min_length=1, max_length=100)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    printer_id: int | None = None
    enabled: bool | None = None

class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)

def dto(row, db):
    printer = db.get(Printer, row.printer_id)
    return dict(id=row.id, username=row.username, display_name=row.display_name,
                printer_id=row.printer_id, printer_name=printer.name if printer else None, enabled=row.enabled)

def save(row, db):
    if not row.username.strip() or not row.display_name.strip():
        raise HTTPException(422, 'Username and station name cannot be blank')
    row.username = row.username.strip()
    row.display_name = row.display_name.strip()
    with db.no_autoflush:
        if not db.get(Printer, row.printer_id):
            raise HTTPException(422, 'Assigned printer does not exist')
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Station username already exists or printer is unavailable') from exc
    db.refresh(row)
    return dto(row, db)

@router.get('')
def list_stations(db: Session = Depends(get_session)):
    return [dto(row, db) for row in db.exec(select(Station).order_by(Station.display_name)).all()]

@router.post('')
def create_station(body: StationCreate, db: Session = Depends(get_session)):
    values = body.model_dump(exclude={'password'})
    return save(Station(**values, password_hash=hash_password(body.password), session_version=secrets.token_hex(16)), db)

@router.patch('/{station_id}')
def update_station(station_id: int, body: StationPatch, db: Session = Depends(get_session)):
    row = db.get(Station, station_id)
    if not row:
        raise HTTPException(404, 'Station not found')
    values = body.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(422, 'Station fields cannot be null')
    password = values.pop('password', None)
    if password:
        row.password_hash = hash_password(password)
    # Revoke old tokens on password changes or disabling (including later re-enabling).
    if password or values.get('enabled') is False:
        row.session_version = secrets.token_hex(16)
    for key, value in values.items():
        setattr(row, key, value)
    return save(row, db)

@auth_router.get('/status')
def status(db: Session = Depends(get_session)):
    return {'required': stations_required(db)}

@auth_router.post('/login')
def login(body: Login, request: Request, db: Session = Depends(get_session)):
    client = request.client.host if request.client else 'unknown'
    retry = login_limiter.retry_after(client)
    if retry:
        raise HTTPException(429, 'Too many login attempts. Try again later.', headers={'Retry-After': str(retry)})
    station = db.exec(select(Station).where(Station.username == body.username.strip())).first()
    # Do the expensive hash even for missing users to reduce account enumeration.
    valid = verify_password(body.password, station.password_hash) if station else (hash_password(body.password) and False)
    if not valid or not station.enabled:
        raise HTTPException(401, 'Invalid username or password')
    return {'access_token': create_station_token(station), 'token_type': 'bearer', 'station': dto(station, db)}

@auth_router.get('/me')
def me(db: Session = Depends(get_session), credentials: OperatorCredentials = None):
    return dto(resolve_operator(db, credentials, station_only=True), db)
