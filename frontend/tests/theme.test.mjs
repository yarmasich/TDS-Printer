import test from 'node:test';
import assert from 'node:assert/strict';
import {createPinia, setActivePinia} from 'pinia';
import {useTheme, resolveDark, nextPreference, isPreference} from '../src/stores/theme.ts';

/** Browser stand-in: a localStorage that can be made to throw, a settable
 *  prefers-color-scheme, and an <html> whose classList we can read back. */
function setup({stored, systemDark = false, storageThrows = false} = {}) {
  const map = new Map();
  if (stored !== undefined) map.set('tds-theme', stored);
  globalThis.localStorage = {
    getItem: k => { if (storageThrows) throw new Error('SecurityError'); return map.get(k) ?? null; },
    setItem: (k, v) => { if (storageThrows) throw new Error('QuotaExceeded'); map.set(k, v); },
    removeItem: k => map.delete(k),
  };
  const classes = new Set();
  globalThis.document = {documentElement: {classList: {
    toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
    contains: name => classes.has(name),
  }}};
  const listeners = [];
  globalThis.window = {matchMedia: () => ({
    matches: systemDark,
    addEventListener: (_, fn) => listeners.push(fn),
  })};
  setActivePinia(createPinia());
  return {
    store: useTheme(),
    isDarkClassOn: () => classes.has('tds-dark'),
    stored: () => map.get('tds-theme'),
    changeSystem: matches => listeners.forEach(fn => fn({matches})),
  };
}

test('resolveDark: an explicit choice wins, auto follows the OS', () => {
  assert.equal(resolveDark('dark', false), true, 'pinned dark ignores a light OS');
  assert.equal(resolveDark('light', true), false, 'pinned light ignores a dark OS');
  assert.equal(resolveDark('system', true), true);
  assert.equal(resolveDark('system', false), false);
});

test('one tap cycles Auto to Light to Dark and back', () => {
  assert.equal(nextPreference('system'), 'light');
  assert.equal(nextPreference('light'), 'dark');
  assert.equal(nextPreference('dark'), 'system');
  assert.equal(isPreference('dark'), true);
  assert.equal(isPreference('sepia'), false);
  assert.equal(isPreference(null), false);
});

test('a tablet whose OS says light still keeps the operator choice across a reload', () => {
  const first = setup({systemDark: false});
  first.store.load();
  assert.equal(first.isDarkClassOn(), false, 'auto on a light OS paints light');
  first.store.cycle();                       // -> light
  first.store.cycle();                       // -> dark
  assert.equal(first.store.preference, 'dark');
  assert.equal(first.isDarkClassOn(), true);
  assert.equal(first.stored(), 'dark', 'the choice is written to localStorage');

  // Reload: same storage contents, fresh store, same light-mode OS.
  const second = setup({stored: 'dark', systemDark: false});
  second.store.load();
  assert.equal(second.store.preference, 'dark');
  assert.equal(second.isDarkClassOn(), true, 'the dark class is re-applied on boot');
});

test('auto tracks a later OS change but a pinned preference does not', () => {
  const auto = setup({systemDark: false});
  auto.store.load();
  auto.changeSystem(true);
  assert.equal(auto.store.dark, true);
  assert.equal(auto.isDarkClassOn(), true);

  const pinned = setup({stored: 'light', systemDark: false});
  pinned.store.load();
  pinned.changeSystem(true);
  assert.equal(pinned.store.dark, false, 'the OS cannot override an explicit choice');
  assert.equal(pinned.isDarkClassOn(), false);
});

test('storage that throws falls back to auto and still applies this session', () => {
  const t = setup({systemDark: true, storageThrows: true});
  t.store.load();
  assert.equal(t.store.preference, 'system');
  assert.equal(t.isDarkClassOn(), true, 'unreadable storage must not block the OS preference');
  t.store.set('light');
  assert.equal(t.store.preference, 'light');
  assert.equal(t.isDarkClassOn(), false, 'an unwritable store still repaints now');
});

test('an unrecognised stored value is ignored rather than trusted', () => {
  const t = setup({stored: 'midnight', systemDark: false});
  t.store.load();
  assert.equal(t.store.preference, 'system');
});

test('loading twice does not stack media listeners', () => {
  const t = setup({systemDark: false});
  t.store.load();
  t.store.load();
  let calls = 0;
  const original = t.store.apply.bind(t.store);
  t.store.apply = () => { calls += 1; original(); };
  t.changeSystem(true);
  assert.equal(calls, 1);
});
