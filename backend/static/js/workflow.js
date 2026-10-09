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

/* #182 — per-item locks. The backend is the truth (清空/删除 respect it); this is a
   client cache so the panels can paint a lock icon. It loads once (every panel calls
   load(), which no-ops after the first fetch) and updates itself on a toggle, so the
   icon flips without a round-trip and no panel polls /api/locks on every refresh. */
var _locks = { exports: [], runs: [], history: [], workflows: [] };
var Locks = {
    _loaded: false,
    isLocked(panel, key) {
        return (_locks[panel] || []).indexOf(String(key)) >= 0;
    },
    load(force) {
        if (this._loaded && !force) return Promise.resolve(_locks);
        var self = this;
        return fetch('/api/locks')
            .then(function (resp) { return resp.json(); })
            .then(function (j) {
                if (j && j.ok && j.locks) _locks = j.locks;
                self._loaded = true;
                return _locks;
            })
            .catch(function () { return _locks; });
    },
    toggle(panel, key) {
        var next = !this.isLocked(panel, key);
        return fetch('/api/locks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': (typeof I18n !== 'undefined' && I18n.lang) || 'zh' },
            body: JSON.stringify({ panel: panel, key: String(key), locked: next }),
        })
            .then(function (resp) { return resp.json(); })
            .then(function (j) {
                if (j && j.ok && Array.isArray(j.locks)) _locks[panel] = j.locks;
                return Locks.isLocked(panel, key);
            })
            .catch(function () { return next; });
    },
};

/* One button, three panels. panel is a fixed constant (never user text); the key is
   rendered twice — attrJsArg for the inline handler (the engine hands the RAW key back
   to onLockToggle, which is exactly what the cache is looked up by) and escapeHtml for
   the plain text the handler receives, so a filename with a quote cannot break the
   attribute or the JS literal. */
function lockButtonHtml(panel, key) {
    var locked = Locks.isLocked(panel, key);
    var label = I18n.t(locked ? 'lock.unlock' : 'lock.lock');
    // A drawn padlock, not the Unicode emoji (U+1F512 / U+1F513): those render in the
    // OS's fixed colours
    // and ignore CSS, so they never match the page palette. stroke="currentColor" makes
    // the icon take the button's own (grey / accent) colour. The shackle is the state:
    // seated and centred when locked, swung open when not. aria-hidden because the
    // button already carries the state in title + aria-pressed.
    var svg =
        '<svg class="lock-svg" viewBox="0 0 24 24" width="12" height="12" aria-hidden="true" focusable="false">' +
        '<rect x="5" y="11" width="14" height="9" rx="2"/>' +
        (locked ? '<path d="M8 11V8a4 4 0 0 1 8 0v3"/>' : '<path d="M8 11V8a4 4 0 0 1 7.6-2.1"/>') +
        '</svg>';
    return '<button class="runs-mgr-btn lock' + (locked ? ' locked' : '') + '" title="' + escapeHtml(label) +
        '" aria-pressed="' + (locked ? 'true' : 'false') +
        '" onclick="onLockToggle(\'' + panel + '\', \'' + attrJsArg(key) + '\')">' + svg + '</button>';
}

function onLockToggle(panel, key) {
    return Locks.toggle(panel, key).then(function () {
        if (panel === 'exports' && typeof exportsManager !== 'undefined') exportsManager.render();
        else if (panel === 'runs' && typeof runsManager !== 'undefined') runsManager.render(runsManager._shown || []);
        else if (panel === 'workflows' && typeof wfFiles !== 'undefined' && wfFiles._last) wfFiles.render();
    });
}

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

/* What a refreshed page asks the server for on its first read. The buffer behind
 * `?tail=` is LOG_KEEP lines (backend `app.py`); the browser then keeps what its own
 * view keeps (CONSOLE_VIEW_CAP) — the ask is "give me back what I lost", the cap is a
 * DOM-size decision, and the two are different questions. */
var CONSOLE_REPLAY_LIMIT = 5000;

/** Load one view from a replay, and mark EVERY line the server has ever produced as seen.
 *
 * A fresh page starts at `seen: 0` while the run it is reconnecting to may be at line
 * four thousand. Filling `lines` from the replay is only half of it: the cursor has to
 * land on the reported total as well, or the very next poll — which ships the last 200 —
 * would hand back lines this view has just painted and print them a second time.
 * `takeLines` reads the pair, so the pair must be right. */
function replayConsoleView(view, lines, total) {
    var held = lines || [];
    var count = total === undefined || total === null ? held.length : total;
    view.seen = count;
    view.lines = held.length > CONSOLE_VIEW_CAP ? held.slice(held.length - CONSOLE_VIEW_CAP) : held.slice();
    return view.lines;
}

/* The console's workflow tabs, built in one place. A page that reconnects mid-run has to
 * rebuild them from a status read rather than from a poll it never started, and a copy of
 * this markup in the reconnect path is a bar that drifts from the one the user looks at. */
function consoleTabsHtml(result, activeTab) {
    var html = '<div class="console-tab' + (activeTab === 'all' ? ' active' : '') +
        '" data-wf="all" onclick="switchWfTab(\'all\')">\u25a0 ' + I18n.t('console.all') + '</div>';
    (result.workflows || []).forEach(function (wf) {
        var dotClass = 'tab-dot-idle';
        if (result.running) dotClass = 'tab-dot-run';
        else dotClass = 'tab-dot-done';
        html += '<div class="console-tab' + (activeTab === wf.id ? ' active' : '') + '" data-wf="' + wf.id +
            '" onclick="switchWfTab(' + wf.id + ')">' +
            '<span class="tab-dot ' + dotClass + '"></span>' + escapeHtml(wf.name || ('#' + (wf.id + 1))) + '</div>';
    });
    return html;
}

function consoleHasMultipleWf(result) {
    return !!(result.workflows && result.workflows.length > 1 && result.mode === 'parallel');
}

