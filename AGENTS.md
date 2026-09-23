# AGENTS.md

Guidance for the AI agent in this repository. This file is loaded into **every** session, so it stays
short on purpose: a *rule* belongs here, the *evidence* for it belongs in `docs/crawler_notes.md`.
When you are about to change a crawler, its columns, or a live-site assertion, read that file's
section for the platform first — every such rule came from a measurement whose re-payment costs
minutes of real crawling.

## Project

采析绘 (crawler_workflow): Flask backend + vanilla-JS frontend that crawls Chinese and overseas social
media (zhihu / weibo / xiaohongshu / wechat / bilibili / douyin / youtube / twitter, plus instagram as
cookie-capture only) via Selenium, cleans and analyzes the text with local Ollama LLMs and
scikit-learn, and renders a drag-and-drop workflow canvas. Single project, no build step.

## Commands

**The project venv `.venv/` (Python 3.11) is mandatory — never system Python.** Call
`.venv/Scripts/python.exe` / `ruff.exe` / `pylint.exe` / `pip.exe` directly (or `source
.venv/Scripts/activate`).

- Run the app: `cd backend && python app.py` → http://localhost:5000 (port via `PORT`). **Must run from
  `backend/`** — it is the `sys.path` root, so imports are top-level (`from config import Config`). Never
  add a `backend.` prefix to imports.
- Lint: `ruff check backend/` (fast gate) then `pylint <module>` (deeper); format `ruff format backend/`.
- Deps: `.venv/Scripts/pip.exe install <pkg>` **and** list it in `requirements.txt` in the same change, no
  exceptions. The rule is broader than installs: *every package imported directly by code must be declared
  there*, even when it also arrives transitively. A new tool's caches go into `.gitignore` in the same
  change that adds the tool (already covered: `.venv/`, `.ruff_cache/`, `__pycache__/`, `data/`, `logs/`).
- `backend/test_*.py` are manual probe scripts, NOT pytest (`python backend/test_zhihu.py <kw> --count N
  --no-headless`). They are the accepted place for a one-off measurement.
- **Test tiers** (`pytest.ini` `addopts = --disable-socket -m "not integration and not live_ollama and not
  live_site"`, so the two real tiers are excluded by default):
  - Fast (~2.6k cases, ~70 s, no browser/daemon): `.venv/Scripts/python.exe -m pytest -q`.
  - Device (real Chrome on `file://` fixtures + real Ollama): `... -m "integration or live_ollama"`.
  - Live-site (REAL crawls; every platform in both browser modes; per-platform skip when a cookie is absent):
    `... -m live_site`.
  - **To run one device/live case you must override the marker filter as well as naming it** —
    `pytest tests/integration/x.py::test_y` alone reports `N deselected` and looks like it ran.
  - Coverage: `--cov=backend --cov-report=term` (target ≥70%).
  - Layout: `tests/unit` (pure logic + frontend-JS harnesses), `tests/api` (Flask `test_client`, fully
    tmp-isolated), `tests/integration` (LLM boundary mocks run by default; Chrome/Ollama are marked).
    OpenRouter is **never** really called — patch `analyzers.llm_client.requests.post/get`.
  - Frontend JS needs plain `node` on `PATH`; without it those cases skip, so a "nothing skipped" closure
    run requires node.

## How tests are written here

- **Frontend JS is under test too.** `tests/frontend/harness_*.mjs` load the REAL `canvas.js` /
  `workflow.js` / `app.js` into a zero-dependency node `vm` (shared `harness_dom.mjs`) and are driven by
  `tests/unit/test_frontend_*` pytest modules: validation gates, panel HTML, popups, catalog parity,
  undo/redo, save/open/new, the run-records table, the profile fork. Any JS change to result-affecting
  logic must sync a scenario there; `urlPlatform` (workflow.js) is contract-pinned against
  `utils.helpers.platform_for`.
