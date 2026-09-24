/* Runs the REAL panel actions of workflow.js under node.
 *
 * The panels themselves are rendered and asserted elsewhere; what had never been
 * executed is the click behind the row — 继续 / 重新开始 / 删除 / 详情 on a stored
 * run, download / view / delete on an export file, rename / delete on a dataset,
 * Kill on a process row, and the three top-bar controls that write settings
 * (pin, background, language). Each of those is a request body, a confirmation, or
 * a "which endpoint" decision, so a mistake is silent data loss or a paid re-crawl.
 *
 * The decisions worth pinning:
 *   · discarding a run also drops its "already crawled" claims, so a restart
 *     re-crawls instead of returning fewer rows;
 *   · deleting a FINISHED run keeps them (it must not resurrect items as unseen),
 *     so the two paths hit different endpoints;
 *   · every destructive action asks first, and an answer of "no" sends nothing;
 *   · while a run is going, continue/restart refuse instead of queueing a
 *     second attempt at the same data;
 *   · a dataset a saved workflow still points at is refused client-side too;
 *   · the language switch re-renders every JS-built surface, not just the
 *     attribute-stamped ones.
 *
 * Usage: node harness_panel_actions.mjs <canvas.js> <workflow.js> <stats.js> <app.js> <menu.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow, resetWorld } from './harness_dom.mjs';

const paths = process.argv.slice(2);
const src = paths.map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

const answers = { confirm: true, dialog: null };
/* Every dialog spec the modules under test asked for, in order. A dialog WITH an
   input is answered by the real showDialog with `b.value !== undefined ? b.value :
   inputEl.value`, so a confirm button carrying its own value token silently
   replaces whatever the user typed — the shape of the spec is therefore part of
   what a scenario asserts, not an implementation detail. */
const dialogSpecs = [];
const requests = [];
const toasts = [];
const opened = [];
const sandbox = {
    ...baseSandbox(),
    confirm: () => answers.confirm,
    alert: () => {},
    open: (url) => opened.push(String(url)),
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(
    `${src}
     ;globalThis.__pa = { resumeBar, runsManager, exportsManager, datasetManager, dataNodes,
                          workflow, canvas, historyPanel, processesPoll, killProcess,
                          togglePin, setBg, setLang, closeDockedPanels, RunState };`,
    sandbox,
);

/* Installed after the load so the real function bodies see them. */
sandbox.showToast = (m) => toasts.push(String(m));
sandbox.showDialog = async (spec) => {
    answers.spec = spec;
    dialogSpecs.push({
        hasInput: !!(spec && spec.input),
        buttons: (spec && spec.buttons || []).map((b) => ({
            label: b.label,
            primary: !!b.primary,
            /* '<absent>' and 'null' mean different things to the real resolver:
               the first falls back to the input, the second answers null (cancel). */
            value: 'value' in b ? String(b.value) : '<absent>',
        })),
    });
    return typeof answers.dialog === 'function' ? answers.dialog(spec) : answers.dialog;
};

/* One answer for every URL would be a lie: `execute()` starts by probing the
 * cookie status, then the run-gate settings, then posts the run — a single shared
 * object would satisfy one of those three and silently abort the rest, and the
 * scenario would report "no request" for a click that works in the browser. So the
 * stub routes by URL, with defaults that let a run reach the POST. */
const defaultRoutes = () => ({
    '/api/cookies/status': { ok: true, cookies: { zhihu: true } },
    '/api/settings': { ok: true, settings: { cookie_confirm_before_run: false } },
    '/api/workflow/execute': { ok: true, run_id: 'newrun1' },
    '/api/runs/discard': { ok: true },
    '/api/runs/delete': { ok: true },
    '/api/exports/delete': { ok: true },
    '/api/workflow/processes/kill': { ok: true, message: 'killed' },
});
const routes = defaultRoutes();
let answer = { ok: true };
/** Override one route's answer for a refusal scenario. A single shared fallback
 *  object cannot express "the delete failed but the rest of the page still works". */
function route(path, value) {
    routes[path] = value;
}
sandbox.fetch = (url, opts) => {
    const path = String(url).split('?')[0];
    requests.push({ url: String(url), method: (opts && opts.method) || 'GET', body: opts && opts.body });
    const answered = Object.prototype.hasOwnProperty.call(routes, path) ? routes[path] : answer;
    /* `fetchJSON` reads `.text()` and parses it, while the rest of the app calls
       `.json()`; a response stub with only one of the two makes every dataset
       action look like a crash for a reason that has nothing to do with the code. */
    const text = JSON.stringify(answered);
    return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(answered),
        text: () => Promise.resolve(text),
    });
};
/* setInterval is used by the language switch to re-stamp the canvas; capture it so
   nothing fires after the scenario that scheduled it. */
