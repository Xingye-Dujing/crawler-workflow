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

from i18n import t

OK = 'ok'
BLOCKED = 'blocked'
DEAD = 'dead'

_BLOCK_MARKS = ('暂时限制', '40362', '扫码登录', '登录后查看', '当前请求存在异常')

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


def page_is_blocked(body_head: str) -> bool:
    return any(mark in (body_head or '') for mark in _BLOCK_MARKS)


# ---------------------------------------------------------------------------
# wechat: the comment call and its refusal
# ---------------------------------------------------------------------------

#: The article page hands its own comment-call parameters to the browser as a
#: mix of JS globals and a config object. Shared with
#: ``WechatCrawler.article_credentials`` so the cookie diagnosis and the actual
#: crawl can never disagree about what "reachable" means.
WECHAT_CREDENTIAL_FIELDS = (
    'key',
    'show_comment',
    'comment_id',
    'appmsg_token',
    'biz',
    'mid',
    'idx',
    'sn',
    'pass_ticket',
    'uin',
)

WECHAT_CREDENTIAL_SCRIPT = """
    var out = {};
    var cfg = null;
    try { cfg = window.wx_getext_config || null; } catch (e) { cfg = null; }
    var commentId = (cfg && (cfg.comment_id || cfg.appmsgcommentid)) || '';
    out.key = (cfg && cfg.k) ? String(cfg.k) : '';
    out.comment_id = commentId ? String(commentId) : '';
    out.appmsg_token = (cfg && cfg.appmsg_token) ? String(cfg.appmsg_token)
        : ((typeof appmsg_token !== 'undefined' && appmsg_token) ? String(appmsg_token) : '');
    out.biz = (typeof biz !== 'undefined' && biz) ? String(biz) : '';
    out.mid = (typeof mid !== 'undefined' && mid) ? String(mid) : '';
    out.idx = (typeof idx !== 'undefined' && idx) ? String(idx) : '';
    out.sn = (typeof sn !== 'undefined' && sn) ? String(sn) : '';
    out.pass_ticket = (typeof pass_ticket !== 'undefined' && pass_ticket) ? String(pass_ticket) : '';
    out.uin = (typeof uin !== 'undefined' && uin) ? String(uin) : '';
    /* show_comment is the server's own switch: it reads '0' for a session the
       site will not show 留言 to — a different fact from "this article has no
       comments", and it must not be reported as one. */
    var html = document.documentElement.innerHTML || '';
    var sw = html.match(/show_comment:\\s*['\\"]?(\\d)/);
    out.show_comment = sw ? sw[1] : '';
    /* A browser session has no wx_getext_config at all, yet the article still
       publishes its own comment id in the inline config the page's script
       reads — that is what makes the request possible to attempt, and therefore
       the refusal possible to report. Without this fallback a 留言-enabled
       article would be misread as "no comment module". */
    if (!out.comment_id) {
        var hit = html.match(/comment_id:\\s*['\\"](\\d{6,})['\\"]/);
        if (hit) { out.comment_id = hit[1]; }
        if (!out.biz) {
            var b = html.match(/__biz=([A-Za-z0-9%=]+)/);
            if (b) { out.biz = decodeURIComponent(b[1]); }
        }
    }
    return out;
    """

#: The numbers that only a recognised visit gets: 阅读/赞/在看/转发. WeChat fills
#: them from the same privileged call that carries the comment data, so their
#: absence is the evidence that this visit never got in — which is NOT the same
#: claim as "the article has no comments".
WECHAT_ENTRY_SCRIPT = r"""
    var labels = ['阅读', '赞', '在看', '转发'];
    var found = {};
    var nodes = document.querySelectorAll('span, em, div, a');
    for (var i = 0; i < nodes.length && i < 4000; i++) {
        var el = nodes[i];
        var txt = (el.textContent || '').trim();
        if (!txt || txt.length > 24) { continue; }
        for (var k = 0; k < labels.length; k++) {
            var label = labels[k];
            if (txt.indexOf(label) !== 0) { continue; }
            var num = txt.replace(label, '').trim();
            if (/^[\d.,]+[万千]?\+?$/.test(num)) { found[label] = num; }
        }
    }
    return found;
    """

