/* Drives the REAL update.js (with the real app.js catalogue) under node.
 *
 * What only this can prove, and what none of it is visible to a Python test:
 *   · 稍后 is REMEMBERED (localStorage, 24 h, per version) — it used to live in sessionStorage,
 *     which in a desktop window means "forgotten the moment you close it";
 *   · the card paints every state the server can report, including a download that was already
 *     running when the page loaded (a reload must not offer the download again);
 *   · the three answers go to the three routes, with a POST body-less request each;
 *   · a language switch repaints the sentence that carries {version} and {progress}.
 *
 * The dialog is the ONE thing stubbed: what is under test is the answer the card does with it, not
 * the dialog's own rendering (harness_dialog_a11y.mjs drives that).
 *
 * Usage: node harness_update.mjs <module.js> …  (workflow.js, app.js, update.js)
 * Output: one JSON object of observations on stdout.
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { sourcesWithCompanions } from './companions.mjs';

const modules = sourcesWithCompanions(process.argv.slice(2));
const calls = { posts: [], gets: [], dialogs: [], toast: [] };
const replies = {
    check: {
        ok: true,
        supported: true,
        current: '2026.11.11.2',
        latest: '2026.12.1.1',
        update_available: true,
        apply_supported: true,
        signed: false,
        notes: '修复若干问题',
        job: { state: 'idle' },
    },
    download: { ok: true, job: { id: 'j1', version: '2026.12.1.1', state: 'downloading', progress: 0 } },
    status: { ok: true, job: { id: 'j1', version: '2026.12.1.1', state: 'downloading', progress: 40 } },
    restart: { ok: true, restarting: true },
    cancel: { ok: true, job: { state: 'idle' } },
};
let dialogAnswer = 'later';

function payloadFor(url) {
    const path = String(url).split('?')[0];
    if (path.endsWith('/api/update/check')) return replies.check;
    if (path.endsWith('/api/update/download')) return replies.download;
    if (path.endsWith('/api/update/status')) return replies.status;
    if (path.endsWith('/api/update/restart')) return replies.restart;
    if (path.endsWith('/api/update/cancel')) return replies.cancel;
    return { ok: true };
}

const sandbox = {
    ...baseSandbox(),
    console: { log() {}, warn() {}, error() {} },
};
sandbox.fetch = (url, options) => {
    const method = ((options && options.method) || 'GET').toUpperCase();
    const record = { url: String(url), method };
    (method === 'POST' ? calls.posts : calls.gets).push(record);
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payloadFor(url)) });
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
for (const src of modules) vm.runInContext(src, sandbox);
sandbox.showDialog = async (spec) => {
    calls.dialogs.push(spec);
    return dialogAnswer;
};
sandbox.showToast = (text) => calls.toast.push(String(text));

const run = (code) => vm.runInContext(code, sandbox);
const tick = (ms = 40) => new Promise((resolve) => setTimeout(resolve, ms));
const doc = sandbox.document;

function paint() {
    const card = doc.getElementById('update-banner');
    if (!card) return { mounted: false };
    const text = card.querySelector('.update-text');
    const now = card.querySelector('.update-now');
    const later = card.querySelector('.update-later');
    const cancel = card.querySelector('.update-cancel');
    const progress = card.querySelector('.update-progress');
    const bar = card.querySelector('.update-bar');
    return {
        mounted: true,
        hidden: !!card.hidden,
        label: card.querySelector('.update-label').textContent,
        version: card.querySelector('.update-version').textContent,
        text: text ? text.textContent : '',
        now: now && !now.hidden ? now.textContent : null,
        later: later && !later.hidden ? later.textContent : null,
        cancel: cancel && !cancel.hidden ? cancel.textContent : null,
        progress: progress && !progress.hidden ? (bar ? bar.style.width : '') : null,
    };
}

const report = {};
run("I18n.lang = 'zh';");

/* 1. The prompt: one card, both answers, no dialog yet. */
await run('UpdatePanel.check()');
report.ready = paint();
report.readyCalls = { posts: calls.posts.length, dialogs: calls.dialogs.length };

/* 2. 稍后 is remembered for a day, per version. */
run("document.querySelector('.update-later').onclick()");
report.afterLater = paint();
report.snooze = JSON.parse(sandbox.localStorage.getItem('update-snooze') || '{}');
report.snoozeHours = Math.round((Number(report.snooze.until) - Date.now()) / 3600000);

/* 3. A later check does not ask again... */
await run('UpdatePanel.check()');
report.snoozedAgain = paint();

