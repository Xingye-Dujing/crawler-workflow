/* Autosave + dirty-guard behaviour, run against the REAL workflow.js (+ canvas.js).
 *
 * workflow.js owns the substantive logic — `scheduleAutosave` (a debounce that only arms
 * when a file is already open and the canvas is dirty), `_autosaveToFile` (the silent POST),
 * and `installDirtyGuard` (the beforeunload warning). app.js only WIRES the guard, so the
 * harness tests the logic here and the browser tier tests the wiring.
 *
 * `baseSandbox` runs setTimeout for real (0 ms) and clearTimeout as a no-op, which cannot
 * pin a debounce — so the timers and fetch are replaced with a deterministic queue the
 * scenario drains by hand.
 *
 * Usage: node harness_autosave.mjs <canvas.js> <workflow.js>
 * Prints one JSON object to stdout.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, dispatchWindow, fixWindow } from './harness_dom.mjs';

const [canvasPath, wfPath] = process.argv.slice(2);
const src = [canvasPath, wfPath].map((p) => fs.readFileSync(p, 'utf8')).join('\n;\n');

const I18n = {
    lang: 'en',
    dict: { en: {}, zh: {} },
    t(k) { return k; },
    fill() { },
};

/* Deterministic timers: scheduleAutosave stores the returned id and clearTimeout must
   really cancel the pending one, or the debounce is untestable. */
let timers = {};
let tid = 0;
const fetchCalls = [];
const toasts = [];

const sandbox = {
    ...baseSandbox(),
    I18n,
    setTimeout: (fn) => { timers[++tid] = fn; return tid; },
    clearTimeout: (id) => { delete timers[id]; },
    fetch: (url, opts) => {
        fetchCalls.push({ url: String(url), opts });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    },
    showToast: (m) => toasts.push(String(m)),
    showDialog: async () => null,
    /* canvas.toWorkflowJSON reads RunState.parallel/headless to describe the run mode,
       so a harness that serialises a workflow must give it one (same as harness_canvas_ix). */
    RunState: { parallel: true, headless: true, running: false, setRunning() { }, set() { } },
    resumeBar: { refresh() { } },
    __drain() {
        const pending = Object.values(timers);
        timers = {};
        pending.forEach((f) => f());
        return pending.length;
    },
    __pending() { return Object.keys(timers).length; },
};

vm.createContext(sandbox);
fixWindow(vm, sandbox);
vm.runInContext(src + '\n;globalThis.__canvas = canvas; globalThis.__workflow = workflow;', sandbox);

const canvas = sandbox.__canvas;
const workflow = sandbox.__workflow;

canvas.init();

/* Force the dirty flag without a real edit: _refreshDirty recomputes dirty from
   _cleanState, so a sentinel baseline that can never equal getState() reads as dirty. */
const setDirty = (on) => {
    canvas._cleanState = on ? '__SENTINEL_DIRTY__' : JSON.stringify(canvas.getState());
    canvas.dirty = on;
};

const out = {};
const flushMicrotasks = () => new Promise((resolve) => setImmediate(resolve));

/* ── 1. armed autosave: one timer, then one silent POST, and dirty clears ── */
workflow.currentFile = 'wfA';
setDirty(true);
fetchCalls.length = 0;
workflow.scheduleAutosave();
out.fire = { pendingAfterSchedule: sandbox.__pending(), dirtyBefore: canvas.dirty };
/* Run the armed timer, then await the silent save's async work. */
sandbox.__drain();
await flushMicrotasks();
const saveCall = fetchCalls.find((c) => c.url.indexOf('/api/workflow/save') >= 0);
out.fire.postCount = fetchCalls.filter((c) => c.url.indexOf('/api/workflow/save') >= 0).length;
out.fire.postName = saveCall ? JSON.parse(saveCall.opts.body).name : null;
out.fire.silent = toasts.length === 0;
out.fire.dirtyAfter = canvas.dirty;

/* ── 2. no file open: never schedules (an unnamed canvas is left to the explicit Save) ── */
workflow.currentFile = '';
setDirty(true);
workflow.scheduleAutosave();
out.noFile = { pending: sandbox.__pending() };

/* ── 3. nothing dirty: nothing to flush ── */
workflow.currentFile = 'wfA';
setDirty(false);
workflow.scheduleAutosave();
out.notDirty = { pending: sandbox.__pending() };

/* ── 4. debounce: two quick schedules leave exactly one timer ── */
workflow.currentFile = 'wfA';
setDirty(true);
workflow.scheduleAutosave();
workflow.scheduleAutosave();
out.debounce = { pending: sandbox.__pending() };
sandbox.__drain();
await flushMicrotasks();

/* ── 5. dirty guard fires only while dirty, installs once ── */
workflow._dirtyGuardInstalled = false;
delete sandbox.__handlers.window.beforeunload;
workflow.installDirtyGuard();
out.guard = { listeners: (sandbox.__handlers.window.beforeunload || []).length };

let preventedDirty = false;
setDirty(true);
const evDirty = dispatchWindow(sandbox.__handlers, 'beforeunload', { preventDefault: () => { preventedDirty = true; } });
out.guard.dirtyTriggers = { prevented: preventedDirty, returnValue: evDirty.returnValue };

let preventedClean = false;
setDirty(false);
const evClean = dispatchWindow(sandbox.__handlers, 'beforeunload', { preventDefault: () => { preventedClean = true; } });
out.guard.cleanDoesNotTrigger = { prevented: preventedClean, returnValue: evClean.returnValue };

workflow.installDirtyGuard();
out.guard.idempotent = (sandbox.__handlers.window.beforeunload || []).length === out.guard.listeners;

/* ── 6. saveState (the mutation chokepoint) is what arms the autosave ── */
workflow.currentFile = 'wfC';
workflow._autosaveTimer = null;
sandbox.__drain();
setDirty(true);
const beforeChoke = sandbox.__pending();
canvas.addNode('source', 10, 10);
out.chokepoint = { scheduledByMutation: sandbox.__pending() > beforeChoke };

process.stdout.write(JSON.stringify(out));
