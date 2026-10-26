/* The server's node-type catalogue — what types exist, how the palette words them, and the
   parameters a new node starts with.

   ``nodes/catalog.py`` declares the types and ``nodes/defaults.py`` the seeds; this module only
   carries the answer to the canvas. The canvas keeps a cold-page fallback (its own list and
   seeds) which ``tests/unit/test_node_plugins.py`` pins against this payload, so the two cannot
   drift; once this answer arrives, it is what the canvas reads.

   A failure is NAMED, never silently replaced by a guess: without this payload the canvas falls
   back to its pinned table, and the toast says the server's catalogue could not be read. */
const NodeTypes = {
    _types: null,
    _failure: '',

    load() {
        return fetch('/api/node-types')
            .then(function (resp) {
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return resp.json();
            })
            .then(function (body) {
                const types = (body && Array.isArray(body.types)) ? body.types : [];
                if (!types.length) throw new Error('the catalogue answered with no types');
                NodeTypes._types = types;
                NodeTypes._failure = '';
                document.dispatchEvent(new CustomEvent('node-types-loaded'));
            })
            .catch(function (err) {
                NodeTypes._types = null;
                NodeTypes._failure = String((err && err.message) || err);
                console.error('node-type catalogue failed to load:', NodeTypes._failure);
                if (typeof showToast === 'function' && typeof I18n !== 'undefined') {
                    showToast(I18n.t('toast.nodeTypesFailed', { err: NodeTypes._failure }), 8000);
                }
                document.dispatchEvent(new CustomEvent('node-types-failed'));
            });
    },

    ready() {
        return !!this._types;
    },

    failure() {
        return this._failure;
    },

    all() {
        return this._types ? this._types.slice() : [];
    },

    entry(type) {
        const list = this._types || [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].type === type) return list[i];
        }
        return null;
    },

    types() {
        return (this._types || []).map(function (t) { return t.type; });
    },

    /* A deep copy: seeding a node must never share an object with the payload, or two nodes of
       one type would edit each other's parameters. ``null`` means "the server did not freeze
       this type's seeds" (source derives them from the crawl matrix), never "no parameters". */
    defaults(type) {
        const entry = this.entry(type);
        if (!entry || !entry.defaults) return null;
        return JSON.parse(JSON.stringify(entry.defaults));
    },

    labelKey(type) {
        const entry = this.entry(type);
        return entry ? String(entry.labelKey || '') : '';
    },

    category(type) {
        const entry = this.entry(type);
        return entry ? String(entry.category || '') : '';
    },
};

window.NodeTypes = NodeTypes;
