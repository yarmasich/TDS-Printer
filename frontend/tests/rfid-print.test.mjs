import test from 'node:test';
import assert from 'node:assert/strict';
import { useRfidPrint } from '../src/composables/useRfidPrint.ts';
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
test('off policy prints once despite double click during policy lookup', async () => {
  const policy = deferred(); const calls = [];
  const flow = useRfidPrint(() => policy.promise, async code => { calls.push(code); });
  const first = flow.start(); await flow.start();
  assert.equal(flow.busy.value, true);
  policy.resolve({ requires_rfid: false, configured: false }); await first;
  assert.deepEqual(calls, [undefined]);
});
test('required unconfigured integration blocks printing', async () => {
  let calls = 0;
  const flow = useRfidPrint(async () => ({ requires_rfid: true, configured: false }), async () => { calls++; });
  await flow.start(); flow.code.value = '00123'; await flow.submit();
  assert.equal(calls, 0); assert.match(flow.error.value, /not configured/);
});
test('scan keeps leading zeros, consumes once, and clears after completion', async () => {
  const print = deferred(); const calls = [];
  const flow = useRfidPrint(async () => ({ requires_rfid: true, configured: true }), async code => { calls.push(code); await print.promise; });
  await flow.start(); assert.equal(flow.open.value, true);
  flow.code.value = '00123'; const first = flow.submit(); await flow.submit();
  assert.deepEqual(calls, ['00123']); assert.equal(flow.code.value, '');
  print.resolve(); await first;
  assert.equal(flow.open.value, false); assert.equal(flow.busy.value, false);
});
test('failed request is never retried automatically and requires a fresh scan', async () => {
  let calls = 0;
  const flow = useRfidPrint(async () => ({ requires_rfid: true, configured: true }), async () => { calls++; throw new Error('Connection lost'); });
  await flow.start(); flow.code.value = '00123'; await flow.submit(); await flow.submit();
  assert.equal(calls, 1); assert.equal(flow.code.value, ''); assert.equal(flow.open.value, true);
  assert.match(flow.error.value, /Connection lost/);
  flow.code.value = 'another'; flow.close(); assert.equal(flow.code.value, '');
});
test('failed policy lookup cannot submit or print', async () => {
  let calls = 0;
  const flow = useRfidPrint(async () => { throw new Error('Offline'); }, async () => { calls++; });
  await flow.start(); flow.code.value = '00123'; await flow.submit();
  assert.equal(calls, 0); assert.match(flow.error.value, /Offline/);
});
