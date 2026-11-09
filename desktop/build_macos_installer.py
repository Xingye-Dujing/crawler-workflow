"""Build the macOS *online installer* (.app + DMG) around an already-built application DMG.

    python desktop/build_macos_installer.py --app-dmg dist/CaiXiHui-macOS-arm64.dmg

The installer itself is a small PyInstaller ``.app`` (the shared page + component core, no analysis
stack). Its catalogue is generated HERE, because only this step knows the SHA-256 and size of the
application DMG it is about to publish; the checked-in catalogue cannot name bytes that do not exist
yet. Chrome, chromedriver and Node entries are copied from the checked-in catalogue unchanged.

Run on macOS, or by ``.github/workflows/macos-build.yml`` immediately after ``build_macos.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
CATALOG = ROOT / 'backend' / 'services' / 'components' / 'default_catalog.json'
DIST = ROOT / 'dist'
WORK = ROOT / 'build' / 'pyinstaller-macos-installer'
CATALOG_WORK = ROOT / 'build' / 'macos-installer-catalog'
APP_BINARY = 'CaiXiHui.app/Contents/MacOS/CaiXiHui'
REPOSITORY = 'Xingye-Dujing/crawler-workflow'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


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


def build_catalog(dmg: Path, arch: str, release_tag: str, base: Path = CATALOG) -> dict:
    """The checked-in catalogue plus the one asset that describes the app DMG built right now."""
    payload = json.loads(base.read_text(encoding='utf-8'))
    key = f'darwin-{asset_key(arch)}'
    url = f'https://github.com/{REPOSITORY}/releases/download/{release_tag}/CaiXiHui-macOS-{artifact_arch(arch)}.dmg'
    payload['components']['app']['platforms'][key] = {
        'archive': 'dmg',
        'install_as': 'app',
        'verify': [APP_BINARY],
        'sha256': sha256(dmg),
        'size': dmg.stat().st_size,
        'urls': [url],
    }
    return payload


def run(command: list[str]) -> None:
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, check=True, cwd=str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build the macOS online installer app and DMG')
    parser.add_argument('--app-dmg', required=True, help='the application DMG this installer downloads')
    parser.add_argument('--release-tag', default='exe-2026-11')
    parser.add_argument('--arch', default=platform.machine() or 'arm64')
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        print('this build must run on macOS', file=sys.stderr)
        return 2
    dmg = Path(args.app_dmg)
    if not dmg.is_file():
        print(f'application DMG not found: {dmg}', file=sys.stderr)
        return 1
    if args.clean:
        shutil.rmtree(DIST / 'CaiXiHui-Online-Setup.app', ignore_errors=True)
        for old in DIST.glob('CaiXiHui-Online-Setup-macOS-*.dmg'):
            old.unlink(missing_ok=True)
        shutil.rmtree(WORK, ignore_errors=True)
        shutil.rmtree(CATALOG_WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    CATALOG_WORK.mkdir(parents=True, exist_ok=True)
    catalog = build_catalog(dmg, args.arch, args.release_tag)
    catalog_path = CATALOG_WORK / 'default_catalog.json'
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.environ['CIXI_INSTALLER_CATALOG'] = str(catalog_path)

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
