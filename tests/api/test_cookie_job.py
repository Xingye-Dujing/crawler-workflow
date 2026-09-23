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

from services.cookie_manager import CookieManager

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
        # Two cookies, on purpose: the identity provider's own session rides along
        # whenever a login ends on its page, and it must not be stored as this
        # platform's cookie.
        return [
            {'name': 'SUB', 'value': 'x', 'domain': '.example.com'},
            {'name': 'SID', 'value': 'g', 'domain': '.google.com'},
        ]

    def quit(self):
        pass


class FakeCrawler:
    def __init__(self, login_block=None, facts=None, hold=None):
        self.domain = 'example.com'
        self.login_url = 'https://example.com/login'
        self.driver = FakeDriver(self)
        self.dead = False
        self.closed = False
        self._block = login_block  # optional Event to stall driver.get
        self.diagnosed = []
        self._facts = facts if facts is not None else {'login_wall': False, 'url': 'https://example.com/feed'}
        # A probe that answers instantly is never caught mid-flight by a poller,
        # so a test that wants to act *during* one holds it here.
        self._hold = hold

    def close(self):
        self.closed = True

    def diagnose(self, url=''):
        self.diagnosed.append(url)
        if self._hold is not None:
            self._hold.wait(5)
        return dict(self._facts)


@pytest.fixture
def job(monkeypatch, app_module):
    """Fresh job state + get_crawler swap; yields the list collecting fakes."""
    made = []
    block = threading.Event()
    block.set()
    state = {'facts': None, 'hold': None}

    def fake_get_crawler(platform, headless=True, cookie_dir=None, for_login=False):
        crawler = FakeCrawler(login_block=block, facts=state['facts'], hold=state['hold'])
        # What the window was built for, recorded so a test can assert it: a login
        # browser that does not ask for images cannot show a QR code.
        crawler.requested = {'headless': headless, 'for_login': for_login}
        made.append(crawler)
        return crawler

    monkeypatch.setattr(app_module, 'get_crawler', fake_get_crawler)

    def reset():
        with app_module._COOKIE_JOB_LOCK:
            app_module._COOKIE_JOB.update(
                active=False,
                kind='',
                platform='',
                phase='',
                error='',
                count=0,
                entry='',
                facts={},
                lines=[],
            )
            app_module._COOKIE_JOB['cancel'].clear()
            app_module._COOKIE_JOB['confirm'].clear()

    reset()
    yield {'made': made, 'block': block, 'state': state}
    reset()


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

    def test_the_login_window_is_built_to_show_the_qr_code(self, client, job, app_module):
        """A crawl browser blocks images to save seconds per navigation; a *login*
        window that does the same shows the user a page with no QR code to scan, so
        the one step the crawler cannot perform becomes impossible as well.

        Reported by a user re-saving a weibo cookie: the window opened, the code
        area stayed empty. The job has to ask for a human-facing window.
        """
        assert client.post('/api/cookies/generate', json={'platform': 'weibo', 'wait_seconds': 10}).status_code == 202
        _await_phase(client, 'waiting')
        client.post('/api/cookies/generate/confirm')
        assert _await_idle(client)
        made = job['made'][0]
        assert made.requested['for_login'] is True, 'the login window was built as a crawl (images blocked)'
        assert made.requested['headless'] is False, 'a login has to be a window the user can see'

    def test_capture_is_read_on_the_platform_page_not_wherever_login_ended(self, client, job, app_module):
        """A login that finishes on the identity provider's own page (Google behind
        YouTube, Facebook behind Instagram) would otherwise be captured *there*:
        the driver only sees the current page's cookies, so the file would hold
        someone else's session and miss the one the crawl needs. So the browser is
        pulled back to the platform before the read, and a foreign cookie that
        still turns up is dropped rather than saved."""
        assert client.post('/api/cookies/generate', json={'platform': 'youtube', 'wait_seconds': 10}).status_code == 202
        _await_phase(client, 'waiting')
        assert client.post('/api/cookies/generate/confirm').get_json()['ok'] is True
        assert _await_idle(client)
        crawler = job['made'][0]
        assert crawler.driver.visited.count(crawler.login_url) == 2, 'opened, then re-opened to capture'
        assert client.get('/api/cookies/generate/status').get_json()['phase'] == 'saved'
        saved = app_module.cookie_manager.load('youtube')
        assert [c['name'] for c in saved] == ['SUB'], 'the identity provider stayed out of this platform’s file'

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


