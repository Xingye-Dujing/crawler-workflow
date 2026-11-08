# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the macOS desktop app (``CaiXiHui.app`` + DMG in CI).

The Windows spec (``caixihui.spec``) is onedir because the app is 160 MB and onefile would unpack
it on every launch. The macOS release is a .app bundle built by ``desktop/build_macos.py``; the
window is pywebview's Cocoa backend over the same loopback Flask server, and WebView2/pythonnet
are Windows-only and never collected here.
"""

import glob
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
BACKEND = ROOT / 'backend'
if str(SPEC_DIR) not in sys.path:
    sys.path.insert(0, str(SPEC_DIR))
from frozen_modules import package_module_names

datas = [
    (str(BACKEND / 'static'), 'static'),
    (str(BACKEND / 'services' / 'components' / 'default_catalog.json'), 'services/components'),
    (str(ROOT / 'samples'), 'samples'),
    (str(ROOT / 'README.md'), '.'),
    (str(ROOT / 'data' / 'workflows' / '文献计量演示：CNKI 与 CSSCI 知识图谱.json'), 'seed/workflows'),
]
for model in sorted(glob.glob(str(ROOT / 'data' / 'models' / '*.pkl'))):
    datas.append((model, 'seed/models'))

datas += collect_data_files('jieba')
datas += collect_data_files('snownlp')

binaries = []
try:
    import selenium

    manager = Path(selenium.__file__).parent / 'webdriver' / 'common' / 'macos' / 'selenium-manager'
    if manager.is_file():
        binaries.append((str(manager), 'selenium/webdriver/common/macos'))
except Exception:
    pass

hiddenimports = []
for package in (
    'api',
    'crawlers',
    'services',
    'analyzers',
    'core',
    'capabilities',
    'engine',
    'nodes',
    'sessions',
    'scheduling',
    'i18n_catalog',
    'runtime',
):
    hiddenimports += package_module_names(BACKEND, package)
hiddenimports += [
    'core.config',
    'i18n',
    'runtime.state',
    'runtime.stores',
    'runtime.settings',
    'scheduling.clock',
    'sessions.profiles',
    'bert_pack',
    'webview.platforms.cocoa',
    'objc',
    'Foundation',
    'AppKit',
    'WebKit',
    'PyObjCTools.AppHelper',
]

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
    'matplotlib.backends.backend_tkagg',
    'matplotlib.backends._tkagg',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_wx',
    'matplotlib.backends.backend_gtk3',
    'matplotlib.backends.backend_gtk3agg',
]

a = Analysis(
    [str(SPEC_DIR / 'macos_entry.py')],
    pathex=[str(BACKEND), str(SPEC_DIR)],
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
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='CaiXiHui',
)

app = BUNDLE(
    coll,
    name='CaiXiHui.app',
    icon=os.environ.get('CIXI_MACOS_ICON') or None,
    bundle_identifier='com.caixihui.desktop',
    info_plist={
        'CFBundleDisplayName': '采析绘',
        'CFBundleName': 'CaiXiHui',
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
    },
)
