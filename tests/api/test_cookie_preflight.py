"""The pre-run cookie check: what it decides, what it caches and what it refuses.

Nothing here launches a browser. The one function that would (``_probe_live``) is
swapped for a recorder in almost every test, because what needs pinning is the
*decision* around it — which answer blocks a run, which answer must never be called
a dead cookie, how long a verdict is reused, and what happens when a probe outruns
its deadline. The browser-facing half is covered from the other side: a handful of
tests run the real ``_probe_live`` against a fake ``get_crawler``, and the device tier
probes a real site.

The rule most of these tests exist to protect: **an unreadable page is not a dead
cookie**. A check that blocked on risk control, a timeout or a profile Chrome already
holds would refuse runs that were about to succeed, and would send the user to re-log
in a session that is fine — a cost they cannot undo and this suite cannot forgive.
"""

import contextlib
import shutil
import threading

import browser_profiles
import cookie_preflight
import pytest

import i18n
from config import Config
from services.cookie_manager import CookieManager

pytestmark = [pytest.mark.api, pytest.mark.serial]


class _Probes:
    """Stand-in for ``_probe_live`` that records every call it was asked to make."""

    def __init__(self):
        self.calls = []
        self.answer = {'login_wall': False, 'risk_blocked': False}
        self.by_platform = {}
        # Set to an Event (or a callable) to hold a probe mid-flight, which is how a
        # test catches one on its deadline instead of pretending the wait is instant.
        self.hold = None

    def __call__(self, platform, *, use_profile=None):
        self.calls.append({'platform': platform, 'use_profile': use_profile})
        if self.hold is not None:
            self.hold()
        facts = self.by_platform.get(platform, self.answer)
        return dict(facts) if isinstance(facts, dict) else facts

    @property
    def platforms(self):
        return [call['platform'] for call in self.calls]


@pytest.fixture
def probes(monkeypatch):
    made = _Probes()
    monkeypatch.setattr(cookie_preflight, '_probe_live', made)
    cookie_preflight.reset()
    return made


@pytest.fixture(autouse=True)
def clean_jar(app_module):
    """No saved cookie and no profile history for any platform before each test.

    Both halves matter, in opposite directions: ``Config.COOKIE_DIR`` and
    ``Config.BROWSER_PROFILE_DIR`` are session-scoped tmp paths, so a file one test
    saved (or a profile marker it wrote) is still there for the next — and 「没有
    Cookie 可测」, 「profile 里有会话」 and 「测了，失效」 are three different verdicts.
    A test that wants one of them says so; nothing here may inherit one by luck.
    """
    for platform in CookieManager.PLATFORMS:
        with contextlib.suppress(FileNotFoundError):
            app_module.cookie_manager.delete(platform)
        shutil.rmtree(browser_profiles.platform_dir(platform), ignore_errors=True)
    yield


@pytest.fixture
def probe_zhihu(probes, with_cookie):
    """A platform with a saved cookie, so the gate gets as far as the page."""
    with_cookie('zhihu')
    return probes


@pytest.fixture
def with_cookie(app_module):
    """Give a platform a saved cookie file, as the panel would have."""

    def _give(platform, count=1):
        app_module.cookie_manager.save(platform, [{'name': f'c{i}', 'value': 'v'} for i in range(count)])

    return _give


def _use_profile(monkeypatch, enabled):
    """Pin the profile question without touching the user's settings file."""
    monkeypatch.setattr(browser_profiles, 'is_enabled', lambda: bool(enabled))


