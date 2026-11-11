/* Runs the REAL saved-logins dock with the account/exit pool switched on.
 *
 * The pool adds a second read (`/api/pool/state`) and two more tabs to a panel that used to
 * be one table. What this harness proves is the part a server test cannot see: with the
 * feature off the dock is unchanged, with it on the state/exit columns and the levers are
 * built from the server's numbers, and a lever posts the pair of the ROW it was pressed on.
 *
 * Usage: node harness_pool.mjs <path/to/workflow.js>
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { sourceOf } from './companions.mjs';

const src = sourceOf(process.argv[2]);
const sandbox = {
    ...baseSandbox(),
    I18n: {
        lang: 'en',
        t: (k, vars) => {
            const names = Object.keys(vars || {});
            if (!names.length) return String(k);
            return String(k) + ' - ' + names.map((name) => String(vars[name])).join(' | ');
        },
    },
    __toasts: [],
    __calls: [],
    __responses: {},
};
vm.createContext(sandbox);
// ``fixWindow`` is applied by the other harnesses so a panel that touches ``window`` works.
fixWindow(vm, sandbox);
vm.runInContext(src, sandbox);

sandbox.fetchJSON = (url, opts) => {
    sandbox.__calls.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
    const payload = sandbox.__responses[url] === undefined ? { ok: true } : sandbox.__responses[url];
    return Promise.resolve(payload);
};
sandbox.showToast = (msg) => sandbox.__toasts.push(msg);
sandbox.showDialog = () => Promise.resolve(null);

const doc = sandbox.document;
const flush = async () => {
    for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
};

const ROWS = [
    {
        platform: 'weibo',
        account: 'work',
        label_key: '',
        label_args: {},
        entries: 12,
        saved_at: '2026-11-01 10:00',
        profile_exists: false,
        profile_used: false,
        pool_state: 'cooling',
        pool_reason: 'login_wall',
        pool_cool_until_local: '2026-11-11 20:00',
        pool_strikes: 1,
        exit_id: '',
    },
    {
        platform: 'weibo',
        account: 'home',
        label_key: '',
        label_args: {},
        entries: 8,
        saved_at: '2026-11-02 10:00',
        profile_exists: false,
        profile_used: false,
        pool_state: 'ok',
        pool_reason: '',
        pool_cool_until_local: '',
        pool_strikes: 0,
        exit_id: 'p_1',
    },
];
const POOL_ON = {
    ok: true,
    enabled: true,
    summary: { weibo: { usable: 1, cooling: 1, disabled: 0 } },
    accounts: [],
    exits: [
        {
            id: 'p_1',
            name: 'hk03',
            scheme: 'http',
            host: '10.0.0.1',
            port: 8080,
            allowed_platforms: [],
            has_auth: false,
            enabled: true,
            states: [],
        },
    ],
    events: [
        {
            at_local: '2026-11-11 18:00:00',
            kind: 'login_wall',
            platform: 'weibo',
            account: 'work',
            exit_id: '',
            rows: 0,
            run_id: 'r_1',
        },
    ],
};

const body = () => doc.getElementById('cookies-mgr-body');
const rows = (host) => Array.prototype.slice.call(host.querySelectorAll('tr.cookie-row'));
const texts = (row) => (row.children || []).map((cell) => cell.textContent || '');
const tabBar = () =>
    (body().children || []).filter((child) => child.classList && child.classList.contains('cookie-pool-tabs'))[0] || null;
const tabs = () => (tabBar() ? tabBar().children : []);
const press = (row, label) => {
    const td = (row.children || []).filter((cell) => cell.className === 'runs-mgr-ops')[0];
    const button = td && (td.children || []).filter((b) => b.textContent === label)[0];
    if (button) button.click();
    return !!button;
};
const out = {};

/* 1. Feature off: the dock is the table it always was. */
sandbox.__responses['/api/cookies/status'] = { ok: true, rows: ROWS, cookies: {}, accounts: {} };
sandbox.__responses['/api/pool/state'] = { ok: true, enabled: false, accounts: [], exits: [], events: [] };
await sandbox.cookiesManager.refresh();
await flush();
out.featureOff = {
    tabs: tabs().length,
    headerCells: Array.prototype.slice
        .call(body().querySelectorAll('th'))
        .map((th) => th.textContent),
    firstRowCells: texts(rows(body())[0]).length,
    firstRowButtons: (rows(body())[0].children.slice(-1)[0].children || []).map((b) => b.textContent),
    poolStateAsked: sandbox.__calls.some((call) => call.url === '/api/pool/state'),
};

/* 2. Feature on: tabs, state/exit columns, and the per-row levers. */
sandbox.__responses['/api/pool/state'] = POOL_ON;
await sandbox.cookiesManager.refresh();
await flush();
const table = rows(body());
const bindingOf = (row) => {
    const select = (row.querySelectorAll('select') || [])[0];
    return select ? Array.prototype.slice.call(select.children || []).map((o) => o.value) : null;
};
out.featureOn = {
    tabs: tabs().map((b) => b.textContent),
    headerCells: Array.prototype.slice
        .call(body().querySelectorAll('th'))
        .map((th) => th.textContent),
    coolingRow: texts(table[0]),
    healthyRow: texts(table[1]),
    coolingButtons: (table[0].children.slice(-1)[0].children || []).map((b) => b.textContent),
    healthyButtons: (table[1].children.slice(-1)[0].children || []).map((b) => b.textContent),
    coolingBinding: bindingOf(table[0]),
    healthyBinding: bindingOf(table[1]),
};

/* 3. A lever acts on ITS row: the box is not part of the question. */
sandbox.__calls.length = 0;
sandbox.__toasts.length = 0;
sandbox.__responses['/api/pool/account/reset'] = { ok: true, message: 'UNFROZEN' };
press(rows(body())[0], 'pool.resetOne');
await flush();
out.resetRow = {
    posted: sandbox.__calls.filter((call) => call.url === '/api/pool/account/reset').map((call) => call.body),
    toasts: sandbox.__toasts.slice(),
};

sandbox.__calls.length = 0;
sandbox.__responses['/api/pool/account/disable'] = { ok: true, message: 'DISABLED' };
press(rows(body())[1], 'pool.disableOne');
await flush();
out.disableRow = {
    posted: sandbox.__calls.filter((call) => call.url === '/api/pool/account/disable').map((call) => call.body),
    toasts: sandbox.__toasts.slice(),
};

/* 4. The exit tab renders the server's inventory and never a credential. */
sandbox.__calls.length = 0;
await sandbox.cookiesManager.refresh();
await flush();
const exitTab = tabs().filter((b) => b.textContent === 'pool.tabExits')[0];
exitTab.click();
await flush();
out.exits = {
    rows: rows(body()).map(texts),
    hasCredentialField: JSON.stringify(sandbox.__responses['/api/pool/state']).indexOf('password') >= 0,
    saveButton: Array.prototype.slice
        .call(body().querySelectorAll('button'))
        .map((b) => b.textContent)
        .filter((label) => String(label).indexOf('pool.exit') === 0),
};

/* 5. The record tab shows the audit rows the server sent. */
const eventTab = tabs().filter((b) => b.textContent === 'pool.tabEvents')[0];
eventTab.click();
await flush();
out.events = rows(body()).map(texts);

process.stdout.write(JSON.stringify(out));
