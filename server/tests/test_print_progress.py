"""A running scoped cable-label send publishes how many labels it has handed to the printer."""
from unittest.mock import patch

from sqlmodel import Session, select

from app.api import integrations
from app.models import IntegrationPrintRequest
from tests.test_scoped_routing import scope  # noqa: F401 (fixture)
from tests.test_scoped_trunk import allow, prepare, send


def progress(c, h, token):
    response = c.get(f'/api/v1/integrations/print-requests/{token}/progress', headers=h)
    assert response.status_code == 200, response.text
    return response.json()


def test_progress_counts_each_label_as_it_is_sent(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    seen = []

    def hardware(*_args, **_kwargs):
        with Session(engine) as s:
            row = s.exec(select(IntegrationPrintRequest)).one()
            seen.append((row.progress_total, row.progress_sent))

    with patch.object(integrations, 'render_and_send', side_effect=hardware):
        assert send(c, h, p, token='job-1', trunk='with').status_code == 200
    # Two legs and the trunk: the count before each send, then the final reading.
    assert seen == [(3, 0), (3, 1), (3, 2)]
    assert progress(c, h, 'job-1') == {'state': 'completed', 'total': 3, 'sent': 3}


def test_unknown_and_refused_requests_have_no_counts(scope):
    c, engine, h, p, _ = scope
    prepare(engine); allow(c, h, p)
    assert progress(c, h, 'never-sent') == {'state': 'unknown', 'total': None, 'sent': None}
    with patch.object(integrations, 'render_and_send', side_effect=AssertionError('nothing may print')):
        assert send(c, h, p, token='refused', cables=['99.*']).status_code == 200
    assert progress(c, h, 'refused') == {'state': 'completed', 'total': None, 'sent': None}


def test_progress_needs_the_print_scope_and_is_advertised(scope):
    c, _, h, _, legacy = scope
    assert c.get('/api/v1/integrations/print-requests/x/progress', headers={'X-API-Key': legacy}).status_code == 403
    assert 'print.progress' in c.get('/api/v1/integrations/configuration', headers=h).json()['capabilities']


def test_migration_adds_progress_columns_idempotently(monkeypatch, tmp_path):
    from alembic import command
    from sqlalchemy import inspect
    from tests.test_integration_keys_admin import _alembic
    engine, cfg = _alembic(monkeypatch, tmp_path)
    columns = lambda: {c['name'] for c in inspect(engine).get_columns('integrationprintrequest')}
    command.upgrade(cfg, 'f3b9e2c71a58')
    assert not {'progress_total', 'progress_sent'} & columns()
    command.upgrade(cfg, 'head')
    assert {'progress_total', 'progress_sent'} <= columns()
    command.stamp(cfg, 'f3b9e2c71a58')
    command.upgrade(cfg, 'head')  # columns already there: a no-op
    command.downgrade(cfg, 'f3b9e2c71a58')
    assert not {'progress_total', 'progress_sent'} & columns()
    engine.dispose()
