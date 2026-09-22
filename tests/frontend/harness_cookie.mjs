/* Runs the REAL cookie panel (backend/static/js/workflow.js) in node.
 *
 * The panel is the only place a user learns *which page to log in on* — the
 * thing that made WeChat unusable (its two capabilities need two different
 * links). That behaviour lives in JS: fetch the flow, render the steps, carry
 * the pasted entry link into the generate/verify request, and keep the login
 * buttons out of a verification. A Python test cannot see any of it, so this
 * harness loads the untouched file and reports what the panel did.
 *
 * Usage: node harness_cookie.mjs <path/to/workflow.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox } from './harness_dom.mjs';

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
vm.runInContext(src, sandbox);

/* workflow.js declares its own fetchJSON, and a function declaration overwrites
   whatever the sandbox held at load time — so the stand-in is installed AFTER
   the file runs. The panel resolves it per call, which is what lets one stub
   route every endpoint. */
sandbox.fetchJSON = (url, opts) => {
    sandbox.__calls.push({ url, opts: opts || null });
    const canned = sandbox.__responses[url];
    return Promise.resolve(canned === undefined ? { ok: true } : canned);
};
sandbox.showToast = (msg) => {
    sandbox.__toasts.push(msg);
};

const flush = async () => {
    for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
};

const doc = sandbox.document;
const FLOW_BODY = {
    ok: true,
    flows: [
        {
            platform: 'wechat',
            purpose: 'PURPOSE-WECHAT',
            steps: ['STEP-ONE', 'STEP-TWO'],
            login_url: 'https://mp.weixin.qq.com/',
            accepts_custom_url: true,
            allowed_hosts: ['mp.weixin.qq.com'],
            multi_purpose: true,
        },
        {
            platform: 'zhihu',
            purpose: 'PURPOSE-ZHIHU',
            steps: ['Z-STEP'],
            login_url: 'https://www.zhihu.com/',
            accepts_custom_url: false,
            allowed_hosts: [],
            multi_purpose: false,
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

/* ── 1. the guide is fetched once and rendered per selected platform ───── */
out.label = 'cookie panel behaviour';

sandbox.__responses['/api/cookies/flow'] = FLOW_BODY;
setPlatform('wechat');
sandbox.renderCookieGuide();
await flush();
out.guideWechatFirstCall = report();

sandbox.renderCookieGuide();
await flush();
out.guideWechatSecondCall = report();

setPlatform('zhihu');
sandbox.renderCookieGuide();
await flush();
out.guideZhihu = report();

/* ── 2. generate carries the pasted entry link, and a rejection is spoken ─ */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
doc.getElementById('cookie-entry').value = 'https://mp.weixin.qq.com/s?pass_ticket=P#rd';
doc.getElementById('cookie-wait').value = '45';
sandbox.__responses['/api/cookies/generate'] = {
    ok: true,
    message: 'started',
    entry: 'https://mp.weixin.qq.com/s?pass_ticket=P#rd',
    entry_rejected: true,
    entry_note: 'ENTRY-REJECTED',
};
sandbox.__responses['/api/cookies/generate/status'] = { ok: true, active: false, phase: '', kind: 'login' };
setPlatform('wechat');
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
    platform: 'wechat',
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
    platform: 'wechat',
    phase: 'verified',
    facts: { mp_logged_in: true },
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
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: { zhihu: true, wechat: false } };
doc.getElementById('cookie-dialog').classList.remove('open');
sandbox.openCookieDialog();
await flush();
out.adoptedOnOpen = report();
out.dialogOpen = doc.getElementById('cookie-dialog').classList.contains('open');

process.stdout.write(JSON.stringify(out));
