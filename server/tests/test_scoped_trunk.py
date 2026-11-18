"""Scoped cable labels print a leg's trunk label on the trunk discipline's own printer."""
from unittest.mock import patch

import pytest
from sqlmodel import Session

from app.api import integrations
from app.models import DataHall, Discipline, Label, Printer, Template
from tests.test_scoped_routing import scope, policy  # noqa: F401 (fixture)


def prepare(engine, *, trunk_printer=True, link=True):
    with Session(engine) as s:
        s.add(Printer(id=3, name='Trunks', ip='192.0.2.3', protocol='epl2'))
        s.add(Template(id=1, name='Legs', printer_id=1, bytes_per_row=64, height=100))
        s.add(Template(id=2, name='Trunk stock', printer_id=3 if trunk_printer else 2, bytes_per_row=64, height=100))
        s.add(DataHall(id=1, project_id=1, name='Hall'))
        s.add(Discipline(id=2, data_hall_id=1, name='NET-Trunk', template_id=2))
        s.add(Discipline(id=1, data_hall_id=1, name='NET', template_id=1, trunk_discipline_id=2 if link else None))
        s.add(Label(discipline_id=2, left_text='TRUNK 7', trunk_no='7'))
        s.add_all([Label(discipline_id=1, left_text=f'CBL#7.{leg}', trunk_no='7', leg_no=str(leg)) for leg in (1, 2)])
        s.commit()


def send(c, h, p, token='intent', **body):
    return c.post(f'/api/v1/integrations/projects/{p}/cable-labels', headers={**h, 'Idempotency-Key': token},
                  json={'cables': ['7.*'], 'discipline': 'NET', 'data_hall': 'Hall', **body})


def allow(c, h, p, ids=(1, 3)):
    body = policy(p, cable_labels={'printer_ids': list(ids), 'default_printer_id': 1})
    assert c.put(f'/api/v1/integrations/projects/{p}/policy', headers=h, json=body).status_code == 200


def sends(mock):
    return [(call.args[0].name, call.args[1].name) for call in mock.call_args_list]


def test_with_prints_the_legs_then_the_trunk_once_on_its_own_printer(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    with patch.object(integrations, 'render_and_send') as hardware:
        response = send(c, h, p, trunk='with')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['printed'] == 3 and body['ok'] is True
    assert sends(hardware) == [('Legs', 'Cable'), ('Legs', 'Cable'), ('Trunk stock', 'Trunks')]
    assert [(r['role'], r['trunk_no'], r['status']) for r in body['results']] == [
        ('leg', '7', 'printed'), ('leg', '7', 'printed'), ('trunk', '7', 'printed')]
    assert body['results'][-1]['cable'] == 'trunk 7'
    assert body['trunk_printer'] == 'Trunks'


def test_only_prints_just_the_trunk(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    with patch.object(integrations, 'render_and_send') as hardware:
        response = send(c, h, p, trunk='only')
    assert response.json()['printed'] == 1
    assert sends(hardware) == [('Trunk stock', 'Trunks')]


@pytest.mark.parametrize('setup,ids,status,code', [
    ({'link': False}, (1, 3), 409, 'trunk_not_linked'),
    ({}, (1,), 403, 'trunk_printer_not_allowed'),
    ({'trunk_printer': False}, (1, 3), 403, 'trunk_printer_not_allowed'),  # the QR printer
])
def test_an_unresolved_trunk_prints_nothing(scope, setup, ids, status, code):
    c, engine, h, p, _ = scope
    prepare(engine, **setup); allow(c, h, p, ids)
    with patch.object(integrations, 'render_and_send', side_effect=AssertionError('nothing may print')):
        response = send(c, h, p, trunk='with')
    assert response.status_code == status
    assert response.json()['detail']['code'] == code


def test_a_missing_trunk_label_prints_nothing(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    with Session(engine) as s:
        s.add(Label(discipline_id=1, left_text='CBL#8.1', trunk_no='8', leg_no='1')); s.commit()
    with patch.object(integrations, 'render_and_send', side_effect=AssertionError('nothing may print')):
        response = send(c, h, p, cables=['8.*'], trunk='with')
    assert (response.status_code, response.json()['detail']['code']) == (404, 'trunk_label_not_found')


def test_a_trunk_printer_fault_holds_every_label(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    reads = {'Cable': (None, None), 'Trunks': (('cover_open', 'Cover open'), None)}
    with patch('app.printer_device_status.print_preflight', side_effect=lambda printer: reads[printer.name]), \
            patch.object(integrations, 'render_and_send', side_effect=AssertionError('nothing may print')):
        response = send(c, h, p, trunk='with')
    assert response.status_code == 400
    assert response.json()['detail'] == {'code': 'printer_fault', 'printer_state': 'cover_open',
                                         'message': 'Cover open', 'printer_role': 'trunk'}


def test_none_keeps_the_request_hash_of_earlier_intents(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    with patch.object(integrations, 'render_and_send') as hardware:
        first = send(c, h, p)
        replay = send(c, h, p, trunk='none')
    assert replay.headers['X-Idempotent-Replay'] == 'true' and replay.json() == first.json()
    assert len(sends(hardware)) == 2
    from app.api.scoped_integrations import CableRequest
    assert 'trunk' not in CableRequest(cables=['7.*'], discipline='NET', data_hall='Hall').model_dump(mode='json')
