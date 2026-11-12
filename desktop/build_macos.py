"""Build the macOS app bundle and DMG (run on macOS, or by .github/workflows/macos-build.yml).

    python desktop/build_macos.py --clean

The DMG is named ``CaiXiHui-macOS-<arch>.dmg`` (arm64 / x86_64) so both CI matrix legs can upload
to the same release without colliding. Codesigning/notarisation are deliberately not done here:
without an Apple Developer certificate the image is unsigned, and the README says how to open it.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'desktop'
SPEC = DESKTOP / 'caixihui_macos.spec'
DIST = ROOT / 'dist'
WORK = ROOT / 'build' / 'pyinstaller-macos'
ICON_SOURCE = ROOT / 'backend' / 'static' / 'icon.png'


def app_version() -> str:
    """The version the bundle reports: one source, ``backend/services/version.py``."""
    text = (ROOT / 'backend' / 'services' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"^APP_VERSION\s*=\s*'([^']+)'", text, re.MULTILINE)
    return match.group(1) if match else '1.0.0'


def make_icns() -> Path | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    if not ICON_SOURCE.is_file():
        return None
    target = WORK / 'CaiXiHui.icns'
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(ICON_SOURCE).convert('RGBA')
    side = max(image.size)
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    try:
        canvas.save(target, format='ICNS')
    except (OSError, ValueError):
        return None
    return target


def run(command: list[str]) -> None:
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, check=True, cwd=str(ROOT))


def build_dmg(app: Path, arch: str, *, stem: str = 'CaiXiHui', volume: str = 'CaiXiHui') -> Path:
    """Wrap an existing ``.app`` in a DMG named ``<stem>-macOS-<arch>.dmg``.

    ``stem`` lets the macOS online installer reuse this exact staging (ditto + /Applications
    symlink + UDZO) without a second copy of the hdiutil sequence.
    """
    stage = ROOT / 'build' / f'dmg-stage-{stem.lower()}'
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run(['ditto', str(app), str(stage / app.name)])
    os.symlink('/Applications', stage / 'Applications')
    dmg = DIST / f'{stem}-macOS-{arch}.dmg'
    if dmg.exists():
        dmg.unlink()
    run(
        [
            'hdiutil',
            'create',
            '-volname',
            volume,
            '-srcfolder',
            str(stage),
            '-ov',
            '-format',
            'UDZO',
            str(dmg),
        ]
    )
    shutil.rmtree(stage, ignore_errors=True)
    return dmg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build the macOS CaiXiHui.app and DMG')
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        print('this build must run on macOS', file=sys.stderr)
        return 2
    if args.clean:
        shutil.rmtree(DIST / 'CaiXiHui.app', ignore_errors=True)
        for old in DIST.glob('CaiXiHui-macOS-*.dmg'):
            old.unlink(missing_ok=True)
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('CIXI_APP_VERSION', app_version())
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
    app = DIST / 'CaiXiHui.app'
    if not app.is_dir():
        print(f'expected app bundle not found: {app}', file=sys.stderr)
        return 1
    arch = platform.machine() or 'unknown'
    dmg = build_dmg(app, arch)
    size = dmg.stat().st_size / 1024**2
    print(f'App: {app}')
    print(f'DMG: {dmg} ({size:.1f} MB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
