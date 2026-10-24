"""The packaged Windows build's own contract, testable without PyInstaller.

The build is a folder, not a one-file exe, and size is a feature: these tests pin the
launcher's writable-data choices, its first-run seeding (never overwrite), its driver
fallback, and the spec's exclusion list so a later dependency cannot silently pull a
multi-gigabyte stack back into ``dist/``.

Nothing here starts the server or needs a frozen exe; ``main()`` is not called.
"""

import importlib.util
import socket
import tempfile
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
PACKAGING = REPO / 'packaging'


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
