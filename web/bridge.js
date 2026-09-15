// The page's half of the bridge to Python.
//
// The object it builds is pywebview's, name for name, because app.js was
// written against that and there is nothing wrong with the shape: every
// method returns a promise of whatever Python returned. What is different
// is underneath - the call is a POST to the same origin the page was
// served from (see qtshell.py), which needs no injection into the page
// and no channel library, and is the same transport in both directions.
(function () {
  function call(name, args) {
    return fetch('/api/' + name, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
      cache: 'no-store',
    }).then(function (r) {
      if (!r.ok) throw new Error(name + ': HTTP ' + r.status);
      return r.json();
    }).then(function (r) {
      if (r && r.error) throw new Error(name + ': ' + r.error);
      return r ? r.value : null;
    });
  }

  // A proxy rather than a fixed list, so adding a method to the Python
  // side is all it takes - and so that pulling one off the object to call
  // later (app.js does that to pick a resize function) still works.
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
  // app.js waits for this before it asks for anything (see the bottom of
  // app.js), exactly as it did under pywebview.
  window.addEventListener('DOMContentLoaded', function () {
    window.dispatchEvent(new Event('pywebviewready'));
  });
  if (document.readyState !== 'loading') {
    window.dispatchEvent(new Event('pywebviewready'));
  }
})();
