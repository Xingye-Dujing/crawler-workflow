"""The 微信 LIVE program: real runs through the app, judged by what the console says.

Same shared machinery as every other run-level matrix (driver / recorder / grader / acceptance),
but WeChat has the **fewest moving parts of any platform** — which is itself the thing to verify:

* **Body-only by measurement, not assumption.** The article page serves 标题 / 公众号 / 发布时间 /
  发布地区 / 是否原创 / 正文 / 正文图片数 / 链接 and **nothing else** — no 评论数/点赞数/转发数/阅读数,
  because those come from a per-article credential WeChat mints only for a recognised client session
  (``crawler_notes.md`` / ``crawler_rules.md``: a real browser gets ``show_comment=0`` and an HTML
  「请在微信客户端打开链接」 from the comment endpoint). So A1 asserts the eight columns are present **and
  the interaction columns are absent** — a 评论数 column here would be an invented zero, which is the
  worst kind of false data this project refuses.
* **No target semantics: the links ARE the budget.** ``posts`` has no ``target_count`` field; the row
  count can never exceed the number of URLs pasted, so "did it collect everything asked" is "did every
  live link become a row, and did each dead link name itself".
* **Cookie death is structurally unreachable here** (``needs_session=False``, no cookie row at all): the
  ``run.cookieExpired`` branch cannot fire, and this tier asserts that as a design fact rather than
  leaving a case that can never exercise it.
* **Every row is a real navigation** (``collects='page_per_row'``): one link, one page load.

Step 0 (``backend/test_wechat_step0.py`` → ``scratchpad/wechat_step0.json``, 2026-09-29) re-measured the
three acceptance links: all alive, every field selector fired exactly once, bodies (2903/2332/93 chars)
complete and under the 5000 clip. One drift recorded as §6 **U56** (``get_detail`` navigates with
``driver.get`` not ``Crawler.open``, losing the settled record) — not a 采不满, so it does not block this
tier, but a red that separates "page never arrived" from "arrived with an empty column" is what the settled
flag would have bought.

Run in batches, domestic network, no login spent (public pages)::

    .venv/Scripts/python.exe -m pytest -q -m "live_site and live_cn" \\
        tests/live_site/test_live_wechat_workflow.py -k "a1 or c1" -p no:cacheprovider

**No case skips.** A dead link is asserted as a named per-link failure.
"""

import csv
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

PLATFORM = 'wechat'
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The three acceptance links (D7) — the same set ``crawler_notes`` / the crawler docstring / the
#: existing low-level live file carry. Step 0 re-measured them alive; a future red that a link is dead is
#: the site aging, and ``crawl.wechat.failed`` naming it is the honest outcome the whitelist allows.
URLS = [
    'https://mp.weixin.qq.com/s/cAx1zGfT2MzqpwnhULmSQA',
    'https://mp.weixin.qq.com/s/q59mL_dHixC97p19RpcfVQ',
    'https://mp.weixin.qq.com/s/f_2nB7u7pQApgIoPsBKMQg',
]

#: The eight columns a WeChat row carries — the WHOLE contract. There is no 评论数/点赞数/转发数/阅读数
#: on purpose (§7): their selectors would be the fabricated-zero this project refuses.
BODY_COLUMNS = ('标题', '公众号', '发布时间', '发布地区', '是否原创', '正文', '正文图片数', '链接')
FORBIDDEN_COLUMNS = ('评论数', '点赞数', '转发数', '阅读数', '在看数')

#: WeChat's own honest terminal lines: ``crawl.wechat.failed`` names a per-link dead/timeout visit (a
#: site answer about *that* URL, not the session), ``crawl.wechat.no_urls`` an empty paste. ``batch_done``
#: is the code summarising its own walk and is deliberately absent.
WECHAT_LEGIT_EXITS = harness.SHARED_EXITS + ('crawl.wechat.failed',)

QUICK_TIMEOUT = 600.0
STOP_DEADLINE = 300.0


