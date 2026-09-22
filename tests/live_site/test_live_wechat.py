"""Live WeChat article crawl — three real public articles, real Chrome.

The URLs were supplied by the user as stable test pages. Read counts are NOT
asserted non-zero: an anonymous viewer's DOM genuinely omits them (only the
account owner's logged-in WeChat client injects them) — zero is the correct
observation, and the column must stay an int either way.
"""

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]

ARTICLE_URLS = [
    'https://mp.weixin.qq.com/s/cAx1zGfT2MzqpwnhULmSQA',
    'https://mp.weixin.qq.com/s/q59mL_dHixC97p19RpcfVQ',
    'https://mp.weixin.qq.com/s/f_2nB7u7pQApgIoPsBKMQg',
]


@pytest.mark.parametrize('headless', [True, False], ids=['headless', 'visible'])
def test_three_real_articles_parse_into_full_rows(live_crawler, headless):
    crawler = live_crawler('wechat', headless=headless)
    rows = crawler.search(urls=list(ARTICLE_URLS))
    assert len(rows) == 3, 'every supplied article must yield exactly one row'
    links = [r['链接'] for r in rows]
    assert links == ARTICLE_URLS  # order preserved, identity = the URL we asked for
    for row in rows:
        assert row['标题'].strip(), f'title missing: {row["链接"]}'
        assert row['公众号'].strip(), f'account missing: {row["链接"]}'
        assert len(row['正文']) >= 20, f'body too thin: {row["链接"]}'
        # The Chinese date spelling must survive the extractor (2026年9月15日…).
        assert '20' in row['发布时间'], f'publish time empty for {row["链接"]}'
        assert isinstance(row['阅读数'], int) and row['阅读数'] >= 0


class TestCookieDiagnosis:
    """What a real browser session is actually allowed to see — measured here so
    the panel's verdict is pinned to the site's behaviour, not to a theory."""

    def test_both_capabilities_are_answered_without_raising(self, live_crawler):
        crawler = live_crawler('wechat', headless=False)
        facts = crawler.diagnose(ARTICLE_URLS[0])
        assert set(facts) >= {
            'platform',
            'url',
            'login_wall',
            'mp_logged_in',
            'comment_key',
            'comment_visible',
            'has_pass_ticket',
            'body_readable',
        }
        # An article page is public: if the body does not render, the crawl of
        # this site is broken for a reason the diagnosis must surface.
        assert facts['body_readable'] is True, f'正文 did not render: {facts["url"]}'

    def test_a_plain_web_link_gets_no_comment_credential(self, live_crawler):
        """Measured on every supplied article: the comment container exists but
        the server hands out no ``key``, so the list stays empty. This is the
        fact behind "评论区在浏览器里不可见" — if WeChat ever starts granting it
        to browsers, this test failing is the news, and the panel can be relaxed."""
        crawler = live_crawler('wechat', headless=False)
        for url in ARTICLE_URLS:
            facts = crawler.diagnose(url)
            assert facts['comment_key'] == '', f'a credential appeared for {url}'
            assert facts['has_pass_ticket'] is False, f'pass_ticket appeared for {url}'
            assert facts['comment_visible'] == 0, f'the comment list filled in for {url}'

    def test_the_admin_verdict_agrees_with_the_address_shown(self, live_crawler):
        """Logged into the 公众平台, the login page redirects to a URL carrying a
        ``token``; that redirect IS the check, so the two answers cannot disagree."""
        crawler = live_crawler('wechat', headless=False)
        facts = crawler.diagnose()
        assert facts['mp_logged_in'] == ('token=' in facts['url'])


class TestCommentRefusal:
    """The measured answer to "can a browser read 推文留言": no.

    Pinned as an invariant rather than one status, because the articles differ in
    whether they even have a 留言 module (the three stable ones do not, so they
    correctly read as ``dead``); what must never happen is a browser session
    being told "0 comments" as if that were the article's answer.
    """

    #: An article that provably HAS 留言 in the WeChat client (one comment,
    #: confirmed by the user on 2026-09-22) — the only kind of article that can
    #: distinguish "the site hides comments from browsers" from "this article has
    #: no comments". The three stable URLs above have none, so they prove nothing
    #: on their own.
    ARTICLE_WITH_COMMENTS = 'https://mp.weixin.qq.com/s/oErxI--zmd7HkEWtF8BiHQ'

    def _crawl(self, live_crawler, url):
        from crawlers.comments import CommentSession

        crawler = live_crawler('wechat', headless=False)
        session = CommentSession(crawler.driver, log=lambda msg: None, nap=lambda _s: None)
        return crawler, session.crawl_wechat(url, 20)

    def test_an_article_with_comments_is_refused_not_reported_as_empty(self, live_crawler):
        """The decisive case: the client shows 1 条留言, a browser session gets
        ``show_comment=0``, no ``elected_comment`` in 3.4 MB of HTML, no credential,
        and the endpoint answers its 验证 page. That must surface as ``blocked``."""
        crawler, (rows, status) = self._crawl(live_crawler, self.ARTICLE_WITH_COMMENTS)
        assert (rows, status) == ([], 'blocked'), f'the endpoint answered a browser: {rows[:2]}'
        creds = crawler.article_credentials()
        assert creds['comment_id'], 'the page must still expose its comment id, else DEAD would be the wrong answer'
        assert not creds['key'], 'a key appeared — the site now issues comment credentials to browsers'
        assert creds['show_comment'] == '0', 'the server stopped hiding the area from this session'
        assert crawler.rendered_comment_count() == 0

    @pytest.mark.parametrize('url', ARTICLE_URLS + [ARTICLE_WITH_COMMENTS])
    def test_a_browser_session_never_returns_comment_rows(self, live_crawler, url):
        _crawler, (rows, status) = self._crawl(live_crawler, url)
        assert rows == [], f'a browser was handed comments, which the site says it cannot see: {rows[:2]}'
        assert status != 'ok', 'zero rows must not be reported as a clean "this article has no comments"'


def test_reread_of_same_url_is_deduped_by_the_ledger(live_crawler):
    """The streaming contract on the real store path: a second sighting of an
    already-collected item is refused by the sink, not duplicated."""
    from config import Config
    from services.run_store import RunStore

    store = RunStore(str(Config.RUNS_DB))
    crawler = live_crawler('wechat')
    scope = 'live-test:wechat'
    # The app wires both sinks together; mimic that here so mark_position and
    # the ledger run exactly as they do inside a durable run.
    crawler.set_sink(lambda item: store.append_rows('live-r', 'wechat-node', [item], dedupe_scope=scope)[0] > 0)
    crawler.set_cursor_sink(lambda pos: store.save_cursor('live-r', 'wechat-node', pos))
    rows = crawler.search(urls=[ARTICLE_URLS[0], ARTICLE_URLS[0]])
    assert len(rows) == 1, 'the same article fetched twice must be collected once'
    assert store.row_count('live-r', 'wechat-node') == 1
    store.delete_run('live-r')
    store.forget_items(scope)
