"""Project-authorized QR labels; renderer and physical output share one bitmap."""
import base64
import binascii
import hashlib
import io
import json
import re
from typing import Annotated, Literal
from uuid import UUID
from fastapi import Depends, Header, HTTPException, Security
from PIL import Image
from pydantic import BaseModel, Field, model_serializer
from fastapi.responses import JSONResponse
from sqlmodel import Session
from .scoped_integrations import router, find_policy, policy_dto, check_scope, require_integration, require_api_key, get_session, fail
from ..models import ApiKey, Printer, PrintLog
from ..qr_labels import MEDIA, QrLabelRequest, render_bitmap
from ..printer import PrintError
from ..printer_brother import require_brother, build_qr_job, send_brother_job, PrinterNotReady
from ..print_idempotency import run_print_request

RENDERER_VERSION = 'preparation-qr-1'
PACKING_WIDTH = MEDIA['DK-2246'][1]
PACKING_ROW_BYTES = PACKING_WIDTH // 8
MAX_BITMAP_BASE64 = 4 * ((PACKING_ROW_BYTES * round(200 * 300 / 25.4) + 2) // 3)
MAX_PREVIEW_JSON = 256 * 1024

class ScopedQrPreview(QrLabelRequest):
    media: str = Field(..., pattern=r'^DK-(2205|2246)$')
    length_mm: float = Field(..., ge=30, le=200, allow_inf_nan=False)

    bitmap_1bpp_base64: str | None = Field(default=None, max_length=MAX_BITMAP_BASE64, repr=False)

    @model_serializer(mode='wrap')
    def serialize_request(self, handler):
        # Preserve idempotency hashes recorded before bitmap support.
        fields = handler(self)
        if self.bitmap_1bpp_base64 is None:
            fields.pop('bitmap_1bpp_base64', None)
        return fields


class ScopedQrSend(ScopedQrPreview):
    expected_fingerprint: str = Field(pattern=r'^[0-9a-f]{64}$')

class ScopedQrResult(BaseModel):
    code: str
    message: str
    log_id: int
    printer_id: int
    scan: str
    print_observation: Literal['counter_advanced', 'unconfirmed'] = 'unconfirmed'

class PackingQrResult(ScopedQrResult):
    bitmap_fingerprint: str


def packing_bitmap(req, encoded):
    if (req.media != 'DK-2246' or req.description or
            not re.fullmatch(r'inventory-packing:(box|pallet):[^:]+', req.reference)):
        raise PrintError('Bitmap is only available for 103 mm Inventory packing labels')
    height = round(req.length_mm * 300 / 25.4)
    expected_bytes = height * PACKING_ROW_BYTES
    if len(encoded) != 4 * ((expected_bytes + 2) // 3):
        raise PrintError('Bitmap length does not match the label')
    try:
        pixels = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise PrintError('Invalid packing bitmap encoding') from exc
    if len(pixels) != expected_bytes:
        raise PrintError('Bitmap length does not match the label')
    image = Image.frombytes('1', (PACKING_WIDTH, height), pixels)
    context = ['inventory-packing-bitmap-1', req.printer_id, req.media, req.reference,
               req.scan, image.width, image.height]
    header = json.dumps(context, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    digest = hashlib.sha256(header + b'\n' + pixels).hexdigest()
    return image, digest


def bitmap(req):
    plain=QrLabelRequest.model_validate(req.model_dump(exclude={'expected_fingerprint', 'bitmap_1bpp_base64'}))
    if req.bitmap_1bpp_base64 is not None:
        image, digest = packing_bitmap(plain, req.bitmap_1bpp_base64)
        return plain, image, digest
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
        response = JSONResponse(dict(png_base64=base64.b64encode(output.getvalue()).decode(),fingerprint=digest), headers={'Cache-Control':'no-store'})
        if req.bitmap_1bpp_base64 is not None and len(response.body) > MAX_PREVIEW_JSON:
            raise PrintError('Packing label preview is too large')
        return response
    except PrintError: fail(400,'error_not_sent')

@router.post('/projects/{external_project_id}/qr-labels')
def send(external_project_id:UUID,req:ScopedQrSend,session:Session=Depends(get_session),key:ApiKey=Security(require_api_key),
         token:Annotated[str|None,Header(alias='Idempotency-Key')]=None):
    check_scope(key,'print');require_integration(session,key)
    if not token: fail(400,'idempotency_key_required')
    def operation():
        try:
            printer,policy=assigned(session,key,external_project_id,req)
            plain,image,digest=bitmap(req)
            if digest!=req.expected_fingerprint: fail(409,'fingerprint_mismatch')
            if req.bitmap_1bpp_base64 is None:
                raster = build_qr_job(plain, printer)
            else:
                raster = build_qr_job(plain, printer, image=image)
        except (HTTPException,PrintError) as exc:
            session.add(PrintLog(operator=f'api:{key.name}',operator_source='api',integration_id=key.integration_id,
                external_project_id=str(external_project_id),print_purpose='qr_labels',label_kind='qr',status='denied',reason='Scoped preparation QR',error='request_denied'))
            session.commit()
            if isinstance(exc,PrintError): fail(400,'error_not_sent')
            raise
        log=PrintLog(label_kind='qr',qr_scan=req.scan,media_code=req.media,printer_model=printer.model,source_reference=req.reference,
            reason=f'Packing bitmap {digest}' if req.bitmap_1bpp_base64 is not None else '',
            template_name='QR label',printer_name=printer.name,operator=f'api:{key.name}',operator_source='api',status='sending',
            integration_id=key.integration_id,external_project_id=str(external_project_id),project_id=policy.tds_project_id,print_purpose='qr_labels')
        session.add(log);session.commit();session.refresh(log)
        try: observation = send_brother_job(printer,raster,media=req.media)
        except PrintError as exc:
            log.status='uncertain' if exc.uncertain else 'error';log.error='Check printer before retrying';session.add(log);session.commit()
            if isinstance(exc, PrinterNotReady): fail(409,'printer_not_ready')
            fail(502,'uncertain' if exc.uncertain else 'error_not_sent')
        log.status='ok';session.add(log);session.commit()
        result = ScopedQrResult(code='sent',message='Sent to printer; physical output not confirmed.',log_id=log.id,printer_id=printer.id,scan=req.scan,
            print_observation=observation if observation in ('counter_advanced','unconfirmed') else 'unconfirmed')
        if req.bitmap_1bpp_base64 is not None:
            return PackingQrResult(**result.model_dump(), bitmap_fingerprint=digest)
        return result
    return run_print_request(f'/integrations/projects/{external_project_id}/qr-labels',req,key,token,session,operation,machine_codes=True,stable_integration=True)