class LiveRun(driver.RunDriver):
    """WeChat's binding of the shared run driver: no cookie jar, body-only vocabulary."""

    PLATFORM = PLATFORM
    DEFAULT_TIMEOUT = QUICK_TIMEOUT
    # A dead session is structurally impossible on a session-less platform; if one ever appears it is a
    # genuine product fault (the cookieExpired branch should never be reachable), so keep it a red.
    NAMED_DEATH_OK = False

    def vocabulary(self, mode: str, headless: bool) -> tuple[tuple, tuple]:
        return WECHAT_LEGIT_EXITS, ()


# ─── builders ───────────────────────────────────────────────────────────


def posts_canvas(urls, *, headless=False, **overrides):
    """A paste-a-links crawl: WeChat's only mode. ``target`` is the link count, not a field."""
    pasted = urls if isinstance(urls, str) else '\n'.join(urls)
    return harness.canvas_for(
        PLATFORM,
        'posts',
        settings=harness.run_settings('serial', headless),
        urls=pasted,
        **overrides,
    )


def _assert_body_rows(rows, *, expected_urls, source='paste') -> None:
    """The 8 columns present, the interaction columns absent, one row per live link, body non-empty."""
    by_link = {str(row.get('链接') or ''): row for row in rows}
    assert set(by_link) <= set(expected_urls), f'a stored 链接 is not one of the pasted URLs: {sorted(by_link)}'
    for row in rows:
        missing = [column for column in BODY_COLUMNS if column not in row]
        assert not missing, f'a body column the crawler promised is absent ({source}): {missing}'
        invented = [column for column in FORBIDDEN_COLUMNS if column in row]
        assert not invented, (
            f'a WeChat row grew an interaction column ({invented}) — the page serves none of these, '
            'so any value in them is a fabricated zero (§7)'
        )
        assert str(row.get('正文') or '').strip(), f'an article row with no body: {row.get("链接")}'
        assert str(row.get('标题') or '').strip(), f'an article row with no title: {row.get("链接")}'
        assert isinstance(row.get('正文图片数'), int) and row['正文图片数'] >= 0, (
            f'正文图片数 is not a count: {row.get("正文图片数")!r}'
        )


# ─── A · 正文采集 (paste / clip / dedupe) ───────────────────────────────


def test_a1_the_pasted_links_become_body_only_rows(client, app_module):
    """A1 — three live links → three rows, exactly the 8 columns, and no interaction column invented.

    The load-bearing half is the ABSENT columns: WeChat serves no comment/like/read figures to a browser,
    so a 评论数 here — even a 0 — is the fabricated data the whole platform note exists to refuse. Step 0
    measured every field selector firing once, so an empty cell now means the page changed, not that the
    test is generous.
    """
    with LiveRun(client, app_module, posts_canvas(URLS), case_id='A1', mode='posts', target=3) as run:
        run.wait()
        answer = run.verdict()
        assert answer['verdict'] == harness.FULL, f'three links alive at step 0 must become three rows: {answer}'
        rows = run.preview('node-1')
        assert len(rows) == 3, rows[:2]
        _assert_body_rows(rows, expected_urls=URLS)
        assert {str(row['链接']) for row in rows} == set(URLS), (
            f'not every pasted link became a row: {run.rec.lines[-8:]!r}'
        )
        run.finish(answer=answer)


def test_a2_a_long_body_is_clipped_with_a_marker_not_silently(client, app_module, monkeypatch):
    """A2 — the 正文 ceiling marks its cut; a silent short body is the indistinguishable-under-collect.

    The cap exists because one article can outgrow every other row a run stores, but a cut that leaves no
    trace reads to the analysis node as a complete-but-short article. The marker '…' is the difference.
    the limit is set to 200 here (not the shipped 5000) so the test does not depend on finding a 5000+
    character article — the claim is "a body longer than the limit is cut and says so", arithmetic and all.
    """
    from config import Config

    monkeypatch.setattr(Config, 'WECHAT_BODY_MAX_CHARS', 200, raising=False)
    with LiveRun(client, app_module, posts_canvas([URLS[0]]), case_id='A2', mode='posts', target=1) as run:
        run.wait()
        rows = run.preview('node-1')
        assert len(rows) == 1, rows
        body = str(rows[0].get('正文') or '')
        assert body.endswith('…'), f'a 2900-char article clipped at 200 must carry the cut marker: {body[-20:]!r}'
        assert len(body) == 201, f'the clip should be limit(200)+marker(1), got {len(body)}'
        run.finish(answer=run.verdict())


