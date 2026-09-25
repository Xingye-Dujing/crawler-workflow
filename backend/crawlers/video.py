"""Video platforms: what a browser session can actually get, and how.

Bilibili is implemented against measurements taken with the user's own saved
session (the gitignored ``backend/test_bili_*.py`` probes), because every
plausible-looking alternative here is wrong:

* **The search list does not infinite-scroll.** Eight scroll rounds left exactly
  42 cards / 34 videos, unchanged. The row budget is the pager instead:
  ``&page=N`` serves a fresh screen (25–35 new videos out to page 6, 176
  distinct across 6 pages for one keyword) — except ``page=1``, which renders
  zero cards, so the first screen has to be requested as the bare URL.
* **The cards identify, the API informs.** ``x/web-interface/view?bvid=`` answers
  ``code=0`` with the panel's cookie, no wbi signature, and cross-origin from the
  search page itself — which is what keeps the whole crawl inside one session.
  The card's own DOM figures are a rounded 万-label and nothing else, so every
  number in a row comes from ``stat``.
* **Comments have no DOM at all** (``.reply-item`` renders nothing), so
  :mod:`crawlers.comments` reads ``x/v2/reply/main``. Its paging is a quirk to
  respect, not to fix: ``next`` is a cursor, not a page counter. ``next=0``
  answers and reports ``cursor.next=2``, and asking for ``next=1`` replays page
  0 byte for byte. Following the server's own value is the only walk that
  advances; a loop that incremented would store the same 19 comments forever.

Douyin is measured too (``backend/test_douyin_*.py``) and its constraints are
the opposite of bilibili's in every respect that matters:

* **Only a visible window gets through.** A headless one is answered with
  验证码中间页 on every navigation, so ``never_headless`` is set and the executor
  downgrades ``headless`` before the browser is bought.
* **The search endpoint is signed** (``a_bogus``/``msToken``/``verifyFp`` on the
  page's own ``general/search/single`` call), so there is no API to call and the
  DOM is the only path — the reverse of bilibili.
* **A deep link is an empty shell.** ``/search/<kw>`` renders three empty
  ``[data-e2e="scroll-list"]`` lists; results mount only after the real search
  bar and its button drive the app's own router, and they arrive on a *content*
  signal (为你找到…) some ten seconds later, never on a fixed sleep.
* **The web player never shows 播放数.** ``detail-video-info``'s second number is
  the same 5.9万 as the 点赞 counter, so it is the like count — douyin rows
  therefore carry no 播放数 column at all rather than a mislabelled one.
* **Comments do have a DOM** (``[data-e2e="comment-item"]``), unlike bilibili, and
  they grow by scrolling the route container (16 → 56 observed) — so the crawl is
  scroll-and-dedupe, and 「展开N条回复」 is recorded as a count instead of being
  clicked, because clicking rewrites the page under the next read.
"""

import contextlib
import logging
import re
import time
from urllib.parse import quote

from i18n import t

from .base import Crawler, PageNotArrivedError, as_index
from .engine import feed, pagefetch, popup
from .engine.counters import parse_count

logger = logging.getLogger(__name__)

# ─── bilibili endpoints and their codes ──────────────────────────────

VIEW_API = 'https://api.bilibili.com/x/web-interface/view?bvid='
#: The two boards of "what is hot right now", measured 2026-09 to answer
#: ``code=0`` unsigned from inside a bilibili page — like ``view``, they need no
#: signature and no cookie beyond what the panel saved. ``popular`` is a paged feed
#: (20 items a page, page 2 a disjoint set); ``ranking`` answers the whole weekly
#: list in one response (100 items), which is why it is walked as a single page.
POPULAR_API = 'https://api.bilibili.com/x/web-interface/popular?ps=20&pn='
RANKING_API = 'https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all'
REPLY_API = 'https://api.bilibili.com/x/v2/reply/main'

#: A withdrawn or private video answers ``-404 啥都木有``: that card is gone and
#: the crawl moves past it. Any *other* non-zero code is the session or the risk
#: engine answering, and a row built from it would be zeros wearing a real
#: title — so it stops the walk instead of being stored.
CODE_GONE = -404

_BVID_RE = re.compile(r'(BV[0-9A-Za-z]{6,})')

# One pass over the cards returns the video links and nothing else. Ad cards
# point at cm.bilibili.com and course cards at /cheese/, so the ``/video/BV``
# test already excludes them; the class check is the cheap belt, because those
# nodes are bought placement and never hold a row anyone can reopen.
CARDS_JS = """
return Array.from(document.querySelectorAll('.bili-video-card'))
  .filter(function (card) {
    return !card.querySelector('.bili-video-card__info--ad')
      && !card.querySelector('.bili-video-card__info--cheese');
  })
  .map(function (card) {
    var links = card.querySelectorAll('a');
    for (var i = 0; i < links.length; i++) {
      var h = links[i].href || '';
      if (h.indexOf('/video/BV') >= 0) { return h; }
    }
    return '';
  });
"""


def bilibili_bvid(url: str) -> str:
    """The BV id a card link or a pasted video URL identifies."""
    match = _BVID_RE.search(str(url or ''))
    return match.group(1) if match else ''


