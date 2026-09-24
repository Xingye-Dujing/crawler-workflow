/* Runs the REAL canvas interaction layer (canvas.js + workflow.js together) under node.
 *
 * The state harness covers what a canvas *serialises to*; this one covers how a
 * user gets there — the pointer layer that was previously unenterable because the
 * DOM stub had no selector engine, no parent chain and dropped every frame:
 *
 *   · wiring a connection: drag from an out-port, drop on an in-port, and the rules
 *     that decide it (no self-loop, no duplicate, cancel drops the temp line),
 *     including the tokenize↔visualize coupling that rewrites output_mode and
 *     re-renders an open settings panel;
 *   · repainting: `updateConnections` deletes the old paths by selector and rebuilds
 *     one per connection, and the hover target that removes one on click is a
 *     listener only that function installs;
 *   · selecting, folding, zoom bounds, reset-view centring, autoLayout ordering, the
 *     settings button's "which node is open" marker;
 *   · the delegated node header/port mousedown, the right-click pan threshold that
 *     decides whether a context menu appears, and the background click that closes
 *     settings;
 *   · the two functions the state harness replaces with spies — the real
 *     `renameNode` dialog flow and the real `editNode`/`openSettings`/`closeSettings`
 *     round trip.
 *
 * Both files load because `closeSettings` lives in workflow.js and *clears*
 * `canvas._settingsNodeId`: stubbing it here would have let the toggle-off path look
 * broken (a stuck highlight) while the shipped app was fine. The stub has to be the
 * least faithful thing in the room, not the thing that changes a verdict.
 *
 * Usage: node harness_canvas_ix.mjs <canvas.js> <workflow.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, dispatchDocument, dispatchOn, fixWindow, flushFrames, resetWorld } from './harness_dom.mjs';

const [canvasPath, wfPath] = process.argv.slice(2);
const src = [canvasPath, wfPath].map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

const KEYS = {
    'node.source': 'Data Source',
    'node.upload': 'Upload',
    'node.process': 'Process',
    'node.analysis': 'Analysis',
    'node.visualize': 'Visualize',
    'node.tokenize': 'Tokenize',
    'node.output': 'Output',
    'node.resume': 'Resume',
    'node.comment': 'Comments',
    'node.name': 'Workflow Name',
    'status.nodes': 'Nodes: ',
    'toast.connCreated': 'CONN-CREATED',
    'toast.connRemoved': 'CONN-REMOVED',
    'ctx.edit': 'edit',
    'ctx.delete': 'delete',
    'canvas.fold': 'FOLD',
    'canvas.unfold': 'UNFOLD',
    'dialog.renameNode': 'RENAME-NODE',
    'dialog.cancel': 'Cancel',
    'dialog.confirm': 'OK',
};
/* The zh side exists so a language switch has somewhere to land: with an empty
   dictionary every "does the label follow the language" probe answers "no" for
   the wrong reason. */
const ZH = {
    'node.source': '数据源',
    'node.upload': '上传文件',
    'node.process': '处理',
    'node.analysis': '分析',
    'node.visualize': '可视化',
    'node.tokenize': '分词',
    'node.output': '输出',
    'node.resume': '断点续跑',
    'node.comment': '评论',
    'node.name': '工作流名称',
    'status.nodes': '节点：',
};
const DICT = {
    en: KEYS,
    zh: { ...KEYS, ...ZH },
};
let LANG = 'en';
const I18n = {
    get lang() { return LANG; },
    set lang(v) { LANG = v; },
    dict: DICT,
    t(k) { return DICT[LANG][k] || k; },
    apply() {},
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    RunState: { parallel: false, headless: true, setRunning() {}, set() {} },
    resumeBar: { refresh() {} },
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'm', api_key: '' }) },
    /* Settings lives in app.js, which is not loaded here — the canvas only ever
       calls `Settings.save()` to remember a view change, so the interesting part is
       that it was called, and how many times. */
    Settings: { save() { sandbox.__settingsSaves += 1; } },
    __settingsSaves: 0,
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__canvas = canvas; globalThis.__wf = workflow;', sandbox);

