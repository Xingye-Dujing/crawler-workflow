# AGENTS.md

Rules for the AI agent, loaded into **every** session. Each rule is stated bare. Its **why/evidence** — every
hard-won measurement and crash — is in [`docs/agent_practices.md`](docs/agent_practices.md) (not auto-loaded): read
the matching section before rewriting, doubting, or "simplifying away" any rule below. Grep by the bolded title.

**采集端（crawler/platform）规则已拆到 [`docs/crawler_rules.md`](docs/crawler_rules.md)**。
**改爬虫、其列或真站断言前，先读该文件，再读 `docs/crawler_notes.md` 对应平台小节**——那里的规则都真机付过钱。

## Project

采析绘 (crawler_workflow): Flask + zero-build vanilla-JS that crawls Chinese and overseas social media (9 platforms;
instagram cookie-capture only) via Selenium, cleans and analyzes the text with local Ollama LLMs and scikit-learn, and
renders a drag-and-drop workflow canvas.

## Cross-platform (MANDATORY on every change)

**Three platforms are in scope: Windows (development), Linux (cloud deployment), macOS.** Nothing in `backend/`,
`tools/`, `ml_train/`, `tests/` or the docs may hardcode a Windows assumption — a drive letter, `\` path joining, an
`.exe` suffix, `%APPDATA%`/`PROGRAMFILES` lookups, `taskkill`, a cp936 console, or a Windows-only font name. Every
change is judged on all three, not on the machine it was typed on. Why/evidence:
`docs/agent_practices.md` → "Cross-platform / Win・Linux・macOS 三套系统".

- **A capability that truly cannot exist off Windows refuses BY NAME and its UI entry disappears.** Refusing at
  run time is not enough (the user pays a node start for an answer known at load); the front-end must not offer it.
  Ask the server once — `Config.CLOUD_MODE` / `sys.platform` folded into a capability verdict — never keep a second
  opinion in JS. Existing answers: 红果短剧 harvest (mitmdump + UIA + crypt32), the login-cookie window, local
  Ollama under cloud mode.
- **`desktop/` is the ONE deliberate Windows-only tree** (PyInstaller/UPX/Inno). Its Windows facts stay there and
  must not leak into `backend/`; the packaged EXE is judged on Windows alone.
- **Machine-level lookups are per-OS in one place.** Chrome / xelatex / **Node + the CatBus adapter**
  candidates are tables keyed by the running OS in `utils/machine_deps.py` and `services/latex_compile.py`,
  and they are joined with the TARGET's separator (`ntpath`/`posixpath`) so a Windows test can ask what a
  Linux box would find. The CJK font stack and the ctex font set carry each OS's own names in
  `services/visualizer.py` and `services/latex_charts.py`. `CHROME_BIN`/`CHROME_PATH` remain the explicit
  override (`CIXI_NODE_BIN`/`NODE_BIN`, `CIXI_CATBUS_CLI`/`CATBUS_CLI`/`CATBUS_HOME` the adapter's). Never
  inline a `Program Files` path, a `.exe` name or a `taskkill` anywhere else.
- **A `Popen` keyword that only exists on one OS belongs in `utils/procs`.** `windowsHide` is not a
  `Popen` keyword at all (measured: `TypeError`); the answer is `creationflags=CREATE_NO_WINDOW`, which
  POSIX' `subprocess` does not define — so it is `procs.popen_kwargs()` and tests ask all three systems.
  Likewise a piped **child** writes the ANSI code page unless it reconfigures itself: cross the boundary in
  bytes and decode UTF-8 by hand, and pass parameters on stdin, never argv.
- **Platform-independent tests are the proof.** No test may pass only because it ran on Windows: no drive letters
  as data, no `.exe` filename pinning a refusal, no `sys.platform='win32'` monkeypatch that fakes a gate the
  product reads (patch both sides or assert the refusal), no timezone literal for the "server local" zone.
- **Byte limits are byte limits:** a Linux filename cap is UTF-8 **bytes** (ext4 NAME_MAX 255), a Windows path cap
  is characters — measure the one you are actually protecting.
- **Real Linux/macOS startup is not verifiable on this box** (no docker, no WSL, by the user's decision). Such
  changes are landed as code + platform-independent tests, and the Linux side is listed as an explicitly unverified
  surface to be run on the server; the docs state the Linux system packages (Chrome/Chromium + driver,
  `fonts-noto-cjk`, optional `texlive-xetex`/`texlive-lang-chinese`).

## Commands

**venv `.venv/` (Python 3.11) is mandatory — never system Python.** Call `.venv/Scripts/python.exe`/`ruff.exe`/
`pylint.exe`/`pip.exe` directly (or `source .venv/Scripts/activate`). Those spellings are this box (Windows);
on Linux/macOS the same tools are `.venv/bin/python` / `.venv/bin/ruff` — the commands, not the separators, are
the contract.

- Run: `cd backend && python app.py` → localhost:5000 (port via `PORT`). **Run from `backend/`** (the `sys.path` root,
  so imports are top-level like `from config import Config`); never add a `backend.` prefix.
- Lint: `ruff check backend/ tests/` and `ruff format --check backend/ tests/` (fast gate, same scope as CI), **plus
  pylint — three standards, three runs, all clean**: `.pylintrc` for product code (`backend` minus its
  `test_*.py`, `desktop`, `tools`, `ml_train/scripts`), `.pylintrc.tests` for `tests/`, `.pylintrc.probes` for the
  `backend/test_*.py` measurement scripts. Nested config files are ignored by pylint (measured), so each tier is
  its own call with an explicit `--rcfile`. **Never write `# pylint: disable` or `# noqa`** and never widen a
  `.pylintrc*` to make a finding go away: fix the cause, and where a message is truly meaningless for that tree
  the exception lives in that tree's config with a written reason. Every exemption in those files is already
  justified there — adding one is a decision to argue about, not a shortcut.
