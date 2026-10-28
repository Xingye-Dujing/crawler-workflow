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
from device_policy import REQUIRE_BROWSER_ENV, unavailable

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]

REPO = Path(__file__).resolve().parents[2]
VIEWPORTS = [(1920, 1080), (1366, 768), (1024, 700)]


@pytest.fixture(scope='module')
def app_url(tmp_path_factory):
    """Boot the real server on a private port, in a state root of its own.

    ``CRAWLER_DATA_ROOT`` (see ``backend/core/config.py``) is what makes that possible: without it, this
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
    from crawlers.platforms.wechat.crawler import WechatCrawler

    try:
        crawler = WechatCrawler(headless=True)
    except Exception as e:
        unavailable(f'Chrome/chromedriver unavailable: {e}', REQUIRE_BROWSER_ENV)
    try:
        yield crawler.driver
    finally:
        crawler.close()


def _load_app(driver, app_url):
    """Open the page and refuse to drive bindings it never installed.

    A bare ``driver.get`` is not enough evidence that the canvas is there: the crawl
    driver runs ``page_load_strategy='eager'``, which returns at DOM parse time, and one
    CI run then ran a script against a document whose ``canvas.js`` had not executed —
    every later line failed with ``canvas is not defined`` while ``I18n`` (a LATER
    script) was fine, so the log named a symptom and no cause. Wait for the three
    bindings every test drives, and on timeout fail with the page's own evidence
    (which scripts the document lists, which ones transferred bytes) rather than a
    bare JavaScript exception.
    """
    driver.get(app_url + '/')
    deadline = time.monotonic() + 15
    while True:
        state = driver.execute_script(
            'return { ready: document.readyState, canvas: typeof canvas, i18n: typeof I18n };'
        )
        if state['ready'] == 'complete' and state['canvas'] == 'object' and state['i18n'] == 'object':
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    evidence = driver.execute_script(
        """
        return {
            scripts: Array.from(document.scripts).map((s) => s.src || 'inline'),
            fetched: performance.getEntriesByType('resource')
                .filter((e) => e.initiatorType === 'script')
                .map((e) => `${e.name} transfer=${e.transferSize} duration=${Math.round(e.duration)}`),
        };
        """
    )
    pytest.fail(f'the page never finished booting: {state}; {evidence}')


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


def _read_url_json(url: str):
    """Fetch a URL from the tier's own private server and parse it, or ``None``.

    Used where the fact under test is the SERVER's answer (a static asset's route), which is not
    something a stubbed ``window.fetch`` can prove.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _settle_console_replay(driver):
    """Wait out the page's OWN console replay before a test empties the box.

    The boot sequence asks ``/api/workflow/status?tail=`` for the lines a reload lost, and
    that read is still in flight when the next script runs. A test that clears
    ``#console-output`` and then reads it back therefore gets the SERVER's history painted
    over the lines it fed itself — on the CI runner, where a previous test had left a long
    run log behind, the assertion printed several hundred retention lines instead of the
    three it had stubbed. ``workflow.reconnectConsole`` keeps the in-flight promise exactly
    so a caller can wait for a replay it did not start; this is that caller.

    Returns whether a replay was actually waited for, so a caller can say what it measured.
    """
    return bool(
        driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];
            if (!workflow._reconnect) { done(false); return; }
            // A replay that fails still finishes writing the box; both endings are settled.
            workflow._reconnect.then(() => done(true), () => done(true));
            """,
            [],
        )
    )


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
    'outline-panel',
    'clipboard-drawer',
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
    'help-overlay',
    'source-help-overlay',
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
    # The outline is a static header row (title + toggle) over a JS-rendered list; with an
    # empty canvas it still shows the header, the two chrome parts and the list box, so 3
    # is a safe floor. Node rows only ever add to the count, never reduce it.
    'outline-panel': 3,
    # Opened with an empty board the drawer shows header chrome (title + Add/Clear/Close),
    # the list box and the empty message — a floor of 4 leaves slack for a button's chrome
    # to be counted separately in one language. Copied rows only ever add to the count.
    'clipboard-drawer': 4,
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
    # The cheat sheet paints a header (title + close) over one row per shortcut, each row
    # a key span + a label span — 11 rows. 20 is a floor well under the ~39 real elements,
    # so it only fails if the overlay lost its content, never if it grows.
    'help-overlay': 20,
    # The guide's own floor is low on purpose: this generic pass forces `.open` without stubbing
    # the request, so the shell (title, close, body, waiting line) is all that is guaranteed.
    # The content is measured by name in test_the_export_guide_lists_a_link_the_user_can_copy.
    'source-help-overlay': 4,
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
def test_loading_a_run_paints_node_verdicts_and_marks_the_record(driver, app_url, lang):
    """The loaded-run UI, measured where a user meets it.

    The node harness can prove the map/serialization; only a real engine can prove
    the badges are visible circles with distinct colours, that two parallel nodes
    both spin, that the panel's new tab bar and load action fit, and that loading an
    older record really repaints the nodes. ``fetch`` is stubbed throughout — this
    tier performs no server writes and starts no run.
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    facts = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {}; canvas.connections = []; canvas.selectedNodes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';
        const a = canvas.addNode('upload', 80, 60);
        const b = canvas.addNode('process', 360, 60);
        canvas.connections = [{ from: a, to: b }];
        canvas.scheduleRender();
        const RUNS = [
            { run_id: 'r-new', workflow_name: '测试画布', status: 'completed',
              started_at: '2026-10-24T10:00:00', node_done: 1, node_total: 2, rows_kept: 3,
              wf_count: 1, mode: 'serial', headless: 1,
              nodes: [
                  { node_id: a, status: 'failed', row_count: 0 },
                  { node_id: b, status: 'done', row_count: 3 },
              ] },
            { run_id: 'r-old', workflow_name: '测试画布', status: 'completed',
              started_at: '2026-10-23T10:00:00', node_done: 2, node_total: 2, rows_kept: 7,
              wf_count: 1, mode: 'serial', headless: 1,
              nodes: [
                  { node_id: a, status: 'done', row_count: 5 },
                  { node_id: b, status: 'restored', row_count: 2 },
              ] },
        ];
        window.fetch = function (url) {
            if (String(url).indexOf('/api/runs/for-workflow') >= 0) {
                return Promise.resolve({ json: () => Promise.resolve({
                    ok: true, runs: RUNS, latest_run_id: 'r-new',
                    workflow_fingerprint: 'fp-test', queue: [],
                }) });
            }
            return Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
        };
        const panel = document.getElementById('runs-panel');
        panel.classList.add('open');
        panel.style.height = '320px';
        runsManager._tab = 'workflow';
        runsManager._detail = null;
        runResults.refresh().then(() => runsManager.refresh()).then(() => {
            const badgeOf = (id) => canvas._nodeEl(id).querySelector('.node-run-badge');
            const describe = (id) => {
                const badge = badgeOf(id);
                const cs = getComputedStyle(badge);
                const rect = badge.getBoundingClientRect();
                return {
                    cls: badge.className,
                    display: cs.display,
                    bg: cs.backgroundColor,
                    title: badge.title,
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    clipped: rect.right > document.querySelector('#nodes-container').getBoundingClientRect().right + 1,
                };
            };
            const rows = Array.from(document.querySelectorAll('#runs-panel tbody tr'));
            const of = (rid) => rows.filter((r) => (r.getAttribute('data-run-id') || '') === rid)[0];
            const table = document.querySelector('#runs-panel table');
            const tabs = document.getElementById('runs-tabs');
            done({
                a, b,
                badges: [describe(a), describe(b)],
                runId: runResults.runId,
                tabs: tabs ? tabs.textContent : '',
                tabCount: tabs ? tabs.querySelectorAll('.runs-tab').length : 0,
                loadedChipOnNew: !!(of('r-new') && of('r-new').querySelector('.runs-mgr-tag.loaded')),
                oldHasLoadButton: !!(of('r-old') && Array.from(of('r-old').querySelectorAll('.runs-mgr-btn'))
                    .some((btn) => String(btn.getAttribute('onclick') || '').indexOf('loadRun') >= 0)),
                tableOverflow: table ? table.scrollWidth - table.clientWidth : null,
                tabsOverflow: tabs ? tabs.scrollWidth - tabs.clientWidth : null,
                pageBar: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
            });
        }).catch((e) => done({ error: String(e) }));
        """,
        [lang],
    )
    assert not facts.get('error'), facts
    assert facts['runId'] == 'r-new', f'the latest run was not the default: {facts}'
    # Green check and red X are different shapes AND different colours on screen.
    assert facts['badges'][0]['cls'].endswith('run-failed'), facts['badges']
    assert facts['badges'][1]['cls'].endswith('run-done'), facts['badges']
    assert facts['badges'][0]['bg'] != facts['badges'][1]['bg'], facts['badges']
    assert all(b['display'] == 'flex' and b['width'] >= 12 and b['height'] >= 12 for b in facts['badges']), facts[
        'badges'
    ]
    assert all(b['clipped'] is False for b in facts['badges']), f'a badge hangs off the canvas box: {facts["badges"]}'
    assert facts['tabCount'] == 2, f'the two views did not render: {facts["tabs"]!r}'
    assert facts['loadedChipOnNew'] is True, 'the loaded record was not marked'
    assert facts['oldHasLoadButton'] is True, 'the older record offered no way to load it'
    assert facts['tableOverflow'] <= 1 and facts['tabsOverflow'] <= 1, facts
    assert facts['pageBar'][0] <= facts['pageBar'][1] + 1, f'the new buttons grew a page-level bar: {facts["pageBar"]}'

    # Parallel: several nodes can be spinning at once, with a real animation.
    spinning = driver.execute_script(
        """
        const [a, b] = arguments;
        canvas.applyRunStatuses({
            [a]: { status: 'running', row_count: 0 },
            [b]: { status: 'running', row_count: 0 },
        });
        const items = [a, b].map((id) => {
            const badge = canvas._nodeEl(id).querySelector('.node-run-badge');
            const spinner = badge.querySelector('.node-run-spinner');
            return {
                badgeCls: badge.className,
                display: getComputedStyle(badge).display,
                bg: getComputedStyle(badge).backgroundColor,
                spinner: !!spinner,
            };
        });
        /* This fixture installs `animation: none !important` so rects are measured after
           transitions; the keyframes themselves are still in the shipped stylesheet. */
        const keyframes = Array.from(document.styleSheets).some((sheet) => {
            try {
                return Array.from(sheet.cssRules).some(
                    (rule) => rule.type === CSSRule.KEYFRAMES_RULE && rule.name === 'node-run-spin'
                );
            } catch (e) {
                return false;
            }
        });
        return { items, keyframes };
        """,
        facts['a'],
        facts['b'],
    )
    assert all(item['badgeCls'].endswith('run-running') for item in spinning['items']), spinning
    assert all(item['display'] == 'flex' and item['spinner'] for item in spinning['items']), spinning
    assert spinning['keyframes'] is True, 'the loading spinner has no animation rule in the shipped CSS'
    assert all(item['bg'].startswith('rgb(224, 168, 0') for item in spinning['items']), (
        f'a running node is not yellow: {spinning}'
    )

    loaded = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        runsManager.loadRun('r-old').then(() => {
            const badgeOf = (id) => canvas._nodeEl(id).querySelector('.node-run-badge');
            const row = Array.from(document.querySelectorAll('#runs-panel tbody tr'))
                .filter((r) => (r.getAttribute('data-run-id') || '') === 'r-old')[0];
            const toast = document.getElementById('toast');
            done({
                runId: runResults.runId,
                isLoaded: runResults.isLoaded('r-old'),
                oldChip: !!(row && row.querySelector('.runs-mgr-tag.loaded')),
                newChip: !!Array.from(document.querySelectorAll('#runs-panel tbody tr'))
                    .filter((r) => (r.getAttribute('data-run-id') || '') === 'r-new')[0]
                    .querySelector('.runs-mgr-tag.loaded'),
                badges: [badgeOf(arguments[0]), badgeOf(arguments[1])].map((b) => b.className),
                toast: toast ? toast.textContent : '',
            });
        }).catch((e) => done({ error: String(e) }));
        """,
        facts['a'],
        facts['b'],
    )
    assert not loaded.get('error'), loaded
    assert loaded['runId'] == 'r-old' and loaded['isLoaded'] is True, loaded
    assert loaded['oldChip'] is True and loaded['newChip'] is False, 'the marker did not move with the selection'
    assert all(cls.endswith(('run-done', 'run-running')) for cls in loaded['badges']), loaded
    assert loaded['badges'][0].endswith('run-done') and loaded['badges'][1].endswith('run-done'), loaded
    assert loaded['toast'], 'loading a run said nothing'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_help_overlay_opens_over_the_page_without_breaking_layout(driver, app_url, lang):
    """The cheat sheet is a fixed full-viewport backdrop; if its sheet or a row overflowed
    (long English labels) it would grow a horizontal bar over the whole page. Opened in a
    real engine, in both languages, it must stay inside its own box."""
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    opened = driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        toggleShortcutsHelp();
        const el = document.getElementById('help-overlay');
        return el.classList.contains('open');
        """
    )
    assert opened, 'toggleShortcutsHelp() did not open the overlay'
    result = driver.execute_script(_audit_js('help-overlay'), [])
    _assert_contains_itself(result, f'#help-overlay in {lang}', may_be_wider_than_viewport=True, min_measured=20)


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_align_is_one_undo_step_and_a_cycle_is_refused_in_a_real_browser(driver, app_url, lang):
    """Both claims are pure-JS behaviour the node harness cannot measure: an alignment that
    pushes one history entry (not one per node), and a wire that would close a loop being
    rejected at the single commit seam WITHOUT painting a path. Driven with `process` nodes
    only — a `source` node would fire a capability fetch against the live server."""
    _load_app(driver, app_url)
    facts = driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {}; canvas.connections = []; canvas.selectedNodes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';

        const a = canvas.addNode('process', 300, 40);
        const b = canvas.addNode('process', 0, 120);
        const c = canvas.addNode('process', 150, 240);
        canvas.setSelectedNodes([a, b, c]);
        const histBefore = canvas._history.length;
        const aligned = canvas.alignSelected('left');
        const xs = [a, b, c].map((id) => parseInt(canvas._nodeEl(id).style.left, 10));
        const historySteps = canvas._history.length - histBefore;

        const p = canvas.addNode('process', 0, 500);
        const q = canvas.addNode('process', 0, 600);
        const r = canvas.addNode('process', 0, 700);
        canvas.connectNodes(p, q); canvas.connectNodes(q, r);
        canvas.updateConnections();
        // Two legitimate wires are now painted; measure AFTER the repaint (a wire only
        // materialises on updateConnections).
        const wiresBefore = document.querySelectorAll('#svg-layer .conn-line:not(.temp)').length;
        const loop = canvas.connectNodes(r, p);
        canvas.updateConnections();
        const wiresAfter = document.querySelectorAll('#svg-layer .conn-line:not(.temp)').length;

        return {
            aligned, xs, historySteps,
            cycleOk: loop.ok, edges: canvas.connections.length,
            wiresBefore, wiresAfter,
        };
        """,
        lang,
    )
    assert facts['aligned'] is True
    assert facts['xs'] == [0, 0, 0], f'align left must collapse every box to the smallest x: {facts}'
    assert facts['historySteps'] == 1, f'one alignment must be exactly one undo step, was {facts["historySteps"]}'
    assert facts['cycleOk'] is False, 'a wire that closes a loop must be refused'
    assert facts['edges'] == 2, 'the refused edge wrote nothing to the model'
    # The two real wires paint (2), and the refused loop adds a THIRD path: it must not.
    assert facts['wiresBefore'] == 2 and facts['wiresAfter'] == 2, (
        f'a refused wire must not paint a path: before={facts["wiresBefore"]} after={facts["wiresAfter"]}'
    )


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_opening_the_settings_panel_lands_focus_in_and_closing_returns_it(driver, app_url, lang):
    """The panel's keyboard path, only provable in a real engine (the node stub has no
    activeElement): freshly opening a node's settings must move focus INTO the form (a keyboard
    user who reached a node lands in its fields, not behind the canvas), and closing must hand
    focus back to whatever opened it — not dump the user at the top of the page."""
    _load_app(driver, app_url)
    facts = driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        const id = canvas.addNode('process', 200, 200);
        const opener = canvas._nodeEl(id).querySelector('.node-action-btn');
        opener.focus();
        const focusedOpener = document.activeElement === opener;
        openSettings(id);
        const inPanel = !!(document.activeElement && document.activeElement.closest('#settings-content'));
        closeSettings();
        const returned = document.activeElement === opener;
        return { focusedOpener, inPanel, returned };
        """,
        lang,
    )
    assert facts['focusedOpener'], 'test precondition: the opener button was not focusable'
    assert facts['inPanel'], 'opening the panel did not move focus into the form'
    assert facts['returned'], 'closing the panel did not return focus to the opener'


#: Columns of a dual-map table: every one of them is an ASCII name on disk, which is the half
#: that used to print as an identifier in a Chinese table. ``cluster_id`` is deliberately NOT in
#: the catalogue — it is the control that proves an unknown column is shown as itself.
_BIBLIO_COLUMNS = ['map', 'source', 'target', 'weight', 'x', 'label', 'cluster_id']


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_bibliometrics_panel_names_its_columns_and_keeps_the_caret(app_url, driver, lang):
    """The workspace dock, measured in a real engine.

    Three facts the node harness cannot reach. ``biblio.col.<column>`` is a COMPUTED key, so
    whether a header reads as a word or as an identifier is only visible once the page has a
    catalogue loaded. The panel's own fields are built as bare ``<input>``/``<select>`` markup
    with no ``.settings-input`` class, so a theme that is not honoured is a white box with black
    text on a dark panel — and a native ``<select>`` is OS-drawn until CustomSelect scans it. And
    every keystroke repaints the whole body: the caret's element is destroyed, so the second
    character needs a second click unless focus is handed back (measured lost 2026-10-24).

    Nothing is written: the panel is painted from a stubbed ``/api/biblio/*`` answer.
    """
    driver.set_window_size(1650, 1080)
    _load_app(driver, app_url)
    _kill_animations(driver)
    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        document.documentElement.dataset.themeChoice = 'dark';
        applyTheme();
        I18n.apply();
        window.__asked = [];
        const rows = [{ map: 'journal', source: '中国人口·资源与环境', target: '', weight: 14,
                        x: 150, label: '中国人口·资源与环境', cluster_id: 'c-1' }];
        const payload = (u) => {
            if (u.indexOf('/api/biblio/runs') >= 0) {
                return { ok: true, runs: [{ run_id: 'r-1', workflow_name: '布局测量', started_at: '2026-10-24 01:00',
                         status: 'completed', nodes: [{ node_id: 'n-dual', title: '双图叠加', status: 'done',
                         row_count: 1, component_name: '', files: [] }] }] };
            }
            if (u.indexOf('/api/biblio/table') >= 0) {
                return { ok: true, run_id: 'r-1', node_id: 'n-dual', title: '双图叠加', status: 'done',
                         shape: 'dual_map', columns: arguments[1], rows: rows,
                         total: 1, offset: 0, limit: 200, files: [] };
            }
            if (u.indexOf('/api/biblio/projects') >= 0) return { ok: true, projects: [] };
            return { ok: true };
        };
        window.fetch = (url) => {
            const u = String(url);
            window.__asked.push(u);
            const body = JSON.stringify(payload(u));
            return Promise.resolve({
                text: () => Promise.resolve(body),
                json: () => Promise.resolve(body),
                status: 200,
            });
        };
        toggleBiblioPanel();
        """,
        lang,
        _BIBLIO_COLUMNS,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if not driver.execute_script("return !document.querySelector('#biblio-mgr-body table')"):
            break
        time.sleep(0.2)
    # The W3C locator string: this tier drives the page through `execute_script` and imports no
    # `By`, so a real keystroke is sent without adding a Selenium import to the module.
    facts = driver.execute_script(
        """
        const body = document.getElementById('biblio-mgr-body');
        const probe = document.createElement('span');
        probe.style.color = 'var(--text)';
        document.body.appendChild(probe);
        const ink = getComputedStyle(probe).color;
        probe.remove();
        const search = body.querySelector('input[type="search"]');
        const cs = search ? getComputedStyle(search) : null;
        const box = document.createElement('span');
        box.style.background = 'transparent';
        return {
            theme: document.documentElement.dataset.theme,
            ink: ink,
            asked: window.__asked,
            headers: Array.from(body.querySelectorAll('table thead th')).map(
                (th) => [th.textContent, th.getAttribute('title')]),
            rawKey: body.textContent.indexOf('biblio.col.') >= 0,
            searchColor: cs ? cs.color : null,
            searchBg: cs ? cs.backgroundColor : null,
            uaWhite: cs ? (cs.backgroundColor === 'rgb(255, 255, 255)') : null,
            cselects: body.querySelectorAll('.cselect').length,
            selects: body.querySelectorAll('select').length,
            rows: body.querySelectorAll('table tbody tr').length,
        };
        """,
        [],
    )
    assert facts['theme'] == 'dark', f'the theme did not land: {facts["theme"]}'
    assert facts['rawKey'] is False, 'a header printed its catalogue key instead of a word'
    words = {
        column: driver.execute_script("return I18n.t('biblio.col.' + arguments[0]);", column)
        for column in _BIBLIO_COLUMNS
    }
    painted = dict((title, text) for text, title in facts['headers'])
    for column in _BIBLIO_COLUMNS[:-1]:
        assert words[column] != f'biblio.col.{column}', f'{column} has no word in {lang}'
        shown = painted.get(column)
        assert shown == words[column], f'{column} header reads {shown!r}, not the catalogue word {words[column]!r}'
    # An unknown column is the stored name itself — never a key, never a guessed word.
    assert painted.get('cluster_id') == 'cluster_id', facts['headers']
    assert facts['searchColor'] == facts['ink'], (
        f'the field text is {facts["searchColor"]}, the theme ink is {facts["ink"]}'
    )
    assert facts['uaWhite'] is False, 'the search box is still UA-painted white'
    assert facts['searchBg'] == 'rgba(0, 0, 0, 0)', facts['searchBg']
    assert facts['selects'] == 3, facts
    assert facts['cselects'] == 3, f'the pickers were never upgraded: {facts["cselects"]} of {facts["selects"]}'
    assert len(facts['headers']) == len(_BIBLIO_COLUMNS), facts['headers']
    assert facts['rows'] == 1, facts['rows']

    # Now type a term that MATCHES a row: the panel repaints its whole body on every keystroke,
    # and the element under the caret is destroyed by that repaint.
    driver.find_element('css selector', '#biblio-mgr-body input[type="search"]').send_keys('资源')
    typed = driver.execute_script(
        """
        const body = document.getElementById('biblio-mgr-body');
        const search = body.querySelector('input[type="search"]');
        return {
            value: search ? search.value : null,
            focused: document.activeElement === search,
            caret: search && search.selectionStart !== null ? search.selectionStart : null,
            rows: body.querySelectorAll('table tbody tr').length,
        };
        """,
        [],
    )
    assert typed['value'] == '资源', f'the typed text did not survive the repaint: {typed["value"]!r}'
    assert typed['focused'] is True, 'typing in the panel still drops the caret'
    assert typed['caret'] == 2, f'the caret was not put back where the user left it: {typed["caret"]}'
    assert typed['rows'] == 1, f'the filter dropped the row it matches: {typed["rows"]}'


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
    _load_app(driver, app_url)
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


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_hostile_workflow_name_stays_text_and_inside_its_attribute(app_url, driver, lang):
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
    _kill_animations(driver)
    # The page's own replay must have landed before the box is emptied, or the server's
    # history arrives after the clear and is read back as if this test had fed it.
    waited = _settle_console_replay(driver)
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
        /* A page that boots now reads the console back from the server (a refresh used to
           lose it), and this test server has startup lines of its own. This case is about
           what a TAB SWITCH does to lines the poller already showed, so it starts from an
           empty page rather than inheriting another run's log. */
        document.getElementById('console-output').innerHTML = '';
        consoleViews.all = { seen: 0, lines: [] };
        consoleViews.wf = {};
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
    assert seen['before'] == ['第一行', '第二行', '第三行'], f'{seen["before"]} (waited for the boot replay: {waited})'
    assert seen['tabA'] == ['甲的第一行', '甲的第二行'], f'the 甲 tab opened blank: {seen}'
    assert seen['tabB'] == ['乙的第一行'], f'the 乙 tab did not show only its own lines: {seen}'
    assert seen['backToAll'] == seen['before'], f'coming back to 全部 lost or duplicated lines: {seen}'


