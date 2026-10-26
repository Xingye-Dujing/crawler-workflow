"""The packaged Windows build's own contract, testable without PyInstaller.

The build is a folder, not a one-file exe, and size is a feature: these tests pin the
launcher's writable-data choices, its first-run seeding (never overwrite), its driver
fallback, and the spec's exclusion list so a later dependency cannot silently pull a
multi-gigabyte stack back into ``dist/``.

Nothing here runs the app's own server or needs a frozen exe, and ``main()`` is not called; one test
stands up a throwaway stdlib HTTP server because the launcher's "is it up yet?" probe has to be
answered by something before its browser hand-off can be measured.
"""

import contextlib
import importlib.util
import json
import socket
import struct
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
PACKAGING = REPO / 'desktop'


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def desktop():
    return _load('desktop_entry', PACKAGING / 'desktop_entry.py')


@pytest.fixture(scope='module')
def prune_module():
    return _load('prune_dist', PACKAGING / 'prune_dist.py')


class TestDataRoot:
    def test_an_explicit_override_wins(self, desktop, tmp_path):
        chosen = desktop.choose_data_root(tmp_path, env={'CRAWLER_DATA_ROOT': str(tmp_path / 'mine')})
        assert chosen == (tmp_path / 'mine').resolve()

    def test_portable_marker_keeps_everything_beside_the_exe(self, desktop, tmp_path):
        (tmp_path / 'portable.txt').write_text('', encoding='utf-8')
        chosen = desktop.choose_data_root(tmp_path, env={'APPDATA': str(tmp_path / 'appdata')})
        assert chosen == tmp_path.resolve()

    def test_the_default_is_appdata_not_program_files(self, desktop, tmp_path):
        chosen = desktop.choose_data_root(tmp_path, env={'APPDATA': str(tmp_path / 'appdata')})
        assert chosen == (tmp_path / 'appdata' / 'CaiXiHui')

    def test_a_stale_override_is_created_not_guessed(self, desktop, tmp_path):
        """The caller mkdirs the answer; this only pins that it is the literal path."""
        chosen = desktop.choose_data_root(tmp_path, env={'CRAWLER_DATA_ROOT': str(tmp_path / 'new-root')})
        assert not chosen.exists()
        assert chosen.name == 'new-root'

    def test_a_data_folder_beside_the_exe_keeps_the_next_launch_in_the_same_place(self, desktop, tmp_path):
        """A fallback that lasts one launch is a data-loss trap: if the denied AppData opens up
        later, the next start would look at an empty folder and the user's canvas is gone."""
        (tmp_path / 'data').mkdir()
        chosen = desktop.choose_data_root(tmp_path, env={'APPDATA': str(tmp_path / 'appdata')})
        assert chosen == tmp_path.resolve()

    def test_the_refused_preference_is_followed_by_localappdata_then_the_exe_folder(self, desktop, tmp_path):
        """A managed machine can lock or redirect %APPDATA%; the order of escape routes is
        the product answer, so it is pinned rather than left to whatever the loop hits first."""
        appdata = tmp_path / 'appdata'
        local = tmp_path / 'local'
        candidates = desktop.data_root_candidates(
            tmp_path,
            env={'APPDATA': str(appdata), 'LOCALAPPDATA': str(local)},
        )
        assert candidates == [appdata / 'CaiXiHui', local / 'CaiXiHui', tmp_path.resolve()]

    def test_a_refused_root_falls_back_and_says_so(self, desktop, tmp_path, monkeypatch):
        """Silently relocating the user's data is the failure mode this exists to avoid."""
        appdata = tmp_path / 'appdata'
        local = tmp_path / 'local'
        blocked = appdata / 'CaiXiHui'

        def fake_writable(path):
            return '' if Path(path) != blocked else f'{path} — [WinError 5] 拒绝访问'

        monkeypatch.setattr(desktop, '_root_is_writable', fake_writable)
        root, refusals = desktop.prepare_data_root(
            tmp_path,
            env={'APPDATA': str(appdata), 'LOCALAPPDATA': str(local)},
        )
        assert root == local / 'CaiXiHui'
        assert len(refusals) == 1 and 'WinError 5' in refusals[0]

    def test_an_explicit_override_is_never_replaced_by_a_fallback(self, desktop, tmp_path):
        """Isolation is what CRAWLER_DATA_ROOT means here: falling through to the shared AppData
        root would let a smoke run settle that user's live run as stale. So it is refused by name."""
        blocked = tmp_path / 'blocked'
        blocked.write_text('not a directory', encoding='utf-8')
        candidates = desktop.data_root_candidates(
            tmp_path,
            env={'CRAWLER_DATA_ROOT': str(blocked), 'APPDATA': str(tmp_path / 'shared')},
        )
        assert candidates == [blocked.resolve()]
        with pytest.raises(desktop.DataRootError) as caught:
            desktop.prepare_data_root(tmp_path, env={'CRAWLER_DATA_ROOT': str(blocked)})
        assert len(caught.value.notes) == 1 and str(blocked) in caught.value.notes[0]

    def test_the_root_that_already_holds_data_beats_a_writable_empty_one(self, desktop, tmp_path):
        """The same durability rule read from the other side: Roaming with history comes first."""
        appdata = tmp_path / 'appdata'
        (appdata / 'CaiXiHui' / 'data').mkdir(parents=True)
        chosen = desktop.data_root_candidates(
            tmp_path / 'exe',
            env={'APPDATA': str(appdata), 'LOCALAPPDATA': str(tmp_path / 'local')},
        )
        assert chosen[0] == appdata / 'CaiXiHui'

    def test_the_probe_actually_writes_a_file(self, desktop, tmp_path):
        """mkdir is not the test: a protected folder can accept a directory and refuse the first
        file in it. Nothing may be left behind either."""
        assert desktop._root_is_writable(tmp_path) == ''
        assert not (tmp_path / '.write_probe').exists()

    def test_a_path_that_is_a_file_refuses_with_its_own_name(self, desktop, tmp_path):
        blocker = tmp_path / 'runs.db'
        blocker.write_text('x', encoding='utf-8')
        reason = desktop._root_is_writable(blocker)
        assert reason and str(blocker) in reason

    def test_the_mutex_is_per_data_root_not_per_session(self, desktop):
        """One server per data root is the app's own rule. A root-blind name let an installed copy
        refuse a portable one, which then had no address file to show — the address lives in the
        other root — and the user saw a window flash and nothing else."""
        first = desktop.mutex_name_for(r'F:\app\CaiXiHui')
        second = desktop.mutex_name_for(r'C:\Users\me\AppData\Roaming\CaiXiHui')
        assert first != second
        assert first == desktop.mutex_name_for('F:\\app\\CaiXiHui\\'), 'one root, one name'
        assert '\\' not in first[len('Local\\') :], 'mutex names may not contain a backslash'

    def test_no_writable_root_refuses_with_every_attempt_named(self, desktop, tmp_path, monkeypatch):
        monkeypatch.setattr(desktop, '_root_is_writable', lambda path: f'{path} — 拒绝访问')
        with pytest.raises(desktop.DataRootError) as caught:
            desktop.prepare_data_root(
                tmp_path, env={'APPDATA': str(tmp_path / 'a'), 'LOCALAPPDATA': str(tmp_path / 'b')}
            )
        assert len(caught.value.notes) == 3


