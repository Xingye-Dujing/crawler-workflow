"""The douyin LIVE program: real runs through the app, judged by what the console says.

Same shape as ``test_live_bilibili_workflow.py``: cells grouped by §3's dimensions, every
verdict graded on the console's own words, one audit row per crawl. The keyword-search mode
was removed (its feed is shallow and lazily throttled, measured at 26 then 16 distinct ids for
two keywords, neither reaching the site's own 「暂时没有更多了」), so this tier covers the three
douyin modes that page differently and work — **author**, **热榜**, **评论**.

What is platform-specific here is the **cost model**: author mode is ``collects='page_per_row'``
— a row costs one detail navigation (the grid card publishes one rounded figure and nothing
else) — so a 12-row ask buys ~18-20 page loads, and the funnel question is not "how many windows
did the walk touch" but **how many pages were opened and how many of them published nothing**.
Measured while writing this (``backend/test_dy_author.py`` → ``scratchpad/dy_*.json``), and
load-bearing for the assertions below:

* the author grid pages by its **own** scroll box (the window moves the footer's recommendations
  instead); the product's walk reached 40 distinct ids when asked for 40, against a profile that
  publishes 作品 145.
* 作者 used to come out of ``[data-e2e="related-video"]``, which this build no longer renders: every
  row stored an empty author and two zeros (§6 U42). B1 asserts the column is *read*, because a green
  tier that never looked at a blank column is how it stayed blank.

**Cost, stated because it is the user's account.** Each author cell is one profile page plus ~1.5
navigations per row; 热榜 is one page plus one request; 评论 scrolls one panel. Nothing here asks for
more than 40 rows. Run in batches, domestic network, never unattended (douyin is
``profile_recommended``: a copy of the login is a second device, so this tier crawls in the user's own
profile under ``CIXI_LIVE_USE_USER_PROFILE=1``, as §10 spells out)::

    # -k matches SUBSTRINGS: name the cells, not the group letter.
    .venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn" \\
        tests/live_site/test_live_douyin_workflow.py -k "b1 or c1" -p no:cacheprovider

**No case skips.** A refusal that names itself is asserted as what it is; the tier's skip allowance is
a closed list this file does not extend.
"""

from pathlib import Path

import live_acceptance as accept
import live_run_driver as driver
import live_run_harness as harness
import pytest

pytestmark = [
    pytest.mark.live_site,
    pytest.mark.live_cn,
    pytest.mark.enable_socket,
    pytest.mark.serial,
]

PLATFORM = 'douyin'

#: Where the repo root is from this file — the acceptance canvas is read from ``data/workflows`` by path.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: douyin's honest terminal lines on top of the shared ones. Keys, not sentences (§5's rule), and no
#: wrapper that merely restates how short the walk was: ``crawl.dy.target_reached`` /
#: ``crawl.dy.processed`` / ``crawl.dy.round`` are the crawl certifying itself, and ``crawl.dy.authorDone``
#: is a summary whose ``{works}`` slot gets asserted numerically in B1 instead of being allowed to excuse
#: anything.
DOUYIN_LEGIT_EXITS = harness.SHARED_EXITS + (
    'crawl.dy.wall',  # 验证码中间页 met mid-walk: the site's own answer, named by douyin's title check
    'crawl.dy.noMore',  # the list wrote its own 「暂时没有更多了」: the supply ended, said with its numbers
    'crawl.dy.authorNoWorks',  # the profile publishes 0 posts
    'crawl.dy.authorNoCards',  # the grid published nothing at all
    'crawl.dy.hotCapped',  # the board is the site's size, not our ceiling
    'crawl.dy.hotRefused',  # the board endpoint answered without a board
    'crawl.dy.hotWall',  # 验证码中间页 on the way in
)

#: Refusals raised **before the browser is pointed anywhere**, so the site was never asked and an empty
#: table is the only honest answer. §5 keeps the whitelist per mode because this one is a fact about the
#: *input*: a 作者 typed as a display name addresses nobody — douyin routes creators by an opaque
#: ``sec_uid`` only, so guessing would file somebody else's posts under the name the user asked for.
DY_AUTHOR_REFUSALS = ('crawl.dy.authorEmpty',)