const workflow = {
    currentFile: null,

    /* The file that is open is part of the session, not of a single page load: a refresh or a
       backend restart must reopen what the user was editing, and only 新建 clears it. The canvas
       itself is already drafted to localStorage; this records WHICH saved file that draft belongs
       to, so runName()/export identity survives a restart instead of the draft reading as new. */
    _persistOpenFile() {
        try {
            if (this.currentFile) localStorage.setItem('crawler_open_file', this.currentFile);
            else localStorage.removeItem('crawler_open_file');
        } catch (e) {
            /* A browser that refuses localStorage (private mode) simply will not carry the name
               across a reload; the canvas draft behaves the same way, so this is a soft decline. */
        }
    },

    restoreOpenFile() {
        /* Only worth restoring when a canvas draft actually came back: an empty browser has no
           open file to remember, and claiming a name with nothing on screen would attribute the
           next Save to a file the user never loaded. */
        try {
            if (!localStorage.getItem('crawler_canvas')) return;
            var name = localStorage.getItem('crawler_open_file');
            if (name) this.currentFile = name;
        } catch (e) {
            /* Same soft decline as _persistOpenFile. */
        }
    },

    /* The remembered open file is the source of truth, but a local draft is only a SNAPSHOT of it:
       the file can be changed out from under us (a re-save, another tab, an edit on the server). So on
       entry we re-fetch the file's CONTENT by name and load the latest, rather than trusting the stale
       draft. A genuinely new canvas (no currentFile) keeps its draft — there is no server file to be
       stale against. A missing or failing load is non-destructive: the restored draft stays put. No
       "loaded" toast is raised on this silent refresh; it is boot, not a user action. */
    async reloadOpenFile() {
        var name = this.currentFile;
        if (!name) return;
        try {
            var resp = await fetch('/api/workflow/load?name=' + encodeURIComponent(name));
            var result = await resp.json();
            if (result && result.ok && result.workflow) this.loadFromJSON(result.workflow);
        } catch (e) {
            /* offline at boot, or the file is gone: leave the draft as-is, never throw into boot */
        }
        if (typeof resumeBar !== 'undefined' && resumeBar && resumeBar.refresh) resumeBar.refresh();
    },

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
                localStorage.setItem('crawler_canvas', JSON.stringify(canvas.serializeDraft()));
                this._persistOpenFile();
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
            var names = result.workflows.map(function (w) {
                // The list now carries one object per file (for the management
                // panel); this menu path only needs the stems.
                return typeof w === 'string' ? w : w.name;
            });
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
                this._persistOpenFile();
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
        /* Read the block in both directions. `toWorkflowJSON` writes all four
           settings, but this used to look only for 'serial' and `headless:false`, so
           opening a file saved as parallel/headless left the bar where it was — and
           the next 保存 then wrote the WRONG settings back over the file, quietly
           converting the workflow the user had configured. An absent key still means
           "leave the panel alone", which is what older files expect. */
        if (settings.mode === 'serial' || settings.mode === 'parallel') {
            RunState.set('parallel', settings.mode === 'parallel');
        }
        if (typeof settings.headless === 'boolean') {
            RunState.set('headless', settings.headless);
        }
        canvas.disabledTypes = Array.isArray(settings.disabledTypes) ? settings.disabledTypes.slice() : [];
        /* …and the fifth read-back is the CAMERA. A file saved after 适应/自动排布
           says where the author was looking; opening it without that line showed a
           different workflow than the one on disk — and the draft written a few
           lines above still held the PREVIOUS canvas's viewport, so the next
           autosave would fossilise the wrong view into this file's draft. */
        if (settings.view) canvas._applyView(settings.view);
        canvas.saveState();
        canvas.scheduleRender();
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
        this._persistOpenFile();
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
        /* Only the name nodes that still take part in a run label it — the same set the backend
           records. A workflow whose head node is switched off is not on the canvas for this run,
           so its label must be absent here too, or the composed name the preview looks rows up by
           would not match the stored (effective) one and a multi-workflow run's data goes
           invisible. `effectiveIds` is the canvas mirror of engine.effective_workflow. */
        var alive = {};
        (canvas.effectiveIds ? canvas.effectiveIds() : Object.keys(nodes)).forEach(function (id) {
            alive[id] = true;
        });
        for (var id in nodes) {
            if (!Object.prototype.hasOwnProperty.call(nodes, id)) continue;
            if (nodes[id].type !== 'name') continue;
            if (!alive[id]) continue;
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

    async _confirmSerialPlatformsBeforeRun() {
        /* A serial-only platform (weibo: parallel paging on one account is always
           answered by the login wall — measured) queues whatever the 排队/错峰 switch
           says, and that is a fact about the site the user is entitled to hear
           BEFORE the run, not after the console stalls. One dialog per press when
           the canvas holds 2+ crawls of such a platform; continuing is legitimate —
           the crawls are correct, just one at a time — closing refuses the run.
           Serial mode needs nothing said: workflows there take turns anyway, so no
           two same-platform crawls are ever in flight. Without the matrix loaded
           nothing is claimed. */
        var json = canvas.toWorkflowJSON();
        var settings = (json && json.settings) || {};
        if (settings.mode !== 'parallel') return true;
        var data = (window.Capabilities && Capabilities.data) || null;
        if (!data || !data.platforms) return true;
        var forced = {};
        data.platforms.forEach(function (cap) {
            if (cap.serialOnly) forced[cap.platform] = true;
        });
        var counts = {};
        Object.keys(canvas.nodes).forEach(function (id) {
            var node = canvas.nodes[id] || {};
            if (node.type !== 'source') return;
            var platform = (node.params || {}).platform;
            if (platform && forced[platform]) counts[platform] = (counts[platform] || 0) + 1;
        });
        var names = Object.keys(counts).filter(function (platform) {
            return counts[platform] > 1;
        });
        if (!names.length) return true;
        var choice = await showDialog({
            message: I18n.t('dialog.serialWarn').replace('{platforms}', platformLabels(names)),
            buttons: [
                { label: I18n.t('dialog.serialWarnGo'), value: 'serial' },
                { label: I18n.t('dialog.cancel'), value: null },
            ],
        });
        return choice === 'serial';
    },

    async _confirmProfileChoiceBeforeRun() {
        /* Parallel + the same platform in two workflows is a genuine fork in the
           road, and only the user can pick:

             · 用 Profile — the site sees one continuous device (what weibo and
               xiaohongshu punish a throwaway browser for), but one profile holds
               one Chrome, so those crawls take turns and 并行 buys nothing there;
             · 本次不用 — each workflow starts as a brand-new device on a planted
               cookie snapshot, which is what makes two of them overlap, spaced only
               by 同平台错峰间隔.

           The question is not asked when 真排队 is on: that switch already decided,
           for the whole program, that one platform crawls one at a time — and the
           serialization it promises is the profile's, so answering it would only let
           this one run opt out of a promise the user just made globally. Returning
           null (no answer given, nothing to carry) makes the backend follow the
           profile setting, which is what 真排队 needs to hold.

           Returns null whenever there is nothing to decide (profiles off, not
           parallel, no shared platform, or 真排队 on), true/false for the user's own
           answer, and undefined when they closed the dialog — which the caller reads
           as "do not start the run". */
        var json = canvas.toWorkflowJSON();
        var settings = (json && json.settings) || {};
        if (settings.mode !== 'parallel') return null;
        if (window.AppSettings) await AppSettings.pull();
        var values = (window.AppSettings && AppSettings._values) || {};
        if (!values.use_browser_profile) return null;
        if (values.same_platform_queue) return null;
        var shared = profileCollisions(canvas.nodes, canvas.connections);
        /* A serial-only platform is taken out of the fork: its crawls queue whatever
           this answer says, so letting it appear here would offer 真并行 that the
           gate will not deliver. */
        var fdata = (window.Capabilities && Capabilities.data) || null;
        if (fdata && fdata.platforms) {
            shared = shared.filter(function (platform) {
                var cap = null;
                fdata.platforms.forEach(function (c) {
                    if (c.platform === platform) cap = c;
                });
                return !(cap && cap.serialOnly);
            });
        }
        if (!shared.length) return null;
        var choice = await showDialog({
            message: I18n.t('dialog.profileClash')
                .replace('{platforms}', platformLabels(shared))
                .replace('{n}', shared.length),
            showClose: false,
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

    _crawlPlatforms() {
        /* Every platform this canvas is about to crawl, in node order, deduped.
           Two node types buy a session: a Data Source names one, and a Comment node
           is dispatched per link by its own domain (that is what the backend does
           with it), so its platforms are read off the links with the same rule the
           textarea's examples follow. A canvas that crawls nothing asks nothing. */
        var found = [];
        Object.keys(canvas.nodes).forEach(function (id) {
            var node = canvas.nodes[id];
            var p = node.params || {};
            if (node.type === 'source') {
                if (p.platform) found.push(p.platform);
            } else if (node.type === 'comment') {
                String(p.urls || '').split(/[\s,;、]+/).forEach(function (line) {
                    var plat = urlPlatform(line);
                    if (plat) found.push(plat);
                });
            }
        });
        return found.filter(function (platform, index) {
            return found.indexOf(platform) === index;
        });
    },

    _sessionPlatforms() {
        /* The sessions this run actually visits, as {platform, account} entries —
           a cookie only decides the crawl of the login it belongs to.

           ``_crawlPlatforms()`` answers "where is this run going" — the network
           warning and the cost of a browser are per site, whatever the mode. This
           answers a narrower question, because the matrix says some crawls are served
           to an anonymous browser (measured: weibo's 热搜 board). Probing those would
           refuse a run the site would have completed, on the strength of a login the
           user was never asked for.

           Comment nodes are always in: the comment engine reads a logged-in feed
           whatever the platform, and its mode is not on the node. */
        var found = [];
        var alive = {};
        (canvas.effectiveIds ? canvas.effectiveIds() : Object.keys(canvas.nodes)).forEach(function (id) {
            alive[id] = true;
        });
        Object.keys(canvas.nodes).forEach(function (id) {
            /* A disabled node (its own switch, its type off, or starved by a disabled upstream)
               runs nothing, so its cookie must never refuse the run — only platforms the run will
               actually visit are asked. */
            if (!alive[id]) return;
            var node = canvas.nodes[id];
            var p = node.params || {};
            if (node.type === 'source') {
                if (p.platform && Capabilities.needsSession(p.platform, p.collect || p.mode)) {
                    found.push({ platform: p.platform, account: String(p.account || '') });
                }
            } else if (node.type === 'comment') {
                String(p.urls || '').split(/[\s,;、]+/).forEach(function (line) {
                    var plat = urlPlatform(line);
                    if (plat) found.push({ platform: plat, account: String(p.account || '') });
                });
            }
        });
        return found.filter(function (entry, index) {
            return found.map(preflightEntryKey).indexOf(preflightEntryKey(entry)) === index;
        });
    },

    async _confirmOverseasBeforeRun() {
        /* One question, asked once: 你的外网开了吗? From inside China x.com and YouTube never
           load at all, and nothing on this page can see which route the machine is actually on,
           so the canvas's own matrix regions are the only evidence there is.

           Measured 2026-09-26, the ask replaced an older warning that claimed a mixed canvas must
           lose a half whichever way it ran: a domestic platform was crawled normally FROM an
           overseas exit, so that claim was wrong and the pair-listing dialog went with it. What is
           left worth knowing is the direction that still holds — overseas platforms need the VPN,
           and a run started without it reads as an empty search.

           Asked *before* the cookie check, because that check buys a browser per platform and a
           run the user is about to cancel should not have paid for it. With the matrix
           unavailable it says nothing: no facts, no claim. */
        if (window.AppSettings) await AppSettings.pull();
        var values = (window.AppSettings && AppSettings._values) || {};
        if (!values.ask_overseas_network) return true;
        var overseas = overseasPlatformsOf(this._crawlPlatforms(), Capabilities.data);
        if (!overseas.length) return true;
        var choice = await showDialog({
            message: I18n.t('dialog.overseasNetwork').replace('{overseas}', platformLabels(overseas)),
            buttons: [
                { label: I18n.t('dialog.overseasNetworkYes'), value: 'go', primary: true },
                { label: I18n.t('dialog.overseasNetworkNo'), value: null },
            ],
        });
        return choice === 'go';
    },

    _hasCommentCrawl() {
        /* A comment crawl is either a dedicated 「评论」 node or a source node switched to
           the comments mode. Only nodes the run will actually reach count — a disabled one
           crawls nothing, so it must not raise a notice about a column it will never fill. */
        var alive = {};
        (canvas.effectiveIds ? canvas.effectiveIds() : Object.keys(canvas.nodes)).forEach(function (id) {
            alive[id] = true;
        });
        return Object.keys(canvas.nodes).some(function (id) {
            if (!alive[id]) return false;
            var node = canvas.nodes[id];
            var p = node.params || {};
            return node.type === 'comment' || (node.type === 'source' && (p.collect === 'comments' || p.mode === 'comments'));
        });
    },

    async _confirmCommentRegionBeforeRun() {
        /* Some platforms/videos do not publish an IP region in their comments, so the 「评论地区」
           column can legitimately come back blank — a measured site fact, not a broken crawl (douyin
           especially: two comment sections, one shows 「·湖南」, the next shows nothing). Users read
           the blank as a bug, so say once, before the run, what the column's emptiness means. */
        if (!this._hasCommentCrawl()) return true;
        var choice = await showDialog({
            message: I18n.t('dialog.commentRegionNotice'),
            buttons: [{ label: I18n.t('dialog.commentRegionOk'), value: 'go', primary: true }],
        });
        return choice === 'go';
    },

    async _cookieGateBeforeRun(opts, profileChoice) {
        /* One place decides what this run has to know about its cookies, because the
           answers have to stay in one order:

           · nothing to crawl, or a 继续 → no question at all. A resumed run is already
             inside "refresh the cookie and carry on", and asking again is cruelty;
           · 自动验证 on → ask the *sites* (``_preflightCookies``), which is a fact, and
             a platform that answers with a login page refuses the run;
           · off → proceed unanswered. The old 「执行前确认 Cookie」 prompt that stood here
             was a guess about a session, and the user asked for it gone: with the real
             check switched off, nothing is asked and nothing blocks.

           ``profileChoice`` is the per-run answer from the profile dialog, forwarded to
           the check so it probes the browser the run will actually use. */
        if (opts && opts.resumeRunId) return true;
        var platforms = this._sessionPlatforms();
        if (!platforms.length) return true;
        if (window.AppSettings) await AppSettings.pull();
        var values = (window.AppSettings && AppSettings._values) || {};
        if (values.cookie_preflight_before_run) return await this._preflightCookies(platforms, profileChoice);
        return true;
    },

    async _preflightCookies(entries, profileChoice) {
        /* Ask each (platform, account) this run will use whether it still lets us in —
           and refuse to start when one says it does not. There is deliberately no
           「我确定，照样跑」 button: the point of measuring instead of guessing is that a
           run past a login wall costs the user an hour and a half-finished dataset they
           then have to reason about.

           A platform that could not be checked does *not* block. Risk control, a
           timeout and a profile held by another browser say nothing about the
           cookie, and pretending otherwise would send the user to re-log in a
           session that is fine — the one mistake this whole path cannot undo.

           The answer table and the blocked/unclear lists are keyed by the same
           ``preflightEntryKey`` the backend computes, so a second account's dead
           cookie never stands in for the one this node actually asks for. */
        function isBlocked(table, key) {
            return (table[key] || {}).blocking === true;
        }
        showToast(I18n.t('toast.cookieChecking').replace('{platforms}', entryLabels(entries)));
        var body = { platforms: entries };
        if (profileChoice !== null && profileChoice !== undefined) {
            /* The per-run answer from the profile dialog decides *which browser* the
               crawl will use, so it decides which browser is worth probing. Absent
               means "follow the setting" and stays absent — writing false here would
               turn one dialog's answer into a permanent override. */
            body.use_profile = profileChoice;
        }
        var resp = null;
        try {
            resp = await fetchJSON('/api/cookies/preflight', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (e) {
            resp = null;
        }
        if (!resp || !resp.ok) {
            /* The check itself failed. Say that, and let the run go: the page has no
               licence to refuse a crawl on an answer it never received, and the run
               will meet the real wall soon enough and report it as its own failure. */
            showToast(I18n.t('toast.cookieUncheckable').replace('{platforms}', entryLabels(entries)));
            return true;
        }
        var results = resp.results || {};
        var blocked = (resp.blocked || []).filter(isBlocked.bind(null, results));
        var unclear = (resp.unclear || []).filter(function (key) {
            return blocked.indexOf(key) < 0;
        });
        if (unclear.length) {
            showToast(I18n.t('toast.cookieUnclear').replace('{platforms}', entryLabels(unclear.map(unpackEntryKey))), 6000);
        }
        if (!blocked.length) return true;
        var lines = blocked.map(function (key) {
            var verdict = results[key] || {};
            /* Server-rendered wording: the sentences live next to the crawler that
               decided them, so the panel cannot hold a second opinion about what
               「已失效」 meant on the page the probe actually looked at. */
            return '· ' + (verdict.text || key);
        });
        var choice = await showDialog({
            message: I18n.t('dialog.cookieExpired')
                .replace('{n}', blocked.length)
                .replace('{platforms}', entryLabels(blocked.map(unpackEntryKey))) +
                '\n' + lines.join('\n') + '\n' + I18n.t('dialog.cookieExpiredHint'),
            buttons: [
                { label: I18n.t('dialog.cookieGoUpdate'), value: 'update', primary: true },
                { label: I18n.t('dialog.cancel'), value: null },
            ],
        });
        /* Both answers stop the run — that is the hard block. Only 「去更新 Cookie」
           opens the panel: closing the dialog with 取消 and finding a panel the user
           did not ask for is the difference between refusing and nagging. */
        if (choice === 'update') {
            /* Land them on the login that is broken rather than on a selector still showing
               whoever was last picked — which, on a platform with several accounts, is a
               different file than the one the run was refused for. */
            var broken = unpackEntryKey(blocked[0]);
            openCookieDialog(broken.platform, broken.account);
        }
        return false;
    },

    async execute(opts) {
        opts = opts || {};
        /* Validate before running */
        var validationErrors = this.validate();
        /* NO cookie check here. This used to ask /api/cookies/status and push 「缺少 Cookie」 for
           every source node whose platform was not in its `cookies` map — a second, weaker opinion
           about the same question the run gate already answers, and wrong in three ways measured on
           the user's own canvas: that map is keyed by platform and answers only for the DEFAULT
           account (app.py:4841), so a node on a saved named account was refused for a cookie it has;
           it is built from CookieManager.PLATFORMS, so wechat — a platform with no cookie row at all —
           read as "missing" and could never run; and it walked every node instead of the live ones, so
           a disabled node blocked the press. `validate()` owns the shape (the matrix refuses a stored
           account that has no file, BY NAME), and `_cookieGateBeforeRun` owns the question of whether
           the login still works, per (platform, account) — AGENTS: the frontend holds no second
           opinion about a crawl, and 「无法核对」 never blocks. */
        if (validationErrors.length > 0) {
            /* ONE toast for one press of the button. `#toast` is a single element whose
               text is replaced, so the loop that used to run over these errors left the
               LAST one on screen: a canvas with five problems reported one, the user
               fixed it, pressed 执行 again and was told about the next — the same button
               three times over. Numbered lines and a header that says how many. */
            if (validationErrors.length === 1) {
                showToast(validationErrors[0]);
            } else {
                var lines = validationErrors.map(function (err, i) {
                    return (i + 1) + '. ' + err;
                });
                showToast(
                    I18n.t('toast.problems').replace('{n}', validationErrors.length) + '\n' + lines.join('\n'),
                    Math.min(9000, 2500 + 900 * validationErrors.length)
                );
            }
            return;
        }
        /* Ask about the browser before the browser is bought: on the platforms
           whose session rotates, a throwaway profile *is* the failure, and a run
           would only discover it an hour deep. */
        if (!(await this._confirmProfileBeforeRun())) return;
        /* Said before the fork question and the cookie probes: on a platform the site
           forces to one-at-a-time, 「本次不用 = 真并行」 is not on offer, and a run the
           user cancels here should not have paid for the questions behind it. */
        if (!(await this._confirmSerialPlatformsBeforeRun())) return;
        /* Parallel + a platform two workflows both want is the one case where
           keeping the device and keeping the parallelism are mutually exclusive,
           so the user decides which they are buying. ``undefined`` means they
           closed the dialog; null means there was nothing to decide. */
        var profileChoice = await this._confirmProfileChoiceBeforeRun();
        if (profileChoice === undefined) return;
        /* A canvas holding both a domestic and an overseas platform is run from two
           different networks, and neither one serves both — say so before paying for
           the cookie probes below. */
        if (!(await this._confirmOverseasBeforeRun())) return;
        /* A comment crawl can come back with a blank 「评论地区」 because the *site* does not
           publish an IP region for that video — say so once before the run, so the empty column
           is not mistaken for a failure. Silent when the canvas has no comment node. */
        if (!(await this._confirmCommentRegionBeforeRun())) return;
        /* A long crawl can outlive its cookie and die at the login wall an hour
           in. When 自动验证 is on, the sites are asked whether that has already
           happened and a login page refuses the run; with it off nothing is asked.
           Only fires when the canvas really contains a crawler node. */
        if (!(await this._cookieGateBeforeRun(opts, profileChoice))) return;
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
                if (_clearConsoleBeforeRun()) {
                    /* The option is on: wipe everything the console owns — tabs and
                       their retained histories included — so the new run opens blank. */
                    resetConsoleForNewRun();
                } else {
                    document.getElementById('console-output').innerHTML = '';
                }
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
            /* Not "已停止": the Stop request only asks. The browsers close on a side
               thread and the run's own thread still owes the record its verdict, so
               announcing the outcome here would be a claim the run has not made — and
               the run-record row is still '运行中' until it lands. */
            showToast(I18n.t('toast.stopping'));
            var statusText = document.getElementById('status-text');
            if (statusText) statusText.textContent = I18n.t('status.stopping');
            /* Follow the record to its settled state so the panel flips 运行中 →
               中断 without the user having to refresh it. The worker may still be
               writing; awaitSettled re-reads until no row claims to be running. */
            if (window.runsManager) runsManager.awaitSettled();
        } catch (e) {
            showToast(I18n.t('toast.stopFailed') + ': ' + e.message);
        }
    },

    async reconnectConsole() {
        /* A refresh used to cost the console: nothing in the boot sequence started the
           poll, so the box sat empty for the rest of a run that was still writing and the
           user read a dead UI for a live crawl. The lines are in the server's buffer (it
           never knew this tab went away), so the page asks for what it lost, paints it,
           and — if the work is still going — takes the stream up again.

           A run that finished while the page was closed is shown too. The buffer is not
           cleared until the NEXT run claims it, so 「刚才那次跑了什么」 is still answerable,
           and answering it is the point of keeping the lines at all. */
        if (this._pollTimer) return;
        var result;
        try {
            var resp = await fetch('/api/workflow/status?tail=' + CONSOLE_REPLAY_LIMIT);
            result = await resp.json();
        } catch (e) {
            return; // no server to read, so nothing to say about it
        }
        var out = document.getElementById('console-output');
        if (!out) return;
        var live = !!(result.running || result.settling || result.stopping);
        var shown = (result.logs && result.logs.length) || 0;
        if (!live && !shown) return; // an empty between-runs buffer is not a console

        /* Every view is loaded from the replay, not only the visible one: a parallel run's
           second tab is one click away, and a tab that replays nothing when it is opened
           is the same loss this function exists to end. */
        replayConsoleView(consoleViews.all, result.logs, result.log_total);
        (result.workflows || []).forEach(function (w) {
            replayConsoleView(consoleViewFor(w.id), w.logs, w.total);
        });

        var tabs = document.getElementById('console-tabs');
        if (consoleHasMultipleWf(result)) {
            tabs.style.display = 'flex';
            tabs.innerHTML = consoleTabsHtml(result, _wfActiveTab);
        } else {
            tabs.style.display = 'none';
            tabs.innerHTML = '';
        }
        var active = consoleHasMultipleWf(result) && _wfActiveTab !== 'all' ? _wfActiveTab : 'all';
        repaintConsoleView(out, active);

        var statusText = document.getElementById('status-text');
        var statusNodes = document.getElementById('status-nodes');
        if (result.total_nodes > 0 && statusNodes) {
            statusNodes.textContent = I18n.t('status.progress')
                .replace('{done}', result.completed_nodes)
                .replace('{total}', result.total_nodes);
        }
        if (statusText) {
            /* The run's own last line is the sentence that describes it; inventing a
               status word here would be a second opinion about a run this page did not
               watch end. */
            var last = (result.logs || [])[shown - 1];
            if (live) {
                statusText.textContent = last
                    ? last.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '')
                    : I18n.t('status.running');
            } else if (result.outcome === 'completed') {
                statusText.textContent = I18n.t('status.completed');
            } else if (last) {
                statusText.textContent = last.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '');
            }
        }

        if (!live) return;
        /* Only a run that is still going steals the screen. A finished one is worth
           reading — its lines are painted above — but popping the console panel open on
           every page load for work that ended an hour ago is the app deciding to show the
           user something they did not ask for. */
        var panel = document.getElementById('console-panel');
        if (panel && !panel.classList.contains('open')) {
            closeDockedPanels('console-panel');
            panel.classList.add('open');
        }
        RunState.setRunning(true);
        this.pollStatus();
        showToast(I18n.t('toast.consoleReconnected'));
    },

    _stopPoll: function () {
        /* One owner for the timer. The reconnect path and the Run button can both ask
           for status, and two intervals reading the same console would append the same
           line twice — the cursor cannot tell them apart because both reads are valid. */
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    },

    pollStatus: function () {
        var self = this;
        if (this._pollTimer) return;
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
        /* A Stop flips `running` off on the request thread and writes 正在停止 into
           the record, but the worker still owes that record its verdict. Keep reading
           through that window — bounded, so a wedged worker cannot hold the console
           open forever, and long enough to cover a page load the worker may be
           standing in: measured, 40 s, because a browser closed from the Stop request
           does not interrupt the command already running inside it. */
        var SETTLE_TICKS = 90;
        var settleTicks = 0;
        var interval = setInterval(async function () {
            try {
                var resp = await fetch('/api/workflow/status');
                var result = await resp.json();
                if (result.cookie_expired && !cookieWarned) {
                    cookieWarned = true;
                    showToast(I18n.t('toast.cookieExpired'));
                }
                /* The panel that shows what has run keeps itself current for the whole
                   life of the run's record — while it runs AND while a stopped one is
                   being settled. Stopping was the case where nobody touched anything
                   and the row still said 运行中 for half a minute, because the tick
                   that refreshes it only ran while the run said 'running'. */
                if (result.running || result.settling || result.stopping) {
                    if (window.runsManager) runsManager.autoRefresh();
                }
                if (result.running) {
                    settleTicks = 0;
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

                    var hasMultipleWf = consoleHasMultipleWf(result);

                    if (hasMultipleWf) {
                        /* Show tab bar */
                        consoleTabs.style.display = 'flex';
                        var activeTab = typeof _wfActiveTab !== 'undefined' ? _wfActiveTab : 'all';
                        consoleTabs.innerHTML = consoleTabsHtml(result, activeTab);

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
                    if (!result.running && (result.settling || result.stopping) && settleTicks < SETTLE_TICKS) {
                        /* The Stop was received but the worker has not written the
                           verdict: keep reading rather than guess 'failed'/'interrupted'
                           from counts a finalizing run is still moving. */
                        settleTicks += 1;
                        return;
                    }
                    if (!result.running && (result.settling || result.stopping)) {
                        /* Out of budget with the worker still unwinding. This used to
                           fall straight into the block below and print a verdict — the
                           run's own `outcome` was still the empty string, so the
                           console claimed 失败 for a run that had merely been stopped
                           slowly. Say the one thing that is known instead, and let the
                           record be read where it is read from: the run panel keeps
                           re-reading it until the verdict lands. */
                        self._stopPoll();
                        RunState.setRunning(false);
                        document.getElementById('status-text').textContent = I18n.t('status.stopping');
                        showToast(I18n.t('toast.stillSettling'));
                        return;
                    }
                    if (!result.running) {
                        self._stopPoll();
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
                        /* The worker's verdict has landed: one last read so the row
                           in the panel speaks it too — this tick is the first one that
                           was allowed to trust the record. */
                        if (window.runsManager) runsManager.refreshIfOpen();
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
                self._stopPoll();
                RunState.setRunning(false);
                showToast(I18n.t('toast.pollFailed'));
            }
        }, 1000);
        this._pollTimer = interval;
    },
};

/* What a data source still needs is the MATRIX's answer, not this file's.

   The branch this replaces knew three shapes — comments→links, wechat→links,
   everything else→keyword — which is the `if platform == '…'` second opinion
   AGENTS.md forbids, and it was not hypothetical: four platforms offer
   「某作者的作品」 (which asks for a creator, not a keyword) and 哔哩哔哩 offers
   热榜 (which asks for nothing at all). Both were declared in the matrix, rendered
   in the panel, executable by the backend — and unreachable from the UI, because
   a filled-in author or board node was refused 「缺少关键词」 and no request ever
   left the page. Same payload, one source: `/api/capabilities`. */
function sourceNodeErrors(node, label, hasDataInput) {
    var params = node.params || {};
    var platform = node.platform || params.platform;
    if (!platform) {
        return [I18n.t('validate.sourceNoPlatform').replace('{title}', label)];
    }
    if (!Capabilities.ready()) {
        /* Refusing to guess is the honest answer: without the matrix this function
           cannot know which fields the mode asks for, and the panel already says so
           with a retry button wherever it renders a form. */
        return [I18n.t('validate.capUnavailable').replace('{title}', label)];
    }
    if (!Capabilities.platform(platform)) {
        return [I18n.t('validate.sourceUnknownPlatform', { title: label, platform: String(platform) })];
    }
    var wanted = String(params.collect || params.mode || '');
    var offered = Capabilities.modes(platform);
    var mode = Capabilities.mode(platform, wanted);
    if (wanted && offered.length > 1 && mode.key !== wanted) {
        return [I18n.t('validate.sourceUnknownMode')
            .replace('{title}', label)
            .replace('{platform}', I18n.t('platform.' + platform))];
    }
    var errors = [];
    /* Feed gate, matrix-driven like the rest of this function: a field the matrix
       marks feedable (f.fedBy) reads an upstream table column, and a wired table
       REPLACES the pasted list — its requiredness and ownership become runtime
       facts about the parent's rows, not design-time claims about this node.
       A wire that cannot feed and a column named with nothing wired are both
       half-mistakes this gate refuses by name (backend validate agrees exactly). */
    var feedFields = (mode.fields || []).filter(function (f) { return f.fedBy; });
    if (hasDataInput && !feedFields.length) {
        errors.push(I18n.t('validate.sourceFeedNoMode').replace('{title}', label));
    }
    if (!hasDataInput && feedFields.some(function (f) { return String(params[f.fedBy] || '').trim(); })) {
        errors.push(I18n.t('validate.sourceFeedNoInput').replace('{title}', label));
    }
    (mode.fields || []).forEach(function (field) {
        if (field.fedBy && hasDataInput) {
            if (!String(params[field.fedBy] || '').trim()) {
                errors.push(
                    I18n.t('validate.sourceFeedNoColumn')
                        .replace('{title}', label)
                        .replace('{field}', I18n.t(field.labelKey))
                );
            }
            return;
        }
        var raw = params[field.key];
        var text = String(raw === undefined || raw === null ? '' : raw);
        if (field.linksOf) {
            var links = text.replace(/,/g, '\n').split(/\r?\n/).filter(function (s) { return s.trim(); });
            if (!links.length) {
                if (field.required) {
                    errors.push(I18n.t('validate.sourceFieldMissing')
                        .replace('{title}', label)
                        .replace('{field}', I18n.t(field.labelKey)));
                }
                return;
            }
            /* Each pasted line has to belong to the platform named for it — the
               engine refuses others at crawl time; say it before the run. */
            var bad = links.filter(function (u) { return urlPlatform(u) !== field.linksOf; }).length;
            if (bad) {
                errors.push(I18n.t('validate.sourceCommentPlat')
                    .replace('{title}', label)
                    .replace('{n}', bad)
                    .replace('{plat}', I18n.t('platform.' + field.linksOf)));
            }
            return;
        }
        if (field.required && !text.trim()) {
            errors.push(I18n.t('validate.sourceFieldMissing')
                .replace('{title}', label)
                .replace('{field}', I18n.t(field.labelKey)));
        }
    });
    return errors;
}

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

    needsSession(id, key) {
        /* Whether this crawl is a session crawl. With no answer from the matrix it
           says yes: a probe that is not run cannot block a run, but a crawl that
           quietly turns out to need a login costs the user a wasted crawl — so the
           unknown direction is "keep asking", matching `fields()` never guessing a
           shape. */
        if (!this.ready()) return true;
        var mode = this.mode(id, key);
        if (!mode) return true;
        return mode.needsSession !== false;
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

/* Registered fine-tuned models, fetched once at boot so the bert-mode picker can
   offer them by friendly NAME (「网暴模型」) instead of making the user type a path.
   Same shape as Capabilities: a cold page starts the fetch before any node is
   opened, so the first bert settings panel shows the list, not a spinner. The list
   is OPTIONAL — a node always accepts a raw path, and a missing or malformed
   registry (the backend returns an empty list, never an error) simply leaves the
   text input as the only way in. `load()` re-renders the open settings panel,
   because a node clicked in the sliver before the response arrives must not stay
   stuck without its picker. */
const BertModels = {
    data: null,
    load() {
        if (this._pending) return this._pending;
        var self = this;
        this._pending = fetch('/api/models')
            .then(function (resp) {
                return resp.json();
            })
            .then(function (payload) {
                self.data = payload && Array.isArray(payload.models) ? payload.models : [];
                /* `canvas` is a top-level const in canvas.js — window.canvas never
                   exists; `openSettings` is a top-level function in this file. */
                if (typeof canvas !== 'undefined' && canvas && canvas._settingsNodeId &&
                    typeof openSettings === 'function') {
                    openSettings(canvas._settingsNodeId);
                }
                return self.data;
            })
            .catch(function () {
                self.data = [];
                return self.data;
            })
            .then(function (result) {
                self._pending = null;
                return result;
            });
        return this._pending;
    },
    list() {
        return this.data || [];
    },
};
window.BertModels = BertModels;

/* The bert-mode fields, shared by the sentiment / emotion / tendency analyzers. When
   the registry names any models a picker lists them by name (each option's value is
   that model's path) above the raw path box; picking one writes the path into
   bert_model and updateParam re-renders, so the text box shows what was chosen. A
   leading blank option keeps "no registered model picked" an honest state: without it
   a stored-but-blank path would visually land on option #0, which is a model the user
   never selected. A stored path that is not a registered one still shows itself —
   selectOptionTags appends it as 「不是可选项」, never reverting to the first model. */
function _bertModelsSelected(p) {
    /* The chosen model paths, de-duplicated, from the comma-joined bert_models param —
       mirrored off the backend's bert_model_list so the checkbox echo and the run agree. */
    var raw = String((p && p.bert_models) || '').replace(/，/g, ',');
    var out = [];
    raw.split(',').forEach(function (s) {
        var t = s.trim();
        if (t && out.indexOf(t) < 0) out.push(t);
    });
    return out;
}

function toggleBertModel(nodeId, path, checked) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var set = _bertModelsSelected(node.params);
    var i = set.indexOf(path);
    if (checked && i < 0) set.push(path);
    if (!checked && i >= 0) set.splice(i, 1);
    // Stored SORTED so one model set is one fingerprint whatever the click order.
    updateParam(nodeId, 'bert_models', set.slice().sort().join(','));
}

function renderBertField(nodeId, p) {
    var html = '';
    var models = BertModels.list();
    var chosen = _bertModelsSelected(p);
    if (models.length) {
        // One checkbox per registered model; the label is the friendly NAME, the value written
        // into bert_models is that model's PATH. Checking two or more switches the node to a
        // tidy multi-model comparison table (see the note below); the raw path box beside it
        // still accepts a model nobody registered.
        var boxes = models.map(function (m) {
            var ck = chosen.indexOf(m.path) >= 0 ? ' checked' : '';
            return '<label class="settings-label" style="display:block;font-weight:normal;cursor:pointer;">' +
                '<input type="checkbox"' + ck + ' ' +
                'onchange="toggleBertModel(\'' + nodeId + '\',\'' + attrJsArg(m.path) + '\',this.checked)"> ' +
                escapeHtml(m.name) + '</label>';
        }).join('');
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.bertModelsPick') + '</label>' + boxes + '</div>';
        if (chosen.length >= 2) {
            html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('hint.bertModelsMulti') + '</div>';
        }
    }
    html += renderParamInput(nodeId, p, 'bert_model', 'settings.bertModel', 'text', '');
    html += renderParamInput(nodeId, p, 'batch_size', 'settings.batchSize', 'number', 32);
    html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('settings.bertModelHint') + '</div></div>';
    return html;
}

function parseWorkflowFileText(text) {
    /* Decide whether a file's contents are a workflow — WITHOUT touching the canvas. A
       workflow file is JSON carrying a node list; anything else is named, never thrown.
       Kept as a pure (string → verdict) function so the File menu's decision is testable
       without a FileReader or a browser. loadFromJSON repeats the node-list guard, but this
       answers BEFORE the canvas is torn down and lets the caller pick which toast to show. */
    var data;
    try {
        data = JSON.parse(String(text || ''));
    } catch (e) {
        return { ok: false, reason: 'parse' };
    }
    if (!data || typeof data !== 'object' || !Array.isArray(data.nodes)) {
        return { ok: false, reason: 'nodes' };
    }
    return { ok: true, workflow: data };
}

function openWorkflowImportPicker() {
    var el = document.getElementById('workflow-import-file');
    if (el) el.click();
}

function importWorkflowFile(input) {
    /* Import a workflow file the user chose on disk (not one already saved to the server).
       Read it as text, decide if it is a workflow, and only then hand a valid one to the SAME
       loadFromJSON the Load panel uses — so an imported canvas is built identically (its own
       node ids preserved, files the server still has re-attached). */
    var file = input && input.files && input.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
        var parsed = parseWorkflowFileText(String(reader.result || ''));
        if (!parsed.ok) {
            showToast(I18n.t(parsed.reason === 'parse' ? 'toast.workflowImportFailed' : 'toast.workflowFileInvalid'));
        } else if (workflow.loadFromJSON(parsed.workflow)) {
            showToast(I18n.t('toast.workflowImported'));
        }
        input.value = '';  // let re-picking the SAME file fire onchange again
    };
    reader.onerror = function () {
        showToast(I18n.t('toast.workflowImportFailed'));
        input.value = '';
    };
    reader.readAsText(file);
}

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

function refreshAccountCandidates() {
    /* Which logins exist is which cookie files are on disk NOW, and that list reaches the
       data-source node ONLY through GET /api/capabilities (its account options are rebuilt at
       send time from the on-disk accounts) — the frontend never keeps its own second opinion
       about which accounts a crawl may use. `refreshCookieStatus()` below repaints the cookie
       panel from /api/cookies/status, but the node's account box reads the CAPABILITIES cache,
       which was filled once at startup — so without this, a login created, deleted, renamed or
       had its device retired stayed invisible to the data-source node until a full page reload.
       Re-read that one endpoint and repaint a node panel the user may already have open. */
    Capabilities.load().then(function () {
        if (typeof canvas !== 'undefined' && canvas && canvas._settingsNodeId) openSettings(canvas._settingsNodeId);
    });
}

function _upstreamDeclaresWindow(nodeId) {
    /* Walk the wiring upstream from this node and ask whether ANY collection node set a
       complete start AND end window. This reads the node's own parameters — the same "did a
       range get stated" fact the backend records via _note_window — purely to decide whether
       to OFFER the "append the crawled time range" checkbox. It is not a second opinion about
       how a crawl behaves. A canvas can still carry the flag from an earlier wiring; the
       backend ignores it then and writes the file anyway, so nothing is lost either way. */
    var conns = (typeof canvas !== 'undefined' && canvas && canvas.connections) || [];
    var nodes = (typeof canvas !== 'undefined' && canvas && canvas.nodes) || {};
    var seen = {};
    var stack = [nodeId];
    seen[nodeId] = true;
    while (stack.length) {
        var cur = stack.pop();
        for (var i = 0; i < conns.length; i++) {
            var c = conns[i];
            if (c.to !== cur || seen[c.from]) continue;
            seen[c.from] = true;
            var n = nodes[c.from];
            if (n && n.params && String(n.params.start_time || '').trim() && String(n.params.end_time || '').trim()) {
                return true;
            }
            stack.push(c.from);
        }
    }
    return false;
}

/* The DIRECT parents' types. An output node's format has to match what it is actually fed, and that is
   decided by its immediate upstream — the save node merges its direct tables, and a PDF is produced from a
   direct visualize / compile parent. Not a transitive walk: two hops away is not "this node's input". */
function _outputParentTypes(nodeId) {
    var conns = (typeof canvas !== 'undefined' && canvas && canvas.connections) || [];
    var nodes = (typeof canvas !== 'undefined' && canvas && canvas.nodes) || {};
    var types = [];
    for (var i = 0; i < conns.length; i++) {
        if (String(conns[i].to) !== String(nodeId)) continue;
        var n = nodes[conns[i].from];
        if (n && n.type) types.push(n.type);
    }
    return types;
}

/* PDF is the ONLY honest format when every direct parent carries a LaTeX artifact (visualize) or an
   already-compiled PDF (compile) and none carries a row table. A pdfable + tabular mix is deliberately
   NOT offered as PDF — it shows the tabular list without pdf, exactly as the backend refuses to merge a
   chart into a csv save. Mirrors the backend TABLE_NODE_TYPES; the backend is the authority. */
function _outputIsPdfOnly(nodeId) {
    var TABLE = ['source', 'upload', 'resume', 'comment', 'process', 'analysis', 'tokenize', 'output'];
    var types = _outputParentTypes(nodeId);
    var pdfable = 0;
    var tabular = 0;
    for (var i = 0; i < types.length; i++) {
        if (types[i] === 'visualize' || types[i] === 'compile') pdfable += 1;
        else if (TABLE.indexOf(types[i]) >= 0) tabular += 1;
    }
    return pdfable > 0 && tabular === 0;
}

/* A single screen that answers "which platform wants what" from the crawl matrix
   alone (#181). It never keeps its own platform list: every line is generated from
   the `profileRecommended` / `serialOnly` / `parallelRecommended` flags the backend
   already sends, so a platform reclassified in the matrix changes this text with no
   second place to edit. Split out as a pure message-builder (matrix in, string out)
   so the node harness can drive it without a DOM. */
function platformAdviceMessage(matrix) {
    var caps = (matrix && Array.isArray(matrix.platforms)) ? matrix.platforms : [];
    var names = function (predicate) {
        var list = caps.filter(predicate).map(function (cap) { return cap.platform; });
        return list.length ? platformLabels(list) : I18n.t('advice.none');
    };
    var wantsProfile = function (cap) { return !!cap.profileRecommended; };
    return [
        I18n.t('advice.title'),
        '',
        I18n.t('advice.profile') + names(wantsProfile),
        I18n.t('advice.live') + names(wantsProfile),
        I18n.t('advice.serial') + names(function (cap) { return !!cap.serialOnly; }),
        I18n.t('advice.parallel') + names(function (cap) { return !!cap.parallelRecommended; }),
    ].join('\n');
}

function showPlatformAdvice() {
    /* Refuse to advise without the facts: a dialog that guesses "which platforms are
       serial-only" from memory is exactly the second opinion this app forbids. */
    if (!Capabilities.ready()) {
        showToast(I18n.t('advice.unavailable'));
        return;
    }
    showDialog({ message: platformAdviceMessage(Capabilities.data), showClose: true });
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

/* The platforms of this canvas that live behind an overseas network.

 * Only one direction is asked about, because only one direction is a fact: from inside China
 * x.com and YouTube do not load at all, so a canvas holding one of them needs the VPN to be up
 * and nothing on this page can see whether it is. The reverse was believed for a while — that a
 * mixed canvas must lose a half whichever way it ran — and measured false on 2026-09-26, where a
 * domestic platform crawled normally from an overseas exit; a Chinese platform stays runnable on
 * either route, so it is not classified here.
 *
 * The region is read off the crawl matrix (the same payload that says which fields a
 * mode needs), never from a list typed here: a platform added to the matrix without a
 * region is simply left out rather than guessed at, and a platform the matrix has not
 * delivered yet cannot be classified either — which is why the caller stays silent when
 * this answers empty.
 */
function overseasPlatformsOf(platforms, matrix) {
    var found = [];
    if (!matrix || !Array.isArray(matrix.platforms)) return found;
    (platforms || []).forEach(function (platform) {
        matrix.platforms.forEach(function (cap) {
            if (cap.platform === platform && cap.region === 'overseas' && found.indexOf(platform) === -1) {
                found.push(platform);
            }
        });
    });
    return found;
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
function platformLabels(list) {
    /* A platform key (`zhihu`) is what the canvas, the crawl matrix and the cookie files
       are addressed by — it is not a word the user reads, and printing it left a bare
       `zhihu` inside a Chinese dialog. The backend applies the same rule to its own
       `{platform}` placeholders inside `i18n.t()`, and the two label sets are pinned
       equal by TestPlatformLabelParity. */
    return (list || []).map(function (p) { return I18n.t('platform.' + p); }).join('、');
}

/* The one answer-key for a preflight entry — the same string the backend computes in
   ``cookie_preflight.entry_key``. A blank account keeps the bare platform name (every
   old payload and test stays true); a named account gets its own slot, so a second
   login that was never used cannot be called dead on the first one's verdict. */
function preflightEntryKey(entry) {
    var plat = typeof entry === 'string' ? entry : String((entry && entry.platform) || '');
    var acct = typeof entry === 'string' ? '' : String((entry && entry.account) || '');
    return acct ? plat + '@' + acct : plat;
}

/* The reverse: an answer key back into an entry, for display and for opening the
   panel on the right platform. An entry that is already an object passes through —
   the blocked/unclear lists arrive as keys, the toast paths may hold either. */
function unpackEntryKey(key) {
    if (key && typeof key === 'object') {
        return { platform: String(key.platform || ''), account: String(key.account || '') };
    }
    var s = String(key || '');
    var at = s.indexOf('@');
    return at < 0 ? { platform: s, account: '' } : { platform: s.slice(0, at), account: s.slice(at + 1) };
}

function entryLabels(entries) {
    /* Localize an entry list for a dialog: the platform word, and the account only
       when there is one. Printing ``weibo@work`` verbatim would be the bare-key bug
       again — a machine name inside prose the user reads. */
    return (entries || [])
        .map(function (e) {
            var plat = typeof e === 'string' ? e : String((e && e.platform) || '');
            var acct = typeof e === 'string' ? '' : String((e && e.account) || '');
            return I18n.t('platform.' + plat) + (acct ? '@' + acct : '');
        })
        .join('、');
}

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
        html += sourceFieldHtml(nodeId, fields[i], p[fields[i].key], p);
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

/* A stored switch, read in whichever grammar wrote it.

   Two spellings are on disk and always have been: `renderParamCheckbox` stored the TEXTS
   'true'/'false' until it started storing `this.checked`, every other checkbox stored the
   boolean, and a hand-written or exported workflow file holds either. `p.x ? 'checked' : ''`
   reads the text 'false' as ON — the box then shows the opposite of what the run does, which
   is the one thing a settings panel may not do. Same rule as the backend's
   `utils.helpers.as_bool`: a value that states nothing (absent, blank, a word neither list
   knows) answers the default the panel shows. */
function boolParam(value, defVal) {
    if (value === undefined || value === null) return !!defVal;
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value === value && value !== 0;
    var text = String(value).trim().toLowerCase();
    if (['true', '1', 'yes', 'y', 'on', '是'].indexOf(text) >= 0) return true;
    if (['false', '0', 'no', 'n', 'off', 'none', 'null', 'nan', '否', '不', '假'].indexOf(text) >= 0) return false;
    return !!defVal;
}

/* One select's options, with the node's own stored value kept on screen when it is not one
   of the choices. Painting the first option instead would show a choice the run then
   refuses BY NAME (the backend refuses an unoffered `select` rather than guessing), so the
   user would re-pick exactly what was already written and still be refused. The extra
   option carries the raw text through escapeHtml: it is the user's own data, most often
   from a file they edited by hand. */
function selectOptionTags(items, stored, defVal) {
    var value =
        stored === undefined || stored === null || String(stored).trim() === ''
            ? String(defVal === undefined ? '' : defVal)
            : String(stored);
    var known = items.some(function (item) {
        return String(item.value) === value;
    });
    var html = items
        .map(function (item) {
            return (
                '<option value="' +
                escapeHtml(String(item.value)) +
                '"' +
                (known && String(item.value) === value ? ' selected' : '') +
                '>' +
                item.label +
                '</option>'
            );
        })
        .join('');
    if (known || value === '') return html;
    return (
        html +
        '<option value="' +
        escapeHtml(value) +
        '" selected>' +
        escapeHtml(I18n.t('settings.unknownOption').replace('{value}', value)) +
        '</option>'
    );
}

function sourceSelectHtml(nodeId, labelKey, options, value, onChange) {
    if (!onChange) return '';
    var html =
        '<div class="settings-group"><label class="settings-label">' +
        I18n.t(labelKey) +
        '</label><select class="settings-select" onchange="' +
        onChange +
        '">';
    html += selectOptionTags(
        options.map(function (o) {
            // A real catalogue key is translated; an empty one (a user-typed account name)
            // shows the value as typed — a name they chose is not the program's word to look up.
            return { value: o.value, label: o.labelKey ? I18n.t(o.labelKey) : o.value };
        }),
        value,
        ''
    );
    return html + '</select></div>';
}

function sourceFieldHtml(nodeId, f, value, allParams) {
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
            (boolParam(v, f.default) ? 'checked' : '') +
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
        /* A field whose list can be fed from an upstream column shows itself disabled
           the moment the user names one: the executor crawls the table, not this box,
           and grey says so before the run rather than after. Which fields can be fed
           is the matrix's answer (f.fedBy), never a list the panel keeps by hand. */
        var fedAway = f.fedBy && allParams && String(allParams[f.fedBy] || '').trim();
        input =
            '<textarea class="settings-input" rows="5" placeholder="' +
            escapeHtml(f.placeholder || '') +
            '" onchange="' +
            paramCall(nodeId, f.key, 'this.value') +
            '"' +
            (fedAway ? ' disabled' : '') +
            '>' +
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
            '<input class="settings-input" type="number" min="0" value="' + escapeHtml(p.comment_limit != null ? p.comment_limit : 0) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_limit\',parseInt(this.value)||0)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentLimitHint') + '</div></div>' +
            /* A table-side time filter over the comments already crawled — distinct from a
               crawl node's start/end (which bound how far back to CRAWL). Keys are
               comment_start/comment_end so the two never share a name. Both ends or neither:
               a half range is refused by the backend, not guessed. */
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentStart') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.comment_start || '') + '" placeholder="2026-01-01" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_start\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentEnd') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.comment_end || '') + '" placeholder="2026-12-31" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_end\',this.value)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentTimeHint') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.partSize') + '</label>' +
            '<input class="settings-input" type="number" min="0" value="' + escapeHtml(p.part_size != null ? p.part_size : 50) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'part_size\',parseInt(this.value)||0)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.partSizeHint') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.format') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'format\',this.value)">' +
            selectOptionTags(
                ['csv', 'json'].map(function (f) {
                    return { value: f, label: I18n.t('format.' + f) };
                }),
                p.format,
                'csv'
            ) +
            '</select></div>' +
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (boolParam(p.per_article_file, false) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'per_article_file\',this.checked)">' + I18n.t('settings.perArticleFile') + '</label></div>' +
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (boolParam(p.keep_parts, true) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'keep_parts\',this.checked)">' + I18n.t('settings.keepParts') + '</label></div>' +
            /* 重新采集 belongs here for the same reason it exists on a source node: the comment
               walk shares that walk's ledger, so a comment already stored is skipped rather than
               re-fetched — and a node whose form cannot say "collect again" leaves the user with
               an empty table and no explanation. (Measured: it was missing on every platform's
               comment node, which is what the matrix test now refuses.) */
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (boolParam(p.recrawl, false) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'recrawl\',this.checked)">' + I18n.t('settings.recrawl') + '</label>' +
            '<div class="settings-hint">' + I18n.t('settings.recrawlHint') + '</div></div>' +
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
        var PROCESS_OPS = ['clean', 'emotion', 'tendency', 'sentiment', 'keyword', 'cluster', 'ner', 'aggression', 'anomaly', 'correlation'];
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value);openSettings(\'' + nodeId + '\')">' +
            selectOptionTags(
                PROCESS_OPS.map(function (op) {
                    return { value: op, label: I18n.t('op.' + op) };
                }),
                p.operation,
                'clean'
            ) +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.text_column || '正文') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>';

        /* Clean operation. Two ways to wash a table: the model reads each row and judges
           both artifacts and relevance; the rule set strips what a repost leaves behind
           (转发链, @提及, 话题标签, O网页链接, 展开c) for free. The topic box belongs to the model
           alone, and is therefore not shown for the rules that would ignore it. */
        if (p.operation === 'clean') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'llm', [
                { v: 'llm', l: llmModeLabel() },
                { v: 'regex', l: I18n.t('mode.regex') },
            ]);
            if (p.mode === 'regex') {
                html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                    I18n.t('settings.cleanRegexHint') + '</div></div>';
            } else {
                html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.topic') + '</label>' +
                    '<input class="settings-input" value="' + escapeHtml(p.topic || '') + '" placeholder="e.g. topic" ' +
                    'onchange="updateParam(\'' + nodeId + '\',\'topic\',this.value)"></div>';
            }
        }

        /* Mode selector for emotion / tendency. Both additionally offer the fine-tuned BERT
           path (emotion: six SMP2020-EWECT classes incl. Surprise; tendency: six stance
           classes distilled from the LLM). The bert option needs a model path, so it reveals
           the same two fields the sentiment node's bert mode does. */
        if (p.operation === 'emotion' || p.operation === 'tendency') {
            var modeOptions = [
                { value: 'llm', label: llmModeLabel() },
                { value: 'ml', label: I18n.t('mode.ml') },
                { value: 'bert', label: I18n.t('mode.bert') },
            ];
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.mode') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'mode\',this.value)">' +
                selectOptionTags(modeOptions, p.mode, 'llm') +
                '</select></div>';
            if (p.mode === 'ml') {
                html += '<div class="settings-group"><button class="menu-btn" onclick="trainMLModel(\'' + nodeId + '\',\'' + p.operation + '\')">' + I18n.t('settings.trainModel') + '</button></div>';
            }
            if (p.mode === 'bert') {
                html += renderBertField(nodeId, p);
            }
        }

        /* Sentiment polarity. Four ways to answer 正面/负面/中性, and the default is the one
           that costs nothing: SnowNLP needs no model, no download and no GPU. The
           thresholds only mean anything to the two modes that answer with a POLARITY
           PROBABILITY — ml and llm answer with a label they were trained or prompted to
           pick, and re-deciding it from their confidence number would be a second opinion
           about the model's own answer (see analyzers/sentiment.py). */
        if (p.operation === 'sentiment') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'snownlp', [
                { v: 'snownlp', l: I18n.t('mode.snownlp') },
                { v: 'ml', l: I18n.t('mode.ml') },
                { v: 'llm', l: llmModeLabel() },
                { v: 'bert', l: I18n.t('mode.bert') },
            ]);
            if (p.mode === 'snownlp') {
                html += renderParamInput(nodeId, p, 'pos_threshold', 'settings.posThreshold', 'number', 0.6);
                html += renderParamInput(nodeId, p, 'neg_threshold', 'settings.negThreshold', 'number', 0.4);
                html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                    I18n.t('settings.sentimentThresholdHint') + '</div></div>';
            }
            if (p.mode === 'bert') {
                html += renderBertField(nodeId, p);
            }
            if (p.mode === 'ml') {
                html += '<div class="settings-group"><button class="menu-btn" onclick="trainMLModel(\'' + nodeId + '\',\'' + p.operation + '\')">' + I18n.t('settings.trainModel') + '</button></div>';
            }
        }

        /* Keyword extraction. Three methods, and the third is the one for social text:
           jieba's built-in IDF table comes from a news corpus, so Weibo colloquial words
           score wrongly; tfidf_corpus fits the IDF on the user's own table instead. The
           word-class filter is what keeps 转发/哈哈 out of the list. */
        if (p.operation === 'keyword') {
            html += renderParamSelect(nodeId, p, 'method', 'settings.method', 'tfidf',
                [{ v: 'tfidf', l: 'TF-IDF' }, { v: 'textrank', l: 'TextRank' },
                 { v: 'tfidf_corpus', l: I18n.t('settings.methodCorpusIdf') }]);
            html += renderParamInput(nodeId, p, 'topk', 'settings.topk', 'number', 10);
            html += renderParamInput(nodeId, p, 'allow_pos', 'settings.allowPos', 'text', '');
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('settings.allowPosHint') + '</div></div>';
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
                [{ v: 'regex', l: I18n.t('mode.regex') }, { v: 'llm', l: llmModeLabel() }]);
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.entityTypes') +
                '</label><input class="settings-input" value="' + escapeHtml(p.entity_types || '') + '" placeholder="' +
                I18n.t('settings.entityTypesPlaceholder') + '" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'entity_types\',this.value)">' +
                '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.entityTypesHint') +
                '</div></div>';
        }

        /* Cyberbullying speech — the study's own object. The word-list path needs no model,
           costs nothing and gives the same answer twice; the model path is for the euphemisms
           a fixed list cannot see. */
        if (p.operation === 'aggression') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'lexicon',
                [{ v: 'lexicon', l: I18n.t('mode.lexicon') }, { v: 'llm', l: llmModeLabel() }]);
            if (p.mode === 'llm') {
                html += renderParamInput(nodeId, p, 'model', 'settings.model', 'text', '');
            }
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('settings.aggressionHint') + '</div></div>';
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
            /* Per-node model override: the transport (provider/host/key) stays
               run-global, but a node may pick its own local Ollama tag. Only
               offered on the ollama provider — an OpenRouter run cannot use a
               daemon tag it has no id for. The real tag list is filled in async
               by renderNodeModelSelect once the panel mounts; until then the box
               shows 跟随全局 plus whatever value is already stored. */
            if (typeof LLMSettings !== 'undefined' && LLMSettings.load().provider === 'ollama') {
                var modelOpts = [{ value: '', label: I18n.t('settings.followGlobalModel') }];
                if (p.model) modelOpts.push({ value: p.model, label: escapeHtml(p.model) });
                html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.nodeModel') + '</label>' +
                    '<select class="settings-select" id="node-model-' + nodeId + '" ' +
                    'onchange="updateParam(\'' + nodeId + '\',\'model\',this.value)">' +
                    selectOptionTags(modelOpts, p.model, '') +
                    '</select></div>';
            }
            html += '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
                '<input type="checkbox" ' + (boolParam(p.live_export, false) ? 'checked' : '') + ' ' +
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
            '<input class="settings-input" value="' + escapeHtml(p.text_column || '') + '" placeholder="' + I18n.t('settings.textColumnPlaceholder') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.outputMode') + '</label>' +
            (hasDownstreamVisualize ? '<div style="font-size:12px;color:var(--accent);padding:4px 0;">' + I18n.t('settings.tokenizeOutputLocked') + '</div>' :
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'output_mode\',this.value)">' +
                selectOptionTags(
                    ['word_freq', 'words_only', 'csv_line'].map(function (m) {
                        return { value: m, label: I18n.t('outputMode.' + m) };
                    }),
                    p.output_mode,
                    'word_freq'
                ) +
                '</select>') + '</div>' +
            ((p.output_mode || 'word_freq') === 'word_freq' ?
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.topN') + '</label>' +
                '<input class="settings-input" type="number" value="' + escapeHtml(p.top_n || '') + '" placeholder="' + I18n.t('settings.topNPlaceholder') + '" ' +
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
            'onchange="updateParam(\'' + nodeId + '\',\'workflow_name\',this.value)"></div>' +
            /* 排布顺序 drives autoLayout's vertical stack. Store the RAW string (never
               parseInt || 0): a cleared field must stay blank = "no preference", whereas
               forcing 0 would silently pin this workflow above the other untouched ones. */
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.layoutOrder') + '</label>' +
            '<input class="settings-input" type="number" value="' + escapeHtml(p.layout_order != null ? p.layout_order : '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'layout_order\',this.value)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.layoutOrderHint') + '</div></div>';
    } else if (node.type === 'resume') {
        /* Adopts rows a previous run already paid for. Both lists live on the
           server, so the panel fills them asynchronously below. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('resume.hint') + '</div>' +
            '<div id="resume-pick" data-node="' + nodeId + '">' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">…</div></div>' +
            '<div class="settings-group"><button class="menu-btn" onclick="renderResumeSettings(\'' + nodeId + '\')">' +
            I18n.t('resume.refresh') + '</button></div>';
    } else if (node.type === 'compile') {
        /* The compile node has no fields of its own: it runs the LaTeX its upstream visualize node produced
           through the local MiKTeX (the xelatex path is set under 设置) and hands a PDF downstream. The one
           precondition worth stating is the one a run otherwise refuses. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.compileHint') + '</div>';
    } else if (node.type === 'output') {
        var p = node.params;
        var pdfOnly = _outputIsPdfOnly(nodeId);
        /* An output fed only by a chart / compile has exactly one valid format; force and persist it so the
           run sends pdf even if the select is never touched. The extension itself is enforced server-side. */
        if (pdfOnly && p.format !== 'pdf') {
            p.format = 'pdf';
            canvas.saveState();
        }
        var fmt = pdfOnly ? 'pdf' : (p.format || 'csv');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t(pdfOnly ? 'settings.outputPdfHint' : 'settings.outputMergeHint') + '</div></div>';
        var formatOptions = pdfOnly
            ? [{ value: 'pdf', label: I18n.t('format.pdf') }]
            : ['csv', 'json', 'excel', 'txt', 'html', 'markdown'].map(function (f) {
                  return { value: f, label: I18n.t('format.' + f) };
              });
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.format') + '</label>' +
            '<select class="settings-select" onchange="onOutputFormatChange(\'' + nodeId + '\',this.value)">' +
            selectOptionTags(formatOptions, p.format, pdfOnly ? 'pdf' : 'csv') +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.filename') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.filename || (pdfOnly ? 'export.pdf' : 'export.csv')) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'filename\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.filename_timestamp, false) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'filename_timestamp\',this.checked)"> ' +
            I18n.t('settings.filenameTimestamp') + '</label></div>';
        if (!pdfOnly && _upstreamDeclaresWindow(nodeId)) {
            html += '<div class="settings-group"><label class="settings-checkbox-label">' +
                '<input type="checkbox" ' + (boolParam(p.filename_time_range, false) ? 'checked' : '') + ' ' +
                'onchange="updateParam(\'' + nodeId + '\',\'filename_time_range\',this.checked)"> ' +
                I18n.t('settings.filenameTimeRange') + '</label></div>';
        }
        if (!pdfOnly && fmt === 'txt') {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
                '<input class="settings-input" value="' + escapeHtml(p.text_column || '') + '" placeholder="optional: one column per line" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>';
        }
        if (!pdfOnly) {
            html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
        }
    }
    content.innerHTML = html;
    if (node.type === 'resume') renderResumeSettings(nodeId);
    if (
        node.type === 'process' &&
        nodeNeedsLlm(node.params, node.operation) &&
        typeof LLMSettings !== 'undefined' &&
        LLMSettings.load().provider === 'ollama'
    ) {
        renderNodeModelSelect(nodeId);
    }
    canvas.updateSettingsButton();
}

