/* The server's node-type catalogue — what types exist, how the palette words them, the parameters
   a new node starts with, and the schema its settings panel renders.

   The declarations are the capability manifests under ``backend/capabilities_kernel/nodes/``;
   ``/api/node-types`` projects them and ``node-types-fallback.js`` is the generated cold-page copy
   that loads before this module (one page already has a usable list while the fetch is in flight).
   This module holds no type, label or default table of its own.

   A failure is NAMED, never silently replaced by a guess: the generated fallback stays in use and
   the toast says the server's catalogue could not be read. */
/* A page loads this once; a harness may concatenate the same module through two companions.
   Keeping the first instance makes that harmless (one object, never a redeclaration). */
var NodeTypes = window.NodeTypes || {
    _types: null,
    _charts: null,
    _operators: null,
    _failure: '',

    /* The generated fallback is a separate script; read it lazily so the load order of the two
       modules never decides whether a cold page has a catalogue. */
    _seed() {
        if (!this._types && typeof NODE_TYPE_CATALOGUE !== 'undefined' && NODE_TYPE_CATALOGUE
            && Array.isArray(NODE_TYPE_CATALOGUE.types)) {
            this._types = NODE_TYPE_CATALOGUE.types.slice();
            this._charts = Array.isArray(NODE_TYPE_CATALOGUE.charts) ? NODE_TYPE_CATALOGUE.charts.slice() : [];
            this._operators = Array.isArray(NODE_TYPE_CATALOGUE.operators) ? NODE_TYPE_CATALOGUE.operators.slice() : [];
        }
        return this._types;
    },

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
                /* The chart profiles are the same declaration the fallback carries; a page whose
                   answer omits them keeps the generated copy rather than emptying the chart form. */
                if (body && Array.isArray(body.charts) && body.charts.length) {
                    NodeTypes._charts = body.charts;
                }
                /* Same rule for the operator tree: an answer without it keeps the generated copy
                   rather than emptying the 步骤 dropdown. */
                if (body && Array.isArray(body.operators) && body.operators.length) {
                    NodeTypes._operators = body.operators;
                }
                NodeTypes._failure = '';
                NodeTypes._announce('node-types-loaded');
            })
            .catch(function (err) {
                /* Keep the generated fallback: it is the same catalogue, and an empty list would
                   read as "this product has no node types". */
                NodeTypes._failure = String((err && err.message) || err);
                console.error('node-type catalogue failed to load:', NodeTypes._failure);
                if (typeof showToast === 'function' && typeof I18n !== 'undefined') {
                    showToast(I18n.t('toast.nodeTypesFailed', { err: NodeTypes._failure }), 8000);
                }
                NodeTypes._announce('node-types-failed');
            });
    },

    /* A page has an event bus; a node harness may not. The answer is still recorded. */
    _announce(name) {
        if (typeof document !== 'undefined' && typeof CustomEvent !== 'undefined') {
            document.dispatchEvent(new CustomEvent(name));
        }
    },

    ready() {
        const list = this._seed();
        return !!(list && list.length);
    },

    failure() {
        return this._failure;
    },

    all() {
        const list = this._seed();
        return list ? list.slice() : [];
    },

    entry(type) {
        const list = this._seed() || [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].type === type) return list[i];
        }
        return null;
    },

    types() {
        return (this._seed() || []).map(function (t) { return t.type; });
    },

    /* A deep copy: seeding a node must never share an object with the payload, or two nodes of
       one type would edit each other's parameters. ``null`` means "the server did not freeze
       this type's seeds" (source derives them from the crawl matrix), never "no parameters". */
    defaults(type) {
        const entry = this.entry(type);
        if (!entry || !entry.defaults) return null;
        return JSON.parse(JSON.stringify(entry.defaults));
    },

    /* The generic form renderer's input: parameter specs in manifest order (may be empty for a
       custom-rendered type such as source). */
    params(type) {
        const entry = this.entry(type);
        return entry && Array.isArray(entry.params) ? JSON.parse(JSON.stringify(entry.params)) : [];
    },

    ui(type) {
        const entry = this.entry(type);
        return entry && entry.ui ? JSON.parse(JSON.stringify(entry.ui)) : null;
    },

    /* Every chart type the visualize node can draw, in panel order. The same declaration decides
       which fields its form shows and which of them validation requires. */
    charts() {
        this._seed();
        return (this._charts || []).slice();
    },

    /* The analysis operators, in the manifest's panel order. The 分析 node's 步骤 dropdown renders
       this; the panel keeps no array of its own. */
    operators() {
        this._seed();
        return (this._operators || []).slice();
    },

    chart(key) {
        this._seed();
        const list = this._charts || [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].key === key) return JSON.parse(JSON.stringify(list[i]));
        }
        return null;
    },

    /* One operator's profile: the settings form renders ``panel`` (its declared boxes) when it has
       any, so a migrated operation needs no block in panels/node-analysis.js. */
    operator(key) {
        this._seed();
        const list = this._operators || [];
        for (let i = 0; i < list.length; i++) {
            if (list[i].id === key) return JSON.parse(JSON.stringify(list[i]));
        }
        return null;
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
