"""Screenshot helper for docs/manual.

It drives the running app with Selenium and writes PNGs into docs/manual/img.
Nothing here hardcodes a Windows path: Chrome and its driver come from the
environment (CIXI_DRIVER_PATH / CHROME_BIN), and Selenium's own lookup is used
when they are unset.

Usage (the app must be running, default http://127.0.0.1:5000):

    python docs/manual/shots/capture.py canvas   --workflow "测试：图表可视化" --out zh-canvas
    python docs/manual/shots/capture.py panels   --workflow "刘学州-评论-情感演化分析-BERT" --out liu --types analysis --limit 1
    python docs/manual/shots/capture.py dock     --out runs --panel runs
    python docs/manual/shots/capture.py chart    --workflow "刘学州-评论-情感演化分析-BERT" --out liu-chart --node-type visualize
    python docs/manual/shots/capture.py fullscreen --workflow "刘学州-评论-情感演化分析-BERT" --out liu-zoom --node-type visualize
    python docs/manual/shots/capture.py dashboard --workflow "刘学州-评论-情感演化分析-BERT" --out liu-board
    python docs/manual/shots/capture.py menus    --out style --panel style
    python docs/manual/shots/capture.py outline  --workflow "刘学州-评论-情感演化分析-BERT" --out liu-outline

    python docs/manual/shots/capture.py --batch                 # every figure the book cites
    python docs/manual/shots/capture.py --batch --only hg-canvas,dark

Every mode sets the light theme first (the manual is printed on paper), lays the
canvas out with canvas.autoLayout(), fits it with canvas.resetView(), and takes
an element screenshot for panels so the crop is tight and the text stays large.

``--batch`` runs the whole figure list in ONE browser session, reloading the page
between figures: state left by the previous figure is what put a stale 数据预览
panel behind the shortcuts help card the first time this was tried by hand. Each
figure is one entry of :data:`RECIPES`; :data:`KEPT` names the figures that cannot
be shot from this checkout and says why, so a later edit knows what it is standing on.

Side effect to undo afterwards: opening a workflow makes the SERVER persist the
canvas view and node positions, so a batch rewrites ``data/workflows/*.json``.
Restore it with ``git checkout -- data/workflows`` once the pictures are taken.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'img'))


def build_driver(url: str) -> webdriver.Chrome:
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--hide-scrollbars')
    options.add_argument('--force-device-scale-factor=2')
    options.add_argument('--window-size=1600,1000')
    if os.environ.get('CHROME_BIN'):
        options.binary_location = os.environ['CHROME_BIN']
    service = Service(os.environ.get('CIXI_DRIVER_PATH') or None)
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_window_size(1600, 1000)
    # Paper-white rendering, whatever the desktop theme is.
    driver.execute_cdp_cmd(
        'Emulation.setEmulatedMedia',
        {'features': [{'name': 'prefers-color-scheme', 'value': 'light'}]},
    )
    driver.get(url)
    time.sleep(9)
    return driver


def js(driver, code, *args):
    try:
        return driver.execute_script(code, *args)
    except Exception as exc:  # a missing optional panel must not abort a batch
        print('js failed:', code[:60], exc)
        return None


def hide_toast(driver):
    js(
        driver,
        "var s=document.createElement('style');"
        "s.textContent='#toast{display:none !important}';"
        'document.head.appendChild(s);',
    )


def open_workflow(driver, name: str):
    js(driver, 'workflow._loadByName(arguments[0])', name)
    time.sleep(7)
    js(driver, 'try{canvas.autoLayout();}catch(e){}')
    time.sleep(1.2)
    js(driver, 'canvas.resetView()')
    time.sleep(1.5)


def hydrate_results(driver):
    """Load the newest stored run of this canvas, so panels preview real rows.

    Opening a workflow paints node verdicts from the ledger, but the chart and the
    table previews read the loaded run; without this every panel says "先跑一次".
    """
    run_id = js(
        driver,
        'var wf = canvas.toWorkflowJSON();'
        'var r = await (await fetch("/api/runs/for-workflow", {method: "POST",'
        ' headers: {"Content-Type": "application/json"},'
        ' body: JSON.stringify({workflow: wf, limit: 50})})).json();'
        'return (r.ok && r.runs && r.runs[0]) ? r.runs[0].run_id : "";',
    )
    if run_id:
        js(driver, 'return runResults.load(arguments[0])', run_id)
        time.sleep(3)
        print('loaded run', run_id)
    else:
        print('no stored run for this canvas')
    return run_id


def save_window(driver, name: str):
    path = os.path.join(OUT, name + '.png')
    driver.save_screenshot(path)
    print('wrote', path)


def save_element(driver, selector: str, name: str):
    path = os.path.join(OUT, name + '.png')
    try:
        driver.find_element(By.CSS_SELECTOR, selector).screenshot(path)
        print('wrote', path)
    except Exception as exc:
        print('element shot failed', selector, exc)


def node_types(driver):
    return js(
        driver,
        'return Object.values(canvas.nodes).map(n=>({id:n.id,type:n.type,'
        'title:(n.params||{}).workflow_name||n.title,params:n.params||{}}))',
        [],
    )


def pick_node(driver, type_name: str, want_chart: bool = False):
    nodes = node_types(driver) or []
    for node in nodes:
        if type_name and node['type'] != type_name:
            continue
        if want_chart and not (node['params'] or {}).get('chart_type'):
            continue
        return node
    return nodes[0] if nodes else None


def mode_canvas(driver, args):
    open_workflow(driver, args.workflow)
    save_window(driver, args.out)


def mode_panels(driver, args):
    open_workflow(driver, args.workflow)
    nodes = node_types(driver) or []
    wanted = args.types.split(',') if args.types else ['source', 'process', 'analysis', 'visualize', 'upload', 'output']
    taken = 0
    for node in nodes:
        if node['type'] not in wanted:
            continue
        js(driver, 'openSettings(arguments[0])', node['id'])
        time.sleep(1.8)
        save_element(driver, '#node-settings', '%s-%s' % (args.out, node['id']))
        js(driver, 'closeSettings()')
        time.sleep(0.8)
        taken += 1
        if args.limit and taken >= args.limit:
            break


def mode_dock(driver, args):
    selector = {
        'runs': '#btn-runs',
        'exports': '#btn-exports',
        'datasets': '#btn-datasets',
        'schedules': '#btn-schedules-dock',
        'biblio': '#btn-biblio-dock',
        'lexicon': '#btn-lexicon',
        'cookies': '#btn-cookies',
        'processes': '#btn-processes',
        'workflows': '#btn-workflows',
        'console': '#btn-console',
    }[args.panel]
    js(driver, "document.getElementById('%s').click()" % selector[1:])
    time.sleep(4)
    if args.panel == 'runs':
        js(driver, "try{runsManager.switchTab('all')}catch(e){}")
        time.sleep(2)
    save_window(driver, args.out)


def mode_cookies(driver, args):
    js(driver, "document.getElementById('btn-cookies').click()")
    time.sleep(3)
    save_window(driver, args.out)


def mode_theme(driver, args):
    js(driver, "if(typeof setTheme==='function') setTheme('dark')")
    time.sleep(3)
    save_window(driver, args.out)


def mode_outline(driver, args):
    open_workflow(driver, args.workflow)
    save_element(driver, '#outline-panel', args.out)


def mode_menus(driver, args):
    table = {
        'style': ('toggleStyleMenu()', '#style-menu'),
        'ai': ('toggleAiMenu()', '#ai-menu'),
        'settings': ('toggleSettingsMenu()', '#settings-menu'),
        'help': ('openShortcutsHelp()', '#help-overlay'),
        'clipboard': ('toggleClipboardDrawer()', '#clipboard-drawer'),
    }
    opener, selector = table[args.panel]
    js(driver, opener)
    time.sleep(2)
    save_element(driver, selector, args.out)


def mode_chart(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    node = pick_node(driver, args.node_type, want_chart=True)
    js(driver, 'dataNodes.previewVisualize(arguments[0])', node['id'])
    time.sleep(5)
    save_element(driver, '#chart-preview-panel', args.out)


def mode_fullscreen(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    node = pick_node(driver, args.node_type, want_chart=True)
    js(driver, 'openChartFullscreen(arguments[0])', node['id'])
    time.sleep(6)
    save_element(driver, '#chart-fullscreen-panel', args.out)


def mode_dashboard(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    js(driver, 'dashboard.open()')
    time.sleep(10)
    save_element(driver, '#dashboard-panel', args.out)


def mode_dashboardzoom(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    js(driver, 'dashboard.open()')
    time.sleep(10)
    node = pick_node(driver, args.node_type, want_chart=True)
    js(driver, 'openChartFullscreen(arguments[0])', node['id'])
    time.sleep(6)
    save_window(driver, args.out)


def scroll_preview_to_results(driver):
    """Push the preview table to its last columns.

    A step's OUTPUT columns are appended at the right end of the table (``评论`` keeps its place, the
    label and the score land after it). The panel opens at ``scrollLeft = 0``, so a figure shot without
    this scroll shows only the inputs — the exact mismatch ch02b's "预览数据" step kept having.
    """
    js(
        driver,
        "var w=document.getElementById('data-preview-table-wrap');"
        'if(!w) return null; w.scrollLeft = w.scrollWidth;'
        'return [w.scrollWidth, w.clientWidth];',
    )
    time.sleep(1.0)


def mode_datapreview(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    node = pick_node(driver, args.node_type)
    js(driver, 'dataNodes.previewData(arguments[0])', node['id'])
    time.sleep(5)
    if getattr(args, 'scroll', '') == 'right':
        scroll_preview_to_results(driver)
    save_element(driver, '#data-preview-panel', args.out)


def mode_stats(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    js(driver, 'toggleStats()')
    time.sleep(4)
    save_element(driver, '#stats-panel', args.out)


def mode_history(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    js(driver, 'historyPanel.open()')
    time.sleep(5)
    save_element(driver, '#history-panel', args.out)


def mode_studio(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    node = pick_node(driver, args.node_type, want_chart=True)
    js(driver, 'chartStudio.openForNode(arguments[0])', node['id'])
    time.sleep(12)
    save_window(driver, args.out)


MODES = {
    'canvas': mode_canvas,
    'panels': mode_panels,
    'dock': mode_dock,
    'cookies': mode_cookies,
    'theme': mode_theme,
    'outline': mode_outline,
    'menus': mode_menus,
    'chart': mode_chart,
    'fullscreen': mode_fullscreen,
    'dashboard': mode_dashboard,
    'dashboardzoom': mode_dashboardzoom,
    'datapreview': mode_datapreview,
    'stats': mode_stats,
    'history': mode_history,
    'studio': mode_studio,
    'zoom': None,  # filled in below; kept out of the table literal so the order reads as the manual does
}


# ─── Batch: the book's whole figure list in one browser ───
HG = '红果短剧-四个热播榜'
HGT = '红果短剧-热榜转评论'
WB = '测试：微博'
DY = '测试：抖音'
ZH = '测试：图表可视化'
BIB = 'AIGC文献计量（知网自动采集3000篇·去重清洗）'
LIU = '刘学州-评论-情感演化分析-BERT'
#: ch02b's walkthrough canvas (name → upload → 情感极性 → 柱状图), shipped beside the book so the
#: chapter's four figures can be shot again instead of being kept as stale copies.
DEMO = '示例评论情感'

#: ``(file stem written to img/, kind, arguments)``, in the order the book reads them. ``kind`` is
#: the same small set of gestures the single-shot modes offer, so a figure that needs one-off handling
#: is a new kind here rather than a second script outside the repo.
RECIPES = (
    ('hg-canvas', 'canvas', {'workflow': HG}),
    ('hg-source', 'settings', {'workflow': HG, 'want': {'board': 'hot_drama'}}),
    ('hg-data', 'datapreview', {'workflow': HG, 'node_type': 'source', 'want': {'board': 'hot_drama'}}),
    ('hg-talk-canvas', 'canvas', {'workflow': HGT}),
    ('hg-talk-source', 'settings', {'workflow': HGT, 'node_type': 'source'}),
    ('wb-canvas', 'canvas', {'workflow': WB}),
    ('wb-keyword', 'settings', {'workflow': WB, 'node_type': 'source', 'want': {'collect': 'posts'}}),
    ('wb-comment', 'settings', {'workflow': WB, 'node_type': 'source', 'want': {'collect': 'comments'}}),
    ('dy-canvas', 'canvas', {'workflow': DY}),
    ('dy-sentiment', 'settings', {'workflow': DY, 'node_type': 'process'}),
    ('zh-canvas', 'canvas', {'workflow': ZH}),
    ('zh-visualize', 'settings', {'workflow': ZH, 'node_type': 'visualize'}),
    ('panel-visualize', 'settings', {'workflow': ZH, 'node_type': 'visualize'}),
    ('panel-source', 'settings', {'workflow': HG, 'want': {'board': 'hot_drama'}}),
    ('panel-upload', 'settings', {'workflow': LIU, 'node_type': 'upload'}),
    ('panel-analysis', 'settings', {'workflow': LIU, 'node_type': 'analysis', 'want': {'operation': 'filter_rows'}}),
    ('panel-output', 'settings', {'workflow': LIU, 'node_type': 'output'}),
    ('panel-process', 'settings', {'workflow': LIU, 'node_type': 'process', 'want': {'mode': 'bert'}}),
    ('liu-stage', 'settings', {'workflow': LIU, 'node_type': 'analysis', 'want': {'operation': 'bin_time'}}),
    ('liu-topicmap', 'settings', {'workflow': LIU, 'node_type': 'analysis', 'want': {'operation': 'topic_map'}}),
    (
        'liu-evolution',
        'settings',
        {'workflow': LIU, 'node_type': 'analysis', 'want': {'operation': 'sentiment_evolution'}},
    ),
    ('liu-alert', 'settings', {'workflow': LIU, 'node_type': 'analysis', 'want': {'operation': 'alert'}}),
    ('bib-canvas', 'canvas', {'workflow': BIB}),
    ('bib-node', 'settings', {'workflow': BIB, 'node_type': 'biblio'}),
    ('bib-graph', 'settings', {'workflow': BIB, 'node_type': 'visualize', 'want': {'chart_type': 'knowledge_graph'}}),
    ('outline', 'element', {'workflow': LIU, 'selector': '#outline-panel'}),
    ('shortcuts', 'menu', {'opener': 'openShortcutsHelp()', 'selector': '#help-box'}),
    ('clipboard', 'menu', {'opener': 'toggleClipboardDrawer()', 'selector': '#clipboard-drawer'}),
    ('style-menu', 'menu', {'opener': 'toggleStyleMenu()', 'selector': '#style-menu'}),
    ('ai-menu', 'menu', {'opener': 'toggleAiMenu()', 'selector': '#ai-menu'}),
    ('settings-menu', 'menu', {'opener': 'toggleSettingsMenu()', 'selector': '#settings-menu'}),
    ('node-closeup', 'node_element', {'workflow': HG, 'want': {'board': 'hot_drama'}}),
    ('console', 'dock', {'button': 'btn-console'}),
    ('run-log', 'runlog', {}),
    ('demo-canvas', 'canvas', {'workflow': DEMO}),
    ('demo-chart', 'chart', {'workflow': DEMO, 'want': {'chart_type': 'bar'}}),
    # 结果列在表格最右边：不横向滚到底，图里只有输入列（ch02b 那处图文不符就是这么来的）
    ('data-preview', 'datapreview', {'workflow': DEMO, 'node_type': 'process', 'scroll': 'right'}),
    # The three account-scoped docks need a SIGNED-IN server to show rows; on a bare one they are the
    # empty state. Their captions promise a table, so a signed-in pass is what to run before shipping.
    ('runs-panel', 'dock', {'button': 'btn-runs'}),
    ('runs', 'dock', {'button': 'btn-runs', 'row': 'tr[data-run-id]'}),
    ('datasets', 'dock', {'button': 'btn-datasets'}),
    ('exports', 'dock', {'button': 'btn-exports'}),
    ('exports-panel', 'dock', {'button': 'btn-exports'}),
    ('workflows', 'dock', {'button': 'btn-workflows'}),
    ('schedules', 'dock', {'button': 'btn-schedules-dock'}),
    ('lexicon', 'dock', {'button': 'btn-lexicon'}),
    ('cookies', 'dock', {'button': 'btn-cookies'}),
    ('cookie-dialog', 'cookie_dialog', {}),
    ('chart-preview', 'chart', {'workflow': LIU, 'want': {'chart_type': 'line'}}),
    ('dashboard', 'dashboard', {'workflow': LIU}),
    ('dashboard-zoom', 'dashboardzoom', {'workflow': LIU, 'want': {'chart_type': 'line'}}),
    ('dark', 'dark', {'workflow': ZH}),
    ('liu-zoom-clean', 'zoom', {'workflow': LIU, 'ids': ('node-5', 'node-6', 'node-7', 'node-8', 'node-9')}),
    (
        'liu-zoom-stage',
        'zoom',
        {'workflow': LIU, 'ids': ('node-12', 'node-13', 'node-16', 'node-19', 'node-35', 'node-37')},
    ),
)

#: Figures the book cites that this checkout cannot re-shoot, and the fact that stops it. The gate
#: `tests/unit/gates/test_manual_capture.py` reads this: a new figure with neither a recipe nor an
#: entry here fails, and an entry nobody cites any more fails too (an exemption that outlives its fact).
KEPT = {
    'login': 'the cloud sign-in page needs cloud mode and its own account store',
    'force-password': 'the first-login password change needs cloud mode and a fresh account',
    'accounts': 'the account panel needs cloud mode and accounts to list',
}


#: Every gesture :func:`run_recipe` knows. A recipe naming anything else is a typo that would only show
#: up as a failed shot minutes into a batch.
KINDS = frozenset(
    {
        'canvas',
        'dark',
        'settings',
        'zoom',
        'node_element',
        'element',
        'chart',
        'dashboard',
        'dashboardzoom',
        'datapreview',
        'dock',
        'menu',
        'cookie_dialog',
        'runlog',
    }
)


def load_workflow(driver, name):
    """Open *name* on a fresh page and answer its nodes."""
    open_workflow(driver, name)
    return node_types(driver) or []


def fresh_page(driver, url, dark=False):
    """Reload before every figure: a reused page carries the last one's open dialogs."""
    driver.get(url)
    time.sleep(5.5)
    hide_toast(driver)
    js(driver, "if(typeof setTheme==='function') setTheme(arguments[0])", 'dark' if dark else 'light')
    time.sleep(0.4)


