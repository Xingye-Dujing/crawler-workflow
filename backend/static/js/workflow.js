/* Workflow Execution & File Management */

/* How far the browser has read in the run console, and what each view has shown.
 *
 * The status endpoint ships the last 200 lines plus the true total, and "which
 * lines are new" is derived from that pair. Two things can strand the console: a
 * run that passes 200 lines (the total solves it), and the server restarting its
 * buffer when the NEXT run begins — the total then drops BELOW the index already
 * consumed, and a plain slice returns nothing for the rest of the run, which is
 * how the console used to freeze after a second Run. `takeLines` is the single
 * place that reads both cases.
 *
 * The second half of this state is the reason a tab switch stopped emptying the
 * box: the server holds only the tail of the *whole* run, so a view cannot be
 * rebuilt from a later response. Each view therefore keeps the lines it has
 * already shown, which is what lets 切换工作流标签页 repaint the tab it enters
 * instead of showing nothing until the next line arrives. */
var CONSOLE_VIEW_CAP = 500;
var consoleViews = { all: { seen: 0, lines: [] }, wf: {} };

function consoleViewFor(key) {
    if (key === 'all') return consoleViews.all;
    if (!consoleViews.wf[key]) consoleViews.wf[key] = { seen: 0, lines: [] };
    return consoleViews.wf[key];
}

function takeLines(lines, total, seen) {
    var held = lines || [];
    var count = total === undefined || total === null ? held.length : total;
    var seenAt = count < seen ? 0 : seen;
    var dropped = Math.max(0, count - held.length);
    return held.slice(Math.max(0, seenAt - dropped));
}

/** Advance one view over the answer it just received.
 *
 * Returns the lines that are new to this view and whether its history had to be
 * trimmed. Every view is fed on every poll — including the tab nobody is looking
 * at — because a tab that is only read when it becomes visible has nothing to
 * show the moment the user clicks it. */
function feedConsoleView(view, lines, total) {
    var fresh = takeLines(lines, total, view.seen);
    var held = lines || [];
    view.seen = total === undefined || total === null ? held.length : total;
    if (!fresh.length) return { fresh: fresh, trimmed: false };
    view.lines = view.lines.concat(fresh);
    var trimmed = false;
    if (view.lines.length > CONSOLE_VIEW_CAP) {
        view.lines = view.lines.slice(view.lines.length - CONSOLE_VIEW_CAP);
        trimmed = true;
    }
    return { fresh: fresh, trimmed: trimmed };
}

function appendConsoleLines(out, lines) {
    (lines || []).forEach(function (log) {
        var line = document.createElement('div');
        line.className = 'console-line';
        line.textContent = log;
        out.appendChild(line);
    });
}

