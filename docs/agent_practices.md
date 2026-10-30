# agent_practices.md — the *why* behind each AGENTS.md rule

Every rule in `AGENTS.md` is stated bare there because that file loads into **every** session and must stay small.
The evidence — the measurement, the crash, the feature it once cost — lives here, and this file is **not** auto-loaded.
Read the matching section before rewriting, doubting, or "simplifying away" a rule: each was paid for (a live re-run,
a broken feature, a silently-skipped green tier, a blank page). **Grep by the bolded rule title** — the same anchor
`AGENTS.md` uses; every bolded title survives on purpose.

Dedup with the other docs: the refactor **ledger** is `docs/archive/refactor_plan_2026-10.md` (archived when
the refactor completed); **crawler imperatives** live only in
`docs/crawler_rules.md` (linked, never copied here). A whole-project refactor (Stages 0–11) is complete; this file
records why each rule exists, not the migration narration.

## Commands / deps — why the model-degradation rules exist

Code may never **silently** answer with a model other than the one it claims — a column labeled `bert` that actually
ran `snownlp` is a fabricated, unauditable result. Each sanctioned degradation PRINTS the method that ran. The two
that exist: a topic step's `method=auto` (`_resolve_topic_method`) picks **embedding** when the encoder imports,
**LDA** when it does not; `sentiment`/`emotion`/`tendency` default to `bert` (`_effective_bert_model` reads the node's
model or `model_registry.json`'s `operation` default) and `_resolve_bert_mode` degrades to the dependency-free mode
(`snownlp`/`ml`) with a printed line. The analyzers still refuse an unrunnable `bert` **by name** (defense in depth),
and a multi-model BERT comparison never degrades. torch/transformers go to `requirements-optional.txt` (not CI-installed)
precisely so CI exercises the degrade-and-print path rather than hiding it.

The local PostToolUse `ruff format` **silently fails on a restricted workspace** (measured `os error 5`: ruff writes a
temp file then renames) — the edit stays unformatted while the hook looks fine. Hence run `ruff format` by hand before
committing; CI (`ruff check` + `ruff format --check`) is the unskippable gate.

## How tests are written here

- **Isolation happens at conftest import; the suite fails if `data/`/`logs/` gains a byte.** `tests/conftest.py`
  redirects every write path *before any test module imports* — collection imports all modules before any fixture runs,
  and `app.py` captures `Config.COOKIE_DIR`/`history.db` into module-level singletons at its own import, so a later
  redirect is too late. `test_test_tiers.py` refuses the import statically; the session-finish snapshot refuses the write.
- **A warning is a test that noticed something and passed anyway — fix what it noticed, never mute it.** Fixes landed
  from warnings: a class-scoped fixture is `@pytest.fixture` FIRST, `@classmethod` SECOND (an instance-method fixture's
  `self` is discarded before tests run). pytest is unpinned, so CI moved 9.1.1→9.2.0 mid-day on 2026-10-28 and the old
  order stopped being registered — every such test errored at setup `fixture '<name>' not found`. Measured in a throwaway
  venv: swapped order, `@staticmethod` and module-level fixtures all pass on 9.1.1 AND 9.2.0; only the old order breaks.
  Pinned: `tests/unit/gates/test_test_tiers.py::TestClassScopedFixturesAreVersionProof`. Other fixes: close file
  responses; never let a cookie-save open a **real Chrome inside the fast tier** (the plant swallowed a socket failure,
  answered 「种入失败」, left a `UserWarning`); a no-browser test says so (`profiles_off`). Not ours, left visible:
  jieba 0.42.1 imports deprecated `pkg_resources`, and anyio's plugin warns about `CallSpec2` under 9.2.0.
- **A stateful rule needs a stateless suite.** The suite shares ONE cookie directory, so `quiet_jar` snapshots/restores
  it per test — a login another test saved is a precondition this one never set up.
- **The frontend may not hold a second opinion about a crawl.** `sourceNodeErrors()` asks `Capabilities` which fields
  the mode requires; if not loaded it refuses rather than guesses — and the form obeys the same rule (`boolParam`,
  `selectOptionTags`), so a stored value off the list shows as itself, never option #0.
- **A canvas shortcut belongs to the canvas only while the user is not typing.** `canvas._isTypingTarget()` asks what the
  element IS (`isContentEditable`, `.cselect`, …), because an earlier growing *tag list* left out a paste box.
- **The camera is not part of the model.** Putting pan/zoom in `getState()` made every pan an undo step. `addNode`
  randomizes only for a non-finite value, never `x || …`, because a saved x/y of `0` is a real position.
- **One page boot must not be a single point of failure:** a throw inside the one `DOMContentLoaded` body skipped every
  later step (canvas.init never ran, page stayed blank, nothing readable in console) — hence `boot(name, fn)`.
- **Six frontend rules, each costing a feature when forgotten.** (1) `if (window.X)` cannot see a top-level `const X`
  (not on `window`). (2) The DOM stub's matcher is real (`harness_dom.mjs`); fabricating a child hides a broken selector.
  (3) A wrapper with an empty parameter list acts on whatever was selected *before*. (4) A name inside
  `onclick="fn('…')"` spans two grammars: `attrJsArg` JS-escapes the literal *then* HTML-escapes the attribute. (5) A node
  captured before an `await` is gone after it (panels/run-list rebuild) — re-look it up (`_rowFor`). (6) **A wrapper
  installed in another file is not the function your harness loads**: `app.js` re-assigned `window.openCookieDialog`
  with one parameter while the real one took two, so the account argument died *in the browser only* — forward
  `(...args)` and measure a change behind a patched global in the browser tier too.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the bug's dimension.
- **A live case's numbers are computed from the site, never chosen.** Derive an ask/threshold/floor from what the crawl
  reported (the card's 评论数, the page's own count, the board's size) and make the assertion two-sided — two D-cells of
  `test_live_weibo_workflow.py` each cost a live re-run for breaking this.
- **A browser-measured assertion must report how much it measured, or it is not an assertion.**
  `tests/integration/test_ui_layout.py` audits containers **by id**, never falls back to `<body>`, reports a
  per-container floor, and resolves on-screen wording from `I18n` in the browser. **State the viewport:** on Windows
  `set_window_size`/`set_window_rect` are silently ignored (a dialog's `calc(100vh - …)` cap is taken once, on first
  open), so "fits a 1366×768 laptop" can be measuring a 1920×1080 window wearing another test's cap — emulate
  (`Emulation.setDeviceMetricsOverride`) and assert the size CSS sees with a `100vh` probe, because `window.innerHeight`
  reports the un-emulated one.
- **A closed panel must be gone, not merely moved — and only pixels can prove it.** `#clipboard-drawer` hid with
  `transform: translateX(100%)` under `right: 12px`; a percentage translate is the box's own width, so the closed edge
  landed 12px INSIDE the viewport and its last 12 columns painted over the canvas. Measured in Chrome at 960×920
  (`clientWidth` 938): `rect.left=926`, a 60×340 `Page.captureScreenshot` strip against the same box forced
  `display:none` read **813 differing pixels, worst channel delta 41** (a closed-vs-closed control read 0/0 first — that
  control is what makes those pixels quotable). The shadow (`--shadow-soft` blurs 3px past the border box, not
  hit-testable) is why the rect fix alone is not the fix: the drawer also carries `visibility: hidden`, delayed 0.15s.
  `test_ui_layout.py` pins both halves (each fails independently) plus the byte-identical strip. `clientWidth`, never
  `innerWidth`: it excludes a classic scrollbar.
- **A test may not assume the machine's own zone.** GitHub CI runs UTC, this box runs UTC+8, so the scheduler's
  blank-zone case written as `... == '2026-10-16 08:00 (服务器本地)'` was a +08:00 literal wearing a test's clothes (failed
  CI as `1 failed, 6498 passed` while green locally). The expectation belongs to the machine (`astimezone()`, the same
  definition `scheduling.store.describe_time` uses); a NAMED zone stays a literal (`'Asia/Shanghai'`→`08:00`).
  **Python on Windows honours `TZ`** — `$env:TZ='UTC'` reproduced CI's failure and removing it restored `+08:00` — so
  `$env:TZ='UTC'; pytest -q` is a cheap CI-equivalent gate (reads 6501 passed).
- **The `integration` UI tier performs no server writes** — no data-dir switch exists, so a run/upload lands in the
  user's real `data/`/`logs/`. Stub `fetch`.
- **A fail-loudly flag must fire for the run that asked for the guarantee, not for the directory it happened to import.**
  With `CRAWLER_REQUIRE_BROWSER=1` the session probe in `tests/integration/conftest.py` started Chrome for *any* file in
  that directory — including `test_weibo_crawler.py`, whose 66 cases drive a fake driver in 0.9 s and are marked `unit` —
  giving 66 ERRORs reading `SocketBlockedError`: a confident claim the device tier is broken, from a session that never
  requested a device. Fixed by `pytest_collection_modifyitems` recording whether any selected item carries
  `integration`/`live_ollama` and gating the probe on it. Pinned: `tests/unit/gates/test_test_tiers.py` drives the hook
  with both selection shapes.
- **A comment naming its callers is a claim, and callers can be deleted around it.** `weibo/crawler.py` carried a block
  headed *"compatibility shims (kept for callers outside this module)"* with four methods; measured, each appeared
  **exactly once in the repo — at its own definition**. Count occurrences repo-wide before believing a "kept for callers"
  note.
- **A whole-class move is only safe if the copy is proved, not promised.** `PlayerUI` (559 lines, 29 methods) went from
  `hongguo/harvest.py` to `hongguo/player_ui.py`; the script asserted the moved text appears in the new file **as one
  contiguous run**, differing only by the four allowed renames (crossing names lost their leading underscore — an
  underscore imported by another module invites copying it). A hand-typed 83-line `naming.py` was checked the same way.
  Two ordering rules, both costing a cycle: **check before you write** (the first version wrote `harvest.py` then asserted
  no stale name, leaving a second `class PlayerUI:` + an import; only `git checkout --` saved it) and **the seams move
  with the code** (three tests patched `harvest.time.sleep` to drive a `PlayerUI` walk; `time` is one module object so they
  still worked — the shape that breaks quietly when the old module stops importing it — so they now patch `player_ui.time`).
- **A rename pass must be written as three rules, not one.** Moving five modules into `sessions/` was 661 references, and
  two over-reaches came from one string substitution: ① `cookie_manager` is BOTH the module and the jar *instance*
  (`state.cookie_manager`), so rewriting `cookie_manager.`→`cookies.` broke 28 instance calls; ② `api.browser_profiles`
  contains `browser_profiles` as a *word*, so a word-boundary rule rewrote the route's own import path. Surviving rules:
  import lines by exact form, attribute sites only where the file cannot mean the instance, instance spellings left alone.
  `ruff check` is the cheap first net: it reported 23 F821 + 2 F401 before any test ran.
- **`git mv` stages the rename, not the edits that follow it.** Moving the scheduling trio, the add list named only
  `scheduling/__init__.py`, so `clock.py`/`store.py` were committed **with their old imports**; the commit summary still
  printed the `M` lines and the local gate was green (worktree right), but CI answered `E0611` in two and a half minutes.
  Rule: after `git mv`, every moved path is a **new path** added explicitly; read `git diff --cached --stat` — the runner
  tests the index, local green says nothing about it.
- **Before "creating" a file, ask whether it already exists — and run the whole family, not the new test.** Stage 8's
  first knife overwrote `tests/frontend/page_scripts.mjs` (which already existed with `loadPageScripts`, imported by four
  harnesses); the Write result said **updated** and `git status --short` showed `M`. Caught by running every
  `tests/unit/frontend/test_frontend_*.py` — 58 errors. Two rules: check existence (`??`=new, `M`=overwriting someone);
  a new test file is not the blast radius of a shared helper — the family that imports it is.
- **A rename pass must not run before the path rules, and cannot see modules held through another module.** Moving `utils/`
  into `core/` ended with two wounds: ① rule `\bmachine_deps\b`→`machine` rewrote the *string literal*
  `'utils/machine_deps.py'` inside `WINDOWS_TABLES` and the Dockerfile-env scan — a path that existed in prose nowhere on
  disk; path rules run first and a word rule skips quoted spans. ② Tests reached the module through the *production
  module's attribute* (`bridge.machine_deps`, `harvest_module.machine_deps`), invisible to import/attribute rules; only the
  full suite named them (5 failed + 10 errors). Grep `\.<old name>\b` across tests, not just imports of the old path.
- **`getattr(x, name, None)` is the seam shape that never reports.** `tests/live_run_harness.py::real_jar/no_jar` located
  the cookie jar through `getattr(module, 'cookie_manager', None)` with `module`=the imported `app`, but the instance had
  moved to `state.cookie_manager` (`runtime/state.py`), so the lookup answered `None`, the guard skipped the patch, and
  **88 live cases redirected only `Config.COOKIE_DIR`** — a live case could crawl with the user's real session while
  claiming it proved the anonymous path. Nothing failed. Census after this: search `getattr(<module-ish>, '` in every
  tier's helpers; a helper that *optionally* patches something must assert the thing exists (these now import `state` and
  patch `cookie_manager.cookie_dir` unconditionally). An optional seam is an untestable seam.
