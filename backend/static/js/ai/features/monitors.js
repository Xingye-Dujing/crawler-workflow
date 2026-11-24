/* Run monitors, and the failed-node card a monitor's answer brings.
 *
 * The builder offers only the event names the server's catalog knows, arms through the same route
 * the artifact card uses, and a failure answer carries the rerun action rather than a sentence to
 * copy.
 */

Object.assign(AIWorkspace, {
    /* ``app_errors`` is the evidence the model reads after a monitor fires; its failed nodes become
       one card with a button that reruns that subtree from the SAVED file. */
    _ingestFailedNodes(result, current) {
        const runs = Array.isArray(result && result.runs) ? result.runs : [];
        if (!runs.length) return;
        const wanted = String((this._monitorFailed && this._monitorFailed.run_id) || '');
        const run = runs.find((row) => String(row.run_id || '') === wanted) || runs[0];
        const nodes = (Array.isArray(run.nodes) ? run.nodes : [])
            .filter((node) => ['failed', 'partial'].includes(String(node.status || '')) || node.error)
            .map((node) => ({ node: String(node.node || node.node_id || ''), error: String(node.error || '') }))
            .filter((node) => node.node);
        const runId = String(run.run_id || wanted || '');
        const workflowName = String(run.workflow || (this._monitorFailed && this._monitorFailed.workflow_name) || '');
        this._pushFailedCard(runId, workflowName, nodes, current);
    },

    /* ``run_status`` is the other reader a monitor turn uses; it answers one run with a node map. */
    _ingestRunNodes(result, current) {
        const run = (result && result.run) || {};
        const nodes = result && result.nodes;
        if (!nodes || typeof nodes !== 'object') return;
        const rows = Object.entries(nodes)
            .filter(([, row]) => row && (['failed', 'partial'].includes(String(row.status || '')) || row.error))
            .map(([id, row]) => ({ node: String(id), error: String((row && row.error) || '') }));
        const runId = String(run.id || run.run_id || '');
        if (!runId) return;
        this._pushFailedCard(runId, String(run.workflow_name || ''), rows, current);
    },

    _pushFailedCard(runId, workflowName, nodes, current) {
        if (!nodes.length) return;
        const existing = (current.blocks || []).find((row) => row.type === 'failed_nodes' && String(row.run_id || '') === runId);
        if (existing) {
            existing.nodes = nodes;
            existing.workflow_name = workflowName || existing.workflow_name || '';
        } else {
            current.blocks.push({ type: 'failed_nodes', run_id: runId, workflow_name: workflowName, nodes: nodes });
        }
        this._schedulePaint(current);
    },

    _markRerunStarted(runId, nodeId, workflowName, current) {
        const turn = current || this._current || this._ensureAssistant();
        const block = (turn.blocks || []).find((row) => row.type === 'failed_nodes' && String(row.run_id || '') === String(runId || ''));
        if (block) {
            block.started = nodeId;
            if (workflowName) block.workflow_name = workflowName;
            if (!(block.nodes || []).some((node) => String(node.node || '') === String(nodeId || ''))) {
                block.nodes = (block.nodes || []).concat([{ node: nodeId, error: '' }]);
            }
            return;
        }
        turn.blocks.push({
            type: 'failed_nodes',
            run_id: String(runId || ''),
            workflow_name: String(workflowName || ''),
            nodes: [{ node: String(nodeId || ''), error: '' }],
            started: String(nodeId || ''),
        });
    },

    async _rerunFailedNode(runId, nodeId, workflowName) {
        if (!runId || !nodeId) {
            this._toast(I18n.t('ai.rerunNoWorkflowHint'));
            return false;
        }
        if (typeof showDialog !== 'function') return false;
        const answer = await showDialog({
            message: I18n.t('ai.rerunConfirm', { run: runId, node: nodeId }),
            buttons: [
                { label: I18n.t('ai.rerunNode'), value: true, primary: true },
                { label: I18n.t('ai.close'), value: false },
            ],
            cancelValue: false,
        });
        if (answer !== true) return false;
        try {
            const { data } = await AIHttp.post('/rerun', {
                conversation_id: this._conversationId,
                run_id: runId,
                workflow_name: workflowName,
                node_id: nodeId,
            });
            if (!data.ok) {
                this._toast(I18n.t('ai.rerunFailed', { detail: data.error || I18n.t('ai.error') }));
                return false;
            }
            this._markRerunStarted(data.run_id || runId, data.node_id || nodeId, data.workflow_name || workflowName);
            this._paintAssistant();
            this._toast(data.message || I18n.t('ai.rerunStarted', { node: nodeId }));
            return true;
        } catch (error) {
            this._toast(I18n.t('ai.rerunFailed', { detail: error.message }));
            return false;
        }
    },

    _workflowFeedback(title, detail) {
        const turn = this._feedbackTurn || '';
        if (this._sending || (turn && turn === (this._current && this._current.turnId))) return;
        this._feedbackTurn = (this._current && this._current.turnId) || 'pending';
        /* Three attempts is already a conversation about a broken draft, not a retry loop the user
           did not ask for. After that the failure stays on screen for them to decide. */
        this._feedbackCount = (this._feedbackCount || 0) + 1;
        const text = I18n.t('ai.feedback.workflow', { name: title || 'AI', detail: detail || '—' });
        this._renderError(text);
        if (this._feedbackCount > 3) return;
        this._sendText(text, { feedback: true });
    },

    async deliverMonitor(event) {
        const monitor = (this._bootstrap?.monitors || []).find((item) => item.id === event.monitor_id);
        const auto = !!monitor?.auto_analyze;
        if (!auto) {
            if (this._open && this._conversationId === event.conversation_id) {
                const meta = event.payload || {};
                this._appendUser(
                    I18n.t('ai.monitor.notice') + ': ' + String(meta.event || '') + ' · ' + String(meta.run_id || ''),
                    {},
                    [],
                    { monitor_event: event.id }
                );
            }
            this._toast(I18n.t('ai.monitor.armed') + ' · ' + I18n.t('ai.monitor.notice'));
            return true;
        }
        // A turn already streaming owns the transcript; leave the event pending so the next tick
        // delivers it after the answer, instead of interleaving two conversations.
        if (this._sending) return false;
        const target = String(event.conversation_id || '');
        if (target && target !== this._conversationId) {
            if (!this._open) this.open({ silent: true });
            await this.selectConversation(target);
        }
        const conversation = (this._bootstrap?.conversations || []).find((item) => item.id === (target || this._conversationId));
        if (conversation?.provider) {
            this._provider = conversation.provider;
            this._model = conversation.model || AISettings.modelFor(this._provider, this._bootstrap?.providers);
        }
        const facts = JSON.stringify(event.payload || {}, null, 2);
        const failed = ['failed', 'partial', 'stopped'].includes(String((event.payload || {}).outcome || (event.payload || {}).status || ''));
        if (failed) {
            // The card is built from the run this event names, not from whatever app_errors returns
            // first: a conversation may know about several runs.
            const payload = event.payload || {};
            this._monitorFailed = {
                run_id: String(payload.run_id || ''),
                workflow_name: String(payload.workflow || payload.workflow_name || ''),
                node_id: String(payload.node_id || ''),
                label: String(payload.label || ''),
            };
        } else {
            this._monitorFailed = null;
        }
        const tail = failed
            ? I18n.t('ai.monitor.promptFailure')
            : I18n.t('ai.monitor.promptAsk');
        const text = I18n.t('ai.monitor.promptHead') + '\n```json\n' + facts + '\n```\n' + tail;
        return this._sendText(text, { monitor: true, monitorEventId: event.id });
    },

    /* Manual monitor builder. The event/status/outcome names come from the SERVER's matcher table —
       the page holds no second list — and the rule is POSTed through the SAME arm endpoint the
       artifact card uses, so the validator and the delivery path cannot drift apart. */
    async _newMonitor() {
        if (typeof showDialog !== 'function') return;
        let catalog;
        try {
            catalog = (await AIHttp.get('/monitors/catalog')).data.catalog || {};
        } catch (error) {
            this._toast(I18n.t('ai.monitor.failed') + ': ' + error.message);
            return;
        }
        const events = Array.isArray(catalog.events) ? catalog.events : [];
        const message = I18n.t('ai.monitor.build.hint', {
            events: events.join(', '),
            statuses: (catalog.statuses || []).join(', '),
            outcomes: (catalog.outcomes || []).join(', '),
        });
        const answer = await showDialog({
            message,
            fields: [
                {
                    id: 'ai-mon-event',
                    label: I18n.t('ai.monitor.build.event'),
                    type: 'select',
                    options: events.map((name) => ({ value: name, label: name })),
                    value: events[0] || '',
                },
                { id: 'ai-mon-statuses', label: I18n.t('ai.monitor.build.statuses'), type: 'text' },
                { id: 'ai-mon-outcomes', label: I18n.t('ai.monitor.build.outcomes'), type: 'text' },
                { id: 'ai-mon-run', label: I18n.t('ai.monitor.build.runId'), type: 'text' },
                { id: 'ai-mon-console', label: I18n.t('ai.monitor.build.console'), type: 'text' },
                { id: 'ai-mon-note', label: I18n.t('ai.monitor.build.note'), type: 'text' },
            ],
            toggles: [{ id: 'ai-mon-auto', label: I18n.t('ai.monitor.build.auto'), checked: false }],
            buttons: [
                { label: I18n.t('ai.monitor.build.create'), value: 'create', primary: true, collect: true },
                { label: I18n.t('dialog.cancel'), value: 'cancel' },
            ],
            cancelValue: null,
        });
        if (!answer || answer.value !== 'create') return;
        const fields = answer.fields || {};
        const list = (value) => String(value || '').split(',').map((part) => part.trim()).filter(Boolean);
        const spec = {
            events: [String(fields['ai-mon-event'] || events[0] || '').trim()].filter(Boolean),
            statuses: list(fields['ai-mon-statuses']),
            outcomes: list(fields['ai-mon-outcomes']),
            run_id: String(fields['ai-mon-run'] || '').trim(),
            console_contains: String(fields['ai-mon-console'] || '').trim(),
            note: String(fields['ai-mon-note'] || '').trim(),
        };
        try {
            const conversationId = await this._ensureConversation();
            const { data } = await AIHttp.post('/monitors', {
                conversation_id: conversationId,
                spec,
                auto_analyze: !!(answer.toggles || {})['ai-mon-auto'],
            });
            if (!data.ok) throw new Error(data.error || I18n.t('ai.error'));
            this._bootstrap.monitors = [data.monitor, ...(this._bootstrap.monitors || [])];
            this._renderSide();
            this._toast(I18n.t('ai.monitor.build.created'));
        } catch (error) {
            this._toast(I18n.t('ai.monitor.failed') + ': ' + error.message);
        }
    },

});
