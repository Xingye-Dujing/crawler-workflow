"""Tests for the runtime-configuration endpoints the UI bootstraps from.

Two read/write surfaces live here and neither one should surprise the frontend:

* ``GET /api/config`` — the three crawler defaults the canvas pre-fills its
  node forms with. What matters is that the payload is read from the live
  ``Config`` object on every request (a stale copy would make the settings
  panel a lie after an env change), not that any particular default is used.
* ``GET /api/capabilities`` — the crawl matrix the Data Source panel builds
  itself from. The endpoint is the only way the browser learns what a platform
  can do, so the payload has to be the matrix and nothing else.
* ``/api/cookies/*`` — credential bookkeeping. ``status`` only reports whether a
  file exists, and ``save`` refuses anything but the platforms
  ``CookieManager.PLATFORMS`` lists, because the platform name becomes a path
  component — and it drops cookies that belong to some other site.
  ``/api/cookies/generate`` is deliberately untouched here: it drives a real
  browser and sleeps.
"""

import pytest

from config import Config
from services.cookie_manager import CookieManager

pytestmark = pytest.mark.api

CONFIG_KEYS = {'ollama_model', 'default_headless', 'max_workers', 'cloud_mode'}
# The cookie panel's platform set is the manager's own list — mirroring it here
# would only ever record the last time someone forgot the other side.
COOKIE_PLATFORMS = set(CookieManager.PLATFORMS)


class TestConfigEndpoint:
    def test_config_exposes_exactly_the_keys_the_panel_needs(self, client):
        response = client.get('/api/config')
        assert response.status_code == 200
        assert set(response.get_json()) == CONFIG_KEYS

    def test_config_reports_values_from_the_live_config_object(self, client):
        body = client.get('/api/config').get_json()
        assert body['ollama_model'] == Config.OLLAMA_MODEL
        assert body['default_headless'] is Config.DEFAULT_HEADLESS
        assert body['max_workers'] == Config.DEFAULT_MAX_WORKERS
        assert body['cloud_mode'] is Config.CLOUD_MODE, 'the whole Ollama/headless UI hiding reads this flag'

    def test_config_is_not_cached_at_import_time(self, client, monkeypatch):
        monkeypatch.setattr(Config, 'OLLAMA_MODEL', 'patched-model:1')
        monkeypatch.setattr(Config, 'DEFAULT_MAX_WORKERS', 9)
        assert client.get('/api/config').get_json() == {
            'ollama_model': 'patched-model:1',
            'default_headless': True,
            'max_workers': 9,
            'cloud_mode': Config.CLOUD_MODE,
        }

    def test_config_is_read_only(self, client):
        assert client.post('/api/config', json={}).status_code == 405

    @pytest.mark.parametrize('argv', [['cloud'], ['--cloud'], ['CLOUD'], [' run', '--cloud-mode'], ['cloud', '5000']])
    def test_the_command_line_can_raise_the_cloud_switch(self, app_module, argv):
        """``python app.py cloud`` is the launcher line a systemd unit or a shell alias writes,

        so it has to be recognised in the shapes people actually type. The switch matters twice
        over: it is read at import time, and it is the only thing standing between a public
        server and a page that offers a local model, a visible window and a browser-generated
        cookie to whoever opens the URL.
        """
        assert app_module._cloud_requested(argv) is True

    @pytest.mark.parametrize('argv', [[], ['5000'], ['--host', 'cloud.example'], ['work']])
    def test_nothing_else_on_the_command_line_means_cloud(self, app_module, argv):
        assert app_module._cloud_requested(argv) is False


