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
    /* Fan-in / fan-out consequences, as stable sentinels so a scenario asserts WHICH
       outcome fired, not a whole translated sentence. Slots are filled by the stub `t`
       below, exactly as the real I18n.fill does. */
    'conn.fanin.name': 'FANIN-NAME',
    'conn.fanin.ignore': 'FANIN-IGNORE',
    'conn.fanin.first': 'FANIN-FIRST',
    'conn.fanin.source': 'FANIN-SOURCE',
    'conn.fanin.analysis': 'FANIN-ANALYSIS',
    'conn.fanin.merge': 'FANIN-MERGE',
    'conn.fanout': 'FANOUT',
    'conn.help': 'SEE-HELP',
    'conn.undo': 'UNDO',
    'conn.keep': 'KEEP',
    'conn.dismiss': 'DISMISS',
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
    t(k, vars) {
        let s = DICT[LANG][k] || k;
        if (vars) {
            for (const name of Object.keys(vars)) s = s.split('{' + name + '}').join(String(vars[name]));
        }
        return s;
    },
    apply() {},
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    /* The stub has no layout, so nothing resizes on its own: addNode's observer
       registers each box here, and a scenario fires the callback to SAY "the box
       just changed". Without a working observer the product's guard would skip
       wiring, and the test would assert a branch the browser never takes. */
    ResizeObserver: class ResizeObserver {
        constructor(cb) { sandbox.__roCallbacks.push(cb); }
        observe(el) { sandbox.__observed.push(el); }
    },
    __observed: [],
    __roCallbacks: [],
    __fireResizes() {
        /* One batched delivery, the way a frame's resizes arrive together. */
        sandbox.__roCallbacks.forEach((cb) => cb([], null));
    },
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
    dialogs.push({
        message: spec.message,
        initial: spec.input && spec.input.value,
        buttons: (spec.buttons || []).map((b) => b.label),
        toggles: (spec.toggles || []).map((t) => t.id),
    });
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
    canvas._panPointers = {};
    canvas._pinchBase = null;
    canvas._gestureMoved = false;
    canvas.zoom = 1;
    canvas.panX = 0;
    canvas.panY = 0;
    /* The observer is a page-level singleton in the product; a fresh scenario is
       a fresh page, and leaving the old instance cached would make addNode's
       `|| new` guard skip registering where __fireResizes can reach it. */
    canvas._nodeObserver = null;
    toasts.length = 0;
    dialogs.length = 0;
    dialogAnswer = null;
    /* A fresh page has muted nothing: a per-session wire-warning dismissal must not
       leak from one scenario into the next, or a later assertion goes green for the
       wrong reason (the warning was silenced, not absent). */
    canvas._connWarningsDismissed = new Set();
    /* Yesterday's boxes must not receive today's resize: the observer outlives
       the page it was wired on, the scenario does not. */
    sandbox.__observed.length = 0;
    sandbox.__roCallbacks.length = 0;
    /* init() re-resolves the layer references AND wires every document/workspace
       listener against the now-empty page; skipping it leaves the pointer handlers
       attached to the previous scenario's elements. */
    canvas.init();
}

function addNode(type, x = 100, y = 100, w = 220, h = 120) {
    const nid = canvas.addNode(type, x, y);
    /* The stub reports a per-node box so port centres, the hit radius, the
       auto-layout rank advance and reset-view centring can tell sizes apart —
       and so a wide/tall node can actually collide with a fixed lattice.
       Defaults keep every older scenario's numbers byte-identical. */
    const el = doc.getElementById(nid);
    el.offsetLeft = x;
    el.offsetTop = y;
    el.offsetWidth = w;
    el.offsetHeight = h;
    el.querySelectorAll('.node-port').forEach((port) => {
        const px = port.dataset.port === 'in' ? x : x + w;
        port.getBoundingClientRect = () => ({
            left: px - 5, top: y + h / 2 - 5, width: 10, height: 10, right: px + 5, bottom: y + h / 2 + 5,
        });
    });
    return nid;
}

/* The browser tracks offsetLeft/Top from style automatically; the stub must be
   told, so a layout that just wrote style can be measured through the same
   _getPortCenter the wires use. */
