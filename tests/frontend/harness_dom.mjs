/* Minimal browser world for running the REAL frontend JS under plain node.
 *
 * Why hand-rolled instead of jsdom: this repo is a Python project with a
 * zero-build-step rule — no package.json, nothing to npm-install. The only
 * browser surface the tested code paths actually touch is a registry of stub
 * elements, captured event handlers, and a resolved fetch. That is small
 * enough to fake faithfully, and faithful enough that a regression in the
 * real files (not in a mirror copy) fails the test.
 */

export function makeEl(tag = 'div', id = '') {
    const el = {
        tagName: String(tag).toUpperCase(),
        id,
        style: {},
        dataset: {},
        children: [],
        value: '',
        checked: false,
        innerHTML: '',
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
        _classes: new Set(),
        _text: '',
    };
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
        toggle: (c) => (el._classes.has(c) ? el._classes.delete(c) : el._classes.add(c)),
    };
    Object.defineProperty(el, 'className', {
        get: () => Array.from(el._classes).join(' '),
        set: (v) => {
            el._classes = new Set(String(v).split(/\s+/).filter(Boolean));
        },
    });
    el.appendChild = (child) => {
        el.children.push(child);
        return child;
    };
    el.removeChild = (child) => {
        const i = el.children.indexOf(child);
        if (i >= 0) el.children.splice(i, 1);
        return child;
    };
    el.querySelectorAll = (sel) => Array.from(el._subsets(sel) || []);
    el.querySelector = (sel) => {
        /* Real pages answer with the first matching descendant; the canvas code
           only ever asks for its fixed header/title/action children and guards
           misses. A stable per-(el,selector) child satisfies both the null
           checks and the stamping the state tests assert on. */
        el._subs ||= {};
        if (!el._subs[sel]) {
            el._subs[sel] = makeEl('span', `${el.id || 'anon'}:${sel}`);
            el.children.push(el._subs[sel]);
        }
        return el._subs[sel];
    };
    /* Selectors whose product code reads more than one child back. A single stub
       would collapse the pair (and canvas.js wires the edit and delete buttons by
       index), so those selectors get distinct children; the FIRST is still the one
       `querySelector(sel)` answers with, which keeps every existing assertion
       pointing at the same element. */
    const MULTIPLICITY = { '.node-action-btn': 2, '.node-port': 2 };
    el._subsets = (sel) => {
        const count = MULTIPLICITY[sel] || 1;
        return Array.from({ length: count }, (_, index) => el.querySelector(count === 1 ? sel : `${sel}\u0000${index}`));
    };
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
    el.click = () => {};
    el.remove = () => {};
    el.after = () => {};
    el.closest = () => null;
    el.insertAdjacentHTML = () => {};
    el.scrollIntoView = () => {};
    el.getBoundingClientRect = () => ({ left: 0, top: 0, right: 120, bottom: 60, width: 120, height: 60 });
    return el;
}

/** A document whose getElementById never returns null. */
export function makeDocument() {
    const registry = new Map();
    const handlers = { document: {}, window: {} };
    const byId = (id) => {
        if (!registry.has(id)) registry.set(id, makeEl('div', id));
        return registry.get(id);
    };
    const body = byId('__body');
    body.dataset.lang = 'en';
    const doc = {
        body,
        documentElement: makeEl('html'),
        registry,
        getElementById: byId,
        createElement: (tag) => {
            const el = makeEl(tag);
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
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener: (type, fn) => (handlers.document[type] ||= []).push(fn),
        removeEventListener: () => {},
    };
    return { doc, handlers, byId };
}

/** Fire a mousedown through every captured document listener. */
export function dispatchMousedown(handlers, target) {
    (handlers.document.mousedown || []).forEach((fn) => fn({ type: 'mousedown', target, preventDefault() {}, stopPropagation() {} }));
}

/** Fire an event on one stub element, the way a real click bubbles to it. */
export function dispatchOn(el, type, ev = {}) {
    ((el && el._events && el._events[type]) || []).forEach((fn) => fn({ type, ...ev }));
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
        setTimeout: (fn) => setTimeout(fn, 0),
        clearTimeout: () => {},
        setInterval: () => 0,
        clearInterval: () => {},
        /* The canvas schedules connection repaints through rAF; there is no
           pixel world to keep in sync, and a callback firing after the
           scenario ends would only crash the process — so drop the frame. */
        requestAnimationFrame: () => {},
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
        getComputedStyle: () => ({ getPropertyValue: () => '' }),
        ResizeObserver: undefined,
        URLSearchParams,
        __handlers: handlers,
        __byId: byId,
        __stored: stored,
    };
    sandbox.window = sandbox;
    sandbox.innerWidth = 1920;
    sandbox.innerHeight = 1080;
    sandbox.addEventListener = (type, fn) => (handlers.window[type] ||= []).push(fn);
    sandbox.removeEventListener = () => {};
    sandbox.location = { href: 'http://localhost:5000/', origin: 'http://localhost:5000' };
    sandbox.navigator = { clipboard: { writeText: () => Promise.resolve() } };
    sandbox.echarts = {
        init: () => ({ setOption() {}, resize() {}, on() {}, dispose() {}, showLoading() {}, hideLoading() {} }),
        registerTheme() {},
    };
    return sandbox;
}
