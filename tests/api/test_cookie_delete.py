"""Deleting a saved cookie: what goes, what stays, and what the answer may claim.

The file a platform's crawl is planted from is one of two places a session can live,
and this endpoint only ever touches one of them. Every test here exists because the
plausible reading of 「删除 Cookie」 is "I am logged out now" — which is true of a
throwaway browser and false of a profile that has already logged in inside itself
(``browser_profiles`` imports the file once and never plants it again).
"""

import contextlib
import os
import shutil

import browser_profiles
import pytest

import i18n
from services.cookie_manager import CookieManager

pytestmark = [pytest.mark.api, pytest.mark.serial]


def _names(line: str, platform: str) -> bool:
    """Does this console line name *platform*?

    A `{platform}` slot is answered with the word the language uses (``t()`` localizes
    it), so counting lines by storage key alone reports "nobody said it" for a sentence
    the user can read — and the "one failure, one line" rule this file checks would pass
    by measuring nothing."""
    forms = {platform, i18n.platform_label(platform, 'zh'), i18n.platform_label(platform, 'en')}
    return any(form in line for form in forms)


@pytest.fixture(autouse=True)
def clean_jar(app_module):
    """No inherited cookie file and no inherited profile history.

    Both dirs are session-scoped tmp paths, so a marker another test wrote would make
    「profile 里还留着会话」 true for reasons this test never set up.
    """
    for platform in CookieManager.PLATFORMS:
        with contextlib.suppress(FileNotFoundError):
            app_module.cookie_manager.delete(platform)
        shutil.rmtree(browser_profiles.platform_dir(platform), ignore_errors=True)
    yield


@pytest.fixture
def saved(app_module):
    """Put a cookie file on disk, as the panel's save button would."""

    def _save(platform='zhihu', count=2):
        app_module.cookie_manager.save(platform, [{'name': f'c{i}', 'value': 'v'} for i in range(count)])
        return platform

    return _save


