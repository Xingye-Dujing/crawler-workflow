/* Renders the workflow-file table with the REAL wfFiles.render (workflow.js).

   This panel is the only way to reach a saved canvas by name, so two things have
   to hold on screen and not in the request: the row for the canvas the user is
   editing says 当前, and a stem the user typed (quotes, backslashes, angle
   brackets) neither breaks the delegated button nor reaches the DOM as a tag.
   A broken file keeps its 删除 button — a row that cannot be opened is exactly
   the row that has to be removable.

   Usage: node harness_wfmgr.mjs <workflow.js>
   Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { sourceOf } from './companions.mjs';

const src = sourceOf(process.argv[2]);

const DICT = {
    en: {
        'wfMgr.header': 'Workflows',
        'wfMgr.empty': 'EMPTY',
        'wfMgr.colName': 'Name',
        'wfMgr.colNodes': 'Nodes',
        'wfMgr.colModified': 'Modified',
        'wfMgr.current': 'open',
        'wfMgr.broken': 'unreadable',
        'wfMgr.open': 'Open',
        'wfMgr.copy': 'Copy',
        'wfMgr.copyDone': 'Copied to {name}',
        'wfMgr.copyFailed': 'Copy failed',
        'wfMgr.rename': 'Rename',
        'wfMgr.remove': 'Delete',
    },
    zh: {
        'wfMgr.empty': '空',
        'wfMgr.current': '当前',
        'wfMgr.broken': '已损坏',
        'wfMgr.open': '打开',
        'wfMgr.copy': '复制',
        'wfMgr.copyDone': '已复制为 {name}',
        'wfMgr.copyFailed': '复制失败',
        'wfMgr.rename': '重命名',
        'wfMgr.remove': '删除',
    },
};
const I18n = {
    lang: 'en',
    t(k) {
        return (DICT[this.lang] || {})[k] || DICT.en[k] || k;
    },
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    /* workflow.js reads these through `typeof`; the render path needs a canvas
       that exists but holds nothing, and a RunState that is not running. */
    RunState: { running: false },
};
vm.createContext(sandbox);
fixWindow(vm, sandbox);
/* canvas.js is not loaded here on purpose: `wfFiles.open()` guards its confirm on
   `typeof canvas !== 'undefined'`, and this harness is about what the table looks
   like, not about the dialog. The click paths live in harness_panel_actions.mjs. */
vm.runInContext(src + '\n;globalThis.__wf = { wfFiles, workflow };', sandbox);
sandbox.showToast = () => {};

const panel = sandbox.__byId('workflows-panel');
const body = sandbox.__byId('workflows-mgr-body');
const manager = sandbox.__wf.wfFiles;
const workflow = sandbox.__wf.workflow;

const ROWS = [
    { name: '日报', nodes: 3, labels: ['日报'], size: 1200, mtime: 1760000000, broken: false },
    { name: "it's <img src=x onerror=alert(1)>", nodes: 7, labels: [], size: 900, mtime: 1760003600, broken: false },
    { name: 'back\\slash', nodes: 1, labels: [], size: 10, mtime: 0, broken: true },
    /* A double quote is the character that closes a `onclick="…"` attribute, and
       `&` is the character that must not be escaped twice. */
    { name: 'q"uote & co', nodes: 2, labels: [], size: 5, mtime: 1760007200, broken: false },
];

function render(rows, current) {
    manager._last = rows;
    workflow.currentFile = current;
    manager.render();
    return body.innerHTML;
}

const out = {};

workflow.currentFile = '日报';
out.current = render(ROWS, '日报');
out.escaped = render(ROWS, '');
out.empty = render([], '');
out.noRowsKey = body.textContent.trim();

/* 修改时间 comes from the file's own mtime; 0 (an unknown stamp) must read as
   nothing rather than the 1970 epoch. */
out.when = {
    stamped: manager._when(1760000000),
    unknown: manager._when(0),
    garbage: manager._when('abc'),
};

/* A broken row is the one that must stay removable, and must not offer 打开 or 复制
   (there is no readable payload to duplicate). */
const brokenRow = out.current.split('</tr>').find((chunk) => chunk.indexOf('back') >= 0) || '';
out.brokenRow = {
    opens: brokenRow.indexOf("wfFiles.open(") >= 0,
    copies: brokenRow.indexOf('wfFiles.copy(') >= 0,
    renames: brokenRow.indexOf('wfFiles.rename(') >= 0,
    removes: brokenRow.indexOf('wfFiles.remove(') >= 0,
    chip: brokenRow.indexOf(I18n.t('wfMgr.broken')) >= 0,
};

