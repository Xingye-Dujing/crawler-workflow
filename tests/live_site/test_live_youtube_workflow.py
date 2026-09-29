"""The YouTube LIVE program: real runs through the app, judged by what the console says.

Same eight steps and the same shared machinery as ``test_live_bilibili_workflow.py`` (the driver, the
console recorder, the FULL/NAMED_SHORT/SILENT_SHORT grader, the H-group acceptance kit) — nothing here
re-types the ~450-line walk. What is YouTube-specific is that the crawl is **JSON run inside a loaded
page**, which reshapes three things the other platforms do not have to think about:

* **It needs no session at all** (``crawler_notes``: every measured round worked logged out, and the
  crawler keeps no cookie host), so a cookie death is not this platform's ordinary answer and stays a
  red — unlike bilibili, where the profile answers an intermittent wall. YouTube is also the one
  overseas platform explicitly *allowed* to run headless (headless answered the identical rows and
  player facts), so A4 asserts 无头 is honoured rather than excused.
* **``with_facts`` is a real fork, not a label.** The search card carries no 点赞数 and only a rounded
  "1.2M views" 播放数; the per-row ``player`` call is the *only* source of both. So the fast path
  (``with_facts=False``) must arrive FULL with 点赞数 **0 in every row** — a fast path that somehow
  grew likes means the fork is not wired, and a facts path where no row carries a like means the detail
  round trip silently failed. That is the load-bearing shape of "采不满" here.
* **A search cursor is a ``continuation`` token, and the ids live in the rows, not the cursor**
  (``_collected_ids`` reads them off stored rows). E1 proves the resumed walk re-opens at the cursor and
  smuggles no id list into it — §6 U5's rule, the one paid for on xiaohongshu, asserted positively here.

Modes (``crawl_capabilities``): ``posts`` (keyword search, ``with_facts``), ``author`` (one channel's
uploads, paged by ``browse`` continuation), ``comments`` (the ``next`` pager read as JSON — the panel
grows 20 a round by cursor, so >20 rows is the only proof the cursor was followed). There is **no
``hot`` board**, so the dedupe-repeats cell (C1) runs on the only stable supply YouTube has — one video's
comment thread. A channel's initial 视频 document **rotates its batch between loads** exactly like a
keyword search does (measured live 2026-09-29: asking the same channel twice handed back two different
ten), so no crawl-shaped re-run is a real cross-run dedupe case here (§6 U26's rule, re-paid on YouTube).

**Cost, stated because it is the user's account — but YouTube spends none of a login.** A search is one
page load then ~10 rows per 0.68 s JSON round; a facts row adds one 0.31 s ``player`` call; comments are
``next`` JSON rounds. Nothing here asks more than 60 rows. Run in batches on the VPN network (YouTube is
``region='overseas'`` → ``live_os``), never unattended::

    # -k matches SUBSTRINGS: name the cells, not the group letter.
    .venv/Scripts/python.exe -m pytest -q -m "live_site and live_os" \\
        tests/live_site/test_live_youtube_workflow.py -k "a1 or b1" -p no:cacheprovider

**No case skips.** A refusal that names itself is asserted as what it is; the tier's skip allowance is a
closed list this file does not extend.
"""

import csv
import os
from pathlib import Path

import live_acceptance as accept
import live_run_driver as driver
import live_run_harness as harness
import pytest

from crawlers.youtube import video_id_of
from utils.helpers import sanitize_filename

pytestmark = [
    pytest.mark.live_site,
    pytest.mark.live_os,
    pytest.mark.enable_socket,
    pytest.mark.serial,
]

PLATFORM = 'youtube'
REPO_ROOT = Path(__file__).resolve().parents[2]

#: YouTube's honest terminal lines on top of the shared ones — keys, not sentences (§5's rule). Only the
#: *site-shaped* stops are here: ``crawl.yt.drained`` is "the API stopped handing out a cursor" (the list
#: really ran out), ``crawl.yt.replay`` is "the cursor came back onto itself" (exhausted or shuffled),
#: ``crawl.yt.noPage``/``noResults`` are the pager and the keyword answering nothing, and
#: ``crawl.yt.wall``/``noContext`` are the page itself refusing — a human-verification wall, or a document
#: that exposed no innertube config because it was intercepted (the headless shape A4 must read as NAMED,
#: not convict as silent; ``noContext`` is what ``search()``/``author()`` raise, so without it an
#: intercepted-but-named run would grade SILENT). ``crawl.yt.finished`` / ``targetReached`` stay **absent**
#: — the code certifying its own walk ("自己给自己发满分"), so a shortfall whose only line is one of those is SILENT.
YT_SEARCH_EXITS = harness.SHARED_EXITS + (
    'crawl.yt.drained',  # the continuation ran out: the search list is the site's length, not our ceiling
    'crawl.yt.replay',  # a round added nothing new and the walk judged the list exhausted
    'crawl.yt.noPage',  # a round returned no items at all: the pager said stop
    'crawl.yt.noResults',  # the keyword matched no public video (or this anonymous session was throttled)
    'crawl.yt.wall',  # a human-verification page was served: named, so a shortfall is not silent
    'crawl.yt.noContext',  # the page exposed no innertube config (intercepted, or the DOM changed)
)

