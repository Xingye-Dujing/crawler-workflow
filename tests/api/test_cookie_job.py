"""Cookie login-job API tests — the async generate flow against a fake crawler.

No browser is launched here: get_crawler is swapped for a stand-in whose
driver can be steered (alive / window-closed / cookie-present), so the JOB
STATE MACHINE — single-flight 409, confirm→saved, cancel→cancelled, dead
window→error, and the status endpoint that the dialog polls — is what's under
test, in milliseconds.
"""

import threading
import time

import pytest

pytestmark = [pytest.mark.api, pytest.mark.serial]


class FakeDriver:
    def __init__(self, crawler):
        self._crawler = crawler
        self.visited = []
        self.service = type('S', (), {'process': type('P', (), {'pid': None})})()

    def get(self, url):
        self.visited.append(url)

    @property
    def window_handles(self):
        if self._crawler.dead:
            raise RuntimeError('window gone')
        return ['w1']

    def get_cookies(self):
        if self._crawler.dead:
            raise RuntimeError('window gone')
        return [{'name': 'SUB', 'value': 'x', 'domain': '.example.com'}]

    def quit(self):
        pass


class FakeCrawler:
    def __init__(self, login_block=None):
        self.domain = 'example.com'
        self.login_url = 'https://example.com/login'
        self.driver = FakeDriver(self)
        self.dead = False
        self.closed = False
        self._block = login_block  # optional Event to stall driver.get

    def close(self):
        self.closed = True


@pytest.fixture
def job(monkeypatch, app_module):
    """Fresh job state + get_crawler swap; yields the list collecting fakes."""
    made = []
    block = threading.Event()
    block.set()

    def fake_get_crawler(platform, headless=True, cookie_dir=None):
        crawler = FakeCrawler(login_block=block)
        made.append(crawler)
        return crawler

    monkeypatch.setattr(app_module, 'get_crawler', fake_get_crawler)
    with app_module._COOKIE_JOB_LOCK:
        app_module._COOKIE_JOB.update(active=False, platform='', phase='', error='', count=0)
        app_module._COOKIE_JOB['cancel'].clear()
        app_module._COOKIE_JOB['confirm'].clear()
    yield {'made': made, 'block': block}
    with app_module._COOKIE_JOB_LOCK:
        app_module._COOKIE_JOB.update(active=False, platform='', phase='', error='', count=0)
        app_module._COOKIE_JOB['cancel'].clear()
        app_module._COOKIE_JOB['confirm'].clear()


def _await_idle(client, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not client.get('/api/cookies/generate/status').get_json()['active']:
            return True
        time.sleep(0.05)
    raise AssertionError('cookie job never settled')


class TestCookieJob:
    def test_confirm_captures_and_saves(self, client, job, app_module):
        r = client.post('/api/cookies/generate', json={'platform': 'zhihu', 'wait_seconds': 10})
        assert r.status_code == 202 and r.get_json()['ok'] is True
        # The job runs on its own thread — confirm once it reaches waiting.
        _await_phase(client, 'waiting')
        assert client.post('/api/cookies/generate/confirm').get_json()['ok'] is True
        assert _await_idle(client)
        body = client.get('/api/cookies/generate/status').get_json()
        assert body['phase'] == 'saved' and body['count'] >= 1
        # Saved cookies are visible through the ordinary status endpoint...
        assert client.get('/api/cookies/status').get_json()['cookies']['zhihu'] is True
        # ...and the browser was closed through the bounded helper.
        assert job['made'][0].closed is True

    def test_second_generate_is_busy_409(self, client, job):
        assert client.post('/api/cookies/generate', json={'platform': 'weibo'}).status_code == 202
        _await_phase(client, 'waiting')
        r = client.post('/api/cookies/generate', json={'platform': 'zhihu'})
        assert r.status_code == 409
        body = r.get_json()
        assert body['busy'] is True and body['platform'] == 'weibo'
        client.post('/api/cookies/generate/cancel')
        assert _await_idle(client)
        assert client.get('/api/cookies/generate/status').get_json()['phase'] == 'cancelled'

    def test_dead_window_becomes_error_not_hang(self, client, job):
        assert client.post('/api/cookies/generate', json={'platform': 'zhihu'}).status_code == 202
        _await_phase(client, 'waiting')
        job['made'][0].dead = True  # user closed the browser at the OS level
        assert _await_idle(client)
        body = client.get('/api/cookies/generate/status').get_json()
        assert body['phase'] == 'error' and body['error']

    def test_cancel_without_job_and_bad_platform(self, client, job):
        assert client.post('/api/cookies/generate/confirm').status_code == 400
        assert client.post('/api/cookies/generate/cancel').status_code == 400
        assert client.post('/api/cookies/generate', json={'platform': 'tumblr'}).status_code == 400
        assert client.post('/api/cookies/generate', json='null').status_code in (400,)


def _await_phase(client, phase, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.get('/api/cookies/generate/status').get_json()['phase'] == phase:
            return
        time.sleep(0.05)
    raise AssertionError(f'cookie job never reached phase {phase!r}')
