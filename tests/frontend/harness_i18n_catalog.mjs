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
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const jsDir = process.argv[2];
const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);

/* The page's own load order, not a list kept here: the catalogue is app.js's remainder merged with
   every js/i18n/<domain>.js, and a private list would report the moved half as missing words. */
loadPageScripts(sandbox, { jsDir, only: ['custom-select.js', 'workflow.js', 'app.js'] });

process.stdout.write(
    JSON.stringify({
        en: vm.runInContext('I18n.dict.en', sandbox),
        zh: vm.runInContext('I18n.dict.zh', sandbox),
    })
);
