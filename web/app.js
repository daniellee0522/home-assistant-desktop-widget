"use strict";

/* ============================================================
 * Icons (hand-drawn, single <path> per glyph, 24x24 viewBox)
 * ============================================================ */
const ICON_PATHS = {
  light: '<path d="M12 2a7 7 0 00-4 12.74V17a1 1 0 001 1h6a1 1 0 001-1v-2.26A7 7 0 0012 2zm-2 18h4v1a1 1 0 01-1 1h-2a1 1 0 01-1-1v-1z"/>',
  switch: '<path d="M7 2h2v5H7zM15 2h2v5h-2zM6 7h12a1 1 0 011 1v4a7 7 0 01-6 6.93V22h-2v-3.07A7 7 0 015 12V8a1 1 0 011-1z"/>',
  climate: '<path d="M13 14.76V4a1 1 0 00-2 0v10.76a3.5 3.5 0 102 0zM12 6a1 1 0 011 1v7.17a1.5 1.5 0 11-2 0V7a1 1 0 011-1z"/>',
  fan: '<path d="M12 12.9a1.9 1.9 0 100-3.8 1.9 1.9 0 000 3.8zM12.8 10c1-3 4.8-4.8 6.4-2.4 1.6 2.4-1.1 4.8-4 4.6zM11.2 10c-1-3-4.8-4.8-6.4-2.4-1.6 2.4 1.1 4.8 4 4.6zM11.2 12c-1 3-4.8 4.8-6.4 2.4-1.6-2.4 1.1-4.8 4-4.6zM12.8 12c1 3 4.8 4.8 6.4 2.4 1.6-2.4-1.1-4.8-4-4.6z"/>',
  cover: '<path d="M4 3h16v2H4zM4 6.5h16v2H4zM4 10h16v2H4zM6 13h4v8H6zM14 13h4v8h-4z"/>',
  media: '<path d="M15 3v10.55A4 4 0 1013 17V8h5V3z"/>',
  lock: '<path d="M12 2a4 4 0 00-4 4v3H7a1 1 0 00-1 1v10a1 1 0 001 1h10a1 1 0 001-1V10a1 1 0 00-1-1h-1V6a4 4 0 00-4-4zm-2 7V6a2 2 0 114 0v3zm2 4a1.5 1.5 0 011.5 1.5c0 .6-.34 1.1-.83 1.36l.33 2.14h-2l.33-2.14A1.5 1.5 0 0112 13z"/>',
  vacuum: '<path d="M12 4a8 8 0 100 16 8 8 0 000-16zm0 2.4a5.6 5.6 0 110 11.2 5.6 5.6 0 010-11.2zm0 2.8a2.8 2.8 0 100 5.6 2.8 2.8 0 000-5.6z"/>',
  scene: '<path d="M5 19l9-9 2 2-9 9-2-2zm10-15.6l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM4 3.5l.7 1.6L6.3 5.8l-1.6.7L4 8.1l-.7-1.6L1.7 5.8l1.6-.7z"/>',
  script: '<path d="M6 3h2v2H7v14h1v2H6a1 1 0 01-1-1V4a1 1 0 011-1zm12 0a1 1 0 011 1v16a1 1 0 01-1 1h-2v-2h1V5h-1V3h2zM10 8l6 4-6 4z"/>',
  automation: '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
  sensor: '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 3a1.6 1.6 0 110 3.2A1.6 1.6 0 0112 5zm-2 6h4v8h-4z"/>',
  monitor: '<path d="M4 4h16a1 1 0 011 1v11a1 1 0 01-1 1h-5l1 3H9l1-3H5a1 1 0 01-1-1V5a1 1 0 011-1zm1 2v9h14V6H5z"/>',
  door: '<path d="M6 2h12v20H6V2zm2 2v16h8V4H8zm5.5 7a1.25 1.25 0 110 2.5 1.25 1.25 0 010-2.5z"/>',
  curtain: '<path d="M4 3h16v2H4V3zm2 2.5c1.8 3-1.8 4-.4 7s-1.4 4 .4 7H5v-14h1zm12 0c-1.8 3 1.8 4 .4 7s1.4 4-.4 7h1v-14h-1zM10.5 5.5h3V19h-3V5.5z"/>',
  power: '<path d="M11 2h2v9h-2zM6.3 5.3l1.4 1.4A6 6 0 1016.3 6.7l1.4-1.4A8 8 0 1112 4a7.95 7.95 0 00-5.7 1.3z"/>',
  gear: '<path d="M12 8.5a3.5 3.5 0 100 7 3.5 3.5 0 000-7zM21 12a9 9 0 00-.19-1.86l2.03-1.58a.75.75 0 00.17-.96l-1.92-3.32a.75.75 0 00-.91-.32l-2.39.96c-.98-.75-1.44-.99-2.36-1.32L15.07.6A.75.75 0 0014.33 0h-3.84a.75.75 0 00-.74.64l-.36 2.54c-.93.33-1.38.57-2.36 1.32l-2.39-.96a.75.75 0 00-.91.32L1.81 7.18a.75.75 0 00.17.96l2.03 1.58A9 9 0 003 12c0 .64.07 1.26.19 1.86l-2.03 1.58a.75.75 0 00-.17.96l1.92 3.32c.2.34.6.47.91.32l2.39-.96c.98.75 1.44.99 2.36 1.32l.36 2.54c.06.37.37.64.74.64h3.84c.37 0 .68-.27.74-.64l.36-2.54c.93-.33 1.38-.57 2.36-1.32l2.39.96c.34.14.75 0 .91-.32l1.92-3.32a.75.75 0 00-.17-.96l-2.03-1.58c.12-.6.19-1.22.19-1.86z"/>',
};
const ICON_PLAY = '<path d="M8 5v14l11-7z"/>';
const ICON_PAUSE = '<path d="M7 5h4v14H7zM13 5h4v14h-4z"/>';
const ICON_PREV = '<path d="M6 6h2v12H6zM20 6L10 12l10 6z"/>';
const ICON_NEXT = '<path d="M16 6h2v12h-2zM4 6l10 6-10 6z"/>';

function svgIcon(name) {
  return '<svg viewBox="0 0 24 24">' + (ICON_PATHS[name] || ICON_PATHS.sensor) + '</svg>';
}

/* ============================================================
 * Domain metadata
 * ============================================================ */
const DOMAIN_META = {
  light: { icon: 'light', expand: true },
  switch: { icon: 'switch', expand: true },
  input_boolean: { icon: 'switch', expand: true },
  climate: { icon: 'climate', expand: true },
  fan: { icon: 'fan', expand: true },
  cover: { icon: 'cover', expand: true },
  media_player: { icon: 'media', expand: true },
  lock: { icon: 'lock' },
  vacuum: { icon: 'vacuum', expand: true },
  scene: { icon: 'scene', momentary: true },
  script: { icon: 'script', momentary: true },
  automation: { icon: 'automation', momentary: true },
  sensor: { icon: 'sensor', readonly: true },
  binary_sensor: { icon: 'sensor', readonly: true },
  default: { icon: 'sensor', readonly: true },
};
const DOMAIN_LABELS = {
  light: '燈光', switch: '開關/插座', input_boolean: '虛擬開關', climate: '空調',
  fan: '風扇', cover: '窗簾/百葉', media_player: '媒體播放器', lock: '門鎖',
  vacuum: '掃地機', scene: '場景', script: '腳本', automation: '自動化',
  sensor: '感測器', binary_sensor: '感測器 (開關型)',
};
const HVAC_LABELS = { off: '關閉', cool: '冷氣', heat: '暖氣', heat_cool: '自動', auto: '自動', dry: '除濕', fan_only: '送風' };
const LIGHT_PALETTE = [
  [255, 255, 255], [255, 214, 153], [255, 159, 67], [255, 94, 87],
  [255, 107, 181], [142, 111, 255], [72, 159, 255], [93, 222, 140],
];

