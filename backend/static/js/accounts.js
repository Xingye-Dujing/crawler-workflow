/* The signed-in account's own actions and the administrator's account registry.
 *
 * Nothing here ever holds a password after the request is sent: the field is read, the request is
 * made, and the input's value is cleared in the same tick. The server never answers with a
 * password or a hash, so there is nothing to render — the panel shows usernames, roles and state
 * only. */

const Accounts = {
    overlay: null,
    users: [],
    _pwOpen: false,

    open() {
        if (Auth.user && Auth.user.role === 'admin') return this.openAdmin();
        return this.openPasswordDialog(false);
    },

    close() {
        if (this.overlay && this.overlay.parentNode) this.overlay.parentNode.removeChild(this.overlay);
        this.overlay = null;
    },

    /* ── Everyone: change the password ─────────────────────────────────── */

    openPasswordDialog(forced) {
        if (this._pwOpen) return;
        this._pwOpen = true;
        showDialog({
            message: I18n.t(forced ? 'accounts.mustChange' : 'accounts.changePassword'),
            fields: [
                { id: 'acc-current', label: I18n.t('accounts.currentPassword'), type: 'password' },
                { id: 'acc-new', label: I18n.t('accounts.newPassword'), type: 'password' },
                { id: 'acc-confirm', label: I18n.t('accounts.confirmPassword'), type: 'password' },
            ],
            buttons: [{ label: I18n.t('accounts.save'), value: 'save', primary: true }],
            dismissable: !forced,
            showClose: !forced,
            cancelValue: '',
        }).then((answer) => {
            this._pwOpen = false;
            const current = document.getElementById('acc-current');
            const next = document.getElementById('acc-new');
            const confirm = document.getElementById('acc-confirm');
            const currentPassword = current ? current.value : '';
            const newPassword = next ? next.value : '';
            const repeated = confirm ? confirm.value : '';
            /* Clear the fields before anything is awaited: a password typed into a dialog that
               stayed on screen must not survive the next open. */
            [current, next, confirm].forEach((box) => { if (box) box.value = ''; });
            if (answer !== 'save') return;
            if (!newPassword || newPassword !== repeated) {
                showToast(I18n.t('accounts.passwordMismatch'));
                if (forced) this.openPasswordDialog(true);
                return;
            }
            fetch('/api/account/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
            }).then((response) => response.json().then((body) => ({ response, body })))
                .then(({ response, body }) => {
                    if (response.ok && body.ok) {
                        Auth.mustChange = false;
                        showToast(I18n.t('accounts.passwordSaved'));
                        /* Reload so every panel that was refused while the debt stood is fetched
                           again under the new session state. Without this the page keeps its
                           half-loaded state (node types, workflow, runs) until a manual refresh. */
                        if (typeof location !== 'undefined' && typeof location.reload === 'function') {
                            location.reload();
                        }
                        return;
                    }
                    /* Deliberately no value echoed back: the refusal names what is wrong
                       ("current password incorrect", "too short"), never the password. */
                    showToast((body && body.error) || I18n.t('accounts.failed'));
                    if (forced) this.openPasswordDialog(true);
                })
                .catch(() => showToast(I18n.t('accounts.failed')));
        });
    },

    /* ── Administrators: the registry ──────────────────────────────────── */

    openAdmin() {
        this.close();
        const overlay = document.createElement('div');
        overlay.className = 'accounts-overlay';
        overlay.id = 'accounts-overlay';
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) this.close();
        });
        overlay.innerHTML =
            '<div class="accounts-panel">' +
            '  <div class="accounts-head">' +
            '    <span class="accounts-title">' + this.esc(I18n.t('accounts.title')) + '</span>' +
            '    <span class="accounts-me">' + this.esc(I18n.t('accounts.signedInAs', { user: Auth.user.username })) + '</span>' +
            '    <button class="menu-btn" type="button" onclick="Accounts.close()">' + this.esc(I18n.t('accounts.close')) + '</button>' +
            '  </div>' +
            '  <div class="accounts-create">' +
            '    <input class="settings-input" id="acc-new-username" autocomplete="off" placeholder="' + this.esc(I18n.t('accounts.username')) + '">' +
            '    <input class="settings-input" id="acc-new-password" type="password" autocomplete="new-password" placeholder="' + this.esc(I18n.t('accounts.password')) + '">' +
            '    <select class="settings-input" id="acc-new-role">' +
            '      <option value="user">' + this.esc(I18n.t('accounts.roleUser')) + '</option>' +
            '      <option value="admin">' + this.esc(I18n.t('accounts.roleAdmin')) + '</option>' +
            '    </select>' +
            '    <button class="menu-btn toggle-on" type="button" onclick="Accounts.create()">' + this.esc(I18n.t('accounts.create')) + '</button>' +
            '  </div>' +
            '  <div class="accounts-list" id="accounts-list">' + this.esc(I18n.t('accounts.loading')) + '</div>' +
            '  <div class="accounts-audit" id="accounts-audit"></div>' +
            '</div>';
        document.body.appendChild(overlay);
        this.overlay = overlay;
        this.load();
    },

    load() {
        fetch('/api/accounts')
            .then((response) => response.json())
            .then((body) => {
                if (!body || !body.ok) {
                    this.render('', (body && body.error) || I18n.t('accounts.failed'));
                    return;
                }
                this.users = body.accounts || [];
                this.render('');
            })
            .catch(() => this.render('', I18n.t('accounts.failed')));
    },

    render(auditHtml, error) {
        const list = document.getElementById('accounts-list');
        if (!list) return;
        if (error) {
            list.innerHTML = '<p class="accounts-error">' + this.esc(error) + '</p>';
            return;
        }
        let html = '<table class="accounts-table"><thead><tr>' +
            '<th>' + this.esc(I18n.t('accounts.username')) + '</th>' +
            '<th>' + this.esc(I18n.t('accounts.role')) + '</th>' +
            '<th>' + this.esc(I18n.t('accounts.status')) + '</th>' +
            '<th>' + this.esc(I18n.t('accounts.lastLogin')) + '</th>' +
            '<th>' + this.esc(I18n.t('accounts.actions')) + '</th>' +
            '</tr></thead><tbody>';
        this.users.forEach((user) => {
            const disabled = user.status === 'disabled';
            const self = Auth.user && user.username === Auth.user.username;
            html += '<tr>' +
                '<td>' + this.esc(user.username) + '</td>' +
                '<td>' + this.esc(user.role === 'admin' ? I18n.t('accounts.roleAdmin') : I18n.t('accounts.roleUser')) + '</td>' +
                '<td>' + this.esc(disabled ? I18n.t('accounts.disabled') : I18n.t('accounts.active')) + '</td>' +
                '<td>' + this.esc(this.when(user.last_login_at)) + '</td>' +
                '<td class="accounts-actions">' +
                '<button class="menu-btn" type="button" onclick="Accounts.reset(\'' + this.esc(user.user_id) + '\')">' + this.esc(I18n.t('accounts.reset')) + '</button>' +
                '<button class="menu-btn" type="button" onclick="Accounts.forceLogout(\'' + this.esc(user.user_id) + '\')">' + this.esc(I18n.t('accounts.forceLogout')) + '</button>' +
                (self ? '' : '<button class="menu-btn" type="button" onclick="Accounts.toggle(\'' + this.esc(user.user_id) + '\')">' +
                    this.esc(disabled ? I18n.t('accounts.enable') : I18n.t('accounts.disable')) + '</button>' +
                    '<button class="menu-btn" type="button" onclick="Accounts.remove(\'' + this.esc(user.user_id) + '\')">' + this.esc(I18n.t('accounts.delete')) + '</button>') +
                '</td></tr>';
        });
        html += '</tbody></table>';
        list.innerHTML = html;
        const audit = document.getElementById('accounts-audit');
        if (audit) {
            audit.innerHTML = '<div class="accounts-audit-head">' +
                '<span>' + this.esc(I18n.t('accounts.audit')) + '</span>' +
                '<button class="menu-btn" type="button" onclick="Accounts.loadAudit()">' + this.esc(I18n.t('accounts.refresh')) + '</button>' +
                '</div><div id="accounts-audit-rows"></div>';
            this.loadAudit();
        }
    },

    create() {
        const name = document.getElementById('acc-new-username');
        const password = document.getElementById('acc-new-password');
        const role = document.getElementById('acc-new-role');
        const username = name ? name.value.trim() : '';
        const secret = password ? password.value : '';
        const roleValue = role ? role.value : 'user';
        if (password) password.value = '';
        fetch('/api/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password: secret, role: roleValue }),
        }).then((response) => response.json().then((body) => ({ response, body })))
            .then(({ response, body }) => {
                if (response.ok && body.ok) {
                    showToast(I18n.t('accounts.userCreated', { user: body.user.username }));
                    if (name) name.value = '';
                    this.load();
                    return;
                }
                showToast((body && body.error) || I18n.t('accounts.failed'));
            })
            .catch(() => showToast(I18n.t('accounts.failed')));
    },

    reset(userId) {
        showDialog({
            message: I18n.t('accounts.resetPrompt'),
            fields: [{ id: 'acc-reset-password', label: I18n.t('accounts.newPassword'), type: 'password' }],
            buttons: [{ label: I18n.t('accounts.save'), value: 'save', primary: true }],
            cancelValue: '',
        }).then((answer) => {
            const field = document.getElementById('acc-reset-password');
            const password = field ? field.value : '';
            if (field) field.value = '';
            if (answer !== 'save' || !password) return;
            this.post('/api/accounts/' + encodeURIComponent(userId) + '/password', { password, must_change: true })
                .then((ok) => {
                    showToast(I18n.t(ok ? 'accounts.passwordSaved' : 'accounts.failed'));
                    if (ok) this.load();
                });
        });
    },

    toggle(userId) {
        const user = this.users.find((row) => row.user_id === userId);
        if (!user) return;
        const status = user.status === 'disabled' ? 'active' : 'disabled';
        this.post('/api/accounts/' + encodeURIComponent(userId) + '/status', { status })
            .then((ok) => {
                showToast(I18n.t(ok ? 'accounts.updated' : 'accounts.failed'));
                if (ok) this.load();
            });
    },

    forceLogout(userId) {
        this.post('/api/accounts/' + encodeURIComponent(userId) + '/logout', {})
            .then((ok) => {
                showToast(I18n.t(ok ? 'accounts.updated' : 'accounts.failed'));
            });
    },

    remove(userId) {
        const user = this.users.find((row) => row.user_id === userId);
        if (!user) return;
        showDialog({
            message: I18n.t('accounts.deleteConfirm'),
            fields: [{ id: 'acc-confirm-name', label: I18n.t('accounts.confirmUsername'), type: 'text' }],
            buttons: [{ label: I18n.t('accounts.delete'), value: 'delete', primary: true }],
            cancelValue: '',
        }).then((answer) => {
            const field = document.getElementById('acc-confirm-name');
            const confirmName = field ? field.value : '';
            if (field) field.value = '';
            if (answer !== 'delete' || !confirmName) return;
            fetch('/api/accounts/' + encodeURIComponent(userId), {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm_username: confirmName }),
            }).then((response) => response.json().then((body) => ({ response, body })))
                .then(({ response, body }) => {
                    if (response.ok && body.ok) {
                        showToast(I18n.t('accounts.deleteDone', { user: user.username }));
                        this.load();
                        return;
                    }
                    showToast((body && body.error) || I18n.t('accounts.failed'));
                })
                .catch(() => showToast(I18n.t('accounts.failed')));
        });
    },

    loadAudit() {
        fetch('/api/accounts/audit?limit=100')
            .then((response) => response.json())
            .then((body) => {
                const out = document.getElementById('accounts-audit-rows');
                if (!out || !body || !body.ok) return;
                const rows = body.entries || [];
                if (!rows.length) {
                    out.innerHTML = '<p class="accounts-empty">' + this.esc(I18n.t('accounts.auditEmpty')) + '</p>';
                    return;
                }
                out.innerHTML = '<table class="accounts-table"><tbody>' + rows.map((row) => {
                    const label = I18n.t('accounts.event.' + row.event);
                    return '<tr><td>' + this.esc(this.when(row.ts)) + '</td><td>' +
                        this.esc(row.username || '') + '</td><td>' +
                        this.esc(label === 'accounts.event.' + row.event ? row.event : label) + '</td></tr>';
                }).join('') + '</tbody></table>';
            })
            .catch(() => { });
    },

    post(url, payload) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        }).then((response) => response.json().then((body) => response.ok && !!body.ok))
            .catch(() => false);
    },

    when(ts) {
        if (!ts) return I18n.t('accounts.never');
        const date = new Date(Number(ts) * 1000);
        return isNaN(date.getTime()) ? I18n.t('accounts.never') : date.toLocaleString();
    },

    esc(value) {
        return String(value === undefined || value === null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },
};