class TestFailureReporting:
    def test_the_error_lands_in_the_first_directory_that_takes_it(self, desktop, tmp_path):
        blocked = tmp_path / 'blocked'
        blocked.write_text('a file, not a directory', encoding='utf-8')
        written = desktop.write_startup_error('boom', [blocked, tmp_path / 'logs'])
        assert written is not None and written.parent.name == 'logs'
        assert 'boom' in written.read_text(encoding='utf-8')

    def test_the_refusal_advice_answers_the_refusal_that_happened(self, desktop):
        """An override refusal must not tell the user to put a portable.txt beside the exe: that
        rule does not apply to them, and a wrong instruction costs a phone call."""
        notes = [r'C:\Users\me\AppData\Roaming\CaiXiHui — [WinError 5] 拒绝访问']
        plain = desktop.data_root_refusal_message(notes)
        assert '已尝试（按顺序）' in plain and 'portable.txt' in plain and notes[0] in plain

        asked = desktop.data_root_refusal_message([r'D:\locked — 拒绝访问'], override=r'D:\locked')
        assert 'CRAWLER_DATA_ROOT' in asked and '不会被其它目录顶替' in asked
        assert 'portable.txt' not in asked

    def test_the_dialog_and_the_log_happen_before_the_print(self, desktop, tmp_path, monkeypatch):
        """Printing first is what hid the original failure: a console on a non-UTF codepage raises
        on the first Chinese character, and the report would stop right there with no log, no dialog."""
        order = []
        monkeypatch.setattr(desktop, '_print_safe', lambda text: order.append('print'))
        desktop.fail_loudly(
            '启动失败：数据目录不可写。',
            [tmp_path],
            detail='PermissionError: 5',
            dialog=lambda message, title='': order.append('dialog'),
        )
        assert order[:2] == ['dialog', 'print'], 'the message and its detail, in that order, after the report'

    def test_a_console_that_cannot_encode_the_message_still_reports(self, desktop, tmp_path, monkeypatch):
        """``_print_safe`` must degrade to replacement bytes, never lose the report."""

        class _BrokenStdout:
            encoding = 'cp1252'

            def write(self, data):
                raise UnicodeEncodeError('cp1252', str(data), 0, 1, 'no such byte')

        monkeypatch.setattr(desktop.sys, 'stdout', _BrokenStdout())
        asked = []
        logged = desktop.fail_loudly(
            '启动失败：数据目录不可写。',
            [tmp_path],
            dialog=lambda message, title='': asked.append(message),
        )
        assert asked and logged is not None

    def test_a_directory_list_item_that_is_not_a_path_does_not_swallow_the_report(self, desktop, tmp_path):
        written = desktop.write_startup_error('boom', [None, tmp_path])
        assert written is not None and written.parent == tmp_path

    def test_the_data_root_logs_come_first_and_the_temp_folder_is_the_backstop(self, desktop, tmp_path, monkeypatch):
        monkeypatch.setenv('APPDATA', str(tmp_path / 'roaming'))
        dirs = desktop.error_log_dirs(tmp_path)
        assert dirs[0] == tmp_path / 'logs'
        assert dirs[1] == tmp_path / 'roaming' / 'CaiXiHui'
        assert str(tempfile.gettempdir()) in str(dirs[-1])

    def test_a_fatal_error_prints_the_detail_but_dialogs_only_the_reason(self, desktop, tmp_path):
        """A traceback in a message box cannot be scrolled or copied; the console that
        carried it is about to close, which is why the file exists."""
        asked = []
        logged = desktop.fail_loudly(
            '启动失败：数据目录不可写。',
            [tmp_path / 'logs'],
            detail='Traceback...\nPermissionError: 5',
            dialog=lambda message, title='': asked.append((message, title)),
        )
        assert asked and 'PermissionError' not in asked[0][0]
        assert str(logged) in asked[0][0]
        text = logged.read_text(encoding='utf-8')
        assert 'PermissionError' in text and '数据目录不可写' in text

    def test_a_failure_still_reports_when_no_directory_would_take_the_log(self, desktop, tmp_path):
        blocked = tmp_path / 'blocked'
        blocked.write_text('not a directory', encoding='utf-8')
        asked = []
        logged = desktop.fail_loudly(
            '启动失败。',
            [blocked],
            dialog=lambda message, title='': asked.append(message),
        )
        assert logged is None
        assert asked == ['启动失败。']

    def test_the_real_dialog_opens_only_for_the_frozen_build(self, desktop, monkeypatch):
        """A source run has a terminal that stays up; an unattended build check that hit a failure
        would otherwise stall on a box nobody is there to dismiss. When the build IS frozen the box
        must really be asked for — that dialog is the only notice that outlives the console."""
        monkeypatch.setattr(desktop, 'is_frozen', lambda: False)
        desktop._message_box('启动失败。')  # must return, not raise and not block

        seen = []
        windll = types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=lambda *args: seen.append(args)))
        monkeypatch.setattr(desktop, 'is_frozen', lambda: True)
        monkeypatch.setattr(desktop.ctypes, 'windll', windll)
        desktop._message_box('启动失败。', '采析绘 已在运行')
        assert len(seen) == 1 and seen[0][1] == '启动失败。' and seen[0][2] == '采析绘 已在运行'

    def test_a_dialog_that_cannot_be_shown_says_so(self, desktop, monkeypatch, capsys):
        def _refuse(*args):
            raise OSError('no window station')

        windll = types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=_refuse))
        monkeypatch.setattr(desktop, 'is_frozen', lambda: True)
        monkeypatch.setattr(desktop.ctypes, 'windll', windll)
        desktop._message_box('启动失败。')
        assert '弹窗没能显示' in capsys.readouterr().out


class TestAlreadyRunning:
    def test_the_found_address_is_opened(self, desktop, tmp_path):
        desktop.write_instance(tmp_path, 5057)
        opened = []
        verdict = desktop._open_existing_instance(tmp_path, dialog=lambda *a: None, open_url=opened.append)
        assert verdict is True
        assert opened == ['http://127.0.0.1:5057/']

    def test_a_missing_address_is_dialogued_not_printed(self, desktop, tmp_path):
        """The mutex said another copy is running; a console line about it dies with this process,
        and the address file lives in the OTHER copy's data root — so it is named, loudly."""
        asked = []
        verdict = desktop._open_existing_instance(
            tmp_path,
            dialog=lambda message, title='': asked.append((message, title)),
            open_url=lambda url: None,
        )
        assert verdict is False
        assert asked and str(tmp_path) in asked[0][0] and '已在运行' in asked[0][1]


