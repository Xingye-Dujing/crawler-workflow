"""Live douyin author crawl — the 某作者的作品 mode against a real profile page.

Visible window only (headless is answered 验证码中间页 on every navigation), and no
skip branch in this file: turning a refusal into a skip is how a mode stops being
tested while the suite stays green.

The creator is **discovered during this run**: the search walk already opens a video
page, and that page carries ``a[href*="/user/"]`` — so the ``sec_uid`` is read off
the live site rather than pasted from a note. A written-down token rots, and a walk
that finds nothing on a dead profile still looks like a passing test.

What is pinned is the measurement the handler was written against: the 作品 grid
pages off its own scrollable container (a window scroll moves the footer's
recommended videos instead, which a count-based walk reads as an exhausted list), and
every number still comes from opening the video — the grid's card carries one bare
figure that measures equal to the **like** count, so a row that reported it as 播放数
would be a wrong figure with a plausible column name.
"""

import re

import pytest

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket]

KEYWORD = '风景'
_VIDEO = re.compile(r'^https://www\.douyin\.com/video/\d{15,20}$')
#: Discovery is a live search plus a video page; the tests below ask about the same
#: creator, so the token is kept for the module. (A module-scoped *fixture* cannot
#: do this: ``live_crawler`` is function-scoped and closes every crawler it made.)
_FOUND: dict = {}


def _discover_author(live_crawler) -> str:
    """A ``sec_uid`` taken off a video page the search actually opened."""
    if 'sec' in _FOUND:
        return str(_FOUND['sec'])
    crawler = live_crawler('douyin', headless=False)
    try:
        rows = crawler.search(KEYWORD, target_count=2)
        assert rows, f'the search crawl produced nothing for {KEYWORD}, so there is no author to ask about'
        found = crawler.driver.find_elements('css selector', 'a[href*="/user/"]')
        anchors = [str(element.get_attribute('href') or '') for element in found]
        tokens = [m.group(1) for href in anchors if (m := re.search(r'/user/([A-Za-z0-9_.-]{30,})', href))]
        assert tokens, f'no author link on the video page: {anchors[:3]}'
        _FOUND['sec'] = tokens[0]
        return tokens[0]
    finally:
        crawler.close()


def _profile_nickname(live_crawler, sec: str) -> str:
    """The name the profile header publishes, or ``''`` when it never mounts.

    This node used to be read with a single unwaited ``find_element``, and on a session
    douyin is refusing it isn't there at all — which surfaced as a raw
    ``NoSuchElementException`` out of the driver rather than as anything about the crawl.
    Two things follow. The read is now bounded by the same kind of poll the crawler uses
    everywhere, and an absent header is an absent anchor: the identity claim below does
    not depend on a decorative block, because every row already carries the name of the
    person whose video page was opened.
    """
    crawler = live_crawler('douyin', headless=False)
    try:
        crawler.open(f'https://www.douyin.com/user/{sec}')
        if not crawler.wait_for_element('[data-e2e="user-info"]', timeout=8):
            return ''
        text = crawler._node_text(crawler._element_or_none('[data-e2e="user-info"]'))
        return (str(text or '').splitlines() or [''])[0].strip()
    finally:
        crawler.close()


def test_one_creators_own_posts_are_collected(live_crawler):
    sec = _discover_author(live_crawler)
    nickname = _profile_nickname(live_crawler, sec)
    crawler = live_crawler('douyin', headless=False)
    try:
        rows = crawler.author(sec, target_count=5)
    finally:
        crawler.close()
    assert len(rows) >= 3, f'expected at least 3 posts from the grid, got {len(rows)}'
    ids = [str(row['视频ID']) for row in rows]
    assert len(set(ids)) == len(ids), f'the grid replayed the same videos: {ids}'
    for row in rows:
        assert _VIDEO.match(str(row['链接'] or '')), f'row without an openable address: {row}'
        assert str(row['链接']).endswith(str(row['视频ID'])), f'link and id disagree: {row}'
        assert isinstance(row['点赞数'], int) and row['点赞数'] > 0, f'点赞数 must be a real count: {row}'
        assert '播放数' not in row, 'the card figure is the like count; a 播放数 column would be false data'
        assert (row['标题'] or '').strip(), f'row without a title: {row}'
    assert any((row['发布时间'] or '').startswith('20') for row in rows), 'no row carried a formatted 发布时间'
    # The identity anchor is the rows themselves, not the header: one profile page cannot
    # legitimately hold two creators' videos, and the header node may be missing on a
    # session the site is refusing (see ``_profile_nickname``). The nickname, when the page
    # does publish it, is then checked *against* that anchor rather than being the only
    # evidence there is.
    named = [str(row.get('作者') or '') for row in rows]
    distinct = {name for name in named if name}
    assert len(distinct) <= 1, f'one profile grid, several author names: {named}'
    if nickname and distinct:
        # The name a card carries is read off the video page's related-panel, and a
        # session the site is throttling never renders that panel (measured 2026-09-25:
        # rows complete but nameless beside a header that DID name itself). An empty
        # name is not evidence of a different creator — the check below fires the moment
        # the site publishes one, and the dedupe/anchor checks above already refuse a
        # grid that mixes creators.
        assert distinct == {nickname}, f'the grid named {sorted(distinct)} beside the profile header {nickname!r}'


def test_the_grid_is_walked_on_one_navigation(live_crawler):
    """One profile open, then scrolls. A handler that re-navigated per screen would
    pay a full page load for every batch of 18 rows, and the user would watch the
    same page reload for the whole run."""
    sec = _discover_author(live_crawler)
    crawler = live_crawler('douyin', headless=False)
    navigated = []
    original = crawler.open

    def record(url, *args, **kwargs):
        navigated.append(str(url))
        return original(url, *args, **kwargs)

    crawler.open = record
    try:
        rows = crawler.author(sec, target_count=4)
    finally:
        crawler.close()
    spaces = [url for url in navigated if '/user/' in url]
    assert rows, 'nothing was collected, so the navigation count proves nothing'
    assert len(spaces) == 1, f'the profile was opened {len(spaces)} times: {spaces}'
    video_pages = [url for url in navigated if '/video/' in url]
    assert len(video_pages) == len(rows), f'one navigation per row is the cost model: {len(video_pages)} vs {len(rows)}'


def test_something_that_is_not_a_profile_is_refused(live_crawler):
    crawler = live_crawler('douyin', headless=False)
    try:
        with pytest.raises(ValueError):
            crawler.author('泫九', target_count=2)
        with pytest.raises(ValueError):
            crawler.author('   ', target_count=2)
    finally:
        crawler.close()
