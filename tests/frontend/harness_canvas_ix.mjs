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

import { baseSandbox, dispatchDocument, dispatchOn, dispatchWindow, fixWindow, flushFrames, resetWorld } from './harness_dom.mjs';

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
    /* Keyboard link-mode (L) sentinels so a scenario asserts WHICH hint fired, not a
       whole translated sentence. */
    'canvas.linkNoSel': 'LINK-NOSEL',
    'canvas.linkHint': 'LINK-HINT',
    'canvas.linkCancel': 'LINK-CANCEL',
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
    'outline.noNodes': 'NO-NODES',
    'outline.noMatch': 'NO-MATCH',
    /* The palette's keyboard/pointer add route: stable sentinels so a scenario asserts the
       toast fired and WHICH node it named, not a whole translated sentence. */
    'palette.added': '{label} added',
    'palette.addHint': 'ADD-HINT',
    /* Copy/paste sentinels so the shortcut scenario asserts a toast fired without pinning
       a whole translated sentence. */
    'toast.nodeCopied': 'COPIED',
    'toast.nodePasted': 'PASTED',
    'toast.nodesCopied': 'NODES-COPIED',
    'toast.nodesPasted': 'NODES-PASTED',
    'toast.nodeJsonCopied': 'JSON-COPIED',
    'toast.nodeJsonInvalid': 'JSON-INVALID',
    'dialog.nodeJsonCopy': 'COPY-PROMPT',
    'dialog.nodeJsonImport': 'IMPORT-PROMPT',
    /* Clipboard drawer sentinels so a scenario asserts WHICH toast/dialog fired and can
       count rendered rows/badges without pinning a whole translated sentence. */
    'toast.clipboardAdded': 'CLIP-ADDED',
    'toast.clipboardCleared': 'CLIP-CLEARED',
    'toast.clipboardTextCopied': 'CLIP-TEXT',
    'clipboard.empty': 'CLIP-EMPTY',
    'clipboard.kindNode': 'NODE',
    'clipboard.kindNodes': '{n} nodes',
    'clipboard.kindText': 'TEXT',
    'clipboard.rename': 'CLIP-RENAME',
    'clipboard.addPrompt': 'CLIP-ADDPROMPT',
    'clipboard.clearConfirm': 'CLIP-CLEARCONFIRM',
    'clipboard.copy': 'CLIP-COPY',
    /* Cycle-refusal and align-applied sentinels, so a scenario asserts WHICH toast fired
       without pinning a whole translated sentence. */
    'toast.connCycle': 'CONN-CYCLE',
    'toast.alignApplied': 'ALIGN-APPLIED',
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
    apply() { },
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
    RunState: { parallel: false, headless: true, setRunning() { }, set() { } },
    resumeBar: { refresh() { } },
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'm', api_key: '' }) },
    /* Settings lives in app.js, which is not loaded here — the canvas only ever
       calls `Settings.save()` to remember a view change, so the interesting part is
       that it was called, and how many times. */
    Settings: { save() { sandbox.__settingsSaves += 1; } },
    __settingsSaves: 0,
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__canvas = canvas; globalThis.__wf = workflow; globalThis.__outline = Outline; globalThis.__clipboard = Clipboard;', sandbox);

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
sandbox.clearInterval = () => { };

const canvas = sandbox.__canvas;
const Outline = sandbox.__outline;
const Clipboard = sandbox.__clipboard;
const doc = sandbox.document;
const updateParam = vm.runInContext('updateParam', sandbox);
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
    canvas.selectedNodes = [];
    canvas.nextId = 1;
    canvas._history = [];
    canvas._historyIdx = -1;
    canvas._clipboardData = null;
    canvas._clipboardNodes = null;
    /* The persisted clipboard board is separate state: a fresh scenario is a fresh page
       with an empty board, or one copy's history would leak into the next scenario's
       eviction/paste assertions. */
    Clipboard.reset();
    sandbox.localStorage.removeItem('crawler_clipboard');
    canvas._settingsNodeId = null;
    canvas.connectingFrom = null;
    canvas._linkFromId = null;
    canvas.tempLine = null;
    canvas._renderPending = false;
    canvas.isDragging = false;
    canvas.isPanning = false;
    canvas.panWasDragging = false;
    canvas.dragTarget = null;
    canvas._panPointers = {};
    canvas._pinchBase = null;
    canvas._gestureMoved = false;
    /* Wheel-stream classifier state: each scenario starts as if the wheel had been quiet
       (a far-past last event), so the first dispatched event is judged on its own
       evidence, not a previous scenario's burst. */
    canvas._lastWheelAt = 0;
    canvas._lastWheelDeltaY = 0;
    canvas._wheelStreamTrackpad = false;
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
/* 适应 and the outline jump EASE the rendered transform, not the state: right after
   the call the camera already sits at its target AND a glide is armed — a CSS
   transition on #canvas-inner. (A browser runs the transition; the harness only
   proves the hook is set, the state is committed, and a gesture cancels it.) */
const inner = doc.getElementById('canvas-inner');
out.view_anim = {
    resetArmsGlide: canvas._viewAnimating === true && /transform/.test(inner.style.transition || ''),
    /* The state is committed synchronously, so the math reads the target at once. */
    resetCommittedTarget: canvas.zoom >= 0.2 && canvas.zoom <= 1,
};
/* A scroll is a manual gesture: it must cancel the glide, so panning never
   rubber-bands behind an animation the user has just overridden. */
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: 0, deltaY: -40, ctrlKey: false, clientX: 200, clientY: 200 }));
out.view_anim.gestureCancelsGlide = canvas._viewAnimating === false && inner.style.transition === '';
/* An explicit 0 ms (the reduced-motion path in a real browser) snaps: no glide armed,
   but the target is still applied to the state. */
canvas._animateViewTo(120, 80, 1, 0);
out.view_anim.instantSnap = { animating: canvas._viewAnimating, panX: canvas.panX, zoom: canvas.zoom };
/* The outline's jump-to-node arms the very same glide. */
canvas.centerOnNode(vA);
out.view_anim.focusArmsGlide = canvas._viewAnimating === true && /transform/.test(inner.style.transition || '');
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

/* 排布顺序 (layout_order) overrides creation order: numbered components stack ascending
   (a LOWER number sits HIGHER), a blank one falls below every numbered one and keeps its
   place among the other blanks. Creation order here is 1,2,3 but the numbers are 2,1,'' so
   the expected top→bottom stack is component-2, component-1, component-3(blank). */
freshWorld();
const oName1 = addNode('name', 0, 0);
const oOut1 = addNode('output', 0, 0);
const oName2 = addNode('name', 0, 0);
const oOut2 = addNode('output', 0, 0);
const oName3 = addNode('name', 0, 0);
const oOut3 = addNode('output', 0, 0);
canvas.connections = [{ from: oName1, to: oOut1 }, { from: oName2, to: oOut2 }, { from: oName3, to: oOut3 }];
canvas.nodes[oName1].params.layout_order = '2';
canvas.nodes[oName2].params.layout_order = '1';
canvas.nodes[oName3].params.layout_order = '';
canvas.autoLayout();
const orderTops = box([oName1, oName2, oName3]).map((b) => b[1]);
out.auto_layout_order = {
    tops: orderTops,
    // component-2 ('1') above component-1 ('2') above component-3 (blank, last)
    numbered_flip: orderTops[1] < orderTops[0],
    numbered_above_blank: orderTops[0] < orderTops[2],
};
/* Control: when nobody numbers anything, the stack stays in creation order. */
freshWorld();
const cA = addNode('name', 0, 0);
const cAO = addNode('output', 0, 0);
const cB = addNode('name', 0, 0);
const cBO = addNode('output', 0, 0);
canvas.connections = [{ from: cA, to: cAO }, { from: cB, to: cBO }];
canvas.autoLayout();
const ctrlTops = box([cA, cB]).map((b) => b[1]);
out.auto_layout_order_default = { a_above_b: ctrlTops[0] < ctrlTops[1] };

