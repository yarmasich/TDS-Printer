import test from 'node:test';
import assert from 'node:assert/strict';
import { clampMinimumFont, calibrationPending, draftChanged } from '../src/data/templateEditorSafety.ts';

test('minimum font follows either reduced side including preset changes', () => {
  assert.equal(clampMinimumFont(7, 5, 8), 5);
  assert.equal(clampMinimumFont(7, 8, 3), 3);
  assert.equal(clampMinimumFont(4, 12, 12), 4);
});
test('corrections and unprocessed measurements both count as pending work', () => {
  assert.equal(calibrationPending(0, 0, 0, 0, 0, 0), false);
  assert.equal(calibrationPending(1, 0, 0, 0, 0, 0), true);
  assert.equal(calibrationPending(0, 0, 0, 0, 0.5, 0), true);
});
test('draft comparisons detect nested edits without depending on object identity', () => {
  const snapshot = JSON.stringify({ left_text:'original', left_pt:7 });
  assert.equal(draftChanged(snapshot, { left_text:'original', left_pt:7 }), false);
  assert.equal(draftChanged(snapshot, { left_text:'changed', left_pt:7 }), true);
});

test('concurrent leave requests share one decision and a settled decision can be requested again', async () => {
  const { singleLeaveDecision } = await import('../src/data/templateEditorSafety.ts');
  let calls = 0;
  let answer;
  const leave = singleLeaveDecision(() => { calls++; return new Promise(resolve => { answer = resolve; }); });
  const first = leave();
  const second = leave();
  assert.equal(calls, 1);
  answer(false);
  assert.deepEqual(await Promise.all([first, second]), [false, false]);
  const retry = leave();
  assert.equal(calls, 2);
  answer(true);
  assert.equal(await retry, true);
});
