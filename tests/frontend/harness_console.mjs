/* Runs the REAL run-console poller (backend/static/js/workflow.js `pollStatus`) under node.
 *
 * The console is the only place a user sees a run happening, so its cursor rules
 * are user-visible correctness, and each one has already broken once:
 *   · past 200 lines the browser believed it had seen everything (the delta has
 *     to come from the reported total, not from the truncated array);
 *   · a SECOND run restarts that total below the consumed index, which used to
 *     slice the array empty for the rest of the run — a frozen console with a
 *     live run behind it;
 *   · switching to the "all" tab cleared the DOM without moving any cursor, so
 *     the tab came back blank while per-workflow tabs re-rendered;
 *   · the cookie-expiry toast must shout once, not every second.
 * None of that is visible to a Python test, so this harness loads the untouched
 * file, feeds scripted /api/workflow/status answers to one poll tick at a time,
 * and reports which lines landed in the DOM.
 *
 * Usage: node harness_console.mjs <workflow.js> <stats.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

/* Two files, not one: the run's last poll refreshes the stats panel through the
   real `stats` object, which lives in stats.js. */
const src = process.argv.slice(2).map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

const KEYS = {
    'status.running': 'running',
    'status.progress': 'progress {done}/{total}',
    'status.completed': 'completed',
    'status.stopping': 'STOPPING',
    'status.nodes': 'Nodes: ',
    'console.all': 'ALL',
    'toast.stopping': 'STOPPING-TOAST',
    'toast.stillSettling': 'STILL-SETTLING',
    'toast.cookieExpired': 'COOKIE-EXPIRED',
    'toast.workflowCompleted': 'WORKFLOW-COMPLETED',
    'toast.workflowEnded': 'WORKFLOW-ENDED {done}/{total}',
    'toast.workflowRejected': 'WORKFLOW-REJECTED',
    'toast.workflowStopped': 'WORKFLOW-STOPPED',
    'name.unnamed': 'unnamed',
};
const I18n = { lang: 'en', dict: { en: KEYS, zh: {} }, t(k) { return KEYS[k] || k; }, apply() {} };

const toasts = [];
const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas: { nodes: {}, connections: [], toWorkflowJSON: () => ({ nodes: {}, connections: [] }) },
    RunState: { running: false, setRunning(v) { this.running = v; } },
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'm', api_key: '' }) },
    escapeHtml: (s) => String(s),
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__wf = { workflow, clearConsole, switchWfTab, consoleViews };', sandbox);
/* Assigned after the load: workflow.js declares showToast itself, and a function
   declaration inside the script wins over anything seeded before it. */
sandbox.showToast = (msg) => toasts.push(String(msg));

/* The poller is a setInterval callback; capture it so the test drives one tick at
   a time against scripted answers, with no wall clock involved. */
let tick = null;
let nextAnswer = null;
sandbox.setInterval = (fn) => {
    tick = fn;
    return 1;
};
sandbox.clearInterval = () => {
    tick = null;
};
sandbox.fetch = () => Promise.resolve({ json: () => Promise.resolve(nextAnswer) });

const consoleOutput = sandbox.__byId('console-output');
/* `const workflow` is script-scoped, not a sandbox property, so everything the
   test calls comes out of the export the script line appended. */
const wf = sandbox.__wf.workflow;
const clearConsole = sandbox.__wf.clearConsole;
const switchWfTab = sandbox.__wf.switchWfTab;
function lines() {
    return (consoleOutput.children || []).map((child) => child.textContent);
}

async function answer(payload) {
    const before = lines().length;
    nextAnswer = payload;
    await tick();
    await new Promise((r) => setImmediate(r));
    return lines().slice(before);
}

function status(logs, total, extra) {
    return Object.assign(
        {
            running: true,
            logs: logs,
            log_total: total,
            workflows: [],
            mode: 'serial',
            results: [],
            chart_results: {},
            cookie_expired: false,
            queue: [],
            total_nodes: 3,
            completed_nodes: 0,
        },
        extra || {}
    );
}

const out = { label: 'console poller' };

/* The settle budget, read out of the file under test rather than copied here: the
   scenario below walks the poller to the END of that budget, so a constant kept in
   two places would silently stop short (or spin forever) after someone changed it. */
const SETTLE_BUDGET = Number(/var SETTLE_TICKS = (\d+);/.exec(src)?.[1]);
if (!Number.isFinite(SETTLE_BUDGET) || SETTLE_BUDGET < 30) {
    throw new Error(`settle budget missing or too short in workflow.js: ${SETTLE_BUDGET}`);
}

/** Forget everything the browser believes it has shown.
 *
 * Stands in for a fresh page: the state under test is what one poll does to the
 * view history, so a scenario cannot inherit the previous one's cursors. */
function resetViews() {
    sandbox.__wf.consoleViews.all = { seen: 0, lines: [] };
    sandbox.__wf.consoleViews.wf = {};
}

wf.pollStatus();