#: Author mode's only short stops are the channel's cursor running out (``drained``, §6 U14) and the three
#: author refusals — ``authorEmpty``/``authorNotFound``/``authorNoVideos`` each name the channel they
#: could not read — plus the same two page-shaped refusals a search names. The search-only lines are
#: deliberately **not** here: author() never prints them, and a whitelist carrying a sentence a mode cannot
#: say is how one mode's silence gets excused by another's.
YT_AUTHOR_EXITS = harness.SHARED_EXITS + (
    'crawl.yt.drained',
    'crawl.yt.wall',
    'crawl.yt.noContext',
    'crawl.yt.authorEmpty',  # no creator was given (a bare address with no handle/id in it)
    'crawl.yt.authorNotFound',  # the address is not a channel page, so it carries no UC… id to page by
    'crawl.yt.authorNoVideos',  # the channel's own 视频 tab holds nothing
)

#: A comment crawl ends on the comment engine's own words; the search lines must not excuse it.
#: ``commentsClosed`` is the author turning the section off (an answer, not a failure), ``ytNoPage`` a
#: link that never booted as a watch page, and ``status.blocked``/``status.dead`` are the per-link
#: engine verdicts the node prints for *that* URL.
YT_COMMENT_EXITS = harness.SHARED_EXITS + (
    'comment.commentsClosed',
    'comment.ytNoPage',
    'comment.status.blocked',
    'comment.status.dead',
)

#: Per-round transport refusals. They are **not** exits: ``callFailed``/``badAnswer`` fire on a share of
#: any walk (one JS round that answered non-JSON), and a shortfall whose only lines are those is the
#: transport failing to reach the target — a finding, not the site honestly running out. A1 grades them
#: where they belong (against the per-row ``processed`` count), never as the run's excuse.

#: The 12 columns both list readers (``row_from_video_renderer`` for search, ``row_from_lockup`` for a
#: channel tab) lay down before ``apply_player``. 分类/是否直播/频道链接 come only from the player, so
#: they are checked in the facts cell, never promised here.
POST_COLUMNS = (
    '标题',
    '正文',
    '作者',
    '视频ID',
    '链接',
    '播放数',
    '点赞数',
    '发布时间',
    '时长',
    '时长秒',
    '频道ID',
    '图片链接',
)
COUNTER_COLUMNS = ('播放数', '点赞数', '时长秒')

#: The comment columns ``parse_youtube_comments`` yields. 评论ID (``properties.commentId``) is the dedupe
#: identity across a resume; 楼层 keeps a reply-under-a-reply on its thread so "what did people say" can
#: tell a thread from a top-level comment.
COMMENT_COLUMNS = (
    '平台',
    '文章URL',
    '评论者',
    '评论者主页',
    '评论者ID',
    '评论内容',
    '评论时间',
    '点赞数',
    '回复数',
    '楼层',
    '评论ID',
    '是否作者回复',
    '视频ID',
)

#: A prolific channel with thousands of public uploads and open comments — chosen so a 60-row ask is
#: provably short of one screen's worth and past a single document page (measured: the 视频 document
#: carries ~30 items, each ``browse`` round ~55). NASA is also the channel the low-level live file
#: (``test_live_youtube.py``) and the user's own flagship both point at, so the identity claim ("one
#: channel was asked for, one answered") is checked against the same supply the panel exercises.
AUTHOR_HANDLE = 'NASA'

#: A permanently-open, always-playable, heavily-commented thread — YouTube's own first video, "Me at
#: the zoo" (jawdz, 20 years up, tens of millions of comments). Chosen over a music video because the
#: current exit can be served a geo/playback block on VEVO content (measured live 2026-09-29 on the
#: flagship's own Shape-of-You link: the watch page loaded fine, innertube ready, but the body printed
#: 「该视频无法再播放」 and the comment walk honestly answered ``comment.commentsClosed`` — a real site
#: answer that would have failed D1 for the video's sake, not the crawl's). This one has no licensing
#: story and no region wall, so a short answer here can only be the cursor, not the day.
COMMENT_URL = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'

