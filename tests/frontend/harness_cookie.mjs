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
/* Capabilities.load() reaches the server through the NATIVE fetch, not fetchJSON — and the
   data-source node's account box reads its candidate list ONLY from /api/capabilities (the
   backend rebuilds those options from the on-disk accounts at send time). A cookie mutation
   must re-read that endpoint (refreshAccountCandidates) so a new/renamed/deleted login shows
   up without a page reload. Recording the native fetch here is what proves it fired. */
sandbox.__fetches = [];
sandbox.fetch = (url) => {
    sandbox.__fetches.push(url);
    const body =
        sandbox.__responses[url] !== undefined ? sandbox.__responses[url] : { platforms: [{ platform: 'weibo', modes: [] }] };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
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
const beforeFetchCancel = sandbox.__fetches.length;
await sandbox.deleteCookie();
await flush();
out.deleteCancelled = {
    calls: sandbox.__calls.slice(before).map((call) => call.url),
    toasts: sandbox.__toasts.slice(),
    dialog: dialogs[dialogs.length - 1] || null,
    // A cancelled confirmation changes nothing, so it must NOT re-read the account list.
    capabilitiesRefetched: sandbox.__fetches.slice(beforeFetchCancel).includes('/api/capabilities'),
};

before = sandbox.__calls.length;
const beforeFetchDel = sandbox.__fetches.length;
sandbox.__dialogAnswer = 'delete';
sandbox.__toasts.length = 0;
await sandbox.deleteCookie();
await flush();
out.deleteConfirmed = {
    requests: sandbox.__calls.slice(before).map((call) => ({ url: call.url, body: call.opts && call.opts.body })),
    toasts: sandbox.__toasts.slice(),
    dialog: dialogs[dialogs.length - 1] || null,
    // A login really went away, so the data-source node's account box must be re-read.
    capabilitiesRefetched: sandbox.__fetches.slice(beforeFetchDel).includes('/api/capabilities'),
};

/* ── 6b. the dialog's 「删除已存 Profile」 speaks for its OWN selection ─────── */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.cookieJob.active = false;
sandbox.__toasts.length = 0;
setPlatform('zhihu');
sandbox.__byId('cookie-account').value = 'work';
sandbox.__responses['/api/profiles/delete'] = { ok: true, message: 'PROFILE-DELETED' };
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: {}, accounts: {}, rows: [] };
sandbox.__dialogAnswer = 'delete';
before = sandbox.__calls.length;
await sandbox.deleteCookieProfile();
await flush();
out.dialogProfileDelete = {
    posted: sandbox.__calls
        .slice(before)
        .filter((call) => call.url === '/api/profiles/delete')
        .map((call) => JSON.parse(call.opts.body)),
    toasts: sandbox.__toasts.slice(),
    statusFetched: sandbox.__calls.slice(before).some((call) => call.url === '/api/cookies/status'),
};

/* The same button refuses 默认账号 (its dir is the platform root): no dialog, no request. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__toasts.length = 0;
setPlatform('zhihu');
sandbox.__byId('cookie-account').value = '';
sandbox.__dialogAnswer = 'delete';
before = sandbox.__calls.length;
await sandbox.deleteCookieProfile();
await flush();
out.dialogProfileDeleteDefault = {
    posted: sandbox.__calls.slice(before).filter((call) => call.url === '/api/profiles/delete').length,
    toasts: sandbox.__toasts.slice(),
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
sandbox.__responses['/api/cookies/status'] = {
    ok: true,
    cookies: { weibo: true },
    accounts: { weibo: ['work'] },
    rows: [{ platform: 'weibo', account: 'work', entries: 21, saved_at: '2026-10-10 12:00', label_key: null, label_args: null }],
};
sandbox.__toasts.length = 0;
before = sandbox.__calls.length;
const beforeFetchSave = sandbox.__fetches.length;
sandbox.saveCookieConfig();
await flush();
out.savePlants = {
    urls: sandbox.__calls.slice(before).map((call) => call.url),
    saveBody: sandbox.__calls
        .slice(before)
        .filter((call) => call.url === '/api/cookies/save' && call.opts && call.opts.body)
        .map((call) => JSON.parse(call.opts.body)),
    statusText: doc.getElementById('cookie-status').textContent,
    accountLine: doc.getElementById('cookie-account-status').textContent,
    toasts: sandbox.__toasts.slice(),
    // Even when the profile plant is deferred, the login is on disk now — the account box
    // must offer it without a reload, so /api/capabilities is re-read on this branch too.
    capabilitiesRefetched: sandbox.__fetches.slice(beforeFetchSave).includes('/api/capabilities'),
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
        // The server sends the account's NAME now — the platform's own login included — so the
        // fixture must not hand the panel a blank and let the tests pass on the old spelling.
        account: 'default',
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
    accounts: { zhihu: ['default', 'default2', 'work'], weibo: [] },
    rows: ACCOUNT_ROWS,
};
sandbox.__responses['/api/cookies/status'] = STATUS_ROWS;
setPlatform('zhihu');
doc.getElementById('cookie-account').value = '';
sandbox.refreshCookieStatus();
await flush();

/* The candidates are a popup on <body> now (a list permanently under the box made the panel
   taller for a choice made once per login, and a popup living inside a scrolling dialog gets
   clipped by it), so they are read from where the product put them — the body's children —
   and their labels and account values come off the built elements, not off a markup string. */