def test_a_page_that_reloaded_takes_the_console_back_up_in_a_real_browser(app_url, driver):
    """The console is a real docked panel, and the reconnect writes into it: opens
    ``#console-panel``, builds the parallel tab bar and paints ``.console-line`` rows.

    The node harness proves the cursor arithmetic; this tier is the only one that can see
    the panel actually opening, the tabs actually rendering, and the class names the CSS
    matches. ``fetch`` is stubbed — this tier performs no server writes, and no run is
    started — and the answer is the shape ``/api/workflow/status?tail=`` really ships: a
    tail plus the total that was ever produced.
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    # The boot replay shares one in-flight promise with this test's own call, so a replay
    # the page started for itself has to be over before asking for another: otherwise the
    # await below is handed the SERVER's history and the stubbed tail is never read.
    _settle_console_replay(driver)
    driver.execute_script(
        """
        document.getElementById('console-output').innerHTML = '';
        document.getElementById('console-panel').classList.remove('open');
        consoleViews.all = { seen: 0, lines: [] };
        consoleViews.wf = {};
        const held = [];
        for (let i = 1; i <= 240; i++) held.push('L' + i);
        window.__tail = held.slice(40);
        window.fetch = function (url) {
            if (String(url).indexOf('/api/workflow/status') === 0) {
                return Promise.resolve({ json: () => Promise.resolve({
                    running: true, logs: window.__tail, log_total: 240,
                    workflows: [
                        { id: 0, name: '甲', logs: ['a1', 'a2'], total: 2 },
                        { id: 1, name: '乙', logs: ['b1'], total: 1 }
                    ],
                    mode: 'parallel', total_nodes: 6, completed_nodes: 2,
                    results: [], chart_results: {}, cookie_expired: false, queue: []
                }) });
            }
            return Promise.resolve({ json: () => Promise.resolve({ ok: true }) });
        };
        """,
        [],
    )
    facts = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const read = () => Array.from(document.querySelectorAll('#console-output .console-line'))
            .map((el) => el.textContent);
        workflow.reconnectConsole().then(() => {
            const first = read();
            switchWfTab(1);
            const tabB = read();
            switchWfTab('all');
            done({
                asked: String(window.__tail.length),
                painted: first.length,
                first: first[0],
                last: first[first.length - 1],
                panelOpen: document.getElementById('console-panel').classList.contains('open'),
                tabs: document.querySelectorAll('#console-tabs .console-tab').length,
                tabBarShown: getComputedStyle(document.getElementById('console-tabs')).display !== 'none',
                tabB: tabB,
                allSeen: consoleViews.all.seen,
                bSeen: (consoleViews.wf[1] || {}).seen,
                statusNodes: document.getElementById('status-nodes').textContent,
                stillThere: read().length,
            });
        });
        """,
        [],
    )
    assert facts['painted'] == 200, f'the replay painted {facts["painted"]} of the {facts["asked"]} held lines'
    assert (facts['first'], facts['last']) == ('L41', 'L240'), facts
    assert facts['panelOpen'] is True, 'the log came back but its panel stayed shut'
    assert facts['tabs'] == 3 and facts['tabBarShown'] is True, f'the workflow tabs were not rebuilt: {facts}'
    assert facts['tabB'] == ['b1'], f'the 乙 tab opened blank: {facts["tabB"]}'
    assert facts['allSeen'] == 240 and facts['bSeen'] == 1, f'cursors did not land on the reported totals: {facts}'
    assert facts['stillThere'] == 200, 'returning to 全部 lost the replayed history'
    assert '2/6' in facts['statusNodes'], facts['statusNodes']


def test_a_fresh_page_reconnects_its_console_without_being_asked(app_url, driver):
    """The wiring, not the logic: ``app.js``'s boot sequence must call
    ``workflow.reconnectConsole()`` on its own.

    The reconnect code and the call site live in two different files, which is exactly the
    shape this project has already been burned by — a wrapper installed in one file whose
    signature was only right in the browser, while every single-file harness stayed green.
    A node harness loads workflow.js alone and can never see the hand-off, and no
    ``execute()`` happens here, so the only proof is a real page that nobody told to
    reconnect arriving with the server's own lines already in its console box.

    The test server writes its startup narration into the same buffer, so this reads a
    page-load against it with no run in flight: the lines must be PAINTED (the run's log is
    worth showing) and the panel must stay SHUT (a run that ended before this page opened
    does not get to take over the screen on every refresh).
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    # The boot step is one fetch deep, so wait for the lines rather than for a tick.
    shown = driver.execute_script(
        """
        const read = () => document.querySelectorAll('#console-output .console-line').length;
        return new Promise((resolve) => {
            let waited = 0;
            const step = () => {
                if (read() > 0 || waited > 6000) return resolve(read());
                waited += 100;
                setTimeout(step, 100);
            };
            step();
        });
        """,
        [],
    )
    facts = driver.execute_script(
        """
        const read = () => Array.from(document.querySelectorAll('#console-output .console-line'));
        const lines = read().map((el) => el.textContent);
        return {
            lines: lines,
            panelOpen: document.getElementById('console-panel').classList.contains('open'),
            seen: consoleViews.all.seen,
            held: consoleViews.all.lines.length,
        };
        """,
        [],
    )
    assert facts['lines'], (
        f'a page loaded against a server with lines in its console buffer showed none '
        f'({shown} after waiting) — the boot step is not wired, or it refuses to read'
    )
    assert facts['seen'] >= len(facts['lines']), (
        f'the cursor ({facts["seen"]}) is behind what was painted ({len(facts["lines"])}), so the next '
        'poll would reprint the buffer'
    )
    assert facts['held'] == len(facts['lines']), facts
    assert facts['panelOpen'] is False, 'a run that was already over took over the screen on page load: ' + ' / '.join(
        facts['lines'][:3]
    )


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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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


FAR_WORLD_WIRE_JS = r"""
// TWO flat wires, built the same way and measured the same way, differing only in
// where they sit in the world: one pair inside the 10000px #canvas-inner box (the
// positive control — proof the probe can land on painted wire at all) and one pair
// past its right edge (the case the user hit). Equal type AND equal params is what
// makes each pair's node heights equal, which is what makes each wire flat (a
// forward hop between centre-aligned ports draws ` L `, not ` C `) — and a flat
// stroke is the only geometry whose bounding-rect centre lies ON the paint, which is
// the point probed below.
canvas.nodes = {}; canvas.connections = [];
document.getElementById('nodes-container').innerHTML = '';
localStorage.removeItem('crawler_canvas');
const fill = (id) => {
    const p = canvas.nodes[id].params;
    p.operation = 'keyword'; p.method = 'tfidf'; p.topk = 10;
    canvas.updateNodeDisplay(id);
};
const pair = (x) => {
    const a = canvas.addNode('process', x, 300); fill(a);
    const b = canvas.addNode('process', x + 700, 300); fill(b);
    canvas.connections.push({from: a, to: b});
    return {a, b};
};
const near = pair(200);      // inside the world box
const far = pair(10400);     // past its right edge
canvas.updateConnections();