/* ── outline sidebar (a jump-to-node navigator) ───────────────────── */
freshWorld();
/* The three rows: a name (head, live), a source far off-screen (live), a visualize
   node we disable (off → dimmed). Object.keys(canvas.nodes) order is creation order,
   which is the flat list the outline shows. */
const oName = addNode('name', 100, 100);
const oSrc = addNode('source', 3000, 2000);
const oVis = addNode('visualize', 500, 400);
canvas.toggleEnabled(oVis);
const collected = Outline._collect();
/* focus(oSrc) must select it AND move the camera so it comes into view. */
const panBefore = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };
Outline.focus(oSrc);
const panAfter = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };
/* toggle: the outline collapses/expands like the palette, persisted to its own key. */
const panelEl = doc.getElementById('outline-panel');
Outline.toggle();
const collapsedOnce = panelEl.classList.contains('collapsed');
const persistedOnce = sandbox.localStorage.getItem('crawler_outline_collapsed');
Outline.toggle();
const collapsedTwice = panelEl.classList.contains('collapsed');
const persistedTwice = sandbox.localStorage.getItem('crawler_outline_collapsed');
/* The list is rebuilt by saveState on every mutation — a bare render() proves the DOM shape. */
Outline.render();
const listEl = doc.getElementById('outline-list');
const rowEls = listEl.querySelectorAll('.outline-row');
out.outline = {
    count: collected.length,
    labels: collected.map((r) => r.label),
    tags: collected.map((r) => Outline._tag(r.type)),
    offIds: collected.filter((r) => r.off).map((r) => r.id),
    disabledId: oVis,
    focusSelected: canvas.selectedNode,
    focusMoved: panAfter.panX !== panBefore.panX || panAfter.panY !== panBefore.panY,
    focusZoomInRange: panAfter.zoom >= 0.5 && panAfter.zoom <= 1.5,
    // The jump must ZOOM IN past 100% (the fix over the old shrink-only behaviour).
    focusZoomPast100: panAfter.zoom > 1.0,
    focusZoomPct: Math.round(panAfter.zoom * 100),
    statusZoom: doc.getElementById('status-zoom').textContent,
    collapsedOnce,
    collapsedTwice,
    persistedOnce,
    persistedTwice,
    rows: rowEls.length,
    /* A row's data attribute carries its node id (built via createElement, never an
       inline handler keyed by the id). */
    rowIds: rowEls.map((el) => el.dataset.node),
};

/* ── outline filter + Ctrl/Cmd+F finder ───────────────────────────── */
/* removed: relocated to a self-contained scenario before the async chain */


/* The sidebar must mirror the graph's selection — including when the graph is
   DEselected by clicking empty canvas. Previously selectNode/deselectNode never told the
   outline (they are view-only, not saveState), so the last-highlighted row stayed lit after
   the node was deselected, and a plain canvas click never lit the outline row at all. */
canvas.deselectNode();
out.outline_deselect = {
    activeAfterDeselect: doc.getElementById('outline-list').querySelectorAll('.outline-active').length,
};
canvas.selectNode(oName);
out.outline_reselect = {
    activeIds: doc.getElementById('outline-list').querySelectorAll('.outline-active').map((el) => el.dataset.node),
};

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
    /* Screen-reader identity: the box is a named group, labelled by its visible name. */
    const created = {
        role: doc.getElementById(r1).getAttribute('role'),
        aria: doc.getElementById(r1).getAttribute('aria-label'),
    };
    dialogAnswer = '  我的爬虫  ';
    await canvas.renameNode(r1);
    results.created = created;
    results.typed = {
        title: canvas.nodes[r1].title,
        stamped: doc.getElementById(r1).querySelector('.node-title').textContent,
        persisted: draft().nodes[r1].title,
        /* The accessible name must follow the rename, not stay the creation-time type label. */
        aria: doc.getElementById(r1).getAttribute('aria-label'),
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

/* ── wheel: three independent roles (双指平移 / 捏合缩放 / 鼠标滚轮缩放) ── */
/* Each single-event scenario resets the stream classifier and simulates a quiet gap
   (lastWheelAt = 0) so the event is judged on its own evidence, not a prior burst. */
const quietWheel = (extra) => {
    canvas._lastWheelAt = 0; canvas._lastWheelDeltaY = 0; canvas._wheelStreamTrackpad = false;
    canvas.panX = 0; canvas.panY = 0; canvas.zoom = 1;
    dispatchOn(canvas.workspace, 'wheel', ev({ ctrlKey: false, clientX: 200, clientY: 200, ...extra }));
};
freshWorld();

/* 1. A scroll with a horizontal delta is a trackpad → pan FOLLOWING the fingers (the
      wheel delta is negated, so a leftward swipe drags the surface left), zoom untouched. */
quietWheel({ deltaX: -80, deltaY: -20 });
out.wheel = { trackpad: { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom } };

/* 2. A pinch — Chrome/Edge report it as a ctrlKey wheel — zooms in about the cursor. */
quietWheel({ deltaX: 0, deltaY: -100, ctrlKey: true });
out.wheel.ctrlPinch = { zoom: canvas.zoom, status: doc.getElementById('status-zoom').textContent };

/* 3. A lone integer, pure-vertical notch with no trackpad evidence is a MOUSE WHEEL →
      zoom (down = out), and it must NOT pan — this is the restored desktop behaviour. */
quietWheel({ deltaX: 0, deltaY: 120 });
out.wheel.mouseWheel = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };

/* 4. A fractional vertical swipe is a trackpad scroll → pan following the fingers. */
quietWheel({ deltaX: 0, deltaY: -37.5 });
out.wheel.verticalTrackpadSwipe = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };

/* 5. The axis-lock regression, isolated: a diagonal burst whose horizontal component
      flickers to 0 on one event (and whose deltaY is momentarily unchanged, so only the
      sticky stream can save it) must KEEP panning every event, not split into a zoom.
      Three back-to-back events, no quiet gap between them. Negated sum: panX=-(12+0+9),
      panY=-(6+6+4), zoom unchanged. */
canvas._lastWheelAt = 0; canvas._lastWheelDeltaY = 0; canvas._wheelStreamTrackpad = false;
canvas.panX = 0; canvas.panY = 0; canvas.zoom = 1;
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: 12, deltaY: 6, ctrlKey: false, clientX: 200, clientY: 200 }));
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: 0, deltaY: 6, ctrlKey: false, clientX: 200, clientY: 200 }));
dispatchOn(canvas.workspace, 'wheel', ev({ deltaX: 9, deltaY: 4, ctrlKey: false, clientX: 200, clientY: 200 }));
out.wheel.diagonalNoLock = { panX: canvas.panX, panY: canvas.panY, zoom: canvas.zoom };

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

