/* Drives the REAL canvas-history tab and layout strategy in workflow.js under node.
 *
 * These are the decisions a user cannot see in a table until it is too late:
 * which canvas body a snapshot stores, whether restoring is ONE undo step,
 * whether deleting a snapshot clears a baseline it was pointing at, and whether
 * the Layout button actually obeys the strategy chosen in the Style menu.
 *
 * Usage: node harness_wf_history.mjs <workflow.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');

const DICT = {
    en: {
        'wfHistory.tabFiles': 'Workflows',
        'wfHistory.tabHistory': 'Canvas history',
        'wfHistory.loading': 'LOADING',
        'wfHistory.loadFailed': 'LOAD-FAILED',
        'wfHistory.empty': 'EMPTY',
        'wfHistory.colSnapshot': 'Snapshot',
        'wfHistory.colNodes': 'Nodes / links',
        'wfHistory.colSaved': 'Saved',
        'wfHistory.untitled': 'Untitled snapshot',
        'wfHistory.noWorkflow': 'Unsaved canvas',
        'wfHistory.restore': 'Restore',
        'wfHistory.restoreConfirm': 'Restore "{label}"?',
        'wfHistory.restored': 'RESTORED',
        'wfHistory.restoreFailed': 'RESTORE-FAILED',
        'wfHistory.remove': 'Delete',
        'wfHistory.confirmRemove': 'Delete "{label}"?',
        'wfHistory.removed': 'DELETED',
        'wfHistory.removeFailed': 'DELETE-FAILED',
        'wfHistory.baseline': 'Baseline',
        'wfHistory.baselineSet': 'BASELINE-SET',
        'wfHistory.baselineClearedByDelete': ' ({n} cleared)',
        'wfHistory.baselineFailed': 'BASELINE-FAILED',
        'wfHistory.baselineTag': 'baseline',
        'wfHistory.needSaved': 'SAVE-FIRST',
        'wfHistory.noBaseline': 'NO-BASELINE',
        'wfHistory.save': 'Save this canvas',
        'wfHistory.savePrompt': 'Name it:',
        'wfHistory.savePlaceholder': 'e.g. before',
        'wfHistory.saved': 'SAVED',
        'wfHistory.saveFailed': 'SAVE-FAILED',
        'style.layoutBaselineNone': 'NO-BASELINE-YET',
        'style.layoutBaselineMissing': 'BASELINE-GONE',
        'style.layoutHint': 'Applied by Layout',
        'wfMgr.busy': 'BUSY',
        'toast.layoutApplied': 'LAYOUT-APPLIED',
        'dialog.cancel': 'Cancel',
    },
    zh: {
        'wfHistory.tabFiles': '工作流文件',
        'wfHistory.tabHistory': '画布历史',
        'wfHistory.colSnapshot': '快照',
        'wfHistory.colNodes': '节点 / 连线',
        'wfHistory.colSaved': '保存时间',
        'wfHistory.untitled': '未命名快照',
        'wfHistory.noWorkflow': '未命名画布',
        'wfHistory.restore': '恢复',
        'wfHistory.remove': '删除',
        'wfHistory.baseline': '设为布局基准',
        'wfHistory.baselineTag': '基准',
    },
};
const I18n = {
    lang: 'en',
    t(key) {
        return (DICT[this.lang] || {})[key] || DICT.en[key] || key;
    },
};

const sandbox = { ...baseSandbox(), I18n, RunState: { running: false } };
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__wfh = { wfFiles, workflow, LayoutStrategy };', sandbox);

const { wfFiles, workflow, LayoutStrategy } = sandbox.__wfh;
const doc = sandbox.document;
const body = doc.getElementById('workflows-mgr-body');
const tabs = doc.getElementById('workflows-tabs');
const select = doc.getElementById('layout-strategy');
const hint = doc.getElementById('layout-baseline-hint');
const panel = doc.getElementById('workflows-panel');

const CANVAS = { nodes: [{ id: 'node-0', type: 'name' }], connections: [], settings: { view: { zoom: 1 } } };
const SNAP_WORKFLOW = { nodes: [{ id: 'node-0', type: 'name', x: 5, y: 6 }], connections: [], settings: {} };
const ROWS = [
    { id: 's1', label: '手动存档', workflow_name: '日报', created_at: 1760000000, nodes: 3, connections: 2 },
    { id: 's2', label: '<img src=x onerror=alert(1)>', workflow_name: 'q"uote', created_at: 1760003600, nodes: 1, connections: 0 },
];

let requests = [];
let toasts = [];
let dialogAnswer = true;
let typed = '手动存档';
let routes = {
    list: ROWS,
    layout: { workflow_name: '日报', strategy: 'algorithm', snapshot: null, baseline_missing: false },
    layoutResult: { workflow_name: '日报', strategy: 'algorithm', snapshot: null, baseline_missing: false },
    snapshot: { ok: true, snapshot: { id: 's1', workflow: SNAP_WORKFLOW } },
    save: { ok: true, snapshot: { id: 's9' } },
    delete: { ok: true, deleted: true, baselines_cleared: [] },
};

sandbox.showToast = (message) => toasts.push(String(message));
sandbox.showDialog = async (spec) => (spec && spec.input ? typed : dialogAnswer);
sandbox.fetch = (url, options) => {
    const target = String(url);
    const method = (options && options.method) || 'GET';
    requests.push({ url: target, method, body: options && options.body });
    let payload = { ok: true };
    if (target.indexOf('/api/workflow/history/save') >= 0) payload = routes.save;
    else if (target.indexOf('/api/workflow/history/delete') >= 0) payload = routes.delete;
    else if (target.indexOf('/api/workflow/history/get') >= 0) payload = routes.snapshot;
    else if (target.indexOf('/api/workflow/history/layout') >= 0) {
        payload = method === 'POST' ? { ok: true, layout: routes.layoutResult } : { ok: true, layout: routes.layout };
    } else if (target.indexOf('/api/workflow/history') >= 0) {
        payload = { ok: true, snapshots: routes.list, max: 100 };
    }
    const text = JSON.stringify(payload);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload), text: () => Promise.resolve(text) });
};

const nodeEls = {};
sandbox.canvas = {
    nodes: {},
    batchCalls: 0,
    layoutOptions: null,
    resetCount: 0,
    batchHistory(fn) {
        this.batchCalls += 1;
        return fn();
    },
    autoLayout(options) {
        this.layoutOptions = options || null;
    },
    _nodeEl(id) {
        return nodeEls[id] || null;
    },
    resetView() {
        this.resetCount += 1;
    },
    scheduleRender() {},
    saveState() {},
    toWorkflowJSON() {
        return CANVAS;
    },
};
workflow.currentFile = '日报';
workflow.runName = () => '日报';

const out = {};
const resetCalls = () => {
    requests = [];
    toasts = [];
    dialogAnswer = true;
    sandbox.RunState.running = false;
};

/* ── tabs and the history table ─────────────────────────────────────── */
wfFiles._history = ROWS;
wfFiles._tab = 'files';
wfFiles.renderTabs();
out.tabs = { html: tabs.innerHTML };
wfFiles._tab = 'history';
wfFiles.renderTabs();
out.tabs_history = { html: tabs.innerHTML };

