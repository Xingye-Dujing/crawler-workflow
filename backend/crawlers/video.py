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
    #: The crawl's own starting point. ``https://www.douyin.com/`` answers with a
    #: redirect to ``/jingxuan`` (measured: 2.3 s for the pair, and the search box
    #: is only on the target document), so the hop is entered at its end instead
    #: of being followed. It also removes one page refresh — which is what was
    #: wiping the 「保存登录信息」 mask mid start-up and making that failure look
    #: intermittent. The cookie panel still uses ``login_url``, where a login
    #: actually begins.
    crawl_entry = 'https://www.douyin.com/jingxuan'
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
    NO_BOX = 'no_box'
    NOT_MOUNTED = 'not_mounted'
    CAPTCHA = 'captcha'
    #: The words never made it into the search box (or never reached the router),
    #: so nothing was actually searched. Not the same claim as "0 results".
    QUERY_LOST = 'query_lost'

    CARD_SELECTOR = 'div.discover-video-card-item[data-aweme-id]'
    SEARCH_INPUT = '[data-e2e="searchbar-input"]'
    SEARCH_BUTTON = '[data-e2e="searchbar-button"]'
    #: The result route carries the keyword in its path (measured:
    #: ``/jingxuan/search/人工智能?…``), which is the only proof that the query the
    #: user asked for is the query the app actually ran.
    #: Douyin's box is a controlled input: while the 「保存登录信息」 mask is up, a
    #: whole phrase arriving in one event is wiped by the site's own handler, so
    #: the query is submitted empty. Bulk writing is the fast path (measured: a
    #: fraction of a second) and per-character typing is the repair (~15 s on a
    #: busy page), which is why the order is bulk → verify → character by
    #: character → verify, never character-by-character by default.
    TYPE_DELAY = 0.12
    SUBMIT_ATTEMPTS = 2
    #: How long to wait for the address to carry the keyword after a click. The
    #: router answers in well under a second once the header is wired up; the wait
    #: is there for the case where it is not, and it is bounded so a wasted
    #: attempt costs seconds rather than the whole mount budget.
    LAND_WAIT = 5.0
    #: The results are only *there* when the page says so; the deep link and a
    #: cold SPA both look identical (and empty) before that.
    MOUNTED_MARKS = ('为你找到', '搜索响应编号')
    CAPTCHA_MARKS = ('验证码', '滑动验证')
    MOUNT_WAIT = 40.0
    MAX_ROUNDS = 6
    POLITE_BASE = 1.0
    POLITE_SPREAD = 0.4

    def search(self, keyword: str, target_count: int = 50, **kwargs):
        """Drive the site's own search box, then open each card.

        The list is one screen (19–30 cards, and scrolling the route container
        recycles the same count), so the row budget is not the pager — it is the
        detail visit: every card is opened for the numbers the card itself never
        carries. The cursor records which ids have been opened, so a resumed run
        picks up mid-list instead of re-paying for the head of it.
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
        if reached == self.NO_BOX:
            raise RuntimeError(t('crawl.dy.noSearchBox'))
        if reached == self.QUERY_LOST:
            # Nothing was searched, so "0 results" would be a lie about the
            # keyword: say the words never got in, and let the user retry.
            raise RuntimeError(t('crawl.dy.queryFailed', kw=keyword))
        if reached != self.OK:
            return self.results()
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
        """Drive the real search bar and report *how* the attempt ended.

        Four non-success outcomes and they must not blur:

        * ``nobox`` — the page handed over no search tool at all (dead session or
          a changed DOM): an actionable failure, not an empty result;
        * ``query_lost`` — the words never got into the box, or never reached the
          router: also not an empty result, and the retry is a re-type, not a
          longer wait;
        * ``captcha`` — the interstitial, which douyin announces in the **title**
          rather than in a URL pattern;
        * ``not_mounted`` — the app accepted the query but never drew cards,
          which is what a genuinely empty keyword looks like from here, so it is
          reported as zero rows rather than as a crash.

        A deep link to ``/search/<kw>`` leaves three empty ``<ul>``s behind; only
        the router's own path — focus, type, click 搜索 — mounts cards. The button
        is covered by a transparent overlay on this build, so the Enter key is the
        fallback rather than a stylistic choice.
        """
        self.open(self.crawl_entry)
        self._polite_pause(1.2, 0.3)
        # The dialog can mount during that pause, so look once more before the box
        # is touched: a mask over the page steals the focus the typing needs.
        self._dismiss_prompts()
        box = self._element_or_none(self.SEARCH_INPUT)
        if box is None:
            self.check_login_wall(self.crawl_entry)
            logger.warning(t('crawl.dy.noSearchBox'))
            return self.NO_BOX
        landed = False
        for attempt in range(1, self.SUBMIT_ATTEMPTS + 1):
            # The router is the only witness that counts: when the URL carries the
            # keyword, the search happened, whatever the input reported. Reading
            # the box back is used only to decide whether the retry needs to type
            # slowly — the node itself is replaced by the app when the header
            # re-renders, and a stale handle makes the value unreadable, which is
            # not the same as the words being missing (watched: the box held the
            # phrase, the search ran, and a value-gated loop kept clearing and
            # retyping until it gave up).
            self._type_query(box, keyword, per_character=attempt > 1)
            self._submit(box, keyword)
            landed = self._query_landed(keyword, timeout=self.LAND_WAIT)
            if landed:
                if self._wait_mounted():
                    return self.OK
                if any(mark in self._title() for mark in self.CAPTCHA_MARKS):
                    # The wall here is a page title; no _WALL_MARKERS URL matches it.
                    self.login_wall = True
                    logger.warning(t('crawl.loginWall', platform=self.domain, where=self._title()))
                    return self.CAPTCHA
            else:
                logger.info(t('crawl.dy.queryDropped', kw=keyword, url=self._current_url()))
                box = self._element_or_none(self.SEARCH_INPUT) or box
        if self.login_wall:
            return self.CAPTCHA
        if not landed:
            # The route never took the words, so no search was run: reporting zero
            # rows would be a claim about the keyword rather than about us.
            return self.QUERY_LOST
        logger.info(t('crawl.dy.noMount', url=self._current_url()))
        return self.NOT_MOUNTED

    def _type_query(self, box, keyword: str, per_character: bool = False) -> bool:
        """Write *keyword* into the search box; report whether it reads back.

        Bulk first (measured: a fraction of a second), character by character when
        asked for — that path costs ~15 s on a busy page, so it is a repair and not
        the default. The return value is advisory: ``_open_results`` judges the
        attempt by the resulting URL.
        """
        text = str(keyword or '')
        self._clear_box(box)
        with contextlib.suppress(Exception):
            self.driver.execute_script('arguments[0].focus();', box)
        if per_character:
            for ch in text:
                with contextlib.suppress(Exception):
                    box.send_keys(ch)
                time.sleep(self.TYPE_DELAY)
        else:
            with contextlib.suppress(Exception):
                box.send_keys(text)
        return self._box_value(box) == text

    def _clear_box(self, box):
        """Empty the box before a (re)type, so a retry cannot append to leftovers."""
        script = """
        var el = arguments[0];
        el.value = '';
        el.dispatchEvent(new Event('input', {bubbles: true}));
        """
        with contextlib.suppress(Exception):
            self.driver.execute_script(script, box)

    def _box_value(self, box) -> str:
        """What the input holds, read as a *property*.

        The HTML attribute is never updated by the site's own framework, so
        reading it would report an empty box on a page that is showing the words
        — the mistake this method used to make. Unreadable (a stale node) reads as
        empty, which is safe because the caller judges the attempt by the URL.
        """
        try:
            return str(self.driver.execute_script('return arguments[0].value;', box) or '')
        except Exception:
            return ''

    def _submit(self, box, keyword: str = ''):
        """Press 搜索 on a page that is actually ready to take it.

        Three things happen here in this order, and each one is a measured
        observation rather than defensive noise:

        * the dialog is cleared **first** — it mounts some six seconds after the
          page, so a mask can appear between typing and clicking, and pressing
          搜索 behind it wipes the box (watched: the click closed the dialog and
          took the words with it, which threw the whole attempt away);
        * the box is then re-checked and refilled if the words are gone, because
          that is exactly what the dialog just did;
        * the click is retried once if the overlay intercepts it, with Enter as the
          fallback — the button sits under a transparent layer on this build.
        """
        self._dismiss_prompts()
        if keyword and self._box_value(box) != str(keyword):
            self._type_query(box, keyword)
        button = self._element_or_none(self.SEARCH_BUTTON)
        if button is not None:
            try:
                button.click()
                return
            except Exception:
                self._dismiss_prompts()
                with contextlib.suppress(Exception):
                    button.click()
                    return
        with contextlib.suppress(Exception):
            box.send_keys('\n')

    def _query_landed(self, keyword: str, timeout: float = 10.0) -> bool:
        """Poll until the router carries *keyword* in the address.

        The click is not the event that matters: the header is interactive a
        moment after the page is, and a submit issued before its handler is
        attached does nothing at all (measured — two immediate clicks left the
        address on ``/jingxuan``). Waiting on the address is what makes the
        difference between "the search ran" and "this keyword found nothing"
        decidable without retrying the whole page.

        Checked in both the decoded and percent-encoded spelling, because the
        driver reports one or the other depending on the build.
        """
        text = str(keyword or '')
        encoded = quote(text)

        def hit() -> int:
            try:
                url = self.driver.current_url or ''
            except Exception:
                return 0
            return 1 if (text in url or encoded in url) else 0

        return feed.wait_for(hit, 1, timeout=timeout, tick=0.5) == 1

    def _wait_mounted(self) -> bool:
        """Wait for the result page to say it found something."""
        return self._wait_for_text(self.MOUNTED_MARKS, timeout=self.MOUNT_WAIT)

    def _wait_for_text(self, marks, timeout: float = 20.0) -> bool:
        """Poll the rendered text for one of *marks* (bounded, clock-free)."""
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
        out = []
        for el in self.driver.find_elements('css selector', self.CARD_SELECTOR):
            with contextlib.suppress(Exception):
                aweme_id = str(el.get_attribute('data-aweme-id') or '')
                if aweme_id and aweme_id not in out:
                    out.append(aweme_id)
        return out

    def _scroll_results(self) -> bool:
        """Scroll the app's own route container — the window never moves here.

        Returns whether anything new appeared. Measured: the card count stays
        fixed while scrolling (the list is virtualised), so this normally ends
        the walk after one screen rather than pretending to find more.
        """
        before = len(self._card_ids())
        script = """
        var best = null;
        document.querySelectorAll('*').forEach(function (el) {
          if (el.scrollHeight > el.clientHeight + 200 && el.clientHeight > 300
              && (!best || el.scrollHeight > best.scrollHeight)) { best = el; }
        });
        if (best) { best.scrollTop = best.scrollHeight; return true; }
        window.scrollTo(0, document.body.scrollHeight);
        return false;
        """
        with contextlib.suppress(Exception):
            self.driver.execute_script(script)
        time.sleep(2.0)
        return len(self._card_ids()) > before

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
