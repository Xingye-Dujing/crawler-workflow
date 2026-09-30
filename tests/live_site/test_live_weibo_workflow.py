"""The weibo LIVE program: real runs through the app, judged by what the console says.

Mirrors ``tests/live_site/test_live_zhihu_workflow.py`` cell-for-cell where the shapes exist, and
substitutes the two weibo-only axes §7 records: **``serial_only``** (every weibo crawl takes 真排队
whatever the 排队/错峰 switch says, because the site bounces one account firing several deep requests at
once) and the **time-window** parameter, which is what 「采不满」 actually looks like on this platform —
one hourly URL per window, thousands of windows in a week's range.

**What this round's measurements changed about the assertions** (``docs/crawler_notes.md`` 微博第 0 步;
§6 U10-U12 / U19 / U31-U33). Three of them are not background, they are cells:

* **A4** — an empty window must yield **zero** rows. Measured: a window that matches nothing still prints
  「抱歉，未找到相关结果」 *beside five unrelated posts* under the same ``#pl_feedlist_index``, with no
  attribute or container that separates them, and the old card-first ordering filed those five as keyword
  hits. That is not a short crawl; it is a table of content the user never asked for.
* **A5** — an hourly window has **a pager**: page 1 gave 9 cards, page 2 gave 6 with no mid in common,
  while ``.page-info`` prints nothing there. ``_may_page`` used to refuse paging inside a window on the
  theory that an hour is narrow — that silently dropped ~40% of every window, the largest under-collection
  this round found here.
* **A3** — D9's promise, asserted positively: 「目标先满、窗口未轮完即收工」 is normal, so the walk may pay
  for the windows it needed and **none** of the ones after it.

**How a short crawl is judged** is the harness's ``classify_verdict``: FULL (the number arrived),
NAMED_SHORT (it did not, and the console carries the *site's* reason), SILENT_SHORT (red, everywhere).
weibo keeps two lists, and the second is the interesting one:

* :data:`WEIBO_LIES` — lines that report *this walk* while reading like a site answer. A timeout names a
  machine event, never an empty window, so it may not excuse a shortfall.
* Absent from :data:`WEIBO_LEGIT_EXITS` on purpose: ``crawl.weibo.target_reached``. A walk that reached its
  number printing that it reached its number is a crawl certifying its own FULL.

**One search burst per pass, not one per cell.** This account is refused by the *second* search of a
session (``docs/crawler_notes.md`` 微博的墙是间歇风控 and the ``weibo_windowed`` fixture's own history), so
the cells that need post links with comments read them from the tier's session-scoped shared crawl instead
of opening their own browser — the same reason the author mode's "discovery" step was moved onto it. Cells
that crawl *through the app* (every A/B/C/D/E/G cell below) are the run being measured, not a discovery ask.

**Cost, stated because it is the user's account.** One navigation per window and per page (~1-3 s
measured, plus the crawler's own polite pause); a comment crawl is one ``statuses/show`` plus ~20 rows per
``buildComments`` page, so D4 — which asks for **all** of the largest thread the shared search found — is
the deepest walk here at ``declared / 20`` navigations (a 749-comment thread is ~37). A4's one-day range is
the expensive posts cell by construction (24 hourly windows, all empty, ~2-4 min) because proving 「an empty
window stores nothing」 needs a whole empty range. Nothing here asks for a week. Run it in batches, on the
domestic network, never unattended::

    # -k matches SUBSTRINGS of the test name, so ``-k "A or C"`` — which reads like "groups A and C" —
    # selects all 20 cells here (every name contains an 'a' or a 'c'). Name the cells.
    .venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn" \\
        tests/live_site/test_live_weibo_workflow.py -k "a1 or a2 or a3" -p no:cacheprovider
    # then: -k "a4 or a5 or a6" | -k "b1 or b2 or b3" | -k "c1 or c2 or c3"
    #       -k "d1 or d2" | -k "d3 or d4 or d5" | -k "e1" | -k "g1 or g2"
    # One weibo *search burst* per pass is the discipline (see below), so the A batches and the D batch
    # should not share a session unless the shared fixture is what is being tested.

**The H group is here too** (H1 his canvas with its window narrowed per D9, H2 the same file 串行), built on
the shared :mod:`tests.live_acceptance` rather than on a second copy of zhihu's. H3 is declined with a
stated reason at the bottom of this file: on a ``serial_only`` platform the browser pool has nothing to
narrow, so that cell would re-run H1's four crawls to assert what G1/G2 already do.

**No case skips.** A refusal that names itself is the site's answer and is asserted; the tier's skip
allowance is a closed list this file does not extend.
"""

import copy
import re
from datetime import date, timedelta
from pathlib import Path

import live_acceptance as accept
import live_run_driver as driver
import live_run_harness as harness
import pytest

pytestmark = [
    pytest.mark.live_site,
    pytest.mark.live_cn,
    pytest.mark.enable_socket,
    # This file presses Run; the worker puts a tee over ``sys.stdout`` for its whole life, so two of
    # these side by side would interleave consoles (see the ``serial`` marker).
    pytest.mark.serial,
]

PLATFORM = 'weibo'

#: weibo's own honest terminal lines, on top of the ones every platform shares. Keys, not sentences:
#: a reworded message keeps matching, a renamed one fails visibly instead of turning a pass into a red.
#:
#: **Nothing generic is on this list**, and §5 is why. Its posts/author row licenses 「真 no_more（列表
#: 末尾标记在场）」 — the *site's own* marker, which on this platform is the 「未找到相关结果」 plate and a
#: page that rendered no cards. The closing lines (``crawl.weibo.walk_done``, ``crawl.weibo.authorDone``)
#: and their ``{reason}`` slot (``crawl.stopReason.end`` / ``no_new`` / ``no_cards`` / ``empty_page``) are
#: deliberately absent, because each is printed by our code as a *summary of its own loop*:
#: ``reason='end'`` is weibo.py's fallback for "the window walk finished", which a pager that read one page
#: too few produces just as surely as a range that really ran dry. Whitelisting it would make every
#: posts/author ``!= SILENT_SHORT`` assertion unfalsifiable — the cell would read its own arithmetic back.
#: ``crawl.stopReason.unreachable`` is absent for the opposite reason: AGENTS is explicit that a browser
#: which never fetched a page is not a refusal by the site, so it may not excuse a shortfall either.
WEIBO_LEGIT_EXITS = harness.SHARED_EXITS + (
    'crawl.weibo.no_result',  # the site printed its own 「未找到相关结果」 plate
    'crawl.weibo.page_empty',  # a page that really rendered no cards (see :meth:`_harvest`'s pair)
    'crawl.weibo.hotCapped',  # the board is the site's size, not our ceiling
    'crawl.weibo.hotRefused',  # the board endpoint refused; loud, so never a silent zero
    'crawl.weibo.authorNoPosts',  # 200 + empty list is a fact about an account
)

#: The four ways the author walk refuses — each of them a **raise**, never an empty table (AGENTS: a
#: refusal raises, or the node settles DONE over nothing). ``mymblog`` is measured to answer ``200`` with
#: real posts in one session and a ``<h2>403 Forbidden</h2>`` edge body in the next with the same walk and
#: the same logged-in navigation (``docs/crawler_notes.md``), so a named 403 is this mode's ordinary
#: answer and belongs in its exits — while the shape it must never take is zero rows that report 完成.
#: ``authorEmpty`` is the fourth: the 作者 field is free text the matrix cannot type, so a value that is
#: neither a UID nor a profile URL is refused *before* the browser is asked, rather than guessed at —
#: the site answers an unreadable uid with the home timeline, and a wrong-but-plausible table is worse
#: than a red line.
AUTHOR_REFUSALS = (
    'crawl.weibo.authorRefused',
    'crawl.weibo.authorWall',
    'crawl.weibo.authorMirror',
    'crawl.weibo.authorEmpty',
)

#: Lines that report the walk while reading like an answer from the site. A short crawl whose only reason
#: is one of these grades SILENT_SHORT, with the line quoted into the audit row: the message is the bug.
#:
#: Both were reworded on 2026-09-28 after measurement, and both stay here *because* they are about us:
#: ``page_timeout`` used to print 「页面加载超时，可能无内容」 — a claim about the window's content that the
#: code cannot see; it now reports the seconds it waited and whether the navigation settled, which is
#: honest and still proves nothing about what the hour held. ``page_gave_up`` is this browser's own
#: breaker ("two pages delivered nothing, I will not spend a third budget"), which is a statement about
#: the machine, never about the site.
WEIBO_LIES = (
    'crawl.weibo.page_timeout',
    'crawl.weibo.page_gave_up',
)

#: A comment crawl's honest endings — comment words only. The search lines above must not leak in: a
#: feed canvas puts a search node and a comment node in ONE workflow, and 「该时间段无搜索结果」 is nobody's
#: excuse for a comment table that stored nothing and said nothing.
#:
#: Two keys that look like they belong here are left out, and §5's warning about dead whitelist entries is
#: the reason: ``crawl_weibo`` holds no wall verdict, so it can only ever return ``OK`` or ``DEAD``, and
#: 「评论已关闭」 is the bilibili/X/YouTube adapters' sentence. A weibo thread that really does answer with
#: a closed-comment body therefore arrives as an unnamed short table — red, correctly, and §6 gets the row.
COMMENT_EXITS = harness.SHARED_EXITS + (
    'comment.weiboShowFailed',  # statuses/show answered nothing: dead cookie or limited
    'comment.weiboReplay',  # the cursor moved on, over rows this table already held
    'comment.weiboShort',  # the cursor ran out and the thread's own number says more exists
    'comment.weiboFetchDied',  # a comment page failed to fetch: named, with its gap and its cursor
    'comment.status.dead',  # the per-article summary of the DEAD return above
)

#: The subset of :data:`COMMENT_EXITS` that names **which article** it is talking about — the two lines
#: that carry the URL (``comment.weiboShowFailed`` directly, ``comment.status.dead`` inside the
#: per-article summary). D2 needs one of these per un-served link: ``comment.weiboShort`` and
#: ``comment.weiboFetchDied`` state facts about *a* thread without saying which, so they can excuse one
#: link's absence only in the row that already names it.
COMMENT_NAMED = ('comment.weiboShowFailed', 'comment.status.dead')

