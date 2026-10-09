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

## Backend layout (~57k Python LOC)
| area | contents |
|---|---|
| `app.py` | **8,043 LOC — the HTTP layer + the workflow node executors.** 78 `@app.route`, 0 Blueprints. |
| `config.py` | paths, env, constants (retention/queue/preflight). |
| `i18n.py` | 2,781-line zh/en message catalog (`t()`, `set_lang` thread-local, `audit`). |
| `crawl_capabilities.py` | the single crawl matrix: platform × mode × field × handler. |
| `engine/` | `workflow.py` (DAG resolve, `effective_workflow`, `node_label`), `executor.py`, `logger.py`. |
| `services/` | `run_store`, `data_analysis` (2,931), `visualizer` (1,686), `latex_charts`/`latex_compile`, `dataset_store`, `execution_history`, `cookie_manager`/`cookie_flow`, `cookie_preflight.py` (top-level), `exporter`/`export_browser`, `report_service`, `housekeeping`, `lock_store`, `browser_profiles`, `net_probe`, `stats`, `workflow_manager`, `text_dedupe`, `part_writer`. |
| `analyzers/` | `llm_client` (Ollama/OpenRouter), sklearn + BERT analyzers, `keyword`, `ner`, `stopwords`. |
| `crawlers/` | `base.py` + per-platform (`weibo`/`zhihu`/`douyin`/`xiaohongshu`/`bilibili`/`twitter`/`youtube`/`wechat`/`instagram`) + `comments_*` + a site-independent `engine/`. **Well separated.** |
| `utils/` | helpers (`as_bool`, `platform_for`, `sanitize_filename`). |

### Why `app.py` is big — and the coupling that constrains how to split it
`app.py` mixes two different jobs: (a) the ~78 request handlers, and (b) the **node executors**
(`_execute_visualize_node`, `_execute_process_node`, …) plus a large set of module-level helpers
(`_json_body`, `_results_snapshot`, `_safe_int`, `all_settings`, `execution_state`, …). Every new
analyzer/chart forces an edit here, which is how it grew.

**The key constraint for any refactor:** the test harness treats `app.py` as a module of shared
singletons. `tests/conftest.py` does `import app` and reaches directly into
`app.execution_state`, `app.cookie_manager`, `app.history_service`, and calls
`app.reset_console_state()`; the `client` fixture uses `module.app.test_client()`. That isolation
machinery (redirecting every write path before any test imports `app`) is what keeps `data/`/`logs/`
byte-clean — `AGENTS.md` calls it out explicitly. So **`create_app()` is not a drop-in**: turning the
module into a factory would orphan every one of those references and silently break isolation. Any
split must move that shared state to a place both `app.py` and `conftest.py` can import from, *first*.

## Frontend layout (~15k JS LOC, no build step)
| file | role |
|---|---|
| `workflow.js` | **7,713 LOC — 132 top-level functions, 59 col-0 globals.** Run console, panels/settings, execution, resume, Chart Studio glue. |
| `app.js` | 3,210 LOC — i18n catalogs (en+zh) + `AppSettings`/`BrowserProfiles`/`CloudMode`/`RunState`/… namespaces, boot, cookie dialog. |
| `canvas.js` | 1,864 LOC — node graph, camera (`pan/zoom`, kept out of `getState`), pointer/touch gestures. |
| `custom-select.js`, `menu.js`, `stats.js`, `zenviz*.js` | widget + Chart-Studio host/bridge. |

The codebase already uses a lightweight namespace convention (`const Foo = { … }`), but everything
loads as flat `<script>` tags in a fixed order — which is why `AGENTS.md` warns that a top-level
`const` is not a `window` property and that "a wrapper installed in another file is not the function
your harness loads". Frontend JS *is* under test: `tests/frontend/harness_*.mjs` load the **real**
files into a node `vm`, driven by `tests/unit/test_frontend_*`.

## Test tiers
`pytest.ini` runs **only the fast tier by default** and adds `--disable-socket`. Tiers: `unit`,
`api` (tmp-isolated `test_client`), `integration` (real Chrome/Ollama), `live_ollama`, `live_quick`,
`live_site`. Scale: 168 test files, **4,315 test functions**; the fast tier is ~5.8k cases / ~3.5 min.
Frontend needs `node` on `PATH` (those cases otherwise *skip*, which can look green). See `AGENTS.md`
for the "nothing skipped" closure gate.

