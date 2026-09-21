# AGENTS.md

This file provides guidance to the AI agent when working with code in this repository.

## Project

采析绘 (crawler_workflow): Flask backend + vanilla-JS frontend that crawls Chinese social media
(Zhihu/Weibo/Xiaohongshu/WeChat) via Selenium, cleans/analyzes text with Ollama LLMs and
scikit-learn, and renders a drag-and-drop workflow canvas. Single project, no build step.

## Commands

**The project venv `.venv/` (Python 3.11) is mandatory — never use system Python.** Every run,
install, lint and test goes through it: in Git Bash run `source .venv/Scripts/activate`, or call
`.venv/Scripts/python.exe` / `ruff.exe` / `pylint.exe` / `pip.exe` directly.
- Install new third-party libraries: `.venv/Scripts/pip.exe install <pkg>`, and add it to
  `requirements.txt` **in the same change** — no exceptions. The rule is broader than installs:
  *every package imported directly by code must be declared in requirements.txt*, even when it
  arrives transitively (e.g. `requests`, `joblib` were both imported directly but undeclared).
- **Repo hygiene**: a new tool leaves caches/artifacts behind — record them in `.gitignore` in the
  same change that adds the tool (pytest → `.pytest_cache/`, coverage → `.coverage` and `htmlcov/`;
  already covered: `.venv/`, `.ruff_cache/`, `__pycache__/`, `data/`, `logs/`).
- Install/restore deps: `pip install -r requirements.txt`
- Run the app: `cd backend && python app.py` → http://localhost:5000 (port via `PORT` env).
  **Must run from `backend/`** — it is the `sys.path` root, so imports are top-level
  (`from config import Config`, `from analyzers import ...`). Never add a `backend.` prefix to imports.
- Lint: `ruff check backend/` then `pylint <module>` (both configured; ruff is the fast gate, pylint the deeper check).
- Format: `ruff format backend/`
- Standalone crawler scripts: `python backend/test_zhihu.py <keyword> --count N --no-headless`
  (test_*.py are manual run scripts, NOT pytest).
- **Automated tests (pytest, ~1150 cases)**:
  - Fast suite, <60s, no browser/daemon needed: `.venv/Scripts/python.exe -m pytest -q`
    (plain `node` on PATH enables the frontend-JS behavior tests; without it they skip).
  - Device tier (real Chrome on `file://` fixtures + real local Ollama; skips cleanly if absent):
    `.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"`
  - Live-site tier (REAL crawls — every platform runs in BOTH browser modes, headless and visible
    window, plus the comment node across zhihu/weibo/xiaohongshu and 3 real WeChat articles;
    per-platform skip when a cookie is absent): `.venv/Scripts/python.exe -m pytest -q -m live_site`
  - Coverage: append `--cov=backend --cov-report=term` (total target ≥70%).
  - Layout: `tests/unit` (pure logic + frontend-JS behavior harnesses), `tests/api` (Flask
    test_client, fully tmp-isolated), `tests/integration` (LLM boundary mocks run by default;
    real-Chrome/Ollama are marked). OpenRouter is **never** really called — patch
    `analyzers.llm_client.requests.post/get`.
  - **Frontend JS is under test too**: `tests/frontend/harness_*.mjs` load the REAL
    canvas.js/workflow.js/app.js in a zero-dependency node vm (shared `harness_dom.mjs`) and
    are driven by `tests/unit/test_frontend_*` pytest modules — validation gates, panel HTML,
    popup outside-click, catalog parity, undo/redo, the save/open/new lifecycle and the
    run-records table. Any JS change to result-affecting logic must sync a scenario there;
    `urlPlatform` (workflow.js) is contract-pinned against `utils.helpers.platform_for`.

## Style (differs from defaults)

- Comments and docstrings are in **English** even though README/commits are Chinese. Explain "why".
- Section dividers use `# ─── Name ───`.
- Ruff: line-length 120, **single quotes**, indent 4. Lint findings must be **genuinely fixed**:
  never `# noqa`, never `# ruff: noqa`, never a `per-file-ignores`/rule-exemption in `ruff.toml`.
- Modern typing (`str | None`, `list[str]`), target py311.

## Commits

Chinese messages with a type prefix, matching history: `功能更新：`, `问题修复：`, `修改：`.

## Environment & gotchas

- Requires **Ollama** running at `localhost:11434` (model `qwen3.5:9b`, override via `OLLAMA_MODEL`/`OLLAMA_HOST`)
  and **Chrome + chromedriver** for crawling. `DRIVER_PATH` is hardcoded in `backend/config.py`
  but overridable at runtime via `data/settings.json` (POST `/api/settings`).
- Runtime state lives in gitignored `data/` (SQLite: `runs.db`, `datasets.db`, `history.db`) and `logs/`.
  Do not delete `data/` contents casually — saved workflows reference uploaded datasets there.