#: A link that names no video at all: ``video_id_of('.../@NASA')`` is empty, so the engine refuses it
#: DEAD before it ever opens a watch page — the per-link refusal that must not be read as a dead session.
NOT_A_VIDEO_URL = 'https://www.youtube.com/@NASA'

KEYWORDS = {
    'A1': '人工智能',
    'A2': 'Python',
    'A3': 'machine learning',
    'A4': 'travel vlog',
    'C1': 'NASA',
    'E1': 'deep learning',
}

#: Budgets are the product's own worst cases stacked. A boot is one page load (``Config.PAGE_WAIT_TIMEOUT``
#: 300 s ceiling); a facts row is a 0.31 s ``player`` call; comments are ``next`` rounds behind a watch-page
#: load. YouTube is JSON-fast, so these are generous rather than tight. One number per cell, handed to
#: ``RunDriver.wait``. The single-mode cells never ask past 60; the H-group flagship runs the user's own three
#: legs at his numbers (search 50 + author 50 + comments 50), which is the only run that exceeds 60 rows.
QUICK_TIMEOUT = 600.0
DEEP_TIMEOUT = 1200.0
COMMENT_TIMEOUT = 1500.0
STOP_DEADLINE = 600.0


# ─── the driver, bound to YouTube ───────────────────────────────────────


class LiveRun(driver.RunDriver):
    """YouTube's binding of the shared run driver: platform word, budget, mode vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = QUICK_TIMEOUT
    # A cookie death is NOT YouTube's ordinary answer — the crawl needs no session and is measured to work
    # logged out — so a named session death in any cell is a genuine product fault (the innertube transport
    # mistaking a JSON refusal for a wall), not something to carry as a WARN. Kept False.
    NAMED_DEATH_OK = False

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return _vocabulary(mode, headless)


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines excuse a shortfall in this shape, and which are known liars.

    ``headless`` is not branched: YouTube is measured to answer a headless window with the identical rows
    and player facts, and nothing about its supply depends on the screen. A second whitelist for a shape
    never measured would be a claim the next reader has to re-prove.
    """
    if mode == 'author':
        return YT_AUTHOR_EXITS, ()
    if mode == 'comments':
        return YT_COMMENT_EXITS, ()
    return YT_SEARCH_EXITS, ()


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


def author_canvas(target: int, author: str = AUTHOR_HANDLE, *, headless=False, **overrides):
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


def _assert_video_rows(rows, *, minimum: int, source: str = 'search', expect_facts=False) -> None:
    """The 12 list columns, real integer counters, a unique 视频ID, and 链接 built from that id.

    Both card readers flatten through the same keys, so a row cannot disagree about where 播放数 or 链接
    comes from across search and author. ``expect_facts`` additionally requires the table to have *paid*
    for the detail round trip — at least one row carrying a like, since 点赞数 exists nowhere but the
    ``player`` answer — which is the only way a facts crawl that silently skipped every player call is
    caught without trusting a single row's value.
    """
    assert len(rows) >= minimum, f'expected {minimum} rows, got {len(rows)}'
    ids = [str(row.get('视频ID') or '') for row in rows]
    assert all(ids), f'a row with no 视频ID cannot be de-duplicated or resumed: {ids[:6]}'
    assert len(set(ids)) == len(ids), f'{len(ids)} rows, {len(set(ids))} distinct 视频ID — one video filed twice'
    for row in rows:
        missing = [column for column in POST_COLUMNS if column not in row]
        assert not missing, f'a column the crawler promised is absent ({source}): {missing}'
        assert str(row.get('标题') or '').strip(), f'a row with no title: {row.get("视频ID")}'
        assert str(row.get('作者') or '').strip(), f'作者 is blank, neither the card nor the player named it: {row}'
        link = str(row.get('链接') or '')
        assert link.startswith('https://www.youtube.com/watch?v='), f'not a watch link ({source}): {link}'
        assert video_id_of(link) == row['视频ID'], f'链接 and 视频ID disagree: {link}'
        for counter in COUNTER_COLUMNS:
            assert isinstance(row.get(counter), int), f'{counter} is not a number: {row.get(counter)!r}'
    # A live / premiere / upcoming card carries no view text and the player omits viewCount, so 播放数 can be
    # a real 0 — requiring >0 per row would red an honest table. It must be a non-negative integer, and the
    # caller asserts positivity where the supply guarantees it (the abundance cells).
    assert all(isinstance(row.get('播放数'), int) and row['播放数'] >= 0 for row in rows), (
        f'播放数 must be a non-negative integer count: {[row.get("播放数") for row in rows[:6]]}'
    )
    if expect_facts:
        assert any(row['点赞数'] > 0 for row in rows), (
            f'no row carried 点赞数 — the per-row detail round trip never paid, yet with_facts was on ({source})'
        )


