import sqlite3
from contextlib import closing
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine

from app.models import ApiKey, DataHall, Discipline, Label, Printer, Project, Template
from app.api import integrations, labels
from app.printer import PrintError
from app.search import (
    MAX_QUERY_LENGTH,
    cable_query_pattern,
    like_prefilter,
    parse_batch_query,
    validate_query,
)


@pytest.fixture
def data():
    engine = create_engine("sqlite://")
    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        p = Printer(name="P", ip="192.0.2.1")
        project = Project(name="Project")
        session.add_all([p, project]); session.commit()
        t = Template(name="T", printer_id=p.id, bytes_per_row=20, height=100)
        h = DataHall(name="H", project_id=project.id)
        session.add_all([t, h]); session.commit()
        d = Discipline(name="D", data_hall_id=h.id, template_id=t.id)
        session.add(d); session.commit()
        key = ApiKey(name="test", prefix="test", key_hash="not-a-key")
        yield session, d, key
    engine.dispose()


def add(session, d, text, bundle=None):
    row = Label(discipline_id=d.id, left_text=text, right_text=text, bundle=bundle)
    session.add(row); session.commit()
    return row.id


def batch(data, **kwargs):
    s, d, key = data
    return integrations.api_print_batch(integrations.ApiBatchPrintRequest(discipline_id=d.id, **kwargs), s, key)


@pytest.mark.parametrize("query, expected", [
    ("1.1,1.2,1.5", ["1.1", "1.2", "1.5"]),
    ("45.5,6,7", ["45.5", "45.6", "45.7"]),
    ("1.5-1.8", ["1.5", "1.6", "1.7", "1.8"]),
    ("1.5-8", ["1.5", "1.6", "1.7", "1.8"]),
    ("SERVER ROOM", ["SERVER ROOM"]),
])
def test_documented_query_forms(query, expected):
    assert parse_batch_query(query) == expected


def test_bounds_before_allocating_range():
    with pytest.raises(ValueError):
        parse_batch_query("1.1-10000")


@pytest.mark.parametrize("query", ["2026-11-06", "7-3", "1.1,", "1.1-", "1.5-2.8", "0-0,"])
def test_digits_that_are_not_a_cable_list_stay_a_text_search(query):
    assert parse_batch_query(query) == [query]


def test_resource_guards_still_refuse_instead_of_degrading():
    with pytest.raises(ValueError):
        parse_batch_query("1-2" + "0" * MAX_QUERY_LENGTH)
    with pytest.raises(ValueError):
        parse_batch_query("1,2,3", max_items=2)
    with pytest.raises(ValueError):
        parse_batch_query("1.1-5000", max_items=2)


@pytest.mark.parametrize("query", ["2026-11-06", "7-3"])
def test_date_and_port_text_searches_return_hits(data, query):
    s, d, _ = data
    wanted = add(s, d, f"CBL#8 | {query} | 300ft")
    add(s, d, "CBL#8 | 300ft")
    result = labels.search(q=query, project_id=None, data_hall_id=None,
                           discipline_id=d.id, limit=500, offset=0, session=s)
    assert [hit.label_id for hit in result.hits] == [wanted]


def test_text_search_preserves_spaces():
    assert validate_query("SERVER ROOM") == (True, "SERVER ROOM")


def test_search_reports_truncation(data):
    s, d, _ = data
    for i in range(3): add(s, d, f"CBL#1.{i}")
    result = labels.search(q="1.*", project_id=None, data_hall_id=None, discipline_id=d.id, limit=2, offset=0, session=s)
    assert result.total == 3
    assert result.truncated is True
    assert len(result.hits) == 2


def test_overlapping_groups_print_each_label_once(data):
    s, d, _ = data
    a = add(s, d, "CBL#1.1"); b = add(s, d, "CBL#1.2")
    with patch.object(integrations, "render_and_send") as send:
        result = batch(data, cables=["1.*", "1.1"])
    assert result.printed == 2
    assert send.call_count == 2
    assert {r.label_id for r in result.results} == {a, b}


def test_individual_cable_in_bundle_mode_is_not_whole_bundle(data):
    s, d, _ = data
    d.bundle_mode = True; s.add(d); s.commit()
    a = add(s, d, "CBL#1.1", "1"); add(s, d, "CBL#1.2", "1")
    with patch.object(integrations, "render_and_send") as send:
        result = batch(data, cable="1.1")
    assert result.printed == send.call_count == 1
    assert result.results[0].label_id == a