- **Two frontend rules that each cost a feature when forgotten.** (1) `if (window.X)` cannot see a module
  declared as a top-level `const X` — `const` never becomes a window property — which is why
  `resumeBar.refresh()` and `runsManager._busy()` were dead code forever (the 断点续跑 banner never
  showed). Guard the binding itself (`typeof X !== 'undefined'`) or export it (`window.X = X`, as app.js
  does for `LLMSettings`/`AppSettings`). (2) The DOM stub parses `innerHTML` into real children, matches
  `.class`/`#id`/`[data-x="y"]`/`:not()`, walks `closest`, queues `requestAnimationFrame` until
  `flushFrames()`, and treats an id listed in `document.absent` as truly missing. Never reintroduce
  "fabricate a child when a query finds nothing": it turned a deleted connection into a phantom one.
- **A browser-measured assertion must report how much it measured, or it is not an assertion.**
  `tests/integration/test_ui_layout.py` audits containers **by id** (the page has no `.panel` class — a
  selector matching zero elements kept that test green while checking nothing), never falls back to
  `<body>` silently, and asserts a per-container floor on the element count gathered (counted in real
  Chrome, not guessed). New containers join that list with their floor; a JS-side subtree walk returns its
  population alongside the verdict. Resolve on-screen wording from `I18n` inside the browser rather than
  hardcoding it — a pasted copy of a label drifted (lower-case `parallel ×2` vs a demanded `PARALLEL`)
  and the test asserted a string the product never emits.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the
  one the bug was about. The 并行/串行 chip was wrong precisely because `mode` was never a column of the
  record test. When you test a record, a run or a panel row, list the dimensions first (`mode`,
  `headless`, `wf_count`, resume state, language, platform, cookie state …) and cover the grid.
- **The `integration` UI tier performs no server writes** — uploading, saving a workflow or executing a run
  would leave rows in the user's real `data/` and `logs/` (the app has no data-dir override). Stub `fetch`.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall`: a valid
  session can be answered a login redirect once by risk control. An empty result without a wall is a real
  "found nothing" and still reaches the assertion.

## Crawler architecture

- **The crawl matrix (`backend/crawl_capabilities.py`) is the only answer to "what can this platform
  collect".** It declares each platform's modes, the fields each mode needs (widget, default, floor,
  ceiling, required-ness) and which crawler method runs. `app.py::_execute_source_node` dispatches
  through it, `engine/workflow.py::validate` refuses through it, and `GET /api/capabilities` hands the
  identical description to the browser, whose Data Source panel is generated from it (`Capabilities` +
  `sourcePanelHtml`). So a new platform or mode is **one matrix entry**, never an `if platform == '…'`
  branch in four files — a reintroduced branch is a second opinion that can disagree with the crawl.
  The module sits at the backend root (like `i18n.py`) because `engine/workflow.py` reads it and must not
  import the crawler package. Field labels are *frontend* catalog keys, required-field names *backend*
  ones (`field.*`), both pinned by `test_frontend_contract.py::TestCrawlMatrixParity`; `target_count`
  stays 50 for every platform because that is what the panel previews, whatever a crawler's signature
  says. **An unrecognised mode is refused by name on a platform that offers a choice**
  (`engine.source_unknown_mode`), while `mode_for` still falls back to the first mode for panel rendering
  and single-mode platforms: silently substituting a keyword search for one creator's uploads is a
  different crawl, and 「缺少关键词」 sends the user to a field the panel never showed. A payload is a
  network response and the renderer writes field names into inline handlers, so a name that is not
  `/^[\w.-]{1,64}$/` is dropped whole — and a JS-generated panel is driven in tests by the matrix dumped
  from Python (`harness_capabilities.mjs` + the `capabilities_matrix` fixture), never a copy checked in.
- **`crawlers/engine/` is mechanics, a platform module is the site.** `engine.counters.parse_count` (one
  万/千/亿/K/M/B parser), `engine.wall` (login / risk-control / root-bounce), `engine.popup.Prompt` + a
  platform's `prompts`, `engine.feed.walk_feed` / `wait_for` / `jump_to_bottom` (the scroll that finds the
  element which actually moves), `engine.pager.walk_pages` (cursor paging that follows the server's own
  value) and `engine.jsonpath` know nothing about any platform; a platform module declares only selectors,
  endpoints and column names. New crawl logic goes through these helpers — a second copy of a scroll loop
  or a 万-parser is exactly what this rule exists to prevent. `Crawler.open(url)` is the only navigation
  entry point: it survives a renderer timeout, clears the dialog and classifies the page.
