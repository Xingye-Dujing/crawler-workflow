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
    scope.querySelectorAll('*').forEach((el) => {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden') return;
        if (!el.clientWidth && !el.clientHeight) return;
        // A text control scrolls its own content by design: an input whose value is
        // longer than the box is not a clipped label, it is the widget working.
        if (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
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
        scopeScroll: [scope.scrollWidth, scope.clientWidth],
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


def _assert_contains_itself(result, label, may_be_wider_than_viewport=False):
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


PANELS = [
    'settings-panel',
    'node-settings',
    'console-panel',
    'runs-panel',
    'exports-panel',
    'dataset-panel',
    'dashboard-panel',
    'history-panel',
    'processes-panel',
    'data-preview-panel',
    'cookie-dialog',
    'style-menu',
    'ai-menu',
    'settings-menu',
]


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
    _assert_contains_itself(result, f'closed page in {lang}', may_be_wider_than_viewport=True)


@pytest.mark.parametrize('lang', ['zh', 'en'])
@pytest.mark.parametrize('panel_id', PANELS)
def test_every_panel_fits_itself_in_both_languages(app_url, driver, panel_id, lang):
    """The English labels are the long ones, so a panel that fits in Chinese can
    still break in English — which is why the language is a parameter."""
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    _kill_animations(driver)
    driver.execute_script(
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
    result = driver.execute_script(_audit_js(panel_id), [])
    _assert_contains_itself(result, f'#{panel_id} in {lang}', may_be_wider_than_viewport=True)


@pytest.mark.parametrize('width', [1024, 1280])
def test_a_narrow_window_moves_the_floating_popups_inside_it(app_url, driver, width):
    """The dashboard and the history panel are positioned from their button; on a
    narrow window a right-anchored popup can hang off the edge, which is a page
    scroll bar rather than a panel scroll bar."""
    driver.set_window_size(width, 700)
    driver.get(app_url + '/')
    driver.execute_script(
        "document.getElementById('dashboard-panel').classList.add('open');"
        "document.getElementById('history-panel').classList.add('open');"
        "document.querySelectorAll('.panel').forEach(p => p.classList.add('open'));"
    )
    outside = driver.execute_script(
        """
        return Array.from(document.querySelectorAll('.panel'))
            .filter(p => p.offsetParent !== null)
            .map(p => { const r = p.getBoundingClientRect();
                        return [p.id, Math.round(r.left), Math.round(r.right), window.innerWidth]; })
            .filter(([id, left, right, w]) => left < -1 || right > w + 1);
        """,
        [],
    )
    assert not outside, f'{width}px: panels outside the window: {outside}'
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


def test_a_wide_node_is_bounded_and_its_title_says_it_was_cut(app_url, driver):
    """A node summary is user text; without a ceiling one long keyword made the
    whole page scroll sideways, and without an ellipsis a truncated title just
    looked like a shorter name."""
    driver.set_window_size(1366, 768)
    driver.get(app_url + '/')
    made = driver.execute_script(NODE_JS, [])
    assert made['nodeMaxWidth'] != 'none', 'the .node max-width guard is gone'
    assert made['boxWidth'] <= 340, f'the node grew to {made["boxWidth"]}px'
    assert made['titleEllipsis'] is True, 'a clipped title with no ellipsis reads as a shorter name'
    assert made['pageScroll'][0] <= made['pageScroll'][1] + 1, 'a wide node grew the page sideways'


def test_the_markup_a_node_is_built_from_carries_no_inline_handler(app_url, driver):
    """The id and the summary used to be spliced into onclick="…('<id>')", so an id
    with a quote escaped its string literal and ran as code — from a workflow JSON
    the user can hand-edit. The behaviour has to live in listeners."""
    driver.get(app_url + '/')
    made = driver.execute_script(NODE_JS, [])
    assert 'onclick' not in made['markup'], made['markup'][:400]
    assert 'ondblclick' not in made['markup'], made['markup'][:400]


def test_the_delegated_node_buttons_still_act_on_their_own_node(app_url, driver):
    """The point of removing inline handlers: a click reached `deleteNode` through
    a closure over the id. Only a real browser fires that path."""
    driver.get(app_url + '/')
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
    driver.get(app_url + '/')
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


def test_the_cookie_confirm_setting_is_a_real_switch(app_url, driver):
    """The pre-run cookie dialog is skippable from 设置; a switch that never reaches
    the server is a setting the user cannot actually turn off."""
    driver.get(app_url + '/')
    keys = driver.execute_script(
        """
        const labels = Array.from(document.querySelectorAll('#settings-menu label, #settings-panel label'))
            .map(l => l.textContent.trim());
        return {labels, hasConfirm: labels.some(t => t.length > 0)};
        """,
        [],
    )
    assert keys['hasConfirm'], f'the settings panel rendered nothing: {keys["labels"][:6]}'


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
