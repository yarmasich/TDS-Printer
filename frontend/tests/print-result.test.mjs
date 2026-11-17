import test from 'node:test';
import assert from 'node:assert/strict';
import { printFailureDetail } from '../src/data/printResult.ts';

const fault = 'Printer P cover is open. Close it, then print again.';

test('a printer fault held for a whole cart is said once, not once per label', () => {
  const errors = Array.from({ length: 50 }, (_, i) => ({ item_id: i, error: fault, uncertain: false }));
  assert.equal(printFailureDetail('', errors), fault);
});

test('distinct failures keep their order after the per-printer summary', () => {
  const errors = [
    { item_id: 1, error: fault },
    { item_id: 2, error: 'Template is missing; check the discipline settings.' },
    { item_id: 3, error: fault },
  ];
  assert.equal(
    printFailureDetail('Healthy: 1 sent', errors),
    `Healthy: 1 sent; ${fault}; Template is missing; check the discipline settings.`,
  );
});
