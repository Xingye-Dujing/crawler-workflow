/* A proposed artifact and the cards that act on it.
 *
 * A proposal is not a write: preview, apply and copy go through the existing route, and each kind
 * (workflow draft, plan, chart, memory, monitor) answers with its own button.
 */

Object.assign(AIWorkspace, {
    /* ─── Applying a workflow the assistant produced ─── */
    async _applyWorkflowPayload(payload, run, title, options) {
        if (typeof workflow === 'undefined' || !workflow || typeof workflow.loadFromJSON !== 'function') {
            this._toast(I18n.t('toast.workflowFileInvalid'));
            return false;
        }
        var opts = options || {};
        /* Replacing the canvas is the same destructive act as 打开 another file: confirm when
           there is unsaved work. The artifact button passes confirm:true; the live `workflow_apply`
           event cannot ask mid-turn and replaces the canvas without a prompt, but it still detaches
           the file name (below) so it can never overwrite what the user had open. */
        if (opts.confirm && typeof canvas !== 'undefined' && canvas.dirty && typeof showDialog === 'function') {
            var proceed = await showDialog({
                message: I18n.t('ai.confirmReplaceCanvas'),
                buttons: [
                    { label: I18n.t('dialog.cancel'), value: false },
                    { label: I18n.t('wfMgr.open'), value: true, primary: true },
                ],
            });
            if (!proceed) return false;
        }
        let ok = false;
        let detail = '';
        try {
            ok = workflow.loadFromJSON(payload, { detachFile: !!opts.detach }) !== false;
            if (!ok) detail = 'loadFromJSON refused the file';
        } catch (error) {
            detail = String((error && error.message) || error);
        }
        if (!ok) {
            this._workflowFeedback(title, detail);
            return false;
        }
        if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
        this._toast(I18n.t('ai.workflowApplied', { name: title || '' }));
        if (run) {
            try {
                await workflow.execute();
            } catch (error) {
                this._workflowFeedback(title, String((error && error.message) || error));
                return false;
            }
        }
        return true;
    },

    /* ─── Failed nodes and rerun ─── */

    /* A plan or a chart spec has no mechanical "apply" of its own: the honest action is to ask the
       assistant to BUILD it with the same validated tools (apply_workflow, workspace_write), so the
       card is a proposal that can become a canvas rather than a dead frame. */
    _implementArtifact(id) {
        const artifact = (this._artifactsById || {})[id] || null;
        const title = String((artifact && artifact.title) || id || '');
        this._sendText(I18n.t('ai.artifactImplementAsk', { title: title }), {});
    },

    _copyAnswer(target) {
        const message = target.closest('.ai-message');
        const flow = message ? message.querySelector('.ai-flow') : null;
        const text = flow ? String(flow.innerText || '').trim() : '';
        if (!text) return;
        const done = () => this._toast(I18n.t('ai.copied'));
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done).catch(() => this._copyFallback(text, done));
            return;
        }
        this._copyFallback(text, done);
    },

    _copyFallback(text, done) {
        /* A page served over plain HTTP has no Clipboard API; the old textarea path still works
           and is the difference between "copy" and a button that silently does nothing. */
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', 'readonly');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.select();
        let copied = false;
        try {
            copied = document.execCommand('copy');
        } catch (error) {
            copied = false;
        }
        document.body.removeChild(area);
        if (copied) done();
    },

    async retry() {
        if (this._sending || !this._conversationId) return;
        const provider = this._bootstrap?.providers?.find((item) => item.id === this._provider);
        const key = AISettings.keyFor(this._provider);
        if (provider?.requires_key && !key) {
            this._toast(I18n.t('ai.keyMissing'));
            this.openSettings();
            return;
        }
        this._current = null;
        this._beginTurn();
        this._sending = true;
        this._setSending(true);
        try {
            await this._stream('/retry', { conversation_id: this._conversationId, api_key: key });
        } catch (error) {
            if (error.name !== 'AbortError') this._renderError(error.message);
        } finally {
            this._sending = false;
            this._setSending(false);
            this._stopClock();
            this._noteCutStream();
            this._paintAssistant();
        }
    },

    /* An artifact's "preview" door: ask the SERVER what applying would change, let the user tick
       the parts they want, then hand the selection to the SAME apply path the primary button uses.
       The server owns both the kind's shape and its legality; this file holds no second opinion. */
    async _previewArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        const kind = String(artifact.kind || '');
        const draft = typeof canvas !== 'undefined' && canvas && typeof canvas.serializeDraft === 'function'
            ? canvas.serializeDraft()
            : null;
        /* serializeDraft() inherits getState(), which keys nodes BY ID. Both the server preview
           and the merge below take a LIST; sending the map made every draft node read as "new"
           and made an apply with one tick rebuild the canvas from an empty base — deleting every
           node the user had not selected. Unwrap here, the same way AIContext.canvasDraft does. */
        const current = draft && draft.nodes && typeof draft.nodes === 'object' && !Array.isArray(draft.nodes)
            ? Object.assign({}, draft, { nodes: Object.values(draft.nodes) })
            : draft;
        const currentNodes = current && Array.isArray(current.nodes) ? current.nodes : [];
        try {
            const { data: response } = await AIHttp.post('/artifacts/preview', {
                kind,
                payload: artifact.payload || {},
                current,
            });
            if (!response.ok) throw new Error(response.error || I18n.t('ai.error'));
            const pv = response.preview || {};
            const items = Array.isArray(pv.items) ? pv.items : [];
            const chosen = items.filter((item) => item.selectable);
            const message = [
                pv.summary,
                ...(Array.isArray(pv.warnings) ? pv.warnings : []),
                ...items.filter((item) => !item.selectable).map((item) => item.label + (item.detail ? ' — ' + item.detail : '')),
            ].filter(Boolean).join('\n');
            const toggles = chosen.map((item, index) => ({
                id: 'ai-preview-' + index,
                label: item.label + (item.detail ? ' — ' + item.detail : ''),
                checked: item.checked !== false,
            }));
            if (kind === 'monitor') {
                toggles.push({ id: 'ai-preview-auto', label: I18n.t('ai.preview.auto'), checked: true });
            }
            if (typeof showDialog !== 'function') return;
            const answer = await showDialog({
                message,
                toggles,
                buttons: [
                    { label: I18n.t('ai.preview.apply'), value: 'apply', primary: true, collect: true },
                    { label: I18n.t('dialog.cancel'), value: 'cancel' },
                ],
                cancelValue: null,
            });
            if (!answer || answer.value !== 'apply') return;
            const selected = answer.toggles || {};
            const picked = new Set(
                chosen.filter((_item, index) => selected['ai-preview-' + index]).map((item) => String(item.id))
            );
            if (chosen.length && !picked.size) {
                this._toast(I18n.t('ai.preview.none'));
                return;
            }
            if (kind === 'workflow' || kind === 'workflow_draft') {
                const base = currentNodes;
                const draftNodes = Array.isArray((artifact.payload || {}).nodes)
                    ? artifact.payload.nodes.filter((node) => picked.has(String(node.id || '')))
                    : [];
                const baseIds = new Set(base.map((node) => String(node.id || '')));
                const nodes = base.map((node) => draftNodes.find((draft) => String(draft.id) === String(node.id)) || node);
                for (const draft of draftNodes) {
                    if (!baseIds.has(String(draft.id || ''))) nodes.push(draft);
                }
                const ids = new Set(nodes.map((node) => String(node.id || '')));
                const connections = []
                    .concat(current && Array.isArray(current.connections) ? current.connections : [])
                    .concat(Array.isArray((artifact.payload || {}).connections) ? artifact.payload.connections : [])
                    .filter((edge) => edge && ids.has(String(edge.from)) && ids.has(String(edge.to)));
                await this._applyWorkflowPayload({ ...(artifact.payload || {}), nodes, connections }, false, artifact.title || '');
            } else if (kind === 'memory') {
                await this._applyMemoryArtifact(id);
            } else if (kind === 'monitor') {
                await this._applyMonitor(id, selected['ai-preview-auto'] !== false);
            } else if (kind === 'chart_spec') {
                await this._applyChartArtifact(id);
            }
        } catch (error) {
            this._toast(error.message || I18n.t('ai.error'));
        }
    },

    _artifactById(id) {
        const artifacts = this._current?.artifacts || [];
        return artifacts.find((item) => item.id === id) || null;
    },

    _applySkillArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        const payload = artifact.payload || {};
        this._editingSkill = {
            id: payload.id || '',
            name: payload.name || '',
            description: payload.description || '',
            prompt: payload.prompt || '',
            context: payload.context || [],
            tools: payload.tools || [],
            suggested: payload.suggested || [],
            ask_policy: payload.ask_policy || 'auto',
        };
        this._mode = 'studio';
        this._studioTab = 'skills';
        this._renderStudio();
    },

    _applyPluginArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        this._mode = 'studio';
        this._studioTab = 'plugins';
        this._renderStudio();
        const box = this._dom.panel.querySelector('[data-ai-plugin-manifest]');
        if (box) box.value = JSON.stringify(artifact.payload || {}, null, 2);
    },

    _applyMemoryArtifact(id) {
        const artifact = this._artifactById(id);
        if (!artifact) return;
        const text = String((artifact.payload || {}).text || '').trim();
        if (!text) return;
        AIHttp.post('/memories', { text })
            .then(({ data }) => {
                if (!data.ok) throw new Error(data.error || 'save failed');
                this._toast(I18n.t(data.duplicate ? 'ai.memoryDuplicate' : 'ai.memorySaved'));
            })
            .catch((error) => this._toast(error.message));
    },

    /* A chart_spec is a proposal with ONE mechanical action: render it through the SAME endpoint
       the dashboard uses. The server validates the chart type, the dataset and every named column;
       this page holds no second opinion about either the registry or the data contract. */
    async _applyChartArtifact(id) {
        const artifact = (this._artifactsById || {})[id] || this._artifactById(id);
        if (!artifact) return;
        try {
            const { data: prepared } = await AIHttp.post('/chart/preview', { spec: artifact.payload || {} });
            if (!prepared.ok) throw new Error(prepared.error || I18n.t('ai.error'));
            const { data: result } = await ProductHttp.post('/api/visualize/render', prepared.request);
            if (!result.ok) throw new Error(result.error || I18n.t('ai.error'));
            if (typeof renderChartPreview !== 'function') throw new Error(I18n.t('ai.chartPainterMissing'));
            renderChartPreview(result);
            this._toast(I18n.t('ai.chartRendered'));
        } catch (error) {
            this._toast(error.message || I18n.t('ai.error'));
        }
    },

    _toast(message) {
        if (typeof showToast === 'function') showToast(message);
    },

    _copyText(text) {
        /* A packaged window (WebView2/WKWebView) and a plain-http LAN page are both outside the
           secure-context guarantee, so navigator.clipboard can be absent or reject. The textarea
           fallback is the only path left; it must not leave a visible node behind. */
        const done = () => this._toast(I18n.t('ai.copied'));
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(done, () => this._copyWithTextarea(text, done));
            return;
        }
        this._copyWithTextarea(text, done);
    },

    _copyWithTextarea(text, done) {
        const area = document.createElement('textarea');
        area.value = text;
        area.setAttribute('readonly', 'readonly');
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        try {
            area.select();
            if (document.execCommand && document.execCommand('copy')) done();
            else this._toast(I18n.t('ai.error'));
        } finally {
            area.remove();
        }
    },

});