#: Lines that describe this machine or this browser rather than the site's supply: a shortfall whose
#: only reason is one of these is still a finding (§6 attributes them, and W1 stays open until one
#: appears at a real address).
DOUYIN_LIES = (
    'crawl.dy.detailSlow',  # a detail page that never finished loading
    'crawl.dy.noPageRefused',  # the browser wrote its own error page: this machine, not the site
    'crawl.dy.authorNotMounted',  # the profile grid never mounted
)

#: Per-row refusals. They are **not** exits: ``detailEmpty`` / ``detailNoIdentity`` / ``detailWalled``
#: fire on a share of every walk (measured 2026-09-28: 15 of 39 openings on one keyword, all of them 图文
#: pages the site answers with the captcha interstitial), so a whitelist entry for one of them would
#: excuse any shortfall at all — a walk that could not re-open its list would still carry a stray line.
#: They are graded where they belong: B1 counts them per skipped page.
DY_ROW_REFUSALS = (
    'crawl.dy.detailEmpty',
    'crawl.dy.detailNoIdentity',
    'crawl.dy.detailWalled',
    'crawl.dy.detailSwapped',
)

#: The 12 columns a stored video row carries (author mode is the shape), the 8 a board row carries, and
#: the 10 the comment panel yields. The matrix holds no column names, so this tier is where they are
#: pinned against the live page.
POST_COLUMNS = (
    '标题',
    '正文',
    '作者',
    '粉丝数',
    '获赞数',
    '发布时间',
    '视频ID',
    '点赞数',
    '评论数',
    '收藏数',
    '转发数',
    '链接',
)
HOT_COLUMNS = ('排名', '标题', '热度', '观看数', '视频数', '讨论视频数', '发布时间', '链接')
COMMENT_COLUMNS = (
    '平台',
    '文章URL',
    '评论者',
    '评论者主页',
    '评论内容',
    '评论时间',
    '评论地区',
    '点赞数',
    '子回复数',
    '楼层',
)

#: The creator the author cells crawl, taken from the user's own acceptance canvas
#: (``data/workflows/测试：抖音.json``, node-10) so the live matrix and the flagship ask the same
#: profile of the site. The opaque ``sec_uid`` is the only address douyin's web app routes; a display
#: name is what a person types first and it addresses nobody (§6 U42's sibling refusal is B2).
AUTHOR_URL = 'https://www.douyin.com/user/MS4wLjABAAAA6xlnmUuddUZ7zQhYvd4TlOiLlEn2rQgY3Xjm-FAShgo'

#: A video the user pasted into his own canvas for the comment mode. Ages on its own schedule: if it
#: dies, D1's named refusal is the site's answer about *that link*, which is a different fact from a
#: comment engine that cannot read any panel.
COMMENT_URL = 'https://www.douyin.com/video/7653009893066067242'

#: Budgets are the product's own worst cases stacked, not "seems long": one page's first content may
#: take ``Config.PAGE_WAIT_TIMEOUT`` (300 s), a profile or a lane up to 900 s, and a douyin row costs
#: a whole detail navigation (~2-4 s plus the polite pause) — so a 12-row ask is minutes even when
#: nothing refuses. One number per cell, handed to :meth:`RunDriver.wait` as one wall-clock budget.
QUICK_TIMEOUT = 1500.0
DEEP_TIMEOUT = 2700.0
COMMENT_TIMEOUT = 3300.0


# ─── the driver, bound to douyin ────────────────────────────────────────


class LiveRun(driver.RunDriver):
    """douyin's binding of the shared run driver: platform word, budget, vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = QUICK_TIMEOUT
    # A session death named in the console is a WARN here, not a red: douyin answers a logged-in
    # profile intermittently with 验证码中间页 (§6, and the wall lives in the page title rather than
    # any URL). The designed path (``run.cookieExpired`` → partial → 继续) is proved by the shared
    # resume tier.
    NAMED_DEATH_OK = True

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return _vocabulary(mode, headless)


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines excuse a shortfall in this shape, and which are known machine events.

    ``headless`` is deliberately not branched: since #148 douyin honours 无头 verbatim and nothing about
    its supply is measured to depend on the window (zhihu's day-by-day throttle is that platform's
    exception, not a rule to copy). A second whitelist for a shape that was never measured would be a
    claim the next reader has to re-prove.
    """
    exits, liars = DOUYIN_LEGIT_EXITS, DOUYIN_LIES
    if mode == 'author':
        exits += DY_AUTHOR_REFUSALS
    elif mode == 'comments':
        # A comment crawl ends on the panel's own words; the list/board lines must not excuse it.
        exits, liars = (
            harness.SHARED_EXITS
            + (
                'comment.dyNone',  # the video reports N comments and no list opened
                'comment.dyNoPanel',  # the panel never rendered
                'comment.dyGone',  # the address was answered with a different video: dead, not walled
                'comment.dyShort',  # the panel ended short of the video's own count, with both numbers said
                'comment.status.blocked',  # the panel met a wall
                'comment.status.dead',  # the link is unreadable
                # 「评论已关闭」 is bilibili/X/YouTube's sentence — no douyin path prints it, and a dead
                # entry in a closed whitelist teaches the next reader that this case exists.
            ),
            (),
        )
    return exits, liars