const candMenu = () => (doc.body.children || []).filter((c) => c._classes && c._classes.has('cand-menu'))[0] || null;
const chips = () => {
    const menu = candMenu();
    if (!menu) return [];
    return (menu.children || []).map((child) => ({
        text: child.textContent,
        account: (child.dataset && child.dataset.account) || '',
        open: menu.classList.contains('open'),
    }));
};
/* The cards are built as elements (no markup string is assembled from a response any more),
   so a row is read as the cells the user reads and the buttons the user presses — through the
   same query the browser would run, never by re-reading a string the product built. */
const rowsOf = (host) => Array.prototype.slice.call(host.querySelectorAll('tr.cookie-row'));
const headOf = (row) => {
    const cell = row.querySelector('.cookie-cell-account');
    return cell ? cell.textContent : '';
};
const platformOf = (row) => {
    const cell = row.querySelector('.cookie-cell-platform');
    return cell ? cell.textContent : '';
};
const buttonsOf = (row) => {
    const td = row.querySelector('.runs-mgr-ops');
    /* Both the label and whether it is dead: the default row still SHOWS 「重命名」 and refuses
       when pressed, and a report of the labels alone cannot tell that apart from a row whose
       rename works. */
    return td
        ? (td.children || []).map((b) => ({ label: b.textContent, disabled: !!b.disabled, title: b.title || '' }))
        : [];
};
const clickButton = (row, label) => {
    const td = row.querySelector('.runs-mgr-ops');
    const b = (td.children || []).filter((x) => x.textContent === label)[0];
    if (b) b.click();
    return !!b;
};
const managerRows = () =>
    rowsOf(doc.getElementById('cookies-mgr-body')).map((row) => ({
        platform: platformOf(row),
        account: headOf(row),
        key: (row.dataset || {}).account,
        buttons: buttonsOf(row),
        // The profile sentence was deleted; a rebuilt `cookie-row-state` cell is the proof it
        // came back, so the harness reports whether one exists.
        hasStateCell: !!row.querySelector('.cookie-row-state'),
    }));
const accountLine = () => doc.getElementById('cookie-account-status').textContent;

sandbox.renderCookieAccounts(true);
out.candidates = chips();
out.summaryLine = doc.getElementById('cookie-status').textContent;
out.lineForDefault = accountLine();
out.managerRows = managerRows();

/* The box is the subject: typing a name the machine does not have must change the answer
   WITHOUT another request (the rows are already cached), and typing one it does have must
   change it back. Typing also re-filters the popup — a candidate list that kept its old
   contents after a keystroke would offer a login the user has just typed past. */
doc.getElementById('cookie-account').value = 'ghost';
sandbox.renderCookieAccountStatus();
sandbox.renderCookieAccounts(true);
out.lineForGhost = accountLine();
out.ghostCandidates = chips();
doc.getElementById('cookie-account').value = 'WORK';
sandbox.renderCookieAccountStatus();
sandbox.renderCookieAccounts(true);
out.lineForWork = accountLine();
out.workCandidates = chips();
out.rowsAskedAgain = sandbox.__calls.filter((c) => c.url === '/api/cookies/status').length;

/* A candidate is clicked, not called by name: the row's account lives in a listener now, so
   the only way to prove the wiring is to press the button the user presses. */