class TestDriverFallback:
    def test_an_existing_configured_driver_wins(self, desktop, tmp_path):
        driver = tmp_path / 'chromedriver.exe'
        driver.write_bytes(b'x')
        assert desktop.find_driver(tmp_path, env={'CHROMEDRIVER_PATH': str(driver)}) == str(driver.resolve())

    def test_a_missing_driver_is_blank_so_selenium_manager_can_resolve_it(self, desktop, tmp_path):
        """Returning a guessed Windows path made every crawl fail with file-not-found
        on a machine that had Chrome but no driver; '' is the Selenium Manager signal."""
        assert (
            desktop.find_driver(
                tmp_path,
                env={'CHROMEDRIVER_PATH': str(tmp_path / 'ghost.exe')},
                legacy='',
            )
            == ''
        )

    def test_a_driver_dropped_beside_the_exe_is_found(self, desktop, tmp_path):
        drivers = tmp_path / 'drivers'
        drivers.mkdir()
        driver = drivers / 'chromedriver.exe'
        driver.write_bytes(b'x')
        assert desktop.find_driver(tmp_path, env={}) == str(driver.resolve())


class TestSeedData:
    def test_first_run_copies_the_demo_and_models_without_overwriting(self, desktop, tmp_path):
        seed = tmp_path / 'seed'
        (seed / 'workflows').mkdir(parents=True)
        (seed / 'models').mkdir(parents=True)
        (seed / 'workflows' / 'demo.json').write_text('{"nodes": []}', encoding='utf-8')
        (seed / 'models' / 'm.pkl').write_bytes(b'model')
        root = tmp_path / 'root'
        copied = desktop.seed_user_data(seed, root)
        assert sorted(copied) == ['demo.json', 'm.pkl']
        assert (root / 'data' / 'workflows' / 'demo.json').is_file()
        assert (root / 'data' / 'models' / 'm.pkl').read_bytes() == b'model'

        # A user-edited copy is the user's; re-running the launcher must not reset it.
        (root / 'data' / 'workflows' / 'demo.json').write_text('{"nodes": ["mine"]}', encoding='utf-8')
        copied_again = desktop.seed_user_data(seed, root)
        assert copied_again == []
        assert (root / 'data' / 'workflows' / 'demo.json').read_text(encoding='utf-8') == '{"nodes": ["mine"]}'

    def test_an_empty_seed_is_not_an_error(self, desktop, tmp_path):
        assert desktop.seed_user_data(tmp_path / 'missing', tmp_path / 'root') == []


@pytest.mark.enable_socket
class TestPortSelection:
    def test_an_occupied_port_is_skipped(self, desktop):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.bind(('127.0.0.1', 0))
            held.listen(1)
            occupied = held.getsockname()[1]
            chosen = desktop.pick_port(occupied, attempts=5)
        assert chosen is not None and chosen != occupied

    def test_a_free_port_is_returned(self, desktop):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(('127.0.0.1', 0))
            free = probe.getsockname()[1]
        assert desktop.pick_port(free, attempts=2) == free


class TestPackagingContract:
    def test_the_spec_builds_a_folder_and_excludes_the_giant_optional_stacks(self):
        spec = (PACKAGING / 'caixihui.spec').read_text(encoding='utf-8')
        assert 'COLLECT(' in spec, 'the build is onedir, not a single-file exe'
        assert 'onefile' not in spec.lower()
        assert 'console=True' in spec
        for excluded in ('torch', 'transformers', 'sentence_transformers', 'pyarrow', 'mitmproxy', 'uiautomation'):
            assert repr(excluded) in spec or f"'{excluded}'" in spec, f'{excluded} is not excluded'
        assert 'requirements-runtime.txt' in (PACKAGING / 'README.md').read_text(encoding='utf-8')
        assert "'static'" in spec and "'seed/models'" in spec
        runtime = (PACKAGING / 'requirements-runtime.txt').read_text(encoding='utf-8')
        declarations = [
            line.split('#', 1)[0].strip().lower() for line in runtime.splitlines() if line.split('#', 1)[0].strip()
        ]
        names = {line.split('==', 1)[0].split('>', 1)[0].strip() for line in declarations}
        for absent in ('torch', 'transformers', 'sentence-transformers', 'pyarrow', 'mitmproxy', 'pytest', 'ruff'):
            assert absent not in names, f'{absent} leaked into the runtime requirements'
        for present in ('flask', 'pandas', 'numpy', 'scipy', 'scikit-learn', 'selenium', 'jieba', 'snownlp'):
            assert present in names, f'{present} is missing from the runtime requirements'

    def test_the_launcher_binds_loopback_and_never_starts_the_reloader(self):
        source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
        assert "host='127.0.0.1'" in source
        assert '0.0.0.0' not in source
        assert 'use_reloader=False' in source
        assert 'CIXI_NO_BROWSER' in source
        assert 'CRAWLER_DATA_ROOT' in source

    def test_no_startup_path_can_exit_as_a_bare_traceback(self):
        """A double-click's console dies with the process, so an unhandled exception is
        literally invisible: the user reports "a window flashed and nothing happened".
        The data root must be probed (not blind-mkdir'd) and every exit must be reported."""
        source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
        assert 'root.mkdir(parents=True, exist_ok=True)' not in source, 'the data root is created blind again'
        assert 'prepare_data_root(base)' in source
        assert 'except BaseException' in source, 'the entry point can crash bare again'
        # Counted, not just present: a single remaining use (the definition) would pass a substring test.
        assert source.count('fail_loudly(') >= 6, 'a startup exit path lost its loud report'
        # The pause-on-error was an input() on a window that is already closing.
        assert "input('按回车关闭窗口" not in source

    def test_the_pruner_removes_dead_platform_trees_and_keeps_runtime_ones(self, prune_module, tmp_path):
        internal = tmp_path / '_internal'
        dead_linux = internal / 'selenium' / 'webdriver' / 'common' / 'linux'
        dead_tests = internal / 'matplotlib' / 'tests'
        keep_manager = internal / 'selenium' / 'webdriver' / 'common' / 'windows' / 'selenium-manager.exe'
        for directory in (dead_linux, dead_tests):
            directory.mkdir(parents=True)
            (directory / 'payload.bin').write_bytes(b'x' * 100)
        keep_manager.parent.mkdir(parents=True)
        keep_manager.write_bytes(b'manager')
        removed = prune_module.prune(tmp_path)
        names = {name.replace('\\', '/') for name, _ in removed}
        assert 'selenium/webdriver/common/linux' in names
        assert 'matplotlib/tests' in names
        assert not dead_linux.exists() and not dead_tests.exists()
        assert keep_manager.is_file(), 'the Windows Selenium Manager was pruned'

    def test_the_pruner_clears_the_state_a_verification_run_left_behind(self, prune_module, tmp_path):
        """The mandated acceptance double-click WRITES into the delivery folder, and the zip and the
        installer pack that folder. Shipping it would hand every user the maintainer's runs.db,
        datasets and saved logins — and the launcher's existing-data rule would then keep that
        folder as their data home for good."""
        (tmp_path / '_internal').mkdir()
        (tmp_path / 'data' / 'cookies').mkdir(parents=True)
        (tmp_path / 'data' / 'runs.db').write_bytes(b'secret' * 20)
        (tmp_path / 'data' / 'cookies' / 'weibo.json').write_text('{}', encoding='utf-8')
        (tmp_path / 'logs').mkdir()
        (tmp_path / 'logs' / 'app.log').write_text('run', encoding='utf-8')
        (tmp_path / 'mplconfig').mkdir()  # an empty directory is still state that must not ship
        (tmp_path / 'instance.json').write_text('{}', encoding='utf-8')
        (tmp_path / 'startup_error.log').write_text('boom', encoding='utf-8')
        # The user's own choices are not state: both must survive a prune.
        (tmp_path / 'portable.txt').write_text('', encoding='utf-8')
        (tmp_path / 'drivers').mkdir()
        (tmp_path / 'drivers' / 'chromedriver.exe').write_bytes(b'driver')

        prune_module.prune(tmp_path)
        for stale in ('data', 'logs', 'mplconfig', 'instance.json', 'startup_error.log'):
            assert not (tmp_path / stale).exists(), f'{stale} would ship to every user'
        assert (tmp_path / 'portable.txt').exists() and (tmp_path / 'drivers' / 'chromedriver.exe').is_file()


