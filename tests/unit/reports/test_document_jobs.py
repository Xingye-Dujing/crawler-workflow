"""The document-job runtime: bounded threads, owner-only reads, and the same body either way."""

import threading
import time

import pytest
from runtime import account_context
from runtime.account_context import Account

from services.reports import jobs

ALICE = Account('u_aaaaaaaaaaaa', 'alice', 'user')
BOB = Account('u_bbbbbbbbbbbb', 'bob', 'user')

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs.reset()
    account_context.clear()
    yield
    jobs.reset()
    account_context.clear()


def _wait(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job is not None and job['state'] != 'running':
            return job
        time.sleep(0.01)
    raise AssertionError(f'job {job_id} never finished')


def test_a_finished_job_answers_the_body_the_route_used_to_return():
    with account_context.use(ALICE):
        started = jobs.start('x', lambda: (200, {'ok': True, 'name': 'report-1.html'}), lang='en')
        assert started and started['state'] in ('running', 'done')
        job = _wait(started['id'])
    assert job['state'] == 'done'
    assert job['result'] == {'ok': True, 'name': 'report-1.html'}


def test_another_account_cannot_read_the_job():
    with account_context.use(ALICE):
        started = jobs.start('x', lambda: (200, {'ok': True}), lang='en')
        assert started is not None
    with account_context.use(BOB):
        assert jobs.get(started['id']) is None, 'a job id is not a capability across accounts'
    with account_context.use(ALICE):
        assert jobs.get(started['id']) is not None


def test_the_worker_binds_the_starting_account():
    seen = []

    def work():
        seen.append(account_context.current())
        return 200, {'ok': True}

    with account_context.use(ALICE):
        started = jobs.start('x', work, lang='en')
        assert started is not None
        _wait(started['id'])
    assert seen == [ALICE], 'get_run_store()/paths.active() resolved the request-less default'


def test_a_third_job_is_refused_while_two_run():
    release = threading.Event()

    def work():
        release.wait(3)
        return 200, {'ok': True}

    with account_context.use(ALICE):
        first = jobs.start('x', work, lang='en')
        second = jobs.start('x', work, lang='en')
        third = jobs.start('x', work, lang='en')
    assert first is not None and second is not None
    assert third is None, 'an unbounded thread per click is the resource bug on another thread'
    release.set()
    with account_context.use(ALICE):
        _wait(first['id'])
        _wait(second['id'])
