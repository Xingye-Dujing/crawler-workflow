/* The panel's forms that are not the transcript: provider settings and the skill editor.
 *
 * Every field is a data-ai-* attribute and every submit is one route; the panel never keeps a second
 * copy of a provider's name, model list or capability set.
 */

Object.assign(AIWorkspace, {
    openSettings() {
        this._mode = 'settings';
        this._renderSettings();
    },

    _renderSettings() {
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider) || { id: this._provider, models: [] };
        const key = AISettings.keyFor(this._provider);
        const models = provider.models || [];
        const capabilityRows = (provider.capabilities || []).map((cap) => '<span class="ai-chip">' + AIRender.escape(I18n.has('ai.cap.' + cap) ? I18n.t('ai.cap.' + cap) : cap) + '</span>').join('');
        this._showPanel();
        this._dom.panel.innerHTML =
            '<section class="ai-settings">' +
            '<header class="ai-studio-head"><div><h2>' + AIRender.escape(I18n.t('ai.settingsTitle')) + '</h2><p class="ai-hint">' + AIRender.escape(I18n.t('ai.settingsHint')) + '</p></div><button type="button" class="ai-ghost" data-ai-studio-close="1">' + AIRender.escape(I18n.t('ai.close')) + '</button></header>' +
            '<div class="ai-field-row"><label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.provider')) + '</span><select class="ai-select" data-ai-switch-provider>' +
            (this._bootstrap?.providers || []).map((item) => '<option value="' + AIRender.escape(item.id) + '"' + (item.id === this._provider ? ' selected' : '') + '>' + AIRender.escape(I18n.has(item.label_key) ? I18n.t(item.label_key) : item.id) + '</option>').join('') +
            '</select></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.model')) + '</span><select class="ai-select" data-ai-switch-model>' +
            models.map((item) => '<option value="' + AIRender.escape(item.id) + '"' + (item.id === this._model ? ' selected' : '') + '>' + AIRender.escape(item.label || item.id) + '</option>').join('') +
            '</select></label></div>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.key')) + '</span><input class="ai-input" type="password" autocomplete="off" data-ai-key value="' + AIRender.escape(key) + '" placeholder="' + AIRender.escape(I18n.t('ai.keyPlaceholder')) + '" /></label>' +
            /* The one switch that protects a wallet: with it on, every send must go to the local
               daemon, and a paid provider is refused with a sentence instead of a charge. */
            '<label class="ai-field ai-field-check"><input type="checkbox" data-ai-local-only="1"' + (AISettings.load().localOnly ? ' checked' : '') + ' /><span>' + AIRender.escape(I18n.t('ai.localOnly')) + '</span></label>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.localOnlyHint')) + '</p>' +
            '<div class="ai-skill-meta">' + capabilityRows + '</div>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.has(provider.notes_key) ? I18n.t(provider.notes_key) : '') + '</p>' +
            '<div class="ai-editor-actions"><button type="button" class="ai-primary" data-ai-save-settings="1">' + AIRender.escape(I18n.t('ai.save')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-refresh-models="1">' + AIRender.escape(I18n.t('ai.refreshModelsBtn')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-test="1">' + AIRender.escape(I18n.t('ai.test')) + '</button></div>' +
            '<div class="ai-test-result" data-ai-test-result></div>' +
            '</section>';
    },

    async _loadSkillForEdit(id) {
        try {
            const { data } = await AIHttp.get('/skills/' + encodeURIComponent(id));
            if (!data.ok) throw new Error(data.error || 'skill not found');
            this._editingSkill = { ...data.skill, builtin: !!data.skill.builtin };
        } catch (e) {
            this._editingSkill = (this._bootstrap?.skills || []).find((item) => item.id === id) || null;
        }
        AIStudio.render(this._dom.panel, this);
    },

    async _saveSkillFromEditor() {
        const editor = this._editingSkill;
        if (!editor) return;
        const value = (name) => this._dom.panel.querySelector('[data-ai-skill-field="' + name + '"]')?.value || '';
        const context = Array.from(this._dom.panel.querySelectorAll('[data-ai-skill-context]:checked')).map((el) => el.getAttribute('data-ai-skill-context'));
        const tools = Array.from(this._dom.panel.querySelectorAll('[data-ai-skill-tool]:checked')).map((el) => el.getAttribute('data-ai-skill-tool'));
        const payload = {
            id: editor.builtin ? (editor.id || value('id')) : value('id') || editor.id,
            name: value('name'),
            description: value('description'),
            name_key: editor.name_key || ('ai.skill.' + (value('id') || editor.id) + '.name'),
            description_key: editor.description_key || ('ai.skill.' + (value('id') || editor.id) + '.desc'),
            prompt: value('prompt'),
            context,
            tools,
            suggested: value('suggested').split('\n').map((item) => item.trim()).filter(Boolean),
            ask_policy: this._dom.panel.querySelector('[data-ai-skill-field="ask_policy"]')?.value || 'auto',
        };
        try {
            const { data } = await AIHttp.post('/skills', payload);
            if (!data.ok) throw new Error(data.error || 'save failed');
            this._editingSkill = null;
            await this._loadBootstrap();
            this.openStudio();
            this._toast(I18n.t('ai.saved'));
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _forkSkill(id) {
        try {
            const { data } = await AIHttp.post('/skills/' + encodeURIComponent(id) + '/fork', {});
            if (!data.ok) throw new Error(data.error || 'fork failed');
            await this._loadBootstrap();
            this.openStudio();
            this._toast(I18n.t('ai.saved'));
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _deleteSkill(id) {
        if (!(await this._confirm(I18n.t('ai.deleteConfirm')))) return;
        try {
            const { data } = await AIHttp.del('/skills/' + encodeURIComponent(id));
            if (!data.ok) throw new Error(data.error || 'delete failed');
            await this._loadBootstrap();
            this.openStudio();
        } catch (error) {
            this._toast(error.message);
        }
    },

});
