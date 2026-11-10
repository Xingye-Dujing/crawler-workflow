"""macOS entry point for the packaged 采析绘 build (PyInstaller .app bundle).

The Windows launcher (``desktop_entry.py``) owns named mutexes, MessageBoxW and the WebView2
window; none of those exist on macOS. This entry reuses the backend's own server and first-run
seed data, then shows the page in a native WKWebView through pywebview's Cocoa backend.

There is no online installer on macOS: the release ships a DMG built by ``desktop/build_macos.py``
in GitHub Actions, and the app is dragged into Applications. Data lives in
``~/Library/Application Support/CaiXiHui``; ``CRAWLER_DATA_ROOT`` overrides it exactly as on
Windows.
"""

from __future__ import annotations

import contextlib
import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import native_window

APP_NAME = 'CaiXiHui'
DISPLAY_NAME = '采析绘'
BUNDLE_ID = 'com.caixihui.desktop'
PREFERRED_PORT = 5000
PORT_ATTEMPTS = 30


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def resource_dir() -> Path:
    """Read-only bundled assets (``static``, ``seed``, ``samples``, catalogue)."""
    bundled = getattr(sys, '_MEIPASS', None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parents[1]


def default_data_root() -> Path:
    return Path.home() / 'Library' / 'Application Support' / APP_NAME


def _takes_write(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.write-test'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink()
    except OSError:
        return False
    return True


def _configured_data_root() -> Path | None:
    """The folder the online installer chose, written beside the .app (or into Resources).

    The full-DMG build has no such file and uses the default. Reading it BEFORE ``core.config`` is
    imported is what makes a custom data folder survive a later double-click from Finder, where no
    ``CRAWLER_DATA_ROOT`` environment exists.
    """
    executable = Path(sys.executable).resolve()
    candidates: list[Path] = []
    if len(executable.parents) >= 4 and executable.parents[2].suffix == '.app':
        candidates.append(executable.parents[3] / 'data-root.txt')
        candidates.append(executable.parents[1] / 'Resources' / 'data-root.txt')
    for path in candidates:
        try:
            text = path.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if text:
            return Path(text).expanduser().resolve()
    try:
        preference = Path.home() / 'Library' / 'Preferences' / f'{BUNDLE_ID}.plist'
        payload = plistlib.loads(preference.read_bytes())
    except (OSError, ValueError):
        payload = {}
    configured = str(payload.get('CRAWLER_DATA_ROOT') or '').strip() if isinstance(payload, dict) else ''
    return Path(configured).expanduser().resolve() if configured else None


def data_root() -> Path:
    override = str(os.environ.get('CRAWLER_DATA_ROOT') or '').strip()
    if override:
        return Path(override).expanduser().resolve()
    configured = _configured_data_root()
    if configured is not None:
        return configured
    return default_data_root()


def log_dirs(root: Path) -> list[Path]:
    return [root / 'startup_error.log', Path.home() / 'Library' / 'Logs' / APP_NAME / 'startup_error.log']


def _alert(message: str, title: str = DISPLAY_NAME) -> None:
    """A native notice before/without the webview window, through AppleScript."""
    escaped = str(message).replace('\\', '\\\\').replace('"', '\\"')
    script = f'display alert "{title}" message "{escaped}" as critical'
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(['osascript', '-e', script], timeout=10, check=False)


def fail(message: str, root: Path, detail: str = '') -> None:
    text = message if not detail else f'{message}\n\n{detail}'
    for path in log_dirs(root):
        with contextlib.suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + '\n', encoding='utf-8')
            break
    print(text, file=sys.stderr)
    _alert(message)


def pick_port(preferred: int = PREFERRED_PORT, attempts: int = PORT_ATTEMPTS) -> int | None:
    for port in range(preferred, min(65536, preferred + attempts)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe, contextlib.suppress(OSError):
            probe.bind(('127.0.0.1', port))
            return port
    return None


def seed_user_data(root: Path) -> None:
    """Copy the demo workflow and small scikit-learn models on first run (never overwrite)."""
    from desktop_entry import seed_user_data as seed

    with contextlib.suppress(OSError):
        seed(resource_dir() / 'seed', root)


def apply_component_env(root: Path) -> None:
    """Let a double-click find Chrome/Node installed by the online installer.

    ``desktop_entry.apply_component_env`` is the one implementation of that rule (it reads
    ``install-manifest.json`` before ``core.config`` snapshots the environment). Reusing it keeps
    Windows and macOS from disagreeing about which component the app will actually launch.
    """
    from desktop_entry import apply_component_env as apply_env

    with contextlib.suppress(OSError):
        apply_env(root)


def seed_models(root: Path) -> None:
    """Register BERT packs the user placed in ``<data>/bert_models``.

    macOS has no writable folder beside the .app, so the online installer and a manual unpack both
    use the user's data root. Registry paths are absolute; ``resolve_bert_model`` and the probe both
    accept them, and the app bundle stays replaceable.
    """
    from desktop_entry import seed_bert_models

    models = Path(root) / 'bert_models'
    with contextlib.suppress(OSError):
        seed_bert_models(root, root, models_dir=models, root_label=models.as_posix())


def doctor() -> int:
    from i18n import set_lang, t
    from services.components.probe import environment

    set_lang('zh')
    report = environment()
    for row in report.get('capabilities') or ():
        row['label_text'] = t(str(row.get('label_key') or ''))
        row['reason_text'] = t(str(row.get('reason_key') or ''), **(row.get('reason_params') or {}))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = data_root()
    if not _takes_write(root):
        fail(f'数据目录不可写：{root}\n请把 CRAWLER_DATA_ROOT 指向一个可写目录。', Path.home(), traceback.format_exc())
        return 1
    os.environ['CRAWLER_DATA_ROOT'] = str(root)
    os.environ.setdefault('MPLCONFIGDIR', str(root / 'mplconfig'))
    os.environ.setdefault('MPLBACKEND', 'Agg')
    scratch = root / 'tmp'
    with contextlib.suppress(OSError):
        scratch.mkdir(parents=True, exist_ok=True)
        (root / 'mplconfig').mkdir(parents=True, exist_ok=True)
    for name in ('TMP', 'TEMP', 'TMPDIR'):
        os.environ[name] = str(scratch)
    tempfile.tempdir = None
    with contextlib.suppress(OSError):
        os.chdir(root)

    base = resource_dir()
    backend = base / 'backend'
    if backend.is_dir() and str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    # Before core.config is imported: it snapshots CHROME_PATH/CIXI_NODE_BIN/etc. at import time.
    apply_component_env(root)
    # A BERT pack in the user's data root is invisible without a registry entry; register it before
    # the app is imported, exactly as the Windows launcher does.
    seed_models(root)
    if '--doctor' in argv:
        try:
            return doctor()
        except Exception:
            fail('环境检查失败。', root, traceback.format_exc())
            return 1

    seed_user_data(root)
    try:
        from core import config

        # The online installer exports CIXI_DRIVER_PATH for the chromedriver it installed. Keeping
        # it is what makes 安装器的组件 real on macOS; clearing it let Selenium Manager fetch a
        # driver outside the installer's tree. Blank (本机 mode) stays blank as before.
        config.DRIVER_PATH = str(os.environ.get('CIXI_DRIVER_PATH') or '').strip()
    except Exception:
        fail('启动失败：配置模块没有加载成功。请把日志发给维护者。', root, traceback.format_exc())
        return 1
    try:
        from app import app as flask_app
        from app import start_background_services
    except Exception:
        fail('启动失败：应用模块没有加载成功。请把日志发给维护者。', root, traceback.format_exc())
        return 1
    static = base / 'static'
    if static.is_dir():
        flask_app.static_folder = str(static)

    port = pick_port()
    if port is None:
        fail('没有启动：本地端口都被占用了。', root)
        return 1
    from werkzeug.serving import make_server

    server = make_server('127.0.0.1', port, flask_app, threaded=True)
    with contextlib.suppress(Exception):
        start_background_services()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{port}/'
    exit_code = 0

    def release_window() -> None:
        with contextlib.suppress(OSError):
            server.shutdown()
        with contextlib.suppress(OSError):
            server.server_close()

    try:
        import webview

        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
        window = webview.create_window(
            DISPLAY_NAME,
            url,
            width=1280,
            height=820,
            min_size=(1024, 700),
            text_select=True,
            maximized=True,
        )

        def closed() -> None:
            # The window is the program: a destroyed window ends the process even if the Cocoa host
            # keeps a thread or its loop alive. Minimising does not fire this event.
            release_window()
            native_window.terminate_process()

        window.events.closed += closed
        webview.start(private_mode=False, storage_path=str(root / 'webview'))
    except Exception:
        fail('窗口没能打开。请把日志发给维护者。', root, traceback.format_exc())
        exit_code = 1
    finally:
        release_window()
        # Same rule as the Windows launcher: a closed window (or a failed one) ends the process.
        # The Cocoa host leaves threads behind, and the interpreter would otherwise wait for them
        # after ``main`` returns. Minimising keeps the event loop alive and never reaches this line.
        native_window.terminate_process(exit_code)


if __name__ == '__main__':
    raise SystemExit(main())
