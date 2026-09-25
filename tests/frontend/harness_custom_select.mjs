/* Drives the REAL dropdown machinery of custom-select.js under node.
 *
 * Three harnesses load this file (`harness_app.mjs`, `harness_cookie_gate.mjs`,
 * `harness_profiles.mjs`) and none of them ever *uses* it: it is there so app.js's
 * boot finds `window.CustomSelect`. So `enhance` / `build` / `open` / `close` /
 * `place` / `scan` / `refreshAll` — the ~600 lines that draw every themed select
 * in the app — had never been entered by a test, and any of them could have been
 * deleted without anything turning red.
 *
 * This harness runs the untouched file against selects built from the same markup
 * shapes `index.html` and `zenviz.js` produce, performs real presses / taps /
 * keydowns, and reports what the control ended up looking like.
 *
 * Usage: node harness_custom_select.mjs <jsDir> <scenarios.json>
 * scenarios = [ { "id", "html", "viewport": {...}, "steps": [ {do: ...} ],
 *                 "ids": ["kw", ...] } ]
 *
 * ── what this driver adds to the stub DOM, and why ─────────────────────────
 *
 * `harness_dom.mjs` fakes the surface the canvas and workflow tests needed. A
 * `<select>` needs four more browser facts, and every one of them is DERIVED
 * from the element's own children rather than hand-set — because the whole
 * contract under test is custom-select's claim that the native control stays the
 * value store, which it states at `wrap.appendChild(sel)`:
 *   · `select.options`       — the option children;
 *   · `select.selectedIndex` — the chosen row, with the browser's default of 0
 *     when nobody picked one, and -1 for a multiple with nothing ticked;
 *   · `select.value`         — the selected option's value;
 *   · `isConnected`          — "still under <body>", which `refreshAll()` prunes
 *     on and which a real DOM answers from the ancestor chain.
 * Plus three generic members the stub simply does not have: `insertBefore` (how
 * `enhance` puts its wrapper where the control was), `contains` (used by the
 * outside-click guard and by `ownsPopup`) and `dispatchEvent` — with bubbling,
 * because a blocked row is *reported to the document* (zenviz.js listens there
 * for `cselect-blocked`), so a non-bubbling dispatch would test a contract the
 * owner cannot hear.
 *
 * Two layout numbers cannot be computed without an engine: `scrollWidth` (how
 * wide the menu's content wants to be) and the anchor's box. A scenario supplies
 * the figure a browser would have measured; what is under test is the arithmetic
 * `place()` performs on it, never the figure itself.
 *
 * Boolean attributes are spelled `multiple="multiple"` in the fixtures because
 * the stub's markup parser only understands `name=value`; HTML accepts that form
 * as true and the product reads the property, never the attribute.
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const [jsDir, scenarioPath] = process.argv.slice(2);
const scenarios = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'));

/* ─── browser surface the stub does not have ─────────────────────────────── */

/* Event objects of the kind the product constructs itself: `new Event('change')`
   and `new CustomEvent('cselect-blocked', {detail})`. */
class DomEvent {
    constructor(type, init) {
        this.type = String(type);
        this.bubbles = false;
        Object.assign(this, init || {});
    }

    preventDefault() {
        this.defaultPrevented = true;
    }

    stopPropagation() {
        this.propagationStopped = true;
    }
}

class CustomEvent extends DomEvent {
    constructor(type, init) {
        super(type, init);
        this.detail = (init && init.detail) || null;
    }
}

