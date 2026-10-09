# AGENTS.md

Rules for the AI agent, loaded into **every** session. A *rule* belongs here; *evidence* in `docs/crawler_notes.md`.

**采集端（crawler/platform）规则已拆到 [`docs/crawler_rules.md`](docs/crawler_rules.md)**。
**改爬虫、其列或真站断言前，先读该文件，再读 `docs/crawler_notes.md` 对应平台小节**——那里的规则都真机付过钱。

## Project

采析绘 (crawler_workflow): Flask backend + vanilla-JS frontend that crawls Chinese and overseas social media
(8 platforms; instagram cookie-capture only) via Selenium, cleans and analyzes the text with local Ollama LLMs and
scikit-learn, and renders a drag-and-drop workflow canvas. Single project, no build step.

## Commands

**The venv `.venv/` (Python 3.11) is mandatory — never system Python.** Call `.venv/Scripts/python.exe` / `ruff.exe`
/ `pylint.exe` / `pip.exe` directly (or `source .venv/Scripts/activate`).

- Run: `cd backend && python app.py` → http://localhost:5000 (port via `PORT`). **Run from `backend/`** (the
  `sys.path` root, so imports are top-level like `from config import Config`); never add a `backend.` prefix.
- Lint: `ruff check backend/ tests/` (fast gate, same scope as CI), then `pylint <module>` (deeper); format
  `ruff format backend/ tests/`.
- Deps: *every package code imports directly* goes into `.venv/` **and** `requirements.txt` in the same change, even
  when it also arrives transitively; a new tool's caches go into `.gitignore` in the same change. The
  torch/transformers deps `sentiment`'s `bert` mode probes for go to `requirements-optional.txt` instead — never
  CI-installed, and code needing them may only refuse by name, never fall back to another model.
- **CI** (`.github/workflows/ci.yml`, windows-latest): fast tier + `ruff check`/`ruff format --check` over
  `backend/ tests/`. The local PostToolUse `ruff format` **silently fails on a restricted workspace** (measured
  `os error 5`: ruff writes a temp file then renames) — the edit stays unformatted while the hook looks fine, so run
  `ruff format` by hand before committing; CI is the unskippable gate.
- `backend/test_*.py` are manual probe scripts, NOT pytest — the accepted home for a one-off measurement.
- **`ml_train/`** (gitignored): `scripts/` (training, e.g. `scripts/train_sklearn_ml.py`), `datasets/` (CSVs
  producing the sklearn+bert models the `emotion`/`tendency`/`sentiment` analyzers load), `models/` (deployed HF dirs,
  registered in `data/model_registry.json` by relative path), `logs/`. Changing those analyzers' features or labels
  means retraining here; nothing in `backend/` points at it. See `ml_train/README.md`.
- **Test tiers** (`pytest.ini` excludes the real tiers by default; pinned by `tests/unit/test_test_tiers.py`):
  - Fast (~5.2k cases, ~2 min, no browser/daemon): `.venv/Scripts/python.exe -m pytest -q`.
  - Device (real Chrome on `file://` fixtures + real Ollama; LLM-boundary mocks run by default):
    `... -m "integration or live_ollama"`. **An unavailable browser/daemon SKIPS, so a tier can look green without
    running**
    (measured: a crashing chromedriver left all 99 UI-layout cases skipped under a passing run). When green must be
    evidence, set `CRAWLER_REQUIRE_BROWSER=1` / `CRAWLER_REQUIRE_OLLAMA=1` — the session probes the real thing once
    and FAILS instead of skipping (`tests/integration/conftest.py` owns it).
  - Live (REAL crawls, skip when a cookie is absent): `... -m live_quick` visits each platform once; `... -m
    live_site` is the full acceptance pass. **Never run a live tier unattended: it spends the user's accounts.** A
    copied login is a second device, so the tier keeps its own profile root; only `CIXI_LIVE_USE_USER_PROFILE=1`
    (his consent) crawls as he does. Weibo is asked once per pass. Both split by network (`live_cn`/`live_os`);
    **ask which network he is on**, then run the other.
  - **To run one device/live case, override the marker filter too**: naming the file alone reports `N deselected`.
  - Layout: `tests/unit`, `tests/api` (tmp-isolated `test_client`), `tests/integration` (marked Chrome/Ollama).
    OpenRouter is **never** really called — patch `analyzers.llm_client.requests.post/get`.
  - Frontend JS needs plain `node` on `PATH`; without it those cases skip, so a "nothing skipped" run needs node.

