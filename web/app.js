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
  // Same body, shackle swung clear of it - a lock that is open should look
  // open, not just be a different colour.
  // The keyhole is cut out of the body with evenodd rather than painted
  // over it in the tile's colour: the tile is glass now, so painting it
  // back would leave a translucent smudge instead of a hole.
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

// A tile's icon is normally fixed by its domain (or overridden by hand),
// but a lock's whole job is to show which way it is, so it gets a second
// glyph rather than just a second colour. A hand-picked icon always wins.
function iconNameFor(tile, state) {
  if (tile.icon) return tile.icon;
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

// --- climate: the icon *is* the reading -------------------------------------
// A thermostat's one interesting number is the temperature it is set to,
// so the icon slot shows it directly instead of a glyph that says
// "this is an air conditioner" next to the same number written again.
const HVAC_COLORS = {
  cool: '#3fa9f5',
  heat: '#ff7a45',
  heat_cool: '#34c759',
  auto: '#34c759',
  dry: '#f0b429',
  fan_only: '#8e9aaf',
};

function climateBadge(state, on) {
  const attrs = (state && state.attributes) || {};
  const temp = attrs.temperature != null ? attrs.temperature : attrs.current_temperature;
  if (temp == null) return null;
  return {
    text: String(Math.round(Number(temp) * 10) / 10) + '°',
    // Off is a plain white chip with dark text - it reads as "not doing
    // anything". Running, it takes the colour of what it is doing.
    background: on ? (HVAC_COLORS[state.state] || 'var(--accent-cyan)') : '#ffffff',
    color: on ? '#ffffff' : '#1d1d1f',
  };
}

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

// This one page runs in three separate OS windows - the grid widget, the
// detail popover, and Settings - told apart only by the fragment the
// window was opened with (#popover, #settings, or nothing). pywebview
// strips the fragment when working out where to serve from, and it never
// reaches the server, so all three are the same request for index.html.
//
// Separate windows rather than views swapped inside one: a window is
// always a rectangle, so a popover floating beside a grid it doesn't
// align with left real dead space that the grid still owned, and Settings
// swapped in resized the grid out from under whatever was on screen.
// Apart from that each window wants different behaviour - the grid never
// takes focus, Settings must, and Settings ignores the widget's zoom.
const WINDOW_ROLE = (location.hash || '').replace('#', '') || 'grid';
const IS_POPOVER_WINDOW = WINDOW_ROLE === 'popover';
const IS_FLYOUT_WINDOW = WINDOW_ROLE === 'flyout';
// What Python calls this window. Same page, four windows; every call that
// has to act on "this one" carries it.
const WINDOW_KIND = WINDOW_ROLE === 'grid' ? 'main' : WINDOW_ROLE;
const IS_SETTINGS_WINDOW = WINDOW_ROLE === 'settings';

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
  // This window still runs the full shared bootstrap (same config file,
  // same tile list) so findTile()/CONFIG/STATES all work normally once
  // __showPopoverForTile asks it to render a tile's detail - but the grid
  // section itself is never actually shown here (see IS_POPOVER_WINDOW).
  // Each window owns one of the views; the others stay hidden for the
  // life of that window. The markup for all of them is present in every
  // window because they all load the same page.
  if (IS_FLYOUT_WINDOW) {
    // Same grid as the desktop widget, in a window that behaves like a
    // taskbar panel - see the flyout rules in style.css.
    document.documentElement.classList.add('is-flyout-window');
  }
  if (IS_POPOVER_WINDOW) {
    document.getElementById('view-grid').hidden = true;
    // Lets the card lay itself out in the flow here, so #stage takes the
    // card's own size and the window follows it - see openDetail.
    document.documentElement.classList.add('is-popover-window');
  } else if (IS_SETTINGS_WINDOW) {
    openSettingsView();
  }
  updateConnDot();
  try { await window.pywebview.api.ui_ready(); } catch (e) { /* ignore */ }
  startBackdropTicker();

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

  // First run, from the grid window only - the other two are opened on
  // demand and would otherwise each try to raise Settings as well.
  if (WINDOW_ROLE === 'grid' && !CONFIG.ha_token && (!CONFIG.tiles || !CONFIG.tiles.length)) {
    setTimeout(openSettings, 150);
  }
}

function applyTheme() {
  document.documentElement.setAttribute('data-theme', CONFIG.theme || 'auto');
}

