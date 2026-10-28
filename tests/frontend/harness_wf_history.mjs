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
import { sourceOf } from './companions.mjs';

const src = sourceOf(process.argv[2]);

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
        'wfHistory.rename': 'Rename',
        'wfHistory.renamePrompt': 'Rename "{label}":',
        'wfHistory.renamePlaceholder': 'Snapshot name',
        'wfHistory.renamed': 'RENAMED',
        'wfHistory.renameFailed': 'RENAME-FAILED',
        'wfHistory.capacity': '{n} / {max} snapshots',
        'wfHistory.diffSame': 'SAME',
        'wfHistory.diffCounts': 'COUNTS {nodesAdded}/{nodesRemoved} {linksAdded}/{linksRemoved} moved={moved}',
        'wfHistory.diffWillReturn': 'RETURN {names}',
        'wfHistory.diffWillLeave': 'LEAVE {names}',
        'wfHistory.diffMore': ' +{n}',
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
        'wfProject.export': 'Export project',
        'wfProject.import': 'Import project',
        'wfProject.hint': 'PROJECT-HINT',
        'wfProject.exportPrompt': 'Export which?',
        'wfProject.current': 'This workflow',
        'wfProject.all': 'All workflows',
        'wfProject.noWorkflow': 'SAVE-FIRST',
        'wfProject.exported': 'EXPORTED',
        'wfProject.exportedWarn': 'EXPORTED {n}',
        'wfProject.exportFailed': 'EXPORT-FAILED',
        'wfProject.imported': 'IMPORTED {n}: {names}',
        'wfProject.importedNone': 'IMPORTED-NONE',
        'wfProject.warnings': '{n} warnings',
        'wfProject.importFailed': 'IMPORT-FAILED',
        'runsMgr.compare': 'Compare',
        'runsMgr.comparePick': 'Compare with?',
        'runsMgr.compareNeedOther': 'NO-OTHER-RUN',
        'runsMgr.compareFailed': 'COMPARE-FAILED',
        'runsMgr.compareTitle': 'RUN-COMPARE',
        'runsMgr.compareClose': 'Close comparison',
        'runsMgr.compareColNode': 'Node',
        'runsMgr.compareColStatus': 'Status',
        'runsMgr.compareColRows': 'Rows',
        'runsMgr.compareColDelta': 'Delta',
        'runsMgr.compareNode': 'Table: {name}',
        'runsMgr.compareCounts': 'ADDED {added} REMOVED {removed} CHANGED {changed}',
        'runsMgr.compareColumns': 'COLUMNS +{added} / -{removed}',
        'runsMgr.compareAdded': 'Added rows',
        'runsMgr.compareRemoved': 'Removed rows',
        'runsMgr.compareMore': '+{n} more',
        'runsMgr.compareWorkflowDiff': 'WORKFLOW-DIFF',
        'runsMgr.compareShapeDiff': 'SHAPE-DIFF',
        'runsMgr.compareKeyUsed': 'KEY {key}',
        'runsMgr.node.done': 'Done',
        'style.layoutBaselineNone': 'NO-BASELINE-YET',
        'style.layoutBaselineMissing': 'BASELINE-GONE',
        'style.layoutHint': 'Applied by Layout',
        'wfMgr.busy': 'BUSY',
        'wfMgr.broken': 'unreadable',
        'reusable.templatesTab': 'Reusable nodes',
        'reusable.colName': 'Template',
        'reusable.colNodes': 'Nodes / inputs',
        'reusable.colUpdated': 'Updated',
        'reusable.preview': 'Preview',
        'reusable.insert': 'Insert',
        'reusable.removeTemplate': 'Delete template',
        'reusable.confirmRemoveTemplate': 'Delete template "{name}"?',
        'reusable.templateRemoved': 'TEMPLATE-DELETED',
        'reusable.templateRemoveFailed': 'TEMPLATE-DELETE-FAILED',
        'reusable.loadFailed': 'TEMPLATES-LOAD-FAILED',
        'reusable.none': 'NO-TEMPLATES',
        'reusable.inserted': 'INSERTED',
        'reusable.insertFailed': 'INSERT-FAILED',
        'reusable.previewFailed': 'PREVIEW-FAILED',
        'reusable.rename': 'Rename',
        'reusable.renamePrompt': 'Rename "{name}":',
        'reusable.renamePlaceholder': 'Template name',
        'reusable.renamed': 'RENAMED',
        'reusable.renameFailed': 'RENAME-FAILED',
        'reusable.nameRequired': 'NAME-REQUIRED',
        'reusable.dragHint': 'DRAG-HINT',
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
        'wfHistory.rename': '重命名',
        'wfHistory.diffSame': '一致',
        'wfHistory.remove': '删除',
        'wfProject.export': '导出项目包',
        'wfProject.import': '导入项目包',
        'wfHistory.baseline': '设为布局基准',
        'wfHistory.baselineTag': '基准',
        'reusable.templatesTab': '可复用节点',
        'reusable.colName': '模板',
        'reusable.colNodes': '节点 / 输入',
        'reusable.colUpdated': '更新时间',
        'reusable.preview': '预览',
        'reusable.insert': '插入',
        'reusable.removeTemplate': '删除模板',
        'reusable.rename': '重命名',
        'reusable.dragHint': '拖拽提示',
    },
};
const I18n = {
    lang: 'en',
    t(key, vars) {
        let text = (DICT[this.lang] || {})[key] || DICT.en[key] || key;
        if (vars) {
            Object.keys(vars).forEach((name) => {
                text = text.split('{' + name + '}').join(String(vars[name]));
            });
        }
        return text;
    },
};

