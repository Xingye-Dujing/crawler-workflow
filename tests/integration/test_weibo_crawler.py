"""Weibo redirect-facade tests on a fake driver — no browser needed.

s.weibo.com answers a fresh search with a passport QR frame and only a moment
later bounces the (already logged-in) session back to the feed. The crawler
must wait for that bounce instead of reading the intermediate URL as a login
wall — the exact bug that made valid cookies "expire". These tests pin the
settle behavior of ``WeiboCrawler._await_search_page``.
"""

import json
import re
from urllib.parse import quote

import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.base as base_module
import crawlers.weibo as weibo_module
from crawlers.base import Crawler, CrawlerStopped
from crawlers.weibo import WeiboCrawler

pytestmark = pytest.mark.unit

PASSPORT = 'https://passport.weibo.com/sso/signin?entry=miniblog&source=s.weibo.com'
FEED = 'https://s.weibo.com/weibo?q=%E4%B8%89%E4%BA%9A&typeall=1&suball=1&Refer=g'


class FakeEl:
    def __init__(self, text=''):
        self.text = text

    def get_attribute(self, name):
        return ''


class FakeLink:
    """A pager anchor: ``_get_total_pages`` reads only its ``href``."""

    def __init__(self, href):
        self._href = href

    def get_attribute(self, name):
        return self._href if name == 'href' else ''


class FakeWeiboDriver:
    """One search page with a switchable final state.

    ``cards``/``no_result`` model what the DOM holds once the redirect settles;
    ``appear_after`` delays the first card sighting by N probes, which is how
    the QR→feed bounce looks from inside the poll loop. ``current_url`` starts
    at whatever the last ``get`` was handed, mirroring the real driver.
    ``total_pages`` feeds the pager text the crawl reads its depth from, and
    ``wall_from_get`` parks the browser on passport from that navigation on —
    the deep-page refusal a parallel crawl meets.
    """

    def __init__(
        self,
        final_url=PASSPORT,
        cards=True,
        no_result=False,
        appear_after=0,
        total_pages=50,
        wall_from_get=None,
        page_info=True,
        page_links=(),
    ):
        self.current_url = final_url
        self._cards = cards
        self._no_result = no_result
        self._appear_after = appear_after
        self._card_probes = 0
        self._total_pages = total_pages
        self._wall_from_get = wall_from_get
        self._gets = 0
        self.visited = []
        # Measured 2026-09-28: inside a ``timescope`` window the site prints no 「共N页」 plate
        # (``page_info='empty'``) while its pager links are still there (``page_links``) — the shape
        # ``_get_total_pages``' href fallback exists for, and the shape ``_may_page`` used to refuse
        # to consult at all.
        self._page_info = page_info
        self._page_links = list(page_links)

    def get(self, url):
        self._gets += 1
        self.visited.append(url)
        self.current_url = url
        self._card_probes = 0
        if self._wall_from_get is not None and self._gets >= self._wall_from_get:
            # From here on the site answers passport with no feed, however often
            # this browser asks — the session, not the window, got flagged.
            self._cards = False
            self.current_url = PASSPORT

    def find_element(self, by, selector):
        if selector == '.card-wrap':
            if not self._cards:
                raise NoSuchElementException(selector)
            self._card_probes += 1
            if self._card_probes <= self._appear_after:
                # The QR frame is still on screen; the feed has not bounced back yet.
                self.current_url = PASSPORT
                raise NoSuchElementException(selector)
            self.current_url = FEED
            return FakeEl()
        if selector == '.card-no-result':
            if self._no_result:
                return FakeEl()
            raise NoSuchElementException(selector)
        if selector == '.page-info':
            if not self._cards or self._page_info == 'absent':
                raise NoSuchElementException(selector)
            if self._page_info == 'empty':
                # The measured timescope shape: the node IS on the page and its text carries no 「共N页」
                # (scratchpad/weibo_structure.json → window.pageInfo=""), which is a different branch of
                # ``_get_total_pages`` than "no node at all" — model the wrong one and a regression back
                # to "one page" would still read green.
                return FakeEl('')
            return FakeEl(f'共{self._total_pages}页/{self._total_pages * 10}条')
        if selector in ('body', 'html'):
            # A real page's body reflects where it actually is: the QR screen
            # only shows while the browser is parked on passport.
            if 'passport' in self.current_url:
                return FakeEl('扫描二维码登录 手机号登录')
            return FakeEl('微博搜索 结果列表')
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        if selector in ('ul.page-list li a, .m-page2 a', 'ul.page-list li a'):
            return [FakeLink(h) for h in self._page_links]
        if selector == WeiboCrawler.CARD_SELECTOR:
            return [FakeEl() for _ in range(1)] if self._cards else []
        return []

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    """WeiboCrawler whose _create_driver installs a FakeWeiboDriver and whose
    poll sleeps are instant. Returns (crawler, driver).

    The sleep is patched on :mod:`crawlers.base`, not on the platform module: the wait for a page's
    first content is the *shared* one now (``wait_for_first_content``), and a platform-local patch left
    the real helper ticking once a second through its whole budget — a "unit" test that quietly took
    minutes and proved nothing about the timing.
    """
    # Two modules hold a wait sleep now: the platform's own poll (weibo's redirect facade cannot
    # use the shared helper — see ``WeiboCrawler._await_search_page``) and the shared helpers in
    # ``crawlers.base``. Patching only one leaves a "unit" test sleeping in real time.
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)
    monkeypatch.setattr(weibo_module.time, 'sleep', lambda s: None)

    def _make(**driver_kwargs):
        driver = FakeWeiboDriver(**driver_kwargs)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return WeiboCrawler(headless=True), driver

    return _make


