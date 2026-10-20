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
  latches a wall only once it is still there after re-reading. **A navigation that never committed is re-driven, not
  refused:** after a cold launch the very first `get` can leave the tab parked on its own `chrome://new-tab-page`
  (empty address bar, spinning forever until a manual Enter), and `wall.classify` reads that internal page as
  `blocked` — filing a keyword that plainly has results behind a false 风控; the same parked page makes
  `_load_cookies` plant every cookie into a document whose origin matches nothing, so the session itself rides on a
  launch that did not fire. `Crawler._drive_off_internal_page` re-issues the `get` while the browser is on one of its
  own pages (`never_arrived`) and is shared by `open` *and* `_load_cookies` so the two never disagree about whether
  the site was actually reached. `NAV_RETRY` is measured to 1 (the user's fix was one Enter, and it keeps the probe's
  page loads inside `COOKIE_PREFLIGHT_TIMEOUT`). It fires on that shape only — a committed page, a real wall and the
  browser's own `chrome-error://` are each answered once — and a *deliberate* internal navigation stays outside it:
  the template warmer enters `about:blank` on purpose, so it is a bare `driver.get`, never re-driven off itself.
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

- **A relative timestamp is resolved at READ time, and only there.** The sites print
  「3小时前」/「昨天 21:30」/「2 days ago」 for anything recent, and storing that wording is what
  rots: the same cell means a different date tomorrow. Leaving it stored was the old answer
  (``normalise_rfc822`` returns what it cannot parse untouched) and it is honest and useless —
  a time series over it silently loses exactly the rows a live event is about, and 发布时间 is
  empty for them. So every platform hands its own time cell through **``engine/times.absolute``**
  (RFC-822 → the site's CJK display form → a relative wording → unchanged), which converts once,
  at the moment of the read. Two properties make that safe rather than a fabrication:
  - **the recognised set is CLOSED.** ``relative_to_absolute`` admits a listed set of Chinese and
    English shapes and answers ``''`` for anything else, so a topic tag or a layout string can
    never become a timestamp — which is the same protection bilibili's author mode bought by
    leaving relative words empty (``crawler_notes`` line ~578) and the reason douyin's
    ``_publish_from_info`` **still refuses** them: that cell is a ``·``-split segment, not a
    dedicated time node, so we cannot be sure the token is a time at all. ``_clean_publish``
    (the cell the page labels 发布时间) does convert.
  - **the precision is stated, not dressed up.** An OFFSET (``3小时前``) names an instant, so it
    answers ``now − N`` and keeps the clock; a NAMED DAY with no clock (``昨天``, ``yesterday``)
    names a day, so it answers that day's ``00:00`` rather than a made-up reading. A year-less
    date (``09月26日 21:00``, ``09-10``) is deliberately NOT inferred — the same decision as
    bilibili's, because guessing the year moves a row into another year.
  Pinned: ``tests/unit/test_times.py``.

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
- **hongguo (红果短剧)**: four boards are **one mode + one board select** whose values are storage identifiers
  (`crawlers/hongguo.py::BOARDS` is the single name list, order-pinned against the matrix); the board is read from the
  document's own loader payload (`window._ROUTER_DATA` → `rank_<slug>/page.content._data`), **never from the rendered
  columns** — and it is **deferred** (~2 s after `get`), so wait through `wait_for_first_content`, never a fixed sleep.
  集数 is the length of the payload's `episodeVids`, not the DOM's 25-link player window. Paging follows the site's own
  `pagination.nextUrl` (that URL is the cursor); `?page=1` is the bare URL, and the unserved `?page=6` renders
  `rank_layout` alone → `stalled` → `PageNotArrivedError` **named refusal**, never an empty board. Anonymous: no
  `login_url`, no cookie row, `needs_session=False`, and `live_crawler` exempts it like wechat. 热度/收藏/点赞 are
  rounded 万-labels expanded by `parse_count` (absent → blank, never 0); 分类 keeps the site's literal `205` tag id.
  `search`/`get_detail` are named refusals — no such mode was ever measured.
  **Its comments exist only in the app protocol, and this tool never speaks it — it listens.** The signature is
  body-covering (byte-identical replay answers 110001, measured 2026-10-19), so the 评论 mode drives the third-party
  desktop player behind our own mitmproxy and parses what the player legitimately fetched
  (`crawlers/hongguo_harvest.py`; full chain in `docs/crawler_notes.md` 红果短剧). Rules that keep it honest: a player
  window the USER opened is refused by name, never killed — only Popen-children of this node get reaped;
  navigation is the leaderboard page's per-card ``▶ 播放`` (the 找剧 page has NO search box — measured), and
  the comment trigger is the action-rail ``💬 <count>`` click that opens the drawer (the feed's silent prefetch
  died with a protocol update the same day); danmaku-guide rows (`create_timestamp == 0`) are dropped and
  counted, never emitted as comments; a page whose NON-ZERO `book_id` names another drama is discarded by
  name (real rows print `book_id: "0"`, so 0 means "unnamed", not "wrong show"); the walk may only say
  `site_end` when the ARITHMETIC closes — every group's kept reached the `total` the site itself printed
  (`has_more: false` alone is a cursor window ending, not a thread: measured 20 kept of 800) — and any
  scroll failure leaves `UNDER_TARGET`; the harness ALSO publishes `shortfall` (rows the site counted
  that this walk did not keep), because comparing ROWS against the total is NOT a fair test — reply rows
  ride in the table under no episode's printed total, and a short 698-comment episode can otherwise be
  masked by 400 children harvested elsewhere; a UIA tree that never wakes is its OWN named refusal (`treeCold`),
  never a fake 搜不到剧 — and warming is the FULL walk itself (partial early-return walks read the tree cold
  forever); mitmproxy 11's `Response` has no `get_json()` (a bare `except` turned it into a silently empty
  capture — decode `response.content` explicitly); a topmost window over the player silently steals every
  synthetic click (measured); and the comment engine's U1 gate reads `end_reason` BY ATTRIBUTE, so every
  browser adapter stays untouched. WebView2 CDP is a dead end (the loader env var is overridden by the
  app's own options) — do not retry it.
  **Four more, from the second live run the same night** (each one cost real rows): the drawer's per-comment
  button is literally named `回复` and it opens the COMPOSER — clicking it steals the keyboard from the wheel and
  an 800-comment episode comes home as 20 rows, so an expand click must match `is_expand_control` (the name
  carries 回复 AND one of 展开/查看/更多), every visible expansion gets clicked per episode (not one), and
  `SendKeys {Esc}` hands the focus back. One silent scroll is never the end of a thread: paging retries with an
  escalating action (wheel → Esc+harder wheel → `{PageDown}`) and a growing window, and only after `_MAX_STALLS`
  silences does the episode settle short — naming `kept` against the site's `total`. The WEB board and the
  CLIENT's boards are two different rankings, so the comment form also accepts a plain 剧名: that is declared
  once as `Field.accepts_names` and the panel check, `engine.workflow` validation and the comment router all read
  the matrix (a name-fed row keeps `文章URL` BLANK — no page was opened, no link is invented — and the 错剧 guard
  falls back to the first non-zero `book_id` of the walk as its reference). A tree that goes cold MID-walk raises
  the dedicated `TreeCold` (never compare message text), gets one louder re-wake, and then skips THAT drama by
  name into `skipped_targets` while the rest still harvest; the engine refuses the node at the end naming them,
  rows kept. `文章URL` itself is NOT renamed for the drama's sake: it is the join key of all eight comment tables
  (66 references), and 短剧 semantics live in the added columns 剧名 / 集序号 / 分集ID (the id column held a
  per-EPISODE `group_id` and was misnamed 剧集ID).
  **And six more, from auditing that change** (each is a way the node could still settle `DONE` over a hole):
  an expanded child thread prints its OWN `total` too, so `reply/list` pages are graded in `_reply_progress`
  and `site_end` now requires children as well as episodes — clicking 展开 once and taking 20 of 200 is a named
  gap (`子回复不完整`), never a full table; a walk that ends with NOTHING (`titleMissing`, or `noTraffic` on the
  first episode — the popup-blocked-drama case) goes through `_mark_short()` + `skipped_targets` like any other
  hole, because a bare `([], DEAD)` fed neither tail gate and a five-drama feed came home as a four-drama table
  marked 正常; a reply page is stamped with the drama whose drawer asked for it (`_stamp`), since expansion
  fires up to 40 requests, the per-episode grace is short, and a late page drained under the NEXT target
  corrupts 剧名/文章URL rather than merely losing a row; card matching takes an EXACT normalised title across
  the whole tree before any prefix match, because `斗罗大陆` answers a request for `斗罗大陆 第二季` and the 错剧
  guard cannot catch it on a name-fed walk (the reference `book_id` is read from the wrong drama's own first
  page); the board list is read AFTER the switcher is opened, never from the closed page — one tab named like a
  board satisfies the same pattern as the whole list, and the walk then "cannot find" every drama on another
  board; and 停止 is asked inside every UIA wait (`PlayerUI` holds the harness `abort`, and `open_drama`'s
  `except Exception` re-raises `CrawlerStopped`), otherwise a cold tree burns minutes per drama uninterruptibly
  and a Stop mid-open was filed as 「搜不到这部剧」.
  **Three more, measured on the third live run (2026-10-20, capture kept on disk)**: `reply/list` is a
  DIFFERENT envelope — `data.comment_list_info` + `data.reply_list[]`, element body under a CAPITALISED
  `Common`, own id `reply_id`, parent in `data.comment`, and **no `data_list` at all** — so reading only
  `data_list` made every 「包含子回复」 run silently collect ZERO children (53 expansion clicks, 0 rows);
  normalise the element into the `comment/list` shape and keep ONE row builder. Which drama a page belongs
  to is asked of the **request** (`req_body.business_param.book_id`), never of the rows: another drama's
  comment pages print `expand.book_id == "0"`, and grading the payload let 30 stranger rows into the table
  under the fed 剧名. The gate covers reply pages too (the expansion clicks on whatever is on screen). And
  the web `series_id` is **not** the client `book_id` (same drama measured: `7696437705822981182` vs
  `7697823071830297624`) — two id spaces, so the reference is the first page's own book and comparing the
  two would refuse every page a link-fed walk correctly asked for. When a page arrives for a different
  book the walk names it and **stops the drama** (`feedDrifted`) rather than spending every remaining
  episode's full wait on traffic it will never accept. The walk also **asks the screen before it
  harvests** (`PlayerUI.screen_drama_title` → `_confirm_position`): the player prints `@剧名` in the
  header. That header is the ONLY screen fact the drawer-open tree offers — the `N / M` episode
  counter is on the video page but **absent once the comment drawer is open** (measured in the warm
  dump), so the walk cannot read its own position from it and a gate built on `第N集` (what it numbers
  was never established) would refuse dramas it was harvesting correctly. The header answers at entry
  and after each `next_episode`, and it is read with two rules that bias toward PROCEEDING, because a
  wrong 「drifted」 throws away a drama the user paid to open while a wrong 「keep going」 is caught a
  layer down by the traffic gate: a single foreign read is **re-asked** before it is a verdict (the
  header prints whatever is on stage and the browse page keeps naming the PREVIOUS show for a moment
  after a card click), and the match is a prefix in EITHER direction at any length (the header is the
  BASE name, the request may carry a season suffix — or the reverse). Not exactly one `@`-prefixed
  text means no answer (a 弹幕/reply that opens with `@昵称` sits before the header in tree order). A
  tree that prints nothing confirms nothing, and the traffic gate stays underneath as the second line
  of defense. A `next_episode()` that fails to land is **counted** (`_count_unfinished`), not just
  licensed false: the never-reached episodes print no total, so shortfall alone cannot name that hole.
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
- **A shortfall must be licensed by the SITE, never by our own loop (U1/U2).** `walk_feed`/`pager` report a
  self-summary (`'stuck'` = "stopped growing", `'no_new'`) that a soft throttle mimics, so it is **not** proof the
  site ran out, and the executor must not quietly license it. The harness mostly agrees (`SHARED_EXITS` holds none of
  those) — **but zhihu's `author` tier still whitelists `crawl.zhihu.authorTabDone`, a self-summary**; that exception
  must be closed when zhihu migrates, exactly as the X and bilibili tiers already refuse their `finished`/`authorDone`. The contract is `crawler.end_reason`, **three states**:
  `None` (handler not migrated → the gate stays silent, so platforms migrate one at a time with no half-red tree);
  `UNDER_TARGET` (`''`, the handler ran short and saw no site end → the executor **refuses by name**
  `run.underTargetShort`, settling partial/继续, NOT clean DONE); or a member of `crawlers.base.LICENSED_ENDS`
  (`'site_end'` / `'capped'` / `'empty'` — each requires a fact the SITE attested: an end-of-list marker, a fixed
  board size, a server-confirmed 200-empty list; NOT an unrendered DOM that merely "looked empty"). A login wall and
  the user's 停止 are settled by the executor BEFORE this gate; a **risk bounce has its own gate ahead of U1** (see the
  next paragraph) and U1 itself still skips when `risk_blocked` is set, so the two refusals never collide; a license is
  never one of the three.
  **A short crawl the platform marked `risk_blocked` is named 风控 (back off), not 采得不足 (U1) and never a dead
  cookie.** `_execute_source_node` raises `run.riskControlled` when `risk_blocked`, the target was missed and there is
  NO login wall — keeping the rows, failing the run so 继续 appears, and telling the user to WAIT (it explicitly suggests
  慢速采集), because re-running straight into risk control is forbidden advice and re-saving a session that may be fine
  is a lie. Douyin is the reason this exists: its 验证码中间页 speaks only in the tab TITLE, which `classify` never reads,
  so `DouyinCrawler._latch_risk_if_walled` sets `risk_blocked` at the ONE crawl-level point a captcha can end an author
  walk — a profile grid that never arrived — deliberately NOT `login_wall`. It is NOT re-checked at the end of a walk:
  a per-detail-page 验证码 (measured to fire on a share of every walk) leaves a stale title that would false-convict a
  crawl that collected everything the site has. The comment node splits the same way: `_execute_comment_node` records
  which blocked platforms latched `risk_blocked`, and raises `run.riskControlled` only when EVERY blocked platform named
  风控 and none named a login wall; any cookie wall, or any platform naming neither, keeps the original cookie verdict AND
  its `cookie_expired` toast flag (a bare BLOCKED never set that flag before either, so nothing regresses).
  **The ONLY sanctioned way to reduce 风控 is pacing, never disguise.** The `gentle_crawl` setting scales the POLITENESS
  pauses — `Crawler._polite_pause` and the douyin panel's between-screen wait — by `GENTLE_PAUSE_FACTOR`; it is speed only.
  The comment engine's per-URL `nap` calls are NOT scaled: those are page-arrival render budgets, not anti-bot pacing, and
  stretching them just slows the crawl and delays honouring 停止. No UA/`navigator`/fingerprint work is added or permitted
  here, since spoofing detection is an arms race whose loss mode is a banned account, not a blocked request.
  **`Crawler.note_end(reason)` raises on any value outside `None`/`UNDER_TARGET`/`LICENSED_ENDS`, and on a non-string**
  (a bare truthiness test would let a bool `note_end(x.hit_cap)` slip past as falsy and go silently unlicensed), and
  `None` is a no-op, never the convicting `''`: a crawler excusing a gap with its own pager crashes at the boundary
  instead of stamping 完成 on a thin table. A convicted short may carry the walk funnel (`scanned/kept/refused`),
  rendered ONLY when all three were measured; a partial or absent funnel is omitted, never printed as fake zeros.
  **Current arming: the LICENSE side is wired for the platforms with a real site-attested end**
  (douyin author `empty`/`capped`/`site_end` marker, zhihu search `no_more` + hot `capped`, weibo hot
  `capped`, youtube search `drained`, bilibili hot `empty`/`capped`, **hongguo hot `site_end`/`empty`**),
  **and one handler now convicts: hongguo's `hot` issues `UNDER_TARGET`** — it is the first platform
  whose short has a POSITIVE incompleteness signal instead of a self-summary. The site hands out the
  next page address itself (`pagination.nextUrl`), so the three ways its walk can end short are each
  attributable: a `nextUrl` that points back at the page just read, or two pages in a row that brought
  nothing new while the pager still offered a next one (a resume of a page the ledger already holds is
  why the first no-fresh page is tolerated) — those are our loop stopping, and the executor now refuses
  them by name; the site's own "no next page" (`site_end`) and an `isSuccess`-attested empty list
  (`empty`) license the rest. Every other platform stays as before: its license is armed (a license and
  `None` both settle clean, so arming one changes no observable outcome), but its conviction is still
  deferred — a scroll/cursor walk's "stopped growing" / "cursor gave nothing new" fires *identically* on
  a soft throttle and on an honest 继续 replay (the cursor points at a page the ledger already holds), so
  convicting on it would false-fail good resumes, and §6's conviction needs a POSITIVE incompleteness
  signal which only per-platform live measurement (#7) can supply. Platforms with no reliable end signal
  stay fully un-armed (`end_reason=None`): weibo search (its `'end'` is a loop fallback, not a site
  marker), weibo/youtube author, bilibili search/author, xiaohongshu, twitter, zhihu author.
  Pinned: `tests/api/test_under_target.py`, `tests/unit/test_hongguo_crawler.py`.

- **A 分批输出 stem is a storage key, not a label: it must be identical across every attempt of
  one run.** `PartWriter` adopts the shards a crashed attempt already flushed by matching
  `{stem}.part` as a directory prefix (`services/part_writer.py`), and `run.progress_file`
  announces the merged file the user is told to open. So any component that changes between
  attempts of the SAME run silently orphanes those parts and restarts the numbering at 001
  beside them — the resume looks green and the merged table is only the tail. That is why the
  optional 「创建时间」 component (`utils.helpers.export_stamp`) is read from the run RECORD's
  `started_at` plus its `run_id`, never from the clock at write time: `run_store.start_run`'s
  继续 conflict update deliberately does NOT refresh `started_at`, and `run_id` is what the
  resume keys on, so both are stable per record and different between records. A date-only
  component is not enough on its own — a parallel canvas opens several records inside one
  second. The time window a crawl was told to walk (`utils.helpers.window_tag`) is safe to put
  in the same stem for the same reason: it is a node parameter, so it cannot drift mid-run.
  Pinned: `tests/unit/test_utils.py::TestExportStamp`, `tests/api/test_nodes_execution.py::
  TestWindowedFilenames::test_the_stamp_a_resume_reuses_is_the_record_and_not_the_clock`.
- **A filename component is a name being chosen, so an ambiguous one is refused by name.**
  「文件名带时间范围」 asks the SAVE node to print a window it cannot see (it receives a table),
  so the range travels through the run (`execution_state['_time_windows']`, keyed per workflow
  exactly like the console buffers, recorded where the crawl states it). Zero windows and two
  different windows both fail the node saying which, rather than naming a file after a stretch
  this table does not describe — a CSV labelled with the wrong month reads as evidence.
  The resolved name is still never written back into `node['params']` (the fingerprint rule).