class TestTheSelfCheckNeverDelaysTheBind:
    """Four filesystem probes and a TCP connect used to run between picking the port and
    binding it, so the window sat there for seconds before the browser could reach the app."""

    def test_the_probe_runs_after_the_bind_not_before_it(self):
        source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
        thread = source.index('threading.Thread(target=_print_dependencies')
        assert 'print_dependency_report(dependency_report(base))' not in source, 'the check is back on the bind path'
        assert thread < source.index('flask_app.run('), 'the self-check must not precede the bind'
        # What still has to stay synchronous, because the server needs the answer: the driver
        # lookup that feeds ``config.DRIVER_PATH`` (its last reference is the one in ``main()``).
        assert source.rindex('find_driver(') < thread

    def test_the_words_are_the_ones_the_console_always_printed(self, desktop):
        lines = desktop.dependency_lines({})
        assert lines[0] == '依赖自检（不影响启动，只说明哪类节点可用）：'
        assert [line.split(':')[0].strip() for line in lines[1:]] == ['Chrome', 'chromedriver', 'Ollama', 'xelatex']
        assert '未找到（采集节点需要安装 Chrome）' in lines[1]
        assert 'Selenium 自动下载匹配版本' in lines[2]
        assert '可改用 OpenRouter' in lines[3]
        assert '只影响 PDF / 论文成稿' in lines[4]

    def test_a_machine_that_has_everything_names_every_path(self, desktop):
        report = {
            'chrome': 'C:/chrome.exe',
            'driver': 'C:/chromedriver.exe',
            'xelatex': 'D:/xelatex.exe',
            'ollama': True,
        }
        text = '\n'.join(desktop.dependency_lines(report))
        assert 'Chrome: 已找到' in text, 'Chrome is answered as a fact, not as a path'
        for value in ('C:/chromedriver.exe', 'D:/xelatex.exe', '运行中'):
            assert value in text

    def test_a_probe_that_raises_is_reported_and_never_propagates(self, desktop, monkeypatch, capsys):
        """The absence of the four lines must not look like a quiet pass."""

        def _boom(_path):
            raise OSError('disk went away')

        monkeypatch.setattr(desktop, 'dependency_report', _boom)
        desktop._print_dependencies(Path('.'))  # must not raise: it runs unwatched on a daemon thread
        printed = capsys.readouterr().out
        assert '依赖自检未能完成' in printed
        assert 'disk went away' in printed

    def test_the_block_is_one_write_so_nothing_splits_it(self, desktop, monkeypatch):
        writes = []

        class _Console:
            def write(self, text):
                writes.append(text)

            def flush(self):
                pass

        monkeypatch.setattr(
            desktop, 'dependency_report', lambda _path: {'chrome': 'c', 'driver': 'd', 'ollama': True, 'xelatex': 'x'}
        )
        monkeypatch.setattr(sys, 'stdout', _Console())
        desktop._print_dependencies(Path('.'))
        # ``print`` adds the line ending as its own write; what must not split is the text.
        blocks = [text for text in writes if text.strip()]
        assert len(blocks) == 1, f'the report ships in {len(blocks)} text writes; Flask can split them apart'
        assert blocks[0].count('\n') == 4