- Deps: *every directly-imported package* goes into `.venv/` **and** `requirements.txt` in the same change (even
  transitively); a new tool's caches into `.gitignore`. torch/transformers that `sentiment`'s `bert` probes for go to
  `requirements-optional.txt`, never CI. **Never SILENTLY answer with a model other than the one it claims** — a
  sanctioned degradation must PRINT the method that ran (topic `method=auto`→embedding/LDA; sentiment/emotion/tendency
  bert→`snownlp`/`ml`); analyzers refuse an unrunnable `bert` by name; a multi-model BERT comparison never degrades.
- CI (`.github/workflows/ci.yml`, windows-latest): fast tier + `ruff check`/`ruff format --check` over `backend/ tests/`.
  The local PostToolUse `ruff format` **silently fails on a restricted workspace** (`os error 5`) — run `ruff format` by
  hand before committing; CI is the unskippable gate.
- `backend/test_*.py` are manual probe scripts, NOT pytest — the home for a one-off measurement.
- `ml_train/` (gitignored) trains the sklearn+bert models the `emotion`/`tendency`/`sentiment` analyzers load
  (registered in `data/model_registry.json`); changing their features/labels means retraining there. See
  `ml_train/README.md`.
- **Test tiers** (`pytest.ini` excludes real tiers; pinned by `tests/unit/test_test_tiers.py`):
  - Fast: `.venv/Scripts/python.exe -m pytest -q` (~5.2k cases, ~2 min, no browser/daemon).
  - Device: `-m "integration or live_ollama"` (real Chrome on `file://` + real Ollama; LLM-boundary mocks by default).
  - Live: `-m live_quick` (one visit per platform) or `-m live_site` (full pass). **Never run a live tier unattended:
    it spends the user's accounts.** It keeps its own profile root (a copied login is a second device); only
    `CIXI_LIVE_USE_USER_PROFILE=1` (his consent) crawls as he does; weibo asked once per pass; split `live_cn`/`live_os`
    — **ask which network he is on**, then run the other.
  - **An unavailable browser/daemon SKIPS, so a tier can look green without running** — when green must be evidence, set
    `CRAWLER_REQUIRE_BROWSER=1`/`CRAWLER_REQUIRE_OLLAMA=1` to FAIL instead of skip. `CRAWLER_REQUIRE_NODE=1` does the
    same for the ~43 frontend JS cases that `skipif(node is None)`: it aborts the session in `pytest_configure`,
    because "43 skipped" is indistinguishable from a tier that never existed.
  - **To run one device/live case, override the marker filter too** (naming the file alone reports `N deselected`).
  - Layout: `tests/unit`, `tests/api` (tmp-isolated `test_client`), `tests/integration` (marked Chrome/Ollama).
    OpenRouter is **never** really called — patch `analyzers.llm_client.requests.post/get`. Frontend JS needs `node`.

