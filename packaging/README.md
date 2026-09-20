# Build an installer

Requirements: Windows, Python 3.12, the project dependencies, PyInstaller, and
Inno Setup 6. Installers bundle Python and Qt; end users do not need either.

```powershell
pip install -r requirements.txt pyinstaller
./packaging/release.ps1 -Version 1.3.0
```

The version comes from `VERSION`. Output is
`dist/<version>/HA-Widgets-Setup-<version>.exe`, with a SHA-256 checksum beside it.
Use `--iscc "C:\path\to\ISCC.exe"` if the compiler is not found automatically.

For the next release, use a new semantic version:

```powershell
./packaging/release.ps1 -Version 1.3.1
```

The script writes `VERSION`, runs the test suite, builds the bundle and
installer, and produces a SHA-256 file. Review and commit the version change
before attaching the installer and checksum to a GitHub release with the same
`v<version>` tag. Pass `-Iscc "C:\path\to\ISCC.exe"` if needed.

Keep the `AppId` in `installer.iss` unchanged. Running a newer installer updates
the existing installation and preserves `%APPDATA%\HA Widgets` settings.
It closes the installed app when necessary and launches the updated app afterward.
Startup preferences are left unchanged. There is no automatic online update check.

The build uses a restricted DLL search path and checks the frozen capture worker
before creating the installer. Release 1.1.1 also removes the incompatible ICU
files accidentally included in 1.1.0 during an upgrade.

The installer does not bundle local Home Assistant credentials. On first install,
it can migrate a legacy settings file from the installation folder or a nearby
source checkout; existing user settings always win.

Installer testing: `/VERYSILENT /TESTINSTALL=1 /DIR="<isolated directory>"` skips
shortcuts, uninstall registration, and launching. Settings migration is redirected
to `test-user-data` inside that directory. Never use this switch for a normal install.
