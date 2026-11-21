"""Project routing for integration-bound credentials. No name based routing."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Security
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from ..auth_apikey import check_scope, generate_key, require_api_key
from ..db import get_session
from ..models import (ApiKey, Integration, IntegrationPrintRequest, ProjectPrintPolicy, ProjectPrinterAssignment,
                      PolicyAudit, Printer, Project, DataHall, Discipline, Template, PrintLog)
from ..print_idempotency import record_progress, request_scope, run_print_request
from .. import rfid, printer_reachability, printer_device_status, trunks
from .integrations import (_catalog_entry, ApiBatchPrintRequest, ApiBatchPrintResponse, BatchItemResult,
                          _plan_batch, _print_label, _printer_counter)

PURPOSES = ('cable_labels', 'qr_labels')
SCOPES = {'policy.read', 'policy.write', 'print'}
# Advertised in /configuration so a caller sends optional request fields only
# to a server that accepts them (request bodies forbid unknown fields).
CAPABILITIES = ('policy.external_project_name', 'print.progress')
MAX_PROJECT_NAME = 200
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
    # Display only. Left out: the stored name is kept; null or blank clears it.
    external_project_name: str | None = Field(default=None, max_length=MAX_PROJECT_NAME)


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
                capabilities=list(CAPABILITIES),
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
    name_sent = 'external_project_name' in req.model_fields_set
    if name_sent:
        values['external_project_name'] = (req.external_project_name or '').strip() or None
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
        after = req.model_dump(mode='json', exclude={'external_project_name'})
        after['revision'] += 1
        if name_sent:
            after['external_project_name'] = values['external_project_name']
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
    device_addresses = []
    for pid in dto[purpose]['printer_ids']:
        p = session.get(Printer, pid)
        if p is not None and purpose in capability(p):
            printers.append({**catalog(p), 'online': None})
            if ping:
                addresses.append((p.id, p.ip, p.port))
                if purpose == 'qr_labels' or p.model in printer_device_status.PANDUIT_SNMP_DESCRIPTIONS:
                    device_addresses.append(printer_device_status.DeviceStatusConfig.from_printer(p))
    if addresses:
        # Independent read-only probes run concurrently: <=8s TCP and <=8s SNMP
        # (status + counter GET) socket budgets for 32 profiles, so the slower
        # of the two still fits inside the upstream 15s request timeout.
        device_statuses = {}
        if device_addresses:
            with ThreadPoolExecutor(max_workers=2) as executor:
                tcp = executor.submit(printer_reachability.printer_statuses, addresses)
                hardware = executor.submit(printer_device_status.device_statuses, device_addresses)
                statuses, device_statuses = tcp.result(), hardware.result()
        else:
            statuses = printer_reachability.printer_statuses(addresses)
        for printer in printers:
            printer['online'] = statuses.get(printer['id'])
            if printer['id'] in device_statuses:
                printer['device_status'] = device_statuses.get(printer['id'])
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
    # 'with' also prints each leg's trunk label (once per trunk), 'only' just the trunks. Trunks
    # print on the trunk discipline's template printer, which the policy must allow. Left out
    # of the idempotency hash at 'none', so intents sent before this field replay unchanged.
    trunk: trunks.TrunkMode = Field('none', exclude_if=lambda mode: mode == 'none')


def _frozen(printer: Printer, template: Template):
    """Detached snapshots: an admin edit between sends cannot reroute the rest of a batch."""
    frozen_printer = Printer(**deepcopy(printer.model_dump()))
    canonical = _catalog_entry(printer)
    frozen_printer.protocol, frozen_printer.dpi = canonical.protocol, canonical.dpi
    return frozen_printer, Template(**deepcopy(template.model_dump()))


def _trunk_route(session, disc: Discipline, allowed_ids):
    """The trunk discipline's template and printer, checked against the project policy."""
    linked = session.get(Discipline, disc.trunk_discipline_id) if disc.trunk_discipline_id else None
    if linked is None:
        fail(409, 'trunk_not_linked')
    template = session.get(Template, linked.template_id) if linked.template_id else None
    if template is None:
        fail(404, 'trunk_template_not_found')
    printer = session.get(Printer, template.printer_id) if template.printer_id else None
    if printer is None or printer.id not in allowed_ids or 'cable_labels' not in capability(printer):
        fail(403, 'trunk_printer_not_allowed')
    return template, printer


