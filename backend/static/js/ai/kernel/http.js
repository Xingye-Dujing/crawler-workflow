/* The page's server boundary.
 *
 * `jsonDoor(base)` is the ONE JSON implementation (`url`/`fetch`/`get`/`post`/`patch`/`del`, and the
 * raw answer for a multipart upload or a stream). Two doors are built from it: `AIHttp` for the
 * workspace's routes and `ProductHttp` for the rest of the page, so a module never spells `fetch` +
 * `Content-Type` + `.json()` again. Keeping a route, the refusal it may answer and the field it
 * updates side by side is what makes a failure one sentence.
 * `AI_BASE` lives here too: the one place the page spells the workspace's route prefix.
 */

const AI_BASE = '/api/ai/ws';

/* A route that needs its own status (delete, rename) still gets the raw `response` back, and the body
   is parsed the same way everywhere. The only difference between the two doors is the prefix: a
   chart render or a page setting is the product's route, not the workspace's, and spelling that
   difference as an empty base is what keeps one implementation instead of two. */
function jsonDoor(base) {
    return {
        base,

        url(path) {
            return base + path;
        },

        /** The raw answer, for a body that is not JSON (a multipart upload) or a stream. */
        fetch(path, options) {
            return fetch(base + path, options);
        },

        /** `{response, data}`; an unparseable body reads as `{}` so a caller's `data.ok` is the verdict. */
        async json(path, options) {
            const response = await fetch(base + path, options);
            const data = await response.json().catch(() => ({}));
            return { response, data };
        },

        get(path, headers) {
            return this.json(path, headers ? { headers } : undefined);
        },

        send(path, method, body, headers) {
            const options = { method };
            if (body !== undefined) {
                options.headers = { 'Content-Type': 'application/json', ...(headers || {}) };
                options.body = JSON.stringify(body);
            } else if (headers) {
                options.headers = headers;
            }
            return this.json(path, options);
        },

        post(path, body, headers) {
            return this.send(path, 'POST', body, headers);
        },

        patch(path, body, headers) {
            return this.send(path, 'PATCH', body, headers);
        },

        del(path, body, headers) {
            return this.send(path, 'DELETE', body, headers);
        },
    };
}

const AIHttp = jsonDoor(AI_BASE);

/* The product's own routes (a chart render, a page setting): the same door without the prefix. */
const ProductHttp = jsonDoor('');

