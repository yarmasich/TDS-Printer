import test from 'node:test';
import assert from 'node:assert/strict';
import {createPinia,setActivePinia} from 'pinia';
import {api, requestAuthHeader} from '../src/api/client.ts';
import {useStationAuth} from '../src/stores/stationAuth.ts';
import {useCart} from '../src/stores/cart.ts';
import {useSession} from '../src/stores/session.ts';
function setup(){setActivePinia(createPinia());const map=new Map();globalThis.sessionStorage=globalThis.localStorage={getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};sessionStorage.setItem('tds-admin-token','admin');sessionStorage.setItem('tds-station-token','station-a');sessionStorage.setItem('tds-station-id','1');}
const deferred=()=>{let resolve;return {promise:new Promise(r=>resolve=r),resolve:v=>resolve(v)}};
test('operator and admin authorization stay independent',()=>{setup();assert.equal(requestAuthHeader('/api/cart?sid=x').Authorization,'Bearer station-a');assert.equal(requestAuthHeader('/api/labels/4/preview').Authorization,'Bearer station-a');assert.equal(requestAuthHeader('/api/print').Authorization,'Bearer station-a');assert.equal(requestAuthHeader('/api/print/test').Authorization,'Bearer admin');assert.equal(requestAuthHeader('/api/stations').Authorization,'Bearer admin');assert.deepEqual(requestAuthHeader('/api/station-auth/login'),{});sessionStorage.removeItem('tds-station-token');assert.deepEqual(requestAuthHeader('/api/cart'),{});});
test('failed station login preserves admin session',async()=>{setup();globalThis.fetch=async()=>new Response('{"detail":"Invalid credentials"}',{status:401});await assert.rejects(api.post('/api/station-auth/login',{}));assert.equal(sessionStorage.getItem('tds-admin-token'),'admin');});
test('delayed unauthorized response cannot sign out new station',async()=>{setup();const pending=deferred();globalThis.fetch=()=>pending.promise;const request=api.get('/api/cart?sid=x');sessionStorage.setItem('tds-station-token','station-b');pending.resolve(new Response('{}',{status:401}));await assert.rejects(request);assert.equal(sessionStorage.getItem('tds-station-token'),'station-b');});
test('station account keeps its own Print and Kiosk cart IDs',()=>{setup();const session=useSession();const first=session.ensure();assert.notEqual(first,session.ensure('kiosk'));sessionStorage.setItem('tds-station-id','2');assert.notEqual(first,session.ensure());sessionStorage.setItem('tds-station-id','1');assert.equal(first,session.ensure());});
test('logout clears both local carts and rejects old snapshots',async()=>{setup();const pending=deferred();globalThis.fetch=()=>pending.promise;const cart=useCart();useCart('kiosk').items=[{id:2}];const request=cart.fetch();useStationAuth().logout();pending.resolve(new Response('[{"id":1}]'));await request;assert.deepEqual(cart.items,[]);assert.deepEqual(useCart('kiosk').items,[]);assert.equal(sessionStorage.getItem('tds-admin-token'),'admin');});
test('bulk add stops when station changes during a request',async()=>{setup();const pending=deferred();let calls=0;globalThis.fetch=()=>{calls++;return pending.promise};const request=useCart().addMany([1,2,3]);sessionStorage.setItem('tds-station-token','station-b');pending.resolve(new Response('{}'));await request;assert.equal(calls,1);});
test('an unauthorized print releases the cart lock even though it clears the station token',async()=>{setup();globalThis.fetch=async(url,init)=>init.method==='POST'?new Response('{"detail":"Station session expired"}',{status:401}):new Response('[]');const cart=useCart();cart.items=[{id:1,status:'queued'}];await assert.rejects(cart.printAll(),/Station session expired/);assert.equal(sessionStorage.getItem('tds-station-token'),null);assert.equal(cart.printing,false);assert.equal(cart.hasPrinting,false);});
test('a stale print cannot release the lock the next station holds',async()=>{setup();const first=deferred(),second=deferred();let n=0;globalThis.fetch=()=>++n===1?first.promise:n===2?second.promise:Promise.resolve(new Response('[]'));const cart=useCart();cart.items=[{id:1,status:'queued'}];const stale=cart.printAll();useStationAuth().logout();sessionStorage.setItem('tds-station-token','station-b');cart.items=[{id:2,status:'queued'}];const current=cart.printAll();first.resolve(new Response('{}',{status:409}));await assert.rejects(stale);assert.equal(cart.printing,true);second.resolve(new Response('{}'));await current;assert.equal(cart.printing,false);});
test('a backend outage keeps the print page reachable while a revoked session fails closed',async()=>{setup();sessionStorage.removeItem('tds-station-token');const auth=useStationAuth();globalThis.fetch=async()=>new Response('{"required":false}');await auth.restore();assert.equal(auth.required,false);
 for(const outage of [async()=>{throw new TypeError('Failed to fetch')},async()=>new Response('{"detail":"offline"}',{status:503})]){globalThis.fetch=outage;await auth.restore();assert.equal(auth.required,false);assert.equal(auth.error,'');}
 sessionStorage.setItem('tds-station-token','station-a');globalThis.fetch=async(url)=>url.endsWith('/status')?new Response('{"required":false}'):new Response('{"detail":"Station session expired"}',{status:401});await auth.restore();assert.equal(auth.required,true);assert.equal(auth.error,'Station session expired');assert.equal(auth.station,null);assert.equal(sessionStorage.getItem('tds-station-token'),null);});

test('saving RFID settings uses the admin token even with a station session', async () => {
  setup();
  globalThis.fetch = async (_url, request) => {
    assert.equal(request.method, 'PATCH');
    assert.equal(request.headers.Authorization, 'Bearer admin');
    assert.deepEqual(JSON.parse(request.body), { require_rfid: false });
    return new Response(JSON.stringify({ id: 1, require_rfid: false }));
  };
  assert.equal((await api.patch('/api/projects/1', { require_rfid: false })).require_rfid, false);
  assert.equal(sessionStorage.getItem('tds-admin-token'), 'admin');
  assert.equal(sessionStorage.getItem('tds-station-token'), 'station-a');
});

test('a rejected shared catalogue read only clears the token it sent', async () => {
  setup();
  globalThis.fetch = async (_url, request) => {
    assert.equal(request.headers.Authorization, 'Bearer station-a');
    return new Response('{"detail":"Expired token"}', { status: 401 });
  };
  await assert.rejects(api.get('/api/projects'), { status: 401 });
  assert.equal(sessionStorage.getItem('tds-admin-token'), 'admin');
  assert.equal(sessionStorage.getItem('tds-station-token'), null);
});