function installSurface(sandbox) {
    const doc = sandbox.document;
    const patched = new WeakSet();

    function under(ancestor, node) {
        for (let n = node; n; n = n.parentElement) {
            if (n === ancestor) return true;
        }
        return false;
    }

    /* The one capture-phase listener in this module is custom-select's document
       `mousedown`, which a browser therefore runs *before* the trigger's own
       handler. The stub's `addEventListener` keeps no capture flag, so replay
       that order for that type only — otherwise `armed` would be cleared after
       the press that set it and the "this press opened it" exemption would test
       nothing. */
    function dispatch(node, ev) {
        const runAll = (list) => (list || []).slice().forEach((fn) => fn(ev));
        if (!ev.target) ev.target = node;
        if (ev.type === 'mousedown') {
            runAll(sandbox.__handlers.document.mousedown);
        }
        for (let n = node; n && !ev.propagationStopped; n = n.parentElement) {
            runAll(n._events && n._events[ev.type]);
        }
        if (!ev.propagationStopped && ev.type !== 'mousedown') {
            runAll(sandbox.__handlers.document[ev.type]);
        }
        return ev;
    }

    function patch(el) {
        if (!el || el === doc || patched.has(el)) return el;
        patched.add(el);
        if (!el.contains) el.contains = (other) => under(el, other);
        /* In a DOM, `setAttribute('class', …)` and `className` are the same
           attribute; the stub writes them to two different places and `svgArrow()`
           builds its `<svg class="cselect-arrow">` through the setter, so reflect
           it here rather than let a drawn arrow look absent. */
        el.setAttribute = (name, value) => {
            if (name === 'class') el.className = value;
            else el[name] = value;
        };
        if (!el.removeAttribute) {
            /* The stub stores a non-data attribute as a plain field (see
               `_parseMarkup`), so dropping one has to drop that field again. */
            el.removeAttribute = (name) => {
                delete el[name];
            };
        }
        if (!el.insertBefore) {
            el.insertBefore = (node, ref) => {
                const at = ref ? el.children.indexOf(ref) : -1;
                el.appendChild(node);
                if (at >= 0) {
                    el.children.splice(el.children.indexOf(node), 1);
                    el.children.splice(at, 0, node);
                }
                return node;
            };
        }
        if (el.isConnected === undefined) {
            Object.defineProperty(el, 'isConnected', {
                get: () => under(doc.body, el),
                configurable: true,
            });
        }
        if (el.scrollWidth === undefined) el.scrollWidth = 0;
        if (!el.dispatchEvent) {
            el.dispatchEvent = (event) => {
                dispatch(el, event);
                return true;
            };
        }
        const measured = el.getBoundingClientRect;
        el.getBoundingClientRect = () => {
            const box = el.__box;
            if (!box) return measured.call(el);
            return {
                left: box.left,
                top: box.top,
                width: box.width,
                height: box.height,
                right: box.left + box.width,
                bottom: box.top + box.height,
            };
        };
        return el;
    }

    function selectSurface(sel) {
        const rows = () => (sel.children || []).filter((el) => el.tagName === 'OPTION');
        Object.defineProperty(sel, 'options', { get: rows, configurable: true });
        Object.defineProperty(sel, 'selectedIndex', {
            get() {
                const at = rows().findIndex((o) => o.selected);
                if (at >= 0) return at;
                return sel.multiple || !rows().length ? -1 : 0;
            },
            set(v) {
                rows().forEach((o, i) => {
                    o.selected = i === Number(v);
                });
            },
            configurable: true,
        });
        Object.defineProperty(sel, 'value', {
            get() {
                const o = rows()[this.selectedIndex];
                return o ? String(o.value === undefined ? '' : o.value) : '';
            },
            set(v) {
                const at = rows().findIndex((o) => String(o.value) === String(v));
                if (at >= 0) this.selectedIndex = at;
            },
            configurable: true,
        });
        return sel;
    }

    const created = doc.createElement;
    doc.createElement = (tag) => {
        const el = patch(created(tag));
        if (String(tag).toLowerCase() === 'select') selectSurface(el);
        return el;
    };
    /* `createElementNS` resolves `doc.createElement` at call time, so the SVG
       arrow custom-select builds inherits the patch. */

    return {
        patch,
        dispatch,
        /* Markup reaches its descendants through the stub's own parser, which
           builds elements without this driver's help, so re-walk the page. A parsed
           `id` also has to reach the registry: a browser makes an element findable
           by `getElementById` the moment the markup carries the id, and the stub
           only learns ids from `createElement`. */
        patchAll() {
            doc.world.forEach((el) => {
                patch(el);
                if (el.id && !doc.registry.has(el.id)) doc.registry.set(el.id, el);
                if (el.tagName === 'SELECT' && !el.__selectPatched) {
                    el.__selectPatched = true;
                    selectSurface(el);
                }
            });
            return doc.world;
        },
    };
}

/* ─── one page, one scenario ─────────────────────────────────────────────── */

function world() {
    const sandbox = { ...baseSandbox(), Event: DomEvent, CustomEvent };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    const dom = installSurface(sandbox);
    vm.runInContext(fs.readFileSync(path.join(jsDir, 'custom-select.js'), 'utf8'), sandbox, {
        filename: 'custom-select.js',
    });
    return { sandbox, dom };
}

/** The parts a wrapper owns, found only the way the page finds them. */
function control(sandbox, id) {
    const sel = sandbox.document.world.find((el) => el.id === id);
    if (!sel) return { missing: `no <select id="${id}"> in the page` };
    const wrap = sel.parentElement;
    const trigger = wrap && wrap.querySelector('.cselect-trigger');
    const menu = sandbox.document.world.filter((el) => el._csSource === sel)[0] || null;
    return {
        sel,
        wrap,
        trigger,
        valueEl: trigger && trigger.querySelector('.cselect-value'),
        menu,
        rows: menu ? menu.querySelectorAll('.cselect-option') : [],
    };
}

