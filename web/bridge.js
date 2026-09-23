// The page's half of the bridge to Python: window.pywebview.api.<name>(...)
// POSTs to /api/<name> on the page's own origin (see qtshell.py) and
// resolves to whatever Python returned.
(function () {
  function call(name, args) {
    const controller = new AbortController();
    const timeout = name === 'get_desktop_backdrop'
      ? setTimeout(() => controller.abort(), 12000) : null;
    return fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
      cache: 'no-store',
      signal: controller.signal,
    }).then(function (r) {
      if (!r.ok) throw new Error(name + ': HTTP ' + r.status);
      return r.json();
    }).then(function (r) {
      if (r && r.error) throw new Error(name + ': ' + r.error);
      return r ? r.value : null;
    }).finally(() => { if (timeout !== null) clearTimeout(timeout); });
  }

  // A proxy, so any public Python method is callable without a list here.
  var api = new Proxy({}, {
    get: function (_, name) {
      if (typeof name !== 'string') return undefined;
      return function () {
        return call(name, Array.prototype.slice.call(arguments));
      };
    },
    has: function () { return true; },
  });

  window.pywebview = { api: api };
  // app.js boots on this event.
  window.addEventListener('DOMContentLoaded', function () {
    window.dispatchEvent(new Event('pywebviewready'));
  });
  if (document.readyState !== 'loading') {
    window.dispatchEvent(new Event('pywebviewready'));
  }
})();
