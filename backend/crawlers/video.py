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
import json
import logging
import re
import time
from urllib.parse import quote

from i18n import t

from .base import Crawler, as_index
from .engine import feed, popup
from .engine.counters import parse_count

logger = logging.getLogger(__name__)

# ─── bilibili endpoints and their codes ──────────────────────────────

VIEW_API = 'https://api.bilibili.com/x/web-interface/view?bvid='
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
        page and from the video page alike.
        """
        script = (
            'var done = arguments[arguments.length - 1];'
            f'fetch({json.dumps(url)}, {{credentials: "include"}})'
            '.then(function (r) { return r.json(); })'
            '.then(function (j) { done(j); })'
            '.catch(function (e) { done({err: String(e)}); });'
        )
        try:
            self.driver.set_script_timeout(25)
            payload = self.driver.execute_async_script(script)
        except Exception as e:
            logger.debug('in-page fetch failed: %s', e)
            return {}
        return payload if isinstance(payload, dict) else {}

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

    MAX_PAGES = 40
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
        while page <= self.MAX_PAGES and self.collected() < target_count:
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
                    # do not spend the remaining 39 pages on it.
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
            stopped=lambda: self.login_wall,
            max_rounds=self.MAX_PAGES,
            stuck_rounds=2,
            settle_wait=self.CARD_WAIT,
        )
        logger.info(t('crawl.bili.authorDone', n=self.collected(), reason=result.stopped_reason))
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
        if payload.get('code') != 0:
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
    #: The search box still takes the text and its 搜索 button is still clickable,
    #: but neither routes any more (measured, and confirmed by the user watching the
    #: window: the words appear, the click does nothing, and Enter does not either).
    #: So the result page is entered through its own address, which has the extra
    #: merit that the keyword the user asked for is the keyword the URL carries —
    #: there is no router left to interrogate about it.
    SEARCH_ENTRY = 'https://www.douyin.com/search/{kw}?type=video'
    CAPTCHA_MARKS = ('验证码', '滑动验证')
    #: The list mounts as 16 **skeleton** rows first — an opacity-.04 logo with no
    #: anchor and no text — and fills them in ~4-6 s later (measured). Waiting for
    #: "some rows" would read an undrawn page as a keyword that found nothing, so
    #: the wait is for a row that carries a video address.
    MOUNT_WAIT = 45.0
    #: How long one scroll is allowed to take to pay out new rows.
    SCROLL_WAIT = 14.0
    MAX_ROUNDS = 12
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
        if reached == self.CAPTCHA:
            raise RuntimeError(t('crawl.dy.wall'))
        if reached != self.OK:
            # Zero cards is never an empty answer here. Measured: a keyword that
            # cannot exist still came back with 16 related videos, because douyin
            # fills the list in rather than showing an empty plate — so an empty
            # page means blocked (验证码中间页) or broken (``502 Bad Gateway``), both
            # of which were observed, and reporting 0 rows would blame the keyword.
            raise RuntimeError(t('crawl.dy.noCards', page=self._page_words(), url=self._current_url()))
        rounds = 0
        while self.collected() < target_count and rounds < self.MAX_ROUNDS:
            rounds += 1
            ids = self._card_ids()
            todo = [aweme_id for aweme_id in ids if aweme_id not in done]
            logger.info(t('crawl.dy.round', i=rounds, n=len(ids), fresh=len(todo), done=self.collected()))
            if not todo:
                break
            for aweme_id in todo:
                if self.collected() >= target_count:
                    break
                done.add(aweme_id)
                row = self._detail_row(aweme_id)
                if row and self.emit(row):
                    logger.info(t('crawl.dy.processed', i=aweme_id, n=self.collected()))
                self.mark_position(page=rounds, done=self.collected(), opened=sorted(done)[-40:])
                self._polite_pause(0.6, 0.2)
            if self.collected() >= target_count:
                # The budget is met — do not go looking for the next batch. The
                # check belongs here rather than being left to the loop condition,
                # because scrolling first would wait out ``SCROLL_WAIT`` for rows
                # nobody asked for.
                break
            if not self._scroll_results():
                break
        logger.info(t('crawl.dy.finished', n=self.collected(), total=target_count))
        return self.results()

    # ─── reaching and reading the result list ─────────────────────────

    def _title(self) -> str:
        with contextlib.suppress(Exception):
            return self.driver.title or ''
        return ''

    def _open_results(self, keyword: str) -> str:
        """Enter the result page through its own address; report how it ended.

        Measured 2026-09: the search box takes the text, the 搜索 button is present
        and clickable, and neither routes — the address sits on ``/jingxuan``
        through a click *and* through Enter, which is exactly what the user reported
        watching the window. The ``/search/<kw>`` deep link, which used to leave three
        empty ``<ul>``s behind, now serves the result list, and it carries the keyword
        in its own path: the search the user asked for and the search that ran cannot
        disagree.

        ``ok`` / ``captcha`` / ``not_mounted`` — and none of them is "no results".
        A nonsense keyword still drew 16 related cards, so this page has no empty
        state to report; see ``search`` for why the third ending raises.
        """
        url = self.SEARCH_ENTRY.format(kw=quote(str(keyword or '')))
        self.open(url)
        # The 「保存登录信息」 mask mounts seconds after the page and covers the
        # list; it is dismissed on arrival rather than after a failed click.
        self._dismiss_prompts()
        return self._wait_for_page()

    def _wait_for_page(self) -> str:
        """Poll until the list draws a card, the wall shows up, or time runs out.

        The wall is checked **on every round**, and that ordering is measured:
        headless douyin is answered with 验证码中间页 *after* the navigation settles,
        so a single check right after ``open()`` walks straight past the wall and the
        walk ends reporting zero cards — a statement about the keyword when the truth
        is about the session. The list also mounts as 16 skeleton rows (no anchor, no
        text) and fills in ~4-6 s later, so the wait is for an *anchor*.
        """
        for _ in range(max(1, int(self.MOUNT_WAIT))):
            if self._card_ids():
                return self.OK
            if self._is_walled():
                return self.CAPTCHA
            time.sleep(1.0)
        if self._is_walled():
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

    def _card_ids(self) -> list:
        """The video ids on the result page, in the order the list draws them.

        The id comes out of the card's own href (``/video/7688240192020385070``),
        which is the one thing on the card that is both stable and addressable: a
        card that has not been filled in yet — the skeleton rows the list mounts
        first — has no anchor and contributes nothing, which is why the mount wait
        counts these rather than counting nodes.
        """
        out = []
        for el in self.driver.find_elements('css selector', self.CARD_ANCHOR):
            with contextlib.suppress(Exception):
                match = self.VIDEO_HREF.search(str(el.get_attribute('href') or ''))
                if match and match.group(1) not in out:
                    out.append(match.group(1))
        return out

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
        self.open(f'https://www.douyin.com/video/{aweme_id}')
        if not self._wait_for_text(('发布时间', '评论'), timeout=15.0):
            self.check_login_wall(f'https://www.douyin.com/video/{aweme_id}')
            logger.warning(t('crawl.dy.detailEmpty', i=aweme_id))
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
