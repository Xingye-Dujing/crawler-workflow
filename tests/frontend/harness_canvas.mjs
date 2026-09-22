/* Node harness for the canvas serialization contract (tests/unit/test_frontend_contract.py).
 *
 * Why this exists: /api/workflow/execute receives the JSON canvas.toWorkflowJSON()
 * builds, and a field dropped there (title once was) is invisible to every
 * Python test — they hand-build their own workflow dicts. This harness runs the
 * REAL canvas.js in a stubbed browser world and prints what the backend would
 * actually receive, so the contract is testable from pytest.
 *
 * Usage: node harness_canvas.mjs <path/to/canvas.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { fixWindow } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');

const fakeEl = null; // getElementById: no element anywhere — toWorkflowJSON must cope
const sandbox = {
    console,
    document: {
        getElementById: () => fakeEl,
        querySelectorAll: () => [],
        addEventListener: () => {},
        createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {} }),
    },
    window: {},
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    I18n: { t: (k) => k, lang: 'en', dict: { en: {}, zh: {} } },
    RunState: { parallel: false, headless: true },
    Settings: { save: () => {} },
    showToast: () => {},
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__canvas = canvas;', sandbox);

const canvas = sandbox.__canvas;
canvas.nodes = {
    'node-1': { id: 'node-1', type: 'source', title: '我的抓取', params: { platform: 'weibo', keyword: '测试' } },
    'node-2': { id: 'node-2', type: 'output', title: 'node-2', params: { operation: 'save' } },
};
canvas.connections = [{ from: 'node-1', to: 'node-2' }];
process.stdout.write(JSON.stringify(canvas.toWorkflowJSON()));