function syncGeometry(ids) {
    ids.forEach((id) => {
        const el = doc.getElementById(id);
        el.offsetLeft = parseFloat(el.style.left) || 0;
        el.offsetTop = parseFloat(el.style.top) || 0;
    });
}

function wireDs() {
    return canvas.svgLayer
        .querySelectorAll('.conn-line:not(.temp)')
        .map((l) => l.getAttribute('d') || '');
}

function portOf(id, which) {
    return doc.getElementById(id).querySelectorAll('.node-port').find((p) => p.dataset.port === which);
}

function draft() {
    return JSON.parse(sandbox.localStorage.getItem('crawler_canvas') || 'null');
}

function ev(extra = {}) {
    // pointerType defaults to 'mouse' so a dispatched pointerdown follows the desktop path;
    // a touch-only scenario overrides it with pointerType: 'touch'.
    return { button: 0, pointerType: 'mouse', clientX: 100, clientY: 100, target: { closest: () => null }, ...extra };
}

/** Drop a connection from `fromId`'s out-port onto `toId`'s in-port. */
function dragConnection(fromId, toId) {
    dispatchOn(portOf(fromId, 'out'), 'pointerdown', ev({ target: portOf(fromId, 'out') }));
    const rect = toId === null ? { left: 10, top: 10 } : portOf(toId, 'in').getBoundingClientRect();
    return dispatchDocument(sandbox.__handlers, 'pointerup', {
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
dispatchOn(portOf(cFrom, 'out'), 'pointerdown', ev({ target: portOf(cFrom, 'out') }));
out.connect_started = {
    connectingFrom: canvas.connectingFrom,
    /* The temp line is the only feedback that a wire is being dragged. */
    tempLines: canvas.svgLayer.querySelectorAll('.conn-line.temp').length,
};
dispatchDocument(sandbox.__handlers, 'pointermove', { clientX: 500, clientY: 60 });
out.connect_temp_d = canvas.tempLine.d || '';
/* Finish THIS drag rather than starting a second one, or the line above leaks
   into every later count in this scenario. */
const firstDrop = portOf(cTo, 'in').getBoundingClientRect();
dispatchDocument(sandbox.__handlers, 'pointerup', {
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
dispatchOn(portOf(cTo, 'out'), 'pointerdown', ev());
const beforeCancel = canvas.svgLayer.querySelectorAll('.conn-line.temp').length;
canvas.cancelConnection();
out.connect_cancel = {
    beforeCancel,
    afterCancel: canvas.svgLayer.querySelectorAll('.conn-line.temp').length,
    connectingFrom: canvas.connectingFrom,
};
/* Dropping on empty space creates nothing and ends the drag. */
dispatchOn(portOf(cFrom, 'out'), 'pointerdown', ev());
dispatchDocument(sandbox.__handlers, 'pointerup', { clientX: -5000, clientY: -5000, target: { closest: () => null } });
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
    /* rA→rB→rC sit on one centreline, so the ONLY honest rendering is flat:
       a curve here is the old always-bezier behaviour, not geometry. */
    wire_ds: wireDs(),
};
/* A wire drawn BACKWARD (target left of source) cannot be flat: the straight
   run would cut back through the source box, and the bezier bulge is the route
   around. This pins that the flat rule excludes exactly what it must. */
canvas.connections = [{ from: rA, to: rB }, { from: rB, to: rC }, { from: rC, to: rA }];
canvas.updateConnections();
out.repaint.back_edge_d = wireDs()[2];
canvas.connections = [{ from: rA, to: rB }, { from: rB, to: rC }];
canvas.updateConnections();
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
/* resetView now fits to the WORKSPACE's own box and keeps the top clear of the
   menu bar (menu height + margin), not window.innerWidth — give the stub a known
   viewport and menu height so the view scenarios measure against fixed numbers. */
canvas.workspace.clientWidth = 1920;
canvas.workspace.clientHeight = 1080;
doc.getElementById('top-menu').offsetHeight = 48;
const vA = addNode('source', 100, 100);
const vB = addNode('output', 300, 300);
canvas.resetView();
out.reset_view = {
    zoom: canvas.zoom,
    /* A cluster that already fits stays at 100%; it is re-centred inside the band
       below the 48px menu, so panY is pulled down from the naive 280 to 304. */
    panX: canvas.panX,
    panY: canvas.panY,
    status: doc.getElementById('status-zoom').textContent,
};
freshWorld();
canvas.resetView();
out.reset_view_no_nodes = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };

/* A cluster wider than the viewport: the OLD resetView kept zoom at 100%, so the
   far node sat off-screen and 适应 hid it. Fit must shrink so every projected box
   lands inside the 1920x1080 box the scenario gives the workspace, below the menu. */
freshWorld();
canvas.workspace.clientWidth = 1920;
canvas.workspace.clientHeight = 1080;
doc.getElementById('top-menu').offsetHeight = 48;
const fA = addNode('source', 0, 0);
const fB = addNode('output', 4000, 3000);
canvas.resetView();
const projectFit = (id) => {
    const el = doc.getElementById(id);
    const l = canvas.panX + el.offsetLeft * canvas.zoom;
    const t = canvas.panY + el.offsetTop * canvas.zoom;
    return {
        left: Math.round(l),
        top: Math.round(t),
        right: Math.round(l + el.offsetWidth * canvas.zoom),
        bottom: Math.round(t + el.offsetHeight * canvas.zoom),
    };
};
out.reset_view_fit = {
    zoom: canvas.zoom,
    status: doc.getElementById('status-zoom').textContent,
    boxes: [projectFit(fA), projectFit(fB)],
};

/* ── autoLayout ────────────────────────────────────────────────────── */
freshWorld();
/* The head is deliberately 340 wide and 300 tall — the shape a comments source
   grows into with a pasted link list. Under the old fixed 280×120 lattice it
   bled into the next rank and the one below; that collision is what the
   rectangle test below refuses to accept. */
const l1 = addNode('source', 5, 7, 340, 300);
const l2 = addNode('process', 900, 800);
const l3 = addNode('output', 13, 41);
canvas.connections = [{ from: l1, to: l2 }, { from: l2, to: l3 }];
canvas.autoLayout();
const box = (ids) => ids.map((id) => {
    const el = doc.getElementById(id);
    return [parseFloat(el.style.left), parseFloat(el.style.top)];
});
const laid = box([l1, l2, l3]);
const laidRects = [l1, l2, l3].map((id) => {
    const el = doc.getElementById(id);
    const L = parseFloat(el.style.left);
    const T = parseFloat(el.style.top);
    return { L, T, R: L + el.offsetWidth, B: T + el.offsetHeight };
});
let rectOverlap = false;
for (let i = 0; i < laidRects.length; i++) {
    for (let j = i + 1; j < laidRects.length; j++) {
        const a = laidRects[i];
        const b = laidRects[j];
        if (Math.min(a.R, b.R) - Math.max(a.L, b.L) > 1 && Math.min(a.B, b.B) - Math.max(a.T, b.T) > 1) {
            rectOverlap = true;
        }
    }
}
out.auto_layout = {
    positions: laid,
    dependencyOrderPreserved: laid[0][0] < laid[1][0] && laid[1][0] < laid[2][0],
    noOverlap: !rectOverlap,
    persisted: Object.values(draft().nodes).map((n) => [n.x, n.y]),
    toasts: toasts.slice(),
};
/* Straight wires must MATERIALISE from the layout, not by luck of equal boxes:
   the three ranks have heights 120 / 300 / 120, so under the old equal-TOPS rule
   the middle node's port centre sat 90px off the line and both wires bowed. With
   centre-aligned ranks, both wires are flat. */
freshWorld();
const s1 = addNode('source', 0, 0, 220, 120);
const s2 = addNode('process', 0, 0, 220, 300);
const s3 = addNode('output', 0, 0, 220, 120);
canvas.connections = [{ from: s1, to: s2 }, { from: s2, to: s3 }];
canvas.autoLayout();
syncGeometry([s1, s2, s3]);
canvas.updateConnections();
out.auto_layout_straight = { wire_ds: wireDs() };
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
    out.rename = results;
    return results;
}

/* ── delegated pointer wiring on a node ────────────────────────────── */
freshWorld();
out.wiring = {};
const w1 = addNode('source', 40, 60);
const header = doc.getElementById(w1).querySelector('.node-header');
dispatchOn(header, 'pointerdown', ev({ clientX: 140, clientY: 160, target: { closest: () => null } }));
out.wiring.drag = {
    isDragging: canvas.isDragging,
    dragTargetId: canvas.dragTarget && canvas.dragTarget.id,
    selected: canvas.selectedNode,
};
dispatchDocument(sandbox.__handlers, 'pointermove', { clientX: 240, clientY: 260 });
out.wiring.moved = { left: canvas.dragTarget.style.left, top: canvas.dragTarget.style.top };
dispatchDocument(sandbox.__handlers, 'pointerup', { clientX: 240, clientY: 260, target: { closest: () => null } });
out.wiring.released = {
    isDragging: canvas.isDragging,
    dragTarget: canvas.dragTarget,
    persistedX: draft().nodes[w1].x,
};
/* A mousedown that starts inside the action bar is a button press, not a drag. */
dispatchOn(header, 'pointerdown', ev({ target: { closest: (sel) => (sel === '.node-actions' ? { id: 'actions' } : null) } }));
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
dispatchOn(workspace, 'pointerdown', ev({ button: 2, clientX: 300, clientY: 300 }));
out.pan = {
    isPanning: canvas.isPanning,
    deselected: canvas.selectedNode,
    cursor: workspace.style.cursor,
    /* A right-press also dismisses an open context menu, so the panel it was on. */
    contextMenuOpen: doc.getElementById('context-menu').classList.contains('open'),
};
dispatchDocument(sandbox.__handlers, 'pointermove', { clientX: 302, clientY: 302 });
out.pan.below_threshold = { panX: canvas.panX, wasDragging: canvas.panWasDragging };
dispatchDocument(sandbox.__handlers, 'pointermove', { clientX: 400, clientY: 300 });
out.pan.over_threshold = {
    panX: canvas.panX,
    wasDragging: canvas.panWasDragging,
    transform: doc.getElementById('canvas-inner').style.transform,
};
dispatchDocument(sandbox.__handlers, 'pointerup', { clientX: 400, clientY: 300, target: { closest: () => null } });
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
dispatchOn(workspace, 'pointerdown', ev({ button: 0, target: { closest: () => null } }));
out.pan.background_click_closed_settings = canvas._settingsNodeId === null;
canvas.editNode(p1);
dispatchOn(workspace, 'pointerdown', ev({
    button: 0,
    target: { closest: (sel) => (sel === '.node' ? doc.getElementById(p1) : null) },
}));
out.pan.node_click_kept_settings = canvas._settingsNodeId === p1;

/* ── wheel: trackpad two-finger pan, ctrl/pinch zoom, mouse-wheel zoom ── */
freshWorld();
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: -80, deltaY: -20, ctrlKey: false, clientX: 200, clientY: 200 }));
out.wheel = {
    /* A trackpad scroll carries a horizontal delta → pan the canvas following the scroll,
       zoom untouched. This is the two-finger "移动画布". */
    trackpad: { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom },
};
canvas.panX = 0; canvas.panY = 0; canvas.zoom = 1;
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: 0, deltaY: -100, ctrlKey: true, clientX: 200, clientY: 200 }));
/* Chrome/Edge report a trackpad pinch as a ctrlKey wheel → zoom in about the cursor. */
out.wheel.ctrlPinch = { zoom: canvas.zoom, status: doc.getElementById('status-zoom').textContent };
canvas.panX = 0; canvas.panY = 0; canvas.zoom = 1;
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: 0, deltaY: 120, ctrlKey: false, clientX: 200, clientY: 200 }));
/* A mouse wheel has no horizontal travel and no modifier → keeps the old zoom behaviour. */
out.wheel.mouseWheel = { zoom: canvas.zoom };

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
    pasteVisible: doc.getElementById('ctx-paste-node').style.display,
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
/* 粘贴节点 only means something once something has been copied. */
const copyFirst = addNode('source', 5, 5);
canvas._contextNode = copyFirst;
clickItem('ctxCopy');
dispatchOn(workspace, 'contextmenu', ev({ clientX: 120, clientY: 140, target: { closest: (sel) => (sel === '.node' ? doc.getElementById(copyFirst) : null) } }));
out.context_menu.paste_after_copy = doc.getElementById('ctx-paste-node').style.display;
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

