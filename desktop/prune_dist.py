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
    # jieba's LAC tagger model (13 MB) is only reachable through ``cut(..., use_paddle=True)``,
    # which requires paddle to be installed (jieba/__init__.py:301-305, jieba/posseg/__init__.py
    # :281-285). No analyzer passes that flag and paddle is not a dependency of this project.
    'jieba/lac_small',
)

#: Package DATA files copied by ``collect_data_files`` that this app never opens. Each one is
#: matched by exact name, because the sibling that IS read has an almost identical name.
DEAD_PACKAGE_FILES = (
    # snownlp stores its models twice: ``utils/tnt.py`` and ``classification/bayes.py`` both
    # append ``.3`` to the path when running on Python 3, so the extension-less file is the
    # Python-2 copy. The build is Python 3.11, and each ``*.marshal`` loads fine without it.
    'snownlp/seg/seg.marshal',
    'snownlp/tag/tag.marshal',
    'snownlp/sentiment/sentiment.marshal',
    # Training corpora, read only by snownlp's ``train()`` entry points. This app scores text
    # with the shipped models (``SnowNLP(text).sentiments``) and never retrains them; without
    # the marshal file the loader raises on import, without these it simply never learns a new
    # model — which is the behaviour we ship.
    'snownlp/seg/data.txt',
    'snownlp/tag/199801.txt',
    'snownlp/sentiment/neg.txt',
    'snownlp/sentiment/pos.txt',
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
USER_STATE_DIRS = ('data', 'logs', 'mplconfig', 'tmp')
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
    for relative in DEAD_PACKAGE_FILES:
        freed = _remove(internal / relative)
        if freed:
            removed.append((relative, freed))
    removed.extend(_strip_font_cache_dirs(dist))
    # Tcl/Tk data lives in sibling directories; remove only if present.
    for relative in ('tcl', 'tk', 'tcl8', 'tk8'):
        freed = _remove(internal / relative)
        if freed:
            removed.append((relative, freed))
    removed.extend(strip_user_state(dist))
    return removed


def _strip_font_cache_dirs(dist: Path) -> list[tuple[str, int]]:
    """Delete scratch directories an older build left beside the exe, and nothing else.

    Two shapes are removed: matplotlib's font-cache folder (it holds a ``fontlist-*.json``) and an
    **empty** ``tmp*`` folder. Both were measured in ``dist/CaiXiHui`` — ``tmp5ttn736f/``,
    ``tmpciehu6a_/`` with a fontlist, and then four empty ``tmp…`` directories after one launch each,
    because ``tempfile`` falls back to the current directory when ``%TEMP%`` is denied and the
    launcher's cwd is the install folder. The launcher now points TMP/TEMP/TMPDIR at
    ``<data root>/tmp``, so these are the residue of earlier builds; a ``tmp*`` folder with anything
    in it that is not a font cache is not ours to delete.
    """
    removed = []
    for holder in sorted(dist.glob('tmp*')):
        if not holder.is_dir():
            continue
        contents = list(holder.iterdir())
        is_font_cache = any(path.name.startswith('fontlist-') for path in contents)
        if contents and not is_font_cache:
            continue
        freed = _remove(holder)
        if freed or not contents:
            removed.append((holder.name, freed))
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
