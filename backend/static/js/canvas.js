/* Canvas Node Management */

/* Inline SVG glyphs for the node header action buttons. They stroke with
   `currentColor`, so the existing hover / `.settings-open` colour rules and the
   default dim state all apply unchanged — only sizing lives in the stylesheet. */
const NODE_ICON = {
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">' +
        '<path d="M4 7.5h16M4 16.5h16"/><path d="M10 5v5M15 14v5"/></svg>',
    del: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M4 7h16"/>' +
        '<path d="M9.5 7V5.3c0-.7.6-1.3 1.3-1.3h2.4c.7 0 1.3.6 1.3 1.3V7"/>' +
        '<path d="M6.6 7l.8 11.9a1.9 1.9 0 0 0 1.9 1.8h5.4a1.9 1.9 0 0 0 1.9-1.8L17.4 7"/>' +
        '<path d="M10.4 11v5.5M13.6 11v5.5"/></svg>'
};

const canvas = {
    nodes: {},
    connections: [],
    selectedNode: null,
    nextId: 1,
    panX: 0,
    panY: 0,
    zoom: 1,
    isDragging: false,
    isPanning: false,
    panStartPX: 0,
    panStartPY: 0,
    panWasDragging: false,
    dragTarget: null,
    dragOffsetX: 0,
    dragOffsetY: 0,
    _contextNode: null,
    _contextMenuPos: null,
    _clipboardData: null,
    _settingsNodeId: null,
    connectingFrom: null,
    tempLine: null,
    _renderPending: false,
    PORT_HIT_RADIUS: 400,
    /* ── Undo / Redo ── */
    _history: [],
    _historyIdx: -1,
    _historyMax: 50,
    _historySaving: false,

    init() {
        this.container = document.getElementById('canvas-inner');
        this.svgLayer = document.getElementById('svg-layer');
        this.nodesContainer = document.getElementById('nodes-container');
        this.workspace = document.getElementById('workspace');
        this.setupEvents();
        this.updateStatus();
        const saved = localStorage.getItem('crawler_canvas');
        if (saved) {
            try {
                const state = JSON.parse(saved);
                this.restoreState(state);
            } catch (e) { /* ignore */ }
        }
        /* Uploaded files live in the server's database now, so a node's
           dataset_id is a pointer that outlives this page — it is kept and
           re-verified (see dataNodes.reconcileDatasets) rather than dropped. */
        this._pushState();
    },

    /* ---- Coordinate helpers ---- */
    _getPortCenter(port) {
        const node = port.closest('.node');
        if (!node) return { x: 0, y: 0 };
        const isIn = port.classList.contains('node-port-in');
        const cx = isIn
            ? node.offsetLeft
            : node.offsetLeft + node.offsetWidth;
        const cy = node.offsetTop + node.offsetHeight / 2;
        return { x: cx, y: cy };
    },

    _screenToCanvas(cx, cy) {
        return {
            x: (cx - this.panX) / this.zoom,
            y: (cy - this.panY) / this.zoom,
        };
    },

    _getPortAt(cx, cy) {
        const ports = document.querySelectorAll('.node-port');
        for (const p of ports) {
            const rect = p.getBoundingClientRect();
            const dx = cx - (rect.left + rect.width / 2);
            const dy = cy - (rect.top + rect.height / 2);
            if (dx * dx + dy * dy < this.PORT_HIT_RADIUS) return p;
        }
        return null;
    },

    setupEvents() {
        /* Right-click pan (with drag threshold for context menu) */
        this.workspace.addEventListener('mousedown', (e) => {
            if (e.button === 2) {
                document.getElementById('context-menu').classList.remove('open');
                this.isPanning = true;
                this.panStartX = e.clientX;
                this.panStartY = e.clientY;
                this.panStartPX = this.panX;
                this.panStartPY = this.panY;
                this.panWasDragging = false;
                this.deselectNode();
                this.workspace.style.cursor = 'grabbing';
                e.preventDefault();
            }
        });

        /* Left-click on workspace background to deselect */
        this.workspace.addEventListener('mousedown', (e) => {
            if (e.button === 0 && !e.target.closest('.node') && !e.target.closest('.node-port')) {
                this.deselectNode();
                closeSettings();
            }
        });

        document.addEventListener('mousemove', (e) => {
            if (this.isPanning) {
                const dx = e.clientX - this.panStartX;
                const dy = e.clientY - this.panStartY;
                if (dx * dx + dy * dy > 25) {
                    this.panWasDragging = true;
                }
                if (this.panWasDragging) {
                    this.panX = this.panStartPX + dx;
                    this.panY = this.panStartPY + dy;
                    this.updateTransform();
                }
            }
            if (this.isDragging && this.dragTarget) {
                const rect = this.workspace.getBoundingClientRect();
                const x = (e.clientX - rect.left - this.dragOffsetX - this.panX) / this.zoom;
                const y = (e.clientY - rect.top - this.dragOffsetY - this.panY) / this.zoom;
                this.dragTarget.style.left = x + 'px';
                this.dragTarget.style.top = y + 'px';
                this.scheduleRender();
            }
            if (this.connectingFrom) {
                this.updateTempLine(e);
            }
        });

        document.addEventListener('mouseup', (e) => {
            if (this.isDragging && this.dragTarget) {
                this.saveState();
            }
            this.isPanning = false;
            this.workspace.style.cursor = 'default';
            this.isDragging = false;
            this.dragTarget = null;
            if (this.connectingFrom) {
                this.finishConnection(e);
            }
        });

        /* Right-click context menu */
        this.workspace.addEventListener('contextmenu', (e) => {
            if (this.panWasDragging) {
                this.panWasDragging = false;
                e.preventDefault();
                return;
            }
            e.preventDefault();
            const node = e.target.closest('.node');
            this._contextNode = node ? node.id : null;
            this._contextMenuPos = { x: e.clientX, y: e.clientY };
            const ctxMenu = document.getElementById('context-menu');
            document.getElementById('ctx-edit').style.display = node ? 'block' : 'none';
            document.getElementById('ctx-rename').style.display = node ? 'block' : 'none';
            document.getElementById('ctx-copy').style.display = node ? 'block' : 'none';
            document.getElementById('ctx-delete-node').style.display = node ? 'block' : 'none';
            const foldItem = document.getElementById('ctx-fold-node');
            if (node) {
                const el = document.getElementById(node.id);
                const folded = el && el.classList.contains('node-folded');
                foldItem.style.display = 'block';
                foldItem.textContent = folded ? I18n.t('canvas.unfold') : I18n.t('canvas.fold');
                foldItem.dataset.action = folded ? 'ctxUnfoldNode' : 'ctxFoldNode';
            } else {
                foldItem.style.display = 'none';
            }
            ctxMenu.style.left = Math.min(e.clientX, window.innerWidth - 200) + 'px';
            ctxMenu.style.top = Math.min(e.clientY, window.innerHeight - 200) + 'px';
            ctxMenu.classList.add('open');
        });
        document.addEventListener('click', (e) => {
            const ctxMenu = document.getElementById('context-menu');
            if (!e.target.closest('#context-menu')) {
                ctxMenu.classList.remove('open');
                return;
            }
            /* Handle context menu actions via data-action */
            const item = e.target.closest('[data-action]');
            if (!item) return;
            const action = item.dataset.action;
            ctxMenu.classList.remove('open');
            switch (action) {
                case 'ctxNewSource':
                case 'ctxNewUpload':
                case 'ctxNewProcess':
                case 'ctxNewAnalysis':
                case 'ctxNewVisualize':
                case 'ctxNewTokenize':
                case 'ctxNewOutput': {
                    const pos = this._contextMenuPos
                        ? this._screenToCanvas(this._contextMenuPos.x - 110, this._contextMenuPos.y - 40)
                        : { x: 50 + Math.random() * 200, y: 50 + Math.random() * 200 };
                    const typeMap = {
                        ctxNewSource: 'source', ctxNewUpload: 'upload',
                        ctxNewProcess: 'process',
                        ctxNewAnalysis: 'analysis', ctxNewVisualize: 'visualize',
                        ctxNewTokenize: 'tokenize',
                        ctxNewOutput: 'output',
                    };
                    this.addNode(typeMap[action], pos.x, pos.y);
                    break;
                }
                case 'ctxEdit':
                    if (this._contextNode) this.editNode(this._contextNode);
                    break;
                case 'ctxRename':
                    if (this._contextNode) this.renameNode(this._contextNode);
                    break;
                case 'ctxCopy':
                    if (this._contextNode) {
                        const n = this.nodes[this._contextNode];
                        if (n) {
                            /* The title belongs in the clipboard next to the type and
                               params: a node the user bothered to name is copied to be
                               edited again, and a paste that came back labelled
                               "Data Source" threw the name away for no reason. */
                            this._clipboardData = {
                                type: n.type,
                                title: n.title || '',
                                params: JSON.parse(JSON.stringify(n.params)),
                            };
                            showToast(I18n.t('toast.nodeCopied'));
                        }
                    }
                    break;
                case 'ctxPasteNode':
                    if (this._clipboardData) {
                        const pp = this._contextMenuPos
                            ? this._screenToCanvas(this._contextMenuPos.x - 110, this._contextMenuPos.y - 40)
                            : { x: 100 + Math.random() * 200, y: 100 + Math.random() * 200 };
                        const id = this.addNode(this._clipboardData.type, pp.x, pp.y);
                        if (this.nodes[id]) {
                            this.nodes[id].params = JSON.parse(JSON.stringify(this._clipboardData.params));
                            /* Same order restoreState needs: updateNodeDisplay only keeps
                               a name that is already on both the node AND its element, so
                               stamping it afterwards would let the re-stamp overwrite the
                               copied name with the type's default label. */
                            if (this._clipboardData.title) {
                                this.nodes[id].title = this._clipboardData.title;
                                const titleEl = this.nodes[id].el && this.nodes[id].el.querySelector('.node-title');
                                if (titleEl) titleEl.textContent = this._clipboardData.title;
                            }
                            this.updateNodeDisplay(id);
                        }
                        showToast(I18n.t('toast.nodePasted'));
                    }
                    break;
                case 'ctxDeleteNode':
                    if (this._contextNode) this.deleteNode(this._contextNode);
                    break;
                case 'clearConns':
                    this.connections = [];
                    this.scheduleRender();
                    this.saveState();
                    showToast(I18n.t('toast.connCleared'));
                    break;
                case 'ctxFoldNode':
                    if (this._contextNode) this.toggleFold(this._contextNode);
                    break;
                case 'ctxUnfoldNode':
                    if (this._contextNode) this.toggleFold(this._contextNode);
                    break;
                case 'undo':
                    this.undo();
                    break;
                case 'redo':
                    this.redo();
                    break;
                case 'autoLayout':
                    this.autoLayout();
                    break;
            }
        });

        /* Zoom with the scroll wheel — no buttons. The point under the cursor
           stays put, so zooming feels anchored rather than drifting. */
        this.workspace.addEventListener('wheel', (e) => {
            e.preventDefault();
            const rect = this.workspace.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            const oldZoom = this.zoom;
            /* 0.999^deltaY ≈ 10% per mouse notch, smooth on trackpads too */
            const factor = Math.pow(0.999, e.deltaY);
            const newZoom = Math.max(0.2, Math.min(3, oldZoom * factor));
            if (newZoom === oldZoom) return;
            /* pan' = cursor - (cursor - pan) * (zoom'/zoom) keeps that point fixed */
            const ratio = newZoom / oldZoom;
            this.panX = mx - (mx - this.panX) * ratio;
            this.panY = my - (my - this.panY) * ratio;
            this.zoom = newZoom;
            this.updateTransform();
            document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
            Settings.save();
        }, { passive: false });

        /* Drag from palette */
        document.querySelectorAll('.palette-item').forEach(item => {
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.type);
            });
        });
        this.workspace.addEventListener('dragover', (e) => e.preventDefault());
        this.workspace.addEventListener('drop', (e) => {
            e.preventDefault();
            const type = e.dataTransfer.getData('text/plain');
            if (type) {
                const pos = this._screenToCanvas(e.clientX - 110, e.clientY - 40);
                this.addNode(type, pos.x, pos.y);
            }
        });

        /* Keyboard shortcuts */
        document.addEventListener('keydown', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (this.selectedNode) this.deleteNode(this.selectedNode);
                return;
            }
            if (e.key === 'Escape') {
                this.cancelConnection();
                this.deselectNode();
                closeSettings();
                return;
            }
            /* Undo / Redo */
            if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
                e.preventDefault();
                if (e.shiftKey) {
                    this.redo();
                } else {
                    this.undo();
                }
                return;
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
                e.preventDefault();
                this.redo();
                return;
            }
            /* Fold/unfold selected node with F key */
            if (e.key === 'f' && this.selectedNode) {
                e.preventDefault();
                this.toggleFold(this.selectedNode);
            }
        });
    },

    /* Node ids are keys, not labels: run records, resume cursors and the LLM
       answer cache are all filed under them, and the workflow fingerprint hashes
       them. Re-minting them on restore therefore breaks the resume banner for a
       canvas the user only pressed Ctrl+Z on. So a restored or opened node keeps
       the id it was stored with, and this keeps the counter clear of it — a
       later drag-and-drop must not mint an id that is already on the board. */
    reserveId(id) {
        const match = /(\d+)\s*$/.exec(String(id || ''));
        if (match) this.nextId = Math.max(this.nextId, parseInt(match[1], 10) + 1);
    },

    addNode(type, x, y, nodeId) {
        const wanted = String(nodeId || '').trim();
        /* A node id is a DOM id, a run-record key and part of the workflow
           fingerprint, so a file-authored id has to be shaped like one. Anything
           else (quotes, brackets, whitespace) comes from a hand-edited JSON and
           gets a fresh id minted rather than a place in this document. */
        const usable = /^[\w.-]{1,64}$/.test(wanted) && !this.nodes[wanted];
        const id = usable ? wanted : 'node-' + this.nextId++;
        this.reserveId(id);
        const labels = {
            name: I18n.t('node.name'),
            source: I18n.t('node.source'),
            upload: I18n.t('node.upload'),
            process: I18n.t('node.process'),
            analysis: I18n.t('node.analysis'),
            visualize: I18n.t('node.visualize'),
            tokenize: I18n.t('node.tokenize'),
            output: I18n.t('node.output'),
            resume: I18n.t('node.resume'),
            comment: I18n.t('node.comment'),
        };
        const title = labels[type] || 'Node';
        const el = document.createElement('div');
        el.className = 'node node-type-' + type;
        el.id = id;
        el.style.left = (x || 100 + Math.random() * 200) + 'px';
        el.style.top = (y || 100 + Math.random() * 200) + 'px';
        const params = this.getDefaultParams(type);
        /* Markup and behaviour are kept apart on purpose. This template used to
           splice the id and the node summary into `onclick="canvas.editNode('<id>')"`
           and `innerHTML`, so an id or a keyword containing a quote escaped its
           string literal and ran as code — a workflow JSON is a file the user can
           edit, and every restore path hands it straight back to this function.
           Icons are trusted constants, so they are the only thing interpolated. */
        el.innerHTML = [
            '<div class="node-header">',
            '  <span class="node-title"></span>',
            '  <div class="node-actions">',
            '    <button class="node-action-btn" type="button">' + NODE_ICON.settings + '</button>',
            '    <button class="node-action-btn del" type="button">' + NODE_ICON.del + '</button>',
            '  </div>',
            '</div>',
            '<div class="node-content"></div>',
            '<div class="node-port node-port-in" data-port="in"></div>',
            '<div class="node-port node-port-out" data-port="out"></div>',
        ].join('');
        const titleEl = el.querySelector('.node-title');
        titleEl.textContent = title;
        titleEl.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            this.renameNode(id);
        });
        const actionBtns = el.querySelectorAll('.node-action-btn');
        actionBtns[0].title = I18n.t('ctx.edit');
        actionBtns[0].addEventListener('click', () => this.editNode(id));
        actionBtns[1].title = I18n.t('ctx.delete');
        actionBtns[1].addEventListener('click', () => this.deleteNode(id));
        el.querySelector('.node-content').textContent = this.getNodeSummary(type, params);
        el.querySelectorAll('.node-port').forEach((port) => {
            port.dataset.node = id;
        });
        this.nodesContainer.appendChild(el);
        this.nodes[id] = { id: id, type: type, title: title, el: el, params: params, x: el.offsetLeft, y: el.offsetTop };

        /* Make draggable */
        const header = el.querySelector('.node-header');
        header.addEventListener('mousedown', (e) => {
            if (e.target.closest('.node-actions')) return;
            this.isDragging = true;
            this.dragTarget = el;
            const rect = el.getBoundingClientRect();
            this.dragOffsetX = e.clientX - rect.left;
            this.dragOffsetY = e.clientY - rect.top;
            this.selectNode(id);
        });

        /* Port connection */
        el.querySelectorAll('.node-port').forEach(port => {
            port.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                if (port.dataset.port === 'out') this.startConnection(id, e);
            });
        });

        this.updateStatus();
        this.scheduleRender();
        this.saveState();
        return id;
    },

    getUpstreamNodeId(nodeId) {
        const conn = this.connections.find(c => c.to === nodeId);
        return conn ? conn.from : null;
    },

    _defaultSourceParams() {
        /* A fresh Data Source node carries the matrix's own figures rather than a
           copy of them typed in here, so the crawl a never-opened node performs is
           the crawl its panel would have previewed. The executor also falls back to
           those defaults when a stored file has no key, which is what keeps this
           working before the fetch has answered: `Capabilities` is workflow.js
           territory, and a top-level `const` never becomes a window property, so
           the binding itself is what has to be asked. */
        if (typeof Capabilities === 'undefined' || !Capabilities.ready()) {
            return { platform: 'zhihu', collect: 'posts' };
        }
        const platform = 'zhihu';
        const params = Capabilities.defaults(platform);
        params.platform = platform;
        params.collect = Capabilities.mode(platform, '').key;
        return params;
    },

    getDefaultParams(type) {
        /* The name node carries the workflow's label for the Execution History
           panel — it is metadata, not data, so its params are just the name. */
        if (type === 'name') return { workflow_name: '' };
        if (type === 'source') return this._defaultSourceParams();
        if (type === 'upload') return { dataset_id: '', dataset_name: '', row_count: '' };
        if (type === 'process') return { operation: 'clean', text_column: '正文', topic: '', live_export: false, format: 'csv' };
        if (type === 'analysis') return { operation: 'drop_null', columns: '', column: '', value: '', op: 'eq', dtype: 'str', rename_from: '', rename_to: '' };
        if (type === 'visualize') return { chart_type: 'bar', x_field: '', y_field: '', value_field: '', agg: 'sum', engine: 'echarts', title: '', tokenize: false };
        if (type === 'tokenize') return { text_column: '', top_n: '', output_mode: 'word_freq' };
        /* Empty run ids mean "auto": pick the newest interrupted run, and
           inside it whichever node holds the most rows. */
        if (type === 'resume') return { resume_run_id: '', resume_node_id: '', resume_limit: 0 };
        if (type === 'comment') return { urls: '', comment_limit: 0, part_size: 50, per_article_file: true, keep_parts: false, format: 'csv' };
        if (type === 'output') return { operation: 'save', format: 'csv', filename: 'export.csv' };
        return {};
    },

    sourceSummaryLine(f, value) {
        /* One line of a data-source card, shaped by the widget the matrix declares:
           a link list reads as a count (the paste is long and the number is the
           useful part), a choice reads as its label, and text reads as itself. */
        var label = I18n.t(f.labelKey);
        if (f.coerce === 'urls') {
            var count = String(value || '').split('\n').filter(function (u) { return u.trim(); }).length;
            return label + ': ' + count;
        }
        if (f.control === 'select') {
            var options = f.options || [];
            var chosen = (value === undefined || value === null || value === '') ? f.default : value;
            for (var i = 0; i < options.length; i++) {
                if (String(options[i].value) === String(chosen)) return label + ': ' + I18n.t(options[i].labelKey);
            }
            return label + ': ' + (chosen || '—');
        }
        return label + ': ' + (String(value || '').trim() || '—');
    },

    getNodeSummary(type, params) {
        if (type === 'name') {
            var n = String(params.workflow_name || '').trim();
            return I18n.t('settings.workflowName') + ': ' + (n || I18n.t('name.unnamed'));
        }
        if (type === 'source') {
            var plat = params.platform || '';
            var head = I18n.t('settings.platform') + ': ' + (plat ? I18n.t('platform.' + plat) : '?');
            /* Read what the platform actually offers from the crawl matrix. This
               used to be two hard-coded branches (comments, wechat) plus a default
               of "关键词", so a node collecting one creator's uploads — or a hot
               board, which has no keyword at all — printed a keyword it never used,
               and the user watched the card promise a crawl the run did not do. */
            if (!plat || typeof Capabilities === 'undefined' || !Capabilities.ready()) {
                /* No matrix yet (a cold page renders its restored nodes before the
                   fetch answers) says only what is in the node. Guessing 关键词 here
                   would be the bug above wearing a different hat. */
                return head;
            }
            var mode = Capabilities.mode(plat, params.collect || params.mode);
            if (!mode) {
                return head;
            }
            var lines = [head + ' · ' + I18n.t(mode.labelKey)];
            var canvas = this;
            (mode.fields || []).forEach(function (f) {
                if (f.control === 'number' || f.control === 'checkbox' || !f.required && f.control !== 'select') return;
                lines.push(canvas.sourceSummaryLine(f, params[f.key]));
            });
            return lines.join('\n');
        }
        if (type === 'upload') {
            var name = params.dataset_name || '';
            var rows = params.row_count || '';
            if (!name) return I18n.t('dataSource.none');
            return I18n.t('settings.file') + ': ' + name + (rows ? '\n' + rows + ' ' + I18n.t('settings.rows') : '');
        }
        if (type === 'process') {
            var op = params.operation || '';
            return I18n.t('settings.operation') + ': ' + (op ? I18n.t('op.' + op) : '?');
        }
        if (type === 'analysis') {
            var op = params.operation || '';
            return I18n.t('settings.operation') + ': ' + (op ? I18n.t('op.' + op) : '?');
        }
        if (type === 'visualize') {
            return I18n.t('settings.chartType') + ': ' + (params.chart_type || '?') +
                '\n' + I18n.t('settings.engine') + ': ' + (params.engine || 'echarts');
        }
        if (type === 'tokenize') {
            var mode = params.output_mode || 'word_freq';
            var summary = I18n.t('settings.textColumn') + ': ' + (params.text_column || '?') +
                '\n' + I18n.t('settings.outputMode') + ': ' + I18n.t('outputMode.' + mode);
            if (mode === 'word_freq' && params.top_n) {
                summary += I18n.t('summary.tokenizeTop').replace('{n}', params.top_n);
            }
            return summary;
        }
        if (type === 'resume') {
            /* What it will hand downstream is stored server-side, so the node
               has nothing to summarise beyond which pick it will use. */
            var runPart = params.resume_run_id || I18n.t('resume.autoNode');
            return I18n.t('settings.operation') + ': ' + runPart +
                (params.resume_node_id ? '\n' + params.resume_node_id : '');
        }
        if (type === 'comment') {
            /* Source-like crawler: the only thing worth reading off the node is
               how many article links it will visit and in what format. */
            var cUrls = String(params.urls || '').split('\n').filter(function (u) { return u.trim(); }).length;
            return I18n.t('settings.commentUrls') + ': ' + cUrls +
                '\n' + I18n.t('settings.format') + ': ' + (params.format || 'csv');
        }
        if (type === 'output') {
            var op = params.operation || '';
            if (op === 'save') {
                return I18n.t('settings.format') + ': ' + (params.format || 'csv') + ' \u2192 ' + (params.filename || 'export');
            }
            return I18n.t('settings.operation') + ': ' + (op ? I18n.t('op.' + op) : '?');
        }
        return '';
    },

    deleteNode(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
        delete this.nodes[id];
        this.connections = this.connections.filter(c => c.from !== id && c.to !== id);
        if (this.selectedNode === id) this.selectedNode = null;
        /* The panel is bound to this node id — leaving it open would keep showing
           its old settings and let the user edit a node that no longer exists. */
        if (this._settingsNodeId === id) closeSettings();
        this.scheduleRender();
        this.updateStatus();
        this.saveState();
        showToast(I18n.t('toast.nodeDeleted'));
    },

    selectNode(id) {
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        this.selectedNode = id;
        const el = document.getElementById(id);
        if (el) el.classList.add('selected');
    },

    deselectNode() {
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        this.selectedNode = null;
    },

    editNode(id) {
        this.selectNode(id);
        if (this._settingsNodeId === id) {
            closeSettings();
            return;
        }
        this._settingsNodeId = id;
        const node = this.nodes[id];
        if (node) openSettings(id);
    },

    async renameNode(id) {
        /* The console reads nodes as "name #node-3" — this name is the user's.
           An empty box clears the custom name back to the type's label, and
           updateNodeDisplay's re-stamp logic then lets language switches
           rename it again (a name the user typed is never touched). */
        const node = this.nodes[id];
        if (!node) return;
        const name = await showDialog({
            message: I18n.t('dialog.renameNode'),
            input: { value: node.title || '', placeholder: I18n.t('node.' + node.type) },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('dialog.confirm'), primary: true },
            ],
        });
        if (name === null || name === undefined) return;
        const title = String(name).trim() || I18n.t('node.' + node.type);
        node.title = title;
        const titleEl = node.el ? node.el.querySelector('.node-title') : null;
        if (titleEl) titleEl.textContent = title;
        this.saveState();
    },

    /* Undo/redo and workflow loads can drop nodes wholesale — the settings panel
       must not outlive the node it describes. */
    closeSettingsIfStale() {
        if (this._settingsNodeId && !this.nodes[this._settingsNodeId]) closeSettings();
    },

    updateSettingsButton() {
        document.querySelectorAll('.node-action-btn').forEach(btn => {
            btn.classList.remove('settings-open');
        });
        if (this._settingsNodeId) {
            const nodeEl = document.getElementById(this._settingsNodeId);
            if (nodeEl) {
                const btn = nodeEl.querySelector('.node-action-btn');
                if (btn) btn.classList.add('settings-open');
            }
        }
    },

    /* ---- Connections ---- */
    startConnection(fromId, e) {
        this.connectingFrom = fromId;
        this.tempLine = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        this.tempLine.classList.add('conn-line', 'temp');
        this.svgLayer.appendChild(this.tempLine);
        this.updateTempLine(e);
    },

    updateTempLine(e) {
        if (!this.tempLine) return;
        const fromPort = document.querySelector('[data-node="' + this.connectingFrom + '"][data-port="out"]');
        if (!fromPort) return;
        const from = this._getPortCenter(fromPort);
        const to = this._screenToCanvas(e.clientX, e.clientY);
        if (from.x == null) return;
        const dx = to.x - from.x;
        const cp1x = from.x + Math.abs(dx) * 0.5;
        const cp2x = to.x - Math.abs(dx) * 0.5;
        this.tempLine.setAttribute('d', [
            'M', from.x, from.y,
            'C', cp1x, from.y, ',', cp2x, to.y, to.x, to.y,
        ].join(' '));
    },

    finishConnection(e) {
        const target = this._getPortAt(e.clientX, e.clientY);
        if (target && target.dataset.port === 'in') {
            const toId = target.dataset.node;
            if (toId !== this.connectingFrom) {
                const exists = this.connections.some(c => c.from === this.connectingFrom && c.to === toId);
                if (!exists) {
                    this.connections.push({ from: this.connectingFrom, to: toId });
                    this.scheduleRender();
                    this.saveState();
                    showToast(I18n.t('toast.connCreated'));
                    // Tokenize ↔ Visualize: force word_freq + refresh settings
                    var nA = this.nodes[this.connectingFrom];
                    var nB = this.nodes[toId];
                    var tkNode = (nA && nA.type === 'tokenize') ? nA : (nB && nB.type === 'tokenize') ? nB : null;
                    var vzNode = (nA && nA.type === 'visualize') ? nA : (nB && nB.type === 'visualize') ? nB : null;
                    if (tkNode && vzNode) {
                        if (tkNode.params.output_mode !== 'word_freq') {
                            tkNode.params.output_mode = 'word_freq';
                            this.updateNodeDisplay(tkNode.id);
                            this.saveState();
                        }
                        if (typeof openSettings === 'function') {
                            var openId = this._settingsNodeId;
                            if (openId === tkNode.id || openId === vzNode.id) {
                                openSettings(openId);
                            }
                        }
                    }
                }
            }
        }
        this.cancelConnection();
    },

    cancelConnection() {
        this.connectingFrom = null;
        if (this.tempLine) { this.tempLine.remove(); this.tempLine = null; }
    },

    scheduleRender() {
        if (this._renderPending) return;
        this._renderPending = true;
        requestAnimationFrame(() => {
            this._renderPending = false;
            this.updateConnections();
        });
    },

    updateConnections() {
        this.svgLayer.querySelectorAll('.conn-line:not(.temp)').forEach(l => l.remove());
        this.svgLayer.querySelectorAll('.conn-delete-hit').forEach(l => l.remove());
        this.connections.forEach((conn, idx) => {
            const fromPort = document.querySelector('[data-node="' + conn.from + '"][data-port="out"]');
            const toPort = document.querySelector('[data-node="' + conn.to + '"][data-port="in"]');
            if (!fromPort || !toPort) return;
            const from = this._getPortCenter(fromPort);
            const to = this._getPortCenter(toPort);
            if (from.x == null || to.x == null) return;
            const dx = to.x - from.x;
            const cp1x = from.x + Math.abs(dx) * 0.5;
            const cp2x = to.x - Math.abs(dx) * 0.5;
            const d = [
                'M', from.x, from.y,
                'C', cp1x, from.y, ',', cp2x, to.y, to.x, to.y,
            ].join(' ');

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.classList.add('conn-line');
            path.setAttribute('d', d);

            const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            hit.classList.add('conn-delete-hit');
            hit.setAttribute('d', d);
            hit.addEventListener('click', function () {
                canvas.connections.splice(idx, 1);
                canvas.scheduleRender();
                canvas.saveState();
                showToast(I18n.t('toast.connRemoved'));
            });
            hit.addEventListener('mouseenter', function () {
                path.style.stroke = '#ff4444';
                path.style.strokeWidth = '3px';
            });
            hit.addEventListener('mouseleave', function () {
                path.style.stroke = '';
                path.style.strokeWidth = '';
            });

            this.svgLayer.appendChild(hit);
            this.svgLayer.appendChild(path);
        });
    },

    /* ---- Transform ---- */
    updateTransform() {
        /* Round the pan to whole device pixels so the canvas never sits on a
           sub-pixel boundary (which would smear text and edges into a blur). */
        const px = Math.round(this.panX);
        const py = Math.round(this.panY);
        this.container.style.transform = 'translate(' + px + 'px, ' + py + 'px) scale(' + this.zoom + ')';
    },

    zoomIn() {
        this.zoom = Math.min(3, this.zoom * 1.2);
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
        Settings.save();
    },

    zoomOut() {
        this.zoom = Math.max(0.2, this.zoom / 1.2);
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
        Settings.save();
    },

    resetView() {
        this.panX = 0;
        this.panY = 0;
        this.zoom = 1;
        /* Center nodes in viewport */
        const ids = Object.keys(this.nodes);
        if (ids.length > 0) {
            let cxSum = 0, cySum = 0;
            ids.forEach(function (id) {
                const el = document.getElementById(id);
                if (el) {
                    cxSum += el.offsetLeft + el.offsetWidth / 2;
                    cySum += el.offsetTop + el.offsetHeight / 2;
                }
            });
            const avgCx = cxSum / ids.length;
            const avgCy = cySum / ids.length;
            this.panX = window.innerWidth / 2 - avgCx;
            this.panY = window.innerHeight / 2 - avgCy;
        }
        this.updateTransform();
        document.getElementById('status-zoom').textContent = '100%';
        Settings.save();
    },

    /* ---- State ---- */
    getState() {
        const nodes = {};
        Object.keys(this.nodes).forEach(id => {
            const n = this.nodes[id];
            const el = document.getElementById(id);
            nodes[id] = {
                id: id, type: n.type, title: n.title, params: n.params,
                x: el ? parseInt(el.style.left) : n.x,
                y: el ? parseInt(el.style.top) : n.y,
                /* A folded node is a layout the user chose, and toggleFold already
                   pays for a save — which used to write a draft with no fold in it,
                   so a reload quietly unfolded everything. */
                folded: el ? el.classList.contains('node-folded') : false,
            };
        });
        return { nodes: nodes, connections: this.connections, nextId: this.nextId };
    },

    restoreState(state) {
        this.nextId = 1;
        /* Sort by the trailing number in the id so a rebuild lands in the same
           order it was drawn in. parseInt on a split('-') was the old way and
           returned NaN for ids a file authored (n1, nA) — an arbitrary order
           then fed the index-based connection remap below. */
        const ordinal = (id) => {
            const match = /(\d+)\s*$/.exec(String(id || ''));
            return match ? parseInt(match[1], 10) : 0;
        };
        var nodeList = Object.values(state.nodes || {}).sort(function (a, b) {
            return ordinal(a.id) - ordinal(b.id);
        });
        nodeList.forEach(function (n) {
            const id = canvas.addNode(n.type, n.x, n.y, n.id);
            if (canvas.nodes[id]) {
                canvas.nodes[id].params = n.params;
                /* The renamed title must travel back BEFORE the display update
                   — which re-stamps only titles that are still a type default —
                   and into the ELEMENT too, because that is what the re-stamp
                   reads; otherwise a reload (or undo/redo) erases every name
                   the user chose. */
                if (n.title) {
                    canvas.nodes[id].title = n.title;
                    const titleEl = canvas.nodes[id].el && canvas.nodes[id].el.querySelector('.node-title');
                    if (titleEl) titleEl.textContent = n.title;
                }
                /* After the display update, which rewrites `.node-content`'s text:
                   hiding it first would only be undone by the stamp. */
                canvas.updateNodeDisplay(id);
                if (n.folded) canvas._setFolded(id, true);
            }
        });
        var ids = Object.keys(canvas.nodes);
        this.connections = (state.connections || []).map(function (c) {
            var fromIdx = nodeList.findIndex(function (n) { return n.id === c.from; });
            var toIdx = nodeList.findIndex(function (n) { return n.id === c.to; });
            if (fromIdx >= 0 && toIdx >= 0 && ids[fromIdx] && ids[toIdx]) {
                return { from: ids[fromIdx], to: ids[toIdx] };
            }
            return null;
        }).filter(Boolean);
        this.scheduleRender();
        this.saveState();
    },

    /* ── Undo / Redo ── */
    _pushState() {
        if (this._historySaving) return;
        const state = this.getState();
        /* Remove any redo states beyond current position */
        this._history = this._history.slice(0, this._historyIdx + 1);
        this._history.push(state);
        if (this._history.length > this._historyMax) {
            this._history.shift();
        }
        this._historyIdx = this._history.length - 1;
    },

    undo() {
        if (this._historyIdx <= 0) return;
        this._historyIdx--;
        this._restoreHistory();
    },

    redo() {
        if (this._historyIdx >= this._history.length - 1) return;
        this._historyIdx++;
        this._restoreHistory();
    },

    _restoreHistory() {
        const state = this._history[this._historyIdx];
        if (!state) return;
        this._historySaving = true;
        Object.keys(this.nodes).forEach(id => {
            const el = document.getElementById(id);
            if (el) el.remove();
        });
        this.nodes = {};
        this.connections = [];
        this.restoreState(state);
        this._historySaving = false;
        /* An undo/redo may have removed the node the settings panel is showing. */
        this.closeSettingsIfStale();
    },

    refreshSourceSummaries() {
        /* A data-source card is written from the crawl matrix, which arrives
           asynchronously — so the nodes a draft restored before it landed are
           showing the platform line alone until this runs. */
        var self = this;
        Object.keys(this.nodes).forEach(function (id) {
            if (self.nodes[id].type === 'source') self.updateNodeDisplay(id);
        });
    },

    updateNodeDisplay(id) {
        const node = this.nodes[id];
        if (!node) return;
        const el = document.getElementById(id);
        if (!el) return;
        const content = el.querySelector('.node-content');
        if (content) content.textContent = this.getNodeSummary(node.type, node.params);
        /* The header label is stamped once, at creation time, so a language
           switch would leave "Data Source" sitting on a node while the rest of
           the UI turns Chinese. Re-stamp it — but only while it still is one of
           that type's default labels, so a renamed node keeps its name. */
        const titleEl = el.querySelector('.node-title');
        if (titleEl) {
            titleEl.title = I18n.t('ctx.renameHint');
            const defaults = Object.keys(I18n.dict).map(function (lang) {
                return I18n.dict[lang]['node.' + node.type];
            });
            if (defaults.indexOf(titleEl.textContent) >= 0) {
                const label = I18n.t('node.' + node.type);
                titleEl.textContent = label;
                node.title = label;
            }
        }
        /* The two header buttons are built once at creation time, so their
           tooltips have to be re-stamped whenever the language changes. */
        const btns = el.querySelectorAll('.node-action-btn');
        if (btns[0]) btns[0].title = I18n.t('ctx.edit');
        if (btns[1]) btns[1].title = I18n.t('ctx.delete');
    },

    saveState() {
        localStorage.setItem('crawler_canvas', JSON.stringify(this.getState()));
        this._pushState();
    },

    updateStatus() {
        const count = Object.keys(this.nodes).length;
        document.getElementById('status-nodes').textContent = I18n.t('status.nodes') + count;
    },

    /* ── Node fold / unfold ── */
    /* Shared with restoreState: a fold is two style writes plus a class, and a
       second copy would drift the moment one of the three changed. */
    _setFolded(id, folded) {
        const el = document.getElementById(id);
        if (!el) return false;
        el.classList.toggle('node-folded', !!folded);
        const content = el.querySelector('.node-content');
        const actions = el.querySelector('.node-actions');
        if (content) content.style.display = folded ? 'none' : '';
        if (actions) actions.style.display = folded ? 'none' : '';
        return true;
    },

    toggleFold(id) {
        const el = document.getElementById(id);
        if (!el) return;
        const folded = !el.classList.contains('node-folded');
        if (!this._setFolded(id, folded)) return;
        this.scheduleRender();
        this.saveState();
    },

    /* ── Auto-layout using simple grid placement ── */
    autoLayout() {
        const gapX = 280;
        const gapY = 120;

        /* Step 1: find connected components (undirected) */
        const nodeIds = Object.keys(this.nodes);
        if (nodeIds.length === 0) return;
        const uadj = {};
        nodeIds.forEach(function (nid) { uadj[nid] = new Set(); });
        this.connections.forEach(function (c) {
            if (uadj[c.from]) uadj[c.from].add(c.to);
            if (uadj[c.to]) uadj[c.to].add(c.from);
        });
        const visited = new Set();
        const components = [];
        nodeIds.forEach(function (nid) {
            if (visited.has(nid)) return;
            const comp = [];
            const queue = [nid];
            visited.add(nid);
            while (queue.length) {
                const cur = queue.shift();
                comp.push(cur);
                uadj[cur].forEach(function (nb) {
                    if (!visited.has(nb)) { visited.add(nb); queue.push(nb); }
                });
            }
            components.push(comp);
        });

        /* Step 2: layout each component independently (stacked vertically) */
        const allPositions = [];
        const compGap = 40;
        let cursorY = 0;

        components.forEach(function (comp) {
            const compSet = new Set(comp);
            const compConns = this.connections.filter(function (c) {
                return compSet.has(c.from) && compSet.has(c.to);
            });
            /* Build topology for this component */
            const inDeg = {};
            const adj = {};
            comp.forEach(function (nid) {
                if (!(nid in inDeg)) inDeg[nid] = 0;
                adj[nid] = [];
            });
            compConns.forEach(function (c) {
                adj[c.from] = adj[c.from] || [];
                adj[c.from].push(c.to);
                if (!(c.to in inDeg)) inDeg[c.to] = 0;
                inDeg[c.to]++;
            });
            comp.forEach(function (nid) {
                if (!(nid in inDeg)) inDeg[nid] = 0;
            });
            const levels = [];
            let remaining = new Set(comp);
            while (remaining.size > 0) {
                const current = [];
                remaining.forEach(function (nid) {
                    if (inDeg[nid] === 0) current.push(nid);
                });
                if (current.length === 0) break;
                levels.push(current);
                current.forEach(function (nid) {
                    (adj[nid] || []).forEach(function (nb) { inDeg[nb]--; });
                    remaining.delete(nid);
                });
            }
            if (remaining.size > 0) levels.push(Array.from(remaining));

            /* Compute node positions for this component */
            const positions = [];
            levels.forEach(function (level, li) {
                level.forEach(function (nid, ni) {
                    const x = li * gapX;
                    const y = ni * gapY - (level.length - 1) * gapY / 2;
                    positions.push({ id: nid, x: x, y: y });
                });
            });

            /* Find component's actual top and bottom edges in local coords */
            let compTop = Infinity, compBottom = -Infinity;
            positions.forEach(function (p) {
                const el = document.getElementById(p.id);
                const h = (el && el.offsetHeight) || 80;
                if (p.y < compTop) compTop = p.y;
                if (p.y + h > compBottom) compBottom = p.y + h;
            });

            /* Shift so the top edge aligns with cursorY */
            const shift = cursorY - compTop;

            positions.forEach(function (p) {
                const el = document.getElementById(p.id);
                if (!el) return;
                allPositions.push({ id: p.id, x: p.x, y: p.y + shift });
            });

            cursorY = compBottom + shift + compGap;
        }, this);

        /* Step 3: center everything in viewport using visual node centers */
        let cxSum = 0, cySum = 0, count = 0;
        allPositions.forEach(function (p) {
            const el = document.getElementById(p.id);
            if (!el) return;
            cxSum += p.x + el.offsetWidth / 2;
            cySum += p.y + el.offsetHeight / 2;
            count++;
        });
        if (count === 0) return;
        const layoutCenterX = cxSum / count;
        const layoutCenterY = cySum / count;
        const vpCenterX = window.innerWidth / 2;
        const vpCenterY = window.innerHeight / 2;
        const offsetX = vpCenterX - layoutCenterX;
        const offsetY = vpCenterY - layoutCenterY;

        allPositions.forEach(function (p) {
            const el = document.getElementById(p.id);
            if (el) {
                el.style.left = Math.round(p.x + offsetX) + 'px';
                el.style.top = Math.round(p.y + offsetY) + 'px';
            }
        });

        this.panX = 0;
        this.panY = 0;
        this.zoom = 1;
        this.updateTransform();
        document.getElementById('status-zoom').textContent = '100%';
        this.scheduleRender();
        this.saveState();
        showToast(I18n.t('toast.layoutApplied'));
    },

    toWorkflowJSON() {
        const nodes = [];
        Object.keys(this.nodes).forEach(id => {
            const n = this.nodes[id];
            const el = document.getElementById(id);
            nodes.push({
                id: id,
                type: n.type,
                // The console addresses nodes by this title ('数据源 #node-1');
                // omitting it here (as an earlier revision did) silently sent
                // title:None to the backend, so every run spoke in bare node-N.
                title: n.title,
                platform: n.params.platform,
                params: n.params,
                operation: n.params.operation,
                x: el ? parseInt(el.style.left) : 0,
                y: el ? parseInt(el.style.top) : 0,
                // Positions survive a save, and so must the fold they were arranged with.
                folded: el ? el.classList.contains('node-folded') : false,
            });
        });
        return {
            nodes: nodes,
            connections: this.connections,
            settings: {
                mode: RunState.parallel ? 'parallel' : 'serial',
                headless: RunState.headless,
                max_workers: 4,
            },
        };
    },
};
