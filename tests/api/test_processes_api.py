"""The children registry: what is running, whose it is, and whether it can be stopped.

A real (short) child process, no network: the point is that a command the assistant started is
VISIBLE and stoppable after the request that started it is over.
"""

import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.api


@pytest.fixture
def clean_ai():
    from ai import store

    store.mark_interrupted()
    yield


def _spawn(seconds: float = 30) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, '-c', f'import time; time.sleep({seconds})'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    from runtime import processes

    processes.reset_for_tests()
    yield
    processes.reset_for_tests()


class TestRegistry:
    def test_a_child_is_listed_until_it_exits(self):
        from runtime import processes

        child = _spawn()
        try:
            ident = processes.register('cmd', 'python -c sleep', child)
            rows = processes.rows()
            assert [row['id'] for row in rows] == [ident]
            assert rows[0]['kind'] == 'cmd'
            assert rows[0]['pid'] == child.pid
            assert rows[0]['command'] == 'python -c sleep'
        finally:
            processes.stop(ident)
        assert processes.rows() == []

    def test_an_exited_child_disappears_on_its_own(self):
        from runtime import processes

        child = _spawn(0)
        processes.register('cmd', 'short', child)
        child.wait(timeout=10)
        assert processes.rows() == [], 'a finished child stayed in the list'

    def test_stopping_kills_the_child(self):
        from runtime import processes

        child = _spawn()
        ident = processes.register('python', 'quiet loop', child)
        status, _reason = processes.stop(ident)
        assert status == 'stopped'
        child.wait(timeout=10)
        assert child.poll() is not None
        assert processes.rows() == []

    def test_another_accounts_child_is_refused_by_name(self):
        from runtime import processes

        child = _spawn()
        try:
            ident = processes.register('cmd', 'mine', child, owner='someone-else')
            status, reason = processes.stop(ident, owner='system')
            assert status == 'refused'
            assert 'not yours' in reason
            assert processes.rows(owner='someone-else'), 'a refused stop removed the row anyway'
        finally:
            processes.stop(ident, owner='someone-else')

    def test_stopping_something_already_gone_is_not_an_error(self):
        from runtime import processes

        status, _reason = processes.stop('p999')
        assert status == 'gone'


class TestProcessesApi:
    def test_the_route_lists_and_stops_a_child(self, client):
        from runtime import processes

        child = _spawn()
        ident = processes.register('cmd', 'python -c sleep', child)
        listed = client.get('/api/processes').get_json()
        assert listed['ok'] is True
        assert any(row['id'] == ident and row['kind'] == 'cmd' for row in listed['children'])
        stopped = client.post(f'/api/processes/{ident}/stop').get_json()
        assert stopped['ok'] is True and stopped['stopped'] is True
        child.wait(timeout=10)
        assert all(row['id'] != ident for row in client.get('/api/processes').get_json()['children'])

    def test_a_foreign_child_answers_403_in_the_envelope(self, client):
        from runtime import processes

        child = _spawn()
        try:
            ident = processes.register('cmd', 'theirs', child, owner='other-account')
            response = client.post(f'/api/processes/{ident}/stop')
            assert response.status_code == 403
            body = response.get_json()
            assert body['ok'] is False and body['error']
        finally:
            processes.stop(ident, owner='other-account')

    def test_a_child_that_already_exited_is_a_plain_ok(self, client):
        from runtime import processes

        child = _spawn(0)
        ident = processes.register('cmd', 'short', child)
        child.wait(timeout=10)
        body = client.post(f'/api/processes/{ident}/stop').get_json()
        assert body['ok'] is True and body['stopped'] is False


class TestScope:
    """A conversation owns what it started: 停止 or 删除 takes the children with it."""

    def test_stop_scope_only_takes_that_conversations_children(self):
        from runtime import processes

        first = _spawn()
        second = _spawn()
        try:
            processes.register('cmd', 'chat a', first, scope='c_a')
            b = processes.register('cmd', 'chat b', second, scope='c_b')
            assert processes.stop_scope('c_a') == 1
            first.wait(timeout=10)
            assert first.poll() is not None
            assert second.poll() is None, 'another conversation lost its child'
            assert [row['id'] for row in processes.rows()] == [b]
        finally:
            processes.stop_scope('c_b')

    def test_the_stop_route_ends_the_conversations_children(self, client):
        from runtime import processes

        child = _spawn()
        processes.register('cmd', 'chat batch', child, scope='c_stop')
        body = client.post('/api/ai/stop', json={'conversation_id': 'c_stop'}).get_json()
        assert body['ok'] is True
        assert body['stopped_processes'] == 1
        child.wait(timeout=10)
        assert child.poll() is not None

    def test_deleting_a_conversation_stops_its_children(self, client, clean_ai):
        from ai import store
        from runtime import processes

        conversation = store.create_conversation('deepseek', 'deepseek-flash', 'auto')
        child = _spawn()
        processes.register('cmd', 'orphan batch', child, scope=conversation['id'])
        body = client.delete('/api/ai/conversations/' + conversation['id']).get_json()
        assert body['ok'] is True and body['stopped_processes'] == 1
        child.wait(timeout=10)
        assert child.poll() is not None


def test_the_registry_forgets_nothing_that_still_runs():
    """A 30 s child would outlive the test run; prove it is gone after the stop, not merely hidden."""
    from runtime import processes

    child = _spawn()
    ident = processes.register('cmd', 'still here', child)
    assert processes.rows()
    processes.stop(ident)
    deadline = time.time() + 10
    while child.poll() is None and time.time() < deadline:
        time.sleep(0.1)
    assert child.poll() is not None
