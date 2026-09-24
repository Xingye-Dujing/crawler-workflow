/* Renders the export-artefact table with the REAL exportsManager (workflow.js).
 *
 * This panel is the one place a filename is both shown and handed back to the
 * server, so the things worth pinning are: a `.py` in the export folder gets no
 * download button (the backend refuses it too — the rule must not live only in
 * the UI), a name carrying a quote or a backslash must survive both the HTML
 * attribute and the JS string literal it is embedded in, sizes must be human
 * readable, and an empty folder must read as empty rather than as an error.
 *
 * The 生成报告 button is driven here too, because what it decides is what gets
 * POSTed: the dialog's three outcomes (create / create with the AI paragraph /
 * cancel) have to produce two different payloads and one request fewer.
 *
 * Usage: node harness_exports.mjs <workflow.js> <exports.json>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const src = fs.readFileSync(process.argv[2], 'utf8');
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const I18n = {
    lang: 'en',
    dict: {
        en: {
            'exportsMgr.empty': 'EMPTY',
            'exportsMgr.summary': '{files} file(s), {size} in total',
            'exportsMgr.colName': 'File',
            'exportsMgr.colKind': 'Kind',
            'exportsMgr.colSize': 'Size',
            'exportsMgr.colModified': 'Modified',
            'exportsMgr.download': 'Download',
            'exportsMgr.view': 'VIEW',
            'exportsMgr.report': 'REPORT',
            'exportsMgr.reportHint': 'HINT',
            'exportsMgr.reportPlaceholder': 'PLACEHOLDER',
            'exportsMgr.reportGo': 'CREATE',
            'exportsMgr.reportAi': 'CREATE-AI',
            'exportsMgr.reportDone': 'DONE',
            'exportsMgr.reportFailed': 'FAILED',
            'exportsMgr.remove': 'Delete',
            'exportsMgr.confirmRemove': 'CONFIRM-REMOVE',
            'exportsMgr.removeDone': 'DELETED',
            'exportsMgr.removeFailed': 'DELETEFAILED',
            'exportsMgr.loadFailed': 'LOADFAILED',
            'dialog.cancel': 'CANCEL',
        },
        zh: {},
    },
    t(k) {
        return this.dict.en[k] || k;
    },
};

/* Everything the report button touches that is not workflow.js's own logic.
   The dialog answer is set per scenario, because the same method has to be
   proven to distinguish "create", "create with the AI paragraph" and "cancel". */
const captured = { dialogs: [], posts: [], opens: [], toasts: [] };
const dialogAnswer = { value: null };

const sandbox = baseSandbox();
/* In this DOM stub ``window`` *is* the sandbox object, so the globals the report
   button reaches for have to be assigned onto that same object — spreading it
   into a new one would leave ``window`` pointing at the original and
   ``window.open`` would be undefined inside the script. */
Object.assign(sandbox, {
    I18n,
    canvas: { nodes: {}, connections: [] },
    RunState: { running: false },
    fetch: (url, options) => {
        const body = options && options.body ? JSON.parse(options.body) : null;
        if (body) {
            captured.posts.push({ url, method: options.method, lang: options.headers['X-Lang'], body });
        }
        const answer =
            body
                ? { ok: true, name: 'report-x.html' }
                : { ok: true, exports: payload.exports, files: payload.files, bytes: payload.bytes };
        return Promise.resolve({ json: () => Promise.resolve(answer) });
    },
    setTimeout: () => {},
    encodeURIComponent: (value) => `ENC(${value})`,
    open: (url) => captured.opens.push(url),
    confirm: () => true,
    LLMSettings: { payload: () => ({ provider: 'ollama', model: 'm', api_key: '' }) },
});
vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__ex = { exportsManager };', sandbox);
const { exportsManager } = sandbox.__ex;
/* Assigned after the script ran: workflow.js declares showToast and showDialog
   itself, and a function declaration in the script wins over anything seeded
   into the context beforehand. The two are what this harness observes. */
sandbox.showToast = (msg) => captured.toasts.push(String(msg));
sandbox.showDialog = (opts) => {
    captured.dialogs.push(opts);
    return Promise.resolve(dialogAnswer.value);
};

exportsManager._last = payload.exports;
exportsManager._totals = { files: payload.files, bytes: payload.bytes };
exportsManager.render();

const html = sandbox.__byId('exports-mgr-body').innerHTML;
const out = {
    html,
    rows: (html.match(/<tr>/g) || []).length,
    downloads: (html.match(/exportsManager\.download\(/g) || []).length,
    deletes: (html.match(/exportsManager\.remove\(/g) || []).length,
    size: [
        exportsManager.size(0),
        exportsManager.size(999),
        exportsManager.size(2048),
        exportsManager.size(5 * 1024 * 1024),
    ],
    quoted: [
        exportsManager._quote("it's.csv"),
        exportsManager._quote('back\\slash.csv'),
        exportsManager._quote('a"b.csv'),
    ],
};
/* The empty-state path, rendered after the populated one so the two do not
   share a fixture. */
exportsManager._last = [];
exportsManager.render();
out.empty = sandbox.__byId('exports-mgr-body').innerHTML;
out.dlHref = '/api/exports/download?name=' + sandbox.encodeURIComponent("it's.csv");
/* A report row offers 查看 and not 下载: the file is .html and the download
   route refuses that extension, so a download button here would be a dead end. */
out.views = (html.match(/exportsManager\.view\(/g) || []).length;

/* ── the report button ─────────────────────────────────────────
   Three different outcomes of one dialog: create, create-with-AI, cancel. The
   first two must send different payloads; the third must send nothing at all. */
sandbox.canvas.nodes = {
    'node-1': { id: 'node-1', type: 'source', title: '数据源', params: {} },
    'node-2': { id: 'node-2', type: 'output', title: '', params: {} },
};

dialogAnswer.value = { value: 'ai', input: '  季度报告  ' };
await exportsManager.report();
dialogAnswer.value = { value: 'go', input: '' };
await exportsManager.report('run-7', 'stored name');
dialogAnswer.value = null;
await exportsManager.report();

out.dialogs = captured.dialogs.map((opts) => ({
    buttons: (opts.buttons || []).map((b) => [b.label, b.value, !!b.withInput]),
    hasInput: !!opts.input,
}));
out.posts = captured.posts.slice();
out.opens = captured.opens.slice();
out.toasts = captured.toasts.slice();

/* ── deleting a file: the app's own dialog decides, and only 删除 sends ─────
   This used to be `window.confirm`, which cannot be translated, cannot be
   styled with the page, and answers with a bare boolean that hides what is
   about to be lost. It runs last and reports its own slices, so the report
   assertions above keep seeing only what the report button did. */
const triples = (opts) =>
    opts && opts.buttons ? opts.buttons.map((b) => [b.label, b.value === undefined ? null : b.value, !!b.withInput]) : null;
const postsBefore = captured.posts.length;
const toastsBefore = captured.toasts.length;
const dialogsBefore = captured.dialogs.length;

dialogAnswer.value = null;
await exportsManager.remove("it's.csv");
out.cancelledPosts = captured.posts.slice(postsBefore);
out.cancelledDialog = triples(captured.dialogs[dialogsBefore]);

dialogAnswer.value = 'go';
await exportsManager.remove('ok.csv');
out.deletedPosts = captured.posts.slice(postsBefore + out.cancelledPosts.length);
out.deletedDialog = triples(captured.dialogs[dialogsBefore + 1]);
out.deletedToasts = captured.toasts.slice(toastsBefore + out.cancelledPosts.length);

process.stdout.write(JSON.stringify(out));