function domainMeta(domain) { return DOMAIN_META[domain] || DOMAIN_META.default; }

/* ============================================================
 * Global state
 * ============================================================ */
let CONFIG = {
  ha_url: '', ha_token: '', theme: 'auto', columns: 4, tiles: [],
  lock_position: false, start_on_boot: false,
  zoom: 100, fixed_size: false, fixed_width: 400, fixed_height: 300,
};
let STATES = {};
let CONNECTED = false;
let entityToTileIds = {};
let currentDetailTileId = null;
let allEntities = [];

function findTile(id) { return (CONFIG.tiles || []).find((t) => t.id === id); }
function friendlyName(state) { return state && state.attributes && state.attributes.friendly_name; }

/* ============================================================
 * Realtime push handlers (called from Python)
 * ============================================================ */
window.__haPush = function (entityId, newState) {
  STATES[entityId] = newState;
  updateTileByEntity(entityId);
};
window.__haPushBatch = function (items) {
  for (const [entityId, newState] of items) STATES[entityId] = newState;
  for (const [entityId] of items) updateTileByEntity(entityId);
};
// The websocket can drop and reconnect for all sorts of transient reasons
// (network blip, HA restarting a component, idle timeout) and usually
// recovers within its own backoff (a few seconds). Flashing the indicator
// red for every one of those blips is just noise - only report
// "disconnected" if it's still down after a few seconds; report
// "connected" immediately, since that's never something to hide.
let connDisconnectTimer = null;
window.__haStatus = function (connected) {
  if (connDisconnectTimer) { clearTimeout(connDisconnectTimer); connDisconnectTimer = null; }
  if (connected) {
    CONNECTED = true;
    updateConnDot();
  } else {
    connDisconnectTimer = setTimeout(() => {
      connDisconnectTimer = null;
      CONNECTED = false;
      updateConnDot();
    }, 8000);
  }
};

/* ============================================================
 * Boot
 * ============================================================ */
async function boot() {
  try {
    const data = await window.pywebview.api.bootstrap();
    CONFIG = data.config;
    CONNECTED = !!data.connected;
  } catch (e) {
    /* keep defaults, still render an empty widget */
  }
  applyTheme();
  applyZoom();
  applyFixedSizeConstraint();
  renderGrid();
  updateConnDot();
  try { await window.pywebview.api.ui_ready(); } catch (e) { /* ignore */ }

  // Fetched separately from - and after - the first render: this is a
  // real network round-trip, and bootstrap() above deliberately avoids
  // blocking the initial paint on it (a slow or unreachable HA would
  // otherwise stall the whole widget for as long as that request takes to
  // time out). Tiles just show "無法連線" until this resolves or the
  // websocket's own push arrives, whichever comes first.
  window.pywebview.api.fetch_initial_states().then((states) => {
    if (states && Object.keys(states).length) {
      for (const [entityId, state] of Object.entries(states)) STATES[entityId] = state;
      for (const entityId of Object.keys(states)) updateTileByEntity(entityId);
    }
  }).catch(() => { /* ignore */ });

  if (!CONFIG.ha_token && (!CONFIG.tiles || !CONFIG.tiles.length)) {
    setTimeout(openSettings, 150);
  }
}

function applyTheme() {
  document.documentElement.setAttribute('data-theme', CONFIG.theme || 'auto');
}

/* ============================================================
 * View switching + auto window sizing
 * ============================================================ */
function showView(name) {
  for (const id of ['view-grid', 'view-settings', 'view-picker']) {
    document.getElementById(id).hidden = id !== name;
  }
  // The widget normally can't take keyboard focus (so tiles never yank it
  // above other windows) - but Settings/the entity picker have real text
  // inputs, so they need focus to actually be typeable.
  const needsFocus = (name === 'view-settings' || name === 'view-picker');
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_activatable(needsFocus).catch(() => {});
  }
}

// window.innerWidth/innerHeight turned out to be unreliable to read back
// right after a programmatic resize on this host (observed to freeze at a
// stale value indefinitely after the first resize call, on this project's
// own dev machine), so the native window is never sized by asking
// pywebview's own resize() to convert CSS pixels to physical ones - that
// conversion uses Win32's GetDpiForWindow, which on that same machine
// disagreed with WebView2's real devicePixelRatio (a Windows text-scaling
// setting layered on top of normal monitor scaling was the reproducible
// cause), leaving real content clipped at the window edge. Instead, this
// converts to physical pixels itself using window.devicePixelRatio - a
// static per-monitor value that doesn't need "measuring after a resize"
// the way innerWidth/innerHeight do - and sends the OS an exact physical
// pixel count to set via SetWindowPos, bypassing that translation step
// entirely (see resize_window in main.py).
let resizeRaf = null;
let resizeSeq = 0;

function applyZoom() {
  const z = Math.max(50, Math.min(200, Number(CONFIG.zoom) || 100)) / 100;
  document.documentElement.style.zoom = String(z);
}

function applyFixedSizeConstraint() {
  const viewGrid = document.getElementById('view-grid');
  if (CONFIG.fixed_size) {
    viewGrid.style.width = Math.max(120, Number(CONFIG.fixed_width) || 400) + 'px';
    viewGrid.style.height = Math.max(90, Number(CONFIG.fixed_height) || 300) + 'px';
    viewGrid.style.overflow = 'auto';
  } else {
    viewGrid.style.width = '';
    viewGrid.style.height = '';
    viewGrid.style.overflow = '';
  }
}

// The window can show more than one rounded card at once (the grid, plus
// a floating detail popover that's a sibling of it, not nested inside) -
// a single rounded-rect clip for the whole window would either round the
// *bounding box* of both (wrong shape) or force them to share one
// footprint (which is what used to visibly distort the grid whenever a
// popover opened). Each visible card gets its own rounded-rect region
// instead, unioned together in Python via CombineRgn.
function getActiveCardRects(stageRect, zoomFactor) {
  const rects = [];
  for (const id of ['view-grid', 'view-settings', 'view-picker']) {
    const el = document.getElementById(id);
    if (el.hidden) continue;
    const r = el.getBoundingClientRect();
    rects.push({ x: r.left - stageRect.left, y: r.top - stageRect.top, w: r.width, h: r.height });
  }
  const popover = document.getElementById('detail-popover');
  if (!popover.hidden) {
    // Deliberately *not* popover.getBoundingClientRect() for the popover's
    // own box size: it no longer scale-transforms (only opacity/translateY,
    // which don't change layout size), but style.left/top/POPOVER_W/H are
    // all expressed in *un-zoomed* local CSS px, whereas every other rect
    // above comes from getBoundingClientRect() - already in *post-zoom*
    // (visual) px, since `zoom` is applied on <html> itself. Multiplying by
    // zoomFactor here converts to the same post-zoom space as the rest, so
    // the single dpr-only conversion below applies uniformly. Skipping this
    // left the popover's clip region ~1/zoomFactor times too big (at 75%
    // zoom, ~33% oversized) - bigger than the window itself, so it just got
    // truncated to "whole window, rounded corners", exposing a big
    // unpainted black rectangle everywhere the actual (correctly zoomed,
    // much smaller) popover card didn't reach.
    rects.push({
      x: (parseFloat(popover.style.left) || 0) * zoomFactor,
      y: (parseFloat(popover.style.top) || 0) * zoomFactor,
      w: POPOVER_W * zoomFactor,
      h: POPOVER_H * zoomFactor,
    });
  }
  return rects;
}

