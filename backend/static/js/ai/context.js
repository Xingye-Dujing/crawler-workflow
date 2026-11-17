/* Page context for the assistant. The browser sends IDs and, for an unsaved canvas, the draft the
 * page already owns; the server re-reads every saved fact from its own stores. */
const AIContext = {
    manual: { dataset_id: '', run_id: '' },

    setManual(patch) {
        this.manual = Object.assign({}, this.manual, patch || {});
    },

    canvasDraft() {
        try {
            if (typeof canvas !== 'undefined' && canvas && typeof canvas.serializeDraft === 'function') {
                const draft = canvas.serializeDraft();
                if (draft && typeof draft === 'object') {
                    /* ``getState()`` keys nodes BY ID (``{node-1: {...}}``) while the server's
                       context builder takes a LIST and refuses anything else by name — the map
                       was sent as-is, so the canvas section of the context was dropped and the
                       bar read “节点 undefined” (an object has no ``.length``). Unwrap it here,
                       where the page's model is known, and send the shape the contract names. */
                    const raw = draft.nodes && typeof draft.nodes === 'object' ? draft.nodes : {};
                    const nodes = Array.isArray(raw) ? raw : Object.values(raw);
                    const sel = canvas.selectedNode;
                    return {
                        unsaved: true,
                        nodes: nodes,
                        connections: Array.isArray(draft.connections) ? draft.connections : [],
                        selectedNode: (sel && typeof sel === 'object') ? String(sel.id || '') : String(sel || ''),
                    };
                }
            }
        } catch (e) {
            /* a half-restored canvas must not stop the assistant from opening */
        }
        return null;
    },

    collect() {
        const draft = this.canvasDraft();
        const context = {
            page: 'canvas',
            dataset_id: this.manual.dataset_id || '',
            run_id: this.manual.run_id || '',
        };
        if (draft) context.canvas = draft;
        return context;
    },

    summary(context) {
        const items = [];
        if (context.canvas) items.push((context.canvas.nodes || []).length + ' nodes');
        if (context.dataset_id) items.push('dataset');
        if (context.run_id) items.push('run');
        return items.join(' · ');
    },
};
window.AIContext = AIContext;
