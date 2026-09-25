import json
import logging
import math
import re
import time
from datetime import datetime, timedelta
from urllib.parse import quote, unquote

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from i18n import t

from .base import Crawler, as_index
from .engine import pagefetch, pager
from .engine.counters import parse_count

logger = logging.getLogger(__name__)


# The author walk addresses a person by their numeric uid only; the mymblog endpoint
# honours `uid`, and a screen name addresses nobody (measured).
_UID_PATTERNS = (
    re.compile(r'(?:^|\.)weibo\.com/u/(\d{5,})'),
    re.compile(r'(?:^|//)m?\.?weibo\.(?:com|cn)/u/(\d{5,})'),
    re.compile(r'weibo\.com/(\d{5,})(?:[/?#]|$)'),
    re.compile(r'^(\d{5,})$'),
)


def weibo_uid(value: str) -> str:
    """Digits, a ``weibo.com/u/<uid>`` profile link, a ``weibo.com/<uid>/<post>`` link
    or the search row's own 用户链接 → the numeric uid.

    Anything without one of those digit shapes is refused with ``''``: opening a
    guessed profile would report "this person posted nothing" about a page that is
    not theirs, which is worse than saying the address was not a uid. The ``/u/<id>``
    form is matched only on a weibo host (a taobao ``/u/123456`` is a different
    person), and query/fragment junk is stripped first because the real 用户链接
    carries ``?refer_flag=…``.
    """
    raw = str(value or '').strip().split('#')[0].split('?')[0]
    if not raw:
        return ''
    for pattern in _UID_PATTERNS:
        match = pattern.search(raw)
        if match:
            return match.group(1)
    return ''


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
      costs wall risk. Hence the target cutoff and the jittered pauses between
      requests; the depth itself is the pager's answer, not a hardcoded cap.
      Parallel windows of one account pay this risk together (weibo walls a
      session that fires several deep requests at once), which is what the
      同平台排队 setting is for — the crawler cannot talk the site out of it.
    """

    domain = 'weibo.com'
    #: 热搜, served by the logged-in origin. Measured: ``ok: 1`` with ~52 rows in
    #: ``data.realtime``, repeatable, and answered with or without a session.
    HOT_API = 'https://weibo.com/ajax/side/hotSearch'
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
    # Rows per feed page is ~9-10. The walk goes as deep as the site's own pager
    # says it can; what bounds it is the target (break on reaching it) and the
    # wall (break on latching it), never a hardcoded page count — capping at 5
    # made a "共50页" feed quit early with the target unmet and nothing said why.
    # Paging is meaningless inside a time window: the window is already narrow.
    PAGE_WAIT = 3.0
    POLITE_BASE = 1.0
    POLITE_SPREAD = 0.35

    # A date-range crawl without a target wants every window it was given: the
    # "no number asked" sentinel is *no ceiling*, not a very big one.
    DEFAULT_TARGET = math.inf

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
                logger.info(t('crawl.weibo.target_reached', n=target))
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

    # ─── the site's own board ─────────────────────────────────────────

    def hot(self, target_count: int = 50, **kwargs):
        """微博热搜 — the topic board the site ranks for itself.

        ``ajax/side/hotSearch`` is read from inside a loaded ``weibo.com`` document,
        which is the shape that answers: measured 52 rows carrying an exact integer
        heat (``num``), a repeat call returning the same list, and — unlike every other
        weibo surface here — the same answer in a planted-cookie window, in the
        profile, and with **no cookie at all**. That last fact is why this mode asks
        for no login: refusing to run without a session would be inventing a
        requirement the site does not have.

        The DOM table on the search host (``s.weibo.com/top/summary``) answers in all
        three shapes too and is kept as the fallback in docs; it is not used here
        because it labels its heat with 万 rounding and costs a passport-flash judge on
        the way in, while the JSON gives the same rows exactly.

        A row is a TOPIC, not a post: its 链接 is the search page for that word, which
        is what the board itself links to. Columns the payload cannot fill (正文, 作者,
        发布时间) are simply absent rather than empty-and-implied.
        """
        logger.info(t('crawl.weibo.hotStart', n=target_count))
        self.open('https://weibo.com/')
        payload = pagefetch.fetch_json(self.driver, self.HOT_API, requests=self.requests)
        rows = None
        if isinstance(payload, dict) and payload.get('ok') == 1:
            data = payload.get('data') or {}
            candidate = data.get('realtime')
            if isinstance(candidate, list):
                rows = candidate
        if rows is None:
            answer = payload.get('ok') if isinstance(payload, dict) else None
            raise RuntimeError(t('crawl.weibo.hotRefused', answer=str(answer if answer is not None else 'empty')))
        seen = {str(row.get('链接') or '') for row in self.results()}
        for index, item in enumerate(rows, start=1):
            if self.collected() >= target_count:
                break
            row = self._hot_row(item, index)
            if not row or row['链接'] in seen:
                continue
            seen.add(row['链接'])
            self.emit(row)
            self.mark_position(board='hot', done=self.collected())
        logger.info(t('crawl.weibo.hotDone', n=self.collected(), total=target_count))
        if self.collected() < target_count:
            logger.info(t('crawl.weibo.hotCapped', board=len(rows)))
        return self.results()

    @staticmethod
    def _hot_row(item: dict, rank: int) -> dict | None:
        """One board entry, flattened. ``word`` is the topic; ``word_scheme`` carries
        the ``#…#`` form the site publishes. ``note`` duplicates ``word`` on the
        measured rows, so it is not a column of its own."""
        word = str(item.get('word') or '').strip()
        if not word:
            return None
        scheme = str(item.get('word_scheme') or '').strip() or word
        heat = item.get('num')
        return {
            '排名': as_index(item.get('realpos'), rank),
            '标题': word,
            '话题': scheme,
            '热度': as_index(heat, 0) if str(heat or '').strip() else parse_count(str(item.get('label') or '')),
            '链接': f'https://s.weibo.com/weibo?q={quote(scheme)}',
        }

    # ─── one author's posts ─────────────────────────────────────────────

    def author(self, author: str, target_count: int = 50, **kwargs):
        """One account's own posts, read from the author's loaded profile page.

        The ``mymblog`` endpoint is fetched INSIDE ``weibo.com/u/<uid>`` with
        ``credentials:'include'`` — the shape that answers, where the same request
        issued standalone is bounced (docs). Depth is the pager's answer (``page=N``
        advances until the target, the server's end, or a refusal), never a page
        budget. Two refusals are named, never filed as an empty table: the edge's
        403/WAF body (a per-session throttle — the cookie may be fine, so the user
        backs off rather than re-saving), and the mirror case (the payload is the
        home timeline, not this uid's posts), caught by the one anchor that separates
        them — the first row's ``user.id`` must equal the requested uid.
        """
        uid = weibo_uid(author)
        if not uid:
            raise ValueError(t('crawl.weibo.authorEmpty', author=author))
        target = self.DEFAULT_TARGET if not target_count else int(target_count)
        if self.collected() >= target:
            logger.info(t('crawl.weibo.target_reached', n=target))
            return self.results()
        resume = self.resume_of(kwargs)
        page = max(1, as_index(resume.get('page'), 1))
        logger.info(t('crawl.weibo.authorStart', uid=uid, n=target))
        # One navigation, through open() so the passport-flash is judged the way the
        # search path judges it; the endpoint is asked from that loaded page.
        self.open(f'https://weibo.com/u/{uid}')
        if self.login_wall:
            raise RuntimeError(t('crawl.weibo.authorWall', uid=uid))

        seen = {str(r.get('微博ID') or '') for r in self.results() if r.get('微博ID')}
        state = {'page': page, 'refused_status': None}

        def _fetch(cursor):
            state['page'] = int(cursor)
            answer = pagefetch.fetch(self.driver, self._mymblog(uid, cursor), requests=self.requests)
            body = str(answer.get('body') or '')
            if answer.get('status') != 200 or not body.lstrip().startswith('{'):
                # 403 edge, an HTML wall, or a transport death: a refused page, not
                # an empty one — remember the status so the message can name it.
                if state['refused_status'] is None:
                    state['refused_status'] = answer.get('status')
                return None
            return json.loads(body)

        def _extract(payload):
            rows = (payload.get('data') or {}).get('list') or []
            if rows and str((rows[0].get('user') or {}).get('id')) != uid:
                raise RuntimeError(t('crawl.weibo.authorMirror', uid=uid))
            return rows, state['page'] + 1

        def _emit(raw):
            row = self._author_row(raw, uid)
            if not row:
                return False
            kept = self.emit(row)
            if kept:
                # The cursor is the page number plus the uid it was walked for, so a
                # 继续 resumes on the same author rather than guessing. Ids never go
                # into the cursor (they come from the seeded rows).
                self.mark_position(uid=uid, page=state['page'], done=self.collected())
            return kept

        walk = pager.walk_pages(
            _fetch,
            _extract,
            _emit,
            start_cursor=page,
            collected=self.collected,
            target=target,
            seen=seen,
            identity=lambda raw: str(raw.get('mid') or raw.get('id') or ''),
            polite=lambda: self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD),
            alive=lambda: not self.login_wall,
        )
        if not self.collected() and walk.stopped_reason == 'fetch_failed':
            raise ValueError(t('crawl.weibo.authorRefused', uid=uid, status=state['refused_status']))
        if not self.collected():
            # 200 with an empty list is a real fact about the account, not a
            # refusal — legal, exactly as a bilibili space with no uploads is.
            logger.info(t('crawl.weibo.authorNoPosts', uid=uid))
        logger.info(t('crawl.weibo.authorDone', n=self.collected(), reason=walk.stopped_reason))
        return self.results()

    @staticmethod
    def _mymblog(uid: str, page: int) -> str:
        return f'https://weibo.com/ajax/statuses/mymblog?uid={uid}&page={page}&feature=0'

    def _author_row(self, raw: dict, uid: str) -> dict | None:
        """Flatten one mymblog item into the SEARCH mode's column set.

        Same keys as :meth:`_scrape_card` on purpose: author and keyword crawls of
        one platform feed the same cleaning/analysis nodes, and a table that differs
        per mode is the "same video, two tables" trap. The counters are already ints
        here, so they are NOT run through :func:`parse_count` (which reads the
        search page's 万-labelled text). Columns the payload cannot fill honestly —
        图片链接 (only ``pic_ids``, no URLs), 话题 beyond ``topic_struct``, 视频数
        beyond what ``page_info`` says — are left empty/zero rather than guessed.
        """
        user = raw.get('user') or {}
        mid = str(raw.get('mid') or raw.get('id') or '')
        if not mid:
            return None
        return {
            '发布者': str(user.get('screen_name') or ''),
            '发布时间': self._normalise_weibo_time(raw.get('created_at')),
            '发布来源': str(raw.get('source') or ''),
            '正文': str(raw.get('text_raw') or '') or self._strip_html(str(raw.get('text') or '')),
            '转发数': self._as_int(raw.get('reposts_count')),
            '评论数': self._as_int(raw.get('comments_count')),
            '点赞数': self._as_int(raw.get('attitudes_count')),
            '图片链接': '',
            '图片数': self._as_int(raw.get('pic_num')),
            '话题': self._author_topics(raw.get('topic_struct')),
            '视频数': 0,
            '用户链接': f'https://weibo.com/u/{uid}',
            '链接': f'https://weibo.com/detail/{mid}',
            '微博ID': mid,
        }

    @staticmethod
    def _as_int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _normalise_weibo_time(value) -> str:
        # The endpoint stamps 'Wed Sep 24 15:42:51 +0800 2026'; the search page
        # shows a relative label. Two shapes in one column is the documented defect,
        # so normalise the absolute time to a readable absolute form rather than
        # shipping an English stamp beside a Chinese one.
        text = str(value or '').strip()
        if not text:
            return ''
        try:
            return datetime.strptime(text, '%a %b %d %H:%M:%S %z %Y').strftime('%Y-%m-%d %H:%M')
        except ValueError:
            return text

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r'<[^>]+>', '', text).strip()

    @staticmethod
    def _author_topics(struct) -> str:
        # topic_struct carries {topic_url, title} with an EMPTY title; the name lives
        # url-encoded between %23…%23 (#…#) in topic_url's q= parameter.
        names = []
        for item in struct or []:
            url = str((item or {}).get('topic_url') or '')
            match = re.search(r'q=([^&]+)', url)
            if not match:
                continue
            label = unquote(match.group(1)).strip('#').strip()
            if label and label not in names:
                names.append(label)
        return ' | '.join(names)

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
        # No width cap: how far a range reaches is the user's own choice, and the
        # walk already ends on the target, on the last window, or on a wall.
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

            total_pages = self._get_total_pages()
            logger.info(t('crawl.weibo.total_pages', n=total_pages))
            page_url = self._page_url(base_url)
            for page_num in range(2, total_pages + 1):
                if self.collected() >= target:
                    logger.info(t('crawl.weibo.target_reached', n=target))
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
                logger.info(t('crawl.weibo.target_reached', n=target))
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
