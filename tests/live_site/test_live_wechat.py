"""Live WeChat article crawl — three real public articles, real Chrome.

The URLs were supplied by the user as stable test pages. Read counts, like counts and
rewards are not columns at all: an anonymous viewer's DOM never carries them,
and a zero read from nothing would be indistinguishable from real data.
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
        # 阅读/在看/赞赏/留言 are never obtainable in a browser — see the
        # WechatCrawler docstring — so a live row must not carry them at all.
        assert '阅读数' not in row and '在看数' not in row and '赞赏数' not in row


class TestCookieDiagnosis:
    """What a real browser session is actually allowed to see — measured here so
    the panel's verdict is pinned to the site's behaviour, not to a theory."""

    def test_the_generic_diagnosis_carries_no_wechat_special_case(self, live_crawler):
        """WeChat has no cookie row in the panel any more (bodies are served to
        anyone, and the keyword-search channel was removed), so the diagnosis is
        the plain generic one: an address and a wall flag."""
        crawler = live_crawler('wechat', headless=False)
        facts = crawler.diagnose()
        assert set(facts) == {'platform', 'url', 'login_wall'}
        assert facts['platform'] == 'mp.weixin.qq.com'
        assert facts['url'].startswith('https://mp.weixin.qq.com/')

    def test_the_diagnosis_reports_no_comment_state_at_all(self, live_crawler):
        """WeChat comments are not a capability here, so the diagnosis must not
        even have a field for them — a leftover key would let the panel keep
        talking about something no code can read."""
        crawler = live_crawler('wechat', headless=False)
        facts = crawler.diagnose(ARTICLE_URLS[0])
        for gone in (
            'comments_supported',
            'comment_key',
            'comment_visible',
            'has_pass_ticket',
            'body_readable',
            'comment_id',
            'mp_logged_in',
        ):
            assert gone not in facts, f'{gone} survived the removal'
        # The article body is still public, which is what WeChat crawling does offer.
        assert crawler.driver.current_url.startswith('https://mp.weixin.qq.com/')


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
