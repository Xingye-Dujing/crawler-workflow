/* Drives the REAL Console phase-timing strip (panels/phase-log.js) under node.
 *
 * The strip answers “where did the time go” for a slow run, so what it renders (and what
 * it refuses to render) is product behaviour:
 *   · rows are built from /api/run/phases, with seconds and the status/rows detail;
 *   · a label or URL is escaped (a note URL is user data);
 *   · an unchanged payload does not repaint the box every poll;
 *   · a closed console is not polled at all.
 *
 * Usage: node harness_phase_log.mjs <phase-log.js> — prints one JSON object.
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [sourcePath] = process.argv.slice(2);

const sandbox = { ...baseSandbox() };
sandbox.console = { log() {}, warn() {}, error() {} };
vm.createContext(sandbox);
fixWindow(vm, sandbox);

const consolePanel = sandbox.document.createElement('div');
consolePanel.id = 'console-panel';
consolePanel.classList.add('open');
const body = sandbox.document.createElement('div');
body.id = 'console-phases-body';
sandbox.document.body.appendChild(consolePanel);
sandbox.document.body.appendChild(body);

const LABELS = {
    'phaseLog.title': 'Startup / phase log',
    'phaseLog.empty': 'No timings yet',
    'phaseLog.phase.browser': 'Browser start',
    'phaseLog.phase.crawl': 'Crawl',
    'phaseLog.phase.walk': 'Comment walk',
    'phaseLog.status.ok': 'ok',
    'phaseLog.status.blocked': 'blocked',
    'phaseLog.rows': '{n} rows',
    'phaseLog.unproven': '{n} unproven',
    'phaseLog.wall': 'login wall',
    'phaseLog.risk': 'risk control',
    'phaseLog.loginWindow': 'login window',
    'platform.xiaohongshu': 'Xiaohongshu',
};
sandbox.I18n = {
    t(key) {
        return Object.prototype.hasOwnProperty.call(LABELS, key) ? LABELS[key] : key;
    },
};
sandbox.escapeHtml = (value) =>
    String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

/* No real timer: the module starts a 2s interval at load and that would keep node alive. */
sandbox.setInterval = () => 0;
sandbox.clearInterval = () => {};

let answer = { ok: true, running: true, phases: [] };
const fetches = [];
sandbox.fetch = (url) => {
    fetches.push(String(url));
    return Promise.resolve({ json: () => Promise.resolve(answer) });
};

const source = fs.readFileSync(sourcePath, 'utf8');
vm.runInContext(source, sandbox);
const PhaseLog = sandbox.PhaseLog;

const out = {};

/* ── an empty answer is a sentence, not a blank box ─────────────────────── */
await PhaseLog.refresh();
out.empty = {
    text: body.innerHTML,
    fetched: fetches.length,
    url: fetches[0],
};

/* ── rows carry seconds, the status and the row count ───────────────────── */
answer = {
    ok: true,
    running: true,
    phases: [
        { phase: 'browser', label: 'xiaohongshu', platform: 'xiaohongshu', seconds: 1.2, at: 1 },
        {
            phase: 'crawl',
            label: 'xiaohongshu',
            platform: 'xiaohongshu',
            seconds: 55.0,
            rows: 2,
            at: 2,
        },
        {
            phase: 'walk',
            label: 'xiaohongshu',
            platform: 'xiaohongshu',
            seconds: 11.54,
            status: 'ok',
            rows: 3,
            unproven: 0,
            at: 3,
            url: 'https://www.xiaohongshu.com/explore/6ad81a29000000002c011778',
        },
    ],
};
await PhaseLog.refresh();
out.rows = { html: body.innerHTML, fetched: fetches.length };

/* ── an unchanged payload does not repaint ──────────────────────────────── */
body.innerHTML = 'SENTINEL';
await PhaseLog.refresh();
out.unchanged = { kept: body.innerHTML === 'SENTINEL', fetched: fetches.length };

/* ── a note URL is user data: escaped, never markup ─────────────────────── */
answer = {
    ok: true,
    running: true,
    phases: [
        {
            phase: 'walk',
            label: '<img src=x onerror=alert(1)>',
            seconds: 1,
            status: 'blocked',
            rows: 0,
            at: 1,
            url: 'https://www.xiaohongshu.com/explore/<b>x</b>',
        },
    ],
};
await PhaseLog.refresh();
out.escaped = body.innerHTML;

/* ── a running phase shows its live elapsed, not a silence ─────────────── */
answer = {
    ok: true,
    running: true,
    phases: [
        {
            phase: 'walk',
            label: 'xiaohongshu',
            platform: 'xiaohongshu',
            running: true,
            seconds: 0,
            at: Date.now() / 1000 - 74,
            url: 'https://www.xiaohongshu.com/explore/6ad81a29000000002c011778',
        },
    ],
};
await PhaseLog.refresh();
out.running = body.innerHTML;

/* ── a closed console is not polled ─────────────────────────────────────── */
consolePanel.classList.remove('open');
const before = fetches.length;
await PhaseLog.refresh();
out.closed = { fetched: fetches.length - before, kept: body.innerHTML };

process.stdout.write(JSON.stringify(out));
