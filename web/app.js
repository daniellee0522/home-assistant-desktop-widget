"use strict";

/* ============================================================
 * Icons (hand-drawn, single <path> per glyph, 24x24 viewBox)
 * ============================================================ */
const ICON_PATHS = {
  light: '<path d="M12 2a7 7 0 00-4 12.74V17a1 1 0 001 1h6a1 1 0 001-1v-2.26A7 7 0 0012 2zm-2 18h4v1a1 1 0 01-1 1h-2a1 1 0 01-1-1v-1z"/>',
  switch: '<path d="M7 2h2v5H7zM15 2h2v5h-2zM6 7h12a1 1 0 011 1v4a7 7 0 01-6 6.93V22h-2v-3.07A7 7 0 015 12V8a1 1 0 011-1z"/>',
  climate: '<path d="M13 14.76V4a1 1 0 00-2 0v10.76a3.5 3.5 0 102 0zM12 6a1 1 0 011 1v7.17a1.5 1.5 0 11-2 0V7a1 1 0 011-1z"/>',
  // Hub plus one blade drawn three times, 120 degrees apart - the same
  // shape rotated rather than three hand-placed ones, so the blades
  // cannot drift out of balance.
  fan: '<circle cx="12" cy="12" r="2.1"/>'
     + '<path d="M12 9.9c-.3-3.3.4-6 2.3-7 2.2-1.2 4.6.3 4.3 2.7-.3 2.5-2.9 4-6.6 4.3z"/>'
     + '<path d="M12 9.9c-.3-3.3.4-6 2.3-7 2.2-1.2 4.6.3 4.3 2.7-.3 2.5-2.9 4-6.6 4.3z" transform="rotate(120 12 12)"/>'
     + '<path d="M12 9.9c-.3-3.3.4-6 2.3-7 2.2-1.2 4.6.3 4.3 2.7-.3 2.5-2.9 4-6.6 4.3z" transform="rotate(240 12 12)"/>',
  cover: '<path d="M4 3h16v2H4zM4 6.5h16v2H4zM4 10h16v2H4zM6 13h4v8H6zM14 13h4v8h-4z"/>',
  media: '<path d="M15 3v10.55A4 4 0 1013 17V8h5V3z"/>',
  lock: '<path d="M12 2a4 4 0 00-4 4v3H7a1 1 0 00-1 1v10a1 1 0 001 1h10a1 1 0 001-1V10a1 1 0 00-1-1h-1V6a4 4 0 00-4-4zm-2 7V6a2 2 0 114 0v3zm2 4a1.5 1.5 0 011.5 1.5c0 .6-.34 1.1-.83 1.36l.33 2.14h-2l.33-2.14A1.5 1.5 0 0112 13z"/>',
  // Shackle swung open; the keyhole is cut out with evenodd so the glass
  // tile shows through it.
  'lock-open': '<path fill-rule="evenodd" d="M6 10h12a1 1 0 011 1v10a1 1 0 01-1 1H6a1 1 0 01-1-1V11a1 1 0 011-1z'
             + 'M12 14a1.5 1.5 0 011.5 1.5c0 .6-.34 1.1-.83 1.36l.33 2.14h-2l.33-2.14A1.5 1.5 0 0112 14z"/>'
             + '<path d="M14 10V6a3.5 3.5 0 117 0v2h-2V6a1.5 1.5 0 10-3 0v4z"/>',
  vacuum: '<path d="M12 4a8 8 0 100 16 8 8 0 000-16zm0 2.4a5.6 5.6 0 110 11.2 5.6 5.6 0 010-11.2zm0 2.8a2.8 2.8 0 100 5.6 2.8 2.8 0 000-5.6z"/>',
  scene: '<path d="M5 19l9-9 2 2-9 9-2-2zm10-15.6l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM4 3.5l.7 1.6L6.3 5.8l-1.6.7L4 8.1l-.7-1.6L1.7 5.8l1.6-.7z"/>',
  script: '<path d="M6 3h2v2H7v14h1v2H6a1 1 0 01-1-1V4a1 1 0 011-1zm12 0a1 1 0 011 1v16a1 1 0 01-1 1h-2v-2h1V5h-1V3h2zM10 8l6 4-6 4z"/>',
  automation: '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
  sensor: '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 3a1.6 1.6 0 110 3.2A1.6 1.6 0 0112 5zm-2 6h4v8h-4z"/>',
  thermometer: '<path d="M12 2a3.2 3.2 0 00-3.2 3.2v7.9a5 5 0 106.4 0V5.2A3.2 3.2 0 0012 2zm0 1.9a1.3 1.3 0 011.3 1.3v8.8l.4.3a3.1 3.1 0 11-3.4 0l.4-.3V5.2A1.3 1.3 0 0112 3.9z"/>'
             + '<path d="M12 6.6a.9.9 0 01.9.9v7.2a2.1 2.1 0 11-1.8 0V7.5a.9.9 0 01.9-.9z"/>',
  humidity: '<path d="M12 2.8c3.4 4 6 7.1 6 10.1a6 6 0 11-12 0c0-3 2.6-6.1 6-10.1z"/>',
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
  const legacyMdi = { climate: 'air-conditioner', cover: 'blinds', curtain: 'curtains',
    vacuum: 'robot-vacuum', scene: 'palette', automation: 'robot' };
  const mdiName = typeof name === 'string' && name.startsWith('mdi:') ? name.slice(4) : legacyMdi[name];
  const mdiPath = mdiName && window.MDI_PATHS && window.MDI_PATHS[mdiName];
  const fallback = ICON_PATHS[name] || ICON_PATHS.sensor;
  return '<svg viewBox="0 0 24 24" aria-hidden="true">' + (mdiPath ? '<path d="' + mdiPath + '"/>' : fallback) + '</svg>';
}

/* ============================================================
 * Domain metadata
 * ============================================================ */
