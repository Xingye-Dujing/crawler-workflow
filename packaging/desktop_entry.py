"""Windows double-click entry point for the packaged 采析绘 build.

``backend/app.py``'s ``__main__`` is deliberately NOT reused: it opens the browser itself
and enables the Werkzeug reloader, which would spawn a second process and leave the console
window looking dead. This entry point owns the frozen-specific concerns instead:

* pick a writable data root (``%APPDATA%\\CaiXiHui`` by default, or the folder beside the
  exe when ``portable.txt`` is present) and export it before ``config`` is imported;
* seed the demo workflow and the small scikit-learn models on first run, without ever
  overwriting a file the user already has;
* find a real chromedriver or leave the path blank so Selenium Manager can resolve one;
* enforce one local server per data root, bind ``127.0.0.1`` only, and open the browser
  once the server answers;
* keep the console visible: closing it stops the server, which is the one "quit" a
  non-technical user can find without a tray icon dependency.

Everything here is import-safe (no server starts at import) so the packaging contract can
be tested by ``tests/unit/test_desktop_packaging.py`` without a frozen build.
"""

from __future__ import annotations

import atexit
import contextlib
import ctypes
import json
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = 'CaiXiHui'
DISPLAY_NAME = '采析绘'
PREFERRED_PORT = 5000
PORT_ATTEMPTS = 30
MUTEX_NAME = 'Local\\CaiXiHuiDesktop'
BROWSER_WAIT_SECONDS = 60.0


# ─── paths ────────────────────────────────────────────────────
def is_frozen() -> bool:
    """Whether this process is the PyInstaller build rather than a source checkout."""
    return bool(getattr(sys, 'frozen', False))


def app_dir() -> Path:
    """The folder the user double-clicked: the exe's folder, or the repo root in source."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    """Read-only bundled assets (``static``, ``seed``, ``samples``)."""
    bundled = getattr(sys, '_MEIPASS', None)
    return Path(bundled).resolve() if bundled else app_dir()


def choose_data_root(app_dir_path, *, env=None, appdata=None, portable_marker=None) -> Path:
    """Where ``data/`` and ``logs/`` live.

    Precedence: an explicit ``CRAWLER_DATA_ROOT`` (tests, power users) → the exe folder when
    ``portable.txt`` sits beside it → ``%APPDATA%\\CaiXiHui``. The AppData default keeps a
    Program Files install writable without elevation; the portable marker keeps a USB copy
    self-contained.
    """
    env = os.environ if env is None else env
    override = str(env.get('CRAWLER_DATA_ROOT') or '').strip()
    if override:
        return Path(override).expanduser().resolve()
    base = Path(app_dir_path).resolve()
    marker = Path(portable_marker) if portable_marker is not None else base / 'portable.txt'
    if marker.exists():
        return base
    appdata_value = appdata if appdata is not None else env.get('APPDATA')
    parent = Path(appdata_value) if appdata_value else Path.home()
    return parent / APP_NAME


def find_driver(app_dir_path, *, env=None, legacy: str | None = None) -> str:
    """An existing chromedriver path, or '' to let Selenium Manager resolve one.

    A missing driver is normal on a fresh machine: Selenium 4 downloads the matching
    driver on first use. Returning '' is therefore the honest answer, not a guessed path
    that would make every crawl fail with "file not found". ``legacy`` is injectable so a
    test machine that happens to have the old hardcoded path cannot hide this branch.
    """
    env = os.environ if env is None else env
    candidates = [env.get('CRAWLER_DRIVER_PATH'), env.get('CHROMEDRIVER_PATH')]
    candidates.append(str(Path(app_dir_path) / 'drivers' / 'chromedriver.exe'))
    candidates.append(legacy if legacy is not None else r'C:\Program Files\Google\Chrome\Application\chromedriver.exe')
    for value in candidates:
        if not value:
            continue
        path = Path(str(value)).expanduser()
        if path.is_file():
            return str(path.resolve())
    return ''


def seed_user_data(seed_dir, data_root) -> list[str]:
    """Copy first-run assets into a fresh user data directory; never overwrite.

    Only two small things are seeded: the bibliometric demonstration workflow (so the
    canvas has a working example) and the scikit-learn ``.pkl`` models (12 MB, used by the
    dependency-free 情绪/倾向 modes). The multi-gigabyte BERT checkpoints stay a separate
    optional download; seeding a registry that points at them would promise models that
    are not there.
    """
    seed = Path(seed_dir)
    data = Path(data_root) / 'data'
    copied = []
    pairs = (
        (seed / 'workflows', data / 'workflows'),
        (seed / 'models', data / 'models'),
    )
    for source_dir, target_dir in pairs:
        if not source_dir.is_dir():
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(source_dir.iterdir()):
            if not source.is_file():
                continue
            target = target_dir / source.name
            if target.exists():
                continue
            shutil.copy2(source, target)
            copied.append(source.name)
    return copied


def pick_port(preferred: int = PREFERRED_PORT, attempts: int = PORT_ATTEMPTS, host: str = '127.0.0.1') -> int | None:
    """The first local port we can bind, or ``None`` when the range is exhausted.

    Binding probes the actual address Flask will bind. The short socket lifetime is a
    probe, not a reservation; the mutex is what prevents a second copy of this app from
    racing for the same slot.
    """
    start = max(1, min(int(preferred or PREFERRED_PORT), 65535))
    for port in range(start, min(65536, start + max(1, attempts))):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe, contextlib.suppress(OSError):
            probe.bind((host, port))
            return port
    return None


# ─── one instance per data root ───────────────────────────────
def acquire_instance_mutex():
    """``(handle, already_running)`` for this user's packaged app.

    A named mutex is per-session and dies with the process, so it has none of the stale
    lock-file failure modes. Non-Windows returns ``(None, False)``: this entry is for the
    Windows build, and a source run should not pretend to be a global singleton.
    """
    if os.name != 'nt':
        return None, False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return handle, kernel32.GetLastError() == 183


def _instance_path(data_root) -> Path:
    return Path(data_root) / 'instance.json'


def write_instance(data_root, port: int) -> None:
    path = _instance_path(data_root)
    payload = {'pid': os.getpid(), 'port': int(port), 'url': f'http://127.0.0.1:{int(port)}/'}
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload), encoding='utf-8')
        os.replace(temporary, path)


def read_instance(data_root) -> dict:
    try:
        value = json.loads(_instance_path(data_root).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def clear_instance(data_root, port: int | None = None) -> None:
    """Remove our instance file, never another process's."""
    path = _instance_path(data_root)
    current = read_instance(data_root)
    if current.get('pid') != os.getpid():
        return
    if port is not None and current.get('port') != int(port):
        return
    with contextlib.suppress(OSError):
        path.unlink()


