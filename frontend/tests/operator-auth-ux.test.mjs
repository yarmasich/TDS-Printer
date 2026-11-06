import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
import { ref } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
import { useAuth } from '../src/stores/auth.ts';

function setup() {
  setActivePinia(createPinia());
  const storage = new Map();
  globalThis.sessionStorage = {getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k)};
}
const deferred = () => { let resolve; return {promise: new Promise(r => resolve=r), resolve: () => resolve()}; };

test('admin status outage stays distinct from unconfigured and can be retried', async () => {
  setup();
  const auth = useAuth();
  globalThis.fetch = async () => { throw new Error('Network unavailable'); };
  await auth.checkStatus();
  assert.equal(auth.configured, null);
  assert.match(auth.statusError, /Network unavailable/);
  assert.equal(auth.statusLoading, false);
  globalThis.fetch = async () => new Response('{"configured":true}');
  await auth.checkStatus();
  assert.equal(auth.configured, true);
  assert.equal(auth.statusError, '');
});

test('an explicit unconfigured response is preserved as a separate state', async () => {
  setup();
  globalThis.fetch = async () => new Response('{"configured":false}');
  const auth = useAuth();
  await auth.checkStatus();
  assert.equal(auth.configured, false);
  assert.equal(auth.statusError, '');
});

// Execute the component's actual script with lifecycle/router dependencies stubbed.
async function loginScript(auth) {
  const source = await readFile(new URL('../src/pages/AdminLogin.vue', import.meta.url), 'utf8');
  const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^import .*;\n/gm, '');
  const js = ts.transpileModule(script, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText;
  return new Function('ref', 'onMounted', 'useAuth', 'useRouter', 'useRoute', 'ApiError', `${js};return {submit, username, password, loading};`)(ref, () => {}, () => auth, () => ({replace: async () => {}}), () => ({query: {}}), class ApiError extends Error {});
}

test('admin login ignores repeated submission while the first request is pending', async () => {
  const pending = deferred(); let requests = 0;
  const form = await loginScript({configured: true, login: async () => {requests++; await pending.promise;}});
  form.username.value = 'operator'; form.password.value = 'password';
  const first = form.submit();
  const second = form.submit();
  assert.equal(requests, 1);
  pending.resolve(); await Promise.all([first, second]);
  assert.equal(form.loading.value, false);
});

test('admin login does not submit whitespace usernames through keyboard submission', async () => {
  let requests = 0;
  const form = await loginScript({configured: true, login: async () => {requests++;}});
  form.username.value = '   '; form.password.value = 'password';
  await form.submit();
  assert.equal(requests, 0);
});