function syncWindowSize() {
  if (resizeRaf) cancelAnimationFrame(resizeRaf);
  resizeRaf = requestAnimationFrame(() => {
    if (!(window.pywebview && window.pywebview.api)) return;
    const dpr = window.devicePixelRatio || 1;
    const stage = document.getElementById('stage');
    let cssW, cssH;
    if (CONFIG.fixed_size) {
      cssW = Math.max(120, Number(CONFIG.fixed_width) || 400);
      cssH = Math.max(90, Number(CONFIG.fixed_height) || 300);
    } else {
      const rect = stage.getBoundingClientRect();
      cssW = rect.width + 4;
      cssH = rect.height + 4;
    }
    resizeSeq += 1;

    // Convert each active card's box to physical pixels for the window's
    // clip region, matching the actual rendered corner radius (--radius-
    // panel), zoom included - CSS zoom scales border-radius rendering the
    // same way it scales everything else getBoundingClientRect() sees.
    const stageRect = stage.getBoundingClientRect();
    const zoomFactor = Math.max(50, Math.min(200, Number(CONFIG.zoom) || 100)) / 100;
    const cssRadius = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--radius-panel')) || 28;
    const radius = Math.round(cssRadius * zoomFactor * dpr);
    const rects = getActiveCardRects(stageRect, zoomFactor).map((r) => [
      Math.round(r.x * dpr), Math.round(r.y * dpr), Math.round(r.w * dpr), Math.round(r.h * dpr), radius,
    ]);

    window.pywebview.api.resize_window(Math.ceil(cssW * dpr), Math.ceil(cssH * dpr), resizeSeq, rects);
  });
}
new ResizeObserver(syncWindowSize).observe(document.getElementById('stage'));

/* ============================================================
 * Grid rendering
 * ============================================================ */
function isOnState(domain, state) {
  if (!state) return false;
  switch (domain) {
    case 'climate': return state.state && state.state !== 'off';
    case 'cover': return state.state === 'open';
    case 'lock': return state.state === 'unlocked';
    case 'media_player': return state.state === 'playing';
    case 'vacuum': return state.state === 'cleaning' || state.state === 'returning';
    default: return state.state === 'on';
  }
}

function iconColorFor(domain, state, on) {
  const attrs = (state && state.attributes) || {};
  switch (domain) {
    case 'light':
      if (!on) return 'var(--text-off-1)';
      if (Array.isArray(attrs.rgb_color)) return 'rgb(' + attrs.rgb_color.join(',') + ')';
      return 'var(--accent-yellow)';
    case 'switch': case 'input_boolean': return on ? 'var(--accent-blue)' : 'var(--text-off-1)';
    case 'climate': return on ? 'var(--accent-cyan)' : 'var(--text-off-1)';
    case 'fan': return on ? 'var(--accent-blue)' : 'var(--text-off-1)';
    case 'cover': return on ? 'var(--accent-blue)' : 'var(--text-off-1)';
    case 'media_player': return on ? 'var(--accent-green)' : 'var(--text-off-1)';
    case 'lock': return state && state.state === 'locked' ? 'var(--text-off-1)' : 'var(--accent-red)';
    case 'vacuum': return on ? 'var(--accent-blue)' : 'var(--text-off-1)';
    case 'scene': case 'script': case 'automation': return 'var(--accent-blue)';
    case 'binary_sensor': return state && state.state === 'on' ? 'var(--accent-green)' : 'var(--text-off-1)';
    default: return 'var(--text-off-1)';
  }
}

function valueTextFor(domain, state) {
  if (!state) return '';
  const attrs = state.attributes || {};
  if (domain === 'climate') return state.state !== 'off' && attrs.temperature != null ? attrs.temperature + '°' : '';
  if (domain === 'sensor') return state.state + (attrs.unit_of_measurement || '');
  return '';
}

function defaultLabel(domain, state) {
  const s = state ? state.state : '';
  const map = {
    light: '燈光', switch: '插座', input_boolean: '虛擬開關', climate: s, fan: '風扇',
    cover: s === 'open' ? '開啟' : s === 'closed' ? '關閉' : s,
    media_player: s, lock: s === 'locked' ? '已上鎖' : '未上鎖',
    vacuum: s, scene: '場景', script: '腳本', automation: '自動化',
    binary_sensor: s === 'on' ? '偵測到' : '正常',
  };
  return map[domain] || s || '';
}

function tileEl(tile) {
  const state = STATES[tile.entity];
  const domain = tile.domain;
  const meta = domainMeta(domain);
  const ok = !!state;
  const on = ok && !meta.momentary && isOnState(domain, state);

  const div = document.createElement('div');
  div.className = 'tile' + (on ? ' is-on' : '') + (meta.readonly ? ' is-readonly' : '');
  div.dataset.id = tile.id;

  const iconWrap = document.createElement('div');
  iconWrap.className = 'tile-icon';
  iconWrap.innerHTML = svgIcon(tile.icon || meta.icon);
  iconWrap.style.color = ok ? iconColorFor(domain, state, on) : 'var(--text-off-1)';
  div.appendChild(iconWrap);

  const valueText = ok ? valueTextFor(domain, state) : '';
  if (valueText) {
    const v = document.createElement('div');
    v.className = 'tile-value';
    v.textContent = valueText;
    div.appendChild(v);
  }

  const room = document.createElement('div');
  room.className = 'tile-room';
  room.textContent = tile.room || friendlyName(state) || tile.entity;
  div.appendChild(room);

  const label = document.createElement('div');
  label.className = 'tile-label';
  label.textContent = ok ? (tile.label || defaultLabel(domain, state)) : '無法連線';
  div.appendChild(label);

  if (!ok) {
    const warn = document.createElement('div');
    warn.className = 'conn-warn';
    div.appendChild(warn);
  }

  if (domain === 'climate' && on) addClimateMiniButtons(div, tile);

  attachTileInteraction(div, tile);
  return div;
}

function addClimateMiniButtons(div, tile) {
  const wrap = document.createElement('div');
  wrap.className = 'mini-btns';
  const minus = document.createElement('button');
  minus.className = 'mini-btn'; minus.textContent = '−';
  const plus = document.createElement('button');
  plus.className = 'mini-btn'; plus.textContent = '+';
  minus.addEventListener('click', (e) => { e.stopPropagation(); climateStep(tile, -(Number(tile.temp_step) || 1)); });
  plus.addEventListener('click', (e) => { e.stopPropagation(); climateStep(tile, Number(tile.temp_step) || 1); });
  wrap.appendChild(minus); wrap.appendChild(plus);
  div.appendChild(wrap);
}