class TestCookieFlow:
    """The panel's guidance is served, not hard-coded, so the translated steps
    and the host allowlist can never disagree with the crawler."""

    @pytest.mark.parametrize('platform', list(CookieManager.PLATFORMS))
    def test_every_cookie_platform_is_described(self, client, platform):
        flows = client.get('/api/cookies/flow').get_json()['flows']
        by_name = {flow['platform']: flow for flow in flows}
        assert platform in by_name
        assert by_name[platform]['purpose']
        assert by_name[platform]['steps']

    def test_hosts_come_from_the_crawler_that_will_use_them(self, client):
        from crawlers import cookie_hosts

        by_name = {flow['platform']: flow for flow in client.get('/api/cookies/flow').get_json()['flows']}
        for platform in by_name:
            assert by_name[platform]['allowed_hosts'] == list(cookie_hosts(platform))
        assert by_name['zhihu']['login_url'] == 'https://www.zhihu.com/'

    def test_the_registry_and_the_panel_never_drift_apart(self, client):
        """A platform added to the crawler registry but not to the cookie panel
        would save a cookie file nobody reads."""
        import app as app_module

        from crawlers import CRAWLERS

        # Cookie capture is a subset of crawling: WeChat is crawled from public
        # article pages and needs no session, so it must not appear in the panel.
        assert set(app_module.COOKIE_PLATFORMS) < set(CRAWLERS)
        assert 'wechat' not in app_module.COOKIE_PLATFORMS


class TestEntryLink:
    """A pasted link becomes the page the login browser opens, so it has to be
    restricted to the platform's own hosts — anything else would store another
    site's cookies in this platform's file."""

    def test_an_allowed_link_is_what_the_browser_is_sent_to(self, client, job, monkeypatch):
        monkeypatch.setattr('app.cookie_hosts', lambda platform: ('www.zhihu.com',))
        article = 'https://www.zhihu.com/question/1/answer/2'
        assert (
            client.post(
                '/api/cookies/generate', json={'platform': 'zhihu', 'wait_seconds': 10, 'url': article}
            ).status_code
            == 202
        )
        _await_phase(client, 'waiting')
        assert job['made'][0].driver.visited[0] == article
        assert client.get('/api/cookies/generate/status').get_json()['entry'] == article
        client.post('/api/cookies/generate/cancel')
        assert _await_idle(client)

    def test_a_foreign_link_is_rejected_and_says_so_instead_of_landing_elsewhere(self, client, job, monkeypatch):
        monkeypatch.setattr('app.cookie_hosts', lambda platform: ('www.zhihu.com',))
        r = client.post(
            '/api/cookies/generate', json={'platform': 'zhihu', 'wait_seconds': 10, 'url': 'https://evil.test/x'}
        )
        assert r.status_code == 202
        body = r.get_json()
        assert body['entry_rejected'] is True and body['entry_note']
        _await_phase(client, 'waiting')
        # The login page, not the pasted link, is what opened.
        assert job['made'][0].driver.visited == ['https://example.com/login']
        client.post('/api/cookies/generate/cancel')
        assert _await_idle(client)


