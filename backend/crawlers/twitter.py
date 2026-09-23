"""X (推特): a visible-window DOM crawl of a virtualized timeline.

Measured on the live site in 2026-9 (scratchpad/x_map.json, x_detail.json,
x_crawl.json, x_counts.json), and every one of these facts changed a line of code
below:

* **A headless browser is refused outright.** ``/search`` renders the sign-up
  sheet and zero tweets, and a profile answers "Access to x.com was denied …
  HTTP ERROR 403". So ``never_headless = True`` and the executor buys a visible
  window for it, exactly as it does for douyin — but for the opposite reason:
  douyin blocks the *mode*, X blocks the *window type*.
* **The feed is virtualized.** ``article[data-testid="tweet"]`` holds 13-21 nodes
  however far you scroll, while 139 distinct tweets passed through in eight
  scrolls. So the walk waits for the *window of ids on screen* to change
  (``feed.walk_feed(window=…)`` and :meth:`TwitterCrawler.window_key`), never for
  the card count, and a row's identity is its status id — never an index into a
  list that is rebuilt underneath it.
* **One ``execute_script`` per card, not twelve ``find_element`` calls.** The card
  read is a single in-page extraction returning plain JSON; the Python side turns
  that into a row. On a 50-row crawl this is the difference of roughly a minute.
* **The counters are one sentence.** A ``[role="group"]`` aria-label carries
  "1887 replies, 7746 reposts, 49483 likes, 6045 bookmarks, 1.1M views" for the
  whole row — parsed here rather than read from five buttons, and parsed with the
  shared 万/K/M parser so "1.1M views" is 1100000 and not 1. It names **only what
  exists**: a screen of live replies read "1 like, 1 view" and "19 views", which is
  why a zero here means the site showed nothing, and why 浏览数 can only ever come
  from this sentence (no button carries it).
* **A screen takes ~12 s to paint.** Measured polling ``/search`` after a
  navigation on a good connection: 0 cards at 9.9 s, 11 at 11.9 s. An 8-second
  settle therefore reported "this keyword found nothing" about a search that was
  about to succeed — hence :attr:`TwitterCrawler.MOUNT_WAIT`, which is a poll and
  costs nothing when the page is quick.
* **A card can vanish between listing it and reading it.** The recycler detaches
  nodes, and ``execute_script`` on one raised ``StaleElementReferenceException``
  during measurement, so the read is guarded: the tweet is not marked seen and a
  later round picks it up off a fresh handle.
* **``time[datetime]`` is ISO UTC**, which is the only publish time the site
  gives: the visible label is relative ("13s", "15h") and drifts while a crawl
  runs, so storing it would make 发布时间 mean a different moment in every row.
* An href like ``/Lowes/status/209801…/analytics`` **is on the card** and looks
  like the permalink: the id pattern is anchored to the end for that reason.
* **A caption-less photo post has no text node at all** (measured: no
  ``div[data-testid="tweetText"]``, one ``pbs.twimg.com`` image). So an empty 正文
  is a real answer rather than a failed read, and the row keeps its 图片数 — a
  reader that demanded text would drop posts the user searched for, and one that
  filled it in would write a caption the site never sent.

Comments (a tweet's replies) are read by the same walk on the tweet's own page —
see ``CommentSession.crawl_twitter`` in ``crawlers/comments.py``.
"""

import logging
import re
from urllib.parse import quote

from selenium.common.exceptions import JavascriptException, StaleElementReferenceException
from selenium.webdriver.common.by import By

from i18n import t

from .base import Crawler
from .engine import feed
from .engine.counters import parse_count

logger = logging.getLogger(__name__)

