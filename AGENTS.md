# AGENTS.md

Rules loaded into **every** session. Each rule is bare; the **why/evidence** is in
[`docs/agent_practices.md`](docs/agent_practices.md) — read it before doubting a rule, and load the matching
`.opencode/skills/<id>/` before editing a domain (`cai-xihui-context` is the map). Grep by section title.

**采集端（crawler/platform）规则拆到 [`docs/crawler_rules.md`](docs/crawler_rules.md)**：改爬虫、其列或真站断言前，先读该
文件，再读 `docs/crawler_notes.md` 对应小节。

## Project

采析绘 (crawler_workflow): Flask + zero-build vanilla-JS; crawls 9 social platforms + CNKI export (instagram
cookie-capture only) via Selenium, cleans/analyzes text with local Ollama LLMs + scikit-learn, drag-drop workflow canvas.

**Map**: `backend/app.py` is the composition root; run it from `backend/` (the `sys.path` root). Backend packages are
`core`/`runtime`/`api`/`engine`/`nodes`/`analyzers`/`crawlers`/`capabilities`/`services`/`sessions`/`scheduling`/`ai`/
`extensions`, plus `i18n_catalog/` for text; the no-build frontend is `backend/static/js/` in `index.html` order.
`docs/ARCHITECTURE.md` is the full module map; `tests/` is unit/api/integration/frontend + real-site.

## Architecture: plugin seams — know the seam before editing

**Read the seam before you change it, and extend it instead of bypassing it.** Every extension point below is a
registry plus **one file per entry**. A new platform, node type, op, chart, source, provider or skill is a new file and
one registration line — never a new `if` in shared code. A change that adds an entry-specific branch to shared code is
a defect, not a shortcut.