## How tests are written here

- **Isolation happens at conftest import, and the suite fails if `data/` or `logs/` gains a byte.**
  `tests/conftest.py` redirects every write path *before any test module imports* (collection imports all of them
  before fixtures run, and `app.py` captures `Config.COOKIE_DIR` / `history.db` into module-level singletons at its
  own import). `test_test_tiers.py` refuses the import statically; the session-finish snapshot refuses the write.
- **A warning is a test that noticed something and passed anyway — fix what it noticed, never mute it.** `pytest.ini`
  has no `filterwarnings`; adding an `ignore` is not closing one. Fixes landed here: class-scoped fixtures must be
  `@classmethod` (an instance-method fixture's `self` is discarded before tests run, so any `self.` it sets is
  invisible to them); close file responses after reading; never let a cookie-save open a **real Chrome inside the
  fast tier** (the plant swallowed a socket failure, answered 「种入失败」, left a `UserWarning`). A no-browser test
  says so (`profiles_off` in `tests/api/conftest.py`); a dependency leaking its own handle is reported to the user,
  not filtered.
- **A stateful rule needs a stateless suite.** The suite shares ONE cookie directory, so `quiet_jar`
  (`tests/conftest.py`) snapshots and restores it per test — a login another test saved is a precondition this one
  never set up, and "is this cookie here?" passes for the wrong reason when inherited. A test that starts a crawl
  says so via `seeded_logins`; a test *about* the login rule points `Config.COOKIE_DIR` at its own tmp dir, not the
  shared one.
- **Frontend JS is under test too.** `tests/frontend/harness_*.mjs` load the REAL `canvas.js` / `workflow.js` /
  `app.js` into a zero-dependency node `vm` (shared `harness_dom.mjs`), driven by `tests/unit/test_frontend_*`. Any
  JS change to result-affecting logic must sync a scenario there; `urlPlatform` is contract-pinned against
  `utils.helpers.platform_for`.
- **The frontend may not hold a second opinion about a crawl.** `sourceNodeErrors()` in workflow.js asks
  `Capabilities` which fields the selected mode requires; if not loaded, refuse by saying the required fields could
  not be checked — never guess a shape. The form obeys it: a stored value off the option list shows as itself
  (`selectOptionTags`, `boolParam`), never as option #0.
- **A canvas shortcut belongs to the canvas only while the user is not typing:** use `canvas._isTypingTarget()`,
  which asks what the element IS (`isContentEditable`, `.cselect`, …), not a growing tag list (a tag list left out a
  paste box).
- **History entries are snapshots, and identical ones are not entries:** `getState()` deep-copies `params`,
  `_pushState()` skips a state equal to the current one, `restoreState()` brackets itself with `_historySaving` so
  one restore is ONE undo point.
- **The camera is not part of the model:** pan/zoom go in `serializeDraft()` (localStorage) and `settings.view` (the
  file) — NEVER in `getState()`, or every pan is an undo step; `restoreState` leaves the camera alone. A saved x/y of
  0 is a position: `addNode` randomizes only for a non-finite value, never `x || …`.
- **One page boot must not be a single point of failure:** a throw inside the one `DOMContentLoaded` body skips every
  later step. Boot steps go through `boot(name, fn)`; `stats` declines on a missing library and says so.
- **A dialog with an input is answered by the input:** a confirm button carrying its own `value:` replaces whatever
  the user typed in `showDialog`, so leave `value` off input dialogs.