class TestVerdicts:
    def test_a_login_page_is_the_only_answer_called_expired(self, probe_zhihu):
        probe_zhihu.answer = {'login_wall': True, 'risk_blocked': False}
        verdict = cookie_preflight.probe('zhihu')
        assert verdict['state'] == cookie_preflight.EXPIRED
        assert verdict['blocking'] is True

    def test_risk_control_is_never_reported_as_a_dead_cookie(self, probe_zhihu):
        """Zhihu answers a page it dislikes with 40362 and a captcha; the session
        behind it may be perfect. The crawler keeps those two facts apart, and this
        module may not merge them back together."""
        probe_zhihu.answer = {'login_wall': False, 'risk_blocked': True}
        verdict = cookie_preflight.probe('zhihu')
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert verdict['blocking'] is False
        assert '风控' in verdict['detail'] or 'risk' in verdict['detail'].lower()

    def test_a_browser_that_would_not_start_is_no_opinion(self, probes, with_cookie):
        with_cookie('weibo')
        probes.answer = {'error': 'chromedriver.exe not found'}
        verdict = cookie_preflight.probe('weibo')
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert verdict['blocking'] is False
        assert 'chromedriver' in verdict['detail'], 'the reason the user sees must be the reason it failed'

    def test_a_page_that_came_back_as_content_is_valid(self, probes, with_cookie):
        with_cookie('bilibili')
        assert cookie_preflight.probe('bilibili')['state'] == cookie_preflight.VALID

    def test_wechat_is_never_blocking_because_it_needs_no_session(self, probes):
        """WeChat is crawled from public article pages. A gate that demanded a
        cookie there would refuse a crawl that has never used one — and it must
        refuse to open a browser to find that out."""
        verdict = cookie_preflight.probe('wechat')
        assert verdict['state'] == cookie_preflight.NO_LOGIN
        assert verdict['blocking'] is False
        assert probes.calls == []

    def test_instagram_holds_a_cookie_but_cannot_be_crawled(self, probes):
        """Capture-only platforms are in the cookie registry and not the crawl
        matrix, so the honest answer is 「not crawlable」 — which blocks nothing,
        because validation already refused the node before this ran."""
        verdict = cookie_preflight.probe('instagram')
        assert verdict['state'] == cookie_preflight.NOT_CRAWLABLE
        assert verdict['blocking'] is False
        assert probes.calls == []

    def test_a_name_nothing_knows_is_answered_without_a_browser(self, probes):
        verdict = cookie_preflight.probe('tumblr')
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert probes.calls == []

    def test_no_file_and_no_profile_leaves_nothing_to_probe(self, probes, monkeypatch, app_module):
        """This is a fact, not a guess about whether a cookie expired: the file is
        absent and no browser has ever held the platform's session."""
        app_module.cookie_manager.delete('xiaohongshu')
        _use_profile(monkeypatch, True)
        verdict = cookie_preflight.probe('xiaohongshu')
        assert verdict['state'] == cookie_preflight.NO_COOKIE
        assert verdict['blocking'] is True
        assert probes.calls == []

    def test_a_used_profile_is_worth_probing_though_the_file_is_gone(self, probes, monkeypatch, app_module):
        """The consequence of deleting a cookie file (#111) and of a profile that
        imports once: a live session can exist with no snapshot beside it. Answering
        「没有 Cookie」 there would refuse a run that was about to work."""
        app_module.cookie_manager.delete('weibo')
        _use_profile(monkeypatch, True)
        browser_profiles.mark_used('weibo', imported=False)
        cookie_preflight.probe('weibo')
        assert probes.platforms == ['weibo']

    def test_a_profile_another_browser_holds_is_left_alone(self, probes, monkeypatch, with_cookie):
        """Waiting on that lock can outlast a whole crawl, and the run holding the
        profile is better evidence about the session than a second browser trying to
        start inside it."""
        with_cookie('zhihu')
        monkeypatch.setattr(browser_profiles, 'is_busy', lambda path: True)
        verdict = cookie_preflight.probe('zhihu')
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert verdict['blocking'] is False
        assert probes.calls == []

    def test_classify_probe_answers_in_that_order(self):
        """The pure part, pinned directly: whoever else learns to read a diagnosis
        (the panel's 验证 button does) gets these three answers, not two."""
        assert cookie_preflight.classify_probe({'error': 'x', 'login_wall': True}) == cookie_preflight.UNKNOWN
        assert cookie_preflight.classify_probe({'login_wall': True, 'risk_blocked': True}) == cookie_preflight.EXPIRED
        assert cookie_preflight.classify_probe({'risk_blocked': True}) == cookie_preflight.UNKNOWN
        assert cookie_preflight.classify_probe({}) == cookie_preflight.VALID


