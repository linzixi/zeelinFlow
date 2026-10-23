import assert from "node:assert/strict";
import test from "node:test";
import { startPolling } from "./polling";

test("slow requests never overlap and disposal prevents another poll", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let calls = 0;
  let finish = () => {};
  const stop = startPolling(() => {
    calls += 1;
    return new Promise<void>(resolve => { finish = resolve; });
  }, 10, { visible: () => true, subscribe: () => () => {} });
  t.mock.timers.tick(100);
  assert.equal(calls, 1);
  finish();
  await Promise.resolve();
  t.mock.timers.tick(9);
  assert.equal(calls, 1);
  t.mock.timers.tick(1);
  assert.equal(calls, 2);
  stop();
  finish();
  await Promise.resolve();
  t.mock.timers.tick(100);
  assert.equal(calls, 2);
});

test("hidden tabs stop requests and resume once when visible", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let visible = false;
  let changed = () => {};
  let calls = 0;
  let removed = false;
  const stop = startPolling(async () => { calls += 1; }, 10, {
    visible: () => visible,
    subscribe: listener => { changed = listener; return () => { removed = true; }; },
  });
  t.mock.timers.tick(100);
  assert.equal(calls, 0);
  visible = true;
  changed();
  changed();
  assert.equal(calls, 1);
  await Promise.resolve();
  visible = false;
  changed();
  t.mock.timers.tick(100);
  assert.equal(calls, 1);
  visible = true;
  changed();
  assert.equal(calls, 2);
  stop();
  assert.equal(removed, true);
});