class TestAwaitSearchPage:
    def test_qr_redirect_with_url_still_on_passport_is_not_a_wall(self, make_crawler):
        # The facade in its purest form: the URL says passport, but the feed
        # DOM is already rendered. The old code read the URL first and died.
        crawler, driver = make_crawler(final_url=PASSPORT, cards=True)
        assert crawler._await_search_page(PASSPORT) is True
        assert crawler.login_wall is False

    def test_bounce_that_takes_a_few_probes_is_awaited(self, make_crawler):
        crawler, _ = make_crawler(final_url=PASSPORT, cards=True, appear_after=3)
        assert crawler._await_search_page(PASSPORT) is True
        assert crawler.login_wall is False

    def test_persistent_passport_page_without_cards_sets_the_wall(self, make_crawler):
        crawler, _ = make_crawler(final_url=PASSPORT, cards=False)
        assert crawler._await_search_page(PASSPORT) is False
        assert crawler.login_wall is True

    def test_no_result_plate_is_an_empty_window_not_a_wall(self, make_crawler):
        crawler, _ = make_crawler(final_url=FEED, cards=False, no_result=True)
        assert crawler._await_search_page(FEED) is False
        assert crawler.login_wall is False

    def test_slow_page_that_never_shows_cards_is_a_timeout_not_a_wall(self, make_crawler):
        crawler, _ = make_crawler(final_url=FEED, cards=False)
        assert crawler._await_search_page(FEED) is False
        assert crawler.login_wall is False

    def test_navigation_happens_exactly_once_per_call(self, make_crawler):
        crawler, driver = make_crawler(final_url=FEED, cards=True)
        crawler._await_search_page(FEED)
        assert driver.visited == [FEED]

    def test_a_plate_beside_foreign_cards_is_still_an_empty_window(self, make_crawler):
        """The window says 未找到结果 and the SAME page shows five other people's posts.

        Measured 2026-09-28 with a keyword that exists nowhere: ``.card-no-result`` was on screen
        *together with* five ``.card-wrap`` rows carrying a ``.name`` — weibo's own recommendations,
        timestamped outside the asked hour and hung on the very same ``#pl_feedlist_index`` chain, with
        no ``mark``/``card-type`` attribute to tell them apart. The card-first order therefore filled a
        keyword's table with content that never matched the keyword, which is worse than an empty
        result: the user cannot see which rows the search did not answer for. The plate is the only
        answer, so it is read first.
        """
        crawler, _ = make_crawler(final_url=FEED, cards=True, no_result=True)
        assert crawler._await_search_page(FEED) is False
        assert crawler.login_wall is False, 'an empty window is a result, not a refusal'

    def test_the_walk_navigates_through_open_not_past_it(self, make_crawler):
        """A bare ``driver.get`` here would be the platform's one navigation outside ``Crawler.open``.

        The reason this call does not simply judge the wall on arrival is ``judge=False``: weibo's
        passport frame is a stage the site walks every visitor through, and a wall latched from it is
        the bug these tests were written for. What the platform still gets from ``open`` is the dialog
        dismissal and the settled-flag.
        """
        crawler, driver = make_crawler(final_url=FEED, cards=True)
        seen = {}

        def spy(url, judge=True):
            seen['judge'] = judge
            return Crawler.open(crawler, url, judge=judge)

        monkeypatch_open = getattr(crawler, 'open', None)
        assert monkeypatch_open is not None
        crawler.open = spy
        try:
            assert crawler._await_search_page(FEED) is True
        finally:
            crawler.open = monkeypatch_open
        assert seen['judge'] is False, 'the arrival verdict is what this platform cannot afford'
        assert driver.visited == [FEED]