/* ── the comment node's own form (workflow.js renders it by hand) ──── */
freshWorld();
const cf1 = addNode('comment', 0, 0);
canvas.editNode(cf1);
out.comment_form = doc.getElementById('settings-content').innerHTML;

/* ── the box that changes AFTER the wire was drawn ─────────────────── */
/* ── fan-in / fan-out connect warnings ─────────────────────────────── */
const KEEP = { value: true };

/** Draw one wire the way `dragConnection` does, but await the ASYNC finishConnection
 *  directly, so the warning dialog's undo branch (which runs after an await) has
 *  settled before the scenario reads `connections`. */
async function warnDrag(fromId, toId, answer) {
    dialogAnswer = answer;
    canvas.startConnection(fromId, ev());
    const rect = portOf(toId, 'in').getBoundingClientRect();
    await canvas.finishConnection({ clientX: rect.left + 5, clientY: rect.top + 5, target: null });
}
const lastDialog = () => dialogs[dialogs.length - 1];

async function connectWarningsScenarios() {
    const res = {};

    /* process/tokenize/visualize: the FIRST parent feeds it normally (silent); the
       SECOND triggers "only the first is used". */
    freshWorld();
    let s1 = addNode('source', 0, 0);
    const p = addNode('process', 400, 0);
    let s2 = addNode('upload', 0, 200);
    await warnDrag(s1, p, KEEP);
    res.process_first_silent = dialogs.length === 0;
    await warnDrag(s2, p, KEEP);
    res.process_fanin = { msg: lastDialog().message, toggles: lastDialog().toggles, connections: canvas.connections.length };

    /* output merges from the second parent; analysis joins the same; source names one
       consequence without deciding which mode can be fed. */
    freshWorld();
    s1 = addNode('source', 0, 0);
    s2 = addNode('upload', 0, 200);
    const outn = addNode('output', 400, 0);
    await warnDrag(s1, outn, KEEP);
    await warnDrag(s2, outn, KEEP);
    res.output_merge = { msg: lastDialog().message, connections: canvas.connections.length };

    freshWorld();
    s1 = addNode('source', 0, 0);
    s2 = addNode('upload', 0, 200);
    const an = addNode('analysis', 400, 0);
    await warnDrag(s1, an, KEEP);
    await warnDrag(s2, an, KEEP);
    res.analysis_fanin = { msg: lastDialog().message };

    freshWorld();
    s1 = addNode('upload', 0, 0);
    s2 = addNode('resume', 0, 200);
    const src = addNode('source', 400, 0);
    await warnDrag(s1, src, KEEP);
    await warnDrag(s2, src, KEEP);
    res.source_fanin = { msg: lastDialog().message };

    /* upload / comment / resume ignore upstream from the FIRST wire in; name rejects
       any incoming wire. Both fire on a single-parent connection. */
    freshWorld();
    s1 = addNode('source', 0, 0);
    const up = addNode('upload', 400, 0);
    await warnDrag(s1, up, KEEP);
    res.upload_ignore = { msg: lastDialog().message, toggles: lastDialog().toggles };

    freshWorld();
    s1 = addNode('source', 0, 0);
    const nm = addNode('name', 400, 0);
    await warnDrag(s1, nm, KEEP);
    res.name_refused = { msg: lastDialog().message };

    /* Undo: the wire is written, the dialog explains it, "undo" takes it back. */
    freshWorld();
    s1 = addNode('source', 0, 0);
    s2 = addNode('upload', 0, 200);
    let s3 = addNode('resume', 0, 400);
    const out2 = addNode('output', 400, 0);
    await warnDrag(s1, out2, KEEP);
    const before = canvas.connections.length;
    await warnDrag(s2, out2, { value: false });
    res.undo = { before, after: canvas.connections.length, lastToast: toasts[toasts.length - 1] };

    /* Dismiss: ticking "don't warn again" mutes ONLY that category for the session. */
    freshWorld();
    s1 = addNode('source', 0, 0);
    s2 = addNode('upload', 0, 200);
    s3 = addNode('resume', 0, 400);
    const out3 = addNode('output', 400, 0);
    await warnDrag(s1, out3, KEEP);
    await warnDrag(s2, out3, { value: true, toggles: { conn_dismiss_fanin_merge: true } });
    const afterDismiss = dialogs.length;
    await warnDrag(s3, out3, KEEP);
    res.dismiss = { afterDismiss, afterThird: dialogs.length, muted: dialogs.length === afterDismiss };

    /* Fan-out: the first branch off a node explains the snapshot once; a third adds
       nothing new, and the merge target it feeds never re-triggers a fan-in notice. */
    freshWorld();
    s1 = addNode('source', 0, 0);
    const bA = addNode('analysis', 400, 0);
    const bB = addNode('output', 400, 200);
    const bC = addNode('process', 400, 400);
    await warnDrag(s1, bA, KEEP);
    res.fanout_first_silent = dialogs.length === 0;
    await warnDrag(s1, bB, KEEP);
    res.fanout_shown = { msg: lastDialog().message };
    await warnDrag(s1, bC, KEEP);
    res.fanout_third_silent = dialogs.length === 1;

    out.connect_warnings = res;
}

