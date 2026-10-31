"""Account layout and identity context: the two seams every scoped lookup goes through."""

import os

import pytest
from core.config import Config
from runtime import account_context, paths
from runtime.account_context import Account


def test_system_paths_follow_config_live(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(Config, 'COOKIE_DIR', str(tmp_path / 'cookies'))
    first = paths.system()
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'other'))
    second = paths.system()
    assert first.data_dir == str(tmp_path / 'data')
    assert second.data_dir == str(tmp_path / 'other')
    # A monkeypatched standalone directory is not overwritten by a DATA_DIR join.
    assert second.cookie_dir == str(tmp_path / 'cookies')


def test_user_paths_are_one_tree_under_users(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'data'))
    got = paths.for_user('u_0123456789ab')
    root = str(tmp_path / 'data' / 'users' / 'u_0123456789ab')
    assert got.data_dir == root
    assert got.runs_db == os.path.join(root, 'runs.db')
    assert got.datasets_db == os.path.join(root, 'datasets.db')
    assert got.workflow_dir == os.path.join(root, 'workflows')
    assert got.cookie_dir == os.path.join(root, 'cookies')
    assert got.schedules_json == os.path.join(root, 'schedules.json')
    got.ensure()
    assert os.path.isdir(got.cookie_dir)
    assert os.path.isdir(got.export_dir)


@pytest.mark.parametrize('bad', ['', '..', 'u_zzzzzzzzzzzz', 'u_0123456789ab/../x', 'alice'])
def test_user_id_must_be_server_minted(monkeypatch, tmp_path, bad):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'data'))
    with pytest.raises(ValueError):
        paths.for_user(bad)


def test_active_is_the_bound_account_then_the_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, 'DATA_DIR', str(tmp_path / 'data'))
    alice = Account('u_0123456789ab', 'alice')
    assert paths.active().data_dir == paths.system().data_dir
    with account_context.use(alice):
        assert paths.active().data_dir == paths.for_user(alice.user_id).data_dir
        assert account_context.scope_key() == alice.user_id
        with account_context.use(None):
            assert account_context.current() is None
            assert paths.active().data_dir == paths.system().data_dir
        assert account_context.current() == alice
    assert account_context.current() is None
    assert account_context.scope_key() == 'system'