/* ── 新建: the outline sidebar must empty at once and the camera reset to 100% ── */
function newfileScenario() {
    freshWorld();
    const nfA = addNode('source', 10, 10);
    addNode('output', 200, 200);
    canvas.selectedNode = nfA;
    canvas.zoom = 1.5;
    canvas.panX = 120;
    canvas.panY = -40;
    canvas.updateTransform();
    Outline.render();
    const before = doc.getElementById('outline-list').querySelectorAll('.outline-row').length;
    sandbox.__wf.newFile();
    out.newfile = {
        rowsBefore: before,
        zoomAfter: canvas.zoom,
        panAfter: [canvas.panX, canvas.panY],
        statusAfter: doc.getElementById('status-zoom').textContent,
        nodesAfter: Object.keys(canvas.nodes).length,
        selectedAfter: canvas.selectedNode,
        rowsAfter: doc.getElementById('outline-list').querySelectorAll('.outline-row').length,
        emptyShown: !!doc.getElementById('outline-list').querySelector('.outline-empty'),
    };
}

/* ── outline filter + Ctrl/Cmd+F finder (self-contained; last, before the chain) ── */
/* It runs its own freshWorld + canvas.init because resetWorld clears the document
   handlers; giving it its own three nodes keeps it from leaking selection/collapse state
   into the deselect/reselect scenario that follows the shared outline block above. */
freshWorld();
canvas.init();
Outline.init(); /* wires the filter box's own 'input' listener that the keystroke drives */
const fName = addNode('name', 100, 100);
const fSrc = addNode('source', 300, 200);
const fVis = addNode('visualize', 500, 400);
/* setFilter narrows by label/type/tag; '' restores the whole map. */
Outline.setFilter('viz');
const fFiltered = doc.getElementById('outline-list').querySelectorAll('.outline-row').map((el) => el.dataset.node);
Outline.setFilter('');
const fAll = doc.getElementById('outline-list').querySelectorAll('.outline-row').length;
/* An impossible query says NO-MATCH, not the empty-canvas NO-NODES wording. */
Outline.setFilter('zzz-no-such');
const fNoMatch = (doc.getElementById('outline-list').querySelector('.outline-empty') || {}).textContent;
/* The 'input' listener Outline.init() wires is what a real keystroke reaches. */
const fBox = doc.getElementById('outline-filter');
fBox.value = 'source';
dispatchOn(fBox, 'input', { target: fBox });
flushFrames(sandbox);
const fInputDriven = doc.getElementById('outline-list').querySelectorAll('.outline-row').length;
fBox.value = '';
dispatchOn(fBox, 'input', { target: fBox });
flushFrames(sandbox);
const fInputCleared = doc.getElementById('outline-list').querySelectorAll('.outline-row').length;
/* Ctrl/Cmd+F expands a collapsed sidebar and leaves the selection untouched (the finder,
   not the fold). */
canvas.selectNode(fSrc);
const fPanel = doc.getElementById('outline-panel');
fPanel.classList.add('collapsed');
dispatchDocument(sandbox.__handlers, 'keydown', { key: 'f', ctrlKey: true, target: doc.body });
out.outline_filter = {
    filtered: fFiltered,
    disabledId: fVis,
    unfiltered: fAll,
    noMatchText: fNoMatch,
    inputDriven: fInputDriven,
    inputCleared: fInputCleared,
    panelExpanded: !fPanel.classList.contains('collapsed'),
    ctrlLeftSelected: canvas.selectedNode === fSrc,
};

/* ── palette keyboard/pointer add route (self-contained) ─────────── */
/* A drag is mouse-only, so before this a keyboard user could not add a node at all. The
   items become real buttons (role + tabindex) whose Enter/Space — or a plain click — call
   addNodeFromPalette, which adds the node, selects it and toasts its type. Its own freshWorld
   + a second init mirrors the outline finder scenario: freshWorld binds whatever palette items
   exist at that moment, so the items are seeded first and the loop picks them up. */
function paletteKeyboardScenario() {
    freshWorld();
    const mk = (type) => {
        const el = doc.createElement('div');
        el.className = 'palette-item';
        el.dataset.type = type;
        doc.body.appendChild(el);
        return el;
    };
    const pSrc = mk('source');
    const pOut = mk('output');
    canvas.init();
    const attrs = { role: pSrc.getAttribute('role'), tabindex: pSrc.tabIndex, title: pSrc.title };
    const before = Object.keys(canvas.nodes).length;
    dispatchOn(pSrc, 'keydown', { key: 'Enter', target: pSrc });
    const afterEnter = Object.keys(canvas.nodes).length;
    const enterId = canvas.selectedNode;
    const toastEnter = toasts[toasts.length - 1];
    dispatchOn(pOut, 'keydown', { key: ' ', target: pOut });
    const afterSpace = Object.keys(canvas.nodes).length;
    dispatchOn(pSrc, 'click', { target: pSrc });
    const afterClick = Object.keys(canvas.nodes).length;
    const emptyId = canvas.addNodeFromPalette('');
    out.palette_keyboard = {
        attrs,
        addedByEnter: afterEnter - before,
        enterIsSource: !!(enterId && canvas.nodes[enterId] && canvas.nodes[enterId].type === 'source'),
        toastEnter,
        addedBySpace: afterSpace - afterEnter,
        addedByClick: afterClick - afterSpace,
        emptyTypeNull: emptyId === null,
    };
}

/* Ctrl+C / Ctrl+V / arrow-nudge keyboard shortcuts (self-contained; freshWorld+init so the
   keydown listener is bound exactly once and a dispatched keystroke does not fire two handlers). */
function nodeClipboardScenario() {
    /* freshWorld() already runs canvas.init() (it wires the document/workspace listeners
       against the empty page), so calling init() again here would bind a SECOND keydown
       listener and every keystroke below would fire twice. */
    freshWorld();
    const nid = addNode('source', 120, 90);
    /* Name it and set a distinctive param, or a paste that dropped the title or the params
       would still "look like it worked". */
    canvas.nodes[nid].title = '源A';
    canvas.nodes[nid].params = { platform: 'weibo', keyword: 'KEEPME' };
    canvas.selectNode(nid);

    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'c', ctrlKey: true, target: doc.body });
    const clip = canvas._clipboardData && {
        type: canvas._clipboardData.type,
        title: canvas._clipboardData.title,
        keyword: canvas._clipboardData.params.keyword,
    };
    const copyToast = toasts[toasts.length - 1];

    const countBefore = Object.keys(canvas.nodes).length;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'v', ctrlKey: true, target: doc.body });
    const pastedId = Object.keys(canvas.nodes).find((id) => id !== nid);
    const pasted = pastedId && {
        title: canvas.nodes[pastedId].title,
        keyword: canvas.nodes[pastedId].params.keyword,
        /* The copy must land a cascade step off the selected node, not on top of it. */
        leftDelta: parseInt(doc.getElementById(pastedId).style.left, 10) - 120,
    };
    const addedByPaste = Object.keys(canvas.nodes).length - countBefore;
    const pasteToast = toasts[toasts.length - 1];

    /* Arrow nudge moves the still-selected node 10px (Shift → 1px). */
    const leftBefore = parseInt(doc.getElementById(nid).style.left, 10);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'ArrowRight', target: doc.body });
    const nudgeStep = parseInt(doc.getElementById(nid).style.left, 10) - leftBefore;
    const topBefore = parseInt(doc.getElementById(nid).style.top, 10);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'ArrowDown', shiftKey: true, target: doc.body });
    const fineStep = parseInt(doc.getElementById(nid).style.top, 10) - topBefore;

    /* Ctrl+C with nothing selected must not overwrite the clipboard. */
    canvas._clipboardData = { type: 'output', title: '', params: {} };
    canvas.selectedNode = null;
    canvas.selectedNodes = [];
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'c', ctrlKey: true, target: doc.body });
    const clipUntouchedWithNoSelection = canvas._clipboardData.type === 'output';

    /* An empty-clipboard Ctrl+V must add nothing. */
    canvas._clipboardData = null;
    const beforeEmptyPaste = Object.keys(canvas.nodes).length;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'v', ctrlKey: true, target: doc.body });
    const emptyPasteAddsNothing = Object.keys(canvas.nodes).length === beforeEmptyPaste;

    out.node_clipboard = {
        clip,
        copyToast,
        addedByPaste,
        pasted,
        pasteToast,
        nudgeStep,
        fineStep,
        clipUntouchedWithNoSelection,
        emptyPasteAddsNothing,
    };
}

