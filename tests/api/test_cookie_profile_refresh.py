"""「把 Cookie 更新进 Profile」 — the one door a re-taken cookie gets in through (#108).

A platform profile imports the saved cookie file **once** and is never planted again,
because overwriting a live session with an older snapshot is the harm (weibo re-issues
SUB/SUBP on the first logged-in load). That rule is right for a crawl and left the panel
with no answer at all for a person who had just re-taken a cookie: the file was newer than
what the browser that would do the crawling actually holds, and nothing would ever read it.

So this endpoint exists, and almost every path through it is a refusal — each with its own
sentence, because from a button "there was nothing to do" and "I could not do it" look
identical. The tests below are mostly about that: which refusal, which status code, and
that the success path opens exactly one browser, plants, and closes it again.

No Chrome is bought by any test here: the factory is stubbed, and the fake records the
decisions the handler is supposed to make.
"""

import browser_profiles
import pytest

pytestmark = [pytest.mark.api, pytest.mark.serial]


class _FakeCrawler:
    """A crawler that was already planted, so only the handler's decisions are observable."""

    def __init__(self, planted=3, never_headless=False):
        self.cookies_loaded = planted
        self.driver = None
        self.closed = 0

    def close(self):
        self.closed += 1


@pytest.fixture
def factory(monkeypatch, app_module, tmp_path):
    """A profile that exists and has been used, a real cookie file, and no browser."""
    made = []

    def _install(planted=3, error=None):
        def build(platform, headless=True, cookie_dir=None, use_profile=None, for_login=False, abort=None, **kwargs):
            if error is not None:
                raise error
            crawler = _FakeCrawler(planted)
            made.append(
                {
                    'platform': platform,
                    'headless': headless,
                    'use_profile': use_profile,
                    'cookie_dir': cookie_dir,
                    'crawler': crawler,
                    **kwargs,
                }
            )
            return crawler

        monkeypatch.setattr(app_module, 'get_crawler', build)
        monkeypatch.setattr(app_module.browser_profiles, 'is_enabled', lambda: True)
        monkeypatch.setattr(app_module.browser_profiles, 'is_used', lambda platform: True)
        monkeypatch.setattr(app_module.browser_profiles, 'is_busy', lambda path: False)
        monkeypatch.setattr(app_module.browser_profiles, 'platform_dir', lambda platform: str(tmp_path / platform))
        app_module.cookie_manager.save('weibo', [{'name': 'SUB', 'value': 'x', 'domain': '.weibo.com'}])
        return made

    return _install


def _post(client, platform='weibo'):
    return client.post('/api/cookies/refresh-profile', json={'platform': platform})


class TestWhatItRefuses:
    def test_an_unsupported_platform_is_refused_by_name(self, client, factory):
        factory()
        answer = _post(client, 'secondlife')
        assert answer.status_code == 400
        assert 'secondlife' in answer.get_json()['error']

    def test_a_platform_with_no_saved_file_says_so(self, client, factory, app_module):
        factory()
        app_module.cookie_manager.delete('zhihu')
        answer = _post(client, 'zhihu')
        assert answer.status_code == 400
        assert '没有' in answer.get_json()['error'] or 'no saved' in answer.get_json()['error'].lower()

    def test_a_profile_that_was_never_used_needs_no_button(self, client, factory, monkeypatch, app_module):
        """The next crawl imports the file by itself, and reporting 「已更新」 for a thing
        that has not happened is exactly the overstatement this panel has to keep not doing."""
        factory()
        monkeypatch.setattr(app_module.browser_profiles, 'is_used', lambda platform: False)
        answer = _post(client)
        assert answer.status_code == 400
        assert answer.get_json()['error'] == app_module.t('cookie.refresh.notYet', platform='weibo')

    def test_a_disabled_profile_setting_means_every_crawl_already_plants(self, client, factory, monkeypatch):
        import app as app_module

        monkeypatch.setattr(app_module.browser_profiles, 'is_enabled', lambda: False)
        answer = _post(client)
        assert answer.status_code == 400
        assert answer.get_json()['error'] == app_module.t('cookie.refresh.noProfile')

    def test_a_busy_profile_is_refused_rather_than_queued(self, client, factory, monkeypatch):
        """Waiting on a profile lock can cost ``PROFILE_LOCK_TIMEOUT`` (900 s) inside an
        HTTP request, which is not a thing a button may do to a browser."""
        factory()
        monkeypatch.setattr(browser_profiles, 'is_busy', lambda path: True)
        answer = _post(client)
        assert answer.status_code == 409
        assert answer.get_json()['ok'] is False

    def test_a_run_in_flight_is_refused_too(self, client, factory, app_module):
        factory()
        app_module.execution_state['running'] = True
        try:
            assert _post(client).status_code == 409
        finally:
            app_module.execution_state['running'] = False

    def test_two_presses_at_once_are_refused(self, client, factory, app_module):
        factory()
        held = app_module._PROFILE_REFRESH_LOCK
        assert held.acquire(blocking=False), 'something else is holding the refresh lock'
        try:
            assert _post(client).status_code == 409
        finally:
            held.release()


