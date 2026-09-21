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

import { baseSandbox } from './harness_dom.mjs';

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

const sandbox = { ...baseSandbox(), I18n, RunState: { parallel: false, headless: true }, Settings: { save: () => {} } };
vm.createContext(sandbox);
vm.runInContext(src + '\n;globalThis.__canvas = canvas;', sandbox);

const canvas = sandbox.__canvas;
canvas.nodesContainer = sandbox.__byId('nodes-container');
canvas.workspace = sandbox.__byId('workspace');

const out = {};
for (const sc of scenarios) {
    // Fresh canvas for every scenario.
    canvas.nodes = {};
    canvas.connections = [];
    canvas.nextId = 1;
    canvas._history = [];
    canvas._historyIdx = -1;
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
    if (sc.undo) canvas.undo();
    if (sc.redo) canvas.redo();
    if (sc.setLang) I18n.lang = sc.setLang;
    for (const id of sc.refresh || []) canvas.updateNodeDisplay(id);
    if (sc.deleteNode) canvas.deleteNode(sc.deleteNode);

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
    };
}
process.stdout.write(JSON.stringify(out));
