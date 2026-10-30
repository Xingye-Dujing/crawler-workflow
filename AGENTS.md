# AGENTS.md

Rules for the AI agent, loaded into **every** session. Each rule is stated bare; its **why/evidence** (measurements,
crashes) is in [`docs/agent_practices.md`](docs/agent_practices.md) (not auto-loaded) — read the matching section
before rewriting, doubting, or "simplifying away" a rule. Grep by the bolded title.

**采集端（crawler/platform）规则已拆到 [`docs/crawler_rules.md`](docs/crawler_rules.md)**。
**改爬虫、其列或真站断言前，先读该文件，再读 `docs/crawler_notes.md` 对应平台小节**——那里的规则都真机付过钱。

## Project

采析绘 (crawler_workflow): Flask + zero-build vanilla-JS; crawls 9 social-media platforms (instagram cookie-capture
only) via Selenium, cleans and analyzes text with local Ollama LLMs + scikit-learn, renders a drag-and-drop workflow
canvas.

## Cross-platform (MANDATORY on every change)

**Scope: Windows (dev), Linux (cloud deployment), macOS.** Nothing in `backend/`, `tools/`, `ml_train/`, `tests/` or
the docs may hardcode a Windows assumption — a drive letter, `\` joining, `.exe`, `%APPDATA%`/`PROGRAMFILES`, `taskkill`,
a cp936 console, a Windows-only font. Every change is judged on all three.

- **A capability that cannot exist off Windows refuses BY NAME and its UI entry disappears** (a run-time refusal is
  too late — a node start is paid for). The verdict comes from the server once (`Config.CLOUD_MODE` / `sys.platform`);
  JS holds no second opinion. Existing: 红果短剧 harvest, the login-cookie window, local Ollama under cloud mode.
- **`desktop/` is the ONE Windows-only tree** (PyInstaller/UPX/Inno); its Windows facts stay there and never leak into
  `backend/`; the packaged EXE is judged on Windows alone.
- **Machine-level lookups are per-OS tables in one place**: Chrome / xelatex / Node+CatBus in `core/machine.py` and
  `services/charts/pdf.py`, joined with the TARGET separator (`ntpath`/`posixpath`) so a Windows test can ask what a
  Linux box finds; CJK font stack and ctex font set in `services/charts/visualizer.py`/`tikz.py`. Overrides:
  `CHROME_BIN`/`CHROME_PATH`, `CIXI_NODE_BIN`/`NODE_BIN`, `CIXI_CATBUS_CLI`/`CATBUS_CLI`/`CATBUS_HOME`. Never inline a
  `Program Files` path, an `.exe` name or `taskkill` anywhere else.
- **OS-only `Popen` keywords live in `utils/procs`**: `windowsHide` is not a keyword (`TypeError`); the answer is
  `creationflags=CREATE_NO_WINDOW` via `procs.popen_kwargs()`, tested on all three. A piped **child** writes the ANSI
  code page: cross in bytes, decode UTF-8 by hand, pass params on stdin, never argv.
- **Platform-independent tests are the proof**: no drive-letter data, no `.exe`-pinned refusal, no
  `sys.platform='win32'` patch faking a gate the product reads (patch both sides or assert the refusal), no timezone
  literal for the "server local" zone.
- **Byte limits are byte limits:** ext4 NAME_MAX 255 is UTF-8 **bytes**, a Windows path cap is characters.
- **Real Linux/macOS startup is unverifiable on this box** (no docker/WSL): land code + platform-independent tests,
  list the Linux side as an explicitly unverified surface, and state the Linux packages (Chrome/Chromium + driver,
  `fonts-noto-cjk`, optional `texlive-xetex`/`texlive-lang-chinese`).

## Commands

**venv `.venv/` (Python 3.11) is mandatory — never system Python.** Windows spellings `.venv/Scripts/python.exe`/
`ruff.exe`/`pylint.exe`/`pip.exe`, POSIX `.venv/bin/python`/`ruff` — the commands, not the separators, are the contract.

- Run: `cd backend && python app.py` → localhost:5000 (`PORT`). **From `backend/`** (the `sys.path` root, top-level
  imports like `from config import Config`); never a `backend.` prefix.
- Lint — **three standards, three runs, all clean**: `ruff check backend/ tests/` + `ruff format --check backend/
  tests/` (same scope as CI), plus pylint with an explicit `--rcfile` (nested configs are ignored): `.pylintrc` for
  product code (`backend` minus `test_*.py`, `desktop`, `tools`, `ml_train/scripts`), `.pylintrc.tests` for `tests/`,
  `.pylintrc.probes` for `backend/test_*.py`. **Never `# pylint: disable` / `# noqa` / widen a config**: fix the cause;
  a truly meaningless message is excused in that tree's config with a written reason.
