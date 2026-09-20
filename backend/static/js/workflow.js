/* Workflow Execution & File Management */
const workflow = {
    currentFile: null,

    async save() {
        const workflowData = canvas.toWorkflowJSON();
        let name = this.currentFile;
        if (!name) {
            name = await showDialog({
                message: I18n.t('dialog.workflowName'),
                input: { placeholder: 'my_workflow', value: '' },
                buttons: [
                    { label: I18n.t('dialog.cancel'), value: null },
                    { label: I18n.t('dialog.confirm'), primary: true },
                ],
            });
            if (!name) return;
            this.currentFile = name;
        }
        try {
            const resp = await fetch('/api/workflow/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name, workflow: workflowData }),
            });
            const result = await resp.json();
            if (result.ok) {
                showToast(I18n.t('toast.workflowSaved') + ': ' + name);
                localStorage.setItem('crawler_canvas', JSON.stringify(canvas.getState()));
            } else {
                showToast(I18n.t('toast.saveFailed') + ': ' + result.error);
            }
        } catch (e) {
            showToast(I18n.t('toast.saveFailed') + ': ' + e.message);
        }
    },

    async load() {
        try {
            const resp = await fetch('/api/workflow/list');
            const result = await resp.json();
            if (!result.ok || !result.workflows.length) {
                showToast(I18n.t('toast.noWorkflows'));
                return;
            }
            var names = result.workflows;
            if (names.length === 1) {
                this._loadByName(names[0]);
            } else {
                var chosen = await showDialog({
                    message: I18n.t('dialog.selectWorkflow'),
                    list: names,
                    buttons: [
                        { label: I18n.t('dialog.cancel'), value: null },
                    ],
                });
                if (chosen) this._loadByName(chosen);
            }
        } catch (e) {
            showToast(I18n.t('toast.loadFailed') + ': ' + e.message);
        }
    },

    _loadByName: async function (name) {
        try {
            var resp = await fetch('/api/workflow/load?name=' + encodeURIComponent(name));
            var result = await resp.json();
            if (result.ok) {
                this.loadFromJSON(result.workflow);
                this.currentFile = name;
                showToast(I18n.t('toast.workflowLoaded') + ': ' + name);
                /* The workflow we just opened may have an unfinished run filed
                   under the same shape — offer to continue it before the user
                   starts a second attempt from scratch. */
                if (window.resumeBar) resumeBar.refresh();
            } else {
                showToast(I18n.t('toast.loadFailed') + ': ' + result.error);
            }
        } catch (e) {
            showToast(I18n.t('toast.loadFailed') + ': ' + e.message);
        }
    },

    loadFromJSON(workflowData) {
        document.getElementById('nodes-container').innerHTML = '';
        canvas.nodes = {};
        canvas.connections = [];
        canvas.nextId = 1;
        workflowData.nodes.forEach(function (n) {
            canvas.addNode(n.type, n.x, n.y);
            var id = 'node-' + (canvas.nextId - 1);
            if (canvas.nodes[id]) {
                canvas.nodes[id].params = n.params || {};
                canvas.updateNodeDisplay(id);
            }
        });
        var ids = Object.keys(canvas.nodes);
        canvas.connections = (workflowData.connections || []).map(function (c) {
            var fromIdx = workflowData.nodes.findIndex(function (n) { return n.id === c.from; });
            var toIdx = workflowData.nodes.findIndex(function (n) { return n.id === c.to; });
            if (fromIdx >= 0 && toIdx >= 0 && ids[fromIdx] && ids[toIdx]) {
                return { from: ids[fromIdx], to: ids[toIdx] };
            }
            return null;
        }).filter(Boolean);
        canvas.scheduleRender();
        canvas.updateStatus();
        canvas.saveState();
        /* The nodes we just built may point at files the server still has —
           check each one instead of assuming it must be re-uploaded. */
        dataNodes.reconcileDatasets();
        /* Node ids are reassigned on load, so any panel on screen now belongs to
           a workflow that is no longer open. */
        if (canvas._settingsNodeId) closeSettings();
        var settings = workflowData.settings || {};
        if (settings.mode === 'serial') RunState.set('parallel', false);
        if (settings.headless === false) RunState.set('headless', false);
    },

    newFile() {
        document.getElementById('nodes-container').innerHTML = '';
        canvas.nodes = {};
        canvas.connections = [];
        canvas.nextId = 1;
        canvas.scheduleRender();
        canvas.updateStatus();
        if (canvas._settingsNodeId) closeSettings();
        this.currentFile = null;
        localStorage.removeItem('crawler_canvas');
        showToast(I18n.t('toast.newWorkflow'));
    },

    async execute(opts) {
        opts = opts || {};
        /* Validate before running */
        var validationErrors = this.validate();
        /* Async cookie check */
        try {
            var cookieResp = await fetch('/api/cookies/status');
            var cookieResult = await cookieResp.json();
            if (cookieResult.ok) {
                Object.keys(canvas.nodes).forEach(function (id) {
                    var node = canvas.nodes[id];
                    if (node.type === 'source') {
                        var platform = node.params.platform;
                        if (platform && cookieResult.cookies && !cookieResult.cookies[platform]) {
                            validationErrors.push(I18n.t('toast.cookiesMissing') + ' ' + platform);
                        }
                    }
                });
            }
        } catch (e) { /* skip cookie check if API fails */ }
        if (validationErrors.length > 0) {
            validationErrors.forEach(function (err) { showToast(err); });
            return;
        }
        RunState.setRunning(true);
        var statusText = document.getElementById('status-text');
        statusText.textContent = I18n.t('status.running');
        /* Open console and clear previous output */
        document.getElementById('console-panel').classList.add('open');
        document.getElementById('console-output').innerHTML = '';
        /* The run-records panel shares the console's bottom slot. */
        if (window.runsManager) runsManager.close();
        var workflowData = canvas.toWorkflowJSON();
        /* AI transport check — fail fast instead of dying 200 rows into a run. */
        var llm = LLMSettings.payload();
        if (canvas.nodes && Object.keys(canvas.nodes).some(function (id) {
            var n = canvas.nodes[id];
            return n.type === 'process' &&
                (n.params.operation === 'clean' ||
                    ((n.params.operation === 'emotion' || n.params.operation === 'tendency') && n.params.mode !== 'ml'));
        })) {
            /* Each transport has its own prerequisite: OpenRouter needs a key
               *and* a catalog model, the local daemon needs a tag it has pulled.
               The backend enforces the same rules, so neither side can start a
               run the other would refuse. */
            var missing = '';
            if (llm.provider === 'openrouter') {
                missing = !llm.api_key ? 'toast.aiNeedKey' : (!llm.model ? 'toast.aiNeedModel' : '');
            } else if (!llm.model) {
                missing = 'toast.aiNeedOllamaModel';
            }
            if (missing) {
                showToast(I18n.t(missing));
                RunState.setRunning(false);
                return;
            }
        }
        try {
            var resp = await fetch('/api/workflow/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                /* The run outlives this request, so its console language is
                   pinned here — X-Lang alone would die with the request. The
                   workflow name travels too: execution history groups runs by
                   it, and without it every run was filed as "untitled". */
                body: JSON.stringify({
                    workflow: workflowData,
                    llm: llm,
                    lang: I18n.lang,
                    workflow_name: this.currentFile || '',
                    /* The resume banner's "continue" passes the interrupted
                       run's id here: the backend reuses that run (same node
                       rows, same crawler cursors) instead of starting a fresh
                       one. Without it the backend mints a new id and every
                       cursor dies — the run silently degrades to a cold start. */
                    resume_run_id: opts.resumeRunId || '',
                }),
            });
            var result = await resp.json();
            if (result.ok) {
                showToast(I18n.t('toast.workflowStarted'));
                this.pollStatus();
            } else {
                showToast(I18n.t('toast.executeFailed') + ': ' + (result.error || ''));
                RunState.setRunning(false);
            }
        } catch (e) {
            showToast(I18n.t('toast.executeFailed') + ': ' + e.message);
            RunState.setRunning(false);
        }
    },

    async stop() {
        try {
            await fetch('/api/workflow/stop', { method: 'POST' });
            RunState.setRunning(false);
            showToast(I18n.t('toast.workflowStopped'));
        } catch (e) {
            showToast(I18n.t('toast.stopFailed') + ': ' + e.message);
        }
    },

    pollStatus: function () {
        /* The status endpoint ships only the last 200 console lines, but also
           reports how many exist in total. Deriving the delta from that total is
           what keeps the console alive past 200 lines: indexing the truncated
           array alone silently froze it (once the log passed 200 lines the
           browser believed it had already seen everything). */
        function freshLines(lines, total, seen) {
            var dropped = Math.max(0, (total || lines.length) - lines.length);
            return lines.slice(Math.max(0, seen - dropped));
        }
        /* Stick-to-bottom, not force-to-bottom. Measure BEFORE appending: if
           the user is already near the bottom they are "following" the stream,
           so keep doing it; if they scrolled up to read history, leave their
           position alone until they scroll back down themselves. Measuring
           before the append also keeps the first big batch flowing to the
           bottom — after it, the new rows themselves would look like the
           user having scrolled away. */
        function consoleWantsFollow(el) {
            return el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }
        var lastLogIdx = 0;
        var interval = setInterval(async function () {
            try {
                var resp = await fetch('/api/workflow/status');
                var result = await resp.json();
                if (result.logs) {
                    var lastLog = result.logs[result.logs.length - 1];
                    document.getElementById('status-text').textContent = lastLog || I18n.t('status.running');
                    var statusNodes = document.getElementById('status-nodes');
                    if (result.total_nodes > 0) {
                        statusNodes.textContent = I18n.t('status.progress')
                            .replace('{done}', result.completed_nodes)
                            .replace('{total}', result.total_nodes);
                    }
                    var consoleOut = document.getElementById('console-output');
                    var consoleTabs = document.getElementById('console-tabs');
                    if (!consoleOut) return;

                    var hasMultipleWf = result.workflows && result.workflows.length > 1 && result.mode === 'parallel';

                    if (hasMultipleWf) {
                        /* Show tab bar */
                        consoleTabs.style.display = 'flex';
                        var activeTab = typeof _wfActiveTab !== 'undefined' ? _wfActiveTab : 'all';
                        var tabHtml = '<div class="console-tab' + (activeTab === 'all' ? ' active' : '') + '" data-wf="all" onclick="switchWfTab(\'all\')">\u25a0 ' + I18n.t('console.all') + '</div>';
                        result.workflows.forEach(function (wf) {
                            var dotClass = 'tab-dot-idle';
                            if (result.running) dotClass = 'tab-dot-run';
                            else dotClass = 'tab-dot-done';
                            tabHtml += '<div class="console-tab' + (activeTab === wf.id ? ' active' : '') + '" data-wf="' + wf.id + '" onclick="switchWfTab(' + wf.id + ')">' +
                                '<span class="tab-dot ' + dotClass + '"></span>WF' + (wf.id + 1) + '</div>';
                        });
                        consoleTabs.innerHTML = tabHtml;

                        /* Render the active tab's logs */
                        if (activeTab === 'all') {
                            var newLogs = freshLines(result.logs, result.log_total, lastLogIdx);
                            var follow = newLogs.length > 0 && consoleWantsFollow(consoleOut);
                            newLogs.forEach(function (log) {
                                var line = document.createElement('div');
                                line.className = 'console-line';
                                line.textContent = log;
                                consoleOut.appendChild(line);
                            });
                            if (follow) {
                                consoleOut.scrollTop = consoleOut.scrollHeight;
                            }
                            lastLogIdx = result.log_total || result.logs.length;
                        } else {
                            var wfData = null;
                            result.workflows.forEach(function (w) { if (w.id === activeTab) wfData = w; });
                            if (wfData) {
                                if (typeof _wfLastIdx === 'undefined') _wfLastIdx = {};
                                if (_wfLastIdx[activeTab] === undefined) _wfLastIdx[activeTab] = 0;
                                var newWfLogs = freshLines(wfData.logs, wfData.total, _wfLastIdx[activeTab]);
                                var followWf = newWfLogs.length > 0 && consoleWantsFollow(consoleOut);
                                newWfLogs.forEach(function (log) {
                                    var line = document.createElement('div');
                                    line.className = 'console-line';
                                    line.textContent = log;
                                    consoleOut.appendChild(line);
                                });
                                if (followWf) {
                                    consoleOut.scrollTop = consoleOut.scrollHeight;
                                }
                                _wfLastIdx[activeTab] = wfData.total || wfData.logs.length;
                            }
                        }
                    } else {
                        /* Single workflow — original behavior */
                        consoleTabs.style.display = 'none';
                        consoleTabs.innerHTML = '';
                        var newLogs = freshLines(result.logs, result.log_total, lastLogIdx);
                        var followSingle = newLogs.length > 0 && consoleWantsFollow(consoleOut);
                        newLogs.forEach(function (log) {
                            var line = document.createElement('div');
                            line.className = 'console-line';
                            line.textContent = log;
                            consoleOut.appendChild(line);
                        });
                        if (followSingle) {
                            consoleOut.scrollTop = consoleOut.scrollHeight;
                        }
                        lastLogIdx = result.log_total || result.logs.length;
                    }

                    /* Status bar update */
                    if (!result.running) {
                        clearInterval(interval);
                        RunState.setRunning(false);
                        if (result.logs && result.logs.length) {
                            document.getElementById('status-text').textContent = I18n.t('status.completed');
                        }
                        document.getElementById('status-nodes').textContent = I18n.t('status.nodes') + Object.keys(canvas.nodes).length;
                        showToast(I18n.t('toast.workflowCompleted'));
                        I18n.apply();
                        stats.refresh();
                        /* Whatever left nodes unfinished is now worth offering
                           to continue — including a run someone stopped. */
                        if (window.resumeBar) resumeBar.refresh();
                        /* Auto-display charts for visualize nodes */
                        if (result.chart_results) {
                            var vizNodes = Object.keys(result.chart_results);
                            if (vizNodes.length === 1) {
                                renderChartPreview(result.chart_results[vizNodes[0]]);
                            } else if (vizNodes.length > 1) {
                                dashboard.open();
                            }
                        }
                    }
                }
            } catch (e) {
                /* The server went away mid-run: stop polling, but say so
                   instead of leaving a frozen "running" status bar. */
                clearInterval(interval);
                RunState.setRunning(false);
                showToast(I18n.t('toast.pollFailed'));
            }
        }, 1000);
    },
};