class TestCache:
    def test_a_recent_verdict_is_reused_instead_of_opening_a_second_browser(self, probe_zhihu):
        cookie_preflight.probe('zhihu')
        cookie_preflight.probe('zhihu')
        assert probe_zhihu.platforms == ['zhihu'], 'two presses of one button bought two Chromes'

    def test_a_reused_verdict_says_it_was_reused(self, probe_zhihu):
        """The distinction is the whole honesty of the answer: 「3 分钟前验证过」 and
        「刚验证过」 are different claims about the same verdict."""
        cookie_preflight.probe('zhihu')
        second = cookie_preflight.probe('zhihu')
        assert second['cached'] is True
        assert second['probed'] is False

    def test_no_opinion_is_never_cached(self, probe_zhihu):
        """A timeout, a captcha or a dead driver is not a fact about the session, and
        holding it for five minutes would keep answering later runs with a check that
        never happened."""
        probe_zhihu.answer = {'error': 'no browser'}
        cookie_preflight.probe('zhihu')
        probe_zhihu.answer = {'login_wall': False, 'risk_blocked': False}
        assert cookie_preflight.probe('zhihu')['state'] == cookie_preflight.VALID
        assert probe_zhihu.platforms == ['zhihu', 'zhihu']

    def test_fresh_forces_a_second_look(self, probe_zhihu):
        cookie_preflight.probe('zhihu')
        cookie_preflight.probe('zhihu', fresh=True)
        assert probe_zhihu.platforms == ['zhihu', 'zhihu']

    def test_a_verdict_stops_being_quotable_after_the_ttl(self, probe_zhihu, monkeypatch):
        monkeypatch.setattr(Config, 'COOKIE_PREFLIGHT_TTL', -1)
        cookie_preflight.probe('zhihu')
        cookie_preflight.probe('zhihu')
        assert probe_zhihu.platforms == ['zhihu', 'zhihu']

    def test_saving_a_cookie_drops_the_verdict_it_could_only_invalidate(self, client, probes, with_cookie, app_module):
        """The dangerous direction of the bug: the cached answer was 「失效」, the user
        has now pasted a fresh cookie, and a gate quoting the old verdict would refuse
        the run they just fixed."""
        with_cookie('zhihu')
        probes.answer = {'login_wall': True, 'risk_blocked': False}
        assert client.post('/api/cookies/preflight', json={'platforms': ['zhihu']}).get_json()['blocked'] == ['zhihu']
        body = {'platform': 'zhihu', 'cookies': [{'name': 'z_c0', 'value': 'x'}]}
        assert client.post('/api/cookies/save', json=body).status_code == 200
        probes.answer = {'login_wall': False, 'risk_blocked': False}
        assert client.post('/api/cookies/preflight', json={'platforms': ['zhihu']}).get_json()['blocked'] == []
        assert probes.platforms == ['zhihu', 'zhihu'], 'the second answer came from the new probe, not the cache'

    def test_deleting_a_cookie_drops_the_verdict_too(self, client, probes, app_module):
        app_module.cookie_manager.save('weibo', [{'name': 'SUB', 'value': 'x'}])
        assert client.post('/api/cookies/preflight', json={'platforms': ['weibo']}).status_code == 200
        assert client.post('/api/cookies/delete', json={'platform': 'weibo'}).status_code == 200
        assert cookie_preflight.cached('weibo') is None

    def test_a_manual_verification_refreshes_the_gate(self, client, app_module, monkeypatch):
        """验证 Cookie and the pre-run gate ask the same question of the same browser.
        A user who just watched the panel answer 「已失效」 must not then pay for a
        second probe to be told the same thing — and a cached 「可用」 must not survive
        the check that contradicted it."""
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])
        cookie_preflight.record('zhihu', {'login_wall': False})
        assert cookie_preflight.cached('zhihu')['state'] == cookie_preflight.VALID

        class _Crawler:
            risk_blocked = False

            def diagnose(self, url=''):
                return {'url': 'https://www.zhihu.com/', 'login_wall': True}

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Crawler())
        assert client.post('/api/cookies/verify', json={'platform': 'zhihu'}).status_code == 202
        deadline = threading.Event()
        for _ in range(120):
            if client.get('/api/cookies/generate/status').get_json()['phase'] == 'verified':
                break
            deadline.wait(0.05)
        assert cookie_preflight.cached('zhihu')['state'] == cookie_preflight.EXPIRED

    def test_a_verification_of_some_other_page_does_not_vouch_for_the_platform(self, client, app_module, monkeypatch):
        """The gate probes the platform's own address. A manual check that was aimed
        at a pasted article link measured a different page, so it may not become the
        answer to a question nobody asked about that page."""
        app_module.cookie_manager.save('zhihu', [{'name': 'z_c0', 'value': 'x'}])
        monkeypatch.setattr('app.cookie_hosts', lambda platform: ('www.zhihu.com',))

        class _Crawler:
            risk_blocked = False

            def diagnose(self, url=''):
                return {'url': url, 'login_wall': False}

            def close(self):
                pass

        monkeypatch.setattr(app_module, 'get_crawler', lambda *a, **k: _Crawler())
        article = 'https://www.zhihu.com/question/1/answer/2'
        assert client.post('/api/cookies/verify', json={'platform': 'zhihu', 'url': article}).status_code == 202
        for _ in range(120):
            if client.get('/api/cookies/generate/status').get_json()['phase'] == 'verified':
                break
            threading.Event().wait(0.05)
        assert cookie_preflight.cached('zhihu') is None


