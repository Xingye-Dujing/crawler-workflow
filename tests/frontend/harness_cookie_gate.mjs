/* Runs the REAL pre-run Cookie gate (workflow.js) under node.
 *
 * What is under test is the stretch of one button press between "this canvas is
 * valid" and "the run started": does the Cookie of every platform this run crawls
 * still work, and what does the page do with the answer. Two settings choose the
 * branch (执行前自动验证 / 执行前确认), and every interesting failure here is
 * invisible to Python: a gate that asks about platforms the canvas never touches,
 * a 「无法核对」 treated as a dead cookie (which would refuse runs about to
 * succeed), a refusal that posts the run anyway, a block dialog that quietly
 * offers 「我确定，照样跑」 — the whole point of the feature is that it does not.
 *
 * Each scenario gets a fresh world: AppSettings and Capabilities cache what they
 * fetched, so a shared sandbox would answer every case with the first payload it
 * saw, and "the setting was off" would be indistinguishable from "it was never read".
 *
 * Usage: node harness_cookie_gate.mjs <jsDir> <scenarios.json>
 * scenario = { id, settings, nodes, connections, canvasSettings, preflight,
 *              preflightThrows, dialogChoice, opts, matrix, clashChoice, panelOpen }
 * Prints {id: {asked, askedBody, ran, dialogLabels, dialogMessage, toasts,
 *              cookiePlatform, cookiePanelOpen, sentProfile}}
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const jsDir = process.argv[2];
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const FILES = ['custom-select.js', 'canvas.js', 'workflow.js', 'app.js'];

const ALL_COOKIES = {
    ok: true,
    cookies: {
        zhihu: true,
        weibo: true,
        xiaohongshu: true,
        bilibili: true,
        douyin: true,
        twitter: true,
        instagram: true,
        youtube: true,
    },
};
const CLEAN = { ok: true, results: {}, blocked: [], unclear: [], probed: true };

function world(sc) {
    const sandbox = { ...baseSandbox(), console: { log: () => {}, warn: () => {}, error: () => {} } };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    const routes = sandbox.__routes;
    routes['/api/settings'] = { ok: true, settings: sc.settings || {} };
    routes['/api/cookies/status'] = ALL_COOKIES;
    routes['/api/cookies/flow'] = { ok: true, flows: [] };
    routes['/api/cookies/generate/status'] = { ok: true, active: false };
    routes['/api/workflow/execute'] = { ok: true, run_id: 'r1' };
    routes['/api/cookies/preflight'] = sc.preflight === undefined ? CLEAN : sc.preflight;
    if (sc.matrix) routes['/api/capabilities'] = sc.matrix;
    for (const file of FILES) {
        vm.runInContext(fs.readFileSync(path.join(jsDir, file), 'utf8'), sandbox, { filename: file });
    }
    /* Declared after the load: workflow.js declares `fetchJSON` and `showToast`
       itself, and a function declaration in the script wins over anything seeded
       before it — which is how a refused run used to report as a missing POST with
       no reason attached. */
    const posts = [];
    sandbox.fetch = (url, opts) => {
        const route = String(url).split('?')[0];
        posts.push({ url: route, body: opts && opts.body ? String(opts.body) : null });
        if (route === '/api/cookies/preflight' && sc.preflightThrows) {
            return Promise.reject(new Error('network is down'));
        }
        const hit = Object.keys(routes).filter((frag) => route.indexOf(frag) >= 0)[0];
        const payload = hit ? routes[hit] : { ok: true };
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve(payload),
            text: () => Promise.resolve(JSON.stringify(payload)),
        });
    };
    sandbox.__posts = posts;
    sandbox.__toasts = [];
    sandbox.showToast = (msg) => sandbox.__toasts.push(String(msg));
    sandbox.__dialogs = [];
    /* One press can raise several dialogs in a row (the profile fork, then the
       Cookie block), and each has its own answer. They are told apart by the values
       their buttons carry — a real property of the spec, not a guess about wording
       that a translation could move. */
    vm.runInContext(
        `showDialog = function (options) {
            var buttons = options.buttons || [];
            var values = buttons.map(function (b) { return ('value' in b) ? String(b.value) : '<absent>'; });
            var labels = buttons.map(function (b) { return b.label; });
            globalThis.__dialogs.push({ message: options.message, labels: labels, values: values });
            var kind = null;
            if (values.indexOf('use') >= 0 && values.indexOf('skip') >= 0) kind = 'clash';
            else if (values.indexOf('update') >= 0) kind = 'expired';
            /* Both remaining dialogs offer 继续, so the *other* button is what tells
               them apart — 「退出更新 Cookie」 only exists on the cookie prompt. */
            else if (values.indexOf('go') >= 0 && values.indexOf('exit') >= 0) kind = 'confirm';
            else if (values.indexOf('go') >= 0) kind = 'mixed';
            var answers = ${JSON.stringify(sc.answers || {})};
            return Promise.resolve(kind in answers ? answers[kind] : ${JSON.stringify(
                sc.dialogChoice === undefined ? 'go' : sc.dialogChoice
            )});
        };`,
        sandbox
    );
    /* The Cookie panel's own containers live in index.html, which this harness does
       not parse, so the ids have to be registered — and registered honestly: the
       platform selector is a <select> with the real option list, because the block
       dialog is supposed to land the user on the platform that is broken. */
    const platform = sandbox.__byId('cookie-platform');
    platform.options = ['zhihu', 'weibo', 'bilibili'].map((value) => ({ value }));
    platform.value = 'bilibili';
    sandbox.__byId('cookie-dialog');
    sandbox.__byId('cookie-status');
    sandbox.__byId('cookie-guide-body');
    if (sc.panelOpen) vm.runInContext('document.getElementById("cookie-dialog").classList.add("open")', sandbox);
    return sandbox;
}

