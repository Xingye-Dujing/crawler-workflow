"""Browser profiles: the directory policy, the settings round-trip, and the panel API.

A persistent per-platform Chrome profile exists because a *throwaway* one is measurably
punished: weibo re-issues SUB/SUBP on the first logged-in page load (so a saved snapshot
is stale the next time it is replayed, and the rotated pair replanted into a fresh
browser is bounced back to ``/newlogin``), and xiaohongshu walled a search session twice
within an hour while the user's own browser kept working.

The rules worth pinning are the ones that are invisible when they break:

* **used profile ⇒ no planting.** Importing the cookie file is a one-time act; planting
  it again would overwrite the live session with the stale snapshot — the harm inverted,
  and the crawl would look like a dead cookie. The one exception is an explicit
  ``refresh_cookies=True`` from the panel's own button, which is the door a *re-taken*
  cookie gets in through (see ``TestCookieFileIsNotTheProfileSession``);
* **switched off ⇒ exactly the old behaviour**, including planting every time;
* the settings panel's two new keys survive a round-trip, and a *relative* directory is
  refused with a warning rather than quietly made into a path somewhere surprising;
* ``/api/browser/profiles`` answers for **every matrix platform** — a platform missing
  from that table is a platform the user cannot see the state of.
"""

import json
import threading
import time
from pathlib import Path

import browser_profiles
import pytest

import crawl_capabilities
import crawlers as crawlers_pkg
from settings_store import DEFAULTS, save_settings

pytestmark = pytest.mark.unit


