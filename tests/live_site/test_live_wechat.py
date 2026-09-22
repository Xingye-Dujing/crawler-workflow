"""Live WeChat article crawl — three real public articles, real Chrome.

The URLs were supplied by the user as stable test pages. Read counts, like counts and
rewards are not columns at all: an anonymous viewer's DOM never carries them,
and a zero read from nothing would be indistinguishable from real data.

Nothing here logs in or visits 微信公众平台: WeChat bodies need no session, so the
platform has no cookie row at all. "The diagnosis object carries no WeChat key"
is a question about field shapes, not about the live site, and it is answered in
tests/unit/test_wechat_diagnose.py against a scripted driver — no browser is
spent here for a capability this platform does not have.
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