/* Drag a clipboard NODE row onto the canvas — the palette drag, but for a saved record.
   It must (a) land at the drop point, (b) reuse the SAME paste funnel (params + title
   survive), (c) leave the palette's text/plain→type route working, and (d) never treat a
   text row as draggable. Self-contained: freshWorld wires both the drawer dragstart and
   the workspace drop listener against the live page. */
function clipDragToCanvasScenario() {
    freshWorld();
    const srcId = addNode('source', 10, 10);
    canvas.nodes[srcId].title = '源Z';
    canvas.nodes[srcId].params = { platform: 'zhihu', keyword: 'DRAGME' };
    canvas.copyNodeToClipboard(srcId);
    const entry = Clipboard.items[Clipboard.items.length - 1];
    Clipboard.render();

    const drawer = doc.getElementById('clipboard-drawer');
    const row = doc.getElementById('clipboard-list').querySelector('[data-clip-id]');

    // The node row is marked draggable, so the browser will even start a drag for it.
    const rowDraggable = row ? row.getAttribute('draggable') : null;

    // A dragstart hands the entry id to the private MIME type, nothing else.
    const dt = { _d: {}, setData(t, v) { this._d[t] = String(v); }, getData(t) { return this._d[t] || ''; }, effectAllowed: '' };
    dispatchOn(drawer, 'dragstart', ev({ target: row, dataTransfer: dt }));
    const dragWroteClipId = dt._d['application/x-canvas-clip'] === entry.id;

    // Dropping it on the workspace pastes ONE node at the drop point, params + title kept.
    const idsBefore = Object.keys(canvas.nodes);
    dispatchOn(canvas.workspace, 'drop', ev({
        target: { closest: () => null }, clientX: 410, clientY: 140,
        dataTransfer: { getData: (t) => (t === 'application/x-canvas-clip' ? entry.id : '') },
    }));
    const dragNew = Object.keys(canvas.nodes).filter((id) => idsBefore.indexOf(id) < 0);
    const pasted = dragNew.length === 1 && canvas.nodes[dragNew[0]]
        ? { keyword: canvas.nodes[dragNew[0]].params.keyword, title: canvas.nodes[dragNew[0]].title }
        : null;

    // The palette's own text/plain route still adds a node of that TYPE.
    const idsBefore2 = Object.keys(canvas.nodes);
    dispatchOn(canvas.workspace, 'drop', ev({
        target: { closest: () => null }, clientX: 410, clientY: 140,
        dataTransfer: { getData: (t) => (t === 'text/plain' ? 'output' : '') },
    }));
    const palNew = Object.keys(canvas.nodes).filter((id) => idsBefore2.indexOf(id) < 0);

    // A drop carrying neither type adds nothing.
    const idsBefore3 = Object.keys(canvas.nodes).length;
    dispatchOn(canvas.workspace, 'drop', ev({ target: { closest: () => null }, dataTransfer: { getData: () => '' } }));
    const emptyAddsNothing = Object.keys(canvas.nodes).length === idsBefore3;

    // A TEXT row is not draggable and drags nothing onto the canvas.
    Clipboard.add({ kind: 'text', payload: 'plain note' });
    Clipboard.render();
    const textRow = doc.getElementById('clipboard-list').children
        .find((c) => c.tagName === 'DIV' && c.getAttribute('draggable') === null);
    const dt2 = { _d: {}, setData(t, v) { this._d[t] = String(v); }, getData(t) { return this._d[t] || ''; }, effectAllowed: '' };
    dispatchOn(drawer, 'dragstart', ev({ target: textRow, dataTransfer: dt2 }));

    out.clip_drag_to_canvas = {
        rowDraggable,
        dragWroteClipId,
        pastedOne: dragNew.length === 1,
        pastedKeyword: pasted ? pasted.keyword : null,
        pastedTitle: pasted ? pasted.title : null,
        paletteAddedOne: palNew.length === 1,
        paletteIsOutput: palNew.length === 1 && canvas.nodes[palNew[0]].type === 'output',
        emptyAddsNothing,
        textRowNotDraggable: !!textRow,
        textDragWroteNothing: dt2._d['application/x-canvas-clip'] === undefined,
    };
}

/* ── keyboard node-connect (L link mode) + the connectNodes seam ───── */
/* The wire that used to be creatable only by dragging an out-port onto an in-port is now
   also reachable from the keyboard. `connectNodes` is the single synchronous model mutation
   (edge + tokenize↔visualize coupling) shared by the pointer path and link mode; the async
   fan-in/fan-out warning is separate and stays silent for a first parent. Every source→
   target used here is a single-parent wire, so `_afterConnectWarning` no-ops and the
   connection is readable immediately. */
function keyboardConnectScenario() {
    const res = {};

    /* connectNodes: create once; a duplicate and a self-edge are refused and write nothing. */
    freshWorld();
    const a = addNode('source', 0, 0);
    const b = addNode('output', 400, 0);
    const first = canvas.connectNodes(a, b);
    const dup = canvas.connectNodes(a, b);
    const selfEdge = canvas.connectNodes(a, a);
    res.direct = {
        firstOk: first.ok === true,
        dupOk: dup.ok === false,
        selfOk: selfEdge.ok === false,
        count: canvas.connections.length,
    };

    /* The coupling lives in connectNodes now, not finishConnection: wiring tokenize→visualize
       still rewrites output_mode to word_freq. */
    freshWorld();
    const tk = addNode('tokenize', 0, 0);
    const vz = addNode('visualize', 400, 0);
    canvas.nodes[tk].params.output_mode = 'words_only';
    canvas.connectNodes(tk, vz);
    res.tokenizeCoupling = { mode: canvas.nodes[tk].params.output_mode };

    /* Link mode with L: select A, L arms the start; select B, L commits A→B and clears. */
    freshWorld();
    const ka = addNode('source', 0, 0);
    const kb = addNode('analysis', 400, 0);
    canvas.selectNode(ka);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body });
    const armed = canvas._linkFromId;
    canvas.selectNode(kb);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body });
    res.linkMode = {
        armedFrom: armed === ka,
        armedToast: toasts[0],
        created: canvas.connections.some((c) => c.from === ka && c.to === kb),
        clearedAfter: canvas._linkFromId === null,
    };

    /* L with nothing selected: the no-selection hint fires and NO start is armed. */
    freshWorld();
    toasts.length = 0;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body });
    res.linkNoSelection = { linkFrom: canvas._linkFromId, toast: toasts[toasts.length - 1] };

    /* Escape clears an armed start. */
    freshWorld();
    const ea = addNode('source', 0, 0);
    canvas.selectNode(ea);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body });
    const armedBeforeEscape = canvas._linkFromId;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Escape', target: doc.body });
    res.linkEscapeClears = { armed: armedBeforeEscape === ea, afterEscape: canvas._linkFromId };

    /* L on the same node twice (start re-pressed) cancels the mode and wires nothing. */
    freshWorld();
    const ca = addNode('source', 0, 0);
    canvas.selectNode(ca);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body });
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body });
    res.linkSameStartCancel = { connections: canvas.connections.length, linkFrom: canvas._linkFromId };

    /* A second L would start a fresh link, not a stuck mode. */
    freshWorld();
    const sa = addNode('source', 0, 0);
    canvas.selectNode(sa);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body }); // arm
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body }); // cancel (same node)
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'l', target: doc.body }); // arm again
    res.linkRetriable = { armedAgain: canvas._linkFromId === sa };

    out.keyboard_connect = res;
}