# ─── builders ───────────────────────────────────────────────────────────


def author_canvas(target: int, author: str = AUTHOR_URL, *, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'author',
        settings=harness.run_settings('serial', headless),
        author=author,
        target_count=target,
        **overrides,
    )


def hot_canvas(target: int, *, headless=False, **overrides):
    """The board, read in a **throwaway** browser — on purpose, and measured.

    docs/crawler_notes.md §抖音热榜: this tool's own douyin profile is answered 验证码中间页 at ``/hot``,
    while a fresh browser with the cookies pasted in reads the board. So the cell must not inherit the
    run-as-the-user switch: ``use_profile=False`` is what the measurement says to ask for, and a board
    that came back walled would otherwise be re-run as a mystery about the cookie.
    """
    return harness.canvas_for(
        PLATFORM,
        'hot',
        settings=harness.run_settings('serial', headless, use_profile=False),
        target_count=target,
        **overrides,
    )


def comments_canvas(urls, *, limit=0, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'comments',
        settings=harness.run_settings('serial', headless),
        urls=urls,
        comment_limit=limit,
        **overrides,
    )


# ─── shape checks (a right count with the wrong columns is a red) ───────


def _assert_video_rows(rows, *, minimum: int, source: str = 'author') -> None:
    """The 12 columns, a real author, unique ids — and no play count, ever.

    ``作者`` is the column this round found blank on the live site (U42): the crawler read it out of a
    panel that this build stopped rendering, every row stored ``''``, and the nameless-row guard never
    fired because the publish time *was* there. Asserting it here is what stops that column rotting
    silently a second time. ``粉丝数``/``获赞数`` are asserted as **not fake numbers**: the video page
    does not publish them, so they must be empty rather than a 0 that reads as a count.
    """
    assert len(rows) >= minimum, f'expected {minimum} rows, got {len(rows)}'
    ids = [str(row.get('视频ID') or '') for row in rows]
    assert all(ids), f'a row with no 视频ID cannot be de-duplicated or resumed: {ids[:6]}'
    assert len(set(ids)) == len(ids), f'{len(ids)} rows, {len(set(ids))} distinct ids — one video filed twice'
    for row in rows:
        missing = [column for column in POST_COLUMNS if column not in row]
        assert not missing, f'a column the crawler promised is absent ({source}): {missing}'
        assert '播放数' not in row, 'the web player never shows plays; a 播放数 column would be an invented figure'
        assert str(row.get('正文') or '').strip() or str(row.get('标题') or '').strip(), f'a row with no text: {row}'
        assert str(row.get('作者') or '').strip(), f'作者 is blank again (U42 regressed): {row.get("视频ID")}'
        for counter in ('点赞数', '评论数', '收藏数', '转发数'):
            assert isinstance(row.get(counter), int), f'{counter} is not a number: {row.get(counter)!r}'
        for stat in ('粉丝数', '获赞数'):
            value = row.get(stat)
            assert value == '' or (isinstance(value, int) and value > 0), (
                f'{stat} says {value!r}: the page publishes no such figure, so 0 is a lie, not a zero'
            )
        link = str(row.get('链接') or '')
        assert link.endswith(str(row['视频ID'])), f'链接 and 视频ID disagree: {link}'


