/* Safe rendering for model output. Everything is escaped FIRST, then a small Markdown subset is
 * turned into elements; raw HTML never survives. Links are limited to http/https. */
const AIRender = {
    escape(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    safeUrl(value) {
        const raw = String(value || '').trim();
        return /^https?:\/\//i.test(raw) ? raw : '';
    },

    inline(text) {
        /* Links are lifted out BEFORE escaping. Escaping first turned a URL's ``&`` into ``&amp;``
           and the link pass then escaped it again, so ``?a=1&b=2`` became ``?a=1&amp;amp;b=2`` and
           every link with a query string opened the wrong address. The placeholders survive the
           escape and the emphasis passes; the anchors are inserted last. */
        const anchors = [];
        const linked = String(text == null ? '' : text).replace(
            /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
            (match, label, url) => {
                const safe = this.safeUrl(url);
                if (!safe) return match;
                const token = '\u0000LINK' + anchors.length + '\u0000';
                anchors.push(
                    '<a href="' + this.escape(safe) + '" target="_blank" rel="noopener noreferrer">' +
                        this.escape(label) + '</a>'
                );
                return token;
            }
        );
        let out = this.escape(linked);
        out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
        out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        out = out.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
        out = out.replace(/\u0000LINK(\d+)\u0000/g, (match, index) => anchors[Number(index)] || '');
        return out;
    },

    /* Split one table row into cells. Two things are NOT column breaks:
       - a `|` inside inline code (`` `a|b` ``), which a model writes all the time when naming a
         pipe-joined value;
       - an escaped `\|`, Markdown's own way to keep a literal pipe in a cell.
       Without this, one cell became two and the rest of the row shifted. */
    tableCells(line) {
        const body = String(line || '').slice(1, -1);
        const cells = [];
        let current = '';
        let inCode = false;
        for (let index = 0; index < body.length; index += 1) {
            const ch = body[index];
            if (ch === '\\' && body[index + 1] === '|') {
                current += '|';
                index += 1;
                continue;
            }
            if (ch === '`') {
                inCode = !inCode;
                current += ch;
                continue;
            }
            if (ch === '|' && !inCode) {
                cells.push(current.trim());
                current = '';
                continue;
            }
            current += ch;
        }
        cells.push(current.trim());
        return cells;
    },

    markdown(text) {
        const source = String(text || '');
        const parts = [];
        let buffer = [];
        let inCode = false;
        let code = [];
        const flush = () => {
            if (buffer.length) {
                parts.push(this.paragraphs(buffer.join('\n')));
                buffer = [];
            }
        };
        for (const line of source.split(/\r?\n/)) {
            if (line.trim().startsWith('```')) {
                if (inCode) {
                    parts.push('<pre class="ai-code"><code>' + this.escape(code.join('\n')) + '</code></pre>');
                    code = [];
                    inCode = false;
                } else {
                    flush();
                    inCode = true;
                }
                continue;
            }
            if (inCode) {
                code.push(line);
            } else {
                buffer.push(line);
            }
        }
        if (inCode) parts.push('<pre class="ai-code"><code>' + this.escape(code.join('\n')) + '</code></pre>');
        flush();
        return parts.join('');
    },

    paragraphs(text) {
        const lines = text.split(/\r?\n/);
        const out = [];
        let list = null;
        let table = null;
        const closeList = () => {
            if (list) {
                out.push('<' + list.tag + '>' + list.items.map((item) => '<li>' + this.inline(item) + '</li>').join('') + '</' + list.tag + '>');
                list = null;
            }
        };
        const closeTable = () => {
            if (table) {
                /* A table is RECTANGULAR: a row with one cell too few/too many used to shift every
                   following column. Rows are padded/trimmed to the header's width. */
                const width = table.head.length;
                const head = '<thead><tr>' + table.head.map((cell) => '<th>' + this.inline(cell) + '</th>').join('') + '</tr></thead>';
                const body = '<tbody>' + table.rows
                    .map((row) => {
                        const cells = row.slice(0, width);
                        while (cells.length < width) cells.push('');
                        return '<tr>' + cells.map((cell) => '<td>' + this.inline(cell) + '</td>').join('') + '</tr>';
                    })
                    .join('') + '</tbody>';
                out.push('<div class="ai-table-wrap"><table class="ai-table">' + head + body + '</table></div>');
                table = null;
            }
        };
        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) {
                closeList();
                closeTable();
                continue;
            }
            if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
                closeList();
                const cells = this.tableCells(trimmed);
                if (cells.every((cell) => /^:?-{2,}:?$/.test(cell))) continue;
                if (!table) table = { head: cells, rows: [] };
                else table.rows.push(cells);
                continue;
            }
            closeTable();
            const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
            if (heading) {
                closeList();
                const level = Math.min(4, heading[1].length);
                out.push('<h' + level + '>' + this.inline(heading[2]) + '</h' + level + '>');
                continue;
            }
            if (/^>\s?/.test(trimmed)) {
                closeList();
                out.push('<blockquote>' + this.inline(trimmed.replace(/^>\s?/, '')) + '</blockquote>');
                continue;
            }
            const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
            const bullet = /^[-*+]\s+(.*)$/.exec(trimmed);
            if (ordered || bullet) {
                closeTable();
                const tag = ordered ? 'ol' : 'ul';
                if (!list || list.tag !== tag) {
                    closeList();
                    list = { tag, items: [] };
                }
                list.items.push((ordered || bullet)[1]);
                continue;
            }
            closeList();
            out.push('<p>' + this.inline(trimmed) + '</p>');
        }
        closeList();
        closeTable();
        return out.join('');
    },

    /* The exact act behind an approval question: resolved target facts and, for a write, the diff
       the user is being asked to allow. The server supplies every key; this only paints it. */
    approvalPreview(preview) {
        if (!preview || !preview.kind) return '';
        const facts = (preview.facts || []).map((fact) => {
            const key = String(fact.key || '');
            const label = I18n.has('ai.approvalField.' + key) ? I18n.t('ai.approvalField.' + key) : key;
            return (
                '<div class="ai-approval-fact"><dt>' + this.escape(label) + '</dt>' +
                '<dd><code>' + this.escape(String(fact.value || '')) + '</code></dd></div>'
            );
        }).join('');
        let diff = '';
        const lines = preview.diff || [];
        if (lines.length) {
            const rows = lines.map((line) => {
                const text = String(line);
                const tone = text.startsWith('+') ? ' add' : text.startsWith('-') ? ' del' : text.startsWith('@@') ? ' hunk' : '';
                return '<span class="ai-diff-line' + tone + '">' + this.escape(text) + '</span>';
            }).join('');
            diff =
                '<div class="ai-approval-diff">' +
                '<div class="ai-approval-diff-head">' +
                this.escape(I18n.t(preview.exists ? 'ai.approvalDiffOverwrite' : 'ai.approvalDiffNew')) +
                (preview.changed ? '' : ' · ' + this.escape(I18n.t('ai.approvalNoChange'))) +
                '</div><pre class="ai-diff">' + rows + '</pre>' +
                (preview.truncated ? '<div class="ai-hint">' + this.escape(I18n.t('ai.approvalDiffCut')) + '</div>' : '') +
                '</div>';
        } else if (preview.kind === 'write' && !preview.error) {
            diff =
                '<div class="ai-hint">' +
                this.escape(I18n.t(preview.changed ? 'ai.approvalNoDiff' : 'ai.approvalNoChange')) +
                '</div>';
        }
        return (
            '<div class="ai-approval-preview">' +
            (facts ? '<dl class="ai-approval-facts">' + facts + '</dl>' : '') +
            diff +
            (preview.error ? '<div class="ai-approval-error">' + this.escape(preview.error) + '</div>' : '') +
            '</div>'
        );
    },

    questionCard(question, answered) {
        /* An approval question is the same card with a danger tone: the runtime marks it with
           ``kind`` (and the stable id ``approval``), never with a translated sentence. */
        const approval = String(question.kind || '') === 'approval' || String(question.id || '') === 'approval';
        const options = (question.options || []).map((option, index) => {
            const description = option.description ? '<span class="ai-option-desc">' + this.escape(option.description) + '</span>' : '';
            return (
                '<button type="button" class="ai-option" data-ai-answer="' + this.escape(option.label) + '" data-ai-question="' + this.escape(question.id) + '">' +
                '<span class="ai-option-key">' + (index + 1) + '</span>' +
                '<span class="ai-option-label">' + this.escape(option.label) + description + '</span>' +
                '</button>'
            );
        }).join('');
        const custom = answered ? '' :
            '<div class="ai-question-refs" data-ai-question-refs="' + this.escape(question.id) + '"></div>' +
            '<textarea class="ai-answer-custom" data-ai-custom="' + this.escape(question.id) + '" rows="2" placeholder="' + this.escape(I18n.t('ai.customAnswerRefs')) + '"></textarea>';
        const customButton = answered ? '' : '<button type="button" class="ai-ghost" data-ai-send-custom="' + this.escape(question.id) + '">' + this.escape(I18n.t('ai.answer')) + '</button>';
        return (
            '<section class="ai-question' + (approval ? ' ai-question-approval' : '') + '" data-ai-question-card="' + this.escape(question.id) + '">' +
            '<div class="ai-question-head"><span class="ai-dot"></span>' + this.escape(question.header || I18n.t('ai.questionTitle')) +
            (approval ? '<span class="ai-chip ai-chip-danger">' + this.escape(I18n.t('ai.approvalBadge')) + '</span>' : '') +
            '</div>' +
            '<p class="ai-question-text">' + this.inline(question.question) + '</p>' +
            this.approvalPreview(question.preview) +
            '<div class="ai-options">' + options + '</div>' +
            custom + customButton +
            (answered ? '<div class="ai-question-answered">' + this.escape(I18n.t('ai.questionAnswered')) + '</div>' : '') +
            '</section>'
        );
    },

    failedNodesCard(block) {
        /* A monitor's failure answer names the nodes it could rerun; the button calls the same
           server decision as the canvas's 重跑节点 and never loads the canvas here. */
        const nodes = Array.isArray(block && block.nodes) ? block.nodes : [];
        if (!nodes.length) return '';
        const runId = String(block.run_id || '');
        const workflow = String(block.workflow_name || '');
        const rows = nodes.map((node) => {
            const nid = String(node.node || node.id || '');
            const error = String(node.error || '') || I18n.t('ai.failedNodeNoError');
            const action = runId
                ? '<button type="button" class="ai-ghost" data-ai-rerun-run="' + this.escape(runId) + '" data-ai-rerun-workflow="' + this.escape(workflow) + '" data-ai-rerun-node="' + this.escape(nid) + '">' + this.escape(I18n.t('ai.rerunNode')) + '</button>'
                : '<span class="ai-hint">' + this.escape(I18n.t('ai.rerunNoWorkflowHint')) + '</span>';
            return (
                '<li class="ai-failed-node">' +
                '<span class="ai-failed-node-id">' + this.escape(nid) + '</span>' +
                '<span class="ai-failed-node-error">' + this.escape(error) + '</span>' +
                action +
                '</li>'
            );
        }).join('');
        const started = String(block.started || '');
        return (
            '<section class="ai-failed-nodes' + (started ? ' is-started' : '') + '">' +
            '<div class="ai-question-head"><span class="ai-dot"></span>' + this.escape(I18n.t('ai.failedNodesTitle')) + '</div>' +
            '<ul>' + rows + '</ul>' +
            (started ? '<div class="ai-question-answered">' + this.escape(I18n.t('ai.rerunStarted', { node: started })) + '</div>' : '') +
            '</section>'
        );
    },

    sourceCard(block) {
        if (!block || typeof block !== 'object') return '';
        if (block.type === 'server_tool_use') {
            const action = block.input || {};
            if (action.action === 'search' || action.action === 'deep_search') {
                const queries = (action.queries || []).map((query) => '“' + this.escape(query) + '”').join(' ');
                return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.searching')) + '</span>' + queries + '</div>';
            }
            if (action.action === 'open_page' || action.action === 'read_link') {
                const url = this.safeUrl(action.url);
                return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.reading')) + '</span>' + (url ? '<a href="' + this.escape(url) + '" target="_blank" rel="noopener noreferrer">' + this.escape(url) + '</a>' : this.escape(action.url || '')) + '</div>';
            }
            if (action.action === 'find_in_page') {
                return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.reading')) + '</span>' + this.escape(action.pattern || '') + '</div>';
            }
            return '';
        }
        if (block.type === 'web_search_tool_result') {
            const results = (block.content || []).filter((item) => item && item.type === 'web_search_result');
            if (!results.length) {
                const error = (block.content || [])[0] || {};
                return '<div class="ai-source-card ai-source-error">' + this.escape(error.error_code || 'search unavailable') + '</div>';
            }
            return results.map((item, index) =>
                '<a class="ai-source-card ai-source-link" href="' + this.escape(this.safeUrl(item.url)) + '" target="_blank" rel="noopener noreferrer">' +
                '<span class="ai-source-index">' + (index + 1) + '</span>' +
                '<span class="ai-source-body"><span class="ai-source-title">' + this.escape(item.title || item.url) + '</span>' +
                '<span class="ai-source-meta">' + this.escape(item.site_name || '') + (item.page_age ? ' · ' + this.escape(String(item.page_age).slice(0, 10)) : '') + '</span>' +
                (item.snippet ? '<span class="ai-source-snippet">' + this.escape(item.snippet) + '</span>' : '') +
                '</span></a>'
            ).join('');
        }
        if (block.type === 'web_fetch_tool_result') {
            const content = block.content || {};
            if (content.type === 'web_fetch_tool_result_error') {
                return '<div class="ai-source-card ai-source-error">' + this.escape(content.error_code || 'fetch failed') + '</div>';
            }
            const url = this.safeUrl(content.url);
            return '<div class="ai-source-card"><span class="ai-source-kind">' + this.escape(I18n.t('ai.reading')) + '</span>' + (url ? '<a href="' + this.escape(url) + '" target="_blank" rel="noopener noreferrer">' + this.escape(content.content?.title || url) + '</a>' : this.escape(content.content?.title || '')) + '</div>';
        }
        return '';
    },

    artifactCard(artifact) {
        if (!artifact) return '';
        const label = I18n.t('ai.artifact') + ' · ' + String(artifact.kind || 'markdown');
        const summary = artifact.summary ? '<p class="ai-artifact-summary">' + this.inline(artifact.summary) + '</p>' : '';
        const apply = artifact.kind === 'skill_draft'
            ? '<button type="button" class="ai-primary" data-ai-apply-skill="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.openEditor')) + '</button>'
            : artifact.kind === 'plugin_manifest'
                ? '<button type="button" class="ai-primary" data-ai-apply-plugin="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.openInstaller')) + '</button>'
                : artifact.kind === 'monitor'
                    ? '<button type="button" class="ai-primary" data-ai-apply-monitor="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.monitor.auto')) + '</button>' +
                      '<button type="button" class="ai-ghost" data-ai-watch-only="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.monitor.watchOnly')) + '</button>'
                    : artifact.kind === 'memory'
                        ? '<button type="button" class="ai-primary" data-ai-apply-memory="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.remember')) + '</button>'
                    : (artifact.kind === 'workflow' || artifact.kind === 'workflow_draft')
                        ? '<button type="button" class="ai-primary" data-ai-apply-workflow="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.workflowLoad')) + '</button>' +
                          '<button type="button" class="ai-ghost" data-ai-run-workflow="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.workflowLoadRun')) + '</button>'
                        : artifact.kind === 'chart_spec'
                            ? '<button type="button" class="ai-primary" data-ai-apply-chart="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.chartRender')) + '</button>'
                        /* Every OTHER artifact (a plan, a report) is a proposal with no
                           mechanical "apply" of its own — but it must still be actionable, or it reads
                           as a dead card. The button hands the proposal back to the assistant, which
                           builds the canvas with its validated tools. */
                        : '<button type="button" class="ai-primary" data-ai-implement-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.artifactImplement')) + '</button>';
        /* A previewable artifact gets a second, additive door: the primary button still applies
           directly, but this one shows the exact change first and lets the user pick the parts.
           The server decides which kinds have a published preview — this is only the card. */
        const previewable = ['memory', 'workflow', 'workflow_draft', 'monitor', 'chart_spec'];
        const previewButton = previewable.includes(String(artifact.kind || ''))
            ? '<button type="button" class="ai-ghost" data-ai-preview-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.preview.button')) + '</button>'
            : '';
        return (
            '<section class="ai-artifact" data-ai-artifact="' + this.escape(artifact.id || '') + '">' +
            '<div class="ai-artifact-head"><span class="ai-artifact-kind">' + this.escape(label) + '</span><span>' + this.escape(artifact.title || '') + '</span></div>' +
            summary +
            '<details class="ai-artifact-body" data-ai-detail="artifact:' + this.escape(String(artifact.id || '')) + ':body"><summary>' + this.escape(I18n.t('ai.preview')) + '</summary><pre class="ai-code">' + this.escape(JSON.stringify(artifact.payload || {}, null, 2)) + '</pre></details>' +
            '<div class="ai-artifact-actions">' + apply + previewButton + '<button type="button" class="ai-ghost" data-ai-copy-artifact="' + this.escape(artifact.id || '') + '">' + this.escape(I18n.t('ai.copy')) + '</button><span class="ai-hint">' + this.escape(I18n.t('ai.applyHint')) + '</span></div>' +
            '</section>'
        );
    },

    /* While a tool runs, say WHAT is being produced — a plan, a question, a workflow — instead of a
       generic “读取中…”. The model emits no prose before `present_artifact` / `ask_user_question`, so
       without this the turn looks stalled exactly when the useful part is being built. */
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
                const id = String(block.name || '');
                const nameKey = 'ai.skill.' + id + '.name';
                const label = I18n.has(nameKey) ? I18n.t(nameKey) : id;
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

    number(value) {
        return Number(value || 0).toLocaleString();
    },
};
window.AIRender = AIRender;