LayoutStrategy._layout = { workflow_name: '日报', strategy: 'baseline', snapshot: { id: 's1' }, baseline_missing: false };
wfFiles.renderHistory();
out.history_render = {
    html: body.innerHTML,
    img_elements: doc.querySelectorAll('img').length,
    text: body.innerHTML,
};

wfFiles._history = [];
wfFiles.renderHistory();
out.history_empty = { html: body.innerHTML };
wfFiles._history = ROWS;

/* ── saving a snapshot ──────────────────────────────────────────────── */
resetCalls();
routes.list = ROWS;
wfFiles._tab = 'files';
await wfFiles.saveSnapshot();
const saveRequest = requests.find((r) => r.url.indexOf('/api/workflow/history/save') >= 0);
out.save = {
    body: saveRequest ? JSON.parse(saveRequest.body) : null,
    tab: wfFiles._tab,
    toasts: toasts.slice(),
    history_reads: requests.filter((r) => r.url.startsWith('/api/workflow/history?') || r.url === '/api/workflow/history').length,
};

/* A cancelled name dialog must send nothing. */
resetCalls();
typed = null;
await wfFiles.saveSnapshot();
out.save_cancelled = { requests: requests.length, toasts: toasts.slice() };
typed = '手动存档';

/* ── restoring ──────────────────────────────────────────────────────── */
resetCalls();
let loaded = null;
workflow._loadFromJSON = (data) => {
    loaded = data;
    return true;
};
routes.snapshot = { ok: true, snapshot: { id: 's1', workflow: SNAP_WORKFLOW } };
await wfFiles.restoreSnapshot('s1');
out.restore = {
    gets: requests.filter((r) => r.url.indexOf('/history/get') >= 0).map((r) => r.url),
    loaded_is_snapshot: JSON.stringify(loaded) === JSON.stringify(SNAP_WORKFLOW),
    batch_calls: sandbox.canvas.batchCalls,
    toasts: toasts.slice(),
};

resetCalls();
dialogAnswer = false;
loaded = null;
await wfFiles.restoreSnapshot('s1');
out.restore_cancelled = { requests: requests.length, loaded: loaded, toasts: toasts.slice() };

resetCalls();
sandbox.RunState.running = true;
loaded = null;
await wfFiles.restoreSnapshot('s1');
out.restore_busy = { requests: requests.length, loaded: loaded, toasts: toasts.slice() };

/* ── deleting ──────────────────────────────────────────────────────── */
resetCalls();
routes.delete = { ok: true, deleted: true, baselines_cleared: ['日报'] };
routes.list = [];
await wfFiles.deleteSnapshot('s1');
const deleteRequest = requests.find((r) => r.url.indexOf('/history/delete') >= 0);
out.delete = {
    body: deleteRequest ? JSON.parse(deleteRequest.body) : null,
    toasts: toasts.slice(),
    history_reads: requests.filter((r) => r.url.startsWith('/api/workflow/history?') || r.url === '/api/workflow/history').length,
};

