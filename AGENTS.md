# AGENTS.md

Rules for the AI agent in this repository. Loaded into **every** session, so it is a rule list: a *rule* belongs
here, *evidence* belongs in `docs/crawler_notes.md`.

**采集端（crawler/platform）的两段规则已拆到 [`docs/crawler_rules.md`](docs/crawler_rules.md)** ——
"Crawler architecture" 与 "Platform red lines"。**改任何爬虫、它的列、或真站断言之前，必须先读那个文件，
再读 `docs/crawler_notes.md` 对应平台小节**；那里的每条规则都是真机付过钱的。本文件只留每次编辑都要用的规则。

## Project

采析绘 (crawler_workflow): Flask backend + vanilla-JS frontend that crawls Chinese and overseas social media
(8 platforms; instagram is cookie-capture only) via Selenium, cleans and analyzes the text with local Ollama LLMs
and scikit-learn, and renders a drag-and-drop workflow canvas. Single project, no build step.

## Commands

**The project venv `.venv/` (Python 3.11) is mandatory — never system Python.** Call
`.venv/Scripts/python.exe` / `ruff.exe` / `pylint.exe` / `pip.exe` directly (or `source
.venv/Scripts/activate`).

- Run: `cd backend && python app.py` → http://localhost:5000 (port via `PORT`). **Must run from `backend/`** — it
  is the `sys.path` root, so imports are top-level (`from config import Config`); never add a `backend.` prefix.
- Lint: `ruff check backend/` (fast gate) then `pylint <module>` (deeper); format `ruff format backend/`.
- Deps: *every package imported directly by code* is installed into `.venv/` **and** declared in
  `requirements.txt` in the same change — even when it also arrives transitively. A new tool's caches go into
  `.gitignore` in the same change that adds the tool.
- `backend/test_*.py` are manual probe scripts, NOT pytest — the accepted place for a one-off measurement.
- **Test tiers** (`pytest.ini` excludes the real tiers by default; pinned by `tests/unit/test_test_tiers.py`):
  - Fast (~4.3k cases, ~2 min, no browser/daemon): `.venv/Scripts/python.exe -m pytest -q`.
  - Device (real Chrome on `file://` fixtures + real Ollama; LLM boundary mocks run by default):
    `... -m "integration or live_ollama"`.
  - Live (REAL crawls, skip when a cookie is absent): `... -m live_quick` visits each platform once and gates a
    change; `... -m live_site` is the full acceptance pass. **Never run a live tier unattended: it spends the
    user's accounts.** A copied login is a second device, so the tier keeps its own profile root; only
    `CIXI_LIVE_USE_USER_PROFILE=1` (his consent, exempting that subtree from the isolation guard) crawls as he
    does. Weibo is asked once per pass. Both split by network (`live_cn`, `live_os`); **ask which network he is
    on**, then run the other.
  - **To run one device/live case, override the marker filter too**: naming the file alone reports
    `N deselected` and looks like it ran.
  - Layout: `tests/unit`, `tests/api` (tmp-isolated `test_client`), `tests/integration` (marked Chrome/Ollama).
    OpenRouter is **never** really called — patch `analyzers.llm_client.requests.post/get`.
  - Frontend JS needs plain `node` on `PATH`; without it those cases skip, so a "nothing skipped" closure run
    requires node.

## How tests are written here

- **Isolation happens at conftest import, and the suite fails if `data/` or `logs/` gains a byte.**
  `tests/conftest.py` redirects every write path *before any test module is imported* (collection imports them all
  before fixtures run, and `app.py` captures `Config.COOKIE_DIR` / `history.db` into module-level singletons at its
  own import). `test_test_tiers.py` refuses the import statically; the session-finish snapshot refuses the write
  dynamically.