## How tests are written here

- **Isolation happens at conftest import, and the suite fails if `data/` or `logs/` gains a byte.**
- **A warning is a test that noticed something and passed anyway — fix what it noticed, never mute it.** `pytest.ini`
  has no `filterwarnings`; adding an `ignore` is not closing one.
- **A stateful rule needs a stateless suite.** One shared cookie dir → `quiet_jar` snapshots/restores it per test; a
  crawl test declares `seeded_logins`; a test *about* the login rule points `Config.COOKIE_DIR` at its own tmp dir.
- **Frontend JS is under test too.** `tests/frontend/harness_*.mjs` load the REAL `canvas.js`/`workflow.js`/`app.js`
  into a node `vm` (`harness_dom.mjs`), driven by `tests/unit/test_frontend_*`; any result-affecting JS change must
  sync a scenario; `urlPlatform` is contract-pinned against `utils.helpers.platform_for`.
- **The frontend may not hold a second opinion about a crawl.** `sourceNodeErrors()` asks `Capabilities` which fields the
  selected mode requires; if not loaded, refuse — never guess a shape. A stored value off the option list shows as
  itself (`selectOptionTags`/`boolParam`), never option #0.
- **A canvas shortcut belongs to the canvas only while the user is not typing:** use `canvas._isTypingTarget()` (what the
  element IS), not a growing tag list.
- **History entries are snapshots, and identical ones are not entries:** `getState()` deep-copies params, `_pushState()`
  skips a state equal to current, `restoreState()` brackets itself with `_historySaving` (one restore = one undo point).
- **The camera is not part of the model:** pan/zoom go in `serializeDraft()`/`settings.view`, NEVER `getState()`;
  `restoreState` leaves the camera alone. A saved x/y of 0 is a position — `addNode` randomizes only a non-finite value.
- **One page boot must not be a single point of failure:** a throw in the one `DOMContentLoaded` body skips every later
  step, so boot steps go through `boot(name, fn)`.
- **A dialog with an input is answered by the input:** a confirm button's own `value:` overrides what the user typed, so
  leave `value` off `showDialog` input dialogs.
- **Six frontend rules, each costing a feature when forgotten:** (1) `if (window.X)` cannot see a top-level `const X` —
  guard the binding or export it; (2) the DOM stub's matcher is real — never fabricate a child a query finds nothing
  for; (3) a wrapper must forward its arguments (an empty list acts on the *previous* selection); (4) a name inside
  `onclick="fn('…')"` spans two grammars — `attrJsArg` JS-escapes then HTML-escapes the attribute; (5) a node captured
  before an `await` is gone after it — re-look it up (`_rowFor`, holder by id); (6) a wrapper installed in another file
  is not the function your harness loads — forward `(...args)` and measure behind a patched global in the browser tier.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the one the bug was
  about.
