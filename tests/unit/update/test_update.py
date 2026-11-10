"""The self-updater's decisions, without downloading or replacing anything."""

import sys

import pytest

from services import update

pytestmark = pytest.mark.unit


def test_versions_compare_numerically_not_as_strings():
    assert update.version_tuple('2026.11.11.1') > update.version_tuple('2026.9.30.8')
    assert update.is_newer('2026.11.11.1', '2026.11.10.9')
    assert not update.is_newer('2026.11.11.1', '2026.11.11.1')
    assert not update.is_newer('2026.11.10', '2026.11.11')


def test_a_source_run_never_offers_an_update(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    answer = update.check()
    assert answer['ok'] is True
    assert answer['supported'] is False
    assert answer['reason'] == 'source'


def test_a_feed_is_only_accepted_with_a_version_and_platform_table():
    assert update._valid_feed({'schema': 1, 'version': '2026.11.11.1', 'platforms': {}})
    assert not update._valid_feed({'schema': 2, 'version': '2026.11.11.1', 'platforms': {}})
    assert not update._valid_feed({'schema': 1, 'version': '', 'platforms': {}})
    assert not update._valid_feed({'schema': 1, 'version': 'x', 'platforms': []})


def test_the_check_uses_the_platform_key_and_reports_availability(monkeypatch):
    feed = {'schema': 1, 'version': '2026.11.11.1', 'notes': 'fixes', 'platforms': {'win32': {'sha256': 'a'}}}
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(update, 'current_version', lambda: '2026.11.10.1')
    monkeypatch.setattr(update, 'fetch_feed', lambda force=False: feed)
    monkeypatch.setattr(update, '_platform_key', lambda: 'win32')
    answer = update.check()
    assert answer['update_available'] is True
    assert answer['latest'] == '2026.11.11.1'
    assert answer['asset_ready'] is True
    assert answer['notes'] == 'fixes'


def test_the_layout_names_the_online_app_folder(monkeypatch, tmp_path):
    exe = tmp_path / 'app' / 'CaiXiHui.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'MZ')
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(update.machine, 'platform_name', lambda: 'win32')
    mode, root, found = update.install_layout()
    assert mode == 'app'
    assert root == tmp_path
    assert found == exe


def test_the_layout_names_a_portable_folder(monkeypatch, tmp_path):
    exe = tmp_path / 'CaiXiHui' / 'CaiXiHui.exe'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'MZ')
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(update.machine, 'platform_name', lambda: 'win32')
    mode, root, _found = update.install_layout()
    assert mode == 'portable'
    assert root == tmp_path / 'CaiXiHui'


def test_the_macos_layout_names_the_bundle(monkeypatch, tmp_path):
    exe = tmp_path / 'CaiXiHui.app' / 'Contents' / 'MacOS' / 'CaiXiHui'
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b'x')
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(update.machine, 'platform_name', lambda: 'darwin')
    mode, root, _found = update.install_layout()
    assert mode == 'macapp'
    assert root == tmp_path / 'CaiXiHui.app'


def test_the_windows_swap_keeps_user_data_and_offers_rollback():
    script = update._WINDOWS_SCRIPT
    assert 'app.previous' in script
    assert 'components' in script and 'data' in script and 'logs' in script
    assert 'data-root.txt' in script and 'portable.txt' in script
    assert 'Copy-Item' in script and 'Move-Item' in script
    assert 'Start-Process' in script


def test_a_staged_package_is_never_applied_before_it_is_done():
    update._JOB.clear()
    assert update.apply_update()['ok'] is False
