"""The native window host, exercised without opening a real WebView2 window.

The contract worth pinning is what the two executables depend on: the page URL is handed to
WebView2 (never to a browser), storage is persistent, the X can be refused while work runs, and a
machine that cannot host the window is told so by name instead of showing an empty frame.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / 'desktop' / 'native_window.py'


@pytest.fixture()
def window():
    """The module under test, with any real ``webview`` kept out of the way."""
    spec = importlib.util.spec_from_file_location('native_window_under_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Events:
    def __init__(self):
        self.shown = _Event()
        self.loaded = _Event()
        self.closing = _Event()
        self.closed = _Event()


class _Event:
    def __init__(self):
        self.handlers = []
        self.flag = False

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def set(self, *args):
        self.flag = True
        for handler in list(self.handlers):
            handler(*args)

    def wait(self, timeout=None):
        return self.flag


class _FakeWindow:
    def __init__(self, recorded, **_kwargs):
        self.recorded = recorded
        self.events = _Events()
        self.destroyed = 0
        self.native = types.SimpleNamespace(Handle=types.SimpleNamespace(ToInt32=lambda: 4242))

    def destroy(self):
        self.destroyed += 1
        # The real backends raise ``closed`` here (winforms FormClosed, Cocoa windowWillClose).
        # Firing it in the double is what keeps the programmatic-close cases honest.
        self.events.closed.set()


@pytest.fixture()
def fake_webview(monkeypatch, window):
    """Install a fake host and record what ``run`` asks it to do."""
    recorded = {}
    created = []

    def create_window(title, url, **kwargs):
        recorded['window'] = {'title': title, 'url': url, **kwargs}
        fake = _FakeWindow(recorded, **kwargs)
        created.append(fake)
        recorded['last_window'] = fake
        return fake

    def start(func=None, **kwargs):
        recorded['start'] = kwargs
        created[-1].events.shown.set()
        if not recorded.get('fail_load'):
            created[-1].events.loaded.set()
        # The real loop blocks until the window closes; a test may need to look at the window
        # while it is "open", which is exactly this instant.
        hook = recorded.get('on_start')
        if hook is not None:
            hook(created[-1])
        if func is not None:
            func()

    module = types.ModuleType('webview')
    module.create_window = create_window
    module.start = start
    module.settings = {}
    monkeypatch.setitem(sys.modules, 'webview', module)
    return recorded


def test_the_page_goes_into_webview2_not_a_browser(window, fake_webview):
    reason = window.run('采析绘', 'http://127.0.0.1:3968/token/', storage='C:/state')
    assert reason == ''
    assert fake_webview['window']['url'] == 'http://127.0.0.1:3968/token/'
    assert fake_webview['window']['min_size'] == (900, 620)
    assert fake_webview['start']['gui'] == 'edgechromium'
    assert fake_webview['start']['private_mode'] is False, 'private mode would forget localStorage'
    assert fake_webview['start']['storage_path'] == 'C:/state'


def test_the_application_window_opens_maximized(window, fake_webview):
    reason = window.run('采析绘', 'http://127.0.0.1:5000/', maximized=True)
    assert reason == ''
    assert fake_webview['window']['maximized'] is True
    assert window.run('采析绘', 'http://127.0.0.1:5000/') == ''
    assert fake_webview['window']['maximized'] is False, 'the installer keeps its one-screen size'


def test_the_handle_is_captured_for_the_folder_picker(window, fake_webview):
    assert window.handle() == 0
    seen = []
    fake_webview['on_start'] = lambda _fake: seen.append(window.handle())
    window.run('采析绘', 'http://127.0.0.1:3968/token/')
    assert seen == [4242], 'the picker needs the window handle while the window is open'
    assert window.handle() == 0, 'a closed window owns nothing'


def test_close_ends_the_gui_loop_even_when_the_x_is_guarded(window, fake_webview):
    verdict = {}

    def during(fake):
        verdict['refused'] = fake.events.closing.handlers[0]()
        window.close()
        verdict['forced'] = fake.events.closing.handlers[0]()

    fake_webview['on_start'] = during
    window.run('采析绘', 'http://127.0.0.1:3968/token/', on_close=lambda: False)
    assert verdict['refused'] is False, 'a running job refuses the user close'
    assert fake_webview['last_window'].destroyed == 1
    assert verdict['forced'] is True, 'the program can always close itself'


def test_exit_on_close_ends_the_process_without_a_window(window, fake_webview, monkeypatch):
    """The application window is the program: a destroyed window ends it, a hidden one does not."""
    ended = []
    monkeypatch.setattr(window, 'terminate_process', lambda: ended.append(True))

    def during(fake):
        fake.events.shown.set()  # minimise/restore keep the loop alive and end nothing
        fake.events.closed.set()

    fake_webview['on_start'] = during
    window.run('采析绘', 'http://127.0.0.1:5000/', exit_on_close=True)
    assert ended == [True]


def test_exit_on_close_ignores_a_programmatic_close(window, fake_webview, monkeypatch):
    """A page that never loads closes itself; that must still reach the caller's error dialog."""
    ended = []
    monkeypatch.setattr(window, 'terminate_process', lambda *args: ended.append(args))
    fake_webview['on_start'] = lambda _fake: window.close()
    assert window.run('采析绘', 'http://127.0.0.1:5000/', exit_on_close=True) == ''
    assert ended == [], 'run() still has to report the failure before the process ends'


