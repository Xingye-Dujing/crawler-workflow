/* ============================================================================
   zenviz.js — host side of the embedded Chart Studio

   The studio (zenviz.html) is a full chart-authoring workbench. This module
   wires it into the workflow so visualization becomes a stage of the pipeline
   rather than a separate tool:

       workflow node ──(dataset)──▶ chart studio ──(PNG)──▶ export folder

   · open()            show the overlay and mount the iframe (once)
   · openForNode(id)   open it and auto-load that node — but only if the node
                       can actually be loaded, so a Visualize node with nothing
                       wired into it explains itself instead of failing
   · refreshSources()  list the canvas's nodes, disabling the ones that cannot
                       supply a table right now and carrying the reason why.
                       The picker is a checklist — several nodes can be chosen at
                       once, so the loaded table is their combination
   · loadSelected()    pull the selected nodes' tables into the studio, either
                       appended (union of columns) or aligned on the columns they
                       share, then hand the result to the iframe
   · saveBack()        snapshot the studio's chart and save it next to the
                       other workflow exports

   The studio also brings its own top nav. Embedded, that row is suppressed and
   its chips are mirrored into this bar (see _renderMenus) so the studio never
   adds a second toolbar line.

   The iframe is same-origin, but all cross-document traffic goes through
   postMessage (see zenviz-bridge.js) so the contract stays explicit.
   ========================================================================== */

/* Picking a node is the request, so a load starts on its own — but not on every
   single tick: this is long enough to swallow a burst of checklist clicks and
   short enough to still feel like a direct response. */
var STUDIO_AUTO_LOAD_DELAY = 260;

