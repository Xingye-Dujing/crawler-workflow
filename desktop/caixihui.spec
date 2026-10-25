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

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
BACKEND = ROOT / 'backend'
# UPX shrinks many .pyd/.dll files, but packed binaries attract more antivirus
# false positives. It is opt-in (`build_windows.ps1 -Upx`) and the Python/VC runtime
# DLLs stay uncompressed so the bootloader can always start.
USE_UPX = os.environ.get('CAIXIHUI_UPX') == '1'
UPX_EXCLUDE = [
    'python311.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'msvcp140.dll',
    'ucrtbase.dll',
    'api-ms-win-*.dll',
]

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

hiddenimports = []
for package in ('api', 'crawlers', 'services', 'analyzers', 'utils'):
    hiddenimports += collect_submodules(package)
hiddenimports += [
    'config',
    'i18n',
    'state',
    'stores',
    'settings_store',
    'scheduler',
    'browser_profiles',
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
    upx=USE_UPX,
    upx_exclude=UPX_EXCLUDE,
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
    upx=USE_UPX,
    upx_exclude=UPX_EXCLUDE,
    name='CaiXiHui',
)