def test_a_window_that_never_loads_is_reported_and_closed(window, fake_webview):
    """A blank window on a machine whose WebView2 cannot start is the "flashed and did nothing"
    failure: the page's loaded event is the proof, and without it the loop must not stay open."""
    fake_webview['fail_load'] = True
    reason = window.run('采析绘', 'http://127.0.0.1:3968/token/')
    assert '页面没有加载出来' in reason
    assert fake_webview['last_window'].destroyed == 1


def test_storage_lives_under_the_user_profile(window, monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.delenv('APPDATA', raising=False)
    monkeypatch.delenv('CRAWLER_DATA_ROOT', raising=False)
    assert Path(window.storage_dir('webview-installer')) == tmp_path / 'CaiXiHui' / 'webview-installer'


def test_storage_falls_back_when_local_appdata_is_blocked(window, monkeypatch, tmp_path):
    """A locked-down machine denied creating anything under LocalAppData; the profile must move,
    not stop the window (“Storage path … is not writable”)."""
    blocker = tmp_path / 'blocked'
    blocker.write_text('not a directory', encoding='utf-8')
    monkeypatch.setenv('LOCALAPPDATA', str(blocker / 'sub'))
    monkeypatch.setenv('APPDATA', str(tmp_path / 'roaming'))
    monkeypatch.delenv('CRAWLER_DATA_ROOT', raising=False)
    assert Path(window.storage_dir('webview')) == tmp_path / 'roaming' / 'CaiXiHui' / 'webview'


def test_storage_falls_back_to_the_application_data_root(window, monkeypatch, tmp_path):
    blocker = tmp_path / 'blocked'
    blocker.write_text('not a directory', encoding='utf-8')
    monkeypatch.setenv('LOCALAPPDATA', str(blocker / 'local'))
    monkeypatch.setenv('APPDATA', str(blocker / 'roaming'))
    monkeypatch.setenv('CRAWLER_DATA_ROOT', str(tmp_path / 'data'))
    assert Path(window.storage_dir('webview')) == tmp_path / 'data' / 'webview'


def test_complaining_about_a_missing_runtime_does_not_require_startfile(window, monkeypatch):
    """``os.startfile`` is Windows-only; the notice must still be assembled off Windows.

    The branch that offers the WebView2 download is reachable only on Windows, but importing and
    linting the module happens on every runner. Asking for the attribute instead of dereferencing
    it keeps that path from turning an importable module into a platform-specific one.
    """
    monkeypatch.setattr(window, 'alert', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(window, 'os', types.SimpleNamespace())
    window.complain('WebView2 runtime is missing')  # must not raise


def test_a_machine_without_the_host_is_refused_by_name(window, monkeypatch):
    monkeypatch.setitem(sys.modules, 'webview', None)
    reason = window.run('采析绘', 'http://127.0.0.1:3968/token/')
    assert reason.startswith('无法加载 WebView2 窗口组件')
    assert window.available() is False


def test_activating_a_missing_pid_is_false_not_an_exception(window):
    assert window.activate(0) is False


def test_a_windowed_build_gets_real_streams(window, monkeypatch):
    """PyInstaller's windowed bootloader leaves ``sys.stdout`` as None; ``print`` would raise."""
    monkeypatch.setattr(sys, 'stdout', None)
    monkeypatch.setattr(sys, 'stderr', None)
    window.ensure_streams()
    assert sys.stdout is not None and sys.stderr is not None
    print('ok')  # must not raise
