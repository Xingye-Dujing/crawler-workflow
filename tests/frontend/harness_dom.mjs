/* Minimal browser world for running the REAL frontend JS under plain node.
 *
 * Why hand-rolled instead of jsdom: this repo is a Python project with a
 * zero-build-step rule — no package.json, nothing to npm-install. The only
 * browser surface the tested code paths actually touch is a registry of stub
 * elements, captured event handlers, and a resolved fetch. That is small
 * enough to fake faithfully, and faithful enough that a regression in the
 * real files (not in a mirror copy) fails the test.
 */

/* Selector subset the product code actually uses: comma alternatives, and
 * compounds of `tag`, `#id`, `.class`, `[attr]` / `[attr="v"]` and `:not(…)`.
 *
 * A real matcher is what makes the delegated-click and repaint code testable at
 * all: canvas.js finds its connection paths with
 * `.conn-line:not(.temp)` and its ports with `[data-node="x"][data-port="out"]`,
 * and an answer of `null` for every selector would let those functions be
 * deleted from the file without a single test noticing. */
function _matchesPart(el, part) {
    if (!part) return false;
    const tokens = String(part).match(/\[[^\]]*\]|:not\([^)]*\)|[.#]?[\w-]+/g) || [];
    return tokens.every((token) => {
        if (token[0] === '.') return el.classList ? el.classList.contains(token.slice(1)) : false;
        if (token[0] === '#') return el.id === token.slice(1);
        if (token.startsWith(':not(')) return !_matchesPart(el, token.slice(5, -1));
        if (token[0] === '[') {
            const inner = token.slice(1, -1);
            const eq = inner.indexOf('=');
            /* A `[data-port="out"]` selector addresses `dataset.port`, not
               `dataset.dataPort` — the prefix the author writes is the prefix the
               browser strips. */
            const raw = eq < 0 ? inner : inner.slice(0, eq);
            const key = raw.startsWith('data-') ? _camelize(raw.slice(5)) : _camelize(raw);
            if (eq < 0) return el.dataset && el.dataset[key] !== undefined;
            const want = inner.slice(eq + 1).replace(/^["']|["']$/g, '');
            return String(el.dataset ? el.dataset[key] : '') === want;
        }
        return String(el.tagName || '').toUpperCase() === token.toUpperCase();
    });
}

function _camelize(name) {
    return String(name).replace(/-([a-z])/g, (_m, c) => c.toUpperCase());
}

/* Attach `child` under `parent`, carrying the document's element index with it.
 * The index is what makes page-wide `querySelectorAll` work, and a node built by
 * `innerHTML` is as findable as one built by `createElement`. */
function _adopt(child, parent) {
    child.parentElement = parent;
    child.parentNode = parent;
    const world = parent && parent._world;
    if (!world) return child;
    child._world = world;
    child.__unregister = parent.__unregister;
    for (const node of [child, ..._descendants(child, [])]) {
        if (!world.includes(node)) world.push(node);
        node._world = world;
        node.__unregister = parent.__unregister;
    }
    return child;
}

export function matches(el, selector) {
    return String(selector).split(',').some((part) => _matchesPart(el, part.trim()));
}

function _descendants(el, into) {
    (el.children || []).forEach((child) => {
        into.push(child);
        _descendants(child, into);
    });
    return into;
}

/* Parse the markup the product writes into `innerHTML` into real descendants.
 *
 * Without this, `el.innerHTML = '<div class="node-port" data-port="in">'` left the
 * element childless, so `querySelectorAll('.node-port')` could only ever answer
 * with fabricated stubs that carry no class and no dataset. Every function that
 * finds its way around by selector — the port hit-test, the connection repaint,
 * the fold's content/action lookup — was therefore unreachable from a harness, and
 * deleting them would not have turned a test red.
 *
 * The templates in this codebase are hand-written, closed and attribute-simple, so
 * a tag/attribute scanner is enough; it deliberately ignores anything it is not
 * shown, and a malformed fragment yields no children rather than a wrong guess.
 *
 * `innerHTML` itself stays exactly the string the product assigned, so the tests
 * that assert "nothing unescaped reached the markup" keep their meaning.
 */
const _VOID_TAGS = new Set(['br', 'hr', 'img', 'input', 'source', 'path', 'circle', 'rect', 'use', 'line']);

function _parseMarkup(html) {
    const roots = [];
    const stack = [];
    const tagRe = /<\/?([a-zA-Z][\w-]*)((?:\s+[a-zA-Z_:][\w:.-]*\s*=\s*(?:"[^"]*"|'[^']*'|[^\s">]+))*)\s*(\/?)>|([^<]+)/g;
    let match;
    while ((match = tagRe.exec(String(html))) !== null) {
        if (match[4] !== undefined) {
            const text = match[4];
            if (text.trim() && stack.length) stack[stack.length - 1]._text += text;
            continue;
        }
        const closing = match[0][1] === '/';
        const name = match[1];
        if (closing) {
            for (let i = stack.length - 1; i >= 0; i -= 1) {
                if (stack[i].tagName === name.toUpperCase()) {
                    stack.length = i;
                    break;
                }
            }
            continue;
        }
        const el = makeEl(name);
        const attrRe = /([a-zA-Z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s">]+))/g;
        let attr;
        while ((attr = attrRe.exec(match[2] || '')) !== null) {
            const key = attr[1];
            const value = attr[2] ?? attr[3] ?? attr[4] ?? '';
            if (key === 'class') el.className = value;
            else if (key === 'id') el.id = value;
            /* `data-port` is read back as `dataset.port`, in the attribute and in
               the selector alike — so the prefix has to come off both ways. */
            else if (key.startsWith('data-')) el.dataset[_camelize(key.slice(5))] = value;
            else el[key] = value;
        }
        const parent = stack[stack.length - 1];
        if (parent) {
            el.parentElement = parent;
            el.parentNode = parent;
            parent.children.push(el);
        } else {
            roots.push(el);
        }
        if (!match[3] && !_VOID_TAGS.has(name.toLowerCase())) stack.push(el);
    }
    return roots;
}

export function makeEl(tag = 'div', id = '') {
    const el = {
        tagName: String(tag).toUpperCase(),
        id,
        style: {},
        dataset: {},
        children: [],
        value: '',
        checked: false,
        _html: '',
        title: '',
        placeholder: '',
        disabled: false,
        offsetLeft: 10,
        offsetTop: 20,
        offsetWidth: 120,
        offsetHeight: 60,
        scrollTop: 0,
        scrollHeight: 0,
        clientHeight: 600,
        parentElement: null,
        parentNode: null,
        _classes: new Set(),
        _text: '',
    };
    /* A style object that only stores plain assignments breaks the moment product
       code reaches for the CSS custom-property API — which is how the corner
       radius setting is applied (`setProperty('--radius', …)`). */
    el.style.getPropertyValue = function (name) {
        return this[name] === undefined ? '' : String(this[name]);
    };
    el.style.setProperty = function (name, value) {
        this[name] = value;
    };
    el.style.removeProperty = function (name) {
        delete this[name];
    };
    /* Assigning innerHTML rebuilds the subtree, exactly as a browser does, so the
       selectors the product uses afterwards resolve against what it just wrote.
       Attributes become plain fields — an `onclick="…"` in a template is stored as
       a string and never wrapped in a function, which is what lets a test assert
       that no inline handler exists without the harness running one. */
    Object.defineProperty(el, 'innerHTML', {
        get: () => el._html,
        set: (v) => {
            el._html = v === null || v === undefined ? '' : String(v);
            el.children = [];
            el._text = '';
            el._subs = {};
            _parseMarkup(el._html).forEach((child) => {
                el.children.push(child);
                _adopt(child, el);
            });
        },
        configurable: true,
    });
    /* Assigning textContent replaces every descendant in a real browser — which
       is exactly how the panel clears a list before rebuilding it. A plain field
       would let the stub keep stale children and report a duplicate-render bug
       that does not exist (and hide a real one that does). */
    Object.defineProperty(el, 'textContent', {
        get: () => el._text,
        set: (v) => {
            el._text = v === null || v === undefined ? '' : String(v);
            el.children = [];
        },
        configurable: true,
    });
    el.classList = {
        add: (...cs) => cs.forEach((c) => el._classes.add(c)),
        remove: (...cs) => cs.forEach((c) => el._classes.delete(c)),
        contains: (c) => el._classes.has(c),
        /* The two-argument form is the one the product uses to state a desired
           condition rather than flip one, so honouring only the first would make
           a restore fold an unfold (and vice versa) in the harness alone. */
        toggle: (c, force) => {
            const want = force === undefined ? !el._classes.has(c) : !!force;
            if (want) el._classes.add(c);
            else el._classes.delete(c);
            return want;
        },
    };
    /* `Array.from(element.classList)` is how the app reads the body's classes back
       out when it saves the background, so an non-iterable stub silently reported
       "no bg class" and the draft captured the fallback instead of the truth. */
    el.classList[Symbol.iterator] = function* () {
        yield* el._classes;
    };
    Object.defineProperty(el, 'className', {
        get: () => Array.from(el._classes).join(' '),
        set: (v) => {
            el._classes = new Set(String(v).split(/\s+/).filter(Boolean));
        },
    });
    el.appendChild = (child) => {
        el.children.push(child);
        /* Ancestry has to be real, not faked per test: code that delegates a
           click by walking up to the nearest `.node` (which is how the canvas
           avoids inline handlers) cannot be tested at all while `closest`
           answers null for everything. */
        _adopt(child, el);
        return child;
    };
    el.removeChild = (child) => {
        const i = el.children.indexOf(child);
        if (i >= 0) el.children.splice(i, 1);
        child.parentElement = null;
        child.parentNode = null;
        return child;
    };
    /* Real descendants only. `innerHTML` is parsed into a real subtree (see
       _parseMarkup), so the markup the product writes is what its own selectors
       find — and a query that matches nothing answers with nothing. An earlier
       revision invented a child on a miss, which quietly turned "the old
       connection paths were removed" into a phantom path that no assertion could
       tell apart from a real one. */
    el.querySelectorAll = (sel) => _descendants(el, []).filter((child) => matches(child, sel));
    el.querySelector = (sel) => el.querySelectorAll(sel)[0] || null;
    /* Listeners are kept, not dropped: some handlers (the canvas right-click
       menu) hang off a specific element rather than the document, and a harness
       that cannot fire them would have to fake the surrounding logic by hand. */
    el._events = {};
    el.addEventListener = (type, fn) => {
        (el._events[type] ||= []).push(fn);
    };
    el.removeEventListener = (type, fn) => {
        el._events[type] = (el._events[type] || []).filter((f) => f !== fn);
    };
    el.insertAdjacentHTML = () => {};
    el.setAttribute = (k, v) => {
        el[k] = v;
    };
    el.getAttribute = (k) => (el[k] === undefined ? null : el[k]);
    el.focus = () => {};
    el.blur = () => {};
    el.select = () => {};
    el.click = () => dispatchOn(el, 'click');
    el.remove = () => {
        if (el.__unregister) el.__unregister(el);
        if (el.parentElement) el.parentElement.removeChild(el);
    };
    el.after = () => {};
    /* A real parent chain, so delegated handlers — "find the `.node` this click
       landed inside" — are the shipped code path rather than an unenterable one. */
    el.matches = (sel) => matches(el, sel);
    el.closest = (sel) => {
        for (let node = el; node; node = node.parentElement) {
            if (matches(node, sel)) return node;
        }
        return null;
    };
    el.scrollIntoView = () => {};
    el.getBoundingClientRect = () => ({ left: 0, top: 0, right: 120, bottom: 60, width: 120, height: 60 });
    return el;
}

/** A document whose getElementById never returns null.
 *
 * `world` is the flat list of every element the document handed out. Document-wide
 * `querySelectorAll` needs it: `selectNode` clears `.node.selected` from the whole
 * page and `updateConnections` repaints every path, neither of which is reachable
 * from a single root the harness holds. Removing an element takes it out of the
 * list, so "the old paths are gone" is an observation rather than an assumption.
 */
export function makeDocument() {
    const registry = new Map();
    const handlers = { document: {}, window: {} };
    const world = [];
    const register = (el) => {
        if (!world.includes(el)) world.push(el);
        el._world = world;
        el.__unregister = unregisterTree;
        return el;
    };
    const unregisterTree = (el) => {
        const doomed = new Set([el, ..._descendants(el, [])]);
        for (let i = world.length - 1; i >= 0; i -= 1) {
            if (doomed.has(world[i])) world.splice(i, 1);
        }
    };
    /* Ids a scenario has decided do NOT exist. Auto-creation is what lets a
       scenario skip building the whole page, but it also makes "is this element
       already there?" unanswerable — and code branches on exactly that (the run
       detail row toggles by testing for its own id). Listing an id here restores
       the browser's real answer for it. */
    const absent = new Set();
    const byId = (id) => {
        if (absent.has(id)) return null;
        if (!registry.has(id)) registry.set(id, register(makeEl('div', id)));
        return registry.get(id);
    };
    const body = byId('__body');
    body.dataset.lang = 'en';
    const find = (sel, root) => world.filter((el) => (root === undefined || el === root || _descendants(root, []).includes(el)) && matches(el, sel));
    const doc = {
        body,
        documentElement: makeEl('html'),
        registry,
        world,
        absent,
        getElementById: byId,
        /* Empty the page without replacing the document object.
         *
         * A harness that wants a clean canvas between scenarios cannot install a
         * *new* document here: the sandbox's `requestAnimationFrame` and the
         * product's own captured references both outlive that swap, so the frames
         * of scenario two would land in scenario one's queue and the assertions
         * would read elements no listener can see. Clearing in place is the
         * difference between a fresh page and a split one. */
        __reset() {
            world.length = 0;
            registry.clear();
            absent.clear();
            for (const key of Object.keys(handlers.document)) delete handlers.document[key];
            for (const key of Object.keys(handlers.window)) delete handlers.window[key];
            body.children = [];
            Object.keys(body.dataset).forEach((k) => delete body.dataset[k]);
            Object.keys(body._events).forEach((k) => delete body._events[k]);
            body.classList.remove(...Array.from(body._classes));
            register(body);
            body.dataset.lang = 'en';
        },
        createElement: (tag) => {
            const el = register(makeEl(tag));
            let ownId = '';
            /* The browser makes an element findable by getElementById the
               moment its id is set (canvas.addNode relies on exactly this);
               mirror that, or the two APIs would speak about different
               objects and the title-stamping tests would fake their result. */
            Object.defineProperty(el, 'id', {
                get: () => ownId,
                set: (v) => {
                    ownId = v;
                    if (v) registry.set(v, el);
                },
                configurable: true,
            });
            return el;
        },
        /* The connection layer is SVG, built through the namespaced factory;
           without it `startConnection` cannot even be entered. */
        createElementNS: (_ns, tag) => doc.createElement(tag),
        querySelector: (sel) => find(sel)[0] || null,
        querySelectorAll: (sel) => find(sel),
        addEventListener: (type, fn) => (handlers.document[type] ||= []).push(fn),
        removeEventListener: () => {},
        /* An element pulled out of the tree stops matching page-wide queries. */
        __unregister: unregisterTree,
    };
    return { doc, handlers, byId, world, register, unregisterTree };
}

/** Fire a mousedown through every captured document listener. */
export function dispatchMousedown(handlers, target) {
    (handlers.document.mousedown || []).forEach((fn) => fn({ type: 'mousedown', target, preventDefault() {}, stopPropagation() {} }));
}

/** Fire an event through every captured *document* listener.
 *
 * The canvas drags, the connection drop and the context-menu actions all hang off
 * `document.addEventListener`, so a harness that can only fire on one element
 * cannot reach them at all — and `dispatchOn(el, …)` on the document object itself
 * silently finds nothing, because the document keeps its handlers in its own table.
 */
export function dispatchDocument(handlers, type, ev = {}) {
    const event = { type, preventDefault() {}, stopPropagation() {}, target: { closest: () => null }, ...ev };
    (handlers.document[type] || []).forEach((fn) => fn(event));
    return event;
}

/** Fire an event through every captured *window* listener.
 *
 * `window.addEventListener('resize', …)` lands in a different table from both the
 * document's and any element's, so a harness that only has the other two cannot
 * reach a resize handler at all.
 */
export function dispatchWindow(handlers, type, ev = {}) {
    const event = { type, preventDefault() {}, stopPropagation() {}, ...ev };
    (handlers.window[type] || []).forEach((fn) => fn(event));
    return event;
}

/** Fire an event on one stub element, the way a real click lands on it. */
export function dispatchOn(el, type, ev = {}) {
    const event = { type, preventDefault() {}, stopPropagation() {}, target: { closest: () => null }, ...ev };
    ((el && el._events && el._events[type]) || []).forEach((fn) => fn(event));
    return event;
}

/** Make `window` the script's own global, once the context exists.
 *
 * In a browser `window === globalThis`, so `var resumeBar = {…}` is reachable as
 * `window.resumeBar` and every `if (window.X)` guard behaves. Pointing
 * `sandbox.window` at the host object instead leaves those lookups blind to the
 * script's own bindings, so a guard that is true in the browser read as false
 * here — the harness then tested a branch no user ever sees.
 */
export function fixWindow(vm, sandbox) {
    vm.runInContext('globalThis.window = globalThis;', sandbox);
}

/**
 * Event target with an explicit ancestry: closest(sel) answers for every
 * comma-separated part of sel, so "#dashboard-panel, #history-panel" matches
 * when any ancestor is in the chain. The popup-close logic branches purely on
 * this — it is the whole contract of the outside-click guards.
 */
export function makeTarget(ancestors) {
    const set = new Set(ancestors);
    return {
        closest: (sel) => {
            const parts = String(sel).split(',').map((s) => s.trim());
            for (const p of parts) {
                if (set.has(p)) return { _sel: p };
            }
            return null;
        },
    };
}

/** Drain the frames the sandbox has been holding.
 *
 * `requestAnimationFrame` queues rather than runs: the canvas repaints
 * (connections, transform) through rAF, so a callback that never fires leaves
 * `updateConnections` a function no test has ever entered — while a callback that
 * fires the instant it is scheduled can turn one repaint into a loop the scenario
 * never asked for. A test that cares flushes explicitly.
 */
export function flushFrames(sandbox) {
    const pending = sandbox.__frames.splice(0);
    pending.forEach((fn) => fn());
    return pending.length;
}

/** Empty the page, keeping the same document object. See `doc.__reset`. */
export function resetWorld(sandbox) {
    sandbox.document.__reset();
    sandbox.__frames.length = 0;
    return sandbox;
}

export function baseSandbox() {
    const { doc, handlers, byId } = makeDocument();
    const stored = {};
    const sandbox = {
        console,
        JSON,
        Math,
        Number,
        String,
        Boolean,
        Array,
        Object,
        Date,
        RegExp,
        Promise,
        Map,
        Set,
        Error,
        TypeError,
        setTimeout: (fn) => setTimeout(fn, 0),
        clearTimeout: () => {},
        setInterval: () => 0,
        clearInterval: () => {},
        requestAnimationFrame: (fn) => {
            sandbox.__frames.push(fn);
            return sandbox.__frames.length;
        },
        cancelAnimationFrame: () => {},
        document: doc,
        localStorage: {
            getItem: (k) => (k in stored ? stored[k] : null),
            setItem: (k, v) => {
                stored[k] = String(v);
            },
            removeItem: (k) => delete stored[k],
        },
        fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) }),
        alert: () => {},
        confirm: () => true,
        prompt: () => null,
        /* A computed style that always answers '' would make every
           `getComputedStyle(…).getPropertyValue('--radius')` read as "unset", so a
           setting the page writes through style.setProperty could never be read
           back. Falling through to the element's own declarations keeps that loop
           honest; `__computed` lets a scenario pin a stylesheet value the stub has
           no way to know. */
        getComputedStyle: (el) => {
            const own = (el && el.style) || {};
            const pinned = sandbox.__computed || {};
            return {
                getPropertyValue: (name) => {
                    const value = pinned[name] !== undefined ? pinned[name] : own[name];
                    return value === undefined || value === null ? '' : String(value);
                },
                getPropertyValueName: () => '',
                right: pinned.right !== undefined ? pinned.right : own.right || 'auto',
                top: own.top || 'auto',
                transform: own.transform || 'none',
            };
        },
        ResizeObserver: undefined,
        matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
        URLSearchParams,
        URL: { createObjectURL: () => 'blob:stub', revokeObjectURL: () => {} },
        /* The upload panel builds a FormData over a File list. Faking the two
           constructors is enough to *enter* those functions — what they put in
           the body is the assertion, not what a server would do with it. */
        FormData: class FormData {
            constructor() {
                this.entries = [];
            }

            append(key, value) {
                this.entries.push([key, value]);
            }
        },
        File: class File {
            constructor(name, size) {
                this.name = name;
                this.size = size || 0;
                this.type = '';
            }
        },
        Blob: class Blob {
            constructor(parts, options) {
                this.parts = parts;
                this.type = (options && options.type) || '';
                this.size = String(parts || '').length;
            }
        },
        __frames: [],
        __handlers: handlers,
        __byId: byId,
        __stored: stored,
    };
    sandbox.window = sandbox;
    sandbox.innerWidth = 1920;
    sandbox.innerHeight = 1080;
    sandbox.devicePixelRatio = 1;
    sandbox.addEventListener = (type, fn) => (handlers.window[type] ||= []).push(fn);
    sandbox.removeEventListener = () => {};
    sandbox.location = { href: 'http://localhost:5000/', origin: 'http://localhost:5000' };
    sandbox.navigator = { clipboard: { writeText: () => Promise.resolve() }, userAgent: 'node-harness' };
    sandbox.echarts = {
        init: () => ({ setOption() {}, resize() {}, on() {}, dispose() {}, showLoading() {}, hideLoading() {} }),
        registerTheme() {},
    };
    return sandbox;
}

