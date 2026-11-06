# PyInstaller spec for the online installer (one small windowed exe).
#
# The bootstrap imports services.components through importlib so the same code the app runs is what
# the installer runs; hiddenimports makes PyInstaller follow that indirection. UPX is deliberately
# off: the installer is the first file SmartScreen sees, and an uncompressed ~15 MB exe is a much
# weaker false-positive signal than a packed one.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # desktop/bootstrap -> repo root
BACKEND = ROOT / 'backend'
CATALOG = BACKEND / 'services' / 'components' / 'default_catalog.json'
ICON = BACKEND / 'static' / 'icon.ico'

a = Analysis(
    [str(ROOT / 'desktop' / 'bootstrap' / 'installer.py')],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[
        (str(CATALOG), 'services/components'),
        (str(ROOT / 'desktop' / 'bootstrap' / 'plan.py'), '.'),
    ],
    hiddenimports=[
        'services.components.catalog',
        'services.components.manifest',
        'services.components.fetch',
        'services.components.archive',
        'services.components.install',
        'services.components.paths',
        'core.machine',
        'core.procs',
        'core.config',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter.test',
        'test',
        'tests',
        'pandas',
        'numpy',
        'scipy',
        'sklearn',
        'matplotlib',
        'PIL',
        'openpyxl',
        'jieba',
        'yaml',
        'requests',
        'sessions',
        'analyzers',
        'api',
        'engine',
        'nodes',
        'scheduling',
        'capabilities',
        'crawlers',
        'tzdata',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CaiXiHui-Online-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=str(ICON) if ICON.exists() else None,
)
