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
- **A result view is pinned to a RUN, not to each node's newest rows.** `latest_rows(node_id, workflow_name)` answers
  "show me the latest table" one node at a time; loaded together that can stitch node-1 from last night to node-2 from
  this morning and present a run that never happened. `/api/runs/for-workflow` lists this canvas's records by the same
  structure fingerprint a 继续 uses, the browser pins `run_id` into every preview/chart/dashboard payload, and the
  resolver then reads **only** that run's rows (not even the live dict). Live node states come from `attempt_records`
  (reset per attempt), never `owned_records` (kept across runs) — otherwise a previous run's verdicts would paint
  themselves over tonight's canvas and a parallel run's several `running` nodes would collapse into one "current" node.
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

**"It compiled" is not "it fits the page" — and a standalone source can never tell you which one happened.** Every figure this project writes is a `standalone` document, so TeX sizes the paper to the picture and a 46 cm ring simply becomes a 46 cm sheet: 22/22 PDFs, nothing wrong. The same body pasted into an A4 paper page ran off the right edge, and the three-line table beside it lost its last column. The evidence for a *document* is `grep -c Overfull` on the compile log plus reading the rendered pages — the first paper build had a page holding nothing but the heading 「图表」, another had a table 2.6 cm past the bottom, and both compiled "successfully". Three layout attempts, three different failures: a normal `figure`/`table` float moved every picture past the section heading (blank page); an in-flow `center` + `\captionof` kept the order but could not break, so an over-tall item overshot the bottom; `[H]` (float package) does both — pinned in reading order, and TeX still moves the whole item to the next page.

**A layout whose size grows with the data has to be sized against the page, not against the unit.** The ring's radius is `0.46 × nodes` on purpose (labels need arc to sit on), but the tikz unit stayed 1 cm, so the picture's own extent was a function of how many keywords the run found. `GRAPH_BOX_CM` now sets the coordinate scale (`x=…cm,y=…cm`, clamped at 1 so a small graph keeps the size it always had) *after* paying for the labels, and the label width is estimated deliberately wide — under-estimating is the direction that overflows a page. Dropping colliding labels is geometric (rectangles across east/west/north/south, first arrival wins) rather than a per-side sweep: an east label from one node and a north label from its neighbour overlap just the same, and a per-side pass calls both fine. What it drops is printed on the figure ("已省略 N 个会互相遮盖的节点标签；完整节点见三线表"), because a silent thinning is a figure that lies about the corpus.

**A `tabular` cannot break, so a document that pastes whole tables must cut them itself.** A 50-row three-line table is ~26.5 cm of unbreakable box on a 24.6 cm text block. `latex_report` re-cuts it into page-sized blocks that repeat the header, numbers only the first (`\caption*` for the continuations — two numbers for one table is a citation nobody can point at) and keeps every row. It only cuts bodies whose shape it recognises (one row per line, `\bottomrule` alone on its own line): a hand-edited `.txt` in the export folder is pasted unchanged rather than mangled, and `_split_table` returning `None` is the refusal.

**A dual-map table lists its nodes as well as its links, and a builder that reads only links loses half the figure.** `output_shape=dual_map` emits `map/source/target/weight` rows where an empty 终点 means "this journal/category is a node". Both the ECharts builder and the TikZ one filtered those out, so a journal reached by a single overlay line — the sparse end every real corpus has — simply was not drawn. Same-side edges are undirected too: collecting only the `source` endpoint left a journal that ever appeared as a `target` without a position, and its links were dropped with it.

**An axis label box wider than the preview panel is a name cut off the left edge, not a wrapped one.** The bibliometric views reserve `axisLabel.width: 200` so long names truncate instead of collapsing the plot — correct on a 1650 px canvas, but at the preview panel's 400 px the label was measured starting 46 px LEFT of the canvas (`containLabel` does not pay for a *declared* width), so every node name disappeared. The overlay views use 96 px (≈10 CJK characters) and leave the full name to the tooltip and the table; the browser tier now measures both overlays at 400 px in zh and en. The same measurement caught a `type:'scroll'` legend adding a `1/1` page marker on the first row (plain legends are already the house rule here) and `patchOptionForTheme` rewriting a series label colour for its own background — a white number inside a coloured segment therefore has to be stated **per data item**, or the light theme prints dark text on a dark bar.

