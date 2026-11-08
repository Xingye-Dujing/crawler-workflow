"""The one native window both executables show: Edge WebView2 inside our own process.

The page is still served from ``127.0.0.1`` (both front ends call ``fetch``), but the viewer is no
longer the user's browser and there is no console: ``pywebview`` creates a real window and hosts
WebView2 in this process. That buys three things a browser handoff could not:

* a stable origin, so ``localStorage`` (theme, language) survives a restart — the installer keeps
  a fixed port for exactly this reason;
* a window that cannot be lost behind a browser, and an owner handle for the folder picker;
* no console at all, which is what a double-clicked desktop program should look like.

The Edge WebView2 runtime ships with Windows 10/11 (it is the engine of the installed Edge). A
machine without it is refused by name: :func:`run` returns the reason and :func:`complain` names
the download page instead of failing with an empty window.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

WEBVIEW2_URL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'

#: Paper, the application's own background token (``--bg`` in ``static/css/base.css``).
BACKGROUND = '#ffffff'

#: How long the page has to prove it loaded before the window is declared broken. A cold WebView2
#: profile and a local server answer well inside this; a missing runtime never answers at all.
PAGE_TIMEOUT = 25.0

_WINDOW = None
_HANDLE = 0
_ALLOW_CLOSE = False


def storage_dir(name: str) -> str:
    """Where WebView2 keeps cookies and localStorage for one of the two windows.

    Explicit, not pywebview's default: the data must live under the user's own profile beside the
    rest of this application's state, and it must be the SAME folder on every launch.
    """
    base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return str(Path(base) / 'CaiXiHui' / name)


def handle() -> int:
    """The window's native HWND, or ``0`` before it is shown (the folder picker's owner)."""
    return _HANDLE


def stage_window_stack() -> str:
    """Copy the .NET assemblies to a local folder and point both loaders at it.

    .NET Framework treats some paths as "remote" (UNC, substituted/network-backed volumes, and
    measured on this project's F: drive) and refuses ``Assembly.LoadFrom`` there with "Attempt to
    load an assembly from a network location". The symptom was the installer extracted beside
    itself on such a drive dying with ``Failed to resolve Python.Runtime.Loader.Initialize``, while
    the same bytes run fine from C:.

    The stack is about 1.5 MB. Copying it once into ``%LOCALAPPDATA%`` makes every .NET load local,
    so the program (and the folder the user installs it into) may live on any drive. A storage
    refusal is not fatal: the original paths still work on a local drive.
    """
    try:
        import json
        import shutil

        import pythonnet
        import webview
        import webview.util
    except Exception:
        return ''
    source_webview = Path(webview.__file__).resolve().parent
    source_pythonnet = Path(pythonnet.__file__).resolve().parent
    source_lib = source_webview / 'lib'
    source_runtime = source_pythonnet / 'runtime'
    if not source_lib.is_dir() or not source_runtime.is_dir():
        return ''
    stamp = {}
    for name in ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll'):
        if (source_lib / name).is_file():
            stamp[name] = (source_lib / name).stat().st_size
    if (source_runtime / 'Python.Runtime.dll').is_file():
        stamp['Python.Runtime.dll'] = (source_runtime / 'Python.Runtime.dll').stat().st_size
    target = Path(storage_dir('webview-runtime'))
    marker = target / 'stamp.json'
    try:
        current = json.loads(marker.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        current = None
    try:
        if current != stamp:
            with contextlib.suppress(OSError):
                shutil.rmtree(target)
            (target / 'webview').mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_lib, target / 'webview' / 'lib', dirs_exist_ok=True)
            shutil.copytree(source_runtime, target / 'pythonnet' / 'runtime', dirs_exist_ok=True)
            marker.write_text(json.dumps(stamp), encoding='utf-8')
    except OSError:
        return ''
    # These two module attributes are what the loaders read their assembly paths from; the code
    # itself is already imported from the bundle.
    webview.util.__file__ = str(target / 'webview' / 'util.py')
    pythonnet.__file__ = str(target / 'pythonnet' / '__init__.py')
    return str(target)


def available() -> bool:
    """Whether the WebView2 host can be imported at all (a missing runtime refuses later)."""
    import importlib.util

    with contextlib.suppress(ValueError, ImportError):
        return importlib.util.find_spec('webview') is not None
    return False


def close() -> None:
    """Ask the window to go away; safe to call from a request thread.

    The close is forced: ``on_close`` exists to stop the USER from closing mid-download, not to
    stop this program from shutting itself down after a launch or an elevation request.
    """
    global _ALLOW_CLOSE
    _ALLOW_CLOSE = True
    window = _WINDOW
    if window is None:
        return
    with contextlib.suppress(Exception):
        window.destroy()


def run(
    title: str,
    url: str,
    *,
    width: int = 1080,
    height: int = 760,
    min_size: tuple[int, int] = (900, 620),
    storage: str = '',
    on_close=None,
) -> str:
    """Show ``url`` in a native window and block until it closes.

    Returns ``''`` on a normal close, or a sentence naming why no window could be shown (the
    WebView2 runtime is missing, the host refused to start). The caller decides how loud that is.
    """
    global _WINDOW, _HANDLE, _ALLOW_CLOSE
    # Must run before the first .NET import: it points both loaders at a local copy of the stack.
    stage_window_stack()
    try:
        import webview
    except Exception as exc:
        return f'无法加载 WebView2 窗口组件：{exc}'

    window = webview.create_window(
        title,
        url,
        width=width,
        height=height,
        min_size=min_size,
        background_color=BACKGROUND,
        text_select=True,
    )
    _WINDOW = window
    _HANDLE = 0
    _ALLOW_CLOSE = False
    failed = []

    def remember_handle() -> None:
        global _HANDLE
        with contextlib.suppress(Exception):
            _HANDLE = int(window.native.Handle.ToInt32())

    def closing() -> bool:
        # pywebview cancels a close when a handler returns False. On close there is no question to
        # ask: the caller's guard decides (the installer refuses while a download runs).
        if _ALLOW_CLOSE or on_close is None:
            return True
        return bool(on_close())

    def wait_for_page() -> None:
        """A window whose page never loads is the "it flashed and did nothing" failure.

        WebView2 reports a broken runtime on its own thread and pywebview's loop keeps running,
        so the blank window would stay forever. The page's ``loaded`` event is the proof that the
        server was reached; without it the user is told the real reason and the window closes.
        """
        if window.events.loaded.wait(PAGE_TIMEOUT):
            return
        # Close here, report to the caller: the caller already owns the one dialog it shows for a
        # failed start (a second box for the same fact is noise, and a box waits for a click).
        failed.append('窗口已经打开，但页面没有加载出来：本机无法启动 Microsoft Edge WebView2 组件。')
        close()

    window.events.shown += remember_handle
    window.events.closing += closing
    try:
        # private_mode=False + storage_path is what makes localStorage persist; the Edge engine
        # itself is the installed WebView2 runtime, so nothing is downloaded here.
        webview.start(
            wait_for_page,
            gui='edgechromium',
            private_mode=False,
            storage_path=storage or None,
        )
    except Exception as exc:
        return f'无法打开程序窗口：{exc}'
    finally:
        _WINDOW = None
        _HANDLE = 0
    return failed[0] if failed else ''


def alert(message: str, title: str = '') -> None:
    """A native message box — the one notice that exists before a window can be shown."""
    if os.name != 'nt':
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(message), str(title), 0x00000010)  # MB_ICONERROR
    except (AttributeError, OSError):
        pass


def complain(reason: str, title: str = '采析绘') -> None:
    """Report a failed window, naming WebView2 only when that is the actual cause.

    The old text always told the user to install WebView2, so a Python.Runtime load failure on a
    drive .NET treats as remote read as "your WebView2 is missing" while it was installed all
    along. A diagnosis that guesses is worse than the raw reason.
    """
    lowered = reason.lower()
    missing_runtime = 'webview2' in lowered or '运行时' in reason
    if missing_runtime:
        text = (
            f'{reason}\n\n'
            '这个程序用 Windows 自带的 Microsoft Edge WebView2 显示界面。\n'
            '请先安装 WebView2 运行时，再重新打开：\n'
            f'{WEBVIEW2_URL}'
        )
    else:
        text = f'{reason}\n\n窗口没能打开。请把这段提示和日志文件一起发给维护者。'
    alert(text, title)
    if missing_runtime:
        with contextlib.suppress(OSError):
            os.startfile(WEBVIEW2_URL)


def activate(pid: int) -> bool:
    """Bring an already-running copy's window to the front; ``False`` when it is gone.

    A second double-click used to hand the address to a browser. There is no browser now, so the
    existing window is raised instead — and when it cannot be found the caller says so.
    """
    if os.name != 'nt' or pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

        found = []

        def visit(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not user32.IsWindowVisible(hwnd):
                return True
            if not user32.GetWindowTextLengthW(hwnd):
                return True
            found.append(hwnd)
            return False

        user32.EnumWindows(callback_type(visit), 0)
        if not found:
            return False
        target = found[0]
        user32.ShowWindow(target, 9)  # SW_RESTORE
        user32.SetForegroundWindow(target)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def ensure_streams() -> None:
    """Give a windowed build real ``stdout``/``stderr`` when anything is listening.

    PyInstaller's windowed bootloader leaves ``sys.stdout`` as ``None``, so ``print`` raises. Two
    cases must still write: the installer captures ``--doctor`` through a pipe, and ``CaiXiHui
    --doctor`` run from a terminal should answer there (the exe attaches to the parent console).
    A plain double-click has no listener and gets ``os.devnull``.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    # These streams outlive the function on purpose (they become ``sys.stdout``), which is why
    # they are not opened in a ``with``. The fd is inherited from a pipe, or from the terminal
    # this GUI exe attached itself to; a plain double-click gets os.devnull.
    stream = None
    with contextlib.suppress(OSError, ValueError):
        stream = io.TextIOWrapper(io.FileIO(1, 'w', closefd=False), encoding='utf-8', errors='replace')
    if stream is None and os.name == 'nt':
        with contextlib.suppress(AttributeError, OSError):
            import ctypes

            ctypes.windll.kernel32.AttachConsole(-1)  # ATTACH_PARENT_PROCESS
            stream = io.TextIOWrapper(io.FileIO('CONOUT$', 'w'), encoding='utf-8', errors='replace')
    if stream is None:
        stream = io.TextIOWrapper(io.FileIO(os.devnull, 'w'), encoding='utf-8', errors='replace')
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
