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
from crawlers.video import BilibiliCrawler, bilibili_bvid, bilibili_search_url

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