/* Settings Panel */
function openSettings(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) {
        /* Stale id (the node was deleted while the panel was open, or a redo
           dropped it): never leave an orphan panel on screen. */
        canvas.closeSettingsIfStale();
        return;
    }
    canvas._settingsNodeId = nodeId;
    var panel = document.getElementById('node-settings');
    var content = document.getElementById('settings-content');
    panel.classList.add('open');
    var html = '<div class="settings-group">' +
        '<label class="settings-label">' + I18n.t('settings.nodeType') + '</label>' +
        '<span style="font-size:12px;color:var(--text-dim);">' + I18n.t('nodeType.' + node.type) + '</span>' +
        '</div>';
    if (node.type === 'source') {
        var p = node.params;
        /* WeChat scrapes a list of article URLs, not a keyword — the panel has
           to change shape with the platform, which is why the select re-opens
           itself on change. */
        var isWechat = p.platform === 'wechat';
        html += '<div class="settings-group">' +
            '<label class="settings-label">' + I18n.t('settings.platform') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'platform\',this.value);openSettings(\'' + nodeId + '\')">' +
            '<option value="zhihu"' + (p.platform === 'zhihu' ? ' selected' : '') + '>' + I18n.t('platform.zhihu') + '</option>' +
            '<option value="weibo"' + (p.platform === 'weibo' ? ' selected' : '') + '>' + I18n.t('platform.weibo') + '</option>' +
            '<option value="xiaohongshu"' + (p.platform === 'xiaohongshu' ? ' selected' : '') + '>' + I18n.t('platform.xiaohongshu') + '</option>' +
            '<option value="wechat"' + (p.platform === 'wechat' ? ' selected' : '') + '>' + I18n.t('platform.wechat') + '</option>' +
            '</select></div>';
        if (isWechat) {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.urls') + '</label>' +
                '<textarea class="settings-input" rows="5" placeholder="https://mp.weixin.qq.com/s/..." ' +
                'onchange="updateParam(\'' + nodeId + '\',\'urls\',this.value)">' + escapeHtml(p.urls || '') + '</textarea>' +
                '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.urlsHint') + '</div></div>';
        } else {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.keyword') + '</label>' +
                '<input class="settings-input" value="' + escapeHtml(p.keyword || '') + '" placeholder="keyword" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'keyword\',this.value)"></div>' +
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.targetCount') + '</label>' +
                '<input class="settings-input" type="number" value="' + (p.target_count || 50) + '" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'target_count\',parseInt(this.value)||50)"></div>';
        }
        if (p.platform === 'weibo') {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.startTime') + '</label>' +
                '<input class="settings-input" value="' + (p.start_time || '') + '" placeholder="2026-01-01" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'start_time\',this.value)"></div>' +
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.endTime') + '</label>' +
                '<input class="settings-input" value="' + (p.end_time || '') + '" placeholder="2026-12-31" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'end_time\',this.value)"></div>';
        }
    } else if (node.type === 'upload') {
        /* The single place a file enters a workflow: pick a CSV / JSON / TXT
           and this node publishes its rows to whatever is connected below. */
        var p = node.params;
        html += '<div class="settings-group" style="display:flex;gap:8px;align-items:center;">' +
            '<button class="menu-btn" onclick="dataNodes.pickFile(\'' + nodeId + '\')">' + I18n.t('btn.uploadFile') + '</button>' +
            '<span style="font-size:11px;color:var(--text-dim);">' +
            (p.dataset_id ? I18n.t('dataSource.loaded') + ': ' + escapeHtml(p.dataset_name || p.dataset_id) : I18n.t('dataSource.none')) +
            '</span></div>';
        if (p.dataset_id && p.row_count) {
            html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
                p.row_count + ' ' + I18n.t('settings.rows') + '</div>';
        }
        if (p.dataset_id) {
            /* Worth saying out loud: this is the reason reopening the saved
               workflow does not ask for the file again. */
            html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('dataSource.persisted') + '</div>';
        }
        html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' +
            I18n.t('btn.previewData') + '</button></div>';
    } else if (node.type === 'process') {
        var p = node.params;
        var PROCESS_OPS = ['clean', 'emotion', 'tendency', 'keyword', 'cluster', 'ner', 'anomaly', 'correlation'];
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value);openSettings(\'' + nodeId + '\')">' +
            PROCESS_OPS.map(function (op) {
                return '<option value="' + op + '"' + (p.operation === op ? ' selected' : '') + '>' + I18n.t('op.' + op) + '</option>';
            }).join('') +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
            '<input class="settings-input" value="' + (p.text_column || '正文') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>';

        /* Clean operation */
        if (p.operation === 'clean') {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.topic') + '</label>' +
                '<input class="settings-input" value="' + (p.topic || '') + '" placeholder="e.g. topic" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'topic\',this.value)"></div>';
        }

        /* ML mode selector for emotion / tendency */
        if (p.operation === 'emotion' || p.operation === 'tendency') {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.mode') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'mode\',this.value)">' +
                '<option value="llm"' + (p.mode !== 'ml' ? ' selected' : '') + '>' + I18n.t('mode.llm') + '</option>' +
                '<option value="ml"' + (p.mode === 'ml' ? ' selected' : '') + '>' + I18n.t('mode.ml') + '</option>' +
                '</select></div>';
            if (p.mode === 'ml') {
                html += '<div class="settings-group"><button class="menu-btn" onclick="trainMLModel(\'' + nodeId + '\',\'' + p.operation + '\')">' + I18n.t('settings.trainModel') + '</button></div>';
            }
        }

        /* Keyword extraction */
        if (p.operation === 'keyword') {
            html += renderParamSelect(nodeId, p, 'method', 'settings.method', 'tfidf', [{ v: 'tfidf', l: 'TF-IDF' }, { v: 'textrank', l: 'TextRank' }]);
            html += renderParamInput(nodeId, p, 'topk', 'settings.topk', 'number', 10);
            html += renderParamCheckbox(nodeId, p, 'merge', 'settings.merge', true);
        }

        /* Text clustering */
        if (p.operation === 'cluster') {
            html += renderParamSelect(nodeId, p, 'cluster_method', 'settings.clusterMethod', 'kmeans',
                [{ v: 'kmeans', l: 'K-Means' }, { v: 'kmeans++', l: 'K-Means++' }, { v: 'dbscan', l: 'DBSCAN' }]);
            html += renderParamInput(nodeId, p, 'n_clusters', 'settings.nClusters', 'number', 3);
            html += renderParamInput(nodeId, p, 'eps', 'settings.eps', 'number', 0.5);
            html += renderParamInput(nodeId, p, 'min_samples', 'settings.minSamples', 'number', 2);
        }

        /* NER (regex only) */
        if (p.operation === 'ner') {
            /* NER uses regex-based entity extraction — no external model needed */
        }

        /* Anomaly detection */
        if (p.operation === 'anomaly') {
            html += renderParamInput(nodeId, p, 'columns', 'settings.columns', 'text', '');
            html += renderParamInput(nodeId, p, 'contamination', 'settings.contamination', 'number', 0.1);
        }

        /* Correlation analysis */
        if (p.operation === 'correlation') {
            html += renderParamInput(nodeId, p, 'columns', 'settings.columns', 'text', '');
            html += renderParamSelect(nodeId, p, 'corr_method', 'settings.corrMethod', 'pearson',
                [{ v: 'pearson', l: 'Pearson' }, { v: 'spearman', l: 'Spearman' }, { v: 'kendall', l: 'Kendall' }]);
            html += renderParamInput(nodeId, p, 'min_abs', 'settings.minAbs', 'number', 0.0);
        }

        html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    } else if (node.type === 'analysis') {
        html += renderAnalysisSettings(nodeId, node.params);
    } else if (node.type === 'visualize') {
        html += renderVisualizeSettings(nodeId, node.params);
    } else if (node.type === 'tokenize') {
        var p = node.params;
        // Force word_freq when a visualize node is downstream
        var hasDownstreamVisualize = canvas.connections.some(function (c) { return c.from === nodeId && canvas.nodes[c.to] && canvas.nodes[c.to].type === 'visualize'; });
        if (hasDownstreamVisualize && p.output_mode !== 'word_freq') {
            p.output_mode = 'word_freq';
            canvas.updateNodeDisplay(nodeId);
            canvas.saveState();
        }
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
            '<input class="settings-input" value="' + (p.text_column || '') + '" placeholder="' + I18n.t('settings.textColumnPlaceholder') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.outputMode') + '</label>' +
            (hasDownstreamVisualize ? '<div style="font-size:12px;color:var(--accent);padding:4px 0;">' + I18n.t('settings.tokenizeOutputLocked') + '</div>' :
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'output_mode\',this.value)">' +
                ['word_freq', 'words_only', 'csv_line'].map(function (m) {
                    return '<option value="' + m + '"' + ((p.output_mode || 'word_freq') === m ? ' selected' : '') + '>' + I18n.t('outputMode.' + m) + '</option>';
                }).join('') +
                '</select>') + '</div>' +
            ((p.output_mode || 'word_freq') === 'word_freq' ?
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.topN') + '</label>' +
                '<input class="settings-input" type="number" value="' + (p.top_n || '') + '" placeholder="' + I18n.t('settings.topNPlaceholder') + '" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'top_n\',this.value)"></div>' : '') +
            '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    } else if (node.type === 'name') {
        /* The workflow's label for the Execution History panel. It is the one
           node that must sit at the head of a workflow and wire into what
           follows, so the panel says so and validates the same way. */
        var p = node.params;
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('name.hint') + '</div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.workflowName') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.workflow_name || '') + '" placeholder="' + I18n.t('name.unnamed') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'workflow_name\',this.value)"></div>';
    } else if (node.type === 'resume') {
        /* Adopts rows a previous run already paid for. Both lists live on the
           server, so the panel fills them asynchronously below. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('resume.hint') + '</div>' +
            '<div id="resume-pick" data-node="' + nodeId + '">' +
            '<span style="font-size:11px;color:var(--text-dim);">…</span></div>' +
            '<div class="settings-group"><button class="menu-btn" onclick="renderResumeSettings(\'' + nodeId + '\')">' +
            I18n.t('resume.refresh') + '</button></div>';
    } else if (node.type === 'output') {
        var p = node.params;
        var fmt = p.format || (p.operation === 'save_csv' ? 'csv' : 'csv');
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.format') + '</label>' +
            '<select class="settings-select" onchange="onOutputFormatChange(\'' + nodeId + '\',this.value)">' +
            ['csv', 'json', 'excel', 'txt', 'html', 'markdown'].map(function (f) {
                return '<option value="' + f + '"' + (fmt === f ? ' selected' : '') + '>' + I18n.t('format.' + f) + '</option>';
            }).join('') +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.filename') + '</label>' +
            '<input class="settings-input" value="' + (p.filename || 'export.csv') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'filename\',this.value)"></div>';
        if (fmt === 'txt') {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
                '<input class="settings-input" value="' + (p.text_column || '') + '" placeholder="optional: one column per line" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>';
        }
        html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    }
    content.innerHTML = html;
    if (node.type === 'resume') renderResumeSettings(nodeId);
    canvas.updateSettingsButton();
}

/* ── Resume node: pick a stored run and one of its node outputs ── */
async function renderResumeSettings(nodeId) {
    var node = canvas.nodes[nodeId];
    var holder = document.getElementById('resume-pick');
    /* The panel may have moved on to another node while this request was in
       flight; writing then would overwrite that node's settings. */
    if (!node || !holder || holder.dataset.node !== nodeId) return;
    var p = node.params;
    var runs = [];
    try {
        var resp = await fetch('/api/runs/resumable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow: canvas.toWorkflowJSON() }),
        });
        var result = await resp.json();
        runs = (result.ok && result.runs) || [];
    } catch (e) {
        runs = [];
    }
    if (!runs.length) {
        holder.innerHTML = '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('resume.none') + '</div>';
        return;
    }
    /* Whatever it was pointed at may have been purged since; falling back to
       the newest keeps the node usable instead of silently reading nothing. */
    if (!runs.some(function (r) { return r.run_id === p.resume_run_id; })) {
        p.resume_run_id = runs[0].run_id;
        canvas.saveState();
    }
    var run = runs.filter(function (r) { return r.run_id === p.resume_run_id; })[0] || runs[0];
    var nodes = (run.nodes || []).filter(function (n) { return (n.row_count || 0) > 0; });
    if (!nodes.some(function (n) { return n.node_id === p.resume_node_id; })) {
        p.resume_node_id = '';
    }
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.runSelect') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'resume_run_id\',this.value);renderResumeSettings(\'' + nodeId + '\')">' +
        runs.map(function (r) {
            var label = (r.started_at || r.run_id) + ' · ' + (r.rows_kept || 0) + ' ' + I18n.t('settings.rows');
            return '<option value="' + r.run_id + '"' + (r.run_id === p.resume_run_id ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('') +
        '</select></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.nodeSelect') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'resume_node_id\',this.value);canvas.updateNodeDisplay(\'' + nodeId + '\')">' +
        '<option value=""' + (!p.resume_node_id ? ' selected' : '') + '>' + I18n.t('resume.autoNode') + '</option>' +
        nodes.map(function (n) {
            var label = (n.title || n.node_id) + ' · ' + n.row_count + ' ' + I18n.t('settings.rows');
            return '<option value="' + n.node_id + '"' + (n.node_id === p.resume_node_id ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('') +
        '</select></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.limit') + '</label>' +
        '<input class="settings-input" type="number" value="' + (p.resume_limit || 0) + '" placeholder="' + I18n.t('resume.limitPlaceholder') + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'resume_limit\',parseInt(this.value)||0)"></div>';
    holder.innerHTML = html;
    canvas.updateNodeDisplay(nodeId);
}

/* Format -> file-extension map for the Save node. Keeps the filename's
   extension in sync whenever the user picks a different export format,
   instead of leaving a stale ".csv" on a JSON/Excel/... export. */
var FORMAT_EXTENSIONS = { csv: '.csv', json: '.json', excel: '.xlsx', txt: '.txt', html: '.html', markdown: '.md' };

function onOutputFormatChange(nodeId, fmt) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var filename = node.params.filename || 'export.csv';
    var dot = filename.lastIndexOf('.');
    var base = dot > 0 ? filename.slice(0, dot) : filename;
    node.params.operation = 'save';
    node.params.format = fmt;
    node.params.filename = base + (FORMAT_EXTENSIONS[fmt] || '.csv');
    canvas.updateNodeDisplay(nodeId);
    canvas.saveState();
    openSettings(nodeId);
}

/* ── Shared settings UI helpers ── */
function renderParamInput(nodeId, p, key, labelKey, type, defVal) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t(labelKey) + '</label>' +
        '<input class="settings-input" type="' + type + '" value="' + (p[key] !== undefined ? p[key] : defVal) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.value)"></div>';
}
function renderParamSelect(nodeId, p, key, labelKey, defVal, options) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t(labelKey) + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.value)">';
    options.forEach(function (o) {
        var sel = (p[key] || defVal) === o.v ? ' selected' : '';
        html += '<option value="' + o.v + '"' + sel + '>' + (o.l || o.v) + '</option>';
    });
    html += '</select></div>';
    return html;
}
function renderParamCheckbox(nodeId, p, key, labelKey, defVal) {
    var checked = p[key] !== undefined ? (p[key] === true || p[key] === 'true') : !!defVal;
    return '<div class="settings-group"><label class="settings-label">' +
        '<input type="checkbox" ' + (checked ? 'checked' : '') + ' ' +
        'onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.checked ? \'true\' : \'false\')"> ' +
        I18n.t(labelKey) + '</label></div>';
}

