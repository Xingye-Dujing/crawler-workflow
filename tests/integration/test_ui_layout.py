"""Real-browser layout and interaction proofs — the part Python asserts cannot see.

Two reasons this tier exists. First, CSS overflow only *looks* fine until a real
engine lays the labels out in both languages and measures pixels. Second, the node
canvas is built from string templates in a jsdom-free harness, so "the edit button
still edits its own node after the inline-handler splice was removed" was a claim
about code that had never been clicked. Both are settled here.

What the check is, precisely (the user's rule: no horizontal scrollbar on the
window or the page; a table inside a panel MAY scroll, but nothing may be silently
clipped):

* the page and every docked/floating panel must have ``scrollWidth <= clientWidth``;
* an element that is allowed to scroll is only allowed to if it declares
  ``overflow-x: auto|scroll|hidden`` *and* its own box stays inside its parent — an
  element that overflows while declaring ``visible`` is the horizontal bar;
* text that is truncated must say so (an ellipsis is a decision, a clipped glyph is
  data the user cannot read).

This module deliberately performs NO server-side writes: the app has no
data-directory override, so uploading, saving a workflow or executing a run here
would leave rows in the user's real ``data/`` and ``logs/``. Everything below is
either layout, or client-side state that dies with the page (the run console is
driven by stubbing ``fetch``, so no run is started).

Marked ``integration`` so it runs with ``-m integration`` on a machine with Chrome.
"""

import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

REPO = Path(__file__).resolve().parents[2]
VIEWPORTS = [(1920, 1080), (1366, 768), (1024, 700)]


@pytest.fixture(scope='module')
def app_url(tmp_path_factory):
    """Boot the real server on a private port, in a state root of its own.

    ``CRAWLER_DATA_ROOT`` (see ``backend/config.py``) is what makes that possible: without it, this
    instance shares the user's ``data/`` — and a second process reading that directory still writes
    ``app.log`` and the databases' ``-wal``/``-shm`` sidecars, while a startup ``promote_stale_runs``
    would settle whatever run their own instance is in the middle of. Measured, that is exactly what
    happened: the suite's own end-of-run snapshot caught these files moving.

    Nothing here needs the user's state anyway — every panel is driven by a stubbed ``fetch`` — so
    an empty root costs the assertions nothing, and this tier no longer depends on the user having
    stopped their own server.
    """
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    root = tmp_path_factory.mktemp('ui_server_state')
    env = {**os.environ, 'PORT': str(port), 'CRAWLER_DATA_ROOT': str(root)}
    (root / 'logs').mkdir(exist_ok=True)
    log_path = root / 'logs' / '_ui_layout_server.log'
    with log_path.open('w', encoding='utf-8') as log:
        proc = subprocess.Popen(
            [sys.executable, 'app.py'],
            cwd=str(REPO / 'backend'),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
        url = f'http://127.0.0.1:{port}'
        deadline = time.time() + 40
        try:
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(url + '/', timeout=2) as resp:
                        if resp.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError, TimeoutError):
                    if proc.poll() is not None:
                        msg = log_path.read_text(errors='replace')[-2000:]
                        pytest.fail(f'server exited early; log:\n{msg}')
                    time.sleep(0.5)
            else:
                pytest.fail('server did not come up within 40s')
            yield url
        finally:
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=10)
            with contextlib.suppress(Exception):
                proc.kill()


@pytest.fixture(scope='module')
def driver():
    """A headless Chrome borrowed from the crawler stack (its driver factory
    already honours the configured chromedriver/binary/window settings)."""
    from crawlers.wechat import WechatCrawler

    try:
        crawler = WechatCrawler(headless=True)
    except Exception as e:
        pytest.skip(f'Chrome/chromedriver unavailable: {e}')
    try:
        yield crawler.driver
    finally:
        crawler.close()


# ─── the overflow rule, stated once as JavaScript ───────────────────────


def _audit_js(scope_id):
    """Measure `scope_id` and everything under it.

    An element overflowing while its own overflow-x is ``visible`` IS the
    horizontal bar the user forbade; one that overflows inside
    ``auto``/``scroll``/``hidden`` is a deliberate scroller and only has to
    contain itself — so it is reported separately from the failure list, with the
    cell that needs it checked for the ellipsis that makes the clipping visible.

    Kept as a plain string with one marked hole rather than an f-string: the body is
    full of JavaScript object literals, and every one of their braces would need
    doubling to survive Python's formatter — which makes the JS unreadable to the
    next person, and this file's job is to be checked by eye against the pixels.
    """
    return _AUDIT_JS.replace('__SCOPE__', repr(scope_id))


_AUDIT_JS = """
    const scope = document.getElementById(__SCOPE__) || document.body;
    const SCROLLABLE = {'auto': 1, 'scroll': 1, 'hidden': 1};
    const clipped = [], scrollers = [];
    // Counted so an empty scope cannot pass as a clean one: a panel whose id was
    // renamed, or whose body only fills in after a lazy load, holds nothing to
    // measure and every assertion below would then be true of zero elements.
    let measured = 0;
    scope.querySelectorAll('*').forEach((el) => {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        if (!el.clientWidth && !el.clientHeight) return;
        measured += 1;
        // A text control scrolls its own content by design: an input whose value is
        // longer than the box is not a clipped label, it is the widget working.
        // ``option``/``optgroup`` join that exclusion for the same reason: their
        // metrics are the native popup's, taken while it is closed, and a long
        // option can neither clip the page nor grow a bar on it.
        if (/^(INPUT|TEXTAREA|SELECT|OPTION|OPTGROUP)$/.test(el.tagName)) return;
        const over = el.scrollWidth - el.clientWidth;
        if (over <= 1) return;
        const record = {
            what: (el.tagName + '.' + (el.className || '')).slice(0, 70),
            over: over,
            ellipsis: cs.textOverflow === 'ellipsis',
            clippedCells: 0
        };
        if (SCROLLABLE[cs.overflowX]) {
            // A declared scroller may overflow, but a table cell inside it must
            // still show an ellipsis: a scrolled-off column with no cue is data
            // the user cannot find.
            el.querySelectorAll('th, td').forEach((cell) => {
                const ccs = getComputedStyle(cell);
                if (cell.scrollWidth - cell.clientWidth > 1 && ccs.textOverflow !== 'ellipsis') {
                    record.clippedCells += 1;
                }
            });
            scrollers.push(record);
        } else {
            clipped.push(record);
        }
    });
    // Transform-animated slides are where a panel sits BEFORE it is opened, so a
    // rect measured during the transition reports the panel as off-screen. The
    // measurement is about final layout, so the animation is not needed for it.
    scope.style.transition = 'none';
    const rect = scope.getBoundingClientRect();
    return {
        // The body fallback below is a convenience for the caller, not a verdict:
        // measuring the whole page and reporting it as "#settings-panel is fine"
        // is how a renamed id passed for a whole release. Say so explicitly.
        scopeMissing: !document.getElementById(__SCOPE__),
        scopeScroll: [scope.scrollWidth, scope.clientWidth],
        measured: measured,
        outsideViewport: Math.round(Math.max(0, rect.right - window.innerWidth, -rect.left)),
        clipped: clipped.slice(0, 8),
        scrollers: scrollers.filter((r) => r.clippedCells).slice(0, 8),
        page: [document.documentElement.scrollWidth, document.documentElement.clientWidth,
               window.innerWidth],
        body: [document.body.scrollWidth, document.body.clientWidth]
    };
    """


def _kill_animations(driver):
    """Slide-in panels are laid out at their open position only after a transition;
    a rect measured mid-slide reports them as off-screen."""
    driver.execute_script(
        """
        const style = document.createElement('style');
        style.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
        document.head.appendChild(style);
        """,
        [],
    )


def _assert_contains_itself(result, label, may_be_wider_than_viewport=False, min_measured=1):
    assert not result['scopeMissing'], f'{label}: that id is not in the page — the audit fell back to <body>'
    assert result['measured'] >= min_measured, (
        f'{label}: only {result["measured"]} visible element(s) were measured (floor {min_measured}) — '
        'an empty scope makes every assertion below true of nothing, which is not a pass'
    )
    clipped = result['clipped']
    assert not clipped, f'{label}: {len(clipped)} element(s) overflow without being scrollable: {clipped}'
    sw, cw = result['scopeScroll']
    if not may_be_wider_than_viewport:
        assert sw <= cw + 1, f'{label}: the container itself scrolls sideways ({sw} > {cw}) — {result["clipped"]}'
    if not may_be_wider_than_viewport:
        assert result['outsideViewport'] <= 1, f'{label}: grows past the viewport by {result["outsideViewport"]}px'
    assert result['page'][0] <= result['page'][1] + 1, (
        f'{label}: the PAGE grew a horizontal bar ({result["page"][0]} > {result["page"][1]})'
    )
    assert result['body'][0] <= result['body'][1] + 1, f'{label}: <body> scrolls sideways: {result["body"]}'
    silently_clipped = result['scrollers']
    assert not silently_clipped, f'{label}: cells cut off inside a scroller with no ellipsis: {silently_clipped}'


# Every container the page shows and hides, taken off ``index.html`` rather than
# remembered: these are top-level elements addressed by id, with no shared class
# (``class="panel"`` has never existed here, and a selector that matches nothing
# turns a layout audit into a pass over zero elements).
PANELS = [
    'node-palette',
    'stats-panel',
    'chart-preview-panel',
    'data-preview-panel',
    'dashboard-panel',
    'history-panel',
    'studio-overlay',
    'node-settings',
    'console-panel',
    'runs-panel',
    'exports-panel',
    'dataset-panel',
    'workflows-panel',
    'cookies-panel',
    'processes-panel',
    'status-bar',
    'context-menu',
    'dialog-overlay',
    'cookie-dialog',
    'style-menu',
    'ai-menu',
    'settings-menu',
    'profile-status',
]

# How many elements each panel actually puts on screen at 1366×768 with nothing
# selected and no data loaded — measured in a real Chrome, per panel. The floor is
# what stops this file from passing on an empty scope: a renamed id, a panel whose
# markup was deleted, or a table that only fills in on a lazy load would otherwise
# satisfy every overflow rule simply by having nothing to break them.
#
# A panel growing past its number is fine (these are minimums); one falling under
# it has lost content, which is exactly what must be noticed.
# How many elements each container actually puts on screen at 1366×768 with nothing
# selected and no data loaded — counted in a real Chrome, per container, then
# rounded down. The floor is what stops this file from passing on an empty scope: a
# renamed id, a container whose markup was deleted, or a table that only fills in on
# a lazy load would otherwise satisfy every overflow rule by having nothing to break.
#
# Growing past the number is fine (these are minimums); falling under it means the
# container lost content.
MIN_MEASURED = {
    'node-palette': 16,
    'stats-panel': 6,
    'chart-preview-panel': 3,
    'data-preview-panel': 6,
    'dashboard-panel': 4,
    'history-panel': 13,
    'studio-overlay': 16,
    'node-settings': 3,
    'console-panel': 6,
    'runs-panel': 5,
    'exports-panel': 6,
    'dataset-panel': 5,
    # 7 counted in a real Chrome in both languages with the list still empty; 6
    # leaves one element of slack for a state that shows fewer chrome parts.
    'workflows-panel': 6,
    # 7 counted in a real Chrome in both languages with the list still empty (header, its
    # two buttons, the resize handle, the body and the panel itself); 6 keeps one element of
    # slack, the same convention as the other docks.
    'cookies-panel': 6,
    'processes-panel': 4,
    'status-bar': 7,
    'context-menu': 13,
    'dialog-overlay': 2,
    'cookie-dialog': 20,
    'style-menu': 10,
    'ai-menu': 32,
    'settings-menu': 26,
    # 23 measured in a real Chrome in both languages (one row per capture-capable
    # platform, WeChat excluded); 20 leaves room for a row's chip to be absent.
    'profile-status': 20,
}

#: Containers whose content is fetched rather than written into the markup, so the
#: audit has to wait for the render instead of measuring a box that is still empty
#: (which would satisfy every overflow rule by having nothing in it).
_ASYNCHRONOUS = {'profile-status': 'document.querySelectorAll("#profile-status .profile-item").length'}


def _seed(driver, panel_id):
    """Open what the panel needs and wait until it has drawn its own rows."""
    if panel_id not in _ASYNCHRONOUS:
        return
    driver.execute_script(
        """
        const menu = document.getElementById('settings-menu');
        if (menu) { menu.classList.add('open'); menu.classList.remove('hidden'); }
        if (window.renderBrowserProfiles) renderBrowserProfiles();
        """,
        [],
    )
    deadline = time.monotonic() + 15
    probe = _ASYNCHRONOUS[panel_id]
    while time.monotonic() < deadline:
        if driver.execute_script(f'return {probe};', []) > 0:
            return
        time.sleep(0.2)
    pytest.fail(f'#{panel_id} never rendered a row — the panel is empty, so nothing about it was measured')


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_page_itself_never_grows_a_horizontal_bar(app_url, driver, lang):
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(f"document.body.dataset.lang = '{lang}'; I18n.apply();")
    result = driver.execute_script(_audit_js('workspace'), [])
    # The canvas layer is a deliberately huge pannable surface (the user drags it
    # around), so it is allowed to be wider than the window. What must not happen is
    # a node, a label or a panel overflowing its own box, or the window itself
    # growing a bar — which is what the rest of this check still asserts.
    #
    # No per-element floor here, deliberately: with every panel closed and no node
    # on the canvas this scope holds three measured elements (measured, not assumed
    # — see MIN_MEASURED for the panels). What this test owns is the page-level
    # verdict in ``result['page']``/``['body']`` below, which is whole-document
    # however empty the scope is; the per-panel floors are what prove content.
    _assert_contains_itself(result, f'closed page in {lang}', may_be_wider_than_viewport=True)