/* Cross-canvas share: copy a node to a JSON snippet on the OS clipboard, and add a node back
   from such a snippet. Async (clipboard + dialog are promise-based), so it joins the .then chain.
   The copied node is a `process`, not a `source`, so its seeding never fires an async capability
   fetch that could rewrite the draft behind this scenario's back. */
async function nodeJsonScenario() {
    freshWorld();
    const written = [];
    sandbox.navigator = { clipboard: { writeText: (t) => { written.push(String(t)); return Promise.resolve(); } } };
    const nid = addNode('process', 140, 60);
    canvas.nodes[nid].title = '处理源';
    canvas.nodes[nid].params = { operation: 'keyword' };
    canvas._contextNode = nid;

    const copyOk = await canvas.copyNodeAsJson(nid);
    const copy = {
        ok: copyOk,
        wrote: written.length,
        parsed: written.length ? JSON.parse(written[0]) : null,
        toast: toasts[toasts.length - 1],
    };

    const before = Object.keys(canvas.nodes).length;
    dialogAnswer = JSON.stringify({ type: 'source', title: '导入源', params: { platform: 'weibo', keyword: 'IMP' } });
    const newId = await canvas.importNodeFromJson({ x: 220, y: 220 });
    const imp = {
        added: Object.keys(canvas.nodes).length - before,
        madeNode: !!newId,
        node: newId && canvas.nodes[newId]
            ? { type: canvas.nodes[newId].type, title: canvas.nodes[newId].title, keyword: canvas.nodes[newId].params.keyword }
            : null,
    };

    /* Garbage → refused, no node, invalid toast. */
    const beforeBad = Object.keys(canvas.nodes).length;
    dialogAnswer = '这不是 JSON';
    const badId = await canvas.importNodeFromJson({ x: 30, y: 30 });
    const bad = { added: Object.keys(canvas.nodes).length - beforeBad, nullReturn: badId === null, toast: toasts[toasts.length - 1] };

    /* A well-formed object with an unknown type → refused (must not mint a broken node). */
    const beforeUT = Object.keys(canvas.nodes).length;
    dialogAnswer = JSON.stringify({ type: 'canner', params: {} });
    const utId = await canvas.importNodeFromJson({ x: 30, y: 30 });
    const unknownType = { added: Object.keys(canvas.nodes).length - beforeUT, nullReturn: utId === null, toast: toasts[toasts.length - 1] };

    /* Cancel (null answer) → no node. */
    const beforeCancel = Object.keys(canvas.nodes).length;
    dialogAnswer = null;
    const cancelId = await canvas.importNodeFromJson({ x: 30, y: 30 });
    const cancelled = { added: Object.keys(canvas.nodes).length - beforeCancel, nullReturn: cancelId === null };

    out.node_json = { copy, imp, bad, unknownType, cancelled };
    dialogAnswer = null;
}

/* ── minimap: bounds/scale math, the drawn boxes, and click-to-recentre ── */
/* The overview box is drawn as an innerHTML string of positioned <i> elements (the DOM stub
   stores innerHTML verbatim, and the real browser lays it out). The geometry is pure, so the
   harness can assert bounds, the click→world inverse, and — crucially — that re-centring is a
   VIEW change only: the model (getState) and the undo history must not move. */
function minimapScenario() {
    const res = {};
    freshWorld();
    canvas.renderMinimap();
    res.empty = {
        boundsNull: canvas._minimapBounds() === null,
        cleared: doc.getElementById('minimap').innerHTML === '',
    };

    freshWorld();
    canvas.workspace.clientWidth = 1200;
    canvas.workspace.clientHeight = 800;
    addNode('source', 0, 0, 200, 100);
    const mB = addNode('output', 1000, 600, 200, 100);
    const b = canvas._minimapBounds();
    res.bounds = { minX: b.minX, minY: b.minY, maxX: b.maxX, maxY: b.maxY };
    const scale = canvas._minimapScale(b, 176);
    res.scale_positive = scale > 0;
    const target = { x: 300, y: 250 };
    const mmpx = { x: 10 + (target.x - b.minX) * scale, y: 10 + (target.y - b.minY) * scale };
    const back = canvas._minimapClickToWorld(mmpx.x, mmpx.y, b, scale);
    res.click_roundtrip = { dx: Math.abs(back.x - target.x), dy: Math.abs(back.y - target.y) };
    canvas.renderMinimap();
    const html = doc.getElementById('minimap').innerHTML || '';
    res.render = {
        nodes: (html.match(/minimap-node/g) || []).length,
        view: (html.match(/minimap-view/g) || []).length,
    };
    canvas.toggleEnabled(mB);
    canvas.renderMinimap();
    res.disabled = ((doc.getElementById('minimap').innerHTML || '').match(/mm-off/g) || []).length === 1;

    freshWorld();
    canvas.workspace.clientWidth = 1200;
    canvas.workspace.clientHeight = 800;
    addNode('source', 0, 0, 200, 100);
    addNode('output', 1000, 600, 200, 100);
    const historyBefore = canvas._history.length;
    const stateBefore = JSON.stringify(canvas.getState());
    canvas._centerWorldPoint(500, 350);
    res.centre = {
        moved: canvas.panX !== 0 || canvas.panY !== 0,
        historyUnchanged: canvas._history.length === historyBefore,
        stateUnchanged: JSON.stringify(canvas.getState()) === stateBefore,
        panX: canvas.panX,
    };
    out.minimap = res;
}