@pytest.mark.usefixtures('profiles_off')
class TestCapabilitiesEndpoint:
    """``/api/capabilities`` is the panel's whole vocabulary, so the two things
    worth pinning are that it is the matrix (not a second list someone maintains)
    and that it carries keys rather than sentences (the payload has no
    language — the canvas translates it)."""

    def test_the_endpoint_hands_out_the_matrix_itself(self, client):
        import crawl_capabilities

        body = client.get('/api/capabilities').get_json()
        assert body == crawl_capabilities.as_dict()

    def test_the_payload_names_the_platforms_the_crawlers_can_crawl(self, client):
        from crawlers import CRAWLERS, is_crawlable

        body = client.get('/api/capabilities').get_json()
        assert [p['platform'] for p in body['platforms']] == [p for p in CRAWLERS if is_crawlable(p)]

    def test_no_text_travels_to_the_browser(self, client):
        """Every word the panel shows is a catalogue key.

        The test is structural because a stray sentence would not break anything
        until somebody switched language and found half a form still in the
        other one.
        """
        body = client.get('/api/capabilities').get_json()
        keys = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key.endswith('Key'):
                        keys.append((key, value))
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(body)
        assert keys, 'the payload stopped carrying any catalogue keys at all'
        # '' is how an absent label travels (not every field has a hint); a key
        # that is neither empty nor dotted is a sentence shipped to the browser.
        assert all(value == '' or '.' in value for _key, value in keys), keys

    def test_it_is_read_only(self, client):
        assert client.post('/api/capabilities', json={}).status_code == 405

    def test_saved_accounts_join_the_fields_options_at_send_time(self, client):
        """账号's real options are per-machine: the matrix declares the shape, and the
        payload lists whatever cookie files exist NOW, oldest login first. The panel
        therefore lists exactly what can be chosen — and the account a NEW node starts
        on is the first one this machine holds, not "not chosen"."""
        saved = client.post(
            '/api/cookies/save', json={'platform': 'zhihu', 'cookies': [{'name': 'a', 'value': 'v'}], 'account': 'work'}
        )
        assert saved.get_json()['ok'] is True, saved.get_json()

        def _field():
            body = client.get('/api/capabilities').get_json()
            zhihu = next(p for p in body['platforms'] if p['platform'] == 'zhihu')
            posts = next(m for m in zhihu['modes'] if m['key'] == 'posts')
            return next(f for f in posts['fields'] if f['key'] == 'account')

        account_field = _field()
        assert [o['value'] for o in account_field['options']] == ['work'], account_field
        # the label of a real account IS its name — the catalogue has no word for it,
        # and I18n.t answers an unknown key verbatim, which is the intent.
        assert account_field['options'][0]['labelKey'] == 'work'
        # A node added to this canvas logs in as the only login there is. Leaving the
        # default '' meant "the 默认账号 file", which on this machine does not exist —
        # the crawl would then hit a wall and hand back an empty table.
        assert account_field['default'] == 'work', account_field
        # 默认账号 is itself an account, with a file of its own: it joins the list the
        # moment that file exists. WHICH of the two is listed first is creation order —
        # measured in ``test_cookie_manager.py``, where the stamps can be set; two saves
        # inside one second here would make the order a coin toss, so this pins the
        # invariant instead: both are offered, the blank one by its catalogue word.
        assert (
            client.post(
                '/api/cookies/save', json={'platform': 'zhihu', 'cookies': [{'name': 'a', 'value': 'v'}]}
            ).get_json()['ok']
            is True
        )
        account_field = _field()
        listed = [o['value'] for o in account_field['options']]
        assert sorted(listed) == ['', 'work'], account_field
        assert next(o for o in account_field['options'] if o['value'] == '')['labelKey'] == 'cookies.accountDefault'
        assert account_field['default'] == listed[0], 'a new node starts on the FIRST login listed'
        # anonymous forms carry no account field at all, and the static matrix did not move
        weibo = next(p for p in client.get('/api/capabilities').get_json()['platforms'] if p['platform'] == 'weibo')
        hot = next(m for m in weibo['modes'] if m['key'] == 'hot')
        assert 'account' not in [f['key'] for f in hot['fields']], hot['fields']