const DOMAIN_META = {
  light: { icon: 'light', expand: true },
  switch: { icon: 'switch', expand: true },
  input_boolean: { icon: 'switch', expand: true },
  climate: { icon: 'mdi:air-conditioner', expand: true },
  fan: { icon: 'fan', expand: true },
  cover: { icon: 'mdi:blinds', expand: true },
  media_player: { icon: 'media', expand: true },
  lock: { icon: 'lock' },
  vacuum: { icon: 'mdi:robot-vacuum', expand: true },
  scene: { icon: 'mdi:palette', momentary: true },
  script: { icon: 'script', momentary: true },
  automation: { icon: 'mdi:robot', momentary: true },
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
function domainMeta(domain) { return DOMAIN_META[domain] || DOMAIN_META.default; }

// A tile's icon is normally fixed by its domain (or overridden by hand),
// but a lock's whole job is to show which way it is, so it gets a second
// glyph rather than just a second colour. A hand-picked icon always wins.
function iconNameFor(tile, state) {
  if (tile.icon) return tile.icon;
  const haIcon = state && state.attributes && state.attributes.icon;
  if (typeof haIcon === 'string' && haIcon.startsWith('mdi:') &&
      window.MDI_PATHS && window.MDI_PATHS[haIcon.slice(4)]) return haIcon;
  if (tile.domain === 'lock' && state && state.state !== 'locked') return 'lock-open';
  // A sensor's generic dot says nothing; Home Assistant already tells us
  // what it measures, so use it rather than making people pick by hand.
  if (tile.domain === 'sensor') {
    const attrs = (state && state.attributes) || {};
    const unit = attrs.unit_of_measurement || '';
    if (attrs.device_class === 'temperature' || unit.indexOf('°') === 0) return 'thermometer';
    if (attrs.device_class === 'humidity' || unit === '%') return 'humidity';
  }
  return domainMeta(tile.domain).icon;
}

/* ============================================================
 * Global state
 * ============================================================ */
let CONFIG = {
  ha_url: '', ha_token: '', theme: 'auto', glass_style: 'classic', tiles: [],
  widgets: [], panel: { mode: 'grid', tiles: null },
  dim_when_idle: true, dim_after_sec: 120,
  lock_position: false, start_on_boot: false,
  zoom: 100,
};
let STATES = {};
let CONNECTED = false;
let entityToTileIds = {};
let currentDetailTileId = null;
let allEntities = [];

// This page runs in four OS windows, told apart by the URL fragment:
// the grid widget (none), #popover, #settings and #flyout (the tray panel).
// Each window shows one view; the grid never takes focus, Settings must,
// and Settings ignores the widget's zoom.
const WINDOW_HASH = (location.hash || '').replace('#', '') || 'grid';
const WINDOW_ROLE = WINDOW_HASH.split(':')[0];
// Which desktop widget this window is (grid windows only).
const WIDGET_ID = WINDOW_HASH.indexOf(':') >= 0
  ? WINDOW_HASH.slice(WINDOW_HASH.indexOf(':') + 1) : '';
const IS_POPOVER_WINDOW = WINDOW_ROLE === 'popover';
const IS_FLYOUT_WINDOW = WINDOW_ROLE === 'flyout';
// What Python calls this window.
const WINDOW_KIND = WINDOW_ROLE === 'grid'
  ? (WIDGET_ID ? 'w:' + WIDGET_ID : 'main') : WINDOW_ROLE;
const IS_SETTINGS_WINDOW = WINDOW_ROLE === 'settings';

// Widget sizes as [columns, rows] of tile cells (see config.WIDGET_SIZES).
const WIDGET_SIZES = { '1x1': [1, 1], '2x2': [2, 2], '2x4': [4, 2], '4x4': [4, 4] };

// Every tile this page knows about: each widget's, plus the panel's own.
function allTiles(cfg) {
  const c = cfg || CONFIG;
  const tiles = [];
  for (const w of (c.widgets || [])) tiles.push(...(w.tiles || []));
  if (c.panel && Array.isArray(c.panel.tiles)) tiles.push(...c.panel.tiles);
  return tiles;
}

function uniqueByEntity(tiles) {
  const seen = new Set();
  return tiles.filter((t) => !seen.has(t.entity) && seen.add(t.entity));
}

let settingsWidgetId = '';

// The widget the settings window is editing.
function settingsWidget(cfg) {
  const widgets = (cfg || CONFIG).widgets || [];
  return widgets.find((w) => w.id === settingsWidgetId) || widgets[0] || null;
}

// The tiles this window draws: a widget its own, the panel its own list or
// every widget's, Settings the widget being edited.
function tilesFor(cfg) {
  const widgets = cfg.widgets || [];
  if (WINDOW_ROLE === 'grid') {
    const w = widgets.find((x) => x.id === WIDGET_ID) || widgets[0];
    return w ? w.tiles : [];
  }
  if (IS_SETTINGS_WINDOW) {
    const w = settingsWidget(cfg);
    return w ? w.tiles : [];
  }
  if (IS_FLYOUT_WINDOW) {
    if (cfg.panel && Array.isArray(cfg.panel.tiles)) return cfg.panel.tiles;
    return uniqueByEntity(allTiles(cfg));
  }
  return allTiles(cfg);
}

function resolveWindowTiles() {
  CONFIG.tiles = tilesFor(CONFIG);
}

function myWidget() {
  const widgets = CONFIG.widgets || [];
  return widgets.find((w) => w.id === WIDGET_ID) || widgets[0] || null;
}

function findTile(id) { return allTiles().find((t) => t.id === id); }
function friendlyName(state) { return state && state.attributes && state.attributes.friendly_name; }

/* ============================================================
 * Realtime push handlers (called from Python)
 * ============================================================ */
window.__haPushBatch = function (items) {
  for (const [entityId, newState] of items) STATES[entityId] = newState;
  for (const [entityId] of items) updateTileByEntity(entityId);
};
// Short websocket drops usually recover within the client's backoff, so
// "disconnected" is only shown once it has lasted a few seconds.
let connDisconnectTimer = null;
window.__haStatus = function (connected) {
  if (connected) {
    if (connDisconnectTimer) { clearTimeout(connDisconnectTimer); connDisconnectTimer = null; }
    CONNECTED = true;
    updateConnDot();
  } else if (!connDisconnectTimer) {
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
  connectFrames();
  try {
    const data = await window.pywebview.api.bootstrap();
    CONFIG = data.config;
    CONNECTED = !!data.connected;
  } catch (e) {
    /* keep defaults, still render an empty widget */
  }
  resolveWindowTiles();
  // A widget made while the others are dimmed starts dimmed as well.
  if (CONFIG.dimmed && WINDOW_ROLE === 'grid') window.__setDimmed(true);
  setInterfaceLanguage(CONFIG.language);
  applyTheme();
  applySystemGlass();
  applyZoom();
  renderGrid();
  if (IS_FLYOUT_WINDOW) {
    document.documentElement.classList.add('is-flyout-window');
  }
  if (IS_POPOVER_WINDOW) {
    document.getElementById('view-grid').hidden = true;
    // Lays the card out in the flow so the window takes its size.
    document.documentElement.classList.add('is-popover-window');
  } else if (IS_SETTINGS_WINDOW) {
    openSettingsView();
    settingsBooted = true;
    if (pendingEditor !== null) { openEditor(pendingEditor); pendingEditor = null; }
  }
  updateConnDot();
  markLayoutReady();
  try { await window.pywebview.api.ui_ready(); } catch (e) { /* ignore */ }
  startBackdropTicker();

  // After the first render, so an unreachable Home Assistant never delays
  // it; tiles show as unavailable until this or a websocket push arrives.
  window.pywebview.api.fetch_initial_states().then((states) => {
    if (states && Object.keys(states).length) {
      for (const [entityId, state] of Object.entries(states)) STATES[entityId] = state;
      for (const entityId of Object.keys(states)) updateTileByEntity(entityId);
    }
  }).catch(() => { /* ignore */ });

  // First run: only the grid window raises Settings.
  const firstWidget = (CONFIG.widgets || [])[0];
  if (WINDOW_ROLE === 'grid' && (!firstWidget || firstWidget.id === WIDGET_ID) &&
      !CONFIG.ha_token && !allTiles().length) {
    setTimeout(openSettings, 150);
  }
}

function applyTheme() {
  // The tray panel opens over other applications, so it has its own theme.
  const panel = CONFIG.panel_theme || 'follow';
  const theme = (IS_FLYOUT_WINDOW && panel !== 'follow') ? panel : (CONFIG.theme || 'auto');
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.setAttribute('data-glass-style', CONFIG.glass_style || 'classic');
}

/* ============================================================
 * View switching + auto window sizing
 * ============================================================ */
// Swaps between the views that share the Settings window.
function showView(name) {
  for (const id of ['view-grid', 'view-settings', 'view-picker', 'view-editor']) {
    document.getElementById(id).hidden = id !== name;
  }
}

// Every window is sized to its #stage. The page converts the measured CSS
// size to physical pixels with its own devicePixelRatio, and Python sets
// exactly that (see resize_window in main.py).
let resizeRaf = null;
let resizeSeq = 0;
let lastRequestedSize = '';

// The tray panel's own compact scale, independent of the widget's zoom.
const FLYOUT_ZOOM = 0.5;

function applyZoom() {
  // Settings is never scaled, so its controls stay usable at any zoom.
  const z = IS_SETTINGS_WINDOW
    ? 1
    : IS_FLYOUT_WINDOW
      ? FLYOUT_ZOOM
      : Math.max(50, Math.min(200, Number(CONFIG.zoom) || 100)) / 100;
  document.documentElement.style.zoom = String(z);
  currentZoom = z;
}
// Needed to convert computed CSS lengths (which ignore `zoom`) to device
// pixels in cardGeometry.
let currentZoom = 1;

// A desktop widget is a grid of whole tile cells (1x1, 2x2, 2x4, 4x4),
// padded and spaced exactly like the original widget, so a tile is the same
// size in every widget. Only one tile form is used at a time: big squares
// (2x2 cells), long bars (2x1) or the small squares (1x1), whichever fills
// the widget for the number of tiles it has.
const CELL_W = 152, CELL_H = 146, WIDGET_PAD = 14, WIDGET_GAP = 14;
const BIG_TILE_SCALE = 1.4;
let tileForm = 'small';

function tileFormFor(cols, rows, count) {
  const cells = cols * rows;
  if (count > 0 && cells >= 4 && count <= cells / 4) return 'big';
  if (count > 0 && cells >= 2 && count <= cells / 2) return 'bar';
  return 'small';
}

// Everything a widget's layout needs, as CSS variables, for a size and a
// number of tiles.
function widgetGeometry(size, count) {
  const [cols, rows] = WIDGET_SIZES[size] || WIDGET_SIZES['2x4'];
  const width = cols * CELL_W + (cols - 1) * WIDGET_GAP + 2 * WIDGET_PAD;
  const height = rows * CELL_H + (rows - 1) * WIDGET_GAP + 2 * WIDGET_PAD;
  const form = tileFormFor(cols, rows, count);
  const span = form === 'big' ? [2, 2] : form === 'bar' ? [2, 1] : [1, 1];
  return {
    cols, rows, width, height, form, small: cols * rows === 1,
    vars: {
      '--cols': cols, '--rows': rows,
      '--widget-w': width + 'px', '--widget-h': height + 'px',
      '--cell-w': CELL_W + 'px', '--cell-h': CELL_H + 'px',
      '--ts': 1, '--tz': form === 'big' ? BIG_TILE_SCALE : 1,
      '--span-c': span[0], '--span-r': span[1],
    },
  };
}

function applyWidgetGeometry(el, geometry) {
  el.classList.add('widget-scope');
  el.classList.toggle('is-widget-small', geometry.small);
  for (const [name, value] of Object.entries(geometry.vars)) el.style.setProperty(name, value);
}

function layoutWidget(count) {
  const widget = myWidget();
  const geometry = widgetGeometry(widget && widget.size, count);
  tileForm = geometry.form;
  applyWidgetGeometry(document.documentElement, geometry);
}

// The last resize requested, so work that needs the final size can wait
// for it (see __armBackdrop).
let pendingResize = Promise.resolve();

// The ResizeObserver fires immediately on the still-empty #stage; sizes
// only count once boot() has rendered this window's view.
let layoutReady = false;

function markLayoutReady() {
  if (layoutReady) return;
  layoutReady = true;
  syncWindowSize();
}

function syncWindowSize() {
  if (!layoutReady) return;
  if (resizeRaf) cancelAnimationFrame(resizeRaf);
  resizeRaf = requestAnimationFrame(() => {
    if (!(window.pywebview && window.pywebview.api)) return;
    const dpr = window.devicePixelRatio || 1;
    const stage = document.getElementById('stage');
    const rect = stage.getBoundingClientRect();
    const cssW = rect.width, cssH = rect.height;
    resizeSeq += 1;

    const physW = Math.ceil(cssW * dpr), physH = Math.ceil(cssH * dpr);
    if (physW <= 0 || physH <= 0) return;
    const sizeKey = `${physW}:${physH}`;
    if (sizeKey === lastRequestedSize) return;
    lastRequestedSize = sizeKey;
    const api = window.pywebview.api;
    const done = IS_POPOVER_WINDOW ? api.resize_popover_window(physW, physH, resizeSeq)
      : IS_SETTINGS_WINDOW ? api.resize_settings_window(physW, physH, resizeSeq)
      : IS_FLYOUT_WINDOW ? api.resize_flyout_window(physW, physH, resizeSeq)
      : api.resize_window(physW, physH, resizeSeq, WIDGET_ID);
    pendingResize = Promise.resolve(done).catch(() => {
      if (lastRequestedSize === sizeKey) lastRequestedSize = '';
    });
    // The backdrop is captured at the window's size; re-take it.
    Promise.resolve(done).then(() => refreshBackdropSoon()).catch(() => {});
  });
}
new ResizeObserver(syncWindowSize).observe(document.getElementById('stage'));

// A DPR change need not change the CSS dimensions observed above.
let dpiQuery = null;
let displayDpr = window.devicePixelRatio || 1;
function watchDisplayScale() {
  if (dpiQuery) dpiQuery.removeEventListener('change', displayScaleChanged);
  dpiQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
  dpiQuery.addEventListener('change', displayScaleChanged);
}
function displayScaleChanged() {
  displayDpr = window.devicePixelRatio || 1;
  watchDisplayScale();
  window.__recoverDisplay();
}
watchDisplayScale();
window.addEventListener('resize', () => {
  if ((window.devicePixelRatio || 1) !== displayDpr) displayScaleChanged();
});

/* ============================================================
 * Frosted backdrop
 * ============================================================ */
// Python captures the desktop behind this window and returns a blurred copy
// (the liquid lens refracts that picture too). The page paints it
// into #backdrop-glass, clipped to the card. Outside the card the window is
// transparent, so the rounded corners show the live desktop.
//
// Sampling is chained, not on an interval. Through Desktop Duplication the
// host answers when the screen under the window changes ("paced"), so the
// next request goes out at once and the display sets the rate. Otherwise
// (compatibility capture, GDI fallback) it is paced from what a capture
// costs: BACKDROP_DUTY is how many times that cost to wait before the next
// one, so slow machines thin the rate out instead of pinning a core.
const BACKDROP_DUTY = 4;
const BACKDROP_FLOOR_MS = 16;
// The open tray panel sits over other applications (often a scrolling
// page), so it samples faster and never backs off.
const PANEL_DUTY = 2;
const PANEL_FLOOR_MS = 16;
const BACKDROP_IDLE_MS = 3000;        // once the picture stops changing
// Identical frames in a row before the desktop counts as still.
const BACKDROP_STILL_BEFORE_IDLE = 4;
let backdropPending = false;
let backdropTimer = null;
let backdropHash = null;
let backdropGeneration = 0;
let backdropStill = 0;
// Set when Python skips a capture (window hidden or covered); replaces
// the normal pacing while it lasts.
let backdropSkipMs = 0;
// Where a dragged window is going, so the capture is taken there.
let backdropAt = null;
let backdropFrameMs = 60;
// True while the host paces reads by the screen (see above).
let backdropPaced = false;

// Tracks the cheap end of capture cost: occasional spikes (e.g. while the
// page repaints) must not set the pace. Drops immediately, rises slowly.
function noteFrameCost(ms) {
  if (!(ms > 0)) return;
  backdropFrameMs = ms < backdropFrameMs ? ms : backdropFrameMs * 0.9 + ms * 0.1;
}

let glassCtx = null;

// True when DWM draws the glass for this window (see _set_system_glass in
// main.py); the page then paints no backdrop at all.
function systemGlass() {
  return CONFIG.glass_style !== 'liquid'
    && CONFIG.glass_mode === 'system' && CONFIG.system_glass_ok === true
    && CONFIG.system_glass_active?.[WINDOW_KIND] === true
    && (WINDOW_ROLE === 'grid' || WINDOW_KIND === 'popover'
        || WINDOW_KIND === 'flyout');
}

function applySystemGlass() {
  document.documentElement.classList.toggle('is-system-glass', systemGlass());
}

// The visible card in the glass canvas's device pixels, plus its corner
// radius. A card within CARD_SNAP_PX of the canvas edges is snapped to
// them, absorbing rounding differences between the card and the window.
const CARD_SNAP_PX = 4;

// The card's geometry from the last moment nothing was animating. The
// glass canvas animates with the card, so measuring mid-animation would
// apply the transform twice.
let restingCard = null;

function cardGeometry() {
  const cv = document.getElementById('backdrop-glass');
  if (!cv) return null;
  const dpr = window.devicePixelRatio || 1;
  const view = document.getElementById('view-grid');
  const animating = !!(view && view.getAnimations && view.getAnimations().length);
  if (animating && restingCard) return restingCard;
  for (const card of document.querySelectorAll('.card-bg')) {
    const r = card.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;        // a view that is not showing
    const radius = (parseFloat(getComputedStyle(card).borderTopLeftRadius) || 0)
      * currentZoom * dpr;
    const box = { x: r.left * dpr, y: r.top * dpr, w: r.width * dpr, h: r.height * dpr,
                  radius: radius, fills: false };
    if (box.x <= CARD_SNAP_PX && box.y <= CARD_SNAP_PX
        && box.x + box.w >= cv.width - CARD_SNAP_PX
        && box.y + box.h >= cv.height - CARD_SNAP_PX) {
      box.x = 0;
      box.y = 0;
      box.w = cv.width;
      box.h = cv.height;
      box.fills = true;
    }
    if (!animating) restingCard = box;
    return box;
  }
  return null;
}

// The window's box in CSS pixels: the glass canvas covers it, except in
// system-glass mode where the canvas is hidden and the viewport is used.
function viewportBox() {
  const g = document.getElementById('backdrop-glass');
  if (g) {
    const r = g.getBoundingClientRect();
    if (r.width >= 1 && r.height >= 1) return r;
  }
  return { width: window.innerWidth, height: window.innerHeight };
}

// Port of KMPLiquidGlass's Skia Lens.kt sampling model: signed distance to
// a rounded rectangle, its outward normal, and the quarter-circle falloff.
// The untouched interior is already drawn from the same sharp capture.
let lensSourceCanvas = null;
let lensOutputCanvas = null;
let liquidGpu = null;
let liquidGpuUnavailable = false;

function initLiquidGpu() {
  if (liquidGpu || liquidGpuUnavailable) return liquidGpu;
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl2', {
    alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: true,
  });
  if (!gl) { liquidGpuUnavailable = true; return null; }
  const compile = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return null;
    return shader;
  };
  const vertex = compile(gl.VERTEX_SHADER, `#version 300 es
    void main() {
      vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
      gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
    }`);
  const fragment = compile(gl.FRAGMENT_SHADER, `#version 300 es
    precision highp float;
    uniform sampler2D backdrop;
    uniform vec2 canvasSize;
    uniform vec4 cardRect;
    uniform float cornerRadius;
    uniform float refractionHeight;
    uniform float refractionAmount;
    uniform float lensSoftness;
    uniform float lensOpacity;
    out vec4 color;
    void main() {
      vec2 coord = vec2(gl_FragCoord.x, canvasSize.y - gl_FragCoord.y);
      vec2 center = cardRect.xy + cardRect.zw * 0.5;
      vec2 halfSize = cardRect.zw * 0.5;
      vec2 p = coord - center;
      float radius = min(cornerRadius, min(halfSize.x, halfSize.y));
      vec2 q = abs(p) - (halfSize - vec2(radius));
      vec2 outside = max(q, 0.0);
      const float exponent = 4.0; // CSS superellipse(2), C3 at straight edges
      float superNorm = pow(pow(outside.x, exponent) +
        pow(outside.y, exponent), 1.0 / exponent);
      float sd = superNorm - radius + min(max(q.x, q.y), 0.0);
      if (sd > 0.0) { color = vec4(0.0); return; }
      if (-sd >= refractionHeight) {
        color = vec4(0.0);
        return;
      }
      // Lens.kt: quarter-circle falloff from signed distance, followed by
      // the negative rounded-rectangle normal and an inward texture sample.
      float t = 1.0 + sd / refractionHeight;
      float strength = 1.0 - sqrt(max(0.0, 1.0 - t * t));
      float gradRadius = min(radius * 1.5, min(halfSize.x, halfSize.y));
      vec2 gq = abs(p) - (halfSize - vec2(gradRadius));
      vec2 outer = max(gq, 0.0);
      vec2 normal = dot(outer, outer) > 0.0
        ? sign(p) * normalize(pow(outer, vec2(exponent - 1.0)))
        : sign(p) * (gq.x > gq.y ? vec2(1.0, 0.0) : vec2(0.0, 1.0));
      vec2 sampled = clamp(coord - normal * strength * refractionAmount,
        vec2(0.5), canvasSize - vec2(0.5));
      vec2 uv = vec2(sampled.x / canvasSize.x, 1.0 - sampled.y / canvasSize.y);
      vec2 blurStep = vec2(lensSoftness / canvasSize.x,
        lensSoftness / canvasSize.y);
      // Centre-weighted 3x3 Gaussian. Four diagonal taps alone create a
      // repeating diamond pattern on fine desktop textures behind tiles.
      color = texture(backdrop, uv) * 0.25
        + (texture(backdrop, uv + vec2(-blurStep.x, 0.0))
          + texture(backdrop, uv + vec2(blurStep.x, 0.0))
          + texture(backdrop, uv + vec2(0.0, -blurStep.y))
          + texture(backdrop, uv + vec2(0.0, blurStep.y))) * 0.125
        + (texture(backdrop, uv + vec2(-blurStep.x, -blurStep.y))
          + texture(backdrop, uv + vec2(blurStep.x, -blurStep.y))
          + texture(backdrop, uv + vec2(-blurStep.x, blurStep.y))
          + texture(backdrop, uv + vec2(blurStep.x, blurStep.y))) * 0.0625;
      // A narrow refracted rim: RGB samples separate only at the outer
      // edge. The inner region retains the ordinary lens sample.
      float rim = 1.0 - smoothstep(0.5, 4.0, -sd);
      vec2 split = normal * (2.5 * rim);
      vec2 redCoord = clamp(sampled - split, vec2(0.5), canvasSize - vec2(0.5));
      vec2 blueCoord = clamp(sampled + split, vec2(0.5), canvasSize - vec2(0.5));
      float red = texture(backdrop, vec2(redCoord.x / canvasSize.x,
        1.0 - redCoord.y / canvasSize.y)).r;
      float blue = texture(backdrop, vec2(blueCoord.x / canvasSize.x,
        1.0 - blueCoord.y / canvasSize.y)).b;
      color.r = mix(color.r, red, rim);
      color.b = mix(color.b, blue, rim);
      float line = 1.0 - smoothstep(0.0, 1.8, abs(-sd - 1.4));
      color.rgb = mix(color.rgb, vec3(1.0), line * 0.16);
      color.a = lensOpacity * (1.0 - smoothstep(max(0.0, refractionHeight - 8.0),
        refractionHeight, -sd));
    }`);
  if (!vertex || !fragment) { liquidGpuUnavailable = true; return null; }
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    liquidGpuUnavailable = true;
    return null;
  }
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const uniforms = Object.fromEntries([
    'backdrop', 'canvasSize', 'cardRect', 'cornerRadius',
    'refractionHeight', 'refractionAmount', 'lensSoftness', 'lensOpacity',
  ].map(name => [name, gl.getUniformLocation(program, name)]));
  liquidGpu = { canvas, gl, program, texture, uniforms, half: document.createElement('canvas'),
                textureW: 0, textureH: 0 };
  canvas.addEventListener('webglcontextlost', () => {
    liquidGpu = null;
    liquidGpuUnavailable = true;
  });
  return liquidGpu;
}

