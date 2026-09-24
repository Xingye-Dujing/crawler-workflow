/* Runs the REAL cookie panel (backend/static/js/workflow.js) in node.
 *
 * The panel is the only place a user learns *which page to log in on*, and for
 * a few platforms the answer is "the page you paste in", not "the home page".
 * That behaviour lives in JS: fetch the flow, render the steps, carry the
 * pasted entry link into the generate/verify request, and keep the login
 * buttons out of a verification. A Python test cannot see any of it, so this
 * harness loads the untouched file and reports what the panel did.
 *
 * Usage: node harness_cookie.mjs <path/to/workflow.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const wfPath = process.argv[2];
const src = fs.readFileSync(wfPath, 'utf8');

const sandbox = {
    ...baseSandbox(),
    /* I18n.t answers with the KEY: a panel that renders the wrong string is a
       wrong string no matter what language it is in, and the assertions must
       not track translation. */
    I18n: { lang: 'en', t: (k) => k },
    __toasts: [],
    __calls: [],
    __responses: {},
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src, sandbox);

/* workflow.js declares its own fetchJSON, and a function declaration overwrites
   whatever the sandbox held at load time — so the stand-in is installed AFTER
   the file runs. The panel resolves it per call, which is what lets one stub
   route every endpoint. */
sandbox.fetchJSON = (url, opts) => {
    sandbox.__calls.push({ url, opts: opts || null });
    const canned = sandbox.__responses[url];
    let payload = canned === undefined ? { ok: true } : canned;
    /* The status endpoint always sends the per-platform map; a stub that answered it
       without one made the panel crash on a scenario that simply never bothered to
       seed it, and the crash read as a product bug. */
    if (url === '/api/cookies/status' && payload && !payload.cookies) payload = { ...payload, cookies: {} };
    return Promise.resolve(payload);
};
sandbox.showToast = (msg) => {
    sandbox.__toasts.push(msg);
};

const flush = async () => {
    for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
};

const doc = sandbox.document;
/* Two REAL cookie platforms, chosen for the one thing that differentiates them
   in the panel: bilibili accepts a pasted entry link (its cookies are planted
   while sitting on a video page), zhihu does not. WeChat is deliberately absent
   — it has no cookie row, because its article bodies need no session. */
const FLOW_BODY = {
    ok: true,
    flows: [
        {
            platform: 'bilibili',
            purpose: 'PURPOSE-BILIBILI',
            steps: ['STEP-ONE', 'STEP-TWO'],
            login_url: 'https://www.bilibili.com/',
            accepts_custom_url: true,
            allowed_hosts: ['bilibili.com', 'www.bilibili.com'],
        },
        {
            platform: 'zhihu',
            purpose: 'PURPOSE-ZHIHU',
            steps: ['Z-STEP'],
            login_url: 'https://www.zhihu.com/',
            accepts_custom_url: false,
            allowed_hosts: [],
        },
    ],
};

function setPlatform(value) {
    doc.getElementById('cookie-platform').value = value;
}

function report() {
    const guide = doc.getElementById('cookie-guide-body');
    const entry = doc.getElementById('cookie-entry');
    const status = doc.getElementById('cookie-status');
    const actions = doc.getElementById('cookie-job-actions');
    return {
        guideLines: (guide.children || []).map((child) => child.textContent),
        guideText: guide.textContent,
        entryPlaceholder: entry.placeholder,
        entryDisabled: entry.disabled,
        statusText: status.textContent,
        actionsDisplay: actions.style.display || '',
        job: {
            active: sandbox.cookieJob.active,
            kind: sandbox.cookieJob.kind,
            platform: sandbox.cookieJob.platform,
        },
        toasts: sandbox.__toasts.slice(),
        calls: sandbox.__calls.map((call) => ({
            url: call.url,
            body: call.opts && call.opts.body ? JSON.parse(call.opts.body) : null,
        })),
    };
}

const out = {};

/* Every dialog the panel raised, with the values its buttons carry. A dialog WITH an
   input is answered by the real showDialog as `b.value !== undefined ? b.value :
   inputEl.value`, so the shape of the spec is part of what is under test: a 「删除」
   button that shipped a `value:` on an input dialog would replace what the user
   typed. Here it is what tells a refusal from a confirmation. */
const dialogs = [];
sandbox.showDialog = function (spec) {
    dialogs.push({
        message: spec.message,
        labels: (spec.buttons || []).map((b) => b.label),
        values: (spec.buttons || []).map((b) => ('value' in b ? String(b.value) : '<absent>')),
    });
    return Promise.resolve(sandbox.__dialogAnswer);
};

/* ── 1. the guide is fetched once and rendered per selected platform ───── */
out.label = 'cookie panel behaviour';

sandbox.__responses['/api/cookies/flow'] = FLOW_BODY;
setPlatform('bilibili');
sandbox.renderCookieGuide();
await flush();
out.guideBilibiliFirstCall = report();

sandbox.renderCookieGuide();
await flush();
out.guideBilibiliSecondCall = report();

setPlatform('zhihu');
sandbox.renderCookieGuide();
await flush();
out.guideZhihu = report();