- **Six frontend rules, each costing a feature when forgotten.** (1) `if (window.X)` cannot see a top-level
  `const X` — guard the binding (`typeof X !== 'undefined'`) or export it. (2) The DOM stub's matcher is real
  (`harness_dom.mjs`); never fabricate a child when a query finds nothing. (3) A wrapper must forward its arguments —
  an empty parameter list acts on whatever was selected before, not on what just failed. (4) A name inside
  `onclick="fn('…')"` spans two grammars: `attrJsArg` JS-escapes the literal, *then* HTML-escapes the attribute;
  JS-escaping alone lets one `"` end the attribute. (5) A node captured before an `await` is gone after it —
  settings panels and run-list refreshes rebuild the markup, so re-look it up (`_rowFor`, the holder by id) or the
  write lands in an orphan. (6) **A wrapper installed in another file is not the function your harness loads**:
  `app.js` re-assigns `window.openCookieDialog` (drag/resize) with one parameter while the real function took two, so
  the account argument died *in the browser only* — each cookie harness runs `workflow.js` alone and stayed green.
  Forward the whole list (`(...args)`), and measure a change behind a patched global in the browser tier too, not
  just the single-file harness.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the one the bug
  was about: for a record, a run or a panel row, list the dimensions first and cover the grid.
- **A live case's numbers are computed from the site, never chosen.** An ask, threshold or supply floor the site is
  not obliged to fit reds an honest crawl (and greens one when the cell only fires "if the thread is big enough"):
  derive it from what the crawl reported (the card's 评论数, the page's own count, the board's size) and make the
  assertion two-sided so a thin day still proves something (two D-cells of `test_live_weibo_workflow.py` each cost a
  live re-run for breaking this).
- **A browser-measured assertion must report how much it measured, or it is not an assertion.**
  `tests/integration/test_ui_layout.py` audits containers **by id**, never falls back to `<body>`, reports a
  per-container floor, and resolves on-screen wording from `I18n` in the browser. **State the viewport:** on Windows
  `set_window_size`/`set_window_rect` are silently ignored (a dialog's `calc(100vh - …)` cap is taken once, when it
  first opens), so "fits a 1366×768 laptop" can be measuring a 1920×1080 window wearing another test's cap — emulate
  (`Emulation.setDeviceMetricsOverride`) and assert the size CSS sees with a `100vh` probe, because
  `window.innerHeight` reports the un-emulated one.
- **The `integration` UI tier performs no server writes** — no data-dir switch exists, so a run or upload lands in the
  user's real `data/`/`logs/`. Stub `fetch`.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall` (risk control can
  answer a valid session a login redirect once). An empty that NAMES its refusal (wall or risk) is the site's answer
  — assert the naming; an unnamed empty is real "found nothing" and stays red.

## Run, resume and record invariants

- Runtime state lives in gitignored `data/` (SQLite `runs.db`/`datasets.db`/`history.db`) and `logs/`.
  `data/workflows/` is the ONE versioned exception: a workflow is authored work, not runtime residue — but it
  references uploaded datasets **by id**, so a checked-out workflow is only runnable next to the same `data/`. Do not
  delete `data/` casually.
- **A step's output column names are a chart's input contract.** 主题距离图 reads `pc1/pc2/topic/prevalence_pct` and
  显著词图 reads `term/overall_freq/within_freq` because the steps that write them use exactly those names; both
  charts take the names as parameters with those defaults and refuse a missing column, so a rename on one side is a
  named refusal on the other rather than an empty figure.
- **One server per data root, by design (local single-user tool).** `RunStore.__init__` calls `promote_stale_runs()`,
  which marks every run still `running` as interrupted, so a second instance on the same `data/` kills the first
  one's live run. `CRAWLER_DATA_ROOT` (config.py) gives a process its own `data/`+`logs/` — the `/smoke-verify` boot
  and the UI tier's self-booted server use it. Without it, **ask before booting a second server, and never kill a
  process on 5000.**
- **One run at a time; a busy server queues instead of refusing.** `_begin_run()` (app.py) owns the whole start path
  (claim, validations, `execution_state`, worker thread), so the queue drains by calling *that* function, never a
  weaker second one. `/api/workflow/execute` with `queue:false` keeps the 400 for callers that must fail fast (the
  resume banner). The hand-off is in the worker's `finally` and clears `execution_state['thread']` **first** — the
  claim also checks thread liveness, so an unwinding thread would queue the next request behind itself forever.
  Queues are in-memory and `tests/conftest.py` clears `_RUN_QUEUE` per test. The Execute button is never disabled; it
  relabels 排队运行.