class TestPagingWalk:
    """How deep ``_scrape_single_search`` walks a keyword feed.

    The old crawler capped the walk at five pages however deep the pager said
    and however empty the target still was — a "共50页" feed quit at page 5 with
    no line explaining why. The walk now answers to two things only: the target
    (stop when full) and the wall (stop when refused, keeping every row).

    ``_harvest`` is replaced with one-row-per-page emissions: the card DOM is
    another test's subject, and here it is the *visited URLs* that carry the
    contract.
    """

    @pytest.fixture
    def make_walker(self, make_crawler, monkeypatch):
        def _make(target, **driver_kwargs):
            crawler, driver = make_crawler(cards=True, **driver_kwargs)
            monkeypatch.setattr(Crawler, '_polite_pause', staticmethod(lambda *a: None))
            page_counter = {'n': 0}

            def harvest(_target):
                page_counter['n'] += 1
                item = {'正文': f'p{page_counter["n"]}'}
                crawler.emit(item)
                # ``(rows, cards)`` — the pair the page loop stops on. One card per page here, always
                # fresh, so these tests stay about the URLs visited.
                return [item], 1

            monkeypatch.setattr(crawler, '_harvest', harvest)
            return crawler, driver

        return _make

    @staticmethod
    def _paged_urls(driver):
        return [u for u in driver.visited if 'page=' in u]

    def test_a_deep_pager_is_walked_to_its_own_end_not_to_a_hard_cap(self, make_walker):
        crawler, driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=50)
        crawler._scrape_single_search(FEED, WeiboCrawler.DEFAULT_TARGET)
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in range(2, 51)]
        assert crawler.collected() == 50

    def test_the_walk_stops_the_moment_the_target_is_full(self, make_walker):
        crawler, driver = make_walker(4, total_pages=50)
        crawler._scrape_single_search(FEED, 4)
        assert crawler.collected() == 4
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in (2, 3, 4)]

    def test_a_time_window_is_paged_like_any_other_window(self, make_walker):
        """An hour is not "everything it holds is on page 1" — the site disagrees.

        Measured 2026-09-28 on one hourly ``timescope`` URL: page 1 rendered 9 cards, page 2 rendered
        6 more with **no mid in common**, and the only reason the old code never asked was
        ``_may_page``'s assumption. Such a window prints no 「共N页」 text either, so the depth has to
        come from the pager anchors — which is what ``page_info='empty'`` plus ``page_links`` models.
        """
        window = FEED.replace('Refer=g', 'timescope=custom%3A2026-09-26-20%3A2026-09-26-21&Refer=g')
        links = [f'{window}&page={n}' for n in range(1, 4)]
        crawler, driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=1, page_info='empty', page_links=links)
        scraped = crawler._scrape_single_search(window, WeiboCrawler.DEFAULT_TARGET)
        assert self._paged_urls(driver) == [f'{window}&page={n}' for n in (2, 3)], driver.visited
        assert len(scraped) == 3, 'page 1 plus the two deeper ones'

    def test_a_page_with_nothing_new_on_it_is_not_a_page_with_nothing_on_it(self, make_crawler, monkeypatch, caplog):
        """U36 — the 继续 shape, and the second silent under-collection this walk had.

        A resume re-enters the hourly window 停止 died in, and every card on the pages *before* the kill is
        already in the ledger. The loop broke the moment ``collected()`` stood still, so the pages deeper
        than the kill — the only ones still owing rows — were never fetched, and the console printed
        「某一页是空的」 about a page that was full. Stopping on the *site's* emptiness (no cards rendered)
        is the discriminator; nothing-new is a fact about this run's ledger, never about the window.

        The cost is stated rather than hidden: a pager whose every page repeats the previous one is now
        walked to ``total_pages`` (measured 1..10 anchors on a window) instead of quitting at the first
        repeat. That is a bounded number of navigations, and the alternative is a short table nobody named.
        """
        import i18n

        crawler, driver = make_crawler(cards=True, total_pages=5)
        monkeypatch.setattr(Crawler, '_polite_pause', staticmethod(lambda *a: None))
        pages = {'n': 0}

        def harvest(_target):
            pages['n'] += 1
            if pages['n'] <= 3:
                # Pages 1-3: paid for before the kill, so the ledger refuses every row on them.
                return [], 1
            item = {'正文': f'p{pages["n"]}'}
            crawler.emit(item)
            return [item], 1

        monkeypatch.setattr(crawler, '_harvest', harvest)
        with caplog.at_level('INFO'):
            scraped = crawler._scrape_single_search(FEED, WeiboCrawler.DEFAULT_TARGET)
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in range(2, 6)], driver.visited
        assert len(scraped) == 2, f'the rows past the kill are the ones the resume exists to fetch: {scraped}'
        said = [record.getMessage() for record in caplog.records]
        assert i18n.t('crawl.weibo.page_empty', i=2) not in said, (
            f'a page full of already-known cards was reported as an empty one: {said[-6:]}'
        )

    def test_the_walk_closes_with_rows_target_and_reason(self, make_walker, caplog):
        """U10: the search walk used to end mid-sentence, on every platform's worst console.

        ``author()`` has always closed with ``rows / target / reason``; ``search()`` printed a line per
        window and returned, so a date-range crawl that stopped at window 12 of 6432 — wall, target, or
        the end of the list, the user cannot tell which — left the console holding only 「第 12/6432
        个链接完成」. The closing line is what makes 「采满了」 and 「没采满」 different sentences.
        """
        import i18n

        crawler, _driver = make_walker(2, total_pages=50)
        with caplog.at_level('INFO'):
            crawler.search(keyword='三亚', target_count=2)
        said = [record.getMessage() for record in caplog.records]
        assert (
            i18n.t('crawl.weibo.walk_done', n=2, walked=1, total=1, target=2, reason=i18n.stop_reason_label('target'))
            in said
        ), said

    def test_a_window_met_by_a_wall_reports_the_wall_as_the_reason(self, make_walker, caplog):
        """The reason slot must name the refusal, not leave 「target」 to be inferred from a short table."""
        import i18n

        crawler, _driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=50, wall_from_get=2)
        with caplog.at_level('INFO'):
            crawler.search(keyword='三亚', target_count=0)
        said = [record.getMessage() for record in caplog.records]
        assert (
            i18n.t('crawl.weibo.walk_done', n=1, walked=1, total=1, target='∞', reason=i18n.stop_reason_label('wall'))
            in said
        ), said

    def test_a_wall_met_while_paging_keeps_the_rows_and_stops_the_walk(self, make_walker):
        # The parallel-session refusal: pages 2 answers, page 3 parks on passport.
        crawler, driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=50, wall_from_get=3)
        scraped = crawler._scrape_single_search(FEED, WeiboCrawler.DEFAULT_TARGET)
        assert crawler.login_wall is True
        assert len(scraped) == 2, 'the rows paid for before the wall must still be handed back'
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in (2, 3)], (
            'the walk may pay for the request that discovers the wall, never one past it'
        )

    def test_a_page_that_shows_neither_is_reported_as_that_and_not_as_emptiness(self, make_crawler, caplog):
        """The line may only say what the code saw (U11's second half).

        The old wording was 「页面加载超时，可能无内容」 — a guess about the window's content, printed by
        code that cannot see the window at all: it saw a load that produced no cards and no plate. On a
        slow network that sentence tells the user the hour was empty, which is the one thing they cannot
        un-see in the table. The replacement carries the seconds actually waited and whether the
        navigation settled, because both are facts.
        """
        import i18n

        crawler, _driver = make_crawler(final_url=FEED, cards=False)
        with caplog.at_level('WARNING'):
            assert crawler._await_search_page(FEED) is False
        said = [record.getMessage() for record in caplog.records]
        assert not [line for line in said if '无内容' in line], said
        assert any(line.startswith('    等了') or 'Waited' in line for line in said), said
        assert i18n.t('crawl.weibo.navSettled') in ''.join(said), said

    def test_an_unsettled_load_says_so_instead_of_blaming_the_site(self, make_crawler, caplog, monkeypatch):
        """The other half of the same sentence: a load that never finished is a slow network."""
        import i18n

        crawler, _driver = make_crawler(final_url=FEED, cards=False)
        monkeypatch.setattr(crawler, 'open', lambda url, judge=True: False)
        with caplog.at_level('WARNING'):
            assert crawler._await_search_page(FEED) is False
        said = ''.join(record.getMessage() for record in caplog.records)
        assert i18n.t('crawl.weibo.navUnsettled') in said, said

    def test_the_wait_is_patient_and_hears_stop_every_tick(self, make_crawler, monkeypatch):
        """The budget is the shared one, and 停止 is heard inside the wait.

        A platform-local timeout is how a crawl ends up blaming a site for its own machine
        (``PAGE_WAIT * 3`` was nine seconds on a surface measured delivering in under a second and a
        half), and a wait that ignores 停止 is the longest thing in the program — the user's only exit
        would have to wait for it.
        """
        from config import Config

        crawler, _driver = make_crawler(final_url=FEED, cards=False)
        ticks = []

        def _counting_stop():
            ticks.append(1)
            return len(ticks) > 40

        monkeypatch.setattr(crawler, 'may_stop', _counting_stop)
        with pytest.raises(CrawlerStopped):
            crawler._await_search_page(FEED)
        assert 40 < len(ticks) < int(Config.PAGE_WAIT_TIMEOUT), (
            f'the wait ran {len(ticks)} ticks against a budget of {Config.PAGE_WAIT_TIMEOUT}s'
        )

    def test_a_parked_browser_is_not_charged_a_whole_budget_per_window(self, make_crawler, monkeypatch):
        """The shared breaker, taken on directly because this wait cannot be the shared helper.

        Two pages that delivered nothing and this crawler stops spending
        :attr:`~crawlers.base.Crawler.MAX_PENDING_WAITS` budgets on further windows: a date range is
        thousands of windows wide, and "the network is down" must cost two waits, not two hours.
        """
        crawler, _driver = make_crawler(final_url=FEED, cards=False)
        crawler.pending_waits = Crawler.MAX_PENDING_WAITS
        monkeypatch.setattr(crawler, 'may_stop', lambda: False)
        assert crawler._await_search_page(FEED) is False
        assert crawler.pending_waits == Crawler.MAX_PENDING_WAITS, 'it still waited and charged another'


