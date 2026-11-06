"""Project routing for integration-bound credentials. No name based routing."""
from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Security
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth_apikey import check_scope, generate_key, require_api_key
from ..db import get_session
from ..models import (ApiKey, Integration, ProjectPrintPolicy, ProjectPrinterAssignment,
                      PolicyAudit, Printer, Project, DataHall, Discipline, Template, PrintLog)
from ..print_idempotency import run_print_request
from .. import rfid, printer_reachability
from .integrations import (_catalog_entry, ApiBatchPrintRequest, ApiBatchPrintResponse,
                          _plan_batch, _print_label)

PURPOSES = ('cable_labels', 'qr_labels')
SCOPES = {'policy.read', 'policy.write', 'print'}
router = APIRouter(prefix='/api/v1/integrations', tags=['project-routing'])
admin_router = APIRouter(prefix='/api/integrations', tags=['integration-admin'])
PositiveID = Annotated[StrictInt, Field(gt=0)]
Purpose = Literal['cable_labels', 'qr_labels']


def fail(status: int, code: str):
    raise HTTPException(status, {'code': code})


def capability(printer: Printer) -> list[str]:
    protocol = _catalog_entry(printer).protocol
    if protocol == 'brother_ql':
        return ['qr_labels']
    return ['cable_labels'] if protocol in ('epl2', 'ezpl', 'jscript') else []


def catalog(printer: Printer, *, network=False):
    row = _catalog_entry(printer).model_dump()
    row['purposes'] = capability(printer)
    if not network:
        for name in ('ip', 'port', 'protocol'):
            row.pop(name)
    return row


class StrictBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PurposePolicy(StrictBody):
    printer_ids: list[PositiveID] = Field(default_factory=list)
    default_printer_id: PositiveID | None = None

    @model_validator(mode='after')
    def valid_default(self):
        if len(self.printer_ids) != len(set(self.printer_ids)):
            raise ValueError('Duplicate printer IDs')
        if self.default_printer_id is not None and self.default_printer_id not in self.printer_ids:
            raise ValueError('Default must be assigned')
        return self


class PolicyBody(StrictBody):
    external_project_id: UUID
    revision: Annotated[StrictInt, Field(ge=0)]
    tds_project_id: PositiveID | None = None
    cable_labels: PurposePolicy
    qr_labels: PurposePolicy


def find_policy(session, integration_id, external_id):
    return session.exec(select(ProjectPrintPolicy).where(
        ProjectPrintPolicy.integration_id == integration_id,
        ProjectPrintPolicy.external_project_id == str(external_id))).first()


def policy_dto(session, external_id, row):
    assignments = session.exec(select(ProjectPrinterAssignment).where(
        ProjectPrinterAssignment.policy_id == row.id)).all() if row else []
    return dict(external_project_id=str(external_id), revision=row.revision if row else 0,
                tds_project_id=row.tds_project_id if row else None,
                **{purpose: {'printer_ids': sorted(a.printer_id for a in assignments if a.purpose == purpose),
                             'default_printer_id': getattr(row, 'cable_default_printer_id' if purpose == 'cable_labels' else 'qr_default_printer_id') if row else None}
                   for purpose in PURPOSES})


def require_integration(session, key):
    if not key.integration_id or session.get(Integration, key.integration_id) is None:
        fail(403, 'scope_forbidden')


@router.get('/configuration')
def configuration(session: Session = Depends(get_session), key: ApiKey = Security(require_api_key)):
    check_scope(key, 'policy.read'); require_integration(session, key)
    integration = session.get(Integration, key.integration_id)
    return dict(integration_id=integration.id, name=integration.name, scopes=key.scopes,
                printers=[catalog(p, network=True) for p in session.exec(select(Printer).order_by(Printer.name)).all()],
                projects=[{'id': p.id, 'name': p.name} for p in session.exec(select(Project).order_by(Project.name)).all()])


@router.get('/projects/{external_project_id}/policy')
def get_policy(external_project_id: UUID, session: Session = Depends(get_session), key: ApiKey = Security(require_api_key)):
    check_scope(key, 'policy.read'); require_integration(session, key)
    return policy_dto(session, external_project_id, find_policy(session, key.integration_id, external_project_id))


