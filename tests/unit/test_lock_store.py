"""``services/lock_store`` — the small JSON store behind the panel locks (#182).

The endpoints are thin; what must be pinned here is the store's own contract: a key
round-trips per panel, an unknown panel raises rather than silently filing a lock
nobody reads back, ``drop`` forgets a dead entry, and — critically — the file lives
under ``Config.DATA_DIR`` resolved at call time, so the suite's isolation lands it in
the throwaway root and never touches the user's ``data/``.
"""

import pytest

from config import Config
from services import lock_store

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Point DATA_DIR at a temp root so every test writes its own locks.json."""
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path))


class TestLockRoundTrip:
    def test_a_key_locks_then_unlocks_within_its_own_panel(self):
        assert lock_store.set_locked('exports', 'a.csv', True) == ['a.csv']
        assert lock_store.is_locked('exports', 'a.csv') is True
        # The same key in another panel is a different lock.
        assert lock_store.is_locked('workflows', 'a.csv') is False
        assert lock_store.set_locked('exports', 'a.csv', False) == []
        assert lock_store.is_locked('exports', 'a.csv') is False

    def test_all_locks_lists_every_panel(self):
        lock_store.set_locked('runs', 'r1', True)
        snapshot = lock_store.all_locks()
        assert set(snapshot) == set(lock_store.PANELS)
        assert snapshot['runs'] == ['r1']

    def test_unknown_panel_is_refused_not_filed_silently(self):
        with pytest.raises(KeyError):
            lock_store.set_locked('secrets', 'x', True)
        assert lock_store.is_locked('secrets', 'x') is False

    def test_drop_removes_a_lock_for_a_deleted_entry(self):
        lock_store.set_locked('workflows', 'flow', True)
        lock_store.drop('workflows', 'flow')
        assert lock_store.is_locked('workflows', 'flow') is False

    def test_two_keys_are_sorted_and_deduplicated(self):
        lock_store.set_locked('exports', 'b.csv', True)
        lock_store.set_locked('exports', 'a.csv', True)
        lock_store.set_locked('exports', 'a.csv', True)
        assert lock_store.all_locks()['exports'] == ['a.csv', 'b.csv']
