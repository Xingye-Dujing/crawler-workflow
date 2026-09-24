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

from .engine import feed, pager
from .engine.counters import parse_count, to_int
from .engine.jsonpath import collect, get_in, runs_text
from .engine.wall import looks_blocked

OK = 'ok'
BLOCKED = 'blocked'
DEAD = 'dead'


def _json_or_none(raw):
    """Parse an endpoint answer, treating anything unparseable as no answer.

    An HTML risk-control page served where JSON was expected is a refusal, not
    malformed data — the caller decides between ``blocked`` and ``dead``.
    """
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


# platform_for (the article-link → adapter router) lives in utils.helpers:
# the engine validator needs the same table without importing any crawler.


# ---------------------------------------------------------------------------
# pure parsers (unit-testable without any browser)
# ---------------------------------------------------------------------------


def _strip_tags(html: str) -> str:
    text = re.sub(r'<[^>]+>', '', html or '')
    return re.sub(r'\s+', ' ', text).strip()


def parse_weibo_comments(payload: dict, article_url: str) -> list:
    """buildComments JSON → rows. Missing fields degrade to empty, never raise."""
    rows = []
    for i, item in enumerate(payload.get('data') or [], 1):
        if not isinstance(item, dict):
            continue
        user = item.get('user') if isinstance(item.get('user'), dict) else {}
        rows.append(
            {
                '平台': 'weibo',
                '文章URL': article_url,
                '评论者': str(user.get('screen_name') or ''),
                '评论者主页': str(user.get('profile_image_url') or ''),
                '评论内容': _strip_tags(str(item.get('text') or '')),
                '评论时间': str(item.get('created_at') or ''),
                '点赞数': int(item.get('like_count') or 0),
                '楼层': i,
            }
        )
    return rows


def parse_xhs_comments(items) -> list:
    """Takes [(author, text, date, likes)] tuples scraped by the DOM walker."""
    return [
        {
            '平台': 'xiaohongshu',
            '文章URL': url,
            '评论者': author,
            '评论者主页': '',
            '评论内容': text,
            '评论时间': date,
            '点赞数': likes,
            '楼层': idx,
        }
        for idx, (url, author, text, date, likes) in enumerate(items, 1)
    ]


def parse_zhihu_comments(items) -> list:
    """Takes [(url, author, author_href, text)] tuples scraped per panel."""
    return [
        {
            '平台': 'zhihu',
            '文章URL': url,
            '评论者': author,
            '评论者主页': author_href,
            '评论内容': text,
            '评论时间': '',
            '点赞数': 0,
            '楼层': idx,
        }
        for idx, (url, author, author_href, text) in enumerate(items, 1)
    ]


# ``1周前·江苏`` / ``刚刚`` / ``2026-08-04`` — douyin puts the relative time and
# the IP 地区 in one line, and it is the only line of the block that is neither a
# name, the text itself, nor a number.
_DOUYIN_WHEN_RE = re.compile(r'^(?:刚刚|\d+\s*(?:分钟|小时|天|周|月|年)前|\d{4}-\d{1,2}-\d{1,2})(?:·.+)?$')
_DOUYIN_SUBS_RE = re.compile(r'展开\s*(\d+)\s*条回复')


def douyin_comment_fields(text: str) -> tuple:
    """One rendered comment block → (author, content, when, region, likes, subs).

    The panel's line order is fixed but not dense: an author whose name is empty
    collapses a line, so the fields are recognised by *shape* (a date-shaped line,
    a bare number, a 展开N条回复 label) rather than by index. That is also what
    keeps a truncated preview (``展开更多`` inserts a literal ``...`` line) from
    becoming comment text.
    """
    lines = [line.strip() for line in str(text or '').split('\n') if line.strip() and line.strip() != '...']
    author = lines[0] if lines else ''
    content = lines[1] if len(lines) > 1 else ''
    when, region, likes, subs = '', '', 0, 0
    for line in lines[2:]:
        match = _DOUYIN_SUBS_RE.search(line)
        if match and not subs:
            subs = int(match.group(1))
            continue
        if not when and _DOUYIN_WHEN_RE.match(line):
            when, _, region = line.partition('·')
            when = when.strip()
            region = region.strip()
            continue
        if line.isdigit() and not likes:
            likes = int(line)
    return author, content, when, region, likes, subs