@pytest.mark.usefixtures('profiles_off')
class TestCookieEndpoints:
    def test_status_answers_for_every_supported_platform(self, client):
        body = client.get('/api/cookies/status').get_json()
        assert body['ok'] is True
        assert set(body['cookies']) == COOKIE_PLATFORMS
        # Existence flags only: never the cookie contents.
        assert all(isinstance(flag, bool) for flag in body['cookies'].values())

    def test_status_lists_saved_account_names_without_touching_their_values(self, client, app_module):
        """The panel shows WHICH accounts a platform holds so the user can pick or
        delete one — that list is read off the filenames, and no cookie value is
        opened for it (the same no-peeking rule the existence flags follow)."""
        app_module.cookie_manager.save('weibo', [{'name': 'SUB', 'value': 'secret'}], 'acct_one')
        app_module.cookie_manager.save('weibo', [{'name': 'SUB', 'value': 'other'}], 'acct_two')
        body = client.get('/api/cookies/status').get_json()
        assert set(body['accounts']['weibo']) >= {'acct_one', 'acct_two'}, body['accounts']
        # Every value is a list of NAMES — the shape that cannot carry a session.
        assert all(isinstance(names, list) for names in body['accounts'].values())
        assert all(isinstance(n, str) for names in body['accounts'].values() for n in names)
        assert 'secret' not in str(body['accounts']), 'a cookie value leaked into the listing'

    def test_the_rows_answer_for_each_account_with_metadata_only(self, client, app_module):
        """The management view's whole payload, and the rule it is built under.

        One row per saved login: how many entries, how many of them expire, when the file
        was written, and what that account's OWN browser directory holds. A cookie value is
        the login itself, so the sentence this endpoint exists to answer is asked without
        ever carrying one — which is what the marker below is for: it is a string that
        exists only inside the jar, so its absence from the response is measured, not
        assumed.
        """
        marker = 'VALUE-THAT-MUST-NEVER-LEAVE-THE-JAR'
        app_module.cookie_manager.save('zhihu', [{'name': 'SUB', 'value': marker}, {'name': 'zh-s', 'value': 'x'}])
        app_module.cookie_manager.save('zhihu', [{'name': 'SUB', 'value': marker, 'expiry': 9_999_999_999}], 'work')
        body = client.get('/api/cookies/status').get_json()
        rows = {row['account']: row for row in body['rows'] if row['platform'] == 'zhihu'}
        assert set(rows) == {'', 'work'}, body['rows']
        assert rows['']['entries'] == 2 and rows['']['session_only'] == 2, rows['']
        # The named login has one entry WITH an expiry, so exactly none of it dies with a
        # window — the count is the difference between the two rows, not a repeated total.
        assert rows['work']['entries'] == 1 and rows['work']['session_only'] == 0, rows['work']
        assert rows['']['saved_at'], 'a saved login always knows when it was taken'
        assert marker not in str(body), 'a cookie value left the process'
        assert 'name' not in str([row.keys() for row in body['rows']]), 'a cookie NAME is session data too'

    def test_a_generated_account_name_travels_as_a_key(self, client):
        """默认账号 and 默认账号2 are words this program chose, so they travel as catalogue
        keys; ``work`` is a word the user typed, and it is shown exactly as typed.

        The second blank login is made through the ROUTE, because numbering is the route's
        decision: saving twice into the same account on purpose overwrites, and a test that
        called the manager directly would be asserting a rule it never exercised.
        """
        for account in (None, 'work'):
            payload = {'platform': 'weibo', 'cookies': [{'name': 'a', 'value': 'v'}]}
            if account is not None:
                payload['account'] = account
            assert client.post('/api/cookies/save', json=payload).get_json()['ok'] is True
        second = client.post('/api/cookies/save', json={'platform': 'weibo', 'cookies': [{'name': 'a', 'value': 'v'}]})
        assert second.get_json()['account'] == 'default2', second.get_json()
        rows = {row['account']: row for row in client.get('/api/cookies/status').get_json()['rows']}
        assert rows['']['label_key'] == 'cookies.accountDefault', rows['']
        assert rows['default2']['label_key'] == 'cookies.accountDefaultNumbered', rows['default2']
        assert rows['default2']['label_args'] == {'n': 2}, rows['default2']
        assert rows['work']['label_key'] == '', "a typed name is not this program's word to translate"

    def test_the_profile_half_answers_for_that_account_s_own_directory(self, client, app_module, monkeypatch):
        """The fact the panel could not get before: profiles are per ACCOUNT.

        ``/api/browser/profiles`` answers one row per platform against the DEFAULT file, so
        「这个 profile 里还是旧的那份 Cookie」 was read off the wrong device whenever the
        login had a name. Each row now carries its own account's directory.
        """
        import browser_profiles

        app_module.cookie_manager.save('douyin', [{'name': 'a', 'value': 'v'}])
        app_module.cookie_manager.save('douyin', [{'name': 'a', 'value': 'v'}], 'work')
        # A stamp from BEFORE this file was written: ``needs_refresh`` compares the two, and
        # a marker that recorded no stamp at all answers False on purpose (it cannot claim
        # to know which file the profile was planted from).
        browser_profiles.mark_used('douyin', imported=True, cookie_stamp='1:1', account='work')
        rows = {row['account']: row for row in client.get('/api/cookies/status').get_json()['rows']}
        assert rows['work']['profile_used'] is True and rows['work']['profile_exists'] is True, rows['work']
        # The DEFAULT account's directory exists too — a named device is stored one level
        # inside it, so ``os.path.isdir`` alone can never answer "has THIS account been
        # opened". The marker is what answers it, and the panel reads the marker.
        assert rows['']['profile_exists'] is True, rows['']
        assert rows['']['profile_used'] is False, 'the default device was never opened, and says so'
        # A file newer than what that profile was planted from is the one state nobody can
        # see from outside — and it is per account, not per platform.
        assert rows['work']['needs_refresh'] is True, rows['work']

    def test_no_login_saved_answers_with_no_rows_at_all(self, client):
        """Empty, not a table of zeros: the panel shows 「还没有任何已保存的登录」 because that
        is the answer, and a row per platform with nothing in it would read as eight
        logins that are each somehow missing."""
        assert client.get('/api/cookies/status').get_json()['rows'] == []

    def test_save_persists_into_the_isolated_cookie_dir(self, client, app_module, data_root):
        payload = {'platform': 'weibo', 'cookies': [{'name': 'SUB', 'value': 'x'}]}
        response = client.post('/api/cookies/save', json=payload)
        body = response.get_json()
        assert response.status_code == 200
        assert body['ok'] is True
        assert 'weibo' in body['message'] or '微博' in body['message'] or 'Weibo' in body['message'], (
            'the answer names the platform it saved for — as the key or as the word'
        )

        saved = data_root / 'data' / 'cookies' / 'weibo_cookies.json'
        assert saved.exists()
        assert app_module.cookie_manager.load('weibo') == [{'name': 'SUB', 'value': 'x'}]
        assert client.get('/api/cookies/status').get_json()['cookies']['weibo'] is True

    def test_pasted_cookies_from_another_site_never_enter_the_platform_file(self, client, app_module):
        """An extension export carries whatever the browser held, and a YouTube
        session is issued through a Google sign-in — so ``.google.com`` rows sit
        in the same paste. Those open Gmail and Drive, and have no business in a
        file named after YouTube. A lookalike suffix must not pass either, and an
        entry with no domain is kept because pastes routinely omit it."""
        payload = {
            'platform': 'youtube',
            'cookies': [
                {'name': 'SID', 'value': 'a', 'domain': '.youtube.com'},
                {'name': '__Secure-1PSID', 'value': 'b', 'domain': 'www.youtube.com'},
                {'name': 'SID', 'value': 'c', 'domain': '.google.com'},
                {'name': 'session', 'value': 'd', 'domain': '.evilyoutube.com'},
                {'name': 'PREF', 'value': 'e'},
            ],
        }
        response = client.post('/api/cookies/save', json=payload)
        body = response.get_json()
        assert response.status_code == 200
        assert body['count'] == 3
        assert [c['name'] for c in app_module.cookie_manager.load('youtube')] == ['SID', '__Secure-1PSID', 'PREF']

    def test_a_paste_of_nobody_s_here_is_refused_instead_of_saved_empty(self, client, app_module):
        """Writing an empty list would leave ``youtube_cookies.json`` behind, and
        the panel's exists-flag would call that "cookie configured"."""
        # The data dir is session-wide (the app has no per-test override), and the
        # test above just saved a YouTube file into it — start from a known blank.
        app_module.cookie_manager.delete('youtube')
        response = client.post(
            '/api/cookies/save', json={'platform': 'youtube', 'cookies': [{'name': 'SID', 'domain': '.google.com'}]}
        )
        assert response.status_code == 400
        assert response.get_json()['ok'] is False
        assert app_module.cookie_manager.exists('youtube') is False

    @pytest.mark.parametrize(
        ('payload', 'expected'),
        [
            ({'cookies': [{'name': 'a'}]}, 'Platform is required'),
            ({'platform': 'tiktok', 'cookies': [{'name': 'a'}]}, 'Unsupported platform'),
            ({'platform': 'zhihu', 'cookies': []}, 'Cookies data is required'),
        ],
    )
    def test_save_rejects_input_it_cannot_turn_into_a_safe_file(self, client, payload, expected):
        response = client.post('/api/cookies/save', json=payload)
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert expected in body['error']

    def test_save_of_a_foreign_platform_never_touches_the_store(self, client, data_root):
        payload = {'platform': '../escape', 'cookies': [{'name': 'a'}]}
        response = client.post('/api/cookies/save', json=payload)
        assert response.status_code == 400
        assert response.get_json()['ok'] is False
        # The platform name is a path component, so nothing may be written for
        # an unsupported one — neither inside the cookie dir nor above it.
        assert not (data_root / 'data' / 'cookies' / 'escape_cookies.json').exists()
        assert not (data_root / 'escape_cookies.json').exists()