- **One profile is one browser, and a parallel canvas has to be told that.** chromedriver pre-writes
  `<user-data-dir>/Default/Preferences`, so two sessions created in one directory at the same instant
  cannot both come up (measured: 2 of 8 barrier-synchronised attempts died with `session not created:
  failed to write prefs file`). `browser_profiles.acquire_profile(dir)` is a plain, **non-reentrant**
  `Lock` keyed by normalised path, held for the crawler's whole life and released in `close()` — it must
  stay non-reentrant because `_close_login_browser` releases it from a *side* thread (an `RLock` fails to
  release there and parks the platform for the rest of the process; that was the actual bug). Waiting is
  not free, so the user decides per run: `profileCollisions()` groups the canvas by connected component
  and names the platforms two workflows both crawl, `_confirmProfileChoiceBeforeRun()` asks 用 Profile
  (those crawls take turns) vs 本次不用 (true parallel, a brand-new device each), and the answer travels
  as `settings.use_profile` → `ctx['use_profile']` → `get_crawler(use_profile=…)` →
  `profile_dir_for(enabled=…)`. **Absence means "follow the setting" — never coerce missing to `False`,** or
  one dialog's answer becomes a global override. `Config.PROFILE_LOCK_TIMEOUT` bounds the wait and the node
  fails with the directory named, never with a driver stack trace.
- **A crawl runs in the platform's own Chrome profile, and the profile owns its cookies.**
  `browser_profiles.py` resolves `data/chrome_profile/<platform>` (or the user's absolute
  `browser_profile_dir`) and `get_crawler` passes it as `--user-data-dir`, so the login window and the
  crawl are the same device. Consequence: **the saved cookie file is imported once** (first use of the
  directory, marked in `.crawler-profile.json`) and **never planted again** — overwriting a live profile
  with an old snapshot is the harm, not the fix. **Never write the browser's live jar back to a saved
  cookie file.** `Capability.profile_recommended` is the single source for "this platform punishes a
  throwaway browser" and drives both the panel hint and the pre-run dialog; a second list of platforms
  anywhere else will drift.

## Platform red lines (full evidence in `docs/crawler_notes.md`)

- **douyin**: `never_headless = True` (验证码 on every headless navigation), search is DOM-only and routed
  by `/search/<kw>?type=video`, **no 播放数 column exists** (its only figure is the like count), don't
  block its images, authors are addressed by opaque `sec_uid` only, `_published_count()` returns `-1` for
  "the page said nothing".
- **X (twitter)**: `never_headless = True`; the timeline is virtualized so progress is rows kept and
  resume identity is the **status-id set**, never a list index; all five counters come from one
  `[role="group"]` aria-label and **浏览数 exists nowhere else**; one `execute_script` per card.
