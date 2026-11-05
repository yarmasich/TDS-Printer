"""Single QR label operations; separate admin and machine authentication."""
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Security
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session

from ..auth_admin import require_admin
from ..auth_apikey import require_legacy_print
from ..db import get_session
from ..models import ApiKey, Printer, PrintLog
from ..print_idempotency import run_print_request
from ..printer import PrintError
from ..printer_brother import build_qr_job, require_brother, send_brother_job
from ..qr_labels import QrLabelRequest, preview_png

router = APIRouter(prefix='/api/qr-labels', tags=['QR labels'])
integration_router = APIRouter(prefix='/api/v1/qr-labels', tags=['integrations'])


class QrLabelResult(BaseModel):
    code: str = 'sent'
    message: str = 'Sent to printer; check physical label.'
    log_id: int
    printer_id: int
    scan: str


def _printer(req: QrLabelRequest, session: Session) -> Printer:
    row = session.get(Printer, req.printer_id)
    if not row:
        raise HTTPException(404, detail={'code': 'error_not_sent', 'message': 'Printer not found'})
    try:
        require_brother(row)
    except PrintError as exc:
        raise HTTPException(400, detail={'code': 'error_not_sent', 'message': str(exc)}) from exc
    # Freeze routing for this intent. A later commit must not refresh a changed address.
    return Printer(**row.model_dump())


def _preview(req: QrLabelRequest, session: Session):
    _printer(req, session)
    try:
        return Response(preview_png(req), media_type='image/png', headers={'Cache-Control': 'no-store'})
    except PrintError as exc:
        raise HTTPException(400, detail={'code': 'error_not_sent', 'message': str(exc)}) from exc


def _submit(req, token, credential, session, endpoint):
    if token is None:
        raise HTTPException(428, detail={'code': 'key_required', 'message': 'Idempotency-Key is required'})
    if not token or len(token) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise HTTPException(400, detail={'code': 'invalid_key', 'message': 'Idempotency-Key must contain 1–200 visible ASCII characters'})

    def operation():
        printer = _printer(req, session)
        try:
            payload = build_qr_job(req, printer)
        except PrintError as exc:
            raise HTTPException(400, detail={'code': 'error_not_sent', 'message': str(exc)}) from exc
        log = PrintLog(label_kind='qr', qr_scan=req.scan, media_code=req.media,
                       printer_model=printer.model, source_reference=req.reference,
                       template_name='QR label', printer_name=printer.name,
                       printer_ip=f'{printer.ip}:{printer.port}',
                       operator=credential.name, operator_source='api' if endpoint.startswith('/api/v1') else 'admin',
                       status='sending')
        session.add(log)
        session.commit()  # A crash cannot erase the fact that this attempt began.
        session.refresh(log)
        try:
            send_brother_job(printer, payload)
        except PrintError as exc:
            log.status = 'uncertain' if exc.uncertain else 'error'
            log.error = str(exc)
            session.add(log)
            session.commit()
            raise HTTPException(502, detail={'code': 'uncertain' if exc.uncertain else 'error_not_sent',
                                            'message': str(exc), 'log_id': log.id, 'scan': req.scan}) from exc
        log.status = 'ok'  # Existing history convention: sent, not confirmed physical output.
        session.add(log)
        session.commit()
        return QrLabelResult(log_id=log.id, printer_id=printer.id, scan=req.scan)

    return run_print_request(endpoint, req, credential, token, session, operation, machine_codes=True)


def _admin_credential(username: str) -> ApiKey:
    # Never persisted. Distinct from real keys' 64-hex credential hashes.
    return ApiKey(name=username, prefix='admin-qr',
                  key_hash='admin-qr:' + hashlib.sha256(username.encode()).hexdigest())


@router.post('/preview')
def admin_preview(req: QrLabelRequest, session: Session = Depends(get_session),
                  username: str = Depends(require_admin)):
    return _preview(req, session)


@router.post('', response_model=QrLabelResult)
def admin_submit(req: QrLabelRequest, session: Session = Depends(get_session),
                 username: str = Depends(require_admin),
                 token: Annotated[str | None, Header(alias='Idempotency-Key')] = None):
    return _submit(req, token, _admin_credential(username), session, '/api/qr-labels')


@integration_router.post('/preview')
def api_preview(req: QrLabelRequest, session: Session = Depends(get_session),
                key: ApiKey = Security(require_legacy_print)):
    return _preview(req, session)


@integration_router.post('', response_model=QrLabelResult)
def api_submit(req: QrLabelRequest, session: Session = Depends(get_session),
               key: ApiKey = Security(require_legacy_print),
               token: Annotated[str | None, Header(alias='Idempotency-Key')] = None):
    return _submit(req, token, key, session, '/api/v1/qr-labels')