#: The walls a *headless* crawl may answer with. This account gets bounced by burst, not by window shape
#: (docs 微博的墙是间歇风控), so a named wall is the site's answer here.
HEADLESS_REFUSALS = ('crawl.riskBlocked', 'crawl.loginWall')

#: The lines that make a **failed run** an honest one. H1/H2 assert per component that a record which did
#: not settle ``completed`` said why somewhere in *its own* slice — a run going red is fine, a run going
#: red that the console cannot explain is the thing the user cannot act on. These are the weibo shapes of
#: that: the dead-session line, the two page verdicts, the comment link that died, and the three ways the
#: author endpoint refuses.
WEIBO_NAMED_DEATHS = (
    'run.cookieExpired',
    'crawl.loginWall',
    'crawl.riskBlocked',
    'comment.weiboShowFailed',
    'crawl.weibo.authorRefused',
    'crawl.weibo.authorWall',
    'crawl.weibo.authorMirror',
    'crawl.weibo.hotRefused',
    'crawl.weibo.hotNoHost',
)

#: The 14 columns ``WeiboCrawler.search``/``author`` emit for one post, the 5 the board emits, and the 10
#: the comment adapter emits. The crawl matrix carries no column names, so this tier is where they are
#: pinned against the live page.
POST_COLUMNS = (
    '发布者',
    '发布时间',
    '发布来源',
    '正文',
    '转发数',
    '评论数',
    '点赞数',
    '图片链接',
    '图片数',
    '话题',
    '视频数',
    '用户链接',
    '链接',
    '微博ID',
)
HOT_COLUMNS = ('排名', '标题', '话题', '热度', '链接')
COMMENT_COLUMNS = (
    '平台',
    '文章URL',
    '评论者',
    '评论者主页',
    '评论内容',
    '评论时间',
    '点赞数',
    '楼层',
    '父楼层',
    '评论ID',
)

#: The RFC-822 residue weibo's JSON stamps into ``created_at`` (``'Sun Jul 26 09:49:46 +0800 2026'``).
#: Measured in every payload this round read; ``engine/times.py`` normalises it now, so a cell that lets
#: this through is the fabricated-column regression, in 评论时间 specifically — the column whose sibling in
#: the author path had been normalised for months while the comment path shipped the English stamp.
RFC822_RESIDUE = re.compile(r'\+0800\b|^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s')

#: Distinct abundant keywords, one per cell that crawls: the dedupe ledger is scoped by node fingerprint,
#: so two cells sharing a word on the same canvas shape would let one cell's paid rows excuse the other's
#: shortness. ``MISSING_KEY`` is the one that must never match anything (A4).
KEYWORDS = {
    'A1': '人工智能',
    'A2': '北京 天气',
    'A3': '人工智能 应用',
    'A5': '演唱会',
    # Evergreen and volume-stable: A6 asks for exactly 25 rows over one day, and a keyword whose supply
    # depends on the news cycle (高考 was the first pick) makes 「the site had them」 the thing that fails.
    'A6': '旅游',
    'E1': '机器人',
    'G': ('新能源', '储能'),
    'G2': ('新能源 基地', '储能 电站'),
}
MISSING_KEY = 'zzqqxx-无此关键词-9f3c2a'

#: Budgets are the product's own worst cases stacked, not "seems long": one page's first content may now
#: take ``Config.PAGE_WAIT_TIMEOUT`` (300 s) on a slow network, a profile or a lane up to 900 s, and a
#: comment crawl walks ``buildComments`` pages at ~0.8 s plus one fetch each. One number per cell is one
#: wall-clock budget (:meth:`live_run_driver.RunDriver.wait` hands the console watch's leftovers to the
#: thread watch instead of paying both in full).
QUICK_TIMEOUT = 1500.0
DEEP_TIMEOUT = 2700.0
COMMENT_TIMEOUT = 3300.0

#: How long E1 waits for the first stored row before pressing 停止: a browser start, one page's first
#: content, and the polite pause between windows.
STOP_DEADLINE = 1200.0

#: A window the site's own pager can fill: measured 9 cards on page 1 + 6 on page 2 for one recent hour of
#: an abundant keyword. This ask is unreachable from a single rendered page, so A5 fails if page 2 is never
#: opened — which is exactly the ``_may_page`` regression.
WINDOW_PAGING_TARGET = 14

#: The widest first screen this platform has been measured serving one hourly window (9 cards, page 2
#: added 6 with no mid in common). A5 leans on it: it is the only fact that turns 「14 行」 into
#: 「page 2 was opened」, and a cell that assumed it silently would be the kind of internally
#: consistent short table this campaign keeps finding.
MEASURED_FIRST_SCREEN_CARDS = 9

#: The shared search's own target (the ``weibo_windowed`` fixture crawls 三亚 over a week for the cells that
#: need post links), and the comment counts it must beat to be usable as a comment target.
#:
#: The shared search's own target (the ``weibo_windowed`` fixture crawls 三亚 over a week for the cells that
#: need post links). ``PROBE_MIN_COMMENTS`` is only 「有评论可读」 — D1 needs two such threads and picks the
#: two richest, while D3/D4/D5 take the single richest one via :func:`_richest_link` and scale their asks to
#: what it reports. Any *threshold* here would be a number the site is not obliged to fit, which is the
#: mistake each of those two drafts has already paid for with a live re-run.
PROBE_MIN_COMMENTS = 1

#: The account the author cells crawl, as a profile URL — the form the panel takes and the uid the user's
#: own acceptance canvas names (``data/workflows/测试：微博.json``, node-2), so the live matrix and the
#: flagship ask the same profile of the site. ``AUTHOR_UID`` is the number that URL must resolve to, and
#: the anchor every stored row is checked against: the crawler refuses the whole walk unless its first
#: row's ``user.id`` equals it, because a home-timeline mirror answers ``200`` with the same envelope.
AUTHOR_URL = 'https://weibo.com/u/6122597700'
AUTHOR_UID = '6122597700'

#: Measured 2026-09-24: page 1 of ``mymblog`` hands back 28 rows and every later page 20, with fresh ids
#: each time. An ask above that therefore cannot be filled without ``page=N`` advancing — which is what B2
#: buys with its rows, rather than asserting a page count the site could answer by luck. (The page-1
#: surplus is itself a fact to pin, not something to normalise to 20.)
MEASURED_AUTHOR_PAGE_ONE = 28
AUTHOR_PAGING_TARGET = MEASURED_AUTHOR_PAGE_ONE + 12


# ─── the driver, bound to weibo ─────────────────────────────────────────


class LiveRun(driver.RunDriver):
    """weibo's binding of the shared run driver: platform word, budget, vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = QUICK_TIMEOUT
    # Measured, and the reason this file does not treat a named session death as a code defect:
    # ``docs/crawler_notes.md`` 微博的墙是间歇风控 — the same walk on the same cookie is answered a
    # passport page by the *second* burst of a session, and the account carries the flag, not the page.
    # The designed path (``run.cookieExpired`` → node ``partial`` → run ``failed`` → 继续) still has to
    # name itself, so the row lands as WARN with the death in it; E1/E2 are where the death path's
    # correctness is actually proved.
    NAMED_DEATH_OK = True

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return _vocabulary(mode, headless)


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines excuse a shortfall in this shape, and which are known liars.

    Split by mode because weibo's modes end differently (a window walk runs out of windows, a board is
    ~51 topics, a thread is capped by its own ``total_number``), and by shape because a named login wall
    is the site's honest answer to a headless ask on this account while an empty windowed crawl is the
    code's problem.
    """
    exits, liars = {
        'posts': (WEIBO_LEGIT_EXITS, WEIBO_LIES),
        'author': (WEIBO_LEGIT_EXITS + AUTHOR_REFUSALS, WEIBO_LIES),
        'hot': (WEIBO_LEGIT_EXITS, ()),
        'comments': (COMMENT_EXITS, ()),
    }.get(str(mode or ''), (WEIBO_LEGIT_EXITS, WEIBO_LIES))
    if headless:
        # A named wall is the site's answer to a headless ask on this account, so it joins the
        # *exits*. The liars are untouched: neither of them is a refusal, and a browser that timed out
        # while headless is still this machine's event, whatever the shape of the window.
        exits = tuple(exits) + HEADLESS_REFUSALS
    return exits, liars


# ─── builders ───────────────────────────────────────────────────────────


def posts_canvas(target: int, keyword: str, *, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'posts',
        settings=harness.run_settings('serial', headless),
        keyword=keyword,
        target_count=target,
        **overrides,
    )


def range_canvas(target: int, keyword: str, *, headless=False, days: int = 1, ends_at=None):
    """A date-range search: the site's hourly-window walk, bounded to ``days`` days.

    The range is built to end *yesterday* rather than today: the product walks hour windows, and today's
    unfinished hours are the part of a range most likely to answer empty for a reason that has nothing to
    do with the crawl. ``days=1`` is 24 windows — the smallest range that still has windows to stop short
    of, which is what A3 and A4 both assert about, and the only one-day shape the crawler accepts, since
    ``_build_urls`` refuses a range whose end is not after its start.

    ``days`` counts *whole* days back from that bound, so ``days=2`` is 48 windows: the walk's window
    count is what E1 cuts in the middle of, and a builder that off-by-ones it makes 停止 cheaper than the
    case claims to be.
    """
    end = ends_at or (date.today() - timedelta(days=1))
    start = end - timedelta(days=max(1, int(days)))
    return posts_canvas(target, keyword, headless=headless, start_time=f'{start}', end_time=f'{end}')


def hot_canvas(target: int, *, headless=False, use_profile=None, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'hot',
        settings=harness.run_settings('serial', headless, use_profile=use_profile),
        target_count=target,
        **overrides,
    )


def author_canvas(target: int, author: str = AUTHOR_URL, *, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'author',
        settings=harness.run_settings('serial', headless),
        author=author,
        target_count=target,
        **overrides,
    )


