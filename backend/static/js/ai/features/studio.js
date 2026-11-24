/* The studio panel and the actions it offers.
 *
 * The studio is the workspace's own editor surface: user skills, plugin install/disable, permissions,
 * memory and the Python script library. Its rendering lives in ai/studio.js (the panel object); what
 * is added here are the workspace methods that open it and act on a gallery row.
 */

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
            ['memory', I18n.t('ai.tabMemory')],
            ['python', I18n.t('ai.tabPython')],
            ['plugins', I18n.t('ai.tabPlugins')],
            ['permissions', I18n.t('ai.tabPermissions')],
        ].map(([id, label]) =>
            '<button type="button" class="ai-tab ' + (tab === id ? 'selected' : '') + '" data-ai-studio-tab="' + id + '">' + AIRender.escape(label) + '</button>'
        ).join('');
        let body = '';
        if (tab === 'skills') body = this.skills(skills, host);
        else if (tab === 'memory') body = this.memory(host);
        else if (tab === 'python') body = this.python(host);
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

    /* One label per server-side context source id; an id this build has no row for shows as
       itself (the server may offer a source a newer UI knows how to name). */
    contextLabel(source) {
        const key = 'ai.contextSource.' + String(source || '');
        return I18n.has(key) ? I18n.t(key) : String(source || '');
    },

    skills(skills, host) {
        const editor = host._editingSkill;
        const cards = skills.map((skill) => {
            const builtin = skill.builtin;
            const name = skill.name || (I18n.has(skill.name_key) ? I18n.t(skill.name_key) : skill.id);
            const description = skill.description || (I18n.has(skill.description_key) ? I18n.t(skill.description_key) : '');
            const badge = builtin ? I18n.t('ai.builtin') : I18n.t('ai.userSkill');
            const unavailable = skill.available === false;
            return (
                '<article class="ai-skill-card ' + (unavailable ? 'is-unavailable' : '') + '">' +
                '<div class="ai-skill-head"><strong>' + AIRender.escape(name) + '</strong><span class="ai-tag">' + AIRender.escape(badge) + '</span></div>' +
                '<p class="ai-skill-desc">' + AIRender.escape(description) + '</p>' +
                '<div class="ai-skill-meta">' + (skill.context || []).map((item) => '<span class="ai-chip">' + AIRender.escape(this.contextLabel(item)) + '</span>').join('') + '</div>' +
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
        // Both lists are the server's answer: a new context source or a new control tool must not
        // need a browser edit, and a cloud host must not offer `code` here.
        const contextSources = host._bootstrap?.context_sources || [];
        const toolList = (host._bootstrap?.tools || [])
            .filter((tool) => !tool.control)
            .map((tool) => tool.name);
        const selectedContext = new Set(skill.context || []);
        const selectedTools = new Set(skill.tools || []);
        const contextChecks = contextSources.map((source) =>
            '<label class="ai-check"><input type="checkbox" data-ai-skill-context="' + AIRender.escape(source) + '"' + (selectedContext.has(source) ? ' checked' : '') + ' /><span class="ai-check-box"></span>' + AIRender.escape(this.contextLabel(source)) + '</label>'
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

    /* Confirmed facts the assistant carries into every later turn. The list is the server's; the
       input is a proposal the user writes, never something the model can add behind their back. */
    memory(host) {
        const rows = host._memories || [];
        const limit = host._memoryLimit || 0;
        const cards = rows.map((item) =>
            '<article class="ai-skill-card ai-memory-card">' +
            '<p class="ai-memory-text">' + AIRender.escape(item.text || '') + '</p>' +
            '<div class="ai-skill-actions"><button type="button" class="ai-ghost danger" data-ai-memory-delete="' + AIRender.escape(item.id || '') + '">' + AIRender.escape(I18n.t('ai.delete')) + '</button></div>' +
            '</article>'
        ).join('');
        const count = limit ? I18n.t('ai.memoryCount', { n: rows.length, limit: limit }) : String(rows.length);
        return (
            '<div class="ai-studio-toolbar"><span class="ai-hint">' + AIRender.escape(I18n.t('ai.memoryHint')) + '</span>' +
            '<span class="ai-chip">' + AIRender.escape(count) + '</span></div>' +
            '<div class="ai-skill-grid">' + (cards || '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.memoryEmpty')) + '</p>') + '</div>' +
            '<section class="ai-editor"><h3>' + AIRender.escape(I18n.t('ai.memoryAdd')) + '</h3>' +
            '<textarea class="ai-textarea" rows="3" id="ai-memory-text" placeholder="' + AIRender.escape(I18n.t('ai.memoryPlaceholder')) + '"></textarea>' +
            '<div class="ai-editor-actions"><button type="button" class="ai-primary" data-ai-memory-add="1">' + AIRender.escape(I18n.t('ai.memorySave')) + '</button></div>' +
            '</section>'
        );
    },

    async loadMemory(host) {
        try {
            const { data } = await AIHttp.get('/memories');
            if (!data.ok) throw new Error(data.error || 'memories unavailable');
            host._memories = data.memories || [];
            host._memoryLimit = Number(data.limit || 0);
            if ((host._studioTab || '') === 'memory') host._renderStudio();
        } catch (error) {
            host._toast(error.message);
        }
    },

    async saveMemory(host) {
        const box = host._dom.panel.querySelector('#ai-memory-text');
        const text = String(box?.value || '').trim();
        if (!text) return;
        try {
            const { data } = await AIHttp.post('/memories', { text });
            if (!data.ok) throw new Error(data.error || 'save failed');
            if (box) box.value = '';
            host._toast(I18n.t(data.duplicate ? 'ai.memoryDuplicate' : 'ai.memorySaved'));
            await this.loadMemory(host);
        } catch (error) {
            host._toast(error.message);
        }
    },

    async deleteMemory(host, memoryId) {
        try {
            const { data } = await AIHttp.del('/memories/' + encodeURIComponent(memoryId));
            if (!data.ok) throw new Error(data.error || 'delete failed');
            await this.loadMemory(host);
        } catch (error) {
            host._toast(error.message);
        }
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

    python(host) {
        /* The script library and the workspace status. The list and the interpreter verdict come
           from the server after paint; this HTML is the shell that receives them. */
        const editor = host._pythonScript || null;
        const editorHtml = editor
            ? '<section class="ai-editor"><h3>' + AIRender.escape(editor.id || I18n.t('ai.pythonNew')) + '</h3>' +
              '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.fieldId')) + '</span><input class="ai-input" data-ai-python-field="id" value="' + AIRender.escape(editor.id || '') + '"' + (editor.builtin ? ' disabled' : '') + ' /></label>' +
              '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillName')) + '</span><input class="ai-input" data-ai-python-field="name" value="' + AIRender.escape(editor.name || '') + '" /></label>' +
              '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.skillDescription')) + '</span><input class="ai-input" data-ai-python-field="description" value="' + AIRender.escape(editor.description || '') + '" /></label>' +
              '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.fieldCode')) + '</span><textarea class="ai-textarea ai-code-input" rows="14" data-ai-python-field="code">' + AIRender.escape(editor.code || '') + '</textarea></label>' +
              '<div class="ai-editor-actions">' +
              (editor.builtin
                  ? '<button type="button" class="ai-primary" data-ai-python-fork="' + AIRender.escape(editor.id) + '">' + AIRender.escape(I18n.t('ai.fork')) + '</button>'
                  : '<button type="button" class="ai-primary" data-ai-python-save="1">' + AIRender.escape(I18n.t('ai.save')) + '</button>') +
              '<button type="button" class="ai-ghost" data-ai-python-cancel="1">' + AIRender.escape(I18n.t('ai.close')) + '</button></div></section>'
            : '';
        return (
            '<div class="ai-studio-toolbar"><span class="ai-hint">' + AIRender.escape(I18n.t('ai.pythonHint')) + '</span>' +
            '<button type="button" class="ai-primary" data-ai-python-new="1">' + AIRender.escape(I18n.t('ai.pythonNew')) + '</button></div>' +
            '<div id="ai-python-status" class="ai-python-status"></div>' +
            '<div id="ai-python-list" class="ai-skill-grid"></div>' +
            '<section class="ai-editor"><h3>' + AIRender.escape(I18n.t('ai.pythonTry')) + '</h3>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.pythonScript')) + '</span><select class="ai-select" id="ai-python-run-id"></select></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.rowsJson')) + '</span><textarea class="ai-textarea ai-code-input" rows="3" id="ai-python-run-rows">[{"text":"hello"}]</textarea></label>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.argsJson')) + '</span><textarea class="ai-textarea ai-code-input" rows="2" id="ai-python-run-args">{}</textarea></label>' +
            '<div class="ai-editor-actions"><button type="button" class="ai-primary" data-ai-python-run="1">' + AIRender.escape(I18n.t('ai.pythonRun')) + '</button></div>' +
            '<pre class="ai-code" id="ai-python-output"></pre></section>' + editorHtml
        );
    },

    async loadPython(host) {
        const body = document.getElementById('ai-python-status');
        if (!body) return;
        try {
            const [status, listing] = await Promise.all([
                AIHttp.get('/python/status').then(({ data }) => data),
                AIHttp.get('/python/scripts').then(({ data }) => data),
            ]);
            const report = status.report || {};
            const line = report.available
                ? (report.version || '?') + ' · ' + (report.path || '')
                : I18n.t('ai.pythonMissing');
            body.innerHTML = '<span class="ai-chip">' + AIRender.escape(line) + '</span>' +
                (status.enabled ? '<span class="ai-chip">' + AIRender.escape(I18n.t('ai.pythonOn')) + '</span>' : '<span class="ai-chip warn">' + AIRender.escape(I18n.t('ai.pythonOff')) + '</span>') +
                (!report.available && status.install && status.install.supported
                    ? '<button type="button" class="ai-ghost" data-ai-python-install="1">' + AIRender.escape(I18n.t('ai.pythonDownload')) + '</button>'
                    : '');
            const scripts = listing.scripts || [];
            const list = document.getElementById('ai-python-list');
            if (list) {
                list.innerHTML = scripts.map((script) =>
                    '<article class="ai-skill-card"><div class="ai-skill-head"><strong>' + AIRender.escape(script.name) + '</strong>' +
                    '<span class="ai-tag">' + AIRender.escape(script.builtin ? I18n.t('ai.builtin') : 'v' + script.version) + '</span></div>' +
                    '<p class="ai-skill-desc">' + AIRender.escape(script.description || '') + '</p>' +
                    '<div class="ai-skill-meta"><span class="ai-chip">' + AIRender.escape(script.id) + '</span></div>' +
                    '<div class="ai-skill-actions"><button type="button" class="ai-ghost" data-ai-python-edit="' + AIRender.escape(script.id) + '">' + AIRender.escape(I18n.t(script.builtin ? 'ai.fork' : 'ai.edit')) + '</button>' +
                    (!script.builtin ? '<button type="button" class="ai-ghost danger" data-ai-python-delete="' + AIRender.escape(script.id) + '">' + AIRender.escape(I18n.t('ai.delete')) + '</button>' : '') +
                    '</div></article>'
                ).join('') || '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.pythonEmpty')) + '</p>';
            }
            const runSelect = document.getElementById('ai-python-run-id');
            if (runSelect) {
                runSelect.innerHTML = scripts.map((script) =>
                    '<option value="' + AIRender.escape(script.id) + '">' + AIRender.escape(script.name) + '</option>'
                ).join('');
            }
        } catch (error) {
            body.textContent = I18n.t('ai.error') + ': ' + error.message;
        }
    },

    async editPython(host, scriptId) {
        try {
            const { data } = await AIHttp.get('/python/scripts/' + encodeURIComponent(scriptId));
            if (!data.ok) throw new Error(data.error || 'not found');
            host._pythonScript = data.script;
            AIWorkspace.openStudio('python');
        } catch (error) {
            host._toast(error.message);
        }
    },

    newPython(host) {
        host._pythonScript = { id: '', name: '', description: '', code: '# Reads CIXI_INPUT JSONL, writes CIXI_OUTPUT JSONL.\n', builtin: false };
        AIWorkspace.openStudio('python');
    },

    async savePython(host) {
        const editor = host._pythonScript || {};
        const read = (name) => host._dom.panel.querySelector('[data-ai-python-field="' + name + '"]');
        const payload = {
            id: (read('id')?.value || editor.id || '').trim(),
            name: (read('name')?.value || '').trim(),
            description: (read('description')?.value || '').trim(),
            code: read('code')?.value || '',
        };
        try {
            const { data } = await AIHttp.post('/python/scripts', payload);
            if (!data.ok) throw new Error(data.error || 'save failed');
            host._pythonScript = null;
            host._toast(I18n.t('ai.saved'));
            AIWorkspace.openStudio('python');
        } catch (error) {
            host._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    async deletePython(host, scriptId) {
        try {
            const { data } = await AIHttp.del('/python/scripts/' + encodeURIComponent(scriptId));
            if (!data.ok) throw new Error(data.error || 'delete failed');
            AIWorkspace.openStudio('python');
        } catch (error) {
            host._toast(error.message);
        }
    },

    async forkPython(host, scriptId) {
        try {
            const { data } = await AIHttp.post('/python/scripts/' + encodeURIComponent(scriptId) + '/fork', {
                id: scriptId + '_mine',
            });
            if (!data.ok) throw new Error(data.error || 'fork failed');
            host._pythonScript = data.script;
            AIWorkspace.openStudio('python');
        } catch (error) {
            host._toast(error.message);
        }
    },

    async runPython(host) {
        const output = document.getElementById('ai-python-output');
        let rows = [];
        let args = {};
        try {
            rows = JSON.parse(document.getElementById('ai-python-run-rows')?.value || '[]');
            args = JSON.parse(document.getElementById('ai-python-run-args')?.value || '{}');
        } catch (error) {
            if (output) output.textContent = I18n.t('ai.pythonBadJson');
            return;
        }
        const scriptId = document.getElementById('ai-python-run-id')?.value || '';
        if (output) output.textContent = I18n.t('ai.pythonRunning');
        try {
            const { data } = await AIHttp.post('/python/run', { script_id: scriptId, rows, args, max_rows: 200 });
            if (!data.ok) throw new Error(data.error || 'run failed');
            if (output) {
                output.textContent = JSON.stringify({ rows: data.rows, sample: data.sample, stderr: data.stderr, duration_ms: data.duration_ms }, null, 2);
            }
        } catch (error) {
            if (output) output.textContent = I18n.t('ai.error') + ': ' + error.message;
        }
    },

    async installPython(host) {
        if (!(await host._confirm(I18n.t('ai.pythonDownloadConfirm')))) return;
        try {
            const { data } = await AIHttp.post('/python/install', { allow_download: true });
            if (!data.ok) throw new Error(data.error || 'install failed');
            host._toast(I18n.t('ai.pythonInstalled'));
            AIWorkspace.openStudio('python');
        } catch (error) {
            host._toast(I18n.t('ai.error') + ': ' + error.message);
        }
    },

    permissions(context, host) {
        const capabilities = context.providers ? (context.providers.find((item) => item.id === host._provider)?.capabilities || []) : [];
        return (
            '<section class="ai-permissions">' +
            '<h3>' + AIRender.escape(I18n.t('ai.permissionsTitle')) + '</h3>' +
            '<p class="ai-hint">' + AIRender.escape(I18n.t('ai.permissionsBody')) + '</p>' +
            '<div class="ai-skill-meta">' + capabilities.map((cap) => '<span class="ai-chip">' + AIRender.escape(I18n.has('ai.cap.' + cap) ? I18n.t('ai.cap.' + cap) : cap) + '</span>').join('') + '</div>' +
            '<label class="ai-field"><span>' + AIRender.escape(I18n.t('ai.contextScope')) + '</span><select class="ai-select" data-ai-scope>' +
            ['off', 'summary', 'full'].map((value) => '<option value="' + value + '"' + (host._scope === value ? ' selected' : '') + '>' + AIRender.escape(I18n.t(this.CONTEXT_KEYS[value])) + '</option>').join('') +
            '</select></label>' +
            '</section>'
        );
    },
};

Object.assign(AIWorkspace, {
    /* The skill row expands into what the skill ACTUALLY carries: its prompt, context sources and
       tools. Fetched on first open, so a long prompt costs nothing until it is asked for. */
    async _loadSkillDetail(el) {
        const body = el.querySelector('.ai-skill-body');
        if (!body || body.getAttribute('data-loaded') === '1') return;
        const id = el.getAttribute('data-ai-skill') || '';
        /* `data-loaded` is set only AFTER the answer arrives: marking it first made one failed
           request permanent — every later click returned early and the row could never load. */
        body.setAttribute('data-loading', '1');
        body.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.skillLoading')) + '</div>';
        try {
            const { response, data } = await AIHttp.get('/skills/' + encodeURIComponent(id));
            if (!data.ok) throw new Error(data.error || ('HTTP ' + response.status));
            const skill = data.skill || {};
            const context = (skill.context || []).join(', ') || '—';
            const tools = (skill.tools || []).join(', ') || '—';
            body.innerHTML =
                '<p class="ai-skill-prompt">' + AIRender.escape(String(skill.prompt || '')) + '</p>' +
                '<div class="ai-skill-meta"><span>' + AIRender.escape(I18n.t('ai.skillContext')) + ': ' +
                AIRender.escape(context) + '</span><span>' + AIRender.escape(I18n.t('ai.skillTools')) + ': ' +
                AIRender.escape(tools) + '</span></div>';
            body.setAttribute('data-loaded', '1');
        } catch (error) {
            body.removeAttribute('data-loading');
            body.innerHTML = '<div class="ai-hint">' + AIRender.escape(I18n.t('ai.skillLoadFailed')) + '</div>';
        }
    },

    /* ─── Entry from a panel outside the workspace ─────────────────────────────
       A dataset / run / node panel hands over the ids of the thing it is showing and the question
       to ask. This opens a NEW chat (an entry from a table must not inherit an unrelated
       conversation), attaches the ids as manual context so the server re-reads that object, and
       PRE-FILLS the question without sending it: the send button stays the user's, and a prompt
       they can edit is the point of an entry. */
    async askAbout(target) {
        const spec = target || {};
        const context = {};
        if (spec.dataset_id) context.dataset_id = String(spec.dataset_id);
        if (spec.run_id) context.run_id = String(spec.run_id);
        AIContext.setManual(context);
        this.open({ context });
        await this.newChat();
        if (this._dom.input) {
            this._dom.input.value = String(spec.prompt || '');
            this._dom.input.focus();
        }
        this._renderContextBar();
    },

    openStudio(tab) {
        if (tab) this._studioTab = tab;
        /* The panel may be closed: a control OUTSIDE it (the Python node's 管理脚本) called this
           and nothing appeared — `_mode` only decides what the transcript draws. Opening first is
           what makes that button act; `_renderWelcome` then declines to paint over the studio
           because the mode is no longer 'chat'. */
        if (!this._open) this.open({ silent: true });
        this._mode = 'studio';
        this._renderStudio();
        if (this._studioTab === 'python' && typeof AIStudio.loadPython === 'function') {
            AIStudio.loadPython(this);
        }
        if (this._studioTab === 'memory' && typeof AIStudio.loadMemory === 'function') {
            AIStudio.loadMemory(this);
        }
    },

    async _togglePlugin(id, enabled) {
        try {
            const { data } = await AIHttp.post('/plugins/' + encodeURIComponent(id) + '/enable', { enabled });
            if (!data.ok) throw new Error(data.error || 'toggle failed');
            await this._loadBootstrap();
            this.openStudio();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _deletePlugin(id) {
        if (!(await this._confirm(I18n.t('ai.deleteConfirm')))) return;
        try {
            const { data } = await AIHttp.del('/plugins/' + encodeURIComponent(id));
            if (!data.ok) throw new Error(data.error || 'delete failed');
            await this._loadBootstrap();
            this.openStudio();
        } catch (error) {
            this._toast(error.message);
        }
    },

    async _installPlugin() {
        const box = this._dom.panel.querySelector('[data-ai-plugin-manifest]');
        if (!box) return;
        let payload;
        try {
            payload = JSON.parse(box.value || '{}');
        } catch (error) {
            this._toast(I18n.t('ai.testFail') + ': ' + error.message);
            return;
        }
        const permissions = (payload.permissions || []).join(', ');
        if (!(await this._confirm((payload.name || payload.id || '') + '\n' + I18n.t('ai.pluginPermissions') + ': ' + permissions))) return;
        try {
            const { data } = await AIHttp.post('/plugins/install', payload);
            if (!data.ok) throw new Error(data.error || 'install failed');
            await this._loadBootstrap();
            this.openStudio();
            this._toast(I18n.t('ai.saved'));
        } catch (error) {
            this._toast(error.message);
        }
    },

});

window.AIStudio = AIStudio;
