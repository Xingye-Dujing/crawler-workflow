/* Drives the three bottom-docked panels in the REAL workflow.js + app.js.
 *
 * Console, 运行记录 and 导出产物 share one screen slot, and each writes an inline
 * height when its resize handle is dragged. An inline height beats the CSS
 * `height: 0` that hides a panel, so a panel that is closed by dropping `.open`
 * alone stays visually expanded — which is how two of them ended up stacked on
 * top of each other. This loads both scripts in one sandbox (workflow.js needs
 * what app.js defines and vice versa), and checks:
 *   · opening any one of the three closes the other two AND clears their inline
 *     height;
 *   · the export panel's resize handle really exists;
 *   · the cookie dialog's resize bounds follow the viewport instead of a fixed
 *     500px ceiling.
 *
 * Usage: node harness_panels.mjs <workflow.js> <app.js>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const workflowSrc = fs.readFileSync(process.argv[2], 'utf8');
const appSrc = fs.readFileSync(process.argv[3], 'utf8');

const sandbox = {
    ...baseSandbox(),
    console: { log() {}, warn() {}, error() {} },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(workflowSrc, sandbox);
/* app.js is an IIFE-ish sibling of workflow.js in the browser: same global. */
vm.runInContext(appSrc, sandbox);

const ids = ['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel', 'workflows-panel'];

function state() {
    const out = {};
    for (const id of ids) {
        const el = sandbox.__byId(id);
        out[id] = { open: el.classList.contains('open'), height: el.style.height || '' };
    }
    return out;
}

const out = {};
/* Each opening must leave exactly one panel open, with no stale inline height. */
for (const target of ids) {
    for (const id of ids) {
        const el = sandbox.__byId(id);
        el.classList.add('open');
        el.style.height = '300px';
    }
    const togglers = {
        'console-panel': 'toggleConsole()',
        'runs-panel': 'runsManager.toggle()',
        'exports-panel': 'exportsManager.toggle()',
        'dataset-panel': 'datasetManager.toggle()',
        'workflows-panel': 'wfFiles.toggle()',
    };
    const toggler = togglers[target];
    sandbox.__byId(target).classList.remove('open');
    try {
        vm.runInContext(toggler, sandbox);
    } catch (e) {
        out[toggler] = 'THREW ' + String(e).slice(0, 120);
        continue;
    }
    const after = state();
    out[target] = {
        opened: ids.filter((id) => after[id].open),
        staleHeights: ids.filter((id) => after[id].height && !after[id].open),
    };
}

out.exportHandle = !!sandbox.__byId('exports-resize-handle');
out.datasetHandle = !!sandbox.__byId('dataset-resize-handle');
out.workflowsHandle = !!sandbox.__byId('workflows-resize-handle');
out.dockedList = typeof sandbox.closeDockedPanels === 'function' ? 'helper present' : 'MISSING helper';
/* The cookie dialog's ceiling has to be viewport-derived, not 500px. */
out.cookieBounds = /maxW:\s*Math\.min\(760,\s*window\.innerWidth\s*-\s*40\)[\s\S]{0,80}maxH:\s*window\.innerHeight\s*-\s*40/.test(
    appSrc,
)
    ? 'viewport bounds' : 'still a fixed ceiling';
process.stdout.write(JSON.stringify(out));
