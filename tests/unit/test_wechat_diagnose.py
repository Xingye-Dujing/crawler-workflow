"""WeChat cookie diagnosis — the two capabilities, checked separately.

No browser here: ``Crawler._create_driver`` is swapped for a scripted fake, so
what is under test is which facts the crawler reports and how it reads them.
The live question — does a browser session ever get a comment credential — is
covered by ``tests/live_site/test_live_wechat.py`` instead.
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
    """Answers with a fixed script: URL per page, credential object, comment rows."""

    def __init__(self, url_map=None, credentials=None, comment_rows=0, body_text=''):
        self.url_map = url_map or {}
        self.credentials = credentials if credentials is not None else {}
        self.comment_rows = comment_rows
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
        return dict(self.credentials)

    def find_element(self, by, selector):
        if selector == 'body':
            return FakeElement(self.body_text)
        if selector == '#rich_media_content, .rich_media_content':
            return FakeElement('正文')
        raise KeyError(selector)

    def find_elements(self, by, selector):
        if selector == '.discuss_list .item':
            return [FakeElement() for _ in range(self.comment_rows)]
        return []


@pytest.fixture
def make_crawler(monkeypatch):
    """Build a WechatCrawler over a scripted fake driver."""

    def _make(**driver_kwargs):
        def fake_create_driver(self):
            self.driver = FakeDriver(**driver_kwargs)

        monkeypatch.setattr(Crawler, '_create_driver', fake_create_driver, raising=False)
        crawler = WechatCrawler(headless=True, cookie_path=None)
        crawler.cookies_loaded = 0
        return crawler

    return _make


ADMIN = 'https://mp.weixin.qq.com/'
ADMIN_LOGGED_IN = 'https://mp.weixin.qq.com/cgi-bin/home?t=home/index&token=987654321'
ARTICLE = 'https://mp.weixin.qq.com/s/cAx1zGfT2MzqpwnhULmSQA'
CLIENT_ARTICLE = (
    'https://mp.weixin.qq.com/s?__biz=MzA3Mjc3NjkxNg%3D%3D&mid=265&idx=1&sn=abc123&pass_ticket=Pt%2Fxyz&chksm=8d0#rd'
)


class TestAdminSession:
    def test_a_redirect_carrying_a_token_is_a_logged_in_admin(self, make_crawler):
        crawler = make_crawler(url_map={ADMIN: ADMIN_LOGGED_IN})
        facts = crawler.diagnose()
        assert facts['mp_logged_in'] is True
        assert facts['login_wall'] is False

    def test_staying_on_the_login_page_is_not_logged_in(self, make_crawler):
        crawler = make_crawler()
        facts = crawler.diagnose()
        assert facts['mp_logged_in'] is False
        assert facts['login_wall'] is True

    def test_the_admin_check_runs_even_when_an_article_was_supplied(self, make_crawler):
        """Two capabilities, one panel action: search readiness and comment
        access are answered together rather than forcing a second round trip."""
        crawler = make_crawler(url_map={ADMIN: ADMIN_LOGGED_IN})
        facts = crawler.diagnose(ARTICLE)
        assert crawler.driver.visited[0] == ADMIN
        assert facts['mp_logged_in'] is True


class TestNoCommentDiagnostics:
    """The comment apparatus is gone, so the diagnosis must not claim any of it.

    A half-removed capability is worse than an absent one: a leftover
    ``comment_key`` fact would let the panel keep reporting on something no code
    can read.
    """

    def test_no_comment_facts_are_ever_reported(self, make_crawler):
        facts = make_crawler().diagnose(ARTICLE)
        for gone in ('comment_key', 'comment_id', 'comment_visible', 'has_pass_ticket', 'body_readable'):
            assert gone not in facts, f'{gone} survived the removal'

    def test_an_article_url_changes_nothing_about_the_verdict(self, make_crawler):
        crawler = make_crawler(url_map={ADMIN: ADMIN_LOGGED_IN})
        assert crawler.diagnose(ARTICLE)['mp_logged_in'] is True
        assert crawler.diagnose()['mp_logged_in'] is True

    def test_the_crawler_exposes_no_comment_helpers(self):
        for gone in ('article_credentials', 'rendered_comment_count'):
            assert not hasattr(WechatCrawler, gone), f'{gone} still reachable'

    def test_wechat_is_not_a_comment_platform_for_the_router(self):
        """utils.helpers routes article links to adapters; WeChat has none, so a
        pasted 微信 link in comments mode must be refused rather than silently
        producing zero rows."""
        from utils.helpers import platform_for

        assert platform_for('https://mp.weixin.qq.com/s/abc') == ''
        assert platform_for('https://www.zhihu.com/question/1') == 'zhihu'