- **A warning is a test that noticed something and passed anyway, so the thing it noticed gets
  fixed — never muted.** `pytest.ini` has no `filterwarnings` section at all, and adding an
  `ignore` line is not how a warning is closed here. What fixing looks like, from the set this
  suite actually had: four class-scoped fixtures written as instance methods (the instance they
  fill is discarded before the first test runs, so any `self.` they set is invisible to the tests
  that asked for them — `@classmethod` is the documented shape), file responses read without
  closing them, and seven cookie saves that opened a **real Chrome inside the fast tier** because
  saving plants the session into that account's profile — the plant swallowed the socket failure,
  answered 「种入失败」 and left one `UserWarning` as the only trace. A test that wants no browser
  says so (`profiles_off` in `tests/api/conftest.py`); a test that reads a file response closes it.
  Something unfixable from inside this repo (a dependency leaking its own handle) is reported to
  the user, not filtered.
- **A stateful rule needs a stateless suite.** The suite shares ONE cookie directory, so `quiet_jar`
  (`tests/conftest.py`) snapshots it per test and puts it back — a login another test saved is a precondition this
  test never set up, and "is this account's cookie here?" is exactly the kind of question that passes for the wrong
  reason when the answer is inherited. A test that starts a crawl says so with `seeded_logins`; a test *about* the
  login rule points `Config.COOKIE_DIR` at its own tmp dir instead of trusting the shared one.
- **Frontend JS is under test too.** `tests/frontend/harness_*.mjs` load the REAL `canvas.js` / `workflow.js` /
  `app.js` into a zero-dependency node `vm` (shared `harness_dom.mjs`), driven by `tests/unit/test_frontend_*`. Any
  JS change to result-affecting logic must sync a scenario there; `urlPlatform` is contract-pinned against
  `utils.helpers.platform_for`.
- **The frontend may not hold a second opinion about a crawl.** `sourceNodeErrors()` in workflow.js asks
  `Capabilities` which fields the selected mode requires; if it has not loaded, refuse by saying the required fields
  could not be checked — never guess a shape. The form obeys it too: a stored value off the option list shows as
  itself (`selectOptionTags`, `boolParam`), never as option #0.
- **A canvas shortcut belongs to the canvas only while the user is not typing:** use
  `canvas._isTypingTarget()`, which asks what the element IS (`isContentEditable`, `.cselect`, …), not a growing tag
  list (a tag list is how a paste box was left out).
- **History entries are snapshots, and identical ones are not entries:** `getState()` deep-copies `params`,
  `_pushState()` skips a state equal to the current one, `restoreState()` brackets itself with `_historySaving` so
  one restore is ONE undo point.
- **The camera is not part of the model:** pan/zoom go in `serializeDraft()` (localStorage) and `settings.view` (the
  file) — NEVER in `getState()`, or every pan is an undo step; `restoreState` leaves the camera alone. A saved x/y of
  0 is a position: `addNode` randomizes only for a non-finite value, never `x || …` (that scatters a 0-coordinate node).
- **One page boot must not be a single point of failure:** one `DOMContentLoaded` body, so a throw inside it skips
  every later step. Boot steps go through `boot(name, fn)`; `stats` declines on a missing library and says so.
- **A dialog with an input is answered by the input:** a confirm button carrying its own `value:` replaces whatever
  the user typed in `showDialog`, so leave `value` off input dialogs.
- **Five frontend rules that each cost a feature when forgotten.** (1) `if (window.X)` cannot see a top-level
  `const X` — guard the binding (`typeof X !== 'undefined'`) or export it. (2) The DOM stub's matcher is real
  (`harness_dom.mjs`); never fabricate a child when a query finds nothing. (3) A wrapper must forward its arguments
  — an empty parameter list acts on whatever was selected before, not on what just failed. (4) A name inside
  `onclick="fn('…')"` spans two grammars: `attrJsArg` JS-escapes the literal, *then* HTML-escapes the attribute;
  JS-escaping alone lets one `"` end the attribute. (5) A node captured before an `await` is not on the page after
  it — settings panels and run-list refreshes rebuild the markup, so re-look the element up (`_rowFor`, the holder
  by id) or the write lands in an orphan.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the one the bug
  was about: for a record, a run or a panel row, list the dimensions first and cover the grid.
