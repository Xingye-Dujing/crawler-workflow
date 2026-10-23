# agent_practices.md — the *why* behind each AGENTS.md rule

Every rule in `AGENTS.md` is stated bare there because that file is loaded into **every** session and must stay
small. The evidence for each rule — the measurement, the crash, the feature it once cost — lives here, and this file
is **not** auto-loaded. Read the matching section before rewriting, doubting, or "simplifying away" a rule: these
lessons were each paid for (a live re-run, a broken feature, a silently-skipped green tier, a blank page).

Grep by the bolded rule title; it is the same anchor used in `AGENTS.md`.

## Commands / deps — why the model-degradation rules exist

Code may never **silently** answer with a model other than the one it claims, because a column labeled `bert` that
actually ran `snownlp` is a fabricated result the report can't be audited against. Each sanctioned degradation therefore
PRINTS the method that actually ran. The two degradations that exist:

- a topic step's `method=auto` (resolved by `_resolve_topic_method`) picks **embedding** when the encoder imports and
  **LDA** when it does not;
- `sentiment`/`emotion`/`tendency` **default to `bert`** — `_effective_bert_model` uses the node's own model or that op's
  registered default from `model_registry.json` (each entry carries an `operation`), and `_resolve_bert_mode` degrades to
  the dependency-free mode (`snownlp` / `ml`) with a printed line when bert cannot run (missing torch/transformers, or
  nothing registered to load).

The analyzers themselves still refuse a direct unrunnable `bert` **by name** (defense in depth), and a multi-model BERT
comparison never degrades (it has no general-mode equivalent). torch/transformers go to `requirements-optional.txt` (not
CI-installed) precisely so the CI tier exercises the degrade-and-print path rather than hiding it.

The local PostToolUse `ruff format` **silently fails on a restricted workspace** (measured `os error 5`: ruff writes a
temp file then renames) — the edit stays unformatted while the hook looks fine. Hence: run `ruff format` by hand before
committing; CI (`ruff check` + `ruff format --check`) is the unskippable gate.

## How tests are written here

- **Isolation happens at conftest import; the suite fails if `data/`/`logs/` gains a byte.** `tests/conftest.py`
  redirects every write path *before any test module imports* — collection imports all test modules before any fixture
  runs, and `app.py` captures `Config.COOKIE_DIR` / `history.db` into module-level singletons at its own import, so a
  later redirect would be too late. `test_test_tiers.py` refuses the import statically; the session-finish snapshot
  refuses the write.
- **A warning is a test that noticed something and passed anyway — fix what it noticed, never mute it.** Fixes landed
  here because of warnings: class-scoped fixtures must be `@classmethod` (an instance-method fixture's `self` is
  discarded before tests run, so any `self.` it sets is invisible to them); close file responses after reading; never
  let a cookie-save open a **real Chrome inside the fast tier** (the plant swallowed a socket failure, answered
  「种入失败」, left a `UserWarning`). A no-browser test says so (`profiles_off` in `tests/api/conftest.py`); a dependency
  leaking its own handle is reported to the user, not filtered. One not ours, left visible (never filtered): jieba
  0.42.1 (final) imports deprecated `pkg_resources` → one `DeprecationWarning` (`jieba_fast` too); see
  `docs/development.md`.
- **A stateful rule needs a stateless suite.** The suite shares ONE cookie directory, so `quiet_jar` snapshots and
  restores it per test — a login another test saved is a precondition this one never set up, and "is this cookie here?"
  passes for the wrong reason when inherited.
- **The frontend may not hold a second opinion about a crawl.** `sourceNodeErrors()` asks `Capabilities` which fields the
  selected mode requires; if not loaded, it must refuse rather than guess — the form obeys the same rule (`boolParam`,
  `selectOptionTags`) so a stored value off the list shows as itself, never option #0.
- **A canvas shortcut belongs to the canvas only while the user is not typing.** `canvas._isTypingTarget()` asks what the
  element IS (`isContentEditable`, `.cselect`, …), because an earlier growing *tag list* left out a paste box and the
  shortcut hijacked a paste.
- **The camera is not part of the model.** Putting pan/zoom in `getState()` made every pan an undo step. `addNode`
  randomizes only for a non-finite value, never `x || …`, because a saved x/y of `0` is a real position.
- **One page boot must not be a single point of failure:** a throw inside the one `DOMContentLoaded` body skipped every
  later step (canvas.init never ran, page stayed blank with nothing readable in the console) — hence `boot(name, fn)`.