/* ── Per-node Ollama model picker: fill the node's model select from the
   daemon's own tags ──
   The panel renders synchronously, so the box starts with just 跟随全局 + the
   stored value; this runs after mount and repopulates it with the real list.
   One fetch per session (the daemon list rarely changes while the page is
   open) — 刷新 in the AI panel stays the way to force a re-read. Guarded on the
   ollama provider by the caller. */
var _nodeOllamaModels = null; // cached tag list, or '' once a fetch failed
async function renderNodeModelSelect(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    if (_nodeOllamaModels === null) {
        try {
            var resp = await fetch('/api/llm/ollama/models');
            var result = await resp.json();
            _nodeOllamaModels = (result.ok && result.models) || [];
        } catch (e) {
            _nodeOllamaModels = ''; // say it failed once, do not re-hit every panel open
        }
    }
    // A node captured before the await is not on the page after it: re-look the
    // select up (the panel may have been rebuilt while we were fetching).
    node = canvas.nodes[nodeId];
    var sel = document.getElementById('node-model-' + nodeId);
    if (!node || !sel) return;
    var current = node.params && node.params.model ? node.params.model : '';
    var tags = _nodeOllamaModels === '' ? [] : _nodeOllamaModels;
    var items = [{ value: '', label: I18n.t('settings.followGlobalModel') }];
    tags.forEach(function (m) {
        items.push({ value: m, label: escapeHtml(m) });
    });
    if (current && !tags.some(function (m) { return m === current; })) {
        items.push({ value: current, label: escapeHtml(current) });
    }
    sel.innerHTML = selectOptionTags(items, current, '');
}