/** Rebuild the box from the view's own history (a tab switch, or a trim). */
function repaintConsoleView(out, key) {
    out.textContent = '';
    appendConsoleLines(out, consoleViewFor(key).lines);
    out.scrollTop = out.scrollHeight;
}

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
                /* A file that opens is a file that loads. `loadFromJSON` refuses a
                   body without a node list, and remembering the name anyway would
                   make the next Save overwrite a workflow the screen never showed. */
                if (!this.loadFromJSON(result.workflow)) return;
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
        /* Checked BEFORE anything is torn down: the old order cleared the canvas,
           then died on `workflowData.nodes.forEach` for a file without a node
           list, so opening a foreign or half-written JSON cost the user the
           workflow they had on screen and told them only 'load failed'. */
        if (!workflowData || typeof workflowData !== 'object' || !Array.isArray(workflowData.nodes)) {
            showToast(I18n.t('toast.workflowFileInvalid'));
            return false;
        }
        document.getElementById('nodes-container').innerHTML = '';
        canvas.nodes = {};
        canvas.connections = [];
        canvas.nextId = 1;
        workflowData.nodes.forEach(function (n) {
            /* The file's own ids come back unchanged: run records and resume
               cursors are filed under them, so a re-mint on open would leave
               the interrupted run unreachable from the canvas it belongs to
               (see canvas.addNode's nodeId). */
            var id = canvas.addNode(n.type, n.x, n.y, n.id);
            if (canvas.nodes[id]) {
                canvas.nodes[id].params = n.params || {};
                // A renamed node must come back renamed (see canvas.restoreState).
                if (n.title) {
                    canvas.nodes[id].title = n.title;
                    var titleEl = canvas.nodes[id].el && canvas.nodes[id].el.querySelector('.node-title');
                    if (titleEl) titleEl.textContent = n.title;
                }
                canvas.updateNodeDisplay(id);
                // After the display update, which rewrites the content it hides.
                if (n.folded) canvas._setFolded(id, true);
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
        /* The panel may still be showing a node from whatever was open before. */
        if (canvas._settingsNodeId) closeSettings();
        var settings = workflowData.settings || {};
        if (settings.mode === 'serial') RunState.set('parallel', false);
        if (settings.headless === false) RunState.set('headless', false);
        return true;
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

    /* The name this canvas's runs are filed under: a name node's label wins,
       then the saved file name — the same precedence the backend applies when
       it records a run. Preview and the studio must ask for rows by the name
       the run was STORED under, or a reopened canvas asks for nothing and the
       server would have to guess by node id (which repeats on every canvas). */
    runName() {
        var nodes = canvas.nodes || {};
        var labels = [];
        for (var id in nodes) {
            if (!Object.prototype.hasOwnProperty.call(nodes, id)) continue;
            if (nodes[id].type !== 'name') continue;
            var label = String((nodes[id].params || {}).workflow_name || '').trim();
            /* All of them, joined — the same composition the backend applies when it
               records the run. This string is how a preview finds the stored rows after
               a refresh (node ids repeat across every canvas), so the two sides have
               to build it identically or a multi-workflow run's data becomes invisible. */
            if (label && labels.indexOf(label) < 0) labels.push(label);
        }
        return labels.join(' + ') || this.currentFile || '';
    },

    async _confirmProfileBeforeRun() {
        /* Off-by-default is the point: a run that is about to be refused by a
           rotating session cookie should say so while the user can still act —
           one dialog, naming how many platforms are affected, with 继续运行 for
           the case where they know it works anyway. */
        if (window.AppSettings) await AppSettings.pull();
        var values = (window.AppSettings && AppSettings._values) || {};
        var wanted = profileNoticeCount(canvas.nodes, values, Capabilities.data);
        if (!wanted) return true;
        var message = I18n.t('dialog.profileOff').replace('{n}', wanted);
        var choice = await showDialog({
            message: message,
            buttons: [
                { label: I18n.t('dialog.profileGoOn'), value: 'go' },
                { label: I18n.t('dialog.profileSetup'), value: 'setup', primary: true },
            ],
        });
        if (choice !== 'go' && typeof toggleSettingsMenu === 'function') toggleSettingsMenu();
        return choice === 'go';
    },

    async _confirmProfileChoiceBeforeRun() {
        /* Parallel + the same platform in two workflows is a genuine fork in the
           road, and only the user can pick:

             · 用 Profile — the site sees one continuous device (what weibo and
               xiaohongshu punish a throwaway browser for), but one profile holds
               one Chrome, so those crawls take turns and 并行 buys nothing there;
             · 本次不用 — the workflows really do crawl side by side, and each one
               starts as a brand-new device on a planted cookie snapshot.

           Returns null when there is nothing to decide (profiles off, not
           parallel, no shared platform) or true/false for the user's answer. A
           cancelled dialog returns false *and* stops the run — see the caller. */
        var json = canvas.toWorkflowJSON();
        var settings = (json && json.settings) || {};
        if (settings.mode !== 'parallel') return null;
        if (window.AppSettings) await AppSettings.pull();
        var values = (window.AppSettings && AppSettings._values) || {};
        if (!values.use_browser_profile) return null;
        var shared = profileCollisions(canvas.nodes, canvas.connections);
        if (!shared.length) return null;
        var message = I18n.t('dialog.profileClash')
            .replace('{platforms}', shared.join('、'))
            .replace('{n}', shared.length);
        var choice = await showDialog({
            message: message,
            buttons: [
                { label: I18n.t('dialog.profileClashUse'), value: 'use' },
                { label: I18n.t('dialog.profileClashSkip'), value: 'skip', primary: true },
                { label: I18n.t('dialog.cancel'), value: null },
            ],
        });
        if (choice === 'use') return true;
        if (choice === 'skip') return false;
        return undefined; // cancelled — the caller must not start the run
    },

    async _confirmCookieBeforeRun(opts) {
        /* Returns true when the run may proceed (no crawler nodes, the prompt
           disabled, a resume — the user is already mid "refresh cookie and
           continue" loop, asking twice would be cruelty —, or the user chose
           继续执行), false when the user chose to exit and refresh. */
        if (opts && opts.resumeRunId) return true;
        var hasCrawler = Object.keys(canvas.nodes).some(function (id) {
            var t = canvas.nodes[id].type;
            return t === 'source' || t === 'comment';
        });
        if (!hasCrawler) return true;
        if (window.AppSettings) await AppSettings.pull();
        var values = (window.AppSettings && AppSettings._values) || {};
        if (!values.cookie_confirm_before_run) return true;
        var choice = await showDialog({
            message: I18n.t('dialog.cookieConfirm'),
            buttons: [
                { label: I18n.t('dialog.cookieGoOn'), value: 'go' },
                { label: I18n.t('dialog.cookieExit'), value: 'exit', primary: true },
            ],
        });
        return choice === 'go';
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
        /* Ask about the browser before the browser is bought: on the platforms
           whose session rotates, a throwaway profile *is* the failure, and a run
           would only discover it an hour deep. */
        if (!(await this._confirmProfileBeforeRun())) return;
        /* Parallel + a platform two workflows both want is the one case where
           keeping the device and keeping the parallelism are mutually exclusive,
           so the user decides which they are buying. ``undefined`` means they
           closed the dialog; null means there was nothing to decide. */
        var profileChoice = await this._confirmProfileChoiceBeforeRun();
        if (profileChoice === undefined) return;
        /* A long crawl can outlive its cookie and die at the login wall an hour
           in. When the setting is on, ask up front "refresh the cookie first?"
           — the user can bail here instead of wasting a run. Off means run
           straight away, exactly as before. Only fires when the workflow really
           contains a crawler (source/comment) node. */
        if (!(await this._confirmCookieBeforeRun(opts))) return;
        /* A second press while a run is in flight is no longer a dead end: the
           server parks the request and starts it when the slot frees. So every
           claim this function makes about the page state has to go back to what
           it *was*, not to 'idle' — the run already in flight is still running,
           and the console on screen still belongs to it. */
        var wasRunning = RunState.running;
        function restoreRunState() {
            RunState.setRunning(wasRunning);
        }
        RunState.setRunning(true);
        var workflowData = canvas.toWorkflowJSON();
        if (profileChoice !== null && workflowData && workflowData.settings) {
            /* Only when the user actually answered: writing `false` for every run
               would turn a per-run choice into a silent override of the setting. */
            workflowData.settings.use_profile = profileChoice;
        }
        /* AI transport check — fail fast instead of dying 200 rows into a run. */
        var llm = LLMSettings.payload();
        if (canvas.nodes && Object.keys(canvas.nodes).some(function (id) {
            var n = canvas.nodes[id];
            return n.type === 'process' && nodeNeedsLlm(n.params, n.operation);
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
                restoreRunState();
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
                    workflow_name: this.runName(),
                    /* The resume banner's "continue" passes the interrupted
                       run's id here: the backend reuses that run (same node
                       rows, same crawler cursors) instead of starting a fresh
                       one. Without it the backend mints a new id and every
                       cursor dies — the run silently degrades to a cold start. */
                    resume_run_id: opts.resumeRunId || '',
                    /* A 继续 is never parked. While it waits, the record it points
                       at can be aged out by retention, and a continue that starts
                       minutes later is a different — worse — operation than the
                       one the user asked for. Refuse it now, say why, let them
                       press Run on purpose. */
                    queue: !opts.resumeRunId,
                }),
            });
            var result = await resp.json();
            if (result.ok && result.queued) {
                /* Parked, not started: the console must keep showing the run
                   that IS going, so nothing here is cleared. */
                restoreRunState();
                showToast(result.message || I18n.t('toast.queued'));
                runsManager.refreshIfOpen();
                return;
            }
            if (result.ok) {
                var statusText = document.getElementById('status-text');
                statusText.textContent = I18n.t('status.running');
                /* One bottom slot for console / run records / export artefacts.
                   Cleared only now: until this answer there was no run of ours. */
                closeDockedPanels('console-panel');
                document.getElementById('console-panel').classList.add('open');
                document.getElementById('console-output').innerHTML = '';
                showToast(I18n.t('toast.workflowStarted'));
                this.pollStatus();
            } else {
                showToast(I18n.t('toast.executeFailed') + ': ' + (result.error || ''));
                restoreRunState();
            }
        } catch (e) {
            showToast(I18n.t('toast.executeFailed') + ': ' + e.message);
            restoreRunState();
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
        /* The expiry toast is once-per-run: the flag stays set for the rest of
           the crawl, and polling every second would otherwise shout forever. */
        var cookieWarned = false;
        var interval = setInterval(async function () {
            try {
                var resp = await fetch('/api/workflow/status');
                var result = await resp.json();
                if (result.cookie_expired && !cookieWarned) {
                    cookieWarned = true;
                    showToast(I18n.t('toast.cookieExpired'));
                }
                if (result.logs) {
                    var lastLog = result.logs[result.logs.length - 1];
                    /* The bar carries the activity, without the console's clock:
                       copying the whole line in — '[12:04:11] …' included — put
                       the same sentence on screen twice, in two formats. */
                    document.getElementById('status-text').textContent = lastLog
                        ? lastLog.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '')
                        : I18n.t('status.running');
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
                                '<span class="tab-dot ' + dotClass + '"></span>' + escapeHtml(wf.name || ('#' + (wf.id + 1))) + '</div>';
                        });
                        consoleTabs.innerHTML = tabHtml;

                        /* Every view is read on every tick; only the visible one is
                           written to the DOM. That is what keeps a tab the user is
                           not looking at from losing its history. */
                        var feedAll = feedConsoleView(consoleViews.all, result.logs, result.log_total);
                        var feeds = {};
                        (result.workflows || []).forEach(function (w) {
                            feeds[w.id] = feedConsoleView(consoleViewFor(w.id), w.logs, w.total);
                        });
                        var shown = activeTab === 'all' ? feedAll : feeds[activeTab];
                        if (shown) {
                            var follow = shown.fresh.length > 0 && consoleWantsFollow(consoleOut);
                            if (shown.trimmed) {
                                repaintConsoleView(consoleOut, activeTab);
                            } else {
                                appendConsoleLines(consoleOut, shown.fresh);
                                if (follow) {
                                    consoleOut.scrollTop = consoleOut.scrollHeight;
                                }
                            }
                        }
                    } else {
                        /* Single workflow — original behavior */
                        consoleTabs.style.display = 'none';
                        consoleTabs.innerHTML = '';
                        var feedSingle = feedConsoleView(consoleViews.all, result.logs, result.log_total);
                        var followSingle = feedSingle.fresh.length > 0 && consoleWantsFollow(consoleOut);
                        if (feedSingle.trimmed) {
                            repaintConsoleView(consoleOut, 'all');
                        } else {
                            appendConsoleLines(consoleOut, feedSingle.fresh);
                            if (followSingle) {
                                consoleOut.scrollTop = consoleOut.scrollHeight;
                            }
                        }
                    }

                    /* Status bar update */
                    if (!result.running) {
                        clearInterval(interval);
                        RunState.setRunning(false);
                        if (result.logs && result.logs.length) {
                            document.getElementById('status-text').textContent = I18n.t('status.completed');
                        }
                        /* The run reports its own verdict. Inferring
                           'unfinished, worth a continue' from completed<total
                           announced a resume for a run that had merely starved
                           one node, and inferred '0/0' for a definition that was
                           refused before anything ran. */
                        var doneNodes = Number(result.completed_nodes) || 0;
                        var plannedNodes = Number(result.total_nodes) || 0;
                        var outcome = result.outcome
                            || (plannedNodes > 0 && doneNodes >= plannedNodes ? 'completed' : 'failed');
                        /* The progress ratio stays on screen. Overwriting it with
                           the canvas node count was a different statistic wearing
                           the same label, printed at the exact moment the reader
                           wants to know how much of the run finished. */
                        document.getElementById('status-nodes').textContent = I18n.t('status.progress')
                            .replace('{done}', doneNodes)
                            .replace('{total}', plannedNodes);
                        if (outcome === 'completed') {
                            showToast(I18n.t('toast.workflowCompleted'));
                        } else if (outcome === 'rejected') {
                            showToast(I18n.t('toast.workflowRejected'));
                        } else if (outcome === 'interrupted') {
                            showToast(I18n.t('toast.workflowStopped'));
                        } else {
                            showToast(I18n.t('toast.workflowEnded').replace('{done}', doneNodes).replace('{total}', plannedNodes));
                        }
                        I18n.apply();
                        stats.refresh();
                        /* Only a run that left work behind is worth offering to
                           continue — a clean completion and a refused definition
                           both have nothing to resume. */
                        if (window.resumeBar && (outcome === 'failed' || outcome === 'interrupted')) resumeBar.refresh();
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

/* ─── Crawl capabilities: the backend's matrix, rendered rather than re-listed ───
   Which platforms exist, which of them take links instead of a keyword, and what
   each mode asks for belongs to the executor. The panel used to keep its own
   answer to those questions — a platform could be added in Python and stay
   missing here, or appear here while the server still refused it. One fetch now
   feeds one renderer, so the form is the matrix. Labels travel as catalogue keys
   because the payload carries no language: the canvas translates it. */
const Capabilities = {
    data: null,
    error: '',
    loading: false,

    load() {
        /* One in-flight request, handed to whoever asks while it is running: a
           second caller that got `null` back would render the failure note for a
           list that was about to arrive, and a retry clicked twice would fire two
           fetches whose answers race. */
        if (this._pending) return this._pending;
        this.loading = true;
        var self = this;
        this._pending = fetch('/api/capabilities')
            .then(function (resp) {
                return resp.json();
            })
            .then(function (payload) {
                self.data = payload && Array.isArray(payload.platforms) && payload.platforms.length ? payload : null;
                self.error = self.data ? '' : 'malformed';
                /* The data-source card is written from this payload, and the nodes a
                   draft restored on a cold page were drawn before it arrived. Redraw
                   them here rather than at each caller, so no entry point (startup,
                   the retry button, a later refresh) can forget it. `canvas` is a
                   top-level const in canvas.js — `window.canvas` would never exist. */
                if (self.data && typeof canvas !== 'undefined' && canvas && canvas.refreshSourceSummaries) {
                    canvas.refreshSourceSummaries();
                }
                return self.data;
            })
            .catch(function (e) {
                self.data = null;
                self.error = (e && e.message) || String(e);
                return null;
            })
            .then(function (result) {
                self.loading = false;
                self._pending = null;
                return result;
            });
        return this._pending;
    },

    ready() {
        return !!this.data;
    },

    platforms() {
        return this.data ? this.data.platforms : [];
    },

    platform(id) {
        var list = this.platforms();
        for (var i = 0; i < list.length; i++) {
            if (list[i].platform === id) return list[i];
        }
        return null;
    },

    modes(id) {
        var entry = this.platform(id);
        return entry ? entry.modes : [];
    },

    /* An unknown or missing mode key resolves to the platform's first mode —
       the same fallback the backend applies, so the panel can never show a form
       the run would not use, and an old canvas opens the mode it will execute. */
    mode(id, key) {
        var modes = this.modes(id);
        for (var i = 0; i < modes.length; i++) {
            if (modes[i].key === key) return modes[i];
        }
        return modes.length ? modes[0] : null;
    },

    fields(id, key) {
        var mode = this.mode(id, key);
        if (!mode) return [];
        return mode.fields.concat((this.data && this.data.fileFields) || []);
    },

    defaults(id) {
        var out = {};
        if (!this.data) return out;
        var modes = this.modes(id);
        for (var i = 0; i < modes.length; i++) {
            var fields = modes[i].fields.concat(this.data.fileFields || []);
            for (var j = 0; j < fields.length; j++) {
                if (!(fields[j].key in out)) out[fields[j].key] = fields[j].default;
            }
        }
        return out;
    },
};
window.Capabilities = Capabilities;

function reloadCapabilities() {
    Capabilities.load().then(function () {
        /* Whoever is watching the panel has to be told the list came back: a
           silent retry that leaves the same note on screen reads as a dead
           button. `canvas` is a top-level const in canvas.js, so it is asked for
           by name — `window.canvas` could never be truthy. */
        if (typeof canvas !== 'undefined' && canvas._settingsNodeId) openSettings(canvas._settingsNodeId);
        showToast(Capabilities.error ? I18n.t('settings.capFailed') : I18n.t('settings.capLoaded'));
    });
}

/* How many platforms in this run want a persistent browser profile and are not
   getting one. Pure on purpose (nodes, settings, matrix in; a count out) so the node
   harness can drive every branch — a pre-run dialog that never appears because it
   read `window.Capabilities` (a top-level const, so never a window property), or
   that fires for an upload-only canvas, is otherwise invisible to tests.

   Returns 0 when profiles are on, when the matrix has not loaded (no claim without
   the facts), and when nothing in the run is flagged. */
function profileNoticeCount(nodes, settings, matrix) {
    if (!settings || settings.use_browser_profile) return 0;
    if (!matrix || !Array.isArray(matrix.platforms)) return 0;
    var wanted = {};
    Object.keys(nodes || {}).forEach(function (id) {
        var node = nodes[id] || {};
        if (node.type !== 'source' && node.type !== 'comment') return;
        var platform = (node.params || {}).platform;
        if (!platform) return;
        matrix.platforms.forEach(function (cap) {
            if (cap.platform === platform && cap.profileRecommended) wanted[platform] = true;
        });
    });
    return Object.keys(wanted).length;
}

/* Which platforms two *different* workflows on this canvas both want to crawl.
 *
 * One browser profile holds one Chrome at a time (chromedriver pre-writes the
 * profile's preferences file, and two sessions created in it together cannot both
 * come up), so a parallel run whose components share a platform is not really two
 * crawls at once — unless it runs without profiles. Returning the platforms rather
 * than a boolean lets the dialog name what will queue.
 *
 * Grouping is by connected component, which is how the backend splits a canvas
 * into workflows: two same-platform nodes inside one component crawl one after the
 * other anyway, and asking the user about that would be a question with no choice
 * behind it. Comment nodes count too — they buy a browser per platform as well.
 */
function profileCollisions(nodes, connections) {
    var ids = Object.keys(nodes || {});
    if (ids.length < 2) return [];
    var parent = {};
    ids.forEach(function (id) { parent[id] = id; });
    function root(id) {
        while (parent[id] !== id) {
            parent[id] = parent[parent[id]];
            id = parent[id];
        }
        return id;
    }
    (connections || []).forEach(function (conn) {
        if (!conn || !parent.hasOwnProperty(conn.from) || !parent.hasOwnProperty(conn.to)) return;
        var a = root(conn.from);
        var b = root(conn.to);
        if (a !== b) parent[b] = a;
    });
    var perComponent = {};
    ids.forEach(function (id) {
        var node = nodes[id] || {};
        if (node.type !== 'source' && node.type !== 'comment') return;
        var platforms = [];
        if (node.type === 'source') {
            if (node.params && node.params.platform) platforms.push(node.params.platform);
        } else {
            String((node.params && node.params.urls) || '')
                .split(/\r?\n/)
                .forEach(function (line) {
                    var platform = line.trim() ? urlPlatform(line.trim()) : '';
                    if (platform) platforms.push(platform);
                });
        }
        var component = root(id);
        platforms.forEach(function (platform) {
            var seen = perComponent[component] || (perComponent[component] = {});
            seen[platform] = true;
        });
    });
    var counted = {};
    Object.keys(perComponent).forEach(function (component) {
        Object.keys(perComponent[component]).forEach(function (platform) {
            counted[platform] = (counted[platform] || 0) + 1;
        });
    });
    return Object.keys(counted).filter(function (platform) { return counted[platform] > 1; }).sort();
}

/* Every control the source panel builds writes exactly one node parameter, and
   the parameter's *name* arrives over the network with the rest of the matrix.
   The handlers are written as inline JS, so a key has to look like an
   identifier: the parity test pins the shape on the Python side, and the guard
   here is what stops a payload that ever stops matching it from becoming a
   script. Values never go through this — they are HTML-escaped where they are
   printed. */
var ID_SHAPE = /^[\w.-]{1,64}$/;

function paramCall(nodeId, key, expr) {
    if (!ID_SHAPE.test(String(nodeId)) || !ID_SHAPE.test(String(key))) return '';
    return "updateParam('" + nodeId + "','" + key + "'," + expr + ')';
}

function numberCall(nodeId, key, fallback) {
    /* The fallback travels as a number the panel itself showed, never as the
       payload's own text: an empty box means "put that back", while a typed 0 is
       a real choice (0 分片 = 不分片, 0 评论预览 = 跳过评论面板) and stays 0. */
    if (!ID_SHAPE.test(String(nodeId)) || !ID_SHAPE.test(String(key))) return '';
    var safe = typeof fallback === 'number' && isFinite(fallback) ? fallback : 0;
    return (
        "updateParam('" +
        nodeId +
        "','" +
        key +
        "',isNaN(parseInt(this.value,10)) ? " +
        safe +
        ' : parseInt(this.value,10))'
    );
}

function reopenCall(nodeId) {
    return ID_SHAPE.test(String(nodeId)) ? ";openSettings('" + nodeId + "')" : '';
}

function sourcePanelHtml(nodeId, p) {
    if (!Capabilities.ready()) {
        return (
            '<div class="settings-group">' +
            '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">' +
            I18n.t('settings.capFailed') +
            '</div>' +
            '<button class="menu-btn" type="button" onclick="reloadCapabilities()">' +
            I18n.t('btn.retry') +
            '</button></div>'
        );
    }
    var platform = String(p.platform || '');
    var mode = Capabilities.mode(platform, p.collect || p.mode);
    var pick = ID_SHAPE.test(String(nodeId)) ? "selectSourcePlatform('" + nodeId + "',this.value)" : '';
    var html = sourceSelectHtml(
        nodeId,
        'settings.platform',
        Capabilities.platforms().map(function (entry) {
            return { value: entry.platform, labelKey: 'platform.' + entry.platform };
        }),
        platform,
        pick
    );
    if (!mode) {
        /* A platform the matrix does not describe cannot be crawled, and the
           run would say so too — but saying it while the panel is open beats
           letting the user fill a form and find out later. */
        return (
            html +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.capNoMode') +
            '</div>'
        );
    }
    if (Capabilities.modes(platform).length > 1) {
        /* One mode is not a choice: WeChat offers a single form, and a select
           with one option only makes the panel look unfinished. */
        html += sourceSelectHtml(
            nodeId,
            'settings.collect',
            Capabilities.modes(platform).map(function (m) {
                return { value: m.key, labelKey: m.labelKey };
            }),
            mode.key,
            paramCall(nodeId, 'collect', 'this.value') + reopenCall(nodeId)
        );
    }
    var fields = Capabilities.fields(platform, mode.key);
    for (var i = 0; i < fields.length; i++) {
        html += sourceFieldHtml(nodeId, fields[i], p[fields[i].key]);
    }
    /* Which platforms a throwaway browser actively fails on is a measured fact about
       the site, so it comes from the matrix (`profileRecommended`) rather than a list
       the panel keeps by hand. The wording depends on the user's own setting, because
       "turn it on" and "it is on, now log into it" are different next steps. */
    var capEntry = Capabilities.platform(platform);
    if (capEntry && capEntry.profileRecommended) {
        var values = (window.AppSettings && AppSettings._values) || {};
        html +=
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">' +
            I18n.t(values.use_browser_profile ? 'settings.profileOnHint' : 'settings.profileOffHint') +
            '</div>';
        if (ID_SHAPE.test(String(nodeId))) {
            html += '<button class="menu-btn" type="button" onclick="openSettings(\'' + nodeId + '\');toggleSettingsMenu()">' + I18n.t('settings.profileGo') + '</button>';
        }
        html += '</div>';
    }
    if (mode.noteKey) {
        html +=
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">' +
            I18n.t(mode.noteKey) +
            '</div>';
        /* A button the page cannot service is worse than no button, and the name
           arrives over the network: it has to both look like a function name and
           resolve to one before it is wired to a click. */
        if (mode.actionKey && ID_SHAPE.test(String(mode.actionJs)) && typeof window[mode.actionJs] === 'function') {
            html +=
                '<button class="menu-btn" type="button" onclick="' +
                escapeHtml(mode.actionJs) +
                '()">' +
                I18n.t(mode.actionKey) +
                '</button>';
        }
        html += '</div>';
    }
    return html;
}

function sourceSelectHtml(nodeId, labelKey, options, value, onChange) {
    if (!onChange) return '';
    var html =
        '<div class="settings-group"><label class="settings-label">' +
        I18n.t(labelKey) +
        '</label><select class="settings-select" onchange="' +
        onChange +
        '">';
    for (var i = 0; i < options.length; i++) {
        html +=
            '<option value="' +
            escapeHtml(options[i].value) +
            '"' +
            (options[i].value === value ? ' selected' : '') +
            '>' +
            I18n.t(options[i].labelKey) +
            '</option>';
    }
    return html + '</select></div>';
}

function sourceFieldHtml(nodeId, f, value) {
    if (!ID_SHAPE.test(String(f.key))) return '';
    var v = value === undefined || value === null || value === '' ? f.default : value;
    var hint = sourceFieldHint(f);
    var tail = hint ? '<div style="font-size:11px;color:var(--text-dim);">' + hint + '</div>' : '';
    if (f.control === 'checkbox') {
        /* The label wraps the box on purpose: a 12px caption beside a checkbox is
           a click target, and the panel's other toggles already work that way. */
        return (
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' +
            (v ? 'checked' : '') +
            ' onchange="' +
            paramCall(nodeId, f.key, 'this.checked') +
            '">' +
            I18n.t(f.labelKey) +
            '</label>' +
            tail +
            '</div>'
        );
    }
    var label = '<label class="settings-label">' + I18n.t(f.labelKey) + '</label>';
    var input;
    if (f.control === 'textarea') {
        input =
            '<textarea class="settings-input" rows="5" placeholder="' +
            escapeHtml(f.placeholder || '') +
            '" onchange="' +
            paramCall(nodeId, f.key, 'this.value') +
            '">' +
            escapeHtml(v) +
            '</textarea>';
    } else if (f.control === 'number') {
        input =
            '<input class="settings-input" type="number"' +
            (f.minimum != null ? ' min="' + parseInt(f.minimum, 10) + '"' : '') +
            (f.maximum != null ? ' max="' + parseInt(f.maximum, 10) + '"' : '') +
            ' value="' +
            escapeHtml(v) +
            '" onchange="' +
            numberCall(nodeId, f.key, f.default) +
            '">';
    } else if (f.control === 'select') {
        var html = sourceSelectHtml(
            nodeId,
            f.labelKey,
            f.options.map(function (o) {
                return { value: o.value, labelKey: o.labelKey };
            }),
            String(v),
            paramCall(nodeId, f.key, 'this.value')
        );
        return hint ? html + '<div class="settings-group">' + tail + '</div>' : html;
    } else {
        input =
            '<input class="settings-input" value="' +
            escapeHtml(v) +
            '" placeholder="' +
            escapeHtml(f.placeholder || '') +
            '" onchange="' +
            paramCall(nodeId, f.key, 'this.value') +
            '">';
    }
    return '<div class="settings-group">' + label + input + tail + '</div>';
}

function sourceFieldHint(f) {
    if (f.hintKey) return I18n.t(f.hintKey);
    if (f.linksOf) {
        /* The selected platform decides what a usable link looks like, so the
           panel names it instead of listing every site's URL shape at once. */
        return I18n.t('settings.commentUrlsHintPlat').replace('{plat}', I18n.t('platform.' + f.linksOf));
    }
    return '';
}

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
        /* The form is the matrix: which platforms exist, which of them want
           links instead of a keyword, and every field in between come from
           /api/capabilities (see Capabilities above), so the panel and the
           executor cannot disagree about what a platform offers. */
        html += sourcePanelHtml(nodeId, node.params);
    } else if (node.type === 'comment') {
        /* Source-like crawler: article links go in, comment rows come out. The
           panel mirrors the WeChat source block (a multi-line textarea) and the
           recrawl checkbox markup, because zhihu comment pages refuse headless
           sessions — so the hint has to warn that a visible window opens. */
        var p = node.params;
        /* The legacy standalone Comment node (kept for older canvases) has no
           platform selector — each link is dispatched by its own domain, so
           the hint says the mix is deliberate, not an oversight. */
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentUrls') + '</label>' +
            '<textarea class="settings-input" rows="5" placeholder="https://www.zhihu.com/question/... &#10;https://weibo.com/... &#10;https://www.xiaohongshu.com/explore/..." ' +
            'onchange="updateParam(\'' + nodeId + '\',\'urls\',this.value)">' + escapeHtml(p.urls || '') + '</textarea>' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentUrlsHintMixed') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentLimit') + '</label>' +
            '<input class="settings-input" type="number" min="0" value="' + (p.comment_limit != null ? p.comment_limit : 0) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_limit\',parseInt(this.value)||0)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentLimitHint') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.partSize') + '</label>' +
            '<input class="settings-input" type="number" min="0" value="' + (p.part_size != null ? p.part_size : 50) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'part_size\',parseInt(this.value)||0)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.partSizeHint') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.format') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'format\',this.value)">' +
            ['csv', 'json'].map(function (f) {
                return '<option value="' + f + '"' + ((p.format || 'csv') === f ? ' selected' : '') + '>' + I18n.t('format.' + f) + '</option>';
            }).join('') +
            '</select></div>' +
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (p.per_article_file ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'per_article_file\',this.checked)">' + I18n.t('settings.perArticleFile') + '</label></div>' +
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (p.keep_parts ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'keep_parts\',this.checked)">' + I18n.t('settings.keepParts') + '</label></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentHint') + '</div>';
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

        /* Named entities. The rules need no model and stay the default; the
           model is for texts that name people and places without any of the
           surface cues the regexes look for. The category filter applies to
           both, so asking for persons only costs persons only. */
        if (p.operation === 'ner') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'regex',
                [{ v: 'regex', l: I18n.t('mode.regex') }, { v: 'llm', l: I18n.t('mode.llm') }]);
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.entityTypes') +
                '</label><input class="settings-input" value="' + escapeHtml(p.entity_types || '') + '" placeholder="' +
                I18n.t('settings.entityTypesPlaceholder') + '" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'entity_types\',this.value)">' +
                '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.entityTypesHint') +
                '</div></div>';
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

        /* AI 调用实时导出: the LLM ops rewrite a {stem}.live.{ext} snapshot
           after every settled batch — watch the enriched rows grow without
           waiting for the node (or the run) to finish. */
        var isLlmOp = nodeNeedsLlm(p, node.operation);
        if (isLlmOp) {
            html += '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
                '<input type="checkbox" ' + (p.live_export ? 'checked' : '') + ' ' +
                'onchange="updateParam(\'' + nodeId + '\',\'live_export\',this.checked)">' + I18n.t('settings.liveExport') + '</label>' +
                '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.liveExportHint') + '</div></div>';
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

