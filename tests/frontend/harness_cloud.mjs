/* Runs the cloud-deployment switch against the REAL app.js + workflow.js.
 *
 * `python app.py cloud` is the server's fact, and the page is told through
 * /api/config.cloud_mode. What the page then does with it is JS, so Python cannot see
 * any of it:
 *
 *   · the transport is taken OUT of the provider select — a hidden <option> is still a
 *     value the element can be asked for, and this host cannot serve it;
 *   · a stored 「ollama」 in localStorage is normalised to the transport that can run,
 *     because the run body is built from the same object;
 *   · the 「本地 Ollama」 half of the process node's mode label is not shown, since a
 *     word naming a transport with no daemon behind it is a lie in two languages;
 *   · the flag arrives asynchronously, so everything above has to be re-applied when it
 *     lands rather than only at the first paint.
 *
 * Usage: node harness_cloud.mjs <canvas.js> <workflow.js> <app.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { addOptions, baseSandbox, fixWindow, resetWorld } from './harness_dom.mjs';

const [canvasPath, wfPath, appPath] = process.argv.slice(2);
const src = [canvasPath, wfPath, appPath].map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

/* One /api/config answer, switchable per scenario: the real boot reads it once, and the
   assertions below are about what the page does with the answer it got. */
let cloudAnswer = false;
const requests = [];
const sandbox = { ...baseSandbox() };
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(
    `${src}
     ;globalThis.__cloud = { CloudMode, LLMSettings, llmModeLabel, I18n, PrivacyNotice };`,
    sandbox,
);
/* `const` bindings are lexical, not properties of the context object, so the only way
   out here is the export line above — reaching for `sandbox.CloudMode` reads as missing. */
const { CloudMode, LLMSettings, llmModeLabel, I18n, PrivacyNotice } = sandbox.__cloud;
sandbox.fetch = () => {
    requests.push('/api/config');
    return Promise.resolve({
        json: () =>
            Promise.resolve({
                ollama_model: 'qwen-pulled:7b',
                default_headless: true,
                max_workers: 4,
                cloud_mode: cloudAnswer,
            }),
    });
};

/* Every dialog the page raised, with what its buttons would resolve to. Installed after
   the sources run: app.js calls `showDialog` by name, so the stub has to be what the
   context resolves at call time. */
const dialogs = [];
sandbox.showDialog = (spec) => {
    dialogs.push({
        message: String(spec.message || ''),
        labels: (spec.buttons || []).map((b) => b.label),
        values: (spec.buttons || []).map((b) => ('value' in b ? String(b.value) : '<absent>')),
    });
    return Promise.resolve(sandbox.__answer === undefined ? null : sandbox.__answer);
};

const doc = sandbox.document;
const flush = async () => {
    for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r));
};

/* The AI submenu as the page ships it: one row holding the provider select with BOTH
   transports in it. Built element by element — no markup string is parsed, so the option
   list the guards below consult is the same tree a browser would walk. */
function buildAiMenu() {
    /* A clean world per scenario: `getElementById` resolves through the document's id
       registry, and a select left in it by the previous scenario is the one the flag
       would then edit — the page under test would keep both transports while the harness
       reported a removal that happened to a detached element. */
    resetWorld(sandbox);
    const doc2 = sandbox.document;
    const row = doc2.createElement('div');
    row.className = 'dd-item-row';
    const select = doc2.createElement('select');
    select.id = 'ai-provider';
    select.className = 'settings-select';
    addOptions(doc2, select, ['ollama', 'openrouter']);
    row.appendChild(select);
    doc2.body.appendChild(row);
    const ollamaModel = doc2.createElement('input');
    ollamaModel.id = 'ai-ollama-model';
    ollamaModel.className = 'ai-only-ollama';
    doc2.body.appendChild(ollamaModel);
}

const providerValues = () =>
    Array.prototype.map.call(doc.getElementById('ai-provider').options || [], (o) => o.value);

const out = {};

function boot() {
    /* A fresh world AND a fresh /api/config pull: `loadDefaults` guards itself so a page
       asks once, which is right for a browser and would make the second scenario below
       measure the first one's answer. */
    LLMSettings._defaultsPulled = false;
    buildAiMenu();
}