- **A test that calls an executor function directly must leave the app quiet**: `clean_globals` (tests/conftest.py)
  resets the console and *fails* a test that leaks `execution_state['running']`, because nothing else clears either
  without the run start / the `client` fixture.
- **Checkpointing is the core value** (`services/run_store.py`): per-node outputs and LLM answers persist so an
  interrupted run resumes rather than re-crawls or re-pays; keep `runs.db` state compatible. Three measured rules,
  each pinned by a test: the streaming row sink writes **one transaction per row** on purpose; the next free slot is
  `MAX(seq)+1`, **never `COUNT(*)`**; a **cursor records position, not content** — collected ids come from the seeded
  rows (`Crawler.seed`), so an id list must not go back into `mark_position`.
- **A label is not an input.** A node's fingerprint feeds its children and the dedupe ledger's scope (`'item:' +
  node_fingerprint`), so a *name* inside one invalidates a whole chain and moves the other. `_VOLATILE_PARAMS`
  (labels + switches like `recrawl`/`enabled`) answers "does this parameter choose data, or just describe the
  record?" — ids stay in, labels and switches out.
- **A disabled node is not on the canvas.** `engine.workflow.effective_workflow` drops it (`enabled` off, type off,
  or all upstream gone — cascades down; fan-in survives on one live input); validate/naming/fingerprint/execution run
  on that graph, so disabling a workflow is disabling its head node.
- **Reuse has four rules.** `done` AND `restored` are reusable; a stored result with **zero rows** is never reused (an
  empty parent may deliver this time); the source node is never adopted (it resumes by cursor); and `begin_node`
  reporting `dropped_stale` cancels reuse, because those rows were deleted.
- **Startup recovery shares the end-of-run settlement.** A node leaves `running` only through `finish_node`, which a
  kill skips, so `node_runs.row_count` still holds the 0 `begin_node` wrote. `promote_stale_runs` must call
  `settle_nodes` (status *and* count from the rows): the panel's 已存行数 and the 续跑 node's "adopt the fullest node"
  both read that column.
- **One definition of "completed".** `runs.node_done` and the console's `completed_nodes` must agree:
  skipped/failed/partial are not done, `restored` is. The finish line's counts are taken **after** settling and only
  over `attempted_nodes` (the record also keeps nodes the canvas deleted), and a node 停止 cut short is counted in its
  own `stopped_node_ids` bucket — reporting the user's button press as 「1 个失败」 is.
- **A resumed run re-describes itself.** `start_run`'s conflict update refreshes
  `workflow_name`/`workflow_fingerprint`/`mode`/`headless`/`lang` (not `started_at`): left at their first-attempt
  values the 并行/串行 and 无头/窗口 chips describe a run that never happened, and the stale name — the key every
  preview/chart/export probe uses — makes the kept rows unfindable.
- **A phase column's order is not data, and a records round trip erases it.** `bin_time` writes an ORDERED
  categorical (`pd.cut`), but every node boundary rebuilds the table with `pd.DataFrame(current_input)` (app.py),
  leaving plain strings whose code-point order puts 二次爆发期 before 发酵期. Anything grouping BY phase — 分阶段 LDA,
  the `TopicⅠ-1 … TopicⅤ-4` numbering, 主题生命周期, 主题流向, 表 2 的情感演化曲线, 分组聚合 — takes the order from the
  categorical while it still has one, otherwise from a column the user names (a NUMBER like `stage_order` / `阶段序号`,
  or a TIME), and otherwise REFUSES. Sorting the names is how a replicated 表 1 gets renumbered while still looking
  complete — so a step emitting a phase table must also emit its position column, the only thing surviving the
  boundary.
- **A quoted row count is only true of the merge order that produced it.** 近重复去重（SimHash）keeps whichever row of
  a group arrived first, so the same six files merged in canvas order give 3778/4366/4993/4526/623 rows per phase and
  in filename order give 3620/4454/5032/4555/625 — and every 事件标注 volume with them. Any number in a saved canvas,
  README or report must be measured through the canvas's OWN upstream order (walk `connections` into the merge node,
  don't glob the folder), and a re-measurement that disagrees is a clue the order changed, not that the data did.