/* ── Which process nodes really call a model ──
 * The run-gate and the AI 实时导出 checkbox used to spell this rule out
 * separately, and the two had already begun to drift. backend/app.py
 * (_workflow_needs_llm) keeps the same list, because a workflow that never
 * reaches a model must not be blocked by a missing API key or an unpicked
 * Ollama tag. Note the opposite defaults: emotion/tendency ask the model
 * unless told not to, NER uses its rules unless told otherwise. The second
 * argument is the node's own ``operation``, which toWorkflowJSON also carries:
 * the backend reads that one first, so this has to as well. */
function nodeNeedsLlm(params, nodeOperation) {
    var p = params || {};
    var op = p.operation || nodeOperation || '';
    if (op === 'clean') return true;
    if (op === 'emotion' || op === 'tendency') return p.mode !== 'ml';
    if (op === 'ner') return p.mode === 'llm';
    return false;
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
    if (op === 'drop_null') {
        /* 'any' drops a row with one empty cell, 'all' only when every selected
           cell is empty — the two produce very different tables, so the choice
           has to be on the panel and not buried in a default. */
        html += renderParamSelect(nodeId, p, 'how', 'settings.dropHow', 'any',
            [{ v: 'any', l: I18n.t('settings.dropHowAny') }, { v: 'all', l: I18n.t('settings.dropHowAll') }]);
    }
    if (op === 'fill_null') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + (p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
        /* A method and a literal value are different operations; leaving method
           empty means "fill with the value above". */
        html += renderParamSelect(nodeId, p, 'method', 'settings.fillMethod', '',
            [{ v: '', l: I18n.t('settings.fillMethodValue') }, { v: 'ffill', l: 'ffill' }, { v: 'bfill', l: 'bfill' }]);
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
        /* One integer = that many equal-width buckets; a comma-separated list =
           those exact edges. The backend tells the two apart by shape. */
        html += renderParamInput(nodeId, p, 'bins', 'settings.binEdges', 'text', '4 或 0, 60, 80, 100');
        html += renderParamInput(nodeId, p, 'bin_labels', 'settings.binLabels', 'text', 'low, mid, high');
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
        if (payload.node_id) {
            /* Which workflow's rows this is: recorded rows are looked up by name
               once the live results are gone (a refresh, a server restart). */
            payload.workflow_name = workflow.runName();
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
            /* Bound once, on the container, because the rows are replaced by
               every reload: a listener per button would pile up one per refresh
               and a deleted row's button would still be listening. */
            var runsWrap = document.getElementById('history-runs-wrap');
            if (runsWrap && !runsWrap.dataset._delBound) {
                runsWrap.dataset._delBound = '1';
                runsWrap.addEventListener('click', function (e) {
                    var button = e.target && e.target.closest ? e.target.closest('.history-del') : null;
                    if (!button) return;
                    historyPanel.deleteRun(button.getAttribute('data-run-id'));
                });
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
                '<th></th>' +
                '</tr></thead><tbody>';
            result.runs.forEach(function (r) {
                /* The id goes into a data attribute, not into an inline handler:
                   it is database text, and one quote would end the attribute and
                   start whatever the user typed next. */
                html += '<tr><td>' + escapeHtml(r.run_id) + '</td><td>' + escapeHtml(r.workflow_name || '') + '</td>' +
                    '<td>' + escapeHtml(r.started_at) + '</td><td>' + r.metric_count + '</td>' +
                    '<td class="history-ops"><button class="history-del" data-run-id="' + escapeHtml(r.run_id) +
                    '">' + I18n.t('history.remove') + '</button></td></tr>';
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

    async deleteRun(runId) {
        var id = String(runId || '').trim();
        if (!id) return;
        var confirmed = await showDialog({
            message: I18n.t('history.confirmRemove').replace('{rid}', id),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('dialog.confirm'), value: true, primary: true },
            ],
        });
        if (!confirmed) return;
        try {
            var resp = await fetch('/api/history/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: id }),
            });
            var result = await resp.json();
            if (!result.ok) {
                showToast(I18n.t('history.removeFailed') + ': ' + (result.error || ''));
                return;
            }
            /* Zero deleted rows is reported, not hidden: the list on screen was
               loaded before this click, and a run aged out by the retention
               policy in between is a different fact than "deleted". */
            showToast(result.deleted ? I18n.t('history.removed') : I18n.t('history.removeGone'));
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

/* ─── Data Source platform helpers (mirror the backend's routing rules) ───
   urlPlatform duplicates crawlers/comments.py:platform_for on purpose: the
   designer must reject a wrong-platform link before the run, and the engine
   rejects it at crawl time — the two answers have to agree. The frontend
   contract test pins the table against the Python one. */
/* The host of a link, the way the backend's _host_of does it: the domain table
   below is matched against the authority, never against the whole URL. Matching
   the whole string would route "https://example.com/weibo.com/x" to Weibo, and
   'x.com' is a substring of 'max.com' — so a link could be crawled as the wrong
   platform and land in the user's table wearing the wrong site's name. */
function urlHost(url) {
    var text = String(url || '').toLowerCase().trim();
    if (!text) return '';
    var tail = text.indexOf('://') !== -1 ? text.split('://')[1] : text;
    tail = tail.split('/')[0].split('?')[0].split(':')[0];
    return tail.trim();
}

function urlPlatform(url) {
    var host = urlHost(url);
    if (!host) return '';
    var TABLE = [
        ['zhihu', ['zhihu.com']],
        ['xiaohongshu', ['xiaohongshu.com', 'xhslink.com']],
        ['weibo', ['weibo.com', 'weibo.cn']],
        ['bilibili', ['bilibili.com']],
        ['douyin', ['douyin.com', 'iesdouyin.com']],
        ['youtube', ['youtube.com', 'youtu.be']],
        ['twitter', ['x.com', 'twitter.com', 'fxtwitter.com', 'vxtwitter.com']],
    ];
    for (var i = 0; i < TABLE.length; i++) {
        for (var j = 0; j < TABLE[i][1].length; j++) {
            var domain = TABLE[i][1][j];
            if (host === domain || host.slice(-domain.length - 1) === '.' + domain) return TABLE[i][0];
        }
    }
    return '';
}

/* One example shape per platform — the comments textarea must not suggest
   that links from the other sites are acceptable when a platform is chosen. */
/* Changing the site can drop the mode: the matrix decides what each platform
   offers, so a comments flag carried over from a platform that has no comment
   adapter is rewritten to the new platform's first mode rather than left to sit
   in the saved JSON claiming a crawl that does not exist. updateParam re-opens
   the panel by itself, so only the state has to be fixed here. */
function selectSourcePlatform(nodeId, value) {
    var node = canvas.nodes[nodeId];
    if (node && node.params && Capabilities.ready() && node.params.collect) {
        node.params.collect = Capabilities.mode(value, node.params.collect).key;
    }
    updateParam(nodeId, 'platform', value);
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
    /* The run-records table is JS-rendered, so I18n.apply() never reaches it —
       if the panel is open, redraw it in the new language right away instead
       of only after the next open. */
    if (window.runsManager) runsManager.onLanguageChange();
    if (window.exportsManager) exportsManager.onLanguageChange();
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
    if (!panel.classList.contains('open')) {
        /* Opening the console from the button must clear the other two docked
           panels; only run-records was cleared before, so 导出产物 stayed open
           underneath and the two overlapped. */
        closeDockedPanels('console-panel');
    }
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
    /* Every view's history goes with it, and no cursor moves: "clear" means the
       user wants the NEXT line, not a replay of the up-to-200 the server still
       holds. Leaving one view's lines behind would have a tab switch repaint what
       was just deleted, which is the opposite of clearing. */
    consoleViews.all.lines = [];
    Object.keys(consoleViews.wf).forEach(function (key) {
        consoleViews.wf[key].lines = [];
    });
    _wfActiveTab = 'all';
}

/* Workflow tab switching for parallel mode */
var _wfActiveTab = 'all';
function switchWfTab(wfId) {
    _wfActiveTab = wfId;
    /* Repainted from the view's own history rather than emptied: the server holds
       only the tail of the whole run, so a blank box here read as "switching tabs
       deletes the console". The cursor stays put, so the next poll appends only
       what is genuinely new to this view. */
    repaintConsoleView(document.getElementById('console-output'), wfId);
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
                showToast(I18n.t('toast.killFailed') + ': ' + (result.error || ''));
            }
        })
        .catch(function (err) {
            showToast(I18n.t('toast.killFailed') + ': ' + err.message);
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
                    '<td>' + escapeHtml(t.name) + '</td>' +
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
                    /* A dialog that asks for a text AND offers two ways to use it
                       (the report: plain, or with an AI conclusion) would
                       otherwise lose one of them — resolving a declared `value`
                       throws the typed text away, and resolving the text loses
                       which button was pressed. `withInput` returns both. */
                    if (b.withInput && opts.input) {
                        resolve({ value: b.value, input: inputEl.value });
                        return;
                    }
                    resolve(b.value !== undefined ? b.value : (opts.input ? inputEl.value : true));
                });
                actionsEl.appendChild(btn);
            });
        }

        overlay.classList.add('open');
        if (opts.input) setTimeout(function () { inputEl.focus(); inputEl.select(); }, 100);
    });
}

