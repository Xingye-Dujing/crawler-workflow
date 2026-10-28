/* Drives the REAL runResults module (workflow.js) — the state that decides which
 * run's results the canvas is showing.
 *
 * The three things that can go wrong here are all invisible in a screenshot:
 *   · the default selection is not the newest run of this workflow;
 *   · a preview payload does not carry the pinned run id, so the server quietly
 *     stitches each node's newest rows into one "run";
 *   · live status ticks overwrite a record the user deliberately loaded, or stop
 *     updating the one they are actually following (and parallel nodes must all
 *     stay `running` at once, not collapse to one).
 *
 * Usage: node harness_run_results.mjs <workflow.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { sourceOf } from './companions.mjs';

const src = sourceOf(process.argv[2]);

const DICT = {
    en: {
        'runsMgr.loadedToast': 'LOADED {when}',
        'runsMgr.loadFailed': 'FAILED {rid}',
        'runsMgr.runStatus': 'STATUS {status}',
        'runsMgr.colRows': 'rows',
        'runsMgr.node.pending': 'Pending',
        'runsMgr.node.running': 'Running',
        'runsMgr.node.done': 'Done',
        'runsMgr.node.partial': 'Partial',
        'runsMgr.node.failed': 'Failed',
        'runsMgr.node.skipped': 'Skipped',
        'runsMgr.node.restored': 'Restored',
        'toast.rerunNoResult': 'NO-RERUN',
    },
    zh: {},
};
const I18n = {
    lang: 'en',
    dict: DICT,
    t(key, vars) {
        let text = DICT.en[key] || key;
        if (vars) {
            for (const name of Object.keys(vars)) text = text.split('{' + name + '}').join(String(vars[name]));
        }
        return text;
    },
    apply() {},
};

const applied = [];
const canvas = {
    nodes: {},
    connections: [],
    toWorkflowJSON: () => ({ nodes: Object.values(canvas.nodes), connections: [], settings: {} }),
    applyRunStatuses: (map) => applied.push(JSON.parse(JSON.stringify(map || {}))),
};
canvas.nodes = {
    'node-1': { id: 'node-1', type: 'upload', params: {} },
    'node-2': { id: 'node-2', type: 'process', params: {} },
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas,
    RunState: { running: false, setRunning() {} },
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'm', api_key: '' }) },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__rr = runResults;', sandbox);

const toasts = [];
sandbox.showToast = (msg) => toasts.push(String(msg));

const RUNS = [
    {
        run_id: 'r-live',
        workflow_name: 'wf',
        workflow_fingerprint: 'fp',
        status: 'running',
        started_at: '2026-10-24T12:00:00',
        nodes: [
            { node_id: 'node-1', status: 'done', row_count: 5 },
            { node_id: 'node-2', status: 'running', row_count: 0 },
        ],
    },
    {
        run_id: 'r-new',
        workflow_name: 'wf',
        workflow_fingerprint: 'fp',
        status: 'completed',
        started_at: '2026-10-24T10:00:00',
        nodes: [
            { node_id: 'node-1', status: 'done', row_count: 3 },
            { node_id: 'node-2', status: 'failed', row_count: 0 },
        ],
    },
    {
        run_id: 'r-old',
        workflow_name: 'wf',
        workflow_fingerprint: 'fp',
        status: 'completed',
        started_at: '2026-10-23T10:00:00',
        nodes: [
            { node_id: 'node-1', status: 'restored', row_count: 2 },
            { node_id: 'node-2', status: 'done', row_count: 4 },
        ],
    },
];

let currentRuns = RUNS;
const requests = [];
sandbox.fetch = (url, options) => {
    requests.push({ url, options });
    let payload = { ok: true, runs: currentRuns, latest_run_id: currentRuns[0] && currentRuns[0].run_id, queue: [] };
    if (String(url).indexOf('/api/runs/r-old') >= 0) payload = { ok: true, run: RUNS[2] };
    return Promise.resolve({ json: () => Promise.resolve(payload) });
};

const rr = sandbox.__rr;
const out = {};
const lastApplied = () => applied[applied.length - 1] || null;

/* 1. On entry the newest run of this canvas is loaded, with its verdicts. */
const first = await rr.refresh();
out.defaultSelection = {
    runId: first && first.run_id,
    rrRunId: rr.runId,
    selected: lastApplied(),
    followLive: rr.followLive,
};