class TestWhatItDoes:
    def test_it_asks_the_factory_for_a_refresh_planted_into_the_profile(self, client, factory):
        made = factory()
        answer = _post(client)
        assert answer.status_code == 200, answer.get_json()
        assert len(made) == 1
        assert made[0]['refresh_cookies'] is True, 'it planted into a throwaway browser instead'
        assert made[0]['use_profile'] is True
        assert made[0]['cookie_dir']

    def test_a_platform_that_punishes_a_headless_browser_gets_a_window(self, client, factory, app_module):
        """The plant *is* a page load on that site, and douyin answers a headless one with
        验证码中间页 — so the same class flag the run path reads decides the window here."""
        made = factory()
        app_module.cookie_manager.save('douyin', [{'name': 'sessionid', 'value': 'x', 'domain': '.douyin.com'}])
        _post(client, 'douyin')
        assert made[-1]['platform'] == 'douyin'
        assert made[-1]['headless'] is False, 'a headless plant was bought for a platform that refuses one'

    def test_the_browser_is_closed_whatever_the_plant_counted(self, client, factory, monkeypatch, app_module):
        made = factory(planted=0)
        closed = []
        monkeypatch.setattr(app_module, '_close_login_browser', lambda crawler, **kw: closed.append(crawler))
        answer = _post(client)
        assert answer.status_code == 200
        assert answer.get_json()['count'] == 0, 'a plant that took nothing was reported as a success count'
        assert closed == [made[0]['crawler']], 'the refresh browser was left open holding the profile'

    def test_the_cached_cookie_verdict_is_dropped_afterwards(self, client, factory, monkeypatch, app_module):
        """The pre-run probe caches 「Cookie 可用」 per platform; the profile behind that
        answer now holds a different session, so the verdict has to be re-taken."""
        factory()
        seen = []
        monkeypatch.setattr(app_module.cookie_preflight, 'invalidate', lambda platform: seen.append(platform))
        _post(client)
        assert seen == ['weibo']

    def test_a_plant_of_session_cookies_says_part_of_it_will_not_last(self, client, factory, app_module):
        """Measured on a real Chrome: a cookie with no expiry is never written to the
        profile store, so it dies with the window opened to plant it. The count is in the
        answer because 「已更新」 alone would promise more than the mechanism delivers."""
        made = factory()
        del made
        app_module.cookie_manager.save(
            'weibo',
            [
                {'name': 'SUB', 'value': 'x', 'domain': '.weibo.com', 'expiry': 4e9},
                {'name': 'short_lived', 'value': 'y', 'domain': '.weibo.com'},
            ],
        )
        body = _post(client).get_json()
        assert body['session_only'] == 1, body
        assert app_module.t('cookie.refresh.sessionOnly', n=1) in body['message'], body

    def test_a_fully_persistent_plant_adds_no_warning(self, client, factory, app_module):
        factory()
        app_module.cookie_manager.save('weibo', [{'name': 'SUB', 'value': 'x', 'domain': '.weibo.com', 'expiry': 4e9}])
        body = _post(client).get_json()
        assert body['session_only'] == 0, body
        assert '没有有效期' not in body['message'] and 'no expiry' not in body['message'], body

    def test_a_browser_that_will_not_open_reports_and_writes_nothing(self, client, factory):
        factory(error=RuntimeError('no chromedriver'))
        answer = _post(client)
        assert answer.status_code == 500
        body = answer.get_json()
        assert body['ok'] is False and 'no chromedriver' in body['error']


class TestThePanelCanSeeIt:
    def test_the_profile_table_says_which_profiles_are_behind_their_file(self, client, monkeypatch):
        """The hint is the server's answer, not a browser-side guess: it is the only place
        that knows both the marker and the file."""
        monkeypatch.setattr(browser_profiles, 'needs_refresh', lambda platform, path: platform == 'weibo')
        rows = client.get('/api/browser/profiles').get_json()['profiles']
        by_name = {row['platform']: row for row in rows}
        assert by_name['weibo']['needs_refresh'] is True
        assert by_name['zhihu']['needs_refresh'] is False
