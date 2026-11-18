import test from 'node:test';
import assert from 'node:assert/strict';
import { createPinia, setActivePinia } from 'pinia';
import { offersTrunk, operatorDisciplines, trunkCaption, trunkTargets } from '../src/data/trunks.ts';
import { useCart } from '../src/stores/cart.ts';

const halls = [{ id: 1, project_id: 1, name: '8k&16k' }, { id: 2, project_id: 2, name: 'DH26' }];
const d = (id, name, hall = 1, trunk = null) => ({ id, name, data_hall_id: hall, trunk_discipline_id: trunk });

test('a result offers its trunk only when its discipline links trunks and the row has a trunk number', () => {
  assert.equal(offersTrunk({ trunk_no: '1' }, d(1, 'Legs', 1, 2)), true);
  assert.equal(offersTrunk({ trunk_no: null }, d(1, 'Legs', 1, 2)), false);  // old file without Trunk#
  assert.equal(offersTrunk({ trunk_no: '1' }, d(1, 'Legs')), false);        // no trunk discipline linked
  assert.equal(offersTrunk({ trunk_no: '1' }, undefined), false);
});

test('the caption names the trunk and leg from the workbook columns', () => {
  assert.equal(trunkCaption({ trunk_no: '1', leg_no: '2' }), 'Trunk 1 · Leg 2');
  assert.equal(trunkCaption({ trunk_no: '7', leg_no: null }), 'Trunk 7');
  assert.equal(trunkCaption({ trunk_no: null, leg_no: null }), '');
});

test('trunk labels come from another discipline of the same project, one level deep', () => {
  // Mirrors the server: no self link, no other project, no chains either way.
  const legs = d(1, '16K-EW-LS'), trunks = d(2, '16K-EW-LS-Trunk'), other = d(3, 'AS-T1', 2), linked = d(4, '8K', 1, 2);
  const all = [legs, trunks, other, linked];
  assert.deepEqual(trunkTargets(legs, all, halls).map((x) => x.name), ['16K-EW-LS-Trunk']);
  assert.deepEqual(trunkTargets(trunks, all, halls), []);  // already holds 8K's trunks
});

function setup() {
  setActivePinia(createPinia());
  const map = new Map();
  globalThis.sessionStorage = globalThis.localStorage = { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v), removeItem: (k) => map.delete(k) };
  sessionStorage.setItem('tds-station-token', 'station-a');
  sessionStorage.setItem('tds-station-id', '1');
}

test('the cart sends the trunk choice with each add', async () => {
  setup();
  const posted = [];
  globalThis.fetch = async (url, init) => {
    if (init?.method === 'POST') posted.push(JSON.parse(init.body));
    return new Response(init?.method === 'POST' ? '{}' : '[]');
  };
  const cart = useCart();
  await cart.add(5, 'with');
  await cart.add(6);
  await cart.addMany([7, 8], 'only');
  assert.deepEqual(posted.map((b) => [b.label_id, b.trunk]), [[5, 'with'], [6, 'none'], [7, 'only'], [8, 'only']]);
});


test('operators see leg disciplines, not the trunk disciplines linked to them', () => {
  const legs = d(1, '16K-EW-LS', 1, 2), trunks = d(2, '16K-EW-LS-Trunk'), plain = d(3, '8K-IBLFSP'), loose = d(4, 'Spare trunks');
  assert.deepEqual(operatorDisciplines([legs, trunks, plain, loose]).map((x) => x.name), ['16K-EW-LS', '8K-IBLFSP', 'Spare trunks']);
});

test('a trunk discipline already chosen stays listed until the choice changes', () => {
  // A kiosk may have remembered it from before it was linked.
  const legs = d(1, '16K-EW-LS', 1, 2), trunks = d(2, '16K-EW-LS-Trunk');
  assert.deepEqual(operatorDisciplines([legs, trunks], 2).map((x) => x.name), ['16K-EW-LS', '16K-EW-LS-Trunk']);
});
