/* Drives the REAL app.js + accounts.js: the CSRF header, the forced password dialog, and the
 * admin panel's requests.
 *
 * The assertions belong to Python (they are product decisions), so this harness prints one JSON
 * object. Passwords are inspected only in the request BODY that is about to be sent — the point of
 * the other assertions is that no password survives in the page's own state or in a field.
 *
 * Usage: node harness_accounts.mjs <app.js> <accounts.js>
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { sourceOf } from './companions.mjs';

const src = sourceOf(...process.argv.slice(2));
const sandbox = { ...baseSandbox() };
/* The browser globals app.js's fetch patch uses. The DOM stub carries no Headers/Request, and a
   missing one would send the patch down its own catch branch — the harness would then "prove"
   that no CSRF header is added. */
class HeadersStub {
    constructor(init) {
        this._map = new Map();
        if (init instanceof HeadersStub) init.forEach((value, key) => this.set(key, value));
        else if (init) Object.keys(init).forEach((key) => this.set(key, init[key]));
    }

    has(key) { return this._map.has(String(key).toLowerCase()); }

    set(key, value) { this._map.set(String(key).toLowerCase(), String(value)); }

    get(key) { return this._map.get(String(key).toLowerCase()); }

    forEach(fn) { this._map.forEach((value, key) => fn(value, key)); }
}
sandbox.Headers = HeadersStub;
sandbox.Request = class RequestStub {};
vm.createContext(sandbox);
fixWindow(vm, sandbox);

/* Requests the patched window.fetch actually makes. Installed BEFORE the sources run, because
   app.js closes over the fetch it finds at load time — the whole point of the patch. */
const calls = [];
let accountsAnswer = { ok: true, accounts: [
    {
        user_id: 'u_aaaaaaaaaaaa', username: 'alice', role: 'user', status: 'active',
        must_change_password: false, created_at: 1, last_login_at: null,
    },
    {
        user_id: 'u_bbbbbbbbbbbb', username: 'boss', role: 'admin', status: 'disabled',
        must_change_password: true, created_at: 1, last_login_at: 1,
    },
] };
let status = 200;
let responseBody = { ok: true };
let responseHeaders = {};
sandbox.fetch = async (input, init) => {
    const headers = {};
    const given = init && init.headers;
    if (given && typeof given.forEach === 'function') given.forEach((value, key) => { headers[key] = value; });
    else if (given) Object.assign(headers, given);
    calls.push({
        url: String(input),
        method: String((init && init.method) || 'GET').toUpperCase(),
        headers,
        body: init && init.body ? String(init.body) : '',
    });
    return {
        status,
        ok: status >= 200 && status < 300,
        headers: { get: (name) => responseHeaders[name] || null },
        json: () => Promise.resolve(responseBody),
    };
};

const dialogs = [];
const toasts = [];
sandbox.showDialog = (spec) => {
    dialogs.push({
        message: String(spec.message || ''),
        fields: (spec.fields || []).map((f) => f.id),
        buttons: (spec.buttons || []).map((b) => b.label),
        dismissable: spec.dismissable !== false,
    });
    return Promise.resolve(sandbox.__answer === undefined ? null : sandbox.__answer);
};
sandbox.showToast = (msg) => { toasts.push(String(msg)); };

vm.runInContext(
    `${src}
     ;globalThis.__acc = { Auth, Accounts };`,
    sandbox,
);
const { Auth, Accounts } = sandbox.__acc;
const doc = sandbox.document;
const flush = async () => {
    for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r));
};

const out = {};

/* ── the CSRF header rides every mutating fetch, and only those ─────────── */
Auth.set({ csrf_token: 'csrf-1', user: { username: 'boss', role: 'admin' }, must_change_password: false });
calls.length = 0;
await sandbox.fetch('/api/accounts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'x', password: 'secret-123' }),
});
await sandbox.fetch('/api/config', { method: 'GET' });
out.csrf = {
    posted: calls[0],
    fetched: calls[1],
};