const report = {};
for (const sc of scenarios) {
    const sandbox = world(sc);
    const entry = {};
    await vm.runInContext('Capabilities.load()', sandbox);
    await vm.runInContext('AppSettings.pull(true)', sandbox);
    vm.runInContext(
        `canvas.nodes = ${JSON.stringify(sc.nodes || {})};
         canvas.connections = ${JSON.stringify(sc.connections || [])};
         canvas.settings = ${JSON.stringify(sc.canvasSettings || { mode: 'serial' })};
         canvas.toWorkflowJSON = function () {
             return { nodes: Object.values(canvas.nodes), connections: canvas.connections, settings: canvas.settings };
         };
         workflow.pollStatus = function () {};
         RunState.running = false;`,
        sandbox
    );
    const before = sandbox.__posts.length;
    await vm.runInContext(`workflow.execute(${JSON.stringify(sc.opts || {})})`, sandbox);
    const posts = sandbox.__posts.slice(before);
    const asked = posts.find((post) => post.url === '/api/cookies/preflight');
    const executed = posts.find((post) => post.url === '/api/workflow/execute');
    entry.asked = Boolean(asked);
    entry.askedBody = asked && asked.body ? JSON.parse(asked.body) : null;
    entry.ran = Boolean(executed);
    entry.sentProfile = executed && executed.body ? String(JSON.parse(executed.body).workflow.settings.use_profile) : 'no-request';
    entry.dialogs = sandbox.__dialogs.slice();
    entry.toasts = sandbox.__toasts.slice();
    /* Read back from inside the vm, not off the host object: `fixWindow` gives the
       context its own view of `document`, and a host-side handle to an element is a
       different object from what `getElementById` returns in there — which is how a
       panel that had switched platforms read as one that never did. */
    entry.cookiePlatform = vm.runInContext('document.getElementById("cookie-platform").value', sandbox);
    entry.cookiePanelOpen = vm.runInContext('document.getElementById("cookie-dialog").classList.contains("open")', sandbox);
    report[sc.id] = entry;
}

process.stdout.write(JSON.stringify(report));
