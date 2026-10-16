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

/* The camera glide for 适应 (resetView) and the outline's jump-to-node. The final
   pan/zoom is committed to state synchronously (so the math and the tests read it at
   once); only the RENDERED transform is eased, via a CSS transition on #canvas-inner,
   from whatever was on screen to that target. Any manual gesture clears it so a
   wheel/pan never rubber-bands behind the state. */
const VIEW_ANIM_MS = 280;
const VIEW_ANIM_EASE = 'cubic-bezier(0.22, 0.61, 0.36, 1)';

/* The overview minimap: a fixed-size corner box that shows every node as a proportional
   rectangle plus a viewport indicator. Clicking it re-centres the camera on that spot (a
   view change only — never an undo step). The math is pure (bounds/scale/click→world) so a
   harness can assert it without a rendered canvas; only the string it writes into #minimap's
   innerHTML is browser-only. */
const MINIMAP_SIZE = 176;
const MINIMAP_PAD = 10;

const canvas = {
    nodes: {},
    connections: [],
    /* Node types the user has switched off for the whole canvas (e.g. ['source']). A node of one
       of these types is disabled, and so is anything that loses its last live input — the canvas
       mirrors the backend's effective graph (:func:`effective_workflow`) ONLY to grey the boxes
       and to name the run; what actually executes stays the backend's decision. */
    disabledTypes: [],
    selectedNode: null,
    /* The selected set. selectedNode stays as the ANCHOR (the last node touched) so every
       single-selection caller (panel, copy, outline) keeps working; selectedNodes is the full
       group for shift-click / marquee batch operations. Selection is view-only — it never
       enters getState()/history — so a multi-select is not an undo step. */
    selectedNodes: [],
    nextId: 1,
    panX: 0,
    panY: 0,
    zoom: 1,
    isDragging: false,
    isPanning: false,
    /* A drag moves the whole selected group as one, so the press snapshots every member's
       start position and the origin of the grabbed box; pointermove shifts each by the delta.
       Cleared on pointerup. (Selection is view-only, but the drag must know what it grabbed.) */
    _dragGroup: null,
    _dragOriginX: 0,
    _dragOriginY: 0,
    panStartPX: 0,
    panStartPY: 0,
    panWasDragging: false,
    /* Multi-touch (tablet/phone) gesture bookkeeping. Only touch & pen pointers are
       recorded here: one finger pans like before, a second turns the pair into a pinch
       (spread/close = zoom, slide = pan). A mouse never enters this map, so the desktop
       right-drag and wheel paths are untouched. */
    _panPointers: {},
    _pinchBase: null,
    _gestureMoved: false,
    /* The in-flight camera glide: the timer that removes the CSS transition when the
       ease ends, and a flag so a manual gesture can tell whether one needs cancelling. */
    _viewAnim: null,
    _viewAnimating: false,
    /* Wheel-stream bookkeeping for the three-role split (pan / pinch / mouse wheel). A
       single wheel event on Windows/Chrome cannot always tell a trackpad vertical scroll
       from a mouse notch (both are pure-vertical integer deltas), so the classifier
       looks at the STREAM: any event carrying a horizontal delta, a fractional value, or
       a delta that differs from the previous event within the same burst is proof of a
       trackpad — and the whole burst then pans until it goes quiet. A burst whose events
       are all pure-vertical integer constants with no history is treated as a mouse
       wheel and zooms. This makes 双指平移 / 双指捏合 / 鼠标滚轮 independent roles. */
    _lastWheelAt: 0,
    _lastWheelDeltaY: 0,
    _wheelStreamTrackpad: false,
    dragTarget: null,
    dragOffsetX: 0,
    dragOffsetY: 0,
    _contextNode: null,
    _contextMenuPos: null,
    _clipboardData: null,
    _clipboardNodes: null,
    _settingsNodeId: null,
    connectingFrom: null,
    /* The node whose "wire start" the keyboard link mode is holding, waiting for a second
       selected node to complete the edge. View-only, never in getState/history. */
    _linkFromId: null,
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
    /* ── Unsaved-changes flag ── */
    /* dirty = the model differs from the state that was last saved to (or loaded from) a
       file. `_cleanState` is the JSON of getState() at that point; null means "no file
       baseline yet" — a brand-new draft, where anything with nodes counts as unsaved.
       Comparison is against getState() (which EXCLUDES the camera), so panning never
       makes the canvas dirty — only real model edits do. */
    dirty: false,
    _cleanState: null,

    init() {
        this.container = document.getElementById('canvas-inner');
        this.svgLayer = document.getElementById('svg-layer');
        this.nodesContainer = document.getElementById('nodes-container');
        this.workspace = document.getElementById('workspace');
        this.setupEvents();
        /* The minimap is a fixed corner box in the page markup; a click re-centres the
           camera on the spot clicked. It is a view change only (never an undo step). */
        const minimap = document.getElementById('minimap');
        if (minimap && minimap.addEventListener) {
            minimap.addEventListener('pointerdown', (e) => this.onMinimapClick(e));
        }
        /* The clipboard drawer: load the persisted history, draw it, and wire its two
           input surfaces (a delegated row-action click and the filter box). Guarded so a
           canvas-only harness without the drawer markup still initialises. */
        try {
            Clipboard.load();
            Clipboard.render();
            const drawer = document.getElementById('clipboard-drawer');
            if (drawer && drawer.addEventListener) {
                drawer.addEventListener('click', (e) => Clipboard.onAction(e));
                /* Delegated dragstart (rows are innerHTML, so no per-node listener survives
                   a re-render): a node/nodes row hands its id to the workspace drop under a
                   private type; a text row drags nothing onto the canvas. */
                drawer.addEventListener('dragstart', (e) => {
                    if (!e.dataTransfer || !e.target || !e.target.closest) return;
                    const row = e.target.closest('[data-clip-id]');
                    if (!row) return;
                    const it = Clipboard.get(row.dataset.clipId);
                    if (!it || (it.kind !== 'node' && it.kind !== 'nodes')) return;
                    e.dataTransfer.setData('application/x-canvas-clip', it.id);
                    e.dataTransfer.effectAllowed = 'copy';
                });
            }
            const clipSearch = document.getElementById('clipboard-search');
            if (clipSearch && clipSearch.addEventListener) {
                clipSearch.addEventListener('input', (e) => Clipboard.setQuery(e.target.value));
            }
            if (typeof window !== 'undefined' && window.addEventListener) {
                window.addEventListener('storage', (e) => Clipboard.onStorageEvent(e));
            }
        } catch (e) { /* a clipboard failure must never take down the canvas boot */ }
        /* Help overlay: a click on the dimmed backdrop (not the sheet itself) closes it. */
        try {
            const helpOverlay = document.getElementById('help-overlay');
            if (helpOverlay && helpOverlay.addEventListener) {
                helpOverlay.addEventListener('click', (e) => {
                    if (e.target === helpOverlay) closeShortcutsHelp();
                });
            }
        } catch (e) { /* the cheat sheet is optional chrome, never a boot blocker */ }
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
        /* Boot starts from an empty file baseline: a restored draft that already holds nodes
           is unsaved work (dirty) unless reloadOpenFile immediately re-syncs it to a file. */
        this._cleanState = null;
        this._refreshDirty();
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
            this._clearViewAnim(); /* grabbing the surface ends any camera glide first */
            if (e.button === 2 || e.pointerType !== 'mouse') {
                /* A touch/pen press may become a pinch, so record this pointer by id;
                   a second finger then drives zoom. A mouse right-drag stays pan-only
                   (never added), leaving the single-pointer baseline below intact. */
                if (e.pointerType === 'touch' || e.pointerType === 'pen') {
                    this._panPointers[e.pointerId] = { x: e.clientX, y: e.clientY };
                    /* Capture the pinch base at the two fingers' first positions — the
                       instant the second lands — so a single spread already reads as zoom,
                       and the base never drifts with the first move. */
                    const active = Object.keys(this._panPointers).length;
                    if (active === 2) {
                        const p = Object.values(this._panPointers);
                        this._pinchBase = {
                            dist: Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y),
                            midX: (p[0].x + p[1].x) / 2,
                            midY: (p[0].y + p[1].y) / 2,
                            zoom: this.zoom,
                            panX: this.panX,
                            panY: this.panY,
                        };
                    }
                }
                this.isPanning = true;
                this.panStartX = e.clientX;
                this.panStartY = e.clientY;
                this.panStartPX = this.panX;
                this.panStartPY = this.panY;
                this.workspace.style.cursor = 'grabbing';
                e.preventDefault();
            } else {
                closeSettings();
                /* A left-drag on the empty surface draws a selection marquee (a click that never
                   moved just deselects, as before). Isolated listeners so it never rides the
                   pan/pinch path. */
                this._startMarquee(e);
            }
        });

        document.addEventListener('pointermove', (e) => {
            if (e.pointerId in this._panPointers) {
                this._panPointers[e.pointerId] = { x: e.clientX, y: e.clientY };
            }
            const panPointerCount = Object.keys(this._panPointers).length;
            if (this.isPanning && panPointerCount >= 2) {
                /* Two or more fingers on the background: pinch-zoom + two-finger pan. */
                this._applyPinch();
                this.panWasDragging = true;
                this._gestureMoved = true;
            } else if (this.isPanning) {
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
                if (this._dragGroup && this._dragGroup.length > 1) {
                    /* A multi-select drags as one: every selected box moves by the grabbed box's
                       delta from where it started, so their relative layout survives. */
                    const dx = x - this._dragOriginX;
                    const dy = y - this._dragOriginY;
                    this._dragGroup.forEach((m) => {
                        const nx = m.x + dx;
                        const ny = m.y + dy;
                        m.el.style.left = nx + 'px';
                        m.el.style.top = ny + 'px';
                        if (this.nodes[m.id]) {
                            this.nodes[m.id].x = nx;
                            this.nodes[m.id].y = ny;
                        }
                    });
                } else {
                    this.dragTarget.style.left = x + 'px';
                    this.dragTarget.style.top = y + 'px';
                }
                this.scheduleRender();
            }
            if (this.connectingFrom) {
                this.updateTempLine(e);
            }
        });

        /* A pan/pinch moves the camera, not the model — but the camera is part of what the
           draft owes the user, and an ended gesture is the one moment that knows the drag
           actually moved something. Shared by pointerup and pointercancel so a finger that
           leaves the page cannot strand the pan in a half-claimed state. */
        const endPanPointer = (e) => {
            delete this._panPointers[e.pointerId];
            const left = Object.keys(this._panPointers).length;
            if (left < 2) {
                this._pinchBase = null;
            }
            if (this.isPanning && (this.panWasDragging || this._gestureMoved)) {
                this.scheduleViewSave();
            }
            if (left === 0) {
                this.isPanning = false;
                this.workspace.style.cursor = 'default';
                this._gestureMoved = false;
                /* panWasDragging is NOT cleared here: the contextmenu handler reads it to
                   suppress a menu that would otherwise pop right after a pan/pinch (the
                   user was moving the page, not asking for a menu). It resets on the next
                   pointerdown and on the suppressed contextmenu itself. */
            } else {
                /* One finger is still down after a pinch collapsed: re-anchor the plain
                   pan to it, so continuing that finger does not teleport the canvas. */
                const remain = Object.values(this._panPointers)[0];
                if (remain) {
                    this.panStartX = remain.x;
                    this.panStartY = remain.y;
                    this.panStartPX = this.panX;
                    this.panStartPY = this.panY;
                }
            }
        };

        document.addEventListener('pointerup', (e) => {
            if (this.isDragging && this.dragTarget) {
                this.saveState();
            }
            endPanPointer(e);
            this.isDragging = false;
            this.dragTarget = null;
            this._dragGroup = null;
            if (this.connectingFrom) {
                this.finishConnection(e);
            }
        });

        document.addEventListener('pointercancel', endPanPointer);

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
            document.getElementById('ctx-copy-json').style.display = node ? 'block' : 'none';
            document.getElementById('ctx-delete-node').style.display = node ? 'block' : 'none';
            /* 粘贴节点 is offered only when something is actually on the clipboard.
               The action itself refuses silently, so the item used to sit there on every
               canvas with nothing copied and do nothing when clicked — which reads as a
               broken menu rather than as "there is nothing to paste". "Something copied" is
               BOTH clipboard shapes: a single node lives on _clipboardData, a multi-select
               copy on _clipboardNodes (and clears _clipboardData), so the check must mirror
               the paste door (_pasteAt) — the item once checked only _clipboardData and so
               hid itself right after a batch copy that pasted perfectly well by Ctrl+V. */
            const pasteable = !!this._clipboardData || !!(this._clipboardNodes && this._clipboardNodes.length);
            document.getElementById('ctx-paste-node').style.display = pasteable ? 'block' : 'none';
            /* Import-from-JSON always applies: it takes its payload from the dialog, not the
               in-canvas clipboard, so an empty clipboard must still leave it offered. */
            document.getElementById('ctx-import-json').style.display = 'block';
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
                ctxNewOutput: 'output', ctxNewCompile: 'compile',
            };
            Object.keys(newTypeByAction).forEach((action) => {
                const el = ctxMenu.querySelector('[data-action="' + action + '"]');
                if (el) el.style.display = (this.disabledTypes || []).indexOf(newTypeByAction[action]) >= 0 ? 'none' : 'block';
            });
            /* Align/distribute only makes sense with a group to align; the same >=2 rule the
               copy-menu uses (464). Hidden otherwise so a single-node right-click stays clean. */
            const multi = this.selectedNodes.length > 1;
            const alignDivider = document.getElementById('ctx-align-divider');
            if (alignDivider) alignDivider.style.display = multi ? 'block' : 'none';
            ctxMenu.querySelectorAll('.ctx-align').forEach((el) => {
                el.style.display = multi ? 'block' : 'none';
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
                case 'ctxNewCompile':
                case 'ctxNewOutput': {
                    const pos = this._contextMenuPos
                        ? this._screenToCanvas(this._contextMenuPos.x - 110, this._contextMenuPos.y - 40)
                        : { x: 50 + Math.random() * 200, y: 50 + Math.random() * 200 };
                    const typeMap = {
                        ctxNewSource: 'source', ctxNewUpload: 'upload',
                        ctxNewProcess: 'process',
                        ctxNewAnalysis: 'analysis', ctxNewVisualize: 'visualize',
                        ctxNewTokenize: 'tokenize',
                        ctxNewCompile: 'compile',
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
                        /* A copy from the menu on a node that is part of a live multi-selection
                           copies the whole group — same path as Ctrl+C, so the two doors agree. */
                        if (this.selectedNodes.length > 1 && this.selectedNodes.indexOf(this._contextNode) >= 0) {
                            this.copySelection();
                        } else {
                            this.copyNodeToClipboard(this._contextNode);
                        }
                    }
                    break;
                case 'ctxCopyJson':
                    if (this._contextNode) this.copyNodeAsJson(this._contextNode);
                    break;
                case 'ctxPasteNode':
                    /* The menu pastes at the click hotspot (canvas space, menu offsets the
                       hotspot); the keyboard route passes no pos and _nextPastePos cascades off
                       the selected node. Both funnel through the SAME paste helpers (single vs
                       batch) so a pasted node can never differ by which door it entered. */
                    this._pasteAt(this._contextMenuPos
                        ? this._screenToCanvas(this._contextMenuPos.x - 110, this._contextMenuPos.y - 40)
                        : null);
                    break;
                case 'ctxImportJson':
                    this.importNodeFromJson(
                        this._contextMenuPos
                            ? this._screenToCanvas(this._contextMenuPos.x - 110, this._contextMenuPos.y - 40)
                            : null
                    );
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
                case 'ctxAlign':
                    this.alignSelected(item.dataset.mode);
                    break;
            }
        });

        /* Wheel = three independent roles, none of which grabs another:
             · Ctrl / Cmd held — Chrome/Edge report a trackpad pinch this way — zoom about
               the cursor (a deliberate ctrl-wheel also zooms; it is the same intent).
             · A trackpad two-finger scroll — pan the surface, FOLLOWING the fingers. The
               wheel delta is negated because a delta is written in scrollbar space (positive
               = the viewport moved down/right = content moved up/left), the opposite of
               grabbing the canvas.
             · A mouse wheel notch — zoom, the long-standing desktop behaviour.
           Per-event, a purely-vertical trackpad swipe and a mouse notch can look identical
           on Windows/Chrome (both are integer, pure-vertical pixel deltas), so the
           classifier reads the STREAM, not one event. A burst is upgraded to trackpad
           whenever any event in it carries a horizontal delta, a fractional value, or a
           delta that differs from the previous event — evidence a mouse cannot produce.
           Once upgraded, the rest of the burst pans too, so the brief horizontal-zero
           moment of a diagonal no longer steals an axis. A burst whose events are all
           pure-vertical integer constants is treated as a mouse wheel. */
        this.workspace.addEventListener('wheel', (e) => {
            e.preventDefault();
            this._clearViewAnim(); /* a scroll/pinch wins over an in-flight camera glide */
            const rect = this.workspace.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            if (e.ctrlKey || e.metaKey) {
                /* Pinch (a Ctrl+wheel in Chrome/Edge) or a deliberate ctrl-wheel: zoom
                   about the cursor. 0.999^deltaY ≈ 10% per notch; small pinch deltas
                   already read smooth, so no bigger step is needed here. */
                this._zoomAt(mx, my, Math.pow(0.999, e.deltaY));
                this._lastWheelAt = Date.now();
                this._lastWheelDeltaY = e.deltaY;
                this._wheelStreamTrackpad = true;
                this.scheduleViewSave();
                return;
            }
            const now = Date.now();
            const inBurst = (now - this._lastWheelAt) < 180;
            /* Any concrete sign of a trackpad: horizontal component, a fractional delta
               on THIS event, a change in deltaY within the same burst, or an already-
               trackpad burst. The last rule is what stops the brief deltaX === 0 moment
               of a diagonal from misfiring as a mouse notch (and stealing one axis). */
            const fractional = Math.abs(e.deltaY) % 1 !== 0;
            const isTrackpad = e.deltaX !== 0
                || fractional
                || (inBurst && e.deltaY !== this._lastWheelDeltaY)
                || (this._wheelStreamTrackpad && inBurst);
            this._lastWheelAt = now;
            this._lastWheelDeltaY = e.deltaY;
            this._wheelStreamTrackpad = isTrackpad;
            if (isTrackpad) {
                this._panBy(-e.deltaX, -e.deltaY);
            } else {
                /* A lone integer, pure-vertical delta with no trackpad evidence around it:
                   treat it as a mouse wheel and zoom (the desktop muscle memory). The step
                   is 0.9^(dy/100) ≈ 10% per 100-px notch, matching the wheel's discrete
                   feel rather than the smooth per-pixel pinch. */
                this._zoomAt(mx, my, Math.pow(0.9, e.deltaY / 100));
            }
            /* The camera is part of what a draft (and later a saved file) owes the
               user, so a wheel move that is never written back is a viewpoint that
               disappears on refresh. Debounced: a flick fires dozens of wheel events
               and each redraws nothing but a localStorage write. */
            this.scheduleViewSave();
        }, { passive: false });

        /* Drag from palette — and the same items are the pointer/keyboard route in. A drag
           is a mouse-only gesture, so before this a keyboard user had NO way to add a node.
           Each item becomes a real button (role + tabindex) whose Enter/Space — or a plain
           click, the pointer equivalent of that press — adds that node type at a fresh spot. */
        document.querySelectorAll('.palette-item').forEach(item => {
            item.setAttribute('role', 'button');
            item.tabIndex = 0;
            item.title = I18n.t('palette.addHint');
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.type);
            });
            item.addEventListener('click', () => this.addNodeFromPalette(item.dataset.type));
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    e.preventDefault();
                    this.addNodeFromPalette(item.dataset.type);
                }
            });
        });
        this.workspace.addEventListener('dragover', (e) => e.preventDefault());
        this.workspace.addEventListener('drop', (e) => {
            e.preventDefault();
            /* A clipboard node dragged in carries its entry id under a private type; it
               re-uses the SAME paste funnel as the drawer's 粘贴 button (Clipboard.paste),
               so a drag can never paste a node differently from a click. Checked BEFORE the
               palette's text/plain branch, which the drawer drop leaves empty. */
            const clipId = e.dataTransfer.getData('application/x-canvas-clip');
            if (clipId) {
                const pos = this._screenToCanvas(e.clientX - 110, e.clientY - 40);
                Clipboard.paste(clipId, pos);
                return;
            }
            const type = e.dataTransfer.getData('text/plain');
            if (type) {
                const pos = this._screenToCanvas(e.clientX - 110, e.clientY - 40);
                this.addNode(type, pos.x, pos.y);
            }
        });

        /* Enter also closes the settings panel from INSIDE it. A fresh open drops the caret
           into the panel's first control, so the second Enter lands on a field — not the
           canvas — and the canvas handler is (correctly) silent while typing. Delegated on
           the stable panel element (its body is re-rendered per edit), it stays out of the
           way of controls that OWN Enter: a button/link (they activate), a textarea (a
           newline), or a CustomSelect list (it picks an option). */
        const settingsPanel = document.getElementById('node-settings');
        if (settingsPanel && settingsPanel.addEventListener) {
            settingsPanel.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter' || !this._settingsNodeId) return;
                const t = e.target;
                if (t && t.closest && t.closest('button, a, textarea, .cselect, [contenteditable="true"]')) return;
                e.preventDefault();
                closeSettings();
            });
        }

        /* Keyboard shortcuts */
        document.addEventListener('keydown', (e) => {
            if (this._isTypingTarget(e.target)) return;
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (this.selectedNodes.length > 1) this.deleteNodes(this.selectedNodes.slice());
                else if (this.selectedNode) this.deleteNode(this.selectedNode);
                return;
            }
            if (e.key === 'Escape') {
                this.cancelConnection();
                this._linkFromId = null;
                this.deselectNode();
                closeSettings();
                if (typeof closeShortcutsHelp === 'function') closeShortcutsHelp();
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
            /* Ctrl/Cmd+C / Ctrl/Cmd+V: copy and paste a NODE. A text field is already
               excluded above by _isTypingTarget, so these never hijack the OS text
               clipboard while the user is typing; off-field, they act on the selection.
               Neither fires without a target to act on (a selected node to copy, a filled
               clipboard to paste), so Ctrl+C over some page text with nothing selected is
               left to the browser. */
            if ((e.ctrlKey || e.metaKey) && e.key === 'c') {
                if (this.selectedNodes.length || this.selectedNode) {
                    e.preventDefault();
                    this.copySelection();
                }
                return;
            }
            if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
                if (this._clipboardNodes || this._clipboardData) {
                    e.preventDefault();
                    this._pasteAt(null);
                }
                return;
            }
            /* Arrow keys nudge the selected node — 10px, or 1px with Shift for fine work.
               Only when a node is selected and not typing; otherwise the key falls through
               (a selected node with no clipboard, arrows still move it). */
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                if (this.selectedNode) {
                    e.preventDefault();
                    const step = e.shiftKey ? 1 : 10;
                    const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0;
                    const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0;
                    this._nudgeSelected(dx, dy);
                }
                return;
            }
            /* Enter toggles the selected node's settings — the keyboard route to the same
               panel a double-click or the gear button opens. editNode is the shared toggle:
               a closed panel opens, and pressing Enter again on the node whose panel is
               already open closes it. It never steals Enter from a focused control: typing
               is excluded above, and a button/link keeps its own activation. */
            if (e.key === 'Enter') {
                if (this.selectedNode && typeof this.editNode === 'function' &&
                    !(e.target && e.target.closest && e.target.closest('button, a'))) {
                    e.preventDefault();
                    this.editNode(this.selectedNode);
                }
                return;
            }
            /* W/A/S/D move the selection to the nearest node in that direction (spatial
               traversal). Arrow keys keep nudging the selected node above, so navigation and
               repositioning never fight over one key. Ctrl/Meta/Alt are left to their own
               bindings (copy, etc.). */
            const NAV_DIR = { w: [0, -1], a: [-1, 0], s: [0, 1], d: [1, 0] };
            const nav = NAV_DIR[(e.key || '').toLowerCase()];
            if (nav && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                this._navigateSelection(nav[0], nav[1]);
                return;
            }
            /* Ctrl/Cmd+F: jump to the outline finder. Handled before the plain-`f` fold so
               find does not fold the selected node; typing in a field is already excluded
               above, which is also what lets Ctrl+F inside the finder box itself be normal
               browser search. */
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                e.preventDefault();
                if (typeof Outline !== 'undefined' && Outline.revealFilter) Outline.revealFilter();
                return;
            }
            /* L: keyboard node-connect (link mode) — see toggleLinkMode. Typing is already
               excluded at the top of this handler; placed before the plain-f fold. */
            if (e.key === 'l') {
                e.preventDefault();
                this.toggleLinkMode();
                return;
            }
            /* Fold/unfold selected node with F key */
            if (e.key === 'f' && this.selectedNode) {
                e.preventDefault();
                this.toggleFold(this.selectedNode);
                return;
            }
            /* Zoom: +/= in, -/_ out, 0 fit. The view only — never an undo step (the camera
               is excluded from history by design, same as pan/scroll). */
            if (e.key === '+' || e.key === '=') {
                e.preventDefault();
                this.zoomIn();
                return;
            }
            if (e.key === '-' || e.key === '_') {
                e.preventDefault();
                this.zoomOut();
                return;
            }
            if (e.key === '0') {
                e.preventDefault();
                this.resetView();
                return;
            }
            /* ? / F1: the keyboard-shortcut cheat sheet (a global overlay from app.js). */
            if (e.key === '?' || e.key === 'F1') {
                e.preventDefault();
                if (typeof toggleShortcutsHelp === 'function') toggleShortcutsHelp();
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

    /* Add a node from the palette the way a drag would drop one, but for the pointer and
       keyboard routes a drag cannot serve. Position is left to addNode's own non-finite
       fallback (a fresh random spot, never on top of the last node), and the new node is
       selected so the Delete, `f`-fold, Ctrl+C/V and arrow-key nudge shortcuts act on it
       rather than on whatever was selected before. A toast names the type added: a sighted
       keyboard user gets the same confirmation a drop is, and a screen reader reads it from
       the live region. */
    addNodeFromPalette(type) {
        const t = String(type || '').trim();
        if (!t) return null;
        const id = this.addNode(t);
        this.selectNode(id);
        if (typeof showToast === 'function') {
            showToast(I18n.t('palette.added', { label: I18n.t('node.' + t) }));
        }
        return id;
    },

    /* ── Copy / paste / keyboard-nudge ── */
    /* One implementation each, reached by BOTH the context menu and the keyboard shortcuts.
       A pasted node must not come out different depending on which door it entered — a second
       inline copy of the paste body is exactly the "wrapper in another file" drift this repo
       keeps paying for. */
    PASTE_CASCADE: 24,

    copyNodeToClipboard(id) {
        const n = this.nodes[id];
        if (!n) return false;
        /* The title belongs in the clipboard next to the type and params: a node the user
           bothered to name is copied to be edited again, and a paste that came back labelled
           "Data Source" threw the name away for no reason. */
        this._clipboardData = {
            type: n.type,
            title: n.title || '',
            params: JSON.parse(JSON.stringify(n.params)),
        };
        /* Also append a persisted history entry (additive — the slot above keeps the
           single/last-copy behaviour Ctrl+V depends on; the drawer lists this one). */
        Clipboard.add({ kind: 'node', payload: this._clipboardData });
        if (typeof showToast === 'function') showToast(I18n.t('toast.nodeCopied'));
        return true;
    },

    /* pos is canvas-space (the space addNode writes straight to el.style.left). null → place
       the copy a short diagonal step off the selected node, so repeated Ctrl+V cascades visibly
       rather than stacking copies on one another or teleporting to a random spot. */
    _nextPastePos() {
        if (this.selectedNode) {
            const el = this._nodeEl(this.selectedNode);
            if (el) {
                return {
                    x: (parseInt(el.style.left, 10) || 0) + this.PASTE_CASCADE,
                    y: (parseInt(el.style.top, 10) || 0) + this.PASTE_CASCADE,
                };
            }
        }
        return { x: 100 + Math.random() * 200, y: 100 + Math.random() * 200 };
    },

    pasteClipboardAt(pos) {
        if (!this._clipboardData) return null;
        const pp = pos || this._nextPastePos();
        const id = this.addNode(this._clipboardData.type, pp.x, pp.y);
        if (this.nodes[id]) {
            this.nodes[id].params = JSON.parse(JSON.stringify(this._clipboardData.params));
            /* Same order restoreState needs: updateNodeDisplay only keeps a name that is
               already on both the node AND its element, so stamping it afterwards would let the
               re-stamp overwrite the copied name with the type's default label. */
            if (this._clipboardData.title) {
                this.nodes[id].title = this._clipboardData.title;
                const titleEl = this.nodes[id].el && this.nodes[id].el.querySelector('.node-title');
                if (titleEl) titleEl.textContent = this._clipboardData.title;
            }
            this.updateNodeDisplay(id);
            /* The params (and the copy's name) are written only AFTER addNode has already run
               its own saveState of the freshly-minted defaults, and updateNodeDisplay repaints
               the box's TEXT but not the enable/disable shading, which disableStates computes on
               a full render. So a paste has to re-render and re-save here, or the copied node's
               enabled:false and edited title never reach the draft and it comes back ENABLED (and
               unnamed) on the next load. */
            this.scheduleRender();
            this.saveState();
        }
        if (typeof showToast === 'function') showToast(I18n.t('toast.nodePasted'));
        return id;
    },

    /* One paste door for the single and the batch clipboard, so the keyboard route and the
       context menu can never paste a node differently. */
    _pasteAt(pos) {
        if (this._clipboardNodes && this._clipboardNodes.length) return this.pasteNodesAt(pos);
        return this.pasteClipboardAt(pos);
    },

    /* Batch copy of the whole selection. One node delegates to the single-copy path so the
       clipboard shape (and every existing paste consumer) is unchanged; two or more are stored as
       a list pasteNodesAt reads back. */
    copySelection() {
        const ids = (this.selectedNodes.length ? this.selectedNodes : (this.selectedNode ? [this.selectedNode] : []))
            .filter((id) => this.nodes[id]);
        if (!ids.length) return false;
        if (ids.length === 1) return this.copyNodeToClipboard(ids[0]);
        this._clipboardNodes = ids.map((id) => {
            const n = this.nodes[id];
            return { type: n.type, title: n.title || '', params: JSON.parse(JSON.stringify(n.params || {})) };
        });
        this._clipboardData = null;
        Clipboard.add({ kind: 'nodes', payload: this._clipboardNodes });
        if (typeof showToast === 'function') showToast(I18n.t('toast.nodesCopied', { n: this._clipboardNodes.length }));
        return true;
    },

    /* Paste the batch as ONE undo step: suppress per-node history while each addNode runs its own
       saveState, then a single saveState records the whole group. Copies cascade and the new set
       becomes the selection. */
    pasteNodesAt(pos) {
        const list = this._clipboardNodes;
        if (!list || !list.length) return [];
        const base = pos || this._nextPastePos();
        this._historySaving = true;
        const ids = [];
        list.forEach((rec, i) => {
            const id = this.addNode(rec.type, base.x + i * this.PASTE_CASCADE, base.y + i * this.PASTE_CASCADE);
            if (this.nodes[id]) {
                this.nodes[id].params = JSON.parse(JSON.stringify(rec.params || {}));
                if (rec.title) {
                    this.nodes[id].title = rec.title;
                    const titleEl = this.nodes[id].el && this.nodes[id].el.querySelector('.node-title');
                    if (titleEl) titleEl.textContent = rec.title;
                }
                this.updateNodeDisplay(id);
            }
            ids.push(id);
        });
        this._historySaving = false;
        this.saveState();
        this.scheduleRender();
        this.setSelectedNodes(ids);
        if (typeof showToast === 'function') showToast(I18n.t('toast.nodesPasted', { n: ids.length }));
        return ids;
    },

    /* The same-type multi-edit target set: the whole selection, but ONLY when every selected node
       shares the panel-open node's type. A mixed selection returns [] so the panel keeps editing
       the one node it was opened on rather than writing this type's params onto another type. */
    multiEditTargets(nodeId) {
        if (!(this.selectedNodes.length > 1)) return [];
        if (this.selectedNodes.indexOf(nodeId) < 0) return [];
        const anchor = this.nodes[nodeId];
        if (!anchor) return [];
        const same = this.selectedNodes.every((id) => this.nodes[id] && this.nodes[id].type === anchor.type);
        return same ? this.selectedNodes.slice() : [];
    },

    /* Move the selected node by (dx,dy) canvas pixels. Position lives in el.style.left/top —
       that is what getState snapshots and what the draft persists — so writing there (and
       mirroring onto node.x/y) is what makes the nudge undoable and survive a reload. */
    _nudgeSelected(dx, dy) {
        const ids = this.selectedNodes.length ? this.selectedNodes : (this.selectedNode ? [this.selectedNode] : []);
        if (!ids.length) return;
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const x = (parseInt(el.style.left, 10) || 0) + dx;
            const y = (parseInt(el.style.top, 10) || 0) + dy;
            el.style.left = x + 'px';
            el.style.top = y + 'px';
            if (this.nodes[id]) {
                this.nodes[id].x = x;
                this.nodes[id].y = y;
            }
        });
        this.scheduleRender();
        this.saveState();
    },

    /* Spatial node traversal (W/A/S/D): from the current selection — or, when nothing
       is selected, from the node nearest the viewport centre — move to the closest node
       lying in the given world direction. A candidate must be genuinely ahead of the
       current box on the axis of travel (its leading edge past the current box's far
       edge), compared by perpendicular alignment first and gap second. Edge gating, not
       centre distance, is what keeps a taller node in the SAME row from being mistaken
       for one below. Position is read from el.style.left/top (the same world coordinates
       _nudgeSelected writes), never offsetLeft — so it is deterministic under the DOM
       stub and after a reload. */
    _navigateSelection(dx, dy) {
        const boxes = [];
        Object.keys(this.nodes).forEach((id) => {
            const el = this._nodeEl(id);
            if (!el || el.style.display === 'none') return;
            const w = el.offsetWidth || 240;
            const h = el.offsetHeight || 80;
            const x = parseFloat(el.style.left) || 0;
            const y = parseFloat(el.style.top) || 0;
            boxes.push({
                id, left: x, top: y, right: x + w, bottom: y + h, cx: x + w / 2, cy: y + h / 2,
            });
        });
        if (!boxes.length) return;
        const cur = this.selectedNode ? boxes.find((b) => b.id === this.selectedNode) : null;
        if (!cur) {
            const vw = (this.workspace && this.workspace.clientWidth) || window.innerWidth;
            const vh = (this.workspace && this.workspace.clientHeight) || window.innerHeight;
            const ccx = (vw / 2 - this.panX) / this.zoom;
            const ccy = (vh / 2 - this.panY) / this.zoom;
            let best = null;
            let bd = Infinity;
            boxes.forEach((b) => {
                const d = (b.cx - ccx) ** 2 + (b.cy - ccy) ** 2;
                if (d < bd) { bd = d; best = b; }
            });
            if (best) { this.selectNode(best.id); this._ensureNodeVisible(best.id); }
            return;
        }
        const horizontal = dx !== 0;
        // A box is strictly ahead on the travel axis, past the current box's far edge.
        const ahead = (b) => (horizontal
            ? (dx > 0 ? b.left >= cur.right : b.right <= cur.left)
            : (dy > 0 ? b.top >= cur.bottom : b.bottom <= cur.top));
        let cands = boxes.filter((b) => b.id !== cur.id && ahead(b));
        if (!cands.length) {
            // Nothing is cleanly ahead (overlapping rows): fall back to centre-ahead so a
            // clearly-lower/right node is still reachable.
            cands = boxes.filter((b) => b.id !== cur.id && (horizontal
                ? (dx > 0 ? b.cx > cur.cx : b.cx < cur.cx)
                : (dy > 0 ? b.cy > cur.cy : b.cy < cur.cy)));
        }
        const score = (b) => {
            const perp = horizontal ? Math.abs(b.cy - cur.cy) : Math.abs(b.cx - cur.cx);
            const gap = horizontal
                ? (dx > 0 ? b.left - cur.right : cur.left - b.right)
                : (dy > 0 ? b.top - cur.bottom : cur.top - b.bottom);
            return perp + Math.max(0, gap);
        };
        let best = null;
        let bestScore = Infinity;
        cands.forEach((b) => {
            const s = score(b);
            if (s < bestScore) { bestScore = s; best = b; }
        });
        if (best) { this.selectNode(best.id); this._ensureNodeVisible(best.id); }
    },

    /* Pan the camera onto a node only when it is off-screen, so traversal never yanks
       the view for a node the user can already see. */
    _ensureNodeVisible(id) {
        const el = this._nodeEl(id);
        if (!el) return;
        const w = el.offsetWidth || 240;
        const h = el.offsetHeight || 80;
        const cx = (parseFloat(el.style.left) || 0) + w / 2;
        const cy = (parseFloat(el.style.top) || 0) + h / 2;
        const vw = (this.workspace && this.workspace.clientWidth) || window.innerWidth;
        const vh = (this.workspace && this.workspace.clientHeight) || window.innerHeight;
        const sx = cx * this.zoom + this.panX;
        const sy = cy * this.zoom + this.panY;
        if (sx < 0 || sy < 0 || sx > vw || sy > vh) this._centerWorldPoint(cx, cy);
    },

    /* Align / distribute the multi-selection as ONE undo step — the same batch-then-saveState
       pattern autoLayout and _nudgeSelected use, so one click is one Ctrl+Z. Position lives in
       el.style.left/top (mirrored onto node.x/y); size is the rendered box, exactly what
       autoLayout advances by. Fewer than two selected nodes is a no-op (nothing to align to). */
    alignSelected(mode) {
        const ids = this.selectedNodes.length ? this.selectedNodes.slice() : (this.selectedNode ? [this.selectedNode] : []);
        if (ids.length < 2) return false;
        const boxes = ids.map((id) => {
            const el = this._nodeEl(id);
            return {
                id,
                el,
                x: parseInt(el.style.left, 10) || 0,
                y: parseInt(el.style.top, 10) || 0,
                w: el.offsetWidth || 120,
                h: el.offsetHeight || 60,
            };
        });
        const minX = Math.min(...boxes.map((b) => b.x));
        const maxX = Math.max(...boxes.map((b) => b.x + b.w));
        const minY = Math.min(...boxes.map((b) => b.y));
        const maxY = Math.max(...boxes.map((b) => b.y + b.h));
        let apply = null;
        if (mode === 'left') apply = (b) => ({ x: minX, y: b.y });
        else if (mode === 'right') apply = (b) => ({ x: maxX - b.w, y: b.y });
        else if (mode === 'top') apply = (b) => ({ x: b.x, y: minY });
        else if (mode === 'bottom') apply = (b) => ({ x: b.x, y: maxY - b.h });
        else if (mode === 'hcenter') apply = (b) => ({ x: (minX + maxX) / 2 - b.w / 2, y: b.y });
        else if (mode === 'vcenter') apply = (b) => ({ x: b.x, y: (minY + maxY) / 2 - b.h / 2 });
        else if (mode === 'distributeH' || mode === 'distributeV') {
            const horizontal = mode === 'distributeH';
            boxes.sort((a, b) => (horizontal ? a.x - b.x : a.y - b.y));
            const first = boxes[0];
            const last = boxes[boxes.length - 1];
            const firstCenter = horizontal ? first.x + first.w / 2 : first.y + first.h / 2;
            const lastCenter = horizontal ? last.x + last.w / 2 : last.y + last.h / 2;
            const step = (lastCenter - firstCenter) / (boxes.length - 1);
            apply = horizontal
                ? (b, i) => ({ x: firstCenter + i * step - b.w / 2, y: b.y })
                : (b, i) => ({ x: b.x, y: firstCenter + i * step - b.h / 2 });
        }
        if (!apply) return false;
        boxes.forEach((b, i) => {
            const t = apply(b, i);
            const nx = Math.round(t.x === undefined ? b.x : t.x);
            const ny = Math.round(t.y === undefined ? b.y : t.y);
            if (!b.el) return;
            b.el.style.left = nx + 'px';
            b.el.style.top = ny + 'px';
            if (this.nodes[b.id]) {
                this.nodes[b.id].x = nx;
                this.nodes[b.id].y = ny;
            }
        });
        this.scheduleRender();
        this.saveState();
        if (typeof showToast === 'function') showToast(I18n.t('toast.alignApplied'));
        return true;
    },
    /* Ctrl+C/V is same-page. These put a single node on the OS clipboard as text and read one
       back, so a node config travels between canvases, machines or a chat message. The snippet
       is exactly the in-canvas clipboard shape ({type,title,params}), so import reuses
       pasteClipboardAt — one paste path, no second implementation to drift. */
    _VALID_NODE_TYPES: ['name', 'source', 'upload', 'process', 'analysis', 'visualize', 'tokenize', 'output', 'compile', 'resume', 'comment'],

    copyNodeAsJson(id) {
        const n = this.nodes[id];
        if (!n) return Promise.resolve(false);
        const snippet = JSON.stringify({ type: n.type, title: n.title || '', params: n.params || {} });
        /* The same node also enters the persisted clipboard history (structured, so the
           drawer can paste it as a node without re-parsing the OS-clipboard text). */
        Clipboard.add({ kind: 'node', payload: { type: n.type, title: n.title || '', params: n.params || {} } });
        const notify = () => {
            if (typeof showToast === 'function') showToast(I18n.t('toast.nodeJsonCopied'));
            return true;
        };
        /* The async Clipboard API is only exposed in a secure context (https or localhost);
           served over a plain http LAN address it is undefined, so fall back to a dialog whose
           input already holds the text (select-all + copy) rather than failing silently. */
        if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(snippet).then(notify, () => this._showJsonCopyFallback(snippet));
        }
        return this._showJsonCopyFallback(snippet);
    },

    _showJsonCopyFallback(snippet) {
        /* No Clipboard API here (plain-http context): show the text so the user can select +
           copy it. We do NOT toast "copied" — nothing was put on the clipboard by us. */
        return Promise.resolve(showDialog({
            message: I18n.t('dialog.nodeJsonCopy'),
            input: { value: snippet },
            buttons: [{ label: I18n.t('dialog.confirm'), primary: true }],
        })).then(() => true);
    },

    /* atPos is canvas-space (from a menu click), or null → _nextPastePos cascades off the
       selected node / a random spot, exactly like pasteClipboardAt's keyboard route. */
    importNodeFromJson(atPos) {
        return Promise.resolve(showDialog({
            message: I18n.t('dialog.nodeJsonImport'),
            input: { placeholder: '{"type":"source", ...}', value: '' },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('dialog.confirm'), primary: true },
            ],
        })).then((raw) => {
            if (raw === null || raw === undefined) return null;
            const text = String(raw).trim();
            if (!text) return null;
            let parsed;
            try {
                parsed = JSON.parse(text);
            } catch (e) {
                if (typeof showToast === 'function') showToast(I18n.t('toast.nodeJsonInvalid'));
                return null;
            }
            if (!parsed || typeof parsed !== 'object'
                || this._VALID_NODE_TYPES.indexOf(parsed.type) < 0
                || typeof parsed.params !== 'object' || parsed.params === null) {
                if (typeof showToast === 'function') showToast(I18n.t('toast.nodeJsonInvalid'));
                return null;
            }
            this._clipboardData = {
                type: parsed.type,
                title: String(parsed.title || ''),
                params: parsed.params,
            };
            return this.pasteClipboardAt(atPos || null);
        });
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
            compile: I18n.t('node.compile'),
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
            '<div class="node-validate-badge" style="display:none"></div>',
            '<div class="node-content"></div>',
            '<div class="node-port node-port-in" data-port="in"></div>',
            '<div class="node-port node-port-out" data-port="out"></div>',
        ].join('');
        const titleEl = el.querySelector('.node-title');
        titleEl.textContent = title;
        /* Screen-reader identity: the box is a named group, so Tab reaching it announces
           "Data Source" (or the node's custom name) rather than reading a button soup. The
           label is kept in step with the visible title in updateNodeDisplay (rename + language). */
        el.setAttribute('role', 'group');
        el.setAttribute('aria-label', title);
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
            /* The right button belongs to the context menu, never to a drag. A right-press must
               not collapse a live multi-selection when it lands on a node already in the group —
               the menu reads that group for 复制/对齐 — so it leaves the selection untouched; a
               right-press on an unselected node selects just it, the way a fresh left-click does. */
            if (e.button === 2) {
                if (this.selectedNodes.indexOf(id) < 0) this.selectNode(id);
                return;
            }
            this.isDragging = true;
            this.dragTarget = el;
            const rect = el.getBoundingClientRect();
            this.dragOffsetX = e.clientX - rect.left;
            this.dragOffsetY = e.clientY - rect.top;
            /* Keep the group when the pressed box is already one of it (the batch-op contract, as
               in editNode/_nudgeSelected) so the drag moves every selected node together; a press
               on a fresh box selects just it, and shift adds. */
            if (!(this.selectedNodes.indexOf(id) >= 0 && this.selectedNodes.length > 1)) {
                this.selectNode(id, e.shiftKey);
            }
            /* Snapshot the whole selected group with its start position; the drag moves each box
               by the SAME delta, so a multi-select keeps its relative layout. */
            const ids = this.selectedNodes.length ? this.selectedNodes : [id];
            this._dragGroup = ids
                .map((mid) => {
                    const mel = this._nodeEl(mid);
                    if (!mel) return null;
                    return {
                        el: mel,
                        id: mid,
                        x: parseInt(mel.style.left, 10) || 0,
                        y: parseInt(mel.style.top, 10) || 0,
                    };
                })
                .filter(Boolean);
            this._dragOriginX = parseInt(el.style.left, 10) || 0;
            this._dragOriginY = parseInt(el.style.top, 10) || 0;
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
           panel and an optional 排布顺序 for auto-layout — both metadata, not data,
           so its params never choose a crawl. layout_order blank = keep creation order. */
        if (type === 'name') return { workflow_name: '', layout_order: '' };
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
        /* A compile node carries no fields of its own: it reads the LaTeX its upstream
           visualize node produced. Its only setting is the MiKTeX path, which lives in 设置. */
        if (type === 'compile') return {};
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
        if (type === 'compile') {
            /* No fields to show: it compiles whatever LaTeX its upstream visualize node emitted. */
            return I18n.t('compile.summary');
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
        this.selectedNodes = this.selectedNodes.filter(nid => nid !== id);
        /* The panel is bound to this node id — leaving it open would keep showing
           its old settings and let the user edit a node that no longer exists. */
        if (this._settingsNodeId === id) closeSettings();
        this.scheduleRender();
        this.updateStatus();
        this.saveState();
        showToast(I18n.t('toast.nodeDeleted'));
    },

    /* Delete a whole selection set as ONE edit: every box removed, every touching wire pruned,
       one saveState (one undo step), one toast naming how many went. */
    deleteNodes(ids) {
        const list = (ids || []).filter((id) => this.nodes[id]);
        if (!list.length) return;
        list.forEach((id) => {
            const el = this._nodeEl(id);
            if (el) el.remove();
            delete this.nodes[id];
        });
        this.connections = this.connections.filter(c => list.indexOf(c.from) < 0 && list.indexOf(c.to) < 0);
        this.selectedNodes = this.selectedNodes.filter(nid => this.nodes[nid]);
        if (list.indexOf(this.selectedNode) >= 0) {
            this.selectedNode = this.selectedNodes.length ? this.selectedNodes[this.selectedNodes.length - 1] : null;
        }
        if (list.indexOf(this._settingsNodeId) >= 0) closeSettings();
        this.scheduleRender();
        this.updateStatus();
        this.saveState();
        showToast(I18n.t('toast.nodesDeleted', { n: list.length }));
    },

    selectNode(id, additive) {
        if (additive) {
            if (this.selectedNodes.indexOf(id) < 0) this.selectedNodes.push(id);
            this.selectedNode = id;
        } else {
            this.selectedNodes = [id];
            this.selectedNode = id;
        }
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        this.selectedNodes.forEach((nid) => {
            const el = this._nodeEl(nid);
            if (el) el.classList.add('selected');
        });
        this._notifyOutlineActive();
    },

    /* Paint a selection set directly (marquee result): the anchor is the last id, and every
       listed box lights. An empty set is a deselect. */
    setSelectedNodes(ids) {
        this.selectedNodes = (ids || []).slice();
        this.selectedNode = this.selectedNodes.length ? this.selectedNodes[this.selectedNodes.length - 1] : null;
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        this.selectedNodes.forEach((nid) => {
            const el = this._nodeEl(nid);
            if (el) el.classList.add('selected');
        });
        this._notifyOutlineActive();
    },

    deselectNode() {
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        this.selectedNode = null;
        this.selectedNodes = [];
        this._notifyOutlineActive();
    },

    /* Mirror the graph's selection into the outline: the outline's active row must follow
       selectNode/deselectNode directly. Selection is a VIEW change, not a model change, so it
       deliberately does NOT go through saveState (that would make every click an undo step) —
       which is exactly why the sidebar used to keep a stale highlight after the graph was
       deselected. Guarded on `typeof Outline` so a canvas-only harness (no workflow.js) is safe. */
    _notifyOutlineActive() {
        if (typeof Outline !== 'undefined' && Outline._markActive) Outline._markActive();
    },

    /* Rubber-band selection. Drawn as a positioned overlay div; its own one-shot document
       listeners do the move/up so this never intersects the pan/pinch/node-drag paths (those
       only act when isPanning/isDragging are set, which a plain background press does not). A
       press that never moved is left as the deselect the caller already performed. */
    _startMarquee(e) {
        const wsRect = this.workspace.getBoundingClientRect();
        const sx = e.clientX - wsRect.left;
        const sy = e.clientY - wsRect.top;
        const box = document.createElement('div');
        box.className = 'marquee';
        this.workspace.appendChild(box);
        let moved = false;
        let rect = { x: sx, y: sy, w: 0, h: 0 };
        const paint = (cx, cy) => {
            rect = { x: Math.min(sx, cx), y: Math.min(sy, cy), w: Math.abs(cx - sx), h: Math.abs(cy - sy) };
            box.style.left = rect.x + 'px';
            box.style.top = rect.y + 'px';
            box.style.width = rect.w + 'px';
            box.style.height = rect.h + 'px';
        };
        const self = this;
        /* Update the selection AS the band grows/shrinks, not only when the mouse is released: a
           node the band has just swept over lights up the instant it is covered, and un-lights the
           instant the band shrinks past it. Guarded by the hit-set so an unchanged band repaints
           nothing (a bare re-paint would flash every box off and on per pointermove). */
        let lastKey = '';
        const apply = () => {
            const hits = self._marqueeHits(rect, wsRect);
            const key = hits.join(',');
            if (key !== lastKey) {
                lastKey = key;
                self.setSelectedNodes(hits);
            }
        };
        const onMove = (ev) => {
            moved = true;
            paint(ev.clientX - wsRect.left, ev.clientY - wsRect.top);
            apply();
        };
        const cleanup = () => {
            if (document.removeEventListener) {
                document.removeEventListener('pointermove', onMove);
                document.removeEventListener('pointerup', onUp);
            }
            if (box.parentNode && box.parentNode.removeChild) box.parentNode.removeChild(box);
            else if (box.remove) box.remove();
        };
        function onUp(ev) {
            if (!moved) {
                cleanup();
                return;
            }
            paint(ev.clientX - wsRect.left, ev.clientY - wsRect.top);
            apply();
            cleanup();
        }
        document.addEventListener('pointermove', onMove);
        document.addEventListener('pointerup', onUp);
    },

    /* Select every node whose box the marquee rectangle (workspace pixels) overlaps. The rect's
       corners are converted to canvas/world coordinates through the same transform the render
       uses, so a zoomed/panned canvas still hits the right boxes. Returns the ids; the caller
       paints them (live during the drag, and once more at release). */
    _marqueeHits(rect, wsRect) {
        const p0 = this._screenToCanvas(wsRect.left + rect.x, wsRect.top + rect.y);
        const p1 = this._screenToCanvas(wsRect.left + rect.x + rect.w, wsRect.top + rect.y + rect.h);
        const left = Math.min(p0.x, p1.x);
        const right = Math.max(p0.x, p1.x);
        const top = Math.min(p0.y, p1.y);
        const bottom = Math.max(p0.y, p1.y);
        return Object.keys(this.nodes).filter((id) => {
            const el = this._nodeEl(id);
            if (!el) return false;
            const l = el.offsetLeft;
            const t = el.offsetTop;
            const r = l + (el.offsetWidth || 240);
            const b = t + (el.offsetHeight || 80);
            return r > left && l < right && b > top && t < bottom;
        });
    },

    /* The marquee's final commit: compute the covered ids and paint them as one selection. The
       live drag path calls _marqueeHits + setSelectedNodes directly (guarded per move); this is
       the entry the browser tier and any whole-rect selection use. */
    _marqueeSelect(rect, wsRect) {
        this.setSelectedNodes(this._marqueeHits(rect, wsRect));
    },

    editNode(id) {
        /* Preserve a live multi-selection when the edit is triggered on a node already in the
           group — that is how the panel reaches the "apply to all" path. A plain edit of an
           unselected or single node still selects just it. */
        if (!(this.selectedNodes.indexOf(id) >= 0 && this.selectedNodes.length > 1)) {
            this.selectNode(id);
        }
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
        if (node.el) node.el.setAttribute('aria-label', title);
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

    /* Is `target` reachable from `start` by following existing directed wires? Iterative DFS
       (no recursion) over the {from,to} connection list. Used to refuse a wire that would close
       a loop before it is ever committed to the model. */
    _reaches(start, target) {
        if (start === target) return true;
        const adj = {};
        this.connections.forEach((c) => {
            (adj[c.from] || (adj[c.from] = [])).push(c.to);
        });
        const seen = new Set([start]);
        const stack = [start];
        while (stack.length) {
            const cur = stack.pop();
            const nexts = adj[cur] || [];
            for (let i = 0; i < nexts.length; i++) {
                const nb = nexts[i];
                if (nb === target) return true;
                if (!seen.has(nb)) { seen.add(nb); stack.push(nb); }
            }
        }
        return false;
    },

    /* The one place a wire is committed: pure model mutation (edge + its side effects), no
       pointer event and no dialog. finishConnection and the keyboard link mode both call it,
       so both share identical semantics. Returns {ok, warn} — ok is false for a self-edge, a
       duplicate, or a wire that would form a cycle, in which case nothing was written. */
    connectNodes(fromId, toId) {
        if (!fromId || !toId || fromId === toId) return { ok: false, warn: null };
        const exists = this.connections.some(c => c.from === fromId && c.to === toId);
        if (exists) return { ok: false, warn: null };
        /* A cycle would make the graph unrunnable (the engine walks wires top-down). Refuse it
           at the single commit point so BOTH the pointer drag and keyboard link mode are held
           to the same rule: adding from→to loops iff `to` already reaches `from`. */
        if (this._reaches(toId, fromId)) {
            if (typeof showToast === 'function') showToast(I18n.t('toast.connCycle'));
            return { ok: false, warn: null };
        }
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
        return { ok: true, warn: this.classifyConnection(fromId, toId) };
    },

    /* The wire is explained AFTER it is written: the user is told what THIS engine will do
       with it and can take it back (undo the edge). Shared by the pointer and keyboard paths
       so both warn identically; `warn` is null when nothing was created. */
    async _afterConnectWarning(fromId, toId, warn) {
        if (warn && !this._connWarningsDismissed.has(warn.category)) {
            const keep = await this._warnConnection(fromId, toId, warn);
            if (!keep) this._undoConnection(fromId, toId);
        }
    },

    /* Keyboard link mode (L): with a node selected, the first L marks it the wire START and
       tells you to pick the end; selecting a second node and pressing L again commits the
       edge through connectNodes (so a fan-in warning can still offer to take it back). Same
       L on the start again, or nothing selected, cancels the mode. Selection is view-only —
       this never touches getState/history. */
    toggleLinkMode() {
        if (this._linkFromId == null) {
            if (!this.selectedNode) {
                showToast(I18n.t('canvas.linkNoSel'));
                return;
            }
            this._linkFromId = this.selectedNode;
            showToast(I18n.t('canvas.linkHint'));
            return;
        }
        const fromId = this._linkFromId;
        const toId = this.selectedNode;
        this._linkFromId = null;
        if (!toId || toId === fromId) {
            showToast(I18n.t('canvas.linkCancel'));
            return;
        }
        const res = this.connectNodes(fromId, toId);
        if (res.ok) this._afterConnectWarning(fromId, toId, res.warn);
    },

    async finishConnection(e) {
        const target = this._getPortAt(e.clientX, e.clientY);
        const fromId = this.connectingFrom;
        let toId = null;
        let warn = null;
        if (target && target.dataset.port === 'in') {
            toId = target.dataset.node;
            const res = this.connectNodes(fromId, toId);
            if (res.ok) warn = res.warn;
        }
        this.cancelConnection();
        if (warn) await this._afterConnectWarning(fromId, toId, warn);
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
            this.renderMinimap();
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
        this.renderMinimap();
    },

    _paintZoomReadout() {
        const el = document.getElementById('status-zoom');
        if (el) el.textContent = Math.round(this.zoom * 100) + '%';
    },

    _prefersReducedMotion() {
        /* Honour the OS "reduce motion" setting: glide only when the user has not asked
           the system to minimise animation. */
        return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    },

    /* Drop the camera glide: cancel the end timer and remove the CSS transition so the
       next transform change is immediate. Called before a manual gesture (wheel / pan /
       pinch / node drag) and whenever a new glide starts, so the surface never lags the
       state that was already committed. */
    _clearViewAnim() {
        if (this._viewAnim) {
            clearTimeout(this._viewAnim);
            this._viewAnim = null;
        }
        if (this._viewAnimating) {
            if (this.container && this.container.style) this.container.style.transition = '';
            this._viewAnimating = false;
        }
    },

    /* Ease the camera to (tx, ty, tz). The final state is committed SYNCHRONOUSLY — the
       model, the coordinate math and the tests all read the target at once — and only the
       rendered transform glides there from what is on screen, via a CSS transition. `ms`
       overrides the default duration; 0 or a reduced-motion preference snaps instantly. */
    _animateViewTo(tx, ty, tz, ms) {
        this._clearViewAnim();
        this.panX = tx;
        this.panY = ty;
        this.zoom = tz;
        this._paintZoomReadout();
        const duration = ms === undefined ? VIEW_ANIM_MS : ms;
        const el = this.container;
        if (duration <= 0 || this._prefersReducedMotion() || !el || !el.style) {
            this.updateTransform();
            this.scheduleViewSave();
            return;
        }
        /* Set the transition BEFORE the transform changes, so the browser interpolates
           from the currently-painted transform to the new one. */
        el.style.transition = 'transform ' + duration + 'ms ' + VIEW_ANIM_EASE;
        this._viewAnimating = true;
        this.updateTransform();
        this._viewAnim = setTimeout(() => this._clearViewAnim(), duration + 60);
        this.scheduleViewSave();
    },

    /* Screen-space pan by (dx, dy). Used by a two-finger trackpad scroll and by the
       axis of a pinch. The canvas is unbounded, so — like a pointer drag — there is no
       clamp: the surface simply follows the gesture. */
    _panBy(dx, dy) {
        if (!dx && !dy) return;
        this.panX += dx;
        this.panY += dy;
        this.updateTransform();
    },

    /* Zoom by `factor` about the workspace point (mx, my) so that point stays put — the
       anchored feel that keeps a pinch or ctrl-wheel from drifting the view. */
    _zoomAt(mx, my, factor) {
        const oldZoom = this.zoom;
        const newZoom = Math.max(0.2, Math.min(3, oldZoom * factor));
        if (newZoom === oldZoom) return;
        const ratio = newZoom / oldZoom;
        this.panX = mx - (mx - this.panX) * ratio;
        this.panY = my - (my - this.panY) * ratio;
        this.zoom = newZoom;
        this.updateTransform();
        const el = document.getElementById('status-zoom');
        if (el) el.textContent = Math.round(this.zoom * 100) + '%';
    },

    /* Two-finger gesture on the background: slide = pan, spread/close = zoom, both
       anchored at the fingers' midpoint so the content between them holds still. The
       first call only records the base; later calls are RELATIVE to that base, so the
       two fingers' own micro-jitter during a pinch never compounds into a drift. */
    _applyPinch() {
        const pts = Object.values(this._panPointers);
        if (pts.length < 2) return;
        const a = pts[0];
        const b = pts[1];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (!dist) return;
        const midX = (a.x + b.x) / 2;
        const midY = (a.y + b.y) / 2;
        /* The base is captured the moment the second finger lands (pointerdown); a move
           with no base is a can't-happen, so bail rather than invent one mid-gesture. */
        if (!this._pinchBase) return;
        const base = this._pinchBase;
        const targetZoom = Math.max(0.2, Math.min(3, base.zoom * (dist / base.dist)));
        const rect = this.workspace.getBoundingClientRect();
        const cmx = midX - rect.left;
        const cmy = midY - rect.top;
        const baseCmx = base.midX - rect.left;
        const baseCmy = base.midY - rect.top;
        /* Resolve pan and zoom TOGETHER, relative to the base, so the canvas point that
           sat under the fingers at pinch-start stays under their midpoint now — a spread
           that also slides across the surface neither drifts nor compounds one frame's
           rounding into the next. */
        this.panX = cmx - targetZoom * ((baseCmx - base.panX) / base.zoom);
        this.panY = cmy - targetZoom * ((baseCmy - base.panY) / base.zoom);
        this.zoom = targetZoom;
        this.updateTransform();
        const el = document.getElementById('status-zoom');
        if (el) el.textContent = Math.round(this.zoom * 100) + '%';
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
            this._animateViewTo(0, 0, 1);
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
        const tZoom = Math.max(0.2, Math.min(1, fit));
        const cx = (minX + maxX) / 2;
        const cy = (minY + maxY) / 2;
        /* Centre inside the band the menu does NOT cover, not inside the whole
           height — so the top margin is (menu + VIEW_FIT_MARGIN), never 0. */
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this._animateViewTo(vw / 2 - cx * tZoom, bandCentreY - cy * tZoom, tZoom);
    },

    /* Bring ONE node to the centre of the visible box and ZOOM IN enough to read it
       with its neighbours — the outline's jump-to-node. Unlike resetView (适应), which
       fits the WHOLE graph and so shrinks every box to a thumbnail once there are many,
       this frames just the target plus a ring around it: the zoom window is 3× the node's
       own size, so the node lands dead centre and one hop of neighbours stays visible. The
       camera MAY zoom in here (past 100%) — that is the whole point — clamped to [0.5, 1.5]
       so an extreme window can neither bury the node nor blow it into a pixel blob. It
       still borrows resetView's viewport facts (workspace client rect, menu-height top inset, VIEW_FIT_MARGIN). */
    centerOnNode(id) {
        const el = this._nodeEl(id);
        if (!el) return;
        const vp = this.workspace || {};
        const vw = vp.clientWidth || window.innerWidth;
        const vh = vp.clientHeight || window.innerHeight;
        const menu = document.getElementById('top-menu');
        const topInset = (menu ? menu.offsetHeight : 0) + VIEW_FIT_MARGIN;
        const nodeW = el.offsetWidth || 240;
        const nodeH = el.offsetHeight || 80;
        const availW = Math.max(1, vw - 2 * VIEW_FIT_MARGIN);
        const availH = Math.max(1, vh - topInset - VIEW_FIT_MARGIN);
        const fit = Math.min(availW / (nodeW * 3), availH / (nodeH * 3));
        const tZoom = Math.max(0.5, Math.min(1.5, fit));
        const cx = el.offsetLeft + nodeW / 2;
        const cy = el.offsetTop + nodeH / 2;
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this._animateViewTo(vw / 2 - cx * tZoom, bandCentreY - cy * tZoom, tZoom);
    },

    /* ── Minimap: an overview of the whole graph in a corner ── */

    /* The world rectangle every node occupies, sized by each box's own DOM size (the
       same facts resetView fits to). null when there is nothing to draw — an empty
       canvas gets no minimap, not a lone point at the origin. */
    _minimapBounds() {
        const ids = Object.keys(this.nodes);
        if (!ids.length) return null;
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            minX = Math.min(minX, el.offsetLeft);
            minY = Math.min(minY, el.offsetTop);
            maxX = Math.max(maxX, el.offsetLeft + (el.offsetWidth || 240));
            maxY = Math.max(maxY, el.offsetTop + (el.offsetHeight || 80));
        });
        if (!isFinite(minX)) return null;
        return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
    },

    /* Uniform scale (min of the two axes) that fits the world bounds into the box, so the
       minimap never stretches a node sideways. */
    _minimapScale(bounds, size) {
        const contentW = Math.max(1, bounds.maxX - bounds.minX);
        const contentH = Math.max(1, bounds.maxY - bounds.minY);
        const avail = Math.max(1, size - 2 * MINIMAP_PAD);
        return Math.min(avail / contentW, avail / contentH);
    },

    /* A click at minimap pixels → the world point it stands for (inverse of the draw map). */
    _minimapClickToWorld(mx, my, bounds, scale) {
        return { x: bounds.minX + (mx - MINIMAP_PAD) / scale, y: bounds.minY + (my - MINIMAP_PAD) / scale };
    },

    /* Re-centre the camera on a world point at the CURRENT zoom (kept — a minimap click is a
       pan, not a zoom). Same viewport-box + menu-inset convention as resetView, so the point
        lands in the band the top menu does not cover. */
    _centerWorldPoint(wx, wy) {
        const vp = this.workspace || {};
        const vw = vp.clientWidth || window.innerWidth;
        const vh = vp.clientHeight || window.innerHeight;
        const menu = document.getElementById('top-menu');
        const topInset = (menu ? menu.offsetHeight : 0) + VIEW_FIT_MARGIN;
        const bandCentreY = (topInset + (vh - VIEW_FIT_MARGIN)) / 2;
        this._animateViewTo(vw / 2 - wx * this.zoom, bandCentreY - wy * this.zoom, this.zoom);
    },

    onMinimapClick(e) {
        const bounds = this._minimapBounds();
        if (!bounds) return;
        const scale = this._minimapScale(bounds, MINIMAP_SIZE);
        const rect = (e.currentTarget && e.currentTarget.getBoundingClientRect) ? e.currentTarget.getBoundingClientRect() : { left: 0, top: 0 };
        const world = this._minimapClickToWorld(e.clientX - rect.left, e.clientY - rect.top, bounds, scale);
        this._centerWorldPoint(world.x, world.y);
    },

    /* Draws the minimap as positioned boxes in #minimap's innerHTML: one rectangle per node and
       a viewport frame. Kept in one string (the DOM stub stores innerHTML verbatim, and the real
       browser lays it out) so a harness can count node boxes without measuring drawn geometry. */
    renderMinimap() {
        const box = document.getElementById('minimap');
        if (!box) return;
        const bounds = this._minimapBounds();
        if (!bounds) {
            box.innerHTML = '';
            return;
        }
        const scale = this._minimapScale(bounds, MINIMAP_SIZE);
        const ids = Object.keys(this.nodes);
        const states = this.disableStates();
        let html = '';
        ids.forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const x = MINIMAP_PAD + (el.offsetLeft - bounds.minX) * scale;
            const y = MINIMAP_PAD + (el.offsetTop - bounds.minY) * scale;
            const w = Math.max(2, (el.offsetWidth || 240) * scale);
            const h = Math.max(2, (el.offsetHeight || 80) * scale);
            const off = states[id] !== 'on';
            html += '<i class="minimap-node' + (off ? ' mm-off' : '') + '" style="left:' + x.toFixed(1) + 'px;top:' + y.toFixed(1) + 'px;width:' + w.toFixed(1) + 'px;height:' + h.toFixed(1) + 'px"></i>';
        });
        // The viewport frame: the world rectangle the canvas currently shows, mapped the same way.
        const vw = (this.workspace && this.workspace.clientWidth) || 1200;
        const vh = (this.workspace && this.workspace.clientHeight) || 700;
        const vLeft = (0 - this.panX) / this.zoom;
        const vTop = (0 - this.panY) / this.zoom;
        const vx = MINIMAP_PAD + (vLeft - bounds.minX) * scale;
        const vy = MINIMAP_PAD + (vTop - bounds.minY) * scale;
        const vwid = Math.max(4, (vw / this.zoom) * scale);
        const vhei = Math.max(4, (vh / this.zoom) * scale);
        html += '<i class="minimap-view" style="left:' + vx.toFixed(1) + 'px;top:' + vy.toFixed(1) + 'px;width:' + vwid.toFixed(1) + 'px;height:' + vhei.toFixed(1) + 'px"></i>';
        box.innerHTML = html;
    },

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
        this._clearViewAnim(); /* a restore/load is a placement, not a glide to animate */
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
            /* A history entry has to be a SNAPSHOT. Handing out the live array let
               connectNodes' push and _undoConnection's splice rewrite every EARLIER entry
               retroactively, so wiring two nodes added no undo step at all (the identity test
               below compared the same array to itself) and the next Ctrl+Z deleted a node the
               user never added instead of removing the wire. Connections are whole entries that
               get added or removed, never mutated in place, so a copy of each {from,to} is all
               it takes. */
            connections: (this.connections || []).map((c) => ({ from: c.from, to: c.to })),
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
        /* Undo can walk the model back onto the saved baseline (or off it), so the flag is
           recomputed here — _pushState is suppressed during a history restore. */
        this._refreshDirty();
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
            /* Keep the screen-reader name equal to whatever the header actually shows
               (custom name or the type's current-language label). */
            el.setAttribute('aria-label', titleEl.textContent);
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
        /* The outline is a pure read of the model, and saveState is the ONE chokepoint
           every structural change (add / delete / rename / enable / undo / load) passes
           through — so the list can never drift from the graph. Kept in a try/catch and
           guarded on `typeof`, because a canvas-only harness (which loads just this file)
           has no Outline, and a broken sidebar must never take down a state write. */
        if (typeof Outline !== 'undefined' && Outline.render) {
            try {
                Outline.render();
            } catch (e) {
                console.error('outline render failed', e);
            }
        }
        /* Recompute dirty BEFORE the autosave hook: addNode's saveState runs while the canvas was
           still clean, so gating first would arm autosave only from the SECOND change onward. */
        this._refreshDirty();
        /* Autosave hangs off this same chokepoint: every structural change passes here, so
           the debounced file-save needs no per-caller wiring. Guarded and try/caught for the
           same reason as Outline — a canvas-only harness has no workflow, and a failed
           autosave schedule must never take down a state write. */
        if (typeof workflow !== 'undefined' && workflow.scheduleAutosave) {
            try {
                workflow.scheduleAutosave();
            } catch (e) {
                console.error('autosave schedule failed', e);
            }
        }
        /* Every structural change re-checks the edit-time diagnostics (badges, output
           columns, cost) on a debounce; a failed request keeps the last picture. */
        if (typeof Diagnostics !== 'undefined' && Diagnostics.schedule) {
            try {
                Diagnostics.schedule();
            } catch (e) {
                console.error('diagnostics schedule failed', e);
            }
        }
    },

    /* Baseline the dirty flag at the point the canvas matches a file on disk: after a
       successful save, a load-by-name, or boot's re-fetch of the remembered file. The
       empty canvas a 新建 leaves is also clean (nothing to save). */
    markSaved() {
        this._cleanState = JSON.stringify(this.getState());
        this.dirty = false;
        this._renderDirty();
    },

    _refreshDirty() {
        var clean;
        if (this._cleanState === null) {
            clean = Object.keys(this.nodes).length === 0;
        } else {
            clean = JSON.stringify(this.getState()) === this._cleanState;
        }
        this.dirty = !clean;
        this._renderDirty();
    },

    _renderDirty() {
        if (typeof document === 'undefined' || !document.getElementById) return;
        var el = document.getElementById('dirty-indicator');
        if (!el) return;
        el.textContent = this.dirty ? '●' : '';
        el.title = this.dirty && typeof I18n !== 'undefined' ? I18n.t('canvas.dirtyUnsaved') : '';
        el.setAttribute('aria-hidden', this.dirty ? 'false' : 'true');
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

    /* Paint the edit-time diagnostics: a count badge + a red frame on every node that
       has a problem, its `title` listing the reasons, and a click that selects and
       scrolls to the node (so a badge on an off-screen box is actionable). Fed by
       Diagnostics.recompute — the canvas holds no opinion about what is wrong, it only
       draws what it is told. */
    _applyValidationVisuals(perNode) {
        const map = perNode || {};
        Object.keys(this.nodes).forEach((id) => {
            const el = this._nodeEl(id);
            if (!el) return;
            const problems = map[id] || [];
            const invalid = problems.length > 0;
            el.classList.toggle('node-invalid', invalid);
            const badge = el.querySelector('.node-validate-badge');
            if (!badge) return;
            badge.style.display = invalid ? '' : 'none';
            badge.textContent = invalid ? String(problems.length) : '';
            badge.title = invalid ? problems.join('\n') : '';
            badge.onclick = (function (self, nid) {
                return function (ev) {
                    if (ev) ev.stopPropagation();
                    self.selectNode(nid);
                    self._ensureNodeVisible(nid);
                };
            })(this, id);
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

        /* Step 2: layout each component independently (stacked vertically).
           The stack ORDER is the user's, not creation order: sort by the component's
           排布顺序 (the smallest integer found on any of its name nodes). Numbered
           components rise to the top, ascending — a LOWER number sits HIGHER, the same
           convention as 阶段序号. A component whose name node left 排布顺序 blank has no
           preference, so it drops below every numbered one and keeps its creation
           order relative to the other blanks: Array.prototype.sort is stable (ES2019),
           so an untouched canvas — nobody ever set the field — lays out byte-identically. */
        const layoutOrderOf = (comp) => {
            let key = null;
            comp.forEach((nid) => {
                const n = this.nodes[nid];
                if (n && n.type === 'name' && n.params) {
                    const raw = n.params.layout_order;
                    if (raw !== '' && raw !== null && raw !== undefined) {
                        const v = parseInt(raw, 10);
                        if (Number.isFinite(v) && (key === null || v < key)) key = v;
                    }
                }
            });
            return key;
        };
        const ordered = components.slice().sort((a, b) => {
            const ka = layoutOrderOf(a);
            const kb = layoutOrderOf(b);
            if (ka === null && kb === null) return 0;
            if (ka === null) return 1;
            if (kb === null) return -1;
            return ka - kb;
        });
        const allPositions = [];
        const compGap = 40;
        let cursorY = 0;

        ordered.forEach(function (comp) {
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

/* ── Clipboard drawer: a persisted, fine-grained history of what was copied ──
   The working slots `canvas._clipboardData`/`canvas._clipboardNodes` stay exactly as
   they were — last copy wins, in memory only, so Ctrl+C/V and the context menu keep
   their behaviour untouched. The drawer is an ADDITIVE second thing: every copy also
   appends one entry to a persisted list under its own localStorage key, and the user
   can paste, rename, pin, delete or clear any single entry. It is deliberately NOT
   part of getState()/the draft: copied content is view state, and mixing it into the
   model would make an unrelated paste an undo step of the graph's saved file.
   Paste funnels through the SAME `canvas._pasteAt` the keyboard/menu already use — a
   second paste implementation is exactly the drift this repo keeps paying for. */
const CLIPBOARD_MAX = 50;

const Clipboard = {
    items: [],
    _seq: 0,
    _query: '',

    /* localStorage keys are separate from the canvas draft on purpose: an item the
       user copied must survive a reload yet never leak into the workflow file. */
    load() {
        this.items = [];
        let raw = null;
        try {
            raw = localStorage.getItem('crawler_clipboard');
        } catch (e) {
            return;
        }
        if (!raw) return;
        try {
            const parsed = JSON.parse(raw);
            if (parsed && Array.isArray(parsed.items)) {
                this.items = parsed.items.filter((it) => it && typeof it === 'object' && it.kind);
            }
        } catch (e) { /* a corrupt clipboard is an empty clipboard, not a crash on load */ }
    },

    save() {
        try {
            localStorage.setItem('crawler_clipboard', JSON.stringify({ items: this.items }));
        } catch (e) { /* quota/serialization can never take down a copy */ }
    },

    reset() {
        this.items = [];
        this._seq = 0;
        this._query = '';
    },

    /* Another tab wrote the same key; this tab's in-memory items are now stale. A storage
       event fires only in the OTHER tabs (never the one that called setItem), so reloading
       from localStorage here is exactly the cross-tab pull — no echo, no loop. */
    onStorageEvent(e) {
        if (!e || e.key !== 'crawler_clipboard') return;
        this.load();
        this.render();
    },

    /* A copy is a silent add: the node/nodes path already fires its own toast, so a
       second one would overwrite the copy toast every existing test asserts. */
    add(entry) {
        const rec = {
            id: 'clip-' + Date.now().toString(36) + '-' + (this._seq++),
            kind: entry.kind,
            payload: JSON.parse(JSON.stringify(entry.payload)),
            label: entry.label || this._defaultLabel(entry.kind, entry.payload),
            pinned: false,
            ts: Date.now(),
        };
        this.items.push(rec);
        if (this.items.length > CLIPBOARD_MAX) this._evict();
        this.save();
        this.render();
        return rec.id;
    },

    /* Drop the single oldest UNPINNED entry; a board of only pinned entries is allowed
       to sit one over the cap rather than silently evict something the user kept. */
    _evict() {
        let oldest = -1;
        for (let i = 0; i < this.items.length; i++) {
            if (!this.items[i].pinned && (oldest < 0 || this.items[i].ts < this.items[oldest].ts)) oldest = i;
        }
        if (oldest >= 0) this.items.splice(oldest, 1);
    },

    _defaultLabel(kind, payload) {
        if (kind === 'node') return String((payload && (payload.title || payload.type)) || 'node');
        if (kind === 'nodes') return I18n.t('clipboard.kindNodes', { n: payload ? payload.length : 0 });
        const first = String(payload || '').split('\n')[0].trim();
        return first.length > 40 ? first.slice(0, 40) + '…' : first;
    },

    get(id) {
        for (let i = 0; i < this.items.length; i++) if (this.items[i].id === id) return this.items[i];
        return null;
    },

    remove(id) {
        this.items = this.items.filter((it) => it.id !== id);
        this.save();
        this.render();
    },

    clearAll() {
        /* An explicit "清空" wins over pins (a pin only protects against cap-eviction). */
        this.items = [];
        this.save();
        this.render();
        if (typeof showToast === 'function') showToast(I18n.t('toast.clipboardCleared'));
    },

    togglePin(id) {
        const it = this.get(id);
        if (!it) return;
        it.pinned = !it.pinned;
        this.save();
        this.render();
    },

    rename(id) {
        const it = this.get(id);
        if (!it) return Promise.resolve(false);
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.rename'),
            input: { value: it.label || '' },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('dialog.confirm'), primary: true },
            ],
        })).then((answer) => {
            if (answer === null || answer === undefined) return false;
            const text = String(answer).trim();
            if (text) it.label = text;
            this.save();
            this.render();
            return true;
        });
    },

    /* Add a free-text entry from the drawer's own "add text" button — the ONLY text
       source, so we never call navigator.clipboard.readText (unavailable over plain
       http, and the repo consistently refuses to guess at a hidden clipboard). */
    addText() {
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.addPrompt'),
            input: { placeholder: I18n.t('clipboard.addPrompt'), value: '' },
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('dialog.confirm'), primary: true },
            ],
        })).then((answer) => {
            if (answer === null || answer === undefined) return null;
            const text = String(answer);
            if (!text.trim()) return null;
            const id = this.add({ kind: 'text', payload: text });
            if (typeof showToast === 'function') showToast(I18n.t('toast.clipboardAdded'));
            return id;
        });
    },

    /* nodeRecordFromText mirrors importNodeFromJson's validation exactly: a known type
       and a params object, nothing else mints a node. */
    nodeRecordFromText(text) {
        let parsed;
        try {
            parsed = JSON.parse(String(text).trim());
        } catch (e) {
            return null;
        }
        if (!parsed || typeof parsed !== 'object'
            || canvas._VALID_NODE_TYPES.indexOf(parsed.type) < 0
            || typeof parsed.params !== 'object' || parsed.params === null) {
            return null;
        }
        return { type: parsed.type, title: String(parsed.title || ''), params: parsed.params };
    },

    /* Paste loads the chosen entry into the working slot and runs the shared funnel, so
       a drawer paste can never differ from a Ctrl+V paste of the same record. */
    paste(id, pos) {
        const it = this.get(id);
        if (!it || (it.kind !== 'node' && it.kind !== 'nodes')) return null;
        const copy = JSON.parse(JSON.stringify(it.payload));
        if (it.kind === 'node') {
            canvas._clipboardNodes = null;
            canvas._clipboardData = copy;
            return canvas._pasteAt(pos || null);
        }
        canvas._clipboardData = null;
        canvas._clipboardNodes = copy;
        return canvas._pasteAt(pos || null);
    },

    /* A text entry whose content is a node JSON becomes a node; otherwise refuse BY
       NAME with the same toast import uses — never silently mint a broken box. */
    insertText(id, pos) {
        const it = this.get(id);
        if (!it || it.kind !== 'text') return null;
        const rec = this.nodeRecordFromText(it.payload);
        if (!rec) {
            if (typeof showToast === 'function') showToast(I18n.t('toast.nodeJsonInvalid'));
            return null;
        }
        canvas._clipboardNodes = null;
        canvas._clipboardData = rec;
        return canvas._pasteAt(pos || null);
    },

    /* Text → the OS clipboard, reusing the secure-context-or-dialog fallback shape the
       node JSON copy already established (a failed write shows the text, never a lie). */
    copyText(id) {
        const it = this.get(id);
        if (!it || it.kind !== 'text') return Promise.resolve(false);
        const text = String(it.payload);
        const notify = () => {
            if (typeof showToast === 'function') showToast(I18n.t('toast.clipboardTextCopied'));
            return true;
        };
        if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text).then(notify, () => this._showTextFallback(text));
        }
        return this._showTextFallback(text);
    },

    _showTextFallback(text) {
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.copy'),
            input: { value: text },
            buttons: [{ label: I18n.t('dialog.confirm'), primary: true }],
        })).then(() => true);
    },

    _filtered() {
        const q = this._query.trim().toLowerCase();
        const list = this.items.slice();
        list.sort((a, b) => (b.pinned - a.pinned) || (b.ts - a.ts));
        if (!q) return list;
        return list.filter((it) => (String(it.label).toLowerCase().indexOf(q) >= 0) || (it.kind.indexOf(q) >= 0));
    },

    _esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },

    render() {
        const box = document.getElementById('clipboard-list');
        if (!box) return;
        const list = this._filtered();
        if (!list.length) {
            box.innerHTML = '<div class="clip-empty">' + this._esc(I18n.t('clipboard.empty')) + '</div>';
            return;
        }
        let html = '';
        list.forEach((it) => {
            const badge = it.kind === 'node'
                ? I18n.t('clipboard.kindNode')
                : it.kind === 'nodes'
                    ? I18n.t('clipboard.kindNodes', { n: (it.payload || []).length })
                    : I18n.t('clipboard.kindText');
            const label = this._esc(it.label || '');
            let actions = '<button class="clip-btn" type="button" data-clip-action="pin" data-clip-id="'
                + it.id + '" title="' + this._esc(I18n.t(it.pinned ? 'clipboard.unpin' : 'clipboard.pin')) + '">'
                + (it.pinned ? '★' : '☆') + '</button>';
            if (it.kind === 'node' || it.kind === 'nodes') {
                actions += '<button class="clip-btn" type="button" data-clip-action="paste" data-clip-id="'
                    + it.id + '">' + this._esc(I18n.t('clipboard.paste')) + '</button>';
            }
            if (it.kind === 'text') {
                actions += '<button class="clip-btn" type="button" data-clip-action="copy" data-clip-id="'
                    + it.id + '">' + this._esc(I18n.t('clipboard.copy')) + '</button>';
                actions += '<button class="clip-btn" type="button" data-clip-action="insert" data-clip-id="'
                    + it.id + '">' + this._esc(I18n.t('clipboard.insert')) + '</button>';
            }
            actions += '<button class="clip-btn" type="button" data-clip-action="rename" data-clip-id="'
                + it.id + '">' + this._esc(I18n.t('clipboard.rename')) + '</button>';
            actions += '<button class="clip-btn clip-danger" type="button" data-clip-action="delete" data-clip-id="'
                + it.id + '">' + this._esc(I18n.t('clipboard.delete')) + '</button>';
            const isNode = (it.kind === 'node' || it.kind === 'nodes');
            const dragAttrs = isNode
                ? ' draggable="true" title="' + this._esc(I18n.t('clipboard.dragHint')) + '"'
                : '';
            html += '<div class="clip-row' + (it.pinned ? ' clip-pinned' : '') + '"' + dragAttrs + ' data-clip-id="' + it.id + '">'
                + '<span class="clip-badge">' + this._esc(badge) + '</span>'
                + '<span class="clip-label" title="' + label + '">' + label + '</span>'
                + '<span class="clip-actions">' + actions + '</span>'
                + '</div>';
        });
        box.innerHTML = html;
    },

    onAction(e) {
        const btn = e.target && e.target.closest ? e.target.closest('[data-clip-action]') : null;
        if (!btn) return;
        const action = btn.getAttribute('data-clip-action');
        const id = btn.getAttribute('data-clip-id');
        if (action === 'paste') this.paste(id, null);
        else if (action === 'insert') this.insertText(id, null);
        else if (action === 'copy') this.copyText(id);
        else if (action === 'rename') this.rename(id);
        else if (action === 'pin') this.togglePin(id);
        else if (action === 'delete') this.remove(id);
    },

    setQuery(v) {
        this._query = String(v || '');
        this.render();
    },

    requestClearAll() {
        return Promise.resolve(showDialog({
            message: I18n.t('clipboard.clearConfirm'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: null },
                { label: I18n.t('clipboard.clear'), value: 'clear', primary: true },
            ],
        })).then((answer) => {
            if (answer === 'clear') {
                this.clearAll();
                return true;
            }
            return false;
        });
    },
};

/* The drawer is a right-side slide-in; opening re-renders so a board that filled while
   closed (e.g. by an earlier copy) is current the moment the user sees it. */
function toggleClipboardDrawer() {
    const drawer = document.getElementById('clipboard-drawer');
    if (!drawer) return;
    if (drawer.classList.contains('open')) {
        drawer.classList.remove('open');
    } else {
        drawer.classList.add('open');
        Clipboard.render();
    }
}

/* The keyboard-shortcut cheat sheet: an overlay opened from the View menu, `?` or F1 and
   closed by its button, Escape, or a click on the backdrop. It paints a static list of the
   shortcuts the canvas ACTUALLY binds (see the keydown handler) — never a guessed table. */
function openShortcutsHelp() {
    const box = document.getElementById('help-overlay');
    if (box) box.classList.add('open');
}

function closeShortcutsHelp() {
    const box = document.getElementById('help-overlay');
    if (box) box.classList.remove('open');
}

function toggleShortcutsHelp() {
    const box = document.getElementById('help-overlay');
    if (!box) return;
    if (box.classList.contains('open')) closeShortcutsHelp();
    else openShortcutsHelp();
}
