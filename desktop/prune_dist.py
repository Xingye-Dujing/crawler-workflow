"""Remove platform/test payloads PyInstaller collected but this server never reads.

The packaged app is a local Flask server on Windows. It does not drive Linux/macOS
Selenium managers, draw with a GUI Matplotlib backend, or run dependency self-tests, so
those trees are dead weight in the folder users copy around. Every removal is conservative
and matched by exact name; a missing path is skipped rather than guessed at.

Usage: python prune_dist.py <dist/CaiXiHui>
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

#: Directories under the PyInstaller ``_internal`` folder that are never used at run time.
DEAD_DIRS = (
    'selenium/webdriver/common/linux',
    'selenium/webdriver/common/macos',
    'matplotlib/mpl-data/sample_data',
    'matplotlib/tests',
    'numpy/tests',
    'scipy/tests',
    'sklearn/tests',
    'pandas/tests',
)

#: Individual files PyInstaller may keep even when tkinter is excluded.
DEAD_FILES = (
    '_tkinter.pyd',
    'tcl86t.dll',
    'tk86t.dll',
)

#: Runtime state a verification run leaves beside the exe, cleared before the folder is zipped.
#: Shipping it would hand every user the maintainer's ``runs.db``, datasets and saved logins
#: (``data/cookies/*`` is a second device for that account), and the launcher's own
#: existing-data rule would then keep that folder as the user's data home for good.
USER_STATE_DIRS = ('data', 'logs', 'mplconfig')
USER_STATE_FILES = ('instance.json', 'startup_error.log')


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def _remove(path: Path) -> int:
    if not path.exists():
        return 0
    freed = _size(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return freed


def prune(dist: Path) -> list[tuple[str, int]]:
    internal = dist / '_internal'
    removed = []
    for relative in DEAD_DIRS:
        target = internal / relative
        freed = _remove(target)
        if freed:
            removed.append((relative, freed))
    for name in DEAD_FILES:
        target = internal / name
        freed = _remove(target)
        if freed:
            removed.append((name, freed))
    # Tcl/Tk data lives in sibling directories; remove only if present.
    for relative in ('tcl', 'tk', 'tcl8', 'tk8'):
        freed = _remove(internal / relative)
        if freed:
            removed.append((relative, freed))
    removed.extend(strip_user_state(dist))
    return removed


def strip_user_state(dist: Path) -> list[tuple[str, int]]:
    """Delete the run state a test launch left in the delivery folder, nothing else.

    ``portable.txt`` and ``drivers/`` are the user's choices and are never touched.
    """
    removed = []
    for name in USER_STATE_DIRS:
        freed = _remove(dist / name)
        if freed:
            removed.append((name, freed))
    for name in USER_STATE_FILES:
        freed = _remove(dist / name)
        if freed:
            removed.append((name, freed))
    return removed


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: python prune_dist.py <dist/CaiXiHui>', file=sys.stderr)
        return 2
    dist = Path(argv[1])
    if not (dist / '_internal').is_dir():
        print(f'not an onedir build: {dist}', file=sys.stderr)
        return 2
    before = _size(dist)
    removed = prune(dist)
    after = _size(dist)
    for name, freed in removed:
        print(f'removed {name}: {freed / 1024 / 1024:.1f} MB')
    print(f'pruned {sum(item[1] for item in removed) / 1024 / 1024:.1f} MB; folder now {after / 1024 / 1024:.1f} MB')
    if before < after:  # impossible, but a silent negative delta would hide a bug
        print('prune unexpectedly grew the folder', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