/* ============================================================
 * View switching + auto window sizing
 * ============================================================ */
// Only ever swaps between the two views that share the Settings window;
// the grid window shows the grid and nothing else.
function showView(name) {
  for (const id of ['view-grid', 'view-settings', 'view-picker']) {
    document.getElementById(id).hidden = id !== name;
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

// The tray panel's own scale, deliberately not the widget's. The zoom
// setting is about how big the widget should look sitting on the desktop,
// which has nothing to do with how big a panel hanging off the taskbar
// should be - and the panel wants to be compact, like the ones Windows
// puts there.
const FLYOUT_ZOOM = 0.5;

function applyZoom() {
  // Settings is never scaled. The zoom setting is there to size the
  // *widget* against the desktop; applying it here too meant that turning
  // the widget down to 50% left the controls for turning it back up half
  // size as well.
  const z = IS_SETTINGS_WINDOW
    ? 1
    : IS_FLYOUT_WINDOW
      ? FLYOUT_ZOOM
      : Math.max(50, Math.min(200, Number(CONFIG.zoom) || 100)) / 100;
  document.documentElement.style.zoom = String(z);
  currentZoom = z;
}
// The page's own scale, kept here because paintBackdrop has to convert CSS
// lengths that `zoom` does not touch (a computed border-radius) into the
// canvas's device pixels.
let currentZoom = 1;

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
      // The window hugs the stage exactly, with no margin: the card is
      // anchored at the window's top-left, which is what lets the saved
      // window position *be* the card's on-screen position and lets
      // requestPopover() turn a tile's client rect straight into screen
      // coordinates. The cost is that .card-bg's box-shadow, which bleeds
      // outside the card, gets cut off at the window edge.
      cssW = rect.width;
      cssH = rect.height;
    }
    resizeSeq += 1;

    const physW = Math.ceil(cssW * dpr), physH = Math.ceil(cssH * dpr);
    const resize = IS_POPOVER_WINDOW ? window.pywebview.api.resize_popover_window
      : IS_SETTINGS_WINDOW ? window.pywebview.api.resize_settings_window
      : IS_FLYOUT_WINDOW ? window.pywebview.api.resize_flyout_window
      : window.pywebview.api.resize_window;
    const done = resize(physW, physH, resizeSeq);
    // The backdrop is captured at the window's size, so it is wrong the
    // moment the window changes size - re-take it once the resize lands.
    Promise.resolve(done).then(() => refreshBackdropSoon()).catch(() => {});
  });
}
new ResizeObserver(syncWindowSize).observe(document.getElementById('stage'));

/* ============================================================
 * Frosted backdrop
 * ============================================================ */
// The window cannot be translucent (see the note in main.py), so the
// frosted look is built the other way round: Python hands over a picture
// of the desktop from directly behind this window, the page paints it
// full-bleed, and .card-bg blurs it with backdrop-filter. Outside the
// card it stays unblurred, which is what makes the rounded corners read
// as a cutout rather than as a shape drawn on top of something.
//
// It has to be re-taken whenever the window moves or resizes, and on a
// slow tick as well, because an animated wallpaper keeps changing under a
// window that has not moved at all.
// This runs as fast as it can while the picture keeps changing - enough
// to follow an animated wallpaper - and backs off hard once it stops.
//
// The rate is set from what a frame actually costs rather than fixed,
// because "as fast as possible" on a background widget is the wrong
// answer: BACKDROP_DUTY is how much of one core the capture is allowed,
// so a frame that takes 13ms is followed by ~100ms of quiet, and a slower
// machine thins itself out instead of pinning a core. A blurred backdrop
// hides a low frame rate well, so this is a cheap trade.
const BACKDROP_DUTY = 4;              // wait this many times the capture cost
const BACKDROP_MIN_MS = 60;           // ...but never busier than this
const BACKDROP_IDLE_MS = 3000;        // once the picture stops changing
const BACKDROP_STILL_BEFORE_IDLE = 8;
let backdropPending = false;
let backdropTimer = null;
let backdropHash = null;
let backdropStill = 0;
// Set from Python's answer when there is nothing worth capturing (window
// hidden, or completely covered); it replaces the pacing below for as
// long as that lasts - see refreshBackdrop.
let backdropSkipMs = 0;
let backdropFrameMs = BACKDROP_MIN_MS;

