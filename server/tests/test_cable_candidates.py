"""API cable lookups read only the labels a query could match.

FloorHub prints whole trunks ("324.*") and single legs of disciplines with
tens of thousands of labels. The batch planner used to load the whole
discipline for every request and regex-scan it; it now selects candidates in
SQL. These tests pin that the plan is identical to the former full scan
(forced by ``MAX_PREFILTER_TERMS = -1``) for every query shape.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import integrations
from app.models import DataHall, Discipline, Label, Project


@pytest.fixture
def data():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def fk(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        project = Project(name='Nscale'); s.add(project); s.commit()
        hall = DataHall(name='8k&16k', project_id=project.id); s.add(hall); s.commit()
        legs = Discipline(name='16K-EW-LS', data_hall_id=hall.id)
        mixed = Discipline(name='8K-IBLFSP', data_hall_id=hall.id)
        bundles = Discipline(name='AS-T1', data_hall_id=hall.id, bundle_mode=True)
        s.add_all([legs, mixed, bundles]); s.commit()
        rows = []
        # Structured legs: text without a cable number, the link in the columns.
        for trunk in (1, 2, 12, 21, 324):
            for leg in (1, 2, 3, 10, 11):
                rows.append(Label(discipline_id=legs.id, left_text=f'EH1A | swp{trunk}s{leg} / SU1 | 16K-EW-LS | ',
                                  right_text=f'CNR | swp{trunk}s{leg}', trunk_no=str(trunk), leg_no=str(leg)))
        # Text that names a cable its columns do not: the text still answers.
        rows.append(Label(discipline_id=legs.id, left_text='CBL# | 7.1 | 300ft', right_text='LU#324',
                          trunk_no='8', leg_no='1'))
        # Trunk 2 leg 2 imported twice, as a re-uploaded file does.
        rows.append(Label(discipline_id=legs.id, left_text='EH1A | swp2s2 again', right_text='CNR',
                          trunk_no='2', leg_no='2'))
        # A trunk label kept in the leg discipline.
        rows.append(Label(discipline_id=legs.id, left_text='CBL# | 324 | 361ft', right_text='CNR', trunk_no='324'))
        # Mixed: older rows without the columns, cable number only in the text.
        for text in ('CBL#1.1 | 78m', 'CBL#1.2', 'CBL#1.10', 'LU#1 | CBL#50.1', 'CBL#8-B.1', '#20.18 | 300ft',
                     'MPO #324.3', 'DH26 AS-T1 | SOURCE', 'swp1s1 text only'):
            rows.append(Label(discipline_id=mixed.id, left_text=text, right_text=text))
        rows.append(Label(discipline_id=mixed.id, left_text='plain', right_text='plain', trunk_no='1', leg_no='2'))
        for bundle, text in (('1', 'CBL#1.1'), ('1', 'CBL#1.2'), ('2', 'CBL#2.1'), (None, 'CBL#3.1')):
            rows.append(Label(discipline_id=bundles.id, left_text=text, right_text=text, bundle=bundle))
        s.add_all(rows); s.commit()
        yield s, legs, mixed, bundles
    engine.dispose()


QUERIES = [
    ['1.*'], ['1.'], ['324.*'], ['2.*'], ['12.*'], ['1.2'], ['01.02'], ['1.1'], ['1.10'], ['324.11'],
    ['1'], ['324'], ['2.2'], ['99.1'], ['99.*'], ['7.1'], ['7.*'], ['8.1'], ['50.1'], ['20.18'],
    ['1.1-3'], ['1.1,2,10'], ['1.1', '2.*', '324.3'], ['swp1s3'], ['SWP2S2'], ['source'], ['8-B'],
    ['a'], ['zzz-no-hit'], ['#324.1'], ['1.*', '1.2'], ['3'], ['3.1'], ['2'],
]


def plan(s, disc, **request):
    req = integrations.ApiBatchPrintRequest(discipline_id=disc.id, **request)
    try:
        return [(result.model_dump(), label.id if label else None)
                for result, label in integrations._plan_batch(req, disc, s)]
    except HTTPException as exc:
        return ('error', exc.status_code, str(exc.detail))


def both(s, disc, monkeypatch, **request):
    fast = plan(s, disc, **request)
    with monkeypatch.context() as m:
        m.setattr(integrations, 'MAX_PREFILTER_TERMS', -1)  # the former full scan
        full = plan(s, disc, **request)
    return fast, full


@pytest.mark.parametrize('which', ['legs', 'mixed', 'bundles'])
@pytest.mark.parametrize('cables', QUERIES, ids=lambda q: '+'.join(q))
def test_batch_plan_equals_the_full_scan(data, monkeypatch, which, cables):
    s, legs, mixed, bundles = data
    disc = {'legs': legs, 'mixed': mixed, 'bundles': bundles}[which]
    fast, full = both(s, disc, monkeypatch, cables=cables)
    assert fast == full


@pytest.mark.parametrize('bundle', ['1', '2', '9'])
def test_explicit_bundle_plan_equals_the_full_scan(data, monkeypatch, bundle):
    s, _, _, bundles = data
    fast, full = both(s, bundles, monkeypatch, bundle=bundle)
    assert fast == full


def test_the_structured_shapes_resolve_as_expected(data):
    s, legs, _, _ = data
    ids = lambda q: [label for _, label in plan(s, legs, cables=[q])]
    trunk_324 = [r['label_id'] for r, _ in plan(s, legs, cables=['324.*'])]
    assert len(trunk_324) == 6  # five legs and the trunk label kept here
    assert len(ids('1.10')) == 1 and ids('1.10') != ids('1.1')
    assert plan(s, legs, cables=['99.1'])[0][0]['status'] == 'not_found'
    assert plan(s, legs, cables=['2.2'])[0][0]['status'] == 'ambiguous'
    assert plan(s, legs, cables=['a'])[0][0]['status'] == 'invalid'
    # The text names 7.1; its columns say 8.1. Both still find it.
    assert ids('7.1') == ids('8.1')


def test_a_whole_trunk_reads_only_that_trunks_rows(data, monkeypatch):
    s, legs, _, _ = data
    loaded = []
    real = integrations._match_cable
    monkeypatch.setattr(integrations, '_match_cable', lambda rows, q: (loaded.append(len(rows)), real(rows, q))[1])
    plan(s, legs, cables=['1.*'])
    # Trunk 1's five legs by column, plus the two rows whose text has a "#"
    # before a 1. Never the other legs, whose text is full of 1s ("SU1").
    assert loaded == [7]


def test_a_long_leg_range_still_prefilters(data, monkeypatch):
    s, legs, _, _ = data
    cables = [f'324.{i}' for i in range(1, 301)]  # more terms than the limit
    loaded = []
    real = integrations._match_cable
    monkeypatch.setattr(integrations, '_match_cable', lambda rows, q: (loaded.append(len(rows)), real(rows, q))[1])
    fast = plan(s, legs, cables=cables)
    assert set(loaded) == {7}  # trunk 324's legs and trunk label, and the two '#' rows
    monkeypatch.setattr(integrations, '_match_cable', real)
    monkeypatch.setattr(integrations, 'MAX_PREFILTER_TERMS', -1)
    assert fast == plan(s, legs, cables=cables)


# Label text shapes from the field, as in test_search_batch.
SHAPES = [
    'WH1D9-U18-P37/1\nCH1C1-U18-P1/1\n8k-IBLFSP-001 | SU1\n144S SMF | CBL#1.1 | 78m',
    'AS-T1 | LU#1 | SU01 | CBL# | 1.1 | 270ft', 'LU#8 | SU#8 | CBL#50.1 | 300ft', 'CBL#8-B.1 | 300ft',
    'CBL#8 | 2026-11-06 | 7-3 | 300ft', '#20.18 | 300ft', '| # 20.18', 'CBL # | 324 | 361ft',
    'MPO #324.3', 'CAT6#7', 'LC # | 9.37', 'EH1A | swp1s1 / SU1 | 16K-EW-LS | ',
]


@pytest.mark.parametrize('queries', [['1'], ['1.1'], ['1.*'], ['1.'], ['8'], ['8.1'], ['20.18'], ['20.*'], ['324'],
                                     ['324.*'], ['324.3'], ['7'], ['9.37'], ['50.1'], ['01.1'], ['#8'], ['8-B'],
                                     ['swp1s1'], ['1.1', '1.2', '324.3', '20.*'], ['324.3', '324.*']],
                         ids=lambda q: '+'.join(q))
@pytest.mark.parametrize('limit', [256, 1])  # 1: legs fall back to the shared trunk term
def test_text_prefilter_never_narrows_the_regex(data, monkeypatch, queries, limit):
    from app.search import cable_query_pattern, validate_query
    s, legs, _, _ = data
    for text in SHAPES:
        s.add(Label(discipline_id=legs.id, left_text=text, right_text='')); s.commit()
    monkeypatch.setattr(integrations, 'MAX_PREFILTER_TERMS', limit)
    candidates = {label.id for label in integrations._candidate_labels(s, legs, queries)}
    for q in queries:
        pattern = cable_query_pattern(validate_query(q)[1])
        for label in s.exec(select(Label).where(Label.discipline_id == legs.id)).all():
            if pattern.search(label.left_text):
                assert label.id in candidates, (q, label.left_text)
