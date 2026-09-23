"""Bilibili search crawl against a fake driver — the pager contract, no browser.

What this pins is the shape the live probes measured, which no reading of the
site suggests:

* page one is the bare ``all?keyword=`` URL, because ``&page=1`` renders zero
  cards and a crawler that slept on it would report an exhausted search;
* identity comes from the card link, every number from ``x/web-interface/view``,
  because the card's own DOM figure is a rounded 万-label;
* ``code=-404`` is one withdrawn video (skip it) while any other non-zero code
  is the session talking (stop, and refuse the run if nothing was collected) —
  the distinction that keeps a risk-control answer from becoming a table of
  zeros beside real titles.

The BV ids are the real ones the search page served for 人工智能, because the
id pattern is part of what the crawler matches on: ``BV1a`` looks like a
convenient fixture and is silently not a video.
"""

import re

import pytest

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.video import BilibiliCrawler, bilibili_bvid, bilibili_mid, bilibili_search_url

pytestmark = pytest.mark.unit

A = 'BV1atCRYsE7x'
B = 'BV1E7wtzaEdq'
C = 'BV19se263EZy'
D = 'BV1yVNU6xERx'
GONE = 'BV1gone9QxE7'


class El:
    def __init__(self, text=''):
        self.text = text


class FakeDriver:
    """Serves one card list per ``get()`` and one endpoint payload per fetch.

    The queues are the assertions: a crawler that fetched a card it should have
    filtered, or paged past its target, would consume a payload out of order and
    the row checks downstream would fail.
    """

    def __init__(self, pages, payloads, body=''):
        self.pages = list(pages)
        self.payloads = list(payloads)
        self.body = body
        self.visited = []
        self.fetched = []
        self.current_url = 'https://search.bilibili.com/all'
        self.wall = False
        self._page = []

    def get(self, url):
        self.visited.append(url)
        # A real wall is a redirect: the URL asked for and the one on screen
        # differ, which is what the base class detector reads.
        self.current_url = 'https://passport.bilibili.com/login?act=3' if self.wall else url
        self._page = self.pages.pop(0) if self.pages else []

    def find_element(self, by, selector):
        return El(self.body)

    def set_script_timeout(self, seconds):
        pass

    def execute_script(self, script, *args):
        if '.bili-video-card' in script:
            return list(self._page)
        if 'innerText' in script and args:
            return getattr(args[0], 'text', '')
        return None

    def execute_async_script(self, script):
        match = re.search(r'fetch\("(.*?)"', script)
        self.fetched.append(match.group(1) if match else script[:40])
        if self.payloads:
            return self.payloads.pop(0)
        return {'code': None, 'data': {}}

    def quit(self):
        pass


def _card(bvid):
    return f'https://www.bilibili.com/video/{bvid}/'


AD_CARD = 'https://cm.bilibili.com/cm/api/fees/pc/sync/v2?msg=a%7C5'
COURSE_CARD = 'https://www.bilibili.com/cheese/play/ss14173'


def _view(bvid=A, code=0, **over):
    data = {
        'aid': 113332711333508,
        'bvid': bvid,
        'title': '90分钟！清华博士带你一口气搞懂人工智能和神经网络',
        'desc': '视频使用素材来自：3blue1brown',
        'pubdate': 1729321171,
        'duration': 5338,
        'videos': 1,
        'owner': {'mid': 266765166, 'name': '漫士沉思录'},
        'ugc_season': {'title': 'AI 入门合集'},
        'stat': {
            'view': 1405449,
            'like': 85667,
            'coin': 79485,
            'favorite': 130552,
            'share': 24794,
            'danmaku': 7368,
            'reply': 2194,
        },
    }
    data.update(over)
    return {'code': code, 'message': 'OK', 'data': data}


