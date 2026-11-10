"""The online installer: choose a folder and components, download from domestic mirrors, launch.

The page is served on ``127.0.0.1`` and shown in this process's own WebView2 window
(``desktop/native_window.py``), not in a browser and not behind a console: the application is a
web UI, so the installer wears the SAME design language for the cost of a few kilobytes of CSS
instead of shipping a GUI toolkit. The exe stays small (stdlib server + the component core), which
is what "小而精" asks for, and the page is generated from the application's own tokens
(``backend/static/css/base.css``).

It is deliberately a Windows desktop tool: it needs a folder picker (``SHBrowseForFolderW``) and
PyInstaller. Download, verification, extraction and the environment report are the same modules the
running app uses, so the installer cannot disagree with the app about what is installed.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

#: The exe is windowed, but the packaged app's own doctor report is a child process; the report is
#: read with this timeout (a live Ollama answers slowly).
DOCTOR_TIMEOUT = 90


def asset_dir() -> Path:
    bundled = getattr(sys, '_MEIPASS', None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parent


def icon_path() -> Path:
    candidates = (asset_dir() / 'icon.ico', Path(__file__).resolve().parents[2] / 'backend' / 'static' / 'icon.ico')
    return next((item for item in candidates if item.exists()), candidates[0])


def log_line(text: str) -> None:
    """Append one line to the diagnostic log (and echo it only where something is listening).

    The exe is windowed, so ``stdout`` is normally ``None``; the file copy is the record that
    survives a failed window. Destinations, best first: an explicit test path, the user's local
    app data, the exe's own folder, then the system temp.
    """
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    if sys.stdout is not None:
        with contextlib.suppress(OSError, ValueError):
            print(f'{stamp} {text}', flush=True)
    line = f'{stamp} {text}\n'
    explicit = str(os.environ.get('CIXI_INSTALLER_LOG') or '').strip()
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if sys.platform == 'darwin':
        candidates.append(Path.home() / 'Library' / 'Logs' / 'CaiXiHui' / 'installer.log')
    else:
        local = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        candidates.append(Path(local) / 'CaiXiHui' / 'installer.log')
    candidates.append(Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent / 'installer.log')
    with contextlib.suppress(Exception):
        import tempfile

        candidates.append(Path(tempfile.gettempdir()) / 'CaiXiHui-installer.log')
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as handle:
                handle.write(line)
            return
        except OSError:
            continue


def _backend_on_path() -> None:
    """Make ``services.components`` importable without importing the application's package root.

    ``backend/services/__init__.py`` exports CookieManager/StatsService/WorkflowManager, which pull
    the whole analysis stack. The installer only needs the component core, so a synthetic package
    object is put in ``sys.modules`` first: importing the subpackage then skips that eager root.
    """
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    candidates = [
        bundle / 'backend',
        bundle,
        Path(__file__).resolve().parents[2] / 'backend',
        Path(__file__).resolve().parents[1] / 'backend',
    ]
    backend = next((item for item in candidates if (item / 'services' / 'components').is_dir()), None)
    if backend is None:
        return
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    import types

    if 'services' not in sys.modules:
        package = types.ModuleType('services')
        package.__path__ = [str(backend / 'services')]
        sys.modules['services'] = package
    if 'services.components' not in sys.modules:
        component = types.ModuleType('services.components')
        component.__path__ = [str(backend / 'services' / 'components')]
        sys.modules['services.components'] = component


_backend_on_path()

_CATALOG = importlib.import_module('services.components.catalog')
_INSTALL = importlib.import_module('services.components.install')
_PLAN_SPEC = importlib.util.spec_from_file_location('installer_plan', Path(__file__).with_name('plan.py'))
assert _PLAN_SPEC and _PLAN_SPEC.loader
_PLAN = importlib.util.module_from_spec(_PLAN_SPEC)
_PLAN_SPEC.loader.exec_module(_PLAN)
# Loaded by path, like the plan: this module is a script in both a source run and a onefile
# bundle, and a plain ``import ui_theme`` would need the script directory on sys.path in the test
# harness (where it is not).
_THEME_SPEC = importlib.util.spec_from_file_location('installer_theme', Path(__file__).with_name('ui_theme.py'))
assert _THEME_SPEC and _THEME_SPEC.loader
ui_theme = importlib.util.module_from_spec(_THEME_SPEC)
_THEME_SPEC.loader.exec_module(ui_theme)
TEXT = ui_theme.TEXT
STATE_LABEL = ui_theme.STATE_LABEL

#: The BERT pack placement module is a script too (it loads ``desktop/bert_pack.py`` by path), so
#: it is loaded explicitly rather than imported. The onefile bundle copies both files beside this.
_BERT_SPEC = importlib.util.spec_from_file_location(
    'installer_bert_install', Path(__file__).with_name('bert_install.py')
)
assert _BERT_SPEC and _BERT_SPEC.loader
_BERT = importlib.util.module_from_spec(_BERT_SPEC)
_BERT_SPEC.loader.exec_module(_BERT)
BertPackError = _BERT.BertPackError
bert_pack_problem = _BERT.pack_problem
install_bert_pack = _BERT.install


def models_registry_label(models: str | Path, install_root: str | Path) -> str:
    """How ``model_registry.json`` names the chosen folder.

    A folder inside the install root is written relative to ``app/`` so moving the installation keeps
    working; a folder elsewhere (the default is under the data root) is absolute — there is no stable
    relative answer across drives/trees, and the registry is machine-local user data.
    """
    resolved = Path(models).expanduser().resolve()
    try:
        resolved.relative_to(Path(install_root).resolve())
    except ValueError:
        return resolved.as_posix()
    app_dir = Path(install_root).resolve() / 'app'
    return Path(os.path.relpath(resolved, app_dir)).as_posix()


def _load_window_module():
    """The shared WebView2 host, loaded by path like the plan and the theme.

    In a source checkout it sits one level above ``bootstrap/``; in the onefile bundle the spec
    copies it beside ``installer.py`` (``sys._MEIPASS``). Both are tried, in that order.
    """
    candidates = [asset_dir() / 'native_window.py', Path(__file__).resolve().parents[1] / 'native_window.py']
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise ImportError('native_window.py is missing from the installer bundle')
    spec = importlib.util.spec_from_file_location('installer_window', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


native_window = _load_window_module()

Catalog = _CATALOG.Catalog
CatalogError = _CATALOG.CatalogError
load_catalog = _CATALOG.load_catalog
_DOWNLOAD = importlib.import_module('services.components.fetch')
DownloadError = _DOWNLOAD.DownloadError
_MANIFEST = importlib.import_module('services.components.manifest')
ManifestError = _MANIFEST.ManifestError
InstallError = _INSTALL.InstallError
install_component = _INSTALL.install_component
download_asset = _DOWNLOAD.download_asset
_PROC = importlib.import_module('core.procs')
chosen_ids = _PLAN.chosen_ids
default_data_root = _PLAN.default_data_root
default_root = _PLAN.default_root
free_space = _PLAN.free_space
human_size = _PLAN.human_size
preset_choices = _PLAN.preset_choices


def pick_folder(title: str) -> str:
    """The native Windows folder picker, without a GUI toolkit in the bundle.

    ``SHBrowseForFolderW`` is an OS dialog: it costs nothing to ship, and the installer only needs
    a path (a browser cannot hand one over). Cancelled or unsupported answers are ``''``.
    """
    if os.name != 'nt':
        return ''
    import ctypes
    from ctypes import wintypes

    # shellapi.h's BIF_* flags; locals, so the naming rule can stay lowercase.
    return_only_fsdirs = 0x00000001
    edit_box = 0x00000010
    new_dialog_style = 0x00000040

    class BrowseInfo(ctypes.Structure):
        _fields_ = [
            ('hwndOwner', wintypes.HWND),
            ('pidlRoot', ctypes.c_void_p),
            # A buffer, not a str: declaring LPWSTR made ctypes reject the create_unicode_buffer
            # below (c_wchar_Array is not c_wchar_p) before the dialog ever opened.
            ('pszDisplayName', ctypes.c_void_p),
            ('lpszTitle', wintypes.LPCWSTR),
            ('ulFlags', wintypes.UINT),
            ('lpfn', ctypes.c_void_p),
            ('lParam', wintypes.LPARAM),
            ('iImage', ctypes.c_int),
        ]

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    # A request handler runs on its own thread; Shell dialogs want an initialized apartment.
    # A thread already in another mode is fine (RPC_E_CHANGED_MODE) — it only means "do not
    # uninitialize", not "cannot show a folder picker".
    initialized = False
    with contextlib.suppress(AttributeError, OSError):
        result = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        initialized = result in (0, 1)  # S_OK / S_FALSE
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    # Both parameters are pointers. Declaring the buffer as LPWSTR made ctypes refuse the
    # c_wchar_Array a create_unicode_buffer returns; the buffer is cast to a void pointer instead.
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    display = ctypes.create_unicode_buffer(260)
    user32 = ctypes.windll.user32
    # Owner: this process's own WebView2 window, so the dialog is modal to it and cannot open
    # behind it. The helper below is the second line of defence for a window the shell refuses to
    # treat as the foreground one.
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = native_window.handle() or user32.GetForegroundWindow() or None
    stop_focus = threading.Event()

    def focus_dialog() -> None:
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        pid = os.getpid()

        def visit(hwnd, _lparam):
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            name = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hwnd, name, 32)
            if name.value != '#32770':
                return True
            # Topmost for the dialog's lifetime: a background process cannot always take the
            # foreground, and a picker the user cannot see is worse than one that stays on top.
            user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0003 | 0x0040)
            user32.SetForegroundWindow(hwnd)
            return False

        callback = callback_type(visit)
        for _ in range(25):
            if stop_focus.wait(0.2):
                return
            user32.EnumWindows(callback, 0)

    threading.Thread(target=focus_dialog, daemon=True).start()
    info = BrowseInfo(
        owner,
        None,
        ctypes.cast(display, ctypes.c_void_p),
        title,
        return_only_fsdirs | edit_box | new_dialog_style,
        None,
        0,
        0,
    )
    try:
        item = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not item:
            return ''
        path = ctypes.create_unicode_buffer(260)
        try:
            shell32.SHGetPathFromIDListW(ctypes.c_void_p(item), ctypes.cast(path, ctypes.c_void_p))
        finally:
            ole32.CoTaskMemFree(ctypes.c_void_p(item))
    except (AttributeError, OSError, TypeError, ValueError):
        return ''
    finally:
        stop_focus.set()
        if initialized:
            with contextlib.suppress(AttributeError, OSError):
                ole32.CoUninitialize()
    return path.value or ''


def pick_file(title: str) -> str:
    """The native Windows open-file dialog for the BERT archive; ``''`` when cancelled.

    ``GetOpenFileNameW`` is the shell's own dialog, like the folder picker above: no GUI toolkit in
    the bundle, and the filter starts on the model pack's ``.zip``. The owner is the installer window
    so the dialog cannot open behind it.
    """
    if os.name != 'nt':
        return ''
    import ctypes
    from ctypes import wintypes

    class OpenFileName(ctypes.Structure):
        _fields_ = [
            ('lStructSize', wintypes.DWORD),
            ('hwndOwner', wintypes.HWND),
            ('hInstance', wintypes.HANDLE),
            ('lpstrFilter', wintypes.LPCWSTR),
            ('lpstrCustomFilter', wintypes.LPWSTR),
            ('nMaxCustFilter', wintypes.DWORD),
            ('nFilterIndex', wintypes.DWORD),
            # A buffer, not LPWSTR: ctypes rejects the c_wchar_Array a create_unicode_buffer
            # returns for a c_wchar_p field (the same trap the folder picker documents).
            ('lpstrFile', ctypes.c_void_p),
            ('nMaxFile', wintypes.DWORD),
            ('lpstrFileTitle', ctypes.c_void_p),
            ('nMaxFileTitle', wintypes.DWORD),
            ('lpstrInitialDir', wintypes.LPCWSTR),
            ('lpstrTitle', wintypes.LPCWSTR),
            ('Flags', wintypes.DWORD),
            ('nFileOffset', wintypes.WORD),
            ('nFileExtension', wintypes.WORD),
            ('lpstrDefExt', wintypes.LPCWSTR),
            ('lCustData', wintypes.LPARAM),
            ('lpfnHook', ctypes.c_void_p),
            ('lpTemplateName', wintypes.LPCWSTR),
            ('pvReserved', ctypes.c_void_p),
            ('dwReserved', wintypes.DWORD),
            ('FlagsEx', wintypes.DWORD),
        ]

    file_buffer = ctypes.create_unicode_buffer(32768)
    # OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_NOCHANGEDIR
    flags = 0x00001000 | 0x00000800 | 0x00080000 | 0x00000008
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = native_window.handle() or user32.GetForegroundWindow() or None
    info = OpenFileName(
        ctypes.sizeof(OpenFileName),
        owner,
        None,
        'BERT model pack (*.zip)\0*.zip\0All files (*.*)\0*.*\0\0',
        None,
        0,
        1,
        ctypes.cast(file_buffer, ctypes.c_void_p),
        len(file_buffer),
        None,
        0,
        None,
        title,
        flags,
        0,
        0,
        'zip',
        0,
        None,
        None,
        None,
        0,
        0,
    )
    dialog = ctypes.windll.comdlg32
    dialog.GetOpenFileNameW.argtypes = [ctypes.POINTER(OpenFileName)]
    dialog.GetOpenFileNameW.restype = wintypes.BOOL
    try:
        if not dialog.GetOpenFileNameW(ctypes.byref(info)):
            return ''
    except (AttributeError, OSError, TypeError, ValueError):
        return ''
    return file_buffer.value or ''


def create_shortcut(exe: Path) -> str:
    """Create ``采析绘.lnk`` on this user's Desktop; ``''`` on success or the reason.

    The shortcut is a convenience, never a reason to call a finished install failed. PowerShell's
    ``[Environment]::GetFolderPath('Desktop')`` follows OneDrive/redirection; paths travel in the
    environment, not in the command line, so a Chinese or spaced install folder cannot break the
    quoting. The same name is used by the offline Setup's desktop-icon task.
    """
    if os.name != 'nt':
        return ''
    if not exe.is_file():
        return f'missing {exe}'
    env = dict(os.environ)
    env['CIXI_SHORTCUT_TARGET'] = str(exe)
    env['CIXI_SHORTCUT_NAME'] = '采析绘.lnk'
    env['CIXI_SHORTCUT_DESC'] = '采析绘'
    script = (
        "$ErrorActionPreference='Stop';"
        "$dir=[Environment]::GetFolderPath('Desktop');"
        '$path=Join-Path $dir $env:CIXI_SHORTCUT_NAME;'
        '$shell=New-Object -ComObject WScript.Shell;'
        '$link=$shell.CreateShortcut($path);'
        '$link.TargetPath=$env:CIXI_SHORTCUT_TARGET;'
        '$link.WorkingDirectory=Split-Path -Parent $env:CIXI_SHORTCUT_TARGET;'
        '$link.IconLocation=$env:CIXI_SHORTCUT_TARGET;'
        '$link.Description=$env:CIXI_SHORTCUT_DESC;'
        '$link.Save()'
    )
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script],
            capture_output=True,
            timeout=30,
            check=False,
            env=env,
            **_PROC.popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if result.returncode != 0:
        text = (result.stderr or result.stdout or b'').decode('utf-8', errors='replace').strip()
        return text.splitlines()[-1] if text else f'exit {result.returncode}'
    return ''


class InstallerState:
    """Everything the page may ask about, guarded because the install runs on a thread."""

    #: Whether this platform's packaged app can actually load a BERT pack. Windows ships
    #: onnxruntime; the macOS bundle deliberately does not, so its page hides the path field.
    bert_supported = True

    #: Desktop shortcuts are a Windows shell concept. The macOS app is installed in /Applications
    #: and appears in Launchpad; a checkbox there would do nothing.
    shortcut_supported = True

    def __init__(
        self,
        catalog: Catalog,
        root: str,
        data: str,
        elevated: bool,
    ) -> None:
        self.catalog = catalog
        self.root = str(root)
        self.data = str(data)
        self.elevated = elevated
        self.bert = ''
        self.shortcut = True
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.preset = 'one'
        self.selected = self._preset_ids('one')
        self.job = {
            'state': 'idle',
            'done': 0,
            'total': 100,
            'status_key': '',
            'status_params': {},
            'error': '',
            'log': [],
        }
        self.doctor = {'state': 'idle', 'report': {}}
        self.shutting_down = False

    # ── selections ──────────────────────────────────────────────
    def _downloadable(self) -> list[str]:
        return list(self.catalog.downloadable())

    def _preset_ids(self, preset: str) -> list[str]:
        defaults = [item.id for item in self.catalog.components.values() if item.default]
        choices = preset_choices(preset, defaults, self._downloadable())
        return chosen_ids(choices, self._downloadable())

    def effective(self) -> list[str]:
        requires = {key: list(item.requires) for key, item in self.catalog.components.items()}
        return _PLAN.with_requirements(self.selected, requires, self._downloadable())

    def snapshot(self) -> dict:
        with self.lock:
            selected = set(self.selected)
            effective = self.effective()
            rows = []
            total = 0
            for item in self.catalog.components.values():
                info = item.asset()
                if info is None:
                    rows.append(
                        {
                            'id': item.id,
                            'version': item.version,
                            'summary': item.summary,
                            'downloadable': False,
                            'checked': False,
                            'size': 0,
                            'size_text': '',
                            # A manual entry is detection-only everywhere; a real component with no
                            # asset here simply has no build for this OS (CatBus on macOS).
                            'unavailable': item.kind != 'manual',
                        }
                    )
                    continue
                total += info.size if item.id in effective else 0
                rows.append(
                    {
                        'id': item.id,
                        'version': item.version,
                        'summary': item.summary,
                        'downloadable': True,
                        'checked': item.id in selected,
                        'size': info.size,
                        'size_text': human_size(info.size),
                    }
                )
            return {
                'root': self.root,
                'data': self.data,
                'models': self.models,
                'bert': self.bert,
                'bert_supported': self.bert_supported,
                'shortcut': self.shortcut,
                'shortcut_supported': self.shortcut_supported,
                'preset': self.preset,
                'components': rows,
                # Bytes, not a sentence: the page renders the size in its own language.
                'total': total,
                'job': dict(self.job, log=list(self.job['log'])),
            }

    # ── actions ─────────────────────────────────────────────────
    @property
    def models(self) -> str:
        """The model storage folder follows the data folder, exactly like ``data/`` and ``logs/``.

        The source archive is a separate, optional value (:attr:`bert`); this is only where its
        extracted folders live. Keeping it derived means a user who moves the data folder never has
        a registry pointing at the old drive.
        """
        return str(Path(self.data) / 'bert_models')

    def set_bert(self, path) -> None:
        with self.lock:
            self.bert = str(path or '').strip()

    def set_shortcut(self, enabled) -> None:
        with self.lock:
            self.shortcut = bool(enabled)

    def set_selection(self, ids) -> None:
        if not isinstance(ids, list):
            return
        allowed = set(self._downloadable())
        with self.lock:
            self.selected = [str(item) for item in ids if str(item) in allowed]

    def set_preset(self, preset: str) -> bool:
        if preset not in ('one', 'app'):
            return False
        with self.lock:
            self.preset = preset
            self.selected = self._preset_ids(preset)
        return True

    def _log(self, line: str) -> None:
        with self.lock:
            lines = self.job['log']
            lines.append(line)
            if len(lines) > 200:
                del lines[:-200]

    def _set_job(self, **values) -> None:
        with self.lock:
            self.job.update(values)

    def start(self, root: Path, data: Path) -> None:
        ids = self.effective()
        self.cancel.clear()
        with self.lock:
            self.job = {
                'state': 'running',
                'done': 0,
                'total': 100,
                'status_key': '',
                'status_params': {},
                'error': '',
                'log': [],
            }
        self.root = str(root)
        self.data = str(data)
        threading.Thread(target=self._run_job, args=(ids, root, data), daemon=True).start()

    def _run_job(self, ids: list[str], root: Path, data: Path) -> None:
        total = max(1, len(ids))
        for index, component_id in enumerate(ids):
            if self.cancel.is_set():
                self._set_job(state='cancelled')
                return
            component = self.catalog.get(component_id)
            self._set_job(status_key='installing', status_params={'name': component_id})
            self._set_job(done=int(index / total * 100))
            try:

                def progress(done: int, size: int, start=index) -> None:
                    if size:
                        self._set_job(done=int((start + done / size) / total * 100))

                install_component(self.catalog, component_id, root, progress=progress, cancel=self.cancel.is_set)
            except (InstallError, CatalogError, DownloadError, ManifestError, OSError) as exc:
                # A network failure is a DownloadError, which is not an OSError: without it here the
                # thread died silently and the page sat on "installing" with the button off.
                self._set_job(state='failed', error=str(exc), status_key='')
                return
            self._log(f'{component_id} {component.version} -> {root}')
        if self.bert:
            self._set_job(done=99, status_key='bert_installing', status_params={})
            models = Path(self.models)
            try:
                placed = install_bert_pack(
                    self.bert,
                    root,
                    data,
                    models_dir=models,
                    root_label=models_registry_label(models, root),
                )
            except (BertPackError, OSError, ValueError) as exc:
                self._set_job(state='failed', error=str(exc), status_key='')
                return
            ledger = placed['ledger']
            for name in ledger['added']:
                self._log(f'bert registered: {name}')
            for name in ledger['skipped']:
                self._log(f'bert existing registry entry kept: {name}')
            for name in placed['skipped_folders']:
                self._log(f'bert model folder already present, kept: {name}')
            self._log(f'bert {ledger["packs"]} packs -> {models}')
        if self.shortcut:
            problem = create_shortcut(root / 'app' / 'CaiXiHui.exe')
            if problem:
                self._log(f'shortcut not created: {problem}')
            else:
                self._log('shortcut -> 采析绘.lnk')
        self._write_data_root(root, data)
        self._set_job(done=100, state='done', status_key='done', status_params={})
        self._run_doctor(root, data)

    def _write_data_root(self, root: Path, data: Path) -> None:
        """Tell the application where its data belongs, so a later double-click finds it.

        Written after the app is unpacked (the install replaces ``app/``) and before launch. The
        launcher reads this file before it falls back to AppData, which is what lets a user keep
        every byte off the system drive.
        """
        try:
            target = root / 'app' / 'data-root.txt'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(data), encoding='utf-8')
        except OSError as exc:
            with self.lock:
                self.job['log'].append(f'data-root.txt: {exc}')

    def _run_doctor(self, root: Path, data: Path) -> None:
        exe = root / 'app' / ('CaiXiHui.exe' if os.name == 'nt' else 'CaiXiHui')
        if not exe.exists():
            self.doctor = {'state': 'done', 'report': {}}
            return
        self.doctor = {'state': 'running', 'report': {}}
        env = dict(os.environ)
        env['CIXI_COMPONENTS_DIR'] = str(root / 'components')
        env['CRAWLER_DATA_ROOT'] = str(data)
        # The report is Chinese and captured through a pipe: without this the child uses the
        # console code page (cp936 on a Chinese Windows) and the decoded sentence is mojibake.
        # The app also writes UTF-8 bytes itself; this is the second line of defence.
        env['PYTHONIOENCODING'] = 'utf-8'
        report: dict = {}
        try:
            result = subprocess.run(
                [str(exe), '--doctor'],
                capture_output=True,
                timeout=DOCTOR_TIMEOUT,
                check=False,
                env=env,
            )
            text = (result.stdout or b'').decode('utf-8-sig', errors='replace')
            # The launcher may print a note about the data root before the report (a fallback is
            # always stated aloud), so the JSON starts at the first brace rather than at byte 0.
            start = text.find('{')
            report = json.loads(text[start:]) if start >= 0 else {}
        except (OSError, subprocess.SubprocessError, ValueError):
            report = {}
        self.doctor = {'state': 'done', 'report': report if isinstance(report, dict) else {}}


def _writable(path: Path) -> str:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
    except OSError as exc:
        return str(exc)
    return ''


def path_load_refusal(root: Path) -> str:
    """``''`` when .NET can load an assembly from this folder, else the reason.

    Windows classifies some volumes as "remote" for the CLR (this project's F: is one): the
    installed onedir application would then fail to load pythonnet/WebView2 with
    ``Failed to resolve Python.Runtime.Loader.Initialize``. ``GetDriveType`` says Fixed for that
    volume, so the only honest test is the load itself: copy a managed DLL into the chosen folder
    and ask a separate PowerShell process to ``Assembly.LoadFrom`` it. Nothing is downloaded
    before this runs, so a bad drive is refused before the user pays for it.
    """
    if os.name != 'nt':
        return ''
    try:
        import pythonnet

        source = Path(pythonnet.__file__).resolve().parent / 'runtime' / 'Python.Runtime.dll'
    except Exception:
        source = asset_dir() / 'pythonnet' / 'runtime' / 'Python.Runtime.dll'
    if not source.is_file():
        return ''
    probe = Path(root) / '.caixihui-path-probe.dll'
    try:
        shutil.copy2(source, probe)
    except OSError:
        return ''
    quoted = str(probe).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop'; "
        f"try {{ [Reflection.Assembly]::LoadFrom('{quoted}') | Out-Null; 'OK' }} "
        'catch { $_.Exception.Message; exit 1 }'
    )
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ''
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()
    if result.returncode == 0 and 'OK' in (result.stdout or ''):
        return ''
    output = f'{result.stdout or ""}\n{result.stderr or ""}'
    # Only the CLR's remote-assembly refusal is a verdict. A locked-down PowerShell (execution
    # policy, missing profile) must not block a perfectly good folder: that check could not answer.
    if '0x80131515' not in output and 'network location' not in output and '网络位置' not in output:
        return ''
    lines = output.strip().splitlines()
    return lines[-1] if lines else 'Assembly.LoadFrom was refused'


def relaunch_command(argv: list[str]) -> tuple[str, str]:
    """The exe to elevate and its argument string, for a frozen build or a source run."""
    if getattr(sys, 'frozen', False):
        return sys.executable, subprocess.list2cmdline(argv)
    script = str(Path(__file__).resolve())
    return sys.executable, subprocess.list2cmdline([script, *argv])


def is_elevated() -> bool:
    """Whether THIS process's token is elevated (not merely an Administrators-group member).

    ``IsUserAnAdmin`` reports group membership, which stays true for a filtered UAC token; using it
    would skip the elevation prompt on a non-elevated admin and then fail at the first write. Ask
    the token's ``TokenElevation`` value instead.
    """
    if os.name != 'nt':
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        advapi32.OpenProcessToken.restype = wintypes.BOOL
        advapi32.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        advapi32.GetTokenInformation.restype = wintypes.BOOL
        token = wintypes.HANDLE()
        # TOKEN_QUERY = 0x0008
        if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            return False
        try:
            elevation = wintypes.DWORD()
            size = wintypes.DWORD()
            # TokenElevation = 20; a DWORD where 1 means the token is elevated.
            if not advapi32.GetTokenInformation(
                token,
                20,
                ctypes.byref(elevation),
                ctypes.sizeof(elevation),
                ctypes.byref(size),
            ):
                return False
            return elevation.value == 1
        finally:
            kernel32.CloseHandle(token)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _relaunch_elevated(root: Path, data: Path, bert: str = '') -> bool:
    """Ask Windows for administrator rights once, with the same folders preselected."""
    if os.name != 'nt':
        return False
    try:
        import ctypes

        argv = ['--root', str(root), '--data', str(data), '--elevated']
        if bert:
            argv += ['--bert', bert]
        exe, params = relaunch_command(argv)
        result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', exe, params, None, 1)
    except (AttributeError, OSError):
        return False
    return result > 32


#: A fixed port keeps the page's origin stable, which is what makes ``localStorage`` (language,
#: theme) survive a restart. A busy port falls back to an ephemeral one; the token still guards the
#: server either way.
INSTALLER_PORT = 3968


class InstallerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, state: InstallerState, token: str, port: int = INSTALLER_PORT, handler=None) -> None:
        super().__init__(('127.0.0.1', int(port)), handler or Handler)
        self.state = state
        self.token = token
        # Set by main(): closing the window is what ends the GUI loop, so the server cannot stop
        # on its own (a launch or an elevation request ends BOTH).
        self.on_stop = None

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.server_address[1]}/{self.token}/'

    def stop_soon(self, delay: float = 0.2) -> None:
        if self.state.shutting_down:
            return
        self.state.shutting_down = True

        def stop() -> None:
            self.shutdown()
            if self.on_stop is not None:
                self.on_stop()

        timer = threading.Timer(delay, stop)
        timer.daemon = True
        timer.start()


class Handler(BaseHTTPRequestHandler):
    server_version = 'CaiXiHuiInstaller'
    sys_version = ''

    #: The platform installer may replace these two seams: the shared page text differs on macOS
    #: (no “domestic” claim for the DMG, no Windows elevation sentence), and its folder picker is
    #: ``osascript`` rather than ``SHBrowseForFolderW``.
    @property
    def words(self) -> dict:
        return TEXT

    pick_folder = staticmethod(pick_folder)
    pick_file = staticmethod(pick_file)

    # ── plumbing ────────────────────────────────────────────────

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self._send(status, body, 'application/json; charset=utf-8')

    def _asset(self, name: str, content_type: str) -> None:
        path = asset_dir() / name
        if not path.exists():
            self._send(404, b'not found', 'text/plain; charset=utf-8')
            return
        self._send(200, path.read_bytes(), content_type)

    def _authorized(self, path: str) -> bool:
        return path.startswith(f'/{self.server.token}/')

    def _route(self) -> str:
        path = urlparse(self.path).path
        prefix = f'/{self.server.token}'
        return path[len(prefix) :] or '/'

    def _body(self) -> dict:
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 65536:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
        except (ValueError, UnicodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    # ── GET ─────────────────────────────────────────────────────
    def handle_get(self):
        if not self._authorized(urlparse(self.path).path):
            self._send(404, b'not found', 'text/plain; charset=utf-8')
            return
        route = self._route()
        if route in ('/', '/index.html'):
            self._send(200, self._page(), 'text/html; charset=utf-8')
        elif route == '/installer_page.js':
            self._asset('installer_page.js', 'application/javascript; charset=utf-8')
        elif route == '/icon.ico':
            path = icon_path()
            if path.exists():
                self._send(200, path.read_bytes(), 'image/x-icon')
            else:
                self._send(404, b'', 'image/x-icon')
        elif route == '/api/state':
            self._json({'ok': True, 'state': self.server.state.snapshot()})
        elif route == '/api/doctor':
            self._json(dict(self.server.state.doctor))
        else:
            self._send(404, b'not found', 'text/plain; charset=utf-8')

    # ── POST ────────────────────────────────────────────────────
    def handle_post(self):
        if not self._authorized(urlparse(self.path).path):
            self._send(404, b'not found', 'text/plain; charset=utf-8')
            return
        route = self._route()
        state = self.server.state
        payload = self._body()
        if route == '/api/select':
            state.set_selection(payload.get('ids'))
            self._json({'ok': True, 'state': state.snapshot()})
        elif route == '/api/preset':
            if not state.set_preset(str(payload.get('preset') or '')):
                self._json({'ok': False, 'error': 'unknown preset'}, 400)
            else:
                self._json({'ok': True, 'state': state.snapshot()})
        elif route == '/api/browse':
            kind = str(payload.get('kind') or 'root')
            lang = 'en' if str(payload.get('lang')) == 'en' else 'zh'
            title_key = {'data': 'data_dir', 'bert': 'bert'}.get(kind, 'dir')
            title = self.words[lang][title_key]
            try:
                picked = self.pick_file(title) if kind == 'bert' else self.pick_folder(title)
            except (OSError, TypeError, ValueError) as exc:
                # A picker failure is "no path chosen", never a dead HTTP request: the page's
                # browse button used to end in ERR_EMPTY_RESPONSE when the shell call raised.
                log_line(f'folder picker failed: {exc}')
                picked = ''
            self._json({'ok': True, 'path': picked})
        elif route == '/api/start':
            self._json(self._start(state, payload))
        elif route == '/api/cancel':
            state.cancel.set()
            self._json({'ok': True, 'state': state.snapshot()})
        elif route == '/api/open':
            target = str(payload.get('root') or '').strip() or state.root
            self._open_folder(target)
            self._json({'ok': True})
        elif route == '/api/launch':
            self._json(self._launch(state))
        elif route == '/api/shutdown':
            self._json({'ok': True})
            self.server.stop_soon()
        else:
            self._send(404, b'not found', 'text/plain; charset=utf-8')

    # ── actions ─────────────────────────────────────────────────
    def _start(self, state: InstallerState, payload: dict) -> dict:
        lang = 'en' if str(payload.get('lang')) == 'en' else 'zh'
        words = self.words[lang]
        if state.job['state'] == 'running':
            return {'ok': False, 'error': words['already_running']}
        root_text = str(payload.get('root') or '').strip()
        data_text = str(payload.get('data') or '').strip()
        if not root_text or not data_text:
            return {'ok': False, 'error': words['dir']}
        state.set_selection(payload.get('ids'))
        ids = state.effective()
        if 'app' not in ids:
            return {'ok': False, 'error': words['no_selection']}
        bert_text = str(payload.get('bert') or '').strip()
        if state.bert_supported and bert_text:
            problem = _BERT.pack_problem(bert_text)
            if problem:
                return {'ok': False, 'error': words['bert_invalid'].format(err=problem)}
        state.set_bert(bert_text if state.bert_supported else '')
        raw_shortcut = payload.get('shortcut', True)
        if isinstance(raw_shortcut, str):
            state.set_shortcut(raw_shortcut.strip().lower() not in ('0', 'false', 'off', 'no', ''))
        else:
            state.set_shortcut(bool(raw_shortcut))
        root = Path(root_text)
        data = Path(data_text).expanduser()
        for path in (root, data):
            anchor = path.anchor
            if anchor and not Path(anchor).exists():
                return {'ok': False, 'error': words['drive_missing'].format(path=path)}
            problem = _writable(path)
            if not problem:
                continue
            # The manifest already asks for admin, so a second UAC here is only for an unusual
            # non-elevated run (a source checkout, a host that stripped the manifest). Never ask
            # twice when this token is already administrator: a redundant request can be denied
            # and then the real write error is hidden behind a misleading "no admin" sentence.
            if not is_elevated() and not state.elevated and _relaunch_elevated(root, data, state.bert):
                self.server.stop_soon(0.8)
                return {'ok': False, 'relaunching': True}
            log_line(f'install path not writable: {path}: {problem}')
            return {'ok': False, 'error': words['not_writable'].format(path=path, err=problem)}
        remote = path_load_refusal(root)
        if remote:
            # A named refusal instead of letting the user install 560 MB onto a volume the
            # application cannot start from; the raw CLR sentence goes to the log.
            log_line(f'install path refused: {root}: {remote}')
            return {'ok': False, 'error': words['bad_path'].format(path=root)}
        need = sum(state.catalog.get(item).asset().size for item in ids if state.catalog.get(item).asset())
        free = free_space(root)
        if free and free < need + 200 * 1024 * 1024:
            return {
                'ok': False,
                'error': words['disk'].format(free=human_size(free), need=human_size(need)),
            }
        bert_need = 0
        if state.bert:
            with contextlib.suppress(OSError):
                source = Path(state.bert)
                if source.is_file():
                    bert_need = source.stat().st_size
        if bert_need:
            data_free = free_space(data)
            if data_free and data_free < bert_need + 200 * 1024 * 1024:
                return {
                    'ok': False,
                    'error': words['disk'].format(free=human_size(data_free), need=human_size(bert_need)),
                }
        state.start(root, data)
        return {'ok': True, 'state': state.snapshot()}

    def _open_folder(self, root: str) -> None:
        path = Path(root)
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(path)
            else:
                subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        except OSError:
            return

    def _launch(self, state: InstallerState) -> dict:
        root = Path(state.root)
        exe = root / 'app' / ('CaiXiHui.exe' if os.name == 'nt' else 'CaiXiHui')
        if not exe.exists():
            return {'ok': False, 'error': self.words['zh']['not_installed']}
        env = dict(os.environ)
        env['CIXI_COMPONENTS_DIR'] = str(root / 'components')
        env['CRAWLER_DATA_ROOT'] = state.data
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
        except OSError as exc:
            return {'ok': False, 'error': str(exc)}
        self.server.stop_soon(1.0)
        return {'ok': True}

    def _page(self) -> bytes:
        template = (asset_dir() / 'installer_page.html').read_text(encoding='utf-8')
        config = {
            'token': self.server.token,
            'lang': 'zh',
            'text': self.words,
            'state_labels': STATE_LABEL,
            'bert_supported': self.server.state.bert_supported,
            'shortcut_supported': self.server.state.shortcut_supported,
            'path_separator': os.sep,
            'state': self.server.state.snapshot(),
        }
        payload = json.dumps(config, ensure_ascii=False).replace('</', '<\\/')
        html = template.replace('{{CSS}}', ui_theme.stylesheet()).replace(
            '{{CONFIG}}', f'window.INSTALLER = {payload};'
        )
        return html.encode('utf-8')


def _quiet_request_log(_self, *_args, **_kwargs):
    """The installer has no console; a request log would only be noise in a windowed build."""


# The stdlib dispatches on these exact names. Assigning them outside the class keeps the
# pep8-naming rule honest without an exemption: the handlers themselves are ordinary methods, and
# the log override keeps its own signature out of a base-class argument comparison.
Handler.do_GET = Handler.handle_get
Handler.do_POST = Handler.handle_post
Handler.log_message = _quiet_request_log


def may_close(job_state: str) -> bool:
    """Whether the window's X may end the process. A running download is never cut off; 取消 is
    the documented way out, and closing would leave a half-downloaded component behind."""
    return job_state != 'running'


def _make_server(state: InstallerState, token: str) -> InstallerServer:
    """The fixed port when it is free, an ephemeral one when another program holds it."""
    try:
        return InstallerServer(state, token=token, port=INSTALLER_PORT)
    except OSError:
        return InstallerServer(state, token=token, port=0)


def main(argv=None) -> int:
    native_window.ensure_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    options: dict[str, str] = {}
    for index, arg in enumerate(argv):
        if arg in ('--root', '--data', '--bert') and index + 1 < len(argv):
            options[arg[2:]] = argv[index + 1]
    catalog = Catalog(load_catalog())
    state = InstallerState(
        catalog,
        options.get('root') or str(default_root()),
        options.get('data') or str(default_data_root()),
        elevated='--elevated' in argv,
    )
    if options.get('bert'):
        state.set_bert(options['bert'])
    # A random path token keeps other local pages from poking this server. The environment
    # override exists for the packaged smoke test, which cannot read a windowed build's stdout.
    token = str(os.environ.get('CIXI_INSTALLER_TOKEN') or '').strip() or secrets.token_hex(8)
    server = _make_server(state, token)
    server.on_stop = native_window.close
    url = server.url
    log_line(f'安装器已启动：{url}')
    threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.2}, daemon=True).start()

    # The window is the whole user interface: no console, no browser handoff. It blocks here, and
    # closing it (or a launch/elevation request, which calls close()) ends the process.
    # ``--no-window`` is the automation seam: the same server, no GUI.
    no_window = os.environ.get('CIXI_NO_WINDOW') == '1' or '--no-window' in argv
    if no_window:
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever(poll_interval=0.2)
        failure = ''
    else:
        failure = native_window.run(
            TEXT['zh']['title'],
            url,
            width=1080,
            height=760,
            min_size=(920, 640),
            storage=native_window.storage_dir('webview-installer'),
            on_close=lambda: may_close(state.job['state']),
            # A closed installer must not linger either: the next run would otherwise contend for
            # the fixed port and the same component folders.
            exit_on_close=True,
        )
    if failure:
        log_line(f'window failed: {failure}')
        native_window.complain(failure)
    with contextlib.suppress(OSError):
        server.shutdown()
    server.server_close()
    log_line('installer stopped')
    status = 1 if failure else 0
    if not no_window:
        # A closed installer must not linger with its fixed port and install folders held; the
        # status keeps a failed window visible to whoever launched the installer.
        native_window.terminate_process(status)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
