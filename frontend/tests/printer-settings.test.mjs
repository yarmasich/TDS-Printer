import test from 'node:test';
import assert from 'node:assert/strict';
import { communityUpdate, printerMediaMismatch, printerQrDefaults, shouldApplyPrinterDefaults } from '../src/data/printerSettings.ts';

test('community is omitted unless replacement or reset explicitly selected', () => {
  assert.deepEqual(communityUpdate('keep', 'accidental-autofill'), {});
  assert.deepEqual(communityUpdate('reset', 'accidental-autofill'), {snmp_community:null});
  assert.deepEqual(communityUpdate('replace', 'sample-community'), {snmp_community:'sample-community'});
  assert.throws(() => communityUpdate('replace', ''), /1–128/);
  assert.throws(() => communityUpdate('replace', 'é'.repeat(65)), /1–128/);
  assert.equal(communityUpdate('replace', 'é'.repeat(64)).snmp_community.length, 64);
});
test('old server fallback keeps historical QR workspace media and length', () => {
  assert.deepEqual(printerQrDefaults(), {media:'DK-2246',length_mm:60});
  assert.deepEqual(printerQrDefaults({qr_media_id:'DK-2205',qr_label_length_mm:45}), {media:'DK-2205',length_mm:45});
});
test('printer defaults only initialize clean settings without a preview or intent', () => {
  assert.equal(shouldApplyPrinterDefaults(0, 2, false, false), true);
  assert.equal(shouldApplyPrinterDefaults(1, 2, false, false), true);
  assert.equal(shouldApplyPrinterDefaults(2, 2, false, false), false);
  assert.equal(shouldApplyPrinterDefaults(1, 2, true, false), false);
  assert.equal(shouldApplyPrinterDefaults(1, 2, false, true), false);
  assert.equal(shouldApplyPrinterDefaults(0, 0, false, false), false);
});

test('DK-2246 accepts Brother 104mm media reporting while detecting true roll mismatches', () => {
  assert.equal(printerMediaMismatch('DK-2246', 104, 'continuous'), false);
  assert.equal(printerMediaMismatch('DK-2246', 103, 'continuous'), false);
  assert.equal(printerMediaMismatch('DK-2205', 62, 'continuous'), false);
  assert.equal(printerMediaMismatch('DK-2205', 104, 'continuous'), true);
  assert.equal(printerMediaMismatch('DK-2246', 62, 'continuous'), true);
  assert.equal(printerMediaMismatch('DK-2205', 62, 'die_cut'), true);
  assert.equal(printerMediaMismatch('DK-2205', null, 'unknown'), false);
});

test('supported Panduit models expose SNMP while QR defaults remain Brother-only', async () => {
  const {readFile} = await import('node:fs/promises');
  const view = await readFile(new URL('../src/components/admin/PrintersSection.vue', import.meta.url), 'utf8');
  assert.match(view, /const panduitSnmp = computed\(\(\) => \['DP4300M', 'DP4300H', 'DP4600H'\]\.includes\(form\.model\)\)/);
  assert.match(view, /v-if="selectedBrand === 'brother' \|\| panduitSnmp">\s*<h3[^>]*>Device status/);
  assert.match(view, /v-if="selectedBrand === 'brother'">\s*<h3[^>]*>QR label defaults/);
});
