/* Runs the REAL floating-popup logic (backend/static/js/app.js) under node.
 *
 * The outside-click guards for the dashboard/history popups are behaviour the
 * user asked for and cannot see from Python at all: which clicks count as
 * "outside", which must not (the panel itself, the sibling popup, a
 * CustomSelect menu rendered into <body>, a modal dialog). app.js registers
 * its document mousedown listeners at load; this harness loads the untouched
 * file, replays clicks, and reports which panels ended up closed.
 *
 * Usage: node harness_app.mjs <jsDir> <scenarios.json>
 * scenarios.json = [ { "id": "...", "open": ["dashboard-panel",...],
 *                      "ancestors": ["#history-panel", ...] } ]
 * Prints {id: {panel: isOpen}} for every floating panel.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow, makeTarget } from './harness_dom.mjs';

const jsDir = process.argv[2];
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);

/* Load order mirrors index.html: workflow.js defines closeSettings/showToast
   that app.js's click-away handlers call; app.js defines the I18n catalog
   those functions read at CALL time (never at load time). */
const FILES = ['custom-select.js', 'workflow.js', 'app.js'];
for (const f of FILES) {
    vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f });
}

const PANELS = ['dashboard-panel', 'history-panel', 'node-settings', 'cookie-dialog'];
const report = {};

/* One deep scenario: the REAL I18n catalog from app.js, checked at runtime.
   Key parity across languages, the other-language fallback for a gap, and the
   unknown-language path must all behave — the console text the user reads
   depends on it. */
for (const sc of scenarios) {
    if (sc.id === 'i18n-runtime') {
        const info = vm.runInContext(
            `(function () {
                const en = I18n.dict.en, zh = I18n.dict.zh;
                const onlyEn = Object.keys(en).filter((k) => !(k in zh)).sort();
                const onlyZh = Object.keys(zh).filter((k) => !(k in en)).sort();
                I18n.lang = 'zh';
                const zhUpload = I18n.t('palette.upload');
                I18n.lang = 'en';
                const enUpload = I18n.t('palette.upload');
                I18n.lang = 'de';  // a language nobody ships
                const fallback = I18n.t('palette.upload');
                const echo = I18n.t('totally.missing.key');
                I18n.lang = 'en';
                return { enCount: Object.keys(en).length, zhCount: Object.keys(zh).length,
                         onlyEn, onlyZh, zhUpload, enUpload, fallback, echo };
            })()`,
            sandbox,
        );
        report[sc.id] = info;
        continue;
    }
    for (const id of PANELS) {
        const el = sandbox.__byId(id);
        el.classList.remove('open');
    }
    for (const id of sc.open || []) sandbox.__byId(id).classList.add('open');
    const target = makeTarget(sc.ancestors || []);
    const handlers = sandbox.__handlers.document.mousedown || [];
    for (const fn of handlers) {
        fn({ type: 'mousedown', target, preventDefault() {}, stopPropagation() {} });
    }
    report[sc.id] = {};
    for (const id of PANELS) report[sc.id][id] = sandbox.__byId(id).classList.contains('open');
}
process.stdout.write(JSON.stringify(report));