def _assert_comment_rows(rows, *, minimum: int, url: str) -> None:
    """Columns present, content non-empty, 评论ID unique, 楼层 a floor, every row filed under the link."""
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    ids = [str(row.get('评论ID') or '') for row in rows]
    assert all(ids) and len(set(ids)) == len(ids), f'评论ID must be present and unique (the dedupe key): {ids[:6]}'
    floors = [int(row.get('楼层') or 0) for row in rows]
    assert all(floor >= 1 for floor in floors), f'every comment sits on a floor (reply-level + 1): {floors[:12]}'
    for row in rows:
        missing = [column for column in COMMENT_COLUMNS if column not in row]
        assert not missing, f'a comment column the adapter promises is absent: {missing}'
        assert str(row.get('评论内容') or '').strip(), f'an empty comment row: {row}'
        assert str(row.get('平台') or '') == 'youtube', f'a comment not tagged as youtube: {row.get("平台")}'
        assert str(row.get('文章URL') or '') == url, 'a comment must be filed under the video it came from'
        for counter in ('点赞数', '回复数'):
            assert isinstance(row.get(counter), int), f'{counter} is not a number: {row.get(counter)!r}'


# ─── A · 关键词搜索 (posts) ─────────────────────────────────────────────


def test_a1_a_search_delivers_rows_and_the_summary_ties_the_table(client, app_module, monkeypatch):
    """A1 — 10 facts rows, the 12 columns, and every filed row narrated (the per-card-drop hole, closed).

    The claim beyond "count arrived": the number the ``finished`` line printed equals the table, and the
    ``processed`` line fired exactly once per stored row. ``_harvest`` logs ``processed`` only when the
    row actually lands, so a search whose summary said 10 while the table held 8 (a round that answered
    non-JSON and was skipped without a word) cannot quietly agree on the smaller figure — that is
    YouTube's face of §6 U9. 点赞数 > 0 on some row proves the player calls were genuinely paid for.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(client, app_module, posts_canvas(10, KEYWORDS['A1']), case_id='A1', mode='posts', target=10) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'10 rows is well under two search rounds: {answer}'
        rows = run.preview('node-1')
        _assert_video_rows(rows, minimum=10, expect_facts=True)
        # Two-sided: a 人工智能 search is abundant with real videos, so most rows must carry a positive view
        # count — and if the day is thin, the count is reported, not silently accepted.
        played = sum(1 for row in rows if row['播放数'] > 0)
        assert played >= len(rows) // 2, f'only {played} of {len(rows)} rows carried a 播放数 for an abundant keyword'
        finished = harness.numbers_from(run.rec.lines, 'crawl.yt.finished', 'n')
        assert finished and finished[-1] == len(rows), f'the summary said {finished}, the table holds {len(rows)}'
        said = run.rec.counts_key('crawl.yt.processed')
        assert said == len(rows), f'{said} processed lines for {len(rows)} stored rows — a row dropped in silence'
        run.finish(answer=answer)


def test_a2_the_fast_path_arrives_full_and_pays_for_nothing_extra(client, app_module, monkeypatch):
    """A2 — ``with_facts=False`` is the fast path and still returns rows, with 点赞数 blank everywhere.

    The fork is real or it is a label: the search card carries no like count and only a rounded view
    label, so a fast crawl that did not call ``player`` must leave 点赞数 at 0 in *every* row. Any non-zero
    like here means the fork is not honoured and the crawl paid the per-row round trip it was told to skip;
    a 0-row fast crawl would be the same 采不满 the facts path refuses. Both directions are asserted.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        posts_canvas(10, KEYWORDS['A2'], with_facts=False),
        case_id='A2',
        mode='posts',
        target=10,
    ) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the keyword is abundant even without detail calls: {answer}'
        rows = run.preview('node-1')
        _assert_video_rows(rows, minimum=10, source='fast path')
        assert all(row['点赞数'] == 0 for row in rows), 'the fast path paid for detail calls it was told to skip'
        run.finish(answer=answer)


