/* Drives the Data Source panel over several /api/capabilities payloads.
 *
 * The panel is generated (workflow.js renders whatever the matrix says), so its
 * own contract is about what it does with an answer — including the answers it
 * must not swallow:
 *   · no payload at all  → the failure note plus a retry, never a blank form;
 *   · a platform nobody declared → a refusal in place of a working-looking form;
 *   · a field key that is not an identifier → dropped, because the renderer
 *     writes the key into an inline handler and a payload is a network input;
 *   · a note with a button whose function the page does not have → the note
 *     alone, since a dead button is worse than a missing one.
 *
 * Usage: node harness_capabilities.mjs <canvas.js> <workflow.js> <scenarios.json>
 * scenarios.json = [ { "id", "payload": <matrix|null|"malformed">,
 *                      "params": {...}, "type": "source" } ]
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [canvasPath, wfPath, scPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scPath, 'utf8'));

const I18n = {
    lang: 'en',
    t(k) {
        return k; // keys, not sentences: the assertions are about WHICH word shows
    },
};

function world() {
    const sandbox = {
        ...baseSandbox(),
        I18n,
        RunState: { parallel: false, headless: true },
        Settings: { save: () => {} },
        showToast: () => {},
        resumeBar: { refresh: () => {} },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    sandbox.window.explainWechatLimits = () => {};
    vm.runInContext(fs.readFileSync(canvasPath, 'utf8') + '\n;globalThis.__canvas = canvas;', sandbox);
    vm.runInContext(fs.readFileSync(wfPath, 'utf8') + '\n;globalThis.__workflow = workflow;', sandbox);
    return sandbox;
}

const out = {};
for (const sc of scenarios) {
    const sandbox = world();
    /* One fresh world per scenario: Capabilities caches what it fetched, so a
       shared one would answer every case with the first payload it ever saw. */
    sandbox.__routes['/api/capabilities'] =
        sc.payload === null ? { ok: true } : sc.payload === 'malformed' ? { nonsense: 1 } : sc.payload;
    await sandbox.Capabilities.load();
    const canvas = sandbox.__canvas;
    const id = 'n1';
    canvas.nodes[id] = { id, type: sc.type || 'source', title: 't', params: sc.params || {}, el: null };
    canvas._settingsNodeId = id;
    sandbox.__byId('settings-content').innerHTML = '';
    sandbox.__wf_open = null;
    vm.runInContext('globalThis.openSettings(globalThis.__canvas._settingsNodeId);', sandbox);
    out[sc.id] = {
        html: sandbox.__byId('settings-content').innerHTML,
        defaults: canvas.getDefaultParams('source'),
        ready: sandbox.Capabilities.ready(),
        modes: sandbox.Capabilities.modes((sc.params || {}).platform || 'zhihu').map((m) => m.key),
    };
}

process.stdout.write(JSON.stringify(out));