def bilibili_mid(value: str) -> str:
    """The numeric member id a space link or a typed mid identifies.

    Accepts ``266765166``, a pasted ``space.bilibili.com/266765166/upload/video``
    link (what the browser's address bar actually holds after visiting someone) and
    the ``/space.to_511...`` share form. Anything without digits is refused rather
    than turned into a URL that would show an empty page — "this UP has posted
    nothing" must not be inferable from a malformed address.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    if text.isdigit():
        return text
    match = re.search(r'bilibili\.com/(\d{3,})', text) or re.search(r'space\.to_(\d{3,})', text)
    return match.group(1) if match else ''


def bilibili_search_url(keyword: str, page: int) -> str:
    """Page *page* of a keyword search — where page 1 carries no parameter.

    ``&page=1`` is a real measured hole (0 cards, and 12 s of waiting did not
    fill it), so asking for it would look like an exhausted result set.
    """
    base = 'https://search.bilibili.com/all?keyword=' + quote(str(keyword or ''))
    return base if page <= 1 else f'{base}&page={page}'


def _stamp(value) -> str:
    """Unix seconds → the local datetime the platform shows; blank when absent."""
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seconds)) if seconds else ''


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class VideoCrawler(Crawler):
    """Shared shape for the video platforms."""

    #: Flipped per platform once its search/detail/comment crawl exists.
    supports_crawl = False

    def _not_crawlable(self) -> RuntimeError:
        return RuntimeError(t('crawl.platformNotCrawlable', platform=self.domain))

    def _fetch_json(self, url: str) -> dict:
        """GET *url* from inside the open page, with the browser's own session.

        The endpoints authenticate the cookie the panel saved, so issuing the
        request in page is both the only way the credentials travel and the
        reason no signature has to be forged: measured ``code=0`` from the search
        page and from the video page alike. The mechanics live in
        :mod:`crawlers.engine.pagefetch` (one home for every page-context fetch);
        this keeps the platform's own ledger (``self.requests``) wired in.
        """
        # Counted alongside the navigations: "this board needs one request per page"
        # is a claim about the in-page fetches, not about ``open()``.
        return pagefetch.fetch_json(self.driver, url, requests=self.requests)

    def search(self, keyword: str, **_kwargs):
        raise self._not_crawlable()

    def get_detail(self, url: str) -> dict | None:
        raise self._not_crawlable()


class BilibiliCrawler(VideoCrawler):
    """Bilibili (哔哩哔哩): paged keyword search, rows resolved through the API."""

    domain = 'www.bilibili.com'
    cookie_domains = ('bilibili.com', 'm.bilibili.com', 'api.bilibili.com')
    login_url = 'https://www.bilibili.com/'
    supports_crawl = True

    #: The site's own pager answers how deep the search goes; the walk stops on the
    #  user's target, an empty page or risk control — nothing caps it here.
    CARD_WAIT = 12.0
    #: How far one round of the space page is scrolled. The upload list appends as
    #: it is reached (measured 40 cards, then 80 anchors after three steps), so the
    #: pager is the scroll and not a page parameter.
    SCROLL_STEPS = 3
    POLITE_BASE = 0.8
    POLITE_SPREAD = 0.3

    def search(self, keyword: str, target_count: int = 200, **kwargs):
        """Walk the pager, resolving each card into a full row.

        The cursor is the page number: a resumed run re-opens the pager at the
        page it died on, and the row ledger drops the overlap that the pages
        repeat (the search list is not disjoint — 25 fresh out of 35 on the far
        pages). Nothing is re-fetched from the API for a video already in hand.
        """
        resume = self.resume_of(kwargs)
        page = max(1, as_index(resume.get('page'), 1))
        if self.collected() >= target_count:
            logger.info(t('crawl.bili.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.bili.start', kw=keyword, n=target_count))
        seen: set[str] = set()
        stuck = 0
        blocked = ''
        while self.collected() < target_count:
            url = bilibili_search_url(keyword, page)
            if page == 1:
                logger.info(t('crawl.bili.url', url=url))
            self.open(url)
            bvids = self._wait_bvids()
            self.check_login_wall(url)
            if self.login_wall:
                break
            if not bvids:
                logger.info(t('crawl.bili.empty_page', page=page))
                break
            fresh = [b for b in bvids if b not in seen]
            logger.info(t('crawl.bili.page', page=page, n=len(bvids), fresh=len(fresh), done=self.collected()))
            for bvid in fresh:
                seen.add(bvid)
                if self.collected() >= target_count:
                    break
                payload = self._fetch_json(f'{VIEW_API}{bvid}')
                code = payload.get('code')
                if code == 0:
                    if self.emit(self._row(payload.get('data') or {})):
                        logger.info(t('crawl.bili.processed', i=bvid, n=self.collected()))
                    else:
                        logger.debug(t('crawl.bili.duplicate', i=bvid))
                elif code is not None and code != CODE_GONE:
                    # Risk control or a dead session: keep what is on disk, but
                    # do not spend further pages on it.
                    blocked = str(code)
                    break
                self.mark_position(page=page, done=self.collected(), bvid=bvid)
            if blocked:
                break
            # A page that repeats the whole screen adds nothing: the list is
            # exhausted (or shuffled back onto itself), and further pages would
            # only spend API calls on rows the ledger already has.
            stuck = stuck + 1 if not fresh else 0
            if stuck >= 2:
                logger.info(t('crawl.bili.no_more', page=page))
                break
            page += 1
            self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)
        if blocked and not self.collected():
            raise RuntimeError(t('crawl.bili.blocked', code=blocked))
        logger.info(t('crawl.bili.finished', n=self.collected(), total=target_count))
        return self.results()

    def author(self, author: str, target_count: int = 200, **kwargs):
        """One creator's own uploads, read off their space page.

        The list is built from the same ``.bili-video-card`` container the keyword
        search uses, so the card reader is shared and a row from this mode cannot
        disagree with a row from that one — the counts still come from the unsigned
        ``x/web-interface/view`` per video.

        The signed ``x/space/wbi/arc/search`` is deliberately not used: measured it
        answers ``code=-403 访问权限不足`` for our session (and the older un-wbi path
        is rate-limited at ``-799``), and forging a per-request signature is a
        different, larger problem than reading a page that already renders.
        """
        mid = bilibili_mid(author)
        if not mid:
            raise ValueError(t('crawl.bili.authorEmpty', author=author))
        if self.collected() >= target_count:
            logger.info(t('crawl.bili.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.bili.authorStart', mid=mid, n=target_count))
        url = f'https://space.bilibili.com/{mid}/video'
        self.open(url)
        self.check_login_wall(url)
        if self.login_wall:
            raise RuntimeError(t('crawl.bili.blocked', code='login'))
        # A space of one's own starts empty only while it hydrates; the profile
        # header above the list is already there, so a poll is enough.
        bvids = self._wait_bvids()
        if not bvids:
            logger.info(t('crawl.bili.authorNoVideos', mid=mid))
            return self.results()

        # Identity is the set already in hand, not a resume blob: the rows carry
        # their own BV号, so a resumed crawl skips what it paid for and the cursor
        # stays a position. (A bvid is added the moment it is *attempted*: one that
        # answered 稿件不存在 must not be re-asked every round of the same walk.)
        seen: set[str] = {str(row.get('BV号') or '') for row in self.results() if row.get('BV号')}

        def scrape(bvid: str, index: int) -> dict | None:
            if bvid in seen:
                return None
            seen.add(bvid)
            payload = self._fetch_json(f'{VIEW_API}{bvid}')
            if payload.get('code') != 0:
                if payload.get('code') is not None and payload.get('code') != CODE_GONE:
                    raise RuntimeError(t('crawl.bili.blocked', code=str(payload.get('code'))))
                return None
            return self._row(payload.get('data') or {})

        def mark(position):
            self.mark_position(mid=mid, **position, done=self.collected())

        result = feed.walk_feed(
            self._bvids,
            scrape,
            self.emit,
            scroll=lambda: self.scroll_down(steps=self.SCROLL_STEPS),
            target=target_count,
            collected=self.collected,
            mark=mark,
            stopped=lambda: self.login_wall or self.may_stop(),
            stuck_rounds=2,
            settle_wait=self.CARD_WAIT,
        )
        logger.info(t('crawl.bili.authorDone', n=self.collected(), reason=result.stopped_reason))
        return self.results()

    def hot(self, board: str = 'popular', target_count: int = 50, **kwargs):
        """The site's own hot list: 热门 (a paged feed) or 排行榜 (one 100-item page).

        This is the one bilibili walk that needs **no per-row request**: measured,
        ``x/web-interface/popular`` and ``ranking/v2`` answer ``code=0`` unsigned and
        each item already carries ``owner``/``stat``/``pubdate`` — the same shape
        ``view`` returns for a single video. The search walk pays one request per row
        only because a search *card* shows a rounded 万-label.

        The row goes through :meth:`_row`, the same flattener the other two modes
        use, so a hot-list row cannot disagree with a search row about what 播放数
        means or where 链接 comes from.
        """
        single = str(board or '').strip() == 'ranking'
        board_label = t('crawl.bili.boardRanking') if single else t('crawl.bili.boardPopular')
        resume = self.resume_of(kwargs)
        page = max(1, as_index(resume.get('page'), 1))
        if self.collected() >= target_count:
            logger.info(t('crawl.bili.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.bili.hotStart', board=board_label, n=target_count))
        # The endpoints are read from inside a bilibili page (same-origin, cookie
        # carried), so one navigation buys the session a document to ask from.
        self.open('https://www.bilibili.com/')
        self.check_login_wall('https://www.bilibili.com/')
        if self.login_wall:
            raise RuntimeError(t('crawl.bili.blocked', code='login'))
        seen: set[str] = {str(row.get('BV号') or '') for row in self.results() if row.get('BV号')}
        while self.collected() < target_count:
            payload = self._fetch_json(RANKING_API if single else f'{POPULAR_API}{page}')
            code = payload.get('code')
            if code != 0:
                if self.collected():
                    logger.warning(t('crawl.bili.blocked', code=str(code)))
                    break
                raise RuntimeError(t('crawl.bili.blocked', code=str(code)))
            items = (payload.get('data') or {}).get('list') or []
            fresh = [item for item in items if str(item.get('bvid') or '') not in seen]
            logger.info(t('crawl.bili.hotPage', page=page, n=len(items), fresh=len(fresh), done=self.collected()))
            if not items:
                break
            for item in fresh:
                if self.collected() >= target_count:
                    break
                seen.add(str(item.get('bvid') or ''))
                self.emit(self._row(item))
                self.mark_position(page=page, board='ranking' if single else 'popular', done=self.collected())
            if single:
                # One answer *is* the whole board; asking for page two would replay it.
                break
            if not fresh:
                break
            page += 1
            self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)
        logger.info(t('crawl.bili.hotDone', n=self.collected(), total=target_count))
        return self.results()

    # ─── pieces ────────────────────────────────────────────────────────

    def _bvids(self) -> list:
        hrefs = None
        with contextlib.suppress(Exception):
            hrefs = self.driver.execute_script(CARDS_JS)
        out = []
        for href in hrefs or []:
            bvid = bilibili_bvid(href)
            if bvid and bvid not in out:
                out.append(bvid)
        return out

    def _wait_bvids(self) -> list:
        """Poll the card list until it has something or the wait is spent.

        A fixed sleep is wrong in both directions here: the pager hydrates in
        under a second when it is warm, and a cold page that needs three still
        reads as "no results" to a crawler that stopped looking at t=2s.
        """
        self._wait_for_count(lambda: len(self._bvids()), 1, timeout=self.CARD_WAIT, tick=1.0)
        return self._bvids()

    @staticmethod
    def _row(data: dict) -> dict:
        """One view answer, flattened.

        The column names follow the rest of the project (正文 is the body the
        analysis nodes read, 链接 is the row's identity in the dedupe ledger) and
        every count is a bare integer, so a spreadsheet sums them without
        parsing 万.
        """
        stat = data.get('stat') or {}
        owner = data.get('owner') or {}
        season = data.get('ugc_season') or {}
        bvid = Crawler._as_text(data.get('bvid'))
        return {
            '标题': Crawler._as_text(data.get('title')),
            'UP主': Crawler._as_text(owner.get('name')),
            'UP主ID': str(owner.get('mid') or ''),
            '正文': Crawler._as_text(data.get('desc')),
            '发布时间': _stamp(data.get('pubdate')),
            'BV号': bvid,
            '稿件ID': str(data.get('aid') or ''),
            '合集': Crawler._as_text(season.get('title')),
            '分P数': _as_int(data.get('videos')),
            '时长秒': _as_int(data.get('duration')),
            '播放数': _as_int(stat.get('view')),
            '点赞数': _as_int(stat.get('like')),
            '投币数': _as_int(stat.get('coin')),
            '收藏数': _as_int(stat.get('favorite')),
            '转发数': _as_int(stat.get('share')),
            '弹幕数': _as_int(stat.get('danmaku')),
            '评论数': _as_int(stat.get('reply')),
            '链接': f'https://www.bilibili.com/video/{bvid}/' if bvid else '',
        }

    def get_detail(self, url: str) -> dict | None:
        bvid = bilibili_bvid(url)
        if not bvid:
            return None
        payload = self._fetch_json(f'{VIEW_API}{bvid}')
        code = payload.get('code')
        if code != 0:
            # None is this method's contract answer (never a plausible empty row), but
            # on its own it conflates two facts the rest of the project keeps apart:
            # the endpoint REFUSED (a risk code, or a WAF body that is not JSON at all
            # — measured 2026-09-25 when a batch's earlier view calls spent the
            # session's budget) and the video is GONE (-404, a real fact about the
            # row). The first names itself on ``risk_blocked`` so a caller — and the
            # live tier — can tell a refusal from an answer, the same rule search()
            # enforces by raising.
            if code == CODE_GONE:
                return None
            self.risk_blocked = True
            logger.warning(t('crawl.bili.blocked', code=str(code if code is not None else 'fetch')))
            return None
        return self._row(payload.get('data') or {})


class DouyinCrawler(VideoCrawler):
    """Douyin (抖音 web): search-bar driven, one video page per row, visible window only."""

    domain = 'www.douyin.com'
    cookie_domains = ('douyin.com', 'www.iesdouyin.com')
    login_url = 'https://www.douyin.com/'
    supports_crawl = True

    #: Headless is answered by 验证码中间页 on every navigation — measured, not
    #: assumed. The executor has to open a real window for this platform.
    never_headless = True

    #: The 「保存登录信息超过5天」 mask covers the search button (measured: the
    #: click is intercepted by ``.trust-login-dialog-mask``). Only 取消 is ever
    #: pressed: the user reports that 保存 leads to a phone-verification step, so
    #: declining is both the safe answer and the one that keeps the session alone.
    prompts = (popup.DOUYIN_TRUST_LOGIN,)

    #: Outcomes of the "reach the result list" step — kept as names because the
    #: caller has to treat them differently (see ``_open_results``).
    OK = 'ok'
    NOT_MOUNTED = 'not_mounted'
    CAPTCHA = 'captcha'

    #: A result card is ``li > div.search-result-card > a[href]`` inside the site's
    #: own ``[data-e2e="scroll-list"]``, and the anchor *is* the video address
    #: (measured 2026-09: ``//www.douyin.com/video/7688240192020385070``). The
    #: previous selector, ``div.discover-video-card-item[data-aweme-id]``, now
    #: matches zero nodes and the class names beside it are build hashes, so the
    #: ``data-e2e`` key plus the href shape is all that is stable enough to crawl by.
    CARD_ANCHOR = '[data-e2e="scroll-list"] a[href*="/video/"]'
    VIDEO_HREF = re.compile(r'/video/(\d{6,25})')
    #: A creator's own page. The 作品 grid is ``[data-e2e="user-post-list"]`` and its
    #: anchors are the video addresses, but the shape that matters is *how it pages*:
    #: the window does not scroll this list at all (measured — a window scroll grew the
    #: footer's recommended-video links from 8 to 29 and left the grid untouched, which
    #: reads as "57 of 85 and no more" about a page that pages perfectly). Taking the
    #: grid's own scrollable ancestor to its bottom adds a batch of 18 per round:
    #: 21 → 39 → 57 → 85, and 85 is what ``user-tab-count`` publishes.
    PROFILE_ENTRY = 'https://www.douyin.com/user/{sec}'
    PROFILE_ANCHOR = '[data-e2e="user-post-list"] a[href*="/video/"]'
    PROFILE_GRID = '[data-e2e="user-post-list"]'
    #: What the page says its own 作品 count is — the only honest yardstick for
    #: "did we reach the end of this list" when the list has no end marker.
    WORK_COUNT = '[data-e2e="user-tab-count"]'
    #: The search box still takes the text and its 搜索 button is still clickable,
    #: but neither routes any more (measured, and confirmed by the user watching the
    #: window: the words appear, the click does nothing, and Enter does not either).
    #: So the result page is entered through its own address, which has the extra
    #: merit that the keyword the user asked for is the keyword the URL carries —
    #: there is no router left to interrogate about it.
    SEARCH_ENTRY = 'https://www.douyin.com/search/{kw}?type=video'
    #: The board page and its own endpoint. Measured twice today
    #: (``scratchpad/douyin_hot_static.json``): asked from inside a loaded ``/hot``
    #: document with a URL built **from literals** — no ``a_bogus``, no ``msToken``, no
    #: ``fp``, no ``webid`` — it answers ``status_code=0`` with 51 rows and every one of
    #: them carries ``hot_value`` *and* ``view_count``, four repeats in a row. Adding a
    #: made-up ``webid`` changes nothing, so the crawler can author the URL instead of
    #: copying the page's request; stripping down to 6 public params loses the figure
    #: entirely (48 rows, ``view_count`` null on all of them), which is why the names
    #: below are spelled out rather than reduced to what "looks required".
    HOT_ENTRY = 'https://www.douyin.com/hot'
    HOT_API = (
        'https://www.douyin.com/aweme/v1/web/hot/search/list/'
        '?device_platform=webapp&aid=6383&channel=channel_pc_web&detail_list=1&source=6'
        '&pc_client_type=1&version_code=170400&version_name=17.4.0&cookie_enabled=true'
        '&screen_width=1920&screen_height=1080&browser_language=zh-CN&browser_platform=Win32'
        '&browser_name=Chrome&browser_version=148.0.0.0&browser_online=true&os_name=Windows'
        '&platform=webapp'
    )
    CAPTCHA_MARKS = ('验证码', '滑动验证')
    #: The list mounts as 16 **skeleton** rows first — an opacity-.04 logo with no
    #: anchor and no text — and fills them in ~4-6 s later (measured). Waiting for
    #: "some rows" would read an undrawn page as a keyword that found nothing, so
    #: the wait is for a row that carries a video address.
    MOUNT_WAIT = 45.0
    #: How long one scroll is allowed to take to pay out new rows.
    SCROLL_WAIT = 14.0
    #: Measured: the window scrolling does page the list now (16 → 26 → 36 → 46 → 56
    #: cards), so the pager is the window and not only the detail visit.
    SCROLL_STEP = 0.9
    POLITE_BASE = 1.0
    POLITE_SPREAD = 0.4

    def search(self, keyword: str, target_count: int = 50, **kwargs):
        """Open the result route, then open each card for the numbers it lacks.

        A search card carries an address, a duration and one rounded figure — the
        four counters and the real publish time come only from the video page, so
        the row budget is the detail visit and the cursor records which ids have
        been opened: a resumed run picks up mid-list instead of re-paying for the
        head of it.
        """
        resume = self.resume_of(kwargs)
        opened = [str(v) for v in (resume.get('opened') or []) if str(v)]
        done = set(opened)
        if self.collected() >= target_count:
            logger.info(t('crawl.dy.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.dy.start', kw=keyword, n=target_count))
        reached = self._open_results(keyword)
        if self._page_outcome(reached) == self.CAPTCHA:
            raise RuntimeError(t('crawl.dy.wall'))
        if not reached['arrived']:
            # Zero cards is never an empty answer here. Measured: a keyword that
            # cannot exist still came back with 16 related videos, because douyin
            # fills the list in rather than showing an empty plate — so an empty
            # page means blocked (验证码中间页), broken (``502 Bad Gateway``) or a
            # load that never finished, and reporting 0 rows would blame the keyword.
            # The third of those is said by its own sentence: it is the machine's
            # network, not the site refusing, and the user watching the window told us
            # so after a run blamed douyin for exactly this.
            #
            # And when the browser wrote the page itself, that is said instead: there
            # is no slower wait that would change a refused address into a page, which
            # is why the shared wait leaves it as soon as it sees it. Every branch
            # raises :class:`PageNotArrivedError` with its own numbers so the executor can
            # add what only a probe of this machine can tell — the three sentences on
            # their own are observations, not advice.
            facts = {'waited': reached['waited'], 'verdict': reached['verdict'], 'gave_up': reached['gave_up']}
            if reached['verdict'] == 'unreachable':
                raise PageNotArrivedError(
                    t('crawl.dy.noPageRefused', url=self._current_url(), detail=self._error_detail()), **facts
                )
            if not self.navigation_settled:
                raise PageNotArrivedError(t('crawl.dy.noCardsSlow', url=self._current_url()), **facts)
            raise PageNotArrivedError(t('crawl.dy.noCards', page=self._page_words(), url=self._current_url()), **facts)
        rounds = self._open_each(self._card_ids, self._scroll_results, done, target_count)
        logger.info(t('crawl.dy.finished', n=self.collected(), rounds=rounds, total=target_count))
        return self.results()

    def author(self, author: str, target_count: int = 50, **kwargs):
        """One creator's own posts, read off their profile grid.

        The row budget is the detail visit here exactly as in a keyword search: the
        grid's card carries an address, a 置顶 mark and one bare figure, and that
        figure measures equal to the **like** count — so the counters come from
        opening the video, and a row from this mode is indistinguishable from a row
        from the search mode.
        """
        sec = douyin_sec_uid(author)
        if not sec:
            raise ValueError(t('crawl.dy.authorEmpty', author=author))
        if self.collected() >= target_count:
            logger.info(t('crawl.dy.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.dy.authorStart', n=target_count))
        url = self.PROFILE_ENTRY.format(sec=sec)
        self.open(url)
        self._dismiss_prompts()
        if self._is_walled():
            raise RuntimeError(t('crawl.dy.wall'))
        published = self._published_count()
        # A page that has already published its own 作品 count arrived, so what is left to
        # learn about its grid is progress — and progress keeps the short budget. Any
        # other page is one this machine may still be delivering, and that is what the
        # patient clock is for.
        grid = self._wait_for_grid(timeout=self.MOUNT_WAIT if published == 0 else None)
        if not grid['arrived']:
            if published == 0:
                # The page says it holds nothing, which is a fact about the creator.
                logger.info(t('crawl.dy.authorNoWorks'))
                return self.results()
            # Anything else is a page that did not answer: quoting the site is the
            # only way the user can tell a wall from a quiet zero.
            facts = {'waited': grid['waited'], 'verdict': grid['verdict'], 'gave_up': grid['gave_up']}
            if grid['verdict'] == 'unreachable':
                raise PageNotArrivedError(
                    t('crawl.dy.noPageRefused', url=self._current_url(), detail=self._error_detail()), **facts
                )
            if published > 0:
                raise PageNotArrivedError(
                    t('crawl.dy.authorNoCards', page=self._page_words(), url=self._current_url(), works=published),
                    **facts,
                )
            raise PageNotArrivedError(
                t('crawl.dy.authorNotMounted', page=self._page_words(), url=self._current_url()), **facts
            )
        # Identity, not a resume blob: the rows carry their own 视频ID, so a resumed
        # run skips what it already paid for and the cursor stays a position.
        done = {str(row.get('视频ID') or '') for row in self.results() if row.get('视频ID')}
        self._open_each(lambda: self._grid_ids(), self._scroll_profile, done, target_count)
        if published >= 0:
            logger.info(t('crawl.dy.authorDone', n=self.collected(), works=published))
        else:
            # No count on the page is not a count of zero: the line says so instead
            # of printing a number the site never published.
            logger.info(t('crawl.dy.authorDoneNoCount', n=self.collected()))
        return self.results()

    # ─── the site's own hot board ──────────────────────────────────────

    def hot(self, target_count: int = 50, **kwargs):
        """抖音热榜 — one answer, which IS the whole board.

        The page is opened for two reasons and neither is the rows: it is the same-origin
        document the endpoint is asked from, and it is where a session that has died is
        seen being answered the 验证码中间页 (measured: the wall arrives *after* the
        navigation settles, which is why this waits the way ``search`` does rather than
        checking the URL once).

        There is no paging and no per-row visit: measured, the one answer carries all 51
        entries with their own figures, so asking again would replay the board and
        opening each topic page would pay for rows the board already published. A target
        above what the board holds is answered by saying what it holds.
        """
        if self.collected() >= target_count:
            logger.info(t('crawl.dy.hotTarget', n=target_count))
            return self.results()
        logger.info(t('crawl.dy.hotStart', n=target_count))
        self.open(self.HOT_ENTRY)
        self._dismiss_prompts()
        wait = self._wait_for_page()
        if self._page_outcome(wait) == self.CAPTCHA or self._is_walled():
            # Named, not empty: the board needs a session, and 0 rows would read as
            # "nothing is hot today" rather than "this cookie is not getting in".
            raise RuntimeError(t('crawl.dy.hotWall'))
        if not wait['arrived'] and wait['verdict'] == 'unreachable':
            # The browser wrote this page itself. There is no board to read out of a
            # document that never came from douyin, and saying so is better than the
            # empty-payload refusal two lines below, which would blame the endpoint.
            raise PageNotArrivedError(
                t('crawl.dy.noPageRefused', url=self._current_url(), detail=self._error_detail()),
                waited=wait['waited'],
                verdict=wait['verdict'],
                gave_up=wait['gave_up'],
            )
        payload = self._fetch_json(self.HOT_API)
        data = payload.get('data') if isinstance(payload, dict) else None
        words = data.get('word_list') if isinstance(data, dict) else None
        if not isinstance(words, list) or not words:
            envelope = payload if isinstance(payload, dict) else {}
            answer = str(envelope.get('status_msg') or envelope.get('status_code') or 'empty')[:60]
            raise RuntimeError(t('crawl.dy.hotRefused', answer=answer))
        seen = {str(row.get('链接') or '') for row in self.results()}
        for index, item in enumerate(words, start=1):
            if self.collected() >= target_count:
                break
            row = self._hot_row(item, index)
            if not row or row['链接'] in seen:
                continue
            seen.add(row['链接'])
            self.emit(row)
            self.mark_position(board='hot', done=self.collected())
        logger.info(t('crawl.dy.hotDone', n=self.collected(), total=target_count))
        if self.collected() < target_count:
            logger.info(t('crawl.dy.hotCapped', board=len(words)))
        return self.results()

    @staticmethod
    def _published(value):
        """The site's own figure, or blank when it published none.

        ``as_index`` would answer 0 for a missing value, and on this board 0 is a claim:
        the pinned top entry really is published as ``0`` at one hour and ``null`` at
        another (measured twice the same day), so only a blank says "the site gave no
        number here" without also saying it counted one.
        """
        return value if isinstance(value, int) and not isinstance(value, bool) else ''

    @classmethod
    def _hot_row(cls, item: dict, rank: int) -> dict | None:
        """One board entry, flattened by what the answer actually publishes.

        ``word`` is both the title and the topic on this site — weibo publishes a separate
        ``#…#`` form and douyin does not, so 话题 is not invented as a second column of the
        same text. ``position`` is the site's own rank and it is **absent** on the pinned
        entry, which is why the caller's index is only a fallback. The link is the address
        the board's own anchors use: ``/hot/<sentence_id>/<word>``, verified today against
        four DOM hrefs and the ids in the same answer.
        """
        word = str(item.get('word') or '').strip()
        sentence = str(item.get('sentence_id') or '').strip()
        if not word or not sentence:
            return None
        return {
            '排名': cls._published(item.get('position')) or rank,
            '标题': word,
            '热度': cls._published(item.get('hot_value')),
            '观看数': cls._published(item.get('view_count')),
            '视频数': cls._published(item.get('video_count')),
            '讨论视频数': cls._published(item.get('discuss_video_count')),
            '发布时间': _stamp(item.get('event_time')),
            '链接': f'https://www.douyin.com/hot/{sentence}/{quote(word)}',
        }

    # ─── spending the list ─────────────────────────────────────────────

    def _open_each(self, read_ids, scroll, done: set, target_count: int) -> int:
        """Open one video page per id of a self-paging list, to the budget or the end.

        Both douyin walks are this shape, so the loop that spends the row budget is
        written once: read the ids on screen, open the ones not yet opened, scroll
        for the next batch.

        A round whose ids are all already known is **not** the end of the list. That
        is the resumed run's ordinary first round — the page reopens on the very ids
        the dead run opened — so stopping there (which this loop used to do) made
        断点续跑 hand back the dead run's rows and never advance past them. Only a
        scroll that pays out nothing ends the walk.
        """
        rounds = 0
        while self.collected() < target_count:
            rounds += 1
            ids = read_ids()
            todo = [aweme_id for aweme_id in ids if aweme_id not in done]
            logger.info(t('crawl.dy.round', i=rounds, n=len(ids), fresh=len(todo), done=self.collected()))
            for aweme_id in todo:
                if self.collected() >= target_count:
                    break
                done.add(aweme_id)
                row = self._detail_row(aweme_id)
                if row and self.emit(row):
                    logger.info(t('crawl.dy.processed', i=aweme_id, n=self.collected()))
                # ``page`` is kept as the cursor key because runs saved before the
                # shared walk already store the round number under it.
                self.mark_position(page=rounds, done=self.collected(), opened=sorted(done)[-40:])
                self._polite_pause(0.6, 0.2)
            if self.collected() >= target_count:
                # The budget is met — do not go looking for the next batch. The
                # check belongs here rather than being left to the loop condition,
                # because scrolling first would wait out the settle for rows
                # nobody asked for.
                break
            if not scroll():
                break
        return rounds

    # ─── reaching and reading the result list ─────────────────────────

    def _title(self) -> str:
        with contextlib.suppress(Exception):
            return self.driver.title or ''
        return ''

    def _open_results(self, keyword: str) -> dict:
        """Enter the result page through its own address; report how the wait ended.

        Measured 2026-09: the search box takes the text, the 搜索 button is present
        and clickable, and neither routes — the address sits on ``/jingxuan``
        through a click *and* through Enter, which is exactly what the user reported
        watching the window. The ``/search/<kw>`` deep link, which used to leave three
        empty ``<ul>``s behind, now serves the result list, and it carries the keyword
        in its own path: the search the user asked for and the search that ran cannot
        disagree.

        The dict is :meth:`Crawler.wait_for_first_content`'s own answer, because which
        of the three endings this is changes what the caller may claim: ``ok`` /
        ``captcha`` / ``not_mounted`` — and none of them is "no results". A nonsense
        keyword still drew 16 related cards, so this page has no empty state to report;
        see ``search`` for why the third ending raises.
        """
        url = self.SEARCH_ENTRY.format(kw=quote(str(keyword or '')))
        self.open(url)
        # The 「保存登录信息」 mask mounts seconds after the page and covers the
        # list; it is dismissed on arrival rather than after a failed click.
        self._dismiss_prompts()
        return self._wait_for_page()

    def _wait_for_page(self) -> dict:
        """Wait for the result list's first card, under the shared patient clock.

        Two facts of this page stay here rather than in the shared wait, because they
        are douyin's and not the engine's: the list mounts as 16 **skeleton** rows (no
        anchor, no text) and fills in ~4-6 s later, so the probe asks for an *anchor*
        and not for rows; and the 验证码中间页 this platform answers a bad session with
        speaks in the tab **title**, which the shared classifier cannot read — so it is
        handed in as *stalled* and the wait leaves as soon as it appears.
        """
        return self.wait_for_first_content(has_content=self._card_ids, stalled=self._is_walled)

    def _page_outcome(self, wait: dict) -> str:
        """The three-way answer this platform's callers branch on, from a wait's facts."""
        if wait.get('arrived'):
            return self.OK
        if wait.get('verdict') in ('login', 'blocked', 'wall') or self._is_walled():
            return self.CAPTCHA
        return self.NOT_MOUNTED

    def _is_walled(self) -> bool:
        """A refusal the page has already announced: captcha title, or a wall flag."""
        return bool(self.login_wall or self.risk_blocked or any(mark in self._title() for mark in self.CAPTCHA_MARKS))

    def _page_words(self) -> str:
        """What the page says about itself, quoted into the refusal.

        The title carries both measured cases (``验证码中间页``, ``502 Bad Gateway``);
        an untitled error plate still spells itself in the body, and a refusal that
        quotes the site is a different thing to read than one that says "nothing".
        """
        title = self._title().strip()
        if title:
            return title[:80]
        head = self._body_text(limit=120).strip()
        return (head.splitlines() or ['(空白页)'])[0][:80]

    def _wait_for_text(self, marks, timeout: float = 20.0) -> bool:
        """Poll the rendered text for one of *marks* (bounded, clock-free).

        Used by the video page, which answers 「视频数据加载中」 for several seconds
        before the player and its counters exist. A captcha title ends the wait
        early: waiting out a wall costs the whole timeout and changes nothing.
        """
        ticks = max(1, int(timeout / 2.0))
        for _ in range(ticks):
            body = self._body_text(limit=4000)
            if any(mark in body for mark in marks):
                return True
            if any(mark in self._title() for mark in self.CAPTCHA_MARKS):
                return False
            time.sleep(2.0)
        return any(mark in self._body_text(limit=4000) for mark in marks)

    def _card_ids(self, anchor: str | None = None) -> list:
        """The video ids on screen, in the order the list draws them.

        The id comes out of the card's own href (``/video/7688240192020385070``),
        which is the one thing on a card that is both stable and addressable: a card
        that has not been filled in yet — the skeleton rows the search list mounts
        first — has no anchor and contributes nothing, which is why the mount wait
        counts these rather than counting nodes. *anchor* switches which list is
        read: the search result or a creator's own grid.
        """
        out = []
        for el in self.driver.find_elements('css selector', anchor or self.CARD_ANCHOR):
            with contextlib.suppress(Exception):
                match = self.VIDEO_HREF.search(str(el.get_attribute('href') or ''))
                if match and match.group(1) not in out:
                    out.append(match.group(1))
        return out

    def _grid_ids(self) -> list:
        return self._card_ids(self.PROFILE_ANCHOR)

    def _wait_for_grid(self, timeout: float | None = None) -> dict:
        """Wait for the profile grid's first post, under the shared patient clock.

        A page of one's own has no empty plate to wait for: the grid either hydrates or
        this session is not being served the list, and the caller tells those two apart
        with :meth:`_published_count` — which is also why it may hand in a *shorter*
        budget, because a page that has already published its own count is a page that
        arrived, and what is left to learn there is progress, not arrival.
        """
        return self.wait_for_first_content(has_content=self._grid_ids, stalled=self._is_walled, timeout=timeout)

    def _published_count(self) -> int:
        """What the page publishes as its own 作品 count (-1 when it says nothing).

        The site's number is the only honest yardstick for a walk that ends early:
        57 rows from a page that says 85 is a pager that stopped, while 0 rows from a
        page that says 0 is a creator who has never posted.

        ``-1`` for "no such element" is the whole point of the signature: the shared
        counter parser answers an empty string with 0, and 0 is a *claim* — reading a
        missing number as zero would let a page that never rendered be reported as an
        author who never posted.
        """
        text = ''
        with contextlib.suppress(Exception):
            element = self.driver.find_element('css selector', self.WORK_COUNT)
            text = str(self._node_text(element) or '').strip()
        return parse_count(text) if text else -1

    def _scroll_profile(self) -> bool:
        """Take the grid's own scroller to its bottom and wait for the next batch.

        Measured: 21 → 39 → 57 → 85 anchors, one batch of 18 per round, each arriving
        within a second of the jump. The **window** does none of this on a profile
        page (it only feeds the footer's recommended videos), which is why the scroll
        hunts for the element that actually moves instead of calling
        :meth:`Crawler.scroll_down`.
        """
        before = len(set(self._grid_ids()))
        with contextlib.suppress(Exception):
            feed.jump_to_bottom(self.driver, self.PROFILE_GRID)
        settled = feed.wait_for(lambda: len(set(self._grid_ids())), before + 1, timeout=self.SCROLL_WAIT, tick=1.0)
        self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)
        return bool(settled > before)

    def _scroll_results(self) -> bool:
        """Step the window down and report whether the list handed over more rows.

        Measured on the current build: 16 → 26 → 36 → 46 → 56 cards, one batch of
        ten per scroll. The previous shape of this method hunted for the page's
        largest scrollable element and jumped it to its bottom, because on that
        build the window never moved at all — the measurement is what decides which
        of the two is right, and returning "nothing new" is how a walk stops
        pretending a one-screen list paged when it did not.
        """
        before = len(self._card_ids())
        step = 'window.scrollBy(0, document.body.scrollHeight * arguments[0]);'
        with contextlib.suppress(Exception):
            self.driver.execute_script(step, self.SCROLL_STEP)
        grown = feed.wait_for(lambda: len(self._card_ids()), before + 1, timeout=self.SCROLL_WAIT, tick=1.0) > before
        self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)
        return bool(grown)

    # ─── one video ────────────────────────────────────────────────────

    def get_detail(self, url: str) -> dict | None:
        aweme_id = douyin_id(url)
        if not aweme_id:
            return None
        return self._detail_row(aweme_id)

    def _detail_row(self, aweme_id: str) -> dict | None:
        """Open one video page and read the counters that name themselves.

        ``_ROUTER_DATA`` is undefined on this build and ``#RENDER_DATA`` holds
        only ``{app}``, so the numbers come from the DOM — and only from the
        ``data-e2e`` attributes that state what they count. The 播放数 column is
        deliberately absent: ``detail-video-info``'s second number equals the 点赞
        counter, so it *is* the like count, and publishing it as 播放数 would be a
        wrong figure with a plausible column name.
        """
        # Taken from the call, not from ``navigation_settled``: ``check_login_wall``
        # below may navigate again, and by the time the line is written the stored fact
        # would no longer be about this page.
        settled = self.open(f'https://www.douyin.com/video/{aweme_id}')
        if not self._wait_for_text(('发布时间', '评论'), timeout=15.0):
            self.check_login_wall(f'https://www.douyin.com/video/{aweme_id}')
            # Two different complaints. "No data rendered" says the page arrived and
            # published nothing; "the page never finished loading" says the request is
            # still owed — which is what a slow connection actually produces, and the
            # row may well be there on a retry.
            logger.warning(
                t('crawl.dy.detailSlow', i=aweme_id) if not settled else t('crawl.dy.detailEmpty', i=aweme_id)
            )
            return None
        facts = self._driver_facts()
        info_lines = [line.strip() for line in str(facts.get('info') or '').split('\n') if line.strip()]
        text = info_lines[0] if info_lines else ''
        publish = _clean_publish(facts.get('publish'))
        author, followers, liked = _author_from_related(str(facts.get('related') or ''))
        return {
            '标题': (self._title().removesuffix(' - 抖音').strip() or text)[:120],
            '正文': text,
            '作者': author,
            '粉丝数': followers,
            '获赞数': liked,
            '发布时间': publish,
            '视频ID': str(aweme_id),
            '点赞数': parse_count(facts.get('digg')),
            '评论数': parse_count(facts.get('comment')),
            '收藏数': parse_count(facts.get('collect')),
            '转发数': parse_count(facts.get('share')),
            '链接': f'https://www.douyin.com/video/{aweme_id}',
        }

    def _driver_facts(self) -> dict:
        """Every self-describing counter on the open video page, in one pass."""
        script = """
        function txt(sel) {
          var el = document.querySelector(sel);
          return el ? (el.innerText || '').trim() : '';
        }
        return {
          digg: txt('[data-e2e="video-player-digg"]'),
          comment: txt('[data-e2e="feed-comment-icon"]'),
          collect: txt('[data-e2e="video-player-collect"]'),
          share: txt('[data-e2e="video-player-share"]'),
          info: txt('[data-e2e="detail-video-info"]'),
          publish: txt('[data-e2e="detail-video-publish-time"]'),
          related: txt('[data-e2e="related-video"]')
        };
        """
        with contextlib.suppress(Exception):
            found = self.driver.execute_script(script)
            if isinstance(found, dict):
                return found
        return {}


def douyin_sec_uid(value: str) -> str:
    """The ``sec_uid`` a profile link (or a pasted token) identifies.

    Douyin addresses a creator by this opaque token only — ``/user/<numeric uid>``
    is not a route on the web app — and the token is handed out on every video page
    as ``a[href*="/user/"]``, so a pasted profile link is the thing a user can
    actually bring here. A bare token is accepted on its shape (long, no spaces):
    a display name is what people try first and it addresses nobody, and opening a
    guessed profile would report "this account posted nothing" about a page that
    belongs to someone else.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    from_link = re.search(r'/user/([A-Za-z0-9_.-]{10,})', text)
    if from_link:
        return from_link.group(1)
    return text if re.fullmatch(r'[A-Za-z0-9_.-]{30,}', text) else ''


def _clean_publish(value) -> str:
    """「发布时间：2026-08-04 16:32」 → 「2026-08-04 16:32」."""
    text = str(value or '')
    return text.split('：')[-1].strip() if '：' in text else text.strip()


def _author_from_related(related: str) -> tuple:
    """Pull the author block out of the related-videos panel.

    It is the only place the web player names the author with its follower
    count, and the line is unpunctuated (``泫九粉丝167.0万获赞1157.5万关注``), so
    the split is on the two labels rather than on positions that shift with the
    episode list.
    """
    match = re.search(r'^(.*?)粉丝([\d.]+[万千]?)获赞([\d.]+[万千]?)', related.strip())
    if not match:
        return '', 0, 0
    return match.group(1).strip(), parse_count(match.group(2)), parse_count(match.group(3))


def douyin_id(url: str) -> str:
    """The aweme id from a video URL, a share link or a bare id."""
    text = str(url or '').strip()
    if re.fullmatch(r'\d{15,20}', text):
        return text
    match = re.search(r'/video/(\d{15,20})', text) or re.search(r'[?&]modal_id=(\d{15,20})', text)
    return match.group(1) if match else ''