- **A live case's numbers are computed from the site, never chosen.** An ask, a selection threshold or a supply
  floor the site is not obliged to fit reds an honest crawl (and greens one when the cell only fires "if the thread
  is big enough"): derive it from what the crawl reported — the card's 评论数, the page's own count, the board's
  size — and make the assertion two-sided so a thin day still proves something. Two D-cells of
  `tests/live_site/test_live_weibo_workflow.py` each cost a live re-run for breaking this.
- **A browser-measured assertion must report how much it measured, or it is not an assertion.**
  `tests/integration/test_ui_layout.py` audits containers **by id**, never falls back to `<body>`, reports a
  per-container floor, and resolves on-screen wording from `I18n` in the browser. **State the viewport too:** on
  Windows `set_window_size`/`set_window_rect` are silently ignored (a dialog's `calc(100vh - …)` cap is taken once,
  when it first opens), so "fits a 1366×768 laptop" can be measuring a 1920×1080 window wearing another test's cap —
  emulate (`Emulation.setDeviceMetricsOverride`) and assert the size CSS sees with a `100vh` probe, because
  `window.innerHeight` reports the un-emulated one.
- **The `integration` UI tier performs no server writes** — no data-dir switch exists, so a run or upload lands in
  the user's real `data/` and `logs/`. Stub `fetch`.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall` (risk control can
  answer a valid session a login redirect once). An empty that NAMES its refusal (wall or risk) is the site's answer
  — assert the naming; an unnamed empty is real "found nothing" and stays red.

## Run, resume and record invariants

- Runtime state lives in gitignored `data/` (SQLite `runs.db` / `datasets.db` / `history.db`) and `logs/`. Do not
  delete `data/` casually — saved workflows reference uploaded datasets stored there.
- **One server per data root, by design (local single-user tool).** `RunStore.__init__` calls
  `promote_stale_runs()`, which marks every run still `running` as interrupted, so a second instance on the same
  `data/` kills the first one's live run. `CRAWLER_DATA_ROOT` (config.py) gives a process its own `data/` + `logs/` —
  the `/smoke-verify` boot and the UI tier's self-booted server both use it. Without it, **ask before booting a
  second server, and never kill a process on 5000.**
- **One run at a time; a busy server queues instead of refusing.** `_begin_run()` (app.py) owns the whole start path
  (claim, validations, `execution_state`, worker thread), so the queue drains by calling *that* function, never a
  second weaker one. `/api/workflow/execute` with `queue:false` keeps the 400 for callers that must fail fast (the
  resume banner). The hand-off is in the worker's `finally` and clears `execution_state['thread']` **first** — the
  claim also checks thread liveness, so a still-alive unwinding thread would queue the next request behind itself
  forever. Queues are in-memory and `tests/conftest.py` clears `_RUN_QUEUE` per test. The Execute button is therefore
  never disabled; it relabels 排队运行.
- **A test that calls an executor function directly must leave the app quiet**: `clean_globals` (tests/conftest.py)
  resets the console and *fails* a test that leaks `execution_state['running']`, because nothing else clears either
  without the run start / the `client` fixture.
- **Checkpointing is the core value** (`services/run_store.py`): per-node outputs and LLM answers persist so an
  interrupted run resumes rather than re-crawls or re-pays. Keep `runs.db` state compatible. Three measured rules,
  each pinned by a test: the streaming row sink writes **one transaction per row** on purpose; the next free slot is
  `MAX(seq)+1`, **never `COUNT(*)`**; a **cursor records position, not content** — collected ids come from the seeded
  rows (`Crawler.seed`), so an id list must not go back into `mark_position`.
- **A label is not an input.** A node's fingerprint feeds its children and the dedupe ledger's scope
  (`'item:' + node_fingerprint`), so a *name* inside one invalidates a whole chain and moves the other.
  `_VOLATILE_PARAMS` (labels + switches like `recrawl`/`enabled`) is the answer to "does this parameter choose data,
  or just describe the record?" — ids stay in, labels and switches out.
- **A disabled node is not on the canvas.** `engine.workflow.effective_workflow` drops it (`enabled` off, type off, or
  all upstream gone — cascades down; fan-in survives on one live input); validate/naming/fingerprint/execution run on
  that graph, so disabling a workflow is disabling its head node.
