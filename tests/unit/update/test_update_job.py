"""The on-disk update job: what survives a closed window, a reload and a restart."""

import os
import time

import pytest

from services import update_job

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(update_job, 'data_dir', lambda root=None: tmp_path / 'data')
    (tmp_path / 'data' / 'updates').mkdir(parents=True)
    yield tmp_path / 'data' / 'updates'


def test_a_job_is_written_and_read_back(store):
    job = update_job.start(version='2026.11.12.1', asset={'sha256': 'a' * 64}, from_version='2026.11.11.2')
    assert job['state'] == update_job.STATE_DOWNLOADING
    assert job['progress'] == 0
    assert job['owner_pid'] == os.getpid()
    stored = update_job.read()
    assert stored['id'] == job['id']
    assert stored['version'] == '2026.11.12.1'
    assert stored['asset'] == {'sha256': 'a' * 64}
    assert stored['updated']


def test_a_write_merges_instead_of_replacing(store):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(progress=42, worker_pid=1234)
    stored = update_job.read()
    assert stored['progress'] == 42
    assert stored['worker_pid'] == 1234
    assert stored['version'] == '2026.11.12.1', 'a progress tick dropped the rest of the job'


def test_the_browser_never_sees_a_filesystem_path(store):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(state=update_job.STATE_STAGED, staged='/home/someone/data/updates/2026.11.12.1/staged')
    public = update_job.public()
    assert 'staged' in public and public['staged'] is True
    assert '/home/someone' not in repr(public)
    assert public['state'] == update_job.STATE_STAGED


def test_an_empty_store_answers_idle_not_nothing(store):
    public = update_job.public()
    assert public['state'] == update_job.STATE_IDLE
    assert public['progress'] == 0


def test_a_failure_keeps_its_code_and_writes_a_line(store):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.fail('sha', '安装包 SHA-256 校验失败')
    stored = update_job.read()
    assert stored['state'] == update_job.STATE_FAILED
    assert stored['error_code'] == 'sha'
    assert 'SHA-256' in stored['error_detail']
    assert '[sha]' in update_job.log_tail()


def test_the_log_is_append_only_and_readable_afterwards(store):
    update_job.log('第一行', actor='worker')
    update_job.log('第二行')
    tail = update_job.log_tail()
    assert '第一行' in tail and '第二行' in tail
    assert '[worker]' in tail


def test_only_one_worker_owns_the_download(store):
    assert update_job.claim(os.getpid()) is True
    assert update_job.claim(4321) is False, 'a second worker would download into one folder'
    update_job.release(os.getpid())
    assert update_job.claim(4321) is True


def test_a_lock_left_by_a_dead_worker_is_reclaimed(store):
    path = update_job.lock_file()
    path.write_text('999999', encoding='utf-8')
    old = time.time() - 60
    os.utime(path, (old, old))
    assert update_job.claim(os.getpid()) is True, 'a crash must not block every later update'


def test_a_fresh_lock_is_not_stolen(store):
    """``O_EXCL`` then a pid write is two steps; the gap belongs to the worker that owns it."""
    path = update_job.lock_file()
    path.write_text('', encoding='utf-8')
    assert update_job.claim(4321) is False


def test_a_release_never_drops_another_workers_lock(store):
    update_job.lock_file().write_text('4321', encoding='utf-8')
    update_job.release(os.getpid())
    assert update_job.lock_file().exists()


def test_a_sweep_keeps_the_version_a_job_owns(store):
    keep_dir = store / '2026.11.12.1'
    stale_dir = store / '2026.11.11.1'
    keep_dir.mkdir()
    stale_dir.mkdir()
    (keep_dir / 'package.zip').write_bytes(b'x')
    update_job.prune({'2026.11.12.1'})
    assert keep_dir.is_dir()
    assert not stale_dir.exists()
    assert update_job.log_file().parent.is_dir(), 'the sweep must not remove its own folder'


def test_a_worker_is_only_alive_while_the_state_says_so(store):
    update_job.start(version='2026.11.12.1', asset={}, from_version='1')
    update_job.write(worker_pid=os.getpid())
    assert update_job.worker_alive() is True
    update_job.write(state=update_job.STATE_STAGED)
    assert update_job.worker_alive() is False, 'a staged job has no worker any more'


def test_the_marker_lives_beside_the_job(store):
    assert update_job.marker_file().parent == store
    assert update_job.marker_file().name == update_job.MARKER_NAME
    assert update_job.job_file().name == update_job.JOB_NAME