/* ── Analysis node settings ── */
var ANALYSIS_OPS = ['drop_null', 'fill_null', 'drop_duplicates', 'filter_rows', 'select_columns', 'rename_columns', 'strip_whitespace', 'convert_type', 'sort_rows', 'sample_rows', 'groupby_agg', 'join_tables', 'column_calc', 'bin_column'];
var FILTER_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'in', 'not_in', 'is_null', 'not_null'];
var CONVERT_TYPES = ['str', 'int', 'float', 'bool', 'datetime'];

function renderAnalysisSettings(nodeId, p) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value)">' +
        ANALYSIS_OPS.map(function (op) {
            return '<option value="' + op + '"' + (p.operation === op ? ' selected' : '') + '>' + I18n.t('op.' + op) + '</option>';
        }).join('') +
        '</select></div>';

    var op = p.operation || 'drop_null';
    if (['drop_null', 'fill_null', 'drop_duplicates', 'select_columns', 'strip_whitespace'].indexOf(op) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.columns') + '</label>' +
            '<input class="settings-input" value="' + (p.columns || '') + '" placeholder="col1, col2 (empty = all)" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'columns\',this.value)"></div>';
    }
    if (op === 'fill_null') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + (p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
    }
    if (op === 'filter_rows') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + (p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.filterOp') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'op\',this.value)">' +
            FILTER_OPS.map(function (o) { return '<option value="' + o + '"' + (p.op === o ? ' selected' : '') + '>' + o + '</option>'; }).join('') +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + (p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
    }
    if (op === 'rename_columns') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.renameFrom') + '</label>' +
            '<input class="settings-input" value="' + (p.rename_from || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'rename_from\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.renameTo') + '</label>' +
            '<input class="settings-input" value="' + (p.rename_to || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'rename_to\',this.value)"></div>';
    }
    if (op === 'convert_type') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + (p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.dtype') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'dtype\',this.value)">' +
            CONVERT_TYPES.map(function (t) { return '<option value="' + t + '"' + (p.dtype === t ? ' selected' : '') + '>' + t + '</option>'; }).join('') +
            '</select></div>';
    }
    if (op === 'sort_rows') {
        html += renderParamInput(nodeId, p, 'column', 'settings.column', 'text', '');
        html += renderParamCheckbox(nodeId, p, 'ascending', 'settings.ascending', true);
    }
    if (op === 'sample_rows') {
        html += renderParamInput(nodeId, p, 'n', 'settings.n', 'number', '');
        html += renderParamInput(nodeId, p, 'frac', 'settings.frac', 'number', '');
        html += renderParamInput(nodeId, p, 'seed', 'settings.seed', 'number', '');
    }
    if (op === 'groupby_agg') {
        html += renderParamInput(nodeId, p, 'group_col', 'settings.groupCol', 'text', '');
        html += renderParamInput(nodeId, p, 'agg_col', 'settings.aggCol', 'text', '');
        html += renderParamSelect(nodeId, p, 'agg_func', 'settings.aggFunc', 'sum',
            [{ v: 'sum', l: 'Sum' }, { v: 'mean', l: 'Mean' }, { v: 'count', l: 'Count' }, { v: 'max', l: 'Max' }, { v: 'min', l: 'Min' }]);
    }
    if (op === 'join_tables') {
        /* The right table is the node's second incoming connection — the old
           "dataset id" box asked for an id the user had no way to obtain. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.joinHint') + '</div>';
        html += renderParamSelect(nodeId, p, 'join_how', 'settings.joinHow', 'left',
            [{ v: 'left', l: 'Left' }, { v: 'right', l: 'Right' }, { v: 'inner', l: 'Inner' }, { v: 'outer', l: 'Outer' }]);
        html += renderParamInput(nodeId, p, 'left_on', 'settings.leftOn', 'text', '');
        html += renderParamInput(nodeId, p, 'right_on', 'settings.rightOn', 'text', '');
    }
    if (op === 'column_calc') {
        html += renderParamInput(nodeId, p, 'new_col', 'settings.newCol', 'text', '');
        html += renderParamInput(nodeId, p, 'expr', 'settings.expr', 'text', '');
    }
    if (op === 'bin_column') {
        html += renderParamInput(nodeId, p, 'column', 'settings.column', 'text', '');
        html += renderParamInput(nodeId, p, 'bin_new_col', 'settings.binNewCol', 'text', '');
    }
    html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    return html;
}

/* ── Visualize node settings ── */
var CHART_TYPES = ['bar', 'line', 'pie', 'scatter', 'histogram', 'box', 'heatmap', 'sankey', 'wordcloud', 'map'];

/* Field labels change meaning per chart type (e.g. x/y are two category
   dimensions for heatmap/sankey, not "category + value" like bar/line). */
var CHART_X_LABEL_KEY = {
    heatmap: 'settings.xFieldCat1', sankey: 'settings.sourceField',
    wordcloud: 'settings.textField', map: 'settings.regionField',
};
var CHART_Y_LABEL_KEY = { heatmap: 'settings.yFieldCat2', sankey: 'settings.targetField' };
var CHARTS_WITH_Y_AS_CATEGORY = ['heatmap', 'sankey'];
var CHARTS_WITH_VALUE_FIELD = ['heatmap', 'sankey', 'wordcloud', 'map'];
var CHARTS_NO_Y = ['histogram', 'wordcloud', 'map'].concat(CHARTS_WITH_Y_AS_CATEGORY);

function renderVisualizeSettings(nodeId, p) {
    var upstream = canvas.getUpstreamNodeId(nodeId);
    var upstreamNode = upstream ? canvas.nodes[upstream] : null;
    var isTokenizeUpstream = upstreamNode && upstreamNode.type === 'tokenize';

    // Simplified settings when connected to a tokenize node
    if (isTokenizeUpstream) {
        var changed = false;
        if (!p.x_field) { p.x_field = 'word'; changed = true; }
        if (!p.y_field) { p.y_field = 'frequency'; changed = true; }
        if (!p.value_field) { p.value_field = 'frequency'; changed = true; }
        if (changed) { canvas.updateNodeDisplay(nodeId); canvas.saveState(); }

        var ct = p.chart_type || 'bar';
        var TOKENIZE_CHART_TYPES = ['bar', 'pie', 'wordcloud'];

        // Wordcloud only supports ECharts engine
        var isWordcloud = ct === 'wordcloud';
        if (isWordcloud && p.engine !== 'echarts') {
            p.engine = 'echarts';
            canvas.updateNodeDisplay(nodeId);
            canvas.saveState();
        }

        var html = '<div class="settings-group" style="margin-bottom:6px;">' +
            '<span style="font-size:11px;color:var(--accent);">' + I18n.t('settings.tokenizeUpstream') + '</span></div>' +
            (isWordcloud ? '' :
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'engine\',this.value)">' +
                '<option value="echarts"' + (p.engine !== 'matplotlib' ? ' selected' : '') + '>ECharts</option>' +
                '<option value="matplotlib"' + (p.engine === 'matplotlib' ? ' selected' : '') + '>Matplotlib</option>' +
                '</select></div>') +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'chart_type\',this.value)">' +
            TOKENIZE_CHART_TYPES.map(function (c) { return '<option value="' + c + '"' + (ct === c ? ' selected' : '') + '>' + I18n.t('chart.' + c) + '</option>'; }).join('') +
            '</select></div>';
        if (isWordcloud) {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.wordcloudStyle') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'wordcloud_style\',this.value)">' +
                ['vibrant', 'monoBlue', 'monoOrange', 'pastel', 'ocean', 'sunset', 'forest']
                    .map(function (s) { return '<option value="' + s + '"' + ((p.wordcloud_style || 'vibrant') === s ? ' selected' : '') + '>' + I18n.t('wordcloudStyle.' + s) + '</option>'; }).join('') +
                '</select></div>';
        }
        html += '<div class="settings-group" style="display:flex;gap:8px;">' +
            '<button class="menu-btn toggle-on" onclick="dataNodes.previewVisualize(\'' + nodeId + '\')">' + I18n.t('btn.preview') + '</button>' +
            '<button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button>' +
            '</div>';
        return html;
    }

    var ct = p.chart_type || 'bar';
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'chart_type\',this.value)">' +
        CHART_TYPES.map(function (c) { return '<option value="' + c + '"' + (ct === c ? ' selected' : '') + '>' + I18n.t('chart.' + c) + '</option>'; }).join('') +
        '</select></div>' +
        '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'engine\',this.value)">' +
        '<option value="echarts"' + (p.engine !== 'matplotlib' ? ' selected' : '') + '>ECharts</option>' +
        '<option value="matplotlib"' + (p.engine === 'matplotlib' ? ' selected' : '') + '>Matplotlib</option>' +
        '</select></div>';
    if (p.engine === 'matplotlib' && ['heatmap'].indexOf(ct) < 0 && ['wordcloud', 'sankey', 'map'].indexOf(ct) >= 0) {
        html += '<div class="settings-group" style="color:#e67e22;font-size:11px;">' + I18n.t('warn.echartsOnly') + '</div>';
    }
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t(CHART_X_LABEL_KEY[ct] || 'settings.xField') + '</label>' +
        '<input class="settings-input" value="' + (p.x_field || '') + '" placeholder="category / numeric column" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'x_field\',this.value)"></div>';
    if (CHARTS_WITH_Y_AS_CATEGORY.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t(CHART_Y_LABEL_KEY[ct]) + '</label>' +
            '<input class="settings-input" value="' + (p.y_field || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y_field\',this.value)"></div>';
    } else if (CHARTS_NO_Y.indexOf(ct) < 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.yField') + '</label>' +
            '<input class="settings-input" value="' + (p.y_field || '') + '" placeholder="optional: value column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>';
    }
    if (CHARTS_WITH_VALUE_FIELD.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.valueField') + '</label>' +
            '<input class="settings-input" value="' + (p.value_field || '') + '" placeholder="optional: weight column (default = count)" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>';
    }
    if (ct === 'wordcloud') {
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (p.tokenize ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'tokenize\',this.checked)"> ' +
            I18n.t('settings.tokenize') + '</label></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.wordcloudStyle') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'wordcloud_style\',this.value)">' +
            ['vibrant', 'monoBlue', 'monoOrange', 'pastel', 'ocean', 'sunset', 'forest']
                .map(function (s) { return '<option value="' + s + '"' + ((p.wordcloud_style || 'vibrant') === s ? ' selected' : '') + '>' + I18n.t('wordcloudStyle.' + s) + '</option>'; }).join('') +
            '</select></div>';
    }
    if (ct === 'map') {
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.mapRegionNames') + '</div>';
    }
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.title') + '</label>' +
        '<input class="settings-input" value="' + (p.title || '') + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'title\',this.value)"></div>';
    html += '<div class="settings-group" style="display:flex;gap:8px;flex-wrap:wrap;">' +
        '<button class="menu-btn toggle-on" onclick="dataNodes.previewVisualize(\'' + nodeId + '\')">' + I18n.t('btn.preview') + '</button>' +
        '<button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button>' +
        '<button class="menu-btn" onclick="chartStudio.openForNode(\'' + nodeId + '\')">' + I18n.t('btn.studio') + '</button>' +
        '</div>';
    return html;
}

/* ── Data helpers for the Upload node: pick a file / preview it ──
   The Upload node is the single entry point for files, so a workflow can
   start from an uploaded CSV/JSON/TXT instead of a crawl. Downstream
   nodes just see rows, whoever produced them. */
var dataNodes = {
    _pendingNodeId: null,

    pickFile(nodeId) {
        this._pendingNodeId = nodeId;
        document.getElementById('dataset-file-input').click();
    },

    async handleFileSelected(evt) {
        var file = evt.target.files[0];
        var nodeId = this._pendingNodeId;
        evt.target.value = '';
        if (!file || !nodeId) return;
        var form = new FormData();
        form.append('file', file);
        try {
            var resp = await fetch('/api/data/upload', { method: 'POST', body: form });
            var result = await resp.json();
            if (result.ok) {
                var node = canvas.nodes[nodeId];
                if (node) {
                    node.params.dataset_id = result.dataset_id;
                    node.params.dataset_name = result.name || '';
                    node.params.row_count = result.row_count || 0;
                    /* A .txt arrives as one row in a 'content' column — worth
                       saying out loud, since word clouds read that column. */
                    showToast(result.is_txt
                        ? I18n.t('toast.txtUploaded') + ' (' + result.row_count + ' rows)'
                        : I18n.t('toast.datasetUploaded') + ' (' + result.row_count + ' rows)');
                    canvas.updateNodeDisplay(nodeId);
                    canvas.saveState();
                }
                if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
            } else {
                showToast(I18n.t('toast.uploadFailed') + ': ' + result.error);
            }
        } catch (e) {
            showToast(I18n.t('toast.uploadFailed') + ': ' + e.message);
        }
    },

    /* Keep every Upload node in touch with the file it points at.

       Uploaded files are stored in a database on the server, so a node's
       dataset_id is a pointer that outlives the page: a refresh, a restart or
       reopening the saved workflow should leave the file attached. Instead of
       throwing those ids away on every load, re-check them — the file is used
       when it is still there, and only nodes whose file really is gone fall
       back to asking for it again. */
    async reconcileDatasets() {
        var pending = Object.keys(canvas.nodes).filter(function (id) {
            var n = canvas.nodes[id];
            return n && n.type === 'upload' && n.params && n.params.dataset_id;
        });
        if (!pending.length) return;
        var known = {};
        try {
            var resp = await fetch('/api/data/datasets?limit=1000');
            var result = await resp.json();
            (result.datasets || []).forEach(function (d) { known[d.dataset_id] = d; });
        } catch (e) {
            /* Offline or a dead server: keep the ids. Losing them would mean
               re-uploading a file that is very likely still on disk. */
            return;
        }
        var missing = [];
        pending.forEach(function (id) {
            var node = canvas.nodes[id];
            if (!node) return;
            var meta = known[node.params.dataset_id];
            if (!meta) {
                node.params.dataset_id = '';
                node.params.dataset_name = '';
                node.params.row_count = '';
                missing.push(node.title || id);
            } else {
                node.params.dataset_name = meta.name || node.params.dataset_name || '';
                node.params.row_count = meta.row_count || 0;
            }
            canvas.updateNodeDisplay(id);
            if (canvas._settingsNodeId === id) openSettings(id);
        });
        canvas.saveState();
        if (missing.length) showToast(I18n.t('toast.datasetsMissing') + ': ' + missing.join(', '));
    },

    async previewVisualize(nodeId) {
        var node = canvas.nodes[nodeId];
        if (!node) return;
        var p = node.params;
        var payload = {
            chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
            y_field: p.y_field, value_field: p.value_field, agg: p.agg, title: p.title,
            tokenize: !!p.tokenize,
            wordcloud_style: p.wordcloud_style || 'vibrant',
        };
        /* A chart always renders whatever its upstream produced — a crawl or
           an Upload node's file, it makes no difference here. */
        var upstream = canvas.getUpstreamNodeId(nodeId);
        if (!upstream) {
            showToast(I18n.t('toast.previewNeedsInput'));
            return;
        }
        payload.node_id = upstream;
        /* Show panel with loading spinner immediately */
        var panel = document.getElementById('chart-preview-panel');
        panel.classList.add('open');
        var echartsDiv = document.getElementById('chart-preview-echarts');
        if (_chartPreviewInstance) {
            _chartPreviewInstance.dispose();
            _chartPreviewInstance = null;
        }
        echartsDiv.innerHTML = '<div class="loading-container"><div class="loading-spinner"></div></div>';
        echartsDiv.style.display = 'block';
        document.getElementById('chart-preview-image').style.display = 'none';
        try {
            var resp = await fetch('/api/visualize/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            if (result.ok) {
                renderChartPreview(result);
            } else {
                showToast(I18n.t('toast.renderFailed') + ': ' + result.error);
                echartsDiv.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:12px;">' + escapeHtml(result.error) + '</div>';
            }
        } catch (e) {
            showToast(I18n.t('toast.renderFailed') + ': ' + e.message);
            echartsDiv.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:12px;">' + escapeHtml(e.message) + '</div>';
        }
    },

    /* Preview the raw tabular data produced by a node:
        - source / process / analysis nodes → show their own result (post-transform)
        - output / visualize nodes → show whatever their upstream connection
          last produced (pass-through / consume-only nodes).
       Requires the workflow to have been executed at least once so
       execution_state has a result for the requested node. */
    async previewData(nodeId) {
        var node = canvas.nodes[nodeId];
        if (!node) return;
        var payload = {};
        if (node.type === 'upload') {
            /* Its own file, no execution needed. */
            if (!node.params.dataset_id) {
                showToast(I18n.t('toast.previewNeedsUpload'));
                return;
            }
            payload.dataset_id = node.params.dataset_id;
        } else if (['source', 'process', 'analysis', 'tokenize'].indexOf(node.type) >= 0) {
            payload.node_id = nodeId;
        } else {
            var upstream = canvas.getUpstreamNodeId(nodeId);
            if (!upstream) {
                showToast(I18n.t('toast.previewNeedsInput'));
                return;
            }
            payload.node_id = upstream;
            // Pass output format so preview matches saved file format.
            if (node.type === 'output' && node.params.format) {
                payload.preview_format = node.params.format;
            }
        }
        await dataPreview.open(payload);
    },
};

/* ── Train ML model from upstream node data ── */
async function trainMLModel(nodeId, modelType) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var payload = {};
    /* Training data comes from upstream, like every other data-consuming
       node: a file reaches here through an Upload node, not from a dataset
       stored on this node. */
    var upstream = canvas.getUpstreamNodeId(nodeId);
    if (!upstream) {
        showToast(I18n.t('toast.mlUpstreamNeeded'));
        return;
    }
    payload.node_id = upstream;
    payload.model_type = modelType;
    payload.text_column = node.params.text_column || '正文';
    payload.label_column = modelType === 'emotion' ? 'emotion' : 'tendency';
    try {
        var resp = await fetch('/api/analysis/train', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        var result = await resp.json();
        if (result.ok) {
            showToast(I18n.t('toast.modelTrained') + ' (' + result.trained_on + ' rows, ' + result.label_count + ' labels)');
        } else {
            showToast(I18n.t('toast.modelTrainFailed') + ': ' + result.error);
        }
    } catch (e) {
        showToast(I18n.t('toast.modelTrainFailed') + ': ' + e.message);
    }
}

/* Some chart types need extra client-side setup before echarts can render
   them: the wordcloud series type needs the echarts-wordcloud extension
   script (loaded in index.html), and the map series type needs a GeoJSON
   registered via echarts.registerMap() first. This wraps setOption so
   every render path (chart preview, dashboard) gets that for free. */
var _mapRegistryPromises = {};
function ensureMapRegistered(mapName) {
    if (_mapRegistryPromises[mapName]) return _mapRegistryPromises[mapName];
    var urls = { china: 'https://geo.datav.aliyun.com/areas_v3/bound/100000_full.json' };
    var url = urls[mapName];
    if (!url) return Promise.resolve(false);
    _mapRegistryPromises[mapName] = fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (geoJson) { echarts.registerMap(mapName, geoJson); return true; })
        .catch(function () { showToast(I18n.t('toast.mapLoadFailed')); return false; });
    return _mapRegistryPromises[mapName];
}

function patchOptionForTheme(option) {
    /* Always applied: the design system is light-only. */
    function pick(val) {
        if (typeof val === 'string' && val.length) return val;
    }
    /* Title */
    if (option.title && option.title.textStyle) option.title.textStyle.color = '#111';
    /* Tooltip */
    if (option.tooltip) {
        option.tooltip.backgroundColor = 'rgba(248,248,248,0.95)';
        option.tooltip.borderColor = '#ddd';
        if (option.tooltip.textStyle) option.tooltip.textStyle.color = '#222';
    }
    /* Legend */
    if (option.legend && option.legend.textStyle) option.legend.textStyle.color = '#222';
    /* Axes */
    [].concat(option.xAxis || []).concat(option.yAxis || []).forEach(function (ax) {
        if (!ax) return;
        if (ax.axisLabel) ax.axisLabel.color = '#444';
        if (ax.nameTextStyle) ax.nameTextStyle.color = '#222';
        if (ax.axisLine && ax.axisLine.lineStyle) ax.axisLine.lineStyle.color = '#ccc';
        if (ax.axisTick && ax.axisTick.lineStyle) ax.axisTick.lineStyle.color = '#ccc';
        if (ax.splitLine && ax.splitLine.lineStyle) ax.splitLine.lineStyle.color = '#e8e8e8';
    });
    /* Series labels */
    (option.series || []).forEach(function (s) {
        if (!s) return;
        if (s.label) s.label.color = '#222';
        if (s.labelLine && s.labelLine.lineStyle) s.labelLine.lineStyle.color = '#bbb';
        if (s.type === 'wordCloud' && s.textStyle) s.textStyle.color = '#222';
    });
    /* VisualMap */
    if (option.visualMap && option.visualMap.textStyle) option.visualMap.textStyle.color = '#444';
}

function applyEchartsOption(instance, option) {
    patchOptionForTheme(option);
    var mapSeries = (option.series || []).find(function (s) { return s.type === 'map'; });
    if (mapSeries) {
        ensureMapRegistered(mapSeries.map || 'china').then(function () {
            instance.setOption(option, true);
            instance.resize();
        });
    } else {
        instance.setOption(option, true);
        instance.resize();
    }
}

var _chartPreviewInstance = null;
var _chartPreviewResizeHandler = null;
function renderChartPreview(result) {
    var panel = document.getElementById('chart-preview-panel');
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, {
            minW: 300,
            minH: 200,
            maxW: window.innerWidth - 40,
            maxH: window.innerHeight - 40,
            onResize: function () { if (_chartPreviewInstance) _chartPreviewInstance.resize(); }
        });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var echartsDiv = document.getElementById('chart-preview-echarts');
    var imgEl = document.getElementById('chart-preview-image');
    if (result.engine === 'matplotlib') {
        echartsDiv.style.display = 'none';
        echartsDiv.innerHTML = '';
        imgEl.style.display = 'block';
        imgEl.src = result.image;
    } else {
        imgEl.style.display = 'none';
        echartsDiv.style.display = 'block';
        if (!_chartPreviewInstance) {
            echartsDiv.innerHTML = '';
            _chartPreviewInstance = echarts.init(echartsDiv);
            if (!_chartPreviewResizeHandler) {
                _chartPreviewResizeHandler = function () { _chartPreviewInstance.resize(); };
                window.addEventListener('resize', _chartPreviewResizeHandler);
            }
        }
        applyEchartsOption(_chartPreviewInstance, result.option);
    }
}

function toggleChartPreview() {
    var panel = document.getElementById('chart-preview-panel');
    panel.classList.remove('open');
    if (_chartPreviewInstance) {
        _chartPreviewInstance.dispose();
        _chartPreviewInstance = null;
    }
}

/* ── Data Preview: generic paginated table for any dataset ──
   Used by Analysis/Visualize/Output node settings ("Preview Data"
   button) to inspect real rows instead of only JSON or a chart. */
function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

var dataPreview = {
    _payload: null,
    _offset: 0,
    _limit: 50,
    _total: 0,

    async open(payload) {
        this._payload = payload;
        this._offset = 0;
        var fmt = payload.preview_format || '';
        if (fmt === 'txt' || fmt === 'json') {
            this._limit = 5000; // fetch enough for a full text view
        } else {
            this._limit = 50;
        }
        var panel = document.getElementById('data-preview-panel');
        panel.classList.add('open');
        document.getElementById('data-preview-meta').textContent = '';
        document.getElementById('data-preview-table-wrap').innerHTML =
            '<div class="loading-container"><div class="loading-spinner"></div></div>';
        document.getElementById('data-preview-pager').style.display = '';
        document.getElementById('data-preview-page-label').textContent = '';
        await this._fetch();
    },

    async _fetch() {
        var body = Object.assign({}, this._payload, { limit: this._limit, offset: this._offset });
        try {
            var resp = await fetch('/api/data/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            var result = await resp.json();
            if (!result.ok) {
                showToast(I18n.t('toast.previewFailed') + ': ' + result.error);
                return;
            }
            this._total = result.total_rows;
            var fmt = this._payload.preview_format || '';
            if (fmt === 'txt' || fmt === 'json') {
                renderDataPreviewText(result, fmt);
            } else {
                renderDataPreviewTable(result);
            }
        } catch (e) {
            showToast(I18n.t('toast.previewFailed') + ': ' + e.message);
        }
    },

    prevPage() {
        if (this._offset - this._limit >= 0) { this._offset -= this._limit; this._fetch(); }
    },
    nextPage() {
        if (this._offset + this._limit < this._total) { this._offset += this._limit; this._fetch(); }
    },
};

function renderDataPreviewTable(result) {
    var panel = document.getElementById('data-preview-panel');
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, { minW: 320, minH: 220, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var meta = document.getElementById('data-preview-meta');
    meta.textContent = I18n.t('dataPreview.rows') + ': ' + result.total_rows + '  |  ' + I18n.t('dataPreview.columns') + ': ' + result.columns.length;

    var wrap = document.getElementById('data-preview-table-wrap');
    var html = '<table class="data-preview-table"><thead><tr>' +
        result.columns.map(function (c) { return '<th>' + escapeHtml(c) + '</th>'; }).join('') +
        '</tr></thead><tbody>';
    result.rows.forEach(function (row) {
        html += '<tr>' + result.columns.map(function (c) {
            var v = row[c];
            return '<td>' + escapeHtml(v === null || v === undefined ? '' : v) + '</td>';
        }).join('') + '</tr>';
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;

    var page = Math.floor(result.offset / result.limit) + 1;
    var pages = Math.max(1, Math.ceil(result.total_rows / result.limit));
    document.getElementById('data-preview-page-label').textContent = page + ' / ' + pages;
}

function renderDataPreviewText(result, format) {
    var panel = document.getElementById('data-preview-panel');
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, { minW: 320, minH: 220, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var meta = document.getElementById('data-preview-meta');
    meta.textContent = I18n.t('dataPreview.rows') + ': ' + result.total_rows;

    var text;
    if (format === 'json') {
        text = JSON.stringify(result.rows, null, 2);
    } else {
        // txt: one line per row, columns separated by space
        text = result.rows.map(function (row) {
            return result.columns.map(function (c) { return row[c]; }).join('\t');
        }).join('\n');
    }

    var wrap = document.getElementById('data-preview-table-wrap');
    wrap.innerHTML = '<pre class="data-preview-text">' + escapeHtml(text) + '</pre>';

    document.getElementById('data-preview-pager').style.display = 'none';
}

function toggleDataPreview() {
    document.getElementById('data-preview-panel').classList.remove('open');
}

/* ── Dashboard: grid view of every Visualize node's chart at once ──
   Purely a *view* over existing Visualize nodes already configured on
   the canvas — it doesn't introduce a new workflow/DAG node type, it
   just renders each one's current settings side by side, like a simple
   BI board. Requires the workflow to have been executed at least once
   (so there's an upstream result to render). */
var dashboard = {
    _instances: {},

    async open() {
        var panel = document.getElementById('dashboard-panel');
        panel.classList.add('open');
        var grid = document.getElementById('dashboard-grid');
        grid.innerHTML = '';
        this._instances = {};

        var vizNodeIds = Object.keys(canvas.nodes).filter(function (id) {
            return canvas.nodes[id].type === 'visualize';
        });

        if (!vizNodeIds.length) {
            grid.innerHTML = '<div class="dashboard-empty">' + I18n.t('dashboard.empty') + '</div>';
            return;
        }

        var self = this;
        vizNodeIds.forEach(function (id) {
            var node = canvas.nodes[id];
            var cell = document.createElement('div');
            cell.className = 'dashboard-cell';
            cell.innerHTML =
                '<div class="dashboard-cell-title">' + escapeHtml(node.title || id) + '</div>' +
                '<div class="dashboard-cell-body" id="dash-cell-' + id + '"></div>';
            grid.appendChild(cell);
            self._renderCell(id, node);
        });
    },

    async _renderCell(nodeId, node) {
        var body = document.getElementById('dash-cell-' + nodeId);
        if (!body) return;
        var p = node.params;
        var payload = {
            chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
            y_field: p.y_field, value_field: p.value_field, agg: p.agg,
            title: p.title, tokenize: !!p.tokenize,
            wordcloud_style: p.wordcloud_style || 'vibrant',
        };
        var upstream = canvas.getUpstreamNodeId(nodeId);
        if (!upstream) {
            body.innerHTML = '<div class="dashboard-cell-error">' + I18n.t('dashboard.noData') + '</div>';
            return;
        }
        payload.node_id = upstream;

        try {
            var resp = await fetch('/api/visualize/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            if (!result.ok) {
                body.innerHTML = '<div class="dashboard-cell-error">' + escapeHtml(result.error) + '</div>';
                return;
            }
            if (result.engine === 'matplotlib') {
                body.innerHTML = '<img src="' + result.image + '" />';
            } else {
                var inst = echarts.init(body);
                this._instances[nodeId] = inst;
                applyEchartsOption(inst, result.option);
            }
        } catch (e) {
            body.innerHTML = '<div class="dashboard-cell-error">' + escapeHtml(e.message) + '</div>';
        }
    },

    close() {
        document.getElementById('dashboard-panel').classList.remove('open');
    },
};

window.addEventListener('resize', function () {
    Object.keys(dashboard._instances).forEach(function (id) {
        var inst = dashboard._instances[id];
        if (inst) inst.resize();
    });
});

/* ── Execution History: time-series comparison across runs ──
   Reads /api/history/* (populated automatically after each workflow run)
   to chart how a metric — emotion distribution, tendency distribution, or
   row count — has changed across runs over time, e.g. "how has sentiment
   on this topic shifted over the last two weeks of crawls". */
var historyPanel = {
    _instance: null,

    async open() {
        var panel = document.getElementById('history-panel');
        panel.classList.add('open');
        if (!panel.dataset._uiInit) {
            panel.dataset._uiInit = '1';
            makeDraggable(panel, '.panel-header');
            makeResizable(panel, { minW: 420, minH: 320, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
            if (!panel.querySelector('.resize-handle')) {
                var rh = document.createElement('div');
                rh.className = 'resize-handle';
                panel.appendChild(rh);
            }
        }
        await this._loadRuns();
        await this.loadSeries();
    },

    async _loadRuns() {
        try {
            var resp = await fetch('/api/history/runs');
            var result = await resp.json();
            if (!result.ok) return;
            var select = document.getElementById('history-workflow-select');
            var current = select.value;
            select.innerHTML = '<option value="">' + I18n.t('history.allWorkflows') + '</option>' +
                result.workflow_names.map(function (n) { return '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + '</option>'; }).join('');
            if (current) select.value = current;

            var wrap = document.getElementById('history-runs-wrap');
            if (!result.runs.length) {
                wrap.innerHTML = '<div class="dashboard-empty">' + I18n.t('history.empty') + '</div>';
                return;
            }
            var html = '<table class="history-runs-table"><thead><tr>' +
                '<th>' + I18n.t('history.runId') + '</th><th>' + I18n.t('history.workflowName') + '</th>' +
                '<th>' + I18n.t('history.startedAt') + '</th><th>' + I18n.t('history.metricCount') + '</th>' +
                '</tr></thead><tbody>';
            result.runs.forEach(function (r) {
                html += '<tr><td>' + escapeHtml(r.run_id) + '</td><td>' + escapeHtml(r.workflow_name || '') + '</td>' +
                    '<td>' + escapeHtml(r.started_at) + '</td><td>' + r.metric_count + '</td></tr>';
            });
            html += '</tbody></table>';
            wrap.innerHTML = html;
        } catch (e) { /* non-fatal */ }
    },

    async loadSeries() {
        var workflowName = document.getElementById('history-workflow-select').value;
        var metric = document.getElementById('history-metric-select').value;
        var params = new URLSearchParams();
        if (workflowName) params.set('workflow_name', workflowName);
        if (metric) params.set('metric', metric);
        try {
            var resp = await fetch('/api/history/series?' + params.toString());
            var result = await resp.json();
            if (!result.ok) return;
            this._renderChart(result.rows, metric);
        } catch (e) { /* non-fatal */ }
    },

    /* Editorial palette drawn from the design system's muted accents
       (paper-white ground, ink #1a1a1a). The same label names the stats
       pies use are mapped here so a metric reads the same colour in both
       places. */
    _COLORS: {
        'Anger': '#a85454',
        'Joy': '#9a7740',
        'Sadness': '#4a6fa5',
        'Fear': '#8a6ea8',
        'Neutral': '#6f7f8a',
        'Objective Statement': '#6f7f8a',
        'Praise/Affirmation': '#4e8061',
        'Criticism/Questioning': '#a85454',
        'Controversy/Reflection': '#9a7740',
        'Advocacy/Call-to-action': '#4a6fa5',
        'Satire/Mockery': '#8a6ea8',
    },
    _FALLBACK: ['#4a6fa5', '#9a7740', '#4e8061', '#a85454', '#8a6ea8', '#6f7f8a', '#b5895a', '#5a8a7a'],

    _colorFor(metric, label, i) {
        if (metric === 'rows') return '#4a6fa5';
        var named = this._COLORS[label];
        if (named) return named;
        return this._FALLBACK[(i || 0) % this._FALLBACK.length];
    },

    _rgba(hex, alpha) {
        var h = String(hex || '').replace('#', '');
        if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
        var r = parseInt(h.slice(0, 2), 16) || 0;
        var g = parseInt(h.slice(2, 4), 16) || 0;
        var b = parseInt(h.slice(4, 6), 16) || 0;
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    },

    _ensureChart() {
        var el = document.getElementById('history-chart');
        if (this._instance) return el;
        /* SVG renderer: the chart is real, interactive SVG — crisp at any zoom,
           printable, and resizable without a canvas re-alloc. */
        this._instance = echarts.init(el, null, { renderer: 'svg' });
        if (window.ResizeObserver) {
            var inst = this._instance;
            new ResizeObserver(function () { inst.resize(); }).observe(el);
        }
        return el;
    },

    _renderChart(rows, metric) {
        this._ensureChart();
        var inst = this._instance;
        var metricLabel = I18n.t('history.metric.' + (metric || 'rows'));
        var wf = document.getElementById('history-workflow-select').value;
        var subtext = wf ? wf : I18n.t('history.allWorkflows');
        var ink = '#1a1a1a';
        var dim = 'rgba(26,26,26,0.55)';
        var faint = 'rgba(26,26,26,0.06)';
        /* Single source of truth is --font in style.css: Literata carries the
           latin glyphs and digits, 宋体/SimSun carries the CJK ones. ECharts
           text defaults to sans-serif, so the stack must be passed explicitly
           to every text block — reading the CSS variable keeps them in sync. */
        var chartFont = (getComputedStyle(document.documentElement)
            .getPropertyValue('--font') || '').trim()
            || '"Literata", "Songti SC", "SimSun", "宋体", serif';

        if (!rows.length) {
            var emptyFont = (getComputedStyle(document.documentElement)
                .getPropertyValue('--font') || '').trim()
                || '"Literata", "Songti SC", "SimSun", "宋体", serif';
            inst.setOption({
                title: {
                    text: I18n.t('history.empty'), left: 'center', top: 'middle',
                    textStyle: { color: 'rgba(26,26,26,0.4)', fontSize: 12, fontWeight: 400, fontFamily: emptyFont },
                },
                xAxis: { show: false }, yAxis: { show: false }, series: [],
            }, true);
            return;
        }

        var labelSet = {};
        rows.forEach(function (r) { labelSet[r.label || r.metric] = true; });
        var labels = Object.keys(labelSet);
        var self = this;
        var series = labels.map(function (label, i) {
            var color = self._colorFor(metric, label, i);
            var pts = rows
                .filter(function (r) { return (r.label || r.metric) === label; })
                .map(function (r) { return [r.timestamp, r.value]; });
            if (metric === 'rows') {
                return {
                    name: label, type: 'bar', data: pts, barWidth: '46%',
                    itemStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: color },
                            { offset: 1, color: self._rgba(color, 0.5) },
                        ]),
                        borderRadius: [3, 3, 0, 0],
                    },
                };
            }
            return {
                name: label, type: 'line', data: pts, smooth: true,
                symbol: 'circle', symbolSize: 5, showSymbol: true,
                lineStyle: { width: 2, color: color },
                itemStyle: { color: color },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: self._rgba(color, 0.22) },
                        { offset: 1, color: self._rgba(color, 0.02) },
                    ]),
                },
            };
        });

        inst.setOption({
            backgroundColor: 'transparent',
            /* Title → legend → plot are stacked with real gaps: the title block
               ends ~45px down, the legend sits below it, and the grid starts
               low enough that neither can clip the other. Legend is scroll
               type so many workflow labels stay on one line instead of
               wrapping down over the plot. Left/right grid margins stay
               symmetric so the plot area reads as centred in the panel. */
            title: {
                text: metricLabel, subtext: subtext, left: 'center', top: 8,
                textStyle: { color: ink, fontSize: 14, fontWeight: 500, fontFamily: chartFont },
                subtextStyle: { color: 'rgba(26,26,26,0.45)', fontSize: 11, fontFamily: chartFont },
            },
            tooltip: {
                trigger: 'axis',
                backgroundColor: '#fff',
                borderColor: 'rgba(26,26,26,0.15)', borderWidth: 1,
                textStyle: { color: ink, fontSize: 12, fontFamily: chartFont },
                axisPointer: { type: 'line', lineStyle: { color: 'rgba(26,26,26,0.25)', type: 'dashed' } },
            },
            legend: {
                data: labels, top: 50, left: 'center', icon: 'circle',
                type: 'scroll', width: '86%',
                itemWidth: 8, itemHeight: 8, itemGap: 12,
                textStyle: { color: ink, fontSize: 11, fontFamily: chartFont },
            },
            grid: { top: 84, left: 44, right: 44, bottom: 56, containLabel: true },
            xAxis: {
                type: 'time',
                axisLine: { lineStyle: { color: 'rgba(26,26,26,0.15)' } },
                axisLabel: { color: dim, fontSize: 10, hideOverlap: true, fontFamily: chartFont },
                splitLine: { show: true, lineStyle: { color: faint } },
            },
            yAxis: {
                type: 'value',
                axisLine: { show: false }, axisTick: { show: false },
                axisLabel: { color: dim, fontSize: 10, fontFamily: chartFont },
                splitLine: { lineStyle: { color: faint } },
            },
            dataZoom: [
                { type: 'inside' },
                {
                    type: 'slider', height: 14, bottom: 4, borderColor: 'transparent',
                    fillerColor: 'rgba(26,26,26,0.06)', handleStyle: { color: ink },
                    textStyle: { color: dim, fontFamily: chartFont }, moveHandleSize: 4,
                },
            ],
            series: series,
        }, true);
        inst.resize();
    },

    async clear() {
        var confirmed = await showDialog({
            message: I18n.t('history.confirmClear'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('dialog.confirm'), value: true, primary: true },
            ],
        });
        if (!confirmed) return;
        try {
            await fetch('/api/history/clear', { method: 'POST' });
            showToast(I18n.t('history.cleared'));
            await this._loadRuns();
            await this.loadSeries();
        } catch (e) {
            showToast(I18n.t('toast.previewFailed') + ': ' + e.message);
        }
    },

    close() {
        document.getElementById('history-panel').classList.remove('open');
    },
};

// updateParam with refresh=true by default
function updateParam(nodeId, key, value) {
    var node = canvas.nodes[nodeId];
    if (node) {
        node.params[key] = value;
        canvas.updateNodeDisplay(nodeId);
        canvas.saveState();
        if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
    }
}

function closeSettings() {
    document.getElementById('node-settings').classList.remove('open');
    canvas._settingsNodeId = null;
    canvas.updateSettingsButton();
    /* The panel's controls render their dropdowns / suggestion lists into
       <body>, so they must be dismissed here too — otherwise a stray menu
       keeps floating over the canvas and can edit a node that is no longer
       on screen. */
    if (window.CustomSelect) CustomSelect.close();
}

/* Toggle Functions */

/* The app is light-only now: no dark (black) surface exists anywhere, so
   there is no theme toggle. Kept out deliberately.
   Parallel / Headless live in RunState (see app.js) because their buttons only
   exist inside a dropdown panel. */

function togglePin() {
    var menu = document.getElementById('top-menu');
    var btn = document.getElementById('pin-btn');
    menu.classList.toggle('pinned');
    btn.classList.toggle('pinned');
    var on = menu.classList.contains('pinned');
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    if (!on && window.TopMenu) TopMenu.close();
    Settings.save();
}

function toggleStats() {
    document.getElementById('stats-panel').classList.toggle('open');
}

/* Apply a canvas background. Called from the background swatches inside the
   View group of the flat bar, so the swatch that is current gets `.active`. */
function setBg(bg, el) {
    var body = document.body;
    body.className = body.className.replace(/bg-\S+/g, '').trim();
    body.classList.add(bg);
    body.classList.add('theme-light');
    document.querySelectorAll('.bar-bg-dot').forEach(function (o) { o.classList.remove('active'); });
    if (el) el.classList.add('active');
    Settings.save();
}

function setLang(nextLang) {
    var body = document.body;
    body.dataset.lang = nextLang;
    I18n.apply();
    Settings.save();
    showToast(I18n.t('toast.languageChanged').replace('{lang}', nextLang === 'zh' ? '中文' : 'English'));
    /* Refresh dynamically rendered content */
    Object.keys(canvas.nodes).forEach(function (id) {
        canvas.updateNodeDisplay(id);
    });
    if (canvas._settingsNodeId) openSettings(canvas._settingsNodeId);
    /* Keep the flat bar's active-language marker truthful. */
    if (window.TopMenu) TopMenu.refresh();
    /* Chart Studio: its mirrored nav chips and its source list (whose rows
       carry localised reasons) are built by JS, so I18n.apply() never reaches
       them — rebuild both. */
    if (window.chartStudio) {
        chartStudio.refreshMenus();
        chartStudio.refreshSources();
    }
    if (window.CustomSelect) CustomSelect.refreshAll();
}

function showToast(msg) {
    var toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    setTimeout(function () { toast.classList.remove('show'); }, 2500);
}

/* Console Panel */
function toggleConsole() {
    var panel = document.getElementById('console-panel');
    if (panel.classList.contains('popout')) {
        toggleConsolePopout(); /* Dock first, then close */
        panel.classList.remove('open');
    } else {
        panel.classList.toggle('open');
        if (!panel.classList.contains('open')) {
            /* Dropping .open only shrinks the panel if nothing overrides the
               CSS `height: 0` — the dock resize handle writes an inline
               height, and that inline value survives the class toggle. Clear
               it, or Close looks dead after the user resized the panel. */
            panel.style.height = '';
        }
    }
    /* The two panels share the same bottom slot; opening one closes the other. */
    if (panel.classList.contains('open') && window.runsManager) runsManager.close();
}

function toggleRunsPanel() {
    runsManager.toggle();
}

function clearConsole() {
    document.getElementById('console-output').innerHTML = '';
    /* Reset tab state so next poll starts fresh */
    _wfLastIdx = {};
    _wfActiveTab = 'all';
}

/* Workflow tab switching for parallel mode */
var _wfActiveTab = 'all';
var _wfLastIdx = {};
function switchWfTab(wfId) {
    _wfActiveTab = wfId;
    /* Clear output and re-fetch will fill it on next poll */
    document.getElementById('console-output').innerHTML = '';
    /* Reset log index for this tab so all logs re-render */
    if (wfId === 'all') {
        /* Will use lastLogIdx from pollStatus closure — just force re-render */
    } else {
        _wfLastIdx[wfId] = 0;
    }
    /* Update active tab styling */
    document.querySelectorAll('#console-tabs .console-tab').forEach(function (tab) {
        tab.classList.toggle('active', String(tab.dataset.wf) === String(wfId));
    });
}

/* Kill a process by calling the API */
function killProcess(btn) {
    var ident = parseInt(btn.dataset.ident);
    if (!ident) return;
    fetch('/api/workflow/processes/kill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ident: ident }),
    })
        .then(function (r) { return r.json(); })
        .then(function (result) {
            if (result.ok) {
                showToast(result.message);
            } else {
                showToast('Kill failed: ' + (result.error || ''));
            }
        })
        .catch(function (err) {
            showToast('Kill failed: ' + err.message);
        });
}