- **bilibili**: search pages by `&page=N` and **`page=1` renders zero cards**; comments have no DOM (only
  `x/v2/reply/main`, walked by the server's own cursor); author mode is the space *page*, not the
  (403-wbi) API; hot boards carry `owner`/`stat` inline so `hot()` fetches nothing per row.
- **youtube**: JSON-first via `engine/innertube` POSTs issued *inside* one loaded page (never hardcode
  `INNERTUBE_*`); headless is fine (no `never_headless`); a channel's uploads come from the loaded
  `/@handle/videos` document; a continuation token is chosen by **which list it is an element of**.
- **weibo**: never judge the login wall from the URL right after `get()` (it flashes the passport page
  then bounces); `/ajax/statuses/mymblog` is a per-session edge 403 → the author mode must refuse loudly,
  never serve an empty table (`backend/test_weibo_recipe.py` is the re-test gate).
- **zhihu**: headless throttles day-by-day (risk 40362) — a headless search returning 0 rows is a legit
  outcome; comment crawling always opens a visible browser. Don't loosen the assertion.
- **xiaohongshu**: replays of a saved session get walled within minutes (profile required); author mode
  is dropped — the route needs a per-note `xsec_token` this session cannot reliably get.
- **wechat**: body-only by measurement. No comments/likes/forwards columns, **no cookie row at all**, no
  `mp_logged_in`/`login_url`/`diagnose`/`MULTI_PURPOSE`, no client impersonation or session replay. The
  `live_site` file visits article URLs only; the cookie-panel harness samples bilibili/zhihu, never wechat.
- **instagram**: capture-only (`supports_crawl = False`), refused by `run.notCrawlable` and earlier by
  validation; a capture-only platform still needs `domain` + `login_url`, stays OUT of `CAPABILITIES`, and
  must clear `TestCookiePanelParity` + `TestPlatformOrder`.
- **Cookie capture ≠ crawl capability**: `CookieManager.PLATFORMS` is who the panel can log in,
  `crawlers.is_crawlable()` who has a crawler. Captured cookies are filtered to their own platform
  (`cookie_flow.retain_for_platform`) because a login detours through Google/Facebook — never widen
  YouTube's allow-list to `.google.com` (that is Gmail and Drive).
- **Cookie death mid-crawl is a designed path**: `login_wall` + under-target rows →
  `_execute_source_node` sets `execution_state['cookie_expired']` (rides on `/api/workflow/status` for the
  toast), logs `run.cookieExpired`, and **RAISES** so the node settles `partial` and the RUN becomes
  `failed` → the resume banner offers 继续 from the stored cursor. Never downgrade this to "completed with
  fewer rows" — that hides the gap forever. Comment nodes raise when any article was blocked likewise.

## Run, resume and record invariants

- Runtime state lives in gitignored `data/` (SQLite `runs.db` / `datasets.db` / `history.db`) and `logs/`.
  Do not delete `data/` casually — saved workflows reference uploaded datasets stored there.
- **One server at a time, by design (local single-user tool).** `RunStore.__init__` calls
  `promote_stale_runs()`, which marks every run still `running` as interrupted, assuming a dead process
  left it. Booting a second instance against the same `data/` interrupts the first one's live run. So
  `/smoke-verify`'s port-5057 boot is only safe when the user's own server is stopped — **ask before
  booting a second one, and never work around it by killing a process on 5000.**
- **One run at a time; a busy server queues instead of refusing.** `_begin_run()` (app.py) owns the whole
  start path (claim, validations, `execution_state`, worker thread), so the queue drains by calling *that*
  function, never a second weaker one. `/api/workflow/execute` with `queue:false` keeps the 400 for callers
  that must fail fast (the resume banner). The hand-off is in the worker's `finally` and clears
  `execution_state['thread']` **first** — the claim also checks thread liveness, so a still-alive
  unwinding thread would queue the next request behind itself forever. Queues are in-memory and
  `tests/conftest.py` clears `_RUN_QUEUE` per test. The Execute button is therefore never disabled; it
  relabels 排队运行.
- **Checkpointing is the core value** (`backend/services/run_store.py`): per-node outputs and LLM answers
  persist so an interrupted run resumes rather than re-crawls or re-pays. Keep `runs.db` state compatible.
  Three measured rules, each pinned by a test: the streaming row sink writes **one transaction per row**
  on purpose (WAL + `synchronous=NORMAL` makes a commit microseconds while a page costs seconds, so
  batching trades "killed at row 900 of 1000 still owns those 900 rows" for nothing); the next free slot
  is `MAX(seq)+1`, **never `COUNT(*)`** (that ran once per scraped row and made a long crawl quadratic in
  its own table); a **cursor records position, not content** — collected ids come from the seeded rows
  (`Crawler.seed`), so an id list must not go back into `mark_position`.
- **A label is not an input.** A node's fingerprint feeds its children, and the crawl's
  dedupe ledger is scoped by `'item:' + node_fingerprint`, so putting a *name* inside one
  invalidates a whole chain and moves the other: renaming a 工作流命名 box made 继续
  re-crawl and re-pay items it had already collected. `_VOLATILE_PARAMS`
  (`dataset_name`, `row_count`, `workflow_name`) is therefore the answer to "does this
  parameter choose data, or describe the record?" — ids stay in, labels stay out.
- **Reuse has four rules that are each easy to break.** `done` AND `restored` are reusable
  (a node that only replayed last time is just as settled — omitting `restored` made the
  *second* 继续 recompute everything); a stored result with **zero rows** is never reused,
  because a parent that came up empty last time may deliver this time and reuse is decided
  by fingerprint, not by rows; the source node is never adopted, it resumes by cursor; and
  `begin_node` reporting `dropped_stale` cancels reuse, because those rows were deleted.
- **Startup recovery shares the end-of-run settlement.** A node only ever leaves `running`
  through `finish_node`, which a kill skips, so `node_runs.row_count` still holds the 0
  `begin_node` wrote while `node_rows` holds the real work. `promote_stale_runs` must call
  `settle_nodes` (status *and* count from the rows) — the panel's 已存行数 and the 续跑
  node's "adopt the fullest node" both read that column, so a status-only promotion
  reported a 900-row crawl as empty and the user discarded paid-for data.
- **One definition of "completed".** `runs.node_done` and the console's `completed_nodes`
  must agree: skipped/failed/partial are not done, `restored` is. And the finish line's
  failed count is taken **after** settling, from `execution_state['attempted_nodes']` —
  the run record also keeps nodes the canvas deleted, which otherwise made every later
  继续 "4/4 个节点完成，1 个失败" over a run that had nothing left to fail.
- **A resumed run re-describes itself.** `start_run`'s conflict update refreshes
  `workflow_name`/`workflow_fingerprint`/`mode`/`headless`/`lang` (not `started_at`):
  leaving them at their first-attempt values made the 并行/串行 and 无头/窗口 chips
  describe a run that never happened, and the stale name is the key every
  preview/chart/export probe uses, so the kept rows stopped being findable.
- **Retention must release what it destroyed.** `purge` deletes a run's rows, so it also
  calls `forget_run_items` — an `item_seen` entry whose rows are gone would make a later
  crawl of the same signature silently under-collect, with no visible gap and no way back
  except 「重新采集」. An explicit `delete_run` still *keeps* claims: there the user removed
  a record while knowing the crawl was paid for.
- **`' + '` is a composed lookup key, not a permission.** `_durable_node_rows` tries the
  exact name the browser sends first and widens to its pieces only on a miss, or a canvas
  genuinely called `节奏` can be handed the table of someone else's `节奏 + BPM`.
- **A node id is a storage key — never re-mint one on restore.** Run records, resume cursors, LLM caches
  and `workflow_fingerprint` all key on node ids, so renumbering detaches a canvas from its own
  interrupted run. `canvas.addNode(type, x, y, nodeId)` adopts the stored id and `reserveId` keeps
  `nextId` past it (a later drag must not collide); both restore paths (`canvas.restoreState`,
  `WorkflowManager.loadFromJSON`) pass file ids straight through — pinned by `harness_state.mjs`.
- **Recorded rows are addressed by workflow, never by bare node id.** `_durable_node_rows` (app.py) answers
  a preview/chart/export/studio probe after a refresh from `runs.db`; ids like `node-2` repeat on every
  canvas, so with no identity it returns nothing rather than guessing. The browser sends `workflow_name`
  from `workflow.runName()`, which mirrors the backend precedence: name-node label, then saved file name.
- **A parallel run is one record, labelled with every workflow's name.** `app.py` joins all non-empty labels
  with `' + '` in canvas order (deduped); that string is also a **lookup key**, so `_durable_node_rows`
  splits it on `'+'` and offers both spellings to `latest_rows(workflow_names=…)` — otherwise a run stored
  before the composition existed is uninspectable. A single-workflow run keeps its plain name exactly.
  `wf_count`/`headless`/`mode` are added to an existing `runs.db` by `RunStore._ensure_columns()` (PRAGMA +
  `ALTER TABLE ADD COLUMN`), so old rows read as 1. **A chip must describe what happened, not what the
  canvas held**: `并行 ×N` only when `mode == 'parallel'`, `串行 ×N` otherwise (`wf_count` counts connected
  components, and a serial run of the same canvas has the same count with no concurrency — shipped wrong,
  caught by the user on screen). Resume state stays **per workflow** even though the record is shared:
  reuse is decided per node id by `fingerprints_for_workflow` over the whole canvas, so a failure in
  component B restores A's finished nodes and editing A re-runs A alone.

## Console, messages and i18n

- UI text supports zh/en via the `backend/i18n.py` catalog — add every new user-facing string there (both
  languages), and the same for `backend/static/js/app.js` catalogs.
- Console/validation messages reference nodes through `engine.workflow.node_label(node, nid)` (→ `title
  #nid`), never a bare `nid`, so a renamed node speaks with the user's name. Store keys, the results dict
  and resume plumbing still use the raw `nid`. The frontend keeps `node.title` in `getState` /
  `toWorkflowJSON`, and BOTH restore paths re-apply title + element text BEFORE `updateNodeDisplay`, whose
  re-stamp guard reads the element.
- **The run console keeps its own history per view, because the server cannot give it back.**
  `/api/workflow/status` ships only the last 200 lines of the *whole* run, so a tab switch that blanks
  `#console-output` leaves it empty forever for a finished run. `consoleViews` in workflow.js holds
  `{seen, lines}` per view (`'all'` plus each workflow id), **every** view is fed on every poll, and
  `switchWfTab` repaints from that view's history without moving its cursor. `clearConsole` empties the
  histories and leaves cursors alone. Cap is `CONSOLE_VIEW_CAP` per view; a trim repaints.
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook.** Those nodes
  get no "Executing node …" and no "Node … completed (n/N)" line. Everything that states a fact still
  prints: the upload's own "Loaded uploaded file X: N rows", and any failure/skip/restore line (with
  `node_label` — a silenced node that then fails is a run the user cannot diagnose). Progress counters
  still count them.