@pytest.mark.parametrize('lang', ['zh', 'en'])
@pytest.mark.parametrize('panel_id', PANELS)
def test_every_panel_fits_itself_in_both_languages(app_url, driver, panel_id, lang):
    """The English labels are the long ones, so a panel that fits in Chinese can
    still break in English — which is why the language is a parameter."""
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    opened = driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const el = document.getElementById({panel_id!r});
        if (!el) return 'missing';
        el.classList.add('open');
        el.classList.remove('hidden');
        return 'ok';
        """
    )
    # An id that no longer exists must not be allowed to fall through to the
    # body-wide audit below — that would measure a hundred elements and call the
    # panel checked.
    assert opened == 'ok', f'#{panel_id} is not in the page, so nothing about it was measured'
    _seed(driver, panel_id)
    result = driver.execute_script(_audit_js(panel_id), [])
    _assert_contains_itself(
        result, f'#{panel_id} in {lang}', may_be_wider_than_viewport=True, min_measured=MIN_MEASURED[panel_id]
    )


@pytest.mark.parametrize('lang', ['zh', 'en'])
@pytest.mark.parametrize('mode', ['parallel', 'serial'], ids=['parallel', 'serial'])
def test_a_multi_workflow_record_is_tagged_with_how_it_really_ran(app_url, driver, lang, mode):
    """The run-records row is where the user reads "did both workflows run, and did
    they run at the same time?".

    Nothing is written to the server: the row is drawn by the real
    ``runsManager.render`` from a payload shaped exactly like ``/api/runs/list``,
    so what is asserted here is the pixels the composed name and the chips produce
    — a name cell that clips, a chip that grows the row past the table, or a chip
    that claims a concurrency this run never had would all be invisible to the
    Python tier. Both languages, because the English label is the longer one.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const panel = document.getElementById('runs-panel');
        panel.classList.add('open');
        panel.classList.remove('hidden');
        runsManager.render([{{
            run_id: 'multi1', workflow_name: '热门榜 + 周排行榜', status: 'completed',
            resumable: false, node_done: 6, node_total: 6, rows_kept: 40,
            started_at: '2026-09-24 03:00', mode: {mode!r}, wf_count: 2, headless: 1
        }}]);
        """,
        [],
    )
    facts = driver.execute_script(
        """
        const cell = document.querySelector('#runs-panel .runs-mgr-wf');
        if (!cell) return {found: false};
        const chips = Array.from(cell.querySelectorAll('.runs-mgr-tag'));
        const table = document.querySelector('#runs-panel table');
        const window1366 = window.innerWidth;
        const label = (key) => I18n.t(key).replace('{n}', 2);
        return {
            found: true,
            text: cell.textContent,
            chips: chips.map((c) => c.textContent),
            // Both mode labels as this language really spells them. Hardcoding the
            // wording is how this test came to demand 'PARALLEL' of a serial run:
            // the catalog says 'parallel ×2' in lower case, so a copy of the string
            // drifts from the thing it claims to check.
            parallel: label('runsMgr.tagParallel'),
            serial: label('runsMgr.tagSerial'),
            // A chip whose own glyphs are cut off reads as a shorter fact than it is.
            clippedChips: chips.filter((c) => c.scrollWidth - c.clientWidth > 1).length,
            tableOverflows: table ? table.scrollWidth - table.clientWidth > 1 : null,
            cellRight: Math.round(cell.getBoundingClientRect().right),
            windowWidth: window1366,
            pageBar: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
        };
        """,
        [],
    )
    assert facts['found'] is True, '#runs-panel .runs-mgr-wf rendered nothing, so the row was not measured'
    assert '热门榜' in facts['text'] and '周排行榜' in facts['text'], facts['text']
    assert 'runsMgr.' not in facts['parallel'] + facts['serial'], f'the label fell back to its key: {facts}'
    assert facts['parallel'] != facts['serial'], f'the two mode labels are the same string in {lang}: {facts}'
    said = facts['parallel'] if mode == 'parallel' else facts['serial']
    silent = facts['serial'] if mode == 'parallel' else facts['parallel']
    assert len(facts['chips']) == 2, f'expected a mode chip and a window chip, got {facts["chips"]}'
    assert said in facts['chips'], f'a {mode} run must be tagged {said}, chips were {facts["chips"]}'
    assert silent not in facts['chips'], f'the row claims {silent}, which this run was not: {facts["chips"]}'
    assert any('2' in chip for chip in facts['chips']), f'the chip must say how many workflows: {facts["chips"]}'
    assert facts['clippedChips'] == 0, f'a chip is silently cut off: {facts["chips"]}'
    assert facts['cellRight'] <= facts['windowWidth'] + 1, f'the name cell runs off the window: {facts}'
    assert facts['pageBar'][0] <= facts['pageBar'][1] + 1, f'the page grew a horizontal bar: {facts["pageBar"]}'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_stopping_record_says_stopping_and_offers_nothing(app_url, driver, lang):
    """The row the user stares at after pressing 停止, measured in the browser.

    This record is the whole complaint: the Stop request writes 正在停止 into it and
    the worker's verdict arrives seconds later, so the panel has to (a) have a word
    for that state instead of falling back to 已完成, (b) wear its own chip colour,
    (c) offer no 继续/重新开始 and refuse nothing the user might click, because the
    run is still writing its rows — and (d) do all of that in both languages without
    the longer label pushing the table or the page into a horizontal bar.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        const panel = document.getElementById('runs-panel');
        panel.classList.add('open');
        panel.classList.remove('hidden');
        runsManager.render([{
            run_id: 'stopping1', workflow_name: '正在被停止的采集', status: 'stopping',
            resumable: false, node_done: 1, node_total: 3, rows_kept: 12,
            started_at: '2026-09-25 03:00', mode: 'serial', wf_count: 1, headless: 1
        }]);
        """,
        [lang],
    )
    facts = driver.execute_script(
        """
        const row = document.querySelector('#runs-panel tbody tr');
        if (!row) return {found: false};
        const chip = row.querySelector('.runs-mgr-status');
        const table = document.querySelector('#runs-panel table');
        return {
            found: true,
            label: chip ? chip.textContent : null,
            cls: chip ? chip.className : null,
            // A cut-off word is a different word: 「正在停止」 printed as 「正在停…」
            // is the one state the user needs to read correctly.
            clipped: chip ? chip.scrollWidth - chip.clientWidth > 1 : null,
            handlers: Array.from(row.querySelectorAll('.runs-mgr-btn')).map((b) => b.textContent),
            tableOverflows: table ? table.scrollWidth - table.clientWidth > 1 : null,
            pageBar: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
            fallback: I18n.t('runsMgr.status.completed'),
            key: I18n.t('runsMgr.status.stopping'),
        };
        """,
        [],
    )
    assert facts['found'] is True, 'the run row rendered nothing, so nothing was measured'
    assert facts['key'] != 'runsMgr.status.stopping', f'{lang} has no word for the stopping state'
    assert facts['label'] == facts['key'], f'the row reads {facts["label"]!r}, expected {facts["key"]!r}'
    assert facts['label'] != facts['fallback'], 'a run with no verdict yet is presented as completed'
    assert 'st-stopping' in (facts['cls'] or ''), f'the chip wears no style of its own: {facts["cls"]}'
    assert facts['clipped'] is False, f'the word is cut off in {lang}: {facts["label"]!r}'
    offered = (facts['key'], '继续', '重新开始', 'Continue', 'Restart')
    assert not any(h in facts['handlers'] for h in offered), facts['handlers']
    assert facts['tableOverflows'] is False, 'the row widened its own table'
    assert facts['pageBar'][0] <= facts['pageBar'][1] + 1, f'the page grew a horizontal bar: {facts["pageBar"]}'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_record_that_skipped_workflows_names_them_on_screen(app_url, driver, lang):
    """The 跳过 chip, measured where the user reads it.

    A disabled workflow leaves no node rows anywhere, so without this chip a
    record read back next week cannot tell "we chose not to run 凌晨热身" from
    "凌晨热身 was deleted". The chip's wording comes from the REAL app.js catalog
    (the node harness stubs I18n, so only the browser proves the key exists in
    both languages), and the longer English label must still not clip or grow a
    page-level bar.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        const panel = document.getElementById('runs-panel');
        panel.classList.add('open');
        panel.classList.remove('hidden');
        runsManager.render([
            {run_id: 'skip1', workflow_name: '白天榜', status: 'completed', resumable: false,
             node_done: 2, node_total: 2, rows_kept: 10, started_at: '2026-09-26 03:00',
             mode: 'serial', wf_count: 1, headless: 1, skipped_workflows: '凌晨热身 + 夜间增量'},
            {run_id: 'clean1', workflow_name: '干净榜', status: 'completed', resumable: false,
             node_done: 2, node_total: 2, rows_kept: 10, started_at: '2026-09-26 04:00',
             mode: 'serial', wf_count: 1, headless: 1, skipped_workflows: ''},
        ]);
        """,
        [lang],
    )
    facts = driver.execute_script(
        """
        const rows = Array.from(document.querySelectorAll('#runs-panel tbody tr'));
        const of = (id) => rows.filter((r) => (r.getAttribute('data-run-id') || '') === id)[0];
        const skip = of('skip1');
        const clean = of('clean1');
        if (!skip || !clean) return {found: false};
        const chipTexts = (row) =>
            Array.from(row.querySelectorAll('.runs-mgr-wf .runs-mgr-tag')).map((c) => c.textContent);
        return {
            found: true,
            chips: chipTexts(skip),
            cleanChips: chipTexts(clean),
            label: I18n.t('runsMgr.skipped').replace('{names}', '凌晨热身 + 夜间增量'),
            clipped: Array.from(skip.querySelectorAll('.runs-mgr-tag')).filter(function (c) {
                return c.scrollWidth - c.clientWidth > 1;
            }).length,
            pageBar: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
        };
        """,
        [],
    )
    assert facts['found'] is True, 'the two rows rendered nothing, so nothing was measured'
    assert 'runsMgr.' not in facts['label'], f'{lang} catalog has no word for runsMgr.skipped'
    assert facts['label'] in facts['chips'], f'the skipping row must wear the named chip: {facts["chips"]}'
    # A one-workflow 串行 record now also wears the 串行 ×1 chip (user directive), so the
    # skip row reads three: mode + window + skipped. The skip chip is the one under test.
    assert len(facts['chips']) == 3, f'expected 串行×1 + window + skip chips: {facts["chips"]}'
    assert any('串行' in c or 'serial' in c.lower() for c in facts['chips']), f'no serial chip: {facts["chips"]}'
    assert not any('凌晨' in c for c in facts['cleanChips']), f'the clean row grew a skip chip: {facts["cleanChips"]}'
    assert facts['clipped'] == 0, f'a chip is silently cut off in {lang}: {facts["chips"]}'
    assert facts['pageBar'][0] <= facts['pageBar'][1] + 1, f'the page grew a horizontal bar: {facts["pageBar"]}'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_disabled_node_goes_grey_and_its_downstream_says_so(app_url, driver, lang):
    """The disable visuals, read from computed styles — not from the class list.

    The node harness proves the classes land; only a real engine can prove the
    user actually SEES them: the off box really renders greyed and translucent,
    the starved box really wears a dashed frame and a named badge, the wire
    between them really dims, and the power button on a live node carries a
    resolved tooltip in this language. Toggling back must clear all of it. Two
    connected nodes are drawn (floor: 2 boxes, 1 wire measured).
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    facts = driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        // The boot restore paints whatever the shared Chrome profile saved last —
        // nodes, wires and type switches included. Measure on a canvas the page
        // itself owns: empty, like a first visit.
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        canvas.disabledTypes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';
        const idA = canvas.addNode('source', 120, 120);
        const idB = canvas.addNode('process', 420, 120);
        const ids = [idA, idB];
        canvas.connections.push({ from: ids[0], to: ids[1] });
        canvas.updateConnections();

        const probe = () => {
            const box = (id) => {
                const el = canvas._nodeEl(id);
                const cs = getComputedStyle(el);
                const badge = el.querySelector('.node-state-badge');
                return {
                    opacity: parseFloat(cs.opacity),
                    filter: cs.filter,
                    classes: el.className,
                    borderStyle: cs.borderTopStyle,
                    badge: badge ? badge.textContent : null,
                    badgeShown: badge ? getComputedStyle(badge).display !== 'none' : null,
                    powerTitle: el.querySelector('.node-power-btn').title,
                };
            };
            const wires = Array.from(document.querySelectorAll('#svg-layer path.conn-line'));
            return {
                head: box(ids[0]),
                child: box(ids[1]),
                wiresMeasured: wires.length,
                wireDimmed: wires.filter((w) => w.classList.contains('conn-disabled')).length,
            };
        };
        const onBefore = probe();
        // Click the real power button — the same handler a drag-and-drop user reaches.
        canvas._nodeEl(ids[0]).querySelector('.node-power-btn').click();
        canvas.updateConnections();
        canvas.applyDisabledVisuals();
        const offAfter = probe();
        canvas._nodeEl(ids[0]).querySelector('.node-power-btn').click();
        canvas.updateConnections();
        canvas.applyDisabledVisuals();
        const onAgain = probe();
        return {
            onBefore,
            offAfter,
            onAgain,
            disableWord: I18n.t('node.badgeDisabled'),
            starveWord: I18n.t('node.badgeNoInput'),
        };
        """,
        [lang],
    )
    before, disabled, again = facts['onBefore'], facts['offAfter'], facts['onAgain']
    assert before['wiresMeasured'] >= 1 and disabled['wiresMeasured'] >= 1, 'no wire was measured, so dimming was not'
    # live before: fully opaque, no grey filter, no dimmed wire
    assert before['head']['opacity'] > 0.99 and before['child']['opacity'] > 0.99, before
    assert before['wireDimmed'] == 0, f'a fresh wire reads as disabled: {before}'
    assert disabled['head']['badge'] == facts['disableWord'], f'the off box badge fell back: {disabled["head"]}'
    assert disabled['child']['badge'] == facts['starveWord'], f'the starved box badge fell back: {disabled["child"]}'
    assert 'node.' not in facts['disableWord'], 'zh/en catalog gap on node.badgeDisabled'
    assert 'node.' not in facts['starveWord'], 'zh/en catalog gap on node.badgeNoInput'
    # disabled: grey + translucent, badge shown, downstream dashed, the wire dimmed
    assert disabled['head']['opacity'] < 0.6, f'the disabled box is not visibly faded: {disabled["head"]}'
    assert 'grayscale' in disabled['head']['filter'], f'the disabled box is not greyed: {disabled["head"]}'
    assert disabled['head']['badgeShown'] is True and disabled['child']['badgeShown'] is True, disabled
    assert disabled['child']['borderStyle'] == 'dashed', f'starvation is not drawn as a frame: {disabled["child"]}'
    assert disabled['wireDimmed'] == 1, f'the wire to the disabled box did not dim: {disabled}'
    # re-enabled: every visual cleared, and the button's tooltip speaks this language
    assert again['head']['opacity'] > 0.99 and again['child']['opacity'] > 0.99, again
    assert again['wireDimmed'] == 0, f'a re-enabled wire stayed dim: {again}'
    assert again['head']['badge'] == '' and again['child']['badge'] == '', again
    assert again['head']['powerTitle'] and 'ctx.' not in again['head']['powerTitle'], (
        f'the power tooltip is untranslated in {lang}: {again["head"]["powerTitle"]!r}'
    )
    """The 工作流文件 table draws a user-chosen stem twice: as text, and inside the
    ``onclick="wfFiles.rename('…')"`` attribute the row buttons are made of.

    Only a real HTML parser can say whether that attribute held. The node harness
    sees the string the product assigned; the browser is what decides whether one
    double quote in a file name closed the attribute and turned the rest of the
    name into markup — and whether the cell still fits its row instead of growing a
    page-level bar. Nothing is written: ``fetch`` is stubbed.
    """
    hostile = 'q"uote \'quote \\slash <img src=x onerror=alert(1)> 以及一段很长的中文工作流名称用来把它撑开'
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        window.__calls = [];
        window.fetch = function (url, opts) {{
            window.__calls.push({{ url: String(url), body: opts && opts.body ? String(opts.body) : null }});
            const payload = {{ ok: true, name: {hostile!r}, workflows: [] }};
            return Promise.resolve({{
                ok: true, json: () => Promise.resolve(payload), text: () => Promise.resolve(JSON.stringify(payload)),
            }});
        }};
        window.showDialog = () => Promise.resolve('renamed');
        const panel = document.getElementById('workflows-panel');
        panel.classList.add('open');
        panel.classList.remove('hidden');
        wfFiles._last = [
            {{ name: {hostile!r}, nodes: 3, labels: [], size: 400, mtime: 1760000000, broken: false }},
            {{ name: 'broken', nodes: 0, labels: [], size: 10, mtime: 0, broken: true }},
        ];
        workflow.currentFile = {hostile!r};
        wfFiles.render();
        """,
        [],
    )
    facts = driver.execute_script(
        """
        const cell = document.querySelector('#workflows-mgr-body .runs-mgr-wf');
        const buttons = Array.from(document.querySelectorAll('#workflows-mgr-body .runs-mgr-btn'));
        const rename = buttons.find((b) => (b.getAttribute('onclick') || '').indexOf('rename') >= 0);
        window.__calls = [];
        if (rename) rename.click();
        const table = document.querySelector('#workflows-mgr-body table');
        return {
            text: cell ? cell.textContent : null,
            buttons: buttons.length,
            imgElements: document.querySelectorAll('#workflows-mgr-body img').length,
            clipped: cell ? cell.scrollWidth - cell.clientWidth : null,
            cellRight: cell ? Math.round(cell.getBoundingClientRect().right) : null,
            windowWidth: window.innerWidth,
            tableOverflows: table ? table.scrollWidth - table.clientWidth : null,
            page: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
        };
        """,
        [],
    )
    # The click answers a promise before it fetches, so the request is polled rather
    # than read in the same task — reading it synchronously passes by accident and
    # fails whenever the page is busy.
    deadline = time.monotonic() + 10
    calls: list = []
    while time.monotonic() < deadline:
        calls = driver.execute_script('return window.__calls;', [])
        if any(str(c['url']).split('?')[0] == '/api/workflow/rename' for c in calls):
            break
        time.sleep(0.2)
    assert facts['text'] and 'q"uote' in facts['text'] and '<img' in facts['text'], facts['text']
    assert facts['imgElements'] == 0, 'the name reached the DOM as a tag, not as text'
    rename_calls = [c for c in calls if str(c['url']).split('?')[0] == '/api/workflow/rename']
    assert rename_calls, f'the click never reached the server: {calls}'
    assert json.loads(rename_calls[0]['body'])['name'] == hostile, (
        f'the name the button handed over is not the name on disk: {rename_calls[0]["body"]!r}'
    )
    assert facts['cellRight'] <= facts['windowWidth'] + 1, f'the name cell runs off the window: {facts}'
    assert facts['page'][0] <= facts['page'][1] + 1, f'the page grew a horizontal bar: {facts["page"]}'
    if facts['clipped'] and facts['clipped'] > 1:
        assert facts['tableOverflows'] > 1, f'the cell is cut off with no way to reach the rest: {facts}'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_dialog_never_asks_the_browser_to_overflow_it(app_url, driver, lang):
    """Measured inside the page, not read off the stylesheet.

    The 「用不用 Profile」 buttons carried whole sentences and `.menu-btn` is
    ``white-space: nowrap``, so the row could neither shrink nor wrap and the label ran
    out of the box — which the user read as truncated text. Every property that fixes
    this can be present in the CSS and still lose in the browser, so the only assertion
    that means anything here is a rect.
    """
    driver.set_window_size(1000, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(f"document.body.dataset.lang = '{lang}'; I18n.apply();")
    report = driver.execute_script(
        """
        showDialog({
            message: I18n.t('dialog.profileClash')
                .replace('{platforms}', platformLabels(['weibo', 'zhihu']))
                .replace('{n}', 2),
            buttons: [
                { label: I18n.t('dialog.profileClashUse'), value: 'use' },
                { label: I18n.t('dialog.profileClashSkip'), value: 'skip', primary: true },
                { label: I18n.t('dialog.cancel'), value: null },
            ],
        });
        const box = document.getElementById('dialog-box').getBoundingClientRect();
        const buttons = Array.from(document.querySelectorAll('#dialog-actions .menu-btn'));
        const worst = buttons.map((node) => {
            const r = node.getBoundingClientRect();
            return {
                text: node.textContent.slice(0, 20),
                /* Past 1px of rounding slack this is text the user cannot read: either the
                   box was stepped out of, or the label was clipped inside its own button. */
                over: Math.round(Math.max(
                    r.right - box.right, box.left - r.left, node.scrollWidth - node.clientWidth
                )),
            };
        });
        const rows = document.getElementById('dialog-actions').getBoundingClientRect();
        document.getElementById('dialog-overlay').classList.remove('open');
        return {
            measured: buttons.length,
            worst: worst,
            boxWidth: Math.round(box.width),
            actionsBottom: Math.round(rows.bottom - box.bottom),
        };
        """,
        [],
    )
    assert report['measured'] == 3, f'the dialog drew {report["measured"]} buttons, not the three asked for'
    over = [w for w in report['worst'] if w['over'] > 1]
    assert not over, f'{lang}: button text escapes the {report["boxWidth"]}px dialog box: {over}'
    assert report['actionsBottom'] <= 1, f'the button row hangs below the box: {report}'


def test_the_dialog_dismisses_by_x_backdrop_and_esc(app_url, driver):
    """The corner X is OPT-IN (only an info dialog with no buttons — 采集建议 — draws
    it), but every dialog is still dismissable by backdrop click and Esc, resolving
    the "no answer" value (null). A dismissable:false dialog (cookie login) must ignore
    all of it. Measured in the real browser: only a real event dispatch proves the
    backdrop-target check and the keydown handler fire, and that dismissing a dialog
    removes its close button so it cannot leak across dialogs."""
    driver.set_window_size(1000, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)

    # Default dialog: NO corner X (opt-in policy), yet the backdrop dismisses it.
    driver.execute_script(
        """
        window.__r = '__pending__';
        showDialog({ message: 'd' }).then(v => { window.__r = (v === null ? 'null' : String(v)); });
        window.__hadClose = !!document.querySelector('#dialog-box .dialog-close');
        document.getElementById('dialog-overlay').dispatchEvent(new MouseEvent('click', { bubbles: true }));
        """,
        [],
    )
    default_no_x = driver.execute_script(
        'return { hadClose: window.__hadClose, resolved: window.__r, '
        "open: document.getElementById('dialog-overlay').classList.contains('open') };",
        [],
    )
    assert default_no_x['hadClose'] is False, 'a default dialog must not draw the X (opt-in only)'
    assert default_no_x['resolved'] == 'null' and not default_no_x['open'], (
        f'backdrop must dismiss a default dialog: {default_no_x}'
    )

    # showClose:true (the advice dialog): a drawn SVG X, clicking it resolves null + is removed.
    present = driver.execute_script(
        """
        window.__r = '__pending__';
        showDialog({ message: 'x', showClose: true }).then(v => { window.__r = (v === null ? 'null' : String(v)); });
        const c = document.querySelector('#dialog-box .dialog-close');
        return { hasClose: !!c, hasSvg: !!(c && c.querySelector('svg')) };
        """,
        [],
    )
    assert present['hasClose'], 'showClose:true must draw a close (X) button'
    assert present['hasSvg'], 'the dialog close is not a drawn SVG'

    driver.execute_script("document.querySelector('#dialog-box .dialog-close').click();")
    xres = driver.execute_script(
        """
        return {
            resolved: window.__r,
            open: document.getElementById('dialog-overlay').classList.contains('open'),
            gone: !document.querySelector('#dialog-box .dialog-close'),
        };
        """,
        [],
    )
    assert xres['resolved'] == 'null', f'the X resolved {xres["resolved"]!r}, not "no answer" (null)'
    assert not xres['open'], 'the overlay stayed open after the X'
    assert xres['gone'], 'the close button must be removed on dismiss (no leak across dialogs)'

    # Esc dismisses a default dialog too.
    driver.execute_script(
        """
        window.__r = '__pending__';
        showDialog({ message: 'e' }).then(v => { window.__r = (v === null ? 'null' : String(v)); });
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        """,
        [],
    )
    esc = driver.execute_script(
        "return { resolved: window.__r, open: document.getElementById('dialog-overlay').classList.contains('open') };",
        [],
    )
    assert esc['resolved'] == 'null' and not esc['open'], f'Esc did not dismiss: {esc}'

    # A dialog that opts out (cookie login) must NOT be dismissable: no X, backdrop/Esc inert.
    noauto = driver.execute_script(
        """
        window.__r = '__pending__';
        showDialog({ message: 'lock', dismissable: false }).then(
            v => { window.__r = (v === null ? 'null' : String(v)); });
        const before = !!document.querySelector('#dialog-box .dialog-close');
        document.getElementById('dialog-overlay').dispatchEvent(new MouseEvent('click', { bubbles: true }));
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        const stillOpen = document.getElementById('dialog-overlay').classList.contains('open');
        document.getElementById('dialog-overlay').classList.remove('open');  // manual teardown
        return { hadClose: before, resolved: window.__r, stillOpen: stillOpen };
        """,
        [],
    )
    assert noauto['hadClose'] is False, 'a dismissable:false dialog must not show an X'
    assert noauto['stillOpen'] is True, 'a dismissable:false dialog must ignore backdrop/Esc'
    assert noauto['resolved'] == '__pending__', 'a dismissable:false dialog must not resolve on dismiss'


def test_the_resume_banner_gets_out_of_the_pinned_menu_s_way(app_url, driver):
    """The menu bar is ``position: fixed`` and covers the top ``--menuH`` of the viewport
    while pinned, and the banner used to sit at a fixed ``top: 8px`` underneath it —
    hiding the very 继续 button the user came to the page to press. Only a computed style
    proves the selector matches the real element tree.

    The bar is taken off first rather than assumed: this app persists the pin and boots
    with it on, so a measurement that starts from whatever the page happened to load
    compares pinned with pinned and passes on a rule that does nothing.
    """
    driver.set_window_size(1280, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    moved = driver.execute_script(
        """
        const banner = document.getElementById('resume-banner');
        const bar = document.getElementById('top-menu');
        banner.classList.remove('hidden');
        bar.classList.remove('pinned');
        const free = parseFloat(getComputedStyle(banner).top);
        bar.classList.add('pinned');
        const pushed = parseFloat(getComputedStyle(banner).top);
        const height = Math.round(bar.getBoundingClientRect().height);
        bar.classList.remove('pinned');
        banner.classList.add('hidden');
        return { free: free, pushed: pushed, height: height };
        """,
        [],
    )
    assert moved['pushed'] > moved['free'], f'pinning the menu did not move the banner: {moved}'
    assert moved['pushed'] >= moved['free'] + moved['height'], (
        f'the banner moved by {moved["pushed"] - moved["free"]}px, which does not clear a '
        f'{moved["height"]}px bar: {moved}'
    )


def test_switching_console_tabs_keeps_the_lines_already_shown(app_url, driver):
    """The console is the one panel whose content cannot be rebuilt by asking.

    ``/api/workflow/status`` ships only the tail of the run, so a tab switch that
    blanks the box leaves it empty until the next line arrives — for a finished run
    that is forever, which is what the user reported as "切换标签页就清空了". The
    driver feeds the real poller scripted answers, then clicks between the 全部 tab
    and a workflow tab and reads back what is on screen.

    ``fetch`` is stubbed, so no run is started and nothing is written.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        """
        const lines = ['第一行', '第二行', '第三行'];
        let sent = 0;
        window.__poll = { answer: null };
        window.fetch = function (url) {
            const payload = {
                running: true, logs: lines, log_total: lines.length, mode: 'parallel',
                workflows: [
                    { id: 0, name: '甲', logs: ['甲的第一行', '甲的第二行'], total: 2 },
                    { id: 1, name: '乙', logs: ['乙的第一行'], total: 1 }
                ],
                results: [], chart_results: {}, cookie_expired: false, queue: [],
                total_nodes: 3, completed_nodes: sent
            };
            sent += 1;
            return Promise.resolve({ json: () => Promise.resolve(payload), text: () => Promise.resolve('') });
        };
        document.getElementById('console-panel').classList.add('open');
        // One tick of the real poller: capture the callback setInterval was given.
        window.__tick = null;
        const realInterval = window.setInterval;
        window.setInterval = function (fn) { window.__tick = fn; return 1; };
        workflow.pollStatus();
        window.setInterval = realInterval;
        return window.__tick();
        """,
        [],
    )
    seen = driver.execute_script(
        """
        const read = () => Array.from(document.querySelectorAll('#console-output .console-line'))
            .map((el) => el.textContent);
        const before = read();
        switchWfTab(0);
        const tabA = read();
        switchWfTab(1);
        const tabB = read();
        switchWfTab('all');
        return { before: before, tabA: tabA, tabB: tabB, backToAll: read() };
        """,
        [],
    )
    assert seen['before'] == ['第一行', '第二行', '第三行'], seen['before']
    assert seen['tabA'] == ['甲的第一行', '甲的第二行'], f'the 甲 tab opened blank: {seen}'
    assert seen['tabB'] == ['乙的第一行'], f'the 乙 tab did not show only its own lines: {seen}'
    assert seen['backToAll'] == seen['before'], f'coming back to 全部 lost or duplicated lines: {seen}'


def test_deleting_one_history_row_reaches_the_server_with_that_run_only(app_url, driver):
    """The button is delegated, so only a real click proves it works.

    The row list is re-rendered on every reload, which is exactly the shape a
    per-row listener gets wrong (it would fire once per refresh). And the id has
    to arrive as the clicked row's — a handler reading the wrong attribute deletes
    somebody else's history.

    ``fetch`` is stubbed for the whole test: this tier must not write, and a live
    ``/api/history/delete`` would erase a record of the user's own runs.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        """
        window.__calls = [];
        window.fetch = function (url, opts) {
            window.__calls.push({ url: String(url), body: opts && opts.body ? String(opts.body) : null });
            const path = String(url).split('?')[0];
            let payload = { ok: true };
            if (path === '/api/history/runs') {
                payload = { ok: true, workflow_names: ['甲', '乙'], runs: [
                    { run_id: 'r-keep', workflow_name: '甲', started_at: '2026-09-24T01:00:00', metric_count: 3 },
                    { run_id: 'r-del', workflow_name: '乙', started_at: '2026-09-24T02:00:00', metric_count: 2 },
                ] };
            } else if (path === '/api/history/series') {
                payload = { ok: true, rows: [] };
            } else if (path === '/api/history/delete') {
                payload = { ok: true, deleted: 2, run_id: JSON.parse(opts.body).run_id };
            }
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve(payload),
                text: () => Promise.resolve(JSON.stringify(payload)),
            });
        };
        """,
        [],
    )
    # The dialog is the app's own promise-based confirm; answer it without the
    # user, and say yes.
    driver.execute_script(
        """
        window.__dialogs = [];
        window.showDialog = function (spec) {
            window.__dialogs.push(spec && spec.message ? String(spec.message) : '');
            return Promise.resolve(true);
        };
        """,
        [],
    )
    # Opened through the real ``open()``: that is where the delegated listener for
    # the row buttons is installed, so a test that only called ``_loadRuns()``
    # would click a button nothing is listening to.
    driver.execute_script('historyPanel._renderChart = function () {}; return historyPanel.open();', [])
    clicked = driver.execute_script(
        """
        const buttons = document.querySelectorAll('#history-runs-wrap .history-del');
        if (buttons.length !== 2) return { count: buttons.length };
        const target = Array.from(buttons).find((b) => b.getAttribute('data-run-id') === 'r-del');
        target.click();
        return { count: buttons.length, found: !!target };
        """,
        [],
    )
    assert clicked['count'] == 2, f'one button per recorded run: {clicked}'
    assert clicked['found'] is True, 'the clicked row is not addressable by its own run id'
    deadline = time.monotonic() + 10
    calls: list = []
    while time.monotonic() < deadline:
        calls = driver.execute_script('return window.__calls;', [])
        if any(str(c['url']).split('?')[0] == '/api/history/delete' for c in calls):
            break
        time.sleep(0.2)
    delete_calls = [c for c in calls if str(c['url']).split('?')[0] == '/api/history/delete']
    assert delete_calls, f'the click never reached the server: {calls}'
    assert json.loads(delete_calls[0]['body']) == {'run_id': 'r-del'}, delete_calls[0]['body']
    asked = driver.execute_script('return window.__dialogs;', [])
    assert asked and 'r-del' in asked[0], f'the confirmation must name the run about to vanish: {asked}'
    layout = driver.execute_script(
        """
        const wrap = document.getElementById('history-runs-wrap');
        const table = wrap.querySelector('table');
        const buttons = Array.from(wrap.querySelectorAll('.history-del'));
        return [document.documentElement.scrollWidth, document.documentElement.clientWidth,
                table.scrollWidth - table.clientWidth,
                buttons.filter((b) => b.scrollWidth - b.clientWidth > 1).length];
        """,
        [],
    )
    assert layout[0] <= layout[1] + 1, f'the extra column grew a page-level horizontal bar: {layout}'
    assert layout[3] == 0, f'a delete button is cut off, so the user cannot read what it says: {layout}'


@pytest.mark.parametrize('width', [1024, 1280])
def test_a_narrow_window_moves_the_floating_popups_inside_it(app_url, driver, width):
    """The dashboard and the history panel are positioned from their button; on a
    narrow window a right-anchored popup can hang off the edge, which is a page
    scroll bar rather than a panel scroll bar.

    The containers are listed by id because the page has no shared class for them
    — a ``.panel`` selector matches nothing here, and matched nothing for as long as
    this test has existed, which is how it kept passing while checking zero elements.
    """
    driver.set_window_size(width, 700)
    driver.get(app_url + '/')
    _kill_animations(driver)
    shown, offenders = driver.execute_script(
        """
        const seen = [];
        for (const id of arguments[0]) {
            const el = document.getElementById(id);
            if (!el) continue;
            el.classList.add('open');
            el.classList.remove('hidden');
            const r = el.getBoundingClientRect();
            // A container CSS keeps off screen until it is really opened (a
            // dropdown anchored to a hidden button) has no layout to judge.
            if (r.width <= 0 || r.height <= 0 || getComputedStyle(el).visibility === 'hidden') continue;
            seen.push([id, Math.round(r.left), Math.round(r.right), window.innerWidth]);
        }
        return [seen, seen.filter(([id, left, right, w]) => left < -1 || right > w + 1)];
        """,
        PANELS,
    )
    assert len(shown) >= 10, f'{width}px: only {len(shown)} of {len(PANELS)} containers had a box to measure: {shown}'
    assert not offenders, f'{width}px: containers outside the window: {offenders}'
    page = driver.execute_script(
        'return [document.documentElement.scrollWidth, document.documentElement.clientWidth];', []
    )
    assert page[0] <= page[1] + 1, f'{width}px: the page scrolls sideways: {page}'


# ─── the node box, and the delegated buttons on it ─────────────────────


NODE_JS = """
canvas.nodes = {}; canvas.connections = [];
document.getElementById('nodes-container').innerHTML = '';
const wide = '这个关键词特别长长长长长长长长长长长长长长长长长长'.repeat(3);
const a = canvas.addNode('source', 20, 20);
canvas.nodes[a].params.keyword = wide;
canvas.nodes[a].title = wide;
canvas.updateNodeDisplay(a);
const b = canvas.addNode('output', 400, 20);
const el = document.getElementById(a);
const title = el.querySelector('.node-title');
return {
    a, b,
    boxWidth: el.offsetWidth,
    titleOverflow: title.scrollWidth - title.clientWidth,
    titleEllipsis: getComputedStyle(title).textOverflow === 'ellipsis',
    nodeMaxWidth: getComputedStyle(el).maxWidth,
    pageScroll: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
    markup: el.innerHTML,
};
"""


def _quiet_canvas(driver, app_url):
    """Load the page with nothing on the canvas and nothing left to restore.

    Boot rebuilds the canvas from the autosaved draft — the previous test's nodes —
    and that repaint replaces ``#nodes-container``'s children. A test that injected
    its own nodes right after ``get()`` could therefore have them removed underneath
    it, which surfaced as ``document.getElementById(<node id>)`` answering null and
    the click script dying inside the page (measured once in five runs, and a test
    that fails one time in five is a test that tells you nothing when it passes).
    """
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        """
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        """,
        [],
    )


def test_a_wide_node_is_bounded_and_its_title_says_it_was_cut(app_url, driver):
    """A node summary is user text; without a ceiling one long keyword made the
    whole page scroll sideways, and without an ellipsis a truncated title just
    looked like a shorter name."""
    driver.set_window_size(1366, 768)
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(NODE_JS, [])
    assert made['nodeMaxWidth'] != 'none', 'the .node max-width guard is gone'
    assert made['boxWidth'] <= 340, f'the node grew to {made["boxWidth"]}px'
    assert made['titleEllipsis'] is True, 'a clipped title with no ellipsis reads as a shorter name'
    assert made['pageScroll'][0] <= made['pageScroll'][1] + 1, 'a wide node grew the page sideways'


AUTO_LAYOUT_JS = """
canvas.nodes = {}; canvas.connections = [];
document.getElementById('nodes-container').innerHTML = '';
localStorage.removeItem('crawler_canvas');
const wide = '这个关键词特别长长长长长长长长长长长长长长长长长长'.repeat(6);
const a = canvas.addNode('source', 20, 20);
canvas.nodes[a].params.platform = 'zhihu';
canvas.nodes[a].params.keyword = wide;
canvas.updateNodeDisplay(a);
const b = canvas.addNode('output', 60, 500);
canvas.nodes[b].params.operation = 'save';
canvas.nodes[b].params.filename = 'x.csv';
canvas.updateNodeDisplay(b);
canvas.connections = [{from: a, to: b}];
canvas.autoLayout();
canvas.updateConnections();
const rects = {};
[a, b].forEach((id) => {
    const r = document.getElementById(id).getBoundingClientRect();
    rects[id] = [r.left, r.top, r.right, r.bottom];
});
const paths = Array.from(document.querySelectorAll('.conn-line:not(.temp)'))
    .map((p) => p.getAttribute('d') || '');
