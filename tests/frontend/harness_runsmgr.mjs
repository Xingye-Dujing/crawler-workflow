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
            'runsMgr.status.stopping': 'stopping',
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
            'runsMgr.tagHeadlessMixed': 'MIXED',
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
    /* The chip describes what RAN. A 无头 run the executor switched to a real window
       (forced_visible) must not still read 「无头」; and the flag is irrelevant once
       the run already asked for a window. */
    headlessForcedWindow: manager.tags({ mode: 'serial', wf_count: 1, headless: 1, forced_visible: 1 }),
    headlessClean: manager.tags({ mode: 'serial', wf_count: 1, headless: 1, forced_visible: 0 }),
    windowIgnoringFlag: manager.tags({ mode: 'serial', wf_count: 1, headless: 0, forced_visible: 1 }),
};

/* The report button may name the run only by id: a workflow name is user text,
   and one double quote in it would close the onclick attribute and let whatever
   follows become markup. */
/* One record holds every workflow of a serial run, so its expansion has to say which
   node ran in which workflow — and a record that holds ONE workflow must not grow a
   heading over its own nodes. `detail()` fetches the run and inserts a row under the
   record's own <tr>, so the scenario renders the table first: the panel's code path is
   "find the live row, insert after it", and a stub that faked the row would not be able
   to see the case where a refresh replaced the table while the fetch was in flight. */
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
    const runId = payload.run.run_id;
    const id = 'runs-mgr-detail-' + runId;
    /* The detail row is inserted by the code under test, so it must not exist yet:
       the stub hands out a fresh element for any id it was never told is absent,
       and detail() reads that as "already open" and returns without rendering. */
    sandbox.document.absent.add(id);
    sandbox.__routes['/api/runs/' + runId] = payload;
    manager._detail = null;
    /* The record has to be in the table for its expansion to have somewhere to go —
       that is the state a person is in when they click 详情, and the only way to test
       "inserted under the LIVE row" rather than under whatever object the click came from. */
    manager.render([
        {
            run_id: runId,
            workflow_name: payload.run.workflow_name,
            status: payload.run.status,
            node_done: 3,
            node_total: 3,
            rows_kept: 9,
            wf_count: payload.run.wf_count,
            mode: 'parallel',
            headless: 1,
        },
    ]);
    await manager.detail(runId);
    const drawn = sandbox
        .__byId('runs-mgr-body')
        .querySelectorAll('tr')
        .filter((row) => row.id === id)[0];
    return drawn ? drawn.innerHTML : null;
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
   after 停止 until the row carries a verdict. "Carries a verdict" excludes
   `stopping` too, which is the state the Stop request itself writes. */