def test_a3_the_target_is_a_ceiling_the_walk_lands_on_exactly(client, app_module, monkeypatch):
    """A3 — 5 asked, 5 stored, and the pager is never advanced past the ask.

    ``_harvest`` returns the moment ``collected()`` reaches the target, so a 5-row ask must not walk a
    second page: ``crawl.yt.page`` prints once (round 1 yields ~10 fresh, the ask is met inside it).
    Over-collecting each costs an unnecessary ``player`` call on the facts path — the other half of
    "完全符合要求" is that the walk stops exactly where it was told to.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 5
    with LiveRun(
        client, app_module, posts_canvas(asked, KEYWORDS['A3']), case_id='A3', mode='posts', target=asked
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        assert len(rows) == asked, f'{asked} asked, {len(rows)} filed: {run.rec.lines[-8:]!r}'
        _assert_video_rows(rows, minimum=asked)
        rounds = run.rec.counts_key('crawl.yt.page')
        assert rounds == 1, f'the walk read {rounds} pages for a {asked}-row ask — it paged past the ceiling'
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'the keyword is abundant, so {asked} rows must arrive: {answer}'
        run.finish(answer=answer)


def test_a4_a_headless_search_is_full_or_named(client, app_module, monkeypatch):
    """A4 — YouTube is allowed to run headless (measured identical rows and player facts); a refusal is named.

    The claim is not "headless works" (it does, and nothing about its supply depends on the window) but
    "if it ever stops working, the run names why": a 0-row headless search that blamed nothing would be
    the silent under-report the whole tier exists to catch. 点赞数 is checked only when rows arrive, so a
    genuine throttle that named itself never trips on a missing like.
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client,
        app_module,
        posts_canvas(10, KEYWORDS['A4'], headless=True),
        case_id='A4',
        mode='posts',
        target=10,
        timeout=DEEP_TIMEOUT,
    ) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, f'a headless search said nothing about being short: {answer}'
        rows = run.preview('node-1')
        if rows:
            _assert_video_rows(rows, minimum=len(rows), source='headless')
        for key in ('crawl.loginWall', 'crawl.riskBlocked'):
            for where in harness.slots_from(run.rec.lines, key, 'where'):
                assert 'youtube.com' in str(where).lower(), f'{key} named {where!r}, which is not a YouTube address'
        run.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── B · 某频道作品 (browse continuation — the U14 drained line) ─────────