class Recorder:
    """Stands in for a crawler class: records what the factory decided to hand it."""

    last = None

    def __init__(self, headless=True, cookie_path=None, for_login=False, profile_dir=None, abort=None):
        Recorder.last = {
            'headless': headless,
            'cookie_path': cookie_path,
            'for_login': for_login,
            'profile_dir': profile_dir,
            'abort': abort,
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

    def test_an_explicit_refresh_replants_into_a_used_profile(self, profiles_on, fake_crawler, tmp_path):
        """#108, the one door through which a used profile is given the file again.

        Without it the panel's 「保存 Cookie」 writes a file that the crawling browser
        will never read again, and a re-taken session buys nothing.
        """
        cookie_dir = tmp_path / 'cookies'
        cookie_dir.mkdir()
        saved = cookie_dir / 'weibo_cookies.json'
        saved.write_text('[]', encoding='utf-8')
        crawlers_pkg.get_crawler('weibo', cookie_dir=str(cookie_dir))
        crawlers_pkg.get_crawler('weibo', cookie_dir=str(cookie_dir))
        assert fake_crawler()['cookie_path'] is None, 'the second ordinary crawl planted, which is the harm'
        crawlers_pkg.get_crawler('weibo', cookie_dir=str(cookie_dir), refresh_cookies=True)
        # Compared as paths: the factory joins with a forward slash and Windows reports
        # ``tmp_path`` with backslashes, and both name the same file.
        assert Path(fake_crawler()['cookie_path']) == saved

    def test_the_refresh_is_not_a_new_default(self, profiles_on, fake_crawler):
        """A caller that says nothing must not re-plant: a crawl is not a user asking."""
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies')
        crawlers_pkg.get_crawler('weibo', cookie_dir='/tmp/cookies', refresh_cookies=False)
        assert fake_crawler()['cookie_path'] is None


class TestCookieFileIsNotTheProfileSession:
    """Can the panel tell "the file changed" from "the profile already holds this file"?

    The marker records *which* file it was planted from, by mtime and size rather than by
    contents: reading the cookie values to compare them would put a live session in this
    module's memory for no reason, and a re-save always moves the modification time.
    """

    def test_a_file_that_never_changed_needs_no_refresh(self, profiles_on, tmp_path):
        saved = tmp_path / 'weibo_cookies.json'
        saved.write_text('[{"name":"a"}]', encoding='utf-8')
        browser_profiles.mark_used('weibo', imported=True, cookie_stamp=browser_profiles.file_stamp(str(saved)))
        assert browser_profiles.needs_refresh('weibo', str(saved)) is False

    def test_a_file_saved_over_since_needs_one(self, profiles_on, tmp_path):
        saved = tmp_path / 'weibo_cookies.json'
        saved.write_text('[{"name":"a"}]', encoding='utf-8')
        browser_profiles.mark_used('weibo', imported=True, cookie_stamp=browser_profiles.file_stamp(str(saved)))
        saved.write_text('[{"name":"a"},{"name":"b"}]', encoding='utf-8')
        assert browser_profiles.needs_refresh('weibo', str(saved)) is True

    def test_a_profile_used_without_a_file_is_not_nagged(self, profiles_on, tmp_path):
        """Logging in *inside* the profile plants nothing, so there is no "your file is
        newer" to say — and a hint that fired here would push the user to overwrite the
        very session they just created by hand."""
        saved = tmp_path / 'douyin_cookies.json'
        saved.write_text('[{"name":"a"}]', encoding='utf-8')
        browser_profiles.mark_used('douyin', imported=False)
        assert browser_profiles.needs_refresh('douyin', str(saved)) is False

    def test_a_profile_with_no_history_of_what_went_in_says_nothing(self, profiles_on, tmp_path):
        """Every profile built before this field existed answers "I cannot tell", which is
        deliberately not rendered as a hint. The button still works for them."""
        saved = tmp_path / 'zhihu_cookies.json'
        saved.write_text('[{"name":"a"}]', encoding='utf-8')
        browser_profiles.mark_used('zhihu', imported=True)
        assert browser_profiles.needs_refresh('zhihu', str(saved)) is False

    def test_an_unused_profile_is_answered_by_the_next_crawl_not_by_a_button(self, profiles_on, tmp_path):
        saved = tmp_path / 'weibo_cookies.json'
        saved.write_text('[]', encoding='utf-8')
        assert browser_profiles.needs_refresh('weibo', str(saved)) is False

    def test_a_missing_or_unreadable_file_has_no_stamp_rather_than_a_fake_one(self, tmp_path):
        assert browser_profiles.file_stamp(str(tmp_path / 'nope.json')) == ''
        assert browser_profiles.file_stamp('') == ''

    def test_the_status_row_carries_the_answer_for_the_panel(self, profiles_on, tmp_path):
        saved = tmp_path / 'weibo_cookies.json'
        saved.write_text('[{"name":"a"}]', encoding='utf-8')
        browser_profiles.mark_used('weibo', imported=True, cookie_stamp='111:8')
        row = browser_profiles.status('weibo', has_cookie=True, cookie_path=str(saved))
        assert row['needs_refresh'] is True
        assert row['imported'] is True
        # Asked without a path (a caller that cannot know which file), the answer is no —
        # never a guess.
        assert browser_profiles.status('weibo')['needs_refresh'] is False


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


class TestOneBrowserPerProfile:
    """A profile directory holds one Chrome at a time — and that has to be enforced.

    chromedriver pre-writes ``<dir>/Default/Preferences`` before it launches the
    browser, so two sessions created in one directory together cannot both come up:
    measured 2026-09 with two barrier-synchronised crawls, 2 of 8 attempts died with
    ``session not created: failed to write prefs file`` / ``Chrome failed to start:
    crashed``. A parallel canvas is exactly that shape when two of its workflows
    crawl the same platform.
    """

    def test_the_same_directory_shares_one_lock_and_different_ones_do_not(self, tmp_path):
        a = str(tmp_path / 'bilibili')
        assert browser_profiles.lock_for(a) is browser_profiles.lock_for(a)
        assert browser_profiles.lock_for(a) is not browser_profiles.lock_for(str(tmp_path / 'zhihu'))
        # Windows paths differ by case and separator while naming one directory.
        assert browser_profiles.lock_for(a) is browser_profiles.lock_for(a.replace('/', '\\').upper().lower())

    def test_a_second_thread_waits_for_the_first_to_finish(self, tmp_path):
        path = str(tmp_path / 'weibo')
        held = threading.Event()
        release = threading.Event()
        order = []

        def holder():
            lock = browser_profiles.acquire_profile(path, timeout=20)
            assert lock is not None
            held.set()
            release.wait(20)
            order.append('holder-finished')
            browser_profiles.release_profile(lock)

        def waiter():
            held.wait(20)
            lock = browser_profiles.acquire_profile(path, timeout=20)
            order.append('waiter-entered' if lock is not None else 'waiter-refused')
            browser_profiles.release_profile(lock)

        threads = [threading.Thread(target=holder), threading.Thread(target=waiter)]
        for t in threads:
            t.start()
        held.wait(20)
        # The waiter is parked on the lock, so nothing has been appended by it yet.
        time.sleep(0.3)
        assert order == [], f'the second thread got in while the first held the profile: {order}'
        release.set()
        for t in threads:
            t.join(30)
        assert order == ['holder-finished', 'waiter-entered'], order

    def test_an_abort_ends_the_queue_wait_instead_of_burying_the_stop(self, tmp_path):
        """A wait that cannot be cancelled turns 停止 into a lie: the node keeps
        sitting on the lock, the run keeps its slot, the record keeps reading
        运行中 — and the browser the Stop already closed was the only reason the
        wait had an end. The abort is polled in slices, so it lands within ~0.5 s
        rather than after the whole PROFILE_LOCK_TIMEOUT."""
        path = str(tmp_path / 'weibo')
        held = threading.Event()
        release = threading.Event()

        def holder():
            lock = browser_profiles.acquire_profile(path, timeout=20)
            held.set()
            release.wait(20)
            browser_profiles.release_profile(lock)

        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        held.wait(20)
        give_up = threading.Event()
        give_up.set()
        started = time.monotonic()
        lock = browser_profiles.acquire_profile(path, timeout=20, abort=lambda: give_up.is_set())
        release.set()
        thread.join(30)
        assert lock is None, 'the aborted wait still took the profile'
        assert time.monotonic() - started < 1.5, 'the abort was polled too coarsely to end the wait'

    def test_a_crawler_abandons_the_profile_queue_when_its_run_stops(self, tmp_path, monkeypatch):
        """The crawl side of the same promise: the executor's "run is over" check
        reaches the profile wait, and a crawler that gives up the queue says it
        gave up — not blames a browser that was never left open."""
        import crawlers

        monkeypatch.setattr(crawlers.browser_profiles.Config, 'PROFILE_LOCK_TIMEOUT', 20)
        path = str(tmp_path / 'weibo')
        held = browser_profiles.acquire_profile(path, timeout=20)
        assert held is not None
        try:
            with pytest.raises(RuntimeError) as caught:
                _make_waiting_crawler(path)
        finally:
            browser_profiles.release_profile(held)
        text = str(caught.value)
        assert '停止' in text or 'stopped' in text.lower(), f'not the gave-up line: {text}'
        assert '超时' not in text and 'timed out' not in text.lower(), 'a Stop was reported as a stuck profile'


def _make_waiting_crawler(profile_dir: str):
    """A real crawler class pointed at a busy profile with a run already stopped.

    Only the profile claim runs — the browser is never reached — so no Chrome and
    no monkeypatched driver are needed to exercise the give-up path.
    """
    from crawlers.weibo import WeiboCrawler

    return WeiboCrawler(headless=True, profile_dir=profile_dir, abort=lambda: True)

    def test_a_claim_taken_on_one_thread_can_be_released_from_another(self, tmp_path):
        """The browser is closed on a helper thread, so the lock has to survive that.

        This is the shape every real crawl takes: ``_close_login_browser`` gives
        ``quit()`` a bounded grace on a side thread — and if the primitive were an
        RLock, the release there would raise, be swallowed, and leave the profile
        claimed for the rest of the process.
        """
        path = str(tmp_path / 'zhihu')
        results = {}
        started = threading.Event()

        def holder():
            results['lock'] = browser_profiles.acquire_profile(path, timeout=5)
            started.set()
            time.sleep(0.2)
            # Released by whoever the context leaves it to — here, the main thread.

        worker = threading.Thread(target=holder)
        worker.start()
        assert started.wait(10)
        browser_profiles.release_profile(results['lock'])
        gained = browser_profiles.acquire_profile(path, timeout=1)
        assert gained is not None, 'a claim made on another thread could not be handed over'
        browser_profiles.release_profile(gained)
        worker.join(10)

    def test_a_directory_still_held_gives_up_rather_than_waiting_forever(self, tmp_path):
        """The ceiling is what keeps a leaked browser from parking a platform: None is
        the caller's signal to fail with a reason instead of queueing forever."""
        path = str(tmp_path / 'douyin')
        holder = browser_profiles.acquire_profile(path, timeout=5)
        results = {}

        def try_claim():
            results['lock'] = browser_profiles.acquire_profile(path, timeout=0.2)

        t = threading.Thread(target=try_claim)
        t.start()
        t.join(10)
        assert not t.is_alive(), 'the bounded wait never let go'
        assert results['lock'] is None, 'a busy profile must answer None so the caller can say why'
        browser_profiles.release_profile(holder)
        after = browser_profiles.acquire_profile(path, timeout=0.5)
        assert after is not None, 'the directory stayed claimed after its holder released it'
        browser_profiles.release_profile(after)

    def test_releasing_something_unheld_is_not_an_error(self, tmp_path):
        # `close()` runs in finally-blocks; a release that raises would replace the
        # crawl's real outcome with a lock bookkeeping crash.
        browser_profiles.release_profile(None)
        browser_profiles.release_profile(browser_profiles.lock_for(str(tmp_path / 'x')))


class TestCrawlerHoldsItsProfile:
    """The browser owns the claim for its own lifetime, so no caller can forget it.

    Every one of these is a `Crawler` subclass with the real profile plumbing and a
    `_create_driver` that buys no Selenium session — the claim, not the browser, is
    what is under test.
    """

    @staticmethod
    def _probe_class(name, domain, driver_raises=False):
        from crawlers.base import Crawler

        namespace = {
            'domain': domain,
            'login_url': f'https://www.{domain}.com/',
            'get_detail': lambda self, url: None,
            'search': lambda self, **kw: [],
        }
        if driver_raises:

            def _create(self):
                raise RuntimeError('session not created')

            namespace['_create_driver'] = _create
        else:

            def _create(self):
                self.driver = None

            namespace['_create_driver'] = _create
        return type(name, (Crawler,), namespace)

    @staticmethod
    def _held_elsewhere(path):
        """Claim *path* from another thread and hand back a releaser.

        Another thread is the only shape that matters: the exclusion exists because a
        parallel run starts two crawls of one platform in two pool threads, and a
        same-thread re-claim is not something the product does.
        """
        acquired = threading.Event()
        stop = threading.Event()
        held = {'lock': None}

        def hold():
            held['lock'] = browser_profiles.acquire_profile(path, timeout=20)
            acquired.set()
            stop.wait(60)
            browser_profiles.release_profile(held['lock'])

        worker = threading.Thread(target=hold, daemon=True)
        worker.start()
        assert acquired.wait(20), 'the holder thread never claimed the profile'
        assert held['lock'] is not None, 'the holder thread was refused a free profile'

        def release():
            stop.set()
            worker.join(20)

        return release

    def test_close_gives_the_profile_back_to_the_next_crawl(self, tmp_path):
        path = str(tmp_path / 'bilibili')
        crawler = self._probe_class('Open', 'bilibili')(headless=True, profile_dir=path)
        results = {}

        def probe_free():
            results['free'] = browser_profiles.acquire_profile(path, timeout=0.3)

        watcher = threading.Thread(target=probe_free)
        watcher.start()
        watcher.join(10)
        assert results['free'] is None, 'the running browser did not claim its profile, so two would fight over it'
        crawler.close()
        gained = browser_profiles.acquire_profile(path, timeout=0.3)
        assert gained is not None, 'closing the browser did not give the profile back'
        browser_profiles.release_profile(gained)

    def test_a_browser_that_never_came_up_leaves_no_claim_behind(self, tmp_path):
        """__init__ claims, then buys the driver. A chromedriver refusal has to walk
        the claim back, or every later run of that platform waits out its timeout on a
        directory nobody is using."""
        path = str(tmp_path / 'weibo')
        broken = self._probe_class('Broken', 'weibo', driver_raises=True)
        with pytest.raises(RuntimeError, match='session not created'):
            broken(headless=True, profile_dir=path)
        gained = browser_profiles.acquire_profile(path, timeout=0.2)
        assert gained is not None, 'a failed browser locked the profile for the rest of the process'
        browser_profiles.release_profile(gained)

    def test_a_profile_held_by_someone_else_fails_with_a_reason(self, tmp_path, monkeypatch):
        """Not a silent hang and not a chromedriver stack trace: the node has to say
        which directory it is waiting for and that a browser is holding it."""
        from config import Config

        path = str(tmp_path / 'douyin')
        self._held_elsewhere(path)
        monkeypatch.setattr(Config, 'PROFILE_LOCK_TIMEOUT', 0.2)
        crawler_class = self._probe_class('Waiter', 'douyin')
        with pytest.raises(RuntimeError) as raised:
            crawler_class(headless=True, profile_dir=path)
        assert path in str(raised.value), f'the message must name the directory that is busy: {raised.value}'

    def test_a_throwaway_browser_claims_nothing(self, tmp_path):
        """Profiles switched off (or declined for one run) is the old behaviour: every
        crawl is its own device, and nothing may serialise them."""
        crawler = self._probe_class('Ephemeral', 'zhihu')(headless=True, profile_dir=None)
        assert crawler._profile_lock is None
        crawler.close()
        crawler.close()  # idempotent — callers close in a finally
