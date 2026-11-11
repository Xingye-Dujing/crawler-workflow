"""The self-updater's decisions, without downloading or replacing anything."""

import hashlib
import sys
from pathlib import Path

import pytest

from services import update, update_job

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolated_updates(tmp_path, monkeypatch):
    """Every case owns its ``<data>/updates``: the job file is shared state on disk now."""
    monkeypatch.setattr(update_job, 'data_dir', lambda root=None: tmp_path / 'data')
    monkeypatch.setattr(update, '_FEED_CACHE', {'at': 0.0, 'feed': None, 'error': ''})
    (tmp_path / 'data' / 'updates').mkdir(parents=True)
    yield tmp_path


def _frozen(monkeypatch, current='2026.11.10.1', feed=None):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(update, 'current_version', lambda: current)
    monkeypatch.setattr(update, '_platform_key', lambda: 'win32')
    monkeypatch.setattr(update, 'swap_supported', lambda: True)
    monkeypatch.setattr(update, 'fetch_feed', lambda force=False: feed)
    monkeypatch.setattr(update, '_public_key_pem', lambda: None)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _asset(**overrides):
    asset = {'sha256': 'a' * 64, 'size': 10, 'url': 'https://example.invalid/app.zip'}
    asset.update(overrides)
    return asset


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
    feed = {'schema': 1, 'version': '2026.11.11.1', 'notes': 'fixes', 'platforms': {'win32': _asset()}}
    _frozen(monkeypatch, feed=feed)
    answer = update.check()
    assert answer['update_available'] is True
    assert answer['latest'] == '2026.11.11.1'
    assert answer['asset_ready'] is True
    assert answer['notes'] == 'fixes'
    assert answer['apply_supported'] is True
    assert answer['job']['state'] == update_job.STATE_IDLE


def test_a_package_without_a_digest_is_not_an_offer(monkeypatch):
    """Absence of a digest is "unverified", never "unknown but fine"."""
    asset = _asset()
    asset.pop('sha256')
    feed = {'schema': 1, 'version': '2026.11.11.1', 'platforms': {'win32': asset}}
    _frozen(monkeypatch, feed=feed)
    answer = update.check()
    assert answer['asset_ready'] is False
    assert answer['update_available'] is False
    assert 'SHA-256' in answer['asset_problem']


def test_a_shard_without_a_digest_is_refused_too(monkeypatch):
    asset = _asset(parts=[{'url': 'https://example.invalid/a', 'size': 5}])
    feed = {'schema': 1, 'version': '2026.11.11.1', 'platforms': {'win32': asset}}
    _frozen(monkeypatch, feed=feed)
    assert update.check()['asset_ready'] is False


def test_an_unreachable_feed_keeps_the_job_visible(monkeypatch):
    """The panel must still paint a download that is in flight when the feed is down."""
    _frozen(monkeypatch, feed=None)
    update_job.start(version='2026.11.12.1', asset=_asset(), from_version='2026.11.10.1')
    answer = update.check()
    assert answer['ok'] is True
    assert answer['feed_error']
    assert answer['job']['version'] == '2026.11.12.1'


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


def test_a_linux_build_is_never_offered_an_in_app_update(monkeypatch, tmp_path):
    """The check must not promise what ``request_restart`` would refuse."""
    exe = tmp_path / 'CaiXiHui'
    exe.write_bytes(b'x')
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(update.machine, 'platform_name', lambda: 'linux')
    assert update.swap_supported() is False


def test_the_windows_swap_keeps_user_data_and_waits_for_both_peers():
    script = update._WINDOWS_SCRIPT
    assert 'app.previous' in script
    assert 'components' in script and 'data' in script and 'logs' in script
    assert 'data-root.txt' in script and 'portable.txt' in script
    assert 'Copy-Item' in script and 'Move-Item' in script
    assert 'Start-Process' in script
    # The receipt is the handshake the app waits for; without it a dead swapper is silent.
    assert 'Receipt' in script
    # Both processes must be gone before a file is moved: the app that holds the image and the
    # worker that holds the staged payload.
    assert '$AppPid' in script and '$WorkerPid' in script
    # A locked file (antivirus, a slow close) is retried, never a fixed 900 ms guess.
    assert 'Try-Step' in script
    # A build that dies right after launch is rolled back rather than left as a broken install.
    assert 'Restore-Program' in script and 'HasExited' in script


