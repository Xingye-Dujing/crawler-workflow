"""Live comment crawls — the real sites, small limits, three outcomes.

Same tier rules as the other live tests (saved cookies required, tiny
volumes). Weibo/xiaohongshu/zhihu each get one article found live *right
before* the comment crawl — no fixture URLs that quietly die over time —
and the assertions tolerate the honest outcomes (a post with no comments is
`ok` with zero rows; a wall must surface as `blocked`, never as empty data).
"""

import re

import pytest

from crawlers.comments import BLOCKED, OK, CommentSession

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


def _fresh_post_with_comments(live_crawler, headless=True):
    """A weibo post that reports 评论数 > 0 from the ordinary time-window search."""
    from datetime import date, timedelta

    crawler = live_crawler('weibo', headless=headless)
    end = date.today()
    start = end - timedelta(days=7)
    rows = crawler.search(
        '三亚', start_time=start.strftime('%Y-%m-%d'), end_time=end.strftime('%Y-%m-%d'), target_count=8
    )
    link = ''
    for row in rows:
        if int(row.get('评论数') or 0) > 0 and 'weibo.com/' in (row.get('链接') or ''):
            link = row['链接']
            break
    crawler.close()
    return link


@pytest.mark.parametrize(
    'headless',
    [pytest.param(True, marks=pytest.mark.live_quick, id='headless'), pytest.param(False, id='visible')],
)
def test_weibo_comments_live(live_crawler, headless):
    link = _fresh_post_with_comments(live_crawler, headless=headless)
    if not link:
        pytest.skip('no searched weibo post had comments right now — nothing to fetch honestly')
    crawler = live_crawler('weibo', headless=headless)
    try:
        session = CommentSession(crawler.driver, log=print)
        rows, status = session.crawl_weibo(link, limit=5)
    finally:
        crawler.close()
    assert status == OK, f'ajax comments failed with {status}'
    assert rows, 'a post reporting 评论数>0 must yield comment rows'
    for row in rows:
        assert row['评论内容'].strip()
        assert row['平台'] == 'weibo' and row['文章URL'] == link
    assert len(rows) <= 5


def test_xhs_note_comments_live(live_crawler):
    crawler = live_crawler('xiaohongshu')
    try:
        cards = crawler.search('三亚', target_count=3)
        note = next((c.get('笔记链接') or c.get('链接') or '') for c in cards if (c.get('笔记链接') or c.get('链接')))
        assert note, 'xhs search produced no clickable note'
        session = CommentSession(crawler.driver, log=print)
        rows, status = session.crawl_xiaohongshu(note, limit=5)
    finally:
        crawler.close()
    assert status in (OK, BLOCKED), f'unexpected adapter failure: {status}'
    if status == BLOCKED:
        pytest.skip('xhs served a login/risk wall for this session')
    assert rows, 'the probed note page had visible comments'
    assert all(re.sub(r'\s', '', r['评论内容']) for r in rows)


def test_zhihu_answer_comments_live(live_crawler):
    """zhihu needs the visible browser (content pages reject headless)."""
    crawler = live_crawler('zhihu', headless=False)
    try:
        answers = crawler.search('三亚', target_count=3)
        link = ''
        for row in answers:
            url = row.get('链接') or ''
            if '/answer/' in url:
                link = url
                break
        assert link, 'no answer-type result to test against'
        session = CommentSession(crawler.driver, log=print)
        rows, status = session.crawl_zhihu(link, limit=5)
    finally:
        crawler.close()
    if status == BLOCKED:
        # zhihu's risk control is session-sensitive; surface it, don't fake data.
        pytest.skip('zhihu served the risk-control page for the answer view')
    assert status == OK
    assert rows, 'the probed answers carried open comment panels with content'
    assert any(r['评论者'] for r in rows), 'at least one comment row should name its author'
