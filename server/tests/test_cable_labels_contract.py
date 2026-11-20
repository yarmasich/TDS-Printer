"""Shared FloorHub contract for POST /api/v1/integrations/projects/{id}/cable-labels.

Every example in tests/contracts/cable_labels_contract.json is produced here by the real
endpoint. FloorHub keeps a byte-identical copy and replays the same examples through its
parser, so a change to the response shape, a result status or an error code fails a test
in this repo first. After an intended contract change, regenerate with
TDS_CONTRACT_REGENERATE=1, then copy the file to FloorHub and update its expectations.
"""
import ast
import inspect
import json
import os
import textwrap
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlmodel import Session, select

from app import auth_apikey, print_idempotency, printer_device_status, trunks
from app.api import integrations, scoped_integrations
from app.auth_apikey import generate_key
from app.models import ApiKey, Discipline, Label
from app.printer import PrintError
from tests.test_scoped_routing import policy, scope  # noqa: F401 (fixture)
from tests.test_scoped_trunk import allow, prepare

CONTRACT = Path(__file__).parent / 'contracts' / 'cable_labels_contract.json'
SIBLING = Path(__file__).resolve().parents[2].parent / 'FloorHub'
SIBLING_CONTRACT = SIBLING / 'backend' / 'tests' / 'contracts' / 'cable_labels_contract.json'
# Values FloorHub decides on are compared exactly; everything else by key and type only.
EXACT_KEYS = {'ok', 'requested', 'printed', 'status', 'role', 'code', 'printer_state', 'printer_role'}


def contract():
    return json.loads(CONTRACT.read_text())


