import test from 'node:test';
import assert from 'node:assert/strict';
import {createPinia,setActivePinia} from 'pinia';
import {useCart} from '../src/stores/cart.ts';
import {useProjects} from '../src/stores/projects.ts';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
function setup(){setActivePinia(createPinia()); const m=new Map();globalThis.localStorage={getItem:k=>m.get(k),setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)};globalThis.sessionStorage=globalThis.localStorage;}
test('Print and Kiosk keep independent carts and session IDs for actions',async()=>{
 setup();const requests=[];globalThis.fetch=async(url,init)=>{requests.push({url,body:JSON.parse(init.body||'null')});return new Response(JSON.stringify(init.method==='GET'?[{id:url.includes('sid=')?url:''}]:{}));};
 const print=useCart('print'),kiosk=useCart('kiosk');assert.notEqual(print,kiosk);
 await print.add(1);await kiosk.add(2);assert.notEqual(requests[0].body.sid,requests[2].body.sid);assert.notDeepEqual(print.items,kiosk.items);
});
test('older cart fetch cannot replace a newer snapshot',async()=>{setup();const a=deferred(),b=deferred();let n=0;globalThis.fetch=()=>++n===1?a.promise:b.promise;const cart=useCart('print');const first=cart.fetch(),second=cart.fetch();b.resolve(new Response(JSON.stringify([{id:2}])));await second;a.resolve(new Response(JSON.stringify([{id:1}])));await first;assert.equal(cart.items[0].id,2);});
test('older project request cannot restore disciplines after project changes',async()=>{setup();const a=deferred(),b=deferred();let n=0;globalThis.fetch=()=>++n===1?a.promise:b.promise;const projects=useProjects();const first=projects.loadDisciplinesForProject(1),second=projects.loadDisciplinesForProject(2);b.resolve(new Response(JSON.stringify([{id:2}])));await second;a.resolve(new Response(JSON.stringify([{id:1}])));await first;assert.equal(projects.disciplines[0].id,2);});
test('clearing context invalidates pending search and loading state',async()=>{
 const {useLatestResource}=await import('../src/composables/latestResource.ts');const state=useLatestResource();const a=deferred();const pending=state.run(()=>a.promise);state.clear();a.resolve({hits:[1]});await pending;assert.equal(state.data.value,null);assert.equal(state.loading.value,false);
});
test('latest search wins and old failures do not erase current results',async()=>{
 const {useLatestResource}=await import('../src/composables/latestResource.ts');const state=useLatestResource();let reject;const first=state.run(()=>new Promise((_,r)=>reject=r));await state.run(async()=>({hits:[2]}));reject(new Error('old error'));await first;assert.deepEqual(state.data.value,{hits:[2]});assert.equal(state.error.value,'');
});
test('print failure refreshes cart and never resends uncertain items',async()=>{
 setup();let posts=0;globalThis.fetch=async(url,init)=>{if(init.method==='POST'){posts++;return new Response(JSON.stringify({detail:'active'}),{status:409});}return new Response(JSON.stringify([{id:1,status:'uncertain',error:'Check printer'}]));};
 const cart=useCart('kiosk');cart.items=[{id:1,status:'queued'}];await assert.rejects(cart.printAll(),/already active/);assert.equal(cart.items[0].status,'uncertain');assert.equal(cart.printing,false);await assert.rejects(cart.printAll(),/No queued labels/);assert.equal(posts,1);
});
test('all kiosk cart actions retain the kiosk session',async()=>{
 setup();const requests=[];globalThis.fetch=async(url,init)=>{requests.push({url,body:JSON.parse(init.body||'null')});return new Response(JSON.stringify(init.method==='GET'?[{id:1,status:'queued'}]:{ok:1,errors:[],log_ids:[]}));};
 const cart=useCart('kiosk');await cart.fetch();await cart.addMany([1,2]);await cart.remove(1);await cart.printAll();await cart.clear();const sid=localStorage.getItem('tds.sid.kiosk');assert.ok(sid);assert.equal(localStorage.getItem('tds.sid.print'),undefined);for(const r of requests) assert.ok(r.body?r.body.sid===sid:r.url.includes(encodeURIComponent(sid)));
});
test('clearing cart during active printing is blocked before mutation',async()=>{setup();let called=false;globalThis.fetch=async()=>{called=true;return new Response('[]');};const cart=useCart();cart.items=[{id:1,status:'printing'}];await assert.rejects(cart.clear(),/Printing/);assert.equal(called,false);});
test('clearing project invalidates pending discipline requests',async()=>{setup();const a=deferred();globalThis.fetch=()=>a.promise;const projects=useProjects();const pending=projects.loadDisciplinesForProject(1);projects.clearDisciplines();a.resolve(new Response('[{"id":1}]'));await pending;assert.deepEqual(projects.disciplines,[]);assert.equal(projects.loadingDisciplines,false);});
test('cart refresh failure preserves active-print explanation',async()=>{setup();globalThis.fetch=async(url,init)=>init.method==='POST'?new Response('{"detail":"active"}',{status:409}):new Response('{"detail":"offline"}',{status:503});const cart=useCart();cart.items=[{id:1,status:'queued'}];await assert.rejects(cart.printAll(),/already active/);assert.equal(cart.printing,false);assert.equal(cart.error,'offline');});
test('unmounted project owner cannot publish a pending response',async()=>{setup();const a=deferred();globalThis.fetch=()=>a.promise;const projects=useProjects();let active=true;const pending=projects.loadDisciplinesForProject(1,()=>active);active=false;a.resolve(new Response('[{"id":1}]'));await pending;assert.deepEqual(projects.disciplines,[]);});
test('unmounted project owner cannot publish a pending failure',async()=>{setup();const a=deferred();globalThis.fetch=()=>a.promise;const projects=useProjects();let active=true;const pending=projects.loadDisciplinesForProject(1,()=>active);active=false;a.resolve(new Response('{"detail":"old project failed"}',{status:500}));await assert.rejects(pending);assert.equal(projects.disciplineError,'');});