class TestTheWindowWalkStopsOnAnyRefusal:
    """A refusal of any kind ends a walk over windows, and the closing line says which kind.

    The loop used to break on ``login_wall`` alone. Risk control and a browser that fetched nothing at
    all set *other* flags — so a session answered 风控 at window 13 of 6432 kept navigating windows, and
    the summary called that 「已到列表末尾」. Three different answers, three different reasons, and the
    user reads which one happened.
    """

    @pytest.fixture
    def make_walk(self, make_crawler, monkeypatch):
        def _make(flag, urls=3):
            crawler, driver = make_crawler(cards=True)
            monkeypatch.setattr(Crawler, '_polite_pause', staticmethod(lambda *a: None))
            crawler._build_urls = lambda keyword, start, end: [f'{FEED}&w={i}' for i in range(urls)]
            asked = []

            def _window(base_url, _target):
                asked.append(base_url)
                setattr(crawler, flag, True)
                return []

            monkeypatch.setattr(crawler, '_scrape_single_search', _window)
            return crawler, asked

        return _make

    @pytest.mark.parametrize('flag,token', [('risk_blocked', 'risk'), ('unreachable', 'unreachable')])
    def test_a_refusal_that_is_not_a_login_wall_stops_the_walk(self, make_walk, caplog, flag, token):
        import i18n

        crawler, asked = make_walk(flag)
        with caplog.at_level('INFO'):
            crawler.search(keyword='三亚', target_count=0)
        assert len(asked) == 1, f'{flag} did not stop the walk: {asked}'
        said = ''.join(record.getMessage() for record in caplog.records)
        assert i18n.stop_reason_label(token) in said, said

    def test_a_kill_inside_a_window_leaves_the_cursor_on_the_previous_one(self, make_crawler, monkeypatch):
        """A window is behind the cursor only once it has been walked (M4).

        Marking it done before entering was harmless when a window was one page; now that a window is up
        to ten pages deep, a 停止 or a cookie death mid-window would have 继续 skip the pages it had not
        reached and the summary would still say the list ended. Re-entering costs requests, never rows —
        the ledger de-dupes by 微博ID.
        """
        crawler, _driver = make_crawler(cards=True)
        monkeypatch.setattr(Crawler, '_polite_pause', staticmethod(lambda *a: None))
        crawler._build_urls = lambda keyword, start, end: [f'{FEED}&w=1', f'{FEED}&w=2']
        asked = []

        def _window(url, _target):
            asked.append(url)
            if len(asked) > 1:
                # 停止 lands during the SECOND window's page walk; the first one is finished and paid for.
                raise CrawlerStopped('stopped')
            item = {'正文': url}
            crawler.emit(item)
            return [item]

        crawler._scrape_single_search = _window
        with pytest.raises(CrawlerStopped):
            crawler.search(keyword='三亚', target_count=50)
        assert asked == [f'{FEED}&w=1', f'{FEED}&w=2']
        assert crawler.position.get('url_index') == 1, f'the interrupted window was marked done: {crawler.position}'