class TestThePrunerOnlyCutsWhatIsProvablyDead:
    """Each of these removals cites the loader that never reads the file (see prune_dist.py).

    The snownlp pair is the one worth pinning: ``*.marshal`` and ``*.marshal.3`` differ by a
    three-character suffix, and deleting the wrong one makes ``import snownlp`` raise at run
    time — in the packaged app, where snownlp is also the sanctioned sentiment fallback.
    """

    def test_the_python2_marshal_and_the_training_corpora_go_the_models_stay(self, prune_module, tmp_path):
        internal = tmp_path / '_internal'
        gone, kept = [], []
        for relative, keep in (
            ('snownlp/seg/seg.marshal', False),
            ('snownlp/seg/seg.marshal.3', True),
            ('snownlp/seg/data.txt', False),
            ('snownlp/tag/tag.marshal', False),
            ('snownlp/tag/tag.marshal.3', True),
            ('snownlp/tag/199801.txt', False),
            ('snownlp/sentiment/sentiment.marshal', False),
            ('snownlp/sentiment/sentiment.marshal.3', True),
            ('snownlp/sentiment/neg.txt', False),
            ('snownlp/sentiment/pos.txt', False),
            ('jieba/dict.txt', True),
            ('jieba/lac_small/model_baseline', False),
        ):
            target = internal / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'x' * 2048)
            (gone if not keep else kept).append(target)
        assert 'jieba/lac_small' in prune_module.DEAD_DIRS

        removed = prune_module.prune(tmp_path)
        for target in gone:
            assert not target.exists(), f'{target} is read by nothing and still shipped'
        for target in kept:
            assert target.is_file(), f'{target} is the file the loader actually opens'
        assert len(removed) >= len(gone), f'expected one entry per deletion, got {removed}'

    def test_a_font_cache_folder_is_cleared_only_when_it_is_one(self, prune_module, tmp_path):
        (tmp_path / '_internal').mkdir(parents=True)
        cache = tmp_path / 'tmp5ttn736f'
        cache.mkdir()
        (cache / 'fontlist-v3.11.0.json').write_text('{}', encoding='utf-8')
        other = tmp_path / 'tmpmy_own_folder'
        other.mkdir()
        (other / 'keep.txt').write_text('mine', encoding='utf-8')
        litter = tmp_path / 'tmpeegn58pz'  # measured: one of these per launch, left empty by tempfile
        litter.mkdir()

        prune_module.prune(tmp_path)
        assert not cache.exists(), 'matplotlib cache would ship in the zip and the installer'
        assert not litter.exists(), 'an empty launch litter must not ship either'
        assert (other / 'keep.txt').is_file(), 'a folder that merely starts with tmp is not ours to delete'

    def test_the_launcher_gives_the_frozen_child_a_scratch_dir_it_can_write(self):
        """``tempfile`` falls back to the **current directory**, and the launcher's cwd is the install
        folder — so a denied ``%TEMP%`` littered empty ``tmp…`` dirs beside the exe (measured, one per
        launch). Scratch belongs in the data root, which the pruner strips from the deliverable."""
        source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
        assert "('TMP', 'TEMP', 'TMPDIR')" in source, 'the scratch redirect is gone'
        assert source.index("'TMP', 'TEMP', 'TMPDIR'") < source.index('os.chdir(base)'), (
            'TMP has to be set before the process starts creating files in its cwd'
        )
        # Assigning the variables is not enough: `tempfile` caches the directory it resolved, and with
        # a denied %TEMP% that cached answer is the current directory (= the install folder).
        assert 'tempfile.tempdir = None' in source, 'the cached tempdir is not cleared, so the fix is cosmetic'
        assert 'os.environ[_name] =' in source, 'a setdefault leaves an inherited-but-unwritable %TEMP% in charge'
        assert "root / 'tmp'" in source, 'scratch must live inside the data root, not the install folder'
        prune = (PACKAGING / 'prune_dist.py').read_text(encoding='utf-8')
        assert "'tmp'" in prune.split('USER_STATE_DIRS')[1].split(')')[0], '<data root>/tmp would ship to users'

    def test_the_launcher_sweeps_the_litter_a_library_leaves_behind(self, desktop, tmp_path):
        """Two empty ``tmp…`` dirs per launch appeared beside the exe even with TMP redirected, and
        they are not our own calls (ours all pass a ``cixi-`` prefix) — so the launcher cleans the
        install folder instead of guessing which dependency resolves scratch to the cwd."""
        litter = tmp_path / 'tmpeegn58pz'
        litter.mkdir()
        ours = tmp_path / 'cixi-pdf-something'
        ours.mkdir()
        kept = tmp_path / 'tmpnotempty'
        kept.mkdir()
        (kept / 'file.txt').write_text('mine', encoding='utf-8')
        (tmp_path / 'tmpafile.txt').write_text('not a directory', encoding='utf-8')

        assert desktop.sweep_startup_litter(tmp_path) == 1
        assert not litter.exists(), 'the empty launch litter must go'
        assert ours.is_dir() and (kept / 'file.txt').is_file() and (tmp_path / 'tmpafile.txt').is_file(), (
            'anything with contents, a different name shape, or not a directory is untouched'
        )

    def test_the_sweep_runs_at_both_ends_of_a_launch(self):
        """At start for the litter a killed process never cleaned, at exit for this launch's own."""
        source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
        assert source.count('sweep_startup_litter(') >= 3, 'one of the two sweeps was dropped'
        assert source.index('sweep_startup_litter(base)') < source.index('from app import app')
        assert source.rindex('sweep_startup_litter(base)') > source.index('clear_instance(root, port)')