- **A coherence sweep is not a decision, and only the canvas's own sweep may be quoted.** 主题数扫描 draws 2000
  documents by default and the draw follows the table's row order, so its argmax moved between merge orders
  (8,5,6,7,3 ↔ 2,7,3,4,2). Run per phase over every row it answers 5,6,2,6,2 — but 波动期's coherence spans 0.227–0.337
  across 2..8 and 发酵期's 5..8 sit within 0.004, so the argmax is noise with a number on it. Two rules: (1) the scan
  node justifying a canvas's `stage_topic_counts` must run `coherence_max_documents=0` and be fed by that canvas's own
  phase filters, or the tool and the number it defends measure different tables; (2) where the sweep is flat, state the
  rule: this canvas takes the highest coherence at **≥3 topics** (a 2-topic phase cannot show a lifecycle), and the
  node title says so — an unseen floor is judgement dressed as measurement.
- **A score is a function of the column it was read from, so the column name belongs to the number.** The same 18286
  rows scored on `正文` give 0.211/0.200/0.217/0.228/0.238 per phase, and on `cleaned_text` give
  0.164/0.170/0.173/0.199/0.200 — same shape, ~0.04 apart, because a repost chain carries the insult verbatim while
  the cleaner strips it. A curve quoted without its column cannot be audited later.
- **An unused LDA topic is the model's answer, not the user's mistake.** An argmax can leave a topic with zero
  documents; the stage's other topics are still real output, so `topic_by_stage` fills that row from the topic's own
  word distribution, files `doc_n = 0`, and logs one named warning. Killing the run, or printing an empty 特征词 cell,
  would each destroy information the model has.
- **A recall device must not be allowed to look like a classifier.** `aggression`'s word-list mode states in its
  docstring, panel hint and console line that a miss is unmeasurable, keeps the lists in code so their
  incompleteness is reviewable, and deliberately does NOT count 辟谣-style accusations as violent. An all-`none` column
  must come from a real reading of the text, never a mistyped column: that is why a missing text column raises
  instead of returning blanks.
- **The analysis node's one non-deterministic step borrows the process node's client.** `topic_label` asks the model
  once per topic row. `run_pipeline(df, steps, llm=, cancel=)` hands those to the ops in `LLM_OPS` *only*, never
  through `params`: the run report echoes every step's `params` into the console and the durable record, so a client
  in there would be a live object written into a ledger. No model configured is refused BEFORE the first call is paid
  for, and a Stop leaves `未处理` in the rows the model never saw — which is how the executor settles that node PARTIAL
  instead of DONE.
- **Retention must release what it destroyed.** `purge` deletes a run's rows, so it also calls `forget_run_items` —
  an `item_seen` entry whose rows are gone would make a later crawl under-collect silently, with no way back except
  「重新采集」. An explicit `delete_run` still *keeps* claims: there the user removed a record knowing the crawl was
  paid for.
- **`' + '` is a composed lookup key, not a permission.** `_durable_node_rows` tries the exact name the browser sends
  first and widens to its pieces only on a miss, or a canvas genuinely called `节奏` can be handed the table of someone
  else's `节奏 + BPM`.
- **A node id is a storage key — never re-mint one on restore.** Run records, resume cursors, LLM caches and
  `workflow_fingerprint` all key on node ids, so renumbering detaches a canvas from its own interrupted run.
  `canvas.addNode(type, x, y, nodeId)` adopts the stored id and `reserveId` keeps `nextId` past it (a later drag must
  not collide); both restore paths (`canvas.restoreState`, `WorkflowManager.loadFromJSON`) pass file ids straight
  through — pinned by `harness_state.mjs`. That id is also the box's **DOM** id, so `getElementById(<node id>)` lets a
  workflow file address chrome the node does not own: reach node elements through `canvas._nodeEl(id)` (reading
  `nodes[id].el`), and `test_frontend_state_js.py` fails any variable-argument `getElementById` in canvas.js.