def shape(value, key=None):
    if isinstance(value, dict):
        return {k: shape(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(v) for v in value]
    return value if key in EXACT_KEYS else type(value).__name__


def post(c, h, p, token='intent', **body):
    headers = {**h, **({'Idempotency-Key': token} if token is not None else {})}
    return c.post(f'/api/v1/integrations/projects/{p}/cable-labels', headers=headers,
                  json={'cables': ['7.*'], 'discipline': 'NET', 'data_hall': 'Hall', **body})


def fault(state, sentence, printer_name=None):
    """print_preflight stub: a fault on one printer (or every printer), no counter."""
    return lambda printer: ((state, sentence) if printer_name in (None, printer.name) else None, None)


def edit(engine, model, row_id, **values):
    with Session(engine) as s:
        row = s.get(model, row_id)
        for name, value in values.items():
            setattr(row, name, value)
        s.add(row); s.commit()


def add(engine, *rows):
    with Session(engine) as s:
        s.add_all(rows); s.commit()


# Each case prepares state and returns (final request, render_and_send side effect, extra patches).
def full_success(c, e, h, p):
    prepare(e); allow(c, h, p)
    counter = [patch.object(printer_device_status, 'print_preflight', return_value=(None, 500)),
               patch.object(printer_device_status, 'counter_supported', return_value=True),
               patch.object(printer_device_status, 'print_counter', return_value=502)]
    return lambda: post(c, h, p), None, counter


def partial(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, cables=['7.1', '99.1']), None, []


def partial_send_error(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p), [None, PrintError('dropped', uncertain=True)], []


def nothing_printed(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, cables=['99.1']), None, []


def send_error_nothing_printed(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p), PrintError('send failed; outcome unknown', uncertain=True), []


def trunk_with(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, trunk='with'), None, []


def trunk_only(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, trunk='only'), None, []


def printer_fault_leg(c, e, h, p):
    prepare(e); allow(c, h, p)
    stub = patch.object(printer_device_status, 'print_preflight',
                        side_effect=fault('cover_open', 'Printer Cable cover is open. Close it, then print again.'))
    return lambda: post(c, h, p), None, [stub]


def printer_fault_trunk(c, e, h, p):
    prepare(e); allow(c, h, p)
    stub = patch.object(printer_device_status, 'print_preflight',
                        side_effect=fault('no_media', 'Printer Trunks has no labels loaded.', 'Trunks'))
    return lambda: post(c, h, p, trunk='with'), None, [stub]


def trunk_not_linked(c, e, h, p):
    prepare(e, link=False); allow(c, h, p)
    return lambda: post(c, h, p, trunk='with'), None, []


def trunk_template_not_found(c, e, h, p):
    prepare(e); allow(c, h, p); edit(e, Discipline, 2, template_id=None)
    return lambda: post(c, h, p, trunk='with'), None, []


def trunk_printer_not_allowed(c, e, h, p):
    prepare(e); allow(c, h, p, ids=(1,))
    return lambda: post(c, h, p, trunk='with'), None, []


def trunk_number_missing(c, e, h, p):
    prepare(e); allow(c, h, p)
    add(e, Label(discipline_id=1, left_text='CBL#9.1', leg_no='1'))
    return lambda: post(c, h, p, cables=['9.1'], trunk='with'), None, []


def trunk_label_not_found(c, e, h, p):
    prepare(e); allow(c, h, p)
    add(e, Label(discipline_id=1, left_text='CBL#8.1', trunk_no='8', leg_no='1'))
    return lambda: post(c, h, p, cables=['8.*'], trunk='with'), None, []


def trunk_label_ambiguous(c, e, h, p):
    prepare(e); allow(c, h, p)
    add(e, Label(discipline_id=2, left_text='TRUNK 7 copy', trunk_no='7'))
    return lambda: post(c, h, p, trunk='with'), None, []


def policy_missing(c, e, h, p):
    prepare(e)
    return lambda: post(c, h, p), None, []


def default_missing(c, e, h, p):
    prepare(e)
    body = policy(p, cable_labels={'printer_ids': [1], 'default_printer_id': None})
    assert c.put(f'/api/v1/integrations/projects/{p}/policy', headers=h, json=body).status_code == 200
    return lambda: post(c, h, p), None, []


def printer_not_allowed(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, printer_id=2), None, []


def binding_missing(c, e, h, p):
    prepare(e)
    assert c.put(f'/api/v1/integrations/projects/{p}/policy', headers=h,
                 json=policy(p, tds_project_id=None)).status_code == 200
    return lambda: post(c, h, p), None, []


def binding_not_found(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, data_hall='Unknown hall'), None, []


def template_not_found(c, e, h, p):
    prepare(e); allow(c, h, p); edit(e, Discipline, 1, template_id=None)
    return lambda: post(c, h, p), None, []


def scope_forbidden(c, e, h, p):
    prepare(e); allow(c, h, p)
    raw, prefix, digest = generate_key()
    with Session(e) as s:
        integration_id = s.exec(select(ApiKey).where(ApiKey.name == 'scoped')).one().integration_id
        s.add(ApiKey(name='read-only', prefix=prefix, key_hash=digest, integration_id=integration_id,
                     scopes=['policy.read'])); s.commit()
    return lambda: post(c, {'X-API-Key': raw}, p), None, []


def idempotency_key_required(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, token=None), None, []


def idempotency_key_invalid(c, e, h, p):
    prepare(e); allow(c, h, p)
    return lambda: post(c, h, p, token='has space'), None, []


def idempotency_replay(c, e, h, p):
    prepare(e); allow(c, h, p)
    with patch.object(integrations, 'render_and_send'):
        assert post(c, h, p).status_code == 200
    return lambda: post(c, h, p), None, []


def idempotency_conflict(c, e, h, p):
    prepare(e); allow(c, h, p)
    with patch.object(integrations, 'render_and_send'):
        assert post(c, h, p).status_code == 200
    return lambda: post(c, h, p, cables=['7.1']), None, []


def idempotency_in_progress(c, e, h, p):
    prepare(e); allow(c, h, p)
    # A send interrupted by an unexpected error leaves the reservation unresolved.
    with patch.object(integrations, 'render_and_send', side_effect=RuntimeError('interrupted')):
        with pytest.raises(RuntimeError):
            post(c, h, p)
    return lambda: post(c, h, p), None, []


CASES = {case.__name__: case for case in (
    full_success, partial, partial_send_error, nothing_printed, send_error_nothing_printed, trunk_with, trunk_only,
    printer_fault_leg, printer_fault_trunk, trunk_not_linked, trunk_template_not_found, trunk_printer_not_allowed,
    trunk_number_missing, trunk_label_not_found, trunk_label_ambiguous, policy_missing, default_missing,
    printer_not_allowed, binding_missing, binding_not_found, template_not_found, scope_forbidden,
    idempotency_key_required, idempotency_key_invalid, idempotency_replay, idempotency_conflict,
    idempotency_in_progress)}


def observe(scope, name):
    c, engine, h, p, _ = scope
    request, side_effect, stubs = CASES[name](c, engine, h, p)
    hardware = Mock(side_effect=side_effect)
    with patch.object(integrations, 'render_and_send', hardware):
        for stub in stubs:
            stub.start()
        try:
            response = request()
        finally:
            for stub in reversed(stubs):
                stub.stop()
    replay = response.headers.get('X-Idempotent-Replay')
    return {'status': response.status_code, 'headers': {'X-Idempotent-Replay': replay} if replay else {},
            'sends_attempted': hardware.call_count > 0, 'body': response.json()}


@pytest.mark.parametrize('name', sorted(CASES))
def test_endpoint_matches_contract_example(scope, name):
    actual = observe(scope, name)
    if os.environ.get('TDS_CONTRACT_REGENERATE') == '1':
        data = contract()
        data['examples'][name] = {'description': data['examples'].get(name, {}).get('description', ''), **actual}
        CONTRACT.write_text(json.dumps(data, indent=2) + '\n')
        return
    expected = contract()['examples'][name]
    assert actual['status'] == expected['status']
    assert actual['headers'] == expected['headers']
    # Only a documented pre-send rejection may promise that nothing was sent.
    assert actual['sends_attempted'] is expected['sends_attempted']
    assert shape(actual['body']) == shape(expected['body'])


def test_every_example_is_produced_here():
    assert set(contract()['examples']) == set(CASES)


def _codes_in(function):
    """String codes this function raises: fail(_, 'x'), {'code': 'x'} and TrunkLookupError(_, _, 'x')."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            position = {'fail': 1, 'TrunkLookupError': 2}.get(name)
            if position is not None and len(node.args) > position and isinstance(node.args[position], ast.Constant):
                found.add(node.args[position].value)
            found.update(k.value.value for k in node.keywords
                         if k.arg == 'code' and isinstance(k.value, ast.Constant))
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == 'code' and isinstance(value, ast.Constant):
                    found.add(value.value)
    return found


# Everything on the request path of the endpoint that can raise a machine code.
CODE_SOURCES = (scoped_integrations.cable_labels, scoped_integrations.require_integration,
                scoped_integrations._trunk_route, scoped_integrations._trunk_plan,
                trunks.trunk_label, print_idempotency.run_print_request, auth_apikey.check_scope)


def test_error_code_list_matches_the_source():
    emitted = set().union(*(_codes_in(f) for f in CODE_SOURCES))
    assert emitted == set(contract()['error_codes']), 'Update the contract (both copies) and FloorHub mappings'


def test_every_error_code_has_an_example():
    data = contract()
    exercised = {e['body']['detail']['code'] for e in data['examples'].values()
                 if isinstance(e['body'].get('detail'), dict)}
    assert exercised == set(data['error_codes'])


def test_contract_copy_matches_floorhub():
    if not SIBLING.is_dir():
        pytest.skip(f'FloorHub checkout not found at {SIBLING}; drift is checked where both repos are side by side')
    assert SIBLING_CONTRACT.is_file(), f'FloorHub copy missing: {SIBLING_CONTRACT}'
    assert SIBLING_CONTRACT.read_bytes() == CONTRACT.read_bytes(), (
        f'{CONTRACT} and {SIBLING_CONTRACT} must stay byte-identical')
