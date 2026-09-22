"""What the WeChat crawler must NOT claim.

Two capabilities have been removed from this platform, and both removals are
pinned here because a leftover is worse than an absence:

* 留言/点赞/转发 were never obtainable from a browser (measured), so no comment
  helper, comment fact or comment column may reappear;
* keyword search via the 公众号后台 was deleted once WeChat's ``freq control``
  window made its article-list endpoint impossible to verify — so the crawler
  must not carry an admin-session diagnosis either, and the cookie panel must
  not offer a 微信 row that unlocks nothing (article bodies need no login).

No browser here: ``Crawler._create_driver`` is swapped for a scripted fake.
"""

import pytest

from crawlers.base import Crawler
from crawlers.wechat import WechatCrawler

pytestmark = pytest.mark.unit


class FakeElement:
    def __init__(self, text=''):
        self.text = text

    def get_attribute(self, name):
        return ''


class FakeDriver:
    def __init__(self, url_map=None, body_text=''):
        self.url_map = url_map or {}
        self.body_text = body_text
        self.visited = []
        self._current = ''

    def get(self, url):
        self.visited.append(url)
        self._current = self.url_map.get(url, url)

    @property
    def current_url(self):
        return self._current

    def execute_script(self, _script, *_args):
        return {}

    def find_element(self, by, selector):
        if selector == 'body':
            return FakeElement(self.body_text)
        raise KeyError(selector)

    def find_elements(self, by, selector):
        return []


ARTICLE = 'https://mp.weixin.qq.com/s/cAx1zGfT2MzqpwnhULmSQA'


@pytest.fixture
def make_crawler(monkeypatch):
    def _make(**driver_kwargs):
        def fake_create_driver(self):
            self.driver = FakeDriver(**driver_kwargs)

        monkeypatch.setattr(Crawler, '_create_driver', fake_create_driver, raising=False)
        crawler = WechatCrawler(headless=True, cookie_path=None)
        crawler.cookies_loaded = 0
        return crawler

    return _make


class TestNoCommentApparatus:
    """A half-removed capability still lets the UI report on what no code can read."""

    def test_the_crawler_exposes_no_comment_helpers(self):
        for gone in ('article_credentials', 'rendered_comment_count', 'get_like_count', 'get_reward_count'):
            assert not hasattr(WechatCrawler, gone), f'{gone} survived the removal'

    def test_diagnose_reports_only_generic_facts(self, make_crawler):
        facts = make_crawler().diagnose(ARTICLE)
        for gone in ('comment_key', 'comment_id', 'comment_visible', 'has_pass_ticket', 'mp_logged_in'):
            assert gone not in facts, f'{gone} survived the removal'

    def test_an_article_url_changes_nothing_about_the_verdict(self, make_crawler):
        """Diagnosis is the shared base-class behaviour now: it visits the login
        page and reports a wall or not — nothing WeChat-specific."""
        crawler = make_crawler()
        facts = crawler.diagnose(ARTICLE)
        assert facts['platform'] == 'mp.weixin.qq.com'
        assert set(facts) == {'platform', 'url', 'login_wall'}


class TestNoSearchLeftovers:
    def test_wechat_is_not_a_comment_platform_for_the_router(self):
        """utils.helpers routes article links to adapters; WeChat has none, so a
        pasted 微信 link in comments mode must be refused rather than silently
        producing zero rows."""
        from utils.helpers import platform_for

        assert platform_for('https://mp.weixin.qq.com/s/abc') == ''
        assert platform_for('https://www.zhihu.com/question/1') == 'zhihu'

    def test_the_crawler_takes_urls_because_a_keyword_would_lie(self, make_crawler):
        """Keyword search is gone, so the only WeChat crawl is "these links".

        An empty keyword list returns empty without opening a page — which is the
        behaviour a saved workflow with an empty textarea depends on, and the
        reason a keyword argument can never silently become a search again.
        """
        crawler = make_crawler()
        assert crawler.search(keyword='人工智能', urls=[]) == []
        assert crawler.search(urls=None) == []
        assert crawler.driver.visited == [], 'nothing may be fetched when no link was given'

    def test_no_module_builds_an_admin_request(self):
        """searchbiz/appmsg were the search channel; nothing may assemble them."""
        import inspect

        source = inspect.getsource(WechatCrawler)
        for gone in ('searchbiz', 'appmsg', 'list_ex', 'fakeid'):
            assert gone not in source, f'{gone} survived the removal'