const svg = document.getElementById('svg-layer');
const world = document.getElementById('canvas-inner');
const work = document.getElementById('workspace').getBoundingClientRect();
const at = (x, y) => {
    const el = document.elementFromPoint(x, y);
    if (!el) return null;
    return el.className && el.className.baseVal !== undefined
        ? el.className.baseVal : String(el.tagName);
};
// Centre one pair on screen at zoom 1 by moving the camera to where the paint is,
// rather than trusting a fit that would shrink the whole 11000px spread to 0.2 and
// leave both pairs unreadable.
const measure = (which, ids) => {
    canvas.zoom = 1;
    canvas.panX = 0; canvas.panY = 0;
    canvas.updateTransform();
    const paths = Array.prototype.filter.call(
        svg.querySelectorAll('.conn-line:not(.temp)'),
        (p) => (p.getAttribute('d') || '').length
    );
    const idx = which === 'near' ? 0 : 1;
    const line = paths[idx];
    const hit = svg.querySelectorAll('.conn-delete-hit')[idx];
    let r = hit.getBoundingClientRect();
    canvas.panX = work.left + work.width / 2 - (r.left + r.right) / 2;
    canvas.panY = work.top + work.height / 2 - (r.top + r.bottom) / 2;
    canvas.updateTransform();
    r = hit.getBoundingClientRect();
    const cx = (r.left + r.right) / 2;
    const cy = (r.top + r.bottom) / 2;
    const box = svg.getBoundingClientRect();
    const nodeA = document.getElementById(ids.a);
    return {
        d: line ? (line.getAttribute('d') || '') : '',
        // The canvas-space coordinate of the node that owns this wire's out-port.
        canvasX: nodeA.offsetLeft,
        worldEdge: world.clientWidth,
        svgBox: [box.left, box.top, box.width, box.height],
        pathBox: [r.left, r.top, r.width, r.height],
        // How far past the svg's own viewport the whole stroke sits, in canvas units.
        beyondCanvas: Math.round(Math.min(nodeA.offsetLeft, nodeA.offsetWidth) - box.width),
        hitCentre: at(cx, cy),
        onScreen: cx >= work.left && cx <= work.right && cy >= work.top && cy <= work.bottom,
        overflow: getComputedStyle(svg).overflow,
    };
};
const probe = {
    near: measure('near', near),
    far: measure('far', far),
    viewport: (() => {
        const p = document.createElement('div');
        p.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;visibility:hidden';
        document.body.appendChild(p);
        const v = [p.offsetWidth, p.offsetHeight];
        p.remove();
        return v;
    })(),
};
canvas.connections = []; canvas.nodes = {};
document.getElementById('nodes-container').innerHTML = '';
canvas.updateConnections();
return probe;
"""


def test_a_wire_between_far_apart_nodes_is_painted_not_clipped(app_url, driver):
    """The nodes are `<div>`s, so dragging one past the finite #canvas-inner kept it
    visible; the wires all live in ONE `<svg>` sized 100% of that box, and an `<svg>`
    root clips to its own viewport by UA default. Past x=10000 the curve simply did not
    exist on screen — the user's report was 「连线到一定范围就不渲染了」, and
    `#svg-layer { overflow: visible }` is what removes that bound.

    A bounding rect CANNOT see this bug: a clipped path reports its full layout box while
    painting nothing. So the instrument is real hit-testing — the delete target is a
    sibling path with `pointer-events: stroke` carrying the identical `d`, and Chrome does
    not deliver a pointer event into a region clipped away. The same probe is run on a
    wire INSIDE the world box first, so "the probe finds nothing" can never be mistaken
    for "the fix works": only the pair of readings differs in where it sits, and only a
    control that lands while the far one does not is evidence about a clip.

    The viewport is emulated, because on Windows `set_window_size` is answered by neither
    the OS nor the page (see the cookie panel case above for the measurement).
    """
    driver.set_window_size(1366, 768)
    driver.execute_cdp_cmd(
        'Emulation.setDeviceMetricsOverride',
        {'width': 1366, 'height': 768, 'deviceScaleFactor': 1, 'mobile': False},
    )
    try:
        _quiet_canvas(driver, app_url)
        got = driver.execute_script(FAR_WORLD_WIRE_JS, [])
    finally:
        driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})

    inner_w, inner_h = got['viewport']
    assert abs(inner_w - 1366) <= 2 and abs(inner_h - 768) <= 2, (
        f'this case measures a 1366x768 window and CSS saw {got["viewport"]}; the emulation '
        'did not take effect, so nothing below describes a laptop'
    )
    for name, one in (('near', got['near']), ('far', got['far'])):
        assert ' L ' in one['d'] and ' C ' not in one['d'], (
            f'the {name} wire is not the flat line whose centre lies on the stroke, so its '
            f'probe point is not on any paint: {one["d"]}'
        )
        assert one['onScreen'], (
            f'the {name} wire {one["pathBox"]} never landed inside the workspace after the camera '
            f'moved, so its probe could not have hit painted pixels'
        )
    assert got['near']['canvasX'] < got['near']['worldEdge'], (
        f'the control wire was meant to sit inside the {got["near"]["worldEdge"]}px world box, '
        f'it is at canvas x={got["near"]["canvasX"]}'
    )
    assert got['far']['canvasX'] > got['far']['worldEdge'], (
        f'the measured wire was meant to sit PAST the {got["far"]["worldEdge"]}px world box, it '
        f'is at canvas x={got["far"]["canvasX"]} — the case is testing the wrong geometry'
    )
    # Positive control before the verdict: the probe lands on painted wire where the old
    # clip box always painted, so a miss below is about the clip and not about the probe.
    assert got['near']['hitCentre'] == 'conn-delete-hit', (
        f'the probe does not find the delete target even INSIDE the world box (got '
        f'{got["near"]["hitCentre"]!r} at {got["near"]["pathBox"]} inside svg '
        f'{got["near"]["svgBox"]}); the point missed the stroke, so the verdict on the far '
        'wire would mean nothing'
    )
    assert got['far']['hitCentre'] == 'conn-delete-hit', (
        f'a wire {got["far"]["beyondCanvas"]}px past the {got["far"]["worldEdge"]}px world border '
        f'still does not paint: its delete target is un-hittable at its own centre (got '
        f'{got["far"]["hitCentre"]!r} at {got["far"]["pathBox"]}, svg {got["far"]["svgBox"]}, '
        f'overflow {got["far"]["overflow"]!r}) — the UA clip is back'
    )
    assert got['far']['overflow'] == 'visible', f'the svg is clipping its viewport again: {got["far"]["overflow"]!r}'


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
    _load_app(driver, app_url)
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
            deleteProfileWord: I18n.t('cookies.deleteProfileOne'),
            profileRefuseWord: I18n.t('cookies.profileDeleteDefaultRefused'),
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
    # Rename + delete + 「删除 Profile」, in that order, for a row that HAS a profile directory.
    # Both the rename and the profile-delete are visibly refused on the default row (disabled with
    # a reason) rather than offered as a control that cannot do the thing (user: 「哪有同一个东西不同
    # 规范的」 — 默认账号 owns no folder to move, and its browser data is the platform root that nests
    # every named account, so a delete there would over-reach). A named account gets all three live.
    assert [o['label'] for o in report['workOps']] == [
        report['renameWord'],
        report['deleteWord'],
        report['deleteProfileWord'],
    ], report
    assert report['workOps'][0]['disabled'] is False, report
    assert report['workOps'][2]['disabled'] is False, report
    assert [o['label'] for o in report['defaultOps']] == [
        report['renameWord'],
        report['deleteWord'],
        report['deleteProfileWord'],
    ], report
    assert report['defaultOps'][0]['disabled'] is True and report['defaultOps'][0]['title'], report['defaultOps']
    assert (
        report['defaultOps'][2]['disabled'] is True and report['defaultOps'][2]['title'] == report['profileRefuseWord']
    ), report['defaultOps']
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
    _load_app(driver, app_url)
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
                expectDeleteProfile: I18n.t('cookies.deleteProfileOne'),
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
    assert en['dockButtons'] == [en['expectRename'], en['expectDelete'], en['expectDeleteProfile']], (
        f'the row buttons kept the old language: {en}'
    )
    assert en['dockButtons'] != zh['dockButtons'], en


def test_the_report_rows_field_wears_the_same_skin_as_the_text_field(app_url, driver):
    """The report dialog's 「行数」 number box (``#rpt-rows``) must read as a site input, not OS
    chrome, sitting beside a text field that already wore the house class.

    ``showDialog`` built every ``field`` row as a bare ``<input>`` while its text ``input`` and the
    node-panel numbers carry ``.settings-input`` — so one form had two skins. This is measured, not
    eyeballed: the rows box's computed border, ground, text colour and size are read against the
    dialog's own text input (a known ``.settings-input``), and a divergence is exactly the OS default
    creeping back. (measured: 2 inputs × 4 computed properties)
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    got = driver.execute_script(
        """
        document.body.dataset.lang = 'zh';
        I18n.apply();
        showDialog({
            message: 'x',
            input: {value: 'T', placeholder: 'p'},
            fields: [{id: 'rpt-rows', label: '行数', type: 'number', value: '20', min: '1', max: '200'}],
            buttons: [{label: 'go', value: 'go'}],
        });
        const rows = document.getElementById('rpt-rows');
        const text = document.getElementById('dialog-input');
        if (!rows || !text) return {error: 'the dialog did not build both fields, so nothing was measured'};
        const cs = (el) => {
            const s = getComputedStyle(el);
            return {border: s.borderTopWidth + ' ' + s.borderTopStyle + ' ' + s.borderTopColor,
                    bg: s.backgroundColor, color: s.color, font: s.fontSize};
        };
        return {
            measured: 2,
            rowsClass: rows.className,
            rows: cs(rows),
            text: cs(text),
            // The compact width that makes it a field, not a full row — must survive the class.
            rowsWidth: getComputedStyle(rows).width,
        };
        """,
        [],
    )
    assert 'error' not in got, got
    assert got['measured'] == 2, got
    assert 'settings-input' in got['rowsClass'], f'the rows box lost the house class: {got}'
    # Same skin as the text field it sits beside — this is the whole point of the fix.
    assert got['rows']['border'] == got['text']['border'], f'the number box border diverges from the text field: {got}'
    assert got['rows']['bg'] == got['text']['bg'], f'the number box ground diverges: {got}'
    assert got['rows']['color'] == got['text']['color'], f'the number box text colour diverges: {got}'
    assert got['rows']['font'] == got['text']['font'], f'the number box font diverges: {got}'
    # The house style must actually paint a border (0px would mean the rule never applied).
    assert got['rows']['border'].startswith('1px solid'), got['rows']['border']
    # And the dialog-field width override must win over .settings-input's width:100%.
    assert got['rowsWidth'] not in ('', 'auto'), got['rowsWidth']


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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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
        _load_app(driver, app_url)
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
    _load_app(driver, app_url)
    _kill_animations(driver)
    driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        /* The stub goes in BEFORE anything is rendered. The page's own boot reads the run
           list with the REAL fetch, and that request answers whenever the server likes: it
           repaints the table, and a repaint drops the expansion row the test is about to
           add. Stubbing first means every fetch after this point is the stub's, and the
           measurement below happens in the same script as the expansion, so no WebDriver
           round trip can slip between the row appearing and being read. */
        const summary = {{
            run_id: 'grp1', workflow_name: '热门榜 + 周排行榜', status: 'completed',
            resumable: false, node_done: 6, node_total: 6, rows_kept: 40,
            started_at: '2026-09-24 03:00', mode: 'serial', wf_count: 2, headless: 1
        }};
        const detailPayload = {{
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
        }};
        window.fetch = (url) => Promise.resolve({{ json: () => Promise.resolve(
            String(url).indexOf('/api/runs/grp1') === 0
                ? detailPayload
                : {{ ok: true, runs: [summary], total: 1, has_more: false }}
        ) }});
        const panel = document.getElementById('runs-panel');
        panel.classList.add('open');
        panel.classList.remove('hidden');
        runsManager.render([summary]);
        """,
        [],
    )
    facts = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const detail = () => document.getElementById('runs-mgr-detail-grp1');
        const read = () => {
            const row = detail();
            if (!row) return { found: false, rows: document.querySelectorAll('#runs-panel tbody tr').length };
            const names = Array.from(row.querySelectorAll('.rm-group-name'));
            const tallies = Array.from(row.querySelectorAll('.rm-group-tally'));
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
                nodes: row.querySelectorAll('.rm-node').length,
                panelBar: [panel.scrollWidth, panel.clientWidth],
                pageBar: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
                windowWidth: window.innerWidth,
                detailRight: Math.round(row.getBoundingClientRect().right),
            };
        };
        /* ``detail`` toggles, so start from a known state: drop anything already there and
           ask once. Then read in THIS script — the reason CI could report "the detail row
           never appeared" while the earlier gate said everything was fine is that the
           timeout sentinel started with 'ok', so a run that rendered nothing still passed
           the first assert and lost the reason on its way to the second. */
        const existing = detail();
        if (existing) existing.remove();
        Promise.resolve(runsManager.detail('grp1')).then(
            () => done(read()),
            (err) => done({ found: false, rejected: String((err && err.message) || err) })
        );
        """,
        [],
    )

    def _short(names):
        return [name[:24] + ('…' if len(name) > 24 else '') for name in names]

    assert facts['found'] is True, f'the detail row never appeared, so nothing about the grouping was measured: {facts}'
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
    _kill_animations(driver)
    facts = driver.execute_script(
        f"""
        document.body.dataset.lang = {lang!r};
        I18n.apply();
        const out = {{}};
        for (const id of ['node-settings', 'cookie-dialog']) {{
            const box = document.getElementById(id);
            /* The node panel scrolls its CONTENT (#settings-content) so the header and the
               resize grip stay put; the cookie dialog still scrolls itself. The rows go into
               whichever element is the scroller. */
            const scroller = id === 'node-settings' ? box.querySelector('#settings-content') : box;
            scroller.innerHTML = '';
            for (let i = 0; i < 24; i += 1) {{
                const row = document.createElement('div');
                row.className = 'settings-group';
                row.innerHTML = '<label>' + 'a'.repeat(46) + ' ' + i + '</label>';
                scroller.appendChild(row);
            }}
            box.classList.add('open');
            box.classList.remove('hidden');
            const rect = box.getBoundingClientRect();
            const cs = getComputedStyle(scroller);
            out[id] = {{
                rows: scroller.querySelectorAll('.settings-group').length,
                top: Math.round(rect.top),
                bottom: Math.round(rect.bottom),
                maxHeight: getComputedStyle(box).maxHeight,
                overflowY: cs.overflowY,
                panelOverflowY: getComputedStyle(box).overflowY,
                scrollHeight: scroller.scrollHeight,
                clientHeight: scroller.clientHeight,
                innerHeight: window.innerHeight,
                pageV: [document.documentElement.scrollHeight, document.documentElement.clientHeight],
                pageH: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
            }};
            box.classList.remove('open');
            scroller.innerHTML = '';
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
        if panel_id == 'node-settings':
            assert box['panelOverflowY'] == 'hidden', (
                'the panel itself must not scroll: the grip and the header stay put while the '
                f'content moves (measured {box["panelOverflowY"]})'
            )
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
    _load_app(driver, app_url)
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
    _load_app(driver, app_url)
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


# ─── features whose proof needs a real engine (node stub cannot render or time) ───


def _reset_canvas(driver):
    """Give the scenario a page-owned empty canvas: the shared Chrome profile can carry a
    previous run's draft (nodes, camera, type switches) that would pollute the measurement."""
    driver.execute_script(
        """
        localStorage.removeItem('crawler_canvas');
        /* The clipboard board is separate persisted state; clear it here too so a board a
           previous test wrote can never leak into this one's page boot (stateless suite). */
        localStorage.removeItem('crawler_clipboard');
        Clipboard.reset();
        canvas.nodes = {};
        canvas.connections = [];
        canvas.selectedNode = null;
        canvas.selectedNodes = [];
        canvas.disabledTypes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';
        canvas.panX = 0;
        canvas.panY = 0;
        canvas.zoom = 1;
        canvas.updateTransform();
        """,
        [],
    )


def test_autosave_writes_the_open_file_over_a_real_debounce_timer(app_url, driver):
    """The debounced autosave is a real setTimeout — the node harness fakes timers, so only a
    browser can prove it fires, saves EXACTLY once for one quiet change, names the already-open
    file (never invents a new one), and clears the dirty flag on success. It must also stay
    SILENT (no toast), because a save that announces itself every few seconds is noise."""
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    _reset_canvas(driver)
    driver.execute_script(
        """
        // Intercept instead of hitting the server: this tier performs no writes, and we need to
        // observe the exact call the autosave makes.
        window.__saves = [];
        window.__toasts = [];
        window.fetch = function (url, opts) {
            if (String(url).indexOf('/api/workflow/save') >= 0) {
                let name = null;
                try {
                    name = JSON.parse((opts && opts.body) || '{}').name;
                } catch (e) { /* leave null */ }
                window.__saves.push({url: String(url), name: name});
            }
            return Promise.resolve({ok: true, json: () => Promise.resolve({ok: true})});
        };
        const origToast = window.showToast;
        window.showToast = function (m) {
            window.__toasts.push(String(m));
            if (origToast) origToast.call(window, m);
        };
        workflow.currentFile = 'autosave-target';
        window.__historyBefore = canvas._history.length;
        canvas.addNode('source', 60, 60);   // a real change: dirties the canvas and arms the timer
        """,
        [],
    )
    armed = driver.execute_script(
        'return {dirty: canvas.dirty, timer: !!workflow._autosaveTimer, '
        'hasFn: typeof workflow.scheduleAutosave, file: String(workflow.currentFile)};',
        [],
    )
    assert armed['timer'] is True, f'adding a node did not arm the autosave debounce: {armed}'
    assert armed['dirty'] is True, 'a fresh change must leave the canvas dirty'
    # The debounce is 2000 ms; wait past it and let the awaited save settle.
    time.sleep(2.6)
    after = driver.execute_script(
        'return {saves: window.__saves, toasts: window.__toasts, dirty: canvas.dirty, '
        'hist: canvas._history.length, before: window.__historyBefore};',
        [],
    )
    assert len(after['saves']) == 1, f'expected exactly one autosave POST, got {after["saves"]}'
    assert after['saves'][0]['name'] == 'autosave-target', 'autosave must write the OPEN file, not a new name'
    assert after['toasts'] == [], f'autosave must be silent, saw toasts: {after["toasts"]}'
    assert after['dirty'] is False, 'a successful autosave must clear the dirty flag'


def test_the_minimap_uses_real_box_geometry_and_a_click_is_a_view_only_change(app_url, driver):
    """renderMinimap reads each box's real offsetLeft/offsetWidth — geometry the stub fakes.
    A click must move the CAMERA (proving the click→world→recentre path runs in a browser) while
    leaving getState() and the undo history untouched, because the camera is deliberately outside
    the model."""
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    _reset_canvas(driver)
    facts = driver.execute_script(
        """
        const a = canvas.addNode('source', 40, 40);
        const b = canvas.addNode('process', 500, 40);
        const c = canvas.addNode('output', 40, 460);
        canvas.renderMinimap();
        const box = document.getElementById('minimap');
        const nodeBoxes = box.querySelectorAll('.minimap-node').length;
        const hasView = !!box.querySelector('.minimap-view');
        const stateBefore = JSON.stringify(canvas.getState());
        const histBefore = canvas._history.length;
        const panBefore = {x: canvas.panX, y: canvas.panY};
        // Click the box's centre: the handler must read a real bounding rect and move the camera.
        const r = box.getBoundingClientRect();
        canvas.onMinimapClick({clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, currentTarget: box});
        return {
            nodeBoxes: nodeBoxes,
            hasView: hasView,
            moved: canvas.panX !== panBefore.x || canvas.panY !== panBefore.y,
            stateSame: JSON.stringify(canvas.getState()) === stateBefore,
            histSame: canvas._history.length === histBefore,
        };
        """,
        [],
    )
    assert facts['nodeBoxes'] == 3, f'the minimap drew {facts["nodeBoxes"]} node boxes for 3 real nodes'
    assert facts['hasView'] is True, 'no viewport rectangle was drawn'
    assert facts['moved'] is True, 'a minimap click did not move the camera'
    assert facts['stateSame'] is True, 'the camera must not enter getState()'
    assert facts['histSame'] is True, 'a camera move must not be an undo step'


def test_the_clipboard_drawer_renders_a_copy_and_pastes_it_as_one_undo_step(app_url, driver):
    """The board is real DOM, and a paste must be a real graph edit.

    The fast harness stubs layout and localStorage; only here can we watch the drawer
    actually open, a copied node render a row with a paste control, and that paste add a
    box to the canvas that one undo removes again — proving the board funnels through the
    SAME canvas._pasteAt the keyboard uses, not a second implementation. It also pins that
    the board lives in its OWN key, so a copy never dirties the workflow draft's clipboard.
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    _reset_canvas(driver)
    facts = driver.execute_script(
        """
        // A process node (not a source) so no async capability fetch rewrites the draft
        // behind this test's back.
        const a = canvas.addNode('process', 60, 60);
        canvas.nodes[a].params = { operation: 'keyword', keyword: 'CLIPBRD' };
        canvas.selectNode(a);
        canvas.copyNodeToClipboard(a);
        toggleClipboardDrawer();
        const drawer = document.getElementById('clipboard-drawer');
        const list = document.getElementById('clipboard-list');
        const hasRow = !!list.querySelector('[data-clip-action="paste"]');
        // Paste through the board entry, not Ctrl+V — the exact seam the feature adds.
        const entryId = Clipboard.items[0].id;
        const before = Object.keys(canvas.nodes).length;
        const pasted = Clipboard.paste(entryId, { x: 400, y: 400 });
        const after = Object.keys(canvas.nodes).length;
        const pastedKeyword = pasted && canvas.nodes[pasted] ? canvas.nodes[pasted].params.keyword : null;
        // The board paste went through the SAME funnel Ctrl+V uses, so it left the same
        // number of snapshots (addNode's default save + the params save). Rewinding far
        // enough to pass the pre-paste point must take the added box out of the real DOM —
        // proving the paste is undoable, without pinning an exact step count that belongs
        // to the shared paste path, not to this feature.
        let guard = 0;
        while (Object.keys(canvas.nodes).length > before && guard < 10) {
            canvas.undo();
            guard += 1;
        }
        const afterUndo = Object.keys(canvas.nodes).length;
        const domAfterUndo = document.querySelectorAll('#nodes-container .node').length;
        return {
            opened: drawer.classList.contains('open'),
            hasRow: hasRow,
            added: after - before,
            pastedKeyword: pastedKeyword,
            undoRestoresCount: afterUndo === before,
            domAfterUndo: domAfterUndo,
            boardKey: localStorage.getItem('crawler_clipboard') !== null,
            // The board content is NEVER inside the canvas draft key.
            draftCarriesKeyword: (localStorage.getItem('crawler_canvas') || '').indexOf('CLIPBRD') >= 0,
        };
        """,
        [],
    )
    assert facts['opened'] is True, 'toggleClipboardDrawer did not open the drawer'
    assert facts['hasRow'] is True, 'a copied node produced no paste row in the real DOM'
    assert facts['added'] == 1, f'a board paste added {facts["added"]} nodes (expected 1)'
    assert facts['pastedKeyword'] == 'CLIPBRD', 'the paste dropped the copied param'
    assert facts['undoRestoresCount'] is True, 'undoing back past the paste restores the original node count'
    assert facts['domAfterUndo'] == 1, 'after rewinding past the paste only the 1 original box remains in the DOM'
    assert facts['boardKey'] is True, 'the board was not persisted under crawler_clipboard'
    assert facts['draftCarriesKeyword'] is False, 'copied content must never ride in the workflow draft'


def test_a_closed_clipboard_drawer_leaves_no_pixel_of_itself_on_the_canvas(app_url, driver):
    """Closed means GONE — measured in the last painted column of the page, not in the CSS text.

    ``translateX(100%)`` moves a box by its own width, but ``right: 12px`` parks the box's
    right edge 12px INSIDE the layout viewport, so sliding by the width alone left exactly
    those 12px painted over the canvas. Measured in Chrome before the fix (960x920 window,
    the drawer's own 280px box): ``rect.left=926`` against ``clientWidth=938``, 12 of the
    last 40 painted columns hit-tested as ``clipboard-list``, and a pixel diff of the
    right-edge strip against the same box forced to ``display:none`` read **813 differing
    pixels, worst channel delta 41** — a sliver the user sees and cannot explain.

    Two properties are needed and both are pinned here, because either one alone still left
    part of the panel on screen:

    * the box sits beyond ``clientWidth`` (the ``100% + 12px`` translate), and
    * it is ``visibility: hidden``, because the box-shadow blurs 3px PAST the border box and
      a shadow is invisible to hit-testing — so the hit test alone would pass while a smear
      still painted. The pixel comparison is what actually decides that, which is why the
      strip is compared against ``display:none`` (the strongest possible "not there") with a
      closed-vs-closed control first: if the control is not identical, the browser's PNG
      encoder is not reproducible in this run and the comparison may not be quoted.

    ``clientWidth`` and not ``innerWidth``: it excludes a classic scrollbar, so it is the
    right-most column the user can actually see.
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    facts = driver.execute_script(
        """
        const d = document.getElementById('clipboard-drawer');
        // The page's own default state; make sure nothing left it open.
        d.classList.remove('open');
        const cs = getComputedStyle(d);
        const r = d.getBoundingClientRect();
        const cw = document.documentElement.clientWidth;
        const ch = document.documentElement.clientHeight;
        // The direct "is any of it on screen" question: walk the last 40 painted columns
        // and count the ones that land on the drawer (its own top 60px, since the box is
        // 60px down, and its mid-height so a row of chrome cannot hide it).
        let onDrawer = 0;
        for (let i = 1; i <= 40; i += 1) {
            const el = document.elementFromPoint(cw - i, Math.round(ch / 2));
            if (el && (el === d || d.contains(el))) onDrawer += 1;
        }
        return {
            clientWidth: cw,
            clientHeight: ch,
            innerWidth: window.innerWidth,
            left: r.left,
            right: r.right,
            width: r.width,
            top: r.top,
            bottom: r.bottom,
            visiblePx: Math.max(0, cw - r.left),
            onDrawer: onDrawer,
            visibility: cs.visibility,
            transform: cs.transform,
            open: d.classList.contains('open'),
            viewport: window.innerWidth + 'x' + window.innerHeight,
        };
        """,
        [],
    )
    measured = (
        f'viewport {facts["viewport"]} (client {facts["clientWidth"]}x{facts["clientHeight"]}); '
        f'drawer rect.left={facts["left"]} right={facts["right"]} width={facts["width"]} '
        f'top={facts["top"]} bottom={facts["bottom"]}; transform={facts["transform"]}'
    )
    assert facts['open'] is False, f'the drawer was already open, so nothing was measured: {measured}'
    assert facts['visibility'] == 'hidden', f'a closed drawer must not be painted at all: {measured}'
    assert facts['left'] >= facts['clientWidth'], (
        f'the closed drawer is inside the layout viewport by {facts["visiblePx"]}px '
        f'(the `right: 12px` offset has to be paid for in the closed translate): {measured}'
    )
    assert facts['onDrawer'] == 0, (
        f'{facts["onDrawer"]} of the last 40 painted columns belong to the closed drawer: {measured}'
    )

    # The strip a closed drawer would show: its own y-range, the last 60 painted columns.
    strip = {
        'x': max(0, facts['clientWidth'] - 60),
        'y': max(0, int(facts['top'])),
        'width': min(60, facts['clientWidth']),
        'height': max(1, int(min(facts['bottom'], facts['clientHeight'])) - int(facts['top'])),
        'scale': 1,
    }
    assert strip['width'] > 0 and strip['y'] < facts['clientHeight'], f'no strip over the canvas to compare: {measured}'

    def shot():
        answer = driver.execute_cdp_cmd('Page.captureScreenshot', {'format': 'png', 'clip': strip})
        return answer['data']

    closed, control = shot(), shot()
    driver.execute_script("document.getElementById('clipboard-drawer').style.display = 'none';")
    gone = shot()
    driver.execute_script("document.getElementById('clipboard-drawer').style.display = '';")
    assert closed == control, (
        'the browser did not paint two identical states identically, so a pixel comparison here '
        f'proves nothing and must not be quoted (strip {strip}, {measured})'
    )
    assert closed == gone, (
        'the closed drawer is not identical to the same box at display:none — it still paints '
        f'something the hit test cannot see (a shadow or an edge) (strip {strip}, {measured})'
    )


def test_multi_select_marks_real_boxes_and_batch_delete_removes_them_from_the_dom(app_url, driver):
    """Selection paints real DOM classes and the marquee hit-test reads real box geometry; a batch
    delete must physically remove those boxes from #nodes-container. The stub records a fake
    class list and layout — only here can we watch the boxes actually light and vanish."""
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    _reset_canvas(driver)
    facts = driver.execute_script(
        """
        const a = canvas.addNode('source', 0, 0);
        const b = canvas.addNode('process', 100, 0);
        const far = canvas.addNode('output', 1200, 0);
        // Marquee over the two near boxes only; pin pan/zoom and the workspace origin so the
        // hit-test is measured purely against the nodes' real offsetLeft (geometry the stub fakes).
        canvas.panX = 0;
        canvas.panY = 0;
        canvas.zoom = 1;
        canvas._marqueeSelect({x: 0, y: 0, w: 300, h: 300}, {left: 0, top: 0});
        const selectedAfterMarquee = Array.from(document.querySelectorAll('.node.selected')).map((el) => el.id).sort();
        const marqueeSet = canvas.selectedNodes.slice().sort();
        // One batch delete removes both from the model AND the real DOM.
        const domBefore = document.querySelectorAll('#nodes-container .node').length;
        canvas.deleteNodes([a, b]);
        const domAfter = document.querySelectorAll('#nodes-container .node').length;
        return {
            selectedAfterMarquee: selectedAfterMarquee,
            marqueeSet: marqueeSet,
            farExcluded: marqueeSet.indexOf(far) < 0,
            domBefore: domBefore,
            domAfter: domAfter,
            remaining: Object.keys(canvas.nodes).length,
        };
        """,
        [],
    )
    assert facts['domBefore'] == 3, f'three nodes should be in the real DOM: {facts}'
    assert sorted(facts['marqueeSet']) == sorted(facts['selectedAfterMarquee']), (
        'the selection set and the lit DOM classes disagree'
    )
    assert len(facts['marqueeSet']) == 2, f'the marquee must catch the 2 near boxes: {facts["marqueeSet"]}'
    assert facts['farExcluded'] is True, 'the far node must stay out of the band'
    assert facts['remaining'] == 1, f'batch delete left {facts["remaining"]} nodes in the model'
    assert facts['domAfter'] == 1, f'batch delete left {facts["domAfter"]} boxes in the DOM (el.remove() skipped)'


def test_batch_paste_and_apply_to_all_reach_the_real_dom(app_url, driver):
    """Batch copy→paste adds real boxes (one undo step), and a same-type multi-select writes one
    panel field to EVERY selected node's real params — the DOM/`getState` view of the apply-to-all
    path the node harness checks only at the object level."""
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    _kill_animations(driver)
    _reset_canvas(driver)
    facts = driver.execute_script(
        """
        const a = canvas.addNode('process', 40, 40);
        const b = canvas.addNode('process', 40, 340);
        canvas.nodes[a].params.keyword = 'A';
        canvas.nodes[b].params.keyword = 'B';
        canvas.selectedNodes = [a, b];
        canvas.selectedNode = b;
        const copyCount0 = document.querySelectorAll('#nodes-container .node').length;
        canvas.copySelection();
        canvas.pasteNodesAt({ x: 700, y: 40 });
        const pasteDom = document.querySelectorAll('#nodes-container .node').length;

        // Re-open the group selection and write one field through the real updateParam path.
        const all = Object.keys(canvas.nodes);
        canvas.setSelectedNodes(all);
        canvas._settingsNodeId = all[0];
        updateParam(all[0], 'keyword', '写到全部');
        return {
            copyCount0,
            pasteDom,
            targets: canvas.multiEditTargets(all[0]).length,
            keywords: all.map((id) => canvas.nodes[id].params.keyword),
        };
        """,
        [],
    )
    assert facts['pasteDom'] == facts['copyCount0'] + 2, f'batch paste must add 2 real boxes: {facts}'
    assert facts['targets'] >= 2, 'the same-type group must resolve to a multi-edit set'
    assert all(k == '写到全部' for k in facts['keywords']), f'apply-to-all must reach every node: {facts["keywords"]}'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_saving_a_chart_as_svg_hands_over_a_real_vector_document(app_url, driver, lang):
    r"""The node harness can only prove the vector path's refusals: serializing an SVG needs a real
    renderer, and the stub has no `outerHTML`. Only a browser can show that the bytes the button
    posts are a vector figure at all — with the chart's own Chinese words as `<text>` elements
    (a raster with a `.svg` name would pass a size check and fail a reader), the requested size
    written into the document, and nothing that could carry a script.

    The off-screen surface is the other half: an export that leaves a hidden chart instance and a
    stray `<div>` on the page leaks on every click.
    """
    driver.set_window_size(1650, 1080)
    _load_app(driver, app_url)
    _kill_animations(driver)
    facts = driver.execute_script(
        r"""
        document.body.dataset.lang = arguments[0];
        I18n.apply();
        const option = {
            title: { text: '主题分布' },
            xAxis: { type: 'category', data: ['数字治理', '乡村振兴', '公共服务'] },
            yAxis: { type: 'value' },
            series: [{ type: 'bar', name: '频次', data: [12, 7, 4] }],
        };
        const before = document.body.children.length;
        const markup = chartSvgMarkup(option, 900, 520);
        const after = document.body.children.length;
        const host = document.createElement('div');
        host.style.cssText = 'position:fixed;left:0;top:0;width:900px;height:520px;';
        document.body.appendChild(host);
        const painted = echarts.init(host, null, { renderer: 'svg' });
        painted.setOption(option);
        const texts = Array.from(host.querySelectorAll('text')).map((t) => t.textContent);
        painted.dispose();
        host.remove();
        return {
            length: markup.length,
            starts: markup.slice(0, 60),
            hasXmlns: markup.indexOf('xmlns=') >= 0,
            width: (markup.match(/width="900"/) || []).length,
            height: (markup.match(/height="520"/) || []).length,
            hasText: markup.indexOf('<text') >= 0,
            namesInMarkup: ['数字治理', '乡村振兴', '公共服务'].every((n) => markup.indexOf(n) >= 0),
            script: /<\s*script|\son[a-z]+\s*=|\bhref\s*=/i.test(markup),
            closed: markup.trim().endsWith('</svg>'),
            leaked: after - before,
            paintedTexts: texts.length,
        };
        """,
        lang,
    )
    assert facts['length'] > 500, f'the serializer returned almost nothing: {facts["starts"]!r}'
    assert facts['starts'].lstrip().startswith('<svg'), facts['starts']
    assert facts['hasXmlns'] is True, 'an SVG without its namespace is not a document'
    assert facts['closed'] is True, 'the document was truncated'
    assert facts['width'] == 1 and facts['height'] == 1, f'the requested size is not written in: {facts}'
    assert facts['hasText'] is True, 'labels must be text, not paths, or the figure is a picture'
    assert facts['namesInMarkup'] is True, 'the chart’s own category names must survive into the file'
    assert facts['script'] is False, 'the markup carries something the server would (rightfully) refuse'
    assert facts['paintedTexts'] > 0, 'the SVG renderer painted no labels, so the measurement is hollow'
    assert facts['leaked'] == 0, 'the off-screen surface was left on the page'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_replay_bar_sits_under_the_chart_and_its_frames_are_real(app_url, driver, lang):
    """The year-by-year replay, measured where it is painted.

    Two facts only a real engine gives, and both were paid for on 2026-10-24:

    * the bar is appended UNDER a canvas ECharts sized at ``init``, so without a ``resize()`` the
      canvas keeps the old height and swallows the click meant for 播放 — Chrome answered
      ``ElementClickInterceptedException`` naming the ``<canvas>`` while the bar looked perfect in
      a screenshot;
    * a frame reaches the screen through a partial ``setOption`` merge, and whether a graph node
      actually disappears is ECharts' decision, not the option author's.

    Nothing is written: the option is handed straight to the preview window in the shape
    ``services/biblio/charts`` ships it (every node carrying its own ``yearSeries``).
    """
    driver.set_window_size(1650, 1080)
    _load_app(driver, app_url)
    _kill_animations(driver)
    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        document.documentElement.dataset.themeChoice = 'dark';
        applyTheme();
        I18n.apply();
        renderChartPreview({ ok: true, engine: 'echarts', option: {
            series: [{
                type: 'graph', layout: 'none', left: 30, top: 60, right: 30, bottom: 90,
                data: [
                    { name: '甲', x: 0, y: 0, symbolSize: 30, label: { show: true },
                      yearSeries: [[2018, 1], [2019, 2]] },
                    { name: '乙', x: 60, y: 0, symbolSize: 20, label: { show: true },
                      yearSeries: [[2018, 2]] },
                    { name: '丙', x: 30, y: 60, symbolSize: 14, label: { show: true },
                      yearSeries: [[2019, 1]] },
                ],
                links: [
                    { source: '甲', target: '乙', value: 2 },
                    { source: '甲', target: '丙', value: 1 },
                ],
            }],
        } });
        """,
        lang,
    )
    time.sleep(1.0)

    def measure():
        return driver.execute_script(
            """
            const panel = document.getElementById('chart-preview-panel');
            const bar = panel.querySelector('.chart-replay-bar');
            const host = document.getElementById('chart-preview-echarts');
            const barRect = bar.getBoundingClientRect();
            const hostRect = host.getBoundingClientRect();
            const inst = echarts.getInstanceByDom(host);
            const series = inst.getOption().series[0];
            const shown = series.data.filter(function (node) {
                return (node.itemStyle || {}).opacity !== 0 && Number(node.symbolSize) > 2;
            }).map(function (node) { return node.name; });
            const hiddenLinks = (series.links || []).filter(function (link) {
                return (link.lineStyle || {}).opacity === 0;
            }).length;
            return {
                barHeight: Math.round(barRect.height),
                gapBelowChart: Math.round(barRect.top - hostRect.bottom),
                shown: shown,
                hiddenLinks: hiddenLinks,
                readout: bar.querySelector('.chart-replay-year').textContent,
                playLabel: bar.querySelector('.chart-replay-play').textContent,
                allWord: I18n.t('chart.replayAllYears'),
                playWord: I18n.t('chart.replayPlay'),
                pauseWord: I18n.t('chart.replayPause'),
                year2018: I18n.t('chart.replayYear', { year: 2018 }),
                storedUntouched: JSON.stringify(_chartPreviewOption).indexOf('"symbolSize":30') >= 0,
            };
            """
        )

    whole = measure()
    assert whole['barHeight'] > 20, f'the bar painted {whole["barHeight"]}px of nothing'
    assert whole['gapBelowChart'] >= -1, (
        f'the bar is under the chart, not below it: it starts {whole["gapBelowChart"]}px above the '
        'canvas bottom, so a click on it hits the canvas'
    )
    assert len(whole['shown']) == 3, whole['shown']
    assert whole['hiddenLinks'] == 0
    assert whole['readout'] == whole['allWord'] != 'chart.replayAllYears'

    # The button has to answer a real mouse, not just exist in the DOM. The handler runs inside
    # the click, so the frame it cut is measurable the moment the call returns — no sleeping on
    # the 900 ms tick, which is a race this tier must not lose on a loaded machine.
    driver.find_element('css selector', '#chart-preview-panel .chart-replay-play').click()
    playing = measure()
    assert playing['readout'] == playing['year2018'], f'播放 did not land on the first year: {playing["readout"]}'
    assert len(playing['shown']) == 2, f'the 2018 frame still shows every node: {playing["shown"]}'
    assert playing['playLabel'] == playing['pauseWord'], 'the button must say what it will do next'
    driver.execute_script('_replayStop("preview");')

    driver.execute_script('_replayShow("preview", 0);')
    time.sleep(0.6)
    first = measure()
    assert sorted(first['shown']) == ['乙', '甲'], f'the 2018 frame shows the wrong set: {first["shown"]}'
    assert first['hiddenLinks'] == 1, 'the link to a node that has not happened yet must not be drawn'
    assert first['readout'] == first['year2018'] != 'chart.replayYear'
    assert first['storedUntouched'] is True, 'frames must be cut from the option, never carved out of it'

    driver.find_element('css selector', '#chart-preview-panel .chart-replay-reset').click()
    time.sleep(0.8)
    reset = measure()
    assert len(reset['shown']) == 3 and reset['hiddenLinks'] == 0, '看完整图 did not restore the figure'
    assert reset['readout'] == reset['allWord']
    assert reset['playLabel'] == reset['playWord']


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_world_map_loads_its_shipped_basemap_and_prints_no_colliding_labels(app_url, driver, lang):
    """The country choropleth, measured in the browser that has to draw it.

    Three things the Python tier cannot reach:

    * the basemap is a FILE the app serves, and ``static_url_path`` is ``''`` here — a guessed
      ``/static/geo/...`` is a 404 and a toast the user reads as "maps are broken";
    * ``registerMap(name, {geoJSON, nameProperty})`` is what makes a Chinese run's data names and
      its printed labels the same words; ECharts 5 alone decides whether it honours that;
    * whether the country labels collide. Measured at the preview panel's own 400 px: 德国 over 英国
      and 中华人民共和国 over 日本 until ``labelLayout.hideOverlap`` was set WITHOUT ``moveOverlap``
      (adding 'shiftY' switches hiding off again — 12 labels with the collisions, against 10 without).

    Nothing is written to the server; the option is built in the page in the shape
    ``services/biblio/charts`` ships.
    """
    driver.set_window_size(1650, 1080)
    served = _read_url_json(app_url + '/geo/world.json')
    assert served is not None, 'the basemap is not served — static_url_path is "", so the app path is /geo/...'
    features = served.get('features') or []
    assert len(features) > 150, f'the served basemap carries only {len(features)} regions'
    _load_app(driver, app_url)
    _kill_animations(driver)

    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        document.documentElement.dataset.themeChoice = 'dark';
        applyTheme();
        I18n.apply();
        ensureMapRegistered(arguments[1] === 'zh' ? 'world_zh' : 'world');
        """,
        lang,
        lang,
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        ready = driver.execute_script(
            'return !!(echarts.getMap && echarts.getMap(arguments[0]));', 'world_zh' if lang == 'zh' else 'world'
        )
        if ready:
            break
        time.sleep(0.4)
    assert driver.execute_script(
        'return !!(echarts.getMap && echarts.getMap(arguments[0]));', 'world_zh' if lang == 'zh' else 'world'
    ), 'the basemap never registered with ECharts'

    host = 'geo-measure-host'
    driver.execute_script(
        """
        const lang = arguments[0], hostId = arguments[1];
        const zh = lang === 'zh';
        const names = zh
            ? ['中华人民共和国', '美国', '英国', '德国', '日本', '法国', '印度', '澳大利亚']
            : ['China', 'United States of America', 'United Kingdom', 'Germany', 'Japan', 'France', 'India',
               'Australia'];
        const host = document.createElement('div');
        host.id = hostId;
        host.style.cssText = 'position:fixed;left:0;top:0;width:400px;height:600px;background:#fff';
        document.body.appendChild(host);
        const inst = echarts.init(host, null, { renderer: 'svg' });
        window.__geo = { inst: inst, host: host };
        applyEchartsOption(inst, {
            title: { text: I18n.t('chart.geo_map'), subtext: I18n.t('chart.biblio_geo_merged',
                                                                      { n: 1, detail: 'England→x' }) },
            tooltip: { trigger: 'item', formatter: '{b}: {c}' },
            visualMap: { min: 0, max: 35, left: 16, bottom: 22, itemWidth: 12, itemHeight: 88,
                         inRange: { color: ['#ffffff', '#fdcc8a', '#e34a33'] } },
            series: [{
                type: 'map', map: zh ? 'world_zh' : 'world', nameProperty: zh ? 'zh' : 'name',
                left: 12, right: 96, top: 74, bottom: 96, aspectScale: 0.92, label: { show: false },
                data: names.map(function (n, i) {
                    return { name: n, value: 35 - i * 3, label: { show: true } };
                })
            }]
        });
        """,
        lang,
        host,
    )
    time.sleep(1.8)
    facts = driver.execute_script(
        """
        const host = document.getElementById(arguments[0]);
        const rect = host.getBoundingClientRect();
        const painted = Array.from(host.querySelectorAll('svg text')).map(function (t) {
            return { text: t.textContent, box: t.getBoundingClientRect() };
        }).filter(function (item) { return item.text.trim() && item.box.width > 0 && item.box.height <= 18; });
        let overlaps = 0;
        const pairs = [];
        for (let i = 0; i < painted.length; i++) {
            for (let j = i + 1; j < painted.length; j++) {
                const a = painted[i].box, b = painted[j].box;
                const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                if (x > 1 && y > 1) {
                    overlaps++;
                    if (pairs.length < 5) pairs.push([painted[i].text, painted[j].text]);
                }
            }
        }
        const outside = painted.filter(function (item) {
            const b = item.box;
            return b.right > rect.right + 1 || b.left < rect.left - 1 || b.bottom > rect.bottom + 1;
        }).map(function (item) { return item.text.slice(0, 24); });
        const paths = host.querySelectorAll('svg path').length;
        return { measured: painted.length, paths: paths, overlaps: overlaps, pairs: pairs, outside: outside };
        """,
        host,
    )
    driver.execute_script(
        """
        const host = document.getElementById(arguments[0]);
        if (window.__geo) { window.__geo.inst.dispose(); }
        host.remove();
        """,
        host,
    )
    assert facts['paths'] > 100, f'the map drew {facts["paths"]} shapes — that is not a world map'
    assert facts['measured'] >= 4, f'only {facts["measured"]} labels measured; the audit is hollow'
    assert facts['overlaps'] == 0, f'country labels collide: {facts["pairs"]}'
    assert facts['outside'] == [], f'labels run past the canvas: {facts["outside"]}'


def _overlay_options(lang: str) -> dict:
    """The two overlay options, built by the service in the run's language."""
    import pandas as pd

    from i18n import set_lang
    from services.visualizer import VisualizationService

    frame = pd.DataFrame(
        {
            '节点': ['数字治理', '数据要素', '公共服务', '协同监管'],
            '频次': [30, 26, 22, 20],
            '情感分布': [
                json.dumps({'positive': 6, 'neutral': 3, 'negative': 1}),
                json.dumps({'negative': 5, 'neutral': 2, 'positive': 1}),
                json.dumps({'neutral': 4, 'positive': 1}),
                json.dumps({'positive': 2, 'negative': 2}),
            ],
            '话题分布': [
                json.dumps({'T1': 7, 'T2': 3}),
                json.dumps({'T2': 6, 'T1': 1}),
                json.dumps({'T1': 5}),
                json.dumps({'T2': 2}),
            ],
        }
    )
    set_lang(lang)
    try:
        return {
            'sentiment_overlay': VisualizationService.to_echarts_option(
                frame, 'sentiment_overlay', title='overlay-probe'
            ),
            'topic_overlay': VisualizationService.to_echarts_option(frame, 'topic_overlay', title='overlay-probe'),
        }
    finally:
        set_lang('zh')


def _concentric_option(lang: str) -> dict:
    """Three year rings, six Chinese keyword nodes: the layout at the preview panel's 400 px."""
    import pandas as pd

    from i18n import set_lang
    from services.visualizer import VisualizationService

    names = ['数字治理', '数据要素', '公共服务', '协同监管', '算法问责', '开放数据']
    years = [2018, 2018, 2019, 2019, 2020, 2020]
    links = [
        json.dumps([{'target': names[(index + 1) % len(names)], 'value': 1.0}], ensure_ascii=False)
        for index in range(len(names))
    ]
    frame = pd.DataFrame(
        {
            '节点': names,
            '频次': [30, 26, 22, 20, 18, 16],
            '连接': links,
            '年份序列': [json.dumps({str(year): 2 + index % 3}) for index, year in enumerate(years)],
        }
    )
    set_lang(lang)
    try:
        return VisualizationService.to_echarts_option(frame, 'concentric', title='concentric-probe')
    finally:
        set_lang('zh')


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_concentric_rings_draw_inside_the_preview_panel(app_url, driver, lang):
    """The ring layout at 400×600: every node lands in the canvas, labels never stack, and the
    explanatory note under the title is painted rather than clipped.

    A graph with ``layout:'none'`` places nodes by their own coordinates, so the only way to know
    the rings fit a narrow preview is to render them there; the note matters because "which ring
    is which year" is not guessable from the picture alone.
    """
    driver.set_window_size(1650, 1080)
    _load_app(driver, app_url)
    _kill_animations(driver)
    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        document.documentElement.dataset.themeChoice = 'dark';
        applyTheme();
        I18n.apply();
        const old = document.getElementById('ring-measure-host');
        if (old) old.remove();
        const host = document.createElement('div');
        host.id = 'ring-measure-host';
        host.style.cssText = 'position:fixed;left:0;top:0;width:400px;height:600px;background:#fff';
        document.body.appendChild(host);
        window.__ring = echarts.init(host, null, { renderer: 'svg' });
        applyEchartsOption(window.__ring, arguments[1]);
        """,
        lang,
        _concentric_option(lang),
    )
    time.sleep(1.4)
    facts = driver.execute_script(
        """
        const host = document.getElementById('ring-measure-host');
        const rect = host.getBoundingClientRect();
        const painted = Array.from(host.querySelectorAll('svg text')).map(function (t) {
            return { text: t.textContent, box: t.getBoundingClientRect() };
        }).filter(function (item) { return item.text.trim() && item.box.width > 0; });
        let overlaps = 0;
        const pairs = [];
        for (let i = 0; i < painted.length; i++) {
            for (let j = i + 1; j < painted.length; j++) {
                const a = painted[i].box, b = painted[j].box;
                const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                if (x > 1 && y > 1) {
                    overlaps++;
                    if (pairs.length < 5) pairs.push([painted[i].text, painted[j].text]);
                }
            }
        }
        const outside = painted.filter(function (item) {
            const b = item.box;
            return b.left < rect.left - 1 || b.right > rect.right + 1
                || b.top < rect.top - 1 || b.bottom > rect.bottom + 1;
        }).map(function (item) { return item.text.slice(0, 24); });
        const symbols = host.querySelectorAll('svg path').length;
        return {
            symbols: symbols,
            texts: painted.map(function (item) { return item.text; }),
            overlaps: overlaps,
            pairs: pairs,
            outside: outside
        };
        """
    )
    driver.execute_script(
        """
        if (window.__ring) { window.__ring.dispose(); }
        document.getElementById('ring-measure-host').remove();
        """
    )
    joined = ' | '.join(facts['texts'])
    assert facts['symbols'] >= 6, f'{facts["symbols"]} painted symbols for six nodes'
    assert any(name in joined for name in ('数字治理', '数据要素')), joined
    assert facts['overlaps'] == 0, f'labels collide: {facts["pairs"]}'
    assert facts['outside'] == [], f'labels run past the canvas: {facts["outside"]}'
    if lang == 'zh':
        assert '同心环' in joined, 'the ring rule must be painted under the title'
    else:
        assert 'Concentric' in joined, 'the ring rule must be painted under the title'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_overlay_views_print_every_label_inside_the_preview_panel(app_url, driver, lang):
    """Both overlay views, measured at the preview panel's own 400 px.

    What only a browser can say: a 200 px ``axisLabel.width`` hangs 46 px LEFT of a 400 px canvas
    and the node names are cut away entirely (measured, then narrowed to 96 px); a scroll legend
    adds a ``1/1`` page marker that lands on the first row's text; and the theme patcher rewrites
    a series label colour for the background, so a white number inside a coloured segment has to
    be stated per data item. The note under the title and the legend share the top band, which is
    why the sentiment grid starts at a fixed 112 px rather than a percentage.
    """
    driver.set_window_size(1650, 1080)
    _load_app(driver, app_url)
    _kill_animations(driver)
    driver.execute_script(
        """
        document.body.dataset.lang = arguments[0];
        document.documentElement.dataset.themeChoice = 'dark';
        applyTheme();
        I18n.apply();
        """,
        lang,
    )
    totals = {}
    for chart_type, option in _overlay_options(lang).items():
        driver.execute_script(
            """
            const old = document.getElementById('overlay-measure-host');
            if (old) old.remove();
            const host = document.createElement('div');
            host.id = 'overlay-measure-host';
            host.style.cssText = 'position:fixed;left:0;top:0;width:400px;height:600px;background:#fff';
            document.body.appendChild(host);
            window.__overlay = echarts.init(host, null, { renderer: 'svg' });
            applyEchartsOption(window.__overlay, arguments[0]);
            """,
            option,
        )
        time.sleep(1.4)
        facts = driver.execute_script(
            """
            const host = document.getElementById(arguments[0]);
            const rect = host.getBoundingClientRect();
            const painted = Array.from(host.querySelectorAll('svg text')).map(function (t) {
                return { text: t.textContent, box: t.getBoundingClientRect() };
            }).filter(function (item) { return item.text.trim() && item.box.width > 0 && item.box.height <= 24; });
            let overlaps = 0;
            const pairs = [];
            for (let i = 0; i < painted.length; i++) {
                for (let j = i + 1; j < painted.length; j++) {
                    const a = painted[i].box, b = painted[j].box;
                    const x = Math.min(a.right, b.right) - Math.max(a.left, b.left);
                    const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
                    if (x > 1 && y > 1) {
                        overlaps++;
                        if (pairs.length < 5) pairs.push([painted[i].text, painted[j].text]);
                    }
                }
            }
            const outside = painted.filter(function (item) {
                const b = item.box;
                return b.left < rect.left - 1 || b.right > rect.right + 1
                    || b.top < rect.top - 1 || b.bottom > rect.bottom + 1;
            }).map(function (item) { return item.text.slice(0, 24); });
            return { measured: painted.length, overlaps: overlaps, pairs: pairs, outside: outside };
            """,
            'overlay-measure-host',
        )
        driver.execute_script(
            """
            if (window.__overlay) { window.__overlay.dispose(); }
            document.getElementById('overlay-measure-host').remove();
            """
        )
        assert facts['measured'] >= 12, f'{chart_type}: only {facts["measured"]} labels measured'
        assert facts['overlaps'] == 0, f'{chart_type} labels collide: {facts["pairs"]}'
        assert facts['outside'] == [], f'{chart_type} labels run past the canvas: {facts["outside"]}'
        totals[chart_type] = facts['measured']
    assert set(totals) == {'sentiment_overlay', 'topic_overlay'}


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_export_guide_lists_a_link_the_user_can_copy(app_url, driver, lang):
    """The overlay measured in a real engine: links copyable, wording translated, scrim only.

    Three things only a browser can answer. The anchor must carry ``rel="noopener noreferrer"``
    and show the URL as its own text, because the whole purpose of the guide is that a user
    copies the address and searches there himself. The sentences arrive translated, so a switch
    to the other language has to change them — a catalogue key reaching the screen is the failure
    this tier exists to see. And the backdrop dismissal is an identity test against the overlay
    element, which only a real click can prove is not fired by a click inside the sheet.
    """
    driver.set_window_size(1400, 900)
    _load_app(driver, app_url)
    driver.execute_script(
        """
        const original = window.fetch;
        const payload = {
            ok: true,
            extensions: ['.net', '.ris', '.txt'],
            sources: [
                { id: 'CSSCI', label: 'CSSCI', group: 'library', site: 'https://cssci.nju.edu.cn/',
                  extensions: ['.txt'], capabilities: {},
                  purpose: '合成说明一', steps: ['1. 检索', '2. 导出文本'], missing: ['无【摘要】'] },
                { id: 'NoteExpress', label: 'NoteExpress', group: 'exchange', site: 'https://kns.cnki.net/',
                  extensions: ['.net'], capabilities: {},
                  purpose: '合成说明二', steps: ['1. 选 NoteExpress 下载'], missing: [] }
            ]
        };
        window.__asked = [];
        window.fetch = (url) => {
            const u = String(url);
            if (u.indexOf('/api/biblio/sources') >= 0) {
                window.__asked.push(u);
                const body = JSON.stringify(payload);
                const answer = { text: () => Promise.resolve(body), json: () => Promise.resolve(body), status: 200 };
                return Promise.resolve(answer);
            }
            return original.apply(window, arguments.length ? Array.prototype.slice.call(arguments) : []);
        };
        toggleSourceHelp();
        """
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if driver.execute_script("return document.querySelectorAll('#source-help-body .source-help-item').length") >= 2:
            break
        time.sleep(0.2)

    facts = driver.execute_script(
        r"""
        const body = document.getElementById('source-help-body');
        const links = Array.from(body.querySelectorAll('a'));
        const raw = [];
        body.querySelectorAll('*').forEach(function (el) {
            const text = (el.textContent || '').trim();
            if (/^(sourceHelp|source)\.[\w.]+$/.test(text)) raw.push(text);
        });
        const box = document.getElementById('source-help-box').getBoundingClientRect();
        return {
            items: body.querySelectorAll('.source-help-item').length,
            groups: body.querySelectorAll('.source-help-group').length,
            linkTexts: links.map(function (a) { return a.textContent.trim(); }),
            hrefs: links.map(function (a) { return a.getAttribute('href'); }),
            rels: links.map(function (a) { return a.getAttribute('rel'); }),
            targets: links.map(function (a) { return a.getAttribute('target'); }),
            raw: raw,
            missing: body.querySelectorAll('.source-help-missing').length,
            steps: body.querySelectorAll('.source-help-steps li').length,
            accepts: (document.getElementById('dataset-file-input').getAttribute('accept') || '').split(','),
            insideViewport: box.right <= window.innerWidth + 1 && box.left >= -1,
            opened: document.getElementById('source-help-overlay').classList.contains('open'),
        };
        """
    )
    assert facts['items'] == 2, facts
    assert facts['groups'] == 2, 'both served groups are headed, in the page language'
    assert facts['raw'] == [], f'an untranslated catalogue key reached the screen: {facts["raw"]}'
    assert facts['hrefs'] and all(str(href).startswith('https://') for href in facts['hrefs']), facts['hrefs']
    assert facts['linkTexts'] == facts['hrefs'], 'the visible text must be the URL, so it can be copied'
    assert all(rel and 'noopener' in rel and 'noreferrer' in rel for rel in facts['rels']), facts['rels']
    assert all(target == '_blank' for target in facts['targets']), facts['targets']
    assert facts['steps'] >= 3 and facts['missing'] >= 1, facts
    assert '.net' in facts['accepts'], f'the served extension never reached the picker: {facts["accepts"]}'
    assert '.csv' in facts['accepts'], f'merging the list dropped what the picker already had: {facts["accepts"]}'
    assert facts['insideViewport'] is True, 'a centred overlay may not hang outside the window'

    scrim_and_sheet = driver.execute_script(
        """
        const overlay = document.getElementById('source-help-overlay');
        const sheet = document.getElementById('source-help-box');
        const isOpen = () => overlay.classList.contains('open');
        overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        const afterScrim = isOpen();
        toggleSourceHelp();
        sheet.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        const afterSheet = isOpen();
        closeSourceHelp();
        return { afterScrim, afterSheet };
        """
    )
    assert scrim_and_sheet['afterScrim'] is False, 'a click on the dimmed backdrop closes the guide'
    assert scrim_and_sheet['afterSheet'] is True, 'a click inside the sheet must not close it'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_reusable_node_expands_inside_its_own_border_and_aggregates_statuses(driver, app_url, lang):
    """The inside of a reusable node is a real browser render, not a list.

    What only pixels can settle: the group's outer border encloses its inside cards
    (the inside never becomes unrelated top-level nodes), the two inside boxes do not
    overlap, the inside stage does not overflow the group, a collapsed/expanded toggle
    is immediate, and the group badge is the aggregate of the children (running wins
    over done). The template save is stubbed in the page: this module performs no
    server writes.
    """
    _load_app(driver, app_url)
    facts = driver.execute_async_script(
        """
        const lang = arguments[0];
        const done = arguments[arguments.length - 1];
        document.body.dataset.lang = lang;
        I18n.apply();
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        canvas.selectedNodes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';

        const realFetch = window.fetch;
        const realDialog = window.showDialog;
        window.fetch = function (url, opts) {
            if (String(url).indexOf('/api/reusable/save') >= 0) {
                const body = JSON.parse(opts.body);
                const payload = { ok: true, template: Object.assign({ id: 'r-000000000001' }, body) };
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve(payload),
                    text: () => Promise.resolve(JSON.stringify(payload)),
                });
            }
            return realFetch.apply(window, arguments);
        };
        window.showDialog = async function (spec) {
            if (spec && spec.input) return lang === 'zh' ? '浏览器验收' : 'Browser check';
            return true;
        };

        (async () => {
            try {
                const up = canvas.addNode('process', 320, 90);
                const a = canvas.addNode('process', 620, 90);
                const b = canvas.addNode('analysis', 920, 90);
                const down = canvas.addNode('output', 1220, 90);
                canvas.connections = [
                    { from: up, to: a },
                    { from: a, to: b },
                    { from: b, to: down },
                ];
                canvas.setSelectedNodes([a, b]);
                await ReusableNodes.createFromSelection();
                const group = Object.keys(canvas.nodes).find((id) => canvas.nodes[id].type === 'reusable');
                if (!group) throw new Error('no reusable group was created');
                const el = canvas._nodeEl(group);
                document.getElementById('reusable-auto-layout').checked = false;
                ReusableNodes.toggle(group);
                await new Promise((r) => setTimeout(r, 250));

                const stage = el.querySelector('.reusable-stage');
                const cards = Array.from(el.querySelectorAll('.reusable-inner-node'));
                const rects = cards.map((c) => c.getBoundingClientRect());
                let overlap = false;
                for (let i = 0; i < rects.length; i += 1) {
                    for (let j = i + 1; j < rects.length; j += 1) {
                        const x = rects[i];
                        const y = rects[j];
                        if (
                            Math.min(x.right, y.right) - Math.max(x.left, y.left) > 1 &&
                            Math.min(x.bottom, y.bottom) - Math.max(x.top, y.top) > 1
                        ) {
                            overlap = true;
                        }
                    }
                }

                ReusableNodes.preview(group);
                const overlay = document.getElementById('reusable-preview-overlay');
                const box = document.getElementById('reusable-preview-box');
                const previewStage = document.getElementById('reusable-preview-stage');
                const preview = {
                    open: overlay.classList.contains('open'),
                    cards: previewStage.querySelectorAll('.reusable-inner-node').length,
                    inside:
                        box.getBoundingClientRect().right <= window.innerWidth + 1 &&
                        box.getBoundingClientRect().bottom <= window.innerHeight + 1,
                };
                ReusableNodes.closePreview();

                const template = canvas.nodes[group].params.template;
                const map = {};
                map[ReusableNodes.innerId(group, template.nodes[0].id)] = { status: 'done', row_count: 6 };
                map[ReusableNodes.innerId(group, template.nodes[1].id)] = { status: 'running', row_count: 0 };
                runResults.statuses = map;
                canvas.applyRunStatuses(map);
                const badge = el.querySelector('.node-run-badge');
                const groupModel = Object.keys(canvas.nodes);
                const groupConnections = canvas.connections.map((c) => [c.from, c.to]);
                const runningDots = el.querySelectorAll('.rin-status.st-running').length;
                const doneDots = el.querySelectorAll('.rin-status.st-done').length;
                const summary = el.querySelector('.node-content').textContent;

                const beforeUnwrap = Object.keys(canvas.nodes).length;
                await ReusableNodes.unwrap(group);
                await new Promise((r) => setTimeout(r, 120));
                const unwrapGroupGone = !canvas.nodes[group];
                const unwrapCount = Object.keys(canvas.nodes).length;
                canvas.undo();
                await new Promise((r) => setTimeout(r, 120));

                const result = {
                    ok: true,
                    group,
                    up,
                    down,
                    model: groupModel,
                    connections: groupConnections,
                    cards: cards.length,
                    paths: stage.querySelectorAll('path').length,
                    overlap,
                    stageInside: stage.scrollWidth <= stage.clientWidth + 1,
                    border: getComputedStyle(el).borderStyle !== 'none',
                    badge: badge ? badge.dataset.status : '',
                    runningDots,
                    doneDots,
                    preview,
                    unwrap: {
                        before: beforeUnwrap,
                        groupGone: unwrapGroupGone,
                        after: unwrapCount,
                        groupBack: !!canvas.nodes[group],
                    },
                    controls: {
                        styleStrategy: !!document.getElementById('layout-strategy'),
                        styleCheckbox: !!document.getElementById('reusable-auto-layout'),
                        toggle: !!el.querySelector('.node-reusable-toggle'),
                        insidePreview: !!el.querySelector('.node-reusable-preview'),
                    },
                    summary,
                };
                window.fetch = realFetch;
                window.showDialog = realDialog;
                done(result);
            } catch (e) {
                window.fetch = realFetch;
                window.showDialog = realDialog;
                done({ ok: false, error: String(e), stack: e && e.stack });
            }
        })();
        """,
        lang,
    )
    assert facts.get('ok') is True, facts
    assert len(facts['model']) == 3, facts['model']
    assert facts['group'] in facts['model']
    assert facts['connections'] == [
        [facts['up'], facts['group']],
        [facts['group'], facts['down']],
    ], facts['connections']
    assert facts['cards'] == 2, 'both saved nodes render inside the expanded group'
    assert facts['paths'] == 1, 'the wire between the inside nodes is painted in the stage'
    assert facts['overlap'] is False, 'inside cards may not cover each other'
    assert facts['stageInside'] is True, 'the inside stage may not overflow the group horizontally'
    assert facts['border'] is True, 'the group needs the outer border that frames its inside'
    assert facts['badge'] == 'running', 'running must win over a settled sibling'
    assert facts['runningDots'] == 1 and facts['doneDots'] == 1, facts
    assert facts['preview'] == {'open': True, 'cards': 2, 'inside': True}, facts['preview']
    assert facts['unwrap']['groupGone'] is True, facts['unwrap']
    assert facts['unwrap']['after'] == 4, facts['unwrap']  # up + down + the two inside nodes
    assert facts['unwrap']['groupBack'] is True, 'undo must restore the group as one history step'
    assert all(facts['controls'].values()), facts['controls']
    assert '2' in facts['summary'], facts['summary']


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_template_dragged_from_the_manager_lands_where_it_was_dropped(driver, app_url, lang):
    """The template tab's drag handle is a real drop source, not a decorated row.

    What only a browser settles: a real ``DragEvent`` with a real ``DataTransfer``
    carries the private MIME type from the row to the canvas, the canvas converts the
    pointer position under its current pan/zoom, and the fetched template becomes one
    reusable node whose screen box starts at the drop point. The template read is
    stubbed: this module performs no server writes.
    """
    _load_app(driver, app_url)
    facts = driver.execute_async_script(
        """
        const lang = arguments[0];
        const done = arguments[arguments.length - 1];
        document.body.dataset.lang = lang;
        I18n.apply();
        localStorage.removeItem('crawler_canvas');
        canvas.nodes = {};
        canvas.connections = [];
        canvas.selectedNodes = [];
        document.getElementById('nodes-container').innerHTML = '';
        document.getElementById('svg-layer').innerHTML = '';

        const realFetch = window.fetch;
        window.fetch = function (url, opts) {
            if (String(url).indexOf('/api/reusable/get') >= 0) {
                const name = lang === 'zh' ? '拖拽模板' : 'Dragged template';
                const payload = {
                    ok: true,
                    template: {
                        id: 'r-000000000001',
                        name,
                        description: '',
                        nodes: [
                            { id: 'a', type: 'process', title: 'A', params: {}, x: 0, y: 0, w: 220, h: 80 },
                            { id: 'b', type: 'output', title: 'B', params: {}, x: 260, y: 0, w: 220, h: 80 },
                        ],
                        connections: [{ from: 'a', to: 'b' }],
                        inputs: ['a'],
                        outputs: ['b'],
                    },
                };
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve(payload),
                    text: () => Promise.resolve(JSON.stringify(payload)),
                });
            }
            return realFetch.apply(window, arguments);
        };

        (async () => {
            try {
                const name = lang === 'zh' ? '拖拽模板' : 'Dragged template';
                document.getElementById('workflows-panel').classList.add('open');
                wfFiles._templates = [
                    {
                        id: 'r-000000000001',
                        name,
                        description: '',
                        nodes: 2,
                        connections: 1,
                        inputs: 1,
                        updated_at: '',
                        broken: false,
                    },
                ];
                wfFiles._tab = 'reusable';
                wfFiles.renderTabs();
                wfFiles.renderReusable();

                const handle = document.querySelector('#workflows-mgr-body .wf-template-drag');
                const ws = document.getElementById('workspace');
                const rect = ws.getBoundingClientRect();
                const dropX = rect.left + 500;
                const dropY = rect.top + 300;
                const dt = new DataTransfer();
                handle.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
                const carried = dt.getData('application/x-reusable-template');
                const duringCursor = getComputedStyle(handle).cursor;
                const duringClass = handle.classList.contains('dragging');
                const before = Object.keys(canvas.nodes).length;
                ws.dispatchEvent(
                    new DragEvent('drop', {
                        bubbles: true,
                        cancelable: true,
                        clientX: dropX,
                        clientY: dropY,
                        dataTransfer: dt,
                    })
                );
                for (let i = 0; i < 40 && Object.keys(canvas.nodes).length === before; i += 1) {
                    await new Promise((resolve) => setTimeout(resolve, 25));
                }
                handle.dispatchEvent(new DragEvent('dragend', { bubbles: true, cancelable: true, dataTransfer: dt }));
                const afterCursor = getComputedStyle(handle).cursor;
                const afterClass = handle.classList.contains('dragging');
                const group = Object.keys(canvas.nodes).find((id) => canvas.nodes[id].type === 'reusable');
                const el = group ? canvas._nodeEl(group) : null;
                const box = el ? el.getBoundingClientRect() : null;
                const result = {
                    ok: true,
                    handle: !!handle,
                    carried,
                    duringCursor,
                    duringClass,
                    afterClass,
                    group: !!group,
                    nodes: Object.keys(canvas.nodes).length - before,
                    name: group ? canvas.nodes[group].params.template_name : '',
                    left: box ? Math.round(box.left) : null,
                    top: box ? Math.round(box.top) : null,
                    expectedLeft: Math.round(dropX - 110),
                    expectedTop: Math.round(dropY - 40),
                    hint:
                        (document.getElementById('workflows-mgr-body').textContent || '').indexOf(
                            I18n.t('reusable.dragHint')
                        ) >= 0,
                    handleCursor: afterCursor,
                };
                window.fetch = realFetch;
                done(result);
            } catch (e) {
                window.fetch = realFetch;
                done({ ok: false, error: String(e), stack: e && e.stack });
            }
        })();
        """,
        lang,
    )
    assert facts.get('ok') is True, facts
    assert facts['handle'] is True, 'the template row must expose a drag handle'
    assert facts['carried'] == 'r-000000000001', 'the drag must carry the template id'
    assert facts['group'] is True and facts['nodes'] == 1, facts
    assert facts['name'] in ('拖拽模板', 'Dragged template'), facts
    assert abs(facts['left'] - facts['expectedLeft']) <= 2, facts
    assert abs(facts['top'] - facts['expectedTop']) <= 2, facts
    assert facts['hint'] is True, 'the manager must say that a template can be dragged'
    assert facts['duringClass'] is True and facts['duringCursor'] == 'grabbing', facts
    assert facts['afterClass'] is False and facts['handleCursor'] == 'grab', facts


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_dataset_merge_door_collects_files_and_posts_their_ids(driver, app_url, lang):
    """The dataset panel's merge selection is a real multi-select and one request.

    Only DOM can show that two row buttons update the bar, that the merge button is
    enabled by that state, and that the name dialog's answer is what the request
    carries. The server write is stubbed: this module performs no writes.
    """
    _load_app(driver, app_url)
    facts = driver.execute_async_script(
        """
        const lang = arguments[0];
        const done = arguments[arguments.length - 1];
        document.body.dataset.lang = lang;
        I18n.apply();
        const realFetch = window.fetch;
        const realDialog = window.showDialog;
        const requests = [];
        window.fetch = function (url, opts) {
            const target = String(url);
            if (target.indexOf('/api/data/merge') >= 0) {
                requests.push({ url: target, body: opts && opts.body });
                const payload = { ok: true, rows: 5, dataset: { dataset_id: 'm1', name: 'MERGED' } };
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve(payload),
                    text: () => Promise.resolve(JSON.stringify(payload)),
                });
            }
            if (target.indexOf('/api/data/datasets') >= 0) {
                const payload = { ok: true, datasets: [] };
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve(payload),
                    text: () => Promise.resolve(JSON.stringify(payload)),
                });
            }
            return realFetch.apply(window, arguments);
        };
        window.showDialog = async function (spec) {
            if (spec && spec.input) return lang === 'zh' ? '合并结果' : 'Merged';
            return spec && spec.list ? spec.list[0] : true;
        };
        (async () => {
            try {
                document.getElementById('dataset-panel').classList.add('open');
                datasetManager._compare = [];
                datasetManager._merge = [];
                datasetManager._last = [
                    { dataset_id: 'd1', name: 'A.csv', source: 'upload', row_count: 2, byte_size: 10, workflows: [] },
                    { dataset_id: 'd2', name: 'B.csv', source: 'upload', row_count: 3, byte_size: 12, workflows: [] },
                ];
                datasetManager.render();
                const body = document.getElementById('dataset-mgr-body');
                const toggles = Array.from(body.querySelectorAll('button')).filter(
                    (b) => (b.getAttribute('onclick') || '').indexOf('toggleMerge') >= 0
                );
                toggles[0].click();
                toggles[1].click();
                const barAfter = body.textContent;
                const merge = Array.from(body.querySelectorAll('button')).find(
                    (b) => (b.getAttribute('onclick') || '').indexOf('mergeSelected') >= 0
                );
                merge.click();
                for (let i = 0; i < 30 && !requests.length; i += 1) {
                    await new Promise((resolve) => setTimeout(resolve, 20));
                }
                await new Promise((resolve) => setTimeout(resolve, 40));
                const result = {
                    ok: true,
                    toggles: toggles.length,
                    bar_has_two: barAfter.indexOf('(2)') >= 0,
                    requests: requests.length,
                    body: requests.length ? JSON.parse(requests[0].body) : null,
                    toast: document.getElementById('toast').textContent,
                    selected_after: datasetManager._merge.length,
                };
                window.fetch = realFetch;
                window.showDialog = realDialog;
                done(result);
            } catch (e) {
                window.fetch = realFetch;
                window.showDialog = realDialog;
                done({ ok: false, error: String(e), stack: e && e.stack });
            }
        })();
        """,
        lang,
    )
    assert facts.get('ok') is True, facts
    assert facts['toggles'] == 2, facts
    assert facts['bar_has_two'] is True, facts
    assert facts['requests'] == 1, facts
    assert facts['body']['dataset_ids'] == ['d1', 'd2'], facts
    assert facts['body']['name'] in ('合并结果', 'Merged'), facts
    assert facts['selected_after'] == 0, facts
    assert facts['toast'], 'the merge says what it produced'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_run_comparison_row_is_drawn_from_the_server_diff(driver, app_url, lang):
    """A comparison is one request and one row beside the run, with the server's diff.

    The panel must not compute the diff itself. This drives the real compare button,
    the real dialog choice and the real row insertion with a stubbed answer, so the
    browser proves the wiring and the text; the server's computation is covered by
    the API tests.
    """
    _load_app(driver, app_url)
    facts = driver.execute_async_script(
        """
        const lang = arguments[0];
        const done = arguments[arguments.length - 1];
        document.body.dataset.lang = lang;
        I18n.apply();
        const realFetch = window.fetch;
        const realDialog = window.showDialog;
        const requests = [];
        const diff = {
            a: { run_id: 'r1', workflow_name: 'wf', status: 'completed' },
            b: { run_id: 'r2', workflow_name: 'wf', status: 'completed' },
            same_workflow: true,
            same_shape: true,
            nodes: [
                {
                    node_id: 'node-0',
                    title: 'Output',
                    status_a: 'done',
                    status_b: 'done',
                    rows_a: 1,
                    rows_b: 2,
                    row_delta: 1,
                },
            ],
            node: { node_id: 'node-0', title: 'Output', rows_a: 1, rows_b: 2, row_delta: 1 },
            diff: {
                added_count: 1,
                removed_count: 1,
                changed_count: 0,
                columns_common: ['title'],
                columns_added: [],
                columns_removed: [],
                added: [{ title: 'NEW-ROW' }],
                removed: [{ title: 'OLD-ROW' }],
            },
        };
        window.fetch = function (url, opts) {
            if (String(url).indexOf('/api/runs/compare') >= 0) {
                requests.push(String(url));
                const payload = { ok: true, diff };
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve(payload),
                    text: () => Promise.resolve(JSON.stringify(payload)),
                });
            }
            return realFetch.apply(window, arguments);
        };
        window.showDialog = async function (spec) {
            return spec && spec.list ? spec.list[0] : true;
        };
        (async () => {
            try {
                runsManager._tab = 'workflow';
                runsManager._queue = [];
                runsManager._detail = null;
                runsManager._compare = null;
                const rows = [
                    {
                        run_id: 'r1',
                        workflow_name: 'wf',
                        status: 'completed',
                        node_done: 1,
                        node_total: 1,
                        rows_kept: 1,
                        started_at: '2026-10-26 10:00',
                        duration_seconds: 2,
                        wf_count: 1,
                        mode: 'serial',
                        headless: true,
                        resumable: false,
                    },
                    {
                        run_id: 'r2',
                        workflow_name: 'wf',
                        status: 'completed',
                        node_done: 1,
                        node_total: 1,
                        rows_kept: 2,
                        started_at: '2026-10-26 10:05',
                        duration_seconds: 2,
                        wf_count: 1,
                        mode: 'serial',
                        headless: true,
                        resumable: false,
                    },
                ];
                runsManager.render(rows);
                const compareButton = Array.from(document.querySelectorAll('#runs-mgr-body button')).find(
                    (b) => (b.getAttribute('onclick') || '').indexOf("runsManager.compare('r1')") >= 0
                );
                compareButton.click();
                for (let i = 0; i < 30 && !requests.length; i += 1) {
                    await new Promise((resolve) => setTimeout(resolve, 20));
                }
                await new Promise((resolve) => setTimeout(resolve, 40));
                const row = document.getElementById('runs-mgr-compare');
                const html = row ? row.innerHTML : '';
                const close = row ? row.querySelector('button') : null;
                if (close) close.click();
                await new Promise((resolve) => setTimeout(resolve, 30));
                const result = {
                    ok: true,
                    requests,
                    row: !!row,
                    html,
                    added: html.indexOf(I18n.t('runsMgr.compareAdded')) >= 0,
                    old: html.indexOf('OLD-ROW') >= 0,
                    new_row: html.indexOf('NEW-ROW') >= 0,
                    closed: !document.getElementById('runs-mgr-compare'),
                };
                window.fetch = realFetch;
                window.showDialog = realDialog;
                done(result);
            } catch (e) {
                window.fetch = realFetch;
                window.showDialog = realDialog;
                done({ ok: false, error: String(e), stack: e && e.stack });
            }
        })();
        """,
        lang,
    )
    assert facts.get('ok') is True, facts
    assert facts['requests'] == ['/api/runs/compare?a=r1&b=r2'], facts
    assert facts['row'] is True and facts['added'] is True, facts
    assert facts['old'] is True and facts['new_row'] is True, facts
    assert facts['closed'] is True, 'closing the comparison removes its row'


def test_the_shipped_page_draws_its_figures_without_asking_anything_off_this_machine(app_url, driver):
    """A double-clicked desktop app has to draw on a machine with no network.

    Every figure on this UI is drawn by a bundle the app serves itself (``/vendor``), over basemaps
    it ships (``/geo``), with the interface face in the same folder. Until that was true, a machine
    without internet — or one whose network resets a given CDN host, which this project has measured
    for ``raw.githubusercontent.com`` — showed an empty figure area and said nothing about why.

    This is the proof from a real browser rather than a claim about code: not one network resource
    left the origin, both shipped basemaps register, and the shipped webfont is the face the page
    actually loaded. The count of measured resources is reported because "no foreign request" from a
    page that loaded nothing would pass for the wrong reason.
    """
    driver.set_window_size(1366, 768)
    _load_app(driver, app_url)
    facts = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const origin = location.origin;
        const entries = performance.getEntriesByType('resource').map((entry) => entry.name);
        // An inlined data: URI never left the process, so it is not a network request.
        const foreign = entries.filter((name) =>
            name.indexOf(origin) !== 0 && name.indexOf('data:') !== 0);
        Promise.all([ensureMapRegistered('china'), ensureMapRegistered('world_zh'), document.fonts.ready])
            .then((answers) => {
                const faces = Array.from(document.fonts)
                    .filter((face) => face.family === 'Literata' && face.status === 'loaded');
                done({
                    origin: origin,
                    resources: entries.length,
                    foreign: foreign,
                    china: answers[0],
                    world: answers[1],
                    chinaRegistered: !!echarts.getMap('china'),
                    worldRegistered: !!echarts.getMap('world_zh'),
                    faces: faces.length,
                    library: typeof echarts !== 'undefined' && !!echarts.init,
                });
            }, (error) => done({ error: String(error) }));
        """
    )
    assert 'error' not in facts, facts
    assert facts['library'] is True, 'the chart library is not on the page at all'
    assert facts['resources'] >= 8, f'only {facts["resources"]} resources measured — the page did not load'
    assert facts['foreign'] == [], f'requests that left the origin: {facts["foreign"]}'
    assert facts['china'] == '', f'china basemap refused: {facts["china"]}'
    assert facts['chinaRegistered'] is True
    assert facts['world'] == '', f'world basemap refused: {facts["world"]}'
    assert facts['worldRegistered'] is True
    assert facts['faces'] >= 1, 'the vendored webfont never loaded'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_a_server_without_a_desktop_hides_the_windows_only_controls_and_greys_the_mode(app_url, driver, lang):
    """What the machine verdict does to the page, measured in a real layout engine.

    The node harness can prove the JS decides correctly; only a browser can prove the CSS rule that
    consumes the flag actually removes the four 红果 harvest rows from the settings panel — a row that
    is "hidden" by a selector that does not match is still on screen, and a Windows-only path setting
    offered on a Linux server is exactly the advice nobody can follow. The same payload has to leave
    the 采集内容 option LISTED but disabled: the node stores that mode, and an absent option would paint
    the platform's first mode instead, which is a panel lying about what the run would do.
    """
    _load_app(driver, app_url)
    # The matrix arrives asynchronously, and the panel is BUILT from it: asking for the mode select
    # before the answer lands measures nothing (and used to throw on ``undefined.length``). Bounded, and
    # named if it never arrives — a test that silently skips a load race proves nothing about the race.
    deadline = time.time() + 20
    while not driver.execute_script('return !!(window.Capabilities && Capabilities.ready());'):
        if time.time() > deadline:
            pytest.fail('/api/capabilities never loaded, so the mode select was never rendered')
        time.sleep(0.1)
    facts = driver.execute_script(
        """
        const lang = arguments[0];
        document.body.dataset.lang = lang;
        I18n.apply();
        const rows = Array.from(document.querySelectorAll('.windows-only'));
        const display = () => rows.map((el) => getComputedStyle(el).display);
        const before = display();
        Machine.apply({ machine: { windows_desktop: false } });
        const after = display();
        const flag = document.documentElement.dataset.winDesktop;
        Capabilities.data = Object.assign({}, Capabilities.data, { machine: { windows_desktop: false } });
        canvas.nodes = {};
        canvas.connections = [];
        document.getElementById('nodes-container').innerHTML = '';
        const id = canvas.addNode('source', 200, 200);
        canvas.nodes[id].platform = 'hongguo';
        canvas.nodes[id].params.platform = 'hongguo';
        canvas.nodes[id].params.collect = 'comments';
        openSettings(id);
        const selects = Array.from(document.querySelectorAll('#settings-content select'));
        const modeSel = selects.find((s) =>
            Array.from(s.options).some((o) => o.value === 'comments'));
        const options = modeSel
            ? Array.from(modeSel.options).map((o) => ({
                value: o.value, disabled: o.disabled, text: o.textContent.trim(),
            }))
            : null;
        Machine.apply({ machine: { windows_desktop: true } });
        const restored = display();
        return { rows: rows.length, before, after, restored, flag, options };
        """,
        lang,
    )
    assert facts['rows'] == 4, f'the desktop-only rows are not the four declared ones: {facts["rows"]}'
    assert all(value != 'none' for value in facts['before']), facts['before']
    assert all(value == 'none' for value in facts['after']), f'CSS did not remove them: {facts["after"]}'
    assert all(value != 'none' for value in facts['restored']), 'the flag must not hide them for good'
    assert facts['flag'] == '0'
    assert facts['options'], 'the 采集内容 select never rendered, so nothing about the option was measured'
    harvest = next((o for o in facts['options'] if o['value'] == 'comments'), None)
    assert harvest and harvest['disabled'] is True, facts['options']
    reason = '桌面版' if lang == 'zh' else 'Windows desktop'
    assert reason in harvest['text'], f'the greyed option says nothing about why: {harvest["text"]}'
    board = next((o for o in facts['options'] if o['value'] == 'hot'), None)
    assert board and board['disabled'] is False, 'a browser crawl must not be collateral damage'