/* Processes Monitor Panel */
function toggleProcessesPanel() {
    var panel = document.getElementById('processes-panel');
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) {
        processesPoll();
    }
}

var _procInterval = null;

function processesPoll() {
    if (_procInterval) clearInterval(_procInterval);
    var panel = document.getElementById('processes-panel');
    if (!panel.classList.contains('open')) return;

    fetch('/api/workflow/processes')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!panel.classList.contains('open')) return;
            var out = document.getElementById('processes-output');
            var html = '';

            /* Summary line */
            var runningText = data.running
                ? '<span class="proc-ok">\u25cf ' + I18n.t('processes.running') + '</span>'
                : '<span class="proc-err">\u25cf ' + I18n.t('processes.stopped') + '</span>';
            html += '<div class="proc-summary">' + runningText +
                '<span>' + I18n.t('processes.threads') + ': <b>' + data.threads.length + '</b></span>' +
                '<span>' + I18n.t('processes.crawlers') + ': <b>' + data.active_crawlers + '</b></span>' +
                '<span>' + I18n.t('processes.pool') + ': <b>' + (data.executor_pool_alive ? I18n.t('processes.yes') : I18n.t('processes.no')) + '</b></span>' +
                '</div>';

            /* Thread table */
            html += '<table class="proc-table"><tr>' +
                '<th>' + I18n.t('processes.name') + '</th>' +
                '<th>' + I18n.t('processes.type') + '</th>' +
                '<th>' + I18n.t('processes.status') + '</th>' +
                '<th>' + I18n.t('processes.kill') + '</th>' +
                '</tr>';
            data.threads.forEach(function (t) {
                var typeClass = '';
                var typeLabel = '';
                if (t.name === 'MainThread') { typeLabel = 'main'; }
                else if (t.name.startsWith('ThreadPoolExecutor')) { typeLabel = '<span class="proc-tag proc-tag-pool">pool</span>'; }
                else if (t.name === 'run') { typeLabel = '<span class="proc-tag proc-tag-run">run</span>'; }
                else { typeLabel = t.daemon ? '<span class="proc-tag proc-tag-daemon">daemon</span>' : ''; }
                var canKill = t.name !== 'MainThread' && t.name !== 'run' && t.alive;
                html += '<tr>' +
                    '<td>' + t.name + '</td>' +
                    '<td>' + typeLabel + '</td>' +
                    '<td>' + (t.alive ? '<span class="proc-ok">alive</span>' : '<span class="proc-err">dead</span>') + '</td>' +
                    '<td>' + (canKill ? '<button class="proc-kill-btn" data-ident="' + t.ident + '" onclick="killProcess(this)">' + I18n.t('processes.kill') + '</button>' : '') + '</td>' +
                    '</tr>';
            });
            html += '</table>';
            out.innerHTML = html;
        })
        .catch(function () {
            if (document.getElementById('processes-panel').classList.contains('open')) {
                document.getElementById('processes-output').innerHTML =
                    '<div class="proc-line proc-err">Failed to fetch process info</div>';
            }
        });

    /* Poll every 1s while open */
    _procInterval = setInterval(function () {
        if (!document.getElementById('processes-panel').classList.contains('open')) {
            clearInterval(_procInterval);
            _procInterval = null;
            return;
        }
        fetch('/api/workflow/processes')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!document.getElementById('processes-panel').classList.contains('open')) return;
                var out = document.getElementById('processes-output');
                var html = '';
                var runningText = data.running
                    ? '<span class="proc-ok">\u25cf ' + I18n.t('processes.running') + '</span>'
                    : '<span class="proc-err">\u25cf ' + I18n.t('processes.stopped') + '</span>';
                html += '<div class="proc-summary">' + runningText +
                    '<span>' + I18n.t('processes.threads') + ': <b>' + data.threads.length + '</b></span>' +
                    '<span>' + I18n.t('processes.crawlers') + ': <b>' + data.active_crawlers + '</b></span>' +
                    '<span>' + I18n.t('processes.pool') + ': <b>' + (data.executor_pool_alive ? I18n.t('processes.yes') : I18n.t('processes.no')) + '</b></span>' +
                    '</div>';
                html += '<table class="proc-table"><tr>' +
                    '<th>' + I18n.t('processes.name') + '</th>' +
                    '<th>' + I18n.t('processes.type') + '</th>' +
                    '<th>' + I18n.t('processes.status') + '</th>' +
                    '<th>' + I18n.t('processes.kill') + '</th>' +
                    '</tr>';
                data.threads.forEach(function (t) {
                    var typeLabel = '';
                    if (t.name === 'MainThread') { typeLabel = 'main'; }
                    else if (t.name.startsWith('ThreadPoolExecutor')) { typeLabel = '<span class="proc-tag proc-tag-pool">pool</span>'; }
                    else if (t.name === 'run') { typeLabel = '<span class="proc-tag proc-tag-run">run</span>'; }
                    else { typeLabel = t.daemon ? '<span class="proc-tag proc-tag-daemon">daemon</span>' : ''; }
                    var canKill = t.name !== 'MainThread' && t.name !== 'run' && t.alive;
                    html += '<tr>' +
                        '<td>' + t.name + '</td>' +
                        '<td>' + typeLabel + '</td>' +
                        '<td>' + (t.alive ? '<span class="proc-ok">alive</span>' : '<span class="proc-err">dead</span>') + '</td>' +
                        '<td>' + (canKill ? '<button class="proc-kill-btn" data-ident="' + t.ident + '" onclick="killProcess(this)">' + I18n.t('processes.kill') + '</button>' : '') + '</td>' +
                        '</tr>';
                });
                html += '</table>';
                out.innerHTML = html;
            }).catch(function () { });
    }, 1000);
}