/* ── multi-select: shift-click, batch nudge/delete, and the marquee ── */
function multiSelectScenario() {
    const res = {};

    // Shift-click accumulates; a plain click resets to one.
    freshWorld();
    const sA = addNode('source', 0, 0, 200, 100);
    const sB = addNode('output', 400, 0, 200, 100);
    canvas.selectNode(sA);
    canvas.selectNode(sB, true);
    res.shiftAdd = {
        set: canvas.selectedNodes.slice(),
        anchor: canvas.selectedNode,
        highlighted: doc.querySelectorAll('.node.selected').map((el) => el.id).sort(),
    };
    canvas.selectNode(sA);
    res.plainResets = { set: canvas.selectedNodes.slice() };

    // Batch nudge moves every selected box.
    freshWorld();
    const nA = addNode('source', 0, 0, 200, 100);
    const nB = addNode('output', 400, 0, 200, 100);
    canvas.selectNode(nA);
    canvas.selectNode(nB, true);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'ArrowRight', target: doc.body });
    res.batchNudge = {
        aLeft: parseInt(doc.getElementById(nA).style.left, 10),
        bLeft: parseInt(doc.getElementById(nB).style.left, 10),
    };

    // Batch delete removes both as one edit with one toast.
    freshWorld();
    const dA = addNode('source', 0, 0, 200, 100);
    const dB = addNode('output', 400, 0, 200, 100);
    const dC = addNode('process', 800, 0, 200, 100);
    canvas.selectNode(dA);
    canvas.selectNode(dB, true);
    toasts.length = 0;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Delete', target: doc.body });
    res.batchDelete = {
        remaining: Object.keys(canvas.nodes).sort(),
        survivor: dC,
        toast: toasts[toasts.length - 1],
        setAfter: canvas.selectedNodes.slice(),
    };

    // Marquee selects the nodes its rectangle overlaps.
    freshWorld();
    canvas.workspace.clientWidth = 1920;
    canvas.workspace.clientHeight = 1080;
    const qA = addNode('source', 0, 0, 200, 100);
    const qB = addNode('output', 100, 0, 200, 100);
    const qC = addNode('process', 1000, 1000, 200, 100);
    dispatchOn(canvas.workspace, 'pointerdown', ev({ button: 0, clientX: 0, clientY: 0, target: { closest: () => null } }));
    dispatchDocument(sandbox.__handlers, 'pointermove', { clientX: 350, clientY: 150, target: { closest: () => null } });
    dispatchDocument(sandbox.__handlers, 'pointerup', { clientX: 350, clientY: 150, target: { closest: () => null } });
    res.marquee = { set: canvas.selectedNodes.slice().sort(), expected: [qA, qB].sort(), anchor: canvas.selectedNode };

    // A background click that never moved selects nothing (stays a plain deselect).
    freshWorld();
    addNode('source', 0, 0, 200, 100);
    dispatchOn(canvas.workspace, 'pointerdown', ev({ button: 0, clientX: 5, clientY: 5, target: { closest: () => null } }));
    dispatchDocument(sandbox.__handlers, 'pointerup', { clientX: 5, clientY: 5, target: { closest: () => null } });
    res.clickNoDrag = { set: canvas.selectedNodes.slice() };

    // Batch copy → paste adds all as a single undo step and selects the new copies.
    freshWorld();
    const bA = addNode('source', 0, 0, 200, 100);
    const bB = addNode('process', 400, 0, 200, 100);
    canvas.setSelectedNodes([bA, bB]);
    toasts.length = 0;
    canvas.copySelection();
    const clipLen = (canvas._clipboardNodes || []).length;
    const copyToast = toasts[toasts.length - 1];
    const countBefore = Object.keys(canvas.nodes).length;
    const histBefore = canvas._history.length;
    canvas.pasteNodesAt({ x: 0, y: 500 });
    const pasteToast = toasts[toasts.length - 1];
    const countAfter = Object.keys(canvas.nodes).length;
    const newIds = canvas.selectedNodes.slice();
    res.batchPaste = {
        clipLen,
        copyToast,
        added: countAfter - countBefore,
        // suppressed per-node pushState + one saveState → history grows by a single step
        singleUndoStep: canvas._history.length - histBefore,
        selectedNew: newIds.length === 2 && newIds.indexOf(bA) < 0 && newIds.indexOf(bB) < 0,
        pasteToast,
    };

    // Same-type multi-select: one updateParam lands on every node in the group.
    freshWorld();
    const p1 = addNode('process', 0, 0);
    const p2 = addNode('process', 400, 0);
    const p3 = addNode('process', 800, 0);
    canvas.setSelectedNodes([p1, p2, p3]);
    canvas._settingsNodeId = null; // edit through the function, skip the panel re-open path
    updateParam(p1, 'keyword', '群发到全部');
    res.applyToAll = {
        targets: canvas.multiEditTargets(p1).length,
        all: [p1, p2, p3].map((id) => canvas.nodes[id].params.keyword),
    };

    // A mixed selection must NOT write this type's param onto the other type.
    freshWorld();
    const mp = addNode('process', 0, 0);
    const ms = addNode('source', 400, 0);
    canvas.setSelectedNodes([mp, ms]);
    canvas._settingsNodeId = null;
    const mixedTargets = canvas.multiEditTargets(mp);
    updateParam(mp, 'keyword', '只应落在处理节点');
    res.mixedSelection = {
        targets: mixedTargets.length,
        processGot: canvas.nodes[mp].params.keyword,
        sourceUntouched: canvas.nodes[ms].params.keyword === undefined || canvas.nodes[ms].params.keyword === '',
    };

    out.multi_select = res;
}

/* ── cycle refusal at the single connect seam ──────────────────────── */
/* connectNodes is the ONLY place a wire commits (pointer + link mode both funnel here), so
   a cycle guard at that one seam covers every route. Uses `process` nodes (a `source` copy
   would fire an async capability fetch that rewrites the draft mid-scenario). */
function cycleScenario() {
    const res = {};

    freshWorld();
    const a = addNode('process', 0, 0);
    const b = addNode('process', 400, 0);
    const c = addNode('process', 800, 0);
    res.chain = {
        abOk: canvas.connectNodes(a, b).ok,
        bcOk: canvas.connectNodes(b, c).ok,
    };
    // a reaches c along a→b→c; c does NOT reach a yet.
    res.reaches = { aToC: canvas._reaches(a, c), cToA: canvas._reaches(c, a) };
    // Closing c→a would loop; it must be refused, write nothing, and toast the cycle reason.
    toasts.length = 0;
    const loop = canvas.connectNodes(c, a);
    res.refused = {
        ok: loop.ok,
        count: canvas.connections.length,
        toast: toasts[toasts.length - 1],
    };
    // A fresh target with no back-path still connects normally.
    const d = addNode('process', 1200, 0);
    res.normalStillWorks = canvas.connectNodes(c, d).ok === true && canvas.connections.length === 3;

    out.cycle = res;
}

/* ── align / distribute as ONE undo step ──────────────────────────── */
function alignScenario() {
    const res = {};

    freshWorld();
    const a = addNode('process', 300, 0, 220, 120);
    const b = addNode('process', 0, 400, 220, 120);
    const c = addNode('process', 150, 800, 220, 120);
    canvas.setSelectedNodes([a, b, c]);

    const histBefore = canvas._history.length;
    res.leftResult = canvas.alignSelected('left') === true;
    res.leftPositions = [a, b, c].map((id) => parseInt(doc.getElementById(id).style.left, 10));
    res.historyOneStep = canvas._history.length - histBefore;
    res.toast = toasts[toasts.length - 1];

    // top: every y collapses to the smallest.
    canvas.alignSelected('top');
    res.topPositions = [a, b, c].map((id) => parseInt(doc.getElementById(id).style.top, 10));

    // distributeH: extremes fixed, the middle re-centred so centres are evenly spaced.
    freshWorld();
    const d1 = addNode('process', 0, 0, 220, 120);
    const d2 = addNode('process', 100, 0, 220, 120);
    const d3 = addNode('process', 400, 0, 220, 120);
    canvas.setSelectedNodes([d1, d2, d3]);
    canvas.alignSelected('distributeH');
    const dx = [d1, d2, d3].map((id) => parseInt(doc.getElementById(id).style.left, 10));
    const centres = dx.map((l) => l + 110);
    res.distribute = {
        firstUnchanged: dx[0] === 0,
        lastUnchanged: dx[2] === 400,
        evenSpacing: Math.abs((centres[1] - centres[0]) - (centres[2] - centres[1])) < 1,
    };

    // fewer than two selected is a silent no-op that writes no history.
    freshWorld();
    const solo = addNode('process', 0, 0, 220, 120);
    canvas.setSelectedNodes([solo]);
    const soloHist = canvas._history.length;
    res.singleNoop = canvas.alignSelected('left') === false && canvas._history.length === soloHist;

    out.align = res;
}

