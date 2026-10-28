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

/* The fields that name *which login* a crawl asks, shown one at a time.

   A node declares a Selenium 账号 and a CatBus 账号; only the one its 采集方式 will read can be filled
   in honestly, and a panel showing both would have the user pick a session for a crawl that never
   looks at it. 采集方式 itself always stays: an unreachable backend is greyed and named on its option
   (``Capabilities.backendState``), because a canvas that STORED the value must show what it holds —
   removing the field would make the panel read as Selenium while the run starts the other one. */
function visibleSourceFields(fields, p) {
    var catbus = String(p.backend || '') === 'catbus';
    return fields.filter(function (f) {
        /* 采集引擎 is rendered above the 采集内容 selector from the platform's engine list, so the
           stored backend keeps one control on screen even though every shared form declares it.
           A payload that predates the engine dimension has no such list; the old in-form select is
           the only control then, and hiding it would leave the stored backend invisible. */
        if (f.key === 'backend') return !Capabilities.engines(String(p.platform || '')).length;
        if (f.key === 'catbus_account') return catbus;
        if (f.key === 'account') return !catbus;
        return true;
    });
}

/* Switching the engine is a change of WHAT this node runs, not a cosmetic filter: if the stored mode
   is not offered by the new engine, the node's ``collect`` moves to the mode the panel will show (the
   engine's first runnable one) in the same write, so the saved canvas and the panel never disagree. */
