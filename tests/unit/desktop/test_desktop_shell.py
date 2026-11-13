"""The desktop shell bridge and the tray's delivery rules, without a real tray.

Two halves:

* ``services/desktop`` is the seam the engine notifies through. Its contract is small but load
  bearing: no shell means a no-op, and a notifier that raises may never take down the worker thread
  that just finished a multi-hour crawl.
* ``desktop/tray.py`` builds a Windows tray (pystray) or macOS notifications. A real tray needs a
  desktop session, so the backend is injected; what is pinned here is the shape the launchers rely
  on — the menu's three answers, the (message, title) order pystray expects, and a failure that is a
  sentence rather than an exception.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import ModuleType

import pytest

from i18n import t
from services import desktop

REPO = Path(__file__).resolve().parents[3]
DESKTOP = REPO / 'desktop'
pytestmark = pytest.mark.unit


def _tray_module():
    """Import ``desktop/tray.py`` by path (``desktop/`` is not on sys.path in the test process)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location('desktop_tray_contract', DESKTOP / 'tray.py')
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules['desktop_tray_contract'] = module
    spec.loader.exec_module(module)
    return module


class FakeMenu:
    SEPARATOR = '·'

    def __init__(self, *items):
        self.items = list(items)


class FakeMenuItem:
    def __init__(self, text, action, default=False):
        self.text = text
        self.action = action
        self.default = default


class FakeIcon:
    def __init__(self, name, image, title, menu):
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.notified = []
        self.stopped = False
        self.running = threading.Event()

    def run(self):
        self.running.set()

    def stop(self):
        self.stopped = True

    def notify(self, message, title=None):
        self.notified.append((title, message))


def _fake_pystray(monkeypatch):
    module = ModuleType('pystray')
    module.Menu = FakeMenu
    module.MenuItem = FakeMenuItem
    module.Icon = FakeIcon
    monkeypatch.setitem(sys.modules, 'pystray', module)
    return module


# ─── services.desktop ───


class TestTheNotifier:
    def test_with_no_shell_nothing_happens(self):
        desktop.clear_notifier()
        assert desktop.active() is False
        assert desktop.notify('标题', '正文') is False

    def test_an_installed_shell_receives_the_words(self):
        seen = []
        desktop.set_notifier(lambda title, message: seen.append((title, message)))
        try:
            assert desktop.active() is True
            assert desktop.notify('运行完成', '工作流 A') is True
        finally:
            desktop.clear_notifier()
        assert seen == [('运行完成', '工作流 A')]

    def test_a_broken_shell_never_reaches_the_run_thread(self):
        def explode(title, message):
            raise RuntimeError('tray died')

        desktop.set_notifier(explode)
        try:
            assert desktop.notify('x', 'y') is False
        finally:
            desktop.clear_notifier()


# ─── desktop/tray.py ───


class TestTheWindowsTray:
    def test_it_starts_the_icon_with_the_three_answers(self, monkeypatch):
        _fake_pystray(monkeypatch)
        tray = _tray_module()
        shown, quit_called, opened = [], [], []
        shell = tray.DesktopShell(
            title='采析绘',
            icon_path=DESKTOP.parent / 'backend' / 'static' / 'icon.png',
            on_show=lambda: shown.append(1),
            on_quit=lambda: quit_called.append(1),
            on_open_data=lambda: opened.append(1),
            platform='win32',
        )
        monkeypatch.setattr(shell, '_icon_image', lambda image_module: object())
        assert shell.start() == ''
        assert shell.mode == 'tray'
        icon = shell._icon
        assert icon.running.wait(2), 'the icon must be running on its own thread'
        texts = [item.text for item in icon.menu.items if isinstance(item, FakeMenuItem)]
        assert texts == [t('desktop.show'), t('desktop.openData'), t('desktop.quit')]
        for item in icon.menu.items:
            if isinstance(item, FakeMenuItem):
                item.action(icon, item)
        assert shown == [1] and quit_called == [1] and opened == [1]
        shell.stop()
        assert icon.stopped is True

    def test_notify_keeps_pystrays_message_then_title_order(self, monkeypatch):
        _fake_pystray(monkeypatch)
        tray = _tray_module()
        shell = tray.DesktopShell(title='采析绘', platform='win32')
        monkeypatch.setattr(shell, '_icon_image', lambda image_module: object())
        assert shell.start() == ''
        shell.notify('运行完成', '工作流 A 已完成')
        assert shell._icon.notified == [('运行完成', '工作流 A 已完成')]

    def test_a_missing_backend_is_a_sentence_not_a_crash(self, monkeypatch):
        monkeypatch.setitem(sys.modules, 'pystray', None)
        tray = _tray_module()
        shell = tray.DesktopShell(title='采析绘', platform='win32')
        reason = shell.start()
        assert '托盘' in reason
        assert shell.mode == ''
        shell.notify('标题', '正文')  # must not raise