# ─── the author walk: mymblog read from inside the profile page ───────────────


def _mymblog_item(mid, uid, screen='QPikapikaQ', long=False, topics=None, retweet_of=None):
    """One item shaped like the measured payload (docs 2026-09-25)."""
    row = {
        'id': int(mid),
        'idstr': str(mid),
        'mid': str(mid),
        'mblogid': f'Ri{mid}',
        'created_at': 'Thu Sep 24 15:42:51 +0800 2026',
        'source': 'iPhone客户端',
        'text': ('x' * 400) if long else f'<a href="#">html</a>{mid}',
        'text_raw': ('很长的全文' + str(mid)) if long else f'正文{mid}',
        'isLongText': long,
        'reposts_count': 1,
        'comments_count': 2,
        'attitudes_count': 3,
        'pic_num': 2,
        'pic_ids': ['a', 'b'],
        'user': {'id': int(uid), 'idstr': str(uid), 'screen_name': screen},
        'visible': {'type': 0},
    }
    if topics:
        row['topic_struct'] = [{'title': '', 'topic_url': t} for t in topics]
    if retweet_of:
        row['retweeted_status'] = {'user': {'screen_name': retweet_of}}
    return row


class FakeMymblogDriver:
    """Answers the profile navigation and the in-page mymblog bridge.

    ``pages`` maps page-number → items (or ``'refuse'`` for the 403 edge page, or
    ``'gone'`` for a non-JSON body); a page beyond the map is an empty list, which
    is the server saying the account has nothing deeper. ``wall`` parks the browser
    on passport from the profile navigation itself — the session bounce, judged by
    ``open`` before any endpoint is asked.
    """

    def __init__(self, pages, uid='6302837173', wall=False):
        self.pages = pages
        self.uid = uid
        self.wall = wall
        self.current_url = 'about:blank'
        self.visited = []
        self.fetched = []

    def get(self, url):
        self.visited.append(url)
        if self.wall:
            self.current_url = PASSPORT
            return
        self.current_url = url

    def set_script_timeout(self, seconds):
        pass

    def execute_async_script(self, script):
        match = re.search(r'fetch\("(.*?)"', script)
        url = match.group(1) if match else ''
        self.fetched.append(url)
        page = int(re.search(r'page=(\d+)', url).group(1))
        payload = self.pages.get(page, [])
        if payload == 'refuse':
            return json.dumps({'status': 403, 'body': '<h2>403 Forbidden</h2>', 'error': ''})
        if payload == 'gone':
            return json.dumps({'status': 200, 'body': '<!doctype html>wall', 'error': ''})
        body = json.dumps({'data': {'since_id': 'x', 'list': payload}})
        return json.dumps({'status': 200, 'body': body, 'error': ''})

    def find_element(self, by, selector):
        if selector in ('body', 'html'):
            return FakeEl('登录' if self.wall else '微博 个人主页')
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def quit(self):
        pass