sandbox.setInterval = () => 1;
sandbox.clearInterval = () => {};

const pa = sandbox.__pa;
const doc = sandbox.document;
const out = {};

function id(name) {
    return doc.getElementById(name);
}

function fresh() {
    resetWorld(sandbox);
    sandbox.localStorage.removeItem('crawler_settings');
    sandbox.localStorage.removeItem('crawler_canvas');
    requests.length = 0;
    toasts.length = 0;
    opened.length = 0;
    answers.confirm = true;
    answers.dialog = null;
    dialogSpecs.length = 0;
    answer = { ok: true };
    Object.assign(routes, defaultRoutes());
    pa.resumeBar.hide();
    pa.runsManager._shown = [];
    pa.exportsManager._last = [];
    pa.datasetManager._last = [];
    Object.keys(pa.canvas.nodes).forEach((key) => delete pa.canvas.nodes[key]);
    pa.canvas.connections = [];
    pa.canvas._settingsNodeId = null;
    /* A scenario that pressed a run-starting button leaves the page "running",
       and every later continue/restart then refuses itself for the wrong reason. */
    pa.RunState.running = false;
    pa.canvas.init();
}

/** Let queued promises run: `execute()` is async and starts with a cookie probe,
 *  so a click that looked synchronous had in fact sent nothing yet. */
async function drain() {
    for (let i = 0; i < 8; i += 1) await new Promise((resolve) => setImmediate(resolve));
}

/** upload → output: the smallest canvas the shipped validator signs off on.
 *
 * `init()` is called once per scenario, never per node: it re-reads the stored
 * draft, and a draft written by the previous addNode would rebuild the canvas out
 * from under the params this helper is about to set. */
function addCanvasNode(type, params) {
    const nid = pa.canvas.addNode(type, 10, 10);
    if (params) {
        pa.canvas.nodes[nid].params = params;
        pa.canvas.updateNodeDisplay(nid);
    }
    return nid;
}

function addFlow() {
    const upload = addCanvasNode('upload', { dataset_id: 'ds1', dataset_name: 'a.csv', row_count: 3 });
    const save = addCanvasNode('output', { operation: 'save', format: 'csv', filename: 'a.csv' });
    pa.canvas.connections = [{ from: upload, to: save }];
    pa.canvas.scheduleRender();
    return [upload, save];
}

const RESUMABLE = {
    ok: true,
    runs: [{ run_id: 'abc123', started_at: '2026-01-02T03:04:05', node_done: 2, node_total: 5, rows_kept: 40 }],
};

/* ── the resume banner ─────────────────────────────────────────────── */
fresh();
out.banner_without_canvas_nodes = await (async () => {
    addCanvasNode('upload');
    Object.keys(pa.canvas.nodes).forEach((key) => delete pa.canvas.nodes[key]);
    return { candidate: await pa.resumeBar.refresh().then(() => pa.resumeBar.candidate), hidden: id('resume-banner').classList.contains('hidden') };
})();

fresh();
addFlow();
answer = RESUMABLE;
await pa.resumeBar.refresh();
out.banner_shown = {
    candidate: pa.resumeBar.candidate && pa.resumeBar.candidate.run_id,
    hidden: id('resume-banner').classList.contains('hidden'),
    text: id('resume-text').textContent,
    requested: requests.map((r) => ({ url: r.url, method: r.method })),
};
requests.length = 0;
pa.resumeBar.continueRun();
await drain();
out.banner_continue = {
    urls: requests.map((r) => r.url),
    toasts: toasts.slice(),
    resumedFrom: sentTo('/api/workflow/execute') && sentTo('/api/workflow/execute').resume_run_id,
};