def find_node(nodes, type_name=None, **want):
    """The first node of *type_name* whose params match every ``want`` entry."""
    for node in nodes:
        params = node.get('params') or {}
        if type_name and node['type'] != type_name:
            continue
        if all(params.get(key) == value for key, value in want.items()):
            return node
    return None


def shot_settings(driver, node, out):
    js(driver, 'openSettings(arguments[0])', node['id'])
    time.sleep(2.2)
    save_element(driver, '#node-settings', out)
    js(driver, 'closeSettings()')
    time.sleep(0.6)


def shot_zoom(driver, ids, out, zoom=1.0):
    """Frame just these nodes: the book's 'zoom' figures are a region, not the whole 172-node canvas."""
    js(
        driver,
        """var ids = arguments[0], z = arguments[1];
        var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
        ids.forEach(function (id) {
            var el = canvas._nodeEl(id);
            if (!el) return;
            minX = Math.min(minX, el.offsetLeft); minY = Math.min(minY, el.offsetTop);
            maxX = Math.max(maxX, el.offsetLeft + el.offsetWidth);
            maxY = Math.max(maxY, el.offsetTop + el.offsetHeight);
        });
        if (minX > maxX) return null;
        var vp = canvas.workspace || {};
        var vw = vp.clientWidth || window.innerWidth, vh = vp.clientHeight || window.innerHeight;
        canvas.zoom = z;
        canvas.panX = vw / 2 - z * (minX + maxX) / 2;
        canvas.panY = vh / 2 - z * (minY + maxY) / 2;
        canvas.updateTransform();
        return [vw, vh, minX, minY, maxX, maxY];""",
        list(ids),
        zoom,
    )
    time.sleep(1.5)
    save_window(driver, out)


