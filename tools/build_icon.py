"""Regenerate ``backend/static/icon.ico`` from ``backend/static/icon.png``.

Two packagers read that ICO: PyInstaller stamps it into ``CaiXiHui.exe`` (``desktop/caixihui.spec``)
and Inno Setup stamps it into ``CaiXiHui-Setup.exe`` (``desktop/installer.iss``). The file that
shipped for a long time was the PNG itself wearing an ``.ico`` name — a browser content-sniffs that
and shows the favicon, Inno refuses it outright (``Resource update error: Icon file is invalid``,
measured) and PyInstaller copies the invalid bytes into the exe without complaining, which is the
worse of the two because the exe then looks fine until something tries to read its icon.

So the ICO is generated rather than renamed. Run it after changing the art:

    .venv/Scripts/python.exe tools/build_icon.py

The byte shape of the result is pinned by ``tests/unit/desktop/test_desktop_packaging.py``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / 'backend' / 'static' / 'icon.png'
TARGET = REPO_ROOT / 'backend' / 'static' / 'icon.ico'

# 256 is the largest entry the ICO format allows; 16/24/32/48 are the sizes Windows actually picks
# (taskbar, desktop, explorer list/details, and the small title-bar icon).
SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER = 256


def _square(im: Image.Image) -> Image.Image:
    """Pad the art onto a transparent square canvas instead of stretching it.

    The source art is 127x128, so rescaling straight to a square icon skews every frame by a pixel;
    padding keeps the drawing's proportions at every size.
    """
    side = max(im.size)
    canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    return canvas


def build(source: Path = SOURCE, target: Path = TARGET) -> dict[str, object]:
    """Write a multi-size ICO from the source art and report what went into it."""
    if not source.is_file():
        raise SystemExit(f'source art missing: {source}')
    with Image.open(source) as opened:
        master = _square(opened.convert('RGBA')).resize((MASTER, MASTER), Image.Resampling.LANCZOS)
    master.save(target, format='ICO', sizes=[(size, size) for size in SIZES])
    return {
        'source': source,
        'target': target,
        'bytes': target.stat().st_size,
        'sizes': SIZES,
    }


def main() -> int:
    info = build()
    print(
        f'Wrote {info["target"]} ({info["bytes"] / 1024:.1f} KB) '
        f'with sizes {", ".join(str(size) for size in info["sizes"])}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
