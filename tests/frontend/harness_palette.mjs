/* Drives the REAL left-palette filter (backend/static/js/app.js: filterPalette) under node.

   Palette search is pure DOM behaviour with no server round trip, so it is invisible to
   Python unless a harness builds the markup and calls the function. Like harness_app it loads
   custom-select.js + workflow.js + app.js in index.html's order (app.js's boot needs the
   globals workflow.js declares), builds a small palette, and reports which items/categories
   survive each query. `filterPalette` is a top-level function, so the context can call it
   directly without firing DOMContentLoaded. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const jsDir = process.argv[2];
const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);
const FILES = ['custom-select.js', 'workflow.js', 'app.js'];
for (const f of FILES) {
    vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f });
}

const doc = sandbox.document;
const scope = doc.getElementById('node-palette');
const cats = [];
const items = [];

function addCat(text) {
    const el = doc.createElement('div');
    el.classList.add('palette-cat');
    el.textContent = text;
    scope.appendChild(el);
    cats.push(el);
    return el;
}

function addItem(type, tagText, labelText) {
    const el = doc.createElement('div');
    el.classList.add('palette-item');
    el.dataset.type = type;
    const tag = doc.createElement('span');
    tag.classList.add('palette-tag');
    tag.textContent = tagText;
    const lbl = doc.createElement('span');
    lbl.dataset.i18n = 'palette.' + type;
    lbl.textContent = labelText;
    el.appendChild(tag);
    el.appendChild(lbl);
    scope.appendChild(el);
    items.push(el);
    return el;
}

/* Interleaved in document order so the category grouping is exercised, not just filtering. */
addCat('Workflow');
addItem('name', '[NAM]', 'Workflow Name');
addCat('Data Inputs');
addItem('source', '[SRC]', 'Data Source');
addItem('upload', '[UPL]', 'Upload File');
addCat('Processing');
addItem('process', '[PRC]', 'Process');
addCat('Outputs');
addItem('visualize', '[VIZ]', 'Visualize');
addItem('output', '[OUT]', 'Output');

function snap() {
    return {
        types: items.filter((el) => el.style.display !== 'none').map((el) => el.dataset.type).sort(),
        visibleCats: cats.filter((c) => c.style.display !== 'none').length,
    };
}

const report = {};
for (const q of ['', 'process', 'xyz-nothing', 'out', 'src']) {
    vm.runInContext('filterPalette(' + JSON.stringify(q) + ')', sandbox);
    report[q === '' ? '(empty)' : q] = snap();
}
process.stdout.write(JSON.stringify(report));
