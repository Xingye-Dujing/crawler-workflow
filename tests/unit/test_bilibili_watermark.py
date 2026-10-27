"""The Bilibili author walk stops at the previous completed run's newest BV."""

import pytest

from crawlers.platforms.bilibili.crawler import BilibiliCrawler
from engine.workflow import WorkflowEngine
from i18n import get_lang, set_lang


@pytest.fixture()
def crawler(monkeypatch):
    monkeypatch.setattr('crawlers.core.crawler.Crawler._create_driver', lambda self: None)
    instance = BilibiliCrawler(headless=True)
    instance.driver = None
    instance.CARD_WAIT = 0
    instance.POLITE_BASE = 0
    instance.POLITE_SPREAD = 0
    instance.open = lambda _url: None
    instance.check_login_wall = lambda _url: None
    instance._bvids = lambda: ['BVnew1', 'BVnew2', 'BVold']
    instance._on_screen_key = lambda: 'screen'
    instance._click_next_page = lambda: None
    instance.results = lambda: []
    instance._row = lambda data: {'BV号': data['bvid']}
    fetched = []

    def fetch(url):
        bvid = url.rsplit('=', 1)[1]
        fetched.append(bvid)
        return {'code': 0, 'data': {'bvid': bvid}}

    instance._fetch_json = fetch
    emitted = []
    instance.emit = lambda row: emitted.append(row) or True
    instance.collected = lambda: len(emitted)
    instance.test_fetched = fetched
    instance.test_emitted = emitted
    yield instance
    instance.close()


def test_the_boundary_video_is_not_fetched_and_the_walk_stops(crawler):
    crawler.set_watermark('BVold')
    crawler.author('123456', target_count=10)
    assert crawler.test_fetched == ['BVnew1', 'BVnew2'], crawler.test_fetched
    assert [row['BV号'] for row in crawler.test_emitted] == ['BVnew1', 'BVnew2']
    assert crawler._watermark_hit is True
    assert crawler._watermark_candidate == 'BVnew1'


def test_without_a_watermark_the_same_walk_fetches_the_boundary(crawler):
    crawler.author('123456', target_count=3)
    assert crawler.test_fetched == ['BVnew1', 'BVnew2', 'BVold']
    assert crawler._watermark_hit is False
    assert crawler._watermark_candidate == 'BVnew1'


def _source(platform, collect, **extra):
    params = {'platform': platform, 'collect': collect, **extra}
    return {'nodes': [{'id': 'node-0', 'type': 'source', 'platform': platform, 'params': params}], 'connections': []}


def test_the_engine_refuses_watermark_where_no_stable_boundary_exists(monkeypatch):
    previous = get_lang()
    set_lang('en')
    try:
        monkeypatch.setattr(WorkflowEngine, '_source_errors', lambda *args, **kwargs: [])
        errors = WorkflowEngine(_source('zhihu', 'posts', watermark=True)).validate()
        assert any('watermark' in error.lower() for error in errors), errors

        errors = WorkflowEngine(_source('bilibili', 'author', author='123456', watermark=True, recrawl=True)).validate()
        assert any('watermark' in error.lower() and 're-crawl' in error.lower() for error in errors), errors
    finally:
        set_lang(previous)