return { a, b, rects, paths };
"""


def test_auto_layout_clears_a_wide_node_and_draws_its_wire_flat(app_url, driver):
    """The layout reads the REAL boxes now: a wide+tall source must not be overlapped
    by its downstream, and a forward wire between centre-aligned ranks must be flat.

    Both halves were browser-false before: the fixed 280×120 lattice put the next
    rank inside a 340-wide node, and the equal-TOPS rule offset the port centres of
    unequal heights, so the bezier bowed. The node harness fakes offsetWidth/Height —
    this is the tier that measures pixels; it asserts on everything it counted.
    """
    driver.set_window_size(1366, 768)
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(AUTO_LAYOUT_JS, [])
    ra, rb = made['rects'][made['a']], made['rects'][made['b']]
    overlap_x = min(ra[2], rb[2]) - max(ra[0], rb[0])
    overlap_y = min(ra[3], rb[3]) - max(ra[1], rb[1])
    assert not (overlap_x > 1 and overlap_y > 1), (
        f'the downstream node sits {round(overlap_x)}x{round(overlap_y)}px inside the wide one: {made["rects"]}'
    )
    assert len(made['paths']) == 1, f'expected exactly the one wire measured, got {made["paths"]}'
    d = made['paths'][0]
    assert ' L ' in d and ' C ' not in d, f'the forward wire between centre-aligned ranks still bows: {d}'


AUTO_LAYOUT_FIT_JS = """
canvas.nodes = {}; canvas.connections = [];
document.getElementById('nodes-container').innerHTML = '';
localStorage.removeItem('crawler_canvas');
/* A long chain autoLayout spreads past the laptop window: twelve ranks of
   ~200px + 120px gaps run far wider than the 1344px workspace. Before this change
   autoLayout centred its own result at 100%, leaving the tail off-screen; now it
   delegates the camera to resetView, so a relayout must fit like 适应 does. */