class TestTheUpxPassReportsWhatItActuallyDid:
    """PyInstaller's own ``upx=True`` skips every file when it cannot find the tool. That is how a
    deliverable ends up labelled "compressed" while carrying uncompressed bytes, so the pass lives
    here with a named failure, a per-file verification and a byte ledger.

    The binary tool itself is not needed for these: ``_run`` is the seam, and the one thing worth
    pinning about the real tool is the flag list (measured on UPX 5.0.2: ``--no-version-info`` is
    rejected outright, which would have made every single file a silent no-op).
    """

    @pytest.fixture(scope='module')
    def compressor(self):
        return _load('compress_dist', PACKAGING / 'compress_dist.py')

    def test_the_flags_are_the_ones_the_installed_upx_accepts(self, compressor):
        assert compressor.UPX_ARGS == ['--best', '--force']
        assert '--no-version-info' not in compressor.UPX_ARGS, 'UPX 5.0.2 rejects it and exits 1'

    def test_the_runtime_that_boots_the_app_is_never_packed(self, compressor, tmp_path):
        for name in (
            'python311.dll',
            'vcruntime140.dll',
            'msvcp140.dll',
            'ucrtbase.dll',
            'api-ms-win-core-xxxxx-l1-1-0.dll',
        ):
            assert compressor.is_unchanged(tmp_path / name), f'{name} would be packed'
        assert not compressor.is_unchanged(tmp_path / 'numpy.cp311-win_amd64.pyd')

    def test_targets_are_the_executables_of_this_build_only(self, compressor, tmp_path):
        internal = tmp_path / '_internal'
        (tmp_path / 'CaiXiHui.exe').write_bytes(b'MZ')
        (internal / 'numpy').mkdir(parents=True)
        (internal / 'numpy' / 'core.pyd').write_bytes(b'MZ')
        (internal / 'python311.dll').write_bytes(b'MZ')
        (internal / 'numpy' / 'multiarray.pyd.upxbackup').write_bytes(b'MZ')
        (internal / 'numpy' / 'dict.txt').write_text('data', encoding='utf-8')
        found = {path.name for path in compressor.pe_targets(tmp_path)}
        assert found == {'CaiXiHui.exe', 'core.pyd'}, found

    def test_a_file_upx_declines_is_reported_and_is_not_a_failed_build(self, compressor, tmp_path, monkeypatch):
        """Measured on the real build: ``python3.dll: NotCompressibleException`` every time.

        UPX refusing a 100 KB forwarder DLL is neither a defect nor a risk — the original file stays
        and loads — so it is recorded as a skip. Calling that a failure paints the gate red on every
        run, and a gate that is always red is a gate nobody reads. ``python3.dll`` is also excluded
        outright now, because the loader pairs it with ``python311.dll``.
        """

        def refuse(_upx, args):
            if '--best' in args:
                # UPX writes to the same path, so a refusal can leave a truncated file: simulate that.
                Path(forwarder).write_bytes(b'MZ\x00\x00')
                return types.SimpleNamespace(returncode=1, stdout='', stderr='upx: x: NotCompressibleException')
            return types.SimpleNamespace(returncode=0, stdout='', stderr='')

        assert compressor.is_unchanged(tmp_path / 'python3.dll'), 'the stable-ABI loader is not ours to pack'
        internal = tmp_path / '_internal'
        internal.mkdir(parents=True)
        forwarder = internal / 'some_forwarder.dll'
        forwarder.write_bytes(b'MZ' + b'x' * 500)
        monkeypatch.setattr(compressor, '_run', refuse)
        ledger = compressor.compress(tmp_path, upx_path='upx')
        assert ledger['failed'] == []
        assert 'NotCompressibleException' in ledger['skipped'][0][2]
        assert forwarder.stat().st_size == 502, 'the original must stay'
        assert not list(internal.rglob('*.upxbackup'))
        assert compressor.main(['compress_dist.py', str(tmp_path)]) == 0, 'a declined file is not a red build'

    def test_a_missing_upx_is_a_named_failure_not_a_quiet_pass(self, compressor, tmp_path, monkeypatch):
        monkeypatch.setattr(compressor.shutil, 'which', lambda _name: None)
        (tmp_path / '_internal').mkdir(parents=True)
        ledger = compressor.compress(tmp_path)
        assert ledger['compressed'] == [] and ledger['failed']
        assert 'not on PATH' in ledger['failed'][0][2]
        assert compressor.main(['compress_dist.py', str(tmp_path)]) == 1, 'the build must not call this a pass'

    def test_the_ledger_counts_only_verified_packed_bytes(self, compressor, tmp_path, monkeypatch):
        internal = tmp_path / '_internal'
        (internal / 'numpy').mkdir(parents=True)
        good = internal / 'numpy' / 'good.pyd'
        bad = internal / 'numpy' / 'bad.pyd'
        for target in (good, bad):
            target.write_bytes(b'MZ' + b'x' * 4000)

        def fake_run(_upx, args):
            """Shrink the first file; the second packs larger, which is a failure to restore."""
            outcome = types.SimpleNamespace(returncode=0, stdout='', stderr='')
            if args[-1] == str(bad):
                if '--best' in args:
                    Path(bad).write_bytes(b'MZ' + b'y' * 5000)
                return outcome
            if '--best' in args:
                Path(good).write_bytes(b'MZ' + b'z' * 40)
            return outcome

        monkeypatch.setattr(compressor, '_run', fake_run)
        ledger = compressor.compress(tmp_path, upx_path='upx')
        assert len(ledger['compressed']) == 1 and ledger['compressed'][0][0].endswith('good.pyd')
        assert ledger['failed'] and ledger['failed'][0][0].endswith('bad.pyd')
        assert good.stat().st_size == 42, 'the packed bytes should remain'
        assert bad.stat().st_size == 4002, f'a rejected file must be restored, got {bad.stat().st_size}'
        assert not list(internal.rglob('*.upxbackup')), 'a backup must not ship in the zip'
        assert ledger['before'] > ledger['after']

    def test_a_file_upx_already_packed_is_skipped_not_double_packed(self, compressor, tmp_path, monkeypatch):
        internal = tmp_path / '_internal'
        (internal / 'numpy').mkdir(parents=True)
        packed = internal / 'numpy' / 'packed.pyd'
        packed.write_bytes(b'MZ' + b'UPX!' + b'z' * 200)
        monkeypatch.setattr(compressor, '_run', lambda *_a: pytest.fail('upx ran over an already-packed file'))
        ledger = compressor.compress(tmp_path, upx_path='upx')
        assert ledger['compressed'] == []
        assert ledger['skipped'][0][2] == 'already packed'

    def test_the_build_script_runs_the_pass_and_the_spec_does_not(self):
        """Two packers on the same file is a corruption risk, and PyInstaller's is the silent one."""
        script = (PACKAGING / 'build_windows.ps1').read_text(encoding='utf-8')
        spec = (PACKAGING / 'caixihui.spec').read_text(encoding='utf-8')
        assert 'upx=False' in spec and 'USE_UPX' not in spec, 'PyInstaller would pack in the dark again'
        assert 'CAIXIHUI_UPX' not in spec and 'CAIXIHUI_UPX' not in script, 'the dead opt-in is back'
        assert script.index('prune_dist.py') < script.index('compress_dist.py'), 'pack before pruning wastes the pass'
        assert '[switch]$NoUpx' in script, 'the escape hatch for a machine without upx disappeared'
        # The comment at the top of the script is the reason every native call goes through
        # Invoke-Exe; ISCC was the one holdout that could hang a build.
        assert '& $iscc' not in script, 'the direct call can block forever on a non-interactive host'
        assert 'Invoke-Exe $iscc' in script

    def test_the_contradictory_flag_pair_is_refused_before_the_venv_is_deleted(self):
        """Measured: `-Clean -SkipInstall` wiped the build env and then skipped refilling it, so the
        run died at `No module named PyInstaller` minutes later, pointing at nothing useful."""
        script = (PACKAGING / 'build_windows.ps1').read_text(encoding='utf-8')
        guard = 'if ($Clean -and $SkipInstall)'
        assert guard in script, 'the contradictory pair is back'
        assert script.index(guard) < script.index('Remove-Item -LiteralPath $Venv -Recurse'), (
            'the guard has to run before -Clean destroys the environment it is warning about'
        )

    def test_the_files_other_tools_parse_are_pure_ascii(self):
        """Two tools outside our control decode these files by the machine's locale, not as UTF-8.

        Measured twice in one session. Windows PowerShell 5.1 reads a ``.ps1`` **without a BOM** in the
        ANSI codepage, so a ``Write-Host '中文…'`` literal arrives as GBK bytes, one of which looks like a
        quote terminator — ``字符串缺少终止符`` reported hundreds of characters away from the real line, and
        the build never started. pip's ``auto_decode`` does the same for a requirements file
        (``locale.getpreferredencoding()``, UTF-8 only with a BOM): a Chinese comment there is a
        ``UnicodeDecodeError: 'gbk' codec can't decode byte 0x94`` inside the very first install step.
        ASCII-only cannot be mis-decoded; user-facing Chinese lives in ``backend/i18n.py`` and the
        console lines the launcher prints from Python, which does default to UTF-8.

        The same applies to the two requirement files a user installs from on Windows, so they are
        checked here too: an em dash in ``requirements.txt`` is the same ``UnicodeDecodeError`` one
        keystroke away from the README's install command.
        """
        targets = [
            PACKAGING / name for name in ('build_windows.ps1', 'requirements-runtime.txt', 'requirements-build.txt')
        ]
        targets += [REPO / name for name in ('requirements.txt', 'requirements-optional.txt')]
        for path in targets:
            raw = path.read_bytes()
            non_ascii = sorted({byte for byte in raw if byte > 127})
            assert not non_ascii, (
                f'{path.name} holds non-ASCII bytes {non_ascii}; the tool reading it decodes by locale'
            )
            assert not raw.startswith(b'\xef\xbb\xbf'), (
                f'{path.name} carries a BOM, which hides the problem from other readers'
            )
        # The installer script legitimately carries Chinese, so it has to declare it: Inno Setup reads a
        # .iss without a BOM in the ANSI codepage, which is mojibake in the wizard the user sees.
        iss = (PACKAGING / 'installer.iss').read_bytes()
        assert iss.startswith(b'\xef\xbb\xbf'), 'installer.iss has Chinese but no UTF-8 BOM; ISCC would misread it'
        assert iss.decode('utf-8-sig')


