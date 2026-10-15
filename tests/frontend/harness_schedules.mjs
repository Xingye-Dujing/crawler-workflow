/* Drives the REAL schedules.js dock (with the real workflow.js + app.js) under node.
 *
 * What this file is for: the panel is the only place a user can write a schedule, and every rule
 * that keeps that honest lives in JavaScript — the table is painted from ONE server payload (never
 * from local guesses), a status token becomes a catalogue word but an unknown one shows as itself,
 * the editor is one dialog whose fields say exactly what the server will be asked, and a refusal
 * from the server is shown as the server worded it. None of that is visible to a Python test.
 *
 * The dialog is the ONE thing stubbed, and on purpose: what is under test is what the panel ASKS a
 * dialog for (`fields`/`toggles`/`buttons`) and what it does with the answer, not the dialog's own
 * rendering (harness_dialog_a11y.mjs drives that).
 *
 * Usage: node harness_schedules.mjs <workflow.js> <app.js> <schedules.js>
 * Output: one JSON object of observations on stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const workflowSrc = fs.readFileSync(process.argv[2], 'utf8');
const appSrc = fs.readFileSync(process.argv[3], 'utf8');
const schedulesSrc = fs.readFileSync(process.argv[4], 'utf8');

const calls = { gets: 0, posts: [], toasts: [], dialogs: [], dialog: null };
/* One mutable reply for every request, so a scenario can make the server refuse
 * without rebuilding the world — and a POST is answered the same way a real one is:
 * with the WHOLE payload, which is what the panel repaints from. */
let reply = { ok: true, tasks: [], canvases: [], status: {} };