fresh();
addFlow();
answer = RESUMABLE;
await pa.resumeBar.refresh();
requests.length = 0;
await pa.resumeBar.restart();
await drain();
out.banner_restart = {
    urls: requests.map((r) => r.url),
    discarded: sentTo('/api/runs/discard') ? [sentTo('/api/runs/discard')] : [],
    started: requests.some((r) => r.url.indexOf('/api/workflow/execute') === 0),
    toasts: toasts.slice(),
    hidden: id('resume-banner').classList.contains('hidden'),
};

fresh();
addFlow();
answer = { ok: false, error: 'server said no' };
await pa.resumeBar.refresh();
out.banner_failure = { candidate: pa.resumeBar.candidate, hidden: id('resume-banner').classList.contains('hidden') };

fresh();
addFlow();
answer = RESUMABLE;
await pa.resumeBar.refresh();
pa.resumeBar.dismiss();
out.banner_dismiss = { candidate: pa.resumeBar.candidate, hidden: id('resume-banner').classList.contains('hidden') };

/* ── the run-records panel ─────────────────────────────────────────── */
fresh();
pa.runsManager._shown = [{ run_id: 'r1', workflow_name: "It's 三亚" }];
requests.length = 0;
answer = { ok: true, run: { run_id: 'r1', nodes: [] } };
await pa.exportsManager.report('r1', "It's 三亚");
out.report_dialog = { requested: requests.length };

fresh();
answers.dialog = { ok: true, format: 'html' };
answer = { ok: true, file: { name: 'report.html' } };
requests.length = 0;
await pa.exportsManager.report('r1', '名字');
out.report_request = { url: requests[0] && requests[0].url, body: requests[0] && JSON.parse(requests[0].body) };

fresh();
answers.dialog = null;
requests.length = 0;
await pa.exportsManager.report('r1', '名字');
out.report_cancelled = { requested: requests.length };

/* continue / restart refuse to start a second attempt while one is going */
fresh();
pa.RunState.running = true;
requests.length = 0;
pa.runsManager.continueRun('r9');
await drain();
out.busy_continue = { requested: requests.length, toasts: toasts.slice() };
requests.length = 0;
await pa.runsManager.restart('r9');
await drain();
out.busy_restart = { requested: requests.length };
pa.RunState.running = false;

/** The last recorded request to a path, parsed. `execute()` probes the cookie
 *  status and the run gate before it posts, so "requests[0]" is never the body a
 *  scenario is actually asserting on. */
function sentTo(path) {
    const found = requests.filter((r) => r.url.split('?')[0] === path).pop();
    return found && found.body ? JSON.parse(found.body) : null;
}

fresh();
requests.length = 0;
addFlow();
pa.runsManager.continueRun('r9');
await drain();
out.free_continue = {
    requested: requests.map((r) => r.url),
    /* The reason a click sent no run is always a toast: validation, the cookie
       probe, or the LLM pre-check. Printing it keeps a scaffolding mistake from
       reading like a product bug (and the reverse). */
    toasts: toasts.slice(),
    resume: sentTo('/api/workflow/execute') && sentTo('/api/workflow/execute').resume_run_id,
};

fresh();
addFlow();
answer = { ok: true };
requests.length = 0;
await pa.runsManager.restart('r9');
await drain();
out.free_restart = {
    urls: requests.map((r) => r.url),
    toasts: toasts.slice(),
    discarded: sentTo('/api/runs/discard') && sentTo('/api/runs/discard').run_id,
    startedWithoutResume: sentTo('/api/workflow/execute') && sentTo('/api/workflow/execute').resume_run_id,
};

/* A declined confirmation sends nothing at all. */
fresh();
answers.confirm = false;
requests.length = 0;
await pa.runsManager.restart('r9');
out.restart_declined = { requested: requests.length };

fresh();
answers.confirm = false;
requests.length = 0;
await pa.runsManager.remove('r9', true);
out.remove_declined = { requested: requests.length };

/* An interrupted run is discarded (claims included); a finished one is deleted. */
fresh();
answers.confirm = true;
answer = { ok: true };
requests.length = 0;
await pa.runsManager.remove('r9', true);
out.remove_resumable = { url: requests[0].url, toast: toasts[0] };
fresh();
answers.confirm = true;
requests.length = 0;
await pa.runsManager.remove('r9', false);
out.remove_finished = { url: requests[0].url };
fresh();
route('/api/runs/delete', { ok: false, error: 'gone' });
route('/api/runs/discard', { ok: false, error: 'gone' });
requests.length = 0;
await pa.runsManager.remove('r9', false);
out.remove_refused_by_server = { toasts: toasts.slice() };

