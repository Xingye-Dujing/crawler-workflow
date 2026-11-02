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

Every mode sets the light theme first (the manual is printed on paper), lays the
canvas out with canvas.autoLayout(), fits it with canvas.resetView(), and takes
an element screenshot for panels so the crop is tight and the text stays large.
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


def mode_datapreview(driver, args):
    open_workflow(driver, args.workflow)
    hydrate_results(driver)
    node = pick_node(driver, args.node_type)
    js(driver, 'dataNodes.previewData(arguments[0])', node['id'])
    time.sleep(5)
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
}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Capture manual screenshots from the running app.')
    parser.add_argument('mode', choices=sorted(MODES))
    parser.add_argument('--url', default='http://127.0.0.1:5000/')
    parser.add_argument('--workflow', default='刘学州-评论-情感演化分析-BERT')
    parser.add_argument('--out', required=True)
    parser.add_argument('--types', default='')
    parser.add_argument('--panel', default='runs')
    parser.add_argument('--node-type', default='visualize')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args(argv)
    os.makedirs(OUT, exist_ok=True)
    driver = build_driver(args.url)
    try:
        hide_toast(driver)
        js(driver, "if(typeof setTheme==='function') setTheme('light')")
        MODES[args.mode](driver, args)
    finally:
        driver.quit()
    return 0


if __name__ == '__main__':
    sys.exit(main())