/* Re-seeded after the load: workflow.js declares both of these itself, and a
   function declaration inside the script wins over anything seeded before it. */
const toasts = [];
const dialogs = [];
let dialogAnswer = null;
sandbox.showToast = (msg) => toasts.push(String(msg));
sandbox.showDialog = async (spec) => {
    dialogs.push({ message: spec.message, initial: spec.input && spec.input.value, buttons: (spec.buttons || []).map((b) => b.label) });
    return dialogAnswer;
};
/* The panels fetch nothing here, but workflow.js polls on load; stop the timer so
   a pending tick cannot fire after the scenario that created it is gone. */
sandbox.clearInterval = () => {};

const canvas = sandbox.__canvas;
const doc = sandbox.document;
const out = {};

/* `Math.random` seeds a node dropped with no coordinates; a fixed value makes
   every asserted position meaningful instead of merely in-range. */
const realRandom = Math.random;
Math.random = () => 0.5;

/** A clean page with the same document object (see harness_dom.resetWorld). */
function freshWorld() {
    resetWorld(sandbox);
    sandbox.localStorage.removeItem('crawler_canvas');
    canvas.nodes = {};
    canvas.connections = [];
    canvas.selectedNode = null;
    canvas.nextId = 1;
    canvas._history = [];
    canvas._historyIdx = -1;
    canvas._clipboardData = null;
    canvas._settingsNodeId = null;
    canvas.connectingFrom = null;
    canvas.tempLine = null;
    canvas._renderPending = false;
    canvas.isDragging = false;
    canvas.isPanning = false;
    canvas.panWasDragging = false;
    canvas.dragTarget = null;
    canvas.zoom = 1;
    canvas.panX = 0;
    canvas.panY = 0;
    toasts.length = 0;
    dialogs.length = 0;
    dialogAnswer = null;
    /* init() re-resolves the layer references AND wires every document/workspace
       listener against the now-empty page; skipping it leaves the pointer handlers
       attached to the previous scenario's elements. */
    canvas.init();
}

function addNode(type, x = 100, y = 100) {
    const nid = canvas.addNode(type, x, y);
    /* The stub reports one fixed box for everything; give each node its own so
       port centres, the hit radius and reset-view centring can tell them apart. */
    const el = doc.getElementById(nid);
    el.offsetLeft = x;
    el.offsetTop = y;
    el.offsetWidth = 220;
    el.offsetHeight = 120;
    el.querySelectorAll('.node-port').forEach((port) => {
        const px = port.dataset.port === 'in' ? x : x + 220;
        port.getBoundingClientRect = () => ({
            left: px - 5, top: y + 55, width: 10, height: 10, right: px + 5, bottom: y + 65,
        });
    });
    return nid;
}

function portOf(id, which) {
    return doc.getElementById(id).querySelectorAll('.node-port').find((p) => p.dataset.port === which);
}

function draft() {
    return JSON.parse(sandbox.localStorage.getItem('crawler_canvas') || 'null');
}

function ev(extra = {}) {
    return { button: 0, clientX: 100, clientY: 100, target: { closest: () => null }, ...extra };
}

/** Drop a connection from `fromId`'s out-port onto `toId`'s in-port. */
function dragConnection(fromId, toId) {
    dispatchOn(portOf(fromId, 'out'), 'mousedown', ev({ target: portOf(fromId, 'out') }));
    const rect = toId === null ? { left: 10, top: 10 } : portOf(toId, 'in').getBoundingClientRect();
    return dispatchDocument(sandbox.__handlers, 'mouseup', {
        clientX: rect.left + 5,
        clientY: rect.top + 5,
        target: { closest: () => null },
    });
}

/* ── selection ─────────────────────────────────────────────────────── */
freshWorld();
const selA = addNode('source', 0, 0);
const selB = addNode('output', 400, 0);
canvas.selectNode(selA);
const first = doc.querySelectorAll('.node.selected').map((el) => el.id);
canvas.selectNode(selB);
const second = doc.querySelectorAll('.node.selected').map((el) => el.id);
canvas.deselectNode();
out.selection = {
    afterFirst: first,
    afterSecond: second,
    afterDeselect: doc.querySelectorAll('.node.selected').map((el) => el.id),
    selectedId: canvas.selectedNode,
    statusText: doc.getElementById('status-nodes').textContent,
};