- Deps: *every directly-imported package* into `.venv/` **and** `requirements.txt` in the same change (even
  transitively); new tool caches into `.gitignore`. torch/transformers for `sentiment`'s `bert` go to
  `requirements-optional.txt`, never CI.
- **Never SILENTLY answer with a model other than the one claimed**: a sanctioned degradation PRINTS the method that
  ran (topic `method=auto`→embedding/LDA; sentiment/emotion/tendency bert→`snownlp`/`ml`); analyzers refuse an
  unrunnable `bert` by name; a multi-model BERT comparison never degrades.
- CI (`.github/workflows/ci.yml`, windows-latest): fast tier + `ruff check`/`format --check` over `backend/ tests/`.
  The local PostToolUse `ruff format` silently fails on a restricted workspace (`os error 5`) — format by hand; CI is
  the unskippable gate. `backend/test_*.py` are manual probe scripts, NOT pytest.
- `ml_train/` (gitignored) trains the sklearn+bert models the `emotion`/`tendency`/`sentiment` analyzers load
  (`data/model_registry.json`); changing features/labels means retraining there (`ml_train/README.md`).
- **Test tiers** (`pytest.ini` excludes real tiers; pinned by `tests/unit/gates/test_test_tiers.py`):
  - Fast: `python -m pytest -q` (~8.2k, no browser/daemon). Device: `-m "integration or live_ollama"` (real Chrome on
    `file://` + real Ollama; LLM-boundary mocks by default). Live: `-m live_quick` / `-m live_site`.
  - **Never run live unattended — it spends the user's accounts.** Own profile root (a copied login is a second
    device); only `CIXI_LIVE_USE_USER_PROFILE=1` (his consent) crawls as he does; weibo asked once per pass; split
    `live_cn`/`live_os` — **ask which network he is on**, then run the other.
  - **Unavailable browser/daemon SKIPS, so a tier can look green without running.** When green must be evidence set
    `CRAWLER_REQUIRE_BROWSER=1`/`CRAWLER_REQUIRE_OLLAMA=1` (fail instead of skip); `CRAWLER_REQUIRE_NODE=1` aborts the
    session in `pytest_configure` for the ~43 JS modules (~1.4k cases) that `skipif(node is None)`.
  - One device/live case: override the marker filter too (naming the file alone reports `N deselected`).
  - Layout `tests/unit`, `tests/api` (tmp-isolated `test_client`), `tests/integration`. OpenRouter is **never** really
    called — patch `analyzers.llm_client.requests.post/get`. Frontend JS needs `node`.

## How tests are written here

- **Isolation happens at conftest import; the suite fails if `data/` or `logs/` gains a byte.**
- **A warning is a test that noticed something and passed anyway — fix it, never mute it** (no `filterwarnings`).
- **A stateful rule needs a stateless suite:** `quiet_jar` snapshots/restores the shared cookie dir; a crawl test
  declares `seeded_logins`; a test *about* the login rule points `Config.COOKIE_DIR` at its own tmp dir.
- **The `integration` UI tier performs no server writes** (no data-dir switch) — stub `fetch`.
- **A test may not assume the machine: CI is UTC, this box is UTC+8.** Ask the machine (`astimezone()`); `TZ` **is**
  honoured on Windows — `$env:TZ='UTC'` before believing a green run.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the bug's one.

### Frontend JS

- **JS is under test.** `tests/frontend/harness_*.mjs` load the REAL `canvas.js`/`workflow.js`/`app.js` into a node
  `vm` (`harness_dom.mjs`), driven by `tests/unit/frontend/test_frontend_*`; any result-affecting JS change syncs a
  scenario; `urlPlatform` is contract-pinned against `core.refs.platform_for`.