- **Six frontend rules, each costing a feature when forgotten.**
  1. `if (window.X)` cannot see a top-level `const X` (it's not on `window`) — the guard silently never fired.
  2. The DOM stub's matcher is real (`harness_dom.mjs`); fabricating a child hides a broken selector from the harness.
  3. A wrapper with an empty parameter list acts on whatever was selected *before*, not on what just failed.
  4. A name inside `onclick="fn('…')"` spans two grammars: `attrJsArg` must JS-escape the literal, *then* HTML-escape the
     attribute; JS-escaping alone lets one `"` end the attribute.
  5. A node captured before an `await` is gone after it — settings panels and run-list refreshes rebuild the markup, so
     the write lands in an orphan unless you re-look it up (`_rowFor`, the holder by id).
  6. **A wrapper installed in another file is not the function your harness loads**: `app.js` re-assigns
     `window.openCookieDialog` (drag/resize) with one parameter while the real function took two, so the account argument
     died *in the browser only* — each cookie harness ran `workflow.js` alone and stayed green. Hence forward `(...args)`
     and measure a change behind a patched global in the browser tier too, not just the single-file harness.
- **A feature matrix must enumerate every dimension that classifies the thing under test**, not only the one the bug was
  about: for a record, a run or a panel row, list the dimensions first and cover the grid.
- **A live case's numbers are computed from the site, never chosen.** An ask, threshold or supply floor the site is not
  obliged to fit reds an honest crawl (and greens one when the cell only fires "if the thread is big enough"): derive it
  from what the crawl reported (the card's 评论数, the page's own count, the board's size) and make the assertion
  two-sided so a thin day still proves something — two D-cells of `test_live_weibo_workflow.py` each cost a live re-run
  for breaking this.
- **A browser-measured assertion must report how much it measured, or it is not an assertion.**
  `tests/integration/test_ui_layout.py` audits containers **by id**, never falls back to `<body>`, reports a
  per-container floor, and resolves on-screen wording from `I18n` in the browser. **State the viewport:** on Windows
  `set_window_size`/`set_window_rect` are silently ignored (a dialog's `calc(100vh - …)` cap is taken once, when it first
  opens), so "fits a 1366×768 laptop" can be measuring a 1920×1080 window wearing another test's cap — emulate
  (`Emulation.setDeviceMetricsOverride`) and assert the size CSS sees with a `100vh` probe, because `window.innerHeight`
  reports the un-emulated one.
- **A closed panel must be gone, not merely moved — and only pixels can prove it.** `#clipboard-drawer` hid itself with
  `transform: translateX(100%)` under `right: 12px`, and a percentage translate is the box's own width: the closed drawer's
  left edge landed exactly 12px INSIDE the layout viewport, so its last 12 columns painted over the canvas. Measured in
  Chrome at 960×920 (`clientWidth` 938): `rect.left=926`, 12 of the last 40 painted columns hit-tested as
  `clipboard-list`, and a 60×340 `Page.captureScreenshot` strip against the same box forced to `display:none` read **813
  differing pixels, worst channel delta 41** (a closed-vs-closed control read 0/0 first, which is what makes those pixels
  quotable). The shadow is why the rect fix alone is not the fix: `--shadow-soft` blurs 3px past the border box, and a
  shadow is not hit-testable — so the drawer also carries `visibility: hidden`, delayed 0.15s so the drawer is still seen
  leaving. `test_ui_layout.py` pins both halves (each fails independently: dropping `visibility` trips the paint
  assertion, dropping the `+ 12px` trips the rect one) plus the byte-identical strip comparison. `clientWidth`, never
  `innerWidth`: it excludes a classic scrollbar, so it is the right-most column the user can actually see.
- **A test may not assume the machine's own zone — the two machines are never in the same place.** GitHub CI runs
  UTC and this box runs UTC+8, so the scheduler's blank-zone case ("留空=服务器本地时区") written as
  `describe_time(moment.isoformat(), '') == '2026-10-16 08:00 (服务器本地)'` was a +08:00 literal wearing a test's
  clothes: the same `00:00Z` instant renders `08:00` here and `00:00` on CI — which is exactly how it failed there
  (`1 failed, 6498 passed`), while the full fast suite was green locally. The expectation belongs to the machine
  (`astimezone()` with no argument — the same definition `schedule_store.describe_time` uses for a blank zone), while
  a NAMED zone stays a literal (`'Asia/Shanghai'` → `08:00`), because that one is machine-independent. Reproduce the
  other machine instead of waiting for CI: **Python on Windows honours `TZ`** — measured, `$env:TZ='UTC'` turned
  `astimezone()` into `+00:00` and reproduced CI's single failure, and removing the variable restored `+08:00` — so
  `$env:TZ='UTC'; pytest -q` is a cheap CI-equivalent gate that reads 6501 passed.
- **The `integration` UI tier performs no server writes** — no data-dir switch exists, so a run or upload lands in the
  user's real `data/`/`logs/`. Stub `fetch`.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall` (risk control can
  answer a valid session a login redirect once). An empty that NAMES its refusal (wall or risk) is the site's answer —
  assert the naming; an unnamed empty is real "found nothing" and stays red.

## Run, resume and record invariants

- **One server per data root, by design (local single-user tool).** `RunStore.__init__` calls `promote_stale_runs()`,
  which marks every run still `running` as interrupted, so a second instance on the same `data/` kills the first one's
  live run. `CRAWLER_DATA_ROOT` (config.py) gives a process its own `data/`+`logs/` — the `/smoke-verify` boot and the
  UI tier's self-booted server use it.
- **One run at a time; a busy server queues instead of refusing.** `_begin_run()` owns the whole start path, so the queue
  must drain by calling *that* function, never a weaker second one. The hand-off is in the worker's `finally` and clears
  `execution_state['thread']` **first** — the claim also checks thread liveness, so an unwinding thread would queue the
  next request behind itself forever. Queues are in-memory and `tests/conftest.py` clears `_RUN_QUEUE` per test.
- **A test that calls an executor function directly must leave the app quiet:** `clean_globals` resets the console and
  *fails* a test that leaks `execution_state['running']`, because nothing else clears either without the run start / the
  `client` fixture.
- **Checkpointing is the core value.** Three measured rules, each pinned by a test: the streaming row sink writes **one
  transaction per row** on purpose; the next free slot is `MAX(seq)+1`, **never `COUNT(*)`** (deleted rows make COUNT
  collide); a **cursor records position, not content** — collected ids come from the seeded rows (`Crawler.seed`), so an
  id list must not go back into `mark_position`.
- **A label is not an input.** A node's fingerprint feeds its children AND the dedupe ledger's scope (`'item:' +
  node_fingerprint`), so a *name* inside one invalidates a whole chain and moves the other. `_VOLATILE_PARAMS` (labels +
  switches like `recrawl`/`enabled`) answers "does this parameter choose data, or just describe the record?" — ids stay
  in, labels and switches out.
- **A disabled node is not on the canvas:** `effective_workflow` drops it (`enabled` off, type off, or all upstream gone
  — cascades down; fan-in survives on one live input); validate/naming/fingerprint/execution all run on that graph, so
  disabling a workflow is disabling its head node.
- **Reuse has four rules** because each was violated once: `done` AND `restored` are reusable; a stored result with
  **zero rows** is never reused (an empty parent may deliver this time); the source node is never adopted (it resumes by
  cursor); and `begin_node` reporting `dropped_stale` cancels reuse, because those rows were deleted.
- **Startup recovery shares the end-of-run settlement.** A node leaves `running` only through `finish_node`, which a kill
  skips, so `node_runs.row_count` still holds the 0 `begin_node` wrote. `promote_stale_runs` must call `settle_nodes`
  (status *and* count from the rows): the panel's 已存行数 and the 续跑 node's "adopt the fullest node" both read that
  column.
- **One definition of "completed":** the finish line's counts are taken **after** settling and only over `attempted_nodes`
  (the record also keeps nodes the canvas deleted), and a node 停止 cut short is counted in its own `stopped_node_ids`
  bucket — reporting the user's own button press as 「1 个失败」 is a lie about what happened.
- **A resumed run re-describes itself:** left at first-attempt values the 并行/串行 and 无头/窗口 chips describe a run that
  never happened, and the stale name — the key every preview/chart/export probe uses — makes the kept rows unfindable.
- **A phase column's order is not data, and a records round trip erases it.** `bin_time` writes an ORDERED categorical
  (`pd.cut`), but every node boundary rebuilds the table with `pd.DataFrame(current_input)` (app.py), leaving plain
  strings whose code-point order puts 二次爆发期 before 发酵期. Sorting the names is how a replicated 表 1 gets renumbered
  while still looking complete — so a step emitting a phase table must also emit its position column (`stage_order` /
  阶段序号, a NUMBER), the only thing surviving the boundary.
- **A quoted row count is only true of the merge order that produced it.** 近重复去重（SimHash）keeps whichever row of a
  group arrived first, so the same six files merged in canvas order give 3778/4366/4993/4526/623 rows per phase and in
  filename order give 3620/4454/5032/4555/625 — and every 事件标注 volume with them. Measure through the canvas's OWN
  upstream order (walk `connections` into the merge node, don't glob the folder); a re-measurement that disagrees is a
  clue the order changed, not that the data did.
- **A coherence sweep is not a decision, and only the canvas's own sweep may be quoted.** 主题数扫描 draws 2000 documents
  by default and the draw follows the table's row order, so its argmax moved between merge orders (8,5,6,7,3 ↔
  2,7,3,4,2). Run per phase over every row it answers 5,6,2,6,2 — but 波动期's coherence spans 0.227–0.337 across 2..8
  and 发酵期's 5..8 sit within 0.004, so the argmax is noise with a number on it. Hence: (1) the scan node justifying a
  canvas's `stage_topic_counts` must run `coherence_max_documents=0` and be fed by that canvas's own phase filters, or
  the tool and the number it defends measure different tables; (2) where the sweep is flat, state the tie-break (this
  canvas takes the highest coherence at **≥3 topics** — a 2-topic phase cannot show a lifecycle) in the node title — an
  unseen floor is judgement dressed as measurement.
- **A score is a function of the column it was read from, so the column name belongs to the number.** The same 18286
  rows scored on `正文` give 0.211/0.200/0.217/0.228/0.238 per phase, and on `cleaned_text` give 0.164/0.170/0.173/0.199/
  0.200 — same shape, ~0.04 apart, because a repost chain carries the insult verbatim while the cleaner strips it. A
  curve quoted without its column cannot be audited later.
- **An unused LDA topic is the model's answer, not the user's mistake.** An argmax can leave a topic with zero documents;
  the stage's other topics are still real output, so `topic_by_stage` fills that row from the topic's own word
  distribution, files `doc_n = 0`, and logs one named warning. Killing the run, or printing an empty 特征词 cell, would
  each destroy information the model has.
- **A recall device must not be allowed to look like a classifier.** `aggression`'s word-list mode states in its
  docstring, panel hint and console line that a miss is unmeasurable, keeps the lists in code so their incompleteness is
  reviewable, and deliberately does NOT count 辟谣-style accusations as violent. A missing text column **raises** rather
  than returning blanks, so an all-`none` column can only come from a real reading, never a mistyped column.
- **The analysis node's one non-deterministic step borrows the process node's client:** the run report echoes every
  step's `params` into the console and the durable record, so a client in `params` would be a live object written into a
  ledger — hence `llm=`/`cancel=` are handed to the ops in `LLM_OPS` *only*. A Stop leaves `未处理` in the rows the model
  never saw, which is how the executor settles that node PARTIAL instead of DONE.
- **Retention must release what it destroyed:** `purge` deletes a run's rows, so it also calls `forget_run_items` — an
  `item_seen` entry whose rows are gone would make a later crawl under-collect silently, with no way back except
  「重新采集」. An explicit `delete_run` still *keeps* claims: there the user removed a record knowing the crawl was paid
  for.
- **`' + '` is a composed lookup key, not a permission:** widening the exact-name probe to its pieces unconditionally
  would hand a canvas genuinely called `节奏` the table of someone else's `节奏 + BPM` — hence widen only on a miss.
- **A node id is a storage key — never re-mint one on restore.** Run records, resume cursors, LLM caches and
  `workflow_fingerprint` all key on node ids, so renumbering detaches a canvas from its own interrupted run. `addNode`'s
  `nodeId` + `reserveId` keep `nextId` past a restored id (a later drag must not collide); both restore paths pass file
  ids straight through — pinned by `harness_state.mjs`. That id is also the box's **DOM** id, so `getElementById(<node
  id>)` lets a workflow file address chrome the node does not own: reach node elements through `canvas._nodeEl(id)`, and
  `test_frontend_state_js.py` fails any variable-argument `getElementById` in canvas.js.
- **Recorded rows are addressed by workflow, never by bare node id:** ids like `node-2` repeat on every canvas, so
  `_durable_node_rows` returns nothing rather than guessing when it has no identity. The browser sends `workflow_name`
  from `workflow.runName()`, mirroring the backend precedence: name-node label, then saved file name.
- **Parallel is one record; serial is one record per workflow that started.** Parallel runs the workflows together, so one
  row joins their labels with `' + '` in canvas order; that string is also a **lookup key** (old rows stay inspectable,
  pinned by `TestRowLookupStillWorks`). Serial runs take turns, so each workflow opens its own row **as it is reached**.
  Every row keeps the **canvas** fingerprint (what the resume banner and `/api/runs/resumable` match on), and the id the
  HTTP response returns is workflow zero's row; 继续 adopts each workflow's own row by name. **A chip must describe what
  happened:** `并行 ×N` only when `mode == 'parallel'`, and a serial row says `串行 ×1` because that row *is* one workflow.
  Resume state stays **per workflow** (`fingerprints_for_workflow`), so a failure in B restores A.
- **A cursor records what the node PROVED, never what it attempted.** `_execute_comment_node` wrote
  `{'url_index': idx - 1}` *before* handing a link to its adapter, so a pass that walked all ten dramas left the
  cursor at `9`. Both end-of-node refusals (a drama the client would not open; a walk short of the site's total)
  raise *after* the loop, so 继续 skipped 1..9 and re-walked the last link alone: the harness is freshly built per
  attempt, `skipped_targets` was empty, both gates slept, and the node settled **DONE** over the hole the console
  had just named — with a message promising 「继续只补这几部」. The write now happens after the walk and only while
  the run of completed inputs is unbroken, so the cursor means "leading inputs proven complete"; the blocked/
  cookie-wall refusal laundered the same way is fixed by the same change. Rewinding is safe only because the ledger
  refuses a re-walked comment (`item_key` below), and that is what `test_a_tail_refusal_leaves_the_cursor_behind_
  the_hole_it_named` measures with a real `RunStore`.
- **A row's ledger key is its site identity, not its content.** `run_store.item_key` identifies an item by link, else
  by title+author+the head of the body, else by a hash of the WHOLE row. Comment columns deliberately avoid the first
  two field lists (`crawlers/comments.py` says why: every comment of one article would then share a key and all but
  the first would be dropped) — which left them on the whole-row hash, and that row carries `楼层`, which a fresh
  harness numbers from 1 again. So any resume that re-walked an article re-stored all of its comments with invented
  floors, and the comment engine's own in-run dedupe already used `评论ID` (`identity=lambda row: row['评论ID']`) —
  two answers to one question in the same feature. A comment is now keyed by (`平台`, `评论ID`): the id alone would
  let a 知乎 numeric id meet a 微博 one inside a mixed-input node. Changing the function rotates existing keys, so a
  saved comment node re-files its set exactly once — a one-time cost for a dedupe that previously did not hold at all.

## Console, messages and i18n

- **A missing `t()` keyword is a printed bug, not a crash.** `t()` deliberately returns the *raw template* when a
  parameter is missing (never abort a crawl for a sentence), so a forgotten `{reads}` prints `阅读={reads}` once per
  article. Key parity, reachability and zh/en matching are all blind to it; `test_i18n.py::TestCallSitePlaceholders`
  walks every `t('literal', …)` in `backend/` with `ast` and refuses the mismatch.
- **A `{platform}` slot is answered with a word, not the key:** `zhihu` keys the matrix and the cookie file, `i18n`
  localizes it (splitting on `,`/`、` only), and `test_frontend_contract.py` (`TestChromeOfThePageItself`) keeps the two
  lists equal.
- **Console messages reference nodes through `node_label` (→ `title #nid`), never a bare `nid`,** so a renamed node
  speaks with the user's name — while store keys, the results dict and resume plumbing still use the raw `nid`. BOTH
  restore paths re-apply title + element text BEFORE `updateNodeDisplay`, whose re-stamp guard reads the element.
