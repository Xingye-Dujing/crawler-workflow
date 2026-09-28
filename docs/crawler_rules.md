# 采集端规则（从 `AGENTS.md` 拆出）

`AGENTS.md` 是每次会话都加载的核心规则；本文件装的是**只在动采集代码/平台断言时才需要**的两段：采集架构与
平台红线。**改任何爬虫、它的列、或真站断言之前，先读本文件，再读 `docs/crawler_notes.md` 对应平台小节**
（`AGENTS.md` 的 Change workflow 第 6/7 步把这句话变成硬要求）。这里每条规则都是真机付过钱的。

## Crawler architecture

- **Read the page before reviewing the code.** Any audit, fix or extension of a crawl starts by re-measuring the
  surface it reads (a throwaway `backend/test_<platform>_<thing>.py`, payload to `scratchpad/`): what the list is
  paged *by* — a button, the window, or one element's own scroll box; whether nested content (replies to comments,
  merged cards) exists only behind an expander; which container actually holds the rows; and which columns the page
  really shows. A wrong page model does not fail loudly — it makes every downstream judgement agree with itself, so
  summary, store and preview all concur on a table the page never offered (zhihu's comment panel: no 「更多」
  control, lazy-fills by scrolling its own overlay, nested replies behind an expander nothing clicked — measured in
  `docs/crawler_notes.md`). **Ask the page for a denominator (its own printed count) and grade against that.**
- **The crawl matrix (`backend/crawl_capabilities.py`) is the only answer to "what can this platform collect".** It
  declares each platform's modes, the fields each mode needs (widget, default, floor, ceiling, required-ness, and
  `fed_by` = the link field a wired upstream column may replace), which crawler method runs, and `region`
  (`cn` / `overseas`) — the overseas-VPN question and the `live_cn`/`live_os` markers read it rather than holding
  lists of their own. `_execute_source_node` dispatches, `engine/workflow.py::validate` refuses, and
  `GET /api/capabilities` hands the browser the identical description its Data Source panel is generated from. A new
  platform or mode is **one matrix entry**, never an `if platform == '…'` branch in four files. It sits at the
  backend root because `engine/workflow.py` reads it and must not import the crawler package. Field labels are
  *frontend* keys and required-field names *backend* ones (`field.*`), both pinned by
  `test_frontend_contract.py::TestCrawlMatrixParity`. A field name reaches an inline handler, so one not matching
  `/^[\w.-]{1,64}$/` is dropped whole, and the JS panel is tested against the matrix dumped from Python, never a
  copy checked in.
- **A record whose worker is gone is settled by the panel, not by a restart:** `/api/runs/list` settles a row this
  process opened and never closed, once no worker is alive. Adding a run status means updating
  `RESUMABLE_RUN_STATUS`, `purge`'s protection, the panel's `known` list and both app.js catalogs.