/* 2. Loading an older record replaces the map (no green check left behind) and is
      the id every preview payload carries from then on. */
const loaded = await rr.load('r-old');
out.loadOld = {
    loaded: loaded && loaded.run_id,
    rrRunId: rr.runId,
    selected: lastApplied(),
    isLoaded: rr.isLoaded('r-old'),
    previousNotLoaded: rr.isLoaded('r-new'),
    payloadRun: rr.payload({ node_id: 'node-1' }).run_id,
    toast: toasts[toasts.length - 1],
};

/* 3. A historical load is not dragged back by the live stream. */
rr.applyLive({ 'node-1': { status: 'running', run_id: 'r-live' } }, ['r-live']);
out.liveIgnoredAfterHistoricalLoad = {
    followLive: rr.followLive,
    status: rr.statuses['node-1'].status,
};

/* 4. Starting a run clears the old marks immediately and follows it. */
rr.beginLive('r-live');
out.beginLive = { followLive: rr.followLive, runId: rr.runId, applied: lastApplied() };

/* 5. Two nodes running at once is a map, not one slot; a later tick merges rather
      than dropping a node it did not mention. */
rr.applyLive(
    {
        'node-1': { status: 'running', run_id: 'r-live', row_count: 0 },
        'node-2': { status: 'running', run_id: 'r-live', row_count: 0 },
    },
    ['r-live']
);
const bothRunning = JSON.parse(JSON.stringify(rr.statuses));
rr.applyLive({ 'node-1': { status: 'done', run_id: 'r-live', row_count: 5 } }, ['r-live']);
out.liveTicks = {
    bothRunning: [bothRunning['node-1'].status, bothRunning['node-2'].status],
    merged: [rr.statuses['node-1'].status, rr.statuses['node-2'].status],
    appliedBothRan: lastApplied()['node-1'].status === 'done' && lastApplied()['node-2'].status === 'running',
};

/* 6. Only a settled node WITH rows can be replayed. */
out.canRerun = {
    doneWithRows: rr.canRerun('node-1'),
    runningNode: rr.canRerun('node-2'),
    missingNode: rr.canRerun('node-9'),
    ownerOfNode: rr.runIdFor('node-1'),
};
rr.statuses['node-1'].row_count = 0;
out.canRerun.zeroRows = rr.canRerun('node-1');
rr.statuses['node-1'].row_count = 5;

/* 7. When the worker settles, the record is re-read and following stops. */
currentRuns = [
    Object.assign({}, RUNS[0], {
        status: 'completed',
        nodes: [
            { node_id: 'node-1', status: 'done', row_count: 5 },
            { node_id: 'node-2', status: 'done', row_count: 2 },
        ],
    }),
    RUNS[1],
    RUNS[2],
];
rr.finishLive();
await new Promise((r) => setImmediate(r));
out.finishLive = {
    followLive: rr.followLive,
    runId: rr.runId,
    selected: lastApplied(),
    askedForWorkflow: requests.some((r) => String(r.url).indexOf('/api/runs/for-workflow') >= 0),
};

/* 8. A canvas that lost its nodes clears the selection and the badges. */
canvas.nodes = {};
await rr.refresh();
out.emptyCanvas = { runId: rr.runId, statuses: rr.statuses, applied: lastApplied(), payload: rr.payload({ node_id: 'x' }) };

process.stdout.write(JSON.stringify(out));