/* Every cookie-panel call shares one guard: a refused connection (the debug
   server restarting) or an HTML error page used to surface as
   'Uncaught (in promise) TypeError: Failed to fetch' in the console and
   nothing on screen. This always resolves to a plain {ok, error} object —
   callers only render. */
function fetchJSON(url, options) {
    return fetch(url, options)
        .then(function (r) {
            return r.text().then(function (txt) {
                var body = null;
                try { body = txt ? JSON.parse(txt) : null; } catch (e) { body = null; }
                if (body && typeof body === 'object') return body;
                return { ok: false, error: 'HTTP ' + r.status };
            });
        })
        .catch(function (e) {
            return { ok: false, error: (e && e.message) || String(e), unreachable: true };
        });
}

/* Cookie Configuration — driven by the server-side single-flight login job.
   The browser opens server-side and the job lives in app state; this dialog
   polls its status, offers Done/Cancel, and REFUSES to close while a login is
   waiting: the dialog's buttons are the only way to finish or abort that
   browser, and closing it used to leave the login window orphaned. */
var cookieJob = { active: false, known: false, timer: null, platform: '', kind: 'login' };
/* The server owns the guidance (translated, and next to the code that enforces
   which link is acceptable), so it is fetched once and rendered from cache. */
var cookieFlows = null;

