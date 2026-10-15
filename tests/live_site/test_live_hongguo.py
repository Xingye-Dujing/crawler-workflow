"""Live 红果短剧 (hongguoduanju.com): the four boards, read from the pages the site serves.

No cookie, no account, no session: measured 2026-10, all four boards answer a fresh
throwaway browser, which is why this file needs no saved login and why the panel holds no
cookie row for the platform. The board's contents are the site's to decide (20 works a page,
five pages measured on every board, ranks continuing across pages), so what is asserted is
the *shape* the payload promises:

* one work per ``seriesId``, ranks unique and in the board's own order;
* a figure the card carries is a real expanded number (8 134 would mean the parser stopped at
  the ``8134万`` label's first token) while a column the payload leaves empty stays blank —
  never a fabricated 0;
* 集数 is the length of the payload's episode list, the count the detail page itself prints
  (measured 222 == 222 and 69 == 69); the DOM's player window holds 25 links, which is why
  this crawl never counts what is on screen;
* paging follows the address the site itself named, and a resume opens the page its cursor
  names instead of paying for page 1 again.
"""

import pytest

from crawlers import hongguo

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

BOARD = hongguo.DEFAULT_BOARD
BOARD_URL = f'{hongguo.BASE}/rank/hot-drama'


def _assert_work_rows(rows, board):
    """Shape only: the site owns every number below, this owns what a row must be."""
    ids = [row['作品ID'] for row in rows]
    assert len(set(ids)) == len(ids), f'{board} repeated a work: {ids}'
    ranks = [row['排名'] for row in rows]
    assert ranks == sorted(ranks), f'{board} 排名 is not the board order: {ranks}'
    assert len(set(ranks)) == len(ranks) and ranks[0] == 1, f'{board} 排名 is not a position: {ranks}'
    for row in rows:
        assert str(row['作品名']).strip(), row
        assert row['作品ID'], row
        assert row['链接'].startswith(f'{hongguo.BASE}/detail?series_id='), row
        assert row['播放链接'].startswith(f'{hongguo.BASE}/player/'), row
        assert row['封面'].startswith('http'), row
        assert row['评分'] == '' or (isinstance(row['评分'], float) and 0 < row['评分'] <= 10), row
        assert row['集数'] == '' or (isinstance(row['集数'], int) and row['集数'] >= 0), row
        for column in ('热度', '收藏', '点赞'):
            assert row[column] == '' or (isinstance(row[column], int) and row[column] > 0), (column, row)


@pytest.mark.live_quick
def test_the_hot_board_answers_one_page_load_with_its_own_numbers(live_crawler):
    crawler = live_crawler('hongguo')
    try:
        rows = crawler.hot(target_count=20, board=BOARD)
        asked = list(crawler.requests)
    finally:
        crawler.close()
    _assert_work_rows(rows, BOARD)
    assert len(rows) == 20, f'the first page holds 20 works (measured); it gave {len(rows)}'
    assert asked == [BOARD_URL], f'page 1 is the bare URL and the target ended the walk: {asked}'
    heats = [row['热度'] for row in rows]
    assert sum(1 for heat in heats if isinstance(heat, int)) >= len(rows) // 2, (
        f'the cards publish a 万热度 label; only {sum(1 for h in heats if isinstance(h, int))} rows read one'
    )
    episodes = [row['集数'] for row in rows]
    assert sum(1 for count in episodes if isinstance(count, int) and count > 1) >= len(rows) // 2, (
        f'episodeVids is the episode count and a 短剧 has more than one; got {episodes}'
    )
    assert sum(1 for row in rows if row['评分']) >= 1, 'the cards publish 评分; none came back'


def test_paging_follows_the_address_the_site_itself_named(live_crawler):
    """45 rows is page 1, page 2 and the first five of page 3 — asked at the addresses page 1
    and page 2 pointed at, and ending on the target rather than a site-attested end."""
    slug = hongguo.BOARDS['hot_comic_drama'][0]
    base = f'{hongguo.BASE}/rank/{slug}'
    crawler = live_crawler('hongguo')
    try:
        rows = crawler.hot(target_count=45, board='hot_comic_drama')
        asked = list(crawler.requests)
    finally:
        crawler.close()
    _assert_work_rows(rows, 'hot_comic_drama')
    assert len(rows) == 45, f'the target, not the site, ended this walk: {len(rows)}'
    assert asked == [base, f'{base}?page=2', f'{base}?page=3'], asked
    assert [row['排名'] for row in rows] == list(range(1, 46)), 'ranks continue across pages (measured)'


def test_every_board_answers_from_its_own_route(live_crawler):
    for board, (slug, _label) in hongguo.BOARDS.items():
        crawler = live_crawler('hongguo')
        try:
            rows = crawler.hot(target_count=20, board=board)
            asked = list(crawler.requests)
        finally:
            live_crawler.release(crawler)
        _assert_work_rows(rows, board)
        assert len(rows) == 20, f'{board} gave {len(rows)} rows'
        assert asked == [f'{hongguo.BASE}/rank/{slug}'], f'{board} asked {asked}'


def test_a_resume_starts_at_the_page_its_cursor_names(live_crawler):
    """The core value, measured on the site: page 1's twenty works are already stored, so the
    resumed crawl asks page 2 alone and adds only what was missing."""
    first = live_crawler('hongguo')
    try:
        stored = first.hot(target_count=20, board=BOARD)
    finally:
        live_crawler.release(first)
    assert len(stored) == 20, f'the first attempt gave {len(stored)} rows, so the resume below proves nothing'
    second = live_crawler('hongguo')
    try:
        second.seed(stored)
        rows = second.hot(target_count=25, board=BOARD, resume={'page': 2, 'page_url': f'{BOARD_URL}?page=2'})
        asked = list(second.requests)
    finally:
        second.close()
    _assert_work_rows(rows, BOARD)
    assert asked == [f'{BOARD_URL}?page=2'], f'a resume must not re-pay for page 1: {asked}'
    assert len(rows) == 25, f'a resume adds what it was missing, not a fresh table: {len(rows)}'
    assert [row['排名'] for row in rows][20:] == [21, 22, 23, 24, 25], 'page 2 continues where page 1 ended'
