/* Runs the REAL reusable-node code (canvas.js + workflow.js + reusable.js) under node.
 *
 * The structural claim is the one a screenshot cannot prove: a reusable node is ONE
 * entry in the canvas model, its inside exists only in the DOM/template, and a RUN gets
 * a namespaced expanded graph with the external wires mapped onto ordered input slots.
 * The rest pins the user-visible behaviours: create-from-selection leaves the outside
 * wires connected, insert carries the saved template, toggle really shows/hides the
 * inside, statuses aggregate (running dominates, then failed), the preview works while
 * collapsed, and a file save keeps the group instead of fossilising the expansion.
 *
 * Usage: node harness_reusable.mjs <canvas.js> <workflow.js> <reusable.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow, flushFrames } from './harness_dom.mjs';

const [canvasPath, wfPath, reusablePath] = process.argv.slice(2);
const src = [canvasPath, wfPath, reusablePath].map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

const DICT = {
    en: {
        'node.process': 'Process',
        'node.analysis': 'Analysis',
        'node.output': 'Output',
        'node.reusable': 'Reusable node',
        'nodeType.process': 'Process',
        'nodeType.analysis': 'Analysis',
        'nodeType.output': 'Output',
        'nodeType.reusable': 'Reusable node',
        'settings.operation': 'Operation',
        'op.clean': 'Clean',
        'op.drop_null': 'Drop empty',
        'ctx.createReusable': 'Create',
        'reusable.previewClose': 'Close',
        'reusable.readOnly': 'Read only',
        'runsMgr.node.pending': 'Pending',
        'runsMgr.node.running': 'Running',
        'runsMgr.node.done': 'Done',
        'runsMgr.node.partial': 'Partial',
        'runsMgr.node.failed': 'Failed',
        'runsMgr.node.skipped': 'Skipped',
        'runsMgr.node.restored': 'Restored',
        'runsMgr.runStatus': 'STATUS {status}',
        'runsMgr.colRows': 'rows',
        'dialog.cancel': 'Cancel',
        'toast.nodeDeleted': 'NODE-DELETED',
        'toast.nodesDeleted': 'NODES-DELETED',
        'toast.layoutApplied': 'LAYOUT-APPLIED',
        'toast.workflowSaved': 'SAVED',
        'toast.saveFailed': 'SAVE-FAILED',
        'toast.workflowLoaded': 'LOADED',
        'toast.loadFailed': 'LOAD-FAILED',
        'toast.workflowFileInvalid': 'INVALID',
        'toast.newWorkflow': 'NEW',
        'toast.languageChanged': 'LANG {lang}',
        'status.nodes': 'Nodes: ',
        'canvas.fold': 'Fold',
        'canvas.unfold': 'Unfold',
        'conn.undo': 'Undo',
        'ctx.edit': 'Edit',
        'ctx.delete': 'Delete',
        'ctx.renameHint': 'Rename',
        'name.unnamed': 'unnamed',
        'reusable.created': 'CREATED',
        'reusable.inserted': 'INSERTED',
        'reusable.previewTitle': 'INSIDE {name}',
        'reusable.previewClose': 'Close',
        'reusable.readOnly': 'Read only',
        'reusable.inputsTitle': 'Inputs',
        'reusable.outputTitle': 'Output',
        'reusable.nodesTitle': 'Inside',
        'reusable.noInputs': 'No inputs',
        'reusable.nodeCount': '{n} nodes',
        'reusable.connectionCount': '{n} links',
        'reusable.inputsWired': '{wired}/{n} wired',
        'reusable.untitled': 'Untitled',
        'reusable.summary': '{n} nodes · {inputs} input(s)',
        'reusable.outputLine': 'output: {name}',
        'reusable.expandedLine': 'expanded',
        'reusable.unwrap': 'Unwrap',
        'reusable.unwrapConfirm': 'Unwrap "{name}"?',
        'reusable.unwrapped': 'UNWRAPPED',
        'reusable.unwrapTooManyInputs': 'TOO-MANY-INPUTS',
        'reusable.unwrapHint': 'Unwrap hint',
        'reusable.noTemplateForRun': 'NO-TEMPLATE',
        'reusable.badTemplate': 'BAD-TEMPLATE',
    },
    zh: {},
};
const I18n = {
    lang: 'en',
    dict: DICT,
    t(key, vars) {
        var text = (DICT[this.lang] && DICT[this.lang][key]) || DICT.en[key] || key;
        Object.keys(vars || {}).forEach(function (name) {
            text = text.split('{' + name + '}').join(String(vars[name]));
        });
        return text;
    },
    apply() {},
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    RunState: { parallel: false, headless: true, running: false, setRunning() {}, set() {} },
    Settings: { save() {} },
    resumeBar: { refresh() {} },
    runResults: { statuses: {}, clear() {}, refresh() {} },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(
    src + '\n;globalThis.__ru = { canvas, workflow, ReusableNodes, Outline, runResults };',
    sandbox,
);
const { canvas, workflow, ReusableNodes, Outline, runResults } = sandbox.__ru;
const doc = sandbox.document;
canvas.nodesContainer = doc.getElementById('nodes-container');
canvas.svgLayer = doc.getElementById('svg-layer');
canvas.container = doc.getElementById('canvas-inner');
canvas.workspace = Object.assign(doc.getElementById('workspace'), {
    clientWidth: 1400,
    clientHeight: 900,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 1400, height: 900 }),
});
Outline.render = function () {};
workflow.scheduleAutosave = function () {};
/* The page markup ships this checked; the stub's auto-created element has no such state. */
doc.getElementById('reusable-auto-layout').checked = true;
const toasts = [];
sandbox.showToast = (message) => toasts.push(String(message));