- Run-gating UX lives in `workflow.js execute()`: `_confirmCookieBeforeRun` (skippable via the
  `cookie_confirm_before_run` setting, auto-pass for resume runs). **A new settings key needs all four:**
  the bool branch in `settings_store.save_settings`, both app.js catalogs, and the `AppSettings` wiring.

## Style (differs from defaults)

- Comments and docstrings are in **English** even though README/commits are Chinese. Explain "why".
- Section dividers: `# ─── Name ───`.
- Ruff: line-length 120, **single quotes**, indent 4, modern typing (`str | None`), py311. Lint findings are
  **genuinely fixed**: never `# noqa`, never `# ruff: noqa`, never a `per-file-ignores` or rule exemption
  in `ruff.toml`.
- **Code changes are tracked Edits.** No Python/sed bulk rewrites of source or test files.

## Commits

Chinese messages with a type prefix matching history: `功能更新：`, `问题修复：`, `修改：`.

## Change workflow (MANDATORY on every change)

1. **Edit** — the PostToolUse hook auto-runs `ruff format` + `ruff check --fix` on touched `.py` files.
2. **Tests are part of the change.** Any code file touched (backend *or* frontend JS) means syncing the
   suite in the same change: new feature → test it; changed behavior → update the affected assertions;
   deleted feature → remove its tests. The suite must prove the new thing is right *and* nothing old
   broke. A previously-green test failing because of your change means the bug is in the change — fix the
   code, not the test (exception: it pinned an old bug that is now genuinely fixed).