@pytest.fixture
def make_author(monkeypatch):
    # Two modules hold a wait sleep now: the platform's own poll (weibo's redirect facade cannot
    # use the shared helper — see ``WeiboCrawler._await_search_page``) and the shared helpers in
    # ``crawlers.base``. Patching only one leaves a "unit" test sleeping in real time.
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)
    monkeypatch.setattr(weibo_module.time, 'sleep', lambda s: None)

    def _make(pages, uid='6302837173', wall=False):
        driver = FakeMymblogDriver(pages, uid=uid, wall=wall)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        monkeypatch.setattr(Crawler, '_polite_pause', staticmethod(lambda *a: None))
        return WeiboCrawler(headless=False), driver

    return _make


class TestWeiboUid:
    @pytest.mark.parametrize(
        ('value', 'want'),
        [
            ('6302837173', '6302837173'),
            ('https://weibo.com/u/6302837173', '6302837173'),
            ('https://weibo.com/u/6302837173?tabtype=weibo', '6302837173'),
            ('https://m.weibo.cn/u/6302837173', '6302837173'),
            ('https://weibo.com/6302837173/RiQSj42In', '6302837173'),
            ('https://weibo.com/u/6302837173#feed', '6302837173'),
            ('@QPikapikaQ', ''),
            ('QPikapikaQ', ''),
            ('', ''),
            ('https://weibo.com/p/100808', ''),
            ('https://taobao.com/u/123456', ''),
        ],
    )
    def test_addresses_that_name_one_author_and_the_junk_that_does_not(self, value, want):
        from crawlers.weibo import weibo_uid

        assert weibo_uid(value) == want, value


