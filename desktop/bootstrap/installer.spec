# PyInstaller spec for the online installer (one small windowed exe).
#
# The bootstrap imports services.components through importlib so the same code the app runs is what
# the installer runs; hiddenimports makes PyInstaller follow that indirection. The page is served
# from 127.0.0.1 and shown in this process's own WebView2 window (pywebview); no Qt/Tcl/Tk is
# bundled, which is what keeps the download small. UPX is deliberately off here too: this is the
# first file SmartScreen sees, and packing it would trade a few MB for more false positives.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # desktop/bootstrap -> repo root
BACKEND = ROOT / 'backend'
CATALOG = BACKEND / 'services' / 'components' / 'default_catalog.json'
ICON = BACKEND / 'static' / 'icon.ico'
PAGE = ROOT / 'desktop' / 'bootstrap' / 'installer_page.html'
PAGE_JS = ROOT / 'desktop' / 'bootstrap' / 'installer_page.js'
WINDOW = ROOT / 'desktop' / 'native_window.py'

datas = [
    (str(CATALOG), 'services/components'),
    (str(ROOT / 'desktop' / 'bootstrap' / 'plan.py'), '.'),
    (str(ROOT / 'desktop' / 'bootstrap' / 'ui_theme.py'), '.'),
    # The page, its script and the window/tab icon; a onefile bundle resolves them through
    # sys._MEIPASS, i.e. the root this copies them to.
    (str(PAGE), '.'),
    (str(PAGE_JS), '.'),
    (str(ICON), '.'),
    # The shared window host is loaded by path, so the analysis cannot see it.
    (str(WINDOW), '.'),
]
# pythonnet 3.x loads Python.Runtime.dll from ``pythonnet/runtime``; the upstream hook copies it to
# the bundle root instead, which is not where the package looks. Without this copy the process
# starts and the window never appears.
try:
    import pythonnet

    _runtime = Path(pythonnet.__file__).parent / 'runtime'
    for _file in sorted(_runtime.glob('*')):
        datas.append((str(_file), 'pythonnet/runtime'))
except Exception:
    pass

a = Analysis(
    [str(ROOT / 'desktop' / 'bootstrap' / 'installer.py')],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # pywebview + pythonnet: the window is Edge WebView2 hosted in this process. The upstream
        # PyInstaller hooks collect webview/lib and clr_loader's native parts; pythonnet 3.x loads
        # Python.Runtime.dll from ``pythonnet/runtime``, which the datas block below restores.
        'webview',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'clr',
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
        # No GUI toolkit, no analysis stack, no web client: the installer is a local HTTP server
        # plus the component core. Excluding tkinter is what removes Tcl/Tk (about 9 MB).
        'tkinter',
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
        # No database and no decimal arithmetic anywhere in this program: sqlite3.dll alone is
        # 1.5 MB, and the installer is what a user waits on before anything is installed.
        'sqlite3',
        'decimal',
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
    # A onefile normally unpacks into %TEMP%. On a machine where endpoint protection denies that
    # folder (measured on this build box: a trivial onefile died with “Could not create temporary
    # directory”), the installer would fail before its first window. Unpacking beside the exe —
    # which a double-click makes the current directory — uses the folder the user downloaded to;
    # PyInstaller removes it again on exit.
    runtime_tmpdir='.',
    # A desktop program: the page lives in a WebView2 window created by this process. A failure
    # before that window exists is reported by a native message box and installer.log.
    console=False,
    icon=str(ICON) if ICON.exists() else None,
)