/* ── connecting ────────────────────────────────────────────────────── */
freshWorld();
const cFrom = addNode('source', 0, 0);
const cTo = addNode('analysis', 400, 0);
dispatchOn(portOf(cFrom, 'out'), 'mousedown', ev({ target: portOf(cFrom, 'out') }));
out.connect_started = {
    connectingFrom: canvas.connectingFrom,
    /* The temp line is the only feedback that a wire is being dragged. */
    tempLines: canvas.svgLayer.querySelectorAll('.conn-line.temp').length,
};
dispatchDocument(sandbox.__handlers, 'mousemove', { clientX: 500, clientY: 60 });
out.connect_temp_d = canvas.tempLine.d || '';
/* Finish THIS drag rather than starting a second one, or the line above leaks
   into every later count in this scenario. */
const firstDrop = portOf(cTo, 'in').getBoundingClientRect();
dispatchDocument(sandbox.__handlers, 'mouseup', {
    clientX: firstDrop.left + 5,
    clientY: firstDrop.top + 5,
    target: { closest: () => null },
});
out.connect_created = {
    connections: JSON.parse(JSON.stringify(canvas.connections)),
    toasts: toasts.slice(),
    connectingFrom: canvas.connectingFrom,
    tempLineGone: canvas.tempLine === null,
    persisted: draft().connections.length,
};
flushFrames(sandbox);
out.connect_created.lines_after_flush = canvas.svgLayer.querySelectorAll('.conn-line:not(.temp)').length;
/* The same pair again must not add a second wire. */
toasts.length = 0;
dragConnection(cFrom, cTo);
out.connect_duplicate = { connections: canvas.connections.length, toasts: toasts.slice() };
/* Onto its own node: a self-loop is a cycle the executor cannot sort. */
dragConnection(cFrom, cFrom);
out.connect_self = { connections: canvas.connections.length };
/* Mid-drag cancel leaves no temp line behind. */
dispatchOn(portOf(cTo, 'out'), 'mousedown', ev());
const beforeCancel = canvas.svgLayer.querySelectorAll('.conn-line.temp').length;
canvas.cancelConnection();
out.connect_cancel = {
    beforeCancel,
    afterCancel: canvas.svgLayer.querySelectorAll('.conn-line.temp').length,
    connectingFrom: canvas.connectingFrom,
};
/* Dropping on empty space creates nothing and ends the drag. */
dispatchOn(portOf(cFrom, 'out'), 'mousedown', ev());
dispatchDocument(sandbox.__handlers, 'mouseup', { clientX: -5000, clientY: -5000, target: { closest: () => null } });
out.connect_dropped_on_nothing = { connections: canvas.connections.length, connectingFrom: canvas.connectingFrom };

/* ── tokenize ↔ visualize coupling ─────────────────────────────────── */
freshWorld();
const tk = addNode('tokenize', 0, 0);
const vz = addNode('visualize', 400, 0);
canvas.nodes[tk].params.output_mode = 'words_only';
canvas.updateNodeDisplay(tk);
canvas._settingsNodeId = vz;
dragConnection(tk, vz);
out.tokenize_visualize = {
    mode: canvas.nodes[tk].params.output_mode,
    content: doc.getElementById(tk).querySelector('.node-content').textContent,
    panelStillOn: canvas._settingsNodeId,
    persistedMode: draft().nodes[tk].params.output_mode,
};

