/* The delegated click and change router.
 *
 * The panel's controls are markup with data-ai-* attributes, so one listener on the dock answers
 * every button, including the session list, the side panel and the context bar, which are siblings
 * of the transcript and used to be inert. A branch acts only on an element it recognises; a click
 * outside any data-ai target does nothing.
 */

Object.assign(AIWorkspace, {
    _onChange(event) {
        const target = event.target;
        if (target && target.hasAttribute('data-ai-local-only')) {
            const on = !!target.checked;
            AISettings.save({ localOnly: on });
            if (on && this._provider !== 'ollama') {
                this._provider = 'ollama';
                AISettings.setProvider('ollama');
                this._model = AISettings.modelFor('ollama', this._bootstrap?.providers);
                AISettings.setModel('ollama', this._model);
                this._renderSettings();
                this._renderModelOptions();
                this._renderToggles();
            }
            this._toast(I18n.t(on ? 'ai.localOnlyOn' : 'ai.localOnlyOff'));
            return;
        }
        if (target && target.hasAttribute('data-ai-switch-provider')) {
            this._provider = target.value;
            AISettings.setProvider(this._provider);
            this._model = AISettings.modelFor(this._provider, this._bootstrap?.providers);
            this._renderModelOptions();
            this._renderToggles();
            this._renderSettings();
            return;
        }
        if (target && target.hasAttribute('data-ai-switch-model')) {
            this._model = target.value;
            AISettings.setModel(this._provider, this._model);
            return;
        }
        if (target && target.hasAttribute('data-ai-scope')) {
            this._scope = target.value;
            AISettings.save({ scope: this._scope });
            // One owner for one fact: the server setting is what the next page load reads, so the
            // studio's choice is written there instead of living only in localStorage.
            ProductHttp.post('/api/settings', { settings: { ai_context_scope: this._scope } }).catch(() => {});
        }
    },

    _onClick(event) {
        /* A click with no target (a synthetic event from a harness or a detached node) is nothing. */
        if (!event || !event.target) return;
        /* A tool card's own row toggles its result BEFORE the data-action lookup: the row carries no
           data-ai-* attribute, and clicking the result's body must not close what it points at. */
        const raw = event.target;
        const card = raw && raw.closest ? raw.closest('.ai-tool') : null;
        if (card && !(raw.closest('summary')) && !(raw.closest('details')) && !(raw.closest('button'))) {
            const detail = card.querySelector('details.ai-tool-detail');
            if (detail) {
                this._setDetailOpen(detail, detail.open !== true);
                return;
            }
        }
        const target = event.target.closest('[data-ai-suggest],[data-ai-conversation],[data-ai-new-session],[data-ai-rename-conversation],[data-ai-delete-conversation],[data-ai-context-refresh],[data-ai-context-preview],[data-ai-cmd],[data-ai-agents],[data-ai-context-apply],[data-ai-manual],[data-ai-answer],[data-ai-send-custom],[data-ai-copy-artifact],[data-ai-preview-artifact],[data-ai-apply-skill],[data-ai-apply-plugin],[data-ai-apply-chart],[data-ai-apply-workflow],[data-ai-run-workflow],[data-ai-copy-answer],[data-ai-retry],[data-ai-jump],[data-ai-folder-open],[data-ai-folder-root],[data-ai-folder-native],[data-ai-folder-use],[data-ai-folder-clear],[data-ai-folder-close],[data-ai-apply-monitor],[data-ai-watch-only],[data-ai-disarm-monitor],[data-ai-revoke-grant],[data-ai-monitor-new],[data-ai-remove-attachment],[data-ai-ref],[data-ai-remove-ref],[data-ai-remove-answer-ref],[data-ai-skill],[data-ai-rerun-node],[data-ai-studio-tab],[data-ai-python-new],[data-ai-python-edit],[data-ai-python-save],[data-ai-python-cancel],[data-ai-python-delete],[data-ai-python-fork],[data-ai-python-run],[data-ai-python-install],[data-ai-fork],[data-ai-edit-skill],[data-ai-delete-skill],[data-ai-new-skill],[data-ai-save-skill],[data-ai-cancel-skill],[data-ai-toggle-plugin],[data-ai-delete-plugin],[data-ai-install-plugin],[data-ai-studio-close],[data-ai-provider-select],[data-ai-refresh-models],[data-ai-spend-refresh],[data-ai-implement-artifact],[data-ai-test],[data-ai-save-settings],[data-ai-scope],[data-ai-switch-provider],[data-ai-switch-model],[data-ai-switch-skill],[data-ai-pin-conversation],[data-ai-archive-conversation],[data-ai-export-conversation],[data-ai-toggle-archived],[data-ai-memory-add],[data-ai-memory-delete],[data-ai-apply-memory],[data-ai-recipe-skip]');
        if (!target) return;
        if (target.hasAttribute('data-ai-recipe-skip')) {
            this._skipRecipeStep();
            return;
        }
        if (target.hasAttribute('data-ai-suggest')) {
            this._skill = target.getAttribute('data-ai-suggest');
            AISettings.save({ skill: this._skill });
            this._renderSkillOptions();
            this._dom.input.focus();
            return;
        }
        if (target.hasAttribute('data-ai-conversation')) {
            this.selectConversation(target.getAttribute('data-ai-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-new-session')) {
            this.newChat();
            if (this._sessionsOpen) this.toggleSessions();
            return;
        }
        if (target.hasAttribute('data-ai-rename-conversation')) {
            this._renameConversation(target.getAttribute('data-ai-rename-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-delete-conversation')) {
            this._deleteConversation(target.getAttribute('data-ai-delete-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-pin-conversation')) {
            this._toggleConversationPin(target.getAttribute('data-ai-pin-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-archive-conversation')) {
            this._toggleConversationArchive(target.getAttribute('data-ai-archive-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-export-conversation')) {
            this._exportConversation(target.getAttribute('data-ai-export-conversation'));
            return;
        }
        if (target.hasAttribute('data-ai-toggle-archived')) {
            this._showArchived = !this._showArchived;
            this._refreshConversations();
            return;
        }
        if (target.hasAttribute('data-ai-context-refresh')) {
            this._renderContextBar();
            return;
        }
        if (target.hasAttribute('data-ai-context-preview')) {
            this._previewContext();
            return;
        }
        if (target.closest('[data-ai-skill]')) {
            this._loadSkillDetail(target.closest('[data-ai-skill]'));
        }
        if (target.hasAttribute('data-ai-agents')) {
            this.setAgentMode(target.getAttribute('data-ai-agents'));
            return;
        }
        if (target.hasAttribute('data-ai-cmd')) {
            this._runCommand(target.getAttribute('data-ai-cmd'));
            return;
        }
        if (target.hasAttribute('data-ai-context-apply')) {
            const dataset = this._dom.side.querySelector('[data-ai-manual="dataset_id"]');
            const run = this._dom.side.querySelector('[data-ai-manual="run_id"]');
            AIContext.setManual({ dataset_id: dataset?.value || '', run_id: run?.value || '' });
            this._renderContextBar();
            this._toast(I18n.t('ai.saved'));
            return;
        }
        if (target.hasAttribute('data-ai-answer')) {
            this._answerOption(target.getAttribute('data-ai-question'), target.getAttribute('data-ai-answer'));
            return;
        }
        if (target.hasAttribute('data-ai-send-custom')) {
            const questionId = target.getAttribute('data-ai-send-custom');
            const box = this._findByData(this._dom.chat, 'data-ai-custom', questionId);
            this._answerCustom(questionId, box ? box.value : '');
            return;
        }
        if (target.hasAttribute('data-ai-copy-artifact')) {
            const id = target.getAttribute('data-ai-copy-artifact');
            const artifact = (this._current?.artifacts || []).find((item) => item.id === id);
            if (artifact) this._copyText(JSON.stringify(artifact.payload || {}, null, 2));
            return;
        }
        if (target.hasAttribute('data-ai-preview-artifact')) {
            this._previewArtifact(target.getAttribute('data-ai-preview-artifact'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-skill')) {
            this._applySkillArtifact(target.getAttribute('data-ai-apply-skill'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-plugin')) {
            this._applyPluginArtifact(target.getAttribute('data-ai-apply-plugin'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-memory')) {
            this._applyMemoryArtifact(target.getAttribute('data-ai-apply-memory'));
            return;
        }
        if (target.hasAttribute('data-ai-apply-workflow') || target.hasAttribute('data-ai-run-workflow')) {
            const run = target.hasAttribute('data-ai-run-workflow');
            const id = target.getAttribute(run ? 'data-ai-run-workflow' : 'data-ai-apply-workflow');
            const artifact = (this._artifactsById || {})[id] || (this._current?.artifacts || []).find((item) => item.id === id);
            if (!artifact) {
                this._toast(I18n.t('ai.error'));
                return;
            }
            this._applyWorkflowPayload(artifact.payload || {}, run, artifact.title || '', {
                confirm: true,
                detach: true,
            });
            return;
        }
        if (target.hasAttribute('data-ai-apply-chart')) {
            this._applyChartArtifact(target.getAttribute('data-ai-apply-chart'));
            return;
        }
        if (target.hasAttribute('data-ai-copy-answer')) {
            this._copyAnswer(target);
            return;
        }
        if (target.hasAttribute('data-ai-retry')) {
            this.retry();
            return;
        }
        if (target.hasAttribute('data-ai-folder-open')) {
            this._openFolder(target.getAttribute('data-ai-folder-open'));
            return;
        }
        if (target.hasAttribute('data-ai-folder-root')) {
            this._openFolder(target.getAttribute('data-ai-folder-root'));
            return;
        }
        if (target.hasAttribute('data-ai-folder-native')) {
            this._pickNativeFolder();
            return;
        }
        if (target.hasAttribute('data-ai-folder-use')) {
            this._setFolder(target.getAttribute('data-ai-folder-use'));
            return;
        }
        if (target.hasAttribute('data-ai-folder-clear')) {
            this._setFolder('');
            return;
        }
        if (target.hasAttribute('data-ai-folder-close')) {
            if (this._dom.folderDialog) this._dom.folderDialog.hidden = true;
            return;
        }
        if (target.hasAttribute('data-ai-apply-monitor')) {
            this._applyMonitor(target.getAttribute('data-ai-apply-monitor'), true);
            return;
        }
        if (target.hasAttribute('data-ai-watch-only')) {
            this._applyMonitor(target.getAttribute('data-ai-watch-only'), false);
            return;
        }
        if (target.hasAttribute('data-ai-monitor-new')) {
            this._newMonitor();
            return;
        }
        if (target.hasAttribute('data-ai-disarm-monitor')) {
            this._disarmMonitor(target.getAttribute('data-ai-disarm-monitor'));
            return;
        }
        if (target.hasAttribute('data-ai-revoke-grant')) {
            this._revokeDatasetGrant(target.getAttribute('data-ai-revoke-grant'));
            return;
        }
        if (target.hasAttribute('data-ai-remove-attachment')) {
            this._removeAttachment(target.getAttribute('data-ai-remove-attachment'));
            return;
        }
        if (target.hasAttribute('data-ai-ref')) {
            const [kind, id] = String(target.getAttribute('data-ai-ref') || '').split('|');
            const row = this._refResults.find((item) => item.kind === kind && item.id === id) || {};
            this._pickRef(kind, id, row.label || id);
            return;
        }
        if (target.hasAttribute('data-ai-remove-ref')) {
            const [kind, id] = String(target.getAttribute('data-ai-remove-ref') || '').split('|');
            this._removeRef(kind, id);
            return;
        }
        if (target.hasAttribute('data-ai-remove-answer-ref')) {
            const [kind, id, questionId] = String(target.getAttribute('data-ai-remove-answer-ref') || '').split('|');
            const rows = this._answerRefs(questionId).filter((row) => !(row.kind === kind && row.id === id));
            if (this._current && this._current.answerRefs) this._current.answerRefs[String(questionId)] = rows;
            this._renderAnswerRefs(questionId);
            return;
        }
        if (target.hasAttribute('data-ai-rerun-node')) {
            this._rerunFailedNode(
                target.getAttribute('data-ai-rerun-run'),
                target.getAttribute('data-ai-rerun-node'),
                target.getAttribute('data-ai-rerun-workflow')
            );
            return;
        }
        if (target.hasAttribute('data-ai-memory-add')) {
            AIStudio.saveMemory(this);
            return;
        }
        if (target.hasAttribute('data-ai-memory-delete')) {
            AIStudio.deleteMemory(this, target.getAttribute('data-ai-memory-delete'));
            return;
        }
        if (target.hasAttribute('data-ai-python-new')) {
            AIStudio.newPython(this);
            return;
        }
        if (target.hasAttribute('data-ai-python-edit')) {
            AIStudio.editPython(this, target.getAttribute('data-ai-python-edit'));
            return;
        }
        if (target.hasAttribute('data-ai-python-save')) {
            AIStudio.savePython(this);
            return;
        }
        if (target.hasAttribute('data-ai-python-cancel')) {
            this._pythonScript = null;
            this.openStudio('python');
            return;
        }
        if (target.hasAttribute('data-ai-python-delete')) {
            AIStudio.deletePython(this, target.getAttribute('data-ai-python-delete'));
            return;
        }
        if (target.hasAttribute('data-ai-python-fork')) {
            AIStudio.forkPython(this, target.getAttribute('data-ai-python-fork'));
            return;
        }
        if (target.hasAttribute('data-ai-python-run')) {
            AIStudio.runPython(this);
            return;
        }
        if (target.hasAttribute('data-ai-python-install')) {
            AIStudio.installPython(this);
            return;
        }
        if (target.hasAttribute('data-ai-studio-tab')) {
            this._studioTab = target.getAttribute('data-ai-studio-tab');
            AIStudio.render(this._dom.panel, this);
            if (this._studioTab === 'python' && typeof AIStudio.loadPython === 'function') AIStudio.loadPython(this);
            if (this._studioTab === 'memory' && typeof AIStudio.loadMemory === 'function') AIStudio.loadMemory(this);
            return;
        }
        if (target.hasAttribute('data-ai-studio-close')) {
            this._mode = 'chat';
            this._editingSkill = null;
            /* Hiding the panel is enough: the transcript was never overwritten, so an answer that
               arrived (or is still streaming) is still there. The second argument re-reads the
               conversation so a question that arrived while the studio was up gets its card. */
            this._showChat(true);
            return;
        }
        if (target.hasAttribute('data-ai-new-skill')) {
            this._editingSkill = { id: '', name: '', prompt: '', context: [], tools: [], suggested: [], ask_policy: 'auto' };
            AIStudio.render(this._dom.panel, this);
            return;
        }
        if (target.hasAttribute('data-ai-edit-skill')) {
            const id = target.getAttribute('data-ai-edit-skill');
            const skill = (this._bootstrap?.skills || []).find((item) => item.id === id);
            this._editingSkill = skill ? Object.assign({}, skill, { prompt: skill.prompt || '' }) : null;
            this._loadSkillForEdit(id);
            return;
        }
        if (target.hasAttribute('data-ai-fork')) {
            this._forkSkill(target.getAttribute('data-ai-fork'));
            return;
        }
        if (target.hasAttribute('data-ai-delete-skill')) {
            this._deleteSkill(target.getAttribute('data-ai-delete-skill'));
            return;
        }
        if (target.hasAttribute('data-ai-save-skill')) {
            this._saveSkillFromEditor();
            return;
        }
        if (target.hasAttribute('data-ai-cancel-skill')) {
            this._editingSkill = null;
            AIStudio.render(this._dom.panel, this);
            return;
        }
        if (target.hasAttribute('data-ai-toggle-plugin')) {
            this._togglePlugin(target.getAttribute('data-ai-toggle-plugin'), target.getAttribute('data-ai-enabled') === '1');
            return;
        }
        if (target.hasAttribute('data-ai-delete-plugin')) {
            this._deletePlugin(target.getAttribute('data-ai-delete-plugin'));
            return;
        }
        if (target.hasAttribute('data-ai-install-plugin')) {
            this._installPlugin();
            return;
        }
        if (target.hasAttribute('data-ai-provider-select')) {
            this._provider = target.value;
            AISettings.setProvider(this._provider);
            this._model = AISettings.modelFor(this._provider, this._bootstrap?.providers);
            this._renderModelOptions();
            this._renderToggles();
            return;
        }
        if (target.hasAttribute('data-ai-switch-provider')) {
            this._provider = target.value;
            AISettings.setProvider(this._provider);
            this._model = AISettings.modelFor(this._provider, this._bootstrap?.providers);
            this._renderModelOptions();
            return;
        }
        if (target.hasAttribute('data-ai-switch-model')) {
            this._model = target.value;
            AISettings.setModel(this._provider, this._model);
            return;
        }
        if (target.hasAttribute('data-ai-switch-skill')) {
            this._skill = target.value;
            AISettings.save({ skill: this._skill });
            return;
        }
        if (target.hasAttribute('data-ai-scope')) {
            this._scope = target.value;
            AISettings.save({ scope: this._scope });
            return;
        }
        /* The settings page's three buttons. They were in the delegated selector above but had no
           branch here, so clicking 保存 (the only place the API key is typed) did nothing at all —
           no toast, no request, no error. Pinned by harness_ai_workspace.mjs. */
        if (target.hasAttribute('data-ai-save-settings')) {
            this._saveSettings();
            return;
        }
        if (target.hasAttribute('data-ai-refresh-models')) {
            this._refreshModels();
            return;
        }
        if (target.hasAttribute('data-ai-spend-refresh')) {
            this._loadSpend();
            return;
        }
        if (target.hasAttribute('data-ai-implement-artifact')) {
            this._implementArtifact(target.getAttribute('data-ai-implement-artifact'));
            return;
        }
        if (target.hasAttribute('data-ai-test')) {
            this._testProvider();
            return;
        }
    },

});