function setSourceBackend(nodeId, value) {
    if (!ID_SHAPE.test(String(nodeId))) return;
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var params = node.params || {};
    var platform = String(params.platform || '');
    var current = String(params.collect || params.mode || '');
    var offered = Capabilities.modes(platform, value);
    var keys = offered.map(function (m) { return m.key; });
    if (keys.length && keys.indexOf(current) < 0) {
        var fallback = Capabilities.mode(platform, current, value);
        if (fallback && fallback.key !== current) updateParam(nodeId, 'collect', fallback.key);
    }
    updateParam(nodeId, 'backend', value);
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
    var backend = String(p.backend || '') || Capabilities.defaultBackend(platform);
    var pick = ID_SHAPE.test(String(nodeId)) ? "selectSourcePlatform('" + nodeId + "',this.value)" : '';
    var html = sourceSelectHtml(
        nodeId,
        'settings.platform',
        Capabilities.platforms().map(function (entry) {
            return { value: entry.platform, labelKey: entry.labelKey || 'platform.' + entry.platform };
        }),
        platform,
        pick
    );
    /* 平台 → 引擎 → 功能, in that order. The engine is a first-class choice: it decides which
       functions the next select offers, and a stored choice the adapter no longer supports stays on
       screen, greyed and named, rather than being replaced by Selenium behind the user's back. */
    var engines = Capabilities.engines(platform);
    if (engines.length) {
        var engineOptions = engines.map(function (e) {
            var unavailable = e.available === false;
            return {
                value: e.key,
                labelKey: e.labelKey,
                disabled: unavailable,
                labelSuffix: unavailable ? '（' + I18n.t(e.reasonKey || 'settings.backendProbeFailed') + '）' : '',
            };
        });
        if (
            backend &&
            !engineOptions.some(function (o) {
                return o.value === backend;
            })
        ) {
            var gone = Capabilities.engine(platform, backend);
            engineOptions.push({
                value: backend,
                labelKey: '',
                disabled: true,
                labelSuffix: '（' + I18n.t((gone && gone.reasonKey) || 'settings.backendUnknown') + '）',
            });
        }
        html += sourceSelectHtml(
            nodeId,
            'settings.crawlEngine',
            engineOptions,
            backend,
            ID_SHAPE.test(String(nodeId)) ? "setSourceBackend('" + nodeId + "',this.value)" : ''
        );
        html +=
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);margin-top:-2px;">' +
            I18n.t('settings.engineHint') +
            '</div></div>';
    }
    var mode = Capabilities.mode(platform, p.collect || p.mode, backend);
    if (!mode) {
        /* A platform × engine with no functions cannot be crawled, and the run
           would say so too — but saying it while the panel is open beats letting
           the user fill a form and find out later. The engine's own reason is
           quoted when it has one (no Node, adapter not installed, platform not
           listed, nothing runnable). */
        var engine = Capabilities.engine(platform, backend);
        var engineWhy =
            engine && engine.available === false ? I18n.t(engine.reasonKey || 'settings.backendProbeFailed') : '';
        return (
            html +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.capNoMode') +
            (engineWhy ? '（' + engineWhy + '）' : '') +
            '</div>'
        );
    }
    var offeredModes = Capabilities.modes(platform, backend);
    var wantedMode = String(p.collect || p.mode || '');
    if (offeredModes.length > 1) {
        /* One mode is not a choice: WeChat offers a single form, and a select
           with one option only makes the panel look unfinished. */
        var modeOptions = offeredModes.map(function (m) {
            /* A mode this machine or engine cannot run stays in the list and says why, rather
               than disappearing: a node restored from another canvas has that mode STORED, and
               an option that is simply absent would show the engine's first mode instead — the
               panel lying about what the run would do. Disabled + named is the honest shape. */
            var runnable = Capabilities.runnable(m) && Capabilities.cellRunnable(m, backend);
            var why = runnable ? '' : Capabilities.modeRefusal(platform, m, backend);
            return {
                value: m.key,
                labelKey: m.labelKey,
                disabled: !runnable,
                labelSuffix: runnable ? '' : '（' + why + '）',
            };
        });
        if (
            wantedMode &&
            !offeredModes.some(function (m) {
                return m.key === wantedMode;
            })
        ) {
            /* The stored function is not in this engine's list at all (an old canvas, or a cell
               CatBus dropped). Keep it visible and named: removing it would paint a different
               function as if it were the one written, which is the mismatch this panel exists to
               prevent. The run refuses the stored key by name until the user picks another. */
            modeOptions.unshift({
                value: wantedMode,
                labelKey: '',
                disabled: true,
                labelSuffix: '（' + I18n.t('settings.backendNoCell') + '）',
            });
        }
        html += sourceSelectHtml(
            nodeId,
            'settings.collect',
            modeOptions,
            mode.key,
            paramCall(nodeId, 'collect', 'this.value') + reopenCall(nodeId)
        );
    }
    var fields = visibleSourceFields(Capabilities.fields(platform, mode.key, backend), p);
    for (var i = 0; i < fields.length; i++) {
        html += sourceFieldHtml(nodeId, fields[i], p[fields[i].key], p);
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
            /* ``disabled`` is the one thing a select cannot do with styling: an option the machine
               cannot honour is still a value the element can be asked for (keyboard, a stale draft,
               an autofill). A node restored onto a Linux server keeps its stored mode and shows it
               here as a selected-but-disabled row — the panel says what the canvas already knows,
               and ``sourceNodeErrors`` refuses the run rather than starting it. */
            return (
                '<option value="' +
                escapeHtml(String(item.value)) +
                '"' +
                (known && String(item.value) === value ? ' selected' : '') +
                (item.disabled ? ' disabled' : '') +
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
            // ``labelSuffix`` is for a reason the option needs to carry itself (a machine
            // requirement this host does not meet), already in the canvas's language.
            return {
                value: o.value,
                label: (o.labelKey ? I18n.t(o.labelKey) : o.value) + (o.labelSuffix || ''),
                disabled: !!o.disabled,
            };
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
        var isBackend = f.key === 'backend';
        var html = sourceSelectHtml(
            nodeId,
            f.labelKey,
            f.options.map(function (o) {
                if (!isBackend) return { value: o.value, labelKey: o.labelKey };
                /* Which tool this cell can actually run is the server's answer, not a rule here. */
                var ok = Capabilities.backendState(allParams.platform, allParams.collect || allParams.mode, o.value);
                return {
                    value: o.value,
                    labelKey: o.labelKey,
                    disabled: !ok.runnable,
                    labelSuffix: ok.runnable ? '' : '（' + I18n.t(ok.wordKey) + '）',
                };
            }),
            String(v),
            paramCall(nodeId, f.key, 'this.value') + (isBackend ? reopenCall(nodeId) : '')
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

/* Settings Panel */
function openSettings(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) {
        /* Stale id (the node was deleted while the panel was open, or a redo
           dropped it): never leave an orphan panel on screen. */
        canvas.closeSettingsIfStale();
        return;
    }
    var previousNode = canvas._settingsNodeId;
    var wasOpen = !!previousNode;
    /* Rebuilding the SAME open panel (every parameter edit lands here) must keep its offset —
       the caret may be near the bottom. Opening a DIFFERENT node starts at the top. */
    var sameNode = previousNode === nodeId;
    canvas._settingsNodeId = nodeId;
    /* Focus moves into the panel only on a CLOSED→OPEN transition. openSettings is also the
       rebuild path after every parameter edit, and stealing focus there would drop the caret out
       of the field the user is typing in. Remember the opener so closeSettings can hand focus
       back to it (keyboard users are not dumped to the top of the page). */
    if (!wasOpen) {
        canvas._settingsReturnFocus = document.activeElement;
    }
    var panel = document.getElementById('node-settings');
    var content = document.getElementById('settings-content');
    panel.classList.add('open');
    var html = '<div class="settings-group">' +
        '<label class="settings-label">' + I18n.t('settings.nodeType') + '</label>' +
        '<span style="font-size:12px;color:var(--text-dim);">' + nodeTypeWord(node.type) + '</span>' +
        '</div>';
    /* The columns this node will emit — the edit-time lineage. A producer whose shape
       the server can see lists them; a crawl/comment/resume says so plainly rather than
       guessing. */
    var OUTPUT_PRODUCERS = ['source', 'upload', 'process', 'analysis', 'biblio', 'fuse', 'accumulate', 'tokenize', 'resume', 'comment'];
    if (OUTPUT_PRODUCERS.indexOf(node.type) >= 0 && typeof Diagnostics !== 'undefined') {
        var _oc = Diagnostics.outputColumns(nodeId);
        var _ocText = _oc === null
            ? I18n.t('diagnostics.unknownCols')
            : (_oc.length ? I18n.t('diagnostics.outputCols') + ': ' + escapeHtml(_oc.join(', ')) : I18n.t('diagnostics.outputColsNone'));
        html += '<div class="settings-group node-output-cols" style="font-size:11px;color:var(--text-dim);">' + _ocText + '</div>';
    }
    if (node.type === 'source') {
        /* The form is the matrix: which platforms exist, which of them want
           links instead of a keyword, and every field in between come from
           /api/capabilities (see Capabilities above), so the panel and the
           executor cannot disagree about what a platform offers. */
        html += sourcePanelHtml(nodeId, node.params);
        /* Only a mode whose walk is newest-first and has a stable item identity can
           stop at the previous completed run's boundary. Today that is Bilibili's
           author uploads (BV号); the backend refuses the switch everywhere else. */
        var wmPlatform = node.params.platform || node.platform || '';
        var wmMode = (typeof Capabilities !== 'undefined' && Capabilities.ready())
            ? Capabilities.mode(wmPlatform, node.params.collect || node.params.mode)
            : null;
        if (wmPlatform === 'bilibili' && wmMode && wmMode.handler === 'author') {
            html += '<div class="settings-group"><label class="settings-label">' +
                '<input type="checkbox" ' + (boolParam(node.params.watermark, false) ? 'checked' : '') + ' ' +
                'onchange="updateParam(\'' + nodeId + '\',\'watermark\',this.checked)"> ' +
                I18n.t('settings.watermark') + '</label>' +
                '<div class="settings-hint">' + I18n.t('settings.watermarkHint') + '</div></div>';
        }
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
        /* Two buttons and a status word share one row; a narrow panel has to wrap them instead
           of pushing the status out of the frame (measured on a 300 px panel: 已加载 was cut). */
        html += '<div class="settings-group upload-actions">' +
            '<button class="menu-btn" onclick="dataNodes.pickFile(\'' + nodeId + '\')">' + I18n.t('btn.uploadFile') + '</button>' +
            /* Asked where this file comes from at the moment the user is holding the picker,
               not from a menu he has to remember existed. */
            '<button class="menu-btn" onclick="toggleSourceHelp()">' + I18n.t('sourceHelp.button') + '</button>' +
            '<span class="upload-status">' +
            (p.dataset_id ? I18n.t('dataSource.loaded') + ': ' + escapeHtml(p.dataset_name || p.dataset_id) : I18n.t('dataSource.none')) +
            '</span></div>';
        if (node._datasetMissing) {
            /* The file this node pointed at is gone from the library, so its id was
               cleared to keep a run off a dead pointer — say what happened, not just
               "no file". */
            html += '<div class="settings-group dataset-missing">' + I18n.t('dataSource.missingRef') + '</div>';
        }
        /* A file already in the dataset library (a prior upload, a paste, an analysis
           result) can be attached without re-uploading it: the executor only needs a
           valid dataset_id. The list is fetched and rendered after the panel opens
           (loadDatasetOptions), so it can be filtered and carry per-file metadata. */
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chooseDataset') + '</label>' +
            '<div class="dataset-picker">' +
            '<input class="settings-input" id="dataset-filter-' + nodeId + '" placeholder="' +
            escapeHtml(I18n.t('settings.datasetFilter')) + '" oninput="dataNodes.filterDatasets(\'' + nodeId + '\', this.value)">' +
            '<select class="settings-select" id="dataset-pick-' + nodeId + '" ' +
            'onchange="dataNodes.pickFromDataset(\'' + nodeId + '\', this.value)">' +
            '<option value="' + escapeHtml(p.dataset_id || '') + '" selected>' +
            escapeHtml(p.dataset_name || I18n.t('dataSource.chooseLoading')) + '</option></select>' +
            '</div>' +
            '<div id="dataset-hint-' + nodeId + '" class="dataset-hint" style="font-size:11px;color:var(--text-dim);"></div>' +
            '<div style="display:flex;gap:8px;margin-top:6px;">' +
            /* Only offered when there is a dataset to describe: with no file attached the old
               button was rendered anyway and its handler returned without a word, so it looked
               broken (the fused demo's upload node is exactly that state). */
            (p.dataset_id
                ? '<button class="menu-btn" onclick="dataNodes.toggleDatasetDetail(\'' + nodeId + '\')">' +
                  I18n.t('settings.datasetDetail') + '</button>'
                : '') +
            (p.dataset_id ? '<button class="menu-btn" onclick="dataNodes.applyToOtherUploadNodes(\'' + nodeId + '\')">' + I18n.t('settings.applyToOthers') + '</button>' : '') +
            '</div>' +
            '<div id="dataset-detail-' + nodeId + '" class="dataset-detail" style="display:none;"></div></div>';
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
    } else if (node.type === 'accumulate') {
        /* The node appends this run's rows to a named, versioned table and passes the
           full table downstream. Identity is an explicit choice: whole-row equality
           or named key columns; the backend refuses a missing key by name. */
        var p = node.params;
        html += renderParamInput(nodeId, p, 'lineage_name', 'settings.accumulateName', 'text', '');
        html += renderParamSelect(nodeId, p, 'identity', 'settings.accumulateIdentity', 'row', [
            { v: 'row', l: I18n.t('settings.accumulateRow') },
            { v: 'columns', l: I18n.t('settings.accumulateColumns') },
        ]);
        html += renderParamInput(nodeId, p, 'key_columns', 'settings.accumulateKeys', 'text', '');
        var lineageArg = attrJsArg(String(p.lineage_name || '').trim());
        if (lineageArg) {
            html += '<div class="settings-group upload-actions">' +
                '<button class="menu-btn" style="color:var(--err)" ' +
                'onclick="datasetManager.resetLineage(\'' + lineageArg + '\')">' +
                I18n.t('datasetMgr.lineageReset') + '</button></div>';
        }
        html += '<div class="settings-hint">' + I18n.t('settings.accumulateHint') + '</div>';
    } else if (node.type === 'reusable') {
        /* The group's form is about its boundary: the template it carries, the ordered
           input slots an outside wire lands in, its single output, and the two view
           controls. The inside is read-only here — see ReusableNodes. */
        if (typeof ReusableNodes !== 'undefined') html += ReusableNodes.settingsHtml(nodeId);
    } else if (node.type === 'biblio') {
        html += renderBiblioSettings(nodeId, node.params);
    } else if (node.type === 'fuse') {
        html += renderFuseSettings(nodeId, node.params);
    } else if (node.type === 'process') {
        var p = node.params;
        var PROCESS_OPS = ['clean', 'emotion', 'tendency', 'sentiment', 'keyword', 'cluster', 'ner', 'aggression', 'bot', 'anomaly', 'correlation', 'significance'];
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

        /* Mode selector for emotion / tendency. The default is the fine-tuned BERT path (the
           recommended main model — see docs/why_finetuned_bert.md); a node that names no model runs
           the op's registered default, and the executor degrades to ml with a printed line when bert
           truly cannot run. Both also offer llm (row-by-row) and ml (offline sklearn). */
        if (p.operation === 'emotion' || p.operation === 'tendency') {
            var modeOptions = [
                { value: 'bert', label: I18n.t('mode.bert') },
                { value: 'llm', label: llmModeLabel() },
                { value: 'ml', label: I18n.t('mode.ml') },
            ];
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.mode') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'mode\',this.value)">' +
                selectOptionTags(modeOptions, p.mode, 'bert') +
                '</select></div>';
            if (p.mode === 'ml') {
                html += '<div class="settings-group"><button class="menu-btn" onclick="trainMLModel(\'' + nodeId + '\',\'' + p.operation + '\')">' + I18n.t('settings.trainModel') + '</button></div>';
            }
            if (p.mode === 'bert') {
                html += renderBertField(nodeId, p);
            }
        }

        /* Sentiment polarity. Four ways to answer 正面/负面/中性. The default is the fine-tuned BERT
           path (the recommended main model): a node that names no model runs the op's registered
           default, and the executor degrades to SnowNLP with a printed line when bert truly cannot
           run. The thresholds only mean anything to the two modes that answer with a POLARITY
           PROBABILITY — ml and llm answer with a label they were trained or prompted to pick, and
           re-deciding it from their confidence number would be a second opinion about the model's
           own answer (see analyzers/sentiment.py). */
        if (p.operation === 'sentiment') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'bert', [
                { v: 'bert', l: I18n.t('mode.bert') },
                { v: 'snownlp', l: I18n.t('mode.snownlp') },
                { v: 'ml', l: I18n.t('mode.ml') },
                { v: 'llm', l: llmModeLabel() },
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

        /* Bot / 水军 likelihood — per-author coordinated posting, a recall device (not a classifier). */
        if (p.operation === 'bot') {
            html += renderParamInput(nodeId, p, 'text_column', 'settings.textColumn', 'text', '正文');
            html += renderParamInput(nodeId, p, 'author_column', 'settings.botAuthorColumn', 'text', '评论者');
            html += renderParamInput(nodeId, p, 'time_column', 'settings.botTimeColumn', 'text', '评论时间');
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('settings.botHint') + '</div></div>';
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

        /* Significance test: compare one numeric column across the levels of one group column.
           ttest/mannwhitney are two-group; anova/kruskal are two-or-more — the analyzer refuses a
           method whose group count it cannot serve, by name, so the panel offers all four and the
           server is the single authority on which is legal (mirrors PROCESS_ENUMS.sig_method). */
        if (p.operation === 'significance') {
            html += renderParamInput(nodeId, p, 'group_column', 'settings.groupColumn', 'text', '');
            html += renderParamInput(nodeId, p, 'value_column', 'settings.valueColumn', 'text', '');
            html += renderParamSelect(nodeId, p, 'sig_method', 'settings.sigMethod', 'ttest', [
                { v: 'ttest', l: "Welch's t" },
                { v: 'anova', l: 'ANOVA' },
                { v: 'mannwhitney', l: 'Mann-Whitney U' },
                { v: 'kruskal', l: 'Kruskal-Wallis H' },
            ]);
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
        // Force word_freq when a visualize node is downstream. This is a derived default filled on a
        // MERE OPEN, not a user edit: the value is written so the preview/run reads it, but the panel
        // may not saveState() or updateNodeDisplay() here — that pushed an undo step and lit the dirty
        // dot for looking at a node (the same rule test_opening_a_tokenize_visualize_panel… guards on
        // the visualize side; connectNodes already persists it as a real edit at WIRING time).
        var hasDownstreamVisualize = canvas.connections.some(function (c) { return c.from === nodeId && canvas.nodes[c.to] && canvas.nodes[c.to].type === 'visualize'; });
        if (hasDownstreamVisualize && p.output_mode !== 'word_freq') {
            p.output_mode = 'word_freq';
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
        /* An output fed only by a chart / compile has exactly one valid format; force it in the live
           model so the run sends pdf even if the select is never touched (the extension itself is
           enforced server-side). Filling a derived default on a mere OPEN is not a user edit, so this
           branch must not saveState() — that pushed an undo step and lit the dirty dot for looking. */
        if (pdfOnly && p.format !== 'pdf') {
            p.format = 'pdf';
        }
        var fmt = pdfOnly ? 'pdf' : (p.format || 'csv');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t(pdfOnly ? 'settings.outputPdfHint' : 'settings.outputMergeHint') + '</div></div>';
        var formatOptions = pdfOnly
            ? [{ value: 'pdf', label: I18n.t('format.pdf') }]
            : ['csv', 'json', 'excel', 'txt', 'html', 'markdown', 'parquet'].map(function (f) {
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
    if (!sameNode) {
        /* Opening for a DIFFERENT node starts at the top. The panel is the scroll container, and
           it used to keep the previous form's offset: open a long node, scroll to its bottom,
           then open a short one and the panel shows blank space below the content until you
           scroll up yourself. A rebuild of the SAME open panel (every parameter edit) keeps its
           offset — the caret may be down there. */
        panel.scrollTop = 0;
        content.scrollTop = 0;
        /* The resize grip is pinned by cancelling the panel's scroll; after a reset the cancelling
           transform has to follow the new offset or the grip lands somewhere else for a frame. */
        var grip = panel.querySelector('.resize-handle');
        if (grip) grip.style.transform = 'translate(0px,0px)';
    }
    if (node.type === 'resume') renderResumeSettings(nodeId);
    if (node.type === 'upload') dataNodes.loadDatasetOptions(nodeId);
    if (
        node.type === 'process' &&
        nodeNeedsLlm(node.params, node.operation) &&
        typeof LLMSettings !== 'undefined' &&
        LLMSettings.load().provider === 'ollama'
    ) {
        renderNodeModelSelect(nodeId);
    }
    canvas.updateSettingsButton();
    if (!wasOpen) _focusFirstSetting();
}

/* Move the caret to the panel's first editable control when it is freshly opened, so a
   keyboard user who reaches a node lands inside its form rather than behind the canvas.
   Only ever called on a closed→open transition, so a rebuild during typing never fires it. */
function _focusFirstSetting() {
    var content = document.getElementById('settings-content');
    if (!content || !content.querySelector) return;
    var first = content.querySelector('input:not([type=hidden]), select, textarea, button');
    if (first && first.focus) first.focus();
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
       the newest keeps the node usable instead of silently reading nothing. This is
       the panel filling its own default on a render, not the user choosing — so it
       writes the value (the dropdown and the run both read it) but must not saveState(),
       or merely opening the resume panel would push an undo step and mark the file dirty. */
    if (!runs.some(function (r) { return r.run_id === p.resume_run_id; })) {
        p.resume_run_id = runs[0].run_id;
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
    if (op === 'emotion' || op === 'tendency') return (mode || 'bert') === 'llm';
    if (op === 'sentiment') return (mode || 'bert') === 'llm';
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
var ANALYSIS_OPS = ['drop_null', 'fill_null', 'drop_duplicates', 'dedupe_similar', 'filter_rows', 'select_columns', 'rename_columns', 'strip_whitespace', 'convert_type', 'sort_rows', 'sample_rows', 'groupby_agg', 'join_tables', 'column_calc', 'bin_column', 'extract_time', 'bin_time', 'suggest_stages', 'topic_model', 'topic_by_stage', 'topic_label', 'cluster_label', 'cluster_review', 'topic_map', 'topic_salience', 'topic_timeline', 'topic_flow', 'topic_coherence', 'cooccur', 'reply_graph', 'compare_platform', 'forecast', 'alert', 'sentiment_evolution'];
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
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
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
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
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
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') },
             { v: 'fallback', l: I18n.t('settings.labelOnFailFallback') }]);
        html += renderParamInput(nodeId, p, 'label_max_topics', 'settings.labelMaxTopics', 'number', 30);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.topicLabelHint') + '</div></div>';
    }
    if (op === 'cluster_label') {
        html += renderParamInput(nodeId, p, 'cluster_group_col', 'settings.clusterGroupColumn', 'text', 'cluster');
        html += renderParamInput(nodeId, p, 'cluster_text_col', 'settings.clusterTextColumn', 'text', '正文');
        html += renderParamInput(nodeId, p, 'cluster_summary_col', 'settings.clusterSummaryColumn', 'text', '摘要');
        html += renderParamSelect(nodeId, p, 'cluster_on_fail', 'settings.clusterOnFail', 'abort',
            [{ v: 'abort', l: I18n.t('settings.labelOnFailAbort') },
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') },
             { v: 'fallback', l: I18n.t('settings.labelOnFailFallback') }]);
        html += renderParamInput(nodeId, p, 'cluster_max_groups', 'settings.clusterMaxGroups', 'number', 60);
        html += renderParamInput(nodeId, p, 'cluster_sample_n', 'settings.clusterSampleN', 'number', 8);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.clusterLabelHint') + '</div></div>';
    }
    if (op === 'cluster_review') {
        html += renderParamInput(nodeId, p, 'review_group_col', 'settings.reviewGroupColumn', 'text', '聚类');
        html += renderParamInput(nodeId, p, 'review_label_col', 'settings.reviewLabelColumn', 'text', '聚类标签');
        html += renderParamInput(nodeId, p, 'review_name_col', 'settings.reviewNameColumn', 'text', '节点');
        html += renderParamInput(nodeId, p, 'review_freq_col', 'settings.reviewFreqColumn', 'text', '频次');
        html += renderParamInput(nodeId, p, 'review_summary_col', 'settings.reviewSummaryColumn', 'text', '簇综述');
        html += renderParamSelect(nodeId, p, 'review_on_fail', 'settings.clusterOnFail', 'abort',
            [{ v: 'abort', l: I18n.t('settings.labelOnFailAbort') },
             { v: 'blank', l: I18n.t('settings.labelOnFailBlank') },
             { v: 'fallback', l: I18n.t('settings.labelOnFailFallback') }]);
        html += renderParamInput(nodeId, p, 'review_max_groups', 'settings.clusterMaxGroups', 'number', 60);
        html += renderParamInput(nodeId, p, 'review_members', 'settings.reviewMembers', 'number', 12);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.clusterReviewHint') + '</div></div>';
    }
    if (op === 'topic_map') {
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.column') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.column || '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'column\',this.value)"></div>';
        html += renderParamInput(nodeId, p, 'n_topics', 'settings.nTopics', 'number', 5);
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
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
        html += renderParamSelect(nodeId, p, 'topic_method', 'settings.topicMethod', 'auto',
            [{ v: 'auto', l: I18n.t('settings.topicMethodAuto') }, { v: 'embedding', l: I18n.t('settings.topicMethodEmbed') }, { v: 'lda', l: I18n.t('settings.topicMethodLda') }]);
        html += renderParamInput(nodeId, p, 'embedding_model', 'settings.embeddingModel', 'text', 'BAAI/bge-small-zh-v1.5');
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
    if (op === 'reply_graph') {
        html += renderParamInput(nodeId, p, 'reply_author_col', 'settings.replyAuthorColumn', 'text', '评论者');
        html += renderParamInput(nodeId, p, 'reply_floor_col', 'settings.replyFloorColumn', 'text', '楼层');
        html += renderParamInput(nodeId, p, 'reply_parent_col', 'settings.replyParentColumn', 'text', '父楼层');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.replyGraphHint') + '</div></div>';
    }
    if (op === 'compare_platform') {
        html += renderParamInput(nodeId, p, 'compare_platform_col', 'settings.comparePlatformColumn', 'text', 'platform');
        html += renderParamInput(nodeId, p, 'compare_value_col', 'settings.compareValueColumn', 'text', '');
        html += renderParamSelect(nodeId, p, 'compare_agg', 'settings.compareAgg', 'mean',
            [{ v: 'mean', l: I18n.t('settings.compareAggMean') }, { v: 'sum', l: I18n.t('settings.compareAggSum') }]);
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.compareHint') + '</div></div>';
    }
    if (op === 'forecast') {
        html += renderParamInput(nodeId, p, 'forecast_period_col', 'settings.forecastPeriodColumn', 'text', 'period');
        html += renderParamInput(nodeId, p, 'forecast_value_col', 'settings.forecastValueColumn', 'text', 'sentiment_index');
        html += renderParamSelect(nodeId, p, 'forecast_method', 'settings.forecastMethod', 'moving_average',
            [{ v: 'moving_average', l: I18n.t('settings.forecastMethodMa') },
             { v: 'holt', l: I18n.t('settings.forecastMethodHolt') },
             { v: 'seasonal_naive', l: I18n.t('settings.forecastMethodSeasonalNaive') },
             { v: 'holt_winters', l: I18n.t('settings.forecastMethodHoltWinters') }]);
        html += renderParamInput(nodeId, p, 'forecast_horizon', 'settings.forecastHorizon', 'number', 3);
        html += renderParamInput(nodeId, p, 'forecast_window', 'settings.forecastWindow', 'number', 3);
        html += renderParamInput(nodeId, p, 'forecast_season', 'settings.forecastSeason', 'number', 7);
        html += renderParamInput(nodeId, p, 'forecast_alpha', 'settings.forecastAlpha', 'number', 0.5);
        html += renderParamInput(nodeId, p, 'forecast_beta', 'settings.forecastBeta', 'number', 0.3);
        html += renderParamInput(nodeId, p, 'forecast_gamma', 'settings.forecastGamma', 'number', 0.35);
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
        html += renderParamInput(nodeId, p, 'agg_metrics', 'settings.aggMetrics', 'text', '');
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

/* ── Bibliometrics node settings ── */
var BIBLIO_ENTITY_TYPES = ['keyword', 'author', 'institution', 'country', 'term', 'category', 'journal', 'source', 'funder', 'grant', 'document_cocitation', 'author_cocitation', 'journal_cocitation', 'article', 'document', 'bibliographic_coupling'];
var BIBLIO_SELECTION_MODES = ['top_n', 'top_pct', 'g_index', 'threshold'];
var BIBLIO_LINK_MEASURES = ['cosine', 'dice', 'jaccard', 'association'];
var BIBLIO_COUNTING = ['full', 'fractional'];
var BIBLIO_PRUNING_MODES = ['none', 'mst', 'pathfinder'];
var BIBLIO_PRUNING_SCOPES = ['slices', 'merged'];
var BIBLIO_PATHFINDER_R = ['1', '2', 'inf'];
var BIBLIO_LABEL_METHODS = ['llr', 'lsi', 'mi', 'tfidf'];
var BIBLIO_LABEL_SOURCES = ['all', 'title', 'abstract', 'keywords', 'author'];
var BIBLIO_OUTPUT_SHAPES = ['nodes', 'edges', 'clusters', 'bursts', 'variation', 'dual_map'];

function biblioOption(value, label) {
    /* Both shapes: `selectOptionTags` reads value/label, `renderParamSelect`
       reads v/l. One list, so a new entity type cannot appear in one control
       and be missing from the other. The key prefixes are spelled literally so
       the i18n reachability audit can see every label this panel renders. */
    return { value: value, label: label, v: value, l: label };
}
function biblioEntityOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.entity.' + value)); });
}
function biblioSelectionOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.selection.' + value)); });
}
function biblioMeasureOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.measure.' + value)); });
}
function biblioCountingOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.counting.' + value)); });
}
function biblioPruningOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.pruning.' + value)); });
}
function biblioPruningScopeOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.scope.' + value)); });
}
function biblioPathfinderOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.pfnetR.' + value)); });
}
function biblioLabelOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.label.' + value)); });
}
function biblioLabelSourceOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.label_source.' + value)); });
}
function biblioOutputShapeOptions(values) {
    return values.map(function (value) { return biblioOption(value, I18n.t('biblio.shape.' + value)); });
}
var BIBLIO_COUPLING_TYPES = ['document', 'bibliographic_coupling', 'journal', 'source'];
function isBiblioCoupling(entity) {
    return BIBLIO_COUPLING_TYPES.indexOf(entity) >= 0;
}

function updateBiblioEntity(nodeId, entity) {
    updateParam(nodeId, 'entity_type', entity);
    /* Coupling nodes are the citing papers themselves, so burst detection has
       no meaning there. Uncheck it as a derived default when that mode is
       chosen; an EXPLICIT true is still refused by the backend by name. */
    if (isBiblioCoupling(entity)) updateParam(nodeId, 'burst', false);
    openSettings(nodeId);
}

/* One candidate list per role, in the order the fold tries them. */
var FUSE_ROLE_FIELDS = [
    ['entity_columns', 'fuse.ui.entityColumns'],
    ['year_columns', 'fuse.ui.yearColumns'],
    ['title_columns', 'fuse.ui.titleColumns'],
    ['author_columns', 'fuse.ui.authorColumns'],
    ['affiliation_columns', 'fuse.ui.affiliationColumns'],
    ['text_columns', 'fuse.ui.textColumns'],
    ['reference_columns', 'fuse.ui.referenceColumns'],
    ['source_columns', 'fuse.ui.sourceColumns']
];

function renderFuseSettings(nodeId, p) {
    var html = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
        I18n.t('fuse.ui.hint') + '</div>';
    FUSE_ROLE_FIELDS.forEach(function (field) {
        html += renderParamInput(nodeId, p, field[0], field[1], 'text', '');
    });
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('fuse.ui.sourceLabels') + '</label>' +
        '<textarea class="settings-input" rows="3" placeholder="' +
        escapeHtml(I18n.t('fuse.ui.sourceLabelsPlaceholder')) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'source_labels\',this.value)">' +
        escapeHtml(p.source_labels || '') + '</textarea>' +
        '<div class="settings-hint">' + I18n.t('fuse.ui.sourceLabelsHint') + '</div></div>';
    html += renderParamCheckbox(nodeId, p, 'keep_undated', 'fuse.ui.keepUndated', true);
    html += renderParamCheckbox(nodeId, p, 'export_files', 'fuse.ui.exportFiles', false);
    return html;
}

function renderBiblioSettings(nodeId, p) {
    var entity = p.entity_type || 'keyword';
    var html = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('biblio.ui.hint') + '</div>';

    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.entityType') + '</label>' +
        '<select class="settings-select" onchange="updateBiblioEntity(\'' + nodeId + '\', this.value)">' +
        selectOptionTags(biblioEntityOptions(BIBLIO_ENTITY_TYPES), entity, 'keyword') +
        '</select></div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.columns') + '</div>';
    html += renderParamInput(nodeId, p, 'entity_column', 'biblio.ui.entityColumn', 'text', '') +
        renderParamInput(nodeId, p, 'year_column', 'biblio.ui.yearColumn', 'text', '年份') +
        renderParamInput(nodeId, p, 'title_column', 'biblio.ui.titleColumn', 'text', '题名') +
        renderParamInput(nodeId, p, 'abstract_column', 'biblio.ui.abstractColumn', 'text', '摘要') +
        renderParamInput(nodeId, p, 'reference_column', 'biblio.ui.referenceColumn', 'text', '参考文献') +
        renderParamInput(nodeId, p, 'tc_column', 'biblio.ui.tcColumn', 'text', '引用次数') +
        renderParamInput(nodeId, p, 'usage_column', 'biblio.ui.usageColumn', 'text', '使用次数') +
        '<div class="settings-hint">' + I18n.t('biblio.ui.columnsHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.network') + '</div>';
    html += renderParamInput(nodeId, p, 'time_start', 'biblio.ui.timeStart', 'number', '') +
        renderParamInput(nodeId, p, 'time_end', 'biblio.ui.timeEnd', 'number', '') +
        renderParamInput(nodeId, p, 'slice_years', 'biblio.ui.sliceYears', 'number', 1) +
        renderParamInput(nodeId, p, 'look_back_years', 'biblio.ui.lookBackYears', 'number', 0) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.timeHint') + '</div>';
    html += renderParamSelect(nodeId, p, 'selection', 'biblio.ui.selection', 'top_n', biblioSelectionOptions(BIBLIO_SELECTION_MODES)) +
        renderParamInput(nodeId, p, 'top_n', 'biblio.ui.topN', 'number', 50) +
        renderParamInput(nodeId, p, 'top_pct', 'biblio.ui.topPct', 'number', 10) +
        renderParamInput(nodeId, p, 'g_index', 'biblio.ui.gIndex', 'number', 25) +
        renderParamInput(nodeId, p, 'min_count', 'biblio.ui.minCount', 'number', 2) +
        renderParamInput(nodeId, p, 'threshold_c', 'biblio.ui.thresholdC', 'number', 0) +
        renderParamInput(nodeId, p, 'threshold_cc', 'biblio.ui.thresholdCC', 'number', 1) +
        renderParamInput(nodeId, p, 'threshold_ccv', 'biblio.ui.thresholdCCV', 'number', 0) +
        renderParamInput(nodeId, p, 'min_tc', 'biblio.ui.minTc', 'number', '') +
        renderParamInput(nodeId, p, 'min_usage', 'biblio.ui.minUsage', 'number', '') +
        renderParamCheckbox(nodeId, p, 'largest_component', 'biblio.ui.largestComponent', false);
    html += renderParamSelect(nodeId, p, 'link_measure', 'biblio.ui.linkMeasure', 'cosine', biblioMeasureOptions(BIBLIO_LINK_MEASURES)) +
        renderParamSelect(nodeId, p, 'counting', 'biblio.ui.counting', 'full', biblioCountingOptions(BIBLIO_COUNTING)) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.countingHint') + '</div>' +
        renderParamInput(nodeId, p, 'citation_expansion', 'biblio.ui.citationExpansion', 'number', 0) +
        renderParamInput(nodeId, p, 'max_links_per_node', 'biblio.ui.maxLinks', 'number', 10) +
        renderParamInput(nodeId, p, 'lrf', 'biblio.ui.lrf', 'number', 2.5) +
        renderParamSelect(nodeId, p, 'pruning', 'biblio.ui.pruning', 'none', biblioPruningOptions(BIBLIO_PRUNING_MODES)) +
        renderParamSelect(nodeId, p, 'pruning_scope', 'biblio.ui.pruningScope', 'slices', biblioPruningScopeOptions(BIBLIO_PRUNING_SCOPES)) +
        renderParamSelect(nodeId, p, 'pathfinder_r', 'biblio.ui.pathfinderR', 'inf', biblioPathfinderOptions(BIBLIO_PATHFINDER_R)) +
        renderParamInput(nodeId, p, 'pathfinder_lmax', 'biblio.ui.pathfinderLmax', 'number', 0) +
        renderParamInput(nodeId, p, 'pathfinder_dmax', 'biblio.ui.pathfinderDmax', 'number', 1) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.pathfinderHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.cluster') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'cluster', 'biblio.ui.cluster', true) +
        renderParamInput(nodeId, p, 'cluster_count', 'biblio.ui.clusterCount', 'number', '') +
        renderParamSelect(nodeId, p, 'label_method', 'biblio.ui.labelMethod', 'llr', biblioLabelOptions(BIBLIO_LABEL_METHODS)) +
        renderParamSelect(nodeId, p, 'label_source', 'biblio.ui.labelSource', 'all', biblioLabelSourceOptions(BIBLIO_LABEL_SOURCES)) +
        renderParamInput(nodeId, p, 'top_terms', 'biblio.ui.topTerms', 'number', 5) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.labelSourceHint') + '</div>' +
        '<div class="settings-hint">' + I18n.t('biblio.ui.clusterHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.burst') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'burst', 'biblio.ui.burst', true) +
        renderParamInput(nodeId, p, 'burst_gamma', 'biblio.ui.burstGamma', 'number', 1.0) +
        renderParamInput(nodeId, p, 'burst_min_duration', 'biblio.ui.burstMinDuration', 'number', 2) +
        renderParamInput(nodeId, p, 'burst_weight', 'biblio.ui.burstWeight', 'number', 2.0) +
        renderParamInput(nodeId, p, 'burst_top', 'biblio.ui.burstTop', 'number', 20) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.burstHint') + '</div>';
    if (isBiblioCoupling(entity)) {
        html += '<div class="settings-group" style="font-size:11px;color:#e67e22;">' + I18n.t('biblio.ui.burstCoupling') + '</div>';
    }

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.variation') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'variation', 'biblio.ui.variation', false) +
        renderParamInput(nodeId, p, 'variation_min', 'biblio.ui.variationMin', 'number', 0.05) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.variationHint') + '</div>';
    if (isBiblioCoupling(entity)) {
        // The switch is refused by the server here, so the panel says so instead of offering a
        // box that only ever produces an error at run time.
        html += '<div class="settings-group" style="font-size:11px;color:#e67e22;">' + I18n.t('biblio.ui.variationCoupling') + '</div>';
    }

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.overlay') + '</div>';
    html += renderParamInput(nodeId, p, 'sentiment_column', 'biblio.ui.sentimentColumn', 'text', '') +
        renderParamInput(nodeId, p, 'topic_column', 'biblio.ui.topicColumn', 'text', '') +
        '<div class="settings-hint">' + I18n.t('biblio.ui.overlayHint') + '</div>';

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.correction') + '</div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.aliases') + '</label>' +
        '<textarea class="settings-input" rows="4" placeholder="' + escapeHtml(I18n.t('biblio.ui.aliasesPlaceholder')) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'aliases\',this.value)">' + escapeHtml(p.aliases || '') + '</textarea></div>' +
        '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.exclusions') + '</label>' +
        '<textarea class="settings-input" rows="4" placeholder="' + escapeHtml(I18n.t('biblio.ui.exclusionsPlaceholder')) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'exclude_values\',this.value)">' + escapeHtml(p.exclude_values || '') + '</textarea>' +
        '<div class="settings-hint">' + I18n.t('biblio.ui.correctionHint') + '</div></div>';
    if (!isBiblioCoupling(entity)) {
        // A coupling network's clusters are the citing documents, which no one names by hand;
        // the box only appears where a label can actually be overridden.
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.clusterLabels') + '</label>' +
            '<textarea class="settings-input" rows="3" placeholder="' +
            escapeHtml(I18n.t('biblio.ui.clusterLabelsPlaceholder')) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'cluster_labels\',this.value)">' +
            escapeHtml(p.cluster_labels || '') + '</textarea>' +
            '<div class="settings-hint">' + I18n.t('biblio.ui.clusterLabelsHint') + '</div></div>';
    }

    html += '<div class="settings-group" style="font-size:11px;color:var(--accent);">' + I18n.t('biblio.ui.section.output') + '</div>';
    html += renderParamSelect(nodeId, p, 'output_shape', 'biblio.ui.outputShape', 'nodes', biblioOutputShapeOptions(BIBLIO_OUTPUT_SHAPES));
    var basemapId = escapeHtml(p.basemap_dataset_id || '');
    var basemapOptions = '<option value="' + basemapId + '" selected>' + escapeHtml(p.basemap_dataset_id || I18n.t('biblio.ui.noBasemap')) + '</option>';
    if (p.basemap_dataset_id && dataNodes._datasets && dataNodes._datasets[p.basemap_dataset_id]) {
        basemapOptions = '<option value="' + basemapId + '" selected>' + escapeHtml(dataNodes._dsLabel(dataNodes._datasets[p.basemap_dataset_id])) + '</option>';
    }
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('biblio.ui.basemap') + '</label>' +
        '<select class="settings-select" id="biblio-basemap-' + nodeId + '" onchange="updateParam(\'' + nodeId + '\',\'basemap_dataset_id\',this.value)">' +
        basemapOptions + '</select>' +
        '<button class="menu-btn" onclick="dataNodes.loadBiblioBasemapOptions(\'' + nodeId + '\')">' + I18n.t('settings.capLoaded') + '</button>' +
        '<div class="settings-hint">' + I18n.t('biblio.ui.basemapHint') + '</div></div>';
    html += renderParamInput(nodeId, p, 'watch_project', 'biblio.ui.watchProject', 'text', '') +
        renderParamInput(nodeId, p, 'watch_baseline', 'biblio.ui.watchBaseline', 'text', '') +
        renderParamInput(nodeId, p, 'watch_label', 'biblio.ui.watchLabel', 'text', '') +
        '<div class="settings-hint">' + I18n.t('biblio.ui.watchHint') + '</div>';
    html += renderParamCheckbox(nodeId, p, 'export_files', 'biblio.ui.exportFiles', true) +
        '<div class="settings-hint">' + I18n.t('biblio.ui.exportHint') + '</div>' +
        '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    return html;
}

