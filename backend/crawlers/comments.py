"""Comment crawling for zhihu / xiaohongshu / weibo / bilibili article links.

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
"""

import contextlib
import json
import re
import time

from i18n import t

OK = 'ok'
BLOCKED = 'blocked'
DEAD = 'dead'

_BLOCK_MARKS = ('暂时限制', '40362', '扫码登录', '登录后查看', '当前请求存在异常')


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


def page_is_blocked(body_head: str) -> bool:
    return any(mark in (body_head or '') for mark in _BLOCK_MARKS)


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
            self.log(f'weibo show failed for {url}')
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
        if page_is_blocked(self._body_head()):
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
        if page_is_blocked(head):
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
            self.log(f'zhihu no comment panels on {url}')
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
        if page_is_blocked(self._body_head()):
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
            self.log(t('comment.biliClosed', url=url))
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