- **A live case's numbers are computed from the site, never chosen** — derive thresholds from what the crawl reported
  (card's 评论数, the page's own count, the board's size) and make the assertion two-sided.
- **A browser-measured assertion must report how much it measured** — audit containers **by id**, never fall back to
  `<body>`, report a per-container floor, resolve wording from `I18n`. **State the viewport:** Windows ignores
  `set_window_size`/`set_window_rect`, so emulate (`Emulation.setDeviceMetricsOverride`) and assert the size CSS sees
  with a `100vh` probe (`window.innerHeight` reports the un-emulated one).
- **A closed panel must be GONE, not merely moved — and only pixels say so.** A fixed box whose side offset is not paid
  for in its closed translate leaves exactly that offset on screen (`right: 12px` + `translateX(100%)` = a 12px sliver),
  and a `box-shadow` blurs past the border box where no rect and no hit-test can see it. The real-browser tier compares
  the closed strip byte-for-byte against the same box at `display:none`, after a closed-vs-closed control that must match
  exactly — an unreproducible comparison is REFUSED, never quietly passed.
- **A test may not assume the machine it runs on: CI is UTC, this box is UTC+8.** A wall-clock literal for the
  blank/"server local" zone passes only where it was written; ask the machine (`astimezone()` is the definition the
  product uses). `TZ` **is** honoured by Python on Windows, so the other machine is reproducible here
  (`$env:TZ='UTC'`) — do that before believing a green run.
- **The `integration` UI tier performs no server writes** (no data-dir switch exists) — stub `fetch`.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall`; assert a refusal that
  NAMES it (wall/risk) — an unnamed empty is real "found nothing" and stays red.

## Run, resume and record invariants

- Runtime state lives in gitignored `data/` (`runs.db`/`datasets.db`/`history.db`) and `logs/`. `data/workflows/` is the
  ONE versioned exception (authored work) but references datasets **by id**, so a checkout only runs next to the same
  `data/`. Do not delete `data/` casually.
- **A step's output column names are a chart's input contract.** 主题距离图 reads `pc1/pc2/topic/prevalence_pct`,
  显著词图 reads `term/overall_freq/within_freq`; both take the names as parameters with those defaults and **refuse a
  missing column** — a rename on one side is a named refusal on the other, not an empty figure.
- **One server per data root, by design (local single-user tool).** `promote_stale_runs()` kills a same-`data/` rival's
  live run; `CRAWLER_DATA_ROOT` gives a process its own `data/`+`logs/` (`/smoke-verify` and the UI tier use it).
  Without it, **ask before booting a second server, and never kill a process on 5000.**
- **One run at a time; a busy server queues instead of refusing.** `_begin_run()` owns the whole start path, so the queue
  drains by calling *that* function, never a weaker one; `queue:false` keeps the 400 for fail-fast callers. The worker's
  `finally` clears `execution_state['thread']` **first** (the claim checks thread liveness). Queues are in-memory
  (`tests/conftest.py` clears `_RUN_QUEUE`); the Execute button is never disabled, it relabels 排队运行.
- **A test that calls an executor function directly must leave the app quiet:** `clean_globals` *fails* a test that leaks
  `execution_state['running']`.
- **Checkpointing is the core value** (`services/run_store.py`): outputs and LLM answers persist so a run resumes, not
  re-crawls/re-pays; keep `runs.db` state compatible. Three pinned rules: the row sink writes **one transaction per
  row**; the next slot is `MAX(seq)+1`, **never `COUNT(*)`**; a **cursor records position, not content** (`Crawler.seed`
  supplies ids; never re-feed an id list into `mark_position`).
- **The crawl backend is part of a node's identity.** `backend` (`selenium` / `catbus`) is keyed into the node
  fingerprint with `selenium`/blank **folded out** (the `account`/`model` precedent — unfolded, adding the switch
  would move every saved canvas's fingerprint and 继续 would re-crawl the whole library), so the two backends never
  share a dedupe ledger, a cursor or a watermark scope. CatBus is a subprocess (`services/catbus_bridge.py`,
  `crawlers/catbus.py`): which cells exist, which columns a row has and which column is its identity are read out of
  the adapter's own `capabilities` manifest — **never copied into a Python table**; and every failure names the
  missing part (no Node / no adapter / Node too old / unreadable manifest / no such cell / no CatBus login) rather
  than answering with an empty table, which a node would settle DONE on. Its login gate is keyed apart
  (`bilibili@work#catbus`) and never cached as a cookie verdict. Why/evidence: `docs/crawler_rules.md` →
  「第二采集后端」, `docs/agent_practices.md` → "The second crawl backend (CatBus)".
- **A cursor records what the node PROVED, never what it attempted.** The comment engine writes its `url_index` *after*
  an input's rows land and stops advancing at the first hole — writing it *before* left it at `len(urls)-1` after a
  full pass, so a tail refusal (skipped drama, under-target) was laundered by 继续: the replay re-walked the LAST link
  only, a fresh harness reported no skips, and the node settled DONE over the hole its own console line had named.
- **A row's ledger key is its site identity, not its content.** `item_key` answers a comment by (`平台`, `评论ID`) —
  its columns deliberately avoid `_URL_FIELDS`/`_AUTHOR_FIELDS`/`_BODY_FIELDS` (that would collapse one article's whole
  comment set into one key), and falling through to the whole-row hash keyed on volatile `楼层`, which a fresh harness
  numbers from 1 again, so every resume re-stored a re-walked article's comments with invented floors.
- **A label is not an input.** A node fingerprint feeds children and the dedupe scope (`'item:'+node_fingerprint`), so a
  *name* inside one breaks the chain. `_VOLATILE_PARAMS` answers "chooses data, or just describes?": ids in, labels and
  switches (`recrawl`/`enabled`) out.
- **A disabled node is not on the canvas.** `engine.workflow.effective_workflow` drops it (off-type/off-upstream cascade;
  fan-in survives on one live input), and validate/naming/fingerprint/execution run on that graph — disabling a workflow
  is disabling its head node.
- **Reuse has four rules:** `done` AND `restored` are reusable; a stored result with **zero rows** is never reused; the
  source node is never adopted (resumes by cursor); `begin_node` `dropped_stale` cancels reuse.
- **Startup recovery shares the end-of-run settlement:** a kill skips `finish_node`, so `promote_stale_runs` must call
  `settle_nodes` (status *and* row_count from the rows) — the panel's 已存行数 and 续跑's "adopt the fullest node" both
  read that column.
- **One definition of "completed":** `runs.node_done` and `completed_nodes` agree — skipped/failed/partial are not done,
  `restored` is; counts are taken **after** settling over `attempted_nodes`; a node 停止 cut short counts in
  `stopped_node_ids`, never as 「1 个失败」.
- **A resumed run re-describes itself:** `start_run`'s conflict update refreshes `workflow_name`/`workflow_fingerprint`/
  `mode`/`headless`/`lang` (not `started_at`), or the chips lie and the stale name makes kept rows unfindable.
- **A phase column's order is not data, and a records round trip erases it.** Node boundaries rebuild via
  `pd.DataFrame(current_input)` and drop the categorical. Anything grouping BY phase (分阶段 LDA, `TopicⅠ-1…`,
  主题生命周期/流向, 表 2 演化曲线, 分组聚合) takes the order from the categorical, else from a NUMBER (`stage_order`/
  阶段序号) or TIME, else REFUSES — so a phase-table step must also emit its position column.
- **A quoted row count is only true of the merge order that produced it** (SimHash keeps the first-arriving row of a
  group). Measure through the canvas's OWN upstream order (walk `connections`, don't glob); a disagreeing re-measure
  means the order changed, not the data.
