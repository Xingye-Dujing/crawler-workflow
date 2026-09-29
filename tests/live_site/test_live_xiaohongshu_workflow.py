"""Xiaohongshu's run-level matrix + 旗舰画布 (H), built on the shared live machinery.

Like every platform's program file this one drives REAL crawls through the app (his saved
cookie, his ``测试：小红书.json``), grades each run against *its own* console slice with
``classify_verdict``, and ties file==store==preview per component. What is xhs-specific and
lives here:

* **vocabulary** — which lines are an honest site answer for a recycling grid. The load-bearing
  discipline is that a shortfall is excused ONLY by a sentence the site truthfully said:
  ``crawl.xhs.exhausted`` is a real bottom *because* the walk now follows ``笔记ID`` (U59), and a
  broad keyword at 50 that stops short without that or a named wall is the silent under-collect
  this tier exists to catch, so it is NOT whitelisted away.
* **shape checks** — 笔记ID is the dedupe/resume identity, so a post row without one, or the same
  笔记ID twice across a grid that re-promotes with fresh tokens, is a red.
* **the two components he saved** — node-1 关键词 ``IU`` (posts, ``recrawl:true``) and node-4 a
  pasted note URL (comments). The comment leg also exercises the expired-``xsec_token`` path
  (U60): a stale token answers 安全验证, which is now a *named* dead note, never a blank row.

Nothing here decides a pass by hand: :func:`live_acceptance.audit_components` writes one ledger
row per component and the case index is derived from those verdicts.

Run (supervised; this spends the logged-in XHS session, which walls within minutes):
    pytest -m "live_site and live_cn" tests/live_site/test_live_xiaohongshu_workflow.py
"""

import os
from pathlib import Path

import live_acceptance as accept
import live_run_driver as driver
import live_run_harness as harness
import pytest

from utils.helpers import sanitize_filename

pytestmark = [pytest.mark.live_site, pytest.mark.live_cn, pytest.mark.enable_socket, pytest.mark.serial]

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM = 'xiaohongshu'
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：小红书.json'

#: A keyword search that reads every note's detail (each detail is a second-tab navigation) is the
#: slowest thing here; the comment walk is bounded by its own panel scroll. Budgets are the wall-clock
#: ceiling a ``wait`` will tolerate, not a guess at how long the site takes — a 风控 ends the run early.
QUICK_TIMEOUT = 600.0
DEEP_TIMEOUT = 1800.0
COMMENT_TIMEOUT = 1200.0
#: posts (50, deep) + comments (1 URL) run serially, each its own workflow, so the ceiling is their sum.
ACCEPTANCE_TIMEOUT = DEEP_TIMEOUT + COMMENT_TIMEOUT

#: Columns the xhs posts crawler promises (``_scrape_card`` then the detail merge in ``_scrape_note``).
POST_COLUMNS = ('笔记链接', '笔记ID', '标题', '正文', '作者', '发布时间', '点赞数', '收藏数', '评论数')
#: Columns ``parse_xhs_comments`` writes per comment.
COMMENT_COLUMNS = ('文章URL', '评论者', '评论内容', '评论时间', '点赞数', '楼层')


# ─── the driver, bound to xiaohongshu ───────────────────────────────────


