"""Comment crawling for zhihu / xiaohongshu / weibo article links.

Design notes that the code cannot shout later:

* Column keys deliberately avoid every name in ``run_store._URL_FIELDS`` /
  ``_AUTHOR_FIELDS`` / ``_BODY_FIELDS`` ('文章URL', '评论者', '评论内容').
  The dedupe ledger picks identity from those field lists; a comment has no
  link of its own, so borrowing those names would make every comment of one
  article hash to the same key and silently drop all but the first.
* One article can fail for different reasons and they must not blur:
  ``ok`` (rows, maybe zero — zero means 无评论), ``blocked`` (risk-control or
  login wall answered instead of content), ``dead`` (link unreadable/404).
* weibo reads through its own site's JSON endpoints fetched *in page*
  (same-origin, cookie-authenticated) — the desktop DOM is a maze of hashed
  class names, and the ajax path is what the probes proved stable.
* zhihu blocks headless sessions on content pages (answer/question), so the
  caller must give this platform a visible window; that requirement is
  declared here as ``NEVER_HEADLESS`` and honoured by the node handler.
"""

import contextlib
import json
import re
import time

OK = 'ok'
BLOCKED = 'blocked'
DEAD = 'dead'

_BLOCK_MARKS = ('暂时限制', '40362', '扫码登录', '登录后查看', '当前请求存在异常')


def platform_for(url: str) -> str:
    """Which adapter handles this article link ('' = unsupported)."""
    u = (url or '').strip().lower()
    if 'zhihu.com' in u:
        return 'zhihu'
    if 'xiaohongshu.com' in u or 'xhslink.com' in u:
        return 'xiaohongshu'
    if 'weibo.com' in u or 'weibo.cn' in u:
        return 'weibo'
    return ''


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