- **A JS split registers in `tests/frontend/splits.json`, and the companion closure is TRANSITIVE** (same rule in
  `companions.mjs` and `frontend_catalogue.with_companions`, keyed by the page spelling `panels/x.js`): a harness
  naming `workflow.js` receives every module split out of its companions, or it boots half a panel. Harnesses take
  files through `sourcesWithCompanions` (**one read per file** — naming an owner and its companion is not a licence to
  evaluate twice, and a doubled top-level `const` is a redeclaration), never their own `readFileSync(argv)`;
  Python-side scans use `static_assets.js_text(name)`. **Splitting an object's MEMBERS keeps ONE global via
  `Object.assign(obj, { … })`** (a later script cannot rebind a top-level `const`; onclick handlers name the object):
  member lines stay verbatim and the sections' member sets must be disjoint (a duplicate is a silent overwrite).
- **The frontend holds no second opinion about a crawl.** `sourceNodeErrors()` asks `Capabilities` which fields the
  mode requires — if not loaded, refuse, never guess. A stored value off the option list shows as itself
  (`selectOptionTags`/`boolParam`), never option #0.
- **Six frontend rules, each costing a feature:** (1) `if (window.X)` cannot see a top-level `const X` — guard the
  binding or export it; (2) the DOM stub's matcher is real — never fabricate a child a query finds nothing for; (3) a
  wrapper must forward its arguments (an empty list acts on the *previous* selection); (4) `onclick="fn('…')"` spans
  two grammars — `attrJsArg` JS-escapes then HTML-escapes; (5) a node captured before an `await` is gone after it —
  re-look it up (`_rowFor`, holder by id); (6) a wrapper installed in another file is not what the harness loads —
  forward `(...args)` and measure behind a patched global in the browser tier.
- **A canvas shortcut belongs to the canvas only while the user is not typing:** `canvas._isTypingTarget()` (what the
  element IS), not a growing tag list.
- **History entries are snapshots, identical ones are not entries:** `getState()` deep-copies params; `_pushState()`
  skips a state equal to current; `restoreState()` is bracketed by `_historySaving` (one restore = one undo point).
- **The camera is not part of the model:** pan/zoom live in `serializeDraft()`/`settings.view`, NEVER `getState()`;
  `restoreState` leaves the camera alone; `addNode` randomizes only a non-finite x/y (0 is a position).
- **One page boot must not be a single point of failure:** a throw in the one `DOMContentLoaded` body skips every later
  step, so boot steps go through `boot(name, fn)`.
- **A dialog with an input is answered by the input:** leave `value:` off `showDialog` input dialogs.

### Measurement and live assertions

- **A browser-measured assertion must report how much it measured:** audit containers **by id**, never `<body>`,
  report a per-container floor, resolve wording from `I18n`. **State the viewport** — Windows ignores
  `set_window_size`/`set_window_rect`, so emulate (`Emulation.setDeviceMetricsOverride`) and assert the size CSS sees
  with a `100vh` probe (`window.innerHeight` is the un-emulated one).
- **A closed panel must be GONE, not merely moved — only pixels say so.** The real-browser tier compares the closed
  strip byte-for-byte with the same box at `display:none`, after a closed-vs-closed control that must match exactly; an
  unreproducible comparison is REFUSED, never passed.
- **A live case's numbers are computed from the site, never chosen** — derive thresholds from what the crawl reported
  and make the assertion two-sided.
- The `live_site` tier retries once **only** on a crawler-reported `login_wall`; assert a refusal that NAMES it
  (wall/risk) — an unnamed empty is real "found nothing" and stays red.

## Run, resume and record

### Data root, single-run ownership, module scope

- Runtime state lives in gitignored `data/` (`runs.db`/`datasets.db`/`history.db`) and `logs/`, always the
  checkout-level pair, never a `data/` beside code. `data/workflows/` is the ONE versioned exception (authored work) but
  references datasets **by id**, so a checkout only runs next to the same `data/`. Do not delete `data/` casually.
- **One server per data root, by design** (local single-user tool). `promote_stale_runs()` kills a same-`data/` rival's
  live run; `CRAWLER_DATA_ROOT` gives a process its own `data/`+`logs/` (`/smoke-verify` and the UI tier use it).
  Without it, **ask before booting a second server, and never kill a process on 5000.**
- **One run at a time; a busy server queues instead of refusing.** `begin_run()` owns the start path — the queue drains
  by calling *that*, never a weaker one; `queue:false` keeps the 400 for fail-fast callers. The worker's `finally`
  clears `execution_state['thread']` **first** (the claim checks thread liveness). Queues are in-memory
  (`tests/conftest.py` clears `_RUN_QUEUE`); the Execute button is never disabled, it relabels 排队运行.