class TestTheModelPackBecomesARegistryEntry:
    """A pack sitting on disk is invisible until it is in ``data/model_registry.json`` — and the
    seeder must not rewrite anything the user owns (the three rules in ``bert_pack.py``)."""

    @pytest.fixture(scope='module')
    def pack_module(self):
        return _load('bert_pack', PACKAGING / 'bert_pack.py')

    def _folder(self, root: Path, name: str, *, complete=True, sidecar=None):
        folder = root / name
        folder.mkdir(parents=True)
        if not complete:
            (folder / 'cixi_bert.json').write_text('{}', encoding='utf-8')
            return folder
        holder = {
            'name': f'{name}（int8 ONNX）',
            'operation': 'sentiment',
            'desc': 'd',
            'precision': 'int8',
        } | (sidecar or {})
        (folder / 'model.onnx').write_bytes(b'graph')
        (folder / 'tokenizer.json').write_text('{}', encoding='utf-8')
        (folder / 'cixi_bert.json').write_text(json.dumps(holder, ensure_ascii=False), encoding='utf-8')
        return folder

    def test_only_a_complete_folder_is_offered(self, pack_module, tmp_path):
        models = tmp_path / 'bert_models'
        self._folder(models, 'good')
        self._folder(models, 'half', complete=False)
        (models / 'empty').mkdir()
        entries = pack_module.discover_packs(models)
        assert [item['name'] for item in entries] == ['good（int8 ONNX）']
        assert entries[0]['path'] == 'bert_models/good', 'an absolute build path would be dead on the next machine'

    def test_a_sidecar_without_an_operation_is_not_a_model_of_anything(self, pack_module, tmp_path):
        models = tmp_path / 'bert_models'
        self._folder(models, 'odd', sidecar={'operation': ''})
        assert pack_module.discover_packs(models) == []

    def test_the_user_s_entry_wins_and_its_extra_keys_survive(self, pack_module):
        existing = [{'name': 'sentiment（int8 ONNX）', 'path': 'D:/mine', 'operation': 'sentiment', 'note': 'keep me'}]
        packs = [{'name': 'sentiment（int8 ONNX）', 'path': 'bert_models/x', 'operation': 'sentiment', 'desc': ''}]
        merged, added, skipped = pack_module.merge_registry(existing, packs)
        assert added == [] and skipped == ['sentiment（int8 ONNX）']
        assert merged == existing, 'the registry is the user file; a clash must not rewrite it'

    def test_seeding_writes_once_and_leaves_the_file_alone_after_that(self, pack_module, tmp_path):
        data, models = tmp_path / 'data', tmp_path / 'bert_models'
        self._folder(models, 'emotion_ewect_six_onnx_int8')
        first = pack_module.seed_registry(data, models)
        assert first['added'] == ['emotion_ewect_six_onnx_int8（int8 ONNX）']
        holder = data / 'model_registry.json'
        written = holder.read_text(encoding='utf-8')
        second = pack_module.seed_registry(data, models)
        assert second['added'] == [] and second['untouched'] == '模型包已全部登记过'
        assert holder.read_text(encoding='utf-8') == written, 'a start with no change must not rewrite the file'

    def test_a_registry_that_cannot_be_read_is_not_replaced(self, pack_module, tmp_path):
        data, models = tmp_path / 'data', tmp_path / 'bert_models'
        self._folder(models, 'pack')
        holder = data / 'model_registry.json'
        for content in ('not json at all', '{"a": 1}'):
            holder.parent.mkdir(parents=True, exist_ok=True)
            holder.write_text(content, encoding='utf-8')
            ledger = pack_module.seed_registry(data, models)
            assert ledger['added'] == [] and 'model_registry.json' in ledger['untouched']
            assert holder.read_text(encoding='utf-8') == content, 'a file we cannot parse is still the user data'

    def test_no_pack_means_no_file_and_no_claim(self, pack_module, tmp_path):
        ledger = pack_module.seed_registry(tmp_path / 'data', tmp_path / 'bert_models')
        assert ledger == {'packs': 0, 'added': [], 'skipped': [], 'untouched': '没有可登记的模型包目录'}
        assert not (tmp_path / 'data' / 'model_registry.json').exists()

    def test_the_launcher_registers_the_pack_before_the_app_starts(self):
        """Order matters: ``/api/models`` reads the registry through Config, so a late registration
        would show an empty model list on the first start after unpacking a pack."""
        source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
        assert source.index('seed_registry(root /') < source.index('from app import app')


class TestTheModelPackArchive:
    """The archive's layout is the contract the launcher reads, so it is asserted — not eyeballed."""

    @pytest.fixture(scope='module')
    def packer(self):
        return _load('build_model_pack', PACKAGING / 'build_model_pack.py')

    def _source(self, root: Path, name: str, precision: str) -> Path:
        folder = root / f'{name}_onnx_{precision}'
        folder.mkdir(parents=True)
        (folder / 'model.onnx').write_bytes(b'graph')
        (folder / 'tokenizer.json').write_text('{}', encoding='utf-8')
        (folder / 'cixi_bert.json').write_text('{"name": "n", "operation": "sentiment"}', encoding='utf-8')
        return folder

    def test_the_archive_unpacks_to_the_directory_the_launcher_scans(self, packer, tmp_path):
        import zipfile

        source = tmp_path / 'onnx'
        self._source(source, 'sentiment_weibosenti_bin', 'fp16')
        self._source(source, 'emotion_ewect_six', 'fp16')
        archive = tmp_path / 'dist' / 'CaiXiHui-bert-models-win64.zip'
        code = packer.main(
            [
                'build_model_pack.py',
                'fp16',
                str(archive),
                str(source),
                'sentiment_weibosenti_bin',
                'emotion_ewect_six',
            ]
        )
        assert code == 0
        with zipfile.ZipFile(archive) as holder:
            names = holder.namelist()
            assert names.count('bert_models/sentiment_weibosenti_bin_onnx_fp16/model.onnx') == 1
            assert all(item.startswith('bert_models/') for item in names), names
            assert zipfile.ZipFile(archive).testzip() is None, 'a corrupt entry would surface as a missing model'
        assert not (tmp_path / 'dist' / 'CaiXiHui-bert-models-win64.staging').exists(), 'staging must not linger'

    def test_a_model_without_that_precision_refuses_and_writes_no_archive(self, packer, tmp_path):
        source = tmp_path / 'onnx'
        self._source(source, 'sentiment_weibosenti_bin', 'fp16')
        archive = tmp_path / 'dist' / 'pack.zip'
        code = packer.main(['build_model_pack.py', 'int8', str(archive), str(source), 'sentiment_weibosenti_bin'])
        assert code == 2, 'a half pack shipped is a model the user cannot select'
        assert not archive.exists()