- Interrupt/resume checkpointing (`backend/services/run_store.py`) is core: per-node outputs and LLM
  answers persist so interrupted runs resume rather than re-crawl/re-pay. Change executor/run-store
  code carefully so resumed runs stay compatible with existing `runs.db` state.
- UI text supports zh/en via `backend/i18n.py` message catalog — add new user-facing strings there.
- **Weibo serves a fake login wall**: a search first flashes the passport QR page, then bounces the
  logged-in session back to the feed. Never judge the wall from the URL right after `get()` —
  `WeiboCrawler._await_search_page` waits for a terminal state (cards / no-result plate / persistent
  passport page). Keep that ordering in any refactor.
- Zhihu throttles headless content pages day-by-day (risk code 40362); comment crawling always opens
  a visible browser for zhihu, and a headless zhihu search returning 0 rows is a legit risk-control
  outcome the message catalog already explains — don't "fix" it by loosening assertions.
- **Cookie death mid-crawl is a designed path**: crawler `login_wall` + under-target rows →
  `_execute_source_node` sets `execution_state['cookie_expired']` (rides on `/api/workflow/status`
  for the browser toast), logs `run.cookieExpired`, and RAISES so the node settles `partial`, the
  RUN becomes `failed` → appears in the resume banner → fresh-cookie 继续 continues from the stored
  cursor/ledger. Never downgrade this to "node completed with fewer rows" — that hides the gap
  forever. Comment nodes raise when any article was BLOCKED for the same reason.
- Console/validation messages must reference nodes through
  `engine.workflow.node_label(node, nid)` (→ `title #nid`) — never a bare `nid` —
  so a renamed node speaks with the user's name. Store keys, results dict and
  resume plumbing still use the raw `nid`; only display strings change. The
  frontend keeps `node.title` in `getState`/`toWorkflowJSON`, and BOTH restore
  paths (`canvas.restoreState`, `WorkflowManager.loadFromJSON`) must re-apply
  title + element text BEFORE `updateNodeDisplay`, whose re-stamp guard reads
  the element.
- Run-gating UX lives in `workflow.js execute()`: `_confirmCookieBeforeRun` (dialog, skippable via
  the `cookie_confirm_before_run` setting, auto-pass for resume runs); new settings keys need the
  bool branch in `settings_store.save_settings` + both app.js catalogs + `AppSettings` wiring.

## Change workflow (MANDATORY — run the full loop on every change)

Correctness comes from this loop. Every step must actually pass — a change is not done
until the whole chain is green end to end.

1. **Edit** — the PostToolUse hook auto-runs `ruff format` + `ruff check --fix` on each touched `.py` file.
2. **Tests are part of the change — never an afterthought.** Any code file touched (backend *or*
   frontend JS) means syncing the pytest suite in the same change:
   - new functionality → introduce tests for it,
   - changed behavior → update the affected assertions,
   - deleted functionality → remove its tests (no orphans kept for a feature that no longer exists).
   The suite must prove two things every time: the new feature is correct, and nothing that worked
   before broke. If a previously-green test now fails because of your change, the bug is in the
   change — fix the code, not the test (exception: a test pinned an old bug that is now genuinely
   fixed, in which case update it to the correct expectation).
3. **Fast test suite**: `.venv/Scripts/python.exe -m pytest -q` must be green. If a test exposes a
   genuine product bug: fix the product code (never bend the test to the bug); if the fix cannot
   land now, pin it with `@pytest.mark.xfail(strict=False, reason='product bug <file:line> — ...')`
   and report it.
4. **Lint every file being committed**: `.venv/Scripts/ruff.exe check <files>` and `format --check <files>`
   must both pass. Fix real warnings/errors in code — suppression (noqa/ignores) is forbidden (see Style).
5. **New packages**: installed into `.venv/` AND listed in `requirements.txt` in the same change
   (see the declare-every-direct-import rule under Commands), plus their cache artifacts added to
   `.gitignore`; then verify `pip install -r requirements.txt` in a clean env would work.
6. **Docs stay true**: update `README.md` in the same change whenever code behavior is visible to
   users — feature list, node types, API tables, config tables, project structure, quickstart.
   README must always match the current code; a stale README is a failed change.
7. **Device paths**: if the change touches crawling, LLM transports, or checkpoint/resume, also run
   `-m "integration or live_ollama"` (Chrome + Ollama are available on this machine) and
   `/smoke-verify` end to end (lint → boot server on port 5057 → GET endpoints 200 → clean shutdown).
   Paths neither suite reaches (logged-in scraping against live sites, UI) must be exercised by the user
   in a browser.
8. **Commit** last, with a Chinese type prefix (`功能更新：` / `问题修复：` / `修改：`).