// The interval is derived from what a capture costs, so a single slow
// frame must not be allowed to set the pace: capture time spikes whenever
// this window happens to be repainting at the same moment, and taking the
// last frame at face value let those spikes roughly halve the frame rate
// and leave it there. Track the floor instead - drop to a cheaper reading
// immediately, drift up to an expensive one slowly.
function noteFrameCost(ms) {
  if (!(ms > 0)) return;
  backdropFrameMs = ms < backdropFrameMs ? ms : backdropFrameMs * 0.9 + ms * 0.1;
}

// One canvas holds everything behind the page's own content: the desktop
// as captured, and the blurred copy of it inside each card. Drawing both
// in one go is atomic - nothing is ever half-updated on screen - which is
// what the old pair of cross-fading layers existed to fake.
let backdropCtx = null;
let glassCtx = null;

// Where the visible card sits, in the canvas's device pixels, plus its
// corner radius. Everything the backdrop does is expressed against this:
// the blurred copy is clipped to it, and the sharp copy is only needed
// where it does not reach - the four wedges outside its rounded corners.
// `fills` says the card is the window, give or take the pixel or two by
// which the two roundings disagree (the window is sized from the card's
// measured box, and WebView2's viewport does not always land on the same
// device pixel). When it does, the box is snapped out to the canvas so
// that the clip's rounded corners sit exactly where the sharp corner
// wedges are drawn. When it does not - fixed-size mode can leave a real
// margin - the whole frame has to come back sharp.
const CARD_SNAP_PX = 4;

function cardGeometry() {
  const cv = document.getElementById('backdrop');
  if (!cv) return null;
  const dpr = window.devicePixelRatio || 1;
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
    return box;
  }
  return null;
}

function paintBackdrop(sharp, blurred, w, h, corner) {
  const cv = document.getElementById('backdrop');
  const glass = document.getElementById('backdrop-glass');
  if (!cv) return;
  if (!backdropCtx) backdropCtx = cv.getContext('2d', { alpha: false });
  const ctx = backdropCtx;
  if (cv.width !== w || cv.height !== h) {
    // Resizing clears the bitmap to black; the fill and the draw below
    // happen in this same task, so that black is never painted.
    cv.width = w;
    cv.height = h;
  }
  if (corner) {
    // The sharp copy arrived as the four corner wedges packed into one
    // square (see get_desktop_backdrop); put each back where it came
    // from. Everything between them is about to be covered by the card.
    const c = corner;
    ctx.drawImage(sharp, 0, 0, c, c, 0, 0, c, c);
    ctx.drawImage(sharp, c, 0, c, c, w - c, 0, c, c);
    ctx.drawImage(sharp, 0, c, c, c, 0, h - c, c, c);
    ctx.drawImage(sharp, c, c, c, c, w - c, h - c, c, c);
  } else {
    ctx.drawImage(sharp, 0, 0, w, h);
  }
  if (!glass) return;
  // The card's frosted fill, on its own layer above that: it belongs to
  // the card and has to be able to come and go with it. Clipped to the
  // card's own rounded rectangle here rather than set as its CSS
  // background, so the frame never becomes an image resource of its own.
  if (!glassCtx) glassCtx = glass.getContext('2d');
  const gctx = glassCtx;
  if (glass.width !== w || glass.height !== h) {
    glass.width = w;
    glass.height = h;
  } else {
    gctx.clearRect(0, 0, w, h);
  }
  const card = blurred ? cardGeometry() : null;
  if (!card) return;
  gctx.save();
  gctx.beginPath();
  gctx.roundRect(card.x, card.y, card.w, card.h, card.radius);
  gctx.clip();
  gctx.drawImage(blurred, 0, 0, w, h);
  gctx.restore();
}

// Decoded off the main thread, drawn, then closed - the bitmap's lifetime
// is exactly this frame. Going through an <img> and a CSS background left
// every frame in Chromium's decoded-image cache instead.
function decodeShot(url) {
  return fetch(url).then((r) => r.blob()).then(createImageBitmap);
}