/* Custom Dialog - replaces browser prompt() */
function showDialog(opts) {
    return new Promise(function (resolve) {
        var overlay = document.getElementById('dialog-overlay');
        var msgEl = document.getElementById('dialog-message');
        var inputArea = document.getElementById('dialog-input-area');
        var inputEl = document.getElementById('dialog-input');
        var listArea = document.getElementById('dialog-list-area');
        var actionsEl = document.getElementById('dialog-actions');

        msgEl.textContent = opts.message || '';
        actionsEl.innerHTML = '';
        inputArea.style.display = 'none';
        listArea.style.display = 'none';
        listArea.innerHTML = '';

        if (opts.input) {
            inputArea.style.display = 'block';
            inputEl.value = opts.input.value || '';
            inputEl.placeholder = opts.input.placeholder || '';
        }

        if (opts.list) {
            listArea.style.display = 'block';
            opts.list.forEach(function (item) {
                var btn = document.createElement('button');
                btn.className = 'dialog-list-item';
                btn.textContent = item;
                btn.addEventListener('click', function () {
                    overlay.classList.remove('open');
                    resolve(item);
                });
                listArea.appendChild(btn);
            });
        }

        if (opts.buttons) {
            opts.buttons.forEach(function (b) {
                var btn = document.createElement('button');
                btn.className = 'menu-btn' + (b.primary ? ' toggle-on' : '');
                btn.textContent = b.label;
                btn.addEventListener('click', function () {
                    overlay.classList.remove('open');
                    resolve(b.value !== undefined ? b.value : (opts.input ? inputEl.value : true));
                });
                actionsEl.appendChild(btn);
            });
        }

        overlay.classList.add('open');
        if (opts.input) setTimeout(function () { inputEl.focus(); inputEl.select(); }, 100);
    });
}