/* ── touch (tablet/phone) gestures: what a finger drives through Pointer ── */
async function touchGestureScenario() {
    const res = {};

    // A finger drag from an out-port to an in-port wires them.
    freshWorld();
    const tA = addNode('source', 0, 0);
    const tB = addNode('analysis', 400, 0);
    const inRect = portOf(tB, 'in').getBoundingClientRect();
    dispatchOn(portOf(tA, 'out'), 'pointerdown', ev({ pointerType: 'touch', target: portOf(tA, 'out') }));
    await canvas.finishConnection({ clientX: inRect.left + 5, clientY: inRect.top + 5 });
    res.wireFromFingerDrag = canvas.connections.some((c) => c.from === tA && c.to === tB);

    // A finger drag across the empty background pans the camera (a tablet has no right button).
    freshWorld();
    addNode('source', 100, 100);
    const panBefore = canvas.panX;
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', clientX: 600, clientY: 600, target: { closest: () => null } }));
    dispatchDocument(sandbox.__handlers, 'pointermove', { pointerType: 'touch', clientX: 500, clientY: 600, target: { closest: () => null } });
    dispatchDocument(sandbox.__handlers, 'pointerup', { pointerType: 'touch', clientX: 500, clientY: 600, target: { closest: () => null } });
    res.backgroundPanByFinger = canvas.panX !== panBefore;

    // A finger drag on a node header moves the node.
    freshWorld();
    const tD = addNode('source', 40, 60);
    const headerD = doc.getElementById(tD).querySelector('.node-header');
    dispatchOn(headerD, 'pointerdown', ev({ pointerType: 'touch', clientX: 140, clientY: 160, target: { closest: () => null } }));
    dispatchDocument(sandbox.__handlers, 'pointermove', { pointerType: 'touch', clientX: 240, clientY: 260, target: { closest: () => null } });
    dispatchDocument(sandbox.__handlers, 'pointerup', { pointerType: 'touch', clientX: 240, clientY: 260, target: { closest: () => null } });
    res.nodeMovedByFinger = doc.getElementById(tD).style.left !== '40px';

    // Two fingers spread apart on the background → pinch zooms IN. The base is the two
    // fingers' landing positions, so one spread already reads as zoom (not a no-op).
    freshWorld();
    addNode('source', 100, 100);
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', pointerId: 11, clientX: 400, clientY: 300 }));
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', pointerId: 12, clientX: 600, clientY: 300 }));
    res.pinchBaseCaptured = canvas._pinchBase !== null;
    const pinchZoomBefore = canvas.zoom;
    dispatchDocument(sandbox.__handlers, 'pointermove', { pointerType: 'touch', pointerId: 12, clientX: 900, clientY: 300, target: { closest: () => null } });
    res.pinchZoomIn = { zoomedIn: canvas.zoom > pinchZoomBefore, status: doc.getElementById('status-zoom').textContent };

    // Two fingers slide together at a CONSTANT distance → pan, and zoom stays exactly 1
    // (a pinch resolves relative to the base, so equal spreads cannot creep the scale).
    freshWorld();
    addNode('source', 100, 100);
    canvas.zoom = 1; canvas.panX = 0; canvas.panY = 0;
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', pointerId: 21, clientX: 300, clientY: 300 }));
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', pointerId: 22, clientX: 500, clientY: 300 }));
    dispatchDocument(sandbox.__handlers, 'pointermove', { pointerType: 'touch', pointerId: 21, clientX: 400, clientY: 300, target: { closest: () => null } });
    dispatchDocument(sandbox.__handlers, 'pointermove', { pointerType: 'touch', pointerId: 22, clientX: 600, clientY: 300, target: { closest: () => null } });
    res.twoFingerSlide = { panned: canvas.panX !== 0, zoomUnchanged: canvas.zoom === 1 };

    // Lift one finger of a pinch: the pan stays claimed for the finger still down; lifting
    // the last one releases the gesture and clears its bookkeeping (never a stuck pan).
    freshWorld();
    addNode('source', 100, 100);
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', pointerId: 31, clientX: 300, clientY: 300 }));
    dispatchOn(canvas.workspace, 'pointerdown', ev({ pointerType: 'touch', pointerId: 32, clientX: 500, clientY: 300 }));
    dispatchDocument(sandbox.__handlers, 'pointermove', { pointerType: 'touch', pointerId: 31, clientX: 350, clientY: 300, target: { closest: () => null } });
    dispatchDocument(sandbox.__handlers, 'pointerup', { pointerType: 'touch', pointerId: 31, clientX: 350, clientY: 300, target: { closest: () => null } });
    res.stillPanningWithOneFinger = canvas.isPanning === true;
    dispatchDocument(sandbox.__handlers, 'pointerup', { pointerType: 'touch', pointerId: 32, clientX: 500, clientY: 300, target: { closest: () => null } });
    res.gestureReleased = canvas.isPanning === false
        && canvas._pinchBase === null
        && canvas._gestureMoved === false
        && Object.keys(canvas._panPointers).length === 0;

    out.touch_gestures = res;
}