/* ── repaint and the connection delete target ──────────────────────── */
freshWorld();
const rA = addNode('source', 0, 0);
const rB = addNode('analysis', 400, 0);
const rC = addNode('output', 800, 0);
canvas.connections = [{ from: rA, to: rB }, { from: rB, to: rC }];
canvas.scheduleRender();
const frames = flushFrames(sandbox);
const hits = () => canvas.svgLayer.querySelectorAll('.conn-delete-hit');
const lines = () => canvas.svgLayer.querySelectorAll('.conn-line:not(.temp)');
out.repaint = {
    frames,
    lines: lines().length,
    hits: hits().length,
    /* One repaint per frame, however many changes queued it. */
    pendingCleared: canvas._renderPending === false,
};
canvas.scheduleRender();
canvas.scheduleRender();
flushFrames(sandbox);
out.repaint.lines_after_two_schedules = lines().length;
const firstLine = lines()[0];
dispatchOn(hits()[0], 'mouseenter', ev());
out.repaint.hover_paints_red = firstLine.style.stroke;
dispatchOn(hits()[0], 'mouseleave', ev());
out.repaint.hover_releases = firstLine.style.stroke === '';
dispatchOn(hits()[0], 'click', ev());
out.repaint.after_delete = {
    linesBefore: 2,
    connections: canvas.connections.length,
    toasts: toasts.slice(),
    persisted: draft().connections.length,
};
flushFrames(sandbox);
out.repaint.paths_repainted = lines().length;
/* A wire to a node that is gone must not paint a path to nowhere. */
canvas.connections = [{ from: rA, to: 'ghost' }];
canvas.updateConnections();
out.repaint.orphan = { lines: lines().length };

/* ── folding, and that a reload keeps it ───────────────────────────── */
freshWorld();
const fold = addNode('process', 0, 0);
canvas.toggleFold(fold);
const foldEl = doc.getElementById(fold);
out.fold = {
    folded: foldEl.classList.contains('node-folded'),
    contentHidden: foldEl.querySelector('.node-content').style.display,
    actionsHidden: foldEl.querySelector('.node-actions').style.display,
    persisted: draft().nodes[fold].folded,
};
/* Captured while it is still folded: the reload below must reproduce THIS draft. */
const foldedDraft = sandbox.localStorage.getItem('crawler_canvas');
canvas.toggleFold(fold);
out.fold.unfolded = {
    folded: doc.getElementById(fold).classList.contains('node-folded'),
    contentShown: doc.getElementById(fold).querySelector('.node-content').style.display === '',
    persisted: draft().nodes[fold].folded,
};
const foldsBefore = Object.keys(canvas.nodes).length;
canvas.toggleFold('not-a-node');
out.fold.missing_node_is_harmless = Object.keys(canvas.nodes).length === foldsBefore;
/* The round trip through the draft is what a page reload performs. */
freshWorld();
sandbox.localStorage.setItem('crawler_canvas', foldedDraft);
canvas.init();
out.fold.after_reload = {
    folded: doc.getElementById(fold).classList.contains('node-folded'),
    contentHidden: doc.getElementById(fold).querySelector('.node-content').style.display,
};

/* ── zoom and view ─────────────────────────────────────────────────── */
freshWorld();
addNode('source', 0, 0);
canvas.zoomIn();
canvas.zoomIn();
out.zoom = {
    afterTwoIns: Math.round(canvas.zoom * 100) / 100,
    transform: doc.getElementById('canvas-inner').style.transform,
    status: doc.getElementById('status-zoom').textContent,
};
for (let i = 0; i < 40; i += 1) canvas.zoomIn();
out.zoom.ceiling = canvas.zoom;
canvas.zoom = 1;
for (let i = 0; i < 40; i += 1) canvas.zoomOut();
out.zoom.floor = canvas.zoom;
/* The pan is rounded to whole device pixels; a fractional zoom is legitimate. */
canvas.panX = 10.6;
canvas.panY = -3.4;
canvas.updateTransform();
out.zoom.pan_rounded = doc.getElementById('canvas-inner').style.transform;

freshWorld();
const vA = addNode('source', 100, 100);
const vB = addNode('output', 300, 300);
canvas.resetView();
out.reset_view = {
    zoom: canvas.zoom,
    /* Two nodes centred at (210,160) and (410,360): the mean, pulled to the
       middle of the 1920x1080 window the stub reports. */
    panX: canvas.panX,
    panY: canvas.panY,
    status: doc.getElementById('status-zoom').textContent,
};
freshWorld();
canvas.resetView();
out.reset_view_no_nodes = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };

/* ── autoLayout ────────────────────────────────────────────────────── */
freshWorld();
const l1 = addNode('source', 5, 7);
const l2 = addNode('process', 900, 800);
const l3 = addNode('output', 13, 41);
canvas.connections = [{ from: l1, to: l2 }, { from: l2, to: l3 }];
canvas.autoLayout();
const box = (ids) => ids.map((id) => {
    const el = doc.getElementById(id);
    return [parseFloat(el.style.left), parseFloat(el.style.top)];
});
const laid = box([l1, l2, l3]);
out.auto_layout = {
    positions: laid,
    dependencyOrderPreserved: laid[0][0] < laid[1][0] && laid[1][0] < laid[2][0],
    noOverlap: new Set(laid.map(String)).size === 3,
    persisted: Object.values(draft().nodes).map((n) => [n.x, n.y]),
    toasts: toasts.slice(),
};
freshWorld();
canvas.autoLayout();
out.auto_layout_empty = { survived: true };
freshWorld();
const iA = addNode('source', 0, 0);
const iB = addNode('output', 0, 0);
canvas.autoLayout();
const islands = box([iA, iB]);
out.auto_layout_two_components = { positions: islands, separated: islands[0][1] !== islands[1][1] };

/* ── editNode / openSettings / closeSettings (all real) ────────────── */
freshWorld();
const e1 = addNode('source', 0, 0);
const panel = doc.getElementById('node-settings');
canvas.editNode(e1);
const openBtn = doc.getElementById(e1).querySelector('.node-action-btn');
out.edit = {
    settingsNode: canvas._settingsNodeId,
    selected: canvas.selectedNode,
    panelOpen: panel.classList.contains('open'),
    buttonMarked: openBtn.classList.contains('settings-open'),
    /* The real panel renders into #settings-content — proof it is the shipped
       renderer rather than an empty div left over from a stub. */
    panelFilled: doc.getElementById('settings-content').children.length > 0,
};
/* The same node again is a toggle: it must close and clear the marker. */
canvas.editNode(e1);
out.edit.toggled_off = {
    settingsNode: canvas._settingsNodeId,
    panelOpen: panel.classList.contains('open'),
    buttonMarked: doc.getElementById(e1).querySelector('.node-action-btn').classList.contains('settings-open'),
};
canvas.editNode(e1);
out.edit.reopened = { settingsNode: canvas._settingsNodeId, panelOpen: panel.classList.contains('open') };
/* Deleting the node the panel describes must take the panel with it. */
canvas.deleteNode(e1);
canvas.closeSettingsIfStale();
out.edit.stale_closed = { settingsNode: canvas._settingsNodeId, panelOpen: panel.classList.contains('open') };
freshWorld();
canvas.editNode('missing-node');
out.edit.missing_node = {
    settingsNode: canvas._settingsNodeId,
    panelOpen: doc.getElementById('node-settings').classList.contains('open'),
};

/* ── the real renameNode dialog ────────────────────────────────────── */
async function renameScenarios() {
    const results = {};

    freshWorld();
    const r1 = addNode('source', 0, 0);
    dialogAnswer = '  我的爬虫  ';
    await canvas.renameNode(r1);
    results.typed = {
        title: canvas.nodes[r1].title,
        stamped: doc.getElementById(r1).querySelector('.node-title').textContent,
        persisted: draft().nodes[r1].title,
        dialog: dialogs[0],
    };

    dialogAnswer = '   ';
    await canvas.renameNode(r1);
    results.cleared_to_type_label = {
        title: canvas.nodes[r1].title,
        stamped: doc.getElementById(r1).querySelector('.node-title').textContent,
    };

    const before = canvas.nodes[r1].title;
    dialogAnswer = null;
    await canvas.renameNode(r1);
    results.cancelled_leaves_it_alone = canvas.nodes[r1].title === before;

    dialogAnswer = '改名';
    await canvas.renameNode('no-such-node');
    results.missing_node_makes_no_dialog = dialogs.length === 3;

    /* An empty answer falls back to the type's own label, read through the
       current language — so a Chinese dialog gives a Chinese name. */
    freshWorld();
    const r2 = addNode('process', 0, 0);
    dialogAnswer = '';
    await canvas.renameNode(r2);
    const englishLabel = canvas.nodes[r2].title;
    I18n.lang = 'zh';
    dialogAnswer = '';
    await canvas.renameNode(r2);
    results.follows_language_after_clear = {
        englishLabel,
        chineseLabel: canvas.nodes[r2].title,
        changed: canvas.nodes[r2].title !== englishLabel,
        stamped: doc.getElementById(r2).querySelector('.node-title').textContent,
    };
    I18n.lang = 'en';
    return results;
}