- **The run console keeps its own history per view, because the server cannot give it back** (it ships only the last 200
  lines of the *whole* run). `consoleViews` holds `{seen, lines}` per view (`'all'` plus each workflow id), **every**
  view is fed on every poll, and `switchWfTab` repaints from that view's history without moving its cursor.
- **The console is ALSO persisted per run (`run_store.run_log`), but that durable log is a pure side effect of the live
  path — it may never move the live console.** `_push_log` (state.py) writes through to `app`'s `_RunLogWriter` via the
  `set_log_sink` seam; the writer files every physical line under the run that printed it (flush every 200 lines + on
  any error + once in the worker's `finally`), armed only inside a run's window so a stray post-run `add_log` cannot
  orphan rows. The durable viewer (`/api/runs/<id>/log(.txt)`, `runLogViewer`) reads ONLY that table. **The reattach
  reads `execution_state['logs']/_log_total/_wf_logs/_wf_log_total` and the `?tail=5000` replay, and those values must
  stay byte-identical whether or not a sink is installed** — a shifted total is a cursor that skips or repeats live
  content after a reload. `test_console_buffer.py` fails that invariant; it is the guarantee, not a nuisance test.
- **Every thread that logs must pin its own language:** `set_lang` is thread-local and a daemon thread starts fresh, so
  `run()`, the parallel pool wrapper and **both cookie workers** set the request's language first — a daemon thread that
  does not is Chinese in an English interface. A test asserting console text asserts on the reason, not a pasted
  sentence, or sends both languages.
- **One failure, one line:** `LogBufferHandler` forwards every `logger.*` call into the console buffer (its `format` is
  the message alone, so a traceback still goes only to the log file), so `logger.exception(...)` **and** an `add_log` of
  the same text print the sentence twice. Keep the logger call for the file's traceback; let `wf.node_failed` be the
  single attributed console line; a helper line may add a fact that line cannot carry (how many rows survived), never
  repeat the reason.
- **Anything that chooses data, cost or a name is refused BY NAME, never guessed** (a mode, a `select`, a step's select
  or missing column via `data_analysis.validate_step`, an analyzer's `method`/`mode` via `app.enum_param`), and refusals
  `raise` rather than returning `[]` — else the node settles DONE over an empty table. **Read a switch, never compare
  it** (`utils.helpers.as_bool`; blank = the declared default); a form shows a stored value off the list
  (`selectOptionTags`), never option #0.
- **`_push_log` stores one entry per physical line** — the total advances by lines, not `add_log` calls: a multi-line
  driver `Message:` block rendered as several rows and the browser's cursor skipped or repeated content.
- **`_QUIET_NODE_TYPES` (`name`, `upload`) is a console-noise decision, not a filtering hook:** those nodes get no
  "Executing node …" / "Node … completed (n/N)" line, and progress counters still count them; everything stating a fact
  still prints (the upload's "Loaded … N rows", any failure/skip/restore line) — with `node_label`, or a silenced node
  that fails is undiagnosable.
- Run-gating lives in `execute()` → `_cookieGateBeforeRun`. The measured history behind it: **`execute()` asks no cookie
  question of its own** — its 2026-09 shape was a `/api/cookies/status` loop that refused on each platform's
  *default-account* boolean, so it blocked a node on a saved named account and blocked wechat entirely (that map holds
  no key for a platform with no cookie row). Hence the probe is `cookie_preflight_before_run` per platform **whose mode
  needs a session** (`Mode.needs_session`; weibo's 热搜 answers anonymously, wechat has no session to want — not a cookie
  platform at all), a login wall **refuses** (no "run anyway"), and 「无法核对」 (timeout, captcha, busy profile) **never
  blocks**, because no answer is not evidence of a dead cookie.
  - **A named cookie and a named profile belong together:** one account = one
    `data/cookies/<platform>@<account>.json` *and* one `chrome_profile/<platform>/<account>` (own device, own rotated
    session, own concurrency lane), so nothing answering "does this crawl have a login" may drop the account.
  - **A node's 账号 is a session question, asked once:** `engine.workflow._account_session_errors` refuses a crawl that
    `Mode.needs_session` says needs a login when `cookie_preflight.has_session_to_test` finds neither that account's
    cookie file *nor* a profile still carrying it — blank included, because blank IS an account (默认账号), not a
    wildcard.
  - **Every account has one name and one spelling:** the default login is named `default` (the box shows it, never a
    blank; the blank is only its old filename), folded at the ONE point `CookieManager.key`/`path_segment` (`''` ⇄
    `default`, lowercase always) — `Work` and `work` are the same session, because a case-insensitive filesystem cannot
    hold two logins under one spelling — so `browser_profiles`, the preflight cache and the JS box all route through
    that fold. `unoffered_selections` must not answer it either (one failure, one line). Letting it through is not a
    harmless crawl — it walks into a login wall, files an empty table and reports 完成. The candidate list and a new
    node's preselection are both `CookieManager.accounts_in_order`, so the first row listed is the account a node starts
    on.
  - **A new settings key needs all four:** the bool branch in `settings_store.save_settings`, both app.js catalogs, and
    the `AppSettings` wiring.

## 定时任务 (scheduler) — why the clock is narrow

**The clock is one thread, and it is started from exactly one place.** Flask's reloader (`FLASK_DEBUG=1`) imports the
module twice — parent and serving child — so a `scheduler.start()` at import scope gives **two clocks ticking the same
`data/schedules.json`**: two threads that each see the task due, so the second fire is queued behind the first and the user
gets a run nobody asked for (and a canvas that spends accounts gets crawled twice). Hence `start()` is called only under
`__main__`, and only when `not debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true'` — i.e. in the process that really
serves. `start`/`stop` are idempotent so a test (or a future caller) cannot stack threads.

**A fire is the same start as a manual Run, because `_begin_run` owns the whole start path.** `scheduler` may not import
`app` (the Blueprint imports the scheduler, so that would be a cycle), so app.py installs two seams at import:
`set_run_starter(app._start_scheduled_run)` and `set_canvas_source(app._scheduled_canvas)`. `_start_scheduled_run` then
calls `_begin_run` — the *only* start path — which is what makes a busy server **queue** the fire exactly like the Execute
button instead of racing it (`queue:false` keeps the 400 for fail-fast callers, so a second path would have looked
plausible). The scheduler is refused by name (`sched.notWired`) when nothing was wired, because a silently-dropped fire
would look like "the scheduler does not work on this box" with no line saying why.

**A crash in the starter is not a refusal.** `_fire` records `error` for an exception (with the traceback in the log file)
and `refused` for an executor saying no. They mean different things to the user reading the task's history — "my canvas
needs a model" versus "something is broken" — and the first version recorded both as `refused`. A crash also must not stop
the clock for every other task, so the `except` is per-task and the tick continues.

**One rule about a canvas, asked three times, from one function.** `app._scheduled_canvas` wraps the existing
`_workflow_needs_llm` (the same test the executor uses), and the panel's `runnable`/`why_not`, the save-time check and the
fire-time check all go through it. Three copies would drift, and the drift is invisible until 03:00. This is why a
scheduled canvas may not need a model at all: a cloud box has neither Ollama nor a person to answer a provider question,
and the user explicitly refused a server-side key — so the canvas is refused **while it is being chosen**, in the picker's
own label, rather than at the moment of firing in a history row nobody is reading.

**A missed moment is recorded, never replayed.** A restart after a night down must not fire a backlog (each fire spends
accounts, and the user asked for one run per slot). `note_missed()` runs once before the thread starts and marks a past
moment as missed, and `_reanchor()` re-arms the task from *now*; a task that is switched off or not yet due is left alone,
and **at most one missed event is filed per restart** however many slots were skipped (`missed.count` accumulates across
restarts, which is what the panel's 「错过 N 次」 chip reads).

**Accounting goes to the task, and the console stays honest.** The run console is a per-run view: a queued fire has no
console of its own yet (the queue narrates when it starts) and a refused one has none at all. So only a run that really
started gets one attributed line (`sched.fired` / `sched.firedManual`), and everything else lands in the task's own
`last_run`/`history` (20 entries, newest first) where the user is already looking. The language of those lines is pinned
from the task (`set_lang` in `_fire`), because a daemon thread starts fresh and would otherwise print in whatever language
the last request left behind.

**The browser may not hold a second opinion about time or state.** A Beijing screen can be looking at a UTC cloud box, so
a moment the browser formatted would name a time the schedule does not mean: `next_run_local`/`last_run_local` are
rendered server-side in the *task's* zone, and the trigger sentence comes from the store's own `describe_trigger`. A
status token the catalogue does not know shows **as itself** (the same rule as a stored value off an option list —
`weird` is real information, and mapping it to a neighbouring word would be a lie). `schedules.js` therefore has no time
arithmetic and no status vocabulary of its own; `tests/unit/test_frontend_schedules.py` drives the real file under node to
keep it that way.

**The dock list and the dock matrix are two places, and both are needed.** `DOCKED_PANELS` is the list
`closeDockedPanels` walks — a panel missing from it stacks on top of the console instead of replacing it — while
`tests/frontend/harness_panels.mjs` is the one place that proves "opening any one closes the others AND clears the stale
inline height" (an inline height beats the CSS `height: 0`, which is how two panels once overlapped). Adding
`schedules-panel` to the list surfaced that **`cookies-panel` had never been in the harness** — docked but undriven since
it was added. Hence the test that fails a docked panel missing from the matrix
(`test_the_dock_matrix_in_the_shared_harness_still_covers_every_panel`), and hence the shared harness now loads
`schedules.js` too: the panel's toggle lives in its own file, unlike the other togglers.

**cron is hand-rolled on purpose, and its edges are measured.** stdlib only (`zoneinfo`; zero new dependencies — the
project's dependency rule), with `next_after()` strictly *after* the given moment so a tick landing exactly on the slot
cannot fire the same slot twice. The edges a user hits once a year are pinned in `tests/unit/test_cron.py`: a
spring-forward hour that does not exist is **skipped whole** (never fired twice), an autumn ambiguous hour runs on its
**first** pass (`fold=0`), `0` and `7` are both Sunday, day-of-month and day-of-week are combined POSIX-style (OR), and an
expression that can never fire (`0 0 30 2 *`) is refused **at save time** by name rather than stored and never answered.


**A bibliometric node is still an ordinary table node, and its source is not necessarily a bibliographic file.** The first version read fixed `关键词/年份/题名/参考文献` columns, which quietly made "CNKI/CSSCI" the only possible source and contradicted the project rule that files and crawls publish the same rows. `read_columns()` now resolves the user's mapping (topic/username/publish-time works); `entity_column` blank means the canonical column for the chosen entity, never a wildcard, and citation modes refuse a table with no reference column by name. The node emits one row per entity — not a chart spec — so resume, analysis and output nodes see it exactly like a crawl table; `连接`/`年份序列` are canonical JSON text because a dict result is not persisted by `run_store`. CiteSpace was inspected for its feature surface only: algorithms are reimplemented from published work, no decompiled code or bundled basemap is shipped, and CNKI data limits (no CR/TC) are a named refusal rather than an empty graph.

**Format detection is a registry, not a pile of file extensions.** WoS, Scopus, PubMed, Dimensions, Lens, RIS, BibTeX and EndNote each declare what fields they can carry; the upload response reports the fields this particular file actually carried. A recognized format with zero records is a 400, while an unrecognized CSV/text/Excel keeps the old table path. Structured references are normalized once in `biblio_refs.py` and shared by importer and graph builder, so a co-citation node cannot silently parse `引文` differently from the file that stored it.

**A paper-ready graph label needs the browser's real rectangle, not only a server-side guess.** Backend offsets were still overlapping in Chrome because ECharts' graph coordinate-to-pixel mapping depends on the container. `workflow.js` now installs a `labelLayout` collision resolver for graph/scatter labels at render time: it shifts labels into the first free slot and hides only what cannot fit, while hover still exposes the full name. The fast suite pins the resolver's presence; the browser probe measured node-label overlaps down to zero (remaining overlap was legend/visualMap text, not graph labels).

**Avoiding other labels is not the whole job — a label also has to stay out of the chrome.** The first resolver only compared labels with labels, and the browser then measured `风险沟通` printed on the cluster legend entry `#5 数据治理；…`. Nothing in the option said where the legend was, so the graph builders now reserve a band (`left/top/right/bottom` on the series: title above, legend column right) and the resolver clamps every candidate box into it, hiding a label that has no legal slot. Two follow-ups the same probe forced: a **percentage** inset is a length too (`'10%'` read as a number is `NaN`→0 and the clamp silently vanishes), and a **rotated** label cannot be clamped at all — `circular.rotateLabel: true` left one vertical term standing on the chart title, so circular labels read horizontally like every other view here. `tests/frontend/harness_label_layout.mjs` drives the real `workflow.js` under node and states, per case, both the box it asked for and whether the label survived — a resolver that hid everything would pass the "inside" flags alone.

**`ECHARTS_ONLY_TYPES` is a statement about matplotlib, and reading it as a statement about LaTeX switched the paper output off.** `build_latex_outputs` skipped every type on that list, so `emit_latex` was a no-op for the word cloud, the sankey, the map, the topic views, the network graph and all nine bibliometric views — the box was there, the checkbox defaulted on, and nothing complained because a skipped add-on is not an error. pgfplots draws every one of them. The skip now asks its own question (`LATEX_UNBUILDABLE_TYPES`, which is exactly 模型一致率), and `test_only_the_agreement_matrix_has_no_paper_twin` fails if the catalogue grows a type with no LaTeX twin or the two lists are conflated again.

**A LaTeX source that passes pytest is not a figure.** The fast suite only reads the emitted string, so `hide y axis line` — a key this MiKTeX does not know — compiled to an error page for the burst and timezone figures while every test stayed green. Compiling all nine figures and all nine three-line tables with `xelatex` is what found it (`axis y line=none` is the supported spelling); do that before claiming a chart has a paper twin, and check the PDF exists rather than trusting a silent exit code.

**A dual-map table lists its nodes as well as its links, and a builder that reads only links loses half the figure.** `output_shape=dual_map` emits `map/source/target/weight` rows where an empty 终点 means "this journal/category is a node". Both the ECharts builder and the TikZ one filtered those out, so a journal reached by a single overlay line — the sparse end every real corpus has — simply was not drawn. Same-side edges are undirected too: collecting only the `source` endpoint left a journal that ever appeared as a `target` without a position, and its links were dropped with it.

**A verification server has to be a server you can prove is yours.** Two processes were listening on the probe port at
once (an earlier session's isolated boot never died), and the requests answered with code from before the change — the
first "dual_map is refused" and "the chart needs an x field" were that rival's behaviour, not the working tree's. Check
`netstat -ano | grep :<port>` before believing a probe, boot on a port you just freed, and re-read the boot log. Chrome
then refused the fresh port outright: `5060`/`5061` are on its unsafe-port list, so the page never loaded and the symptom
was `echarts is not defined` — a missing global that was really `ERR_UNSAFE_PORT`. Probe ports are Chrome-safe ports
(5057/5058/5077), and a probe should say which of the two it saw.