class TestTheIconIsWhatItsNameSays:
    """``backend/static/icon.ico`` has to be an icon, because two tools read it and one checks.

    It used to be the app's PNG wearing an ``.ico`` name. A browser content-sniffs that and draws the
    favicon, so the defect hid in plain sight for as long as the file existed; PyInstaller copied the
    invalid bytes into ``CaiXiHui.exe`` and printed ``Copying icon to EXE`` as if it worked; Inno
    Setup refused to compile the installer at all — ``Resource update error: Icon file is invalid`` —
    and it said so only after the folder build and the zip had already taken their ten minutes.
    """

    ICON = REPO / 'backend' / 'static' / 'icon.ico'
    ART = REPO / 'backend' / 'static' / 'icon.png'
    GENERATOR = REPO / 'tools' / 'build_icon.py'

    @staticmethod
    def _frames(raw: bytes) -> list[dict[str, int]]:
        """Parse the ICO header and its directory; a PNG wearing the name fails here."""
        reserved, kind, count = struct.unpack_from('<HHH', raw, 0)
        assert (reserved, kind) == (0, 1), (
            f'not an ICO directory (reserved={reserved}, type={kind}): '
            'a PNG renamed to .ico gets this far and Inno Setup rejects it'
        )
        frames = []
        for index in range(count):
            width, height, _colors, _reserved, planes, depth, size, offset = struct.unpack_from(
                '<BBBBHHII', raw, 6 + 16 * index
            )
            frames.append(
                {
                    'width': width or 256,
                    'height': height or 256,
                    'planes': planes,
                    'depth': depth,
                    'size': size,
                    'offset': offset,
                }
            )
        return frames

    def test_the_committed_file_is_an_icon_and_every_frame_is_inside_it(self):
        raw = self.ICON.read_bytes()
        frames = self._frames(raw)
        assert frames, 'an icon with no frames is a header'
        for frame in frames:
            assert frame['offset'] + frame['size'] <= len(raw), 'the directory promises bytes the file does not have'
            assert frame['planes'] in (0, 1), 'the format carries one colour plane (0 is what writers emit)'
            assert frame['depth'] in (1, 4, 8, 24, 32), frame['depth']
            payload = raw[frame['offset'] : frame['offset'] + 4]
            if payload == b'\x89PNG':
                continue
            assert struct.unpack_from('<I', raw, frame['offset'])[0] in (40, 52, 56, 64, 108, 124), (
                f'frame {frame["width"]} is neither a PNG nor a DIB header'
            )

    def test_the_sizes_windows_picks_are_all_present(self):
        frames = self._frames(self.ICON.read_bytes())
        sizes = {frame['width'] for frame in frames}
        assert sizes == {frame['height'] for frame in frames}, 'a non-square icon is stretched by the shell'
        assert {16, 24, 32, 48, 256} <= sizes, f'missing shell sizes: {sorted(sizes)}'

    def test_both_packagers_read_the_file_these_tests_checked(self):
        spec = (PACKAGING / 'caixihui.spec').read_text(encoding='utf-8')
        assert "icon=str(BACKEND / 'static' / 'icon.ico')" in spec
        iss = (PACKAGING / 'installer.iss').read_text(encoding='utf-8-sig')
        assert 'SetupIconFile=..\\backend\\static\\icon.ico' in iss

    def test_the_build_checks_the_header_before_it_spends_its_time(self):
        script = (PACKAGING / 'build_windows.ps1').read_text(encoding='utf-8')
        assert 'backend\\static\\icon.ico' in script
        assert 'is not an ICO' in script
        assert script.index('is not an ICO') < script.index('Write-Step "Build environment"'), (
            'the check that costs nothing has to run before the steps that cost ten minutes'
        )

    def test_the_generator_rebuilds_the_same_frames_from_the_source_art(self, tmp_path):
        builder = _load('build_icon', self.GENERATOR)
        assert self.ART.is_file(), 'the art the icon is generated from belongs next to it'
        assert self.ART.read_bytes()[:4] == b'\x89PNG', 'the source is the PNG; the .ico is its output'
        rebuilt = tmp_path / 'icon.ico'
        info = builder.build(self.ART, rebuilt)
        assert info['target'] == rebuilt
        assert {frame['width'] for frame in self._frames(rebuilt.read_bytes())} == {
            frame['width'] for frame in self._frames(self.ICON.read_bytes())
        }, 'the committed icon is not what the tool produces'

    def test_a_missing_source_refuses_rather_than_writing_a_stub(self, tmp_path):
        builder = _load('build_icon', self.GENERATOR)
        with pytest.raises(SystemExit):
            builder.build(tmp_path / 'no-such-art.png', tmp_path / 'icon.ico')


def test_the_launcher_starts_the_clock_the_serving_process_needs():
    """``python app.py`` starts the scheduler inside its ``__main__``; the frozen entry imports the
    module and runs Flask itself, so ``__main__`` never ran there.

    Measured on the built exe: the 定时任务 panel said 「调度线程没有运行——任务已保存，但到点不会
    执行」 because no tick thread existed. The launcher must therefore call the same shared starter,
    once, before it starts serving.
    """
    source = (PACKAGING / 'desktop_entry.py').read_text(encoding='utf-8')
    assert 'from app import start_background_services' in source
    assert source.count('start_background_services()') == 1
    assert source.index('start_background_services()') < source.index('flask_app.run(')


@contextlib.contextmanager
def _served():
    """A throwaway local server that answers 200 on ``/api/config``, as a context manager.

    The launcher's open path needs a probe that succeeds — not our app, just an address that says
    "here I am" once, so what is under test is what happens AFTER the server is confirmed reachable.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        # No ``log_message`` override: the access line goes to stderr, and the assertions below read
        # stdout only — shadowing the base method's parameters is how this fixture once earned a
        # pylint W0221.

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestTheAddressSurvivesWhenNoBrowserExists:
    """``webbrowser.open`` answers ``False`` when nothing is registered — it never raises.

    A console that goes quiet right after the startup line is the failure this project has been asked
    to remove twice, and both entries have the same hole: the launcher and ``app._open_browser``.
    """

    @pytest.mark.enable_socket
    def test_the_launcher_prints_the_address_instead_of_going_quiet(self, desktop, capsys):
        with _served() as url:
            desktop._wait_and_open(url, open_url=lambda _target: False)
            out = capsys.readouterr().out
        assert '请手动打开' in out, out
        assert url in out, 'the printed line has to carry the address it could not hand over'

    @pytest.mark.enable_socket
    def test_a_successful_open_adds_no_line_of_its_own(self, desktop, capsys):
        opened = []
        with _served() as url:
            desktop._wait_and_open(url, open_url=lambda target: opened.append(target) or True)
        assert opened == [url]
        assert capsys.readouterr().out == ''

    def test_the_source_startup_logs_the_same_fact(self, caplog, monkeypatch):
        import webbrowser

        import app as app_module

        import i18n

        monkeypatch.setattr(webbrowser, 'open', lambda _url: False)
        with caplog.at_level('WARNING', logger='app'):
            app_module._open_browser('http://127.0.0.1:5000')
        said = [record.message for record in caplog.records if record.levelname == 'WARNING']
        assert i18n.t('misc.browserNotFound', url='http://127.0.0.1:5000') in said, said