var chartStudio = {
    _mounted: false,
    _ready: false,
    _hasSources: false,
    _lastPayloadKey: '',
    /* Pending auto-load (see scheduleAutoLoad) and the sequence number that
       tells a superseded response to stay off the screen. */
    _autoTimer: null,
    _loadSeq: 0,
    /* The wording a finished load should keep. The bridge echoes back "data
       applied" a moment later; without this the echo would flatten a merged
       load back into the single-source sentence. */
    _lastLoadNote: '',
    /* How several selected nodes are combined: 'rows' puts the next table under
       the first, 'side' puts it to the right. */
    _mergeMode: 'rows',
    /* Row count per node, from the last probe — used for the picker's tooltip. */
    _rowsById: {},

    /* Nav mirrored out of the studio (see _renderMenus) and the small amount of
       state its chips need to look right. */
    _menus: [],
    _menusKey: '',
    _openMenu: '',

    /* ── Lifecycle ───────────────────────────────────────────────────────── */

    open() {
        var overlay = document.getElementById('studio-overlay');
        overlay.classList.add('open');
        this._mount();
        /* Status first, then the probe: refreshSources() is async and owns the
           status line while it runs (it is what reports "nothing selectable"). */
        this._setStatus('');
        this.refreshSources();
        return this;
    },

    close() {
        document.getElementById('studio-overlay').classList.remove('open');
        /* Leaving a dropdown hanging over a closed overlay would strand it. */
        this._openMenu = '';
        this._post({ type: 'zenviz:closeMenu' });
        this._syncMenuState();
    },

    isOpen() {
        return document.getElementById('studio-overlay').classList.contains('open');
    },

    _mount() {
        if (this._mounted) return;
        var frame = document.getElementById('studio-frame');
        frame.src = '/zenviz.html?embed=1';
        this._mounted = true;
        this._setStatus(I18n.t('studio.booting'));

        frame.addEventListener('load', () => {
            document.getElementById('studio-loading').classList.add('hidden');
            /* Ask the bridge to confirm it is live (it may have missed our
               earlier messages while the document was still parsing). */
            this._post({ type: 'zenviz:ping' });
        });
    },

    _post(msg) {
        var frame = document.getElementById('studio-frame');
        if (!frame || !frame.contentWindow) return;
        frame.contentWindow.postMessage(msg, window.location.origin || '*');
    },

    _setStatus(text) {
        var el = document.getElementById('studio-status');
        if (el) el.textContent = text || '';
    },

    _busy(on) {
        this._syncButtons(!!on);
    },

    /* A busy request wins over "no data yet"; otherwise the buttons simply
       reflect whether there is anything on the canvas to pull from. */
    _syncButtons(busy) {
        ['studio-load', 'studio-save'].forEach((id) => {
            var b = document.getElementById(id);
            if (b) b.disabled = !!busy || !this._hasSources;
        });
    },

    /* ── Studio nav, re-hosted in the bar ─────────────────────────────────── */

    /* The studio carries its own top nav (engine / data / style / export).
       Embedded, that row is suppressed and mirrored here instead, so the bar
       stays one line. Its dropdowns still render inside the iframe — the bar
       sits directly above it, so iframe y=0 is the bar's bottom edge and a
       dropdown anchored there reads as hanging off the chip we clicked. */

    refreshMenus() {
        this._renderMenus();
    },

    _menuLabel(id, fallback) {
        var key = 'studio.menu.' + id;
        var text = I18n.t(key);
        return text === key ? fallback || id : text;
    },

    _renderMenus() {
        var host = document.getElementById('studio-menus');
        if (!host) return;
        host.innerHTML = '';
        /* Nothing to show until the studio has booted and named its menus —
           an empty container collapses (see .studio-menus:empty). */
        if (!this._menus.length) return;

        this._menus.forEach((m) => {
            var group = document.createElement('div');
            group.className = 'menu-group';

            var label = document.createElement('span');
            label.className = 'menu-label';
            label.textContent = this._menuLabel(m.id, m.label);

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'menu-btn';
            btn.dataset.menu = m.id;
            btn.textContent = this._menuLabel(m.id, m.label);
            btn.addEventListener('click', () => this.toggleMenu(m.id));

            group.appendChild(label);
            group.appendChild(btn);
            host.appendChild(group);
        });

        this._syncMenuState();
    },

    toggleMenu(id) {
        if (this._openMenu === id) {
            this._openMenu = '';
            this._post({ type: 'zenviz:closeMenu' });
            this._syncMenuState();
            return;
        }
        var frame = document.getElementById('studio-frame');
        var btn = document.querySelector('#studio-menus .menu-btn[data-menu="' + id + '"]');
        if (!frame || !btn) return;
        /* Only x has to travel — see the note above about y = 0. */
        var left = Math.round(
            btn.getBoundingClientRect().left - frame.getBoundingClientRect().left
        );
        this._openMenu = id;
        this._post({ type: 'zenviz:openMenu', menu: id, left: Math.max(0, left) });
        this._syncMenuState();
    },

    _syncMenuState() {
        document.querySelectorAll('#studio-menus .menu-btn').forEach((b) => {
            b.classList.toggle('active', b.dataset.menu === this._openMenu);
        });
    },

    /* ── Data source list ────────────────────────────────────────────────── */

    /* Every node is listed, but only the ones that can actually hand the studio
       a table right now are selectable. That judgement has two halves:
       _payloadFor() covers the static dead ends (a Visualize/Output node with
       nothing wired into it), while /api/studio/sources answers the runtime
       ones (has this node produced a result yet, is the uploaded dataset still
       around). Either way the reason travels with the row, so an unselectable
       node explains itself on hover and on click — instead of failing only
       after the user presses Load. */
    _candidateNodes() {
        return Object.keys(canvas.nodes).map((id) => {
            var payload = this._payloadFor(id);
            return {
                id: id,
                node: canvas.nodes[id],
                payload: payload,
                reason: payload ? '' : 'no_upstream',
            };
        });
    },

    /* Ask the server which candidates it can serve right now. Probing is an
       optimisation, not a gate: if the call itself fails we offer everything
       and let Load Data report the problem, so a broken endpoint can never
       lock the user out of their own data. */
    async _probeSources(items) {
        try {
            var resp = await fetch('/api/studio/sources', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    candidates: items.map((e) => ({ node_id: e.id, payload: e.payload })),
                }),
            });
            var result = await resp.json();
            if (result.ok && Array.isArray(result.sources)) return result.sources;
        } catch (e) {
            /* fall through to the pessimistic-but-permissive view below */
        }
        return items.map((e) => ({
            node_id: e.id,
            available: !!e.payload,
            rows: 0,
            reason: e.reason,
        }));
    },

    /* Server reason code → i18n key stem. Two forms: `short` fits inside the
       dropdown row, the full sentence goes in the tooltip, toast and status
       line. Unknown codes read as "no result yet", which is the commonest
       cause and the least misleading guess. */
    _reasonText(code, short) {
        var keys = {
            no_upstream: 'noUpstream',
            no_result: 'noResult',
            stale_dataset: 'staleDataset',
            empty: 'empty',
            error: 'probeFailed',
        };
        var stem = 'studio.src.' + (keys[code] || keys.no_result) + (short ? 'Short' : '');
        var text = I18n.t(stem);
        return text === stem ? code : text;
    },

    async refreshSources(selectedId) {
        var sel = document.getElementById('studio-source');
        if (!sel) return;

        var items = this._candidateNodes();
        if (!items.length) {
            this._renderNoSource(sel, I18n.t('studio.noNodes'));
            this._setStatus(I18n.t('studio.noNodes'));
            return;
        }

        /* A checklist, not a single choice: carry the whole selection across the
           rebuild instead of one value. */
        var previous = [].concat(selectedId || this._selectedNodeIds());
        var probed = await this._probeSources(items);
        var byId = {};
        this._rowsById = {};
        probed.forEach((p) => {
            byId[p.node_id] = p;
            if (p.available) this._rowsById[p.node_id] = p.rows || 0;
        });

        /* Both templates belong to the app, so the wording follows the language
           (custom-select.js only knows how to fill them in). */
        sel.dataset.multiLabel = I18n.t('studio.multiCount');
        sel.dataset.placeholder = I18n.t('studio.pickMulti');

        /* Build the whole list off to the side and swap it in one go. Emptying
           the control first would leave a window with zero options, and a click
           that landed inside it would find nothing to open (custom-select's
           open() bails on an empty list) — one more way a control could look
           like it needed two presses. */
        var available = 0;
        var firstAvailable = '';
        var picked = [];
        var built = [];
        items.forEach((entry) => {
            var p = byId[entry.id] || {};
            var code = p.reason || entry.reason;
            var o = document.createElement('option');
            o.value = entry.id;
            o.textContent = this._nodeLabel(entry.id, entry.node);
            if (p.available) {
                available++;
                if (!firstAvailable) firstAvailable = entry.id;
                if (previous.indexOf(entry.id) >= 0) picked.push(entry.id);
                /* The count sits in the row; the columns go in the tooltip, so
                   the user can tell what they are about to combine. */
                if (p.rows > 0) o.dataset.note = I18n.t('studio.src.rows').replace('{rows}', p.rows);
                o.title = this._sourceTip(p);
            } else {
                /* data-reason is the long form; data-note is the abbreviated
                   one the dropdown paints next to the label (custom-select.js). */
                o.disabled = true;
                o.dataset.reason = this._reasonText(code, false);
                o.dataset.note = this._reasonText(code, true);
                o.title = o.dataset.reason;
            }
            built.push(o);
        });

        if (!available) {
            /* Nothing selectable at all — one row saying so beats a list the
               user can only fail from. */
            this._renderNoSource(sel, I18n.t('studio.src.none'));
            this._setStatus(I18n.t('studio.src.none'));
            return;
        }

        sel.textContent = '';
        built.forEach((o) => sel.appendChild(o));
        this._setSourceEnabled(true);
        /* Keep the previous picks while they are still usable, otherwise land on
           the first node that is — never on a disabled row. */
        if (!picked.length) picked = [firstAvailable];
        Array.prototype.forEach.call(sel.options, (o) => {
            o.selected = picked.indexOf(o.value) >= 0;
        });
        this._updateSelectionUI();
    },

    _renderNoSource(sel, label) {
        sel.innerHTML = '';
        var opt = document.createElement('option');
        opt.value = '';
        opt.textContent = label;
        sel.appendChild(opt);
        this._setSourceEnabled(false);
        this._updateSelectionUI();
    },

    /* The trigger's look follows sel.disabled, which flips over the session —
       and the custom select caches that state, so nudge it. */
    _setSourceEnabled(on) {
        var sel = document.getElementById('studio-source');
        if (sel) sel.disabled = !on;
        this._hasSources = !!on;
        if (window.CustomSelect) CustomSelect.refreshAll();
        this._syncButtons(false);
    },

    /* ── Selection ───────────────────────────────────────────────────────── */

    /* The native options are the single source of truth, so the checkbox rows
       and the loader can never drift apart. */
    _selectedNodeIds() {
        var sel = document.getElementById('studio-source');
        if (!sel) return [];
        var ids = [];
        Array.prototype.forEach.call(sel.options, (o) => {
            if (o.selected && !o.disabled && o.value) ids.push(o.value);
        });
        return ids;
    },

    /* The merge control only means something once there are two tables to
       combine, and the picker's tooltip is where the running total lives. */
    _updateSelectionUI() {
        var ids = this._selectedNodeIds();
        var field = document.getElementById('studio-merge-field');
        if (field) field.hidden = ids.length < 2;
        var merge = document.getElementById('studio-merge');
        if (merge && merge.value !== this._mergeMode) merge.value = this._mergeMode;
        var sel = document.getElementById('studio-source');
        if (sel) {
            var total = 0;
            ids.forEach((id) => {
                total += this._rowsById[id] || 0;
            });
            sel.title = ids.length
                ? I18n.t('studio.src.selection').replace('{n}', ids.length).replace('{rows}', total)
                : '';
        }
        /* The trigger reports the count, and the selection is written
           programmatically — which the option-list observer cannot see. */
        if (window.CustomSelect) CustomSelect.refreshAll();
        this._syncButtons(false);
    },

    /* How several nodes' tables are laid out side by side: `rows` puts the next
       table under the first, `side` puts it to the right. Both just place whole
       tables — nothing is matched up by value. */
    setMergeMode(value) {
        this._mergeMode = value === 'side' ? 'side' : 'rows';
        return this._mergeMode;
    },

    /* What a servable node holds — enough to tell two nodes of the same type
       apart before combining them. */
    _sourceTip(p) {
        var cols = Array.isArray(p.cols) ? p.cols : [];
        var rows = I18n.t('studio.src.rows').replace('{rows}', p.rows);
        if (!cols.length) return rows;
        var shown = cols.slice(0, 6).join(' · ');
        if (cols.length > 6) shown += ' …';
        return I18n.t('studio.src.tip')
            .replace('{rows}', p.rows)
            .replace('{cols}', cols.length)
            .replace('{names}', shown);
    },

    /* "Merged 3 sources · 128 rows" — plus a warning when part of what was asked
       for could not be served, because a partial merge must not read complete. */
    _mergeNote(result, asked, cols) {
        var served = Array.isArray(result.sources) ? result.sources.filter((s) => s.ok).length : 0;
        var text = I18n.t('studio.loadedMerged')
            .replace('{n}', served)
            .replace('{rows}', result.total_rows)
            .replace('{cols}', cols);
        var missing = asked - served;
        if (missing > 0) text += ' · ' + I18n.t('studio.mergedSkipped').replace('{n}', missing);
        return text;
    },

    /* What the studio shows as the dataset's name. */
    _selectionLabel(ids) {
        if (ids.length > 3) return I18n.t('studio.mergedName').replace('{n}', ids.length);
        return ids
            .map((id) => this._nodeLabel(id, canvas.nodes[id]))
            .join(' + ');
    },

    /* Every node is its own entry. The node's own title is just its type's
       default label ("Visualize"), so two Visualize nodes would otherwise read
       identically — the number identifies it and the summary says what it does. */
    _DEFAULT_TITLES: {
        source: 'Data Source',
        upload: 'Upload File',
        process: 'Process',
        analysis: 'Analysis',
        visualize: 'Visualize',
        tokenize: 'Tokenize',
        output: 'Output',
    },

    _nodeSeq(id) {
        var m = String(id).match(/(\d+)\s*$/);
        return m ? m[1] : String(id);
    },

    _nodeLabel(id, node) {
        node = node || {};
        var type = node.type ? I18n.t('nodeType.' + node.type) : '';
        var parts = ['#' + this._nodeSeq(id)];
        var title = (node.title || '').trim();
        /* Only a name the user actually chose is worth showing. */
        if (title && title !== type && title !== this._DEFAULT_TITLES[node.type]) parts.push(title);
        if (type) parts.push(type);
        var detail = this._nodeDetail(node);
        if (detail) parts.push(detail);
        return parts.join(' · ');
    },

    /* The first line of the node's own summary is what distinguishes two nodes of
       the same type: chart type, operation, column… */
    _nodeDetail(node) {
        if (!node.type || !canvas.getNodeSummary) return '';
        var text = '';
        try {
            text = String(canvas.getNodeSummary(node.type, node.params || {}) || '');
        } catch (e) {
            return '';
        }
        text = text.split('\n')[0].trim();
        return text.length > 44 ? text.slice(0, 43) + '…' : text;
    },

    /* Build the same payload /api/data/preview understands, so the studio and
       the Data Preview panel always agree on what "this node's data" means. */
    _payloadFor(nodeId) {
        var node = canvas.nodes[nodeId];
        if (!node) return null;

        /* An Upload node carries its own file, so the studio can read it
           without the workflow having run. */
        if (node.type === 'upload') {
            return node.params && node.params.dataset_id ? { dataset_id: node.params.dataset_id } : null;
        }
        if (['source', 'process', 'analysis', 'tokenize'].indexOf(node.type) >= 0) {
            return { node_id: nodeId };
        }

        var upstream = canvas.getUpstreamNodeId(nodeId);
        if (!upstream) return null;
        return { node_id: upstream };
    },

    /* ── Hand a dataset to the studio ────────────────────────────────────── */

    async openForNode(nodeId) {
        this.open();
        /* Probe before loading: "open the studio on this node" is only
           meaningful once we know that node can actually be loaded. Opening on
           a node means *that* node alone, so it replaces any earlier picks. */
        await this.refreshSources([nodeId]);
        var sel = document.getElementById('studio-source');
        var target = sel
            ? Array.prototype.find.call(sel.options, (o) => o.value === nodeId)
            : null;
        if (target && !target.disabled) {
            this.loadSelected();
            return;
        }
        /* Not selectable — explain why and stay put rather than loading some
           other node's table behind the user's back. */
        var why = (target && target.dataset.reason) || I18n.t('studio.emptyData');
        this._setStatus(why);
        showToast(why);
    },

    /* ── Auto-load ───────────────────────────────────────────────────────── */

    /* Picking a node (or a merge mode) is the whole instruction — making the
       user press Load afterwards was busywork, and it read as "my change did
       nothing". Bursts are coalesced: ticking three nodes in a row fires one
       request, not three, and the picker stays clickable while it runs. */
    scheduleAutoLoad() {
        clearTimeout(this._autoTimer);
        var ids = this._selectedNodeIds();
        if (!ids.length) {
            /* An empty selection is a half-finished thought, not an error —
               stay quiet instead of shouting mid-click. */
            this._autoTimer = null;
            this._lastLoadNote = '';
            this._setStatus('');
            return;
        }
        /* Answer the click immediately, then do the work — otherwise a probe
           that takes a moment feels like nothing happened. */
        this._setStatus(I18n.t('studio.loading'));
        this._autoTimer = setTimeout(() => {
            this._autoTimer = null;
            this.loadSelected();
        }, STUDIO_AUTO_LOAD_DELAY);
    },

    async loadSelected() {
        /* An explicit press supersedes whatever the picker had queued. */
        clearTimeout(this._autoTimer);
        this._autoTimer = null;
        var ids = this._selectedNodeIds();
        if (!ids.length) {
            this._setStatus(I18n.t('studio.pickSource'));
            showToast(I18n.t('studio.pickSource'));
            return;
        }
        /* The picker disables rows it knows are unusable, so this is belt and
           braces — but a probe that went stale (the node has not been run yet,
           or the reverse: it just finished) must not slip through silently. */
        var blocked = '';
        var sel = document.getElementById('studio-source');
        if (sel) {
            Array.prototype.forEach.call(sel.options, (o) => {
                if (!blocked && o.selected && o.disabled) {
                    blocked = o.dataset.reason || I18n.t('studio.emptyData');
                }
            });
        }
        if (blocked) {
            this._setStatus(blocked);
            showToast(blocked);
            return;
        }

        var payloads = [];
        ids.forEach((id) => {
            var payload = this._payloadFor(id);
            if (payload) payloads.push({ id: id, payload: payload });
        });
        if (!payloads.length) {
            this._setStatus(I18n.t('studio.emptyData'));
            return;
        }

        this._lastLoadNote = '';
        this._busy(true);
        this._setStatus(I18n.t('studio.loading'));
        /* Ticking a fourth node while the third request is still in flight is
           normal now that changes load by themselves — stamp each request so a
           slow answer cannot overwrite a newer one. */
        var seq = (this._loadSeq = this._loadSeq + 1);
        try {
            /* One node keeps the plain request (and with it the "that node has
               nothing yet, use this one" fallback); several are merged
               server-side into a single table. */
            var body;
            if (payloads.length === 1) {
                body = Object.assign({}, payloads[0].payload, { limit: 5000 });
            } else {
                body = {
                    sources: payloads.map((e) => e.payload),
                    merge: this._mergeMode,
                    limit: 5000,
                };
            }

            var resp = await fetch('/api/studio/dataset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            var result = await resp.json();
            if (seq !== this._loadSeq) return;
            if (!result.ok) {
                /* Known dead-end: the nodes simply haven't produced a result yet
                   (first run, or the server was restarted and results — which
                   live in memory — were wiped). Say so plainly instead of
                   surfacing the raw backend exception. */
                if (result.code === 'no_result') throw new Error(I18n.t('studio.noResult'));
                throw new Error(result.error || 'request failed');
            }
            if (!result.columns || !result.columns.length) throw new Error('empty dataset');

            if (!this._ready) {
                /* The bridge announces itself on load; nudge it in case the
                   overlay was opened before the iframe finished booting. */
                this._post({ type: 'zenviz:ping' });
            }
            this._post({
                type: 'zenviz:setData',
                headers: result.columns,
                rows: result.rows,
                name: this._selectionLabel(payloads.map((e) => e.id)),
            });
            this._lastPayloadKey = payloads.map((e) => e.id).join('|');

            if (result.fallback && result.fallback.used) {
                var asked = this._nodeLabel(
                    result.fallback.requested,
                    canvas.nodes[result.fallback.requested]
                );
                var used = this._nodeLabel(result.fallback.used, canvas.nodes[result.fallback.used]);
                this._setStatus(I18n.t('studio.fallback').replace('{a}', asked).replace('{b}', used));
                /* Keep the selector honest about where the data came from. */
                this.refreshSources(result.fallback.used);
            } else if (payloads.length > 1) {
                this._lastLoadNote = this._mergeNote(result, ids.length, result.columns.length);
                this._setStatus(this._lastLoadNote);
                /* A partial merge is the one case worth interrupting for. */
                if (result.sources && result.sources.some((s) => !s.ok)) showToast(this._lastLoadNote);
            } else {
                this._lastLoadNote = I18n.t('studio.loaded')
                    .replace('{rows}', result.total_rows)
                    .replace('{cols}', result.columns.length);
                this._setStatus(this._lastLoadNote);
            }
        } catch (e) {
            /* A superseded request must not paint its failure over the newer
               one's result either. */
            if (seq !== this._loadSeq) return;
            var msg = e && e.message ? e.message : String(e);
            /* The no-result message is already written for humans. */
            this._setStatus(
                msg === I18n.t('studio.noResult') ? msg : I18n.t('studio.loadFailed') + ': ' + msg
            );
        } finally {
            if (seq === this._loadSeq) this._busy(false);
        }
    },

    /* ── Pull the rendered chart back out ────────────────────────────────── */

    saveBack() {
        this._busy(true);
        this._setStatus('…');
        this._post({ type: 'zenviz:snapshot', name: 'studio-chart' });
        /* Un-busy happens on the bridge's reply (see handleMessage). */
    },

    async _persistSnapshot(dataUrl, name) {
        try {
            var resp = await fetch('/api/studio/save-image', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: dataUrl, name: name || 'studio-chart' }),
            });
            var result = await resp.json();
            if (!result.ok) throw new Error(result.error || 'request failed');
            this._setStatus(I18n.t('studio.saved').replace('{path}', result.filename));
            showToast(I18n.t('studio.saved').replace('{path}', result.filename));
        } catch (e) {
            this._setStatus(I18n.t('studio.saveFailed') + ': ' + e.message);
        } finally {
            this._busy(false);
        }
    },

    /* ── Bridge replies ──────────────────────────────────────────────────── */

    handleMessage(evt) {
        if (!evt || !evt.data || evt.data.source !== 'zenviz-bridge') return;
        var msg = evt.data;

        if (msg.type === 'zenviz:ready') {
            this._ready = true;
            document.getElementById('studio-loading').classList.add('hidden');
            if (!this._lastPayloadKey) this._setStatus(I18n.t('studio.ready'));
            /* The studio only knows its own nav once it has booted. */
            var menus = Array.isArray(msg.menus) ? msg.menus : [];
            var key = menus.map((m) => m.id + ':' + (m.label || '')).join('|');
            if (key && key !== this._menusKey) {
                this._menus = menus;
                this._menusKey = key;
                this._renderMenus();
            }
            this._syncMenuState();
            return;
        }

        /* The studio owns dropdown lifetime (clicking the chart closes one), so
           it is the authority on which chip should look active. */
        if (msg.type === 'zenviz:menuState') {
            this._openMenu = msg.menu || '';
            this._syncMenuState();
            return;
        }

        if (msg.type === 'zenviz:dataApplied') {
            /* Echo of a load we have already described — a merged load keeps its
               own wording instead of being flattened to the single-source one. */
            this._setStatus(
                this._lastLoadNote ||
                    I18n.t('studio.loaded').replace('{rows}', msg.rows).replace('{cols}', msg.cols)
            );
            return;
        }

        if (msg.type === 'zenviz:snapshot') {
            this._persistSnapshot(msg.dataUrl, msg.name);
            return;
        }

        if (msg.type === 'zenviz:error') {
            this._busy(false);
            if (msg.stage === 'snapshot') {
                this._setStatus(I18n.t('studio.noChart'));
            } else {
                this._setStatus(I18n.t('studio.loadFailed') + ': ' + msg.error);
            }
        }
    },
};