class TestCookieVerify:
    def test_a_stored_cookie_is_probed_and_the_verdict_comes_back_as_lines(self, client, job, app_module):
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])
        job['state']['facts'] = {'platform': 'zhihu.com', 'url': 'https://www.zhihu.com/signin', 'login_wall': True}
        assert client.post('/api/cookies/verify', json={'platform': 'zhihu'}).status_code == 202
        assert _await_phase(client, 'verified')
        body = client.get('/api/cookies/generate/status').get_json()
        assert body['kind'] == 'verify'
        assert body['facts']['login_wall'] is True
        assert any('login' in line.lower() or '登录' in line for line in body['lines'])

    def test_a_verify_answers_with_the_generic_two_lines(self, client, job, app_module):
        """Every platform answers the same question now — wall or no wall.

        The WeChat-specific third line went with the keyword-search feature; a
        leftover would have the panel reporting on a capability no code has.
        """
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])
        job['state']['facts'] = {'platform': 'www.zhihu.com', 'url': 'https://www.zhihu.com/', 'login_wall': False}
        assert client.post('/api/cookies/verify', json={'platform': 'zhihu'}).status_code == 202
        body = _await_phase(client, 'verified')
        assert len(body['lines']) == 2, 'a verdict is the checked URL plus one wall answer'
        assert not any('公众号' in line or 'MP admin' in line for line in body['lines'])

    def test_verifying_without_a_stored_cookie_is_refused_before_any_browser(self, client, job, app_module):
        app_module.cookie_manager.delete('weibo')
        r = client.post('/api/cookies/verify', json={'platform': 'weibo'})
        assert r.status_code == 400
        assert 'COOKIE' in r.get_json()['error'] or 'cookie' in r.get_json()['error']
        assert job['made'] == []

    def test_a_link_outside_the_platform_is_refused(self, client, job, app_module, monkeypatch):
        monkeypatch.setattr('app.cookie_hosts', lambda platform: ('www.zhihu.com',))
        app_module.cookie_manager.save('zhihu', [{'name': 'x', 'value': 'y'}])
        r = client.post('/api/cookies/verify', json={'platform': 'zhihu', 'url': 'https://evil.test/'})
        assert r.status_code == 400
        assert job['made'] == []

    def test_the_login_buttons_do_not_answer_a_verification(self, client, job, app_module):
        """Done/Cancel belong to a login window. Pressing them while a probe
        runs would claim to confirm a login that never happened."""
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])
        hold = threading.Event()
        job['state']['hold'] = hold
        try:
            assert client.post('/api/cookies/verify', json={'platform': 'zhihu'}).status_code == 202
            _await_phase(client, 'verifying')
            assert client.post('/api/cookies/generate/confirm').status_code == 400
            assert client.post('/api/cookies/generate/cancel').status_code == 400
        finally:
            hold.set()
        assert _await_phase(client, 'verified')
        # The buttons never resolved the probe, so the job finished on its own.
        assert job['made'][0].closed is True

    def test_a_crashing_probe_settles_as_error_not_a_hanging_dialog(self, client, job, app_module, monkeypatch):
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])

        def explode(*_args, **_kwargs):
            raise RuntimeError('chromedriver vanished')

        monkeypatch.setattr(app_module, 'get_crawler', explode)
        assert client.post('/api/cookies/verify', json={'platform': 'zhihu'}).status_code == 202
        assert _await_phase(client, 'error')
        assert 'chromedriver' in client.get('/api/cookies/generate/status').get_json()['error']

    def test_verification_never_shares_the_window_with_a_login(self, client, job, app_module):
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])
        assert client.post('/api/cookies/generate', json={'platform': 'zhihu', 'wait_seconds': 10}).status_code == 202
        _await_phase(client, 'waiting')
        assert client.post('/api/cookies/verify', json={'platform': 'zhihu'}).status_code == 409
        client.post('/api/cookies/generate/cancel')
        assert _await_idle(client)


def _await_phase(client, phase, timeout=6.0):
    """Wait for one phase, then hand back the whole status body.

    Returning it makes ``assert _await_phase(...)`` mean "the job reached this
    phase" instead of "the helper happened to return None".
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get('/api/cookies/generate/status').get_json()
        if body['phase'] == phase:
            return body
        time.sleep(0.05)
    raise AssertionError(f'cookie job never reached phase {phase!r}')
