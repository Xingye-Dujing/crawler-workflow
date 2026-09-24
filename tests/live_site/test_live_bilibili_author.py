"""Live Bilibili author crawl — the 某作者的作品 mode against a real space page.

The UP is **discovered during this run**: the search walk already carries ``UP主ID``,
so picking the most-played creator among a few results is both a live target and one
that has more than a handful of uploads (a space with two videos cannot show the
scroll pager doing its job). A written-down mid rots, and a dead space returning zero
rows still looks like a passing test.

What is being proven is the two things the mode was built on: the space is opened
**once** and paged by scrolling (its own API needs a per-request signature, which is
why the list is read off the page), and every number still comes from
``x/web-interface/view`` — a row from this mode must be indistinguishable from a
search row except for belonging to one creator.
"""

import pytest

from crawlers.video import bilibili_bvid, bilibili_mid

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

KEYWORD = '人工智能'


def _discover_up(live_crawler):
    """The mid of a popular creator the search page itself named."""
    crawler = live_crawler('bilibili')
    try:
        rows = crawler.search(KEYWORD, target_count=4)
        assert rows, f'the search crawl produced nothing for {KEYWORD}, so there is no UP to ask about'
        best = max(rows, key=lambda row: int(row.get('播放数') or 0))
        mid = str(best.get('UP主ID') or '')
        assert mid.isdigit(), f'the chosen row carries no numeric UP主ID: {best}'
        return mid
    finally:
        crawler.close()


def test_one_ups_own_uploads_are_collected(live_crawler):
    mid = _discover_up(live_crawler)
    crawler = live_crawler('bilibili')
    try:
        rows = crawler.author(mid, target_count=5)
        visited = crawler.driver.current_url
    finally:
        crawler.close()
    assert len(rows) >= 4, f'expected at least 4 uploads from {mid}, got {len(rows)}'
    assert bilibili_mid(visited) == mid and 'space.bilibili.com' in visited, f'the walk left the UP space: {visited}'
    ids = {str(row['BV号']) for row in rows}
    assert len(ids) == len(rows), f'the scroll replayed the same videos: {sorted(ids)}'
    for row in rows:
        assert str(row['UP主ID']) == mid, f'a video from another UP in {mid} space: {row}'
        assert bilibili_bvid(row['链接']) == row['BV号'], f'row whose link and id disagree: {row}'
        assert (row['标题'] or '').strip() and (row['UP主'] or '').strip()
        # The card's own figure is a rounded 万-label; an integer here is the proof
        # the detail endpoint answered for this row.
        assert isinstance(row['播放数'], int) and row['播放数'] > 0, f'播放数 must be a real count: {row}'
        assert (row['发布时间'] or '').startswith('20'), f'发布时间 not formatted: {row}'


def test_a_space_cursor_names_the_up_it_walked(live_crawler):
    """The cursor is a position *inside* one creator's list, so a resumed run knows
    whose page to reopen — a cursor without the mid would resume on the wrong UP."""
    mid = _discover_up(live_crawler)
    crawler = live_crawler('bilibili')
    try:
        crawler.author(mid, target_count=2)
        position = dict(crawler.position)
    finally:
        crawler.close()
    assert position.get('mid') == mid, f'cursor without the UP: {position}'
    assert position.get('scanned', 0) >= 2 and position.get('done', 0) >= 1


def test_something_that_is_not_an_up_is_refused(live_crawler):
    crawler = live_crawler('bilibili')
    try:
        with pytest.raises(ValueError):
            crawler.author('漫士沉思录', target_count=2)
        with pytest.raises(ValueError):
            crawler.author('   ', target_count=2)
    finally:
        crawler.close()