/* ── 2. generate carries the pasted entry link, and a rejection is spoken ─ */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
doc.getElementById('cookie-entry').value = 'https://www.bilibili.com/video/BV1xx411c7mD';
doc.getElementById('cookie-wait').value = '45';
sandbox.__responses['/api/cookies/generate'] = {
    ok: true,
    message: 'started',
    entry: 'https://www.bilibili.com/video/BV1xx411c7mD',
    entry_rejected: true,
    entry_note: 'ENTRY-REJECTED',
};
sandbox.__responses['/api/cookies/generate/status'] = { ok: true, active: false, phase: '', kind: 'login' };
setPlatform('bilibili');
sandbox.generateCookie();
await flush();
out.generate = report();

/* ── 3. a verification reports its lines and hides the login buttons ───── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.cookieJob.known = false;
sandbox.__responses['/api/cookies/verify'] = { ok: true, message: 'verifying' };
sandbox.__responses['/api/cookies/generate/status'] = {
    ok: true,
    active: true,
    kind: 'verify',
    platform: 'bilibili',
    phase: 'verifying',
    lines: [],
};
sandbox.verifyCookie();
await flush();
out.verifyRunning = report();

sandbox.__responses['/api/cookies/generate/status'] = {
    ok: true,
    active: false,
    kind: 'verify',
    platform: 'bilibili',
    phase: 'verified',
    // The three keys the generic diagnosis is allowed to produce — a stale one
    // (an old WeChat admin-session field, say) would keep the panel talking
    // about something no code can read.
    facts: { platform: 'bilibili.com', url: 'https://www.bilibili.com/', login_wall: false },
    lines: ['LINE-ONE', 'LINE-TWO'],
};
sandbox.pollCookieJob();
await flush();
out.verifyDone = report();

/* ── 4. a busy verify refuses to look like a login ─────────────────────── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.cookieJob.known = false;
sandbox.__responses['/api/cookies/verify'] = {
    ok: false,
    busy: true,
    platform: 'weibo',
    error: 'BUSY',
};
sandbox.__responses['/api/cookies/generate/status'] = {
    ok: true,
    active: true,
    kind: 'verify',
    platform: 'weibo',
    phase: 'verifying',
};
sandbox.verifyCookie();
await flush();
out.verifyBusy = report();

/* ── 5. reopening the dialog adopts a job already in flight ────────────── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.cookieJob.known = false;
sandbox.__responses['/api/cookies/generate/status'] = {
    ok: true,
    active: true,
    kind: 'verify',
    platform: 'zhihu',
    phase: 'verifying',
};
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: { zhihu: true, bilibili: false } };
doc.getElementById('cookie-dialog').classList.remove('open');
sandbox.openCookieDialog();
await flush();
out.adoptedOnOpen = report();
out.dialogOpen = doc.getElementById('cookie-dialog').classList.contains('open');

/* ── 6. deleting a cookie asks first, and only the confirmation sends anything ─ */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.cookieJob.known = false;
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: { zhihu: false, bilibili: false } };
setPlatform('bilibili');
sandbox.__dialogAnswer = null; // the user closed the confirmation
sandbox.__toasts.length = 0;
let before = sandbox.__calls.length;
await sandbox.deleteCookie();
await flush();
out.deleteCancelled = {
    calls: sandbox.__calls.slice(before).map((call) => call.url),
    toasts: sandbox.__toasts.slice(),
    dialog: dialogs[dialogs.length - 1] || null,
};

before = sandbox.__calls.length;
sandbox.__dialogAnswer = 'delete';
sandbox.__toasts.length = 0;
await sandbox.deleteCookie();
await flush();
out.deleteConfirmed = {
    requests: sandbox.__calls.slice(before).map((call) => ({ url: call.url, body: call.opts && call.opts.body })),
    toasts: sandbox.__toasts.slice(),
    dialog: dialogs[dialogs.length - 1] || null,
};

/* ── 7. a refusal from the server is shown, not swallowed ───────────────── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/delete'] = { ok: false, error: 'NOTHING-STORED' };
before = sandbox.__calls.length;
sandbox.__dialogAnswer = 'delete';
sandbox.__toasts.length = 0;
await sandbox.deleteCookie();
await flush();
out.deleteRefused = {
    posted: sandbox.__calls.slice(before).length,
    statusText: sandbox.document.getElementById('cookie-status').textContent,
    toasts: sandbox.__toasts.slice(),
};

/* ── 8. the profile caveat travels from the server's answer to the screen ── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/delete'] = {
    ok: true,
    message: 'Cookies deleted for zhihu\nNote: zhihu’s browser profile stays logged in',
    profile_holds: true,
};
before = sandbox.__calls.length;
sandbox.__dialogAnswer = 'delete';
sandbox.__toasts.length = 0;
setPlatform('zhihu');
await sandbox.deleteCookie();
await flush();
out.deleteWithCaveat = {
    askedPlatforms: sandbox.__calls
        .slice(before)
        .filter((call) => call.opts && call.opts.body)
        .map((call) => JSON.parse(call.opts.body).platform),
    statusText: sandbox.document.getElementById('cookie-status').textContent,
    toasts: sandbox.__toasts.slice(),
};

/* ── 7. the saved-cookie line speaks the interface language ───────────────
   It used to print `zhihu: OK` / `weibo: -`, which stayed English in a Chinese
   interface and named nothing the user could read. Because this stub's `t()`
   answers with the KEY, the assertion is about where the words come from — the
   catalog — not about any particular translation. */
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: { zhihu: true, weibo: false } };
sandbox.refreshCookieStatus();
await flush();
out.savedStatus = doc.getElementById('cookie-status').textContent;

process.stdout.write(JSON.stringify(out));
