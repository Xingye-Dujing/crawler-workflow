/* Renders the run-records table with the REAL runsManager.render (workflow.js).
 *
 * "运行记录的管理" is a place a lie shows up on screen: a resumable run must
 * offer 继续/重新开始, a finished one must not; node progress must read
 * done/total; and a workflow name is user data that must be HTML-escaped.
 * Loads workflow.js with a working fake DOM and reports the generated table.
 *
 * Usage: node harness_runsmgr.mjs <workflow.js> <runs.json>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');
const runs = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const I18n = {
    lang: 'en',
    dict: {
        en: {
            'runsMgr.status.running': 'running', 'runsMgr.status.interrupted': 'interrupted',
            'runsMgr.status.completed': 'completed', 'runsMgr.status.failed': 'failed',
            'runsMgr.status.abandoned': 'abandoned', 'runsMgr.resume': 'Continue',
            'runsMgr.restart': 'Restart', 'runsMgr.remove': 'Delete', 'runsMgr.detail': 'Detail',
            'runsMgr.empty': 'empty', 'name.unnamed': 'unnamed', 'runsMgr.colWorkflow': 'wf',
            'runsMgr.colStatus': 'st', 'runsMgr.colNodes': 'nodes', 'runsMgr.colRows': 'rows',
            'runsMgr.colStarted': 'started', 'runsMgr.report': 'Report',
            'runsMgr.queueHeader': 'WAITING({n})', 'runsMgr.queueCancel': 'CancelQueued',
            'runsMgr.queueCancelled': 'REMOVED', 'runsMgr.queueGone': 'GONE',
            'runsMgr.queueCancelFailed': 'FAILED',
            'runsMgr.groupDone': '{done}/{total} nodes',
            'runsMgr.tagParallel': 'PARALLEL({n})', 'runsMgr.tagSerial': 'SERIAL({n})',
            'runsMgr.tagHeadless': 'HEADLESS', 'runsMgr.tagWindow': 'WINDOW',
        },
        zh: {},
    },
    t(k) {
        return this.dict.en[k] || k;
    },
};

const captured = { posts: [], toasts: [] };
const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas: {
        nodes: {},
        connections: [],
        getState: () => ({ nodes: {}, connections: [] }),
        toWorkflowJSON: () => ({ nodes: {}, connections: [], settings: {} }),
        getUpstreamNodeId: (id) => (id === 'node-2' ? 'node-1' : null),
        saveState: () => {},
    },
    RunState: { running: false, setRunning(v) { this.running = v; } },
    /* Lives in app.js; execute() reads the transport choice off it before POSTing. */
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'qwen3.5:9b', api_key: '' }) },
    /* Also app.js: the preview panel makes itself draggable on open, which is
       not what is under test here. */
    makeDraggable: () => {},
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__wf = { runsManager, workflow, dataNodes };', sandbox);
/* Assigned after the script ran: workflow.js declares showToast itself, and a
   function declaration in the script wins over anything seeded before it. */
sandbox.showToast = (msg) => captured.toasts.push(String(msg));
sandbox.fetch = (url, options) => {
    captured.posts.push({ url, body: options && options.body ? JSON.parse(options.body) : null });
    /* A scenario may seed an answer (the run-detail fetch below asks for one run by
       id); anything unclaimed keeps the canned reply the execute() phases read, which
       those phases assert on as "the server said ok". */
    const frag = Object.keys(sandbox.__routes || {}).filter((f) => String(url).indexOf(f) >= 0)[0];
    const payload = frag
        ? sandbox.__routes[frag]
        : { ok: true, removed: true, run_id: 'r-new', rows: [], columns: [], total_rows: 0 };
    return Promise.resolve({ json: () => Promise.resolve(payload) });
};
sandbox.__byId('runs-mgr-body').innerHTML = '';
const manager = sandbox.__wf.runsManager;
manager._queue = runs.queue || [];
manager.render(runs.runs);
const html = sandbox.__byId('runs-mgr-body').innerHTML;
/* Snapped now: the execute() scenarios below re-render the panel through
   refreshIfOpen(), and a count read after them is not this render's answer. */
const countText = sandbox.__byId('runs-mgr-count').textContent;
/* Awaited: the toast lands after the response, and stdout is written now. */
await manager.cancelQueued('q1');
/* Snapped before the execute() scenarios add their own: the cancel assertions
   read this list, and a 'started' toast from a later phase is not its answer. */