/* ── zoom + shortcut-help keyboard bindings ───────────────────────── */
function zoomHelpScenario() {
    const res = {};

    freshWorld();
    addNode('process', 0, 0);
    canvas.zoom = 1;
    const before = canvas.zoom;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: '+', target: doc.body });
    res.zoomIn = canvas.zoom > before;
    const afterIn = canvas.zoom;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: '-', target: doc.body });
    res.zoomOut = canvas.zoom < afterIn;
    // '0' fits: a single node cluster that already fits stays at 100% (shrink-only resetView).
    canvas.zoom = 1;
    dispatchDocument(sandbox.__handlers, 'keydown', { key: '0', target: doc.body });
    res.fitKeeps100 = Math.round(canvas.zoom * 100) === 100;

    // '?' opens the overlay; Escape closes it (the cheat sheet is view chrome, not model).
    freshWorld();
    dispatchDocument(sandbox.__handlers, 'keydown', { key: '?', target: doc.body });
    const helpOpen = doc.getElementById('help-overlay').classList.contains('open');
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Escape', target: doc.body });
    res.helpToggle = { opened: helpOpen, closedOnEscape: !doc.getElementById('help-overlay').classList.contains('open') };

    out.zoom_help = res;
}

/* ── cross-tab clipboard sync via the storage event ───────────────── */
function crossTabClipboardScenario() {
    const res = {};
    freshWorld();
    // Another tab wrote the same key: this tab is still empty, then reloads through the
    // listener that init() registered on window.
    const remote = JSON.stringify({ items: [{ id: 'x', kind: 'text', payload: 'REMOTE', label: 'REMOTE', pinned: false, ts: 1 }] });
    sandbox.localStorage.setItem('crawler_clipboard', remote);
    const emptyBefore = Clipboard.items.length;
    dispatchWindow(sandbox.__handlers, 'storage', { key: 'crawler_clipboard' });
    res.pulledFromStorage = { before: emptyBefore, after: Clipboard.items.length, label: Clipboard.items[0] && Clipboard.items[0].label };
    // An unrelated key must not disturb the board.
    const lenAfterPull = Clipboard.items.length;
    dispatchWindow(sandbox.__handlers, 'storage', { key: 'something_else' });
    res.unrelatedKeyIgnored = Clipboard.items.length === lenAfterPull;
    out.crossTabClipboard = res;
}

/* ── clipboard drawer: the persisted board, its controls, and paste-via-funnel ──
   Async (rename / addText / clear / copyText all await a dialog or the clipboard), so it
   joins the .then chain. Node copies use `process`, not `source`, so no async capability
   fetch can rewrite the draft behind a scenario's back (same reason nodeJsonScenario does). */
async function clipboardScenario() {
    const res = {};

    // A single-node copy records exactly one 'node' entry AND stays silent — the copy
    // toast must still be node-copied, proving Clipboard.add does not overwrite it.
    freshWorld();
    const n1 = addNode('process', 100, 100);
    canvas.nodes[n1].title = 'P-源';
    canvas.nodes[n1].params = { operation: 'keyword', keyword: 'KP' };
    canvas.selectNode(n1);
    canvas.copyNodeToClipboard(n1);
    res.singleCopy = {
        entries: Clipboard.items.length,
        kind: Clipboard.items[0] && Clipboard.items[0].kind,
        label: Clipboard.items[0] && Clipboard.items[0].label,
        slotStillSet: canvas._clipboardData && canvas._clipboardData.type === 'process',
        toast: toasts[toasts.length - 1],
    };

    // A batch copy records one 'nodes' entry sized to the selection.
    freshWorld();
    const b1 = addNode('process', 0, 0);
    const b2 = addNode('process', 400, 0);
    canvas.setSelectedNodes([b1, b2]);
    canvas.copySelection();
    res.batchCopy = {
        entries: Clipboard.items.length,
        kind: Clipboard.items[0] && Clipboard.items[0].kind,
        payloadLen: Clipboard.items[0] && Clipboard.items[0].payload.length,
    };

    // Pasting a stored entry funnels through canvas._pasteAt: it adds the node, is an
    // undo step, carries the copied param, and the board lives in its OWN key, not the
    // canvas draft.
    freshWorld();
    const ps = addNode('process', 0, 0);
    canvas.nodes[ps].params = { operation: 'keyword', keyword: 'ONLYCLIP' };
    canvas.selectNode(ps);
    canvas.copyNodeToClipboard(ps);
    const entryId = Clipboard.items[0].id;
    const countBefore = Object.keys(canvas.nodes).length;
    const histBefore = canvas._history.length;
    const pastedId = Clipboard.paste(entryId, { x: 30, y: 40 });
    res.paste = {
        madeNode: !!pastedId,
        added: Object.keys(canvas.nodes).length - countBefore,
        historyGrew: canvas._history.length > histBefore,
        keyword: pastedId && canvas.nodes[pastedId] ? canvas.nodes[pastedId].params.keyword : null,
        boardKeySeparate: sandbox.localStorage.getItem('crawler_clipboard') !== null,
    };

    // Rename (dialog) + pin + remove all mutate the board.
    freshWorld();
    const r1 = addNode('process', 0, 0);
    canvas.copyNodeToClipboard(r1);
    const rid = Clipboard.items[0].id;
    dialogAnswer = '自定义名字';
    await Clipboard.rename(rid);
    Clipboard.togglePin(rid);
    res.mutations = {
        renamed: Clipboard.items[0].label === '自定义名字',
        pinned: Clipboard.items[0].pinned === true,
    };
    Clipboard.remove(rid);
    res.mutations.afterRemove = Clipboard.items.length;

    // The cap trims to CLIPBOARD_MAX=50 ...
    freshWorld();
    for (let i = 0; i < 52; i++) Clipboard.add({ kind: 'text', payload: 't' + i });
    res.cap = { len: Clipboard.items.length };

    // ... and eviction SPARES a pinned entry while dropping the oldest unpinned ones.
    freshWorld();
    Clipboard.add({ kind: 'text', payload: 'KEEPME' });
    const keepId = Clipboard.items[0].id;
    Clipboard.togglePin(keepId);
    for (let i = 0; i < 60; i++) Clipboard.add({ kind: 'text', payload: 'f' + i });
    res.pinImmune = {
        len: Clipboard.items.length,
        keepSurvives: Clipboard.items.some((it) => it.id === keepId && it.payload === 'KEEPME'),
    };

    // Search filters the rendered rows; clear-all empties the board with a toast.
    freshWorld();
    Clipboard.add({ kind: 'text', payload: 'alpha' });
    Clipboard.add({ kind: 'text', payload: 'beta' });
    Clipboard.setQuery('alph');
    const rowsHtml = doc.getElementById('clipboard-list').innerHTML;
    res.filter = { alphaShown: rowsHtml.indexOf('alpha') >= 0, betaHidden: rowsHtml.indexOf('beta') < 0 };
    Clipboard.setQuery('');
    dialogAnswer = 'clear';
    await Clipboard.requestClearAll();
    res.clear = { len: Clipboard.items.length, toast: toasts[toasts.length - 1] };

    // addText records a text entry; a node-JSON text inserts a node, garbage is refused.
    freshWorld();
    dialogAnswer = 'hello clipboard';
    const added = await Clipboard.addText();
    res.addText = {
        entry: !!added,
        kind: Clipboard.items[0] && Clipboard.items[0].kind,
        toast: toasts[toasts.length - 1],
    };
    const jsonText = JSON.stringify({ type: 'process', title: 'X', params: { operation: 'keyword', keyword: 'INS' } });
    const jtId = Clipboard.add({ kind: 'text', payload: jsonText });
    const beforeIns = Object.keys(canvas.nodes).length;
    const insId = Clipboard.insertText(jtId, { x: 10, y: 10 });
    res.insertText = {
        added: Object.keys(canvas.nodes).length - beforeIns,
        keyword: insId && canvas.nodes[insId] ? canvas.nodes[insId].params.keyword : null,
    };
    const badId = Clipboard.add({ kind: 'text', payload: 'not json' });
    const beforeBad = Object.keys(canvas.nodes).length;
    toasts.length = 0;
    const badIns = Clipboard.insertText(badId, { x: 10, y: 10 });
    res.insertBad = { added: Object.keys(canvas.nodes).length - beforeBad, nullReturn: badIns === null, toast: toasts[toasts.length - 1] };

    // copyText writes to the OS clipboard and toasts; the board survives a reload read.
    freshWorld();
    const written = [];
    sandbox.navigator = { clipboard: { writeText: (t) => { written.push(String(t)); return Promise.resolve(); } } };
    const ctId = Clipboard.add({ kind: 'text', payload: 'to-os' });
    await Clipboard.copyText(ctId);
    res.copyText = { wrote: written[0], toast: toasts[toasts.length - 1] };

    freshWorld();
    const p1 = addNode('process', 0, 0);
    canvas.copyNodeToClipboard(p1);
    const savedLen = Clipboard.items.length;
    Clipboard.load();
    res.persist = { savedLen, reloadedLen: Clipboard.items.length, same: savedLen === 1 && Clipboard.items.length === 1 };

    out.clipboard = res;
}