/* ── a 403 that names the debt opens the change dialog ─────────────────── */
dialogs.length = 0;
sandbox.handlePasswordChangeRequired({
    status: 403,
    headers: { get: (name) => (name === 'X-Password-Change-Required' ? '1' : null) },
});
await flush();
out.forced = { dialogs: dialogs.slice(), mustChange: Auth.mustChange };

/* ── the change dialog sends a password and keeps none of it ───────────── */
dialogs.length = 0;
calls.length = 0;
for (const id of ['acc-current', 'acc-new', 'acc-confirm']) {
    const box = doc.createElement('input');
    box.id = id;
    doc.body.appendChild(box);
}
doc.getElementById('acc-current').value = 'old-password';
doc.getElementById('acc-new').value = 'new-password-1';
doc.getElementById('acc-confirm').value = 'new-password-1';
sandbox.__answer = 'save';
status = 200;
responseBody = { ok: true, user: { username: 'boss' } };
Accounts.openPasswordDialog(false);
await flush();
out.changed = {
    dialog: dialogs.slice(),
    request: calls.slice(),
    cleared: ['acc-current', 'acc-new', 'acc-confirm'].map((id) => doc.getElementById(id).value),
    authHasPassword: Object.prototype.hasOwnProperty.call(Auth, 'password'),
};

/* ── a mismatch is refused before any request ──────────────────────────── */
calls.length = 0;
doc.getElementById('acc-current').value = 'old-password';
doc.getElementById('acc-new').value = 'one-password';
doc.getElementById('acc-confirm').value = 'other-password';
sandbox.__answer = 'save';
Accounts.openPasswordDialog(false);
await flush();
out.mismatch = { requests: calls.length, dialogs: dialogs.length };

/* ── a regular user gets the dialog, not the registry ──────────────────── */
dialogs.length = 0;
calls.length = 0;
Auth.user = { username: 'alice', role: 'user' };
Accounts.open();
await flush();
out.regularUser = { dialogs: dialogs.slice(), requests: calls.slice() };

/* ── an administrator gets the table, and no hash is rendered ──────────── */
dialogs.length = 0;
calls.length = 0;
status = 200;
responseBody = accountsAnswer;
Auth.user = { username: 'boss', role: 'admin' };
Accounts.open();
await flush();
const panel = doc.getElementById('accounts-list');
out.adminPanel = {
    request: calls.slice(),
    html: panel ? panel.innerHTML : '',
    overlay: !!doc.getElementById('accounts-overlay'),
};

/* ── creating an account clears the password field and sends it once ───── */
calls.length = 0;
for (const id of ['acc-new-username', 'acc-new-password', 'acc-new-role']) {
    if (!doc.getElementById(id)) {
        const box = doc.createElement('input');
        box.id = id;
        doc.body.appendChild(box);
    }
}
doc.getElementById('acc-new-username').value = 'carol';
doc.getElementById('acc-new-password').value = 'carol-password-1';
doc.getElementById('acc-new-role').value = 'user';
status = 201;
responseBody = { ok: true, user: { username: 'carol' } };
Accounts.create();
await flush();
out.created = {
    request: calls.slice(),
    cleared: doc.getElementById('acc-new-password').value,
};

/* ── a deletion needs the typed username, and its folder message ──────── */
calls.length = 0;
Accounts.users = accountsAnswer.accounts;
sandbox.__answer = 'delete';
for (const id of ['acc-confirm-name']) {
    const box = doc.createElement('input');
    box.id = id;
    doc.body.appendChild(box);
}
doc.getElementById('acc-confirm-name').value = 'alice';
status = 200;
responseBody = { ok: true, user: { username: 'alice', trashed_to: '/tmp/trash' } };
Accounts.remove('u_aaaaaaaaaaaa');
await flush();
out.deleted = {
    request: calls.slice(),
    toasts: toasts.slice(),
};

process.stdout.write(JSON.stringify(out));
