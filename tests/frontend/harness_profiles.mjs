/* Runs the REAL browser-profile UI (workflow.js + app.js) under node.

What is being driven is the part no Python test can reach and the part this project
has been burned by twice:

* the pre-run gate. A profile decision lives in `Settings.use_browser_profile`, the
  suggestion lives in the crawl matrix, and the canvas decides which platforms are in
  play. Read through `window.X` it would never fire (a top-level `const` is not a
  window property — the bug that kept the 断点续跑 banner hidden for a release), and
  read from the wrong source it would nag about platforms the run does not touch;
* the settings panel's profile table, which has to render one row per platform, in
  the right state, from a server payload — and survive the payload not arriving.

Every scenario runs in a fresh sandbox: `Capabilities` and `AppSettings` cache what
they fetched, so a shared world would answer every case with the first payload it saw.

Usage: node harness_profiles.mjs <jsDir> <scenarios.json>
scenarios.json = [ { id, matrix, settings, nodes, profiles, choice, openSettings } ]
Prints {id: {notice, dialog, result, openedSettings, rows, kinds, box, panelHint}}.
*/
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const jsDir = process.argv[2];
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const FILES = ['custom-select.js', 'canvas.js', 'workflow.js', 'app.js'];

function world(sc) {
    const sandbox = { ...baseSandbox(), console: { log: () => {}, warn: () => {}, error: () => {} } };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    const routes = sandbox.__routes;
    routes['/api/settings'] = { ok: true, settings: sc.settings || {} };
    routes['/api/browser/profiles'] = sc.profiles === 'throw' ? { nonsense: 1 } : sc.profiles;
    if (sc.matrix) routes['/api/capabilities'] = sc.matrix;
    for (const f of FILES) {
        vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f });
    }
    sandbox.__dialog = null;
    vm.runInContext(
        `showDialog = function (options) {
            globalThis.__dialog = { message: options.message, labels: (options.buttons || []).map(function (b) { return b.label; }) };
            return Promise.resolve(${JSON.stringify(sc.choice === undefined ? 'go' : sc.choice)});
        };
        globalThis.__settingsOpened = 0;
        toggleSettingsMenu = function () { globalThis.__settingsOpened += 1; };`,
        sandbox
    );
    /* Assigned after the load: workflow.js declares showToast itself, and a function
       declaration inside the script wins over anything seeded before it. Without
       this a refused run would report as a missing POST with no reason attached. */
    sandbox.__toasts = [];
    sandbox.showToast = (msg) => sandbox.__toasts.push(String(msg));
    return sandbox;
}

