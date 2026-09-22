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


class TestArticleCredentials:
    def test_the_credential_page_yields_a_usable_comment_key(self, make_crawler):
        crawler = make_crawler(
            credentials={
                'key': 'K-123',
                'comment_id': 'C-9',
                'appmsg_token': 'T-1',
                'biz': 'B',
                'mid': 'M',
                'idx': '1',
                'sn': 'S',
                'pass_ticket': 'P',
            },
            comment_rows=7,
        )
        facts = crawler.diagnose(CLIENT_ARTICLE)
        assert facts['comment_key'] == 'K-123'
        assert facts['comment_id'] == 'C-9'
        assert facts['has_pass_ticket'] is True
        assert facts['comment_visible'] == 7
        assert facts['body_readable'] is True

    def test_a_plain_web_link_has_no_credential_and_shows_no_comments(self, make_crawler):
        """This is the shape the user meets every day — the comment area is
        present but empty. It must read as "not permitted", never as "the
        article has no comments"."""
        crawler = make_crawler(credentials={}, comment_rows=0)
        facts = crawler.diagnose(ARTICLE)
        assert facts['comment_key'] == ''
        assert facts['has_pass_ticket'] is False
        assert facts['comment_visible'] == 0

    def test_url_tokens_backfill_what_the_page_globals_do_not_provide(self, make_crawler):
        """Older article templates do not define the globals but always carry the
        tokens in the address — percent-decoded, which is the form the comment
        endpoint expects."""
        crawler = make_crawler(url_map={CLIENT_ARTICLE: CLIENT_ARTICLE})
        crawler.driver.get(CLIENT_ARTICLE)
        creds = crawler.article_credentials()
        assert creds['pass_ticket'] == 'Pt/xyz'
        assert creds['biz'] == 'MzA3Mjc3NjkxNg=='
        assert creds['sn'] == 'abc123'

    def test_a_script_that_raises_yields_empty_credentials_not_a_crash(self, make_crawler):
        crawler = make_crawler()

        def boom(_script, *_args):
            raise RuntimeError('page navigated away')

        crawler.driver.execute_script = boom
        assert set(crawler.article_credentials()) == {
            'key',
            'show_comment',
            'comment_id',
            'appmsg_token',
            'biz',
            'mid',
            'idx',
            'sn',
            'pass_ticket',
            'uin',
        }
        assert crawler.article_credentials()['key'] == ''

    def test_no_article_requested_reports_no_comment_facts_at_all(self, make_crawler):
        """Absent is not the same as empty: the panel only shows the comment
        verdict when an article was actually probed."""
        facts = make_crawler().diagnose()
        assert 'comment_key' not in facts
        assert 'has_pass_ticket' not in facts


class TestRenderedCommentCount:
    def test_the_widest_of_the_known_list_shapes_wins(self, make_crawler):
        crawler = make_crawler(comment_rows=3)
        crawler.driver.find_elements = lambda by, selector: [object()] * 5 if selector == '.discuss_list > li' else []
        assert crawler.rendered_comment_count() == 5

    def test_a_driver_that_cannot_answer_reads_as_no_comments(self, make_crawler):
        crawler = make_crawler()

        def boom(by, selector):
            raise RuntimeError('no such element')

        crawler.driver.find_elements = boom
        assert crawler.rendered_comment_count() == 0
