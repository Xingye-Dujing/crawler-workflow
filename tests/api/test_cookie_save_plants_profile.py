"""Saving a cookie IS the plant: one cookie, one profile (#108's button, now deleted).

A platform profile imports the cookie file **once** and is not planted again, because
overwriting a live session with an older snapshot is the measured harm (weibo re-issues
SUB/SUBP on the first logged-in load). That rule protects a crawl from the app, not the
user from themselves — and the panel had left the other half unattended: paste a fresh
cookie and the browser that would actually crawl with it never read it again, unless the
user noticed and pressed 「把 Cookie 更新进 Profile」.

A paste is not an older snapshot; it is the newest session there is. So the save path now
does the transfer itself, and what is left to test is what it says when it *cannot* do it
on the spot (that account's browser is held) — the file is newer than the profile, and
``crawlers/__init__.py`` honours ``needs_refresh`` so the next crawl brings it in.

No Chrome is bought by any test here: the factory is stubbed and records the decisions.
"""

import pytest

pytestmark = [pytest.mark.api, pytest.mark.serial]

_PASTE = [{'name': 'SUB', 'value': 'x', 'domain': '.weibo.com'}]


class _FakeCrawler:
    """A crawler that was already planted, so only the handler's decisions are observable."""

    def __init__(self, planted=3):
        self.cookies_loaded = planted
        self.driver = None
        self.closed = 0

    def close(self):
        self.closed += 1


@pytest.fixture
def factory(monkeypatch, app_module, tmp_path):
    """A profile that exists and has been used, plus a stubbed browser factory."""
    made = []

    def _install(planted=3, error=None, enabled=True, used=True, busy=False):
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
        monkeypatch.setattr(app_module.browser_profiles, 'is_enabled', lambda: enabled)
        monkeypatch.setattr(app_module.browser_profiles, 'is_used', lambda platform, account='': used)
        monkeypatch.setattr(app_module.browser_profiles, 'is_busy', lambda path: busy)
        monkeypatch.setattr(
            app_module.browser_profiles, 'platform_dir', lambda platform, account='': str(tmp_path / platform)
        )
        return made

    return _install


def _save(client, platform='weibo', account='', cookies=None):
    body = {'platform': platform, 'account': account, 'cookies': cookies or _PASTE}
    return client.post('/api/cookies/save', json=body)


class TestTheSecondUnnamedLogin:
    """A blank name is 「a login with no name yet」, so a second one is a NEW login (#R2).

    Two logins of one platform carry the same cookie names, and the value that would tell them
    apart is the one that rotates (weibo's SUB), so nothing in the paste says "this is the same
    device again". Overwriting on that guess would destroy a login the user paid for, and asking
    every time is the extra click he has already refused. The reading that is safe in both
    directions: blank + taken default = 默认账号2. Replacing a known login is what selecting
    that account in the box means.
    """

    @pytest.fixture(autouse=True)
    def _clean_default(self, app_module):
        """The suite shares one cookie dir per import, and a sibling test mints these labels on
        purpose — so the precondition is set here rather than assumed from execution order.
        """
        for name in ('', 'default2', 'default3'):
            app_module.cookie_manager.delete('weibo', name)

    def test_the_first_blank_save_is_the_default_account(self, client, factory, app_module):
        factory()
        answer = _save(client)
        assert answer.status_code == 200
        assert answer.get_json()['account'] == ''
        assert app_module.cookie_manager.exists('weibo', '')
        assert not app_module.cookie_manager.exists('weibo', 'default2')

    def test_a_second_blank_save_becomes_default2_and_keeps_the_first(self, client, factory, app_module):
        factory()
        _save(client, cookies=[{'name': 'SUB', 'value': 'one', 'domain': '.weibo.com'}])
        second = _save(client, cookies=[{'name': 'SUB', 'value': 'two', 'domain': '.weibo.com'}])
        assert second.status_code == 200, 'the save must not ask, and must not refuse'
        assert second.get_json()['account'] == 'default2'
        assert app_module.cookie_manager.load('weibo', '')[0]['value'] == 'one', 'the first login was clobbered'
        assert app_module.cookie_manager.load('weibo', 'default2')[0]['value'] == 'two'

    def test_the_third_one_counts_on_rather_than_reusing_default2(self, client, factory, app_module):
        factory()
        for value in ('one', 'two', 'three'):
            _save(client, cookies=[{'name': 'SUB', 'value': value, 'domain': '.weibo.com'}])
        assert app_module.cookie_manager.load('weibo', 'default3')[0]['value'] == 'three'

    def test_the_generated_label_is_a_word_not_the_file_segment(self, client, factory, app_module):
        factory()
        _save(client)
        label = _save(client).get_json()['account_label']
        assert 'default2' not in label, f'the panel showed the machine label: {label}'
        assert label, 'an unnamed login still has to be named'

    def test_choosing_an_account_still_overwrites_that_account(self, client, factory, app_module):
        """Selecting the login IS the explicit act — no numbering, no second file."""
        factory()
        _save(client, account='work', cookies=[{'name': 'SUB', 'value': 'one', 'domain': '.weibo.com'}])
        _save(client, account='work', cookies=[{'name': 'SUB', 'value': 'two', 'domain': '.weibo.com'}])
        assert app_module.cookie_manager.entry_count('weibo', 'work') == 1
        assert app_module.cookie_manager.load('weibo', 'work')[0]['value'] == 'two'


