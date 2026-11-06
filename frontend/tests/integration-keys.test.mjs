import test from 'node:test';
import assert from 'node:assert/strict';
import { keyRequest, purposeLabel } from '../src/data/integrationKeys.ts';

test('scoped key creation sends only explicitly selected scoped permissions',()=>{
 assert.deepEqual(keyRequest(' Rotated FloorHub ',['policy.read','print']),{name:'Rotated FloorHub',scopes:['policy.read','print']});
 assert.throws(()=>keyRequest('FloorHub',['legacy_print']),/scope/i);
 assert.throws(()=>keyRequest('FloorHub',['print','print']),/scope/i);
});
test('empty name or permissions cannot accidentally create a credential',()=>{
 assert.throws(()=>keyRequest(' ',['print']),/name/i);
 assert.throws(()=>keyRequest('FloorHub',[]),/scope/i);
});
test('purpose labels distinguish cable labels, QR and unsupported drivers',()=>{
 assert.equal(purposeLabel(['qr_labels']),'QR labels');
 assert.equal(purposeLabel(['cable_labels']),'Cable labels');
 assert.equal(purposeLabel([]),'No supported print type');
});
