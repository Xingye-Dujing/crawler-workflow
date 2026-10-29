/* The modules a split-out module cannot do without.
 *
 * The page always ships both halves; a harness handed only the old file boots half a layer and dies
 * the first time the scenario asks the split-out half anything (measured 2026-10-28: moving the
 * capability matrix out of `workflow.js` broke 14 test modules at boot with
 * `Cannot read properties of undefined (reading 'load')`, not one product line). The split declares
 * its new file here, once, so a future file split edits this map instead of every harness.
 */
import { readFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

/* The map lives in splits.json so the Python drivers (frontend_catalogue.with_companions) and this
 * loader read the same declaration; a second copy in a comment is how the two would drift.
 * BOTH SIDES OF EVERY PAIR ARE SPELLED RELATIVE TO `js/` — the page's own spelling, because that is
 * what `loadPageScripts` matches against. A name relative to its owner's directory would read as a
 * different file to the page list, and the split-out module would silently never load. */
const JS_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'backend', 'static', 'js');
const SPLIT_OF = JSON.parse(readFileSync(new URL('./splits.json', import.meta.url), 'utf8'));

/** The owner-first closure of the split map: each name, then everything split out of it (and of
 *  those, recursively). Both `withCompanions` and the path-reading harnesses need this order. */
function closure(names) {
    const out = [];
    const seen = new Set();
    const visit = (name) => {
        if (seen.has(name)) return;
        seen.add(name);
        out.push(name);
        for (const extra of SPLIT_OF[name] || []) visit(extra);
    };
    for (const name of names) visit(name);
    return out;
}

/** `names` plus every companion of the modules it names (for `loadPageScripts`'s `only`).
 *
 * The closure is transitive on purpose: a file split out of a split-out file is still a module the
 * owner cannot do without. One level would boot `panels/settings.js` without the node panels split
 * out of IT — the same half-layer death this map exists to prevent, one level deeper.
 */
export function withCompanions(names) {
    return closure(names);
}

/**
 * The SOURCE TEXT of the given module paths, each followed by its companions. For the harnesses
 * that take paths on argv and concatenate them: their argv layout stays exactly as it was, and only
 * what gets evaluated grows.
 *
 * A path is matched to the map by its spelling under `js/` (what the page uses); a driver that hands
 * over something outside `js/` is read as-is, with no companions to add.
 *
 * A file is emitted ONCE per call, even when the driver named it itself and it is also a companion of
 * something else it named (`harness_schedules.mjs` lists `workflow.js` and `panels/shell.js`, and the
 * panel is a companion of the workflow). Evaluated twice, its top-level `const` is a redeclaration in
 * the shared global lexical scope and the boot dies on `Identifier 'Outline' has already been
 * declared` — an error that would look like the map's fault rather than a duplicated read.
 */
export function sourcesWithCompanions(paths) {
    const sources = [];
    const read = new Set();
    const emit = (absolute) => {
        if (read.has(absolute)) return;
        read.add(absolute);
        sources.push(readFileSync(absolute, 'utf8'));
    };
    for (const path of paths) {
        const absolute = resolve(String(path));
        const relativeToJs = relative(JS_DIR, absolute).split(sep).join('/');
        if (relativeToJs.startsWith('..')) {
            emit(absolute);
            continue;
        }
        for (const name of closure([relativeToJs])) emit(join(JS_DIR, name));
    }
    return sources;
}

/** One string for the harnesses that concatenate their modules into a single script. */
export function sourceOf(...paths) {
    return sourcesWithCompanions(paths).join('\n;\n');
}