const sandbox = { ...baseSandbox(), I18n, RunState: { running: false } };
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__wfh = { wfFiles, workflow, LayoutStrategy, runsManager };', sandbox);

const { wfFiles, workflow, LayoutStrategy, runsManager } = sandbox.__wfh;
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
const TEMPLATES = [
    { id: 'r-000000000001', name: '清洗流水线', description: '两步', nodes: 2, connections: 1, inputs: 1, updated_at: '2026-10-26T01:00:00', broken: false },
    { id: 'r-000000000002', name: '<img src=x onerror=alert(1)>', description: '', nodes: 0, connections: 0, inputs: 0, updated_at: '', broken: true },
];

let requests = [];
let toasts = [];
let dialogAnswer = true;
let dialogMessages = [];
let typed = '手动存档';
let routes = {
    list: ROWS,
    layout: { workflow_name: '日报', strategy: 'algorithm', snapshot: null, baseline_missing: false },
    layoutResult: { workflow_name: '日报', strategy: 'algorithm', snapshot: null, baseline_missing: false },
    snapshot: { ok: true, snapshot: { id: 's1', workflow: SNAP_WORKFLOW } },
    save: { ok: true, snapshot: { id: 's9' } },
    delete: { ok: true, deleted: true, baselines_cleared: [] },
    historyRename: { ok: true, snapshot: { id: 's1', label: '重排前' } },
    reusableList: TEMPLATES,
    reusableDelete: { ok: true, deleted: true },
    reusableRename: { ok: true, template: { id: 'r-000000000001', name: '清洗流水线 v2' } },
    projectImport: {
        ok: true,
        summary: { workflows: [{ from: '项目A', to: '项目A (2)' }], datasets: [], templates: [], warnings: [] },
    },
    projectWarnings: 0,
    runCompare: {
        ok: true,
        diff: {
            a: { run_id: 'r1', workflow_name: '日报', status: 'completed' },
            b: { run_id: 'r2', workflow_name: '日报', status: 'completed' },
            same_workflow: true,
            same_shape: true,
            nodes: [
                {
                    node_id: 'node-0',
                    title: '输出',
                    status_a: 'done',
                    status_b: 'done',
                    rows_a: 2,
                    rows_b: 3,
                    row_delta: 1,
                },
            ],
            node: { node_id: 'node-0', title: '输出', rows_a: 2, rows_b: 3, row_delta: 1 },
            diff: {
                added_count: 1,
                removed_count: 1,
                changed_count: 0,
                columns_common: ['标题'],
                columns_added: [],
                columns_removed: [],
                added: [{ 标题: '新条目' }],
                removed: [{ 标题: '旧条目' }],
            },
        },
    },
    reusableGet: {
        ok: true,
        template: {
            id: 'r-000000000001',
            name: '清洗流水线',
            description: '两步',
            nodes: [
                { id: 'n1', type: 'process', title: '清洗', params: {}, x: 0, y: 0, w: 220, h: 90 },
                { id: 'n2', type: 'analysis', title: '去空', params: {}, x: 300, y: 0, w: 220, h: 80 },
            ],
            connections: [{ from: 'n1', to: 'n2' }],
            inputs: ['n1'],
            outputs: ['n2'],
        },
    },
};

