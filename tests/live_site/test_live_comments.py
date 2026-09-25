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

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]


def _fresh_post_with_comments(weibo_windowed) -> str:
    """A weibo post from the session's one windowed search that reports 评论数 > 0.

    Read off the shared crawl rather than searched again: the search endpoint is the
    request this account gets refused by, and the two cases want the same rows.
    """
    for row in weibo_windowed['rows']:
        if int(row.get('评论数') or 0) > 0 and 'weibo.com/' in (row.get('链接') or ''):
            return str(row['链接'])
    return ''


@pytest.mark.parametrize(
    'headless',
    [pytest.param(True, marks=pytest.mark.live_quick, id='headless'), pytest.param(False, id='visible')],
)
def test_weibo_comments_live(live_crawler, weibo_windowed, headless):
    link = _fresh_post_with_comments(weibo_windowed)
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
        # Asserted rather than skipped, in the shape this file's douyin case already uses: a wall
        # the session names is the site's honest answer, but a *skipped* case would also hide a
        # blocked crawl that filed rows anyway — and this tier's closure run allows no skipped case.
        assert not rows, f'a blocked crawl still returned {len(rows)} rows as if it succeeded'
        return
    assert rows, 'the probed note page had visible comments'
    assert all(re.sub(r'\s', '', r['评论内容']) for r in rows)


def test_zhihu_answer_comments_live(live_crawler):
    """zhihu needs the visible browser (content pages reject headless).

    The answer is picked by the comment count its own search card reports, exactly as
    ``_fetch`` does for weibo two tests up — NOT by "the first ``/answer/`` link on the page".
    An answer with zero comments is a legal thing for the site to hand back (this file's own
    contract says so), so pointing the probe at one produced an ``OK`` with no rows whose only
    honest reading was "the panel never opened": measured 2026-09-26, when the case went red on
    a sample that simply had nothing to collect.
    """
    crawler = live_crawler('zhihu', headless=False)
    try:
        answers = crawler.search('三亚', target_count=3)
        candidates = [row for row in answers if '/answer/' in str(row.get('链接') or '')]
        assert candidates, 'no answer-type result to test against'
        reported = [int(row.get('评论数') or 0) for row in candidates]
        assert max(reported) > 0, (
            f'none of the {len(candidates)} live answers reported a single comment {reported}: either the '
            'keyword stopped returning discussion or the 评论数 column stopped being read — '
            'a probe aimed at an empty answer proves nothing about the comment walk'
        )
        link = str(candidates[reported.index(max(reported))]['链接'])
        session = CommentSession(crawler.driver, log=print)
        rows, status = session.crawl_zhihu(link, limit=5)
    finally:
        crawler.close()
    if status == BLOCKED:
        # Named and accepted, but asserted rather than skipped: a skip would also hide a
        # blocked crawl that filed rows anyway, and this tier's closure run allows no skipped case.
        assert not rows, f'a blocked crawl still returned {len(rows)} rows as if it succeeded'
        return
    assert status == OK
    assert rows, 'the probed answers carried open comment panels with content'
    assert any(r['评论者'] for r in rows), 'at least one comment row should name its author'