/* ── WASD spatial navigation + Enter opens settings ───────────────────
   Arrows nudge the selected node (nodeClipboardScenario pins that); W/A/S/D must move
   the SELECTION to the nearest node in that direction without nudging, and Enter opens
   the selected node's panel. This is the canvas's own traversal, so it is asserted here
   against the real keydown handler. */
function keyboardNavigationScenario() {
    freshWorld();
    const realOpenSettings = sandbox.openSettings;
    let enterOpens = 0;
    sandbox.openSettings = () => { enterOpens += 1; };
    const A = addNode('source', 0, 0, 100, 60);      // centre 50,30
    const B = addNode('output', 300, 0, 100, 60);    // centre 350,30 (right of A)
    const C = addNode('output', 0, 300, 100, 60);    // centre 50,330 (below A)
    canvas.selectNode(A);

    const key = (k, extra = {}) => dispatchDocument(sandbox.__handlers, 'keydown', { key: k, target: doc.body, ...extra });

    key('d');
    const afterD = canvas.selectedNode;              // expect B
    const nudgedByWasd = parseInt(doc.getElementById(B).style.left, 10) !== 300; // must NOT move
    key('a');
    const afterA = canvas.selectedNode;              // expect A
    key('s');
    const afterS = canvas.selectedNode;              // expect C
    key('w');
    const afterW = canvas.selectedNode;              // expect A

    // Enter opens the selected node's settings; a focused button keeps its own Enter.
    canvas.selectNode(B);
    key('Enter');
    const enterForNode = enterOpens;
    const btn = doc.createElement('button');
    doc.body.appendChild(btn);
    dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Enter', target: btn });
    const enterFromButton = enterOpens;

    // Enter again on the canvas toggles the SAME node's panel closed (editNode is the toggle).
    key('Enter');
    const enterClosesSecond = canvas._settingsNodeId === null;

    // Enter from INSIDE the panel closes it too: a fresh open drops the caret into the first
    // field, so the second Enter lands there and the canvas handler is silent while typing.
    const settingsPanel = doc.getElementById('node-settings');
    const panelField = doc.createElement('input');
    settingsPanel.appendChild(panelField);
    canvas.editNode(B);
    const reopenedForPanel = canvas._settingsNodeId === B;
    dispatchOn(settingsPanel, 'keydown', ev({ key: 'Enter', target: panelField }));
    const panelFieldEnterCloses = canvas._settingsNodeId === null;

    // ... but a control that OWNS Enter keeps it: a textarea (a newline) and a button (it acts).
    canvas.editNode(B);
    const ta = doc.createElement('textarea');
    settingsPanel.appendChild(ta);
    dispatchOn(settingsPanel, 'keydown', ev({ key: 'Enter', target: ta }));
    const textareaKeepsOpen = canvas._settingsNodeId === B;
    const panelBtn = doc.createElement('button');
    settingsPanel.appendChild(panelBtn);
    dispatchOn(settingsPanel, 'keydown', ev({ key: 'Enter', target: panelBtn }));
    const panelButtonKeepsOpen = canvas._settingsNodeId === B;

    // With nothing selected, WASD seeds a selection rather than crashing.
    canvas.deselectNode();
    key('d');
    const seededFromEmpty = !!canvas.selectedNode;

    // Regression: a TALLER node sharing the anchor's row must not be mistaken for one
    // below it — down navigation is gated on box edges, not centre distance.
    freshWorld();
    const tall = addNode('source', 0, 0, 100, 200);      // top 0, but its centre is low
    const anchor = addNode('output', 400, 0, 100, 60);   // anchor centre is higher than tall's
    const below = addNode('output', 400, 400, 100, 60);  // genuinely below the anchor
    canvas.selectNode(anchor);
    key('s');
    const downToBelow = canvas.selectedNode === below;

    sandbox.openSettings = realOpenSettings;

    out.keyboard_navigation = {
        ids: { A, B, C },
        afterD, afterA, afterS, afterW,
        nudgedByWasd,
        enterForNode,
        enterFromButton,
        enterClosesSecond,
        reopenedForPanel,
        panelFieldEnterCloses,
        textareaKeepsOpen,
        panelButtonKeepsOpen,
        seededFromEmpty,
        tall, anchor, below, downToBelow,
    };
}

resizeRepaintScenario();
paletteKeyboardScenario();
nodeClipboardScenario();
clipDragToCanvasScenario();
keyboardNavigationScenario();
keyboardConnectScenario();
minimapScenario();
multiSelectScenario();
cycleScenario();
alignScenario();
zoomHelpScenario();
crossTabClipboardScenario();
connectWarningsScenarios()
    .then(() => touchGestureScenario())
    .then(() => renameScenarios())
    .then(() => {
        newfileScenario();
    })
    .then(() => nodeJsonScenario())
    .then(() => clipboardScenario())
    .then(() => {
        process.stdout.write(JSON.stringify(out));
    })
    .catch((err) => {
        process.stdout.write(JSON.stringify({ error: String(err && err.stack) }));
    });