3. **Fast suite green**: `.venv/Scripts/python.exe -m pytest -q`. A genuine product bug found by a test is
   fixed in product code; if it cannot land now, pin it with
   `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — ...')` and report it.
4. **Lint green** on every file committed: `ruff check <files>` and `ruff format --check <files>`.
5. **New packages**: installed into `.venv/` AND declared in `requirements.txt` in the same change, with
   caches in `.gitignore`.
6. **Docs stay true**: update `README.md` in the same change whenever user-visible behavior changed
   (features, node types, API tables, config, structure, quickstart). Move crawler measurements to
   `docs/crawler_notes.md`. A stale README is a failed change.
7. **Device paths**: if the change touches crawling, LLM transports, checkpoint/resume or the UI, also run
   `-m "integration or live_ollama"` (Chrome + Ollama exist on this machine — and check port 5000 is free
   first), then `/smoke-verify` (lint → boot 5057 → GET endpoints 200 → clean shutdown). Paths neither
   tier reaches (logged-in scraping against live sites, human feel) are exercised by the user in a browser.
8. **Commit** last, with a Chinese type prefix.
9. **Closure gate for any "we are done" claim**: one full run of *every* tier with nothing deselected and
   nothing skipped, in which **no file needed changing**. Any edit restarts the loop.