function attachTileInteraction(el, tile) {
  const meta = domainMeta(tile.domain);
  if (meta.readonly) return;

  if (!meta.expand) {
    // 'click' only ever fires for the primary (left) button, so right-click
    // naturally can't trigger this - just stop the native context menu.
    el.addEventListener('click', (e) => {
      if (e.target.closest('.mini-btn')) return;
      quickAction(tile);
    });
    el.addEventListener('contextmenu', (e) => e.preventDefault());
    return;
  }

  // Pointer events fire for *any* mouse button, unlike 'click', so the
  // tap/long-press machinery below must ignore right-click itself - it
  // gets its own, deliberately different behavior via 'contextmenu'.
  let timer = null, startX = 0, startY = 0, fired = false, primaryDown = false;
  const cancel = () => { el.classList.remove('is-pressing'); if (timer) { clearTimeout(timer); timer = null; } };

  el.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.mini-btn')) return;
    primaryDown = true;
    startX = e.clientX; startY = e.clientY; fired = false;
    el.classList.add('is-pressing');
    timer = setTimeout(() => { fired = true; el.classList.remove('is-pressing'); openDetail(tile); }, 420);
  });
  el.addEventListener('pointermove', (e) => {
    if (!primaryDown) return;
    if (timer && (Math.abs(e.clientX - startX) > 8 || Math.abs(e.clientY - startY) > 8)) cancel();
  });
  el.addEventListener('pointerup', (e) => {
    if (!primaryDown) return;
    primaryDown = false;
    const wasFired = fired;
    cancel();
    if (e.target.closest('.mini-btn')) return;
    if (!wasFired) quickAction(tile);
  });
  el.addEventListener('pointerleave', () => { primaryDown = false; cancel(); });
  el.addEventListener('pointercancel', () => { primaryDown = false; cancel(); });

  // Right-click jumps straight to the detailed control sheet (brightness,
  // temperature, position...) instead of duplicating the left-click action.
  el.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    openDetail(tile);
  });
}

function renderGrid() {
  const grid = document.getElementById('tiles');
  const emptyHint = document.getElementById('empty-hint');
  grid.innerHTML = '';
  entityToTileIds = {};
  const tiles = CONFIG.tiles || [];
  // Using the full configured column count even when there are fewer
  // tiles than that would reserve empty grid-track width nobody's using,
  // leaving a big dead strip on the right - not very "widget"-sized.
  const cols = Math.max(1, Math.min(CONFIG.columns || 4, tiles.length || 1));
  document.documentElement.style.setProperty('--cols', cols);
  if (!tiles.length) {
    grid.hidden = true;
    emptyHint.hidden = false;
  } else {
    grid.hidden = false;
    emptyHint.hidden = true;
    for (const t of tiles) {
      (entityToTileIds[t.entity] || (entityToTileIds[t.entity] = [])).push(t.id);
      grid.appendChild(tileEl(t));
    }
  }
  syncWindowSize();
}

function updateTileByEntity(entityId) {
  const ids = entityToTileIds[entityId];
  if (!ids) return;
  for (const id of ids) {
    const tile = findTile(id);
    if (!tile) continue;
    const old = document.querySelector('.tile[data-id="' + id + '"]');
    if (old) old.replaceWith(tileEl(tile));
  }
  if (currentDetailTileId && ids.includes(currentDetailTileId)) renderDetailBody();
}

function optimisticSet(entity, patch) {
  if (!STATES[entity]) return;
  STATES[entity] = Object.assign({}, STATES[entity], patch);
  updateTileByEntity(entity);
}

function flashTile(tileId) {
  const el = document.querySelector('.tile[data-id="' + tileId + '"]');
  if (!el) return;
  el.classList.remove('flash');
  void el.offsetWidth;
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 650);
}

/* ============================================================
 * Actions / service calls
 * ============================================================ */
async function callService(domain, service, entity, extra) {
  try {
    await window.pywebview.api.call_service(domain, service, entity, extra || {});
  } catch (e) {
    showToast('操作失敗: ' + (e && e.message ? e.message : e));
  }
}

function quickAction(tile) {
  const domain = tile.domain, entity = tile.entity, state = STATES[entity];
  switch (domain) {
    case 'light': case 'switch': case 'fan': case 'input_boolean':
      if (state) optimisticSet(entity, { state: state.state === 'on' ? 'off' : 'on' });
      callService(domain, 'toggle', entity);
      break;
    case 'climate': {
      const on = state && state.state !== 'off';
      if (state) optimisticSet(entity, { state: on ? 'off' : (tile.on_mode || 'cool') });
      callService('climate', 'set_hvac_mode', entity, { hvac_mode: on ? 'off' : (tile.on_mode || 'cool') });
      break;
    }
    case 'cover': {
      const open = state && state.state === 'open';
      if (state) optimisticSet(entity, { state: open ? 'closing' : 'opening' });
      callService('cover', open ? 'close_cover' : 'open_cover', entity);
      break;
    }
    case 'media_player':
      callService('media_player', 'media_play_pause', entity);
      break;
    case 'lock': {
      const locked = state && state.state === 'locked';
      if (state) optimisticSet(entity, { state: locked ? 'unlocked' : 'locked' });
      callService('lock', locked ? 'unlock' : 'lock', entity);
      break;
    }
    case 'vacuum': {
      const cleaning = state && (state.state === 'cleaning' || state.state === 'returning');
      callService('vacuum', cleaning ? 'pause' : 'start', entity);
      break;
    }
    case 'scene': callService('scene', 'turn_on', entity); flashTile(tile.id); break;
    case 'script': callService('script', 'turn_on', entity); flashTile(tile.id); break;
    case 'automation': callService('automation', 'trigger', entity); flashTile(tile.id); break;
    default: break;
  }
}

function climateStep(tile, delta) {
  const state = STATES[tile.entity];
  const attrs = (state && state.attributes) || {};
  if (attrs.temperature == null) return;
  const next = Math.round((attrs.temperature + delta) * 10) / 10;
  optimisticSet(tile.entity, { attributes: Object.assign({}, attrs, { temperature: next }) });
  callService('climate', 'set_temperature', tile.entity, { temperature: next });
}

/* ============================================================
 * Detail popover: anchored to the tile that opened it, fixed size,
 * fades in place instead of replacing the whole widget.
 * ============================================================ */
const POPOVER_W = 260, POPOVER_H = 336;
let popoverCloseTimer = null;