def shot_node_element(driver, node, out):
    element_id = js(driver, 'return canvas._nodeEl(arguments[0]).id', node['id'])
    save_element(driver, '#' + str(element_id), out)


def shot_runlog(driver, out):
    """Newest recorded run's durable console — the four interleaved chains of a parallel canvas."""
    run_id = js(
        driver,
        'var r = await (await fetch("/api/runs/list?limit=5")).json();'
        'return (r.ok && r.runs && r.runs.length) ? r.runs[0].run_id : "";',
    )
    if not run_id:
        raise RuntimeError('no stored run on this server')
    js(driver, 'runLogViewer.open(arguments[0])', run_id)
    time.sleep(5)
    save_window(driver, out)


def mode_zoom(driver, args):
    open_workflow(driver, args.workflow)
    shot_zoom(driver, args.ids.split(','), args.out, args.zoom)


MODES['zoom'] = mode_zoom


def run_recipe(driver, url, out, kind, args):
    """One entry of :data:`RECIPES` against a freshly loaded page."""
    fresh_page(driver, url, dark=(kind == 'dark'))
    if kind == 'canvas' or kind == 'dark':
        load_workflow(driver, args['workflow'])
        save_window(driver, out)
    elif kind == 'settings':
        nodes = load_workflow(driver, args['workflow'])
        node = find_node(nodes, args.get('node_type'), **args.get('want', {}))
        if not node:
            raise RuntimeError(f'no such node in {args["workflow"]}: {args}')
        shot_settings(driver, node, out)
    elif kind == 'zoom':
        load_workflow(driver, args['workflow'])
        shot_zoom(driver, args['ids'], out, args.get('zoom', 1.0))
    elif kind == 'node_element':
        nodes = load_workflow(driver, args['workflow'])
        shot_node_element(driver, find_node(nodes, args.get('node_type'), **args.get('want', {})), out)
    elif kind in ('element', 'chart', 'dashboard', 'dashboardzoom', 'datapreview'):
        # The small canvases (9 nodes) leave a calm background behind a dock or a menu.
        nodes = load_workflow(driver, args['workflow'])
        if kind == 'element':
            save_element(driver, args['selector'], out)
        elif kind == 'chart':
            hydrate_results(driver)
            node = find_node(nodes, args.get('node_type', 'visualize'), **args.get('want', {}))
            js(driver, 'dataNodes.previewVisualize(arguments[0])', node['id'])
            time.sleep(5)
            save_element(driver, '#chart-preview-panel', out)
        elif kind == 'dashboard':
            hydrate_results(driver)
            js(driver, 'dashboard.open()')
            time.sleep(10)
            save_element(driver, '#dashboard-panel', out)
        elif kind == 'dashboardzoom':
            hydrate_results(driver)
            js(driver, 'dashboard.open()')
            time.sleep(10)
            node = find_node(nodes, args.get('node_type', 'visualize'), **args.get('want', {}))
            js(driver, 'openChartFullscreen(arguments[0])', node['id'])
            time.sleep(6)
            save_window(driver, out)
        else:
            hydrate_results(driver)
            node = find_node(nodes, args.get('node_type'), **args.get('want', {}))
            js(driver, 'dataNodes.previewData(arguments[0])', node['id'])
            time.sleep(5)
            if args.get('scroll') == 'right':
                scroll_preview_to_results(driver)
            save_element(driver, '#data-preview-panel', out)
    elif kind == 'dock':
        load_workflow(driver, ZH)
        js(driver, 'document.getElementById(arguments[0]).click()', args['button'])
        time.sleep(4)
        if args.get('row'):
            # A table row sits under the sticky header until it is scrolled into the middle.
            js(
                driver,
                "var el=document.querySelector(arguments[0]); if(el) el.scrollIntoView({block:'center'});",
                args['row'],
            )
            time.sleep(1.2)
            save_element(driver, args['row'], out)
        else:
            save_window(driver, out)
    elif kind == 'menu':
        load_workflow(driver, ZH)
        js(driver, args['opener'])
        time.sleep(2)
        save_element(driver, args['selector'], out)
    elif kind == 'cookie_dialog':
        load_workflow(driver, ZH)
        js(driver, "openCookieDialog('weibo','default')")
        time.sleep(3)
        save_element(driver, '#cookie-dialog', out)
    elif kind == 'runlog':
        shot_runlog(driver, out)
    else:
        raise RuntimeError('unknown kind ' + kind)


