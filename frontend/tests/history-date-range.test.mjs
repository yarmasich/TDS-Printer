import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
import { ref } from 'vue';
import { historyDateRange } from '../src/utils/historyDateRange.ts';

test('history accepts open-ended dates and converts local values to API timestamps', () => {
  assert.deepEqual(historyDateRange('', ''), {since: undefined, until: undefined, error: ''});
  const range = historyDateRange('2026-10-01T09:00', '');
  assert.equal(range.since, new Date('2026-10-01T09:00').toISOString());
  assert.equal(range.until, undefined);
  assert.equal(range.error, '');
});

test('history rejects reversed and equal exclusive date ranges', () => {
  for (const until of ['2026-10-01T08:00', '2026-10-01T09:00']) {
    assert.match(historyDateRange('2026-10-01T09:00', until).error, /Until must be later than From/);
  }
  assert.equal(historyDateRange('2026-10-01T09:00', '2026-10-01T09:01').error, '');
});

test('history rejects invalid dates instead of throwing or normalizing them', () => {
  for (const value of ['invalid', '2026-02-30T09:00', '2026-13-01T09:00', '2026-10-01T25:00']) {
    assert.match(historyDateRange(value, '').error, /valid From date/);
    assert.match(historyDateRange('', value).error, /valid Until date/);
  }
  assert.equal(historyDateRange('2024-02-29T09:00', '').error, '');
});

test('invalid history range sends no requests and retains the previous results', async () => {
  const source = await readFile(new URL('../src/components/admin/HistorySection.vue', import.meta.url), 'utf8');
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^import .*;\n/gm, '');
  const js = ts.transpileModule(script, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText;
  let requests = 0;
  const page = new Function('ref', 'onMounted', 'onBeforeUnmount', 'api', 'historyDateRange', `${js};return {load, since, until, logs, error, loading};`)(ref, () => {}, () => {}, {get: async () => {requests++; throw new Error('Unexpected request');}}, historyDateRange);
  page.logs.value = [{id: 42}];
  page.since.value = '2026-10-02T09:00';
  page.until.value = '2026-10-01T09:00';
  await page.load();
  assert.equal(requests, 0);
  assert.deepEqual(page.logs.value, [{id: 42}]);
  assert.match(page.error.value, /Filters were not applied/);
  assert.equal(page.loading.value, false);
});