function readControl(sandbox, id) {
    const c = control(sandbox, id);
    if (c.missing) return c;
    const style = c.menu ? c.menu.style : {};
    return {
        enhanced: c.sel.dataset.cselect === '1',
        label: c.valueEl ? c.valueEl.textContent : null,
        title: c.trigger ? c.trigger.title : null,
        wrapClass: c.wrap ? Array.from(c.wrap.classList) : null,
        triggerClass: c.trigger ? Array.from(c.trigger.classList) : null,
        menuClass: c.menu ? Array.from(c.menu.classList) : null,
        /* The stub's `body` is a plain element, so the honest question is identity:
           is the popup a child of the document body (where nothing can clip it)
           rather of the panel it belongs to? */
        menuOnBody: c.menu ? c.menu.parentElement === sandbox.document.body : null,
        popupBelongsToControl: c.menu ? c.menu._csSource === c.sel : null,
        /* One popup per control: a second `enhance` on the same select would append
           another menu to <body> and the old one would keep answering. */
        popupCount: sandbox.document.world.filter((el) => el._csSource === c.sel).length,
        nativeInsideWrapper: !!(c.wrap && c.wrap.children.includes(c.sel)),
        nativeConnected: c.sel.isConnected,
        nativeTabIndex: c.sel.tabIndex === undefined ? null : c.sel.tabIndex,
        arrowDrawn: !!(c.trigger && c.trigger.querySelector('.cselect-arrow')),
        selectedIndex: c.sel.selectedIndex,
        value: c.sel.value,
        selectedOptions: c.sel.options.filter((o) => o.selected).map((o) => o.value),
        optionStates: c.sel.options.map((o) => ({
            value: o.value,
            text: o.textContent,
            selected: !!o.selected,
            disabled: !!o.disabled,
        })),
        menuStyle: {
            minWidth: style.minWidth === undefined ? null : style.minWidth,
            width: style.width === undefined ? null : style.width,
            left: style.left === undefined ? null : style.left,
            top: style.top === undefined ? null : style.top,
        },
        rows: c.rows.map((row) => ({
            text: (row.querySelector('.cselect-option-label') || { textContent: null }).textContent,
            classes: Array.from(row.classList),
            title: row.title === undefined ? null : row.title,
            note: (row.querySelector('.cselect-option-note') || { textContent: null }).textContent,
            hasCheck: !!row.querySelector('.cselect-check'),
        })),
    };
}