- **Recorded rows are addressed by workflow, never by bare node id.** `_durable_node_rows` (app.py) answers a
  preview/chart/export/studio probe after a refresh from `runs.db`; ids like `node-2` repeat on every canvas, so with
  no identity it returns nothing rather than guessing. The browser sends `workflow_name` from `workflow.runName()`,
  mirroring the backend precedence: name-node label, then saved file name.
- **Parallel is one record; serial is one record per workflow that started.** Parallel runs the workflows together, so
  one row joins their labels with `' + '` in canvas order; that string is also a **lookup key** (old rows stay
  inspectable, pinned by `TestRowLookupStillWorks`). Serial runs take turns, so each workflow opens its own row **as
  it is reached** and an unreached one leaves none. Every row keeps the **canvas** fingerprint (what the resume banner
  and `/api/runs/resumable` match on), and the id the HTTP response returns is workflow zero's row (the browser polls
  and resumes by it); 继续 adopts each workflow's own row by name. **A chip must describe what happened, not what the
  canvas held:** `并行 ×N` only when `mode == 'parallel'`, and a serial row says `串行 ×1` because that row *is* one
  workflow. Resume state stays **per workflow** (`fingerprints_for_workflow`), so a failure in B restores A.

## Console, messages and i18n

- UI text supports zh/en via the `backend/i18n.py` catalog — add every new user-facing string there (both languages),
  and the same for `backend/static/js/app.js` catalogs.
- **A missing `t()` keyword is a printed bug, not a crash — so the suite checks call sites.** `t()` deliberately
  returns the *raw template* when a parameter is missing (never abort a crawl for a sentence), so a forgotten
  `{reads}` prints `阅读={reads}` once per article. Key parity, reachability and zh/en matching are all blind to it;
  `test_i18n.py::TestCallSitePlaceholders` walks every `t('literal', …)` in `backend/` with `ast` and refuses the
  mismatch.
- **A `{platform}` slot is answered with a word, not the key.** `zhihu` keys the matrix and the cookie file; `i18n`
  localizes it, splitting on `,`/`、` only; `test_frontend_contract.py` (`TestChromeOfThePageItself`) keeps the two
  lists equal.
- Console/validation messages reference nodes through `engine.workflow.node_label(node, nid)` (→ `title #nid`), never
  a bare `nid`, so a renamed node speaks with the user's name. Store keys, the results dict and resume plumbing still
  use the raw `nid`. The frontend keeps `node.title` in `getState`/`toWorkflowJSON`, and BOTH restore paths re-apply
  title + element text BEFORE `updateNodeDisplay`, whose re-stamp guard reads the element.
- **The run console keeps its own history per view, because the server cannot give it back** (it ships only the last
  200 lines of the *whole* run). `consoleViews` in workflow.js holds `{seen, lines}` per view (`'all'` plus each
  workflow id), **every** view is fed on every poll, and `switchWfTab` repaints from that view's history without
  moving its cursor.
- **Every thread that logs must pin its own language.** `set_lang` is thread-local and a daemon thread starts fresh, so
  `run()`, the parallel pool wrapper and **both cookie workers** take the request's language and set it first,
  because a daemon thread that does not is Chinese in an English interface. A test asserting console text should
  assert on the reason, not a pasted sentence, or send both languages.
- **One failure, one line.** `LogBufferHandler` forwards every `logger.*` call into the console buffer (its `format`
  is the message alone, so a traceback still goes only to the log file), so `logger.exception(...)` **and** an
  `add_log` of the same text print the sentence twice. Keep the logger call for the file's traceback, and let the
  executor's `wf.node_failed` be the single attributed console line; a helper line may add a fact that line cannot
  carry (how many rows survived), never repeat the reason. Refusals `raise` rather than returning `[]`, or the node
  settles DONE over an empty table. **Anything that chooses data, cost or a name is refused BY NAME, never guessed**:
  a mode, a `select`, a step's select or missing column (`data_analysis.validate_step`), an analyzer's
  `method`/`mode` (`app.enum_param`). **Read a switch, never compare it**: `utils.helpers.as_bool`; blank = the
  declared default. A form shows a stored value off the list (`selectOptionTags`), never option #0.