@router.put('/projects/{external_project_id}/policy')
def put_policy(external_project_id: UUID, req: PolicyBody,
               session: Session = Depends(get_session), key: ApiKey = Security(require_api_key),
               actor: Annotated[str, Header(alias='X-FloorHub-Actor', max_length=256)] = ''):
    check_scope(key, 'policy.write'); require_integration(session, key)
    if req.external_project_id != external_project_id:
        fail(400, 'project_mismatch')
    if req.tds_project_id is not None and not session.get(Project, req.tds_project_id):
        fail(400, 'binding_not_found')
    for purpose in PURPOSES:
        for printer_id in getattr(req, purpose).printer_ids:
            printer = session.get(Printer, printer_id)
            if printer is None or purpose not in capability(printer):
                fail(400, 'printer_not_allowed')
    row = find_policy(session, key.integration_id, external_project_id)
    before = policy_dto(session, external_project_id, row)
    if before['revision'] != req.revision:
        fail(409, 'revision_conflict')
    values = dict(revision=req.revision + 1, tds_project_id=req.tds_project_id,
                  cable_default_printer_id=req.cable_labels.default_printer_id,
                  qr_default_printer_id=req.qr_labels.default_printer_id)
    try:
        if row is None:
            row = ProjectPrintPolicy(id=str(uuid4()), integration_id=key.integration_id,
                                     external_project_id=str(external_project_id), **values)
            session.add(row); session.flush()
        else:
            changed = session.execute(update(ProjectPrintPolicy).where(
                ProjectPrintPolicy.id == row.id, ProjectPrintPolicy.revision == req.revision).values(**values))
            if changed.rowcount != 1:
                session.rollback(); fail(409, 'revision_conflict')
            session.execute(delete(ProjectPrinterAssignment).where(ProjectPrinterAssignment.policy_id == row.id))
        for purpose in PURPOSES:
            for printer_id in getattr(req, purpose).printer_ids:
                session.add(ProjectPrinterAssignment(policy_id=row.id, purpose=purpose, printer_id=printer_id))
        after = req.model_dump(mode='json'); after['revision'] += 1
        session.add(PolicyAudit(integration_id=key.integration_id, external_project_id=str(external_project_id),
                               actor=actor, before=before, after=after))
        session.commit()
    except IntegrityError:
        session.rollback(); fail(409, 'revision_conflict')
    session.refresh(row)
    return policy_dto(session, external_project_id, row)


@router.get('/projects/{external_project_id}/printers')
def allowed_printers(external_project_id: UUID, purpose: Purpose, ping: bool = False,
                     session: Session = Depends(get_session), key: ApiKey = Security(require_api_key)):
    check_scope(key, 'policy.read' if 'policy.read' in key.scopes else 'print'); require_integration(session, key)
    row = find_policy(session, key.integration_id, external_project_id)
    dto = policy_dto(session, external_project_id, row)
    printers = []
    addresses = []
    for pid in dto[purpose]['printer_ids']:
        p = session.get(Printer, pid)
        if p is not None and purpose in capability(p):
            printers.append({**catalog(p), 'online': None})
            if ping:
                addresses.append((p.id, p.ip, p.port))
    if addresses:
        statuses = printer_reachability.printer_statuses(addresses)
        for printer in printers:
            printer['online'] = statuses.get(printer['id'])
    default = dto[purpose]['default_printer_id']
    valid_default = default if default in {p['id'] for p in printers} else None
    out = dict(external_project_id=str(external_project_id), purpose=purpose, revision=dto['revision'],
               default_printer_id=valid_default, printers=printers)
    if default is not None and valid_default is None:
        out['invalid_default'] = True
    return out


class CableRequest(StrictBody):
    printer_id: PositiveID | None = None
    cables: list[str] = Field(min_length=1, max_length=500)
    discipline: str = Field(min_length=1, max_length=256)
    data_hall: str = Field(min_length=1, max_length=256)