/* 4. ...but a NEWER version does. */
replies.check = { ...replies.check, latest: '2026.12.2.1' };
await run('UpdatePanel.check()');
report.newerVersion = paint();

/* 5. 不再提示此版本 (dialog answer 'skip'). */
dialogAnswer = 'skip';
await run('UpdatePanel._ask()');
report.skip = JSON.parse(sandbox.localStorage.getItem('update-snooze') || '{}');
replies.check = { ...replies.check, latest: '2026.12.2.2' };
await run('UpdatePanel.check()');
report.afterSkip = paint();

/* 6. 立即更新: POST /download, then the card follows the job. */
dialogAnswer = 'now';
replies.status = { ok: true, job: { id: 'j1', version: '2026.12.2.2', state: 'downloading', progress: 40 } };
await run('UpdatePanel._ask()');
report.downloading = paint();
report.downloadPosts = calls.posts.map((item) => item.url);

/* 7. The download finishes: the card offers the restart and stops polling. */
replies.status = { ok: true, job: { id: 'j1', version: '2026.12.2.2', state: 'staged', progress: 100 } };
await tick(120);
report.staged = paint();
const pollsBefore = calls.gets.length;
await tick(120);
report.pollingStopped = calls.gets.length === pollsBefore;

/* 8. 重启并完成更新 posts /restart. */
await run('UpdatePanel._restart()');
await tick(20);
report.restartPosts = calls.posts.map((item) => item.url);
report.applying = paint();

/* 9. A page reload while a download is in flight reattaches instead of re-offering. */
replies.check = {
    ...replies.check,
    latest: '2026.12.3.1',
    update_available: true,
    job: { id: 'j2', version: '2026.12.3.1', state: 'downloading', progress: 42 },
};
replies.status = { ok: true, job: { id: 'j2', version: '2026.12.3.1', state: 'staged', progress: 100 } };
await run('UpdatePanel.check()');
report.reattached = paint();
await tick(120);

/* 10. A version this install cannot apply: no download button, an installer sentence. */
replies.check = { ...replies.check, apply_supported: false, job: { state: 'idle' } };
await run('UpdatePanel.check()');
report.unsupported = paint();

/* 11. A failure is a named reason with 重试, never a dead card. */
replies.check = {
    ...replies.check,
    apply_supported: true,
    job: { id: 'j3', version: '2026.12.3.1', state: 'failed', error_code: 'sha', error_detail: '摘要不符' },
};
await run('UpdatePanel.check()');
await tick(20);
report.failed = paint();

/* 12. Cancel clears the card and the job. */
replies.check = {
    ...replies.check,
    job: { id: 'j4', version: '2026.12.4.1', state: 'downloading', progress: 10 },
};
await run('UpdatePanel.check()');
await run('UpdatePanel._cancel()');
await tick(20);
report.cancelled = paint();

/* 13. A language switch repaints the sentence the card itself formats (no request). */
replies.check = { ...replies.check, job: { state: 'idle' }, latest: '2026.12.5.1' };
await run('UpdatePanel.check()');
report.chinese = paint();
run("I18n.lang = 'en'; UpdatePanel.onLanguageChange();");
report.english = paint();

/* 14. The settings-menu button: a check the user ASKED for is not silenced by 稍后 / 不再提示. */
sandbox.localStorage.setItem(
    'update-snooze',
    JSON.stringify({ version: '2026.12.6.1', until: Date.now() + 86400000, skip: true }),
);
replies.check = {
    ok: true,
    supported: true,
    current: '2026.11.11.2',
    latest: '2026.12.6.1',
    update_available: true,
    apply_supported: true,
    signed: false,
    notes: '',
    job: { state: 'idle' },
};
await run('UpdatePanel.checkNow()');
report.manualCheck = paint();
report.manualToast = calls.toast[calls.toast.length - 1];

/* 15. Nothing to offer: the press gets an answer instead of looking broken. */
replies.check = { ...replies.check, latest: '2026.11.11.2', update_available: false };
await run('UpdatePanel.checkNow()');
report.manualLatest = paint();
report.manualLatestToast = calls.toast[calls.toast.length - 1];

/* 16. A host with no feed (a source checkout) names why, rather than saying nothing. */
replies.check = { ok: true, supported: false, current: '2026.11.11.2', reason: 'source' };
await run('UpdatePanel.checkNow()');
report.manualNoChannel = paint();
report.manualNoChannelToast = calls.toast[calls.toast.length - 1];

process.stdout.write(JSON.stringify(report));