const ids = [];
let prev = null;
for (let i = 0; i < 12; i++) {
    const id = canvas.addNode(i === 11 ? 'output' : 'process', 0, 0);
    ids.push(id);
    if (prev) canvas.connections.push({ from: prev, to: id });
    prev = id;
}
canvas.autoLayout();
const work = document.getElementById('workspace').getBoundingClientRect();
const boxes = {};
ids.forEach((id) => {
    const r = document.getElementById(id).getBoundingClientRect();
    boxes[id] = [r.left, r.top, r.right, r.bottom];
});
return { zoom: canvas.zoom, boxes,
         menuH: document.getElementById('top-menu').offsetHeight,
         viewport: [work.left, work.top, work.right, work.bottom] };
"""


def test_auto_layout_fits_the_camera_like_adapt(app_url, driver):
    """The user's #171: 自动布局 = 重新排布 + 适应. After relaying a chain that no
    longer fits at 100%, the camera must have SHRUNK (zoom<1) and every node must sit
    inside the workspace and below the menu bar — the exact contract 适应 upholds,
    because autoLayout now calls it rather than centre-at-100% on its own."""
    driver.set_window_size(1366, 768)
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(AUTO_LAYOUT_FIT_JS, [])
    wl, wt, wr, wb = made['viewport']
    vp = made['viewport']
    assert len(made['boxes']) == 12, f'expected twelve relaid nodes, measured {len(made["boxes"])}'
    assert made['zoom'] < 1, f'autoLayout left the wide chain at {made["zoom"]:.2f}, so the tail is off-screen'
    assert made['menuH'] > 0, 'the menu bar reported no height; the clearance assertion is vacuous'
    for box in made['boxes'].values():
        assert box[0] >= wl - 1 and box[2] <= wr + 1, f'node outside the viewport horizontally: {box} in {vp}'
        assert box[1] >= wt - 1 and box[3] <= wb + 1, f'node outside the viewport vertically: {box} in {vp}'
        assert box[1] >= wt + made['menuH'] - 1, f'node sits under the {made["menuH"]}px menu bar: top={box[1]}'


FIT_VIEW_JS = """
canvas.nodes = {}; canvas.connections = [];
document.getElementById('nodes-container').innerHTML = '';
localStorage.removeItem('crawler_canvas');
/* Two nodes spread past the laptop window in canvas-local coords; the OLD 适应
   pinned zoom at 100%, so the far one landed off the right/bottom edge. The spread
   stays inside the app's 0.2 minimum zoom, so what this proves is 适应 not fitting. */
