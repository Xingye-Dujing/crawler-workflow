"""Bilibili (哔哩哔哩): paged keyword search, rows resolved through the API.

Split out of the former ``crawlers/video.py``; the shared video base and the two
generic row helpers live in :mod:`crawlers.video_base`. The measurements that shaped
this crawler are in ``docs/crawler_notes.md``.
"""

import contextlib
import logging
import re
from urllib.parse import quote

from i18n import stop_reason_label, t

from .base import Crawler, as_index
from .engine import feed
from .video_base import VideoCrawler, _as_int, _stamp

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
        logger.info(t('crawl.bili.authorDone', n=self.collected(), reason=stop_reason_label(result.stopped_reason)))
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
