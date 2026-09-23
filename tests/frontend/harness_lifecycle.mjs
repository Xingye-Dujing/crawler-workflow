/* Drives the REAL save/open/new lifecycle (canvas.js + workflow.js) under node.
 *
 * workflow.loadFromJSON/newFile/save are the File menu: a workflow is turned
 * back into nodes (with renamed titles + params + remapped connections) or
 * cleared. This loads BOTH real files in one vm world — so the whole path from
 * the server JSON to live canvas nodes runs untouched — and reports the result.
 * fetch is a recording stub, so save()'s request body is inspectable too.
 *
 * Usage: node harness_lifecycle.mjs <canvas.js> <workflow.js> <scenarios.json> [matrix.json]
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow, readJson } from './harness_dom.mjs';

const [canvasPath, wfPath, scPath, matrixPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scPath, 'utf8'));

const LABELS = {
    en: {
        'node.source': 'Data Source', 'node.output': 'Output', 'node.upload': 'Upload File',
        'node.process': 'Process', 'node.analysis': 'Analysis', 'node.visualize': 'Visualize',
        'node.tokenize': 'Tokenize', 'node.resume': 'Resume', 'node.name': 'Workflow Name',
        'node.comment': 'Comments', 'ctx.renameHint': 'x', 'status.nodes': 'Nodes: ',
        'toast.newWorkflow': 'new', 'toast.workflowSaved': 'saved', 'toast.saveFailed': 'fail',
        'toast.noWorkflows': 'none', 'toast.workflowLoaded': 'loaded', 'toast.loadFailed': 'loadfail',
        'dialog.workflowName': 'name?', 'dialog.cancel': 'cancel', 'dialog.confirm': 'ok',
        'summary.source': 'src', 'summary.output': 'out', 'summary.upload': 'up',
    },
    zh: {},
};
const I18n = { lang: 'en', dict: LABELS, t(k) { return LABELS.en[k] || k; } };

const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas: undefined,
    RunState: {
        parallel: true,
        headless: true,
        _calls: [],
        set(k, v) {
            this[k] = v;
            this._calls.push([k, v]);
        },
    },
    resumeBar: { refresh: () => {} },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
sandbox.window.Settings = { save: () => {} };

// Recording fetch installed INSIDE the context so the async code sees it.
vm.runInContext(
    `globalThis.__fetchLog = [];
     globalThis.fetch = function (url, opts) {
         globalThis.__fetchLog.push({ url, opts });
         if (String(url).indexOf('/api/workflow/load') === 0) {
             var r = globalThis.__loadResponse || { ok: false, error: 'no stub' };
             return Promise.resolve({ json: () => Promise.resolve(r) });
         }
         /* The crawl matrix, answered with the payload the pytest driver dumped
            from the backend: a new Data Source node seeds its numbers from it, so
            pretending it is absent would test a browser that never boots. */
         if (String(url).indexOf('/api/capabilities') === 0) {
             var caps = globalThis.__capabilities || { ok: true };
             return Promise.resolve({ json: () => Promise.resolve(caps) });
         }
         var body = { ok: true, workflows: [], datasets: [] };
         return Promise.resolve({ json: () => Promise.resolve(body) });
     };`,
    sandbox,
);

vm.runInContext(fs.readFileSync(canvasPath, 'utf8') + '\n;globalThis.__canvas = canvas;', sandbox);
vm.runInContext(fs.readFileSync(wfPath, 'utf8') + '\n;globalThis.__workflow = workflow;', sandbox);
/* Hand the matrix to the stubbed endpoint and let the browser's own loader run,
   so the panel and the node defaults are built from the payload the server would
   really have sent. Awaited before any scenario: a node dropped into an
   unloaded world seeds differently, and that is a different test. */
const matrix = readJson(matrixPath);
if (matrix) {
    sandbox.__capabilities = matrix;
    await sandbox.Capabilities.load();
}
/* After the file load: workflow.js DECLARES showDialog/showToast, and function
   declarations overwrite the context globals — stubbing before would leave the
   real modal/toast code running instead of our canned answer. */
vm.runInContext(
    `globalThis.showDialog = function () { return Promise.resolve(globalThis.__dialogAnswer || null); };
     globalThis.__toasts = [];
     globalThis.showToast = function (m) { globalThis.__toasts.push(String(m)); };`,
    sandbox,
);

const canvas = sandbox.__canvas;
const workflow = sandbox.__workflow;
canvas.nodesContainer = sandbox.__byId('nodes-container');
canvas.workspace = sandbox.__byId('workspace');

const out = {};
for (const sc of scenarios) {
    canvas.nodes = {};
    canvas.connections = [];
    canvas.nextId = 1;
    canvas._history = [];
    canvas._historyIdx = -1;
    workflow.currentFile = sc.currentFile ?? null;
    sandbox.__dialogAnswer = sc.dialogAnswer ?? null;
    sandbox.__loadResponse = sc.loadResponse ?? null;
    vm.runInContext('globalThis.__fetchLog = [];', sandbox);
    sandbox.RunState._calls = [];
    sandbox.__toasts.length = 0;

    for (const t of sc.add || []) canvas.addNode(t);
    if (sc.load) workflow.loadFromJSON(sc.load);
    if (sc.loadByName) await workflow._loadByName(sc.loadByName);
    if (sc.newFile) workflow.newFile();
    if (sc.save) await workflow.save();
    /* loadFromJSON fires reconcileDatasets() without awaiting; flush it so the
       upload node's dataset reconciliation is visible in the snapshot below. */
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    out[sc.id] = {
        nodes: Object.values(canvas.nodes).map((n) => ({
            id: n.id,
            type: n.type,
            title: n.title,
            params: n.params,
            elTitle: n.el ? n.el.querySelector('.node-title').textContent : null,
        })),
        connections: canvas.connections,
        currentFile: workflow.currentFile,
        newfileDraftCleared: sandbox.__stored.crawler_canvas === undefined,
        fetches: vm.runInContext(
            'globalThis.__fetchLog.map(f => ({ url: f.url, body: (f.opts && f.opts.body) || null }))',
            sandbox,
        ),
        toasts: sandbox.__toasts.slice(),
        runState: sandbox.RunState._calls,
    };
}
process.stdout.write(JSON.stringify(out));