function paintLiquidLensGpu(ctx, image, width, height, card) {
  const gpu = initLiquidGpu();
  if (!gpu) return false;
  const { canvas, gl, program, texture, uniforms } = gpu;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  gl.viewport(0, 0, width, height);
  gl.useProgram(program);
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
  // The texture is the small picture stretched (smoothly) to half the
  // window's size. The GPU's own bilinear stretch of the raw picture leaves
  // faint diagonal creases where the lens bends the sampling across texels.
  const half = gpu.half;
  const hw = Math.max(1, Math.ceil(width / 2)), hh = Math.max(1, Math.ceil(height / 2));
  if (half.width !== hw || half.height !== hh) { half.width = hw; half.height = hh; }
  const halfCtx = half.getContext('2d');
  halfCtx.imageSmoothingEnabled = true;
  halfCtx.imageSmoothingQuality = 'high';
  halfCtx.drawImage(image, 0, 0, hw, hh);
  if (gpu.textureW === hw && gpu.textureH === hh) {
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, gl.RGBA, gl.UNSIGNED_BYTE, half);
  } else {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, half);
    gpu.textureW = hw;
    gpu.textureH = hh;
  }
  gl.uniform1i(uniforms.backdrop, 0);
  gl.uniform2f(uniforms.canvasSize, width, height);
  gl.uniform4f(uniforms.cardRect, card.x, card.y, card.w, card.h);
  gl.uniform1f(uniforms.cornerRadius, card.radius);
  const refractionHeight = Math.min(46, card.radius * 1.05);
  gl.uniform1f(uniforms.refractionHeight, refractionHeight);
  gl.uniform1f(uniforms.refractionAmount,
    Math.min(58, refractionHeight * 1.45));
  gl.uniform1f(uniforms.lensSoftness, 1.2);
  gl.uniform1f(uniforms.lensOpacity, 0.78);
  // The shader returns transparent beyond the refracted rim. Clear the old
  // frame, then shade only strips that can contain that rim. The extra
  // radius covers the rounded corners, including their diagonal samples.
  gl.disable(gl.SCISSOR_TEST);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  const x = Math.max(0, Math.floor(card.x));
  const y = Math.max(0, Math.floor(card.y));
  const right = Math.min(width, Math.ceil(card.x + card.w));
  const bottom = Math.min(height, Math.ceil(card.y + card.h));
  if (right > x && bottom > y) {
    const band = Math.ceil(Math.min(card.radius, card.w / 2, card.h / 2)
      + refractionHeight + 2);
    const innerTop = Math.min(bottom, y + band);
    const innerBottom = Math.max(innerTop, bottom - band);
    const innerLeft = Math.min(right, x + band);
    const innerRight = Math.max(innerLeft, right - band);
    if (innerLeft >= innerRight || innerTop >= innerBottom) {
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    } else {
      const strips = [
        [x, y, right - x, innerTop - y],
        [x, innerBottom, right - x, bottom - innerBottom],
        [x, innerTop, innerLeft - x, innerBottom - innerTop],
        [innerRight, innerTop, right - innerRight, innerBottom - innerTop],
      ];
      gl.enable(gl.SCISSOR_TEST);
      for (const [sx, sy, sw, sh] of strips) {
        if (sw <= 0 || sh <= 0) continue;
        gl.scissor(sx, height - sy - sh, sw, sh);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }
      gl.disable(gl.SCISSOR_TEST);
    }
    ctx.drawImage(canvas, x, y, right - x, bottom - y,
      x, y, right - x, bottom - y);
  }
  return true;
}

function paintLiquidLens(ctx, image, width, height, card) {
  if (paintLiquidLensGpu(ctx, image, width, height, card)) return;
  const heightPx = Math.min(46, card.radius * 1.05);
  const amountPx = Math.min(58, heightPx * 1.45);
  if (heightPx < 1) return;
  if (!lensSourceCanvas) lensSourceCanvas = document.createElement('canvas');
  if (!lensOutputCanvas) lensOutputCanvas = document.createElement('canvas');
  for (const canvas of [lensSourceCanvas, lensOutputCanvas]) {
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }
  const sourceCtx = lensSourceCanvas.getContext('2d', { willReadFrequently: true });
  const outputCtx = lensOutputCanvas.getContext('2d');
  sourceCtx.filter = 'blur(1.2px)';
  sourceCtx.drawImage(image, 0, 0, width, height);
  sourceCtx.filter = 'none';
  const source = sourceCtx.getImageData(0, 0, width, height).data;
  const result = outputCtx.createImageData(width, height);
  const dest = result.data;
  const cx = card.x + card.w / 2, cy = card.y + card.h / 2;
  const halfW = card.w / 2, halfH = card.h / 2;
  const radius = Math.min(card.radius, halfW, halfH);
  const exponent = 4;
  const normalPower = exponent - 1;
  const x0 = Math.max(0, Math.floor(card.x));
  const y0 = Math.max(0, Math.floor(card.y));
  const x1 = Math.min(width, Math.ceil(card.x + card.w));
  const y1 = Math.min(height, Math.ceil(card.y + card.h));
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const px = x + .5 - cx, py = y + .5 - cy;
      const qx = Math.abs(px) - (halfW - radius);
      const qy = Math.abs(py) - (halfH - radius);
      const ox = Math.max(qx, 0), oy = Math.max(qy, 0);
      const sd = Math.pow(ox ** exponent + oy ** exponent, 1 / exponent) - radius +
        Math.min(Math.max(qx, qy), 0);
      const inside = -sd;
      if (inside <= 0 || inside >= heightPx) continue;
      const t = 1 - inside / heightPx;
      const intensity = 1 - Math.sqrt(Math.max(0, 1 - t * t));
      const gradRadius = Math.min(radius * 1.5, halfW, halfH);
      const gx = Math.abs(px) - (halfW - gradRadius);
      const gy = Math.abs(py) - (halfH - gradRadius);
      const gox = Math.max(gx, 0), goy = Math.max(gy, 0);
      let nx, ny;
      if (gox || goy) {
        const length = Math.hypot(gox ** normalPower, goy ** normalPower);
        nx = Math.sign(px) * gox ** normalPower / length;
        ny = Math.sign(py) * goy ** normalPower / length;
      } else if (gx > gy) {
        nx = Math.sign(px); ny = 0;
      } else {
        nx = 0; ny = Math.sign(py);
      }
      // Lens.kt negates the SDF normal: sample farther inside the pane.
      const sx = Math.max(0, Math.min(width - 1, x - nx * intensity * amountPx));
      const sy = Math.max(0, Math.min(height - 1, y - ny * intensity * amountPx));
      const ix = Math.floor(sx), iy = Math.floor(sy);
      const fx = sx - ix, fy = sy - iy;
      const to = (y * width + x) * 4;
      for (let channel = 0; channel < 3; channel++) {
        const a = source[(iy * width + ix) * 4 + channel];
        const b = source[(iy * width + Math.min(ix + 1, width - 1)) * 4 + channel];
        const c = source[(Math.min(iy + 1, height - 1) * width + ix) * 4 + channel];
        const d = source[(Math.min(iy + 1, height - 1) * width + Math.min(ix + 1, width - 1)) * 4 + channel];
        dest[to + channel] = (a * (1 - fx) + b * fx) * (1 - fy)
          + (c * (1 - fx) + d * fx) * fy;
      }
      const rim = Math.max(0, Math.min(1, (4 - inside) / 3.5));
      const rx = Math.max(0, Math.min(width - 1, Math.round(sx - nx * 2.5 * rim)));
      const ry = Math.max(0, Math.min(height - 1, Math.round(sy - ny * 2.5 * rim)));
      const bx = Math.max(0, Math.min(width - 1, Math.round(sx + nx * 2.5 * rim)));
      const by = Math.max(0, Math.min(height - 1, Math.round(sy + ny * 2.5 * rim)));
      dest[to] = dest[to] * (1 - rim) + source[(ry * width + rx) * 4] * rim;
      dest[to + 2] = dest[to + 2] * (1 - rim)
        + source[(by * width + bx) * 4 + 2] * rim;
      const line = Math.max(0, 1 - Math.abs(inside - 1.4) / 1.8) * 0.16;
      for (let channel = 0; channel < 3; channel++)
        dest[to + channel] = dest[to + channel] * (1 - line) + 255 * line;
      const fadeStart = Math.max(0, heightPx - 8);
      const fade = Math.max(0, Math.min(1, (heightPx - inside) / (heightPx - fadeStart)));
      dest[to + 3] = Math.round(255 * 0.78 * fade * fade * (3 - 2 * fade));
    }
  }
  outputCtx.putImageData(result, 0, 0);
  ctx.drawImage(lensOutputCanvas, x0, y0, x1 - x0, y1 - y0,
    x0, y0, x1 - x0, y1 - y0);
}