let dialogInput = '清洗流水线';
let dialogList = null;
sandbox.showDialog = async (spec) => {
    if (spec && spec.input) return dialogInput;
    if (spec && spec.list) return dialogList || spec.list[0];
    return true;
};

let requests = [];
let saveEcho = true;
sandbox.fetch = (url, options) => {
    const target = String(url);
    const method = (options && options.method) || 'GET';
    const body = options && options.body ? JSON.parse(options.body) : null;
    requests.push({ url: target, method, body });
    let payload = { ok: true };
    if (target.indexOf('/api/reusable/save') >= 0 && saveEcho) {
        payload = {
            ok: true,
            template: Object.assign(
                {
                    id: 'r-000000000001',
                    created_at: '2026-10-26T00:00:00',
                    updated_at: '2026-10-26T00:00:00',
                },
                body,
            ),
        };
    } else if (target.indexOf('/api/reusable/get') >= 0) {
        payload = {
            ok: true,
            template: {
                id: 'r-000000000002',
                name: '已保存的模板',
                description: '复用',
                nodes: [
                    { id: 'a', type: 'process', title: '清洗', params: { operation: 'clean' }, x: 0, y: 0, w: 220, h: 80 },
                    { id: 'b', type: 'analysis', title: '去空', params: { operation: 'drop_null' }, x: 260, y: 0, w: 220, h: 80 },
                ],
                connections: [{ from: 'a', to: 'b' }],
                inputs: ['a'],
                outputs: ['b'],
            },
        };
    } else if (target.indexOf('/api/reusable') >= 0) {
        payload = {
            ok: true,
            templates: [
                { id: 'r-000000000002', name: '已保存的模板', description: '复用', nodes: 2, connections: 1, inputs: 1, updated_at: '', broken: false },
            ],
        };
    } else if (target.indexOf('/api/workflow/save') >= 0) {
        payload = { ok: true, path: 'x', datasets: 0 };
    }
    const text = JSON.stringify(payload);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload), text: () => Promise.resolve(text) });
};

const out = {};
function add(type, x, y) {
    const id = canvas.addNode(type, x || 0, y || 0);
    canvas._nodeEl(id).offsetWidth = 220;
    canvas._nodeEl(id).offsetHeight = 80;
    return id;
}
function fresh() {
    Object.keys(canvas.nodes).forEach(function (id) { canvas.deleteNode(id); });
    canvas.connections = [];
    canvas._history = [];
    canvas._historyIdx = -1;
    canvas._historySaving = false;
    canvas.selectedNodes = [];
    canvas.selectedNode = null;
    runResults.statuses = {};
    toasts.length = 0;
    requests = [];
}
function groupOf() {
    return Object.keys(canvas.nodes).find(function (id) { return canvas.nodes[id].type === 'reusable'; });
}