class TestParallelAndDeadline:
    def test_two_platforms_are_probed_at_the_same_time(self, monkeypatch, with_cookie):
        """Serial probes would make the wait the sum of every platform's page load —
        the opposite of what a pre-check is for."""
        with_cookie('zhihu')
        with_cookie('weibo')
        barrier = threading.Barrier(2)
        seen = []

        def fake_probe(platform, *, use_profile=None):
            seen.append(platform)
            try:
                barrier.wait(timeout=3)
                return {'login_wall': False, 'risk_blocked': False}
            except threading.BrokenBarrierError:
                return {'error': 'serialized'}

        monkeypatch.setattr(cookie_preflight, '_probe_live', fake_probe)
        monkeypatch.setattr(Config, 'COOKIE_PREFLIGHT_MAX_PARALLEL', 2)
        answers = cookie_preflight.check(['zhihu', 'weibo'])
        assert [answers[p]['state'] for p in ('zhihu', 'weibo')] == ['valid', 'valid'], seen

    def test_the_cap_is_honoured_when_there_is_more_than_one_platform(self, monkeypatch, with_cookie):
        """The cap exists because each probe is a Chrome on the user's desktop, so it
        has to be a real ceiling and not a suggestion."""
        with_cookie('zhihu')
        with_cookie('weibo')
        barrier = threading.Barrier(2)

        def fake_probe(platform, *, use_profile=None):
            try:
                barrier.wait(timeout=0.4)
                return {'login_wall': False, 'risk_blocked': False}
            except threading.BrokenBarrierError:
                return {'error': 'never overlapped'}

        monkeypatch.setattr(cookie_preflight, '_probe_live', fake_probe)
        monkeypatch.setattr(Config, 'COOKIE_PREFLIGHT_MAX_PARALLEL', 1)
        answers = cookie_preflight.check(['zhihu', 'weibo'])
        assert {answers[p]['state'] for p in ('zhihu', 'weibo')} == {cookie_preflight.UNKNOWN}

    def test_a_probe_that_outruns_the_deadline_is_still_answered(self, monkeypatch, with_cookie):
        """The key must be present or the browser reads 「no answer」 as 「no opinion
        needed」; and the platform must not be able to hold the press of 执行 open."""
        with_cookie('zhihu')
        hold = threading.Event()

        def fake_probe(platform, *, use_profile=None):
            hold.wait(10)
            return {'login_wall': True, 'risk_blocked': False}

        monkeypatch.setattr(cookie_preflight, '_probe_live', fake_probe)
        monkeypatch.setattr(Config, 'COOKIE_PREFLIGHT_TIMEOUT', 0.3)
        try:
            answers = cookie_preflight.check(['zhihu'])
        finally:
            hold.set()
        verdict = answers['zhihu']
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert verdict['blocking'] is False
        assert verdict['detail'], 'a probe that ran out of budget has to say so, not answer in silence'

    def test_an_empty_canvas_asks_nothing(self, probes):
        assert cookie_preflight.check([]) == {}
        assert probes.calls == []

    def test_a_platform_listed_twice_is_probed_once(self, probes, with_cookie):
        """Two workflows of one platform on a parallel canvas is the common case; the
        gate is asked per canvas, not per node."""
        with_cookie('zhihu')
        cookie_preflight.check(['zhihu', 'zhihu'])
        assert probes.platforms == ['zhihu']


