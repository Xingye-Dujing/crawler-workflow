/* Workflow Execution & File Management */


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
        var loaded = false;
        if (name) {
            try {
                var resp = await fetch('/api/workflow/load?name=' + encodeURIComponent(name));
                var result = await resp.json();
                if (result && result.ok && result.workflow) {
                    loaded = this.loadFromJSON(result.workflow);
                    if (loaded) canvas.markSaved();
                }
            } catch (e) {
                /* offline at boot, or the file is gone: leave the draft as-is, never throw into boot */
            }
        }
        if (typeof resumeBar !== 'undefined' && resumeBar && resumeBar.refresh) resumeBar.refresh();
        /* A draft that was restored without a server file still has results filed
           under its structure. loadFromJSON already asks; this is the no-file case. */
        if (!loaded && typeof runResults !== 'undefined' && runResults.refresh) runResults.refresh();
    },

    async save() {
        /* The FILE keeps a reusable node as a group (its template and collapsed state);
           only a RUN expands it. Using one shape for both would make Save silently
           replace the group with its children, and reopening would lose the feature. */
        const workflowData = canvas.toWorkflowJSON({ expandReusable: false });
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
            if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
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
                canvas.markSaved();
            } else {
                showToast(I18n.t('toast.saveFailed') + ': ' + result.error);
            }
        } catch (e) {
            showToast(I18n.t('toast.saveFailed') + ': ' + e.message);
        }
    },

    /* Debounced, silent autosave — fires a couple seconds after the last structural change
       and ONLY when a file is already open. A never-named canvas is deliberately left for the
       explicit Save, so autosave never drops unexpected files into the folder; and it writes
       no toast, because a background save that announces itself every few seconds is noise.
       The dirty flag is the whole gate: nothing to flush, nothing scheduled. */
    scheduleAutosave() {
        if (!this.currentFile || !canvas.dirty) return;
        if (this._autosaveTimer) clearTimeout(this._autosaveTimer);
        this._autosaveTimer = setTimeout(() => {
            this._autosaveTimer = null;
            this._autosaveToFile();
        }, 2000);
    },

    async _autosaveToFile() {
        /* Re-check at fire time, not just schedule time: the user may have saved explicitly
           (clearing dirty) or opened a new file inside the debounce window. */
        if (!this.currentFile || !canvas.dirty) return;
        try {
            const resp = await fetch('/api/workflow/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: this.currentFile, workflow: canvas.toWorkflowJSON({ expandReusable: false }) }),
            });
            const result = await resp.json();
            if (result.ok) {
                canvas.markSaved();
                this._persistOpenFile();
            }
        } catch (e) {
            /* A failed background save stays silent by design: dirty stays up, the next change
               re-schedules, and beforeunload still warns on close — the user never loses an
               unsaved file to an autosave that could not reach the server. */
        }
    },

    /* The last line before the browser throws an unsaved draft away. The logic lives HERE
       (not in app.js) so a harness can drive the handler directly; app.js only invokes the
       install — the AGENTS cross-file-wrapper rule in one place. The message text is
       browser-owned, so only preventDefault / the truthy return matter. Installed once: a
       re-entry (a soft reload) must not stack a second identical listener. */
    installDirtyGuard() {
        if (this._dirtyGuardInstalled) return;
        this._dirtyGuardInstalled = true;
        window.addEventListener('beforeunload', (e) => {
            if (!canvas.dirty) return;
            e.preventDefault();
            e.returnValue = '';
        });
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
                if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
                canvas.markSaved();
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

    /* Restoring a snapshot is ONE undo step. The file-open path is unchanged: it
       deliberately records its own entries (a file load is not a canvas edit). */
    loadFromJSON(workflowData, options) {
        if (options && options.history === 'single') {
            return canvas.batchHistory(() => this._loadFromJSON(workflowData));
        }
        return this._loadFromJSON(workflowData);
    },

    _loadFromJSON(workflowData) {
        /* Checked BEFORE anything is torn down: the old order cleared the canvas,
           then died on `workflowData.nodes.forEach` for a file without a node
           list, so opening a foreign or half-written JSON cost the user the
           workflow they had on screen and told them only 'load failed'. */
        if (!workflowData || typeof workflowData !== 'object' || !Array.isArray(workflowData.nodes)) {
            showToast(I18n.t('toast.workflowFileInvalid'));
            return false;
        }
        /* The badges on screen describe the PREVIOUS canvas until this one has a
           run's statuses of its own; loadFromJSON asks for them at the end. */
        if (typeof runResults !== 'undefined') runResults.clear();
        document.getElementById('nodes-container').innerHTML = '';
        canvas.nodes = {};
        canvas.connections = [];
        canvas.nextId = 1;
        /* Keyed by the id the file ASKED for, not the id the canvas kept: addNode
           re-mints a malformed or already-taken id, and the wires must follow the
           node that was actually built (see canvas._remapConnections). */
        var idMap = {};
        workflowData.nodes.forEach(function (n) {
            /* The file's own ids come back unchanged: run records and resume
               cursors are filed under them, so a re-mint on open would leave
               the interrupted run unreachable from the canvas it belongs to
               (see canvas.addNode's nodeId). */
            var id = canvas.addNode(n.type, n.x, n.y, n.id);
            idMap[n.id] = id;
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
        canvas.connections = canvas._remapConnections(workflowData.connections, idMap);
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
        /* Default result view: the newest run of this exact structure, with its node
           verdicts, as soon as a canvas is open. */
        if (typeof runResults !== 'undefined' && runResults.refresh) runResults.refresh();
        return true;
    },

    newFile() {
        if (typeof runResults !== 'undefined') runResults.clear();
        document.getElementById('nodes-container').innerHTML = '';
        canvas.nodes = {};
        canvas.connections = [];
        canvas.nextId = 1;
        canvas.selectedNode = null;
        if (canvas._settingsNodeId) closeSettings();
        /* A new canvas is a fresh view, not the last one with its nodes deleted: 适应 on an
           empty graph lands exactly at pan 0 / zoom 100%, so 新建 never inherits the previous
           file's camera. resetView repaints the transform and re-paints the % readout. */
        canvas.resetView();
        canvas.scheduleRender();
        canvas.updateStatus();
        /* The outline reads the model at saveState, which a bare 新建 never runs — so rebuild
           it here, immediately, instead of leaving the previous canvas's rows on screen until
           some later write. Guarded the same way saveState guards it (a canvas-only harness
           has no Outline; a broken sidebar must not abort the reset). */
        if (typeof Outline !== 'undefined' && Outline.render) {
            try {
                Outline.render();
            } catch (e) {
                console.error('outline render failed', e);
            }
        }
        this.currentFile = null;
        localStorage.removeItem('crawler_canvas');
        this._persistOpenFile();
        if (typeof LayoutStrategy !== 'undefined') LayoutStrategy.reset();
        /* An empty canvas has nothing to save, so it is clean — and markSaved resets the
           baseline, since 新建 rebuilds the canvas without going through saveState. */
        canvas.markSaved();
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
                if (p.platform && sessionAsked(p, p.platform, p.collect || p.mode)) {
                    found.push(sessionEntry(p));
                }
            } else if (node.type === 'comment') {
                String(p.urls || '').split(/[\s,;、]+/).forEach(function (line) {
                    var plat = urlPlatform(line);
                    if (plat && sessionAsked(p, plat, 'comments')) found.push(sessionEntry(p, plat));
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

    async rerunNode(nodeId, runId) {
        /* Re-run one node + its downstream by replaying the SAME run as a resume after the
           backend wipes that subtree's stored rows. The CURRENT canvas is what we send (not the
           historical one) so the fingerprint matches what the user sees; a mismatch is refused by
           name rather than silently mixing two workflows' rows under one run id. */
        var result = await fetchJSON('/api/workflow/rerun-node', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({
                workflow: canvas.toWorkflowJSON(),
                workflow_name: this.runName(),
                node_id: nodeId,
                resume_run_id: runId,
                lang: I18n.lang,
            }),
        }).catch(function () { return null; });
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('toast.rerunFailed'));
            return null;
        }
        if (result.queued) {
            /* Parked behind a live run: nothing has started, so neither the badges
               nor the console change — and the toast must not claim a rerun began. */
            showToast(result.message || I18n.t('runsMgr.busy'));
            if (window.runsManager) runsManager.refreshIfOpen();
            return result;
        }
        showToast(I18n.t('toast.rerunStarted', { n: (result.invalidated || []).length }));
        /* The same run id is being re-executed, but its statuses are new: clear the
           old subtree's marks, follow this attempt, and put the console back on
           screen — a rerun that starts without a log looks like nothing happened. */
        if (typeof runResults !== 'undefined') runResults.beginLive(result.run_id || runId);
        if (typeof RunState !== 'undefined' && RunState.setRunning) RunState.setRunning(true);
        var statusText = document.getElementById('status-text');
        if (statusText) statusText.textContent = I18n.t('status.running');
        closeDockedPanels('console-panel');
        document.getElementById('console-panel').classList.add('open');
        if (window.runsManager) runsManager.refreshIfOpen();
        this.pollStatus();
        return result;
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
        /* The remedy depends on which tool holds the dead login. A Selenium verdict points at the
           cookie panel; a CatBus one must NOT — its login lives in CatBus' own account files, and the
           server already put 「catbus <平台> auth login」 in the text. Opening a cookie dialog for it
           would send the user to re-save a session this crawl never reads, so the button is only
           offered when every refused entry belongs to the browser. */
        var browserOnly = blocked.every(function (key) {
            return !unpackEntryKey(key).backend || unpackEntryKey(key).backend === 'selenium';
        });
        var choice = await showDialog({
            message: I18n.t('dialog.cookieExpired')
                .replace('{n}', blocked.length)
                .replace('{platforms}', entryLabels(blocked.map(unpackEntryKey))) +
                '\n' + lines.join('\n') + (browserOnly ? '\n' + I18n.t('dialog.cookieExpiredHint') : ''),
            buttons: browserOnly
                ? [
                      { label: I18n.t('dialog.cookieGoUpdate'), value: 'update', primary: true },
                      { label: I18n.t('dialog.cancel'), value: null },
                  ]
                : [{ label: I18n.t('dialog.close'), value: null, primary: true }],
        });
        /* Both answers stop the run — that is the hard block. Only 「去更新 Cookie」 opens the panel:
           closing the dialog with 取消 and finding a panel the user did not ask for is the difference
           between refusing and nagging. */
        if (browserOnly && choice === 'update') {
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
        /* A reusable node's errors exist only in the expanded graph, so the canvas's
           own validate() cannot see them. Asking here means a bad group refuses the
           press by name instead of sending a graph the engine will reject halfway. */
        if (typeof ReusableNodes !== 'undefined' && ReusableNodes.errors) {
            validationErrors = validationErrors.concat(ReusableNodes.errors());
        }
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
        /* AI transport check — fail fast instead of dying 200 rows into a run. Asked of the
           EFFECTIVE nodes, the same graph the server walks: a node the user switched off is not
           on the canvas, so it must not be able to hold up a run that would call no model at all. */
        var llm = LLMSettings.payload();
        if (canvas.effectiveIds && canvas.effectiveIds().some(function (id) {
            var n = canvas.nodes[id];
            return n && n.type === 'process' && nodeNeedsLlm(n.params, n.operation);
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
                /* The canvas now follows THIS run: the previous run's green/red marks
                   are history the moment a new attempt starts. */
                if (typeof runResults !== 'undefined') runResults.beginLive(result.run_id);
                if (window.runsManager) runsManager.refreshIfOpen();
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

    reconnectConsole() {
        /* One replay at a time, and shareable by whoever asks. Two doors call this: the page
           boot, and a 「立即执行」 fire that really started. Each of them used to run its own
           read of the tail, because the guard against a second reader (``_pollTimer``) is only
           installed at the END of the first one — so both fetched, both opened the panel, and
           both shouted 「已重新连接控制台」 for the same run. Keeping the promise is also the
           only way a caller can wait for a replay it did not start: a test (or a panel) that is
           about to clear the console box has no other way to learn the server's history is
           still on its way in. */
        if (!this._reconnect) {
            this._reconnect = this._replayConsole().finally(() => { this._reconnect = null; });
        }
        return this._reconnect;
    },

    async _replayConsole() {
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
                /* The run ledger's per-node verdicts. Applied outside the log branch:
                   a quiet node can change status between lines, and the final tick
                   after `running` turns false is the one that paints the last one. */
                if (typeof runResults !== 'undefined' && result.node_states) {
                    runResults.applyLive(result.node_states, result.run_ids);
                }
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
                                repaintConsoleView(consoleOut, activeTab, follow);
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
                            repaintConsoleView(consoleOut, 'all', followSingle);
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
                        /* Re-read the finished record: the panel marker and the node
                           map should come from what was persisted, not from the last
                           tick that may have raced the worker's final write. */
                        if (typeof runResults !== 'undefined') runResults.finishLive();
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
    /* The engine is part of the question: the same platform offers a different function list under
       each one, and the run will fall back inside THAT list. Asking the union would bless a stored
       browser-only mode for a CatBus node the adapter has no handler for. */
    var backend = String(params.backend || '') || Capabilities.defaultBackend(platform);
    var offered = Capabilities.modes(platform, backend);
    var mode = Capabilities.mode(platform, wanted, backend);
    if (!mode) {
        return [I18n.t('validate.sourceUnknownPlatform', { title: label, platform: String(platform) })];
    }
    if (wanted && offered.length > 1 && mode.key !== wanted) {
        return [I18n.t('validate.sourceUnknownMode')
            .replace('{title}', label)
            .replace('{platform}', I18n.t('platform.' + platform))];
    }
    var engine = Capabilities.engine(platform, backend);
    if (engine && engine.available === false) {
        return [
            I18n.t('validate.modeUnavailable', {
                title: label,
                reason: I18n.t(engine.reasonKey || 'settings.backendProbeFailed'),
            }),
        ];
    }
    if (!Capabilities.runnable(mode) || !Capabilities.cellRunnable(mode, backend)) {
        /* The server already answered that this machine or this engine cannot run the pair, so this is
           not a warning about a risk — it is a refusal of a certainty, said before the run is paid
           for. The same rule runs in ``engine/workflow.py``, and the wording is the catalogue's. */
        return [
            I18n.t('validate.modeUnavailable', {
                title: label,
                reason: Capabilities.modeRefusal(platform, mode, backend),
            }),
        ];
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
               engine refuses others at crawl time; say it before the run. A field
               that declares it also takes NAMES (红果: the walk runs inside the
               client, whose own boards answer to a title) does not call a title a
               broken link; a line that does look like a link still has to match.
               The link test is spelled [A-Za-z0-9_] rather than \w so it is the
               ONE rule the server answers too (crawl_capabilities.is_url_cell) —
               JS \w is ASCII, Python \w is not, and two spellings would let the
               panel bless a line the engine then refuses. */
            var bad = links.filter(function (u) {
                if (field.acceptsNames && !/:\/\/|[?&][A-Za-z0-9_]+=/.test(u)) return false;
                return urlPlatform(u) !== field.linksOf;
            }).length;
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
    html += renderParamInput(nodeId, p, 'max_length', 'settings.maxLength', 'number', 512);
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
    var TABLE = ['source', 'upload', 'resume', 'comment', 'process', 'analysis', 'tokenize', 'accumulate', 'output'];
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
/* One pre-run gate entry: which login, of which system, for which platform.

   ``backend`` travels with it because the server routes the question by that field
   (``cookie_preflight.entry_of``), and a CatBus 「default」 and a cookie file named 「default」 are two
   accounts on two systems. The account that names the session differs by backend, and the node's own
   form holds both, so this picks the one the run will actually read instead of asking both systems
   about one name. */
function sessionEntry(p, platform) {
    var backend = String(p.backend || '');
    return {
        platform: String(platform || p.platform || ''),
        account: backend === 'catbus' ? String(p.catbus_account || '') : String(p.account || ''),
        backend: backend,
    };
}

/* Whether the run gate has a login to ask about for this node.

   Two backends, two answers, and neither may stand in for the other: the Selenium matrix knows which
   of its own crawls are served to a logged-in session (weibo's 热搜 answers anyone, 微信 wants no
   session at all), and the CatBus manifest knows which of ITS cells need an account of their own.
   Asking the wrong one is not harmless — an anonymous browser crawl refused for a missing cookie, or
   a CatBus crawl that never needed a login blocked by 「Cookie 已失效」 for a cookie it never reads. */
function sessionAsked(p, platform, modeKey) {
    if (String(p.backend || '') === 'catbus') {
        /* A cell the backend cannot crawl at all is refused by name when the walk starts, so there is
           no login worth asking about and no browser worth buying to test one. */
        if (!Capabilities.backendState(platform, modeKey, 'catbus').runnable) return false;
        return Capabilities.backendAuth(platform, modeKey);
    }
    return Capabilities.needsSession(platform, modeKey);
}

function preflightEntryKey(entry) {
    var plat = typeof entry === 'string' ? entry : String((entry && entry.platform) || '');
    var acct = typeof entry === 'string' ? '' : String((entry && entry.account) || '');
    /* The backend belongs in the identity of the question: one key for both systems is how a dead
       cookie blocks a node that never reads it — or a live CatBus login clears a gate a dead cookie
       should have stopped. ``CookieManager.path_segment`` folds the default account onto '' exactly
       as this folds a blank backend onto the browser, and only a non-browser backend gains a suffix,
       so every key this app ever produced still spells the same. */
    var be = typeof entry === 'string' ? '' : String((entry && entry.backend) || '');
    var base = acct ? plat + '@' + acct : plat;
    return be && be !== 'selenium' ? base + '#' + be : base;
}

/* The reverse: an answer key back into an entry, for display and for opening the
   panel on the right platform. An entry that is already an object passes through —
   the blocked/unclear lists arrive as keys, the toast paths may hold either. */
function unpackEntryKey(key) {
    if (key && typeof key === 'object') {
        return {
            platform: String(key.platform || ''),
            account: String(key.account || ''),
            backend: String(key.backend || ''),
        };
    }
    var s = String(key || '');
    var hash = s.indexOf('#');
    var backend = hash < 0 ? '' : s.slice(hash + 1);
    if (hash >= 0) s = s.slice(0, hash);
    var at = s.indexOf('@');
    return {
        platform: at < 0 ? s : s.slice(0, at),
        account: at < 0 ? '' : s.slice(at + 1),
        backend: backend,
    };
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

/* The word for a node type. The key is computed, so the i18n audit cannot see the missing
   half: a type this build's catalogue does not name (a canvas stored by a newer version, or a
   node type added here and forgotten there) would otherwise print the identifier
   「nodeType.fuse」 in the panel header. The raw type is the honest fallback — it is what the
   file says, and it never claims to be a translation of something else. */
function nodeTypeWord(type) {
    if (!type) return '';
    var key = 'nodeType.' + type;
    var word = I18n.t(key);
    return word === key ? type : word;
}

// updateParam with refresh=true by default
function updateParam(nodeId, key, value) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    /* Same-type multi-edit: when the panel was opened on one node of a live all-same-type
       selection, a field write lands on every node in that group. multiEditTargets returns []
       for a mixed selection, so the panel then edits only this node (writing this type's params
       onto another type would be nonsense). */
    var targets = canvas.multiEditTargets ? canvas.multiEditTargets(nodeId) : [];
    if (targets.length > 1) {
        targets.forEach(function (id) {
            var nd = canvas.nodes[id];
            if (nd) {
                nd.params[key] = value;
                canvas.updateNodeDisplay(id);
            }
        });
        canvas.saveState();
        if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
        return;
    }
    node.params[key] = value;
    canvas.updateNodeDisplay(nodeId);
    canvas.saveState();
    if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
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
        ['hongguo', ['hongguoduanju.com']],
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
    if (node && node.params && Capabilities.ready()) {
        /* A new platform may not offer the engine the old one used (a CatBus-only platform, or a
           machine where CatBus cannot run). The stored engine and the stored mode both move to what
           THIS platform can actually offer, in one write, so the panel and the saved node agree. */
        var backend = String(node.params.backend || '') || Capabilities.defaultBackend(value);
        var engine = Capabilities.engine(value, backend);
        if (!engine || engine.available === false) backend = Capabilities.defaultBackend(value);
        if (node.params.collect) {
            var mode = Capabilities.mode(value, node.params.collect, backend);
            if (mode) node.params.collect = mode.key;
        }
        node.params.backend = backend;
    }
    updateParam(nodeId, 'platform', value);
}

function closeSettings() {
    var hadPanel = !!canvas._settingsNodeId;
    document.getElementById('node-settings').classList.remove('open');
    canvas._settingsNodeId = null;
    canvas.updateSettingsButton();
    /* The panel's controls render their dropdowns / suggestion lists into
       <body>, so they must be dismissed here too — otherwise a stray menu
       keeps floating over the canvas and can edit a node that is no longer
       on screen. */
    if (window.CustomSelect) CustomSelect.close();
    /* Hand focus back to whatever opened the panel (the node's ⚙ button), so a keyboard
       user is not dumped at the top of the page. Only when a panel was actually closing,
       and only if the opener is still in the document (undo/reload may have dropped it). */
    var back = canvas._settingsReturnFocus;
    canvas._settingsReturnFocus = null;
    var alive = back && back.focus && (typeof document.contains === 'function' ? document.contains(back) : true);
    if (hadPanel && alive) back.focus();
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

/* ─── Three docked panels share one slot ─────────────────────────
   Console, 运行记录 and 导出产物 are all bottom-docked, and each writes an inline
   height when its resize handle is dragged. That inline height beats the CSS
   `height: 0` which hides a panel, so closing one by dropping `.open` alone
   leaves it visually expanded — two panels then overlap in the same slot. All
   three toggles live in this file, so the helper is called directly rather than
   reached for through `window`. */
var DOCKED_PANELS = ['console-panel', 'runs-panel', 'exports-panel', 'dataset-panel', 'workflows-panel', 'cookies-panel', 'lexicon-panel', 'schedules-panel', 'processes-panel', 'biblio-panel'];

function closeDockedPanels(exceptId) {
    DOCKED_PANELS.forEach(function (id) {
        if (id === exceptId) return;
        var other = document.getElementById(id);
        if (!other) return;
        other.classList.remove('open');
        other.style.height = '';
    });
}

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

function toggleDatasetPanel() {
    datasetManager.toggle();
}

/* Reached from both the status-bar button and the menu 「打开」. `wfFiles` is a
   top-level `var`, so the inline handlers in its rendered table resolve it, but an
   explicit export costs nothing and keeps the panel reachable from app.js. */
function toggleWorkflowsPanel() {
    wfFiles.toggle();
}