/* ── create from a selection keeps the outside wires ─────────────────── */
fresh();
const up = add('process', 0, 0);
const p1 = add('process', 300, 0);
const p2 = add('analysis', 600, 0);
const down = add('output', 900, 0);
canvas.connections = [
    { from: up, to: p1 },
    { from: p1, to: p2 },
    { from: p2, to: down },
];
canvas.setSelectedNodes([p1, p2]);
await ReusableNodes.createFromSelection();
const createdId = groupOf();
const created = canvas.nodes[createdId];
out.create = {
    group: createdId,
    collapsed: created.params.collapsed,
    template_name: created.params.template_name,
    template_nodes: created.params.template.nodes.length,
    inputs: created.params.template.inputs,
    outputs: created.params.template.outputs,
    nodes_left: Object.keys(canvas.nodes).sort(),
    connections: canvas.connections.map((c) => [c.from, c.to]),
    toasts: toasts.slice(),
    save_request: requests.filter((r) => r.url.indexOf('/api/reusable/save') >= 0).map((r) => r.body),
};

/* ── insert a saved template ─────────────────────────────────────────── */
fresh();
const before = Object.keys(canvas.nodes).length;
await ReusableNodes.pickAndInsert();
const insertedId = groupOf();
out.insert = {
    added: Object.keys(canvas.nodes).length - before,
    name: canvas.nodes[insertedId].params.template_name,
    nodes: canvas.nodes[insertedId].params.template.nodes.length,
    toasts: toasts.slice(),
};

/* ── expand for a run, and keep the group in a file ──────────────────── */
const ext = add('process', 0, 0);
canvas.connections = [{ from: ext, to: insertedId }];
const runJson = canvas.toWorkflowJSON();
const fileJson = canvas.toWorkflowJSON({ expandReusable: false });
out.expand = {
    run_ids: runJson.nodes.map((n) => n.id).sort(),
    run_connections: runJson.connections.map((c) => [c.from, c.to]),
    run_has_group: runJson.nodes.some((n) => n.id === insertedId),
    file_ids: fileJson.nodes.map((n) => n.id),
    file_types: fileJson.nodes.map((n) => n.type),
    file_connections: fileJson.connections.map((c) => [c.from, c.to]),
};

/* Two input slots: the wires map in connection order. */
fresh();
const ext2 = add('process', 0, 0);
const second = add('process', 0, 200);
const down2 = add('output', 900, 0);
const two = {
    template_id: 'r-two',
    template_name: '双入口',
    description: '',
    collapsed: true,
    template: {
        nodes: [
            { id: 'a', type: 'process', params: {}, x: 0, y: 0, w: 220, h: 80 },
            { id: 'b', type: 'process', params: {}, x: 260, y: 0, w: 220, h: 80 },
            { id: 'c', type: 'analysis', params: {}, x: 520, y: 0, w: 220, h: 80 },
        ],
        connections: [{ from: 'a', to: 'c' }, { from: 'b', to: 'c' }],
        inputs: ['a', 'b'],
        outputs: ['c'],
    },
};
const twoId = canvas.addNode('reusable', 600, 300);
canvas.nodes[twoId].params = two;
canvas.updateNodeDisplay(twoId);
canvas.connections = [
    { from: ext2, to: twoId },
    { from: second, to: twoId },
    { from: twoId, to: down2 },
];
const twoJson = canvas.toWorkflowJSON();
out.slots = {
    connections: twoJson.connections.map((c) => [c.from, c.to]),
    errors: ReusableNodes.errors(),
};
canvas.connections = [{ from: ext2, to: twoId }];
out.missing_input = { errors: ReusableNodes.errors() };