class TestRoute:
    def test_one_request_answers_the_whole_canvas(self, client, probes, with_cookie):
        with_cookie('zhihu')
        probes.by_platform['zhihu'] = {'login_wall': True, 'risk_blocked': False}
        body = client.post('/api/cookies/preflight', json={'platforms': ['zhihu', 'wechat']}).get_json()
        assert body['ok'] is True
        assert body['blocked'] == ['zhihu']
        assert set(body['results']) == {'zhihu', 'wechat'}
        assert body['results']['zhihu']['text'], 'the sentence is rendered server-side, not keyed'
        assert body['probed'] is True

    def test_a_name_nothing_here_knows_is_refused_rather_than_dropped(self, client, probes):
        """Filtering it out quietly would answer "checked, nothing blocked" for the
        one platform nobody was able to check."""
        body = client.post('/api/cookies/preflight', json={'platforms': ['zhihu', 'evil/../x']})
        assert body.status_code == 400
        assert 'evil' in body.get_json()['error']
        assert probes.calls == []

    def test_a_wechat_canvas_passes_the_name_gate_it_would_otherwise_be_refused_by(self, client, probes):
        """WeChat holds no cookie and is not in the cookie registry, but it is a real
        crawl. Refusing its name would make a WeChat-only canvas unrunnable."""
        body = client.post('/api/cookies/preflight', json={'platforms': ['wechat']})
        assert body.status_code == 200
        assert body.get_json()['blocked'] == []

    @pytest.mark.parametrize(
        ('platforms', 'expected'),
        [
            ('zhihu', ['zhihu']),  # a bare string is one platform, not five characters
            (5, 'refused'),
            ({'a': 1}, 'refused'),
            (None, []),
        ],
    )
    def test_the_platforms_field_has_exactly_one_shape(self, client, probes, platforms, expected, with_cookie):
        if expected:
            with_cookie('zhihu')  # without a session there is nothing to probe, and no call to see
        body = client.post('/api/cookies/preflight', json={'platforms': platforms})
        if expected == 'refused':
            assert body.status_code == 400
            return
        assert body.status_code == 200
        assert [call['platform'] for call in probes.calls] == expected

    def test_the_answer_arrives_in_the_language_that_was_asked_for(self, client, probes, with_cookie):
        with_cookie('weibo')
        probes.answer = {'login_wall': True, 'risk_blocked': False}
        english = client.post('/api/cookies/preflight', json={'platforms': ['weibo']}, headers={'X-Lang': 'en'})
        chinese = client.post('/api/cookies/preflight', json={'platforms': ['weibo']}, headers={'X-Lang': 'zh'})

        def text_of(response):
            return response.get_json()['results']['weibo']['text']

        assert i18n._EN['cookie.pre.expired'].replace('{platform}', i18n.platform_label('weibo', 'en')) in text_of(
            english
        )
        assert i18n._ZH['cookie.pre.expired'].replace('{platform}', i18n.platform_label('weibo', 'zh')) in text_of(
            chinese
        )
        # The sentence is asked for in a language and must come back in that one — a raw
        # `weibo` inside it would be neither.
        assert 'weibo' not in text_of(english) and 'weibo' not in text_of(chinese)

    def test_the_probe_is_built_with_the_answer_this_run_gave_about_profiles(self, client, probes, with_cookie):
        """The gate has to test the browser the run will use. A canvas whose user
        chose 本次不用 Profile plants from the cookie file, and that is a different
        session from the profile's own."""
        with_cookie('zhihu')
        client.post('/api/cookies/preflight', json={'platforms': ['zhihu'], 'use_profile': False})
        assert probes.calls == [{'platform': 'zhihu', 'use_profile': False}]

    def test_a_missing_use_profile_stays_a_missing_answer(self, client, probes, with_cookie):
        with_cookie('zhihu')
        client.post('/api/cookies/preflight', json={'platforms': ['zhihu']})
        assert probes.calls[0]['use_profile'] is None, 'coercing absence to False overrides a setting'

    def test_a_string_false_is_still_a_no(self, client, probes, with_cookie):
        with_cookie('zhihu')
        client.post('/api/cookies/preflight', json={'platforms': ['zhihu'], 'use_profile': 'false'})
        assert probes.calls[0]['use_profile'] is False

    def test_a_cached_round_reports_that_it_probed_nothing(self, client, probes, with_cookie):
        with_cookie('bilibili')
        client.post('/api/cookies/preflight', json={'platforms': ['bilibili']})
        second = client.post('/api/cookies/preflight', json={'platforms': ['bilibili']}).get_json()
        assert second['probed'] is False
        assert probes.platforms == ['bilibili']

    def test_unclear_platforms_are_listed_apart_from_blocked_ones(self, client, probes, with_cookie):
        """Two different next steps, so two different lists: one is 「go log in」, the
        other is nothing at all."""
        with_cookie('zhihu')
        with_cookie('weibo')
        probes.by_platform['zhihu'] = {'error': 'no browser'}
        probes.by_platform['weibo'] = {'login_wall': True, 'risk_blocked': False}
        body = client.post('/api/cookies/preflight', json={'platforms': ['zhihu', 'weibo']}).get_json()
        assert body['blocked'] == ['weibo']
        assert body['unclear'] == ['zhihu']


