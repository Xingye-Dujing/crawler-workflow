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
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

APP_NAME = 'CaiXiHui'
DISPLAY_NAME = '采析绘'
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


def data_root() -> Path:
    override = str(os.environ.get('CRAWLER_DATA_ROOT') or '').strip()
    if override:
        return Path(override).expanduser().resolve()
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
    if '--doctor' in argv:
        try:
            return doctor()
        except Exception:
            fail('环境检查失败。', root, traceback.format_exc())
            return 1

    seed_user_data(root)
    try:
        from core import config

        config.DRIVER_PATH = ''
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
    try:
        import webview

        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
        webview.create_window(
            DISPLAY_NAME,
            url,
            width=1280,
            height=820,
            min_size=(1024, 700),
            text_select=True,
        )
        webview.start(private_mode=False, storage_path=str(root / 'webview'))
    except Exception:
        fail('窗口没能打开。请把日志发给维护者。', root, traceback.format_exc())
        return 1
    finally:
        with contextlib.suppress(OSError):
            server.shutdown()
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
