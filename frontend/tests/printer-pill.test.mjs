import test from 'node:test';
import assert from 'node:assert/strict';
import { pillFor } from '../src/data/printerPill.ts';

const reachable = (state) => ({ printer_id: 1, ok: true, ms: 4, error: '', device_status: state ? { state } : null });

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
