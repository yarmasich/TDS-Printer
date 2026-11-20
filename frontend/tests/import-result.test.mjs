import test from 'node:test';
import assert from 'node:assert/strict';
import { importResultToast, replaceHint } from '../src/data/importResult.ts';

test('a plain upload reads as before', () => {
  assert.deepEqual(importResultToast({ rows: 12, sheets: 1, trunk_rows: 0 }),
    { summary: 'Imported 12 rows · 1 sheets', detail: undefined });
  // An older server sends none of the newer counts.
  assert.deepEqual(importResultToast({ rows: 3, sheets: 2 }), { summary: 'Imported 3 rows · 2 sheets', detail: undefined });
});

test('a replacement says how many earlier imports it removed', () => {
  assert.equal(importResultToast({ rows: 5, sheets: 1, replaced_imports: 1, labels_removed: 5 }).summary,
    'Imported 5 rows · 1 sheets · Replaced 1 earlier import');
  assert.equal(importResultToast({ rows: 5, sheets: 1, replaced_imports: 2 }).summary,
    'Imported 5 rows · 1 sheets · Replaced 2 earlier imports');
});

test('trunk rows and duplicate legs are both named, each with its consequence', () => {
  const toast = importResultToast({ rows: 9, sheets: 1, trunk_rows: 2, duplicate_legs: 1 });
  assert.equal(toast.summary, 'Imported 9 rows · 1 sheets · 2 trunk labels left out · 1 duplicate leg');
  assert.match(toast.detail, /^Trunk labels in a leg workbook are not imported\./);
  assert.match(toast.detail, /1 row repeats a Trunk# and Leg # pair/);
  assert.match(importResultToast({ rows: 9, sheets: 1, duplicate_legs: 3 }).detail, /^3 rows repeat/);
});

test('the replace hint counts what will be removed', () => {
  assert.equal(replaceHint([{ rows: 4 }, { rows: 6 }]),
    'Removes 2 earlier imports (10 rows) of this discipline when the new file imports. Print history is kept.');
  assert.match(replaceHint([{ rows: 1 }]), /^Removes 1 earlier import \(1 row\)/);
});