/* Cookie Configuration */
function openCookieDialog() {
    var dialog = document.getElementById('cookie-dialog');
    dialog.classList.toggle('open');
    if (dialog.classList.contains('open')) {
        /* Refresh cookie status */
        fetch('/api/cookies/status')
            .then(function (r) { return r.json(); })
            .then(function (result) {
                var statusEl = document.getElementById('cookie-status');
                if (result.ok) {
                    var lines = [];
                    Object.keys(result.cookies).forEach(function (p) {
                        lines.push(p + ': ' + (result.cookies[p] ? 'Configured' : 'Not set'));
                    });
                    statusEl.textContent = lines.join(' | ');
                }
            }).catch(function () { });
    }
}

function closeCookieDialog() {
    document.getElementById('cookie-dialog').classList.remove('open');
}

function saveCookieConfig() {
    var platform = document.getElementById('cookie-platform').value;
    var jsonStr = document.getElementById('cookie-json').value.trim();
    if (!jsonStr) {
        showToast(I18n.t('cookie.pasteFirst'));
        return;
    }
    try {
        var cookies = JSON.parse(jsonStr);
        fetch('/api/cookies/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: platform, cookies: cookies }),
        })
            .then(function (r) { return r.json(); })
            .then(function (result) {
                if (result.ok) {
                    showToast(I18n.t('toast.cookiesSaved') + ' - ' + platform);
                    document.getElementById('cookie-json').value = '';
                } else {
                    showToast(I18n.t('cookie.failed').replace('{err}', result.error || ''));
                }
            });
    } catch (e) {
        showToast(I18n.t('cookie.invalidJson').replace('{err}', e.message));
    }
}