- **A dotted-prose rule is a code rewrite when it runs over `.py` files.** Moving `crawl_capabilities` into
  `capabilities/registry.py` applied `\bcrawl_capabilities\.`→`capabilities.registry.` everywhere, so
  `capabilities.CAPABILITIES` (the module's local alias) became an attribute of a module with no `registry` member. ruff
  named 22 F821 in 9 files; three more had an alias bound where the same bug is a run-time `AttributeError` and no linter
  sees it. Rule: dotted/prose rewrites belong to `.md` and hand-edited docstrings; `.py` code changes by import/attribute
  rules only.
- **A re-export needs `__all__`, and an order pin is a contract only where order is data.** Collapsing five chart-type sets
  into `services/charts/registry.py` hit both: ① `contracts.py` kept re-exports that PostToolUse `ruff --fix` deleted as
  F401 (a name imported only to hand on is *unused* unless `__all__` says otherwise); ② deriving `ECHARTS_ONLY_TYPES`
  put types in panel order and a pre-existing test compared it **as a list** — membership lists both sides test only with
  `in` must be compared as sets; the order pin belongs only to `CHART_TYPES`.
- **A carve's rename map needs a whole-token guard, and "the file parses" is not proof the wiring exists.** Splitting
  `capabilities/registry.py` into `platforms/<id>.py` broke twice: ① plain `str.replace` of private atoms made `_TIMES`
  collide with the suffix of `COMMENT_TIMES` (and `_ACCOUNT`/`_BOARD` similarly) producing `*COMMENTTIMES` and an F821 on
  a name nobody wrote — the guard is `(?<!\w)OLD(?!\w)` and the old name is gone **as a token**; ② writing each body
  without the `CAPABILITY = ` prefix left a bare `Capability(...)` statement — legal Python that `ruff format` wrapped in
  parens, surfacing only as "module has no attribute 'CAPABILITY'" at assembly. The honest proof is a before/after
  comparison of the **behaviour** (`as_dict()` byte-identical, every mode/field equal), not the moved text alone.
- **Splitting a data table by AST line spans breaks on parenthesised values; delimit entries by TOKENS.** Moving the
  4,600-line catalogue into `i18n_catalog/<domain>.py` failed twice: ① taking an entry as `lines[key_line:value_node.end_lineno]`
  is wrong for the multi-line parenthesised form — every generated module lost its `),` and failed to parse; `tokenize`
  ends an entry at the comma whose bracket depth is the dict's own level, carrying 281 comment lines with it. ② The walk
  started the first entry at the `_ZH = {` line; the start is the line **after** the brace. ③ The proof compares the
  **values** (`ast.dump` per key), not text (re-indenting is legitimate), and the split creates a hazard a single dict
  could not: a domain file not in `MODULES` holds messages that can never print while parity/reachability/`audit()` stay
  green. So the merge refuses a key claimed twice at import, and `test_i18n.py::test_every_catalogue_module_is_merged`
  compares `MODULES` to disk.
- **The UI tier's driver is `page_load_strategy='eager'`: `driver.get` returning is not evidence that a script ran.** A
  CI run failed `test_opening_the_settings_panel...` with `JavascriptException: canvas is not defined` while `I18n`
  (defined in a LATER script) was fine — the page booted, one earlier script had not; same bytes passed locally and
  before. A test driving page bindings must wait by name (`readyState === 'complete'` plus `typeof canvas === 'object'`)
  and on timeout fail with the document's script list and each script's transfer size. All 54 navigations in
  `test_ui_layout.py` now go through `_load_app`.
- **A harness that reads module files by hand is a second opinion about the split map — and the map must read each file
  once.** Three harnesses (`harness_menu`/`harness_app_state`/`harness_schedules`) did their own `argv.map(readFileSync)`
  instead of `companions.mjs`, so when `LLMSettings`/`AppSettings` moved out of `app.js` their boots died with
  `ReferenceError`. Fixing them surfaced the other half: a harness naming `workflow.js` **and** one companion evaluates a
  file twice, and in the shared global a second top-level `const` is `SyntaxError: Identifier 'Outline' has already been
  declared`. `sourcesWithCompanions` dedupes per call (owner still first). Static scans moved to
  `static_assets.js_text('app.js')`; `I18N_USERS` was a hand-kept list of 14 files while the tree has 37, leaving 709
  literal `I18n.t('…')` calls outside the word audit (every one in fact clean) — now derived (`js/**/*.js` minus `i18n/`)
  with a scope floor.
- **An object cannot be split by concatenation, and its members cannot be re-bound.** `canvas` is one top-level `const`
  object of 158 members that markup and every panel call by name, so a second file has exactly one way to add to it:
  `Object.assign(canvas, { …members… })`. Hazards: ① `Object.assign` does not complain when a member is declared twice —
  the later silently replaces the earlier, the duplicate-key accident spread over two files no diff shows;
  ② the *proof* of a member split is not the byte rejoin alone (that says nothing was lost) but the key-surface compare
  (old single file vs family: names + kinds + function arities identical). Both are pinned by
  `tests/unit/frontend/test_frontend_canvas_sections_js.py` (loads each section against a bare object so a section cannot
  borrow members from another file, asserts per-section key sets disjoint, union equals `Object.keys(canvas)`). The
  one-off `build/verify_canvas_split.py` / `verify_canvas_surface.py` scripts that produced this proof were deleted; the
  **158-member surface is pinned by the test, not the script.** Also `page_js` exists because "who binds `canvas`" is a
  per-PAGE question (the studio page has its own local `canvas`).
- **Moving a Python function moves its patch seam with it — and a stale seam is GREEN, not red.** Run-path tests patch
  `app.add_log` and rely on `tests/api/conftest.py` forwarding it into the module that resolves it. The fixture listed
  `engine.run`; when the scheduled fire's narration moved to `engine/run_schedule.py`, its `add_log` resolved THERE, so two
  schedule cases asserted on a list nobody filled (they failed loudly only because the assertion demanded the lines; a case
  asserting "no line printed" would have passed the whole way through). The census is now read from the source:
  `tests/unit/gates/test_console_seam_census.py` parses every `engine/*.py` for `from runtime.state import add_log` and
  requires each hit in the forward list, and rejects the reverse. Companion fact: `start_scheduled_run` reaches `begin_run`
  as `run_engine.begin_run` looked up INSIDE the function — `tests/api/test_run_races.py` refuses a by-value
  `from engine.run import begin_run` anywhere, which is what keeps "one fake run start" meaning one thing.
- **Lifting a nested helper out of a closure is proved with `ast` + `symtable`, never a byte diff.** Re-indenting changes a
  multi-line string's VALUE (the inner functions' docstrings shift 4 spaces, which a byte compare calls a change and a
  careless `dedent` would really be), so the check is per-function `ast.dump` equal (added params removed from the lifted
  side), multi-line strings equal after stripping each line's leading whitespace, single-line strings strict; then
  `symtable` states the point (lifted function has no free variables; its former host no longer lists it). Both ran
  AGAINST THE FORMATTED FILE, not just the bytes the script wrote. The same proof normalises TWO traps on the last six
  lifts (`run`→`_run_worker`): ① fold the original's constants but do NOT drop its call arguments (dropping both sides
  turned short calls into zero-arg and "failed" a verbatim move); ② align the rename (`run`→`_run_worker`) first — the
  rename itself is pinned by the gate (thread `target`/`name='run'`). Call sites that don't travel with the block
  (`_inputs_for(nid)` inside `_run_single_workflow`) are a third class the arity change turns loud — list them from
  `grep` before proving. The lift buys reachability: a closure is invisible to every test. Captured names becoming
  parameters can RAISE an intermediate helper's free-variable count (`_component_run` now closes `resumable`/`resuming` to
  hand them down): the goal is a visible source for each value, not the smallest closure. All ten helpers are now at
  module scope; pinned by `tests/unit/gates/test_run_worker_module_scope.py` (no FunctionDef nested inside a module-level
  function of `engine/run.py`: the lift is permanent or it is caught).