class TestTheMacShell:
    def test_it_is_notification_only(self):
        tray = _tray_module()
        shell = tray.DesktopShell(title='采析绘', platform='darwin')
        assert shell.start() == ''
        assert shell.mode == 'notifications'

    def test_applescript_quoting(self):
        tray = _tray_module()
        assert tray.applescript_string('a "b" \\ c') == '"a \\"b\\" \\\\ c"'


class TestOtherPlatforms:
    def test_a_host_without_a_desktop_shell_says_so(self):
        tray = _tray_module()
        shell = tray.DesktopShell(title='采析绘', platform='linux')
        assert 'linux' in shell.start()
        assert shell.mode == ''
        shell.notify('标题', '正文')  # no-op, never raises


class TestTheMenuTheme:
    """The native menu is drawn by Windows; the only say we have is uxtheme's process-wide mode."""

    def test_a_light_system_is_left_alone(self, monkeypatch):
        tray = _tray_module()
        monkeypatch.setattr(tray, 'windows_prefers_dark', lambda: False)
        assert tray.prefer_dark_menus('win32') is False

    def test_a_non_windows_host_asks_uxtheme_nothing(self, monkeypatch):
        tray = _tray_module()
        asked = []
        monkeypatch.setattr(tray, 'windows_prefers_dark', lambda: asked.append(1) or True)
        assert tray.prefer_dark_menus('linux') is False
        assert asked == []

    def test_the_registry_answer_maps_zero_to_dark(self, monkeypatch):
        tray = _tray_module()
        module = ModuleType('winreg')
        module.HKEY_CURRENT_USER = 'HKCU'

        class Key:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        module.OpenKey = lambda root, path: Key()
        module.QueryValueEx = lambda key, name: (0, 4)
        monkeypatch.setitem(sys.modules, 'winreg', module)
        assert tray.windows_prefers_dark() is True
        module.QueryValueEx = lambda key, name: (1, 4)
        assert tray.windows_prefers_dark() is False

    def test_a_missing_registry_value_means_light(self, monkeypatch):
        tray = _tray_module()
        module = ModuleType('winreg')
        module.HKEY_CURRENT_USER = 'HKCU'
        module.OpenKey = lambda root, path: (_ for _ in ()).throw(OSError('no key'))
        monkeypatch.setitem(sys.modules, 'winreg', module)
        assert tray.windows_prefers_dark() is False


class TestTheRunOutcomeNotification:
    """``engine.run`` decides WHEN; the shell decides HOW. The decision is what this pins."""

    @pytest.fixture()
    def run_module(self, monkeypatch):
        from engine import run as run_engine

        sent = []
        monkeypatch.setattr(desktop, 'active', lambda: True)
        monkeypatch.setattr(desktop, 'notify', lambda title, message='': sent.append((title, message)) and True)
        for key, value in (('total_nodes', 3), ('completed_nodes', 3), ('failed_nodes', 0)):
            monkeypatch.setitem(run_engine.execution_state, key, value)
        return run_engine, sent

    def test_a_finished_run_says_so_once(self, run_module):
        run_engine, sent = run_module
        run_engine._notify_run_outcome('工作流 A', run_engine.RUN_COMPLETED)
        assert sent == [
            (t('desktop.runDoneTitle'), t('desktop.runDoneBody', name='工作流 A', done=3, total=3)),
        ]

    def test_a_failed_run_names_the_failed_count(self, run_module):
        run_engine, sent = run_module
        run_engine.execution_state['failed_nodes'] = 2
        run_engine._notify_run_outcome('工作流 A', run_engine.RUN_FAILED)
        assert sent == [
            (
                t('desktop.runFailedTitle'),
                t('desktop.runFailedBody', name='工作流 A', failed=2, done=3, total=3),
            ),
        ]

    def test_a_stop_is_not_news(self, run_module):
        run_engine, sent = run_module
        run_engine._notify_run_outcome('工作流 A', run_engine.RUN_INTERRUPTED)
        assert sent == []

    def test_a_refused_canvas_does_not_pop_up(self, run_module):
        run_engine, sent = run_module
        run_engine.execution_state['total_nodes'] = 0
        run_engine._notify_run_outcome('工作流 A', run_engine.RUN_FAILED)
        assert sent == []

    def test_an_untitled_workflow_still_has_a_name(self, run_module):
        run_engine, sent = run_module
        run_engine._notify_run_outcome('', run_engine.RUN_COMPLETED)
        assert sent[0][1] == t('desktop.runDoneBody', name=t('desktop.untitled'), done=3, total=3)

    def test_a_headless_host_sends_nothing(self, monkeypatch, run_module):
        run_engine, sent = run_module
        monkeypatch.setattr(desktop, 'active', lambda: False)
        run_engine._notify_run_outcome('工作流 A', run_engine.RUN_COMPLETED)
        assert sent == []