#: What one card is asked for, in one round trip. Every selector below is the
#: site's own (``data-testid`` names, measured on the live page); the values come
#: back as plain data so the row-shaping logic is testable without a browser.
EXTRACT_CARD_JS = """
var root = arguments[0];
function text(sel) {
    var e = root.querySelector(sel);
    return e ? (e.innerText || '').trim() : '';
}
function attr(sel, name) {
    var e = root.querySelector(sel);
    return e ? (e.getAttribute(name) || '') : '';
}
var link = '', tweetId = '';
var anchors = root.querySelectorAll('a');
for (var i = 0; i < anchors.length; i++) {
    var h = anchors[i].getAttribute('href') || '';
    // Anchored to the end on purpose: a card also carries
    // /<user>/status/<id>/analytics, and an unanchored match stores that as the
    // post's permalink and its id with "/analytics" glued on the end.
    var m = h.match(/^\\/([^/]+)\\/status\\/(\\d+)\\/?$/);
    if (m && !link) { link = h; tweetId = m[2]; }
}
var labels = {};
var group = root.querySelector('[role="group"]');
if (group) labels.group = group.getAttribute('aria-label') || '';
['reply', 'retweet', 'like', 'bookmark'].forEach(function (key) {
    var e = root.querySelector('[data-testid="' + key + '"]');
    if (e) labels[key] = e.getAttribute('aria-label') || '';
});
var images = [];
root.querySelectorAll('div[data-testid="tweetPhoto"] img').forEach(function (img) {
    var src = img.getAttribute('src') || '';
    if (src && images.indexOf(src) < 0) images.push(src);
});
var time = root.querySelector('time');
return {
    text: text('div[data-testid="tweetText"]'),
    user: text('div[data-testid="User-Name"]'),
    iso: time ? (time.getAttribute('datetime') || '') : '',
    link: link,
    tweetId: tweetId,
    images: images,
    video: !!root.querySelector('div[data-testid="videoPlayer"]'),
    quote: !!root.querySelector('div[data-testid="quoteTweet"]'),
    card: !!root.querySelector('div[data-testid="card.wrapper"]'),
    poll: !!root.querySelector('div[data-testid="card Poll"]'),
    labels: labels,
};
"""

_COUNTER_RE = re.compile(r'([\d.,]+\s*[KMB万千万]?)\s*(replies|reposts|likes|bookmarks|views)', re.I)
#: Which tweet links are on screen right now. This string — not the card count —
#: is what tells a scroll on a virtualized timeline that the window moved.
WINDOW_LINKS_JS = """
var out = [];
document.querySelectorAll('article[data-testid="tweet"] a[href*="/status/"]').forEach(function (a) {
    var h = a.getAttribute('href') || '';
    var m = h.match(/^\\/[^/]+\\/status\\/(\\d+)/);
    if (m && out.indexOf(m[1]) < 0) out.push(m[1]);
});
return out.join(',');
"""

#: The group sentence's word → the column it fills.
_LABEL_TO_COLUMN = {
    'replies': '评论数',
    'reposts': '转发数',
    'likes': '点赞数',
    'bookmarks': '收藏数',
    'views': '浏览数',
}
#: The action buttons' own ``data-testid`` → the same columns. Spelled apart
#: because the two vocabularies are the site's, not ours: the sentence says
#: "likes", the button is ``data-testid="like"``.
_BUTTON_TO_COLUMN = {
    'reply': '评论数',
    'retweet': '转发数',
    'like': '点赞数',
    'bookmark': '收藏数',
}


def parse_counters(labels: dict) -> dict:
    """The group sentence (or the individual buttons) → the five count columns.

    ``[role="group"]`` is tried first because it is one read carrying all five;
    the per-button labels are the fallback, since a promoted or third-party card
    renders the action buttons without that group. A number nobody showed stays
    0 rather than becoming a guess.
    """
    out = dict.fromkeys(_LABEL_TO_COLUMN.values(), 0)
    group = str((labels or {}).get('group') or '')
    pairs = _COUNTER_RE.findall(group)
    if pairs:
        for value, name in pairs:
            column = _LABEL_TO_COLUMN.get(name.lower())
            if column:
                out[column] = parse_count(value)
        return out
    for key, column in _BUTTON_TO_COLUMN.items():
        found = _COUNTER_RE.findall(str((labels or {}).get(key) or ''))
        if found:
            out[column] = parse_count(found[0][0] + found[0][1])
    return out