// The outline only changes with the card's box, which is the same from one
// frame to the next, so it is traced once and reused.
let outlineKey = '';
let outlinePath = null;
function superellipsePath(shape) {
  const key = [shape.x, shape.y, shape.w, shape.h, shape.radius].join(',');
  if (key !== outlineKey || !outlinePath) {
    outlinePath = new Path2D();
    traceSuperellipse(outlinePath, shape);
    outlineKey = key;
  }
  return outlinePath;
}

function traceSuperellipse(ctx, shape) {
  const { x, y, w, h } = shape;
  const r = Math.max(0, Math.min(shape.radius, w / 2, h / 2));
  const curvePower = 0.5;
  if (ctx.beginPath) ctx.beginPath();
  if (!r) { ctx.rect(x, y, w, h); return; }
  const corner = (cx, cy, start) => {
    for (let i = 0; i <= 16; i++) {
      const angle = start + i * Math.PI / 32;
      const c = Math.cos(angle), s = Math.sin(angle);
      const px = cx + r * Math.sign(c) * Math.pow(Math.abs(c), curvePower);
      const py = cy + r * Math.sign(s) * Math.pow(Math.abs(s), curvePower);
      ctx.lineTo(px, py);
    }
  };
  ctx.moveTo(x + r, y);
  corner(x + w - r, y + r, -Math.PI / 2);
  corner(x + w - r, y + h - r, 0);
  corner(x + r, y + h - r, Math.PI / 2);
  corner(x + r, y + r, Math.PI);
  ctx.closePath();
}

// The card's outline as a CSS clip-path in the canvas's own CSS pixels. Clipping in the
// compositor, set only when the card's box changes, costs nothing per frame;
// clipping the canvas itself re-rasterised the outline every time.
let glassClipKey = '';
function applyGlassClip(glass, card, dpr) {
  // The page is scaled by CSS zoom, which scales the path as well.
  const unit = dpr * currentZoom;
  const key = [card.x, card.y, card.w, card.h, card.radius, unit].join(',');
  if (key === glassClipKey) return;
  glassClipKey = key;
  let d = '';
  const f = (n) => Math.round(n / unit * 100) / 100;
  traceSuperellipse({
    moveTo(x, y) { d += 'M' + f(x) + ' ' + f(y); },
    lineTo(x, y) { d += 'L' + f(x) + ' ' + f(y); },
    rect(x, y, rw, rh) {
      d += 'M' + f(x) + ' ' + f(y) + 'h' + f(rw) + 'v' + f(rh) + 'h' + f(-rw) + 'Z';
    },
    closePath() { d += 'Z'; },
  }, card);
  glass.style.clipPath = "path('" + d + "')";
}

function paintBackdrop(blurred, w, h) {
  const glass = document.getElementById('backdrop-glass');
  if (!glass) return;
  if (!glassCtx) glassCtx = glass.getContext('2d');
  if (systemGlass()) {
    glassCtx.clearRect(0, 0, glass.width, glass.height);
    return;
  }
  // A frame without a picture leaves the previous one in place rather than
  // flickering the card bare.
  if (!blurred) return;
  // The liquid lens paints around the card's edge, so it clips the canvas
  // itself; every other picture simply fills it.
  const lensed = CONFIG.glass_style === 'liquid' && !IS_POPOVER_WINDOW;
  const resized = glass.width !== w || glass.height !== h;
  if (resized) {
    glass.width = w;
    glass.height = h;
  } else if (lensed) {
    glassCtx.clearRect(0, 0, w, h);
  }
  const card = cardGeometry();
  if (!card) return;
  if (!lensed) {
    applyGlassClip(glass, card, window.devicePixelRatio || 1);
    // The picture is a small, already blurred copy: stretch it with the
    // smooth filter, or the interpolation grid shows through as noise.
    glassCtx.imageSmoothingEnabled = true;
    glassCtx.imageSmoothingQuality = 'high';
    glassCtx.drawImage(blurred, 0, 0, w, h);
    return;
  }
  if (glassClipKey) { glass.style.clipPath = ''; glassClipKey = ''; }
  // The same small picture is the card's fill and what the lens refracts,
  // so the rim is as soft as the rest.
  glassCtx.imageSmoothingEnabled = true;
  glassCtx.imageSmoothingQuality = 'high';
  glassCtx.save();
  glassCtx.clip(superellipsePath(card));
  glassCtx.drawImage(blurred, 0, 0, w, h);
  paintLiquidLens(glassCtx, blurred, w, h, card);
  glassCtx.restore();
}

// Base64 RGB pixels (blur_w x blur_h) to a canvas, reused from frame to frame.
let rawScratch = null;
let rawCtx = null;
let rawImage = null;
function rawToCanvas(shot) {
  const w = shot.blur_w, h = shot.blur_h;
  if (!rawScratch) {
    rawScratch = document.createElement('canvas');
    rawCtx = rawScratch.getContext('2d');
  }
  if (!rawImage || rawImage.width !== w || rawImage.height !== h) {
    rawScratch.width = w;
    rawScratch.height = h;
    rawImage = rawCtx.createImageData(w, h);
    rawImage.data.fill(255);                    // alpha stays opaque
  }
  const bin = atob(shot.blur_raw);
  const rgba = rawImage.data;
  for (let i = 0, j = 0, p = 0; i < w * h; i++, p += 4) {
    rgba[p] = bin.charCodeAt(j++);
    rgba[p + 1] = bin.charCodeAt(j++);
    rgba[p + 2] = bin.charCodeAt(j++);
  }
  rawCtx.putImageData(rawImage, 0, 0);
  return rawScratch;
}

// Paints one answer from Python, whether it came back from a call or was
// pushed by the stream below.
function applyShot(shot, generation, startedAt) {
  if (generation !== backdropGeneration) { backdropPending = false; return; }
  if (shot && typeof shot.system_glass === 'boolean') {
    const previous = systemGlass();
    CONFIG.system_glass_active = Object.assign({}, CONFIG.system_glass_active,
      { [WINDOW_KIND]: shot.system_glass });
    if (previous !== systemGlass()) {
      applySystemGlass();
      backdropHash = null;
    }
  }
  // Python skipped the capture (hidden or covered window).
  if (shot && shot.skip) {
    backdropSkipMs = shot.retry_ms || 500;
    backdropPending = false;
    return;
  }
  backdropSkipMs = 0;
  backdropPaced = !!(shot && shot.paced);
  // Paced from the capture's own cost, not the bridge round trip; a
  // screen-paced answer's time is mostly waiting, not cost.
  if (!backdropPaced) noteFrameCost((shot && shot.ms) || (performance.now() - startedAt));
  if (!shot) { backdropPending = false; return; }
  if (shot.unchanged) { backdropStill += 1; backdropPending = false; return; }
  backdropStill = 0;
  if (!shot.blur_raw) { backdropPending = false; return; }
  // The window may have been resized while this was in flight; a frame
  // of the old size would be stretched, so drop it and ask again.
  const live = viewportBox();
  const liveDpr = window.devicePixelRatio || 1;
  const liveW = Math.round(live.width * liveDpr);
  const liveH = Math.round(live.height * liveDpr);
  if (Math.abs(shot.w - liveW) > 3 || Math.abs(shot.h - liveH) > 3) {
    backdropHash = null;            // that frame was never painted
    backdropPending = false;
    refreshBackdropSoon(0);
    return;
  }
  // The blurred picture arrives as raw pixels and is drawn straight onto a
  // small canvas: no file to decode, nothing to release.
  try {
    paintBackdrop(rawToCanvas(shot), shot.w, shot.h);
    backdropHash = shot.hash;
  } finally {
    backdropPending = false;
  }
}

function refreshBackdrop() {
  if (backdropPending || !(window.pywebview && window.pywebview.api)) return Promise.resolve();
  backdropPending = true;
  const generation = backdropGeneration;
  const startedAt = performance.now();
  // Ask for exactly the device pixels this will be drawn at, so the image
  // lands 1:1 (see get_desktop_backdrop).
  const box = viewportBox();
  const dpr = window.devicePixelRatio || 1;
  return window.pywebview.api
    .get_desktop_backdrop(WINDOW_KIND, backdropHash,
                          Math.round(box.width * dpr), Math.round(box.height * dpr),
                          backdropAt ? backdropAt.x : null, backdropAt ? backdropAt.y : null)
    .then((shot) => applyShot(shot, generation, startedAt))
    .catch(() => { backdropHash = null; backdropPending = false; });
}

// ---- Pushed frames ----------------------------------------------------
// While the screen sets the pace, asking Python for each frame costs an HTTP
// round trip through Chromium's network service per frame. Instead Python
// is told once to keep watching and runs JavaScript here when there is a new
// picture. Anything that would change what is being asked for (a resize, a
// drag, an animation) ends the stream and the ticker takes over again.
// Pictures reach the page as messages on a Qt WebChannel, not as script text
// (see _FrameBridge in qtshell.py). False until the channel is connected.
let framesChannel = false;
function connectFrames() {
  if (!(window.QWebChannel && window.qt && window.qt.webChannelTransport)) return;
  try {
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      const bridge = channel.objects && channel.objects.frames;
      if (!bridge) return;
      bridge.frame.connect((text) => window.__backdropPush(JSON.parse(text)));
      framesChannel = true;
    });
  } catch (e) { /* the script route still works */ }
}

// Collect garbage now and then (the engine is started with --expose-gc; see
// qtshell.prepare). Each frame leaves a few KB of message and pixel buffers
// that the engine does not count towards a collection, so it would not run
// one on its own for a long time.
setInterval(() => {
  if (typeof window.gc === 'function' && !document.hidden) {
    try { window.gc(); } catch (e) { /* ignore */ }
  }
}, 8000);

let streaming = false;
let streamToken = null;
let streamBeat = 0;
let streamUnavailable = false;
let streamSeq = 0;
let queuedShot = null;
const STREAM_BEAT_MS = 5000;

function canStream() {
  return !streamUnavailable && backdropPaced && !backdropSkipMs && !backdropAt
    && !flyoutAnimating && !document.hidden
    && !!(window.pywebview && window.pywebview.api);
}

function enterStream() {
  const box = viewportBox();
  const dpr = window.devicePixelRatio || 1;
  const token = WINDOW_KIND + ':' + (++streamSeq);
  const w = Math.round(box.width * dpr);
  const h = Math.round(box.height * dpr);
  const send = () => window.pywebview.api
    .backdrop_stream(WINDOW_KIND, token, w, h, backdropHash, framesChannel);
  streaming = true;
  streamToken = token;
  queuedShot = null;
  send().catch(() => {
    if (streamToken !== token) return;
    streamUnavailable = true;
    leaveStream(true);
  });
  // Python lets go of a stream whose page stops answering.
  streamBeat = setInterval(() => { send().catch(() => {}); }, STREAM_BEAT_MS);
}

function leaveStream(resume) {
  if (!streaming) return false;
  streaming = false;
  streamToken = null;
  queuedShot = null;
  clearInterval(streamBeat);
  streamBeat = 0;
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.backdrop_stream(WINDOW_KIND, null).catch(() => {});
  }
  if (resume) startBackdropTicker();
  return true;
}

