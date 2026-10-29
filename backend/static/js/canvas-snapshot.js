/* canvas-snapshot.js — 模型快照与撤销：getState/restoreState、连接重映射与撤销历史（相机不在快照里）

 * Split out of the `canvas` object in `canvas.js` on 2026-10-29. `canvas` stays ONE global (the
 * page's markup and every panel call `canvas.x()` by name), so this file does not declare a second
 * object: it ASSIGNS its members, which is the only way a later script can add methods to a
 * top-level `const`. The member lines are the original bytes, unchanged and un-reindented, wrapped
 * in an `Object.assign` call whose opener sits alone on its own line. index.html loads this right
 * after `canvas.js`, and `tests/frontend/splits.json` lists it as a companion, so a harness naming
 * the canvas receives the section too.
 */
Object.assign(canvas, {
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

    /**
     * Resolve a file's `{from,to}` ids against the ids the canvas actually ended
     * up handing out, so a wire reconnects to the node it left from.
     *
     * The old code mapped by POSITION — `findIndex` into the file's node array,
     * then `Object.keys(canvas.nodes)[thatIndex]` — but `Object.keys` returns a
     * dict's integer-like keys first, in ascending numeric order, not insertion
     * order. So a file with ids `['n9','2']` reads back as keys `['2','n9']`, and
     * the wire authored as `n9 → 2` was written as `2 → n9` — the whole graph
     * silently rewired to other nodes, with no refusal and nothing on screen to
     * explain it. Identity is looked up by key now, never by array slot.
     *
     * @param {Array<{from:string,to:string}>} connections raw file connections
     * @param {Object<string,string>} idMap keyed by the requested file id → the id
     *   `addNode` actually returned (equal unless the id was rejected and re-minted)
     * @returns {Array<{from:string,to:string}>} wires whose both ends still exist
     */
    _remapConnections(connections, idMap) {
        const map = idMap || {};
        return (Array.isArray(connections) ? connections : [])
            .filter((c) => c && map[c.from] && map[c.to])
            .map((c) => ({ from: map[c.from], to: map[c.to] }));
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
        /* Keyed by the id the state ASKED for, not the id the canvas kept: a
           malformed or already-taken id is re-minted by addNode, and the wires
           have to find the node that was actually built. */
        var idMap = {};
        nodeList.forEach(function (n) {
            const id = canvas.addNode(n.type, n.x, n.y, n.id);
            idMap[n.id] = id;
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
        this.connections = this._remapConnections(state.connections, idMap);
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
    /* Run `fn` while every per-change history entry is suppressed, then record the
       net change as ONE undo step. A file load rebuilds node by node, so without
       this a restored snapshot would leave one entry per node — Ctrl+Z would peel
       the snapshot apart instead of returning to the canvas it replaced. */
    batchHistory(fn) {
        const outerSaving = this._historySaving;
        this._historySaving = true;
        try {
            return fn();
        } finally {
            this._historySaving = outerSaving;
            if (!outerSaving) this.saveState();
        }
    },

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
        /* The selection is view-only, so restoreState never rebuilds it: an undo that removed
           a node left its id in ``selectedNodes`` as a ghost. ``alignSelected`` then read
           ``el.style`` on a null box (TypeError), and Delete hit the ghost and still toasted
           「节点已删除」 for a node that was already gone. Prune the selection to what survived,
           exactly as the delete paths do. */
        this.selectedNodes = this.selectedNodes.filter((id) => this.nodes[id]);
        if (this.selectedNode && !this.nodes[this.selectedNode]) this.selectedNode = null;
        if (this._linkFromId && !this.nodes[this._linkFromId]) this._linkFromId = null;
        /* An undo/redo may have removed the node the settings panel is showing. */
        this.closeSettingsIfStale();
        /* Undo can walk the model back onto the saved baseline (or off it), so the flag is
           recomputed here — _pushState is suppressed during a history restore. */
        this._refreshDirty();
    },
});
