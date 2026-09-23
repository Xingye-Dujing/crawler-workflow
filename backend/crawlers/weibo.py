import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from i18n import t

from .base import Crawler, as_index
from .engine.counters import parse_count

logger = logging.getLogger(__name__)

# Log strings this crawler needs that the catalog does not have yet.
# ``backend/i18n.py`` is outside this change's ownership, so the wanted keys are
# reported alongside the literal:
#   crawl.weibo.target_reached  {n}
_LOG_TARGET = '已达到目标数量 {n} 条，停止翻页'


class WeiboCrawler(Crawler):
    """Scrapes the s.weibo.com keyword search.

    Three facts about this platform shaped the crawler, all of them measured
    against the live site rather than assumed:

    - The saved cookies are exported from ``weibo.com``, but the feed is served
      by ``s.weibo.com`` and needs to be planted there too (see
      :meth:`Crawler._load_cookies` and :attr:`cookie_domains`).
    - **The QR screen on entry is a staged illusion.** s.weibo.com first answers
      a search request with a ``passport.weibo.com/sso/signin`` frame
      ("扫描二维码登录"), and a session that holds a valid ``SUB`` cookie is
      bounced back to the logged-in feed a moment later. A wall test taken at
      the instant ``get()`` returns catches that intermediate frame and aborts a
      crawl that was about to produce rows — so :meth:`_await_search_page`
      waits for a terminal state (cards, the
      no-result plate, or a *persistent* passport page) before judging. The
      same lesson applies to paging: scrape what is on screen first, and only
      ask for ``page=2`` and deeper when the target genuinely still needs rows.
    - The feed is server-rendered: scrolling fetches nothing new, so "more data"
      means a deeper page or a narrower time window — and each extra request
      costs wall risk. Hence the target cutoff, the page ceiling and the
      jittered pauses between requests.
    """

    domain = 'weibo.com'
    # The search host gets its own cookie pass: a cookie scoped to
    # ``.weibo.com`` is accepted on weibo.com and simply not offered to
    # s.weibo.com until the browser has been there once.
    cookie_domains = ('s.weibo.com',)
    # Open the site itself, not the sign-in page: with saved cookies this lands
    # on the logged-in feed (cookies refresh = press Done immediately), while an
    # expired session is redirected to the passport wall by weibo itself. The old
    # passport URL showed a QR wall even with a perfectly valid cookie.
    login_url = 'https://weibo.com/'

    CARD_SELECTOR = '.card-wrap'
    # Rows per feed page is ~9-10, so this ceiling is what a keyword crawl can
    # reach before the wall becomes the likely answer.
    MAX_PAGES_PER_WINDOW = 5
    # Paging is meaningless inside a time window: the window is already narrow.
    PAGE_WAIT = 3.0
    POLITE_BASE = 1.0
    POLITE_SPREAD = 0.35

    # An hourly-window crawl loads one page per hour of the range, so two years
    # would be ~17 500 page loads — a run that never ends. Past this many
    # windows the range is refused instead of started.
    MAX_HOURLY_WINDOWS = 720

    # A date-range crawl without a target wants every window it was given.
    DEFAULT_TARGET = 10**9

    @staticmethod
    def _parse_date(value: str) -> datetime:
        try:
            return datetime.strptime(str(value).strip(), '%Y-%m-%d')
        except ValueError as e:
            # The field is free text ("2026-01-01"); a typo used to crash the
            # node with a bare strptime error.
            raise ValueError(t('crawl.weibo.bad_date', value=value)) from e

    def search(self, keyword: str, start_time: str = None, end_time: str = None, target_count=None, **_kwargs):
        resume = self.resume_of(_kwargs)
        stored = resume.get('urls')
        # This crawl is a walk over a URL list, so the list plus the index into
        # it *is* the resume point. It is reused when the keyword still matches;
        # otherwise it is rebuilt from the (validated) dates.
        if isinstance(stored, list) and stored and resume.get('keyword') == keyword:
            urls = [str(u) for u in stored]
            logger.info(t('crawl.resume_urls', n=len(urls)))
        else:
            urls = self._build_urls(keyword, start_time, end_time)

        have = self.collected()
        if have:
            logger.info(t('crawl.resume_have', n=have))
        target = self.DEFAULT_TARGET if not target_count else int(target_count)

        start_index = as_index(resume.get('url_index'))
        total_urls = len(urls)
        self.mark_position(keyword=keyword, urls=urls, url_index=start_index, url_total=total_urls, done=have)

        for idx, url in enumerate(urls, start=1):
            if idx <= start_index:
                continue
            if self.collected() >= target:
                logger.info(_LOG_TARGET.format(n=target))
                break
            logger.info('')
            logger.info('=' * 80)
            logger.info(t('crawl.weibo.processing', i=idx, total=total_urls))
            logger.info(t('crawl.weibo.url', url=url))
            logger.info('=' * 80)

            # The card/page cursor restarts per window: it only means anything
            # against the page that is loaded right now.
            self.mark_position(url_index=idx, card_index=0, page_index=0, done=self.collected())
            page_data = self._scrape_single_search(url, target)
            logger.info(t('crawl.weibo.link_done', i=idx, n=len(page_data)))
            logger.info(t('crawl.weibo.accumulated', n=self.collected()))
            # Position after each window: a kill here costs at most the window
            # in flight, never the windows already walked.
            self.mark_position(url_index=idx, done=self.collected())

            if self.login_wall:
                # Every further window would meet the same wall; stopping is
                # both faster and kinder to the session than walking into it
                # another hundred times.
                break

            if idx < total_urls and self.collected() < target:
                self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)

        return self.results()

    def _build_urls(self, keyword: str, start_time: str, end_time: str) -> list:
        if start_time or end_time:
            # One bound alone used to be ignored silently, which quietly ran a
            # completely different (unbounded) search.
            if not (start_time and end_time):
                raise ValueError(t('crawl.weibo.need_both_dates'))
            start = self._parse_date(start_time)
            end = self._parse_date(end_time)
            if end <= start:
                raise ValueError(t('crawl.weibo.bad_range', start=start_time, end=end_time))
            urls = self._generate_hourly_urls(keyword, start, end)
            logger.info(t('crawl.weibo.keyword', kw=keyword))
            logger.info(t('crawl.weibo.range', start=start.strftime('%Y-%m-%d'), end=end.strftime('%Y-%m-%d')))
            logger.info(t('crawl.weibo.links', n=len(urls)))
            return urls
        encoded = quote(keyword)
        logger.info(t('crawl.weibo.keyword_plain', kw=keyword))
        return [f'https://s.weibo.com/weibo?q={encoded}&typeall=1&suball=1&Refer=g']

    def _generate_hourly_urls(self, keyword: str, start: datetime, end: datetime):
        windows = int((end - start).total_seconds() // 3600) + 1
        if windows > self.MAX_HOURLY_WINDOWS:
            raise ValueError(t('crawl.weibo.range_too_wide', n=windows, max=self.MAX_HOURLY_WINDOWS))
        urls = []
        cur = start
        while cur < end:
            nxt = min(cur + timedelta(hours=1), end)
            ss = cur.strftime('%Y-%m-%d-%H')
            es = nxt.strftime('%Y-%m-%d-%H')
            encoded = quote(keyword)
            urls.append(
                f'https://s.weibo.com/weibo?q={encoded}&typeall=1&suball=1&timescope=custom%3A{ss}%3A{es}&Refer=g'
            )
            cur = nxt
        return urls

    # ─── one search window ────────────────────────────────────────────

    def _scrape_single_search(self, base_url: str, target: int) -> list:
        """Harvest one search window: the feed that is already loaded first.

        Returns the rows this window produced. The page walk is a fallback for
        a keyword feed that has not reached the target yet, never the first
        thing the crawl does — re-reading the loaded page as ``page=1`` is the
        request that gets the session thrown at the login wall.
        """
        scraped = []
        try:
            logger.info(t('crawl.weibo.visiting', url=base_url))
            logger.info(t('crawl.weibo.waiting'))
            if not self._await_search_page(base_url):
                return scraped
            scraped.extend(self._harvest(target))
            if self.collected() >= target or not self._may_page(base_url):
                return scraped

            total_pages = min(self._get_total_pages(), self.MAX_PAGES_PER_WINDOW)
            logger.info(t('crawl.weibo.total_pages', n=total_pages))
            page_url = self._page_url(base_url)
            for page_num in range(2, total_pages + 1):
                if self.collected() >= target:
                    logger.info(_LOG_TARGET.format(n=target))
                    break
                # Politeness *between* requests: this is the path that reaches
                # s.weibo.com's rate limiter, so the pause is the fix.
                self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)
                logger.info(t('crawl.weibo.page_crawling', i=page_num, total=total_pages))
                if not self._await_search_page(f'{page_url}{page_num}'):
                    break
                self.mark_position(page_index=page_num, card_index=0)
                before = self.collected()
                found = self._harvest(target)
                scraped.extend(found)
                if self.collected() == before:
                    logger.warning(t('crawl.weibo.page_empty', i=page_num))
                    break
                logger.info(t('crawl.weibo.page_done', i=page_num, n=len(found), total=self.collected()))
            return scraped
        except Exception as e:
            logger.error(t('crawl.weibo.link_error', err=e), exc_info=True)
            return scraped

    def _await_search_page(self, url: str) -> bool:
        """Navigate to a search URL and wait for s.weibo.com to settle.

        The platform answers a fresh search request with a passport QR screen
        first, then — when the session really holds a valid cookie — bounces the
        browser back to the logged-in feed a moment later. That bounce is an
        illusion the site stages, not a wall: a URL read taken the instant
        ``get()`` returns lands on the intermediate frame and kills a crawl that
        was about to produce rows. So poll for one of the *terminal* states
        before judging anything:

        - feed cards present → crawlable, return True;
        - the explicit "no result" plate → a genuine empty window, False;
        - timeout with cards never arriving → only now consult the login wall
          (a truly dead session parks on passport forever), False either way.

        Works identically headless and visible; both modes show the same DOM
        transition, the visible one just lets the user watch it happen.
        """
        self.driver.get(url)
        poll = 0.5
        rounds = max(1, int(self.PAGE_WAIT * 3 / poll))
        for _ in range(rounds):
            if self._element_or_none(self.CARD_SELECTOR) is not None:
                logger.info(t('crawl.weibo.page_loaded'))
                return True
            if self._element_or_none('.card-no-result') is not None:
                logger.info(t('crawl.weibo.no_result'))
                return False
            time.sleep(poll)
        if self.check_login_wall(url):
            return False
        logger.warning(t('crawl.weibo.page_timeout'))
        return False

    def _may_page(self, base_url: str) -> bool:
        """Paging exists only on an open keyword feed.

        A ``timescope`` window is already narrow — everything it holds is on the
        page it renders — so a deeper request there buys nothing and spends wall
        risk for nothing.
        """
        return 'timescope=' not in base_url

    @staticmethod
    def _page_url(base_url: str) -> str:
        cleaned = re.sub(r'[?&]page=\d+', '', base_url)
        return f'{cleaned}{"&" if "?" in cleaned else "?"}page='

    # ─── card harvest ─────────────────────────────────────────────────

    def _harvest(self, target: int) -> list:
        """Scrape and emit the cards of whichever page is loaded right now.

        Rows go to the sink per card, so they are on disk before the next card
        is looked at, and the window's card cursor lets a kill inside a window
        resume at the card it died on.
        """
        cards = self.driver.find_elements(By.CSS_SELECTOR, self.CARD_SELECTOR)
        logger.info(t('crawl.weibo.page_cards', n=len(cards)))
        start = min(as_index(self.position.get('card_index')), len(cards))
        kept = []
        for idx, card in enumerate(cards[start:], start + 1):
            if self.collected() >= target:
                logger.info(_LOG_TARGET.format(n=target))
                break
            try:
                item = self._scrape_card(card, idx)
            except Exception:
                logger.warning(t('crawl.weibo.card_error', i=idx), exc_info=True)
                self.mark_position(card_index=idx, done=self.collected())
                continue
            if item is not None and self.emit(item):
                kept.append(item)
            self.mark_position(card_index=idx, done=self.collected())
        return kept

    def _scrape_card(self, card, idx: int) -> dict | None:
        author = self._text_of(card, '.name')
        if not author:
            logger.debug(t('crawl.debug.card_skip', i=idx))
            return None
        publish_time, source, post_link = self._get_from_line(card)
        text = self._get_full_text(card)
        forward = parse_count(self._text_of(card, '[action-type="feed_list_forward"]'))
        comment = parse_count(self._text_of(card, '[action-type="feed_list_comment"]'))
        like = parse_count(self._text_of(card, '.woo-like-count'))
        images = self._get_images(card)
        mid = card.get_attribute('mid') or ''
        logger.debug(t('crawl.debug.card_author', i=idx, v=author))
        logger.debug(t('crawl.debug.card_time', i=idx, v=publish_time))
        logger.debug(t('crawl.debug.card_len', i=idx, v=len(text)))
        logger.debug(t('crawl.debug.card_metrics', i=idx, f=forward, c=comment, l=like))
        logger.debug(t('crawl.debug.card_images', i=idx, n=len(images)))
        return {
            '发布者': author,
            '发布时间': publish_time,
            '发布来源': source,
            '正文': text,
            '转发数': forward,
            '评论数': comment,
            '点赞数': like,
            '图片链接': ' | '.join(images),
            '图片数': len(images),
            '话题': ' | '.join(self._get_topics(card)),
            '视频数': self._count(card, '.media-video-a'),
            '用户链接': self._abs_url(self._attr(card, '.name', 'href')),
            # The post's own permalink (``//weibo.com/<uid>/<bid>``), tracking
            # query stripped — the row's strongest identity. ``微博ID`` keeps the
            # numeric mid for callers that want to key off it.
            '链接': post_link or (f'https://weibo.com/detail/{mid}' if mid else ''),
            '微博ID': mid,
        }

    def _get_from_line(self, card) -> tuple[str, str, str]:
        """(发布时间, 客户端来源, 该条微博的固定链接).

        ``.from``'s first anchor carries both the timestamp and the canonical
        permalink; the text after it names the client the post was made from.
        """
        try:
            anchors = card.find_elements(By.CSS_SELECTOR, '.from a')
        except NoSuchElementException:
            return '', '', ''
        if not anchors:
            return '', '', ''
        publish_time = self._node_text(anchors[0])
        post_link = self._abs_url(anchors[0].get_attribute('href') or '').split('?')[0]
        whole = self._text_of(card, '.from') or publish_time
        source = whole.replace(publish_time, ' ').strip(' \n\u00a0')
        for prefix in ('来自', 'From', 'from'):
            source = source.replace(prefix, ' ').strip()
        source = re.sub(r'\s+', ' ', source)
        return publish_time, source, post_link

    def _get_topics(self, card) -> list:
        """The post's hashtags, in DOM order.

        The plain body already contains them, but an anchor into ``weibo?q=#``
        is what proves a token is a topic rather than a stray ``#`` in prose.
        """
        try:
            anchors = card.find_elements(By.CSS_SELECTOR, 'a[href*="weibo?q=%23"]')
        except NoSuchElementException:
            return []
        topics = []
        for anchor in anchors:
            text = self._node_text(anchor).strip('# \n\t')
            if text and text not in topics:
                topics.append(text)
        return topics

    def _count(self, card, selector: str) -> int:
        try:
            return len(card.find_elements(By.CSS_SELECTOR, selector))
        except NoSuchElementException:
            return 0

    @staticmethod
    def _attr(card, selector: str, name: str) -> str:
        try:
            return card.find_element(By.CSS_SELECTOR, selector).get_attribute(name) or ''
        except Exception:
            return ''

    def _get_full_text(self, card):
        # The collapsed preview and the expanded body are both in the DOM and
        # the expanded one wins. Neither is ever clicked: ``展开`` folds the card
        # back and detaches the element handles the walk still needs.
        for sel in ('[node-type="feed_list_content_full"]', '[node-type="feed_list_content"]', '.content p.txt'):
            try:
                els = card.find_elements(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            for el in els:
                text = self._node_text(el)
                text = re.sub(r'\s*(展开|收起)\s*$', '', text).strip()
                if text:
                    return text
        return ''

    def _get_images(self, card) -> list:
        """Image URLs of the post, deduplicated.

        ``src`` is preferred over a background-image style so a lazy-load
        placeholder never counts as a picture, and a data: URI is never a URL
        worth handing downstream.
        """
        urls = []
        try:
            imgs = card.find_elements(By.CSS_SELECTOR, '.media-piclist img, [action-type="fl_pics"] img')
        except Exception:
            return urls
        for img in imgs:
            src = (img.get_attribute('src') or '').strip()
            if src and not src.startswith('data:') and src not in urls:
                urls.append(src)
        return urls

    # ─── pager ────────────────────────────────────────────────────────

    def _get_total_pages(self):
        """How deep this keyword feed goes — read from the pager, never clicked.

        The old implementation waited for ``a[action-type="feed_list_page_more"]``
        and clicked it twice. That control no longer exists on the search page
        (0 matches on a live run), so every crawl concluded "one page" after
        burning a click; the page count is now read out of the pager text
        ("共50页/500条"), and reaching a page never needs a click because the URL
        carries it.
        """
        info = self._element_or_none('.page-info')
        if info is not None:
            m = re.search(r'共\s*(\d+)\s*页', self._node_text(info))
            if m:
                total = max(1, int(m.group(1)))
                logger.info(t('crawl.weibo.max_page', n=total))
                return total
        else:
            logger.debug(t('crawl.debug.pager_missing'))
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, 'ul.page-list li a, .m-page2 a')
        except Exception as e:
            logger.error(t('crawl.weibo.pages_fail', err=e))
            return 1
        max_page = 1
        for link in links:
            href = link.get_attribute('href') or ''
            m = re.search(r'page=(\d+)', href)
            if not m:
                continue
            try:
                max_page = max(max_page, int(m.group(1)))
            except ValueError:
                continue
        if max_page > 1:
            logger.info(t('crawl.weibo.max_page', n=max_page))
        return max_page

    # ─── compatibility shims (kept for callers outside this module) ───

    def _extract_text(self, el, sel, default=''):
        return self._text_of(el, sel, default) or default

    def _extract_number(self, text):
        return parse_count(text)

    def _get_publish_time(self, card):
        return self._text_of(card, '.from a')

    def _scrape_page(self):
        """Scrape every card of the page that is loaded right now."""
        return self._harvest(self.DEFAULT_TARGET)

    def get_detail(self, url: str) -> dict | None:
        return None
