// No browser dependency: run the production backdrop loop with a failed decoder.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const refresh = source.slice(source.indexOf('function applyShot('),
  source.indexOf('function invalidateBackdrop()'));
const system = source.slice(source.indexOf('function systemGlass()'),
  source.indexOf('function applySystemGlass()'));

(async () => {
  let fail = true;
  const streamCalls = [];
  let paints = 0;
  let closed = 0;
  let restarted = 0;
  const hashes = [];
  const context = vm.createContext({
    backdropPending: false, backdropGeneration: 0, backdropHash: null,
    backdropStill: 0, backdropSkipMs: 0, backdropAt: null, backdropPaced: false,
    flyoutAnimating: false, backdropTicksOnVsync: () => false,
    startBackdropTicker() { restarted++; }, IS_POPOVER_WINDOW: false,
    CONFIG: {}, WINDOW_KIND: 'main', performance,
    viewportBox: () => ({ width: 100, height: 100 }), cardGeometry: () => null,
    noteFrameCost() {}, applySystemGlass() {}, refreshBackdropSoon() {},
    paintBackdrop() { paints++; },
    decodeShot: async () => {
      if (fail) throw Error('decode failed');
      return { close() { closed++; } };
    },
    document: { hidden: false },
    setInterval: () => 7, clearInterval() {},
    window: { devicePixelRatio: 1, pywebview: { api: {
      backdrop_stream: async (...args) => { streamCalls.push(args); return true; },
      get_desktop_backdrop: async (kind, hash) => {
        hashes.push(hash);
        return { w: 100, h: 100, hash: 123, blur_url: 'frame', system_glass: false };
      },
    } } },
  });
  vm.runInContext(system + refresh, context);
  await context.refreshBackdrop();
  assert.equal(context.backdropPending, false);
  assert.equal(context.backdropHash, null);
  fail = false;
  await context.refreshBackdrop();
  assert.deepEqual(hashes, [null, null]);
  assert.equal(context.backdropHash, 123);
  assert.equal(paints, 1);
  assert.equal(closed, 1);

  context.decodeShot = async () => {
    context.backdropGeneration++;
    return { close() { closed++; } };
  };
  await context.refreshBackdrop();
  assert.equal(paints, 1, 'invalidated frame must not be painted');
  assert.equal(context.backdropHash, null);
  assert.equal(closed, 2);
  assert.equal(context.backdropPending, false);

  // Pushed frames: accepted only for the live stream, painted, and the
  // stream's end hands control back to the ticker.
  paints = 0;
  context.decodeShot = async () => ({ close() { closed++; } });
  context.backdropPaced = true;
  assert.equal(context.canStream(), true);
  context.enterStream();
  const token = streamCalls[0][1];
  assert.equal(streamCalls[0][0], 'main');
  const frame = { token, w: 100, h: 100, hash: 55, blur_url: 'f', paced: true,
                  system_glass: false };
  context.window.__backdropPush({ ...frame, token: 'stale' });
  await new Promise(r => setImmediate(r));
  assert.equal(paints, 0, 'a frame from another stream must be ignored');
  context.window.__backdropPush(frame);
  await new Promise(r => setImmediate(r));
  assert.equal(paints, 1);
  assert.equal(context.backdropHash, 55);
  context.window.__backdropPush({ token, stream_end: true, skip: true, retry_ms: 400 });
  assert.equal(context.backdropSkipMs, 400);
  assert.equal(restarted, 1, 'the ticker resumes when the stream ends');
  context.window.__backdropPush(frame);
  await new Promise(r => setImmediate(r));
  assert.equal(paints, 1, 'nothing is painted after the stream ended');
  context.backdropSkipMs = 0;
  context.enterStream();

  context.CONFIG = { glass_mode: 'system', system_glass_ok: true };
  assert.equal(context.systemGlass(), false, 'capability alone is not activation');
  context.CONFIG.system_glass_active = { main: true };
  assert.equal(context.systemGlass(), true);

  let abortTick;
  let cleared = false;
  const bridge = vm.createContext({
    AbortController,
    setTimeout(fn, ms) { assert.equal(ms, 12000); abortTick = fn; return 1; },
    clearTimeout() { cleared = true; },
    window: { addEventListener() {} }, document: { readyState: 'loading' },
    fetch: (url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(Error('aborted')));
    }),
  });
  vm.runInContext(fs.readFileSync('web/bridge.js', 'utf8'), bridge);
  const pending = bridge.window.pywebview.api.get_desktop_backdrop('main');
  abortTick();
  await assert.rejects(pending, /aborted/);
  assert.equal(cleared, true);
  console.log('Backdrop recovery, invalidation, native activation and HTTP timeout checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
