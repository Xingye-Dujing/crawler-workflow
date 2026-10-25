/* Reusable nodes: a saved subgraph, shown as one canvas node.
 *
 * A reusable node is deliberately ONE top-level node. Its inside (the template's nodes
 * and wires) is rendered as a read-only stage inside the group's own box, never as
 * extra entries in ``canvas.nodes``. That choice is what keeps the rest of the canvas
 * honest: auto-layout sees one measured block, connections only ever touch the group's
 * ports, undo/history serialize the group once, and an inside node can never be dragged
 * somewhere that makes it look like a top-level node the user did not add.
 *
 * What a run receives is a different graph: the file keeps the group, and Run expands it
 * into namespaced child nodes (``<groupId>__<innerId>``) with the external wires rewired
 * to the template's ordered input slots and its single output. The engine is unchanged.
 *
 * All inside nodes are read-only here. A template is created from a selection (its
 * arranged positions and measured sizes are stored), and changing a template means
 * creating a new one — a visible, deliberate action rather than silently editing every
 * instance that shares it.
 */
var REUSABLE_ALLOWED_TYPES = ['process', 'analysis', 'visualize', 'tokenize', 'biblio', 'fuse', 'output', 'compile'];
var REUSABLE_STAGE_MAX_W = 760;
var REUSABLE_STAGE_MAX_H = 520;
var REUSABLE_PREVIEW_MAX_W = 1080;
var REUSABLE_PREVIEW_MAX_H = 660;