@pytest.mark.parametrize('lang', ['zh', 'en'])
def test_the_crawl_panel_offers_platform_then_engine_then_function(app_url, driver, lang):
    """The engine dimension, measured where the selects are actually laid out.

    ``harness_capabilities.mjs`` drives the same handlers in node, but ordering, option text and a
    greyed engine's reason are DOM facts: the panel must read 平台 → 引擎 → 功能 top to bottom, the
    engine list must be the server's ``engines`` list in ITS order (not a list typed here), and a
    stored engine the adapter no longer offers must stay on screen, disabled and named — replacing
    it behind the user's back is the silent fallback this dimension exists to prevent.

    The server this tier boots has whatever adapter the machine has (none on CI), so the test
    measures every platform the payload gives at least one engine to, and exercises the switch on
    the first one that offers two available engines — zero such platforms is stated, not hidden.
    """
    driver.set_window_size(1650, 1080)
    _load_app(driver, app_url)
    _kill_animations(driver)
    facts = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const lang = arguments[0];
        (async () => {
            document.body.dataset.lang = lang;
            I18n.apply();
            for (let i = 0; i < 200 && !Capabilities.ready(); i++) await new Promise((r) => setTimeout(r, 50));
            if (!Capabilities.ready()) return done({ error: 'capabilities never loaded' });
            localStorage.removeItem('crawler_canvas');
            canvas.nodes = {};
            canvas.connections = [];
            document.getElementById('nodes-container').innerHTML = '';
            const id = canvas.addNode('source', 200, 120);
            const waitFor = async (fn) => {
                for (let i = 0; i < 200; i++) {
                    const value = fn();
                    if (value) return value;
                    await new Promise((r) => setTimeout(r, 25));
                }
                return null;
            };
            openSettings(id);
            if (!(await waitFor(() => document.querySelector('select[onchange^="setSourceBackend"]')))) {
                return done({ error: 'the engine select never rendered' });
            }
            const read = (select) =>
                Array.from(select.options).map((o) => ({
                    value: o.value,
                    text: o.textContent.trim(),
                    disabled: o.disabled,
                }));
            const measured = [];
            let switched = null;
            for (const entry of Capabilities.platforms()) {
                const platform = entry.platform;
                const engines = Capabilities.engines(platform);
                if (!engines.length) continue;
                /* Each switch repaints #settings-content, so every element is re-queried: a select
                   captured before the repaint is detached and answers by value, which made the next
                   platform read the previous panel. The settle condition names the platform. */
                const pick = document
                    .getElementById('settings-content')
                    .querySelector('select[onchange^="selectSourcePlatform"]');
                if (!pick) return done({ error: 'the platform select never rendered' });
                pick.value = platform;
                pick.dispatchEvent(new Event('change'));
                const engineSel = await waitFor(() => {
                    const panel = document.getElementById('settings-content');
                    const fresh = panel.querySelector('select[onchange^="selectSourcePlatform"]');
                    const engine = panel.querySelector('select[onchange^="setSourceBackend"]');
                    return fresh && fresh.value === platform && engine ? engine : null;
                });
                if (!engineSel) return done({ error: 'the panel never settled on ' + platform });
                const platformSel = document
                    .getElementById('settings-content')
                    .querySelector('select[onchange^="selectSourcePlatform"]');
                const options = read(engineSel);
                const platformBox = platformSel.getBoundingClientRect();
                const engineBox = engineSel.getBoundingClientRect();
                const backend = String(canvas.nodes[id].params.backend || '') || Capabilities.defaultBackend(platform);
                const offered = Capabilities.modes(platform, backend);
                const modeSel = document.querySelector("select[onchange*=\\"'collect'\\"]");
                const modeBox = modeSel ? modeSel.getBoundingClientRect() : null;
                measured.push({
                    platform,
                    offered: offered.length,
                    modeSelect: !!modeSel,
                    options,
                    expected: engines.map((e) => ({
                        value: e.key,
                        text: I18n.t(e.labelKey) +
                            (e.available === false
                                ? '（' + I18n.t(e.reasonKey || 'settings.backendProbeFailed') + '）'
                                : ''),
                        disabled: e.available === false,
                    })),
                    /* One mode is not a choice, so the panel renders no function select for it
                       («WeChat offers a single form»); the order claim then stops at the engine. */
                    order: modeBox
                        ? platformBox.top < engineBox.top && engineBox.top < modeBox.top
                        : platformBox.top < engineBox.top,
                });
                const available = engines.filter((e) => e.available !== false);
                if (!switched && engines.length > 1 && available.length > 1) {
                    const next = available[available.length - 1].key;
                    engineSel.value = next;
                    engineSel.dispatchEvent(new Event('change'));
                    const wantModes = Capabilities.modes(platform, next).map((m) => m.key);
                    const fresh = await waitFor(() => {
                        const panel = document.getElementById('settings-content');
                        const settled = panel.querySelector('select[onchange^="selectSourcePlatform"]');
                        const mode = panel.querySelector("select[onchange*=\\"'collect'\\"]");
                        if (!settled || settled.value !== platform) return null;
                        return wantModes.length > 1 ? mode : panel;
                    });
                    switched = {
                        platform,
                        engine: next,
                        stored: canvas.nodes[id].params.collect,
                        expectedStored: wantModes[0] || '',
                        modeKeys: wantModes.length > 1 && fresh ? read(fresh).map((o) => o.value) : [],
                        expectedModes: wantModes,
                        modeSelect: wantModes.length > 1 ? !!fresh : false,
                    };
                }
            }
            return done({ measured, switched });
        })();
        """,
        lang,
    )
    assert 'error' not in facts, facts.get('error')
    assert facts['measured'], 'no platform was offered an engine, so nothing about the dimension was measured'
    for row in facts['measured']:
        got = [(o['value'], o['text'], o['disabled']) for o in row['options']]
        want = [(e['value'], e['text'], e['disabled']) for e in row['expected']]
        assert got == want, f'{row["platform"]}: the engine select is not the server list: {got} vs {want}'
        for option in row['options']:
            assert option['text'] and not option['text'].startswith('engine.'), (
                f'{row["platform"]}: an engine option printed its catalogue key: {option}'
            )
        assert row['modeSelect'] == (row['offered'] > 1), (
            f'{row["platform"]}: a function select exists iff there is a choice '
            f'(offered={row["offered"]}, select={row["modeSelect"]})'
        )
        assert row['order'] is True, f'{row["platform"]}: the panel is not 平台 → 引擎 → 功能 top to bottom'
    if facts['switched']:
        row = facts['switched']
        assert row['stored'] == row['expectedStored'], (
            f'{row["platform"]}: switching to {row["engine"]} left the stored mode off that engine: {row}'
        )
        if row['expectedModes'] and len(row['expectedModes']) > 1:
            assert row['modeSelect'] is True, f'{row["platform"]}: the new engine has a choice but no select: {row}'
            assert row['modeKeys'] == row['expectedModes'], (
                f"{row['platform']}: the function list is not the new engine's list: {row}"
            )