function openDetail(tile) {
  const tileNode = document.querySelector('.tile[data-id="' + tile.id + '"]');
  const stage = document.getElementById('stage');
  const popover = document.getElementById('detail-popover');
  const backdrop = document.getElementById('detail-backdrop');
  if (!tileNode) return;
  if (popoverCloseTimer) { clearTimeout(popoverCloseTimer); popoverCloseTimer = null; }

  currentDetailTileId = tile.id;
  showEditMode(false);
  renderDetailBody();

  // Measure the grid's natural size *before* touching stage's own size
  // below - popover/backdrop are absolutely positioned (relative to
  // stage, a sibling of view-grid, never nested inside it), so opening
  // this never resizes or distorts view-grid's own card.
  //
  // getBoundingClientRect() always reports *post-zoom* (visual) px, since
  // `zoom` is applied on <html> itself (see applyZoom) - but any px value
  // *assigned* to .style.left/top/width/height is read back by the zoom
  // engine as a *local, pre-zoom* length and scaled again at render time.
  // Feeding a getBoundingClientRect() delta straight into .style.left
  // therefore renders at left*zoomFactor, not at left - dividing by
  // zoomFactor here converts it back to the local units .style expects.
  const zoomFactor = Math.max(50, Math.min(200, Number(CONFIG.zoom) || 100)) / 100;
  const gridRect = document.getElementById('view-grid').getBoundingClientRect();
  const stageRect = stage.getBoundingClientRect();
  const left = Math.round((tileNode.getBoundingClientRect().left - stageRect.left) / zoomFactor);
  const top = Math.round((tileNode.getBoundingClientRect().top - stageRect.top) / zoomFactor);
  popover.style.left = left + 'px';
  popover.style.top = top + 'px';

  // Absolutely positioned elements don't grow their container's own
  // auto/shrink-to-fit size, so without explicitly setting stage's size
  // to fit both the grid and the popover, the window would never resize
  // to show it and it'd just get clipped at the old edge. gridRect.width/
  // height need the same local-units conversion as left/top above so they
  // combine correctly with POPOVER_W/H (already local/un-zoomed).
  stage.style.width = Math.max(gridRect.width / zoomFactor, left + POPOVER_W) + 'px';
  stage.style.height = Math.max(gridRect.height / zoomFactor, top + POPOVER_H) + 'px';

  backdrop.hidden = false;
  popover.hidden = false;
  requestAnimationFrame(() => popover.classList.add('show'));
  syncWindowSize();
  if (window.pywebview && window.pywebview.api) window.pywebview.api.set_activatable(true).catch(() => {});
}

function closeDetail() {
  if (!currentDetailTileId) return;
  currentDetailTileId = null;
  const popover = document.getElementById('detail-popover');
  const backdrop = document.getElementById('detail-backdrop');
  const stage = document.getElementById('stage');
  popover.classList.remove('show');
  backdrop.hidden = true;
  if (window.pywebview && window.pywebview.api) window.pywebview.api.set_activatable(false).catch(() => {});
  popoverCloseTimer = setTimeout(() => {
    popoverCloseTimer = null;
    if (currentDetailTileId) return; // reopened (on a different tile) before the fade finished
    popover.hidden = true;
    stage.style.width = '';
    stage.style.height = '';
    syncWindowSize();
  }, 170);
}

function renderDetailBody() {
  const tile = findTile(currentDetailTileId);
  if (!tile) return;
  const state = STATES[tile.entity];
  document.getElementById('detail-room').textContent = tile.room || friendlyName(state) || tile.entity;
  document.getElementById('detail-sub').textContent = state ? state.state : '無法連線';
  const body = document.getElementById('detail-body');
  body.innerHTML = '';
  const builder = DETAIL_BUILDERS[tile.domain];
  if (builder) builder(body, tile, state);
}

/* ---- per-tile edit sub-panel (icon / name / category) ---- */
const ICON_CHOICES = [
  'light', 'switch', 'climate', 'fan', 'cover', 'curtain', 'media', 'monitor',
  'lock', 'door', 'vacuum', 'scene', 'script', 'automation', 'sensor',
];

function showEditMode(show) {
  document.getElementById('detail-body').hidden = show;
  document.getElementById('detail-edit-body').hidden = !show;
  if (show) populateEditForm();
}

function populateEditForm() {
  const tile = findTile(currentDetailTileId);
  if (!tile) return;
  document.getElementById('edit-room-input').value = tile.room || '';
  document.getElementById('edit-label-input').value = tile.label || '';
  renderIconPicker(tile);
}

function renderIconPicker(tile) {
  const wrap = document.getElementById('icon-picker');
  wrap.innerHTML = '';
  const current = tile.icon || domainMeta(tile.domain).icon;
  for (const name of ICON_CHOICES) {
    const b = document.createElement('button');
    b.className = 'icon-swatch' + (name === current ? ' active' : '');
    b.innerHTML = svgIcon(name);
    b.addEventListener('click', async () => {
      tile.icon = name;
      renderIconPicker(tile);
      await persistTiles();
    });
    wrap.appendChild(b);
  }
}

function toggleRow(label, on, onClick) {
  const row = document.createElement('div'); row.className = 'toggle-row';
  const l = document.createElement('span'); l.className = 'toggle-label'; l.textContent = label;
  const sw = document.createElement('button'); sw.className = 'toggle-switch' + (on ? ' is-on' : '');
  sw.addEventListener('click', onClick);
  row.appendChild(l); row.appendChild(sw);
  return row;
}

// The big HomeKit-style glance+toggle tile: shared by every expandable
// domain as the primary control, for one consistent look. fillPct is the
// portion (0-100) of the tile that fills with color when on - 100 for a
// plain switch, the live percentage for something dimmable.
function accessoryTile(iconName, on, fillPct, color, stateText, onClick) {
  const tile = document.createElement('button');
  tile.className = 'accessory-tile' + (on ? ' is-on' : '');
  tile.style.setProperty('--accessory-color', color);
  const fill = document.createElement('div'); fill.className = 'fill';
  fill.style.height = (on ? Math.max(6, fillPct) : 0) + '%';
  const icon = document.createElement('div'); icon.className = 'accessory-icon';
  icon.innerHTML = svgIcon(iconName);
  tile.appendChild(fill);
  tile.appendChild(icon);
  if (stateText) {
    const st = document.createElement('div'); st.className = 'accessory-state'; st.textContent = stateText;
    tile.appendChild(st);
  }
  tile.addEventListener('click', onClick);
  return tile;
}
function sliderBlock(label, value, min, max, unit, onCommit, step) {
  const wrap = document.createElement('div'); wrap.className = 'slider-block';
  const lab = document.createElement('div'); lab.className = 'slider-label';
  const l1 = document.createElement('span'); l1.textContent = label;
  const l2 = document.createElement('span'); l2.textContent = value + unit;
  lab.appendChild(l1); lab.appendChild(l2); wrap.appendChild(lab);
  const input = document.createElement('input'); input.type = 'range';
  input.min = String(min); input.max = String(max); input.step = String(step || 1); input.value = String(value);
  input.addEventListener('input', () => { l2.textContent = input.value + unit; });
  input.addEventListener('change', () => onCommit(input.value));
  wrap.appendChild(input);
  return wrap;
}
function stepperBtn(symbol, onClick) {
  const b = document.createElement('button'); b.className = 'stepper-btn'; b.textContent = symbol;
  b.addEventListener('click', onClick); return b;
}
function segBtnEl(text, onClick, active) {
  const b = document.createElement('button'); b.className = 'seg-btn' + (active ? ' active' : '');
  b.textContent = text; b.addEventListener('click', onClick); return b;
}
function sameRgb(a, b) { return Array.isArray(a) && Array.isArray(b) && a[0] === b[0] && a[1] === b[1] && a[2] === b[2]; }
function colorSwatches(currentRgb, onPick) {
  const wrap = document.createElement('div'); wrap.className = 'color-swatches';
  for (const rgb of LIGHT_PALETTE) {
    const s = document.createElement('button');
    s.className = 'swatch' + (sameRgb(rgb, currentRgb) ? ' active' : '');
    s.style.background = 'rgb(' + rgb.join(',') + ')';
    s.addEventListener('click', () => onPick(rgb));
    wrap.appendChild(s);
  }
  return wrap;
}
function mediaBtn(iconPath, onClick, big) {
  const b = document.createElement('button'); b.className = 'icon-btn' + (big ? ' play-btn' : '');
  b.innerHTML = '<svg viewBox="0 0 24 24">' + iconPath + '</svg>';
  b.addEventListener('click', onClick);
  return b;
}