/* ── 1. a growing first run ─────────────────────────────────────────────── */
out.firstBatch = await answer(status(['a1', 'a2', 'a3'], 3));
out.secondBatch = await answer(status(['a1', 'a2', 'a3', 'a4', 'a5'], 5));

/* ── 2. a second run restarts the server buffer below the consumed index ── */
out.afterRestart = await answer(status(['b1', 'b2'], 2));

/* ── 3. past the 200-line cap the total is the only source of the delta ─── */
clearConsole();
resetViews();
const held = [];
for (let i = 1; i <= 200; i++) held.push('line-' + i);
out.cappedFirst = (await answer(status(held, 250))).length;
out.cappedDelta = await answer(status(held.slice(50).concat(['line-251']), 251));

/* ── 4. clearing shows the next line, not a replay of what is held ──────── */
clearConsole();
out.afterClear = await answer(status(held.slice(50).concat(['line-251', 'line-252']), 252));

/* ── 5. a tab switch keeps what the view had already shown ──────────────── */
/* The complaint this answers: switching 工作流标签页 used to blank the box, and
   nothing came back until the next line was written — which for a finished run is
   never. Leaving and returning must be a no-op on content. */
const beforeSwitch = lines();
switchWfTab(3);
out.blankOnUnknownTab = lines().length;
switchWfTab('all');
out.afterTabSwitch = {
    kept: lines().length,
    same: JSON.stringify(lines()) === JSON.stringify(beforeSwitch),
    // and the next poll still appends only what is new — no replay of the tail
    next: await answer(status(['only-one'], beforeSwitch.length + 1)),
};

/* ── 6. the expiry toast shouts once ────────────────────────────────────── */
toasts.length = 0;
await answer(status(['c1'], beforeSwitch.length + 2, { cookie_expired: true }));
await answer(status(['c1', 'c2'], beforeSwitch.length + 3, { cookie_expired: true }));
out.expiryToasts = toasts.slice();

/* ── 7. parallel mode: one tab per workflow, each with its own history ──── */
clearConsole();
resetViews();
switchWfTab('all');
const wfA = { id: 0, name: '甲', logs: ['a-only'], total: 1 };
const wfB = { id: 1, name: '乙', logs: ['b-only'], total: 1 };
out.parallelFirst = await answer(status(['shared'], 1, { workflows: [wfA, wfB], mode: 'parallel' }));
out.tabCount = (sandbox.__byId('console-tabs').innerHTML.match(/console-tab/g) || []).length;
/* B's tab has never been visible, yet its poll-fed history is what the click must
   show — a tab that starts empty when opened is the same bug in a new place. */
switchWfTab(1);
out.tabBOnOpen = lines();
out.tabB = await answer(
    status(['shared'], 1, { workflows: [wfA, { id: 1, name: '乙', logs: ['b-only', 'b-two'] }], mode: 'parallel' })
);
/* And the other tab did not absorb it on the way back. */
switchWfTab('all');
out.allAfterB = lines();

/* ── 8. how the run is announced when it stops ─────────────────────────── */
/* `var resumeBar` is a global binding, so replacing it here is what the poller
   will call. Whether it is asked to refresh IS the assertion: a continue banner
   that appears after a clean completion promises a resume with nothing behind it. */
let resumeRefreshes = 0;
sandbox.resumeBar = { refresh: () => { resumeRefreshes++; } };

async function finishCase(name, payload) {
    toasts.length = 0;
    resumeRefreshes = 0;
    tick = null; // the previous case ended the interval, as in the browser
    wf.pollStatus();
    await answer(payload);
    out[name] = {
        toasts: toasts.slice(),
        statusNodes: sandbox.__byId('status-nodes').textContent,
        statusText: sandbox.__byId('status-text').textContent,
        resumeRefreshed: resumeRefreshes > 0,
    };
}

await finishCase('endedFailed', status(['done'], 4, { running: false, completed_nodes: 2, total_nodes: 3, outcome: 'failed' }));
await finishCase(
    'endedCompleted',
    status(['done'], 4, { running: false, completed_nodes: 3, total_nodes: 3, outcome: 'completed' })
);
await finishCase(
    'endedRejected',
    status(['done'], 4, { running: false, completed_nodes: 0, total_nodes: 0, outcome: 'rejected' })
);
await finishCase(
    'endedInterrupted',
    status(['done'], 4, { running: false, completed_nodes: 1, total_nodes: 3, outcome: 'interrupted' })
);

/* A Stop flips running off before the worker writes the verdict. The poller must
   NOT announce an outcome in that window — it keeps reading until the record
   settles. This is the gap that made the panel show 运行中 forever: here it is
   measured as "no verdict toast on the settling tick, verdict on the settled one". */
async function settleCase(name, payloads) {
    toasts.length = 0;
    resumeRefreshes = 0;
    tick = null;
    wf.pollStatus();
    const sawTick = [];
    for (const payload of payloads) {
        await answer(payload);
        sawTick.push(tick !== null); // still polling?
    }
    out[name] = { toasts: toasts.slice(), stillPolling: sawTick };
}

