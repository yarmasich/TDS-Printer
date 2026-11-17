import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { startVisibleInterval } from '../src/data/visibleInterval.ts';

function page(state = 'visible') {
  const doc = new EventTarget();
  doc.visibilityState = state;
  doc.show = () => { doc.visibilityState = 'visible'; doc.dispatchEvent(new Event('visibilitychange')); };
  doc.hide = () => { doc.visibilityState = 'hidden'; doc.dispatchEvent(new Event('visibilitychange')); };
  return doc;
}

test('refreshes on the interval while the page is visible', (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const refresh = mock.fn();
  startVisibleInterval(refresh, 20000, page());
  t.mock.timers.tick(60000);
  assert.equal(refresh.mock.callCount(), 3);
});

test('a hidden page (screen off, other tab) does not poll the printer', (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const refresh = mock.fn();
  const doc = page('hidden');
  startVisibleInterval(refresh, 20000, doc);
  t.mock.timers.tick(60000);
  assert.equal(refresh.mock.callCount(), 0);
});

test('returning to the page refreshes at once instead of showing a stale state', (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const refresh = mock.fn();
  const doc = page('hidden');
  startVisibleInterval(refresh, 20000, doc);
  doc.show();
  assert.equal(refresh.mock.callCount(), 1);
  doc.hide();
  assert.equal(refresh.mock.callCount(), 1);
});

test('stopping removes both the timer and the visibility listener', (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const refresh = mock.fn();
  const doc = page();
  const stop = startVisibleInterval(refresh, 20000, doc);
  stop();
  t.mock.timers.tick(60000);
  doc.show();
  assert.equal(refresh.mock.callCount(), 0);
});