- **A test that calls an executor function directly must leave the app quiet:** `clean_globals` *fails* a leaked
  `execution_state['running']`.
- **A run helper needing no claim state lives at module scope; a captured name is a parameter.** Ten were lifted out of
  `begin_run`'s closure on 2026-10-29 (last: `run` → `_run_worker`, the eight claim-time names as parameters) — inside
  a closure no test can reach them. Proof is `ast.dump` equality (multi-line strings modulo indent, single-line
  strict) plus `symtable` free-variable count 0, never a byte diff.
  `tests/unit/gates/test_run_worker_module_scope.py` fails any re-embedding.

### Checkpoint, cursor and ledger

- **Checkpointing is the core value** (`services/runs/store/__init__.py`): outputs and LLM answers persist so a run
  resumes, not re-crawls/re-pays; keep `runs.db` state compatible. Three pinned rules: the row sink writes **one
  transaction per row**; the next slot is `MAX(seq)+1`, **never `COUNT(*)`**; a **cursor records position, not
  content** (`Crawler.seed` supplies ids; never re-feed an id list into `mark_position`).
- **A cursor records what the node PROVED, never what it attempted.** The comment engine writes its `url_index`
  *after* an input's rows land and stops advancing at the first hole — writing it *before* launders a tail refusal
  into 继续.
- **A row's ledger key is its site identity, not its content.** `item_key` answers a comment by (`平台`, `评论ID`) — its
  columns avoid `_URL_FIELDS`/`_AUTHOR_FIELDS`/`_BODY_FIELDS` (that would collapse an article's comment set into one
  key); the whole-row-hash fallback keys on volatile `楼层` (a fresh harness renumbers from 1).
- **A label is not an input.** A node fingerprint feeds children and the dedupe scope (`'item:'+node_fingerprint`), so a
  *name* inside it breaks the chain. `_VOLATILE_PARAMS` answers "chooses data, or just describes?": ids in; labels and
  switches (`recrawl`/`enabled`) out.
- **A disabled node is not on the canvas.** `engine.workflow.effective_workflow` drops it (off-type/off-upstream
  cascade; fan-in survives on one live input); validate/naming/fingerprint/execution run on that graph — disabling a
  workflow is disabling its head node.
- **Reuse has four rules:** `done` and `restored` are reusable; a zero-row result is never reused; the source node is
  never adopted (resumes by cursor); `begin_node` `dropped_stale` cancels reuse.
- **Retention must release what it destroyed:** `purge` also calls `forget_run_items`; an explicit `delete_run` still
  *keeps* claims (the user knew the crawl was paid for).

### Node identity and the crawl backend

