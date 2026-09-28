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

import { addOptions, baseSandbox, fixWindow } from './harness_dom.mjs';

const wfPath = process.argv[2];
const src = fs.readFileSync(wfPath, 'utf8');

const sandbox = {
    ...baseSandbox(),
    /* I18n.t answers with the KEY, plus the values it was handed: a panel that renders the
       wrong string is wrong in any language, and the assertions must not track translation.
       It used to drop the arguments entirely — so every placeholder bug was invisible here,
       including the delete dialog that shipped a literal {platform} while these tests passed
       on the bare key. Slots are filled the way the real formatter fills them: all of them. */
    I18n: {
        lang: 'en',
        t: (k, vars) => {
            const names = Object.keys(vars || {});
            if (!names.length) return String(k);
            return String(k) + ' - ' + names.map((name) => String(vars[name])).join(' | ');
        },
    },
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

/* ── 9. saving a cookie IS the plant: no second button, no second request ──────
   The paste is the newest session there is, so the browser that crawls with this
   account has to receive it without the user having to notice anything — and the one
   case that cannot happen on the spot (that profile is held by a running crawl) has to
   be VISIBLE, because a bare 「已保存」 would hide exactly the half the user acts on. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
setPlatform('weibo');
sandbox.__byId('cookie-account').value = 'work';
sandbox.__byId('cookie-json').value = JSON.stringify([{ name: 'SUB', value: 'v', domain: '.weibo.com' }]);
sandbox.__responses['/api/cookies/save'] = {
    ok: true,
    message: 'SAVED\nDEFERRED-PROFILE',
    count: 1,
    profile_note: 'DEFERRED-PROFILE',
};
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: {}, accounts: { weibo: ['work'] } };
sandbox.__toasts.length = 0;
before = sandbox.__calls.length;
sandbox.saveCookieConfig();
await flush();
out.savePlants = {
    urls: sandbox.__calls.slice(before).map((call) => call.url),
    saveBody: sandbox.__calls
        .slice(before)
        .filter((call) => call.url === '/api/cookies/save' && call.opts && call.opts.body)
        .map((call) => JSON.parse(call.opts.body)),
    statusText: doc.getElementById('cookie-status').textContent,
    toasts: sandbox.__toasts.slice(),
};

/* ── 10. a refusal is shown as the server worded it ─────────────────────────── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/save'] = { ok: false, error: 'BAD-JSON' };
sandbox.__toasts.length = 0;
sandbox.__byId('cookie-json').value = JSON.stringify([{ name: 'SUB', value: 'v', domain: '.weibo.com' }]);
sandbox.saveCookieConfig();
await flush();
out.saveRefused = { toasts: sandbox.__toasts.slice() };

/* ── 11. the panel says "your file is newer than the profile" only when the
   server measured that ───────────────────────────────────────────────────
   The hint is the whole reason the button is findable, and a browser-side guess
   about which cookie file a Chrome profile was planted from is not knowable —
   so the row comes from /api/browser/profiles and nothing else. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieFlows = null;
sandbox.cookieProfilesLoaded = false;
sandbox.cookieProfiles = {};
sandbox.__responses['/api/cookies/flow'] = {
    ok: true,
    flows: [{ platform: 'weibo', purpose: 'PURPOSE', steps: ['STEP-1'], accepts_custom_url: true, login_url: 'https://weibo.com' }],
};
sandbox.__responses['/api/browser/profiles'] = {
    ok: true,
    profiles: [{ platform: 'weibo', needs_refresh: true }],
};
setPlatform('weibo');
sandbox.renderCookieGuide();
await flush();
await flush();
out.hintWhenStale = (doc.getElementById('cookie-guide-body').children || []).map((row) => row.textContent);

sandbox.cookieProfilesLoaded = false;
sandbox.__responses['/api/browser/profiles'] = {
    ok: true,
    profiles: [{ platform: 'weibo', needs_refresh: false }],
};
sandbox.renderCookieGuide();
await flush();
await flush();
out.hintWhenCurrent = (doc.getElementById('cookie-guide-body').children || []).map((row) => row.textContent);

/* ── the typed account rides every request; a blank box is the default account ──
   One platform can now hold several logins, so WHICH file the login browser writes is
   decided by the account box. A name typed in mixed case has to reach the backend
   lowercased (the filename rule is lowercase), and the empty box is the historical
   default account — a missing key would read as "not sent" rather than "default". */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.cookieJob.known = false;
sandbox.__calls.length = 0;
doc.getElementById('cookie-account').value = 'Work';
sandbox.__responses['/api/cookies/generate'] = { ok: true, message: 'started' };
sandbox.__responses['/api/cookies/generate/status'] = { ok: true, active: false, phase: '', kind: 'login' };
setPlatform('weibo');
sandbox.generateCookie();
await flush();
out.account = report();

/* ── the account candidates, the line that follows the box, the saved-login cards ──
   One platform holds several logins, so the panel has to SAY which ones exist (in the
   words the user reads — 默认账号, not an empty row), answer for the account currently in
   the box without refetching the world, and offer a delete that removes the row it was
   clicked on rather than whatever happens to be typed. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.cookieJob.known = false;
sandbox.__calls.length = 0;
sandbox.__toasts.length = 0;
const ACCOUNT_ROWS = [
    {
        platform: 'zhihu',
        account: '',
        label_key: 'cookies.accountDefault',
        label_args: {},
        entries: 12,
        session_only: 0,
        saved_at: '2026-09-28 10:00',
        profiles_on: true,
        profile_exists: true,
        profile_used: true,
        profile_imported: true,
        needs_refresh: false,
    },
    {
        platform: 'zhihu',
        account: 'default2',
        label_key: 'cookies.accountDefaultNumbered',
        label_args: { n: 2 },
        entries: 4,
        session_only: 3,
        saved_at: '2026-09-27 08:00',
        profiles_on: true,
        profile_exists: true,
        profile_used: true,
        profile_imported: true,
        needs_refresh: true,
    },
    {
        platform: 'zhihu',
        account: 'work',
        label_key: '',
        label_args: {},
        entries: 2,
        session_only: 2,
        saved_at: '',
        profiles_on: true,
        profile_exists: false,
        profile_used: false,
        profile_imported: false,
        needs_refresh: false,
    },
];
const STATUS_ROWS = {
    ok: true,
    cookies: { zhihu: true, weibo: false },
    accounts: { zhihu: ['', 'default2', 'work'], weibo: [] },
    rows: ACCOUNT_ROWS,
};
sandbox.__responses['/api/cookies/status'] = STATUS_ROWS;
setPlatform('zhihu');
doc.getElementById('cookie-account').value = '';
sandbox.refreshCookieStatus();
await flush();

const chips = () =>
    (doc.getElementById('cookie-account-candidates').children || []).map((child) => ({
        text: child.textContent,
        onclick: child.getAttribute('onclick'),
    }));
/* The cards are reported as the markup string they were handed: the shared stub parses a
   flat child list (which is why the chips above can be read as elements), and the card is
   a nested block. The string is also what the browser receives, so this is the level at
   which the escaping it is worth pinning lives. */
const managerHtml = () => String(doc.getElementById('cookie-manager').innerHTML || '');
const accountLine = () => doc.getElementById('cookie-account-status').textContent;

out.candidates = chips();
out.summaryLine = doc.getElementById('cookie-status').textContent;
out.lineForDefault = accountLine();
out.managerHtml = managerHtml();

/* The box is the subject: typing a name the machine does not have must change the answer
   WITHOUT another request (the rows are already cached), and typing one it does have must
   change it back. */
doc.getElementById('cookie-account').value = 'ghost';
sandbox.renderCookieAccountStatus();
out.lineForGhost = accountLine();
doc.getElementById('cookie-account').value = 'WORK';
sandbox.renderCookieAccountStatus();
out.lineForWork = accountLine();
out.rowsAskedAgain = sandbox.__calls.filter((c) => c.url === '/api/cookies/status').length;

/* A candidate click fills the BOX, not just the line — every action below sends what the
   box holds, so a chip that only repainted would save under another account. */
sandbox.pickCookieAccount('default2');
out.afterPick = {
    box: doc.getElementById('cookie-account').value,
    line: accountLine(),
    profileWord: managerHtml().includes('cookies.profileStale'),
};

/* A row's delete names its OWN login. The box says default2 now; clicking the card for
   `work` must post `work`. */
sandbox.__responses['/api/cookies/delete'] = { ok: true, message: 'gone', profile_holds: false };
sandbox.__dialogAnswer = 'delete';
sandbox.__calls.length = 0;
sandbox.deleteCookie('zhihu', 'work');
await flush();
out.rowDelete = {
    posted: sandbox.__calls
        .filter((c) => c.url === '/api/cookies/delete')
        .map((c) => JSON.parse(c.opts.body)),
    boxStill: doc.getElementById('cookie-account').value,
};

/* Nothing saved: no candidates, and the manager says so rather than showing a table of
   nothing. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: {}, accounts: {}, rows: [] };
sandbox.refreshCookieStatus();
await flush();
out.nothingSaved = {
    chips: chips(),
    manager: managerHtml(),
    line: accountLine(),
};

/* ── being sent here by the pre-run block lands on the BROKEN login ───────
   One platform holds several accounts, so naming the platform alone left the box on
   whoever was last typed — and the user was asked to fix a login they were not looking
   at. The account arrives only when the caller names one: the toolbar button takes no
   argument and must not wipe the box. */
/* The real <select> carries one option per cookie platform, and both
   ``openCookieDialog`` and ``useCookieAccount`` refuse to name a platform that is not on
   it. The stub has no option collection of its own, so the two platforms this harness
   speaks are given to it here — otherwise the guard below would be measuring a select
   that could never match anything. */
/* The real <select> carries one option per cookie platform, and both
   ``openCookieDialog`` and ``useCookieAccount`` refuse to name a platform that is not on
   it. The stub derives ``.options`` from real <option> children, so the platforms this
   harness speaks are BUILT here rather than assigned — an assigned list would let the
   guard pass while nothing on the page resembled a select. */
addOptions(doc, doc.getElementById('cookie-platform'), ['zhihu', 'weibo']);
doc.getElementById('cookie-account').value = 'keepme';
sandbox.openCookieDialog('weibo', 'work');
await flush();
out.openedOnAccount = {
    platform: doc.getElementById('cookie-platform').value,
    box: doc.getElementById('cookie-account').value,
};
doc.getElementById('cookie-account').value = 'keepme';
sandbox.openCookieDialog('weibo');
await flush();
out.openedWithoutAccount = {
    platform: doc.getElementById('cookie-platform').value,
    box: doc.getElementById('cookie-account').value,
};
/* A platform that is not on the panel is not selected, and its account is not written
   either: half a landing is worse than none, because the box would then name a login on a
   platform the panel is not showing. */
doc.getElementById('cookie-account').value = 'keepme';
sandbox.openCookieDialog('youtube', 'work');
await flush();
out.openedOnUnknownPlatform = {
    platform: doc.getElementById('cookie-platform').value,
    box: doc.getElementById('cookie-account').value,
};

/* The profile word is chosen from the MARKER, not from whether the path exists: a named
   device lives inside the platform directory, so the default account's path exists as soon
   as any sibling was opened. These five shapes are every answer the panel can print. */
out.profileWords = {
    off: sandbox.cookieProfileWord({ profiles_on: false, profile_exists: true, profile_used: true, profile_imported: true, needs_refresh: false }),
    neverOpened: sandbox.cookieProfileWord({ profiles_on: true, profile_exists: false, profile_used: false, profile_imported: false, needs_refresh: false }),
    // The trap: a directory that exists only because a sibling account was built inside it.
    existsButUnused: sandbox.cookieProfileWord({ profiles_on: true, profile_exists: true, profile_used: false, profile_imported: false, needs_refresh: false }),
    openedNoLogin: sandbox.cookieProfileWord({ profiles_on: true, profile_exists: true, profile_used: true, profile_imported: false, needs_refresh: false }),
    stale: sandbox.cookieProfileWord({ profiles_on: true, profile_exists: true, profile_used: true, profile_imported: true, needs_refresh: true }),
    current: sandbox.cookieProfileWord({ profiles_on: true, profile_exists: true, profile_used: true, profile_imported: true, needs_refresh: false }),
};

process.stdout.write(JSON.stringify(out));
