"""The packaged Windows build's own contract, testable without PyInstaller.

The build is a folder, not a one-file exe, and size is a feature: these tests pin the
launcher's writable-data choices, its first-run seeding (never overwrite), its driver
fallback, and the spec's exclusion list so a later dependency cannot silently pull a
multi-gigabyte stack back into ``dist/``.

Nothing here starts the server or needs a frozen exe; ``main()`` is not called.
"""

import importlib.util
import socket
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
