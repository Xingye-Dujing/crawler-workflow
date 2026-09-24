import contextlib
import json
import logging
import re
import time
from urllib.parse import quote

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from i18n import t

from .base import Crawler, as_index
from .engine import feed
from .engine.counters import parse_count

logger = logging.getLogger(__name__)


def zhihu_profile_token(value: str) -> str:
    """``zshu-83`` / ``@zshu-83`` / a pasted profile link → the profile token.

    The token cannot be derived from what the crawler already reads: measured on an
    answer permalink, the page carries 86 anchors and **not one** of them is a
    ``/people/`` link, so a display name is all a row can offer. That is why the
    panel asks for a profile link or the token at its end rather than for a name to
    search for — the search-by-name route would be a second, weaker opinion about
    who the user meant.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    if '/people/' in text:
        tail = text.split('/people/', 1)[-1]
        for cut in ('?', '#', '/'):
            tail = tail.split(cut)[0]
        return tail.strip()
    if '://' in text or text.startswith('/'):
        # Some other page's address (an answer or question link is what the
        # clipboard usually holds). There is no token in it, and inventing one
        # would open /people/https: and report an empty profile as if the author
        # had published nothing — refuse with the actionable message instead.
        return ''
    return text.lstrip('@').strip('/').split('/')[0]


def zhihu_item_meta(raw: str) -> dict:
    """The ``data-zop`` JSON a content item carries, or ``{}``.

    It is the site's own tracking payload — ``authorName`` / ``itemId`` / ``title``
    / ``type`` — and on a profile page it is the only place the author's name is
    spelled out as data instead of as markup.
    """
    try:
        parsed = json.loads(str(raw or ''))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


#: ``data-zop``'s kind → the 分类 label. Two vocabularies are the site's, not ours:
#: the search page names a card through ``data-za-detail-view-path-module``
#: (``AnswerItem``) while the row's own tracking payload says ``answer``.
ZOP_KIND_LABELS = {'answer': '回答', 'article': '文章', 'zvideo': '视频', 'question': '提问'}


def zhihu_item_link(meta: dict) -> str:
    """The address of an item, built from the kind and id the page itself names."""
    item_id = str((meta or {}).get('itemId') or '')
    kind = str((meta or {}).get('type') or '')
    question = str((meta or {}).get('questionId') or '')
    if not item_id:
        return ''
    if kind == 'answer' and question:
        return f'https://www.zhihu.com/question/{question}/answer/{item_id}'
    if kind == 'answer':
        return f'https://www.zhihu.com/answer/{item_id}'
    if kind == 'article':
        return f'https://www.zhihu.com/p/{item_id}'
    return ''


class ZhihuCrawler(Crawler):
    """Scrapes zhihu's content-search page.

    The 2026 result list is an infinite scroll of ``SearchResult-Card`` items.
    Two rules shape this crawler:

    - **only an answer card may be clicked** — the list hands out an excerpt and the card's
      own 阅读全文 holds the rest, so a row that is never expanded is a truncated row.
      Answers un-clamp in place (measured: same URL, 21 cards still present, a handle to a
      card two rows down still alive, 8/8 clicks); a column article's control navigates to
      its own page, which detaches every remaining handle and used to turn whole crawls
      into 0 rows. The gate is therefore the card's own link, not its class.
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
    #: A profile tab's rows. Measured 2026-09: ``/people/<token>/answers`` held 39
    #: ``.ContentItem`` nodes and 79 after three scrolls, so the list pages by
    #: scrolling exactly like the search page — and the nodes are the same shape, so
    #: the search card readers apply unchanged.
    PROFILE_ITEM = '.List-item .ContentItem'
    #: The two tabs that hold 作品. 提问/收藏/关注 are not content the user analyses.
    PROFILE_TABS = ('answers', 'posts')
    #: Un-clamps one row's body in place, and is only ever pointed at a row whose control
    #: is known to be a state change on the same document: a profile row measured as one
    #: (the button turns into 收起 and the text grows to its full length), and a search
    #: page *answer* card measured as one too. A column card's control navigates, which
    #: detaches every remaining handle — so the search walk refuses it by link, below.
    EXPAND_JS = """
    var hit = null;
    arguments[0].querySelectorAll('button, a').forEach(function (b) {
        var t = (b.innerText || '').trim();
        if (!hit && t.indexOf('阅读全文') !== -1) hit = b;
    });
    if (!hit) return 0;
    hit.click();
    return 1;
    """

    #: How long an expanded answer may take to arrive. Measured: the text was complete
    #: within ~0.6 s of the click, and the settle poll costs one tick when it already did.
    EXPAND_WAIT = 4.0
    #: Consecutive cards that refuse to grow. A site that answers 3 clicks with nothing is
    #: not answering any more, and paying the full wait per row for the rest of a crawl
    #: would be the worse failure.
    EXPAND_GIVEUP = 3
    #: The one link shape whose 阅读全文 was measured to expand instead of navigating.
    ANSWER_LINK = '/answer/'

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

    def search(self, keyword: str, target_count: int = 200, full_body: bool = True, **_kwargs):
        """One keyword's result list. ``full_body`` decides what a 正文 column holds.

        The list itself only ever carries an excerpt (measured: 35–109 characters, in a
        plain inline span with no CSS clamp, while the same answer's page ran to 308). So
        an unexpanded row is a truncated row, and that is what the flag pays for: one
        click and one short wait per answer card. Turning it off is a deliberate trade of
        data for time, which is why the crawl says so on the console instead of leaving
        the short column to be discovered in the export.
        """
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
        # ``want`` outlives one pass because the decision it carries does: cards that
        # refuse to expand are a property of the site's mood, not of the scroll round, so
        # a walk that gave up stays given up instead of paying the wait again next round.
        expand = {'want': bool(full_body), 'misses': 0, 'short': 0}
        self.mark_position(keyword=keyword, phase='cards', done=have, scanned=cursor['scanned'])
        self._harvest(cursor, target_count, expand)

        rounds = 0
        stuck = 0
        while self.collected() < target_count:
            rounds += 1
            self.scroll_down(steps=self.SCROLL_STEPS)
            # Adaptive wait: a screen that already grew costs one poll, a slow
            # one still gets its 1.5 s.
            before = cursor['total']
            cursor['total'] = self._wait_for_count(self._card_count, before + 1, timeout=self.CARD_WAIT)
            logger.info(t('crawl.zhihu.scrolling', i=rounds))
            logger.info(t('crawl.zhihu.scroll_round', i=rounds, n=cursor['total'], total=target_count))

            self._harvest(cursor, target_count, expand)
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
                self._harvest(cursor, target_count, expand)
                if cursor['total'] <= before:
                    logger.info(t('crawl.zhihu.stuck', n=stuck))
                    break
            else:
                stuck = 0
            # Politeness between network-driving rounds — this is what keeps a
            # long crawl off zhihu's rate-limit page.
            self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)

        logger.info(t('crawl.zhihu.phase_done', n=cursor['total']))
        if self.collected():
            # Said only about a table that exists: a search refused by risk control has no
            # 正文 column to be an excerpt of, and reporting one would describe a run
            # that never happened.
            if not full_body:
                logger.info(t('crawl.zhihu.excerpt_only'))
            elif expand['short']:
                logger.info(t('crawl.zhihu.bodies_short', n=expand['short']))
        logger.info(t('crawl.zhihu.finished', n=self.collected(), total=target_count))
        return self.results()

    # ─── one creator's own list ───────────────────────────────────────

    def author(self, author: str, target_count: int = 50, **kwargs):
        """One account's answers and articles, read from their own profile tabs.

        Both tabs are walked, answers first: 「作品」 for zhihu means the 回答 and the
        文章 an account wrote, and an account that only ever answered (or only ever
        wrote articles) still gets a complete list rather than a false half.

        A profile row is the same ``.ContentItem`` shape the search page harvests, so the
        card readers and :meth:`_expand_body` are reused. What differs is the risk: a
        profile row's 阅读全文 was measured to be a state change on the same document (the
        button turns into 收起 and the text grows), while on the search page the same label
        on a column card navigates — which is why that walk gates by link and this one
        expands every row.
        """
        token = zhihu_profile_token(author)
        if not token:
            raise ValueError(t('crawl.zhihu.authorEmpty', author=author))
        logger.info(t('crawl.zhihu.authorStart', author=token, n=target_count))
        for tab in self.PROFILE_TABS:
            if self.collected() >= target_count:
                break
            self._walk_profile_tab(token, tab, target_count)
        logger.info(t('crawl.zhihu.finished', n=self.collected(), total=target_count))
        return self.results()

    def _walk_profile_tab(self, token: str, tab: str, target_count: int) -> None:
        """Harvest one profile tab, paging it by scrolling the way the search page does."""
        self.open(f'https://www.zhihu.com/people/{token}/{tab}')
        if self.login_wall or self.risk_blocked:
            raise RuntimeError(t('crawl.zhihu.emptyOrBlocked'))

        def items():
            return self.driver.find_elements(By.CSS_SELECTOR, self.PROFILE_ITEM)

        def item_count():
            return len(items())

        if self._wait_for_count(item_count, 1, timeout=self.CARD_WAIT * 6) < 1:
            # Nothing on this tab at all. For a profile that is a normal fact — many
            # accounts answer questions and never write an article — so it is logged
            # and skipped, never raised.
            logger.info(t('crawl.zhihu.authorTabEmpty', tab=tab, author=token))
            return

        def mark(position):
            self.mark_position(author=token, tab=tab, **position, done=self.collected())

        result = feed.walk_feed(
            items,
            self._profile_card,
            self.emit,
            scroll=lambda: self.scroll_down(steps=self.SCROLL_STEPS),
            target=target_count,
            collected=self.collected,
            mark=mark,
            stopped=lambda: self.login_wall or self.risk_blocked,
            stuck_rounds=self.STUCK_ROUNDS,
            settle_wait=self.CARD_WAIT,
        )
        logger.info(t('crawl.zhihu.authorTabDone', tab=tab, n=self.collected(), reason=result.stopped_reason))

    def _profile_card(self, card, index: int = 0) -> dict | None:
        """One profile row → a row, with the body unclamped before it is read."""
        self._expand_body(card)
        item = self._scrape_card(card)
        meta = zhihu_item_meta(card.get_attribute('data-zop') or '')
        # ``data-zop`` is the site's own tracking payload: it names the author, the
        # kind and the id, which is more than the visible markup gives — a profile
        # row has no 「作者名：」 prefix inside its text, so ``_get_author`` comes back
        # empty for every row of exactly the page where the author is known.
        if meta.get('authorName'):
            item['作者'] = meta['authorName']
        if not item.get('分类'):
            item['分类'] = ZOP_KIND_LABELS.get(str(meta.get('type') or ''), '')
        if not item.get('链接'):
            item['链接'] = zhihu_item_link(meta)
        if not item.get('发布时间'):
            item['发布时间'] = self._profile_time(card)
        if not (item.get('正文') or item.get('标题')):
            return None
        return item

    def _expand_body(self, card) -> bool:
        """Click the row's own 阅读全文, which un-clamps it without leaving the page.

        Returns whether a control was found and clicked — the caller needs that to tell
        "this row was already complete" apart from "this row is still an excerpt".
        """
        with contextlib.suppress(Exception):
            if self.driver.execute_script(self.EXPAND_JS, card):
                # The button's click swaps the clamped node for the full one; the
                # text is re-read by the caller right away, and a row that is still
                # short is simply a short answer.
                time.sleep(0.3)
                return True
        return False

    def _profile_time(self, card) -> str:
        """The 发布于 / 编辑于 label of a profile row.

        The label is kept whole, prefix included, because the two words mean
        different things and the list mixes them: ``meta[itemprop=dateCreated]``
        measured equal to the *edited* moment on a row the site labelled 编辑于, so
        reading that attribute and stamping it as 发布时间 would put a wrong figure
        in a plausible column.
        """
        for sel in ('.ContentItem-time', '.ContentItem-footer time', 'time'):
            with contextlib.suppress(Exception):
                node = card.find_element(By.CSS_SELECTOR, sel)
                text = (node.get_attribute('title') or node.text or '').strip()
                if text:
                    return text
        return ''

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

    def _harvest(self, cursor: dict, target_count: int, expand: dict) -> None:
        """Scrape and emit every card past ``cursor['scanned']``.

        Re-reading the cards each round rather than keeping the handles is
        deliberate: the list is virtualised, so an old handle can point at a
        detached node while the same index still resolves to a live card.

        ``expand`` is the crawl's expansion state: whether to keep trying, how many
        cards in a row refused, and how many rows are therefore still excerpts.
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
                if expand['want'] and self._is_answer_card(item):
                    if self._expand_answer(card, item):
                        expand['short'] += 1
                        expand['misses'] += 1
                        if expand['misses'] >= self.EXPAND_GIVEUP:
                            expand['want'] = False
                            logger.info(t('crawl.zhihu.expand_stopped', n=expand['misses']))
                    else:
                        expand['misses'] = 0
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

    def _is_answer_card(self, item: dict) -> bool:
        """Whether this card's own address says it is an answer.

        The link, not the card's class: 阅读全文 is a navigation on a column card, and a
        row whose anchor never mounted is a row whose kind is unknown, so neither is
        clicked. Refusing costs an excerpt on the rare card, where clicking costs the
        rest of the crawl.
        """
        return self.ANSWER_LINK in str(item.get('链接') or '')

    def _expand_answer(self, card, item: dict) -> bool:
        """Un-clamp one answer card in place and put its full body into *item*.

        Returns whether the row is still an excerpt. Only 正文 is touched: the click also
        swaps the card's date label for a longer one (measured: ``08-27`` became
        ``编辑于2026-08-27 12:22``) and drops the ``作者名：`` prefix the preview opens with,
        so re-reading the whole row would leave one column holding two formats depending
        on an internal retry. 作者 and 发布时间 stay as the list itself reported them.
        """
        preview = str(item.get('正文') or '')
        if not self._expand_body(card):
            return False  # no 阅读全文 on this card: the answer is simply short
        feed.wait_for(lambda: len(self._get_content(card)), len(preview) + 1, timeout=self.EXPAND_WAIT, tick=0.25)
        body = str(self._get_content(card) or '')
        if len(body) <= len(preview):
            return True
        item['正文'] = body
        return False

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