def parse_douyin_comments(items) -> list:
    """Takes [(url, author, content, when, region, likes, subs)] scraped per panel."""
    return [
        {
            '平台': 'douyin',
            '文章URL': url,
            '评论者': author,
            '评论者主页': '',
            '评论内容': content,
            '评论时间': when,
            '评论地区': region,
            '点赞数': likes,
            '子回复数': subs,
            '楼层': idx,
        }
        for idx, (url, author, content, when, region, likes, subs) in enumerate(items, 1)
    ]


def parse_bilibili_comments(items, article_url: str, floor: int = 0) -> list:
    """``x/v2/reply/main`` rows → comment rows, sub-replies flattened in place.

    ``floor`` continues the numbering across pages, so 楼层 stays a position in
    the article's comment set rather than in one page's payload.

    A carried ``replies`` list is NOT the whole thread: measured on a hot page,
    a comment with ``rcount=11`` carries 2 sub-replies. They are stored with
    their parent's id so a reader can tell a reply-from-a-reply from a top-level
    comment, and ``子回复数`` keeps the unexpanded remainder visible instead of
    letting the count read as "this thread has 2 replies".
    """
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        floor += 1
        rows.append(_bili_comment_row(item, article_url, floor, parent=''))
        for sub in item.get('replies') or []:
            if isinstance(sub, dict):
                floor += 1
                rows.append(_bili_comment_row(sub, article_url, floor, parent=str(item.get('rpid') or '')))
    return rows


def _bili_comment_row(item: dict, article_url: str, floor: int, parent: str) -> dict:
    member = item.get('member') if isinstance(item.get('member'), dict) else {}
    content = item.get('content') if isinstance(item.get('content'), dict) else {}
    mid = str(member.get('mid') or '')
    level = (
        (member.get('level_info') or {}).get('current_level') if isinstance(member.get('level_info'), dict) else None
    )
    return {
        '平台': 'bilibili',
        '文章URL': article_url,
        '评论者': str(member.get('uname') or ''),
        '评论者主页': f'https://space.bilibili.com/{mid}' if mid else '',
        '用户等级': int(level or 0),
        '评论内容': str(content.get('message') or ''),
        '评论时间': _stamp(item.get('ctime')),
        '点赞数': int(item.get('like') or 0),
        '楼层': floor,
        '评论ID': str(item.get('rpid') or ''),
        '父评论ID': parent or str(item.get('root') or ''),
        '子回复数': int(item.get('rcount') or 0),
        '回复数': int(item.get('count') or 0),
        'UP主态': '点赞' if _bili_up_liked(item) else '',
    }


def _bili_up_liked(item: dict) -> bool:
    """Whether the video's UP主 liked this comment (the card_label badge).

    It is the one signal in the payload that says "the author read this", and
    an analyst sorting a comment table by it is sorting by author engagement —
    which is why it is kept and why a missing label must read as plain ''.
    """
    for label in item.get('card_label') or []:
        if isinstance(label, dict) and 'UP主' in str(label.get('text_content') or ''):
            return True
    return bool((item.get('up_action') or {}).get('like')) if isinstance(item.get('up_action'), dict) else False


def _stamp(value) -> str:
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(seconds)) if seconds else ''


def weibo_bid(url: str) -> str:
    """Extract the weibo id — /detail/<mid> or weibo.com/<uid>/<bid>."""
    m = re.search(r'/detail/(\d+)', url or '')
    if m:
        return m.group(1)
    m = re.search(r'weibo\.com(?:/.*)?/([A-Za-z0-9]{6,})', url or '')
    return m.group(1) if m else ''