function renderCookieGuide() {
    var body = document.getElementById('cookie-guide-body');
    if (!body) return;
    var platform = document.getElementById('cookie-platform').value;
    if (!cookieFlows) {
        body.textContent = I18n.t('cookie.guideLoading');
        fetchJSON('/api/cookies/flow').then(function (result) {
            if (!result.ok) {
                body.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
                return;
            }
            var byName = {};
            result.flows.forEach(function (flow) {
                byName[flow.platform] = flow;
            });
            cookieFlows = byName;
            renderCookieGuide();
        });
        return;
    }
    var flow = cookieFlows[platform];
    if (!flow) {
        body.textContent = '';
        return;
    }
    var lines = [flow.purpose];
    flow.steps.forEach(function (step) {
        lines.push(step);
    });
    body.textContent = '';
    lines.forEach(function (line) {
        var row = document.createElement('div');
        row.className = 'cookie-guide-line';
        row.textContent = line;
        body.appendChild(row);
    });
    /* The entry field only means something when the platform's cookie can be
       captured from a page the user chooses — WeChat above all. */
    var entry = document.getElementById('cookie-entry');
    if (entry) {
        entry.disabled = !flow.accepts_custom_url;
        entry.placeholder = flow.login_url || 'https://…';
    }
}

function refreshCookieStatus() {
    fetchJSON('/api/cookies/status').then(function (result) {
        var statusEl = document.getElementById('cookie-status');
        if (!statusEl || cookieJob.active) return;
        if (result.ok) {
            var lines = [];
            Object.keys(result.cookies).forEach(function (p) {
                lines.push(p + ': ' + (result.cookies[p] ? 'OK' : '-'));
            });
            statusEl.textContent = lines.join('  |  ');
        } else {
            statusEl.textContent = I18n.t('cookie.unreachable');
        }
    });
}

function setCookieJobUI(on) {
    var actions = document.getElementById('cookie-job-actions');
    /* A verification resolves itself — showing "Done — I logged in" over it
       would invite a click that means nothing (and the server refuses it). */
    if (actions) actions.style.display = on && cookieJob.kind === 'login' ? 'flex' : 'none';
    ['cookie-platform', 'cookie-wait', 'cookie-json', 'cookie-entry'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.disabled = !!on;
    });
    var buttons = document.querySelectorAll('#cookie-content button');
    for (var i = 0; i < buttons.length; i++) {
        if (!buttons[i].closest('#cookie-job-actions')) buttons[i].disabled = !!on;
    }
}