/* ── Resume node: pick a stored run and one of its node outputs ── */
async function renderResumeSettings(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var p = node.params;
    var runs = [];
    try {
        var resp = await fetch('/api/runs/resumable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow: canvas.toWorkflowJSON(), all: true }),
        });
        var result = await resp.json();
        runs = (result.ok && result.runs) || [];
    } catch (e) {
        runs = [];
    }
    /* Looked up AFTER the await, and attributed to the node it belongs to.
       `openSettings` rewrites the whole form — which any parameter edit does — so the
       holder this call started with can be off the page when the answer lands, and the
       dropdown then never appears while everything looks idle. The guard used to run
       before the await, which is the one moment it could not be wrong. */
    /* Looked up AFTER the await, and attributed to the node it belongs to.
       `openSettings` rewrites the whole form — which any parameter edit does — so the
       holder this call started with can be off the page when the answer lands, and the
       dropdown then never appears while everything looks idle. The guard used to run
       before the await, which is the one moment it could not be wrong. */
    var holder = document.getElementById('resume-pick');
    if (!holder || holder.dataset.node !== nodeId) return;
    if (!runs.length) {
        holder.innerHTML = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('resume.none') + '</div>';
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
            return '<option value="' + escapeHtml(r.run_id) + '"' + (r.run_id === p.resume_run_id ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('') +
        '</select></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.nodeSelect') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'resume_node_id\',this.value);canvas.updateNodeDisplay(\'' + nodeId + '\')">' +
        '<option value=""' + (!p.resume_node_id ? ' selected' : '') + '>' + I18n.t('resume.autoNode') + '</option>' +
        nodes.map(function (n) {
            var label = (n.title || n.node_id) + ' · ' + n.row_count + ' ' + I18n.t('settings.rows');
            return '<option value="' + escapeHtml(n.node_id) + '"' + (n.node_id === p.resume_node_id ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('') +
        '</select></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.limit') + '</label>' +
        '<input class="settings-input" type="number" value="' + escapeHtml(p.resume_limit || 0) + '" placeholder="' + I18n.t('resume.limitPlaceholder') + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'resume_limit\',parseInt(this.value)||0)"></div>';
    holder.innerHTML = html;
    canvas.updateNodeDisplay(nodeId);
}

/* Format -> file-extension map for the Save node. Keeps the filename's
   extension in sync whenever the user picks a different export format,
   instead of leaving a stale ".csv" on a JSON/Excel/... export. */
var FORMAT_EXTENSIONS = { csv: '.csv', json: '.json', excel: '.xlsx', txt: '.txt', html: '.html', markdown: '.md', pdf: '.pdf' };

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
function llmModeLabel() {
    /* Which transport the 「大模型」 option names. Guarded on the BINDING, not on
       `window.CloudMode`: app.js declares it at top level, so it is a global lexical
       binding that never appears on window, and `if (window.X)` would read as "no flag"
       forever — which is the mistake this repo already documents once. */
    var cloud = typeof CloudMode !== 'undefined' && CloudMode.on;
    return I18n.t(cloud ? 'mode.llmCloud' : 'mode.llm');
}

function nodeNeedsLlm(params, nodeOperation) {
    var p = params || {};
    var op = p.operation || nodeOperation || '';
    /* Trimmed, because a BLANK means the operation's declared default on the server —
       `'  '` is not a mode name and app.py reads it as "not stated". Comparing the raw
       value here answered "no model" for a whitespace-only field while the server
       answered "the default", so one of the two blocked a run the other would allow. */
    var mode = String(p.mode === undefined || p.mode === null ? '' : p.mode).trim();
    /* Asked by NAME, never by "not the one I special-case". `mode !== 'ml'` was the old
       reading and it charged a row-by-row model pass to a node whose mode said something
       else — sentiment has four modes now, three of which need no model at all. A blank
       means the operation's own declared default, which is what the backend reads too
       (app.py `_op_needs_llm`). */
    if (op === 'clean') return (mode || 'llm') === 'llm';
    if (op === 'emotion' || op === 'tendency') return (mode || 'llm') === 'llm';
    if (op === 'sentiment') return (mode || 'snownlp') === 'llm';
    if (op === 'ner') return mode === 'llm';
    return false;
}

/* ── Shared settings UI helpers ── */
function renderParamInput(nodeId, p, key, labelKey, type, defVal) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t(labelKey) + '</label>' +
        '<input class="settings-input" type="' + type + '" value="' + escapeHtml(p[key] !== undefined ? p[key] : defVal) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.value)"></div>';
}
function renderParamSelect(nodeId, p, key, labelKey, defVal, options) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t(labelKey) + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.value)">';
    html += selectOptionTags(
        options.map(function (o) {
            return { value: o.v, label: o.l || o.v };
        }),
        p[key],
        defVal
    );
    html += '</select></div>';
    return html;
}
function renderParamCheckbox(nodeId, p, key, labelKey, defVal) {
    var checked = boolParam(p[key], defVal);
    return '<div class="settings-group"><label class="settings-label">' +
        '<input type="checkbox" ' + (checked ? 'checked' : '') + ' ' +
        'onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.checked)"> ' +
        I18n.t(labelKey) + '</label></div>';
}

/* ── Analysis node settings ── */
var ANALYSIS_OPS = ['drop_null', 'fill_null', 'drop_duplicates', 'dedupe_similar', 'filter_rows', 'select_columns', 'rename_columns', 'strip_whitespace', 'convert_type', 'sort_rows', 'sample_rows', 'groupby_agg', 'join_tables', 'column_calc', 'bin_column', 'extract_time', 'bin_time', 'suggest_stages', 'topic_model', 'topic_by_stage', 'topic_label', 'topic_map', 'topic_salience', 'topic_timeline', 'topic_flow', 'topic_coherence', 'cooccur', 'forecast', 'alert', 'sentiment_evolution'];
var FILTER_OPS = ['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains', 'not_contains', 'in', 'not_in', 'is_null', 'not_null'];
var CONVERT_TYPES = ['str', 'int', 'float', 'bool', 'datetime'];

function renderAnalysisSettings(nodeId, p) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value)">' +
        selectOptionTags(
            ANALYSIS_OPS.map(function (op) {
                return { value: op, label: I18n.t('op.' + op) };
            }),
            p.operation,
            'drop_null'
        ) +
        '</select></div>';

    var op = p.operation || 'drop_null';
    if (['drop_null', 'fill_null', 'drop_duplicates', 'select_columns', 'strip_whitespace'].indexOf(op) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.columns') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.columns || '') + '" placeholder="col1, col2 (empty = all)" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'columns\',this.value)"></div>';
    }
    if (op === 'drop_null') {
        /* 'any' drops a row with one empty cell, 'all' only when every selected
           cell is empty — the two produce very different tables, so the choice
           has to be on the panel and not buried in a default. */
        html += renderParamSelect(nodeId, p, 'how', 'settings.dropHow', 'any',
            [{ v: 'any', l: I18n.t('settings.dropHowAny') }, { v: 'all', l: I18n.t('settings.dropHowAll') }]);
    }
    if (op === 'drop_duplicates') {
        /* Exact text and normalised text are different questions about the same table: a
           comment farm's repost is a NEW string and the same comment. Naming both here is
           what keeps the node from answering the second while the user asked the first. */
        html += renderParamSelect(nodeId, p, 'mode', 'settings.dedupeMode', 'exact',
            [{ v: 'exact', l: I18n.t('settings.dedupeModeExact') },
             { v: 'normalized', l: I18n.t('settings.dedupeModeNormalized') }]);
    }
    if (op === 'dedupe_similar') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            renderParamInput(nodeId, p, 'max_distance', 'settings.dedupeDistance', 'number', 8) +
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.dedupeSimilarHint') + '</div></div>';
    }

    /* ── The event study: when, which subjects, and which way the crowd leaned ──
       These four are the paper-replication steps. They share one shape — name the
       column, name the new column — so they are rendered together rather than one
       block per operation with the same three inputs copied into each. */
    if (op === 'extract_time') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'time_new_col', 'settings.newColumn', 'text', '日期');
        html += renderParamSelect(nodeId, p, 'time_part', 'settings.timePart', 'date',
            [{ v: 'date', l: I18n.t('settings.timePartDate') },
             { v: 'hour', l: I18n.t('settings.timePartHour') },
             { v: 'weekday', l: I18n.t('settings.timePartWeekday') },
             { v: 'month', l: I18n.t('settings.timePartMonth') },
             { v: 'year', l: I18n.t('settings.timePartYear') }]);
    }
    if (op === 'bin_time') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'phase_new_col', 'settings.newColumn', 'text', '阶段');
        html += renderParamInput(nodeId, p, 'phase_edges', 'settings.phaseEdges', 'text', '');
        html += renderParamInput(nodeId, p, 'phase_labels', 'settings.phaseLabels', 'text', '');
        html += renderParamInput(nodeId, p, 'phase_order_col', 'settings.phaseOrderColumn', 'text', '阶段序号');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.phaseHint') + '</div></div>';
    }
    if (op === 'suggest_stages') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'stages_min_days', 'settings.stagesMinDays', 'number', 3);
        html += renderParamInput(nodeId, p, 'stages_max_windows', 'settings.stagesMaxWindows', 'number', 6);
        html += renderParamInput(nodeId, p, 'stages_peak_ratio', 'settings.stagesPeakRatio', 'number', 2);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.stagesHint') + '</div></div>';
    }
    if (op === 'topic_model') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTopn', 'number', 10);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicHint') + '</div></div>';
    }
    if (op === 'topic_by_stage') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'stage_col', 'settings.stageColumn', 'text', '阶段');
        html += renderParamInput(nodeId, p, 'stage_order_col', 'settings.stageOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'stage_topic_counts', 'settings.stageTopicCounts', 'text', '5,6,4,4,4');
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTopn', 'number', 10);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += renderParamInput(nodeId, p, 'topic_sample_n', 'settings.topicSampleN', 'number', 5);
        html += renderParamSelect(nodeId, p, 'word_source', 'settings.topicWordSource', 'tfidf',
            [{ v: 'tfidf', l: I18n.t('settings.topicWordSourceTfidf') },
             { v: 'lda', l: I18n.t('settings.topicWordSourceLda') }]);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicStageHint') + '</div></div>';
    }
    if (op === 'topic_label') {
        html += renderParamInput(nodeId, p, 'label_words_col', 'settings.labelWordsColumn', 'text', 'feature_words');
        html += renderParamInput(nodeId, p, 'label_samples_col', 'settings.labelSamplesColumn', 'text', 'sample_texts');
        html += renderParamInput(nodeId, p, 'label_summary_col', 'settings.labelSummaryColumn', 'text', '主题概括');
        html += renderParamSelect(nodeId, p, 'label_on_fail', 'settings.labelOnFail', 'abort',
            [{ v: 'abort', l: I18n.t('settings.labelOnFailAbort') },
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') }]);
        html += renderParamInput(nodeId, p, 'label_max_topics', 'settings.labelMaxTopics', 'number', 30);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicLabelHint') + '</div></div>';
    }
    if (op === 'topic_map') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicMapTopn', 'number', 6);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicMapHint') + '</div></div>';
    }
    if (op === 'topic_salience') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTermsTopn', 'number', 30);
        html += renderParamInput(nodeId, p, 'topic_lambda', 'settings.topicLambda', 'number', 1);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicSalienceHint') + '</div></div>';
    }
    if (op === 'topic_timeline') {
        // Every box names a column 分阶段 LDA writes, so the defaults are that step's own
        // output names: an untouched form is the pipeline hand-off, not a guess.
        html += renderParamInput(nodeId, p, 'timeline_stage_col', 'settings.timelineStageColumn', 'text', 'stage');
        html += renderParamInput(nodeId, p, 'timeline_topic_col', 'settings.timelineTopicColumn', 'text', 'topic');
        html += renderParamInput(nodeId, p, 'timeline_words_col', 'settings.timelineWordsColumn', 'text', 'feature_words');
        html += renderParamInput(nodeId, p, 'timeline_size_col', 'settings.timelineSizeColumn', 'text', 'doc_n');
        html += renderParamInput(nodeId, p, 'timeline_order_col', 'settings.timelineOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'timeline_overlap', 'settings.timelineOverlap', 'number', 0.5);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.timelineHint') + '</div></div>';
    }
    if (op === 'topic_flow') {
        html += renderParamInput(nodeId, p, 'flow_stage_col', 'settings.flowStageColumn', 'text', 'stage');
        html += renderParamInput(nodeId, p, 'flow_topic_col', 'settings.flowTopicColumn', 'text', 'topic');
        html += renderParamInput(nodeId, p, 'flow_words_col', 'settings.flowWordsColumn', 'text', 'feature_words');
        html += renderParamInput(nodeId, p, 'flow_weights_col', 'settings.flowWeightsColumn', 'text', 'weights');
        html += renderParamInput(nodeId, p, 'flow_order_col', 'settings.flowOrderColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'flow_label_col', 'settings.flowLabelColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'flow_min_similarity', 'settings.flowMinSimilarity', 'number', 0.5);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.flowHint') + '</div></div>';
    }
    if (op === 'topic_coherence') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'coherence_min_topics', 'settings.coherenceMinTopics', 'number', 2);
        html += renderParamInput(nodeId, p, 'coherence_max_topics', 'settings.coherenceMaxTopics', 'number', 8);
        html += renderParamInput(nodeId, p, 'topic_topn', 'settings.topicTopn', 'number', 10);
        html += renderParamInput(nodeId, p, 'coherence_max_documents', 'settings.coherenceMaxDocuments', 'number', 2000);
        html += renderParamInput(nodeId, p, 'topic_max_features', 'settings.topicMaxFeatures', 'number', 2000);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.coherenceHint') + '</div></div>';
    }
    if (op === 'cooccur') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'cooccur_topn', 'settings.cooccurTopn', 'number', 30);
        html += renderParamInput(nodeId, p, 'cooccur_min_count', 'settings.cooccurMinCount', 'number', 2);
        html += renderParamInput(nodeId, p, 'cooccur_window', 'settings.cooccurWindow', 'number', 0);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.cooccurHint') + '</div></div>';
    }
    if (op === 'forecast') {
        html += renderParamInput(nodeId, p, 'forecast_period_col', 'settings.forecastPeriodColumn', 'text', 'period');
        html += renderParamInput(nodeId, p, 'forecast_value_col', 'settings.forecastValueColumn', 'text', 'sentiment_index');
        html += renderParamSelect(nodeId, p, 'forecast_method', 'settings.forecastMethod', 'moving_average',
            [{ v: 'moving_average', l: I18n.t('settings.forecastMethodMa') },
             { v: 'holt', l: I18n.t('settings.forecastMethodHolt') }]);
        html += renderParamInput(nodeId, p, 'forecast_horizon', 'settings.forecastHorizon', 'number', 3);
        html += renderParamInput(nodeId, p, 'forecast_window', 'settings.forecastWindow', 'number', 3);
        html += renderParamInput(nodeId, p, 'forecast_alpha', 'settings.forecastAlpha', 'number', 0.5);
        html += renderParamInput(nodeId, p, 'forecast_beta', 'settings.forecastBeta', 'number', 0.3);
        html += renderParamInput(nodeId, p, 'forecast_min_periods', 'settings.forecastMinPeriods', 'number', 4);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.forecastHint') + '</div></div>';
    }
    if (op === 'alert') {
        html += renderParamInput(nodeId, p, 'alert_period_col', 'settings.alertPeriodColumn', 'text', 'period');
        html += renderParamInput(nodeId, p, 'alert_index_col', 'settings.alertIndexColumn', 'text', 'sentiment_index');
        // Blank means "that half of the rule is not wanted", exactly like the 强度 column box on
        // 情感演化曲线, so these two start empty rather than pre-filled.
        html += renderParamInput(nodeId, p, 'alert_intensity_col', 'settings.alertIntensityColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'alert_volume_col', 'settings.alertVolumeColumn', 'text', '');
        html += renderParamInput(nodeId, p, 'alert_streak', 'settings.alertStreak', 'number', 2);
        html += renderParamInput(nodeId, p, 'alert_swing', 'settings.alertSwing', 'number', 0.2);
        html += renderParamInput(nodeId, p, 'alert_heating', 'settings.alertHeating', 'number', 0.15);
        html += renderParamInput(nodeId, p, 'alert_volume_floor', 'settings.alertVolumeFloor', 'number', 0.6);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.alertHint') + '</div></div>';
    }
    if (op === 'sentiment_evolution') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'label_col', 'settings.labelColumn', 'text', 'sentiment');
        html += renderParamInput(nodeId, p, 'index_new_col', 'settings.newColumn', 'text', 'sentiment_index');
        html += renderParamInput(nodeId, p, 'label_positive', 'settings.labelPositive', 'text', 'positive');
        html += renderParamInput(nodeId, p, 'label_neutral', 'settings.labelNeutral', 'text', 'neutral');
        html += renderParamInput(nodeId, p, 'label_negative', 'settings.labelNegative', 'text', 'negative');
        html += renderParamInput(nodeId, p, 'score_col', 'settings.scoreColumn', 'text', 'score');
        html += renderParamInput(nodeId, p, 'evolution_order_col', 'settings.evolutionOrderColumn', 'text', '');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.evolutionHint') + '</div></div>';
    }
    if (op === 'fill_null') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
        /* A method and a literal value are different operations; leaving method
           empty means "fill with the value above". */
        html += renderParamSelect(nodeId, p, 'method', 'settings.fillMethod', '',
            [{ v: '', l: I18n.t('settings.fillMethodValue') }, { v: 'ffill', l: 'ffill' }, { v: 'bfill', l: 'bfill' }]);
    }
    if (op === 'filter_rows') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.filterOp') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'op\',this.value)">' +
            selectOptionTags(
                FILTER_OPS.map(function (o) {
                    return { value: o, label: o };
                }),
                p.op,
                'eq'
            ) +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.value') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.value || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value\',this.value)"></div>';
    }
    if (op === 'rename_columns') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.renameFrom') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.rename_from || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'rename_from\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.renameTo') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.rename_to || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'rename_to\',this.value)"></div>';
    }
    if (op === 'convert_type') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.dtype') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'dtype\',this.value)">' +
            selectOptionTags(
                CONVERT_TYPES.map(function (t) {
                    return { value: t, label: t };
                }),
                p.dtype,
                'str'
            ) +
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
        html += renderParamInput(nodeId, p, 'group_order_col', 'settings.groupOrderColumn', 'text', '');
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
var CHART_TYPES = ['bar', 'line', 'dual_line', 'stack_pct', 'topic_map', 'topic_terms', 'pie', 'scatter', 'histogram', 'box', 'heatmap', 'model_agreement', 'sankey', 'network', 'wordcloud', 'map'];

// The two renderers, kept equal to app.py's `_CHART_ENGINES` by the contract test.
var ENGINES = [
    { value: 'echarts', label: 'ECharts' },
    { value: 'matplotlib', label: 'Matplotlib' },
];

/* Field labels change meaning per chart type (e.g. x/y are two category
   dimensions for heatmap/sankey, not "category + value" like bar/line). */
var CHART_X_LABEL_KEY = {
    heatmap: 'settings.xFieldCat1', sankey: 'settings.sourceField', network: 'settings.sourceField',
    wordcloud: 'settings.textField', map: 'settings.regionField',
};
var CHART_Y_LABEL_KEY = { heatmap: 'settings.yFieldCat2', sankey: 'settings.targetField', network: 'settings.targetField' };
var CHARTS_WITH_Y_AS_CATEGORY = ['heatmap', 'sankey', 'network'];
var CHARTS_WITH_VALUE_FIELD = ['heatmap', 'sankey', 'network', 'wordcloud', 'map', 'topic_map'];
var CHARTS_NO_Y = ['histogram', 'wordcloud', 'map', 'stack_pct', 'model_agreement'].concat(CHARTS_WITH_Y_AS_CATEGORY);
// The right-hand scale, which only 双轴折线 asks for. Kept equal to the backend's
// ECHARTS_ONLY_TYPES by tests/unit/test_visualization.py, because the renderer that cannot
// draw two axes refuses by name and the panel must not offer it silently.
// 显著词图 asks for y2 too, but as a SECOND BAR SERIES on the same scale, not as a second
// axis — the two counts are in the same unit, and splitting them across scales would let a
// rare word look bigger than a common one.
var CHARTS_WITH_Y2 = ['dual_line', 'topic_terms'];
var CHARTS_WITH_LABEL = ['topic_map'];
var ECHARTS_ONLY_CHARTS = ['wordcloud', 'sankey', 'map', 'dual_line', 'topic_map', 'topic_terms', 'network', 'model_agreement'];
// The types that draw a vertical line at one x-axis label, so an event ("5/19 公安通报") sits
// on the curve it explains. Kept equal to the backend's ANNOTATED_TYPES by
// tests/unit/test_visualization.py: a box the figure cannot honour would drop the date in
// silence, which is the one outcome a reader of the figure must not be left with.
var CHARTS_WITH_ANNOTATIONS = ['bar', 'line', 'dual_line'];

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
                selectOptionTags(ENGINES, p.engine, 'echarts') +
                '</select></div>') +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartType') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'chart_type\',this.value)">' +
            selectOptionTags(
                TOKENIZE_CHART_TYPES.map(function (c) {
                    return { value: c, label: I18n.t('chart.' + c) };
                }),
                ct,
                'bar'
            ) +
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
        selectOptionTags(
            CHART_TYPES.map(function (c) {
                return { value: c, label: I18n.t('chart.' + c) };
            }),
            ct,
            'bar'
        ) +
        '</select></div>' +
        '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.engine') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'engine\',this.value)">' +
        selectOptionTags(ENGINES, p.engine, 'echarts') +
        '</select></div>';
    if (p.engine === 'matplotlib' && ECHARTS_ONLY_CHARTS.indexOf(ct) >= 0) {
        html += '<div class="settings-group" style="color:#e67e22;font-size:11px;">' + I18n.t('warn.echartsOnly') + '</div>';
    }
    if (ct === 'model_agreement') {
        // 模型一致率 reads the tidy multi-model table by three columns, not x/y: which names a
        // model, which holds its label, which aligns the same text across models. Defaults match
        // what the analysis step writes, so a fresh chart needs no typing.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.modelField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.model_field || '模型') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'model_field\',this.value)"></div>';
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agreementLabelField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.agreement_label_field || '') + '" placeholder="emotion / tendency / sentiment" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'agreement_label_field\',this.value)"></div>';
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.idField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.id_field || '原行') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'id_field\',this.value)"></div>';
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.modelAgreement') + '</div>';
    } else {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t(CHART_X_LABEL_KEY[ct] || 'settings.xField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.x_field || '') + '" placeholder="category / numeric column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'x_field\',this.value)"></div>';
    }
    if (ct === 'stack_pct') {
        // A 100%-stacked share takes its segments from a LIST of columns, not one y: each period
        // is normalised to 100%, so the box wants the positive/neutral/negative (or tendency,
        // emotion, …) columns that the analysis step just wrote.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.stackFields') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.stack_fields || '') + '" placeholder="积极占比, 中性占比, 消极占比" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'stack_fields\',this.value)"></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.stackFields') + '</div>';
    }
    if (CHARTS_WITH_Y_AS_CATEGORY.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t(CHART_Y_LABEL_KEY[ct]) + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.y_field || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y_field\',this.value)"></div>';
    } else if (CHARTS_NO_Y.indexOf(ct) < 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.yField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.y_field || '') + '" placeholder="optional: value column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>';
    }
    if (CHARTS_WITH_VALUE_FIELD.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.valueField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.value_field || '') + '" placeholder="optional: weight column (default = count)" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'value_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>';
    }
    if (ct === 'network') {
        // A co-occurrence graph over the whole candidate set is unreadable past ~20 words, and
        // its detail only surfaces on hover — which cannot be saved. Naming one word renders
        // that word's ego-network instead (it + the words directly co-occurring with it): a
        // persistent figure that exports exactly as it previews. Blank leaves the full graph.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.networkCenter') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.center_node || '') + '" placeholder="' + I18n.t('settings.networkCenterPlaceholder') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'center_node\',this.value)"></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.networkCenter') + '</div>';
    }
    if (CHARTS_WITH_LABEL.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.labelField') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.label_field || 'topic') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'label_field\',this.value)"></div>';
    }
    if (CHARTS_WITH_Y2.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.y2Field') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.y2_field || '') + '" placeholder="right-axis value column" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'y2_field\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.agg2') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'agg2\',this.value)">' +
            ['sum', 'mean', 'count', 'max', 'min'].map(function (a) { return '<option value="' + a + '"' + (p.agg2 === a ? ' selected' : '') + '>' + a + '</option>'; }).join('') +
            '</select></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.dualLine') + '</div>';
    }
    if (CHARTS_WITH_ANNOTATIONS.indexOf(ct) >= 0) {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chartAnnotations') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.annotations || '') + '" ' +
            'placeholder="2024-05-19=公安通报; 2024-04-23=遗体打捞" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'annotations\',this.value)"></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('hint.annotations') + '</div>';
    }
    if (ct === 'wordcloud') {
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.tokenize, false) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'tokenize\',this.checked)"> ' +
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
    // LaTeX export is orthogonal to the renderer: the node still draws its chart, and these add a
    // compilable figure source / a booktabs three-line table as .txt next to it.
    html += '<div class="settings-group"><label class="settings-checkbox-label">' +
        '<input type="checkbox" ' + (boolParam(p.emit_latex, true) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'emit_latex\',this.checked)"> ' +
        I18n.t('settings.emitLatex') + '</label>' +
        '<div style="font-size:11px;color:var(--text-dim);margin-top:2px;">' + I18n.t('settings.emitLatexHint') + '</div></div>';
    html += '<div class="settings-group"><label class="settings-checkbox-label">' +
        '<input type="checkbox" ' + (boolParam(p.emit_latex_table, true) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'emit_latex_table\',this.checked)"> ' +
        I18n.t('settings.emitLatexTable') + '</label></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.title') + '</label>' +
        '<input class="settings-input" value="' + escapeHtml(p.title || '') + '" ' +
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
        _chartPreviewName = node.title || nodeId;
        _chartPreviewNodeId = nodeId;
        var payload = {
            chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
            y_field: p.y_field, value_field: p.value_field, agg: p.agg,
            center_node: p.center_node,
            label_field: p.label_field, stack_fields: p.stack_fields,
            model_field: p.model_field, agreement_label_field: p.agreement_label_field, id_field: p.id_field,
            title: p.title, tokenize: boolParam(p.tokenize, false),
            emit_latex: boolParam(p.emit_latex, true), emit_latex_table: boolParam(p.emit_latex_table, true),
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
        /* The chart is re-rendered from the upstream node's rows. Right after a run
           those are still in the server's memory; after a page refresh AND a server
           restart they only exist in the run store, which is addressed by workflow —
           so send the same identity `previewData` sends, or a chart cannot be brought
           back once the process that ran it is gone. */
        payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
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
                var fv = _renderFailureView(result);
                if (!fv.note) showToast(I18n.t('toast.renderFailed') + ': ' + result.error);
                echartsDiv.innerHTML = fv.note
                    ? '<div class="dashboard-cell-note">' + escapeHtml(fv.message) + '</div>'
                    : '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:12px;">' + escapeHtml(fv.message) + '</div>';
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
            payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
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
    // The rows to train on may live only in the run store (a page refresh and a server
    // restart), and that store refuses a bare node id — name the workflow so training can
    // still find the labels after the process that produced them is gone.
    payload.workflow_name = workflow.runName();
    payload.model_type = modelType;
    payload.text_column = node.params.text_column || '正文';
    /* Which column holds the labels is the BACKEND's answer, not this file's. It used to be
       a ternary over two model names, so a third classifier trained itself from whichever
       column the `else` branch happened to name — and the training would have succeeded,
       silently, on the wrong column. `train_ml_model` reads the same table that decides
       what `mode='ml'` later loads, so the two cannot disagree. */
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
/* Which node the open preview belongs to: the saved picture has to be named after
   the chart the user was looking at, not after whichever node was clicked last. */
var _chartPreviewName = '';
/* The node id the preview was opened for, so the preview panel's 全屏 button can hand
   the very same chart to the full-screen window instead of guessing from a title. */
var _chartPreviewNodeId = '';
/* One ECharts instance for the full-screen window, disposed on close so reopening a
   different chart never paints into a stale canvas. */
var _chartFullscreenInstance = null;
var _chartFullscreenImage = '';
/* The raw option each surface was drawn from. The full-screen window reuses THIS rather
   than a live instance's getOption(), which returns an ECharts-resolved tree that is not
   meant to be fed back as an authoring option. */
var _chartPreviewOption = null;

/* ── Saving a drawn chart as a file ─────────────────────────────────────────
   A chart exists on screen in three places — the studio, the preview panel and a
   dashboard cell — and until now only the studio could put its picture on disk.
   All three go through the same endpoint (the studio's own /api/studio/save-image),
   and both engines are covered: an ECharts instance hands over a data URL, and a
   Matplotlib preview already IS one (the <img> the panel was given).
   A chart that was never drawn is refused with a sentence, because a silent button
   reads as "saving is broken" and the real cause is that there is no picture yet. */
async function saveChartPicture(dataUrl, name) {
    if (!dataUrl) {
        showToast(I18n.t('chart.saveNothing'));
        return null;
    }
    try {
        var resp = await fetch('/api/studio/save-image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl, name: name || 'chart' }),
        });
        var result = await resp.json();
        if (!result.ok) throw new Error(result.error || 'request failed');
        showToast(I18n.t('studio.saved').replace('{path}', result.filename));
        return result.filename;
    } catch (e) {
        showToast(I18n.t('studio.saveFailed') + ': ' + e.message);
        return null;
    }
}

function savePreviewImage() {
    var dataUrl = '';
    if (_chartPreviewInstance) {
        dataUrl = _chartPreviewInstance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
    } else {
        var img = document.getElementById('chart-preview-image');
        if (img && img.style.display !== 'none' && String(img.src || '').indexOf('data:image/') === 0) {
            dataUrl = img.src;
        }
    }
    return saveChartPicture(dataUrl, _chartPreviewName || 'chart-preview');
}

function saveDashboardImage(nodeId) {
    var inst = dashboard._instances[nodeId];
    var dataUrl = inst
        ? inst.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' })
        : dashboard._images[nodeId] || '';
    var node = canvas.nodes[nodeId];
    return saveChartPicture(dataUrl, (node && node.title) || nodeId);
}

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
        _chartPreviewOption = null;
        echartsDiv.style.display = 'none';
        echartsDiv.innerHTML = '';
        imgEl.style.display = 'block';
        imgEl.src = result.image;
    } else {
        _chartPreviewOption = result.option;
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
    _renderLatexBar(result);
}

