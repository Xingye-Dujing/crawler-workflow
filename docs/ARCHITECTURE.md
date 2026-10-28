# 采析绘 — Architecture map

Structure-first map of the codebase and a sequenced, test-gated plan for the two largest
refactors. It complements `AGENTS.md` (which is *rules*) — read that for the invariants; this
file is about *shape*. The numbers below are measured, not estimated.

## Runtime model
- One Flask process, **started from `backend/`** (`python app.py` → `:5000`). `backend/` is the
  `sys.path` root, so imports are top-level (`from config import Config`, never `backend.`).
- Single-user by design. All runtime state lives in gitignored `data/` (SQLite
  `runs.db`/`datasets.db`/`history.db`) and `logs/`; `data/workflows/` is the one versioned
  exception. `CRAWLER_DATA_ROOT` gives a process its own `data/`+`logs/` — this is how a second
  server is meant to coexist (see *Run/resume state* and `AGENTS.md`).

## Backend layout (~68.1k Python LOC across 212 files, measured 2026-10-27)
| area | contents |
|---|---|
| `app.py` | **3,253 LOC: the composition root, the run orchestration (`_begin_run`, the drain, `_run_node_durable`) and 27 `@app.route` handlers.** The other 101 route decorators are 23 Blueprints in `backend/api/` plus `sessions/routes.py`; the live URL map holds 129 rules over 123 unique paths (re-measure: `len(app.url_map.iter_rules())` — extraction moves handlers, never a path). What already left this file: the run queue (`services/runs/queue.py`), the payload guards (`services/runs/payload.py`) and the run-record reconciliation (`services/runs/settlement.py`, with `execute_lock` moved to `state.py` so the claim and the settle share one lock). Stage 6 of the plan takes the remaining routes and the orchestration out. |
| `core/config.py` | paths, env, constants (retention/queue/preflight/scheduler tick). |
| `i18n.py` | the zh/en message catalog (`t()`, `set_lang` thread-local, `audit`). |
| `capabilities/` | the single crawl matrix, split by owner (2026-10-28): `platforms/<id>.py` declares one platform each (panel order pinned by `platforms/__init__`), `fields.py` the shared field atoms + mode factories, `catbus.py` the second engine's vocabulary, `model.py`/`requirements.py` the dataclasses and machine gates, `registry.py` the queries over all of it (the one answer validation, execution and the Data Source panel read). |
| `scheduling/` | The 定时任务 domain (2026-10-28 from `scheduler.py` + `services/{schedule_store,cron}.py`): `clock.py` is an in-process daemon thread ticking `Config.SCHEDULER_TICK_SECONDS`, firing through the seam `app._start_scheduled_run` → `_begin_run` (never a second start path); `store.py` is `data/schedules.json`; `cron.py` parses/validates the time expressions. |
| `engine/` | `workflow.py` (DAG resolve, `effective_workflow`, `node_label`), `plan.py` (what a run IS: its shape, its transport, whether it will pay for a model, which nodes a single-node rerun invalidates), `executor.py`, `logger.py`. |
| `services/` | one flat module plus domain packages (grouped 2026-10-28): `lock_store` stays flat because its per-item pins span exports, runs, history and workflow files — grouping it under any one domain would lie. `charts/` (`registry` — **one `ChartSpec` per chart type**: family, ECharts-only, paper twin, required columns, x-axis rule; every other list is a projection of it, `contracts` — re-exports the biblio reads plus the limits that are not a type property, `visualizer` — the ECharts option + `ChartConfigError`, `tikz` — the LaTeX figure + three-line table, `pdf` — xelatex over a run's registered sources, `outputs` — the figure+table add-ons the render route and the visualize node share), `reports/` (`html` — the self-contained run report, `paper` — the article+ctex paper), `ingest/` (`catbus` — the second backend's subprocess bridge, `runtime`, `lifecycle`, `net` — the reachability probe, `parts` — the sharded part writer), `runs/` (`store` — the checkpointing core, `files`, `windows`, `compare`, `history`, `housekeeping`, `queue` — the waiting requests and their db mirror, `payload` — the two guards every run-start passes, `settlement` — stop/orphan reconciliation), `analysis/` (`pipeline` — the op executor, `params`, `process`, `llm`, `lexicon`, `lexicon_store`, `stats`), `biblio/` (`importer`, `schema`, `metrics`, `cluster`, `refs`, `fuse`, `geo`, `charts`, `store`, `monitor`, `sources`), `workflows/` (`manager`, `history`, `reusable`, `expand`, `bundle`), `datasets/` (`store`, `merge`, `dedupe`) and `exports/` (`writer`, `browser`). **The executor module that used to sit in this directory is deleted** — the executors live in
`nodes/executors/` (Phase 1a), and keeping a copy in both places would have let whichever one was
edited first silently win. Stage 4 of the plan replaced this name-prefix grouping with directories (2026-10-28). |
| `analyzers/` | `llm_client` (Ollama/OpenRouter), sklearn + BERT analyzers, `keyword`, `ner`, `stopwords`. |
| `crawlers/` | 60 modules in six layers: `__init__.py` (the platform registry + `get_crawler`/`crawler_class`/`is_crawlable` factory), `core/` (`crawler.py` 1,144 — the crawl contract: streaming sink, cursor/watermark, arrival verdict, DOM reads; `browser.py` 344 — how one Chrome is assembled and what this machine must have for it to exist; `faults.py` 93 — the four failure names that are not about a site; `video.py`), `backends/catbus.py` (the second backend; columns, identity and which cells exist are read from the adapter's manifest), `commenting/` (`session.py` 140 = the live driver plus the reads every walk shares, `walks.py` = the platform→walk registry, `protocol.py` = the browser-free verdicts and text helpers), `engine/` (10 site-independent modules, `pacing.py` among them since 2026-10-27; `innertube` moved to `youtube/innertube.py` and the named dialogs to each site's `dialogs.py` on 2026-10-28), and `platforms/<id>/` — one directory per site, its name being the platform id used everywhere, holding `crawler.py` and the site's own comment `walk` in `comments.py`. A site may add a file for what is not an interaction: `douyin/rows.py` (141) and `weibo/rows.py` (103) hold each platform's string→value rules (which address actually names a creator, why a board's `0` is not a blank, which date tokens are trustworthy), so those refusals are testable without a driver, and `douyin/overlay.py` (200) is the mixin that reads one video inside the same document — no navigation per row. Comment dispatch is a table lookup, so the CatBus backend no longer has to synthesise a method name to be reachable. `hongguo/` is now four files rather than one big one: `harvest.py` (994) owns the capture harness (mitmdump + player lifecycle + the walk over the JSONL), `player_ui.py` (616) owns the UIA driver — window, foreground, whole-tree walk, guarded coordinate clicks — and is where `ctypes.windll` and `uiautomation` live, `naming.py` (83) owns the pure name rules (which card or header actually names the requested drama, which drawer control is an expander), `trust.py` (213) owns the mitmproxy CA (PEM→DER, crypt32 read, and the write in a killable child because writing the store in-process hangs this machine). Left in Stage 1: `engine/wall.py`'s per-site markers stay on purpose — it is ONE classifier every page is checked against, and scoping its vocabulary by platform would be a behaviour change that needs its own live evidence; and the largest crawler module is now `core/crawler.py` (1,144). |
| `utils/` | helpers (`as_bool`, `platform_for`, `sanitize_filename`). |
| `sessions/` | the login-state domain (2026-10-27, from five root/`services` modules): `cookies.py` (the named jar `data/cookies/<platform>@<account>.json` + its folding rules, was `services/cookie_manager.py`), `flow.py` (where each platform's cookie is copied from, was `services/cookie_flow.py`), `profiles.py` (one Chrome `user-data-dir` per account: layout, freshness, the lock that keeps two crawls off one device, was `browser_profiles.py`), `template.py` (who may build the pristine device directory, was the 34-line `profiles.py`), `preflight.py` (the run-now verdict, was `cookie_preflight.py`), `routes.py` (2026-10-28: the `/api/cookies/*` + `/api/profiles/delete` cluster carved out of `app.py`, merged with the two `/api/browser/profiles*` routes that used to sit in `api/browser_profiles.py`; Blueprint `sessions`). `crawlers.core.browser` asks `profiles` for a path and nothing here asks the crawler layer back except `template`/`preflight`, so a session question stays answerable without buying a browser. |

### Why `app.py` is still big — and the coupling that constrains how to split it
`app.py` mixes three jobs: (a) 39 route decorators, (b) the **run orchestration** (`_begin_run` alone is
~895 lines: claiming the run, the queue, the checkpoint/reuse decisions, the stop path, the settlement),
and (c) the module-level helpers that both of those reach (`execution_state` reads, `add_log`, the store
getters, the LLM gate). The node executors are **no longer** part of it — all 14 live in
`nodes/executors/`; what keeps `app.py` growing is that a new route or a new run-state rule has no other
home yet.

**The key constraint for any refactor:** the test harness treats `app.py` as a module of shared
singletons. `tests/conftest.py` does `import app` and reaches directly into
`app.execution_state`, `app.cookie_manager`, `app.history_service`, and calls
`app.reset_console_state()`; the `client` fixture uses `module.app.test_client()`. That isolation
machinery (redirecting every write path before any test imports `app`) is what keeps `data/`/`logs/`
byte-clean — `AGENTS.md` calls it out explicitly. So **`create_app()` is not a drop-in**: turning the
module into a factory would orphan every one of those references and silently break isolation. Any
split must move that shared state to a place both `app.py` and `conftest.py` can import from, *first*.

## Frontend layout (~26k JS LOC across 11 files, no build step)
| file | role |
|---|---|
| `workflow.js` | **13,026 LOC — 206 top-level functions, 34 named objects, 82 top-level `var`.** Run console, every docked panel, node settings, execution, resume, chart preview/export. 33 section banners mark its topics, and they have drifted: the cookie-manager cluster sits under the *Outline sidebar* and *Export guide* banners, `wfFiles` under *Lexicon manager*. Stage 8 of the plan splits it (`docs/frontend_modules.md` is the per-module order). |
| `app.js` | 5,071 LOC — the zh/en catalogues (~3,700 of it) + `Settings`/`AppSettings`/`RunState`/`BrowserProfiles`/`CloudMode`, boot, the cookie dialog, every dock's resize wiring. |
| `canvas.js` | 3,893 LOC — node graph, camera (`pan/zoom`, kept out of `getState`), pointer/touch gestures, auto-layout, clipboard. |
| `reusable.js` | 1,021 LOC — reusable node templates: fold/expand, in-card preview, unwrap. |
| `schedules.js` | 475 LOC — the 定时任务 dock: it renders the server's payload (`/api/schedules*`) and nothing else. Deliberately **no** time arithmetic and **no** status vocabulary of its own (a token the catalogue does not know shows as itself) — see the 定时任务 rules in `AGENTS.md`. |
| `node-types.js` | The served node catalogue (`/api/node-types`): types, word keys, groups and seed parameters. The canvas reads it as soon as it answers; its own literal table is the cold-page fallback, pinned to the server by tests. |
| `custom-select.js`, `menu.js`, `stats.js`, `zenviz*.js` | widget + Chart-Studio host/bridge. `zenviz.html` itself is 16,852 lines and loads `zenviz-bridge.js`, which the workbench page does **not**. |

**The callable surface is markup, not code.** `index.html` (2,336 lines) carries 123 `onclick`,
23 `oninput`, 18 `onchange` attributes naming **66 bare global functions** and **20 namespace
receivers**. Renaming any of them is a user-visible break, which is why the split moves code between
files and never renames a global. `css/style.css` is 5,017 lines over 44 panel banners.

The codebase already uses a lightweight namespace convention (`const Foo = { … }`), but everything
loads as flat `<script>` tags in a fixed order — which is why `AGENTS.md` warns that a top-level
`const` is not a `window` property and that "a wrapper installed in another file is not the function
your harness loads". Frontend JS *is* under test: `tests/frontend/harness_*.mjs` load the **real**
files into a node `vm`, driven by `tests/unit/test_frontend_*`.

## Test tiers
`pytest.ini` runs **only the fast tier by default** and adds `--disable-socket`. Tiers: `unit`,
`api` (tmp-isolated `test_client`), `integration` (real Chrome/Ollama), `live_ollama`, `live_quick`,
`live_site`. Scale, measured: **252 test files** (unit 150 / api 55 / integration 20 / live_site 27) with
**~6,163 test functions**, 44 `.mjs` frontend harnesses, 120,914 test LOC — more test code than product
code, which is the asset the restructure must not lose. The fast tier is 8,104 cases / ~8 min
(the exact case count is parametrized, so treat `pytest -q` as the source of truth).
Frontend needs `node` on `PATH` (those cases otherwise *skip*, which can look green — hence
`CRAWLER_REQUIRE_NODE=1`, which aborts the session instead). See `AGENTS.md` for the
"nothing skipped" closure gate.

## Where the plan lives

The roadmap used to be written here (a section called "Refactor roadmap A–D" plus a "Progress" log),
and it drifted from the code: it still described moving the executors out of `app.py` as a future step
while they had all landed, and it cited 124 `backend/test_*.py` probes that have since been deleted.
**One fact, one home**: [`refactor_plan.md`](refactor_plan.md) is now the only roadmap — the audit,
the target tree, the layering rules, the stage order and the definition of done. This file describes
**what is there today**, and §E below keeps the one durable engineering finding from the old plan
because it is a constraint, not a step.

## Refactor constraint that shapes every move (finding E)

`app.py`'s module globals are used as **monkeypatch seams** by the tests — `app.warm_profile_dir`,
`app._RUN_STORE`, `app.MAX_IMAGE_BYTES`, `app._ML_MODEL_TYPES`, … So any extraction that moves such a
name re-points the tests that patch it, or the test passes while measuring a binding nobody calls.
The two rules that resolved this for the store registry, and that still govern the rest:

- **R1 (app keeps the alias)** — `app.get_run_store is stores.get_run_store`. A function patch on
  `app_module.get_run_store` still redirects app-internal calls (they resolve by name at call time) but
  reaches no Blueprint that imported from `stores`. Patch targets then split by caller, which is a trap.
- **R2 (single seam, chosen)** — every writer binds to the new owner and `app` never re-exports the
  name as an alias; all callers do `from stores import get_run_store`. Function patches target
  `stores.get_run_store` uniformly. `backend/stores.py` owns the registry under this rule;
  `app.py` keeps a PEP-562 `__getattr__` only for the three store globals, which is what the test
  harness rebinds.

The census that forced the choice (measured 2026-10-09 against the tests of that day, so the line
numbers have moved): **~118 read sites** vs **exactly 9 write/patch sites**. Reads survived the move
through the alias; the 9 writes had to move **in the same commit** — leaving one behind is what made
the first attempt fail with 43 errors. Same lesson, same size ratio, for the executor seams:
`tests/executor_seams.py::forward` exists because a plugin resolves its own `get_crawler`, not app's.

## What owns what today

- `backend/state.py` — the in-place run state (`execution_state`, `_RUN_QUEUE`, `_dataset_cache`,
  console-buffer helpers), the eager `history_service`/`cookie_manager`, `_completed_lock`.
- `backend/stores.py` — the store registry (`_RUN_STORE`/`_DATASET_STORE`/`_HOUSEKEEPER`/the saved-canvas
  `WorkflowManager` + the lazy getters). This is the seam the test harness rebinds; writes to
  `app._RUN_STORE` would shadow it.
- `backend/api/` — 23 blueprint modules + `http.py` (request coercions) + `resolution.py`
  (`_resolve_dataframe`, `NoRunDataError`). Blueprints are registered in `app.py`.
- `backend/nodes/executors/` — all 14 node types, each `NODE_TYPE` + `run(node, call)`, self-registered
  in `nodes/registry.py`; the shared legs are `services/ingest/runtime.py`, `services/ingest/lifecycle.py`,
  `services/analysis/params.py`, `services/analysis/process.py`, `services/analysis/llm.py`,
  `services/runs/files.py`, `services/runs/windows.py`.
- `app.py` — composition root: the app object, the request hooks (origin guard, no-store, language
  pin), the console tee/log sink, **run orchestration** (`_begin_run`, the worker, `_run_node_durable`,
  `_execute_node`) and the routes that still reach that orchestration — `/api/workflow/execute`,
  `/api/workflow/rerun-node`, the panel's stop/status reads and the served page `/`. Every other URL
  is a Blueprint; the run-record cluster is `api/runs.py`.
  Line and route counts are deliberately not quoted here, because the number changes with every
  feature and a doc that recites it is stale by construction.

One durable rule from the keystone work, kept because it is a constraint and not a step: **never leave a
reader hitting the old global.** An `app` alias plus `__getattr__` is a safety net only while it is the
*only* name app-internal code uses — a single `global _RUN_STORE` inside a moved function defeats the
whole design, which is why the executors take their state through `NodeCall` instead.


## Seam census behind that rule (measured 2026-10-09 against the tests of that day, so the line numbers have moved)

The store seam has **3 module globals** in `app.py` and **3 lazy getters** around them:

| owner (in `app.py`) | global | lock | getter | `global` sites |
|---|---|---|---|---|
| run store   | `_RUN_STORE`   | `_RUN_STORE_LOCK`   | `get_run_store`   | 1 (app.py:640) |
| dataset store | `_DATASET_STORE` | `_DATASET_LOCK`   | `get_dataset_store` | 1 (app.py:346) |
| housekeeper | `_HOUSEKEEPER` | `_HOUSEKEEPER_LOCK` | `get_housekeeper` | 1 (app.py:658) |

Test access splits sharply between reads and writes:

- **Reads: ~118** sites in tests, uniformly via `app_module._RUN_STORE` / `app_module.get_run_store()` / `app_module.get_dataset_store()`. A PEP-562 `app.__getattr__` delegating `_RUN_STORE`→`stores._RUN_STORE` and an `app.get_run_store = stores.get_run_store` re-export keep every one of them working unchanged.
- **Writes/patches: exactly 9** sites (all in tests). These **must** move to the new owner in the same commit; leaving any behind is what caused the failed slice-1 attempt (43 errors):

  | file:line | form | kind |
  |---|---|---|
  | `tests/conftest.py:454` | `module._RUN_STORE = run_store` | inject |
  | `tests/conftest.py:455` | `module._DATASET_STORE = dataset_store` | inject |
  | `tests/conftest.py:458` | `module._HOUSEKEEPER = None` | inject |
  | `tests/conftest.py:479` | `module._RUN_STORE = None` (finally) | restore |
  | `tests/conftest.py:480` | `module._DATASET_STORE = None` (finally) | restore |
  | `tests/api/test_nodes_execution.py:745` | `app_module._RUN_STORE = RunStore(db)` | direct write |
  | `tests/api/test_run_races.py:419` | `monkeypatch.setattr(app_module,'_RUN_STORE',restarted)` | global patch |
  | `tests/api/test_run_races.py:598` | `monkeypatch.setattr(app_module,'get_run_store', refuse)` | **function patch** |
  | `tests/api/test_run_races.py:614` | `monkeypatch.setattr(app_module,'get_run_store', lambda: app_module._RUN_STORE)` | **function patch** |

The sharp edge is the two **function** patches at the bottom of that table: `app.py`'s own code calls
`get_run_store()` as a module-level name, so patching `app_module.get_run_store` redirects the calls
inside `app.py` (they resolve by name at call time) but reaches no caller that imported from `stores`.
That asymmetry is why R2 above was chosen over R1.

The swings that followed this design (extract route clusters one blueprint at a time) were **not
executed from this document**: they are Stage 6 of [`refactor_plan.md`](refactor_plan.md), which owns
the order, the per-stage gate and the risk note that `_begin_run` is the highest-value, highest-risk
single body left in `app.py`. What is kept above is the census, because it is the reason the seam
rules are what they are: a move that leaves one writer on the old binding is not a refactor, it is a
split-brain that only the user's next resume will discover.