@router.post('/projects/{external_project_id}/cable-labels')
def cable_labels(external_project_id: UUID, req: CableRequest,
                 session: Session = Depends(get_session), key: ApiKey = Security(require_api_key),
                 token: Annotated[str | None, Header(alias='Idempotency-Key')] = None):
    check_scope(key, 'print'); require_integration(session, key)
    if not token:
        fail(400, 'idempotency_key_required')

    def operation():
        row = find_policy(session, key.integration_id, external_project_id)
        if row is None:
            fail(400, 'policy_missing')
        policy = policy_dto(session, external_project_id, row)
        pid = req.printer_id if req.printer_id is not None else row.cable_default_printer_id
        if pid is None:
            fail(400, 'default_missing')
        printer = session.get(Printer, pid)
        if pid not in policy['cable_labels']['printer_ids'] or printer is None or 'cable_labels' not in capability(printer):
            fail(403, 'printer_not_allowed')
        if row.tds_project_id is None:
            fail(400, 'binding_missing')
        discs = session.exec(select(Discipline).join(DataHall, DataHall.id == Discipline.data_hall_id).where(
            DataHall.project_id == row.tds_project_id, DataHall.name == req.data_hall,
            Discipline.name == req.discipline)).all()
        if len(discs) != 1:
            fail(404, 'binding_not_found')
        disc = discs[0]
        template = session.get(Template, disc.template_id) if disc.template_id else None
        if template is None:
            fail(404, 'template_not_found')
        batch = ApiBatchPrintRequest(cables=req.cables)
        plan = _plan_batch(batch, disc, session)
        # SQLModel expires rows on each log commit: detached value snapshots
        # ensure an admin edit between sends cannot reroute the rest of a batch.
        frozen_printer = Printer(**deepcopy(printer.model_dump()))
        canonical = _catalog_entry(printer)
        frozen_printer.protocol, frozen_printer.dpi = canonical.protocol, canonical.dpi
        frozen_template = Template(**deepcopy(template.model_dump()))
        frozen_plan = [(result, type(label)(**deepcopy(label.model_dump())) if label else None) for result, label in plan]
        name = disc.name
        frozen_project = Project(**deepcopy(session.get(Project, row.tds_project_id).model_dump()))
        integration_id = key.integration_id
        identity = rfid.OperatorIdentity(f'api:{key.name}', 'api')
        results, printed = [], 0
        for result, label in frozen_plan:
            if label is not None:
                log_id, error = _print_label(label, frozen_template, frozen_printer,
                                            identity.name, 'API scoped cable labels', session, identity,
                                            integration_id=integration_id, external_project_id=str(external_project_id), audit_project=frozen_project)
                result.log_id = log_id
                result.status = 'error' if error else 'printed'
                result.error = 'Print outcome requires operator inspection' if error else ''
                printed += int(error is None)
            results.append(result)
        return ApiBatchPrintResponse(ok=all(r.status == 'printed' for r in results), requested=len(results),
                                     printed=printed, discipline=name, printer=frozen_printer.name, results=results)

    def audited_operation():
        try:
            return operation()
        except HTTPException as exc:
            # Denials carry no printer address, browser-supplied actor identity,
            # or cable text. They are inspectable beside successful attempts.
            row = find_policy(session, key.integration_id, external_project_id)
            session.add(PrintLog(operator=f'api:{key.name}', operator_source='api',
                                 integration_id=key.integration_id, external_project_id=str(external_project_id),
                                 project_id=row.tds_project_id if row else None,
                                 print_purpose='cable_labels', status='denied',
                                 reason='API scoped cable labels', error=exc.detail.get('code', 'request_denied')
                                 if isinstance(exc.detail, dict) else 'request_denied'))
            session.commit()
            raise

    return run_print_request(f'/integrations/projects/{external_project_id}/cable-labels', req, key, token,
                             session, audited_operation, machine_codes=True, stable_integration=True)


class CreateIntegration(StrictBody):
    name: str = Field(min_length=1, max_length=200)


class CreateScopedKey(CreateIntegration):
    scopes: list[Literal['policy.read', 'policy.write', 'print']] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def unique_scopes(self):
        if len(self.scopes) != len(set(self.scopes)):
            raise ValueError('Duplicate scopes')
        return self


@admin_router.get('')
def inspect_integrations(session: Session = Depends(get_session)):
    from .api_keys import _dto
    out = []
    printers = [{'id': p.id, 'name': p.name, 'purposes': capability(p)} for p in session.exec(select(Printer).order_by(Printer.name)).all()]
    for integration in session.exec(select(Integration).order_by(Integration.name)).all():
        keys = session.exec(select(ApiKey).where(ApiKey.integration_id == integration.id)).all()
        policies = session.exec(select(ProjectPrintPolicy).where(ProjectPrintPolicy.integration_id == integration.id)).all()
        out.append(dict(id=integration.id, name=integration.name,
                        keys=[{**_dto(k).model_dump(), 'scopes': k.scopes} for k in keys], printers=printers,
                        policies=[policy_dto(session, p.external_project_id, p) for p in policies]))
    return out


@admin_router.post('')
def create_integration(req: CreateIntegration, session: Session = Depends(get_session)):
    name = req.name.strip()
    if not name:
        fail(400, 'name_required')
    row = Integration(id=str(uuid4()), name=name)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback(); fail(409, 'name_conflict')
    return {'id': row.id, 'name': row.name}


@admin_router.post('/{integration_id}/keys')
def create_scoped_key(integration_id: UUID, req: CreateScopedKey, session: Session = Depends(get_session)):
    from .api_keys import _dto
    if session.get(Integration, str(integration_id)) is None:
        fail(404, 'integration_not_found')
    if not req.name.strip():
        fail(400, 'name_required')
    plaintext, prefix, digest = generate_key()
    row = ApiKey(name=req.name.strip(), prefix=prefix, key_hash=digest, integration_id=str(integration_id), scopes=req.scopes)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback(); fail(409, 'name_conflict')
    return {**_dto(row).model_dump(), 'integration_id': row.integration_id, 'scopes': row.scopes, 'key': plaintext}