def test_a4_the_same_link_twice_is_refused_by_name_not_by_silence(client, app_module):
    """A4 — re-running one pasted link must not quietly produce a second identical row.

    ``recrawl`` is off by default, so the ledger owns the URL this fingerprint already paid for: the honest
    second answer is 0 new rows **and a sentence saying the ledger skipped it** (AGENTS reuse rules). Without
    a named line, a repeat that filed nothing reads identically to a dead link or a wall.
    """
    canvas = posts_canvas([URLS[0]])
    with LiveRun(client, app_module, canvas, case_id='A4', mode='posts', target=1) as run:
        run.wait()
        assert run.rows() == 1, f'the first pass must file the link before a repeat means anything: {run.rows()}'
        run.finish(answer=run.verdict())

    with LiveRun(client, app_module, canvas, case_id='A4.repeat', mode='posts', target=1) as again:
        again.wait()
        kept = again.rows()
        answer = again.verdict()
        assert kept == 0, f'the repeat re-filed {kept} row(s) the ledger already owns: {answer}'
        named = [key for key in ('run.dedupe_skipped', 'run.dedupe_all_skipped') if again.rec.counts_key(key)]
        assert named, f'a repeat filed nothing and named no ledger refusal: {again.rec.lines[-8:]!r}'
        again.finish(answer=answer, rows=0, warn=True)


# ─── C · 停止 then 继续 (the cursor is the URL index) ───────────────────


def test_c1_stop_then_continue_resumes_on_the_next_url(client, app_module):
    """C1+E — 停止 mid-batch, 继续 from the cursor: no re-paid page, no lost row, no duplicate link.

    The cursor is ``url_index`` (a position); a resumed run re-opens at the next link and the row ledger
    drops any overlap. The proof: the resumed table is the union of the three links, unique, and the cursor
    carries position only — no link list smuggled in (AGENTS: a cursor records position, not content; §6 U5
    is that rule's cost on another platform).
    """
    canvas = posts_canvas(URLS)
    with LiveRun(client, app_module, canvas, case_id='C1', mode='posts', target=3) as run:
        run.wait_until(lambda: run.live_rows() >= 1, within=STOP_DEADLINE, what='the crawl stored one article')
        run.stop()
        run.wait()
        kept = run.rows()
        first_links = {str(row.get('链接') or '') for row in run.preview('node-1')}
        assert run.status['outcome'] == 'interrupted', run.status
        assert run.node()['status'] == 'partial', run.node()
        assert 1 <= kept < 3, f'a walk cut short is short of its links; it kept {kept}'
        assert run.status['failed_nodes'] == 0, f"停止 is the user's button, not a failure: {run.status}"
        answer = run.verdict(rows=kept)
        assert answer['verdict'] == harness.NAMED_SHORT and 'run.nodeStopped' in answer['reasons'], answer
        run.finish(answer=answer)

    with LiveRun(
        client, app_module, canvas, case_id='C1.continue', mode='posts', target=3, resume_run_id=run.run_id, queue=False
    ) as again:
        again.wait()
        assert again.run_id == run.run_id, 'a resume that minted a new id is a second crawl, not 继续'
        rows = again.preview('node-1')
        links = [str(row.get('链接') or '') for row in rows]
        assert first_links <= set(links), f'继续 dropped {first_links - set(links)}: the first attempt paid those pages'
        assert len(links) == len(set(links)), f'{len(links)} rows, {len(set(links))} distinct links — a link re-paid'
        cursor = harness.cursor_of(again.record, 'node-1')
        smuggled = {key: value for key, value in cursor.items() if isinstance(value, (list, tuple, dict))}
        assert not smuggled, f'the resume cursor stores content, not position (U5 shape): {smuggled}'
        _assert_body_rows(rows, expected_urls=URLS, source='resumed')
        answer = again.verdict()
        assert answer['verdict'] != harness.SILENT_SHORT, f'继续 left the table short without naming why: {answer}'
        again.finish(answer=answer, warn=answer['verdict'] == harness.NAMED_SHORT)


