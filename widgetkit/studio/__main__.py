"""python -m widgetkit.studio path/to/widget.py [--shot out.png] [--tab icons] [--search water] [--langs en,zh-TW]
                                [--themes dark,light] [--sizes 2x2,4x4] [--zoom 1.0] [--overlays hits,safe]

Opens the studio on a widget file (or a package folder). Save the file in any editor and it reloads. --shot writes a
picture of the window and exits (for documentation and for tests).
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser(prog="python -m widgetkit.studio")
    ap.add_argument("widget", nargs="?", default=os.path.join(ROOT, "widgetkit", "examples", "water.py"))
    ap.add_argument("--shot")
    ap.add_argument("--tab", choices=("settings", "state", "problems", "actions", "icons"))
    ap.add_argument("--search")
    ap.add_argument("--langs")
    ap.add_argument("--themes")
    ap.add_argument("--sizes")
    ap.add_argument("--zoom", type=float)
    ap.add_argument("--overlays", default="")
    ap.add_argument("--state", help="the widget's memory as JSON")
    ap.add_argument("--config", help="the settings as JSON")
    ap.add_argument("--standby", action="store_true", help="show the widget as it is in standby")
    ap.add_argument("--width", type=int)
    ap.add_argument("--height", type=int)
    a = ap.parse_args()
    from widgetkit.studio.ui import run
    split = lambda s: [x for x in s.split(",") if x] if s else None
    code = run(a.widget, a.shot, a.tab, a.search, split(a.langs), split(a.themes), split(a.sizes), a.zoom,
               split(a.overlays) or (), width=a.width, height=a.height, state=a.state, config=a.config, standby=a.standby)
    sys.exit(code if isinstance(code, int) else 0)


if __name__ == "__main__":
    main()