/* The preview's LaTeX controls. ``emit_latex`` is on by default, so a chart node also files a
   compilable ``.txt``; here the user copies the source or downloads it. The file already lives in
   EXPORT_DIR (written by the node / render path), so download hits the same endpoint the exports
   browser uses; when a preview produced the text inline with no stored file, a Blob download covers it. */
var _lastLatex = '';
var _lastLatexTable = '';
var _lastLatexFile = '';
var _lastLatexTableFile = '';

function _renderLatexBar(result) {
    var panel = document.getElementById('chart-preview-panel');
    if (!panel) return;
    var old = document.getElementById('latex-action-bar');
    if (old) old.remove();
    _lastLatex = result.latex || '';
    _lastLatexTable = result.latex_table || '';
    _lastLatexFile = result.latex_file || '';
    _lastLatexTableFile = result.latex_table_file || '';
    if (!_lastLatex && !_lastLatexTable) return;
    var html = '';
    if (_lastLatex) {
        html += '<button class="menu-btn" onclick="copyLatexSource(\'fig\')">' + I18n.t('chart.copyLatex') + '</button>' +
            '<button class="menu-btn" onclick="downloadLatexFile(\'fig\')">' + I18n.t('chart.downloadLatex') + '</button>';
    }
    if (_lastLatexTable) {
        html += '<button class="menu-btn" onclick="copyLatexSource(\'tab\')">' + I18n.t('chart.copyTable') + '</button>' +
            '<button class="menu-btn" onclick="downloadLatexFile(\'tab\')">' + I18n.t('chart.downloadTable') + '</button>';
    }
    if (result.latex_error || result.latex_table_error) {
        html += '<span style="font-size:11px;color:#e67e22;">' + escapeHtml(String(result.latex_error || result.latex_table_error)) + '</span>';
    }
    var bar = document.createElement('div');
    bar.id = 'latex-action-bar';
    bar.className = 'latex-action-bar';
    bar.innerHTML = html;
    panel.appendChild(bar);
}

function copyLatexSource(kind) {
    var text = kind === 'tab' ? _lastLatexTable : _lastLatex;
    if (!text) return;
    var done = function () { if (typeof showToast === 'function') showToast(I18n.t('chart.copied')); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { _fallbackCopy(text); done(); });
    } else {
        _fallbackCopy(text); done();
    }
}

function _fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* clipboard blocked: the download path still works */ }
    document.body.removeChild(ta);
}

function downloadLatexFile(kind) {
    var name = kind === 'tab' ? _lastLatexTableFile : _lastLatexFile;
    if (name) {
        window.location.href = '/api/exports/download?name=' + encodeURIComponent(name);
        return;
    }
    var text = kind === 'tab' ? _lastLatexTable : _lastLatex;
    if (!text) return;
    var blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (kind === 'tab' ? 'latex-table' : 'latex-figure') + '.txt';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function toggleChartPreview() {
    var panel = document.getElementById('chart-preview-panel');
    panel.classList.remove('open');
    if (_chartPreviewInstance) {
        _chartPreviewInstance.dispose();
        _chartPreviewInstance = null;
    }
}

/* ── Full-screen chart window ──────────────────────────────────────────────
   A dashboard tile is ~300px; a figure meant for a paper has to be read at size.
   openChartFullscreen shows ONE chart in a draggable/resizable floating window (the
   same makeDraggable/makeResizable surface the preview panel uses). It sources the
   chart from what is already on screen — the board's stored option, then its
   matplotlib image, then the open preview — and only re-requests the render when the
   node has none of those. Nothing here pays for an LLM: a 主题概括 tile that has not
   run yet re-renders from the stored last-run rows via the SAME endpoint the cell used,
   and if that has no rows it says so rather than drawing an empty figure. */
async function openChartFullscreen(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var panel = document.getElementById('chart-fullscreen-panel');
    var titleEl = document.getElementById('chart-fullscreen-title');
    if (titleEl) titleEl.textContent = node.title || nodeId;
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, {
            minW: 320,
            minH: 240,
            maxW: window.innerWidth - 20,
            maxH: window.innerHeight - 20,
            onResize: function () { if (_chartFullscreenInstance) _chartFullscreenInstance.resize(); }
        });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var opt = dashboard._options && dashboard._options[nodeId];
    if (opt) { _paintFullscreenOption(opt); return; }
    var img = dashboard._images && dashboard._images[nodeId];
    if (img) { _paintFullscreenImage(img); return; }
    if (nodeId === _chartPreviewNodeId) {
        if (_chartPreviewOption) { _paintFullscreenOption(_chartPreviewOption); return; }
        var previewImg = document.getElementById('chart-preview-image');
        if (previewImg && previewImg.style.display !== 'none' && String(previewImg.src).indexOf('data:image/') === 0) {
            _paintFullscreenImage(previewImg.src);
            return;
        }
    }
    if (node.type !== 'visualize') return;
    var p = node.params;
    var payload = {
        chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
        y_field: p.y_field, value_field: p.value_field, agg: p.agg,
        center_node: p.center_node,
        y2_field: p.y2_field, agg2: p.agg2, annotations: p.annotations,
        label_field: p.label_field, stack_fields: p.stack_fields,
        model_field: p.model_field, agreement_label_field: p.agreement_label_field, id_field: p.id_field,
        title: p.title, tokenize: boolParam(p.tokenize, false),
        emit_latex: boolParam(p.emit_latex, true), emit_latex_table: boolParam(p.emit_latex_table, true),
        wordcloud_style: p.wordcloud_style || 'vibrant',
    };
    var upstream = canvas.getUpstreamNodeId(nodeId);
    if (!upstream) { showToast(I18n.t('dashboard.noData')); return; }
    payload.node_id = upstream;
    // Re-fetched from the server when this node was never drawn on this page (a reopened
    // canvas): name the workflow so the upstream rows resolve from the run store, not just
    // from a live process that may have restarted.
    payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
    try {
        var resp = await fetch('/api/visualize/render', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        var result = await resp.json();
        if (!result.ok) { var fv = _renderFailureView(result); _paintFullscreenError(fv.message, fv.note); return; }
        if (result.engine === 'matplotlib') _paintFullscreenImage(result.image);
        else _paintFullscreenOption(result.option);
    } catch (e) {
        _paintFullscreenError(e.message);
    }
}

function _disposeFullscreenInstance() {
    if (_chartFullscreenInstance) {
        _chartFullscreenInstance.dispose();
        _chartFullscreenInstance = null;
    }
}

function _paintFullscreenOption(option) {
    var div = document.getElementById('chart-fullscreen-echarts');
    var img = document.getElementById('chart-fullscreen-image');
    _disposeFullscreenInstance();
    _chartFullscreenImage = '';
    if (img) img.style.display = 'none';
    div.style.display = 'block';
    div.innerHTML = '';
    _chartFullscreenInstance = echarts.init(div);
    applyEchartsOption(_chartFullscreenInstance, option);
}

function _paintFullscreenImage(dataUrl) {
    var div = document.getElementById('chart-fullscreen-echarts');
    var img = document.getElementById('chart-fullscreen-image');
    _disposeFullscreenInstance();
    div.style.display = 'none';
    div.innerHTML = '';
    _chartFullscreenImage = dataUrl || '';
    if (img) { img.style.display = 'block'; img.src = dataUrl; }
}

function _renderFailureView(result) {
    /* 'No run data yet' is the expected state of a canvas nobody has executed, not a fault:
       the board answers it HTTP 200 with code no_run_data so a cold-load rehydrate does not
       fill the dev console with red 400s. Show it as a muted note and never a toast; anything
       else is a real failure and keeps its red styling. */
    if (result && result.code === 'no_run_data') return { note: true, message: I18n.t('chart.noRunData') };
    return { note: false, message: (result && result.error) || 'render failed' };
}

function _paintFullscreenError(message, isNote) {
    var div = document.getElementById('chart-fullscreen-echarts');
    var img = document.getElementById('chart-fullscreen-image');
    _disposeFullscreenInstance();
    _chartFullscreenImage = '';
    if (img) img.style.display = 'none';
    div.style.display = 'block';
    div.innerHTML = '<div class="' + (isNote ? 'dashboard-cell-note' : 'dashboard-cell-error') + '">' + escapeHtml(message) + '</div>';
}

function closeChartFullscreen() {
    document.getElementById('chart-fullscreen-panel').classList.remove('open');
    _disposeFullscreenInstance();
    _chartFullscreenImage = '';
}

function saveFullscreenImage() {
    var dataUrl = '';
    if (_chartFullscreenInstance) {
        dataUrl = _chartFullscreenInstance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' });
    } else if (_chartFullscreenImage) {
        dataUrl = _chartFullscreenImage;
    }
    var titleEl = document.getElementById('chart-fullscreen-title');
    return saveChartPicture(dataUrl, (titleEl && titleEl.textContent) || 'chart-fullscreen');
}

/* ── Data Preview: generic paginated table for any dataset ──
   Used by Analysis/Visualize/Output node settings ("Preview Data"
   button) to inspect real rows instead of only JSON or a chart. */
function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

/* Escape a value destined for `fn('…')` written INSIDE a double-quoted HTML
   attribute — the shape every panel table builds its row buttons with. Two
   contexts have to be satisfied in order: the JavaScript literal needs `\` and
   `'` (and a raw newline would end it), then the attribute needs `&` and `"`.
   `escapeHtml` alone cannot serve: it also turns `'` into `&#39;`, which the
   parser hands back as a bare quote inside the literal. A panel that skipped the
   second half is how one double quote in a file name closed the attribute and
   made whatever followed into markup — which is why the run panel's buttons carry
   only a hex run id. Names are user data, so they need this. */
function attrJsArg(value) {
    return String(value)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\r/g, '\\r')
        .replace(/\n/g, '\\n')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;');
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
                var fv = _renderFailureView(result);
                if (!fv.note) {
                    showToast(I18n.t('toast.previewFailed') + ': ' + result.error);
                    return;
                }
                document.getElementById('data-preview-table-wrap').innerHTML = '<div class="dashboard-cell-note">' + escapeHtml(fv.message) + '</div>';
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

// A stored data cell is the raw platform key (identity); the UI shows its localized name from the
// same catalog the rest of the page uses. Falls back to the raw value for a key the catalog lacks,
// so an unmapped platform still shows something instead of nothing.
function displayPlatform(v) {
    if (typeof I18n === 'undefined' || !I18n.t) return v;
    var key = 'platform.' + v;
    var label = I18n.t(key);
    return label && label !== key ? label : v;
}

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
            if (v === null || v === undefined) v = '';
            // The 平台 column stores the raw key (douyin, zhihu, …) as the row's storage identity;
            // the preview shows the localized name the rest of the UI already uses, but only when the
            // catalog knows it — an unmapped value falls back to the raw text rather than a blank.
            if (c === '平台' && v) v = displayPlatform(v);
            return '<td>' + escapeHtml(v) + '</td>';
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
    /* A Matplotlib cell has no instance to ask for a picture, but the server already
       sent one as a data URL; keeping it beside the instance is what lets the same
       存图 button serve both engines. */
    _images: {},
    /* The raw authoring option each ECharts cell was drawn from, so the 全屏 window
       reuses the exact option instead of an instance's resolved getOption() tree. */
    _options: {},

    async open() {
        var panel = document.getElementById('dashboard-panel');
        panel.classList.add('open');
        var grid = document.getElementById('dashboard-grid');
        grid.innerHTML = '';
        this._instances = {};
        this._images = {};
        this._options = {};

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
                '<div class="dashboard-cell-title">' + escapeHtml(node.title || id) +
                /* A node id is minted, never typed, so it is safe to put in the handler: the
                   name that could need escaping (the title) is read back at click time. */
                ' <button class="menu-btn" onclick="openChartFullscreen(\'' + id + '\')">' +
                I18n.t('chart.fullscreen') + '</button>' +
                ' <button class="menu-btn" onclick="saveDashboardImage(\'' + id + '\')">' +
                I18n.t('chart.saveImage') + '</button></div>' +
                '<div class="dashboard-cell-body"></div>';
            grid.appendChild(cell);
            self._renderCell(id, node, cell, grid);
        });
    },

    /* Is this cell still one of the board's cells?

       `open()` clears the grid and rebuilds it — on a refresh, a language switch or
       reopening the panel — so a cell from the previous board is an object with no place on
       the page. Tested by position rather than by selector because a node id is not a
       selector: a restored workflow may carry any id, and building a CSS string out of one
       asks the page to parse user data. */
    _isLiveCell(grid, cell) {
        if (!grid || !cell) return false;
        var cells = grid.querySelectorAll('.dashboard-cell');
        return Array.prototype.indexOf.call(cells, cell) >= 0;
    },

    async _renderCell(nodeId, node, cell, grid) {
        var body = cell ? cell.querySelector('.dashboard-cell-body') : null;
        if (!body) return;
        var p = node.params;
        var payload = {
            chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
            y_field: p.y_field, value_field: p.value_field, agg: p.agg,
            center_node: p.center_node,
            /* The board has to ask with the SAME fields the panel previews with. These three
               were left out, so every 双轴折线 cell answered "requires a second value field
               (y2)" — the cell that looked like a board bug was a payload bug — and every cell
               lost its event lines, which is the whole point of 图2/图8/图23~27. */
            y2_field: p.y2_field, agg2: p.agg2, annotations: p.annotations,
            /* The 主题距离图 / 流向图 read their Chinese bubble name from this field; a board
               that dropped it silently fell back to the Topic-1 code the user replaced. */
            label_field: p.label_field,
            /* The 占比堆叠图 draws its segments from a column list, not one y; a board that
               dropped it asked the service for a stacked field and got an opaque refusal. */
            stack_fields: p.stack_fields,
            model_field: p.model_field, agreement_label_field: p.agreement_label_field, id_field: p.id_field,
            title: p.title, tokenize: boolParam(p.tokenize, false),
            emit_latex: boolParam(p.emit_latex, true), emit_latex_table: boolParam(p.emit_latex_table, true),
            wordcloud_style: p.wordcloud_style || 'vibrant',
        };
        var upstream = canvas.getUpstreamNodeId(nodeId);
        if (!upstream) {
            body.innerHTML = '<div class="dashboard-cell-error">' + I18n.t('dashboard.noData') + '</div>';
            return;
        }
        payload.node_id = upstream;
        // A rebuilt board re-renders every cell from the server; name the workflow so a
        // cell still resolves its upstream rows after a page refresh AND a server restart,
        // when the in-memory result that first painted it is gone.
        payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';

        try {
            var resp = await fetch('/api/visualize/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            /* Re-checked after the await: `echarts.init` on a cell the board has since
               replaced paints nothing and still registers the instance, which is then
               resized on every window resize for the life of the page and never disposed.
               No chart, no instance and no error text is the honest outcome. */
            if (!this._isLiveCell(grid, cell)) return;
            if (!result.ok) {
                var fv = _renderFailureView(result);
                body.innerHTML = '<div class="' + (fv.note ? 'dashboard-cell-note' : 'dashboard-cell-error') + '">' + escapeHtml(fv.message) + '</div>';
                return;
            }
            if (result.engine === 'matplotlib') {
                body.innerHTML = '<img src="' + escapeHtml(result.image) + '" />';
                this._images[nodeId] = result.image;
            } else {
                var inst = echarts.init(body);
                this._instances[nodeId] = inst;
                this._options[nodeId] = result.option;
                applyEchartsOption(inst, result.option);
            }
        } catch (e) {
            if (!this._isLiveCell(grid, cell)) return;
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
            /* Kept, not only drawn: this table and the filter select are built in JS,
               so `I18n.apply()` never reaches them — a language switch has to redraw
               from what is already on hand instead of asking the server again. */
            this._runs = result;
            this._renderRuns();
        } catch (e) { /* non-fatal */ }
    },

    _renderRuns() {
        var result = this._runs;
        if (!result) return;
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
    },

    onLanguageChange() {
        /* Same rule as the run-records and export panels: the header row is a
           catalogue string, so switching to English with this panel open used to
           leave the whole table Chinese until it was closed and opened again. */
        var panel = document.getElementById('history-panel');
        if (!panel || !panel.classList.contains('open')) return;
        this._renderRuns();
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
        'Surprise': '#5f8a8a',
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

/* Collapse / expand the node library. It floats over the canvas, so a wide layout
   hides behind it; the toggle keeps the header row visible so there is always a way
   back, and moves the glyph + the accessible label to say which way it will go. */
function togglePalette() {
    var panel = document.getElementById('node-palette');
    var btn = panel.querySelector('.palette-toggle');
    var collapsed = panel.classList.toggle('collapsed');
    btn.textContent = collapsed ? '+' : '−';
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    btn.title = I18n.t(collapsed ? 'palette.expand' : 'palette.collapse');
}

/* ── Outline sidebar (right) ────────────────────────────────────────── */
/* A flat map of every node on the canvas: click a row and the camera jumps to it at a
   readable size. The list is rebuilt from the model inside canvas.saveState() (canvas.js),
   which is the single chokepoint every structural change passes through — so it can never
   drift from the graph, and this object owns only the DOM and the jump. Rows are built with
   createElement + textContent (never an innerHTML string keyed by the node id), because a
   workflow file can author any id and an inline handler would have to re-escape it. */
const Outline = {
    /* The rows as data (no DOM). `off` = outside the effective graph (disabled, starved,
       or its type switched off): still listed — the outline is a complete map, not a run
       preview — but dimmed so it does not read as live. */
    _collect() {
        var live = canvas.effectiveIds();
        return Object.keys(canvas.nodes).map(function (id) {
            var n = canvas.nodes[id];
            return {
                id: id,
                type: n.type,
                label: n.title || I18n.t('node.' + n.type),
                off: live.indexOf(id) < 0,
            };
        });
    },

    _tag(type) {
        var m = {
            name: 'NAM', source: 'SRC', upload: 'UPL', resume: 'RSM', process: 'PRC',
            analysis: 'ANL', tokenize: 'TKN', visualize: 'VIZ', compile: 'CMP', output: 'OUT', comment: 'CMT',
        };
        return m[type] || String(type).slice(0, 3).toUpperCase();
    },

    render() {
        var list = document.getElementById('outline-list');
        if (!list) return;
        var rows = this._collect();
        list.textContent = '';
        if (rows.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'outline-empty';
            empty.textContent = I18n.t('outline.noNodes');
            list.appendChild(empty);
            return;
        }
        var self = this;
        rows.forEach(function (r) {
            var row = document.createElement('div');
            row.className = 'outline-row' + (r.off ? ' outline-off' : '');
            row.dataset.node = r.id;
            row.title = r.label;
            var chip = document.createElement('span');
            chip.className = 'outline-type';
            chip.textContent = self._tag(r.type);
            var name = document.createElement('span');
            name.className = 'outline-name';
            name.textContent = r.label;
            row.appendChild(chip);
            row.appendChild(name);
            row.addEventListener('click', function () { self.focus(r.id); });
            list.appendChild(row);
        });
        this._markActive();
    },

    focus(id) {
        if (!canvas.nodes[id]) return;
        canvas.selectNode(id);
        canvas.centerOnNode(id);
        this._markActive();
    },

    _markActive() {
        var list = document.getElementById('outline-list');
        if (!list) return;
        var sel = canvas.selectedNode;
        list.querySelectorAll('.outline-row').forEach(function (row) {
            row.classList.toggle('outline-active', row.dataset.node === sel);
        });
    },

    toggle() {
        var panel = document.getElementById('outline-panel');
        if (!panel) return;
        var btn = panel.querySelector('.outline-toggle');
        var collapsed = panel.classList.toggle('collapsed');
        if (btn) {
            btn.textContent = collapsed ? '+' : '−';
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            btn.title = I18n.t(collapsed ? 'outline.expand' : 'outline.collapse');
        }
        /* Kept beside the camera in the draft, not in getState(): a collapse is a view
           preference, never an undo step. Its own key so toggling cannot churn a model save. */
        try {
            localStorage.setItem('crawler_outline_collapsed', collapsed ? '1' : '');
        } catch (e) { /* a blocked store is not worth losing the sidebar over */ }
    },

    init() {
        var panel = document.getElementById('outline-panel');
        if (!panel) return;
        var collapsed = false;
        try {
            collapsed = localStorage.getItem('crawler_outline_collapsed') === '1';
        } catch (e) { collapsed = false; }
        if (collapsed) panel.classList.add('collapsed');
        var btn = panel.querySelector('.outline-toggle');
        if (btn) {
            btn.textContent = collapsed ? '+' : '−';
            btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            btn.title = I18n.t(collapsed ? 'outline.expand' : 'outline.collapse');
        }
        this.render();
    },
};

function toggleOutline() {
    Outline.toggle();
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
    /* The 已禁用/无输入 badge is worded by ``applyDisabledVisuals``, which per-node
       ``updateNodeDisplay`` never touches — so a language switch re-stamped the title, the
       summary and the tooltips and left 「DISABLED」 sitting on the corner of a node that
       had just turned Chinese. One call, because the state is computed for the whole canvas
       at once and asking per node would recompute the same answer N times. */
    canvas.applyDisabledVisuals();
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
    /* The saved-logins dock is JS-rendered like those two, and so are the lines the Cookie
       dialog paints under the account box — same bug class, same one-call fix. The dialog's
       own repaint is cheap (cached rows, no request) and it is the panel a user is most
       likely to be looking at when he switches language to read a platform's steps. */
    if (typeof cookiesManager !== 'undefined') cookiesManager.onLanguageChange();
    if (typeof renderCookieAccountStatus === 'function' && document.getElementById('cookie-account-status')) {
        renderCookieAccountStatus();
        renderCookieGuide();
    }
    /* Both of these had the method and never got the call, so their tables kept the
       old language while the rest of the page re-stamped around them. `datasetManager`
       is a top-level `var`, which does make it a window property — but the guard is
       written against the binding for the same reason the resume bar once wasn't. */
    if (typeof datasetManager !== 'undefined') datasetManager.onLanguageChange();
    if (typeof historyPanel !== 'undefined') historyPanel.onLanguageChange();
    if (typeof wfFiles !== 'undefined') wfFiles.onLanguageChange();
}

function showToast(msg, ms) {
    var toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.classList.add('show');
    /* A longer message has to be readable, not merely present: the fixed 2.5 s was
       written for one short sentence and the multi-problem toast below carries a
       line per problem. */
    setTimeout(function () { toast.classList.remove('show'); }, ms || 2500);
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

/* #177 — the "clear console before each run" option asks for a hard blank slate, not
   the soft one clearConsole gives: a new run must not briefly show the PREVIOUS run's
   per-workflow tabs. So the tab bar itself and every cursor go too. pollStatus rebuilds
   tabs from the fresh run's data, and resetting `all.seen` to 0 is exactly the "server
   buffer was zeroed, read from the start" state the poll already handles. */
function resetConsoleForNewRun() {
    var out = document.getElementById('console-output');
    if (out) out.innerHTML = '';
    var tabs = document.getElementById('console-tabs');
    if (tabs) tabs.innerHTML = '';
    consoleViews.all = { seen: 0, lines: [] };
    consoleViews.wf = {};
    _wfActiveTab = 'all';
}

function _clearConsoleBeforeRun() {
    /* AppSettings is a top-level const (never on window), so guard the binding itself.
       Unpulled settings answer false — a console nobody configured stays as before. */
    return typeof AppSettings !== 'undefined' &&
        !!(AppSettings._values && AppSettings._values.clear_console_before_run);
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
                    '<td>' + (canKill ? '<button class="proc-kill-btn" data-ident="' + escapeHtml(t.ident) + '" onclick="killProcess(this)">' + I18n.t('processes.kill') + '</button>' : '') + '</td>' +
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
                        '<td>' + escapeHtml(t.name) + '</td>' +
                        '<td>' + typeLabel + '</td>' +
                        '<td>' + (t.alive ? '<span class="proc-ok">alive</span>' : '<span class="proc-err">dead</span>') + '</td>' +
                        '<td>' + (canKill ? '<button class="proc-kill-btn" data-ident="' + escapeHtml(t.ident) + '" onclick="killProcess(this)">' + I18n.t('processes.kill') + '</button>' : '') + '</td>' +
                        '</tr>';
                });
                html += '</table>';
                out.innerHTML = html;
            }).catch(function () { });
    }, 1000);
}

