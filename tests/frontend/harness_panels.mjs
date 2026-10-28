/* Drives every bottom-docked panel in the REAL workflow.js + app.js + schedules.js.
 *
 * Console, 运行记录, 导出产物 and the rest share one screen slot, and each writes an
 * inline height when its resize handle is dragged. An inline height beats the CSS
 * `height: 0` that hides a panel, so a panel that is closed by dropping `.open`
 * alone stays visually expanded — which is how two of them ended up stacked on
 * top of each other. This loads all three scripts in one sandbox (workflow.js needs
 * what app.js defines and vice versa; the schedule panel's toggle lives in
 * schedules.js, so that file is loaded for the same reason), and checks:
 *   · opening any one of them closes the others AND clears their inline
 *     height;
 *   · each dock's resize handle really exists;
 *   · the cookie dialog's resize bounds follow the viewport instead of a fixed
 *     500px ceiling.
 *
 * The list below is the dock matrix and is meant to hold one entry per
 * `DOCKED_PANELS` member — `test_frontend_schedules.py` fails a panel that is
 * docked but missing here, because a dock nobody drives is a dock nobody checks.
 *
 * Usage: node harness_panels.mjs <module.js> …   (workflow.js, app.js's catalogue, app.js, schedules.js)
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const modules = process.argv.slice(2).map((p) => ({ path: p, src: fs.readFileSync(p, 'utf8') }));
/* One dock rule is read out of app.js's OWN text, so the list keeps where each source came from.
   Nothing is addressed by index: app.js's catalogue files are part of this list (see
   tests/frontend_catalogue.py::with_catalogue), and a positional read would grab the wrong file. */
const appSrc = modules.find((m) => /(^|[\\/])app\.js$/.test(m.path)).src;

const sandbox = {
    ...baseSandbox(),
    console: { log() {}, warn() {}, error() {} },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
for (const m of modules) vm.runInContext(m.src, sandbox);

const ids = ['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel', 'workflows-panel', 'cookies-panel', 'lexicon-panel', 'schedules-panel', 'processes-panel', 'biblio-panel'];

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
        'cookies-panel': 'toggleCookiesPanel()',
        'lexicon-panel': 'lexiconManager.toggle()',
        'schedules-panel': 'toggleSchedulesPanel()',
        'processes-panel': 'toggleProcessesPanel()',
        'biblio-panel': 'toggleBiblioPanel()',
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
out.lexiconHandle = !!sandbox.__byId('lexicon-resize-handle');
out.dockedList = typeof sandbox.closeDockedPanels === 'function' ? 'helper present' : 'MISSING helper';
/* The cookie dialog's ceiling has to be viewport-derived, not 500px. */
out.cookieBounds = /maxW:\s*Math\.min\(760,\s*window\.innerWidth\s*-\s*40\)[\s\S]{0,80}maxH:\s*window\.innerHeight\s*-\s*40/.test(
    appSrc,
)
    ? 'viewport bounds' : 'still a fixed ceiling';
process.stdout.write(JSON.stringify(out));