def weibo_show_js(bid: str) -> str:
    return f'https://weibo.com/ajax/statuses/show?id={bid}'


def weibo_comments_js(mid: str, max_id: int = 0, count: int = 20) -> str:
    return (
        'https://weibo.com/ajax/statuses/buildComments?is_reload=1&id='
        f'{mid}&is_show_bulletin=2&is_mix=0&count={count}&flow=0&fetch_level=0&max_id={max_id}'
    )


def bilibili_view_js(bvid: str) -> str:
    return f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}'


def bilibili_reply_js(aid, next_cursor: int = 0, size: int = 20) -> str:
    """One page of the hot-sorted comment list.

    ``mode=3`` is what the video page itself requests and the only mode measured
    to page coherently: ``mode=2`` (by time) jumped its own cursor to 1435 and
    then reported ``is_end`` after a single row.
    """
    return f'https://api.bilibili.com/x/v2/reply/main?type=1&oid={aid}&mode=3&next={next_cursor}&ps={size}'


# ---------------------------------------------------------------------------
# browser adapters (thin; each returns (rows, status))
# ---------------------------------------------------------------------------


def parse_youtube_comments(payload: dict, article_url: str) -> list:
    """One innertube answer's ``commentEntityPayload`` objects → rows.

    The field names come from the live answer, not from a guess (measured: the
    text is ``properties.content.content``, the like count is
    ``toolbar.likeCountNotliked`` with an accessibility sentence behind it, the
    author is ``author.displayName`` and the stable id is ``properties.commentId``).
    Two of those matter more than they look:

    * 评论时间 is relative prose on YouTube ("1 year ago") with no absolute
      sibling in the payload, so it cannot identify a row on its own — the
      ``评论ID`` is what makes a resumed walk refuse duplicates instead of
      storing the same comment twice;
    * a reply to a reply carries ``properties.replyLevel`` > 0, and the floor is
      kept so an analysis of "what did people say" can tell a thread from a
      top-level comment.
    """
    rows = []
    for item in collect(payload, 'commentEntityPayload'):
        if not isinstance(item, dict):
            continue
        props = item.get('properties') or {}
        toolbar = item.get('toolbar') or {}
        author = item.get('author') or {}
        comment_id = str(props.get('commentId') or '')
        handle = str(author.get('displayName') or '')
        canonical = str(get_in(author, 'channelCommand.innertubeCommand.browseEndpoint.canonicalBaseUrl') or '')
        rows.append(
            {
                '平台': 'youtube',
                '文章URL': article_url,
                '评论者': handle,
                '评论者主页': f'https://www.youtube.com{canonical}' if canonical else '',
                '评论者ID': str(author.get('channelId') or ''),
                '评论内容': runs_text(props.get('content')),
                '评论时间': str(props.get('publishedTime') or ''),
                # The count the viewer has not used reads the same as the one
                # they have, so either spelling is the number — and the a11y
                # sentence ("… along with 56 other people") is the fallback.
                '点赞数': to_int(toolbar.get('likeCountNotliked') or toolbar.get('likeCountLiked'))
                or parse_count(toolbar.get('likeButtonA11y')),
                '回复数': to_int(toolbar.get('replyCount')),
                '楼层': to_int(props.get('replyLevel')) + 1,
                '评论ID': comment_id,
                '是否作者回复': '1' if author.get('isCreator') else '0',
                '视频ID': _query_value(article_url, 'v'),
            }
        )
    return rows


def _query_value(url: str, name: str) -> str:
    """One query parameter of an article link, without importing urllib per row."""
    match = re.search(rf'[?&]{name}=([^&#]+)', str(url or ''))
    if match:
        return match.group(1)
    # Shorts and lives spell the id in the path, and a link pasted from the share
    # sheet may be nothing but the id.
    match = re.search(r'/(?:shorts|live|embed)/([\w-]{6,20})', str(url or ''))
    if match:
        return match.group(1)
    text = str(url or '').strip()
    return text if re.fullmatch(r'[\w-]{11}', text) else ''