function runScenario(sc) {
    const { sandbox, dom } = world();
    const { dispatch } = dom;
    const doc = sandbox.document;
    const host = doc.createElement('div');
    host.className = 'field-host';
    doc.body.appendChild(host);
    if (sc.html) host.innerHTML = sc.html;
    if (sc.viewport) {
        if (sc.viewport.innerWidth !== undefined) sandbox.innerWidth = sc.viewport.innerWidth;
        if (sc.viewport.innerHeight !== undefined) sandbox.innerHeight = sc.viewport.innerHeight;
    }
    /* Events the control reports to its owner, heard where the owner hears them:
       `cselect-blocked` on the document (as zenviz.js does), `change` per select. */
    const blocked = [];
    const changes = {};
    doc.addEventListener('cselect-blocked', (ev) => {
        blocked.push({ detail: ev.detail, targetId: ev.target && ev.target.id });
    });
    dom.patchAll();
    sandbox.CustomSelect.scan(doc);
    dom.patchAll();

    const countChanges = () => {
        doc.world
            .filter((el) => el.tagName === 'SELECT')
            .forEach((sel) => {
                if (sel.__counted) return;
                sel.__counted = true;
                changes[sel.id] = 0;
                sel.addEventListener('change', () => {
                    changes[sel.id] += 1;
                });
            });
    };
    countChanges();

    const mem = {};
    const probes = [];
    for (const step of sc.steps || []) {
        const c = step.target ? control(sandbox, step.target) : null;
        if (step.target && c.missing) throw new Error(`${sc.id}: ${c.missing}`);
        if (step.do === 'open') {
            dispatch(c.trigger, new DomEvent('mousedown', { button: 0, target: c.trigger }));
        } else if (step.do === 'tapRow') {
            const rows = c.menu ? c.menu.querySelectorAll('.cselect-option') : [];
            const row = rows[step.row];
            if (!row) throw new Error(`${sc.id}: row ${step.row} was never rendered`);
            dispatch(row, new DomEvent('click', { target: row }));
        } else if (step.do === 'tapTrigger') {
            /* The click that pairs with the opening mousedown: the trigger swallows
               it so the page-level guard cannot read it as "clicked away". */
            dispatch(c.trigger, new DomEvent('click', { target: c.trigger }));
        } else if (step.do === 'key') {
            step.keys.forEach((key) => {
                dispatch(c.trigger, new DomEvent('keydown', { key, target: c.trigger }));
            });
        } else if (step.do === 'box') {
            c.trigger.__box = { left: step.left, top: step.top, width: step.width, height: step.height };
        } else if (step.do === 'measureMenu') {
            /* A menu's own size is not knowable here, so the scenario hands over the
               figures a browser would report: content width, box width, box height. */
            if (step.scrollWidth !== undefined) c.menu.scrollWidth = step.scrollWidth;
            if (step.width !== undefined) c.menu.offsetWidth = step.width;
            if (step.height !== undefined) c.menu.offsetHeight = step.height;
        } else if (step.do === 'viewport') {
            sandbox.innerWidth = step.innerWidth;
            sandbox.innerHeight = step.innerHeight;
        } else if (step.do === 'docClick') {
            const target = step.inside ? control(sandbox, step.inside).menu : doc.body;
            dispatch(target, new DomEvent('click', { target }));
        } else if (step.do === 'docMousedown') {
            dispatch(doc.body, new DomEvent('mousedown', { target: doc.body, button: 0 }));
        } else if (step.do === 'escape') {
            dispatch(doc.body, new DomEvent('keydown', { key: 'Escape', target: doc.body }));
        } else if (step.do === 'closeAll') {
            sandbox.CustomSelect.close();
        } else if (step.do === 'refreshAll') {
            sandbox.CustomSelect.refreshAll();
        } else if (step.do === 'scan') {
            sandbox.CustomSelect.scan(doc);
            dom.patchAll();
            countChanges();
        } else if (step.do === 'appendMarkup') {
            /* A select rendered later, by the node settings panel re-injecting its
               HTML — the case the body MutationObserver exists for. */
            const added = doc.createElement('div');
            added.className = 'late-host';
            doc.body.appendChild(added);
            added.innerHTML = step.html;
            dom.patchAll();
        } else if (step.do === 'renameOptions') {
            /* What a language flip does to a select: rewrite the option text in
               place. The control's label is only right after `refreshAll`. */
            Object.keys(step.map).forEach((value) => {
                const opt = doc.world.find((el) => el.tagName === 'OPTION' && el.value === value);
                if (!opt) throw new Error(`${sc.id}: no option with value "${value}" to rename`);
                opt.textContent = step.map[value];
            });
        } else if (step.do === 'setDisabled') {
            const sel = doc.world.find((el) => el.id === step.target);
            sel.disabled = !!step.value;
            sandbox.CustomSelect.refreshAll();
        } else if (step.do === 'removeControl') {
            c.wrap.remove();
        } else if (step.do === 'remember') {
            mem[step.as] = c[step.part];
        } else if (step.do === 'ownsPopup') {
            const other = control(sandbox, step.other);
            const panel = doc.world.find((el) => el.id === step.panel);
            if (!panel) throw new Error(`${sc.id}: no container with id "${step.panel}"`);
            probes.push({
                ownsPopup: {
                    ownRow: sandbox.CustomSelect.ownsPopup(c.rows[step.row], c.wrap),
                    ownRowInsidePanel: sandbox.CustomSelect.ownsPopup(c.rows[step.row], panel),
                    rowOfOtherControl: sandbox.CustomSelect.ownsPopup(other.rows[0], c.wrap),
                    otherRowInsidePanel: sandbox.CustomSelect.ownsPopup(other.rows[0], panel),
                    body: sandbox.CustomSelect.ownsPopup(doc.body, c.wrap),
                },
            });
        } else {
            throw new Error(`${sc.id}: unknown step "${step.do}"`);
        }
        probes.push({ after: step.do, target: step.target || null });
    }

    const controls = {};
    for (const id of sc.ids || []) controls[id] = readControl(sandbox, id);
    const remembered = {};
    Object.keys(mem).forEach((key) => {
        const el = mem[key];
        remembered[key] = el ? { stillInPage: !!el.parentElement, connected: el.isConnected } : null;
    });
    return {
        controls,
        blocked,
        changes,
        probes,
        remembered,
        /* What `killAutofill` did to the plain text inputs `scan` found. */
        autofill: doc.world
            .filter((el) => el.tagName === 'INPUT')
            .map((el) => ({
                id: el.id,
                autocomplete: el.autocomplete === undefined ? null : el.autocomplete,
                spellcheck: el.spellcheck === undefined ? null : el.spellcheck,
            })),
        /* `enhanceInputs` detaches the datalist so the OS popup can never open, and
           remembers it on the control; reported so the pickup is observable. */
        candInputs: doc.world
            .filter((el) => el.dataset && el.dataset.cinput === '1')
            .map((el) => ({ id: el.id, keptList: el.dataset.clist, attributeGone: !el.getAttribute('list') })),
    };
}

const out = {};
for (const sc of scenarios) {
    out[sc.id] = runScenario(sc);
}
process.stdout.write(JSON.stringify(out));