const report = {};
for (const sc of scenarios) {
    const sandbox = world(sc);
    const entry = {};
    /* The page loads the matrix and the settings at startup (app.js does both);
       a harness that skips that would test a page where Capabilities never answers,
       and the panel's "no matrix yet" branch would be the only thing on screen. */
    await vm.runInContext(`Capabilities.load()`, sandbox);
    await vm.runInContext(`AppSettings.pull(true)`, sandbox);
    /* The settings panel's containers exist in index.html, which this harness does
       not parse — so the ids the app looks up have to be registered, or
       `getElementById` honestly returns null and the code under test exits early. */
    sandbox.__byId('profile-status');
    sandbox.__byId('settings-content');
    sandbox.__byId('settings-menu');
    sandbox.__byId('btn-settings');
    /* 1. the pure decision, over the real canvas node map. `canvas` is a top-level
       const, so it is reachable only from inside the context — assigning it from the
       host would be undefined and every scenario would "pass" by testing nothing. */
    vm.runInContext(`canvas.nodes = ${JSON.stringify(sc.nodes || {})};`, sandbox);
    entry.notice = vm.runInContext(
        `profileNoticeCount(canvas.nodes, (window.AppSettings && AppSettings._values) || {}, Capabilities.data)`,
        sandbox
    );
    /* 2. the gate itself, through AppSettings.pull (a real fetch of the real route) */
    entry.proceed = await vm.runInContext(`workflow._confirmProfileBeforeRun()`, sandbox);
    entry.result = sandbox.__dialog;
    entry.shown = sandbox.__dialog !== null;
    entry.openedSettings = vm.runInContext(`globalThis.__settingsOpened`, sandbox);
    /* The settings table, read the way the DOM builds it: each row is a name, an
       optional 建议 chip and a state — separate elements, so a long platform name
       can wrap instead of pushing the menu sideways. */
    await vm.runInContext(`renderBrowserProfiles()`, sandbox);
    const box = sandbox.__byId('profile-status');
    const cells = (item) => {
        const out = {};
        (item.children || []).forEach((child) => {
            for (const cls of child.classList) {
                if (cls !== 'profile-name' && cls !== 'profile-state' && cls !== 'profile-chip') continue;
                out[cls] = child.textContent;
            }
        });
        return out;
    };
    entry.rows = box.children.map((child) => {
        const found = cells(child);
        return {
            name: found['profile-name'] || '',
            chip: found['profile-chip'] || '',
            state: found['profile-state'] || '',
            kind: (child.dataset && child.dataset.kind) || '',
        };
    });
    /* 3b. the wiring the user actually exercises: opening 设置 is what reads the
       table now (a page load must not pay for a panel nobody opens). */
    box.textContent = '';
    vm.runInContext(`toggleSettingsMenu();`, sandbox);
    await vm.runInContext(`Promise.resolve().then(() => BrowserProfiles.refresh())`, sandbox);
    entry.rowsAfterOpen = box.children.length;
    /* 4. the data-source panel hint, in the same world as the real matrix */
    if (sc.matrix && sc.hintPlatform) {
        vm.runInContext(
            `canvas.nodes.hint_node = { id: 'hint_node', type: 'source', title: 't', params: { platform: ${JSON.stringify(
                sc.hintPlatform
            )}, keyword: 'x', collect: 'posts' }, el: null };
             globalThis.openSettings('hint_node');`,
            sandbox
        );
        entry.panelHint = sandbox.__byId('settings-content').innerHTML;
    }
    /* 5. the parallel/same-platform fork: what the canvas says collides, whether the
       user was asked, and what the request body then carries. */
    vm.runInContext(
        `canvas.connections = ${JSON.stringify(sc.connections || [])};
         canvas.settings = ${JSON.stringify(sc.canvasSettings || { mode: 'parallel' })};
         canvas.toWorkflowJSON = function () {
             return { nodes: Object.values(canvas.nodes), connections: canvas.connections, settings: canvas.settings };
         };`,
        sandbox
    );
    entry.collisions = vm.runInContext(`profileCollisions(canvas.nodes, canvas.connections)`, sandbox);
    /* The answer to the fork has to be installed BEFORE the gate is called: a stub
       still answering the previous scenario's choice would report the wrong branch,
       and `undefined` (the user closed the dialog) simply vanishes through
       JSON.stringify — so the sentinel is named here rather than left implicit. */
    sandbox.__dialog = null;
    vm.runInContext(
        `showDialog = function (options) {
            globalThis.__dialog = { message: options.message, labels: (options.buttons || []).map(function (b) { return b.label; }) };
            return Promise.resolve(${JSON.stringify(sc.clashChoice === undefined ? null : sc.clashChoice)});
        };`,
        sandbox
    );
    const answered = await vm.runInContext(`workflow._confirmProfileChoiceBeforeRun()`, sandbox);
    /* Three distinct outcomes, and the JSON has to tell them apart:
       'not-asked' (null — nothing to decide), 'cancelled' (undefined — the user
       closed it, so the run must not start), true / false (their answer). */
    entry.clash = answered === undefined ? 'cancelled' : answered === null ? 'not-asked' : answered;
    entry.clashDialog = sandbox.__dialog;
    const posts = [];
    sandbox.fetch = (url, opts) => {
        posts.push({ url: String(url), body: opts && opts.body ? String(opts.body) : null });
        const path = String(url).split('?')[0];
        const payload =
            path === '/api/cookies/status'
                ? { ok: true, cookies: { bilibili: true, zhihu: true, weibo: true } }
                : path === '/api/workflow/execute'
                    ? { ok: true, run_id: 'r1' }
                    : { ok: true, settings: {} };
        return Promise.resolve({ ok: true, json: () => Promise.resolve(payload), text: () => Promise.resolve('x') });
    };
    vm.runInContext(
        `workflow.pollStatus = function () {};
         RunState.running = false;
         makeDraggable = function () {};`,
        sandbox
    );
    await vm.runInContext(`workflow.execute({})`, sandbox);
    const executed = posts.find((p) => p.url.indexOf('/api/workflow/execute') === 0);
    entry.ran = Boolean(executed);
    /* Named, not left implicit: an absent key and a key whose value is undefined
       arrive at Python identically, and "no settings field" is a different fact from
       "the field says true". */
    entry.sentProfile = executed ? String(JSON.parse(executed.body).workflow.settings.use_profile) : 'no-request';
    entry.runToasts = sandbox.__toasts.slice();
    report[sc.id] = entry;
}

process.stdout.write(JSON.stringify(report));
