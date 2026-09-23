"""``GET /api/browser/profiles`` — the table the settings panel draws.

Three things can only be checked from the request side:

* the payload covers **every platform the matrix declares** (a platform missing from
  this table is a platform whose profile state the user cannot see, so they cannot
  tell "已启用" from "还没在里面登录过");
* `recommended` is read off the matrix, not from a second list the endpoint keeps —
  two descriptions of one fact is how the panel starts suggesting a platform the
  crawl does not;
* a directory is reported as *existing* only after something created it, and as
  *imported* only after a cookie actually went in. Those two booleans are the whole
  guidance sentence in the panel.

``profiles_on`` redirects the module's settings lookup at the isolated tmp root, so
nothing here ever touches the real ``data/chrome_profile``.
"""

import json

import browser_profiles
import pytest

import crawl_capabilities

pytestmark = pytest.mark.api


@pytest.fixture
def profiles_on(tmp_path, monkeypatch):
    values = {'use_browser_profile': True, 'browser_profile_dir': str(tmp_path / 'profiles')}
    monkeypatch.setattr(browser_profiles, 'get_setting', lambda key: values[key])
    return values


def _rows(client):
    body = client.get('/api/browser/profiles').get_json()
    assert body['ok'] is True
    return body


def _session_platforms() -> list:
    """Matrix platforms that have a login session at all, in matrix order.

    The cookie panel's list is the existing answer to "can this platform be logged
    into", so a profile table that invents its own would be a second opinion — and
    WeChat is the platform that proves the difference: article bodies need no login,
    so a "profile" for it would be an empty directory and a row that reads as advice.
    """
    from services.cookie_manager import CookieManager

    return [cap.platform for cap in crawl_capabilities.CAPABILITIES if CookieManager.is_supported(cap.platform)]


class TestProfilesEndpoint:
    def test_every_platform_with_a_session_has_a_row_in_matrix_order(self, client, profiles_on):
        body = _rows(client)
        assert body['enabled'] is True and body['root'].endswith('profiles')
        assert [row['platform'] for row in body['profiles']] == _session_platforms()

    def test_wechat_is_not_offered_a_profile(self, client, profiles_on):
        """No cookie row, no login, nothing for a persistent browser to remember."""
        assert 'wechat' not in [row['platform'] for row in _rows(client)['profiles']]
        assert len(_session_platforms()) >= 6, 'the list went vacuous, so the assertion above proves nothing'

    def test_a_row_carries_exactly_what_the_panel_renders(self, client, profiles_on):
        first = _rows(client)['profiles'][0]
        assert set(first) == {
            'platform',
            'enabled',
            'recommended',
            'path',
            'exists',
            'imported',
            'used_at',
            'size_mb',
            'has_saved_cookie',
        }
        assert json.dumps(first)  # the payload must survive JSON, sizes and all

    def test_the_suggestion_comes_from_the_matrix(self, client, profiles_on):
        declared = {cap.platform: cap.profile_recommended for cap in crawl_capabilities.CAPABILITIES}
        for row in _rows(client)['profiles']:
            reason = f'{row["platform"]} suggests a profile for a reason the matrix does not have'
            assert row['recommended'] == declared[row['platform']], reason

    def test_creating_the_directory_is_what_turns_exists_on(self, client, profiles_on):
        before = {row['platform']: row for row in _rows(client)['profiles']}['weibo']
        assert (before['exists'], before['imported']) == (False, False)
        browser_profiles.profile_dir_for('weibo')
        after = {row['platform']: row for row in _rows(client)['profiles']}['weibo']
        assert (after['exists'], after['imported']) == (True, False)
        browser_profiles.mark_used('weibo', imported=True)
        third = {row['platform']: row for row in _rows(client)['profiles']}['weibo']
        assert (third['exists'], third['imported']) == (True, True)
        assert third['used_at']

    def test_a_switched_off_setting_is_said_rather_than_shown_as_ready(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(
            browser_profiles,
            'get_setting',
            lambda key: {'use_browser_profile': False, 'browser_profile_dir': str(tmp_path / 'p')}[key],
        )
        body = _rows(client)
        assert body['enabled'] is False
        assert all(row['enabled'] is False for row in body['profiles'])

    def test_a_saved_cookie_file_shows_up_as_something_to_import(self, client, profiles_on, monkeypatch, tmp_path):
        cookie = tmp_path / 'cookies' / 'zhihu_cookies.json'
        cookie.parent.mkdir(parents=True, exist_ok=True)
        cookie.write_text('[]', encoding='utf-8')
        monkeypatch.setattr(browser_profiles.Config, 'COOKIE_DIR', str(cookie.parent))
        row = {r['platform']: r for r in _rows(client)['profiles']}['zhihu']
        assert row['has_saved_cookie'] is True
