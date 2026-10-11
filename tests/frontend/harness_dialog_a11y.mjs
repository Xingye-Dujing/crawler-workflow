/* Drives the REAL modal dialog (workflow.js: showDialog) for its accessibility wiring.

   showDialog already dismissed on Esc/backdrop; what U5 adds is modal semantics
   (role/aria-modal/aria-labelledby on the box) and a Tab focus trap that keeps the caret among
   the dialog's own controls. This harness reproduces the index.html dialog shell's NESTING (the
   actions live inside the box, which lives inside the overlay — focusables() must find them),
   calls showDialog synchronously (its body up to opening runs before the first await), and reports
   the attributes plus one Tab-wrap observation. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, dispatchDocument, fixWindow } from './harness_dom.mjs';

const jsDir = process.argv[2];
const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);

const LABELS = {
    en: { 'settings.close': 'Close' },
    zh: {},
};
const I18n = { lang: 'en', dict: LABELS, t(k) { return (LABELS.en[k] || k); } };
sandbox.I18n = I18n;
sandbox.showToast = () => {};
sandbox.showDialog = undefined; // defined by workflow.js

const FILES = ['canvas.js', 'workflow.js'];
for (const f of FILES) {
    vm.runInContext(fs.readFileSync(path.join(jsDir, f), 'utf8'), sandbox, { filename: f });
}
vm.runInContext('globalThis.window = globalThis;', sandbox);
sandbox.clearInterval = () => {};

const doc = sandbox.document;

/* Build the shell in the SAME nesting index.html uses: overlay > box > (message, inputArea>input,
   listArea, actions). The buttons showDialog appends land inside actions, hence inside box, so
   box.querySelectorAll(...) sees them. */
function el(tag, id, parent) {
    const e = doc.createElement(tag);
    if (id) e.id = id;
    if (parent) parent.appendChild(e);
    return e;
}
const overlay = el('div', 'dialog-overlay', doc.body);
const box = el('div', 'dialog-box', overlay);
el('div', 'dialog-message', box);
const inputArea = el('div', 'dialog-input-area', box);
el('input', 'dialog-input', inputArea);
el('div', 'dialog-list-area', box);
el('div', 'dialog-actions', box);

const report = {};

// Open a dialog with two buttons (no input, so the trap's focusables are the buttons).
vm.runInContext(
    'showDialog({ message: "确认？", buttons: [{ label: "A", value: true }, { label: "B", value: false }] })',
    sandbox,
);

report.open = overlay.classList.contains('open');
report.role = box.getAttribute('role');
report.modal = box.getAttribute('aria-modal');
report.labelledBy = box.getAttribute('aria-labelledby');

/* Record which focusable receives focus when Tab is pressed on the LAST one: the trap must wrap
   to the FIRST. Buttons are created inside showDialog, so attach the spies only now. */
const focusables = box.querySelectorAll('button, [href], input, select, textarea, [tabindex]');
const order = [];
focusables.forEach((node, index) => {
    node.focus = () => order.push(index);
});
const first = focusables[0];
const last = focusables[focusables.length - 1];

dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Tab', shiftKey: false, target: last });
report.tabAtLastFocused = order[order.length - 1];
order.length = 0;
dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Tab', shiftKey: true, target: first });
report.shiftTabAtFirstFocused = order[order.length - 1];

// Escape still dismisses (the pre-existing path): the overlay closes and the promise resolves.
dispatchDocument(sandbox.__handlers, 'keydown', { key: 'Escape', target: doc.body });
report.dismissedByEsc = !overlay.classList.contains('open');

process.stdout.write(JSON.stringify(report));