class TestProbeBuysTheRightBrowser:
    """These run the REAL ``_probe_live``: the decisions above are only worth
    anything if the page load behind them is the one the run would have done."""

    class _FakeCrawler:
        def __init__(self, kwargs, raise_on_diagnose=False):
            self.kwargs = kwargs
            self.closed = False
            self.login_wall = False
            self.risk_blocked = False
            self._raise = raise_on_diagnose

        def diagnose(self, url=''):
            if self._raise:
                raise RuntimeError('page never arrived')
            return {'url': url or 'https://www.zhihu.com/', 'login_wall': self.login_wall}

        def close(self):
            self.closed = True

    @pytest.fixture
    def made(self, monkeypatch):
        """Swap ``crawlers.get_crawler`` — imported inside the function, so a patch on
        the module attribute is what that lookup actually reaches."""
        built = []

        def factory(platform, **kwargs):
            built.append(TestProbeBuysTheRightBrowser._FakeCrawler(kwargs))
            return built[-1]

        monkeypatch.setattr('crawlers.get_crawler', factory)
        return built

    def test_the_probe_is_a_visible_window_like_the_manual_check(self, made, with_cookie):
        """Measured once already, in the panel's 验证 Cookie: this machine answers a
        headless content page differently, and a probe that blamed the cookie for that
        would send the user to re-log in a session that is fine. Keeping both probes in
        the same mode is also what stops them disagreeing about one platform."""
        with_cookie('zhihu')
        cookie_preflight.probe('zhihu')
        assert made[0].kwargs['headless'] is False
        assert made[0].kwargs['for_login'] is True

    def test_the_probe_reads_cookies_from_the_configured_store(self, made, with_cookie):
        with_cookie('zhihu')
        cookie_preflight.probe('zhihu')
        assert made[0].kwargs['cookie_dir'] == Config.COOKIE_DIR

    def test_the_per_run_profile_answer_reaches_the_browser(self, made, with_cookie):
        with_cookie('zhihu')
        cookie_preflight.probe('zhihu', use_profile=False)
        assert made[0].kwargs['use_profile'] is False

    def test_the_browser_is_closed_even_when_the_page_raises(self, made, monkeypatch, with_cookie):
        """A probe that leaked a Chrome would leave a window on the user's desktop
        *and* keep holding that platform's profile, so the run behind it would wait on
        a browser nobody owns."""
        with_cookie('zhihu')

        def explode(platform, **kwargs):
            crawler = TestProbeBuysTheRightBrowser._FakeCrawler(kwargs, raise_on_diagnose=True)
            made.append(crawler)
            return crawler

        monkeypatch.setattr('crawlers.get_crawler', explode)
        verdict = cookie_preflight.probe('zhihu')
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert 'page never arrived' in verdict['detail']
        assert made[0].closed is True

    def test_a_browser_that_cannot_start_is_no_opinion(self, monkeypatch, with_cookie):
        with_cookie('zhihu')

        def refuse(*_args, **_kwargs):
            raise ValueError('chromedriver missing')

        monkeypatch.setattr('crawlers.get_crawler', refuse)
        verdict = cookie_preflight.probe('zhihu')
        assert verdict['state'] == cookie_preflight.UNKNOWN
        assert 'chromedriver missing' in verdict['detail']

    def test_a_probe_never_writes_the_browsers_session_back_to_the_cookie_file(self, made, monkeypatch, with_cookie):
        """The red line this feature has to stay on the right side of: the probe opens
        a real page, and a check that saved whatever the site issued while it looked
        would overwrite the user's snapshot with a half-session."""
        from services.cookie_manager import CookieManager

        with_cookie('zhihu')

        def forbid(*_args, **_kwargs):
            raise AssertionError('a cookie probe must not save anything')

        monkeypatch.setattr(CookieManager, 'save', forbid)
        assert cookie_preflight.probe('zhihu')['state'] == cookie_preflight.VALID
