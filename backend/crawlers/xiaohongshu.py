import contextlib
import logging
import re
import time
from urllib.parse import quote, urljoin

from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from i18n import t

from .base import UNDER_TARGET, Crawler, as_index
from .engine import feed
from .engine.counters import parse_count

logger = logging.getLogger(__name__)


class XiaohongshuCrawler(Crawler):
    """Scrapes xiaohongshu's search results and the notes behind them.

    The search grid is an infinite scroll of ``section.note-item`` cards, and
    every card already carries the note link, title, author and like count. The
    note *body* only exists on the detail page, and a detail page costs a
    navigation — so the crawl harvests cards as they render, and reads the
    detail in a **throwaway tab**: the search page keeps its scroll offset, the
    crawl emits a row per note as soon as that note is done, and it stops the
    moment the target is met instead of pre-collecting a link list.

    A note link is only openable with its ``xsec_token`` (without it the site
    answers 安全限制 / 404), so the tokenised URL is kept as ``笔记链接`` and the
    session-independent note id goes into ``笔记ID`` for cross-run comparison.
    """

    domain = 'www.xiaohongshu.com'
    # explore (not /login): with valid cookies it renders content immediately for a
    # cookie refresh; expired sessions get xiaohongshu's own login prompt there.
    login_url = 'https://www.xiaohongshu.com/explore'

    CARD_SELECTOR = 'section.note-item, .note-item'
    LINK_SELECTORS = ('a.cover', '.footer .title a', 'a[href*="/search_result/"]')
    NOTE_WAIT = 2.5
    CARD_WAIT = 1.5
    SCROLL_STEPS = 3
    STUCK_ROUNDS = 3
    POLITE_BASE = 0.9
    POLITE_SPREAD = 0.3
    #: How many of a note's comments a search row carries as a preview. It was a
    #: literal 5 buried in the scraper; the node parameter overrides it, because
    #: 0 is a legitimate choice (skip the panel entirely, which is also the
    #: fastest crawl) and a large one is what "I want the comments in the table"
    #: means. The note's own 评论数 is a different thing and is always kept.
    DEFAULT_COMMENT_PREVIEW = 5

    def search(self, keyword: str, target_count: int = 50, **_kwargs):
        self.comment_preview = self._comment_preview_of(_kwargs)
        resume = self.resume_of(_kwargs)
        have = self.collected()
        if have:
            logger.info(t('crawl.resume_have', n=have))
        if have >= target_count:
            logger.info(t('crawl.xhs.target_reached', n=target_count))
            return self.results()

        encoded = quote(keyword)
        url = f'https://www.xiaohongshu.com/search_result?keyword={encoded}&source=web_explore_feed&type=51'
        logger.info(t('crawl.xhs.start', kw=keyword, n=target_count))
        # ``open`` and not ``driver.get``: this is the crawl's first navigation, and a
        # renderer that answers late is a page still building rather than a failed run.
        # Straight from the driver that moment arrived as a raw
        # ``TimeoutException: Timed out receiving message from renderer`` out of the node,
        # instead of the honest ``crawl.xhs.page_timeout`` line the poll below writes.
        self.open(url)
        logger.info(t('crawl.xhs.url', url=url))
        # Adaptive: the grid renders as soon as the API answers, so a fixed
        # 15 s block is pure loss on a warm session.
        found = self._wait_for_count(self._card_count, 1, timeout=self.NOTE_WAIT * 4)
        # Stop on EITHER refusal, not just a login redirect. xiaohongshu walls a
        # replayed session (docs red line: "walled within minutes"), and it answers
        # that with a 风控 page that sets ``risk_blocked`` but is NOT a login page —
        # so the old ``check_login_wall``-only test let the crawl fall through,
        # scroll a zero-card grid, and file an empty table that read as "this keyword
        # found nothing". zhihu and douyin already gate on ``login_wall or
        # risk_blocked``; this is the same rule.
        if not found and self.check_intercept(url) != 'ok':
            return self.results()
        logger.info(t('crawl.xhs.page_ready') if found else t('crawl.xhs.page_timeout'))

        # The resume identity is the session-independent 笔记ID, seeded from the rows this node already
        # stored — NOT the tokenised link (a later scroll can hand the same note with a different token,
        # so keying on the token re-pays it), and NOT a list inside the cursor. §6 U5: a cursor records
        # position, not content — the old ``links=sorted(seen)`` meant one failed note was silently
        # skipped on *every* later resume (the wechat/youtube fixes removed the same shape).
        seen: set[str] = self._collected_ids()
        self.mark_position(keyword=keyword, scanned=as_index(resume.get('scanned')), done=have)
        logger.info(t('crawl.xhs.links', n=len(seen)))

        # The grid is a VIRTUALISED feed (measured 2026-09-29: 22 cards at first read, then a
        # flat ~8 as scrolling swaps card *identities* rather than appending — new 笔记ID enter
        # the DOM, old ones leave). So the walk is keyed on ``_window_key`` — the ids ON SCREEN,
        # which turn over while the node count does not — and the ``seen`` set filed into it by
        # :meth:`_note_row` is what de-dupes each screen read whole. Keying on ``_card_count``
        # growth is §6 U3's silent under-collect: a recycling feed looks exhausted after one
        # screen and stops. This is the same ``feed.walk_feed`` zhihu/bilibili/X run on, so the
        # walk lives in one place (it used to be a second copy here).
        def mark(_progress):
            # ``scanned`` is a running count of distinct notes consumed — a POSITION, never the
            # id list (the rows themselves are the resume skip-set; §6 U5).
            self.mark_position(scanned=len(seen), done=self.collected())

        result = feed.walk_feed(
            self._mounted_cards,
            lambda card, index: self._note_row(card, seen),
            self._emit_note,
            scroll=lambda: self.scroll_down(steps=self.SCROLL_STEPS),
            target=target_count,
            collected=self.collected,
            window=self._window_key,
            mark=mark,
            stopped=lambda: self.login_wall or self.risk_blocked or self.may_stop(),
            stuck_rounds=self.STUCK_ROUNDS,
            settle_wait=self.CARD_WAIT,
        )

        # U1 migration: xiaohongshu's grid publishes NO total and NO end-of-list marker the code
        # can read, so a walk that stopped growing below the ask NEVER proves supply ran out — a
        # soft throttle mimics it exactly (docs/crawler_notes.md). A shortfall is therefore filed
        # ``UNDER_TARGET`` (the executor refuses it by name and keeps it resumable) rather than
        # left ``end_reason=None``, which used to let it settle clean. 停止 / a wall / a risk
        # bounce are NOT convicted here: the executor raises 风控 on ``risk_blocked``, and 停止 is
        # counted in its own bucket — this gate must only fire for an unexplained shortfall.
        # ``walk_feed``'s own ``result.stopped_reason`` is a self-summary of our loop and can never
        # license this — ``Crawler.note_end`` refuses a non-site reason by construction.
        if self.collected() < target_count and not (self.login_wall or self.risk_blocked or self.may_stop()):
            self.note_end(UNDER_TARGET, scanned=result.scanned, kept=result.kept, refused=result.refused)

        logger.info(t('crawl.xhs.collect_done', n=len(seen)))
        logger.info(t('crawl.xhs.finished', n=self.collected()))
        return self.results()

    def _mounted_cards(self) -> list:
        return self.driver.find_elements(By.CSS_SELECTOR, self.CARD_SELECTOR)

    def _window_key(self) -> tuple:
        """The ids currently on screen — the only motion signal a recycled grid gives.

        Selenium wrapper objects are rebuilt on every query, so ``id(element)`` would always look
        changed and the walk would never notice an exhausted list; the 笔记IDs are what actually
        identify the content, and they turn over while the node count holds flat.
        """
        keys = []
        for card in self._mounted_cards():
            link = self._card_link(card)
            keys.append(self._note_id(link) or link)
        return tuple(keys)

    def _note_row(self, card, seen: set) -> dict | None:
        """Read one mounted card once into a row, dropping anything already collected.

        The detail is read in a throwaway tab (``keep_page=True``) so the search grid keeps its
        scroll offset while the walk pages. A card already in ``seen`` is skipped BEFORE its detail
        navigation, so re-reading a mounted card that came back with a fresh ``xsec_token`` costs no
        re-pay. Returns ``None`` for a card with no link or an already-seen note; ``walk_feed``
        counts those as refused and moves on.
        """
        link = self._card_link(card)
        if not link:
            return None
        # Dedupe on the session-independent 笔记ID, not the tokenised link: the grid re-promotes the
        # same note with a fresh token, so keying on the link would re-read (and re-pay) it.
        key = self._note_id(link) or link
        if key in seen:
            return None
        try:
            item = self._scrape_card(card, link)
            detail = self._read_note(link, keep_page=True)
        except Exception as e:
            # One unopenable note costs its row, not the crawl: the same per-card guard the hand-rolled
            # loop had. A note that threw before ``seen.add`` is left OUT of ``seen``, so a later round
            # (the grid re-promotes it) can still recover it — 不漏采 over a transient failure.
            logger.error(t('crawl.xhs.note_error', err=e), exc_info=True)
            return None
        if detail:
            item.update({k: v for k, v in detail.items() if v not in ('', 0, None, [])})
        seen.add(key)
        return item

    def _emit_note(self, row: dict) -> bool:
        """The sink :func:`walk_feed` feeds each built row through — and the per-note console line.

        Dedupe happens here, not in :meth:`_note_row`: ``walk_feed`` calls ``emit`` itself, so calling
        it inside the scrape would file every note twice. The store answers whether the row was kept,
        which is what the 「采到一篇」 line reports.
        """
        kept = self.emit(row)
        if kept:
            title_preview = row['标题'][:30] if row['标题'] else t('crawl.xhs.untitled')
            logger.info(t('crawl.xhs.note_ok', title=title_preview))
        else:
            logger.debug(t('crawl.xhs.note_dup', url=row['笔记链接']))
        return kept

    # ─── card harvest (interleaved with the scroll) ──────────────────

    def _card_count(self) -> int:
        return len(self.driver.find_elements(By.CSS_SELECTOR, self.CARD_SELECTOR))

    def _card_link(self, card) -> str:
        for sel in self.LINK_SELECTORS:
            try:
                href = card.find_element(By.CSS_SELECTOR, sel).get_attribute('href')
            except Exception:
                continue
            if href:
                return urljoin(f'https://{self.domain}', href)
        return ''

    def _scrape_card(self, card, link: str) -> dict:
        return {
            '笔记链接': link,
            '笔记ID': self._note_id(link),
            '标题': self._text_of(card, '.footer .title') or self._text_of(card, '.title'),
            '作者': self._text_of(card, '.author .name') or self._text_of(card, '.name'),
            '点赞数': parse_count(self._text_of(card, '.like-wrapper .count')),
            '正文': '',
            '发布时间': '',
            '收藏数': 0,
            '评论数': 0,
            '评论列表': [],
        }

    @classmethod
    def _comment_preview_of(cls, kwargs: dict) -> int:
        """The node's 评论预览数, defensively: the panel sends a string, and a
        negative or nonsense value means "use the default", never "open the
        whole panel" and never a crash inside the crawl."""
        raw = (kwargs or {}).get('comment_preview')
        if raw is None or str(raw).strip() == '':
            return cls.DEFAULT_COMMENT_PREVIEW
        try:
            value = int(float(str(raw).strip()))
        except (TypeError, ValueError):
            return cls.DEFAULT_COMMENT_PREVIEW
        return value if value >= 0 else cls.DEFAULT_COMMENT_PREVIEW

    @staticmethod
    def _note_id(link: str) -> str:
        m = re.search(r'/(?:search_result|explore|item)/([0-9a-f]{16,})', link or '')
        return m.group(1) if m else ''

    def _collected_ids(self) -> set:
        """The 笔记IDs this crawl already holds, read off its stored rows.

        A resumed run is seeded with everything the node already stored, so the rows ARE the skip-set.
        The cursor carries only the card index (position); ids used to ride in it as a ``links`` list,
        which is §6 U5's permanent silent-skip-on-resume — the same fix paid for on xiaohongshu's own
        navigation and on wechat/youtube's cursors.
        """
        return {str(row.get('笔记ID')) for row in self.results() if row.get('笔记ID')}

    # ─── note detail ─────────────────────────────────────────────────

    def _read_note(self, url: str, keep_page: bool = False) -> dict | None:
        """Scrape one note. With *keep_page* the search tab survives.

        Opening the note in a second tab is what lets the crawl emit while the
        grid is still scrolling: the search page never reloads, so its virtualised
        card list and scroll offset are intact when the tab is closed again.
        """
        logger.info(t('crawl.xhs.detail_visit', url=url))
        search_handle = self.driver.current_window_handle if keep_page else None
        opened_tab = False
        if keep_page:
            try:
                self.driver.switch_to.new_window('tab')
                opened_tab = True
            except Exception as e:
                logger.debug(t('crawl.xhs.note_error', err=e))
                search_handle = None
        try:
            return self._scrape_note(url)
        finally:
            if opened_tab:
                with contextlib.suppress(Exception):
                    self.driver.close()
                    self.driver.switch_to.window(search_handle)

    def _scrape_note(self, url: str) -> dict | None:
        # Same reason as the search page: this navigation is where a note row is paid
        # for, and a driver that cannot settle used to abort the whole crawl with a
        # stack trace rather than lose the one row. But judge=False: a note whose
        # xsec_token has aged (or was stripped) answers 安全验证, and that is THIS link
        # dead, not the session refused. Latching risk_blocked off one bad token would
        # stop the harvest and turn a run into a resume (U55's shape) — the grid re-checks
        # the session on its own, so a single walled detail is read with the *non-latching*
        # verdict and named dead, while the crawl keeps collecting the rest.
        self.open(url, judge=False)
        if self.verdict(url) != 'ok':
            logger.info(t('crawl.xhs.deadNote', url=url))
            return None
        try:
            WebDriverWait(self.driver, int(self.NOTE_WAIT * 6)).until(
                ec.presence_of_element_located((By.CSS_SELECTOR, '.title, #detail-title'))
            )
            logger.info(t('crawl.xhs.detail_ready'))
        except TimeoutException:
            # Re-read after the wait: a session that died mid-load shows a wall only now.
            if self.verdict(url) != 'ok':
                logger.info(t('crawl.xhs.deadNote', url=url))
                return None
            logger.warning(t('crawl.xhs.detail_timeout'))
            return None

        title = self._wait_for_text('#detail-title, .note-content .title, .title')
        if not title:
            logger.debug(t('crawl.debug.title_missing'))
        content = self._wait_for_text('#detail-desc .note-text, .desc .note-text, #detail-desc')
        logger.info(t('crawl.xhs.content_len', n=len(content)))

        author = self._wait_for_text('.author-container .name, .author-wrapper .name, .username')
        if not author:
            logger.debug(t('crawl.debug.author_missing'))
        logger.info(t('crawl.xhs.author', author=author))

        raw_time = self._text_of(self.driver, '.date')
        publish_time, region = self._split_date_location(raw_time)
        logger.info(t('crawl.xhs.pub_time', time=publish_time))

        # The engage bar is the note's own counters; a bare .like-wrapper also
        # matches every comment's like button, which used to report '1'.
        like_count = self._engage_count('like-wrapper')
        collect_count = self._engage_count('collect-wrapper')
        comment_count = self._engage_count('chat-wrapper')
        logger.info(t('crawl.xhs.metrics', likes=like_count, favs=collect_count, comments=comment_count))

        comments = self.extract_comments(max_comments=getattr(self, 'comment_preview', self.DEFAULT_COMMENT_PREVIEW))
        logger.info(t('crawl.xhs.comment_count', n=len(comments)))

        return {
            '笔记链接': url,
            '笔记ID': self._note_id(url),
            '标题': title,
            '正文': content,
            '作者': author,
            '作者链接': self._first_href('.author-container a, .author-wrapper a'),
            '发布时间': publish_time,
            '发布地区': region,
            '点赞数': like_count,
            '收藏数': collect_count,
            '评论数': comment_count,
            '图片数': len(self.driver.find_elements(By.CSS_SELECTOR, '.media-container img, .note-slider img')),
            '话题': ' | '.join(self._topics(content)),
            '评论列表': comments,
        }

    def _wait_for_text(self, selector: str, polls: int = 6) -> str:
        """Poll a field until it has text — the note body hydrates piecewise.

        The author name in particular renders after the title, so reading it
        once right after the title appeared used to return ''. Poll-counted
        rather than clock-based, so a fake driver costs nothing.
        """
        text = self._text_of(self.driver, selector)
        for _ in range(max(0, polls - 1)):
            if text:
                break
            time.sleep(0.2)
            text = self._text_of(self.driver, selector)
        return text

    def _engage_count(self, wrapper: str) -> int:
        """One number out of the note's own engage bar.

        Scoped from the tightest container outwards: ``.like-wrapper .count``
        on its own also matches every comment's like button, and reading the
        first of those reported a comment's '1' as the note's like count.
        """
        for scope in ('.engage-bar .buttons .left', '.engage-bar', '.interactions'):
            try:
                roots = self.driver.find_elements(By.CSS_SELECTOR, scope)
            except NoSuchElementException:
                roots = []
            for root in roots:
                text = self._text_of(root, f'.{wrapper} .count')
                if text:
                    return parse_count(text)
        return self._count_in(f'.{wrapper} .count')

    def _count_in(self, selector: str) -> int:
        try:
            els = self.driver.find_elements(By.CSS_SELECTOR, selector)
        except NoSuchElementException:
            return 0
        for el in els:
            text = self._node_text(el)
            if text:
                return parse_count(text)
        return 0

    def _first_href(self, selector: str) -> str:
        try:
            els = self.driver.find_elements(By.CSS_SELECTOR, selector)
        except NoSuchElementException:
            return ''
        for el in els:
            href = el.get_attribute('href') or ''
            if href:
                return href
        return ''

    @staticmethod
    def _split_date_location(raw: str) -> tuple[str, str]:
        """'09-10 辽宁' → ('09-10', '辽宁'); '编辑于 3天前 海南' likewise.

        The site appends the IP region to the same node, which used to land in
        the date column and made every downstream time filter useless.
        """
        text = (raw or '').strip()
        if not text:
            return '', ''
        m = re.search(r'((?:编辑于\s*)?(?:\d{4}-)?\d{1,2}-\d{1,2}|\d+\s*(?:分钟|小时|天)前|昨天|今天)', text)
        if not m:
            return text, ''
        publish = m.group(1).strip()
        region = text[m.end() :].strip()
        return publish, region

    @staticmethod
    def _topics(content: str) -> list:
        """'#tag' tokens of the note body, in order, without the leading #."""
        return list(dict.fromkeys(re.findall(r'#([^#\s\[\]]{1,40})', content or '')))

    def _extract_count(self, selector: str) -> int:
        return self._count_in(selector)

    def extract_comments(self, max_comments: int = 5):
        if max_comments <= 0:
            # Asking for no comments must cost nothing. Left as it was, a
            # preview of 0 still waited 10 s per note for a panel nobody would
            # read, so the fastest crawl setting was the slowest one.
            logger.debug(t('crawl.xhs.comment_skip'))
            return []
        logger.info(t('crawl.xhs.comment_start', n=max_comments))
        comments = []
        try:
            comment_items = WebDriverWait(self.driver, 10).until(
                ec.presence_of_all_elements_located((By.CSS_SELECTOR, '.comment-item, .parent-comment'))
            )
            logger.info(t('crawl.xhs.comment_found', n=len(comment_items)))
        except TimeoutException:
            logger.debug(t('crawl.debug.comments_missing'))
            return comments

        for idx, item in enumerate(comment_items[:max_comments]):
            try:
                comment_author = self._text_of(item, '.name')
                comment_content = self._text_of(item, '.content .note-text') or self._text_of(item, '.content')
                like_count = parse_count(self._text_of(item, '.like .count, .like-wrapper .count'))
                comment_time = self._text_of(item, '.date')

                if comment_content:
                    comments.append(
                        {
                            '评论者': comment_author,
                            '评论内容': comment_content,
                            '点赞数': like_count,
                            '评论时间': comment_time,
                        }
                    )
                    logger.debug(
                        t(
                            'crawl.debug.comment_item',
                            i=idx + 1,
                            author=comment_author,
                            text=comment_content[:20],
                        )
                    )
            except Exception as e:
                logger.error(t('crawl.xhs.comment_error', i=idx + 1, err=e))

        logger.info(t('crawl.xhs.comment_done', n=len(comments)))
        return comments

    def get_detail(self, url: str) -> dict | None:
        return self._scrape_note(url)