class TestWeiboAuthorWalk:
    def test_page_one_surplus_is_kept_and_pages_advance(self, make_author):
        pages = {
            1: [_mymblog_item(str(1000 + i), '6302837173') for i in range(28)],
            2: [_mymblog_item(str(2000 + i), '6302837173') for i in range(20)],
        }
        crawler, driver = make_author(pages)
        rows = crawler.author('https://weibo.com/u/6302837173', target_count=40)
        assert len(rows) == 40, 'target cut honoured inside a page, not overshooting'
        assert [int(u.split('page=')[1].split('&')[0]) for u in driver.fetched] == [1, 2]
        assert driver.visited == ['https://weibo.com/u/6302837173'], 'exactly one navigation, through open'

    def test_the_mirror_of_the_home_timeline_is_refused_by_the_anchor(self, make_author):
        foreign = [_mymblog_item('111', '9999999999')]  # user.id != uid
        crawler, _driver = make_author({1: foreign, 2: 'gone'})
        with pytest.raises(RuntimeError) as err:
            crawler.author('6302837173', target_count=5)
        assert '6302837173' in str(err.value)
        assert crawler.login_wall is False, 'this refusal is not a login wall'

    def test_a_403_before_any_row_raises_instead_of_filing_an_empty_table(self, make_author):
        crawler, _driver = make_author({1: 'refuse'})
        with pytest.raises(ValueError) as err:
            crawler.author('6302837173', target_count=5)
        assert '403' in str(err.value)

    def test_a_403_after_rows_keeps_every_row_paid_for(self, make_author):
        pages = {1: [_mymblog_item(str(1000 + i), '6302837173') for i in range(10)], 2: 'refuse'}
        crawler, _driver = make_author(pages)
        rows = crawler.author('6302837173', target_count=50)
        assert len(rows) == 10, 'the rows collected before the throttle stay; only the walk stops'

    def test_an_account_with_nothing_to_show_is_an_empty_answer_not_a_refusal(self, make_author):
        crawler, _driver = make_author({1: []})
        assert crawler.author('6302837173', target_count=5) == []

    def test_a_walled_profile_never_asks_the_endpoint(self, make_author):
        crawler, driver = make_author({}, wall=True)
        with pytest.raises(RuntimeError):
            crawler.author('6302837173', target_count=5)
        assert crawler.login_wall is True
        assert driver.fetched == [], 'the wall is judged on arrival, before any request is spent'

    def test_the_row_uses_the_search_vocabulary_and_names_no_invented_data(self, make_author):
        item = _mymblog_item(
            '700',
            '6302837173',
            topics=['sinaweibo://searchall?containerid=231522&q=%23%E6%99%9A%E5%AE%89%23&x=y'],
        )
        crawler, _driver = make_author({1: [item]})
        rows = crawler.author('6302837173', target_count=1)
        assert len(rows) == 1
        row = rows[0]
        search_columns = {
            '发布者',
            '发布时间',
            '发布来源',
            '正文',
            '转发数',
            '评论数',
            '点赞数',
            '图片链接',
            '图片数',
            '话题',
            '视频数',
            '用户链接',
            '链接',
            '微博ID',
        }
        assert set(row) == search_columns, 'author rows speak the search mode columns'
        assert row['正文'] == '正文700', 'text_raw is the body'
        assert row['话题'] == '晚安', 'the topic name is url-encoded in topic_url, not the empty title'
        assert row['发布时间'] == '2026-09-24 15:42', 'the English stamp is normalised, not passed through'
        assert row['点赞数'] == 3 and isinstance(row['点赞数'], int), 'the JSON counters are ints already'
        assert row['图片链接'] == '', 'pic_ids are not image URLs; the column stays empty, never guessed'
        assert row['链接'] == 'https://weibo.com/detail/700'

    def test_a_resumed_walk_starts_at_the_recorded_page(self, make_author):
        pages = {2: [_mymblog_item('200', '6302837173'), _mymblog_item('201', '6302837173')]}
        crawler, driver = make_author(pages)
        crawler.seed([{'微博ID': '100', '正文': 'old'}])
        rows = crawler.author('6302837173', target_count=4, resume={'uid': '6302837173', 'page': 2})
        assert driver.fetched and 'page=2' in driver.fetched[0], 'resume continues on the stored page'
        assert '100' in {r['微博ID'] for r in rows}

    def test_the_anchor_is_the_top_level_author_not_a_retweet(self, make_author):
        item = _mymblog_item('800', '6302837173', screen='转发者', retweet_of='原作者')
        crawler, _driver = make_author({1: [item]})
        rows = crawler.author('6302837173', target_count=1)
        assert rows[0]['发布者'] == '转发者', 'the row is the reposter own post, not the source of the retweet'


class FakeBoardDriver:
    """Answers the weibo.com homepage and the in-page hotSearch bridge.

    ``payload`` is what ``ajax/side/hotSearch`` returns — the shape the site gave in
    every measured session (``ok: 1`` with ~52 rows under ``data.realtime``). The
    fetch is answered through the ``done(j)`` object bridge ``fetch_json`` uses, so
    the fake returns a dict and never sees a JSON string.
    """

    def __init__(self, payload):
        self.payload = payload
        self.current_url = 'about:blank'
        self.visited = []
        self.fetched = []

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def set_script_timeout(self, seconds):
        pass

    def execute_async_script(self, script):
        match = re.search(r'fetch\("(.*?)"', script)
        self.fetched.append(match.group(1) if match else script[:80])
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def find_element(self, by, selector):
        raise NoSuchElementException(selector)

    def find_elements(self, by, selector):
        return []

    def quit(self):
        pass


def _hot_item(word='中美元首华盛顿会晤', num='1003085', realpos='1', scheme=None):
    return {
        'word': word,
        'word_scheme': scheme if scheme is not None else f'#{word}#',
        'note': word,
        'num': num,
        'realpos': realpos,
        'rank': str(int(realpos) - 1),
        'topic_flag': '1',
        'label_name': '',
        'emoticon': '',
    }


