/* Drives the server-served node catalogue and the canvas's use of it.
 *
 * Two sources of truth meet here, and the point is that they cannot drift:
 *   · the payload (``GET /api/node-types``) is what a running page reads;
 *   · the canvas's literal table is the cold-page fallback, and this harness returns it per
 *     type so ``test_frontend_node_types_js.py`` can compare it with ``nodes/defaults.py``.
 *
 * Failure is part of the contract: a catalogue that could not be read leaves the fallback in
 * place and says why — it never presents an empty list as "this product has no node types".
 *
 * Usage: node harness_node_types.mjs <canvas.js> <node-types.js> <scenarios.json>
 * scenarios.json = [ { "id", "fetch": {"status": 200, "body": {...}}, "types": ["process", ...] } ]
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { sourceOf } from './companions.mjs';

const [canvasPath, nodeTypesPath, scPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scPath, 'utf8'));

const toasts = [];

function world(sc) {
    const sandbox = {
        ...baseSandbox(),
        I18n: { t: (k) => k },
        showToast: (msg) => toasts.push(String(msg)),
        CustomEvent: class {
            constructor(type) {
                this.type = type;
            }
        },
        fetch: () => {
            const answer = sc.fetch || { status: 200, body: { ok: true, types: [] } };
            return Promise.resolve({
                ok: answer.status >= 200 && answer.status < 300,
                status: answer.status,
                json: () => Promise.resolve(answer.body),
            });
        },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    /* node-types.js announces its answer on the document; the DOM stub has no event bus. */
    sandbox.document.dispatchEvent = () => {};
    /* `sourceOf` follows the split map: the canvas object is several files since 2026-10-29, and
       reading only `canvas.js` boots a canvas whose `init` calls a member that is not there. */
    vm.runInContext(sourceOf(canvasPath) + '\n;globalThis.__canvas = canvas;', sandbox);
    vm.runInContext(sourceOf(nodeTypesPath) + '\n;globalThis.__NodeTypes = NodeTypes;', sandbox);
    return sandbox;
}

const out = {};
for (const sc of scenarios) {
    const sandbox = world(sc);
    const result = { before: {}, fallback: {}, loaded: null };
    const canvas = sandbox.__canvas;
    const types = sc.types || ['name', 'process', 'biblio', 'source'];

    /* The fallback is read BEFORE the catalogue answers — exactly the cold-page path. */
    result.beforeValid = canvas.validNodeTypes();
    for (const type of types) {
        if (type === 'source') continue; // derived from the crawl matrix, not a static table
        result.fallback[type] = canvas.getDefaultParams(type);
    }

    const promise = sandbox.__NodeTypes.load().then(() => {
        result.loaded = {
            ready: sandbox.__NodeTypes.ready(),
            failure: sandbox.__NodeTypes.failure(),
            types: sandbox.__NodeTypes.types(),
            labelKey: sandbox.__NodeTypes.labelKey('process'),
            category: sandbox.__NodeTypes.category('process'),
            defaultsProcess: sandbox.__NodeTypes.defaults('process'),
        };
        /* A mutation of the returned object must not reach the payload: two nodes of one type
           share nothing. */
        const seeded = canvas.getDefaultParams('process');
        seeded.__mutated = true;
        result.afterMutate = canvas.getDefaultParams('process');
        result.validAfter = canvas.validNodeTypes();
        result.toasts = toasts.slice();
    });
    out[sc.id] = { result, promise };
}

/* Each scenario's promise is awaited by the caller through stdout below. */
const ids = Object.keys(out);
Promise.all(ids.map((id) => out[id].promise)).then(() => {
    const payload = {};
    for (const id of ids) payload[id] = out[id].result;
    process.stdout.write(JSON.stringify(payload));
});