function pollCookieJob() {
    fetchJSON('/api/cookies/generate/status').then(function (s) {
        if (!s.ok) return;
        var statusEl = document.getElementById('cookie-status');
        if (s.active) {
            cookieJob.active = true;
            cookieJob.known = true;
            cookieJob.platform = s.platform;
            cookieJob.kind = s.kind || 'login';
            setCookieJobUI(true);
            if (statusEl) {
                statusEl.textContent =
                    cookieJob.kind === 'verify'
                        ? I18n.t('cookie.verifying')
                        : I18n.t('cookie.waiting').replace('{platform}', s.platform);
            }
            return;
        }
        clearInterval(cookieJob.timer);
        cookieJob.timer = null;
        if (!cookieJob.known) {
            cookieJob.active = false;
            setCookieJobUI(false);
            return;
        }
        cookieJob.active = false;
        cookieJob.known = false;
        setCookieJobUI(false);
        if (!statusEl) return;
        if (s.phase === 'saved') {
            statusEl.textContent = I18n.t('cookie.savedN').replace('{platform}', s.platform).replace('{n}', s.count);
            showToast(I18n.t('toast.cookiesSaved') + ' - ' + s.platform);
            refreshCookieStatus();
        } else if (s.phase === 'verified') {
            statusEl.textContent = (s.lines || []).join('\n');
        } else if (s.phase === 'cancelled') {
            statusEl.textContent = I18n.t('cookie.cancelledMsg').replace('{platform}', s.platform);
        } else if (s.phase === 'error') {
            statusEl.textContent = I18n.t('cookie.failed').replace('{err}', s.error || '');
        }
    });
}

function openCookieDialog() {
    var dialog = document.getElementById('cookie-dialog');
    dialog.classList.toggle('open');
    if (!dialog.classList.contains('open')) return;
    renderCookieGuide();
    /* Adopt a job that is already running (started before the dialog was
       closed/reopened, or from another tab of this page). */
    fetchJSON('/api/cookies/generate/status').then(function (s) {
        if (s.ok && s.active) {
            cookieJob.active = true;
            cookieJob.known = true;
            cookieJob.platform = s.platform;
            cookieJob.kind = s.kind || 'login';
            setCookieJobUI(true);
            if (!cookieJob.timer) cookieJob.timer = setInterval(pollCookieJob, 1000);
        }
    });
    refreshCookieStatus();
}

function closeCookieDialog() {
    if (cookieJob.active) {
        /* While a login browser waits, this dialog's Done/Cancel buttons are
           the only way to resolve it — closing here would orphan that browser
           (and its driver process) with nobody watching. */
        showToast(I18n.t('cookie.mustStay'));
        return;
    }
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
        fetchJSON('/api/cookies/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: platform, cookies: cookies }),
        })
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

function cookieEntryUrl() {
    var el = document.getElementById('cookie-entry');
    return el ? String(el.value || '').trim() : '';
}

function startCookiePolling() {
    cookieJob.active = true;
    cookieJob.known = true;
    setCookieJobUI(true);
    if (!cookieJob.timer) cookieJob.timer = setInterval(pollCookieJob, 1000);
}

function generateCookie() {
    if (cookieJob.active) return;  // single-flight: one login browser at a time
    var platform = document.getElementById('cookie-platform').value;
    var waitSeconds = parseInt(document.getElementById('cookie-wait').value) || 120;
    var statusEl = document.getElementById('cookie-status');
    statusEl.textContent = I18n.t('cookie.opening')
        .replace('{platform}', platform)
        .replace('{s}', waitSeconds);
    fetchJSON('/api/cookies/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, wait_seconds: waitSeconds, url: cookieEntryUrl() }),
    })
        .then(function (result) {
            if (result.ok) {
                cookieJob.platform = platform;
                cookieJob.kind = 'login';
                startCookiePolling();
                if (result.entry_rejected) {
                    /* The window is opening on the platform page instead — say
                       so, or the user logs into the wrong thing believing they
                       pasted a working link. */
                    showToast(result.entry_note || I18n.t('cookie.entryRejected'));
                }
            } else {
                statusEl.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
                if (result.busy) {
                    /* Another login is in flight (this tab or an earlier one):
                       adopt it so its Done/Cancel buttons appear here. */
                    startCookiePolling();
                }
            }
        });
}

function verifyCookie() {
    if (cookieJob.active) return;  // same single-flight as a login
    var platform = document.getElementById('cookie-platform').value;
    var statusEl = document.getElementById('cookie-status');
    statusEl.textContent = I18n.t('cookie.verifying');
    fetchJSON('/api/cookies/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, url: cookieEntryUrl() }),
    }).then(function (result) {
        if (result.ok) {
            cookieJob.platform = platform;
            cookieJob.kind = 'verify';
            startCookiePolling();
            return;
        }
        cookieJob.kind = 'login';
        statusEl.textContent = result.error || I18n.t('cookie.failed').replace('{err}', '');
        if (result.busy) startCookiePolling();
    });
}

/* Why WeChat stops at the article body. Kept as one dialog rather than a
   disabled control with no reason: the platform's limit is a fact about the
   site, and the honest answer is shorter than the confusion of an empty box. */
function explainWechatLimits() {
    showDialog({
        message: I18n.t('settings.wechatLimitsBody'),
        buttons: [{ label: I18n.t('settings.close'), value: 'ok', primary: true }],
    });
}

function confirmCookieLogin() {
    fetchJSON('/api/cookies/generate/confirm', { method: 'POST' }).then(function (result) {
        var statusEl = document.getElementById('cookie-status');
        if (!result.ok && statusEl) {
            statusEl.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
        }
        /* Otherwise the 1s poll picks up the capture and settles the dialog. */
    });
}