/* ── Visualize node settings ── */
var CHART_TYPES = ['bar', 'line', 'dual_line', 'stack_pct', 'topic_map', 'topic_terms', 'pie', 'scatter', 'histogram', 'box', 'heatmap', 'model_agreement', 'sankey', 'network', 'knowledge_graph', 'cluster_timeline', 'burst', 'timezone', 'circular', 'landscape', 'biblio_heatmap', 'graph3d', 'variation', 'dual_map', 'geo_map', 'sentiment_overlay', 'topic_overlay', 'concentric', 'wordcloud', 'map'];
var BIBLIO_CHARTS = ['knowledge_graph', 'cluster_timeline', 'burst', 'timezone', 'circular', 'landscape', 'biblio_heatmap', 'graph3d', 'variation', 'dual_map', 'geo_map', 'sentiment_overlay', 'topic_overlay', 'concentric'];

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
var CHARTS_NO_Y = ['histogram', 'wordcloud', 'map', 'stack_pct', 'model_agreement'].concat(BIBLIO_CHARTS).concat(CHARTS_WITH_Y_AS_CATEGORY);
// The right-hand scale, which only 双轴折线 asks for. Kept equal to the backend's
// ECHARTS_ONLY_TYPES by tests/unit/test_visualization.py, because the renderer that cannot
// draw two axes refuses by name and the panel must not offer it silently.
// 显著词图 asks for y2 too, but as a SECOND BAR SERIES on the same scale, not as a second
// axis — the two counts are in the same unit, and splitting them across scales would let a
// rare word look bigger than a common one.
var CHARTS_WITH_Y2 = ['dual_line', 'topic_terms'];
var CHARTS_WITH_LABEL = ['topic_map'];
var ECHARTS_ONLY_CHARTS = ['wordcloud', 'sankey', 'map', 'dual_line', 'topic_map', 'topic_terms', 'network', 'model_agreement', 'knowledge_graph', 'cluster_timeline', 'burst', 'timezone', 'circular', 'landscape', 'biblio_heatmap', 'graph3d', 'variation', 'dual_map', 'geo_map', 'sentiment_overlay', 'topic_overlay', 'concentric'];
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
        /* The tokenize columns have fixed names, so a never-configured chart still knows what to
           read. Filling them here is a DISPLAY default only — it must NOT call saveState() or
           updateNodeDisplay: opening a panel is not an edit, and stamping an undo step + the dirty
           dot every time the user merely looked at the node was the bug. The values reach the
           preview/executor from the params, so they are set without persisting. */
        if (!p.x_field) p.x_field = 'word';
        if (!p.y_field) p.y_field = 'frequency';
        if (!p.value_field) p.value_field = 'frequency';

        var ct = p.chart_type || 'bar';
        var TOKENIZE_CHART_TYPES = ['bar', 'pie', 'wordcloud'];

        // Wordcloud only supports ECharts engine. Corrected in the params (not saved), because a
        // stored 'matplotlib' would fail the run — but a mere panel open still earns no undo step.
        var isWordcloud = ct === 'wordcloud';
        if (isWordcloud && p.engine !== 'echarts') p.engine = 'echarts';

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
    if (BIBLIO_CHARTS.indexOf(ct) >= 0) {
        /* These four read the fixed columns a Bibliometrics node emits, so x/y boxes would
           promise a choice the builder never reads. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('biblio.ui.chartHint') + '</div>';
    } else if (ct === 'model_agreement') {
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
    // compilable figure source / a booktabs three-line table as .txt next to it. Bibliometric views
    // have paper twins too; only model_agreement remains an on-screen-only matrix.
    if (ct !== 'model_agreement') {
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.emit_latex, true) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'emit_latex\',this.checked)"> ' +
            I18n.t('settings.emitLatex') + '</label>' +
            '<div style="font-size:11px;color:var(--text-dim);margin-top:2px;">' + I18n.t('settings.emitLatexHint') + '</div></div>';
        html += '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.emit_latex_table, true) ? 'checked' : '') + ' onchange="updateParam(\'' + nodeId + '\',\'emit_latex_table\',this.checked)"> ' +
            I18n.t('settings.emitLatexTable') + '</label></div>';
    }
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
    _datasets: null,
    _filter: {},

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
                    var uploadMsg = result.biblio_format
                        ? I18n.t('toast.biblioUploaded').replace('{format}', result.biblio_format).replace('{n}', result.row_count)
                        : result.is_txt
                            ? I18n.t('toast.txtUploaded') + ' (' + result.row_count + ' rows)'
                            : I18n.t('toast.datasetUploaded') + ' (' + result.row_count + ' rows)';
                    /* Dropped duplicates / year-less records are part of what
                       the import decided; a toast that only says "N records"
                       would hide the rows that did not arrive. */
                    if (result.warnings && result.warnings.length) {
                        uploadMsg += ' · ' + result.warnings.join('；');
                    }
                    showToast(uploadMsg);
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

    /* Fill the Upload node's dataset dropdown from the stored files.
       The panel renders synchronously with only the current selection, so the
       list is fetched here, cached with its full metadata, and rendered through
       renderDatasetOptions (which can filter it). */
    async loadDatasetOptions(nodeId) {
        var result = await fetchJSON('/api/data/datasets?limit=1000').catch(function () { return null; });
        if (!result || !result.ok) return;
        var datasets = result.datasets || [];
        dataNodes._datasets = {};
        datasets.forEach(function (d) { dataNodes._datasets[d.dataset_id] = d; });
        /* Re-look-up after the await: the panel may have been rebuilt or closed
           while the request was in flight. */
        if (canvas._settingsNodeId !== nodeId) return;
        if (!canvas.nodes[nodeId]) return;
        dataNodes.renderDatasetOptions(nodeId);
    },

    /* A dropdown row is a whole file description, not just a name: many uploads share
       a filename, so source, size and shape are what tell them apart. */
    _dsLabel(d) {
        var parts = [d.name || I18n.t('name.unnamed'), (d.row_count || 0) + ' ' + I18n.t('settings.rows')];
        if (d.columns && d.columns.length) parts.push(d.columns.length + ' ' + I18n.t('settings.columns'));
        if (d.source && typeof datasetManager !== 'undefined') parts.push(datasetManager._sourceLabel(d.source));
        return parts.join(' · ');
    },

    /* Rebuild the dropdown from the cache, filtered by this node's search term and
       ordered most-recently-used first. selectOptionTags keeps a value that is no
       longer in the list visible rather than silently dropping it to option #0. */
    renderDatasetOptions(nodeId) {
        var select = document.getElementById('dataset-pick-' + nodeId);
        if (!select) return;
        var all = dataNodes._datasets || {};
        var ids = Object.keys(all);
        var list = ids.map(function (id) { return all[id]; });
        list.sort(function (a, b) {
            var ka = String(a.last_used_at || a.created_at || '');
            var kb = String(b.last_used_at || b.created_at || '');
            return ka < kb ? 1 : (ka > kb ? -1 : 0);
        });
        var term = String((dataNodes._filter && dataNodes._filter[nodeId]) || '').trim().toLowerCase();
        if (term) list = list.filter(function (d) { return String(d.name || '').toLowerCase().indexOf(term) >= 0; });
        var node = canvas.nodes[nodeId];
        var current = node && node.params && node.params.dataset_id ? node.params.dataset_id : '';
        var items = list.map(function (d) {
            return { value: d.dataset_id, label: escapeHtml(dataNodes._dsLabel(d)) };
        });
        select.innerHTML = '<option value="">' + escapeHtml(I18n.t('dataSource.choosePlaceholder')) + '</option>' +
            selectOptionTags(items, current, '');
        select.value = current;
        var hint = document.getElementById('dataset-hint-' + nodeId);
        if (hint) {
            if (!ids.length) {
                hint.innerHTML = escapeHtml(I18n.t('dataSource.emptyLibrary')) +
                    ' <button class="menu-btn" onclick="datasetManager.toggle()">' +
                    escapeHtml(I18n.t('dataSource.openManager')) + '</button>';
            } else if (!list.length) {
                hint.textContent = I18n.t('dataSource.noMatch');
            } else {
                hint.innerHTML = '';
            }
        }
    },

    async loadBiblioBasemapOptions(nodeId) {
        var result = await fetchJSON('/api/data/datasets?limit=1000').catch(function () { return null; });
        if (!result || !result.ok) return;
        dataNodes._datasets = {};
        (result.datasets || []).forEach(function (d) { dataNodes._datasets[d.dataset_id] = d; });
        var select = document.getElementById('biblio-basemap-' + nodeId);
        if (!select || !canvas.nodes[nodeId]) return;
        var current = String(canvas.nodes[nodeId].params.basemap_dataset_id || '');
        var items = Object.keys(dataNodes._datasets).map(function (id) {
            return { value: id, label: escapeHtml(dataNodes._dsLabel(dataNodes._datasets[id])) };
        });
        select.innerHTML = '<option value="">' + escapeHtml(I18n.t('biblio.ui.noBasemap')) + '</option>' +
            selectOptionTags(items, current, '');
        select.value = current;
    },

    filterDatasets(nodeId, term) {
        if (!dataNodes._filter) dataNodes._filter = {};
        dataNodes._filter[nodeId] = term;
        dataNodes.renderDatasetOptions(nodeId);
    },

    /* Show the attached file's shape and who reads it: the metadata the dropdown row
       had no room for, plus which nodes on THIS canvas point at the same dataset. */
    toggleDatasetDetail(nodeId) {
        var box = document.getElementById('dataset-detail-' + nodeId);
        if (!box) return;
        if (box.style.display !== 'none') { box.style.display = 'none'; return; }
        var node = canvas.nodes[nodeId];
        var id = node && node.params ? node.params.dataset_id : '';
        if (!id) { box.style.display = 'none'; return; }
        var render = function (meta) {
            if (!meta) { box.style.display = 'none'; return; }
            var users = Object.keys(canvas.nodes).filter(function (nid) {
                var n = canvas.nodes[nid];
                return n && n.type === 'upload' && n.params && n.params.dataset_id === meta.dataset_id;
            });
            var rows = [
                [I18n.t('settings.file'), meta.name || I18n.t('name.unnamed')],
                [I18n.t('datasetMgr.colSource'), typeof datasetManager !== 'undefined' ? datasetManager._sourceLabel(meta.source) : (meta.source || '-')],
                [I18n.t('settings.rows'), String(meta.row_count || 0)],
                [I18n.t('settings.columns'), (meta.columns && meta.columns.length) ? meta.columns.join(', ') : '-'],
                ['id', meta.dataset_id],
                [I18n.t('dataSource.thisCanvasNodes'), users.join(', ') || '-'],
            ];
            if (meta.workflows && meta.workflows.length) rows.push([I18n.t('datasetMgr.colUsedBy'), meta.workflows.join(', ')]);
            box.innerHTML = '<table class="dataset-detail-table"><tbody>' + rows.map(function (r) {
                return '<tr><th>' + escapeHtml(r[0]) + '</th><td>' + escapeHtml(r[1]) + '</td></tr>';
            }).join('') + '</tbody></table>';
            box.style.display = '';
        };
        var cached = dataNodes._datasets && dataNodes._datasets[id];
        if (cached) { render(cached); return; }
        fetchJSON('/api/data/datasets/' + encodeURIComponent(id))
            .then(function (res) {
                if (res && res.ok && res.dataset) { render(res.dataset); return; }
                /* The file is gone from the library, or the read failed. Hiding the box silently
                   is what made 详情 look like a dead button — name the reason instead. */
                showToast(I18n.t('dataSource.detailFailed').replace('{err}', (res && res.error) || ''));
            })
            .catch(function (e) {
                showToast(I18n.t('dataSource.detailFailed').replace('{err}', (e && e.message) || ''));
            });
    },

    /* One crawl paid for is worth reusing across every Upload node on the canvas:
       copy this node's dataset pointer to all the others, no re-picking. */
    applyToOtherUploadNodes(nodeId) {
        var src = canvas.nodes[nodeId];
        if (!src || !src.params || !src.params.dataset_id) return;
        var others = Object.keys(canvas.nodes).filter(function (nid) {
            var n = canvas.nodes[nid];
            return nid !== nodeId && n && n.type === 'upload';
        });
        if (!others.length) { showToast(I18n.t('dataSource.noOtherUploadNodes')); return; }
        others.forEach(function (nid) {
            var n = canvas.nodes[nid];
            n.params.dataset_id = src.params.dataset_id;
            n.params.dataset_name = src.params.dataset_name;
            n.params.row_count = src.params.row_count;
            n._datasetMissing = false;
            var el = canvas._nodeEl(nid);
            if (el) el.classList.remove('node-missing');
            canvas.updateNodeDisplay(nid);
        });
        canvas.saveState();
        showToast(I18n.t('dataSource.appliedToOthers').replace('{n}', others.length));
    },

    /* Attach a stored dataset to the Upload node without re-uploading it: set the
       same three params a fresh upload writes, so the card, preview and the run
       executor all treat it identically. */
    pickFromDataset(nodeId, datasetId) {
        var node = canvas.nodes[nodeId];
        if (!node) return;
        if (!datasetId) {
            node.params.dataset_id = '';
            node.params.dataset_name = '';
            node.params.row_count = '';
            canvas.updateNodeDisplay(nodeId);
            canvas.saveState();
            if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
            return;
        }
        var apply = function (meta) {
            if (!meta) return;
            node.params.dataset_id = meta.dataset_id;
            node.params.dataset_name = meta.name || '';
            node.params.row_count = meta.row_count || 0;
            /* Attaching a live file clears any "reference is broken" state. */
            node._datasetMissing = false;
            var el = canvas._nodeEl(nodeId);
            if (el) el.classList.remove('node-missing');
            canvas.updateNodeDisplay(nodeId);
            canvas.saveState();
            showToast(I18n.t('dataSource.datasetSelected').replace('{name}', meta.name || meta.dataset_id));
            if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
        };
        var cached = dataNodes._datasets && dataNodes._datasets[datasetId];
        if (cached) {
            apply(cached);
            return;
        }
        fetchJSON('/api/data/datasets/' + encodeURIComponent(datasetId))
            .then(function (result) { apply(result && result.ok ? result.dataset : null); })
            .catch(function () { /* offline: leave the node untouched */ });
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
            /* A SUCCESSFUL list is the only answer that licenses clearing an id. A non-OK status,
               a refusal body (the cross-origin guard answers ``{ok:false}`` with a 403), or a shape
               with no ``datasets`` array is the server saying NOTHING — reading it as "every file is
               gone" would clear every Upload node's ``dataset_id`` and then autosave the emptied
               canvas over the author's workflow file. A genuinely empty library returns
               ``{ok:true, datasets:[]}`` and is still honoured below. */
            if (!resp.ok || !result || result.ok === false || !Array.isArray(result.datasets)) return;
            result.datasets.forEach(function (d) { known[d.dataset_id] = d; });
        } catch (e) {
            /* Offline or a dead server: keep the ids. Losing them would mean
               re-uploading a file that is very likely still on disk. */
            return;
        }
        var missing = [];
        var changed = false;
        pending.forEach(function (id) {
            var node = canvas.nodes[id];
            if (!node) return;
            var meta = known[node.params.dataset_id];
            if (!meta) {
                node.params.dataset_id = '';
                node.params.dataset_name = '';
                node.params.row_count = '';
                /* The file is gone: the id is cleared so a run never reads a dead
                   pointer, but the node remembers it WAS broken so the panel and the
                   box say so, not just "no file". */
                node._datasetMissing = true;
                var missEl = canvas._nodeEl(id);
                if (missEl) missEl.classList.add('node-missing');
                missing.push(node.title || id);
                changed = true;
            } else {
                var beforeName = node.params.dataset_name;
                var beforeCount = node.params.row_count;
                node.params.dataset_name = meta.name || node.params.dataset_name || '';
                node.params.row_count = meta.row_count || 0;
                if (beforeName !== node.params.dataset_name || beforeCount !== node.params.row_count) changed = true;
                if (node._datasetMissing) {
                    node._datasetMissing = false;
                    changed = true;
                }
                var okEl = canvas._nodeEl(id);
                if (okEl) okEl.classList.remove('node-missing');
            }
            canvas.updateNodeDisplay(id);
            if (canvas._settingsNodeId === id) openSettings(id);
        });
        /* Only a real change earns a save; a healthy canvas merely refreshed must not push an undo
           step, light the dirty dot, or rewrite the workflow file every time it loads. */
        if (changed) canvas.saveState();
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
        /* Pin the run the user loaded, so a historical preview does not read the
           newest rows of each node independently. */
        if (typeof runResults !== 'undefined') runResults.payload(payload);
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
            if (typeof runResults !== 'undefined') runResults.payload(payload);
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
    if (typeof runResults !== 'undefined') runResults.payload(payload);
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
        if (typeof runResults !== 'undefined') runResults.payload(payload);

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
            } else if (!hasChartLibrary()) {
                /* A board cell that cannot paint names the bundle that is gone: an empty cell reads
                   as "this node produced no chart", which is a different fact entirely. */
                body.innerHTML = '<div class="dashboard-cell-note">' + escapeHtml(chartLibraryMissingMessage()) + '</div>';
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
        if (!hasChartLibrary()) {
            paintChartLibraryNote(el);
            return null;
        }
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
        /* null means "no chart library, and the panel already says so" — drawing on it would throw
           and replace a named refusal with a console error. */
        if (!this._ensureChart()) return;
        var inst = this._instance;
        var metricLabel = I18n.t('history.metric.' + (metric || 'rows'));
        var wf = document.getElementById('history-workflow-select').value;
        var subtext = wf ? wf : I18n.t('history.allWorkflows');
        var pal = chartPalette();
        var ink = pal.ink;
        var dim = pal.dim;
        var faint = pal.faint;
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
                subtextStyle: { color: pal.dim, fontSize: 11, fontFamily: chartFont },
            },
            tooltip: {
                trigger: 'axis',
                backgroundColor: pal.tooltipBg,
                borderColor: pal.tooltipBorder, borderWidth: 1,
                textStyle: { color: ink, fontSize: 12, fontFamily: chartFont },
                axisPointer: { type: 'line', lineStyle: { color: pal.axisLine, type: 'dashed' } },
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
                axisLine: { lineStyle: { color: pal.axisLine } },
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
            // The dialog above is the human half; ``confirm: true`` is the server's own gate,
            // held by every other bulk destructive route so a stray or cross-origin call cannot
            // wipe the whole comparison chart (see ``/api/history/clear``).
            const resp = await fetch('/api/history/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm: true }),
            });
            const result = await resp.json();
            if (!result.ok) {
                showToast(I18n.t('toast.previewFailed') + ': ' + (result.error || resp.status));
                return;
            }
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

