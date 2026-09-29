"""X's 旗舰画布 acceptance (H group) — his ``测试：X.json`` end to end, graded per component.

Third platform to reuse the shared live machinery (``live_run_driver`` / ``live_run_harness`` /
``live_acceptance``): one real run started through the app, graded against **its own** console
slice, with ``file == store == preview`` tied by each 输出 node's own filename stem. X-specific
knowledge lives here: which console lines honestly explain a shortfall (``crawl.x.no_cards`` — a
timeline that rendered nothing), and what a correct X row looks like (``推文ID`` is the status id,
unique across a recycled window).

His canvas has three components: 关键词 posts (``OpenAI``×50), 某作者 (``NASA``×50), and one
post's replies (the pinned ``x.com/jack/status/20``, limit 50 — a stable, reply-rich target, so
the comment leg cannot be "honest" only because it is quiet). A broad keyword and an active
account should reach target = FULL; a shortfall is accepted ONLY when the crawler *names* 风控 /
登录墙 / no_cards — a silent one is the under-collect this tier exists to catch.

Run (supervised; X is unreachable from a CN network, so this needs the overseas route):
    pytest -m "live_site and live_os" tests/live_site/test_live_x_workflow.py
"""

import os
from pathlib import Path

import live_acceptance as accept
import live_run_driver as driver
import live_run_harness as harness
import pytest

from utils.helpers import sanitize_filename