function resizeRepaintScenario() {
    freshWorld();
    const fA = addNode('source', 0, 0);
    const fB = addNode('output', 400, 0);
    canvas.connections = [{ from: fA, to: fB }];
    canvas.scheduleRender();
    flushFrames(sandbox);
    const before = wireDs()[0];
    /* Both boxes grow — what the webfont does when it lands, and what
       CustomSelect UNDOES when it collapses a node's raw <select> to a trigger.
       The wire holds literal numbers, so its ends now sit 50px off the ports. */
    doc.getElementById(fA).offsetHeight = 220;
    doc.getElementById(fB).offsetHeight = 220;
    const historyBefore = canvas._history.length;
    const draftBefore = sandbox.localStorage.getItem('crawler_canvas');
    sandbox.__fireResizes();
    out.resize_repaint = {
        wire_before: before,
        wire_after: wireDs()[0],
        /* The repaint happened IN the callback, not in a deferred frame: a queued
           rAF can run before the next layout and re-measure the stale box — which
           is exactly how the fonts.ready fix still missed the CustomSelect step. */
        no_frame_needed: flushFrames(sandbox) === 0,
        no_history_growth: canvas._history.length === historyBefore,
        no_draft_rewrite: sandbox.localStorage.getItem('crawler_canvas') === draftBefore,
    };
}

Math.random = realRandom;
resizeRepaintScenario();
connectWarningsScenarios()
    .then(() => touchGestureScenario())
    .then(() => renameScenarios())
    .then(() => {
        process.stdout.write(JSON.stringify(out));
    })
    .catch((err) => {
        process.stdout.write(JSON.stringify({ error: String(err && err.stack) }));
    });