@pytest.fixture
def make_crawler(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(pages, payloads):
        driver = FakeDriver(pages, payloads)

        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = BilibiliCrawler(headless=True)
        return crawler, driver

    return _make


class SpaceDriver(FakeDriver):
    """An UP's own page: the upload list *appends* one screen per scroll round.

    The search driver changes its screen on every ``get()``, which is the wrong
    shape here — a space is one navigation, and its pager is the scroll.
    ``scroll_down`` closes a round with ``scrollTo``, so that script (not the
    ``scrollBy`` steps inside it) is where a new screen mounts.
    """

    def __init__(self, screens, payloads):
        super().__init__([screens[0]] if screens else [], payloads)
        self.screens = [list(screen) for screen in screens]
        self.depth = 1
        self.rounds = 0

    def execute_script(self, script, *args):
        if '.bili-video-card' in script:
            return [card for screen in self.screens[: self.depth] for card in screen]
        if 'scrollTo' in script:
            self.depth += 1
            self.rounds += 1
            return None
        return super().execute_script(script, *args)


@pytest.fixture
def make_space(monkeypatch):
    """A space page whose list grows by scrolling, with the same fetch queue."""
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(screens, payloads):
        driver = SpaceDriver(screens, payloads)

        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        crawler = BilibiliCrawler(headless=True)
        return crawler, driver

    return _make


class TestAuthorMid:
    """The address of an UP is the whole feature, so it is parsed in the open."""

    def test_a_bare_mid_a_space_link_and_a_share_form_are_the_same_up(self):
        assert bilibili_mid('266765166') == '266765166'
        assert bilibili_mid('https://space.bilibili.com/266765166/upload/video') == '266765166'
        assert bilibili_mid('https://space.bilibili.com/266765166/?vd_source=9f') == '266765166'
        assert bilibili_mid('space.bilibili.com/266765166') == '266765166'
        assert bilibili_mid('https://space.bilibili.com/space.to_5112345678901234') == '5112345678901234'

    def test_something_that_is_not_an_up_is_refused_before_a_browser_exists(self, make_space):
        """A display name cannot address an UP, and opening a made-up space would
        report "this UP has posted nothing" about a page that was never theirs."""
        crawler, driver = make_space([[_card(A)]], [])
        for value in ('', '   ', '漫士沉思录', f'https://www.bilibili.com/video/{A}/'):
            with pytest.raises(ValueError):
                crawler.author(value, target_count=5)
        assert driver.visited == []


class TestAuthor:
    def test_the_space_is_opened_once_and_paged_by_scrolling(self, make_space):
        crawler, driver = make_space([[_card(A)], [_card(B)]], [_view(A), _view(B)])
        rows = crawler.author('266765166', target_count=10)
        assert [r['BV号'] for r in rows] == [A, B]
        assert driver.visited == ['https://space.bilibili.com/266765166/video']
        assert driver.rounds >= 1, 'the second screen has to arrive by scrolling, not by a page parameter'

    def test_a_row_from_the_space_carries_what_a_search_row_carries(self, make_space):
        crawler, _driver = make_space([[_card(A)]], [_view(A)])
        row = crawler.author('266765166', target_count=5)[0]
        assert row['播放数'] == 1405449 and row['点赞数'] == 85667
        assert row['UP主'] == '漫士沉思录' and row['UP主ID'] == '266765166'
        assert row['发布时间'] == '2024-10-19 14:59:31' and row['链接'] == f'https://www.bilibili.com/video/{A}/'

    def test_the_numbers_are_still_not_read_off_the_card(self, make_space):
        """The card's own figure is a rounded 万-label, so the API answer is the
        only number in the row — the same rule the search walk follows."""
        crawler, driver = make_space([[_card(A)]], [_view(A)])
        crawler.author('266765166', target_count=5)
        assert driver.fetched == [f'https://api.bilibili.com/x/web-interface/view?bvid={A}']

    def test_a_withdrawn_video_costs_a_row_but_not_the_run(self, make_space):
        crawler, _driver = make_space([[_card(GONE), _card(A)]], [_view(GONE, code=-404), _view(A)])
        rows = crawler.author('266765166', target_count=5)
        assert [r['BV号'] for r in rows] == [A]

    def test_risk_control_refuses_instead_of_reporting_a_short_list(self, make_space):
        crawler, _driver = make_space([[_card(A)]], [_view(A, code=-412)])
        with pytest.raises(RuntimeError) as err:
            crawler.author('266765166', target_count=5)
        assert '-412' in str(err.value)

    def test_a_login_wall_refuses_rather_than_calling_it_an_empty_space(self, make_space):
        crawler, driver = make_space([[_card(A)]], [_view(A)])
        driver.wall = True
        with pytest.raises(RuntimeError) as err:
            crawler.author('266765166', target_count=5)
        assert 'login' in str(err.value)
        assert driver.fetched == []

    def test_an_up_with_no_uploads_costs_no_api_call(self, make_space):
        """Zero cards is a real answer here (the profile header rendered, the list
        did not), and it must not be dressed up as a failed crawl."""
        crawler, driver = make_space([[]], [])
        assert crawler.author('266765166', target_count=5) == []
        assert driver.fetched == []

    def test_the_budget_is_spent_on_rows_not_on_screens(self, make_space):
        crawler, driver = make_space([[_card(A), _card(B), _card(C)]], [_view(A), _view(B)])
        rows = crawler.author('266765166', target_count=2)
        assert len(rows) == 2
        assert len(driver.fetched) == 2
        assert driver.rounds == 0, 'no scroll is worth taking when the target is already met'

    def test_a_resumed_run_does_not_pay_twice_for_one_video(self, make_space):
        """The rows carry their own BV号, so identity comes from what is already
        on disk and the cursor stays a position."""
        crawler, driver = make_space([[_card(A), _card(B)]], [_view(B)])
        crawler.seed([BilibiliCrawler._row(_view(A)['data'])])
        rows = crawler.author('266765166', target_count=3, resume={'scanned': 1})
        assert [r['BV号'] for r in rows] == [A, B]
        assert driver.fetched == [f'https://api.bilibili.com/x/web-interface/view?bvid={B}']

    def test_the_cursor_names_the_up_it_is_walking(self, make_space):
        crawler, _driver = make_space([[_card(A), _card(B)]], [_view(A), _view(B)])
        crawler.author('266765166', target_count=2)
        assert crawler.position['mid'] == '266765166'
        assert crawler.position['scanned'] == 2 and crawler.position['done'] == 2

    def test_a_list_that_stops_growing_ends_the_walk(self, make_space):
        """One UP with three videos: the walk must stop instead of scrolling for
        ``MAX_PAGES`` rounds on a page that will never change. Two rounds in a
        row where nothing arrives is the agreed end — one is a slow renderer."""
        crawler, driver = make_space([[_card(A), _card(B), _card(C)]], [_view(A), _view(B), _view(C)])
        rows = crawler.author('266765166', target_count=50)
        assert len(rows) == 3
        assert driver.rounds == 2, 'the walk stops on the second empty round, not the fortieth'
        assert len(driver.fetched) == 3, 'no video is asked for twice'


class TestPureHelpers:
    def test_bvid_is_read_out_of_any_link_shape(self):
        assert bilibili_bvid(f'https://www.bilibili.com/video/{A}/?vd_source=9') == A
        assert bilibili_bvid(f'https://b23.tv/{A}') == A
        assert bilibili_bvid('https://search.bilibili.com/all?keyword=ai') == ''
        assert bilibili_bvid('') == ''

    def test_page_one_carries_no_parameter(self):
        assert (
            bilibili_search_url('人工智能', 1)
            == 'https://search.bilibili.com/all?keyword=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD'
        )
        assert bilibili_search_url('人工智能', 3).endswith('%E6%99%BA%E8%83%BD&page=3')


class TestSearch:
    def test_first_page_is_the_bare_url_then_the_pager(self, make_crawler):
        crawler, driver = make_crawler([[_card(A)], [_card(B)]], [_view(A), _view(B)])
        rows = crawler.search('人工智能', target_count=5)
        assert len(rows) == 2
        assert 'page=' not in driver.visited[0]
        assert driver.visited[1].endswith('&page=2')

    def test_numbers_come_from_the_endpoint_not_the_card(self, make_crawler):
        crawler, _driver = make_crawler([[_card(A)]], [_view(A)])
        row = crawler.search('ai', target_count=1)[0]
        assert row['播放数'] == 1405449 and row['点赞数'] == 85667 and row['投币数'] == 79485
        assert row['收藏数'] == 130552 and row['转发数'] == 24794 and row['弹幕数'] == 7368 and row['评论数'] == 2194
        assert row['UP主'] == '漫士沉思录' and row['发布时间'] == '2024-10-19 14:59:31'
        assert row['正文'] == '视频使用素材来自：3blue1brown'
        assert row['链接'] == f'https://www.bilibili.com/video/{A}/'
        assert row['合集'] == 'AI 入门合集' and row['分P数'] == 1 and row['时长秒'] == 5338

    def test_ad_and_course_cards_cost_no_request(self, make_crawler):
        """The cards stay out of the queue as well as out of the table: an ad
        link carries no BV id, so fetching it would shift every later payload."""
        crawler, driver = make_crawler([[AD_CARD, _card(A), COURSE_CARD]], [_view(A)])
        rows = crawler.search('ai', target_count=5)
        assert [r['BV号'] for r in rows] == [A]
        assert len(driver.fetched) == 1

    def test_target_count_stops_before_the_next_page(self, make_crawler):
        crawler, driver = make_crawler([[_card(A), _card(B), _card(C)]], [_view(A), _view(B)])
        rows = crawler.search('ai', target_count=2)
        assert len(rows) == 2
        assert len(driver.visited) == 1, 'must not fetch a page it cannot use'

    def test_a_withdrawn_video_is_skipped_without_stopping_the_page(self, make_crawler):
        crawler, _driver = make_crawler([[_card(GONE), _card(A)]], [_view(GONE, code=-404), _view(A)])
        rows = crawler.search('ai', target_count=5)
        assert [r['BV号'] for r in rows] == [A]

    def test_risk_control_with_nothing_collected_refuses_the_run(self, make_crawler):
        crawler, _driver = make_crawler([[_card(A)]], [_view(A, code=-412)])
        with pytest.raises(RuntimeError) as err:
            crawler.search('ai', target_count=5)
        assert '-412' in str(err.value)

    def test_risk_control_after_a_page_keeps_the_rows(self, make_crawler):
        crawler, driver = make_crawler([[_card(A)], [_card(B)]], [_view(A), _view(B, code=-412)])
        rows = crawler.search('ai', target_count=50)
        assert [r['BV号'] for r in rows] == [A]
        assert len(driver.visited) == 2, 'the walk stops at the refusal, not at the pager'

    def test_the_pager_ends_on_two_pages_of_nothing_new(self, make_crawler):
        crawler, driver = make_crawler([[_card(A)]] * 4, [_view(A)])
        rows = crawler.search('ai', target_count=50)
        assert len(rows) == 1
        assert len(driver.visited) == 3, 'one repeat tolerated (a shuffled list), then stop'

    def test_an_empty_page_ends_the_walk(self, make_crawler):
        crawler, driver = make_crawler([[]], [])
        assert crawler.search('ai', target_count=5) == []
        assert len(driver.visited) == 1

    def test_a_login_wall_stops_without_inventing_rows(self, make_crawler):
        """The wall is recorded by the base class from ``current_url``; the
        crawler must break out of the pager and hand back what it has — an empty
        table here would read as "this keyword has no videos"."""
        crawler, driver = make_crawler([[_card(A)]], [_view(A)])
        driver.wall = True
        assert crawler.search('ai', target_count=5) == []
        assert crawler.login_wall is True
        assert driver.fetched == [], 'no endpoint call is worth making behind a wall'

    def test_position_is_recorded_per_video_and_resumes_on_that_page(self, make_crawler):
        crawler, _driver = make_crawler([[_card(A), _card(B)]], [_view(A)])
        crawler.search('ai', target_count=1)
        assert crawler.position['page'] == 1 and crawler.position['done'] == 1

        resumed, resumed_driver = make_crawler([[_card(B), _card(C)], [_card(D)]], [_view(C), _view(D)])
        rows = resumed.search('ai', target_count=3, resume={'page': 2})
        assert resumed_driver.visited[0].endswith('&page=2')
        assert len(rows) == 2


class TestHot:
    """The site's own boards: 热门 (paged) and 排行榜 (one answer), no per-row cost.

    What makes this mode its own walk is the measurement: ``popular`` and ``ranking/v2``
    answer ``code=0`` unsigned and **every item already carries owner/stat/pubdate**, so
    the search mode's one-request-per-row is not needed here. A "hot list" implemented
    with the search loop would spend 50 requests to produce what one request holds.
    """

    @staticmethod
    def _board(*bvids, code=0):
        items = []
        for bvid in bvids:
            data = _view(bvid)['data']
            # A board item is the view payload's shape with a couple of extras; the
            # flattener must not care which of the three endpoints produced it.
            data.pop('ugc_season', None)
            items.append(data)
        return {'code': code, 'message': 'OK', 'data': {'list': items, 'no_more': False}}

    def test_the_board_is_read_without_a_single_per_row_request(self, make_crawler):
        crawler, driver = make_crawler([[]], [self._board(A, B), self._board(C, D)])
        rows = crawler.hot('popular', target_count=3)
        assert [row['BV号'] for row in rows] == [A, B, C]
        assert len(driver.fetched) == 2, 'one request per board page, not one per video'
        assert all('popular?ps=20' in url for url in driver.fetched), driver.fetched
        assert driver.fetched[1].endswith('pn=2')

    def test_a_board_row_is_the_same_row_a_search_row_is(self, make_crawler):
        crawler, _driver = make_crawler([[]], [self._board(A)])
        row = crawler.hot('popular', target_count=1)[0]
        assert row['播放数'] == 1405449 and row['点赞数'] == 85667 and row['投币数'] == 79485
        assert row['UP主'] == '漫士沉思录' and row['UP主ID'] == '266765166'
        assert row['链接'] == f'https://www.bilibili.com/video/{A}/'
        assert row['发布时间'] == '2024-10-19 14:59:31'
        assert row['合集'] == '', 'the board carries no 合集, so the column stays empty rather than guessed'

    def test_the_weekly_ranking_is_one_answer_and_is_not_paged(self, make_crawler):
        """The ranking endpoint hands the whole board in one reply; walking it by page
        would replay the same 100 items until the round ceiling."""
        crawler, driver = make_crawler([[]], [self._board(A, B)])
        rows = crawler.hot('ranking', target_count=50)
        assert [row['BV号'] for row in rows] == [A, B]
        assert len(driver.fetched) == 1 and 'ranking/v2' in driver.fetched[0]

    def test_a_refused_board_with_nothing_collected_refuses_the_run(self, make_crawler):
        crawler, _driver = make_crawler([[]], [{'code': -412, 'message': 'risk', 'data': {}}])
        with pytest.raises(RuntimeError) as err:
            crawler.hot('popular', target_count=5)
        assert '-412' in str(err.value)

    def test_a_refusal_midway_keeps_the_rows_it_earned(self, make_crawler):
        crawler, _driver = make_crawler([[]], [self._board(A), {'code': -412, 'message': 'risk', 'data': {}}])
        rows = crawler.hot('popular', target_count=50)
        assert [row['BV号'] for row in rows] == [A]

    def test_a_board_that_answers_nothing_is_an_empty_answer_not_an_error(self, make_crawler):
        crawler, driver = make_crawler([[]], [{'code': 0, 'message': 'OK', 'data': {'list': []}}])
        assert crawler.hot('popular', target_count=5) == []
        assert len(driver.fetched) == 1, 'an empty board is not re-asked'

    def test_a_second_page_of_nothing_new_ends_the_walk(self, make_crawler):
        crawler, driver = make_crawler([[]], [self._board(A, B), self._board(A, B)])
        rows = crawler.hot('popular', target_count=50)
        assert [row['BV号'] for row in rows] == [A, B]
        assert len(driver.fetched) == 2

    def test_a_resumed_run_skips_the_videos_it_already_stored(self, make_crawler):
        """Resume identity is the BV号 already on disk, so a board page that is read
        again rebuilds nothing the dead run already paid for — and the budget counts
        those rows, which is why a target of 2 with 1 stored stops at one page."""
        crawler, driver = make_crawler([[]], [self._board(A, B)])
        crawler.seed([BilibiliCrawler._row(_view(A)['data'])])
        rows = crawler.hot('popular', target_count=2, resume={'page': 1})
        assert [row['BV号'] for row in rows] == [A, B]
        assert len(driver.fetched) == 1, 'the stored row counted toward the target, so no second page was asked'

    def test_the_cursor_records_which_board_was_walked(self, make_crawler):
        crawler, _driver = make_crawler([[]], [self._board(A)])
        crawler.hot('popular', target_count=1)
        assert crawler.position['board'] == 'popular' and crawler.position['page'] == 1

    def test_a_login_wall_refuses_the_board(self, make_crawler):
        crawler, driver = make_crawler([[]], [self._board(A)])
        driver.wall = True
        with pytest.raises(RuntimeError) as err:
            crawler.hot('popular', target_count=5)
        assert 'login' in str(err.value)
        assert driver.fetched == [], 'nothing is worth asking behind a wall'


class TestGetDetail:
    def test_one_video_by_url(self, make_crawler):
        crawler, _driver = make_crawler([], [_view(A)])
        row = crawler.get_detail(f'https://www.bilibili.com/video/{A}/')
        assert row['BV号'] == A and row['稿件ID'] == '113332711333508'

    def test_a_link_that_is_not_a_video_is_none(self, make_crawler):
        crawler, driver = make_crawler([], [])
        assert crawler.get_detail('https://search.bilibili.com/all?keyword=ai') is None
        assert driver.fetched == []

    def test_a_refused_detail_is_none_not_an_empty_row(self, make_crawler):
        crawler, _driver = make_crawler([], [_view(code=-403)])
        assert crawler.get_detail(f'https://www.bilibili.com/video/{A}/') is None