- **The crawl backend is part of a node's identity.** `backend` (`selenium`/`catbus`) is keyed into the node
  fingerprint with `selenium`/blank **folded out** (else the switch moves every saved canvas's fingerprint), so the two
  backends never share a dedupe ledger, cursor or watermark scope. CatBus is a subprocess
  (`services/ingest/catbus.py`, `crawlers/backends/catbus.py`): cells, row columns and identity column come from the
  adapter's `capabilities` manifest — **never copied into a Python table** — and every failure names the missing part
  (no Node / no adapter / Node too old / unreadable manifest / no such cell / no CatBus login) instead of answering an
  empty table a node settles DONE on. Its login gate is keyed apart (`bilibili@work#catbus`) and never cached as a
  cookie verdict. Why/evidence: `docs/crawler_rules.md` → 「第二采集后端」; `docs/agent_practices.md` → "The second crawl
  backend (CatBus)".
- **A node id is a storage key — never re-mint one on restore.** Records, cursors, LLM caches and
  `workflow_fingerprint` key on it. `canvas.addNode(...,nodeId)` + `reserveId` keep `nextId` past it; both restore paths
  pass file ids straight through (`harness_state.mjs`). It is also the box's **DOM** id, so never
  `getElementById(<node id>)` a workflow-supplied value: use `canvas._nodeEl(id)`, and `test_frontend_state_js.py`
  fails any variable-argument `getElementById` in canvas.js.
- **Recorded rows are addressed by workflow, never by bare node id:** `_durable_node_rows` returns nothing rather than
  guessing on an unqualified id. The browser sends `workflow_name` from `workflow.runName()` (name-node label, then
  file name).
- **`' + '` is a composed lookup key, not a permission:** `_durable_node_rows` widens to pieces only on a miss (so
  `节奏` is never handed `节奏 + BPM`'s table).

### Records, settlement and resume

- **Parallel is one record; serial is one record per workflow that started.** Parallel joins labels with `' + '`
  (canvas order; also a lookup key, pinned by `TestRowLookupStillWorks`); serial opens each workflow's row **as
  reached**. Every row keeps the **canvas** fingerprint (resume banner + `/api/runs/resumable`); the response returns
  workflow zero's row; 继续 adopts each by name. **A chip describes what happened:** `并行 ×N` only when
  `mode=='parallel'`, serial says `串行 ×1`; resume state stays **per workflow** (`fingerprints_for_workflow`) so B's
  failure restores A.
- **Startup recovery shares the end-of-run settlement:** a kill skips `finish_node`, so `promote_stale_runs` must call
  `settle_nodes` (status *and* row_count from the rows) — 已存行数 and 续跑's "adopt the fullest node" both read that
  column.
- **One definition of "completed":** `runs.node_done` and `completed_nodes` agree — skipped/failed/partial are not
  done, `restored` is; counts are taken **after** settling over `attempted_nodes`; a node 停止 cut short counts in
  `stopped_node_ids`, never as 「1 个失败」.
- **A resumed run re-describes itself:** `start_run`'s conflict update refreshes `workflow_name`/
  `workflow_fingerprint`/`mode`/`headless`/`lang` (not `started_at`), or the chips lie and kept rows become unfindable.

## Analysis steps and the data contract

- **A step's output column names are a chart's input contract.** 主题距离图 reads `pc1/pc2/topic/prevalence_pct`;
  显著词图 reads `term/overall_freq/within_freq`; both are parameters with those defaults and **refuse a missing
  column** — a rename on one side is a named refusal on the other, not an empty figure.
- **Anything that chooses data, cost or a name is refused BY NAME, never guessed** (mode/`select`/missing column via
  `data_analysis.validate_step`; analyzer `method`/`mode` via `app.enum_param`), and refusals `raise` rather than
  return `[]` (else a node settles DONE over an empty table). **Read a switch, never compare it** (`core.refs.as_bool`;
  blank = default).
- **A phase column's order is not data, and a records round trip erases it.** Node boundaries rebuild via
  `pd.DataFrame(current_input)` and drop the categorical. Anything grouping BY phase (分阶段 LDA, `TopicⅠ-1…`,
  主题生命周期/流向, 表 2 演化曲线, 分组聚合) takes the order from the categorical, else a NUMBER (`stage_order`/阶段序号)
  or TIME, else REFUSES — so a phase-table step must also emit its position column.
- **A quoted row count is only true of the merge order that produced it** (SimHash keeps the first-arriving row of a
  group). Measure through the canvas's OWN upstream order (walk `connections`, don't glob); a disagreeing re-measure
  means the order changed, not the data.
- **A coherence sweep is not a decision; only the canvas's own sweep may be quoted.** The scan's argmax follows row
  order and can be flat noise. The justifying scan runs `coherence_max_documents=0` fed by that canvas's own phase
  filters; where flat, state the tie-break in the node title (highest coherence at **≥3 topics**) — no unseen floor.
- **A score is a function of the column it was read from, so the column name belongs to the number.** `正文` vs
  `cleaned_text` give different curves; quote the column or the curve cannot be audited.
- **An unused LDA topic is the model's answer, not the user's mistake:** `topic_by_stage` fills the zero-doc row from
  the topic's word distribution, files `doc_n = 0`, logs one named warning — never kills the run or empties 特征词.
- **A recall device must not look like a classifier.** `aggression`'s word-list mode says a miss is unmeasurable, keeps
  the lists in code, and does NOT count 辟谣 accusations as violent; a missing text column **raises** rather than
  returning blanks.
- **The analysis node's one non-deterministic step borrows the process node's client:** `topic_label` calls the model
  once per row; `run_pipeline(df, steps, llm=, cancel=)` hands it to `LLM_OPS` only, never via `params` (params echo
  into the durable record). No model → refused before paying; a Stop leaves `未处理` → the node settles PARTIAL, not
  DONE.

## 定时任务 (scheduler)

- **The clock is one thread inside the server process, started only from `__main__`** (under the reloader, only the
  real serving child), and **a fire takes the same start path as a manual Run** — `scheduling.clock` calls the seam
  `engine.run_schedule.start_scheduled_run` → `begin_run`, so a busy server **queues** the fire. Two clocks would
  double-fire; a second start path would bypass single-run ownership.
- **A scheduled canvas may not need a model, and the rule is one rule asked twice**
  (`engine.run_schedule.scheduled_canvas`, shared by the panel's verdict, save time and fire time): refused **by
  name**, never by a server-side key. **A moment missed while the server was down is recorded (`missed.count`), never
  replayed** — at most one event per restart. Refusals and accounting go to the task's own history (`last_run` + 20
  entries), never into the run console, which gets exactly one attributed line when a run really starts (a queued fire
  is narrated by the queue).
- **The panel holds no second opinion about time or state:** `next_run_local`/`last_run_local` (rendered in the
  *task's* zone), the trigger sentence, `runnable`/`why_not` and the clock status all come from the server; a status
  token becomes a catalogue word — an unknown token shows as itself. Never format a moment in the browser, never
  invent a neighbouring word; `tests/unit/frontend/test_frontend_schedules.py` drives the real `schedules.js`.
  **A new dock belongs in `DOCKED_PANELS` *and* in the dock matrix** (`tests/frontend/harness_panels.mjs`, enforced by
  `TestTheDock`/`test_the_dock_matrix_in_the_shared_harness_still_covers_every_panel`).

## Console, messages and i18n

- UI text zh/en via `backend/i18n.py`, merging `backend/i18n_catalog/<domain>.py` (one module per domain:
  `crawl`/`collect`/`cookie`/`sched`/`run`/`analysis`/`biblio`/`charts`/`api`/`settings`): every new user-facing
  string goes to **its own domain, in both languages**, and to the browser catalogue
  (`backend/static/js/i18n/<domain>.js`, merged by `app.js`). A key declared in two domains is refused at import/load;
  a domain file missing from `MODULES` is a failed test.
- **A missing `t()` keyword is a printed bug, not a crash:** `t()` returns the raw template (a forgotten `{reads}`
  prints `阅读={reads}`), and parity/reachability are blind to it — `test_i18n.py::TestCallSitePlaceholders` walks every
  `t('literal', …)` with `ast` and refuses the mismatch.
- **A `{platform}` slot is answered with a word, not the key** (`zhihu` keys the matrix/cookie file; `i18n` localizes,
  splitting on `,`/`、` only) — `test_frontend_contract.py` keeps the two lists equal.
- Console/validation messages name nodes via `engine.workflow.node_label(node, nid)` (→ `title #nid`), never a bare
  `nid`; store keys/results/resume plumbing still use the raw `nid`. Both restore paths re-apply title + element text
  BEFORE `updateNodeDisplay` (whose re-stamp guard reads the element).
- **One failure, one line:** `LogBufferHandler` forwards `logger.*` into the buffer, so `logger.exception(...)` **and**
  a matching `add_log` double-print. Keep the logger call for the file's traceback; let `wf.node_failed` be the single
  attributed line; a helper adds a fact, never repeats the reason.
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook:** no
  Executing/completed line, but progress counters still count them and every fact still prints (with `node_label`, so
  a silenced node that fails is still diagnosable).
- **Every thread that logs must pin its own language** (`set_lang` is thread-local; a daemon starts fresh): `run()`,
  the parallel pool wrapper and both cookie workers set it first. Assert console text on the reason, not a sentence.

### The run console

- **The console keeps its own history per view, because the server cannot give it back** (only the last 200 lines of
  the whole run ship). `consoleViews` holds `{seen, lines}` per view (`'all'` + each workflow id), every view is fed on
  every poll, and `switchWfTab` repaints without moving the cursor.
- **The console is ALSO persisted per run (`run_store.run_log`), as a pure side effect that may never move the live
  console.** `_push_log` → `engine.run_logs.RunLogWriter` via `set_log_sink`, armed only inside a run's window. The
  durable viewer (`/api/runs/<id>/log(.txt)`, `runLogViewer`) reads ONLY that table. **The reattach
  (`execution_state['logs']/_log_total/_wf_logs/_wf_log_total` + `?tail=5000`) must stay byte-identical with or without
  a sink** — a shifted total is a cursor that skips/repeats live lines after reload; `test_console_buffer.py` fails
  that invariant.
- **`_push_log` stores one entry per physical line** — the total advances by lines, not `add_log` calls.

### Sessions, cookies and run gating

- Run-gating lives in `workflow.js execute()` → `_cookieGateBeforeRun`: `cookie_preflight_before_run` probes each
  canvas platform **whose mode needs a session** (`Mode.needs_session`; weibo 热搜 is anonymous, wechat has no session
  to want); a login wall **refuses** (no "run anyway"), 「无法核对」 (timeout/captcha/busy) **never blocks**. Off asks
  nothing; a resume or crawl-free canvas skips it; a cookie write drops the cached verdict. **`execute()` asks no cookie
  question of its own.**
- A named cookie and a named profile belong together: one account = one `data/cookies/<platform>@<account>.json`
  **and** one `chrome_profile/<platform>/<account>`. A node's 账号 is a session question asked once:
  `_account_session_errors` refuses when `has_session_to_test` finds neither that account's cookie file *nor* a
  carrying profile — **blank IS an account (默认账号), not a wildcard.**
- Every account has one name and one spelling: the default is `default` (never a blank in the box), folded at
  `CookieManager.key`/`path_segment` (`''` ⇄ `default`, lowercase always); `sessions.profiles`/preflight/JS box route
  through that fold; the candidate list and a new node's preselection are both `CookieManager.accounts_in_order`.
- **A new settings key needs all four:** the bool branch in `settings_store.save_settings`, both browser catalogue
  sides, and the `AppSettings` wiring.

## Style and commits

- Comments and docstrings in **English** (README/commits are Chinese). Explain "why".
- Section dividers: `# ─── Name ───`.
- Ruff: line-length 120, **single quotes**, indent 4, modern typing (`str | None`), py311. Findings are **genuinely
  fixed**: never `# noqa`, never `# ruff: noqa`, never a `per-file-ignores` or rule exemption in `ruff.toml`.
- **Code changes are tracked Edits.** No Python/sed rewrite of any file: unrestorable = work is gone.
- Commits: Chinese messages with a type prefix — `功能更新：`, `问题修复：`, `修改：`.

## Change workflow (MANDATORY on every change)

**How much to run is decided by what the change can break, not by ritual** (one full tier set is ~18 min — measured).

- **Lane A — docs, comments, the anchor**: `tests/unit/gates/test_doc_paths.py`, plus `ruff check` if a `.py` was
  touched. ~1 min.
- **Lane B — a move, or test-seam retargeting with unchanged behavior**: the moved module's cases + the contract tests
  naming it + `ruff check`/`format --check` on touched files. ~2 min. The **full fast suite and both pylint tiers run
  once at the end of a batch of ~4 such knives** — catching what a move silently broke, before the next push.
- **Lane C — real behavior changes: run orchestration, resume/checkpoint, `runs.db`, UI, crawling, the LLM
  boundary**: full fast always; the device tier when UI/engine/LLM/crawling is touched; pylint at batch end. Being
  wrong here costs a spent account, a corrupted run record, or a figure that lies in a paper.
- **GitHub Actions on every push is the backstop** (fast + ruff + product/tests pylint; the probes tier is local-only,
  gitee has no CI), so a local batch run is the copy that decides whether to push.
- **The closure gate is NOT a lane**: any "it is done" claim means one full run of every tier, nothing deselected,
  nothing skipped, and **no file needing a change** in that run. Any edit restarts the loop.

- **Edit**: the PostToolUse hook auto-runs `ruff format` + `ruff check --fix` on touched `.py` files; every committed
  file still passes `ruff check`/`format --check` by hand.
- **Tests ship with the change.** Any code file touched (backend *or* frontend JS) syncs the suite in the same change:
  new feature → test it; changed behavior → update assertions; deleted feature → remove its tests. A previously-green
  test failing because of your change means the bug is the change — fix the code, not the test (unless it pinned an
  old bug). A genuine product bug that cannot land now gets
  `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — ...')` plus a report.
- **Docs stay true**: `README.md` on any user-visible change (features, node types, API tables, config, structure,
  quickstart); crawler measurements → `docs/crawler_notes.md`; a new crawl-side rule → `docs/crawler_rules.md`; a new
  rule's *why/evidence* → `docs/agent_practices.md`. A stale README is a failed change.
- **New packages**: install into `.venv/` AND declare in `requirements.txt` in the same change, caches in `.gitignore`.
- **Device paths**: crawling, LLM transports, checkpoint/resume or UI touched → also `-m "integration or live_ollama"`
  and `-m live_quick` (Chrome + Ollama and one real crawl per platform exist here — check port 5000 is free first),
  then `/smoke-verify`.
- **Commit last**, with a Chinese type prefix.
