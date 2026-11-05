import test from 'node:test';
import assert from 'node:assert/strict';
import { QrPrintIntent, newQrRequestKey, qrOutcome } from '../src/data/qrPrintIntent.ts';

test('auth or validation failure after a lost response never erases possible output',()=>{
  for(const body of [{detail:'Admin login required'},{detail:[{msg:'invalid input'}]},{}]){
    const intent=new QrPrintIntent(()=> 'uuid');
    intent.begin({scan:'X'});intent.record('unknown');
    intent.begin({scan:'X'});intent.record(qrOutcome(false,body));
    assert.equal(intent.requiresCheck,true);
    assert.throws(()=>intent.newAttempt(false));
  }
  assert.equal(qrOutcome(false,{detail:{code:'error_not_sent'}}),'error_not_sent');
});

test('HTTP LAN browsers without randomUUID still get strong distinct request keys',()=>{
  const crypto={getRandomValues(bytes){ for(let n=0;n<bytes.length;n++)bytes[n]=n;return bytes; }};
  assert.match(newQrRequestKey(crypto), /^[0-9a-f]{32}$/);
  assert.throws(()=>newQrRequestKey({}),/secure random/i);
});

test('transport retries reuse a frozen key and body; changed payload cannot silently resend',()=>{
  let id=0;const intent=new QrPrintIntent(()=>String(++id));
  const first=intent.begin({scan:' A ',printer_id:1});
  intent.record('unknown');
  assert.deepEqual(intent.begin({scan:' A ',printer_id:1}),first);
  assert.throws(()=>intent.begin({scan:'B',printer_id:1}),/new label/i);
  assert.throws(()=>intent.newAttempt(false),/check/i);
  intent.newAttempt(true);
  assert.notEqual(intent.begin({scan:' A ',printer_id:1}).key,first.key);
});

test('safe no-send retry permits a new key; sent and unknown require explicit check',()=>{
  for(const code of ['sent','uncertain','in_progress_or_unknown','key_conflict','unknown']){
    const intent=new QrPrintIntent(()=> 'uuid');intent.begin({scan:'X'});intent.record(code);
    assert.equal(intent.requiresCheck,true);
    assert.throws(()=>intent.newAttempt(false));
  }
  const intent=new QrPrintIntent(()=> 'uuid');intent.begin({scan:'X'});intent.record('error_not_sent');
  assert.equal(intent.requiresCheck,false);intent.newAttempt(false);
  assert.equal(intent.active,false);
});
