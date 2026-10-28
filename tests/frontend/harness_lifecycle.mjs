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
import { sourcesWithCompanions } from './companions.mjs';

const [canvasPath, wfPath, scPath, matrixPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scPath, 'utf8'));

const LABELS = {
    en: {
        'node.source': 'Data Source', 'node.output': 'Output', 'node.upload': 'Upload File',
        'node.process': 'Process', 'node.analysis': 'Analysis', 'node.visualize': 'Visualize',
        'node.tokenize': 'Tokenize', 'node.resume': 'Resume', 'node.name': 'Workflow Name',
        'node.comment': 'Comments', 'ctx.renameHint': 'x', 'status.nodes': 'Nodes: ',
        'canvas.dirtyUnsaved': 'Unsaved changes',
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
             return Promise.resolve({ ok: r.ok !== false, json: () => Promise.resolve(r) });
         }
         /* The crawl matrix, answered with the payload the pytest driver dumped
            from the backend: a new Data Source node seeds its numbers from it, so
            pretending it is absent would test a browser that never boots. */
         if (String(url).indexOf('/api/capabilities') === 0) {
             var caps = globalThis.__capabilities || { ok: true };
             return Promise.resolve({ ok: caps.ok !== false, json: () => Promise.resolve(caps) });
         }
         /* /api/data/datasets: a scenario may override the answer to exercise the two
            distinguishable cases — a refusal (ok:false, the cross-origin guard) vs a
            genuine empty library (ok:true, datasets:[]). The DEFAULT stays a successful
            empty list so every pre-existing lifecycle scenario keeps its current behaviour. */
         if (String(url).indexOf('/api/data/datasets') === 0 && globalThis.__datasetsResponse) {
             var dresp = globalThis.__datasetsResponse;
             return Promise.resolve({ ok: dresp.ok !== false, json: () => Promise.resolve(dresp) });
         }
         var body = { ok: true, workflows: [], datasets: [] };
         return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
     };`,
    sandbox,
);

vm.runInContext(fs.readFileSync(canvasPath, 'utf8') + '\n;globalThis.__canvas = canvas;', sandbox);
/* The workflow layer is more than one file now: its split-out halves are read from the same
   directory and evaluated after it, each as its own script like a real <script> tag. */
const workflowSources = sourcesWithCompanions([wfPath]);
workflowSources[0] += '\n;globalThis.__workflow = workflow;';
for (const code of workflowSources) vm.runInContext(code, sandbox);
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
/* The lifecycle tests are about load/save/undo/dirty semantics. Autosave is a separate concern
   with its own harness (harness_autosave.mjs) and a browser-tier case; neutralise its hook here so
   a 0-timer flush does not auto-persist a legitimately-dirty open and mask the flag under test. */
vm.runInContext('workflow.scheduleAutosave = function () {};', sandbox);

const canvas = sandbox.__canvas;
const workflow = sandbox.__workflow;
canvas.nodesContainer = sandbox.__byId('nodes-container');
canvas.workspace = sandbox.__byId('workspace');
/* _applyView ends in updateTransform, which writes onto the canvas container. */
canvas.container = sandbox.__byId('canvas-inner');

const out = {};
/* Drain the event loop so a scenario's own async tail — chiefly an upload node's
   `reconcileDatasets()` (fired UNAWAITED from loadFromJSON, ending in canvas.saveState())
   — cannot survive into the next scenario's snapshot. Two `setImmediate` was NOT enough:
   the saveState lands behind a fetch→then chain that can also cross a timer, so under
   full-suite CPU load it fired after the next scenario had cleared its draft — the
   load-dependent race that flipped the draft assertions between runs. Loop many macrotask
   turns (each also flushing pending microtasks) so every deferred writer has run before
   we look. No animation frames here on purpose: this harness leaves render frames queued,
   and flushing them would run a repaint against a node the scenario already tore down. */
async function settle() {
    for (let i = 0; i < 12; i++) {
        await new Promise((r) => setImmediate(r));
    }
    await null;
    await null;
}
for (const sc of scenarios) {
    /* Drain BEFORE resetting and clearing the draft, so any writer the PREVIOUS scenario
       left unresolved lands first; the draft delete just below then wipes it, and this
       scenario starts from a clean slate regardless of machine load. */
    await settle();
    canvas.nodes = {};
    canvas.connections = [];
    canvas.nextId = 1;
    canvas._history = [];
    canvas._historyIdx = -1;
    /* Dirty starts fresh each scenario the way init's baseline reset does: without this,
       one scenario's markSaved/dirty leaks into the next (the harness never calls init). */
    canvas._cleanState = null;
    canvas.dirty = false;
    /* Reset the camera too, so one scenario's loaded view cannot leak into the next
       and a 'file with no view leaves the camera alone' test starts from a known
       default. */
    canvas.panX = 0;
    canvas.panY = 0;
    canvas.zoom = 1;
    workflow.currentFile = sc.currentFile ?? null;
    /* The open-file session record lives in localStorage and must be reset between
       scenarios so one scenario's save/restore cannot leak into the next. A
       'returning browser' seeds a draft (the canvas content) and optionally the name
       of the file that draft belongs to; `hasDraft: false` simulates a fresh browser. */
    delete sandbox.__stored.crawler_open_file;
    delete sandbox.__stored.crawler_canvas;
    if (sc.hasDraft !== false) sandbox.__stored.crawler_canvas = JSON.stringify({ nodes: [], view: {} });
    if (sc.storedOpenFile !== undefined) sandbox.__stored.crawler_open_file = sc.storedOpenFile;
    sandbox.__dialogAnswer = sc.dialogAnswer ?? null;
    sandbox.__loadResponse = sc.loadResponse ?? null;
    sandbox.__datasetsResponse = sc.datasetsResponse ?? null;
    vm.runInContext('globalThis.__fetchLog = [];', sandbox);
    sandbox.RunState._calls = [];
    sandbox.__toasts.length = 0;
    /* The boot step `openFile` runs restoreOpenFile() (sets currentFile from the remembered name when
       a draft came back), then `reloadOpenFile()` re-fetches that file's content from the server — so a
       file updated outside this browser is opened fresh, not from the stale draft. Both run AFTER the
       fetch/response reset so the reload's own round-trip is what the snapshot reads. */
    if (sc.restore) workflow.restoreOpenFile();
    if (sc.reload) await workflow.reloadOpenFile();

    for (const t of sc.add || []) canvas.addNode(t);
    if (sc.load) workflow.loadFromJSON(sc.load);
    if (sc.loadByName) await workflow._loadByName(sc.loadByName);
    /* A scenario pans before it saves, so the SAVE body shows whether the camera
       rides along with the file — which is what makes a saved 适应 survive reopen. */
    if (sc.setView) canvas._applyView(sc.setView);
    /* Capture the draft-cleared contract at the instant newFile() runs. newFile removes the
       draft synchronously, but a source node added earlier in this scenario has an async
       capability fetch that fires canvas.saveState() during the flush below; snapshotting here
       (before that resolves) pins exactly what newFile guarantees. */
    let __newfileDraftCleared = null;
    if (sc.newFile) {
        workflow.newFile();
        __newfileDraftCleared = sandbox.__stored.crawler_canvas === undefined;
    }
    if (sc.save) await workflow.save();
    /* loadFromJSON fires reconcileDatasets() without awaiting; flush it so the
       upload node's dataset reconciliation is visible in the snapshot below. */
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));

    const rawDraft = sandbox.__stored.crawler_canvas;
    const draftObj = typeof rawDraft === 'string' ? JSON.parse(rawDraft) : rawDraft || null;

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
        dirty: canvas.dirty,
        dirtyDot: sandbox.__byId('dirty-indicator').textContent,
        newfileDraftCleared: sc.newFile ? __newfileDraftCleared : sandbox.__stored.crawler_canvas === undefined,
        /* The persisted open-file record: which saved file the browser will reopen on the
           next load, and whether it was cleared (only 新建 clears it). */
        openFileStored: sandbox.__stored.crawler_open_file === undefined ? null : sandbox.__stored.crawler_open_file,
        draftStored: sandbox.__stored.crawler_canvas === undefined ? null : true,
        fetches: vm.runInContext(
            'globalThis.__fetchLog.map(f => ({ url: f.url, body: (f.opts && f.opts.body) || null }))',
            sandbox,
        ),
        toasts: sandbox.__toasts.slice(),
        runState: sandbox.RunState._calls,
        /* Where the camera sits after the action, and what the draft kept. */
        view: canvas._viewState(),
        draftView: (draftObj && draftObj.view) || null,
    };
    /* Let this scenario's async tail drain before the next one seeds, so no autosave leaks
       across the boundary and flips the next scenario's draft assertion. */
    await settle();
}
process.stdout.write(JSON.stringify(out));