/* Custom Dialog - replaces browser prompt() */
function showDialog(opts) {
    return new Promise(function (_resolve) {
        var overlay = document.getElementById('dialog-overlay');
        var msgEl = document.getElementById('dialog-message');
        var inputArea = document.getElementById('dialog-input-area');
        var inputEl = document.getElementById('dialog-input');
        var listArea = document.getElementById('dialog-list-area');
        var actionsEl = document.getElementById('dialog-actions');

        /* The dialog is dismissable like a modal: a drawn close (X), a click on the
           backdrop, and Esc all resolve the "no answer" value. The cancel result
           defaults to null so a caller that awaits a typed string or a chosen value
           sees a clean non-answer (never a stray false that a `=== 'x'` check might
           treat as a pick). A dialog may opt out with `dismissable: false`. While a
           login browser is in flight (cookieJob.active) dismissal is refused — those
           Done/Cancel buttons are the only safe exit, or the login window orphans. */
        var dismissable = opts.dismissable !== false;
        // The drawn close (X) can be hidden independently of backdrop/Esc: an
        // information dialog (采集建议) or one that already has its own buttons
        // (the Profile-clash prompt) reads cleaner without a corner X, yet stays
        // dismissable by clicking outside or Esc.
        // The corner X is opt-in: only an information dialog with no buttons of its
        // own (采集建议) needs it. Every other dialog already carries its own action
        // buttons, so it stays X-free; backdrop/Esc still dismiss any dialog.
        var showClose = opts.showClose === true && dismissable;
        var cancelValue = opts.cancelValue !== undefined ? opts.cancelValue : null;
        var dismissed = false;
        var closeBtn = null;
        function onBackdrop(e) {
            if (e.target === overlay && !cookieJob.active) {
                // Do not let this click reach the top-menu outside-click handler,
                // which would also collapse the submenu the dialog was opened from.
                e.stopPropagation();
                resolve(cancelValue);
            }
        }
        function onEsc(e) { if (e.key === 'Escape' && !cookieJob.active) resolve(cancelValue); }
        function resolve(value) {
            if (dismissed) return;
            dismissed = true;
            overlay.classList.remove('open');
            overlay.removeEventListener('click', onBackdrop);
            document.removeEventListener('keydown', onEsc);
            if (closeBtn && closeBtn.parentNode) closeBtn.parentNode.removeChild(closeBtn);
            _resolve(value);
        }

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

        /* A small form — checkboxes and one field or two — rendered into the
           dialog instead of a bare button set (the report dialog is its only
           user). Each control is read back by its own id, never by querying the
           container, so a caller or a test can drive one switch on its own. A
           toggle is a boolean the user chose; "which sections" and "how many
           rows" therefore do not have to be enumerated as button combinations. */
        var toggleIds = (opts.toggles || []).map(function (t) { return t.id; });
        var fieldIds = (opts.fields || []).map(function (f) { return f.id; });
        if (toggleIds.length) {
            listArea.style.display = 'block';
            opts.toggles.forEach(function (t) {
                var label = document.createElement('label');
                label.className = 'dialog-toggle';
                var box = document.createElement('input');
                box.type = 'checkbox';
                box.id = t.id;
                box.checked = t.checked !== false;
                label.appendChild(box);
                label.appendChild(document.createTextNode(' ' + t.label));
                listArea.appendChild(label);
            });
        }
        if (fieldIds.length) {
            listArea.style.display = 'block';
            opts.fields.forEach(function (f) {
                var row = document.createElement('label');
                row.className = 'dialog-field';
                row.appendChild(document.createTextNode(f.label));
                var box = document.createElement('input');
                /* The report dialog's 行数 box is a number input; without the house class it
                   rendered as OS chrome (a bevelled white box) beside a text input that already
                   wears .settings-input, so one form had two skins. Same class, same border,
                   same focus ring, transparent ground — the number spinners are already stripped
                   by the global ``input[type=number]`` rule. */
                box.className = 'settings-input';
                box.type = f.type || 'number';
                box.id = f.id;
                if (f.value !== undefined) box.value = f.value;
                if (f.min !== undefined) box.min = f.min;
                if (f.max !== undefined) box.max = f.max;
                row.appendChild(box);
                listArea.appendChild(row);
            });
        }
        function collectForm() {
            var toggles = {};
            toggleIds.forEach(function (id) {
                var el = document.getElementById(id);
                toggles[id] = !!(el && el.checked);
            });
            var fields = {};
            fieldIds.forEach(function (id) {
                var el = document.getElementById(id);
                fields[id] = el ? el.value : '';
            });
            return { toggles: toggles, fields: fields };
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
                       which button was pressed. `withInput` returns both, and
                       `collect` returns the checkbox / field states on top. */
                    if (b.collect) {
                        var got = collectForm();
                        resolve({
                            value: b.value,
                            input: opts.input ? inputEl.value : undefined,
                            toggles: got.toggles,
                            fields: got.fields,
                        });
                        return;
                    }
                    if (b.withInput && opts.input) {
                        resolve({ value: b.value, input: inputEl.value });
                        return;
                    }
                    resolve(b.value !== undefined ? b.value : (opts.input ? inputEl.value : true));
                });
                actionsEl.appendChild(btn);
            });
        }

        var box = document.getElementById('dialog-box');
        if (box) {
            var stale = box.querySelector('.dialog-close');
            if (stale) stale.parentNode.removeChild(stale);
        }
        if (showClose && box) {
            closeBtn = document.createElement('button');
            closeBtn.className = 'dialog-close';
            closeBtn.type = 'button';
            closeBtn.setAttribute('data-i18n-title', 'settings.close');
            closeBtn.setAttribute('aria-label', 'Close');
            closeBtn.innerHTML =
                '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false">' +
                '<path d="M6 6l12 12M18 6L6 18"/></svg>';
            closeBtn.addEventListener('click', function (e) {
                if (e) e.stopPropagation();
                if (cookieJob.active) return;
                resolve(cancelValue);
            });
            // Insert first so DOM order matches the visual corner position too,
            // not just the absolute CSS placement.
            box.insertBefore(closeBtn, box.firstChild);
        }
        if (dismissable) {
            overlay.addEventListener('click', onBackdrop);
            document.addEventListener('keydown', onEsc);
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
var cookieFlowsLoading = false;
/* The profile state comes from its own endpoint (it is the same table the settings panel
   renders) and is cached by platform name, because the one thing the user cannot see from
   outside is that the cookie file in data/cookies is NOT the session this profile holds. */
var cookieProfiles = {};
var cookieProfilesLoaded = false;
var cookieProfilesLoading = false;

function loadCookieProfiles() {
    /* In-flight as well as loaded: the guide repaints when its own fetch lands, and a
       second call during that window would buy the same table twice — the reason the
       panel is allowed to cache it at all is that it is fetched once. A failed read
       leaves ``loaded`` false, so the next render asks again. */
    if (cookieProfilesLoaded || cookieProfilesLoading) return;
    cookieProfilesLoading = true;
    fetchJSON('/api/browser/profiles').then(function (result) {
        cookieProfilesLoading = false;
        if (!result || !result.ok) return;
        var byName = {};
        (result.profiles || []).forEach(function (row) {
            byName[row.platform] = row;
        });
        cookieProfiles = byName;
        cookieProfilesLoaded = true;
        renderCookieGuide();
    });
}

function renderCookieGuide() {
    var body = document.getElementById('cookie-guide-body');
    if (!body) return;
    var platform = document.getElementById('cookie-platform').value;
    loadCookieProfiles();
    // The account offers follow the platform the guide is being drawn for.
    renderCookieAccounts();
    if (!cookieFlows) {
        body.textContent = I18n.t('cookie.guideLoading');
        /* The same in-flight guard the profile table needs: this function is called again
           when either fetch lands, and without it a repaint mid-flight bought the flow a
           second time for a panel that caches it precisely because it is fetched once. */
        if (cookieFlowsLoading) return;
        cookieFlowsLoading = true;
        fetchJSON('/api/cookies/flow').then(function (result) {
            cookieFlowsLoading = false;
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
    /* The staleness sentence is only ever true because the server measured it: the
       profile records WHICH cookie file went into it, and the answer here is "a
       different one is sitting in data/cookies now". Without that hint the button is
       a mystery door, and with it the panel says the one thing the user cannot
       find out from outside: that their re-taken cookie is not being used yet. */
    var profile = cookieProfiles[platform];
    if (profile && profile.needs_refresh) {
        lines.push(I18n.t('cookie.refreshHint'));
    }
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
        if (!result.ok) {
            statusEl.textContent = I18n.t('cookie.unreachable');
            return;
        }
        /* One read, four renderers. The rows answer per (platform, account), and the
           account line has to repaint on every keystroke in the box — refetching for a
           character typed would make the panel ask the server eight file listings per
           name. */
        cookieRows = result.rows || [];
        var lines = [];
        Object.keys(result.cookies).forEach(function (p) {
            /* Both halves come from the catalog. Written raw this line read
               "zhihu: OK" in a Chinese interface — and a bare "OK" overstates
               the fact anyway: what is known here is that a jar is saved,
               not that the session inside it still opens pages (that is what
               验证 Cookie and the pre-run probe answer). */
            var saved = result.cookies[p];
            // A named account is said by its WORD: "知乎: 未存（work）" tells the
            // default file is empty while a second login exists — two facts
            // the old boolean could not separate. Joined raw, the default
            // account came out as an empty name ("知乎: 已存（, work）").
            var names = cookieRows
                .filter(function (row) {
                    return row.platform === p;
                })
                .map(cookieAccountLabel);
            var tag = names.length ? ' (' + names.join(', ') + ')' : '';
            lines.push(
                I18n.t('platform.' + p) + tag + ': ' + I18n.t(saved ? 'cookie.savedYes' : 'cookie.savedNo')
            );
        });
        statusEl.textContent = lines.join('  |  ');
        renderCookieAccounts();
        renderCookieAccountStatus();
        renderCookieManager();
    });
}

function cookieRowFor(platform, account) {
    /* The row for exactly this pair, or null when nothing is saved under it.
       Matched on the account KEY and never on the label: 「默认账号」 is how one account is
       worded, and a label match would also answer for a login the user happened to name
       that. Both spellings of the default fold to the same key, so a row written before
       multi-account and one named ``default`` are found by either. */
    var want = cookieAccountKey(account);
    for (var i = 0; i < cookieRows.length; i++) {
        var row = cookieRows[i];
        if (row.platform === platform && cookieAccountKey(row.account) === want) return row;
    }
    return null;
}

function cookieAccountLabel(row) {
    if (!row) return '';
    // The backend knows which names IT generated (default, default2) and sends a
    // catalogue key with its arguments; anything else the user typed is shown exactly
    // as typed, because a name they chose is not this program's word to translate.
    return row.label_key ? I18n.t(row.label_key, row.label_args || {}) : cookieAccountKey(row.account);
}

function cookieAccountWord(account) {
    /* The WORD for an account key, in both of its spellings: the default has a name like any
       other account, and what the user reads for it is 默认账号. */
    return cookieAccountKey(account) === COOKIE_DEFAULT_ACCOUNT ? String(I18n.t('cookies.accountDefault')) : cookieAccountKey(account);
}

function renderCookieAccountStatus() {
    /* The line under the box: what THIS account holds, changing as the box changes.
       It answers from the cached rows, so it is a re-render and not a request — the
       question "have I saved a login under that name" is already in the payload. */
    var el = document.getElementById('cookie-account-status');
    if (!el) return;
    var select = document.getElementById('cookie-platform');
    var platform = select ? select.value : '';
    var account = cookieAccount();
    var row = cookieRowFor(platform, account);
    var parts = [
        I18n.t('cookies.accountStatusHead', {
            platform: I18n.t('platform.' + platform),
            account: cookieAccountWord(account),
        }),
    ];
    if (!row) {
        parts.push(I18n.t('cookies.accountStatusNone'));
    } else {
        parts.push(I18n.t('cookies.accountStatusSaved', { n: row.entries, when: row.saved_at }));
    }
    el.textContent = parts.join(' — ');
}

/* The profile sentence is gone (user, 2026-09-28): an account, its cookie file and its
   browser directory are one thing now — saving a cookie plants it into that account's own
   profile by itself — so 「它的浏览器里就是这份 Cookie」 described a state the panel is
   responsible for, not one the user can act on. Same for 「其中 N 条关窗口即失效」: since
   #148 every crawl runs in a headless browser that carries a desktop fingerprint, and a
   session cookie's lifetime is not a fact anybody chooses. What stays readable is the one
   case that is still the user's to know about: a cookie re-saved while its profile was
   held by a running crawl (``cookie.refreshHint``). */

function setCookieJobUI(on) {
    var actions = document.getElementById('cookie-job-actions');
    /* A verification resolves itself — showing "Done — I logged in" over it
       would invite a click that means nothing (and the server refuses it). */
    if (actions) actions.style.display = on && cookieJob.kind === 'login' ? 'flex' : 'none';
    ['cookie-platform', 'cookie-wait', 'cookie-json', 'cookie-entry', 'cookie-account'].forEach(function (id) {
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
                        : I18n.t('cookie.waiting', { platform: platformLabels([s.platform]) });
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
            statusEl.textContent = I18n.t('cookie.savedN', { platform: platformLabels([s.platform]), n: s.count });
            showToast(I18n.t('toast.cookiesSaved') + ' - ' + platformLabels([s.platform]));
            refreshCookieStatus();
        } else if (s.phase === 'verified') {
            statusEl.textContent = (s.lines || []).join('\n');
        } else if (s.phase === 'cancelled') {
            statusEl.textContent = I18n.t('cookie.cancelledMsg', { platform: platformLabels([s.platform]) });
        } else if (s.phase === 'error') {
            statusEl.textContent = I18n.t('cookie.failed').replace('{err}', s.error || '');
        }
    });
}

function openCookieDialog(platform, account) {
    var dialog = document.getElementById('cookie-dialog');
    /* An optional platform AND account: the pre-run block sends the user here with the dead
       session already selected, because a panel that opens on whatever was last picked makes
       them hunt for the one login that is broken — and on a platform that holds several,
       naming the platform alone still leaves the wrong account in the box. */
    var select = document.getElementById('cookie-platform');
    var landed = false;
    if (platform && select) {
        var known = Array.prototype.some.call(select.options || [], function (option) {
            return option.value === platform;
        });
        if (known) {
            select.value = platform;
            landed = true;
            /* The visible half of an enhanced select is a span CustomSelect paints from the
               option text (the native control is kept at 1px and opacity 0), and it re-reads
               itself only on a pick or a refresh. Setting ``value`` alone lands the answer
               for every button below while the user still sees the platform they came in
               with — which is how 「打开」 in the saved-logins list read as doing nothing. */
            if (window.CustomSelect) CustomSelect.refreshAll();
        }
    }
    /* The account FOLLOWS the platform. Writing the box while the select refused to move
       would leave the panel showing one platform and naming another one's login — and
       every button below acts on the pair, so a half-landing is worse than none. */
    if (landed && account !== undefined) {
        setCookieAccountBox(account);
    }
    if (platform) {
        /* Naming a platform is never a toggle: the toolbar button opens and shuts
           this panel, and closing the panel over the answer the user was just sent
           to look at is the opposite of what a refusal wants. */
        dialog.classList.add('open');
    } else {
        dialog.classList.toggle('open');
        if (!dialog.classList.contains('open')) return;
    }
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
    /* The candidate popup lives on <body>, outside the dialog it belongs to: closing the
       panel over an open popup would leave a list of accounts floating on the canvas. */
    hideCookieAccountCandidates();
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
            body: JSON.stringify({ platform: platform, cookies: cookies, account: cookieAccount() }),
        })
            .then(function (result) {
                if (result.ok) {
                    var savedWho = entryLabels([{ platform: platform, account: cookieAccount() }]);
                    showToast(I18n.t('toast.cookiesSaved') + ' - ' + savedWho);
                    document.getElementById('cookie-json').value = '';
                    /* The reply says what happened to the browser that crawls with this login —
                       planted, or deferred because that account's profile is held right now.
                       Showing only my own 「已保存」 toast hides the half the user acts on, and the
                       status refresh must not run first either: it answers asynchronously and
                       would overwrite this sentence a moment later. */
                    var statusEl = document.getElementById('cookie-status');
                    if (result.profile_note && statusEl) {
                        statusEl.textContent = result.message || '';
                    } else {
                        refreshCookieStatus();
                    }
                    // The login is on disk now even when its profile plant was deferred, so
                    // the data-source account box must offer it without a page reload.
                    refreshAccountCandidates();
                } else {
                    showToast(I18n.t('cookie.failed', { err: result.error || '' }));
                }
            });
    } catch (e) {
        showToast(I18n.t('cookie.invalidJson', { err: e.message }));
    }
}

async function deleteCookie(platform, account) {
    /* Remove ONE saved cookie file. Called with nothing it speaks for the panel's own
       selection; a management row calls it WITH its row, because deleting whatever happens
       to be typed in the box is a different login than the one that was clicked.

       The confirmation has to be honest about what a file is: since a browser profile
       imports it once and is never re-planted, a platform that has logged in inside its own
       profile keeps that session, and deleting the snapshot does not sign it out. Saying
       「已删除，等于退出登录」 here would send the user to re-log in a session that is still
       live — the response's own profile_holds line says which of the two just happened. */
    var statusEl = document.getElementById('cookie-status');
    var named = platform !== undefined && platform !== null && platform !== '';
    if (!named) platform = cookiePlatform();
    if (!platform) return;
    if (account === undefined || account === null) account = cookieAccount();
    /* Two fixes in one line. The template names the platform TWICE and the old call used
       `.replace('{platform}', …)`, which fills the first occurrence only — so the user read a
       literal `{platform}` in the middle of a Chinese sentence, next to a raw `zhihu` key.
       And the dialog has to name the SESSION it is about to delete: one platform holds
       several logins, and 「删除 知乎 的 Cookie 文件」 while the account box says `work`
       describes a file this request does not touch. */
    var who = entryLabels([{ platform: platform, account: account }]);
    var answer = await showDialog({
        message: I18n.t('dialog.cookieDelete', { platform: who }),
        buttons: [
            { label: I18n.t('dialog.cookieDeleteYes'), value: 'delete', primary: true },
            { label: I18n.t('dialog.cancel'), value: null },
        ],
    });
    if (answer !== 'delete') return;
    var result = await fetchJSON('/api/cookies/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, account: String(account || '') }),
    });
    if (result.ok) {
        showToast(result.message || I18n.t('toast.cookieDeleted', { platform: who }));
        if (statusEl) statusEl.textContent = result.message || '';
        refreshCookieStatus();
        refreshAccountCandidates();
    } else if (statusEl) {
        statusEl.textContent = result.error || I18n.t('cookie.failed').replace('{err}', '');
    }
}

async function deleteCookieProfile(platform, account) {
    /* Throw away one account's browser PROFILE directory — the device itself, not the cookie
       file. The two are independent on purpose: 「删除 Cookie」 removes only the snapshot a
       throwaway browser is planted from, and a platform crawled inside its own profile keeps
       its live session in that profile, so retiring the device needs this separate action.

       The default account is refused here as well as in the panel button: its browser data is
       the platform root folder that nests every named account, so deleting it would silently
       wipe them all — the same structural reason rename refuses the default. The server repeats
       the refusal, so a hand-built request cannot reach the platform root either. */
    var from = cookieAccountKey(account);
    if (!platform || from === COOKIE_DEFAULT_ACCOUNT) {
        showToast(I18n.t('cookies.profileDeleteDefaultRefused'));
        return;
    }
    var answer = await showDialog({
        message: I18n.t('dialog.profileDelete', {
            platform: I18n.t('platform.' + platform),
            account: cookieAccountWord(from),
        }),
        buttons: [
            { label: I18n.t('dialog.profileDeleteYes'), value: 'delete', primary: true },
            { label: I18n.t('dialog.cancel'), value: null },
        ],
    });
    if (answer !== 'delete') return;
    var result = await fetchJSON('/api/profiles/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, account: from }),
    });
    var statusEl = document.getElementById('cookie-status');
    if (result.ok) {
        showToast(result.message || I18n.t('toast.profileDeleted'));
        if (statusEl) statusEl.textContent = result.message || '';
        // The device is gone, so the profile chip and the whole row state must be re-read.
        refreshCookieStatus();
        refreshAccountCandidates();
    } else if (statusEl) {
        statusEl.textContent = result.error || '';
    }
}

