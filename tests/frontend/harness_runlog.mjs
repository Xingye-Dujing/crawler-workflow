/* Drives the REAL runLogViewer (workflow.js) against the durable /api/runs/<id>/log endpoints.

   The live console is wiped when the next run starts and only ships a 200-line tail, so the
   whole point of this feature is the AFTER-the-fact read. What has to hold, and is checked
   here on the shipped code (not a mirror):

   - opening pulls a page of the persisted log and renders it oldest→newest, escaping every
     line (a saved traceback is data, never markup);
   - the three filters (level / workflow / search) go into the fetch URL, and 「加载更早」
     walks backward from the smallest seq already shown;
   - 「下载 .txt」 points the browser at the SAME filtered download endpoint;
   - the run-records row grew a 「查看运行日志」 button that carries only the run id (a
     workflow name is user text — a quote in it must not be able to close the handler).

   Usage: node harness_runlog.mjs <workflow.js>
*/
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow, dispatchOn } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');

const PAGE = {
    ok: true,
    has_more: true,
    min_seq: 2,
    max_seq: 3,
    rows: [
        { seq: 2, ts: '2026-10-06T04:00:02', wf_idx: 0, wf_name: '微博', level: 'info', line: 'hello <b>x</b>' },
        { seq: 3, ts: '2026-10-06T04:00:03', wf_idx: 1, wf_name: '知乎', level: 'error', line: '抓取失败' },
    ],
};
const OLDER = {
    ok: true,
    has_more: false,
    min_seq: 0,
    max_seq: 1,
    rows: [
        { seq: 0, ts: '2026-10-06T04:00:00', wf_idx: 0, wf_name: '微博', level: 'info', line: 'older-1' },
        { seq: 1, ts: '2026-10-06T04:00:01', wf_idx: 0, wf_name: '微博', level: 'warning', line: '慢' },
    ],
};

const captured = { gets: [], location: '' };
const sandbox = {
    ...baseSandbox(),
    I18n: {
        lang: 'en',
        dict: { en: {}, zh: {} },
        t(k) {
            return k;
        },
    },
    runsManager: null,
};
sandbox.fetch = (url) => {
    const u = String(url);
    captured.gets.push(u);
    let payload = { ok: true, rows: [], has_more: false, min_seq: null, max_seq: null };
    if (u.indexOf('/log?') >= 0 || u.indexOf('/log') >= 0) {
        payload = u.indexOf('before=') >= 0 ? OLDER : PAGE;
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(payload) });
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__wf = { runsManager, runLogViewer };', sandbox);
sandbox.location = { set href(v) { captured.location = v; }, get href() { return captured.location; } };

const viewer = sandbox.__wf.runLogViewer;

const out = {};

// ── opening pulls a page and renders it escaped, oldest→newest ──
viewer.open('r1');
await new Promise((r) => setImmediate(r)); // open() arms the panel then fires load() (unawaited)
out.firstGet = captured.gets[0] || '';
out.firstHasLimit = (captured.gets[0] || '').indexOf('limit=500') >= 0;
out.bodyHtml = viewer._dom.body.innerHTML || '';
out.escapedLine = out.bodyHtml.indexOf('&lt;b&gt;') >= 0 && out.bodyHtml.indexOf('<b>') < 0;
out.lineOrderAfterOpen = (out.bodyHtml.match(/hello|抓取失败/g) || []).length;
out.errorClassShown = out.bodyHtml.indexOf('lvl-error') >= 0;

// ── level filter travels into the request ──
const beforeLevel = captured.gets.length;
viewer._dom.level.value = 'error';
dispatchOn(viewer._dom.level, 'change');
await new Promise((r) => setImmediate(r));
out.levelGet = captured.gets.slice(beforeLevel).find((u) => u.indexOf('level=error') >= 0) || '';

// ── workflow filter: options were populated from the loaded rows ──
out.wfOptions = viewer._dom.wf.querySelectorAll('option').map((o) => o.value);
const beforeWf = captured.gets.length;
viewer._dom.wf.value = '1';
dispatchOn(viewer._dom.wf, 'change');
await new Promise((r) => setImmediate(r));
out.wfGet = captured.gets.slice(beforeWf).find((u) => u.indexOf('wf=1') >= 0) || '';

// ── search: Enter in the box is the filter action ──
const beforeQ = captured.gets.length;
viewer._dom.search.value = '三亚';
dispatchOn(viewer._dom.search, 'keydown', { key: 'Enter' });
await new Promise((r) => setImmediate(r));
out.qGet = captured.gets.slice(beforeQ).find((u) => u.indexOf('q=%E4%B8%89%E4%BA%9A') >= 0) || '';

// ── 「加载更早」 walks back from the smallest seq already shown ──
const beforeOlder = captured.gets.length;
viewer._rows = PAGE.rows.slice();
viewer._oldestSeq = 2;
viewer._hasMore = true;
await viewer.loadOlder();
out.olderGet = captured.gets.slice(beforeOlder).find((u) => u.indexOf('before=2') >= 0) || '';
out.mergedOrder = viewer._rows.map((r) => r.line);

// ── download points at the same filtered .txt endpoint ──
viewer._dom.level.value = 'warning';
captured.location = '';
viewer.download();
out.downloadUrl = captured.location;

// ── close hides the overlay without tearing it down ──
viewer._dom.overlay.classList.add('open');
viewer.close();
out.closed = !viewer._dom.overlay.classList.contains('open');

// ── the run-records row grew a viewer button carrying only the id ──
const mgr = sandbox.__wf.runsManager;
mgr._queue = [];
sandbox.__byId('runs-mgr-body').innerHTML = '';
mgr.render([
    {
        run_id: 'rZ',
        workflow_name: '名"称',
        status: 'completed',
        node_done: 1,
        node_total: 1,
        rows_kept: 0,
        wf_count: 1,
        mode: 'serial',
        headless: 1,
    },
]);
const rowHtml = sandbox.__byId('runs-mgr-body').innerHTML || '';
out.hasLogButton = rowHtml.indexOf('runLogViewer.open(') >= 0;
out.buttonCarriesId = /runLogViewer\.open\('rZ'\)/.test(rowHtml);
out.nameNotInHandler = rowHtml.indexOf('名"称') >= 0 ? /onclick="[^"]*名/.test(rowHtml) === false : true;

process.stdout.write(JSON.stringify(out));