## Refactor roadmap (do each behind a green fast-suite swing; update tests in the same change)

### A. Backend — Blueprints, safely
1. **Extract shared state first.** Move `execution_state`, the singleton services
   (`cookie_manager`/`history_service`/…), and the generic request helpers (`_json_body`,
   `_safe_int`, `_results_snapshot`, `all_settings`) into a new `backend/state.py` (or `context.py`).
   In `app.py` keep thin aliases (`execution_state = state.execution_state`, …) as a temporary
   compatibility shim, and **update `tests/conftest.py` to reference the new module** in this one,
   well-tested commit. Fast suite must stay green *and* the data/logs byte-clean check must still pass.
2. **Move the pure readers to Blueprints** (least shared mutation): `stats`, `history`, `settings`
   GET, `models`, `capabilities`, `analysis`. Paths unchanged, so the `client` tests don't move.
3. **Then the stateful clusters**: `workflow`, `runs`, `cookies`, `exports`, `report`, `studio`, `llm`
   — now safe because they read/write through `state.py`, not module globals.
4. **Move the node executors** (`_execute_*_node`) out of `app.py` into `engine/` or a
   `services/nodes.py`. This is the highest-value step: it stops `app.py` growing on every feature.

### B. Frontend — modularize `workflow.js`
Split it by responsibility into a few `<script>` files in load order (no bundler needed to start):
run-console, panels/settings renderers, Chart Studio, cookie-gate, i18n/bridge, state/history. Keep
the `const Foo = {}` namespace style so the existing harness keeps loading real files. Goal is fewer
implicit globals and a smaller blast radius per edit — **not** a framework rewrite.

### C. Docs / rules
Keep `AGENTS.md` as terse rules and push evidence here/`docs/`. Several rules already have a pinning
test (i18n parity, `_VOLATILE_PARAMS`, refusal-by-name); where they don't, prefer adding the test
over trusting prose. `AGENTS.md` is near its byte budget — trim it as evidence moves out.

### D. Hygiene (small, optional)
- The 124 `backend/test_*.py` manual probes (gitignored) could move to `scripts/probes/` so the
  one-off measurement scripts stop visually colliding with the pytest suite.
- `pytest-cov` is installed but unused; a coverage floor in CI is optional given the test count.
- Multi-user / real job queue **only if** cloud multi-user becomes a goal; otherwise document
  single-user as an explicit non-goal (it currently is) and leave the one-server design intact.

## Progress (as of the Blueprint extraction work)

Step A-1 is done and went further than planned: `backend/state.py` now owns the in-place run state
(`execution_state`, `_RUN_QUEUE`, `_dataset_cache`), the eager `history_service`/`cookie_manager`, and
`_completed_lock` + `_results_snapshot`. Seven Blueprints live in `backend/api/`: `history`, `stats`,
`settings`, `config`+`models`, `capabilities`, `browser_profiles` (+ shared `backend/profiles.py`),
`llm` (+ shared `backend/transport.py`), with `api/http.py` holding the common request helpers
(`_json_body`, `_bad_body`, `_safe_int`). `app.py` 8043 → ~7600 lines. **A finding that reshaped the
plan:** `app.py` module globals are used as *monkeypatch seams* by the tests (e.g. `app.warm_profile_dir`,
`app._RUN_STORE`), so each extraction that moves such a function also re-points the tests that patch it
(done for `browser_profiles`). Every step was landed as its own full-suite-green, lint-clean commit.

### E. Store-registry keystone — design (NOT yet executed; touches the isolation core)

#### Seam census (measured against the current tests, 2026-10-09)

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

#### The two function patches are the sharp edge

`app.py`'s own internal code calls `get_run_store()` as a **module-level name**. If that name is re-bound to `stores.get_run_store`, monkeypatching `app_module.get_run_store` still redirects the calls inside `app.py` (because they resolve by name at call time), but it would **not** affect a Blueprint that imported the name from `stores` directly. So the design must pick one rule and keep it consistent:

- **Rule R1 (app keeps the shim):** `app.get_run_store` is `stores.get_run_store` (same function object). Any patch of `app_module.get_run_store` shadows the app-module name; app's internal calls (which look up `get_run_store` by name) pick up the patched one; a Blueprint importing from `stores` bypasses the app-module name. → function-patch tests stay on `app_module`, Blueprints that need the *patched* store must ALSO go through `app_module.get_run_store`. Not recommended (leaks semantics).
- **Rule R2 (single seam):** migrate every one of the 9 write sites to `stores`, and never bind `app.get_run_store` as an alias — every caller (app-internal and Blueprints) does `from stores import get_run_store` and calls it by that name. Function patches then target `stores.get_run_store` uniformly. Recommended.

#### Design — R2 (single seam), one branch, four green swings

**Swing 1 — introduce `backend/stores.py`** (no route moves yet):
1. Move the 3 globals + 3 locks + 3 getters from `app.py` to `stores.py`.
2. In `app.py`: `from stores import get_run_store, get_dataset_store, get_housekeeper`; add `import stores`; add a PEP-562 `def __getattr__(name)` that resolves `_RUN_STORE` / `_DATASET_STORE` / `_HOUSEKEEPER` to the `stores` module's live values and otherwise raises `AttributeError`. Replace the raw `_RUN_STORE` read in `_execute_analysis_node` (line 3845) with `get_run_store()`.
3. Re-point the **9 write sites** above to `stores` (5 in `conftest.client`, 1 direct, 2 `_RUN_STORE` patches, 2 `get_run_store` function patches). Every other test file is untouched (118 reads keep working via the alias + `__getattr__`).
4. Guards: fast suite green; the isolation byte-clean check still fires; the leaked-flag/queue tripwires still fire; `test_run_races::test_a_resume_node_with_nothing_to_adopt_produces_no_rows_no_crash` and the forged-store `test_nodes_execution:745` still pass (they were the ones that caught the slice-1 under-migration).

**Swing 2 — extract one thin store-backed cluster** to prove the pattern: `api/runs.py` for `/api/runs/*` (9 routes). Each route is small; only import change is `from stores import get_run_store`. URLs unchanged. Fast suite green.

**Swing 3 — extract the medium clusters** one per commit: `exports`, `report`, `studio`. Each has the same `from stores import get_run_store` shape and its own green swing. If a cluster's handler reaches `execution_state` or a store getter via a `global` name still bound to `app`, the migration keeps the alias in `app` (so those lookups keep working) — do **not** rewrite handlers in the same commit.

**Swing 4 — the heavy clusters**: `workflow` (13), `runs`-of-the-cookies (cookie-write cluster is the deepest — it holds `_COOKIE_JOB`, `_plant_saved_cookie_into_profile`, and calls `get_dataset_store()`). Extract last, one endpoint at a time, keeping the executor wiring intact until A-4 moves the executors themselves.

#### Alternative — A-4 first, keystone second

Extract the **node executors** (`_execute_*_node` in `app.py`, 11 of them) into `services/nodes.py` first, passing `get_run_store`/`get_dataset_store`/`get_housekeeper` as **arguments** (dependency injection). This removes ~1 800 lines from `app.py`, is entirely test-transparent (executors are called from the worker, not from the seam), and **shrinks the surface that the keystone then has to cover** — after which the store-registry step in Swing 1 becomes mechanical instead of entangled. Recommended ordering: **A-4 → E**.

#### Rollback + risk

- Each Swing-1..4 commit is revertable in isolation; only Swing 1 (the alias) has cross-file impact — keep the branch off `main` until two consecutive full-suite-green runs on the same commit.
- Never leave a *reader* still hitting the old global: an app module alias + `__getattr__` is the safety net, but it must be the **only** name app-internal code uses; if a function ever does `global _RUN_STORE`, that call site defeats the whole design. The grep above shows only 3 `global` sites, all inside the getters being moved — so this constraint is naturally satisfied after the move.

Guards: every step keeps the fast suite green **and** the `data/`/`logs/` byte-clean session-finish
check **and** the leaked-flag/queue/store tripwires — those are exactly what catch a broken seam.
Ordering matters: create `stores.py`, re-point conftest + tests, *then* move clusters; never leave a
module whose lazy getter and its injection target differ.