def test_b1_an_author_walk_pages_past_the_loaded_document(client, app_module, monkeypatch):
    """B1 — the channel tab is paged by ``browse`` continuation, so an ask past one document lands.

    The first page is read out of the loaded 视频 document (~30 items, measured); everything after comes
    from following the ``continuation`` token. Asking this prolific channel for 60 therefore fails on any
    build that stopped at the document — a walk that never pressed the pager is capped near 30 and, before
    §6 U14, said so only as a bare ``finished n``. Now the only honest way to come up short is the channel
    running out, printed as ``crawl.yt.drained``; for NASA that cannot happen at 60, so FULL is required,
    and every row must carry the *same* UC… channel id (an author crawl mixing in a recommended stranger
    would read as a wide, working table).
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 60
    with LiveRun(
        client, app_module, author_canvas(asked), case_id='B1', mode='author', target=asked, timeout=DEEP_TIMEOUT
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'this channel has thousands of uploads, so 60 must arrive: {answer}'
        assert len(rows) > 30, (
            f'only {len(rows)} rows — the walk stopped at the loaded document and never followed the browse cursor'
        )
        _assert_video_rows(rows, minimum=len(rows), source='author', expect_facts=True)
        channel_ids = {str(row.get('频道ID') or '') for row in rows}
        assert channel_ids == {rows[0]['频道ID']} and rows[0]['频道ID'].startswith('UC'), (
            f'one channel was asked for and these answered: {sorted(channel_ids)}'
        )
        assert all(str(row.get('作者') or '').strip() for row in rows), 'every author row must name the creator'
        run.finish(answer=answer)


def test_b2_an_author_that_addresses_nothing_is_refused_by_name(client, app_module, monkeypatch):
    """B2 — a creator field with no handle or id in it is refused before the browser is pointed anywhere.

    ``channel_videos_url`` answers '' for a bare address that carries no ``@handle``/``UC…``/channel marker,
    and ``author`` raises ``crawl.yt.authorEmpty`` without a navigation — so nothing is paid for and no
    stranger's uploads are filed. Guessing a channel from a non-address would open *somebody's* space and
    report their uploads as the ones the user asked for; refused-by-name is the rule (AGENTS: anything that
    chooses data is refused by name, never guessed).
    """
    harness.real_jar(monkeypatch, app_module)
    with LiveRun(
        client, app_module, author_canvas(5, 'https://www.youtube.com/'), case_id='B2', mode='author', target=5
    ) as run:
        run.wait()
        assert harness.names_key(run.rec.text, 'crawl.yt.authorEmpty'), (
            f'a creator that addresses nothing was not refused by name: {run.rec.lines[-8:]!r}'
        )
        assert run.rows() == 0, 'the unreadable author still produced a table'
        assert run.record['status'] == 'failed', run.record
        answer = run.verdict(rows=0)
        assert answer['verdict'] == harness.NAMED_SHORT, f'an unreadable author must name itself: {answer}'
        run.finish(answer=answer, rows=0, warn=True)


# ─── C · 去重重复 (the stable supply: one video's comment thread) ───────


def test_c1_a_second_run_of_one_thread_is_refused_by_name_not_by_silence(client, app_module, monkeypatch):
    """C1 — re-running the same crawl must not quietly file a second, half-empty table.

    ``recrawl`` is off by default, so the incremental ledger owns the comment ids this fingerprint already
    paid for, and the honest second answer is *fewer-than-asked* rows **and a sentence saying the ledger
    skipped them** (``run.dedupe_skipped`` / ``dedupe_all_skipped``). The supply must be **stable**: a
    keyword batch rotates, and a channel's 视频 document rotates too (measured live 2026-09-29 — asking
    NASA twice gave two different tens), so neither is a real cross-run dedupe case (§6 U26). A single
    video's cursor-walked comment thread is the one stable supply: the same ids come back and the ledger
    refuses them. The assertion is ``kept < limit`` rather than a hard ``0`` because a brand-new comment
    can land in the top window between the two runs — a couple of genuinely-fresh rows is the site's
    answer, while re-filing the whole thread is the bug this catches.
    """
    harness.real_jar(monkeypatch, app_module)
    limit = 10
    canvas = comments_canvas(COMMENT_URL, limit=limit)
    with LiveRun(
        client, app_module, canvas, case_id='C1', mode='comments', target=limit, timeout=COMMENT_TIMEOUT
    ) as run:
        run.wait()
        first = run.rows()
        if first != limit:
            answer = run.verdict()
            assert answer['verdict'] == harness.NAMED_SHORT, (
                f'the thread answered neither full nor by name, so a repeat would mean nothing: {answer}'
            )
            run.finish(answer=answer, warn=True)
            return
        run.finish(answer=run.verdict())

    with LiveRun(
        client, app_module, canvas, case_id='C1.repeat', mode='comments', target=limit, timeout=COMMENT_TIMEOUT
    ) as again:
        again.wait()
        kept = again.rows()
        answer = again.verdict()
        assert kept < limit, f'the repeat re-filed the whole {limit}-row thread the ledger already owns: {answer}'
        named = [key for key in ('run.dedupe_skipped', 'run.dedupe_all_skipped') if again.rec.counts_key(key)]
        assert named, f'a repeat filed {kept} of {limit} and named no ledger refusal: {again.rec.lines[-8:]!r}'
        again.finish(answer=answer, rows=kept, warn=True)


# ─── D · 评论 (the comment pager followed past one round) ───────────────


def test_d1_the_comment_cursor_pages_past_the_first_screen(client, app_module, monkeypatch):
    """D1 — comments of the flagship's video, read by the ``next`` cursor, not by scrolling the panel.

    YouTube's comment panel grows 20 a round by token (measured); one round cannot supply 40, so a count
    past 20 is the proof the cursor was *followed*, and 评论ID uniqueness is the proof it was not
    re-followed onto page one (a sort-menu token re-reads the same 20 and the ledger refuses them — the
    walk would "succeed" on a 20-row thread). 楼层 keeps a reply-under-reply on its thread. The supply is
    a permanently-open, un-geo-blockable thread (see :data:`COMMENT_URL`), so a short answer here is the
    cursor, not the day or the region.
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
        assert len(rows) > 20, f'only {len(rows)} comments — one round, the cursor was not followed: {answer}'
        assert len(rows) >= limit, f'this video must supply the capped ask of {limit}: {len(rows)}'
        _assert_comment_rows(rows, minimum=limit, url=COMMENT_URL)
        run.finish(answer=answer, rows=len(rows))


