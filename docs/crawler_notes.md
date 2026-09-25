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
- [网络分区：海外平台要走外网](#网络分区海外平台要走外网混采必缺一半已被实测否掉用户实测-2026-09-242026-09-26-修正)
- [运行前 Cookie 预检](#运行前-cookie-预检measured-2026-09-24)
- [A login page on the way through is not a wall](#a-login-page-on-the-way-through-is-not-a-wall-measured-2026-09-24)
- [热榜：问过五个平台、上线四块、证无一块](#热榜问过五个平台上线四块证无一块measured-2026-09-25)
- [「停止」为什么必须去杀进程](#停止为什么必须去杀进程quit--stoprequest--kill-三选实测measured-2026-09-25131)
- [停止路径的真机时间戳](#停止路径的真机时间戳measured-2026-09-25133)
- [页面没加载完不是被拦截](#页面没加载完不是被拦截measured-2026-09-25135)

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
talk the site out of it. **Shipped rule:** the matrix marks weibo `serial_only`, so its crawls take
真排队 whatever the 排队/错峰 switch says, and a parallel canvas with 2+ weibo crawls is warned by a
pre-run dialog before it pays for the collision. The only way back to true weibo parallelism is
separate accounts, each with its own session (task #117).

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
* **Measured 2026-09-25 (same recipe, a long row found on page 1): `text_raw` is the COMPLETE body.**
  An `isLongText=true` row carried `text_raw` of 43 chars and `statuses/show?id=<idstr>` answered 200
  with the *same* 43 chars (`text` was the 354-char HTML) — so the author crawl reads 正文 from
  `text_raw` and needs **no per-row detail fetch**. Truncation was the open question; it is closed:
  this list does not truncate.
* `topic_struct` is `[{topic_url, title}]` with `title` empty and the `#话题名#` inside
  `topic_url`'s `q=%23…%23` — so 话题 is parsed from the URL, not the (empty) title, matching the
  search mode's anchor-derived `#…#`.
* rows have **`pic_num` + `pic_ids[]` but NO `pics[]`**: the image count is available, the image URLs
  are not on the row, so 图片数 is filled and 图片链接 is left empty rather than built from a guessed
  CDN pattern. `page_info` may be non-null (`type=11`), but video/album counts do not come from the
  search mode's `.media-video-a` DOM here — 视频数 is not fabricated.
* the row's `user.id == uid` anchor is confirmed on real author rows (`user.idstr` mirrors it); link the
  row as the search mode does (`weibo.com/detail/<mid>`), the identity field is the numeric `mid`/`id`.
  Reading counts from JSON is cheaper and steadier than the DOM walk the search mode uses, so a profile
  crawl must not copy the card scraper.

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

**A detail page that publishes only its counter bar is not a row (measured 2026-09-26, live).** One
opened video answered 点赞 300 / 评论 11 and nothing else — no author, no 发布时间, no 文案, and
`document.title` still empty. `_detail_row` filed it as valid data, so a 2-row target was met by two
blank lines and the live tier caught it as "row without a title". It now refuses a page with
**neither author nor publish time** (`crawl.dy.detailNoIdentity`, one line naming the id) and the walk
moves on to the next card, so the budget buys rows that say something. **The gate is identity, not
prose**: a caption-less clip keeps its author and its date, so it stays a row with an empty 正文 —
refusing on an empty 标题 would drop real data over one column.

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

## 网络分区：海外平台要走外网；"混采必缺一半"已被实测否掉（用户实测 2026-09-24，2026-09-26 修正）

**不挂 VPN 时 x.com / YouTube 根本打不开。** 这条仍然成立，也是界面上唯一值得问的一句：画布里出现
海外平台，运行前问「外网开了吗」（`ask_overseas_network`，默认开；答"还没开"那次就不启动，因为空表
会被读成"这个关键词什么都没搜到"）。这一问排在 Cookie 预检之前 —— 预检要按平台开浏览器，一次注定
被取消的运行不该付那份钱。

**被否掉的那半：「挂 VPN 时抖音回 502，所以一张画布不能同时含国内与海外」。** 2026-09-24 那次只被
观察过一次，却被我写成了平台规律，还据此做了一个"列出两边、建议拆成两次"的弹窗。2026-09-26 用户
的怀疑（是不是 Cookie 签发的 IP 与访问的 IP 不一致才被风控）把这件事一次测清 —— 探针
`backend/test_douyin_region_probe.py`（一次性；只记 IP、行数与判定，绝不记 Cookie 值）拿同一份
**国内签发的会话**跑了三次：

| 时刻 | 出口 | 结果 |
|---|---|---|
| 06:4x | `183.205.131.79`（中国 河南 郑州 移动） | rows=2 verdict=ok |
| 07:04 | 同上（VPN 尚未接管这台机器的流量） | rows=2 verdict=ok |
| 07:1x | **`134.195.101.194`（海外出口；requests 与浏览器两处读到同一个）** | **rows=3 verdict=ok，零登录墙、零风控** |

三条结论：
* **"会话绑 IP"不成立**（用户自己的假设被自己的实验否掉）：国内签发的抖音会话从海外出口照样交出真行
  （标题/作者/发布时间/点赞都齐）。
* **"抖音只在国服应答"也不成立**：至少这个海外节点完全正常。抖音的 502 因此降级为**特定出口/节点或
  时段的现象**，不再作为任何分区依据；下次再见到 502，先用那个探针读出口，再猜原因。
* 于是"混采弹窗"整个删掉，不留残余：`regionGroupsOf` → `overseasPlatformsOf`（只回答"哪些平台要外网"），
  设置键 `warn_mixed_region` → `ask_overseas_network`，两套语言里那三条解释文字一并删除，
  `Capability.region` 的注释改成它真正的含义：**标的是内容与账号属于哪一边，不是哪条路能不能通**。

留在代码里的两件事没变：
* 分区仍是**数据**：`crawl_capabilities.Capability.region`（`cn` / `overseas`）由矩阵一处声明，随
  `/api/capabilities` 发给浏览器；真机层的 `live_cn` / `live_os` 分组读它，
  `tests/unit/test_test_tiers.py` 拿矩阵里的 region 核对每条 live 用例的 marker（矩阵没说的平台按
  "不知道"处理：既不提醒也不拦）。
* 提醒是**建议且可关**：真做了分流路由的机器两边都通，页面分不出那种机器和"只是开着 VPN"。

顺带量到的一条（与网络无关）：一次性浏览器里 **10 个视频页只渲染出计数条**（作者与发布时间都没出），
被 identity 门槛丢掉不计行 —— throwaway 会话的 hydration 明显比 profile 会话慢，另案处理。


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

## 真站层 2026-09-25：拒绝必须被命名，静默空表才是红（measured）

删掉全部采集上限（ab0bb04）与错峰语义（ed007f0）后的第一轮 `live_site AND live_cn` 全量：
8 红 / 33 绿（9 分 28 秒）。逐条单独复跑后定性如下——**没有一条是这两个提交弄坏的**：深翻页走到了
pager 自报页底，排队交棒无恙。红条分三类：

1. **同账号连发的间歇风控（只在批量出现，隔离即绿）**：bilibili 详情与 douyin 作者两条在批量里红、
   单独跑绿。微博侧同一会话第 1 次搜索（windowed，交付 8 行）成功、第 2、3 次（expiry attempt-1、
   visible）被弹回 passport——与 2026-09-24 那节「微博的墙是间歇风控」同形，也与 `weibo_windowed`
   记录过的「第二次爆发拿到 passport 页」逐字吻合。
2. **测试口径落后于产品契约（确定性红）**：`cookie_preflight` 渲染句的断言查的是裸 key `bilibili`
   或「平台」二字，而 Phase C 之后产品按红线把 `{platform}` 槽答成**词**（「哔哩哔哩 的 Cookie 可用」）。
   断言改为经 `i18n.platform_label` 解析期望值——不再是贴进来的副本。
3. **真产品缺陷两枚（都在 xhs 的「静默空表」上）**：`backend/test_xhs_visible_gate.py` 一次可见
   探针量到底——被风控的小红书有两种形态都会**不点名地**交回空表：(a) 风控页把搜索 URL 原地留着、
   只渲染「安全验证」，`classify` 答 `blocked`，但 `xiaohongshu.py` 的收口闸只测
   `check_login_wall`（即 `verdict == 'login'`），`risk_blocked` 已置、循环却继续滚 0 卡网格；
   (b) 更糟：被限流的可见窗口 `driver.get` 根本没换文档，地址栏停在 `chrome://new-tab-page/`
   （body 是「新标签页/应用商店/自定义 Chrome」），分类器看不到任何墙词判 `ok`。站点无法重定向进
   内部协议页——停在这里**本身就是导航失败**。已修两处：搜索闸改判 `check_intercept(url) != 'ok'`
   （与 zhihu/douyin 的 `login_wall or risk_blocked` 同规则）；`engine/wall.classify` 最先回答
   `never_arrived`（`chrome://`/`about:` 等自家协议页 = blocked）。fast 层三个反向测试钉住
   （风控页早退且不写 page_timeout；stuck 窗口点名拒绝；空 URL 仍按死会话规则答 ok，不误伤）。

由此固化的层契约（AGENTS.md「live_site 重试」条的展开）：**被点名（login 或 blocked）的空是站点的
诚实答案，用例断言点名本身即绿；没点名的空是伪成功，永远红**。`live_search` 现在通过 `_Rows`
（list 子类）把 `login_wall`/`risk_blocked` 两面旗随结果带回，调用方才有资格做这个区分。微博可见
窗口用例额外要求「同会话的 headless 采集确实交付过行」才允许接受拒绝——两头都空是死会话，该红，
并直接告诉用户去重存 Cookie。

配套口径修正（同轮）：被墙拦住的采集把 `done:0` 写进游标是合法记账（游标记位置不记内容），expiry
用例的拒绝分支只许断言「行表为空且 done==0」，不得断言游标缺席；bilibili 详情与 weibo expiry 各获得
一次「换新浏览器、隔 `WALL_RETRY_BACKOFF` 再问」的层内容忍，与 `live_search` 的既有政策同构。

## 窗口模式的真实语义：评论可按平台无头、chip 说真话（measured 2026-09-25，#102）

`_execute_comment_node` 过去对**所有**平台写死 `headless=False`，声称「评论一律开可见窗口」。
`backend/test_headless_comments.py`（一次性探针，国内网络，真实 Cookie）量出这不是事实：

* **微博评论**：无头浏览器先搜到 5 行、取一条 评论数>5 的推文，`CommentSession.crawl_weibo(limit=15)`
  → `status=ok`、15 行、15 个 (作者,内容) 全不同；爬虫两面旗都没立（会话是活的）。
* **B 站评论**：对分层测试用的那条已知视频 `crawl_bilibili(limit=40)` → `status=ok`、40 行、40 个去重键，
  地址栏停在视频页（`?vd_source=` 说明页面真加载了，不是被弹走）。

也就是说这两家的评论区是**页内 fetch**（AGENTS 分类表的 (b) 类），开着的窗口只会停在首页什么都不动。
据此把「怎么采集」从散文变成代码：

* `Mode.collects ∈ {fetch, dom_read, dom_scroll, page_per_row}`，每个模式的值按 `docs` 分类表 + 上面实测
  逐条标注；`capabilities.shows_nothing(platform, mode)` 是唯一答复「可见窗口有没有东西可看」。
* 评论建浏览器改判 `_comment_headless(run_headless, kind)` = 用户选择 ∧ `shows_nothing` ∧ ¬`never_headless`；
  于是微博/B站/YouTube 评论尊重无头，知乎/小红书（真滚动）与抖音/X（`never_headless`）仍强制可见窗口。
* 被强制开窗口时置 `runs.forced_visible=1`（`start_run` 的 ON CONFLICT 会把它复位，续跑不背旧值），
  面板 chip 于是能读真话：请求无头却开过窗口 → 「无头→窗口」，不再顶着「无头」骗人。
* 面板文案按 `collects` 分流：fetch 评论模式用新键 `settings.commentFetchHint`（不再声称开窗口），
  滚动/验证码平台仍用 `settings.commentHint`；fetch 源模式（B 站热榜、YouTube 搜索/作者）用
  `settings.fetchQuietNote`。`tests/unit/test_crawl_capabilities.py` 钉住「note 只说它真会做的事」。

## 那条「受自动测试软件的控制」横幅：excludeSwitches 认的是开关名（measured 2026-09-25，#129）

用户问：驱动开出来的 Chrome 都写着"正受到自动测试软件的控制"，平台会不会识别，我们要不要伪装。

量过的答案分三层：

* **横幅本身页面读不到**——它是浏览器自己的外壳（窗口标题条上那一条），不在 DOM 里；
  页面能读到的自动化痕迹是 `navigator.webdriver`、`cdc_adoQpoasnfa76pfcZLmcfl_*` 全局键、
  以及 HeadlessChrome 的 UA。本项目 `navigator.webdriver` 已经是 False（`--disable-blink-features=
  AutomationControlled` 的效果）。
* **横幅的直接原因是 chromedriver 自己往 Chrome 命令行加的 `--enable-automation`**，去掉它的
  正规手段是 `excludeSwitches`——但它匹配的是**生成的开关名**，写错名字不会报错、只是什么都不排除。
  本项目从写下那天起就是 `'automation'`（真名 `enable-automation`），所以每个可见窗口都带着横幅。
* **伪装不是决定性的**：同一晚、同一台机器、同一套 `cdc_*` 表面上，一个会话被挡回登录墙而
  另一个把 51 条数据交了回来；抖音那条风控滑块也在用户手工通过后立刻可爬。因此这次只修拼写，
  不做 UA 伪造、不清 `cdc_*`、不碰验证码——那是把"我们可能被识别"换成"我们确定在违反条款"。

浏览器侧的自证在 `tests/integration/test_driver_surface.py`：读 `chrome://version` 的命令行
（标签是本地化的，开关串不是），一次断言 `--enable-automation` **不在**，另一次把
`excludeSwitches` 摘掉重开、断言它**在**——没有后者，前一句只是"这页什么都没读到"。

## 热榜：问过五个平台、上线四块、证无一块（measured 2026-09-25）

#83 的四个平台逐个问过真站，没有一个是照着"看起来合理的 URL"写的。探针都在
`backend/test_*_hot*.py`（一次性脚本，gitignore），载荷在 `scratchpad/*_hot*.json`。

### 微博热搜：已上线，且是唯一不需要登录态的采集

`https://weibo.com/ajax/side/hotSearch`，在已加载的 `weibo.com` 文档里用
`credentials:'include'` 读（`pagefetch.fetch_json`）。实测：

* `ok:1`，榜单在 `data.realtime`，**51–52 行**，每行带 `word` / `word_scheme` / `note` /
  `num` / `realpos` / `rank` / `topic_flag` / `label_name` / `emoticon`；
* `num` 是**精确整数**（1003085），不是 DOM 表上的 万 标签 —— 这是选 JSON 而不选
  `s.weibo.com/top/summary` 的第二个理由；
* 连打两次计数一致，所以"一次回答就是整块榜"不是猜的；
* **三种会话都答**：插 Cookie 的一次性浏览器、平台 profile、**完全无 Cookie**（匿名会话
  同样 `ok:1`）。这条决定了矩阵新增的 `Mode.needs_session`：Cookie 预检是按**平台**问的，
  如果只看平台，一个只挂「微博热搜」节点的画布会因为没 Cookie 被拒 —— 而站点本来就把榜单
  给了匿名浏览器。所以现在只有 `('weibo','hot')` 是 `needs_session=False`，
  `test_only_the_measured_board_answers_an_anonymous_browser` 钉住"恰好这一个"，
  多一个就是需要重新测量的主张；
* 备用路径（已实测、未使用）：`https://s.weibo.com/top/summary` 的 DOM 表在三种会话下也
  都出表（每行 3 格：序号 / 关键词 / 热度，行链是 `/weibo?q=<词>&t=31&band_rank=N`）。
  没用它是因为它把热度写成 万 标签，并且要先判"路过型 passport 闪现"。
* **一条热搜不一定是 #话题#**：真站跑出来 `word_scheme == word`（例：`让家更有AI`）的行
  确实存在。所以 话题 列存的是站点自己的串，链接按那一串去搜索 ——
  把它统一改写成 `#…#` 会搜出一个榜单上并不存在的话题。
  （这条是**真站测试替我抓到的**：断言"必须以 # 开头"在第一轮 live_cn 就红了。）

### 知乎热榜：已上线，一块只有 30 行、且所有游标都被无视的榜

`https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50`，同样页内 fetch。实测：

* 恰好 **30 行**，`paging.is_end=true`、`next=""`、`totals=0`；
* `limit=100` / `offset=30` / `page=2` / 猜的 cursor **都返回同一批 30 个 id**（重叠 30/30）
  —— 所以这里没有翻页循环，写了就是拿风控的钱重放同一张表；`target_count` 大于 30 时
  日志明说"榜单只有这么多"，不填充也不空转；
* **无 Cookie 直接被拒**：`401 AuthenticationError`，而且首页本身就跳 `/signin`，
  所以 `login_wall` 在问接口之前就已经成立 —— 那时一次请求都不该发出去（有单测钉住）；
* 有 Cookie 时**无头与窗口给出同一个答案**（今天两种都 200/30 行）；
* 行的形状里有**两个字段不能成为列**：`target.author.name` 在 30/30 行都是字面量「用户」，
  `target.comment_count` 在 30/30 行都是 0。把它们写进表就是造两列假数据（同抖音没有
  播放数列的理由）。`answer_count` / `follower_count` 30/30 有值，所以留下；
* `target.url` 给的是 `https://api.zhihu.com/questions/<id>` —— 那不是能打开的页面，
  必须重写成 `https://www.zhihu.com/question/<id>`；
* 热度在 `detail_text`，形如 `398 万热度`，走 `engine.counters.parse_count` 展开成整数。

### 抖音热榜：**已上线**，因为那两个没答完的问题今天答完了

2026-09-25 重探（探针 `backend/test_douyin_hot_probe.py` / `test_douyin_hot_signed2.py` /
`test_douyin_hot_static.py`，载荷 `scratchpad/douyin_hot_*.json`）。当初拦住的正是当年列出的
那两条，如今各有各的实测：

1. **自拼 URL 到底答不答**：答。钩子这次存完整 URL（不再截断到 300 字符），拿到页面自己那一条
   之后，用**只由公开字面量拼出的** URL 在同一个已加载文档里问四组参数：

   | 参数集 | 行数 | 带 hot_value | 带 view_count |
   |---|---|---|---|
   | 21 个公开参数（无 webid） | 51 | 51 | 51 |
   | 再去掉 downlink/effective_type/round_trip_time（18 个） | 51 | 51 | 51 |
   | 上面 21 个 + 一个**假** `webid` | 51 | 51 | 51 |
   | 只留 6 个（device_platform/aid/channel/detail_list/source） | 47~48 | 48 | **0** |

   同一个 URL 连打四次，计数次次一致。结论两头都清楚：**签名一个都不需要**（假 `webid` 不改结果，
   所以爬虫不必去抄页面的请求，也不必新增"抓页内请求 URL"这套机制）；而那批公开参数是**承重的**，
   退到 6 个就丢掉整列 `view_count` 并少掉几行。`HOT_API` 里写下的就是中间那 18 个。
2. **会话**：本工具自己的抖音 profile 仍被答 `验证码中间页`，插 Cookie 的一次性浏览器能读到榜
   （用户手工过的滑块在他的 Chrome 里，那是第三个 profile 目录）。所以矩阵里 `needs_session=True`，
   live 用例显式 `use_profile=False`。

一次回答就是整块榜：不翻页（`len(fetched) == 1` 被离线用例钉住）、不逐条打开话题页 —— 榜自己就带着
`hot_value` / `view_count` / `video_count` / `discuss_video_count` / `event_time`。

行的取值也有据：`word` 在这张榜上**既是标题也是话题**（抖音不像微博另发一个 `#…#` 串），所以**不做**
`话题` 列 —— 一列重复另一列的文字是用户会当成数据的噪声；`position` 是站点自己的名次；链接用榜单
DOM 锚点自己那形状 `https://www.douyin.com/hot/<sentence_id>/<词>`（四条真实 href 与同一次回答里的
`sentence_id` 一一对上，所以这不是猜的）。

**榜首那一行是 0 还是没数**：两种都在同一天出现过 —— 一次是 `position: null, hot_value: 0,
view_count: 0`，另一次同样位置是 `null`。所以这一列的规则是"站点没给的留空"，不给 0：0 在这张榜上
是一个真实的读数，填出来的 0 与读到的 0 分不开。`_published()` 就是为此存在，
`test_a_figure_the_site_did_not_publish_stays_blank_rather_than_becoming_zero` 钉住它。

判墙那一条仍然成立，而且现在被离线用例直接钉住：`验证码中间页` 这种标题下
**通用的 `check_intercept()` 说 `ok`**，而抖音自己的 `_wait_for_page()` 说 `captcha`、
`_is_walled()` 说 `True`。抖音的墙只能由抖音的判定来读；而读到墙时**一次请求都不该发出去**
（`test_the_captcha_interstitial_refuses_before_the_endpoint_is_asked`）。

### 小红书热榜：**证无**，不是"暂时没测到"

三条独立的墙，任何一条都足以不做：

* 没有榜单页面：`https://www.xiaohongshu.com/hot` 重定向回 `/explore?source=4`，就是普通
  信息流；
* 页面上唯一和"热"有关的请求是 `edith.xiaohongshu.com/api/sns/web/v1/search/trending/query`
  —— 那是搜索框的**提示词**接口，不是榜；而且它在页内重放时返回 **406**（同域也拒），
  连提示词都拿不出来；
* 更根本的：从**同一张页面现取**的 `xsec_token` 拼出的笔记链接，打开仍落到
  `/404?source=/404/sec_...`。这与 #82 放弃作者模式是同一堵墙，因此"榜单行打不开"不是
  实现细节，而是这个平台对网页端的整体态度。

`'hot' not in mode_keys_for('xiaohongshu')` 被 `test_each_platform_names_its_modes` 钉住 ——
想加必须先重新测量，不能让它在没人注意时"顺手补上"。同一条测试今天也收了抖音的 `hot`：
它当初的断言写的就是"抖音的榜还没 settle"，等测量把两个问题答完（上面那两条）才换成
`('posts','author','hot','comments')`。少一块榜是红，凭空多一块榜也是红。

## 「停止」为什么必须去杀进程：quit / stopRequest / kill 三选实测（measured 2026-09-25，#131）

用户的说法是："中止之后运行记录刷新慢得不如重开服务"。这句里有两个不同的问题，必须分开量：
**记录什么时候不再说「运行中」**，以及**上一个任务什么时候真的停了**。

探针 `backend/test_stop_latency.py`（一次性脚本，载荷 `scratchpad/stop_latency.json`）用真
Chrome 148 各测两种"卡在页面里"：一个 40 秒才答复的导航（正好是 `page_load_timeout` 的默认值），
以及一个永远不调用回调的 `execute_async_script`（页内 fetch 的形状，30 秒脚本超时）。 worker
线程卡在里面，主线程按三种方式去"停止"它：

| 停止方式 | 卡在导航 | 卡在页内 fetch | worker 最后怎么死的 |
|---|---|---|---|
| 侧线程 `driver.quit()` | **40.02 s** | **30.02 s** | 自己的超时，不是被停 |
| 第二条连接 POST `…/chromium/stopRequest` | 40.01 s | — | 同上，而且端点 **404 unknown command** |
| `taskkill /F /T` 该会话的 chromedriver | **2.25 s** | **2.25 s** | `ConnectionResetError`（socket 被断） |

结论三条，都已写进代码：

* **跨线程 `driver.quit()` 对"正在跑的命令"完全无效**——它是会话内的有序请求，排在 worker 那条
  之后；旧实现把 3 秒宽限给完，就以为自己在关浏览器，实际只是在等 worker 自己超时。
* **`stopRequest` 这个"温柔中断"在 chromedriver 148 上已经不存在**（Selenium 4.45 也没有包装），
  所以别指望它：唯一可靠的打断是让驱动进程消失。
* 因此 `STOP_QUIT_GRACE = 0.8`：给一个本来空闲的浏览器体面退出的机会（顺带把 Cookie 落盘），
  到点就按 PID 杀树；多个浏览器各一条线程并行收，否则并行运行的最后一条抓取要排在前面所有
  清理之后，而记录必须等它们全结束。

至于"抓取自己该不该继续"，以前**没有任何一处**问过：`crawlers/**` 里 `stop`/`cancel` 出现 0 次，
`feed.walk_feed(stopped=…)` / `pager.walk_pages(alive=…)` 这两个钩子只接了 `login_wall`。现在
问题问在 `Crawler.emit`（全站唯一过行口）以及那两处共享走查的谓词里，`CrawlerStopped` 故意继承
`BaseException`——`crawlers/` 里约 60 处 `except Exception` 是"读不到就接着走"的容错，一次停止
被它们咽下就等于悄悄少采，而没人看得见少了什么。

## 停止路径的真机时间戳（measured 2026-09-25，#133）

#131 的三个结论来自"假爬虫 + 单元断言"，以及一段卡在页面里的**手工**测量。这一轮换成真的：
真服务（`backend/test_stop_real.py`，隔离到 `scratchpad/stop_real_data`，端口从 5058 往上找
真正没人答复的那个）、真 B 站搜索、真 Ollama，并且**由页面自己的「执行」「停止」按钮**发起——
这样被测的就是出厂代码，而不是替它写好的替身。载荷 `scratchpad/stop_real.json`。

按停止的**那一刻**为零。首屏那一档跑了三次，中途那一档两次（**这张表是修复前的**；
"被杀后仍向死驱动发命令"那一条已由 #134 修掉，修复后同一探针的重测就在下面几段）：

| 场景 | 记录不再说「运行中」 | 界面那一行自己换字 | worker 定档 | 界面读到定档 |
|---|---|---|---|---|
| 卡在首屏导航（0 行，3 次） | 0.009 / 0.007 / 0.006 s | 0.38 / 0.42 / 0.50 s | 5.77 / 4.80 / 5.28 s | 6.15 / 5.12 / 5.63 s |
| 走查中途（已收 38 条，2 次） | 0.006 / 0.005 s | 0.45 / 0.19 s | 29.64 / 28.66 s | 30.09 / 29.03 s |

三列各自的读法：记录那一列是**服务端事实**（停止请求自己写下 `stopping`），界面那一列是**用户真正在看的**
——面板没人点，`pollStatus → autoRefresh` 自己把「运行中」换成「正在停止」，最后换成「已中断」；
定档那一列才是 worker 的退出。两次中途运行的换字差一倍（0.45 / 0.19 秒），量的其实是**上一次
`pollStatus` 落在哪**（每 2 秒一拍），不是换字本身有多快——上限就是一拍，这一列别当成毫秒级承诺。

**中途那 29.6 s 是新的、#131 没量到的**。当时的猜测是"驱动进程被杀之后 worker 还在往它发命令，
每条约 4 秒"，并把它记为后续；#134 用 `backend/test_dead_driver.py`（真 Chrome + `file://`，
四个变体，载荷 `scratchpad/dead_driver.json`）把猜测量开，四条数字把做法直接定了下来：

| 一条命令花多久 | 秒 | 为什么 |
|---|---|---|
| 被杀那一刻**正在执行**的那条 | 1.72（其中 1.5 s 是探针自己按下去前的等待） | 驱动进程没了 → 连接被 RST；**已经写出去的请求不再重发** |
| 之后每一条（老 driver 对象） | 16.3 | 全新一次 connect 打在没人监听的端口上；Selenium 建池时不传 `retries`，于是拿到 urllib3 默认 `Retry(total=3)`——4 次 × ~4.07 s，connect 失败永远允许重试 |
| 之后每一条（把已建好的 `pool.retries` 归零） | 4.07 | 只剩一次尝试，但每条仍要 4 秒 |
| 之后每一条（换成死驱动桩） | 0.00 | 根本不打开 socket |

三条推论，都改变了做法：**(1)** in-flight 那条不用管，杀进程本身就解了它；被拖长的全是**后面的**
命令——所以"强杀成功后把 `crawler.driver` 换成一个立即抛 `CrawlerStopped` 的桩"就够了。
**(2)** 归零重试严格更差（4.07 s/条 vs 0.00 s/条），于是 urllib3 一处都不动，`requirements.txt`
也因此不加包。**(3)** 关掉/清空连接池（`command_executor.close()`）是唯一"看着该做而实测不该做"
的选项：它不仅不救 in-flight（那条本来就 1.7 s），还让之后的命令回到 16.3 s——`clear()` 之后
新池带着默认 `Retry(3)` 重建。

桩有两处形状是必需的，不是风格：`quit()`/`close()` 必须**静默**（worker 自己的 `finally` 会调
`Crawler.close()`，从收尾里抛 `BaseException` 会把这次抓取的结论换成一段栈回溯）；而 `close()`
清 `self.driver` 必须**比较之后再清**——worker 回来的路正好是被杀的那一秒，`quit()` 恰恰是因为
进程没了才返回，此时若无条件写 `None`，下一条命令拿到的是 `None.<cmd>` 的 `AttributeError`：
一个普通 `Exception`，会被 60 处容错折成"这一页没有更多了"，正是 `CrawlerStopped` 存在要防的那句话。
另有一条反作用力：`_close_login_browser` 会再被 worker 的 `finally` 问第二次，而从死桩上读
`driver.service.process.pid` 抛的是 `CrawlerStopped`，`contextlib.suppress(Exception)` 拦不住它，
那个线程会死在去**下一个**浏览器的路上——所以重入必须在入口就返回，且返回时**不**替它放 profile 锁。

**端到端重测（Cookie 恢复之后，`backend/test_stop_real.py --skip-llm`，载荷
`scratchpad/stop_real.json`；修复前那一版留在 `scratchpad/stop_real_pre134.json`）**：
仍以按停止那一刻为零，首屏与中途各一次——

| 场景 | 记录离开「运行中」 | 界面自己换字 | worker 定档 | 同一档修复前 |
|---|---|---|---|---|
| 卡在首屏导航 | 0.009 s | 0.512 s | **5.30 s** | 4.80~5.77 s |
| 走查中途 | 0.007 s | 0.19 s | **4.35 s** | 28.66~29.64 s |

首屏那一档没动，正是机制预测的样子：那里 in-flight 只有一条命令，本来就被杀解掉了。
被 16.3 s/条拖长的是**走查**这种"一条之后还有好几条"的位置，从约 29 秒落到 4.35 秒；
剩下的 4.35 秒大头仍是那条 in-flight（1.7 s）加上 worker 自己收尾的账（游标、结论、行统计）。
（这一档中间曾经量不了：`workflow.js:576` 的界面校验对 `needs_session` 的平台没有 Cookie 就直接
拒绝，与 `cookie_preflight_before_run` 无关，而那晚 Cookie 文件被测试套件删掉了——见下一节。）


模型那一头量到两件事：

* 停止时 worker 正卡在一次**真的**模型请求里，记录定档花了 **14.6 s / 15.2 s**（两次独立）。
  这就是"停止打断不了 in-flight 读"的实测代价，行循环在下一行边界才听见停止。
* 把守护进程换成"接了连接但不答复"（`HangingDaemon`）后，测出 **本轮真正修掉的 bug**：
  `app.py` 给 ollama 传 `timeout=300`，而这条传输走的是 `ollama.Client(host=...)`——
  ollama-python 把这个参数原样交给 httpx，`None` 在 httpx 里是**永不做超时**，不是"用它的默认"。
  直接量：配 20 秒的客户端，70 秒后仍卡在同一个连接上。修法是 `Client(host=base, timeout=self.timeout)`，
  离线复现见 `TestSilentDaemon`（1 秒超时 → 1 秒返回；回退修复 → 20 秒仍在阻塞）。
  修完之后的天花板变成可算的：`300 s × 2 次尝试 = 600 s`（实测 600.27 s，记录定档为
  `interrupted`、节点 `partial`）。**没有**改成"停止后不再重试"，因为
  `test_one_blip_still_retries_and_answers` 明确钉着"一次抖动该被重试"，那是#131 有意的决定。
* 面板追看记录默认 240×500 ms = 120 s，比上面这个 600 s 短——所以它会在记录早已定档之后
  把「正在停止」留在屏幕上。现在 `tries` 由 `SETTLE_WATCH_MS`（660 s）除以**实际**步长导出，
  `harness_runsmgr.mjs` 用一个"400 次都不定档"的答复钉住它。

还有两条只在真机上才会撞到的：

* 探针第一次跑挂了，因为页面自己的校验拒绝了一个**没有下游**的数据源节点（「必须连接到下游节点」
  + 「至少需要一个输出（保存）或可视化节点」），而 `execute()` 的每个提前退出都只变成一句 toast
  或一个对话框——服务端日志里什么都没有。第二次的错来自 `position: fixed`：`#toast` 就算显示着，
  `offsetParent` 也是 `null`，可见性要问 class（`show` / `open`）。
* 被外力杀掉的探针进程会把**抓取用的 Chrome 留在活着的进程表里**（9 个进程还占着 profile），
  并且它继承了监听套接字：端口显示 LISTENING、谁连都不答复，新服务用 `allow_reuse_address`
  照样 bind 成功——于是"端口空闲"这个检查必须用一次真请求来问。

## 页面没加载完 ≠ 被拦截：慢网络曾被写成站点的错（measured 2026-09-25，#135）

真站层 `test_visible_search_resolves_each_video` 红过一次，用户盯着窗口看到的原因是
**视频页迟迟没加载出来（网络差）**，而不是抖音拒了他。代码里这件事一直没被分开：
`Crawler.open()` 本来就知道答案——`driver.get` 抛异常时它记 `timed_out` 并作为返回值交出去
（X 的 `crawl.x.loadSlow` 就是这么用的）——但抖音两个调用点**把这个返回值丢掉了**：
`search()` 走 `_open_results()` 拿不到它，于是落到 `crawl.dy.noCards`，那句写的是
「只可能是被拦截、页面出错」并让用户去重存 Cookie；`get_detail()` 同理只会说
"详情页没有渲染出数据"。也就是说一次网络抖动被报告成站点级拒绝，方向完全相反。

本轮先做的半措施：`Crawler.navigation_settled` 记下最近一次导航是否走完（抖音的详情路径
仍取返回值，因为它中间的 `check_login_wall` 会再导航一次，存下来的事实会变质），
`crawl.dy.noCardsSlow` / `crawl.dy.detailSlow` 只在**没有检测到任何墙**时出现，
旧句子收窄到"导航确实完成了却还是零卡片"这一种（那才是实测过的 502 / 验证码页）。
测试用 `load_timeout` 的假驱动分别钉住两条句子的分界：慢加载那一句**不许**再出现
「只可能是」这种排他断言。

#135 要把口径做全：可证的"肯定拿不到"只有 链接/区域不通、没登录、被风控 三类，检测不到这三类
就**不许因加载慢而报错退出**——继续等，并在控制台说明"没有依据判断拿不到"，是否中止交给用户。
区域不通（国内 ↔ 海外）能否判出来、怎么测，由调查工作流给结论后再动代码。

### 2026-09-26 落地：四件事，以及被数字否掉的两件事

**先量的是什么形状。** `backend/test_arrival_evidence.py`（Chrome 148，本地 HTTP 服务 +
几个必失败的地址）今天重跑一遍，三种"浏览器自己拒绝"的形状给出的**是同一份文档**：

| 失败形状 | `current_url` | `documentURI` = `location.href` | `readyState` | 导航 `responseStatus` | title | body 里的机器码 |
|---|---|---|---|---|---|---|
| 域名解析不了 | 被请求的 http 地址 | `chrome-error://chromewebdata` | complete | 0 | 裸主机名 | `ERR_NAME_NOT_RESOLVED` |
| 端口被拒（:1） | 同上 | 同上 | complete | 0 | `127.0.0.1` | `ERR_UNSAFE_PORT` |
| 黑洞地址（超时） | 同上 | 同上 | complete | 0 | 裸 IP | `ERR_CONNECTION_TIMED_OUT` |

三条都重要，且都不是"想当然"的那一版：

1. **`driver.current_url` 报的是被请求的地址，不是屏幕上的文档**——所以 `unreachable`
   只能从 `document.documentURI` 读出来，`Crawler._document_uri()` 就是为这一条存在的；
2. **机器码在页面正文里没有 `net::` 前缀**（前缀只出现在 chromedriver 抛出的异常消息里）。
   一开始按 `net::([A-Z]…)` 写，三个真形状一个都没抓到——测试红过一次才改成都量到的 `ERR_…`；
3. **渲染超时留下的是上一份文档**（`documentURI` 仍是刚才那个好页面、`readyState` complete、
   title 也是旧的）。所以"文档地址对不上"不能当"没到达"的证据，`navigation_settled` 才是；
   反过来，一份 `chrome-error` 文档**不会**由超时制造出来，两者不会互相冒充。

**被数字否掉的两件事**（都量了才放弃）：

* 原计划把 `unreachable` 也送进 5×0.3 s 的"墙要再看一眼"窗口。量下来没必要：那 4 次重读
  每次三条命令，而一份已提交的错误文档不会自己变好。`_judge_arrival` 现在对
  `ok` 与 `unreachable` 都在第一次读到时收尾（测试用假驱动的读页次数钉住：`< WALL_PROOFS`）。
* 原计划"每拍都重新判墙"。改成每 5 拍一次 + **第 0 拍就判**（因为 `open()` 已经判过一次，
  一份拒绝在等待开始时就看得见）；实测代价是每次等待多 1 条命令，换来"可证的死掉"不再
  需要 5 拍才被发现。

**分层超时的边界今天定死了**：`Config.PAGE_WAIT_TIMEOUT = 300` 只管**一页的首屏内容**
（`Crawler.wait_for_first_content`），滚动/翻页"还有没有新行"的 14/12/3 s 一律不动。
理由不是怕慢，是**语义**：把进度判据拉长，"这一页采完了"就会被读成"还在加载"，抓取会永远滚下去。
抖音作者模式是个现成的对照：页面自己报了 作品数 = 0 时，首屏显然已经到了，
等待只剩"网格会不会补上"——那一档继续用原来的 45 s（`video.py` 里 `timeout=` 传下去）。

**熔断放在哪里**：计数器挂在 crawler 实例上（`pending_waits`），并且**只在真的看过页面一次之后**
才拒绝第三次。原因是一次实测反驳了最初的写法：如果在进入循环前就查计数，一条恰好连着两次失败的
走查会把**后面每一行**都判死——哪怕下一个页面完全正常。现在的顺序是"先看一眼 → 没内容 →
才问这是不是第三次"。

**被拒绝的捷径**：`_is_collision`（撞车后退避重试一次）**没有**把 `unreachable` 算进去。
那个函数的证据是"我们自己的两条走查同时到门口"，退避 45 s 能解；而 DNS 解析不了、区域不通
都不是撞车，退避只会把一条诚实的拒绝线推迟 45 秒。要救它的是换网/停止，不是再等。

**文案**：一次拒绝只剩一行。爬虫负责它看得见的（等了多久、哪一页、浏览器自己写的话），
执行器负责它看不见的（对照主机 + 一次 2 s 测速 + 下一步），节点名由 `wf.node_failed` 加。
`net.slow` 这一句被要求**不许**指出原因——两侧都通却什么都没拿到，能说的只有"没有依据"。

## 参数只有"被读懂"和"被点名拒绝"两种下场：静默降级实测清单（audited 2026-09-25，#132）


这一轮把"用户选了 A、系统做了 B"的整类问题一次查清。方法：把每个 select/开关参数从**面板写入**
一路读到**真正改变行为的那一句比较**，再问"如果一个不在列表上的值走到这里，会发生什么"。
答案是绝大多数情况**什么都不发生**——因为每个读它的地方只特判自己认识的那一个值：

| 位置 | 比较 | 未知值的下场 | 用户看到什么 |
|---|---|---|---|
| `crawlers/video.py:343`（B 站热榜） | `== 'ranking'` | 走热门榜 | 选了排行榜、拿回热门榜，记录里写着用户"选"的那个 |
| `app.py` 三处 + `part_writer.py` | `== 'json'` | 写 CSV（扩展名也 CSV） | 要 JSON 拿到 CSV |
| `analyzers/keyword.py:45` | `== 'tfidf'` else textrank | 跑 TextRank，并把 `method` 列写成用户请求的名字 | 表里声称 TF-IDF，实际是共现图 |
| `analyzers/emotion.py:130` / `tendency.py:148` | `== 'ml'` else LLM | **走 LLM 逐行** | 拼错 `ML` 就白付一整轮模型调用 |
| `analyzers/ner.py:179` | `== 'llm'` else regex | 走规则 | 节点写着大模型，实体是正则抽的 |
| `services/data_analysis.py` `convert_type` | else 分支 | `astype(str)` | 要 int 拿到文本，节点照 done |
| `services/data_analysis.py` `fill_null` | 字典查不到 | 用字面值填充 | `method='mean'` 把单词 mean 写进每个空格 |
| `data_analysis` 各处 `if column not in df.columns: return df` | — | 整步跳过 | **过滤没生效却绿色**，导出的是没过滤的表 |
| `drop_null`/`fill_null`/`drop_duplicates` 的列清单 | `[c for c in columns if c in df.columns] or None` | 名单全落空 → 子集为空 → **当成所有列** | 打错一个列名，`任一为空` 删掉远超目标的行 |

布尔的两种写法同样会翻车，而且方向相反：

* `params.get('ascending', 'true') == 'true'`：JSON 里的真布尔 `True != 'true'` → **升序变降序**；
* `bool(raw)`（`Field.value_from` 的 bool 分支）与 `bool(params.get(key))`：面板的复选框历史上写的是
  文本 `'false'`，而 `bool('false')` 是 **True** → 不勾选＝勾选。落到 `recrawl` 上就是"没点重新采集
  却释放了台账"，把已经付过钱的条目再爬一遍；落到 `full_body`/`with_facts`/`keep_parts` 上就是白等
  或白留文件。

因此规则收敛成一句话：**选数据、选花费、选名字的参数，只能"被读懂"或"被点名拒绝"**。落点是四个，
不是四十个 `if`：

1. `capabilities.unoffered_selections(mode, params)` + `engine.source_bad_option` —— 矩阵里声明过的
   `select`（现在只有 `board` 与 `format`）值不在 options 内就拒绝；**空值不是错误**（"没选过"，
   按声明默认跑），这一点与 `requested_mode_key` 对未知 mode 的处理完全一致；面板不会写坏值，所以
   这条路只挡手写/外部生成的 JSON 与被下架的旧选项。平台"这个模式根本没这个字段"不算错（切平台
   不会删掉旧 key，拒绝它等于砸用户保存过的工作流）。
2. `data_analysis.normalize_step_params` → `validate_step`，装在 `run_pipeline` 里——分析节点与
   `/api/analysis/run` **两道门都只经过这一处**，所以两条门现在读同一份参数（以前 steps 门把
   `'名称, 城市'` 当成 7 个字符的列名迭代，整步静默无效）。
3. `app.enum_param(op, params, key)` + `PROCESS_ENUMS`（`参数 → (默认值, 允许写法)`）—— 处理节点的
   `mode`/`method`/`cluster_method`/`corr_method`；关键是**被检查的那串字符就是递给分析器的那串**，
   所以测试直接断言分析器收到的值（`test_the_value_the_gate_judges_is_the_value_the_analyzer_is_handed`）。
4. `utils.helpers.as_bool(value, default)` —— 开关一律"读"，不比较。空白／听不懂的写法回答**默认值**
   （面板在那一格显示的数字），因为它不是"另一个答案"。`services/data_analysis._to_bool` 是另一件事：
   它读**抓来的单元格**，那里"不是假即真"是对的，用在参数上就会把清空的一格读成"关"。

`keyword.py` 的 `method` 列现在写 `wanted`（解析后真跑的那个名字），不再写用户送进来的拼写——账本
上"哪种算法产出了这行"必须是事实。

两处**故意保留**的宽松：词云配色（`WORDCLOUD_STYLES.get(name, vibrant)`）与 `merge_frames` 的
`mode`（它把自己的 `used_mode` 回给调用者）。前者是装饰参数，为一个配色丢掉整张图更糟；后者已经
诚实报告了自己用了哪种。两者都不是"选数据/选花费"的参数。

界面这一侧同步改了三处，都是"同一件事只说一次"的反面：

* **画出来的值和存下来的值不是一回事**：`renderParamSelect`/`sourceSelectHtml` 过去用
  `(p[key] || def) === o.v` 判选中——值不在列表里时**没有一个 option 被选中**，浏览器于是显示
  第 0 项（热门榜 / TF-IDF / ECharts），而参数里写的还是那个要被拒绝的值。现在
  `selectOptionTags` 把节点真正持有的值作为一个"不是可选项"的 option 显示出来（原文经
  escapeHtml，因为它是用户自己写进文件的文字）。
* **复选框显示读的是 truthy**：`p.x ? 'checked' : ''` 对文本 `'false'` 为真，于是用户取消勾选、
  重新打开面板却看到勾上，而运行按"关"执行（或相反）。统一成 `boolParam(value, 默认)`，与后端
  `as_bool` 同一套词表；`renderParamCheckbox` 也改成像其它复选框一样写 `this.checked`。
* **await 之前抓的 DOM，await 之后可能已经不在页面上**：`runsManager.detail`、
  `renderResumeSettings`、`dashboard._renderCell` 三处都是"先拿到行/容器，再 `await fetch`，
  然后往里写"。运行中的时候控制台每 2 秒刷一次运行列表，`openSettings` 在任何一次参数改动时
  重写整个表单，`dashboard.open()` 清空重建网格——所以那三次写入经常落进一个已经脱离文档的子树：
  屏幕上什么都没出现，而 `_detail` / `_instances` 这类记账照样被写下（`_detail` 一写，面板就
  以为用户在读明细，自动刷新停了；`echarts.init` 在离页元素上建出的实例每次 resize 都被重画、
  永不 dispose）。现在都是"等回来再按 id/属性重新找一次，找不到就什么都不写"。

顺带记录几条被从 AGENTS.md 移出来的旧事实（那边有 32 KB 硬预算，规则留在那儿，事故留在这儿）：
`_pushState` 曾经让自动保存吃掉 50 步历史栈、把真实编辑挤出去；`DOMContentLoaded` 里一个裸调用
曾经因为 ECharts CDN 拿不到而连带跳过能力拉取、自动保存和续跑横幅——这就是 `boot(name, fn)` 与
"`_pushState` 跳过相等状态"两条规则的来历；`canvas._isTypingTarget()` 存在，是因为旧的按键守卫
只认 `INPUT`/`SELECT`、漏了 `TEXTAREA`，于是粘贴长链接后按退格删掉的是**选中的节点**。
同样搬过来的还有 `_push_log` 那一条：一次多行载荷（驱动报错的 `Message:` 块）曾被当成"一条日志"
存下，于是浏览器按行做的增量游标要么跳过、要么重复真实的控制台内容——现在按**物理行**存，运行
总数也按行走，而不是按 `add_log` 的调用数。参数别名那一条也记在这儿：节点参数曾经被历史快照
直接引用活对象，结果任何参数改动都撤销不掉，后续修改还会改写历史里已经存下的旧条目。

AGENTS.md 压缩（2026-09-25）时又搬来几条事故，规则本身留在原处：数据集重命名那次，对话框的
确认按钮带着自己的 `value: 'ok'`，于是用户输入的文件名被按钮记号顶掉、存成了字面量 `ok`；
app.js 为了拖拽把 `openCookieDialog` 又包了一层，包装函数的空参数列表让面板开在**上一次选中的**
平台上，而不是刚刚拒绝你的那一个；`tests/integration/test_ui_layout.py` 里 `.panel` 这个选择器
在本项目**一个元素都匹配不到**（面板各有 id），所以它按 id 逐容器审、绝不回落 `<body>`；
"改工作流名"那次事故是——名字进了节点指纹，而父指纹喂子指纹，于是重命名一次，续跑就重爬重付
整条链上已经采到的条目；节点 id 同时是框的 **DOM id**，一个 `id: "status-zoom"` 的工作流文件
让 `deleteNode` 与撤销路径把**状态栏本身**删掉了；profile 侧的机制是 chromedriver 会预写
`<user-data-dir>/Default/Preferences`，同一目录同一瞬间起来的两个会话不可能都起来，而"配置文件
只在第一次使用时导入一次"这件事由目录里的 `.crawler-profile.json` 标记；`MAX(seq)+1` 那条的
代价是曾经的 `COUNT(*)` 按**每一行**跑一次，于是一次长抓取在自己的表上平方级地慢下去。

## 测试套件两次写进用户目录：第二次之后，把它改成做不到的事（measured 2026-09-25 与 09-26，#134）

**这是同类事故的第二次。** 第一次的记录是 AGENTS 里那条"UI 层不许写服务器，把 `fetch` 打桩"——
那次是自启的服务把运行与上传落进了真 `data/`、`logs/`。第二次就是本节这一行：

新加的 `tests/integration/test_stop_reaper.py` 在文件顶部写了 `from app import _close_login_browser`。
就这一行，让那次 `pytest -q` 把**假 Cookie 写进了用户真正的 `data/cookies/`**，并且把里面原有的
条目删掉了。机制是一串各自合理、合起来致命的规定：

* `pytest.ini` 的 `addopts` 用 marker 过滤掉的只是**执行**，collection 仍然 `import` 了 `tests/` 下
  每一个 `.py`；被 deselect 的文件照样在导入时跑顶层代码；
* `tests/conftest.py::data_root` 是 session + autouse 的**fixture**，它在第一个测试体之前跑，
  但 fixtures 一律晚于 collection；
* `app.py` 顶层就有 `cookie_manager = CookieManager(Config.COOKIE_DIR)`——**导入那一刻**把目录字符串
  存进单例，之后 `setattr(Config, 'COOKIE_DIR', tmp)` 改不到它；
* 于是 `tests/api/test_config_api.py`（它自己顶层没有任何危险 import，靠 fixture 拿 `app_module`）
  在 `app` 已被我的文件提前导入的那次运行里，往真目录存了 `weibo_cookies.json` /
  `zhihu_cookies.json`（内容 `[{'name':'SUB','value':'x'}]`），而 `test_cookie_delete` 那类用例的
  delete 也打在真目录上。

症状不是崩溃，是**45 个断言在别的时间点也过、只有整轮跑才红**（各模块单跑全绿，因为它们没有提前
导入 `app`）。第一层修法是把新文件改成用 `app_module` fixture（`import app` 因此发生在隔离之后），
再在 `tests/unit/test_test_tiers.py` 里用 AST 静态拒绝任何测试文件的**模块级** `app` 导入。

但这层修法把安全性寄托在"每个人都记得用 fixture"上，而这条规矩本轮已经被违反两次（第一次是
`integration` UI 层往真 `data/`、`logs/` 里落运行痕迹，那次写进 AGENTS 的是"本层不许写服务器，
把 `fetch` 打桩"）。所以真正的修法是**把时序问题解决掉**：

* `tests/conftest.py::_isolate_paths()` 现在在 **conftest 被导入的那一刻**执行，先于 collection
  导入任何测试文件；`data_root` 只负责把那个根目录报给用例，不再负责搬路径——于是"隔离根"与
  单例冻结的路径**不可能不一致**，无论谁在什么时候 import 什么；
* 它同时写下环境变量 `CRAWLER_DATA_ROOT`（`backend/config.py`），所以**子进程**里自启的那台服务
  也用自己的状态目录。这一条不是猜想：新加的看门狗第一次跑设备层就抓到 `logs/app.log`、
  `logs/_ui_layout_server.log` 与 `data/{runs,datasets}.db-wal/-shm` 在动——UI 层自己拉起的服务
  用的正是真 `data/`，而它一旦启动还会把用户正在跑的那次运行判为已中断；
* `tests/isolation_guard.py` 在 conftest 导入时给 `data/`+`logs/` 拍一张指纹（路径、大小、mtime），
  会话结束时比一遍：**只要有一个字节变了就把这轮判红**，并点名是哪些文件。判定逻辑放在这个模块里
  而不是放在 conftest 里，是因为 pytest 会导入本树四个 `conftest.py`，`sys.modules['conftest']`
  属于最后被收集的那一个——写在 conftest 里的判据，测试根本导不到（实测：单独跑绿、整轮跑红）。
  Chrome profile 的子树不逐文件走（每个目录几万文件），但目录本身与其顶层的标记文件在比较之列，
  因为那正是"爬虫没接到重定向"会留下痕迹的地方；只读不动 mtime，所以真站层读你的 Cookie 不会误报。

留在这里的原因：这条不违反就会毁掉用户数据的规矩，长得完全不像错误。写它的反面教材是
`tests/api/test_config_api.py::test_save_persists_into_the_isolated_cookie_dir`——它断言的是
"保存到隔离根"，而它自己那次失败的方式，是**保存成功、日志也说了 saved、文件落在用户目录里**。
看门狗自己也被真机证明过一次：一个临时用例往 `data/_guard_probe.json` 写四个字节，那轮
`1 passed` 仍然以非零码退出并点名了那个文件。

## 停止剩下的三条尾巴：返回的抓取、快照里的 driver、没有 pid 的卡死（#136 / #138 / #139，2026-09-26）

三条都在 #134 的审计里被记下来，今天一起收。**先说被量掉的那半条**：#136 的原始描述里写着
"`engine/feed.py` 卡片读取失败被吞 → 卡片恒空 → `_wait_for_change` 每轮只睡 1.5 秒 → 死循环"。
逐行读下来不是死循环：`read_cards()` 抛异常会被吞成 `[]`，而 `walk_feed` 在**每一轮开头**就对
空卡片 break（`stopped_reason='no_cards'`），所以最坏是 `stuck_rounds × settle_wait`（默认 3 × 1.5
≈ 4.5 秒，X 用 4.0 时约 12 秒）。据此**没有**给走查加"连续 N 轮读不到卡片"的上限——那条会误伤
骨架屏（抖音 16 张空壳正是"有卡片容器、零张卡"的形状），买到的只是一个已经被 break 覆盖的场景。

真剩下的是**结局词**：抓取 honor 停止的方式是**返回**它已经采到的行，不是抛异常。而
`_execute_source_node` 只在**进入节点前**查一次 `stop_requested()`（`_execute_node` 里那条
`if stop_requested(): raise CrawlerStopped`），返回之后没人再问；`_run_node_durable` 的两条
`except` 都要求**有人抛出**。于是一次被停止的走查会：节点 settle `done` → 运行记录写「运行完成」
→ 续跑横幅不给「继续」。回退验证拿到的就是这个字面断言：

```
>       assert _node_row(record, 'node-1')['status'] == NODE_PARTIAL
E       AssertionError: assert 'done' == 'partial'
```

评论节点同样：它的 URL 循环在顶上 `if not execution_state['running']: break`，跳出之后照样
`return rows_out`。两处各补一次"回来了也要问一句"，走既有 `_settle_node_as_stopped`
（保留行、记 被停止、不计入 failed）。评论那处刻意放在 `writer.finish()` **之后**，
`comment.done` 那行随之不再打印——被停止的运行由 `run.nodeStopped` 一个人说。

**#138**：`CommentSession` 存的是 `crawler.driver` 的**对象快照**，`app.py` 传进去就切断了
和 crawler 属性的联系；强杀时换成 `DeadDriver` 的是 crawler 身上的名字，评论引擎手里那个
老对象还活着，于是每条命令继续付 16.3 秒（#134 实测）。改法是把 crawler 交给 session
（`owner=`），`driver` 变成**每次现读**的属性——30 处 `self.driver.<cmd>` 一行没动，但都变活了。
没有 owner 的老构造方式（live 层直接从浏览器建 session）行为不变，这条由一条反向用例钉住。

**#139**：强杀分支的条件是 `waiter.is_alive() and pid`，而 `pid` 那次读被 `suppress(Exception)`
包着——读不到 pid 的卡死会话因此**既没被杀也没人再问**（`/api/workflow/stop` 取完快照就
`clear()`），而释放 profile 锁的正是那个永不返回的 `close()`，本平台目录被占到
`PROFILE_LOCK_TIMEOUT`。没有加"留在注册表里下次再试"的机制：那需要一个第二持有者和一个能
展示它的界面位置，而这里能确定说的只有一句——**它可能还开着**。于是 `run.browserStuck`
进控制台（说占多久、为什么），`_stuck_where()` 把卡住那一帧进 `logs/`。用 `logger.debug`
而不是 `warning`：`LogBufferHandler` 会把 INFO 及以上的 logger 调用转发进控制台，英文帧地址
走 `t()` 没有意义，而 `tests/unit/test_i18n.py::TestNoHardcodedConsoleText` 正是靠"debug 只进
文件"这条豁免的——第一次写成 warning 时它就是被这个用例挡下来的。

**顺带量到的一个平台事实**（写下来是因为它会骗测试）：这台机器上 `time.monotonic()` 的
步进约 16 毫秒——`time.sleep(0.005)` 之后再读，返回值**一模一样**。任何"用真实时钟测一个
小于 16 毫秒的量"的断言都是掷硬币，`services/net_probe.throughput` 的算术就因此需要注入
时钟（`tests/unit/test_net_probe.py::_clock`）才能钉住 kB/s 的算法本身。

## 种进 profile 的 Cookie，只有带有效期的那部分留得住（measured 2026-09-26，#108）

「重取的 Cookie 进不了正在用的 profile」这个洞补上之后，真机量了一次**它到底能补多少**：
在本地 HTTP 服务上（Cookie 的 domain 必须和文档主机对得上，`127.0.0.1` 是唯一能自己服务的选项），
用 `Crawler._plant()` 种一个 Cookie → 关掉浏览器 → 用**同一个 profile 目录**再开一个 → 读回来。

| 种进去的 Cookie | 同一个浏览器里看得见 | 关掉再开还看得见 |
|---|---|---|
| 没有 `expiry`（会话 Cookie） | 看得见 | **看不见**（jar 是空的） |
| 带 `expiry`（持久 Cookie） | 看得见 | 看得见 |

Chrome 只把**持久 Cookie** 写进 profile 的 Cookie 库，会话 Cookie 只在内存里。这条决定三件事：

1. 「把 Cookie 更新进 Profile」的答案必须**同时报两个数**：种进去几条、其中几条关掉窗口就没了
   （`cookie.refresh.sessionOnly`）。只说「已更新」就是许了一个下次重启会破的承诺；
2. 「profile 拥有自己的会话」的准确形式是 **profile 拥有它那份持久 Cookie 与其它站点状态**，
   不是"站点认为我登录了的那一切"。站点若只发会话 Cookie，profile 也留不住；
3. 本机已存的几份文件里，绝大多数条目是带 `expiry` 的（各平台从 7/8 到 57/63 不等），
   所以这个按钮对真实登录态有效，不是只对测试有效——但"绝大多数"不等于全部，提醒照旧要出。

`expiry` 有两种拼法：driver 报回来的是 `expiry`（epoch 秒），浏览器自己导出的是
`expirationDate`。`CookieManager._has_expiry` 两种都认；只认一种会把持久 Cookie 误报成要丢的那种。
`Crawler._cookie_payload` 早就做了同样的兼容（它把 float 的 expiry 取整，否则 `add_cookie` 整条拒绝）。

测量脚本已经变成测试：`tests/integration/test_profile_cookie_plant.py`（真 Chrome，4 条，27 秒），
其中一条**专门钉住那个坏消息**（会话 Cookie 不留在 profile 里）——哪天有人以为"种下去当然会留着"，
那条会红，面板那句提醒也就同时失去依据。

**为什么种 Cookie 只能让浏览器自己干**：Chrome 的 Cookie 库在 Windows 上是应用绑定加密的
（本轮试图从用户日常 Chrome 直接读 Cookie 时实测：66 条目标 Cookie 全是 `v20`，用户态进程解不开，
复制出来的库交给 Chrome 自己也解不开），所以"外部写那个 sqlite"这条路不存在——唯一能写进去的
途径是开着浏览器用 `add_cookie`。这也是这个功能必须开一次浏览器的原因。

## 微博作者模式的「发现」步骤，付的是第三次 burst（measured 2026-09-26，收口第 1 轮）

收口第 1 轮（`-m "not live_os"`，1027.22 秒，4213 passed）唯一的红是
`tests/live_site/test_live_weibo_author.py` 的 `_discover_uid`：它自己起一个浏览器去搜
`人工智能`，被答了 `登录墙：weibo.com … 重定向到登录页`，取回 0 条，然后那句
`assert rows` 把它读成"搜索坏了"。**同一次运行里** `test_live_weibo.py` 的两条都是绿的
（共享的 7 天窗口搜索交出 8 行、可见窗口那条按契约过了），所以会话是活的——这是本文更早那一节
量的同一个形状：**这个账号的下一条 burst 被答 passport 页**，不是死登录态。

于是发现步骤改成读**这一轮已经付过的那一次搜索**（`weibo_windowed`，session 作用域，
`tests/live_site/conftest.py` 里就是为"一个账号被 burst 拒"而存在的），不再另起第三次 burst。
断言的强度一点没降：行必须存在（不存在就是死会话，红），必须有一条带数字 uid 的 `用户链接`
（没有就 `pytest.fail` 把看到的链接全打出来，红）。`live_search` 那条"撞墙就退避后再问一次"的
路子在这里解决不了问题：**重试只是把同一个被拒的端点再问一遍**，多花的正是账号的额度。

顺带量到 today 的另一半：单跑那条用例时日志停在 `开始采集作者 <uid> 的作品，目标 5 条`，
既没有 WARNING 也没有 `authorDone` → 走的是 `crawl.weibo.authorRefused`（mymblog 那一格
`fetch_failed`）分支。用例按自己的契约把"被点名的拒绝"当作站点的诚实回答放它过，这与
`weibo: /ajax/statuses/mymblog is a per-session edge 403 → refuse loudly` 那条红线一致。
作者模式真取到行的证据由离线用例（`_author_row` 的列集合、翻页游标、mirror 拒绝）与
2026-09-23 那轮全量绿提供；真站这一格"能不能取到行"取决于该 session 当日的心情，
所以这条用例才故意在 `live_quick` 之外。

## 真站层每轮都在新浏览器里重放同一份 Cookie（measured 2026-09-26，#140）

微博那条"发现步骤付第三次 burst"只是表面。**结构原因**在这里：`tests/conftest.py:73-102` 为了隔离，
在导入时把 data/、logs/、settings.json 指向 `<tmp>/cixi_pytest/isolated-<pid>`，而且**开头先
rmtree 再新建**。pid 每轮不同 ⇒ 每一轮真站层都从一个**全新空 profile** 起步 ⇒
`crawlers/__init__.py:97` 的 `planting` 条件每轮成立 ⇒ **每轮都把同一份保存的 Cookie 重放进一个新浏览器**。
日志原文可查：`Cookie 预置：weibo.com 接受 8/8 条`。

对照用户自己的抓取：`data/chrome_profile/weibo/.crawler-profile.json` 写着
`used_at 2026-09-26 00:29 / imported_at 2026-09-24` —— profile 已被用过 ⇒ **他的抓取根本不种 Cookie**，
用的是站点自己发给它的那份 jar。这解释了一个原本说不通的现象：**测试反复被弹登录页，而用户
一次都没见过**。而微博的风控记在**账号**上，不是记在浏览器上，所以测试的重放最终把用户自己的
抓取也弹下了登录页（2026-09-26 05:2x 实测发生；他重新登录 + 重存 Cookie 后恢复）。
`crawl_gate.hold` 对此无能为力：它只管顺序，release 之后没有任何冷却
（`crawl_gate.py:230-235` 只给"到门口确实等过"的调用补那一段抖动间隔）。

落地四件：
1. 真站层改用**跨运行保留**的 profile 根 `scratchpad/live_profiles/<platform>`（gitignored，
   且显式拒绝落在 `data/` 里——那是用户自己的目录），首轮种一次、之后与用户同形；
2. 只在**面板那道问句**为真时再种：`refresh_for_planting(platform)` 直接问
   `browser_profiles.needs_refresh(platform, 该平台的 Cookie 文件)`，也就是"种过、之后文件又被保存过"。
   于是用户重存 Cookie 之后测试会话会跟上一次，别的任何时候都不动它；
3. **微博每轮只问一次**：`live_attempts('weibo') == 1`（`live_search` 与 `weibo_windowed` 都读它）。
   重试对微博不是"再试一次"，是拿同一份被拒凭据再敲一次同一扇门；拒绝被当作拒绝来断言
   （`test_visible_window_search_works_too`），严格度一点没降；
4. 真站层的 `pytest.skip` 变成**必须被列举**（`_LIVE_SKIP_ALLOWANCE`，正反两方向都有测试），
   防止"跑不过就跳过"悄悄吃掉闸门。

被数字或事实否掉的三个选项：**给 hold 加冷却**——产品路径从来没有这个承诺，测试自己加会把
真问题（会话形状）盖住，而且每轮多睡几十秒；**把微博降级成只测匿名热搜**——丢掉的是登录态抓取
这一整块覆盖；**每轮删掉测试 profile**——等于回到原点。

**真机复验做到了一半（06:06 与 06:12 两轮）**：
- **结构那一半已经证到**：第二轮的日志里**没有再出现 `Cookie 预置：weibo.com 接受 8/8 条`** —— 持久根
  里 `scratchpad/live_profiles/weibo/.crawler-profile.json` 记着 `imported_at 06:06:38` 与
  `cookie_stamp`，第二轮 `is_used` 为真、`needs_refresh` 为假，于是**没有重放**。这正是修的东西。
- **被拒那一半还没轮到**：第二轮两次搜索仍被答 `登录墙 → passport`（0 条）。原因不是形状了，是
  **账号被今晚前面那几轮刷出了标记**：06:06 那一轮（第一次种）微博交了 8 行、7 条 quick 用例全绿，
  六分钟后同一路径就被拒。所以"真机不再被弹登录页"这句只能在标记过期之后再验（几小时到一天），
  而每敲一次都在花账号的额度 —— 复验之前不再碰微博。
- 顺手改掉三处**误诊**的断言文字：它们把"两路都被拒"写成"那是死会话不是限流"，而今天实测到的第三种
  可能是"账号刚被连刷过"。现在三种并列，并写清"重放救不了它"。

### 06:14 的分岔：不是形状问题了，是"副本 = 第二台设备"（measured 2026-09-26）

用户自己在工作流里点执行，**微博能搜出结果**；同一时刻测试的同一份用例仍被答 passport。两条时间线：

| | Cookie 文件 | 该 profile 的 `imported_at` | 结果 |
|---|---|---|---|
| 用户自己的抓取 | 不种（09-24 导入的那份 jar 一直在滚） | **2026-09-24 14:24** | ✅ 06:14 有结果 |
| 真站层（#140 之后） | 种的是 05:23 重存的那份 | **2026-09-26 06:06** | ❌ 06:13 passport |

所以"每轮重放"只是第一层；**只要测试用的是副本，它就已经是第二台设备**。微博接受的是它那一路一直滚
下来的 jar，不接受 05:23 那份拷贝（它自己的红线就是"已登录页面会重发 SUB/SUBP"）。

结论与做法：给真站层加**显式同意开关** `CIXI_LIVE_USE_USER_PROFILE=1`（`isolation_guard.uses_user_profile()`
是唯一读点，`tests/live_site/conftest.py:resolve_profile_root()` 用它决定根）。开的时候真站层就落在
`data/chrome_profile/<平台>`，与用户同一条会话；隔离看门狗**只**放行这一棵子树，`data/cookies`、
`data/workflows`、两个 .db 与 `logs/` 一个都不放。默认关（保隔离），因为开着它就是在花用户的真实会话。

被否掉的替代：**继续用副本并接受微博测不动**——那等于把"已登录抓取"这一整块自动化覆盖丢掉；
**每轮重登一次测试 profile**——需要用户每次扫码，比开关更贵；**给 hold 加冷却**——治不到"第二台设备"。

### 开关的真机判决（06:32，`CIXI_LIVE_USE_USER_PROFILE=1`）

同一台机器、同一份 Cookie、同一批用例，只把 profile 根换成用户自己那份：
**6 passed，30.42 秒**，全程没有一行 `登录墙`，也**没有一行 `Cookie 预置`**（marker 仍是
`imported_at 2026-09-24`，`used_at` 走到 06:32 —— 用的是它自己那份 jar）。行数：
时间窗搜索 8 条、可见窗口搜索 3 条、**作者模式 5 条（`作者作品采集结束：5 条（target）`）**——
最后这条是今晚第一次真的取到 mymblog 的行（之前分别是 403 拒绝、passport、空表），
评论用例也一起过了。

于是三个说法现在有了次序：**"每轮重放"是第一层病因（#140 已修），"副本 = 第二台设备"是第二层
（这个开关修）**；微博的已登录路径要自动化，必须跑在用户自己那份 jar 上。