function paintPushed(shot) {
  backdropPending = true;
  try {
    applyShot(shot, backdropGeneration, performance.now());
  } catch (e) {
    backdropHash = null;
    backdropPending = false;
  }
  const next = queuedShot;
  queuedShot = null;
  if (next && streaming && next.token === streamToken) paintPushed(next);
}

window.__backdropPush = function (shot) {
  if (!streaming || !shot || shot.token !== streamToken) return;
  if (shot.stream_end) {
    // Python gave up the stream (window hidden or covered, capture
    // unavailable): its answer is handled like a call's, then ticking resumes.
    const pending = backdropPending;
    streaming = false;
    streamToken = null;
    queuedShot = null;
    clearInterval(streamBeat);
    streamBeat = 0;
    applyShot(shot, backdropGeneration, performance.now());
    backdropPending = pending;
    startBackdropTicker();
    return;
  }
  if (backdropPending) { queuedShot = shot; return; }
  paintPushed(shot);
};

// Anything that changes which pixels are behind the window invalidates the
// frame comparison as well as the image.
function invalidateBackdrop() {
  const wasStreaming = leaveStream(false);
  backdropGeneration += 1;
  backdropHash = null;
  backdropStill = 0;
  if (wasStreaming) startBackdropTicker();
}

// Called from Python after a suspend (see on_resume in main.py).
window.__invalidateBackdrop = function () {
  invalidateBackdrop();
  backdropFrameMs = 60;
  restartBackdropTicker();
};

window.__recoverDisplay = function () {
  // Windows may have resized the native window while the renderer slept.
  // Re-send even an unchanged size so the host can restore its geometry.
  lastRequestedSize = '';
  syncWindowSize();
  window.__invalidateBackdrop();
};

// Coalesced: resizes come in bursts.
let backdropSoonTimer = null;
function refreshBackdropSoon(delay) {
  invalidateBackdrop();
  clearTimeout(backdropSoonTimer);
  backdropSoonTimer = setTimeout(refreshBackdrop, delay === undefined ? 60 : delay);
}

function stopBackdropTicker() {
  leaveStream(false);
  clearTimeout(backdropTimer);
  backdropTimer = null;
}

// A hidden window has booked its next look up to a second away; coming on
// screen must not wait for it.
function restartBackdropTicker() {
  stopBackdropTicker();
  backdropSkipMs = 0;
  backdropStill = 0;
  startBackdropTicker();
}

function startBackdropTicker() {
  if (backdropTimer) return;
  const again = () => {
    const idle = document.hidden || flyoutAnimating;
    (idle ? Promise.resolve() : refreshBackdrop()).then(tick, tick);
  };
  const tick = () => {
    if (canStream()) {
      backdropTimer = null;
      enterStream();
      return;
    }
    // A screen-paced read already waited for a change. Otherwise the widget
    // backs off over still wallpaper; the open panel never does, since the
    // window behind it may start scrolling at any time.
    const openPanel = IS_FLYOUT_WINDOW && flyoutOpen;
    const wait = flyoutAnimating ? 40 : (backdropSkipMs
      || (backdropPaced ? 0 : openPanel
        ? Math.max(PANEL_FLOOR_MS, Math.round(backdropFrameMs * PANEL_DUTY))
        : backdropStill >= BACKDROP_STILL_BEFORE_IDLE
          ? BACKDROP_IDLE_MS
          : Math.max(BACKDROP_FLOOR_MS, Math.round(backdropFrameMs * BACKDROP_DUTY))));
    backdropTimer = setTimeout(again, wait);
  };
  refreshBackdrop().then(tick, tick);
}

/* ============================================================
 * Dragging the widget around the desktop
 * ============================================================ */
// Dragging by .drag-region, with a threshold so a plain click (e.g. one that
// dismisses the detail popover) never moves the window. Positions are sent
// as absolute physical pixels.
const DRAG_THRESHOLD_PX = 5;

function installWindowDrag() {
  // The popover and the tray panel are placed by Python.
  if (IS_POPOVER_WINDOW || IS_FLYOUT_WINDOW) return;
  const kind = IS_SETTINGS_WINDOW ? 'settings' : WINDOW_KIND;
  let start = null;

  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (CONFIG.lock_position && !IS_SETTINGS_WINDOW) return;
    if (!e.target.closest('.drag-region')) return;
    // Controls inside a drag region are for clicking.
    if (e.target.closest('button, input, select, textarea, a, [data-action]')) return;
    start = { sx: e.screenX, sy: e.screenY, origin: null, moved: false };
    // Once per drag: the origin only changes because we move it.
    window.pywebview.api.get_window_pos(kind)
      .then((pos) => { if (start) start.origin = pos; })
      .catch(() => { start = null; });
  });

  let dragRaf = 0;
  let dragTo = null;

  document.addEventListener('mousemove', (e) => {
    if (!start || !start.origin) return;
    const dpr = window.devicePixelRatio || 1;
    const dx = (e.screenX - start.sx) * dpr;
    const dy = (e.screenY - start.sy) * dpr;
    if (!start.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
    start.moved = true;
    dragTo = { x: Math.round(start.origin.x + dx), y: Math.round(start.origin.y + dy) };
    // At most one move per frame, however fast the mouse reports.
    if (dragRaf) return;
    dragRaf = requestAnimationFrame(() => {
      dragRaf = 0;
      const to = dragTo;
      if (!to) return;
      window.pywebview.api.move_window(to.x, to.y, kind).catch(() => {});
      // Not refreshBackdropSoon: that debounce would never fire mid-drag.
      // The sampler captures where the window is going instead.
      backdropAt = to;
      invalidateBackdrop();
    });
  });

  const end = () => { start = null; dragTo = null; backdropAt = null; };
  document.addEventListener('mouseup', end);
  window.addEventListener('blur', end);
}

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
    // Unlocked is normal, not an alert: soft green.
    case 'lock': return state && state.state === 'locked' ? 'var(--text-off-1)' : 'var(--accent-green-soft)';
    case 'vacuum': return on ? 'var(--accent-blue)' : 'var(--text-off-1)';
    case 'scene': case 'script': case 'automation': return 'var(--accent-blue)';
    case 'binary_sensor': return state && state.state === 'on' ? 'var(--accent-green)' : 'var(--text-off-1)';
    default: return 'var(--text-off-1)';
  }
}

const HVAC_COLORS = {
  cool: '#3fa9f5', heat: '#ff7a45', heat_cool: '#34c759',
  auto: '#34c759', dry: '#f0b429', fan_only: '#8e9aaf',
};

function climateBadge(state, on) {
  const attrs = (state && state.attributes) || {};
  const temp = attrs.temperature != null ? attrs.temperature : attrs.current_temperature;
  if (temp == null || !Number.isFinite(Number(temp))) return null;
  return {
    text: String(Math.round(Number(temp) * 10) / 10) + '°',
    background: on ? (HVAC_COLORS[state.state] || 'var(--accent-cyan)') : '#ffffff',
    color: on ? '#ffffff' : '#1d1d1f',
  };
}

function valueTextFor(domain, state) {
  if (!state) return '';
  const attrs = state.attributes || {};
  if (domain === 'climate') return state.state !== 'off' && attrs.temperature != null ? attrs.temperature + '°' : '';
  if (domain === 'sensor') {
    const unit = attrs.unit_of_measurement || '';
    // Degrees read better tight against the number; every other unit
    // (%, ppm, hPa, W) wants the space.
    return state.state + (unit.startsWith('°') ? unit : (unit ? ' ' + unit : ''));
  }
  if (domain === 'binary_sensor') return state.state === 'on' ? '偵測到' : '正常';
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

function tileEl(tile, form, preview) {
  const state = STATES[tile.entity];
  const domain = tile.domain;
  const meta = domainMeta(domain);
  const ok = !!state;
  const on = ok && !meta.momentary && isOnState(domain, state);

  const div = document.createElement('div');
  div.className = 'tile' + (on ? ' is-on' : '') + (meta.readonly ? ' is-readonly' : '')
    + ((form || (WINDOW_ROLE === 'grid' ? tileForm : 'small')) !== 'small'
      ? ' is-' + (form || tileForm) : '');
  div.dataset.id = tile.id;

  const iconWrap = document.createElement('div');
  iconWrap.className = 'tile-icon';
  const badge = domain === 'climate' && ok && !tile.icon ? climateBadge(state, on) : null;
  if (badge) {
    iconWrap.classList.add('is-badge');
    iconWrap.textContent = badge.text;
    iconWrap.style.background = badge.background;
    iconWrap.style.color = badge.color;
  } else {
    iconWrap.innerHTML = svgIcon(iconNameFor(tile, state));
    iconWrap.style.color = ok ? iconColorFor(domain, state, on) : 'var(--text-off-1)';
  }
  div.appendChild(iconWrap);

  // A long tile keeps its text in a column beside the icon disc.
  const isBar = div.classList.contains('is-bar');
  const body = isBar ? document.createElement('div') : div;
  if (isBar) { body.className = 'tile-text'; div.appendChild(body); }

  // On a long tile the disc takes the icon's colour and the icon is white.
  if (isBar && on && !badge) {
    iconWrap.style.background = iconWrap.style.color;
    iconWrap.style.color = '#fff';
  }

  const valueText = ok && !badge ? valueTextFor(domain, state) : '';
  if (valueText) {
    const v = document.createElement('div');
    v.className = 'tile-value';
    v.textContent = valueText;
    body.appendChild(v);
  }

  const room = document.createElement('div');
  room.className = 'tile-room';
  room.textContent = tile.room || friendlyName(state) || tile.entity;
  body.appendChild(room);

  // A read-only tile with a reading needs no second line repeating it.
  if (!meta.readonly || !valueText) {
    const label = document.createElement('div');
    label.className = 'tile-label';
    label.textContent = ok ? (tile.label || defaultLabel(domain, state)) : '無法連線';
    body.appendChild(label);
  }

  if (!ok) {
    const warn = document.createElement('div');
    warn.className = 'conn-warn';
    div.appendChild(warn);
  }

  if (domain === 'climate' && on) addClimateMiniButtons(div, tile);

  if (!preview) attachTileInteraction(div, tile);
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

  // Read-only accessories still open the detail card, where the name and
  // icon are edited.
  if (meta.readonly) {
    el.addEventListener('contextmenu', (e) => { e.preventDefault(); requestPopover(tile); });
    let holdTimer = null;
    const stop = () => { el.classList.remove('is-pressing'); clearTimeout(holdTimer); holdTimer = null; };
    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      el.classList.add('is-pressing');
      holdTimer = setTimeout(() => { stop(); requestPopover(tile); }, 420);
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach((n) => el.addEventListener(n, stop));
    return;
  }

  if (!meta.expand) {
    el.addEventListener('click', (e) => {
      if (e.target.closest('.mini-btn')) return;
      quickAction(tile);
    });
    el.addEventListener('contextmenu', (e) => { e.preventDefault(); requestPopover(tile); });
    return;
  }

  // Tap toggles, long press opens the detail card. Pointer events fire for
  // any button, so only the primary one is handled here.
  let timer = null, startX = 0, startY = 0, fired = false, primaryDown = false;
  const cancel = () => { el.classList.remove('is-pressing'); if (timer) { clearTimeout(timer); timer = null; } };

  el.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('.mini-btn')) return;
    primaryDown = true;
    startX = e.clientX; startY = e.clientY; fired = false;
    el.classList.add('is-pressing');
    timer = setTimeout(() => { fired = true; el.classList.remove('is-pressing'); requestPopover(tile); }, 420);
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

  el.addEventListener('contextmenu', (e) => { e.preventDefault(); requestPopover(tile); });
}

// The detail card lives in the popover window: ask Python to show it over
// this tile's screen position (it then calls __showPopoverForTile there).
function requestPopover(tile) {
  const tileNode = document.querySelector('.tile[data-id="' + tile.id + '"]');
  if (!tileNode || !(window.pywebview && window.pywebview.api)) return;
  const dpr = window.devicePixelRatio || 1;
  const r = tileNode.getBoundingClientRect();
  window.pywebview.api.get_window_pos(WINDOW_KIND).then((pos) => {
    const screenX = Math.round((pos && pos.x || 0) + r.left * dpr);
    const screenY = Math.round((pos && pos.y || 0) + r.top * dpr);
    // The tile's size lets the popover flip to its far edge near a screen edge.
    return window.pywebview.api.open_popover(
      tile.id, screenX, screenY, Math.round(r.width * dpr), Math.round(r.height * dpr),
      WINDOW_KIND,
    );
  }).catch(() => {});
}

/* ============================================================
 * Fading out while nobody is there
 * ============================================================ */