sandbox.pickCookieAccount('');
doc.getElementById('cookie-account').value = '';
sandbox.renderCookieAccounts(true);
const workChip = chips().filter((c) => c.account === 'work')[0];
out.workChipSeen = !!workChip;
sandbox.__toasts.length = 0;
if (workChip) {
    const menu = candMenu();
    const pressed = (menu.children || []).filter((c) => (c.dataset || {}).account === 'work')[0];
    pressed.click();
}
out.afterCandidateClick = {
    box: doc.getElementById('cookie-account').value,
    popupClosed: !(candMenu() || { classList: { contains: () => false } }).classList.contains('open'),
    toast: sandbox.__toasts.slice(),
};
/* The default login now has a NAME that shows in the box, so a pick of it is visible the same
   way any other pick is — this is the assertion that keeps 「它也要填值」 from regressing. The
   box is cleared first: typing `work` filters the popup down to that one login, and a scenario
   that looked for the default chip while a filter was active would only prove the filter. */
sandbox.__toasts.length = 0;
doc.getElementById('cookie-account').value = '';
sandbox.renderCookieAccounts(true);
const defaultMenu = candMenu();
const defaultChip = (defaultMenu.children || []).filter((c) => (c.dataset || {}).account === 'default')[0];
out.defaultChipSeen = !!defaultChip;
if (defaultChip) defaultChip.click();
out.afterDefaultPick = {
    box: doc.getElementById('cookie-account').value,
    toast: sandbox.__toasts.slice(),
};
sandbox.pickCookieAccount('default2');
out.afterPick = {
    box: doc.getElementById('cookie-account').value,
    line: accountLine(),
};

/* A row's delete names its OWN login, and it is reached through the button's listener:
   the box says default2 now, so a row that acted on the box would delete the wrong file.
   Buttons are matched by the KEY they were labelled from — this harness's I18n.t answers
   with the key, so a translated string would never appear here. */
sandbox.__responses['/api/cookies/delete'] = { ok: true, message: 'gone', profile_holds: false };
sandbox.__dialogAnswer = 'delete';
sandbox.__calls.length = 0;
const rowByKey = (key) => rowsOf(doc.getElementById('cookies-mgr-body')).filter((r) => (r.dataset || {}).account === key)[0] || null;
const workCard = rowByKey('work');
out.workCardFound = !!workCard;
if (workCard) {
    out.workCardButtons = buttonsOf(workCard);
    clickButton(workCard, 'cookies.deleteOne');
    await flush();
}
out.rowDelete = {
    posted: sandbox.__calls
        .filter((c) => c.url === '/api/cookies/delete')
        .map((c) => JSON.parse(c.opts.body)),
    boxStill: doc.getElementById('cookie-account').value,
};

/* Nothing saved: no candidates, and the list says so rather than showing a table of
   nothing. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/status'] = { ok: true, cookies: {}, accounts: {}, rows: [] };
sandbox.refreshCookieStatus();
await flush();
sandbox.renderCookieAccounts(true);
out.nothingSaved = {
    chips: chips(),
    manager: rowsOf(doc.getElementById('cookies-mgr-body')).map((r) => r.textContent),
    note: (doc.getElementById('cookies-mgr-body').children || []).map((c) => c.textContent),
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

/* ── 「重命名」 in the saved-logins table ────────────────────────
   A rename is the one row action that can point at the WRONG login (a delete that used the
   panel's own selection would simply destroy a different session), so the name the user
   clicked is what must be sent, and the answer must say what moved. The default row offers no
   rename at all — its browser directory IS the platform's — and clicking it says that instead
   of quietly doing nothing. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/status'] = STATUS_ROWS;
sandbox.__responses['/api/cookies/rename'] = { ok: true, account: 'office', message: 'RENAMED' };
/* Read it back through the panel's own request, not by repainting: the previous section left
   the cached rows empty, and a repaint from that cache would have this block press buttons on
   rows that are not there (and report the absence as a passing test). */
sandbox.refreshCookieStatus();
await flush();
out.rowButtons = {
    work: buttonsOf(rowByKey('work')),
    // The default row's rename says why it cannot, rather than being absent in silence.
    defaultRow: buttonsOf(rowByKey('default')),
};
sandbox.__dialogAnswer = 'office';
sandbox.__calls.length = 0;
sandbox.__toasts.length = 0;
clickButton(rowByKey('work'), 'cookies.renameOne');
await flush();
out.renamed = {
    posted: sandbox.__calls.filter((c) => c.url === '/api/cookies/rename').map((c) => JSON.parse(c.opts.body)),
    box: doc.getElementById('cookie-account').value,
    toasts: sandbox.__toasts.slice(),
};
/* The default account is refused BEFORE anything is sent: the name is legal, the directory it
   would have to move is the one every other account of that platform lives inside. */
