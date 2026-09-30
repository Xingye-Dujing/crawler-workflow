"""Douyin (抖音): DOM-only reads (signed API is not callable), scroll-and-dedupe comments.

Split out of the former ``crawlers/video.py``; the shared video base and the two
generic row helpers live in :mod:`crawlers.video_base`. Measurements in ``docs/crawler_notes.md``.
"""

import contextlib
import logging
import re
import time
from urllib.parse import quote

from i18n import t

from .base import UNDER_TARGET, PageNotArrivedError
from .engine import feed, popup
from .engine.counters import parse_count
from .video_base import VideoCrawler, _stamp

logger = logging.getLogger(__name__)


class DouyinCrawler(VideoCrawler):
    """Douyin (抖音 web): one video page per row, visible window only."""

    domain = 'www.douyin.com'
    cookie_domains = ('douyin.com', 'www.iesdouyin.com')
    login_url = 'https://www.douyin.com/'
    supports_crawl = True

    #: How many cards this walk could not open the overlay on (virtualised away / a click swallowed
    #: / the slide never painted), after their bounded retries were used up. Named at the end of the
    #: walk so a shortfall is a stated fact, never a silent 完成.
    _modal_deferred = 0
    #: The account's (粉丝, 获赞), read once off the profile page in ``author`` for the overlay rows
    #: (the slide does not carry them). A class default so any read before ``author`` sets it is
    #: blank rather than an AttributeError — blank, never a fabricated 0.
    _profile_totals = ('', '')

    #: The 「保存登录信息超过5天」 mask covers the search button (measured: the
    #: click is intercepted by ``.trust-login-dialog-mask``). Only 取消 is ever
    #: pressed: the user reports that 保存 leads to a phone-verification step, so
    #: declining is both the safe answer and the one that keeps the session alone.
    prompts = (popup.DOUYIN_TRUST_LOGIN,)

    #: Outcomes of the "reach the page" step — kept as names because the caller has to
    #: treat them differently (see :meth:`_page_outcome`, which ``hot`` branches on).
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
    #: The 遮罩 / preview overlay a grid card opens in the SAME document. Measured 2026-09-30
    #: (``scratchpad/dy_phase0.log``): clicking a ``user-post-list a[href*="/video/<id>"]`` swaps the
    #: URL to ``…?modal_id=<id>`` with NO document navigation (``document navigated: False``), and the
    #: slide renders its own counters + caption + author. Reading a row through it costs ZERO page
    #: loads — the whole point, since the per-row ``/video/<id>`` navigation is what drew the 验证码
    #: storm. The overlay is a SLIDE LIST: the neighbour video's ``feed-item`` sits in the DOM too, so
    #: every read is scoped to ``feed-active-video`` or it can pick up the adjacent post's figures.
    #: ``ESC`` closes it and the grid stays mounted underneath (re-clicking a later card re-opens on
    #: that id — Phase 0 confirmed the swap). Author totals 粉丝/获赞 are NOT in the slide; they come
    #: from the profile page once (``user-info-fans`` / ``user-info-like``), which is account-level.
    MODAL_ID_RE = re.compile(r'modal_id=(\d+)')
    ACTIVE_SLIDE = '[data-e2e="feed-active-video"]'
    PROFILE_FANS = '[data-e2e="user-info-fans"]'
    PROFILE_LIKED = '[data-e2e="user-info-like"]'
    ESC_KEY = '\ue00c'  # Selenium Keys.ESCAPE, sent to the body to dismiss the overlay
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
    #: How long a single overlay read waits for the clicked slide to paint. Deliberately far
    #: short of :attr:`MOUNT_WAIT`: that 45 s clock is a page-arrival budget, and spending it per
    #: row would make a stuck card cost more than the old navigation did. A slide that has not
    #: painted inside this window is treated as un-clickable and deferred, not waited out.
    MODAL_WAIT = 12.0
    #: How many times one card is retried (re-surfaced by a later scroll round and clicked again)
    #: before the walk gives up on it. A stuck overlay is often transient — the slide hydrates late,
    #: a sticky header ate one click — so dropping it the first time would be 漏采. Bounding the
    #: retries is what keeps a genuinely-unclickable card from looping forever; past this the id is
    #: consumed and counted as deferred (named at the end), never navigated.
    MODAL_MAX_TRIES = 3
    POLITE_BASE = 1.0
    POLITE_SPREAD = 0.4

    #: What the result list writes when it is done. Measured 2026-09-28 with 最新发布 chosen on 「IU」:
    #: the page carries 14 cards, the window scroll stops changing anything, and at the foot of the list
    #: sits 「暂时没有更多了」 — the site's own end-of-list sentence, twice in the document. Without reading
    #: it, a walk that ended at 14 of 50 said only 「搜索完成，共获取 14 条」, and a short table caused by
    #: the site is indistinguishable in the console from one caused by our scroll loop (which is the exact
    #: complaint this round exists to answer).
    LIST_END_MARKS = ('暂时没有更多了', '没有更多了')

    def author(self, author: str, target_count: int = 50, **kwargs):
        """One creator's own posts, read off their profile grid.

        The row budget is the detail visit: the grid's card carries an address, a 置顶
        mark and one bare figure, and that figure measures equal to the **like** count —
        so every counter but the like comes from opening the video, not from the card.
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
                # The page says it holds nothing, which is a fact about the creator —
                # the site published its own 作品 count of 0, so an empty table here is
                # attested, not a silent under-collect.
                logger.info(t('crawl.dy.authorNoWorks'))
                self.note_end('empty')
                return self.results()
            # A page that did not answer MAY have been refused by a captcha that mounted
            # during the wait; latch it before the refusal travels so the executor names
            # 风控 rather than 「这一页没到位」. An unreachable browser-error page leaves
            # ``_is_walled`` false, so its own 「浏览器自己拒绝了」 line still stands.
            self._latch_risk_if_walled()
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
        self._list_end_attested = False
        # Cards whose overlay would not open (after bounded retries) are counted here and named at
        # the end — the overlay path never navigates, so there is no per-detail wall tally to keep.
        self._modal_deferred = 0
        # 粉丝/获赞 are account-level and NOT in the slide; read them once off the profile page so
        # every row carries them (blank if the profile published none — never a fabricated 0).
        self._profile_totals = self._read_profile_totals()
        self._open_each(
            url,
            lambda: self._grid_ids(),
            self._scroll_profile,
            done,
            target_count,
        )
        if published >= 0:
            logger.info(t('crawl.dy.authorDone', n=self.collected(), works=published))
        else:
            # No count on the page is not a count of zero: the line says so instead
            # of printing a number the site never published.
            logger.info(t('crawl.dy.authorDoneNoCount', n=self.collected()))
        # The overlay never navigates, so a stuck card is DEFERRED, not chased. That leaves one gap
        # U1 must not paper over: a walk that collected NOTHING while the grid clearly had cards to
        # open (it paged, ids were harvested, but not one overlay opened) is a failed read — NOT the
        # site running out. If the page is now captcha-titled that is 风控 (back off); otherwise it is
        # a real shortfall → ``UNDER_TARGET``, which the executor refuses by name and keeps resumable.
        # A walk that collected SOME rows is left to the licenses below (a 图文 refusal among
        # rendered videos is normal). ``end_reason is None`` guard stops a license overwriting this.
        if target_count and self.collected() == 0 and self._modal_deferred:
            if self._is_walled():
                self.risk_blocked = True
            else:
                self.note_end(UNDER_TARGET)
        if (
            self.collected() < target_count
            and self.end_reason is None
            and not (self._is_walled() or self.risk_blocked or self.may_stop())
        ):
            if published >= 0 and self.collected() >= published:
                self.note_end('capped')
            elif self._list_end_attested:
                self.note_end('site_end')
        if self._modal_deferred:
            # Said once, and about a count: N cards this run could not open is the difference between
            # 「采完了」 and 「采到一半遮罩点不开」, and only the first is a site fact.
            logger.info(t('crawl.dy.modalDeferred', n=self._modal_deferred, total=target_count))
        return self.results()

    # ─── the site's own hot board ──────────────────────────────────────

    def hot(self, target_count: int = 50, **kwargs):
        """抖音热榜 — one answer, which IS the whole board.

        The page is opened for two reasons and neither is the rows: it is the same-origin
        document the endpoint is asked from, and it is where a session that has died is
        seen being answered the 验证码中间页 (measured: the wall arrives *after* the
        navigation settles, which is why this waits for the page rather than checking the
        URL once).

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
            # The board IS the site's whole list (one answer, all entries); a short here
            # is the board's size, an attested end — not an under-collect to convict.
            logger.info(t('crawl.dy.hotCapped', board=len(words)))
            self.note_end('capped')
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

    def _open_each(self, profile_url: str, read_ids, scroll, done: set, target_count: int) -> int:
        """Take the list, then read each id through the in-page overlay — NO per-row navigation.

        Two passes and never interleaved: harvest a pool of ids by scrolling the grid, then spend one
        overlay read per id. The overlay does NOT replace the grid (it opens over the SAME profile
        document and ``ESC`` dismisses it), so this never re-navigates the profile between rounds —
        the grid stays mounted underneath. A card that would not open (virtualised away, a click the
        sticky header swallowed, a slide that never painted) is DEFERRED and counted, not chased with
        a navigation: re-navigating per stuck card is the storm this change removes, and it would cost
        more than the old path. Every pool id is consumed once (added to ``done``), so the walk always
        terminates; ``_modal_deferred`` makes the shortfall visible at the end rather than silent.

        Only a scroll that pays out nothing ends the list — a round whose ids are all already known is
        the resumed run's ordinary first screen, not the end of supply.
        """
        screens = 0
        first = True
        attempts: dict = {}
        while not self.may_stop() and self.collected() < target_count:
            if not first:
                self._ensure_grid(profile_url)
            first = False
            pool, drained, taken = self._harvest_pool(read_ids, scroll, done, target_count - self.collected())
            screens += taken
            if not pool:
                break
            for aweme_id in pool:
                if self.collected() >= target_count or self.may_stop():
                    break
                row = self._modal_row(aweme_id)
                if row is self.DEFER:
                    self._close_modal()  # a stuck overlay would cover the next card
                    tries = attempts.get(aweme_id, 0) + 1
                    attempts[aweme_id] = tries
                    # Not consumed yet: leave the id out of ``done`` so a later round (while the card
                    # is still on screen) re-surfaces and retries it — 不漏采 over a transient stall.
                    # Only give up, and count it, after the bounded retries.
                    if tries >= self.MODAL_MAX_TRIES:
                        done.add(aweme_id)
                        self._modal_deferred += 1
                    continue
                done.add(aweme_id)
                if row and self.emit(row):
                    logger.info(t('crawl.dy.processed', i=aweme_id, n=self.collected()))
                # ``page`` is kept as the cursor key because runs saved before the shared walk already
                # store the round number under it. The cursor records position only — the already-read
                # ids come back from the seeded rows, never from an id list written here.
                self.mark_position(page=screens, done=self.collected())
                self._polite_pause(0.6, 0.2)
            if drained:
                # The list itself said it has nothing more, so every row this crawl can get is either
                # collected already or one whose overlay published nothing (or was deferred).
                break
        return screens

    def _ensure_grid(self, profile_url: str) -> None:
        """Make sure the grid is back and clickable between rounds.

        Reading a row opens an overlay over the grid and closes it with ``ESC``; if a read ever left
        an overlay stuck open the next scroll would feed the slide instead of the grid. Re-opening the
        profile only when the grid is gone keeps this cheap — in the normal path it is just a dismiss +
        presence check, NOT the full re-navigation the old per-detail walk paid every round.
        """
        self._close_modal()
        if not self._grid_ids():
            self._return_to_profile(profile_url)

    def _harvest_pool(self, read_ids, scroll, done: set, need: int) -> tuple:
        """Scroll the list — and nothing but the list — until it holds *need* unpaid-for ids.

        Answers the ids in the order the list draws them, whether the list ran dry, and how
        many screens that took — the last being the number the finish line quotes, so a crawl
        that read two screens still says two. Nothing here may navigate anywhere except down
        this page: once a detail page is open, *read_ids* and *scroll* are reading a document
        that has nothing to do with this search.
        """
        pool: list = []
        queued: set = set()
        screens = 0
        waited_for_swap = False
        while not self.may_stop() and len(pool) < need:
            on_screen = list(read_ids())
            if not on_screen and not waited_for_swap:
                # An empty read is the list being rewritten, not the list being empty — and the two used to
                # be indistinguishable in the console. Measured 2026-09-28: right after an order is chosen
                # the same address re-mounts its cards from scratch (~2.0 s for 最新发布, 0.1 s for the
                # default that needs no click), so the walk's first round read 0 and counted itself as a
                # screen: 「翻了 2 屏」 really meant 「一次换血空档 + 一屏内容」. Wait for the remount once
                # (bounded, 停止-aware) and do not spend a screen number on it. This waits on *read_ids*
                # rather than on :meth:`_wait_for_page`: that helper is the search route's patient mount
                # wait (``Config.PAGE_WAIT_TIMEOUT`` = 300 s, anchored on the search cards), so calling it
                # from the shared walk burned five minutes on an author grid whose cards it cannot see —
                # and threw the answer away, because this loop re-reads through ``read_ids`` anyway.
                waited_for_swap = True
                feed.wait_for(lambda: len(read_ids()), 1, timeout=self.SCROLL_WAIT, tick=1.0)
                continue
            screens += 1
            on_screen = list(read_ids())
            fresh = [aweme_id for aweme_id in on_screen if aweme_id not in done and aweme_id not in queued]
            logger.info(t('crawl.dy.round', i=screens, n=len(on_screen), fresh=len(fresh), done=self.collected()))
            for aweme_id in fresh:
                queued.add(aweme_id)
                pool.append(aweme_id)
            if len(pool) >= need:
                break
            if not scroll():
                # Two different endings, and only one of them is the site's. A list that wrote
                # 「暂时没有更多了」 is done; a scroll that moved nothing while the marker is absent is
                # our read of the page (a slow batch, a box that is not the list's box). Record
                # which, so ``author`` can license a site-attested drain but let the executor
                # convict the un-attested one (U1). Measured 2026-09-28: 最新发布 on 「IU」 ends at 14
                # cards *with* the marker, so a 50-row ask there is a named shortfall, not a bug.
                attested = self._list_says_end()
                self._list_end_attested = attested
                if attested:
                    logger.info(t('crawl.dy.noMore', screens=screens, cards=len(on_screen)))
                return pool, True, screens
        return pool, False, screens

    # ─── reading the page ─────────────────────────────────────────────

    def _title(self) -> str:
        with contextlib.suppress(Exception):
            return self.driver.title or ''
        return ''

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

    def _latch_risk_if_walled(self) -> None:
        """Name a 验证码中间页 as 风控 so the executor tells the user to back off, not re-save.

        The captcha this site answers a throttled session with is visible only in the tab
        title — invisible to the shared classifier — so ``open`` never latched ``risk_blocked``
        and a crawl that died on it used to read as a quiet zero (or a 「页面没到位」). Setting
        ``risk_blocked`` here routes it to ``run.riskControlled``. It is deliberately NOT
        ``login_wall``: re-saving a cookie that is actually fine is the advice this repo refuses.
        """
        if self._is_walled() and not self.login_wall:
            self.risk_blocked = True

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
        that has not been filled in yet — the skeleton rows this site mounts first —
        has no anchor and contributes nothing, which is why the mount wait counts these
        rather than counting nodes. *anchor* switches which list is read: the on-screen
        ``scroll-list`` (the page's arrival check) or a creator's own grid.
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

        The jump is **re-approached** until the grid grows, not taken once: a lazy douyin grid
        sometimes fetches nothing on the first bottom-touch and pages on the next. A single
        approach that grew nothing is therefore not the end of supply — and conceding there is
        exactly what made a 145-work profile stop at its first screen of 20 (measured live,
        pass 20261001-010707). Only after the whole :data:`SCROLL_WAIT` budget of approaches has
        grown nothing does this say False, and the caller still asks the *site*
        (:meth:`_list_says_end`) whether 「暂时没有更多了」 is really on screen before calling it
        ``site_end`` — a stalled read stays a named shortfall, never a quiet success.
        """
        before = len(set(self._grid_ids()))
        deadline = time.monotonic() + self.SCROLL_WAIT
        grew = False
        while not self.may_stop() and time.monotonic() < deadline:
            with contextlib.suppress(Exception):
                feed.jump_to_bottom(self.driver, self.PROFILE_GRID)
            settled = feed.wait_for(lambda: len(set(self._grid_ids())), before + 1, timeout=3.0, tick=0.5)
            if settled > before:
                grew = True
                break
        self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)
        return grew

    def _return_to_profile(self, url: str) -> None:
        """Come back to the creator's grid, for the same reason a search re-open does.

        The grid is a document, and opening one of its videos replaced it. Waiting for its first
        post again is not ceremony: a page that has not mounted has no ids to harvest, and the
        walk would read that as "this author has nothing more" — the exact silence
        :meth:`_published_count` exists to refuse.
        """
        self.open(url)
        self._dismiss_prompts()
        self._wait_for_grid(timeout=self.MOUNT_WAIT)

    def _list_says_end(self) -> bool:
        """Is the site's own end-of-list sentence on screen? Read from the rendered text.

        Checked only when a scroll failed to grow the list, so the cost is one body read at the moment the
        walk is already deciding whether to stop — and the marker is searched in the same text the user
        would see if he looked at the window, not in a node the build might rename.
        """
        return any(mark in self._body_text(limit=6000) for mark in self.LIST_END_MARKS)

    # ─── reading one video through the overlay (no navigation) ─────────

    def _modal_open(self) -> bool:
        """Is an overlay currently up? Active slide node, or a ``?modal_id=`` in the URL."""
        try:
            if self.driver.find_elements('css selector', self.ACTIVE_SLIDE):
                return True
        except Exception:
            return False
        return bool(self._active_modal_id())

    def _close_modal(self) -> bool:
        """Dismiss the overlay with ESC and VERIFY it went — a blind ESC is not "closed".

        Returns whether the overlay is gone. A stuck overlay would cover the next card, so the
        caller needs the true answer rather than hope; ESC is sent, a short bounded re-check polls
        for it, then ESC fires once more before giving up.
        """
        for _ in range(2):
            with contextlib.suppress(Exception):
                self.driver.find_element('css selector', 'body').send_keys(self.ESC_KEY)
            if feed.wait_for(lambda: not self._modal_open(), 1, timeout=3.0, tick=0.5):
                return True
        return not self._modal_open()

    def _find_card(self, aweme_id: str):
        """The profile-grid anchor whose OWN id equals *aweme_id* — matched by parsed id, not a
        substring, so a 19-digit id that merely prefixes another cannot return the wrong card."""
        for el in self.driver.find_elements('css selector', self.PROFILE_ANCHOR):
            with contextlib.suppress(Exception):
                match = self.VIDEO_HREF.search(str(el.get_attribute('href') or ''))
                if match and match.group(1) == str(aweme_id):
                    return el
        return None

    def _open_modal(self, aweme_id: str) -> bool:
        """Click this id's grid card so the overlay opens on it; no navigation to chase a missing card.

        Returns True only when the overlay is showing THIS id and its slide has painted. A card the
        grid has virtualised away is NOT recovered by re-navigating the profile (that is the storm
        this whole change removes) — it returns False, and the caller defers the id to a later round
        where scrolling may re-surface it.
        """
        card = self._find_card(aweme_id)
        if card is None:
            return False
        try:
            self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', card)
            card.click()
        except Exception:
            return False
        # The overlay swaps the URL to modal_id=<id> with no document navigation; wait only as long
        # as a slide should need to paint, and require it be THIS id, never a neighbour.
        return bool(
            feed.wait_for(
                lambda: self._active_modal_id() == str(aweme_id) and self._slide_painted(),
                1,
                timeout=self.MODAL_WAIT,
                tick=0.5,
            )
        )

    def _slide_painted(self) -> bool:
        """The active slide has real content (a caption or a counter) — one read, not two."""
        facts = self._active_facts()
        return bool(facts.get('desc') or facts.get('digg'))

    def _active_modal_id(self) -> str:
        """The id the overlay is currently showing (from ``?modal_id=``), or ''."""
        match = self.MODAL_ID_RE.search(self._current_url() or '')
        return match.group(1) if match else ''

    def _active_facts(self) -> dict:
        """Read the ACTIVE slide only — the neighbour ``feed-item`` is in the DOM and must not mix in.

        Counters carry by their own ``data-e2e`` names exactly as on the standalone page; 正文 comes
        from ``video-desc`` and 作者/发布时间 are parsed from ``video-info`` (``@name · date · #tags``).
        Returns an empty dict when there is no active slide (overlay not open / refused).
        """
        script = """
        var root = document.querySelector(arguments[0]);
        if (!root) { return {}; }
        function t(sel) {
          var el = root.querySelector(sel);
          return el ? (el.innerText || '').trim().replace(/\\s+/g, ' ') : '';
        }
        return {
          digg: t('[data-e2e="video-player-digg"]'),
          comment: t('[data-e2e="feed-comment-icon"]'),
          collect: t('[data-e2e="video-player-collect"]'),
          share: t('[data-e2e="video-player-share"]'),
          desc: t('[data-e2e="video-desc"]'),
          info: t('[data-e2e="video-info"]'),
          nickname: t('[data-e2e="feed-video-nickname"]')
        };
        """
        with contextlib.suppress(Exception):
            found = self.driver.execute_script(script, self.ACTIVE_SLIDE)
            if isinstance(found, dict):
                return found
        return {}

    def _read_profile_totals(self) -> tuple:
        """The account's 粉丝/获赞, read once off the profile page (the slide does not carry them).

        Account-level, so one read applies to every row; ``-1``-style absence becomes blank rather than
        a fabricated 0 — a number the page did not publish is not a count the account is claiming.
        """

        def _num(selector) -> str:
            element = self._element_or_none(selector)
            if element is None:
                return ''
            value = parse_count(self._node_text(element))
            return value if value else ''

        return _num(self.PROFILE_FANS), _num(self.PROFILE_LIKED)

    #: A full calendar date with a four-digit year: 2025年11月12日, 2026-08-04, 2026/8/4, 2026.8.4.
    #: Anchored at the start of a segment so trailing tags/prose are not captured.
    _DATE_RE = re.compile(r'^(\d{4}\s*[年./-]\s*\d{1,2}\s*[月./-]\s*\d{1,2}\s*日?)')
    # Relative stamps (「刚刚」/「3天前」) rot the moment they are stored, and a no-year 「2月25日」 is
    # not comparable against the year-bearing rows beside it — both are worse in a 发布时间 column
    # than a blank, which is the same rule that keeps a wrong number out of 播放数.

    @classmethod
    def _publish_from_info(cls, info: str) -> str:
        """The publish date out of ``video-info`` (``@作者 · 2025年11月12日 #标签…``) — or blank.

        The overlay has no dedicated publish-time node and its date is coarser than the standalone
        page. This accepts ONLY a year-bearing calendar date at the start of a segment; a hashtag
        (``#2025年高考``), a relative word (``刚刚``/``3天前``) or a year-less fragment (``2月25日``)
        is left out rather than filed as a timestamp — a half-token that sorts as a date is exactly
        the "right column name, wrong value" the repo refuses elsewhere.
        """
        for part in str(info or '').split('·'):
            token = part.strip()
            if token.startswith('#'):
                continue
            match = cls._DATE_RE.match(token)
            if match:
                return re.sub(r'\s+', '', match.group(1))[:40]
        return ''

    #: Returned by :meth:`_modal_row` when the overlay simply would not open on this card — the id is
    #: left unpaid so a later scroll round may re-surface it, instead of paying a navigation to chase it.
    DEFER = object()

    def _modal_row(self, aweme_id: str) -> dict | None:
        """One row read off the overlay, or :attr:`DEFER` if it would not open (never a navigation).

        An un-clickable card is DEFERRED — the grid virtualises, and the old walk re-navigated the
        profile to chase it, which is exactly the page-load storm this change removes. Opening the
        overlay on THIS id and reading the active slide is the only path here; ``get_detail`` keeps
        the standalone navigation for a single pasted URL, which has no grid to click.
        """
        if not self._open_modal(aweme_id):
            return self.DEFER
        try:
            facts = self._active_facts()
            shown = self._active_modal_id()
            if shown and shown != str(aweme_id):
                # The active slide is a different video than the card we asked for — a wrong row is
                # data, so refuse it; deferring lets the next look try this id again.
                logger.warning(t('crawl.dy.detailSwapped', i=aweme_id, shown=shown))
                return self.DEFER
            text = facts.get('desc') or ''
            publish = self._publish_from_info(facts.get('info') or '')
            nickname = (facts.get('nickname') or '').lstrip('@').strip()
            followers, liked = self._profile_totals
            if not text and not publish:
                # Identity is the caption or its date — an overlay still hydrating has neither, and an
                # empty row is not data no matter whose counters briefly rendered. CONSUMED (not
                # deferred): a slide that opened and stayed empty is that post having no text, not a
                # stuck card, so re-reading it next round would only spend the budget again.
                logger.warning(t('crawl.dy.detailNoIdentity', i=aweme_id))
                return None
            return {
                # 标题 is the caption on this site (there is no separate video title in the overlay);
                # never ``self._title()`` — that is the PROFILE document's title, not this video's.
                '标题': text[:120],
                '正文': text,
                '作者': nickname,
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
        finally:
            self._close_modal()

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
        if not self._wait_for_text(('发布时间',), timeout=20.0):
            self.check_login_wall(f'https://www.douyin.com/video/{aweme_id}')
            if self._is_walled() and not self.login_wall:
                # One row's wall, said as a wall. Measured 2026-09-28: a search of 「旅行攻略」 opened 39
                # detail pages and 15 came back 「验证码中间页」 — those ids are 图文 posts, whose route the
                # site refuses for this browser while the video pages round it answer perfectly (the card
                # itself always links ``/video/<id>``; the redirect to ``/note/<id>`` is what gives it away).
                # 「没有渲染出数据」 was therefore a wrong sentence about a real event, and the wrong sentence
                # invites the wrong repair. It is NOT the session either: latching ``login_wall`` here would
                # hand the whole node to 「COOKIE 可能过期」 while the next card crawls fine, so the flag is
                # read but not set, and the walk keeps going — this single video is refused, the crawl moves on.
                logger.warning(t('crawl.dy.detailWalled', i=aweme_id))
                return None
            # Two different complaints. "No data rendered" says the page arrived and
            # published nothing; "the page never finished loading" says the request is
            # still owed — which is what a slow connection actually produces, and the
            # row may well be there on a retry.
            logger.warning(
                t('crawl.dy.detailSlow', i=aweme_id) if not settled else t('crawl.dy.detailEmpty', i=aweme_id)
            )
            return None
        shown = douyin_id(self.driver.current_url or '')
        if shown and shown != str(aweme_id):
            # The address the browser ended on is not the video this row was asked for. Measured 2026-09-28
            # on ``7664182466315794939`` (a 图文 id): the walk landed on ``/video/7029265830722489634`` — a
            # real, fully-published video that has nothing to do with the search — and every field on that
            # page (文案, 发布时间, the four counters, the author) belonged to somebody else's post. Filed
            # anyway, the table would claim 「this is the video the list linked」 under a link that opens
            # another one; the user watched that happen on screen before any test described it. Read after
            # the wait and before anything is taken from the page, so the address, the settled content and
            # this judgement are all about the same document. Refused by name with both ids: a missing row
            # is a gap the walk can still be asked about, a wrong row is data.
            logger.warning(t('crawl.dy.detailSwapped', i=aweme_id, shown=shown))
            return None
        facts = self._driver_facts()
        info_lines = [line.strip() for line in str(facts.get('info') or '').split('\n') if line.strip()]
        text = info_lines[0] if info_lines else ''
        publish = _clean_publish(facts.get('publish'))
        related = _author_from_related(str(facts.get('related') or ''))
        # Measured twice on 2026-09-28, and the second reading corrected the first: the creator's name is
        # the text of ``[data-e2e="user-info"] a[href*="/user/<sec_uid>"]``, and the ``related-video`` block
        # *begins* with that same block (``白水鉴心 |  | 粉丝4399获赞341.9万 |  | 关注``), so it is the fallback
        # that also carries the two account totals. The morning's read — that the block had stopped
        # rendering — was taken on a page still hydrating, which is the same condition that filled 作者 with
        # a rail creator and let an empty row through the old guard; hence the scoping in
        # :meth:`_driver_facts` and the identity test below.
        author = str(facts.get('author') or '').strip() or related[0]
        followers, liked = related[1], related[2]
        if not text and not publish:
            # Identity is the caption or its date — **not** the author. Measured 2026-09-28 (live cell A1
            # and the probe behind it): a page still hydrating handed over an id, four zero counters and a
            # 作者 read off the recommendation rail, and this guard let it through because ``author`` was
            # non-empty; the row was then counted as 「当前有效数据: 7 条」 and consumed a slot of the user's
            # target. An empty row is not data no matter whose name is on the page, and the walk says so
            # rather than the export having to explain the line afterwards.
            logger.warning(t('crawl.dy.detailNoIdentity', i=aweme_id))
            return None
        return {
            '标题': (self._title().removesuffix(' - 抖音').strip() or text)[:120],
            '正文': text,
            '作者': author,
            # The creator's totals come from that one block and nowhere else on the page: measured, the
            # words 粉丝/获赞 also appear as bare nav labels with no figure beside them, so a 0 read from
            # one of those would be a count saying 「这个账号没人关注」 — a wrong number under a plausible
            # column name, which is the same reason 播放数 was never added. Blank is therefore the answer
            # for "the page did not publish it", and :func:`_author_from_related` fills both when it did.
            '粉丝数': followers or '',
            '获赞数': liked or '',
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
        function author() {
          // The creator block, by its own name. A document-wide ``a[href*=\"/user/\"]`` scan is NOT that:
          // measured 2026-09-28 on a page still hydrating, the first bare sec_uid anchor with text on the
          // document belonged to the recommendation rail, so the row was stored with a stranger's shop
          // account as its 作者 (「青小鲜三门青蟹 海鲜礼包」 on a video by 白水鉴心). The rail is rendered
          // before the header on a slow page, so the order that saves the caption's owner can also hand
          // over somebody else's name — and a wrong figure under a plausible column is the harm this
          // repo refuses elsewhere (see why there is no 播放数).
          var scope = document.querySelector('[data-e2e="user-info"]');
          if (!scope) return '';
          var links = scope.querySelectorAll('a[href*="/user/"]');
          for (var i = 0; i < links.length; i++) {
            var href = links[i].href || '';
            var name = (links[i].innerText || '').trim();
            if (name && /^https:\\/\\/www\\.douyin\\.com\\/user\\/[A-Za-z0-9_-]{20,}$/.test(href)) return name;
          }
          return '';
        }
        return {
          digg: txt('[data-e2e="video-player-digg"]'),
          comment: txt('[data-e2e="feed-comment-icon"]'),
          collect: txt('[data-e2e="video-player-collect"]'),
          share: txt('[data-e2e="video-player-share"]'),
          info: txt('[data-e2e="detail-video-info"]'),
          publish: txt('[data-e2e="detail-video-publish-time"]'),
          author: author(),
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