function refreshBackdrop() {
  if (backdropPending || !(window.pywebview && window.pywebview.api)) return Promise.resolve();
  backdropPending = true;
  const startedAt = performance.now();
  // Ask for exactly the number of device pixels this will be drawn at, so
  // the image lands 1:1 and is never resampled (see get_desktop_backdrop).
  const box = document.getElementById('backdrop').getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  // Only the wedges outside the card's corners are ever seen sharp, so
  // that is all that has to come back at full size - as long as the card
  // really does cover the window.
  const card = cardGeometry();
  const corner = (card && card.fills) ? Math.ceil(card.radius) : 0;
  return window.pywebview.api
    .get_desktop_backdrop(WINDOW_KIND, backdropHash,
                          Math.round(box.width * dpr), Math.round(box.height * dpr), corner)
    .then((shot) => {
      // shot.ms is the capture's own cost; the rest of the round trip is
      // the bridge waiting, and pacing off that throttled this to a
      // quarter of the rate the CPU budget actually allows.
      // Python declined to capture: this window is hidden, or every
      // pixel of it is behind something else. Nothing to draw, and no
      // frame cost to pace from - just wait as long as it asked.
      if (shot && shot.skip) {
        backdropSkipMs = shot.retry_ms || 500;
        backdropPending = false;
        return;
      }
      backdropSkipMs = 0;
      noteFrameCost((shot && shot.ms) || (performance.now() - startedAt));
      if (!shot) { backdropPending = false; return; }
      if (shot.unchanged) { backdropStill += 1; backdropPending = false; return; }
      backdropStill = 0;
      backdropHash = shot.hash;
      if (!shot.url) { backdropPending = false; return; }
      // Both frames are decoded before either is drawn, so the sharp
      // desktop and the frosted card can never be a frame apart.
      return Promise.all([
        decodeShot(shot.url),
        shot.blur_url ? decodeShot(shot.blur_url) : null,
      ]).then(([sharp, blurred]) => {
        paintBackdrop(sharp, blurred, shot.w, shot.h, shot.corner || 0);
        sharp.close();
        if (blurred) blurred.close();
        backdropPending = false;
      }, () => { backdropPending = false; });
    })
    .catch(() => { backdropPending = false; });
}

// Anything that changes *which* pixels are behind the window invalidates
// the comparison as well as the image.
function invalidateBackdrop() {
  backdropHash = null;
  backdropStill = 0;
}

// Coalesced: a resize or a drag produces a burst of these, and each one is
// a full desktop render on the Python side.
let backdropSoonTimer = null;
function refreshBackdropSoon(delay) {
  invalidateBackdrop();
  clearTimeout(backdropSoonTimer);
  backdropSoonTimer = setTimeout(refreshBackdrop, delay === undefined ? 60 : delay);
}

function startBackdropTicker() {
  if (backdropTimer) return;
  // Chained rather than setInterval: each frame waits for the previous one
  // to come back, so a slow machine thins the rate out instead of queueing
  // work it cannot keep up with.
  const tick = () => {
    const wait = backdropSkipMs
      || (backdropStill >= BACKDROP_STILL_BEFORE_IDLE
        ? BACKDROP_IDLE_MS
        : Math.max(BACKDROP_MIN_MS, Math.round(backdropFrameMs * BACKDROP_DUTY)));
    backdropTimer = setTimeout(() => {
      (document.hidden ? Promise.resolve() : refreshBackdrop()).then(tick, tick);
    }, wait);
  };
  refreshBackdrop().then(tick, tick);
}

/* ============================================================
 * Dragging the widget around the desktop
 * ============================================================ */
// Done here rather than through pywebview's own drag-region support,
// which moves the window on the first mousemove after any mousedown on
// the region - no threshold at all. The detail popover is dismissed by
// clicking away from it, and that click lands on the grid's background,
// so dismissing it dragged the widget out from under the pointer. Its
// move() also takes logical pixels and rescales them, which on a display
// whose devicePixelRatio disagrees with the OS scale (this project's dev
// machine, via Windows text scaling) made the window jump instead of
// follow. Screen deltas converted with the page's own dpr, sent as
// absolute physical pixels, track the pointer exactly.
const DRAG_THRESHOLD_PX = 5;