const a = canvas.addNode('source', 0, 0);
const b = canvas.addNode('output', 3000, 1800);
canvas.connections = [{from: a, to: b}];
canvas.resetView();
const work = document.getElementById('workspace').getBoundingClientRect();
const boxes = {};
[a, b].forEach((id) => {
    const r = document.getElementById(id).getBoundingClientRect();
    boxes[id] = [r.left, r.top, r.right, r.bottom];
});
return { a, b, boxes, zoom: canvas.zoom,
         menuH: document.getElementById('top-menu').offsetHeight,
         viewport: [work.left, work.top, work.right, work.bottom] };
"""


def test_fit_view_clears_the_menu_and_holds_the_whole_cluster(app_url, driver):
    """The user's report about 适应: it only centred at 100%, so a wide layout left
    nodes off-screen AND a pinned menu bar sat on top of them. After fit EVERY node
    box must lie inside the workspace AND below the menu bar — measured in real
    rendered pixels, the only tier that sees true offsetWidth and the true menu."""
    driver.set_window_size(1366, 768)
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(FIT_VIEW_JS, [])
    wl, wt, wr, wb = made['viewport']
    vp = made['viewport']
    assert made['zoom'] < 1, f'fit did not shrink the far cluster: zoom {made["zoom"]}'
    assert made['menuH'] > 0, 'the menu bar reported no height; the clearance assertion is vacuous'
    for box in made['boxes'].values():
        assert box[0] >= wl - 1 and box[2] <= wr + 1, f'node outside the viewport horizontally: {box} in {vp}'
        assert box[1] >= wt - 1 and box[3] <= wb + 1, f'node outside the viewport vertically: {box} in {vp}'
        assert box[1] >= wt + made['menuH'] - 1, f'node sits under the {made["menuH"]}px menu bar: top={box[1]}'


PALETTE_COLLAPSE_JS = """
function state() {
    const panel = document.getElementById('node-palette');
    const item = panel.querySelector('.palette-item');
    const header = panel.querySelector('.palette-header');
    const toggle = panel.querySelector('.palette-toggle');
    return {
        collapsed: panel.classList.contains('collapsed'),
        itemShown: !!item && getComputedStyle(item).display !== 'none',
        headerShown: getComputedStyle(header).display !== 'none' && header.offsetHeight > 0,
        toggleShown: toggle.offsetHeight > 0,
        panelHeight: panel.offsetHeight,
        aria: toggle.getAttribute('aria-expanded'),
        title: toggle.title,
    };
}
const before = state();
document.querySelector('.palette-toggle').click();
const collapsed = state();
document.querySelector('.palette-toggle').click();
const expanded = state();
return { before, collapsed, expanded };
"""


def test_the_node_library_collapses_out_of_the_way_and_reopens(app_url, driver):
    """The library floats over the canvas, so a wide layout hid behind it. The toggle
    must hide the item list but KEEP the header clickable (a way back), shrink the
    panel, and flip its own state; a second click restores it byte-for-byte. Every
    value below is measured on a real page — this is the tier that sees CSS."""
    driver.set_window_size(1366, 768)
    _quiet_canvas(driver, app_url)
    got = driver.execute_script(PALETTE_COLLAPSE_JS, [])
    before, collapsed, expanded = got['before'], got['collapsed'], got['expanded']

    assert before['collapsed'] is False and before['itemShown'] is True, before
    assert collapsed['collapsed'] is True, 'clicking the toggle did not mark the panel collapsed'
    assert collapsed['itemShown'] is False, 'the item list is still visible when collapsed'
    assert collapsed['headerShown'] is True and collapsed['toggleShown'] is True, (
        'collapsing removed the only way back: ' + str(collapsed)
    )
    assert collapsed['panelHeight'] < before['panelHeight'], (
        f'the collapsed panel did not shrink: {collapsed["panelHeight"]} vs {before["panelHeight"]}'
    )
    assert collapsed['aria'] == 'false' and before['aria'] == 'true', (
        'aria-expanded did not follow the collapse: ' + str(before['aria']) + '→' + str(collapsed['aria'])
    )
    assert collapsed['title'] and collapsed['title'] != expanded['title'], (
        'the toggle tooltip does not change with state (and is not localized): ' + str(collapsed['title'])
    )
    assert expanded == before, f'the second click did not restore the panel: {expanded} vs {before}'


COOKIE_FIT_JS = """
document.body.dataset.lang = 'zh';
I18n.apply();
const box = document.getElementById('cookie-dialog');
const select = document.getElementById('cookie-platform');
const opts = Array.prototype.map.call(select.options || [], (o) => o.value).filter((v) => v);
const rows = [];
opts.forEach((p) => {
    select.value = p;
    openCookieDialog(p);
    rows.push({ platform: p, scroll: box.scrollHeight, client: box.clientHeight });
    box.classList.remove('open');
});
const content = document.getElementById('cookie-content');
const kids = (content ? Array.prototype.map.call(content.children,
    (k) => [k.id || k.className, k.offsetHeight]) : []).sort((a, b) => b[1] - a[1]);
