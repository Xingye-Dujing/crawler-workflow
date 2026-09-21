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


def test_three_real_articles_parse_into_full_rows(live_crawler):
    crawler = live_crawler('wechat')
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