#: Pages WeChat serves instead of an article. These are the only links that count
#: as dead: an article that exists but has no 留言 is not a dead link.
_DEAD_ARTICLE_MARKS = ('参数错误', '该内容已被发布者删除', '此内容因违规无法查看', '链接不存在', '该内容已被删除')


def wechat_comment_js(creds: dict, offset: int = 0, count: int = 20) -> str:
    """The comment-page request the article's own script would issue.

    ``key``/``pass_ticket`` are usually empty for a browser session; the call is
    made anyway because the answer is the diagnosis, and a session that does
    carry them (a link opened from the client) then really can page through.
    """
    from urllib.parse import quote

    parts = [
        'action=getcomment',
        'scene=0',
        f'__biz={quote(creds.get("biz") or "", safe="")}',
        f'comment_id={quote(creds.get("comment_id") or "", safe="")}',
        f'idx={quote(creds.get("idx") or "", safe="")}',
        f'mid={quote(creds.get("mid") or "", safe="")}',
        f'sn={quote(creds.get("sn") or "", safe="")}',
        f'key={quote(creds.get("key") or "", safe="")}',
        f'pass_ticket={quote(creds.get("pass_ticket") or "", safe="")}',
        f'offset={int(offset)}',
        f'limit={int(count)}',
        'fjson=1',
        'devicetype=Windows+10+x64',
        'version=3.9.11.23',
        'lang=zh_CN',
        'net_type=1',
    ]
    return 'https://mp.weixin.qq.com/mp/appmsg_comment?' + '&'.join(parts)


def _json_or_none(text: str):
    """Parse a JSON answer, or None when the endpoint served HTML instead."""
    body = str(text or '').strip()
    if not body or body[0] != '{':
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _as_int(value) -> int:
    try:
        return int(float(str(value or 0)))
    except (TypeError, ValueError):
        return 0


def _wechat_time(value) -> str:
    """Comment timestamps arrive as unix seconds; blank when they do not."""
    stamp = _as_int(value)
    if not stamp:
        return ''
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(stamp))