/* ── toggle: the inside is DOM-only, and statuses aggregate ──────────── */
fresh();
const gid = canvas.addNode('reusable', 100, 100);
canvas.nodes[gid].params = JSON.parse(JSON.stringify(two));
canvas.nodes[gid].params.template_name = '双入口';
canvas.updateNodeDisplay(gid);
runResults.statuses = {
    [ReusableNodes.innerId(gid, 'a')]: { status: 'done', row_count: 4 },
    [ReusableNodes.innerId(gid, 'b')]: { status: 'running', row_count: 2 },
    [ReusableNodes.innerId(gid, 'c')]: { status: 'pending', row_count: 0 },
};
let autoLayoutCalls = 0;
canvas.runAutoLayout = function () { autoLayoutCalls += 1; };
canvas.applyRunStatuses(runResults.statuses);
flushFrames(sandbox);
const stage = canvas._nodeEl(gid).querySelector('.node-reusable-stage');
const badge = canvas._nodeEl(gid).querySelector('.node-run-badge');
out.collapsed_status = {
    params: canvas.nodes[gid].params.collapsed,
    badge: badge.dataset.status,
    badgeClass: badge.className,
    stage: !!stage,
};
ReusableNodes.toggle(gid);
const expandedEl = canvas._nodeEl(gid);
const generatedStage = ReusableNodes._stageHtml(gid, canvas.nodes[gid].params.template, {
    maxW: 760,
    maxH: 520,
});
out.expanded = {
    params: canvas.nodes[gid].params.collapsed,
    width: expandedEl.style.width,
    stage: !!expandedEl.querySelector('.node-reusable-stage'),
    inner_cards: expandedEl.querySelectorAll('.reusable-inner-node').length,
    inner_lines: (generatedStage.html.match(/<path/g) || []).length,
    running_dots: expandedEl.querySelectorAll('.rin-status.st-running').length,
    done_dots: expandedEl.querySelectorAll('.rin-status.st-done').length,
    model_has_only_group: Object.keys(canvas.nodes),
    auto_layout_calls: autoLayoutCalls,
};
runResults.statuses = {
    [ReusableNodes.innerId(gid, 'a')]: { status: 'failed', row_count: 0 },
    [ReusableNodes.innerId(gid, 'b')]: { status: 'done', row_count: 2 },
    [ReusableNodes.innerId(gid, 'c')]: { status: 'done', row_count: 1 },
};
canvas.applyRunStatuses(runResults.statuses);
out.failed_status = {
    badge: canvas._nodeEl(gid).querySelector('.node-run-badge').dataset.status,
    badgeClass: canvas._nodeEl(gid).querySelector('.node-run-badge').className,
};
ReusableNodes.toggle(gid);
out.collapsed = {
    params: canvas.nodes[gid].params.collapsed,
    width: canvas._nodeEl(gid).style.width,
    stage: !!canvas._nodeEl(gid).querySelector('.node-reusable-stage'),
};

/* ── preview while collapsed ─────────────────────────────────────────── */
ReusableNodes.preview(gid);
const overlay = doc.getElementById('reusable-preview-overlay');
out.preview = {
    open: overlay.classList.contains('open'),
    title: doc.getElementById('reusable-preview-title').textContent,
    stage_cards: doc.getElementById('reusable-preview-stage').querySelectorAll('.reusable-inner-node').length,
    side_nodes: (doc.getElementById('reusable-preview-side').innerHTML.match(/class="rps-node"/g) || []).length,
    slots: (doc.getElementById('reusable-preview-side').innerHTML.match(/class="rps-index"/g) || []).length,
};
ReusableNodes.closePreview();
out.preview.closed = !overlay.classList.contains('open');

/* A saved template can be previewed from the manager before it is inserted: there is
   no instance and therefore no run status to paint. */
ReusableNodes.previewTemplate({
    name: '模板直看',
    nodes: [
        { id: 'a', type: 'process', title: '清洗', params: {}, x: 0, y: 0, w: 220, h: 90 },
        { id: 'b', type: 'analysis', title: '去空', params: {}, x: 300, y: 0, w: 220, h: 80 },
    ],
    connections: [{ from: 'a', to: 'b' }],
    inputs: ['a'],
    outputs: ['b'],
});
out.template_preview = {
    open: overlay.classList.contains('open'),
    title: doc.getElementById('reusable-preview-title').textContent,
    stage_cards: doc.getElementById('reusable-preview-stage').querySelectorAll('.reusable-inner-node').length,
    side_nodes: (doc.getElementById('reusable-preview-side').innerHTML.match(/class="rps-node"/g) || []).length,
    statuses: (doc.getElementById('reusable-preview-stage').innerHTML.match(/rin-status/g) || []).length,
};
ReusableNodes.closePreview();

/* The settings form names the slots and escapes the template name. */
const safeName = canvas.nodes[gid].params.template_name;
canvas.nodes[gid].params.template_name = '<img src=x onerror=alert(1)>';
const settingsHtml = ReusableNodes.settingsHtml(gid);
out.settings = {
    has_slot_rows: (settingsHtml.match(/reusable-slot-row/g) || []).length,
    escaped_name: settingsHtml.indexOf('&lt;img') >= 0 && settingsHtml.indexOf('<img') < 0,
    toggle_call: settingsHtml.indexOf("ReusableNodes.toggle('") >= 0,
    preview_call: settingsHtml.indexOf("ReusableNodes.preview('") >= 0,
};
canvas.nodes[gid].params.template_name = safeName;