def comments_canvas(urls, *, limit=0, headless=False, **overrides):
    pasted = urls if isinstance(urls, str) else '\n'.join(urls)
    return harness.canvas_for(
        PLATFORM,
        'comments',
        settings=harness.run_settings('serial', headless),
        urls=pasted,
        comment_limit=limit,
        **overrides,
    )


# ─── shape checks (a right count with the wrong columns is a red) ───────


def _assert_post_rows(rows, *, minimum: int) -> None:
    """Columns, distinct addresses, a body, numeric counters. Shape, not only a count."""
    assert len(rows) >= minimum, f'expected {minimum} rows, got {len(rows)}'
    links = [str(row.get('链接') or '') for row in rows]
    assert all(links), f'a row without its own address cannot be resumed or deduped: {links}'
    assert len(set(links)) == len(links), 'rows repeat a link, so the ledger identity (链接) is broken'
    for row in rows:
        missing = [column for column in POST_COLUMNS if column not in row]
        assert not missing, f'a column the crawler promised is absent: {missing}'
        body = str(row.get('正文') or '').strip()
        # A card with no text is legitimate only when it is something: a photo-only or video-only post
        # carries its content in 图片数/视频数. Demanding 正文 unconditionally would convict a real card —
        # and U34 (a repost/merged card has never been sampled) is exactly the shape that must not be
        # papered over by an assertion that quietly passes on it.
        media = int(row.get('图片数') or 0) + int(row.get('视频数') or 0)
        assert body or media, f'a row carrying neither text nor media is not a post: {row}'
        for counter in ('转发数', '评论数', '点赞数'):
            assert isinstance(row.get(counter), int), f'{counter} is not a number: {row.get(counter)!r}'


def _assert_author_rows(rows, *, uid: str) -> None:
    """The author table is the search table, and it is *this account's* — column set and ownership.

    ``_author_row`` mirrors ``_scrape_card``'s keys on purpose (author and keyword crawls of one platform
    feed the same cleaning and chart nodes), so the shape check is the search one. The two author-only
    facts come from the measurement: the crawler refuses the whole walk unless the first row's ``user.id``
    equals the requested uid, because a home-timeline mirror answers ``200`` with the same envelope — so
    every stored row's 用户链接 must carry it; and a row has ``pic_ids`` but no ``pics[]``, so 图片链接 is
    left empty rather than assembled from a guessed CDN pattern, and a non-empty one here means someone
    invented URLs.
    """
    _assert_post_rows(rows, minimum=len(rows))
    for row in rows:
        home = str(row.get('用户链接') or '')
        assert uid in home, f'作者模式 filed a post whose owner is not {uid}: {home!r}'
        assert str(row.get('图片链接') or '') == '', (
            f'图片链接 was built from a guessed CDN pattern: {row["图片链接"]!r}'
        )


def _assert_comment_rows(rows, *, minimum: int) -> None:
    """The four columns this round found fabricated, asserted as *read*.

    Measured against the payload (``scratchpad/weibo_*.json``): the like counter's key is ``like_counts``
    while the adapter read ``like_count`` (every row stored 0); the site prints its own ``floor_number``
    while the adapter counted per page (a 119-row table held six rows called 1); ``created_at`` arrives as
    ``'Sun Jul 26 09:49:46 +0800 2026'`` and was stored verbatim; and the row's ``user`` object carries
    both ``profile_url`` and ``profile_image_url`` — the column named 评论者主页 got the avatar.

    ``父楼层`` is deliberately *not* required to be non-empty: the one child per parent that the endpoint
    hands inline is the only nested reply this session can get at all (U33), so a run may legitimately
    return none of them.
    """
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    # ``楼层`` is a whole-*thread* number (measured: a 30-comment thread's top-level rows carry floors
    # 1..30), so uniqueness is a property *inside one article*. D1 and D2 store two and four threads in
    # one table, where two rows called 「1」 is the site numbering two different posts — and the failure
    # text would have accused the adapter of the exact per-page-index defect this round removed.
    by_thread: dict = {}
    for row in rows:
        if str(row.get('楼层') or '').strip():
            by_thread.setdefault(str(row.get('文章URL') or ''), []).append(int(row['楼层']))
    assert by_thread, f"no row carries the site's floor number: {rows[:3]}"
    for thread, floors in by_thread.items():
        assert len(floors) == len(set(floors)), (
            f'楼层 repeats inside one thread ({thread}), so it is still a page index: {sorted(floors)}'
        )
    for row in rows:
        missing = [column for column in COMMENT_COLUMNS if column not in row]
        assert not missing, f'a comment column the adapter promises is absent: {missing}'
        assert str(row.get('评论内容') or '').strip(), f'an empty comment row: {row}'
        home = str(row.get('评论者主页') or '')
        assert home == '' or '/u/' in home, f'评论者主页 is not a home page: {home!r}'
        assert not home.lower().endswith(('.jpg', '.png', '.gif', '.webp')), f'评论者主页 holds an image: {home!r}'
        when = str(row.get('评论时间') or '')
        assert not RFC822_RESIDUE.search(when), f'评论时间 was never normalised: {when!r}'


# ─── the shared search's own rows (one burst per pass) ──────────────────


def _commented_links(windowed: dict, *, need: int, min_comments: int) -> list[tuple[str, int]]:
    """``(link, 评论数)`` pairs from the pass's single shared search — never a second ask.

    The card's own 评论数 cell is the denominator the comment cells grade against, so a D cell learns what
    it may expect from the site rather than from a URL someone pasted into a fixture. An empty hand here is
    the shared crawl's refusal, and saying so with the flag is the honest red (the fixture documents why
    retrying would only ask a refused endpoint again).
    """
    rows = windowed.get('rows') or []
    digits = re.compile(r'\d+')
    scored = []
    for row in rows:
        link = str(row.get('链接') or '')
        count = digits.search(str(row.get('评论数') or ''))
        if link and count and int(count.group()) >= min_comments:
            scored.append((link, int(count.group())))
    scored.sort(key=lambda pair: -pair[1])
    assert len(scored) >= need, (
        f'the shared search produced {len(rows)} rows, of which {len(scored)} report >= {min_comments} '
        f'comments (need {need}); login_wall={windowed.get("login_wall")!r} — there is no denominator to '
        'crawl comments against, and asking again would be the second burst this fixture exists to avoid'
    )
    return scored[:need]


def _richest_link(windowed: dict) -> tuple[str, int]:
    """The thread this pass's shared search found with the **most** comments, and its number.

    No threshold, on purpose. The first draft asked this fixture for a post with ``>= 12`` comments and
    went red on a day when the hottest of its 12 posts carried single digits — the same mistake as D1's
    fixed ``5 × links`` ask, in the other direction: **the site's supply is not required to fit a number
    this file picked**. So the cells read what the richest available thread reports and scale their own
    asks to it, which keeps each of them a real assertion (see each cell for what it can and cannot
    exercise at that size), and the audit row says which branch ran.

    A search with no commented post at all is still the honest red: there is no denominator to grade
    against, and the flag goes into the message rather than into a skip.
    """
    rows = windowed.get('rows') or []
    digits = re.compile(r'\d+')
    best = ('', 0)
    for row in rows:
        link = str(row.get('链接') or '')
        found = digits.search(str(row.get('评论数') or ''))
        count = int(found.group()) if found else 0
        if link and count > best[1]:
            best = (link, count)
    assert best[1] > 0, (
        f'the shared search returned {len(rows)} rows and not one of them reports a single comment '
        f'(login_wall={windowed.get("login_wall")!r}); the comment cells have no denominator, and asking '
        'the search endpoint again would be the second burst this fixture exists to prevent'
    )
    return best


# ─── A · 关键词搜索 (posts) ─────────────────────────────────────────────


def test_a1_windowed_serial_search_delivers_ten_rows_with_bodies(client, app_module, monkeypatch):
    """A1 — the ordinary case end to end: ten rows, fourteen columns, and a closing sentence.

    The closing line is part of the assertion, not decoration: U10 measured that this walk used to end
    with no summary at all, so a run that filed the right table while narrating only per-window lines
    still fails here.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, posts_canvas(10, KEYWORDS['A1']), case_id='A1', mode='posts', target=10) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'a windowed search on a rich keyword must fill: {answer}'
        assert run.rows() == 10, run.record
        _assert_post_rows(run.preview('node-1'), minimum=10)
        walked, offered = _walked_windows(run)
        assert walked > 0 and offered > 0, f'the walk never said how far it got: {run.rec.lines[-6:]}'
        run.finish(answer=answer)


def _walked_windows(run, lines: list | None = None) -> tuple[int, int]:
    """``(windows reached, windows offered)`` from the walk's own closing line.

    *lines* scopes the reading to one component's slice: a shipped canvas holds two searches in one run,
    and the second's closing line is not the first's answer.
    """
    own = run.rec.lines if lines is None else lines
    walked = harness.numbers_from(own, 'crawl.weibo.walk_done', 'walked')
    total = harness.numbers_from(own, 'crawl.weibo.walk_done', 'total')
    return (walked[-1] if walked else -1), (total[-1] if total else -1)


def _visited_windows(run, lines: list | None = None) -> list[str]:
    """The hourly URLs this walk opened a page for, in the order it opened them.

    ``crawl.weibo.visiting`` is printed once per navigation into a window, so this list is the crawl's
    own record of what it paid for — A3 counts its length against the windows the walk says exist, and
    E1/E2 compare the *last* entry of the interrupted run with the *first* of the resume, which is the
    only console-side proof that 继续 re-opened the window 停止 was inside rather than the next one.
    *lines* scopes the reading to one component's slice, as in :func:`_walked_windows`.
    """
    own = run.rec.lines if lines is None else lines
    return harness.slots_from(own, 'crawl.weibo.visiting', 'url')


def _paid_windows(run, lines: list | None = None) -> int:
    """How many windows the crawl actually opened a page for — the count D9 asserts against."""
    return len(_visited_windows(run, lines))


def test_a2_headless_search_is_full_or_names_the_refusal(client, app_module, monkeypatch):
    """A2 — 无头 on weibo may be refused, but only *out loud*.

    It is the account that gets bounced here, not the window shape (docs 微博的墙是间歇风控): a named wall
    or risk page is the site's answer and lands as NAMED_SHORT/WARN. An empty with no reason is the silent
    one and stays red — that is the shape the user reads as 「又没采满」.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        posts_canvas(10, KEYWORDS['A2'], headless=True),
        case_id='A2',
        mode='posts',
        target=10,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, f'a headless search said nothing about being short: {answer}'
        # A refusal may only be named at an address the site served. §6 W1 is still open (a risk verdict
        # latched on a page the browser wrote for itself — ``about:blank``, ``chrome://``), and this is
        # the cell that either clears it or convicts it on the real machine: an unnamed network is not a
        # login wall, and treating one as one turns a machine event into the site's answer.
        for key in HEADLESS_REFUSALS:
            for where in harness.slots_from(run.rec.lines, key, 'where'):
                assert 'weibo' in str(where).lower(), (
                    f'{key} named {where!r}, which is not a weibo address, so it cannot excuse a short '
                    f'table (§6 W1): {run.rec.lines[-6:]}'
                )
        rows = run.preview('node-1')
        if rows:
            _assert_post_rows(rows, minimum=len(rows))
        run.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