def _trunk_plan(session, plan):
    """Each trunk once, in the order its first leg appears; resolved before any send."""
    seen, out = set(), []
    for _, label in plan:
        if label is None:
            continue
        try:
            trunk = trunks.trunk_label(session, label)
        except trunks.TrunkLookupError as exc:
            fail(exc.status, exc.code)
        if trunk.id not in seen:
            seen.add(trunk.id)
            out.append((BatchItemResult(cable=f'trunk {trunk.trunk_no}', status='pending', label_id=trunk.id,
                                        role='trunk', trunk_no=trunk.trunk_no), trunk))
    return out


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
        for result, label in plan:
            result.trunk_no = label.trunk_no if label is not None else None
        # Legs and trunks are different stock: trunks go to their own template's printer.
        # Every trunk resolves before anything is sent, or nothing prints.
        trunk_jobs, trunk_route = [], None
        if req.trunk != 'none':
            trunk_route = _trunk_route(session, disc, set(policy['cable_labels']['printer_ids']))
            trunk_jobs = _trunk_plan(session, plan)
        # SQLModel expires rows on each log commit, so every send works from snapshots.
        leg_route = _frozen(printer, template)
        trunk_route = _frozen(trunk_route[1], trunk_route[0]) if trunk_route else None
        snapshot = lambda label: type(label)(**deepcopy(label.model_dump())) if label else None
        jobs = [(result, snapshot(label), leg_route) for result, label in plan
                if req.trunk != 'only' or label is None]
        jobs += [(result, snapshot(label), trunk_route) for result, label in trunk_jobs]
        name = disc.name
        frozen_project = Project(**deepcopy(session.get(Project, row.tds_project_id).model_dump()))
        integration_id = key.integration_id
        identity = rfid.OperatorIdentity(f'api:{key.name}', 'api')
        results, printed = [], 0
        legs_print = any(label is not None for _, label, route in jobs if route is leg_route)
        # One fresh read per printer with labels due, all before the first send. The leg
        # read also gives the counter before.
        fault, counter_before = (printer_device_status.print_preflight(leg_route[0])
                                 if legs_print else (None, None))
        role = 'leg'
        if not fault and trunk_jobs:
            role = 'trunk'
            fault = (printer_device_status.print_preflight(trunk_route[0])[0]
                     if trunk_route[0].id != leg_route[0].id or not legs_print else None)
        if fault:
            # `code` stays for existing callers; the state and sentence say which fault.
            # Only a trunk printer fault says so, leaving the leg reply unchanged.
            detail = {'code': 'printer_fault', 'printer_state': fault[0], 'message': fault[1]}
            raise HTTPException(400, {**detail, 'printer_role': 'trunk'} if role == 'trunk' else detail)
        progress_scope = request_scope(key, token, stable_integration=True)
        due = sum(label is not None for _, label, _ in jobs)
        handed = 0
        if due:
            record_progress(session, progress_scope, total=due, sent=0)
        for result, label, (target_printer, target_template) in jobs:
            if label is not None:
                log_id, error = _print_label(label, target_template, target_printer,
                                            identity.name, 'API scoped cable labels', session, identity,
                                            integration_id=integration_id, external_project_id=str(external_project_id), audit_project=frozen_project)
                result.log_id = log_id
                result.status = 'error' if error else 'printed'
                result.error = 'Print outcome requires operator inspection' if error else ''
                printed += int(error is None)
                handed += 1
                record_progress(session, progress_scope, total=due, sent=handed)
            results.append(result)
        # Informational only: the counter changes no status, field or decision.
        counter = _printer_counter(leg_route[0], counter_before, sent=True) if legs_print else None
        return ApiBatchPrintResponse(ok=all(r.status == 'printed' for r in results), requested=len(results),
                                     printed=printed, discipline=name, printer=leg_route[0].name, results=results,
                                     printer_counter=counter,
                                     trunk_printer=trunk_route[0].name if trunk_jobs else None)

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


@router.get('/print-requests/{idempotency_key}/progress')
def print_request_progress(idempotency_key: str, session: Session = Depends(get_session),
                           key: ApiKey = Security(require_api_key)):
    """How far a cable-label request with this Idempotency-Key has got (capability print.progress).

    state: unknown (no such request for this integration), running, or completed. total and
    sent count labels due and labels handed to the printer; null until the send starts.
    """
    check_scope(key, 'print'); require_integration(session, key)
    row = session.get(IntegrationPrintRequest, request_scope(key, idempotency_key, stable_integration=True))
    if row is None:
        return dict(state='unknown', total=None, sent=None)
    return dict(state='completed' if row.state == 'completed' else 'running',
                total=row.progress_total, sent=row.progress_sent)


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
        keys = session.exec(select(ApiKey).where(ApiKey.integration_id == integration.id)
                            .order_by(ApiKey.created_at.desc())).all()
        policies = session.exec(select(ProjectPrintPolicy).where(ProjectPrintPolicy.integration_id == integration.id)).all()
        # The display name stays out of policy_dto: the machine policy contract is unchanged.
        out.append(dict(id=integration.id, name=integration.name,
                        keys=[{**_dto(k).model_dump(), 'scopes': k.scopes} for k in keys], printers=printers,
                        policies=[{**policy_dto(session, p.external_project_id, p),
                                   'external_project_name': p.external_project_name} for p in policies]))
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
