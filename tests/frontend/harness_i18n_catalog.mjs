/* Prints the REAL browser catalog (backend/static/js/app.js) as JSON, both languages.
 *
 * The placeholder guards for the Python catalogue read `backend/i18n.py` with `ast`;
 * nothing has ever looked at the JS side, which is how a dialog that names the platform
 * TWICE was filled by `.replace('{platform}', …)` — a string needle replaces the first
 * occurrence only, so the user read a literal `{platform}` inside a Chinese sentence,
 * beside an untranslated `zhihu`. Parsing the catalog from Python would mean re-guessing
 * JS string escapes; loading the file the browser loads means the guard reads the same
 * text the user sees.
 *
 * Usage: node harness_i18n_catalog.mjs <jsDir>
 * Prints {"en": {key: template}, "zh": {key: template}}.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const jsDir = process.argv[2];
const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);

/* The same load order index.html uses: app.js's catalog is read at call time by the
   helpers defined in workflow.js, and a missing global at load time would skip the
   whole suite rather than report a catalogue. */
for (const f of ['custom-select.js', 'workflow.js', 'app.js']) {
    vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f });
}

process.stdout.write(
    JSON.stringify({
        en: vm.runInContext('I18n.dict.en', sandbox),
        zh: vm.runInContext('I18n.dict.zh', sandbox),
    })
);