def test_a3_recent_range_stops_when_full_and_pays_for_no_further_window(client, app_module, monkeypatch):
    """A3 — D9's promise asserted positively: the target fills first and the rest cost nothing.

    A one-day range is 24 hourly URLs, and ten rows should not need more than a window or two. Counting
    the walk's own per-window navigation lines against the window count it reports is how this cell tells
    "stopped early because it was full" apart from "walked everything and found almost nothing" — the two
    look identical in a short table, and only one of them is the code's fault.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        range_canvas(10, KEYWORDS['A3']),
        case_id='A3',
        mode='posts',
        target=10,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'10 rows over a day of windows is supply this site has: {answer}'
        walked, offered = _walked_windows(run)
        paid = _paid_windows(run)
        assert offered > walked, f'the range was not multi-window at all: walked {walked} of {offered}'
        assert paid == walked, (
            f'the walk opened {paid} windows but reported stopping at {walked}: 剩余窗口零付费 failed'
        )
        assert paid <= 8, f'{paid} windows paid for ten rows; the target is not steering the walk'
        run.finish(answer=answer)


def test_a4_an_empty_window_stores_nothing_not_five_foreign_posts(client, app_module, monkeypatch):
    """A4 — the contamination cell (U31): a plate beside foreign cards means **zero** rows.

    Measured with a keyword that appears nowhere on the site: the page prints 「抱歉，未找到相关结果」
    *together with* five ``.card-wrap`` posts carrying a real ``.name`` and a 「35分钟前」-style timestamp
    outside the asked hour, hung on the same ``#pl_feedlist_index`` chain as a genuine result — no
    container, attribute or card type separates them, so the plate is the only judge available. The old
    card-first ordering stored those five as keyword hits, which is worse than an empty table: nothing in
    the result says the keyword answered none of it.

    The ask is deliberately the whole one-day range (24 windows): the point is that *no* window of a
    keyword that does not exist may contribute a row.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        range_canvas(10, MISSING_KEY),
        case_id='A4',
        mode='posts',
        target=10,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        named = harness.names_key(run.rec.text, 'crawl.weibo.no_result')
        # Built before the assert because a contaminating row is only recognisable by what it *says* — the
        # author and the first characters of its body — and a failure that prints 「None / …」 hides the
        # evidence this cell exists to show. The column is 发布者 (``_scrape_card``), not 发布.
        sample = [f'{row.get("发布者")} / {str(row.get("正文") or "")[:24]}' for row in rows[:4]]
        assert not rows, (
            f'an empty keyword filed {len(rows)} rows while the site printed 「未找到相关结果」'
            f'{" and the plate was read" if named else " but it was never read"}: {sample}'
        )
        assert named, f'a range with no matches ended without saying so: {run.rec.lines[-8:]}'
        answer = run.verdict(rows=0)
        assert answer['verdict'] == harness.NAMED_SHORT, f'an empty range must be named, not full: {answer}'
        run.finish(answer=answer, rows=0)