Object.assign(AIWorkspace, {
    async _loadBootstrap() {
        const settings = AISettings.load();
        const provider = this._provider || settings.provider;
        const model = this._model || AISettings.modelFor(provider, null);
        /* Switching provider/model calls this again while the previous answer is still in flight.
           Without a sequence, the OLDER answer landed last and reset `_provider`/`_model` to what
           the user had just moved away from — the chip said one model while the request, and the
           key check, used another. Only the newest call may write the state. */
        this._bootstrapSeq = (this._bootstrapSeq || 0) + 1;
        const seq = this._bootstrapSeq;
        try {
            const { data } = await AIHttp.get('/bootstrap?provider=' + encodeURIComponent(provider) + '&model=' + encodeURIComponent(model));
            if (seq !== this._bootstrapSeq) return;
            /* An answer about the provider this page has already moved away from must not move the
               picker back: `provider` is captured at request time, and a switch plus a model-list
               refresh while it was in flight is exactly the case only the sequence guard missed. */
            if (this._provider !== provider) return;
            this._bootstrap = data;
            const ids = (data.providers || []).map((item) => item.id);
            this._provider = ids.includes(provider) ? provider : (ids[0] || 'deepseek');
            this._model = AISettings.modelFor(this._provider, data.providers);
            this._skills = Array.isArray(settings.skills) ? settings.skills.slice() : [];
            if (this._conversationId && data.conversations) {
                const current = data.conversations.find((row) => row.id === this._conversationId);
                if (current && Array.isArray(current.skills)) this._skills = current.skills.slice();
            }
            this._scope = data.settings?.context_scope || settings.scope || 'summary';
            /* 联网搜索默认跟随服务端设置：只有这个浏览器从没选过时才采纳，动手点过开关的浏览器
               保留自己的选择（一次点击不该被下一次刷新改回去）。 */
            if (data.settings && !AISettings.has('search')) {
                AISettings.save({ search: !!data.settings.web_search_default });
            }
            this._renderProviderOptions();
            this._renderSkillOptions();
            this._renderSessions();
            this._renderSide();
            this._renderWorkspace();
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    async mountArtifactGroup(groupId) {
        if (!groupId) return;
        try {
            const conversationId = await this._ensureConversation();
            const { data } = await AIHttp.post('/conversations/' + encodeURIComponent(conversationId) + '/workspace', {
                group_id: groupId,
            });
            if (!data.ok) throw new Error(data.error || 'workspace failed');
            this._workspace = data.workspace || null;
            this._toast(I18n.t('ai.workspaceMounted'));
        } catch (error) {
            this._toast(error.message || I18n.t('ai.error'));
        }
    },

    async _loadRefs() {
        this._refTimer = null;
        try {
            const { data } = await AIHttp.get('/references?q=' + encodeURIComponent(this._refQuery || ''));
            this._refResults = data.ok ? (data.references || []) : [];
        } catch (error) {
            this._refResults = [];
        }
        this._refIndex = 0;
        this._renderRefMenu();
    },

    /* ── recipes ─────────────────────────────────────────────────────────── */

    async _loadRecipe() {
        const conversationId = this._conversationId;
        if (!conversationId) {
            this._recipe = null;
            this._renderRecipe();
            return;
        }
        try {
            const { data } = await AIHttp.get('/recipes?conversation_id=' + encodeURIComponent(conversationId));
            if (this._conversationId !== conversationId) return;
            this._recipe = data && data.ok ? (data.active || null) : this._recipe;
        } catch (error) {
            /* A picker that cannot answer leaves the last state; it is not the run's truth. */
        }
        this._renderRecipe();
    },

    async _skipRecipeStep() {
        const conversationId = this._conversationId;
        if (!conversationId || !this._recipe) return;
        try {
            const { response, data } = await AIHttp.post('/recipes/skip', { conversation_id: conversationId });
            if (!response.ok || data.ok === false) throw new Error(data.error || 'HTTP ' + response.status);
            this._recipe = data.recipe || null;
            this._renderRecipe();
        } catch (error) {
            this._toast(error.message || I18n.t('ai.error'));
        }
    },

    async _loadSpend() {
        const provider = this._provider || '';
        const key = AISettings.keyFor(provider);
        if (key) {
            try {
                const { data } = await AIHttp.get('/providers/' + encodeURIComponent(provider) + '/balance', {
                    'X-Provider-Key': key,
                });
                this._balance = data.ok ? data : null;
            } catch (error) {
                this._balance = null;
            }
        } else {
            this._balance = null;
        }
        if (this._conversationId) {
            try {
                const { data } = await AIHttp.get('/conversations/' + encodeURIComponent(this._conversationId) + '/usage');
                this._convoUsage = data.ok ? data.usage : null;
            } catch (error) {
                this._convoUsage = null;
            }
        } else {
            this._convoUsage = null;
        }
        this._renderSide();
    },

    async _applyMonitor(artifactId, auto) {
        const artifact = (this._current?.artifacts || []).find((item) => item.id === artifactId);
        if (!artifact) return;
        try {
            const conversationId = await this._ensureConversation();
            const { data } = await AIHttp.post('/monitors', {
                conversation_id: conversationId,
                spec: artifact.payload || {},
                auto_analyze: !!auto,
            });
            if (!data.ok) throw new Error(data.error || 'monitor failed');
            this._bootstrap.monitors = [data.monitor, ...(this._bootstrap.monitors || [])];
            this._renderSide();
            this._toast(I18n.t('ai.monitor.armed'));
        } catch (error) {
            this._toast(I18n.t('ai.monitor.failed') + ': ' + error.message);
        }
    },

    async _disarmMonitor(monitorId) {
        try {
            await AIHttp.del('/monitors/' + encodeURIComponent(monitorId));
        } catch (error) {
            /* the row may already be retired; the list refresh below tells the truth */
        }
        this._bootstrap.monitors = (this._bootstrap?.monitors || []).filter((item) => item.id !== monitorId);
        this._renderSide();
    },

    /* Re-read only the grant list: a full conversation reload would repaint the live transcript. */
    async _loadDatasetGrants() {
        if (!this._conversationId) return;
        try {
            const { data } = await AIHttp.get('/conversations/' + encodeURIComponent(this._conversationId));
            if (!data.ok) return;
            this._grants = data.dataset_grants || [];
            this._renderSide();
        } catch (error) {
            /* The side panel is informational; the next conversation load asks again. */
        }
    },

    async _revokeDatasetGrant(datasetId) {
        if (!this._conversationId) return;
        const before = this._grants;
        this._grants = (this._grants || []).filter((row) => row.dataset_id !== datasetId);
        this._renderSide();
        try {
            const { data } = await AIHttp.del(
                '/conversations/' + encodeURIComponent(this._conversationId) +
                '/dataset-grants/' + encodeURIComponent(datasetId)
            );
            if (data.ok) {
                this._grants = data.dataset_grants || [];
            } else {
                this._grants = before;
                this._toast(data.error || I18n.t('ai.error'));
            }
        } catch (error) {
            /* The server may have already dropped the grant; keeping the local removal is honest
               for this page, and the next conversation load reads the registry again. */
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
        this._renderSide();
    },

    async _refreshConversations() {
        try {
            const params = new URLSearchParams();
            if (this._sessionQuery) params.set('q', this._sessionQuery);
            if (this._showArchived) params.set('archived', '1');
            const suffix = params.toString() ? '?' + params.toString() : '';
            const { data } = await AIHttp.get('/conversations' + suffix);
            if (data.ok && this._bootstrap) {
                this._bootstrap.conversations = data.conversations || [];
                this._renderSessions();
            }
        } catch (e) {
            /* the transcript is still usable when the list refresh fails */
        }
    },

    async _toggleConversationPin(id) {
        const row = (this._bootstrap?.conversations || []).find((item) => item.id === id);
        if (!row) return;
        try {
            await AIHttp.patch('/conversations/' + encodeURIComponent(id), { pinned: !row.pinned });
            await this._refreshConversations();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _toggleConversationArchive(id) {
        const row = (this._bootstrap?.conversations || []).find((item) => item.id === id);
        if (!row) return;
        const archiving = !row.archived;
        try {
            await AIHttp.patch('/conversations/' + encodeURIComponent(id), { archived: archiving });
            /* The open conversation just left the list: keep the reader on a chat that exists. */
            if (archiving && this._conversationId === id) this.newChat();
            await this._refreshConversations();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _exportConversation(id) {
        let format = 'md';
        if (typeof showDialog === 'function') {
            const choice = await showDialog({
                message: I18n.t('ai.exportHint'),
                buttons: [
                    { label: I18n.t('ai.exportMarkdown'), value: 'md', primary: true },
                    { label: I18n.t('ai.exportJson'), value: 'json' },
                    { label: I18n.t('ai.close'), value: '' },
                ],
                cancelValue: '',
            });
            if (!choice) return;
            format = choice;
        }
        const link = document.createElement('a');
        link.href = AIHttp.url('/conversations/' + encodeURIComponent(id) + '/export?format=' + encodeURIComponent(format));
        link.setAttribute('download', '');
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
    },

    async _deleteConversation(id) {
        if (!(await this._confirm(I18n.t('ai.deleteConfirm')))) return;
        try {
            const { response, data } = await AIHttp.del('/conversations/' + encodeURIComponent(id));
            if (!response.ok || data.ok === false) throw new Error(data.error || 'HTTP ' + response.status);
            if (this._conversationId === id) this.newChat();
            this._refreshConversations();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _renameConversation(id) {
        const title = await this._prompt(I18n.t('ai.renamePrompt'), '');
        if (!title) return;
        try {
            const { response, data } = await AIHttp.patch('/conversations/' + encodeURIComponent(id), { title });
            if (!response.ok || data.ok === false) throw new Error(data.error || 'HTTP ' + response.status);
            this._refreshConversations();
        } catch (error) {
            this._toast(error.message || I18n.t('ai.error'));
        }
    },

    async _saveSettings() {
        const key = this._dom.panel.querySelector('[data-ai-key]');
        if (key) AISettings.setKey(this._provider, key.value.trim());
        AISettings.setProvider(this._provider);
        AISettings.setModel(this._provider, this._model);
        this._toast(I18n.t('ai.saved'));
        await this._loadBootstrap();
        this._showChat(true);
    },

    async _refreshModels() {
        const key = AISettings.keyFor(this._provider);
        try {
            const { data } = await AIHttp.get('/providers/' + encodeURIComponent(this._provider) + '/models', {
                'X-Provider-Key': key,
            });
            if (!data.ok) throw new Error(data.error || 'models failed');
            const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
            if (provider) provider.models = data.models.map((item) => ({ id: item.id, label: item.label || item.id, capabilities: provider.capabilities || [] }));
            this._renderSettings();
            this._toast(I18n.t('ai.refreshModelsBtn') + ': ' + (data.models || []).length);
        } catch (error) {
            this._toast(I18n.t('ai.testFail') + ': ' + error.message);
        }
    },

    async _testProvider() {
        const keyInput = this._dom.panel.querySelector('[data-ai-key]');
        const key = keyInput ? keyInput.value.trim() : AISettings.keyFor(this._provider);
        const result = this._dom.panel.querySelector('[data-ai-test-result]');
        if (result) result.textContent = I18n.t('ai.testing');
        try {
            const { data } = await AIHttp.post('/providers/' + encodeURIComponent(this._provider) + '/test', {
                model: this._model,
                api_key: key,
            });
            if (result) result.textContent = data.ok ? I18n.t('ai.testOk', { ms: data.latency_ms }) : I18n.t('ai.testFail') + ': ' + (data.error || '');
        } catch (error) {
            if (result) result.textContent = I18n.t('ai.testFail') + ': ' + error.message;
        }
    },

    /* One attachment per request (the endpoint takes one), so a multi-file pick is a loop that
       keeps going: a refused file must not throw away the ones that already uploaded. Failures are
       collected and reported together — a toast per file would replace the previous one. */
    async _uploadFiles(files, key) {
        const rows = Array.from(files || []).filter(Boolean);
        if (!rows.length) return;
        const apiKey = key === undefined ? this._attachKey() : key;
        if (apiKey === null) return;
        this._uploading = true;
        this._renderToggles();
        let added = 0;
        let datasetImported = false;
        const failures = [];
        try {
            const conversationId = await this._ensureConversation();
            for (const file of rows) {
                try {
                    const form = new FormData();
                    form.append('file', file);
                    form.append('conversation_id', conversationId);
                    form.append('provider', this._provider);
                    form.append('api_key', apiKey);
                    const { data } = await AIHttp.json('/files', { method: 'POST', body: form });
                    if (!data.ok) throw new Error(data.error || 'upload failed');
                    if (data.dataset) {
                        /* A big table: the server registered it as a dataset instead of sending every
                           row to the model. Reference it, so the assistant reads a bounded slice. */
                        this._pickRef('dataset', data.dataset.dataset_id, data.dataset.name);
                        this._toast(I18n.t('ai.datasetFromUpload', { name: data.dataset.name, rows: data.dataset.rows }));
                        datasetImported = true;
                    } else {
                        this._attachments.push(data.attachment);
                    }
                    added += 1;
                } catch (error) {
                    failures.push({ name: file.name || '', reason: error.message });
                }
            }
        } catch (error) {
            failures.push({ name: '', reason: error.message });
        } finally {
            this._uploading = false;
            this._renderAttachments();
            this._renderToggles();
        }
        if (failures.length) {
            const first = failures[0];
            this._toast(
                added
                    ? I18n.t('ai.attachPartial', { saved: added, failed: failures.length })
                    : (first.name ? first.name + ': ' : '') + first.reason
            );
        } else if (added && !datasetImported) {
            this._toast(I18n.t('ai.saved'));
        }
    },

    async _ensureConversation() {
        if (this._conversationId) return this._conversationId;
        const { data } = await AIHttp.post('/conversations', {
            provider: this._provider,
            model: this._model,
            skills: this._skills || [],
        });
        if (!data.ok) throw new Error(data.error || 'conversation failed');
        this._conversationId = data.conversation.id;
        if (this._bootstrap) {
            this._bootstrap.conversations = [data.conversation, ...(this._bootstrap.conversations || [])];
            this._renderSessions();
        }
        return this._conversationId;
    },

    async _removeAttachment(id) {
        this._attachments = this._attachments.filter((row) => row.id !== id);
        this._renderAttachments();
        try {
            await AIHttp.del('/files/' + encodeURIComponent(id), { api_key: AISettings.keyFor(this._provider) });
        } catch (e) {
            /* local chip removal is enough; the server row is cleaned on the next delete */
        }
    },
});
