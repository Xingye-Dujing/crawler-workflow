"""Comment crawling for zhihu / xiaohongshu / weibo / bilibili / douyin links.

Design notes that the code cannot shout later:

* Column keys deliberately avoid every name in ``run_store._URL_FIELDS`` /
  ``_AUTHOR_FIELDS`` / ``_BODY_FIELDS`` ('文章URL', '评论者', '评论内容').
  The dedupe ledger picks identity from those field lists; a comment has no
  link of its own, so borrowing those names would make every comment of one
  article hash to the same key and silently drop all but the first.
* One article can fail for different reasons and they must not blur:
  ``ok`` (rows, maybe zero — zero means 无评论), ``blocked`` (risk-control or
  login wall answered instead of content), ``dead`` (link unreadable/404).
* weibo and bilibili read through their own site's JSON endpoints fetched *in
  page* (same session, cookie-authenticated) — the desktop DOM is a maze of
  hashed class names, and for bilibili's comment panel there is no DOM at all:
  ``.reply-item`` renders nothing, so the endpoint is the only path.
* zhihu blocks headless sessions on content pages (answer/question), so the
  caller must give this platform a visible window; that requirement is
  declared here as ``NEVER_HEADLESS`` and honoured by the node handler.
* douyin is the mirror image of bilibili: its comment panel renders DOM but its
  endpoint is signed (``a_bogus``), so the crawl scrolls a container that
  ``window.scrollTo`` cannot move — and both the mount and every scroll settle
  by polling here, never by sleeping on the caller's ``nap``. A stubbed nap once
  turned a 2000-comment video into a 5-row crawl that looked like success.
"""

import contextlib
import json
import math
import re
import time

from selenium.common.exceptions import JavascriptException, StaleElementReferenceException

from i18n import t

from .comments_base import BLOCKED, DEAD, OK, _json_or_none
from .comments_bilibili import bilibili_reply_js, bilibili_view_js, parse_bilibili_comments
from .comments_douyin import douyin_comment_fields, parse_douyin_comments
from .comments_twitter import parse_twitter_replies
from .comments_weibo import parse_weibo_comments, weibo_bid, weibo_comments_js, weibo_show_js
from .comments_xhs import parse_xhs_comments
from .comments_youtube import parse_youtube_comments
from .comments_zhihu import parse_zhihu_comments
from .engine import feed, pagefetch, pager
from .engine.counters import parse_count
from .engine.jsonpath import collect
from .engine.wall import looks_blocked

# The browser-free parsers and the shared text helpers live in their own modules,
# one per platform (``comments_weibo.py``, ``comments_bilibili.py`` …) plus
# ``comments_base.py`` for the parts several of them share. They are re-exported
# above so ``from crawlers.comments import parse_weibo_comments, OK, …`` keeps
# working, and this file holds only the stateful :class:`CommentSession` that
# drives one browser per platform and calls them. ``platform_for`` (the
# article-link → adapter router) lives in utils.helpers: the engine validator
# needs the same table without importing any crawler.