// The viewport as CSS sees it, read off a ``100vh`` probe: under an emulated device metric
// ``window.innerHeight`` keeps reporting the OS window (measured 1080 while the layout viewport
// was 768), and it is the layout viewport that every ``max-height: calc(100vh - …)`` in this
// panel is built from. Asserting the JS number would test the wrong instrument.
const probe = document.createElement('div');
probe.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;visibility:hidden';
document.body.appendChild(probe);
const viewport = [probe.offsetWidth, probe.offsetHeight];
probe.remove();
return {
    count: rows.length,
    rows,
    // What is actually tall inside the panel, tallest first: an overflow verdict that cannot say
    // which block costs the height sends someone to read 200 lines of CSS instead of fixing it.
    kids,
    viewport,
    // The viewport is part of the measurement, not background context: the panel's own
    // max-height is derived from ``window.innerHeight`` (app.js's resizable dialog), so a
    // "content overflows" verdict without the viewport it was measured in cannot be told apart
    // from a window that is simply not the one this test claims to be testing.
    inner: [window.innerWidth, window.innerHeight],
    outer: [window.outerWidth, window.outerHeight],
    maxH: getComputedStyle(box).maxHeight
};
"""


def test_the_cookie_panel_fits_a_laptop_window_without_a_vertical_scrollbar(app_url, driver):
    """The eight-platform step guide wrapped into a narrow column and pushed the panel
    past the window, so every platform showed a vertical scrollbar. The panel was
    widened (#175); the guide must now wrap into a height that fits WITHOUT the box
    having to scroll itself. Asserted per platform — this is the only tier that sees
    real text-wrap heights, and the assertion reports how many it measured.

    ``set_window_size``/``set_window_rect`` are not how this measures a laptop: the window
    manager answers neither (measured — the page reported a 1920×1080 viewport while the dialog
    still carried a 646 px ``max-height`` written when its own box was first opened at a
    different size, so the audit compared content against a viewport it did not have). The
    viewport is therefore *emulated*, which is the one thing a page cannot disagree with, and
    the check below fails loudly if the emulated size did not take effect.
    """
    driver.set_window_size(1366, 768)
    driver.execute_cdp_cmd(
        'Emulation.setDeviceMetricsOverride',
        {'width': 1366, 'height': 768, 'deviceScaleFactor': 1, 'mobile': False},
    )
    try:
        _quiet_canvas(driver, app_url)
        got = driver.execute_script(COOKIE_FIT_JS, [])
    finally:
        driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
    inner_w, inner_h = got['viewport'][0], got['viewport'][1]
    assert abs(inner_w - 1366) <= 2 and abs(inner_h - 768) <= 2, (
        f'this case audits a 1366×768 laptop window and CSS measured it as {got["viewport"]} '
        f'(cap {got["maxH"]}); the emulation did not take effect, so nothing measured below '
        'is a statement about a laptop'
    )
    assert got['count'] >= 8, f'expected the whole platform list to be measured, saw {got["count"]}'
    for row in got['rows']:
        assert row['scroll'] <= row['client'] + 1, (
            f'the {row["platform"]} cookie guide still overflows: scrollHeight {row["scroll"]} '
            f'vs clientHeight {row["client"]} (viewport {got["inner"]}, cap {got["maxH"]}, '
            f'tallest blocks {got["kids"][:4]})'
        )


def test_the_saved_login_dock_names_each_row_and_keeps_the_box(app_url, driver):
    """The 已保存的登录 dock, measured in the DOM where a person actually reads it.

    Two defects live here that **no scripted test can see**:

    * the platform select is one CustomSelect has enhanced — the native control sits in the DOM
      at 1px and opacity 0 while the words on screen are a span it paints. Starting the panel on
      ``weibo`` and reading only ``select.value`` would pass while the visible label stayed on
      yesterday's platform; this case reads the **label**, and starts somewhere else so a no-op
      cannot pass by accident;
    * every word and cell in the dock is built by JavaScript from catalogue keys, so a selector
      that no longer exists (the deleted 「打开」 button, the profile-state cells) is only caught
      by querying the real table.

    Pinned here: the dock renders one row per (platform, account) addressed by that login's key,
    the default row offers a rename that is visibly refused rather than absent, 「打开」 and the
    profile cells are gone, the dock shuts the other bottom panel, and the account box's
    candidates are a dropdown that exists only while the box is in use.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    seeded = driver.execute_script(
        """
        document.body.dataset.lang = 'zh';
        I18n.apply();
        const ROWS = [
            {platform: 'zhihu', account: 'default', label_key: 'cookies.accountDefault', label_args: {},
             entries: 12, session_only: 0, saved_at: '2026-09-28 10:00',
             profiles_on: true, profile_exists: true, profile_used: true, profile_imported: true,
             needs_refresh: false},
            {platform: 'zhihu', account: 'work', label_key: '', label_args: {},
             entries: 2, session_only: 1, saved_at: '2026-09-27 09:00',
             profiles_on: true, profile_exists: true, profile_used: true, profile_imported: true,
             needs_refresh: false}
        ];
        window.fetch = function (url) {
            let payload = {ok: true};
            if (String(url).indexOf('/api/cookies/status') === 0) {
                payload = {ok: true, cookies: {zhihu: true}, accounts: {zhihu: ['default', 'work']}, rows: ROWS};
            } else if (String(url).indexOf('/api/cookies/flow') === 0) {
                payload = {ok: true, flows: []};
            } else if (String(url).indexOf('/api/browser/profiles') === 0) {
                payload = {
                    ok: true, enabled: true, root: '/tmp',
                    template: {exists: false, pristine: true}, profiles: []
                };
            } else if (String(url).indexOf('/api/cookies/generate/status') === 0) {
                payload = {ok: true, active: false};
            }
            // ``fetchJSON`` reads the BODY AS TEXT and parses it (it must answer a non-JSON
            // reply without throwing), so a stub that only hands back ``json()`` is answered
            // with 「HTTP undefined」 — the shape this case needed to be written against.
            const body = JSON.stringify(payload);
            return Promise.resolve({
                json: () => Promise.resolve(payload),
                text: () => Promise.resolve(body),
                status: 200,
            });
        };
        const select = document.getElementById('cookie-platform');
        if (!select.closest('.cselect')) {
            return {error: 'the platform select is not enhanced, so no visible label exists to measure'};
        }
        // Start the panel somewhere else, then shut it: the click has to MOVE it.
        openCookieDialog('weibo');
        document.getElementById('cookie-dialog').classList.remove('open');
        document.getElementById('console-panel').classList.add('open');
        toggleCookiesPanel();
        return {
            dialogOpen: document.getElementById('cookie-dialog').classList.contains('open'),
            label: select.closest('.cselect').querySelector('.cselect-value').textContent,
            expected: I18n.t('platform.zhihu'),
            weiboWord: I18n.t('platform.weibo'),
        };
        """,
        [],
    )
    assert 'error' not in seeded, seeded
    assert seeded['dialogOpen'] is False, seeded
    assert seeded['label'] == seeded['weiboWord'], f'the panel did not start on weibo: {seeded}'

    deadline = time.monotonic() + 15
    rows = 0
    while time.monotonic() < deadline:
        rows = driver.execute_script("return document.querySelectorAll('#cookies-mgr-body .cookie-row').length;", [])
        if rows == 2:
            break
        time.sleep(0.2)
    assert rows == 2, f'the dock rendered {rows} saved logins, not the two the stub sent — nothing was clicked'

    report = driver.execute_script(
        """
        const cards = Array.prototype.slice.call(document.querySelectorAll('#cookies-mgr-body .cookie-row'));
        const byKey = (k) => cards.filter((c) => c.getAttribute('data-account') === k)[0] || null;
        const opsOf = (row) => Array.prototype.slice
            .call(row.querySelectorAll('.runs-mgr-ops button'))
            .map((b) => ({label: b.textContent, disabled: !!b.disabled, title: b.title || ''}));
        const defaultRow = byKey('default');
        const workRow = byKey('work');
        if (!defaultRow || !workRow) {
            const keys = cards.map((c) => c.getAttribute('data-account')).join(', ');
            return {error: `a row is not addressed by its own login key: ${keys}`};
        }
        return {
            measured: cards.length,
            // The dock shut the other bottom panel (one slot, 互斥).
            consoleOpen: document.getElementById('console-panel').classList.contains('open'),
            defaultAccount: defaultRow.querySelector('.cookie-cell-account').textContent,
            workAccount: workRow.querySelector('.cookie-cell-account').textContent,
            defaultOps: opsOf(defaultRow),
            workOps: opsOf(workRow),
            // 「打开」 is gone; the profile cells the user deleted must not have come back.
            openButtons: document.querySelectorAll('#cookies-mgr-body .cookie-row-actions').length,
            stateCells: document.querySelectorAll('#cookies-mgr-body .cookie-row-state').length,
            meta: Array.prototype.slice
                .call(document.querySelectorAll('#cookies-mgr-body .cookie-row-meta'))
                .map((m) => m.textContent),
            renameWord: I18n.t('cookies.renameOne'),
            deleteWord: I18n.t('cookies.deleteOne'),
            defaultAccountWord: I18n.t('cookies.accountDefault'),
        };
        """,
        [],
    )
    assert 'error' not in report, report
    assert report['measured'] == 2, report
    assert report['consoleOpen'] is False, f'two docked panels are open at once: {report}'
    # Each row names its own login; the default one is spoken as a word, a typed one verbatim.
    assert report['defaultAccount'] == report['defaultAccountWord'], report
    assert report['workAccount'] == 'work', report
    # Rename + delete, in that order, and the default row's rename is visibly refused (disabled
    # with a reason) rather than offered as a control that cannot do the thing (user: 「哪有同一个
    # 东西不同规范的」 — 默认账号 owns no directory to move).
    assert [o['label'] for o in report['workOps']] == [report['renameWord'], report['deleteWord']], report
    assert report['workOps'][0]['disabled'] is False, report
    assert [o['label'] for o in report['defaultOps']] == [report['renameWord'], report['deleteWord']], report
    assert report['defaultOps'][0]['disabled'] is True and report['defaultOps'][0]['title'], report['defaultOps']
    assert report['openButtons'] == 0, f'the 「打开」 button came back: {report}'
    assert report['stateCells'] == 0, f'a profile-state cell came back: {report}'
    assert not any(('profile' in m.lower() or '关窗口' in m or '失效' in m) for m in report['meta']), report

    popup = driver.execute_script(
        """
        // Land the panel on zhihu so the two zhihu logins are what the box offers, and type a
        // name into the box directly — the candidate dropdown is narrowed by TYPING, not by any
        // row action (the deleted 「打开」 used to be what left `work` here).
        openCookieDialog('zhihu');
        const input = document.getElementById('cookie-account');
        input.value = 'work';
        const openMenu = () => {
            const menus = Array.prototype.slice.call(document.body.children)
                .filter((el) => el.classList.contains('cand-menu'));
            return menus.filter((m) => m.classList.contains('open'))[0] || null;
        };
        const read = (m) => (m ? Array.prototype.slice.call(m.children).map((b) => b.textContent) : []);

        input.dispatchEvent(new FocusEvent('focus'));
        const narrowed = read(openMenu());

        // Empty box: every saved login of this platform is offered.
        input.value = '';
        input.dispatchEvent(new FocusEvent('focus'));
        const menu = openMenu();
        const offered = read(menu);
        const picked = menu && menu.children.length ? menu.children[menu.children.length - 1] : null;
        if (picked) picked.click();
        return {
            narrowed: narrowed,
            offered: offered,
            afterPick: input.value,
            stillOpen: !!document.querySelector('body > .cand-menu.open'),
            chips: document.querySelectorAll('.cookie-candidate').length,
        };
        """,
        [],
    )
    assert popup['chips'] == 0, f'the flat candidate row is back beside the dropdown: {popup}'
    assert popup['offered'] and len(popup['offered']) == 2, f'focusing an empty box did not offer both logins: {popup}'
    assert popup['narrowed'] == popup['offered'][-1:], f'typing did not narrow the offer: {popup}'
    assert popup['afterPick'] == 'work' and popup['stillOpen'] is False, popup


def test_switching_language_restamps_the_badge_and_the_saved_login_dock(app_url, driver):
    """#30, measured in the only engine that can see it: a language switch re-stamps the
    ``.node-state-badge`` and the JS-built 已保存的登录 dock — neither is reached by ``I18n.apply()``.

    Both surfaces are built entirely by JavaScript from catalogue keys (the badge word by
    ``applyDisabledVisuals``, the dock's platform/account/button words by ``renderCookieManager``),
    so ``I18n.apply()`` — which only walks ``[data-i18n]`` nodes — never touches them. A real
    ``setLang`` call has to drive the two extra repaints; the node harnesses cannot prove that
    wiring because each loads only one file (the canvas harness has no ``setLang``, the cookie
    harness has no canvas). Here the browser runs the whole app, so ``setLang`` is the shipped
    function and the words read back are the ones a person sees.

    The assertion compares the **rendered DOM text before and after**, not a freshly computed
    ``I18n.t`` — a stale badge that happened to hold the right key would pass a value-only
    check. Everything runs in ONE ``execute_script`` (seed, measure zh, ``setLang``, measure en)
    because the page's own async boot rebuilds the canvas between separate calls, which is why the
    sibling badge test keeps to a single script too. The dock is painted from a seeded
    ``cookieRows`` rather than a fetch, so nothing here races the disk; the "no second request"
    half of this rule is pinned in the node harness, which can count them exactly.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    measured = driver.execute_script(
        """
        const ROWS = [
            {platform: 'zhihu', account: 'default', label_key: 'cookies.accountDefault', label_args: {},
             entries: 12, session_only: 0, saved_at: '2026-09-28 10:00',
             profiles_on: true, profile_exists: true, profile_used: true, profile_imported: true,
             needs_refresh: false},
            {platform: 'zhihu', account: 'work', label_key: '', label_args: {},
             entries: 2, session_only: 1, saved_at: '2026-09-27 09:00',
             profiles_on: true, profile_exists: true, profile_used: true, profile_imported: true,
             needs_refresh: false},
        ];
        // The integration tier performs no server writes and the app's own boot fires fetches:
        // route every endpoint this path can reach (``setLang`` repaints the Cookie guide, which
        // reads /api/cookies/flow and /api/browser/profiles) so a missing array cannot throw and
        // take the whole script down — the same crash the node harness would have hit.
        window.fetch = function (url) {
            const path = String(url).split('?')[0];
            let payload = {ok: true};
            if (path.indexOf('/api/cookies/status') === 0) {
                payload = {ok: true, cookies: {zhihu: true}, accounts: {zhihu: ['default', 'work']}, rows: ROWS};
            } else if (path.indexOf('/api/cookies/flow') === 0) {
                payload = {ok: true, flows: []};
            } else if (path.indexOf('/api/browser/profiles') === 0) {
                payload = {ok: true, enabled: true, root: '/tmp', profiles: [], template: {exists: false}};
            }
            const text = JSON.stringify(payload);
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve(payload),
                text: () => Promise.resolve(text),
                status: 200,
            });
        };
        // A canvas the page owns, empty like a first visit (the shared profile's restore would
        // paint yesterday's nodes) — then two connected nodes, the head disabled through its own
        // power button so the head is 「已禁用」 and the child 「无有效输入」.
        document.body.dataset.lang = 'zh';
        I18n.apply();
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        canvas.disabledTypes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';
        const idA = canvas.addNode('source', 120, 120);
        const idB = canvas.addNode('process', 420, 120);
        canvas.connections.push({from: idA, to: idB});
        canvas.updateConnections();
        canvas._nodeEl(idA).querySelector('.node-power-btn').click();
        canvas.updateConnections();
        canvas.applyDisabledVisuals();
        // The dock is painted from a seeded cache (renderCookieManager reads the global
        // cookieRows — the very value cookiesManager.onLanguageChange repaints from), so this
        // script never races the app's boot tail or re-reads the disk. Everything below is
        // synchronous: the switch and both measurements happen in ONE script, because the page's
        // own async boot can rebuild the canvas between separate execute_script calls (which is how
        // the sibling badge test keeps to a single script too).
        window.cookieRows = ROWS;
        document.getElementById('cookies-panel').classList.add('open');
        renderCookieManager();

        const measure = () => {
            const elA = canvas._nodeEl(idA);
            const elB = canvas._nodeEl(idB);
            const workRow = document.querySelector('#cookies-mgr-body .cookie-row[data-account="work"]');
            const platformCell = document.querySelector('#cookies-mgr-body .cookie-row .cookie-cell-platform');
            const buttonWords = workRow
                ? Array.prototype.slice.call(workRow.querySelectorAll('.runs-mgr-ops button')).map((b) => b.textContent)
                : [];
            return {
                ok: !!elA && !!elB && !!workRow,
                badgesMeasured: document.querySelectorAll('.node-state-badge').length,
                shownBadges: Array.prototype.slice
                    .call(document.querySelectorAll('.node-state-badge'))
                    .filter((b) => getComputedStyle(b).display !== 'none' && b.textContent).length,
                disabledBadge: elA ? elA.querySelector('.node-state-badge').textContent : null,
                starvedBadge: elB ? elB.querySelector('.node-state-badge').textContent : null,
                dockPlatform: platformCell ? platformCell.textContent : null,
                dockButtons: buttonWords,
                expectDisabled: I18n.t('node.badgeDisabled'),
                expectStarved: I18n.t('node.badgeNoInput'),
                expectPlatform: I18n.t('platform.zhihu'),
                expectRename: I18n.t('cookies.renameOne'),
                expectDelete: I18n.t('cookies.deleteOne'),
            };
        };
        const zh = measure();
        setLang('en');
        const en = measure();
        return {zh, en};
        """,
        [],
    )
    zh, en = measured['zh'], measured['en']
    assert zh['ok'] and en['ok'], f'a node or the dock vanished before it could be measured: {zh} / {en}'
    # Browser-measured floor (AGENTS): report how much was actually on screen.
    assert zh['badgesMeasured'] >= 2 and zh['shownBadges'] >= 2, f'no badge was on screen to measure: {zh}'
    assert zh['disabledBadge'] == zh['expectDisabled'] and zh['starvedBadge'] == zh['expectStarved'], zh
    assert zh['dockPlatform'] == zh['expectPlatform'], zh

    # The badge is a JS word: after the switch it must READ English AND have CHANGED off the
    # Chinese string (a value-only check would pass on a stale badge that still held the key).
    assert en['disabledBadge'] == en['expectDisabled'], f'the 已禁用 badge did not re-stamp: {en}'
    assert en['disabledBadge'] != zh['disabledBadge'], 'the badge kept the old language word'
    assert en['starvedBadge'] == en['expectStarved'] and en['starvedBadge'] != zh['starvedBadge'], en
    # Same for the dock — its whole table is JS-built from keys.
    assert en['dockPlatform'] == en['expectPlatform'], f'the dock platform word kept the old language: {en}'
    assert en['dockPlatform'] != zh['dockPlatform'], en
    assert en['dockButtons'] == [en['expectRename'], en['expectDelete']], f'the row buttons kept the old language: {en}'
    assert en['dockButtons'] != zh['dockButtons'], en


REFRESH_ALIGN_DRAFT = """
const draft = {nodes: {
    'node-1': {id: 'node-1', type: 'source', x: 80, y: 60, title: '',
               params: {platform: 'douyin', keyword: '这个关键词特别长长长长长长长长长长长长长长', sort: '综合'}},
    'node-2': {id: 'node-2', type: 'output', x: 520, y: 60, title: '', params: {}},
}, connections: [{from: 'node-1', to: 'node-2'}], nextId: 3};
localStorage.setItem('crawler_canvas', JSON.stringify(draft));
"""

REFRESH_ALIGN_MEASURE_JS = """
const wires = Array.from(document.querySelectorAll('.conn-line:not(.temp)'))
    .map((p) => p.getAttribute('d') || '');
const ports = Array.from(document.querySelectorAll('.node-port')).map((p) => {
    const n = p.closest('.node');
    const isIn = p.classList.contains('node-port-in');
    return {id: n.id, isIn,
            x: isIn ? n.offsetLeft : n.offsetLeft + n.offsetWidth,
            y: n.offsetTop + n.offsetHeight / 2};
});
const boxes = Object.keys(canvas.nodes).map((id) => [id, canvas.nodes[id].el.offsetHeight]);
return {wires, ports, boxes, fonts: document.fonts.status};
"""


def _wait_for_id(driver, node_id, timeout=20.0):
    """Poll for an element by id without importing selenium into this module —
    the tier's driver fixture already speaks the whole browser API."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script('return !!document.getElementById(arguments[0]);', [node_id]):
            return
        time.sleep(0.2)
    pytest.fail(f'#{node_id} never appeared within {timeout}s')