/* ── a desktop boot: nothing is taken away ─────────────────────────────── */
cloudAnswer = false;
boot();
sandbox.localStorage.setItem('crawler_llm', JSON.stringify({ provider: 'ollama', ollama: { model: 'q:1' } }));
LLMSettings.applyToPanel();
await LLMSettings.loadDefaults();
await flush();
out.desktop = {
    flag: CloudMode.on,
    dataCloud: doc.documentElement.dataset.cloud,
    providers: providerValues(),
    active: LLMSettings.load().provider,
    payload: LLMSettings.payload().provider,
    label: llmModeLabel(),
    configAsked: requests.length,
    /* The notice is a cloud thing or it is noise: on the machine whose owner is standing
       in front of it, "your cookies live on this disk" says nothing they can act on. */
    dialogs: dialogs.slice(),
};

/* ── the same page booted on a server ─────────────────────────────────── */
cloudAnswer = true;
boot();
sandbox.localStorage.setItem(
    'crawler_llm',
    JSON.stringify({
        provider: 'ollama',
        ollama: { model: 'q:1' },
        openrouter: { model: 'deepseek:free', api_key: 'sk-stored-here' },
    })
);
/* The panel is filled from localStorage BEFORE the flag lands — that is the real order,
   applyToPanel runs at boot and /api/config answers a tick later — so a stored 「ollama」
   is the selected transport when the flag arrives. Everything below is measured AFTER
   that, because "correct only on a fresh load" is not what a booted page does. */
LLMSettings.applyToPanel();
await LLMSettings.loadDefaults();
await flush();
const cloudPayload = LLMSettings.payload();
out.cloud = {
    flag: CloudMode.on,
    dataCloud: doc.documentElement.dataset.cloud,
    providers: providerValues(),
    active: LLMSettings.load().provider,
    payloadProvider: cloudPayload.provider,
    /* The key is the other half of the run body: normalising the transport is what makes
       the panel send the credential the chosen transport needs, and only that one. */
    payloadKey: cloudPayload.api_key,
    payloadModel: cloudPayload.model,
    label: llmModeLabel(),
    ollamaRowDisplay: Array.prototype.map.call(doc.querySelectorAll('.ai-only-ollama'), (el) => el.style.display),
};

/* ── the notice: asked once, and 「不再提醒」 means this browser ───────── */
const NOTICE_KEY = 'crawler_privacy_ack';

dialogs.length = 0;
PrivacyNotice.reset();
sandbox.localStorage.setItem(NOTICE_KEY, '1');
CloudMode.set(true);
await flush();
out.ackedBrowser = { dialogs: dialogs.slice(), storage: sandbox.localStorage.getItem(NOTICE_KEY) };

dialogs.length = 0;
PrivacyNotice.reset();
CloudMode.set(true);
await flush();
out.firstVisit = {
    dialogs: dialogs.slice(),
    /* 「知道了」 is the ordinary close: it dismisses this visit and promises nothing about
       the next one. Only 「不再提醒」 writes the ack. */
    afterGotIt: sandbox.localStorage.getItem(NOTICE_KEY),
};

dialogs.length = 0;
PrivacyNotice.reset();
sandbox.__answer = 'never';
CloudMode.set(true);
await flush();
await flush();
out.afterNeverAgain = {
    dialogs: dialogs.slice(),
    stored: sandbox.localStorage.getItem(NOTICE_KEY),
    acked: PrivacyNotice.acked(),
};
/* A second flag landing must not stack a second notice on the same page. */
dialogs.length = 0;
CloudMode.set(true);
await flush();
out.secondLanding = { dialogs: dialogs.slice() };
sandbox.__answer = undefined;

/* ── both languages: the word must not name a transport this host lacks ── */
const labels = {};
for (const lang of ['zh', 'en']) {
    /* The product's own switch (workflow.js), which is also what repaints the chrome:
       asserting on a hand-set `I18n.lang` would skip the part where the page decides
       which dictionary the label is read out of. */
    sandbox.setLang(lang);
    CloudMode.set(true);
    labels[`${lang}_cloud`] = llmModeLabel();
    CloudMode.set(false);
    labels[`${lang}_desktop`] = llmModeLabel();
}
out.labels = labels;

/* A flag that only ever turns a page off has to turn it back on: the same object is what
   a later /api/config answer feeds. */
CloudMode.set(true);
CloudMode.set(false);
out.turnsBack = { flag: CloudMode.on, dataCloud: doc.documentElement.dataset.cloud };

process.stdout.write(JSON.stringify(out));
