"""Server-only RFID identity resolution; never log or persist scanned codes."""
from dataclasses import dataclass
from http.client import HTTPException as HTTPProtocolError
import ipaddress
import json
import os
import string
import math
import time
import unicodedata
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import HTTPException
from sqlmodel import Session

from .models import DataHall, Discipline, Label, Project


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api_url() -> str:
    url = os.getenv('RFID_API_URL', '').strip()
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if not host or parts.username or parts.password or parts.fragment or parts.query:
            return ''
        _ = parts.port
        loopback = host == 'localhost'
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if parts.scheme != 'https' and not (parts.scheme == 'http' and loopback):
            return ''
        return url
    except ValueError:
        return ''


def configured() -> bool:
    return bool(_api_url() and os.getenv('RFID_API_TOKEN', '').strip())


_cooldowns: dict[str, float] = {}
_cooldown_lock = Lock()


def normalize_card(code: str | None) -> str:
    if not isinstance(code, str) or not code or len(code) > 256:
        raise HTTPException(403, 'Scan a valid RFID card before printing.')
    normalized = ''.join(char for char in code if not char.isspace() and char not in string.punctuation and not unicodedata.category(char).startswith('P'))
    if not normalized or len(normalized) > 64 or not normalized.isascii() or not normalized.isalnum():
        raise HTTPException(403, 'Scan a valid RFID card before printing.')
    return normalized.upper()


def _unavailable() -> HTTPException:
    return HTTPException(503, 'RFID verification is unavailable. Try again later.')


def _rate_limited(seconds: int) -> HTTPException:
    return HTTPException(503, 'RFID directory is busy. Wait before scanning again.', headers={'Retry-After': str(seconds)})


def resolve_employee(code: str | None) -> 'OperatorIdentity':
    url = _api_url()
    token = os.getenv('RFID_API_TOKEN', '').strip()
    if not url or not token:
        raise HTTPException(503, 'RFID verification is not configured on the server.')
    code = normalize_card(code)
    with _cooldown_lock:
        remaining = math.ceil(_cooldowns.get(url, 0) - time.monotonic())
    if remaining > 0:
        raise _rate_limited(remaining)
    headers = {'Accept': 'application/json', 'Cache-Control': 'no-store',
               'Authorization': f'Bearer {token}'}
    # Local project IDs have no mapping to directory project IDs.
    query = urlencode({'rfid': code, 'active': 'true', 'limit': 2, 'offset': 0})
    request = Request(url + '?' + query, headers=headers, method='GET')
    try:
        # Redirects are forbidden so bearer credentials cannot move to another host.
        with build_opener(_NoRedirect()).open(request, timeout=5) as response:
            if response.status != 200:
                raise _unavailable()
            payload = response.read(16385)
        if len(payload) > 16384:
            raise ValueError('Response too large')
        data = json.loads(payload)
        if not isinstance(data, dict) or type(data.get('total')) is not int or not isinstance(data.get('items'), list):
            raise _unavailable()
        total, items = data['total'], data['items']
        if total == 0 and not items:
            raise HTTPException(403, 'No active employee was found for this RFID card.')
        if total > 1:
            raise HTTPException(403, 'This RFID card matches multiple employees. Contact an administrator.')
        if total != 1 or len(items) != 1 or not isinstance(items[0], dict):
            raise _unavailable()
        employee = items[0]
        name, employee_id = employee.get('full_name'), employee.get('employee_id')
        for value in (name, employee_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
                raise _unavailable()
        if employee.get('active') is not True:
            raise HTTPException(403, 'This employee is not active. Printing was blocked.')
        try:
            returned_card = normalize_card(employee.get('rfid'))
        except HTTPException:
            raise _unavailable() from None
        if returned_card != code:
            raise _unavailable()
        return OperatorIdentity(name.strip(), 'rfid', True, employee_id)
    except HTTPError as exc:
        if exc.code == 429:
            try:
                delay = max(1, min(300, int(exc.headers.get('Retry-After', '60'))))
            except (ValueError, TypeError, AttributeError):
                delay = 60
            with _cooldown_lock:
                _cooldowns[url] = time.monotonic() + delay
            raise _rate_limited(delay) from None
        # Credential/scope/route/parameter errors must not be presented as an unknown card.
        raise _unavailable() from None
    except (URLError, OSError, ValueError, HTTPProtocolError):
        raise _unavailable() from None


def resolve_full_name(code: str | None) -> str:
    """Compatibility helper; printing uses the complete stable employee identity."""
    return resolve_employee(code).name


def project_for_label(session: Session, label: Label | None) -> Project:
    disc = session.get(Discipline, label.discipline_id) if label else None
    hall = session.get(DataHall, disc.data_hall_id) if disc else None
    project = session.get(Project, hall.project_id) if hall else None
    if project is None:
        raise HTTPException(409, 'Label project is missing; refresh the cart before printing.')
    return project


@dataclass(frozen=True)
class OperatorIdentity:
    name: str
    source: str = 'manual'
    verified: bool = False
    employee_id: str | None = None

    def audit(self, project: Project | None = None) -> dict:
        return dict(operator=self.name, operator_source=self.source,
                    operator_verified=self.verified, operator_employee_id=self.employee_id, project_id=project.id if project else None,
                    project_name=project.name if project else '')


def identify(projects: list[Project], code: str | None, fallback: str, source: str = 'manual') -> OperatorIdentity:
    if any(project.require_rfid for project in projects) or code:
        return resolve_employee(code)
    return OperatorIdentity(fallback, source)