const DETAIL_BUILDERS = {
  light(body, tile, state) {
    const attrs = (state && state.attributes) || {};
    const on = !!state && state.state === 'on';
    const pct = ('brightness' in attrs && attrs.brightness != null) ? Math.round((attrs.brightness / 255) * 100) : 100;
    const color = Array.isArray(attrs.rgb_color) ? 'rgb(' + attrs.rgb_color.join(',') + ')' : 'var(--accent-yellow)';
    const icon = tile.icon || domainMeta('light').icon;
    body.appendChild(accessoryTile(icon, on, pct, color, on ? (pct + '%') : '關閉', () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService('light', 'toggle', tile.entity);
    }));
    if (!on) return;
    if ('brightness' in attrs && attrs.brightness != null) {
      body.appendChild(sliderBlock('亮度', pct, 1, 100, '%', (v) => callService('light', 'turn_on', tile.entity, { brightness_pct: Number(v) }), 1));
    }
    if (attrs.color_temp_kelvin || attrs.min_color_temp_kelvin) {
      const min = attrs.min_color_temp_kelvin || 2000, max = attrs.max_color_temp_kelvin || 6500;
      const val = attrs.color_temp_kelvin || Math.round((min + max) / 2);
      body.appendChild(sliderBlock('色溫', val, min, max, 'K', (v) => callService('light', 'turn_on', tile.entity, { color_temp_kelvin: Number(v) }), 100));
    }
    if (Array.isArray(attrs.rgb_color)) {
      body.appendChild(colorSwatches(attrs.rgb_color, (rgb) => callService('light', 'turn_on', tile.entity, { rgb_color: rgb })));
    }
  },
  fan(body, tile, state) {
    const attrs = (state && state.attributes) || {};
    const on = !!state && state.state === 'on';
    const pct = attrs.percentage != null ? attrs.percentage : 100;
    const icon = tile.icon || domainMeta('fan').icon;
    body.appendChild(accessoryTile(icon, on, pct, 'var(--accent-blue)', on ? (pct + '%') : '關閉', () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService('fan', 'toggle', tile.entity);
    }));
    if (on && attrs.percentage != null) {
      body.appendChild(sliderBlock('風速', attrs.percentage, 0, 100, '%', (v) => callService('fan', 'set_percentage', tile.entity, { percentage: Number(v) }), 10));
    }
  },
  switch(body, tile, state) {
    const on = !!state && state.state === 'on';
    const icon = tile.icon || domainMeta('switch').icon;
    body.appendChild(accessoryTile(icon, on, 100, 'var(--accent-blue)', on ? '開啟' : '關閉', () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService('switch', 'toggle', tile.entity);
    }));
  },
  input_boolean(body, tile, state) {
    const on = !!state && state.state === 'on';
    const icon = tile.icon || domainMeta('input_boolean').icon;
    body.appendChild(accessoryTile(icon, on, 100, 'var(--accent-blue)', on ? '開啟' : '關閉', () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService('input_boolean', 'toggle', tile.entity);
    }));
  },
  climate(body, tile, state) {
    const attrs = (state && state.attributes) || {};
    const modes = attrs.hvac_modes || ['off', 'cool', 'heat', 'auto'];
    const target = attrs.temperature;
    const current = attrs.current_temperature;
    const bigv = document.createElement('div'); bigv.className = 'big-value';
    bigv.textContent = (target != null ? target : '--') + '°';
    body.appendChild(bigv);
    const sub = document.createElement('div'); sub.className = 'sub-value';
    sub.textContent = current != null ? ('目前 ' + current + '°') : '';
    body.appendChild(sub);
    const step = Number(tile.temp_step) || 1;
    const row = document.createElement('div'); row.className = 'stepper-row';
    row.appendChild(stepperBtn('−', () => climateStep(tile, -step)));
    row.appendChild(stepperBtn('+', () => climateStep(tile, step)));
    body.appendChild(row);
    const seg = document.createElement('div'); seg.className = 'btn-row';
    for (const m of modes) {
      seg.appendChild(segBtnEl(HVAC_LABELS[m] || m, () => {
        optimisticSet(tile.entity, { state: m });
        callService('climate', 'set_hvac_mode', tile.entity, { hvac_mode: m });
      }, state && state.state === m));
    }
    body.appendChild(seg);
  },
  cover(body, tile, state) {
    const attrs = (state && state.attributes) || {};
    const s = state ? state.state : '';
    const row = document.createElement('div'); row.className = 'btn-row';
    row.appendChild(segBtnEl('開', () => callService('cover', 'open_cover', tile.entity), s === 'open'));
    row.appendChild(segBtnEl('停', () => callService('cover', 'stop_cover', tile.entity), false));
    row.appendChild(segBtnEl('關', () => callService('cover', 'close_cover', tile.entity), s === 'closed'));
    body.appendChild(row);
    if (attrs.current_position != null) {
      body.appendChild(sliderBlock('開合程度', attrs.current_position, 0, 100, '%', (v) => callService('cover', 'set_cover_position', tile.entity, { position: Number(v) }), 1));
    }
  },
  media_player(body, tile, state) {
    const attrs = (state && state.attributes) || {};
    if (attrs.media_title) {
      const t = document.createElement('div'); t.className = 'sub-value'; t.style.marginTop = '0';
      t.textContent = [attrs.media_title, attrs.media_artist].filter(Boolean).join(' · ');
      body.appendChild(t);
    }
    const controls = document.createElement('div'); controls.className = 'media-controls';
    const playing = state && state.state === 'playing';
    controls.appendChild(mediaBtn(ICON_PREV, () => callService('media_player', 'media_previous_track', tile.entity)));
    controls.appendChild(mediaBtn(playing ? ICON_PAUSE : ICON_PLAY, () => callService('media_player', 'media_play_pause', tile.entity), true));
    controls.appendChild(mediaBtn(ICON_NEXT, () => callService('media_player', 'media_next_track', tile.entity)));
    body.appendChild(controls);
    if (attrs.volume_level != null) {
      const vol = Math.round(attrs.volume_level * 100);
      body.appendChild(sliderBlock('音量', vol, 0, 100, '%', (v) => callService('media_player', 'volume_set', tile.entity, { volume_level: Number(v) / 100 }), 1));
    }
  },
  vacuum(body, tile, state) {
    const s = state ? state.state : '';
    const cleaning = s === 'cleaning';
    const row = document.createElement('div'); row.className = 'btn-row';
    row.appendChild(segBtnEl(cleaning ? '暫停' : '開始', () => callService('vacuum', cleaning ? 'pause' : 'start', tile.entity), cleaning));
    row.appendChild(segBtnEl('回充', () => callService('vacuum', 'return_to_base', tile.entity), s === 'returning'));
    body.appendChild(row);
  },
};