# ─── H · 用户画布（§11 第 8 步）—— 测试：微信.json 的 urls 是空的，按 D7 补副本 ──

#: His WeChat canvas: one 正文 source, a name node and an output. §9 records that the source's ``urls``
#: is EMPTY as saved, so running it as-is is refused by validation (required field) — the acceptance copy
#: fills the URLs from the D7 set (the existing test program's own links) and changes nothing else.
ACCEPTANCE_FILE = REPO_ROOT / 'data' / 'workflows' / '测试：微信.json'
ACCEPTANCE_TIMEOUT = 2 * QUICK_TIMEOUT


def _fill_urls(workflow: dict) -> dict:
    """The one edit the copy makes: paste the acceptance links into the empty source ``urls`` field.

    The file on disk is what the user saved (§D5, read-only); this is the in-memory variant that lets the
    flagship leg crawl instead of tripping the required-field refusal the empty textarea earns.
    """
    filled = 0
    for node in workflow.get('nodes') or []:
        if node.get('type') == 'source' and node.get('platform') == PLATFORM:
            node.setdefault('params', {})['urls'] = '\n'.join(URLS)
            filled += 1
    assert filled == 1, f'the acceptance canvas was expected to hold exactly one wechat source, found {filled}'
    return workflow


def test_h1_the_canvas_crawls_every_article_it_lists(client, app_module):
    """H1 — 测试：微信.json with its links filled (D7): every URL a row, body-only, export ties the table.

    The flagship leg is the canvas he saved; the one thing this copy changes is pasting in the URLs the file
    left blank (a source with an empty required textarea is refused by validation, which is correct product
    behaviour but not an acceptance run). Per-component grading is the shared acceptance kit's job.
    """
    workflow = accept.workflow_file(ACCEPTANCE_FILE)
    workflow = _fill_urls(accept.all_enabled(workflow))
    _on, off, found = accept.parts(workflow, file_name=ACCEPTANCE_FILE.name)
    assert not off, f'the all-enabled copy still holds a switched-off node: {off}'
    # WeChat dropped target semantics (§7): the links ARE the budget. The saved canvas still carries a
    # vestigial ``target_count=50`` from an older default the crawler no longer reads, so parts() derives a
    # 50 ask the walk can never meet — cap each ask at the link count, the honest ceiling for this mode.
    for part in found:
        part['ask'] = min(part['ask'], len(URLS))
    exported_before = accept.export_dir_entries()
    with LiveRun(
        client,
        app_module,
        workflow,
        case_id='H1',
        mode='mixed',
        target=len(URLS),
        timeout=ACCEPTANCE_TIMEOUT,
    ) as run:
        run.wait()
        run.assert_l3()
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
        # Single component: the shared per-label filename match (built to disambiguate a multi-component
        # run) cannot work here — this canvas's label carries a fullwidth '：' that the exporter sanitises
        # in the filename — so tie the L2 three-consistency leg directly: one export file, its data rows
        # equal to the stored table.
        fresh = accept.new_exports(exported_before)
        assert len(fresh) == 1, f'the single source should write exactly one export, got {fresh}'
        stored_rows = run.preview(found[0]['source'], workflow_name=found[0]['label'])
        with fresh[0].open(encoding='utf-8-sig', newline='') as handle:
            exported_rows = sum(1 for _ in csv.reader(handle)) - 1
        assert exported_rows == len(stored_rows), f'export {exported_rows} rows vs stored {len(stored_rows)}'
        for part in found:
            rows = run.preview(part['source'], workflow_name=part['label'])
            if rows:
                _assert_body_rows(rows, expected_urls=URLS, source=f'H1 {part["label"]}')
        summary = accept.summary_row(run, case_id='H1', found=found, answers=answers, kept=kept, asked=asked)
        run.finish(rows=kept, target=asked, warn=summary != harness.FULL)
