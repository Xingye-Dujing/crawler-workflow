"""Browser profiles: the directory policy, the settings round-trip, and the panel API.

A persistent per-platform Chrome profile exists because a *throwaway* one is measurably
punished: weibo re-issues SUB/SUBP on the first logged-in page load (so a saved snapshot
is stale the next time it is replayed, and the rotated pair replanted into a fresh
browser is bounced back to ``/newlogin``), and xiaohongshu walled a search session twice
within an hour while the user's own browser kept working.

The rules worth pinning are the ones that are invisible when they break:

* **used profile ⇒ no planting.** Importing the cookie file is a one-time act; planting
  it again would overwrite the live session with the stale snapshot — the harm inverted,
  and the crawl would look like a dead cookie;
* **switched off ⇒ exactly the old behaviour**, including planting every time;
* the settings panel's two new keys survive a round-trip, and a *relative* directory is
  refused with a warning rather than quietly made into a path somewhere surprising;
* ``/api/browser/profiles`` answers for **every matrix platform** — a platform missing
  from that table is a platform the user cannot see the state of.
"""

import json

import browser_profiles
import pytest

import crawl_capabilities
import crawlers as crawlers_pkg
from settings_store import DEFAULTS, save_settings

pytestmark = pytest.mark.unit


class Recorder:
    """Stands in for a crawler class: records what the factory decided to hand it."""

    last = None

    def __init__(self, headless=True, cookie_path=None, for_login=False, profile_dir=None):
        Recorder.last = {
            'headless': headless,
            'cookie_path': cookie_path,
            'for_login': for_login,
            'profile_dir': profile_dir,
        }


@pytest.fixture
def fake_crawler(monkeypatch):
    Recorder.last = None
    monkeypatch.setattr(crawlers_pkg, 'crawler_class', lambda platform: Recorder)
    return lambda **kw: Recorder.last


def _stub_settings(monkeypatch, *, enabled, root):
    values = {'use_browser_profile': enabled, 'browser_profile_dir': root}
    monkeypatch.setattr(browser_profiles, 'get_setting', lambda key: values[key])


@pytest.fixture
def profiles_off(monkeypatch, tmp_path):
    _stub_settings(monkeypatch, enabled=False, root=str(tmp_path / 'off'))


@pytest.fixture
def profiles_on(tmp_path, monkeypatch):
    values = {'use_browser_profile': True, 'browser_profile_dir': str(tmp_path / 'profiles')}
    _stub_settings(monkeypatch, enabled=True, root=values['browser_profile_dir'])
    return values


class TestPaths:
    def test_a_switched_off_setting_buys_no_directory(self, profiles_off):
        assert browser_profiles.profile_dir_for('weibo') is None
        assert browser_profiles.is_enabled() is False

    def test_the_platform_gets_its_own_directory_under_the_root(self, profiles_on, tmp_path):
        created = tmp_path / 'profiles' / 'weibo'
        assert browser_profiles.profile_dir_for('weibo') == str(created)
        assert created.is_dir(), 'the panel asks whether it exists, so creating it is the contract'

    def test_the_root_follows_the_configured_path(self, tmp_path, monkeypatch):
        configured = str(tmp_path / 'elsewhere')
        _stub_settings(monkeypatch, enabled=True, root=configured)
        assert browser_profiles.profile_dir_for('zhihu').startswith(configured)

    def test_a_blank_platform_is_not_turned_into_the_root_itself(self, profiles_on):
        assert browser_profiles.profile_dir_for('') is None