- **A prefix→directory move has five traps the rename rules cannot see (all hit in one group).** Moving eleven
  `services/biblio_*` into `services/biblio/` went 122 references clean then failed five ways: ① **`ruff --fix` deletes the
  import a pending rename is about to use** — edit call sites BEFORE import lines, every time; ② **a multi-name from-import
  is two names in one line** (`from services import biblio_formats, biblio_sources` matched the first rule and produced a
  named ImportError) — one rule per *name*; ③ **a module one directory deeper changes every `Path(__file__).parents[N]`**
  (geo's basemap pointed at a nonexistent path, 34 tests red) — grep `__file__` first; ④ **a module alias can collide with
  a local variable** (`metrics.py` assigns `cluster = …`, so `cluster.cluster_graph(…)` was F823 — import it `as
  clustering`); ⑤ **`git mv` stages the moves, not the sibling importers**. The proof is a residual scan that REFUSES to
  finish, not a green suite.
- **Count references by the NAME a file binds, not by the module path.** Before moving `net_probe`, grep for
  `services\.net_probe` reported 2 references; the move rewrote **50** `net_probe.` call sites (callers bind via
  `from services import net_probe`). Inventory asks for the binder then greps the bare name. Same day: a **bare module
  reference** `monkeypatch.setattr(net_probe, '_session', …)` is invisible to an attribute rule (name followed by comma)
  and shows only as F821 (23 sites); the multi-name import matched the first rule and left the second; and `--fix` deleted
  a freshly re-added import once more.
- **A readiness sentinel that shares a prefix with success is a tolerance arm wearing a costume.**
  `test_a_run_detail_splits_its_workflows_without_growing_a_bar` failed on CI with "the detail row never appeared" while
  its gate said fine — its bounded poll returned `"ok | the detail row never rendered"` on timeout and the Python side
  asserted `outcome.startswith('ok')`. Fixed by removing the second round trip: expand **and** measure inside one
  `execute_async_script`, returning `{found, …}` or `{found: false, …}` — no sentinel to lie, and the stub installed
  **before** anything renders (the page's own boot repaint drops the expansion row).
- **An async browser seam must resolve on the DOM, and its error arm must not be `done()`.** The earlier fix wrapped
  `Promise.resolve(runsManager.detail(...)).then(() => done(), () => done())`, wrong twice: `detail` renders in a task
  *after* the promise settles, and the rejection arm answered `done()` as if nothing failed, throwing away the only cause.
  Correct shape: await the promise, **keep the outcome**, then poll the document for the element (bounded). Lesson
  generalizes: a tolerance arm in a test helper is the same bug class as one in a crawler — what "a warning is a test that
  noticed something" is about.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall`. An empty that NAMES
  its refusal (wall/risk) is the site's answer — assert the naming; an unnamed empty is real "found nothing" and stays red.

## Run, resume and record invariants

- **One server per data root, by design (local single-user tool).** `RunStore.__init__` calls `promote_stale_runs()`,
  which marks every run still `running` as interrupted, so a second instance on the same `data/` kills the first's live
  run. `CRAWLER_DATA_ROOT` gives a process its own `data/`+`logs/` (the `/smoke-verify` boot and the UI tier use it).
- **One run at a time; a busy server queues instead of refusing.** `begin_run()` owns the whole start path, so the queue
  drains by calling *that* function, never a weaker second one. The worker's `finally` clears
  `execution_state['thread']` **first** (the claim also checks thread liveness). Queues are in-memory
  (`tests/conftest.py` clears `_RUN_QUEUE`).
- **A test that calls an executor function directly must leave the app quiet:** `clean_globals` *fails* a test that leaks
  `execution_state['running']`.
- **Checkpointing is the core value.** Three measured rules: the streaming row sink writes **one transaction per row** on
  purpose; the next free slot is `MAX(seq)+1`, **never `COUNT(*)`** (deleted rows make COUNT collide); a **cursor records
  position, not content** (ids come from `Crawler.seed`, so an id list must not go back into `mark_position`).
- **A label is not an input.** A node's fingerprint feeds children AND the dedupe scope (`'item:'+node_fingerprint`), so
  a *name* inside one invalidates a chain. `_VOLATILE_PARAMS` (labels + switches like `recrawl`/`enabled`) answers "choose
  data, or just describe?" — ids stay in, labels and switches out.
- **A result view is pinned to a RUN, not each node's newest rows.** `latest_rows(node_id, workflow_name)` answered "the
  latest table" one node at a time; loaded together it could stitch node-1 from last night to node-2 from this morning and
  present a run that never happened. `/api/runs/for-workflow` lists this canvas's records by the structure fingerprint 继续
  uses; the browser pins `run_id` into every preview/chart payload and the resolver reads **only** that run's rows. Live
  node states come from `attempt_records` (reset per attempt), never `owned_records` (kept across runs).
- **A disabled node is not on the canvas:** `effective_workflow` drops it (`enabled`/type/all-upstream gone; cascades;
  fan-in survives on one live input); validate/naming/fingerprint/execution run on that graph.
- **Reuse has four rules** because each was violated once: `done` AND `restored` are reusable; a stored result with **zero
  rows** is never reused; the source node is never adopted (resumes by cursor); `begin_node` reporting `dropped_stale`
  cancels reuse.
- **Startup recovery shares the end-of-run settlement.** A node leaves `running` only through `finish_node`, which a kill
  skips, so `node_runs.row_count` still holds the 0 `begin_node` wrote. `promote_stale_runs` must call `settle_nodes`
  (status *and* count from rows) — the panel's 已存行数 and 续跑's "adopt the fullest node" read that column.
- **One definition of "completed":** counts are taken **after** settling over `attempted_nodes` (the record keeps nodes the
  canvas deleted); a node 停止 cut short counts in its own `stopped_node_ids` bucket — reporting the user's own button as
  「1 个失败」 is a lie.
- **A resumed run re-describes itself:** left at first-attempt values the 并行/串行 and 无头/窗口 chips describe a run that
  never happened, and the stale name (the key every preview/chart/export probe uses) makes the kept rows unfindable.
- **A phase column's order is not data, and a records round trip erases it.** `bin_time` writes an ORDERED categorical
  (`pd.cut`), but every node boundary rebuilds the table with `pd.DataFrame(current_input)` (`engine/run.py`), leaving plain
  strings whose code-point order puts 二次爆发期 before 发酵期. A step emitting a phase table must also emit its position
  column (`stage_order`/阶段序号, a NUMBER) — the only thing surviving the boundary.
- **A quoted row count is only true of the merge order that produced it.** 近重复去重（SimHash）keeps whichever row of a
  group arrived first: six files in canvas order give 3778/4366/4993/4526/623 per phase, in filename order 3620/4454/5032/
  4555/625 — and every 事件标注 volume with them. Measure through the canvas's OWN upstream order (walk `connections`).
- **A coherence sweep is not a decision, and only the canvas's own sweep may be quoted.** 主题数扫描 draws 2000 docs by
  default and the draw follows row order, so its argmax moved between merge orders (8,5,6,7,3 ↔ 2,7,3,4,2). 波动期's
  coherence spans 0.227–0.337 across 2..8 and 发酵期's 5..8 sit within 0.004, so argmax is noise with a number on it. Hence
  the justifying scan runs `coherence_max_documents=0` fed by that canvas's own phase filters; where flat, state the
  tie-break (highest coherence at **≥3 topics**) in the node title — an unseen floor is judgement dressed as measurement.
- **A score is a function of the column it was read from.** The same 18286 rows scored on `正文` give
  0.211/0.200/0.217/0.228/0.238, on `cleaned_text` 0.164/0.170/0.173/0.199/0.200 — same shape, ~0.04 apart. Quote the
  column or the curve can't be audited.
- **An unused LDA topic is the model's answer, not the user's mistake.** An argmax can leave a topic with zero documents;
  `topic_by_stage` fills that row from the topic's own word distribution, files `doc_n = 0`, logs one named warning —
  never kills the run or empties 特征词.
- **A recall device must not look like a classifier.** `aggression`'s word-list mode states a miss is unmeasurable, keeps
  the lists in code, and deliberately does NOT count 辟谣 accusations as violent. A missing text column **raises** rather
  than returning blanks.
- **The analysis node's one non-deterministic step borrows the process node's client:** the run report echoes every step's
  `params` into the console and durable record, so a client in `params` would be a live object written into a ledger —
  hence `llm=`/`cancel=` go only to the ops in `LLM_OPS`. A Stop leaves `未处理` rows the model never saw, which settles
  that node PARTIAL, not DONE.
- **Retention must release what it destroyed:** `purge` deletes a run's rows so it also calls `forget_run_items` (an
  `item_seen` entry whose rows are gone would make a later crawl under-collect silently). An explicit `delete_run` still
  *keeps* claims: there the user removed a record knowing the crawl was paid for.
- **`' + '` is a composed lookup key, not a permission:** widening the exact-name probe unconditionally would hand a
  canvas genuinely called `节奏` the table of someone else's `节奏 + BPM` — hence widen only on a miss.
- **A node id is a storage key — never re-mint one on restore.** Run records, resume cursors, LLM caches and
  `workflow_fingerprint` key on node ids. `addNode`'s `nodeId` + `reserveId` keep `nextId` past a restored id; both
  restore paths pass file ids straight through (pinned by `harness_state.mjs`). That id is also the box's **DOM** id, so
  `getElementById(<node id>)` lets a workflow file address chrome the node doesn't own — reach elements through
  `canvas._nodeEl(id)`, and `test_frontend_state_js.py` fails any variable-argument `getElementById` in `canvas.js`.
- **Recorded rows are addressed by workflow, never by bare node id:** ids like `node-2` repeat on every canvas, so
  `_durable_node_rows` returns nothing rather than guessing when it has no identity. The browser sends `workflow_name`
  from `workflow.runName()` (name-node label, then file name).
- **Parallel is one record; serial is one record per workflow that started.** Parallel joins labels with `' + '` in canvas
  order (also a **lookup key**, pinned by `TestRowLookupStillWorks`); serial opens each workflow's own row **as reached**.
  Every row keeps the **canvas** fingerprint (resume banner + `/api/runs/resumable`); the response returns workflow zero's
  row; 继续 adopts each by name. **A chip describes what happened:** `并行 ×N` only when `mode=='parallel'`, serial says
  `串行 ×1`; resume state stays per workflow (`fingerprints_for_workflow`) so B's failure restores A.
- **A cursor records what the node PROVED, never what it attempted.** `execute_comment_node`
  (`nodes/executors/comment.py`) wrote
  `{'url_index': idx-1}` *before* handing a link to its adapter, so a pass that walked all ten dramas left the cursor at
  `9`. Both end-of-node refusals raise *after* the loop, so 继续 skipped 1..9 and re-walked the last link alone (fresh
  harness, `skipped_targets` empty, both gates slept) — the node settled **DONE** over the hole the console had named. The
  write now happens after the walk and only while the run of completed inputs is unbroken; rewinding is safe because the
  ledger refuses a re-walked comment (`item_key`). Pinned by
  `test_a_tail_refusal_leaves_the_cursor_behind_the_hole_it_named`.
- **A row's ledger key is its site identity, not its content.** `run_store.item_key` identifies by link, else
  title+author+body-head, else a whole-row hash. Comment columns deliberately avoid those field lists (every comment of one
  article would share a key and all but the first would be dropped) — which left them on the whole-row hash carrying
  volatile `楼层`, which a fresh harness renumbers from 1. A comment is now keyed by (`平台`, `评论ID`). Changing the function
  rotates existing keys, so a saved comment node re-files its set exactly once.

## Console, messages and i18n

- **A missing `t()` keyword is a printed bug, not a crash.** `t()` deliberately returns the raw template when a param is
  missing (never abort a crawl for a sentence), so a forgotten `{reads}` prints `阅读={reads}`. Key parity, reachability
  and zh/en matching are all blind to it; `test_i18n.py::TestCallSitePlaceholders` walks every `t('literal', …)` with `ast`
  and refuses the mismatch.
- **A `{platform}` slot is answered with a word, not the key:** `zhihu` keys the matrix/cookie file, `i18n` localizes it
  (splitting on `,`/`、` only), and `test_frontend_contract.py` (`TestChromeOfThePageItself`) keeps the two lists equal.
- **Console messages reference nodes through `node_label` (→ `title #nid`), never a bare `nid`,** while store keys/results/
  resume plumbing still use the raw `nid`. BOTH restore paths re-apply title + element text BEFORE `updateNodeDisplay`
  (whose re-stamp guard reads the element).
- **The run console keeps its own history per view, because the server cannot give it back** (it ships only the last 200
  lines of the *whole* run). `consoleViews` holds `{seen, lines}` per view (`'all'` + each workflow id), every view is fed
  on every poll, `switchWfTab` repaints without moving the cursor.
- **The console is ALSO persisted per run (`run_store.run_log`), as a pure side effect that may never move the live
  console.** `_push_log` (runtime/state.py) writes through `RunLogWriter` via `set_log_sink`, armed only inside a run's
  window (flush every 200 lines + on error + once in the worker's `finally`). The durable viewer
  (`/api/runs/<id>/log(.txt)`, `runLogViewer`) reads ONLY that table. **The reattach
  (`execution_state['logs']/_log_total/_wf_logs/_wf_log_total` + `?tail=5000`) must stay byte-identical with or without a
  sink** — a shifted total is a cursor that skips/repeats live lines after reload. `test_console_buffer.py` fails that
  invariant; it is the guarantee, not a nuisance test.
- **Every thread that logs must pin its own language:** `set_lang` is thread-local and a daemon starts fresh, so `run()`,
  the parallel pool wrapper and **both cookie workers** set the request's language first. A test asserting console text
  asserts on the reason, not a pasted sentence.
- **One failure, one line:** `LogBufferHandler` forwards every `logger.*` into the buffer (format is the message alone, so
  a traceback still goes only to the file), so `logger.exception(...)` **and** a matching `add_log` print twice. Keep the
  logger call for the file; let `wf.node_failed` be the single attributed console line.
- **A line printed by a side effect that runs per PAGE LOAD is noise by construction.** App boot fires `POST
  /api/data/clear` to sweep orphaned files, and that route logged 「清理孤立文件 0 个，保留 0 个…」 unconditionally — after
  ~80 page loads the console test's 3 stubbed lines were buried under eighty and the device tier failed on CI while
  passing here. The rule (from `services/runs/housekeeping.py`): **silence is the normal case, say something only when
  something went**; manual 清理 keeps its toast from the response. A test that opens a page is a writer of the console.
  Pinned: `tests/api/test_data_api.py::TestClear` (空扫描不得留行; 删 1 个点名 1 个).
- **A job a page starts by itself must be awaitable, or it races everything after it.** `workflow.reconnectConsole()`
  reads `/api/workflow/status?tail=` during boot; a test that emptied `#console-output` then read it was reading the
  *server's* history. Two fixes: the method keeps its in-flight promise (`_reconnect`, released in `finally`) — which also
  stops boot and a 「立即执行」 fire from each fetching/each opening/each shouting 「已重新连接控制台」 (`harness_console.mjs`
  measures `asked: 1`/`toasts: 1`; against a non-sharing gate reports `2`/`2`); and the tier gained
  `_settle_console_replay(driver)` called **before** any clear.
- **Anything that chooses data, cost or a name is refused BY NAME, never guessed** (mode/`select`/missing column via
  `data_analysis.validate_step`, analyzer `method`/`mode` via `app.enum_param`), and refusals `raise` rather than return
  `[]`. **Read a switch, never compare it** (`core/refs.as_bool`; blank = default).
- **`_push_log` stores one entry per physical line** — the total advances by lines, not `add_log` calls (a multi-line
  driver `Message:` rendered as several rows and the browser cursor skipped/repeated).
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook:** no "Executing node…"/
  "Node…completed" line, but progress counters still count them and every fact still prints (with `node_label`, or a
  silenced node that fails is undiagnosable).
- Run-gating lives in `execute()` → `_cookieGateBeforeRun`. **`execute()` asks no cookie question of its own** — its
  2026-09 shape was a `/api/cookies/status` loop refusing on each platform's *default-account* boolean, which blocked a
  node on a saved named account and blocked wechat entirely. The probe is `cookie_preflight_before_run` per platform
  **whose mode needs a session** (`Mode.needs_session`; weibo 热搜 answers anonymously, wechat has no session to want);
  a login wall **refuses** (no "run anyway"); 「无法核对」 (timeout/captcha/busy) **never blocks**.
  - **A named cookie and a named profile belong together:** one account = one `data/cookies/<platform>@<account>.json`
    *and* one `chrome_profile/<platform>/<account>`.
  - **A node's 账号 is a session question asked once:** `engine.workflow._account_session_errors` refuses when
    `sessions.preflight.has_session_to_test` finds neither that account's cookie file *nor* a carrying profile — blank
    included, because blank IS an account (默认账号), not a wildcard.
  - **Every account has one name and one spelling:** the default is `default` (never blank in the box), folded at the ONE
    point `CookieManager.key`/`path_segment` (`''`⇄`default`, lowercase always — `Work` and `work` are the same session on
    a case-insensitive FS) so `sessions.profiles`, the preflight cache and the JS box route through it. The candidate list
    and a new node's preselection are both `CookieManager.accounts_in_order`.
  - **A new settings key needs all four:** the bool branch in `settings_store.save_settings`, both browser catalogues, and
    the `AppSettings` wiring.

## 定时任务 (scheduler) — why the clock is narrow

- **The clock is one thread, started from exactly one place.** Flask's reloader imports the module twice, so a
  `scheduler.start()` at import scope gives **two clocks ticking the same `data/schedules.json`** (a canvas that spends
  accounts gets crawled twice). Hence `start()` only under `__main__` and only when `not debug or
  os.environ.get('WERKZEUG_RUN_MAIN') == 'true'`; `start`/`stop` are idempotent.
- **A fire is the same start as a manual Run, because `begin_run` owns the whole start path.** `scheduling` may not import
  `app` (the Blueprint imports it), so app.py installs two seams at import
  (`set_run_starter(engine.run_schedule.start_scheduled_run)`,
  `set_canvas_source(engine.run_schedule.scheduled_canvas)` — both moved out of `engine.run` on 2026-10-29).
  `start_scheduled_run` then calls `begin_run` (the *only* path), which is what makes a busy server **queue** the fire.
  The scheduler is refused by name (`sched.notWired`) when nothing was wired.
- **A crash in the starter is not a refusal.** `_fire` records `error` (traceback to the log file) for an exception and
  `refused` for an executor saying no — "my canvas needs a model" vs "something is broken"; the `except` is per-task so the
  tick continues for others.
- **One rule about a canvas, asked three times, from one function.** `engine.run_schedule.scheduled_canvas` wraps the
  same `_workflow_needs_llm` the executor uses; the panel's `runnable`/`why_not`, the save-time and fire-time checks all
  go through it. A scheduled canvas may not need a model at all (a cloud box has neither Ollama nor a person), so it is
  refused **while being chosen** in the picker's own label, not in a history row nobody reads.
- **A missed moment is recorded, never replayed.** `note_missed()` runs once before the thread starts; `_reanchor()`
  re-arms from *now*; **at most one missed event per restart** (`missed.count` accumulates across restarts — what 「错过 N
  次」 reads). Accounting goes to the task's own `last_run`/`history` (20 entries); only a run that really started gets one
  console line, language pinned from the task (`set_lang` in `_fire`).
- **The browser may not hold a second opinion about time or state.** `next_run_local`/`last_run_local` are rendered
  server-side in the *task's* zone, and the trigger sentence comes from the store's `describe_trigger`; a status token the
  catalogue doesn't know shows **as itself**. `schedules.js` has no time arithmetic and no status vocabulary;
  `tests/unit/frontend/test_frontend_schedules.py` drives the real file under node.
- **The dock list and the dock matrix are two places, and both are needed.** `DOCKED_PANELS` is the list
  `closeDockedPanels` walks (a panel missing stacks on the console); `tests/frontend/harness_panels.mjs` proves "opening
  any one closes the others AND clears the stale inline height". Adding `schedules-panel` surfaced that `cookies-panel` had
  never been in the harness — hence `test_the_dock_matrix_in_the_shared_harness_still_covers_every_panel`.
- **cron is hand-rolled on purpose (stdlib `zoneinfo`, zero new deps), with `next_after()` strictly *after* the given
  moment.** Edges pinned in `tests/unit/scheduling/test_cron.py`: a spring-forward hour that doesn't exist is **skipped
  whole**, an autumn ambiguous hour runs on its **first** pass (`fold=0`), `0` and `7` are both Sunday, day-of-month ×
  day-of-week combine POSIX-style (OR), and an expression that can never fire (`0 0 30 2 *`) is refused **at save time**
  by name.

## 桌面打包 / Desktop packaging

- **A double-clicked exe can only be accepted by double-clicking it.** Measured 2026-10-24: the shipped `CaiXiHui.exe`
  flashed a console and exited; my verification had used `CIXI_NO_BROWSER=1` + an explicit `CRAWLER_DATA_ROOT` inside the
  workspace — precisely the two things that hid the failing line (`main()`'s first `root.mkdir()` on
  `%APPDATA%\CaiXiHui` raising `PermissionError [WinError 5]`).
- **Windows destroys the console when the process exits**, so for a frozen entry a printed error is invisible. Every exit
  path must (a) block in a `MessageBoxW`, (b) append the traceback to `startup_error.log` (data root → exe folder →
  `%LOCALAPPDATA%` → temp, in turn). `input('按回车…')` is not visibility — it covered two paths and `suppress` swallowed the
  EOFError on a redirected console.
- **A location is probed, never declared.** `_root_is_writable()` creates the dir and actually writes+removes a probe
  file; on refusal the next candidate is taken with the OS's words printed. `mkdir` alone is not the test (a protected
  folder can accept a dir and refuse the first file). Antivirus / Controlled Folder Access denying an unsigned exe write
  access to `Roaming` is the scenario.
- **An isolation root must not fall through.** `CRAWLER_DATA_ROOT` is the ONLY candidate when set; a refusal there is a
  named startup refusal, not a fallback (silently joining the shared AppData root would let a smoke run's
  `promote_stale_runs()` settle the user's live run). The fallback chain exists for the double-click default only.
- **The mutex is per data root.** "One server per data root" is the app's rule, so the mutex name hashes the root; a
  root-blind name let an installed copy refuse a portable one.
- **A failure reporter must not be able to fail first.** `fail_loudly` files the log and shows the dialog BEFORE printing:
  on a redirected console with a non-UTF codepage the first Chinese char raises `UnicodeEncodeError`, losing both file and
  dialog. `_print_safe` degrades to `sys.stdout.buffer`, never back through the stream that threw.
- **The acceptance run is part of the artifact.** Double-clicking `dist/CaiXiHui/CaiXiHui.exe` writes `data/`, `logs/`,
  `mplconfig/`, `instance.json` into the folder the zip/installer pack; `prune_dist.py` clears them before compression.
- **Dialogs are frozen-only.** A source run has a live terminal, so `_message_box()` returns unless `is_frozen()`; the stub
  in `tests/unit/desktop/test_desktop_packaging.py` asserts the `MessageBoxW` call really happens when frozen (an
  early-return test alone kept passing after the dialog call was deleted).
- **pip hangs on a restricted workspace at `Looking in indexes`, network fine.** It unpacks into `%TEMP%` and caches under
  `%LOCALAPPDATA%\pip`, both denied. Fix in `desktop/build_windows.ps1`: `TMP`/`TEMP`/`TMPDIR` → `build/tmp` +
  `--no-cache-dir`.
- **A UTF-8 Chinese string in a `.ps1` can stop the build from starting.** Windows PowerShell 5.1 reads a BOM-less script
  in the machine's ANSI codepage, so a `Write-Host '中文…'` literal arrives as GBK bytes and one looks like a quote
  terminator → `字符串缺少终止符` on a line far from the real one (a parse error that still looked like success).
  `desktop/build_windows.ps1` is ASCII-only (pinned by `test_the_files_other_tools_parse_are_pure_ascii`).
- **The same locale trap eats `requirements-*.txt`, and one em dash is enough.** pip's `auto_decode` uses the preferred
  encoding and honours UTF-8 only with a BOM, so a Chinese comment or a `—` → `UnicodeDecodeError: 'gbk'`. The test checks
  raw bytes of the ps1, both `desktop/requirements-*.txt` and the two root requirement files.
- **UPX: do the pass yourself, never trust a packer that skips quietly.** PyInstaller's `upx=True` compresses nothing when
  it can't find the tool and only prints it in a scroll-past line. `desktop/compress_dist.py` runs with `upx --best
  --force`, treats a missing `upx` on PATH as a **build failure by name**, verifies each output with `upx -t`, restores
  unverifiable files, skips `UPX!`-marked files, prints the byte delta. Two measured details: UPX 5.0.2 **rejects**
  `--no-version-info` (exit 1), and `--best` costs ~30 s on the 20 MB OpenBLAS DLL (pass parallel across 307 PE files).
- **Dead payload is only dead when you can name the reader.** Dropped by `prune_dist.py` (measured): `jieba/lac_small`
  (13 MB, reachable only via `cut(..., use_paddle=True)`); snownlp's Python-2 marshals `seg.marshal`/`tag.marshal`/
  `sentiment.marshal` (on 3.11 the extension-less copies are read by nothing while the `.3` files are the models — a 3-char
  suffix decides whether the sentiment fallback boots); and the training corpora. NOT droppable: `scipy/spatial` +
  `scipy/interpolate` (reached via `scipy.stats`/`sklearn.cluster._optics`) and matplotlib's DejaVu fonts.
- **A file's extension is a promise to some readers and a suggestion to others.** `backend/static/icon.ico` was the app's
  PNG renamed: browser content-sniffs it (favicon looked right), PyInstaller copied invalid bytes printing "Copying icon",
  Inno Setup refused to compile (`Resource update error: Icon file is invalid`) only *after* the folder/zip took ten
  minutes. Fix: `tools/build_icon.py` generates a real ICO (16/24/32/48/64/128/256),
  `test_desktop_packaging.py::TestTheIconIsWhatItsNameSays` parses every frame offset, and the build checks the header
  bytes **before** the expensive steps.
- **A background build's exit code is only as trustworthy as its wrapper.** A failed-on-icon run reported *completed
  (exit code 0)* because the command ended with an `echo`; the log's own last line was `powershell exit=1`. Launch the
  build as the **last** thing the shell does and read the log's own summary lines.
- **A packer's warning is a switch you think is on.** Inno Setup 7 prints `LZMAUseSeparateProcess is obsolete and ignored`
  — same class as a tool-ignored option: an option the tool ignores is documentation, not configuration; `installer.iss` is
  now verified by compiling it.
- **A packer must collect by the file tree, not by a static-import graph the build's own interpreter can't see.**
  `hiddenimports += collect_submodules(pkg)` was called before `pathex=[BACKEND]` reached `Analysis`, so the spec's
  interpreter couldn't see `backend/` and `collect_submodules('nodes')` returned an **empty list** — `nodes.executors`
  (reached only by `importlib.import_module('nodes.executors')`) meant **zero plugins shipped**, and the exe died on
  launch `No module named 'nodes.executors'`. This held for every build (the 2026-10-28 exe was equally dead). Fix:
  `desktop/frozen_modules.py` (pure `pathlib`, no imports) replaces `collect_submodules`; both test and build read the same
  function; measured **314** first-party modules. Pinned: `tests/unit/desktop/test_desktop_packaging.py` (each `.py` in a
  named package is collected; `nodes.executors`/`runtime.gate`/`engine.run_logs`/`engine.run_schedule` present;
  `frozen_modules` imports no first-party or PyInstaller; removing `nodes` really drops `nodes.executors`).

## Lint 标准 / Lint standards

### pylint is three tiers, because one honest answer does not fit three kinds of file

Product code takes `.pylintrc`; `tests/` takes `.pylintrc.tests`; the `backend/test_*.py` probes take
`.pylintrc.probes`. **Nested config files are ignored by pylint** (measured: a subdir `.pylintrc` did not apply), so each
tier is its own invocation with an explicit `--rcfile`. `tests/unit/gates/test_lint_gate.py` pins the exemptions' shape
(pytest idioms not in the product list, `C0413` not either, `exclude-protected` a named member not a message). The
"lint-gate is only a gate if it linted everything" bullets follow; the whole tier is its own grep anchor.

- **`pylint packaging` was never our folder — the directory is `desktop/` for that reason.** A bare target `packaging`
  resolved to the PyPA distribution in site-packages, linting a third-party library over our files. Two fixes: the workflow
  lists FILES and refuses an empty list, and no project directory shares a name with an installed distribution.
- **Why the test tree is exempt from exactly three messages.** `W0621` (a fixture is requested BY NAME so test and
  module-level fixture must share it), `W0613` (an autouse/requested fixture's argument IS the use), `W0212` (half the
  suite questions the public surface). Those three remain findings in product code.
- **`global` in product code is a seam, not a smell — where it is one.** All 14 sites are state a caller rebinds on
  purpose (store singletons, `settings_store` cache, `state.set_log_sink`, the scheduler's starter/counters). `W0603` is
  exempted in `.pylintrc`/`.pylintrc.probes` with that written down, NOT in `.pylintrc.tests`.
- **A checker's false positive is usually an imprecise type.** `_RUN_QUEUE: list = []` made every subscript `E1136`;
  naming the element (`QueueEntry`) cleared ten. `report_service`'s `E1135` survived a `TypedDict` (traced to a `None`
  literal); a frozen `@dataclass` is readable. `_abort = None` produced `E1102`; annotating `Callable[[], bool] | None` and
  reading `self._abort` removed both it and the defensive `getattr`. `sys.stdout._original` became `unwrap()` on the tee.
- **`webdriver.Chrome` is invisible to checkers** (selenium's exports are lazy `__getattr__`). Importing the full
  `...chrome.webdriver.WebDriver` name removed the only inline `# pylint: disable` in the crawler core — and **moved a test
  seam**: `test_driver_options.py` patched `base_module.webdriver.Chrome` (11 ERROR, 53 passed hid them). Patch the name
  the module constructs; read the whole summary, not the pass count.
- **`W1203` cannot be fixed by lazy `%` here.** `test_i18n.py::TestNoHardcodedConsoleText` counts `%s` tokens as
  untranslated prose and `t(key) + ': %s'` only trades the finding for `W1201`; the answer is a named catalogue slot in
  both languages.
- **Unused arguments find real bugs.** `sessions.profiles.status(size=False)` was documented twice as skipping the walk and
  never read the flag — `/api/cookies/status` re-walked every profile (measured 236 MB) once per account row.
- **The formatting hook eats an import added a hair too early OR too late.** `ruff check --fix` deletes an unused import at
  that moment (`import math` one edit early silently disappears → `F821`); and moving an import into its using function
  while a module-level twin still existed made the local name a redefinition (`F811` autofix deleted the new one, six
  suites died `NameError`). Land use and import in the same edit; delete the old binding first; grep the symbol before
  believing the move.

### A lint gate is only a gate if it linted everything

- **只 lint 改动文件 = 没 lint.** Running pylint over just touched files let three *already committed* violations survive
  (a `W0108` lambda, a `W0212` reaching `bridge._RUNNABLE_STATES`, a `W0201` stub attr), each behind a "both tiers 10.00/10"
  claim from a partial target list. The gate is the whole product tree and the whole test tree (every `tests/**/*.py`, not
  only `test_*.py` — conftest and helpers too), every time.
- **The target list must be absolute, forward-slashed, free of `\r`.** A relative list makes `tests/` helpers report false
  `E0401` (they import each other by a path the relative run lacks); backslashes from Git Bash eat into `backendapp.py`;
  Windows `write_text` writes CRLF so every arg ends `\r` and all files report `F0001`. Generate absolute with `/`, invoke
  via `tr -d '\r'` (reproduction: `build/make_lint_lists.py`, still present).
- **PowerShell: `@( (Get-ChildItem a), (Get-ChildItem b) ) | ForEach-Object FullName` lints NOTHING.** Measured on the
  first CI run carrying the pylint steps (run 40450524569, 0.7 s): the comma builds an array of **two arrays**,
  `ForEach-Object -MemberName` does not member-enumerate it, `$t.Count`=2 with empty items, pylint got two blank args and
  printed `No files to lint: exiting.` — and `if (-not $targets)` did **not** fire (array-of-empties is truthy). The
  shape that works: statements inside `@()` + `ForEach-Object { $_.FullName }`; both CI steps print `linting NNN files`.
  Pinned: `test_lint_gate.py::TestTheStandards::test_ci_runs_the_two_tiers_it_can_and_says_why_not_the_third`.
- **A gate whose machine differs from the runner's proves less than it says.** The product tier read 10.00/10 for weeks
  here and reported **19 × `E0401`** the first CI run (`torch`/`transformers`/`onnx`/`sentence_transformers`/`bertopic`/
  `uiautomation` — all in `requirements-optional.txt`, all imported inside a probing guard, all absent on a hosted runner).
  Fix: `ignored-modules=` in `.pylintrc` **by name, never by switching `E0401` off**; `test_lint_gate.py` pins both
  directions (nothing exempted that isn't a declared optional, nothing the product imports that's left out).
- **A byte pin and `* text=auto` cannot coexist.** `vendor/echarts.min.js` is SHA-256-pinned, but the repo's
  `* text=auto eol=lf` converted its 45 CRLF pairs at commit (upstream really ships those CRLFs), so the blob in git was a
  **different file** than reviewed — CI checked out the blob and failed the pin, this box read its own copy and passed.
  Fixed by `backend/static/vendor/** -text` + `git add --renormalize`, guarded by
  `test_vendored_assets.TestThePinnedBytesAreTheStoredBytes` (`git check-attr text` + hash `git show :<path>`).
  **A check reading the working copy proves nothing about what is stored.**
- **A stub that fakes one backend silently assumes the machine picks that backend.** The three bert analyzer suites
  installed a fake `transformers.pipeline` and were green for weeks (this box has torch); CI installs
  `requirements.txt` (onnxruntime+tokenizers) and never torch, so `bert_runtime()` answered `'onnx'` and the product
  correctly refused a non-directory model name — 13 cases reddened. The fix is not a skip: the case states its runtime
  (`monkeypatch bert_runtime → 'torch'`). Same lesson, second instance: 红果's "missing player refused by name" dropped the
  stack seam, so it only tested the player where mitmproxy/uiautomation are installed; now the case says the stack is
  present, plus a second case pinning the stack refusal (naming the two packages, NOT blaming the player).
- **`subprocess.run` without `check=` is a finding worth taking literally.** W1510 sent two cases to exit 4. `check=False`
  is the honest spelling when the test asserts on `returncode` itself; in `test_boot_import_budget` it turned an
  `AttributeError: 'NoneType' has no attribute 'strip'` (seen once on the runner, unreproducible here) into an assertion
  carrying the child's return code and stderr. When a failure can't be reproduced, make it name itself: the next run's
  decisive measurement was `CompletedProcess(returncode=0, stderr='', stdout=None)` — the child ran cleanly, so the **pipe**
  differed. **A test should read its answer through the transport the claim depends on**, and "which modules did `import
  app` load" does not depend on a captured stdout: the child writes its report to a `tmp_path` file. Harness facts are only
  knowable from the harness — this took two CI runs.
- **Fixing one step of a pipeline does not prove the next ran.** Once both pylint tiers passed on the runner, CI reached
  the **fast tier for the first time in this repo's history** and reported **27 failures** all green on the writing box.
  Five shapes: a stub patching the torch pipeline while the product loads ONNX (13 × `TestBertMode`); a byte-SHA pin on a
  vendored `.js` checkout re-writes line endings for; a `main()` that refuses when `upx` isn't on PATH while its test
  asserts exit 0; a subprocess whose `stdout` came back `None`; a refusal test reading a machine-local path. Rule: **a
  green step nobody has seen run is a claim, not a gate** — each fixed by making the *test ask the machine*.
- **A wrapper that reports the exit code is part of the gate.** A background command ending in `echo done`, or piping the
  checker through `tail`, reports 0 even when the checker failed; the measured exit must be the shell's last one and the
  evidence the checker's own summary line. Same trap one layer up: a redirect to a nonexistent dir (`build/fast.log` before
  `mkdir build`) never runs the suite.

## Cross-platform / Win・Linux・macOS 三套系统

Developed on Windows, deployed on a **Linux cloud server** (`CRAWLER_CLOUD=1`), macOS in scope. Three read-only audits
produced this list; every entry was a real defect on at least one platform, not a style preference. Rules in AGENTS.md
「Cross-platform」; evidence here.

- **Chrome discovery was a Windows-only table.** `chrome_candidates` built `%PROGRAMFILES%…chrome.exe` and nothing else,
  so a server with `/usr/bin/chromium` answered 「本机没有可用的 Chrome」; the Docker image worked **only** because it
  exports `CHROME_BIN`. Tables are now per-OS (`CHROME_PATHS`/`CHROME_PATH_NAMES`/`XELATEX_PATHS`/`CTEX_FONTSET` in
  `core/machine.py`), and a test asserts each is indexed by **exactly** the three platforms.
- **Ask the target OS for its separators, not the host.** `Path('/Users/x')/'Applications'` renders backslashes on a
  Windows test asking about macOS, and `os.pathsep` splits a Linux `PATH` wrong. Build candidates with `ntpath`/`posixpath`
  chosen by the *requested* system.
- **Matplotlib's CJK stack named only Windows fonts.** It resolved to `DejaVu Sans` (every Han char a box); the image
  installs `fonts-noto-cjk` (**Noto Sans CJK SC**) and `fonts-wqy-zenhei` (**WenQuanYi Zen Hei** — not "Micro Hei").
  Windows names stay first so a desktop's answer doesn't move.
- **A remedy sentence is a different sentence per OS.** Telling a Linux user to open the MiKTeX console is advice nobody can
  follow; hence `deps.<family>.<platform>` keys chosen by `core.machine.remedy` — a **computed** key, so the contract walks
  the value universe (`REMEDY_PREFIXES × REMEDY_PLATFORMS × both languages`).
- **仿宋 (FangSong) is a Windows font.** Every paper figure asked `\setCJKmainfont{FangSong}`; on TeX Live the whole PDF
  feature died 「The font "FangSong" cannot be found」. Off Windows the ctex line carries that OS's font set
  (`fontset=fandol`/`macnew`) and no `\setCJK` line; the emitted comment names the family actually used. Windows keeps its
  three lines byte-for-byte (26/26 compiles).
- **`taskkill` under `contextlib.suppress(Exception)` also swallowed the line that marked the session dead.** On Linux:
  nothing killed, `DeadDriver()` never assigned, console read as stopped, and the next crawl waited `PROFILE_LOCK_TIMEOUT`
  (900 s) for a profile a live Chrome held. Off Windows the reap is `os.kill(SIGKILL)` with the driver's **direct children
  first** (field 4 of `/proc/<pid>/stat`). Two facts: Windows' `signal` has **no `SIGKILL`**, and `os.killpg` is unusable
  (chromedriver shares the server's process group).
- **A filename limit limits what the OS counts.** Windows counts characters per component; ext4/APFS count **UTF-8 bytes**
  (NAME_MAX 255). 100 Chinese chars are ~300 bytes. `sanitize_filename` cuts by both, byte budget 200 not 255 (the writer
  appends a suffix after the cap).
- **A container with no `LANG` has an ASCII stdout, and a Chinese log line dies inside the logging handler** (which
  swallows it, so the line vanishes). Not "always force UTF-8" (a Chinese cp936 console writes Han fine): if the stream
  can't encode a Han probe, reconfigure and say so; else only `errors='replace'`. The image sets `PYTHONUTF8=1`/
  `LANG=C.UTF-8`.
- **A Windows-only capability needs four answers, not one.** 红果评论 drives a desktop player through a proxy whose CA is
  installed into the Windows cert store. Refusing inside the node makes the user pay a run start for an answer known at
  load. So the matrix carries `requires='windows_desktop'`; `/api/capabilities` answers whether THIS machine meets it;
  `validate` refuses before run; the panel lists the option **disabled with the reason named** and hides the desktop-only
  rows through `html[data-win-desktop]`; a missing verdict leaves everything visible. `requirement_met` is the one predicate.
- **`pip install -r requirements-optional.txt` was a Windows-only command.** `uiautomation` is a comtypes-based Windows
  sdist, so the optional stack couldn't install on a server; both harvest packages now carry `sys_platform == "win32"`. The
  other gap was `tzdata` (Windows and slim images have no system zoneinfo dir → `ZoneInfoNotFoundError`).
- **A deploy knob nobody reads is worse than none.** The Dockerfile exported `CHROMEDRIVER_PATH`; `core/config.py` reads
  `CIXI_DRIVER_PATH`. The image looked configured and was not.
- **Two tests were pinning a Windows spelling rather than an answer.** `test_lint_gate.py` required the literal
  `Get-ChildItem` (an ubuntu runner would fail the gate, not the code) and `test_browser_startup_refusals.py` named its
  fake driver `chromedriver.exe`. `test_hongguo_harvest.py` faked `sys.platform='win32'` and never asked what the other
  branch does; it now refuses `linux`, `darwin` and a cloud Windows host explicitly.
- **Two `replace('\\', '/')` calls were kept, on purpose** (`api/studio.py::save-pdf` folds both separators before
  `basename` so a Windows-style path is refused on Linux exactly as a POSIX one is on Windows; `analyzers/sentiment.py::
  resolve_bert_model` folds so a registry path typed on Windows still resolves). An audit called these mangling; reading
  each route says otherwise.
- **The scan that keeps the rule has to be able to fire without crying.** A `[A-Za-z]:\` pattern matched the `\s` of every
  regex in `analyzers/` and flagged 20 unrelated lines; it now looks for the artifacts that break Linux (install roots,
  `taskkill`, `ctypes.windll`/`winreg`/`msvcrt`, quoted `.exe`), skips docstrings/trailing comments, and re-asserts every
  exempted file still holds an artifact. An allowlist entry that exempts nothing is a lie waiting to be read.
- **A refusal sentence that names a Windows file is itself a Windows fact.** `crawl.chromeMissing` told every system to
  point at 「它的 chrome.exe」 and `disguise_headless` sent `'platform': 'Win32'` — both survived because the zh/en parity
  check compares the two languages to *each other*. Now the executable name comes from `machine.chrome_executable_name()`
  (reading the same `CHROME_PATH_NAMES` the probe uses) and the platform token from `NAVIGATOR_PLATFORMS`. Deleting
  `i18n.py` from `WINDOWS_TABLES` is what makes it stick (`test_each_exempted_file_actually_holds_a_windows_artifact`).
- **What this box cannot prove.** No Linux runtime here (no docker/WSL, user's decision), so these landed as code +
  platform-independent tests. **Starting on Linux/macOS is an unverified surface**: a real-container crawl, a `fandol`
  compile, the snap/app-bundle Chrome lookups are reasoned and tested by substitution. The Linux packages are in README/
  `docs/config.md`; run them once on the server and report what differs.

## The second crawl backend (CatBus) — why the boundary is where it is

The **imperatives** (the must-obey crawl rules) live only in `docs/crawler_rules.md` → 「第二采集后端 / The second crawl
backend (CatBus)」; read that before touching CatBus. What is kept here is the *why-evidence* AGENTS points at:

- **Why a subprocess, not a port.** CatBus is a Node program already speaking this app's row shape: one JSONL row per
  record on stdout, one summary envelope on last stderr line, exit codes classifying failure (1 unclassified / 2
  usage-unsupported / 3 login / 4 not-implemented / 5 risk control / 6 network / 7 upstream), and a `capabilities`
  command answering 平台×模式 machine-readably. Porting eleven platform clients to Python would be a second implementation
  to keep in step; the boundary is one file (`services/ingest/catbus.py`).
- **Why the manifest is read, never copied.** A local "what CatBus supports" table would be the second opinion the
  frontend rule exists to stop; `probe()` runs `capabilities` (cached, `PROBE_TTL`) and `columns_for`/`identity_for`/
  `mode_state` answer out of that document.
- **Streaming was an upstream change, paid for first.** The adapter printed every row after the run finished while this app
  stores one row per transaction — 停止 mid-crawl would have thrown away everything bought; the adapter now writes each row
  as produced (CatBus commit `4528af3`).
- **`windowsHide` is not a `Popen` keyword.** `windowsHide=True` raised `TypeError` (caught only because a test drove a
  real child). The Windows answer is `creationflags=CREATE_NO_WINDOW`, which POSIX `subprocess` doesn't define — so it
  lives in `core/procs.popen_kwargs()` (Windows: the flag; Linux/macOS: `{}`), tested per OS. A comment crawl starts one
  child per link, so the missing flag is a black window flashing once per article.
- **A piped Python child writes the ANSI code page.** The real-child test printed `{"标题": …}` and the parent read mojibake
  then `UnicodeEncodeError: surrogates not allowed`. The bridge writes/reads **bytes** and decodes UTF-8 itself; parameters
  travel as one UTF-8 stdin document, never argv (a code page rewrites a Chinese keyword; a long link list hits a command
  length limit).
- **Two backends, two logins, two answer keys.** The pre-run gate keys a verdict by `platform[@account]`; a CatBus `default`
  and a cookie `default` are two accounts on two systems, so `entry_key` gains a `#catbus` suffix **only** for a
  non-browser backend (every key this app ever produced still spells the same), and the adapter's verdict is deliberately
  not cached. `login_wall` stays False (the executor's reading would print cookie/风控 advice about a session this crawl
  doesn't have). **Not yet verified on a real site** — no CatBus account on this box, so the row mapping/`--raw` shapes/
  partial accounting are tested against the adapter's documented contract and a stand-in process.

## 按主题的测量记录 / Topic measurements (appendix)

> Undated per-topic measurement records, compressed to rule + number + pinning test. The crawl/analysis facts are here;
> the **rules** are in AGENTS.md and the crawl **imperatives** in `docs/crawler_rules.md`.

### 三维能力模型 / Platform × engine × function

- **A computed label key is an audit blind spot, again.** CatBus's manifest can grow modes without a Python change, so
  labels must be a literal table (`CATBUS_MODE_LABELS`) and a contract test must walk the *manifest's* key set (asking only
  keys already in the table proves nothing) — the same mistake in three earlier places (node types, biblio columns, op
  names). Pinned: `tests/unit/test_catbus_capability_dimension.py`.
- **A function the engine cannot run is still shown, greyed and named.** Removing it paints a stored value as option #0 and
  makes the panel lie; the payload carries `engines` per platform, `engines`+`cells` per function, and the adapter's
  `reason` prose. The frontend holds no list.
- **A seeded default is not a condition the user chose.** The canvas seeds field defaults onto a new node, so
  `board=popular` exists on a posts node that never asked for a board — refusing an unconsumed parameter compares to the
  declared default first, or every CatBus node dies on a field it never filled.
- **Read the manifest, never a list compiled beside it.** The adapter derives read modes from the platform registry
  (`write()`-declared commands carry `mutating` and are mechanically excluded); the one deliberate exception is `msg *`
  (private messages), excluded as a resource with the reason in code.

### 启动路径与 BERT 运行时 / Boot path and BERT runtimes

- **Process start is a budget spent on libraries no request asked for.** `python -X importtime -c "import app"` = **9.2 s**,
  **5.4 s** of it a single top-level `from sklearn.ensemble import IsolationForest` in `analyzers/anomaly.py`; moving the
  heavy third-party imports into their using functions brought it to **2.07 s**. The `analyzers` barrel is deliberately
  untouched (four seams read it at class level). Pinned: `tests/unit/foundation/test_boot_import_budget.py`.
- **Pin a budget with a module census, never a stopwatch.** The test walks module bodies with `ast` and imports `app` in a
  fresh subprocess to read `sys.modules` (catches transitive leakage); a wall-clock assertion would fail a slow runner and
  pass a fast one while proving nothing.
- **Two frontend-adjacent traps in the same move:** `services/biblio/cluster.py`'s return annotation
  `tuple[TfidfVectorizer, …]` is evaluated at `def` time, so quote it AND keep it visible (`if TYPE_CHECKING:`); in
  `services/charts/visualizer.py`, `matplotlib.use('Agg')` + the CJK `rcParams` block must travel **with** the import
  (splitting them gives a window or a figure of tofu).
- **A frozen app's ONNX export must be fed its mask, not let it build one.** Tracing transformers' `attention_mask`
  handling froze the padding branch: the fp32 graph answered up to **1.0 logit** differently depending on how the batch was
  padded (agreeing to 4e-07 unpadded). Fix: the graph takes `position_ids` + an additive `attention_mask_4d` as **inputs**;
  then max abs logit difference is **3.1e-06** over a 243-pad-cell batch. `attn_implementation='eager'` (sdpa's
  shape-dependent booleans bake) and `dynamo=False` are stated, not inherited.
- **`torch.onnx.export` leaves the module in training mode.** A verification pass right after ran BERT's 10% dropout: the
  "graph is wrong" number changed (0.14/0.35/0.99) while the graph was stable to 3e-07. Call `model.eval()` again first.
- **Quantisation is judged on decisions, not distance.** int8 holds macro-F1 within noise but flips **6.7–14.2%** of
  labelled rows (loss shows on near-ties, where the label is the answer); fp16 flipped none and costs 195 MB vs int8's
  98 MB, so the pack ships fp16.
- **A stub that invents an API ships an `AttributeError` in the packaged app.** The `tokenizers` crate exposes `type_ids`;
  the fake said `token_type_ids` and every stubbed case stayed green until the real graph ran. Pinned:
  `tests/unit/ml/test_bert_onnx_real_crate.py` (uses the installed crate, fakes only the inference session).

### 文献导入与真实导出件 / Bibliographic imports and real exports

- **A real export file is the only authority on what a source exports.** Everything below was measured by running the
  product's own readers over files in `samples/`, after doc-derived answers proved wrong three times (PubMed has no XML in
  the user's reach → the branch/slot/two keys deleted; the Lens file given was the **patent** collection, refused by name;
  "Scopus/Dimensions" names coded were the English UI's while the user's CSV arrives as `文献标题/年份/来源出版物名称/施引文献/
  参考文献`). A format nobody handed a file for is not a format the app may claim.
- **Measured, then fixed:** CSSCI writes 【关 键 词】/【期    刊】 (alignment spaces), names authors 来源作者, merges
  year+issue+pages into 【年代卷期】`2021,(2):146-155`, and numbers refs `1.` (not `[1]`, which the old gate assumed — so a
  real CSSCI file wasn't detected and 291 refs would have glued into one citation). Scopus/Dimensions/WoS names are
  per-field candidate lists via `header_has_groups`. WoS' Excel left `Cited References` empty for all 30 records — **name
  the FIELD a vendor doesn't offer, not the whole format** (keywords/categories/funding/usage still work).
- **A fixture may copy structure but never facts.** `samples/biblio/biblio_*_demo.*` reproduce tags/header/spacing/banner
  with values from a synthetic pool; real vendor files are gitignored. `FORMAT_CASES` carries `has_refs` per case.
- **Recognising a file ≠ reading it.** Detection answers "not mine" with a plain table, wrong for a file sharing column
  names. `services/biblio/formats/unsupported.py` holds refusals outside `FORMAT_SPECS`.
- **One vendor, two collections: the signature must require the differing columns.** Lens' patent download shares `Lens ID`
  and `Title` with Scholarly, so `lens.py` requires `Citing Works Count` **or** `Fields of Study`; `unsupported.lens_patents`
  still refuses the patent shape by name. Both directions tested.
- **A column existing ≠ usable.** Lens writes `References` as opaque record ids (of 24331 ids, 1002 resolve within the
  file), so `refs` is not declared; `Source Country` is where the *journal* sits, not the authors — filling 国家 with it
  answers a different question.
- **Vendors rename columns between versions: a measured file adds candidates, never replaces.** Scopus shipped the
  times-cited column as both `Citation count` and `Cited by`, article number as `Article number`/`Art. No.`, funding as
  `Funding Text 1`/`Funding Texts` — each rename silently zeroed one output column.
- **A claim the readers were never shown cannot stay in the guide.** "WoS reads Tab-delimited" had no `.tsv` measured and
  `accepted_extensions()` doesn't list one — removed. Re-measure after the user re-exports (`source.<id>.missing` sentences
  go stale silently).
- **A paper-ready graph label needs the browser's real rectangle, not a server-side guess.** `workflow.js` installs a
  `labelLayout` collision resolver at render time; fast suite pins its presence, browser probe drove overlaps to zero.
- **Avoiding other labels isn't the whole job — a label must stay out of the chrome.** The resolver now compares against a
  reserved band (`left/top/right/bottom`; legend `#5` once printed over 风险沟通); two follow-ups: a **percentage** inset is
  a length too (`'10%'`→NaN→0, clamp vanishes), and a **rotated** label can't be clamped (circular `rotateLabel:true` left
  a vertical term on the title). Pinned: `tests/frontend/harness_label_layout.mjs`.