def test_d2_a_link_with_no_video_is_named_per_link(client, app_module, monkeypatch):
    """D2 — two links where one names no video: the dead one is named, the good one still crawls.

    A link the engine cannot read (``video_id_of`` empty) comes back DEAD for *that* URL and must not be
    read as a dead session (AGENTS: an empty that names its refusal is the site's answer; a dead link is
    input age, not code). So the good video's comments still file, the run reports the dead link by name,
    and ``run.cookieExpired`` never fires — the exact confusion the douyin comment path documents.
    """
    harness.real_jar(monkeypatch, app_module)
    limit = 8
    with LiveRun(
        client,
        app_module,
        comments_canvas(f'{NOT_A_VIDEO_URL}\n{COMMENT_URL}', limit=limit),
        case_id='D2',
        mode='comments',
        target=2 * limit,
        timeout=COMMENT_TIMEOUT,
    ) as run:
        run.wait()
        rows = run.preview('node-1')
        urls = {str(row.get('文章URL') or '') for row in rows}
        assert NOT_A_VIDEO_URL not in urls, 'a link that names no video stored rows anyway'
        assert harness.names_key(run.rec.text, 'comment.status.dead'), (
            f'the unreadable link came back empty and nothing named how: {run.rec.lines[-8:]!r}'
        )
        assert len(rows) >= limit, f'the readable link filed {len(rows)} of its {limit}-row ask: {run.rec.lines[-8:]!r}'
        assert run.record.get('status') != 'failed' and not run.cookie_expired, (
            f'a dead link was read as a dead session: {run.rec.lines[-8:]!r}'
        )
        _assert_comment_rows(rows, minimum=limit, url=COMMENT_URL)
        answer = run.verdict(rows=len(rows))
        assert answer['verdict'] == harness.NAMED_SHORT, (
            f'one link of two was unreadable, so the run must name that and not pass: {answer}'
        )
        run.finish(answer=answer, rows=len(rows), warn=True)


# ─── E · 停止 then 继续 (the cursor is a continuation token, not an id list) ─


def test_e1_stop_then_continue_resumes_on_the_cursor_it_died_on(client, app_module, monkeypatch):
    """E1+E2 — 停止 mid-walk, 继续 from the cursor: no re-paid page, no lost row, no repeat.

    The search cursor is the ``continuation`` **token** (a position; ``_collected_ids`` reads the ids to
    skip off the stored rows, never the cursor), so a resumed run re-opens the pager where it stopped and
    the row ledger drops any overlap. The proof is three-sided: the ids the first attempt paid a ``player``
    call for survive into 继续, nothing repeats, and the cursor holds **no list** — a smuggled id array is
    §6 U5's permanent silent-skip, paid for on xiaohongshu and asserted absent here.
    """
    harness.real_jar(monkeypatch, app_module)
    asked = 30
    canvas = posts_canvas(asked, KEYWORDS['E1'])
    with LiveRun(client, app_module, canvas, case_id='E1', mode='posts', target=asked, timeout=DEEP_TIMEOUT) as run:
        run.wait_until(lambda: run.live_rows() >= 4, within=STOP_DEADLINE, what='the crawl stored four rows')
        run.stop()
        run.wait()
        kept = run.rows()
        first_ids = {str(row.get('视频ID') or '') for row in run.preview('node-1')}
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
        ids = [str(row.get('视频ID') or '') for row in rows]
        assert first_ids <= set(ids), (
            f'继续 dropped {len(first_ids - set(ids))} of the {len(first_ids)} videos the first attempt '
            'already paid a detail call for'
        )
        assert len(ids) == len(set(ids)), f'{len(ids)} rows but {len(set(ids))} distinct — 继续 re-filed a video'
        cursor = harness.cursor_of(again.record, 'node-1')
        # A resume's whole contract is that it re-opened a POSITION: the cursor must be present, must carry
        # the continuation token it died on, and must hold position+label scalars only — no id list smuggled
        # in (AGENTS: a cursor records position, not content; that fix was paid for on xiaohongshu as §6 U5).
        # ``cursor_of`` returns {} when the node stored no cursor, so a bare "no list" test passes vacuously
        # about a crawl that never recorded anything — hence the non-empty + token + key-set trio.
        assert cursor, f'the resumed node stored no cursor, so it cannot have continued from a position: {cursor}'
        assert set(cursor) <= {'keyword', 'token', 'done'}, (
            f'the cursor grew keys beyond position+label: {sorted(cursor)}'
        )
        assert str(cursor.get('token') or ''), (
            f'the search cursor must hold the continuation token it died on: {cursor}'
        )
        smuggled = {key: value for key, value in cursor.items() if isinstance(value, (list, tuple, dict))}
        assert not smuggled, f'the resume cursor stores content, not position (U5 shape): {smuggled}'
        answer = again.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, f'继续 left the table short without naming why: {answer}'
        again.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── H · 用户自己的画布（§11 第 8 步：旗舰是他点 Run 那张）─────────────

#: His YouTube canvas, saved by hand: keyword search (50), 某频道作品 (NASA, 50), 视频评论 (50) — three
#: source nodes each wired to an 输出 node (archived parallel + headless). §9 reads all three as
#: ``enabled: true``, so the all-enabled copy is the same run; ``all_enabled`` is applied anyway so a
#: future edit that switched one off is caught rather than silently shortening the flagship leg.
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：YouTube.json'

