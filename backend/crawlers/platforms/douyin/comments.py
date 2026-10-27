"""douyin comments: the rendered-block field splitter, the tuple adapter and the panel walk.

The panel's line order is fixed but not dense, so the fields are recognised by
*shape* rather than by index — that is also what keeps a truncated preview from
becoming comment text.
"""

import contextlib
import re
import time

from selenium.common.exceptions import JavascriptException
from selenium.webdriver.common.action_chains import ActionChains

from crawlers.commenting.protocol import BLOCKED, DEAD, OK
from crawlers.commenting.walks import register
from crawlers.engine import feed, times
from crawlers.engine.counters import parse_count
from crawlers.engine.pacing import throttled_sleep
from crawlers.engine.wall import looks_blocked
from i18n import stop_reason_label, t

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

    The time line is the anchor, not just another field. The text used to be
    ``lines[1]`` unconditionally, which filed ``1天前·北京`` as the comment when the
    author line had absorbed it — a row whose 评论内容 is a timestamp is a lie in the
    column the user reads — and it dropped every line after the first on a comment
    that wraps, so a two-line comment lost its second line (「不漏采」 is the whole
    point of this table). Lines between the author and the anchor are therefore the
    text, joined; a number standing there is part of what someone wrote, not the
    like count, which only ever sits below the anchor.
    """
    lines = [line.strip() for line in str(text or '').split('\n') if line.strip() and line.strip() != '...']
    author = lines[0] if lines else ''
    when, region, likes, subs = '', '', 0, 0
    anchor = next((i for i, one in enumerate(lines[1:], 1) if _DOUYIN_WHEN_RE.match(one)), None)
    head = lines[1:anchor] if anchor is not None else lines[1:2]
    content = '\n'.join(head)
    tail_start = (anchor + 1) if anchor is not None else 2
    for line in lines[tail_start:]:
        match = _DOUYIN_SUBS_RE.search(line)
        if match and not subs:
            subs = int(match.group(1))
            continue
        if line.isdigit() and not likes:
            likes = int(line)
    if anchor is not None:
        when, _, region = lines[anchor].partition('·')
        when, region = when.strip(), region.strip()
    return author, content, when, region, likes, subs


def parse_douyin_threads(threads: dict, url: str) -> tuple:
    """Ordered parent→reply rows and the UNCOLLECTED reply count, numbered across the whole panel.

    ``threads`` is ``{parent_key: {author, content, when, region, likes, subs, replies: {key: {...}}}}``
    in first-seen order (``dict`` preserves it). 楼层 is a single continuous floor over parents and
    their replies (so a reply's 父楼层 can point back at its parent's number), exactly like zhihu's.

    A parent's **子回复数** is the number of reply rows we actually landed (the user's "实际子行数"),
    falling back to the site's declared 「展开N条回复」 when the thread could not be opened. ``nested`` is
    the sum of ``declared − captured`` over every parent — the replies the denominator counts but this
    walk never reached — so the ``comment.dyShort`` gap stays honest whether or not the threads opened,
    and reply rows (now real rows) are never double-counted against it.
    """
    rows = []
    nested = 0
    floor = 0
    for slot in threads.values():
        floor += 1
        parent_floor = floor
        captured = len(slot['replies'])
        nested += max(slot['subs'] - captured, 0)
        rows.append(
            {
                '平台': 'douyin',
                '文章URL': url,
                '评论者': slot['author'],
                '评论者主页': '',
                '评论内容': slot['content'],
                # The panel prints a relative wording for anything recent ("1天前"), which
                # is the cell ``comments.py``'s own time matcher exists to find. Resolved at
                # the row boundary so every platform's 评论时间 is one format; the region
                # that shares the same line is split off before this and is unaffected.
                '评论时间': times.absolute(slot['when']),
                '评论地区': slot['region'],
                '点赞数': slot['likes'],
                '子回复数': captured if captured else slot['subs'],
                '楼层': parent_floor,
                '父楼层': '',
            }
        )
        for reply in slot['replies'].values():
            floor += 1
            rows.append(
                {
                    '平台': 'douyin',
                    '文章URL': url,
                    '评论者': reply['author'],
                    '评论者主页': '',
                    '评论内容': reply['content'],
                    '评论时间': times.absolute(reply['when']),
                    '评论地区': reply['region'],
                    '点赞数': reply['likes'],
                    '子回复数': 0,
                    '楼层': floor,
                    '父楼层': parent_floor,
                }
            )
    return rows, nested


#: douyin's reply expander is a real ``button`` whose ONLY reliable opener is a native click — a
#: synthetic ``.click()`` does not move React's delegated handler (measured on the real profile).
#: The opener is matched by its 「展开N条回复」 TEXT, not the class alone: after a real expand the same
#: slot reads 「收起」, so the text is both the proof it opened and the guard against a re-click that
#: would collapse it again. Each thread is stamped ``data-dy-tried`` so it is attempted ONCE — a comment
#: that is deleted/hidden only pops 「评论已删除 / 不可见」 and never renders, so retrying it would hang the
#: walk; it is skipped for good and its parent keeps the site's declared count.
_EXPAND_RE = re.compile(r'展开\s*\d+\s*条回复')

#: One round trip for the whole mounted panel: each TOP-LEVEL ``[data-e2e="comment-item"]`` as
#: ``{own, replies}``. A reply is itself a ``[data-e2e="comment-item"]`` nested inside the parent's
#: ``.replyContainer``; those are SKIPPED as parents (``it.closest``) and read only via the parent's
#: ``replies`` — otherwise they double-file and their innerText line order (timestamp before the
#: author) produces malformed rows with a blank region (both live bugs this guards). ``own`` is the
#: parent's LIVE ``innerText``; ``replies`` is each ``.replyContainer``'s text. Chrome's ``innerText``
#: on a detached ``cloneNode`` is empty, so the parent is read from the rendered element directly.
_THREADS_JS = r"""
    var items = document.querySelectorAll('[data-e2e="comment-item"]');
    var out = [];
    Array.prototype.forEach.call(items, function (it) {
      if (it.closest('[class*="replyContainer"]')) return;  // a reply: read under its parent, not as a thread
      var reps = Array.prototype.map.call(it.querySelectorAll('[class*="replyContainer"]'), function (r) {
        return (r.innerText || '').trim();
      });
      out.push({ own: (it.innerText || '').trim(), replies: reps });
    });
    return out;
    """

#: Stamps the expander's comment-item with ``data-dy-tried`` and reports whether THIS is a first try,
#: so a thread is clicked ONCE and never re-clicked — a second click while its signed reply request is
#: still loading can COLLAPSE it, which is what made a big thread re-open/lose-loop. False = already tried.
_MARK_JS = r"""
    var it = arguments[0].closest('[data-e2e="comment-item"]');
    if (!it) { arguments[0].setAttribute('data-dy-tried', '1'); return true; }
    if (it.hasAttribute('data-dy-tried')) return false;
    it.setAttribute('data-dy-tried', '1');
    return true;
    """

#: True only if some 「展开N条回复」 belongs to a comment-item NOT yet tried. The walk keeps going while an
#: untried thread remains but STOPS once every thread has been tried — even a thread that will not open —
#: otherwise one stubborn 「展开」 that never flips would block the exit forever.
_UNTRIED_JS = r"""
    var re = /展开\s*\d+\s*条回复/;
    var btns = document.querySelectorAll('button');
    for (var i = 0; i < btns.length; i++) {
      if (!re.test((btns[i].innerText || '').trim())) continue;
      var it = btns[i].closest('[data-e2e="comment-item"]');
      if (it && it.hasAttribute('data-dy-tried')) continue;
      return true;
    }
    return false;
    """

#: A failed 「展开N条回复」 pops a semi-ui toast/modal (评论已删除 / 该评论不可见) — a comment that is gone
#: or hidden on the web frontend, which is genuinely UNCRAWLABLE and must be skipped, not retried (the
#: ``data-dy-tried`` mark already guarantees one try, no retry). This only clears the popup so it can't
#: cover the panel; it never re-clicks. Douyin ships semi-ui (``.semi-modal``/``.semi-toast`` — the same
#: library the probe's DOM showed via ``semi-avatar``/``semi-icon``), so the close control is real, not guessed.
_POPUP_CLOSE_JS = r"""
    var popups = document.querySelectorAll('.semi-modal, [role="dialog"], .semi-toast, [class*="semi-toast"]');
    var visible = [];
    Array.prototype.forEach.call(popups, function (p) {
      var r = p.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) visible.push(p);
    });
    if (!visible.length) return 'none';
    var close = null;
    visible.forEach(function (p) {
      var c = p.querySelector('.semi-modal-close, [aria-label*="关闭"], [aria-label*="Close"], button[class*="close"]');
      if (!close && c) close = c;
    });
    if (close) { close.click(); return 'closed'; }
    return 'present';
    """


@register('douyin')
def walk(session, url: str, limit: int) -> tuple:
    """Scroll the rendered comment panel; douyin's API is signed.

    Unlike bilibili, the comments ARE in the DOM (``[data-e2e="comment-item"]``)
    and they grow by scrolling the app's own route container — measured 16 rows
    becoming 56 — while ``window.scrollTo`` does nothing at all. The panel's
    request carries ``a_bogus``/``msToken``, so there is no endpoint to call.

    「展开N条回复」 threads ARE expanded and their replies are filed as their own rows
    (``父楼层`` = the parent's floor). Measured on the real profile
    (``backend/test_douyin_subreply_probe.py``): a *native* ``ActionChains`` click on the
    actual ``button...comment-reply-expand-btn`` opens the thread (~1 s async), and the
    replies render inline as ``.replyContainer`` children of the same comment-item. A synthetic
    ``.click()`` does NOT (React's delegated handler ignores it) — so this click is a real one,
    not a dispatched event, and the opener is matched by its 「展开N条回复」 text (after a real
    expand it reads 「收起」, which both proves the open and stops a re-click from collapsing it).
    The walk re-reads the mounted items each round and dedups by (author, body, time), because
    douyin virtualises the list: an item scrolled past is unmounted, so a single final read
    would silently lose it.
    """
    from crawlers.platforms.douyin.crawler import douyin_id

    target = f'https://www.douyin.com/video/{douyin_id(url)}' if douyin_id(url) else url
    if not douyin_id(url):
        session.log(t('comment.dyNoId', url=url))
        return [], DEAD
    session.driver.get(target)
    mounted = _wait_for_panel(session)
    if looks_blocked(session.body_head()):
        # A security-check body is 风控, not a dead session: latch it on the owning
        # crawler so the node reports 「退避重试」, never 「重新保存 Cookie」 for a session
        # that may be perfectly fine.
        session.mark_risk_blocked()
        return [], BLOCKED
    reported = session.node_text('[data-e2e="feed-comment-icon"]')
    # The substitution test runs **before** the panel branch, not inside the 「没挂载」 arm: measured
    # 2026-09-28, the address can move to another video while the substitute's own panel mounts
    # happily, and a check that only fires on a failed mount would then walk the substitute's thread
    # and file every one of its comments under the link the user pasted. Same accident the detail
    # reader already refuses (``crawl.dy.detailSwapped``), same rule: a row nobody asked for is worse
    # than a missing one.
    shown = douyin_id(session.driver.current_url or '')
    if shown and shown != douyin_id(target):
        # The site served **another video**. Measured 2026-09-28, three visits to an id that cannot
        # exist: the address left ``/video/7000000000000000001`` for ``/jingxuan?modal_id=<other id>``
        # — a different substitute on every visit, and once the page printed 「你要观看的视频不存在」
        # for a moment before bouncing, so the plate is not a reliable read while the address is.
        # The old shape called this BLOCKED and logged 「该视频计有 1214 条评论」 — a figure belonging
        # to the substitute — which the node then reported as 「登录态疑似失效：COOKIE 可能过期」 for a
        # batch whose next link crawled its comments one line later. A link the site cannot serve is
        # DEAD: that row is lost, the session is not accused, and nobody's counts are filed under
        # the address the user pasted.
        session.log(t('comment.dyGone', url=target, shown=shown))
        return [], DEAD
    if not mounted:
        if not reported:
            # Neither a panel nor the counter that would explain its absence:
            # that is not "no comments", and reporting it as one would hide a
            # dead session behind an empty table.
            # Douyin's captcha speaks in the tab TITLE (which ``looks_blocked``
            # on the body could not see), so ask the owning crawler directly: if
            # it is walled, this is 风控 (back off), not a cookie to re-save.
            if session.is_walled():
                session.mark_risk_blocked()
            session.log(t('comment.dyNoPanel', url=target))
            return [], BLOCKED
        session.log(t('comment.dyNone', url=target, n=parse_count(reported)))
        if parse_count(reported) == 0:
            # The counter says none exist: an answer, not a failed read.
            return [], OK
        # The video says it has comments and the list never opened — a page
        # we could not read, which must never arrive as an empty table.
        return [], BLOCKED
    # No round budget. The loop used to be ``for _round in range(40)``, which decided the size of a
    # thread: measured 2026-09-28 on a video whose own counter reads 3388, the walk stopped at 406 rows
    # because its fortieth screen came and went, and returned ``OK`` as though the thread were finished.
    # 「怎么采不满」 is exactly this shape, so what ends a douyin panel walk is the panel itself — a
    # screen that grows no further, or the user's 停止 / his 评论条数.
    #
    # The walk re-reads every MOUNTED comment each round (one JS round trip, not one per element),
    # because douyin virtualises the panel: an item scrolled past is unmounted, so a single final
    # read would lose it. Dedup by (author, body, time) makes the re-read idempotent. Each round also
    # opens any still-collapsed reply thread, so its replies are mounted before the next read sees it.
    threads: dict = {}  # parent key -> {'fields', 'subs', 'replies' (ordered reply-key -> fields)}
    seen_identity: set = set()  # every (author, body, time) filed once — virtualisation re-expands a
    # re-collapsed parent on a later round, which would otherwise re-attach its replies as duplicates.
    reply_seen: set = set()
    prev_count = 0
    exit_reason = 'stuck'
    while True:
        opened = _expand_reply_threads(session)
        items = session.driver.find_elements('css selector', '[data-e2e="comment-item"]')
        count = len(items)
        _absorb_threads(_read_threads(session), threads, reply_seen, seen_identity)
        if session.may_stop():
            exit_reason = 'stopped'
            break
        if limit and len(threads) >= limit:
            exit_reason = 'target'
            break
        # The panel is drained only when nothing new mounted AND no thread was left to open. An
        # opener is proof there is more to read, so the walk must not stop while one remains.
        if count == prev_count and not opened and not _has_collapsed_opener(session):
            exit_reason = 'no_new'
            break
        prev_count = count
        # Stopped growing, but a thread openable by a further scroll means there is still more to read;
        # give up only when the scroll moved nothing AND nothing is openable.
        if not _scroll_panel(session) and not opened and not _has_collapsed_opener(session):
            exit_reason = 'stuck'
            break
        # A pacing pause between scrolled screens, so gentle crawl may stretch THIS one. The
        # other ``session.nap`` calls in this engine are page-arrival budgets (render waits), not
        # politeness, and must stay unscaled — which is why pacing is a direct
        # :func:`throttled_sleep`, not the session's ``nap`` knob.
        throttled_sleep(1.5)
    # Numbered once, over the whole thread (parent then its replies), because 楼层 is a continuous
    # floor across the panel and a reply's 父楼层 points back at that number — so it is assigned after
    # the walk, never per screen (AGENTS: a list is a document).
    rows, nested = parse_douyin_threads(threads, target)
    moved = douyin_id(session.driver.current_url or '')
    if rows and moved and moved != douyin_id(target):
        # The address moved while the panel was being walked, so every row above belongs to a video
        # nobody pasted. Discarded rather than filed: this is the same rule the hoisted check before
        # the walk applies, at the moment the walk is over and the cost already paid.
        session.log(t('comment.dyGone', url=target, shown=moved))
        return [], DEAD
    if not rows:
        # A panel of items that produced nothing is a parser or page problem,
        # never a fact about the video.
        session.log(t('comment.dyNoPanel', url=target))
        return [], BLOCKED
    declared = parse_count(reported)
    # ``nested`` is the UNCOLLECTED reply count (each parent's declared 「展开N条回复」 minus the
    # replies this walk actually opened and filed). Reply rows already sit in ``len(rows)``, so the
    # only thing still owed to the denominator is what could not be expanded. The gap therefore says
    # 「the site counted this many and the table + unexpandable replies still fall short」 — never
    # 「这条视频就这么多」 when it is not, and the exit reason keeps a user 停止 off the site's head.
    if declared and len(rows) + nested < declared and not (limit and len(rows) >= limit):
        session.log(
            t(
                'comment.dyShort',
                url=target,
                declared=declared,
                rows=len(rows),
                nested=nested,
                gap=declared - len(rows) - nested,
                reason=stop_reason_label(exit_reason),
            )
        )
    return (rows[:limit] if limit else rows), OK


def _expand_reply_threads(session) -> int:
    """Open every not-yet-tried 「展开N条回复」 thread once with a real (ActionChains) click.

    Clicks are batched and a single settle follows the round (not a per-opener wait): the reply request
    is signed and lands ~1 s after the click (user-measured), so one wait for the whole batch is what
    lets a reply-heavy thread finish instead of grinding. Returns how many it opened.
    """
    clicked = 0
    for btn in list(session.driver.find_elements('css selector', 'button')):
        if not _EXPAND_RE.search(session.safe_text(btn)):
            continue
        with contextlib.suppress(Exception):
            if not session.driver.execute_script(_MARK_JS, btn):
                continue
            session.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', btn)
            ActionChains(session.driver).move_to_element(btn).pause(0.1).click().perform()
            clicked += 1
    if clicked:
        session.nap(1.3)  # one settle for all the signed reply requests this round issued
        # A failed thread pops 「评论已删除 / 不可见」 — clear it so it can't block the rest of the panel.
        _dismiss_popup(session)
    return clicked


def _dismiss_popup(session) -> None:
    with contextlib.suppress(Exception):
        state = session.driver.execute_script(_POPUP_CLOSE_JS)
        # No close control found but a dialog is up: ESC dismisses a modal (comment mode has no video
        # overlay to hit, and ESC only fires when a popup is actually present — never blind).
        if state == 'present':
            session.driver.find_element('css selector', 'body').send_keys('\ue00c')


def _has_collapsed_opener(session) -> bool:
    """A thread NOT yet tried is still on the panel → the walk has more to open. Once every thread
    has been tried (opened, or failed-and-skipped) this is False, so a stubborn 「展开」 that only
    pops 「评论已删除」 cannot hang the walk — it is tried once and then skipped for good."""
    return bool(session.driver.execute_script(_UNTRIED_JS))


def _read_threads(session) -> list:
    with contextlib.suppress(JavascriptException):
        return session.driver.execute_script(_THREADS_JS) or []
    return []


def _absorb_threads(readings, threads: dict, reply_seen: set, seen_identity: set) -> None:
    """Fold one round's mounted readings into the ordered thread map, filing each identity ONCE.

    The panel virtualises: a parent re-read each round it re-mounts (key makes it idempotent), and — the
    live bug this guards — a re-collapsed parent re-expands under another identity and would re-attach its
    replies. ``seen_identity`` (every author/body/time) is the single source of uniqueness across BOTH
    parents and replies, so over-collection is impossible: a comment that is really someone's reply, but
    that douyin also mounts as a top-level item, is skipped as a parent if its reply already landed.
    ``subs`` keeps the largest declared count seen (an early read can be pre-hydration).
    """
    for one in readings or []:
        author, content, when, region, likes, subs = douyin_comment_fields(one.get('own'))
        if not content:
            continue
        key = (author, content, when)
        if key in threads:
            threads[key]['subs'] = max(threads[key]['subs'], subs)
        elif key in reply_seen:
            # This comment is already filed as a reply under another parent — not a top-level thread;
            # skip it (and its nested replies, which are the same comments) so it appears exactly once.
            continue
        else:
            seen_identity.add(key)
            threads[key] = {
                'author': author,
                'content': content,
                'when': when,
                'region': region,
                'likes': likes,
                'subs': subs,
                'replies': {},
            }
        slot = threads[key]
        for rtext in one.get('replies') or []:
            ra, rc, rw, rr, rl, _rs = douyin_comment_fields(rtext)
            if not rc:
                continue
            rkey = (ra, rc, rw)
            if rkey in seen_identity or rkey in slot['replies']:
                continue
            seen_identity.add(rkey)
            reply_seen.add(rkey)
            slot['replies'][rkey] = {'author': ra, 'content': rc, 'when': rw, 'region': rr, 'likes': rl}


def _wait_for_panel(session, timeout: float = 24.0) -> bool:
    """Poll until the comment list actually holds items.

    Measured: the ``[data-e2e="comment-list"]`` container mounts on the route
    *before* its first comment is rendered, so treating the container as
    "mounted" let a crawl read an empty list, break out of the loop on the
    first pass and return zero rows as a success. The item is the evidence.
    """
    ticks = max(1, int(timeout / 2.0))
    for _ in range(ticks):
        if session.driver.find_elements('css selector', '[data-e2e="comment-item"]'):
            return True
        time.sleep(2.0)
    return False


def _scroll_panel(session) -> bool:
    """Scroll whatever really scrolls on this page (the route container).

    Returns whether the panel grew. The settle wait is polled here rather
    than delegated to ``session.nap``: the rows mount asynchronously, so a
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
        return len(session.driver.find_elements('css selector', '[data-e2e="comment-item"]'))

    before = count()
    with contextlib.suppress(Exception):
        feed.jump_to_bottom(session.driver, '[data-e2e="comment-list"]')
    return bool(feed.wait_for(count, before + 1, timeout=6.0, tick=0.5) > before)
