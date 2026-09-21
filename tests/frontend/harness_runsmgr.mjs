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
            'runsMgr.colStarted': 'started',
        },
        zh: {},
    },
    t(k) {
        return this.dict.en[k] || k;
    },
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas: { nodes: {}, connections: [] },
    RunState: { running: false },
    showToast: () => {},
};
vm.createContext(sandbox);
vm.runInContext(src + '\n;globalThis.__wf = { runsManager };', sandbox);

sandbox.__byId('runs-mgr-body').innerHTML = '';
sandbox.__wf.runsManager.render(runs.runs);
process.stdout.write(
    JSON.stringify({
        html: sandbox.__byId('runs-mgr-body').innerHTML,
        count: sandbox.__byId('runs-mgr-count').textContent,
    }),
);
