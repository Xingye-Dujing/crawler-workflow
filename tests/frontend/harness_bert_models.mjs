/* Drives the multi-model BERT picker over several /api/models payloads and stored values.

   renderBertField (workflow.js) is the one place the analyzer nodes' BERT field is built. Its
   contract with the registry is browser-side and the backend cannot see it, so each case is run
   against the real code:

     · every registered model becomes ONE checkbox — the label is the friendly NAME, the value
       written into bert_models is that model's PATH;
     · the stored bert_models is echoed back (only the boxes whose path is in it come checked);
     · two or more checked reveals the "this node will now emit a tidy comparison table" hint,
       so the user is never surprised by the row count changing underneath them;
     · an EMPTY registry draws no checkbox group at all — only the raw path box stays, which is
       the honest state when nobody has registered a model;
     · a single stored bert_model (a pre-multi-model canvas) still shows in the raw path box.

   toggleBertModel's job — de-dup and SORT the selection so one model set is one fingerprint
   whatever the click order — is exercised by calling it for real and reading the param back.

   Usage: node harness_bert_models.mjs <canvas.js> <workflow.js> <scenarios.json>
   scenarios.json = [ { "id", "models": [ {name,path} ] | 'malformed',
                        "bert_model": <str?>, "bert_models": <str?>,
                        "toggle": [ {path, checked}, ... ] } ]
*/
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [canvasPath, wfPath, scPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scPath, 'utf8'));

const I18n = {
    lang: 'en',
    asked: [],
    t(k) {
        this.asked.push(k);
        return k;
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
    vm.runInContext(fs.readFileSync(wfPath, 'utf8'), sandbox);
    return sandbox;
}

/* The checkbox rows are labelled by the model NAME; count boxes and how many are checked,
   and read the raw path box (the field whose handler writes bert_model). */
function inspect(html) {
    const boxes = [...html.matchAll(/<input type="checkbox"([^>]*)onchange="toggleBertModel\([^)]*\)">\s*([^<]*)</g)];
    const pathValue = (html.match(/value="([^"]*)"[^>]*onchange="updateParam\('[^']*','bert_model'/) || [])[1];
    return {
        checkboxCount: boxes.length,
        checkedNames: boxes.filter((m) => /\bchecked\b/.test(m[1])).map((m) => m[2].trim()),
        hasGroup: html.includes('settings.bertModelsPick'),
        hasMultiHint: html.includes('hint.bertModelsMulti'),
        hasPathBox: html.includes("'bert_model',this.value"),
        pathBoxValue: pathValue === undefined ? null : pathValue,
    };
}

const out = {};
for (const sc of scenarios) {
    const sandbox = world();
    sandbox.__routes['/api/models'] = sc.models === 'malformed' ? { nonsense: 1 } : { ok: true, models: sc.models };
    await sandbox.BertModels.load();

    const id = 'n1';
    const canvas = sandbox.__canvas;
    canvas.nodes[id] = {
        id,
        type: 'process',
        title: 't',
        params: { operation: sc.operation || 'sentiment', mode: 'bert', bert_model: sc.bert_model || '', bert_models: sc.bert_models || '' },
        el: null,
    };
    // Keep the panel closed so updateParam's re-render never runs; the toggle test reads the
    // param the same way a real click writes it.
    canvas._settingsNodeId = null;
    canvas.updateNodeDisplay = () => {};
    canvas.saveState = () => {};
    I18n.asked = [];

    const html = vm.runInContext(
        `globalThis.renderBertField('n1', globalThis.__canvas.nodes['n1'].params)`,
        sandbox
    );

    const toggled = [];
    for (const step of sc.toggle || []) {
        vm.runInContext(
            `globalThis.toggleBertModel('n1', ${JSON.stringify(step.path)}, ${step.checked})`,
            sandbox
        );
        toggled.push(canvas.nodes[id].params.bert_models);
    }

    out[sc.id] = { ...inspect(html), toggled };
}

process.stdout.write(JSON.stringify(out));