/* the per-node breakdown */
fresh();
/* The detail row toggles on "does my row already exist", and the stub's
   getElementById invents any id — so declare it absent first, exactly as a freshly
   rendered table has it. */
doc.absent.add('runs-mgr-detail-r1');
answer = {
    ok: true,
    run: {
        run_id: 'r1',
        nodes: [
            { node_id: 'node-1', node_type: 'source', status: 'done', row_count: 10 },
            { node_id: 'node-2', node_type: 'process', status: 'partial', row_count: 3 },
            { node_id: 'node-3', node_type: 'output', status: 'skipped', row_count: 0 },
            { node_id: 'node-4', node_type: 'misc', status: 'unknown-vocabulary', row_count: 0 },
        ],
    },
};
const row = doc.createElement('tr');
const button = doc.createElement('button');
button.closest = (sel) => (sel === 'tr' ? row : null);
row.appendChild(button);
await pa.runsManager.detail('r1', button);
const detail = doc.registry.get('runs-mgr-detail-r1');
out.detail_opened = {
    present: !!detail,
    cards: detail ? detail.children.length : 0,
    /* The node names come out of other people's pages, so the row has to be text. */
    escaped: detail ? detail.innerHTML.indexOf('<script') < 0 : false,
    kinds: detail ? Array.from(detail._classes).concat(detail.children.map((c) => c.className)) : [],
    requested: requests.map((r) => r.url),
};
doc.absent.delete('runs-mgr-detail-r1');
const fetchesBefore = requests.filter((r) => r.url.indexOf('/api/runs/') === 0).length;
await pa.runsManager.detail('r1', button);
/* The toggle's contract is "close what is open, without asking the server again".
   (The element stays in the stub's id registry after remove() — the assertion is
   the missing second fetch, which is what the user can observe.) */
out.detail_toggles = {
    refetched: requests.filter((r) => r.url.indexOf('/api/runs/') === 0).length - fetchesBefore,
};
fresh();
answer = { ok: false, error: 'nope' };
doc.absent.add('runs-mgr-detail-rX');
const row2 = doc.createElement('tr');
const btn2 = doc.createElement('button');
btn2.closest = () => row2;
await pa.runsManager.detail('rX', btn2);
out.detail_failure_adds_nothing = { present: !!doc.registry.get('runs-mgr-detail-rX') };

out.node_status_map = {
    done: pa.runsManager.nodeStatusInfo('done'),
    restored: pa.runsManager.nodeStatusInfo('restored'),
    partial: pa.runsManager.nodeStatusInfo('partial'),
    skipped: pa.runsManager.nodeStatusInfo('skipped'),
    failed: pa.runsManager.nodeStatusInfo('failed'),
    running: pa.runsManager.nodeStatusInfo('running'),
    /* A status the front end has never heard of must not render as success. */
    mystery: pa.runsManager.nodeStatusInfo('mystery-vocabulary'),
    empty: pa.runsManager.nodeStatusInfo(''),
};

/* ── exports panel ─────────────────────────────────────────────────── */
fresh();
pa.exportsManager.download('a b.csv');
const frame = doc.body.children[doc.body.children.length - 1];
out.export_download = {
    tag: frame.tagName,
    src: decodeURIComponent(frame.src),
    hidden: frame.style.display,
};
fresh();
pa.exportsManager.view('报告.html');
out.export_view = { url: decodeURIComponent(opened[0]), isDownload: opened[0].indexOf('/api/exports/download') >= 0 };
fresh();
answer = { ok: true };
requests.length = 0;
await pa.exportsManager.remove('a.csv');
out.export_remove = { url: requests[0].url, body: JSON.parse(requests[0].body), refreshed: requests.length };
fresh();
answers.confirm = false;
requests.length = 0;
await pa.exportsManager.remove('a.csv');
out.export_remove_declined = { requested: requests.length };
fresh();
route('/api/exports/delete', { ok: false, error: 'gone' });
await pa.exportsManager.remove('a.csv');
out.export_remove_refused = { toasts: toasts.slice() };
out.export_sizing = {
    bytes: pa.exportsManager.size(512),
    kilobytes: pa.exportsManager.size(2048),
    megabytes: pa.exportsManager.size(3 * 1024 * 1024),
    missing: pa.exportsManager.size(undefined),
};
out.export_quoting = {
    quote: pa.exportsManager._quote("it's a \\ test"),
    roundTripSafe: pa.exportsManager._quote("it's") === "it\\'s",
};

