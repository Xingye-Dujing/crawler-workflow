/* The composer: the provider / model / skill pickers, the mode switches, attachments and the
 * turn's send and stop path.
 *
 * A composer action never renders the transcript: it hands the words to chat.js's own paint through
 * the shared state, which is why a turn that is still streaming cannot be painted twice.
 */

/* The host label keys are also spelled here so the i18n reachability gate sees the literal keys;
 * the server's `runtime.label_key` remains the value shown, this table only maps kind → key. The
 * composer's runtime chip and the context bar read it; it is declared once, in the first of them. */
const AI_RUNTIME_KEYS = {
    desktop: 'ai.runtime.desktop',
    local_web: 'ai.runtime.local_web',
    cloud: 'ai.runtime.cloud',
};

Object.assign(AIWorkspace, {
    _renderProviderOptions() {
        const providers = this._bootstrap?.providers || [];
        if (this._dom.provider) {
            this._dom.provider.innerHTML = providers.map((item) => {
                const why = item.local_available === false ? (item.why_not_text || I18n.t('ai.noCapability')) : '';
                const title = why ? ' title="' + AIRender.escape(why) + '"' : '';
                return '<option value="' + AIRender.escape(item.id) + '"' + title + (item.id === this._provider ? ' selected' : '') + '' + (item.local_available === false ? ' disabled' : '') + '>' +
                    AIRender.escape(I18n.has(item.label_key) ? I18n.t(item.label_key) : item.id) + (item.local_available === false ? ' — ' + AIRender.escape(why) : '') + '</option>';
            }).join('');
        }
        this._renderModelOptions();
        this._renderToggles();
    },

    _renderModelOptions() {
        const provider = (this._bootstrap?.providers || []).find((item) => item.id === this._provider);
        const models = provider?.models || [];
        if (this._dom.model) {
            this._dom.model.innerHTML = models.map((item) =>
                '<option value="' + AIRender.escape(item.id) + '"' + (item.id === this._model ? ' selected' : '') + '>' +
                AIRender.escape(item.label || item.id) + '</option>'
            ).join('');
        }
        if (this._dom.modelChip) {
            /* Before the bootstrap answer there is no provider row at all; asking `t(undefined)`
               printed an i18n warning on every open. The id is the honest fallback. */
            const label = provider?.label_key && I18n.has(provider.label_key) ? I18n.t(provider.label_key) : this._provider;
            this._dom.modelChip.textContent = label + ' / ' + (this._model || '—');
        }
    },

    _renderSkillOptions() {
        const skills = this._bootstrap?.skills || [];
        if (!this._dom.skill) return;
        const chosen = new Set(this._skills || []);
        this._dom.skill.innerHTML =
            '<option value="auto"' + (chosen.size ? '' : ' selected') + '>' +
            AIRender.escape(I18n.t('ai.skill') + ': ' + I18n.t('ai.skillAuto')) + '</option>' +
            skills.map((skill) => {
                const why = skill.available === false
                    ? (skill.why_not_text || I18n.t('ai.skillUnavailable'))
                    : '';
                const title = why ? ' title="' + AIRender.escape(why) + '"' : '';
                return '<option value="' + AIRender.escape(skill.id) + '"' + title + (chosen.has(skill.id) ? ' selected' : '') + '' + (skill.available === false ? ' disabled' : '') + '>' +
                    AIRender.escape(skill.name || (I18n.has(skill.name_key) ? I18n.t(skill.name_key) : skill.id)) + (skill.available === false ? ' — ' + AIRender.escape(why) : '') + '</option>';
            }).join('');
    },

    _runtimeTitle() {
        /* The chip names the host; its tooltip says which host powers are present here. The
           workspace itself is complete on every host, so only these optional powers are listed. */
        const runtime = this._bootstrap?.runtime;
        if (!runtime) return '';
        const pieces = [I18n.has(runtime.label_key) ? I18n.t(runtime.label_key) : (AI_RUNTIME_KEYS[runtime.kind] ? I18n.t(AI_RUNTIME_KEYS[runtime.kind]) : String(runtime.kind || ''))];
        if (runtime.ollama) pieces.push(I18n.t('ai.runtime.daemon'));
        if (runtime.user_files) pieces.push(I18n.t('ai.runtime.files'));
        if (runtime.local_source) pieces.push(I18n.t('ai.runtime.source'));
        if (runtime.code_plugins) pieces.push(I18n.t('ai.runtime.codePlugins'));
        return pieces.join(' · ');
    },

    _renderAgentMode() {
        const mode = this._agentMode === 'plan' ? 'plan' : 'build';
        for (const [button, value] of [[this._dom.agentPlan, 'plan'], [this._dom.agentBuild, 'build']]) {
            if (!button) continue;
            const on = value === mode;
            button.classList.toggle('selected', on);
            button.setAttribute('aria-pressed', on ? 'true' : 'false');
        }
    },

    setAgentMode(mode) {
        this._agentMode = String(mode) === 'plan' ? 'plan' : 'build';
        AISettings.save({ agentMode: this._agentMode });
        this._renderAgentMode();
        this._toast(I18n.t(this._agentMode === 'plan' ? 'ai.mode.planHint' : 'ai.mode.buildHint'));
    },

    _renderToggles() {
        this._renderAgentMode();
        const provider = (this._bootstrap?.providers || []).find((item) => item.id === this._provider);
        const capabilities = provider?.capabilities || [];
        const thinking = this._thinkingOn();
        const localOnly = !!(provider && provider.local_only);
        const search = !!AISettings.load().search && capabilities.includes('web_search');
        if (this._dom.thinking) {
            this._dom.thinking.classList.toggle('selected', thinking);
            /* Local models never think here: the server forces think=false, so offering a switch
               that does nothing would be a lie. */
            this._dom.thinking.disabled = localOnly || !capabilities.includes('thinking');
            this._dom.thinking.setAttribute('aria-pressed', thinking ? 'true' : 'false');
        }
        if (this._dom.search) {
            this._dom.search.classList.toggle('selected', search);
            this._dom.search.disabled = !capabilities.includes('web_search');
            this._dom.search.setAttribute('aria-pressed', search ? 'true' : 'false');
        }
        if (this._dom.attachBtn) {
            const files = capabilities.includes('files');
            this._dom.attachBtn.disabled = !files || this._uploading || this._sending;
        }
    },

    _renderComposer() {
        this._renderProviderOptions();
        this._renderSkillOptions();
        this._renderToggles();
        this._renderContextBar();
        this._renderAttachments();
    },

    _renderAttachments() {
        if (!this._dom.attachments) return;
        this._dom.attachments.innerHTML = this._attachments.map((row) =>
            '<span class="ai-attachment"><span>' + AIRender.escape(row.name || 'file') + '</span>' +
            '<button type="button" class="ai-attachment-x" data-ai-remove-attachment="' + AIRender.escape(row.id) +
            '" aria-label="' + AIRender.escape(I18n.t('ai.removeAttachment', { name: row.name || 'file' })) + '">×</button></span>'
        ).join('');
    },

    /* ── @ references ─────────────────────────────────────────────────
       Typing `@` names something this account already has, so nothing is uploaded twice: the
       server resolves a dataset/export/workflow into bounded text, and a file uploaded in an
       earlier conversation into its existing file_id. */

    _renderWelcome() {
        if (this._mode !== 'chat' || !this._dom.chat) return;
        if (this._messages.length) return;
        const suggestions = [
            ['diagnose', 'ai.suggest.diagnose'],
            ['analysis', 'ai.suggest.analysis'],
            ['workflow', 'ai.suggest.workflow'],
            ['charts', 'ai.suggest.charts'],
            ['project', 'ai.suggest.project'],
        ].map(([skill, key]) =>
            '<button type="button" class="ai-suggestion" data-ai-suggest="' + skill + '">' + AIRender.escape(I18n.t(key)) + '</button>'
        ).join('');
        this._dom.chat.innerHTML =
            '<section class="ai-welcome">' +
            '<div class="ai-welcome-mark">◌</div>' +
            '<h2>' + AIRender.escape(I18n.t('ai.welcomeTitle')) + '</h2>' +
            '<p>' + AIRender.escape(I18n.t('ai.welcomeBody')) + '</p>' +
            '<div class="ai-suggestions">' + suggestions + '</div>' +
            '</section>';
        this._renderSide();
    },

    _autoGrow() {
        const input = this._dom.input;
        if (!input) return;
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight || 0, 220) + 'px';
        this._syncComposerHeight();
    },

    /* The “back to the latest message” button is anchored ABOVE the composer, and the composer grows
       with the textarea — a fixed `bottom: 96px` put the button on top of the composer's own row.
       Its measured height is published as `--ai-composer-h`, which the stylesheet reads. */
    _syncComposerHeight() {
        const root = this._dom.root;
        if (!root || typeof root.querySelector !== 'function') return;
        const composer = root.querySelector('.ai-composer');
        const rect = composer && composer.getBoundingClientRect ? composer.getBoundingClientRect() : null;
        const height = rect && rect.height ? Math.round(rect.height) : 0;
        if (height > 0) root.style.setProperty('--ai-composer-h', height + 'px');
    },

    async send() {
        const text = (this._dom.input?.value || '').trim();
        /* Any early return inside `_sendText` says why (toast); a throw says why too. Silence is
           what makes a slow turn and a dead button look identical. */
        try {
            await this._sendText(text, {});
        } catch (error) {
            this._toast((I18n.t('ai.error') || '') + ': ' + String((error && error.message) || error));
        }
    },

    async _sendText(text, options) {
        const opts = options || {};
        if (this._sending) {
            if (!opts.monitor) this._toast(I18n.t('ai.busy'));
            return false;
        }
        if (!opts.monitor && !opts.feedback) this._feedbackCount = 0;
        /* A failed-node card belongs to the monitor turn that named the run; a user's own message
           starts a new turn and must not inherit the previous run's nodes. */
        if (!opts.monitor) this._monitorFailed = null;
        const pendingAttachments = opts.monitor ? [] : this._attachments.slice();
        const pendingRefs = opts.monitor ? [] : this._refs.slice();
        if (!text && !pendingAttachments.length && !pendingRefs.length) {
            this._toast(I18n.t('ai.emptyMessage'));
            return false;
        }
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        /* Local-only: a paid provider is refused BEFORE any request leaves the page. This is the
           switch that makes "I only want the free local model" enforceable, not a preference. */
        if (AISettings.load().localOnly && (!provider || !provider.local_only)) {
            this._toast(I18n.t('ai.localOnlyBlocked'));
            return false;
        }
        const key = AISettings.keyFor(this._provider);
        if (provider?.requires_key && !key) {
            this._toast(I18n.t('ai.keyMissing'));
            // A monitor turn has no user watching to fill the key: opening the settings panel every
            // five seconds was the retry loop's visible symptom. Say it once, let the watch give up.
            if (!opts.monitor) this.openSettings();
            return false;
        }
        if (!this._model) {
            this._toast(I18n.t('ai.modelMissing'));
            return false;
        }
        /* Documents no longer need a provider Files API: the server extracts their words. Only an
           image needs the model to SEE — `vision` is a different promise from `files`, and asking
           for the wrong one refused a .txt on a local model. The server re-checks this. */
        const imageAttached = pendingAttachments.some((row) => String(row.mime || '').startsWith('image/'));
        if (imageAttached && !(provider?.capabilities || []).includes('vision')) {
            this._toast(I18n.t('ai.imageUnsupported'));
            return false;
        }
        const context = opts.monitor ? {} : AIContext.collect();
        if (!opts.monitor) {
            this._dom.input.value = '';
            this._autoGrow();
            this._appendUser(text, context, pendingAttachments, { feedback: !!opts.feedback });
            this._attachments = [];
            this._renderAttachments();
            this._refs = [];
            this._renderRefs();
            this._contextPreview = '';
            this._renderSide();
        } else {
            this._appendUser(text, context, [], { monitor_event: opts.monitorEventId });
        }
        this._current = null;
        this._showChat();
        this._beginTurn();
        this._sending = true;
        this._setSending(true);
        /* The reaction is the point: the user must see their message AND a live turn before the
           first byte from the provider, otherwise a slow model looks like a dead button. */
        this._ensureAssistant();
        this._paintAssistant();
        if (this._dom.chat) this._dom.chat.scrollTop = this._dom.chat.scrollHeight;
        const body = {
            conversation_id: this._conversationId || '',
            text,
            provider: this._provider,
            model: this._model,
            api_key: key,
            thinking: this._thinkingOn(),
            web_search: !!AISettings.load().search && (provider?.capabilities || []).includes('web_search'),
            skills: this._selectedSkills(),
            locale: (typeof I18n !== 'undefined' && I18n.lang) || 'zh',
            context,
            scope: this._scope,
            attachments: pendingAttachments.map((row) => row.id),
            references: pendingRefs.filter((row) => row.kind !== 'skill').map((row) => ({ kind: row.kind, id: row.id })),
            monitor_event_id: opts.monitorEventId || '',
            feedback: !!opts.feedback,
            agent_mode: this._agentMode || 'build',
        };
        try {
            await this._stream('/chat', body);
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            this._noteCutStream();
        }
        return true;
    },

    _setSending(sending) {
        if (this._dom.send) this._dom.send.disabled = sending;
        if (this._dom.stop) this._dom.stop.hidden = !sending;
        /* The composer stays ENABLED while a turn runs: disabling it threw away the caret and the
           user could not even draft the next message. A second send is refused by `_sendText` with
           one toast, which is a better answer than a dead input. */
        if (this._dom.input) this._dom.input.disabled = false;
        this._renderToggles();
        /* A closed turn no longer owns a conversation: the next one states its own. The turn id is
           how a repaint recognizes the bubble this stream is still appending to. */
        if (!sending) {
            this._streamConversation = '';
            this._streamTurnId = '';
        }
        /* The live line follows the same switch as the buttons: it is shown exactly while a turn is
           open. One funnel, so no ending path can leave "生成中" painted on a finished answer. */
        this._renderStatus();
    },

    async stop() {
        this._turnEnded = true;
        if (this._abort) this._abort.abort();
        try {
            await AIHttp.post('/stop', { conversation_id: this._conversationId });
        } catch (e) {
            /* stopping is best-effort; the stream abort already closed the page side */
        }
        this._sending = false;
        this._setSending(false);
        this._stopClock();
        /* A stopped turn used to end in silence: the bubble just stopped growing. Say it, and say
           that the commands it started went with it (the route stops that conversation's children).
           Once only: the server may also answer the abort with `done`+`cancelled` first. */
        const said = String(I18n.t('ai.stopped'));
        if (this._current && this._current.blocks) {
            if (!this._current.blocks.some((block) => block.type === 'note' && block.text === said)) {
                this._current.blocks.push({ type: 'note', text: said });
            }
            this._paintAssistant();
        }
    },

    async newChat() {
        this._conversationId = '';
        this._rememberConversation('');
        this._openDetails.clear();
        this._messages = [];
        this._current = null;
        this._plan = [];
        this._usage = null;
        this._contextMeta = null;
        this._grants = [];
        this._attachments = [];
        this._recipe = null;
        this._renderRecipe();
        this._mode = 'chat';
        /* A new chat must leave whatever panel was open: the welcome hint is drawn into the
           transcript, and a hidden transcript would look like nothing happened. */
        this._showChat();
        this._renderWelcome();
        this._renderSessions();
        this._renderSide();
        this._renderAttachments();
        if (this._dom.title) this._dom.title.textContent = I18n.t('ai.title');
        if (this._dom.input) this._dom.input.focus();
    },

    /* Remember the choice on the conversation itself, not only in the global settings: each chat
       (especially a node trace) keeps the model that actually belongs to it. */
    _rememberConversationModel() {
        if (!this._conversationId) return;
        AIHttp.patch('/conversations/' + encodeURIComponent(this._conversationId), {
            provider: this._provider,
            model: this._model,
        }).catch(() => {});
    },

    setProviderFromBar(value) {
        this._provider = value;
        AISettings.setProvider(value);
        this._model = AISettings.modelFor(value, this._bootstrap?.providers);
        this._renderModelOptions();
        this._renderToggles();
        this._rememberConversationModel();
        this._loadBootstrap();
    },

    setModelFromBar(value) {
        this._model = value;
        AISettings.setModel(this._provider, value);
        this._rememberConversationModel();
        this._loadBootstrap();
    },

    _selectedSkills() {
        const ids = [];
        for (const id of this._skills || []) if (id && id !== 'auto' && !ids.includes(id)) ids.push(id);
        for (const row of this._refs || []) {
            if (row.kind === 'skill' && !ids.includes(row.id)) ids.push(row.id);
        }
        return ids;
    },

    setSkillsFromBar(values) {
        this._skills = (values || []).filter((id) => id && id !== 'auto');
        AISettings.save({ skills: this._skills });
        if (this._conversationId) {
            AIHttp.patch('/conversations/' + encodeURIComponent(this._conversationId), {
                skills: this._skills,
            }).catch(() => {});
        }
        this._renderSkillOptions();
    },

    /* The local daemon never thinks in this product: qwen3.5 thinks by default, which doubles a
       local turn's wall time and leaks a trace the workspace does not show. The server enforces
       this too; the switch is disabled for local providers. */
    _thinkingOn() {
        const settings = AISettings.load();
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        if (provider && provider.local_only) return false;
        const caps = (provider && provider.capabilities) || [];
        return !!settings.thinking && caps.includes('thinking');
    },

    toggleThinking() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        if (provider && provider.local_only) return;
        const settings = AISettings.load();
        AISettings.save({ thinking: !settings.thinking });
        this._renderToggles();
    },

    toggleSearch() {
        const settings = AISettings.load();
        AISettings.save({ search: !settings.search });
        this._renderToggles();
    },

    /* The attach button, a drop and a paste all need the same answer first: is a key present when
       the provider requires one. `null` means "refused", `''` means "this provider needs no key" —
       a local model used to be unable to attach anything because the empty key read as missing. */
    _attachKey() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        const key = AISettings.keyFor(this._provider);
        if (provider?.requires_key && !key) {
            this._toast(I18n.t('ai.keyMissing'));
            this.openSettings();
            return null;
        }
        return key;
    },

    async attach() {
        const key = this._attachKey();
        if (key === null) return;
        const input = document.createElement('input');
        input.type = 'file';
        input.multiple = true;
        input.accept = '.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.csv,.json,.log,.xlsx,.xls,.png,.jpg,.jpeg,.gif,.webp';
        input.onchange = () => {
            const files = Array.from(input.files || []);
            if (files.length) this._uploadFiles(files, key);
        };
        input.click();
    },

    _hasFileDrag(event) {
        const transfer = event && event.dataTransfer;
        if (!transfer) return false;
        if (transfer.files && transfer.files.length) return true;
        /* Chrome reports no `files` on dragenter; the type list is what says a file is coming. */
        return transfer.types ? Array.from(transfer.types).includes('Files') : false;
    },

    _droppedFiles(event) {
        const transfer = event && event.dataTransfer;
        if (!transfer || !transfer.files || !transfer.files.length) return [];
        return Array.from(transfer.files).filter(Boolean);
    },

    _bindAttachDrop(root) {
        let depth = 0;
        root.addEventListener('dragenter', (event) => {
            if (!this._hasFileDrag(event)) return;
            event.preventDefault();
            depth += 1;
            root.classList.add('ai-drop-active');
        });
        root.addEventListener('dragover', (event) => {
            if (!this._hasFileDrag(event)) return;
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
        });
        root.addEventListener('dragleave', () => {
            /* No file check here: browsers report an empty `dataTransfer.files` on dragleave for
               security, so requiring one left the highlight stuck after the drag left the panel. */
            if (!depth) return;
            depth = Math.max(0, depth - 1);
            if (!depth) root.classList.remove('ai-drop-active');
        });
        root.addEventListener('drop', (event) => {
            const files = this._droppedFiles(event);
            if (!files.length) return;
            event.preventDefault();
            depth = 0;
            root.classList.remove('ai-drop-active');
            this._uploadFiles(files);
        });
    },

});
