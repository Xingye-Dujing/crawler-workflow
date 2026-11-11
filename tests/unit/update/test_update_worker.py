"""The detached download worker: every way it can end, and what the job says afterwards."""

import os
from pathlib import Path

import pytest

from services import update, update_job, update_worker

pytestmark = pytest.mark.unit


class _LinuxMachine:
    """Only the two facts the worker asks: no DMG branch, no asset key."""

    @staticmethod
    def platform_name(*_args, **_kwargs):
        return 'linux'


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(update_job, 'data_dir', lambda root=None: tmp_path / 'data')
    monkeypatch.setattr(update, 'machine', _LinuxMachine())
    (tmp_path / 'data' / 'updates').mkdir(parents=True)
    yield tmp_path / 'data' / 'updates'


def _job(version='2026.11.12.1'):
    return update_job.start(version=version, asset={'sha256': 'a' * 64}, from_version='2026.11.11.2')


def _staged(staged: Path) -> str:
    staged.mkdir(parents=True, exist_ok=True)
    (staged / 'CaiXiHui.exe').write_bytes(b'MZ')
    return str(staged)


def test_a_finished_download_leaves_a_staged_job(store, monkeypatch):
    _job()
    staged = store / '2026.11.12.1' / 'staged'

    def fake_download(asset, package, **_kwargs):
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_bytes(b'zip')

    monkeypatch.setattr(update, 'download_package', fake_download)
    monkeypatch.setattr(update, 'stage_package', lambda package, root: Path(_staged(staged)))
    monkeypatch.setattr(update, 'spawn_swapper', lambda job, wait: {'ok': True})

    assert update_worker.run(Path('job.json')) == 0
    stored = update_job.read()
    assert stored['state'] == update_job.STATE_STAGED
    assert stored['progress'] == 100
    assert stored['staged'] == str(staged)
    assert not update_job.lock_file().exists(), 'the lock must not outlive the worker'


def test_a_bad_digest_is_a_named_failure_not_a_dead_end(store, monkeypatch):
    _job()

    def fake_download(asset, package, **_kwargs):
        raise update.UpdateError('sha', '安装包 SHA-256 校验失败，已拒绝使用')

    monkeypatch.setattr(update, 'download_package', fake_download)
    assert update_worker.run(Path('job.json')) == 1
    stored = update_job.read()
    assert stored['state'] == update_job.STATE_FAILED
    assert stored['error_code'] == 'sha'
    assert 'SHA-256' in stored['error_detail']
    assert update_job.log_file().is_file(), 'a failure leaves evidence on disk'


def test_a_cancel_cleans_up_instead_of_failing(store, monkeypatch):
    _job()
    version_dir = store / '2026.11.12.1'
    version_dir.mkdir()
    (version_dir / 'package.zip.part001').write_bytes(b'x')

    def fake_download(asset, package, **_kwargs):
        raise update.UpdateError('cancelled', '已取消')

    monkeypatch.setattr(update, 'download_package', fake_download)
    assert update_worker.run(Path('job.json')) == 1
    assert update_job.read() == {}, 'a cancelled job is gone, not a failure to retry'
    assert not version_dir.exists(), 'cancelling frees the disk it used'


def test_a_worker_without_a_job_does_nothing(store):
    assert update_worker.run(Path('job.json')) == 1
    assert not update_job.lock_file().exists()


def test_a_second_worker_refuses_the_same_job(store, monkeypatch):
    _job()
    update_job.claim(4321)

    def never(*_args, **_kwargs):
        pytest.fail('a second worker must not download into the same folder')

    monkeypatch.setattr(update, 'download_package', never)
    assert update_worker.run(Path('job.json')) == 1
    assert update_job.read()['state'] == update_job.STATE_DOWNLOADING


def test_the_swap_is_started_when_the_app_that_asked_is_gone(store, monkeypatch):
    _job()
    staged = store / '2026.11.12.1' / 'staged'

    def fake_download(asset, package, **_kwargs):
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_bytes(b'zip')

    calls = []
    monkeypatch.setattr(update, 'download_package', fake_download)
    monkeypatch.setattr(update, 'stage_package', lambda package, root: Path(_staged(staged)))
    monkeypatch.setattr(update, 'spawn_swapper', lambda job, wait: calls.append(wait) or {'ok': True})
    monkeypatch.setattr(update.procs, 'process_alive', lambda pid, system=None: False)

    assert update_worker.run(Path('job.json')) == 0
    assert calls == [False], 'a download that outlived its window must still end in the new build'


def test_a_living_app_keeps_the_restart_in_its_own_hands(store, monkeypatch):
    _job()

    def fake_download(asset, package, **_kwargs):
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_bytes(b'zip')

    calls = []
    monkeypatch.setattr(update, 'download_package', fake_download)
    monkeypatch.setattr(update, 'stage_package', lambda package, root: Path(_staged(store / 'v')))
    monkeypatch.setattr(update, 'spawn_swapper', lambda job, wait: calls.append(wait) or {'ok': True})
    monkeypatch.setattr(update.procs, 'process_alive', lambda pid, system=None: True)

    assert update_worker.run(Path('job.json')) == 0
    assert calls == [], 'the open window offers 重启; a swap now would replace files under it'


def test_a_cancel_that_lands_while_unpacking_is_honoured(store, monkeypatch):
    """A cancel during the (uninterruptible) unpack must not end in "restart to finish"."""
    _job()

    def fake_download(asset, package, **_kwargs):
        package.parent.mkdir(parents=True, exist_ok=True)
        package.write_bytes(b'zip')
        update_job.write(cancel=True)

    staged = store / '2026.11.12.1' / 'staged'
    monkeypatch.setattr(update, 'download_package', fake_download)
    monkeypatch.setattr(update, 'stage_package', lambda package, root: Path(_staged(staged)))
    assert update_worker.run(Path('job.json')) == 1
    assert update_job.read() == {}
    assert not (store / '2026.11.12.1').exists()


def test_progress_is_written_once_per_percent(store, monkeypatch):
    _job()
    writes = []

    def fake_download(asset, package, progress=None, **_kwargs):
        for value in (0, 0, 3, 3, 60, 95):
            progress(value)
            writes.append(update_job.read()['progress'])

    monkeypatch.setattr(update, 'download_package', fake_download)
    monkeypatch.setattr(update, 'stage_package', lambda package, root: Path(_staged(store / 'v')))
    monkeypatch.setattr(update, 'spawn_swapper', lambda job, wait: {'ok': True})
    update_worker.run(Path('job.json'))
    assert writes == [0, 0, 3, 3, 60, 95]
    assert os.getpid() == update_job.read().get('worker_pid')