- **A free graph is fitted into a SQUARE plot, and its labels follow the area.** ECharts fits `layout:'none'` into the
  series rect with one scale per axis (`View.calculateTransform`), so a 330×257 board tile drew a 900×900 layout 28% wider
  than tall — the "看板变形" the user reported. Measured 2026-10-30 on a real 3000-record AIGC run: preview 401×401, board
  cell 359×359, fullscreen 500×500, resized panel 670×670 after the fix. Three parts belong together: the spring layout is
  normalised with ONE scale (x/y separately stretched the picture at the data level), two invisible `_bbox_` anchors pin
  the data box to 50..950, and the browser sizes the rect itself (title above, legend only when ≥620px wide). Labels: the
  server solver's 1.5 px/unit assumption is wrong at any other size, so symbols/offsets scale with the square and a label
  budget (`side²×0.35/1800`, highest frequency first) keeps a 330px tile from becoming a white mound. ECharts 5.4.4 reads a
  `labelLayout` callback's x/y but **not** its `ignore`; returning `hideOverlap:true` + `priority` hands the losers to
  ECharts' own pass. A panel settles one frame after `init` (fullscreen host measured 1202→1260), hence `settleChart`.
  **The callback must return `dx`/`dy`, never absolute `x`/`y`:** an absolute label is pinned to the canvas and stayed
  behind when the graph was zoomed or panned (measured 2026-10-30 in the dashboard cell: the nodes moved, the text did
  not). An offset keeps the label attached to its node, so roam moves both. Pinned: `TestFreeGraphFitsTheSurface`, the
  backend layout/anchor cases and `harness_label_layout.mjs`.
