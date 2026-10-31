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


class TestEveryAccountIsArchived:
    """A multi-account install keeps its runtime state in ``data/users/<user_id>/``.

    Enumerating only ``data/``'s top level — what this tool did before the accounts landed —
    archived the machine's settings and NOT one run, dataset, saved canvas or cookie jar, and then
    printed a file count that read like a successful backup of the work it exists to protect.
    """

    def _account(self, data_root, user_id='u_alice00000'):
        account = data_root / 'users' / user_id
        (account / 'workflows').mkdir(parents=True)
        (account / 'workflows' / 'mine.json').write_text('{}', encoding='utf-8')
        (account / 'runs.db').write_bytes(b'SQLite format 3\0')
        (account / 'cookies').mkdir()
        (account / 'cookies' / 'zhihu@work.json').write_text('[]', encoding='utf-8')
        # Still browser scratch and re-creatable output, exactly as at the system level.
        (account / 'chrome_profile' / 'zhihu').mkdir(parents=True)
        (account / 'chrome_profile' / 'zhihu' / 'Cookies').write_bytes(b'secret')
        (account / 'exports').mkdir()
        (account / 'exports' / 'chart.png').write_bytes(b'png')
        return account

    def test_an_accounts_stores_and_work_are_in_the_backup(self, tmp_path, data_root):
        self._account(data_root)
        members = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root)}
        assert {'users/u_alice00000/workflows/mine.json', 'users/u_alice00000/runs.db'} <= members

    def test_an_accounts_cookies_are_opt_in_like_everyones(self, tmp_path, data_root):
        self._account(data_root)
        quiet = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root)}
        assert not any('users/u_alice00000/cookies' in name for name in quiet)
        asked = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root, with_cookies=True)}
        assert 'users/u_alice00000/cookies/zhihu@work.json' in asked

    def test_an_accounts_profile_and_exports_never_ride_along(self, tmp_path, data_root):
        self._account(data_root)
        members = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root, with_cookies=True)}
        assert not any('chrome_profile' in name or '/exports/' in name for name in members), members

    def test_a_trashed_account_tree_is_left_alone(self, tmp_path, data_root):
        """``users/.trash/`` is a tree an operator already decided to set aside. Archiving it into
        every future restore point would grow the backup with deleted data and re-restore it."""
        trashed = data_root / 'users' / '.trash' / 'u_gone-20260101'
        trashed.mkdir(parents=True)
        (trashed / 'runs.db').write_bytes(b'SQLite format 3\0')
        members = {path.relative_to(data_root).as_posix() for path in backup.select_data(data_root)}
        assert not any('.trash' in name for name in members), members

    def test_committed_rows_survive_the_archive(self, tmp_path, data_root):
        """Copying ``x.db`` alone is not copying the database.

        In WAL mode a committed transaction can still be living in ``x.db-wal``, and the selector
        called those side files scratch: the restore came back missing the newest rows — the account
        created minutes ago, the table the last node just published."""
        import sqlite3

        account = data_root / 'users' / 'u_live0000000'
        account.mkdir(parents=True)
        database = account / 'runs.db'
        writer = sqlite3.connect(str(database))
        try:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE t (x INTEGER)')
            writer.execute('INSERT INTO t VALUES (41)')
            writer.commit()

            manifest = backup.create_backup(tmp_path / 'out', data_root=data_root, bundle=False)
            unpacked = tmp_path / 'unpacked'
            with zipfile.ZipFile(Path(manifest['path']) / 'data.zip') as archive:
                assert 'data/users/u_live0000000/runs.db' in archive.namelist(), archive.namelist()
                archive.extractall(unpacked)
            writer.close()

            reader = sqlite3.connect(str(unpacked / 'data' / 'users' / 'u_live0000000' / 'runs.db'))
            try:
                assert [row[0] for row in reader.execute('SELECT x FROM t')] == [41]
            finally:
                reader.close()
        finally:
            writer.close()


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