**A verification server has to be a server you can prove is yours.** Two processes were listening on the probe port at
once (an earlier session's isolated boot never died), and the requests answered with code from before the change — the
first "dual_map is refused" and "the chart needs an x field" were that rival's behaviour, not the working tree's. Check
`netstat -ano | grep :<port>` before believing a probe, boot on a port you just freed, and re-read the boot log. Chrome
then refused the fresh port outright: `5060`/`5061` are on its unsafe-port list, so the page never loaded and the symptom
was `echarts is not defined` — a missing global that was really `ERR_UNSAFE_PORT`. Probe ports are Chrome-safe ports
(5057/5058/5077), and a probe should say which of the two it saw.

**A dock that reads a run record has to page it, and a page boundary is a multiple of the page
size.** The bibliometrics workspace clamps its Next button with `min(total - 1, offset + LIMIT)`
— which a real browser then demonstrated on a 164-row table with a 200-row page: Next was
"enabled by the arithmetic", the offset jumped to 163, and the panel showed the last row alone of
a table that fits on one page. `lastStart = floor((total - 1) / LIMIT) * LIMIT` is the honest
clamp, and the case is pinned in the node harness (`singlePage`) because no Python test can see a
button's disabled state. The same probe is why `refresh()`/`pickRun()`/`page()` **return** their
load promise: a fire-and-forget `this.load()` left the caller guessing how many microtask turns
the table needs to land, and a test that guessed wrong measured an empty panel and called it a
pass.

**A capture is not a run record, and its parameters are only provenance if they are proved.** A
`node_runs` row stores a node's *fingerprint*, not its settings — the canvas file holds those. So
`POST /api/biblio/snapshot` reads the parameters out of the **saved** workflow and recomputes the
node fingerprint: equal, and the snapshot carries them with `params_verified=1`; unequal (canvas
rewired, file deleted), and it stores `{}` with `params_verified=0` and the panel prints 「未核对」.
Filing the settings a panel happens to be holding as "the parameters that produced these rows" is
how a paper ends up describing a run that never happened. The same reason drives two other rules
there: the capture reads **all** stored rows (a prefix of a table compared against another prefix
measures the page size, not the corpus), and the diff is computed server-side, with undirected
edges keyed by their canonical endpoint pair — a node table lists every link from both ends, so
comparing rows in arrival order reports a weight change on every edge that merely came from the
other side.

**A monitor reads history, so it is the first caller to meet an older row shape.** Two defects lived
in that comparison until cross-run monitoring (`services/biblio_monitor.py`) walked in front of it:

* `params_differ` indexed the LEFT dict (`a_params[key]`) while iterating `set(a) | set(b)`, so the
  first capture filed after a parameter was ADDED raised `KeyError` when compared with an old
  snapshot that never had the key. Read both sides with `.get()` — "the older capture had no such
  setting" is a real difference to report, not a crash.
* `list_snapshots` ordered by `created_at DESC, label`. `created_at` is second-granular, so two
  captures filed in the same second tie and the tie-break is a **name**: for Chinese labels that is
  codepoint order, which has nothing to do with time, and "compare with the capture before this
  one" silently compared with an arbitrary older one. The tie-break is `rowid` (insertion order).

**A side-effect parameter belongs to neither the fingerprint nor the captured settings.** `watch_*`
changes no row the node emits, so keying it in would recompute a paid-for graph whenever the user
renamed a capture; and filing it with the settings that produced the graph would make every capture
differ from its baseline by its own name, which kills the one signal (「参数变了」) that tells a
reader to suspect an edited node rather than a moving field.

**An `onclick` attribute is two grammars and the DOM stub will not tell you.** The workspace's
新建 button was built as `'… onclick="x.createProject(' + "document.getElementById('id').value)" + '>…'`
— the fragment that looked like it ended the attribute ended the *string* instead, so the quote
never closed and Chrome swallowed the rest of the bar as a text node. Every node-harness assertion
still passed: the stub parses attributes it recognises and ignores the wreckage. Two fixes, both
now rules here: the handler reads its own input element (`createProject()` with no argument), so
nothing but a plain literal sits inside the attribute; and the harness asserts the button is a
closed element (`/onclick="…createProject\(\)">[^<]*<\/button>/`) plus that no `</button></div>`
sequence ever appears inside an attribute value.

**A manual label counts only when it lands, and a stale one is named.** `cluster_labels` overrides
what LLR/LSI/MI/TF-IDF picked, and the note has to report the number that actually matched a
cluster in *this* run — counting the lines the box holds would tell the reader three overrides
applied when one named a cluster that no longer exists. So the applied count comes from the
matched keys, each unmatched `#k` gets its own console line, and `summary.clusters.method` grows a
`+manual` suffix only when something really landed (a summary that names the asked-for method
after a person overrode it is the same lie as a degraded analyzer printing the model it did not
use). Filling the box while clustering is off is refused before the run: the labels choose names
for objects that will not exist, which is a configuration mistake, not a preference.
- **A computed i18n key is invisible to BOTH audits from the missing side, so the value universe has to be walked
  from the other end.** `nodeType.<type>` and `biblio.col.<column>` are assembled at the call site: the reachability
  audit walks keys that ARE defined (a missing one cannot appear in it) and parity compares the two languages with
  each other, so both stay green while the shipped page prints an identifier. Measured twice on 2026-10-24: the
  settings header read 「nodeType.fuse」 for a whole commit after the fusion node shipped, and a Chinese workspace
  table printed `map` / `source` / `x` as column headers. The guard is therefore the *reference set*, not the call
  site: `test_frontend_i18n_js.py::TestJsNodeTypeWords` walks `engine.workflow.NODE_TYPES` and
  `::TestJsBiblioColumnWords` walks the ten column constants in `services/biblio_schema.py`, both in both languages.
  The same class bit a third time from the other direction: `op.<name>` is assembled from the dropdown arrays in
  `workflow.js`, so `test_frontend_contract.py::TestFrontendCatalog` now walks `ANALYSIS_OPS` ∪ `PROCESS_OPS` and asks
  for a word in both catalogues — measured green the day `cluster_review` shipped, which is the point: the guard is
  there for the next op, not for this one.
  A computed lookup still needs an honest fallback — the type or the stored column shown **as itself**, never the key
  and never a guessed word (`nodeTypeWord()` / `biblioColumnWord()`), and where the word replaces a name the user may
  need to match against an exported file, the name stays reachable (the `<th title>` is the disk spelling).
- **A step writes the column names it is PARAMETERISED on, and the lineage table may only promise those.**
  `cluster_label` took a `group_col` and then built every row as `{'cluster': …}`, so pointing it at 簇 produced a
  table keyed by a column the user never named; the same step sat in `STEP_ADD_ONE`, which tells the canvas "upstream
  columns + 摘要" for a step that actually REDUCES the table to three columns — a chart downstream was promised 节点/频次
  and met them as an absence at run time. Both halves are now pinned (`test_a_summarising_step_declares_only_the_columns_it_actually_writes`,
  `test_the_grouping_column_keeps_the_name_the_user_gave_it`), and a step whose row shape depends on which optional
  columns exist answers `None` — "cannot tell" — rather than guessing a lineage.
- **A shared helper's argument that only describes the caller still has to be the caller.** `_execute_analysis_node`
  handed `_llm_run_ctx(node, 'topic_label', ctx)` for every labelling step; the value sizes the answer and names the
  step in the log, so a cluster review was capped and reported as a topic summary. The name now comes out of the
  steps themselves.
- **`labelLayout.moveOverlap` turns `hideOverlap` off.** For a map series, `{hideOverlap: true}` dropped the two colliding country
  labels (10 painted); `{hideOverlap: true, moveOverlap: 'shiftY'}` brought both back with the collision (12 painted). The graph
  views in this app need `moveOverlap` and use it; the choropleth must not, and only a rendered measurement tells the two apart —
  the option is valid JSON either way.
- **A shipped asset's URL is the app's route, not a guess about it.** `static_url_path` is `''` in this project, so the basemap is
  `/geo/world.json`; `/static/geo/world.json` is a 404 that surfaces as 「地图加载失败」 in the UI and a green Python suite. The
  browser tier fetches the file from the tier's own server before it draws anything, so the route itself is under test.
- **A cartographic claim goes in a build script with its reason, and the figure names what it folded.** The world basemap is
  regenerated by `tools/build_world_geojson.py` from public-domain Natural Earth: it folds Taiwan/Hong Kong/Macau into China (the
  app's China basemap, DataV/高德, draws them that way and the figures are for Chinese-language research), keeps Greenland and
  Northern Cyprus split (that is how WoS address fields arrive), and fills the 65 small states 1:110m omits from 1:50m. Every fold
  loses information, so `biblio_geo.aggregate` reports it on the figure — 「并入其他区域 2 处：England→英国…」 — rather than
  letting a merged polygon speak for itself. The alternative, a second gazetteer of ~250 hand-copied names, would be a table nobody
  can check; instead the join reuses the importer's own alias function, and a test walks the importer's whole country vocabulary
  against the basemap so no name can quietly stop resolving.
- **A panel that repaints its whole body on every keystroke owes its own fields three things, and only a real engine
  sees any of them.** (1) Bare `<input>`/`<select>` markup carries no `.settings-input` class, so it is UA-painted —
  a white box with black text on a dark panel; (2) a native `<select>` is OS-drawn until `CustomSelect` scans it, and
  a rebuilt body has never been seen; (3) the repaint destroys the element holding the caret, so the *second*
  character needs a second click — measured with `document.activeElement === null` after one keystroke. The panel
  marks its typing fields `data-biblio-keep`, records focus + `selectionStart/End` BEFORE assigning `innerHTML`, and
  hands both back after. The node stub has no `activeElement` and no caret, so it can pin the markup and drive
  `_focusedField`/`_restoreFocus` directly, but the three facts above are asserted from computed styles and
  `document.activeElement` in `-m integration` (`test_ui_layout.py::test_the_bibliometrics_panel_names_its_columns_and_keeps_the_caret`).
- **Appending a row under an ECharts canvas without resizing it buries the row.** The canvas is absolutely positioned
  and keeps the height it was given at `init`, so a control bar added afterwards sits UNDER it: it paints, it looks
  right in a screenshot, and the click goes to the chart. Measured in Chrome on 2026-10-24 — the replay bar's 播放
  button answered `ElementClickInterceptedException` naming the `<canvas>` that should have been shorter. Call
  `instance.resize()` after the DOM change; the node stub has no layout, so nothing but a real engine can see this.
- **An affordance that cuts frames out of a figure has to end where the figure began.** Every frame is derived from
  the stored option and each node is scaled against its OWN total, so the last frame is byte-for-byte the whole
  network (scaling against the frame's maximum would leave an approximation nobody measured, and the export button
  would file it). The harness pins that equality, the untouched stored option, and that an export carries the frame
  actually on screen.

## 桌面打包 / Desktop packaging

- **A double-clicked exe can only be accepted by double-clicking it.** Measured 2026-10-24: the shipped
  `CaiXiHui.exe` flashed a console and exited, and my own verification had been `CIXI_NO_BROWSER=1` plus an
  explicit `CRAWLER_DATA_ROOT` inside the workspace — precisely the two things that hid the failing line
  (`main()`'s first statement `root.mkdir()` on `%APPDATA%\CaiXiHui` raising `PermissionError [WinError 5]`).
  `packaging/README.md` already listed "double-click" as step 1 of acceptance; skipping it is why the build shipped.
- **Windows destroys the console when the process exits**, so for a frozen entry point a printed error is an
  invisible error. Every exit path must (a) block in a `MessageBoxW`, (b) append the traceback to
  `startup_error.log` under data root → exe folder → `%LOCALAPPDATA%` → temp, tried in turn. A short sentence goes
  in the dialog, the traceback in the file: a message box cannot scroll. `input('按回车关闭窗口…')` is not
  visibility — it covered two paths and its `suppress` swallowed the EOFError on a redirected console.
- **A location is probed, never declared.** `_root_is_writable()` creates the directory and actually writes and
  removes a probe file; on refusal the next candidate is taken and the refused path plus the OS's own words are
  printed. Antivirus / Controlled Folder Access denying an unsigned exe write access to `Roaming` is the real
  scenario this exists for. `mkdir` alone is not the test: a protected folder can accept a directory and refuse
  the first file inside it.
- **An isolation root must not fall through.** `CRAWLER_DATA_ROOT` is the ONLY candidate when set, and a refusal
  there is a named startup refusal rather than a fallback: silently joining the shared AppData root would let a
  smoke run's `promote_stale_runs()` settle the user's live run. The fallback chain (Roaming → Local → exe folder)
  exists for the double-click default only, and the candidate that already holds a `data/` is tried first so a
  fallback survives to the next launch.
- **The mutex is per data root.** "One server per data root" is the app's rule, so the mutex name hashes the root.
  A root-blind name let an installed copy refuse a portable one, which then had no `instance.json` in its own root
  to open — one flash, no message. Measured in review, not in a live double-click.
- **A failure reporter must not be able to fail first.** `fail_loudly` files the log and shows the dialog BEFORE
  printing: on a redirected console with a non-UTF codepage the first Chinese character raises
  `UnicodeEncodeError`, so printing first loses both the file and the dialog. `_print_safe` degrades to the byte
  buffer (`sys.stdout.buffer`), never back through the stream that just threw — the retry that re-`print`ed
  replacement text to the same broken writer was caught by its own test.
- **The acceptance run is part of the artifact.** Double-clicking `dist/CaiXiHui/CaiXiHui.exe` writes `data/`,
  `logs/`, `mplconfig/`, `instance.json` into the folder the zip and the installer pack, and the existing-data rule
  then pins every recipient's data home to the maintainer's install folder. `prune_dist.py` clears them before
  compression; `portable.txt` and `drivers/` are user choices and survive.
- **Dialogs are frozen-only.** A source run has a live terminal, and an unattended build check must not stall on a
  box nobody clicks: `_message_box()` returns unless `is_frozen()`. The stub in `tests/unit/test_desktop_packaging.py`
  asserts the `MessageBoxW` call really happens when frozen — an early-return test alone kept passing after the
  dialog call was deleted.
- **pip hangs on a restricted workspace at `Looking in indexes`, with the network fine.** It unpacks into `%TEMP%`
  and caches under `%LOCALAPPDATA%\pip`, and both writes are denied. Fix in `build_windows.ps1`: `TMP`/`TEMP`/`TMPDIR`
  → `build/tmp` and `--no-cache-dir`. Reproduced: index answered 200 in 1.5 s, pip printed one line and never
  returned; with the relocation the same install finished.

