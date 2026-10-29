# 采析绘 — Architecture map

Structure-first map of the codebase. It complements `AGENTS.md` (which is *rules* — read that for the
invariants); this file is about *shape*. Every number below is measured at HEAD `70f3344` (2026-10-29),
not estimated.

## Runtime model
- One Flask process, **started from `backend/`** (`python app.py` → `:5000`). `backend/` is the
  `sys.path` root, so imports are top-level (`from config import Config`, never `backend.`).
- Single-user by design. All runtime state lives in gitignored `data/` (SQLite
  `runs.db`/`datasets.db`/`history.db`) and `logs/`; `data/workflows/` is the one versioned exception.
  `CRAWLER_DATA_ROOT` gives a process its own `data/`+`logs/` — how a second server is meant to coexist.

## Backend layout (70,187 Python LOC across 328 files)
| area | contents |
|---|---|
| `app.py` | **579 LOC: the composition root only** — the WSGI object, the request hooks (origin guard, no-store, language pin), the 25 `register_blueprint` calls, the clock's two wiring lines, startup recovery, the PEP-562 read seams, and **one route**: the served page `/`. The run doors (`/api/workflow/execute`, `/api/workflow/rerun-node`) are `api/workflow.py`; run orchestration is `engine/run.py` (1,291 LOC, **zero nested functions** — every run helper is at module scope, pinned by `tests/unit/gates/test_run_worker_module_scope.py`); the run-record cluster is `api/runs.py`. The URL map holds **129 rules over 123 unique paths** (`len(list(app.url_map.iter_rules()))` — extraction moves handlers, never a path). |
| `core/` | `config.py` (paths, env, constants), `refs.py` (shared value rules: `as_bool`, `platform_for`, `sanitize_filename`), `machine.py` (per-OS machine facts: Chrome / driver / xelatex / Node locations), `procs.py` (`popen_kwargs()`, driver process-tree reclaim). The old `utils/` package was folded in here — there is no `backend/utils/`. |
| `i18n.py` + `i18n_catalog/` | The zh/en machinery (`t()`, thread-local `set_lang`, `audit`, the merge). The messages are **data**, one module per domain — 10 domains (`crawl`/`collect`/`cookie`/`sched`/`run`/`analysis`/`biblio`/`charts`/`api`/`settings`), merged in `MODULES` order; a key claimed twice is refused at import. `tests/unit/i18n/test_i18n.py` refuses a domain file missing from `MODULES` (an unmerged module would drop its words silently). |
| `capabilities/` | The single crawl matrix, split by owner: `platforms/<id>.py` (one platform each; panel order pinned by `platforms/__init__`), `fields.py` (shared field atoms + mode factories), `catbus.py` (the second engine's vocabulary), `model.py`/`requirements.py` (dataclasses, machine gates), `registry.py` (the queries — the one answer validation, execution and the Data Source panel read). |
| `scheduling/` | The 定时任务 domain: `clock.py` is an in-process daemon thread ticking `Config.SCHEDULER_TICK_SECONDS`, firing through the seam `engine.run_schedule.start_scheduled_run` → `begin_run` (never a second start path); `store.py` is `data/schedules.json`; `cron.py` parses/validates the time expressions. |
| `engine/` | `workflow.py` (DAG resolve, `effective_workflow`, `node_label`), `plan.py` (what a run IS: shape, transport, whether it pays for a model, which nodes a rerun invalidates), `run.py` (`begin_run` + `_run_worker`, `run_node_durable`, `execute_node`, the Stop verdict, the queue drain — **no helper is left inside a closure**), `run_logs.py` (the console's two write paths: the `print()` tee and the durable per-run `RunLogWriter`, armed by the run window), `run_schedule.py` (the two doors a scheduled fire needs: `scheduled_canvas` / `start_scheduled_run`; it reaches `engine.run.begin_run` by name so one patch governs every start), `executor.py`, `logger.py`. Nothing here may import `app` — that is the rule forcing orchestration to hold its state through `state`/`stores`/`services`. |
| `services/` | `lock_store.py` stays flat (its per-item pins span exports, runs, history, workflow files). Domain packages: `charts/` (one `ChartSpec` per chart type is `registry`; `contracts`/`style`/`options/` builders/`visualizer`/`tikz*`/`pdf`/`outputs`), `reports/` (`html`, `paper`), `ingest/` (`catbus` subprocess bridge, `runtime`, `lifecycle`, `net`, `parts`), `runs/` (`store/` checkpointing core split into mixins, `files`, `windows`, `compare`, `history`, `housekeeping`, `queue`, `payload`, `settlement`), `analysis/` (`pipeline`, `params`, `process`, `llm`, `lexicon`, `lexicon_store`, `stats`, `contracts`, `kernels`, `topic_kernels`, `ops/` — **one op per module**), `biblio/` (`importer`, `schema`, `cluster`, `refs`, `fuse`, `geo`, `store`, `monitor`, `sources`; `metrics/`, `charts/`, `formats/` — **one module per citation format**), `workflows/` (`manager`, `history`, `reusable`, `expand`, `bundle`), `datasets/` (`store`, `merge`, `dedupe`), `exports/` (`writer`, `browser`). The executor module that used to sit here is deleted — executors live in `nodes/executors/`. |
| `analyzers/` | `llm_client` (Ollama/OpenRouter), sklearn + BERT analyzers, `keyword`, `ner`, `stopwords`. |
| `crawlers/` | Platform registry + `get_crawler`/`crawler_class`/`is_crawlable` in `__init__.py`; `core/` (`crawler.py` the crawl contract, `browser.py`, `faults.py`, `video.py`), `backends/catbus.py` (the second backend; columns/identity/cells read from the adapter's manifest), `commenting/` (`session`/`walks`/`protocol`), `engine/` (site-independent modules incl. `pacing.py`), `platforms/<id>/` (one directory per site, name == platform id, its `crawler.py` + comment `walk` in `comments.py`, plus site files like `rows.py`/`overlay.py`/`dialogs.py`). `hongguo/` (Windows-only harvest) is `harvest.py` + `player_ui.py` + `naming.py` + `trust.py`. |
| `sessions/` | The login-state domain: `cookies.py` (named jar `data/cookies/<platform>@<account>.json` + folding rules), `flow.py`, `profiles.py` (one Chrome `user-data-dir` per account), `template.py`, `preflight.py` (the run-now verdict), `routes.py` (`/api/cookies/*` + profile-delete cluster). A session question stays answerable without buying a browser. |

### The one constraint on further splitting
**`create_app()` is not a drop-in.** `tests/conftest.py` does `import app` and reaches directly into the
module's shared singletons (`app.execution_state`, `app._dataset_cache`, …) and uses
`module.app.test_client()`. That isolation machinery (redirecting every write path before any test
imports `app`) is what keeps `data/`/`logs/` byte-clean. Turning the module into a factory would orphan
every one of those references and silently break isolation — so any split must move shared state to a
place both `app.py` and `conftest.py` can import from, *first*. That place exists now:
`runtime/state.py` and `runtime/stores.py`.

## Frontend layout (41,307 JS LOC across 50 files, no build step)
Everything loads as flat `<script>` tags in a fixed order. The callable surface is **markup**: `index.html`
carries `onclick`/`oninput`/`onchange` attributes naming bare globals and namespace receivers, so a split
moves code between files and never renames a global. `tests/frontend/harness_*.mjs` load the **real** files
into a node `vm`, driven by `tests/unit/frontend/test_frontend_*`.
| file | role |
|---|---|
| `canvas.js` | 2,553 LOC — the `canvas` object (graph model, node CRUD, selection, wiring, painting, file serialization), **ONE global made of five files** via `Object.assign`: `canvas-view.js` (camera/pinch/minimap), `canvas-snapshot.js` (`getState`/`restoreState`/`undo`, camera outside the snapshot), `canvas-visuals.js` (disable cascade, run badges, outlines), `canvas-auto-layout.js`. A later script cannot rebind a top-level `const`, so each section is an `Object.assign` block — pinned by `test_frontend_canvas_sections_js.py`. |
| `workflow.js` | 2,089 LOC — the workflow controller (file lifecycle, pre-run gate, `execute`/`stop`, console reattach) and cross-panel tools. Docked panels live in `panels/*.js`; layout in `workflow-layout.js`. |
| `app.js` | 545 LOC — the entry: `X-Lang` fetch patch, `I18n`/`_mergeCatalogues`, `RunState`, `Settings`, theme, `CloudMode`, `boot()`. Sliced further: `llm-settings.js` (301), `app-settings.js` (227), `floating-panels.js` (405). |
| `zenviz-page.js` | 14,723 LOC — the Chart-Studio page app, deliberately **unsplit**. `zenviz.html` is markup only; the page loads `zenviz-bridge.js` + `zenviz-page.js`, which the workbench page does not. |
| other | `reusable.js` (reusable node templates), `schedules.js` (定时任务 dock, no time arithmetic of its own), `node-types.js` (`/api/node-types`), `custom-select.js`/`menu.js`/`stats.js`, 17 `panels/*.js`, 24 top-level modules. |
| CSS | **Ten per-domain sheets** (`base`/`menu`/`canvas`/`panels`/`controls`/`console`/`reusable`/`workspace`/`dialog`/`overlays` = 5,077 lines) + `zenviz.css` (1,927); `tests/static_assets.py::css_text()` reads a declaration without naming the file. The single `css/style.css` is deleted. |
| static assets | Geo basemaps live at `backend/static/geo/{china,world}.json`; `backend/static/vendor/` holds only `echarts`/`echarts-gl`/`echarts-wordcloud` and `fonts/`. |

## Test tiers
`pytest.ini` runs **only the fast tier by default** and adds `--disable-socket`. Tiers: `unit`,
`api` (tmp-isolated `test_client`), `integration` (real Chrome/Ollama), `live_ollama`, `live_quick`,
`live_site`. Scale, measured: **265 test files** (unit 163 / api 55 / integration 20 + live layers),
**43 `.mjs` frontend harnesses**, ~110k test LOC — more test code than product code, the asset the
restructure must not lose. The fast tier collects **8,249 cases** (8,246 passed / 3 skipped, ~8 min);
treat `pytest -q` as the source of truth since the case count is parametrized. Frontend needs `node` on
`PATH` (43 JS modules `skipif(node is None)`, ~1.4k cases — those otherwise *skip*, which can look green,
hence `CRAWLER_REQUIRE_NODE=1`, which aborts the session instead). See `AGENTS.md` for the
"nothing skipped" closure gate.

The single roadmap lives in [`refactor_plan.md`](refactor_plan.md) (the audit, target tree, layering
rules, stage order, definition of done). This file describes only **what is there today**.

## Refactor constraint that shapes every move (finding E)

`app.py`'s module globals are used as **monkeypatch seams** by the tests. Any extraction that moves such
a name must re-point the tests that patch it, or the test passes while measuring a binding nobody calls.
The two rules that resolved this for the store registry, and that still govern the rest:

- **R1 (app keeps the alias)** — `app.get_run_store is stores.get_run_store`. A function patch on
  `app_module.get_run_store` still redirects app-internal calls (they resolve by name at call time) but
  reaches no Blueprint that imported from `stores`. Patch targets then split by caller — a trap.
- **R2 (single seam, chosen)** — every writer binds to the new owner and `app` never re-exports the name
  as an alias; all callers do `from runtime.stores import get_run_store`. Function patches target
  `runtime.stores.get_run_store` uniformly. `backend/runtime/stores.py` owns the registry under this rule.

**Never leave a reader hitting the old global.** A single `global _RUN_STORE` inside a moved function
defeats the whole design, which is why executors take their state through `NodeCall` instead. The store
separation is measured against the current tests by `tests/unit/gates/test_run_worker_module_scope.py`
and the seam tests in `tests/api/`; the exact historical line numbers are not quoted here because they
rot — the rule is the durable part.

### The PEP-562 seam (`app.__getattr__`, app.py:315-371)
`app.py` answers a set of names that used to be app globals from the module that owns them now. Reads
through here are honest; a WRITE or PATCH belongs on the owner. The current set is broader than the
three store globals it began as:
- `_RUN_STORE` / `_DATASET_STORE` / `_HOUSEKEEPER` → `runtime.stores` (read-only delegation).
- `_dataset_cache` / `add_log` / `execution_state` → `runtime.state` (same object, mutated in place).
- `get_crawler` → `crawlers` (the crawler-factory seam ~40 tests patch).
- `get_run_store` → `runtime.stores` (a read seam; a fake store is set on the owner, not here).

`app.warm_profile_dir`, `app.MAX_IMAGE_BYTES`, and `app._ML_MODEL_TYPES` are **no longer app globals** —
they were carved out and are reached from their owners directly: `crawlers/core/crawler.py:1131`
(`warm_profile_dir`), `api/studio.py:46` (`MAX_IMAGE_BYTES`), `api/analysis.py:34` (`_ML_MODEL_TYPES`).
Tests that patched them under `app.*` were re-pointed in the same commit as the move.

## What owns what today
- `backend/runtime/` (moved out of the root; root is now only `app.py` + `i18n.py`, pinned by
  `test_foundation_layering.py`): `state.py` (in-place run state, `_RUN_QUEUE`, `_dataset_cache`, console
  buffer, `history_service`/`cookie_manager`), `stores.py` (the store registry + lazy getters — the seam
  the harness rebinds), `settings.py` (`data/settings.json`), `gate.py` (same-platform crawl gate),
  `transport.py` (cloud refusal for local-only model transports).
- `backend/api/` — 24 blueprint modules + `http.py` (request coercions) + `resolution.py`
  (`_resolve_dataframe`, `NoRunDataError`), all registered in `app.py`. Together they hold the whole HTTP
  surface (123 unique paths); `app.py` itself keeps only the `/` route.
- `backend/nodes/executors/` — all 14 node types, each `NODE_TYPE` + `run(node, call)` + its own column
  contract (`emit_columns`/`read_columns`), self-registered in `nodes/registry.py`. `nodes/schema.py` only
  walks the graph and resolves a type through the registry, so the plugin is the one place its columns are
  written.
- `engine/run.py` — the run, at module scope end to end: `begin_run` (claim, queue hand-off, spawns
  `_run_worker`), `run_node_durable`, `execute_node`, `settle_node_as_stopped`, `note_heavy_result`, and
  the ten helpers a worker needs (`_wf_display_name`, `_run_single_workflow`, `_continue_record`,
  `_close_component_record`, `_carries_artifact`, `_node_of`, `_inputs_for`, `_component_run`,
  `_run_workflow_wrapper`, and `run`→`_run_worker` with the claim-time names as parameters). None of it
  reaches a Flask object: the app, the clock and a future CLI all ask the same module. Stubbing a run
  start has exactly one address (`engine.run.begin_run`) that the manual route, the rerun route, the
  scheduled fire and the queue drain all honour (`tests/api/test_run_races.py::TestTheRunStartHasOneAddress`).