def test_a_wire_ends_on_its_port_after_a_bare_refresh(app_url, driver):
    """The user's report, measured the only way it can be: a refresh boots the
    page in the fallback font and with a node <select> still an EXPANDED list;
    both resize every box AFTER the boot paint, and a wire's `d` holds literal
    numbers. Without a resize observer the ends sit on yesterday's box — the
    headless harness cannot see this because its stub never re-lays out.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _wait_for_id(driver, 'workspace')
    driver.execute_script(REFRESH_ALIGN_DRAFT, [])
    driver.refresh()
    _wait_for_id(driver, 'node-1')
    # Settle: the webfont's repaint and CustomSelect's collapse both land well
    # inside this window; the assertion is about the END state, not the race.
    time.sleep(3.0)
    got = driver.execute_script(REFRESH_ALIGN_MEASURE_JS, [])
    assert len(got['wires']) == 1, got
    assert len(got['boxes']) == 2, got
    for d in got['wires']:
        nums = [float(v) for v in d.replace(',', ' ').split() if re.fullmatch(r'-?[\d.]+', v)]
        end_y = nums[-1]
        end_x = nums[-2]
        # The wire's own ends: out-port of one box, in-port of the other.
        outs = [p for p in got['ports'] if not p['isIn']]
        ins = [p for p in got['ports'] if p['isIn']]
        starts = [p for p in (outs + ins) if abs(p['y'] - nums[1]) <= 2 and abs(p['x'] - nums[0]) <= 2]
        ends = [p for p in (outs + ins) if abs(p['y'] - end_y) <= 2 and abs(p['x'] - end_x) <= 2]
        assert starts, f'wire start {nums[:2]} on no port centre: {got["ports"]}'
        assert ends, f'wire end {[end_x, end_y]} on no port centre: {got["ports"]}'


def test_the_markup_a_node_is_built_from_carries_no_inline_handler(app_url, driver):
    """The id and the summary used to be spliced into onclick="…('<id>')", so an id
    with a quote escaped its string literal and ran as code — from a workflow JSON
    the user can hand-edit. The behaviour has to live in listeners."""
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(NODE_JS, [])
    assert 'onclick' not in made['markup'], made['markup'][:400]
    assert 'ondblclick' not in made['markup'], made['markup'][:400]


def test_the_delegated_node_buttons_still_act_on_their_own_node(app_url, driver):
    """The point of removing inline handlers: a click reached `deleteNode` through
    a closure over the id. Only a real browser fires that path."""
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(NODE_JS, [])
    edit, delete = driver.execute_script(
        """
        const el = document.getElementById(arguments[0]);
        const btns = el.querySelectorAll('.node-action-btn');
        btns[0].click();
        const opened = canvas._settingsNodeId;
        btns[1].click();
        return [opened, Object.keys(canvas.nodes)];
        """,
        [made['a']],
    )
    assert edit == made['a'], 'the edit button opened the settings for a different node'
    assert made['a'] not in delete, 'the delete button did not delete its own node'
    assert made['b'] in delete, 'deleting one node removed another'


def test_double_click_on_a_title_opens_the_rename_dialog(app_url, driver):
    _quiet_canvas(driver, app_url)
    made = driver.execute_script(NODE_JS, [])
    label = driver.execute_script(
        """
        let asked = null;
        const original = window.showDialog;
        window.showDialog = (spec) => { asked = spec.message; return Promise.resolve(null); };
        document.getElementById(arguments[0]).querySelector('.node-title')
            .dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        window.showDialog = original;
        return asked;
        """,
        [made['a']],
    )
    assert label and 'dialog.renameNode' not in str(label), f'dblclick did not ask to rename: {label!r}'


def test_a_stored_id_survives_a_reload_and_a_later_drag_cannot_collide(app_url, driver):
    """Node ids are storage keys (run rows, resume cursors, the fingerprint), so a
    reload must not renumber them — and a node dragged in afterwards must not be
    minted onto one that was adopted."""
    driver.get(app_url + '/')
    kept = driver.execute_script(
        """
        const draft = {nodes: {
            'n7': {id: 'n7', type: 'source', x: 10, y: 10, title: 'T', params: {platform: 'zhihu'}},
            'n3': {id: 'n3', type: 'output', x: 20, y: 20, title: 'U', params: {}},
        }, connections: [], nextId: 1};
        localStorage.setItem('crawler_canvas', JSON.stringify(draft));
        canvas.init();
        const later = canvas.addNode('process', 30, 30);
        return {ids: Object.keys(canvas.nodes), later, nextId: canvas.nextId};
        """,
        [],
    )
    assert {'n7', 'n3'} <= set(kept['ids']), kept
    assert kept['later'] not in ('n7', 'n3'), 'a new node was minted onto a restored id'
    assert kept['nextId'] > int(kept['later'].split('-')[-1]), 'nextId did not move past the adopted id'


def test_undo_and_redo_keep_the_ids_and_the_titles(app_url, driver):
    """A restored canvas renumbers and the resume banner stops matching the run
    that is still stored under the old ids."""
    driver.get(app_url + '/')
    result = driver.execute_script(
        """
        canvas.nodes = {}; canvas.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        canvas._history = []; canvas._historyIdx = -1;
        const a = canvas.addNode('source', 10, 10);
        canvas.nodes[a].title = '我的名字';
        canvas.saveState();
        canvas.deleteNode(a);
        const afterDelete = Object.keys(canvas.nodes).length;
        canvas.undo();
        const back = Object.keys(canvas.nodes);
        const title = back.length ? canvas.nodes[back[0]].title : null;
        const stamped = back.length ? document.getElementById(back[0]).querySelector('.node-title').textContent : null;
        canvas.redo();
        return {afterDelete, back, title, stamped, afterRedo: Object.keys(canvas.nodes).length, sameId: back[0] === a};
        """,
        [],
    )
    assert result['afterDelete'] == 0
    assert len(result['back']) == 1, 'undo did not bring the node back'
    assert result['sameId'] is True, 'undo re-minted the node id'
    assert result['title'] == '我的名字' and result['stamped'] == '我的名字', result
    assert result['afterRedo'] == 0


# ─── the console: the formatter, in the real DOM ───────────────────────


def test_console_lines_are_stamped_as_text_never_as_markup(app_url, driver):
    """A log line carries text scraped off other people's pages, and the console is
    built by string concatenation — `escapeHtml` is the only thing between that and
    script.

    This exercises the shipped formatter against the real DOM rather than driving
    `pollStatus`: the poller's only entry point is the one-second interval it
    installs, and its cursor rules are already asserted line by line against the
    untouched function by tests/frontend/harness_console.mjs. Duplicating the
    ticker here would add a two-second wait and no new guarantee.
    """
    driver.get(app_url + '/')
    outcome = driver.execute_script(
        """
        const quote = String.fromCharCode(39);
        const probe = '<img src=x onerror="window.__pwned=1">' + quote + 'q' + quote;
        const escaped = escapeHtml(probe);
        const el = document.getElementById('console-output');
        const original = el.innerHTML;
        el.innerHTML = '<div>' + escaped + '</div>';
        const imgs = el.querySelectorAll('img').length;
        const shown = el.textContent;
        el.innerHTML = original;
        return {escaped, imgs, shown};
        """,
        [],
    )
    assert '<img' not in outcome['escaped'], outcome
    assert outcome['imgs'] == 0, 'an escaped string still became an element'
    assert 'q' in outcome['shown'], outcome
    assert driver.execute_script('return window.__pwned === undefined;') is True


# ─── the settings panel that assembles the run request ──────────────────


def test_the_llm_panel_keeps_the_two_transports_apart(app_url, driver):
    """A local run used to inherit whatever OpenRouter id was left in the box, so
    the daemon refused it; the panels now have separate fields and separate rows."""
    driver.get(app_url + '/')
    outcome = driver.execute_script(
        """
        localStorage.removeItem('crawler_llm');
        LLMSettings.save({provider: 'openrouter', ollama: {model: 'local-tag'},
                          openrouter: {model: 'cat:free', api_key: 'sk-1'}});
        const ollamaPayload = (LLMSettings.save({provider: 'ollama'}), LLMSettings.payload());
        const routerPayload = (LLMSettings.save({provider: 'openrouter'}), LLMSettings.payload());
        document.getElementById('ai-menu').classList.add('open');
        LLMSettings.applyToPanel();
        return {
            ollamaPayload, routerPayload,
            modelField: document.getElementById('ai-model').value,
            ollamaField: document.getElementById('ai-ollama-model').value,
            keyField: document.getElementById('ai-key').value,
        };
        """,
        [],
    )
    assert outcome['ollamaPayload']['model'] == 'local-tag', outcome
    assert outcome['ollamaPayload']['api_key'] == '', 'a key travelled with a local run'
    assert outcome['routerPayload']['model'] == 'cat:free', outcome
    assert outcome['routerPayload']['api_key'] == 'sk-1', outcome
    assert outcome['modelField'] == 'cat:free' and outcome['ollamaField'] == 'local-tag', outcome


def test_language_switch_around_a_visible_run_state(app_url, driver):
    """Switching language mid-page is the one thing that re-renders every JS-built
    surface; a node named by the user must keep its name while the unnamed ones
    follow the language."""
    driver.get(app_url + '/')
    result = driver.execute_script(
        """
        canvas.nodes = {}; canvas.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        const named = canvas.addNode('source', 10, 10);
        /* The documented rename path writes the title to the node AND its element:
           updateNodeDisplay decides whether to re-stamp by reading the element, so
           a bare `nodes[x].title = …` is a state no user action produces. */
        canvas.nodes[named].title = '我自己起的';
        document.getElementById(named).querySelector('.node-title').textContent = '我自己起的';
        const plain = canvas.addNode('source', 300, 10);
        document.body.dataset.lang = 'zh';
        setLang('zh');
        return {
            named: canvas.nodes[named].title,
            namedShown: document.getElementById(named).querySelector('.node-title').textContent,
            plainShown: document.getElementById(plain).querySelector('.node-title').textContent,
            buttons: document.getElementById('btn-execute').textContent,
        };
        """,
        [],
    )
    assert result['named'] == '我自己起的' and result['namedShown'] == '我自己起的', result
    assert result['plainShown'] and 'node.' not in result['plainShown'], result
    assert result['buttons'] and 'toast.' not in result['buttons'] and 'btn.' not in result['buttons'], result


def test_the_palette_items_render_in_both_languages(app_url, driver):
    """The node library is the first thing a new user reads; a missing key there
    shows a raw `palette.source` on screen."""
    for lang in ('zh', 'en'):
        driver.get(app_url + '/')
        driver.execute_script(f"document.body.dataset.lang = '{lang}'; I18n.apply();")
        labels = driver.execute_script(
            "return Array.from(document.querySelectorAll('#node-palette *, .palette-item'))"
            ".map(e => (e.childElementCount ? '' : e.textContent.trim())).filter(t => t);",
            [],
        )
        assert labels, f'{lang}: the palette rendered no text at all'
        raw = [label for label in labels if '.' in label and label.split('.')[0] in ('palette', 'node', 'menu', 'btn')]
        assert not raw, f'{lang}: untranslated keys reached the screen: {raw}'


#: Long enough that no panel width this test could reasonably use renders it whole, so
#: the assertion below measures a heading that really is under stress. A 300-character
#: name is not paranoia: the panel is a floating window whose width follows the user's,
#: and anything shorter stops overflowing on a wide screen without saying so.
LONG_NAME = '热门榜与周排行榜的对照实验' * 25


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_run_detail_splits_its_workflows_without_growing_a_bar(app_url, driver, lang):
    """One record can hold several workflows; its expansion must say which node ran in
    which, and do it without breaking the page.

    This is the half of the grouping the Python tier cannot reach: the panel builds the
    markup it gets from ``/api/runs/<id>``, and whether a long 工作流命名 pushes the tally
    out of the heading — or the panel out of the window — is a fact about flex layout in a
    real browser. Nothing is written to the server: ``fetch`` is stubbed with a payload
    shaped exactly like the endpoint's, so what is measured is the row the product draws.
    """
    driver.set_window_size(1100, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const panel = document.getElementById('runs-panel');
        panel.classList.add('open');
        panel.classList.remove('hidden');
        runsManager.render([{{
            run_id: 'grp1', workflow_name: '热门榜 + 周排行榜', status: 'completed',
            resumable: false, node_done: 6, node_total: 6, rows_kept: 40,
            started_at: '2026-09-24 03:00', mode: 'serial', wf_count: 2, headless: 1
        }}]);
        window.fetch = () => Promise.resolve({{ json: () => Promise.resolve({{
            ok: true,
            run: {{
                run_id: 'grp1', status: 'completed', started_at: '2026-09-24 03:00', wf_count: 2,
                workflow_name: '热门榜 + 周排行榜',
                nodes: [
                    {{ node_id: 'name-1', node_type: 'name', status: 'done', row_count: 0,
                       component: 0, component_name: '{LONG_NAME}' }},
                    {{ node_id: 'up-1', node_type: 'upload', status: 'done', row_count: 4,
                       component: 0, component_name: '{LONG_NAME}' }},
                    {{ node_id: 'name-2', node_type: 'name', status: 'done', row_count: 0,
                       component: 1, component_name: '周排行榜' }},
                    {{ node_id: 'out-2', node_type: 'output', status: 'restored', row_count: 6,
                       component: 1, component_name: '周排行榜' }},
                ],
            }},
        }}) }});
        """,
        [],
    )
    driver.execute_script("return runsManager.detail('grp1', document.querySelector('#runs-panel tbody tr'));", [])
    facts = driver.execute_script(
        """
        const detail = document.getElementById('runs-mgr-detail-grp1');
        if (!detail) return {found: false};
        const names = Array.from(detail.querySelectorAll('.rm-group-name'));
        const tallies = Array.from(detail.querySelectorAll('.rm-group-tally'));
        const panel = document.getElementById('runs-panel');
        const width = (el) => Math.round(el.getBoundingClientRect().width);
        return {
            found: true,
            names: names.map((el) => el.textContent.trim()),
            // A name too long for the heading must be cut WITH the ellipsis saying so:
            // text that simply disappears is the failure mode this project has now been
            // bitten by twice, and the tally must not be the thing that gets pushed out.
            cut: names.map((el) => el.scrollWidth - el.clientWidth > 1),
            visible: names.map((el) => width(el) > 0),
            tallies: tallies.map((el) => el.textContent.trim()),
            tallyInside: tallies.map((el) => {
                const head = el.closest('.rm-group-head');
                return el.getBoundingClientRect().right <= head.getBoundingClientRect().right + 1;
            }),
            nodes: detail.querySelectorAll('.rm-node').length,
            panelBar: [panel.scrollWidth, panel.clientWidth],
            pageBar: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
            windowWidth: window.innerWidth,
            detailRight: Math.round(detail.getBoundingClientRect().right),
        };
        """,
        [],
    )

    def _short(names):
        return [name[:24] + ('…' if len(name) > 24 else '') for name in names]

    assert facts['found'] is True, 'the detail row never appeared, so nothing about the grouping was measured'
    assert facts['nodes'] == 4, f'every node must still be listed under its group: {_short(facts["names"])}'
    assert len(set(facts['names'])) == 2, f'both workflows must be named: {_short(facts["names"])}'
    assert '周排行榜' in facts['names'], f'a group lost its own name: {_short(facts["names"])}'
    assert all(facts['visible']), f'a group heading that renders nothing cannot be read: {facts["visible"]}'
    # The stress has to be real: a name that fits proves nothing about the flex rule, and
    # this file has already carried a layout test that passed by measuring an element that
    # never overflowed.
    assert any(facts['cut']), (
        f'the long name was never cut, so this case stopped stressing it: {_short(facts["names"])}'
    )
    # …and the tally has to stay inside the heading row beside it. This measures boxes,
    # not ink: two mutations (dropping min-width, and switching the name to
    # overflow: visible) left every number below unchanged, so what is pinned here is the
    # layout the panel controls — two named groups, each with its own tally, nothing
    # spilling out of the panel or the page — and not how the glyphs are painted.
    assert all(facts['tallyInside']), f'a tally was pushed past its heading row: {facts["tallyInside"]}'
    assert sum(1 for tally in facts['tallies'] if any(ch.isdigit() for ch in tally)) == 2, facts['tallies']
    assert facts['detailRight'] <= facts['windowWidth'] + 1, (
        f'the expansion runs off the window: {facts["detailRight"]} > {facts["windowWidth"]}'
    )
    assert facts['pageBar'][0] <= facts['pageBar'][1] + 1, f'the page grew a horizontal bar: {facts["pageBar"]}'
    assert facts['panelBar'][0] <= facts['panelBar'][1] + 1, f'the panel grew a horizontal bar: {facts["panelBar"]}'


