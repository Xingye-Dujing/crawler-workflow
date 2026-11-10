"""Build the macOS *online installer* (.app + DMG).

    python desktop/build_macos_installer.py --arch arm64

The installer is a small PyInstaller ``.app`` (the shared page + component core, no analysis stack).
It carries the checked-in catalogue, whose application entry names the release feed: the version,
size and digest of the app DMG are read from ``version.json`` when somebody installs, not compiled in
here. That is why this script no longer takes the application DMG as an input — the same installer
installs every later release, and only a change to the installer itself needs a rebuild.

Run on macOS, or by ``.github/workflows/macos-build.yml``.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'desktop'
BOOTSTRAP = DESKTOP / 'bootstrap'
SPEC = BOOTSTRAP / 'installer_macos.spec'
DIST = ROOT / 'dist'
WORK = ROOT / 'build' / 'pyinstaller-macos-installer'
APP_BINARY = 'CaiXiHui.app/Contents/MacOS/CaiXiHui'


def asset_key(arch: str) -> str:
    """The catalogue's CPU key: the DMG names its architecture, the catalogue normalizes it."""
    value = str(arch or '').lower()
    if value in ('arm64', 'aarch64'):
        return 'arm64'
    if value in ('x86_64', 'amd64', 'x64'):
        return 'x64'
    raise SystemExit(f'unsupported macOS architecture {arch!r}')


def artifact_arch(arch: str) -> str:
    return 'arm64' if asset_key(arch) == 'arm64' else 'x86_64'


def run(command: list[str]) -> None:
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, check=True, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build the macOS online installer app and DMG')
    parser.add_argument('--arch', default=platform.machine() or 'arm64')
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        print('this build must run on macOS', file=sys.stderr)
        return 2
    if args.clean:
        shutil.rmtree(DIST / 'CaiXiHui-Online-Setup.app', ignore_errors=True)
        for old in DIST.glob('CaiXiHui-Online-Setup-macOS-*.dmg'):
            old.unlink(missing_ok=True)
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)

    # The same .icns the application uses; a missing Pillow just leaves the default icon.
    from build_macos import make_icns

    icon = make_icns()
    if icon is not None:
        os.environ['CIXI_MACOS_ICON'] = str(icon)
    run(
        [
            sys.executable,
            '-m',
            'PyInstaller',
            '--noconfirm',
            '--clean',
            '--distpath',
            str(DIST),
            '--workpath',
            str(WORK / 'work'),
            str(SPEC),
        ]
    )
    app = DIST / 'CaiXiHui-Online-Setup.app'
    if not app.is_dir():
        print(f'expected installer bundle not found: {app}', file=sys.stderr)
        return 1
    from build_macos import build_dmg

    artifact = build_dmg(app, artifact_arch(args.arch), stem='CaiXiHui-Online-Setup', volume='CaiXiHui Online Setup')
    print(f'Installer app: {app}')
    print(f'Installer DMG: {artifact} ({artifact.stat().st_size / 1024**2:.1f} MB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
