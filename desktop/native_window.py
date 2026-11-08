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


def _takes_write(path: Path) -> bool:
    """Whether this process can really create a directory and a file inside it.

    ``os.access`` on Windows answers about the token, not the ACL in effect for this process and
    endpoint protection; a probe file is the only honest test. pywebview refuses a profile folder
    with its own ``os.access`` check, so the folder must exist and be writable before it is passed.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
    except OSError:
        return False
    return True


def storage_dir(name: str) -> str:
    """A writable folder for WebView2 state, in the first place this process may write.

    ``%LOCALAPPDATA%`` is the normal answer; a locked-down machine may deny creating anything under
    it (measured: the window died with “Storage path … is not writable”, while the program's own data
    root was fine). ``%APPDATA%``, the application's ``CRAWLER_DATA_ROOT`` and finally the exe's
    folder are tried in that order, and the first that takes a probe file wins. The LocalAppData
    path is returned when nothing works, so the refusal names the intended place rather than a
    surprising substitute.
    """
    local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'CaiXiHui' / name
    candidates = [local]
    roaming = str(os.environ.get('APPDATA') or '').strip()
    if roaming:
        candidates.append(Path(roaming) / 'CaiXiHui' / name)
    data_root = str(os.environ.get('CRAWLER_DATA_ROOT') or '').strip()
    if data_root:
        candidates.append(Path(data_root) / name)
    temp = str(os.environ.get('TEMP') or os.environ.get('TMP') or '').strip()
    if temp:
        # The reference desktop build (D:\blog\web\public) proves a onefile's per-user temp is
        # writable on this machine even when LocalAppData\CaiXiHui is not; WebView2 only needs a
        # folder it can create, and the temp fallback keeps the window usable.
        candidates.append(Path(temp) / 'CaiXiHui' / name)
    candidates.append(Path(sys.executable).resolve().parent / 'webview-profile')
    for candidate in candidates:
        if _takes_write(candidate):
            return str(candidate)
    return str(local)


def handle() -> int:
    """The window's native HWND, or ``0`` before it is shown (the folder picker's owner)."""
    return _HANDLE


def available() -> bool:
    """Whether the WebView2 host can be imported at all (a missing runtime refuses later)."""
    import importlib.util

    with contextlib.suppress(ValueError, ImportError):
        return importlib.util.find_spec('webview') is not None
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
    # The proven reference build (D:\blog\web\public) lets the onefile extract its .NET stack into
    # the user temp dir and does not repoint the loader; copying the assemblies elsewhere made
    # WebView2 fail to initialise (E_UNEXPECTED) even with a complete DLL set.
    if storage:
        os.environ.setdefault('WEBVIEW2_USER_DATA_FOLDER', storage)
    try:
        import webview
    except Exception as exc:
        return f'无法加载 WebView2 窗口组件：{exc}'
    # Same two grants as the reference launcher: the application exports files and opens docs.
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True

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
    remote = 'python.runtime' in lowered or 'network location' in lowered
    missing_runtime = 'webview2' in lowered or '运行时' in reason
    if remote:
        drive = Path(sys.executable).drive or '?'
        text = (
            f'{reason}\n\n'
            f'Windows 把程序所在的盘（{drive}）当作“网络位置”，.NET 拒绝从那里加载窗口组件；\n'
            'WebView2 本身没有问题。请把整个程序文件夹复制到本机 C: 或 D: 磁盘后再运行。'
        )
    elif missing_runtime:
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
        # ``os.startfile`` exists only on Windows. Asking for it through ``getattr`` keeps this
        # module importable (and lintable) on Linux/macOS, where this branch cannot run anyway.
        open_url = getattr(os, 'startfile', None)
        if open_url is not None:
            with contextlib.suppress(OSError):
                open_url(WEBVIEW2_URL)


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
