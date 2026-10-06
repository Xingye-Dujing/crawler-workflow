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
        '<path d="M10.4 11v5.5M13.6 11v5.5"/></svg>',
    power: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">' +
        '<path d="M12 4v7"/>' +
        '<path d="M7.5 7.5a6 6 0 1 0 9 0"/></svg>'
};

/* How far apart two port centres may sit and still be called ALIGNED, in canvas px.
   autoLayout rounds node tops and centres heights of differing parity, so its own
   wires can end up a hair under a pixel off the shared centreline — 1.0 absorbs that
   rounding (each Math.round is ≤0.5) so a laid-out straight chain really draws flat,
   while anything a human dragged with a visible slope (over 1px across a 220–340px
   node is a real angle) keeps its curve: the curve is geometry, not decoration. */
const WIRE_ALIGN_EPS = 1.0;

/* 适应 (resetView) leaves this much SCREEN-pixel air around the node cluster and
   never leaves the zoom band [0.2, 1]: fit means "everything visible", so a
   graph that already fits stays at 100% instead of looming larger, and the floor
   is the same one the zoom-out button stops at. */
const VIEW_FIT_MARGIN = 40;

const canvas = {
    nodes: {},
    connections: [],
    /* Node types the user has switched off for the whole canvas (e.g. ['source']). A node of one
       of these types is disabled, and so is anything that loses its last live input — the canvas
       mirrors the backend's effective graph (:func:`effective_workflow`) ONLY to grey the boxes
       and to name the run; what actually executes stays the backend's decision. */
    disabledTypes: [],
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
    /* Per-session memory of the fan-in / fan-out wire warnings the user chose to
       silence ("don't warn again this session"). It lives on the canvas instance, not a
       module global, so a fresh canvas — and the frontend harness's freshWorld — starts
       with an empty set and one scenario cannot mute another's warnings. */
    _connWarningsDismissed: new Set(),
    tempLine: null,
    _renderPending: false,
    /* One observer for every node box, built on first use. See addNode. */
    _nodeObserver: null,
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
        /* One pointer path for mouse, touch and pen (matches makeDraggable). The workspace
           claims the drag (touch-action:none) so a finger on the background pans the camera —
           a tablet has no right button to hold. A background press that never moved is a
           deselect + close (what the old left-click did); the right button still pans, so the
           desktop gesture is unchanged. Nodes and ports stop propagation into their handlers. */
        this.workspace.style.touchAction = 'none';
        this.workspace.addEventListener('pointerdown', (e) => {
            if (e.target.closest('.node') || e.target.closest('.node-port')) return;
            document.getElementById('context-menu').classList.remove('open');
            this.deselectNode();
            this.panWasDragging = false;
            if (e.button === 2 || e.pointerType !== 'mouse') {
                this.isPanning = true;
                this.panStartX = e.clientX;
                this.panStartY = e.clientY;
                this.panStartPX = this.panX;
                this.panStartPY = this.panY;
                this.workspace.style.cursor = 'grabbing';
                e.preventDefault();
            } else {
                closeSettings();
            }
        });

        document.addEventListener('pointermove', (e) => {
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

        document.addEventListener('pointerup', (e) => {
            if (this.isDragging && this.dragTarget) {
                this.saveState();
            }
            /* A pan moved the camera, not the model — but the camera is part of what the
               draft owes the user, and an ended pan is the one moment that knows the drag
               actually stopped. */
            if (this.isPanning && this.panWasDragging) {
                this.scheduleViewSave();
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
            /* 粘贴节点 is offered only when something is actually on the clipboard.
               The action itself refuses silently, so the item used to sit there on every
               canvas with nothing copied and do nothing when clicked — which reads as a
               broken menu rather than as "there is nothing to paste". */
            document.getElementById('ctx-paste-node').style.display = this._clipboardData ? 'block' : 'none';
            const foldItem = document.getElementById('ctx-fold-node');
            const typeItem = document.getElementById('ctx-toggle-type');
            if (node) {
                /* The element `closest()` answered with IS the node box; looking it up
                   by id again used to resolve to whatever page element shared that id
                   (see `_nodeEl`). */
                const folded = node.classList.contains('node-folded');
                foldItem.style.display = 'block';
                foldItem.textContent = folded ? I18n.t('canvas.unfold') : I18n.t('canvas.fold');
                foldItem.dataset.action = folded ? 'ctxUnfoldNode' : 'ctxFoldNode';
                /* Switching a node TYPE off is the one control no single node's header can
                   express — it takes every box of this kind out of the run at once. Offered on
                   any node, labelled by that node's type, and flipped by the same click. */
                const thisType = (this.nodes[node.id] || {}).type || '';
                const typeOff = (this.disabledTypes || []).indexOf(thisType) >= 0;
                const key = typeOff ? 'ctx.enableType' : 'ctx.disableType';
                typeItem.style.display = 'block';
                typeItem.textContent = I18n.t(key).replace('{type}', I18n.t('node.' + thisType));
            } else {
                foldItem.style.display = 'none';
                typeItem.style.display = 'none';
            }
            /* Clamped by what the menu actually is, not by a guessed 200 px: the
               language changes its width and folding an item changes its height, so a
               constant either leaves the menu off-screen or stops it far too early.
               Measured after the visibility decisions above, which is what sizes it. */
            ctxMenu.style.left = '0px';
            ctxMenu.style.top = '0px';
            const room = {
                x: Math.max(0, e.clientX),
                y: Math.max(0, e.clientY),
            };
            if (ctxMenu.offsetWidth && ctxMenu.offsetHeight) {
                room.x = Math.min(room.x, window.innerWidth - ctxMenu.offsetWidth - 8);
                room.y = Math.min(room.y, window.innerHeight - ctxMenu.offsetHeight - 8);
            }
            ctxMenu.style.left = Math.max(0, room.x) + 'px';
            ctxMenu.style.top = Math.max(0, room.y) + 'px';
            ctxMenu.classList.add('open');
            /* A switched-off type is not offered in the new-node menu: adding a box that the run
               will treat as absent is a dead control. Mapping the action to its type keeps the two
               halves of "type off" — disable existing nodes, and stop creating new ones — in one
               place, so they cannot drift apart. */
            const newTypeByAction = {
                ctxNewSource: 'source', ctxNewUpload: 'upload', ctxNewProcess: 'process',
                ctxNewAnalysis: 'analysis', ctxNewVisualize: 'visualize', ctxNewTokenize: 'tokenize',
                ctxNewOutput: 'output',
            };
            Object.keys(newTypeByAction).forEach((action) => {
                const el = ctxMenu.querySelector('[data-action="' + action + '"]');
                if (el) el.style.display = (this.disabledTypes || []).indexOf(newTypeByAction[action]) >= 0 ? 'none' : 'block';
            });
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
                            /* The params (and the copy's name) are written only AFTER addNode
                               has already run its own saveState of the freshly-minted defaults,
                               and updateNodeDisplay repaints the box's TEXT but not the
                               enable/disable shading, which disableStates computes on a full
                               render. So a paste has to re-render and re-save here, or the
                               copied node's enabled:false and edited title never reach the draft
                               and it comes back ENABLED (and unnamed) on the next load. This is
                               why a disabled 输出 node pasted back looking switched-on — though
                               the loss was never specific to that type: it was every params field
                               and the title, copied into a node that had already been saved. */
                            this.scheduleRender();
                            this.saveState();
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
                case 'ctxToggleType': {
                    if (this._contextNode) {
                        const t = (this.nodes[this._contextNode] || {}).type;
                        if (t) this.toggleTypeDisabled(t);
                    }
                    break;
                }
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
            /* The camera is part of what a draft (and later a saved file) owes the
               user, so a wheel-zoom that is never written back is a viewpoint that
               disappears on refresh. Debounced: a flick fires dozens of wheel events
               and each redraws nothing but a localStorage write. */
            this.scheduleViewSave();
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
            if (this._isTypingTarget(e.target)) return;
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

    /* Keys belong to the canvas only while the user is not typing.

       The guard used to name INPUT and SELECT, so every multi-line field in the app —
       the 推文链接 box of a WeChat source, the 表达式 of a 列计算, the paste field of the
       Cookie dialog — was unprotected: Backspace at the end of a URL deleted the
       SELECTED NODE (toast 「节点已删除」, panel closed) instead of one character, and
       typing an `f` (a URL, `pdf`, `if`) was swallowed by the fold shortcut. A node is
       cheap to create and expensive to lose mid-edit, so the exclusion is by what the
       element IS (a text editor of any kind) rather than by its tag name.
    */
    _isTypingTarget(target) {
        if (!target || !target.tagName) return false;
        const tag = String(target.tagName).toUpperCase();
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if (target.isContentEditable) return true;
        // CustomSelect draws its own focusable option list out of DIVs.
        return !!(target.closest && target.closest('.cselect, [contenteditable="true"]'));
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
        /* A stored coordinate of 0 is a position, not an absence — `x || random`
           used to re-roll any node whose saved x or y landed exactly on 0 (routine
           after 自动排布's centering), so reopening a workflow scattered the very
           layout the file had just recorded. Random is the fallback ONLY when no
           finite number was given. */
        el.style.left = (Number.isFinite(Number(x)) && x !== null && x !== '' ? Number(x) : 100 + Math.random() * 200) + 'px';
        el.style.top = (Number.isFinite(Number(y)) && y !== null && y !== '' ? Number(y) : 100 + Math.random() * 200) + 'px';
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
            '    <button class="node-power-btn" type="button">' + NODE_ICON.power + '</button>',
            '  </div>',
            '</div>',
            '<div class="node-state-badge"></div>',
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
        /* The enable/disable toggle is its own class, not a third .node-action-btn, so the
           settings/delete buttons keep the positions every caller and test assumes. */
        const powerBtn = el.querySelector('.node-power-btn');
        powerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleEnabled(id);
        });
        el.querySelector('.node-content').textContent = this.getNodeSummary(type, params);
        el.querySelectorAll('.node-port').forEach((port) => {
            port.dataset.node = id;
        });
        this.nodesContainer.appendChild(el);
        this.nodes[id] = { id: id, type: type, title: title, el: el, params: params, x: el.offsetLeft, y: el.offsetTop };
        /* A wire's `d` freezes LITERAL coordinates, while the port dot it must meet
           is CSS (`top:50%`) and follows the box forever. Boot proves the two drift
           apart twice over: the webfont lands after the first paint and grows every
           box, and CustomSelect collapses a node's raw <select> — rendered as an
           EXPANDED list until the next boot step enhances it — only after the
           font's own repaint. A resize fires no event, so the observer is the one
           notice the wires get. updateConnections runs DIRECTLY, not via
           scheduleRender: the callback lands after this frame's layout and before
           its paint, where the fresh measurements are guaranteed — a queued rAF
           could run before the next layout and re-measure the stale box again.
           Repaint only: a page that merely loaded must not become an undo step. */
        if (typeof ResizeObserver !== 'undefined') {
            this._nodeObserver = this._nodeObserver || new ResizeObserver(() => this.updateConnections());
            this._nodeObserver.observe(el);
        }

        /* Make draggable */
        const header = el.querySelector('.node-header');
        header.addEventListener('pointerdown', (e) => {
            if (e.target.closest('.node-actions')) return;
            e.preventDefault(); /* one gesture: stop the compatible mousedown/mousemove */
            this.isDragging = true;
            this.dragTarget = el;
            const rect = el.getBoundingClientRect();
            this.dragOffsetX = e.clientX - rect.left;
            this.dragOffsetY = e.clientY - rect.top;
            this.selectNode(id);
        });

        /* Port connection */
        el.querySelectorAll('.node-port').forEach(port => {
            port.addEventListener('pointerdown', (e) => {
                e.stopPropagation();
                e.preventDefault(); /* stop the compatible mouse events double-firing the wire */
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
        if (type === 'visualize') return { chart_type: 'bar', x_field: '', y_field: '', value_field: '', agg: 'sum', engine: 'echarts', title: '', tokenize: false, emit_latex: true, emit_latex_table: true };
        if (type === 'tokenize') return { text_column: '', top_n: '', output_mode: 'word_freq' };
        /* Empty run ids mean "auto": pick the newest interrupted run, and
           inside it whichever node holds the most rows. */
        if (type === 'resume') return { resume_run_id: '', resume_node_id: '', resume_limit: 0 };
        if (type === 'comment') return { urls: '', comment_limit: 0, part_size: 50, per_article_file: true, keep_parts: false, recrawl: false, format: 'csv' };
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
                if (String(options[i].value) === String(chosen)) {
                    // Empty labelKey = a user-typed account name: show the value as typed.
                    return label + ': ' + (options[i].labelKey ? I18n.t(options[i].labelKey) : options[i].value);
                }
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
                if (f.fedBy && String(params[f.fedBy] || '').trim()) {
                    /* Fed from a column: the pasted count would read 0 while the node
                       plans to crawl the whole table — the column it reads is the
                       honest line, and which fields can be fed is the matrix's
                       declaration (f.fedBy), not a list the card keeps by hand. */
                    lines.push(
                        I18n.t(f.labelKey) + ': ' +
                        I18n.t('summary.fedColumn').replace('{col}', String(params[f.fedBy]).trim())
                    );
                    return;
                }
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

    /* A node's element, taken through the node — never through `getElementById`.
       The id a workflow file carries becomes the DOM id of the box (`addNode` sets
       `el.id = id`), so a node whose id happens to be `status-zoom`, `svg-layer` or
       `chart-emotion` resolved to the PAGE element with that name: `deleteNode`
       removed a piece of the interface, `selectNode` highlighted something that is
       not a node, and the geometry reads measured it. `nodes[id].el` is the box this
       object created, which is the only thing these callers may touch. */
    _nodeEl(id) {
        const node = this.nodes[id];
        return node && node.el ? node.el : null;
    },

    deleteNode(id) {
        const el = this._nodeEl(id);
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
        const el = this._nodeEl(id);
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
            const nodeEl = this._nodeEl(this._settingsNodeId);
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

    async finishConnection(e) {
        /* The wire is written first and explained second: the user is not asked to
           pre-approve a shape, they are told what THIS engine will do with it and can
           take it back. `fromId` is captured before the await because `cancelConnection`
           (at the end) clears `connectingFrom`, and the undo must name the original edge. */
        const target = this._getPortAt(e.clientX, e.clientY);
        const fromId = this.connectingFrom;
        let toId = null;
        let warn = null;
        if (target && target.dataset.port === 'in') {
            toId = target.dataset.node;
            if (toId !== fromId) {
                const exists = this.connections.some(c => c.from === fromId && c.to === toId);
                if (!exists) {
                    this.connections.push({ from: fromId, to: toId });
                    this.scheduleRender();
                    this.saveState();
                    showToast(I18n.t('toast.connCreated'));
                    // Tokenize ↔ Visualize: force word_freq + refresh settings
                    var nA = this.nodes[fromId];
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
                    warn = this.classifyConnection(fromId, toId);
                }
            }
        }
        this.cancelConnection();
        if (warn && !this._connWarningsDismissed.has(warn.category)) {
            const keep = await this._warnConnection(fromId, toId, warn);
            if (!keep) this._undoConnection(fromId, toId);
        }
    },

    cancelConnection() {
        this.connectingFrom = null;
        if (this.tempLine) { this.tempLine.remove(); this.tempLine = null; }
    },

    /* How THIS engine treats the wire that was just drawn, so the user learns the
       consequence at the moment they cause it rather than after a wasted run. The
       wording mirrors the executor; the numbers are read off the canvas's own flat
       connection list (there is no adjacency table). A wire to a `source` deliberately
       does NOT ask whether that mode can be fed from upstream — deciding that is the
       backend's single job (a canvas must not hold a second opinion about a crawl), so
       one sentence covers both the fed and the non-feedable outcome.

       A wire counts as fan-in only at the target that actually consumes data
       differently when a SECOND parent appears; `name`, `upload`, `comment` and
       `resume` warn from the FIRST parent in, because that first parent is already
       refused (`name`) or already ignored (the other three). */
    classifyConnection(fromId, toId) {
        const from = this.nodes[fromId];
        const to = this.nodes[toId];
        if (!from || !to) return null;
        let inDeg = 0;
        let outDeg = 0;
        for (const c of this.connections) {
            if (c.to === toId) inDeg += 1;
            if (c.from === fromId) outDeg += 1;
        }
        const nameOf = (id) => {
            const n = this.nodes[id] || {};
            return n.title || I18n.t('node.' + n.type);
        };
        const t = to.type;
        if (t === 'name') {
            return { category: 'fanin_name', i18nKey: 'conn.fanin.name', vars: { node: nameOf(toId) } };
        }
        if (t === 'upload' || t === 'comment' || t === 'resume') {
            return { category: 'fanin_ignore', i18nKey: 'conn.fanin.ignore', vars: { node: nameOf(toId) } };
        }
        // Not a data-consuming fan-in yet — the only thing left to explain is the first
        // branch OUT. A second branch off the same node is still one snapshot to all.
        if (inDeg < 2) {
            if (outDeg === 2) {
                return { category: 'fan_out', i18nKey: 'conn.fanout', vars: { node: nameOf(fromId), count: String(outDeg) } };
            }
            return null;
        }
        if (t === 'process' || t === 'tokenize' || t === 'visualize') {
            return { category: 'fanin_first', i18nKey: 'conn.fanin.first', vars: { node: nameOf(toId) } };
        }
        if (t === 'source') {
            return { category: 'fanin_source', i18nKey: 'conn.fanin.source', vars: { node: nameOf(toId) } };
        }
        if (t === 'analysis') {
            return { category: 'fanin_analysis', i18nKey: 'conn.fanin.analysis', vars: { node: nameOf(toId) } };
        }
        if (t === 'output') {
            return { category: 'fanin_merge', i18nKey: 'conn.fanin.merge', vars: { node: nameOf(toId) } };
        }
        return null;
    },

    /* One wire, one dialog. The connection already exists; this explains it and offers
       to take it back. The dismiss checkbox is keyed per category, so silencing the
       merge notice does not also silence the ignored-upstream one. Cancelling out
       (X / backdrop / Esc) keeps the wire: this is information, not a deletion prompt. */
    async _warnConnection(fromId, toId, warn) {
        const toggleId = 'conn_dismiss_' + warn.category;
        const answer = await showDialog({
            message: I18n.t(warn.i18nKey, warn.vars) + ' ' + I18n.t('conn.help'),
            toggles: [{ id: toggleId, label: I18n.t('conn.dismiss'), checked: false }],
            buttons: [
                { label: I18n.t('conn.undo'), value: false, collect: true },
                { label: I18n.t('conn.keep'), value: true, collect: true, primary: true },
            ],
            cancelValue: true,
        });
        if (answer && typeof answer === 'object' && answer.toggles && answer.toggles[toggleId]) {
            this._connWarningsDismissed.add(warn.category);
        }
        if (answer && typeof answer === 'object') return answer.value !== false;
        return answer !== false;
    },

    _undoConnection(fromId, toId) {
        const idx = this.connections.findIndex(c => c.from === fromId && c.to === toId);
        if (idx < 0) return;
        this.connections.splice(idx, 1);
        this.scheduleRender();
        this.saveState();
        showToast(I18n.t('toast.connRemoved'));
    },

    scheduleRender() {
        if (this._renderPending) return;
        this._renderPending = true;
        requestAnimationFrame(() => {
            this._renderPending = false;
            this.updateConnections();
            this.applyDisabledVisuals();
        });
    },

    updateConnections() {
        this.svgLayer.querySelectorAll('.conn-line:not(.temp)').forEach(l => l.remove());
        this.svgLayer.querySelectorAll('.conn-delete-hit').forEach(l => l.remove());
        // A wire that feeds a node the run will not see reads faint, so "disconnected by a
        // disable" is visible without deleting what the user drew.
        const states = this.disableStates();
        this.connections.forEach((conn, idx) => {
            const fromPort = document.querySelector('[data-node="' + conn.from + '"][data-port="out"]');
            const toPort = document.querySelector('[data-node="' + conn.to + '"][data-port="in"]');
            if (!fromPort || !toPort) return;
            const from = this._getPortCenter(fromPort);
            const to = this._getPortCenter(toPort);
            if (from.x == null || to.x == null) return;
            const dx = to.x - from.x;
            const dy = to.y - from.y;
            const cp1x = from.x + Math.abs(dx) * 0.5;
            const cp2x = to.x - Math.abs(dx) * 0.5;
            /* Straight where the geometry is straight, curved only where it cannot be:
               aligned ports and a forward hop draw a flat line; fan-out/fan-in branches
               (different centrelines), back-edges and user-dragged slopes keep the cubic,
               whose control points bulge outward precisely to sweep around the boxes. */
            const d = (Math.abs(dy) <= WIRE_ALIGN_EPS && dx > WIRE_ALIGN_EPS)
                ? ['M', from.x, from.y, 'L', to.x, from.y].join(' ')
                : ['M', from.x, from.y, 'C', cp1x, from.y, ',', cp2x, to.y, to.x, to.y].join(' ');

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.classList.add('conn-line');
            if (states[conn.from] !== 'on' || states[conn.to] !== 'on') path.classList.add('conn-disabled');
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
        this.scheduleViewSave();
    },

    zoomOut() {
        this.zoom = Math.max(0.2, this.zoom / 1.2);
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
        this.scheduleViewSave();
    },

    resetView() {
        /* 适应: fit EVERY node into the VISIBLE box, not just centre the mean. The
           old behaviour pinned zoom to 100%, so a chain that autoLayout spreads
           past the window left nodes off-screen — '适应' hid them instead of
           revealing them. Zoom only ever shrinks here (max 1), so a graph that
           already fits is re-centred at its own size and no node looms larger
           than the user left it. The box is the workspace's own client rect, NOT
           window.innerWidth: the canvas sits inside the app chrome, so the two
           disagree (measured 1344x670 vs 1920x1080) and fitting to the larger
           number leaves the cluster spilling past the real right/bottom edge.
           The TOP of that box is the menu bar, not the workspace: a pinned/hovered
           #top-menu overlays its height, so the top inset is menu height + margin —
           the cluster sits below the bar and there is more air above it, exactly
           when 100% cannot hold it. */
        const ids = Object.keys(this.nodes);
        const vp = this.workspace || {};
        const vw = vp.clientWidth || window.innerWidth;
        const vh = vp.clientHeight || window.innerHeight;
        const menu = document.getElementById('top-menu');
        const topInset = (menu ? menu.offsetHeight : 0) + VIEW_FIT_MARGIN;
        if (ids.length === 0) {
            this.panX = 0;
            this.panY = 0;
            this.zoom = 1;
            this.updateTransform();
            document.getElementById('status-zoom').textContent = '100%';
            this.scheduleViewSave();
            return;
        }
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            minX = Math.min(minX, el.offsetLeft);
            minY = Math.min(minY, el.offsetTop);
            maxX = Math.max(maxX, el.offsetLeft + el.offsetWidth);
            maxY = Math.max(maxY, el.offsetTop + el.offsetHeight);
        });
        const contentW = Math.max(1, maxX - minX);
        const contentH = Math.max(1, maxY - minY);
        const availW = Math.max(1, vw - 2 * VIEW_FIT_MARGIN);
        const availH = Math.max(1, vh - topInset - VIEW_FIT_MARGIN);
        const fit = Math.min(availW / contentW, availH / contentH);
        this.zoom = Math.max(0.2, Math.min(1, fit));
        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;
        this.panX = vw / 2 - cx * this.zoom;
        /* Centre inside the band the menu does NOT cover, not inside the whole
           height — so the top margin is (menu + VIEW_FIT_MARGIN), never 0. */
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this.panY = bandCentreY - cy * this.zoom;
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
        this.scheduleViewSave();
    },

    /* ---- State ---- */

    /* The camera. It is deliberately NOT inside getState(): that dict is also one
       undo step, and rewinding an accidental node deletion must not also jump the
       viewport somewhere the user never undid. The draft carries it beside the
       model, and a saved file carries it in settings — "this is the view the
       workflow was arranged in". */
    _viewState() {
        return { panX: this.panX, panY: this.panY, zoom: this.zoom };
    },

    _applyView(view) {
        if (!view || typeof view !== 'object') return;
        const parts = [
            ['panX', view.panX, -Infinity, Infinity],
            ['panY', view.panY, -Infinity, Infinity],
            ['zoom', view.zoom, 0.2, 3],
        ];
        parts.forEach(([key, raw, min, max]) => {
            const value = Number(raw);
            if (Number.isFinite(value)) this[key] = Math.max(min, Math.min(max, value));
        });
        this.updateTransform();
        document.getElementById('status-zoom').textContent = Math.round(this.zoom * 100) + '%';
    },

    /* Pan/zoom redraw at most once per gesture-trickle: a wheel flick fires dozens
       of events, and each would otherwise pay a synchronous localStorage write. */
    scheduleViewSave() {
        if (this._viewSaveTimer) return;
        this._viewSaveTimer = setTimeout(() => {
            this._viewSaveTimer = null;
            this.saveState();
        }, 400);
    },

    serializeDraft() {
        return Object.assign(this.getState(), { view: this._viewState() });
    },

    getState() {
        const nodes = {};
        Object.keys(this.nodes).forEach(id => {
            const n = this.nodes[id];
            const el = this._nodeEl(id);
            nodes[id] = {
                id: id, type: n.type, title: n.title,
                /* A snapshot must be a snapshot. Handing out the live object made
                   every history entry alias `node.params`, and updateParam mutates
                   that dict in place — so no parameter edit was undoable anywhere in
                   the app (Ctrl+Z gave back the value you had just typed), and a
                   later edit silently rewrote the PAST entries too. */
                params: JSON.parse(JSON.stringify(n.params || {})),
                x: el ? parseInt(el.style.left) : n.x,
                y: el ? parseInt(el.style.top) : n.y,
                /* A folded node is a layout the user chose, and toggleFold already
                   pays for a save — which used to write a draft with no fold in it,
                   so a reload quietly unfolded everything. */
                folded: el ? el.classList.contains('node-folded') : false,
            };
        });
        return {
            nodes: nodes,
            connections: this.connections,
            nextId: this.nextId,
            disabledTypes: (this.disabledTypes || []).slice(),
        };
    },

    restoreState(state) {
        /* A restore is ONE undo point, not one per node.

           addNode() saves a snapshot on its own (correct for a drag-and-drop, which is
           one user action), so loading a draft or running a history step used to push
           an entry for every node in it — a five-node draft opened the page with six
           snapshots, and the first six Ctrl+Z deleted nodes the user had not added in
           this session. The flag suppresses the per-node pushes; the single
           `_pushState` at the end is the whole restore. */
        const outerSaving = this._historySaving;
        this._historySaving = true;
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
        this.disabledTypes = Array.isArray(state.disabledTypes) ? state.disabledTypes.slice() : [];
        /* A draft carries the camera the user was looking through; an UNDO state
           never does (getState is view-free), so rewinding a step rearranges nodes
           without yanking the viewport — and a restore of a view-less draft leaves
           the camera exactly where it is. Applied before the save below, so the
           draft keeps the view it was handed rather than a stale one. */
        if (state.view) this._applyView(state.view);
        this.scheduleRender();
        this._historySaving = outerSaving;
        if (!outerSaving) {
            /* The one snapshot this restore is worth, taken AFTER the flag is back
               down — while it is up, saveState() declines to record anything. */
            this.saveState();
        }
    },

    /* ── Undo / Redo ── */
    _pushState() {
        if (this._historySaving) return;
        const state = this.getState();
        /* An identical state is not a step. app.js autosaves every 30 seconds and
           init() used to push once per restored node, so the 50-deep stack filled up
           with copies of "now": after ~25 idle minutes every real edit had been
           shifted out and Ctrl+Z did nothing at all, while the first undos after
           opening a draft deleted nodes the user had not added in that session. */
        if (this._history.length && this._historyIdx >= 0) {
            const current = this._history[this._historyIdx];
            if (JSON.stringify(current) === JSON.stringify(state)) return;
        }
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
            const el = this._nodeEl(id);
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
        const el = this._nodeEl(id);
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
        localStorage.setItem('crawler_canvas', JSON.stringify(this.serializeDraft()));
        this._pushState();
    },

    updateStatus() {
        const count = Object.keys(this.nodes).length;
        document.getElementById('status-nodes').textContent = I18n.t('status.nodes') + count;
    },

    /* ── Enable / disable ── */
    /* A canvas-local mirror of the backend's effective graph, used ONLY for grey-out and for
       naming the run; it must agree with engine.workflow.effective_workflow, because the record
       the browser looks up is keyed by that same effective name. A node is OFF if its own switch
       or its type is switched off; it is STARVED if it is on but has at least one upstream and
       none of those upstreams are alive. Starvation cascades, so switching off a workflow's head
       node greys the whole chain — which is exactly why there is no separate "disable workflow"
       control: it is just disabling the first box. */
    _nodeDirectlyOn(id) {
        const n = this.nodes[id];
        if (!n) return false;
        return (n.params || {}).enabled !== false;
    },

    _typeOn(type) {
        return (this.disabledTypes || []).indexOf(type) < 0;
    },

    /* { id: 'on' | 'off' | 'starved' } for every node on the canvas. */
    disableStates() {
        const ids = Object.keys(this.nodes);
        const upstream = {};
        ids.forEach((id) => { upstream[id] = []; });
        this.connections.forEach((c) => {
            if (this.nodes[c.from] && this.nodes[c.to] && upstream[c.to]) upstream[c.to].push(c.from);
        });
        const alive = {};
        ids.forEach((id) => { alive[id] = this._nodeDirectlyOn(id) && this._typeOn(this.nodes[id].type); });
        let changed = true;
        while (changed) {
            changed = false;
            ids.forEach((id) => {
                if (!alive[id]) return;
                const parents = upstream[id];
                if (parents.length && !parents.some((p) => alive[p])) { alive[id] = false; changed = true; }
            });
        }
        const states = {};
        ids.forEach((id) => {
            if (!alive[id]) {
                states[id] = this._nodeDirectlyOn(id) && this._typeOn(this.nodes[id].type) ? 'starved' : 'off';
            } else {
                states[id] = 'on';
            }
        });
        return states;
    },

    /* The ids that take part in a run — the same set the backend computes. */
    effectiveIds() {
        const states = this.disableStates();
        return Object.keys(states).filter((id) => states[id] === 'on');
    },

    toggleEnabled(id) {
        const n = this.nodes[id];
        if (!n) return;
        n.params = n.params || {};
        n.params.enabled = n.params.enabled === false;
        this.saveState();
        this.scheduleRender();
        if (this._settingsNodeId === id) openSettings(id);
    },

    /* Switch a whole node type off (and back on). Off = every box of this kind is out of the run
       and the type cannot be added again from the new-node menu; on = each node returns to its OWN
       switch, because the type toggle never edits params.enabled. */
    toggleTypeDisabled(type) {
        const list = this.disabledTypes || (this.disabledTypes = []);
        const i = list.indexOf(type);
        if (i >= 0) list.splice(i, 1);
        else list.push(type);
        this.saveState();
        this.scheduleRender();
    },

    applyDisabledVisuals() {
        const states = this.disableStates();
        Object.keys(this.nodes).forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const state = states[id];
            el.classList.toggle('node-off', state === 'off');
            el.classList.toggle('node-starved', state === 'starved');
            const btn = el.querySelector('.node-power-btn');
            if (btn) {
                const on = state === 'on';
                btn.classList.toggle('power-off', !on);
                btn.title = I18n.t(on ? 'ctx.disableNode' : 'ctx.enableNode');
            }
            const badge = el.querySelector('.node-state-badge');
            if (badge) {
                badge.textContent = state === 'off'
                    ? I18n.t('node.badgeDisabled')
                    : state === 'starved'
                        ? I18n.t('node.badgeNoInput')
                        : '';
                badge.style.display = state === 'on' ? 'none' : '';
            }
        });
    },

    /* ── Node fold / unfold ── */
    /* Shared with restoreState: a fold is two style writes plus a class, and a
       second copy would drift the moment one of the three changed. */
    _setFolded(id, folded) {
        const el = this._nodeEl(id);
        if (!el) return false;
        el.classList.toggle('node-folded', !!folded);
        const content = el.querySelector('.node-content');
        const actions = el.querySelector('.node-actions');
        if (content) content.style.display = folded ? 'none' : '';
        if (actions) actions.style.display = folded ? 'none' : '';
        return true;
    },

    toggleFold(id) {
        const el = this._nodeEl(id);
        if (!el) return;
        const folded = !el.classList.contains('node-folded');
        if (!this._setFolded(id, folded)) return;
        this.scheduleRender();
        this.saveState();
    },

    /* ── Auto-layout: topological ranks sized by the REAL boxes ── */
    autoLayout() {
        /* The old fixed 280×120 lattice laid nodes out as if every box were that size.
           .node grows to max-width 340 with content, and .node-content wraps a link list
           into ever more height — so wide/tall nodes bled into the next rank and the one
           below, and the equal-TOPS rule put port centres (each at its own half-height)
           on different lines, which is what bowed the wires. Everything below advances by
           the measured offsetWidth/offsetHeight of the rendered box, and a rank of one
           node sits CENTRED on the shared local line so a plain chain draws flat.
           A folded node measures 32 tall, so fold-awareness comes for free. */
        const SP_X = 120;   // edge-to-edge between neighbouring ranks (a GAP, not a stride)
        const SP_Y = 60;    // gap between stacked nodes inside one rank

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

            /* Measure the boxes once; a node not on screen reports 0 and falls back
               to a mid-size box rather than collapsing the rank against its neighbour. */
            const size = {};
            comp.forEach(function (nid) {
                const el = this._nodeEl(nid);
                size[nid] = { w: (el && el.offsetWidth) || 240, h: (el && el.offsetHeight) || 80 };
            }, this);

            /* Compute node positions for this component: each rank advances by its WIDEST
               measured box, and each rank's stacked block is centred on the shared local
               line 0 (a single-node rank sits exactly on it — equal CENTRES, not tops). */
            const positions = [];
            let rankX = 0;
            levels.forEach(function (level) {
                let blockH = 0;
                level.forEach(function (nid) { blockH += size[nid].h + SP_Y; });
                blockH -= SP_Y;
                let y = -blockH / 2;
                let maxW = 0;
                level.forEach(function (nid) {
                    positions.push({ id: nid, x: rankX, y: y });
                    y += size[nid].h + SP_Y;
                    if (size[nid].w > maxW) maxW = size[nid].w;
                });
                rankX += maxW + SP_X;
            });

            /* Find component's actual top and bottom edges in local coords */
            let compTop = Infinity, compBottom = -Infinity;
            positions.forEach((p) => {
                const el = this._nodeEl(p.id);
                const h = (el && el.offsetHeight) || 80;
                if (p.y < compTop) compTop = p.y;
                if (p.y + h > compBottom) compBottom = p.y + h;
            });

            /* Shift so the top edge aligns with cursorY */
            const shift = cursorY - compTop;

            positions.forEach((p) => {
                const el = this._nodeEl(p.id);
                if (!el) return;
                allPositions.push({ id: p.id, x: p.x, y: p.y + shift });
            });

            cursorY = compBottom + shift + compGap;
        }, this);

        allPositions.forEach((p) => {
            const el = this._nodeEl(p.id);
            if (el) {
                /* Positions land in rank-local coordinates rounded to whole pixels;
                   the camera fit below reads these boxes and pans/zooms so the whole
                   relayout is on screen at once. */
                el.style.left = Math.round(p.x) + 'px';
                el.style.top = Math.round(p.y) + 'px';
            }
        });
        this.scheduleRender();
        this.saveState();
        /* autoLayout is 重新排布 + 适应: after moving the nodes it hands the camera to
           resetView, the same rule the 适应 button uses (measured workspace box, a
           shrink-only zoom, top clearance for the menu bar). Keeping one fit routine
           means a relayout and a 适应 press can never disagree about "everything visible". */
        this.resetView();
        showToast(I18n.t('toast.layoutApplied'));
    },

    toWorkflowJSON() {
        const nodes = [];
        Object.keys(this.nodes).forEach(id => {
            const n = this.nodes[id];
            const el = this._nodeEl(id);
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
                disabledTypes: (this.disabledTypes || []).slice(),
                /* The file owes the user the VIEW it was saved behind: 适应/自动排布
                   arranged the camera as much as the nodes, and a saved workflow that
                   drops it opens at a viewport its author never chose. */
                view: this._viewState(),
            },
        };
    },
};