/* ── Outline sidebar (right) ────────────────────────────────────────── */
/* A flat map of every node on the canvas: click a row and the camera jumps to it at a
   readable size. The list is rebuilt from the model inside canvas.saveState() (canvas.js),
   which is the single chokepoint every structural change passes through — so it can never
   drift from the graph, and this object owns only the DOM and the jump. Rows are built with
   createElement + textContent (never an innerHTML string keyed by the node id), because a
   workflow file can author any id and an inline handler would have to re-escape it. */
const Outline = {
    /* The active filter query (lower-cased); the finder input writes it via setFilter.
       It lives on the object, not the DOM, so render() stays the single source of what
       shows and a language switch repaint can re-apply it to the new labels. */
    _query: '',

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

    /* Filter the list to rows whose label, node type or tag contain the query (matching the
       type too lets "src"/"SRC" find sources whatever language the label is in). */
    setFilter(query) {
        this._query = String(query == null ? '' : query).toLowerCase();
        this.render();
    },

    /* Ctrl/Cmd+F: reveal the finder — expand the sidebar if collapsed and focus its filter
       box — so the user is typing to find a node, not folding the selected one. */
    revealFilter() {
        var panel = document.getElementById('outline-panel');
        if (panel && panel.classList.contains('collapsed')) this.toggle();
        var box = document.getElementById('outline-filter');
        if (box) {
            box.focus();
            if (box.select) box.select();
        }
    },

    render() {
        var list = document.getElementById('outline-list');
        if (!list) return;
        var rows = this._collect();
        if (this._query) {
            var q = this._query;
            var outline = this;
            rows = rows.filter(function (r) {
                return (r.label + ' ' + r.type + ' ' + outline._tag(r.type)).toLowerCase().indexOf(q) >= 0;
            });
        }
        list.textContent = '';
        if (rows.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'outline-empty';
            empty.textContent = this._query ? I18n.t('outline.noMatch') : I18n.t('outline.noNodes');
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
        /* The outline mirrors the GRAPH's selection, and the graph can hold a whole group
           (shift-click / marquee). Reading only the anchor lit just the last-clicked row while
           every selected box on the canvas was highlighted — the sidebar disagreed with the
           graph about what was selected. Highlight every member; fall back to the single anchor
           so a caller that sets selectedNode without a group still lights its row. */
        var group = canvas.selectedNodes && canvas.selectedNodes.length ? canvas.selectedNodes : [canvas.selectedNode];
        var active = {};
        group.forEach(function (id) {
            if (id != null) active[id] = true;
        });
        list.querySelectorAll('.outline-row').forEach(function (row) {
            row.classList.toggle('outline-active', active[row.dataset.node] === true);
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
        var box = document.getElementById('outline-filter');
        if (box) {
            box.placeholder = I18n.t('outline.filterPlaceholder');
            var outline = this;
            box.addEventListener('input', function (e) {
                outline.setFilter(e && e.target ? e.target.value : box.value);
            });
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
    /* Run verdicts carry a localized status word in their tooltip; the badge holds
       no state of its own, so repainting from the loaded map is the whole update. */
    if (typeof runResults !== 'undefined') canvas.applyRunStatuses(runResults.statuses);
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
    /* The export guide's sentences are served per language, so an open guide has to refetch —
       the same reason the cookie guide does. */
    if (typeof sourceHelp !== 'undefined') sourceHelp.onLanguageChange();
    /* Both of these had the method and never got the call, so their tables kept the
       old language while the rest of the page re-stamped around them. `datasetManager`
       is a top-level `var`, which does make it a window property — but the guard is
       written against the binding for the same reason the resume bar once wasn't. */
    if (typeof datasetManager !== 'undefined') datasetManager.onLanguageChange();
    if (typeof lexiconManager !== 'undefined') lexiconManager.onLanguageChange();
    if (typeof historyPanel !== 'undefined') historyPanel.onLanguageChange();
    if (typeof wfFiles !== 'undefined') wfFiles.onLanguageChange();
    /* The Style menu's baseline hint is painted by JS from the last layout read, so a
       language switch must re-stamp it rather than leave one English line in a Chinese menu. */
    if (typeof LayoutStrategy !== 'undefined') LayoutStrategy._paint();
    /* The scheduled-task dock is JS-rendered like those, and its table says 「下次运行」 in the
       task's own zone — a row left in the old language would be the one word in the panel that
       did not switch. */
    if (typeof schedulesManager !== 'undefined') schedulesManager.onLanguageChange();
    /* The bibliometrics dock prints its run/node pickers, the shape of the stored table and the
       paging line from here, so nothing `I18n.apply()` re-stamps reaches them. */
    if (typeof biblioWorkspace !== 'undefined') biblioWorkspace.onLanguageChange();
    /* A reusable node's inside preview is JS-painted (title, meta, slot labels,
       statuses), so an open preview would otherwise keep the old language. */
    if (typeof ReusableNodes !== 'undefined' && ReusableNodes.repaintPreview) ReusableNodes.repaintPreview();
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
        /* It lives in the same bottom slot as the other docks: opening it must shut them, and it
           is listed in DOCKED_PANELS so opening any of THEM shuts this one. */
        closeDockedPanels('processes-panel');
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
                    '<div class="proc-line proc-err">' + I18n.t('processes.fetchFailed') + '</div>';
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
        var trap = null;
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
            if (trap) document.removeEventListener('keydown', trap);
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
            var fieldRows = {};
            opts.fields.forEach(function (f) {
                var row = document.createElement('label');
                row.className = 'dialog-field';
                row.appendChild(document.createTextNode(f.label));
                var box;
                if (f.type === 'select') {
                    /* A dropdown field: the smart-clear run/node pickers. ``collectForm`` reads
                       every field by ``.value``, which a <select> answers with its chosen option,
                       so the collection path is shared with the number/text fields unchanged. */
                    box = document.createElement('select');
                    box.className = 'settings-input';
                    box.id = f.id;
                    (f.options || []).forEach(function (opt) {
                        var o = document.createElement('option');
                        o.value = opt.value;
                        o.textContent = opt.label;
                        box.appendChild(o);
                    });
                    if (f.value !== undefined) box.value = f.value;
                } else {
                    box = document.createElement('input');
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
                }
                row.appendChild(box);
                listArea.appendChild(row);
                fieldRows[f.id] = row;
            });
            /* A field may declare which values of ANOTHER field it belongs to (the schedule
               editor: a time only means something for daily/weekly, a cron expression only for
               cron). Without this every trigger kind showed every box, and the ones that did not
               apply were silently ignored on save — a form asking for four answers to one
               question. The rule is read from the live select, so switching 触发方式 re-filters. */
            var dependent = (opts.fields || []).filter(function (f) {
                return f.onlyWhen && f.onlyWhen.field;
            });
            function applyFieldVisibility() {
                dependent.forEach(function (f) {
                    var row = fieldRows[f.id];
                    var source = document.getElementById(f.onlyWhen.field);
                    if (!row || !source) return;
                    var wanted = f.onlyWhen.values || [];
                    row.style.display = wanted.indexOf(source.value) >= 0 ? '' : 'none';
                });
            }
            dependent.forEach(function (f) {
                var source = document.getElementById(f.onlyWhen.field);
                if (source && !source.dataset._onlyWhenBound) {
                    source.dataset._onlyWhenBound = '1';
                    source.addEventListener('change', applyFieldVisibility);
                }
            });
            applyFieldVisibility();
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
        /* Modal accessibility: role/aria-modal/aria-labelledby mark the box as a real modal so a
           screen reader announces it and not the background, and a Tab trap keeps the caret among
           the dialog's own controls while it is open. The initial focus moves INTO the dialog so a
           keyboard user is not left behind on the page body (an input dialog is focused below). */
        if (box) {
            box.setAttribute('role', 'dialog');
            box.setAttribute('aria-modal', 'true');
            if (msgEl && msgEl.id) box.setAttribute('aria-labelledby', msgEl.id);
        }
        function dialogFocusables() {
            if (!box) return [];
            return box.querySelectorAll('button, [href], input, select, textarea, [tabindex]');
        }
        function onDialogTab(e) {
            if (e.key !== 'Tab') return;
            var items = dialogFocusables();
            if (!items.length) return;
            var first = items[0];
            var last = items[items.length - 1];
            if (e.shiftKey && e.target === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && e.target === last) { e.preventDefault(); first.focus(); }
        }
        document.addEventListener('keydown', onDialogTab);
        trap = onDialogTab;
        if (!opts.input) {
            var _first = dialogFocusables();
            if (_first.length) _first[0].focus();
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

/* ── Loaded run results ──────────────────────────────────────
   The canvas shows ONE run's results at a time. On entry that is the newest
   run filed under this workflow's structure (the default the user asked for);
   运行记录 ▸ 当前工作流 can load any earlier one. The id is pinned into every
   preview/chart/dashboard payload, so the server reads that exact attempt
   instead of independently picking each node's newest rows — which could stitch
   last night's node-1 to this morning's node-2 and call it one table.

   Node verdicts come from the run ledger (`/api/runs/for-workflow` and the live
   `/api/workflow/status`), never from the canvas's own guesses: several nodes
   can be `running` at once in parallel mode, and `done`/`restored` are the only
   two words that mean success. */
var runResults = {
    runId: '',
    runIds: [],
    run: null,
    runs: [],
    statuses: {},
    followLive: false,
    workflowFingerprint: '',
    _seq: 0,
    _lastApplied: '',

    isLoaded(runId) {
        var id = String(runId || '');
        return !!id && (id === this.runId || this.runIds.indexOf(id) >= 0);
    },

    /* The record that actually holds a node's verdict. In a split serial canvas one
       attempt owns several run rows, and a node belongs to exactly one of them. */
    runIdFor(nodeId) {
        var info = this.statuses && this.statuses[nodeId];
        return String((info && info.run_id) || this.runId || '');
    },

    async refresh(selectRunId) {
        /* A canvas with nothing on it has no structure to match — and the server
           must not be asked to fingerprint an empty workflow. */
        if (typeof canvas === 'undefined' || !canvas || !Object.keys(canvas.nodes || {}).length) {
            this.clear();
            return null;
        }
        var seq = ++this._seq;
        var result;
        try {
            var resp = await fetch('/api/runs/for-workflow', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workflow: canvas.toWorkflowJSON(), limit: 50 }),
            });
            result = await resp.json();
        } catch (e) {
            return null;
        }
        /* A second refresh started while this one was in flight (a run finishing
           during boot, a quick tab switch). The newer answer is the truth. */
        if (seq !== this._seq) return null;
        if (!result || !result.ok) return null;
        this.runs = result.runs || [];
        this.workflowFingerprint = result.workflow_fingerprint || '';
        var wanted = String(selectRunId || this.runId || '');
        var run =
            this.runs.filter(function (r) {
                return r.run_id === wanted;
            })[0] ||
            this.runs[0] ||
            null;
        if (!run) {
            this.clear();
            return null;
        }
        this._apply(run, { live: run.status === 'running' });
        return run;
    },

    /* One run's node statuses → the canvas badges. The map is replaced, not merged:
       loading another run must not leave a green check from the previous one. */
    _apply(run, opts) {
        var live = !!(opts && opts.live);
        this.run = run;
        this.runId = String(run.run_id || '');
        this.runIds = this.runId ? [this.runId] : [];
        this.followLive = live;
        var map = {};
        (run.nodes || []).forEach(function (n) {
            var nid = String(n.node_id || '');
            if (!nid) return;
            map[nid] = {
                status: String(n.status || ''),
                row_count: Number(n.row_count || 0),
                error: String(n.error || ''),
                run_id: String(run.run_id || ''),
            };
        });
        this.statuses = map;
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses(map);
        if (this._lastApplied !== this.runId) {
            this._lastApplied = this.runId;
            this._repaint();
        }
    },

    /* Load an arbitrary record from 运行记录. The list the panel already holds
       carries the node map, so the common path costs no request; a run that has
       since been deleted falls back to one detail read and says so when that
       fails too. */
    async load(runId) {
        var id = String(runId || '').trim();
        if (!id) return null;
        /* A selection is newer than any read already in flight: without this a
           boot-time refresh could land afterwards and put today's latest run back. */
        this._seq += 1;
        var found = (this.runs || []).filter(function (r) {
            return r.run_id === id;
        })[0];
        if (!found) {
            try {
                var resp = await fetch('/api/runs/' + encodeURIComponent(id));
                var result = await resp.json();
                if (result && result.ok && result.run) found = result.run;
            } catch (e) {
                found = null;
            }
        }
        if (!found) {
            showToast(I18n.t('runsMgr.loadFailed').replace('{rid}', id));
            return null;
        }
        /* Reloading the same record is a real request to repaint (its rows may
           have changed, or a cell failed last time). */
        this._lastApplied = '';
        this._apply(found, { live: found.status === 'running' });
        if (window.runsManager) runsManager.refreshIfOpen();
        var when = found.started_at || found.run_id || id;
        showToast(I18n.t('runsMgr.loadedToast').replace('{when}', when));
        return found;
    },

    /* A run just started (Run or 从此节点重跑). Old verdicts go away immediately;
       the first status tick paints the nodes the worker has reached. */
    beginLive(runId) {
        /* The new attempt outranks any read that started before it. */
        this._seq += 1;
        this.runId = String(runId || '');
        this.runIds = this.runId ? [this.runId] : [];
        this.run = null;
        this.statuses = {};
        this.followLive = true;
        this._lastApplied = this.runId;
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses({});
    },

    /* Live status map from /api/workflow/status. Ignored when the user has
       deliberately loaded an older run mid-flight — following the worker would
       yank their choice out from under them. */
    applyLive(states, runIds) {
        if (!this.followLive) return;
        if (Array.isArray(runIds) && runIds.length) {
            this.runIds = runIds.map(String);
            if (!this.runId || this.runIds.indexOf(this.runId) < 0) this.runId = this.runIds[0] || '';
        }
        var map = Object.assign({}, this.statuses || {});
        Object.keys(states || {}).forEach(function (nid) {
            var s = states[nid];
            if (!s) return;
            map[nid] = {
                status: String(s.status || ''),
                row_count: Number(s.row_count || 0),
                error: String(s.error || ''),
                run_id: String(s.run_id || ''),
            };
        });
        this.statuses = map;
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses(map);
    },

    /* The worker wrote its verdict. Re-read the record so the panel's marker and
       the node map agree with what was persisted, and stop following its stream. */
    finishLive() {
        if (!this.followLive) return;
        this.followLive = false;
        /* A split serial attempt owns several run records, one per workflow. The
           live map already covers every component's nodes; re-reading just one id
           would drop the other components' badges. The panel still refreshes, and
           a single-record run is re-read so its final row counts are authoritative. */
        if (this.runIds.length > 1) {
            if (window.runsManager) runsManager.refreshIfOpen();
            return;
        }
        /* The record now holds the final rows, even though the id did not change;
           clearing the applied marker makes the refresh repaint open panels. */
        this._lastApplied = '';
        this.refresh(this.runId);
        if (window.runsManager) runsManager.refreshIfOpen();
    },

    canRerun(nodeId) {
        var info = this.statuses && this.statuses[nodeId];
        if (!info || !this.runIdFor(nodeId)) return false;
        return (info.status === 'done' || info.status === 'restored') && Number(info.row_count || 0) > 0;
    },

    rerunFrom(nodeId) {
        if (!this.canRerun(nodeId)) {
            showToast(I18n.t('toast.rerunNoResult'));
            return;
        }
        var runId = this.runIdFor(nodeId);
        if (typeof workflow === 'undefined' || !workflow.rerunNode) return;
        workflow.rerunNode(nodeId, runId);
    },

    /* Every preview of a node's rows carries the loaded run, so one screen never
       mixes two attempts. */
    payload(payload) {
        if (this.runId) payload.run_id = this.runId;
        return payload;
    },

    /* Panels already on screen follow the newly loaded run instead of continuing to
       show the previous one's picture. Closed panels are left closed: loading a
       run is not a request to open a chart. */
    _repaint() {
        if (typeof document === 'undefined' || !document.getElementById) return;
        var chartPanel = document.getElementById('chart-preview-panel');
        if (chartPanel && chartPanel.classList.contains('open') && _chartPreviewNodeId) {
            dataNodes.previewVisualize(_chartPreviewNodeId);
        }
        var dash = document.getElementById('dashboard-panel');
        if (dash && dash.classList.contains('open') && typeof dashboard !== 'undefined') {
            dashboard.open();
        }
        var preview = document.getElementById('data-preview-panel');
        if (preview && preview.classList.contains('open') && dataPreview._payload && dataPreview._payload.node_id) {
            dataPreview._payload.run_id = this.runId || undefined;
            if (!dataPreview._payload.run_id) delete dataPreview._payload.run_id;
            dataPreview._offset = 0;
            dataPreview._fetch();
        }
    },

    clear() {
        this._seq += 1;
        this.runId = '';
        this.runIds = [];
        this.run = null;
        this.runs = [];
        this.statuses = {};
        this.followLive = false;
        this.workflowFingerprint = '';
        this._lastApplied = '';
        if (typeof canvas !== 'undefined' && canvas && canvas.applyRunStatuses) canvas.applyRunStatuses({});
    },
};

/* ─── Edit-time diagnostics ───────────────────────────────────────────
   Before this, a wrong column or a missing config only surfaced when a run was
   already paid for. The backend answers WHAT each node emits and reads (the schema
   truth lives beside the executors); the frontend decides WHICH nodes to flag and
   words it in the UI's language. Config/wiring problems come from the offline
   validateDetailed mirror; missing-column problems are the diff between a node's
   reads and its upstream's known columns — never flagged when the upstream is a
   crawl/comment/resume whose columns the server cannot see without running. */
var Diagnostics = {
    _timer: null,
    _armed: false,
    _columns: {},
    _reads: {},
    _problems: {},

    schedule() {
        // Armed only by the real page boot (app.js), so a workflow-only harness —
        // or any scenario that never dispatches DOMContentLoaded — fires nothing.
        if (!this._armed) return;
        var self = this;
        if (this._timer) clearTimeout(this._timer);
        this._timer = setTimeout(function () {
            self._timer = null;
            try { self.refresh(); } catch (e) { /* a background diagnostic never breaks the page */ }
        }, 500);
    },

    async refresh() {
        /* A canvas-only or workflow-only harness has no `canvas`; and a failed
           diagnostic must never crash the page it decorates — guard the whole body. */
        if (typeof canvas === 'undefined' || !canvas || !canvas.nodes) return;
        try {
            /* Only the serialisable model goes over the wire: a node's `el` is a live DOM
               element (circular), so the whole node object cannot be JSON.stringify'd. */
            var clean = {};
            Object.keys(canvas.nodes).forEach(function (id) {
                var n = canvas.nodes[id];
                clean[id] = { id: id, type: n.type, title: n.title || '', params: n.params || {} };
            });
            var payload = {
                nodes: clean,
                connections: canvas.connections,
                settings: { disabledTypes: (canvas.disabledTypes || []).slice() },
            };
            var result = await fetchJSON('/api/workflow/diagnostics', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).catch(function () { return null; });
            if (!result || !result.ok) return; /* offline: keep the last known picture */
            this._columns = result.columns || {};
            this._reads = result.reads || {};
            this.recompute();
        } catch (e) { /* diagnostics are decoration; a failure leaves the last picture */ }
    },

    /* The columns a node RECEIVES = union of its direct upstream producers' emitted
       columns; unknown (null) if any upstream is unknown, so a crawl never triggers a
       false "missing column" on everything below it. */
    inputColumns(id) {
        var ups = canvas.connections.filter(function (c) { return String(c.to) === String(id); }).map(function (c) { return c.from; });
        if (!ups.length) return [];
        var cols = [];
        for (var i = 0; i < ups.length; i += 1) {
            var c = this._columns[ups[i]];
            if (c === null || c === undefined) return null;
            c.forEach(function (x) { if (cols.indexOf(x) < 0) cols.push(x); });
        }
        return cols;
    },

    missingColumnProblems() {
        var out = {};
        var self = this;
        var nodes = canvas.nodes;
        Object.keys(this._reads).forEach(function (id) {
            var reads = self._reads[id] || [];
            if (!reads.length) return;
            var input = self.inputColumns(id);
            if (input === null) return; /* unknown upstream: never guess */
            var missing = reads.filter(function (col) { return input.indexOf(col) < 0; });
            if (missing.length) {
                var node = nodes[id];
                var label = (node && node.title) || id;
                out[id] = [I18n.t('diagnostics.missingColumn').replace('{cols}', missing.join(', ')).replace('{node}', label)];
            }
        });
        return out;
    },

    recompute() {
        if (typeof canvas === 'undefined' || !canvas || !canvas.nodes) return;
        var perNode = workflow.validateDetailed().perNode || {};
        var merged = {};
        Object.keys(perNode).forEach(function (id) { merged[id] = perNode[id].slice(); });
        var missing = this.missingColumnProblems();
        Object.keys(missing).forEach(function (id) {
            (merged[id] = merged[id] || []).push.apply(merged[id], missing[id]);
        });
        this._problems = merged;
        if (typeof canvas._applyValidationVisuals === 'function') canvas._applyValidationVisuals(merged);
        renderCostSummary();
    },

    problems(id) { return this._problems[id] || []; },
    outputColumns(id) {
        var c = this._columns[id];
        return (c === undefined) ? null : c;
    },
};

/* Cost estimate: rows are read straight from the crawl matrix's own per-mode defaults
   (target_count etc.), so nothing here re-declares a platform constant; LLM calls are
   one per row for an llm-mode analyzer, and capped at 30 for a topic/cluster label.
   Unbounded cases (a comment crawl with no limit) are reported as such, not as a
   precise number. */
function _matrixField(platform, modeKey, fieldKey) {
    if (typeof Capabilities === 'undefined' || !Capabilities.ready()) return null;
    var mode = Capabilities.mode(platform, modeKey);
    if (!mode || !mode.fields) return null;
    for (var i = 0; i < mode.fields.length; i += 1) {
        if (mode.fields[i].key === fieldKey) return mode.fields[i];
    }
    return null;
}

function _splitUrls(value) {
    return String(value || '').split(/[\r\n]+/).map(function (s) { return s.trim(); }).filter(Boolean);
}

function _sourceRows(node) {
    var p = node.params || {};
    if (node.type === 'comment') {
        var n = _splitUrls(p.urls).length;
        var lim = parseInt(p.comment_limit, 10) || 0;
        return lim > 0 ? { rows: n * lim, unbounded: false } : { rows: n, unbounded: n > 0 };
    }
    if (node.type === 'upload') {
        return { rows: parseInt(p.row_count, 10) || 0, unbounded: false };
    }
    var f = _matrixField(p.platform, p.collect || p.mode || '', 'target_count');
    var val = parseInt(p.target_count, 10);
    if (isNaN(val)) val = f && f.default != null ? f.default : 50;
    if (f && f.minimum != null) val = Math.max(val, f.minimum);
    return { rows: val, unbounded: false };
}

function _rowsAt(id, memo, stack) {
    memo = memo || {};
    stack = stack || {};
    if (memo[id] !== undefined) return memo[id];
    if (stack[id]) return { rows: 0, unbounded: false };
    stack[id] = true;
    var node = canvas.nodes[id];
    var r;
    if (!node) {
        r = { rows: 0, unbounded: false };
    } else if (node.type === 'source' || node.type === 'comment' || node.type === 'upload') {
        r = _sourceRows(node);
    } else {
        var ups = canvas.connections.filter(function (c) { return String(c.to) === String(id); }).map(function (c) { return c.from; });
        var total = 0;
        var unb = false;
        ups.forEach(function (u) { var x = _rowsAt(u, memo, stack); total += x.rows; unb = unb || x.unbounded; });
        r = { rows: total, unbounded: unb };
    }
    delete stack[id];
    memo[id] = r;
    return r;
}

function _processLlm(op, p) {
    var llmOps = ['clean', 'emotion', 'tendency', 'sentiment', 'ner', 'aggression'];
    if (llmOps.indexOf(op) < 0) return false;
    var mode = String(p.mode || p.method || '');
    return mode === 'llm';
}

/* A label step asks the LLM once per row it summarises, and the node caps how many rows
   it will label (topic_label -> label_max_topics, cluster_label -> cluster_max_groups).
   The row-flow model OVER-counts a label node: _rowsAt hands back the whole upstream
   table, not the handful of topic/cluster rows the node actually reads, so the cap — not
   the row sum — is what bounds the real spend. Defaults match the node renderers. */
function _isLabelOp(op) {
    return op === 'topic_label' || op === 'cluster_label' || op === 'cluster_review';
}

function _labelCallCap(op, src) {
    var s = src || {};
    if (op === 'topic_label') {
        var t = parseInt(s.label_max_topics, 10);
        return isNaN(t) ? 30 : t;
    }
    if (op === 'cluster_label') {
        var g = parseInt(s.cluster_max_groups, 10);
        return isNaN(g) ? 60 : g;
    }
    if (op === 'cluster_review') {
        var rv = parseInt(s.review_max_groups, 10);
        return isNaN(rv) ? 60 : rv;
    }
    return 0;
}

function estimateCost() {
    var memo = {};
    var crawlRows = 0;
    var llmCalls = 0;
    var unbounded = false;
    Object.keys(canvas.nodes).forEach(function (id) {
        var node = canvas.nodes[id];
        var p = node.params || {};
        if (node.type === 'source' || node.type === 'comment' || node.type === 'upload') {
            var s = _sourceRows(node);
            crawlRows += s.rows;
            unbounded = unbounded || s.unbounded;
        }
        var here = _rowsAt(id, memo);
        if (node.type === 'process' && _processLlm(node.operation || p.operation, p)) {
            llmCalls += here.rows;
            unbounded = unbounded || here.unbounded;
        } else if (node.type === 'analysis') {
            /* A label op is either the analysis node's OWN operation (the shape the canvas
               saves — this was the miss, contributing 0) or one of its p.steps. Both count. */
            var ownOp = String(node.operation || p.operation || '');
            if (_isLabelOp(ownOp)) {
                llmCalls += Math.min(here.rows, _labelCallCap(ownOp, p));
            }
            (p.steps || []).forEach(function (st) {
                if (st && _isLabelOp(st.op)) {
                    llmCalls += Math.min(here.rows, _labelCallCap(st.op, st));
                }
            });
        }
    });
    return { crawlRows: crawlRows, llmCalls: llmCalls, unbounded: unbounded };
}

function renderCostSummary() {
    var el = document.getElementById('cost-summary');
    if (!el) return;
    var c = estimateCost();
    if (!Object.keys(canvas.nodes).length) { el.textContent = ''; el.style.display = 'none'; return; }
    var rows = c.unbounded ? I18n.t('diagnostics.costUnbounded') : ('≈' + c.crawlRows);
    el.style.display = '';
    el.textContent = I18n.t('diagnostics.costRows') + ' ' + rows + ' · ' +
        I18n.t('diagnostics.costLlm') + ' ≈' + c.llmCalls;
    el.title = I18n.t('diagnostics.costHint');
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

/* ── Auto-layout strategy (Style menu) ──────────────────────────
   The Layout button has two answers: the topological algorithm, or the positions
   from a canvas snapshot the user designated as this workflow's baseline. The
   baseline is per SAVED workflow (its file stem), stored server-side, because "where
   this canvas belongs" is part of the canvas's state — not a global preference.
   Nodes the snapshot does not know keep the algorithm's placement, so a later-added
   node is still laid out instead of staying on top of an old one. */
var LayoutStrategy = {
    _layout: null,
    _snapshot: null,

    current() {
        return this._layout || {};
    },

    reset() {
        this._layout = null;
        this._snapshot = null;
    },

    _workflowName() {
        return (typeof workflow !== 'undefined' && workflow.currentFile) || '';
    },

    async refresh() {
        var name = this._workflowName();
        if (!name) {
            this._layout = { workflow_name: '', strategy: 'algorithm', snapshot: null, baseline_missing: false };
            this._paint();
            return this._layout;
        }
        var result = await fetchJSON('/api/workflow/history/layout?workflow=' + encodeURIComponent(name));
        if (result && result.ok && result.layout) {
            this._layout = result.layout;
        } else if (!this._layout || this._layout.workflow_name !== name) {
            /* A read failure leaves the select on the algorithm, which is the strategy
               that always works. It must not claim a baseline it could not read. */
            this._layout = { workflow_name: name, strategy: 'algorithm', snapshot: null, baseline_missing: false };
        }
        this._paint();
        return this._layout;
    },

    _paint() {
        var layout = this._layout || { workflow_name: '', strategy: 'algorithm', snapshot: null, baseline_missing: false };
        var select = document.getElementById('layout-strategy');
        if (select) select.value = layout.strategy === 'baseline' ? 'baseline' : 'algorithm';
        /* The style menu's select is themed by CustomSelect: setting the native value
           updates the control but not the visible trigger, so the menu would say
           「算法排布」 while the saved strategy is 「按历史基准」. */
        if (typeof CustomSelect !== 'undefined' && CustomSelect.refreshAll) CustomSelect.refreshAll();
        var hint = document.getElementById('layout-baseline-hint');
        if (!hint) return;
        hint.classList.toggle('missing', !!layout.baseline_missing);
        if (layout.baseline_missing) {
            hint.textContent = I18n.t('style.layoutBaselineMissing');
            hint.title = I18n.t('style.layoutBaselineMissing');
        } else if (layout.snapshot) {
            var label = String(layout.snapshot.label || '') || I18n.t('wfHistory.untitled');
            hint.textContent = label + (wfFiles._when(layout.snapshot.created_at) ? ' · ' + wfFiles._when(layout.snapshot.created_at) : '');
            hint.title = label;
        } else {
            hint.textContent = this._workflowName() ? I18n.t('style.layoutBaselineNone') : I18n.t('wfHistory.needSaved');
            hint.title = '';
        }
    },

    async setStrategy(strategy) {
        var name = this._workflowName();
        if (!name) {
            showToast(I18n.t('wfHistory.needSaved'));
            this._paint();
            return;
        }
        var wanted = strategy === 'baseline' ? 'baseline' : 'algorithm';
        var snapshotId = (this._layout && this._layout.snapshot && this._layout.snapshot.id) || '';
        if (wanted === 'baseline' && !snapshotId) {
            showToast(I18n.t('wfHistory.noBaseline'));
            this._paint();
            return;
        }
        var result = await fetchJSON('/api/workflow/history/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ workflow_name: name, strategy: wanted, snapshot_id: snapshotId }),
        });
        if (result && result.ok) {
            this._layout = result.layout;
            this._paint();
            if (wanted === 'baseline') showToast(I18n.t('wfHistory.baselineSet'));
        } else {
            showToast((result && result.error) || I18n.t('wfHistory.baselineFailed'));
            this._paint();
        }
    },

    async setBaseline(snapshotId) {
        var name = this._workflowName();
        if (!name) {
            showToast(I18n.t('wfHistory.needSaved'));
            return;
        }
        var result = await fetchJSON('/api/workflow/history/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({ workflow_name: name, strategy: 'baseline', snapshot_id: snapshotId }),
        });
        if (result && result.ok) {
            this._layout = result.layout;
            this._snapshot = null;
            this._paint();
            showToast(I18n.t('wfHistory.baselineSet'));
        } else {
            showToast((result && result.error) || I18n.t('wfHistory.baselineFailed'));
        }
    },

    /* Returns true when this strategy owned the action (arranged, or refused by name);
       false lets the caller run the ordinary algorithm. */
    async layout() {
        var name = this._workflowName();
        if (!name) return false;
        if (!this._layout || this._layout.workflow_name !== name) await this.refresh();
        var layout = this._layout || {};
        if (layout.strategy !== 'baseline') return false;
        if (layout.baseline_missing || !layout.snapshot) {
            showToast(I18n.t(layout.baseline_missing ? 'style.layoutBaselineMissing' : 'wfHistory.noBaseline'));
            return true;
        }
        if (!this._snapshot || this._snapshot.id !== layout.snapshot.id) {
            var result = await fetchJSON('/api/workflow/history/get?id=' + encodeURIComponent(layout.snapshot.id));
            if (!result || !result.ok || !result.snapshot) {
                showToast((result && result.error) || I18n.t('wfHistory.baselineFailed'));
                return true;
            }
            this._snapshot = result.snapshot;
        }
        var saved = {};
        ((this._snapshot.workflow && this._snapshot.workflow.nodes) || []).forEach(function (node) {
            if (node && node.id !== undefined && node.id !== null) saved[String(node.id)] = node;
        });
        canvas.batchHistory(function () {
            /* Algorithm first, so nodes the baseline never saw get a real place; then
               the saved positions replace it for the nodes it knows. */
            canvas.autoLayout({ silent: true });
            Object.keys(canvas.nodes).forEach(function (id) {
                var node = saved[String(id)];
                var el = canvas._nodeEl(id);
                if (!node || !el) return;
                var x = Number(node.x);
                var y = Number(node.y);
                if (!Number.isFinite(x) || !Number.isFinite(y)) return;
                el.style.left = Math.round(x) + 'px';
                el.style.top = Math.round(y) + 'px';
            });
            canvas.scheduleRender();
        });
        canvas.resetView();
        showToast(I18n.t('toast.layoutApplied'));
        return true;
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
