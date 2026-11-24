/* The tool card, the running label and the one assistant flow.
 *
 * One turn is a SEQUENCE — skill, thinking, tools, plan, answer — and this file is the definition of
 * that order for both the live view and a reopened one (`assistantFlow`), plus the live status row
 * and the usage line.
 */

Object.assign(AIRender, {
    _runningLabel(name) {
        const tool = String(name || '');
        /* Every phase of a turn says what it is doing. The families below cover the whole built-in
           tool table; anything else (a plugin's tool) still gets a sentence that NAMES it, so no
           generation step is ever a silent tool card. */
        const families = [
            ['present_artifact', 'ai.toolRunningArtifact'],
            ['ask_user_question', 'ai.toolRunningQuestion'],
            ['apply_workflow', 'ai.toolRunningWorkflow'],
            ['rerun_node', 'ai.toolRunningRerun'],
            ['request_approval', 'ai.toolRunningApproval'],
            ['update_plan', 'ai.toolRunningPlan'],
            ['run_cmd', 'ai.toolRunningCommand'],
            ['python_run', 'ai.toolRunningPython'],
            ['python_save_script', 'ai.toolRunningPythonSave'],
            ['python_write', 'ai.toolRunningPythonWrite'],
            ['workspace_import', 'ai.toolRunningImport'],
            ['workspace_write', 'ai.toolRunningWrite'],
            ['workspace_list', 'ai.toolRunningList'],
            ['workspace_info', 'ai.toolRunningFolder'],
            ['workspace_read', 'ai.toolRunningRead'],
            ['workflow_schema', 'ai.toolRunningSchema'],
            ['workflow_validate', 'ai.toolRunningValidate'],
            ['app_errors', 'ai.toolRunningErrors'],
            ['run_status', 'ai.toolRunningRunStatus'],
            ['run_console', 'ai.toolRunningRunConsole'],
            ['list_runs', 'ai.toolRunningListRuns'],
            ['dataset_peek', 'ai.toolRunningPeek'],
            ['dataset_query', 'ai.toolRunningQuery'],
            ['dataset_page', 'ai.toolRunningPage'],
            ['dataset_profile', 'ai.toolRunningProfile'],
            ['list_datasets', 'ai.toolRunningListDatasets'],
            ['chart_catalog', 'ai.toolRunningCharts'],
            ['analysis_catalog', 'ai.toolRunningOps'],
            ['project_facts', 'ai.toolRunningFacts'],
            ['capabilities', 'ai.toolRunningCapabilities'],
            ['docs_search', 'ai.toolRunningDocs'],
            ['code_search', 'ai.toolRunningCodeSearch'],
            ['code_read', 'ai.toolRunningCodeRead'],
            ['python_scripts', 'ai.toolRunningScripts'],
            ['web_search', 'ai.toolRunningWebSearch'],
            ['web_fetch', 'ai.toolRunningWebFetch'],
        ];
        for (const [toolName, key] of families) {
            if (tool === toolName && I18n.has(key)) return I18n.t(key);
        }
        if (I18n.has('ai.toolRunningNamed')) return I18n.t('ai.toolRunningNamed', { tool: tool || 'tool' });
        return I18n.t('ai.toolRunning');
    },

    toolCard(name, args, status, result, block) {
        const summary = status === 'running' ? this._runningLabel(name) : status === 'failed' ? I18n.t('ai.toolFailed') : I18n.t('ai.toolDone');
        const row = block || {};
        let took = '';
        if (row.startedAt && row.endedAt && row.endedAt >= row.startedAt) {
            const seconds = (row.endedAt - row.startedAt) / 1000;
            took = seconds < 1 ? '< 1s' : (seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)) + 's';
        }
        const detailKey = 'tool:' + String(row.id || row.name || '');
        const detail = status === 'done' && result
            ? '<details class="ai-tool-detail" data-ai-detail="' + this.escape(detailKey + ':result') + '"><summary>' + this.escape(I18n.t('ai.toolResult')) + '</summary><pre class="ai-code">' + this.escape(JSON.stringify(result, null, 2)) + '</pre></details>'
            : status === 'failed' && result
                ? '<pre class="ai-code ai-tool-error">' + this.escape(typeof result === 'string' ? result : JSON.stringify(result, null, 2)) + '</pre>'
                : '';
        /* What it was ASKED to do, not only what came back: a reader following the trace needs the
           folder/command/kind, and the running card would otherwise show only a tool name. */
        let argsText = '';
        try {
            const raw = args && typeof args === 'object' && Object.keys(args).length ? JSON.stringify(args) : '';
            if (raw) argsText = raw.length > 180 ? raw.slice(0, 180) + '…' : raw;
        } catch (error) {
            argsText = '';
        }
        const argsLine = argsText ? '<code class="ai-tool-args">' + this.escape(argsText) + '</code>' : '';
        const runningClock = status === 'running' ? '<span class="ai-tool-clock" aria-hidden="true"></span>' : '';
        return (
            '<div class="ai-tool ' + (status === 'running' ? 'is-running' : status === 'failed' ? 'is-failed' : '') + '">' +
            '<span class="ai-tool-dot"></span><span class="ai-tool-name">' + this.escape(name) + '</span>' +
            argsLine +
            '<span class="ai-tool-state">' + this.escape(summary) + runningClock + (took ? ' · ' + this.escape(took) : '') + '</span>' +
            detail +
            '</div>'
        );
    },

    /* The transcript's ONE body painter, for a live turn and for a stored one.

       A turn is a SEQUENCE: thinking, a tool call, more thinking, the answer. The live view used to
       keep three fixed boxes (thinking / text / tools) and append each delta into its own box, so
       the order on screen was the boxes' order, not the model's — the answer appeared above the
       search it was based on. Walking the blocks in order fixes both that and the double listing:
       a tool renders once, keyed by its call id. */
    assistantFlow(blocks) {
        const parts = [];
        let group = null;
        const flush = () => {
            if (!group) return;
            parts.push('<div class="ai-flow-group ai-group-' + group.kind + '">' + group.rows.join('') + '</div>');
            group = null;
        };
        const push = (kind, row) => {
            if (!group || group.kind !== kind) {
                flush();
                group = { kind: kind, rows: [] };
            }
            group.rows.push(row);
        };
        const seen = new Set();
        let thinkingIndex = 0;
        for (const block of blocks || []) {
            if (!block || typeof block !== 'object') continue;
            const type = String(block.type || '');
            if (type === 'thinking') {
                const text = String(block.thinking || '');
                if (!text) continue;
                flush();
                thinkingIndex += 1;
                parts.push(
                    '<details class="ai-thinking" data-ai-detail="thinking:' + thinkingIndex + '"><summary>' +
                    this.escape(I18n.t('ai.thinkingLabel')) +
                    '</summary><pre class="ai-thinking-body">' + this.escape(text) + '</pre></details>'
                );
                continue;
            }
            if (type === 'skill') {
                flush();
                const ids = Array.isArray(block.names) && block.names.length ? block.names.map(String) : [String(block.name || '')];
                const id = ids[0] || '';
                const labels = ids.map((value) => {
                    const key = 'ai.skill.' + value + '.name';
                    return I18n.has(key) ? I18n.t(key) : value;
                });
                const label = labels.join(' + ');
                const reason = String(block.reason || '');
                /* Three distinct facts: auto-routed, chosen by the user, or authored by the model.
                   Printing the skill's own name as its "reason" (`画布建构师 · 画布建构师`) said
                   nothing; the block carries which of the three it was. */
                let why = '';
                if (reason === 'auto') why = I18n.t('ai.skillAuto');
                else if (reason && reason !== id && reason !== label) {
                    why = I18n.has('ai.skill.' + reason + '.name') ? I18n.t('ai.skill.' + reason + '.name') : reason;
                } else if (reason) why = I18n.t('ai.skillManual');
                parts.push(
                    '<details class="ai-skill-row" data-ai-detail="skill:' + this.escape(id) + '" data-ai-skill="' + this.escape(id) + '">' +
                    '<summary><span class="ai-skill-kind">' + this.escape(I18n.t('ai.skillRow')) + '</span>' +
                    '<span class="ai-skill-name">' + this.escape(label) + '</span>' +
                    (why ? '<span class="ai-skill-why">' + this.escape(why) + '</span>' : '') +
                    '</summary>' +
                    '<div class="ai-skill-body"><div class="ai-hint">' + this.escape(I18n.t('ai.skillHint')) + '</div></div>' +
                    '</details>'
                );
                continue;
            }
            if (type === 'plan') {
                flush();
                const steps = Array.isArray(block.steps) ? block.steps : [];
                if (!steps.length) continue;
                parts.push(
                    '<div class="ai-plan"><div class="ai-plan-head">' + this.escape(I18n.t('ai.plan')) + '</div><ol>' +
                    steps.map((step) => {
                        const status = String(step.status || 'pending');
                        return '<li class="ai-plan-step is-' + this.escape(status) + '">' +
                            '<span class="ai-plan-dot" aria-hidden="true"></span>' +
                            '<span>' + this.escape(String(step.title || '')) + '</span></li>';
                    }).join('') +
                    '</ol></div>'
                );
                continue;
            }
            if (type === 'failed_nodes') {
                flush();
                const card = this.failedNodesCard(block);
                if (card) parts.push(card);
                continue;
            }
            if (type === 'text') {
                const text = String(block.text || '');
                if (!text) continue;
                flush();
                parts.push('<div class="ai-text">' + this.markdown(text) + '</div>');
                continue;
            }
            if (type === 'error') {
                flush();
                parts.push('<div class="ai-error-text">' + this.escape(block.text || '') + '</div>');
                continue;
            }
            if (type === 'note') {
                /* A quiet line for a state that is not a failure (停止, 等待选择). */
                flush();
                parts.push('<div class="ai-note">' + this.escape(block.text || '') + '</div>');
                continue;
            }
            if (type === 'tool_use') {
                /* The question card (or its answered row) IS the rendering of `ask_user_question`;
                   a second generic tool card above it was noise. */
                if (String(block.name || '') === 'ask_user_question') continue;
                const key = String(block.id || '') || 'name:' + String(block.name || '');
                if (seen.has(key)) continue;
                seen.add(key);
                push('tools', this.toolCard(block.name || '', block.input || {}, block.status || 'done', block.result ?? null, block));
                continue;
            }
            if (type === 'server_tool_use' || type === 'web_search_tool_result' || type === 'web_fetch_tool_result') {
                const key = 'srv:' + String(block.id || block.tool_use_id || '');
                if (key !== 'srv:' && seen.has(key)) continue;
                if (key !== 'srv:') seen.add(key);
                const card = this.sourceCard(block);
                if (card) push('sources', card);
            }
        }
        flush();
        return parts.join('');
    },

    statusRow() {
        /* The live line ("生成中 · 12s"). It is its OWN node, not part of `.ai-flow`: the flow is
           memoised by its HTML string, so a line carrying a ticking second would either freeze or
           force a full repaint of the whole block stream once a second.

           Two children, for a reason a screen reader makes plain: the WORDS are the live region and
           change only when the phase does, while the seconds are `aria-hidden` — a polite region
           that re-announced itself every second would be unusable. */
        return (
            '<div class="ai-status" hidden>' +
            '<span class="ai-working-dot" aria-hidden="true"></span>' +
            '<span class="ai-status-text" role="status" aria-live="polite"></span>' +
            '<span class="ai-status-clock" aria-hidden="true"></span></div>'
        );
    },

    usage(usage) {
        if (!usage) return '';
        return (
            '<div class="ai-usage">' +
            this.escape(I18n.t('ai.usageLine', {
                prompt: usage.prompt_tokens || 0,
                completion: usage.completion_tokens || 0,
                cached: usage.cached_tokens || 0,
            })) +
            '</div>'
        );
    },

});