const cancelToasts = captured.toasts.slice();

/* ── what the Run/继续 request actually carries ─────────────────────────
   A 继续 must refuse to be parked: while it waits the record it names can
   be aged out, and a continue that starts late is a worse operation than the
   one asked for. The payload's `queue` flag is that contract. */
const wf = sandbox.__wf.workflow;
wf.pollStatus = () => {}; // the status loop has nothing to poll here
/* One canvas that passes validate() — an upload needs no cookie prompt, so the
   preflight stays on the code path under test instead of opening a dialog. */
sandbox.canvas.nodes = {
    'node-1': { id: 'node-1', type: 'upload', title: '文件', params: { dataset_id: 'd1', dataset_name: 'a.csv', row_count: 4 } },
    'node-2': { id: 'node-2', type: 'output', title: '导出', operation: 'save', params: { operation: 'save', filename: 'x' } },
};
sandbox.canvas.connections = [{ from: 'node-1', to: 'node-2' }];
sandbox.canvas.toWorkflowJSON = () => ({
    nodes: Object.values(sandbox.canvas.nodes),
    connections: sandbox.canvas.connections,
    settings: sandbox.canvas.settings || { mode: 'serial' },
});
wf.currentFile = '夜间增量';
const before = captured.posts.length;
await wf.execute({ resumeRunId: 'r-int' });
const resumePost = captured.posts.slice(before).find((p) => p.url === '/api/workflow/execute');
const beforePlain = captured.posts.length;
await wf.execute({});
const plainPost = captured.posts.slice(beforePlain).find((p) => p.url === '/api/workflow/execute');

/* A preview of a node that has not run in this process is answered from the run
   store, so the request has to carry which workflow the canvas is showing. */
const beforePreview = captured.posts.length;
await sandbox.__wf.dataNodes.previewData('node-2');
const previewPost = captured.posts.slice(beforePreview).find((p) => p.url === '/api/data/preview');

/* The name a run is filed under: a name node's label beats the saved file name,
   which beats nothing. */
sandbox.canvas.nodes.n9 = { id: 'n9', type: 'name', params: { workflow_name: '周报表' } };
const nameFromNode = wf.runName();
/* A canvas can hold several workflows, each with its own name node, and they run
   as one record: naming it with only the first made the others look deleted. The
   request body must carry the same composed spelling the panel shows, so the two
   name nodes are wired to two real chains — a name node with nothing downstream
   is refused before any request is sent. */
sandbox.canvas.nodes.n10 = { id: 'n10', type: 'name', params: { workflow_name: '明细表' } };
sandbox.canvas.nodes['node-3'] = { id: 'node-3', type: 'upload', title: '文件', params: { dataset_id: 'd2', dataset_name: 'b.csv', row_count: 4 } };
sandbox.canvas.nodes['node-4'] = { id: 'node-4', type: 'output', title: '导出', operation: 'save', params: { operation: 'save', filename: 'y' } };
sandbox.canvas.connections = [
    { from: 'n9', to: 'node-1' },
    { from: 'node-1', to: 'node-2' },
    { from: 'n10', to: 'node-3' },
    { from: 'node-3', to: 'node-4' },
];
sandbox.canvas.settings = { mode: 'parallel' };
const nameFromTwoNodes = wf.runName();
const beforeTwo = captured.posts.length;
await wf.execute({});
const twoNodePost = captured.posts.slice(beforeTwo).find((p) => p.url === '/api/workflow/execute');
const twoNodeToasts = captured.toasts.slice(beforeTwo);
delete sandbox.canvas.nodes.n10;
delete sandbox.canvas.nodes.n9;
const nameFromFile = wf.runName();
wf.currentFile = '';
const nameWithoutEither = wf.runName();

/* The chips beside the name, straight from the stored fields. */
const tagCases = {
    parallelHeadless: manager.tags({ mode: 'parallel', wf_count: 2, headless: 1 }),
    parallelVisible: manager.tags({ mode: 'parallel', wf_count: 3, headless: 0 }),
    /* Several workflows run one at a time is 串行, not 并行: the count says how many
       the canvas held, only the mode says whether they overlapped. */
    serialHeadless: manager.tags({ mode: 'serial', wf_count: 2, headless: 1 }),
    singleParallel: manager.tags({ mode: 'parallel', wf_count: 1, headless: 1 }),
    singleSerial: manager.tags({ mode: 'serial', wf_count: 1, headless: 0 }),
};