- **A headless run stays headless — nothing forces a window (#148).** A headless Chrome carries a desktop
  fingerprint, so every node/comment panel honours 无头/窗口 verbatim; `无头→窗口`/`forced_visible` are retired and
  `Mode.collects` is the single answer to "does a visible window show anything?" (the panel note and the comment
  engine's window decision both read it). Two measured traps: a sticky header can cover douyin's 筛选 opener's
  centre, so `menu.hover` also fires enter events on the node (`ActionChains` alone misses it); and a *stored*
  profile preference outlives the crawl, so 取/验证 Cookie and the pre-run probe write 允许 explicitly
  (`_content_prefs`) or a window shows a QR-less login.
- **`crawlers/engine/` is mechanics, a platform module is the site.** `engine.counters.parse_count`, `engine.wall`
  (the four page verdicts), `engine.popup.Prompt` + a platform's `prompts`, `engine.feed.walk_feed` / `wait_for` /
  `jump_to_bottom` (finds what actually moves), `engine.pager.walk_pages` and `engine.jsonpath` know nothing about
  any platform; a platform module declares only selectors, endpoints and column names. New crawl logic goes through
  these helpers — a second copy of a scroll loop or a 万-parser is what this rule exists to prevent. No walk has a
  round/page budget: "how much" is the user's target, never a constant. **A list is a document, not a bookmark:** a
  per-row page navigates away, harvest the list before leaving it. `Crawler.open(url)` is the only navigation entry
  point: it survives a renderer timeout and **records whether the navigation settled** — a load that never finished
  is a slow network, not a refusal, and a refusal may name only what the code can see. It clears the dialog, and
  latches a wall only once it is still there after re-reading.
- **A slow network is not a refusal, and only a refusal may be named one.** One page's *first content* gets
  `Config.PAGE_WAIT_TIMEOUT` via `Crawler.wait_for_first_content` — stop-aware, out early on evidence, refused once
  this browser has watched two expire; "any new rows?" keeps its short budget, because stretching a progress
  judgement buys a crawl that never ends. `wall.classify` answers four words (`VERDICTS` is closed); `unreachable`
  is the browser's own page, read from `documentURI` since `current_url` still shows what was asked for, and it sets
  **neither** wall flag — the site never saw the session.
- **One profile is one browser, and a parallel canvas has to be told that.** chromedriver pre-writes the profile's
  `Preferences`, so two sessions in one directory cannot both come up: `browser_profiles.acquire_profile(dir)` is a
  plain, **non-reentrant** `Lock` held for the crawler's whole life (a *side* thread releases it at close). The user
  answers 用 Profile per run as `use_profile`; 真排队 has answered it for the whole program. **A site's rate limit is
  a second collision** — two throwaway browsers can still be bounced as the *account* searching twice in one
  second — so `crawl_gate` lanes crawls by (platform, account): one login takes turns, two logins run at once (真排队
  holds a lane until its crawl *finishes*, 错峰 only spaces its starts). A matrix `serial_only` platform is always
  queued whatever the switch says; the browser warns first. A wall met **before the first row** retries once after a
  back-off; a wall met after rows is the cookie dying and must go to 继续 instead. **Absence means "follow the
  setting" — never coerce missing to `False`,** or one dialog's answer becomes a global override.
  `Config.PROFILE_LOCK_TIMEOUT` bounds the wait and the node fails with the directory named.
- **A Stop is a request, not a verdict.** 停止 writes `stopping` into the record **on the request thread** (the
  worker's verdict replaces it) and `stop_requested()` reads that — never `not running`, which an idle server also
  answers. Each crawl asks it at its next row via `Crawler.emit` (a `BaseException`: `except Exception` would
  swallow it into "the site sent nothing more"). **A walk may honour 停止 by *returning* its rows, so the executor
  asks again after it comes back: a returned table is not a completed node.** `driver.quit()` cannot interrupt the
  command the worker is inside, so 停止 kills that driver process. **A timeout not handed to the connection is a
  comment, not a ceiling:** `ollama.Client` defaults to `None` (never), so pass the run's timeout there; and the
  panel's post-stop watch must outlast the measured tail (`docs/crawler_notes.md`).
- **A crawl runs in the platform's own Chrome profile, and the profile owns its cookies.** `get_crawler` passes
  `data/chrome_profile/<platform>[/<account>]` as `--user-data-dir`, so the login window and the crawl are the same
  device — **one cookie, one profile**: an account's label enters both the file name and the directory, and `lock_for`
  keys on the path, so two accounts of one platform are two devices that can crawl at the same time. Consequence:
  **the saved cookie file is imported once** (first use of the directory) and is not re-planted by a crawl —
  overwriting a live profile with an old snapshot is the harm, not the fix. What changed (2026-09-28): **saving a
  cookie is itself the update**. A paste is the newest session there is, so `POST /api/cookies/save` plants it into
  that account's profile on the spot (`app.py::_plant_saved_cookie_into_profile`, the only caller of
  `get_crawler(refresh_cookies=True)`); the panel's 「把 Cookie 更新进 Profile」 button and
  `POST /api/cookies/refresh-profile` were deleted with it. When that browser is held, the save still succeeds, says
  so, and the next crawl of that account imports the newer file because `planting` also honours
  `browser_profiles.needs_refresh` (file stamp newer than the marker's). **Never write the browser's live jar back to a
  saved cookie file.** `Capability.profile_recommended` is the single source for "this platform punishes a throwaway
  browser"; a second list of platforms anywhere else will drift.
- **A new account's device directory is generated, never copied.** Cloud has no login window and the user's daily
  Chrome is off-limits (copying it ships his whole life to a server), so the program makes its own blank directory
  once — `data/chrome_profile/_template`, created by launching an empty headless Chrome in it
  (`crawlers.base.warm_profile_dir`) — and every account directory created afterwards is cloned from it. Four rules
  hold that together, each pinned by `tests/unit/test_profile_template_policy.py` and measured by
  `tests/integration/test_profile_template.py`: **"pristine" is answered by row counts, not by file names** (a blank
  first run writes `Cookies`/`Login Data`/`History`/`Preferences` empty, so names prove nothing); **the copy refuses
  its own denylist** — every store that can hold a session, `Local State` (the machine-bound key), and
  `.crawler-profile.json` (a seeded marker tells the import-once rule the account already has a session, so the
  cookie the user just pasted is never planted); **seeding is first-creation-only** (`os.makedirs(exist_ok=False)`,
  and a non-empty directory is left alone); **a template that stopped being pristine is destroyed and rebuilt before
  any account uses it**, not quietly copied. `_template` is a reserved platform name because it *is* a directory
  under the same root.

## Platform red lines (full evidence in `docs/crawler_notes.md`)

- **douyin**: headless works now (#148, was forced to a window by 验证码); search is DOM-only; **no 播放数 column
  exists**; don't block its images; authors are opaque `sec_uid` only.
- **X (twitter)**: headless works now (#148); the timeline is virtualized, so progress is rows kept and resume
  identity is the **status-id set**, never an index; all five counters come from one `[role="group"]` aria-label and
  **浏览数 exists nowhere else**; one `execute_script` per card.
- **bilibili**: `page=1` renders zero cards (request page one as the bare URL); comments have no DOM — only
  `x/v2/reply/main` by the server's own cursor; author mode is the space *page*, not the 403-wbi API; hot boards carry
  `owner`/`stat` inline so `hot()` fetches nothing per row.
- **youtube**: JSON-first via `engine/innertube` POSTs issued *inside* one loaded page (never hardcode
  `INNERTUBE_*`); headless is fine; a channel's uploads come from the loaded `/@handle/videos` document; a
  continuation token is chosen by **which list it is an element of**.
- **weibo**: never judge the wall from the URL right after `get()` (it flashes the passport page then bounces);
  `/ajax/statuses/mymblog` is a per-session edge 403 → refuse loudly, never an empty table
  (`backend/test_weibo_recipe.py`); the window scroll brings no new rows, and a search page serves *recommended*
  posts inside the same `#pl_feedlist_index` even when it also prints 「抱歉，未找到相关结果」 (measured 2026-09-28).
- **zhihu**: headless throttles day-by-day (risk 40362), so a headless search returning 0 rows is a legit outcome —
  don't loosen the assertion; comments run in either shape (#148). **A search card is an excerpt**, so the body
  arrives only by clicking: allowed where the row's own link says `/answer/`, and 正文 is the only column replaced.
- **xiaohongshu**: a replayed session is walled within minutes (profile required); author mode is dropped (needs a
  per-note `xsec_token` this session cannot reliably get).
- **wechat**: body-only by measurement — no comments/likes/forwards columns, **no cookie row at all**, no
  `mp_logged_in`/`login_url`/`diagnose`/`MULTI_PURPOSE`, no client impersonation or session replay. The `live_site`
  file visits article URLs only; panel harnesses sample bilibili/zhihu, never wechat.
- **instagram**: capture-only (`supports_crawl = False`), refused by `run.notCrawlable` and earlier by validation;
  such a platform still needs `domain` + `login_url`, stays OUT of `CAPABILITIES`, and must clear
  `TestCookiePanelParity` + `TestPlatformOrder`.
- **Cookie capture ≠ crawl capability**: `CookieManager.PLATFORMS` is who the panel can log in,
  `crawlers.is_crawlable()` who has a crawler. Captured cookies are filtered to their own platform
  (`cookie_flow.retain_for_platform`) because logins detour through Google/Facebook — never widen YouTube's list to
  `.google.com` (that is Gmail and Drive).
- **Cookie death mid-crawl is a designed path**: `login_wall` + under-target rows → `_execute_source_node` sets
  `execution_state['cookie_expired']` (rides on `/api/workflow/status` for the toast), logs `run.cookieExpired`, and
  **RAISES** so the node settles `partial` and the RUN becomes `failed` → the resume banner offers 继续 from the
  stored cursor. Never downgrade this to "completed with fewer rows" — that hides the gap forever. Comment nodes
  raise when any article was blocked likewise.
