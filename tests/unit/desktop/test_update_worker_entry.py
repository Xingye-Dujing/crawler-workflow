"""The launcher's half of the updater: the worker mode and the in-progress swap wait.

``--update-worker`` is the same executable with no window and no Flask app. It must be dispatched
BEFORE the instance mutex (a second copy of the program would otherwise report "already running"
and quit, and the download would never happen) and before the app is imported. The window/mutex
order is asserted from the source: running ``main`` for real here would mutate this process's
environment (data root, TMP, cwd) for every later test.
"""

import importlib.util
import re
import time
from pathlib import Path

import pytest

from services import update_job, update_worker

PACKAGING = Path(__file__).resolve().parents[3] / 'desktop'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def desktop():
    return _load('desktop_entry', PACKAGING / 'desktop_entry.py')


def test_the_marker_path_is_the_one_the_updater_writes(desktop, tmp_path):
    """Two spellings of the swap marker would make the launcher wait for a file nobody creates."""
    assert desktop._update_marker(tmp_path) == update_job.marker_file(tmp_path)
    assert desktop._update_marker(tmp_path).name == update_job.MARKER_NAME


def test_no_marker_means_no_wait(desktop, tmp_path):
    started = time.monotonic()
    desktop._wait_for_swapper(tmp_path, timeout=30)
    assert time.monotonic() - started < 1.0


def test_a_finished_swap_releases_the_launch(desktop, tmp_path):
    marker = desktop._update_marker(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text('123', encoding='utf-8')

    def clear() -> None:
        time.sleep(0.6)
        marker.unlink()

    import threading

    threading.Thread(target=clear, daemon=True).start()
    started = time.monotonic()
    desktop._wait_for_swapper(tmp_path, timeout=10)
    assert 0.3 < time.monotonic() - started < 5


def test_a_marker_nobody_clears_does_not_lock_the_user_out(desktop, tmp_path):
    marker = desktop._update_marker(tmp_path)
    marker.parent.mkdir(parents=True)
    marker.write_text('123', encoding='utf-8')
    started = time.monotonic()
    desktop._wait_for_swapper(tmp_path, timeout=0.5)
    assert time.monotonic() - started < 5


def test_the_worker_mode_passes_the_job_file(desktop, monkeypatch):
    calls = []
    monkeypatch.setattr(update_worker, 'main', lambda argv: calls.append(argv) or 0)
    assert desktop._run_update_worker(['--update-worker', 'job.json']) == 0
    assert calls == [['job.json']]


def test_a_worker_with_no_job_argument_is_still_answered(desktop, monkeypatch):
    calls = []
    monkeypatch.setattr(update_worker, 'main', lambda argv: calls.append(argv) or 2)
    assert desktop._run_update_worker(['--update-worker']) == 2
    assert calls == [[]]


def test_a_broken_worker_is_reported_not_raised(desktop, monkeypatch):
    def explode(argv):
        raise RuntimeError('no store')

    monkeypatch.setattr(update_worker, 'main', explode)
    monkeypatch.setattr(update_job, 'log', lambda *a, **k: None)
    assert desktop._run_update_worker(['--update-worker', 'job.json']) == 1


class TestTheDispatchOrder:
    SOURCE = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')

    def test_the_worker_runs_before_the_single_instance_mutex(self):
        """The worker is a second process of the same program: the mutex would turn it away."""
        worker = self.SOURCE.index("if '--update-worker' in argv:")
        mutex = self.SOURCE.index('handle, already_running = acquire_instance_mutex(root)')
        assert worker < mutex

    def test_the_worker_runs_before_the_app_is_imported(self):
        worker = self.SOURCE.index("if '--update-worker' in argv:")
        app_import = self.SOURCE.index('from app import app as flask_app')
        assert worker < app_import

    def test_a_swap_in_progress_is_waited_for_before_the_mutex(self):
        wait = self.SOURCE.index('_wait_for_swapper(root)')
        mutex = self.SOURCE.index('handle, already_running = acquire_instance_mutex(root)')
        assert wait < mutex

    def test_the_window_close_hands_a_staged_update_over(self):
        assert 'update.on_app_close()' in self.SOURCE
        assert re.search(r'on_closed=closing', self.SOURCE), 'the close path is not the one wired'

    def test_the_restart_ends_through_the_launcher_shutdown_hook(self):
        """A hard kill skips the cleanup the swapper depends on (exe handle, instance file)."""
        assert 'register_shutdown' in self.SOURCE
        macos = (PACKAGING / 'macos_entry.py').read_text(encoding='utf-8')
        assert 'register_shutdown' in macos
        assert 'update.on_app_close()' in macos
        assert "'--update-worker' in argv" in macos