- **A coherence sweep is not a decision, and only the canvas's own sweep may be quoted:** the scan's argmax follows row
  order and can be flat noise. The justifying scan runs `coherence_max_documents=0` fed by that canvas's own phase
  filters; where flat, state the tie-break in the node title (highest coherence at **≥3 topics**) — no unseen floor.
- **A score is a function of the column it was read from, so the column name belongs to the number.** `正文` vs
  `cleaned_text` give different curves; quote the column or the curve can't be audited.
- **An unused LDA topic is the model's answer, not the user's mistake:** `topic_by_stage` fills the zero-doc row from the
  topic's word distribution, files `doc_n = 0`, logs one named warning — never kills the run or empties 特征词.
- **A recall device must not look like a classifier.** `aggression`'s word-list mode says a miss is unmeasurable, keeps
  the lists in code, and does NOT count 辟谣 accusations as violent; a missing text column **raises** rather than
  returning blanks.
- **The analysis node's one non-deterministic step borrows the process node's client:** `topic_label` calls the model once
  per row; `run_pipeline(df, steps, llm=, cancel=)` hands those to `LLM_OPS` only, never via `params` (params echo into
  the durable record). No model → refused before paying; a Stop leaves `未处理` → the node settles PARTIAL, not DONE.
- **Retention must release what it destroyed:** `purge` also calls `forget_run_items`; an explicit `delete_run` still
  *keeps* claims (the user knew the crawl was paid for).