/* ── the auto-layout preference reaches the toggle ───────────────────── */
fresh();
const pref = canvas.addNode('reusable', 100, 100);
canvas.nodes[pref].params = JSON.parse(JSON.stringify(two));
canvas.updateNodeDisplay(pref);
doc.getElementById('reusable-auto-layout').checked = false;
let calledOff = 0;
canvas.runAutoLayout = function () { calledOff += 1; };
ReusableNodes.toggle(pref);
out.auto_layout_off = { calls: calledOff, expanded: canvas.nodes[pref].params.collapsed === false };
doc.getElementById('reusable-auto-layout').checked = true;
ReusableNodes.toggle(pref); // collapse
ReusableNodes.toggle(pref); // expand again, now on
out.auto_layout_on = { calls: calledOff };

/* ── a history state remembers whether the group was open ────────────── */
fresh();
const rid = canvas.addNode('reusable', 100, 100);
canvas.nodes[rid].params = JSON.parse(JSON.stringify(two));
canvas.nodes[rid].params.collapsed = false;
canvas.updateNodeDisplay(rid);
const openState = canvas.getState();
canvas.nodes[rid].params.collapsed = true;
canvas.updateNodeDisplay(rid);
Object.keys(canvas.nodes).forEach(function (id) {
    const el = canvas._nodeEl(id);
    if (el) el.remove();
    delete canvas.nodes[id];
});
canvas.connections = [];
canvas.restoreState(openState);
out.restore = {
    collapsed: canvas.nodes[rid].params.collapsed,
    stage: !!canvas._nodeEl(rid).querySelector('.node-reusable-stage'),
};

/* ── autosave/save uses the file shape ───────────────────────────────── */
fresh();
const savedGroup = canvas.addNode('reusable', 100, 100);
canvas.nodes[savedGroup].params = JSON.parse(JSON.stringify(two));
canvas.updateNodeDisplay(savedGroup);
workflow.currentFile = '画布一';
requests = [];
await workflow.save();
const saveBody = requests.find((r) => r.url.indexOf('/api/workflow/save') >= 0);
out.file_save = {
    has_group: !!(saveBody && saveBody.body.workflow.nodes.some((n) => n.type === 'reusable')),
    ids: saveBody ? saveBody.body.workflow.nodes.map((n) => n.id) : [],
};

/* ── auto-layout treats the expanded group as ONE measured block ─────── */
fresh();
const bigGroup = canvas.addNode('reusable', 0, 0);
canvas.nodes[bigGroup].params = JSON.parse(JSON.stringify(two));
canvas.updateNodeDisplay(bigGroup);
const bigEl = canvas._nodeEl(bigGroup);
bigEl.offsetWidth = 800;
bigEl.offsetHeight = 500;
const sibling = add('process', 0, 0);
canvas.connections = [{ from: bigGroup, to: sibling }];
canvas.autoLayout();
const groupRect = {
    left: parseFloat(bigEl.style.left),
    top: parseFloat(bigEl.style.top),
    right: parseFloat(bigEl.style.left) + bigEl.offsetWidth,
    bottom: parseFloat(bigEl.style.top) + bigEl.offsetHeight,
};
const sibEl = canvas._nodeEl(sibling);
const siblingRect = {
    left: parseFloat(sibEl.style.left),
    top: parseFloat(sibEl.style.top),
    right: parseFloat(sibEl.style.left) + sibEl.offsetWidth,
    bottom: parseFloat(sibEl.style.top) + sibEl.offsetHeight,
};
out.autolayout_block = {
    group_size: [bigEl.offsetWidth, bigEl.offsetHeight],
    overlap:
        Math.min(groupRect.right, siblingRect.right) - Math.max(groupRect.left, siblingRect.left) > 1 &&
        Math.min(groupRect.bottom, siblingRect.bottom) - Math.max(groupRect.top, siblingRect.top) > 1,
    model_has_group_only: Object.keys(canvas.nodes).sort(),
};

/* The Style menu's select is themed; a native value write must also refresh the trigger. */
let customSelectCalls = 0;
sandbox.CustomSelect = { refreshAll() { customSelectCalls += 1; } };
sandbox.LayoutStrategy._layout = { workflow_name: '日报', strategy: 'baseline', snapshot: null, baseline_missing: true };
sandbox.LayoutStrategy._paint();
out.custom_select = { calls: customSelectCalls, value: doc.getElementById('layout-strategy').value };

/* A right-click on an unselected node passes that node explicitly; the selection may
   still be empty (or stale), and the template must use the node that was clicked. */