class CommentSession:
    """One browser session per platform; the node handler owns lifecycle."""

    def __init__(self, driver, log=None, nap=None, abort=None, owner=None):
        self._driver = driver
        # The crawler whose browser this is, when there is one. Held rather than flattened
        # into the snapshot above because 停止 may *replace* the session under the crawl:
        # the reaper installs a :class:`~crawlers.base.DeadDriver` once it has had to kill
        # the process by PID, and a session that read its own stored reference would go on
        # asking a dead chromedriver — 16.3 seconds per command, measured, one retry ladder
        # per row of a walk that is already over.
        self._owner = owner
        self.log = log or (lambda msg: None)
        self.nap = nap or time.sleep
        # "May I stop?" — the same predicate the crawlers carry, because a comment
        # node reads hundreds of pages and the node handler only asks between URLs.
        self._abort = abort

    @property
    def driver(self):
        """The session as it is *now*, not as it was when the walk started."""
        return self._owner.driver if self._owner is not None else self._driver

    def may_stop(self) -> bool:
        return bool(self._abort is not None and self._abort())

    # -- low-level helpers -------------------------------------------------

    def _in_page_fetch(self, url: str, timeout_ms: int = 25000) -> str:
        # The mechanics live in engine.pagefetch (one home for the three page-context
        # fetch shapes); the comment engine wants the raw text so it can read wall
        # wording out of an HTML body a JSON parse would discard.
        return pagefetch.fetch_text(self.driver, url, timeout=timeout_ms / 1000)

    def _body_head(self, limit: int = 600) -> str:
        with contextlib.suppress(Exception):
            return self.driver.find_element('css selector', 'body').text[:limit]
        return ''

    def _safe_text(self, element) -> str:
        with contextlib.suppress(Exception):
            return (element.text or '').strip()
        return ''

    # -- weibo -------------------------------------------------------------

    def crawl_weibo(self, url: str, limit: int) -> tuple:
        bid = weibo_bid(url)
        if not bid:
            return [], DEAD
        try:
            # The in-page fetch is same-origin only: a search flow leaves the
            # browser on s.weibo.com, where fetching weibo.com/ajax is a CORS
            # rejection that reads as a dead link. Park on the right host first.
            current = self.driver.current_url or ''
            if not current.startswith('https://weibo.com'):
                self.driver.get('https://weibo.com/')
                self.nap(2)
        except Exception:
            pass
        try:
            raw = self._in_page_fetch(weibo_show_js(bid))
            show = json.loads(raw)
        except Exception:
            self.log(t('comment.weiboShowFailed', url=url))
            return [], DEAD
        mid = str(show.get('id') or show.get('mid') or '')
        if not mid:
            return [], DEAD
        rows, max_id, page = [], 0, 0
        while True:
            try:
                batch = json.loads(self._in_page_fetch(weibo_comments_js(mid, max_id)))
            except Exception:
                break
            items = batch.get('data') or []
            rows.extend(parse_weibo_comments({'data': items}, url))
            page += 1
            max_id = batch.get('max_id') or 0
            if not items or not max_id or (limit and len(rows) >= limit) or page >= 30:
                break
            self.nap(0.8)  # polite page interval on the comment API
        return (rows[:limit] if limit else rows), OK

    # -- xiaohongshu --------------------------------------------------------

    def crawl_xiaohongshu(self, url: str, limit: int) -> tuple:
        self.driver.get(url)
        self.nap(5)
        if looks_blocked(self._body_head()):
            return [], BLOCKED
        seen, rows = set(), []
        for _round in range(12):
            found = []
            for card in self.driver.find_elements('css selector', '.comment-item'):
                author = self._first_text(card, '.author-wrapper .name, .name')
                text = self._first_text(card, '.content')
                date = self._first_text(card, '.date')
                likes = self._first_number(card, '.like .count, .like-wrapper .count')
                key = (author, text)
                if not text or key in seen:
                    continue
                seen.add(key)
                found.append((url, author, text, date, likes))
            rows.extend(parse_xhs_comments(found))
            if not found or (limit and len(rows) >= limit):
                break
            self._scroll_comments()
            self.nap(1.2)
        return (rows[:limit] if limit else rows), OK

    def _first_text(self, root, selector) -> str:
        for el in root.find_elements('css selector', selector):
            text = self._safe_text(el)
            if text:
                return text
        return ''

    def _first_number(self, root, selector) -> int:
        text = self._first_text(root, selector)
        m = re.search(r'\d+', text or '')
        return int(m.group()) if m else 0

    def _scroll_comments(self):
        script = """
        var box = document.querySelector('.note-scroller') || document.scrollingElement || document.body;
        var step = box === document.body ? 1200 : box.scrollHeight;
        box.scrollBy(0, step);
        window.scrollBy(0, 800);
        """
        with contextlib.suppress(Exception):
            self.driver.execute_script(script)

    # -- zhihu --------------------------------------------------------------

    def crawl_zhihu(self, url: str, limit: int) -> tuple:
        self.driver.get(url)
        self.nap(6)
        head = self._body_head()
        if looks_blocked(head):
            return [], BLOCKED
        opened = 0
        rows = []
        for btn in list(self.driver.find_elements('css selector', 'button')):
            text = self._safe_text(btn)
            match = re.search(r'(\d+)\s*条评论', text)
            if not match:
                continue
            # The button's own number is carried into the walk: it is the figure the user can read
            # off the page, so it is the only honest denominator for 「did we get them all」.
            declared = int(match.group(1))
            with contextlib.suppress(Exception):
                self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', btn)
                self.nap(0.4)
                btn.click()
                opened += 1
                self.nap(2)
                rows.extend(self._drain_comment_panel(url, limit, declared))
            if limit and len(rows) >= limit:
                break
        if not opened and rows == []:
            # No comment button at all: either 评论已关闭 or the page never
            # rendered the answers — treat as ok-with-nothing, but say so.
            self.log(t('comment.zhihuNoPanels', url=url))
        return (rows[:limit] if limit else rows), OK

    #: One read per panel, in the page. The shape of this script is the measurement
    #: (``backend/test_zhihu_comment_dom.py``): the author anchor lives at the FIRST ancestor of
    #: ``.CommentContent`` for most items, but 2 of 12 items on a real panel answered only at
    #: depth 4 — inside a node that already spans their neighbours. A fixed-depth climb therefore
    #: returns either ``''`` or, worse, the person who posted next door. So the climb is bounded
    #: by a structural fact instead: stop as long as the candidate still holds exactly one
    #: comment body. That node is this comment, and nothing read inside it can belong to another.
    #:
    #: The time pattern covers both shapes the panel uses (relative for recent, absolute for old).
    #: No like count is looked for: measured over 22 items, neither an ``aria-label``, a button
    #: nor a bare number carries one, and a column of invented zeros is a worse answer than a
    #: blank one (see :func:`parse_zhihu_comments`).
    _ZHIHU_PANEL_JS = r"""
return (function () {
    var TIME = /(\d+\s*(分钟|小时|天|个月|年)前|\d{4}-\d{1,2}-\d{1,2}|昨天|今天|\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2})/;
    function bodyText(el) {
        return (el.textContent || '').replace(/\s+/g, ' ').trim();
    }
    function ownScope(node) {
        var best = node, up = node.parentElement;
        while (up && up.querySelectorAll('.CommentContent').length === 1) {
            best = up;
            up = up.parentElement;
        }
        return best;
    }
    var out = [];
    var bodies = document.querySelectorAll('.CommentContent');
    for (var i = 0; i < bodies.length; i++) {
        var text = bodyText(bodies[i]);
        if (!text) { continue; }
        var scope = ownScope(bodies[i]);
        var author = '', href = '';
        var links = scope.querySelectorAll('a[href*="/people/"]');
        for (var p = 0; p < links.length; p++) {
            var name = bodyText(links[p]);
            if (name) { author = name; href = links[p].href || ''; break; }
        }
        var when = '';
        var leaves = scope.querySelectorAll('span, time, div');
        for (var s = 0; s < leaves.length; s++) {
            if (leaves[s].children.length) { continue; }
            var hit = bodyText(leaves[s]).match(TIME);
            if (hit) { when = hit[0]; break; }
        }
        var parent = -1;
        var enclosing = bodies[i].parentElement ? bodies[i].parentElement.closest('.CommentContent') : null;
        if (enclosing) {
            for (var q = 0; q < bodies.length; q++) {
                if (bodies[q] === enclosing) { parent = q; break; }
            }
        }
        out.push({text: text, author: author, href: href, time: when, parent: parent});
    }
    return out;
})();
"""

    #: Scroll the panel's OWN box to its bottom. Measured (``backend/test_zhihu_comment_structure.py``):
    #: zhihu has no 「更多」 control on a comment panel at all — the list is lazy-filled by the
    #: container (class ``css-34podr``, whose ``scrollHeight`` grew 1302 → 12733 on one answer), and
    #: scrolling the WINDOW changes nothing (12 items before, 12 after). So this, not a button hunt,
    #: is what feeds the list. Returns how far the box moved, which is the caller's evidence that a
    #: bottom was reached and re-read.
    _ZHIHU_PUMP_JS = r"""
return (function () {
    var boxes = [].slice.call(document.querySelectorAll('div, section, ul')).filter(function (n) {
        return n.scrollHeight > n.clientHeight + 200 && n.querySelectorAll('.CommentContent').length;
    });
    if (!boxes.length) { return -1; }
    // The box that holds the MOST comments, not the first one found. Measured reason: opening a
    // reply thread adds an inner scrollable list that also holds ``.CommentContent`` nodes, so a
    // first-match pump can end up scrolling one reply's own list forever while the panel above it
    // never advances — a walk that stalls and stops, reporting a short table as a finished one.
    var best = boxes[0];
    for (var i = 1; i < boxes.length; i++) {
        if (boxes[i].querySelectorAll('.CommentContent').length > best.querySelectorAll('.CommentContent').length) {
            best = boxes[i];
        }
    }
    var before = best.scrollTop;
    best.scrollTop = best.scrollHeight;
    return best.scrollTop - before;
})();
"""

    #: How many pump-and-read rounds one panel may take, and how many of them must come back with
    #: nothing new (and no reply thread left to open) before the walk believes the panel is done.
    #: Both numbers are a *budget the crawler imposes*, so reaching the first one is announced:
    #: measured, a 261-comment panel needs ~26 fills of ~10 items, and the alternative to naming
    #: the budget is reporting 12 rows as if the site had nothing more (docs/live_test_plan.md §6).
    ZHIHU_PANEL_ROUNDS = 60
    ZHIHU_QUIET_ROUNDS = 3

    #: The nested-reply opener's own words: 「展开其中 2 条回复」 / 「查看 3 条回复」 / 「全部回复」.
    #: The count and the wording between the verb and 回复 both vary (「其中」 is in one of them), so
    #: the match is on the verb-plus-回复 shape rather than an exact phrase. Every one of these is a
    #: bucket of comments that does not exist in the DOM until clicked (measured: +5 and +29 rows on
    #: two answers), so an un-clicked expander is 漏采 by construction.
    ZHIHU_REPLY_OPENER = re.compile(r'(查看|展开).{0,8}回复|全部回复')

    def _click_zhihu_reply_threads(self) -> int:
        """Open every visible 「N 条回复」 thread, so nested comments exist to be read."""
        clicked = 0
        for el in list(self.driver.find_elements('css selector', 'button, a')):
            text = self._safe_text(el)
            if not text or not self.ZHIHU_REPLY_OPENER.search(text):
                continue
            with contextlib.suppress(Exception):
                self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', el)
                self.nap(0.2)
                el.click()
                clicked += 1
                self.nap(0.4)
        return clicked

    def _drain_comment_panel(self, url: str, limit: int, declared: int = 0) -> list:
        collected, seen = [], set()
        quiet = 0
        rounds = 0
        while rounds < self.ZHIHU_PANEL_ROUNDS:
            rounds += 1
            self.driver.execute_script(self._ZHIHU_PUMP_JS)
            self.nap(0.6)
            threads = self._click_zhihu_reply_threads()
            batch = self.driver.execute_script(self._ZHIHU_PANEL_JS) or []
            fresh = []
            for row in parse_zhihu_comments(url, batch):
                key = (row['评论者'], row['评论内容'])
                if key in seen:
                    continue
                seen.add(key)
                fresh.append(row)
            if fresh:
                self.log(t('comment.zhihuRound', n=len(fresh), total=len(collected) + len(fresh), r=rounds))
            collected.extend(fresh)
            unnamed = sum(1 for row in fresh if not row['评论者'])
            if unnamed:
                # Said once per panel, about a count: an empty 评论者 is a site answer for some
                # rows and a dead selector for others, and the only way the two are told apart
                # later is that this line exists with a number in it.
                self.log(t('comment.zhihuNoAuthor', n=unnamed, total=len(fresh)))
            if limit and len(collected) >= limit:
                return collected[:limit]
            if not fresh and not threads:
                quiet += 1
                if quiet >= self.ZHIHU_QUIET_ROUNDS:
                    break
            else:
                quiet = 0
        if rounds >= self.ZHIHU_PANEL_ROUNDS:
            self.log(t('comment.zhihuPanelCapped', n=self.ZHIHU_PANEL_ROUNDS, rows=len(collected)))
        if declared and len(collected) < declared:
            # The site's own number is the denominator the user reads off the page; anything short
            # of it is said out loud, because 「the panel had 12」 and 「we stopped at 12 of 261」 are
            # two different reports and only one of them is checkable.
            self.log(t('comment.zhihuPanelShort', declared=declared, rows=len(collected)))
        return collected

    # -- bilibili -------------------------------------------------------------

    def crawl_bilibili(self, url: str, limit: int) -> tuple:
        """One video's comments, walked through ``x/v2/reply/main``.

        Paging follows the server's cursor rather than a counter, because the
        counter is a trap that this project measured the hard way: ``next=0``
        answers and reports ``cursor.next=2``, and a request for ``next=1``
        replays page 0 identically. Incrementing would therefore store the first
        19 comments over and over and still claim to have reached the limit, so
        the walk stops on a page that carries no new ``rpid`` — which is also
        what makes a repeating server-side cursor harmless.
        """
        from .bilibili import CODE_GONE, bilibili_bvid

        self.driver.get(url)
        self.nap(3)
        if looks_blocked(self._body_head()):
            return [], BLOCKED
        bvid = bilibili_bvid(url)
        if not bvid:
            return [], DEAD
        view = _json_or_none(self._in_page_fetch(bilibili_view_js(bvid)))
        if not view or view.get('code') != 0:
            return [], (DEAD if (view or {}).get('code') == CODE_GONE else BLOCKED)
        data = view.get('data') or {}
        aid = data.get('aid')
        if not aid:
            return [], DEAD
        if not int((data.get('stat') or {}).get('reply') or 0):
            # The author closed the comment section: that is an answer, not a
            # failure, and it has to read as 无评论 rather than as a dead link.
            self.log(t('comment.commentsClosed', url=url))
            return [], OK
        rows, cursor, seen, guard = [], 0, set(), 0
        while guard < 200:
            guard += 1
            payload = _json_or_none(self._in_page_fetch(bilibili_reply_js(aid, cursor)))
            if not payload or payload.get('code') != 0:
                if rows:
                    break  # a later page failing still keeps what we collected
                self.log(t('comment.biliBadAnswer', url=url, code=(payload or {}).get('code')))
                return [], BLOCKED
            page = payload.get('data') or {}
            items = [r for r in (page.get('replies') or []) if str(r.get('rpid')) not in seen]
            if not items:
                break
            for item in page.get('replies') or []:
                seen.add(str(item.get('rpid')))
            rows.extend(parse_bilibili_comments(items, url, floor=len(rows)))
            info = page.get('cursor') or {}
            if info.get('is_end') or (limit and len(rows) >= limit):
                break
            cursor = int(info.get('next') or (cursor + 1))
            self.nap(0.8)  # polite page interval on the comment API
        return (rows[:limit] if limit else rows), OK

    # -- twitter (X) ------------------------------------------------------------

    def crawl_twitter(self, url: str, limit: int) -> tuple:
        """One post's replies, read off its own permalink page.

        X has no readable comment endpoint for a browser session (its GraphQL needs
        a transaction label the page mints per request), so this is a DOM walk —
        and the DOM is virtualized, so the same rules as the timeline apply:
        progress is measured by rows kept, and identity by the reply's status id
        (measured: 13-21 ``<article>`` nodes on screen while 139 distinct replies
        passed through in eight scrolls).
        """
        from .engine import feed
        from .twitter import EXTRACT_CARD_JS, WINDOW_LINKS_JS, TwitterCrawler, tweet_id_of

        root = tweet_id_of(url)
        if not root:
            return [], DEAD

        def cards_of():
            return self.driver.find_elements('css selector', TwitterCrawler.CARD_SELECTOR)

        self.driver.get(url if 'x.com/' in url or 'twitter.com/' in url else f'https://x.com/i/status/{root}')
        # Waited for, not slept: the permalink is an app route that fetches its own
        # thread and measured ~12 s to its first rendered card on a connection that
        # was fine. A fixed nap ended the walk on a page that had not painted, and
        # an empty page is what the walk reports as a dead link.
        feed.wait_for(lambda: len(cards_of()), 1, timeout=TwitterCrawler.MOUNT_WAIT)
        if looks_blocked(self._body_head()):
            return [], BLOCKED

        rows: list[dict] = []
        seen: set[str] = set()

        def scrape(card, index):
            try:
                data = self.driver.execute_script(EXTRACT_CARD_JS, card)
            except (StaleElementReferenceException, JavascriptException):
                # The reply list recycles its nodes while the walk is reading them;
                # the post is still unseen, so a later round reads it off a new handle.
                return None
            parsed = parse_twitter_replies([data], url, root)
            if not parsed:
                return None
            row = parsed[0]
            return None if row['评论ID'] in seen else row

        def keep(row):
            seen.add(row['评论ID'])
            rows.append(row)
            return True

        walk = feed.walk_feed(
            cards_of,
            scrape,
            keep,
            scroll=lambda: self._scroll_replies(),
            target=limit or math.inf,
            collected=lambda: len(rows),
            # Same rule as the timeline: the reply list recycles its nodes, so the
            # walk waits for the ids on screen to change, not for more nodes.
            window=lambda: str(self.driver.execute_script(WINDOW_LINKS_JS) or ''),
            stuck_rounds=3,
            settle_wait=4.0,
            stopped=self.may_stop,
        )
        if not rows and walk.stopped_reason == 'no_cards':
            self.log(t('comment.xNoList', url=url))
            return [], DEAD
        if not rows:
            # The page mounted and there is still nothing under the post: replies
            # are closed, or nobody answered. That is a fact about the tweet and it
            # reads as the same line the other platforms say — not as a failed crawl.
            self.log(t('comment.commentsClosed', url=url))
        return rows, OK

    def _scroll_replies(self):
        """Scroll the reply page the way a person does, then let it settle."""
        self.driver.execute_script('window.scrollBy(0, window.innerHeight * 1.4);')
        self.nap(1.2)

    # -- youtube --------------------------------------------------------------

    def crawl_youtube(self, url: str, limit: int) -> tuple:
        """One video's comments, read as JSON instead of by scrolling the panel.

        The panel is real — it grows by token, 20 comments a round — but reading it
        would pay a rendered screen per round when the page itself is fetching the
        same objects as JSON in ~0.3 s. So the walk is the browser's own:
        ``next(videoId)`` for the pager, then ``next(continuation=…)`` per round.

        The first round is a *search* for the working token rather than a fixed
        pick, and that is measured, not caution: a watch answer carries six
        continuation tokens (the comment pager, the related-video rail twice, the
        sort menu twice and one more), and the comment pager's length is not even
        stable across videos — 78 characters on one, 146 on another, while the
        rail's are 1412. So each candidate is asked, in document order, until one
        answers with comments.

        After that first page the rule is stricter, because a wrong token here is
        worse than a failed one: a round carries the real pager at the end of the
        comment list *and* two sort-menu tokens that both answer **page one again**.
        Following a sort token re-reads the same twenty comments, the ledger refuses
        them all as duplicates, the walk reports success — and a video with three
        thousand comments yields twenty. So the cursor is taken from the list the
        rows actually came from (``innertube.pager_of``).
        """
        from .engine import innertube
        from .youtube import video_id_of

        video = video_id_of(url)
        if not video:
            return [], DEAD
        self.driver.get(f'https://www.youtube.com/watch?v={video}')
        found = innertube.ready(self.driver)
        if not found:
            # No API config means the page never booted as a watch page. Which
            # reason it was changes what the user does next, so the page itself
            # gets the last word.
            if looks_blocked(self._body_head()):
                return [], BLOCKED
            self.log(t('comment.ytNoPage', url=url))
            return [], DEAD
        key, context = found
        watch = innertube.call(self.driver, 'next', key, context, {'videoId': video})
        if innertube.refused(watch):
            return [], BLOCKED

        rows: list[dict] = []
        seen: set[str] = set()
        #: The pager of the list the last answer's rows came from. One entry by
        #: construction — a round carries several tokens and only that one pages
        #: this list, which is why it is selected by position rather than tried.
        candidates: list[str] = []

        def fetch(token):
            # dict.fromkeys keeps first-seen order while dropping the duplicate the
            # first round used to make: with no alternates yet, ``token`` and the
            # seeded ``candidates`` were the same continuation, so the identical
            # token was POSTed twice before giving up.
            order = list(dict.fromkeys(candidate for candidate in [token, *candidates] if candidate))[:3]
            for candidate in order:
                payload = innertube.call(self.driver, 'next', key, context, {'continuation': candidate})
                if innertube.refused(payload):
                    return None
                if collect(payload, 'commentEntityPayload'):
                    return payload
            return {}

        def extract(payload):
            nonlocal candidates
            page = parse_youtube_comments(payload, url)
            # The list holds ``commentThreadRenderer`` entries while the comment
            # text itself arrives beside it under frameworkUpdates, so the marker
            # that identifies *this* list is the thread renderer — asking for
            # commentEntityPayload would find no list at all and stop the walk.
            read = innertube.pager_of(payload, 'commentThreadRenderer')
            candidates = [read] if read else []
            return page, (candidates[0] if candidates else None)

        chosen = ''
        for token in innertube.pager_tokens(watch):
            candidates = [token]
            attempt = fetch(token)
            if attempt is None:
                return [], BLOCKED
            if attempt:
                chosen = token
                break
        if not chosen:
            # Nothing paged the comments: the author turned them off, or the video
            # has none. Either way that is an answer, and it has to read as
            # 无评论 rather than as a failed crawl.
            self.log(t('comment.commentsClosed', url=url))
            return [], OK

        def keep(row):
            rows.append(row)
            return True

        # The chosen token is fetched a second time here, which costs one 0.3 s
        # round: the alternative is to hand the pager a half-consumed page, and a
        # walk that starts from something other than its own cursor is how rows go
        # missing silently.
        walk = pager.walk_pages(
            fetch,
            extract,
            keep,
            start_cursor=chosen,
            collected=lambda: len(rows),
            target=limit or math.inf,
            seen=seen,
            identity=lambda row: row['评论ID'],
            polite=lambda: self.nap(0.35),
            # The pager's own stop check: a comment walk can be asked for hundreds of
            # pages, and the node handler only looks between URLs.
            alive=lambda: not self.may_stop(),
        )
        if not rows and walk.stopped_reason == 'fetch_failed':
            return [], BLOCKED
        return rows, OK

    # -- douyin ---------------------------------------------------------------

    def crawl_douyin(self, url: str, limit: int) -> tuple:
        """Scroll the rendered comment panel; douyin's API is signed.

        Unlike bilibili, the comments ARE in the DOM (``[data-e2e="comment-item"]``)
        and they grow by scrolling the app's own route container — measured 16 rows
        becoming 56 — while ``window.scrollTo`` does nothing at all. The panel's
        request carries ``a_bogus``/``msToken``, so there is no endpoint to call.

        「展开N条回复」 is read as a count and never clicked: expanding a thread
        rewrites the list under the next read, and the count is the fact the user
        needs (this comment has N replies) either way.
        """
        from .douyin import douyin_id

        target = f'https://www.douyin.com/video/{douyin_id(url)}' if douyin_id(url) else url
        if not douyin_id(url):
            self.log(t('comment.dyNoId', url=url))
            return [], DEAD
        self.driver.get(target)
        mounted = self._wait_for_douyin_panel()
        if looks_blocked(self._body_head()):
            return [], BLOCKED
        reported = self._node_text('[data-e2e="feed-comment-icon"]')
        if not mounted:
            if not reported:
                # Neither a panel nor the counter that would explain its absence:
                # that is not "no comments", and reporting it as one would hide a
                # dead session behind an empty table.
                self.log(t('comment.dyNoPanel', url=target))
                return [], BLOCKED
            self.log(t('comment.dyNone', url=target, n=parse_count(reported)))
            if parse_count(reported) == 0:
                # The counter says none exist: an answer, not a failed read.
                return [], OK
            # The video says it has comments and the list never opened — a page
            # we could not read, which must never arrive as an empty table.
            return [], BLOCKED
        seen, rows = set(), []
        for _round in range(40):
            found = []
            for item in self.driver.find_elements('css selector', '[data-e2e="comment-item"]'):
                author, content, when, region, likes, subs = douyin_comment_fields(self._safe_text(item))
                key = (author, content, when)
                if not content or key in seen:
                    continue
                seen.add(key)
                found.append((target, author, content, when, region, likes, subs))
            rows.extend(parse_douyin_comments(found))
            if not found:
                break
            if limit and len(rows) >= limit:
                break
            if not self._scroll_douyin_panel():
                break
            self.nap(1.5)
        if not rows:
            # A panel of items that produced nothing is a parser or page problem,
            # never a fact about the video.
            self.log(t('comment.dyNoPanel', url=target))
            return [], BLOCKED
        return (rows[:limit] if limit else rows), OK

    def _wait_for_douyin_panel(self, timeout: float = 24.0) -> bool:
        """Poll until the comment list actually holds items.

        Measured: the ``[data-e2e="comment-list"]`` container mounts on the route
        *before* its first comment is rendered, so treating the container as
        "mounted" let a crawl read an empty list, break out of the loop on the
        first pass and return zero rows as a success. The item is the evidence.
        """
        ticks = max(1, int(timeout / 2.0))
        for _ in range(ticks):
            if self.driver.find_elements('css selector', '[data-e2e="comment-item"]'):
                return True
            time.sleep(2.0)
        return False

    def _node_text(self, selector: str) -> str:
        element = self._element_or_none(selector)
        return self._safe_text(element) if element is not None else ''

    def _scroll_douyin_panel(self) -> bool:
        """Scroll whatever really scrolls on this page (the route container).

        Returns whether the panel grew. The settle wait is polled here rather
        than delegated to ``self.nap``: the rows mount asynchronously, so a
        caller that stubs the nap (any test, and any caller that wants a fast
        run) would read the pre-scroll count, conclude the list was exhausted
        and stop after one screen — which is exactly how a 5-row crawl of a
        2000-comment video once happened.

        The scroll itself is the shared one (:func:`engine.feed.jump_to_bottom`)
        because the douyin 作品 grid pages off the same route container and needs
        the identical surface hunt; a second copy of this loop is what the engine
        rule exists to prevent.
        """

        def count() -> int:
            return len(self.driver.find_elements('css selector', '[data-e2e="comment-item"]'))

        before = count()
        with contextlib.suppress(Exception):
            feed.jump_to_bottom(self.driver, '[data-e2e="comment-list"]')
        return bool(feed.wait_for(count, before + 1, timeout=6.0, tick=0.5) > before)

    def _element_or_none(self, selector: str):
        try:
            return self.driver.find_element('css selector', selector)
        except Exception:
            return None
