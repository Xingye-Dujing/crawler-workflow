/* The conversations list and the side panel: context, dataset grants, monitors, the agent trace and
 * the spend block.
 *
 * Every section prints the server's last answer and never a browser guess, including the model that
 * answered a saved conversation and the number of secrets a context had removed.
 */

Object.assign(AIWorkspace, {
    _renderSessions() {
        if (!this._dom.sessions) return;
        const rows = this._bootstrap?.conversations || [];
        const archived = !!this._showArchived;
        const query = this._sessionQuery || '';
        /* The search box lives inside this repainted container, so a refresh triggered by typing
           would otherwise drop the caret after the first character. Remember it and put it back. */
        const active = document.activeElement;
        const typing = !!(active && active.hasAttribute && active.hasAttribute('data-ai-session-search'));
        const caret = typing ? active.selectionStart : null;
        const rowHtml = (row) => {
            const id = AIRender.escape(row.id);
            const rename = AIRender.escape(I18n.t('ai.rename'));
            const remove = AIRender.escape(I18n.t('ai.delete'));
            const pinLabel = AIRender.escape(I18n.t(row.pinned ? 'ai.unpinConversation' : 'ai.pinConversation'));
            const exportLabel = AIRender.escape(I18n.t('ai.exportConversation'));
            const archiveLabel = AIRender.escape(I18n.t(archived ? 'ai.restoreConversation' : 'ai.archiveConversation'));
            const sessionModel = [row.provider, row.model].filter(Boolean).join(' / ');
            return (
                '<div class="ai-session-row' + (row.pinned ? ' pinned' : '') + '">' +
                '<button type="button" class="ai-session ' + (row.id === this._conversationId ? 'selected' : '') + '" data-ai-conversation="' + id + '"' +
                (sessionModel ? ' title="' + AIRender.escape(sessionModel) + '"' : '') + '>' +
                '<span class="ai-session-text">' +
                '<span class="ai-session-title">' + (row.pinned ? '<span class="ai-session-pin">★</span>' : '') + AIRender.escape(row.title || I18n.t('ai.noConversation')) + '</span>' +
                (sessionModel ? '<span class="ai-session-model">' + AIRender.escape(sessionModel) + '</span>' : '') +
                '</span>' +
                '<span class="ai-session-meta">' + AIRender.escape(String(row.message_count || 0)) + '</span>' +
                '</button>' +
                '<span class="ai-session-actions">' +
                '<button type="button" class="ai-icon-btn' + (row.pinned ? ' active' : '') + '" data-ai-pin-conversation="' + id + '" title="' + pinLabel + '" aria-label="' + pinLabel + '" aria-pressed="' + (row.pinned ? 'true' : 'false') + '">★</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-rename-conversation="' + id + '" title="' + rename + '" aria-label="' + rename + '">✎</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-export-conversation="' + id + '" title="' + exportLabel + '" aria-label="' + exportLabel + '">⤓</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-archive-conversation="' + id + '" data-ai-archived="' + (archived ? '1' : '0') + '" title="' + archiveLabel + '" aria-label="' + archiveLabel + '">' + (archived ? '↩' : '▤') + '</button>' +
                '<button type="button" class="ai-icon-btn" data-ai-delete-conversation="' + id + '" title="' + remove + '" aria-label="' + remove + '">×</button>' +
                '</span></div>'
            );
        };
        const groups = new Map();
        for (const row of rows) {
            const key = String(row.workspace_group || row.workspace_dir || 'default');
            const label = String(row.workspace_label || (row.workspace_dir ? String(row.workspace_dir).split(/[\\/]/).pop() : I18n.t('ai.workspaceDefault')));
            if (!groups.has(key)) groups.set(key, { key, label, rows: [] });
            groups.get(key).rows.push(row);
        }
        const items = Array.from(groups.values()).map((group) => {
            const open = this._collapsedWorkspace ? !this._collapsedWorkspace[group.key] : true;
            return '<section class="ai-session-group">' +
                '<button type="button" class="ai-session-group-head" data-ai-workspace-group="' + AIRender.escape(group.key) + '" aria-expanded="' + (open ? 'true' : 'false') + '">' +
                '<span class="ai-session-group-icon">▣</span>' +
                '<span class="ai-session-group-label">' + AIRender.escape(group.label) + '</span>' +
                '<span class="ai-hint">' + group.rows.length + '</span></button>' +
                (open ? group.rows.map(rowHtml).join('') : '') +
                '</section>';
        }).join('');
        const emptyKey = query ? 'ai.noSessionsMatch' : archived ? 'ai.archivedEmpty' : 'ai.noSessions';
        this._dom.sessions.innerHTML =
            '<div class="ai-sessions-head"><strong>' + AIRender.escape(I18n.t('ai.sessions')) + '</strong>' +
            '<button type="button" class="ai-ghost" data-ai-new-session="1">' + AIRender.escape(I18n.t('ai.newChat')) + '</button></div>' +
            '<label class="ai-session-search"><input class="ai-input" type="search" data-ai-session-search value="' + AIRender.escape(query) + '" placeholder="' + AIRender.escape(I18n.t('ai.searchSessions')) + '" /></label>' +
            '<div class="ai-session-filter"><button type="button" class="ai-ghost' + (archived ? ' selected' : '') + '" data-ai-toggle-archived="1" aria-pressed="' + (archived ? 'true' : 'false') + '">' + AIRender.escape(I18n.t('ai.archived')) + '</button></div>' +
            '<div class="ai-session-list">' + (items || '<p class="ai-hint">' + AIRender.escape(I18n.t(emptyKey)) + '</p>') + '</div>';
        if (typing) {
            const box = this._dom.sessions.querySelector('[data-ai-session-search]');
            if (box) {
                box.focus();
                if (caret !== null && caret !== undefined) box.setSelectionRange(caret, caret);
            }
        }
    },

    _renderSide() {
        if (!this._dom.side) return;
        const meta = this._contextMeta || {};
        const preview = this._contextPreview
            ? '<section class="ai-side-block ai-context-preview-block"><h3>' +
              AIRender.escape(I18n.t('ai.contextPreview')) + '</h3>' +
              '<button type="button" class="ai-ghost" data-ai-context-preview="1">' +
              AIRender.escape(I18n.t('ai.contextHide')) + '</button>' +
              '<pre class="ai-code ai-context-preview">' + AIRender.escape(this._contextPreview) + '</pre></section>'
            : '';
        const previewLabel = this._contextPreview ? 'ai.contextHide' : 'ai.contextPreview';
        const items = (meta.items || []).map((item) => '<li>' + AIRender.escape(item.title) + ' <span class="ai-hint">' + AIRender.escape(I18n.t('ai.chars', { n: item.chars || 0 })) + '</span></li>').join('');
        /* What was NOT sent is part of the answer: a context cut by the replay budget or by the
           overall budget changed what the model could have known, and silence reads as “it saw
           everything”. */
        const omitted = (meta.omitted || []).filter(Boolean);
        const history = meta.history || {};
        const memories = meta.memories || {};
        const contextNotes =
            (history.dropped
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextHistoryCut', { n: history.dropped, window: history.window || 0 })) + '</p>'
                : '') +
            (memories.omitted
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextMemoryCut', { n: memories.omitted, shown: memories.shown || 0 })) + '</p>'
                : '') +
            (meta.replay_truncated
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextReplayCut', { n: meta.replay_chars || 0 })) + '</p>'
                : '') +
            (omitted.length
                ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextOmitted', { items: omitted.join('、') })) + '</p>'
                : '');
        /* A scrubbed secret is a fact about what the model received, not a silent internal step.
           The count is the only thing the server reports — never the matched value. */
        const redacted = meta.redacted || {};
        const redactedCount = Object.keys(redacted).reduce(function (sum, key) {
            return sum + (Number(redacted[key]) || 0);
        }, 0);
        const redactedNote = redactedCount
            ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.contextRedacted', { n: redactedCount })) + '</p>'
            : '';
        const plan = (this._plan || []).map((step) =>
            '<li class="ai-trace-step ' + (step.status || 'pending') + '"><span class="ai-trace-dot"></span>' + AIRender.escape(step.title) + '</li>'
        ).join('');
        const usage = this._usage ? AIRender.usage(this._usage) : '';
        const monitors = (this._bootstrap?.monitors || [])
            .filter((item) => item.status === 'armed' && (!item.conversation_id || item.conversation_id === this._conversationId));
        /* A data grant is the server's memory of what this conversation was allowed to read. It is
           listed with what was spent and a revoke button; the browser never decides it. */
        const grantRows = (this._grants || []).map((row) => {
            const max = Number(row.max_rows) || 0;
            const used = Number(row.rows_read) || 0;
            const usage = max > 0
                ? I18n.t('ai.datasetGrantUsage', { used: used, max: max })
                : I18n.t('ai.datasetGrantUnlimited', { used: used });
            return '<li class="ai-monitor-row"><span class="ai-monitor-text">' +
                AIRender.escape(row.name || row.dataset_id) +
                ' <span class="ai-hint">' + AIRender.escape(usage) + '</span></span>' +
                '<button type="button" class="ai-ghost" data-ai-revoke-grant="' + AIRender.escape(row.dataset_id) + '">' +
                AIRender.escape(I18n.t('ai.datasetGrantRevoke')) + '</button></li>';
        }).join('');
        const monitorRows = monitors.map((item) => {
            const spec = item.spec || {};
            const title = spec.note || (spec.events || []).join(', ') || I18n.t('ai.monitor.notice');
            return '<li class="ai-monitor-row"><span class="ai-monitor-text">' + AIRender.escape(title) + '</span>' +
                (item.auto_analyze ? '<span class="ai-chip">' + AIRender.escape(I18n.t('ai.monitor.autoTag')) + '</span>' : '') +
                '<button type="button" class="ai-ghost" data-ai-disarm-monitor="' + AIRender.escape(item.id) + '">' + AIRender.escape(I18n.t('ai.monitor.disarm')) + '</button></li>';
        }).join('');
        this._dom.side.innerHTML =
            preview +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.context')) + '</h3>' +
            (meta.scope ? '<div class="ai-chip-row"><span class="ai-chip">' + AIRender.escape(meta.scope) + '</span><span class="ai-chip">' + AIRender.escape(I18n.t('ai.contextTokens', { tokens: meta.tokens || 0, chars: meta.chars || 0 })) + '</span></div>' : '') +
            '<ul class="ai-context-list">' + (items || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.contextEmpty')) + '</li>') + '</ul>' + contextNotes + redactedNote +
            '<div class="ai-context-actions"><button type="button" class="ai-ghost" data-ai-context-preview="1">' + AIRender.escape(I18n.t(previewLabel)) + '</button></div>' +
            '<div class="ai-context-fields"><label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.datasetId')) + '</span><input class="ai-input" data-ai-manual="dataset_id" value="' + AIRender.escape(AIContext.manual.dataset_id || '') + '" /></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.runId')) + '</span><input class="ai-input" data-ai-manual="run_id" value="' + AIRender.escape(AIContext.manual.run_id || '') + '" /></label>' +
            '<button type="button" class="ai-ghost" data-ai-context-apply="1">' + AIRender.escape(I18n.t('ai.applyContext')) + '</button></div>' +
            '</section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.datasetGrants')) + '</h3>' +
            '<ul class="ai-monitor-list">' + (grantRows || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.datasetGrantEmpty')) + '</li>') + '</ul></section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.monitor.heading')) + '</h3>' +
            '<ul class="ai-monitor-list">' + (monitorRows || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.monitor.empty')) + '</li>') + '</ul>' +
            '<button type="button" class="ai-ghost" data-ai-monitor-new="1">' + AIRender.escape(I18n.t('ai.monitor.build.new')) + '</button></section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.agentTrace')) + '</h3>' +
            '<ol class="ai-trace">' + (plan || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.planEmpty')) + '</li>') + '</ol></section>' +
            '<section class="ai-side-block ai-spend"><h3>' + AIRender.escape(I18n.t('ai.spend.heading')) +
            '<button type="button" class="ai-ghost" data-ai-spend-refresh="1">' + AIRender.escape(I18n.t('ai.spend.refresh')) + '</button></h3>' +
            this._spendHtml() + '</section>' +
            '<section class="ai-side-block"><h3>' + AIRender.escape(I18n.t('ai.usage')) + '</h3>' + (usage || '<p class="ai-hint">—</p>') + '</section>';
    },

    /* The conversation's own numbers: which models it used, the tokens, how much of the input came
       back from the provider's prefix cache, and (when the provider publishes prices) the money.
       Everything here is the server's answer — a token count is a fact, a price is the provider's. */
    _spendHtml() {
        const rows = [];
        const money = (amount, currency, digits) => {
            if (amount === null || amount === undefined) return '—';
            const code = String(currency || '').toUpperCase();
            const symbol = code === 'CNY' ? '¥' : (code === 'USD' ? '$' : '');
            const places = Number.isFinite(digits) ? digits : (Number(amount) < 0.01 ? 6 : 4);
            return symbol + Number(amount).toFixed(places);
        };
        const balance = this._balance;
        if (balance && balance.supported) {
            const lines = (balance.balances || []).map((row) => {
                const label = row.currency || balance.currency || '';
                return '<li><span>' + AIRender.escape(I18n.t('ai.spend.balance')) + ' · ' + AIRender.escape(label) + '</span><b>' +
                    AIRender.escape(money(row.total, row.currency || label, 2)) + '</b></li>';
            }).join('');
            rows.push(
                '<ul class="ai-spend-rows">' + (lines || '<li class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.noBalance')) + '</li>') +
                '</ul>' + (balance.available === false ? '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.unavailable')) + '</p>' : '')
            );
        } else if (balance && balance.supported === false) {
            rows.push('<p class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.unsupported')) + '</p>');
        }
        const usage = this._convoUsage;
        if (usage && (usage.total_tokens || usage.calls)) {
            const models = (usage.models || []).map((row) => (row.provider ? row.provider + ' / ' : '') + row.model).filter(Boolean);
            if (models.length) {
                rows.push('<ul class="ai-spend-rows"><li><span>' + AIRender.escape(I18n.t('ai.spend.models')) + '</span><b>' +
                    AIRender.escape(models.join('、')) + '</b></li></ul>');
            }
            rows.push(
                '<ul class="ai-spend-rows">' +
                '<li><span>' + AIRender.escape(I18n.t('ai.spend.input')) + '</span><b>' + usage.prompt_tokens + '</b></li>' +
                '<li><span>' + AIRender.escape(I18n.t('ai.spend.output')) + '</span><b>' + usage.completion_tokens + '</b></li>' +
                '<li><span>' + AIRender.escape(I18n.t('ai.spend.cacheRate')) + '</span><b>' + (Math.round((usage.cache_hit_rate || 0) * 1000) / 10) + '%</b></li>' +
                (usage.cost === null || usage.cost === undefined
                    ? ''
                    : '<li><span>' + AIRender.escape(I18n.t('ai.spend.cost')) + ' <span class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.estimated')) + '</span></span><b>' + AIRender.escape(money(usage.cost, usage.currency)) + '</b></li>') +
                '</ul>'
            );
        } else if (this._conversationId) {
            rows.push('<p class="ai-hint">' + AIRender.escape(I18n.t('ai.spend.empty')) + '</p>');
        }
        return rows.join('') || '<p class="ai-hint">—</p>';
    },

    toggleWorkspaceGroup(key) {
        this._collapsedWorkspace = this._collapsedWorkspace || {};
        this._collapsedWorkspace[key] = !this._collapsedWorkspace[key];
        this._renderSessions();
    },

    async selectConversation(id) {
        if (!id) return;
        /* The turn in flight owns this DOM. Re-selecting the same conversation while it streams
           (which is what reopening the dock does) would repaint from the store and drop the live
           bubble, so the answer would continue in a second bubble. */
        if (this._sending && String(id) === String(this._conversationId)) return;
        this._conversationId = id;
        this._mode = 'chat';
        /* Selecting a conversation is a request to READ it: a settings/studio panel that was up
           must give the column back instead of hiding the transcript the click asked for. */
        this._showChat();
        this._editingSkill = null;
        /* A slow answer for the conversation the user just left must not replace the one they
           clicked next. Every await below is preceded by one token check; the last click wins. */
        const token = (this._selectToken = (this._selectToken || 0) + 1);
        try {
            const { response, data } = await AIHttp.get('/conversations/' + encodeURIComponent(id));
            if (token !== this._selectToken) return;
            if (!data.ok) {
                /* A conversation deleted here or in another tab: forget it instead of reopening a
                   chat that no longer exists on every reload. */
                if (response.status === 404) {
                    this._conversationId = '';
                    this._rememberConversation('');
                    this._grants = [];
                    this._renderWelcome();
                    return;
                }
                throw new Error(data.error || 'not found');
            }
            this._messages = data.messages || [];
            this._turns = data.turns || [];
            this._turnsById = new Map(this._turns.map((turn) => [String(turn.id), turn]));
            this._grants = data.dataset_grants || [];
            this._conversationId = data.conversation.id;
            this._rememberConversation(this._conversationId);
            const isTrace = String(data.conversation.skill || '') === 'node_trace' ||
                (data.messages || []).some((message) => String((message.meta || {}).skill || '') === 'node_trace');
            const savedProvider = String(data.conversation.provider || '');
            const savedModel = String(data.conversation.model || '');
            const startMeta = (this._messages.find((m) => (m.meta || {}).kind === 'trace_start') || {}).meta || {};
            /* The header/chip name the model that ACTUALLY answered this conversation. For a node
               trace that is a display label ("local BERT", "SnowNLP"), not a provider id — read the
               label from the intro row's meta so it survives a later provider/model PATCH. */
            const chipProvider = isTrace && startMeta.provider_label ? String(startMeta.provider_label) : savedProvider;
            const chipModel = isTrace && startMeta.model_label ? String(startMeta.model_label) : savedModel;
            this._conversationModel = [chipProvider, chipModel].filter(Boolean).join(' / ');
            if (this._dom.modelChip) this._dom.modelChip.textContent = this._conversationModel || '—';
            /* The picker is for the NEXT message and must stay on a real catalog provider. A node
               trace's provider is often only a display label; mirroring it here used to select a
               non-existent provider, empty the model list and make every follow-up send fail. Only
               mirror when the stored value is a known id. */
            const knownIds = (this._bootstrap?.providers || []).map((item) => String(item.id));
            if (savedProvider && knownIds.includes(savedProvider)) {
                this._provider = savedProvider;
                if (savedModel) this._model = savedModel;
                this._renderProviderOptions();
            } else if (!isTrace && savedModel) {
                this._model = savedModel;
                this._renderModelOptions();
            }
            this._renderMessages(data.pending_questions || []);
            if (data.active_turn && data.active_turn.id) this._reattachTurn(data.active_turn.id);
            this._renderSessions();
            this._renderSide();
            this._loadRecipe();
            this._loadSpend();
            if (this._dom.title) {
                this._dom.title.textContent = data.conversation.title || I18n.t('ai.title');
            }
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    async _confirm(message) {
        if (typeof showDialog !== 'function') return false;
        const answer = await showDialog({
            message,
            buttons: [
                { label: I18n.t('ai.delete'), value: true, primary: true },
                { label: I18n.t('ai.close'), value: false },
            ],
            cancelValue: false,
        });
        return answer === true;
    },

    async _prompt(message, value) {
        if (typeof showDialog !== 'function') return '';
        const answer = await showDialog({
            message,
            input: { placeholder: I18n.t('ai.renamePrompt') },
            buttons: [
                { label: I18n.t('ai.save'), value: true, primary: true, withInput: true },
                { label: I18n.t('ai.close'), value: false },
            ],
            cancelValue: false,
        });
        // A dialog with an input is answered by `{value, input}` only when the button asks for both;
        // reading `answer.value` from a bare `true` made this return '' for every rename.
        if (!answer || answer.value !== true) return '';
        return String(answer.input || '').trim();
    },

});