def run_batch(driver, url, only=()):
    """Shoot every recipe, naming each figure as it lands, and answer the failures."""
    failures = []
    wanted = {name.strip() for name in only if name.strip()}
    for out, kind, args in RECIPES:
        if wanted and out not in wanted:
            continue
        started = time.time()
        try:
            run_recipe(driver, url, out, kind, args)
            print(f'OK   {out:<16} {time.time() - started:.1f}s', flush=True)
        except Exception as exc:  # one bad figure must not cost the other 48
            failures.append((out, str(exc)))
            print(f'FAIL {out:<16} {exc}', flush=True)
    print(f'\n{len(RECIPES)} recipes, {len(failures)} failed')
    for out, reason in failures:
        print(f'  {out}: {reason}')
    if wanted:
        unknown = wanted - {out for out, _kind, _args in RECIPES}
        if unknown:
            print(f'unknown --only names: {sorted(unknown)}')
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description='Capture manual screenshots from the running app.')
    parser.add_argument('mode', nargs='?', choices=sorted(MODES))
    parser.add_argument('--url', default='http://127.0.0.1:5000/')
    parser.add_argument('--workflow', default=LIU)
    parser.add_argument('--out')
    parser.add_argument('--types', default='')
    parser.add_argument('--panel', default='runs')
    parser.add_argument('--node-type', default='visualize')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--ids', default='', help='zoom mode: comma-separated node ids to frame')
    parser.add_argument('--zoom', type=float, default=1.0)
    parser.add_argument('--scroll', default='', help="datapreview: 'right' scrolls to the appended result columns")
    parser.add_argument('--batch', action='store_true', help='shoot every figure in RECIPES')
    parser.add_argument('--only', default='', help='--batch subset, comma-separated figure names')
    args = parser.parse_args(argv)
    if not args.batch and not args.out:
        parser.error('--out is required unless --batch is given')
    if not args.batch and not args.mode:
        parser.error('a mode is required unless --batch is given')
    os.makedirs(OUT, exist_ok=True)
    driver = build_driver(args.url)
    try:
        if args.batch:
            failures = run_batch(driver, args.url, only=args.only.split(','))
        else:
            hide_toast(driver)
            js(driver, "if(typeof setTheme==='function') setTheme('light')")
            MODES[args.mode](driver, args)
            failures = []
    finally:
        driver.quit()
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