def test_a5_an_hourly_window_is_paged_beyond_its_first_screen(client, app_module, monkeypatch):
    """A5 — the pager inside one hour (U12): page 2 exists and carries fresh rows.

    Measured: 9 cards on page 1, 6 on page 2, **no mid in common**, while ``.page-info`` prints nothing at
    all on a ``timescope`` page (so the depth has to come from the pager anchors, which is what
    ``_get_total_pages``' href fallback is for). ``_may_page`` used to refuse paging any timed window —
    the assumption was that an hour is narrow, so everything it holds is already rendered. It is not, and
    the refusal cost ~40% of every window in a date-range crawl.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        range_canvas(WINDOW_PAGING_TARGET, KEYWORDS['A5']),
        case_id='A5',
        mode='posts',
        target=WINDOW_PAGING_TARGET,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        answer = run.verdict()
        read = harness.numbers_from(run.rec.lines, 'crawl.weibo.total_pages', 'n')
        paged = [line for line in run.rec.lines if harness.names_key(line, 'crawl.weibo.page_crawling')]
        # Every claim here is unconditional, because the conditional version of this cell passed in both
        # states where the bug is present: an ask the first screen happened to fill, and a
        # ``_get_total_pages`` that read 1 (the href fallback dying, which is the thing this window needs
        # the fallback *for*). Measured depth of one rendered screen is 9 cards, so 14 rows cannot arrive
        # without page 2 being opened — that is what turns a row count into a paging proof.
        assert answer['verdict'] == harness.FULL, (
            f'{WINDOW_PAGING_TARGET} rows over a day of 演唱会 windows is supply this site has: {answer}'
        )
        assert len(rows) == WINDOW_PAGING_TARGET, rows[:2]
        _assert_post_rows(rows, minimum=len(rows))
        assert read and max(read) > 1, (
            f'the walk filled its ask without ever reading a window deeper than one page ({read}): either '
            f'the first screen was wider than the {MEASURED_FIRST_SCREEN_CARDS} measured here, which this '
            f'cell reports rather than assumes, or ``_get_total_pages`` lost its href fallback: {paged[:2]}'
        )
        assert paged, (
            f'the site offered {max(read)} pages for a window and the walk opened none — that is a timed '
            f'window refusing to page again, the ~40% silent loss (U12)'
        )
        run.finish(answer=answer)


def test_a6_the_ask_is_a_ceiling_and_the_walk_lands_on_it_exactly(client, app_module, monkeypatch):
    """A6 — the number the panel showed is the number the table holds: 不多采, and the reason says so.

    Measured against the matrix, not against the crawler: ``posts.target_count`` declares ``minimum=1``
    and ``default=50``, so a blank field is 50 and a typed 0 is clamped to 1 — an app-driven post walk
    **always** carries a ceiling. ``WeiboCrawler.DEFAULT_TARGET = math.inf`` ("no number asked = no
    ceiling") is therefore reachable only from a direct crawler call, never from this tier, and no cell
    here pretends to test it (§11 records that branch as crawler-side only).

    What the reachable promise is worth, then, is exactness: 25 asked on a keyword with supply means 25
    rows — not 24 (a ceiling the walk undershoots, which is 漏采) and not 60 (rows filed after the ask was
    met, which is the 多采 half of 「完全符合要求」). And the closing line must name *the ceiling* as its
    reason and carry the ask in its own ``{target}`` slot: 「已到列表末尾」 on a crawl the user cut short at
    25 is the same lie this round removed from the timeout line, one level up.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 25
    with LiveRun(
        client,
        app_module,
        range_canvas(asked, KEYWORDS['A6']),
        case_id='A6',
        mode='posts',
        target=asked,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        assert len(rows) == asked, f'{asked} asked on an abundant range, {len(rows)} filed: {run.rec.lines[-8:]}'
        _assert_post_rows(rows, minimum=asked)
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the site had the rows and the walk did not bring them: {answer}'
        closing = ''.join(line for line in run.rec.lines if harness.names_key(line, 'crawl.weibo.walk_done'))
        assert harness.names_key(closing, 'crawl.stopReason.target'), (
            f'a walk cut by its own ceiling named another reason: {closing!r}'
        )
        stated = harness.numbers_from(run.rec.lines, 'crawl.weibo.walk_done', 'target')
        assert stated and stated[-1] == asked, (
            f'the closing line reported a target of {stated[-1:]} for an ask of {asked}'
        )
        walked, offered = _walked_windows(run)
        # The arithmetic the reason has to agree with, and no more than that. ``offered > walked`` would
        # be the stronger claim — "windows were left unopened" — but a ceiling met on the last window of a
        # day is the site's supply, not a lie, and a cell that reds on where the supply happens to end is
        # one the next reader switches off. ``walked`` never exceeding ``total`` is the invariant.
        assert 0 < walked <= offered, f'the walk reported window {walked} of {offered}: {closing!r}'
        run.finish(answer=answer)


# ─── B · 作者 (the endpoint that is a per-session throttle) ────────────


def test_b1_author_mode_files_this_uid_or_refuses_by_name(client, app_module, monkeypatch):
    """B1 — the mymblog red line, live: this account's posts, or a refusal that says which one.

    ``/ajax/statuses/mymblog`` answers ``200`` with real posts in one session and a
    ``<h2>403 Forbidden</h2>`` edge body in the next — same walk, same logged-in navigation, same cookie
    (``docs/crawler_notes.md``). So this cell cannot demand rows; it demands the half that is always owed.
    An author walk that stores nothing must have *raised*, the console must name which refusal it met, and
    the node must settle ``failed``. The shape it convicts is the one the red line was written against: a
    zero-row table that reports 完成 and reads to the user as 「这个号没发过微博」.

    One failure, one line: ``wf.node_failed`` is the attributed console line, so a refusal that printed
    itself three times is a finding, not a style point.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client, app_module, author_canvas(8), case_id='B1', mode='author', target=8, timeout=DEEP_TIMEOUT
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        if rows:
            _assert_author_rows(rows, uid=AUTHOR_UID)
        else:
            named = [key for key in AUTHOR_REFUSALS if harness.names_key(run.rec.text, key)]
            assert named, f'an author walk stored 0 rows and named no refusal: {run.rec.lines[-8:]}'
            assert run.status['outcome'] == 'failed', (
                f'a refusal that did not fail the RUN settled the node over an empty table: {run.status}'
            )
            assert run.node()['status'] == 'failed', run.node()
            assert run.rec.counts_key('wf.node_failed') == 1, (
                f'one refusal owes one attributed line, not several: {run.rec.lines[-8:]}'
            )
        answer = run.verdict(rows=len(rows))
        run.finish(answer=answer, rows=len(rows), warn=answer['verdict'] == harness.NAMED_SHORT)


def test_b2_an_author_ask_past_its_first_page_pages_and_never_repeats(client, app_module, monkeypatch):
    """B2 — 40 rows from one account is a walk over ``page=N``, and every row is a distinct post.

    Measured: page 1 hands back 28 rows, every later page 20, each with fresh ids. An ask above 28 is
    therefore unreachable from one response — the only way it fills is the pager advancing, and the only
    way the total stays honest is de-duplication by 微博ID across pages. That identity is also the first
    thing a home-timeline mirror breaks (its page 2 repeats page 1), so the repeat check is the mirror
    guard read from the stored table rather than from the payload.

    A session the edge refuses is B1's named path: this cell grades the refusal it got and spends no
    further ask on it, because retrying a throttled endpoint is how one refusal grows into six.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        author_canvas(AUTHOR_PAGING_TARGET),
        case_id='B2',
        mode='author',
        target=AUTHOR_PAGING_TARGET,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        refused = [key for key in AUTHOR_REFUSALS if harness.names_key(run.rec.text, key)]
        if not rows:
            assert refused, f'0 author rows and no named refusal: {run.rec.lines[-8:]}'
            answer = run.verdict(rows=0)
            run.finish(answer=answer, rows=0, warn=answer['verdict'] != harness.FULL)
            return
        _assert_author_rows(rows, uid=AUTHOR_UID)
        ids = [str(row.get('微博ID') or '') for row in rows]
        assert all(ids), f'an author row with no mid cannot be de-duped or resumed: {ids[:6]}'
        assert len(set(ids)) == len(ids), f'{len(ids)} rows, {len(set(ids))} distinct 微博ID — a page repeated'
        # The guard has to be the ask, not the outcome: a walk that stopped at page 1 delivers ≤ 28 rows,
        # and a cell that only checked its paging claim ``if len(rows) > 28`` cannot fail for the bug it is
        # about. Either the edge refused (named above) or this account has more than one page of posts, so
        # the ask itself is what obliges the pager to advance.
        assert refused or len(rows) >= 29, (
            f'{len(rows)} rows, no refusal named, and page 1 alone holds {MEASURED_AUTHOR_PAGE_ONE}: the walk '
            f'never advanced and said nothing ({run.rec.lines[-8:]})'
        )
        cursor = harness.cursor_of(run.record, 'node-1')
        assert int(cursor.get('page') or 1) > 1, (
            f'{len(rows)} rows arrived without the pager ever advancing past page 1: {cursor}'
        )
        # The author cursor is ``uid`` + ``page`` + ``done`` — position, nothing else. Ids belong to the
        # seeded rows and the ledger; a list of them here is the defect commit ee885f7 removed from
        # douyin, where a capped id list made 继续 re-open everything before the cut-off.
        smuggled = {key: value for key, value in cursor.items() if isinstance(value, (list, tuple, dict))}
        assert not smuggled, f'the author cursor stores content, not position: {smuggled}'
        answer = run.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, f'a short author walk that said nothing: {answer}'
        run.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


def test_b3_an_author_that_is_not_an_author_is_refused_by_name(client, app_module, monkeypatch):
    """B3 — a 作者 field holding neither a UID nor a profile URL is refused, never guessed.

    ``author`` is required free text, so the matrix cannot tell ``6122597700`` from a note typed into the
    wrong box, and guessing here would crawl *somebody*: the endpoint answers ``200`` with the home
    timeline when the uid is unreadable. So the crawler raises ``authorEmpty`` before it opens a page —
    which also makes this the one author cell that costs a browser start and no crawling, and the reason
    it can run on the short budget.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        author_canvas(5, '这不是一个微博主页'),
        case_id='B3',
        mode='author',
        target=5,
        timeout=QUICK_TIMEOUT,
    ) as run:
        run.wait()
        assert harness.names_key(run.rec.text, 'crawl.weibo.authorEmpty'), (
            f'a non-author 作者 field was not refused by name: {run.rec.lines[-8:]}'
        )
        assert run.rows() == 0, 'a uid the crawler cannot read still produced a table'
        assert run.record['status'] == 'failed', run.record
        answer = run.verdict(rows=0)
        assert answer['verdict'] == harness.NAMED_SHORT, f'an unreadable uid must name itself, not pass: {answer}'
        run.finish(answer=answer, rows=0, warn=True)


# ─── C · 热搜 (the board the site ranks for itself) ─────────────────────


def test_c1_the_board_delivers_its_topics_and_five_columns(client, app_module, monkeypatch):
    """C1 — the board is one JSON fetch inside a loaded page: 40 topics, 5 columns, exact heat."""
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
            assert isinstance(row.get('热度'), int), f'热度 must be the payload number: {row.get("热度")!r}'
        run.finish(answer=answer)


def test_c2_asking_past_the_board_is_answered_out_loud(client, app_module, monkeypatch):
    """C2 — the board's size is the site's answer, and ``hotCapped`` is what says so.

    60 asked against the measured 51: a crawl that returned 51 with no line reads exactly like one that
    lost ten topics on the way, and the difference is the only thing this tier exists to keep visible.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, hot_canvas(60), case_id='C2', mode='hot', target=60) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.NAMED_SHORT, f'an over-long board ask must name the cap: {answer}'
        capped = harness.numbers_from(run.rec.lines, 'crawl.weibo.hotCapped', 'board')
        assert capped, f'the cap line did not carry the board length it measured: {answer["reasons"]}'
        rows = run.preview('node-1')
        assert len(rows) == capped[-1], f'{len(rows)} rows for a board reported as {capped[-1]} long'
        run.finish(answer=answer)


def test_c3_the_board_is_answered_without_a_session(client, app_module, monkeypatch, tmp_path):
    """C3 — the one weibo mode with ``needs_session=False``: no cookie, still a board.

    The matrix says this so the pre-run gate cannot invent a login requirement the site does not have
    (AGENTS: weibo's 热搜 answers anonymously), and such a declaration is worth exactly what its test is.
    The tier's default jar *is* the user's real one, so a cell that merely forgot to call
    :func:`harness.real_jar` would crawl logged in and still claim it proved the anonymous case: the
    experiment has to withhold the cookie directory on purpose. ``use_profile=False`` is the other half,
    because a shared profile owns its own session whatever the directory holds — so the console must also
    carry ``run.profileOff``, the line that says the throwaway shape was taken rather than assumed.
    """
    harness.no_jar(monkeypatch, app_module, tmp_path)
    with LiveRun(
        client,
        app_module,
        hot_canvas(10, use_profile=False),
        case_id='C3',
        mode='hot',
        target=10,
    ) as run:
        run.wait()
        assert harness.names_key(run.rec.text, 'run.profileOff'), (
            f'no line says this browser ran without the shared device, so the anonymity this cell claims '
            f'is not the thing that was measured: {run.rec.lines[-6:]}'
        )
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the board needs no login, so 10 topics must arrive: {answer}'
        assert run.rows() == 10
        run.finish(answer=answer)


# ─── D · 评论 (the adapter that was guessing four columns) ─────────────


def test_d1_two_posts_carry_comments_the_columns_actually_read(client, app_module, monkeypatch, weibo_windowed):
    """D1 — comments of two known posts, with the fabricated columns asserted as read.

    ``comment_limit`` is *per article*, so the ask is ``sum(min(limit, 评论数))`` over the links actually
    chosen — read off the card's own number, which is the site's denominator for that thread. A fixed
    ``5 × links`` was this cell's first shape and it is wrong twice over: it grades a 2-of-10 crawl FULL
    when the threads only had two comments each, and it *reds* an honest one when they had fewer than the
    limit. Either way the number being asserted is arithmetic the test invented rather than a promise the
    product made (§11 step 3: 评论格按真实 ask 判满).
    """
    harness.real_jar(monkeypatch, app_module)
    limit = 5
    pairs = _commented_links(weibo_windowed, need=2, min_comments=PROBE_MIN_COMMENTS)
    links = [link for link, _count in pairs]
    ask = sum(min(limit, count) for _link, count in pairs)
    with LiveRun(
        client,
        app_module,
        comments_canvas(links, limit=limit),
        case_id='D1',
        mode='comments',
        target=ask,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        _assert_comment_rows(rows, minimum=1)
        answer = run.verdict(rows=len(rows))
        assert answer['verdict'] != harness.SILENT_SHORT, f'a comment crawl that said nothing: {answer}'
        assert len(rows) <= ask or answer['verdict'] == harness.NAMED_SHORT, (
            f'the two threads report {ask} comments between them and the table holds {len(rows)}: '
            f'that is 多采, and only a named line may excuse it'
        )
        run.finish(answer=answer, rows=len(rows), target=ask, warn=answer['verdict'] == harness.NAMED_SHORT)


def test_d2_a_wired_comments_node_crawls_the_links_its_parent_found(client, app_module, monkeypatch):
    """D2 — the 链接 column wired into 评论采集: every link, not the first one.

    One connected canvas is ONE workflow, so both nodes are graded on the same transcript — and the
    whitewash this still allows is closed by the exit lists, not by slicing: the comment half is graded
    with :data:`COMMENT_EXITS`, which holds no search line, so 「该时间段无搜索结果」 printed by the parent
    cannot excuse a comment node that stored nothing.

    The ask is **computed from the parent table after the run**, not invented here: ``comment_limit=3`` per
    article over four links is 12 only if all four hold three comments, and grading a 12-row promise
    against two threads that had one comment each would convict an honest crawl (§11 step 3: 评论格按真实
    ask 判满). What cannot be excused by supply is the feed itself — a wired column that iterates one link
    and calls it done — so every commented parent must appear in the comment table, and a parent missing
    from it must be named by one of the comment refusals carrying that URL.
    """
    harness.real_jar(monkeypatch, app_module)
    limit = 3
    canvas = harness.posts_then_comments_canvas(
        PLATFORM,
        posts={'keyword': KEYWORDS['A1'], 'target_count': 4},
        comments={'comment_limit': limit},
    )
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='D2',
        mode='comments',
        target=4 * limit,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        parent = run.verdict('node-1', target=4, **_post_vocabulary(run))
        assert parent['verdict'] == harness.FULL, f'the parent fed nothing: {parent}'
        parents = run.preview('node-1')
        counts = {str(row.get('链接') or ''): int(row.get('评论数') or 0) for row in parents}
        commented = {link for link, count in counts.items() if count > 0}
        assert len(commented) >= 2, (
            f'the feed can be graded on coverage only if more than one link can answer: {counts}'
        )
        ask = sum(min(limit, count) for count in counts.values())
        rows = run.preview('node-2')
        fed = {str(row.get('文章URL') or '') for row in rows}
        assert fed <= set(counts), (
            f'a comment is attributed to a link this canvas never crawled: {sorted(fed - set(counts))}'
        )
        unerved = commented - fed
        if unerved:
            # A thread that answered nothing must be named *about that thread*: the walker's own lines carry
            # the URL (``comment.weiboShowFailed``) or the per-article summary carries its status, and either
            # lets the user see which link the table is missing. A generic shortfall sentence printed
            # somewhere else in the console is not that.
            tails = {link.rstrip('/').rsplit('/', 1)[-1] for link in unerved if link}
            said = [
                line
                for line in run.rec.lines
                if any(tail and tail in line for tail in tails)
                and any(harness.names_key(line, key) for key in COMMENT_NAMED)
            ]
            assert said, (
                f'the column named {len(commented)} threads with comments and {len(unerved)} of them got '
                f'nothing without one line about those links: {sorted(unerved)} / {run.rec.lines[-8:]}'
            )
        if rows:
            _assert_comment_rows(rows, minimum=1)
        answer = run.verdict('node-2', target=ask)
        assert answer['verdict'] != harness.SILENT_SHORT, f'the fed comment node said nothing: {answer}'
        run.finish(answer=answer, rows=len(rows), target=ask, warn=answer['verdict'] == harness.NAMED_SHORT)


def _post_vocabulary(run) -> dict:
    """The search half's own exits/liars, for a canvas whose run has two modes in one transcript."""
    exits, liars = _vocabulary('posts', run.headless)
    return {'exits': exits, 'bug_lines': liars}


def test_d3_headless_comments_match_the_windowed_shape(client, app_module, monkeypatch, weibo_windowed):
    """D3 — ``collects=fetch`` on this mode says a window buys nothing; the rows must agree.

    The card's own 评论数 is the denominator: a headless comment crawl that returns fewer rows than the
    thread reports *and* names no shortfall has contradicted the matrix's word — which is also the note the
    Data Source panel shows the user. The ask is ``min(limit, 评论数)`` of the richest thread this pass
    found, so the claim is exercisable on a two-comment thread and on a seven-hundred-comment one alike.
    """
    harness.real_jar(monkeypatch, app_module)
    limit = 8
    link, reported = _richest_link(weibo_windowed)
    ask = min(limit, reported)
    with LiveRun(
        client,
        app_module,
        comments_canvas([link], limit=limit, headless=True),
        case_id='D3',
        mode='comments',
        target=ask,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        if rows:
            _assert_comment_rows(rows, minimum=1)
        answer = run.verdict(rows=len(rows))
        assert answer['verdict'] != harness.SILENT_SHORT, (
            f'a headless crawl on a thread the card says holds {reported} comments returned {len(rows)} '
            f'and named nothing: {answer}'
        )
        assert len(rows) >= ask or answer['verdict'] == harness.NAMED_SHORT, (
            f'collects=fetch promises the headless shape loses nothing: {len(rows)} of {ask}'
        )
        run.finish(answer=answer, rows=len(rows), warn=answer['verdict'] == harness.NAMED_SHORT)


def test_d4_no_limit_names_the_gap_the_site_printed(client, app_module, monkeypatch, weibo_windowed):
    """D4 — 「采集全部评论」 is graded against the thread's own number, and the gap must be named (U33).

    Measured: ``buildComments`` cursor-dies at 22 rows for a thread whose envelope says
    ``total_number: 30``, and the eight absent floors are its nested replies — no request shape this
    session tried returns them as a list, and only one preview child per parent is in hand at all. So the
    product's promise here is not "get them all", it is "**say** the site counted more than you got".
    ``trendsText`` printing 「已加载全部评论」 on exactly that crawl is why the line reads ``total_number``
    and never the sentence.

    On a thread small enough that the cursor does reach its end, the same cell asserts the **other** side:
    no gap line. Either way it is a real claim, and which one ran is visible in the numbers the row
    carries (``rows`` against ``target``), because a cell that only ever tested the gap would go vacuously
    green on a quiet day — and quietly red on one too, which is how the fixed ``>= 12`` selection gate in
    this file's first draft behaved.
    """
    harness.real_jar(monkeypatch, app_module)
    link, reported = _richest_link(weibo_windowed)
    with LiveRun(
        client,
        app_module,
        comments_canvas([link], limit=0),
        case_id='D4',
        mode='comments',
        target=reported,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        _assert_comment_rows(rows, minimum=1)
        named = [line for line in run.rec.lines if harness.names_key(line, 'comment.weiboShort')]
        if len(rows) < reported:
            assert named, (
                f'the site reported {reported} comments, {len(rows)} arrived, and nothing named the gap: '
                f'{run.rec.lines[-8:]}'
            )
            slots = harness.numbers_from(run.rec.lines, 'comment.weiboShort', 'declared')
            assert slots and slots[-1] >= reported, f'the shortfall line lost the site number: {named}'
        else:
            assert not named, (
                f'the cursor delivered all {reported} comments the thread reports, yet the console blamed '
                f'a gap: {named}'
            )
        answer = run.verdict()
        run.finish(answer=answer, rows=len(rows), warn=answer['verdict'] == harness.NAMED_SHORT)


def test_d5_an_ask_of_five_is_not_reported_as_a_shortfall(client, app_module, monkeypatch, weibo_windowed):
    """D5 — the line that blames the thread for the user's own number is a bug, not a report.

    评论上限 5 on a 749-comment post is the user's ask, not 744 missing comments: printing
    「站点写着 749 条…差额是楼中楼」 there is the same class of lie this round was fixing, and the live
    tier drives exactly this shape (a small per-article limit). So the cell requires *silence*.
    """
    harness.real_jar(monkeypatch, app_module)
    link, reported = _richest_link(weibo_windowed)
    # The ask is one **below what the thread reports**, by construction: at ``limit == 评论数`` there is no
    # gap for the bug to misattribute and the cell proves nothing. Two comments is the smallest thread this
    # can be said of, and the number it uses is in the row.
    limit = max(1, min(5, reported - 1))
    with LiveRun(
        client,
        app_module,
        comments_canvas([link], limit=limit),
        case_id='D5',
        mode='comments',
        target=limit,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        assert len(rows) <= limit, f'comment_limit is per article and was not honoured: {len(rows)} > {limit}'
        lied = [line for line in run.rec.lines if harness.names_key(line, 'comment.weiboShort')]
        assert not lied, f'the ask was {limit} of {reported} and the console blamed the thread: {lied}'
        answer = run.verdict()
        run.finish(answer=answer, rows=len(rows), target=limit, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── E · 停止 then 继续 (the cursor must not walk past an unfinished window) ─


def test_e1_stop_inside_a_window_then_continue_re_enters_it(client, app_module, monkeypatch):
    """E1+E2 — 停止 inside a multi-window walk, 继续 from the cursor it left (M4's red line).

    A window is behind the cursor only once it has been *walked*; ``weibo.py`` deliberately holds
    ``url_index`` back and restarts the per-window card/page cursors on every entry. Marking a window
    done before entering was harmless while a window was one rendered page; now that an hourly window is
    up to ten pages deep (A5), a kill mid-window let the resume skip the pages it had never reached —
    silent 漏采 that the closing line then reported as 「已到列表末尾」.

    So the proof this cell demands is not "the number went up", which a re-crawl of a *later* window
    would also satisfy. It is that 继续 opens **the same hourly URL** 停止 was inside: the last window the
    first attempt navigated to is the first window the resume navigates to.
    """
    harness.real_jar(monkeypatch, app_module)
    canvas = range_canvas(50, KEYWORDS['E1'], days=2)
    with LiveRun(client, app_module, canvas, case_id='E1', mode='posts', target=50, timeout=DEEP_TIMEOUT) as run:
        # The trigger is the FIRST stored row, not the fifth: waiting for five can spend the case's whole
        # budget before the button is pressed, and an assert that fires mid-crawl then leaks a live worker.
        run.wait_until(lambda: run.live_rows() >= 1, within=STOP_DEADLINE, what='the crawl stored a row')
        run.stop()
        run.wait()
        kept = run.rows()
        assert run.status['outcome'] == 'interrupted', run.status
        assert run.node()['status'] == 'partial', run.node()
        assert 1 <= kept < 50, f'a walk cut short is short of its target; it kept {kept}'
        assert run.status['failed_nodes'] == 0, f"停止 is the user's own button, not a failure: {run.status}"
        assert harness.names_key(run.rec.text, 'run.nodeStopped'), 'the stopped node has to be named by label'
        cut_at = _visited_windows(run)
        assert cut_at, f'the walk stored {kept} rows without naming a window it opened: {run.rec.lines[-6:]}'
        cursor = harness.cursor_of(run.record, 'node-1')
        assert cursor, f'the stop left no cursor, so 继续 has no position to pick up: {run.record}'
        stopped_at = int(cursor.get('url_index') or 0)
        stopped_page = int(cursor.get('page_index') or 0)
        # AGENTS' third checkpoint rule, read against this crawl's actual cursor: ``keyword`` + ``urls``
        # + ``url_index``/``page_index``/``card_index`` is the *itinerary* and the position into it, and
        # ``url_index`` only means anything because the list it indexes is the one that was rebuilt (or
        # reused) on this attempt. What must never come back is the identity of rows already paid for —
        # those live in the seeded rows and the dedupe ledger, and a list of them in the cursor is the
        # defect commit ee885f7 removed from douyin's resume.
        already = {str(row.get('微博ID') or '') for row in run.preview('node-1')} - {''}
        carried = {
            key
            for key, value in cursor.items()
            for item in (value if isinstance(value, (list, tuple)) else [value])
            if str(item) in already
        }
        assert not carried, (
            f'停止 left paid-for row ids in the cursor under {sorted(carried)}; the resume then holds a '
            f'second, possibly capped, opinion about what this run already has: {cursor}'
        )
        answer = run.verdict(rows=kept)
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.nodeStopped' in answer['reasons'], answer
        run.finish(answer=answer)

    # 继续: the same canvas, the same run id, and no queue — a resume that queued would spend its whole
    # read budget watching somebody else's console.
    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='E2',
        mode='posts',
        target=50,
        resume_run_id=run.run_id,
        queue=False,
        timeout=DEEP_TIMEOUT,
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, 'a resume that minted a new id is a second crawl, not 继续'
        assert harness.names_key(again.rec.text, 'run.resume_from'), 'the console must say it is continuing'
        assert harness.names_key(again.rec.text, 'crawl.resume_have'), 'and how many rows it started from'
        assert again.rows() >= kept, f'the continue lost stored rows: {kept} → {again.rows()}'
        resumed = again.verdict()
        window = int(harness.cursor_of(again.record, 'node-1').get('url_index') or 0)
        assert window >= stopped_at >= 0, f'继续 walked backwards past the interrupted window: {stopped_at} → {window}'
        rewalked = _visited_windows(again)
        assert rewalked, f'继续 stored {again.rows()} rows without opening a window: {again.rec.lines[-6:]}'
        assert rewalked[0] == cut_at[-1], (
            f'停止 was inside {cut_at[-1]!r} (url_index {stopped_at}) but 继续 opened {rewalked[0]!r} first: '
            'the pages it had not reached in that window are silently never coming'
        )
        # The address is necessary and not sufficient, and this is the half U36 was written for. Before
        # that fix the resume re-opened the right window, re-harvested page 1, saw nothing new (every row
        # was already in the ledger), printed 「某一页是空的」 and left — so the pages deeper than the kill,
        # the only ones still owing rows, went unfetched while the console read as an exhausted window.
        # The proof is therefore about *depth*: a page beyond the one 停止 was on, or the ask filled.
        pages = harness.numbers_from(again.rec.lines, 'crawl.weibo.page_crawling', 'i')
        filled = again.rows() >= 50
        assert stopped_page <= 1 or filled or (pages and max(pages) > stopped_page), (
            f'停止 was on page {stopped_page} of {cut_at[-1]!r}; 继续 opened pages {pages or "none"} and '
            f'reached {again.rows()} of 50 — the deeper pages of that window were never asked for, which is '
            f'under-collection no final row count can see'
        )
        links = [str(row.get('链接') or '') for row in again.preview('node-1')]
        assert len(links) == len(set(links)), (
            f'继续 re-collected rows it already had: {len(set(links))} unique of {len(links)}'
        )
        assert resumed['verdict'] != harness.SILENT_SHORT, f'继续 left the table short without naming why: {resumed}'
        again.finish(answer=resumed, warn=resumed['verdict'] == harness.NAMED_SHORT)


# ─── G · serial_only (this platform's own axis) ─────────────────────────


def _audit_component(run, case_id: str, label: str, record: dict, node_id: str, *, target: int, mode: str) -> dict:
    """One component's own row: its verdict, its count, its transcript slice.

    A two-component run is two findings. Rolling them into the case row would let 乙's silence hide behind
    甲's honest 「该时间段无搜索结果」, which is the exact shape :meth:`RunDriver.component_verdict` exists
    to refuse — and the artifact would then carry one line for two crawls nobody can match to a table.
    """
    answer = run.component_verdict(label, record, node_id, target=target, mode=mode)
    run.audit(
        f'{case_id}.{mode}.{node_id}',
        verdict=answer['verdict'],
        reasons=answer['reasons'],
        rows=harness.stored_rows(record, node_id),
        target=target,
        warn=answer['verdict'] != harness.FULL,
    )
    return answer


def test_g1_a_parallel_weibo_canvas_is_forced_into_the_queue(client, app_module, monkeypatch):
    """G1 — ``serial_only`` is a fact the platform cannot be voted out of: two weibo crawls queue.

    The switch has to be **off** for this cell to observe anything, and that is worth stating because it is
    the difference between testing a red line and testing a default: :func:`crawl_gate.hold` computes
    ``forced_serial = serial_only_of(platform) and not get_setting('same_platform_queue')``, so with the
    queue on — its shipped default — weibo waits anyway and says so with ``run.platformQueued``. That line
    proves the *user's* switch worked. Only with it off does the console have to answer the real question,
    「did the matrix outrank the switch?」, and ``run.serialForced`` is the only line that can say so.

    Then both tables have to arrive: a queue that quietly loses the second workflow looks exactly like a
    short crawl, which is the complaint this whole pass is about. What this cell does **not** re-prove is
    the lane's *timing* (held until the crawl finishes, not until it starts) — zhihu's G/S cells own that,
    and a second measurement of the same mechanism would cost two more searches on this account.

    A second account is the only way to test true weibo parallelism. This machine has no
    ``weibo@<account>`` cookie file, so that shape is **declared absent here rather than skipped
    silently** — §7's row records it, and this paragraph is its audit trail.
    """
    harness.real_jar(monkeypatch, app_module)
    first, second = KEYWORDS['G']
    canvas = harness.component_canvas(
        [
            {'platform': PLATFORM, 'mode': 'posts', 'label': '甲', 'params': {'keyword': first, 'target_count': 8}},
            {'platform': PLATFORM, 'mode': 'posts', 'label': '乙', 'params': {'keyword': second, 'target_count': 8}},
        ],
        # ``use_profile=False`` is plan decision D3, not a preference: one profile locks one browser, so a
        # parallel canvas crawling the user's own directory contends on the *profile* before it ever
        # reaches the platform lane — and then the queue line this cell asserts can only arrive after a
        # 900-second profile wait. The cookie snapshot is still imported into each throwaway browser.
        settings=harness.run_settings('parallel', True, use_profile=False),
    )
    with (
        harness.lane_switches(queue=False, stagger=0),
        LiveRun(client, app_module, canvas, case_id='G1', mode='posts', target=16, timeout=DEEP_TIMEOUT) as run,
    ):
        run.wait()
        assert harness.names_key(run.rec.text, 'run.serialForced'), (
            f'a serial_only platform ran without the forced-queue line, so the switch outranked the '
            f'matrix: {run.rec.lines[-10:]}'
        )
        assert run.record['mode'] == 'parallel', (
            f'the lane was honoured by rewriting the record instead of holding it: {run.record["mode"]!r}'
        )
        record = run.refresh()
        left = _audit_component(run, 'G1', '甲', record, 'node-1', target=8, mode='posts')
        right = _audit_component(run, 'G1', '乙', record, 'node-3', target=8, mode='posts')
        assert left['verdict'] != harness.SILENT_SHORT, f'component 甲: {left}'
        assert right['verdict'] != harness.SILENT_SHORT, f'component 乙: {right}'
        assert harness.stored_rows(record, 'node-3') > 0, (
            f'the queued component filed nothing while its sibling filled: {left} / {right}'
        )
        run.finish(
            answer=left,
            rows=run.rows('node-1') + run.rows('node-3'),
            warn=harness.NAMED_SHORT in (left['verdict'], right['verdict']),
        )


def test_g2_the_stagger_switch_does_not_unlock_a_serial_only_platform(client, app_module, monkeypatch):
    """G2 — 错峰 is a spacing knob; on weibo the queue still holds, and the spacing is paid *inside* it.

    The two switches were conflated once already (真排队 holds a lane until the crawl *finishes*, 错峰 only
    spaces its starts), and on this platform the difference is the wall. With the queue off and 错峰 turned
    **up**, the forced line must still print — a settings toggle may not become a way to opt out of a
    platform's red line — and the gap is then the second waiter's own doing, which the queue line says out
    loud. So this cell is G1's mirror: same red line, the other switch moved, and the pair of lines is what
    distinguishes them.
    """
    harness.real_jar(monkeypatch, app_module)
    first, second = KEYWORDS['G2']
    canvas = harness.component_canvas(
        [
            {'platform': PLATFORM, 'mode': 'posts', 'label': '丙', 'params': {'keyword': first, 'target_count': 6}},
            {'platform': PLATFORM, 'mode': 'posts', 'label': '丁', 'params': {'keyword': second, 'target_count': 6}},
        ],
        # D3 again: parallel means throwaway profiles, or the two components fight for one browser lock
        # before they ever reach the platform lane this cell is about.
        settings=harness.run_settings('parallel', True, use_profile=False),
    )
    with (
        harness.lane_switches(queue=False, stagger=15),
        LiveRun(client, app_module, canvas, case_id='G2', mode='posts', target=12, timeout=DEEP_TIMEOUT) as run,
    ):
        run.wait()
        assert harness.names_key(run.rec.text, 'run.serialForced'), (
            f'with 错峰 turned up the forced queue was skipped, so spacing became a licence to run two '
            f'walks at once: {run.rec.lines[-10:]}'
        )
        assert harness.names_key(run.rec.text, 'run.platformQueued'), (
            f'the queue held the lane but the spacing the user asked for was never paid: {run.rec.lines[-10:]}'
        )
        record = run.refresh()
        left = _audit_component(run, 'G2', '丙', record, 'node-1', target=6, mode='posts')
        right = _audit_component(run, 'G2', '丁', record, 'node-3', target=6, mode='posts')
        assert left['verdict'] != harness.SILENT_SHORT, f'component 丙: {left}'
        assert right['verdict'] != harness.SILENT_SHORT, f'component 丁: {right}'
        kept = harness.stored_rows(record, 'node-1') + harness.stored_rows(record, 'node-3')
        answer = run.verdict(rows=kept, target=12)
        run.finish(answer=answer, rows=kept, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── H · the user's own acceptance canvas ───────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]

#: His weibo canvas, run as he saved it apart from the one thing §1's D9 carved out. Read-only; the path
#: is absolute because ``Config.WORKFLOW_DIR`` is redirected into a throwaway root by the harness.
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：微博.json'

#: The components he saved, taken one at a time on this platform (``serial_only``), each buying its own
#: pages: 50-row windowed searches (he has two now, one with and one without a stored range; measured:
#: each fills inside one window), a 50-row author walk (3 ``mymblog`` pages), the 51-topic board, and
#: **all** the comments of one post. The comment leg is the unbounded one, so the budget is the comment
#: cells' budget plus the rest.
ACCEPTANCE_TIMEOUT = COMMENT_TIMEOUT + DEEP_TIMEOUT


def _acceptance_copy(**post_params) -> dict:
    """His canvas, deep-copied with every search window narrowed — and the file on disk left alone.

    The saved 文章 legs ask for a range — one stores 2026-01-01 → 2026-09-26 (~6432 hourly windows), the
    other stores none and so would walk unbounded. Running either as written is not a harder test: the
    walk stops at its target and pays for none of the rest, so the long range exercises nothing a two-day
    one does not, at a cost the user did not agree to per pass. D9 decided that, and the assertion runs the
    other way — the copy proves 「目标先满、剩余窗口零付费」 for each search leg (H1). Every ``posts`` node is
    narrowed here, so a 「无时间范围」 leg he adds later is budgeted the same way the moment it appears.
    The file is never rewritten (D5): the variant is what the test wanted, the file is what he wrote.
    """
    opened = copy.deepcopy(accept.workflow_file(ACCEPTANCE_FILE))
    for node in opened['nodes']:
        if (node.get('params') or {}).get(harness.MODE_KEY) == 'posts':
            node.setdefault('params', {}).update(post_params)
    return opened


def _grade_component(run, part, record) -> dict:
    """One component's verdict, on its own console slice with its own mode's vocabulary."""
    return run.component_verdict(part['label'], record, part['source'], target=part['ask'], mode=part['mode'])


def test_h1_the_shipped_canvas_runs_with_its_window_narrowed(client, app_module, monkeypatch):
    """H1 — 测试：微博.json exactly as he left it: only the legs he switched on, minus the range (D9).

    The flagship of the platform's eight steps: not a synthetic canvas but the one he clicks Run on. So
    it runs **as saved**, and a disabled name node cascades its whole leg out (``effective_workflow``) —
    which means this case grades only the switched-on components and holds the switched-off ones
    answerable for sitting out: a leg he turned off must not print a line, open a record, or pay a page.
    H2 forces every leg on in series, so between the two the whole canvas is covered without H1 ever
    pretending a disabled leg ran.

    The component count is read out of the file, never hard-coded: he has been editing this canvas (he
    added a second 文章 search 「无时间范围」 and switched the other legs off), and a pinned 「four」 would go
    red on a legitimate edit while saying nothing about the one shape this case argues — a search walk
    that stops early. The guard is that a switched-on search leg is present, and D9 is asserted of every
    switched-on search leg. Each component gets its own record, console slice, audit row and exported
    file, and the index row is derived from those verdicts — never written as FULL by hand.

    And the claim D9 turned into an assertion: each search component fills its stored 50, and the walk's
    own closing line shows it stopped **before** the range ran out, with no per-window navigation after
    the ceiling. 「剩余窗口零付费」 is what makes a narrow table and an early stop distinguishable in the
    console, which is the whole complaint this round started from.
    """
    harness.real_jar(monkeypatch, app_module)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=1)
    workflow = _acceptance_copy(start_time=f'{start}', end_time=f'{end}')
    _on, _off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    running = [part for part in found if part['on']]
    sat_out = [part for part in found if not part['on']]
    searches = [part for part in running if part['mode'] == 'posts']
    assert searches, (
        'this case narrows the search leg and argues it stops early, but no switched-on component is a '
        f'posts leg to run: {[part["label"] for part in running]}'
    )
    exported_before = accept.export_dir_entries()
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H1',
        mode='mixed',
        target=sum(part['ask'] for part in running),
        timeout=ACCEPTANCE_TIMEOUT,
    ) as run:
        run.wait()
        run.assert_l3()
        records = accept.records_by_node(client, running)
        silent, kept, asked, answers = accept.audit_components(
            run,
            records=records,
            case_id='H1',
            found=running,
            grade=lambda part, record, console: _grade_component(run, part, record),
        )
        assert not silent, f'components under target with no honest reason named: {silent}'
        for posts in searches:
            own = run._slice(posts['label']).splitlines()
            walked, offered = _walked_windows(run, own)
            assert 0 < walked < offered, (
                f'the search component {posts["label"]!r} filled '
                f'{harness.stored_rows(records[posts["label"]], posts["source"])} '
                f'rows and reported window {walked}/{offered}: D9 is about a walk that STOPS EARLY, so either '
                'the range ran out (this copy is the two-day one) or the ceiling did not steer it'
            )
            paid = _paid_windows(run, own)
            assert paid == walked, (
                f'{posts["label"]!r} says it reached window {walked} of {offered} but opened a page for {paid}: '
                '剩余窗口零付费 failed, and the table cannot say which windows it paid for'
            )
        # 谁没跑: a leg he switched off stays silent. ``transcript_for`` is the non-raising accessor —
        # ``_slice`` would report the *absence* as an attribution failure, which is the wrong error for a
        # component that was never meant to run. A disabled leg that printed anything ran against his canvas.
        for part in sat_out:
            assert not run.rec.transcript_for(part['label']), (
                f'the switched-off component {part["label"]!r} still got console lines attributed to it: '
                'a disabled leg must not run, pay, or appear'
            )
        accept.assert_canvas_exports(running, accept.new_exports(exported_before), records)
        # The rows are the shape the canvas mode promises (AGENTS' 「并行是一条记录，串行一 workflow 一行」).
        # This file is 并行 today, but the mode is read off the row, so a canvas he flips to 串行 passes on a
        # run whose every switched-on leg graded honestly instead of reddening at a pinned parallel count.
        accept.assert_record_shape(run, records, running)
        if run.record['status'] != 'completed':
            refusals = accept.named_refusals(run.rec.text, WEIBO_NAMED_DEATHS)
            assert refusals, (
                f'the run settled {run.record["status"]} without naming a reason anywhere: {run.rec.text[-1500:]}'
            )
        summary = accept.summary_row(run, case_id='H1', found=running, answers=answers, kept=kept, asked=asked)
        assert summary == harness.FULL, f'his own canvas must work end to end on a normal day: {answers}'
        # No ``run.finish`` here on purpose: the case's index row is ``summary_row``'s, derived from the
        # component verdicts. A second write under the same case id would leave the artifact holding two
        # answers for one run, and the later one is the arithmetic of a mixed-mode guess.
        run.close()


def test_h2_the_shipped_canvas_completes_in_series(client, app_module, monkeypatch):
    """H2 — the same canvas switched to 串行, which is what weibo crawls are in anyway.

    Parallel is what the file stores, and on this platform the queue makes it one-at-a-time regardless
    (G1/G2 convict any switch that tries to unlock it). So H2 asks the question that is still open: when
    the canvas itself says 串行, does each component still open **its own record**, under its own name,
    with its own rows and its own console slice? A merged or mis-named record is a reporting bug the user
    reads as 「跑丢了」, and it is the shape 串行 ×N chips exist to describe.
    """
    harness.real_jar(monkeypatch, app_module)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=1)
    workflow = accept.all_enabled(_acceptance_copy(start_time=f'{start}', end_time=f'{end}'))
    workflow['settings']['mode'] = 'serial'
    _on, _off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H2',
        mode='mixed',
        target=sum(part['ask'] for part in found),
        timeout=ACCEPTANCE_TIMEOUT,
    ) as run:
        run.wait()
        run.assert_l3()
        records = accept.records_by_node(client, found)
        for part in found:
            record = records[part['label']]
            assert record['mode'] == 'serial', f'{part["label"]} was filed as {record["mode"]!r}'
            assert record['workflow_name'] == part['label'], (
                f'a record named {record["workflow_name"]!r} instead of the component {part["label"]!r} '
                'is a row the panel cannot match to a workflow'
            )
            # 串行 means each workflow opened its own row **as it was reached**, so each one is one
            # workflow: a record here that claims four is the parallel naming leaking into a serial run,
            # and the 串行 ×N chip would then describe a run that never happened.
            assert int(record.get('wf_count') or 0) == 1, f'{part["label"]} carries wf_count={record.get("wf_count")}'
        silent, kept, asked, answers = accept.audit_components(
            run,
            records=records,
            case_id='H2',
            found=found,
            grade=lambda part, record, console: _grade_component(run, part, record),
        )
        assert not silent, f'components under target with no honest reason named: {silent}'
        for part in found:
            record = records[part['label']]
            if record['status'] != 'completed':
                refusals = accept.named_refusals(run._slice(part['label']), WEIBO_NAMED_DEATHS)
                assert refusals, (
                    f'{part["label"]} settled {record["status"]} and its own slice names no reason: '
                    f'{run._slice(part["label"])[-800:]}'
                )
        summary = accept.summary_row(run, case_id='H2', found=found, answers=answers, kept=kept, asked=asked)
        # The same four crawls as H1, one switch away: 串行 is the shape the user gets when he ticks it, so
        # it must also fill. Naming and record-per-component are what this cell is *about*; a green there
        # over tables nobody filled would be the same hollow pass §2 refuses.
        assert summary == harness.FULL, f'his canvas must work in 串行 too: {answers}'
        run.close()


# **H3 is deliberately absent here**, and the reason is a cost claim rather than a shortcut. Zhihu's third
# acceptance cell runs its canvas again as parallel+headless to prove the *browser pool* narrows to one
# walk. On weibo the pool cannot narrow, because ``serial_only`` already holds the lane — that is what
# G1/G2 measure — so the cell would repeat H1's four crawls to assert something this platform has no way
# to fail. The next platform with a real parallel axis gets it; §11's board carries this note so the
# absence is a decision someone can disagree with, not a gap nobody notices.