class TestMarker:
    def test_a_fresh_profile_is_marked_as_needing_an_import(self, profiles_on):
        assert browser_profiles.is_imported('xiaohongshu') is False
        browser_profiles.mark_used('xiaohongshu', imported=True)
        assert browser_profiles.is_imported('xiaohongshu') is True
        assert browser_profiles.is_used('xiaohongshu') is True

    def test_used_and_imported_are_two_different_questions(self, profiles_on):
        """Logging in *inside* the profile imports nothing, yet the profile is used —
        and "used" is what stops the next crawl from planting over its session."""
        browser_profiles.mark_used('douyin', imported=False)
        assert browser_profiles.is_used('douyin') is True
        assert browser_profiles.is_imported('douyin') is False
        status = browser_profiles.status('douyin')
        assert status['used_at'] and status['imported'] is False

    def test_a_corrupt_marker_reads_as_new_rather_than_raising(self, profiles_on):
        path = browser_profiles.profile_dir_for('weibo')
        with open(browser_profiles.marker_path('weibo'), 'w', encoding='utf-8') as handle:
            handle.write('not json{')
        assert browser_profiles.is_imported('weibo') is False
        assert browser_profiles.is_used('weibo') is False, 'an unreadable history must not freeze the credential'
        assert json.loads(json.dumps(browser_profiles.status('weibo')))['platform'] == 'weibo'
        assert path


class TestFactoryPolicy:
    def test_the_first_run_imports_the_saved_cookie_file(self, profiles_on, fake_crawler):
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies')
        assert fake_crawler()['cookie_path'] == '/tmp/cookies/weibo_cookies.json'
        assert fake_crawler()['profile_dir'] == browser_profiles.profile_dir_for('weibo')

    def test_a_second_run_plants_nothing(self, profiles_on, fake_crawler):
        """The rule the whole feature exists for: once the profile has been used, the
        browser's own session wins, or every crawl would rewind the credential."""
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies')
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies')
        assert fake_crawler()['cookie_path'] is None

    def test_turning_profiles_off_restores_the_old_behaviour(self, profiles_off, fake_crawler):
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies')
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies')
        assert fake_crawler()['profile_dir'] is None
        assert fake_crawler()['cookie_path'] == '/tmp/cookies/weibo_cookies.json'

    def test_the_login_browser_gets_the_same_profile_as_the_crawl(self, profiles_on, fake_crawler):
        """Two different directories would mean the user logs into one device and the
        crawl runs as another — which is the failure being fixed."""
        crawlers_pkg.get_crawler('xiaohongshu', cookie_dir='/tmp/cookies', for_login=True)
        login_profile = fake_crawler()['profile_dir']
        crawlers_pkg.get_crawler('xiaohongshu', cookie_dir='/tmp/cookies')
        assert fake_crawler()['profile_dir'] == login_profile
        assert fake_crawler()['for_login'] is False


class TestSettingsRoundTrip:
    def test_both_new_keys_are_declared_with_defaults(self):
        assert DEFAULTS['use_browser_profile'] is True
        assert DEFAULTS['browser_profile_dir'] == ''

    def test_the_switch_round_trips_and_accepts_the_string_form(self):
        values, warnings = save_settings({'use_browser_profile': False})
        assert values['use_browser_profile'] is False and warnings == []
        values, _ = save_settings({'use_browser_profile': 'true'})
        assert values['use_browser_profile'] is True

    def test_a_relative_profile_directory_is_refused_with_a_warning(self):
        values, warnings = save_settings({'browser_profile_dir': 'chrome-stuff'})
        assert values['browser_profile_dir'] == ''
        assert warnings, 'a silently ignored path is worse than a refusal'

    def test_an_absolute_directory_is_taken_as_written(self, tmp_path):
        wanted = str(tmp_path / 'my profiles')
        values, warnings = save_settings({'browser_profile_dir': wanted})
        assert values['browser_profile_dir'] == wanted and warnings == []


class TestMatrixFlag:
    def test_the_recommended_set_is_the_measured_one(self):
        """Pinned as a set: adding a platform here is a claim about a measurement,
        so it has to arrive deliberately and fail loudly if it drifts."""
        flagged = {cap.platform for cap in crawl_capabilities.CAPABILITIES if cap.profile_recommended}
        assert flagged == {'weibo', 'xiaohongshu'}

    def test_the_payload_carries_it_per_platform(self):
        payload = crawl_capabilities.as_dict()
        by_platform = {cap['platform']: cap['profileRecommended'] for cap in payload['platforms']}
        assert by_platform['weibo'] is True and by_platform['zhihu'] is False
        assert set(by_platform) == {cap.platform for cap in crawl_capabilities.CAPABILITIES}