def split_author(user_text: str) -> tuple[str, str]:
    """``Lisa\\n@devtrotter_fr\\n·\\n13s`` → (display name, @handle).

    The handle is what a profile URL is built from, and it is the only part of
    that block that is stable: the display name is free text (it can contain
    newlines) and the trailing relative time changes while a crawl runs.
    """
    lines = [line.strip() for line in str(user_text or '').split('\n') if line.strip()]
    handle = next((line for line in lines if line.startswith('@')), '')
    name = lines[0] if lines and not lines[0].startswith('@') else handle.lstrip('@')
    return name, handle


def iso_stamp(value: str) -> str:
    """``2026-09-23T09:21:41.000Z`` → ``2026-09-23 09:21`` (UTC, as the site sends it).

    The relative label the user sees ("13s", "15h") is not stored: it would put a
    different moment in the same column depending on when the row was read.
    """
    text = str(value or '').strip()
    match = re.match(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})', text)
    if match:
        return f'{match.group(1)} {match.group(2)}'
    return text[:16].replace('T', ' ')


def permalink(link: str, tweet_id: str = '') -> str:
    """The post's own address, cut at ``/status/<id>`` and made absolute.

    A card carries several ``/status/<id>`` links — the timestamp, the analytics
    page, a quoted post — and the extractor takes the first it finds. Measured on
    a promoted card: ``/Lowes/status/2098015709662167492/analytics``. Storing
    that as the row's 链接 means the user gets a page they cannot open and a
    推文ID that matches nothing, so the address is cut at the id.
    """
    text = str(link or '').strip()
    if text and not text.startswith('/'):
        return re.sub(r'(/status/\d+).*$', r'\1', text)
    match = re.match(r'^(/[^/]+/status/\d+)', text)
    path = match.group(1) if match else (f'/i/status/{tweet_id}' if tweet_id else '')
    return f'https://x.com{path}' if path else ''


def row_from_card(card: dict) -> dict | None:
    """One extracted card → a row, or None when the card holds nothing.

    Two cards are dropped, and both were measured rather than imagined:

    * one with **no status id**, which cannot be traced back to a tweet;
    * one with **no body of any kind**. X's own permalink rendered such a card as a
      header, a timestamp, "812 views" and five zeroed buttons — no text node, no
      photo, no video, no link card, nothing. It is a real address, and every
      downstream node (清洗, 情感, 词频) would read the row as empty, so a table
      holding it looks like a finished crawl that collected something.

    A caption-less **photo post is kept**: that card genuinely has no text node
    either, but it carries an image, which is the content the user searched for.

    Dropping a body-less card cannot lose a post that was merely slow to paint:
    a virtualized walk re-reads the whole rendered window every round (see
    :meth:`TwitterCrawler._walk`), and nothing is added to ``seen`` until it has
    produced a row — so the same node gets read again a round later, with its body
    present, if it had one coming.

    No row carries the keyword that found it: provenance lives in the run record,
    no other platform stamps its table with it, and 作者 mode has none to stamp.
    """
    if not isinstance(card, dict) or not card.get('tweetId'):
        return None
    text = str(card.get('text') or '').strip()
    name, handle = split_author(card.get('user'))
    images = [str(src) for src in (card.get('images') or []) if src]
    if not any([text, images, card.get('video'), card.get('quote'), card.get('card'), card.get('poll')]):
        return None
    counters = parse_counters(card.get('labels') or {})
    topics = re.findall(r'(?:^|\s)[#＃]([^\s#]{1,64})', text)
    return {
        '发布者': name,
        '发布者ID': handle,
        '用户链接': f'https://x.com/{handle.lstrip("@")}' if handle else '',
        '发布时间': iso_stamp(card.get('iso')),
        '正文': text,
        '话题': ' | '.join(topics),
        '评论数': counters['评论数'],
        '转发数': counters['转发数'],
        '点赞数': counters['点赞数'],
        '收藏数': counters['收藏数'],
        '浏览数': counters['浏览数'],
        '图片链接': ' | '.join(images),
        '图片数': len(images),
        '视频数': 1 if card.get('video') else 0,
        '是否引用': '1' if card.get('quote') else '0',
        '含外链卡片': '1' if card.get('card') else '0',
        '含投票': '1' if card.get('poll') else '0',
        '链接': permalink(card.get('link'), str(card.get('tweetId') or '')),
        '推文ID': str(card['tweetId']),
    }