- **A keyword chip belongs above its bubble, not beside it.** The cluster timeline's span line runs through the bubble
  centre, so a right-hand chip printed straight across the line joining two bubbles; `position:'top'` on both the series
  and each point's label (a point-level `position` overrides the series) clears it. Same-era points of one cluster are
  labelled once per (year, cluster) — coincident chips printed on each other.
- **A light label chip keeps dark ink in both themes.** The biblio builders paint `rgba(255,255,255,…)` chips in every
  theme; `patchOptionForTheme` recoloured their text to the theme foreground, so the dark theme printed white on white and
  the 关键词共现 graph read as blank boxes. The chip's own background decides the ink.
- **`ECHARTS_ONLY_TYPES` was a statement about matplotlib misread as one about LaTeX, switching paper output off.**
  `build_latex_outputs` skipped every type on it, so `emit_latex` was a no-op for word cloud/sankey/map/topic/network/all
  nine biblio views (a skipped add-on isn't an error, so nothing complained). The skip now asks its own question
  (`LATEX_UNBUILDABLE_TYPES`, exactly 模型一致率); `test_only_the_agreement_matrix_has_no_paper_twin` pins it.
- **"It compiled" ≠ "it fits the page" — and a standalone source can't tell you which.** Every figure is `standalone`, so
  TeX sizes paper to picture (a 46 cm ring became a 46 cm sheet, 22/22 PDFs "fine"); pasted into A4 it ran off the edge.
  Evidence is `grep -c Overfull` on the log plus reading rendered pages (first paper build: a page holding only the heading
  「图表」; a table 2.6 cm past the bottom — both "successfully"). Three attempts, three failures.
- **A layout whose size grows with the data is sized against the page, not the unit.** The ring radius is `0.46 × nodes`
  but the tikz unit stayed 1 cm; `GRAPH_BOX_CM` sets the coordinate scale after paying for labels (deliberately wide —
  under-estimating overflows). What it drops is printed ("已省略 N 个会互相遮盖的节点标签") — silent thinning is a figure
  that lies about the corpus.
- **A `tabular` cannot break, so a document pasting whole tables must cut them.** A 50-row table is ~26.5 cm of
  unbreakable box on a 24.6 cm block; `latex_report` re-cuts into page-sized blocks repeating the header, numbering only the
  first (`\caption*` for continuations). It only cuts bodies whose shape it recognises; `_split_table` returning `None` is
  the refusal.
- **A dual-map table lists nodes as well as links.** `output_shape=dual_map` emits rows where an empty 终点 means "this is a
  node"; both builders filtered those, so a journal reached by one overlay line wasn't drawn. Same-side edges are
  undirected too.
- **An axis label box wider than the preview panel is a name cut off, not wrapped.** Views reserve `axisLabel.width: 200`
  (right on a 1650 px canvas) but at the preview's 400 px the label measured 46 px LEFT of the canvas. Overlay views use
  96 px (≈10 CJK chars); browser tier measures both overlays at 400 px in zh and en.
- **The guide has to name the click, not the capability.** Dimensions writes a full-record CSV, a VOSviewer/CiteSpace
  network file and a BibTeX, and only the first is read; each source's steps say which to pick and avoid.
- **An automated export must land on the same parser as the upload it replaces.** CNKI's 「导出/参考文献」 is the site's
  own window (`manage/export.html`), and its on-screen list is only a 20-record preview — the full selection is the
  `CNKI-…txt` behind 「导出题录文件」. So the crawler 全选s each page (the site accumulates), downloads the file, strips
  the blank line CNKI writes between every field, and hands the records to `services.biblio.importer.parse_cnki` — one
  record shape, one `记录ID`, one set of "this format has no references" refusals. A second parser inside a crawler
  would let a crawled table and an uploaded file disagree about the same paper. **The public ``/dm8/API/GetExport``
  recipe is wrong for this version**: measured 2026-10-30 it answers `code=0 暂无数据` even logged in, while the menu →
  `manage/export.html` → 「导出题录文件」 path returned all 40 selected records. The way in is the profile: a fresh
  headless *and* a fresh visible Chrome both land on `/verify/home` (slider), so the cookie row is not optional
  (`docs/crawler_notes.md` → 中国知网). A download that never appears is carried into the console as a named refusal,
  never retried into a short table.

### Canvas history, layout baselines and reusable nodes

- **A file and a run are two serializations of the same canvas once a reusable node exists.** The file keeps the group
  (template, ordered input slots, collapsed flag, external wires); a run receives the expanded child graph.
  `canvas.toWorkflowJSON()` defaults to the RUN shape; save/autosave pass `{expandReusable:false}`.
- **A reusable node is ONE entry in `canvas.nodes`; its inside is DOM.** Children render inside the group's box from the
  stored template, never added to the model — one decision making undo snapshot one object and auto-layout frame the group,
  not the children. Inside cards are read-only.
- **Input order is the order wires enter the group; a count mismatch is refused** (`reusable.missingInputs`/`tooManyInputs`),
  not a guess.
- **A snapshot restore must be one undo step.** `canvas.batchHistory(fn)` suppresses per-change entries and records the net
  state once; `workflow.loadFromJSON(data,{history:'single'})` is the only snapshot-restore door.
- **A layout baseline is positions keyed by the saved workflow name; a missing baseline is a named refusal.** It runs the
  algorithm first then overlays saved x/y for matching ids; lives in `layout_baselines`, cleared when its snapshot is
  deleted. Falling back while the menu says 「按历史基准」 would make the menu lie.
- **An expanded group's stage needs its own width budget; only a real browser proves it.** The node width from stage+padding
  left the stage 2px wider than its border-box (SVG carried the stage's pixel width incl. 1px borders);
  `.reusable-stage-lines{width:100%;height:100%}` fixed overflow. Occlusion-vs-clipping (card under the fixed palette at
  x<190) is a rect comparison — neither the node stub nor a CSS-only read can tell them apart.
- **The expand-time auto-layout preference is presentation, not canvas state** (`localStorage` with the Style menu's other
  choices; never becomes an undo step or a file change).
- **A read-only inside needs an unwrap door; unwrap is a model operation, not a delete.** `ReusableNodes.unwrap` restores
  children at template positions/params, reconnects external wires by the same ordered slots, rewires outgoing from the
  single output, recorded through `batchHistory` as one undo step. A disabled group unwraps into disabled children.

### Project bundles / 项目包

- **A workflow file is not portable; its dataset references are.** The JSON names datasets by content id in
  `datasets.db`; copying only `workflows/` reopens every Upload node empty. The bundle carries the datasets/templates it can
  prove are referenced; import remaps every `dataset_id`/`template_id`. A bundle without a referenced dataset is refused at
  export.
- **Content identity means the importer cannot promise a new dataset id.** `DatasetStore` hashes rows, so identical bytes
  imported into a fresh store keep the same id; assert the pointer resolves, not "the id changed".
- **Import must never overwrite authored names** — a collision becomes the next free ` (2)`/` (3)`; rows may dedupe, names
  don't replace a file.
- **The manifest is a security boundary** — accepts only `workflows|datasets|templates/<NNN>.json`, refuses traversal names,
  checks per-file SHA-1, total size and entry count, validates all pieces before writing.
- **Never package runtime state by accident** — cookies, keys, logs, run records, model weights, the dataset DB are absent.

### Dataset merge / 数据集合并

- **A union is not an outer join.** Different column sets are refused with the extra/missing names (`pd.concat` would fill
  NaN and look complete until a chart reads the holes); reference order is the first selected dataset's.
- **Provenance is additive, never overwritten.** No `来源` → merge inserts one carrying each source's name; an existing
  `来源`'s per-row values are the user's and win. Source files untouched.
- **The result is an ordinary dataset** — via `DatasetStore.put`, so content identity/dedupe/row caps/preview apply.

### Vendored front-end assets and machine-level refusals

- **A CDN dependency fails as a blank, not an error.** `index.html` pulled ECharts/echarts-gl/wordcloud/Literata from CDNs
  and the China basemap from aliyun; with no network the figure area is simply empty — nothing throws. The assertion is
  over `performance.getEntriesByType('resource')` (every resource from the app's own origin), pinned by
  `tests/integration/test_ui_layout.py`.
- **Redistributed bytes get a hash pin, not a fetch.** `tools/vendor_frontend_assets.py` stores the SHA-256 it reviewed and
  refuses on mismatch; upgrading is one edit with a diff (URL and hash change together).
- **Google's `css2` declares the same file once per weight.** Naming a font file per `@font-face` shipped 42 files / 2 MB
  of what is 14 files / 556 KB — dedupe by URL. Sweep your own orphans (packaging copies all of `static/`): `referenced ==
  on disk`.
- **A basemap check asserts content, not parseability.** `china.json` still renders if a province disappears; losing
  Taiwan or the nine-dash line is a factual defect in a paper figure — name which region ("lost 台湾省" beats "33 of 34"),
  keep the file byte-for-byte as served.
- **Two answers to one machine-level question is the defect.** The launcher kept its own Chrome list, its own MiKTeX scan,
  and a hardcoded `127.0.0.1:11434`, so a user who set 「设置→Ollama 地址」 read "Ollama 未检测到" one line before the app
  answered from that daemon. Both call `core/machine.py` / `services/charts/pdf.find_xelatex()`.
- **A default pointing at a nonexistent file is a wrong default.** `Config.DRIVER_PATH` was
  `C:\Program Files\Google\Chrome\Application\chromedriver.exe`; almost nothing installs there. Blank means "let Selenium
  Manager fetch the driver matching the installed Chrome" (and why the driver isn't bundled: driver↔Chrome major pair 1:1).
  Clearing the field used to restore that broken default (the loop in `save_settings`).
- **`xelatex -interaction=batchmode` puts the reason in `main.log`, not stderr.** Reading only stderr gave "compilation
  failed" with ~300 near-empty chars about a missing `ctex.sty` the log names in line 1. Read the log before `rmtree`, and
  translate ``File `X.sty' not found``→name the package, `font "X" cannot be found`→name the font.
- **Chinese glyphs are a machine fact; silence about it is a paper full of boxes.** Matplotlib falls back per glyph since
  3.6, so what matters is whether *any* family carries Han; `visualizer.cjk_font()` asks `findfont(...,
  fallback_to_default=False)` and warns once per wording (cached per message, not a boolean — console language is
  thread-local). LaTeX asks `\setCJKmainfont{...}` by name, so a missing font is a compile error.
- **A refusal is only real if the exported figure carries it.** A map whose basemap didn't register was drawn anyway
  (ECharts paints an empty frame); `applyEchartsOption` now draws the refusal through the live instance, so the saved
  PNG/SVG contains the reason.
- **Tests may not inherit the machine's browser set.** `crawlers/core/browser.py::resolve_browser` refuses when Chrome is
  missing, so `tests/conftest.py` pins one answer (`machine_has_a_browser`) and tests *about* that refusal override it —
  don't patch `os.path.isfile` (process-wide). Existence questions get real files in `tmp_path` or paths simply absent.
- **The DOM stub already defines `echarts` (`harness_dom.mjs`)**, so a "library missing" scenario must `delete
  sandbox.echarts` (a first run recorded `hasLibrary: true` in a world built without one — measuring the stub). Same family
  as "a wrapper installed in another file isn't the function you load".
- **A docstring is input to other tests.** Adding ``from app import app`` to a `desktop_entry.py` comment broke a
  source-*order* contract (a `str.index()` position comparison), because the comment sat earlier in the file — product order
  was still right, so the comment was reworded rather than the test weakened.