/* The report button may name the run only by id: a workflow name is user text,
   and one double quote in it would close the onclick attribute and let whatever
   follows become markup. */
/* One record holds every workflow of a serial run, so its expansion has to say which
   node ran in which workflow — and a record that holds ONE workflow must not grow a
   heading over its own nodes. `detail()` fetches the run and inserts the row; the
   stub's `after` is a recorder here so the generated markup can be read back. */
const GROUPED = {
    ok: true,
    run: {
        run_id: 'r-group',
        status: 'completed',
        started_at: '2026-09-24T10:00:00',
        wf_count: 2,
        workflow_name: '热门榜 + 周排行榜',
        nodes: [
            { node_id: 'name-1', node_type: 'name', status: 'done', row_count: 0, component: 0, component_name: '热门榜' },
            { node_id: 'up-1', node_type: 'upload', status: 'done', row_count: 4, component: 0, component_name: '热门榜' },
            { node_id: 'name-2', node_type: 'name', status: 'done', row_count: 0, component: 1, component_name: '周排行榜' },
            /* restored counts as settled — a node that only replayed its stored rows
               is just as finished, and a tally that forgot it would under-report. */
            { node_id: 'out-2', node_type: 'output', status: 'restored', row_count: 6, component: 1, component_name: '周排行榜' },
            { node_id: 'p-2', node_type: 'process', status: 'partial', row_count: 2, component: 1, component_name: '周排行榜' },
        ],
    },
};
const FLAT = {
    ok: true,
    run: {
        run_id: 'r-flat',
        status: 'completed',
        started_at: '2026-09-24T09:00:00',
        wf_count: 1,
        workflow_name: '只看排行榜',
        nodes: [
            { node_id: 'up-1', node_type: 'upload', status: 'done', row_count: 4, component: 0, component_name: '只看排行榜' },
            { node_id: 'out-1', node_type: 'output', status: 'failed', row_count: 0, component: 0, component_name: '只看排行榜' },
        ],
    },
};
/* A record written before the component columns existed: one group, no heading, and
   nothing invented about which workflow its nodes belonged to. */
const LEGACY = {
    ok: true,
    run: {
        run_id: 'r-legacy',
        status: 'completed',
        started_at: '2026-09-24T08:00:00',
        wf_count: 1,
        workflow_name: '旧的',
        nodes: [{ node_id: 'node-1', node_type: 'source', status: 'done', row_count: 900 }],
    },
};

async function renderDetail(payload) {
    const inserted = [];
    const id = 'runs-mgr-detail-' + payload.run.run_id;
    /* The detail row is inserted by the code under test, so it must not exist yet:
       the stub hands out a fresh element for any id it was never told is absent,
       and detail() reads that as "already open" and returns without rendering. */
    sandbox.document.absent.add(id);
    sandbox.__routes['/api/runs/' + payload.run.run_id] = payload;
    await manager.detail(payload.run.run_id, { closest: () => ({ after: (el) => inserted.push(el) }) });
    return inserted.length ? inserted[0].innerHTML : null;
}

const groupedHtml = await renderDetail(GROUPED);
const flatHtml = await renderDetail(FLAT);
const legacyHtml = await renderDetail(LEGACY);
const groupTally = manager.nodeGroups(GROUPED.run.nodes).map((g) => ({
    index: g.index,
    name: g.name,
    ids: g.nodes.map((n) => n.node_id),
}));

/* ─── following a live run, and a stop that lands late ─────────────────────
   The panel used to read the record only when the user opened it, so a stopped
   run sat on 运行中 — the verdict existed, nobody re-asked. autoRefresh keeps
   the open panel current while the run lives; awaitSettled keeps re-reading
   after 停止 until no row still claims to be running. */
const LIVE = {
    ok: true,
    runs: [{ run_id: 'live', workflow_name: '在跑', status: 'running', node_done: 1, node_total: 3, rows_kept: 5, wf_count: 1, mode: 'serial', headless: 1 }],
    queue: [],
};
const SETTLED = {
    ok: true,
    runs: [{ run_id: 'live', workflow_name: '在跑', status: 'interrupted', node_done: 1, node_total: 3, rows_kept: 5, wf_count: 1, mode: 'serial', headless: 1 }],
    queue: [],
};
const listFetches = () => captured.posts.filter((p) => String(p.url).indexOf('/api/runs/list') === 0).length;
const follow = {};
const panel = sandbox.__byId('runs-panel');