function cancelCookieLogin() {
    fetchJSON('/api/cookies/generate/cancel', { method: 'POST' }).then(function (result) {
        var statusEl = document.getElementById('cookie-status');
        if (!result.ok && statusEl) {
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
        /* The guard has to name the binding that exists. `canvas` is a top-level
           `const`, which never becomes a property of `window`, so `window.canvas`
           read as undefined forever and this function hid the banner and returned
           before asking the server — 断点续跑 had no entry point in the UI at all.
           What the check is for is an empty canvas: with nothing on it there is no
           workflow shape to match a stored run against. */
        if (!canvas || !Object.keys(canvas.nodes || {}).length) {
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
        /* Same bottom slot as the console and the export list — none stack. */
        if (opening) {
            closeDockedPanels('runs-panel');
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
            this._lastRuns = (result.ok && result.runs) || [];
            /* Waiting requests come back with the records: the panel that shows
               what has run is where someone looks for what has not started. */
            this._queue = (result.ok && result.queue) || [];
            this.render(this._lastRuns);
        } catch (e) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('runsMgr.empty') + '</div>';
        }
    },

    refreshIfOpen() {
        var panel = this.panel();
        if (panel && panel.classList.contains('open')) this.refresh();
    },

    /* The waiting list, drawn above the finished records. Each row can only be
       cancelled — starting it sooner would break the one-writer rule the whole
       checkpoint design rests on. */
    _queueBlock() {
        var queue = this._queue || [];
        if (!queue.length) return '';
        var rows = queue.map(function (entry, index) {
            return '<tr>' +
                '<td>' + (index + 1) + '</td>' +
                '<td class="runs-mgr-wf">' + escapeHtml(entry.workflow_name || I18n.t('name.unnamed')) + '</td>' +
                '<td>' + escapeHtml(String(entry.nodes || 0)) + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(entry.queued_at || '') + '</td>' +
                '<td class="runs-mgr-ops"><button class="runs-mgr-btn del" onclick="runsManager.cancelQueued(\'' +
                entry.id + '\')">' + I18n.t('runsMgr.queueCancel') + '</button></td>' +
                '</tr>';
        }).join('');
        return '<div class="runs-mgr-empty">' +
            I18n.t('runsMgr.queueHeader').replace('{n}', queue.length) +
            '</div><table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>#</th><th>' + I18n.t('runsMgr.colWorkflow') + '</th>' +
            '<th>' + I18n.t('runsMgr.colNodes') + '</th>' +
            '<th>' + I18n.t('runsMgr.colStarted') + '</th><th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>';
    },

    async cancelQueued(queueId) {
        try {
            var resp = await fetch('/api/workflow/queue/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: queueId }),
            });
            var result = await resp.json();
            showToast(result.removed ? I18n.t('runsMgr.queueCancelled') : I18n.t('runsMgr.queueGone'));
        } catch (e) {
            showToast(I18n.t('runsMgr.queueCancelFailed'));
        }
        this.refresh();
    },

    /* Language switch: the table text is JS-built, so an open panel must be
       redrawn now. Re-render from the cached rows — no refetch needed, the
       data itself did not change, only its wording. */
    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        if (this._lastRuns) this.render(this._lastRuns);
        else this.refresh();
    },

    statusKey(status) {
        var known = ['running', 'interrupted', 'completed', 'failed', 'abandoned'];
        return known.indexOf(status) >= 0 ? 'runsMgr.status.' + status : 'runsMgr.status.completed';
    },

    /* What kind of run this was, as chips beside the name: several workflows in one
       record (并行), and which window it crawled in. Both are stored facts, not
       guesses — and they matter when a record from last week is being read back:
       a visible-window crawl and a headless one fail differently. */
    tags(r) {
        var out = [];
        if ((r.wf_count || 1) > 1) out.push(I18n.t('runsMgr.tagParallel').replace('{n}', r.wf_count));
        out.push(I18n.t(r.headless ? 'runsMgr.tagHeadless' : 'runsMgr.tagWindow'));
        return out;
    },

    render(runs) {
        /* Remembered so a button can ask "which workflow is this row?" without
           the answer having to be woven into its onclick attribute. */
        this._shown = runs || [];
        var body = document.getElementById('runs-mgr-body');
        var count = document.getElementById('runs-mgr-count');
        if (!body) return;
        if (count) count.textContent = runs.length ? '(' + runs.length + ')' : '';
        /* Drawn first and kept in both branches: a queue can exist on a machine
           that has no finished records at all, and hiding it there would hide
           the one request the user is waiting for. */
        var queue = this._queueBlock();
        if (!runs.length) {
            body.innerHTML = queue + '<div class="runs-mgr-empty">' + I18n.t('runsMgr.empty') + '</div>';
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
            /* The stored tables are what a report needs, so a run from last week
               is reportable from here. Only the run id travels into the handler:
               a workflow name is user text, and a quote in it would close this
               attribute and start a new one. */
            ops += '<button class="runs-mgr-btn" onclick="runsManager.report(\'' + r.run_id + '\')">' + I18n.t('runsMgr.report') + '</button>';
            var tags = runsManager.tags(r).map(function (text) {
                return '<span class="runs-mgr-tag">' + escapeHtml(text) + '</span>';
            }).join('');
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(r.workflow_name || I18n.t('name.unnamed')) + tags + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(r.run_id) + '</td>' +
                '<td><span class="runs-mgr-status st-' + escapeHtml(r.status || '') + '">' + I18n.t(runsManager.statusKey(r.status)) + '</span></td>' +
                '<td>' + (r.node_done || 0) + '/' + (r.node_total || 0) + '</td>' +
                '<td>' + (r.rows_kept || 0) + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(r.started_at || '') + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            queue +
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
        /* Same trap as resumeBar.refresh(): RunState is a `const` in app.js, so
           `window.RunState` was undefined and this returned false even mid-run —
           继续/重新开始 would close the panel and start a second attempt at the same
           data instead of saying "wait". `typeof` keeps the degradation the guard
           was written for (app.js missing) without pretending to read a property
           that does not exist. */
        if (typeof RunState !== 'undefined' && RunState.running) {
            showToast(I18n.t('runsMgr.busy'));
            return true;
        }
        return false;
    },

    /* A report for this stored run. The name is read back out of the rows the
       panel is already holding, because it is only the dialog's starting
       suggestion — it must not have to survive a trip through an inline
       handler, where one quote in a workflow name would close the attribute. */
    report(runId) {
        var row = (this._shown || []).filter(function (r) {
            return r.run_id === runId;
        })[0] || {};
        exportsManager.report(runId, row.workflow_name || '');
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

    /* Node status → badge colour class + i18n key. Node statuses are their
       own vocabulary (done/partial/skipped/restored …), distinct from the
       run statuses above. */
    nodeStatusInfo(status) {
        var map = {
            done: 'st-completed',
            restored: 'st-completed',
            running: 'st-running',
            partial: 'st-interrupted',
            failed: 'st-failed',
            skipped: 'st-skipped',
            pending: 'st-skipped',
        };
        var known = ['pending', 'running', 'done', 'partial', 'failed', 'skipped', 'restored'];
        var s = String(status || '');
        return {
            cls: map[s] || 'st-completed',
            key: known.indexOf(s) >= 0 ? 'runsMgr.node.' + s : 'runsMgr.node.done',
        };
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
            var self = this;
            var cards = (run.nodes || []).map(function (n) {
                var info = self.nodeStatusInfo(n.status);
                var typeLabel = n.node_type
                    ? I18n.t('nodeType.' + n.node_type)
                    : '';
                return '<div class="rm-node nt-' + escapeHtml(n.node_type || 'misc') + '">' +
                    '<div class="rm-node-head">' +
                    '<span class="rm-node-id">' + escapeHtml(n.node_id || '') + '</span>' +
                    '<span class="rm-node-type">' + escapeHtml(typeLabel) + '</span>' +
                    '<span class="runs-mgr-status ' + info.cls + '">' + I18n.t(info.key) + '</span>' +
                    '<span class="rm-node-rows">' + (n.row_count || 0) + ' ' + I18n.t('runsMgr.colRows') + '</span>' +
                    '</div>' +
                    (n.error ? '<div class="rm-node-err">' + escapeHtml(n.error) + '</div>' : '') +
                    '</div>';
            }).join('');
            var tr = document.createElement('tr');
            tr.id = 'runs-mgr-detail-' + runId;
            tr.innerHTML = '<td colspan="7" class="runs-mgr-detail">' +
                '<div class="rm-meta">' +
                '<span class="rm-meta-title">' + I18n.t('runsMgr.detailNodes') + '</span>' +
                '<span class="runs-mgr-status ' + this.nodeStatusInfo(run.status).cls + '">' +
                I18n.t(this.statusKey(run.status)) + '</span>' +
                '<span class="rm-meta-time">' + escapeHtml(run.started_at || '') +
                (run.finished_at ? ' &rarr; ' + escapeHtml(run.finished_at) : '') +
                '</span>' +
                (run.note ? '<span class="rm-meta-note">' + escapeHtml(run.note) + '</span>' : '') +
                '</div>' +
                '<div class="rm-nodes">' +
                (cards || '<div class="runs-mgr-empty">' + I18n.t('runsMgr.noNodes') + '</div>') +
                '</div>' +
                '</td>';
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
        /* Old saved workflows can carry title:null — the message must still
           name the node (type label + id), never read 'node "null"'. */
        var label = node.title || I18n.t('node.' + type);

        if (type === 'source') {
            var commentsMode = params.collect === 'comments' && params.platform !== 'wechat';
            if (commentsMode) {
                /* Comments mode: links are the input — a keyword would be
                   silently ignored, exactly like WeChat's rule below. Each
                   pasted line must also belong to the selected platform — the
                   engine refuses others at crawl time; say it before the run. */
                var lines = String(params.urls || '').replace(/,/g, '\n').split(/\r?\n/).filter(function (s) {
                    return s.trim();
                });
                if (!lines.length) {
                    errors.push(I18n.t('validate.sourceCommentUrls').replace('{title}', label));
                } else if (params.platform) {
                    var bad = lines.filter(function (u) {
                        return urlPlatform(u) !== params.platform;
                    }).length;
                    if (bad) {
                        errors.push(I18n.t('validate.sourceCommentPlat')
                            .replace('{title}', label)
                            .replace('{n}', bad)
                            .replace('{plat}', I18n.t('platform.' + params.platform)));
                    }
                }
            } else if (params.platform === 'wechat') {
                /* WeChat crawls the article URLs you paste; a keyword would be
                   ignored, so asking for one (as this used to) both blocked a
                   valid workflow and left the platform unusable. */
                if (!params.urls || !String(params.urls).trim()) {
                    errors.push(I18n.t('validate.sourceUrls').replace('{title}', label));
                }
            } else if (!params.keyword || !params.keyword.trim()) {
                errors.push(I18n.t('validate.sourceKeyword').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.sourceDownstream').replace('{title}', label));
            }
        }

        if (type === 'process') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.processInput').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.processDownstream').replace('{title}', label));
            }
        }

        if (type === 'analysis') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.analysisInput').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.analysisDownstream').replace('{title}', label));
            }
            if (!params.operation) {
                errors.push(I18n.t('validate.analysisOperation').replace('{title}', label));
            }
            if (params.operation === 'join_tables' && (inputCount[id] || 0) < 2) {
                /* The right-hand table is the node's second incoming
                   connection — without it the join has nothing to join with. */
                errors.push(I18n.t('validate.joinNeedsTwo').replace('{title}', label));
            }
        }

        if (type === 'upload') {
            /* A source like any other: nothing upstream, but it must have a file. */
            if (!params.dataset_id) {
                errors.push(I18n.t('validate.uploadFile').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.uploadDownstream').replace('{title}', label));
            }
        }

        if (type === 'name') {
            /* The name node is metadata, not data: it must sit at the head of
               the workflow (no incoming edges), wire into something, and
               carry a non-empty label — that label is what groups the run in
               the Execution History panel. */
            if (!params.workflow_name || !String(params.workflow_name).trim()) {
                errors.push(I18n.t('validate.nameEmpty').replace('{title}', label));
            }
            if (hasInput[id]) {
                errors.push(I18n.t('validate.nameMustLead').replace('{title}', label));
            }
            if (!hasOutput[id]) {
                errors.push(I18n.t('validate.nameDownstream').replace('{title}', label));
            }
        }

        if (type === 'tokenize') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.tokenizeInput').replace('{title}', label));
            }
            if (!params.text_column || !params.text_column.trim()) {
                errors.push(I18n.t('validate.tokenizeColumn').replace('{title}', label));
            }
        }

        if (type === 'visualize') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.visualizeInput').replace('{title}', label));
            }
            if (!params.chart_type) {
                errors.push(I18n.t('validate.visualizeChartType').replace('{title}', label));
            }
            if (!params.x_field || !params.x_field.trim()) {
                errors.push(I18n.t('validate.visualizeXField').replace('{title}', label));
            }
        }

        if (type === 'output') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.outputInput').replace('{title}', label));
            }
            if ((params.operation === 'save' || params.operation === 'save_csv') && (!params.filename || !params.filename.trim())) {
                errors.push(I18n.t('validate.outputFilename').replace('{title}', label));
            }
        }
    });

    var hasUpstream = Object.keys(nodes).some(function (id) {
        return ['source', 'upload', 'process', 'analysis', 'tokenize', 'resume', 'comment'].indexOf(nodes[id].type) >= 0;
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

/* ─── Three docked panels share one slot ─────────────────────────
   Console, 运行记录 and 导出产物 are all bottom-docked, and each writes an inline
   height when its resize handle is dragged. That inline height beats the CSS
   `height: 0` which hides a panel, so closing one by dropping `.open` alone
   leaves it visually expanded — two panels then overlap in the same slot. All
   three toggles live in this file, so the helper is called directly rather than
   reached for through `window`. */
var DOCKED_PANELS = ['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel'];

function closeDockedPanels(exceptId) {
    DOCKED_PANELS.forEach(function (id) {
        if (id === exceptId) return;
        var other = document.getElementById(id);
        if (!other) return;
        other.classList.remove('open');
        other.style.height = '';
    });
}

/* ─── Export artefacts panel ────────────────────────────────────
   The read side of data/exports. Rows arrive with a name the server already
   resolved once, so the download link and the delete button both send that
   name back unchanged — the browser never assembles a path, and a hand-edited
   `../../etc/passwd` is answered with a 404 like any other missing file. */
function toggleExportsPanel() {
    exportsManager.toggle();
}

var exportsManager = {
    panel() {
        return document.getElementById('exports-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('exports-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* The resize handle leaves an inline height behind, and an inline
           height overrides the CSS `height: 0`. */
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('exports-mgr-body');
        if (!body) return;
        try {
            var resp = await fetch('/api/exports/list?limit=200');
            var result = await resp.json();
            if (!result.ok) throw new Error('list failed');
            this._last = result.exports || [];
            this._totals = { files: result.files || 0, bytes: result.bytes || 0 };
            this.render();
        } catch (e) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('exportsMgr.loadFailed') + '</div>';
        }
    },

    /* Language switch: the table text is JS-built, so an open panel must be
       redrawn from the cached rows rather than refetched. */
    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        if (this._last) this.render();
        else this.refresh();
    },

    size(bytes) {
        var value = Number(bytes) || 0;
        if (value < 1024) return value + ' B';
        if (value < 1024 * 1024) return (value / 1024).toFixed(1) + ' KB';
        return (value / (1024 * 1024)).toFixed(1) + ' MB';
    },

    render() {
        var body = document.getElementById('exports-mgr-body');
        if (!body) return;
        var rows = this._last || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('exportsMgr.empty') + '</div>';
            return;
        }
        var self = this;
        var html = rows.map(function (row) {
            var name = escapeHtml(row.name);
            var ops = '';
            if (row.downloadable) {
                ops += '<button class="runs-mgr-btn" onclick="exportsManager.download(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.download') + '</button>';
            }
            if (row.kind === 'report') {
                /* No download button on purpose — .html is refused there. A
                   report opens through its own route, script-free. */
                ops += '<button class="runs-mgr-btn" onclick="exportsManager.view(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.view') + '</button>';
            }
            ops += '<button class="runs-mgr-btn del" onclick="exportsManager.remove(\'' + self._quote(row.name) + '\')">' + I18n.t('exportsMgr.remove') + '</button>';
            return '<tr>' +
                '<td class="runs-mgr-wf">' + name + '</td>' +
                '<td>' + escapeHtml(row.kind || '') + '</td>' +
                '<td>' + self.size(row.size) + '</td>' +
                '<td class="runs-mgr-time">' + self._when(row.mtime) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        var totals = this._totals || {};
        body.innerHTML =
            '<div class="runs-mgr-empty">' +
            I18n.t('exportsMgr.summary').replace('{files}', totals.files || 0).replace('{size}', this.size(totals.bytes || 0)) +
            '</div>' +
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('exportsMgr.colName') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colKind') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colSize') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colModified') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    _when(epoch) {
        var stamp = Number(epoch) || 0;
        if (!stamp) return '';
        var d = new Date(stamp * 1000);
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
            ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },

    /* Filenames carry quotes and backslashes; an inline onclick is built by
       string concatenation, so the value has to survive both the JS literal and
       the HTML attribute. */
    _quote(name) {
        return String(name).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    },

    download(name) {
        var frame = document.createElement('iframe');
        frame.style.display = 'none';
        frame.src = '/api/exports/download?name=' + encodeURIComponent(name);
        document.body.appendChild(frame);
        setTimeout(function () { document.body.removeChild(frame); }, 60000);
    },

    view(name) {
        /* The report is text crawled from other people's pages, so it is served
           by a route that sends a Content-Security-Policy with no script in it —
           which is also why this is not the download button. */
        window.open('/api/report/view?name=' + encodeURIComponent(name), '_blank');
    },

    /* One click, one HTML file. With a run id the tables are read back out of
       the run store, so yesterday's run can be reported on from the 运行记录
       panel; without one the run this page is holding is used, and the canvas
       lends the node titles (the store is not the only thing worth a report). */
    async report(runId, suggestedTitle) {
        var answer = await showDialog({
            message: I18n.t('exportsMgr.reportHint'),
            input: { value: suggestedTitle || '', placeholder: I18n.t('exportsMgr.reportPlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.reportAi'), value: 'ai', withInput: true },
                { label: I18n.t('exportsMgr.reportGo'), value: 'go', withInput: true, primary: true },
            ],
        });
        if (!answer) return;
        var payload = {
            title: String(answer.input || '').trim(),
            include_conclusion: answer.value === 'ai',
            lang: I18n.lang || 'zh',
            llm: LLMSettings.payload(),
        };
        if (runId) {
            payload.run_id = runId;
        } else {
            payload.nodes = Object.keys(canvas.nodes || {}).map(function (id) {
                var node = canvas.nodes[id];
                return { id: id, title: node.title || id };
            });
        }
        try {
            var resp = await fetch('/api/report/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            if (!result.ok) throw new Error(result.error || 'report failed');
            showToast(I18n.t('exportsMgr.reportDone'));
            this.view(result.name);
            this.refresh();
        } catch (e) {
            showToast(I18n.t('exportsMgr.reportFailed') + ': ' + (e.message || e));
        }
    },

    async remove(name) {
        if (!window.confirm(I18n.t('exportsMgr.confirmRemove'))) return;
        try {
            var resp = await fetch('/api/exports/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ name: name }),
            });
            var result = await resp.json();
            showToast(result.ok ? I18n.t('exportsMgr.removeDone') : I18n.t('exportsMgr.removeFailed'));
        } catch (e) {
            showToast(I18n.t('exportsMgr.removeFailed'));
        }
        this.refresh();
    },
};