// Python decides when (see _watch_for_idle). The first click on a dimmed
// widget only wakes it.
let dimmed = false;

window.__setDimmed = function (on) {
  const next = !!on;
  if (next === dimmed) return;
  dimmed = next;
  wakeRequested = false;
  document.documentElement.classList.toggle('is-dimmed', dimmed);
};

// Waking is decided in one place: this asks Python, which wakes every widget
// in the same breath (including this one), so they come back together. The
// backdrop never stopped, so there is nothing to restart.
let wakeRequested = false;
function wakeFromDim() {
  if (!dimmed) return false;
  if (!wakeRequested && window.pywebview && window.pywebview.api) {
    wakeRequested = true;
    window.pywebview.api.wake().catch(() => {});
    // Should Python never answer, wake this one on its own.
    setTimeout(() => { if (wakeRequested) window.__setDimmed(false); }, 600);
  }
  return true;
}

// Capture phase, so the waking click never reaches a tile.
document.addEventListener('mousedown', (e) => {
  if (wakeFromDim()) { e.stopPropagation(); e.preventDefault(); }
}, true);
document.addEventListener('mousemove', () => { wakeFromDim(); }, true);

// The card and its frosted pane animate as one.
function flyoutLayers() {
  return [document.getElementById('view-grid'),
          document.getElementById('backdrop-glass')].filter(Boolean);
}

// Called by Python while the window is hidden but already in place: reset
// the entrance and capture the backdrop there, then report back through
// backdrop_armed (see _arm_backdrop in main.py).
window.__armBackdrop = function () {
  for (const el of flyoutLayers()) el.classList.remove('flyout-enter', 'flyout-leave');
  const done = () => {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.backdrop_armed().catch(() => {});
    }
  };
  // Wait out any capture already in flight: it is of the old place.
  const attempt = (tries) => {
    if (backdropPending && tries > 0) {
      setTimeout(() => attempt(tries - 1), 16);
      return;
    }
    invalidateBackdrop();
    Promise.resolve(refreshBackdrop()).then(done, done);
  };
  // Size the window to the new content first, and wait for that to land.
  lastRequestedSize = '';
  syncWindowSize();
  requestAnimationFrame(() => pendingResize.then(() => attempt(12), () => attempt(12)));
};

// Tray panel state. While it animates in or out nothing is captured: the
// capture shares a process with the compositor running the animation.
let flyoutOpen = false;
let flyoutAnimating = false;

window.__flyoutEnter = function () {
  flyoutOpen = true;
  flyoutAnimating = true;
  const view = document.getElementById('view-grid');
  const settled = () => {
    if (!flyoutAnimating) return;
    flyoutAnimating = false;
    restartBackdropTicker();
  };
  if (view) view.addEventListener('animationend', settled, { once: true });
  setTimeout(settled, 500);       // in case the animation never reports
  restartBackdropTicker();
  for (const el of flyoutLayers()) {
    el.classList.remove('flyout-enter', 'flyout-leave');
    void el.offsetWidth;
    el.classList.add('flyout-enter');
  }
};

// Python waits out this animation before hiding the window (hide_flyout).
window.__flyoutLeave = function () {
  flyoutOpen = false;
  flyoutAnimating = true;
  leaveStream(true);
  for (const el of flyoutLayers()) {
    el.classList.remove('flyout-enter');
    void el.offsetWidth;
    el.classList.add('flyout-leave');
  }
};

// The card rendered while hidden; replay its entrance once visible.
window.__popoverEnter = function () {
  const popover = document.getElementById('detail-popover');
  if (!popover) return;
  popover.classList.remove('show');
  void popover.offsetWidth;
  popover.classList.add('show');
  restartBackdropTicker();
};

// See Api.open_popover in main.py.
window.__showPopoverForTile = function (tileId) {
  const tile = findTile(tileId);
  if (tile) openDetail(tile);
};