def _assert_comment_rows(rows, *, minimum: int) -> None:
    """Columns present, content non-empty, and 楼层 a running number rather than a per-page restart."""
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    floors = [int(row.get('楼层') or 0) for row in rows]
    assert floors == sorted(floors) and len(floors) == len(set(floors)), (
        f'楼层 is not a running number across the panel: {floors[:12]}'
    )
    for row in rows:
        missing = [column for column in COMMENT_COLUMNS if column not in row]
        assert not missing, f'a comment column the adapter promises is absent: {missing}'
        assert str(row.get('评论内容') or '').strip(), f'an empty comment row: {row}'
        assert isinstance(row.get('点赞数'), int), f'点赞数 is not a number: {row.get("点赞数")!r}'
        assert isinstance(row.get('子回复数'), int), (
            f'子回复数 is the trace that nested replies exist, so it must be counted, not blank: '
            f'{row.get("子回复数")!r}'
        )


# ─── B · 某作者的作品 (the grid pages in its own scroll box) ────────────


def test_b1_one_creator_s_list_is_walked_and_ties_his_own_count(client, app_module, monkeypatch):
    """B1 — an author's posts, with the profile's own 作品数 as the denominator (§11's 判据带分母).

    The grid's paging is the trap this platform already paid for once: a **window** scroll on a profile
    grows the footer's recommended videos, not the 作品 grid, so a walk that scrolled the window read
    "57 of 85 and nothing more" about a page that pages perfectly. The product jumps the grid's own
    box (measured: 20 → 39 → 57 → 85 anchors, and this pass reached 40 distinct ids when asked for 40,
    against a profile publishing 作品 145).

    ``crawl.dy.authorDone`` prints the profile's own figure, so the ceiling claim is arithmetic here
    rather than a whitelisted sentence: rows must equal the ask, and the ask must be reachable
    against the number the page itself published.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 12
    with LiveRun(
        client, app_module, author_canvas(asked), case_id='B1', mode='author', target=asked, timeout=DEEP_TIMEOUT
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        _assert_video_rows(rows, minimum=1, source='author')
        works = harness.numbers_from(run.rec.lines, 'crawl.dy.authorDone', 'works')
        assert works, f'the author walk never said what the profile publishes ({run.rec.lines[-6:]})'
        # The site's figure first, the grade second. ``works[-1] >= len(rows)`` alone can never fail
        # against a profile publishing hundreds, so the denominator is asked the other way too: if the
        # profile no longer publishes the ask, this cell's FULL grade is about a supply that is gone, and
        # it has to say so rather than convict the walk.
        assert works[-1] >= asked, (
            f'the profile publishes {works[-1]} posts, so asking {asked} tests the walk no more than the '
            f'catalogue; it delivered {len(rows)}'
        )
        answer = run.verdict()
        if len(rows) < asked:
            assert len(rows) == works[-1], (
                f'{len(rows)} rows from a profile publishing {works[-1]} with {asked} asked: the grid ran '
                'dry and nothing named it (SILENT_SHORT is the finding here, not the repair)'
            )
        assert answer['verdict'] == harness.FULL, (
            f'this profile publishes over a hundred posts, so {asked} rows must arrive: {answer}'
        )
        assert works[-1] >= len(rows), f'{len(rows)} rows against a profile publishing {works[-1]} posts'
        run.finish(answer=answer)


def test_b2_a_display_name_is_refused_because_it_addresses_nobody(client, app_module, monkeypatch):
    """B2 — 作者 is free text, so a name typed into it is refused, not guessed at.

    Douyin addresses a creator by an opaque ``sec_uid`` only, and ``/user/<numeric>`` is not a route:
    guessing would open *somebody's* profile and report their posts as the ones the user asked for —
    the douyin shape of 「不替用户挑一个看起来像的」. Refused before the browser is pointed anywhere.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        author_canvas(5, '泫九'),
        case_id='B2',
        mode='author',
        target=5,
        timeout=QUICK_TIMEOUT,
    ) as run:
        run.wait()
        assert harness.names_key(run.rec.text, 'crawl.dy.authorEmpty'), (
            f'a name that addresses nobody was not refused by name: {run.rec.lines[-8:]}'
        )
        assert run.rows() == 0, 'the unreadable author still produced a table'
        assert run.record['status'] == 'failed', run.record
        answer = run.verdict(rows=0)
        assert answer['verdict'] == harness.NAMED_SHORT, f'an unreadable author must name itself: {answer}'
        run.finish(answer=answer, rows=0, warn=True)


# ─── C · 热榜 (one page, one request, the site's own size) ──────────────