- **`_push_log` stores one entry per physical line** — the total advances by lines, not by `add_log` calls (a
  multi-line driver `Message:` block rendered as several rows and the browser's cursor skipped or repeated content).
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook.** Those nodes get no
  "Executing node …" or "Node … completed (n/N)" line, and progress counters still count them. Everything stating a
  fact still prints: the upload's own "Loaded … N rows", and any failure/skip/restore line — with `node_label`, or a
  silenced node that fails is undiagnosable.
- Run-gating UX lives in `workflow.js execute()` → `_cookieGateBeforeRun`: `cookie_preflight_before_run` probes each
  canvas platform **whose mode needs a session** (`Mode.needs_session`; weibo's 热搜 answers anonymously, wechat has no
  session to want — not a cookie platform at all) and a login wall **refuses it** (no "run anyway"); 「无法核对」 —
  timeout, captcha, busy profile — never blocks, because no answer is not evidence of a dead cookie. Off asks and
  blocks nothing; a resume or a crawl-free canvas skips the probe, and a cookie write drops the cached verdict.
  **`execute()` asks no cookie question of its own** — its 2026-09 shape was a `/api/cookies/status` loop that refused
  on each platform's *default-account* boolean, so it blocked a node on a saved named account and blocked wechat
  entirely (that map holds no key for a platform with no cookie row). **A named cookie and a named profile belong
  together**: one account = one `data/cookies/<platform>@<account>.json` *and* one `chrome_profile/<platform>/<account>`
  (own device, own rotated session, own concurrency lane), so nothing answering "does this crawl have a login" may
  drop the account. **A node's 账号 is a session question, asked once**: `engine.workflow._account_session_errors`
  refuses a crawl that `Mode.needs_session` says needs a login when `cookie_preflight.has_session_to_test` finds
  neither that account's cookie file *nor* a profile still carrying it — blank included, because blank IS an account
  (默认账号), not a wildcard. **Every account has one name and one spelling**: the default login is named `default`
  (the box shows it, never a blank; the blank is only its old filename), folded at the ONE point
  `CookieManager.key`/`path_segment` (`''` ⇄ `default`, lowercase always) — `Work` and `work` are the same session,
  because a case-insensitive filesystem cannot hold two logins under one spelling — so `browser_profiles`, the
  preflight cache and the JS box all route through that fold. `unoffered_selections` must not answer it either (one
  failure, one line). Letting it through is not a harmless crawl — it walks into a login wall, files an empty table and
  reports 完成. The candidate list and a new node's preselection are both `CookieManager.accounts_in_order`, so the
  first row listed is the account a node starts on. **A new settings key needs all four:** the bool branch in
  `settings_store.save_settings`, both app.js catalogs, and the `AppSettings` wiring.

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
   tests. The suite must prove the new thing is right *and* nothing old broke. A previously-green test failing
   because of your change means the bug is in the change — fix the code, not the test (exception: it pinned an old bug
   that is now genuinely fixed).
3. **Fast suite green**: `.venv/Scripts/python.exe -m pytest -q`. Fix a genuine product bug in product code; if it
   can't land now, pin it with `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — ...')` and report
   it.
4. **Lint green** on every committed file: `ruff check <files>` and `ruff format --check <files>`.
5. **New packages**: install into `.venv/` AND declare in `requirements.txt` in the same change, with caches in
   `.gitignore`.
6. **Docs stay true**: update `README.md` in the same change whenever user-visible behavior changed (features, node
   types, API tables, config, structure, quickstart). Move crawler measurements to `docs/crawler_notes.md`, and any
   new crawl-side rule to `docs/crawler_rules.md`. A stale README is a failed change.
7. **Device paths**: if the change touches crawling, LLM transports, checkpoint/resume or the UI, also run
   `-m "integration or live_ollama"` and `-m live_quick` (Chrome + Ollama and one real crawl per platform exist
   here — check port 5000 is free first), then `/smoke-verify`.
8. **Commit** last, with a Chinese type prefix.
9. **Closure gate for any "we are done" claim**: one full run of *every* tier with nothing deselected and nothing
   skipped, in which **no file needed changing**. Any edit restarts the loop.
