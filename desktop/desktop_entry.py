"""Windows double-click entry point for the packaged 采析绘 build.

``backend/app.py``'s ``__main__`` is deliberately NOT reused: it opens the browser itself
and enables the Werkzeug reloader, which would spawn a second process and leave the console
window looking dead. This entry point owns the frozen-specific concerns instead:

* pick a writable data root (``%APPDATA%\\CaiXiHui`` by default, or the folder beside the
  exe when ``portable.txt`` is present) and export it before ``config`` is imported; if the
  preferred root refuses a write the next candidate is taken and the refusal is named —
  and when nothing takes a write the reason reaches a dialog, because a console window
  dies with the process and a double-click user would see only a flash;
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
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
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
    """The data root this app would like to use: the first entry of :func:`data_root_candidates`."""
    env = dict(os.environ if env is None else env)
    if appdata is not None:
        env['APPDATA'] = str(appdata)
    return data_root_candidates(app_dir_path, env=env, portable_marker=portable_marker)[0]


def _has_own_data(path: Path) -> bool:
    """Whether this candidate already holds a ``data/`` — i.e. someone's real history."""
    try:
        return (Path(path) / 'data').is_dir()
    except OSError:
        return False


def data_root_candidates(app_dir_path, *, env=None, portable_marker=None) -> list[Path]:
    """Every place the data could live, best first.

    An explicit ``CRAWLER_DATA_ROOT`` is the ONLY answer when it is set: a caller that asked for
    isolation (`/smoke-verify`, the UI tier) must never fall through into the shared AppData root,
    where startup would settle that user's live run as stale. Otherwise the AppData roots come
    first (a Program Files install stays writable without elevation), and whichever candidate
    ALREADY holds a ``data/`` beats an empty one — a fallback that only lasts one launch would
    show the user an empty canvas the next time a blocked folder happens to open up.
    """
    env = os.environ if env is None else env
    override = str(env.get('CRAWLER_DATA_ROOT') or '').strip()
    if override:
        return [Path(override).expanduser().resolve()]
    base = Path(app_dir_path).resolve()
    marker = Path(portable_marker) if portable_marker is not None else base / 'portable.txt'
    ordered: list[Path] = []
    if marker.exists():
        ordered.append(base)
    for parent in (env.get('APPDATA'), env.get('LOCALAPPDATA')):
        if parent:
            ordered.append(Path(parent) / APP_NAME)
    ordered.append(base)
    # Stable partition: roots that already hold data keep their relative order, then the rest.
    ordered.sort(key=lambda path: 0 if _has_own_data(path) else 1)
    seen: set[str] = set()
    unique = []
    for candidate in ordered:
        key = str(candidate).rstrip('\\/').lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


class DataRootError(RuntimeError):
    """No candidate data root would take a write.

    Carries every refusal by name so the user is told which folder was tried and what the
    OS said, instead of watching a console window appear and vanish.
    """

    def __init__(self, notes: list[str]) -> None:
        super().__init__('; '.join(notes))
        self.notes = list(notes)


