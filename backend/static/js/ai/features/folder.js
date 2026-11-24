/* The working-folder dialog: the server's directory listing, the other disks and the native picker.
 *
 * The browser never guesses a path: every root and child comes from /api/ai/ws/workspace, and a
 * desktop-only native dialog is offered only when the runtime manifest says the host has one.
 */

Object.assign(AIWorkspace, {
    /* ─── Working folder (the harness's one root) ─── */

    _workspace() {
        return this._bootstrap?.workspace || {};
    },

    _renderWorkspace() {
        const button = this._dom.workspaceBtn;
        if (!button) return;
        const state = this._workspace();
        button.hidden = !!state.cloud;
        if (state.cloud) return;
        const name = String(state.folder_name || '');
        button.textContent = name || I18n.t('ai.workspace.choose');
        button.classList.toggle('is-set', !!state.folder);
    },

    toggleFolder() {
        if (!this._dom.folderDialog) return;
        if (!this._dom.folderDialog.hidden) {
            this._dom.folderDialog.hidden = true;
            return;
        }
        this._openFolder(this._workspace().folder || '');
    },

    async _openFolder(path) {
        const host = this._dom.folderDialog;
        if (!host) return;
        host.hidden = false;
        host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.choose')) + '…</div>';
        try {
            const { response, data } = await AIHttp.get('/workspace/browse?path=' + encodeURIComponent(path || ''));
            if (!data.ok) throw new Error(data.error || 'HTTP ' + response.status);
            this._folderState = data;
            this._renderFolder();
        } catch (error) {
            host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.failed', { detail: error.message })) + '</div>';
        }
    },

    _renderFolder() {
        const host = this._dom.folderDialog;
        const state = this._folderState;
        if (!host || !state) return;
        const rows = (state.entries || []).filter((row) => row.dir);
        const list = rows.length
            ? rows.map((row) =>
                '<button type="button" class="ai-folder-row" data-ai-folder-open="' + AIRender.escape(row.path) + '">' +
                '<span class="ai-folder-ico" aria-hidden="true">▸</span>' +
                '<span class="ai-folder-name">' + AIRender.escape(row.name) + '</span></button>'
            ).join('')
            : '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.empty')) + '</div>';
        /* The roots are the OTHER disks. Walking down from one drive could never reach another
           (`dirname('C:\\')` is itself, so the Up button vanished at the root), which made every
           folder outside C: unreachable from this panel. The server answers the list per OS. */
        const roots = state.roots || [];
        const rootRow = roots.length > 1
            ? '<div class="ai-folder-roots">' + roots.map((root) =>
                '<button type="button" class="ai-folder-root' +
                (String(root.path) === String(state.path) ? ' is-current' : '') +
                '" data-ai-folder-root="' + AIRender.escape(root.path) + '">' +
                AIRender.escape(root.name) + '</button>'
            ).join('') + '</div>'
            : '';
        host.innerHTML =
            '<div class="ai-folder-head">' + AIRender.escape(I18n.t('ai.workspace.title')) + '</div>' +
            rootRow +
            '<div class="ai-folder-path" title="' + AIRender.escape(state.path) + '">' + AIRender.escape(state.path) + '</div>' +
            '<div class="ai-folder-list">' + list + '</div>' +
            '<div class="ai-folder-actions">' +
            (state.parent ? '<button type="button" class="ai-ghost" data-ai-folder-open="' + AIRender.escape(state.parent) + '">' + AIRender.escape(I18n.t('ai.workspace.up')) + '</button>' : '') +
            '<button type="button" class="ai-ghost" data-ai-folder-native="1">' + AIRender.escape(I18n.t('ai.workspace.native')) + '</button>' +
            '<button type="button" class="ai-primary" data-ai-folder-use="' + AIRender.escape(state.path) + '">' + AIRender.escape(I18n.t('ai.workspace.use')) + '</button>' +
            (this._workspace().folder ? '<button type="button" class="ai-ghost" data-ai-folder-clear="1">' + AIRender.escape(I18n.t('ai.workspace.clear')) + '</button>' : '') +
            '<button type="button" class="ai-ghost" data-ai-folder-close="1">' + AIRender.escape(I18n.t('ai.workspace.close')) + '</button>' +
            '</div>' +
            '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.hint')) + '</div>';
    },

    /* The OS's own dialog: it can jump to any disk, remembers recent places and shows network
       drives. The server opens it in a child process, so this request waits until the user picks. */
    async _pickNativeFolder() {
        const host = this._dom.folderDialog;
        if (!host) return;
        host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.pickWaiting')) + '</div>';
        try {
            const { response, data } = await AIHttp.post('/workspace/pick', {
                start: (this._folderState && this._folderState.path) || '',
            });
            if (!data.ok) throw new Error(data.error || 'HTTP ' + response.status);
            if (data.cancelled || !data.path) {
                this._renderFolder();
                return;
            }
            await this._setFolder(data.path);
        } catch (error) {
            host.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.workspace.failed', { detail: error.message })) + '</div>';
        }
    },

    async _setFolder(path) {
        try {
            const { response, data } = await AIHttp.post('/workspace', { path: path || '' });
            if (!data.ok) throw new Error(data.error || 'HTTP ' + response.status);
            if (this._bootstrap) this._bootstrap.workspace = data.workspace;
            this._renderWorkspace();
            if (this._dom.folderDialog) this._dom.folderDialog.hidden = true;
            this._toast(path
                ? I18n.t('ai.workspace.changed', { path: data.workspace.folder || path })
                : I18n.t('ai.workspace.none'));
            this._renderSide();
        } catch (error) {
            this._toast(I18n.t('ai.workspace.failed', { detail: error.message }));
        }
    },

});
