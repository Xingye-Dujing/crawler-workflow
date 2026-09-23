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
- **Automated tests (pytest, ~2393 fast-tier cases; 2499 across all tiers)**:
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
- **Two frontend rules that cost a feature each time they are forgotten.** (1) A guard written
  `if (window.X)` cannot see a module declared as a top-level `const X` — `const` never becomes a
  window property — so `resumeBar.refresh()` and `runsManager._busy()` were dead code forever
  (the 断点续跑 banner never showed). Either guard on the binding itself (`typeof X !== 'undefined'`)
  or export it: `window.X = X`, the way app.js already does for LLMSettings/AppSettings. (2) The
  DOM stub in `tests/frontend/harness_dom.mjs` parses `innerHTML` into real children, matches
  `.class`/`#id`/`[data-x="y"]`/`:not()`, walks `closest`, queues `requestAnimationFrame` until
  `flushFrames()`, and treats an id listed in `document.absent` as truly missing. Do not reintroduce
  "fabricate a child when a query finds nothing": it turned a removed connection path into a
  phantom one and made every `getElementById(x) ? …` toggle look broken in the harness only.
- **A browser-measured assertion must report how much it measured, or it is not an assertion.**
  `tests/integration/test_ui_layout.py` audits containers by id (the page has no `.panel` class —
  a selector matching zero elements kept that test green while checking nothing), never falls back
  to `<body>` silently (an id that stopped existing measured the whole page and reported
  "#settings-panel is fine"), and asserts a per-container floor on the element count it gathered
  (counted in a real Chrome, not guessed). Add new containers to that list with their floor, and
  when a JS-side check walks a subtree, return the population alongside the verdict.
- **The `integration` UI tier performs no server writes** (uploading, saving a workflow, or
  executing a run would leave rows in the user's real `data/` and `logs/` — the app has no
  data-dir override), and the live-site tier retries a crawl once **only** when the crawler itself
  reported `login_wall`, because a valid session can be answered a login redirect once by risk
  control; an empty result without a wall is a real "found nothing" and still reaches the assertion.

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
  code carefully so resumed runs stay compatible with existing `runs.db` state. Three rules that came
  out of measuring this path, each pinned by a test: the streaming row sink writes **one transaction
  per row** on purpose (WAL + `synchronous=NORMAL` makes a commit microseconds while a Selenium page
  costs seconds, so batching would trade "killed at row 900 of 1000 still owns those 900 rows" for
  nothing); the next free slot is found by `MAX(seq)+1`, **never `COUNT(*)`** — that query ran once per
  scraped row and made a long crawl quadratic in the size of its own table; and a **cursor records
  position, not content** — the collected ids come from the seeded rows (`Crawler.seed`), so an id list
  must not go back into `mark_position` (X and YouTube both used to re-serialise the whole result every
  time the crawl gained a row).
- UI text supports zh/en via `backend/i18n.py` message catalog — add new user-facing strings there.
- **The crawl matrix (`backend/crawl_capabilities.py`) is the only answer to "what can this
  platform collect".**
  It declares each platform's modes, the fields each mode needs (with its widget, default,
  floor/ceiling and required-ness) and which crawler method runs. `app.py::_execute_source_node`
  dispatches through it, `engine/workflow.py::validate` refuses through it, and
  `GET /api/capabilities` hands the identical description to the browser, whose Data Source
  panel is generated from it (`Capabilities` + `sourcePanelHtml` in workflow.js). So a new
  platform or mode is **one matrix entry**, never an `if platform == '…'` branch in four
  files — a branch reintroduced anywhere is a second opinion that can disagree with the crawl.
  The module sits at the backend root (like `i18n.py`) because `engine/workflow.py` reads it and
  must not import the crawler package. Field labels are *frontend* catalogue keys and
  required-field names are *backend* ones (`field.*`), both pinned by
  `test_frontend_contract.py::TestCrawlMatrixParity`; `target_count` stays 50 for every platform
  because that is what the panel previews, whatever a crawler's signature says. **An
  unrecognised mode is refused by name on a platform that offers a choice**
  (`engine.source_unknown_mode`), while `mode_for` still falls back to the first mode for
  panel rendering and for single-mode platforms: silently substituting a keyword search
  for a node that asked for one creator's uploads is a different crawl, and reporting
  「缺少关键词」 sends the user to a field the panel never showed them. A payload is a
  network response and the renderer writes field names into inline handlers, so a name that is
  not `/^[\w.-]{1,64}$/` is dropped whole — and a JS-generated panel is driven in tests by the
  matrix dumped from Python (`tests/frontend/harness_capabilities.mjs`, fed by the
  `capabilities_matrix` fixture), never by a copy checked into tests.
