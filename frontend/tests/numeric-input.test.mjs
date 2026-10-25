import test from 'node:test';
import assert from 'node:assert/strict';
import { boundedNumber } from '../src/data/numericInput.ts';

test('blank and invalid number input cannot replace a valid value with NaN', () => {
  assert.equal(boundedNumber(NaN, 7, 1, 72), 7);
  assert.equal(boundedNumber(Infinity, 4, 1, 72), 4);
});
test('manual input observes the same bounds as controls while retaining fractions and zero', () => {
  assert.equal(boundedNumber(-2, 7, 1, 72), 1);
  assert.equal(boundedNumber(200, 7, 1, 72), 72);
  assert.equal(boundedNumber(0, 5, 0, 20), 0);
  assert.equal(boundedNumber(2.5, 0, 0, 20), 2.5);
});
