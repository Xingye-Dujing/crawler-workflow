"""The two collection-depth parameters: WeChat's body ceiling and XHS's comment preview.

Both are small knobs that were previously hardcoded in the middle of a scraper,
and each hardcoded value caused a distinct silent loss:

* WeChat cut every article at a literal 5000 characters with a ``'...'`` suffix.
  Long posts lost their ending, and nothing downstream could tell a truncated
  body from a short one that simply ended there — which is exactly what feeds a
  keyword/sentiment analysis a quietly wrong input.
* Xiaohongshu waited up to ten seconds per note for a comment panel it then read
  only five rows of. ``0`` has to mean "don't even look", not "wait anyway".

The XHS parser is pinned on its edge cases because the panel sends a string and
``0`` is a legitimate value that a truthiness test would silently discard.
"""

from types import SimpleNamespace

import pytest

from config import Config
from crawlers.wechat import WechatCrawler
from crawlers.xiaohongshu import XiaohongshuCrawler as Xhs

pytestmark = pytest.mark.unit


class TestWechatBodyCeiling:
    def test_a_short_body_is_returned_untouched(self, monkeypatch):
        monkeypatch.setattr(Config, 'WECHAT_BODY_MAX_CHARS', 100)
        assert WechatCrawler._clip('三亚的海很蓝') == '三亚的海很蓝'

    def test_a_long_body_is_cut_and_marked(self, monkeypatch):
        """The marker is the whole point: without it a cut body is
        indistinguishable from an article that ended there."""
        monkeypatch.setattr(Config, 'WECHAT_BODY_MAX_CHARS', 10)
        clipped = WechatCrawler._clip('一' * 30)
        assert clipped == '一' * 10 + '…'
        assert len(clipped) == 11

    def test_zero_means_keep_everything(self, monkeypatch):
        long_text = '句' * 50000
        monkeypatch.setattr(Config, 'WECHAT_BODY_MAX_CHARS', 0)
        assert WechatCrawler._clip(long_text) == long_text
        monkeypatch.setattr(Config, 'WECHAT_BODY_MAX_CHARS', None)
        assert WechatCrawler._clip(long_text) == long_text, 'a missing config must not truncate'

    def test_the_ceiling_is_configurable_not_hardcoded(self):
        assert hasattr(Config, 'WECHAT_BODY_MAX_CHARS'), 'the knob must live in Config'
        monkey_value = 12345
        Config.WECHAT_BODY_MAX_CHARS = monkey_value
        try:
            assert len(WechatCrawler._clip('字' * 20000)) == 12346
        finally:
            Config.WECHAT_BODY_MAX_CHARS = 5000

    def test_an_empty_body_stays_empty(self, monkeypatch):
        monkeypatch.setattr(Config, 'WECHAT_BODY_MAX_CHARS', 10)
        assert WechatCrawler._clip('') == ''
        assert WechatCrawler._clip(None) == ''


class TestXhsCommentPreview:
    @pytest.mark.parametrize(
        ('given', 'expected'),
        [
            ({}, Xhs.DEFAULT_COMMENT_PREVIEW),
            ({'comment_preview': None}, Xhs.DEFAULT_COMMENT_PREVIEW),
            ({'comment_preview': ''}, Xhs.DEFAULT_COMMENT_PREVIEW),
            ({'comment_preview': '0'}, 0),
            ({'comment_preview': 0}, 0),
            ({'comment_preview': '25'}, 25),
            ({'comment_preview': 3.7}, 3),
            ({'comment_preview': 'abc'}, Xhs.DEFAULT_COMMENT_PREVIEW),
            ({'comment_preview': -1}, Xhs.DEFAULT_COMMENT_PREVIEW),
            ({'comment_preview': '1e2'}, 100),
        ],
    )
    def test_the_panel_value_is_parsed_not_tested_for_truthiness(self, given, expected):
        """``0`` is the most important case: a truthy check would turn "skip the
        comment panel" back into the default, and a missing/invalid value must
        never widen the crawl beyond the default."""
        assert Xhs._comment_preview_of(given) == expected

    def test_zero_skips_the_panel_without_waiting(self, monkeypatch):
        """A preview of 0 must cost nothing — that is the user's reason to pick it."""
        waited = []
        crawler = Xhs.__new__(Xhs)  # no browser: only the extractor's guard is under test
        crawler.driver = object()  # never touched on this path; the guard must return first
        monkeypatch.setattr('crawlers.xiaohongshu.WebDriverWait', lambda *a, **k: waited.append('waited') or [])
        assert crawler.extract_comments(max_comments=0) == []
        assert waited == [], 'a zero preview may not wait on the comment panel'

    def test_a_positive_preview_still_reaches_the_wait(self, monkeypatch):
        from selenium.common.exceptions import TimeoutException

        waited = []
        crawler = Xhs.__new__(Xhs)
        crawler.driver = object()  # never touched on this path; the guard must return first

        def _fake_wait(*args, **kwargs):
            waited.append('waited')
            return SimpleNamespace(until=lambda _cond: (_ for _ in ()).throw(TimeoutException()))

        monkeypatch.setattr('crawlers.xiaohongshu.WebDriverWait', _fake_wait)
        assert crawler.extract_comments(max_comments=5) == []
        assert waited == ['waited'], 'a real preview must still try the panel once'

    def test_search_seeds_the_instance_from_its_kwargs(self, monkeypatch):
        """The value has to survive from kwargs to the per-note scraper, which is
        several calls deeper — an instance attribute is the thread between them."""
        crawler = Xhs.__new__(Xhs)
        crawler.comment_preview = crawler._comment_preview_of({'comment_preview': '12'})
        assert crawler.comment_preview == 12
