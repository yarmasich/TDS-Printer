import test from 'node:test';
import assert from 'node:assert/strict';
import { useAdminRequests, useImportDestination } from '../src/composables/adminRequests.ts';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
test('admin mutations reject repeated taps and expose retryable errors',async()=>{
 const state=useAdminRequests(),d=deferred();let calls=0;
 const first=state.run('save',async()=>{calls++;await d.promise;throw new Error('Offline');});
 await state.run('save',async()=>{calls++;});assert.equal(calls,1);assert.equal(state.busy('save'),true);
 d.resolve();await first;assert.equal(state.error.value,'Offline');assert.equal(state.busy('save'),false);
 await state.run('save',async()=>{});assert.equal(state.error.value,'');
});
test('import destinations clear immediately and ignore older responses',async()=>{
 const a=deferred(),b=deferred();const state=useImportDestination(id=>id===1?a.promise:b.promise);
 const first=state.load(1),second=state.load(2);assert.equal(state.valid(10),false);assert.deepEqual(state.options.value,[]);
 b.resolve([{id:20}]);await second;assert.equal(state.valid(20),true);assert.equal(state.valid(10),false);
 a.resolve([{id:10}]);await first;assert.equal(state.valid(20),true);
 await state.load(null);assert.equal(state.valid(20),false);
});
test('failed import destination load blocks selection until a successful retry',async()=>{
 let fail=true;
 const state=useImportDestination(async()=>{if(fail)throw new Error('Connection lost');return [{id:42}];});
 await state.load(1);assert.equal(state.error.value,'Connection lost');assert.equal(state.valid(42),false);assert.equal(state.loading.value,false);
 fail=false;await state.load(1);assert.equal(state.error.value,'');assert.equal(state.valid(42),true);
});