var ReusableNodes = {
    _previewGroup: null,
    _wired: false,

    /* ── selection → template ─────────────────────────────────────── */

    _titleOf(node) {
        if (!node) return '';
        return String(node.title || '').trim() || I18n.t('node.' + node.type);
    },

    _statusWord(status) {
        var known = ['pending', 'running', 'done', 'partial', 'failed', 'skipped', 'restored'];
        return known.indexOf(status) >= 0 ? I18n.t('runsMgr.node.' + status) : String(status || '');
    },

    _statusOf(groupId, innerId) {
        var map = (typeof runResults !== 'undefined' && runResults.statuses) || {};
        return map[this.innerId(groupId, innerId)] || map[innerId] || null;
    },

    innerId(groupId, innerId) {
        /* ``__`` stays inside the id shape addNode/resume records accept; ':' does not. */
        return String(groupId) + '__' + String(innerId);
    },

    _selectionInfo(ids) {
        var selected = (ids || []).filter(function (id) { return canvas.nodes[id]; });
        if (!selected.length) return { error: I18n.t('reusable.noSelection') };
        var set = {};
        selected.forEach(function (id) { set[id] = true; });
        for (var i = 0; i < selected.length; i += 1) {
            var node = canvas.nodes[selected[i]];
            if (node.type === 'reusable' || REUSABLE_ALLOWED_TYPES.indexOf(node.type) < 0) {
                return {
                    error: I18n.t('reusable.badSelectionType', {
                        type: I18n.t('node.' + node.type) || node.type,
                    }),
                };
            }
        }
        var internal = canvas.connections.filter(function (c) { return set[c.from] && set[c.to]; });
        var incoming = canvas.connections.filter(function (c) { return !set[c.from] && set[c.to]; });
        var outgoing = canvas.connections.filter(function (c) { return set[c.from] && !set[c.to]; });

        var bySource = {};
        for (var j = 0; j < incoming.length; j += 1) {
            var source = incoming[j].from;
            if (bySource[source] === undefined) bySource[source] = [];
            bySource[source].push(incoming[j].to);
        }
        var sources = Object.keys(bySource);
        for (var k = 0; k < sources.length; k += 1) {
            if (bySource[sources[k]].length > 1) {
                return {
                    error: I18n.t('reusable.sameSource', {
                        name: this._titleOf(canvas.nodes[sources[k]]) || sources[k],
                    }),
                };
            }
        }
        var targets = {};
        for (var m = 0; m < incoming.length; m += 1) {
            var target = incoming[m].to;
            if (targets[target]) {
                return {
                    error: I18n.t('reusable.sameTarget', {
                        name: this._titleOf(canvas.nodes[target]) || target,
                    }),
                };
            }
            targets[target] = true;
        }
        var terminals = selected.filter(function (id) {
            return !internal.some(function (c) { return c.from === id; });
        });
        if (terminals.length !== 1) {
            return { error: I18n.t('reusable.multiOutput', { n: terminals.length }) };
        }
        var inputs = incoming.map(function (c) { return c.to; });
        var x = Infinity;
        var y = Infinity;
        selected.forEach(function (id) {
            var el = canvas._nodeEl(id);
            var px = el ? parseInt(el.style.left, 10) : 0;
            var py = el ? parseInt(el.style.top, 10) : 0;
            if (Number.isFinite(px) && px < x) x = px;
            if (Number.isFinite(py) && py < y) y = py;
        });
        var self = this;
        var nodes = selected.map(function (id) {
            var node = canvas.nodes[id];
            var el = canvas._nodeEl(id);
            var px = el ? parseInt(el.style.left, 10) : 0;
            var py = el ? parseInt(el.style.top, 10) : 0;
            return {
                id: id,
                type: node.type,
                title: node.title || '',
                params: JSON.parse(JSON.stringify(node.params || {})),
                x: (Number.isFinite(px) ? px : 0) - x,
                y: (Number.isFinite(py) ? py : 0) - y,
                w: (el && el.offsetWidth) || 220,
                h: (el && el.offsetHeight) || 80,
            };
        });
        return {
            ids: selected,
            nodes: nodes,
            connections: internal.map(function (c) { return { from: c.from, to: c.to }; }),
            inputs: inputs,
            outputs: [terminals[0]],
            x: x === Infinity ? 100 : x,
            y: y === Infinity ? 100 : y,
        };
    },

    async createFromSelection(ids) {
        var chosen = (Array.isArray(ids) && ids.length)
            ? ids.slice()
            : ((canvas.selectedNodes && canvas.selectedNodes.length)
                ? canvas.selectedNodes.slice()
                : (canvas.selectedNode ? [canvas.selectedNode] : []));
        var info = this._selectionInfo(chosen);
        if (info.error) {
            showToast(info.error);
            return;
        }
        var answer = await showDialog({
            message: I18n.t('reusable.createPrompt'),
            input: { value: '', placeholder: I18n.t('reusable.createPlaceholder') },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('ctx.createReusable'), primary: true },
            ],
        });
        if (answer === null) return;
        var name = String(answer || '').trim();
        if (!name) {
            showToast(I18n.t('reusable.groupNameRequired'));
            return;
        }
        var result = await fetchJSON('/api/reusable/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Lang': I18n.lang || 'zh' },
            body: JSON.stringify({
                name: name,
                description: '',
                nodes: info.nodes,
                connections: info.connections,
                inputs: info.inputs,
                outputs: info.outputs,
            }),
        });
        if (!result || !result.ok || !result.template) {
            showToast((result && result.error) || I18n.t('reusable.createFailed'));
            return;
        }
        this._wrap(info, result.template);
    },

    _wrap(info, template) {
        var self = this;
        canvas.batchHistory(function () {
            var original = canvas.connections.slice();
            var selected = {};
            info.ids.forEach(function (id) { selected[id] = true; });
            info.ids.forEach(function (id) {
                var el = canvas._nodeEl(id);
                if (el) el.remove();
                delete canvas.nodes[id];
            });
            var groupId = canvas.addNode('reusable', info.x, info.y);
            var group = canvas.nodes[groupId];
            group.title = template.name;
            group.params = {
                template_id: template.id,
                template_name: template.name,
                description: template.description || '',
                template: {
                    nodes: template.nodes || [],
                    connections: template.connections || [],
                    inputs: template.inputs || [],
                    outputs: template.outputs || [],
                },
                collapsed: true,
            };
            var titleEl = group.el.querySelector('.node-title');
            if (titleEl) titleEl.textContent = template.name;
            canvas.updateNodeDisplay(groupId);
            var next = [];
            var seenOut = {};
            original.forEach(function (c) {
                var fromIn = !!selected[c.from];
                var toIn = !!selected[c.to];
                if (fromIn && toIn) return;
                if (!fromIn && toIn) {
                    next.push({ from: c.from, to: groupId });
                    return;
                }
                if (fromIn && !toIn) {
                    /* One group output is the template's single terminal, so several
                       selected nodes feeding the same target collapse into one wire. */
                    if (seenOut[c.to]) return;
                    seenOut[c.to] = true;
                    next.push({ from: groupId, to: c.to });
                    return;
                }
                next.push({ from: c.from, to: c.to });
            });
            canvas.connections = next;
            canvas.setSelectedNodes([groupId]);
            canvas.updateConnections();
            canvas.scheduleRender();
            canvas.applyDisabledVisuals();
            canvas.saveState();
        });
        showToast(I18n.t('reusable.created'));
    },

    /* ── insert a saved template ──────────────────────────────────── */

    _insertPos() {
        if (canvas._contextMenuPos) {
            return canvas._screenToCanvas(canvas._contextMenuPos.x - 110, canvas._contextMenuPos.y - 40);
        }
        var ws = canvas.workspace || {};
        if (ws.clientWidth && ws.clientHeight && canvas._screenToCanvas) {
            return canvas._screenToCanvas(ws.clientWidth / 2 - 120, ws.clientHeight / 2 - 80);
        }
        return { x: 160, y: 120 };
    },

    async pickAndInsert() {
        var result = await fetchJSON('/api/reusable');
        if (!result || !result.ok) {
            showToast((result && result.error) || I18n.t('reusable.loadFailed'));
            return;
        }
        var rows = (result.templates || []).filter(function (row) { return !row.broken; });
        if (!rows.length) {
            showToast(I18n.t('reusable.none'));
            return;
        }
        var labels = rows.map(function (row) {
            return row.name + ' · ' + I18n.t('reusable.nodeCount', { n: row.nodes || 0 });
        });
        var chosen = await showDialog({
            message: I18n.t('reusable.pick'),
            list: labels,
            buttons: [{ label: I18n.t('dialog.cancel'), value: null }],
        });
        if (!chosen) return;
        var index = labels.indexOf(chosen);
        if (index < 0) return;
        var full = await fetchJSON('/api/reusable/get?id=' + encodeURIComponent(rows[index].id));
        if (!full || !full.ok || !full.template) {
            showToast((full && full.error) || I18n.t('reusable.insertFailed'));
            return;
        }
        var pos = this._insertPos();
        this._insert(full.template, pos.x, pos.y);
    },

    _insert(template, x, y) {
        canvas.batchHistory(function () {
            var id = canvas.addNode('reusable', x, y);
            var group = canvas.nodes[id];
            group.title = template.name;
            group.params = {
                template_id: template.id,
                template_name: template.name,
                description: template.description || '',
                template: {
                    nodes: template.nodes || [],
                    connections: template.connections || [],
                    inputs: template.inputs || [],
                    outputs: template.outputs || [],
                },
                collapsed: true,
            };
            var titleEl = group.el.querySelector('.node-title');
            if (titleEl) titleEl.textContent = template.name;
            canvas.updateNodeDisplay(id);
            canvas.setSelectedNodes([id]);
            canvas.scheduleRender();
        });
        showToast(I18n.t('reusable.inserted'));
    },

    /* ── the group's header controls and inside stage ─────────────── */

    decorate(id) {
        var self = this;
        var node = canvas.nodes[id];
        var el = canvas._nodeEl(id);
        if (!node || !el || node.type !== 'reusable') return;
        el.classList.add('node-reusable');
        var actions = el.querySelector('.node-actions');
        if (actions && !actions.querySelector('.node-reusable-toggle')) {
            /* The minimal DOM stub has no insertBefore; a real browser gets the two
               group controls FIRST (they are the node's primary verbs), the stub gets
               them appended and still exercises the same handlers. */
            var place = function (button, before) {
                if (typeof actions.insertBefore === 'function') actions.insertBefore(button, before);
                else actions.appendChild(button);
            };
            var toggle = document.createElement('button');
            toggle.type = 'button';
            toggle.className = 'node-ru-btn node-reusable-toggle';
            toggle.addEventListener('click', function (e) {
                e.stopPropagation();
                self.toggle(id);
            });
            place(toggle, actions.firstChild);
            var preview = document.createElement('button');
            preview.type = 'button';
            preview.className = 'node-ru-btn node-reusable-preview';
            preview.innerHTML =
                '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.6 8s2.3-4.1 6.4-4.1S14.4 8 14.4 8s-2.3 4.1-6.4 4.1S1.6 8 1.6 8z"/><circle cx="8" cy="8" r="2"/></svg>';
            preview.title = I18n.t('reusable.preview');
            preview.addEventListener('click', function (e) {
                e.stopPropagation();
                self.preview(id);
            });
            place(preview, toggle.nextSibling);
        }
        var content = el.querySelector('.node-content');
        if (content && !content.dataset.reusableWired) {
            content.dataset.reusableWired = '1';
            content.addEventListener('dblclick', function (e) {
                e.stopPropagation();
                self.preview(id);
            });
        }
        this._paintToggle(el, node.params || {});
        this.renderStage(id);
    },

    _paintToggle(el, params) {
        var btn = el.querySelector('.node-reusable-toggle');
        if (!btn) return;
        var expanded = params.collapsed === false;
        btn.textContent = expanded ? '▾' : '▸';
        btn.title = I18n.t(expanded ? 'reusable.collapse' : 'reusable.expand');
    },

    toggle(id) {
        var node = canvas.nodes[id];
        if (!node || node.type !== 'reusable') return;
        var wasCollapsed = (node.params || {}).collapsed !== false;
        node.params = node.params || {};
        node.params.collapsed = !wasCollapsed;
        canvas.updateNodeDisplay(id);
        canvas.applyDisabledVisuals();
        canvas.saveState();
        if (node.params.collapsed === false && this.autoLayoutOnExpand()) {
            /* One explicit reflow after the block grows; the preference lives in the
               Style menu and can be switched off for a stable canvas. */
            canvas.runAutoLayout();
        }
    },

    autoLayoutOnExpand() {
        var box = document.getElementById('reusable-auto-layout');
        return box ? box.checked !== false : true;
    },

    setAutoLayoutOnExpand(value) {
        var box = document.getElementById('reusable-auto-layout');
        if (box) box.checked = value !== false;
        if (typeof Settings !== 'undefined') {
            try {
                Settings.save();
            } catch (e) {
                /* A private-mode browser refusing localStorage is not a reason to break the toggle. */
            }
        }
    },

    renderStage(id, repaint) {
        var node = canvas.nodes[id];
        var el = canvas._nodeEl(id);
        if (!node || !el || node.type !== 'reusable') return;
        var params = node.params || {};
        this._paintToggle(el, params);
        var old = el.querySelector('.node-reusable-stage');
        if (old) old.remove();
        if (params.collapsed !== false) {
            el.classList.remove('node-reusable-expanded');
            el.classList.remove('node-folded');
            el.style.width = '';
        } else {
            el.classList.remove('node-folded');
            var built = this._stageHtml(id, params.template || {}, {
                maxW: REUSABLE_STAGE_MAX_W,
                maxH: REUSABLE_STAGE_MAX_H,
            });
            var content = el.querySelector('.node-content');
            if (!content) return;
            var stage = document.createElement('div');
            stage.className = 'node-reusable-stage';
            stage.innerHTML = built.html;
            content.appendChild(stage);
            el.classList.add('node-reusable-expanded');
            el.style.width = (built.width + 28) + 'px';
        }
        if (repaint !== false) {
            canvas.updateConnections();
            canvas.scheduleRender();
        }
    },

    _stageHtml(groupId, template, opts) {
        var self = this;
        var nodes = Array.isArray(template.nodes) ? template.nodes : [];
        var connections = Array.isArray(template.connections) ? template.connections : [];
        var inputs = Array.isArray(template.inputs) ? template.inputs : [];
        var outputs = Array.isArray(template.outputs) ? template.outputs : [];
        if (!nodes.length) {
            return {
                html: '<div class="reusable-stage-empty">' + escapeHtml(I18n.t('reusable.emptyTemplate')) + '</div>',
                width: 240,
                height: 90,
            };
        }
        var pad = 16;
        var minX = Infinity;
        var minY = Infinity;
        var maxX = -Infinity;
        var maxY = -Infinity;
        nodes.forEach(function (n) {
            var x = Number(n.x) || 0;
            var y = Number(n.y) || 0;
            var w = Number(n.w) || 220;
            var h = Number(n.h) || 90;
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x + w > maxX) maxX = x + w;
            if (y + h > maxY) maxY = y + h;
        });
        var naturalW = Math.max(240, maxX - minX + pad * 2);
        var naturalH = Math.max(120, maxY - minY + pad * 2);
        var maxW = opts.maxW || REUSABLE_STAGE_MAX_W;
        var maxH = opts.maxH || REUSABLE_STAGE_MAX_H;
        var scale = Math.min(1, maxW / naturalW, maxH / naturalH);
        var width = Math.round(naturalW * scale);
        var height = Math.round(naturalH * scale);
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        var lines = connections.map(function (c) {
            var a = byId[c.from];
            var b = byId[c.to];
            if (!a || !b) return '';
            var x1 = ((Number(a.x) || 0) - minX + pad + (Number(a.w) || 220)) * scale;
            var y1 = ((Number(a.y) || 0) - minY + pad + (Number(a.h) || 90) / 2) * scale;
            var x2 = ((Number(b.x) || 0) - minX + pad) * scale;
            var y2 = ((Number(b.y) || 0) - minY + pad + (Number(b.h) || 90) / 2) * scale;
            var bend = Math.max(20, Math.abs(x2 - x1) * 0.45);
            return (
                '<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) +
                ' C ' + (x1 + bend).toFixed(1) + ' ' + y1.toFixed(1) +
                ', ' + (x2 - bend).toFixed(1) + ' ' + y2.toFixed(1) +
                ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + '"/>'
            );
        }).join('');
        var compact = scale < 0.62 ? ' compact' : '';
        var cards = nodes.map(function (n) {
            var x = (Number(n.x) - minX + pad) * scale;
            var y = (Number(n.y) - minY + pad) * scale;
            var w = (Number(n.w) || 220) * scale;
            var h = (Number(n.h) || 90) * scale;
            var status = self._statusOf(groupId, n.id);
            var statusWord = status && status.status ? self._statusWord(status.status) : '';
            var statusClass = status && status.status ? self._statusClass(status.status) : '';
            var slot = inputs.indexOf(n.id);
            var slots =
                (slot >= 0 ? '<span class="rin-slot">IN ' + (slot + 1) + '</span>' : '') +
                (outputs[0] === n.id ? '<span class="rin-slot rin-out">OUT</span>' : '');
            var summary = canvas.getNodeSummary(n.type, n.params || {});
            var title = self._titleOf(n);
            var tip = title + (summary ? '\n' + summary : '') + (statusWord ? '\n' + statusWord : '');
            return (
                '<div class="reusable-inner-node" data-inner-id="' + escapeHtml(n.id) + '"' +
                ' style="left:' + x.toFixed(1) + 'px;top:' + y.toFixed(1) + 'px;' +
                'width:' + Math.max(70, w).toFixed(1) + 'px;height:' + Math.max(40, h).toFixed(1) + 'px"' +
                ' title="' + escapeHtml(tip) + '">' +
                '<div class="rin-head">' +
                '<span class="rin-type">' + escapeHtml(nodeTypeWord(n.type)) + '</span>' +
                '<span class="rin-title">' + escapeHtml(title) + '</span>' +
                slots +
                (statusClass ? '<span class="rin-status st-' + statusClass + '" title="' + escapeHtml(statusWord) + '"></span>' : '') +
                '</div>' +
                '<div class="rin-body">' + escapeHtml(summary) + '</div>' +
                '</div>'
            );
        }).join('');
        return {
            html: (
                '<div class="reusable-stage' + compact + '" style="width:' + width + 'px;height:' + height + 'px">' +
                '<svg class="reusable-stage-lines" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" aria-hidden="true">' +
                lines +
                '</svg>' +
                cards +
                '</div>'
            ),
            width: width,
            height: height,
        };
    },

    _statusClass(status) {
        if (status === 'done' || status === 'restored' || status === 'skipped') return 'done';
        if (status === 'running') return 'running';
        if (status === 'pending') return 'pending';
        if (status === 'partial') return 'partial';
        if (status === 'failed') return 'failed';
        return 'unknown';
    },

    aggregate(groupId, map) {
        var self = this;
        var node = canvas.nodes[groupId];
        var template = (node && node.params && node.params.template) || {};
        var nodes = Array.isArray(template.nodes) ? template.nodes : [];
        var infos = nodes
            .map(function (n) {
                var info = map[self.innerId(groupId, n.id)] || map[n.id];
                return info || null;
            })
            .filter(Boolean);
        if (!infos.length) return null;
        var statuses = infos.map(function (info) { return String(info.status || ''); });
        var unknown = statuses.filter(function (status) {
            return ['pending', 'running', 'done', 'partial', 'failed', 'skipped', 'restored'].indexOf(status) < 0;
        })[0];
        var status = 'pending';
        if (statuses.indexOf('running') >= 0) status = 'running';
        else if (statuses.indexOf('failed') >= 0) status = 'failed';
        else if (statuses.indexOf('partial') >= 0) status = 'partial';
        else if (unknown) status = unknown;
        else if (statuses.every(function (s) { return s === 'done' || s === 'restored' || s === 'skipped'; })) status = 'done';
        var rows = infos.reduce(function (sum, info) { return sum + (Number(info.row_count) || 0); }, 0);
        return {
            status: status,
            rows: rows,
            total: infos.length,
            settled: statuses.filter(function (s) { return s === 'done' || s === 'restored' || s === 'skipped'; }).length,
        };
    },

    paintStatuses(map) {
        var self = this;
        var painted = false;
        Object.keys(canvas.nodes).forEach(function (id) {
            var node = canvas.nodes[id];
            if (!node || node.type !== 'reusable') return;
            var el = canvas._nodeEl(id);
            if (!el) return;
            painted = true;
            var badge = el.querySelector('.node-run-badge');
            var agg = self.aggregate(id, map || {});
            if (badge) {
                canvas._paintRunBadge(badge, agg ? agg.status : '', agg ? agg.rows : 0);
            }
            if (node.params && node.params.collapsed === false) self.renderStage(id, false);
        });
        /* No reusable node → no geometry changed, so a one-second status poll must not
           repaint every wire on the canvas. */
        if (painted) canvas.updateConnections();
        this.repaintPreview();
    },

    /* ── settings panel and inside preview ───────────────────────── */

    settingsHtml(nodeId) {
        var node = canvas.nodes[nodeId];
        if (!node) return '';
        var p = node.params || {};
        var template = p.template || {};
        var nodes = Array.isArray(template.nodes) ? template.nodes : [];
        var inputs = Array.isArray(template.inputs) ? template.inputs : [];
        var outputs = Array.isArray(template.outputs) ? template.outputs : [];
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        var wired = canvas.connections.filter(function (c) { return c.to === nodeId; }).length;
        var name = String(p.template_name || '').trim() || I18n.t('reusable.untitled');
        var output = byId[outputs[0]];
        var slotRows = inputs.map(function (id, index) {
            var inner = byId[id];
            return (
                '<div class="reusable-slot-row">' +
                '<span class="reusable-slot-index">' + (index + 1) + '</span>' +
                '<span>' + escapeHtml(inner ? this._titleOf(inner) : id) + '</span>' +
                '</div>'
            );
        }, this).join('');
        var toggleLabel = I18n.t(p.collapsed === false ? 'reusable.collapse' : 'reusable.expand');
        var idArg = attrJsArg(nodeId);
        return (
            '<div class="settings-group">' +
            '<label class="settings-label">' + I18n.t('node.reusable') + '</label>' +
            '<div class="reusable-settings-name">' + escapeHtml(name) + '</div>' +
            (p.description ? '<div class="settings-hint">' + escapeHtml(p.description) + '</div>' : '') +
            '<div class="settings-hint">' +
            I18n.t('reusable.nodeCount', { n: nodes.length }) + ' · ' +
            I18n.t('reusable.connectionCount', { n: (template.connections || []).length }) +
            '</div>' +
            '</div>' +
            '<div class="settings-group">' +
            '<label class="settings-label">' + I18n.t('reusable.inputsTitle') + '</label>' +
            (slotRows || '<div class="settings-hint">' + I18n.t('reusable.noInputs') + '</div>') +
            '<div class="settings-hint">' + I18n.t('reusable.inputsWired', { wired: wired, n: inputs.length }) + '</div>' +            '</div>' +
            '<div class="settings-group">' +
            '<label class="settings-label">' + I18n.t('reusable.outputTitle') + '</label>' +
            '<div class="reusable-settings-name">' +
            escapeHtml(output ? this._titleOf(output) : '—') +
            '</div></div>' +
            '<div class="settings-group upload-actions">' +
            '<button class="menu-btn" type="button" onclick="ReusableNodes.toggle(\'' + idArg + '\')">' +
            toggleLabel + '</button>' +
            '<button class="menu-btn" type="button" onclick="ReusableNodes.preview(\'' + idArg + '\')">' +
            I18n.t('reusable.preview') + '</button>' +
            '</div>' +
            '<div class="settings-hint">' + I18n.t('reusable.readOnly') + '</div>'
        );
    },

    preview(id) {
        var node = canvas.nodes[id];
        if (!node || node.type !== 'reusable') return;
        var overlay = document.getElementById('reusable-preview-overlay');
        if (!overlay) return;
        if (!this._wired) {
            this._wired = true;
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) ReusableNodes.closePreview();
            });
        }
        this._previewGroup = id;
        overlay.classList.add('open');
        this._paintPreview();
    },

    closePreview() {
        this._previewGroup = null;
        var overlay = document.getElementById('reusable-preview-overlay');
        if (overlay) overlay.classList.remove('open');
    },

    repaintPreview() {
        if (this._previewGroup) this._paintPreview();
    },

    _paintPreview() {
        var groupId = this._previewGroup;
        var node = groupId && canvas.nodes[groupId];
        if (!node || node.type !== 'reusable') return;
        var p = node.params || {};
        var template = p.template || {};
        var name = String(p.template_name || '').trim() || node.title || I18n.t('reusable.untitled');
        var title = document.getElementById('reusable-preview-title');
        if (title) title.textContent = I18n.t('reusable.previewTitle', { name: name });
        var meta = document.getElementById('reusable-preview-meta');
        var nodes = Array.isArray(template.nodes) ? template.nodes : [];
        var inputs = Array.isArray(template.inputs) ? template.inputs : [];
        var outputs = Array.isArray(template.outputs) ? template.outputs : [];
        var byId = {};
        nodes.forEach(function (n) { byId[n.id] = n; });
        var agg = this.aggregate(groupId, (typeof runResults !== 'undefined' && runResults.statuses) || {});
        if (meta) {
            meta.textContent =
                I18n.t('reusable.nodeCount', { n: nodes.length }) + ' · ' +
                I18n.t('reusable.connectionCount', { n: (template.connections || []).length }) +
                (agg ? ' · ' + I18n.t('reusable.statusCount', { done: agg.settled, n: agg.total }) : '');
        }
        var stage = document.getElementById('reusable-preview-stage');
        if (stage) {
            var built = this._stageHtml(groupId, template, {
                maxW: REUSABLE_PREVIEW_MAX_W,
                maxH: REUSABLE_PREVIEW_MAX_H,
            });
            stage.innerHTML = built.html;
        }
        var side = document.getElementById('reusable-preview-side');
        if (!side) return;
        var slots = inputs.map(function (innerId, index) {
            var inner = byId[innerId];
            return (
                '<li><span class="rps-index">' + (index + 1) + '</span>' +
                escapeHtml(inner ? this._titleOf(inner) : innerId) + '</li>'
            );
        }, this).join('');
        var rows = nodes.map(function (inner) {
            var info = this._statusOf(groupId, inner.id);
            var status = info && info.status ? info.status : '';
            return (
                '<li class="rps-node">' +
                '<span class="rps-node-name">' + escapeHtml(this._titleOf(inner)) + '</span>' +
                '<span class="rps-node-type">' + escapeHtml(nodeTypeWord(inner.type)) + '</span>' +
                (status ? '<span class="rin-status st-' + this._statusClass(status) + '" title="' +
                    escapeHtml(this._statusWord(status)) + '"></span>' : '') +
                '</li>'
            );
        }, this).join('');
        var output = byId[outputs[0]];
        side.innerHTML =
            '<div class="rps-section"><h4>' + I18n.t('reusable.inputsTitle') + '</h4>' +
            (slots ? '<ol class="rps-slots">' + slots + '</ol>' : '<div class="settings-hint">' + I18n.t('reusable.noInputs') + '</div>') +
            '</div>' +
            '<div class="rps-section"><h4>' + I18n.t('reusable.outputTitle') + '</h4>' +
            '<div class="rps-output">' + escapeHtml(output ? this._titleOf(output) : '—') + '</div></div>' +
            '<div class="rps-section"><h4>' + I18n.t('reusable.nodesTitle') + '</h4>' +
            '<ul class="rps-nodes">' + rows + '</ul></div>';
    },

    /* ── file ↔ run expansion ─────────────────────────────────────── */

    expand(nodes, connections) {
        var self = this;
        var groups = {};
        Object.keys(canvas.nodes).forEach(function (id) {
            var node = canvas.nodes[id];
            if (node.type === 'reusable') groups[id] = node;
        });
        var enabled = {};
        var outNodes = nodes.slice();
        var innerOut = {};
        Object.keys(groups).forEach(function (groupId) {
            var node = groups[groupId];
            var p = node.params || {};
            if (p.enabled === false) return;
            enabled[groupId] = true;
            var template = p.template || {};
            var innerNodes = Array.isArray(template.nodes) ? template.nodes : [];
            var outputs = Array.isArray(template.outputs) ? template.outputs : [];
            if (!innerNodes.length || !outputs.length) return;
            var byId = {};
            innerNodes.forEach(function (inner) {
                var ns = self.innerId(groupId, inner.id);
                byId[inner.id] = ns;
                var params = JSON.parse(JSON.stringify(inner.params || {}));
                outNodes.push({
                    id: ns,
                    type: inner.type,
                    title: inner.title || '',
                    platform: params.platform,
                    params: params,
                    operation: params.operation,
                    x: Number(inner.x) || 0,
                    y: Number(inner.y) || 0,
                    folded: false,
                });
            });
            if (byId[outputs[0]]) innerOut[groupId] = byId[outputs[0]];
        });
        var outConns = [];
        // Internal wires.
        Object.keys(enabled).forEach(function (groupId) {
            var template = (groups[groupId].params || {}).template || {};
            var innerNodes = Array.isArray(template.nodes) ? template.nodes : [];
            var byId = {};
            innerNodes.forEach(function (inner) { byId[inner.id] = self.innerId(groupId, inner.id); });
            (Array.isArray(template.connections) ? template.connections : []).forEach(function (c) {
                if (byId[c.from] && byId[c.to]) outConns.push({ from: byId[c.from], to: byId[c.to] });
            });
        });
        // Normal-to-normal wires.
        connections.forEach(function (c) {
            if (!groups[c.from] && !groups[c.to]) outConns.push({ from: c.from, to: c.to });
        });
        // Wires entering a group: slot i goes to the template's ordered input i.
        Object.keys(enabled).forEach(function (groupId) {
            var template = (groups[groupId].params || {}).template || {};
            var inputs = Array.isArray(template.inputs) ? template.inputs : [];
            var incoming = connections.filter(function (c) { return c.to === groupId; });
            incoming.forEach(function (c, index) {
                if (index >= inputs.length) return;
                var source = groups[c.from] ? innerOut[c.from] : c.from;
                if (!source) return;
                outConns.push({ from: source, to: self.innerId(groupId, inputs[index]) });
            });
        });
        // Wires leaving a group feed from its single output.
        connections.forEach(function (c) {
            if (!groups[c.from] || !enabled[c.from] || groups[c.to]) return;
            if (innerOut[c.from]) outConns.push({ from: innerOut[c.from], to: c.to });
        });
        return { nodes: outNodes, connections: outConns };
    },

    errors() {
        var self = this;
        var messages = [];
        Object.keys(canvas.nodes).forEach(function (id) {
            var node = canvas.nodes[id];
            if (!node || node.type !== 'reusable') return;
            var p = node.params || {};
            if (p.enabled === false) return;
            var name = String(p.template_name || '').trim() || node.title || id;
            var template = p.template || {};
            var innerNodes = Array.isArray(template.nodes) ? template.nodes : [];
            var outputs = Array.isArray(template.outputs) ? template.outputs : [];
            if (!innerNodes.length || !outputs.length) {
                messages.push(I18n.t('reusable.noTemplateForRun', { name: name }));
                return;
            }
            if (!innerNodes.every(function (inner) { return REUSABLE_ALLOWED_TYPES.indexOf(inner.type) >= 0; })) {
                messages.push(I18n.t('reusable.badTemplate', { name: name }));
            }
            var inputs = Array.isArray(template.inputs) ? template.inputs : [];
            var wired = canvas.connections.filter(function (c) { return c.to === id; }).length;
            if (wired > inputs.length) {
                messages.push(I18n.t('reusable.tooManyInputs', { name: name }));
            } else if (wired < inputs.length) {
                messages.push(I18n.t('reusable.missingInputs', { name: name, n: inputs.length, wired: wired }));
            }
            if (innerNodes.every(function (inner) { return String(inner.id) !== String(outputs[0]); })) {
                messages.push(I18n.t('reusable.noTemplateForRun', { name: name }));
            }
        });
        return messages;
    },
};