- **Crawler layering: `crawlers/engine/` is mechanics, a platform module is the site.**
  Counters (`engine.counters.parse_count` — one parser for 万/千/亿/K/M/B, `1,027,710次观看`,
  `97 views`), interception (`engine.wall`: login / risk-control / root-bounce), first-run
  dialogs (`engine.popup.Prompt` + a platform's `prompts`), the infinite-list walk
  (`engine.feed.walk_feed`, `engine.feed.wait_for`) and the scroll that finds the element
  which actually moves (`engine.feed.jump_to_bottom`, for lists a window scroll cannot
  page — douyin's 作品 grid and its comment panel), cursor paging that follows the server's
  own value (`engine.pager.walk_pages`) and reading a page's embedded JSON
  (`engine.jsonpath`) all live in the engine and know nothing about any platform. A platform
  module declares only its selectors, endpoints and column names. New crawl logic goes
  through these helpers — a second copy of a scroll loop or a 万-parser is exactly what this
  rule exists to prevent. `Crawler.open(url)` is the only navigation entry point: it survives
  a renderer timeout, clears the dialog, and classifies the page.
- **Cookie planting visits a host only when a cookie needs it** (`base.Crawler._load_cookies`
  keeps the entries the current host rejected and stops when nothing is left): every extra
  host is a real page load, measured at ~2.3 s on douyin — and one of the three was a pure
  redirect. The driver runs with `page_load_strategy='eager'` and image loading blocked
  unless a class sets `needs_images = True`, because a crawler reads text and attributes,
  never pixels.
- **Weibo serves a fake login wall**: a search first flashes the passport QR page, then bounces the
  logged-in session back to the feed. Never judge the wall from the URL right after `get()` —
  `WeiboCrawler._await_search_page` waits for a terminal state (cards / no-result plate / persistent
  passport page). Keep that ordering in any refactor.
- **Never write the browser's jar back to a saved cookie file.** Measured 2026-09 on weibo: one
  logged-in page load re-issues the pair (`SUB` 90→94 bytes, `SUBP` 144→56, `XSRF-TOKEN` replaced),
  and planting that rotated jar into a fresh browser is bounced straight to `/newlogin` — a
  write-back would degrade the user's file one crawl at a time. A replayed save still *is*
  accepted (several browsers in a row land logged in), which is why the failure mode looks like
  a stale cookie and is not. Same measurement says a weibo author/profile crawl must not be
  written against `/ajax/statuses/mymblog`: the endpoint answers `200` with real posts in one
  session and `<h2>403 Forbidden</h2>` (an edge/WAF body, not a weibo business code) in the next
  with the same walk and the same logged-in nav — a per-session throttle, so that mode needs a
  loud refusal, never an empty table, and `backend/test_weibo_recipe.py` is the re-test gate.
- Zhihu throttles headless content pages day-by-day (risk code 40362); comment crawling always opens
  a visible browser for zhihu, and a headless zhihu search returning 0 rows is a legit risk-control
  outcome the message catalog already explains — don't "fix" it by loosening assertions.
- **YouTube is JSON-first, headless-safe, and its pagers are chosen by their list.** Measured 2026-09:
  the crawler opens **one page** to read `ytcfg` (`INNERTUBE_API_KEY` + `INNERTUBE_CONTEXT`, never hardcoded —
  they rotate) and then POSTs `youtubei/v1/{search,browse,next,player}` **from inside the page**
  (`crawlers/engine/innertube.py`), which is same-origin, unsigned and cookie-carrying: search 0.68 s / 10 rows,
  player 0.31 s / 11 KB, comments 0.32 s / 20 rows. Headless and visible returned identical rows and facts, so the
  class sets **no** `never_headless`, and `page_load_strategy='eager'` + blocked images stay on (nothing is read from
  pixels). Two rules that only measurement could establish, both in `innertube`:
  **a channel's upload tab must be read off the loaded `/@handle/videos` document** — `browse(browseId, params=videos)`
  answers the channel **HOME** (3.7 MB of shelves, other channels' videos mixed in), so the author mode navigates once
  and pages from the document's own cursor; **a continuation token is picked by which list it is an element of**, not by
  length or position — a comment round carries two 78-char sort-menu tokens that each replay page one (the ledger
  swallows the duplicates, the walk reports success, and a 3000-comment video yields 20) plus one per reply-bearing
  thread, while the list's own pager is its trailing element. `next(videoId)` is worse: six tokens, the comment one
  78 chars on one video and 146 on another with 1412-char rail tokens beside it, so the first round *tries* candidates
  until one answers with comments. `lockupViewModel` (the 2025+ view model) and `videoRenderer` coexist — search is the
  former's absence, channel tabs the latter's — and a reader for one is silently empty on the other.
- **Douyin is visible-window-only, DOM-only, entered through its URL, and has no play count.**
  A headless browser is answered by 验证码中间页 on *every* navigation (measured), so the class
  sets ``never_headless = True`` and `_execute_source_node` downgrades to a visible
  window before buying the browser — never let that flip back to headless "for
  speed". Its search endpoint is signed (``a_bogus``/``msToken``/``verifyFp``), so the
  DOM is the only path.
  **Re-measured 2026-09, and two long-standing facts died together:** the search box still
  accepts the text and its 搜索 button is still clickable, but *neither the click nor Enter
  routes any more* (the address sits on `/jingxuan`; the user watching the window reported
  exactly this), while the `/search/<kw>?type=video` deep link — documented for a year as an
  empty shell of three `<ul>`s — now serves the result list. So `SEARCH_ENTRY` is the route,
  the keyword is percent-encoded into the path, and there is no router left to interrogate
  about which search ran. Cards are `[data-e2e="scroll-list"] a[href*="/video/"]` and the id
  comes out of the href — the old `div.discover-video-card-item[data-aweme-id]` matches
  **zero** nodes now and the class names beside it are build hashes.
  **The list mounts as 16 skeleton rows (no anchor, no text) and fills in ~4–6 s**, so
  "some nodes exist" is not "results exist": `_wait_for_cards` polls for an *anchor*
  (`MOUNT_WAIT`), and a page that never fills is `NOT_MOUNTED` → zero rows, which is the
  honest answer for a keyword nobody posted. The **window** now does the paging
  (measured 16 → 26 → 36 → 46 → 56 cards per ~0.9-viewport scroll), so `_scroll_results`
  scrolls the window and stops the walk when a scroll yields nothing new — and the loop
  checks the row budget *before* scrolling, because scrolling first would wait out
  `SCROLL_WAIT` for rows nobody asked for. Counters still come only from the self-describing
  `data-e2e` keys **on the video page** (`video-player-digg`/`feed-comment-icon`/
  `video-player-collect`/`video-player-share`); `detail-video-info`'s second number **is the
  like count** — and the search card's single bare figure measures equal to it — so a 播放数
  column would be a wrong figure with a plausible name: don't re-add it. The
  「是否保存登录信息超过5天」 mask still mounts seconds after the page and is dismissed on
  arrival (取消 only — the user reports 保存 leads to a phone-verification step). Comments DO
  render (`[data-e2e="comment-item"]`) and grow only by scrolling the panel container; both
  the panel mount and each scroll settle by *polling inside the crawler*, never via the
  caller's `nap` — a stubbed nap once turned a 2000-comment video into an "exhausted" 5-row
  crawl.
  **Author mode is paged by a container the window cannot move.** Measured on `/user/<sec_uid>`:
  scrolling the window grows the **footer's** recommended-video links (8 → 29 anchors) while the
  作品 grid (`[data-e2e="user-post-list"]`) does not move — a count-based walk therefore stops at
  57 on a page that publishes 85. Taking the grid's scrollable ancestor to `scrollTop = scrollHeight`
  pays out 18 rows a round (21 → 39 → 57 → **85, which is what `[data-e2e="user-tab-count"]` says**)
  and is why `engine.feed.jump_to_bottom` exists (the comment panel scrolls the same way, so it
  shares it). A creator is addressed by the opaque `sec_uid` only — `/user/<numeric>` is not a
  route — and every video page carries `a[href*="/user/"]`, so a live run can discover one;
  a display name is refused. `DouyinCrawler._published_count()` returns **-1 for "the page said
  nothing"**, because the shared `parse_count('')` answers 0 and 0 is a *claim*: reading a missing
  number as zero would let a page that never rendered report an author who never posted.
  Rows still come from opening each video (`_detail_row`), so this mode carries the same columns
  as the search mode — including the absence of 播放数.
- **A self-paging list is walked by `_open_each`, and "every id here is known" is not its end.**
  The loop used to `break` when the current screen held no unseen id — which is the *normal* first
  round of a resumed run, because the page reopens on exactly the ids the dead run opened. The
  symptom was a 断点续跑 that returned the previous run's rows, never reached its target, and
  complained about nothing. Now an empty `todo` scrolls on and only a scroll that pays out nothing
  ends the walk; both douyin lists share the one loop.
- **Blocking video was measured and rejected — do not add it.** Images are blocked by
  default (`profile.managed_default_content_settings.images=2`, opted out per class via
  `needs_images`), which is a real saving. Video has no such preference, and the CDP entry
  point people reach for, `Page.setBlockedURLs`, **does not exist on Chrome 148**
  (`unknown command`); the working one is `Network.setBlockedURLs`, verified to bite (a
  player's `readyState` falls 4 → 0). It still buys nothing: our crawls never wait for a
  player (`page_load_strategy='eager'`, we read DOM/JSON), so across all seven crawlable
  platforms A/B'd side by side the blocked arm was equal-or-slower (douyin 22.7 s → 26.5 s,
  YouTube 9.5 → 11.9, X 19.3 → 20.5; zhihu/weibo/bilibili/xiaohongshu flat) and **six of the
  seven download no media on the crawl path at all** (`mediaBytes = 0`). Only douyin's
  per-video page touches a player, and there the page weighs 25.6 MB of which ~2% is media —
  the top resources are the site's own JS bundles (`player-4.js`, `client-entry`), which a
  crawl needs. The one honest reason to ask again is metered traffic rather than time:
  blocking saved ~0.6 MB per douyin video row and 0 bytes elsewhere. Probe:
  `backend/test_media_ab.py` (payload `scratchpad/media_ab.json`).
- **Do not block image loading on douyin** (measured the wrong way first): the class
  sets no `needs_images`, the base default blocks images for speed, and that is fine for
  every other platform — but re-tested with the dialog handled, images-on vs images-off
  produced identical screens (22-24 vs 23-24 cards), so the earlier "blocking images
  breaks the grid" reading was the mask all along. `Crawler.needs_images` exists for the
  case where a site really does need it; record the measurement next to the flag.
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
  Its **author mode is the page, not the API**: `x/space/wbi/arc/search` answers
  `code=-403 访问权限不足` for our session (the older un-wbi path is rate-limited at `-799`),
  so `BilibiliCrawler.author()` opens `space.bilibili.com/<mid>/video` once and pages it by
  scrolling (measured 40 cards on one screen, 80 anchors after three steps) while every number
  still comes from the unsigned `x/web-interface/view` — so a row is identical across the two
  modes. `bilibili_mid()` takes digits or a space link and refuses anything else: opening a
  mistyped space would report "this UP posted nothing" about a page that is not theirs.
- **Cookie capture and crawling are different capabilities.** `CookieManager.PLATFORMS`
  (8) is who the panel can log in; `crawlers.is_crawlable()` (8: zhihu, weibo,
  xiaohongshu, wechat, bilibili, douyin, youtube, twitter) is who has a crawler.
  **Instagram is the one capture-only platform** (`overseas.py` registers it with
  `supports_crawl = False`), so `_execute_source_node` refuses it by node label
  (`run.notCrawlable`) and validation refuses it earlier still (`engine.source_unknown_platform`,
  because it is not in the matrix at all) — never let a not-yet-built platform fall through to
  an empty table, which reads as "this keyword found nothing".
  A capture-only platform must still carry `domain` + `login_url` (the panel needs both), stay OUT of
  `crawl_capabilities.CAPABILITIES` (that tuple *is* the Data Source's platform list now — the browser
  renders the select from `/api/capabilities`, so there is no JS list to keep in step), and clear the
  parity guards in `test_frontend_contract.py::TestCookiePanelParity` plus
  `test_crawl_capabilities.py::TestPlatformOrder`.
- **X (twitter) is visible-window, virtualized, and slow to paint — three measured facts, each one
  a line of code.** A headless browser gets the sign-up sheet on `/search` and a flat
  "Access to x.com was denied … HTTP ERROR 403" on a profile, so the class sets
  `never_headless = True` (like douyin, for the opposite reason: douyin blocks the *mode*,
  X blocks the *window type*). `article[data-testid="tweet"]` holds **13-21 nodes however far the
  page is scrolled** while 139 distinct tweets passed through eight scrolls, so progress is
  measured by rows kept and the settle wait watches `window_key()` — the set of status ids on
  screen — through `feed.walk_feed(window=…)`; a card-count watcher declares an exhausted
  timeline after one screen. Resume identity is the **status-id set**, never a list index.
  The first screen measured **0 cards at 9.9 s and 11 at 11.9 s**, so the mount poll is
  `MOUNT_WAIT` (22 s) — an 8-second wait reported "this keyword found nothing" on a search that
  was about to succeed. All five counters come from one `[role="group"]` aria-label sentence
  ("1887 replies, …, 1.1M views") through the shared 万/K/M parser, the per-button labels are only
  the fallback, and **浏览数 exists in no other place**; a live keyword stream really does read
  "0 Likes. Like" on almost every row, so do not assert engagement on `f=live` — assert 浏览数.
  A card node can be detached between listing and reading it (`StaleElementReferenceException`,
  observed), so the read is guarded and the tweet stays unseen for a later round. One
  `execute_script` per card, never per-field `find_element` — `tests/integration/test_twitter_crawler.py`
  counts both.
- **Captured cookies are filtered to their own platform** (`cookie_flow.retain_for_platform`),
  because a login detours through an identity provider (Google behind YouTube, Facebook behind
  Instagram) and `driver.get_cookies()` reads only the *current* page: the worker therefore
  pulls the browser back to the platform's own `login_url` before capturing, and anything still
  foreign when a paste comes in is dropped. Never widen this to `.google.com` for YouTube —
  those cookies open Gmail and Drive.
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
- **A node id is a storage key — never re-mint one on restore.** Run records, resume
  cursors, LLM answer caches and `workflow_fingerprint` all key on node ids, so
  renumbering a canvas detaches it from its own interrupted run. `canvas.addNode(type, x, y,
  nodeId)` adopts the stored id and `canvas.reserveId` keeps `nextId` past whatever was
  adopted (a later drag must not collide); both restore paths (`canvas.restoreState` for
  undo/redo and the draft, `WorkflowManager.loadFromJSON` for opening a file) pass the
  file's ids straight through — pinned by `tests/frontend/harness_state.mjs`.
- **One server at a time, by design (local single-user tool).** `RunStore.__init__` calls
  `promote_stale_runs()`, which marks every run still `running` as interrupted — it assumes
  that state was left behind by a dead process. Booting a second instance against the same
  `data/` therefore interrupts the first one's live run, and the two processes then write
  the same node rows/cursors. This is documented in README (启动应用) and is the reason
  `/smoke-verify`'s 5057 boot is only safe when the user's own server is stopped — ask
  before booting a second one, and never work around it by killing a process on 5000.
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
