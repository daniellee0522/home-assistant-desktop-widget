# Regression checks

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
node tests/backdrop.cjs
node tests/layout.cjs
```

The browser checks require Playwright and Microsoft Edge. Set
`PLAYWRIGHT_MODULE` to an existing Playwright installation if it is not on
Node's module path. They serve the actual web assets with a mocked API and
simulate native resize responses, without Home Assistant credentials.

The backdrop script only requires Node.js. It checks decode recovery, stale-frame
rejection, and confirmed native activation. Python checks also cover GDI object
selection, clipped captures, DWM rollback, capture worker timeout/restart, and
per-page push delivery during loading.

On Windows with the app dependencies installed, `python tests/native_smoke.py`
also checks native GDI resource counts, the compatibility subprocess, and a
hidden Qt page. It does not connect to Home Assistant or change settings.

Covered: settings menus (pointer, keyboard, Escape, hidden options), repeated
theme changes without host resizing, fixed size and zoom isolation, high DPI,
empty panels, state/status fan-out, failed refreshes, compatibility capture
window ordering, and saving outside the installation directory.

The Python tests extract the relevant methods from `main.py` so they can run
without starting Qt or controlling a desktop. These checks do not verify
Windows DWM/PrintWindow output. Test the running Qt app over both static and
moving background windows in compatibility mode before shipping a build;
some GPU-rendered applications do not provide complete PrintWindow output.
