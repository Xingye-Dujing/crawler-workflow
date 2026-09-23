"""What the WeChat crawler must NOT claim.

Two capabilities have been removed from this platform, and both removals are
pinned here because a leftover is worse than an absence:

* 留言/点赞/转发 were never obtainable from a browser (measured), so no comment
  helper, comment fact or comment column may reappear;
* keyword search via the 公众号后台 was deleted once WeChat's ``freq control``
  window made its article-list endpoint impossible to verify — so the crawler
  must not carry an admin-session diagnosis either, must not name a page to log
  in on (article bodies need no session), and the cookie panel must not offer a
  微信 row that unlocks nothing.

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
        """Diagnosis is the shared base-class behaviour now: it opens whatever it
        is handed and reports a wall or not — nothing WeChat-specific."""
        crawler = make_crawler()
        facts = crawler.diagnose(ARTICLE)
        assert facts['platform'] == 'mp.weixin.qq.com'
        assert set(facts) == {'platform', 'url', 'login_wall'}

    def test_wechat_offers_no_login_page_at_all(self):
        """The residue this pins: a ``login_url`` on this class means some code
        will drive a browser to 公众平台 to sign in — for a platform whose one
        capability (article bodies) is served to anyone. The base class default
        is empty, so an empty answer here is the correct one, not a missing field.
        """
        assert 'login_url' not in WechatCrawler.__dict__, 'WeChat must not name a page to log in on'
        assert WechatCrawler.login_url == ''

    def test_diagnosis_without_a_url_opens_nothing(self, make_crawler):
        """With no login page to fall back on, the generic diagnosis must say so
        by visiting nothing — rather than guessing a host and reporting on a page
        the user never asked about."""
        crawler = make_crawler()
        facts = crawler.diagnose()
        assert facts == {'platform': 'mp.weixin.qq.com', 'url': '', 'login_wall': False}
        assert crawler.driver.visited == []

    def test_the_cookie_panel_has_no_wechat_row(self):
        """``CookieManager.PLATFORMS`` is who the panel can log in; WeChat sits
        out of it, so no flow, status entry or generate job can be built for it."""
        from services.cookie_manager import CookieManager

        assert 'wechat' not in CookieManager.PLATFORMS


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

    def test_the_batch_narration_promises_no_figure_the_site_withholds(self):
        """No WeChat message may offer 阅读/点赞/打赏, and no line may print its own keys.

        WeChat publishes none of the three to a browser that is not the client
        (measured — see the red line about those columns), so naming them in a message
        about a WeChat scrape is a plausible figure with no source. The per-article
        line also used to *print* them: the call passed four keywords and the template
        asked for seven, and ``t()`` answers a missing parameter with the raw template,
        so the user read ``| 阅读={reads} 点赞={likes} 打赏={rewards}`` once per article.
        """
        import i18n

        for lang in ('zh', 'en'):
            table = i18n.MESSAGES[lang]
            for key, template in table.items():
                if not key.startswith('crawl.wechat.'):
                    continue
                for banned in ('{reads}', '{likes}', '{rewards}', '阅读=', '点赞=', '--- ', '>>> ', '  '):
                    assert banned not in template, f'{lang}/{key} still carries {banned!r}'
            # Renders from exactly what the call site passes.
            assert '1/3' in table['crawl.wechat.success'].format(i=1, total=3, title='甲', author='乙')

    def test_one_article_produces_one_console_line_not_a_step_trace(self):
        """The scrape trace is debug-level; the console gets the outcome.

        ``get_detail`` used to narrate ten info lines per article — including a
        120-character quote of the body — so a three-link batch buried the one thing
        the user was looking for ("did this one come through?") under a screen of
        steps, and pasted article text into a shared console.
        """
        import inspect

        assert 'logger.info(' not in inspect.getsource(WechatCrawler.get_detail), (
            'a step inside one article is a debugging detail, not a console line'
        )
        batch = inspect.getsource(WechatCrawler.search)
        assert "'=' * 70" not in batch and "logger.info('')" not in batch, 'banner rows are standalone-script style'