/* ── dataset panel ─────────────────────────────────────────────────── */
fresh();
answers.dialog = '新名字';
answer = { ok: true };
requests.length = 0;
await pa.datasetManager.rename('ds1', 'old.csv');
out.dataset_renamed = {
    url: requests[0].url,
    body: JSON.parse(requests[0].body),
    toasts: toasts.slice(),
    specs: dialogSpecs.slice(),
};
fresh();
answers.dialog = null;
requests.length = 0;
await pa.datasetManager.rename('ds1', 'old.csv');
out.dataset_rename_cancelled = { requested: requests.length };
fresh();
answers.dialog = 'x';
answer = { ok: false, error: 'name taken' };
requests.length = 0;
await pa.datasetManager.rename('ds1', 'old.csv');
out.dataset_rename_refused = { toasts: toasts.slice() };
fresh();
requests.length = 0;
await pa.datasetManager.remove('ds1', 'old.csv', true);
out.dataset_remove_blocked_locally = { requested: requests.length, toasts: toasts.slice() };
fresh();
answers.dialog = true;
answer = { ok: true };
requests.length = 0;
await pa.datasetManager.remove('ds1', 'old.csv', false);
out.dataset_removed = { method: requests[0].method, url: requests[0].url, toasts: toasts.slice() };
fresh();
answers.dialog = false;
requests.length = 0;
await pa.datasetManager.remove('ds1', 'old.csv', false);
out.dataset_remove_declined = { requested: requests.length };

/* ── processes panel ───────────────────────────────────────────────── */
fresh();
id('processes-panel').classList.add('open');
answer = {
    running: true,
    /* `ident` is what the Kill button posts, and the server sends it for every
       thread — leaving it out would render a dead button and blame the panel. */
    threads: [
        { name: 'MainThread', alive: true, daemon: false, ident: 1 },
        { name: 'run', alive: true, daemon: false, ident: 2 },
        { name: 'ThreadPoolExecutor-0_0', alive: true, daemon: true, ident: 3 },
        { name: 'selenium-idle', alive: false, daemon: true, ident: 4 },
    ],
    active_crawlers: 2,
    executor_pool_alive: true,
};
requests.length = 0;
pa.processesPoll();
await new Promise((resolve) => setImmediate(resolve));
const proc = id('processes-output');
out.processes = {
    fetched: requests.map((r) => r.url),
    html: proc.innerHTML,
    mentionsEveryThread: ['MainThread', 'run', 'ThreadPoolExecutor-0_0', 'selenium-idle'].every((name) => proc.innerHTML.indexOf(name) >= 0),
    /* MainThread and the run thread are never killable: taking them down takes the
       server with them. */
    killButtons: (proc.innerHTML.match(/killProcess/g) || []).length,
};
fresh();
id('processes-panel');
requests.length = 0;
pa.processesPoll();
await new Promise((resolve) => setImmediate(resolve));
out.processes_closed_panel_fetches_nothing = { requested: requests.length };

fresh();
answer = { ok: true, message: 'killed' };
requests.length = 0;
const killBtn = doc.createElement('button');
killBtn.dataset.ident = '12345';
pa.killProcess(killBtn);
await new Promise((resolve) => setImmediate(resolve));
out.kill = { url: requests[0].url, method: requests[0].method, body: JSON.parse(requests[0].body), toasts: toasts.slice() };
fresh();
requests.length = 0;
const noIdent = doc.createElement('button');
noIdent.dataset.ident = '';
pa.killProcess(noIdent);
out.kill_without_ident = { requested: requests.length };
fresh();
route('/api/workflow/processes/kill', { ok: false, error: 'permission denied' });
toasts.length = 0;
const denied = doc.createElement('button');
denied.dataset.ident = '9';
pa.killProcess(denied);
await new Promise((resolve) => setImmediate(resolve));
out.kill_refused = { toasts: toasts.slice() };

