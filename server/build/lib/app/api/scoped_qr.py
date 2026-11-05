"""Project-authorized QR labels; renderer and physical output share one bitmap."""
import base64
import hashlib
import io
from typing import Annotated
from uuid import UUID
from fastapi import Depends, Header, HTTPException, Security
from pydantic import Field
from sqlmodel import Session
from .scoped_integrations import router, find_policy, policy_dto, check_scope, require_integration, require_api_key, get_session, fail
from ..models import ApiKey, Printer, PrintLog
from ..qr_labels import QrLabelRequest, render_bitmap
from ..printer import PrintError
from ..printer_brother import require_brother, build_qr_job, send_brother_job
from ..print_idempotency import run_print_request

RENDERER_VERSION = 'preparation-qr-1'

class ScopedQrPreview(QrLabelRequest):
    media: str = Field(..., pattern=r'^DK-(2205|2246)$')
    length_mm: float = Field(..., ge=30, le=200, allow_inf_nan=False)

class ScopedQrSend(ScopedQrPreview):
    expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')

def bitmap(req):
    plain=QrLabelRequest.model_validate(req.model_dump(exclude={'expected_fingerprint'}))
    image=render_bitmap(plain)
    digest=hashlib.sha256(f'{RENDERER_VERSION}:{image.mode}:{image.width}:{image.height}:'.encode()+image.tobytes()).hexdigest()
    return plain,image,digest

def assigned(session,key,project,req):
    require_integration(session,key)
    row=find_policy(session,key.integration_id,project)
    if row is None: fail(400,'policy_missing')
    policy=policy_dto(session,project,row)
    if req.printer_id not in policy['qr_labels']['printer_ids']: fail(403,'printer_not_allowed')
    p=session.get(Printer,req.printer_id)
    if p is None: fail(403,'printer_not_allowed')
    try: require_brother(p)
    except PrintError: fail(400,'error_not_sent')
    return Printer(**p.model_dump()),row

@router.post('/projects/{external_project_id}/qr-labels/preview')
def preview(external_project_id:UUID,req:ScopedQrPreview,session:Session=Depends(get_session),key:ApiKey=Security(require_api_key)):
    check_scope(key,'policy.read' if 'policy.read' in key.scopes else 'print')
    assigned(session,key,external_project_id,req)
    try:
        _,image,digest=bitmap(req)
        output=io.BytesIO();image.save(output,format='PNG')
        return dict(png_base64=base64.b64encode(output.getvalue()).decode(),fingerprint=digest)
    except PrintError: fail(400,'error_not_sent')

@router.post('/projects/{external_project_id}/qr-labels')
def send(external_project_id:UUID,req:ScopedQrSend,session:Session=Depends(get_session),key:ApiKey=Security(require_api_key),
         token:Annotated[str|None,Header(alias='Idempotency-Key')]=None):
    check_scope(key,'print');require_integration(session,key)
    if not token: fail(400,'idempotency_key_required')
    def operation():
        try:
            printer,policy=assigned(session,key,external_project_id,req)
            plain,_,digest=bitmap(req)
            if digest!=req.expected_fingerprint: fail(409,'fingerprint_mismatch')
            raster=build_qr_job(plain,printer)
        except (HTTPException,PrintError) as exc:
            session.add(PrintLog(operator=f'api:{key.name}',operator_source='api',integration_id=key.integration_id,
                external_project_id=str(external_project_id),print_purpose='qr_labels',label_kind='qr',status='denied',reason='Scoped preparation QR',error='request_denied'))
            session.commit()
            if isinstance(exc,PrintError): fail(400,'error_not_sent')
            raise
        log=PrintLog(label_kind='qr',qr_scan=req.scan,media_code=req.media,printer_model=printer.model,source_reference=req.reference,
            template_name='QR label',printer_name=printer.name,operator=f'api:{key.name}',operator_source='api',status='sending',
            integration_id=key.integration_id,external_project_id=str(external_project_id),project_id=policy.tds_project_id,print_purpose='qr_labels')
        session.add(log);session.commit();session.refresh(log)
        try: send_brother_job(printer,raster)
        except PrintError as exc:
            log.status='uncertain' if exc.uncertain else 'error';log.error='Check printer before retrying';session.add(log);session.commit()
            fail(502,'uncertain' if exc.uncertain else 'error_not_sent')
        log.status='ok';session.add(log);session.commit()
        return dict(code='sent',message='Sent to printer; physical output not confirmed.',log_id=log.id,printer_id=printer.id,scan=req.scan)
    return run_print_request(f'/integrations/projects/{external_project_id}/qr-labels',req,key,token,session,operation,machine_codes=True,stable_integration=True)
