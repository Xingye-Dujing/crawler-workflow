# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for the Windows desktop build.

The build is deliberately a FOLDER, not a one-file exe: one-file unpacks every library
to %TEMP% on each launch, starts slowly, and is the shape antivirus heuristics dislike.
The folder is compressed once into a zip by ``build_windows.ps1`` for distribution.

Size is controlled by building in ``.venv-build`` (runtime requirements only, no torch /
transformers / pyarrow / mitmproxy) and by excluding optional stacks here. See
``requirements-runtime.txt`` and ``README.md``.
"""

import glob
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
BACKEND = ROOT / 'backend'
# UPX is NOT applied here: PyInstaller compresses nothing and barely says so when the tool is
# not on PATH, which would make the shipped folder's size a guess. `build_windows.ps1` runs
# `compress_dist.py` after the prune step — it names the missing tool, verifies each file with
# `upx -t` and restores anything it cannot prove. See desktop/compress_dist.py.

datas = [
    # Flask serves index.html/JS/CSS itself; world.json is read directly by biblio_geo.
    (str(BACKEND / 'static'), 'static'),
    (str(ROOT / 'samples'), 'samples'),
    (str(ROOT / 'README.md'), '.'),
    # First-run assets the launcher copies into the user's data root (never overwritten).
    (str(ROOT / 'data' / 'workflows' / '文献计量演示：CNKI 与 CSSCI 知识图谱.json'), 'seed/workflows'),
]
for model in sorted(glob.glob(str(ROOT / 'data' / 'models' / '*.pkl'))):
    datas.append((model, 'seed/models'))

# jieba's dictionary and snownlp's small model files are package DATA, not Python imports;
# PyInstaller's generic hooks do not always see them.
datas += collect_data_files('jieba')
datas += collect_data_files('snownlp')

binaries = []
# Selenium Manager is the automatic driver resolver. PyInstaller's selenium hook normally
# carries it, but the path is cheap to state explicitly and its absence is a first-crawl
# failure that only appears on a clean machine.
try:
    import selenium

    manager = Path(selenium.__file__).parent / 'webdriver' / 'common' / 'windows' / 'selenium-manager.exe'
    if manager.is_file():
        binaries.append((str(manager), 'selenium/webdriver/common/windows'))
except Exception:
    pass

# A portable chromedriver can be dropped into drivers/ before building. We never download
# one at build time because the correct version is the one matching the USER's Chrome.
for driver in glob.glob(str(ROOT / 'drivers' / 'chromedriver.exe')):
    binaries.append((driver, 'drivers'))

# onnxruntime is the runtime the packaged app answers bert nodes with, and it loads its C++
# backend as a DLL beside its own .pyd. Stated explicitly because a missing piece there is not a
# boot failure — the import is lazy — it is a refusal on the first bert run on the user's machine.
try:
    binaries += collect_dynamic_libs('onnxruntime')
except Exception:
    pass

hiddenimports = []
# Every top-level backend package is named here, not left to static analysis: ``nodes/registry.py``
# loads its plugins with ``importlib.import_module('nodes.executors')`` — a string. Today PyInstaller
# happens to follow that literal, but a package that is only ever reached by name is one refactor away
# from shipping an exe whose node types simply are not there. ``tests/unit/test_desktop_packaging.py``
# fails if a package appears under backend/ without being added here (and if one is named here and gone).
for package in ('api', 'crawlers', 'services', 'analyzers', 'core', 'engine', 'nodes', 'sessions', 'scheduling'):
    hiddenimports += collect_submodules(package)
hiddenimports += [
    'config',
    'i18n',
    'state',
    'stores',
    'settings_store',
    'scheduling.clock',
    'sessions.profiles',
    # Imported inside ``main()`` (the launcher keeps its boot path import-light), so state it
    # rather than trusting the analysis to reach a function-level import in the entry script.
    'bert_pack',
]

# Optional/heavy stacks that are NOT part of the packaged runtime. The app already
# degrades without them and prints which method actually ran (see AGENTS.md).
excludes = [
    'torch',
    'torchvision',
    'torchaudio',
    'transformers',
    'sentence_transformers',
    'pyarrow',
    'mitmproxy',
    'mitmproxy_rs',
    'uiautomation',
    'tkinter',
    '_tkinter',
    'PyQt5',
    'PyQt6',
    'PySide2',
    'PySide6',
    'IPython',
    'jupyter',
    'notebook',
    'pytest',
    'pytest_cov',
    'pytest_socket',
    'pytest_timeout',
    'ruff',
    'pylint',
    'webdriver_manager',
    'tabulate',
    # Matplotlib GUI backends: the server only saves figures with Agg.
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends._tkagg',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_wx',
    'matplotlib.backends.backend_gtk3',
    'matplotlib.backends.backend_gtk3agg',
    'matplotlib.backends.backend_macosx',
    'matplotlib.backends.backend_nbagg',
    'matplotlib.backends.backend_webagg',
    'matplotlib.backends.backend_webagg_core',
    # Test modules are never needed at run time.
    'pandas.tests',
    'numpy.tests',
    'scipy.tests',
    'sklearn.tests',
    'matplotlib.tests',
]

a = Analysis(
    [str(SPEC_DIR / 'desktop_entry.py')],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CaiXiHui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(BACKEND / 'static' / 'icon.ico'),
    version=str(SPEC_DIR / 'version_info.txt'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='CaiXiHui',
)
