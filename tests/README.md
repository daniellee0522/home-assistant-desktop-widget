# Regression checks

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
node tests/backdrop.cjs
node tests/layout.cjs
```

- **Python unit tests** extract the relevant functions from `main.py` and
  `qtshell.py`, so they run without starting Qt or touching the desktop.
  They cover GDI object selection, clipped captures, capture-exclusion and
  DWM rollback logic, capture worker timeout/restart, and per-page push
  delivery during loading.
- **`backdrop.cjs`** needs only Node.js. It runs the page's backdrop loop
  with a mocked bridge: decode recovery, stale-frame rejection, native glass
  activation, and the bridge's HTTP timeout.
- **`layout.cjs`** needs Playwright and Microsoft Edge (set
  `PLAYWRIGHT_MODULE` if Playwright is not on Node's module path). It serves
  the real web assets with a mocked API and simulated native resizes:
  settings menus (pointer, keyboard, Escape, hidden options), repeated theme
  changes without host resizing, fixed size and zoom isolation, high DPI,
  and empty panels.

On Windows with the app dependencies installed, `python tests/native_smoke.py`
also checks native GDI resource counts, the compatibility capture subprocess,
and a hidden Qt page. It does not connect to Home Assistant or change settings.

None of these verify real DWM/PrintWindow output. Before shipping, run the
app in compatibility mode over both static and moving windows; some
GPU-rendered applications do not provide complete PrintWindow output.