function generateCookie() {
    var platform = document.getElementById('cookie-platform').value;
    var waitSeconds = parseInt(document.getElementById('cookie-wait').value) || 120;
    var statusEl = document.getElementById('cookie-status');
    statusEl.textContent = I18n.t('cookie.opening')
        .replace('{platform}', platform)
        .replace('{s}', waitSeconds);
    fetch('/api/cookies/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, wait_seconds: waitSeconds }),
    })
        .then(function (r) { return r.json(); })
        .then(function (result) {
            if (result.ok) {
                statusEl.textContent = I18n.t('cookie.generated').replace('{platform}', platform);
                showToast(I18n.t('toast.cookiesSaved') + ' - ' + platform);
            } else {
                statusEl.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
            }
        });
}

/* ── Resume banner ─────────────────────────────────────────────
   A run that was interrupted leaves its rows behind, and the only place to say
   so is here: the alternative is a silent re-run that throws away everything
   already paid for. It is refreshed after every run and whenever the canvas
   is rebuilt, because the match depends on the workflow's shape. */
var resumeBar = {
    candidate: null,

    async refresh() {
        const banner = document.getElementById('resume-banner');
        if (!banner) return null;
        if (!window.canvas || !Object.keys(canvas.nodes || {}).length) {
            this.candidate = null;
            banner.classList.add('hidden');
            return null;
        }
        let runs = [];
        try {
            const resp = await fetch('/api/runs/resumable', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workflow: canvas.toWorkflowJSON() }),
            });
            const result = await resp.json();
            runs = (result.ok && result.runs) || [];
        } catch (e) {
            runs = [];
        }
        /* Anything still running belongs to this moment, not to a past attempt. */
        this.candidate = runs[0] || null;
        this.render();
        return this.candidate;
    },

    render() {
        const banner = document.getElementById('resume-banner');
        const text = document.getElementById('resume-text');
        if (!banner || !text) return;
        if (!this.candidate) {
            banner.classList.add('hidden');
            return;
        }
        const run = this.candidate;
        const detail = I18n.t('resume.detail')
            .replace('{done}', run.node_done || 0)
            .replace('{total}', run.node_total || 0)
            .replace('{rows}', run.rows_kept || 0);
        text.textContent = I18n.t('resume.interrupted').replace('{at}', run.started_at || run.run_id) + ' — ' + detail;
        banner.classList.remove('hidden');
    },

    continueRun() {
        if (!this.candidate) return;
        workflow.execute({ resumeRunId: this.candidate.run_id });
    },

    async restart() {
        const runId = this.candidate && this.candidate.run_id;
        this.hide();
        if (runId) {
            try {
                /* Dropping the saved run includes its "already crawled" claims,
                   otherwise the fresh run would skip everything it fetched. */
                await fetch('/api/runs/discard', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ run_id: runId }),
                });
            } catch (e) { /* a failed discard still starts the run */ }
            showToast(I18n.t('toast.runDiscarded'));
        }
        workflow.execute();
    },

    dismiss() {
        this.hide();
    },

    hide() {
        this.candidate = null;
        const banner = document.getElementById('resume-banner');
        if (banner) banner.classList.add('hidden');
    },
};

