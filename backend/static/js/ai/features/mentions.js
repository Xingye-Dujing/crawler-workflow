/* The `@` reference picker, the `/` command menu, the context bar and the server's recipe strip.
 *
 * Three floating menus over the same textarea, so they are read and placed together: only one of
 * them is open at a time, and placing one is what closes the other.
 */

Object.assign(AIWorkspace, {
    /* ─── Slash commands ───
       `/` at the start of the composer is a command palette, the way Codex/Claude Code expose
       actions without hunting through buttons. It is local: no provider call, no new protocol. */

    _commands() {
        return [
            { id: 'folder', label: 'ai.cmd.folder' },
            { id: 'retry', label: 'ai.cmd.retry' },
            { id: 'new', label: 'ai.cmd.new' },
            { id: 'skills', label: 'ai.cmd.skills' },
            { id: 'stop', label: 'ai.cmd.stop' },
        ];
    },

    _onCmdInput() {
        const input = this._dom.input;
        if (!input) return;
        const match = /^\/([a-z]*)$/i.exec(String(input.value || '').trim());
        if (!match) {
            this._closeCmds();
            return;
        }
        this._cmdQuery = match[1].toLowerCase();
        this._cmdRows = this._commands().filter((row) => !this._cmdQuery || row.id.startsWith(this._cmdQuery));
        this._cmdIndex = 0;
        this._cmdOpen = true;
        if (this._refOpen) this._closeRefs();
        this._renderCmdMenu();
    },

    _renderCmdMenu() {
        const menu = this._dom.cmdMenu;
        if (!menu) return;
        if (!this._cmdOpen) {
            menu.hidden = true;
            menu.innerHTML = '';
            return;
        }
        const rows = this._cmdRows || [];
        menu.innerHTML =
            '<div class="ai-ref-head">' + AIRender.escape(I18n.t('ai.cmd.title')) + '</div>' +
            (rows.length
                ? rows.map((row, index) =>
                    '<button type="button" class="ai-ref-row' + (index === this._cmdIndex ? ' active' : '') + '" data-ai-cmd="' + AIRender.escape(row.id) + '">' +
                    '<span class="ai-ref-kind">/' + AIRender.escape(row.id) + '</span>' +
                    '<span class="ai-ref-label">' + AIRender.escape(I18n.t(row.label)) + '</span></button>'
                ).join('')
                : '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.cmd.empty')) + '</div>');
        menu.hidden = false;
    },

    _closeCmds() {
        this._cmdOpen = false;
        this._cmdRows = [];
        if (this._dom.cmdMenu) {
            this._dom.cmdMenu.hidden = true;
            this._dom.cmdMenu.innerHTML = '';
        }
    },

    _onCmdKey(event, composing) {
        if (event.key === 'Escape') {
            event.preventDefault();
            this._closeCmds();
            return true;
        }
        if (!this._cmdRows || !this._cmdRows.length) {
            if (event.key === 'Enter' && !composing) {
                event.preventDefault();
                return true;
            }
            if (event.key === 'Backspace') this._closeCmds();
            return false;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            const delta = event.key === 'ArrowDown' ? 1 : -1;
            this._cmdIndex = (this._cmdIndex + delta + this._cmdRows.length) % this._cmdRows.length;
            this._renderCmdMenu();
            return true;
        }
        if ((event.key === 'Enter' || event.key === 'Tab') && !composing) {
            event.preventDefault();
            this._runCommand(this._cmdRows[this._cmdIndex].id);
            return true;
        }
        return false;
    },

    _runCommand(id) {
        this._closeCmds();
        if (this._dom.input) this._dom.input.value = '';
        if (id === 'folder') this.toggleFolder();
        else if (id === 'retry') this.retry();
        else if (id === 'new') this.newChat();
        else if (id === 'skills') this.openStudio();
        else if (id === 'stop') this.stop();
        this._onRefInput();
    },

    _onRefInput(event) {
        /* Two places accept `@`: the composer and an answer box on a question card. The menu
           belongs to whichever one owns the caret, so a reference picked for an answer lands in
           the answer — never in the composer the user is not looking at. */
        const el = (event && event.target) || this._dom.input;
        if (!el) return;
        const isAnswer = !!(el.hasAttribute && el.hasAttribute('data-ai-custom'));
        if (el !== this._dom.input && !isAnswer) return;
        const match = /(?:^|[\s(])@([^\s@]{0,60})$/.exec(el.value || '');
        if (!match) {
            if (this._refTarget === el) this._closeRefs();
            return;
        }
        this._refTarget = el;
        this._refQuery = match[1];
        this._refOpen = true;
        if (this._dom.refMenu) this._dom.refMenu.hidden = false;
        if (this._refTimer) clearTimeout(this._refTimer);
        this._refTimer = setTimeout(() => this._loadRefs(), 120);
    },

    _refKindLabel(kind) {
        const key = 'ai.ref.' + String(kind || '');
        return I18n.has(key) ? I18n.t(key) : String(kind || '');
    },

    _renderRefMenu() {
        if (!this._dom.refMenu) return;
        if (!this._refOpen) {
            this._dom.refMenu.hidden = true;
            this._dom.refMenu.innerHTML = '';
            return;
        }
        const rows = this._refResults.map((row, index) =>
            '<button type="button" class="ai-ref-row' + (index === this._refIndex ? ' active' : '') + '"' +
            ' data-ai-ref="' + AIRender.escape(row.kind + '|' + row.id) + '">' +
            '<span class="ai-ref-kind">' + AIRender.escape(this._refKindLabel(row.kind)) + '</span>' +
            '<span class="ai-ref-label">' + AIRender.escape(row.label || row.id) + '</span>' +
            '<span class="ai-hint">' + AIRender.escape(row.detail || '') + '</span></button>'
        ).join('');
        this._dom.refMenu.innerHTML =
            '<div class="ai-ref-head">' + AIRender.escape(I18n.t('ai.refsTitle')) + '</div>' +
            (rows || '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.refsEmpty')) + '</div>');
        this._placeRefMenu();
        this._dom.refMenu.hidden = false;
    },

    /* The menu's CSS home is above the composer. An answer box can be anywhere in the transcript,
       so the menu is placed against THAT box's rectangle instead of opening far away at the bottom. */
    _placeRefMenu() {
        const menu = this._dom.refMenu;
        if (!menu || !menu.style) return;
        const target = this._refTarget;
        if (!target || target === this._dom.input || typeof target.getBoundingClientRect !== 'function') {
            menu.style.position = '';
            menu.style.left = '';
            menu.style.right = '';
            menu.style.bottom = '';
            menu.style.width = '';
            return;
        }
        const rect = target.getBoundingClientRect();
        menu.style.position = 'fixed';
        menu.style.left = Math.max(8, rect.left) + 'px';
        menu.style.right = 'auto';
        menu.style.width = Math.max(240, Math.min(rect.width || 320, 420)) + 'px';
        menu.style.bottom = Math.max(8, (window.innerHeight || 800) - rect.top + 6) + 'px';
    },

    /* The menu owns Enter/Arrows/Escape while it is open; true means "handled, do not send". */
    _onRefKey(event, composing) {
        if (event.key === 'Escape') {
            event.preventDefault();
            this._closeRefs();
            return true;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            const total = this._refResults.length;
            if (total) {
                const step = event.key === 'ArrowDown' ? 1 : -1;
                this._refIndex = (this._refIndex + step + total) % total;
                this._renderRefMenu();
            }
            event.preventDefault();
            return true;
        }
        if (event.key === 'Enter' && !event.shiftKey && !composing && this._refResults.length) {
            const row = this._refResults[this._refIndex];
            event.preventDefault();
            if (row) this._pickRef(row.kind, row.id, row.label);
            return true;
        }
        return false;
    },

    _pickRef(kind, id, label) {
        if (!kind || !id) return;
        const target = this._refTarget || this._dom.input;
        if (!target) return;
        const value = String(target.value || '').replace(/@[^\s@]{0,60}$/, '').replace(/\s+$/, '');
        target.value = value ? value + ' ' : '';
        const questionId = target.getAttribute ? target.getAttribute('data-ai-custom') : null;
        const isAnswer = questionId !== null;
        if (isAnswer) {
            const rows = this._answerRefs(questionId);
            if (!rows.some((row) => row.kind === kind && row.id === id)) {
                rows.push({ kind: kind, id: id, label: label || id });
            }
            this._renderAnswerRefs(questionId);
        } else if (!this._refs.some((row) => row.kind === kind && row.id === id)) {
            this._refs.push({kind: kind, id: id, label: label || id});
            this._renderRefs();
        }
        this._closeRefs();
        if (target.focus) target.focus();
    },

    _closeRefs() {
        this._refOpen = false;
        this._refQuery = '';
        if (this._refTimer) {
            clearTimeout(this._refTimer);
            this._refTimer = null;
        }
        if (this._dom.refMenu) {
            this._dom.refMenu.hidden = true;
            this._dom.refMenu.innerHTML = '';
            /* Back to the stylesheet's own position, so the composer's menu is not stuck at an
               answer box's coordinates. */
            if (this._dom.refMenu.style) {
                this._dom.refMenu.style.position = '';
                this._dom.refMenu.style.left = '';
                this._dom.refMenu.style.right = '';
                this._dom.refMenu.style.bottom = '';
                this._dom.refMenu.style.width = '';
            }
        }
        this._refTarget = null;
    },

    _renderRefs() {
        if (!this._dom.refs) return;
        this._dom.refs.innerHTML = this._refs.map((row) =>
            '<span class="ai-ref-chip"><span class="ai-ref-kind">' + AIRender.escape(this._refKindLabel(row.kind)) + '</span>' +
            '<span>' + AIRender.escape(row.label || row.id) + '</span>' +
            '<button type="button" class="ai-attachment-x" data-ai-remove-ref="' + AIRender.escape(row.kind + '|' + row.id) + '" aria-label="Remove ' + AIRender.escape(row.label || row.id) + '">×</button></span>'
        ).join('');
    },

    _renderRecipe() {
        const box = this._dom.recipe;
        if (!box) return;
        const state = this._recipe;
        if (!state || state.status !== 'running' || !state.steps || !state.steps.length) {
            box.hidden = true;
            box.innerHTML = '';
            return;
        }
        const total = state.steps.length;
        const current = Math.min(total, (Number(state.step_index) || 0) + 1);
        const known = ['done', 'skipped', 'current', 'failed', 'pending'];
        const chips = state.steps.map((step, index) => {
            const status = String(step.status || 'pending');
            const tone = known.includes(status) ? status : 'pending';
            const marker = status === 'done' ? '✓' : (status === 'skipped' ? '↷' : (status === 'current' ? '●' : String(index + 1)));
            return '<span class="ai-recipe-step is-' + tone + '" title="' + AIRender.escape(String(step.tool || '')) + '">' +
                AIRender.escape(marker + ' ' + String(step.title || step.id || '')) + '</span>';
        }).join('');
        box.innerHTML =
            '<div class="ai-recipe-head">' +
            '<strong>' + AIRender.escape(String(state.title || state.recipe_id || '')) + '</strong>' +
            '<span class="ai-hint">' + AIRender.escape(I18n.t('ai.recipe.progress', { index: current, total: total })) + '</span>' +
            '<button type="button" class="ai-ghost ai-recipe-skip" data-ai-recipe-skip="1">' +
            AIRender.escape(I18n.t('ai.recipe.skip')) + '</button></div>' +
            '<div class="ai-recipe-steps">' + chips + '</div>';
        box.hidden = false;
    },

    _renderContextBar() {
        if (!this._dom.context) return;
        const context = AIContext.collect();
        const pieces = [];
        if (context.canvas) pieces.push(I18n.t('ai.nodesCount', { n: (context.canvas.nodes || []).length }));
        if (context.dataset_id) pieces.push(I18n.t('ai.datasetShort', { id: context.dataset_id }));
        if (context.run_id) pieces.push(I18n.t('ai.runShort', { id: context.run_id }));
        this._dom.context.innerHTML =
            '<span class="ai-chip">' + AIRender.escape(I18n.t('ai.context')) + '</span>' +
            (this._bootstrap?.runtime ? '<span class="ai-chip ai-runtime-chip" title="' + AIRender.escape(this._runtimeTitle()) + '">' + AIRender.escape(I18n.has(this._bootstrap.runtime.label_key) ? I18n.t(this._bootstrap.runtime.label_key) : (AI_RUNTIME_KEYS[this._bootstrap.runtime.kind] ? I18n.t(AI_RUNTIME_KEYS[this._bootstrap.runtime.kind]) : String(this._bootstrap.runtime.kind || ''))) + '</span>' : '') +
            '<span class="ai-hint">' + AIRender.escape(pieces.join(' · ') || I18n.t('ai.contextEmpty')) + '</span>' +
            '<button type="button" class="ai-ghost" data-ai-context-refresh="1">' + AIRender.escape(I18n.t('ai.contextRefresh')) + '</button>';
    },

    async _previewContext() {
        /* One preview, toggled: every click used to PREPEND another copy of the same section, so
           the side panel filled with duplicates and the button never became "hide". The text is
           kept here (not in the DOM) because `_renderSide` rebuilds the panel after every turn. */
        if (this._contextPreview) {
            this._contextPreview = '';
            this._renderSide();
            return;
        }
        const query = this._dom.input?.value || '';
        const context = AIContext.collect();
        try {
            let endpoint = AI_BASE + '/context';
            let body = { query, context };
            if (this._conversationId) {
                endpoint = AI_BASE + '/conversations/' + encodeURIComponent(this._conversationId) + '/context';
            }
            const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const data = await response.json();
            if (!data.ok) throw new Error(data.error || 'context failed');
            this._contextMeta = data.meta || {};
            this._contextPreview = String(data.context || '');
            this._renderSide();
        } catch (error) {
            this._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

});