class TestDelete:
    def test_the_file_is_gone_and_the_status_endpoint_agrees(self, client, app_module, saved):
        saved('weibo')
        assert client.get('/api/cookies/status').get_json()['cookies']['weibo'] is True
        assert client.post('/api/cookies/delete', json={'platform': 'weibo'}).status_code == 200
        assert client.get('/api/cookies/status').get_json()['cookies']['weibo'] is False
        assert app_module.cookie_manager.load('weibo') == []

    def test_the_other_platforms_keep_their_cookies(self, client, app_module, saved):
        """One row of the panel, one platform: a 「清空」 that the button never claimed
        to be would destroy every session the user has."""
        saved('zhihu')
        saved('weibo')
        assert client.post('/api/cookies/delete', json={'platform': 'weibo'}).status_code == 200
        assert client.get('/api/cookies/status').get_json()['cookies'] == {
            platform: platform == 'zhihu' for platform in CookieManager.PLATFORMS
        }

    def test_a_platform_nothing_can_log_in_is_refused_by_name(self, client):
        response = client.post('/api/cookies/delete', json={'platform': '../x'})
        assert response.status_code == 400
        assert '../x' in response.get_json()['error'], 'the refusal has to name what it refused'

    def test_deleting_nothing_is_answered_as_nothing_rather_than_a_fake_success(self, client, app_module):
        """The panel could show 「已删除」 over a file that was never there, and the
        user would believe a stale snapshot had been replaced."""
        app_module.cookie_manager.delete('douyin')
        response = client.post('/api/cookies/delete', json={'platform': 'douyin'})
        assert response.status_code == 404
        assert (
            i18n._EN['cookie.delete.none'].replace('{platform}', i18n.platform_label('douyin', 'en'))
            in response.get_json()['error']
        )

    def test_one_line_for_one_deletion(self, client, app_module, saved):
        saved('bilibili')
        app_module.execution_state['logs'] = []
        assert client.post('/api/cookies/delete', json={'platform': 'bilibili'}).status_code == 200
        said = [line for line in app_module.execution_state['logs'] if _names(line, 'bilibili')]
        assert len(said) == 1, f'the console said it {len(said)} times: {said}'

    def test_the_profile_caveat_is_the_only_extra_line_a_deletion_may_add(self, client, app_module, saved):
        """A second line has to carry a fact the first cannot, not repeat it: the
        service already logs 「已删除」, so the endpoint's own line is the caveat about
        the profile or nothing."""
        saved('youtube')
        browser_profiles.mark_used('youtube', imported=False)
        app_module.execution_state['logs'] = []
        assert client.post('/api/cookies/delete', json={'platform': 'youtube'}).status_code == 200
        said = [line for line in app_module.execution_state['logs'] if _names(line, 'youtube')]
        assert len(said) == 2, f'deletion plus the one fact it cannot carry: {said}'
        assert any('logged in' in line or 'profile' in line for line in said), said

    def test_one_line_for_one_save_too(self, client, app_module):
        """The same pair shipped in the save path years ago: the service logs the
        success and the handler narrated it again, so 「已保存」 printed twice for one
        paste of one JSON blob."""
        app_module.execution_state['logs'] = []
        body = {'platform': 'zhihu', 'cookies': [{'name': 'z_c0', 'value': 'x'}]}
        assert client.post('/api/cookies/save', json=body).status_code == 200
        said = [line for line in app_module.execution_state['logs'] if _names(line, 'zhihu')]
        assert len(said) == 1, f'the console said it {len(said)} times: {said}'

    def test_a_file_that_will_not_go_says_why_once(self, client, app_module, saved, monkeypatch):
        saved('bilibili')

        def refuse(_platform):
            raise OSError('read-only volume')

        monkeypatch.setattr(app_module.cookie_manager, 'delete', refuse)
        app_module.execution_state['logs'] = []
        response = client.post('/api/cookies/delete', json={'platform': 'bilibili'})
        assert response.status_code == 500
        assert 'read-only volume' in response.get_json()['error']
        said = [line for line in app_module.execution_state['logs'] if 'read-only volume' in line]
        assert len(said) == 1, f'one failure was announced {len(said)} times: {said}'

    def test_a_platform_that_never_had_a_profile_is_not_warned_about_one(self, client, app_module, saved):
        """``profile_holds`` is the fact the answer must not guess about: with no
        profile history the file *was* the session, so deleting it really does log the
        next browser out."""
        saved('youtube')
        body = client.post('/api/cookies/delete', json={'platform': 'youtube'}).get_json()
        assert body['profile_holds'] is False
        assert '\n' not in body['message'], f'no profile is in play, so the answer is one line: {body["message"]}'

    def test_a_platform_whose_profile_has_logged_in_keeps_its_session(self, client, app_module, saved):
        saved('youtube')
        browser_profiles.mark_used('youtube', imported=False)
        body = client.post('/api/cookies/delete', json={'platform': 'youtube'}).get_json()
        assert body['profile_holds'] is True
        assert body['message'].count('\n') == 1, 'the caveat is a second line of the same answer'
        assert i18n._EN['cookie.delete.profileHolds'].split('{platform}')[0].strip() in body['message']

    def test_the_profile_directory_survives_the_deletion_it_was_never_about(self, client, app_module, saved):
        """The scope test, measured on the filesystem rather than on a string: this
        endpoint removes one file, and the browser profile keeps whatever it holds."""
        saved('twitter')
        browser_profiles.mark_used('twitter', imported=False)
        marker = browser_profiles.marker_path('twitter')
        assert client.post('/api/cookies/delete', json={'platform': 'twitter'}).status_code == 200
        assert browser_profiles.is_used('twitter') is True
        assert os.path.exists(marker)

    def test_the_switches_off_still_reports_honestly(self, client, app_module, saved, monkeypatch):
        """With profiles disabled the file is the whole session, and a warning about a
        profile that is not in use would send the user hunting for one."""
        monkeypatch.setattr(browser_profiles, 'is_enabled', lambda: False)
        saved('zhihu')
        browser_profiles.mark_used('zhihu', imported=False)
        body = client.post('/api/cookies/delete', json={'platform': 'zhihu'}).get_json()
        assert body['profile_holds'] is False

    def test_a_deleted_cookie_can_be_saved_again(self, client, app_module, saved):
        """The panel's own loop: delete, paste, save. A removal that left the platform
        un-writable (a directory deleted along with the file) would strand it."""
        saved('zhihu')
        assert client.post('/api/cookies/delete', json={'platform': 'zhihu'}).status_code == 200
        body = {'platform': 'zhihu', 'cookies': [{'name': 'z_c0', 'value': 'fresh'}]}
        assert client.post('/api/cookies/save', json=body).status_code == 200
        assert [c['name'] for c in app_module.cookie_manager.load('zhihu')] == ['z_c0']