function renderGrid() {
  const grid = document.getElementById('tiles');
  const emptyHint = document.getElementById('empty-hint');
  grid.innerHTML = '';
  entityToTileIds = {};
  const tiles = CONFIG.tiles || [];
  if (WINDOW_ROLE === 'grid') {
    layoutWidget(tiles.length);
  } else {
    // The panel and Settings fit their tiles: four across at most.
    const cols = Math.max(1, Math.min(4, tiles.length || 1));
    document.documentElement.style.setProperty('--cols', cols);
  }
  if (!tiles.length) {
    grid.hidden = true;
    emptyHint.hidden = IS_FLYOUT_WINDOW;
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
 * Detail popover (only ever rendered in the popover window)
 * ============================================================ */
let popoverCloseTimer = null;

function openDetail(tile) {
  if (!IS_POPOVER_WINDOW) return;
  const popover = document.getElementById('detail-popover');
  const backdrop = document.getElementById('detail-backdrop');
  if (popoverCloseTimer) { clearTimeout(popoverCloseTimer); popoverCloseTimer = null; }

  currentDetailTileId = tile.id;
  showEditMode(false);
  renderDetailBody();

  // The card is in the flow here, so the window takes its size.
  backdrop.hidden = false;
  popover.hidden = false;
  requestAnimationFrame(() => popover.classList.add('show'));
  syncWindowSize();
  // Python arms a correctly placed backdrop before showing the window;
  // stop the ticker so an older sample cannot race it.
  stopBackdropTicker();
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_popover_activatable(true).catch(() => {});
  }
}

function closeDetail() {
  if (!IS_POPOVER_WINDOW || !currentDetailTileId) return;
  currentDetailTileId = null;
  const popover = document.getElementById('detail-popover');
  const backdrop = document.getElementById('detail-backdrop');
  popover.classList.remove('show');
  backdrop.hidden = true;
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_popover_activatable(false).catch(() => {});
  }
  popoverCloseTimer = setTimeout(() => {
    popoverCloseTimer = null;
    if (currentDetailTileId) return; // reopened before the fade finished
    popover.hidden = true;
    if (window.pywebview && window.pywebview.api) window.pywebview.api.close_popover().catch(() => {});
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
  const builder = DETAIL_BUILDERS[tile.domain] || buildReadoutDetail;
  builder(body, tile, state);
}

/* ---- per-tile edit sub-panel (icon / name / category) ---- */
const ICON_CHOICES = [
  'light', 'switch', 'mdi:air-conditioner', 'fan', 'mdi:blinds', 'mdi:curtains', 'media', 'monitor',
  'lock', 'door', 'mdi:robot-vacuum', 'mdi:palette', 'script', 'mdi:robot',
  'thermometer', 'humidity', 'sensor',
];
const ICON_LABELS = {
  light: '燈', switch: '插座', fan: '風扇', media: '音樂', monitor: '螢幕',
  lock: '門鎖', door: '門', script: '腳本', thermometer: '溫度',
  humidity: '濕度', sensor: '感測器',
  'mdi:air-conditioner': '冷氣', 'mdi:blinds': '百葉窗',
  'mdi:curtains': '窗簾', 'mdi:robot-vacuum': '掃地機',
  'mdi:palette': '場景', 'mdi:robot': '自動化',
};

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
  document.getElementById('edit-mdi-input').value = tile.icon && tile.icon.startsWith('mdi:') ? tile.icon : '';
  renderIconPicker(tile);
}

function renderIconPicker(tile) {
  const wrap = document.getElementById('icon-picker');
  wrap.innerHTML = '';
  const current = tile.icon || domainMeta(tile.domain).icon;
  for (const name of ICON_CHOICES) {
    const b = document.createElement('button');
    b.className = 'icon-swatch' + (name === current ? ' active' : '');
    b.title = ICON_LABELS[name] || name;
    b.setAttribute('aria-label', b.title);
    b.innerHTML = svgIcon(name);
    b.addEventListener('click', async () => {
      tile.icon = name;
      document.getElementById('edit-mdi-input').value = name.startsWith('mdi:') ? name : '';
      renderIconPicker(tile);
      await persistTiles();
    });
    wrap.appendChild(b);
  }
}

// The large glance-and-toggle tile. fillPct (0-100) is how much of it
// fills with colour when on, e.g. a light's brightness.
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
// A two-state tile for switches and locks: a slab that rides from the
// bottom half to the top half, turning white, when on.
function toggleSlabTile(iconName, on, onClick) {
  const tile = document.createElement('button');
  tile.className = 'accessory-tile toggle-slab' + (on ? ' is-on' : '');
  const slab = document.createElement('div');
  slab.className = 'slab';
  slab.innerHTML = svgIcon(iconName);
  tile.appendChild(slab);
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
function rgbHex(rgb) {
  if (!Array.isArray(rgb) || rgb.length < 3) return '#ffffff';
  return '#' + rgb.slice(0, 3).map(v => Math.max(0, Math.min(255, Number(v) || 0))
    .toString(16).padStart(2, '0')).join('');
}
function colorPicker(currentRgb, onPick) {
  const wrap = document.createElement('label'); wrap.className = 'color-picker-row';
  const label = document.createElement('span'); label.textContent = '顏色';
  const input = document.createElement('input'); input.type = 'color';
  input.value = rgbHex(currentRgb);
  input.addEventListener('change', () => {
    const hex = input.value;
    onPick([1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16)));
  });
  wrap.appendChild(label); wrap.appendChild(input);
  return wrap;
}
function mediaBtn(iconPath, onClick, big) {
  const b = document.createElement('button'); b.className = 'icon-btn' + (big ? ' play-btn' : '');
  b.innerHTML = '<svg viewBox="0 0 24 24">' + iconPath + '</svg>';
  b.addEventListener('click', onClick);
  return b;
}

// Detail for accessories without controls: the reading, large, plus a
// history chart when it is numeric.
function buildReadoutDetail(body, tile, state) {
  const wrap = document.createElement('div');
  wrap.className = 'detail-readout';
  const big = document.createElement('div');
  big.className = 'detail-readout-value';
  big.textContent = state ? (valueTextFor(tile.domain, state) || state.state) : '無法連線';
  wrap.appendChild(big);
  const sub = document.createElement('div');
  sub.className = 'detail-readout-sub';
  sub.textContent = tile.entity;
  wrap.appendChild(sub);
  body.appendChild(wrap);
  if (state && !Number.isNaN(Number(state.state))) addHistoryChart(body, tile);
}

// --- history ---------------------------------------------------------------
const HISTORY_HOURS = 24;
const CHART_W = 248;      // the detail card's body width, in its own px
const CHART_H = 64;

function addHistoryChart(body, tile) {
  const block = document.createElement('div');
  block.className = 'history-block';
  const head = document.createElement('div');
  head.className = 'history-head';
  head.innerHTML = '<span>過去 ' + HISTORY_HOURS + ' 小時</span><span class="history-range"></span>';
  block.appendChild(head);
  const holder = document.createElement('div');
  holder.className = 'history-chart';
  holder.textContent = '載入中…';
  block.appendChild(holder);
  body.appendChild(block);
  if (!(window.pywebview && window.pywebview.api)) return;
  window.pywebview.api.get_history(tile.entity, HISTORY_HOURS).then((res) => {
    if (!res || !res.ok || !res.points || res.points.length < 2) {
      holder.textContent = '沒有紀錄';
      return;
    }
    holder.innerHTML = historySvg(res.points);
    const lo = Math.min.apply(null, res.points.map((p) => p[1]));
    const hi = Math.max.apply(null, res.points.map((p) => p[1]));
    head.querySelector('.history-range').textContent =
      trimNumber(lo) + ' – ' + trimNumber(hi);
    syncWindowSize();
  }).catch(() => { holder.textContent = '讀不到紀錄'; });
}

function trimNumber(n) {
  return String(Math.round(n * 10) / 10);
}

function historySvg(points) {
  const t0 = points[0][0];
  const t1 = points[points.length - 1][0] || (t0 + 1);
  const span = Math.max(1, t1 - t0);
  let lo = Math.min.apply(null, points.map((p) => p[1]));
  let hi = Math.max.apply(null, points.map((p) => p[1]));
  if (hi - lo < 0.5) {          // a flat line deserves to look flat
    const mid = (hi + lo) / 2;
    lo = mid - 0.5;
    hi = mid + 0.5;
  }
  const pad = 3;
  const x = (t) => ((t - t0) / span) * CHART_W;
  const y = (v) => pad + (1 - (v - lo) / (hi - lo)) * (CHART_H - pad * 2);
  const line = points.map((p, i) => (i ? 'L' : 'M') + x(p[0]).toFixed(1) + ' ' + y(p[1]).toFixed(1)).join(' ');
  const area = line + ' L' + CHART_W + ' ' + CHART_H + ' L0 ' + CHART_H + ' Z';
  const last = points[points.length - 1];
  return '<svg viewBox="0 0 ' + CHART_W + ' ' + CHART_H + '" preserveAspectRatio="none" class="history-svg">'
    + '<path class="history-area" d="' + area + '"/>'
    + '<path class="history-line" d="' + line + '"/>'
    + '</svg>'
    // The dot's layer has no viewBox, so it is positioned in percentages
    // of the box (matching the stretched line) and stays circular.
    + '<svg class="history-dot-layer">'
    + '<circle class="history-dot"'
    + ' cx="' + (x(last[0]) / CHART_W * 100).toFixed(2) + '%"'
    + ' cy="' + (y(last[1]) / CHART_H * 100).toFixed(2) + '%" r="2.5"/>'
    + '</svg>';
}

function toggleDetail(domain) {
  return (body, tile, state) => {
    const on = !!state && state.state === 'on';
    body.appendChild(toggleSlabTile(iconNameFor(tile, state), on, () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService(domain, 'toggle', tile.entity);
    }));
  };
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
    const modes = Array.isArray(attrs.supported_color_modes) ? attrs.supported_color_modes : [];
    if (modes.includes('color_temp')) {
      const min = Number(attrs.min_color_temp_kelvin), max = Number(attrs.max_color_temp_kelvin);
      if (Number.isFinite(min) && Number.isFinite(max) && min > 0 && max > min) {
        const current = Number(attrs.color_temp_kelvin);
        const val = Number.isFinite(current) && current >= min && current <= max ? current : Math.round((min + max) / 2);
        body.appendChild(sliderBlock('色溫', val, min, max, 'K', (v) => callService('light', 'turn_on', tile.entity, { color_temp_kelvin: Number(v) }), 1));
      }
    }
    if (modes.some(mode => ['hs', 'rgb', 'rgbw', 'rgbww', 'xy'].includes(mode))) {
      body.appendChild(colorPicker(attrs.rgb_color, (rgb) => callService('light', 'turn_on', tile.entity, { rgb_color: rgb })));
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
  switch: toggleDetail('switch'),
  input_boolean: toggleDetail('input_boolean'),
  lock(body, tile, state) {
    // Up and white means unlocked, matching "on" everywhere else.
    const open = !!state && state.state !== 'locked';
    body.appendChild(toggleSlabTile(iconNameFor(tile, state), open, () => {
      optimisticSet(tile.entity, { state: open ? 'locked' : 'unlocked' });
      callService('lock', open ? 'lock' : 'unlock', tile.entity);
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

// Outside the Settings window, ask Python to bring that window up.
function openSettings() {
  if (!IS_SETTINGS_WINDOW) {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.open_settings_window().catch(() => {});
    }
    return;
  }
  return openSettingsView();
}

// See Api.open_settings_window in main.py.
window.__enterSettings = function () {
  if (IS_SETTINGS_WINDOW && !settingsBooted) return;       // boot opens it
  try { openSettingsView(); } catch (e) { /* ignore */ }
};

function openSettingsView() {
  SettingsSelect.close();
  document.getElementById('ha-url').value = CONFIG.ha_url || '';
  document.getElementById('ha-token').value = CONFIG.ha_token || '';
  document.getElementById('theme-select').value = CONFIG.theme || 'auto';
  document.getElementById('language-select').value = CONFIG.language || 'zh-TW';
  document.getElementById('glass-style-select').value = CONFIG.glass_style || 'classic';
  setZoomSlider(CONFIG.zoom || 100);
  document.getElementById('dim-idle-check').checked = CONFIG.dim_when_idle !== false;
  setDimAfterSlider(CONFIG.dim_after_sec || 120);
  document.getElementById('dim-after-block').hidden = CONFIG.dim_when_idle === false;
  document.getElementById('lock-position-check').checked = !!CONFIG.lock_position;
  const glassSelect = document.getElementById('glass-mode-select');
  glassSelect.value = CONFIG.glass_mode || 'fast';
  // Native glass is only offered where it is supported.
  glassSelect.querySelector('option[value="system"]').hidden = CONFIG.system_glass_ok !== true;
  if (CONFIG.system_glass_ok !== true && glassSelect.value === 'system') glassSelect.value = 'fast';
  document.getElementById('panel-theme-select').value = CONFIG.panel_theme || 'follow';
  document.getElementById('start-on-boot-check').checked = !!CONFIG.start_on_boot;
  document.getElementById('test-conn-result').textContent = '';
  renderTileList();
  updateConnDot();
  showView('view-settings');
  SettingsSelect.sync();
}

function dimAfterText(sec) {
  return sec < 60 ? (sec + ' 秒') : (Math.round(sec / 6) / 10 + ' 分鐘');
}

function setDimAfterSlider(sec) {
  const v = Math.max(10, Math.min(600, Number(sec) || 120));
  document.getElementById('dim-after-range').value = String(v);
  document.getElementById('dim-after-value').textContent = dimAfterText(v);
}

function setZoomSlider(pct) {
  const v = Math.max(50, Math.min(200, Number(pct) || 100));
  document.getElementById('zoom-range').value = String(v);
  document.getElementById('zoom-value').textContent = v + '%';
}

async function saveHaConfig(url, token) {
  CONFIG.ha_url = url;
  CONFIG.ha_token = token;
  try { await window.pywebview.api.save_ha_config(url, token); } catch (e) { /* ignore */ }
}

// Only the changed keys, so no window's stale copy overwrites another's edit.
async function savePref(changes) {
  Object.assign(CONFIG, changes);
  try {
    await window.pywebview.api.save_prefs(changes);
  } catch (e) { /* ignore */ }
}

async function closeSettingsAndSave() {
  const url = document.getElementById('ha-url').value.trim();
  const token = document.getElementById('ha-token').value.trim();
  if (url !== CONFIG.ha_url || token !== CONFIG.ha_token) await saveHaConfig(url, token);
  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.close_settings_window().catch(() => {});
  }
}

// ---- Widget editor -------------------------------------------------------
const WIDGET_SOFT_LIMIT = 6;
const PALETTE_SCALE = 0.19;
let editorLayout = null;
let editorTimer = 0;
let editorDragging = false;
let pickerReturn = 'view-settings';

function editorVisible() {
  const el = document.getElementById('view-editor');
  return !!el && !el.hidden;
}

function openEditor(widgetId) {
  if (widgetId) settingsWidgetId = widgetId;
  const w = settingsWidget();
  if (w) settingsWidgetId = w.id;
  resolveWindowTiles();
  showView('view-editor');
  renderEditor();
  refreshEditorLayout();
  clearInterval(editorTimer);
  editorTimer = setInterval(() => { if (!editorDragging) refreshEditorLayout(); }, 900);
}

function closeEditor() {
  clearInterval(editorTimer);
  showView('view-settings');
  renderTileList();
}

// Settings is made when asked for, so these can arrive before its page has
// booted; they are held until then.
let settingsBooted = false;
let pendingEditor = null;
window.__enterEditor = function (widgetId) {
  if (IS_SETTINGS_WINDOW && !settingsBooted) { pendingEditor = widgetId || ''; return; }
  openEditor(widgetId || '');
};

function renderEditor() {
  document.getElementById('editor-lock-check').checked = !!CONFIG.lock_position;
  renderEditorChips();
  renderPalette();
  renderEditorPreview();
  renderTileList();
  renderMinimap();
  syncWindowSize();
}

function renderEditorChips() {
  const widgets = CONFIG.widgets || [];
  const current = settingsWidget();
  const chips = document.getElementById('widget-chips');
  chips.innerHTML = '';
  widgets.forEach((w, i) => {
    const b = document.createElement('button');
    b.className = 'widget-chip' + (current && w.id === current.id ? ' is-active' : '');
    b.textContent = '#' + (i + 1) + ' · ' + w.size;
    b.addEventListener('click', () => selectEditorWidget(w.id));
    chips.appendChild(b);
  });
  const sizes = document.getElementById('widget-size-chips');
  sizes.innerHTML = '';
  for (const size of Object.keys(WIDGET_SIZES)) {
    const b = document.createElement('button');
    b.className = 'widget-chip' + (current && current.size === size ? ' is-active' : '');
    b.textContent = size;
    b.addEventListener('click', () => setWidgetSize(size));
    sizes.appendChild(b);
  }
  document.getElementById('remove-widget-btn').disabled = widgets.length <= 1;
  const hint = document.getElementById('widget-hint');
  hint.hidden = widgets.length <= WIDGET_SOFT_LIMIT;
  hint.textContent = '已超過 ' + WIDGET_SOFT_LIMIT
    + ' 個 Widget，每多一個都會多用一份記憶體 (約 60 MB)。';
}

function selectEditorWidget(id) {
  settingsWidgetId = id;
  resolveWindowTiles();
  renderEditor();
}

// The four sizes, drawn to scale. Pressing one makes a real widget that
// follows the pointer onto the desktop (Python carries it until release).
function renderPalette() {
  const host = document.getElementById('palette');
  if (host.dataset.ready) return;
  host.dataset.ready = '1';
  for (const size of Object.keys(WIDGET_SIZES)) {
    const g = widgetGeometry(size, 0);
    const item = document.createElement('div');
    item.className = 'palette-item';
    item.title = '拖曳到桌面';
    const box = document.createElement('div');
    box.className = 'palette-box';
    box.style.width = Math.round(g.width * PALETTE_SCALE) + 'px';
    box.style.height = Math.round(g.height * PALETTE_SCALE) + 'px';
    box.style.gridTemplateColumns = 'repeat(' + g.cols + ', 1fr)';
    box.style.gridTemplateRows = 'repeat(' + g.rows + ', 1fr)';
    for (let i = 0; i < g.cols * g.rows; i++) {
      const cell = document.createElement('div');
      cell.className = 'palette-cell';
      box.appendChild(cell);
    }
    const name = document.createElement('div');
    name.className = 'palette-name';
    name.textContent = size;
    item.appendChild(box);
    item.appendChild(name);
    item.addEventListener('pointerdown', async (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      editorDragging = true;
      try {
        const r = await window.pywebview.api.begin_widget_drag(size);
        if (r && r.id) settingsWidgetId = r.id;
      } catch (err) { showToast('新增 Widget 失敗'); }
      // Python lets go when the button comes up.
      setTimeout(() => { editorDragging = false; refreshEditorLayout(); }, 400);
    });
    host.appendChild(item);
  }
}

// The selected widget, laid out exactly as on the desktop. Tiles drag to
// reorder, and a cross removes one.
function renderEditorPreview() {
  const host = document.getElementById('editor-preview');
  host.innerHTML = '';
  const widget = settingsWidget();
  if (!widget) return;
  const geometry = widgetGeometry(widget.size, widget.tiles.length);
  const scope = document.createElement('div');
  applyWidgetGeometry(scope, geometry);
  const frame = document.createElement('div');
  frame.className = 'widget-frame';
  const card = document.createElement('div');
  card.className = 'card-bg';
  frame.appendChild(card);
  const grid = document.createElement('div');
  grid.className = 'tiles-grid';
  let dragIndex = -1;
  widget.tiles.forEach((tile, index) => {
    const el = tileEl(tile, geometry.form, true);
    el.draggable = true;
    const remove = document.createElement('button');
    remove.className = 'preview-remove';
    remove.textContent = '✕';
    remove.title = '移除';
    remove.addEventListener('click', (e) => { e.stopPropagation(); removeTileAt(index); });
    el.appendChild(remove);
    el.addEventListener('dragstart', (e) => {
      dragIndex = index;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(index));
      el.classList.add('dragging');
    });
    el.addEventListener('dragend', () => {
      el.classList.remove('dragging');
      for (const t of grid.children) t.classList.remove('drop-before', 'drop-after');
    });
    el.addEventListener('dragover', (e) => {
      if (dragIndex < 0) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const before = e.clientX < r.left + r.width / 2;
      el.classList.toggle('drop-before', before);
      el.classList.toggle('drop-after', !before);
    });
    el.addEventListener('dragleave', () => el.classList.remove('drop-before', 'drop-after'));
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const before = e.clientX < r.left + r.width / 2;
      let to = index + (before ? 0 : 1);
      const from = dragIndex;
      dragIndex = -1;
      if (from < 0) return;
      if (from < to) to -= 1;
      if (to === from) { renderEditorPreview(); return; }
      const [moved] = widget.tiles.splice(from, 1);
      widget.tiles.splice(to, 0, moved);
      persistTiles();
      renderEditor();
    });
    grid.appendChild(el);
  });
  frame.appendChild(grid);
  if (!widget.tiles.length) {
    const empty = document.createElement('div');
    empty.className = 'preview-empty';
    empty.textContent = '尚無配件，按下方「新增配件」';
    frame.appendChild(empty);
  }
  scope.appendChild(frame);
  host.appendChild(scope);
  // Fit the column; never larger than life.
  const room = Math.max(120, host.clientWidth - 36);
  scope.style.zoom = String(Math.min(1, room / geometry.width));
}

function removeTileAt(index) {
  const widget = settingsWidget();
  if (!widget) return;
  widget.tiles.splice(index, 1);
  persistTiles();
  renderEditor();
}

// ---- the desktop map ----
async function refreshEditorLayout() {
  if (!editorVisible()) { clearInterval(editorTimer); return; }
  try { editorLayout = await window.pywebview.api.get_layout(); } catch (e) { return; }
  renderMinimap();
}

function renderMinimap() {
  const host = document.getElementById('minimap');
  const layout = editorLayout;
  if (!host || !layout || !layout.monitors.length) return;
  const mons = layout.monitors;
  const minX = Math.min(...mons.map((m) => m.x)), minY = Math.min(...mons.map((m) => m.y));
  const maxX = Math.max(...mons.map((m) => m.x + m.w)), maxY = Math.max(...mons.map((m) => m.y + m.h));
  const pad = 8;
  const width = host.clientWidth || 300;
  const scale = Math.min((width - 2 * pad) / (maxX - minX), 210 / (maxY - minY));
  host.style.height = Math.round((maxY - minY) * scale + 2 * pad) + 'px';
  host.innerHTML = '';
  const at = (x, y) => [Math.round((x - minX) * scale + pad), Math.round((y - minY) * scale + pad)];
  for (const m of mons) {
    const el = document.createElement('div');
    el.className = 'mm-monitor';
    const [x, y] = at(m.x, m.y);
    el.style.cssText = `left:${x}px;top:${y}px;width:${Math.round(m.w * scale)}px;height:${Math.round(m.h * scale)}px`;
    host.appendChild(el);
  }
  const current = settingsWidget();
  (layout.widgets || []).forEach((w, i) => {
    const el = document.createElement('div');
    el.className = 'mm-widget' + (current && w.id === current.id ? ' selected' : '')
      + (w.visible ? '' : ' hidden-widget');
    const [x, y] = at(w.x, w.y);
    el.style.cssText = `left:${x}px;top:${y}px;width:${Math.max(14, Math.round(w.w * scale))}px;height:${Math.max(14, Math.round(w.h * scale))}px`;
    el.textContent = '#' + ((CONFIG.widgets || []).findIndex((c) => c.id === w.id) + 1);
    el.title = w.size;
    attachMapDrag(el, w, scale);
    host.appendChild(el);
  });
}

// Dragging a box moves the real widget (snapped by Python).
function attachMapDrag(el, widget, scale) {
  el.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    editorDragging = true;
    if (settingsWidgetId !== widget.id) { settingsWidgetId = widget.id; resolveWindowTiles(); renderEditorChips(); renderEditorPreview(); renderTileList(); }
    const startX = e.clientX, startY = e.clientY;
    const originLeft = parseFloat(el.style.left), originTop = parseFloat(el.style.top);
    // Where the widget was when the drag began: the reply moves `widget`,
    // so the target must not be measured from it.
    const baseX = widget.x, baseY = widget.y;
    let pending = false, moved = false;
    const move = (ev) => {
      moved = true;
      el.style.left = (originLeft + ev.clientX - startX) + 'px';
      el.style.top = (originTop + ev.clientY - startY) + 'px';
      if (pending) return;
      pending = true;
      requestAnimationFrame(async () => {
        pending = false;
        try {
          const r = await window.pywebview.api.move_widget(
            widget.id,
            Math.round(baseX + (ev.clientX - startX) / scale),
            Math.round(baseY + (ev.clientY - startY) / scale));
          // The snapped spot: the box follows the real widget.
          if (r) {
            el.style.left = Math.round(originLeft + (r.x - baseX) * scale) + 'px';
            el.style.top = Math.round(originTop + (r.y - baseY) * scale) + 'px';
          }
        } catch (err) { /* ignore */ }
      });
    };
    const up = () => {
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      editorDragging = false;
      refreshEditorLayout();
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
  });
}

