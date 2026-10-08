/* Drives the bert-mode model picker over several /api/models payloads.

   renderBertField (workflow.js) is the one place the analyzer nodes' BERT field is
   built, and it has a contract with the registry that the backend cannot see:

     · registered models → a name→path <select>, each option's VALUE is the model's
       path (that is what lands in bert_model and what the run loads) while the LABEL
       is the friendly name (「网暴模型」);
     · a stored path that IS a registered one → that option is selected, so reopening
       the panel shows what the node will actually run;
     · a stored path that is NOT registered → it must still show itself (selectOptionTags
       appends it as 「不是可选项」), never silently reverting to the first model;
     · a blank stored path → the blank placeholder is selected, never option #0, since a
       model the user never picked must not look picked;
     · an EMPTY registry → no picker at all, just the raw path box.

   Usage: node harness_bert_models.mjs <canvas.js> <workflow.js> <scenarios.json>
   scenarios.json = [ { "id", "models": [ {name,path,desc} ] | 'malformed',
                        "params": {...} } ]
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
    /* `canvas` is a top-level const in canvas.js, so it never lands on window — the
       host reaches it through the same __canvas hook the capabilities harness uses. */
    vm.runInContext(fs.readFileSync(canvasPath, 'utf8') + '\n;globalThis.__canvas = canvas;', sandbox);
    vm.runInContext(fs.readFileSync(wfPath, 'utf8'), sandbox);
    return sandbox;
}

/* Pull every <option> out of ONE <option>-bearing select. escapeHtml never emits a
   bare double-quote, so splitting the value on " is safe. */
function parseOptions(selectHtml) {
    const re = /<option value="([^"]*)"([^>]*)>([\s\S]*?)<\/option>/g;
    const out = [];
    let m;
    while ((m = re.exec(selectHtml)) !== null) {
        out.push({ value: m[1], selected: /\bselected\b/.test(m[2]), label: m[3] });
    }
    return out;
}

/* The picker is the <select> whose LABEL is settings.bertModelPick — anchoring on the
   label isolates it from the mode select that shares the same panel. Returns null when
   no such select was rendered (the empty-registry case). */
function pickerOptions(html) {
    const at = html.indexOf('settings.bertModelPick');
    if (at === -1) return null;
    const start = html.indexOf('<select', at);
    if (start === -1) return null;
    const end = html.indexOf('</select>', start);
    return parseOptions(html.slice(start, end === -1 ? undefined : end + 9));
}


const out = {};
for (const sc of scenarios) {
    const sandbox = world();
    /* One fresh world per scenario: BertModels caches what it fetched, so a shared one
       would answer every case with the first payload it ever saw. */
    sandbox.__routes['/api/models'] = sc.models === 'malformed' ? { nonsense: 1 } : { ok: true, models: sc.models };
    await sandbox.BertModels.load();

    const id = 'n1';
    const canvas = sandbox.__canvas;
    canvas.nodes[id] = {
        id,
        type: 'process',
        title: 't',
        params: Object.assign({ operation: 'sentiment', mode: 'bert' }, sc.params || {}),
        el: null,
    };
    canvas._settingsNodeId = id;
    sandbox.__byId('settings-content').innerHTML = '';
    I18n.asked = [];
    vm.runInContext('globalThis.openSettings(globalThis.__canvas._settingsNodeId);', sandbox);

    const html = sandbox.__byId('settings-content').innerHTML;
    out[sc.id] = {
        picker: pickerOptions(html),
        /* The raw path box always exists beside the picker, so a name is a shortcut
           to it rather than a replacement. Proved by the field's own label + handler. */
        hasPathBox: html.includes('settings.bertModel</label>') && html.includes("'bert_model',this.value"),
        /* The path box mirrors bert_model: the stored value is written into its value=. */
        pathBoxValue: (() => {
            const m = html.match(/value="([^"]*)"[^>]*onchange="updateParam\('[^']*','bert_model',this\.value\)"/);
            return m ? m[1] : null;
        })(),
        bertList: sandbox.BertModels.list(),
    };
}

process.stdout.write(JSON.stringify(out));
