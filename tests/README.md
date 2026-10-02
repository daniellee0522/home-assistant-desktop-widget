# Regression checks

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
node tests/backdrop.cjs
node tests/layout.cjs
```

- **Python unit tests** extract the relevant functions from `main.py` and
  `qtshell.py`, so they run without starting Qt or touching the desktop.
  `test_dxgi_capture.py` covers Desktop Duplication's rotation mapping and
  change tracking without a GPU. They cover GDI object selection, clipped captures, capture-exclusion and
  DWM rollback logic, capture worker timeout/restart, and per-page push
  delivery during loading. Resume checks cover short sleeps, preserving
  manually hidden widgets, and tray recovery independent of desktop visibility.
- **`test_native_widget.py`** runs the natively drawn desktop widget (`nativeui/`) against a stand-in Api: taps, holds, right-click, the climate buttons, dragging, dimming, the wheel, pushed preferences and states, the empty widget, and that every glass style, theme and tile form draws.
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
and a hidden Qt page. It also delivers a native Windows resume notification
through Qt and verifies tray re-registration on pystray's message thread.
It does not connect to Home Assistant or change settings.

None of these verify real DWM/PrintWindow output. Before shipping, run the
app in compatibility mode over both static and moving windows; some
GPU-rendered applications do not provide complete PrintWindow output.