const sandbox = {
    ...baseSandbox(),
    console: { log() {}, warn() {}, error() {} },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
};
sandbox.fetch = (url, options) => {
    const method = (options && options.method) || 'GET';
    if (method === 'POST') {
        calls.posts.push({ url: String(url), body: JSON.parse((options && options.body) || '{}') });
    } else {
        calls.gets += 1;
    }
    return Promise.resolve({
        ok: true,
        status: reply && reply.ok === false ? 400 : 200,
        text: () => Promise.resolve(JSON.stringify(reply)),
    });
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(workflowSrc, sandbox);
vm.runInContext(appSrc, sandbox);
vm.runInContext(schedulesSrc, sandbox);
/* Chinese: every status word differs from the token it came from, so "the token became
   a word" is an observation rather than a coincidence of English spelling. */
vm.runInContext("I18n.lang = 'zh';", sandbox);
sandbox.showDialog = async (spec) => {
    calls.dialogs.push(spec);
    calls.dialog = spec;
    return sandbox.__dialogAnswer === undefined ? null : sandbox.__dialogAnswer;
};
sandbox.showToast = (message) => calls.toasts.push(String(message));

const body = () => sandbox.__byId('schedules-mgr-body');
const html = () => body().innerHTML;
const buttons = () => body().querySelectorAll('button');
const rowText = () => body().innerHTML;

const CLOCK = {
    running: true,
    wired: true,
    tick_seconds: 20,
    now_local: '2026-10-15 20:00',
    local_zone: '中国标准时间 UTC+08:00',
};

function task(over) {
    return Object.assign(
        {
            id: 'abc123',
            name: '每天早八',
            workflow: '红果短剧',
            lang: 'zh',
            enabled: true,
            trigger: { kind: 'daily', at: '08:00' },
            trigger_text: '每天 08:00',
            timezone: 'Asia/Shanghai',
            timezone_label: 'Asia/Shanghai',
            next_run: '2026-10-16T00:00:00+00:00',
            next_run_local: '2026-10-16 08:00 (Asia/Shanghai)',
            last_run: { at: '2026-10-15T00:00:00+00:00', status: 'refused', run_id: 'run-3', note: '画布需要模型' },
            last_run_local: '2026-10-15 08:00 (Asia/Shanghai)',
            missed: { count: 2, last_at: '2026-10-14T00:00:00+00:00' },
            history: [],
        },
        over || {},
    );
}

const CANVASES = [
    { name: '红果短剧', runnable: true, why_not: '' },
    { name: '要模型', runnable: false, why_not: '需要模型，不能定时' },
];

const out = {};

/* ── 1. The table comes from the payload, verbatim ───────────────────────────── */
reply = { ok: true, tasks: [task({})], canvases: CANVASES, status: CLOCK };
await sandbox.schedulesManager.refresh();
out.painted = rowText();
out.rows = body().querySelectorAll('tr').length;
out.header = body()
    .querySelectorAll('th')
    .map((cell) => cell.textContent);
out.statusLine = (body().querySelector('.sched-status') || {}).textContent || '';
out.rowButtons = buttons().map((button) => button._text);

/* ── 2. A token becomes a word; an unknown token stays itself ────────────────── */
reply = {
    ok: true,
    tasks: [
        task({ id: 'a1', last_run: { status: 'started', run_id: '', note: '' } }),
        task({ id: 'a2', last_run: { status: 'weird', run_id: '', note: '' } }),
    ],
    canvases: CANVASES,
    status: CLOCK,
};
sandbox.schedulesManager._tasks = reply.tasks;
sandbox.schedulesManager.render();
out.words = html();

/* ── 3. A hostile id must not be able to break out of the attribute ──────────── */
const HOSTILE = "a' onmouseover='alert(1)";
reply = { ok: true, tasks: [task({ id: HOSTILE, name: HOSTILE, workflow: HOSTILE })], canvases: CANVASES, status: CLOCK };
sandbox.schedulesManager._tasks = reply.tasks;
sandbox.schedulesManager.render();
out.hostile = {
    raw: html(),
    breaksOut: html().indexOf("onmouseover='") >= 0,
    buttons: buttons().length,
    wired: buttons().filter((button) => String(button.onclick || '').indexOf('schedulesManager.') === 0).length,
};

/* ── 4. Nothing saved, and the clock still reported ─────────────────────────── */
reply = { ok: true, tasks: [], canvases: CANVASES, status: CLOCK };
await sandbox.schedulesManager.refresh();
out.empty = { html: html(), rows: body().querySelectorAll('tr').length };

/* ── 5. A server that refuses is quoted, never paraphrased ──────────────────── */
reply = { ok: false, error: '时间格式无法识别：25:00', tasks: [], canvases: CANVASES, status: Object.assign({}, CLOCK, { running: false }) };
await sandbox.schedulesManager.refresh();
out.refused = html();
reply = {
    ok: false,
    error: '需要模型，不能定时',
    tasks: [task({ id: 'kept', name: '留下的任务' })],
    canvases: CANVASES,
    status: Object.assign({}, CLOCK, { running: false }),
};
sandbox.schedulesManager._canvases = CANVASES;
calls.toasts.length = 0;
await sandbox.schedulesManager.toggleTask('kept', false);
out.refusedPost = { posts: calls.posts.slice(-1), toasts: calls.toasts.slice(), html: html() };

/* ── 6. The editor asks the server's own questions ─────────────────────────── */
calls.dialogs.length = 0;
calls.posts.length = 0;
sandbox.__dialogAnswer = null; /* cancel, so nothing is written */
reply = { ok: true, tasks: [task({ id: 'gone-id', workflow: '已经改名的画布' })], canvases: CANVASES, status: CLOCK };
sandbox.schedulesManager._tasks = reply.tasks;
sandbox.schedulesManager._canvases = CANVASES;
await sandbox.schedulesManager.edit('gone-id');
const spec = calls.dialogs[calls.dialogs.length - 1] || { fields: [], buttons: [] };
const field = (id) => spec.fields.filter((f) => f.id === id)[0] || {};
out.editor = {
    message: spec.message || '',
    fields: spec.fields.map((f) => ({ id: f.id, value: f.value, type: f.type })),
    canvasOptions: (field('sched-canvas').options || []).map((o) => [o.value, o.label]),
    weekdayOptions: (field('sched-weekday').options || []).map((o) => o.value),
    kindOptions: (field('sched-kind').options || []).map((o) => o.value),
    toggles: spec.toggles || [],
    buttons: (spec.buttons || []).map((b) => ({ label: b.label, value: b.value, collect: !!b.collect, primary: !!b.primary })),
    posted: calls.posts.length,
};

/* ── 7. …and a save posts only the keys the chosen kind means ──────────────── */
calls.posts.length = 0;
sandbox.__dialogAnswer = {
    value: 'save',
    fields: {
        'sched-name': '  周三九点半  ',
        'sched-canvas': '红果短剧',
        'sched-kind': 'weekly',
        'sched-at': '09:30',
        'sched-weekday': '3',
        'sched-interval': '45',
        'sched-cron': '*/5 * * * *',
        'sched-zone': ' Asia/Shanghai ',
        'sched-lang': 'zh',
    },
    toggles: { 'sched-enabled': false },
};
await sandbox.schedulesManager.edit('gone-id');
out.saved = { posts: calls.posts.slice(), toasts: calls.toasts.slice(-1) };

/* ── 8. 立即执行 says which of the two things happened ─────────────────────── */
calls.posts.length = 0;
calls.toasts.length = 0;
for (const status of ['started', 'queued']) {
    reply = { ok: true, tasks: [task({})], canvases: CANVASES, status: CLOCK, result: { status: status, name: '每天早八', run_id: 'run-9' } };
    await sandbox.schedulesManager.runNow('abc123');
}
out.runToasts = calls.toasts.slice();

/* ── 9. Deleting asks first, and the answer decides ────────────────────────── */
calls.posts.length = 0;
calls.toasts.length = 0;
sandbox.__dialogAnswer = null;
reply = { ok: true, tasks: [task({})], canvases: CANVASES, status: CLOCK };
await sandbox.schedulesManager.remove('abc123');
out.removeCancelled = calls.posts.length;
sandbox.__dialogAnswer = 'yes';
await sandbox.schedulesManager.remove('abc123');
out.removePosts = calls.posts.slice();

/* ── 10. The dock: one slot, and a handle to grow it with ──────────────────── */
const panels = ['runs-panel', 'exports-panel', 'schedules-panel'];
panels.forEach((id) => {
    const el = sandbox.__byId(id);
    el.classList.add('open');
    el.style.height = '300px';
});
sandbox.__byId('schedules-panel').classList.remove('open');
sandbox.toggleSchedulesPanel();
out.dock = {
    open: panels.filter((id) => sandbox.__byId(id).classList.contains('open')),
    staleHeights: panels.filter((id) => sandbox.__byId(id).style.height && !sandbox.__byId(id).classList.contains('open')),
};
sandbox.toggleSchedulesPanel();
out.dock.afterSecondToggle = {
    open: panels.filter((id) => sandbox.__byId(id).classList.contains('open')),
    height: sandbox.__byId('schedules-panel').style.height || '',
};

process.stdout.write(JSON.stringify(out));