async function setWidgetSize(size) {
  const w = settingsWidget();
  if (!w || w.size === size) return;
  try { await window.pywebview.api.set_widget_size(w.id, size); } catch (e) { /* ignore */ }
  const mine = (CONFIG.widgets || []).find((x) => x.id === w.id);
  if (mine) mine.size = size;
  renderEditor();
  setTimeout(refreshEditorLayout, 350);
}

async function removeWidget() {
  const w = settingsWidget();
  if (!w || (CONFIG.widgets || []).length <= 1) return;
  settingsWidgetId = '';
  try { await window.pywebview.api.remove_widget(w.id); } catch (e) { /* ignore */ }
  resolveWindowTiles();
  renderEditor();
  setTimeout(refreshEditorLayout, 200);
}

async function persistTiles() {
  try {
    await window.pywebview.api.save_widgets(CONFIG.widgets);
    if (CONFIG.panel && Array.isArray(CONFIG.panel.tiles)) {
      await window.pywebview.api.save_panel(CONFIG.panel);
    }
  } catch (e) { /* ignore */ }
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
  input.style.cssText = 'width:100%;font-size:12.5px;padding:2px 4px;border-radius:11px;border:1px solid var(--input-border);background:var(--input-bg);color:var(--text-on-1);';
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
  pickerReturn = editorVisible() ? 'view-editor' : 'view-settings';
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
  const widget = settingsWidget();
  if (widget) widget.tiles.push(tile);
  resolveWindowTiles();
  if (e.state && !STATES[e.entity_id]) STATES[e.entity_id] = e.state;
  await persistTiles();
  showView(pickerReturn);
  renderTileList();
  if (pickerReturn === 'view-editor') renderEditor();
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
  if (IS_SETTINGS_WINDOW) SettingsSelect.install();
  document.getElementById('empty-add-btn').addEventListener('click', openSettings);
  document.getElementById('add-tile-btn').addEventListener('click', openPicker);
  document.getElementById('remove-widget-btn').addEventListener('click', removeWidget);
  document.getElementById('open-editor-btn').addEventListener('click', () => openEditor(''));
  // Right-clicking a widget's own surface (not a tile, which opens its detail)
  // edits that widget.
  document.addEventListener('contextmenu', (e) => {
    if (WINDOW_ROLE !== 'grid' || e.target.closest('.tile')) return;
    e.preventDefault();
    window.pywebview.api.open_widget_editor(WIDGET_ID).catch(() => {});
  });
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
  document.getElementById('edit-mdi-input').addEventListener('change', async (e) => {
    const tile = findTile(currentDetailTileId);
    if (!tile) return;
    const value = e.target.value.trim().toLowerCase();
    if (value && (!/^mdi:[a-z0-9-]+$/.test(value) || !window.MDI_PATHS[value.slice(4)])) {
      showToast('找不到 MDI 圖示：' + value);
      e.target.value = tile.icon && tile.icon.startsWith('mdi:') ? tile.icon : '';
      return;
    }
    tile.icon = value;
    renderIconPicker(tile);
    await persistTiles();
  });
  document.getElementById('close-settings-btn').addEventListener('click', closeSettingsAndSave);
  document.getElementById('quit-btn').addEventListener('click', () => { window.pywebview.api.quit_app(); });
  document.getElementById('theme-select').addEventListener('change', async (e) => {
    await savePref({ theme: e.target.value });
    applyTheme();
  });
  document.getElementById('language-select').addEventListener('change', async (e) => {
    await savePref({ language: e.target.value });
    setInterfaceLanguage(e.target.value);
  });
  document.getElementById('glass-style-select').addEventListener('change', async (e) => {
    await savePref({ glass_style: e.target.value });
    applyTheme();
    invalidateBackdrop();
    refreshBackdropSoon(0);
  });
  // The same preference is offered in Settings and in the editor.
  for (const id of ['lock-position-check', 'editor-lock-check']) {
    document.getElementById(id).addEventListener('change', async (e) => {
      await savePref({ lock_position: !!e.target.checked });
      document.getElementById('lock-position-check').checked = !!CONFIG.lock_position;
      document.getElementById('editor-lock-check').checked = !!CONFIG.lock_position;
    });
  }
  document.getElementById('glass-mode-select').addEventListener('change', async (e) => {
    await savePref({ glass_mode: e.target.value });
    applySystemGlass();
    // The frame and its cost estimate belong to the old capture method.
    backdropHash = null;
    backdropFrameMs = BACKDROP_FLOOR_MS;
    backdropPaced = false;
    refreshBackdropSoon(0);
  });
  document.getElementById('panel-theme-select').addEventListener('change', async (e) => {
    await savePref({ panel_theme: e.target.value });
  });
  // Sliders update their label while dragging and save only on release.
  document.getElementById('dim-idle-check').addEventListener('change', async (e) => {
    const on = !!e.target.checked;
    document.getElementById('dim-after-block').hidden = !on;
    await savePref({ dim_when_idle: on });
  });
  const dimRange = document.getElementById('dim-after-range');
  dimRange.addEventListener('input', (e) => {
    document.getElementById('dim-after-value').textContent = dimAfterText(Number(e.target.value));
  });
  dimRange.addEventListener('change', async (e) => {
    await savePref({ dim_after_sec: Number(e.target.value) });
    setDimAfterSlider(CONFIG.dim_after_sec);
  });

  const zoomRange = document.getElementById('zoom-range');
  zoomRange.addEventListener('input', (e) => {
    document.getElementById('zoom-value').textContent = e.target.value + '%';
  });
  zoomRange.addEventListener('change', async (e) => {
    await savePref({ zoom: Number(e.target.value) });
    setZoomSlider(CONFIG.zoom);
    applyZoom();
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
    else if (action === 'close-picker') { showView(pickerReturn); renderTileList(); }
    else if (action === 'close-editor') closeEditor();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!document.getElementById('view-picker').hidden) { showView(pickerReturn); renderTileList(); }
    else if (editorVisible()) closeEditor();
    else if (IS_SETTINGS_WINDOW) closeSettingsAndSave();
    else if (currentDetailTileId) closeDetail();
  });

  installWindowDrag();
}

// Pushed from Python whenever preferences change (Api._push_prefs). Every
// window gets every change, including the one that made it, so compare
// before re-rendering anything under someone mid-edit.
window.__applyPrefs = function (cfg) {
  if (!cfg) return;
  const mine = (c) => (c.widgets || []).find((w) => w.id === WIDGET_ID);
  const tilesChanged = JSON.stringify(tilesFor(cfg)) !== JSON.stringify(CONFIG.tiles || []);
  // A widget's own size is part of its layout.
  const sizeChanged = WINDOW_ROLE === 'grid' &&
    (mine(cfg) || {}).size !== (mine(CONFIG) || {}).size;
  const widgetsChanged = IS_SETTINGS_WINDOW &&
    JSON.stringify((cfg.widgets || []).map((w) => [w.id, w.size, w.tiles.length])) !==
    JSON.stringify((CONFIG.widgets || []).map((w) => [w.id, w.size, w.tiles.length]));
  const editing = IS_SETTINGS_WINDOW && editorVisible();
  const languageChanged = cfg.language !== CONFIG.language;
  const themeChanged = cfg.theme !== CONFIG.theme || cfg.glass_style !== CONFIG.glass_style;
  const glassChanged = cfg.glass_mode !== CONFIG.glass_mode ||
    JSON.stringify(cfg.system_glass_active) !== JSON.stringify(CONFIG.system_glass_active);
  const panelThemeChanged = cfg.panel_theme !== CONFIG.panel_theme;
  const layoutChanged = cfg.zoom !== CONFIG.zoom || sizeChanged;
  CONFIG = Object.assign({}, CONFIG, cfg);
  resolveWindowTiles();
  if (languageChanged) setInterfaceLanguage(CONFIG.language);
  if (glassChanged) {
    applySystemGlass();
    backdropHash = null;
    refreshBackdropSoon(0);
  }
  if (panelThemeChanged || themeChanged) applyTheme();
  if (editing && (widgetsChanged || tilesChanged)) renderEditor();
  if (!tilesChanged && !themeChanged && !layoutChanged) return;
  if (themeChanged) invalidateBackdrop();
  if (layoutChanged) applyZoom();
  // The widget's cell counts live in renderGrid's --cols/--rows.
  if ((tilesChanged || layoutChanged) && !IS_POPOVER_WINDOW) renderGrid();
  if (tilesChanged && !document.getElementById('view-settings').hidden) renderTileList();
  if (currentDetailTileId) renderDetailBody();
  syncWindowSize();
  refreshBackdropSoon();
};

init();
window.addEventListener('pywebviewready', boot);
