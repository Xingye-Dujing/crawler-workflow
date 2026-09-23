"""Live Bilibili hot-list crawl — 热门 and 排行榜 against the real endpoints.

The claim this tier exists to check is the one that made the mode worth having:
**a board answer already carries every figure** (``owner``/``stat``/``pubdate`` inside
each item, measured 2026-09), so the walk pays one request per page instead of one
request per row the way the keyword search must. An implementation that quietly
reused the search loop would still produce a correct table — and 50 requests for 50
rows — so the request count is asserted, not assumed.

Both boards are walked, because they page differently on purpose: 热门 is a feed
(page 2 is a disjoint set), 排行榜 answers the whole board in one reply (asking for a
second page would replay it).
"""

import pytest

from crawlers.video import bilibili_bvid

pytestmark = [pytest.mark.live_site, pytest.mark.enable_socket]


def _assert_board_rows(rows, minimum=5):
    assert len(rows) >= minimum, f'expected at least {minimum} rows from the board, got {len(rows)}'
    ids = [str(row['BV号']) for row in rows]
    assert len(set(ids)) == len(ids), f'the board replayed the same video: {ids}'
    for row in rows:
        assert bilibili_bvid(row['链接']) == row['BV号'], f'link and id disagree: {row}'
        assert (row['标题'] or '').strip() and (row['UP主'] or '').strip(), f'row without title/UP: {row}'
        # A board row whose numbers came from the item itself is the whole point of
        # this mode: a 0 here means the flattener did not find ``stat`` on the item.
        assert isinstance(row['播放数'], int) and row['播放数'] > 0, f'播放数 must be a real count: {row}'
        assert (row['发布时间'] or '').startswith('20'), f'发布时间 not formatted: {row}'


@pytest.mark.parametrize('board', ['popular', 'ranking'], ids=['热门', '排行榜'])
def test_a_board_answers_its_rows_without_a_request_per_row(live_crawler, board):
    crawler = live_crawler('bilibili')
    try:
        rows = crawler.hot(board, target_count=12)
        asked = list(crawler.requests)
    finally:
        crawler.close()
    _assert_board_rows(rows, minimum=8)
    endpoint = 'popular' if board == 'popular' else 'ranking'
    boards = [url for url in asked if 'web-interface' in url]
    assert boards and all(endpoint in url for url in boards), f'the board walked somewhere else: {boards}'
    assert not [url for url in boards if 'web-interface/view' in url], (
        f'a board must not resolve rows one by one: {boards}'
    )
    assert len(boards) <= 2, f'{board} spent {len(boards)} requests on {len(rows)} rows: {boards}'
    assert len([url for url in asked if url.startswith('https://www.bilibili.com/')]) == 1, (
        f'the board is read from one open page, not one per row: {asked}'
    )


def test_the_two_boards_are_different_lists(live_crawler):
    """If both hands answered the same items, one of them is a guess about the site.

    The row shape is shared on purpose (the same flattener), so what has to differ is
    the content and the paging cost.
    """
    crawler = live_crawler('bilibili')
    try:
        popular = crawler.hot('popular', target_count=10)
        crawler2 = live_crawler('bilibili')
        try:
            ranking = crawler2.hot('ranking', target_count=10)
        finally:
            crawler2.close()
    finally:
        crawler.close()
    popular_ids = {str(row['BV号']) for row in popular}
    ranking_ids = {str(row['BV号']) for row in ranking}
    assert popular_ids and ranking_ids
    assert len(popular_ids - ranking_ids) >= 3, f'the two boards are the same list: {popular_ids} vs {ranking_ids}'
    assert {'播放数', 'UP主', 'BV号', '链接'} <= set(popular[0]) and set(popular[0]) == set(ranking[0]), (
        'a board row must be the same row a search produces, whichever board it came from'
    )