/* The renderDetail() phases left a `_detail` flag standing — a table replaced
   underneath an expansion clears it in the real page, so start honest. */
manager._detail = null;
panel.classList.remove('open');
let beforeFollow = listFetches();
manager.autoRefresh();
follow.closedAsksForNothing = listFetches() === beforeFollow;

sandbox.__routes['/api/runs/list'] = LIVE;
panel.classList.add('open');
beforeFollow = listFetches();
manager.autoRefresh();
/* autoRefresh does not await its refresh (the poller must not block the run's
   own ticks); the re-render lands one microtask later. */
await new Promise((r) => setImmediate(r));
follow.followedLive = listFetches() > beforeFollow && manager._anyRunning() === true;

/* A detail row being read is a reason to leave the table alone: the refresh
   would yank the expansion the user is reading out of the DOM. The id must be
   registered-absent first, or the stub's never-null getElementById answers
   "already open" and nothing gets inserted. */
sandbox.document.absent.add('runs-mgr-detail-live');
sandbox.__routes['/api/runs/live'] = { ok: true, run: { run_id: 'live', status: 'running', nodes: [] } };
await manager.detail('live', { closest: () => ({ after: () => {} }) });
beforeFollow = listFetches();
manager.autoRefresh();
follow.pausedForReading = listFetches() === beforeFollow && manager._detail === 'live';

/* The stop-then-settle follow: the server answers 运行中 twice before the
   verdict appears; awaitSettled must keep re-reading and stop on the settle.
   (Collapsed first — awaitSettled honours the open detail, as autoRefresh
   does: no point arriving here to re-assert the pause proved above.) */
manager._detail = null;
const answers = [LIVE, LIVE, SETTLED];
Object.defineProperty(sandbox.__routes, '/api/runs/list', {
    configurable: true,
    get: () => (answers.length > 1 ? answers.shift() : answers[0]),
});
beforeFollow = listFetches();
await manager.awaitSettled(10, 1);
follow.spun = listFetches() - beforeFollow;
follow.settled = manager._anyRunning() === false;
follow.showedVerdict = (sandbox.__byId('runs-mgr-body').innerHTML || '').indexOf('st-interrupted') >= 0;

process.stdout.write(
    JSON.stringify({
        follow,
        html,
        count: countText,
        reports: (html.match(/runsManager\.report\(/g) || []).length,
        nameInHandler: /onclick="[^"]*获取微博/.test(html),
        queueRows: (html.match(/runsManager\.cancelQueued\(/g) || []).length,
        posts: captured.posts,
        toasts: cancelToasts,
        resumeBody: resumePost ? resumePost.body : null,
        plainBody: plainPost ? plainPost.body : null,
        previewBody: previewPost ? previewPost.body : null,
        runName: { fromNode: nameFromNode, fromFile: nameFromFile, none: nameWithoutEither, fromTwo: nameFromTwoNodes },
        twoNodeBody: twoNodePost ? twoNodePost.body : null,
        twoNodeToasts,
        tagCases,
        grouped: {
            html: groupedHtml,
            tally: groupTally,
            headers: (groupedHtml || '').match(/rm-group-name/g) || [],
            tallyText: (groupedHtml || '').match(/\d+\/\d+ nodes/g) || [],
            flatHeaders: (flatHtml || '').match(/rm-group-name/g) || [],
            flatHtml,
            legacyHeaders: (legacyHtml || '').match(/rm-group-name/g) || [],
            legacyHtml,
            doneOf: {
                done: manager.nodeDone('done'),
                restored: manager.nodeDone('restored'),
                partial: manager.nodeDone('partial'),
                failed: manager.nodeDone('failed'),
                skipped: manager.nodeDone('skipped'),
                running: manager.nodeDone('running'),
                empty: manager.nodeDone(undefined),
            },
        },
        // Whatever the two execute() calls said — a refused preflight shows here
        // rather than as a missing POST with no reason attached.
        executeToasts: captured.toasts.slice(cancelToasts.length),
    }),
);
