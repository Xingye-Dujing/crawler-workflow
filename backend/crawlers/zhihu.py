import contextlib
import logging
import re
import time
from urllib.parse import quote

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from i18n import t

from .base import Crawler, as_index
from .engine.counters import parse_count

logger = logging.getLogger(__name__)


class ZhihuCrawler(Crawler):
    """Scrapes zhihu's content-search page.

    The 2026 result list is an infinite scroll of ``SearchResult-Card`` items.
    Two rules shape this crawler:

    - **never click inside a card** — 展开全文/阅读全文 navigates column
      articles to their own page, which detaches every remaining card and used
      to turn whole crawls into 0 rows. The collapsed preview already carries
      author + body, which is all a search-page crawl needs.
    - **harvest while scrolling** — cards are scraped the moment they render, so
      rows stream out during the scroll and the loop can stop the second the
      target is met instead of after a fixed load phase.
    """

    domain = 'www.zhihu.com'
    # Same reasoning as weibo: /signin is a QR wall even when logged in; the
    # home page shows the wall only when the session is actually dead.
    login_url = 'https://www.zhihu.com/'

    # Every result kind, not just articles: the list is ~80 % answers, and
    # pinning the walk to ``PostItem`` made the crawler scroll for cards it had
    # already thrown away.
    CARD_SELECTOR = '.SearchResult-Card[role="listitem"]'
    END_MARKER = '.css-7hmi9v'

    MAX_SCROLL_ROUNDS = 30
    SCROLL_STEPS = 3
    STUCK_ROUNDS = 3
    CARD_WAIT = 1.5
    POLITE_BASE = 0.9
    POLITE_SPREAD = 0.3

    # The card kind is only exposed through the tracking attribute; it is the
    # closest thing the 2026 search page has to a 分类/话题 label.
    _MODULE_LABELS = {
        'AnswerItem': '回答',
        'PostItem': '文章',
        'ZVideoItem': '视频',
        'VideoItem': '视频',
        'PeopleItem': '用户',
        'TopicItem': '话题',
    }

    # The current card DOM has no author element at all — the account name is
    # inlined at the head of the preview ("作者名：正文…"). Bounded and strict
    # on purpose: a ≤12-char prefix before the colon, no spaces or sentence
    # punctuation, so ordinary openers like "注意：…" stay part of the body.
    _AUTHOR_PREFIX = re.compile(r'^([\u4e00-\u9fa5A-Za-z0-9_·\-]{1,12})[:：](?=[^\s])')

    def search(self, keyword: str, target_count: int = 200, **_kwargs):
        # Nothing to seek past: a search result page cannot be re-entered at an
        # old scroll offset, so the position records how many items are in hand
        # and how many cards were read; duplicates are dropped by the sink.
        resume = self.resume_of(_kwargs)
        have = self.collected()
        if have:
            logger.info(t('crawl.resume_have', n=have))
        if have >= target_count:
            logger.info(t('crawl.zhihu.target_reached', n=target_count))
            return self.results()

        encoded = quote(str(keyword or ''))
        url = f'https://www.zhihu.com/search?q={encoded}&type=content'
        logger.info(t('crawl.zhihu.start', kw=keyword, n=target_count))
        logger.info(t('crawl.zhihu.url', url=url))
        self.driver.get(url)
        self.wait_for_element(self.CARD_SELECTOR)
        self.check_login_wall(url)
        if self.login_wall:
            # Risk control answered instead of results: fail loudly with the
            # one actionable instruction, never a silent zero-row 'success'.
            raise RuntimeError(t('crawl.zhihu.emptyOrBlocked'))
        if self._card_count() == 0 and self._deep_link_came_up_empty():
            # The deep-linked SPA sometimes shows its empty shell; typing into
            # the real search box issues the request the app itself expects.
            logger.info(t('crawl.zhihu.fallbackSearch'))
            self._search_via_input(keyword)
            self.check_login_wall(url)
            if self.login_wall:
                raise RuntimeError(t('crawl.zhihu.emptyOrBlocked'))
            if self._card_count() == 0 and not self._deep_link_came_up_empty():
                # The retry produced a DEFINITE no-results plate (not an
                # unfetched shell): zhihu answered with nothing, which the
                # catalog treats as risk control and tells the user to go
                # visible/retry. A still-empty shell instead falls through to
                # the scroll loop and returns 0 rows — the documented, legit
                # headless risk-control outcome we must not turn into a crash.
                raise RuntimeError(t('crawl.zhihu.emptyOrBlocked'))
        logger.info(t('crawl.zhihu.loaded'))

        # ``scanned`` is how far the card walk has got; a resume reads only the
        # cards past it instead of re-emitting the head of the list.
        cursor = {'scanned': as_index(resume.get('scanned')), 'total': self._card_count()}
        self.mark_position(keyword=keyword, phase='cards', done=have, scanned=cursor['scanned'])
        self._harvest(cursor, target_count)

        rounds = 0
        stuck = 0
        while rounds < self.MAX_SCROLL_ROUNDS and self.collected() < target_count:
            rounds += 1
            self.scroll_down(steps=self.SCROLL_STEPS)
            # Adaptive wait: a screen that already grew costs one poll, a slow
            # one still gets its 1.5 s.
            before = cursor['total']
            cursor['total'] = self._wait_for_count(self._card_count, before + 1, timeout=self.CARD_WAIT)
            logger.info(t('crawl.zhihu.scrolling', i=rounds))
            logger.info(t('crawl.zhihu.scroll_round', i=rounds, n=cursor['total'], total=target_count))

            self._harvest(cursor, target_count)
            if self.collected() >= target_count:
                logger.info(t('crawl.zhihu.target_reached', n=target_count))
                break
            if self._end_marker_present():
                logger.info(t('crawl.zhihu.no_more', i=rounds))
                break

            if cursor['total'] <= before:
                stuck += 1
                if stuck >= self.STUCK_ROUNDS:
                    logger.info(t('crawl.zhihu.confirmed', n=before))
                    break
                logger.info(t('crawl.zhihu.no_growth', n=stuck))
                self.scroll_down(steps=self.SCROLL_STEPS)
                cursor['total'] = self._wait_for_count(self._card_count, before + 1, timeout=self.CARD_WAIT)
                self._harvest(cursor, target_count)
                if cursor['total'] <= before:
                    logger.info(t('crawl.zhihu.stuck', n=stuck))
                    break
            else:
                stuck = 0
            # Politeness between network-driving rounds — this is what keeps a
            # long crawl off zhihu's rate-limit page.
            self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)

        logger.info(t('crawl.zhihu.phase_done', n=cursor['total']))
        logger.info(t('crawl.zhihu.finished', n=self.collected(), total=target_count))
        return self.results()

    # ─── scroll + harvest ─────────────────────────────────────────────

    def _card_count(self) -> int:
        return len(self.driver.find_elements(By.CSS_SELECTOR, self.CARD_SELECTOR))

    # Zhihu's own NO-RESULT page is a plain text plate (deep links sometimes
    # skip the fetch entirely and leave a silent shell instead — the two must
    # not blur: only the shell deserves a retry through the search box).
    _NO_RESULT_MARKS = ('未搜索到', '没有找到', '暂无相关', '没有相关')

    def _page_text(self) -> str:
        body = self._element_or_none('body')
        try:
            return (body.text or '') if body is not None else ''
        except Exception:
            return ''

    def _no_result_plate_present(self) -> bool:
        body = self._page_text()
        return any(mark in body for mark in self._NO_RESULT_MARKS)

    def _deep_link_came_up_empty(self) -> bool:
        """True when the zero-card page is still a shell: no cards and no
        definitive no-results plate, so the search request itself deserves a
        second issue. A definite plate means zero IS the answer, and retrying
        would only burn time against a page that already replied."""
        return not self._no_result_plate_present()

    # Zhihu's search input has carried these classes across the 2026 redesign;
    # tried in order because the deep-link shell may render only some of them.
    _SEARCH_BOX_SELECTORS = (
        '.PromptInput',
        'input[placeholder]',
        'input[type="search"]',
    )

    def _search_via_input(self, keyword: str) -> bool:
        """Best-effort human path: type the keyword into the site's own search
        box and press Enter — the request the SPA expects when a deep link
        printed its shell without fetching. A missing box (DOM drift) is not
        fatal: the caller's zero-card check still ends the crawl with the
        actionable risk-control message."""
        box = None
        for selector in self._SEARCH_BOX_SELECTORS:
            box = self._element_or_none(selector)
            if box is not None:
                break
        if box is None:
            logger.debug('zhihu fallback: no search box among %s', self._SEARCH_BOX_SELECTORS)
            return False
        with contextlib.suppress(NoSuchElementException):
            box.clear()
            box.send_keys(f'{keyword}\n')
        self.wait_for_element(self.CARD_SELECTOR)
        return True

    def _end_marker_present(self) -> bool:
        """The 没有更多了 footer, if this page has rendered one yet."""
        try:
            marker = self.driver.find_element(By.CSS_SELECTOR, self.END_MARKER)
        except Exception:
            return False
        return '没有更多' in self._node_text(marker)

    def _harvest(self, cursor: dict, target_count: int) -> None:
        """Scrape and emit every card past ``cursor['scanned']``.

        Re-reading the cards each round rather than keeping the handles is
        deliberate: the list is virtualised, so an old handle can point at a
        detached node while the same index still resolves to a live card.
        """
        cards = self.driver.find_elements(By.CSS_SELECTOR, self.CARD_SELECTOR)
        cursor['total'] = max(cursor['total'], len(cards))
        start = min(cursor['scanned'], len(cards))
        for idx, card in enumerate(cards[start:], start + 1):
            if self.collected() >= target_count:
                logger.info(t('crawl.zhihu.target_reached', n=target_count))
                break
            cursor['scanned'] = idx
            try:
                card_class = card.get_attribute('class') or ''
                if 'hotLanding' in card_class:
                    # 热榜落地推广卡: zero anchors, no title node, a truncated
                    # preview of an answer that appears properly further down
                    # the list. Harvesting it only pollutes the table with
                    # rows nobody can open.
                    logger.debug(t('crawl.zhihu.skipped', i=idx))
                    continue
                item = self._scrape_card(card)
                if not item.get('链接'):
                    # Unmounted top cards of the virtualised list carry no anchor
                    # at all until scrolled into view — nudge and re-scrape
                    # rather than store an identity-less row.
                    with contextlib.suppress(Exception):
                        self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', card)
                        for _ in range(4):
                            time.sleep(0.3)
                            if card.find_elements(By.CSS_SELECTOR, 'a[href]'):
                                break
                        item = self._scrape_card(card)
                keep = bool(item.get('作者') or item.get('正文'))
                if keep:
                    if self.emit(item):
                        logger.info(t('crawl.zhihu.processed', i=idx, n=self.collected()))
                    else:
                        logger.debug(t('crawl.zhihu.duplicate', i=idx))
                else:
                    logger.debug(t('crawl.zhihu.skipped', i=idx))
            except Exception as e:
                logger.error(t('crawl.zhihu.process_error', i=idx, err=e))
            # Recorded per card: a kill between two cards costs at most the one
            # in flight.
            self.mark_position(done=self.collected(), scanned=idx)

    # ─── card parsing ─────────────────────────────────────────────────

    def _scrape_card(self, card):
        content = self._get_content(card)
        return {
            '作者': self._get_author(content),
            '标题': self._get_title(card),
            '正文': content,
            '赞同数': self._get_vote_count(card),
            '评论数': self._get_comment_count(card),
            '发布时间': self._get_publish_time(card),
            '链接': self._get_link(card),
            '分类': self._get_category(card),
        }

    def _get_author(self, content: str) -> str:
        m = self._AUTHOR_PREFIX.match(content or '')
        return m.group(1) if m else ''

    def _get_title(self, card):
        for sel in ('.ContentItem-title a', '.ContentItem-title'):
            try:
                return card.find_element(By.CSS_SELECTOR, sel).text.strip()
            except NoSuchElementException:
                pass
        return ''

    def _get_link(self, card) -> str:
        """The card's own URL — the strongest identity a search row can carry."""
        for sel in ('.ContentItem-title a', '.ContentItem-title'):
            try:
                href = card.find_element(By.CSS_SELECTOR, sel).get_attribute('href') or ''
            except NoSuchElementException:
                continue
            href = href.split('#')[0]
            if href:
                return href
        # Paid columns and promo cards carry no title anchor — their first
        # real link is still the card's own destination.
        try:
            for anchor in card.find_elements(By.CSS_SELECTOR, 'a[href]'):
                href = (anchor.get_attribute('href') or '').split('#')[0]
                if href:
                    return href
        except Exception:
            pass
        return ''

    def _get_category(self, card) -> str:
        try:
            module = card.get_attribute('data-za-detail-view-path-module') or ''
        except Exception:
            module = ''
        return self._MODULE_LABELS.get(module, module)

    def _get_content(self, card):
        # textContent fallback: innerText is empty for cards the virtualised
        # list has not rendered yet — exactly the rows a fast scroll leaves
        # off-screen — and textContent still carries the text.
        try:
            el = card.find_element(By.CSS_SELECTOR, '.RichContent-inner .RichText')
        except NoSuchElementException:
            return ''
        return self._node_text(el)

    # NB: never name a local ``t`` in here — that is the i18n helper these
    # modules import, and shadowing it silently breaks any later t('…') call.
    def _get_vote_count(self, card):
        try:
            label = card.find_element(By.CSS_SELECTOR, '.VoteButton').text.strip()
        except NoSuchElementException:
            return 0
        # Only a 赞同 label carries the vote count; a bare number is the like
        # button on a video card.
        return parse_count(label) if '赞同' in label else 0

    def _get_comment_count(self, card):
        """Two labels are current at once: the action-bar button reads
        '添加评论' / 'N条评论', and the same control carries an aria-label like
        '查看 12 条回答'. A label that names comments but holds no number is a
        zero, not a fallback to the vote count next to it."""
        try:
            buttons = card.find_elements(By.CSS_SELECTOR, '.ContentItem-actions button, .ContentItem-actions a')
        except NoSuchElementException:
            buttons = []
        for btn in buttons:
            label = self._node_text(btn)
            if '评论' not in label and '回答' not in label:
                continue
            return parse_count(label)
        try:
            aria = card.find_element(By.CSS_SELECTOR, '[aria-label*="评论"], [aria-label*="回答"]')
        except NoSuchElementException:
            return 0
        return parse_count(aria.get_attribute('aria-label') or '')

    def _get_publish_time(self, card):
        # 2026 layout moved the date from .ContentItem-time to .SearchItem-time.
        for sel in ('.SearchItem-time', '.ContentItem-time a, .ContentItem-time div'):
            try:
                return card.find_element(By.CSS_SELECTOR, sel).text.strip()
            except NoSuchElementException:
                pass
        return ''

    def get_detail(self, url: str) -> dict | None:
        self.driver.get(url)
        if not self.wait_for_element('.ContentItem-title, .QuestionHeader-title'):
            return None
        return {
            '标题': self._get_title(self.driver),
            '正文': self._get_content(self.driver),
            '赞同数': self._get_vote_count(self.driver),
            '评论数': self._get_comment_count(self.driver),
            '链接': url,
        }