/* ── Run records manager ──────────────────────────────────────
   Every recorded run — including orphans the resume banner can no longer
   match (the workflow was rewired or deleted since). Each row offers the
   three things the banner offers and one it can't: continue, restart from
   scratch, delete outright, and a per-node breakdown. The panel itself is
   docked at the bottom of the window, console-style. */
var runsManager = {
    panel() {
        return document.getElementById('runs-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        var opening = !panel.classList.contains('open');
        /* Same bottom slot as the console — the two cannot stack. */
        if (opening) {
            var consolePanel = document.getElementById('console-panel');
            if (consolePanel) consolePanel.classList.remove('open');
            panel.classList.add('open');
            this.refresh();
        } else {
            this.close();
        }
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* Same trap as the console: the resize handle leaves an inline height
           behind, and an inline height overrides the CSS `height: 0` — the
           panel would refuse to shrink after being resized. */
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('runs-mgr-body');
        if (!body) return;
        try {
            var resp = await fetch('/api/runs/list?limit=50');
            var result = await resp.json();
            this.render((result.ok && result.runs) || []);
        } catch (e) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('runsMgr.empty') + '</div>';
        }
    },

    statusKey(status) {
        var known = ['running', 'interrupted', 'completed', 'failed', 'abandoned'];
        return known.indexOf(status) >= 0 ? 'runsMgr.status.' + status : 'runsMgr.status.completed';
    },

    render(runs) {
        var body = document.getElementById('runs-mgr-body');
        var count = document.getElementById('runs-mgr-count');
        if (!body) return;
        if (count) count.textContent = runs.length ? '(' + runs.length + ')' : '';
        if (!runs.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('runsMgr.empty') + '</div>';
            return;
        }
        var rows = runs.map(function (r) {
            var resumable = !!r.resumable;
            var ops = '';
            if (resumable) {
                ops += '<button class="runs-mgr-btn" onclick="runsManager.continueRun(\'' + r.run_id + '\')">' + I18n.t('runsMgr.resume') + '</button>';
                ops += '<button class="runs-mgr-btn" onclick="runsManager.restart(\'' + r.run_id + '\')">' + I18n.t('runsMgr.restart') + '</button>';
            }
            ops += '<button class="runs-mgr-btn del" onclick="runsManager.remove(\'' + r.run_id + '\', ' + (resumable ? 'true' : 'false') + ')">' + I18n.t('runsMgr.remove') + '</button>';
            ops += '<button class="runs-mgr-btn" onclick="runsManager.detail(\'' + r.run_id + '\', this)">' + I18n.t('runsMgr.detail') + '</button>';
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(r.workflow_name || I18n.t('name.unnamed')) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(r.run_id) + '</td>' +
                '<td><span class="runs-mgr-status st-' + escapeHtml(r.status || '') + '">' + I18n.t(runsManager.statusKey(r.status)) + '</span></td>' +
                '<td>' + (r.node_done || 0) + '/' + (r.node_total || 0) + '</td>' +
                '<td>' + (r.rows_kept || 0) + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(r.started_at || '') + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('runsMgr.colWorkflow') + '</th>' +
            '<th>run_id</th>' +
            '<th>' + I18n.t('runsMgr.colStatus') + '</th>' +
            '<th>' + I18n.t('runsMgr.colNodes') + '</th>' +
            '<th>' + I18n.t('runsMgr.colRows') + '</th>' +
            '<th>' + I18n.t('runsMgr.colStarted') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>';
    },

    _busy() {
        if (window.RunState && RunState.running) {
            showToast(I18n.t('runsMgr.busy'));
            return true;
        }
        return false;
    },

    continueRun(runId) {
        if (this._busy()) return;
        /* Hand the bottom slot back to the console before the run starts. */
        this.close();
        workflow.execute({ resumeRunId: runId });
    },

    async restart(runId) {
        if (this._busy()) return;
        if (!window.confirm(I18n.t('runsMgr.confirmRestart'))) return;
        try {
            /* Same contract as the banner's restart: dropping the run drops
               its "already crawled" claims, or the fresh attempt would see
               everything as already-seen and quietly return fewer rows. */
            await fetch('/api/runs/discard', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: runId }),
            });
        } catch (e) { /* a failed discard still starts the run */ }
        this.close();
        workflow.execute();
    },

    async remove(runId, wasResumable) {
        if (!window.confirm(I18n.t('runsMgr.confirmRemove'))) return;
        /* An interrupted run being deleted outright means "never continue
           it": its crawl claims must go too, or those items stay claimed by
           a run that no longer exists. A finished run keeps them — deleting
           its data must not resurrect items as unseen. */
        var url = wasResumable ? '/api/runs/discard' : '/api/runs/delete';
        try {
            var resp = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: runId }),
            });
            var result = await resp.json();
            showToast(result.ok ? I18n.t('runsMgr.removeDone') : I18n.t('runsMgr.removeFailed'));
        } catch (e) {
            showToast(I18n.t('runsMgr.removeFailed'));
        }
        this.refresh();
        if (window.resumeBar) resumeBar.refresh();
    },

    async detail(runId, btn) {
        var row = btn && btn.closest ? btn.closest('tr') : null;
        var existing = document.getElementById('runs-mgr-detail-' + runId);
        if (existing) {
            existing.remove();
            return;
        }
        try {
            var resp = await fetch('/api/runs/' + encodeURIComponent(runId));
            var result = await resp.json();
            if (!result.ok || !result.run) return;
            var run = result.run;
            var tr = document.createElement('tr');
            tr.id = 'runs-mgr-detail-' + runId;
            tr.innerHTML = '<td colspan="7" class="runs-mgr-detail"><div class="runs-mgr-detail-title">' +
                I18n.t('runsMgr.detailNodes') + '</div>' +
                (run.nodes || []).map(function (n) {
                    return '<div class="runs-mgr-node">' +
                        '<span class="runs-mgr-node-id">' + escapeHtml(n.node_id || '') + '</span>' +
                        '<span>' + escapeHtml(n.node_type || '') + '</span>' +
                        '<span class="runs-mgr-node-st">' + escapeHtml(n.status || '') + '</span>' +
                        '<span>' + (n.row_count || 0) + ' ' + I18n.t('runsMgr.colRows') + '</span>' +
                        (n.error ? '<span class="runs-mgr-node-err">' + escapeHtml(n.error) + '</span>' : '') +
                        '</div>';
                }).join('') + '</td>';
            if (row) row.after(tr);
        } catch (e) { /* leave the table as it was */ }
    },
};

workflow.validate = function () {
    var errors = [];
    var nodes = canvas.nodes;
    var conns = canvas.connections;

    if (Object.keys(nodes).length === 0) {
        errors.push(I18n.t('validate.empty'));
        return errors;
    }

    /* Build lookup: which nodes have inputs/outputs, and how many inputs each
       one has (a join needs two: left table, right table). */
    var hasInput = {};
    var hasOutput = {};
    var inputCount = {};
    conns.forEach(function (c) {
        hasOutput[c.from] = true;
        hasInput[c.to] = true;
        inputCount[c.to] = (inputCount[c.to] || 0) + 1;
    });

    Object.keys(nodes).forEach(function (id) {
        var node = nodes[id];
        var params = node.params || {};
        var type = node.type;

        if (type === 'source') {
            if (params.platform === 'wechat') {
                /* WeChat crawls the article URLs you paste; a keyword would be
                   ignored, so asking for one (as this used to) both blocked a
                   valid workflow and left the platform unusable. */
                if (!params.urls || !String(params.urls).trim()) {
                    errors.push(I18n.t('validate.sourceUrls').replace('{title}', node.title));
                }
            } else if (!params.keyword || !params.keyword.trim()) {
                errors.push(I18n.t('validate.sourceKeyword').replace('{title}', node.title));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.sourceDownstream').replace('{title}', node.title));
            }
        }

        if (type === 'process') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.processInput').replace('{title}', node.title));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.processDownstream').replace('{title}', node.title));
            }
        }

        if (type === 'analysis') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.analysisInput').replace('{title}', node.title));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.analysisDownstream').replace('{title}', node.title));
            }
            if (!params.operation) {
                errors.push(I18n.t('validate.analysisOperation').replace('{title}', node.title));
            }
            if (params.operation === 'join_tables' && (inputCount[id] || 0) < 2) {
                /* The right-hand table is the node's second incoming
                   connection — without it the join has nothing to join with. */
                errors.push(I18n.t('validate.joinNeedsTwo').replace('{title}', node.title));
            }
        }

        if (type === 'upload') {
            /* A source like any other: nothing upstream, but it must have a file. */
            if (!params.dataset_id) {
                errors.push(I18n.t('validate.uploadFile').replace('{title}', node.title));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.uploadDownstream').replace('{title}', node.title));
            }
        }

        if (type === 'name') {
            /* The name node is metadata, not data: it must sit at the head of
               the workflow (no incoming edges), wire into something, and
               carry a non-empty label — that label is what groups the run in
               the Execution History panel. */
            if (!params.workflow_name || !String(params.workflow_name).trim()) {
                errors.push(I18n.t('validate.nameEmpty').replace('{title}', node.title));
            }
            if (hasInput[id]) {
                errors.push(I18n.t('validate.nameMustLead').replace('{title}', node.title));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.nameDownstream').replace('{title}', node.title));
            }
        }

        if (type === 'tokenize') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.tokenizeInput').replace('{title}', node.title));
            }
            if (!params.text_column || !params.text_column.trim()) {
                errors.push(I18n.t('validate.tokenizeColumn').replace('{title}', node.title));
            }
        }

        if (type === 'visualize') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.visualizeInput').replace('{title}', node.title));
            }
            if (!params.chart_type) {
                errors.push(I18n.t('validate.visualizeChartType').replace('{title}', node.title));
            }
            if (!params.x_field || !params.x_field.trim()) {
                errors.push(I18n.t('validate.visualizeXField').replace('{title}', node.title));
            }
        }

        if (type === 'output') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.outputInput').replace('{title}', node.title));
            }
            if ((params.operation === 'save' || params.operation === 'save_csv') && (!params.filename || !params.filename.trim())) {
                errors.push(I18n.t('validate.outputFilename').replace('{title}', node.title));
            }
        }
    });

    var hasUpstream = Object.keys(nodes).some(function (id) {
        return ['source', 'upload', 'process', 'analysis', 'tokenize', 'resume'].indexOf(nodes[id].type) >= 0;
    });
    if (hasUpstream) {
        var hasTerminal = Object.keys(nodes).some(function (id) {
            return nodes[id].type === 'output' || nodes[id].type === 'visualize';
        });
        if (!hasTerminal) {
            errors.push(I18n.t('validate.noTerminal'));
        }
    }

    return errors;
};
