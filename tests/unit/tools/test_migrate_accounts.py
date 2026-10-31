"""The legacy-tree migration: dry by default, verified before the original is set aside."""

import importlib.util
import sqlite3
import time
from pathlib import Path

import pytest

from services.accounts.security import hash_password
from services.accounts.store import AccountsStore

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location('migrate_accounts_tool', REPO / 'tools' / 'migrate_accounts.py')
migration = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(migration)


def _registry(data_root: Path, username: str = 'admin') -> str:
    store = AccountsStore(str(data_root / 'accounts.db'))
    user_id = 'u_0123456789ab'
    store.insert_user(
        user_id=user_id,
        username=username,
        password_hash=hash_password('correct horse battery'),
        role='admin',
        must_change_password=False,
        now=time.time(),
    )
    store.close()
    return user_id


def _legacy_tree(data_root: Path) -> None:
    data_root.mkdir(parents=True)
    conn = sqlite3.connect(str(data_root / 'runs.db'))
    conn.execute('CREATE TABLE runs (run_id TEXT PRIMARY KEY)')
    conn.execute("INSERT INTO runs VALUES ('r1')")
    conn.commit()
    conn.close()
    (data_root / 'workflows').mkdir()
    (data_root / 'workflows' / 'a.json').write_text('{}', encoding='utf-8')
    (data_root / 'cookies').mkdir()
    (data_root / 'cookies' / 'zhihu_cookies.json').write_text('[]', encoding='utf-8')
    # Machine-level state that must stay where it is.
    (data_root / 'settings.json').write_text('{}', encoding='utf-8')


def test_a_dry_run_touches_nothing(tmp_path):
    root = tmp_path / 'data'
    _legacy_tree(root)
    _registry(root)
    answer = migration.migrate(root, 'admin', apply=False)
    assert answer['applied'] is False
    assert {Path(src).name for src, _dst in answer['moves']} == {'runs.db', 'workflows', 'cookies'}
    assert (root / 'runs.db').is_file()
    assert not (root / 'users').exists()


def test_apply_copies_verifies_and_sets_the_original_aside(tmp_path):
    root = tmp_path / 'data'
    _legacy_tree(root)
    user_id = _registry(root)
    answer = migration.migrate(root, 'admin', apply=True)
    assert answer['applied'] is True
    target = root / 'users' / user_id
    assert (target / 'runs.db').is_file()
    assert (target / 'workflows' / 'a.json').is_file()
    assert (target / 'cookies' / 'zhihu_cookies.json').is_file()
    # The copy is a real database, not a byte-for-byte hope.
    conn = sqlite3.connect(str(target / 'runs.db'))
    try:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        conn.close()
    # Originals are gone from the root but preserved under .migrated-*.
    assert not (root / 'runs.db').exists()
    moved = Path(answer['moved_aside'])
    assert (moved / 'runs.db').is_file() and (moved / 'workflows' / 'a.json').is_file()
    # Machine-level files never move.
    assert (root / 'settings.json').is_file()
    assert (root / 'accounts.db').is_file()


def test_an_empty_directory_from_account_creation_is_not_occupied(tmp_path):
    """Creating the account makes empty workflows/cookies dirs; adoption must still work."""
    root = tmp_path / 'data'
    _legacy_tree(root)
    user_id = _registry(root)
    target = root / 'users' / user_id
    (target / 'workflows').mkdir(parents=True)
    (target / 'cookies').mkdir()
    answer = migration.migrate(root, 'admin', apply=True)
    assert answer['applied'] is True
    assert (target / 'workflows' / 'a.json').is_file()
    assert (target / 'cookies' / 'zhihu_cookies.json').is_file()


def test_a_wal_companion_is_planned_and_never_left_behind(tmp_path):
    """A database's -wal/-shm travel with it; a checkpointed-away companion is not an error."""
    root = tmp_path / 'data'
    _legacy_tree(root)
    user_id = _registry(root)
    (root / 'runs.db-wal').write_bytes(b'')
    planned = migration.plan(root, 'admin')
    names = {Path(src).name for src, _dst in planned['moves']}
    assert {'runs.db', 'runs.db-wal'} <= names
    migration.migrate(root, 'admin', apply=True)
    assert not (root / 'runs.db-wal').exists()
    target = root / 'users' / user_id
    assert (target / 'runs.db').is_file()


def test_an_occupied_destination_is_refused(tmp_path):
    root = tmp_path / 'data'
    _legacy_tree(root)
    user_id = _registry(root)
    (root / 'users' / user_id).mkdir(parents=True)
    (root / 'users' / user_id / 'runs.db').write_bytes(b'existing')
    with pytest.raises(migration.MigrationError):
        migration.migrate(root, 'admin', apply=True)


def test_a_missing_account_is_refused(tmp_path):
    root = tmp_path / 'data'
    _legacy_tree(root)
    with pytest.raises(migration.MigrationError):
        migration.migrate(root, 'admin', apply=False)
