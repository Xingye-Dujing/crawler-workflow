/* The studio inside the workspace: user skills, plugin install/disable, permissions.
 *
 * Every control is a data attribute; the workspace's delegated click handler performs the action.
 * A user skill is a declarative record, never code; a plugin manifest is reviewed before install.
 */
const AIStudio = {
    ASK_KEYS: { auto: 'ai.askAuto', always: 'ai.askAlways', never: 'ai.askNever' },
    CONTEXT_KEYS: { off: 'ai.contextOff', summary: 'ai.contextSummary', full: 'ai.contextFull' },

    render(container, host) {
        const context = host._bootstrap || {};
        const skills = context.skills || [];
        const plugins = context.plugins || [];
        const tab = host._studioTab || 'skills';
        const tabs = [
            ['skills', I18n.t('ai.tabSkills')],
            ['plugins', I18n.t('ai.tabPlugins')],
            ['permissions', I18n.t('ai.tabPermissions')],
        ].map(([id, label]) =>
            '<button type="button" class="ai-tab ' + (tab === id ? 'selected' : '') + '" data-ai-studio-tab="' + id + '">' + AIRender.escape(label) + '</button>'
        ).join('');
        let body = '';
        if (tab === 'skills') body = this.skills(skills, host);
        else if (tab === 'plugins') body = this.plugins(plugins, host);
        else body = this.permissions(context, host);
        container.innerHTML =
            '<section class="ai-studio">' +
            '<header class="ai-studio-head"><div><h2>' + AIRender.escape(I18n.t('ai.studioTitle')) + '</h2><p class="ai-hint">' + AIRender.escape(I18n.t('ai.skillEditorHint')) + '</p></div>' +
            '<button type="button" class="ai-ghost" data-ai-studio-close="1">' + AIRender.escape(I18n.t('ai.close')) + '</button></header>' +
            '<nav class="ai-tabs">' + tabs + '</nav>' +
            '<div class="ai-studio-body">' + body + '</div>' +
            '</section>';
    },

    skills(skills, host) {
        const editor = host._editingSkill;
        const cards = skills.map((skill) => {
            const builtin = skill.builtin;
            const name = skill.name || I18n.t(skill.name_key) || skill.id;
            const description = skill.description || I18n.t(skill.description_key) || '';
            const badge = builtin ? I18n.t('ai.builtin') : I18n.t('ai.userSkill');
            const unavailable = skill.available === false;
            return (
                '<article class="ai-skill-card ' + (unavailable ? 'is-unavailable' : '') + '">' +
                '<div class="ai-skill-head"><strong>' + AIRender.escape(name) + '</strong><span class="ai-tag">' + AIRender.escape(badge) + '</span></div>' +
                '<p class="ai-skill-desc">' + AIRender.escape(description) + '</p>' +
                '<div class="ai-skill-meta">' + (skill.context || []).map((item) => '<span class="ai-chip">' + AIRender.escape(item) + '</span>').join('') + '</div>' +
                (unavailable ? '<p class="ai-error-text">' + AIRender.escape(skill.why_not_text || I18n.t('ai.skillUnavailable')) + '</p>' : '') +
                '<div class="ai-skill-actions">' +
                (builtin ? '<button type="button" class="ai-ghost" data-ai-fork="' + AIRender.escape(skill.id) + '">' + AIRender.escape(I18n.t('ai.fork')) + '</button>' : '') +
                (!builtin ? '<button type="button" class="ai-ghost" data-ai-edit-skill="' + AIRender.escape(skill.id) + '">' + AIRender.escape(I18n.t('ai.edit')) + '</button>' : '') +
                (!builtin ? '<button type="button" class="ai-ghost danger" data-ai-delete-skill="' + AIRender.escape(skill.id) + '">' + AIRender.escape(I18n.t('ai.delete')) + '</button>' : '') +
                '</div></article>'
            );
        }).join('');
        const editorHtml = editor ? this.editor(editor, host) : '';
        return (
            '<div class="ai-studio-toolbar"><span class="ai-hint">' + AIRender.escape(I18n.t('ai.studioTitle')) + '</span>' +
            '<button type="button" class="ai-primary" data-ai-new-skill="1">' + AIRender.escape(I18n.t('ai.newSkill')) + '</button></div>' +
            '<div class="ai-skill-grid">' + cards + '</div>' + editorHtml
        );
    },

    editor(skill, host) {
        const contextSources = ['project', 'canvas', 'dataset', 'run', 'docs', 'code'];
        const toolList = (host._bootstrap?.tools || [])
            .filter((tool) => !['ask_user_question', 'update_plan', 'present_artifact'].includes(tool.name))
            .map((tool) => tool.name);
        const selectedContext = new Set(skill.context || []);
        const selectedTools = new Set(skill.tools || []);
        const contextChecks = contextSources.map((source) =>
            '<label class="ai-check"><input type="checkbox" data-ai-skill-context="' + source + '"' + (selectedContext.has(source) ? ' checked' : '') + ' /><span class="ai-check-box"></span>' + AIRender.escape(source) + '</label>'
        ).join('');
        const toolChecks = toolList.map((tool) =>
            '<label class="ai-check"><input type="checkbox" data-ai-skill-tool="' + AIRender.escape(tool) + '"' + (selectedTools.has(tool) ? ' checked' : '') + ' /><span class="ai-check-box"></span>' + AIRender.escape(tool) + '</label>'
        ).join('');
        const idField = skill.builtin
            ? '<input class="ai-input" value="' + AIRender.escape(skill.id) + '" disabled />'
            : '<input class="ai-input" data-ai-skill-field="id" value="' + AIRender.escape(skill.id || '') + '" placeholder="my.skill" />';
        const suggested = (skill.suggested || []).join('\n');
        return (
            '<section class="ai-editor">' +
            '<h3>' + AIRender.escape(skill.id ? I18n.t('ai.edit') : I18n.t('ai.newSkill')) + '</h3>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillId')) + '</span>' + idField + '</label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillName')) + '</span><input class="ai-input" data-ai-skill-field="name" value="' + AIRender.escape(skill.name || '') + '" /></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillDescription')) + '</span><input class="ai-input" data-ai-skill-field="description" value="' + AIRender.escape(skill.description || '') + '" /></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillPrompt')) + '</span><textarea class="ai-textarea" rows="6" data-ai-skill-field="prompt">' + AIRender.escape(skill.prompt || '') + '</textarea></label>' +
            '<fieldset class="ai-field"><legend>' + AIRender.escape(I18n.t('ai.skillContext')) + '</legend><div class="ai-checks">' + contextChecks + '</div></fieldset>' +
            '<fieldset class="ai-field"><legend>' + AIRender.escape(I18n.t('ai.skillTools')) + '</legend><div class="ai-checks">' + toolChecks + '</div></fieldset>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillSuggested')) + '</span><textarea class="ai-textarea" rows="3" data-ai-skill-field="suggested">' + AIRender.escape(suggested) + '</textarea></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillAskPolicy')) + '</span><select class="ai-select" data-ai-skill-field="ask_policy">' +
            ['auto', 'always', 'never'].map((value) => '<option value="' + value + '"' + (skill.ask_policy === value ? ' selected' : '') + '>' + AIRender.escape(I18n.t(this.ASK_KEYS[value])) + '</option>').join('') +
            '</select></label>' +
            '<div class="ai-editor-actions"><button type="button" class="ai-primary" data-ai-save-skill="1">' + AIRender.escape(I18n.t('ai.save')) + '</button>' +
            '<button type="button" class="ai-ghost" data-ai-cancel-skill="1">' + AIRender.escape(I18n.t('ai.close')) + '</button></div>' +
            '</section>'
        );
    },

    plugins(plugins, _host) {
        const cards = (plugins || []).filter((plugin) => plugin.source !== 'builtin').map((plugin) =>
            '<article class="ai-plugin-card">' +
            '<div class="ai-skill-head"><strong>' + AIRender.escape(plugin.name || plugin.id) + '</strong><span class="ai-tag">' + AIRender.escape(plugin.version || '') + '</span></div>' +
            '<p class="ai-hint">' + AIRender.escape(plugin.description || '') + '</p>' +
            '<div class="ai-skill-meta">' + (plugin.permissions || []).map((permission) => '<span class="ai-chip">' + AIRender.escape(permission) + '</span>').join('') + '</div>' +
            '<div class="ai-skill-actions">' +
            '<button type="button" class="ai-ghost" data-ai-toggle-plugin="' + AIRender.escape(plugin.id) + '" data-ai-enabled="' + (plugin.enabled ? '0' : '1') + '">' +
            AIRender.escape(plugin.enabled ? I18n.t('ai.pluginDisabled') : I18n.t('ai.pluginEnabled')) + '</button>' +
            '<button type="button" class="ai-ghost danger" data-ai-delete-plugin="' + AIRender.escape(plugin.id) + '">' + AIRender.escape(I18n.t('ai.pluginRemove')) + '</button>' +
            '</div></article>'
        ).join('');
        return (
            '<div class="ai-studio-toolbar"><span class="ai-hint">' + AIRender.escape(I18n.t('ai.pluginWarning')) + '</span></div>' +
            '<div class="ai-plugin-grid">' + (cards || '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.pluginEmpty')) + '</p>') + '</div>' +
            '<section class="ai-editor"><h3>' + AIRender.escape(I18n.t('ai.pluginInstall')) + '</h3>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.installHint')) + '</p>' +
            '<textarea class="ai-textarea ai-code-input" rows="8" data-ai-plugin-manifest placeholder="{ &quot;id&quot;: &quot;my.pack&quot;, &quot;version&quot;: &quot;1.0.0&quot;, &quot;api&quot;: 1, &quot;kind&quot;: &quot;skill-pack&quot;, &quot;permissions&quot;: [&quot;read:docs&quot;], &quot;skills&quot;: [] }"></textarea>' +
            '<div class="ai-editor-actions"><button type="button" class="ai-primary" data-ai-install-plugin="1">' + AIRender.escape(I18n.t('ai.pluginInstallBtn')) + '</button></div>' +
            '</section>'
        );
    },

    permissions(context, host) {
        const capabilities = context.providers ? (context.providers.find((item) => item.id === host._provider)?.capabilities || []) : [];
        return (
            '<section class="ai-permissions">' +
            '<h3>' + AIRender.escape(I18n.t('ai.permissionsTitle')) + '</h3>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.permissionsBody')) + '</p>' +
            '<div class="ai-skill-meta">' + capabilities.map((cap) => '<span class="ai-chip">' + AIRender.escape(I18n.t('ai.cap.' + cap) || cap) + '</span>').join('') + '</div>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.contextScope')) + '</span><select class="ai-select" data-ai-scope>' +
            ['off', 'summary', 'full'].map((value) => '<option value="' + value + '"' + (host._scope === value ? ' selected' : '') + '>' + AIRender.escape(I18n.t(this.CONTEXT_KEYS[value])) + '</option>').join('') +
            '</select></label>' +
            '</section>'
        );
    },
};
window.AIStudio = AIStudio;