def test_c1_the_board_arrives_with_the_numbers_it_publishes(client, app_module, monkeypatch):
    """C1 — 40 topics, 8 columns, and the counters that are there really there.

    The board is one JSON read inside a loaded ``/hot`` document (§7's cost row: no per-row visit).
    观看数 is asserted as int-or-empty with at least one real figure because the payload's params are
    load-bearing: measured, stripping the URL down to six public parameters returns 48 rows whose
    ``view_count`` is null on every one — a *plausible* board with dead numbers.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, hot_canvas(40), case_id='C1', mode='hot', target=40) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the board holds ~51 topics, so 40 must arrive: {answer}'
        rows = run.preview('node-1')
        assert len(rows) == 40, rows[:2]
        for row in rows:
            missing = [column for column in HOT_COLUMNS if column not in row]
            assert not missing, f'a board column is absent: {missing}'
            assert not any(key in row for key in ('话题',)), f'the board row grew a column the payload lacks: {row}'
        views = [row.get('观看数') for row in rows]
        assert all(value == '' or isinstance(value, int) for value in views), f'观看数 is neither: {views[:5]}'
        assert any(isinstance(value, int) and value > 0 for value in views), (
            f'no row carries a real view count — the params that make the endpoint publish them are gone: {views[:6]}'
        )
        run.finish(answer=answer)


def test_c2_asking_past_the_board_names_the_board_size(client, app_module, monkeypatch):
    """C2 — an ask past the board is answered with the board's own number, not with silence.

    60 is a **floor, not an expectation**: measured today the board holds 51, and the day it grows past 60
    this cell must go green on a full table rather than red on a crawl that did nothing wrong. What is
    being graded is that a shortfall is *quantified by the site* — the cap line carries the length it
    measured and the table matches it — which is why no number here is asserted before the run says one.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 60
    with LiveRun(client, app_module, hot_canvas(asked), case_id='C2', mode='hot', target=asked) as run:
        run.wait()
        answer = run.verdict()
        rows = run.preview('node-1')
        capped = harness.numbers_from(run.rec.lines, 'crawl.dy.hotCapped', 'board')
        if len(rows) < asked:
            assert answer['verdict'] == harness.NAMED_SHORT, f'an over-long board ask must name the cap: {answer}'
            assert capped, f'the cap line did not carry the board length it measured: {answer["reasons"]}'
            assert len(rows) == capped[-1], f'{len(rows)} rows for a board reported as {capped[-1]} long'
        else:
            assert not capped, f'the board supplied {len(rows)} rows and the walk still claimed a cap: {capped}'
            assert answer['verdict'] == harness.FULL, answer
        run.finish(answer=answer)


# ─── D · 评论 (a panel that only the DOM can open) ──────────────────────