/* ── delegated pointer wiring on a node ────────────────────────────── */
freshWorld();
out.wiring = {};
const w1 = addNode('source', 40, 60);
const header = doc.getElementById(w1).querySelector('.node-header');
dispatchOn(header, 'mousedown', ev({ clientX: 140, clientY: 160, target: { closest: () => null } }));
out.wiring.drag = {
    isDragging: canvas.isDragging,
    dragTargetId: canvas.dragTarget && canvas.dragTarget.id,
    selected: canvas.selectedNode,
};
dispatchDocument(sandbox.__handlers, 'mousemove', { clientX: 240, clientY: 260 });
out.wiring.moved = { left: canvas.dragTarget.style.left, top: canvas.dragTarget.style.top };
dispatchDocument(sandbox.__handlers, 'mouseup', { clientX: 240, clientY: 260, target: { closest: () => null } });
out.wiring.released = {
    isDragging: canvas.isDragging,
    dragTarget: canvas.dragTarget,
    persistedX: draft().nodes[w1].x,
};
/* A mousedown that starts inside the action bar is a button press, not a drag. */
dispatchOn(header, 'mousedown', ev({ target: { closest: (sel) => (sel === '.node-actions' ? { id: 'actions' } : null) } }));
out.wiring.actions_press_does_not_drag = canvas.isDragging === false;
const btns = doc.getElementById(w1).querySelectorAll('.node-action-btn');
out.wiring.no_inline_handlers = {
    /* Behaviour lives in listeners; a `onclick` attribute here would mean the
       id-injection fix regressed. */
    onclickAbsent: btns.map((b) => b.onclick === undefined),
    innerHtmlHasOn: btns.map((b) => /on[a-z]+\s*=/i.test(b._html || '') || /on[a-z]+\s*=/.test(doc.getElementById(w1)._html)),
    titles: btns.map((b) => b.title),
    listenerTypes: btns.map((b) => Object.keys(b._events)),
};
dispatchOn(btns[1], 'click', ev());
out.wiring.delete_button = {
    nodes: Object.keys(canvas.nodes).length,
    status: doc.getElementById('status-nodes').textContent,
    /* The panel that described the deleted node must not stay open on it. */
    settingsNode: canvas._settingsNodeId,
};
dispatchOn(btns[0], 'click', ev());
out.wiring.edit_button_opened_settings = canvas._settingsNodeId !== null;