sandbox.showToast = (message) => toasts.push(String(message));
sandbox.showDialog = async (spec) => {
    dialogMessages.push(String((spec && spec.message) || ''));
    return spec && spec.input ? typed : dialogAnswer;
};
sandbox.fetch = (url, options) => {
    const target = String(url);
    const method = (options && options.method) || 'GET';
    requests.push({ url: target, method, body: options && options.body });
    if (target.indexOf('/api/project/export') >= 0) {
        const filename = 'attachment; filename="project.zip"';
        return Promise.resolve({
            ok: true,
            headers: {
                get(name) {
                    if (name === 'Content-Disposition') return filename;
                    if (name === 'X-Project-Warnings') return String(routes.projectWarnings || 0);
                    return '';
                },
            },
            blob: () => Promise.resolve({ size: 1 }),
            json: () => Promise.resolve({ ok: true }),
            text: () => Promise.resolve(''),
        });
    }
    let payload = { ok: true };
    if (target.indexOf('/api/project/import') >= 0) payload = routes.projectImport;
    else if (target.indexOf('/api/runs/compare') >= 0) payload = routes.runCompare;
    else if (target.indexOf('/api/workflow/history/save') >= 0) payload = routes.save;
    else if (target.indexOf('/api/workflow/history/delete') >= 0) payload = routes.delete;
    else if (target.indexOf('/api/workflow/history/rename') >= 0) payload = routes.historyRename;
    else if (target.indexOf('/api/workflow/history/get') >= 0) payload = routes.snapshot;
    else if (target.indexOf('/api/workflow/history/layout') >= 0) {
        payload = method === 'POST' ? { ok: true, layout: routes.layoutResult } : { ok: true, layout: routes.layout };
    } else if (target.indexOf('/api/workflow/history') >= 0) {
        payload = { ok: true, snapshots: routes.list, max: 100 };
    } else if (target.indexOf('/api/reusable/rename') >= 0) {
        payload = routes.reusableRename;
    } else if (target.indexOf('/api/reusable/get') >= 0) {
        payload = routes.reusableGet;
    } else if (target.indexOf('/api/reusable/delete') >= 0) {
        payload = routes.reusableDelete;
    } else if (target.indexOf('/api/reusable') >= 0) {
        payload = { ok: true, templates: routes.reusableList };
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
const originalToWorkflow = sandbox.canvas.toWorkflowJSON;
workflow.currentFile = '日报';
workflow.runName = () => '日报';

const out = {};
const resetCalls = () => {
    requests = [];
    toasts = [];
    dialogMessages = [];
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
wfFiles._historyMax = 100;
wfFiles.renderHistory();
out.history_render = {
    html: body.innerHTML,
    img_elements: doc.querySelectorAll('img').length,
    text: body.innerHTML,
    capacity: doc.getElementById('workflows-history-capacity').textContent,
};

wfFiles._history = [];
wfFiles.renderHistory();
out.history_empty = {
    html: body.innerHTML,
    capacity: doc.getElementById('workflows-history-capacity').textContent,
};
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

/* The confirmation compares the snapshot (target) with the current file-shaped canvas,
   so a person sees what comes back and what goes away before saying yes. */
resetCalls();
const DIFF_CURRENT = {
    nodes: [
        { id: 'node-0', type: 'name', title: '起点', x: 10, y: 20 },
        { id: 'node-1', type: 'output', title: '当前节点', x: 0, y: 0 },
    ],
    connections: [{ from: 'node-0', to: 'node-1' }],
};
const DIFF_TARGET = {
    nodes: [
        { id: 'node-0', type: 'name', title: '起点', x: 10, y: 20 },
        { id: 'node-2', type: 'process', title: '恢复节点', x: 0, y: 0 },
    ],
    connections: [{ from: 'node-0', to: 'node-2' }],
};
sandbox.canvas.toWorkflowJSON = () => DIFF_CURRENT;
routes.snapshot = { ok: true, snapshot: { id: 's1', workflow: DIFF_TARGET } };
dialogAnswer = false;
loaded = null;
workflow._loadFromJSON = (data) => {
    loaded = data;
    return true;
};
const diff = wfFiles._diffWorkflow(DIFF_TARGET, DIFF_CURRENT);
await wfFiles.restoreSnapshot('s1');
out.restore_diff = {
    added_nodes: diff.addedNodes,
    removed_nodes: diff.removedNodes,
    added_links: diff.addedLinks,
    removed_links: diff.removedLinks,
    moved: diff.moved,
    changed: diff.changed,
    will_return: diff.willReturn.map((n) => n.id),
    will_leave: diff.willLeave.map((n) => n.id),
    message: dialogMessages[dialogMessages.length - 1],
    gets: requests.filter((r) => r.url.indexOf('/history/get') >= 0).length,
    loaded: loaded,
};
const same = wfFiles._diffWorkflow(DIFF_TARGET, DIFF_TARGET);
out.diff_same = { changed: same.changed, message: wfFiles._diffMessage(same) };
sandbox.canvas.toWorkflowJSON = originalToWorkflow;
routes.snapshot = { ok: true, snapshot: { id: 's1', workflow: SNAP_WORKFLOW } };

/* ── renaming a snapshot ───────────────────────────────────────────── */
resetCalls();
typed = '重排前';
routes.list = [{ ...ROWS[0], label: '重排前' }, ROWS[1]];
await wfFiles.renameSnapshot('s1');
const renameHistoryRequest = requests.find((r) => r.url.indexOf('/history/rename') >= 0);
out.history_rename = {
    body: renameHistoryRequest ? JSON.parse(renameHistoryRequest.body) : null,
    messages: dialogMessages.slice(),
    toasts: toasts.slice(),
    reads: requests.filter((r) => r.url === '/api/workflow/history').length,
    label: (wfFiles._history || [])[0].label,
    capacity: doc.getElementById('workflows-history-capacity').textContent,
};
typed = '手动存档';
routes.list = ROWS;

resetCalls();
typed = null;
await wfFiles.renameSnapshot('s1');
out.history_rename_cancelled = { requests: requests.length, toasts: toasts.slice() };
typed = '手动存档';

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

/* ── the reusable-template tab: insert / delete ────────────────────── */
wfFiles._tab = 'reusable';
wfFiles._templates = TEMPLATES;
wfFiles.renderTabs();
wfFiles.renderReusable();
out.reusable_tabs = { tabs: tabs.innerHTML };
out.reusable_list = {
    html: body.innerHTML,
    img_elements: doc.querySelectorAll('img').length,
};

resetCalls();
const dragData = {
    values: {},
    setData(type, value) { this.values[type] = String(value); },
    effectAllowed: '',
};
const dragHandle = {
    classes: [],
    classList: {
        add(name) { dragHandle.classes.push('+' + name); },
        remove(name) { dragHandle.classes.push('-' + name); },
    },
};
wfFiles.dragTemplate({ dataTransfer: dragData, currentTarget: dragHandle }, 'r-000000000001');
wfFiles.dragTemplate({ dataTransfer: dragData, currentTarget: dragHandle }, 'r-000000000002');
wfFiles.endTemplateDrag({ currentTarget: dragHandle });
out.reusable_drag = {
    data: dragData.values,
    effect: dragData.effectAllowed,
    classes: dragHandle.classes.slice(),
};

resetCalls();
const previewCalls = [];
sandbox.ReusableNodes = {
    previewTemplate: function (template) { previewCalls.push(template); },
};
await wfFiles.previewTemplate('r-000000000001');
out.reusable_preview = {
    calls: previewCalls.map((t) => ({ id: t.id, name: t.name })),
    gets: requests.filter((r) => r.url.indexOf('/api/reusable/get') >= 0).map((r) => r.url),
    toasts: toasts.slice(),
};

resetCalls();
typed = '清洗流水线 v2';
routes.reusableList = [{ ...TEMPLATES[0], name: '清洗流水线 v2' }];
await wfFiles.renameTemplate('r-000000000001');
const renameRequest = requests.find((r) => r.url.indexOf('/api/reusable/rename') >= 0);
out.reusable_rename = {
    body: renameRequest ? JSON.parse(renameRequest.body) : null,
    messages: dialogMessages.slice(),
    toasts: toasts.slice(),
    reads: requests.filter((r) => r.url === '/api/reusable').length,
    name: (wfFiles._templates || [])[0].name,
};

resetCalls();
typed = '';
routes.reusableList = TEMPLATES;
await wfFiles.renameTemplate('r-000000000001');
out.reusable_rename_blank = { requests: requests.length, toasts: toasts.slice() };
typed = '手动存档';

resetCalls();
routes.reusableList = [TEMPLATES[0]];
await wfFiles.removeTemplate('r-000000000001');
const templateDeleteRequest = requests.find((r) => r.url.indexOf('/api/reusable/delete') >= 0);
out.reusable_delete = {
    body: templateDeleteRequest ? JSON.parse(templateDeleteRequest.body) : null,
    toasts: toasts.slice(),
    reads: requests.filter((r) => r.url === '/api/reusable').length,
    rows: (wfFiles._templates || []).length,
};

resetCalls();
const insertCalls = [];
sandbox.ReusableNodes = {
    insertTemplate: async function (id, fromPanel) {
        insertCalls.push({ id: id, fromPanel: fromPanel });
        return 'node-new';
    },
};
panel.classList.add('open');
wfFiles._templates = TEMPLATES;
await wfFiles.insertTemplate('r-000000000001');
out.reusable_insert = {
    calls: insertCalls,
    panel_open: panel.classList.contains('open'),
};

/* ── project bundles: current/all choose, download, import ─────────── */
resetCalls();
dialogAnswer = 'current';
routes.projectWarnings = 2;
await wfFiles.exportProject();
out.project_export = {
    urls: requests.map((r) => r.url),
    toasts: toasts.slice(),
};

resetCalls();
dialogAnswer = 'all';
routes.projectWarnings = 0;
await wfFiles.exportProject();
out.project_export_all = {
    urls: requests.map((r) => r.url),
    toasts: toasts.slice(),
};

resetCalls();
workflow.currentFile = '';
dialogAnswer = 'current';
await wfFiles.exportProject();
out.project_export_unsaved = { requests: requests.length, toasts: toasts.slice() };
workflow.currentFile = '日报';
dialogAnswer = true;

resetCalls();
const fakeInput = { value: 'project.zip', files: [{ name: 'project.zip' }] };
await wfFiles.importProject(fakeInput);
const importRequest = requests.find((r) => r.url.indexOf('/api/project/import') >= 0);
out.project_import = {
    method: importRequest ? importRequest.method : '',
    entries: importRequest && importRequest.body && importRequest.body.entries ? importRequest.body.entries : [],
    input_value: fakeInput.value,
    list_reads: requests.filter((r) => r.url.indexOf('/api/workflow/list') >= 0).length,
    toasts: toasts.slice(),
};

/* ── run-to-run comparison: choose the other run, draw the server diff ── */
resetCalls();
runsManager._tab = 'workflow';
runsManager._shown = [
    { run_id: 'r1', started_at: '2026-10-26 10:00', workflow_name: '日报' },
    { run_id: 'r2', started_at: '2026-10-26 10:05', workflow_name: '日报' },
];
let compareRow = null;
runsManager._rowFor = () => ({
    nextSibling: null,
    parentNode: {
        insertBefore(tr) {
            compareRow = tr;
        },
    },
});
dialogAnswer = 'r2 · 2026-10-26 10:05 · 日报';
await runsManager.compare('r1');
out.run_compare = {
    requests: requests.map((r) => r.url),
    messages: dialogMessages.slice(),
    has_diff: !!runsManager._compare,
    row_id: compareRow ? compareRow.id : '',
    html: compareRow ? compareRow.innerHTML : '',
    toasts: toasts.slice(),
};
runsManager.closeCompare();
out.run_compare.closed = runsManager._compare === null;
dialogAnswer = true;

process.stdout.write(JSON.stringify(out));