function installWindowDrag() {
  // The popover is placed by its tile and the flyout by the tray icon;
  // neither is ever dragged.
  if (IS_POPOVER_WINDOW || IS_FLYOUT_WINDOW) return;
  const kind = IS_SETTINGS_WINDOW ? 'settings' : 'main';
  let start = null;

  document.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (CONFIG.lock_position && !IS_SETTINGS_WINDOW) return;
    if (!e.target.closest('.drag-region')) return;
    // Controls sitting inside a drag region (the header's close/back
    // buttons) are for clicking, not for dragging the window by.
    if (e.target.closest('button, input, select, textarea, a, [data-action]')) return;
    start = { sx: e.screenX, sy: e.screenY, origin: null, moved: false };
    // Fetched once per drag, not per move: it's a round trip into Python,
    // and the window's origin only changes because *we* move it.
    window.pywebview.api.get_window_pos(kind)
      .then((pos) => { if (start) start.origin = pos; })
      .catch(() => { start = null; });
  });

  document.addEventListener('mousemove', (e) => {
    if (!start || !start.origin) return;
    const dpr = window.devicePixelRatio || 1;
    const dx = (e.screenX - start.sx) * dpr;
    const dy = (e.screenY - start.sy) * dpr;
    if (!start.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
    start.moved = true;
    window.pywebview.api.move_window(
      Math.round(start.origin.x + dx), Math.round(start.origin.y + dy), kind,
    ).catch(() => {});
    // Different part of the desktop now behind the window.
    refreshBackdropSoon(60);
  });

  const end = () => { start = null; };
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
    // Unlocked is a normal state for a door someone is using, not a
    // fault, so it is a soft green rather than the red it used to be -
    // which read as an alert every time anyone came home.
    case 'lock': return state && state.state === 'locked' ? 'var(--text-off-1)' : 'var(--accent-green-soft)';
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
  const badge = (domain === 'climate' && ok && !tile.icon) ? climateBadge(state, on) : null;
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

  // The badge above already is the temperature; printing it again as the
  // tile's headline would just be the same number twice.
  const valueText = (ok && !badge) ? valueTextFor(domain, state) : '';
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

  // A read-only accessory is a readout: the number is what the tile is
  // for, and the name below it only says which one. It gets no second
  // line, because that line would just repeat the number as raw state.
  if (!meta.readonly || !valueText) {
    const label = document.createElement('div');
    label.className = 'tile-label';
    label.textContent = ok ? (tile.label || defaultLabel(domain, state)) : '無法連線';
    div.appendChild(label);
  }

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

  // Read-only accessories have nothing to toggle, but they still need the
  // detail card: that is where a tile's name and icon are edited, and
  // without this a sensor could only ever be removed and re-added.
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
    // 'click' only ever fires for the primary (left) button, so right-click
    // naturally can't trigger this - it opens the detail card instead, the
    // same as on an expandable tile, since that is the only way to rename
    // this accessory.
    el.addEventListener('click', (e) => {
      if (e.target.closest('.mini-btn')) return;
      quickAction(tile);
    });
    el.addEventListener('contextmenu', (e) => { e.preventDefault(); requestPopover(tile); });
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

  // Right-click jumps straight to the detailed control sheet (brightness,
  // temperature, position...) instead of duplicating the left-click action.
  el.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    requestPopover(tile);
  });
}

// The grid lives in the main window; the detail popover lives in its own
// separate window (see IS_POPOVER_WINDOW) - so opening it from a tile
// here means asking Python to move/show *that* window at this tile's
// current screen position, rather than showing anything locally. Python
// then pushes the tile id into that window via __showPopoverForTile.
function requestPopover(tile) {
  const tileNode = document.querySelector('.tile[data-id="' + tile.id + '"]');
  if (!tileNode || !(window.pywebview && window.pywebview.api)) return;
  const dpr = window.devicePixelRatio || 1;
  const r = tileNode.getBoundingClientRect();
  window.pywebview.api.get_window_pos(WINDOW_KIND).then((pos) => {
    const screenX = Math.round((pos && pos.x || 0) + r.left * dpr);
    const screenY = Math.round((pos && pos.y || 0) + r.top * dpr);
    // The tile's size goes along too: near a screen edge the popover
    // flips to align with the tile's far edge rather than its near one,
    // which it cannot work out from a corner alone.
    return window.pywebview.api.open_popover(
      tile.id, screenX, screenY, Math.round(r.width * dpr), Math.round(r.height * dpr),
    );
  }).catch(() => {});
}