/* ── the Style menu's strategy control ─────────────────────────────── */
resetCalls();
routes.layout = {
    workflow_name: '日报',
    strategy: 'baseline',
    snapshot: { id: 's1', label: '排布基准', created_at: 1760000000 },
    baseline_missing: false,
};
LayoutStrategy._layout = null;
await LayoutStrategy.refresh();
out.layout_paint = {
    select: select.value,
    hint: hint.textContent,
    hint_missing: hint.classList.contains('missing'),
    requests: requests.map((r) => r.url),
};

resetCalls();
LayoutStrategy._layout = { workflow_name: '日报', strategy: 'algorithm', snapshot: null, baseline_missing: false };
await LayoutStrategy.setStrategy('baseline');
out.layout_no_baseline = { requests: requests.length, toasts: toasts.slice(), select: select.value };

resetCalls();
LayoutStrategy._layout = {
    workflow_name: '日报',
    strategy: 'baseline',
    snapshot: { id: 's1', label: '排布基准' },
    baseline_missing: false,
};
routes.layoutResult = {
    workflow_name: '日报',
    strategy: 'baseline',
    snapshot: { id: 's1', label: '排布基准' },
    baseline_missing: false,
};
await LayoutStrategy.setStrategy('baseline');
let layoutPost = requests.find((r) => r.url.indexOf('/history/layout') >= 0 && r.method === 'POST');
out.layout_set_baseline_strategy = {
    body: layoutPost ? JSON.parse(layoutPost.body) : null,
    toasts: toasts.slice(),
    select: select.value,
};

resetCalls();
workflow.currentFile = '';
await LayoutStrategy.setStrategy('baseline');
out.layout_no_file = { requests: requests.length, toasts: toasts.slice() };
workflow.currentFile = '日报';

/* ── applying the baseline ─────────────────────────────────────────── */
resetCalls();
sandbox.canvas.batchCalls = 0;
sandbox.canvas.layoutOptions = null;
sandbox.canvas.resetCount = 0;
sandbox.canvas.nodes = { n0: {}, n1: {}, n2: {} };
nodeEls.n0 = { style: { left: '', top: '' } };
nodeEls.n1 = { style: { left: '', top: '' } };
nodeEls.n2 = { style: { left: '', top: '' } };
LayoutStrategy._layout = {
    workflow_name: '日报',
    strategy: 'baseline',
    snapshot: { id: 's1', label: 'base' },
    baseline_missing: false,
};
LayoutStrategy._snapshot = {
    id: 's1',
    workflow: {
        nodes: [
            { id: 'n0', x: 10, y: 20 },
            { id: 'n1', x: 300.4, y: 40.6 },
        ],
    },
};
const handled = await LayoutStrategy.layout();
out.baseline_layout = {
    handled,
    left0: nodeEls.n0.style.left,
    top0: nodeEls.n0.style.top,
    left1: nodeEls.n1.style.left,
    top1: nodeEls.n1.style.top,
    untouched: nodeEls.n2.style.left,
    batch_calls: sandbox.canvas.batchCalls,
    auto_options: sandbox.canvas.layoutOptions,
    reset_count: sandbox.canvas.resetCount,
    toasts: toasts.slice(),
};

resetCalls();
LayoutStrategy._layout = { workflow_name: '日报', strategy: 'algorithm', snapshot: null, baseline_missing: false };
sandbox.canvas.batchCalls = 0;
const handledAlgorithm = await LayoutStrategy.layout();
out.algorithm_layout = { handled: handledAlgorithm, batch_calls: sandbox.canvas.batchCalls };

resetCalls();
LayoutStrategy._layout = { workflow_name: '日报', strategy: 'baseline', snapshot: null, baseline_missing: true };
sandbox.canvas.batchCalls = 0;
const handledMissing = await LayoutStrategy.layout();
out.missing_layout = { handled: handledMissing, batch_calls: sandbox.canvas.batchCalls, toasts: toasts.slice() };

/* ── the one-undo-step wrapper ─────────────────────────────────────── */
resetCalls();
sandbox.canvas.batchCalls = 0;
let direct = 0;
workflow._loadFromJSON = () => {
    direct += 1;
    return true;
};
workflow.loadFromJSON({}, { history: 'single' });
workflow.loadFromJSON({});
out.load_wrapper = { batch_calls: sandbox.canvas.batchCalls, direct_calls: direct };

/* ── language switch repaints the table and the hint ───────────────── */
panel.classList.add('open');
wfFiles._history = ROWS;
wfFiles._tab = 'history';
I18n.lang = 'zh';
wfFiles.onLanguageChange();
out.language = { html: body.innerHTML, tabs: tabs.innerHTML };
I18n.lang = 'en';

process.stdout.write(JSON.stringify(out));