def test_the_macos_swap_refuses_to_leave_half_a_bundle():
    script = update._MACOS_SCRIPT
    assert 'RECEIPT' in script
    assert 'rollback' in script
    assert 'ditto' in script and 'mv ' in script
    # ``set -u`` but no ``set -e``: every failure is checked so the rollback actually runs.
    assert 'set -u' in script
    assert 'set -e' not in script


def test_a_staged_package_is_never_applied_before_it_is_staged(monkeypatch):
    _frozen(monkeypatch)
    update_job.clear()
    result = update.request_restart()
    assert result['ok'] is False
    assert '下载' in result['error']


def test_the_spawn_asks_for_a_child_that_survives_a_kill():
    """The one regression that broke every shipped updater: flags, not intentions."""
    from core import procs

    flags = procs.popen_kwargs('win32', detached=True)
    if flags:
        assert flags['creationflags'] & 0x08000000, 'no CREATE_NO_WINDOW'
        assert not flags['creationflags'] & 0x00000008, 'DETACHED_PROCESS stops a console child dead'


# ─── Downloading, resuming and the handshake ───


def test_a_verified_shard_is_not_downloaded_again(tmp_path, monkeypatch):
    """A dropped connection costs one shard, not the whole package."""
    parts = [
        {'url': 'https://example.invalid/part1', 'size': 4, 'sha256': _sha(b'AAAA')},
        {'url': 'https://example.invalid/part2', 'size': 4, 'sha256': _sha(b'BBBB')},
    ]
    asset = {'sha256': _sha(b'AAAABBBB'), 'size': 8, 'parts': parts}
    package = tmp_path / 'package.zip'
    first = package.with_name('package.zip.part001')
    first.write_bytes(b'AAAA')
    first.with_name('package.zip.part001.ok').write_text('ok', encoding='utf-8')
    downloaded = []

    def fake_stream(url, destination, **_kwargs):
        downloaded.append(url)
        destination.write_bytes(b'BBBB')
        return 4

    monkeypatch.setattr(update, '_stream', fake_stream)
    update.download_package(asset, package)
    assert downloaded == ['https://example.invalid/part2'], 'the verified shard was fetched again'
    assert package.read_bytes() == b'AAAABBBB'
    assert not first.exists(), 'parts are consumed once merged'


def test_a_package_that_fails_its_digest_is_refused(tmp_path, monkeypatch):
    asset = {'sha256': 'b' * 64, 'size': 4, 'url': 'https://example.invalid/app.zip'}

    def fake_stream(url, destination, **_kwargs):
        destination.write_bytes(b'XXXX')
        return 4

    monkeypatch.setattr(update, '_stream', fake_stream)
    with pytest.raises(update.UpdateError) as caught:
        update.download_package(asset, tmp_path / 'package.zip')
    assert caught.value.code == 'sha'


def test_a_cancel_stops_the_transfer(tmp_path, monkeypatch):
    asset = {'sha256': 'a' * 64, 'size': 4, 'url': 'https://example.invalid/app.zip'}

    def fake_stream(url, destination, *, cancelled=None, **_kwargs):
        destination.write_bytes(b'XX')
        if cancelled is not None and cancelled():
            raise update.UpdateError('cancelled', '已取消')
        return 2

    monkeypatch.setattr(update, '_stream', fake_stream)
    with pytest.raises(update.UpdateError) as caught:
        update.download_package(asset, tmp_path / 'package.zip', cancelled=lambda: True)
    assert caught.value.code == 'cancelled'


def test_a_staged_payload_that_is_not_this_program_is_refused(tmp_path):
    staged = tmp_path / 'staged'
    staged.mkdir()
    (staged / 'random.txt').write_text('x', encoding='utf-8')
    with pytest.raises(update.UpdateError) as caught:
        update.verify_staged(staged, platform='win32')
    assert caught.value.code == 'shape'