// Pushed from Python each time the tray flyout is shown, to replay its
// entrance. Restarting a CSS animation needs the class off, a layout read
// to make that land, and the class back on.
// Called by Python while the window is still hidden but already moved
// to where it will appear: puts the card back to its pre-entrance state
// and takes a fresh backdrop of the place it is about to cover. Without
// it the panel arrived carrying whatever was behind it last time - a
// frosted picture of somewhere else, replaced a moment later, which is
// the flash and the lag. Python waits for the flyout_ready call back
// before it shows the window.
function flyoutLayers() {
  // The card and the frosted pane behind it animate as one thing.
  return [document.getElementById('view-grid'),
          document.getElementById('backdrop-glass')].filter(Boolean);
}

window.__flyoutPrepare = function () {
  for (const el of flyoutLayers()) el.classList.remove('flyout-enter', 'flyout-leave');
  const done = () => {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.flyout_ready().catch(() => {});
    }
  };
  invalidateBackdrop();
  Promise.resolve(refreshBackdrop()).then(done, done);
};

window.__flyoutEnter = function () {
  for (const el of flyoutLayers()) {
    el.classList.remove('flyout-enter', 'flyout-leave');
    void el.offsetWidth;
    el.classList.add('flyout-enter');
  }
};

// ...and to play it backwards on the way out. Python waits out the
// animation before it actually hides the window (see hide_flyout).
window.__flyoutLeave = function () {
  for (const el of flyoutLayers()) {
    el.classList.remove('flyout-enter');
    void el.offsetWidth;
    el.classList.add('flyout-leave');
  }
};

// Pushed from Python (see Api.open_popover in main.py) once the popover
// window has been moved into position for a given tile.
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
let popoverCloseTimer = null;