def tweet_id_of(url: str) -> str:
    """The status id out of any spelling of a tweet link."""
    match = re.search(r'/status/(\d+)', str(url or ''))
    if match:
        return match.group(1)
    return str(url or '').strip() if str(url or '').strip().isdigit() else ''


def handle_of(author: str) -> str:
    """Accept ``@handle``, a bare handle, or a pasted profile link."""
    text = str(author or '').strip()
    if not text:
        return ''
    if 'x.com/' in text.lower() or 'twitter.com/' in text.lower():
        tail = re.sub(r'[?#].*$', '', text.split('//', 1)[-1].split('/', 1)[-1])
        handle = tail.strip('/').split('/')[0]
        return handle.lstrip('@') if handle and handle not in ('home', 'intent') else ''
    return text.lstrip('@').split('/')[0]


class TwitterCrawler(Crawler):
    """X keyword search and one creator's posts, read from the rendered DOM."""

    domain = 'x.com'
    cookie_domains = ('twitter.com',)
    login_url = 'https://x.com/'
    supports_crawl = True
    #: Measured: a headless browser is served the sign-up sheet on ``/search``
    #: and a hard 403 on a profile, so this platform is visible-window only.
    never_headless = True

    CARD_SELECTOR = 'article[data-testid="tweet"]'
    MAX_ROUNDS = 40
    STUCK_ROUNDS = 3
    SETTLE_WAIT = 4.0
    #: How long the *first* screen of a page is given to paint. Measured on the
    #: live site: ``/search`` handed back 0 cards for 9.9 s and 11 at 11.9 s — the
    #: app fetches its own timeline, so an 8-second wait concluded the keyword had
    #: found nothing on a search that was about to succeed.
    MOUNT_WAIT = 22.0
    POLITE_BASE = 1.0
    POLITE_SPREAD = 0.4
    #: A card read is one script call over N cards, so this is the whole cost of
    #: a row; the row budget is scrolls, not requests.
    SCROLL_STEP = 0.9

    def search(self, keyword: str, target_count: int = 50, **kwargs) -> list[dict]:
        """Latest-first keyword search (``f=live``).

        ``f=top`` is deliberately not offered as the default: it is a small
        curated set that stops growing after a screen, while 实时 gives an
        unbounded stream to walk.
        """
        resume = self.resume_of(kwargs)
        encoded = quote(keyword)
        url = f'https://x.com/search?q={encoded}&f=live'
        logger.info(t('crawl.x.start', kw=keyword, n=target_count))
        return self._walk(url, target_count, keyword=keyword, resume=resume)

    def author(self, author: str, target_count: int = 50, **kwargs) -> list[dict]:
        """One account's own posts (the Posts tab, which is the default)."""
        resume = self.resume_of(kwargs)
        handle = handle_of(author)
        if not handle:
            raise ValueError(t('crawl.x.authorEmpty', author=author))
        url = f'https://x.com/{handle}'
        logger.info(t('crawl.x.authorStart', author=handle, n=target_count))
        return self._walk(url, target_count, author=handle, resume=resume)

    # ─── the walk ─────────────────────────────────────────────────────

    def _walk(self, url: str, target_count: int, resume: dict, **position) -> list[dict]:
        if self.collected() >= target_count:
            logger.info(t('crawl.x.target_reached', n=target_count))
            return self.results()
        # The seen-id set, not a card index, is the resume point of a virtualized
        # list: the rows already in hand say which cards to skip on the re-read
        # page, and re-reading is certain because the list scrolls back.
        stored = resume.get('ids')
        seen: set[str] = {str(v) for v in stored if str(v)} if isinstance(stored, list) else set()
        if not self.open(url):
            logger.warning(t('crawl.x.loadSlow', url=self._current_url()))
        if self.login_wall or self.risk_blocked:
            raise RuntimeError(t('crawl.x.wall', url=self._current_url()))
        if not self._wait_for(lambda: len(self._cards()), 1, timeout=self.MOUNT_WAIT):
            self.check_intercept(url, request_url=url)
            if self.login_wall or self.risk_blocked:
                raise RuntimeError(t('crawl.x.wall', url=self._current_url()))
            logger.info(t('crawl.x.no_cards', url=self._current_url()))
            return self.results()

        def mark(progress):
            # The crawler's own position rides along: a cursor that only says
            # "scanned 40" cannot tell a resume *which* search it was. The card
            # index is kept too because it is what a *non*-virtualized list would
            # resume by; here the id set does the work and the index just lets the
            # cursor explain itself in runs.db.
            self.mark_position(**position, **progress, ids=sorted(seen), done=self.collected())

        result = feed.walk_feed(
            self._cards,
            lambda card, index: self._row(card, seen),
            self.emit,
            scroll=self._scroll,
            target=target_count,
            collected=self.collected,
            # The rendered window turns over while its node count does not, so the
            # walk waits for the ids on screen to change. Counting cards here would
            # stop after one screen on a timeline that was still delivering.
            window=self.window_key,
            mark=mark,
            stopped=lambda: self.login_wall or self.risk_blocked,
            max_rounds=self.MAX_ROUNDS,
            stuck_rounds=self.STUCK_ROUNDS,
            settle_wait=self.SETTLE_WAIT,
        )
        if result.stopped_reason == 'no_cards' and not self.collected():
            logger.info(t('crawl.x.no_cards', url=self._current_url()))
        if self.login_wall:
            logger.warning(t('crawl.loginWall', platform=self.domain, where=self._current_url()))
        logger.info(t('crawl.x.finished', n=self.collected(), reason=result.stopped_reason))
        return self.results()

    def _row(self, card, seen: set) -> dict | None:
        """Read one rendered card once, and drop anything already collected.

        The node the walk listed a moment ago can be gone by the time it is read —
        a recycled window detaches its cards while a script is in flight. That is
        the normal hazard of this list, not a failed crawl: the tweet keeps no slot
        in ``seen``, so a later round reads the same post off a fresh handle.
        """
        try:
            data = self.driver.execute_script(EXTRACT_CARD_JS, card)
        except (StaleElementReferenceException, JavascriptException) as e:
            logger.debug('card vanished before it could be read: %s', e)
            return None
        row = row_from_card(data)
        if row is None:
            return None
        tweet_id = row['推文ID']
        if tweet_id in seen:
            return None
        seen.add(tweet_id)
        return row

    def _cards(self) -> list:
        return self.driver.find_elements(By.CSS_SELECTOR, self.CARD_SELECTOR)

    def window_key(self) -> str:
        """The identity of the rendered window: which status links are on screen.

        One cheap script, and it is the only signal a virtualized feed gives — the
        node count is constant while the tweets in it are not. Selenium wrapper
        objects are rebuilt on every query, so ``id(element)`` would always "look
        changed" and the walk would never notice an exhausted list; the links are
        what actually identifies the content on screen.
        """
        try:
            return str(self.driver.execute_script(WINDOW_LINKS_JS) or '')
        except Exception:
            return ''

    def _scroll(self):
        self.driver.execute_script('window.scrollBy(0, document.body.scrollHeight * arguments[0]);', self.SCROLL_STEP)
        self._polite_pause(self.POLITE_BASE, self.POLITE_SPREAD)

    def _wait_for(self, measure, target, timeout):
        return feed.wait_for(measure, target, timeout=timeout)

    # ─── one tweet ────────────────────────────────────────────────────

    def get_detail(self, url: str) -> dict | None:
        """Open one tweet and read it as a row (the standalone detail path)."""
        tweet = tweet_id_of(url)
        if not tweet:
            return None
        self.open(f'https://x.com/i/status/{tweet}')
        if not self._wait_for(lambda: len(self._cards()), 1, timeout=self.MOUNT_WAIT):
            return None
        # The same guarded read the timeline uses: a permalink page repaints the
        # head of its thread while the reply list above it mounts.
        cards = self._cards()
        return self._row(cards[0], set()) if cards else None

    def comment_count(self, url: str) -> int:
        """The reply count the tweet's own card reports, or 0.

        Read from the card rather than guessed from the thread page: a tweet whose
        replies are hidden answers ``0`` here and that is a fact about the tweet,
        not a failed crawl.
        """
        row = self.get_detail(url)
        return int((row or {}).get('评论数') or 0)
