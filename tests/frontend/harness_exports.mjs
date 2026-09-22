/* Renders the export-artefact table with the REAL exportsManager (workflow.js).
 *
 * This panel is the one place a filename is both shown and handed back to the
 * server, so the things worth pinning are: a `.py` in the export folder gets no
 * download button (the backend refuses it too — the rule must not live only in
 * the UI), a name carrying a quote or a backslash must survive both the HTML
 * attribute and the JS string literal it is embedded in, sizes must be human
 * readable, and an empty folder must read as empty rather than as an error.
 *
 * Usage: node harness_exports.mjs <workflow.js> <exports.json>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox } from './harness_dom.mjs';

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
            'exportsMgr.remove': 'Delete',
            'exportsMgr.loadFailed': 'LOADFAILED',
        },
        zh: {},
    },
    t(k) {
        return this.dict.en[k] || k;
    },
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas: { nodes: {}, connections: [] },
    RunState: { running: false },
    showToast: () => {},
    fetch: () => Promise.resolve({ json: () => Promise.resolve(payload) }),
    setTimeout: () => {},
    encodeURIComponent: (value) => `ENC(${value})`,
};
vm.createContext(sandbox);
vm.runInContext(src + '\n;globalThis.__ex = { exportsManager };', sandbox);
const { exportsManager } = sandbox.__ex;

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
process.stdout.write(JSON.stringify(out));
