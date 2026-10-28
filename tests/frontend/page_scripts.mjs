/* Load the page's own scripts, in the order index.html declares them.
 *
 * Every harness used to keep its own list of files, which is a second opinion about
 * the page: after a module was split out of workflow.js, a harness that named only
 * `workflow.js` kept passing while the shipped page had one more file it never ran.
 * The browser has exactly one load order — the `<script src="/js/…">` tags — and that
 * is what this module reads, so splitting a module costs no harness edit.
 *
 * Scripts are evaluated one call at a time, like real script tags: top-level `var`
 * and `function` become context globals, and top-level `const`/`let` land in the
 * context's shared global lexical environment (measured: a later script sees them),
 * which is the browser's behaviour too. Concatenating the files would additionally
 * leak one file's `'use strict'` into the next, so it is deliberately not done.
 *
 * `only` names the files a focused scenario wants; it is checked against the page,
 * so a harness asking for a file the page no longer loads fails by name instead of
 * quietly measuring a subset nobody ships.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO = join(HERE, '..', '..');
export const STATIC_DIR = join(REPO, 'backend', 'static');
export const JS_DIR = join(STATIC_DIR, 'js');
export const INDEX_HTML = join(STATIC_DIR, 'index.html');
/** Where the per-domain message catalogues live, relative to `js/` (see app.js's merge). */
export const CATALOGUE_DIR = 'i18n';

/** The `/js/*.js` names index.html loads, in page order (vendor bundles excluded). */
export function pageScriptNames(indexHtml = INDEX_HTML) {
    const markup = readFileSync(indexHtml, 'utf8');
    const names = Array.from(markup.matchAll(/<script\b[^>]*\bsrc="\/js\/([^"]+)"/g), (m) => m[1]);
    if (!names.length) throw new Error(`no <script src="/js/…"> found in ${indexHtml}`);
    return names;
}

/**
 * Run the page's scripts into `sandbox`, in page order.
 *
 * Returns the names actually evaluated, so a harness can prove it loaded what it
 * meant to (and print the list when a scenario depends on one module).
 */
export function loadPageScripts(sandbox, options = {}) {
    const jsDir = options.jsDir || JS_DIR;
    const names = pageScriptNames(options.indexHtml || INDEX_HTML);
    let only = options.only ? new Set(options.only) : null;
    if (only) {
        const unknown = Array.from(only).filter((name) => !names.includes(name));
        if (unknown.length) {
            throw new Error(
                `index.html does not load ${unknown.join(', ')} — a harness may only name files the page ships`
            );
        }
        /* app.js without the catalogue files is an app with no words: every t() would echo its
           key and a text assertion would pass on an empty string somewhere else. The catalogue is
           app.js's DATA, split out for file size, so selecting app.js selects it too — one rule in
           the loader rather than a list every harness has to remember (and a harness that does
           name them is harmless: a Set). */
        if (only.has('app.js')) {
            for (const name of names) if (name.startsWith(`${CATALOGUE_DIR}/`)) only.add(name);
        }
    }
    const loaded = [];
    for (const name of names) {
        if (only && !only.has(name)) continue;
        vm.runInContext(readFileSync(join(jsDir, name), 'utf8'), sandbox, { filename: name });
        loaded.push(name);
    }
    if (!loaded.length) throw new Error('loadPageScripts selected no files');
    return loaded;
}