/* ── workspace: right-drag pan, its threshold, background click ────── */
freshWorld();
const p1 = addNode('source', 0, 0);
canvas.selectNode(p1);
canvas._settingsNodeId = p1;
const workspace = canvas.workspace;
dispatchOn(workspace, 'mousedown', ev({ button: 2, clientX: 300, clientY: 300 }));
out.pan = {
    isPanning: canvas.isPanning,
    deselected: canvas.selectedNode,
    cursor: workspace.style.cursor,
    /* A right-press also dismisses an open context menu, so the panel it was on. */
    contextMenuOpen: doc.getElementById('context-menu').classList.contains('open'),
};
dispatchDocument(sandbox.__handlers, 'mousemove', { clientX: 302, clientY: 302 });
out.pan.below_threshold = { panX: canvas.panX, wasDragging: canvas.panWasDragging };
dispatchDocument(sandbox.__handlers, 'mousemove', { clientX: 400, clientY: 300 });
out.pan.over_threshold = {
    panX: canvas.panX,
    wasDragging: canvas.panWasDragging,
    transform: doc.getElementById('canvas-inner').style.transform,
};
dispatchDocument(sandbox.__handlers, 'mouseup', { clientX: 400, clientY: 300, target: { closest: () => null } });
out.pan.released = { isPanning: canvas.isPanning, cursor: workspace.style.cursor };
/* After a pan, a right-click must NOT pop the menu — the user was moving the page. */
canvas._contextMenuPos = null;
dispatchOn(workspace, 'contextmenu', ev({ clientX: 400, clientY: 300 }));
out.pan.pan_then_contextmenu_suppressed = {
    menuOpen: doc.getElementById('context-menu').classList.contains('open'),
    wasDraggingAfter: canvas.panWasDragging,
};
dispatchOn(workspace, 'contextmenu', ev({ clientX: 220, clientY: 240, target: { closest: () => null } }));
canvas.panWasDragging = false;
dispatchOn(workspace, 'contextmenu', ev({ clientX: 220, clientY: 240, target: { closest: () => null } }));
out.pan.contextmenu_on_empty_canvas = {
    menuOpen: doc.getElementById('context-menu').classList.contains('open'),
    editHidden: doc.getElementById('ctx-edit').style.display,
    contextNode: canvas._contextNode,
};
/* Left-click on the background closes settings; on a node it must not. */
canvas._settingsNodeId = p1;
dispatchOn(workspace, 'mousedown', ev({ button: 0, target: { closest: () => null } }));
out.pan.background_click_closed_settings = canvas._settingsNodeId === null;
canvas.editNode(p1);
dispatchOn(workspace, 'mousedown', ev({
    button: 0,
    target: { closest: (sel) => (sel === '.node' ? doc.getElementById(p1) : null) },
}));
out.pan.node_click_kept_settings = canvas._settingsNodeId === p1;

/* ── context menu contents and actions ─────────────────────────────── */
freshWorld();
const cmNode = addNode('source', 0, 0);
const ctxMenu = doc.getElementById('context-menu');
dispatchOn(workspace, 'contextmenu', ev({
    clientX: 220,
    clientY: 240,
    target: { closest: (sel) => (sel === '.node' ? doc.getElementById(cmNode) : null) },
}));
out.context_menu = {
    open: ctxMenu.classList.contains('open'),
    contextNode: canvas._contextNode,
    foldLabel: doc.getElementById('ctx-fold-node').textContent,
    foldAction: doc.getElementById('ctx-fold-node').dataset.action,
    editVisible: doc.getElementById('ctx-edit').style.display,
    position: [ctxMenu.style.left, ctxMenu.style.top],
};
/* The items are data-action driven through one document click listener. */
const item = (action) => ({ dataset: { action } });
const clickItem = (action, insideMenu = true) => dispatchDocument(sandbox.__handlers, 'click', {
    target: {
        closest: (sel) => {
            if (sel === '#context-menu') return insideMenu ? ctxMenu : null;
            if (String(sel).indexOf('[data-action') === 0) return insideMenu ? item(action) : null;
            return null;
        },
    },
});
clickItem('ctxFoldNode');
out.context_menu.fold_action = {
    folded: doc.getElementById(cmNode).classList.contains('node-folded'),
    stillOpen: ctxMenu.classList.contains('open'),
    nodes: Object.keys(canvas.nodes).length,
};
/* The same node, now folded: the row has to advertise the OPPOSITE action, or the
   second right-click folds a folded node and reads as a dead menu item. */
const onNode = { closest: (sel) => (sel === '.node' ? doc.getElementById(cmNode) : null) };
dispatchOn(workspace, 'contextmenu', ev({ clientX: 220, clientY: 240, target: onNode }));
out.context_menu.on_folded = {
    foldLabel: doc.getElementById('ctx-fold-node').textContent,
    foldAction: doc.getElementById('ctx-fold-node').dataset.action,
};
/* And the clamp is the menu's own box: 8px padding off a 400×300 window with a
   260×180 menu can only be answered by measuring, not by a guessed constant. */
