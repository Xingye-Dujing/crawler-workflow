"""Live YouTube crawl — real Chrome, real youtube.com, both browser modes.

The tier runs the claims the design rests on, against the site rather than
against a fixture:

* the crawl is JSON, so one navigation must produce rows — and the same rows in
  a headless window as in a visible one (measured identical, which is why
  YouTube, unlike douyin, is allowed to run headless at all);
* the per-row ``player`` round trip is what turns a rounded "1.2M views" label
  into an integer and is the only source of 点赞数;
* the comment walk must page: one round is 20 comments, so 40 is the cheapest
  proof the continuation cursor was followed;
* the author mode must re-enter the same channel through a link it produced,
  because the id it reads off the page is what every later request is addressed
  by.

Assertions are behavioural where the live site can vary: a keyword that returns
fewer videos than asked, or a video whose author turned comments off, is a real
answer and must not be reported as a broken crawler — so those read as
"at least one row carried X" rather than as fixed counts.
"""

import pytest

from crawlers.comments import BLOCKED, DEAD, OK, CommentSession
from crawlers.youtube import video_id_of

#: ``live_os`` with X: the overseas half of the live tier, run while the VPN is up.
pytestmark = [pytest.mark.live_site, pytest.mark.live_os, pytest.mark.enable_socket]

KEYWORD = '人工智能'
#: A channel with public uploads and an open comment section on most of them.
CHANNEL = '@NASA'


def _assert_real_rows(rows, minimum=2):
    assert len(rows) >= minimum, f'expected at least {minimum} rows, got {len(rows)}'
    for row in rows:
        assert row['链接'].startswith('https://www.youtube.com/watch?v='), row['链接']
        assert video_id_of(row['链接']) == row['视频ID'], 'the link must carry the id the row was built from'
        assert (row['标题'] or '').strip(), f'row without a title: {row}'
        assert (row['作者'] or '').strip(), f'row without an author: {row}'
        assert isinstance(row['播放数'], int) and row['播放数'] > 0, f'播放数 must be a real count: {row}'
    ids = {row['视频ID'] for row in rows}
    assert len(ids) == len(rows), 'rows must be distinct videos (dedupe identity is the id)'


@pytest.mark.parametrize('headless', [True, False], ids=['headless', 'visible'])
def test_search_rows_carry_the_figures_only_the_player_answers(live_crawler, headless):
    crawler = live_crawler('youtube', headless=headless)
    try:
        rows = crawler.search(KEYWORD, target_count=4)
    finally:
        crawler.close()
    _assert_real_rows(rows, minimum=2)
    # Neither of these is in the search card at all: 点赞数 never is, and the
    # card's 播放数 is a rounded label, so a crawl that skipped the player round
    # would leave 点赞数 empty across every row.
    assert any(row['点赞数'] > 0 for row in rows), 'no row carried 点赞数 — the per-row detail round trip failed'
    assert any(row['时长秒'] > 0 for row in rows), 'no row carried a duration in seconds'
    assert any(row['正文'] for row in rows), 'no row carried the description'


@pytest.mark.live_quick
def test_search_without_facts_is_the_fast_path_and_still_returns_rows(live_crawler):
    crawler = live_crawler('youtube')
    try:
        rows = crawler.search(KEYWORD, target_count=4, with_facts=False)
    finally:
        crawler.close()
    _assert_real_rows(rows, minimum=2)
    assert all(row['点赞数'] == 0 for row in rows), 'the fast path must not have paid for detail calls'


def test_one_search_reaches_past_a_single_round(live_crawler):
    """A keyword round answers ~10 rows, so 16 is the cheapest proof the
    continuation cursor is followed rather than the first page being re-read."""
    crawler = live_crawler('youtube')
    try:
        rows = crawler.search(KEYWORD, target_count=16, with_facts=False)
    finally:
        crawler.close()
    assert len(rows) >= 16, f'only {len(rows)} rows — the pager did not advance past the first round'
    assert len({row['视频ID'] for row in rows}) == len(rows), 'two rounds handed back the same video'


def test_the_channel_mode_reads_the_id_the_pager_is_addressed_by(live_crawler):
    crawler = live_crawler('youtube')
    try:
        rows = crawler.author(CHANNEL, target_count=6)
    finally:
        crawler.close()
    _assert_real_rows(rows, minimum=4)
    assert len({row['频道ID'] for row in rows}) == 1, 'one channel was asked for and several answered'
    assert rows[0]['频道ID'].startswith('UC'), f'no channel id was read off the page: {rows[0]}'
    assert all(row['作者'] for row in rows), 'every row must name the creator it came from'