sandbox.__calls.length = 0;
sandbox.__toasts.length = 0;
clickButton(rowByKey('default'), 'cookies.renameOne');
await flush();
out.renameDefault = {
    posted: sandbox.__calls.filter((c) => c.url === '/api/cookies/rename').length,
    toasts: sandbox.__toasts.slice(),
};
/* Typing the same name back is not a rename, and a round trip that reports success without
   moving anything would be a lie the panel tells about the disk. */
sandbox.__dialogAnswer = 'work';
sandbox.__calls.length = 0;
sandbox.__toasts.length = 0;
clickButton(rowByKey('work'), 'cookies.renameOne');
await flush();
out.renameSame = {
    posted: sandbox.__calls.filter((c) => c.url === '/api/cookies/rename').length,
    toasts: sandbox.__toasts.slice(),
};

/* ── the list docks in the bottom slot, with the other five ──────
   Opening it must shut 控制台/运行记录/导出产物 (one bottom slot, mutually exclusive), and
   it must read the server rather than the dialog's cache. */
for (const key of Object.keys(sandbox.__responses)) delete sandbox.__responses[key];
sandbox.__responses['/api/cookies/status'] = STATUS_ROWS;
sandbox.__calls.length = 0;
['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel', 'workflows-panel'].forEach((id) => {
    doc.getElementById(id).classList.add('open');
});
sandbox.toggleCookiesPanel();
await flush();
out.docked = {
    cookiesOpen: doc.getElementById('cookies-panel').classList.contains('open'),
    othersLeftOpen: ['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel', 'workflows-panel'].filter(
        (id) => doc.getElementById(id).classList.contains('open')
    ),
    asked: sandbox.__calls.filter((c) => c.url === '/api/cookies/status').length,
    rows: rowsOf(doc.getElementById('cookies-mgr-body')).length,
};
sandbox.toggleCookiesPanel();
out.dockedAfterClose = {
    cookiesOpen: doc.getElementById('cookies-panel').classList.contains('open'),
    height: doc.getElementById('cookies-panel').style.height,
};

/* ── the docked table repaints its words on a language switch, from the cache ──
   Every word in this table (platform, account, the two buttons) is built by JS from a
   catalogue key, so the shipped ``I18n.t`` answers with the bare key and a language change
   would be INVISIBLE here. To see the repaint at all this scenario re-stubs ``t`` to tag
   every word with the language it was read in: a re-render then shows up as the tag moving,
   and a panel that kept speaking the old language would leave the tag behind. That it costs
   no second ``/api/cookies/status`` is the other half — a language switch is not news about
   the disk, so the rows already in hand must be enough. */
sandbox.__responses['/api/cookies/status'] = STATUS_ROWS;
sandbox.refreshCookieStatus();
await flush();
const plainT = sandbox.I18n.t;
sandbox.I18n.t = (k, vars) => plainT(k, vars) + '@' + sandbox.I18n.lang;
const firstPlatformCell = () => {
    const row = rowsOf(doc.getElementById('cookies-mgr-body'))[0];
    const cell = row && row.querySelector('.cookie-cell-platform');
    return cell ? cell.textContent : '';
};
const firstButtons = () => (rowsOf(doc.getElementById('cookies-mgr-body'))[0] ? buttonsOf(rowsOf(doc.getElementById('cookies-mgr-body'))[0]).map((b) => b.label) : []);
// Render once under the tagged t() in the current language to get the "before" words.
sandbox.cookiesManager.onLanguageChange();
const languageBefore = { platform: firstPlatformCell(), buttons: firstButtons() };
const askedBefore = sandbox.__calls.filter((c) => c.url === '/api/cookies/status').length;
sandbox.I18n.lang = 'zh';
sandbox.cookiesManager.onLanguageChange();
const languageAfter = { platform: firstPlatformCell(), buttons: firstButtons() };
const askedAfter = sandbox.__calls.filter((c) => c.url === '/api/cookies/status').length;
sandbox.I18n.lang = 'en';
sandbox.I18n.t = plainT;
out.languageRepaint = {
    before: languageBefore,
    after: languageAfter,
    askedDuringSwitch: askedAfter - askedBefore,
};

process.stdout.write(JSON.stringify(out));
