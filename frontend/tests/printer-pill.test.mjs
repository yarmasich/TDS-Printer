import test from 'node:test';
import assert from 'node:assert/strict';
import { pillFor, warningSuffix, withWarnings } from '../src/data/printerPill.ts';

const reachable = (state, warnings) => ({ printer_id: 1, ok: true, ms: 4, error: '', device_status: state ? { state, ...(warnings ? { warnings } : {}) } : null });

test('a printer that accepts TCP but reports a fault is not shown as online', () => {
  // A DP4600H with its head open still answers on 9100; only SNMP knows.
  assert.deepEqual([pillFor(reachable('cover_open')).label, pillFor(reachable('cover_open')).tone], ['cover open', 'danger']);
  assert.deepEqual([pillFor(reachable('no_media')).label, pillFor(reachable('no_media')).tone], ['no labels', 'danger']);
  assert.deepEqual([pillFor(reachable('error')).label, pillFor(reachable('error')).tone], ['printer error', 'danger']);
});

test('every fault tells the operator what to do', () => {
  for (const state of ['cover_open', 'no_media', 'error']) assert.ok(pillFor(reachable(state)).title);
});

test('a ready, unknown or unsupported state keeps the plain online pill', () => {
  for (const state of ['ready', 'unknown', null]) {
    assert.deepEqual(pillFor(reachable(state)), { label: 'online · 4 ms', tone: 'ok' });
  }
});

test('a printer printing another job reads as printing, not as a fault', () => {
  assert.deepEqual(pillFor(reachable('busy')), { label: 'printing', tone: 'warn' });
});

test('a fault found while this server holds the printer outranks the busy pill', () => {
  // Paper ran out mid-job: TCP is skipped as busy, SNMP still answers.
  const ping = { printer_id: 1, ok: false, ms: null, error: 'Printer busy; status check skipped', device_status: { state: 'no_media' } };
  assert.equal(pillFor(ping).label, 'no labels');
  assert.equal(pillFor({ ...ping, device_status: null }).label, 'busy');
});

test('the existing loading, unknown and offline pills are unchanged', () => {
  assert.deepEqual(pillFor(undefined), { label: 'unknown', tone: 'muted' });
  assert.deepEqual(pillFor(null), { label: 'checking…', tone: 'checking' });
  assert.deepEqual(pillFor({ printer_id: 1, ok: false, ms: null, error: 'refused' }),
    { label: 'offline', tone: 'danger', title: 'refused' });
});

test('a ready printer with a warning shows the state, then the warning', () => {
  assert.equal(pillFor(reachable('ready', ['ribbon_low'])).label, 'Ready · ribbon low');
  assert.equal(pillFor(reachable('ready', ['media_low'])).label, 'Ready · labels low');
  assert.equal(pillFor(reachable('ready', ['maintenance_due'])).label, 'Ready · maintenance due');
  assert.equal(pillFor(reachable('ready', ['media_low', 'ribbon_low'])).label, 'Ready · labels low · ribbon low');
  const pill = pillFor(reachable('ready', ['ribbon_low']));
  // Not a fault: a warning tone, and the title says printing still works.
  assert.equal(pill.tone, 'warn');
  assert.match(pill.title, /^Printing works\. Ribbon is running low\.$/);
});

test('a printing printer keeps its warnings next to the state', () => {
  assert.deepEqual(pillFor(reachable('busy', ['ribbon_low'])),
    { label: 'Printing · ribbon low', tone: 'warn', title: 'Printing works. Ribbon is running low.' });
});

test('a fault keeps its label and adds the warning to its advice', () => {
  const pill = pillFor(reachable('no_media', ['media_low']));
  assert.equal(pill.label, 'no labels');
  assert.equal(pill.tone, 'danger');
  assert.equal(pill.title, 'Load labels, then print. Labels are running low.');
});

test('no, empty or unrecognised warnings leave every pill unchanged', () => {
  for (const warnings of [undefined, [], ['tray_missing'], ['toString']]) {
    assert.deepEqual(pillFor(reachable('ready', warnings)), { label: 'online · 4 ms', tone: 'ok' });
    assert.deepEqual(pillFor(reachable('busy', warnings)), { label: 'printing', tone: 'warn' });
  }
  // An unknown state never turns into "Ready", even beside a warning.
  assert.deepEqual(pillFor(reachable('unknown', ['ribbon_low'])), { label: 'online · 4 ms', tone: 'ok' });
});

test('warning text is sentence case without capitals', () => {
  assert.equal(warningSuffix(['media_low', 'ribbon_low', 'maintenance_due']), ' · labels low · ribbon low · maintenance due');
  assert.equal(warningSuffix(null), '');
  assert.equal(withWarnings('Cover open', ['ribbon_low']), 'Cover open · ribbon low');
});