- **`' + '` is a composed lookup key, not a permission:** `_durable_node_rows` widens to pieces only on a miss (so `节奏`
  is never handed `节奏 + BPM`'s table).
- **A node id is a storage key — never re-mint one on restore.** Records, cursors, LLM caches and `workflow_fingerprint`
  key on node ids. `canvas.addNode(...,nodeId)` + `reserveId` keep `nextId` past it; both restore paths pass file ids
  straight through (`harness_state.mjs`). That id is also the box's **DOM** id, so never `getElementById(<node id>)` a
  workflow-supplied value: reach elements via `canvas._nodeEl(id)`, and `test_frontend_state_js.py` fails any
  variable-argument `getElementById` in canvas.js.
- **Recorded rows are addressed by workflow, never by bare node id:** `_durable_node_rows` returns nothing rather than
  guessing on an unqualified id. The browser sends `workflow_name` from `workflow.runName()` (name-node label, then file
  name).
- **Parallel is one record; serial is one record per workflow that started.** Parallel joins labels with `' + '` (canvas
  order; also a **lookup key**, pinned by `TestRowLookupStillWorks`); serial opens each workflow's own row **as reached**.
  Every row keeps the **canvas** fingerprint (resume banner + `/api/runs/resumable`); the response returns workflow zero's
  row; 继续 adopts each by name. **A chip describes what happened:** `并行 ×N` only when `mode=='parallel'`, serial says
  `串行 ×1`; resume state stays **per workflow** (`fingerprints_for_workflow`) so B's failure restores A.

## 定时任务 (scheduler)

- **The clock is one thread inside the server process, started only from `__main__`** (and, under the reloader, only in
  the real serving child), and **a fire takes the same start path as a manual Run** — `scheduler` never starts a run
  itself, it calls the seam `app._start_scheduled_run` → `_begin_run`, so a busy server **queues** the fire like any
  other request. Two clocks would double-fire; a second start path would bypass `_begin_run`'s single-run ownership.
- **A scheduled canvas may not need a model, and the rule is one rule asked twice** (`app._scheduled_canvas`, shared by
  the panel's verdict, save time and fire time): refused **by name**, never by a server-side key. **A moment missed while
  the server was down is recorded (`missed.count`), never replayed** — at most one event per restart. Refusals and
  accounting go to the task's own history (`last_run` + 20 entries), never into the run console, which gets exactly one
  attributed line when a run really starts (a queued fire is narrated by the queue).
- **The panel holds no second opinion about time or state:** `next_run_local`/`last_run_local` (rendered in the *task's*
  zone), the trigger sentence, `runnable`/`why_not` and the clock status all come from the server, and a status token
  becomes a catalogue word — an unknown token shows as itself. Never format a moment in the browser and never invent a
  neighbouring word; `tests/unit/test_frontend_schedules.py` drives the real `schedules.js`. **A new dock belongs in
  `DOCKED_PANELS` *and* in the dock matrix** (`tests/frontend/harness_panels.mjs`, enforced by
  `TestTheDock`/`test_the_dock_matrix_in_the_shared_harness_still_covers_every_panel`).

## Console, messages and i18n

- UI text supports zh/en via `backend/i18n.py` — add every new user-facing string there (both languages) **and** in the
  `backend/static/js/app.js` catalogs.
- **A missing `t()` keyword is a printed bug, not a crash:** `t()` returns the raw template when a param is missing (a
  forgotten `{reads}` prints `阅读={reads}`), and parity/reachability are blind to it — `test_i18n.py::
  TestCallSitePlaceholders` walks every `t('literal', …)` with `ast` and refuses the mismatch.
- **A `{platform}` slot is answered with a word, not the key** (`zhihu` keys the matrix/cookie file; `i18n` localizes,
  splitting on `,`/`、` only) — `test_frontend_contract.py` keeps the two lists equal.
- Console/validation messages reference nodes through `engine.workflow.node_label(node, nid)` (→ `title #nid`), never a
  bare `nid`; store keys / results / resume plumbing still use the raw `nid`. Both restore paths re-apply title + element
  text BEFORE `updateNodeDisplay` (whose re-stamp guard reads the element).
- **The run console keeps its own history per view, because the server cannot give it back** (only the last 200 lines of
  the whole run ship). `consoleViews` holds `{seen, lines}` per view (`'all'` + each workflow id), every view is fed on
  every poll, and `switchWfTab` repaints without moving the cursor.
- **The console is ALSO persisted per run (`run_store.run_log`), as a pure side effect that may never move the live
  console.** `_push_log` → `app._RunLogWriter` via `set_log_sink`, armed only inside a run's window. The durable viewer
  (`/api/runs/<id>/log(.txt)`, `runLogViewer`) reads ONLY that table. **The reattach (`execution_state['logs']/_log_total/
  _wf_logs/_wf_log_total` + `?tail=5000`) must stay byte-identical with or without a sink** — a shifted total is a cursor
  that skips/repeats live lines after reload; `test_console_buffer.py` fails that invariant.
- **Every thread that logs must pin its own language** (`set_lang` is thread-local; a daemon starts fresh), so `run()`,
  the parallel pool wrapper and both cookie workers set it first. Assert console text on the reason, not a sentence.
- **One failure, one line:** `LogBufferHandler` forwards `logger.*` into the buffer, so `logger.exception(...)` **and** a
  matching `add_log` double-print. Keep the logger call for the file's traceback; let `wf.node_failed` be the single
  attributed line; a helper adds a fact, never repeats the reason.
- **Anything that chooses data, cost or a name is refused BY NAME, never guessed** (mode/`select`/missing column via
  `data_analysis.validate_step`, analyzer `method`/`mode` via `app.enum_param`), and refusals `raise` rather than return
  `[]` (else a node settles DONE over an empty table). **Read a switch, never compare it** (`utils.helpers.as_bool`;
  blank = default).
- **`_push_log` stores one entry per physical line** — the total advances by lines, not `add_log` calls.
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook:** no "Executing/Node …
  completed" line, but progress counters still count them and every fact still prints (with `node_label`, so a silenced
  node that fails is still diagnosable).
- Run-gating lives in `workflow.js execute()` → `_cookieGateBeforeRun`: `cookie_preflight_before_run` probes each canvas
  platform **whose mode needs a session** (`Mode.needs_session`; weibo 热搜 is anonymous, wechat has no session to want);
  a login wall **refuses** (no "run anyway"), 「无法核对」 (timeout/captcha/busy) **never blocks**. Off asks nothing; a
  resume or crawl-free canvas skips it; a cookie write drops the cached verdict. **`execute()` asks no cookie question of
  its own.** A named cookie and a named profile belong together: one account = one
  `data/cookies/<platform>@<account>.json` **and** one `chrome_profile/<platform>/<account>`. A node's 账号 is a session
  question asked once: `_account_session_errors` refuses when `has_session_to_test` finds neither that account's cookie
  file *nor* a carrying profile — **blank IS an account (默认账号), not a wildcard.** Every account has one name and one
  spelling: the default is `default` (never a blank in the box), folded at `CookieManager.key`/`path_segment` (`''` ⇄
  `default`, lowercase always), so `browser_profiles`/preflight/JS box route through that fold; candidate list and a new
  node's preselection are both `CookieManager.accounts_in_order`. **A new settings key needs all four:** the bool branch
  in `settings_store.save_settings`, both app.js catalogs, and the `AppSettings` wiring.

## Style (differs from defaults)

- Comments and docstrings are in **English** even though README/commits are Chinese. Explain "why".
- Section dividers: `# ─── Name ───`.
- Ruff: line-length 120, **single quotes**, indent 4, modern typing (`str | None`), py311. Lint findings are
  **genuinely fixed**: never `# noqa`, never `# ruff: noqa`, never a `per-file-ignores` or rule exemption in
  `ruff.toml`.
- **Code changes are tracked Edits.** No Python/sed rewrite of any file: unrestorable = work is gone.

## Commits

Chinese messages with a type prefix matching history: `功能更新：`, `问题修复：`, `修改：`.

## Change workflow (MANDATORY on every change)

1. **Edit** — the PostToolUse hook auto-runs `ruff format` + `ruff check --fix` on touched `.py` files.
2. **Tests are part of the change.** Any code file touched (backend *or* frontend JS) means syncing the suite in the
   same change: new feature → test it; changed behavior → update the affected assertions; deleted feature → remove its
   tests. The suite must prove the new thing is right *and* nothing old broke. A previously-green test failing because of
   your change means the bug is in the change — fix the code, not the test (exception: it pinned an old bug now fixed).
3. **Fast suite green**: `.venv/Scripts/python.exe -m pytest -q`. Fix a genuine product bug in product code; if it can't
   land now, pin it with `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — ...')` and report it.
4. **Lint green** on every committed file: `ruff check <files>` and `ruff format --check <files>`.
5. **New packages**: install into `.venv/` AND declare in `requirements.txt` in the same change, caches in `.gitignore`.
6. **Docs stay true**: update `README.md` whenever user-visible behavior changed (features, node types, API tables,
   config, structure, quickstart). Move crawler measurements to `docs/crawler_notes.md`, any new crawl-side rule to
   `docs/crawler_rules.md`, and any new rule *why/evidence* to `docs/agent_practices.md`. A stale README is a failed
   change.
7. **Device paths**: if the change touches crawling, LLM transports, checkpoint/resume or the UI, also run
   `-m "integration or live_ollama"` and `-m live_quick` (Chrome + Ollama and one real crawl per platform exist here —
   check port 5000 is free first), then `/smoke-verify`.
8. **Commit** last, with a Chinese type prefix.
9. **Closure gate for any "we are done" claim**: one full run of *every* tier with nothing deselected and nothing
   skipped, in which **no file needed changing**. Any edit restarts the loop.
