"""Admin station provisioning and separate operator sign-in."""
import secrets
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from ..auth_admin import require_admin
from ..auth_station import (OperatorCredentials, create_station_token, hash_password,
                            verify_password, resolve_operator, stations_required)
from ..db import get_session
from ..login_limits import LoginLimiter
from ..models import Printer, Station, StationPrinter
from ..station_routing import allowed_printers

router = APIRouter(prefix='/api/stations', tags=['stations'], dependencies=[Depends(require_admin)])
auth_router = APIRouter(prefix='/api/station-auth', tags=['station-auth'])
login_limiter = LoginLimiter()

class StationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    username: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=256)
    printer_ids: list[int] = Field(min_length=1)
    default_printer_id: int | None = None
    enabled: bool = True

class StationPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str | None = Field(default=None, min_length=1, max_length=100)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    printer_ids: list[int] | None = Field(default=None, min_length=1)
    default_printer_id: int | None = None
    enabled: bool | None = None

class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)

def dto(row, db):
    return dict(id=row.id, username=row.username, display_name=row.display_name, enabled=row.enabled,
                default_printer_id=row.default_printer_id,
                allowed_printers=[dict(id=printer.id, name=printer.name)
                                  for printer in allowed_printers(db, row.id).values()])


def save(row, db, printer_ids=None, *, default_changed=False):
    if not row.username.strip() or not row.display_name.strip():
        raise HTTPException(422, 'Username and station name cannot be blank')
    row.username = row.username.strip()
    row.display_name = row.display_name.strip()
    db.add(row)
    try:
        if printer_ids is not None or default_changed:
            db.flush()
            # Serialize configuration replacements even when station fields are unchanged.
            db.execute(update(Station).where(Station.id == row.id).values(id=Station.id))
        if printer_ids is not None:
            desired = set(printer_ids)
            with db.no_autoflush:
                printers = db.exec(select(Printer).where(Printer.id.in_(desired))).all()
            if len(printers) != len(desired) or any(printer.protocol == 'brother_ql' for printer in printers):
                raise HTTPException(422, 'Allowed printers must be existing cable label printers')
            existing = db.exec(select(StationPrinter).where(StationPrinter.station_id == row.id)).all()
            for assignment in existing:
                if assignment.printer_id in desired:
                    desired.remove(assignment.printer_id)
                else:
                    db.delete(assignment)
            db.add_all([StationPrinter(station_id=row.id, printer_id=printer_id) for printer_id in desired])
        if row.default_printer_id is not None and (printer_ids is not None or default_changed):
            db.flush()
            if not db.get(StationPrinter, (row.id, row.default_printer_id)):
                if default_changed:
                    raise HTTPException(422, 'Default printer must be allowed on this station')
                row.default_printer_id = None
        db.commit()
    except HTTPException:
        db.rollback()
        raise
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
    values = body.model_dump(exclude={'password', 'printer_ids'})
    return save(Station(**values, password_hash=hash_password(body.password), session_version=secrets.token_hex(16)), db, body.printer_ids, default_changed=True)

@router.patch('/{station_id}')
def update_station(station_id: int, body: StationPatch, db: Session = Depends(get_session)):
    row = db.get(Station, station_id)
    if not row:
        raise HTTPException(404, 'Station not found')
    values = body.model_dump(exclude_unset=True)
    if any(value is None for key, value in values.items() if key != "default_printer_id"):
        raise HTTPException(422, 'Station fields cannot be null')
    values.pop('printer_ids', None)
    password = values.pop('password', None)
    if password:
        row.password_hash = hash_password(password)
    # Revoke old tokens on password changes or disabling (including later re-enabling).
    if password or values.get('enabled') is False:
        row.session_version = secrets.token_hex(16)
    for key, value in values.items():
        setattr(row, key, value)
    return save(row, db, body.printer_ids,
                default_changed="default_printer_id" in values)

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