async function renameCookieAccount(platform, account) {
    /* Give one saved login a new name. The box is prefilled with the name it carries now, so
       what the user edits is the thing being renamed — and the answer is sent as the pair
       (platform, account), never as "whatever is typed in the panel's box", because that box
       is a different control on a different panel and may name another account by now.

       The server moves the cookie file AND that account's own browser directory, or neither,
       and says which of the two happened; a name that only half-moved would leave the account
       pointing at a device that is still called the old one. */
    var from = cookieAccountKey(account);
    if (!platform || from === COOKIE_DEFAULT_ACCOUNT) {
        showToast(I18n.t('cookies.renameDefaultRefused'));
        return;
    }
    var answer = await showDialog({
        message: I18n.t('dialog.cookieRename', { account: cookieAccountWord(from), platform: I18n.t('platform.' + platform) }),
        input: { value: from, placeholder: I18n.t('cookies.renamePlaceholder') },
        buttons: [
            { label: I18n.t('dialog.confirm'), primary: true },
            { label: I18n.t('dialog.cancel'), value: null },
        ],
    });
    // An input dialog answers with the TYPED text (the confirm button carries no value of its
    // own — that is the rule in AGENTS), so a dismissed dialog is the only null here.
    if (!answer) return;
    var to = cookieAccountKey(answer);
    if (to === from) {
        showToast(I18n.t('cookies.renameSame'));
        return;
    }
    var result = await fetchJSON('/api/cookies/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, account: from, to: to }),
    });
    var statusEl = document.getElementById('cookie-status');
    if (result.ok) {
        showToast(result.message || I18n.t('toast.cookieRenamed'));
        if (statusEl) statusEl.textContent = result.message || '';
        // The box follows the name: a panel still typing the old one would save a NEW login
        // under the name that was just freed, which is the opposite of what was asked for.
        setCookieAccountBox(result.account);
        refreshCookieStatus();
        refreshAccountCandidates();
    } else if (statusEl) {
        statusEl.textContent = result.error || I18n.t('cookie.failed').replace('{err}', '');
        showToast(result.error || I18n.t('cookie.failed').replace('{err}', ''));
    }
}

function cookieEntryUrl() {
    var el = document.getElementById('cookie-entry');
    return el ? String(el.value || '').trim() : '';
}

/* One account, one name, one rule (user, 2026-09-28: 「哪有同一个东西不同规范的」). The default
   login is named ``default`` like any other account; the empty string is only its historical
   spelling, and it is folded HERE, at the one place the box is read, so no other code path has
   to know that the same account was once addressed by leaving a field blank. A name typed with
   capitals is lowercased for the same reason: the jar's key on this OS cannot tell ``Work``
   from ``work``, and two spellings of one login is what this refuses to keep. */
var COOKIE_DEFAULT_ACCOUNT = 'default';

function cookieAccountKey(text) {
    var key = String(text || '').trim().toLowerCase();
    return key === '' ? COOKIE_DEFAULT_ACCOUNT : key;
}

function cookieAccount() {
    /* Which login the panel's actions speak for, as the server knows it. Free text, folded to
       the canonical key: blank means the default account and arrives as ``default``, so what
       the user sees and what the file is named are one thing said one way.

       Typing a NEW name here is how a second login is created: 生成/保存 then write that
       account's file, and every node can pick it. */
    return cookieAccountKey(document.getElementById('cookie-account') ? document.getElementById('cookie-account').value : '');
}

function setCookieAccountBox(account) {
    /* Write the box from an account key: a name as saved, the default as ``default``. */
    var el = document.getElementById('cookie-account');
    if (el) el.value = cookieAccountKey(account);
}

/* The per-(platform, account) rows, cached from the one status read the panel makes.
   Everything under the account box renders from here — the candidates, the live line and
   the management table — because a keystroke must not buy a directory listing. */
var cookieRows = [];

function cookieRowsOf(platform) {
    return cookieRows.filter(function (row) {
        return row.platform === platform;
    });
}

/* The account box's own candidate popup, appended to <body> like CustomSelect's two popups:
   the Cookie panel is a fixed box that scrolls, so a popup living inside it would be clipped
   by the panel's own overflow. ``_csSource`` is what makes ``CustomSelect.ownsPopup`` count a
   click inside it as "still inside the dialog" — without that field an outside-click guard
   would close the panel the moment the user picked a candidate. */
var cookieCand = null;

function cookieCandMenu() {
    if (cookieCand && document.body.contains(cookieCand)) return cookieCand;
    var input = document.getElementById('cookie-account');
    if (!input) return null;
    var menu = document.createElement('div');
    menu.className = 'cand-menu';
    menu._csSource = input;
    document.body.appendChild(menu);
    cookieCand = menu;
    return menu;
}

function hideCookieAccountCandidates() {
    if (cookieCand) cookieCand.classList.remove('open');
}

function renderCookieAccounts(show) {
    /* The saved logins of the platform on screen, as the WORDS the user reads (a typed name
       as typed, a generated one as 默认账号 / 默认账号2), offered as a dropdown on the account
       box instead of a row of buttons permanently under it — the box is where the choice is
       made, and a permanent row made the panel taller for a choice made once per login.

       It stays a hand-built popup rather than the browser's own because the value it carries
       is the empty string: a <datalist> prints the VALUE, so the default account could only
       ever have appeared as a blank row, and a blank row is not a candidate anybody can
       decide to trust. Nothing saved, nothing shown — offering 「默认账号」 for a file that
       does not exist is how a node ends up naming a login this machine cannot produce. */
    var menu = cookieCandMenu();
    var input = document.getElementById('cookie-account');
    var select = document.getElementById('cookie-platform');
    if (!menu || !input) return;
    var rows = cookieRowsOf(select ? select.value : '');
    var typed = String(input.value || '').toLowerCase();
    var items = rows.filter(function (row) {
        if (!typed) return true;
        return cookieAccountLabel(row).toLowerCase().indexOf(typed) >= 0 || String(row.account || '').toLowerCase() === typed;
    });
    if (!show || !items.length) {
        menu.classList.remove('open');
        menu.textContent = '';
        return;
    }
    /* Listeners, not an inline onclick: the account name is user text, and putting it in an
       attribute means spanning two escaping grammars for a value that is only ever read back
       as a string. */
    menu.textContent = '';
    items.forEach(function (row) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'cand-option';
        b.dataset.account = cookieAccountKey(row.account);
        b.textContent = cookieAccountLabel(row);
        b.title = row.account || I18n.t('cookies.accountDefaultHint');
        b.addEventListener('mousedown', function (e) {
            e.preventDefault();  // keep the focus on the box so the click lands before blur hides it
        });
        b.addEventListener('click', function () {
            pickCookieAccount(b.dataset.account);
        });
        menu.appendChild(b);
    });
    var rect = input.getBoundingClientRect();
    menu.classList.add('open');
    menu.style.minWidth = rect.width + 'px';
    var wanted = menu.scrollWidth || rect.width;
    menu.style.width = Math.max(rect.width, wanted) + 'px';
    var top = rect.bottom + 3;
    if (top + menu.offsetHeight > window.innerHeight - 6) top = Math.max(6, rect.top - menu.offsetHeight - 3);
    menu.style.left = Math.max(6, Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
    menu.style.top = top + 'px';
}

function pickCookieAccount(account) {
    /* Fill the box, not just the label: the box IS the answer every action below sends,
       so a candidate that only repainted the line under it would save under a different
       account than the one that was clicked. The box gets the account's NAME — ``default``
       for the platform's own login, which is why picking it no longer looks like a click that
       did nothing (reported 2026-09-28: the box went blank exactly when the right account was
       chosen, because blank used to be that account's spelling). */
    setCookieAccountBox(account);
    hideCookieAccountCandidates();
    renderCookieAccountStatus();
    renderCookieManager();
    showToast(
        I18n.t('cookies.chosen', {
            platform: I18n.t('platform.' + cookiePlatform()),
            account: cookieAccountWord(String(account || '')),
        })
    );
}

function cookieRowCells(row) {
    /* One row of the dock's table, built from the same classes 运行记录/导出产物 use, so a
       dock that is a different shape in every panel is not one panel but five. Elements, not
       a markup string: the account name is user text, and an inline
       ``onclick="fn('…','…')"`` would put it across two escaping grammars to reach a function
       that is right there anyway. */
    var cells = [
        { cls: 'runs-mgr-wf cookie-cell-platform', text: I18n.t('platform.' + row.platform) },
        { cls: 'runs-mgr-wf cookie-cell-account', text: cookieAccountLabel(row) },
        { cls: 'runs-mgr-id cookie-cell-entries', text: String(row.entries) },
        { cls: 'runs-mgr-time cookie-cell-saved', text: row.saved_at || I18n.t('cookies.unknownWhen') },
    ];
    var td = document.createElement('td');
    td.className = 'runs-mgr-ops';
    var ops = [{ label: 'cookies.renameOne', cls: 'cookie-mini runs-mgr-btn', go: function () { renameCookieAccount(row.platform, row.account); } }];
    if (cookieAccountKey(row.account) === COOKIE_DEFAULT_ACCOUNT) {
        /* 「重命名」 is offered for the other accounts only, and the reason is the directory
           layout rather than the name: 默认账号 owns no folder of its own — it IS
           ``<root>/<platform>``, the directory every other account of that platform is nested
           in. Naming it would move them with it. The row says that instead of offering a
           button that cannot do the thing. */
        ops[0].title = I18n.t('cookies.renameDefaultRefused');
        ops[0].cls += ' disabled';
        ops[0].disabled = true;
        ops[0].go = function () {
            showToast(I18n.t('cookies.renameDefaultRefused'));
        };
    }
    ops.push({ label: 'cookies.deleteOne', cls: 'cookie-mini runs-mgr-btn del', go: function () { deleteCookie(row.platform, row.account); } });
    /* 「删除 Profile」 only where there IS a profile directory to remove. The default account's
       row shows it greyed, not hidden — its browser data is the platform root that nests every
       named account, so the delete would over-reach; the tooltip says why, the same structural
       reason rename disables the default. A named account gets a working device-retire. */
    if (row.profile_exists) {
        var profOp = { label: 'cookies.deleteProfileOne', cls: 'cookie-mini runs-mgr-btn del', go: function () { deleteCookieProfile(row.platform, row.account); } };
        if (cookieAccountKey(row.account) === COOKIE_DEFAULT_ACCOUNT) {
            profOp.disabled = true;
            profOp.title = I18n.t('cookies.profileDeleteDefaultRefused');
            profOp.go = function () {
                showToast(I18n.t('cookies.profileDeleteDefaultRefused'));
            };
        }
        ops.push(profOp);
    }
    ops.forEach(function (spec) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = spec.cls;
        b.textContent = I18n.t(spec.label);
        if (spec.title) b.title = spec.title;
        if (spec.disabled) b.disabled = true;
        b.addEventListener('click', spec.go);
        td.appendChild(b);
    });
    return { cells: cells, ops: td };
}

function renderCookieManager() {
    /* Every saved login on this machine, one TABLE ROW per (platform, account): which platform,
       which account, how many entries, when it was taken, and the two actions. Metadata only —
       a cookie value is the login itself, and this is the one surface a stranger could stand
       in front of on a cloud deploy.

       It docks in the bottom slot with 控制台/运行记录/导出产物 (see ``toggleCookiesPanel``)
       rather than living inside the Cookie dialog: the list is the read side of a whole
       machine, and it used to push the paste box — the thing the user came to DO — off the
       bottom of a panel that only scrolls because of it. */
    var host = document.getElementById('cookies-mgr-body');
    if (!host) return;
    host.textContent = '';
    if (!cookieRows.length) {
        return void cookieListNote(host, 'cookies.noneSaved');
    }
    var table = document.createElement('table');
    table.className = 'data-preview-table runs-mgr-table';
    var head = document.createElement('thead');
    var headRow = document.createElement('tr');
    ['cookies.colPlatform', 'cookies.colAccount', 'cookies.colEntries', 'cookies.colSavedAt', 'cookies.colActions'].forEach(
        function (key) {
            var th = document.createElement('th');
            th.textContent = I18n.t(key);
            headRow.appendChild(th);
        }
    );
    head.appendChild(headRow);
    table.appendChild(head);
    var body = document.createElement('tbody');
    cookieRows.forEach(function (row) {
        var built = cookieRowCells(row);
        var tr = document.createElement('tr');
        /* The row carries its own account key: 「this row's delete/rename means THIS login」 has
           to be readable off the row it was clicked on, not inferred from what the dialog box
           happens to hold, and a test that presses the button must be able to say which row it
           pressed. */
        tr.className = 'cookie-row';
        tr.dataset.account = cookieAccountKey(row.account);
        tr.dataset.platform = String(row.platform || '');
        built.cells.forEach(function (cell) {
            var td = document.createElement('td');
            td.className = cell.cls;
            td.textContent = cell.text;
            tr.appendChild(td);
        });
        tr.appendChild(built.ops);
        body.appendChild(tr);
    });
    table.appendChild(body);
    host.appendChild(table);
}

function cookieListNote(host, key) {
    /* The empty answer and the failed answer are two different sentences and both are said
       the same way: one element, one textContent, no markup assembled from a response. */
    var note = document.createElement('div');
    note.className = 'cookie-row-empty';
    note.textContent = I18n.t(key);
    host.appendChild(note);
    return note;
}

/* ─── Saved logins panel (the bottom dock) ────────────────────── */
function toggleCookiesPanel() {
    var panel = document.getElementById('cookies-panel');
    if (!panel) return;
    if (panel.classList.contains('open')) {
        cookiesManager.close();
        return;
    }
    closeDockedPanels('cookies-panel');
    panel.classList.add('open');
    cookiesManager.refresh();
}

var cookiesManager = {
    panel() {
        return document.getElementById('cookies-panel');
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* The dock resize handle leaves an inline height behind, and an inline height
           overrides the CSS ``height: 0`` — without this, Close looks dead. */
        panel.style.height = '';
    },

    refresh() {
        /* Ask the server, then paint: the dialog's own read is a different moment (it fires
           when a panel opens), and a list of what is on disk that answers from a cache the
           last paste left behind would be a list of what used to be on disk. */
        var self = this;
        return fetchJSON('/api/cookies/status')
            .then(function (result) {
                if (!result || !result.ok) throw new Error('status failed');
                cookieRows = result.rows || [];
                renderCookieManager();
            })
            .catch(function () {
                var body = document.getElementById('cookies-mgr-body');
                if (body) {
                    body.textContent = '';
                    cookieListNote(body, 'cookies.listFailed');
                }
            });
    },

    onLanguageChange() {
        /* Every word in this table is built by JS from a catalogue key — the platform name,
           the account's word, 「时间未知」, the two buttons — so ``I18n.apply()`` never reaches
           any of it, and the panel kept speaking the old language after a switch. Repainted
           from the rows already in hand: a language change is not new information about the
           disk, and asking the server for it would make the switch cost a directory listing. */
        renderCookieManager();
    },
};

function cookiePlatform() {
    var el = document.getElementById('cookie-platform');
    return el ? String(el.value || '') : '';
}