/* ============================================================
 * Settings view
 * ============================================================ */
function updateConnDot() {
  const dot = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  if (dot) dot.classList.toggle('ok', CONNECTED);
  if (label) label.textContent = CONNECTED ? '已連線 (即時同步)' : '未連線';
}

function openSettings() {
  document.getElementById('ha-url').value = CONFIG.ha_url || '';
  document.getElementById('ha-token').value = CONFIG.ha_token || '';
  document.getElementById('theme-select').value = CONFIG.theme || 'auto';
  document.getElementById('columns-select').value = String(CONFIG.columns || 4);
  document.getElementById('zoom-select').value = String(CONFIG.zoom || 100);
  document.getElementById('lock-position-check').checked = !!CONFIG.lock_position;
  document.getElementById('start-on-boot-check').checked = !!CONFIG.start_on_boot;
  document.getElementById('fixed-size-check').checked = !!CONFIG.fixed_size;
  document.getElementById('fixed-width-input').value = String(CONFIG.fixed_width || 400);
  document.getElementById('fixed-height-input').value = String(CONFIG.fixed_height || 300);
  document.getElementById('fixed-size-fields').hidden = !CONFIG.fixed_size;
  document.getElementById('test-conn-result').textContent = '';
  renderTileList();
  updateConnDot();
  showView('view-settings');
}

async function saveHaConfig(url, token) {
  CONFIG.ha_url = url;
  CONFIG.ha_token = token;
  try { await window.pywebview.api.save_ha_config(url, token); } catch (e) { /* ignore */ }
}

async function savePrefs() {
  try {
    await window.pywebview.api.save_prefs(CONFIG.theme, CONFIG.columns, CONFIG.lock_position,
      CONFIG.zoom, CONFIG.fixed_size, CONFIG.fixed_width, CONFIG.fixed_height);
  } catch (e) { /* ignore */ }
}

async function closeSettingsAndSave() {
  const url = document.getElementById('ha-url').value.trim();
  const token = document.getElementById('ha-token').value.trim();
  if (url !== CONFIG.ha_url || token !== CONFIG.ha_token) await saveHaConfig(url, token);
  showView('view-grid');
}

async function persistTiles() {
  try { await window.pywebview.api.save_tiles(CONFIG.tiles); } catch (e) { /* ignore */ }
  renderGrid();
}

function renderTileList() {
  const wrap = document.getElementById('tile-list');
  wrap.innerHTML = '';
  document.getElementById('tile-count').textContent = (CONFIG.tiles || []).length;
  (CONFIG.tiles || []).forEach((t, idx) => {
    const row = document.createElement('div'); row.className = 'tile-row';
    row.draggable = true; row.dataset.idx = String(idx);

    const handle = document.createElement('span'); handle.className = 'tr-handle'; handle.textContent = '⠿';
    row.appendChild(handle);

    const icon = document.createElement('div'); icon.className = 'tr-icon';
    icon.innerHTML = svgIcon(t.icon || domainMeta(t.domain).icon);
    row.appendChild(icon);

    const text = document.createElement('div'); text.className = 'tr-text';
    const room = document.createElement('div'); room.className = 'tr-room';
    room.textContent = t.room || t.entity; room.title = '雙擊重新命名';
    room.addEventListener('dblclick', () => renameTileRoom(t, room));
    const ent = document.createElement('div'); ent.className = 'tr-entity'; ent.textContent = t.entity;
    text.appendChild(room); text.appendChild(ent);
    row.appendChild(text);

    if (t.domain === 'climate') {
      const stepWrap = document.createElement('label'); stepWrap.className = 'tr-step'; stepWrap.title = '每次調整溫度的幅度';
      const stepLabel = document.createElement('span'); stepLabel.textContent = '±';
      const stepInput = document.createElement('input');
      stepInput.type = 'number'; stepInput.min = '0.5'; stepInput.step = '0.5';
      stepInput.value = String(Number(t.temp_step) || 1);
      stepInput.addEventListener('change', async () => {
        const v = parseFloat(stepInput.value);
        t.temp_step = (Number.isFinite(v) && v > 0) ? v : 1;
        stepInput.value = String(t.temp_step);
        await persistTiles();
      });
      stepWrap.appendChild(stepLabel); stepWrap.appendChild(stepInput);
      row.appendChild(stepWrap);
    }

    const del = document.createElement('button'); del.className = 'tr-btn'; del.textContent = '✕';
    del.addEventListener('click', async () => {
      CONFIG.tiles.splice(idx, 1);
      await persistTiles();
      renderTileList();
    });
    row.appendChild(del);

    wrap.appendChild(row);
  });
  attachTileListDnD(wrap);
}

function renameTileRoom(tile, el) {
  const input = document.createElement('input');
  input.value = tile.room || '';
  input.style.cssText = 'width:100%;font-size:12.5px;padding:2px 4px;border-radius:6px;border:1px solid var(--input-border);background:var(--input-bg);color:var(--text-on-1);';
  el.replaceWith(input);
  input.focus(); input.select();
  const commit = async () => {
    tile.room = input.value.trim() || tile.entity;
    await persistTiles();
    renderTileList();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') input.blur();
    if (e.key === 'Escape') { input.value = tile.room; input.blur(); }
  });
  input.addEventListener('blur', commit, { once: true });
}

function attachTileListDnD(wrap) {
  let dragIdx = null;
  wrap.querySelectorAll('.tile-row').forEach((row) => {
    row.addEventListener('dragstart', () => {
      dragIdx = Number(row.dataset.idx);
      row.classList.add('dragging');
    });
    row.addEventListener('dragend', () => row.classList.remove('dragging'));
    row.addEventListener('dragover', (e) => e.preventDefault());
    row.addEventListener('drop', async (e) => {
      e.preventDefault();
      const targetIdx = Number(row.dataset.idx);
      if (dragIdx === null || targetIdx === dragIdx) return;
      const arr = CONFIG.tiles;
      const [moved] = arr.splice(dragIdx, 1);
      arr.splice(targetIdx, 0, moved);
      dragIdx = null;
      await persistTiles();
      renderTileList();
    });
  });
}

async function openPicker() {
  document.getElementById('picker-search').value = '';
  document.getElementById('picker-list').innerHTML = '<div class="hint">載入中...</div>';
  showView('view-picker');
  try { allEntities = await window.pywebview.api.get_entities(); } catch (e) { allEntities = []; }
  renderPickerList('');
}