def test_missing_bundle_is_reported(data):
    s, d, _ = data
    d.bundle_mode = True; s.add(d); s.commit()
    add(s, d, "CBL#1.1", "1")
    with patch.object(integrations, "render_and_send"):
        result = batch(data, cables=["1.*", "999.*"])
    assert not result.ok
    assert any(r.status == "not_found" and "999" in r.cable for r in result.results)


@pytest.mark.parametrize("bundle_mode", [False, True])
def test_actual_label_limit_checked_before_any_print(data, bundle_mode):
    s, d, _ = data
    d.bundle_mode = bundle_mode; s.add(d)
    s.add_all([Label(discipline_id=d.id, left_text=f"CBL#1.{i}", bundle="1") for i in range(501)])
    s.commit()
    with patch.object(integrations, "render_and_send") as send:
        with pytest.raises(HTTPException) as err:
            batch(data, cable="1.*")
    assert err.value.status_code == 400
    send.assert_not_called()


def test_group_abort_reports_every_selected_label(data):
    s, d, _ = data
    for i in range(3): add(s, d, f"CBL#1.{i}")
    with patch.object(integrations, "render_and_send", side_effect=PrintError("offline")):
        result = batch(data, cable="1.*", stop_on_error=True)
    assert [r.status for r in result.results] == ["error", "skipped", "skipped"]


def test_individual_partial_failure_keeps_log_and_continues(data):
    s, d, _ = data
    add(s, d, "CBL#1.1"); add(s, d, "CBL#1.2")
    with patch.object(integrations, "render_and_send", side_effect=[PrintError("offline"), None]):
        result = batch(data, cables=["1.1", "1.2"])
    assert result.printed == 1
    assert not result.ok
    assert [r.status for r in result.results] == ["error", "printed"]


@pytest.mark.parametrize('query, expected', [('8', [0]), ('8.*', [0, 1]), ('8.', [0, 1]), ('8.1', [1])])
def test_cable_search_does_not_match_lu_or_su_numbers(data, query, expected):
    s, d, _ = data
    ids = [add(s, d, t) for t in [
        'LU#1 | SU#01 | CBL#8 | 300ft',
        'LU#1 | SU#01 | CBL# | 8.1 | 300ft',
        'LU#8 | SU#8 | CBL#50.1 | 300ft',
        'LU #8 | SU #8 | CBL#80.1 | 300ft',
        'LU#8.1 | CBL#18.1 | 300ft',
        'CBL#8.10 | 300ft' if query == '8.1' else 'CBL#80 | 300ft',
    ]]
    result = labels.search(q=query, project_id=None, data_hall_id=None,
                           discipline_id=d.id, limit=500, offset=0, session=s)
    assert [h.label_id for h in result.hits] == [ids[i] for i in expected]


@pytest.mark.parametrize('prefix', ['CBL#', 'CBL # | ', 'CAT6 #', 'LC #', 'MPO #', '#', '| #'])
def test_supported_cable_markers(prefix):
    from app.search import cable_query_pattern
    assert cable_query_pattern('8.*').search(prefix + '8.1 | 300ft')
    assert not cable_query_pattern('8.1').search(prefix + '8.10 | 300ft')


def test_batch_does_not_print_lu_number_matches(data):
    s, d, _ = data
    wanted = add(s, d, 'LU#1 | CBL#8.1')
    add(s, d, 'LU#8 | CBL#50.1')
    with patch.object(integrations, 'render_and_send') as send:
        result = batch(data, cable='8.*')
    assert result.printed == send.call_count == 1
    assert result.results[0].label_id == wanted


@pytest.mark.parametrize('query', ['8', '8.1'])
def test_exact_numeric_search_excludes_extended_identifiers(data, query):
    s, d, _ = data
    wanted = add(s, d, f'LU#1 | CBL#{query} | 300ft')
    for suffix in ['-B', '-B.1', '-B.6', 'A', '_B', '.1', '0']:
        add(s, d, f'LU#1 | CBL#{query}{suffix} | 300ft')
    result = labels.search(q=query, project_id=None, data_hall_id=None,
                           discipline_id=d.id, limit=500, offset=0, session=s)
    assert [hit.label_id for hit in result.hits] == [wanted]


def test_exact_batch_does_not_print_hyphenated_cable_family(data):
    s, d, _ = data
    wanted = add(s, d, 'CBL#8 | 300ft')
    add(s, d, 'CBL#8-B | 300ft')
    add(s, d, 'CBL#8-B.1 | 300ft')
    with patch.object(integrations, 'render_and_send') as send:
        result = batch(data, cable='8')
    assert result.printed == send.call_count == 1
    assert result.results[0].label_id == wanted


