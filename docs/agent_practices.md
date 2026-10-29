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
  here because of warnings: **a class-scoped fixture in a class is `@pytest.fixture` FIRST and `@classmethod` SECOND**
  (an instance-method fixture's `self` is discarded before tests run, so any `self.` it sets is invisible to them);
  pytest is unpinned, so CI moved from 9.1.1 to 9.2.0 mid-day on 2026-10-28 and the old order — `@classmethod` on top —
  stopped being registered at all: every such test errored at setup with `fixture '<name>' not found`. Measured with
  both versions in a throwaway venv: the swapped order, a `@staticmethod` fixture and a module-level fixture all pass
  on 9.1.1 AND 9.2.0; only the old order breaks. `tests/unit/gates/test_test_tiers.py::TestClassScopedFixturesAreVersionProof`
  scans the suite for it. Other fixes from warnings: close file responses after reading; never let a cookie-save open a
  **real Chrome inside the fast tier** (the plant swallowed a socket failure, answered 「种入失败」, left a
  `UserWarning`). A no-browser test says so (`profiles_off` in `tests/api/conftest.py`); a dependency leaking its own
  handle is reported to the user, not filtered. Not ours, left visible (never filtered): jieba 0.42.1 (final) imports
  deprecated `pkg_resources` → one `DeprecationWarning` (`jieba_fast` too), and anyio's pytest plugin warns about
  `CallSpec2` under 9.2.0; see `docs/development.md`.
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
  (`astimezone()` with no argument — the same definition `scheduling.store.describe_time` uses for a blank zone), while
  a NAMED zone stays a literal (`'Asia/Shanghai'` → `08:00`), because that one is machine-independent. Reproduce the
  other machine instead of waiting for CI: **Python on Windows honours `TZ`** — measured, `$env:TZ='UTC'` turned
  `astimezone()` into `+00:00` and reproduced CI's single failure, and removing the variable restored `+08:00` — so
  `$env:TZ='UTC'; pytest -q` is a cheap CI-equivalent gate that reads 6501 passed.
- **The `integration` UI tier performs no server writes** — no data-dir switch exists, so a run or upload lands in the
  user's real `data/`/`logs/`. Stub `fetch`.
- **A fail-loudly flag must fire for the run that asked for the guarantee, not for the directory it
  happened to import.** With `CRAWLER_REQUIRE_BROWSER=1`, the session probe in
  `tests/integration/conftest.py` started Chrome for *any* file in that directory — including
  `test_weibo_crawler.py`, whose 66 cases drive a fake driver in 0.9 s and are marked `unit`. The result
  was 66 ERRORs reading `Chrome/chromedriver cannot start: SocketBlockedError`: a confident claim that the
  device tier is broken, from a session that never requested a device. Worse, AGENTS *instructs* the reader
  to override the marker filter to run one device case, so the documented entry point was the broken one.
  Fixed by having `pytest_collection_modifyitems` record whether any selected item carries `integration`/
  `live_ollama` and gating the probe on it — verified on both halves: the browser-free file passes 66 with
  the flag set, and a real device file still starts Chrome (5 passed, 21 s). `tests/unit/gates/test_test_tiers.py`
  now drives the hook with both selection shapes instead of trusting the flag is consulted.
- **A comment naming its callers is a claim, and callers can be deleted around it.**
  `weibo/crawler.py` carried a block headed *"compatibility shims (kept for callers outside this module)"*
  with four methods; measured, each appeared **exactly once in the repository — at its own definition**, and
  the only external-looking hit (`_get_publish_time`) was zhihu's unrelated method of the same name. The
  comment had been true once, maybe, and outlived the callers by months while staying authoritative-looking.
  The check that costs nothing: count occurrences repo-wide before believing a "kept for callers" note, and
  when you move a helper out of a class, count what still names it.
- **A whole-class move is only safe if the copy is proved, not promised.** `PlayerUI` (559 lines, 29 methods,
  every one of them carrying a measured sentence about the real player window) went from
  `hongguo/harvest.py` to `hongguo/player_ui.py` in one pass, and the pass was scripted *with* a check that can
  fail: the moved text must appear in the new file **as one contiguous run**, differing from the source range only
  by the renames the script is allowed to make (the four names that now cross a module boundary lost their leading
  underscore — an underscore name imported by another module is an invitation to copy it rather than reference it).
  Retyping 559 lines of evidence loses evidence silently; a hand-typed 83-line `naming.py` was checked the same way,
  line against source range, precisely because the hand-typed one is the risky one.
  Two ordering rules came out of the first run, both of which cost a cycle: **check before you write** (the first
  version wrote `harvest.py` and only then asserted no stale name survived, so a missing cut range left a second
  `class PlayerUI:` plus an `import PlayerUI` in the same file — recoverable only because the file was committed,
  `git checkout --` and re-run), and **the seams move with the code**: three tests patched `harvest.time.sleep` to
  drive a `PlayerUI` walk. `time` is one module object so they still worked — which is exactly the shape that breaks
  quietly the day the old module stops importing it, so they now patch `player_ui.time`.
- **A rename pass must be written as three rules, not one, because the same word means three things.**
  Moving five modules into `sessions/` (2026-10-27) was 661 references, and two distinct over-reaches came
  from treating them as one string substitution: ① `cookie_manager` is BOTH the module and the jar *instance*
  (`state.cookie_manager`, imported by name into `app.py` and `api/capabilities.py`, reached from tests as
  `app_module.cookie_manager`), so rewriting `cookie_manager.` → `cookies.` broke 28 instance calls in `app.py`
  with an AttributeError that looked like a product regression — the first version was reverted for exactly
  this, and v2 asks per file whether that file also imports the instance; ② `api.browser_profiles` contains
  `browser_profiles` as a *word*, so a word-boundary rule rewrote `from api.browser_profiles import bp` into
  `from api.profiles import ...` while that route file never moved — a `ModuleNotFoundError` at import time,
  which is the loudest possible failure and still only found by running the suite. The rules that survive
  review: import lines by exact form at any indentation, module-attribute call sites only where the file
  cannot mean the instance, and instance spellings (`state.X`, `app_module.X`, persisted SETTINGS keys like
  `cookie_preflight_before_run`, blueprint names, test filenames like `test_browser_profiles.py`) left alone.
  `ruff check` is a cheap and honest first net: it reported 23 F821 (undefined names) and 2 F401 before a
  single test ran, which is the fastest possible way to find out that a ruleset over-reached.
- **`git mv` stages the rename, not the edits that follow it.** Moving the scheduling trio (2026-10-28) went
  `git mv` → rewrite script → hand edits → `git add <the files I remembered>` — and the remembered list named
  only `scheduling/__init__.py`, so `clock.py`/`store.py` were committed **with their old imports**. The commit
  summary still printed the renames plus `M` lines (the `M` was the renames' similarity, not the edits), the
  whole local gate was green because the *worktree* was right, and CI answered `E0611: No name 'cron' in module
  'services'` in two and a half minutes. Rule: after a `git mv`, every moved path is a **new path** that must be
  added explicitly; read `git diff --cached --stat` (or `git status --short` for a leading `RM`/` M`) before
  committing. Local green says nothing about the index — the runner tests the index.
- **Before "creating" a file in this repo, ask whether it already exists — and run the whole family, not the new test.**
  Stage 8's first knife (2026-10-28): I wrote `tests/frontend/page_scripts.mjs` as if it were new. It already existed,
  with a different API (`loadPageScripts(sandbox, {jsDir, only})`), and four harnesses imported it. The write result
  said **updated**, not created — that word is the tell — and `git status --short` showed `M` where I expected `??`.
  What caught it was running every `tests/unit/frontend/test_frontend_*.py` rather than only the new contract:
  58 errors, `SyntaxError: The requested module './page_scripts.mjs' does not provide an export named 'loadPageScripts'`,
  and `git checkout --` restored the file. Two rules fall out: ① check existence first (`??` means new, `M` means you are
  overwriting someone); ② a new test file is not the blast radius of a shared helper — the family that imports it is.
- **A rename pass must not run before the path rules, and it cannot see modules held through another module.**
  Moving `utils/` into `core/` (2026-10-28) ended with two avoidable wounds. ① The rule `\bmachine_deps\b` → `machine`
  was applied to whole files to fix bare-module call sites, and it also rewrote the *string literal*
  `'utils/machine_deps.py'` into `'utils/machine.py'` inside `WINDOWS_TABLES` and the Dockerfile-env scan — a path
  that still existed in prose but nowhere on disk. Path rules must run first, and a word rule must skip quoted spans
  (or the diff must be read for string changes before committing). ② Tests reached the moved module through the
  *production module's attribute* (`bridge.machine_deps`, `harvest_module.machine_deps`), which no import/attribute
  rule for the moved file can see; only the full suite named them (5 failed + 10 errors). A move that renames a
  module should grep for `\.<old name>\b` across tests, not just for imports of the old path.
- **`getattr(x, name, None)` is the seam shape that never reports.** The same family, found by the batched full
  gate (2026-10-28): `tests/live_run_harness.py::real_jar/no_jar` located the cookie jar through
  `getattr(module, 'cookie_manager', None)` with `module` = the imported `app`. The instance had long since moved to
  `state.cookie_manager` (`backend/runtime/state.py:36`), so the lookup answered `None`, the `if manager is not None:` guard
  politely skipped the patch, and **88 live cases redirected only `Config.COOKIE_DIR`** — the jar that decides whether
  to run kept reading the throwaway directory. A live case could therefore crawl with the user's real session while
  claiming it had proved the anonymous path, which is the one thing those two helpers exist to prevent. Nothing failed:
  no AttributeError, no skip, no warning — the fast suite does not run live cases, so this survived several moves in a
  row. Census rules after this: ① search `getattr(<module-ish>, '` in every tier's helpers, not just for
  `app_module.X`; ② a helper that *optionally* patches something must assert the thing it is patching exists
  (these two now import `state` and patch `cookie_manager.cookie_dir` unconditionally, and the 88 call sites lost
  the vestigial argument). An optional seam is an untestable seam.
- **A dotted-prose rule is a code rewrite when it runs over ``.py`` files.** Moving ``crawl_capabilities`` into
  ``capabilities/registry.py`` (2026-10-28) applied ``\bcrawl_capabilities\.`` → ``capabilities.registry.`` to every
  file, so code such as ``capabilities.CAPABILITIES`` (the local alias for the module) became
  ``capabilities.registry.CAPABILITIES`` — an attribute of a module that has no ``registry`` member. ruff named 22
  F821 in 9 test files; three more files still had an alias bound, where the same bug is an ``AttributeError`` at
  run time and **no** linter can see it. Rule: dotted/prose rewrites belong to ``.md`` (and docstrings you edit by
  hand); ``.py`` code is changed by import rules and module-attribute rules only, and the diff must be read for
  ``.registry.``-style artefacts before the suite is trusted.
- **A re-export needs `__all__`, and an order pin is a contract only where order is data.** Collapsing five
  chart-type sets into `services/charts/registry.py` (2026-10-28) hit both. ① `contracts.py` kept
  `BIBLIO_CHART_TYPES`/`NO_X_TYPES`/`BIBLIO_CHART_READS` as re-exports after the literals moved to the registry;
  the PostToolUse ``ruff --fix`` deleted them as F401 — a name imported only to be handed on is *unused* unless the
  module says so with ``__all__``. ② Deriving `ECHARTS_ONLY_TYPES` from the spec table put the types in panel order,
  and a pre-existing test compared it **as a list** against the browser's array. Membership lists that both sides
  only ever test with `in` must be compared as sets; the order pin belongs to the one list the panel actually walks
  (`CHART_TYPES`). Changing the test to a set comparison is the honest fix — silently reordering the specs to satisfy
  an accidental order pin would have made the table lie about the panel.
- **A carve's rename map needs a whole-token guard, and "the file parses" is not proof the wiring exists.**
  Splitting ``capabilities/registry.py`` into ``platforms/<id>.py`` (2026-10-28) was a byte-exact slice move with a
  reconstitution assertion, and still broke twice. ① Plain ``str.replace`` of private atoms made ``_TIMES`` collide
  with the *suffix* of ``COMMENT_TIMES`` (and ``_ACCOUNT`` with ``CATBUS_ACCOUNT``, ``_BOARD`` with
  ``HONGGUO_BOARD``): the first map run produced ``*COMMENTTIMES`` and ruff answered F821 on a name nobody wrote.
  The guard is ``(?<!\\w)OLD(?!\\w)`` for identifiers (no trailing guard for the call-form names that end in ``(``),
  and the carve asserts the old name is gone **as a token**, not as a substring. ② The first version wrote each
  module body without the ``CAPABILITY = `` prefix, leaving a bare ``Capability(...)`` expression statement —
  legal Python, so it imported; ``ruff format`` then wrapped it in parentheses and the failure surfaced only as
  ``module 'capabilities.platforms.zhihu' has no attribute 'CAPABILITY'`` from the assembly. A split must assert
  the names the package will read exist, and the honest proof is a before/after comparison of the **behaviour**
  (here: ``as_dict()`` byte-identical and every mode/field declaration equal), not of the moved text alone.
- **Splitting a data table by AST line spans breaks on parenthesised values; delimit entries by TOKENS.**
  Moving the 4,600-line message catalogue into ``backend/i18n_catalog/<domain>.py`` (2026-10-28) failed twice
  before anything shipped. ① Taking an entry as ``lines[key_line : value_node.end_lineno]`` is right for
  ``'k': 'text',`` and wrong for the multi-line form::

      'k': (
          'a'
          'b'
      ),

  because the parentheses are syntax, not part of the value node — every generated module lost its closing
  ``),`` and failed to parse. The fix is ``tokenize``: an entry ends at the comma token whose bracket depth is the
  dict's own level, which also carries each entry's leading comment lines with it (281 of them, and a wording
  decision's history is in those comments). ② The same walk started the first entry at the ``_ZH = {`` line, so
  that header text landed inside a domain file — the entry start is the line **after** the brace. ③ The proof that
  nothing changed has to compare the **values** (``ast.dump`` per key), not the text, because re-indenting is a
  legitimate transformation; and the split creates a hazard the old single dict could not have: a domain file that
  exists but is not in ``MODULES`` holds messages that can never print, with parity/reachability/``audit()`` all
  still green. So the merge refuses a key claimed twice at import time, and
  ``test_i18n.py::test_every_catalogue_module_is_merged`` compares ``MODULES`` with the files on disk.
- **The UI tier's driver is ``page_load_strategy='eager'``: ``driver.get`` returning is not evidence that a script
  ran.** A CI run (2026-10-28) failed ``test_opening_the_settings_panel_lands_focus_in_and_closing_returns_it`` with
  ``JavascriptException: canvas is not defined`` — while ``I18n``, defined in a LATER script (``app.js``), was fine,
  so the page had booted and one earlier script had not. The same bytes passed locally and on the previous CI run, so
  this is a load race, not a code defect. A test that drives page bindings must wait for them by name (``readyState
  === 'complete'`` plus ``typeof canvas === 'object'``) and, on timeout, fail with the page's own evidence — the
  document's script list and each script's transfer size — instead of letting a bare ``canvas is not defined`` be the
  whole report. All 54 navigations in ``test_ui_layout.py`` now go through ``_load_app``.
- **A harness that reads module files by hand is a second opinion about the split map — and the map
  must also read each file once (measured 2026-10-29, on the ``app.js`` cut).** Three harnesses
  (``harness_menu`` / ``harness_app_state`` / ``harness_schedules``) did their own
  ``argv.map(readFileSync)`` instead of ``companions.mjs``, so when ``LLMSettings`` and ``AppSettings``
  moved out of ``app.js`` their boots died with ``ReferenceError: LLMSettings is not defined`` — the
  exact half-layer shape ``splits.json`` exists to prevent, arrived at by a harness ignoring it. Fixing
  them surfaced the other half: ``harness_schedules`` names ``workflow.js`` **and** one of its
  companions, so naive expansion evaluates a file twice, and in the shared global lexical scope a
  second top-level ``const`` is ``SyntaxError: Identifier 'Outline' has already been declared``.
  ``sourcesWithCompanions`` therefore dedupes per call (owner still first, never dropped — a first
  attempt that registered the owner before emitting it deleted ``workflow.js`` from every harness and
  was caught by 931 errors, not by luck). The same knife moved the *static* scans onto
  ``static_assets.js_text('app.js')`` (``_inputMap``, the ``set.`` ask-list, deleted keys, dock
  wiring): a by-name grep reads a moved file as an absent fact, which is a check that quietly stops
  checking. ``I18N_USERS`` was a hand-kept list of 14 files; the tree has 37, so 709 literal
  ``I18n.t('…')`` calls were outside the word audit while every one of them was in fact clean — it is
  now derived (``js/**/*.js`` minus the ``i18n/`` data) with a scope floor, because "add the new file
  to the list" is the step that gets forgotten and reports nothing.
- **A prefix→directory move has five traps the rename rules cannot see (all hit in one group).** Moving eleven
  ``services/biblio_*`` modules into ``services/biblio/`` (2026-10-28) went 122 references clean on the first pass and
  still failed five ways: ① **``ruff --fix`` deletes the import a pending rename is about to use** — after
  ``from services import bibliometrics`` became ``from services.biblio import metrics``, the call sites still said
  ``bibliometrics.build``, so the hook removed ``metrics`` as unused and the next pass reported F821; edit **call
  sites before import lines**, every time. ② **A multi-name from-import is two names in one line**:
  ``from services import biblio_formats, biblio_sources`` matched the first rule and produced
  ``from services.biblio import biblio_sources, formats`` — collection failed with a named ImportError; the rule set
  needs one rule per *name in the list*, not per statement. ③ **A module that moves one directory deeper changes every
  ``Path(__file__).parents[N]``**: ``biblio_geo``'s basemap pointed at ``backend/services/static/geo/world.json`` and
  34 geo tests went red; grep ``__file__`` in the moved set before running anything. ④ **A module alias can collide
  with a local variable in a consumer**: ``metrics.py`` assigns ``cluster = …`` inside a function, so the new
  ``cluster.cluster_graph(…)`` was a use-before-assignment (F823) — import it ``as clustering``. ⑤ **``git mv`` stages
  the moves; it does not stage the sibling importers**: the commit omitted ``backend/api``, ``engine``, ``i18n``,
  ``nodes`` and ``stores`` until ``git status`` was read, and was amended before it left the machine. The proof the
  move is complete is a **residual scan that refuses to finish** (``services[./]biblio_*`` anywhere), not a green
  suite — the suite had already run green locally before the missing files were noticed.
- **Count references by the NAME a file binds, not by the module path (2026-10-28, found on the third group).**
  Before moving ``net_probe`` the inventory grep for ``services\.net_probe`` reported 2 references; the move then had
  to rewrite **50** ``net_probe.`` call sites, because the callers bind the module with ``from services import
  net_probe`` and the module path never appears again. The inventory that works asks for the binder
  (``from services import <old>``) and then greps the bare name. Related, same day: ① a **bare module reference** —
  ``monkeypatch.setattr(net_probe, '_session', …)`` — is invisible to an attribute rule (the name is followed by a
  comma, not a dot) and shows up only as F821 (23 sites across three groups; each fixed by hand after reading the
  line); ② the multi-name import ``from services import latex_charts, visualizer`` matched the first rule and left the
  second name behind, exactly like the biblio case — the rule set needs one rule per *name*, not per statement; ③ the
  post-edit ``ruff --fix`` deleted the freshly re-added import in a test one more time (usage and import must land in
  that order, never the reverse). Batching three groups behind ONE full-suite run was the user's call after the
  per-group 8-minute run became the bottleneck: each commit still carries its own moves + call sites, and CI only
  ever sees the final HEAD.
- **A readiness sentinel that shares a prefix with success is a tolerance arm wearing a costume.**
  `test_a_run_detail_splits_its_workflows_without_growing_a_bar` failed on CI with "the detail row never
  appeared" while the gate before it said everything was fine — because its bounded poll returned
  `"ok | the detail row never rendered"` on timeout and the Python side asserted
  `outcome.startswith('ok')`. The timeout arm therefore passed the check whose whole job was to notice
  the timeout, and the reason was printed only after the layout had been measured off a missing element.
  Fixed by removing the second round trip: the test now expands **and** measures inside one
  `execute_async_script`, returning `{found, names, cut, tallies, …}` or `{found: false, rows}` /
  `{found: false, rejected}` — so there is no sentinel to lie and nothing between the row appearing and
  being read. The other half of the same race: the stub must be installed **before** anything renders,
  because the page's own boot reads `/api/runs/list` with the real fetch, and a repaint drops the
  expansion row the test is about to add.
- **An async browser seam must resolve on the DOM, and its error arm must not be `done()`.**
  `test_a_run_detail_splits_its_workflows_without_growing_a_bar` flaked on CI as "the detail row never appeared".
  The earlier fix had wrapped it in `Promise.resolve(runsManager.detail(...)).then(() => done(), () => done())`, which
  was wrong twice: `detail` renders in a task *after* its promise settles, so the test still measured whatever the
  next WebDriver round trip had happened to paint — and the rejection arm answered `done()` as if nothing failed, so
  the one thing that could have named the cause was thrown away. The correct shape is: await the promise, **keep the
  outcome**, then poll the document for the element and return only when it exists (bounded, so a real regression
  fails with a sentence rather than hanging). Local runs of that file never rejected, which is the point — the test
  can now only pass by having actually rendered. Lesson generalizes: a tolerance arm in a test helper is the same bug
  class as a tolerance arm in a crawler, which is what AGENTS' "a warning is a test that noticed something" is about.
- The `live_site` tier retries a crawl once **only** when the crawler itself reported `login_wall` (risk control can
  answer a valid session a login redirect once). An empty that NAMES its refusal (wall or risk) is the site's answer —
  assert the naming; an unnamed empty is real "found nothing" and stays red.

## Run, resume and record invariants

- **One server per data root, by design (local single-user tool).** `RunStore.__init__` calls `promote_stale_runs()`,
  which marks every run still `running` as interrupted, so a second instance on the same `data/` kills the first one's
  live run. `CRAWLER_DATA_ROOT` (config.py) gives a process its own `data/`+`logs/` — the `/smoke-verify` boot and the
  UI tier's self-booted server use it.
- **One run at a time; a busy server queues instead of refusing.** `begin_run()` owns the whole start path, so the queue
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
  two field lists (`crawlers/commenting/session.py` says why: every comment of one article would then share a key and all but
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
  path — it may never move the live console.** `_push_log` (runtime/state.py) writes through to `app`'s `RunLogWriter` via the
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
- **A line printed by a side effect that runs per PAGE LOAD is noise by construction** (measured on the CI runner,
  2026-10-27). The app boot fires `POST /api/data/clear` to sweep orphaned files (`app.js`), and that route logged
  「清理孤立文件 0 个，保留 0 个…」 unconditionally — so every tab the user (or a browser test) opened added another
  identical row to the run console. After ~80 page loads the console test's own three stubbed lines were buried under
  eighty of them and the device tier failed on CI while passing here, where fewer page loads happened between the two
  tests. The rule is the one `services/runs/housekeeping.py` already states for the automatic sweep — **silence is the
  normal case, say something only when something went** — and the manual 清理 keeps its answer through its own toast
  built from the response, so nothing loses feedback by the line being conditional. A test that opens a page is not a
  cheap read: it is a writer of the console, so anything printed at page-load time is multiplied by the suite's page
  loads and eventually lands on a different test's assertion.
- **A job a page starts by itself must be awaitable, or it races everything after it.** `workflow.reconnectConsole()`
  reads `/api/workflow/status?tail=` during boot; a browser test that empties `#console-output` and then reads it back
  was reading the *server's* history, painted after the clear by the read still in flight. Two fixes, one product and
  one test: the method now keeps its in-flight promise (`_reconnect`, shared, released in `finally`) so a caller can
  wait for work it did not start — which also stops the boot and a 「立即执行」 fire from each fetching the tail, each
  opening the panel and each shouting 「已重新连接控制台」 for the same run (`harness_console.mjs` measures `asked: 1`,
  `reconnectedToasts: 1`, and the same scenario against a non-sharing gate reports `2`/`2`); and the tier gained
  `_settle_console_replay(driver)`, called **before** any test clears the box. Sharing that promise is exactly what
  makes the second console test correct too: once the boot's replay is in flight, a test that calls
  `reconnectConsole()` again is handed *that* promise, so its stubbed tail would never be read.
- **Anything that chooses data, cost or a name is refused BY NAME, never guessed** (a mode, a `select`, a step's select
  or missing column via `data_analysis.validate_step`, an analyzer's `method`/`mode` via `app.enum_param`), and refusals
  `raise` rather than returning `[]` — else the node settles DONE over an empty table. **Read a switch, never compare
  it** (`core.refs.as_bool`; blank = the declared default); a form shows a stored value off the list
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
    `Mode.needs_session` says needs a login when `sessions.preflight.has_session_to_test` finds neither that account's
    cookie file *nor* a profile still carrying it — blank included, because blank IS an account (默认账号), not a
    wildcard.
  - **Every account has one name and one spelling:** the default login is named `default` (the box shows it, never a
    blank; the blank is only its old filename), folded at the ONE point `CookieManager.key`/`path_segment` (`''` ⇄
    `default`, lowercase always) — `Work` and `work` are the same session, because a case-insensitive filesystem cannot
    hold two logins under one spelling — so `sessions.profiles`, the preflight cache and the JS box all route through
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

**A fire is the same start as a manual Run, because `begin_run` owns the whole start path.** `scheduler` may not import
`app` (the Blueprint imports the scheduler, so that would be a cycle), so app.py installs two seams at import:
`set_run_starter(engine.run.start_scheduled_run)` and `set_canvas_source(engine.run.scheduled_canvas)`. `start_scheduled_run` then
calls `begin_run` — the *only* start path — which is what makes a busy server **queue** the fire exactly like the Execute
button instead of racing it (`queue:false` keeps the 400 for fail-fast callers, so a second path would have looked
plausible). The scheduler is refused by name (`sched.notWired`) when nothing was wired, because a silently-dropped fire
would look like "the scheduler does not work on this box" with no line saying why.

**A crash in the starter is not a refusal.** `_fire` records `error` for an exception (with the traceback in the log file)
and `refused` for an executor saying no. They mean different things to the user reading the task's history — "my canvas
needs a model" versus "something is broken" — and the first version recorded both as `refused`. A crash also must not stop
the clock for every other task, so the `except` is per-task and the tick continues.

**One rule about a canvas, asked three times, from one function.** `engine.run.scheduled_canvas` wraps the existing
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
arithmetic and no status vocabulary of its own; `tests/unit/frontend/test_frontend_schedules.py` drives the real file under node to
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
cannot fire the same slot twice. The edges a user hits once a year are pinned in `tests/unit/scheduling/test_cron.py`: a
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
in that comparison until cross-run monitoring (`services/biblio/monitor.py`) walked in front of it:

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
  `::TestJsBiblioColumnWords` walks the ten column constants in `services/biblio/schema.py`, both in both languages.
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
  `desktop/README.md` already listed "double-click" as step 1 of acceptance; skipping it is why the build shipped.
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
  box nobody clicks: `_message_box()` returns unless `is_frozen()`. The stub in `tests/unit/desktop/test_desktop_packaging.py`
  asserts the `MessageBoxW` call really happens when frozen — an early-return test alone kept passing after the
  dialog call was deleted.
- **pip hangs on a restricted workspace at `Looking in indexes`, with the network fine.** It unpacks into `%TEMP%`
  and caches under `%LOCALAPPDATA%\pip`, and both writes are denied. Fix in `build_windows.ps1`: `TMP`/`TEMP`/`TMPDIR`
  → `build/tmp` and `--no-cache-dir`. Reproduced: index answered 200 in 1.5 s, pip printed one line and never
  returned; with the relocation the same install finished.
- **A UTF-8 Chinese string in a `.ps1` can stop the build from starting at all.** Windows PowerShell 5.1 reads a
  script **without a BOM** in the machine's ANSI codepage, so a `Write-Host '中文…'` literal arrives as GBK bytes;
  one of those bytes looks like a quote terminator and the parser reports `字符串缺少终止符` — on a line hundreds of
  characters away from the real one. Measured: `build_windows.ps1` aborted before any step ran, and because the
  failure was a parse error the pipeline still looked like success. `desktop/build_windows.ps1` is therefore
  ASCII-only (pinned by `test_the_files_other_tools_parse_are_pure_ascii`), and the builder's own messages stay
  English like the
  rest of the file — user-facing Chinese belongs in `backend/i18n.py` / `app.js`, not in a batch script. To find this
  without running the build:
  `[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errs)`.
- **The same locale trap eats `requirements-*.txt`, and one em dash is enough.** pip's `auto_decode` uses
  `locale.getpreferredencoding()` and honours UTF-8 **only** with a BOM, so a Chinese comment — or a single `—` —
  inside `desktop/requirements-runtime.txt` is `UnicodeDecodeError: 'gbk' codec can't decode byte 0x94` on the very
  first pip call. It cost a second full build attempt that never got past `Build environment`. Cheap local proof
  before building: `open(p,'rb').read().decode('gbk')`. The test checks the raw bytes of the ps1, both
  `desktop/requirements-*.txt` **and the two root requirement files a user installs from** — an em dash in
  `requirements.txt` is the same crash one keystroke away from the README's install command, and it sat there because
  only the build's own file had ever been measured. A file that legitimately needs Chinese (`installer.iss`, whose
  wizard text is Chinese) declares it with a UTF-8 BOM instead, which the same test asserts.
- **UPX: do the pass yourself, and never trust a packer that skips quietly.** PyInstaller's `upx=True` compresses
  nothing when it cannot find the tool and reports that only in a line people scroll past, so "we shipped the
  compressed build" becomes a guess. `desktop/compress_dist.py` runs after the prune step with `upx --best --force`,
  treats a missing `upx` on PATH as a **build failure by name**, verifies every output with `upx -t`, restores any file
  it cannot verify (a half-packed binary is the flash-quit bug class again, discovered by the user), skips files that
  already carry the `UPX!` marker, and prints the byte delta. Two measured details: UPX 5.0.2 **rejects**
  `--no-version-info` (exit 1 — which would have made every file a silent no-op), and `--best` costs ~30 s on the
  20 MB OpenBLAS DLL, so the pass is parallel across 307 PE files. And it is not free at start: packed PEs unpack
  into memory as they load, so size and boot time are measured together, on the same machine and data root, only
  switching `-NoUpx`.
- **Dead payload is only dead when you can name the reader.** Measured and dropped by `prune_dist.py`:
  `jieba/lac_small` (13 MB — reachable only through `cut(..., use_paddle=True)` with paddle installed, which no
  analyzer asks for); snownlp's Python-2 marshals `seg.marshal`/`tag.marshal`/`sentiment.marshal` (`snownlp/utils/tnt.py` and
  `snownlp/classification/bayes.py` both append `.3` on Python 3, so on 3.11 the extension-less copies are read by nothing
  while the `.3` files are the models — a suffix three characters long decides whether the sentiment fallback boots);
  and the training corpora `seg/data.txt`, `tag/199801.txt`, `sentiment/neg.txt|pos.txt` (only `train()` opens them).
  What is **not** droppable, measured: `scipy/spatial` and `scipy/interpolate` (reached through `scipy.stats` and
  `sklearn.cluster._optics` / `metrics.pairwise` — excluding them kills `from app import app` inside the frozen
  launcher) and matplotlib's DejaVu fonts (the fallback when SimHei/YaHei are missing).
- **A file's extension is a promise to some readers and a suggestion to others.** `backend/static/icon.ico` was the
  app's PNG renamed. Three consumers read that one file and each told a different story: the browser content-sniffs
  it, so the site favicon looked correct for the file's whole life; PyInstaller copied the invalid bytes into
  `CaiXiHui.exe` and printed `Copying icon to EXE` as if it had succeeded; Inno Setup refused to compile the
  installer at all — `Resource update error: Icon file is invalid` — and said so only *after* the folder build and the
  zip had taken their ten minutes. Fix: `tools/build_icon.py` generates the ICO from `backend/static/icon.png`
  (16/24/32/48/64/128/256), `tests/unit/desktop/test_desktop_packaging.py::TestTheIconIsWhatItsNameSays` parses the directory
  and every frame offset, and `build_windows.ps1` checks the four header bytes **before** `Write-Step
  "Build environment"`, with an ordering assertion so the free check cannot drift after the expensive ones. The
  remaining question is answered on the artifact, not by reading the format spec: `[System.Drawing.Icon]
  ::ExtractAssociatedIcon($exe)` is what the shell does, so it is what acceptance runs.
- **A background build's exit code is only as trustworthy as the command that wrapped it.** The notification for the
  run that failed on the icon said *completed (exit code 0)*, because the command I launched ended with an `echo`
  that reported the summary — the log's own last line was `powershell exit=1`. Two builds in this session were lost
  the same way (the other was the `.ps1` parse error). Launch the build as the **last** thing the shell does
  (`powershell … > log 2>&1`) and read the log's own summary lines as the evidence; never append a `; echo` after it.
- **A packer's warning is a switch you think is on.** Inno Setup 7 prints `The [Setup] section directive
  "LZMAUseSeparateProcess" is obsolete and ignored`. It changes nothing about the bytes we ship, but it makes the
  `.iss` a description of a build that isn't happening, so the line is gone. Same class as the matplotlib/GUI-backend
  exclusions: an option the tool ignores is documentation, not configuration — and `installer.iss` is now verified by
  compiling it, not by reading it.

## Lint 标准 / Lint standards

### pylint is three tiers, because one honest answer does not fit three kinds of file

Product code takes `.pylintrc`; `tests/` takes `.pylintrc.tests`; the `backend/test_*.py` measurement scripts take
`.pylintrc.probes`. **Nested config files are ignored by pylint** — measured: a `.pylintrc` in a subdirectory did not
apply to files under it (the run from the repo root used the root config for both), so each tier is its own
invocation with an explicit `--rcfile`. `tests/unit/gates/test_lint_gate.py` pins the shape of the exemptions: the pytest
idioms may not appear in the product list, `C0413` may not either, and `exclude-protected` is a named member, not a
message.

- **`pylint packaging` was never our folder — and the directory is now `desktop/` for that reason.**
  A bare target named `packaging` resolved to the PyPA distribution in site-packages, so the gate
  lints a third-party library and passes over our files. Two independent fixes, both kept: the
  workflow lists FILES and refuses an empty list (a gate that checks nothing is worse than no gate),
  and no project directory may share a name with an installed distribution, because every tool that
  resolves imports by `sys.path` — not only pylint — will pick whichever comes first.
- **Why the test tree is exempt from exactly three messages.** `W0621`: a fixture is requested BY NAME, so the test
  parameter and the module-level fixture must share it — renaming either stops collection. `W0613`: an autouse or
  requested fixture's argument IS the use (`clean_globals`, `seeded_logins`). `W0212`: half this suite exists to
  watch a private field, because the public surface is what is being questioned. Those three are still findings in
  product code, where the same access means a helper was left private by accident.
- **`global` in product code is a seam, not a smell — where it is one.** All 14 sites are state a caller rebinds on
  purpose: the store singletons a conftest points at a tmp data root, `settings_store`'s cache, `state.set_log_sink`,
  the scheduler's starter and its counters. `W0603` is exempted in `.pylintrc` and `.pylintrc.probes` with that
  written down, and NOT in `.pylintrc.tests` — a test that rebinds module state is a different problem.
- **A checker's false positive is usually an imprecise type, and fixing the type is the real fix.**
  `_RUN_QUEUE: list = []` made every queue subscript an `E1136`; naming the element (`QueueEntry`) plus declaring the
  local in `start_next_queued` cleared all ten. `report_service`'s `E1135` survived a `TypedDict`, because pylint
  traces the returned dict back to the `None` literal in `DEFAULT_OPTIONS`; a frozen `@dataclass` with typed fields
  is what it can read. `_abort = None` on the crawler class produced `E1102 not-callable` — annotating the contract
  (`Callable[[], bool] | None`) and reading `self._abort` instead of `getattr(self, '_abort', None)` removed both the
  error and the defensive lookup. `sys.stdout._original` became `unwrap()` on the tee: a method that answers the
  question, instead of a caller reaching into someone's private.
- **`webdriver.Chrome` is invisible to checkers** because `selenium.webdriver`'s exports are lazy (`__getattr__` over
  a table). Importing `selenium.webdriver.chrome.webdriver.WebDriver` by name removed the only inline
  `# pylint: disable` in the crawler core. **It also moved a test seam**: `tests/unit/crawlers/test_driver_options.py` patched
  `base_module.webdriver.Chrome`, and the suite only complained when it actually ran (11 ERROR, not FAILED, and 53
  passed hid them). Patch the name the module constructs — and read the whole summary line, not the pass count.
- **`W1203` cannot be fixed by lazy `%` here.** `tests/unit/i18n/test_i18n.py::TestNoHardcodedConsoleText` counts `%s`
  tokens as untranslated prose, and `t(key) + ': %s'` only trades the finding for `W1201`. The console-level answer
  is the pattern the rest of the codebase already uses: the reason travels as a named catalogue slot
  (`t('misc.cookie_save_failed', err=...)`), in both languages.
- **Unused arguments find real bugs.** `sessions.profiles.status(size=False)` was documented twice as skipping the
  profile walk and never read the flag: `/api/cookies/status` re-walked every profile (measured 236 MB) once per
  account row. That is what the check is for.
- **The formatting hook eats an import added before its first use.** `ruff check --fix` deletes the unused import at
  that moment, so `import math` added one edit early silently disappears (`F821` later). Add the import in the same
  edit that uses it.
- **…and it eats one added a second too late, from the other side.** Moving `from scipy import stats` into the function
  that uses it, while the module-level twin still existed, made the local name a **redefinition** — ruff's `F811`
  autofix deleted the new one, and six suites then died on `NameError`. When relocating an import, delete the old
  binding in the same edit or first; a green `Edit` result is not evidence the line survived, so grep for the symbol
  before believing the refactor.

### A lint gate is only a gate if it linted everything

- **只 lint 改动文件 = 没 lint。** Running pylint over just the touched files is how three *already committed*
  violations survived in the CatBus round: a `W0108` lambda in `test_catbus_bridge.py`, a `W0212` reaching into
  `bridge._RUNNABLE_STATES`, and a `W0201` on a stub's attribute. Each had passed a "both tiers 10.00/10" claim
  produced from a partial target list. The gate is the whole product tree (184 files) and the whole test tree
  (**257** `tests/**/*.py`, not only the **246** `test_*.py` — conftest and helpers are linted too), every time.
- **The target list must be absolute, forward-slashed and free of `\r`.** A pylint list generated relatively makes
  `tests/` helpers report a dozen false `E0401` (they import each other by a path the relative run does not have);
  backslashes written from Git Bash are eaten into `backendapp.py`; and Python's `write_text` on Windows writes CRLF,
  so every argument ends in `\r` and all 184 files report `F0001` before any code is read. Generate the list as
  absolute paths with `/` and invoke through `tr -d '\r'` (CI enumerates them itself, see the next bullet).
  The reproduction lives in `build/make_lint_lists.py` (ignored).
- **PowerShell: `@( (Get-ChildItem a), (Get-ChildItem b) ) | ForEach-Object FullName` lints NOTHING.** Measured on
  the runner on the first CI run that carried the pylint steps (run 40450524569, `Pylint — product`, 0.7 s): the
  comma builds an array of **two arrays**, and `ForEach-Object -MemberName` does not member-enumerate an array handed
  to it — `$t.Count` was 2, `$t[0]` was empty, and pylint received two blank arguments and printed
  `No files to lint: exiting.`. The guard `if (-not $targets)` did **not** fire, because a non-empty array of
  empties is truthy: the only thing that saved this from being a silent green was pylint's own refusal. The shape
  that works is statements inside `@()` (they flatten) plus a per-object projection:
  `@( Get-ChildItem … ; Get-ChildItem … ) | ForEach-Object { $_.FullName }`. Both CI steps now also print
  `linting NNN files`, because a gate that does not say how much it checked is not auditable after the fact.
  Pinned by `tests/unit/gates/test_lint_gate.py::TestTheStandards::test_ci_runs_the_two_tiers_it_can_and_says_why_not_the_third`.
- **A gate whose machine differs from the runner's proves less than it says.** The product tier read
  10.00/10 for weeks on this box and reported **19 × `E0401`** the first time it ran on CI (run
  40457992451): `torch`, `transformers`, `onnx`, `sentence_transformers`, `bertopic`, `uiautomation` —
  all declared in `requirements-optional.txt`, all imported inside a guard that probes for them, and
  all deliberately absent from a hosted runner (AGENTS keeps the multi-gigabyte torch out of CI). The
  fix is `ignored-modules=` in `.pylintrc` — **by module name, never by switching `E0401` off**, so a
  misspelled `import tranformers` is still a finding — and `test_lint_gate.py` now pins both
  directions of that list: nothing exempted that is not a declared optional dependency, and nothing
  the product code imports that is left out. The scan reads the same four roots CI enumerates, so a
  new optional runtime imported by product code forces this argument instead of reddening CI by
  surprise. `mitmproxy`/`pyarrow`/`hdbscan`/`umap-learn` are declared optional but never imported by
  name (they are probed as executables or reached through pandas), and are therefore NOT exempted.
- **A byte pin and `* text=auto` cannot coexist.** `vendor/echarts.min.js` is pinned by SHA-256 because
  a third party must not be able to change what our users' screens execute without a diff here. The
  repository's blanket `* text=auto eol=lf` rule converted its 45 CRLF pairs at commit — and upstream
  really ships those CRLFs (measured: the CDN bytes hash to the recorded pin). So the blob in git was a
  **different file** than the one reviewed, and the divergence chose its own witness: CI checks out the
  blob and failed the pin, while this box read the copy it had written and passed. Fixed by
  `backend/static/vendor/** -text` + `git add --renormalize`, and guarded by
  `test_vendored_assets.TestThePinnedBytesAreTheStoredBytes`, which asks `git check-attr text` and hashes
  `git show :<path>`. The general shape: **a check that reads the working copy proves nothing about what
  is stored** — when the contract is about bytes, assert on the bytes the store holds.
- **A stub that fakes one backend silently assumes the machine picks that backend.** The three bert
  analyzer suites installed a fake `transformers.pipeline`, and were green for weeks because this box has
  torch. CI installs `requirements.txt` (which now carries `onnxruntime` + `tokenizers`) and never torch,
  so `bert_runtime()` answered `'onnx'`, and the product refused a model name that is not a directory —
  correctly, and 13 cases reddened with a sentence about a loader nobody had asked for. The fix is not a
  skip: the case states which runtime it is describing (`monkeypatch … bert_runtime → 'torch'`). A probe
  on this box reproduced the runner's package set (torch hidden, ONNX present) and showed both halves:
  unpinned → the CI refusal, pinned → answers through the stub. Same lesson, second instance: 红果's
  "missing player is refused by name" dropped the stack seam and so only tested the player on a machine
  where mitmproxy/uiautomation are installed — on CI it read the stack refusal instead. Now the case says
  the stack is present, and a second case pins the stack refusal itself (naming the two packages and NOT
  blaming the player).
- **`subprocess.run` without `check=` is a finding worth taking literally.** `pylint` W1510 sent two of
  the cases above to exit 4 on the tests tier. `check=False` is the honest spelling when the test asserts
  on `returncode` itself — and in `test_boot_import_budget` it turned an `AttributeError: 'NoneType'
  object has no attribute 'strip'` (seen once on the runner, unreproducible here) into an assertion that
  carries the child's return code and stderr. When a failure cannot be reproduced, the fix is to make it
  name itself. That produced the decisive measurement on the next run: `CompletedProcess(returncode=0,
  stderr='', stdout=None)` — the child had run and exited cleanly, so the pipe, not the boot, was what
  differed on the runner. **A test should read its answer through the transport the claim depends on**,
  and "which modules did `import app` load" does not depend on a captured stdout: the child now writes
  its report to a `tmp_path` file and the parent reads that, so the assertion is about the import graph
  and nothing else. Two smaller lessons in the same shape: the `assert x is not None` step was worth
  keeping as `assert report.is_file()` (it names the mechanism it protects), and a harness fact is only
  knowable from the harness — this one took two CI runs because no local configuration reproduced it.
- **Fixing one step of a pipeline does not prove the next step ever ran.** Once both pylint tiers
  passed on the runner, CI reached the **fast tier for the first time in this repository's history**
  and reported **27 failures** (run 40461763819) that were all green on the box that wrote them. The
  five shapes found: a stub that patches the torch pipeline while the product now loads ONNX
  (13 × `TestBertMode`); a byte-SHA pin on a vendored `.js` that checkout re-writes line endings for;
  a `main()` that correctly refuses when `upx` is not on `PATH` while its test asserts exit 0; a
  subprocess whose `stdout` came back `None`; and one refusal test that reads a machine-local path.
  The rule is the same one twice: **a green step nobody has ever seen run is a claim, not a gate** —
  so each of those is fixed by making the *test ask the machine* (probe the runtime, pass the tool
  path, normalize what is compared), never by widening the assertion.
- **A wrapper that reports the exit code is part of the gate.** A background command ending in `echo done`, or piping
  the checker through `tail`, reports 0 even when the checker failed — the measured exit status must be the shell's
  last one and the evidence must be the checker's own summary line. The same trap exists one layer up: a redirect to
  a directory that does not exist (`build/fast.log` before `mkdir build`) never runs the suite at all.

## 三维能力模型 / Platform × engine × function

- **A computed label key is an audit blind spot, again.** The CatBus manifest can grow modes without a Python change,
  so their labels must be a literal table (`CATBUS_MODE_LABELS`) and a contract test must walk the *manifest's* key
  set — asking only the keys already in the table proves nothing. The same mistake in three earlier places (node
  types, biblio columns, op names) is why this is a standing rule.
- **A function the engine cannot run is still shown, greyed and named.** Removing it paints a stored value as option
  #0 and makes the panel lie about the run. The three-dimensional payload therefore carries `engines` per platform,
  `engines` + `cells` per function, and the adapter's own `reason` prose; validation refuses the same pair before the
  run is started. The frontend holds no list of its own.
- **A seeded default is not a condition the user chose.** The canvas seeds every platform's field defaults onto a new
  node, so `board=popular` exists on a posts node that never asked for a board. Refusing an unconsumed parameter has
  to compare it with the declared default first, or every CatBus node dies on a field it never filled.
- **Read the manifest, never a list compiled beside it.** The CatBus adapter derives its read modes from the platform
  registry (`write()`-declared commands carry `mutating` and are excluded mechanically); 采析绘 derives CatBus modes
  from that manifest. A second table on either side is the copy that falls behind. The one deliberate exception is
  `msg *` (private messages), excluded as a resource with the reason written in the code.

## 启动路径与 BERT 运行时 / Boot path and BERT runtimes

- **Process start is a budget, and it was being spent on libraries no request asked for.** Measured here:
  `python -X importtime -c "import app"` = **9.2 s**, of which **5.4 s** was a single top-level
  `from sklearn.ensemble import IsolationForest` in `analyzers/anomaly.py` — `app` imports `analyzers`, `analyzers`
  is an eager barrel, so all of sklearn loaded even for a canvas with no ML node. Moving the heavy third-party imports
  (sklearn/scipy/matplotlib/joblib) into the functions that use them brought it to **2.07 s**. The `analyzers`
  barrel itself is deliberately untouched: `api/analysis.py` reads `EmotionAnalyzer.ML_MODEL_NAME` at class level,
  `tests/api/test_node_matrix.py` resolves op→class through `importlib`, `tests/conftest.py` clears
  `sys.modules['analyzers.ml_base']._shared_classifiers`, and `test_multi_model_api.py` patches
  `app_module.<AnalyzerClass>` — a PEP 562 lazy barrel would break all four at once.
- **Pin a budget with a module census, never with a stopwatch.** `tests/unit/foundation/test_boot_import_budget.py` walks the
  module bodies with `ast` (names the file to fix) and imports `app` in a fresh subprocess to read
  `sys.modules` (catches transitive leakage). A wall-clock assertion would fail a slow runner and pass a fast one
  while proving nothing either way.
- **Two frontend-adjacent traps found by the same move:** `services/biblio/cluster.py:111`'s return annotation
  `tuple[TfidfVectorizer, …]` is evaluated at `def` time, so the class has to be quoted *and* kept visible to
  readers (`if TYPE_CHECKING:` — ruff calls an unquoted string to a function-local import `F821`); and in
  `services/charts/visualizer.py`, `matplotlib.use('Agg')` plus the CJK `rcParams` block must travel **with** the import
  into one helper, because splitting them is how a server gains a window or a figure of tofu boxes instead of Chinese
  labels.
- **The desktop self-check was sitting between picking the port and binding it.** Four filesystem probes and a TCP
  connect ran on the main thread after `pick_port()`, so the console printed the URL while nothing could accept it.
  It now runs on a daemon thread: the mutex and `instance.json` are already written ahead of it, so nothing about
  single-instance ownership changed, and the exception path prints a named line because four absent lines look
  exactly like a quiet pass. Its five lines are emitted as **one** write — Flask's own startup lines land on the same
  console from another thread and would split a five-write block apart.
- **A frozen app's ONNX export must be fed its mask, not let it build one.** Tracing transformers' own
  `attention_mask` handling freezes `masking_utils`' `if padding_length := … > 0` branch (the `TracerWarning` says so
  out loud): the exported fp32 graph answered up to **1.0 logit** differently depending on how the batch happened to be
  padded, while agreeing to 4e-07 on unpadded input — measured, not theorised. Fix: the graph takes
  `position_ids` and an additive `attention_mask_4d` as **inputs** built by the caller; the same comparison then
  measures **3.1e-06** max absolute logit difference over a batch with 243 padding cells. `attn_implementation='eager'`
  is required for the same reason (sdpa's shape-dependent booleans bake), and `dynamo=False` is stated rather than
  inherited because torch 2.9+ flipped the exporter default and the dynamo path needs `onnxscript` (not installed).
- **`torch.onnx.export` leaves the module in training mode.** A verification pass computed right after the export
  therefore runs BERT's 10% dropout: the "graph is wrong" number changed on every run (0.14, 0.35, 0.99) while the
  graph itself was stable to 3e-07. Call `model.eval()` again before comparing — and note the reference must be the
  model's own **2D-mask** call, which is the answer the app is trying to reproduce.
- **Quantisation is judged on decisions, not on distance.** int8 (per-tensor and per-channel) holds macro-F1 within
  noise but flips **6.7–14.2%** of the labelled rows' class, because the loss shows up on near-ties — where the label,
  not the score, is the answer the user puts in a table. fp16 flipped none and costs 195 MB against int8's 98 MB, so
  the pack ships fp16. Record agreement *and* ΔF1 *and* bytes; a single number hides which of the three is the reason.
- **A stub that invents an API ships an `AttributeError` in the packaged app.** The `tokenizers` crate exposes
  `type_ids`; the hand-written fake said `token_type_ids`, and every stubbed case stayed green until the real graph
  was run. `tests/unit/ml/test_bert_onnx_real_crate.py` therefore uses the **installed** crate (a declared dependency)
  and fakes only the inference session — the piece a unit test genuinely cannot ship.



## 文献导入与真实导出件 / Bibliographic imports and real exports

- **A real export file is the only authority on what a source exports.** Everything below was
  measured by running the product's own readers over the files in `samples/`, after answers I had
  written from vendor documentation were proved wrong three times: PubMed has no XML download in the
  user's reach (the XML branch, its `.xml` upload slot and two i18n keys were deleted), the one
  Lens file we were given is the **patent** collection (refused by name; its scholarly
  collection only became a reader later, when a real Scholarly Works export arrived — see the
  two-collections bullet below), and the "Scopus/Dimensions column names" I had coded were the English UI's while
  the user's Scopus CSV arrives with `文献标题/年份/来源出版物名称/施引文献/参考文献`. A format nobody
  handed us a file for is not a format the app may claim, in code, in a fixture, in a doc or in
  the help panel.
- **Measured, then fixed:** CSSCI writes 【关 键 词】/【期    刊】/【基    金】 (alignment spaces inside
  the tag), names the author list 来源作者, merges year+issue+pages into 【年代卷期】`2021,(2):146-155`,
  prefixes each affiliation with `[作者]`, and numbers its reference list `1.` — not `[1]`, which the
  old detection gate and `_REF_START` both assumed, so a real CSSCI file was not detected at all and
  its 291 references would have glued into one citation per record. Scopus/Dimensions/WoS-table names
  are now per-field candidate lists in both languages; the signature is "one of these columns per
  group" (`header_has_groups`), because a single required name is what refused the real files.
  Dimensions' first row is a copyright banner, so `frame_of`/`header_of` drop leading provenance lines
  before reading the header. WoS' Excel download was measured twice — the first export left
  `Cited References`, `Author Keywords`, `WoS Categories` and `Funding` empty for all thirty records,
  and after the user re-exported, keywords/categories/funding/usage arrived while `Cited References`
  stayed empty with only `Cited Reference Count` written. The user then said the site simply has no
  such Excel field. **Name the FIELD that a vendor does not offer, not the whole format**: the WoS
  guide now says "Excel has no Cited References column — citation work needs the plain text" while
  keeping Excel as a working route for the keyword/subject/funding/usage networks. Declaring the
  entire download unusable would throw away four networks the file really answers.
- **A fixture may copy structure but never facts.** The committed `samples/biblio/biblio_*_demo.*` files
  reproduce a real export's tags, header order, spacing, separators and banner row, with every value
  from a small synthetic pool; the vendor files themselves are gitignored because the Dimensions
  download states in its own first row that redistribution is prohibited. `FORMAT_CASES` therefore
  carries `has_refs` per case: asserting "every format has a reference list" is what would force a
  fixture to invent a column its vendor does not export.
- **Recognising a file is not the same as being able to read it.** Detection answers "not mine" with
  a plain table, which is the wrong answer for a file that shares column names with a format we do
  read. `services/biblio/formats/unsupported.py` holds those refusals outside `FORMAT_SPECS` (a
  refusal is not a reader), and `biblio_import.parse_text` raises its sentence before the route falls
  back — a silently accepted patent export draws applicants and owners as authors and never says so.
- **One vendor, two collections, overlapping column names: the signature must require the columns
  that differ.** Lens' patent download shares `Lens ID` and `Title` with its Scholarly Works
  download, so a scholarly reader keyed on those two would claim the patent file. `lens.py`
  therefore requires `Citing Works Count` **or** `Fields of Study` — columns only the scholarly
  collection writes — and `unsupported.lens_patents` still refuses the patent shape by name. Both
  directions are tested, because either half failing silently produces a well-formed wrong figure.
- **A column existing is not the same as a column being usable.** Lens writes its `References`
  cell as a list of Lens record ids (`002-341-399-981-03X; …`): of the 24331 ids in the file we
  measured, 1002 name a record the same export contains. Reading that as citation text yields a
  co-citation network whose nodes are almost all opaque numbers, so `refs` is not declared and the
  column is not read. The same test applies to `Source Country`, which is where the *journal* sits
  and not where the authors do: filling 国家 with it would answer a different question than the
  institution and country networks ask.
- **Vendors rename their own columns between versions, so a measured file adds candidates and never
  replaces them.** The Scopus download has shipped the times-cited column as both `Citation count`
  and `Cited by`, the article number as both `Article number` and `Art. No.`, and funding as both
  `Funding Text 1` and `Funding Texts`. Each rename silently zeroed one output column while
  detection still matched — the file imported, the table just lost 引用次数/页码/基金, which is the
  kind of failure no test fails for unless the fixture carries the new spelling.
- **Re-measure after the user re-exports; the help text is a claim about a file, not about a site.**
  The same filenames in `samples/` changed shape twice during this round (Scopus went from the
  Chinese-UI header to an English one *with* `Affiliations`; the WoS Excel re-export still writes an
  empty `Cited References`/`Author Keywords`/`WoS Categories`/`Funding`), and every one of those
  changes makes a previously-true `source.<id>.missing` sentence false. `scratchpad/export_measure.py`
  runs all of `samples/` through the product's own readers and prints the filled columns; run it
  before touching the guide.
- **The guide has to name the click, not the capability.** "Export the publication data as CSV" is
  not actionable when the vendor offers three CSVs: Dimensions writes a full-record CSV, a
  VOSviewer/CiteSpace **network** file and a reference-manager BibTeX, and only the first is what
  this app reads (with its 500-items-per-download ceiling and 30-day Export center). Each source's
  steps now say which option to pick and which to avoid.
- **A claim the readers were never shown cannot stay in the guide.** I had written that WoS reads
  "Excel, Tab-delimited, RIS and BibTeX"; no `.tsv` file was ever measured and
  `accepted_extensions()` does not list one, so the tab-delimited claim came out of the WoS steps in
  both languages, out of `wos.py`'s comment and out of `docs/analysis.md`. The same applies to a
  re-export: when the user replaces `samples/` files, `source.<id>.missing` sentences are claims about
  *those* files and go stale silently. It happened twice in one round — the WoS Excel gained
  `Affiliations` then keywords/categories/funding/usage (only `Cited References` stayed empty), and the
  Scopus download went from 26 to 45 columns — and each time the honest fix was re-measuring
  (`scratchpad/upload_probe.py`, which goes through `/api/data/upload`) and rewriting the sentence, not
  widening it into something vague that stays true.
- **A note added under a chart's title is paid for in that chart's own reserved band.** The
  concentric view states its ring rule as `title.subtext`; at the preview's 400 px the English
  sentence ran off the right edge (ECharts does not wrap a subtitle by itself — it needed
  `subtextStyle.width` + `overflow: 'break'`), and the very first frame after shortening it had
  the legend's `2018` entry sitting on the note, because the legend still started at its default
  `top: 40` while the series started at `GRAPH_TOP`. Three numbers moved together (legend top 78,
  series top +30, note width 330) and only a real browser can see any of it: the node harness has
  no layout, and the option object looks correct either way.
- **The lint hook deletes an import that is not used yet — three times this round.** Adding
  `import numpy as np` at module level while the last local twin still existed, or importing a
  helper a call site added one edit later, gets the new line removed by the PostToolUse
  `ruff check --fix`, and the failure surfaces as `NameError` (in `api/biblio.py`) or as 19 tests
  dying at import. Write the import in the same edit as its first use, or delete the old binding
  first. The same rule cut the other way: while a module-level name still exists, a function-local
  twin is what gets deleted.

### Canvas history, layout baselines and reusable nodes (measured 2026-10-26)

- **A file and a run are two serializations of the same canvas once a reusable node exists.** The
  file must keep the group (its template, its ordered input slots, its collapsed flag, its external
  wires) or Save silently replaces the feature with its children; a run must receive the expanded
  child graph or the engine sees an unknown node type. `canvas.toWorkflowJSON()` therefore defaults
  to the RUN shape and save/autosave pass `{expandReusable:false}`. Forgetting one call site is
  invisible until the next reopen — the file looks like a plain pipeline and the group is gone.
- **A reusable node is ONE entry in `canvas.nodes`; its inside is DOM.** Its children are rendered
  inside the group's own box from the stored template, never added to the model. That one decision
  is what makes undo/history snapshot one object, keeps auto-layout from ranking or framing the
  children separately, and stops an inside node from being dragged out as an unrelated top-level
  node. The inside cards are read-only; changing the fragment means creating a new template.
- **Input order is the order the wires enter the group, and a count mismatch is refused.** The
  template's `inputs` list is the slot map; `canvas.connections` order is the assignment. A group
  with more wires than slots, or fewer, is refused before the run (`reusable.missingInputs` /
  `tooManyInputs`) instead of guessing which child should get the missing table.
- **A snapshot restore must be one undo step.** A file load rebuilds node-by-node and pushes one
  history entry per `addNode`; restoring a canvas snapshot through the same path left Ctrl+Z peeling
  the snapshot apart. `canvas.batchHistory(fn)` suppresses per-change entries and records the net
  state once, and `workflow.loadFromJSON(data,{history:'single'})` is the only snapshot-restore
  door. The normal file-open path is deliberately unchanged.
- **A layout baseline is positions, keyed by the saved workflow name, and a missing baseline is a
  named refusal.** The baseline strategy runs the algorithm first (so nodes the snapshot has never
  seen still get a place) and then overlays the saved x/y for matching ids. It lives in
  `layout_baselines`, is cleared when its snapshot is deleted, and is refused by name when the
  pointer survives without its row; falling back to the algorithm while the Style menu still says
  「按历史基准」 would make the menu lie.
- **An expanded group's stage needs its own width budget, and a real browser is the only proof.**
  Setting the node's width from the stage plus padding still left the stage 2px wider than its
  border-box (the SVG carried the stage's pixel width *including* the 1px borders); `.reusable-stage-lines
  { width:100%; height:100% }` fixed the horizontal overflow. The screenshot also made the first
  card look clipped — it was lying under the fixed left palette, which a rect comparison (node at
  x=80, palette covering x<190) explained; neither the node harness nor a CSS-only read can tell
  occlusion from clipping.
- **The expand-time auto-layout preference is presentation, not canvas state.** It lives in
  `localStorage` with the Style menu's other appearance choices and only decides whether opening a
  group calls the current layout strategy once; the geometry of the group itself is still the
  template's saved relative positions and measured sizes. Keeping it out of the canvas model means
  toggling the preference never becomes an undo step or a file change.
- **A read-only inside needs an unwrap door, and unwrap is a model operation, not a delete.** The
  group's children are not top-level nodes, so "edit an inside step" is impossible without putting
  them back. `ReusableNodes.unwrap` restores them at the template's positions/params, reconnects
  external incoming wires by the same ordered slots the run expansion uses, rewires outgoing wires
  from the single output, and records the whole thing through `batchHistory` as one undo step. A
  group that was disabled must unwrap into disabled children — otherwise the edit silently makes a
  paused pipeline runnable. The saved template is deliberately kept; the user edits and creates a
  new one.
- **A delete endpoint is not a UI feature until a list exists.** The reusable-template API had a
  delete route but no surface; the only way to remove a template was a hand-made POST. The workflow
  dock's third tab lists templates (including corrupt rows, which can only be deleted), offers insert
  and delete per row, and says in the confirmation that existing instances keep their own snapshots.
  The list re-reads after a delete and the insert action closes the dock so the new node is visible.

## Project bundles / 项目包 (measured 2026-10-26)

- **A workflow file is not portable; its dataset references are.** The JSON names datasets by content id,
  and those ids live in `datasets.db`. Copying only `workflows/` to another machine reopens every Upload
  node empty. The bundle therefore carries the datasets and templates it can prove are referenced, and
  import remaps every `dataset_id`/`*_dataset_id`/`template_id` before saving. A bundle without a referenced
  dataset is refused at export; a missing template is only a warning because an instance carries its own
  embedded snapshot.
- **Content identity means the importer cannot promise a new dataset id.** `DatasetStore` hashes the rows,
  so identical bytes imported into a fresh store intentionally keep the same id; the workflow ref is still
  rewritten through the bundle map and `bind` ledger. Do not write a test that asserts "the id changed" —
  assert that the pointer resolves to a stored table and that the ref ledger names it.
- **Import must never overwrite authored names.** Workflow and template names are user work; a collision
  becomes the next free ` (2)`/` (3)` and the summary says so. Dataset rows may dedupe by content, but names
  do not get to replace an existing file.
- **The manifest is a security boundary.** Import accepts only `workflows|datasets|templates/<NNN>.json`,
  refuses traversal-shaped names, checks per-file SHA-1, total uncompressed size and entry count, and
  validates every workflow/dataset/template before writing. A corrupt later entry must not leave a
  half-imported project; the service validates all readable pieces first, then writes.
- **Never package runtime state by accident.** Cookies, API keys, logs, run records, model weights and the
  datasets database file are deliberately absent. The archive is plain JSON so a person can inspect it.

## Dataset merge / 数据集合并 (measured 2026-10-26)

- **A union is not an outer join.** Datasets with different column sets are refused with the extra and
  missing names; `pd.concat` would happily fill the missing columns with NaN and produce a table that
  looks complete until a chart reads the holes. The reference order is the first selected dataset's.
- **Provenance is additive and never overwritten.** When no `来源` column exists, the merge inserts one
  carrying each source dataset's name. If the table already has `来源`, its per-row values are the user's
  own provenance and win over the filename. The source files themselves are untouched.
- **The result is an ordinary dataset.** It goes through `DatasetStore.put`, so content identity,
  dedupe, row caps and the dataset panel's list/preview all apply without a second storage path.

## Vendored front-end assets and machine-level refusals / 前端资源入库与"缺什么就说什么"（measured 2026-10-26）

- **A CDN dependency fails as a blank, not as an error.** `index.html` pulled ECharts, echarts-gl,
  echarts-wordcloud and the Literata face from `cdn.jsdmirror.com` / `fonts.googleapis.com`, and the China
  basemap from `geo.datav.aliyun.com`. On a machine with no network the figure area is simply empty —
  nothing throws, nothing prints, so no tier of the suite could have noticed. Only an assertion over
  `performance.getEntriesByType('resource')` says what the user sees: every resource must come from the
  app's own origin (`tests/integration/test_ui_layout.py::test_the_shipped_page_draws_its_figures_...`).
  Reproduce the old state by serving the page and blocking nothing — the proof is the resource list, not a screenshot.
- **Redistributed bytes get a hash pin, not a fetch.** `tools/vendor_frontend_assets.py` stores the
  SHA-256 it reviewed and refuses on mismatch (printing the hash it saw). "Download whatever upstream
  serves today" hands a third party write access to what our users' screens execute, and makes a broken
  build look like our bug. Upgrading is one edit with a diff: URL and `sha256` change together.
- **Google's `css2` declares the same file once per requested weight.** Naming a font file per
  `@font-face` block shipped 42 files / 2 MB of what is 14 files / 556 KB. Dedupe by URL, name by
  (style, subset). And sweep your own orphans: packaging copies the whole `static/` tree, so a font the
  stylesheet stopped referencing still ships — the tool deletes what it no longer names, and the test
  asserts `referenced == on disk`.
- **A basemap check must assert content, not parseability.** `china.json` still renders if a province
  disappears; losing Taiwan or the nine-dash line is a factual defect in a figure destined for a Chinese
  paper. Name which region went missing before the count ("lost 台湾省" beats "33 of 34"), and keep the
  file byte-for-byte as served rather than re-deriving it.
- **Two answers to one machine-level question is the defect.** The launcher kept its own Chrome candidate
  list, its own MiKTeX scan, and a hardcoded `127.0.0.1:11434` — so a user who set 「设置 → Ollama 地址」 to
  another machine read "Ollama 未检测到" one line before the app answered from that daemon. Both now call
  `core/machine.py` / `services/charts/pdf.find_xelatex()`.
- **A default that points at a file which does not exist is a wrong default.** `Config.DRIVER_PATH` was
  `C:\Program Files\Google\Chrome\Application\chromedriver.exe`; almost nothing installs a driver there, and
  Selenium then dies with `The path is not a valid file`, naming a path the user never typed. Blank means
  "let Selenium Manager fetch the driver matching the installed Chrome", which is the only answer that works
  on an unknown machine — and it is why the driver is not bundled (driver↔Chrome major versions pair 1:1, so a
  shipped driver is a shipped expiry date). Note the trap in `save_settings`: clearing the field used to
  restore that broken default, so 「清空该设置」 advice was a loop, not a remedy.
- **`xelatex -interaction=batchmode` puts the reason in `main.log`, not stderr.** Reading only stderr gave
  "compilation failed" with 300 characters of near-nothing, about a missing `ctex.sty` that the log names in
  its first line. Read the log before `rmtree` deletes the working directory, and translate the two fixable
  shapes: ``File `X.sty' not found`` → name the package; `The font "X" cannot be found` → name the font
  (English Windows needs the Simplified Chinese font feature).
- **Chinese glyphs are a machine fact, and silence about it is a paper full of boxes.** Matplotlib falls back
  per glyph since 3.6, so what matters is whether *any* family in the stack carries Han. `visualizer.cjk_font()`
  asks `fontManager.findfont(name, fallback_to_default=False)` and the first warning prints once per wording —
  cached per message, not by a boolean, because the console language is per thread and an English run deserves
  its own line. LaTeX asks for `\setCJKmainfont{FangSong}` by name, so a missing font is a compile error, which
  is why the log reading above names it.
- **A refusal is only real if the exported figure carries it.** A map whose basemap did not register used to be
  drawn anyway: ECharts paints an empty frame and the user exports it as a result. `applyEchartsOption` now
  draws the refusal sentence *through the live instance* (`drawChartRefusal`), so the panel keeps an instance to
  resize and dispose and the saved PNG/SVG contains the reason.
- **Tests may not inherit the machine's browser set.** `crawlers/core/browser.py::resolve_browser` now
  refuses when Chrome is missing,
  which would make every crawler case depend on what the runner has installed; `tests/conftest.py` pins one
  answer (`machine_has_a_browser`) and the tests *about* that refusal override it. Do not "fix" this by patching
  `os.path.isfile` — that is process-wide, and the cookie/profile fixtures read the same function. Existence
  questions get real files in `tmp_path` and paths that are simply absent.
- **The DOM stub already defines `echarts`** (`harness_dom.mjs`), so a "library missing" scenario must
  `delete sandbox.echarts`; leaving it makes the harness silently exercise the shared stub — my first run
  recorded `hasLibrary: true` in a world built without a library and every case measured the stub instead of
  the product. Same family as AGENTS' rule that a wrapper installed in another file is not the function you load.
- **A docstring is input to other tests.** Adding the phrase ``from app import app`` to a comment in
  `desktop_entry.py` broke a source-*order* contract (`seed_registry` must appear before the real import),
  because the test compares `str.index()` positions and my sentence was earlier in the file. Product-behaviour
  order was still right; the comment was reworded rather than the test weakened.
- **The hook deletes an import added before its use — again.** `import re` (latex_compile) and `import sys`
  (machine_deps) were both auto-removed by the PostToolUse `ruff check --fix` because nothing used them yet at
  that instant. Write the use first, the import second. The same trap fired a third time in this round
  (`from utils import console` in app.py): the symptom was **2209 test errors** — every case that touches the
  `client` fixture fails at import — so an unused-looking import is worth one grep before it is trusted.

## Cross-platform / Win・Linux・macOS 三套系统（measured 2026-10-26）

The project is developed on Windows and deployed on a **Linux cloud server** (`CRAWLER_CLOUD=1`), and macOS is
in scope too. Three read-only audits (backend / cloud mode / tests+deps+CI) produced this list; every entry was
a real defect on at least one of the three, not a style preference. The rules are in `AGENTS.md`
(「Cross-platform」); the evidence is here.

- **Chrome discovery was a Windows-only table.** `chrome_candidates` built `%PROGRAMFILES%…chrome.exe` and
  nothing else, so a server with `/usr/bin/chromium` answered 「本机没有可用的 Chrome」. The Docker image worked
  **only** because it exports `CHROME_BIN` — the one path that bypassed the broken table. The tables are now
  per OS (`CHROME_PATHS` / `CHROME_PATH_NAMES` / `XELATEX_PATHS` / `CTEX_FONTSET`), and a test asserts each is
  indexed by **exactly** the three platforms: a table missing one OS is a feature that silently works on two.
- **Ask the target OS for its separators, not the host.** `Path('/Users/x') / 'Applications'` renders with
  backslashes when a Windows test asks about macOS, and `os.pathsep` splits a Linux `PATH` on the wrong
  character. The candidate list is built with `ntpath`/`posixpath` chosen by the *requested* system — which is
  also what makes a Linux answer verifiable from this box at all.
- **Matplotlib's CJK stack named only Windows fonts.** It resolved to `DejaVu Sans`, which draws every Han
  character as a box, and the warning told the user to install SimHei. The image installs `fonts-noto-cjk`
  (**Noto Sans CJK SC**) and `fonts-wqy-zenhei` (**WenQuanYi Zen Hei** — not the "Micro Hei" that was in the
  list): neither name was being asked for. Windows names stay first in the stack so a desktop's answer does
  not move.
- **A remedy sentence is a different sentence per OS.** Telling a Linux user to open the MiKTeX console is
  advice nobody can follow, and both languages saying the same Windows thing is invisible to the parity
  check. Hence `deps.<family>.<platform>` keys chosen by `machine_deps.remedy` — a **computed** key, so the
  contract walks the value universe (`REMEDY_PREFIXES × REMEDY_PLATFORMS × both languages`), the third time
  this project has been bitten by an unaudited computed key.
- **仿宋 (FangSong) is a Windows font.** Every paper figure asked `\setCJKmainfont{FangSong}`, so on TeX Live
  the whole figure/PDF feature died with 「The font "FangSong" cannot be found」. Off Windows the ctex line
  carries that OS's own font set (`fontset=fandol` / `fontset=macnew`) and no `\setCJK` line at all; the
  emitted comment names the family the document actually used, because a paper author pasting the source is
  on this machine. Windows keeps the three lines byte-for-byte — 26/26 compiles is the evidence for that.
- **`taskkill` under `contextlib.suppress(Exception)` also swallowed the line that marked the session dead.**
  The blocked call was inside the same `with`, so on Linux: nothing was killed, `DeadDriver()` was never
  assigned, and the console still read as though the browser had been stopped — the next crawl of that
  platform then waited `PROFILE_LOCK_TIMEOUT` (900 s) for a profile a live Chrome held. Off Windows the reap is
  `os.kill(SIGKILL)` with the driver's **direct children taken first** (field 4 of `/proc/<pid>/stat`), and the
  outcome is reported either way. Two facts learned here: Windows' `signal` module has **no `SIGKILL`** at all,
  and `os.killpg` is unusable — chromedriver shares the server's process group, so a group kill takes the
  server down with it.
- **A filename limit limits what the OS counts.** Windows counts characters in a component; ext4 and APFS count
  **UTF-8 bytes** (NAME_MAX 255). 100 Chinese characters are ~300 bytes: writable here, `ENAMETOOLONG` on the
  server. `sanitize_filename` cuts by both, and the byte budget is 200 rather than 255 because the writer
  appends a suffix (`.part001.csv`, `-20261016-120000.html`) after the cap.
- **A container with no `LANG` has an ASCII stdout, and a Chinese log line dies inside the logging handler** —
  which swallows the exception, so the line vanishes and the console looks quiet. The answer is not "always
  force UTF-8": a Chinese Windows console (cp936) writes Han fine and would be garbled by the switch. So: if
  the stream cannot encode a Han probe, reconfigure it and print that it did; otherwise only set
  `errors='replace'`, so one unmappable glyph in scraped text costs that glyph and not the line. The image
  sets `PYTHONUTF8=1` / `LANG=C.UTF-8` as its own answer.
- **A Windows-only capability needs four answers, not one.** 红果评论 drives a desktop player through a proxy
  whose CA is installed into the Windows certificate store. Refusing inside the node makes the user pay a run
  start (a browser, the single run slot, any upstream LLM rows) for an answer known at page load. So the
  matrix carries `requires='windows_desktop'`; `/api/capabilities` answers whether THIS machine meets it;
  `validate` refuses the node before the run; the panel lists the option **disabled with the reason named**
  (a node restored from a Windows canvas stores that mode — dropping the option would paint the platform's
  first mode instead, which is a panel lying about what the run would do) and hides the four desktop-only
  settings rows through `html[data-win-desktop]`. A missing verdict leaves everything visible: hiding a
  working feature because a byte never arrived is its own bug. `requirement_met` is the one predicate.
- **`pip install -r requirements-optional.txt` was a Windows-only command.** `uiautomation` is a
  comtypes-based Windows sdist, so the optional stack could not be installed on a server at all — over one
  node that could never run there. Both harvest packages now carry `sys_platform == "win32"`. The other
  declaration gap was `tzdata`: Windows has no system zoneinfo directory and a slim image usually has none
  either, so a scheduled task with a Chinese zone name died with `ZoneInfoNotFoundError`.
- **A deploy knob nobody reads is worse than none.** The Dockerfile exported `CHROMEDRIVER_PATH`; `core/config.py`
  reads `CIXI_DRIVER_PATH`. The image looked configured and was not.
- **Two tests were pinning a Windows spelling rather than an answer.** `test_lint_gate.py` required the
  literal `Get-ChildItem` in `ci.yml` (an ubuntu runner would fail the *gate*, not the code) and
  `test_browser_startup_refusals.py` named its fake driver `chromedriver.exe`. Both now state the rule.
  `test_hongguo_harvest.py` faked `sys.platform='win32'` to reach the Windows branch and never asked what the
  other branch does; it now refuses `linux`, `darwin` and a cloud Windows host explicitly.
- **Two `replace('\\', '/')` calls were kept, on purpose** (`api/studio.py::save-pdf` folds both separators
  before `basename` so a Windows-style path is refused on Linux exactly as a POSIX one is refused on Windows;
  `analyzers/sentiment.py::resolve_bert_model` folds them so a registry path typed on Windows still resolves
  after the project moves, and it tries the literal path first). An audit called these mangling; reading what
  each route is for says otherwise, so the reason now lives next to each line.
- **The scan that keeps the rule has to be able to fire without crying.** A `[A-Za-z]:\` pattern matches the
  `\s` of every regex in `analyzers/` (source text is letter-colon-backslash for both `C:\Program` and
  `KEEP:\s`), so it flagged 20 unrelated lines and would have been switched off inside a week. It now looks
  for the artifacts that actually break Linux — install roots, `taskkill`, `ctypes.windll`/`winreg`/`msvcrt`,
  quoted `.exe` — skips docstrings and trailing comments (prose *about* taskkill is not a call to it), and
  re-asserts that every exempted file still contains an artifact. An allowlist entry that exempts nothing is
  a lie waiting to be read.
- **A refusal sentence that names a Windows file is itself a Windows fact.** `crawl.chromeMissing` told every
  system to point 设置 at 「它的 chrome.exe」, and `disguise_headless` sent `'platform': 'Win32'` to
  `Network.setUserAgentOverride` — both survived for months because the zh/en parity check compares the two
  languages to *each other*, so a sentence that is wrong on Linux is wrong twice and reads consistent. The
  executable name now comes from `machine_deps.chrome_executable_name()` (read off the same
  `CHROME_PATH_NAMES` table the probe uses, so a refusal can never name a file this machine would not have
  found), and the platform token from `NAVIGATOR_PLATFORMS` — 'Win32' on Windows is what a real 64-bit
  Chrome there reports, so the fix is *per-OS*, not a removal. On Linux the old pair was actively producing
  the mismatch the disguise exists to eliminate: the UA is read back off this very Chrome and keeps
  `X1; Linux x86_64`, while the override answered `Win32`. Deleting `i18n.py` from `WINDOWS_TABLES` in the
  same change is what makes that stick: the exemption's stated reason had become false, and
  `test_each_exempted_file_actually_holds_a_windows_artifact` is the test that says so.
- **What this box cannot prove.** No Linux runtime exists here (no docker, no WSL — the user's decision), so
  these changes are landed as code plus platform-independent tests. **Starting the app on Linux/macOS is an
  unverified surface**: a crawl on a real container, a `fandol` compile of a paper figure, and the snap /
  app-bundle Chrome lookups are reasoned and tested by substitution, not executed. The Linux system packages
  are in `README.md` / `docs/config.md`; run them once on the server and report what differs.

## The second crawl backend (CatBus) — why the boundary is where it is (measured 2026-10-26)

- **Why a subprocess and not a port.** CatBus is a Node program that already speaks this app's row shape:
  one JSONL row per record on stdout, one summary envelope as the last stderr line, exit codes that
  classify the failure (1 unclassified / 2 usage-unsupported / 3 login / 4 not-implemented / 5 risk control /
  6 network / 7 upstream), and a `capabilities` command that answers 平台 × 模式 in machine-readable form.
  Porting those eleven platform clients into Python would be a second implementation to keep in step with
  a project that is moving; the boundary is one file (`services/ingest/catbus.py`) and the contract is
  documented in the CatBus repository's own `docs/crawler-workflow.md`.
- **Why the manifest is read and never copied.** A local table of "what CatBus supports" would be the
  second opinion the frontend rule exists to stop: the day the adapter drops a cell, a copied table keeps
  offering it and the refusal arrives as an empty crawl instead of a named one. `probe()` therefore runs
  `capabilities` (cached, `PROBE_TTL`), and `columns_for` / `identity_for` / `mode_state` all answer out of
  that document. Adding a platform is a CatBus change; nothing on this side has a name to add.
  Verified against the built adapter: `node dist/integrations/crawler-workflow/cli.js capabilities` answers
  the manifest, and `preflight --platform bilibili` answers `AUTH_REQUIRED` + `catbus bilibili auth login`
  with exit 3 on an unauthenticated box — which is the shape `_probe_catbus` maps to `EXPIRED`.
- **The streaming was an upstream change, paid for first.** The adapter originally printed every row after
  the run finished, while this app stores one row per transaction: 停止 mid-crawl would have thrown away
  everything it had already bought. `catbus` now writes each row as it is produced (`RowSink` threaded from
  `runMode` into the bilibili adapter; pinned by tests that assert the first row is handed over *before* the
  second detail request goes out), and a failure summary reports the rows actually written instead of 0.
  CatBus commit `4528af3`.
- **`windowsHide` is not a `Popen` keyword.** Written as `windowsHide=True` it raised
  `TypeError: Popen.__init__() got an unexpected keyword argument 'windowsHide'` — caught only because a
  test drove a real child process rather than a fake one. The Windows answer is
  `creationflags=CREATE_NO_WINDOW`, and that constant does not exist in POSIX' `subprocess`, so it lives in
  `utils/procs.popen_kwargs()` (Windows: the flag; Linux/macOS: `{}`) — one place, tested per OS by asking
  each table for its answer, exactly like `reap_command`. A comment crawl starts one child per link, so the
  missing flag is not a crash but a black window flashing once per article.
- **A piped Python child writes the ANSI code page.** The real-child test's child printed `{"标题": …}` and
  the parent read mojibake back, then `UnicodeEncodeError: surrogates not allowed`: on Windows a *piped*
  `sys.stdout`/`sys.stdin` is cp936 unless the child reconfigures it. Two facts fall out of that. The bridge
  writes and reads **bytes** and decodes UTF-8 itself (never a locale), which is why parameters travel as one
  UTF-8 stdin document instead of argv (a code page rewrites a Chinese keyword; a long link list reaches a
  command-line length limit); and any child this app spawns must declare its own encoding — Node does
  unconditionally, which is why the adapter boundary is safe even though a Python stand-in is not.
- **Two backends, two logins, two answer keys.** The pre-run gate keys a verdict by `platform[@account]`.
  A CatBus `default` and a cookie file called `default` are two accounts on two systems, so one key would
  let a dead browser cookie block a crawl that never reads it — or a live CatBus login clear a gate a dead
  cookie should stop. Hence `entry_of` reads a third element (`backend`), `entry_key` gains a `#catbus`
  suffix **only** for a non-browser backend (every key this app ever produced still spells the same), and
  the adapter's verdict is deliberately not cached: a five-minute-old 「没登录」 would block a run the user
  just fixed in a terminal, and the question costs one short-lived process.
- **Why `login_wall` stays False.** The executor's reading of that flag is `execution_state['cookie_expired']`
  + 「重新保存 Cookie」, and its risk sibling prints 风控 itself. Both would be advice about a session this
  crawl does not have, and the second would be the same sentence twice. The CatBus session raises its own
  refusal carrying the adapter's own hint; a test pins that both flags stay False and that no
  `cookie_expired` is implied.
- **The watermark's promise is narrower here, and says so.** Under Selenium `watermark_boundary()` is asked
  *before* the fetch, so older items are never requested — that is the whole network saving. CatBus returns a
  whole list, so the boundary can only stop older rows from being filed. That is a degradation, and the rule
  is "a sanctioned degradation PRINTS what actually ran" (as `topic method=auto`, as bert→snownlp do), hence
  `catbus.watermarkNote` on every watermarked CatBus crawl. The identity column it compares is the manifest's
  (`identity_for`), not a hardcoded `BV号`, and `app.py` now stores the crawler's own `watermark_column`.
- **Not yet verified.** No CatBus account is configured on this box, so nothing here has crawled a real site
  through the adapter: the row mapping, `--raw` field shapes and the blocked/partial accounting are tested
  against the adapter's documented contract and a stand-in process, not against bilibili. The live tier case
  is the next thing to run once `catbus bilibili auth login` exists — and it spends the user's account, so it
  is asked for, never assumed.

