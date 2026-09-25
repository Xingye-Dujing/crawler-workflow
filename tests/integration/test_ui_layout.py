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
def app_url():
    """Boot the real server on a private port; tear it down after the module.

    A second instance against the same ``data/`` would promote the first one's live
    run to interrupted, so this fixture is only ever used with the user's own server
    stopped — which is also why nothing here writes.
    """
    import urllib.error
    import urllib.request

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    env = {**os.environ, 'PORT': str(port)}
    (REPO / 'logs').mkdir(exist_ok=True)
    log_path = REPO / 'logs' / '_ui_layout_server.log'
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
def test_a_workflow_row_survives_being_built_from_its_own_name(app_url, driver, lang):
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