class TestThePlantItself:
    def test_a_pasted_cookie_buys_one_browser_and_plants_it(self, client, factory):
        made = factory()
        answer = _save(client)
        assert answer.status_code == 200, answer.get_json()
        assert len(made) == 1, f'saving a cookie opened {len(made)} browsers'
        assert made[0]['refresh_cookies'] is True, 'it planted into a throwaway browser instead'
        assert made[0]['use_profile'] is True

    def test_the_plant_names_the_account_the_paste_was_saved_for(self, client, factory):
        made = factory()
        _save(client, 'weibo', 'work')
        assert made[0]['account'] == 'work', 'the default login was overwritten instead of the chosen account'

    def test_a_headless_plant_works_on_every_platform_now(self, client, factory, app_module):
        """The plant IS a page load on that site, and a headless Chrome reports a desktop
        fingerprint (#148), so even douyin — which used to answer a bare headless browser
        with 验证码中间页 — takes it. Nothing forces a visible window any more."""
        made = factory()
        _save(client, 'douyin', '', [{'name': 'sessionid', 'value': 'x', 'domain': '.douyin.com'}])
        assert made[-1]['platform'] == 'douyin'
        assert made[-1]['headless'] is True

    def test_the_browser_is_closed_whatever_the_plant_counted(self, client, factory, monkeypatch, app_module):
        made = factory(planted=0)
        closed = []
        monkeypatch.setattr(app_module, '_close_login_browser', lambda crawler, **kw: closed.append(crawler))
        answer = _save(client)
        assert answer.status_code == 200
        assert app_module.t('cookie.refresh.done').split('{')[0] in answer.get_json()['message']
        assert closed == [made[0]['crawler']], 'the plant browser was left open holding the profile'

    def test_the_cached_cookie_verdict_is_dropped_after_the_plant(self, client, factory, monkeypatch, app_module):
        """The profile now answers differently than the one the last probe looked at."""
        factory()
        seen = []
        monkeypatch.setattr(app_module.cookie_preflight, 'invalidate', lambda platform: seen.append(platform))
        _save(client)
        assert 'weibo' in seen

    def test_a_plant_of_session_cookies_says_part_of_it_will_not_last(self, client, factory, monkeypatch, app_module):
        """Measured on a real Chrome: a cookie with no expiry is never written to the
        profile store, so it dies with the window opened to plant it. 「已更新」 alone would
        promise a transfer that partly did not happen."""
        factory()
        monkeypatch.setattr(app_module.cookie_manager, 'session_only_count', lambda platform, account='': 2)
        answer = _save(client)
        assert str(2) in answer.get_json()['message'], answer.get_json()
        assert answer.get_json()['profile_note']

    def test_a_fully_persistent_plant_adds_no_warning(self, client, factory, monkeypatch, app_module):
        factory()
        monkeypatch.setattr(app_module.cookie_manager, 'session_only_count', lambda platform, account='': 0)
        answer = _save(client)
        warning = app_module.t('cookie.refresh.sessionOnly', n=1)
        assert warning not in answer.get_json()['message'], answer.get_json()


class TestWhatItNeverDoes:
    def test_no_browser_when_profiles_are_switched_off(self, client, factory):
        """Every crawl is already planted from the file, so a browser would be bought to
        change nothing — and the save must still answer 200 with nothing claimed."""
        made = factory(enabled=False)
        answer = _save(client)
        assert answer.status_code == 200
        assert made == []
        assert answer.get_json()['profile_note'] == '', 'it promised a profile update that never happened'

    def test_a_profile_that_has_never_been_opened_is_created_and_planted_now(self, client, factory):
        """One cookie, one profile — and the profile has to exist to be the account's own.

        Waiting for "the first crawl will import it" left the login in a file its browser had
        never read, which is the state the deleted button existed to patch. Creating the
        directory is what ``profile_dir_for`` does before Chrome starts, so the save owns both
        halves: the file and the device that will use it.
        """
        made = factory(used=False)
        answer = _save(client, account='work')
        assert answer.status_code == 200
        assert len(made) == 1, 'the account got a cookie and no browser'
        assert made[0]['account'] == 'work'
        assert made[0]['use_profile'] is True

    def test_a_busy_profile_is_deferred_out_loud_rather_than_queued(self, client, factory, monkeypatch):
        """Waiting on a profile lock can cost ``PROFILE_LOCK_TIMEOUT`` (900 s) inside an HTTP
        request, which a paste may never do to the browser. The cookie still saves — and the
        reply has to say the profile did not get it yet."""
        made = factory(busy=True)
        answer = _save(client)
        assert answer.status_code == 200, 'a paste must not be lost because a browser is busy'
        assert made == [], 'it queued a browser behind a live profile'
        assert answer.get_json()['profile_note'], 'the paste looked identical to a planted one'

    def test_a_run_in_flight_defers_too(self, client, factory, app_module):
        made = factory()
        app_module.execution_state['running'] = True
        try:
            answer = _save(client)
        finally:
            app_module.execution_state['running'] = False
        assert answer.status_code == 200
        assert made == []
        assert answer.get_json()['profile_note']

    def test_two_saves_at_once_do_not_share_a_browser(self, client, factory, app_module):
        made = factory()
        held = app_module._PROFILE_REFRESH_LOCK
        assert held.acquire(blocking=False), 'something else is holding the plant lock'
        try:
            answer = _save(client)
        finally:
            held.release()
        assert answer.status_code == 200
        assert made == [], 'a contended save bought a browser anyway'
        assert answer.get_json()['profile_note'], 'the second paste was told nothing about its profile'

    def test_a_browser_that_will_not_open_is_reported_but_loses_no_cookie(self, client, factory):
        made = factory(error=RuntimeError('no chromedriver'))
        answer = _save(client)
        assert answer.status_code == 200, 'the paste is the user work product; a browser is not'
        assert made == []
        note = answer.get_json()['profile_note']
        assert 'no chromedriver' in note, note


def app_module_cookie_manager():
    import app as app_module

    return app_module.cookie_manager