@pytest.mark.parametrize('query', ['8.', '8.*'])
def test_numeric_group_excludes_other_identifier_families(data, query):
    s, d, _ = data
    wanted = [add(s, d, f'CBL#{cable}') for cable in ['8', '8.1', '8.2']]
    for cable in ['80', '8-B', '8-B.1', '8.1-B', '8A', '8_B']:
        add(s, d, f'CBL#{cable}')
    result = labels.search(q=query, project_id=None, data_hall_id=None,
                           discipline_id=d.id, limit=500, offset=0, session=s)
    assert [hit.label_id for hit in result.hits] == wanted


def test_hyphenated_identifier_is_still_searchable_as_text():
    from app.search import cable_query_pattern
    assert cable_query_pattern('8-B').search('CBL#8-B.1 | 300ft')


# Real label shapes, including the ones where Python's case folding reaches
# further than SQLite's: 'ſ' for 's' and U+212A for 'k'.
LABEL_SHAPES = [
    'WH1D9-U18-P37/1\nCH1C1-U18-P1/1\n8k-IBLFSP-001 | SU1\n144S SMF | CBL#1.1 | 78m',
    'AS-T1 | LU#1 | SU01 | CBL# | 1.1 | 270ft',
    'LU#8 | SU#8 | CBL#50.1 | 300ft',
    'CBL#8-B.1 | 300ft',
    'CBL#8 | 2026-11-06 | 7-3 | 300ft',
    '#20.18 | 300ft',
    'FAC | RU32/33 | FAC-AS1-1 | et-0/0/36:0',
    'CBL#9 | 100% | a_b | ſpecial | Kelvin',
    'CBL#9.37 | КАБЕЛЬ | 300ft',
    'DH26 AS-T1 | SOURCE',
]

PREFILTER_QUERIES = [
    '8', '8.1', '8.*', '8.', '9', '1.1', '20.18', '20.*', '50.1', '8-B',
    '1.1,1.2', '1-3', '45.5,6,7', ' 1 - 2 ', '#8', '# 8', 'smf', 'SMF',
    '144S SMF', 'et-0/0/36:0', '2026-11-06', '7-3', '100%', 'a_b', 'special',
    'KELVIN', 'кабель', 'zzz-no-hit',
]


def _sqlite_like(pattern, text):
    """SQLite deciding the prefilter exactly as ``ilike`` emits it."""
    with closing(sqlite3.connect(':memory:')) as conn:
        return bool(conn.execute(r"select lower(?) like lower(?) escape '\'",
                                 (text, pattern)).fetchone()[0])


@pytest.mark.parametrize('query', PREFILTER_QUERIES)
def test_like_prefilter_never_narrows_the_regex(query):
    for ok, single in map(validate_query, parse_batch_query(query)):
        if not ok:
            continue
        for text in LABEL_SHAPES:
            if cable_query_pattern(single).search(text):
                assert _sqlite_like(like_prefilter(single), text), (single, text)


@pytest.mark.parametrize('query', PREFILTER_QUERIES)
def test_sql_prefilter_returns_the_same_hits_as_the_full_scan(data, monkeypatch, query):
    s, d, _ = data
    for text in LABEL_SHAPES:
        add(s, d, text)
    def run():
        return labels.search(q=query, project_id=None, data_hall_id=None,
                             discipline_id=d.id, limit=500, offset=0, session=s)
    prefiltered = run()
    monkeypatch.setattr(labels, 'MAX_PREFILTER_TERMS', -1)  # the former full scan
    scanned = run()
    assert prefiltered == scanned


class CountingPattern:
    """A compiled pattern that records how many rows it is asked about."""

    def __init__(self, pattern):
        self.pattern, self.calls = pattern, 0

    def search(self, text):
        self.calls += 1
        return self.pattern.search(text)


def test_prefilter_keeps_the_regex_off_hopeless_rows(data, monkeypatch):
    s, d, _ = data
    for i in range(1, 51):
        add(s, d, f'CBL#9.{i} | 300ft')
    built = []
    def counting(query):
        built.append(CountingPattern(cable_query_pattern(query)))
        return built[-1]
    monkeypatch.setattr(labels, 'cable_query_pattern', counting)
    result = labels.search(q='9.37', project_id=None, data_hall_id=None,
                           discipline_id=d.id, limit=500, offset=0, session=s)
    assert len(result.hits) == 1
    # Both sides of the one plausible row, where the old scan read all fifty.
    assert built[0].calls == 2