// Detail cards only ever open in the popover window. The grid window
// hands off to it instead of rendering one itself (requestPopover ->
// Api.open_popover -> __showPopoverForTile), so this whole path is a
// no-op there - guarded rather than assumed, since both windows run this
// same script.
function openDetail(tile) {
  if (!IS_POPOVER_WINDOW) return;
  const popover = document.getElementById('detail-popover');
  const backdrop = document.getElementById('detail-backdrop');
  if (popoverCloseTimer) { clearTimeout(popoverCloseTimer); popoverCloseTimer = null; }

  currentDetailTileId = tile.id;
  showEditMode(false);
  renderDetailBody();

  // This window shows nothing but the popover (view-grid is permanently
  // hidden here - see IS_POPOVER_WINDOW/boot), so the card sits at the
  // window's own origin: there is no laid-out tile in this window to
  // anchor it to, and the window itself was already moved over the tile
  // that asked for it. In this window the card is in the flow rather
  // than absolutely positioned (.is-popover-window), which is what lets
  // #stage - and so the window - be exactly the size of the card,
  // whatever its content came to. Hard-coding that size here instead
  // meant every change to the card's CSS had to be mirrored in a pair of
  // constants, and when it wasn't the card was quietly clipped.
  backdrop.hidden = false;
  popover.hidden = false;
  requestAnimationFrame(() => popover.classList.add('show'));
  syncWindowSize();
  // This window was just moved over the tile that asked for it, so
  // whatever backdrop it last captured is of somewhere else entirely.
  refreshBackdropSoon(60);
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
    if (currentDetailTileId) return; // reopened (on a different tile) before the fade finished
    popover.hidden = true;
    // Nothing else is ever shown in this window - hide the whole OS
    // window instead of shrinking it down to 0x0 and leaving it sitting
    // there invisible-but-present.
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
  'light', 'switch', 'climate', 'fan', 'cover', 'curtain', 'media', 'monitor',
  'lock', 'door', 'vacuum', 'scene', 'script', 'automation',
  'thermometer', 'humidity', 'sensor',
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
// A switch or a lock has one thing to say - it is on or it is off - and
// a fill creeping up from the bottom says it badly. This is the physical
// version: a slab that sits in the bottom half of the tile, dark, and
// rides up to the top half and turns white when it is on. The icon
// travels with it, so a lock's shackle opens where the eye already is.
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

// Accessories with nothing to operate - sensors, and anything this build
// has no controls for - still open a detail card, because that is where
// renaming and icon-picking live. Showing the reading large is more use
// than showing an empty panel.
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
    body.appendChild(toggleSlabTile(iconNameFor(tile, state), on, () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService('switch', 'toggle', tile.entity);
    }));
  },
  input_boolean(body, tile, state) {
    const on = !!state && state.state === 'on';
    body.appendChild(toggleSlabTile(iconNameFor(tile, state), on, () => {
      optimisticSet(tile.entity, { state: on ? 'off' : 'on' });
      callService('input_boolean', 'toggle', tile.entity);
    }));
  },
  lock(body, tile, state) {
    // Up and white is open, the same way round as every other accessory
    // here - which for a lock means unlocked.
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

// From the grid, Settings is a different window - so this is a request to
// Python to bring that window up, not a view swap.
function openSettings() {
  if (!IS_SETTINGS_WINDOW) {
    if (window.pywebview && window.pywebview.api) {
      window.pywebview.api.open_settings_window().catch(() => {});
    }
    return;
  }
  return openSettingsView();
}

// Pushed from Python when the Settings window is shown (Api.open_settings_window).
window.__enterSettings = function () {
  try { openSettingsView(); } catch (e) { /* ignore */ }
};

function openSettingsView() {
  document.getElementById('ha-url').value = CONFIG.ha_url || '';
  document.getElementById('ha-token').value = CONFIG.ha_token || '';
  document.getElementById('theme-select').value = CONFIG.theme || 'auto';
  document.getElementById('columns-select').value = String(CONFIG.columns || 4);
  setZoomSlider(CONFIG.zoom || 100);
  document.getElementById('lock-position-check').checked = !!CONFIG.lock_position;
  document.getElementById('fast-glass-check').checked = CONFIG.fast_glass !== false;
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

async function savePrefs() {
  try {
    await window.pywebview.api.save_prefs(CONFIG.theme, CONFIG.columns, CONFIG.lock_position,
      CONFIG.zoom, CONFIG.fixed_size, CONFIG.fixed_width, CONFIG.fixed_height,
      CONFIG.opacity, CONFIG.fast_glass);
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
  document.getElementById('fast-glass-check').addEventListener('change', async (e) => {
    CONFIG.fast_glass = !!e.target.checked;
    await savePrefs();
    // The capture path changed underneath us, so the pacing estimate and
    // the held frame are both about the old one.
    backdropFrameMs = BACKDROP_MIN_MS;
    refreshBackdropSoon(0);
  });
  // The number follows the thumb while it is being dragged, but the
  // widget is only re-laid-out on release: every step in between would
  // save the config and put the grid window through a relayout and a
  // fresh desktop capture, which is a lot of work to throw away 5% later.
  const zoomRange = document.getElementById('zoom-range');
  zoomRange.addEventListener('input', (e) => {
    document.getElementById('zoom-value').textContent = e.target.value + '%';
  });
  zoomRange.addEventListener('change', async (e) => {
    CONFIG.zoom = Number(e.target.value);
    setZoomSlider(CONFIG.zoom);
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
    else if (IS_SETTINGS_WINDOW) closeSettingsAndSave();
    else if (currentDetailTileId) closeDetail();
  });

  installWindowDrag();
}

// Pushed from Python whenever preferences change (Api._push_prefs).
// The popover lives in a second window with its own copy of this script
// and its own CONFIG, loaded once at startup - without this it kept the
// zoom and theme it booted with, so changing either in Settings left the
// detail card rendering at the old scale until the app was restarted.
window.__applyPrefs = function (cfg) {
  if (!cfg) return;
  // The window that made the change gets this back too, so compare before
  // acting: re-rendering the grid or the tile list underneath someone who
  // is mid-edit is worse than doing nothing.
  const tilesChanged = JSON.stringify(cfg.tiles || []) !== JSON.stringify(CONFIG.tiles || []);
  const themeChanged = cfg.theme !== CONFIG.theme;
  const layoutChanged = cfg.zoom !== CONFIG.zoom || cfg.columns !== CONFIG.columns ||
    cfg.fixed_size !== CONFIG.fixed_size || cfg.fixed_width !== CONFIG.fixed_width ||
    cfg.fixed_height !== CONFIG.fixed_height;
  if (!tilesChanged && !themeChanged && !layoutChanged) {
    CONFIG = Object.assign({}, CONFIG, cfg);
    return;
  }
  CONFIG = Object.assign({}, CONFIG, cfg);
  if (themeChanged) applyTheme();
  if (layoutChanged) { applyZoom(); applyFixedSizeConstraint(); }
  if (tilesChanged && !IS_POPOVER_WINDOW) renderGrid();
  if (tilesChanged && !document.getElementById('view-settings').hidden) renderTileList();
  if (currentDetailTileId) renderDetailBody();
  syncWindowSize();
  refreshBackdropSoon();
};

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