window.addEventListener('message', function (evt) {
    chartStudio.handleMessage(evt);
});

/* Keep the source list in sync as nodes are added/removed/renamed, and wire the
   bar. Only a real change event reaches here — refreshSources() writes the
   selection programmatically, so it can never trigger a load on its own. */
document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('studio-overlay')) return;
    chartStudio.refreshSources();
    var sel = document.getElementById('studio-source');
    if (sel) {
        sel.addEventListener('change', () => {
            chartStudio._updateSelectionUI();
            /* Choosing a node IS the request — no second press needed. */
            chartStudio.scheduleAutoLoad();
        });
    }
    var merge = document.getElementById('studio-merge');
    if (merge) {
        merge.addEventListener('change', () => {
            chartStudio.setMergeMode(merge.value);
            /* Changing how they combine means re-combining them. */
            chartStudio.scheduleAutoLoad();
        });
    }
});

/* A row the picker knows is unusable does not change the selection — the
   custom select reports the blocked row here instead. The reason is exactly
   what the user needs, since it says what to run or wire up first. */
document.addEventListener('cselect-blocked', function (e) {
    if (!e.target || e.target.id !== 'studio-source') return;
    var reason = (e.detail && e.detail.reason) || I18n.t('studio.src.none');
    chartStudio._setStatus(reason);
    showToast(reason);
});

/* ESC closes the studio, matching the other overlay panels. */
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && chartStudio.isOpen()) chartStudio.close();
});

/* The studio closes its own dropdown when you click its chart, but it cannot
   see clicks that land on our bar — so mirror that rule here. */
document.addEventListener('click', function (e) {
    if (!chartStudio._openMenu) return;
    if (e.target && e.target.closest && e.target.closest('#studio-menus')) return;
    chartStudio.toggleMenu(chartStudio._openMenu);
});