pytestmark = [
    pytest.mark.live_site,
    pytest.mark.live_os,
    pytest.mark.enable_socket,
    pytest.mark.serial,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
PLATFORM = 'twitter'
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：X.json'

#: X reads cards with one script per scroll and no per-row navigation, so a 50-row walk is a few
#: scroll-and-read rounds. His canvas is saved ``parallel``, so the three legs crawl at once; the
#: shared machinery still slices each workflow's console by its own name-node label.
ACCEPTANCE_TIMEOUT = 3 * 1800.0


class LiveRun(driver.RunDriver):
    """X's binding of the shared run driver: platform word, budget, vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = 1800.0
    # X is refused by risk control (403) / a login wall when a session is over-questioned; the
    # designed cookie-death path is proved by the matrix, so a *named* death here is a WARN, not
    # a conviction.
    NAMED_DEATH_OK = True

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return _vocabulary(mode, headless)


def _vocabulary(mode: str, headless: bool) -> tuple[tuple, tuple]:
    """Which lines honestly explain an X shortfall, per mode. Unknown modes are refused.

    posts/author: ``crawl.x.no_cards`` (a timeline that rendered nothing) and ``crawl.x.wall`` (a
    refusal raised at open) are honest exits for a SHORT walk — but see the ``_grade`` guard: a
    0-row leg may not be excused by ``no_cards`` (a not-yet-painted page reads the same as an empty
    one, the pre-#148 mistake this platform made), only by a named wall. ``crawl.x.finished``'s
    stop-reason is NOT whitelisted because it prints even on a FULL run, so a silent under-target
    stays SILENT_SHORT — the exact whitewash this tier exists to refuse.
    comments: the comment engine prints ``crawl.x.*`` for none of this; a 0-row reply leg is only
    excused by a shared wall/stop, so it is graded on ``SHARED_EXITS`` alone.
    """
    if mode in ('posts', 'author'):
        return harness.SHARED_EXITS + ('crawl.x.no_cards', 'crawl.x.wall'), ()
    if mode == 'comments':
        return harness.SHARED_EXITS, ()
    if mode == 'mixed':
        return harness.SHARED_EXITS + ('crawl.x.wall',), ()
    raise AssertionError(f'X vocabulary is unmeasured for mode {mode!r}; refuse to default it')


def _assert_x_rows(rows, *, minimum: int, source: str) -> None:
    """Each post carries a numeric 推文ID that is in its own 链接, and the ids are unique."""
    assert len(rows) >= minimum, f'expected {minimum} rows for {source}, got {len(rows)}'
    ids = [str(row.get('推文ID') or '') for row in rows]
    assert all(i.isdigit() for i in ids), f'a 推文ID is not a status id: {ids[:6]}'
    assert len(set(ids)) == len(ids), (
        f'{len(ids)} rows, {len(set(ids))} distinct 推文ID — a recycled window double-filed'
    )


def _assert_x_comment_rows(rows, *, minimum: int) -> None:
    """Replies carry text and a unique 评论ID (the root post must not be a reply to itself)."""
    assert len(rows) >= minimum, f'expected {minimum} comment rows, got {len(rows)}'
    ids = [str(row.get('评论ID') or '') for row in rows]
    assert all(ids) and len(set(ids)) == len(ids), f'评论ID must be present and unique: {ids[:6]}'
    for row in rows:
        assert (row.get('评论内容') or '').strip(), f'a reply with no text: {row}'


def _output_stems(workflow: dict) -> dict:
    """``{source_node_id: export filename stem}`` — his 输出 nodes name their own files, so tie
    file→store→preview through what the node actually wrote (the label prefix is sanitised away)."""
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
    """H1 — 测试：X.json at his parameters, three legs (posts / author / comments), each accounting for itself."""
    harness.real_jar(monkeypatch, app_module)
    opened = accept.workflow_file(ACCEPTANCE_FILE)
    workflow = accept.all_enabled(opened)
    _on, off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    assert len(found) == 3, (
        f'this case is written against the three source nodes he saved (posts, author, comments): {found}'
    )
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
            """Per-leg verdict with the B1 guard: a ``crawl.x.no_cards`` over an EMPTY posts/author
            table is a page that had not painted (or a soft block), not a bottom, so it may not
            excuse 0 rows — only a named wall can. A genuine ``no_cards`` bottom at N>0 is allowed."""
            kept_here = harness.stored_rows(record, part['source'])
            exits, liars = _vocabulary(part['mode'], run.headless)
            if kept_here == 0 and part['mode'] in ('posts', 'author'):
                exits = harness.SHARED_EXITS + ('crawl.x.wall',)
            return harness.classify_verdict(part['ask'], kept_here, console, exits=exits, bug_lines=liars)

        run.wait()
        run.assert_l3()
        assert not harness.names_key(run.rec.text, 'run.skippedWorkflows'), (
            f'the all-enabled copy still sat a leg out: {run.rec.lines[:6]!r}'
        )
        records = accept.records_by_node(client, found)
        silent, kept, asked, answers = accept.audit_components(
            run, records=records, case_id='H1', found=found, grade=_grade
        )
        assert not silent, f'components under target with no honest reason named: {silent}'
        stems = _output_stems(workflow)
        fresh = accept.new_exports(exported_before)
        for part in found:
            rows = run.preview(part['source'], workflow_name=part['label'])
            if part['mode'] == 'comments':
                if rows:
                    _assert_x_comment_rows(rows, minimum=1)
            elif rows:
                _assert_x_rows(rows, minimum=1, source=part['label'])
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
                assert not mine, f'a 0-row leg still wrote an export {mine} for {part["label"]}'
                continue
            names = [p.name for p in fresh]
            assert mine, f'no export names {part["label"]!r} (stem {stem!r}): {names}'
            exported_rows, _header = accept.csv_row_count(mine[0])
            assert exported_rows == stored, f'{mine[0].name} file {exported_rows} / store {stored} for {part["label"]}'
            assert len(rows) == min(stored, 500), (
                f'{part["label"]}: preview returned {len(rows)} but store holds {stored} (preview capped at 500)'
            )
        summary = accept.summary_row(run, case_id='H1', found=found, answers=answers, kept=kept, asked=asked)
        # Pass the derived verdict; finish() would otherwise re-grade the WHOLE console (the
        # cross-component whitewash the per-component slices exist to prevent).
        run.finish(
            answer={'verdict': summary, 'reasons': [f'{len(found)} components, {kept} of {asked} rows']},
            rows=kept,
            target=asked,
            warn=summary != harness.FULL,
        )
