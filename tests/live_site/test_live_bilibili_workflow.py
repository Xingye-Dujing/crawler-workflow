"""The B站 LIVE program: real runs through the app, judged by what the console says.

Same eight steps and the same shared machinery as ``test_live_douyin_workflow.py`` (the driver, the
console recorder, the FULL/NAMED_SHORT/SILENT_SHORT grader, the H-group acceptance kit) — nothing here
re-types the ~450-line walk. What is B站-specific is the **shape of "采不满"**, because B站 has three
different paging contracts and a silent drop each of them can produce:

* **posts** page by ``&page=N`` and are *not* disjoint (measured 2026-09-29: page 3 delivered 18 fresh of
  35). The row budget is the pager, ``page=1`` renders zero cards (the bare URL is page one), and every
  number comes from ``x/web-interface/view?bvid=`` — so a card whose view call answers nothing (a WAF body,
  ``code`` absent) is the §6 U9 silent hole, now named ``crawl.bili.fetchEmpty``. A1 asserts the filed set
  equals the console's ``processed`` set, which is what catches a per-card drop that the summary would hide.
* **author** pages by a ``下一页`` that **replaces** the screen (measured: a window/element scroll adds
  nothing; the button swaps in a fresh set, overlap 0, URL unchanged). This is §6 U53 — the old walk scrolled
  and watched the card *count*, so a prolific UP was capped at its first ~40 and the console said 已到列表末尾
  about a page that was never paged. **B1 is the live proof the fix works**: it asks a UP who publishes
  hundreds for more than one screen, so a walk that stopped at 40 goes red here.
* **hot** has two boards with opposite paging: ``popular`` pages (20 a page, disjoint) while ``ranking`` is
  one 100-item answer; asking past 100 must name the board's size (§7 "无 cap 行=修复项", now
  ``crawl.bili.rankingCapped``).
* **comments** have no DOM — ``x/v2/reply/main`` walked by the server's own cursor (a replaying cursor is the
  same silent-under-collect family; the walk stops on ``is_end`` or a page with no new rpid).

**Cost, stated because it is the user's account.** A 10-row search is ~10 unsigned ``view`` calls (cheap, no
navigation per row); an author walk is a screen of cards per ``下一页`` click; the board is one or two
requests; comments are cursor-paged API. Nothing here asks more than 50 rows. Run in batches, domestic
network, never unattended (B站 is ``parallel_recommended`` — two of its own sessions were watched to
coexist)::

    # -k matches SUBSTRINGS: name the cells, not the group letter.
    .venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn" \\
        tests/live_site/test_live_bilibili_workflow.py -k "a1 or b1" -p no:cacheprovider

**No case skips.** A refusal that names itself is asserted as what it is; the tier's skip allowance is a
closed list this file does not extend.
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

PLATFORM = 'bilibili'
REPO_ROOT = Path(__file__).resolve().parents[2]

#: B站's honest terminal lines on top of the shared ones — keys, not sentences (§5's rule). Only the
#: *site-shaped* exits are here: ``crawl.bili.no_more`` is what the page said (two screens of nothing new),
#: ``crawl.bili.authorNoVideos`` is an empty space and ``crawl.bili.rankingCapped`` is the board's own size.
#: ``crawl.bili.finished`` / ``crawl.bili.authorDone`` are deliberately **absent** — the code certifying its
#: own walk (「自己给自己发满分」), so a shortfall whose only line is one of those is SILENT.
BILI_LEGIT_EXITS = harness.SHARED_EXITS + (
    'crawl.bili.no_more',  # two pages in a row held nothing new: the pager ran out, said with its page number
    'crawl.bili.authorNoVideos',  # the space rendered no uploads at all
    'crawl.bili.rankingCapped',  # the board is the site's size, not our ceiling
)

#: Lines §5 has already caught *lying*. ``crawl.bili.empty_page`` is on that list by name ("慢渲染报没卡片"):
#: a page that had not finished hydrating reads as "no video cards", so it may not license a shortfall. A
#: console whose only exit line is empty_page grades SILENT, and the case says so — the W1 slow-network
#: family, not the site's answer.
BILI_LIES = ('crawl.bili.empty_page',)

#: Per-card refusals. They are **not** exits: ``fetchEmpty`` / ``goneVideo`` fire on a share of any walk of
#: real ids (a withdrawn video, a throttled ``view``), so whitelisting one would excuse any shortfall at all.
#: A1 grades them where they belong — counted per skipped card, not allowed to stand as the run's reason.
BILI_ROW_REFUSALS = ('crawl.bili.fetchEmpty', 'crawl.bili.goneVideo')

#: Refused **before the browser is pointed anywhere** — a fact about the input, not the site. 作者 is
#: free text; a display name addresses nobody (B站 routes a creator by numeric mid only), so guessing
#: would file some other UP's uploads under the name the user asked for.
BILI_AUTHOR_REFUSALS = ('crawl.bili.authorEmpty',)

#: The 18 columns a stored bilibili row carries — posts, author and hot all flatten through the same
#: ``_row``, so a row cannot disagree about what 播放数 means or where 链接 comes from across the modes.
POST_COLUMNS = (
    '标题',
    'UP主',
    'UP主ID',
    '正文',
    '发布时间',
    'BV号',
    '稿件ID',
    '合集',
    '分P数',
    '时长秒',
    '播放数',
    '点赞数',
    '投币数',
    '收藏数',
    '转发数',
    '弹幕数',
    '评论数',
    '链接',
)
COUNTER_COLUMNS = ('播放数', '点赞数', '投币数', '收藏数', '转发数', '弹幕数', '评论数')

#: The comment columns ``parse_bilibili_comments`` yields. 楼层 is a running number across the whole
#: thread (the panel walked by the cursor, not per-page restarts) and 评论ID is the de-dup identity.
COMMENT_COLUMNS = (
    '平台',
    '文章URL',
    '评论者',
    '评论者主页',
    '用户等级',
    '评论内容',
    '评论时间',
    '点赞数',
    '楼层',
    '评论ID',
    '父评论ID',
    '子回复数',
    '回复数',
)

#: A prolific educational UP — chosen so "one screen" is provably short of its whole catalogue, not so a
#: number is assumed. 黑马程序员 publishes hundreds of uploads (measured 2026-09-29: 40 cards on the first
#: screen, and the 下一页 pager swaps further), which is exactly the shape U53 capped.
AUTHOR_MID = '37974444'

#: A long-lived, heavily-commented video for the comment mode, taken from step-0's own search rows. It ages
#: on its own schedule: if it dies, D2's named per-link refusal is the site's answer about *that link*.
COMMENT_URL = 'https://www.bilibili.com/video/BV1qW4y1a7fU/'

KEYWORDS = {
    'A1': 'Python',
    'A2': '人工智能',
    'A3': '机器学习',
    'A5': '数据结构',
    'E1': '深度学习',
    'G1': ('前端开发', '后端开发'),
}

#: Budgets are the product's own worst cases stacked. One page's first content may take
#: ``Config.PAGE_WAIT_TIMEOUT`` (300 s) and a profile up to 900 s; a bilibili row is an unsigned ``view``
#: call, cheap, so a 50-row search is minutes. One number per cell, handed to ``RunDriver.wait``.
QUICK_TIMEOUT = 900.0
DEEP_TIMEOUT = 1800.0
COMMENT_TIMEOUT = 2400.0
STOP_DEADLINE = 900.0


# ─── the driver, bound to bilibili ──────────────────────────────────────


class LiveRun(driver.RunDriver):
    """B站's binding of the shared run driver: platform word, budget, vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = QUICK_TIMEOUT
    # B站 answers a logged-in profile intermittently; the designed cookie-death path is proved by E1/E2,
    # so a named session death in another cell is a WARN, not a conviction.
    NAMED_DEATH_OK = True

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return _vocabulary(mode, headless)


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines excuse a shortfall in this shape, and which are known liars.

    ``headless`` is not branched: since #148 B站 honours 无头 verbatim and nothing about its supply is
    measured to depend on the window. A second whitelist for a shape never measured would be a claim the
    next reader has to re-prove.
    """
    exits, liars = BILI_LEGIT_EXITS, BILI_LIES
    if mode == 'author':
        exits += BILI_AUTHOR_REFUSALS
    elif mode == 'comments':
        # A comment crawl ends on the reply API's own words; the search lines must not excuse it.
        exits, liars = (
            harness.SHARED_EXITS
            + (
                'comment.commentsClosed',  # the author closed the section: an answer, not a failure
                'comment.biliBadAnswer',  # reply/main refused with no rows collected
                'comment.status.blocked',  # the reply endpoint refused mid-thread
                'comment.status.dead',  # the link is unreadable (no aid came back)
            ),
            (),
        )
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


def author_canvas(target: int, author: str = AUTHOR_MID, *, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'author',
        settings=harness.run_settings('serial', headless),
        author=author,
        target_count=target,
        **overrides,
    )


def hot_canvas(target: int, board: str = 'popular', *, headless=False, **overrides):
    return harness.canvas_for(
        PLATFORM,
        'hot',
        settings=harness.run_settings('serial', headless),
        board=board,
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


def _assert_post_rows(rows, *, minimum: int, source: str = 'search') -> None:
    """The 18 columns, real integer counters, a unique BV号, and 链接 built from it — not a placeholder.

    ``作者``/UP主 and every counter come from ``x/web-interface/view`` (the card shows only a rounded 万
    label), so a row whose 播放数 is a string or whose 链接 disagrees with its BV号 is a crawler that
    guessed instead of read — the same discipline every video platform here holds.
    """
    assert len(rows) >= minimum, f'expected {minimum} rows, got {len(rows)}'
    ids = [str(row.get('BV号') or '') for row in rows]
    assert all(ids), f'a row with no BV号 cannot be de-duplicated or resumed: {ids[:6]}'
    assert len(set(ids)) == len(ids), f'{len(ids)} rows, {len(set(ids))} distinct BV号 — one video filed twice'
    for row in rows:
        missing = [column for column in POST_COLUMNS if column not in row]
        assert not missing, f'a column the crawler promised is absent ({source}): {missing}'
        assert str(row.get('标题') or '').strip() or str(row.get('正文') or '').strip(), f'a row with no text: {row}'
        assert str(row.get('UP主') or '').strip(), f'UP主 is blank, the view carried no owner: {row.get("BV号")}'
        for counter in COUNTER_COLUMNS:
            assert isinstance(row.get(counter), int), f'{counter} is not a number: {row.get(counter)!r}'
        link = str(row.get('链接') or '')
        assert link.endswith(f'{row["BV号"]}/'), f'链接 and BV号 disagree: {link}'


def _assert_comment_rows(rows, *, minimum: int) -> None:
    """Columns present, content non-empty, 楼层 a running number, 评论ID unique, the reply trace counted."""
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    floors = [int(row.get('楼层') or 0) for row in rows]
    assert floors == sorted(floors) and len(floors) == len(set(floors)), (
        f'楼层 is not a running number across the thread: {floors[:12]}'
    )
    ids = [str(row.get('评论ID') or '') for row in rows]
    assert all(ids) and len(set(ids)) == len(ids), f'评论ID must be unique and present: {ids[:6]}'
    for row in rows:
        missing = [column for column in COMMENT_COLUMNS if column not in row]
        assert not missing, f'a comment column the adapter promises is absent: {missing}'
        assert str(row.get('评论内容') or '').strip(), f'an empty comment row: {row}'
        assert isinstance(row.get('点赞数'), int), f'点赞数 is not a number: {row.get("点赞数")!r}'
        assert isinstance(row.get('子回复数'), int), (
            f'子回复数 is the trace that nested replies exist, so it must be counted, not blank: '
            f'{row.get("子回复数")!r}'
        )


# ─── A · 关键词搜索 (posts) ─────────────────────────────────────────────


def test_a1_a_search_delivers_rows_and_no_card_drops_in_silence(client, app_module, monkeypatch):
    """A1 — 10 rows, the 18 columns, and every filed id narrated (the U9 hole, closed).

    The claim beyond "count arrived": the set the console announced as ``processed`` must equal the set in
    the table. A card the ``view`` endpoint answered with nothing (a WAF body, ``code`` absent) used to cost
    a request and produce neither a row nor a word (§6 U9) — a summary of 10 could hide 2 silently-dropped
    cards. Now each drop names itself, and if the walk still comes up short the table and the console can
    no longer quietly agree on a smaller number than the pager offered.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, posts_canvas(10, KEYWORDS['A1']), case_id='A1', mode='posts', target=10) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'10 rows is well under one search page: {answer}'
        assert run.rows() == 10, run.record
        rows = run.preview('node-1')
        _assert_post_rows(rows, minimum=10)
        filed = {str(row['BV号']) for row in rows}
        named = set(harness.slots_from(run.rec.lines, 'crawl.bili.processed', 'i'))
        assert named == filed, (
            f'the console filed {sorted(named)} while the table holds a different set: {sorted(filed)}'
        )
        dropped = sum(run.rec.counts_key(one) for one in BILI_ROW_REFUSALS)
        assert dropped == 0 or run.rec.counts_key('crawl.bili.finished'), (
            f'{dropped} cards were refused; each must name itself, not vanish between the page line and the summary'
        )
        run.finish(answer=answer)


