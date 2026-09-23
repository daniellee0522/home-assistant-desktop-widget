# Build an installer

Requirements: Windows, Python 3.12, the project dependencies, PyInstaller, and
Inno Setup 6. Installers bundle Python and Qt; end users need neither.

```powershell
pip install -r requirements.txt pyinstaller
./packaging/release.ps1 -Version 1.3.1
```

`release.ps1` writes `VERSION`, runs the Python tests, builds the bundle and
installer, and writes a SHA-256 checksum. Output is
`dist/<version>/HA-Widgets-Setup-<version>.exe`. Pass
`-Iscc "C:\path\to\ISCC.exe"` if Inno Setup is not found automatically.

To build without bumping the version, run `python packaging/build.py
--installer` (add `--iscc PATH` if needed); the version comes from `VERSION`.
Without `--installer` only the PyInstaller bundle is built.

Review and commit the version change, then attach the installer and checksum
to a GitHub release tagged `v<version>`.

## Upgrades

Keep the `AppId` in `installer.iss` unchanged. A newer installer updates the
existing installation, preserves `%APPDATA%\HA Widgets` settings, closes the
running app when necessary, and relaunches it afterward. Startup preferences
are left unchanged. There is no automatic update check.

The build uses a restricted DLL search path and checks the frozen capture
worker (`test_frozen_worker.py`) before creating the installer. The installer
also removes incompatible ICU files that 1.1.0 shipped by mistake.

The installer never bundles local Home Assistant credentials. On first
install it can migrate a legacy settings file from the installation folder or
a nearby source checkout; existing user settings always win.

## Testing the installer

`/VERYSILENT /TESTINSTALL=1 /DIR="<isolated directory>"` skips shortcuts,
uninstall registration, and launching, and redirects settings migration to
`test-user-data` inside that directory (see `test_installer.ps1`). Never use
this switch for a normal install.
