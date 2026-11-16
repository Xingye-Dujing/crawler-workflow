---
name: frontend-omni
description: Build or change 采析绘's no-build vanilla-JS frontend — canvas/panels, script load order and splits.json companions, node harnesses, OMM-ZEN CSS tokens, dialogs, i18n, safe DOM rules. Use when adding a panel/button, changing canvas behavior, styling a surface, or a frontend harness/test fails.
---

# Frontend (no build, OMM-ZEN)

Read first: `AGENTS.md` → “Frontend JS”, `docs/frontend_modules.md`,
`docs/ARCHITECTURE.md` → frontend layout.

## Load model

- `index.html` is the ONLY script order. No bundler, no ES modules, no framework. A top-level
  `function` becomes `window`; a top-level `const` does not (guard with `window.X` or export).
- Every split is registered in `tests/frontend/splits.json`; the companion closure is transitive.
  A harness naming an owner gets its companions; a missing entry boots half the app.
- A member split uses `Object.assign(obj, { … })` keeping member lines verbatim; each section's
  members are disjoint (a duplicate is a silent overwrite).
- `tests/frontend/harness_*.mjs` load the REAL files into a node `vm`; tests are
  `tests/unit/frontend/test_frontend_*`. `node --check` every new file.
- `tests/static_assets.js_text(name)` reads the browser's real source through the split map.

## OMM-ZEN

- Tokens: `--paper`, `--text`/`--ink`, `--line`/`--line2`, `--hover`/`--active-bg`, `--accent`,
  `--ok`/`--warn`/`--err`, `--radius`, `--font`. No filled black, no blue wash, no second palette.
- Active = inset ink underline (`box-shadow: inset 0 -2px 0 var(--ink)`) and a hairline border;
  checked = a 12px hairline square with an ink tick.
- Motion is `transform`/`opacity` only, short, and disabled under `prefers-reduced-motion`.
- One stylesheet per domain; every CSS file on disk must be loaded by a page
  (`test_frontend_page_markup`), and page order is a contract.

## Rules that cost a feature

1. `if (window.X)` cannot see a top-level `const X`; guard/export it.
2. The DOM stub's matcher is real; never fabricate a child a query finds nothing for.
3. A wrapper must forward its arguments; an empty list acts on the previous selection.
4. `onclick="fn('…')"` spans JS + HTML grammar: `attrJsArg` escapes both.
5. A node captured before an `await` is gone after it; re-look it up (`_rowFor`).
6. A wrapper installed in another file is not what the harness loads; forward `(...args)` and
   measure behind a patched global in the browser tier.
7. A canvas shortcut belongs to the canvas only while not typing: `canvas._isTypingTarget()`.
8. History entries are snapshots: `getState()` deep-copies; `_pushState` skips equal; restore is
   bracketed by `_historySaving`. Camera lives in `serializeDraft()`/`settings.view`, never state.
9. A node id is a DOM id too: never `getElementById(<workflow id>)`; use `canvas._nodeEl(id)`.
10. One dialog shell, one pending answer: a second `showDialog` settles the first; a
    `dismissable:false` dialog is never displaced. Success reloads the page.
11. Boot steps go through `boot(name, fn)`; one throw must not skip later steps.

## i18n

- Every user-facing string in both languages, in its own domain (`static/js/i18n/<domain>.js` and
  `backend/i18n_catalog/<domain>.py`); a key claimed twice is refused.
- A missing `t()` keyword is a printed bug: fill every `{slot}`; don't rely on fallback.
- A user-typed value is shown verbatim, not looked up as a key.

## Recipe: a new panel/entry point

1. Add the markup/ids to `index.html` with accessible names; unique ids, no inline script.
2. Add a JS file or a section; register it in `splits.json` as a companion.
3. Use existing `showDialog`, `showToast`, `fetchJSON`, `escapeHtml`/`AIRender.escape`, not
   `window.confirm`/`alert`.
4. Add both-language keys; update the frontend catalogue.
5. Add a harness driver for the real files and a Python test around it.
6. Run `node --check`, the harness, `test_frontend_page_markup`, `test_frontend_contract`,
   `test_frontend_i18n_js`.

## Verification

```bash
node --check backend/static/js/<file>.js
.venv/Scripts/python.exe -m pytest -q tests/unit/frontend/test_frontend_<area>.py
.venv/Scripts/python.exe -m pytest -q tests/unit/frontend/test_frontend_page_markup.py tests/unit/frontend/test_frontend_contract.py
```

For layout/CSS, the real-browser tier is required: audit containers by id, report a per-container
floor, state the viewport, emulate device metrics on Windows, and prove a closed panel is gone by
pixels (closed vs `display:none`).

## Common failures

- File loaded twice → top-level `const` redeclaration kills later scripts.
- Split not in `splits.json` → harness passes on half the app; page runs the other half.
- A panel "closed" by removing `.open` but an inline height remains; clear it.
- A dynamic node id passed to `getElementById` → duplicate/missing DOM target.
- New string in only one language; contract test catches it.