function renderPickerList(query) {
  const list = document.getElementById('picker-list');
  list.innerHTML = '';
  const q = (query || '').toLowerCase();
  const used = new Set((CONFIG.tiles || []).map((t) => t.entity));
  const groups = new Map();
  for (const e of allEntities) {
    if (used.has(e.entity_id)) continue;
    const hay = (e.entity_id + ' ' + (e.name || '')).toLowerCase();
    if (q && !hay.includes(q)) continue;
    if (!groups.has(e.domain)) groups.set(e.domain, []);
    groups.get(e.domain).push(e);
  }
  let any = false;
  for (const domain of Object.keys(DOMAIN_LABELS)) {
    const items = groups.get(domain);
    if (!items || !items.length) continue;
    any = true;
    const gl = document.createElement('div'); gl.className = 'picker-group-label'; gl.textContent = DOMAIN_LABELS[domain];
    list.appendChild(gl);
    for (const e of items) {
      const row = document.createElement('div'); row.className = 'picker-item';
      const icon = document.createElement('div'); icon.className = 'tr-icon';
      icon.innerHTML = svgIcon(domainMeta(domain).icon);
      row.appendChild(icon);
      const text = document.createElement('div'); text.className = 'pi-text';
      const name = document.createElement('div'); name.className = 'pi-name'; name.textContent = e.name || e.entity_id;
      const id = document.createElement('div'); id.className = 'pi-id'; id.textContent = e.entity_id;
      text.appendChild(name); text.appendChild(id);
      row.appendChild(text);
      row.addEventListener('click', () => addTileFromEntity(e));
      list.appendChild(row);
    }
  }
  if (!any) list.innerHTML = '<div class="hint">沒有符合的實體</div>';
}

async function addTileFromEntity(e) {
  const tile = {
    id: (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('tile-' + Date.now() + '-' + Math.random().toString(36).slice(2)),
    entity: e.entity_id, domain: e.domain,
    room: e.name || e.entity_id, label: '', icon: '', on_mode: 'cool', temp_step: 1,
  };
  CONFIG.tiles = (CONFIG.tiles || []).concat([tile]);
  if (e.state && !STATES[e.entity_id]) STATES[e.entity_id] = e.state;
  await persistTiles();
  showView('view-settings');
  renderTileList();
}

/* ============================================================
 * Toast
 * ============================================================ */
let toastTimer = null;
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.classList.remove('show'); setTimeout(() => { t.hidden = true; }, 250); }, 2200);
}

/* ============================================================
 * Static wiring
 * ============================================================ */
function init() {
  document.getElementById('empty-add-btn').addEventListener('click', openSettings);
  document.getElementById('add-tile-btn').addEventListener('click', openPicker);
  document.getElementById('detail-backdrop').addEventListener('click', closeDetail);
  document.getElementById('detail-edit-btn').addEventListener('click', () => showEditMode(true));
  document.getElementById('edit-done-btn').addEventListener('click', () => showEditMode(false));
  document.getElementById('edit-room-input').addEventListener('change', async (e) => {
    const tile = findTile(currentDetailTileId);
    if (!tile) return;
    tile.room = e.target.value.trim() || tile.entity;
    e.target.value = tile.room;
    document.getElementById('detail-room').textContent = tile.room;
    await persistTiles();
  });
  document.getElementById('edit-label-input').addEventListener('change', async (e) => {
    const tile = findTile(currentDetailTileId);
    if (!tile) return;
    tile.label = e.target.value.trim();
    await persistTiles();
  });
  document.getElementById('close-settings-btn').addEventListener('click', closeSettingsAndSave);
  document.getElementById('quit-btn').addEventListener('click', () => { window.pywebview.api.quit_app(); });
  document.getElementById('theme-select').addEventListener('change', async (e) => {
    CONFIG.theme = e.target.value;
    applyTheme();
    await savePrefs();
  });
  document.getElementById('columns-select').addEventListener('change', async (e) => {
    CONFIG.columns = Number(e.target.value);
    await savePrefs();
    renderGrid();
  });
  document.getElementById('lock-position-check').addEventListener('change', async (e) => {
    CONFIG.lock_position = !!e.target.checked;
    await savePrefs();
  });
  document.getElementById('zoom-select').addEventListener('change', async (e) => {
    CONFIG.zoom = Number(e.target.value);
    applyZoom();
    await savePrefs();
    syncWindowSize();
  });
  document.getElementById('fixed-size-check').addEventListener('change', async (e) => {
    CONFIG.fixed_size = !!e.target.checked;
    document.getElementById('fixed-size-fields').hidden = !CONFIG.fixed_size;
    applyFixedSizeConstraint();
    await savePrefs();
    syncWindowSize();
  });
  document.getElementById('fixed-width-input').addEventListener('change', async (e) => {
    CONFIG.fixed_width = Math.max(120, Number(e.target.value) || 400);
    e.target.value = String(CONFIG.fixed_width);
    applyFixedSizeConstraint();
    await savePrefs();
    syncWindowSize();
  });
  document.getElementById('fixed-height-input').addEventListener('change', async (e) => {
    CONFIG.fixed_height = Math.max(90, Number(e.target.value) || 300);
    e.target.value = String(CONFIG.fixed_height);
    applyFixedSizeConstraint();
    await savePrefs();
    syncWindowSize();
  });
  document.getElementById('start-on-boot-check').addEventListener('change', async (e) => {
    const wanted = !!e.target.checked;
    e.target.disabled = true;
    try {
      const r = await window.pywebview.api.set_start_on_boot(wanted);
      CONFIG.start_on_boot = r && r.ok ? wanted : !wanted;
      if (!(r && r.ok)) showToast('設定開機啟動失敗: ' + (r && r.error ? r.error : '未知錯誤'));
    } catch (err) {
      CONFIG.start_on_boot = !wanted;
      showToast('設定開機啟動失敗');
    }
    e.target.checked = CONFIG.start_on_boot;
    e.target.disabled = false;
  });
  document.getElementById('test-conn-btn').addEventListener('click', async () => {
    const url = document.getElementById('ha-url').value.trim();
    const token = document.getElementById('ha-token').value.trim();
    const resEl = document.getElementById('test-conn-result');
    resEl.textContent = '測試中...'; resEl.className = 'hint';
    try {
      const r = await window.pywebview.api.test_connection(url, token);
      if (r.ok) {
        resEl.textContent = '連線成功'; resEl.className = 'hint ok';
        await saveHaConfig(url, token);
      } else {
        resEl.textContent = '失敗: ' + r.detail; resEl.className = 'hint err';
      }
    } catch (e) {
      resEl.textContent = '失敗: ' + e; resEl.className = 'hint err';
    }
  });
  document.getElementById('picker-search').addEventListener('input', (e) => renderPickerList(e.target.value));

  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const action = el.dataset.action;
    if (action === 'close-detail') closeDetail();
    else if (action === 'close-settings') closeSettingsAndSave();
    else if (action === 'close-picker') { showView('view-settings'); renderTileList(); }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!document.getElementById('view-picker').hidden) { showView('view-settings'); renderTileList(); }
    else if (!document.getElementById('view-settings').hidden) closeSettingsAndSave();
    else if (currentDetailTileId) closeDetail();
  });

  // Keep header/back buttons from also starting a window-drag (they live
  // inside a .pywebview-drag-region header bar), and honor the "lock
  // position" setting by stopping the drag before pywebview's own
  // body-level mousedown listener ever sees it (capture phase runs first).
  document.addEventListener('mousedown', (e) => {
    if (e.target.closest('.icon-btn')) { e.stopPropagation(); return; }
    if (CONFIG.lock_position && e.target.closest('.pywebview-drag-region')) e.stopPropagation();
  }, true);
}

window.__openSettingsFromTray = function () {
  try { openSettings(); } catch (e) { /* ignore */ }
};
window.__setThemeFromTray = function (name) {
  CONFIG.theme = name;
  applyTheme();
  const sel = document.getElementById('theme-select');
  if (sel) sel.value = name;
};

init();
window.addEventListener('pywebviewready', boot);
