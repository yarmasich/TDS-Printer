import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../src/api/client.ts';
import { blockerSummary, deleteWithForce, forceDeleteMessage } from '../src/components/admin/ProjectsTree.vue';

// Verbatim details from server/app/importer.py:delete_labels.
const BLOCKED = 'Labels belong to an active or uncertain print job (1 printing, 2 uncertain). Delete again with force=true to clear the items that are no longer in flight.';
const LIVE = 'A print job is running right now (1 printing); a forced delete never cancels a live print. Wait for it to finish.';

/** Drives the flow with scripted DELETE outcomes and a fixed dialog answer. */
function run(url, outcomes, answer = true, label = 'GPU-MS') {
  const log = {deletes:[], prompts:[], failures:[], reloads:0};
  return deleteWithForce(url, label, {
    remove: async (target) => { log.deletes.push(target); const outcome = outcomes[log.deletes.length - 1]; if (outcome) throw outcome; },
    confirmForce: async (message) => { log.prompts.push(message); return answer; },
    fail: (message, forced) => log.failures.push({message, forced}),
    reload: async () => { log.reloads++; },
  }).then(() => log);
}

test('a blocked discipline delete offers the forced retry and the retry carries force=true', async () => {
  const log = await run('/api/disciplines/70', [new ApiError(409, BLOCKED)]);
  assert.deepEqual(log.deletes, ['/api/disciplines/70', '/api/disciplines/70?force=true']);
  assert.equal(log.prompts.length, 1);
  assert.deepEqual(log.failures, []);
  assert.equal(log.reloads, 1);
});

test('the forced-delete dialog names the blockers and the unknown print outcome', async () => {
  const [prompt] = (await run('/api/disciplines/70', [new ApiError(409, BLOCKED)])).prompts;
  assert.match(prompt, /1 printing, 2 uncertain/);
  assert.match(prompt, /nobody knows whether the label physically came out of the printer/);
  assert.match(prompt, /check the printer and the labels on the floor/);
  assert.ok(!prompt.includes('force=true'), 'the curl hint is replaced by the dialog button');
  // A detail without a count still reads as a sentence.
  assert.equal(blockerSummary('Labels belong to an active or uncertain print job.'), '');
  assert.ok(!forceDeleteMessage('GPU-MS', 'nothing parenthesised').includes('—  ,'));
});

test('declining the forced delete sends nothing further and reports no error', async () => {
  const log = await run('/api/disciplines/70', [new ApiError(409, BLOCKED)], false);
  assert.deepEqual(log.deletes, ['/api/disciplines/70']);
  assert.deepEqual(log.failures, []);
  assert.equal(log.reloads, 0);
});

test('a live print after forcing is reported plainly and force is never offered twice', async () => {
  const log = await run('/api/disciplines/70', [new ApiError(409, BLOCKED), new ApiError(409, LIVE)]);
  assert.equal(log.prompts.length, 1);
  assert.deepEqual(log.deletes, ['/api/disciplines/70', '/api/disciplines/70?force=true']);
  assert.deepEqual(log.failures, [{message: LIVE, forced: true}]);
  assert.equal(log.reloads, 0);
});

test('force is offered only for a discipline 409, never for other deletes or other failures', async () => {
  for (const [url, error] of [
    ['/api/halls/4', new ApiError(409, 'Labels belong to an active or uncertain print job (1 printing).')],
    ['/api/projects/2', new ApiError(409, 'Labels belong to an active or uncertain print job (1 printing).')],
    ['/api/disciplines/70', new ApiError(500, 'Request failed (500).')],
    ['/api/disciplines/70', new TypeError('Failed to fetch')],
  ]) {
    const log = await run(url, [error]);
    assert.deepEqual(log.prompts, [], url);
    assert.deepEqual(log.deletes, [url], url);
    assert.deepEqual(log.failures, [{message: error.message, forced: false}], url);
    assert.equal(log.reloads, 0, url);
  }
});

test('an unblocked delete refreshes the tree without any extra prompt', async () => {
  const log = await run('/api/disciplines/70', []);
  assert.deepEqual(log.deletes, ['/api/disciplines/70']);
  assert.deepEqual(log.prompts, []);
  assert.equal(log.reloads, 1);
});
