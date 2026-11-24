---
name: testing-lanes
description: Choose and run the right test tier for a change in 采析绘 — fast/device/live markers, lane A/B/C, pytest isolation, frontend harnesses, browser-measured assertions and the closure rule. Use before claiming a change is done, or when a test is green without proving anything.
---

# Test tiers and change lanes

Read first: `AGENTS.md` → "Commands", "How tests are written here", "Change workflow";
`docs/agent_practices.md` → "How tests are written here"; `docs/development.md`.

## The tiers

| tier | marker / command | needs | what it proves |
|---|---|---|---|
| fast | `python -m pytest -q -rs` | nothing | unit, API with `test_client`, frontend harnesses with node |
| device | `-m "integration or live_ollama"` | real Chrome + matching chromedriver, Ollama | browser UI, real rendering, local model |
| live quick | `-m live_quick` | network + accounts | one real site/API path |
| live site | `-m live_site` | the user's consent + network direction | full platform matrix |

`pytest.ini` deselects the real tiers from the fast run. A tier that skips everything still prints
"passed": set `CRAWLER_REQUIRE_BROWSER=1` / `CRAWLER_REQUIRE_NODE=1` / `CRAWLER_REQUIRE_OLLAMA=1`
to turn a missing dependency into a failure. Never run `live_*` unattended; ask which network
(`live_cn`/`live_os`) and never use the user's profile without `CIXI_LIVE_USE_USER_PROFILE=1`.

## Lanes (how much to run)

- **A** — docs/comments/anchor: `tests/unit/gates/test_doc_paths.py` (+ `ruff check` for a `.py`).
- **B** — a move or test-seam retarget with unchanged behavior: the moved module's cases, contract
  tests naming it, ruff/format on touched files.
- **C** — one domain's behavior change: that domain's own suite plus the contract/gate tests that
  name it; device only when UI/engine/LLM/crawling changed.
- **One full fast run per batch, not per edit**: run it when a ~4-knife batch closes, when the change
  crosses several domains, or at the closure gate. It costs ~14 minutes of the user's time. Both
  pylint tiers ride with that batch run. **A Lane C change never starts the full tier**: name the
  domains it can break and run those; the commit message says which ones ran and CI is the backstop.
  (2026-11-24: a dropdown-plus-tests change nearly burned 14 minutes; the user stopped it.)
- **Do not test the world twice.** A green file is not re-run because a doc line moved. "不用那么严格"
  is about scope, not about the touched domain — prove that one, and let CI be the backstop.
- **Closure** — a "done" claim: one full fast run + the tiers the change touched, nothing
  deselected/skipped, no file left to edit.

CI (`.github/workflows/ci.yml`) runs fast + ruff + two pylint tiers on Windows, Linux and macOS on
every push; it is the backstop, not a substitute for the lane.

## Isolation and honesty

- `tests/conftest.py` isolates the data root at import and **fails the suite if `data/` or `logs/`
  gains a byte**. A test that writes there is the bug.
- `quiet_jar` snapshots/restores the shared cookie dir; a crawl test declares `seeded_logins`; a test
  *about* the login rule points `Config.COOKIE_DIR` at its own tmp dir.
- The `integration` UI tier performs **no server writes** — stub `fetch`.
- A warning is a test that noticed something and passed anyway. Fix the cause; never
  `filterwarnings`.
- Never assume UTC: the dev box is UTC+8 and CI is UTC. Ask the machine (`astimezone()`); `TZ` is
  honoured on Windows (`$env:TZ='UTC'`).
- A test calling an executor directly must leave `execution_state['running']` false;
  `clean_globals` fails a leak.

## Frontend JS

- Harnesses load the **real** files into a node `vm`; a harness takes its files through
  `sourcesWithCompanions` (one read per file), never its own `readFileSync(argv)`.
- A split registers in `tests/frontend/splits.json`; the companion closure is transitive.
- `node --check` every new JS file; drive result-affecting behavior through a harness scenario in
  the same change. Static string assertions are a last resort, not the pattern.

## Browser-measured assertions

- Audit containers **by id**, never `<body>`; report a per-container floor and resolve wording from
  `I18n`. State the viewport; on Windows emulate device metrics
  (`Emulation.setDeviceMetricsOverride`) and assert CSS size with a `100vh` probe.
- "Closed" means gone in pixels: compare the closed strip byte-for-byte with the same box at
  `display:none`, after a closed-vs-closed control that must match. Unreproducible = REFUSED.
- A live case's thresholds are computed from the crawl, two-sided, never chosen. A refusal must be
  named (login wall / risk page); an unnamed empty table stays red.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q -rs
.venv\Scripts\python.exe -m pytest -q -m "integration or live_ollama" -rs
.venv\Scripts\ruff.exe check backend/ tests/
.venv\Scripts\ruff.exe format --check backend/ tests/
.venv\Scripts\python.exe tools\ci_lint_tiers.py product
.venv\Scripts\python.exe tools\ci_lint_tiers.py tests
```

Then `/smoke-verify` for a server boot on an isolated `CRAWLER_DATA_ROOT` (port 5057; never kill
5000).

## Common false greens

- A tier that skipped the only case that mattered (`REQUIRE_*` unset).
- A harness that loaded half the panel because the split/companion is missing.
- A static-asset assertion standing in for behavior.
- A UI test that stubs `fetch`/`showDialog` and then claims the real panel works.
- A "figure looks right" claim without reading the dataframe the run produced.