def parse_wechat_comments(payload: dict, article_url: str) -> list:
    """``appmsg_comment`` JSON → rows: 精选留言 first, then each 作者回复.

    Replies ride inside their parent comment, so they become rows of their own
    with ``回复对象`` filled — a flattened table is what every downstream node and
    export format here already understands; a nested one would be silently
    dropped by the CSV writer.
    """
    rows = []
    for item in payload.get('elected_comment') or []:
        if not isinstance(item, dict):
            continue
        base = {
            '平台': 'wechat',
            '文章URL': article_url,
            '评论者': str(item.get('author') or ''),
            '评论者主页': '',
            '评论内容': _strip_tags(str(item.get('content') or '')),
            '评论时间': _wechat_time(item.get('create_time') or item.get('publish_time')),
            '点赞数': _as_int(item.get('like_num') or item.get('like_count')),
            'IP归属地': str(item.get('location') or '').replace('IP: ', '').strip(),
            '回复对象': '',
            '楼层': len(rows) + 1,
        }
        rows.append(dict(base))
        reply = item.get('reply') if isinstance(item.get('reply'), dict) else {}
        for sub in reply.get('reply') or []:
            if not isinstance(sub, dict):
                continue
            child = dict(base)
            child['评论者'] = str(sub.get('author') or '')
            child['评论内容'] = _strip_tags(str(sub.get('content') or ''))
            child['评论时间'] = _wechat_time(sub.get('create_time'))
            child['点赞数'] = _as_int(sub.get('like_num'))
            child['IP归属地'] = str(sub.get('location') or '').replace('IP: ', '').strip()
            # The client labels the account holder's own answers; keep that.
            child['回复对象'] = '作者回复' if sub.get('is_star') else base['评论者']
            child['楼层'] = len(rows) + 1
            rows.append(child)
    return rows


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

    # -- wechat ---------------------------------------------------------------

    def crawl_wechat(self, url: str, limit: int) -> tuple:
        """Read one article's 精选留言, and read an empty list as what it is.

        The rule this crawler is written to (confirmed by the site's owner, and
        matching every measurement made against real articles): when the article
        body renders normally, the comment area that comes with it is visible too,
        so **an empty comment area means the article has no comments**. An empty
        list is therefore reported as ``ok`` with zero rows — the same way the
        other three platforms report 无评论 — and never as a permission problem.

        ``blocked`` is reserved for what actually is one: a risk-control or login
        page instead of the article. ``dead`` is a link that is not an article at
        all (deleted, revoked, wrong URL). The endpoint's 验证 answer to a browser
        session is treated as "nothing to read here": it carries no comment data,
        which under the rule above is the article's answer, not the site's.
        """
        self.driver.get(url)
        self.nap(3)
        body = self._body_head(1200)
        if any(mark in body for mark in _BLOCK_MARKS):
            return [], BLOCKED
        if any(mark in body for mark in _DEAD_ARTICLE_MARKS):
            self.log(t('comment.wechatDeadLink', url=url))
            return [], DEAD
        rows = self._wechat_rendered_rows(url)
        if not rows:
            # The rendered area is empty; the endpoint may still hold elected
            # comments for a session the site recognises.
            payload = self._wechat_comment_page(self._wechat_credentials())
            if payload is not None:
                rows = parse_wechat_comments(payload, url)
        if rows:
            return rows[:limit] if limit else rows, OK
        # No comments and no rendered list. That is only "该文无留言" if this visit
        # demonstrably got in — which the counts prove, because WeChat fills them
        # from the same privileged path as the comment data. Without them the
        # two cases are indistinguishable, so say so instead of guessing.
        counts = self._wechat_entry_counts()
        if not counts:
            self.log(t('comment.wechatNotEntered', url=url))
            return [], BLOCKED
        self.log(t('comment.wechatEmpty', url=url, counts=json.dumps(counts, ensure_ascii=False)))
        return [], OK

    def _wechat_entry_counts(self) -> dict:
        """The 阅读/赞/在看/转发 numbers this session was allowed to see."""
        try:
            found = self.driver.execute_script(WECHAT_ENTRY_SCRIPT) or {}
        except Exception:
            return {}
        return {str(k): str(v) for k, v in found.items()} if isinstance(found, dict) else {}

    def _wechat_rendered_rows(self, url: str) -> list:
        """Comments the page already rendered into the DOM, if any."""
        rows = []
        for item in self.driver.find_elements('css selector', '.discuss_list .item'):
            text = ' '.join((item.text or '').split())
            if text:
                rows.append(
                    {
                        '平台': 'wechat',
                        '文章URL': url,
                        '评论者': '',
                        '评论者主页': '',
                        '评论内容': text,
                        '评论时间': '',
                        '点赞数': 0,
                        'IP归属地': '',
                        '回复对象': '',
                        '楼层': len(rows) + 1,
                    }
                )
        return rows

    def _wechat_comment_page(self, creds: dict):
        """One page of the comment API, or None when it did not answer with JSON."""
        if not creds.get('comment_id'):
            return None
        try:
            payload = _json_or_none(self._in_page_fetch(wechat_comment_js(creds, 0)))
        except Exception:
            return None
        if payload is None:
            # Not JSON: either a session the site does not recognise, or a
            # transient page. Both mean "no elected comments to read", per the
            # rule in crawl_wechat — so it is logged, not escalated.
            self.log(t('comment.wechatNoApiAnswer'))
        return payload

    def _wechat_credentials(self) -> dict:
        """The tokens the comment call needs, read from the article page."""
        try:
            raw = self.driver.execute_script(WECHAT_CREDENTIAL_SCRIPT) or {}
        except Exception:
            raw = {}
        return {key: str(raw.get(key) or '') for key in WECHAT_CREDENTIAL_FIELDS}

    # -- shared ---------------------------------------------------------------

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
