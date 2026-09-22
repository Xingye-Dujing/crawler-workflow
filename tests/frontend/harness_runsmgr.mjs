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
    canvas: { nodes: {}, connections: [] },
    RunState: { running: false },
};
vm.createContext(sandbox);
vm.runInContext(src + '\n;globalThis.__wf = { runsManager };', sandbox);
/* Assigned after the script ran: workflow.js declares showToast itself, and a
   function declaration in the script wins over anything seeded before it. */
sandbox.showToast = (msg) => captured.toasts.push(String(msg));
sandbox.fetch = (url, options) => {
    captured.posts.push({ url, body: options && options.body ? JSON.parse(options.body) : null });
    return Promise.resolve({ json: () => Promise.resolve({ ok: true, removed: true }) });
};
sandbox.__byId('runs-mgr-body').innerHTML = '';
const manager = sandbox.__wf.runsManager;
manager._queue = runs.queue || [];
manager.render(runs.runs);
const html = sandbox.__byId('runs-mgr-body').innerHTML;
/* Awaited: the toast lands after the response, and stdout is written now. */
await manager.cancelQueued('q1');
/* The report button may name the run only by id: a workflow name is user text,
   and one double quote in it would close the onclick attribute and let whatever
   follows become markup. */
process.stdout.write(
    JSON.stringify({
        html,
        count: sandbox.__byId('runs-mgr-count').textContent,
        reports: (html.match(/runsManager\.report\(/g) || []).length,
        nameInHandler: /onclick="[^"]*获取微博/.test(html),
        queueRows: (html.match(/runsManager\.cancelQueued\(/g) || []).length,
        posts: captured.posts,
        toasts: captured.toasts,
    }),
);
