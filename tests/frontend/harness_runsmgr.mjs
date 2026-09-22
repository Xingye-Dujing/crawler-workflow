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

import { baseSandbox } from './harness_dom.mjs';

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
        saveState: () => {},
    },
    RunState: { running: false, setRunning(v) { this.running = v; } },
    /* Lives in app.js; execute() reads the transport choice off it before POSTing. */
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'qwen3.5:9b', api_key: '' }) },
};
vm.createContext(sandbox);
vm.runInContext(src + '\n;globalThis.__wf = { runsManager, workflow };', sandbox);
/* Assigned after the script ran: workflow.js declares showToast itself, and a
   function declaration in the script wins over anything seeded before it. */
sandbox.showToast = (msg) => captured.toasts.push(String(msg));
sandbox.fetch = (url, options) => {
    captured.posts.push({ url, body: options && options.body ? JSON.parse(options.body) : null });
    return Promise.resolve({ json: () => Promise.resolve({ ok: true, removed: true, run_id: 'r-new' }) });
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
    settings: { mode: 'serial' },
});
const before = captured.posts.length;
await wf.execute({ resumeRunId: 'r-int' });
const resumePost = captured.posts.slice(before).find((p) => p.url === '/api/workflow/execute');
const beforePlain = captured.posts.length;
await wf.execute({});
const plainPost = captured.posts.slice(beforePlain).find((p) => p.url === '/api/workflow/execute');

/* The report button may name the run only by id: a workflow name is user text,
   and one double quote in it would close the onclick attribute and let whatever
   follows become markup. */
process.stdout.write(
    JSON.stringify({
        html,
        count: countText,
        reports: (html.match(/runsManager\.report\(/g) || []).length,
        nameInHandler: /onclick="[^"]*获取微博/.test(html),
        queueRows: (html.match(/runsManager\.cancelQueued\(/g) || []).length,
        posts: captured.posts,
        toasts: cancelToasts,
        resumeBody: resumePost ? resumePost.body : null,
        plainBody: plainPost ? plainPost.body : null,
        // Whatever the two execute() calls said — a refused preflight shows here
        // rather than as a missing POST with no reason attached.
        executeToasts: captured.toasts.slice(cancelToasts.length),
    }),
);