/* ── top bar writes ────────────────────────────────────────────────── */
fresh();
/* In the browser the bar and its button carry the class together; toggling one
   without the other would make the second press look broken. */
id('top-menu').classList.add('pinned');
id('pin-btn').classList.add('pinned');
pa.canvas.init();
pa.togglePin();
out.unpinned = {
    menuPinned: id('top-menu').classList.contains('pinned'),
    buttonPinned: id('pin-btn').classList.contains('pinned'),
    aria: id('pin-btn').getAttribute('aria-pressed'),
    draft: JSON.parse(sandbox.localStorage.getItem('crawler_settings')).menuPinned,
};
pa.togglePin();
out.repinned = {
    aria: id('pin-btn').getAttribute('aria-pressed'),
    menuPinned: id('top-menu').classList.contains('pinned'),
    buttonPinned: id('pin-btn').classList.contains('pinned'),
};

fresh();
const swatchA = doc.createElement('span');
swatchA.className = 'bar-bg-dot active';
swatchA.dataset.bg = 'bg-grid';
const swatchB = doc.createElement('span');
swatchB.className = 'bar-bg-dot';
swatchB.dataset.bg = 'bg-dots';
doc.body.appendChild(swatchA);
doc.body.appendChild(swatchB);
doc.body.classList.add('bg-grid');
pa.canvas.init();
pa.setBg('bg-dots', swatchB);
out.background_switched = {
    bodyClasses: Array.from(doc.body._classes).filter((c) => c.startsWith('bg-')),
    previousCleared: swatchA.classList.contains('active') === false,
    nowMarked: swatchB.classList.contains('active'),
    draft: JSON.parse(sandbox.localStorage.getItem('crawler_settings')).bg,
};

fresh();
pa.canvas.init();
const nodeForLabel = pa.canvas.addNode('source', 0, 0);
doc.body.dataset.lang = 'zh';
pa.setLang('en');
await new Promise((resolve) => setImmediate(resolve));
out.language_switched = {
    tag: doc.body.dataset.lang,
    toasts: toasts.slice(),
    draft: JSON.parse(sandbox.localStorage.getItem('crawler_settings')).lang,
    stampedNodes: Object.keys(pa.canvas.nodes).length,
    nodeLabel: pa.canvas.nodes[nodeForLabel] ? pa.canvas.nodes[nodeForLabel].el.querySelector('.node-title').textContent : '',
};
doc.body.dataset.lang = 'zh';
pa.setLang('zh');
out.language_back = { tag: doc.body.dataset.lang };

/* ── execution history: delete one recorded run ─────────────────────────
   The panel used to offer only 清空历史, so removing one bad run cost the
   whole comparison chart. A row's button now decides: which id is sent, whether
   a decline sends nothing, and what the toast says when the server reports
   that the run was already gone. */
const HISTORY_RUNS = {
    ok: true,
    runs: [
        { run_id: 'r-keep', workflow_name: '甲流程', started_at: '2026-09-24T01:00:00', metric_count: 3 },
        { run_id: 'r-del', workflow_name: '乙流程', started_at: '2026-09-24T02:00:00', metric_count: 2 },
    ],
    workflow_names: ['甲流程', '乙流程'],
};
fresh();
route('/api/history/runs', HISTORY_RUNS);
route('/api/history/series', { ok: true, rows: [] });
pa.historyPanel._renderChart = () => {}; // the chart is stats.js, not this decision
await pa.historyPanel._loadRuns();
const wrap = id('history-runs-wrap');
out.history_rows = {
    buttons: (wrap.innerHTML.match(/history-del/g) || []).length,
    // The id sits in an attribute built by string concatenation, so a quote in it
    // would end the attribute and let the rest become markup.
    ids: (wrap.innerHTML.match(/data-run-id="([^"]*)"/g) || []),
    label: vm.runInContext("I18n.t('history.remove')", sandbox),
    reloads: requests.length,
};

fresh();
route('/api/history/runs', HISTORY_RUNS);
route('/api/history/series', { ok: true, rows: [] });
answers.dialog = false; // 「取消」
await pa.historyPanel.deleteRun('r-del');
out.history_declined = { requested: requests.length, toasts: toasts.slice() };