def test_a2_a_headless_search_is_full_or_named(client, app_module, monkeypatch):
    """A2 — 无头 is honoured verbatim on B站 since #148; if it is refused, the console must say so.

    The claim is not "headless works" (measured once, can rot) but "if it does not, the run names why": a
    0-row headless search that blamed the keyword would be the same lie the visible path refuses.
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
        rows = run.preview('node-1')
        if rows:
            _assert_post_rows(rows, minimum=len(rows), source='headless')
        for key in ('crawl.loginWall', 'crawl.riskBlocked'):
            for where in harness.slots_from(run.rec.lines, key, 'where'):
                assert 'bilibili' in str(where).lower(), f'{key} named {where!r}, which is not a bilibili address'
        run.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


def test_a3_the_target_is_a_ceiling_the_walk_lands_on_exactly(client, app_module, monkeypatch):
    """A3 — 5 asked, 5 stored; rows filed after the ask is met are 多采 and each costs a ``view`` call.

    The pager advances only when a page is not yet exhausted, so the other half of 「完全符合要求」 here is
    that a 5-row ask does not walk a second page: ``crawl.bili.url`` is printed once (page 1), never twice.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 5
    with LiveRun(
        client, app_module, posts_canvas(asked, KEYWORDS['A3']), case_id='A3', mode='posts', target=asked
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        assert len(rows) == asked, f'{asked} asked, {len(rows)} filed: {run.rec.lines[-8:]}'
        _assert_post_rows(rows, minimum=asked)
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the keyword is abundant, so {asked} rows must arrive: {answer}'
        run.finish(answer=answer)


def test_a5_a_second_run_of_the_same_ask_is_refused_by_name_not_by_silence(client, app_module, monkeypatch):
    """A5 — running the same canvas twice must not quietly produce a second, half-empty table.

    ``recrawl`` is off by default, so the incremental ledger owns the rows this fingerprint already paid
    for: the honest second answer is 0 new rows **and a sentence saying the ledger skipped them** — without
    it a repeat that collected nothing reads identically to a wall or a bad keyword.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 5
    canvas = posts_canvas(asked, KEYWORDS['A5'])
    with LiveRun(client, app_module, canvas, case_id='A5', mode='posts', target=asked, timeout=DEEP_TIMEOUT) as run:
        run.wait()
        first = run.rows()
        assert first == asked, f'the first pass must fill the ask before a repeat means anything: {first}'
        run.finish(answer=run.verdict())

    with LiveRun(
        client, app_module, canvas, case_id='A5.repeat', mode='posts', target=asked, timeout=DEEP_TIMEOUT
    ) as again:
        again.wait()
        kept = again.rows()
        answer = again.verdict()
        assert kept == 0, f'the repeat re-collected {kept} rows the ledger already owns: {answer}'
        named = [key for key in ('run.dedupe_skipped', 'run.dedupe_all_skipped') if again.rec.counts_key(key)]
        assert named, f'a repeat filed nothing and named no ledger refusal: {again.rec.lines[-8:]!r}'
        again.finish(answer=answer, rows=0, warn=True)


# ─── B · 某作者的作品 (the 下一页 pager — U53's live proof) ──────────────


def test_b1_the_next_button_pager_walks_past_one_screen(client, app_module, monkeypatch):
    """B1 — the space page is walked by 下一页, so an ask past the first screen lands (U53, closed).

    Measured 2026-09-29 on the production profile: a prolific UP renders ~40 ``.bili-video-card`` and
    **neither a window nor an element scroll adds another**, while clicking 下一页 replaces the screen with a
    fresh ~40 (overlap 0). The old ``author()`` scrolled and watched the card count, so it declared the walk
    exhausted at ~40 and printed 已到列表末尾 about a creator with hundreds — a silent 漏采 on the whole mode.
    Asking this UP for 50 therefore fails on any build that regressed to the scroll model, and passes only if
    the walk actually pressed the pager. If this cell goes red with the fix in place, the UP shrank — the
    console's ``crawl.bili.authorDone`` reason says which.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 50
    with LiveRun(
        client, app_module, author_canvas(asked), case_id='B1', mode='author', target=asked, timeout=DEEP_TIMEOUT
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, (
            f'this UP publishes hundreds of uploads, so 50 must arrive across more than one screen; got {answer}'
        )
        assert len(rows) > 40, (
            f'only {len(rows)} rows — the walk stopped at the first screen, which is the U53 bug (scroll, not 下一页)'
        )
        _assert_post_rows(rows, minimum=len(rows), source='author')
        # Identity is the UP we asked for: every row must be one of his own, never a recommended stranger.
        assert all(str(row.get('UP主ID')) == AUTHOR_MID for row in rows), (
            f'an author row is not the requested UP: {sorted({row.get("UP主ID") for row in rows})}'
        )
        run.finish(answer=answer)


def test_b2_a_display_name_is_refused_because_it_addresses_nobody(client, app_module, monkeypatch):
    """B2 — 作者 is free text, so a name typed into it is refused, not guessed at.

    B站 addresses a creator by a numeric mid (or a space link); guessing from a display name would open
    *somebody's* space and report their uploads as the ones the user asked for. Refused before the browser
    is pointed anywhere, so nothing is paid for.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, author_canvas(5, '漫士沉思录'), case_id='B2', mode='author', target=5) as run:
        run.wait()
        assert harness.names_key(run.rec.text, 'crawl.bili.authorEmpty'), (
            f'a name that addresses nobody was not refused by name: {run.rec.lines[-8:]}'
        )
        assert run.rows() == 0, 'the unreadable author still produced a table'
        assert run.record['status'] == 'failed', run.record
        answer = run.verdict(rows=0)
        assert answer['verdict'] == harness.NAMED_SHORT, f'an unreadable author must name itself: {answer}'
        run.finish(answer=answer, rows=0, warn=True)


# ─── C · 热榜 (popular pages; ranking is one board of its own size) ─────


def test_c1_the_popular_board_pages_without_a_per_row_request(client, app_module, monkeypatch):
    """C1 — 热门 is a paged feed (20 a page, page 2 disjoint), and the row shape matches search.

    This is the mode the notes measured as carrying ``owner``/``stat`` inline: the cost axis is pages, not
    rows, so 40 rows arrive across two board reads and never 40 detail calls.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 40
    with LiveRun(client, app_module, hot_canvas(asked, 'popular'), case_id='C1', mode='hot', target=asked) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the popular feed is unbounded, so 40 must arrive: {answer}'
        rows = run.preview('node-1')
        assert len(rows) == asked, rows[:2]
        _assert_post_rows(rows, minimum=asked, source='popular')
        run.finish(answer=answer)


def test_c2_asking_past_the_ranking_names_the_board_size(client, app_module, monkeypatch):
    """C2 — 排行榜 is exactly 100 items (measured); an ask past it ends BY NAME, not with silence.

    §7 recorded this as a fix item: the old code answered a 150-ask with only ``hotDone 共 100 条`` — a bare
    number that reads as a shortfall we failed to fill rather than a board the site has only that big. Now
    ``crawl.bili.rankingCapped`` carries the site's own figure, and the table matches it. 150 is a floor,
    not an expectation: the day the board grows past it, this cell goes green on a full table.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 150
    with LiveRun(client, app_module, hot_canvas(asked, 'ranking'), case_id='C2', mode='hot', target=asked) as run:
        run.wait()
        answer = run.verdict()
        rows = run.preview('node-1')
        capped = harness.numbers_from(run.rec.lines, 'crawl.bili.rankingCapped', 'n')
        if len(rows) < asked:
            assert answer['verdict'] == harness.NAMED_SHORT, f'an over-long board ask must name the cap: {answer}'
            assert capped, f'the cap line did not carry the board length it measured: {answer["reasons"]}'
            assert len(rows) == capped[-1], f'{len(rows)} rows for a board reported as {capped[-1]} long'
        else:
            assert not capped, f'the board supplied {len(rows)} rows and the walk still claimed a cap: {capped}'
            assert answer['verdict'] == harness.FULL, answer
        _assert_post_rows(rows, minimum=len(rows), source='ranking')
        run.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── D · 评论 (a reply API walked by the server's cursor) ───────────────


def test_d1_the_reply_cursor_walks_the_thread_and_every_row_is_real(client, app_module, monkeypatch):
    """D1 — comments of one known video, read off ``x/v2/reply/main`` by its own cursor.

    B站 comments have **no DOM** — the reply API is the only path, and its ``next`` is a cursor, not a page
    counter (a replaying cursor would store the same 19 rows forever; §6's silent-under-collect family). The
    walk stops on ``is_end`` or a page with no new rpid. What this cell proves is the *reporting*: 楼层 runs
    across the whole thread (not restarts per page), 评论ID is unique, and every row carries content.
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
        assert len(rows) >= limit, f'a heavily-commented video must supply the capped ask of {limit}: {len(rows)}'
        _assert_comment_rows(rows, minimum=limit)
        assert {str(row.get('文章URL') or '') for row in rows} == {COMMENT_URL, COMMENT_URL.rstrip('/')}, rows[:2]
        run.finish(answer=answer, rows=len(rows))


def test_d2_a_link_that_refused_is_named_per_link(client, app_module, monkeypatch):
    """D2 — two links where one is garbage: the dead one is named, the good one still crawls.

    A per-article status is the difference between 「这条没有评论」 and 「这个链接读不出来」, and a batch that
    swallows the second as the first is how a user loses half his rows without seeing it. The dead address is
    a well-formed-but-nonexistent BV id, so what is under test is the *reporting*, not a URL typo.
    """
    harness.real_jar(monkeypatch, app_module)
    dead = 'https://www.bilibili.com/video/BV00000000000/'
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
        assert not any(dead in one for one in urls), 'a video that cannot exist stored rows anyway'
        named = [
            key
            for key in ('comment.status.dead', 'comment.biliBadAnswer', 'comment.status.blocked')
            if harness.names_key(run.rec.text, key)
        ]
        assert named, f'the dead link came back empty and nothing named how: {run.rec.lines[-8:]}'
        assert len(rows) >= 8, f'the readable link filed {len(rows)} of its 8-row ask: {run.rec.lines[-8:]!r}'
        assert not harness.names_key(run.rec.text, 'run.cookieExpired'), (
            f'a dead link was read as a dead session: {run.rec.lines[-8:]!r}'
        )
        _assert_comment_rows(rows, minimum=8)
        answer = run.verdict(rows=len(rows))
        assert answer['verdict'] == harness.NAMED_SHORT, (
            f'one link of two was unreadable, so the run must name that and not pass: {answer}'
        )
        run.finish(answer=answer, rows=len(rows), warn=True)


# ─── E · 停止 then 继续 (the pages already read must not be paid for twice) ─


def test_e1_stop_then_continue_resumes_on_the_page_it_died_on(client, app_module, monkeypatch):
    """E1+E2 — 停止 mid-walk, 继续 from the cursor: no re-paid page, no lost row, no repeat.

    The search cursor is the **page number** (a resumed run re-opens the pager at the page it died on), so
    the resume must not re-store a BV号 the first attempt already kept, and the cursor must hold position
    only — no id or link list smuggled in (AGENTS: a cursor records position, not content; that fix was paid
    for on xiaohongshu as §6 U5).
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 30
    canvas = posts_canvas(asked, KEYWORDS['E1'])
    with LiveRun(client, app_module, canvas, case_id='E1', mode='posts', target=asked, timeout=DEEP_TIMEOUT) as run:
        run.wait_until(lambda: run.live_rows() >= 4, within=STOP_DEADLINE, what='the crawl stored four rows')
        run.stop()
        run.wait()
        kept = run.rows()
        first_ids = {str(row.get('BV号') or '') for row in run.preview('node-1')}
        assert run.status['outcome'] == 'interrupted', run.status
        assert run.node()['status'] == 'partial', run.node()
        assert 4 <= kept < asked, f'a walk cut short is short of its target; it kept {kept}'
        assert run.status['failed_nodes'] == 0, f"停止 is the user's own button, not a failure: {run.status}"
        answer = run.verdict(rows=kept)
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.nodeStopped' in answer['reasons'], answer
        run.finish(answer=answer)

    with LiveRun(
        client,
        app_module,
        canvas,
        case_id='E2',
        mode='posts',
        target=asked,
        resume_run_id=run.run_id,
        queue=False,
        timeout=DEEP_TIMEOUT,
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, 'a resume that minted a new id is a second crawl, not 继续'
        assert again.rows() >= kept, f'the continue lost stored rows: {kept} → {again.rows()}'
        rows = again.preview('node-1')
        ids = [str(row.get('BV号') or '') for row in rows]
        assert first_ids <= set(ids), (
            f'继续 dropped {len(first_ids - set(ids))} of the {len(first_ids)} videos the first attempt '
            'already paid a view call for'
        )
        assert len(ids) == len(set(ids)), f'{len(ids)} rows but {len(set(ids))} distinct — 继续 re-filed a video'
        cursor = harness.cursor_of(again.record, 'node-1')
        smuggled = {key: value for key, value in cursor.items() if isinstance(value, (list, tuple, dict))}
        assert not smuggled, f'the resume cursor stores content, not position (U5 shape): {smuggled}'
        answer = again.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, f'继续 left the table short without naming why: {answer}'
        again.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── G · the platform's own axis: it is parallel_recommended ────────────


def test_g1_two_bilibili_searches_in_parallel_both_arrive(client, app_module, monkeypatch):
    """G1 — B站 is ``parallel_recommended`` (its own sessions were watched to coexist), so a parallel
    canvas must deliver both tables rather than silently dropping one behind a queue or a lane.

    The two lane switches are set **for this cell** and restored (they are global settings, not canvas
    settings — ``crawl_gate`` never reads the canvas block). Left at the defaults, the queue would hold the
    lane for the whole crawl and 乙 would arrive strictly after 甲 — real, but not the overlap this cell names.
    """
    harness.real_jar(monkeypatch, app_module)
    first, second = KEYWORDS['G1']
    canvas = harness.component_canvas(
        [
            {'platform': PLATFORM, 'mode': 'posts', 'label': '甲', 'params': {'keyword': first, 'target_count': 5}},
            {'platform': PLATFORM, 'mode': 'posts', 'label': '乙', 'params': {'keyword': second, 'target_count': 5}},
        ],
        settings=harness.run_settings('parallel', True),
    )
    with (
        harness.lane_switches(queue=False, stagger=0),
        LiveRun(client, app_module, canvas, case_id='G1', mode='posts', target=10, timeout=DEEP_TIMEOUT) as run,
    ):
        run.wait()
        record = run.refresh()
        left = run.component_verdict('甲', record, 'node-1', target=5, mode='posts')
        right = run.component_verdict('乙', record, 'node-3', target=5, mode='posts')
        run.audit(
            'G1.posts.node-1',
            verdict=left['verdict'],
            reasons=left['reasons'],
            rows=harness.stored_rows(record, 'node-1'),
            target=5,
            mode='posts',
            warn=left['verdict'] != harness.FULL,
        )
        run.audit(
            'G1.posts.node-3',
            verdict=right['verdict'],
            reasons=right['reasons'],
            rows=harness.stored_rows(record, 'node-3'),
            target=5,
            mode='posts',
            warn=right['verdict'] != harness.FULL,
        )
        assert left['verdict'] != harness.SILENT_SHORT, f'component 甲: {left}'
        assert right['verdict'] != harness.SILENT_SHORT, f'component 乙: {right}'
        if harness.stored_rows(record, 'node-3') == 0:
            walls = ('crawl.loginWall', 'crawl.riskBlocked')
            walled = [key for key in walls if harness.names_key(run.rec.text, key)]
            assert walled, f'the second workflow filed nothing and nothing named why: {left} / {right}'
        for node in ('node-1', 'node-3'):
            rows = run.preview(node)
            if rows:
                _assert_post_rows(rows, minimum=len(rows), source='parallel')
        kept = harness.stored_rows(record, 'node-1') + harness.stored_rows(record, 'node-3')
        run.finish(answer=left, rows=kept, warn=harness.NAMED_SHORT in (left['verdict'], right['verdict']))


# ─── H · 用户自己的画布（§11 第 8 步：旗舰是他点 Run 那张）─────────────

#: His B站 canvas, saved by hand: keyword search, 某作者, 热门榜, 评论, 周排行榜 — five source nodes,
#: each wired to an 输出 node. §9 read all five as ``enabled: true`` (archived parallel+headless), so the
#: as-saved run crawls all five; ``all_enabled`` is applied anyway so a future edit that switched one off is
#: caught rather than silently shortening the flagship leg.
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：哔哩哔哩.json'

#: Five components — two search-shaped crawls at 50 each, an author walk past one screen, the boards and one
#: comment thread. The comment leg is the unbounded one, so the budget is the crawl cells plus the comment one.
ACCEPTANCE_TIMEOUT = 2 * DEEP_TIMEOUT + COMMENT_TIMEOUT


def _llm_block() -> dict:
    """The AI transport block his panel would send, with the model read off the local daemon.

    His canvas ends a chain in an LLM node, and ``app.py`` refuses such a run *before it starts* unless the
    request names a model (``api.needOllamaModel``); the choice lives in the browser, not the canvas, so the
    harness states it — read from the daemon rather than pasted, so a reworded model tag does not turn the
    acceptance run red for the test's own staleness.
    """
    from analyzers.llm_client import list_ollama_models
    from config import Config

    models = list_ollama_models(Config.OLLAMA_HOST)
    assert models, f'the local daemon at {Config.OLLAMA_HOST} lists no chat model, so the AI leg cannot run'
    return {'provider': 'ollama', 'model': str(models[0]), 'ollama_host': Config.OLLAMA_HOST}


def test_h1_the_shipped_canvas_runs_and_every_leg_accounts_for_itself(client, app_module, monkeypatch):
    """H1 — 测试：哔哩哔哩.json at his parameters, five legs, each accounting for itself.

    The canvas is his, the parameters are his; the question is whether a run he starts from the panel leaves
    a table, a record and an export that agree — per component. ``audit_components`` writes one ledger row
    per leg and derives the case's index row from those five, so a case cannot certify itself FULL by hand.
    The only thing the copy changes is which nodes are switched on (plan decision D5); no ask, keyword or
    link is touched.
    """
    harness.real_jar(monkeypatch, app_module)
    opened = accept.workflow_file(ACCEPTANCE_FILE)
    workflow = accept.all_enabled(opened)
    _on, off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    assert len(found) == 5, f'this case is written against the five source nodes he saved: {found}'
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
        for part in found:
            rows = run.preview(part['source'], workflow_name=part['label'])
            if part['mode'] == 'comments':
                if rows:
                    _assert_comment_rows(rows, minimum=1)
            else:
                _assert_post_rows(rows, minimum=1, source=f'H1 {part["label"]}')
        summary = accept.summary_row(run, case_id='H1', found=found, answers=answers, kept=kept, asked=asked)
        run.finish(rows=kept, target=asked, warn=summary != harness.FULL)
