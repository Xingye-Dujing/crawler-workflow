"""Regenerate the application art from ``backend/static/icon.jpg``.

Two packagers read the ICO: PyInstaller stamps it into ``CaiXiHui.exe`` (``desktop/caixihui.spec``)
and Inno Setup stamps it into ``CaiXiHui-Setup.exe`` (``desktop/installer.iss``). The PNG is the
master the macOS build turns into an ``.icns``. Both are generated from the current photo, never
renamed from it:

* ``icon.png`` is the processed master (circular, 1024×1024, transparent corners);
* ``icon.ico`` is a multi-size circular icon built from that master.

The file that shipped for a long time was the PNG itself wearing an ``.ico`` name — a browser
content-sniffs that and shows the favicon, Inno refuses it outright (``Resource update error: Icon
file is invalid``, measured) and PyInstaller copies the invalid bytes into the exe without
complaining, which is the worst of the three.

Run it after replacing ``icon.jpg``:

    .venv/Scripts/python.exe tools/build_icon.py

The ICO's byte shape and the master's PNG header are pinned by
``tests/unit/desktop/test_desktop_packaging.py``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / 'backend' / 'static'
ART = STATIC / 'icon.jpg'
SOURCE = STATIC / 'icon.png'
TARGET = STATIC / 'icon.ico'

# 256 is the largest entry the ICO format allows; 16/24/32/48 are the sizes Windows actually picks
# (taskbar, desktop, explorer list/details, and the small title-bar icon).
SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER = 256

#: The processed PNG keeps enough pixels for a Retina .icns; the ICO scales down from it.
PNG_MASTER = 1024


def _square(im: Image.Image) -> Image.Image:
    """Pad the art onto a transparent square canvas instead of stretching it.

    The photo is already square, but an icon source may not be (the original art was 127×128), and
    rescaling straight to a square skews every frame by a pixel. Padding keeps the drawing's
    proportions at every size.
    """
    side = max(im.size)
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas


def _circle(im: Image.Image, size: int) -> Image.Image:
    """Square art, then a circular alpha mask (transparent corners), supersampled for a smooth rim.

    Every consumer — the Windows ICO frames, the macOS .icns and the browser favicon — is built from
    this one shape, so the icon cannot be round in one place and square in another. A 4× mask keeps
    the 16 px frame from turning into a jagged octagon.
    """
    master = _square(im).resize((size, size), Image.Resampling.LANCZOS)
    big = size * 4
    mask = Image.new('L', (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    master.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
    return master


def prepare(source: Path = ART, target: Path = SOURCE) -> Path:
    """Write the circular 1024×1024 PNG master from the raw art (EXIF orientation honoured)."""
    if not source.is_file():
        raise SystemExit(f'source art missing: {source}')
    with Image.open(source) as opened:
        master = _circle(ImageOps.exif_transpose(opened).convert('RGBA'), PNG_MASTER)
    target.parent.mkdir(parents=True, exist_ok=True)
    master.save(target, format='PNG', optimize=True)
    return target


def build(source: Path = SOURCE, target: Path = TARGET) -> dict[str, object]:
    """Write a multi-size circular ICO from the PNG master and report what went into it."""
    if not source.is_file():
        raise SystemExit(f'source art missing: {source}')
    with Image.open(source) as opened:
        master = _circle(opened.convert('RGBA'), MASTER)
    master.save(target, format='ICO', sizes=[(size, size) for size in SIZES])
    return {
        'source': source,
        'target': target,
        'bytes': target.stat().st_size,
        'sizes': SIZES,
    }


def main() -> int:
    source = ART if ART.is_file() else SOURCE
    if source.suffix.lower() != '.png':
        prepare(source, SOURCE)
        print(f'Wrote {SOURCE} ({SOURCE.stat().st_size / 1024:.1f} KB, {PNG_MASTER}×{PNG_MASTER})')
    info = build(SOURCE, TARGET)
    print(
        f'Wrote {info["target"]} ({info["bytes"] / 1024:.1f} KB) '
        f'with sizes {", ".join(str(size) for size in info["sizes"])}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
