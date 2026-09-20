"""Build a versioned Qt bundle and, with --installer, an upgrade installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'packaging'
NAME = 'HA Widgets'


def compiler_path(override):
    candidates = [override, os.environ.get('ISCC'), shutil.which('ISCC.exe'),
                  ROOT / 'build/tools/inno/ISCC.exe']
    for base in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        folder = os.environ.get(base)
        if folder:
            candidates.extend([Path(folder) / 'Inno Setup 6/ISCC.exe',
                               Path(folder) / 'Programs/Inno Setup 6/ISCC.exe'])
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise SystemExit('Inno Setup not found. Install it or pass --iscc PATH.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default=(ROOT /
                        'VERSION').read_text(encoding='utf-8-sig').strip())
    parser.add_argument('--installer', action='store_true')
    parser.add_argument('--iscc')
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        parser.error('--version must be MAJOR.MINOR.PATCH')
    parts = tuple(map(int, args.version.split('.'))) + (0,)
    if any(part > 65535 for part in parts):
        parser.error('version components must be <= 65535')
    compiler = compiler_path(args.iscc) if args.installer else None
    # Keep unrelated developer tools (notably Poppler's incompatible ICU)
    # out of PyInstaller's native dependency search.
    build_env = os.environ.copy()
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    build_env['PATH'] = os.pathsep.join(map(str, [Path(sys.executable).parent,
                                                windows / 'System32', windows]))
    work = ROOT / 'build' / args.version
    output = ROOT / 'dist' / args.version
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    # Only versioned build output is replaced; previous release installers remain.
    version_file = work / 'version-info.txt'
    version_file.write_text(f'''VSVersionInfo(
      ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f,
                        flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)),
      kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'HA Widgets'),
        StringStruct('FileDescription', 'Home Assistant Desktop Widgets'),
        StringStruct('FileVersion', '{args.version}'),
        StringStruct('ProductName', 'HA Widgets'),
        StringStruct('ProductVersion', '{args.version}'),
        StringStruct('OriginalFilename', 'HA Widgets.exe')
      ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])''', encoding='utf-8')

    qt_package = 'PySide6'

    pyinstaller_cmd = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed',
        '--name', NAME, '--icon', str(HERE / 'app.ico'),
        '--version-file', str(version_file),
        '--workpath', str(work / 'pyinstaller'), '--specpath', str(work),
        '--distpath', str(
            output), '--add-data', f'{ROOT / "web"}{os.pathsep}web',
        '--hidden-import', 'PIL._imagingft',
        '--hidden-import', f'{qt_package}.QtCore',
        '--hidden-import', f'{qt_package}.QtWidgets',
        '--hidden-import', f'{qt_package}.QtGui',
        str(ROOT / 'main.py'),
    ]

    subprocess.check_call(pyinstaller_cmd, cwd=ROOT, env=build_env)

    bundle = output / NAME
    # A successful analysis is not enough: verify the frozen Qt import and
    # multiprocessing path before publishing an installer.
    subprocess.check_call([sys.executable, str(HERE / 'test_frozen_worker.py'),
                           str(bundle / (NAME + '.exe'))], cwd=ROOT)
    (bundle / 'build-info.json').write_text(json.dumps({
        'version': args.version, 'python': sys.version.split()[0],
        'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [ROOT / 'main.py', ROOT / 'qtshell.py', ROOT / 'capture_worker.py',
                                    ROOT / 'web/app.js', ROOT / 'web/bridge.js',
                                    ROOT / 'web/i18n.js', ROOT / 'web/mdi-paths.js']},
    }, indent=2), encoding='utf-8')

    if compiler:
        subprocess.check_call([compiler, f'/DAppVersion={args.version}',
                               f'/DSourceDir={bundle}', f'/DReleaseDir={output}',
                               str(HERE / 'installer.iss')], cwd=ROOT)
        installer = output / f'HA-Widgets-Setup-{args.version}.exe'
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()
        installer.with_suffix('.exe.sha256').write_text(
            f'{digest}  {installer.name}\n', encoding='ascii')
        print(f'Installer: {installer}\nSHA256: {digest}', flush=True)
    else:
        print(f'Bundle: {bundle}', flush=True)


if __name__ == '__main__':
    main()