/* The delegated call has to receive the stem unchanged: the escaper that turns a
   quote into an entity for the cell text would, if reused here, hand open() a
   different file name than the one on disk. */
const quotedRow = out.current.split('</tr>').find((chunk) => chunk.indexOf('onerror') >= 0) || '';
const ampRow = out.current.split('</tr>').find((chunk) => chunk.indexOf('q&quot;') >= 0) || '';
out.quotedRow = {
    /* `\\.` so an escaped quote does not end the capture, then undo both escape
       layers — the argument the click will hand open() must BE the file's stem. */
    openArg: ((quotedRow.match(/wfFiles\.open\('((?:[^'\\]|\\.)*)'/) || [null, null])[1] || '')
        .replace(/\\'/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, '&'),
    renames: quotedRow.indexOf('wfFiles.rename(') >= 0,
    /* An <img> inside a name must never reach the DOM as a tag. The stub parses
       innerHTML into real children, so a live element is observable here. */
    imgElement: sandbox.document.querySelectorAll('img').length > 0,
};
out.ampRow = {
    present: !!ampRow,
    /* One `&` in the name becomes exactly one `&amp;`. Escaping twice would make
       open() look for a file whose stem literally contains "&amp;amp;". */
    once: ampRow.indexOf('&amp;') >= 0 && ampRow.indexOf('&amp;amp;') < 0,
    /* The whole call has to sit inside ONE attribute. Truncated at the name's own
       quote, this regex stops matching — which is the bug this escaper exists for. */
    intact: /onclick="wfFiles\.open\('[^"]*q&quot;uote[^"]*'\)"/.test(ampRow),
};

/* A closed panel must not fetch on a language switch, and an open one must
   repaint from the rows it already has rather than re-read the disk. */
render(ROWS, '日报');
panel.classList.remove('open');
let fetches = 0;
sandbox.fetch = () => {
    fetches += 1;
    return Promise.resolve({ json: () => Promise.resolve({ ok: true, workflows: [] }), text: () => Promise.resolve('') });
};
I18n.lang = 'zh';
manager.onLanguageChange();
out.closedRepaints = { fetches, html: body.innerHTML };

panel.classList.add('open');
manager.onLanguageChange();
out.openRepaints = { fetches, currentChip: body.innerHTML.indexOf(DICT.zh['wfMgr.current']) >= 0 };

I18n.lang = 'en';
out.headers = render(ROWS, '').indexOf('Name') >= 0;

/* ── 复制: one POST, no question, no canvas change ────────────────────
   The action duplicates a saved file under the next free " (2)" name. It must ask
   nothing (a button that only ADDS a file has nothing to lose), must not open the
   copy over the canvas being edited, and must reload the list so the new row is
   there. A refused copy shows the server's own reason. */
const copyCalls = [];
let copyAnswer = { ok: true, name: '日报 (2)' };
sandbox.fetch = (url, opts) => {
    const path = String(url).split('?')[0];
    copyCalls.push({ url: path, method: (opts && opts.method) || 'GET', body: opts && opts.body });
    const answered =
        path === '/api/workflow/copy'
            ? copyAnswer
            : {
                  ok: true,
                  workflows: [
                      { name: '日报', nodes: 3, labels: [], size: 1200, mtime: 0, broken: false },
                      { name: '日报 (2)', nodes: 3, labels: [], size: 1200, mtime: 0, broken: false },
                  ],
              };
    const text = JSON.stringify(answered);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(answered), text: () => Promise.resolve(text) });
};
const copyToasts = [];
sandbox.showToast = (message) => copyToasts.push(String(message));
workflow.currentFile = '日报';
await manager.copy('日报');
out.copy = {
    url: copyCalls[0] && copyCalls[0].url,
    method: copyCalls[0] && copyCalls[0].method,
    body: copyCalls[0] ? JSON.parse(copyCalls[0].body) : null,
    toast: copyToasts[0],
    reloaded: copyCalls.some((call) => call.url === '/api/workflow/list'),
    rows: (manager._last || []).map((row) => row.name),
    currentFile: workflow.currentFile,
};

copyCalls.length = 0;
copyToasts.length = 0;
copyAnswer = { ok: false, error: 'LOCK-REFUSED' };
await manager.copy('locked');
out.copy_refused = { toast: copyToasts[0], reloaded: copyCalls.some((call) => call.url === '/api/workflow/list') };

copyCalls.length = 0;
copyToasts.length = 0;
copyAnswer = { ok: false };
await manager.copy('locked');
out.copy_failed_without_reason = { toast: copyToasts[0] };

process.stdout.write(JSON.stringify(out));