/* No 「把 Cookie 更新进 Profile」 button any more: saving a cookie now plants it into that
   account's own profile by itself (``app.py::_plant_saved_cookie_into_profile``), which is what
   the paste already meant. The one case the browser cannot take on the spot — its profile is
   held by a running crawl — is answered by the save message and by ``needs_refresh``, so the
   next crawl of that account brings the cookie in. A button that asked the user to notice a
   state the product is responsible for was itself the defect. */

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
    statusEl.textContent = I18n.t('cookie.opening', {
        platform: entryLabels([{ platform: platform, account: cookieAccount() }]),
        s: waitSeconds,
    });
    fetchJSON('/api/cookies/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            platform: platform,
            wait_seconds: waitSeconds,
            url: cookieEntryUrl(),
            account: cookieAccount(),
        }),
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
        body: JSON.stringify({ platform: platform, url: cookieEntryUrl(), account: cookieAccount() }),
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
        /* A cold load has no in-memory results, but the last run's upstream rows are durable and
           the render endpoint resolves them by ``workflow_name`` — so open the board once and the
           charts repaint themselves. Guarded so it fires on the load, never mid-session (a run
           opens the board on its own), and only when the canvas actually has chart nodes. */
        if (this.candidate && !this._rehydrated && typeof dashboard !== 'undefined') {
            this._rehydrated = true;
            const hasChart = Object.keys(canvas.nodes || {}).some(function (id) {
                return canvas.nodes[id] && canvas.nodes[id].type === 'visualize';
            });
            if (hasChart) { dashboard.open(); }
        }
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
            /* The table was replaced: whatever row had been expanded is gone, and
               a stale flag would silence auto-refresh for a detail nobody can see. */
            this._detail = null;
        } catch (e) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('runsMgr.empty') + '</div>';
        }
    },

    refreshIfOpen() {
        var panel = this.panel();
        if (panel && panel.classList.contains('open')) this.refresh();
    },

    /* Follow a live run without the user opening anything: while the console sees
       `running`, the panel that lists runs keeps itself current so the row appears
       and advances on its own. It stays silent when the panel is closed (no polling
       a panel nobody is reading) and while a detail row is expanded — re-rendering
       there would yank the very table the user is reading out from under them. */
    autoRefresh() {
        if (this._detailOpen()) return;
        this.refreshIfOpen();
    },

    _detailOpen() {
        /* The flag, not a DOM probe: render() replaces the whole table, so an
           expanded row can only have come from the last render — and every path
           that wipes rows (a manual refresh, a re-render) clears the flag with
           them. A real `querySelector` here would ask the page a question the
           panel's own bookkeeping already answers truthfully. */
        return !!this._detail;
    },

    /* Any listed record still claiming that no verdict has been written for it.
       Right after 停止 this is true twice over: the row says 正在停止 because the Stop
       request wrote that itself, and the worker may still be unwinding behind it.
       Neither is a finished record, so `awaitSettled` keeps reading through both —
       counting only 'running' made the panel stop watching at the exact moment the
       record had just left that status. */
    _awaitable() {
        return (this._shown || []).some(function (r) {
            return r.status === 'running' || r.status === 'stopping';
        });
    },

    /* Keep re-reading after a stop until the record has actually settled. Bounded so
       a wedged worker cannot make the panel poll forever; a missed flip is repaired
       the moment the panel is next opened. The bound is minutes rather than seconds
       because the worker may be inside a page load it cannot be pulled out of, and
       this is the only thing that turns 正在停止 into the run's real verdict without
       the user touching anything.

       The watch has to outlast the longest tail the worker can be inside, which is
       measured, not guessed (docs/crawler_notes.md): a model request gives up at its
       own 300 s timeout and the retry ladder runs it again — 600 s — while a crawl cut
       short by killing its driver lands in about 5 to 30 s. A 120 s watch expired in
       the middle of that, freezing the row at 正在停止 until somebody opened it again.
       `tries` is derived from the watch budget and the step actually used, so passing a
       shorter `waitMs` (a test does) cannot silently shorten the watch too. */
    async awaitSettled(tries, waitMs) {
        var step = waitMs || runsManager.SETTLE_POLL_MS;
        var n = tries || Math.ceil(runsManager.SETTLE_WATCH_MS / step);
        for (var i = 0; i < n; i++) {
            await new Promise(function (done) { setTimeout(done, step); });
            if (this._detailOpen()) continue;
            /* Awaited, and the flag read from THAT answer: `refreshIfOpen()` fires the
               request without waiting, so a poll that asked `_shown` immediately
               after was judging the PREVIOUS read — which could end the watch the
               moment it started, on a list captured before this run existed. */
            await this.refresh();
            if (!this._awaitable()) break;
        }
    },

    /* Poll interval and total watch of the loop above, as data: the frontend test pins
       that the watch outlasts the measured model tail, which a literal buried in a call
       argument could not be checked against. */
    SETTLE_POLL_MS: 500,
    SETTLE_WATCH_MS: 660000,

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
        /* `stopping` is a status the record really holds: the Stop request writes it
           before the worker's verdict can arrive, so without this line the row would
           read 已完成 for the few seconds it is being stopped. */
        var known = ['running', 'stopping', 'interrupted', 'completed', 'failed', 'abandoned'];
        if (known.indexOf(status) >= 0) {
            return 'runsMgr.status.' + status;
        }
        /* Nothing here is 已完成 by default. A status this build has no word for came
           from somewhere else — an older row, a hand-edited database — and answering
           it with the friendly verdict states a fact the record never said. `I18n.t`
           returns an unknown key verbatim, so the row shows the stored word. */
        return String(status || '');
    },

    /* What kind of run this was, as chips beside the name: several workflows in one
       record (并行), and which window it crawled in. Both are stored facts, not
       guesses — and they matter when a record from last week is being read back:
       a visible-window crawl and a headless one fail differently. */
    tags(r) {
        var out = [];
        var count = r.wf_count || 1;
        if (count > 1 || r.mode === 'serial') {
            /* The mode is the fact; the count alone is not. A canvas can hold several
               workflows and still be run 串行, and labelling that 并行 claims a
               concurrency that never happened. Conversely a serial run IS one workflow
               per record, so its row says 串行 ×1 — the user asked for the mode to be
               stated even for a single one, not silently dropped. 并行 keeps needing
               count>1, because a lone workflow ran with no concurrency to report. */
            var key = r.mode === 'parallel' ? 'runsMgr.tagParallel' : 'runsMgr.tagSerial';
            out.push(I18n.t(key).replace('{n}', count));
        }
        /* 无头 / 窗口 says exactly what ran: a headless Chrome now carries a desktop
           fingerprint (#148), so nothing ever forces a real window into a run the user
           asked to keep headless. The record's requested value IS what ran, and no
           mixed 「无头→窗口」 chip is needed. */
        out.push(I18n.t(r.headless ? 'runsMgr.tagHeadless' : 'runsMgr.tagWindow'));
        /* Which workflows the record deliberately did NOT run. The console said it once
           at the time; a record read back last week has to carry the same answer, or a
           skipped workflow looks like it failed or was deleted. */
        if (r.skipped_workflows) {
            out.push(I18n.t('runsMgr.skipped').replace('{names}', r.skipped_workflows));
        }
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
            ops += '<button class="runs-mgr-btn" onclick="runsManager.detail(\'' + r.run_id + '\')">' + I18n.t('runsMgr.detail') + '</button>';
            ops += lockButtonHtml('runs', r.run_id);
            /* The stored tables are what a report needs, so a run from last week
               is reportable from here. Only the run id travels into the handler:
               a workflow name is user text, and a quote in it would close this
               attribute and start a new one. */
            ops += '<button class="runs-mgr-btn" onclick="runsManager.report(\'' + r.run_id + '\')">' + I18n.t('runsMgr.report') + '</button>';
            var tags = runsManager.tags(r).map(function (text) {
                return '<span class="runs-mgr-tag">' + escapeHtml(text) + '</span>';
            }).join('');
            return '<tr data-run-id="' + escapeHtml(r.run_id) + '">' +
                '<td class="runs-mgr-wf">' + escapeHtml(r.workflow_name || I18n.t('name.unnamed')) + tags + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(r.run_id) + '</td>' +
                '<td><span class="runs-mgr-status st-' + escapeHtml(r.status || '') + '">' + I18n.t(runsManager.statusKey(r.status)) + '</span></td>' +
                '<td>' + (r.node_done || 0) + '/' + (r.node_total || 0) + '</td>' +
                '<td>' + (r.rows_kept || 0) + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(r.started_at || '') + '</td>' +
                '<td class="runs-mgr-time">' + escapeHtml(runsManager._formatDuration(r.duration_seconds)) + '</td>' +
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
            '<th>' + I18n.t('runsMgr.colDuration') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + rows + '</tbody></table>';
    },

    _formatDuration: function (seconds) {
        /* Elapsed wall time as a language-neutral clock (MM:SS, H:MM:SS past an hour). A run still in
           flight has no duration_seconds (the backend leaves it null) → a dash, not a fabricated 0. */
        if (seconds === null || seconds === undefined || seconds < 0) return '—';
        var s = Math.floor(seconds);
        var h = Math.floor(s / 3600);
        var m = Math.floor((s % 3600) / 60);
        var sec = s % 60;
        var pad = function (n) { return (n < 10 ? '0' : '') + n; };
        return h > 0 ? h + ':' + pad(m) + ':' + pad(sec) : pad(m) + ':' + pad(sec);
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
        /* The app's own dialog, not window.confirm: a native box cannot be read
           in the interface language, cannot be styled with the rest of the page,
           and answers with a bare true/false that hides what is about to be lost. */
        var go = await showDialog({
            message: I18n.t('runsMgr.confirmRestart'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('runsMgr.restart'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
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
        var go = await showDialog({
            message: I18n.t('runsMgr.confirmRemove'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('runsMgr.remove'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
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

    /* Emptying the whole list is not "remove" called N times: the backend does it in one
       transaction and, more importantly, hands back the crawl claims of every run it
       deletes — a per-row loop would leave a ledger of "already collected" items pointing
       at rows that are gone, and the next crawl would silently under-deliver. The dialog
       has to say that out loud, because it is the one thing the user cannot un-see. */
    async clearAll() {
        var go = await showDialog({
            message: I18n.t('runsMgr.confirmClearAll'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('runsMgr.clearAll'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        try {
            var resp = await fetch('/api/runs/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ confirm: true }),
            });
            var result = await resp.json();
            if (result && result.ok) {
                showToast(I18n.t('runsMgr.clearAllDone').replace('{n}', (result.removed || {}).runs || 0));
            } else {
                showToast(I18n.t('runsMgr.clearAllFailed') + ((result && result.error) ? ': ' + result.error : ''));
            }
        } catch (e) {
            showToast(I18n.t('runsMgr.clearAllFailed'));
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

    // One definition of "settled", shared with the backend's node_done: a node that
    // only replayed its stored rows is just as finished as one that computed them, and
    // one that failed or starved is not finished at all. The panel counted these two
    // statuses differently from the record until they were tied together.
    nodeDone(status) {
        var s = String(status || '');
        return s === 'done' || s === 'restored';
    },

    // Group a run's nodes by the workflow (connected component) they ran in, keeping
    // canvas order. One record holds every workflow of a serial run by design, so
    // without this the user could not tell which rows came from which workflow — the
    // complaint that started this. A record with a single group renders as it always
    // did: an unnamed one-workflow canvas does not need a heading over its own nodes.
    nodeGroups(nodes) {
        var groups = [];
        var byIndex = {};
        (nodes || []).forEach(function (n) {
            var idx = Number(n.component || 0);
            if (!byIndex[idx]) {
                byIndex[idx] = { index: idx, name: String(n.component_name || ''), nodes: [] };
                groups.push(byIndex[idx]);
            }
            byIndex[idx].nodes.push(n);
        });
        groups.sort(function (a, b) {
            return a.index - b.index;
        });
        return groups;
    },

    /* The live <tr> for one run, found by the attribute the table stamps it with — never
       by a selector built from the id, which would ask the page to parse user data. */
    _rowFor(runId) {
        var body = document.getElementById('runs-mgr-body');
        if (!body) return null;
        var rows = body.querySelectorAll('tr');
        for (var i = 0; i < rows.length; i++) {
            if (rows[i].dataset && String(rows[i].dataset.runId) === String(runId)) return rows[i];
        }
        return null;
    },

    async detail(runId) {
        var existing = document.getElementById('runs-mgr-detail-' + runId);
        if (existing) {
            existing.remove();
            if (this._detail === runId) this._detail = null;
            return;
        }
        try {
            var resp = await fetch('/api/runs/' + encodeURIComponent(runId));
            var result = await resp.json();
            if (!result.ok || !result.run) return;
            var run = result.run;
            var self = this;

            function cardHtml(n) {
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
            }

            var groups = this.nodeGroups(run.nodes);
            var multi = groups.length > 1;
            var body = groups.map(function (group) {
                var cards = group.nodes.map(cardHtml).join('');
                if (!multi) {
                    return cards;
                }
                var done = group.nodes.filter(function (n) { return self.nodeDone(n.status); }).length;
                var rows = group.nodes.reduce(function (sum, n) { return sum + (n.row_count || 0); }, 0);
                return '<div class="rm-group">' +
                    '<div class="rm-group-head">' +
                    // The name is what the console called this workflow — the backend
                    // stores that same fallback per node, so a group is never left
                    // nameless and the two views can never disagree about one workflow.
                    '<span class="rm-group-name">' + escapeHtml(group.name) + '</span>' +
                    '<span class="rm-group-tally">' +
                    I18n.t('runsMgr.groupDone').replace('{done}', done).replace('{total}', group.nodes.length) +
                    ' · ' + rows + ' ' + I18n.t('runsMgr.colRows') +
                    '</span>' +
                    '</div>' +
                    '<div class="rm-nodes">' + cards + '</div>' +
                    '</div>';
            }).join('');
            var tr = document.createElement('tr');
            tr.id = 'runs-mgr-detail-' + runId;
            tr.innerHTML = '<td colspan="8" class="runs-mgr-detail">' +
                '<div class="rm-meta">' +
                '<span class="rm-meta-title">' + I18n.t('runsMgr.detailNodes') + '</span>' +
                '<span class="runs-mgr-status ' + this.nodeStatusInfo(run.status).cls + '">' +
                I18n.t(this.statusKey(run.status)) + '</span>' +
                '<span class="rm-meta-time">' + escapeHtml(run.started_at || '') +
                (run.finished_at ? ' &rarr; ' + escapeHtml(run.finished_at) : '') +
                (run.duration_seconds != null
                    ? ' &middot; ' + escapeHtml(I18n.t('runsMgr.colDuration')) + ' ' + escapeHtml(this._formatDuration(run.duration_seconds))
                    : '') +
                '</span>' +
                (run.note ? '<span class="rm-meta-note">' + escapeHtml(run.note) + '</span>' : '') +
                (run.skipped_workflows
                    ? '<span class="rm-meta-note">' +
                        escapeHtml(I18n.t('runsMgr.skipped').replace('{names}', run.skipped_workflows)) +
                        '</span>'
                    : '') +
                '</div>' +
                (multi
                    ? body
                    : '<div class="rm-nodes">' +
                        (body || '<div class="runs-mgr-empty">' + I18n.t('runsMgr.noNodes') + '</div>') +
                        '</div>') +
                '</td>';
            /* Re-resolved AFTER the fetch, from the live table. `refresh()` replaces the
               whole table while this request is in flight — the console keeps the run list
               current for a live run, which is exactly when a person opens a detail — so the
               row that was clicked can be an orphan by the time the answer lands. Inserting
               under that orphan drew the detail into a detached subtree (nothing appeared on
               screen) and then set `_detail`, which silences auto-refresh *for a detail
               nobody can see*: the panel went quiet and blank at once, and only a page
               reload or a manual refresh repaired it. A run no longer listed answers with
               nothing at all. */
            var row = this._rowFor(runId);
            if (!row) return;
            row.after(tr);
            this._detail = runId;
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
    /* A wire FROM a name node is the labelling pattern, not a data table — the
       source feed gate must not see it as a feed (backend validate builds the same
       distinction off the same rule: parent type !== 'name'). */
    var dataInput = {};
    conns.forEach(function (c) {
        hasOutput[c.from] = true;
        hasInput[c.to] = true;
        inputCount[c.to] = (inputCount[c.to] || 0) + 1;
        var src = nodes[c.from];
        if (src && src.type !== 'name' && nodes[c.to]) dataInput[c.to] = true;
    });
    /* Direct parents' types per node — the compile/output rules below key on exactly the same
       immediate-upstream distinction the backend validate builds. */
    var parentTypes = {};
    conns.forEach(function (c) {
        var src = nodes[c.from];
        if (src && nodes[c.to]) (parentTypes[c.to] = parentTypes[c.to] || []).push(src.type);
    });
    var TABLE_TYPES = ['source', 'upload', 'resume', 'comment', 'process', 'analysis', 'tokenize', 'output'];

    Object.keys(nodes).forEach(function (id) {
        var node = nodes[id];
        var params = node.params || {};
        var type = node.type;
        /* Old saved workflows can carry title:null — the message must still
           name the node (type label + id), never read 'node "null"'. */
        var label = node.title || I18n.t('node.' + type);

        if (type === 'source') {
            errors.push.apply(errors, sourceNodeErrors(node, label, !!dataInput[id]));
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
            // 模型一致率 has no x/y — it reads the tidy table's label column (the model/id columns
            // default to 模型/原行). Requiring x_field here would block a chart that never uses it,
            // so ask for the field THIS type really needs, matching the backend's own refusal.
            if (params.chart_type === 'model_agreement') {
                if (!params.agreement_label_field || !String(params.agreement_label_field).trim()) {
                    errors.push(I18n.t('validate.visualizeAgreementLabel').replace('{title}', label));
                }
            } else if (!params.x_field || !params.x_field.trim()) {
                errors.push(I18n.t('validate.visualizeXField').replace('{title}', label));
            }
        }

        if (type === 'compile') {
            /* A compile node turns a visualize parent's LaTeX into a PDF. Its source must be a visualize
               node that will actually emit some — mirrored off the same immediate-upstream rule as the
               backend, so a chart with neither LaTeX box on, or a non-visualize wire, is refused here too. */
            var cmpParents = parentTypes[id] || [];
            if (!cmpParents.length) {
                errors.push(I18n.t('validate.compileInput').replace('{title}', label));
            }
            cmpParents.forEach(function (ptype) {
                if (ptype !== 'visualize') {
                    errors.push(I18n.t('validate.compileBadParent').replace('{title}', label));
                }
            });
            conns.forEach(function (c) {
                if (String(c.to) !== String(id)) return;
                var par = nodes[c.from];
                if (par && par.type === 'visualize') {
                    var pp = par.params || {};
                    if (!boolParam(pp.emit_latex, true) && !boolParam(pp.emit_latex_table, true)) {
                        errors.push(I18n.t('validate.compileSourceBothOff').replace('{title}', label));
                    }
                }
            });
        }

        if (type === 'output') {
            if (!hasInput[id]) {
                errors.push(I18n.t('validate.outputInput').replace('{title}', label));
            }
            if ((params.operation === 'save' || params.operation === 'save_csv') && (!params.filename || !params.filename.trim())) {
                errors.push(I18n.t('validate.outputFilename').replace('{title}', label));
            }
            /* PDF and a row table are mutually exclusive outputs: a pdf format needs a visualize/compile
               source (and no table alongside); a table format must not be fed only by a chart/compile. */
            var outTypes = parentTypes[id] || [];
            var isPdf = (params.operation === 'save' || params.operation === 'save_csv') &&
                (String(params.format || '').toLowerCase() === 'pdf' || String(params.filename || '').toLowerCase().endsWith('.pdf'));
            var anyTable = outTypes.some(function (t) { return TABLE_TYPES.indexOf(t) >= 0; });
            var anyPdfable = outTypes.some(function (t) { return t === 'visualize' || t === 'compile'; });
            if (isPdf) {
                if (anyTable) errors.push(I18n.t('validate.outputPdfMixed').replace('{title}', label));
                if (!anyPdfable) errors.push(I18n.t('validate.outputPdfOnly').replace('{title}', label));
                if (outTypes.indexOf('visualize') >= 0 && outTypes.indexOf('compile') >= 0) {
                    errors.push(I18n.t('validate.outputPdfTwoSources').replace('{title}', label));
                }
            } else if (anyPdfable && !anyTable) {
                errors.push(I18n.t('validate.outputNeedsPdf').replace('{title}', label));
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
var DOCKED_PANELS = ['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel', 'workflows-panel', 'cookies-panel'];

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
            ops += lockButtonHtml('exports', row.name);
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
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('exportsMgr.colName') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colKind') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colSize') + '</th>' +
            '<th>' + I18n.t('exportsMgr.colModified') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>' +
            /* Read as a summary of the list above it, so it goes after the table — the
               totals cover the whole export directory, not the rows on screen, and a
               heading invites reading them as one file's figures. */
            '<div class="exports-summary">' +
            I18n.t('exportsMgr.summary').replace('{files}', totals.files || 0).replace('{size}', this.size(totals.bytes || 0)) +
            '</div>';
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
       the HTML attribute — see attrJsArg, which is the one place that knows how. */
    _quote(name) {
        return attrJsArg(name);
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

    /* One click, one HTML file — with the sections, row cap and Chart-Studio
       pictures chosen on the way. With a run id the tables are read back out of
       the run store, so yesterday's run can be reported on from the 运行记录
       panel; without one the run this page is holding is used, and the canvas
       lends the node titles (the store is not the only thing worth a report). */
    async report(runId, suggestedTitle) {
        var TOG = { charts: 'rpt-sec-charts', tables: 'rpt-sec-tables', facts: 'rpt-sec-facts' };
        var ROWS_FIELD = 'rpt-rows';
        /* The studio's saved pictures already live in the export folder; offer
           each as a toggle so a report can carry a hand-tuned chart the
           auto-drawn ones cannot reproduce. A folder with none still reports —
           the picker is simply empty, never an error. */
        var studioImages = [];
        try {
            var listResp = await fetch('/api/report/studio-images', { headers: { 'X-Lang': I18n.lang || 'zh' } });
            var list = await listResp.json();
            if (list && list.ok) studioImages = list.images || [];
        } catch (e) {
            studioImages = [];
        }
        var toggles = [
            { id: TOG.charts, label: I18n.t('exportsMgr.reportTCharts'), checked: true },
            { id: TOG.tables, label: I18n.t('exportsMgr.reportTTables'), checked: true },
            { id: TOG.facts, label: I18n.t('exportsMgr.reportTFacts'), checked: true },
        ];
        studioImages.forEach(function (img, i) {
            toggles.push({ id: 'rpt-img-' + i, label: img.name, checked: true });
        });
        var answer = await showDialog({
            message: I18n.t('exportsMgr.reportHint'),
            input: { value: suggestedTitle || '', placeholder: I18n.t('exportsMgr.reportPlaceholder') },
            toggles: toggles,
            fields: [{ id: ROWS_FIELD, label: I18n.t('exportsMgr.reportRows'), type: 'number', value: '20', min: '1', max: '200' }],
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.reportAi'), value: 'ai', collect: true },
                { label: I18n.t('exportsMgr.reportGo'), value: 'go', collect: true, primary: true },
                { label: I18n.t('exportsMgr.reportPdf'), value: 'pdf', collect: true },
            ],
        });
        if (!answer || !answer.value) return;
        var t = answer.toggles || {};
        // A switch the answer does not name is left at its default rather than
        // read as "off": an older or partial dialog must still yield a full
        // report, not a document that quietly lost its tables.
        function tog(id, def) {
            return t[id] === undefined ? def : !!t[id];
        }
        var options = {
            show_charts: tog(TOG.charts, true),
            show_tables: tog(TOG.tables, true),
            show_facts: tog(TOG.facts, true),
        };
        var rows = parseInt(answer.fields && answer.fields[ROWS_FIELD], 10);
        if (!isNaN(rows)) options.max_rows = rows;
        if (studioImages.length) {
            options.images = studioImages
                .filter(function (img, i) { return tog('rpt-img-' + i, true); })
                .map(function (img) { return img.name; });
        }
        var payload = {
            title: String(answer.input || '').trim(),
            include_conclusion: answer.value === 'ai',
            lang: I18n.lang || 'zh',
            llm: LLMSettings.payload(),
            options: options,
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
            if (answer.value === 'pdf') await this.printPdf(result.name);
            showToast(I18n.t('exportsMgr.reportDone'));
            this.view(result.name);
            this.refresh();
        } catch (e) {
            showToast(I18n.t('exportsMgr.reportFailed') + ': ' + (e.message || e));
        }
    },

    /* Print an already-generated report with the user's own headless Chrome. The
       HTML has already landed, so a PDF that will not come is a note, not a
       lost report: the failure is shown and the caller still opens the HTML. */
    async printPdf(name) {
        try {
            var resp = await fetch('/api/report/pdf', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ name: name }),
            });
            var result = await resp.json();
            if (!result.ok) throw new Error(result.error || 'pdf failed');
            showToast(I18n.t('exportsMgr.reportPdfDone'));
        } catch (e) {
            showToast(I18n.t('exportsMgr.reportPdfFailed') + ': ' + (e.message || e));
        }
    },

    async remove(name) {
        var go = await showDialog({
            message: I18n.t('exportsMgr.confirmRemove'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.remove'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
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

    /* The server deletes these one name at a time through the same resolver the per-row
       button uses, so the rules that keep a name from reaching outside data/exports cannot
       drift into a second bulk implementation. It also refuses outright while a run is
       live — a streaming node is writing part files into this very directory — and that
       refusal is shown rather than swallowed. */
    async clearAll() {
        var go = await showDialog({
            message: I18n.t('exportsMgr.confirmClearAll'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('exportsMgr.clearAll'), value: 'go', primary: true },
            ],
        });
        if (go !== 'go') return;
        try {
            var resp = await fetch('/api/exports/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
                body: JSON.stringify({ confirm: true }),
            });
            var result = await resp.json();
            if (result && result.ok) {
                showToast(I18n.t('exportsMgr.clearAllDone').replace('{n}', result.removed || 0));
            } else {
                showToast(I18n.t('exportsMgr.clearAllFailed') + ((result && result.error) ? ': ' + result.error : ''));
            }
        } catch (e) {
            showToast(I18n.t('exportsMgr.clearAllFailed'));
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
        return attrJsArg(value);
    },

    async rename(id, current) {
        /* No `value:` on the confirm button: showDialog answers a button with its own
           value when it has one, and only falls back to the input otherwise — so
           naming it 'ok' stored the literal string as the dataset's new label. The
           user read 「已重命名」 and saw the row say `ok`; the id is a content hash, so
           the file survived, the name did not. */
        var answer = await showDialog({
            message: I18n.t('datasetMgr.renamePrompt'),
            input: { value: current, placeholder: I18n.t('datasetMgr.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('datasetMgr.rename'), primary: true },
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

    /* The per-row button refuses a file a saved workflow points at; a wipe has no such
       guard, because "start from nothing" is exactly the case where the user wants those
       gone too. That difference is the whole content of this dialog: an Upload node whose
       file is deleted here does not break loudly, it just reads as an empty table later. */
    async clearAll() {
        var ok = await showDialog({
            message: I18n.t('datasetMgr.confirmClearAll'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('datasetMgr.clearAll'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/data/clear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ all: true }),
        });
        if (result && result.ok) {
            showToast(I18n.t('datasetMgr.clearAllDone').replace('{n}', result.removed || 0));
        } else {
            showToast(I18n.t('datasetMgr.clearAllFailed') + ((result && result.error) ? ': ' + result.error : ''));
        }
        this.refresh();
    },
};

/* One run at a time is the product's rule, and this panel's three actions all
   reach into the canvas the live run is writing: 打开 would re-key the run's
   ambient name, 重命名/删除 would move or drop the file behind it. The backend now
   refuses load during a run too; this is the front line that says why before
   sending a request the panel already knows will bounce. */
function refuseWhileRunning() {
    if (typeof RunState !== 'undefined' && RunState.running) {
        showToast(I18n.t('wfMgr.busy'));
        return true;
    }
    return false;
}

/* The workflow-file manager (task #115). The menu 「打开」 only ever had a file
   picker; this lists what is saved and lets the user 打开 / 重命名 / 删除 without
   guessing which stems exist. It reuses the runs/dataset panels' delegated-button +
   escaping shape, not a second invention. */
var wfFiles = {
    panel() {
        return document.getElementById('workflows-panel');
    },

    toggle() {
        var panel = this.panel();
        if (!panel) return;
        if (panel.classList.contains('open')) {
            this.close();
            return;
        }
        closeDockedPanels('workflows-panel');
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
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfMgr.loading') + '</div>';
        var result = await fetchJSON('/api/workflow/list').catch(function () { return null; });
        if (!result || !result.ok) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfMgr.loadFailed') + '</div>';
            return;
        }
        this._last = result.workflows || [];
        this.render();
    },

    onLanguageChange() {
        var panel = this.panel();
        if (!panel || !panel.classList.contains('open')) return;
        if (this._last) this.render();
        else this.refresh();
    },

    _when(seconds) {
        var value = Number(seconds) || 0;
        if (!value) return '';
        var d = new Date(value * 1000);
        function pad(n) { return (n < 10 ? '0' : '') + n; }
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
            ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    },

    _quote(value) {
        return attrJsArg(value);
    },

    render() {
        var body = document.getElementById('workflows-mgr-body');
        if (!body) return;
        var rows = this._last || [];
        if (!rows.length) {
            body.innerHTML = '<div class="runs-mgr-empty">' + I18n.t('wfMgr.empty') + '</div>';
            return;
        }
        var self = this;
        var current = (typeof workflow !== 'undefined' && workflow.currentFile) || '';
        var html = rows.map(function (row) {
            var name = String(row.name || '');
            var ops = '';
            if (!row.broken) {
                ops += '<button class="runs-mgr-btn" onclick="wfFiles.open(\'' + self._quote(name) + '\')">' +
                    I18n.t('wfMgr.open') + '</button>';
            }
            ops += '<button class="runs-mgr-btn" onclick="wfFiles.rename(\'' + self._quote(name) + '\')">' +
                I18n.t('wfMgr.rename') + '</button>';
            ops += '<button class="runs-mgr-btn del" onclick="wfFiles.remove(\'' + self._quote(name) + '\')">' +
                I18n.t('wfMgr.remove') + '</button>';
            ops += lockButtonHtml('workflows', name);
            var chip = name === current ? ' <span class="runs-mgr-cur">' + escapeHtml(I18n.t('wfMgr.current')) + '</span>' : '';
            var broken = row.broken ? ' <span class="runs-mgr-cur">' + escapeHtml(I18n.t('wfMgr.broken')) + '</span>' : '';
            return '<tr>' +
                '<td class="runs-mgr-wf">' + escapeHtml(name) + chip + broken + '</td>' +
                '<td>' + (row.nodes || 0) + '</td>' +
                '<td class="runs-mgr-id">' + escapeHtml(self._when(row.mtime)) + '</td>' +
                '<td class="runs-mgr-ops">' + ops + '</td>' +
                '</tr>';
        }).join('');
        body.innerHTML =
            '<table class="data-preview-table runs-mgr-table"><thead><tr>' +
            '<th>' + I18n.t('wfMgr.colName') + '</th>' +
            '<th>' + I18n.t('wfMgr.colNodes') + '</th>' +
            '<th>' + I18n.t('wfMgr.colModified') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>' + html + '</tbody></table>';
    },

    async open(name) {
        if (refuseWhileRunning()) return;
        /* Opening replaces the canvas (and its autosave draft) wholesale, and the
           app tracks no dirty flag — so confirm first when the canvas is not empty,
           exactly as the dataset delete confirms before it destroys. */
        if (typeof canvas !== 'undefined' && Object.keys(canvas.nodes || {}).length) {
            var ok = await showDialog({
                message: I18n.t('wfMgr.confirmOpen').replace('{name}', name),
                buttons: [
                    { label: I18n.t('dialog.cancel'), value: false },
                    { label: I18n.t('wfMgr.open'), value: true, primary: true },
                ],
            });
            if (!ok) return;
        }
        await workflow._loadByName(name);
        this.refresh();
    },

    async rename(name) {
        if (refuseWhileRunning()) return;
        /* No `value:` on the primary button — showDialog answers a button carrying
           one with that value, ignoring the typed input (the dataset rename once
           stored the literal 'ok' this way). */
        var answer = await showDialog({
            message: I18n.t('wfMgr.renamePrompt').replace('{name}', name),
            input: { value: name, placeholder: I18n.t('wfMgr.renamePlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('wfMgr.rename'), primary: true },
            ],
        });
        if (!answer || answer === name) return;
        var result = await fetchJSON('/api/workflow/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: name, new_name: answer }),
        });
        if (result && result.ok) {
            /* The canvas that was open under the old stem now IS the new file;
               leaving currentFile on the old name would make the next Save
               recreate the just-renamed-away file. */
            if (typeof workflow !== 'undefined' && workflow.currentFile === name) workflow.currentFile = result.name;
            if (typeof workflow !== 'undefined') workflow._persistOpenFile();
            showToast(I18n.t('wfMgr.renameDone'));
            this.refresh();
        } else {
            showToast((result && result.error) || I18n.t('wfMgr.renameFailed'));
        }
    },

    async remove(name) {
        if (refuseWhileRunning()) return;
        var ok = await showDialog({
            message: I18n.t('wfMgr.confirmRemove').replace('{name}', name),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('wfMgr.remove'), value: true, primary: true },
            ],
        });
        if (!ok) return;
        var result = await fetchJSON('/api/workflow/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ name: name }),
        });
        showToast(result && result.ok ? I18n.t('wfMgr.removeDone') : I18n.t('wfMgr.removeFailed'));
        if (typeof resumeBar !== 'undefined' && resumeBar.refresh) resumeBar.refresh();
        this.refresh();
    },
};

function toggleDatasetPanel() {
    datasetManager.toggle();
}

/* Reached from both the status-bar button and the menu 「打开」. `wfFiles` is a
   top-level `var`, so the inline handlers in its rendered table resolve it, but an
   explicit export costs nothing and keeps the panel reachable from app.js. */
function toggleWorkflowsPanel() {
    wfFiles.toggle();
}
