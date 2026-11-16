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
                    return {
                        unsaved: true,
                        nodes: draft.nodes || [],
                        connections: draft.connections || draft.edges || [],
                        selectedNode: canvas.selectedNode ? String(canvas.selectedNode.id || '') : '',
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