def test_d1_the_comment_panel_is_scrolled_and_every_row_is_a_real_comment(client, app_module, monkeypatch):
    """D1 — comments of one known video, read off the panel that signs its own endpoint.

    ``a_bogus`` is why this mode is DOM-only (it cannot be fetched like weibo's ``buildComments``), so
    what the cell can prove is the walk: rows carry the 10 columns, 楼层 runs across the whole panel
    rather than restarting per screen, and 子回复数 is a count — the column that says "nested replies
    exist and this table does not hold them", which is the honest trace zhihu's U29 taught.

    The ask is **40**, not the 15 a first draft used: measured, the panel mounts ~16 items on its first
    screen, so a 15-row ask breaks inside round one and the cell's 楼层 claim could not fail for the bug
    it names. 40 crosses screens, which is where the per-round numbering used to restart. The thread
    itself reports 3388 comments (probed today), so 40 is a capped ask the site can supply — and a walk
    that stops on the user's own 评论条数 must **not** complain about a gap, which is the other half of
    what this cell asserts.
    """
    harness.real_jar(monkeypatch, app_module)
    limit = 40
    with LiveRun(
        client,
        app_module,
        comments_canvas(COMMENT_URL, limit=limit),
        case_id='D1',
        mode='comments',
        target=limit,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        answer = run.verdict(rows=len(rows))
        assert len(rows) == limit, f'a capped ask on a 3388-comment thread must land on {limit}: {len(rows)}'
        _assert_comment_rows(rows, minimum=limit)
        assert [int(row['楼层']) for row in rows] == list(range(1, limit + 1)), (
            f'楼层 is not the running number of one thread: {[row["楼层"] for row in rows][:20]}'
        )
        assert not harness.names_key(run.rec.text, 'comment.dyShort'), (
            f"a walk that met the user's own ask complained about the thread anyway: {run.rec.lines[-6:]!r}"
        )
        assert answer['verdict'] == harness.FULL, f'{limit} rows were asked and the thread is huge: {answer}'
        run.finish(answer=answer, rows=len(rows))


def test_d2_a_panel_that_refused_is_named_per_link(client, app_module, monkeypatch):
    """D2 — two links where one is garbage: the dead one is named, the good one still crawls.

    A per-article status is the difference between 「这篇没有评论」 and 「这个链接读不出来」, and a batch
    that swallows the second as the first is how a user loses half his rows without seeing it. The
    garbage address is deliberately well-formed enough to reach the panel (a bad id, not a typo), so
    what is under test is the *reporting*, not the URL parser.
    """
    harness.real_jar(monkeypatch, app_module)
    dead = 'https://www.douyin.com/video/7000000000000000001'
    with LiveRun(
        client,
        app_module,
        comments_canvas(f'{dead}\n{COMMENT_URL}', limit=8),
        case_id='D2',
        mode='comments',
        target=16,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        urls = {str(row.get('文章URL') or '') for row in rows}
        assert dead not in urls, 'a video that cannot exist stored rows anyway'
        named = [
            key
            for key in ('comment.dyNone', 'comment.dyNoPanel', 'comment.dyGone', 'comment.status.dead')
            if harness.names_key(run.rec.text, key)
        ]
        assert named, f'the dead link came back empty and nothing named how: {run.rec.lines[-8:]}'
        # The live half of the batch is not allowed to be soft: this thread reports 3388 comments (probed
        # today), so its own 评论条数 of 8 is an ask the site can meet, and a crawl that lost it while
        # complaining about the dead link would be the half-table this cell exists to catch.
        assert len(rows) == 8, f'the readable link filed {len(rows)} of its 8-row ask: {run.rec.lines[-8:]!r}'
        assert {str(row.get('文章URL') or '') for row in rows} == {COMMENT_URL}, rows[:2]
        # The half that makes this cell worth its crawling cost: an unreadable link must not put the
        # session on trial. Measured before the fix, this same shape printed 「登录态疑似失效：COOKIE
        # 可能过期」 for the whole node and settled it partial — in the run that had just delivered eight
        # comments from the other link. A dead link costs its own row and nothing else.
        assert 'comment.status.dead' in named or 'comment.dyGone' in named, (
            f'the gone link was not reported as dead, so the batch will blame the cookie: {named} '
            f'{run.rec.lines[-8:]!r}'
        )
        assert not harness.names_key(run.rec.text, 'run.cookieExpired'), (
            f'a dead link was read as a dead session: {run.rec.lines[-8:]!r}'
        )
        _assert_comment_rows(rows, minimum=8)
        answer = run.verdict(rows=len(rows))
        assert answer['verdict'] == harness.NAMED_SHORT, (
            f'one link of two was unreadable, so the run must name that and not pass: {answer}'
        )
        run.finish(answer=answer, rows=len(rows), warn=True)


# ─── G · the platform's own axes: page_per_row cost, and the profile ─────


def test_g1_two_douyin_walks_in_parallel_both_arrive(client, app_module, monkeypatch):
    """G1 — douyin is *not* ``serial_only``, so a parallel canvas must deliver both tables.

    The axis that matters here is the opposite of weibo's: this platform's rows each cost a
    navigation, so two walks at once is the shape where a queue, a pool ceiling or a profile lock
    would silently drop one of them. ``use_profile=False`` is plan decision D3 (one profile, one
    browser) and it is also what the hot board measured: the throwaway device is the one douyin
    serves.

    The two lane switches are set **for this cell** and restored after it (they are global settings,
    not canvas settings — ``crawl_gate`` never reads the canvas block). Left at their defaults the
    queue would hold the lane for the whole crawl and 乙 would arrive strictly *after* 甲, which is a
    real behaviour worth a row in the ledger but not the overlap this cell claims to measure.
    """
    harness.real_jar(monkeypatch, app_module)
    leg = {'author': AUTHOR_URL, 'target_count': 5}
    canvas = harness.component_canvas(
        [
            {'platform': PLATFORM, 'mode': 'author', 'label': '甲', 'params': leg},
            {'platform': PLATFORM, 'mode': 'author', 'label': '乙', 'params': leg},
        ],
        settings=harness.run_settings('parallel', True, use_profile=False),
    )
    with (
        harness.lane_switches(queue=False, stagger=0),
        LiveRun(client, app_module, canvas, case_id='G1', mode='author', target=10, timeout=DEEP_TIMEOUT) as run,
    ):
        run.wait()
        record = run.refresh()
        left = run.component_verdict('甲', record, 'node-1', target=5, mode='author')
        right = run.component_verdict('乙', record, 'node-3', target=5, mode='author')
        run.audit(
            'G1.author.node-1',
            verdict=left['verdict'],
            reasons=left['reasons'],
            rows=harness.stored_rows(record, 'node-1'),
            target=5,
            mode='author',
            warn=left['verdict'] != harness.FULL,
        )
        run.audit(
            'G1.author.node-3',
            verdict=right['verdict'],
            reasons=right['reasons'],
            rows=harness.stored_rows(record, 'node-3'),
            target=5,
            mode='author',
            warn=right['verdict'] != harness.FULL,
        )
        assert left['verdict'] != harness.SILENT_SHORT, f'component 甲: {left}'
        assert right['verdict'] != harness.SILENT_SHORT, f'component 乙: {right}'
        # Arrival, stated two ways because the site is allowed to refuse one of two same-account walks
        # that leave at the same second (that is what the lane exists to space out, and this cell switches
        # the spacing off). An empty 乙 is a finding **only** when nothing named it; named, it is the
        # platform's answer and the row records which branch ran.
        if harness.stored_rows(record, 'node-3') == 0:
            walls = ('crawl.dy.wall', 'crawl.loginWall', 'crawl.riskBlocked')
            walled = [key for key in walls if harness.names_key(run.rec.text, key)]
            assert walled, f'the second workflow filed nothing and nothing named why: {left} / {right}'
        for node in ('node-1', 'node-3'):
            rows = run.preview(node)
            if rows:
                _assert_video_rows(rows, minimum=len(rows), source='parallel')
        kept = harness.stored_rows(record, 'node-1') + harness.stored_rows(record, 'node-3')
        run.finish(
            answer=left,
            rows=kept,
            warn=harness.NAMED_SHORT in (left['verdict'], right['verdict']),
        )


# ─── H · 用户自己的画布（§11 第 8 步：旗舰不是合成用例，是他点 Run 那张）─────

#: His douyin canvas, saved by hand: one creator, the board and one thread's comments — three source
#: nodes, each wired to an 输出 node (the comments leg also feeds a 情感分析 pair). The keyword-search
#: legs were removed with the mode. Read as saved: §9's 2026-09-27 snapshot said the 热榜/评论 nodes
#: carried ``recrawl:false`` and the acceptance copy had to flip it; as of 2026-09-28 every source node
#: in this file says ``true``, so this cell changes nothing about it. If that ever goes red, the file
#: changed under us — which is information, not a broken test.
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：抖音.json'

#: Three components, one of them ``page_per_row``: 50 author rows is ~75 detail navigations on this
#: platform (measured ~1.5 openings per row), the board is one page, and the comment leg is unbounded.
#: The budget is the author cell's worst case twice plus the comment cell's own.
ACCEPTANCE_TIMEOUT = 2 * DEEP_TIMEOUT + COMMENT_TIMEOUT


def _llm_block() -> dict:
    """The AI transport block his panel would send, with the model read off the local daemon.

    One chain of his canvas ends in an LLM node, and ``app.py`` refuses such a run *before it starts* unless
    the request names a model (``api.needOllamaModel``) — the choice lives in the browser's settings, not in
    the saved canvas, so a harness that posts the payload has to state it. Read from the daemon rather than
    pasted: a hard-coded tag breaks the day he pulls a different model, and the red would blame the canvas
    for the test's own staleness. Nothing here edits his file to drop the node — that would be the
    acceptance run quietly not accepting what he saved.
    """
    from analyzers.llm_client import list_ollama_models
    from config import Config

    models = list_ollama_models(Config.OLLAMA_HOST)
    assert models, f'the local daemon at {Config.OLLAMA_HOST} lists no chat model, so the AI leg cannot run'
    return {'provider': 'ollama', 'model': str(models[0]), 'ollama_host': Config.OLLAMA_HOST}


def test_h1_the_shipped_canvas_runs_and_every_leg_accounts_for_itself(client, app_module, monkeypatch):
    """H1 — 测试：抖音.json at his parameters, three legs, each accounting for itself.

    This is the step the other cells only approximate: the canvas is his, the parameters are his, and the
    question is whether a run he starts from the panel leaves behind a table, a record and an export that
    agree — per component. ``audit_components`` writes one ledger row per leg and derives the case's index
    row from those three, so a case cannot certify itself FULL by hand. The one thing the copy changes is
    which nodes are switched on (see below); no ask, keyword or link was touched.

    The hot leg is the one this platform answers differently (docs/crawler_notes.md §抖音热榜): the profile
    this run uses is met with 验证码中间页 at ``/hot`` while a throwaway device reads the board, and this
    cell runs **his** settings rather than quietly switching. That is a NAMED_SHORT with ``hotWall``, not a
    silent zero — which is exactly the distinction the whole tier exists to keep.
    """
    harness.real_jar(monkeypatch, app_module)
    opened = accept.workflow_file(ACCEPTANCE_FILE)
    # Measured on the first attempt at this cell (2026-09-28): **as saved, some chains sit out.** A
    # workflow whose name node is off is not an effective component (``execution_state['skipped_workflow_labels']``
    # → ``run.skippedWorkflows``), so the flagship leg of the platform's eight steps has to crawl the three
    # source nodes he wired, at his parameters. Hence the deep copy (plan decision D5: the file on disk is
    # what he wrote; the variant is what the test wanted), and the empty skip list is asserted rather than
    # assumed, because a switched-off leg that quietly stayed off would look like a pass.
    workflow = accept.all_enabled(opened)
    _on, off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    assert len(found) == 3, f'this case is written against the three source nodes he saved: {found}'
    assert not off, f'the all-enabled copy still holds a switched-off node: {off}'
    exported_before = accept.export_dir_entries()
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H1',
        mode='mixed',
        target=sum(part['ask'] for part in found),
        timeout=ACCEPTANCE_TIMEOUT,
        llm=_llm_block(),
    ) as run:
        run.wait()
        run.assert_l3()
        # The copy's own promise, checked against the console rather than the dict: a leg that stayed
        # switched off would shorten this run by one crawl and still print a green-looking row.
        assert not harness.names_key(run.rec.text, 'run.skippedWorkflows'), (
            f'the all-enabled copy still sat a leg out: {run.rec.lines[:6]!r}'
        )
        records = accept.records_by_node(client, found)
        silent, kept, asked, answers = accept.audit_components(
            run,
            records=records,
            case_id='H1',
            found=found,
            grade=lambda part, record, console: run.component_verdict(
                part['label'], record, part['source'], target=part['ask'], mode=part['mode']
            ),
        )
        assert not silent, f'components under target with no honest reason named: {silent}'
        accept.assert_canvas_exports(found, accept.new_exports(exported_before), records)
        # A serial canvas is one record per workflow *as it is reached* (AGENTS), so three legs are three rows —
        # and every one of them has to name the component it crawled, or the panel lists a run nobody can
        # match back to a node on the canvas.
        assert int(run.record.get('wf_count') or 0) == len(found), (
            f'three components, and the row says wf_count={run.record.get("wf_count")}: {run.record}'
        )
        for part in found:
            own = run.component_verdict(
                part['label'], records[part['label']], part['source'], target=part['ask'], mode=part['mode']
            )
            if part['mode'] == 'author':
                rows = run.preview(part['source'], workflow_name=part['label'])
                _assert_video_rows(rows, minimum=1, source=f'H1 {part["label"]}')
                assert len(rows) == own['rows'], f'{part["label"]}: preview {len(rows)} vs ledger {own["rows"]}'
            if part['mode'] == 'comments':
                rows = run.preview(part['source'], workflow_name=part['label'])
                if rows:
                    _assert_comment_rows(rows, minimum=1)
        summary = accept.summary_row(run, case_id='H1', found=found, answers=answers, kept=kept, asked=asked)
        run.finish(rows=kept, target=asked, warn=summary != harness.FULL)
