/* The modules a split-out module cannot do without.
 *
 * The page always ships both halves; a harness handed only the old file boots half a layer and dies
 * the first time the scenario asks the split-out half anything (measured 2026-10-28: moving the
 * capability matrix out of `workflow.js` broke 14 test modules at boot with
 * `Cannot read properties of undefined (reading 'load')`, not one product line). The split declares
 * its new file here, once, so a future file split edits this map instead of every harness.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

const SPLIT_OF = {
    'workflow.js': [
        'chart-preview.js',
        'capabilities.js',
        'panels/cookies.js',
        'panels/source-help.js',
        'panels/biblio.js',
        'panels/runlog.js',
        'panels/exports.js',
        'panels/runs.js',
    ],
};

/** `names` plus every companion of the modules it names (for `loadPageScripts`'s `only`). */
export function withCompanions(names) {
    const expanded = new Set(names);
    for (const name of names) for (const extra of SPLIT_OF[name] || []) expanded.add(extra);
    return Array.from(expanded);
}

/**
 * The SOURCE TEXT of the given module paths, each followed by its companions read from the same
 * directory. For the harnesses that take paths on argv and concatenate them: their argv layout
 * stays exactly as it was, and only what gets evaluated grows.
 */
export function sourcesWithCompanions(paths) {
    const sources = [];
    for (const path of paths) {
        sources.push(readFileSync(path, 'utf8'));
        for (const extra of SPLIT_OF[String(path).split(/[\\/]/).pop()] || []) {
            sources.push(readFileSync(join(dirname(String(path)), extra), 'utf8'));
        }
    }
    return sources;
}

/** One string for the harnesses that concatenate their modules into a single script. */
export function sourceOf(...paths) {
    return sourcesWithCompanions(paths).join('\n;\n');
}