class LiveRun(driver.RunDriver):
    """xhs's binding of the shared run driver: platform word, budget, vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = QUICK_TIMEOUT
    # xiaohongshu walls a *replayed* session within minutes (docs/crawler_notes.md): a named session
    # death mid-crawl is this platform's ordinary answer, not a code fault, so it is carried as a WARN.
    # The designed cookie-death path itself is proved by the strict offline pins, not by convicting here.
    NAMED_DEATH_OK = True

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return _vocabulary(mode, headless)


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines honestly explain an xhs shortfall, per mode. Unknown modes are refused.

    ``crawl.xhs.exhausted`` is a legitimate POSTS exit ONLY when the leg actually consumed a
    note: the walk prints it after ``STUCK_ROUNDS`` cheap no-growth rounds, and the same line is
    emitted by a page that simply has not answered yet (docs/crawler_notes.md measures this grid
    answering late) — so a 0-row leg that says only 「无更多内容」 is a walk that gave up, not a
    bottom. The H1 grader enforces that by grading a 0-row posts leg against ``SHARED_EXITS``
    alone (see :func:`test_h1_...`'s ``grade``). A genuine bottom at N>0 is excused by the walk
    having consumed notes and then run out.

    The comments leg is graded ONLY on ``SHARED_EXITS``: a stale ``xsec_token`` there answers
    安全验证, which the comment engine turns into ``BLOCKED`` → ``run.cookieExpired`` (a shared
    exit). ``crawl.xhs.deadNote``/``crawl.xhs.page_timeout`` are never printed on that path
    (they live in ``search``/``_scrape_note``), so whitelisting them here would be a dead entry
    that licenses the wrong reason. A genuinely empty thread names nothing and stays red — that
    is a real product gap, not something a whitelist may paper over.
    """
    if mode == 'posts':
        return harness.SHARED_EXITS + ('crawl.xhs.exhausted',), ()
    if mode == 'comments':
        return harness.SHARED_EXITS, ()
    raise AssertionError(f'xhs vocabulary is unmeasured for mode {mode!r}; refuse to default it to posts')


# ─── shape checks (a right count with the wrong columns is a red) ───────


def _assert_post_rows(rows, *, minimum: int, source: str = 'search') -> None:
    """Every note carries a session-independent 笔记ID, unique across the run, with real counters.

    The grid re-promotes a note with a fresh ``xsec_token``; the ONLY stable identity is 笔记ID, so a
    row without one cannot be de-duplicated or resumed, and one 笔记ID filed twice is the dedupe failing.
    """
    assert len(rows) >= minimum, f'expected {minimum} rows, got {len(rows)}'
    ids = [str(row.get('笔记ID') or '') for row in rows]
    assert all(ids), f'a row with no 笔记ID cannot be de-duplicated or resumed: {ids[:6]}'
    assert len(set(ids)) == len(ids), f'{len(ids)} rows, {len(set(ids))} distinct 笔记ID — one note filed twice'
    for row in rows:
        missing = [column for column in POST_COLUMNS if column not in row]
        assert not missing, f'a column the crawler promised is absent ({source}): {missing}'
        assert str(row.get('标题') or '').strip() or str(row.get('正文') or '').strip(), f'a row with no text: {row}'
        for counter in ('点赞数', '收藏数', '评论数'):
            assert isinstance(row.get(counter), int), f'{counter} is not a number: {row.get(counter)!r}'


def _assert_comment_rows(rows, *, minimum: int) -> None:
    """Comment rows carry the columns the adapter writes, non-empty content, integer 点赞数.

    Deliberately NOT a 楼层 monotonicity/uniqueness check here: the xhs comment walk re-enumerates
    楼层 from 1 every scroll round (comments.py:274 calls ``parse_xhs_comments`` per round), so
    repeated 楼层 is the current product shape, not an over-collect — cross-round comment ROWS are
    de-duped by (评论者, 评论内容). That renumbering is logged as a candidate product gap (#6), not
    asserted green or red by this flagship cell.
    """
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    for row in rows:
        missing = [column for column in COMMENT_COLUMNS if column not in row]
        assert not missing, f'a comment column the adapter promises is absent: {missing}'
        assert str(row.get('评论内容') or '').strip(), f'an empty comment row: {row}'
        assert isinstance(row.get('点赞数'), int), f'点赞数 is not a number: {row.get("点赞数")!r}'


