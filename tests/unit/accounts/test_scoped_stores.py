"""Per-account stores and caches: the same call under two identities must not meet."""

import os

import pandas as pd
import pytest
from core.config import Config
from runtime import account_context, paths, state, stores
from runtime.account_context import Account


@pytest.fixture
def two_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'data'))
    alice = Account('u_aaaaaaaaaaaa', 'alice')
    bob = Account('u_bbbbbbbbbbbb', 'bob')
    yield alice, bob
    for account in (alice, bob):
        stores.release_user(account.user_id)


def test_each_account_gets_its_own_tree(two_accounts):
    alice, bob = two_accounts
    with account_context.use(alice):
        assert stores.get_run_store().db_path == paths.for_user(alice.user_id).runs_db
        assert stores.get_dataset_store().db_path == paths.for_user(alice.user_id).datasets_db
        assert stores.get_workflow_manager().workflow_dir == paths.for_user(alice.user_id).workflow_dir
        assert stores.get_workflow_history_store().db_path == paths.for_user(alice.user_id).workflow_history_db
        assert stores.get_biblio_store().db_path == paths.for_user(alice.user_id).biblio_db
        assert state.cookie_manager.cookie_dir == paths.for_user(alice.user_id).cookie_dir
        assert state.history_service.db_path == paths.for_user(alice.user_id).history_db
        alice_run = stores.get_run_store()
    with account_context.use(bob):
        assert stores.get_run_store().db_path == paths.for_user(bob.user_id).runs_db
        assert stores.get_run_store() is not alice_run
        assert state.cookie_manager.cookie_dir == paths.for_user(bob.user_id).cookie_dir
        assert state.history_service.db_path == paths.for_user(bob.user_id).history_db
    assert os.path.isdir(paths.for_user(bob.user_id).runs_db.rsplit(os.sep, 1)[0])


def test_the_owner_scope_is_unchanged(two_accounts, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'RUNS_DB', str(tmp_path / 'owner-runs.db'))
    monkeypatch.setattr(Config, 'DATASETS_DB', str(tmp_path / 'owner-datasets.db'))
    # Restore the system slots the suite injected, so this test speaks for the owner.
    stores._RUN_STORE = None
    stores._DATASET_STORE = None
    try:
        assert stores.get_run_store().db_path == str(tmp_path / 'owner-runs.db')
        assert stores.get_dataset_store().db_path == str(tmp_path / 'owner-datasets.db')
        assert state.cookie_manager.cookie_dir == Config.COOKIE_DIR
    finally:
        stores._RUN_STORE = None
        stores._DATASET_STORE = None


def test_the_dataset_cache_is_keyed_by_scope(two_accounts):
    alice, bob = two_accounts
    frame = pd.DataFrame({'text': ['same bytes']})
    with account_context.use(alice):
        dataset_id = stores._register_dataset(frame, name='a.csv')
        assert stores._load_dataset(dataset_id) is not None
    with account_context.use(bob):
        # Same content id, but Bob's store never saw the bytes: the A-scoped cache entry must
        # not answer for him.
        assert stores._load_dataset(dataset_id) is None


def test_release_user_forgets_the_slot(two_accounts):
    alice, _ = two_accounts
    with account_context.use(alice):
        stores.get_run_store()
    assert alice.user_id in stores.user_slots()
    stores.release_user(alice.user_id)
    assert alice.user_id not in stores.user_slots()
