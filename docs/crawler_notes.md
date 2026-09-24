# Crawler measurement record

`AGENTS.md` carries only the red lines. This file carries the *evidence* behind them, so nobody
re-pays for a measurement that already happened. **Read the section for the platform you are about
to touch.** Every claim below was observed against the live site; the date it was established is in
the text. When a measurement is overturned, replace the old paragraph rather than appending a
second opinion beside it.

## Contents

- [Weibo](#weibo) · [Zhihu](#zhihu) · [Douyin](#douyin) · [Bilibili](#bilibili)
- [YouTube](#youtube) · [X (twitter)](#x-twitter) · [WeChat](#wechat) · [Xiaohongshu](#xiaohongshu)
- [Cookie capture vs crawling](#cookie-capture-vs-crawling)
- [Browser options that were measured](#browser-options-that-were-measured)
- [Crawl cost is a testable property](#crawl-cost-is-a-testable-property)

## Weibo

**Weibo serves a fake login wall**: a search first flashes the passport QR page, then bounces the
logged-in session back to the feed. Never judge the wall from the URL right after `get()` —
`WeiboCrawler._await_search_page` waits for a terminal state (cards / no-result plate / persistent
passport page). Keep that ordering in any refactor.

**Never write the browser's jar back to a saved cookie file.** Measured 2026-09: one logged-in page
load re-issues the pair (`SUB` 90→94 bytes, `SUBP` 144→56, `XSRF-TOKEN` replaced), and planting that
rotated jar into a fresh browser is bounced straight to `/newlogin` — a write-back would degrade the
user's file one crawl at a time. A replayed save still *is* accepted (several browsers in a row land
logged in), which is why the failure mode looks like a stale cookie and is not.

**`/ajax/statuses/mymblog` is a per-session throttle, not an endpoint.** The same measurement says a
weibo author/profile crawl must not be written against it: it answers `200` with real posts in one
session and `<h2>403 Forbidden</h2>` (an edge/WAF body, not a weibo business code) in the next, with
the same walk and the same logged-in nav. So that mode needs a loud refusal, never an empty table,
and `backend/test_weibo_recipe.py` is the re-test gate.

**Re-measured 2026-09-24 (visible Chrome, the saved weibo profile): the endpoint answers, and what it
answers is the author's own timeline.** Recipe
`https://weibo.com/ajax/statuses/mymblog?uid=<UID>&page=<N>&feature=0`, fetched *inside the loaded
page* with `credentials: 'include'` — the same shape bilibili comments and YouTube innertube use
(a page-context fetch, not a standalone request):

* page 1 → **28 rows**; page 2 → 20 rows with **20 unseen ids**; page 3 → 20 rows with 20 unseen ids.
  Plain `page=N` advances, so no cursor has to be followed. The page-1 surplus is a fact to pin
  ("page 1 may return more than the rest"), not something to normalise to 20.
* the first row's `user.id` equals the requested `uid`. That is the ONLY thing distinguishing a real
  author crawl from a mirror of the home timeline, because both answer `200` with the same envelope
  (`data.list`, `data.since_id`, `data.pageid`). An earlier reading of this probe printed the same
  `since_id` three times and looked like the home feed — it was the same request body previewed
  three times, not the endpoint ignoring `uid`. **Do not re-derive this from a truncated body:** the
  probe sliced responses to 300 characters, so its contract step died on `json.JSONDecodeError` and
  cost four runs to get here.
* rows carry `id` `mid` `mblogid` `created_at` `text` `text_raw` `source` `region_name` `visible`
  `isLongText` `pic_num` `pic_ids` `reposts_count` `comments_count` `attitudes_count`
  `retweeted_status` `user`. `text_raw` sits next to the HTML `text`.
* still unmeasured before the handler is written: whether `isLongText` rows are truncated in this
  list (i.e. whether a detail fetch is needed for the full body), and whether the 403 comes back for
  this session shape. Reading counts from JSON is cheaper and steadier than the DOM walk the search
  mode uses, so a profile crawl must not copy the card scraper.

## Zhihu

Zhihu throttles headless content pages day-by-day (risk code 40362); comment crawling always opens a
visible browser for zhihu, and a headless zhihu search returning 0 rows is a legit risk-control
outcome the message catalog already explains — don't "fix" it by loosening assertions.

## Douyin

**Visible-window-only, DOM-only, entered through its URL, and has no play count.**

A headless browser is answered by 验证码中间页 on *every* navigation (measured), so the class sets
`never_headless = True` and `_execute_source_node` downgrades to a visible window before buying the
browser — never let that flip back to headless "for speed". Its search endpoint is signed
(`a_bogus`/`msToken`/`verifyFp`), so the DOM is the only path.

**Re-measured 2026-09, and two long-standing facts died together:** the search box still accepts the
text and its 搜索 button is still clickable, but *neither the click nor Enter routes any more* (the
address sits on `/jingxuan`; the user watching the window reported exactly this), while the
`/search/<kw>?type=video` deep link — documented for a year as an empty shell of three `<ul>`s — now
serves the result list. So `SEARCH_ENTRY` is the route, the keyword is percent-encoded into the path,
and there is no router left to interrogate about which search ran. Cards are
`[data-e2e="scroll-list"] a[href*="/video/"]` and the id comes out of the href — the old
`div.discover-video-card-item[data-aweme-id]` matches **zero** nodes now and the class names beside it
are build hashes.

**The list mounts as 16 skeleton rows (no anchor, no text) and fills in ~4–6 s**, so "some nodes
exist" is not "results exist": `_wait_for_cards` polls for an *anchor* (`MOUNT_WAIT`), and a page that
never fills is `NOT_MOUNTED` → zero rows, which is the honest answer for a keyword nobody posted. The
**window** now does the paging (measured 16 → 26 → 36 → 46 → 56 cards per ~0.9-viewport scroll), so
`_scroll_results` scrolls the window and stops the walk when a scroll yields nothing new — and the
loop checks the row budget *before* scrolling, because scrolling first would wait out `SCROLL_WAIT`
for rows nobody asked for. Counters still come only from the self-describing `data-e2e` keys **on the
video page** (`video-player-digg`/`feed-comment-icon`/`video-player-collect`/`video-player-share`);
`detail-video-info`'s second number **is the like count** — and the search card's single bare figure
measures equal to it — so a 播放数 column would be a wrong figure with a plausible name: don't re-add
it. The 「是否保存登录信息超过5天」 mask still mounts seconds after the page and is dismissed on arrival
(取消 only — the user reports 保存 leads to a phone-verification step). Comments DO render
(`[data-e2e="comment-item"]`) and grow only by scrolling the panel container; both the panel mount and
each scroll settle by *polling inside the crawler*, never via the caller's `nap` — a stubbed nap once
turned a 2000-comment video into an "exhausted" 5-row crawl.

**Author mode is paged by a container the window cannot move.** Measured on `/user/<sec_uid>`:
scrolling the window grows the **footer's** recommended-video links (8 → 29 anchors) while the 作品
grid (`[data-e2e="user-post-list"]`) does not move — a count-based walk therefore stops at 57 on a
page that publishes 85. Taking the grid's scrollable ancestor to `scrollTop = scrollHeight` pays out
18 rows a round (21 → 39 → 57 → **85, which is what `[data-e2e="user-tab-count"]` says**) and is why
`engine.feed.jump_to_bottom` exists (the comment panel scrolls the same way, so it shares it). A
creator is addressed by the opaque `sec_uid` only — `/user/<numeric>` is not a route — and every video
page carries `a[href*="/user/"]`, so a live run can discover one; a display name is refused.
`DouyinCrawler._published_count()` returns **-1 for "the page said nothing"**, because the shared
`parse_count('')` answers 0 and 0 is a *claim*: reading a missing number as zero would let a page
that never rendered report an author who never posted. Rows still come from opening each video
(`_detail_row`), so this mode carries the same columns as the search mode — including the absence of
播放数.

**A self-paging list is walked by `_open_each`, and "every id here is known" is not its end.** The
loop used to `break` when the current screen held no unseen id — which is the *normal* first round of
a resumed run, because the page reopens on exactly the ids the dead run opened. The symptom was a
断点续跑 that returned the previous run's rows, never reached its target, and complained about
nothing. Now an empty `todo` scrolls on and only a scroll that pays out nothing ends the walk; both
douyin lists share the one loop.

## Bilibili

**Its two paging contracts are measured, not guessed — keep them exactly.**

The search list does *not* infinite-scroll (8 scroll rounds = 42 cards / 34 videos, unchanged); the
row budget is `&page=N`, and **`page=1` renders zero cards**, so page one must be requested as the
bare `all?keyword=` URL (a crawler that slept on `page=1` would report an exhausted search). Card
numbers are a rounded 万-label only: every count comes from `x/web-interface/view?bvid=`, which
answers `code=0` unsigned, cross-origin from the search page, for the cookie the panel saved.
Comments have **no DOM at all** (`.reply-item` renders nothing), so `x/v2/reply/main` is the only path
— and its `next` is a cursor, not a page counter: `next=0` reports `cursor.next=2` while `next=1`
replays page 0 byte for byte. Walk by the server's value and stop on a page with no new `rpid`; an
incrementing loop would store the same 19 comments forever. `code=-404` is one withdrawn video
(skip); any other non-zero code is the session/risk engine talking (stop, and refuse the run if
nothing was collected).

**Author mode is the page, not the API**: `x/space/wbi/arc/search` answers `code=-403 访问权限不足` for
our session (the older un-wbi path is rate-limited at `-799`), so `BilibiliCrawler.author()` opens
`space.bilibili.com/<mid>/video` once and pages it by scrolling (measured 40 cards on one screen, 80
anchors after three steps) while every number still comes from the unsigned `x/web-interface/view` —
so a row is identical across the two modes. `bilibili_mid()` takes digits or a space link and refuses
anything else: opening a mistyped space would report "this UP posted nothing" about a page that is not
theirs.

**Hot boards need no per-row request**: `x/web-interface/popular` (20 a page, page 2 disjoint) and
`x/web-interface/ranking/v2` (the whole 100-item board in one reply, so it is walked as a single page)
answer `code=0` unsigned for our session **with `owner`/`stat`/`pubdate` inside each item** — the same
shape `view` returns for one video, which is why `hot()` reuses `_row()` and fetches nothing per row.
Reaching for the search loop's one-request-per-row here would produce the same table at 50× the cost.

## YouTube

**JSON-first, headless-safe, and its pagers are chosen by their list.** Measured 2026-09: the crawler
opens **one page** to read `ytcfg` (`INNERTUBE_API_KEY` + `INNERTUBE_CONTEXT`, never hardcoded — they
rotate) and then POSTs `youtubei/v1/{search,browse,next,player}` **from inside the page**
(`crawlers/engine/innertube.py`), which is same-origin, unsigned and cookie-carrying: search 0.68 s /
10 rows, player 0.31 s / 11 KB, comments 0.32 s / 20 rows. Headless and visible returned identical
rows and facts, so the class sets **no** `never_headless`, and `page_load_strategy='eager'` + blocked
images stay on (nothing is read from pixels). Two rules that only measurement could establish, both in
`innertube`:

- **A channel's upload tab must be read off the loaded `/@handle/videos` document** —
  `browse(browseId, params=videos)` answers the channel **HOME** (3.7 MB of shelves, other channels'
  videos mixed in), so the author mode navigates once and pages from the document's own cursor.
- **A continuation token is picked by which list it is an element of**, not by length or position — a
  comment round carries two 78-char sort-menu tokens that each replay page one (the ledger swallows
  the duplicates, the walk reports success, and a 3000-comment video yields 20) plus one per
  reply-bearing thread, while the list's own pager is its trailing element. `next(videoId)` is worse:
  six tokens, the comment one 78 chars on one video and 146 on another with 1412-char rail tokens
  beside it, so the first round *tries* candidates until one answers with comments.

`lockupViewModel` (the 2025+ view model) and `videoRenderer` coexist — search is the former's absence,
channel tabs the latter's — and a reader for one is silently empty on the other.

## X (twitter)

**Visible-window, virtualized, and slow to paint — three measured facts, each one a line of code.** A
headless browser gets the sign-up sheet on `/search` and a flat "Access to x.com was denied … HTTP
ERROR 403" on a profile, so the class sets `never_headless = True` (like douyin, for the opposite
reason: douyin blocks the *mode*, X blocks the *window type*).

`article[data-testid="tweet"]` holds **13-21 nodes however far the page is scrolled** while 139
distinct tweets passed through eight scrolls, so progress is measured by rows kept and the settle wait
watches `window_key()` — the set of status ids on screen — through `feed.walk_feed(window=…)`; a
card-count watcher declares an exhausted timeline after one screen. Resume identity is the
**status-id set**, never a list index.

The first screen measured **0 cards at 9.9 s and 11 at 11.9 s**, so the mount poll is `MOUNT_WAIT`
(22 s) — an 8-second wait reported "this keyword found nothing" on a search that was about to succeed.
All five counters come from one `[role="group"]` aria-label sentence ("1887 replies, …, 1.1M views")
through the shared 万/K/M parser, the per-button labels are only the fallback, and **浏览数 exists in
no other place**; a live keyword stream really does read "0 Likes. Like" on almost every row, so do
not assert engagement on `f=live` — assert 浏览数. A card node can be detached between listing and
reading it (`StaleElementReferenceException`, observed), so the read is guarded and the tweet stays
unseen for a later round. One `execute_script` per card, never per-field `find_element` —
`tests/integration/test_twitter_crawler.py` counts both.

## WeChat

**Intentionally body-only.** No comments, likes, forwards (and usually no read counts) — measured, not
assumed: a real browser gets `show_comment=0`, zero `elected_comment` bytes in ~3.4 MB of article
HTML, and an HTML 验证 page ("请在微信客户端打开链接") from `mp/appmsg_comment`; a `MicroMessenger`/`XWEB`
UA, client-shaped URL params and replaying the client's own decrypted `mp.weixin.qq.com` cookies
(`pass_ticket`, `appmsg_token`) change nothing, because the gate is a per-session credential the
server mints only for a real client session. **Do not add client impersonation or session replay to
get around it, and do not re-add those columns** — in a browser "no comments" and "not allowed to
look" are indistinguishable, so an empty table would be plausible-looking false data. WeChat's 数据源
node therefore offers no comments mode, and `explainWechatLimits()` (workflow.js) +
`settings.wechatLimits*` (app.js) state why.

**WeChat has no cookie row at all.** Keyword search via the 公众号后台 was measured to be the only thing
its session unlocked, and it was deleted rather than shipped unverifiable: `appmsg?action=list_ex`
answered `ret=200013 freq control` for three accounts, three endpoint spellings and every retry after
a 15-minute cooldown, so the article-item field shape was never observed once. Article *bodies* need
no login. Do not re-add `mp_logged_in`, a `WechatCrawler.diagnose` override, `WechatCrawler.login_url`,
`cookie.wechat.*` text or `MULTI_PURPOSE` — and do not implement keyword search again by guessing
field names. Because there is no login, nothing may *behave* as if there were one: the `live_site`
WeChat file crawls article URLs only (no 公众平台 visit, no cookie wait/skip), and the cookie-panel node
harness samples real login platforms (bilibili/zhihu), never `wechat`.

## Xiaohongshu

Xiaohongshu walls a *replayed* session within minutes while the user's own browser keeps working —
that is why the crawl runs in the platform's own profile (see `AGENTS.md`). Its author mode was
dropped unmeasured: the route needs a per-note `xsec_token`, which a session that is being risk-scored
cannot be relied on to yield, and the account here is behind 风控 after a few attempts. Don't rebuild
it by guessing token plumbing.

## Cookie capture vs crawling

`CookieManager.PLATFORMS` (8) is who the panel can log in; `crawlers.is_crawlable()` (8: zhihu, weibo,
xiaohongshu, wechat, bilibili, douyin, youtube, twitter) is who has a crawler. **Instagram is the one
capture-only platform** (`overseas.py` registers it with `supports_crawl = False`; the account used for
the measurement was banned, so no real crawl was ever possible), so `_execute_source_node` refuses it
by node label (`run.notCrawlable`) and validation refuses it earlier still
(`engine.source_unknown_platform`, because it is not in the matrix at all) — never let a not-yet-built
platform fall through to an empty table, which reads as "this keyword found nothing". A capture-only
platform must still carry `domain` + `login_url` (the panel needs both), stay OUT of
`crawl_capabilities.CAPABILITIES` (that tuple *is* the Data Source's platform list now — the browser
renders the select from `/api/capabilities`, so there is no JS list to keep in step), and clear the
parity guards in `test_frontend_contract.py::TestCookiePanelParity` plus
`test_crawl_capabilities.py::TestPlatformOrder`.

**Captured cookies are filtered to their own platform** (`cookie_flow.retain_for_platform`), because a
login detours through an identity provider (Google behind YouTube, Facebook behind Instagram) and
`driver.get_cookies()` reads only the *current* page: the worker therefore pulls the browser back to
the platform's own `login_url` before capturing, and anything still foreign when a paste comes in is
dropped. Never widen this to `.google.com` for YouTube — those cookies open Gmail and Drive.

**Cookie planting visits a host only when a cookie needs it** (`base.Crawler._load_cookies` keeps the
entries the current host rejected and stops when nothing is left): every extra host is a real page
load, measured at ~2.3 s on douyin — and one of the three was a pure redirect.

## Browser options that were measured

The driver runs with `page_load_strategy='eager'` and image loading blocked unless a class sets
`needs_images = True`, because a crawler reads text and attributes, never pixels.

**Do not block image loading on douyin** (measured the wrong way first): the class sets no
`needs_images`, the base default blocks images for speed, and that is fine for every other platform —
but re-tested with the dialog handled, images-on vs images-off produced identical screens (22-24 vs
23-24 cards), so the earlier "blocking images breaks the grid" reading was the mask all along.
`Crawler.needs_images` exists for the case where a site really does need it; record the measurement
next to the flag.

**Blocking video was measured and rejected — do not add it.** Images are blocked by default
(`profile.managed_default_content_settings.images=2`), which is a real saving. Video has no such
preference, and the CDP entry point people reach for, `Page.setBlockedURLs`, **does not exist on
Chrome 148** (`unknown command`); the working one is `Network.setBlockedURLs`, verified to bite (a
player's `readyState` falls 4 → 0). It still buys nothing: our crawls never wait for a player
(`page_load_strategy='eager'`, we read DOM/JSON), so across all seven crawlable platforms A/B'd side by
side the blocked arm was equal-or-slower (douyin 22.7 s → 26.5 s, YouTube 9.5 → 11.9, X 19.3 → 20.5;
zhihu/weibo/bilibili/xiaohongshu flat) and **six of the seven download no media on the crawl path at
all** (`mediaBytes = 0`). Only douyin's per-video page touches a player, and there the page weighs
25.6 MB of which ~2% is media — the top resources are the site's own JS bundles (`player-4.js`,
`client-entry`), which a crawl needs. The one honest reason to ask again is metered traffic rather
than time: blocking saved ~0.6 MB per douyin video row and 0 bytes elsewhere. Probe:
`backend/test_media_ab.py` (payload `scratchpad/media_ab.json`).

## Crawl cost is a testable property

`Crawler.requests` counts every navigation and every in-page fetch **in order**. `open()` records the
URL *before* asking the driver, so a navigation that timed out still counts — it reached the site. Any
mode that promises "one request per page" must be pinned by asserting on that ledger
(`tests/live_site/test_live_bilibili_hot.py` asserts no `web-interface/view` call at all), because a
table alone cannot tell a batched walk from a per-row one.

## What each mode actually does on screen (measured 2026-09-24)

Why this section exists: the user ran `哔哩哔哩.json` in parallel + 窗口 mode with 「本次不用 Profile」
and saw **two** windows appear together (correct), but with 「用 Profile」 only **one** window at a time
(also correct, but never explained). Separately, the 热榜 window opens the homepage and then does
nothing visible while data arrives — the window demonstrates nothing at all. Both facts belong to the
mode, not to the platform, so they are recorded per mode here and the rule lives in AGENTS.md
("A visible window must be doing something visible").

Data path classes: **(a)** navigates and reads the DOM · **(d)** scrolls that page · **(b)** loads one
page then issues in-page `fetch` calls · **(c)** plain HTTP.

| platform × mode | path | what the user sees |
| --- | --- | --- |
| bilibili 关键词 | (a)(b) | search page re-loaded per `page=`, then numbers arrive silently (one `view` fetch per row) |
| bilibili **热榜/排行榜** | **(b)** | **the homepage, then nothing** — one navigation, `popular`/`ranking` fetched |
| bilibili 作者 | (a)(d)(b) | a real scrolling space page |
| bilibili 评论 | (b) | video page open and static (`/x/v2/reply/main` by cursor; there is no comment DOM) |
| zhihu 搜索 / 作者 / 评论 | (a)(d) | scrolling feed / profile; comments click 展开 |
| weibo 搜索 | (a)(d) | one search page per hourly window |
| weibo 评论 | **(b)** | the homepage only |
| xiaohongshu 搜索 / 评论 | (a)(d) | scrolling grid / scrolling comment panel |
| douyin 搜索 / 作者 | (a)(d) | a page per row (never headless: 验证码 on every headless navigation) |
| douyin 评论 | (a)(d) | scrolling route container |
| youtube 搜索 / 作者 / 评论 | **(b)** | one page load, then innertube POSTs — nothing visible moves |
| twitter/X 搜索 / 作者 / 评论 | (a)(d) | scrolling virtualized timeline (never headless) |
| wechat 正文 | (a)(d) | each article page, scrolled |

Consequences to honour when adding a mode:

* A **(b)** mode has no human behaviour to show. Running it in 窗口 mode is a pure cost: a window the
  user watches do nothing. The pre-run dialog must say so and offer headless — and the mode must
  declare which class it is, because the frontend may not hold a second opinion about a crawl.
* A mode where **both** paths exist (bilibili 关键词 reads DOM cards *and* fetches `view` per row) is
  the only kind that can honestly offer "simulate a human" vs "just take the JSON". Where only one
  implementation exists (bilibili 热榜 = API only), the choice must not be offered.
* **(b) still needs the page.** The fetch runs inside the loaded document for same-origin, cookie and
  risk-control reasons, so "headless" cannot mean "no browser" — it means "no window on your screen".

Parallel + the same platform is serialized by the profile lock, not by the pool: the second worker
blocks in `Crawler.__init__` → `acquire_profile()`, i.e. **before Chrome exists**, so only one window
is ever visible at a time; `crawl.profile_wait` states the wait, and 「本次不用 Profile」 lifts the lock
and gives one window per workflow (verified by the user).