def _root_is_writable(path: Path) -> str:
    """'' when ``path`` can be created and takes a file, else the OS's own reason.

    Creating the directory is not the test: a Program Files install lets a standard user make
    the folder in some policies and then refuses the first file inside it.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.write_probe'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
    except OSError as exc:
        return f'{path} — {exc}'
    return ''


def prepare_data_root(app_dir_path, *, env=None, portable_marker=None) -> tuple[Path, list[str]]:
    """The first candidate root that really takes a write, plus the named refusals above it.

    Returning the notes is deliberate: a silent fallback would leave the user looking for
    their data in the folder the launcher told them about.
    """
    notes = []
    for candidate in data_root_candidates(app_dir_path, env=env, portable_marker=portable_marker):
        reason = _root_is_writable(candidate)
        if not reason:
            return candidate, notes
        notes.append(reason)
    raise DataRootError(notes)


def write_startup_error(message: str, log_dirs) -> Path | None:
    """File the failure where the user can hand it over; the console will be gone."""
    for directory in log_dirs:
        try:
            directory = Path(directory)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / 'startup_error.log'
            with path.open('a', encoding='utf-8') as handle:
                handle.write(f'\n{time.strftime("%Y-%m-%d %H:%M:%S")}\n{message}\n')
            return path
        except Exception as exc:
            # A bad entry (None, a non-string) is a bug in this list, not a reason to lose the report.
            print(f'错误日志写不到 {directory}：{exc}', flush=True)
            continue
    return None


def error_log_dirs(data_root=None) -> list[Path]:
    """Where a startup failure may be filed, best for the user first.

    The data root is the folder the launcher just told the user about, so its ``logs/`` is
    where a maintainer would look; the AppData roots and the install folder cover a locked
    data root, and the temp folder is the one place Windows always allows.
    """
    dirs = []
    if data_root:
        dirs.append(Path(data_root) / 'logs')
    for parent in (os.environ.get('APPDATA'), os.environ.get('LOCALAPPDATA')):
        if parent:
            dirs.append(Path(parent) / APP_NAME)
    dirs.append(app_dir())
    dirs.append(Path(tempfile.gettempdir()) / APP_NAME)
    return dirs


def _message_box(message: str, title: str = '') -> None:
    """A blocking Windows dialog, frozen builds only: a source run already has a live terminal.

    Unattended callers (a build check, CI) must not stall on a dialog nobody is there to close.
    """
    if os.name != 'nt' or not is_frozen():
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title or f'{DISPLAY_NAME} 启动失败', 0x10)
    except Exception as exc:
        print(f'弹窗没能显示，原因只在控制台与日志里：{exc}', flush=True)


def _print_safe(text: str) -> None:
    """Print without letting the console's own encoding eat the report.

    A redirected stdout on a non-Chinese Windows falls back to the ANSI codepage and raises
    ``UnicodeEncodeError`` on the first Chinese character. The retry goes to the underlying
    BYTES buffer, not back through the stream that just failed — re-printing replacement text
    to the same broken writer would raise again, and a failure reporter that dies while
    reporting is the exact bug this file exists to fix.
    """
    try:
        print(text, flush=True)
        return
    except UnicodeError:
        pass
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    data = str(text).encode(encoding, errors='replace')
    buffer = getattr(sys.stdout, 'buffer', None)
    if buffer is not None:
        with contextlib.suppress(Exception):
            buffer.write(data + b'\n')
            buffer.flush()
        return
    with contextlib.suppress(Exception):
        print(data.decode(encoding, errors='replace'), flush=True)


def fail_loudly(message: str, log_dirs, *, detail: str = '', dialog=_message_box, title: str = '') -> Path | None:
    """File, dialog, then print a fatal failure. Never returns the process to a bare traceback.

    The dialog is the part that matters for a double-click: Windows destroys the console the
    instant the process exits, so a printed reason is a reason nobody sees. The file and the
    dialog are therefore produced BEFORE anything is printed, and ``detail`` (a traceback) goes
    to the console and the file only — a message box cannot scroll.
    """
    logged = write_startup_error(f'{message}\n{detail}'.strip(), log_dirs)
    dialog(message if not logged else f'{message}\n\n错误详情已写入：{logged}', title)
    _print_safe(message)
    if detail:
        _print_safe(detail)
    return logged


def data_root_refusal_message(notes, override: str = '') -> str:
    """The sentence a double-click user gets when nothing can be written.

    Split out of ``main`` because an override refusal needs DIFFERENT advice: telling a user whose
    ``CRAWLER_DATA_ROOT`` is unwritable to "put a portable.txt beside the exe" points them at a rule
    that no longer applies to them.
    """
    attempts = '\n'.join(f'  · {note}' for note in notes)
    if override:
        return (
            f'没有启动：你指定的数据目录 CRAWLER_DATA_ROOT={override} 不可写。\n\n{attempts}\n\n'
            '它不会被其它目录顶替（否则一次隔离运行会写进别人共享的数据根）。'
            '请把它改指向一个可写目录，或取消这个环境变量后重新双击。'
        )
    return (
        '没有启动：应用找不到任何可以写入的数据目录。\n\n'
        f'已尝试（按顺序）：\n{attempts}\n\n'
        '请给其中一个目录写入权限；或在 exe 同文件夹放一个空文件 portable.txt'
        '（数据就存在 exe 旁边）；或设置环境变量 CRAWLER_DATA_ROOT 指向可写目录。'
    )


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
def mutex_name_for(data_root=None) -> str:
    """The session mutex name for ONE data root.

    The name carries a hash of the root (not the path itself: ``Local\\`` names may not contain
    a backslash), because the app's own rule is one server per data root — a portable copy on a
    USB stick and an installed copy are two different answers to that question.
    """
    if not data_root:
        return MUTEX_NAME
    digest = hashlib.sha1(str(data_root).rstrip('\\/').lower().encode('utf-8')).hexdigest()[:12]
    return f'{MUTEX_NAME}-{digest}'


def acquire_instance_mutex(data_root=None):
    """``(handle, already_running)`` for this user's packaged app ON THIS DATA ROOT.

    A named mutex is per-session and dies with the process, so it has none of the stale
    lock-file failure modes. A root-blind name used to refuse the second copy on a mutex held
    by a totally different install, and then had nothing to show the user, because the running
    copy's ``instance.json`` lives in the other root. Non-Windows returns ``(None, False)``:
    a source run should not pretend to be a global singleton.
    """
    if os.name != 'nt':
        return None, False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, mutex_name_for(data_root))
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


def _open_existing_instance(data_root, *, dialog=_message_box, open_url=webbrowser.open) -> bool:
    """Open the already-running copy, or report by name that it could not be found.

    The not-found case is the one the user cannot diagnose alone: the mutex says another copy
    is running, the address file is not in the root THIS launch chose, and a console line about
    it dies with this process. So it is dialogued and filed, not printed.
    """
    payload = read_instance(data_root)
    url = str(payload.get('url') or '')
    if not url:
        fail_loudly(
            f'已有 {DISPLAY_NAME} 实例在运行，但本次使用的数据目录里没有它的地址记录：\n'
            f'  {data_root}\n'
            f'通常说明正在运行的那一份用的是另一个数据目录（例如一份装在 %APPDATA%，'
            f'这一份是便携拷贝）。\n请关闭旧窗口后再双击，或给这一份指定它自己的数据目录。',
            error_log_dirs(data_root),
            dialog=dialog,
            title=f'{DISPLAY_NAME} 已在运行',
        )
        return False
    _print_safe(f'{DISPLAY_NAME} 已在运行，正在打开：{url}')
    open_url(url)
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


def dependency_lines(report: dict) -> list:
    """The self-check as text lines — one source of wording for both print paths below."""
    return [
        '依赖自检（不影响启动，只说明哪类节点可用）：',
        '  Chrome: ' + ('已找到' if report.get('chrome') else '未找到（采集节点需要安装 Chrome）'),
        '  chromedriver: '
        + (report['driver'] if report.get('driver') else '未配置（首次采集会由 Selenium 自动下载匹配版本，需要联网）'),
        '  Ollama: ' + ('运行中' if report.get('ollama') else '未检测到（只影响本地模型节点；可改用 OpenRouter）'),
        '  xelatex: ' + (report['xelatex'] if report.get('xelatex') else '未找到（只影响 PDF / 论文成稿）'),
    ]


def print_dependency_report(report: dict) -> None:
    for line in dependency_lines(report):
        print(line, flush=True)


def _print_dependencies(app_dir_path) -> None:
    """Run the self-check and print it, on the background thread.

    It probes four filesystem locations and opens a TCP socket, so on a machine with a cold
    disk cache it is seconds — and it used to sit between picking the port and binding it,
    which is why the window sat there before the browser could connect. It is deliberately not
    a gate: whatever it finds, the server is already running. A failure inside the probe is
    reported as its own line rather than killing the thread silently, because the absence of
    the four lines is otherwise indistinguishable from a machine where the check passed quietly.

    One write, not five: Flask's own startup lines land on the same console from another
    thread, and five separate writes can be split apart mid-block.
    """
    try:
        report = dependency_report(app_dir_path)
    except Exception:  # a diagnostic must never break a start; the server is already running
        print(f'依赖自检未能完成：{traceback.format_exc(limit=1).strip()}', flush=True)
        return
    print('\n'.join(dependency_lines(report)), flush=True)


def sweep_startup_litter(install_dir) -> int:
    """Remove the empty ``tmp…`` folders a launch leaves beside the exe, and report how many.

    Measured: two per start, in the install folder, whatever TMP/TEMP/TMPDIR say — so they come from a
    library resolving its scratch directory before (or ignoring) the redirect above, while the process
    cwd is the exe folder. They are not ours to keep or to name: our own ``mkdtemp`` calls all pass a
    ``cixi-`` prefix, and these carry the bare ``tmp`` + 8 random characters shape.

    Only an **empty** directory matching that shape is removed, and a non-empty one is left exactly as
    it is — this is housekeeping, not a cleanup of anything a user might have put there.
    """
    removed = 0
    for holder in Path(install_dir).glob('tmp*'):
        if not holder.is_dir():
            continue
        with contextlib.suppress(OSError):
            if any(holder.iterdir()):
                continue
            holder.rmdir()
            removed += 1
    return removed


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
    # A redirected console on a non-Chinese Windows uses the ANSI codepage and raises on the
    # first Chinese character; the reports below must never be the thing that kills the launch.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stream.reconfigure(errors='replace')
    base = app_dir()
    resources = resource_dir()
    try:
        root, refusals = prepare_data_root(base)
    except DataRootError as exc:
        asked = str(os.environ.get('CRAWLER_DATA_ROOT') or '').strip()
        fail_loudly(data_root_refusal_message(exc.notes, asked), error_log_dirs())
        return 1
    os.environ['CRAWLER_DATA_ROOT'] = str(root)
    for note in refusals:
        # A fallback is stated, never silently taken: the user must know where their data went.
        _print_safe(f'该数据目录不可写，已改用下一个位置：{note}')
    if refusals:
        _print_safe(f'实际数据目录：{root}')
    # Matplotlib writes a font cache; keep it in the user's data root instead of the
    # (possibly read-only) install folder, and never open a GUI backend in a server.
    os.environ.setdefault('MPLCONFIGDIR', str(root / 'mplconfig'))
    os.environ.setdefault('MPLBACKEND', 'Agg')
    # Same reason, one level down: when the system temp directory is not writable (endpoint
    # protection denying `%TEMP%` — the same denial that made pip hang in a restricted workspace),
    # Python's tempfile falls back to the **current directory**, and `main()` chdir's to the install
    # folder just below. Measured on a real launch: an empty `tmp9xh5hzc1`-style directory beside
    # CaiXiHui.exe, one per start, in the folder users copy around. Scratch goes into the data root,
    # which is user state and is stripped from the deliverable before it is zipped.
    scratch = root / 'tmp'
    with contextlib.suppress(OSError):
        scratch.mkdir(parents=True, exist_ok=True)
    # Set, not setdefault: a frozen bundle owns its scratch, and the alternative is measured — with
    # `%TEMP%` denied, one empty `tmp…` directory appeared beside the exe **during startup**, before
    # any request. `tempfile` caches the directory it settled on (`tempdir`, and it resolves to the
    # current directory when the system one is unwritable), so the cache is dropped as well: without
    # that line the assignment changes nothing for anything that touched tempfile earlier.
    for _name in ('TMP', 'TEMP', 'TMPDIR'):
        os.environ[_name] = str(scratch)
    tempfile.tempdir = None
    stale = sweep_startup_litter(base)
    if stale:
        _print_safe(f'已清理上次运行留下的空临时目录：{stale} 个')
    with contextlib.suppress(OSError):
        os.chdir(base)

    handle, already_running = acquire_instance_mutex(root)
    if already_running:
        if handle:
            with contextlib.suppress(Exception):
                ctypes.windll.kernel32.CloseHandle(handle)
        _open_existing_instance(root)
        return 0

    port = None
    try:
        seeded = seed_user_data(resources / 'seed', root)
    except OSError as exc:
        # A demo workflow or a bundled model that will not copy is a loss of two nice-to-haves,
        # not of the app: start anyway and name what did not land.
        seeded = []
        print(f'首次示例文件未能放入数据目录（不影响使用）：{exc}', flush=True)
    with contextlib.suppress(OSError):
        (root / 'mplconfig').mkdir(parents=True, exist_ok=True)

    # Patch the two package-level facts that a frozen bundle cannot infer: relative
    # optional models are looked up beside the exe, and a chromedriver that does not
    # exist must be left blank so Selenium Manager can resolve it.
    try:
        import config

        config.BASE_DIR = str(base)
        config.DRIVER_PATH = find_driver(base)
    except Exception:
        fail_loudly(
            '启动失败：配置模块没有加载成功，数据目录与浏览器路径无法确定。请把日志文件发给维护者。',
            error_log_dirs(root),
            detail=traceback.format_exc(),
        )
        return 1

    # A BERT model pack the user unpacked beside the exe is otherwise invisible: the panel lists
    # models from the registry file, not from the filesystem. Runs after the data root is settled
    # and before the app is imported, so the first /api/models already sees the pack.
    try:
        from bert_pack import seed_registry

        ledger = seed_registry(root / 'data', base / 'bert_models')
    except Exception:
        # A pack that will not register is a lost optional feature, not a reason to not start:
        # the app works, uploading and crawling are unaffected, and the reason is printed.
        ledger = {
            'packs': 0,
            'added': [],
            'skipped': [],
            'untouched': f'登记失败：{traceback.format_exc(limit=1).strip()}',
        }
    if ledger['added']:
        print(f'已登记 BERT 模型包：{", ".join(ledger["added"])}', flush=True)
    if ledger['skipped']:
        print(f'模型包里这些名字已在注册表中，保留你原来的条目：{", ".join(ledger["skipped"])}', flush=True)
    if ledger['packs'] and ledger['untouched']:
        print(f'BERT 模型包未写入注册表：{ledger["untouched"]}', flush=True)

    try:
        from app import app as flask_app
        from app import start_background_services
    except Exception:
        fail_loudly(
            '启动失败：应用模块没有加载成功。请把日志文件发给维护者。',
            error_log_dirs(root),
            detail=traceback.format_exc(),
        )
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
        fail_loudly(
            f'没有启动：端口 {preferred} 起连续 {PORT_ATTEMPTS} 个端口都被占用，本地服务器无法监听。\n'
            '请关闭其它占端口的程序后重试。',
            error_log_dirs(root),
        )
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
    threading.Thread(target=_print_dependencies, args=(base,), daemon=True).start()

    no_browser = os.environ.get('CIXI_NO_BROWSER') == '1' or '--no-browser' in argv
    if not no_browser:
        threading.Thread(target=_wait_and_open, args=(url,), daemon=True).start()

    # The same startup work ``python app.py`` does in its ``__main__``: this launcher imports the
    # module and runs Flask itself, so ``__main__`` never ran here and the packaged app served
    # requests with NO scheduled-task clock (the 定时任务 panel said so, truthfully).
    try:
        start_background_services()
    except Exception:
        # Retention and the queue are conveniences; the clock is the one thing whose absence the
        # user sees in the panel. Say what failed and keep serving — but never hide it.
        print('后台服务启动失败（定时任务可能不会触发）：', file=sys.stderr, flush=True)
        traceback.print_exc()

    try:
        flask_app.run(host='127.0.0.1', port=port, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        pass
    except Exception:
        fail_loudly(
            '服务异常退出。请把日志文件发给维护者。',
            error_log_dirs(root),
            detail=traceback.format_exc(),
        )
        return 1
    finally:
        clear_instance(root, port)
        # Self-clean what this launch created; a killed process never gets the chance, which is why
        # the same sweep also runs at start.
        sweep_startup_litter(base)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SystemExit:
        # The ordinary exit path: main() already reported anything worth reporting.
        raise
    except BaseException:
        # The traceback is printed and filed by fail_loudly, so the exit adds no second chain.
        fail_loudly('启动异常终止。请把日志文件发给维护者。', error_log_dirs(), detail=traceback.format_exc())
        raise SystemExit(1) from None