def _board(items):
    return {'ok': 1, 'data': {'realtime': list(items)}, 'logs': [], 'topLogs': []}


@pytest.fixture
def make_board(monkeypatch):
    # Two modules hold a wait sleep now: the platform's own poll (weibo's redirect facade cannot
    # use the shared helper — see ``WeiboCrawler._await_search_page``) and the shared helpers in
    # ``crawlers.base``. Patching only one leaves a "unit" test sleeping in real time.
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)
    monkeypatch.setattr(weibo_module.time, 'sleep', lambda s: None)

    def _make(payload):
        driver = FakeBoardDriver(payload)

        def fake_create(self, *a, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return WeiboCrawler(headless=True), driver

    return _make


class TestWeiboHotBoard:
    def test_the_board_rows_carry_only_what_the_answer_really_fills(self, make_board):
        """A 热搜 row is a TOPIC. The post vocabulary (正文/发布者/发布时间) is not in the
        answer, so a row that grew those columns would be inventing them."""
        crawler, _driver = make_board(_board([_hot_item(), _hot_item(word='另一条热搜', num='12', realpos='2')]))
        rows = crawler.hot(target_count=10)
        assert [set(row) for row in rows] == [{'排名', '标题', '话题', '热度', '链接'}] * 2, rows
        assert rows[0]['排名'] == 1 and rows[0]['标题'] == '中美元首华盛顿会晤'
        assert rows[0]['热度'] == 1003085, 'the heat is an exact integer in the answer, so it must not be relabelled 万'
        assert rows[0]['链接'].startswith('https://s.weibo.com/weibo?q=')
        assert '%23' in rows[0]['链接'], 'the link is the search page for the #topic# form'

    def test_the_board_is_asked_for_exactly_once(self, make_board):
        """One answer IS the board (measured). A page loop here would re-request the same
        list until the target filled, which is both a lie about depth and weibo's wall
        risk paid for nothing."""
        crawler, driver = make_board(_board([_hot_item(word=f'话题{i}') for i in range(3)]))
        crawler.hot(target_count=200)
        assert len(driver.fetched) == 1, driver.fetched

    def test_a_refused_answer_raises_and_files_no_empty_board(self, make_board):
        import i18n

        crawler, _driver = make_board({'ok': 0, 'data': {}})
        with pytest.raises(RuntimeError) as caught:
            crawler.hot(target_count=10)
        assert str(caught.value) == i18n.t('crawl.weibo.hotRefused', answer='0')
        assert crawler.results() == [], 'a refusal must not leave a board-shaped empty table behind'

    def test_a_target_above_the_board_says_the_site_capped_it(self, make_board, caplog):
        """The number in the panel is the user's ask; the board's length is the site's
        answer. Silence here would read as "weibo had nothing else today"."""
        import i18n

        crawler, _driver = make_board(_board([_hot_item(word=f'话题{i}') for i in range(3)]))
        with caplog.at_level('INFO'):
            rows = crawler.hot(target_count=50)
        assert len(rows) == 3
        assert i18n.t('crawl.weibo.hotCapped', board=3) in [record.getMessage() for record in caplog.records]

    def test_a_row_without_a_topic_word_is_not_a_row(self, make_board):
        crawler, _driver = make_board(_board([_hot_item(word='  '), _hot_item(word='真热搜')]))
        rows = crawler.hot(target_count=10)
        assert [row['标题'] for row in rows] == ['真热搜'], rows

    def test_a_board_entry_that_is_not_a_topic_keeps_its_own_form(self, make_board):
        """Live measured: some rows carry ``word_scheme`` equal to the bare word (a
        非话题 entry). The column is the site's string, and the link has to search for
        exactly that — rewriting it into a #…# shape would ask for a topic that is
        not on the board."""
        crawler, _driver = make_board(_board([_hot_item(word='让家更有AI', scheme='让家更有AI', realpos='4')]))
        row = crawler.hot(target_count=5)[0]
        assert row['话题'] == '让家更有AI' and row['标题'] == '让家更有AI'
        assert '%23' not in row['链接'], row['链接']
        assert quote('让家更有AI') in row['链接']

    def test_the_board_never_asks_for_a_login(self, make_board):
        """Measured: hotSearch answers the same way with no cookie at all, so this mode
        must not gate on a session the site does not require."""
        crawler, driver = make_board(_board([_hot_item()]))
        rows = crawler.hot(target_count=5)
        assert len(rows) == 1
        assert crawler.login_wall is False
        assert driver.visited == ['https://weibo.com/'], 'one page load buys the document to ask from'