ctxMenu.offsetWidth = 260;
ctxMenu.offsetHeight = 180;
sandbox.innerWidth = 400;
sandbox.innerHeight = 300;
dispatchOn(workspace, 'contextmenu', ev({ clientX: 380, clientY: 290, target: onNode }));
out.context_menu.clamped = { position: [ctxMenu.style.left, ctxMenu.style.top] };
sandbox.innerWidth = 1920;
sandbox.innerHeight = 1080;
canvas._contextNode = cmNode;
clickItem('ctxDeleteNode');
out.context_menu.delete_action = { nodes: Object.keys(canvas.nodes).length, menuClosed: !ctxMenu.classList.contains('open') };
/* A new node from the menu lands at the click position, not at a random one. */
canvas._contextMenuPos = { x: 300, y: 300 };
const beforeNew = Object.keys(canvas.nodes);
clickItem('ctxNewSource');
const added = Object.keys(canvas.nodes).filter((id) => !beforeNew.includes(id));
out.context_menu.new_node = {
    count: added.length,
    /* `_screenToCanvas` divides by zoom (1) and the menu offsets the hotspot. */
    at: added.map((id) => [doc.getElementById(id).style.left, doc.getElementById(id).style.top]),
};
clickItem(null, false);
out.context_menu.outside_click_closes = ctxMenu.classList.contains('open');

/* ── init() ────────────────────────────────────────────────────────── */
freshWorld();
const storedDraft = {
    nodes: { 'node-9': { id: 'node-9', type: 'source', x: 12, y: 34, title: '存档名', params: { keyword: 'k' }, folded: true } },
    connections: [],
    nextId: 10,
};
sandbox.localStorage.setItem('crawler_canvas', JSON.stringify(storedDraft));
canvas.init();
out.init = {
    restored: Object.keys(canvas.nodes),
    title: canvas.nodes['node-9'].title,
    stamped: doc.getElementById('node-9').querySelector('.node-title').textContent,
    contentHidden: doc.getElementById('node-9').querySelector('.node-content').style.display,
    nextId: canvas.nextId,
    status: doc.getElementById('status-nodes').textContent,
    historyLength: canvas._history.length,
};
/* A later drag must not mint the id this draft still holds. */
const reserved = canvas.addNode('source', 1, 1);
out.init.next_id_avoids_the_restored = { id: reserved, taken: reserved !== 'node-9' };
freshWorld();
sandbox.localStorage.setItem('crawler_canvas', '{not json');
canvas.init();
out.init.corrupt_draft = { nodes: Object.keys(canvas.nodes), survived: true };
freshWorld();
sandbox.localStorage.removeItem('crawler_canvas');
canvas.init();
out.init.no_draft = { nodes: Object.keys(canvas.nodes) };

/* ── misc lookups ──────────────────────────────────────────────────── */
freshWorld();
const u1 = addNode('upload', 0, 0);
const u2 = addNode('process', 300, 0);
canvas.connections = [{ from: u1, to: u2 }];
out.upstream = { found: canvas.getUpstreamNodeId(u2), none: canvas.getUpstreamNodeId(u1) };
out.icons = {
    markupHasSvg: doc.getElementById(u1).innerHTML.indexOf('<svg') >= 0,
    summary: canvas.nodes[u1].el.querySelector('.node-content').textContent,
};
/* Deleting a node must delete the wires that touched it, not orphan them. */
const u3 = addNode('output', 600, 0);
canvas.connections.push({ from: u2, to: u3 });
canvas.deleteNode(u2);
out.delete_node_prunes = JSON.parse(JSON.stringify(canvas.connections));

/* Every scenario starts from a clean canvas, so node ids repeat across them. The
   assertions therefore name ids per scenario rather than through one positional
   list, which a scenario inserted earlier in this file would silently shift. */
out.ids = {
    selection: [selA, selB],
    connect: [cFrom, cTo],
    tokenize: [tk, vz],
    repaint: [rA, rB, rC],
    fold,
    edit: e1,
    wiring: w1,
    pan: p1,
    contextMenu: cmNode,
    upstream: [u1, u2],
};

Math.random = realRandom;
renameScenarios().then((renamed) => {
    out.rename = renamed;
    process.stdout.write(JSON.stringify(out));
}).catch((err) => {
    process.stdout.write(JSON.stringify({ error: String(err && err.stack) }));
});