- **Reuse has four rules that are each easy to break.** `done` AND `restored` are reusable; a stored result with
  **zero rows** is never reused (an empty parent may deliver this time); the source node is never adopted (it resumes
  by cursor); and `begin_node` reporting `dropped_stale` cancels reuse, because those rows were deleted.
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
- **Retention must release what it destroyed.** `purge` deletes a run's rows, so it also calls `forget_run_items` — an
  `item_seen` entry whose rows are gone would make a later crawl under-collect silently, with no way back except
  「重新采集」. An explicit `delete_run` still *keeps* claims: there the user removed a record knowing the crawl was
  paid for.
- **`' + '` is a composed lookup key, not a permission.** `_durable_node_rows` tries the exact name the browser sends
  first and widens to its pieces only on a miss, or a canvas genuinely called `节奏` can be handed the table of someone
  else's `节奏 + BPM`.
- **A node id is a storage key — never re-mint one on restore.** Run records, resume cursors, LLM caches and
  `workflow_fingerprint` all key on node ids, so renumbering detaches a canvas from its own interrupted run.
  `canvas.addNode(type, x, y, nodeId)` adopts the stored id and `reserveId` keeps `nextId` past it (a later drag must
  not collide); both restore paths (`canvas.restoreState`, `WorkflowManager.loadFromJSON`) pass file ids straight
  through — pinned by `harness_state.mjs`. That same id is the box's **DOM** id, so `getElementById(<node id>)` lets a
  workflow file address chrome the node does not own: node elements are reached through `canvas._nodeEl(id)` (reading
  `nodes[id].el`), and `test_frontend_state_js.py` fails any variable-argument `getElementById` in canvas.js.
- **Recorded rows are addressed by workflow, never by bare node id.** `_durable_node_rows` (app.py) answers a
  preview/chart/export/studio probe after a refresh from `runs.db`; ids like `node-2` repeat on every canvas, so with
  no identity it returns nothing rather than guessing. The browser sends `workflow_name` from `workflow.runName()`,
  which mirrors the backend precedence: name-node label, then saved file name.
- **Parallel is one record; serial is one record per workflow that started.** Parallel runs the workflows together, so
  one row joins their labels with `' + '` in canvas order; that string is also a **lookup key** (old rows stay
  inspectable, pinned by `TestRowLookupStillWorks`). Serial runs take turns, so each workflow opens its own row **as it
  is reached** and an unreached one leaves none. Every row keeps the **canvas** fingerprint (what the resume banner and
  `/api/runs/resumable` match on), and the id the HTTP response returns is workflow zero's row (the browser polls and
  resumes by it); 继续 adopts each workflow's own row by name. **A chip must describe what happened, not what the
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
  localizes it, splitting on `,`/`、` only; `TestPlatformLabelParity` keeps the two lists equal.
- Console/validation messages reference nodes through `engine.workflow.node_label(node, nid)` (→ `title #nid`), never
  a bare `nid`, so a renamed node speaks with the user's name. Store keys, the results dict and resume plumbing still
  use the raw `nid`. The frontend keeps `node.title` in `getState` / `toWorkflowJSON`, and BOTH restore paths re-apply
  title + element text BEFORE `updateNodeDisplay`, whose re-stamp guard reads the element.
- **The run console keeps its own history per view, because the server cannot give it back** (it ships only the last
  200 lines of the *whole* run). `consoleViews` in workflow.js holds `{seen, lines}` per view (`'all'` plus each
  workflow id), **every** view is fed on every poll, and `switchWfTab` repaints from that view's history without
  moving its cursor.
- **Every thread that logs must pin its own language.** `set_lang` is thread-local and a daemon thread starts with a
  fresh one, so `run()`, the parallel pool wrapper and **both cookie workers** take the request's language and set it
  first, because a daemon thread that does not is Chinese in an English interface. A test asserting console text
  should assert on the reason, not on a pasted sentence, or send both languages.
- **One failure, one line.** `LogBufferHandler` forwards every `logger.*` call into the console buffer (its `format`
  is the message alone, so a traceback still goes only to the log file), so `logger.exception(...)` **and** an
  `add_log` of the same text prints the sentence twice. Keep the logger call for the file's traceback, and let the
  executor's `wf.node_failed` be the single attributed console line; a helper line may add a fact that line cannot
  carry (how many rows survived), never repeat the reason. Refusals `raise` rather than returning `[]`, or the node
  settles DONE over an empty table. **Anything that chooses data, cost or a name is refused BY NAME, never
  guessed**: a mode, a `select`, a step's select or missing column (`data_analysis.validate_step`), an analyzer's
  `method`/`mode` (`app.enum_param`). **Read a switch, never compare it**: `utils.helpers.as_bool`; blank = the
  declared default. A form shows a stored value off the list (`selectOptionTags`), never option #0.