- **Platform crawlers are plugins.** `backend/crawlers/platforms/<id>/` (`crawler.py`, `comments.py`, `rows.py`, …)
  and `backend/capabilities/platforms/<id>.py` (that platform's modes, fields, advice, region) are the ONLY homes for
  site facts: selectors, endpoints, in-page JS, column names, pacing baselines, which field a form offers. Shared
  modules (`crawlers/engine/`, `crawlers/core/`, `crawlers/commenting/`, `capabilities/fields.py`,
  `capabilities/model.py`, `nodes/executors/comment.py`) never branch on, or hardcode, a platform. A shared factory
  may accept a generic parameter; the platform file passes its own answer (`comment_mode(..., replies=True)`).
- **Crawl backends**: `crawlers/backends/` + the adapter's own `capabilities` manifest; never copy cells, columns or
  identity keys into a Python table. Ledger, cursor and login are keyed per backend.
- **Node types**: one `NodePlugin` in `backend/nodes/catalog.py` + one `nodes/executors/<type>.py` registered in
  `nodes/registry.py`; the browser reads the server's `node-types.js`, never a second list.
- **Analysis ops**: one `services/analysis/ops/<op>.py` + the `OPS` table; add its enum/contract/gate in the same
  change (`contracts.py`, `validate_step`, the gate tests).
- **Chart types**: one builder in `services/charts/options/` registered in `BUILDERS`; there is no
  `if chart_type == …` chain and must not become one.
- **Bibliographic sources/formats**: `services/biblio/sources.py` + `services/biblio/formats/`; a format's readable
  columns are its own module's answer.
- **AI extensions**: typed contributions through `extensions/` (`ExtensionRegistry`), providers in
  `ai/providers/registry.py`, skills/tools in `ai/skills.py`/`ai/tools.py`; manifests are data, local code plugins are
  local/admin only, cloud refuses them by name.
- **Frontend panels**: a panel is a `static/js/panels/*.js` split with its `<script>` line in `index.html` (the one load
  order) and an entry in `tests/frontend/splits.json`/`companions.mjs`; the one-global rule is the seam. Never add a
  second list.
- **Do not restructure a seam to fit one entry.** If the new entry does not fit the seam's vocabulary, add the missing
  generic capability to the shared layer (one field, one flag, one hook) and let each entry answer it — the shared
  layer stays ignorant of who answers what.

## Cross-platform (MANDATORY on every change)

**Windows (dev), Linux (cloud), macOS.** Nothing in `backend/`, `tools/`, `ml_train/`, `tests/` or docs may hardcode a
Windows fact — drive letter, `\` joining, `.exe`, `%APPDATA%`/`PROGRAMFILES`, `taskkill`, cp936 console, Windows-only font.

- **Every feature ships for all three systems in the same change. Windows-only is a defect, not the default.** Design the
  server behavior, data paths, tests and docs for Linux and macOS alongside Windows; a desktop packaging path
  (installer/`.exe`) needs a macOS counterpart (`.app`/DMG) or a named reason. Only a capability that cannot physically
  exist elsewhere may be gated to one OS, and then: server verdict + named refusal + hidden UI entry.
- **A capability impossible off Windows refuses BY NAME and its UI entry disappears.** Verdict from the server
  (`Config.CLOUD_MODE`/`sys.platform`); JS holds no second opinion. Existing: 红果短剧 harvest, the login-cookie window,
  local Ollama under cloud mode.
- **`desktop/` is the ONE OS-packaging tree** (Windows PyInstaller/UPX/Inno + macOS PyInstaller `BUNDLE`/DMG); its Windows-
  and macOS-only facts never leak into `backend/`. The macOS build runs only on GitHub's macOS runners
  (`desktop/build_macos.py`, `.github/workflows/macos-build.yml`).
- **A Mac payload is per-CPU and an `.app` is copied, never unzipped**: catalogue keys `darwin-arm64`/`darwin-x64`
  (`platform_asset_key`); the DMG is mounted then copied with `ditto`. macOS Chrome/Node use `services/components/macos.py`;
  `safe_extract` stays the portable path.
- **Machine lookups are per-OS tables in one place**: Chrome/xelatex/Node+CatBus in `core/machine.py` +
  `services/charts/pdf.py`, joined with the TARGET separator (`ntpath`/`posixpath`); CJK font stack and ctex in
  `services/charts/visualizer.py`/`tikz.py`. Overrides: `CHROME_BIN`/`CHROME_PATH`, `CIXI_NODE_BIN`/`NODE_BIN`,
  `CIXI_CATBUS_CLI`/`CATBUS_CLI`/`CATBUS_HOME`. Never inline a `Program Files` path, `.exe` or `taskkill` elsewhere.
- **OS-only `Popen` keywords live in `core/procs`**: use `creationflags=CREATE_NO_WINDOW` via `procs.popen_kwargs()`
  (`windowsHide` raises `TypeError`). Every `backend/` spawn passes it — `tests/unit/crawlers/test_platform_rules.py`
  refuses a console child without it. A piped child writes the ANSI code page: cross in bytes, decode UTF-8 by hand, params
  on stdin, never argv. `detached=True` is `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` on Windows — **never
  `DETACHED_PROCESS`**; a helper the program exits for must write a receipt the parent waits for
  (`tests/unit/foundation/test_detached_child.py`).
- **Platform-independent tests are the proof**: no drive-letter data, no `.exe`-pinned refusal, no `sys.platform='win32'`
  patch faking a product gate (patch both sides or assert the refusal), no timezone literal for the "server local" zone.
- **Byte limits are byte limits:** ext4 NAME_MAX 255 is UTF-8 **bytes**; a Windows path cap is characters.
- **CI runs the fast tier, ruff and both pylint tiers on all three systems** (`.github/workflows/ci.yml`:
  `windows-latest`, `ubuntu-latest`, `macos-15`), plus the real-Chrome `browser` job and a `docker` job that builds and
  boots the deployment image. A Linux/macOS-only failure is a real finding, not "unverified". CI cannot prove a real
  cloud crawl, `live_site`/Ollama, CatBus, or the packaged desktop GUI. Linux packages: Chrome/Chromium + driver,
  `fonts-noto-cjk`, optional `texlive-xetex`/`texlive-lang-chinese`.

## Commands

**venv `.venv/` (Python 3.11) is mandatory — never system Python.** Windows `.venv/Scripts/python.exe`/`ruff.exe`/
`pylint.exe`/`pip.exe`, POSIX `.venv/bin/python`/`ruff`. Run the server from `backend/`; run tests and lint from the
repository root.

- Run: `cd backend && python app.py` → 127.0.0.1:5000 (`PORT`, `HOST`, `FLASK_DEBUG=1`). **From `backend/`** (`sys.path`
  root, `from config import Config`); never a `backend.` prefix. Cloud mode is `python app.py cloud` (or
  `CRAWLER_CLOUD=1`) and refuses to boot without `CRAWLER_ADMIN_PASSWORD` + `SECRET_KEY`.
- Lint — **three standards, all clean**:
  - `ruff check backend/ tests/ desktop/ tools/` and `ruff format --check backend/ tests/ desktop/ tools/`.
  - `python tools/ci_lint_tiers.py product` and `... tests` (each tier owns its `--rcfile`, passes explicit files, and
    refuses an empty list). The local probe tier is `pylint --rcfile=.pylintrc.probes (Get-ChildItem backend -Filter
    test_*.py)`; `backend/test_*.py` are gitignored probes, NOT pytest.
  - Never `# pylint: disable`/`# noqa`/widen a config: fix the cause. The post-edit formatter (`.opencode/hooks/format.mjs`)
    can fail on a restricted workspace (`os error 5`); run the commands by hand — CI is the unskippable gate.
- Deps: *every directly-imported package* into `.venv/` **and** `requirements.txt` in the same change; new caches into
  `.gitignore`. torch/transformers for `sentiment`'s `bert` → `requirements-optional.txt`, never CI.
- **Never SILENTLY answer with a model other than the one claimed**: a degradation PRINTS the method that ran (topic
  `method=auto`→embedding/LDA; sentiment/emotion/tendency bert→`snownlp`/`ml`); analyzers refuse an unrunnable `bert` by
  name; a multi-model BERT comparison never degrades.
- `ml_train/` (gitignored) trains the sklearn+bert models `emotion`/`tendency`/`sentiment` load
  (`data/model_registry.json`); changing features/labels means retraining there (`ml_train/README.md`).
- **Test tiers** (`pytest.ini` excludes the real tiers; `tests/unit/gates/test_test_tiers.py`):
  - Fast: `python -m pytest -q` — currently ~10.6k collected. `--disable-socket` makes an unmocked HTTP call fail.
    One case: `python -m pytest -q tests/unit/<path>::<Class>::<test>`; add `-rs` to print every skip.
  - Device: `-m "integration or live_ollama"` (real Chrome + Ollama; LLM mocked by default).
  - Live: `-m live_quick`/`-m live_site`, split by `live_cn`/`live_os`.
  - **Never run live unattended — it spends the user's accounts.** Own profile root; only `CIXI_LIVE_USE_USER_PROFILE=1`
    (his consent) crawls as he does; weibo once per pass; **ask which network he is on**.
  - **Unavailable browser/daemon SKIPS, so a tier can look green without running.** Set `CRAWLER_REQUIRE_BROWSER=1`/
    `CRAWLER_REQUIRE_OLLAMA=1` (fail not skip); `CRAWLER_REQUIRE_NODE=1` aborts the session for the ~43 JS modules that
    `skipif(node is None)`.
  - One device/live case: override the marker filter too (naming the file alone reports `N deselected`).
  - Layout `tests/unit`, `tests/api` (tmp `test_client`), `tests/integration`. OpenRouter **never** really called — patch
    `analyzers.llm_client.requests.post/get`. Frontend JS needs `node`.

## How tests are written here

- **Isolation happens at conftest import; the suite fails if `data/` or `logs/` gains a byte.**
- **A warning is a test that noticed something and passed anyway — fix it, never mute it** (no `filterwarnings`).
- **A stateful rule needs a stateless suite:** `quiet_jar` snapshots/restores the shared cookie dir; a crawl test declares
  `seeded_logins`; a test *about* the login rule points `Config.COOKIE_DIR` at its own tmp dir.
- **The `integration` UI tier performs no server writes** — stub `fetch`.
- **A test may not assume the machine: CI is UTC, this box is UTC+8.** Ask the machine (`astimezone()`); `TZ` is honoured
  on Windows — `$env:TZ='UTC'` before believing a green run.
- **A feature matrix must enumerate every dimension that classifies the thing under test.**

### Frontend JS

- **JS is under test.** `tests/frontend/harness_*.mjs` load the REAL `canvas.js`/`workflow.js`/`app.js` into a node `vm`
  (`harness_dom.mjs`), driven by `tests/unit/frontend/test_frontend_*`; any result-affecting JS change syncs a scenario;
  `urlPlatform` is pinned against `core.refs.platform_for`.
- **Chart Studio is generated from the `third_party/zenviz-core` submodule**: edit its `core/` (or a `profiles/`
  overlay), then `python third_party/zenviz-core/build.py --product caixihui --root .`; never hand-edit
  `backend/static/zenviz.html`, `backend/static/css/zenviz.css` or `backend/static/js/zenviz-*.js`
  (`test_zenviz_core_sync.py` compares bytes). Initialize the submodule on a fresh checkout (`git submodule update --init`).
- **A JS split registers in `tests/frontend/splits.json`, and the companion closure is TRANSITIVE** (also in
  `companions.mjs`/`frontend_catalogue.with_companions`, keyed by `panels/x.js`): a harness naming `workflow.js` gets every
  module split from its companions. Harnesses take files through `sourcesWithCompanions` (**one read per file**), never
  their own `readFileSync(argv)`; Python scans use `static_assets.js_text(name)`. **Splitting an object's MEMBERS keeps ONE
  global via `Object.assign(obj, { … })`**: member lines stay verbatim, sections' member sets must be disjoint.
- **The frontend holds no second opinion about a crawl.** `sourceNodeErrors()` asks `Capabilities` which fields the mode
  requires — if not loaded, refuse, never guess. A stored value off the option list shows as itself
  (`selectOptionTags`/`boolParam`), never option #0.
- **Six frontend rules, each costing a feature:** (1) `if (window.X)` can't see a top-level `const X` — guard or export it;
  (2) the DOM stub's matcher is real — never fabricate a child a query finds nothing for; (3) a wrapper must forward its
  arguments (an empty list acts on the *previous* selection); (4) `onclick="fn('…')"` spans two grammars — `attrJsArg`
  JS-escapes then HTML-escapes; (5) a node captured before an `await` is gone after it — re-look it up (`_rowFor`); (6) a
  wrapper installed in another file is not what the harness loads — forward `(...args)` and measure behind a patched
  global in the browser tier.
- **A canvas shortcut belongs to the canvas only while not typing:** `canvas._isTypingTarget()` (what the element IS), not
  a tag list.
- **History entries are snapshots, identical ones are not entries:** `getState()` deep-copies params; `_pushState()` skips
  an equal state; `restoreState()` is bracketed by `_historySaving`.
- **The camera is not part of the model:** pan/zoom live in `serializeDraft()`/`settings.view`, NEVER `getState()`;
  `addNode` randomizes only a non-finite x/y (0 is a position).
- **One page boot must not be a single point of failure:** a throw in the one `DOMContentLoaded` body skips later steps —
  boot steps go through `boot(name, fn)`.
- **There is ONE dialog shell, holding ONE pending answer:** a second `showDialog` settles the pending dialog with its
  `cancelValue` before painting. A `dismissable: false` dialog is never displaced. Success reloads the page. Pinned in
  `tests/frontend/harness_dialog_a11y.mjs` — `harness_accounts.mjs` stubs `showDialog`.
- **A dialog with an input is answered by the input:** leave `value:` off `showDialog` input dialogs.

### Measurement and live assertions

- **A browser-measured assertion reports how much it measured:** audit containers **by id**, never `<body>`, report a
  per-container floor, resolve wording from `I18n`. **State the viewport** — Windows ignores
  `set_window_size`/`set_window_rect`, so emulate (`Emulation.setDeviceMetricsOverride`) and assert CSS size with a `100vh`
  probe (`window.innerHeight` is un-emulated).
- **A closed panel must be GONE, not merely moved — only pixels say so.** The real-browser tier compares the closed strip
  byte-for-byte with the same box at `display:none`, after a closed-vs-closed control that must match; unreproducible =
  REFUSED, never passed.
- **A live case's numbers are computed from the site, never chosen** — derive thresholds from the crawl, two-sided.
- `live_site` retries once **only** on a crawler-reported `login_wall`; assert a refusal that NAMES it (wall/risk) — an
  unnamed empty stays red.

## Run, resume and record

### Data root, single-run ownership, module scope

- Runtime state lives in gitignored `data/` (`runs.db`/`datasets.db`/`history.db`) and `logs/`, always the checkout-level
  pair, never beside code. `data/workflows/` is the ONE versioned exception but references datasets **by id**. Do not
  delete `data/` casually.
- **One server per data root, by design.** `promote_stale_runs()` kills a same-`data/` rival's live run;
  `CRAWLER_DATA_ROOT` gives a process its own `data/`+`logs/` (`/smoke-verify` and the UI tier). Without it, **ask before
  booting a second server, and never kill a process on 5000.**
- **An account's tree is `data/users/<user_id>/`, resolved at CALL time** (`runtime.paths.active()`): stores, exports,
  cookies, profiles, checkpoint/harvest, reusable nodes, locks, schedules follow the signed-in account; `accounts.db`,
  `settings.json`, `lexicon.db`, `models/`, `logs/` stay system-level. Never cache a path in a module constant or store
  default. The run slot is owner-scoped: queue entries carry `user_id`, worker/drain/clock bind it (`account_context`),
  **every thread they start re-binds it** (a thread inherits NO context), and the durable console takes its owner when the
  sink is ARMED. status/stop/process/stats/live previews/report/console answer another account with `foreign_run`/nothing
  only. **A refused claim owns nothing**: the claim stamps `run_id`/`user_id`/ambient before its last refusal. **A durable
  mutation follows the claim**: 重跑节点 deletes a node's rows and releases its dedupe claims inside the worker, not the
  request. `tests/unit/gates/test_account_paths_resolve_at_call.py` fails any account-level `Config.*` path read outside
  `runtime/paths.py`.
- **Authorize BEFORE touching the target.** An admin-only probe returns the target's run id and `stores.release_user()`
  closes its DBs — both after `_require_admin`; "no run is live" is proved inside `execute_lock` or a run starts between
  guard and move (incl. 强制下线). Deleting an account **revokes its sessions before the tree moves** (a request during the
  move mints an ownerless `data/users/<id>/`). The process panel lists/accepts only the caller's own run threads.
- **One run at a time; a busy server queues instead of refusing.** `begin_run()` owns the start path — the queue drains by
  calling *that*; `queue:false` keeps the 400 for fail-fast callers. The worker's `finally` clears
  `execution_state['thread']` **first** and `stopping` leaves **with it, in one `execute_lock` section** — the stop route
  proves liveness and writes flags under that lock. Queues are in-memory (`tests/conftest.py` clears `_RUN_QUEUE`); the
  Execute button relabels 排队运行, never disabled. A `queued:true` drain answer means the entry is **already parked**. **A
  refusal the queue cannot fix carries `drop:true`** (an un-walkable canvas, a corrupt reusable group, an unknown
  mode/provider, a transport this host does not speak, a 继续 whose record was purged) and the drain discards it. Boot
  restores the mirror without opening a store for an account with no `runs.db`, then drains it.
- **A test calling an executor function directly must leave the app quiet:** `clean_globals` *fails* a leaked
  `execution_state['running']`.
- **A run helper needing no claim state lives at module scope; a captured name is a parameter** (`run`→`_run_worker`).
  Proof is `ast.dump` equality plus `symtable` free-variable count 0;
  `tests/unit/gates/test_run_worker_module_scope.py` fails any re-embedding.

### Checkpoint, cursor and ledger

- **Checkpointing is the core value** (`services/runs/store/__init__.py`): outputs and LLM answers persist so a run
  resumes, not re-pays. Three rules: the row sink writes **one transaction per row**; the next slot is `MAX(seq)+1`,
  **never `COUNT(*)`**; a **cursor records position, not content** (`Crawler.seed` supplies ids; never re-feed an id list
  into `mark_position`).
- **A cursor records what the node PROVED, never what it attempted.** The comment engine writes `url_index` *after* an
  input's rows land and stops at the first hole — writing it *before* launders a tail refusal into 继续.
- **A row's ledger key is its site identity, not its content.** `item_key` answers a comment by (`平台`, `评论ID`) — its
  columns avoid `_URL_FIELDS`/`_AUTHOR_FIELDS`/`_BODY_FIELDS`; the whole-row-hash fallback keys on volatile `楼层`.
- **A label is not an input.** A node fingerprint feeds children and the dedupe scope (`'item:'+node_fingerprint`), so a
  *name* inside it breaks the chain. `_VOLATILE_PARAMS` answers "chooses data, or just describes?": ids in; labels and
  switches (`recrawl`/`enabled`) out.
- **A disabled node is not on the canvas.** `engine.workflow.effective_workflow` drops it (off-type/off-upstream cascade;
  fan-in survives on one live input); validate/naming/fingerprint/execution run on that graph.
- **Reuse has four rules:** `done` and `restored` are reusable; a zero-row result is never reused; the source node is never
  adopted (resumes by cursor); `begin_node` `dropped_stale` cancels reuse.
- **Retention must release what it destroyed:** `purge` also calls `forget_run_items`; an explicit `delete_run` *keeps*
  claims.

### Node identity and the crawl backend

- **The crawl backend is part of a node's identity.** `backend` (`selenium`/`catbus`) is keyed into the node fingerprint
  with `selenium`/blank **folded out**, so the two backends never share a dedupe ledger, cursor or watermark scope. CatBus
  is a subprocess (`services/ingest/catbus.py`, `crawlers/backends/catbus.py`): cells, row columns and identity column come
  from the adapter's `capabilities` manifest — **never copied into a Python table** — and every failure names the missing
  part (no Node / no adapter / Node too old / unreadable manifest / no such cell / no CatBus login), never an empty table a
  node settles DONE on. Its login gate is keyed apart (`bilibili@work#catbus`) and never cached as a cookie verdict.
  Why/evidence: `docs/crawler_rules.md` → “第二采集后端”; `docs/agent_practices.md` → "The second crawl backend (CatBus)".
- **A node id is a storage key — never re-mint one on restore.** Records, cursors, LLM caches and `workflow_fingerprint`
  key on it. `canvas.addNode(...,nodeId)` + `reserveId` keep `nextId` past it; both restore paths pass file ids through,
  pinned by `harness_canvas_ix.mjs`. It is also the box's **DOM** id, so never `getElementById(<node id>)` a
  workflow-supplied value: use `canvas._nodeEl(id)`, and `test_frontend_state_js.py` fails any variable-argument
  `getElementById` in canvas.js.
- **Recorded rows are addressed by workflow, never by bare node id:** `_durable_node_rows` returns nothing rather than
  guess. The browser sends `workflow_name` from `workflow.runName()` (name-node label, then file name).
- **`' + '` is a composed lookup key, not a permission:** `_durable_node_rows` widens to pieces only on a miss (so `节奏`
  is never handed `节奏 + BPM`'s table).

### Records, settlement and resume

- **Parallel is one record; serial is one record per workflow that started.** Parallel joins labels with `' + '` (canvas
  order; a lookup key, pinned by `TestRowLookupStillWorks`); serial opens each workflow's row **as reached**. Every row
  keeps the **canvas** fingerprint (resume banner + `/api/runs/resumable`); the response returns workflow zero's row; 继续
  adopts each by name. `并行 ×N` only when `mode=='parallel'`, serial says `串行 ×1`; resume state stays **per workflow**
  (`fingerprints_for_workflow`) so B's failure restores A.
- **Startup recovery shares the end-of-run settlement:** a kill skips `finish_node`, so `promote_stale_runs` must call
  `settle_nodes` (status *and* row_count from the rows) — 已存行数 and 续跑's "adopt the fullest node" read that column.
- **One definition of "completed":** `runs.node_done` and `completed_nodes` agree — skipped/failed/partial are not done,
  `restored` is; counts taken **after** settling over `attempted_nodes`; a node 停止 counts in `stopped_node_ids`, never as
  “1 个失败”.
- **A resumed run re-describes itself:** `start_run`'s conflict update refreshes
  `workflow_name`/`workflow_fingerprint`/`mode`/`headless`/`lang` (not `started_at`).

## Analysis steps and the data contract

- **A step's output column names are a chart's input contract.** 主题距离图 reads `pc1/pc2/topic/prevalence_pct`; 显著词图
  reads `term/overall_freq/within_freq`; both are parameters with those defaults and **refuse a missing column** — a rename
  on one side is a named refusal, not an empty figure.
- **Anything that chooses data, cost or a name is refused BY NAME, never guessed** (mode/`select`/missing column via
  `data_analysis.validate_step`; analyzer `method`/`mode` via `app.enum_param`), and refusals `raise` rather than return
  `[]`. **Read a switch, never compare it** (`core.refs.as_bool`; blank = default).
- **A phase column's order is not data, and a records round trip erases it.** Node boundaries rebuild via
  `pd.DataFrame(current_input)` and drop the categorical. Anything grouping BY phase (分阶段 LDA, `TopicⅠ-1…`,
  主题生命周期/流向, 表 2 演化曲线, 分组聚合) takes the order from the categorical, else a NUMBER (`stage_order`/阶段序号) or
  TIME, else REFUSES — so a phase-table step must emit its position column.
- **A quoted row count is only true of the merge order that produced it.** Measure through the canvas's OWN upstream order
  (walk `connections`, don't glob).
- **A coherence sweep is not a decision; only the canvas's own sweep may be quoted.** The justifying scan runs
  `coherence_max_documents=0` fed by that canvas's own phase filters; where flat, state the tie-break in the node title
  (highest coherence at **≥3 topics**) — no unseen floor.
- **A score is a function of the column it was read from, so the column name belongs to the number.** `正文` vs
  `cleaned_text` give different curves.
- **An unused LDA topic is the model's answer, not the user's mistake:** `topic_by_stage` fills the zero-doc row from the
  topic's word distribution, files `doc_n = 0`, logs one named warning — never empties 特征词.
- **A recall device must not look like a classifier.** `aggression`'s word-list mode says a miss is unmeasurable, keeps the
  lists in code, does NOT count 辟谣 accusations as violent; a missing text column **raises** rather than returning blanks.
- **The analysis node's one non-deterministic step borrows the process node's client:** `topic_label` calls the model once
  per row; `run_pipeline(df, steps, llm=, cancel=, store=)` hands it to `LLM_OPS` only, never via `params`. No model →
  refused before paying; a Stop leaves `未处理` → the node settles PARTIAL, not DONE.

## AI workspace

- **One provider catalog** (`ai/providers/registry.py`) serves the workspace and the row analyzers; a provider capability is
  a server promise, so an unsupported `thinking`/`web_search`/`files` request is refused by name, never sent as a field the
  provider ignores. JS holds no model/endpoint list.
- **Keys stay in the browser**; the server holds one for a request only. `ai.db` and logs must never contain an API key. A
  turn's assistant row is `streaming` until settled; a crash leaves `interrupted`.
- **A turn is several assistant rows**: every `tool_use` has an immediate tool result, grouped in the UI by `turn_id`.
  `ask_user_question` pauses the turn; its answer is a tool result, not a new user message. Most tools read; a
  workflow/analysis/chart/report proposal is an artifact the user applies. Explicit mutating tools (`apply_workflow`,
  `apply_node_result`, `rerun_node`, `workspace_import`, `run_cmd`, …) act only when called and are permission-gated;
  host-bound ones exist only on desktop/local web and are refused by name on cloud. A mutating call may require
  `request_approval` when auto-consent is off.
- **Context is generated, budgeted and redacted**: project facts come from the existing registries, live data is re-read
  per account, and an omission is reported in `context_meta`/the inspector.
- **Plugins are data first**: declarative skill/provider/tool packs are portable; local code plugins are local/admin only
  and cloud mode refuses them by name. Plugin UI uses OMM-ZEN host components, never arbitrary CSS/HTML.
- **Run monitors are a notification channel, not a poll**: the AI proposes `present_artifact(kind="monitor")`, the user arms
  it, `runtime.run_events` publishes lifecycle facts, and `ai.monitors` writes one durable delivery per match. Events carry
  ids/status/counts, never crawled text. The browser reacts (it owns the key); a monitor never spends a token by itself.
- **Python is the extension surface, and it is local-only**: one script library (`services/python_scripts.py`) feeds both
  the AI tools and the canvas **Python node**; a node stores `script_id`, never inline code. Execution is the JSONL
  contract in `services/python_runtime.py`, gated by `ai_allow_python`; cloud mode refuses it by name. It is not a sandbox
  — say so.
- **Read the smallest evidence first**: `dataset_peek` (names + 5 rows, capped cells) before `dataset_page` (≤50 rows);
  `python_run` returns a sample, not the table; any tool result over 12k characters is truncated and says so.
- **A packaged desktop may carry a read-only source snapshot** (`source/` via
  `desktop/frozen_modules.source_snapshot_datas`); `environment.code_root()` is the one reader. It is for citations, never
  for editing the running program.

## 定时任务 (scheduler)

- **The clock is one thread inside the server process, started only from `start_background_services()`** (called by
  `__main__`'s serving child and by the frozen launcher; under the reloader, only the real child), and **a fire takes the
  same start path as a manual Run** — `scheduling.clock` → `engine.run_schedule.start_scheduled_run` → `begin_run`, so a
  busy server **queues** the fire.
- **A scheduled canvas may not need a model, and the rule is one rule asked twice**
  (`engine.run_schedule.scheduled_canvas`, shared by the panel's verdict, save and fire): refused **by name**, never by a
  server-side key. **A moment missed while the server was down is recorded (`missed.count`), never replayed** — one event
  per restart. Refusals go to the task's own history (`last_run` + 20), never the run console.
- **The panel holds no second opinion about time or state:** `next_run_local`/`last_run_local` (in the *task's* zone), the
  trigger sentence, `runnable`/`why_not` and the clock status come from the server; an unknown token shows as itself.
  `tests/unit/frontend/test_frontend_schedules.py` drives the real `schedules.js`. `public()` and audit rows carry
  `*_local`, and `test_frontend_accounts.py` refuses a date formatter in `accounts.js`. **A new dock belongs in
  `DOCKED_PANELS` *and* the dock matrix** (`tests/frontend/harness_panels.mjs`, enforced by `TestTheDock`).

## Console, messages and i18n

- UI text zh/en via `backend/i18n.py`, merging one module per domain listed in `i18n_catalog/MODULES`: every new
  user-facing string goes to **its own domain, in both languages**, and to the browser catalogue
  (`backend/static/js/i18n/<domain>.js`, merged by `app.js`). A key declared in two domains is refused; a domain file
  missing from `MODULES` (or its browser twin) is a failed test.
- **A missing `t()` keyword is a printed bug, not a crash:** `t()` returns the raw template (a forgotten `{reads}` prints
  `阅读={reads}`) and parity checks are blind to it — `test_i18n.py::TestCallSitePlaceholders` walks every `t('literal', …)`
  with `ast` and refuses the mismatch.
- **A `{platform}` slot is answered with a word, not the key** (`zhihu` keys the matrix/cookie file; `i18n` localizes,
  splitting on `,`/`、` only) — `test_frontend_contract.py` keeps the two lists equal.
- Console/validation messages name nodes via `engine.workflow.node_label(node, nid)` (→ `title #nid`), never a bare `nid`;
  store keys/results/resume plumbing still use the raw `nid`. Both restore paths re-apply title + element text BEFORE
  `updateNodeDisplay`.
- **One failure, one line:** `LogBufferHandler` forwards `logger.*` into the buffer, so `logger.exception(...)` **and** a
  matching `add_log` double-print. Keep the logger for the file's traceback; let `wf.node_failed` be the single attributed
  line; a helper adds a fact, never repeats the reason.
- **`QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision:** no Executing/completed line, but counters still
  count them and every fact prints (with `node_label`).
- **Every thread that logs must pin its own language** (`set_lang` is thread-local; a daemon starts fresh): `run()`, the
  parallel pool wrapper and both cookie workers. Assert console text on the reason, not a sentence.

### The run console

- **The console keeps its own history per view, because a normal poll ships only the last 200 lines** (a refreshed page
  reattaches with `tail=5000`). `consoleViews` holds `{seen, lines}` per view (`'all'` + each workflow id), every view is
  fed on every poll, and `switchWfTab` repaints without moving the cursor.
- **The console is ALSO persisted per run (`run_store.run_log`), as a pure side effect that may never move the live
  console.** `_push_log` → `engine.run_logs.RunLogWriter` via `set_log_sink`, armed only inside a run. The durable viewer
  (`/api/runs/<id>/log(.txt)`, `runLogViewer`) reads ONLY that table. **The reattach
  (`execution_state['logs']/_log_total/_wf_logs/_wf_log_total` + `?tail=5000`) must stay byte-identical with or without a
  sink** — a shifted total skips/repeats live lines after reload; `test_console_buffer.py` fails that invariant.
- **`_push_log` stores one entry per physical line** — the total advances by lines, not `add_log` calls.

### Sessions, cookies and run gating

- Run-gating lives in `workflow.js execute()` → `_cookieGateBeforeRun`: browser sessions are probed only when
  `cookie_preflight_before_run` is on, **CatBus sessions always** (its login lives in the adapter, not our cookie), and only
  for a mode **whose session is actually needed** (`Mode.needs_session`; weibo 热搜 is anonymous, wechat has no session to
  want). A login wall **refuses** (no "run anyway"); “无法核对” (timeout/captcha/busy) **never blocks**. A resume or a
  crawl-free canvas asks nothing; a cookie write drops the cached verdict. **`execute()` asks no cookie question of its
  own.**
- One account = one cookie file **and** one Chrome profile in the active tree: `cookies/<platform>_cookies.json` (the
  default login keeps the unsuffixed name; a named account is `<platform>@<account>_cookies.json`) and
  `chrome_profile/<platform>` (default) or `chrome_profile/<platform>/<account>`. `_account_session_errors` refuses when
  `has_session_to_test` finds neither — **blank IS an account (默认账号), not a wildcard.**
- The default account is `default` (never a blank in the box), folded at `CookieManager.key`/`path_segment` (`''` ⇄
  `default`, lowercase always); `sessions.profiles`/preflight/JS box route through that fold; the candidate list and a new
  node's preselection are both `CookieManager.accounts_in_order`.
- **A new settings key is one declaration:** add a `Setting` to `runtime/settings_schema.py` (kind, default, bounds, group,
  both-language label/hint, consumer, portable/secret flags, preset membership). The settings page renders it from
  `GET /api/settings/schema`; `runtime/settings.py` validates and persists it. `tests/unit/gates/test_settings_schema.py`
  fails a key with no reader, a missing translation, or a platform module that reads a setting directly.

### 账号池与出口池 (account/exit pool)

- **A cooldown is state, not a cache:** `data/pool.db` keeps `cool_until` per `(account|exit, 平台, 主体)`, compared with the
  clock at read time (no sweeper). Manual 停用 never expires. Saving a login clears that account's term.
- **Rotate only at a zero-row, attributable failure.** A source node switches login when THIS attempt stored no row and the
  site answered `login_wall`/`risk` (`SessionBlockedError`); rows already stored keep the PARTIAL-and-continue path. A
  comment node may rotate per LINK (a blocked link was never in the proven cursor prefix). Never rotate on stop, network
  faults, under-target or unknown failures.
- **Each attempt takes `gate.hold(account=<real login>)`; `@pool` is a sentinel, not a login.** It may never reach
  `CookieManager.path_for`, and it stays in the fingerprint (pool mode ≠ a fixed login). CatBus refuses it by name.
- **An exit is sticky to `(platform, account)`**; only a benched exit is replaced ("换 IP 不换号"). Every browser path
  (crawl, login window, verify, preflight) resolves its exit through `get_crawler`, so a session is never used from two
  addresses. Credentials travel only in the loopback relay (`crawlers/core/proxy.py`), never argv/logs.
- Details, attribution table and settings: `docs/account_pool.md`, `docs/crawler_rules.md` → 账号池.

### Login accounts and the gate

- **A wrong password answers one sentence.** Verification runs BEFORE the lock and status check (“登录失败次数过多”/
  “该账号已被禁用” for a wrong password is a username oracle). The failure window is keyed `address|username`.
- **The failed-attempt counter is added IN THE ROW** (`UPDATE … failed_attempts = failed_attempts + 1`, read back, arm
  `locked_until` guarded on that count); a read-modify-write counts a burst as ONE, so “连续 5 次锁 15 分钟” never arrives.
- **Every guess at a secret shares the window**, including 改密's `current_password`. The window is **bounded by size** —
  pruning only the touched key leaks one entry per abandoned username.
- **Token comparisons are on bytes:** `hmac.compare_digest` raises `TypeError` on a non-ASCII `str`, and WSGI hands back a
  header latin-1-decoded and a form field UTF-8-decoded, so a text compare is an attacker-paced 500
  (`security.token_matches`). A `next` value is rejected for control characters (a `\n` is illegal in a header;
  `redirect()` raises **after** the session is created).
- **The gate exists only while the registry does,** so a non-loopback `HOST` with no accounts refuses to boot by name
  (`public_bind_refusal`).
- **A storage failure answers in the envelope the panel parses** (`{ok, error}`, never HTML), and account deletion moves the
  tree and drops the row as one guarded step with a compensating move-back (a move-back can fail on Windows, so a failed
  delete reports **where the tree actually is**, checked on disk).
- **Replacing the process singleton closes the store it replaced** — `AccountsStore` holds one SQLite handle for its
  lifetime; on Windows a live connection also locks its dir. `tests/conftest.py` releases every user slot.
- **A password field says so:** `type:'password'` plus the dialog shell's `autocomplete` default — without a directive the
  browser offers to save the credential and refill “当前密码”.

## 开发助手技能 / Development skills

`.opencode/skills/` holds the OpenCode skills for working *on this repo*; the AI workspace's own skills are
`backend/ai/skills.py` `SkillSpec`s. Do not confuse them. The suite covers one domain each: `cai-xihui-context` (map),
`crawler-platform`, `workflow-runtime`, `analysis-charts`, `frontend-omni`, `data-pipeline`, `accounts-security`,
`ai-workspace-dev`, `plugin-authoring`, `python-extension`, `testing-lanes`, `release-desktop`, `smoke-verify`.
Repo-local helpers: the read-only `code-auditor` subagent for a pre-commit audit, the `live-builder` subagent for one
live-test slice, and `/smoke-verify` (loads the same-named skill).

## Style and commits

- Comments and docstrings in **English** (README/commits Chinese). Explain "why".
- **引号用各语言自己的**: 中文 “ ”（内层 ‘ ’），英文 `" "`（内层 `' '`），**不用角括号 U+300C/U+300D/U+300E/U+300F**。
  代码里的 `'…'` 是 Python 字符串定界符，与这条无关。`tests/unit/gates/test_quote_style.py` 拒绝它们（第三方语料、
  模型卡、SHA-256 钉住的 vendor 字节除外）。
- Section dividers: `# ─── Name ───`.
- Ruff: line-length 120, **single quotes**, indent 4, modern typing (`str | None`), py311. Findings **genuinely fixed**:
  never `# noqa`, never `# ruff: noqa`, never `per-file-ignores` or a rule exemption in `ruff.toml`.
- **Code changes are tracked Edits.** No Python/sed rewrite of any file: unrestorable = work is gone.
- Commits: Chinese with a type prefix — `功能更新：`, `问题修复：`, `修改：`.

## Change workflow (MANDATORY on every change)

**How much to run is decided by what the change can break, not by ritual** (one full tier set is ~18 min).

- **Lane A — docs, comments, the anchor**: `tests/unit/gates/test_doc_paths.py`, plus `ruff check` if a `.py` was touched.
- **Lane B — a move / test-seam retargeting with unchanged behavior**: the moved module's cases + contract tests naming it +
  `ruff check`/`format --check` on touched files. **Full fast suite + both pylint tiers once at the end of a ~4-knife batch.**
- **Lane C — real behavior changes (run orchestration, resume/checkpoint, `runs.db`, UI, crawling, LLM boundary)**: full fast
  always; device tier when UI/engine/LLM/crawling is touched; pylint at batch end.
- **GitHub Actions on every push is the backstop** (fast + ruff + product/tests pylint on three systems, plus the browser
  and docker jobs; probes local-only), so a local batch run decides whether to push.
- **The closure gate is NOT a lane**: any "it is done" claim = one full run of every tier, nothing deselected/skipped, no file
  needing a change. Any edit restarts the loop.
- **Edit**: OpenCode's `formatter` → `.opencode/hooks/format.mjs` auto-runs `ruff format` + `ruff check --fix` on touched
  `.py`; committed files still pass `ruff check`/`format --check` by hand.
- **Tests ship with the change.** Any code file touched (backend or frontend JS) syncs the suite in the same change. A
  previously-green test failing because of your change means the bug is the change — fix the code, not the test (unless it
  pinned an old bug). An unfixed product bug gets `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — …')`.
- **Docs stay true**: `README.md` on any user-visible change; measurements → `docs/crawler_notes.md`; a new crawl rule →
  `docs/crawler_rules.md`; a new rule's *why* → `docs/agent_practices.md`. A stale README is a failed change.
- **Device paths**: crawling, LLM transports, checkpoint/resume or UI touched → also `-m "integration or live_ollama"` and
  `-m live_quick` (check port 5000 free first), then `/smoke-verify`. **Use this machine's Chrome + matching chromedriver**
  (`CIXI_DRIVER_PATH`/the settings panel); never let Selenium Manager download a driver.
- **Commit last**, after the closure gate; the type prefix is in Style.
