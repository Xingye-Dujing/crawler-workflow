"""The backup tool: what a restore point includes, and what it refuses to include by default.

The rule under test is the operator's, not the tool's convenience: live cookie jars are account
credentials in plain JSON, so they are opt-in, and a bundle that git could not write must leave no
file behind that a later restore would trust.
"""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location('backup_tool', REPO / 'tools' / 'backup.py')
backup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(backup)


@pytest.fixture
def data_root(tmp_path):
    root = tmp_path / 'data'
    (root / 'workflows').mkdir(parents=True)
    (root / 'workflows' / 'a.json').write_text('{}', encoding='utf-8')
    (root / 'reusable_nodes').mkdir()
    (root / 'reusable_nodes' / 't.json').write_text('{}', encoding='utf-8')
    (root / 'cookies').mkdir()
    (root / 'cookies' / 'zhihu@work.json').write_text('[]', encoding='utf-8')
    (root / 'runs.db').write_bytes(b'SQLite format 3\0')
    (root / 'settings.json').write_text('{}', encoding='utf-8')
    (root / 'model_registry.json').write_text('[]', encoding='utf-8')
    # Scratch that must never ride along: a browser profile and an export directory.
    (root / 'chrome_profile' / 'zhihu').mkdir(parents=True)
    (root / 'chrome_profile' / 'zhihu' / 'Cookies').write_bytes(b'secret')
    (root / 'exports').mkdir()
    (root / 'exports' / 'out.csv').write_text('x', encoding='utf-8')
    return root


class TestWhatIsIncluded:
    def test_work_products_and_stores_are_included(self, data_root):
        members = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root)}
        assert {'workflows/a.json', 'reusable_nodes/t.json', 'runs.db', 'settings.json'} <= members

    def test_cookies_are_excluded_by_default(self, data_root):
        members = backup.select_data(data_root)
        assert not any('cookies' in path.parts for path in members)

    def test_cookies_join_only_when_asked(self, data_root):
        members = backup.select_data(data_root, with_cookies=True)
        assert any(path.name == 'zhihu@work.json' for path in members)

    def test_browser_profiles_and_exports_never_ride_along(self, data_root):
        members = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root, True)}
        assert not any(name.startswith('chrome_profile/') or name.startswith('exports/') for name in members)


class TestCreateBackup:
    def test_the_manifest_and_archive_describe_the_same_set(self, tmp_path, data_root):
        manifest = backup.create_backup(tmp_path / 'backups', data_root=data_root, bundle=False)
        target = Path(manifest['path'])
        assert target.is_dir()
        assert json.loads((target / 'manifest.json').read_text(encoding='utf-8'))['members'] == manifest['members']
        with zipfile.ZipFile(target / 'data.zip') as archive:
            assert sorted(archive.namelist()) == sorted(manifest['members'])
            assert 'data/runs.db' in archive.namelist()
            assert not any('cookies' in name for name in archive.namelist())

    def test_a_failed_bundle_leaves_no_bundle_file(self, tmp_path, data_root):
        """A half-written bundle next to a manifest that claims one is the worst outcome: the file
        looks like a restore point and is not."""
        repo = tmp_path / 'repo'
        (repo / '.git').mkdir(parents=True)  # exists, but is not a repository git can read
        manifest = backup.create_backup(tmp_path / 'out', data_root=data_root, repo_root=repo)
        assert manifest['git']['bundle']['created'] is False
        assert manifest['git']['bundle']['error']
        assert not (Path(manifest['path']) / 'repo.bundle').exists()

    def test_an_empty_data_root_has_no_archive(self, tmp_path):
        empty = tmp_path / 'empty'
        empty.mkdir()
        manifest = backup.create_backup(tmp_path / 'out', data_root=empty, bundle=False)
        assert manifest['data_archive'] is None
        assert manifest['members'] == []

    def test_cookies_are_recorded_in_the_manifest_when_included(self, tmp_path, data_root):
        manifest = backup.create_backup(tmp_path / 'out', data_root=data_root, bundle=False, with_cookies=True)
        assert manifest['cookies_included'] is True
        assert any('cookies' in name for name in manifest['members'])
