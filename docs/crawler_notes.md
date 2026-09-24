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
- [微博的墙是间歇风控，不是发车太近](#微博的墙是间歇风控不是发车太近measured-2026-09-24)
- [What each mode actually does on screen](#what-each-mode-actually-does-on-screen-measured-2026-09-24)
- [网络分区：国内与海外不能一起爬](#网络分区国内与海外不能一起爬用户实测-2026-09-24)
- [运行前 Cookie 预检](#运行前-cookie-预检measured-2026-09-24)
- [A login page on the way through is not a wall](#a-login-page-on-the-way-through-is-not-a-wall-measured-2026-09-24)

## Weibo

**Weibo serves a fake login wall**: a search first flashes the passport QR page, then bounces the
logged-in session back to the feed. Never judge the wall from the URL right after `get()` —
`WeiboCrawler._await_search_page` waits for a terminal state (cards / no-result plate / persistent
passport page). Keep that ordering in any refactor.

**The wall that parallel crawls meet on page 2 is the account, not the window (user-observed
2026-09-25).** A single crawl walks `page=2, 3, …` with no trouble; start two crawls of the same
saved cookie and each window's *deeper* requests start getting bounced to passport. Every window
holds its own copy of one `SUB`, so s.weibo.com sees one account firing several paging requests
inside a second — the same shape `crawl_gate.hold` exists to space, but that switch spaces crawl
*starts*, and paging rounds interleave long after any start gap. Nothing inside the crawler can
talk the site out of it; the answers are 真排队 for the platform, or separate accounts (task #117).

**The paging caps that used to live here were quitting below the user's target.** `MAX_PAGES_PER_WINDOW = 5`
made a feed whose own pager said 共50页 stop at page 5 with the target unmet and no line saying why;
`MAX_HOURLY_WINDOWS = 720` refused date ranges outright. Both deleted 2026-09-25 together with every
other backend round/page ceiling (bilibili 40, douyin 12, youtube 20, xhs 40, zhihu 30, twitter 40):
depth is the site's pager's answer, volume is the user's target, and a walk ends on target,
site-exhaustion, or a wall — never on a constant.

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

**A search card holds an excerpt, not the answer — and only a 回答 card may be opened**
(measured 2026-09-24, four probes in one logged-in session on `/search?q=三亚&type=content`).
The crawler used to refuse every click inside a card, on the strength of a navigation incident
that was never measured as a length question. It was wrong in both directions:

* the excerpt is **not** a CSS clamp. `.RichContent-inner .RichText` is a plain inline span
  (`display:inline`, `height:auto`, `overflow:visible`) whose `innerText` equalled its
  `textContent` at 35–109 characters. A wider read could not recover what the payload never
  carried, so every row this crawler stored was truncated, and the user's CSV said so.
* an answer card's `button.ContentItem-more` (label 阅读全文, **no href**) re-renders that same
  node in place: 74 → 308, 75 → 782, 69 → 1067, 71 → 2103 characters, and the answer's own page
  agreed (307 vs 308). URL unchanged, 21 cards still present, a handle to a card two rows down
  still alive, 8/8 clicks settled inside ~0.6 s. One node before, one node after — there is no
  second copy to double-count.
* a column card's control is the navigation the old rule remembered, so the gate is the row's own
  link (`/answer/`), not its class. A card whose anchor never mounted has an unknown kind and is
  not clicked either: refusing costs one excerpt, guessing costs the rest of the crawl.
* **expansion changes two other fields, which is why the row is frozen at its first reading.**
  The same click moves the date label off `.SearchItem-time` onto `.ContentItem-time`
  (`08-27` → `编辑于2026-08-27 12:22`) and drops the `作者名：` prefix the preview opens with.
  Re-scraping after the click would leave 发布时间 holding two formats across one column, decided
  by an internal retry, and empty 作者 on exactly the rows the fix improves. Only 正文 is replaced.
* the API route works and is not needed: `GET https://www.zhihu.com/api/v4/answers/<id>?include=content`
  answered `200` in 424 ms with `content` (1316 HTML chars → 674 plain, matching the page) and keys
  including `is_collapsed`, `content_need_truncated`, `force_login_when_click_read_more`. Two other
  shapes failed: `api.zhihu.com/responses/<id>` is CORS-refused from the page, and
  `api/v4/questions/<qid>/answers/<aid>` is `404`. A click is cheaper than a request and needs no
  second vocabulary of ids.
* cost and its bound: one settle wait per answer card (measured < 0.6 s, capped at 4 s). Three
  clicks in a row that answer nothing stops the trying for the rest of the crawl
  (`crawl.zhihu.expand_stopped`), because a site that stopped answering would otherwise be paid
  four seconds per row for two hundred rows. Turning 展开全文 off is the user's call and says so
  once on the console (`crawl.zhihu.excerpt_only`); rows that stayed excerpts while it was on are
  counted (`crawl.zhihu.bodies_short`).

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

**The profile header is not there when the session is being refused** (measured 2026-09-24, visible
window): `backend/test_douyin_profile_probe.py` was answered 验证码中间页 by the *search* itself, and
the live author case had been dying one step later with a raw
`NoSuchElementException: [data-e2e="user-info"]` — the tier's own helper read that node with a single
unwaited `find_element`. The fix is on the test side (bounded wait, absent header is simply no
anchor), and the identity claim no longer leans on the header at all: every row of the grid already
carries the name read off the video page it was opened from, so "one profile, two authors" is caught
from the rows, with the header nickname checked *against* that anchor when the page publishes one.
That file is green again (3 passed, 2026-09-24) — and the same sweep showed the pattern the next tier
change has to answer: **on both weibo and xiaohongshu it was the second case of the file — the
visible-window variant — that came back empty**, weibo still parked on passport after the tier's own
45-second back-off. A session that gets risk-scored stays scored for minutes, so the acceptance tier
cannot treat "rows" as the only honest green; it has to distinguish a *reported* refusal from a
silent empty table, and say per platform which one happened.

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

**Its search page answers late, and that used to be a crash rather than a state** (measured
2026-09-24, twice in one hour on `live_quick`, in two different variants): the crawl came back red
with `TimeoutException: Timed out receiving message from renderer: -0.001` thrown out of a bare
`self.driver.get(url)` — the *first* navigation of the search, and separately of a note page. Two
consequences, both pinned by `tests/unit/test_xhs_crawler.py`:

* the platform already had the honest answer for this state (`crawl.xhs.page_timeout` → keep
  polling, zero cards is a legitimate outcome) and never got to use it, because the exception came
  from the call before its own poll;
* the request really was issued, so dropping it from `Crawler.requests` on the way out would make
  the mode look cheaper than it is.

Fixed by entering both pages through `Crawler.open`, which also means **a slow page must not be
judged as a wall** — see the next section; the two changes only work together.

## A login page on the way through is not a wall (measured 2026-09-24)

`Crawler.open()` judged the wall on the *first* reading after `driver.get`, which is the moment a
single-page site is still mid-redirect. Weibo is the measured case (its own section documents the
passport flash and the bounce back), and believing the flash cost more than a wrong word: latching
`login_wall` stops the harvest loop, makes the run a 继续 candidate and tells the user to re-save a
cookie that is fine — while the crawl underneath it was working.

Now `open` → `_judge_arrival` re-reads the page and latches only a refusal that is **still there**.
The cost is deliberately asymmetric: a clean landing is answered on the first reading
(`test_a_healthy_landing_costs_one_reading` asserts exactly one, because a per-row detail crawl pays
this once per row), and only a suspected wall pays the ~1.2 s window. `verdict()` is the judgement
without the write, and `_record()` the write without the judgement — split because a re-read must be
possible before the one-way flag exists.

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

**A session preference written into a persistent profile stays there (measured 2026-09-24).** After one
weibo crawl, `data/chrome_profile/weibo/Default/Preferences` held
`profile.managed_default_content_settings = {"images": 2}` — and 4 of the 7 platform directories on this
machine carried it. That is what made 登录窗口 unusable: the Cookie panel's login browser runs on the
*same* profile a crawl used (`use_profile` follows the setting), and the fix that shipped first only
*omitted* the blocker for that window — omission is not an answer when the device already remembers a
"no", so the page opened with no QR code to scan and the user could not refresh a dead cookie. Two
consequences to keep: `_content_prefs` writes 1 (允许) or 2 (封锁) for **every** session, never nothing;
and any window a human is asked to read is a human-facing window — 取 Cookie and 验证 Cookie both, since
an expired cookie sends the probe to the login page and the panel then tells the user to sign in there.
`tests/integration/test_browser_profile_launch.py` measures the whole round trip, including the claim
above about the file on disk, so if Chrome ever stops persisting it the test says so by name.

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

## 微博的墙是间歇风控，不是发车太近（measured 2026-09-24）

`live_quick` 的国内组两次把微博搜索判红（0 行 + `登录墙`），而**同一条用例单独跑 5.7 秒就绿**。
排查走过的路与每一步的证据：

1. **不是 Cookie**：`cookie_preflight.probe(fresh=True)`（可见浏览器）对 weibo / zhihu 都回
   `valid`。注意这只回答「会话能不能打开内容页」，它回答不了搜索端点会不会被拒。
2. **不是无头**：`backend/test_headless_wall.py`（payload `scratchpad/headless_wall.json`）直接
   打开那条带时间窗的搜索 URL，无头有头**第一帧**就有卡片（微博 9 张 `.card-wrap`，知乎
   t=1 有 20 张 `.SearchResult-Card`）。
3. **第一个归因是错的**：失败的两组都刚好排在另一条微博采集后面，看起来完全就是「排队只去掉
   重叠、没去掉连发」，于是真给 `crawl_gate` 加了一段「释放时上冷却」的实现。**随后被证伪并
   整体回退**，留下的记录就是这一节。
4. **证伪的两组实验**（各 4~6 次，全部用真实 profile、真实账号）：
   - `backend/test_weibo_second_browser.py`：同一个浏览器连发两次搜索、关掉后**立刻**再开一个
     浏览器搜、再等 `WALL_RETRY_BACKOFF`(45 s) 开第三个浏览器搜 —— 6/6 全部返回数据；
   - `backend/test_weibo_windowed.py`：时间窗 URL 与普通关键词 URL 交替各 4 轮 —— 8/8 返回，
     其中 tier 用的那个 `2026-09-17-00→01` 窗口给了 6 张卡（第 4 轮只给 1 张，也是数据）。
   当天微博累计 14 次采集，无一被拒。

**结论**：那堵墙与发车间隔无关，是站点间歇风控（目测单次拒绝率在一到两成）。所以
`crawl_gate` **不加冷却**——为一条测不存在的规律让串行画布多等，是给成本找了个假理由。
（2026-09-25 的并行深翻页观察与这一节同向：撞的仍是「账号短时连发」这条风控，只不过触发点
在各自 crawl 的**翻页请求互相重叠**上，不在 crawl 的**起步**上——起步间隔正是本节证明没用的那个
变量。见上文 Weibo 一节。）

真机层的应对因此只有两条，且都不降低断言：撞墙重试从 2 次提到 **3 次**，并且每次重试等待
产品自己用的 `Config.WALL_RETRY_BACKOFF`（以前是测试层自己发明的 5 秒，产品路径里根本没有这个
数）。断言仍然要求「真出数据」，只是不再因为一次风控抖动就把爬虫判坏——单次 ~15% 的拒绝率下，
两次都拒的概率约 2%，三次都拒才说明采集器真的坏了。

知乎那次 0 行是同一晚的另一件事：它没撞墙也没报错，只是页面外壳空着落到滚动循环里（代码里写明
这是无头风控的合法结局）。重跑同一条用例即通过（20 张卡），所以是当日节流，不是解析器坏了。

**把 `crawl_gate.hold` 搬进 `live_crawler` fixture 的同一批改动，也让真机层自己撞死过一次**
（measured 2026-09-24）。三条用例在同一条测试里向同一个平台要**第二个**浏览器——
`test_live_zhihu_author.py`（先搜一条现取作者 token，再开作者页）、
`test_live_bilibili_hot.py`（两张榜单各一个 crawler）、`test_live_cookie_expiry.py`
（第一次爬到墙、换新 crawler 续跑）——而第一把锁要等 fixture 结束才释放。
锁不可重入，于是第二次 `hold` 原地等 `Config.PLATFORM_GATE_TIMEOUT` = **900 秒**：
没有浏览器弹出来、没有输出、没有任何一行字说明它在等谁——看上去就是"这条真机用例特别慢"。
判据：单跑 `test_live_zhihu_author.py` 15 分钟无输出且 `chromedriver.exe` 不在进程表里
（浏览器根本没启动，说明卡在拿锁而不是卡在页面）。修法是 fixture 在向同一平台要第二个
crawler 之前先把上一个关掉并交还这一轮（一次只可能有一个，这正是产品自己的规则），
并由 `tests/unit/test_test_tiers.py::TestLiveCrawlerFixture` 用"重复持锁即抛"的假锁把这条
钉住——它不需要浏览器，测的是测试自己的脚手架。

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

## 网络分区：国内与海外不能一起爬（用户实测 2026-09-24）

**挂 VPN 时抖音回 502 拒绝访问；不挂时 x.com / YouTube 根本打不开。** 一台机器一次只能在那两条网络
之一里，所以一张同时包含两边的画布从任何一侧跑都必定缺掉一半——而缺的那一半看起来跟"这次搜索什么都没
搜到"完全一样，这是它最难自证的一种失败。落在代码里的三件事：

* 分区是**数据**，不是散落的判断：`crawl_capabilities.Capability.region`（`cn` / `overseas`）由矩阵
  一处声明，随 `/api/capabilities` 发给浏览器；运行前的「国内与海外混采时提醒」和真机层的
  `live_cn` / `live_os` 分组都读它。`tests/unit/test_test_tiers.py` 会拿矩阵里的 region 去核对每条
  live 用例的 marker，所以给一个海外平台忘了写 `region` 会被测试层直接指出来（矩阵没说的平台按
  "不知道"处理：既不提醒也不拦）。
* 提醒是**建议**且可关（`warn_mixed_region`）：真做了分流路由的机器两边都通，页面分不出那种机器和
  "只是开着 VPN"，所以它只问不禁。
* 真机测试必须分两次跑，中间由用户确认网络状态；抖音那条红在 VPN 状态下不是爬虫坏了。

## 运行前 Cookie 预检（measured 2026-09-24）

`cookie_preflight` answers 「这份会话还认不认」 before a run starts, by loading the platform's own
`login_url` once. What was measured while building it:

* **The first smoke check ran headless and it over-claimed.** With the zhihu profile reset that
  morning, a *headless* probe of `www.zhihu.com` came back 「被重定向到登录页」 — which is a true fact
  about that anonymous session but not necessarily about the user's. This file already records the
  same trap for 验证 Cookie (this machine answers a headless content page differently, Zhihu in
  particular), so the probe now uses the same two choices that worker does: `headless=False` and
  `for_login=True`. Consequence: the panel's 验证 button and the pre-run gate can never disagree
  about one platform, and a visible window per uncached platform is the price of the guarantee.
* **Cost, measured:** one probe ≈ 4–5 s of real Chrome (the `live_site` tier runs three of them in
  ~14 s). Hence `COOKIE_PREFLIGHT_TTL=300` (a parallel canvas and the 继续 behind it pay once),
  `COOKIE_PREFLIGHT_MAX_PARALLEL=4` and the outer `COOKIE_PREFLIGHT_TIMEOUT=45` budget.
* **A busy profile is not waited on.** The probe would otherwise block inside `Crawler.__init__` →
  `acquire_profile()`, whose own timeout (`PROFILE_LOCK_TIMEOUT=900`) outlasts most crawls, so
  `browser_profiles.is_busy()` answers 「无法核对」 at the door instead.
* **"No cookie file" is not "no session".** A profile imports the file **once** and is never
  re-planted, so a used profile can hold a live login with no snapshot beside it — which is exactly
  the state the new 删除已存 Cookie button leaves behind. The gate therefore probes whenever either
  source exists, and only answers the blocking `nocookie` when neither does.