def _staged_job(tmp_path, monkeypatch):
    """A staged job whose swap targets are writable, plus a spawn that only records."""
    staging = tmp_path / 'data' / 'updates' / '2026.11.12.1' / 'staged'
    staging.mkdir(parents=True)
    update_job.start(version='2026.11.12.1', asset={}, from_version='2026.11.11.2')
    update_job.write(state=update_job.STATE_STAGED, staged=str(staging))
    monkeypatch.setattr(
        update,
        '_swap_targets',
        lambda: {'ok': True, 'mode': 'app', 'root': tmp_path, 'exe': tmp_path / 'app.exe'},
    )
    monkeypatch.setattr(update.machine, 'platform_name', lambda system=None: 'win32')
    spawned = []
    original = update._spawn_script

    def fake_spawn(script, args):
        spawned.append((script, args))
        return 4242

    monkeypatch.setattr(update, '_spawn_script', fake_spawn)
    return spawned, original


def test_a_helper_that_never_writes_its_receipt_is_refused(tmp_path, monkeypatch):
    """The exact shape of the shipped bug: a spawn that "succeeds" and a script that never runs."""
    spawned, _original = _staged_job(tmp_path, monkeypatch)
    monkeypatch.setattr(update, 'HELPER_TIMEOUT', 0.2)
    result = update.request_restart()
    assert spawned, 'the script was started'
    assert result['ok'] is False
    assert '回执' in result['error']
    assert update_job.read()['state'] == update_job.STATE_STAGED, 'the job must stay retryable'


def test_a_helper_that_reports_in_lets_the_restart_proceed(tmp_path, monkeypatch):
    _spawned, original = _staged_job(tmp_path, monkeypatch)

    def fake_spawn(script, args):
        receipt = Path(args[args.index('-Receipt') + 1])
        receipt.write_text('started', encoding='utf-8')
        return original(script, args)

    monkeypatch.setattr(update, '_spawn_script', fake_spawn)
    result = update.request_restart()
    assert result['ok'] is True and result['restarting'] is True
    job = update_job.read()
    assert job['state'] == update_job.STATE_APPLYING
    assert job['swapper_pid']


def test_closing_the_window_hands_a_staged_update_over(tmp_path, monkeypatch):
    _staged_job(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(update, 'spawn_swapper', lambda job, wait: calls.append(wait) or {'ok': True})
    update.on_app_close()
    assert calls == [False], 'a closing window cannot wait for a receipt'


def test_closing_the_window_leaves_a_download_alone(tmp_path, monkeypatch):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    calls = []
    monkeypatch.setattr(update, 'spawn_swapper', lambda job, wait: calls.append(wait) or {'ok': True})
    update.on_app_close()
    assert calls == [], 'the worker owns the download; closing the window is not a cancel'


def test_the_log_survives_the_sweep_that_drops_old_packages(tmp_path):
    staging = tmp_path / 'data' / 'updates' / '2026.11.9.1' / 'staged'
    staging.mkdir(parents=True)
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_DOWNLOADING)
    update_job.log('下载中')
    update._cleanup_updates()
    assert not staging.exists()
    assert '下载中' in update_job.log_tail()


def test_a_swap_that_never_finished_is_reported_on_the_next_boot(tmp_path, monkeypatch):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_APPLYING, swapper_pid=999999)
    monkeypatch.setattr(update.procs, 'process_alive', lambda pid, system=None: False)
    update._reconcile_boot('2026.11.11.2')
    stored = update_job.read()
    assert stored['state'] == update_job.STATE_FAILED
    assert stored['error_code'] == 'swap_lost'


def test_a_finished_swap_marks_itself_applied(tmp_path):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_APPLYING, swapper_pid=1)
    update._reconcile_boot('2026.11.12.1')
    assert update_job.read()['state'] == update_job.STATE_APPLIED


def test_a_job_for_a_version_already_installed_is_history(tmp_path):
    """Installed it another way? A card offering to "finish" that older version asks to go back."""
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_STAGED, staged=str(tmp_path / 'gone'))
    update._reconcile_boot('2026.11.12.1')
    assert update_job.read() == {}


def test_a_job_for_a_newer_version_keeps_its_prompt(tmp_path):
    update_job.start(version='2026.11.13.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_STAGED, staged=str(tmp_path / 'staged'))
    update._reconcile_boot('2026.11.12.1')
    assert update_job.read()['state'] == update_job.STATE_STAGED