# ─── #97: the bar, the tall panels, and an option longer than its menu ──────


@pytest.mark.parametrize('lang', ['zh', 'en'])
@pytest.mark.parametrize('width', [1366, 1024])
def test_the_menu_bar_never_hides_a_button_past_its_left_edge(app_url, driver, lang, width):
    """``#top-menu`` is one fixed row of twenty buttons. It used to be centred inside
    ``overflow: auto`` with its scrollbar hidden — and a scroller cannot scroll to a
    NEGATIVE overflow, so once the row was wider than the window BOTH ends were
    unreachable, not merely off-screen. Measured at 1366px in English: the row wanted
    1577px, the first button sat at x=53 only after the fix, and before it sat at -63.

    Asserted is the shape that makes an overflowing bar honest: anchored at the left,
    a scrollbar actually reserved when it overflows (``offsetHeight - clientHeight``
    is the ink-free proof that one exists), and no page-level bar either way.
    """
    driver.set_window_size(width, 700)
    driver.get(app_url + '/')
    _kill_animations(driver)
    facts = driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const bar = document.getElementById('top-menu');
        bar.classList.add('pinned');
        const buttons = Array.from(bar.querySelectorAll('.menu-btn'));
        const r = bar.getBoundingClientRect();
        const first = buttons.length ? buttons[0].getBoundingClientRect() : null;
        return {{
            measured: buttons.length,
            barLeft: Math.round(r.left),
            firstLeft: first ? Math.round(first.left) : null,
            scroll: [bar.scrollWidth, bar.clientWidth],
            reserved: bar.offsetHeight - bar.clientHeight,
            computedScrollbar: getComputedStyle(bar).scrollbarWidth,
            justify: getComputedStyle(bar).justifyContent,
            page: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
        }};
        """,
        [],
    )
    assert facts['measured'] >= 15, f'the bar drew {facts["measured"]} buttons, so this measured nothing'
    assert facts['firstLeft'] >= facts['barLeft'] - 1, (
        f'a button hangs off the left edge where no scrollbar can reach it: {facts}'
    )
    overflows = facts['scroll'][0] > facts['scroll'][1] + 1
    if overflows:
        assert facts['reserved'] >= 4, f'the row overflows with no visible scrollbar: {facts}'
        assert facts['computedScrollbar'] != 'none', f'the affordance is hidden again: {facts}'
    assert facts['page'][0] <= facts['page'][1] + 1, f'the page grew a horizontal bar: {facts["page"]}'
    if width == 1024:
        assert overflows, (
            f'at 1024px the row no longer overflows ({facts["scroll"]}), so the anchored-and-visible '
            'path this test exists for stopped being exercised — update or delete the test'
        )


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_tall_panel_scrolls_itself_instead_of_hanging_off_the_screen(app_url, driver, lang):
    """``#node-settings`` and ``#cookie-dialog`` are vertically centred with
    ``overflow-y: auto`` and had no height ceiling — so the box grew to its content,
    the box hung off the viewport (a long node form measured ``top: -177 / bottom: 727``
    in a 550px window), and the scroll that should have engaged never did: the first
    fields simply existed above the screen.

    A ceiling turns that into an internal scroll. Asserted per panel: the whole box
    is inside the viewport, it genuinely overflowed its own client height, and the
    document grew neither bar.
    """
    driver.set_window_size(1366, 700)
    driver.get(app_url + '/')
    _kill_animations(driver)
    facts = driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const out = {{}};
        for (const id of ['node-settings', 'cookie-dialog']) {{
            const box = document.getElementById(id);
            box.innerHTML = '';
            for (let i = 0; i < 24; i += 1) {{
                const row = document.createElement('div');
                row.className = 'settings-group';
                row.innerHTML = '<label>' + 'a'.repeat(46) + ' ' + i + '</label>';
                box.appendChild(row);
            }}
            box.classList.add('open');
            box.classList.remove('hidden');
            const rect = box.getBoundingClientRect();
            const cs = getComputedStyle(box);
            out[id] = {{
                rows: box.querySelectorAll('.settings-group').length,
                top: Math.round(rect.top),
                bottom: Math.round(rect.bottom),
                maxHeight: cs.maxHeight,
                overflowY: cs.overflowY,
                scrollHeight: box.scrollHeight,
                clientHeight: box.clientHeight,
                innerHeight: window.innerHeight,
                pageV: [document.documentElement.scrollHeight, document.documentElement.clientHeight],
                pageH: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
            }};
            box.classList.remove('open');
            box.innerHTML = '';
        }}
        return out;
        """,
        [],
    )
    for panel_id, box in facts.items():
        assert box['rows'] == 24, f'#{panel_id} kept {box["rows"]} injected rows, so nothing was measured'
        assert box['maxHeight'] != 'none', f'#{panel_id} has no height ceiling again'
        assert box['top'] >= -1, f'#{panel_id} starts above the screen ({box["top"]} of {box["innerHeight"]})'
        assert box['bottom'] <= box['innerHeight'] + 1, (
            f'#{panel_id} runs past the bottom of the viewport: {box["bottom"]} > {box["innerHeight"]}'
        )
        assert box['scrollHeight'] > box['clientHeight'], (
            f'#{panel_id} did not have to scroll, so this case stopped stressing it: {box}'
        )
        assert box['overflowY'] == 'auto', f'#{panel_id} lost its own scroll: {box["overflowY"]}'
        assert box['pageH'][0] <= box['pageH'][1] + 1, f'#{panel_id} grew a page-level horizontal bar'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_an_option_longer_than_its_menu_is_cut_visibly(app_url, driver, lang):
    """A dropdown row used to ellipsise only in multi-select mode. A single option
    longer than the capped menu — a crawled column name is exactly this shape — ran
    past its row inside a box whose ``overflow-y: auto`` computes ``overflow-x`` to
    ``auto``, so it was cut with no ellipsis, no scrollbar meaning and no tooltip.

    Both states are measured, and the stress is proven rather than assumed: the
    closed control must actually be overflowing its own box, the open row must be
    ellipsised and stay inside the menu, and the full text must survive somewhere
    the user can read it (``title``).
    """
    driver.set_window_size(1024, 700)
    driver.get(app_url + '/')
    _kill_animations(driver)
    facts = driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const LONG = '一个特别长的选项标签'.repeat(12);
        const host = document.getElementById('node-settings');
        host.innerHTML = '';
        host.classList.add('open');
        const select = document.createElement('select');
        const option = document.createElement('option');
        option.value = 'a';
        option.textContent = LONG;
        select.appendChild(option);
        select.appendChild(new Option('短', 'b'));
        host.appendChild(select);
        CustomSelect.scan(host);
        /* `.cselect` is the wrapper and `.cselect-trigger` is the button the control
           actually listens on — grabbing the wrapper measures a div that has no
           title and clicking it opens nothing. */
        const trigger = host.querySelector('.cselect-trigger');
        if (!trigger) return {{ enhanced: false }};
        const value = trigger.querySelector('.cselect-value');
        const out = {{
            enhanced: true,
            longLength: LONG.length,
            valueEllipsis: getComputedStyle(value).textOverflow,
            valueOverflow: value.scrollWidth - value.clientWidth,
            triggerTitle: trigger.title,
        }};
        /* The control opens on mousedown, not click (see custom-select.js: a click
           only fires when press and release land on the same moving element). A DOM
           .click() here would press nothing and the menu would stay unbuilt. */
        trigger.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, button: 0 }}));
        /* The popup is rendered into <body> and the page holds several of them (one
           per enhanced control), so the menu under test is found by whose select it
           remembers — a bare querySelector here would measure somebody else's. */
        const menu = Array.from(document.querySelectorAll('.cselect-menu')).find((m) => m._csSource === select);
        if (!menu) return Object.assign(out, {{ menuFound: false }});
        out.menuFound = true;
        const row = menu.querySelector('.cselect-option');
        if (!row) return Object.assign(out, {{ rowFound: false, buttons: menu.querySelectorAll('button').length }});
        out.rowFound = true;
        const label = row.querySelector('.cselect-option-label');
        const mr = menu.getBoundingClientRect();
        const lr = label.getBoundingClientRect();
        out.menuScroll = [menu.scrollWidth, menu.clientWidth];
        out.menuMaxWidth = getComputedStyle(menu).maxWidth;
        out.labelEllipsis = getComputedStyle(label).textOverflow;
        out.labelOverflow = label.scrollWidth - label.clientWidth;
        out.rowInsideMenu = lr.right <= mr.right + 1 && lr.left >= mr.left - 1;
        out.rowTitleIsFull = row.title === LONG;
        out.menuInsideWindow = mr.left >= -1 && mr.right <= window.innerWidth + 1;
        return out;
        """,
        [],
    )
    assert facts['enhanced'] is True, 'CustomSelect never built the control, so nothing was measured'
    assert facts['valueEllipsis'] == 'ellipsis', facts
    assert facts['valueOverflow'] > 1, f'the closed control is not actually cut, so this stopped stressing it: {facts}'
    assert facts['triggerTitle'] == '一个特别长的选项标签' * 12, f'the full text is mirrored nowhere: {facts}'
    assert facts['menuFound'] is True, 'clicking the control opened no menu'
    assert facts.get('rowFound') is True, f'the menu drew no option row, so nothing was measured: {facts}'
    assert facts['menuInsideWindow'] is True, f'the popup hangs off the window: {facts}'
    assert facts['labelEllipsis'] == 'ellipsis', f'a single option row is cut without an ellipsis: {facts}'
    assert facts['labelOverflow'] > 1, f'the open row is not actually cut, so this stopped stressing it: {facts}'
    assert facts['rowInsideMenu'] is True, f'the label escapes its row: {facts}'
    scroller = facts['menuScroll']
    assert scroller[0] <= scroller[1] + 1, f'the menu scrolls sideways instead of cutting: {facts}'
    assert facts['rowTitleIsFull'] is True, f'the cut option carries no tooltip: {facts}'


def test_the_camera_and_a_zero_coordinate_survive_a_real_reload(app_url, driver):
    """The one thing the node harness cannot prove: a viewpoint that lives in
    localStorage and must be read back by a REAL page boot.

    The user's bug was that 适应/自动排布 set the camera but a refresh opened the
    workflow at the default view, and a node whose saved x was exactly 0 got
    re-scattered by ``x || random``. Both only bite after a genuine reload — a fake
    DOM that runs boot and assert in one tick cannot see a re-read that never
    happened. So this writes the draft the product's own saveState writes, reloads
    the page for real, and reads the camera and the node position back off the
    re-booted canvas. Measured floor: 1 node and the three camera numbers.
    """
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
        """
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        // A node pinned at the origin — the exact case the old `x || random` scattered.
        canvas.addNode('source', 0, 0);
        // Pan and zoom the way a wheel/drag gesture leaves the fields.
        canvas.panX = -320;
        canvas.panY = -60;
        canvas.zoom = 0.8;
        canvas.saveState();
        """,
        [],
    )
    # The draft really captured the camera BEFORE the reload, or the next assertion
    # below would only prove the reload returned a value that was never written.
    drafted = driver.execute_script(
        "return (JSON.parse(localStorage.getItem('crawler_canvas') || 'null') || {}).view || null;",
        [],
    )
    assert drafted == {'panX': -320, 'panY': -60, 'zoom': 0.8}, f'the draft never captured the camera: {drafted}'
    driver.refresh()
    _kill_animations(driver)
    facts = driver.execute_script(
        """
        const ids = Object.keys(canvas.nodes);
        const el = ids.length ? canvas._nodeEl(ids[0]) : null;
        return {
            nodeCount: ids.length,
            panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom,
            left: el ? el.style.left : null,
            top: el ? el.style.top : null,
            transform: getComputedStyle(document.getElementById('canvas-inner')).transform,
        };
        """,
        [],
    )
    assert facts['nodeCount'] == 1, f'the reload did not rebuild the one node: {facts}'
    # The camera came back — not the init default of (0,0,1).
    assert facts['zoom'] == 0.8, f'the zoom reset on reload: {facts}'
    assert facts['panX'] == -320 and facts['panY'] == -60, f'the pan reset on reload: {facts}'
    # …and it is actually painted, not just a JS field that nothing read.
    assert 'matrix' in facts['transform'].lower() or 'translate' in facts['transform'].lower(), (
        f'the restored camera never reached the canvas transform: {facts["transform"]}'
    )
    # The node at the origin stayed at the origin instead of scattering to random ~100-300.
    assert facts['left'] == '0px' and facts['top'] == '0px', f'a 0-coordinate node moved on load: {facts}'