#: The comments leg is the unbounded one (a watch-page load plus cursor rounds), so the budget is the two
#: walk cells plus the comment one.
ACCEPTANCE_TIMEOUT = 2 * DEEP_TIMEOUT + COMMENT_TIMEOUT


def _output_stems(workflow: dict) -> dict:
    """``{source_node_id: export filename stem}`` for the output node each source feeds.

    ``assert_canvas_exports`` matches a fresh file by the workflow *label* prefix, which is the wrong key
    for this canvas: his 输出 nodes name their own files (``YouTube 关键词搜索爬取.csv``), and the label
    carries a fullwidth '：' that ``sanitize_filename`` would strip anyway (§9's weibo/微信 finding,
    re-recorded here). So the acceptance leg ties file→store→preview through the filename the node
    actually wrote, which is the only identity that survives the exporter's own sanitising.
    """
    nodes = {str(node.get('id')): node for node in workflow.get('nodes') or []}
    stems: dict = {}
    for conn in workflow.get('connections') or []:
        target = nodes.get(str(conn.get('to')))
        if target is not None and target.get('type') == 'output':
            declared = (target.get('params') or {}).get('filename') or ''
            stem = os.path.splitext(sanitize_filename(declared))[0].strip()
            if stem:
                stems[str(conn.get('from'))] = stem
    return stems


def test_h1_the_shipped_canvas_runs_and_every_leg_accounts_for_itself(client, app_module, monkeypatch):
    """H1 — 测试：YouTube.json at his parameters, three legs, each accounting for itself.

    The canvas is his, the parameters are his; the question is whether a run he starts from the panel
    leaves a table, a record and an export that agree — per component. ``audit_components`` writes one
    ledger row per leg and derives the case's index row from those three, so a case cannot certify itself
    FULL by hand. The only thing the copy changes is which nodes are switched on (plan decision D5); no
    ask, keyword, channel or link is touched. No LLM node lives on this canvas, so no transport block is
    owed — the chains end in an 输出 node.
    """
    harness.real_jar(monkeypatch, app_module)
    opened = accept.workflow_file(ACCEPTANCE_FILE)
    workflow = accept.all_enabled(opened)
    _on, off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    assert len(found) == 3, f'this case is written against the three source nodes he saved: {found}'
    assert not off, f'the all-enabled copy still holds a switched-off node: {off}'
    stems = _output_stems(workflow)
    exported_before = accept.export_dir_entries()
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H1',
        mode='mixed',
        target=sum(part['ask'] for part in found),
        timeout=ACCEPTANCE_TIMEOUT,
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
        fresh = accept.new_exports(exported_before)
        for part in found:
            rows = run.preview(part['source'], workflow_name=part['label'])
            if part['mode'] == 'comments':
                if rows:
                    _assert_comment_rows(rows, minimum=1, url=part['urls'][0])
            elif rows:
                _assert_video_rows(rows, minimum=1, source=f'H1 {part["label"]}')
            # Per-component L2 three-consistency (file == store == preview) tied by the node's own
            # filename. A leg that honestly filed nothing writes nothing: the output node returns before
            # saving when it has no input, so an empty-but-NAMED leg must have NO file, and only a leg that
            # stored rows owes the file that ties store to preview.
            stem = stems.get(part['source'])
            mine = [path for path in fresh if stem and path.name.startswith(f'{stem}-')]
            stored = harness.stored_rows(records[part['label']], part['source'])
            if stored == 0:
                answer = next(a for label, a in answers if label == part['label'])
                assert answer['verdict'] == harness.NAMED_SHORT, (
                    f'leg {part["label"]!r} filed nothing; only a reason the site said makes that legal: {answer}'
                )
                assert not mine, f'a leg that filed 0 rows still wrote an export {mine} for {part["label"]}'
                continue
            assert mine, (
                f'no export file names the component {part["label"]!r} (stem {stem!r}): {[p.name for p in fresh]}'
            )
            with mine[0].open(encoding='utf-8-sig', newline='') as handle:
                exported_rows = sum(1 for _ in csv.reader(handle)) - 1
            assert exported_rows == stored == len(rows), (
                f'{mine[0].name} file {exported_rows} / store {stored} / preview {len(rows)} rows for {part["label"]}'
            )
        summary = accept.summary_row(run, case_id='H1', found=found, answers=answers, kept=kept, asked=asked)
        run.finish(rows=kept, target=asked, warn=summary != harness.FULL)