fresh();
const only = add('process', 300, 300);
canvas.setSelectedNodes([]);
await ReusableNodes.createFromSelection([only]);
const onlyGroup = groupOf();
out.create_from_ids = {
    group: onlyGroup,
    only,
    template_nodes: canvas.nodes[onlyGroup].params.template.nodes.map((n) => n.id),
    model: Object.keys(canvas.nodes),
};

/* ── unwrap: ordinary nodes return, external wires reconnected by slot ── */
fresh();
const uwUp = add('process', 0, 0);
const uwDown = add('output', 900, 0);
const uwGroup = canvas.addNode('reusable', 300, 100);
canvas.nodes[uwGroup].params = JSON.parse(JSON.stringify(two));
canvas.nodes[uwGroup].params.template.inputs = ['a'];
canvas.nodes[uwGroup].params.template.outputs = ['c'];
canvas.updateNodeDisplay(uwGroup);
canvas.connections = [{ from: uwUp, to: uwGroup }, { from: uwGroup, to: uwDown }];
toasts.length = 0;
await ReusableNodes.unwrap(uwGroup);
const unwrappedIds = Object.keys(canvas.nodes).filter((id) => id !== uwUp && id !== uwDown);
out.unwrap = {
    group_gone: !canvas.nodes[uwGroup],
    group: uwGroup,
    up: uwUp,
    down: uwDown,
    inner_ids: unwrappedIds,
    inner_count: unwrappedIds.length,
    connections: canvas.connections.map((c) => [c.from, c.to]),
    toasts: toasts.slice(),
};
canvas.undo();
out.unwrap.undo_group_back = !!canvas.nodes[uwGroup];
out.unwrap.undo_nodes = Object.keys(canvas.nodes).sort();

/* Too many external wires is refused before anything moves. */
fresh();
const mx = add('process', 0, 0);
const my = add('process', 0, 100);
const md = add('output', 900, 0);
const mg = canvas.addNode('reusable', 300, 100);
canvas.nodes[mg].params = JSON.parse(JSON.stringify(two));
canvas.nodes[mg].params.template.inputs = ['a'];
canvas.nodes[mg].params.template.outputs = ['c'];
canvas.updateNodeDisplay(mg);
canvas.connections = [{ from: mx, to: mg }, { from: my, to: mg }, { from: mg, to: md }];
toasts.length = 0;
await ReusableNodes.unwrap(mg);
out.unwrap_too_many = {
    group_still: !!canvas.nodes[mg],
    model: Object.keys(canvas.nodes).sort(),
    toasts: toasts.slice(),
};

/* A disabled group must not silently re-enable its children when unwrapped. */
fresh();
const dg = canvas.addNode('reusable', 100, 100);
canvas.nodes[dg].params = JSON.parse(JSON.stringify(two));
canvas.nodes[dg].params.enabled = false;
canvas.updateNodeDisplay(dg);
toasts.length = 0;
await ReusableNodes.unwrap(dg);
const disabledChildren = Object.keys(canvas.nodes).map((id) => canvas.nodes[id]);
out.unwrap_disabled = {
    count: disabledChildren.length,
    all_disabled: disabledChildren.every((n) => n.params.enabled === false),
    toasts: toasts.slice(),
};

/* The group settings form exposes the unwrap door. */
fresh();
const sg = canvas.addNode('reusable', 100, 100);
canvas.nodes[sg].params = JSON.parse(JSON.stringify(two));
canvas.updateNodeDisplay(sg);
const unwrapSettingsHtml = ReusableNodes.settingsHtml(sg);
out.unwrap_settings = {
    has_unwrap: unwrapSettingsHtml.indexOf('ReusableNodes.unwrap(') >= 0,
    has_hint: unwrapSettingsHtml.indexOf('Unwrap hint') >= 0,
};

/* A drag names its landing point; the insert itself is the same one the button uses.
   Kept last so the extra node id cannot shift the ids earlier scenarios pinned. */
fresh();
const atBefore = Object.keys(canvas.nodes).length;
const atId = await ReusableNodes.insertTemplateAt('r-000000000002', 444, 333);
const atEl = atId && canvas._nodeEl(atId);
out.insert_at = {
    added: Object.keys(canvas.nodes).length - atBefore,
    name: atId ? canvas.nodes[atId].params.template_name : '',
    x: atEl ? parseInt(atEl.style.left, 10) : null,
    y: atEl ? parseInt(atEl.style.top, 10) : null,
};

process.stdout.write(JSON.stringify(out));