def parse_twitter_replies(cards: list, article_url: str, root_id: str = '') -> list:
    """X reply cards → comment rows.

    The same extractor as the timeline is reused (one ``execute_script`` per card),
    and the tweet the page is *about* is dropped: it appears first on its own
    permalink, and storing it would hand the user a row saying "this post replied
    to itself" while inflating its own counts.
    """
    from .twitter import row_from_card

    rows = []
    for index, card in enumerate(cards):
        row = row_from_card(card if isinstance(card, dict) else {})
        if row is None or (root_id and row['推文ID'] == str(root_id)):
            continue
        rows.append(
            {
                '平台': 'twitter',
                '文章URL': article_url,
                '评论者': row['发布者ID'] or row['发布者'],
                '评论者昵称': row['发布者'],
                '评论者主页': row['用户链接'],
                '评论内容': row['正文'],
                '评论时间': row['发布时间'],
                '点赞数': row['点赞数'],
                '回复数': row['评论数'],
                '转发数': row['转发数'],
                '浏览数': row['浏览数'],
                '图片链接': row['图片链接'],
                '图片数': row['图片数'],
                '是否引用': row['是否引用'],
                '楼层': index + 1,
                '评论ID': row['推文ID'],
                '推文ID': row['推文ID'],
            }
        )
    return rows


class CommentSession:
    """One browser session per platform; the node handler owns lifecycle."""

    def __init__(self, driver, log=None, nap=None):
        self.driver = driver
        self.log = log or (lambda msg: None)
        self.nap = nap or time.sleep

    # -- low-level helpers -------------------------------------------------

    def _in_page_fetch(self, url: str, timeout_ms: int = 25000) -> str:
        script = (
            'var cb=arguments[arguments.length-1];'
            f"fetch({json.dumps(url)},{{credentials:'include'}})"
            ".then(r=>r.text()).then(t=>cb(t)).catch(e=>cb('ERR '+e));"
        )
        self.driver.set_script_timeout(timeout_ms / 1000)
        return self.driver.execute_async_script(script)

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
            if not re.search(r'\d+\s*条评论', text):
                continue
            with contextlib.suppress(Exception):
                self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', btn)
                self.nap(0.4)
                btn.click()
                opened += 1
                self.nap(2)
                rows.extend(self._drain_comment_panel(url, limit))
            if limit and len(rows) >= limit:
                break
        if not opened and rows == []:
            # No comment button at all: either 评论已关闭 or the page never
            # rendered the answers — treat as ok-with-nothing, but say so.
            self.log(t('comment.zhihuNoPanels', url=url))
        return (rows[:limit] if limit else rows), OK

    def _drain_comment_panel(self, url: str, limit: int) -> list:
        collected, seen = [], set()
        for _page in range(6):
            batch = []
            for content in self.driver.find_elements('css selector', '.CommentContent'):
                text = self._safe_text(content)
                author, href = self._comment_author(content)
                key = (author, text)
                if not text or key in seen:
                    continue
                seen.add(key)
                batch.append((url, author, href, text))
            new = parse_zhihu_comments(batch)
            collected.extend(new)
            more = [b for b in self.driver.find_elements('css selector', 'button, a') if '更多' in self._safe_text(b)]
            if not new or not more or (limit and len(collected) >= limit):
                break
            with contextlib.suppress(Exception):
                self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', more[-1])
                more[-1].click()
                self.nap(1.5)
        return collected

    def _comment_author(self, content_element) -> tuple:
        """Author sits in the panel item's header, a sibling of the content."""
        with contextlib.suppress(Exception):
            parent = content_element.find_element('xpath', './ancestor::div[3]')
            for a in parent.find_elements('css selector', 'a[href*="/people/"]'):
                name = self._safe_text(a)
                if name:
                    return name, a.get_attribute('href') or ''
        return '', ''

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
        from .video import CODE_GONE, bilibili_bvid

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
            order = [candidate for candidate in [token, *candidates] if candidate][:3]
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
        from .video import douyin_id

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
