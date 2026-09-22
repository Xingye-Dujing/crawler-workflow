/* Runs the REAL canvas state machine (backend/static/js/canvas.js) under node.
 *
 * Three user-visible contracts live only in this file and were each broken
 * once already:
 *   · restoreState must re-apply renamed titles BEFORE updateNodeDisplay's
 *     re-stamp (undo/redo or reload used to erase every custom name);
 *   · a node still wearing a DEFAULT label re-stamps when the language
 *     changes — a renamed one keeps its name;
 *   · saveState feeds the undo/redo stacks that Ctrl+Z walks.
 * The harness loads canvas.js with the shared fake DOM and replays scenario
 * scripts, reporting the resulting node/params/title/element-text state.
 *
 * Usage: node harness_state.mjs <path/to/canvas.js> <scenarios.json>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, dispatchOn, fixWindow } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const LABELS = {
    en: {
        'node.source': 'Data Source', 'node.output': 'Output', 'node.upload': 'Upload File',
        'node.comment': 'Comments', 'ctx.renameHint': 'Double-click to rename', 'status.nodes': 'Nodes: ',
    },
    zh: {
        'node.source': '数据源', 'node.output': '输出', 'node.upload': '上传文件',
        'node.comment': '评论采集', 'ctx.renameHint': '双击重命名', 'status.nodes': '节点数：',
    },
};
const I18n = {
    lang: 'en',
    dict: LABELS,
    t(k) {
        const v = (this.dict[this.lang] || {})[k];
        return v === undefined ? (this.dict.en[k] !== undefined ? this.dict.en[k] : k) : v;
    },
};

const toasts = [];
const sandbox = {
    ...baseSandbox(),
    I18n,
    RunState: { parallel: false, headless: true },
    Settings: { save: () => {} },
    showToast: (msg) => toasts.push(msg),
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__canvas = canvas;', sandbox);

const canvas = sandbox.__canvas;
canvas.nodesContainer = sandbox.__byId('nodes-container');
canvas.workspace = sandbox.__byId('workspace');
/* Copy and paste are context-menu items living in a document click listener, so
   the only way to test them faithfully is to register the real handlers and fire
   the same events a right-click produces. */
canvas.setupEvents();

/** Fire an event through every captured document listener. */
function fire(type, target, extra = {}) {
    const ev = { type, target, preventDefault() {}, stopPropagation() {}, clientX: 300, clientY: 220, ...extra };
    (sandbox.__handlers.document[type] || []).forEach((fn) => fn(ev));
}

/** Right-click `nodeId` (or empty canvas when null), then pick a menu item. */
function useNodeMenu(nodeId, action) {
    const noNode = { closest: () => null };
    const onNode = { closest: (sel) => (sel === '.node' ? { id: nodeId } : null) };
    const item = { dataset: { action } };
    const menuTarget = { closest: (sel) => (sel === '#context-menu' || sel === '[data-action]' ? item : null) };
    dispatchOn(canvas.workspace, 'contextmenu', {
        button: 2,
        clientX: 300,
        clientY: 220,
        target: nodeId ? onNode : noNode,
        preventDefault() {},
        stopPropagation() {},
    });
    fire('click', menuTarget);
}

const out = {};
for (const sc of scenarios) {
    // Fresh canvas for every scenario.
    canvas.nodes = {};
    canvas.connections = [];
    canvas.nextId = 1;
    canvas._history = [];
    canvas._historyIdx = -1;
    canvas._clipboardData = null;
    toasts.length = 0;
    I18n.lang = sc.lang || 'en';

    if (sc.restore) canvas.restoreState(sc.restore);
    for (const t of sc.add || []) canvas.addNode(t);
    if (sc.rename) {
        for (const [id, title] of Object.entries(sc.rename)) {
            // renameNode's committed half: node + element both carry the name.
            canvas.nodes[id].title = title;
            canvas.nodes[id].el.querySelector('.node-title').textContent = title;
            canvas.updateNodeDisplay(id);
        }
    }
    if (sc.copy) useNodeMenu(sc.copy, 'ctxCopy');
    for (let i = 0; i < (sc.paste || 0); i++) useNodeMenu(null, 'ctxPasteNode');
    /* Before the undo/redo steps: a scenario that deletes and then rewinds is
       testing what the rewind restores, and applying the delete afterwards would
       silently test the shape of a one-node history instead. */
    if (sc.deleteNode) canvas.deleteNode(sc.deleteNode);
    if (sc.undo) canvas.undo();
    if (sc.redo) canvas.redo();
    if (sc.setLang) I18n.lang = sc.setLang;
    for (const id of sc.refresh || []) canvas.updateNodeDisplay(id);

    out[sc.id] = {
        nodes: Object.values(canvas.nodes).map((n) => ({
            id: n.id,
            type: n.type,
            title: n.title,
            params: n.params,
            elTitle: n.el ? n.el.querySelector('.node-title').textContent : null,
        })),
        connections: canvas.connections,
        serialized: canvas.toWorkflowJSON(),
        historyIdx: canvas._historyIdx,
        historyLen: canvas._history.length,
        clipboard: canvas._clipboardData,
        toasts: toasts.slice(),
    };
}
process.stdout.write(JSON.stringify(out));