const LIVE = {
    ok: true,
    runs: [{ run_id: 'live', workflow_name: '在跑', status: 'running', node_done: 1, node_total: 3, rows_kept: 5, wf_count: 1, mode: 'serial', headless: 1 }],
    queue: [],
};
const STOPPING = {
    ok: true,
    runs: [{ run_id: 'live', workflow_name: '在跑', status: 'stopping', node_done: 1, node_total: 3, rows_kept: 5, wf_count: 1, mode: 'serial', headless: 1 }],
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
follow.followedLive = listFetches() > beforeFollow && manager._awaitable() === true;

/* A detail row being read is a reason to leave the table alone: the refresh
   would yank the expansion the user is reading out of the DOM. The id must be
   registered-absent first, or the stub's never-null getElementById answers
   "already open" and nothing gets inserted. */
sandbox.document.absent.add('runs-mgr-detail-live');
sandbox.__routes['/api/runs/live'] = { ok: true, run: { run_id: 'live', status: 'running', nodes: [] } };
await manager.detail('live');
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
follow.settled = manager._awaitable() === false;
follow.showedVerdict = (sandbox.__byId('runs-mgr-body').innerHTML || '').indexOf('st-interrupted') >= 0;

/* The state the Stop request writes itself. A row that says 正在停止 carries no
   verdict either, so watching only for 运行中 would stop re-reading at exactly the
   moment the record had just left it — and 正在停止 would be the last thing on
   screen until somebody clicked the panel again. */
manager._detail = null;
const stoppingAnswers = [STOPPING, STOPPING, SETTLED];
Object.defineProperty(sandbox.__routes, '/api/runs/list', {
    configurable: true,
    get: () => (stoppingAnswers.length > 1 ? stoppingAnswers.shift() : stoppingAnswers[0]),
});
beforeFollow = listFetches();
await manager.awaitSettled(10, 1);
/* Two `stopping` answers then the verdict: three reads, and the watch ends on the
   one that carried a verdict — not on the first answer that merely was not 运行中. */
follow.stoppingKeptWatching = listFetches() - beforeFollow;
follow.stoppingSettled = manager._awaitable() === false;
follow.stoppingLabel = I18n.t(manager.statusKey('stopping'));
/* What that row LOOKS like while it is being read: its own word and chip, and no
   affordance that would discard or resume a run whose rows are still being written.
   Measured off the rendered table because the panel's row markup is where a missing
   label silently falls back to 已完成. */
manager._detail = null;
Object.defineProperty(sandbox.__routes, '/api/runs/list', {configurable: true, get: () => STOPPING});
await manager.refresh();
const stoppingHtml = sandbox.__byId('runs-mgr-body').innerHTML || '';
follow.stoppingChip = stoppingHtml.indexOf('st-stopping') >= 0;
follow.stoppingWord = stoppingHtml.indexOf('>stopping<') >= 0;
follow.stoppingHandlers = [...stoppingHtml.matchAll(/runsManager\.(\w+)\(/g)].map((m) => m[1]);
/* And a status this build has no word for: answering it 已完成 states a fact the
   record never said, which is the one thing a history panel exists to avoid. */
follow.unknownLabel = I18n.t(manager.statusKey('undone-by-a-stranger'));

/* ─── a refresh that lands while the detail fetch is in flight ────────────
   The panel keeps itself current during a live run, which is exactly when a person
   opens a record's detail. The row the click came from can therefore be gone by the
   time the answer arrives — and the code used to insert under THAT row: the detail
   landed in a detached subtree (the user saw nothing) while `_detail` was still set,
   which silenced auto-refresh for an expansion nobody could see. The fetch is held
   open here so the re-render happens between the click and the answer. */
const RACE = {
    ok: true,
    run: {
        run_id: 'r-race',
        status: 'completed',
        started_at: '2026-09-25T10:00:00',
        wf_count: 1,
        workflow_name: '抢刷新的',
        nodes: [{ node_id: 'n-1', node_type: 'source', status: 'done', row_count: 2 }],
    },
};
const raceRow = {
    run_id: 'r-race',
    workflow_name: '抢刷新的',
    status: 'completed',
    node_done: 1,
    node_total: 1,
    rows_kept: 2,
    wf_count: 1,
    mode: 'serial',
    headless: 1,
};
const liveDetailRows = () =>
    sandbox
        .__byId('runs-mgr-body')
        .querySelectorAll('tr')
        .filter((row) => String(row.id || '').indexOf('runs-mgr-detail-') === 0).length;
const race = {};
const realFetch = sandbox.fetch;
let release;
function holdDetail(urlFragment, payload) {
    sandbox.fetch = (url, options) => {
        if (String(url).indexOf(urlFragment) >= 0) {
            return new Promise((resolve) => {
                release = () => resolve({ json: () => Promise.resolve(payload) });
            });
        }
        return realFetch(url, options);
    };
}

manager._detail = null;
sandbox.document.absent.add('runs-mgr-detail-r-race');
manager.render([raceRow]);
holdDetail('/api/runs/r-race', RACE);
const raceInFlight = manager.detail('r-race');
await new Promise((r) => setImmediate(r));
/* The refresh: a new table object, a new <tr> for the same run, and a second record
   that was not there when the click happened. */
manager.render([raceRow, Object.assign({}, raceRow, { run_id: 'r-late', workflow_name: '后来那条' })]);
release();
sandbox.fetch = realFetch;
await raceInFlight;
/* The row exists now, so the scenario stops declaring it absent: that flag stands in for
   "the page has no such id", which is what the toggle-off question asks. */
sandbox.document.absent.delete('runs-mgr-detail-r-race');
race.landed = liveDetailRows();
race.flagMatchesWhatIsShown = manager._detail === 'r-race';
race.rowsShown = sandbox.__byId('runs-mgr-body').querySelectorAll('tr').length;
/* The expansion is now a real row, so the same button closes it — and after that the
   panel is free to refresh again. */
await manager.detail('r-race');
race.collapses = liveDetailRows() === 0 && manager._detail === null;

/* A record that left the list while its detail was being read has nowhere to go:
   saying nothing is the honest answer, and setting the reading flag for it would stop
   the panel updating over a detail that does not exist. */
manager._detail = null;
sandbox.document.absent.add('runs-mgr-detail-gone');
manager.render([Object.assign({}, raceRow, { run_id: 'gone-1' })]);
holdDetail('/api/runs/gone-1', { ok: true, run: { run_id: 'gone-1', status: 'completed', nodes: [] } });
const goneInFlight = manager.detail('gone-1');
await new Promise((r) => setImmediate(r));
manager.render([]);
release();
sandbox.fetch = realFetch;
await goneInFlight;
race.vanishedDrawsNothing = liveDetailRows() === 0 && manager._detail === null;

process.stdout.write(
    JSON.stringify({
        follow,
        race,
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
