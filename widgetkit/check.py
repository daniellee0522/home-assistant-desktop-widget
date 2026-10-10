"""Check a widget you have written, the way a person (or an AI) writing one needs: does it load, how does it look, what is wrong.

    python -m widgetkit.check WIDGET [--out preview.png] [--langs en,zh-TW,pseudo-zh] [--themes dark,light]
                                     [--sizes 2x2,2x4] [--config '{"goal": 6}'] [--standby] [--pack my.hawidget]

WIDGET is a .py file that defines WIDGET, or a package folder (manifest.json + main.py). It is drawn in every size it supports,
in light and dark and in the languages asked for (`pseudo`/`pseudo-zh` are longer, made-up words: they show what will not fit),
and the picture of all of them is written to --out. What is wrong is listed one to a line:

    ERROR  load      the widget's code failed to load: ...
    ERROR  error     when pressed: ...
    WARN   cut       "..." is cut off [2x2 dark pseudo]
    WARN   hint      ...

The exit code is 1 when there is an ERROR, else 0. With --pack the checked widget is written as a .hawidget to import in the
program (nothing is written when there is an ERROR).
"""
import argparse
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ERRORS = ("load", "error")


def cell_name(issue):
    cell = getattr(issue, "cell", None)
    return " [%s %s %s]" % (cell.size, cell.theme, cell.lang) if cell is not None else ""


def as_folder(path):
    """A package folder for `path`: the folder itself, or a .py file wrapped as one (its manifest worked out from its WIDGET)."""
    from widgetkit import package
    if os.path.isdir(path):
        return path
    return package.wrap_file(path, tempfile.mkdtemp(prefix="widget-check-"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m widgetkit.check", description=__doc__.split("\n\n")[0])
    ap.add_argument("widget")
    ap.add_argument("--out", default="widget-preview.png", help="where the picture of every size, theme and language is written")
    ap.add_argument("--langs", default="en,zh-TW,pseudo-zh")
    ap.add_argument("--themes", default="light,dark")
    ap.add_argument("--sizes")
    ap.add_argument("--config", help="the settings as JSON, to see the widget as they make it")
    ap.add_argument("--state", help="the widget's memory as JSON")
    ap.add_argument("--standby", action="store_true", help="draw it as it is in standby")
    ap.add_argument("--pack", metavar="FILE.hawidget", help="write the checked widget as a package to import")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")        # (the words of a widget may be Chinese)
    split = lambda s: [x for x in s.split(",") if x] if s else None
    from widgetkit import package
    from widgetkit.studio.ui import run
    try:
        folder = as_folder(args.widget)
    except package.PackageError as e:
        print("ERROR  load      %s" % e)
        return 1
    win = run(args.widget, args.out, "problems", langs=split(args.langs), themes=split(args.themes), sizes=split(args.sizes), config=args.config, state=args.state,
              standby=args.standby, width=1500, height=900)
    session = win.s
    issues = session.all_issues()
    session.check_backgrounds()
    issues = session.all_issues()
    bad = [i for i in issues if i.kind in ERRORS]
    for i in issues:
        print("%-6s %-9s %s%s" % ("ERROR" if i.kind in ERRORS else "WARN", i.kind, i.text, cell_name(i)))
    widget = session.widget
    if widget is not None:
        print("widget %s: sizes %s, standby %s, background %s" % (widget.id, ", ".join(widget.supported_sizes()),
              "ticks every %ss" % widget.standby_interval() if widget.standby_interval() else "still", widget.background))
    print("picture: %s" % os.path.abspath(args.out))
    if args.pack and not bad:
        out = package.export(folder, args.pack)
        print("package: %s  (import it in Settings > Widget editor > the + under Imported widgets)" % os.path.abspath(out))
    print("%d error(s), %d warning(s)" % (len(bad), len(issues) - len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
