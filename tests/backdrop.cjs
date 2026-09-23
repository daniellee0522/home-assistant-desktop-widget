// No browser dependency: run the production backdrop loop with a failed decoder.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/app.js', 'utf8');
const refresh = source.slice(source.indexOf('function refreshBackdrop()'),
  source.indexOf('function invalidateBackdrop()'));
const system = source.slice(source.indexOf('function systemGlass()'),
  source.indexOf('function applySystemGlass()'));

(async () => {
  let fail = true;
  let paints = 0;
  let closed = 0;
  const hashes = [];
  const context = vm.createContext({
    backdropPending: false, backdropGeneration: 0, backdropHash: null,
    backdropStill: 0, backdropSkipMs: 0, backdropAt: null,
    CONFIG: {}, WINDOW_KIND: 'main', performance,
    viewportBox: () => ({ width: 100, height: 100 }), cardGeometry: () => null,
    noteFrameCost() {}, applySystemGlass() {}, refreshBackdropSoon() {},
    paintBackdrop() { paints++; },
    decodeShot: async () => {
      if (fail) throw Error('decode failed');
      return { close() { closed++; } };
    },
    window: { devicePixelRatio: 1, pywebview: { api: {
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