/* ─── Dataset manager ───────────────────────────────────────────
   Uploaded/pasted files outlive a run, and until now the only way to see them
   was the Upload node's own picker. A user who re-uploads the same table twice
   gets one copy (identity is content), so the practical questions are "what is
   stored, which workflow reads it, what is it called, and may I delete it".
   The delete button refuses a file a saved workflow still points at: dropping it
   would turn that workflow into an empty Upload node on its next open, and the
   user would only find out when a run returned 0 rows. */
var datasetManager = {
    panel() {
        return document.getElementById('dataset-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('dataset-panel');
        panel.classList.add('open');
        this.refresh();
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        panel.style.height = '';
    },

    async refresh() {
        var body = document.getElementById('dataset-mgr-body');
        if (!body) return;
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('datasetMgr.loading') + '</div>';
        var result = await fetchJSON('/api/data/datasets?limit=200').catch(function () { return null; });
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('datasetMgr.loadFailed') + '</div>';
            return;
        }
        this._last = result.datasets || [];
        this.render();
    },

    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        if (this._last) this.render();
        else this.refresh();
    },

    size(bytes) {
        var value = Number(bytes) || 0;
        if (value < 1024) return value + ' B';
        if (value < 1024 * 1024) return (value / 1024).toFixed(1) + ' KB';
        return (value / (1024 * 1024)).toFixed(1) + ' MB';
    },

    render() {
        var body = document.getElementById('dataset-mgr-body');
        if (!body) return;
        var rows = this._last || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('datasetMgr.empty') + '</div>';
            return;
        }
        var self = this;
        var html = rows.map(function (row) {
            var id = String(row.dataset_id || '');
            /* A file a saved workflow reads is not the user's to delete quietly —
               the reference list is shown and the button refuses server-side too. */
            var refs = row.workflows || [];
            var ops = '<button class="runs-mgr-btn" onclick="datasetManager.rename(\'' + self._quote(id) + '\', \'' +
                self._quote(row.name || '') + '\')">' + I18n.t('datasetMgr.rename') + '</button>';
            ops += '<button class="runs-mgr-btn del" onclick="datasetManager.remove(\'' + self._quote(id) +
                '\', \'' + self._quote(row.name || '') + '\', ' + (refs.length ? 'true' : 'false') + ')">' +
                I18n.t('datasetMgr.remove') + '</button>';
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(row.name || I18n.t('name.unnamed')) + '</td>' +
                '<td>' + escapeHtml(row.source || '') + '</td>' +
                '<td>' + (row.row_count || 0) + '</td>' +
                '<td>' + self.size(row.byte_size) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(id.slice(0, 12)) + '</td>' +
                '<td>' + escapeHtml(refs.join(', ')) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('datasetMgr.colName') + '</th>' +
            '<th>' + I18n.t('datasetMgr.colSource') + '</th>' +
            '<th>' + I18n.t('datasetMgr.colRows') + '</th>' +
            '<th>' + I18n.t('datasetMgr.colSize') + '</th>' +
            '<th>id</th>' +
            '<th>' + I18n.t('datasetMgr.colUsedBy') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    _quote(value) {
        return String(value).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    },

    async rename(id, current) {
        var answer = await showDialog({
            message: I18n.t('datasetMgr.renamePrompt'),
            input: { value: current, placeholder: I18n.t('datasetMgr.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('datasetMgr.rename'), value: 'ok', primary: true },
            ],
        });
        if (!answer) return;
        var result = await fetchJSON('/api/data/datasets/' + encodeURIComponent(id) + '/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: answer }),
        });
        if (result && result.ok) {
            showToast(I18n.t('datasetMgr.renameDone'));
            this.refresh();
        } else {
            showToast((result && result.error) || I18n.t('datasetMgr.renameFailed'));
        }
    },

    async remove(id, name, referenced) {
        if (referenced) {
            /* Same answer as the server's: a workflow would keep pointing at a
               file that is gone. */
            showToast(I18n.t('datasetMgr.stillUsed'));
            return;
        }
        var ok = await showDialog({
            message: I18n.t('datasetMgr.confirmRemove').replace('{name}', name || id),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('datasetMgr.remove'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/data/datasets/' + encodeURIComponent(id), { method: 'DELETE' });
        showToast(result && result.ok ? I18n.t('datasetMgr.removeDone') : I18n.t('datasetMgr.removeFailed'));
        this.refresh();
    },
};

function toggleDatasetPanel() {
    datasetManager.toggle();
}