fresh();
route('/api/history/runs', HISTORY_RUNS);
route('/api/history/series', { ok: true, rows: [] });
route('/api/history/delete', { ok: true, deleted: 2, run_id: 'r-del' });
answers.dialog = true;
await pa.historyPanel.deleteRun('r-del');
const delPost = requests.find((r) => r.url.indexOf('/api/history/delete') === 0);
out.history_deleted = {
    method: delPost ? delPost.method : null,
    body: delPost ? JSON.parse(delPost.body) : null,
    askedMessage: answers.spec ? answers.spec.message : null,
    reloadedRuns: requests.filter((r) => r.url.indexOf('/api/history/runs') === 0).length,
    reloadedSeries: requests.filter((r) => r.url.indexOf('/api/history/series') === 0).length,
    toasts: toasts.slice(),
};

fresh();
route('/api/history/runs', HISTORY_RUNS);
route('/api/history/series', { ok: true, rows: [] });
route('/api/history/delete', { ok: true, deleted: 0, run_id: 'r-aged' });
answers.dialog = true;
await pa.historyPanel.deleteRun('r-aged');
out.history_already_gone = { toasts: toasts.slice() };

fresh();
route('/api/history/runs', HISTORY_RUNS);
route('/api/history/series', { ok: true, rows: [] });
route('/api/history/delete', { ok: false, error: 'no run id given' });
answers.dialog = true;
await pa.historyPanel.deleteRun('r-x');
out.history_refused = {
    toasts: toasts.slice(),
    // A refusal must not leave the panel showing a row the server says is still there
    // — but it also must not pretend to have refreshed anything.
    reloaded: requests.filter((r) => r.url.indexOf('/api/history/runs') === 0).length,
};

fresh();
answers.dialog = true;
route('/api/history/delete', { ok: true, deleted: 1 });
await pa.historyPanel.deleteRun('   ');
out.history_blank_id = { requested: requests.length };

/* ── one press, one toast ────────────────────────────────────────────── */
/* Two source nodes with nothing typed in: the validator has two separate things to
   say, and the user has to hear both. Looping `showToast` over them printed only the
   last (one element, text replaced each time), so a canvas with N problems needed N
   presses of 执行 to discover them one at a time. */
fresh();
addCanvasNode('source', { platform: 'zhihu', collect: 'posts', keyword: '' });
addCanvasNode('source', { platform: 'weibo', collect: 'posts', keyword: '' });
requests.length = 0;
await pa.workflow.execute();
await drain();
out.two_problems_one_toast = {
    toasts: toasts.slice(),
    started: requests.filter((r) => r.url.indexOf('/api/workflow/execute') === 0).length,
};

/* The same button on a canvas with exactly ONE problem: the list header would be
   scaffolding around a sentence that already names the node. */
fresh();
addCanvasNode('output', { operation: 'save', format: 'csv', filename: 'a.csv' });
requests.length = 0;
await pa.workflow.execute();
await drain();
out.one_problem_plain_toast = { toasts: toasts.slice() };

/* ── the language switch must reach the tables that JS builds ──────────── */
/* Both panels write their header row from the catalogue in JS, so `I18n.apply()`
   re-stamps the static page around them and leaves the table in the old language
   until the panel is closed and opened again — the headers and every status word in
   the row are catalogue text, so half the UI kept speaking the previous language. */
fresh();
route('/api/data/datasets', {
    ok: true,
    datasets: [
        { id: 'd1', name: 'a.csv', source: 'upload', row_count: 3, column_count: 2, size_bytes: 1234, used_by: [] },
    ],
});
route('/api/history/runs', HISTORY_RUNS);
route('/api/history/series', { ok: true, rows: [] });
id('dataset-panel').classList.add('open');
id('history-panel').classList.add('open');
sandbox.setLang('zh');
await pa.datasetManager.refresh();
await pa.historyPanel._loadRuns();
const builtinHeaders = () => ({
    /* `innerHTML` is the string the product assigned (the stub keeps it verbatim and
       also parses it into children); `textContent` does not aggregate children. */
    dataset: id('dataset-mgr-body').innerHTML,
    history: id('history-runs-wrap').innerHTML,
});
const beforeFlip = builtinHeaders();
sandbox.setLang('en');
await drain();
out.language_reaches_builtin_tables = { before: beforeFlip, after: builtinHeaders() };

process.stdout.write(JSON.stringify(out));
