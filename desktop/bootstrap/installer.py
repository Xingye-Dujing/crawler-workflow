"""The online installer: choose a folder and components, download from domestic mirrors, launch.

The window is the user's own browser showing a page this process serves on ``127.0.0.1``: the
application is a web UI, so the installer can wear the SAME design language for the cost of a few
kilobytes of CSS instead of shipping a GUI toolkit. The exe stays small (stdlib server + the
component core), which is what "小而精" asks for, and the page is generated from the application's
own tokens (``backend/static/css/base.css``).

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
import subprocess
import sys
import threading
import time
import webbrowser
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
    """Print one line and append it to the diagnostic log.

    This is a console program: the console is the fallback the user can read when the browser
    cannot be opened. The file copy keeps the same fact after the console closes (several
    destinations, best first: an explicit test path, the user's local app data, the exe's own
    folder, then the system temp).
    """
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f'{stamp} {text}', flush=True)
    line = f'{stamp} {text}\n'
    explicit = str(os.environ.get('CIXI_INSTALLER_LOG') or '').strip()
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
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


def open_page(url: str) -> bool:
    """Open the installer page in the user's default browser.

    No GUI toolkit and no forced browser window: this program is a backend console, and the
    browser is the front end. The URL is printed either way, so a machine that blocks a child
    browser still leaves the user an address they can open themselves.
    """
    try:
        if webbrowser.open(url):
            return True
    except (OSError, webbrowser.Error):
        pass
    startfile = getattr(os, 'startfile', None)
    if startfile is not None:
        try:
            startfile(url)
            return True
        except OSError:
            pass
    return False


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

Catalog = _CATALOG.Catalog
CatalogError = _CATALOG.CatalogError
load_catalog = _CATALOG.load_catalog
_DOWNLOAD = importlib.import_module('services.components.fetch')
DownloadError = _DOWNLOAD.DownloadError
_MANIFEST = importlib.import_module('services.components.manifest')
ManifestError = _MANIFEST.ManifestError
InstallError = _INSTALL.InstallError
install_component = _INSTALL.install_component
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
    kernel32 = ctypes.windll.kernel32
    # Owner: this program's own console (a window in our process, so the shell never waits on a
    # foreign thread), else the foreground window. The helper below then makes the dialog topmost
    # for as long as it is open — an unowned browse dialog can open behind the browser.
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    owner = kernel32.GetConsoleWindow() or user32.GetForegroundWindow() or None
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


class InstallerState:
    """Everything the page may ask about, guarded because the install runs on a thread."""

    def __init__(self, catalog: Catalog, root: str, data: str, elevated: bool) -> None:
        self.catalog = catalog
        self.root = str(root)
        self.data = str(data)
        self.elevated = elevated
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
                'preset': self.preset,
                'components': rows,
                # Bytes, not a sentence: the page renders the size in its own language.
                'total': total,
                'job': dict(self.job, log=list(self.job['log'])),
            }

    # ── actions ─────────────────────────────────────────────────
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


def relaunch_command(argv: list[str]) -> tuple[str, str]:
    """The exe to elevate and its argument string, for a frozen build or a source run."""
    if getattr(sys, 'frozen', False):
        return sys.executable, subprocess.list2cmdline(argv)
    script = str(Path(__file__).resolve())
    return sys.executable, subprocess.list2cmdline([script, *argv])


def _relaunch_elevated(root: Path, data: Path) -> bool:
    """Ask Windows for administrator rights once, with the same folders preselected."""
    if os.name != 'nt':
        return False
    try:
        import ctypes

        exe, params = relaunch_command(['--root', str(root), '--data', str(data), '--elevated'])
        result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', exe, params, None, 1)
    except (AttributeError, OSError):
        return False
    return result > 32


class InstallerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, state: InstallerState, token: str) -> None:
        super().__init__(('127.0.0.1', 0), Handler)
        self.state = state
        self.token = token
        self.last_seen = time.monotonic()

    @property
    def url(self) -> str:
        return f'http://127.0.0.1:{self.server_address[1]}/{self.token}/'

    def stop_soon(self, delay: float = 0.2) -> None:
        if self.state.shutting_down:
            return
        self.state.shutting_down = True
        timer = threading.Timer(delay, self.shutdown)
        timer.daemon = True
        timer.start()


class Handler(BaseHTTPRequestHandler):
    server_version = 'CaiXiHuiInstaller'
    sys_version = ''

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
        prefix = f'/{self.server.token}/'
        if path.startswith(prefix):
            self.server.last_seen = time.monotonic()
            return True
        return False

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
            title = TEXT[lang]['data_dir' if kind == 'data' else 'dir']
            try:
                picked = pick_folder(title)
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
            self._open_folder(state.root)
            self._json({'ok': True})
        elif route == '/api/launch':
            self._json(self._launch(state))
        elif route == '/api/ping':
            self._json({'ok': True})
        elif route == '/api/shutdown':
            self._json({'ok': True})
            self.server.stop_soon()
        else:
            self._send(404, b'not found', 'text/plain; charset=utf-8')

    # ── actions ─────────────────────────────────────────────────
    def _start(self, state: InstallerState, payload: dict) -> dict:
        lang = 'en' if str(payload.get('lang')) == 'en' else 'zh'
        words = TEXT[lang]
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
        root = Path(root_text)
        data = Path(data_text)
        refused = _writable(root) or _writable(data)
        if refused:
            # Nothing was downloaded yet, so asking for rights here costs the user one prompt
            # instead of a failed install minutes later — and only when the folder needs it.
            if not state.elevated and _relaunch_elevated(root, data):
                self.server.stop_soon(0.8)
                return {'ok': False, 'relaunching': True}
            message = words['elevated_again'] if state.elevated else words['elevate_failed']
            return {'ok': False, 'error': message}
        need = sum(state.catalog.get(item).asset().size for item in ids if state.catalog.get(item).asset())
        free = free_space(root)
        if free and free < need + 200 * 1024 * 1024:
            return {
                'ok': False,
                'error': words['disk'].format(free=human_size(free), need=human_size(need)),
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
            return {'ok': False, 'error': TEXT['zh']['not_installed']}
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
            'text': TEXT,
            'state_labels': STATE_LABEL,
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


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    options: dict[str, str] = {}
    for index, arg in enumerate(argv):
        if arg in ('--root', '--data') and index + 1 < len(argv):
            options[arg[2:]] = argv[index + 1]
    catalog = Catalog(load_catalog())
    state = InstallerState(
        catalog,
        options.get('root') or str(default_root()),
        options.get('data') or str(default_data_root()),
        elevated='--elevated' in argv,
    )
    # A random path token keeps other local pages from poking this server. The environment
    # override exists for the packaged smoke test, which cannot read a windowed build's stdout.
    token = str(os.environ.get('CIXI_INSTALLER_TOKEN') or '').strip() or secrets.token_hex(8)
    server = InstallerServer(state, token=token)
    url = server.url
    log_line(f'安装器页面：{url}')

    def open_window() -> None:
        time.sleep(0.4)
        mark = server.last_seen
        open_page(url)
        # `webbrowser.open` returning True only means the shell accepted the call. The page's own
        # request is the proof that a browser is really showing it; otherwise print the address.
        # A cold browser can take longer than a handoff; six seconds produced a false "open it
        # manually" while the tab was still starting on a real machine. Fifteen is enough for a
        # first-run profile without making a blocked launch look like it worked.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and server.last_seen <= mark:
            time.sleep(0.2)
        if server.last_seen > mark:
            log_line('浏览器已打开安装页面')
        else:
            log_line(f'没有等到浏览器打开页面，请手动打开：{url}')

    threading.Thread(target=open_window, daemon=True).start()
    threading.Thread(target=watchdog, args=(server, state), daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log_line('installer stopped')
    return 0


def idle_expired(last_seen: float, now: float, job_state: str, idle: float = 240.0) -> bool:
    """Whether the page has been gone long enough to stop this process.

    A running download is never interrupted by idleness; only a closed window is.
    """
    return job_state != 'running' and now - last_seen > idle


def watchdog(server: InstallerServer, state: InstallerState, *, idle: float = 240.0) -> None:
    """Stop after the page has been gone for a while — a closed window must not leave a process.

    The page sends a heartbeat every 20 s, so a tab left open keeps the installer alive; closing
    it stops the requests.
    """
    while not state.shutting_down:
        time.sleep(20)
        if state.job['state'] == 'running':
            server.last_seen = time.monotonic()
            continue
        if idle_expired(server.last_seen, time.monotonic(), state.job['state'], idle):
            log_line('no page requests; stopping the installer')
            server.stop_soon(0)
            return


if __name__ == '__main__':
    raise SystemExit(main())
