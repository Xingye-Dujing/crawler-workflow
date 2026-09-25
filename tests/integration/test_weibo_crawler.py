"""Weibo redirect-facade tests on a fake driver — no browser needed.

s.weibo.com answers a fresh search with a passport QR frame and only a moment
later bounces the (already logged-in) session back to the feed. The crawler
must wait for that bounce instead of reading the intermediate URL as a login
wall — the exact bug that made valid cookies "expire". These tests pin the
settle behavior of ``WeiboCrawler._await_search_page``.
"""

import json
import re

import pytest
from selenium.common.exceptions import NoSuchElementException

import crawlers.weibo as weibo_module
from crawlers.base import Crawler
from crawlers.weibo import WeiboCrawler

pytestmark = pytest.mark.unit

PASSPORT = 'https://passport.weibo.com/sso/signin?entry=miniblog&source=s.weibo.com'
FEED = 'https://s.weibo.com/weibo?q=%E4%B8%89%E4%BA%9A&typeall=1&suball=1&Refer=g'


class FakeEl:
    def __init__(self, text=''):
        self.text = text

    def get_attribute(self, name):
        return ''


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
        self, final_url=PASSPORT, cards=True, no_result=False, appear_after=0, total_pages=50, wall_from_get=None
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
            if not self._cards:
                raise NoSuchElementException(selector)
            return FakeEl(f'共{self._total_pages}页/{self._total_pages * 10}条')
        if selector in ('body', 'html'):
            # A real page's body reflects where it actually is: the QR screen
            # only shows while the browser is parked on passport.
            if 'passport' in self.current_url:
                return FakeEl('扫描二维码登录 手机号登录')
            return FakeEl('微博搜索 结果列表')
        raise NoSuchElementException(selector)

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    """WeiboCrawler whose _create_driver installs a FakeWeiboDriver and whose
    poll sleeps are instant. Returns (crawler, driver)."""
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
                return [item]

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

    def test_a_wall_met_while_paging_keeps_the_rows_and_stops_the_walk(self, make_walker):
        # The parallel-session refusal: pages 2 answers, page 3 parks on passport.
        crawler, driver = make_walker(WeiboCrawler.DEFAULT_TARGET, total_pages=50, wall_from_get=3)
        scraped = crawler._scrape_single_search(FEED, WeiboCrawler.DEFAULT_TARGET)
        assert crawler.login_wall is True
        assert len(scraped) == 2, 'the rows paid for before the wall must still be handed back'
        assert self._paged_urls(driver) == [f'{FEED}&page={n}' for n in (2, 3)], (
            'the walk may pay for the request that discovers the wall, never one past it'
        )


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