await settleCase('settlingThenSettled', [
    status(['working'], 4, { running: false, settling: true, completed_nodes: 1, total_nodes: 3, outcome: '' }),
    status(['done'], 4, { running: false, completed_nodes: 1, total_nodes: 3, outcome: 'interrupted' }),
]);

/* ── 9. what the panel is asked to do while a stop settles ──────────────── */
/* The complaint this is measured against: after 停止 the run record went on reading
   运行中 for as long as the worker took to unwind, and the only thing that fixed it
   faster was restarting the service. Two halves: the record itself is flipped to
   `stopping` by the Stop request, and the panel has to be RE-read through the whole
   settling window — which it was not, because the refresh rode on `result.running`. */
let refreshes = 0;
sandbox.runsManager.autoRefresh = () => {
    refreshes += 1;
};
toasts.length = 0;
tick = null;
wf.pollStatus();
await answer(status(['working'], 4, { running: false, settling: true, completed_nodes: 1, total_nodes: 3, outcome: '' }));
out.settlingTick = { refreshed: refreshes, toasts: toasts.slice(), stillPolling: tick !== null };
await answer(status(['done'], 4, { running: false, completed_nodes: 1, total_nodes: 3, outcome: 'interrupted' }));
out.settledTick = { refreshed: refreshes, toasts: toasts.slice(), stillPolling: tick !== null };

/* The panel's own reading of the in-between record: a word for it, and the rule
   that it is not yet settled. Falling through to `completed` here would print the
   opposite of the truth for the few seconds the state lasts. */
out.stoppingChip = sandbox.runsManager.statusKey('stopping');
out.stoppingIsAwaited = sandbox.runsManager._awaitable.call({ _shown: [{ status: 'stopping' }] });
out.settledIsNotAwaited = sandbox.runsManager._awaitable.call({ _shown: [{ status: 'interrupted' }] });

/* Out of budget the poller must stop WITHOUT inventing a verdict: `outcome` is the
   empty string while the worker is still unwinding, and reading a failure out of
   that told the user their own button press had broken the workflow. */
toasts.length = 0;
tick = null;
resumeRefreshes = 0;
wf.pollStatus();
const wedged = status(['working'], 4, { running: false, stopping: true, completed_nodes: 1, total_nodes: 3, outcome: '' });
for (let i = 0; i <= SETTLE_BUDGET; i++) await answer(wedged);
out.budgetExhausted = {
    toasts: toasts.slice(),
    statusText: sandbox.__byId('status-text').textContent,
    stillPolling: tick !== null,
    resumeRefreshed: resumeRefreshes,
};

/* ── 10. how long the panel watches a stopping record ───────────────────── */
/* `awaitSettled` used to poll a list captured BEFORE its own re-read, so the row
   that had just landed 已中断 was still believed to be running: every 停止 repainted
   the table twenty times and then gave up without a word. The two cases below are
   the two halves of that — keep watching while it is unsettled, stop the moment the
   fresh answer says it is not. */
const listReads = { n: 0 };
let listScript = [];
const statusFetch = sandbox.fetch;
sandbox.fetch = (url) => {
    if (String(url).indexOf('/api/runs/list') === 0) {
        const status = listScript.length > 1 ? listScript.shift() : listScript[0];
        listReads.n += 1;
        return Promise.resolve({
            json: () => Promise.resolve({ ok: true, runs: [{ run_id: 'r1', status, nodes: [] }], queue: [] }),
        });
    }
    return statusFetch(url);
};
sandbox.__byId('runs-panel').classList.add('open');

listScript = ['stopping', 'stopping', 'stopping', 'interrupted'];
listReads.n = 0;
await sandbox.runsManager.awaitSettled(20, 0);
out.awaitStopsOnTheFreshAnswer = { reads: listReads.n, last: sandbox.runsManager._shown[0].status };

listScript = ['running', 'running', 'running'];
listReads.n = 0;
await sandbox.runsManager.awaitSettled(3, 0);
out.awaitKeepsWatchingAnUnsettledRow = listReads.n;
sandbox.__byId('runs-panel').classList.remove('open');

/* Pressing 停止 announces "stopping…", not "stopped" — the run has not reported
   an outcome yet, and the toast that lies about it is what the user reads. */
toasts.length = 0;
sandbox.__byId('status-text').textContent = 'running';
nextAnswer = { ok: true, browsers: 2 };
await wf.stop();
out.stopPress = {
    toasts: toasts.slice(),
    statusText: sandbox.__byId('status-text').textContent,
};

/* The status bar carries the activity without the console's clock, and keeps the
   progress ratio rather than overwriting it with a different statistic. */
out.statusBarDuringRun = null;
tick = null;
wf.pollStatus();
await answer(status(['[12:00:01] Executing node: 抓取 #node-1'], 5, { completed_nodes: 1, total_nodes: 3 }));
out.statusBarDuringRun = {
    text: sandbox.__byId('status-text').textContent,
    nodes: sandbox.__byId('status-nodes').textContent,
};

process.stdout.write(JSON.stringify(out));
