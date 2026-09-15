"""Build the installable Windows app.

    python packaging/build.py

Leaves dist/HA Widgets/ - the program and everything it needs - which is
what packaging/installer.iss turns into a setup, and what Install.ps1
copies into place when there is no Inno Setup around.

A directory rather than a single file: WebView2 and the .NET bridge both
load native DLLs, which a one-file build has to unpack to a temporary
folder on every launch, and this is a program that starts with Windows
and then sits there for days.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAME = "HA Widgets"


def main():
    subprocess.check_call([sys.executable, os.path.join(HERE, "make_icon.py")])
    for stale in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, stale), ignore_errors=True)
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",                      # no console window behind it
        "--name", NAME,
        "--icon", os.path.join(HERE, "app.ico"),
        "--add-data", "%s%sweb" % (os.path.join(ROOT, "web"), os.pathsep),
        # The tray icon is drawn at runtime from Segoe Fluent Icons, so
        # there is nothing to bundle for it - but Pillow's font support
        # has to come along.
        "--hidden-import", "PIL._imagingft",
        os.path.join(ROOT, "main.py"),
    ]
    print(" ".join(args))
    subprocess.check_call(args, cwd=ROOT)
    out = os.path.join(ROOT, "dist", NAME)
    print("\nbuilt:", out)
    exe = os.path.join(out, NAME + ".exe")
    print("exists:", os.path.exists(exe), os.path.getsize(exe) if os.path.exists(exe) else "")


if __name__ == "__main__":
    main()
