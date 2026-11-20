import test from 'node:test';
import assert from 'node:assert/strict';
import { createdLabel, keyRequest, lastUsedLabel, parseServerTime, projectTitle, purposeLabel, scopeSummary } from '../src/data/integrationKeys.ts';

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
test('last used reads as relative time, or never used',()=>{
 const now=Date.parse('2026-11-20T12:00:00Z');
 assert.equal(lastUsedLabel(null,now),'Never used');
 assert.equal(lastUsedLabel(undefined,now),'Never used');
 assert.equal(lastUsedLabel('2026-11-20T11:59:30+00:00',now),'Last used just now');
 assert.equal(lastUsedLabel('2026-11-20T11:55:00Z',now),'Last used 5 minutes ago');
 assert.equal(lastUsedLabel('2026-11-20T09:00:00Z',now),'Last used 3 hours ago');
 assert.equal(lastUsedLabel('2026-11-18T12:00:00Z',now),'Last used 2 days ago');
 assert.equal(lastUsedLabel('2026-10-01T12:00:00Z',now),'Last used 1 month ago');
});
test('server times without an offset are read as UTC',()=>{
 assert.equal(parseServerTime('2026-11-20T12:00:00'),Date.parse('2026-11-20T12:00:00Z'));
 assert.equal(parseServerTime('2026-11-20T12:00:00.123456+00:00'),Date.parse('2026-11-20T12:00:00.123Z'));
 assert.equal(lastUsedLabel('2026-11-20T11:00:00',Date.parse('2026-11-20T12:00:00Z')),'Last used 1 hour ago');
 assert.equal(lastUsedLabel('garbage',0),'Last used at an unknown time');
});
test('project assignments show the FloorHub name and fall back to the ID',()=>{
 const id='12345678-1234-4234-8234-123456789abc';
 assert.deepEqual(projectTitle({external_project_id:id,external_project_name:'Nscale Loughton'}),{title:'Nscale Loughton',id});
 assert.deepEqual(projectTitle({external_project_id:id,external_project_name:'  '}),{title:`FloorHub project ${id}`,id:null});
 assert.deepEqual(projectTitle({external_project_id:id,external_project_name:null}),{title:`FloorHub project ${id}`,id:null});
 assert.deepEqual(projectTitle({external_project_id:id}),{title:`FloorHub project ${id}`,id:null});
});
test('scope summary uses readable permission names',()=>{
 assert.equal(scopeSummary(['policy.read','print']),'Read assignments · Print cable labels');
 assert.equal(scopeSummary([]),'No permissions');
});
test('created label is a short US date',()=>{
 assert.match(createdLabel('2026-11-20T12:00:00Z'),/^Created Nov 2[01], 2026$/);
 assert.equal(createdLabel('nope'),'Created');
});