def _open_existing_instance(data_root) -> bool:
    """Open the already-running copy, or explain why it could not be found."""
    payload = read_instance(data_root)
    url = str(payload.get('url') or '')
    if not url:
        print(f'已有 {DISPLAY_NAME} 实例在运行，但找不到它的地址。请关闭旧窗口后重试。', flush=True)
        return False
    print(f'{DISPLAY_NAME} 已在运行，正在打开：{url}', flush=True)
    webbrowser.open(url)
    return True


# ─── first-run diagnostics ───────────────────────────────────
def _chrome_candidates(env=None):
    env = os.environ if env is None else env
    names = ('CHROME_PATH', 'CHROME_BIN')
    paths = [env.get(name) for name in names]
    for base in (env.get('PROGRAMFILES'), env.get('PROGRAMFILES(X86)'), env.get('LOCALAPPDATA')):
        if base:
            paths.append(str(Path(base) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'))
    return [Path(p) for p in paths if p]


def dependency_report(app_dir_path, *, env=None) -> dict:
    """What is present/missing, as facts for the console (never a blocking gate).

    Crawling needs Chrome and later a matching chromedriver; local LLM nodes need Ollama;
    PDF/paper nodes need xelatex. Uploading and analysing files works without any of them,
    so the launcher starts regardless and only tells the user what each status affects.
    """
    env = os.environ if env is None else env
    chrome = next((str(p) for p in _chrome_candidates(env) if p.is_file()), '')
    driver = find_driver(app_dir_path, env=env)
    xelatex = shutil.which('xelatex') or ''
    if not xelatex:
        for base in (env.get('LOCALAPPDATA'), env.get('PROGRAMFILES')):
            if not base:
                continue
            for name in ('MiKTeX/miktex/bin/x64/xelatex.exe', 'MiKTeX 2.9/miktex/bin/x64/xelatex.exe'):
                candidate = Path(base) / name
                if candidate.is_file():
                    xelatex = str(candidate)
                    break
            if xelatex:
                break
    ollama = False
    with contextlib.suppress(OSError), socket.create_connection(('127.0.0.1', 11434), timeout=0.25):
        ollama = True
    return {'chrome': chrome, 'driver': driver, 'xelatex': xelatex, 'ollama': ollama}


def print_dependency_report(report: dict) -> None:
    print('依赖自检（不影响启动，只说明哪类节点可用）：', flush=True)
    print(
        '  Chrome: ' + ('已找到' if report.get('chrome') else '未找到（采集节点需要安装 Chrome）'),
        flush=True,
    )
    print(
        '  chromedriver: '
        + (report['driver'] if report.get('driver') else '未配置（首次采集会由 Selenium 自动下载匹配版本，需要联网）'),
        flush=True,
    )
    print(
        '  Ollama: ' + ('运行中' if report.get('ollama') else '未检测到（只影响本地模型节点；可改用 OpenRouter）'),
        flush=True,
    )
    print(
        '  xelatex: ' + (report['xelatex'] if report.get('xelatex') else '未找到（只影响 PDF / 论文成稿）'),
        flush=True,
    )


def _wait_and_open(url: str) -> None:
    deadline = time.monotonic() + BROWSER_WAIT_SECONDS
    probe = url.rstrip('/') + '/api/config'
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(probe, timeout=1.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(0.5)
    print(f'服务器已启动，但浏览器没有在 {int(BROWSER_WAIT_SECONDS)} 秒内确认可访问。', flush=True)
    print(f'请手动打开：{url}', flush=True)


# ─── startup ─────────────────────────────────────────────────
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    base = app_dir()
    resources = resource_dir()
    root = choose_data_root(base)
    root.mkdir(parents=True, exist_ok=True)
    os.environ['CRAWLER_DATA_ROOT'] = str(root)
    # Matplotlib writes a font cache; keep it in the user's data root instead of the
    # (possibly read-only) install folder, and never open a GUI backend in a server.
    os.environ.setdefault('MPLCONFIGDIR', str(root / 'mplconfig'))
    os.environ.setdefault('MPLBACKEND', 'Agg')
    with contextlib.suppress(OSError):
        os.chdir(base)

    handle, already_running = acquire_instance_mutex()
    if already_running:
        if handle:
            with contextlib.suppress(Exception):
                ctypes.windll.kernel32.CloseHandle(handle)
        _open_existing_instance(root)
        return 0

    port = None
    seeded = seed_user_data(resources / 'seed', root)
    with contextlib.suppress(OSError):
        (root / 'mplconfig').mkdir(parents=True, exist_ok=True)

    # Patch the two package-level facts that a frozen bundle cannot infer: relative
    # optional models are looked up beside the exe, and a chromedriver that does not
    # exist must be left blank so Selenium Manager can resolve it.
    import config

    config.BASE_DIR = str(base)
    config.DRIVER_PATH = find_driver(base)

    try:
        from app import app as flask_app
    except Exception:
        traceback.print_exc()
        print('\n启动失败：应用模块没有加载成功。请把上面的错误信息发给维护者。', flush=True)
        if is_frozen():
            with contextlib.suppress(Exception):
                input('按回车关闭窗口…')
        return 1

    # Flask's root_path is inside the bundle; make the bundled assets explicit.
    bundled_static = resources / 'static'
    if bundled_static.is_dir():
        flask_app.static_folder = str(bundled_static)

    requested = os.environ.get('PORT') or str(PREFERRED_PORT)
    try:
        preferred = int(str(requested).strip() or PREFERRED_PORT)
    except ValueError:
        preferred = PREFERRED_PORT
    port = pick_port(preferred)
    if port is None:
        print(f'端口 {preferred} 起连续 {PORT_ATTEMPTS} 个端口都被占用，无法启动本地服务器。', flush=True)
        return 1

    write_instance(root, port)
    atexit.register(clear_instance, root, port)
    url = f'http://127.0.0.1:{port}/'

    with contextlib.suppress(Exception):
        ctypes.windll.kernel32.SetConsoleTitleW(f'{DISPLAY_NAME} - {url}')

    print(f'{DISPLAY_NAME} 已启动：{url}', flush=True)
    print(f'数据目录：{root}', flush=True)
    if seeded:
        print(f'已放入首次示例文件：{", ".join(seeded)}', flush=True)
    print('关闭此窗口即可停止服务（运行中的数据会保留，下次可续跑）。', flush=True)
    print_dependency_report(dependency_report(base))

    no_browser = os.environ.get('CIXI_NO_BROWSER') == '1' or '--no-browser' in argv
    if not no_browser:
        threading.Thread(target=_wait_and_open, args=(url,), daemon=True).start()

    try:
        flask_app.run(host='127.0.0.1', port=port, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        print('\n服务异常退出。请把上面的错误信息发给维护者。', flush=True)
        if is_frozen():
            with contextlib.suppress(Exception):
                input('按回车关闭窗口…')
        return 1
    finally:
        clear_instance(root, port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