def test_a_channel_can_be_reached_by_the_link_it_produced(live_crawler):
    """The author field accepts a pasted channel link, so the id the rows carry
    has to be usable as the address of the next crawl."""
    first_crawler = live_crawler('youtube')
    try:
        first = first_crawler.author(CHANNEL, target_count=1)
    finally:
        first_crawler.close()
    assert first, 'the channel answered with no upload at all'
    channel_id = first[0]['频道ID']
    second_crawler = live_crawler('youtube')
    try:
        again = second_crawler.author(f'https://www.youtube.com/channel/{channel_id}', target_count=2)
    finally:
        second_crawler.close()
    assert len(again) >= 2, f're-opening the channel by its own id answered {len(again)} rows'
    assert {row['频道ID'] for row in again} == {channel_id}, 'the id in the link is not the id on the rows'


def test_comments_page_past_the_first_screen(live_crawler):
    """A paging proof that does not depend on which video the search returned.

    One innertube round is 20 comments (measured), so a count above 20 can only
    come from following the cursor. Whether any *single* video has that many
    comments is not something the crawler can promise in advance — a 人工智能
    search returns a different mix every day, and a 12-comment video cannot
    demonstrate a walk no matter how correct the code is. So the tier reads the
    three most-watched results and requires the proof of at least one of them,
    while the row invariants are asserted for every video that was read.
    """
    finder = live_crawler('youtube')
    try:
        rows = finder.search(KEYWORD, target_count=6, with_facts=False)
    finally:
        finder.close()
    assert rows, 'no video to read comments on was found live'
    ranked = sorted(rows, key=lambda row: int(row['播放数'] or 0), reverse=True)[:3]
    holder = live_crawler('youtube')
    counts = {}
    try:
        session = CommentSession(holder.driver, log=print, nap=lambda s: None)
        for row in ranked:
            link = row['链接']
            comments, status = session.crawl_youtube(link, limit=45)
            if status == DEAD:
                pytest.fail(f'the link the crawler built itself is not readable: {link}')
            if status == BLOCKED:
                pytest.fail(f'YouTube refused the comment walk (risk control) on {link}')
            assert status == OK, f'comment crawl ended as {status} on {link}'
            counts[link] = len(comments)
            for comment in comments:
                assert comment['平台'] == 'youtube'
                assert (comment['评论内容'] or '').strip(), f'comment row without text: {comment}'
                assert comment['评论ID'], f'comment row without an id (the dedupe key): {comment}'
                assert comment['文章URL'] == link, 'a comment must be filed under the video it came from'
            assert len({c['评论ID'] for c in comments}) == len(comments), f'two rows share a comment id on {link}'
    finally:
        holder.close()
    assert max(counts.values()) > 20, f'no video paged past one round: {counts}'
    assert any(count > 0 for count in counts.values()), f'every video answered with nothing: {counts}'


def test_one_videos_comments_are_unique_and_numbered(live_crawler):
    """The row-level contract, on whichever video the search happened to return."""
    finder = live_crawler('youtube')
    try:
        rows = finder.search(KEYWORD, target_count=2, with_facts=False)
        link = rows[0]['链接'] if rows else ''
    finally:
        finder.close()
    holder = live_crawler('youtube')
    try:
        session = CommentSession(holder.driver, log=print, nap=lambda s: None)
        comments, status = session.crawl_youtube(link, limit=8)
    finally:
        holder.close()
    assert status == OK and comments, f'{link} ended as {status} with {len(comments)} rows'
    assert all(int(row['楼层']) >= 1 for row in comments), 'every comment is on a floor'
    assert any(row['评论者'].startswith('@') for row in comments), 'a YouTube author is an @handle'


def test_a_link_with_no_video_is_refused_rather_than_empty(live_crawler):
    crawler = live_crawler('youtube')
    try:
        assert crawler.get_detail('https://www.youtube.com/@NASA') is None
        row = crawler.get_detail('https://www.youtube.com/watch?v=00000000000')
    finally:
        crawler.close()
    assert row is None, 'a video id that does not exist must not produce a blank row'