def _output_stems(workflow: dict) -> dict:
    """``{source_node_id: export filename stem}`` for the output node each source feeds.

    ``assert_canvas_exports`` matches a fresh file by the workflow *label*, which is the wrong key here:
    his 输出 nodes name their own files and the fullwidth '：' is sanitised to ``_`` on the way to disk,
    so ``{label}-`` never matches. Tie file→store→preview through the filename the node actually wrote.
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


# ─── H · 用户自己的画布（§11 第 8 步：旗舰是他点 Run 那张）─────────────


def test_h1_the_shipped_canvas_runs_and_every_leg_accounts_for_itself(client, app_module, monkeypatch):
    """H1 — 测试：小红书.json at his parameters, two legs (posts + comments), each accounting for itself.

    The canvas is his, the parameters are his. The question is whether a run he starts leaves a table,
    a record and an export that agree per component. A leg that honestly filed nothing (a named 风控 on
    a session that walls in minutes) must carry a named verdict and write no export; a leg that stored
    rows owes the file that ties store to preview.
    """
    harness.real_jar(monkeypatch, app_module)
    opened = accept.workflow_file(ACCEPTANCE_FILE)
    workflow = accept.all_enabled(opened)
    _on, off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    assert len(found) == 2, f'this case is written against the two source nodes he saved (posts, comments): {found}'
    assert not off, f'the all-enabled copy still holds a switched-off node: {off}'
    assert all(part['label'] for part in found), f'a component has no 工作流命名 label to key on: {found}'
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

        def _grade(part, record, console):
            """Per-component verdict with the B1 guard: a 「无更多内容」 over an EMPTY posts table is
            a walk that gave up, not a bottom, so it may not excuse 0 rows."""
            kept_here = harness.stored_rows(record, part['source'])
            exits, liars = _vocabulary(part['mode'], run.headless)
            if part['mode'] == 'posts' and kept_here == 0:
                exits = harness.SHARED_EXITS
            return harness.classify_verdict(part['ask'], kept_here, console, exits=exits, bug_lines=liars)

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
            grade=_grade,
        )
        assert not silent, f'components under target with no honest reason named: {silent}'
        stems = _output_stems(workflow)
        fresh = accept.new_exports(exported_before)
        for part in found:
            # ``preview`` is capped at 500 (driver and endpoint both clamp), so tie file==store exactly
            # and check preview only against that ceiling — a 501+ comment leg must not red on the cap.
            rows = run.preview(part['source'], workflow_name=part['label'])
            if part['mode'] == 'comments':
                if rows:
                    _assert_comment_rows(rows, minimum=1)
            elif rows:
                _assert_post_rows(rows, minimum=1, source=f'H1 {part["label"]}')
            stem = stems.get(part['source'])
            mine = [
                path
                for path in fresh
                if stem and (path.name.startswith(f'{stem}.') or path.name.startswith(f'{stem}-'))
            ]
            stored = harness.stored_rows(records[part['label']], part['source'])
            if stored == 0:
                answer = next(a for label, a in answers if label == part['label'])
                assert answer['verdict'] == harness.NAMED_SHORT, (
                    f'leg {part["label"]!r} filed nothing; only a reason the site said makes that legal: {answer}'
                )
                assert not mine, f'a leg that filed 0 rows still wrote an export {mine} for {part["label"]}'
                continue
            names = [p.name for p in fresh]
            assert mine, f'no export names {part["label"]!r} (stem {stem!r}): {names}'
            exported_rows, _header = accept.csv_row_count(mine[0])
            assert exported_rows == stored, f'{mine[0].name} file {exported_rows} / store {stored} for {part["label"]}'
            assert len(rows) == min(stored, 500), (
                f'{part["label"]}: preview returned {len(rows)} but store holds {stored} '
                f'(preview is capped at 500): {mine[0].name}'
            )
        summary = accept.summary_row(run, case_id='H1', found=found, answers=answers, kept=kept, asked=asked)
        # Pass the derived verdict explicitly: finish() would otherwise re-grade on ``mode='mixed'``
        # against the WHOLE console — the cross-component whitewash the per-component slices exist to
        # prevent — and this case's authoritative row is the one ``summary_row`` derived from the two
        # component verdicts, not a whole-canvas arithmetic.
        run.finish(
            answer={'verdict': summary, 'reasons': [f'{len(found)} components, {kept} of {asked} rows']},
            rows=kept,
            target=asked,
            warn=summary != harness.FULL,
        )