- **`_push_log` stores one entry per physical line** — the total advances by lines, not by `add_log` calls (a
  multi-line driver `Message:` block rendered as several rows and the browser's cursor skipped or repeated content).
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook.** Those nodes get no
  "Executing node …" or "Node … completed (n/N)" line, and progress counters still count them. Everything that states
  a fact still prints: the upload's own "Loaded … N rows", and any failure/skip/restore line — with `node_label`, or a
  silenced node that fails is undiagnosable.
- Run-gating UX lives in `workflow.js execute()` → `_cookieGateBeforeRun`: `cookie_preflight_before_run` probes each
  canvas platform **whose mode needs a session** (`Mode.needs_session`; weibo's 热搜 answers anonymously, wechat has no
  session to want — it is not a cookie platform at all) and a login
  wall **refuses it** (no "run anyway"); 「无法核对」 — timeout, captcha, busy profile — never blocks, because no answer
  is not evidence of a dead cookie. Off asks and blocks nothing; a resume or a crawl-free canvas skips the probe, and a
  cookie write drops the cached verdict. **`execute()` asks no cookie question of its own** — the shape this had in
  2026-09 was a `/api/cookies/status` loop inside it that refused on each platform's *default-account* boolean: it
  blocked a node on a saved named account, and blocked wechat entirely because that map holds no key for a platform
  with no cookie row. **A named cookie and a named profile belong together**: one account = one
  `data/cookies/<platform>@<account>.json` *and* one `chrome_profile/<platform>/<account>` (own device, own rotated
  session, own concurrency lane), so nothing that answers "does this crawl have a login" may drop the account.
  **A node's 账号 is a session question, and it is asked once**: `engine.workflow._account_session_errors` refuses a
  crawl that `Mode.needs_session` says needs a login when `cookie_preflight.has_session_to_test` cannot find that
  account's cookie file *or* a profile still carrying it — blank included, because blank IS an account (默认账号), not
  a wildcard. `unoffered_selections` must not answer it too: one failure, one line. Letting it through is not a
  harmless crawl — it walks into a login wall, files an empty table and reports 完成. The candidate list and the
  preselection a new node gets are both `CookieManager.accounts_in_order`, so the first row listed is the account a
  node starts on. **A new settings key needs all four:** the bool branch in
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
   tests. The suite must prove the new thing is right *and* nothing old broke. A previously-green test failing because
   of your change means the bug is in the change — fix the code, not the test (exception: it pinned an old bug that is
   now genuinely fixed).
3. **Fast suite green**: `.venv/Scripts/python.exe -m pytest -q`. A genuine product bug found by a test is fixed in
   product code; if it cannot land now, pin it with
   `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — ...')` and report it.
4. **Lint green** on every file committed: `ruff check <files>` and `ruff format --check <files>`.
5. **New packages**: installed into `.venv/` AND declared in `requirements.txt` in the same change, with caches in
   `.gitignore`.
6. **Docs stay true**: update `README.md` in the same change whenever user-visible behavior changed (features, node
   types, API tables, config, structure, quickstart). Move crawler measurements to `docs/crawler_notes.md`, and any
   new crawl-side rule to `docs/crawler_rules.md`. A stale README is a failed change.
7. **Device paths**: if the change touches crawling, LLM transports, checkpoint/resume or the UI, also run
   `-m "integration or live_ollama"` and `-m live_quick` (Chrome + Ollama and one real crawl per platform exist on this
   machine — check port 5000 is free first), then `/smoke-verify`.
8. **Commit** last, with a Chinese type prefix.
9. **Closure gate for any "we are done" claim**: one full run of *every* tier with nothing deselected and nothing
   skipped, in which **no file needed changing**. Any edit restarts the loop.
