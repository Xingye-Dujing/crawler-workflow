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
- **Automated tests (pytest, ~1602 cases)**:
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
- **Douyin is visible-window-only, DOM-only, and has no play count.** A headless
  browser is answered by 验证码中间页 on *every* navigation (measured), so the class
  sets ``never_headless = True`` and `_execute_source_node` downgrades to a visible
  window before buying the browser — never let that flip back to headless "for
  speed". Its search endpoint is signed (``a_bogus``/``msToken``/``verifyFp``), so
  the DOM is the only path; results mount only after the real search bar plus its
  button drive the app router (a ``/search/<kw>`` deep link leaves three empty
  ``<ul>``s = a shell, not an empty result set) and are detected by the text
  为你找到…, never by a fixed sleep. Cards are ``div.discover-video-card-item[data-aweme-id]``
  with no anchors. Counters come only from self-describing ``data-e2e`` keys
  (``video-player-digg``/``feed-comment-icon``/``video-player-collect``/
  ``video-player-share``); ``detail-video-info``'s second number **is the like
  count**, so a 播放数 column would be a wrong figure with a plausible name — don't
  re-add it. Comments DO render (``[data-e2e="comment-item"]``) and grow only by
  scrolling the route container; both the panel mount and each scroll settle by
  *polling inside the crawler*, never via the caller's ``nap`` — a stubbed nap once
  turned a 2000-comment video into an "exhausted" 5-row crawl.
- **Bilibili's two paging contracts are measured, not guessed — keep them exactly.**
  The search list does *not* infinite-scroll (8 scroll rounds = 42 cards / 34 videos,
  unchanged); the row budget is `&page=N`, and **`page=1` renders zero cards**, so page
  one must be requested as the bare `all?keyword=` URL (a crawler that slept on `page=1`
  would report an exhausted search). Card numbers are a rounded 万-label only: every count
  comes from `x/web-interface/view?bvid=`, which answers `code=0` unsigned, cross-origin
  from the search page, for the cookie the panel saved. Comments have **no DOM at all**
  (`.reply-item` renders nothing), so `x/v2/reply/main` is the only path — and its `next`
  is a cursor, not a page counter: `next=0` reports `cursor.next=2` while `next=1` replays
  page 0 byte for byte. Walk by the server's value and stop on a page with no new `rpid`;
  an incrementing loop would store the same 19 comments forever. `code=-404` is one
  withdrawn video (skip); any other non-zero code is the session/risk engine talking
  (stop, and refuse the run if nothing was collected).
- **Cookie capture and crawling are different capabilities.** `CookieManager.PLATFORMS`
  (6) is who the panel can log in; `crawlers.is_crawlable()` (5) is who has a crawler.
  Douyin sits in the first and not the second, so `_execute_source_node` refuses it by
  node label (`run.notCrawlable`) *before* buying a browser — never let a not-yet-built
  platform fall through to an empty table, which reads as "this keyword found nothing".
- **WeChat is intentionally body-only.** No comments, likes, forwards (and usually no read
  counts) — measured, not assumed: a real browser gets `show_comment=0`, zero `elected_comment`
  bytes in ~3.4 MB of article HTML, and an HTML 验证 page ("请在微信客户端打开链接") from
  `mp/appmsg_comment`; a `MicroMessenger`/`XWEB` UA, client-shaped URL params and replaying the
  client's own decrypted `mp.weixin.qq.com` cookies (`pass_ticket`, `appmsg_token`) change nothing,
  because the gate is a per-session credential the server mints only for a real client session.
  **Do not add client impersonation or session replay to get around it, and do not re-add those
  columns** — in a browser "no comments" and "not allowed to look" are indistinguishable, so an
  empty table would be plausible-looking false data. WeChat's 数据源 node therefore offers no
  comments mode, and `explainWechatLimits()` (workflow.js) + `settings.wechatLimits*` (app.js)
  state why.
  **WeChat has no cookie row at all.** Keyword search via the 公众号后台 was measured to be the
  only thing its session unlocked, and it was deleted rather than shipped unverifiable:
  `appmsg?action=list_ex` answered `ret=200013 freq control` for three accounts, three endpoint
  spellings and every retry after a 15-minute cooldown, so the article-item field shape was never
  observed once. Article *bodies* need no login. Do not re-add `mp_logged_in`, a
  `WechatCrawler.diagnose` override, `WechatCrawler.login_url`, `cookie.wechat.*` text or
  `MULTI_PURPOSE` — and do not implement keyword search again by guessing field names.
  Because there is no login, nothing may *behave* as if there were one: the `live_site`
  WeChat file crawls article URLs only (no 公众平台 visit, no cookie wait/skip), and the
  cookie-panel node harness samples real login platforms (bilibili/zhihu), never `wechat`.
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
- **One run at a time is a design property, and a busy server now queues instead of
  refusing.** `_begin_run()` (app.py) holds the whole start path — claim, validations,
  `execution_state` setup, worker thread — so the queue drains by calling *that* function,
  never a second weaker one. `/api/workflow/execute` with `queue:false` keeps the old 400
  for callers that must fail fast (the resume banner). The hand-off lives in the worker's
  `finally` and clears `execution_state['thread']` **first**: the claim also checks thread
  liveness, so a still-alive unwinding thread would queue the next request behind itself
  forever. Queues are in-memory (a restart drops them) and `tests/conftest.py` clears
  `_RUN_QUEUE` per test, or a parked request would start inside an unrelated test.
  The Execute button is therefore never disabled — it relabels 排队运行 while running.
- **Recorded rows are addressed by workflow, never by bare node id.** `_durable_node_rows`
  (app.py) answers a preview/chart/export/studio probe after a refresh or restart from
  `runs.db`; node ids like `node-2` repeat on every canvas, so with no identity it returns
  nothing rather than guessing (a stranger's table under the user's own node name is false
  data with a plausible face). The browser therefore sends `workflow_name` — computed by
  `workflow.runName()`, which mirrors the backend's precedence: name-node label, then the
  saved file name.
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
