"""xiaohongshu comments: the DOM panel read, the row builder and the thread walk.

What the panel really holds was measured on 2026-11-10 (``backend/test_xiaohongshu_thread_probe.py``,
two notes, one of them 359 comments), and every selector below is one of those facts:

* A top-level comment is a ``.parent-comment`` wrapper holding its own ``.comment-item`` **and** a
  ``.reply-container`` whose ``.comment-item.comment-item-sub`` cards are that comment's replies.
  The replies are SIBLINGS of the parent's card, not children of it — so a flat ``.comment-item``
  read (what this adapter used to do) collects them but cannot say whose they are.
* Each parent mounts **one** reply by default and keeps the rest behind a ``div.show-more`` whose own
  words are ``展开 N 条回复``. Measured: nine such controls on one panel, none of them clicked by the
  old walk — 楼中楼 was half-visible and silently short.
* ``共 N 条评论`` (``.comments-container .total``) counts parents **and** replies (2+2 = 4 on the
  first note), which makes it the one honest denominator for "did we get them all".
* Both levels carry ``id="comment-<24 hex>"``, which is the row's site identity — the ledger keys a
  comment on ``(平台, 评论ID)`` and the whole-row fallback would re-store a thread on every resume
  (``commenting/session.py`` says so by name).
* The author link carries a per-visit ``xsec_token`` query, so only its path is kept: a column that
  changes on every visit is not an identity.
* A click that the site refuses for lack of a session does not fail silently: it pops
  ``.login-modal``. That is measured as the refusal it is and named, never retried into a loop.
"""

import contextlib
import re

from selenium.webdriver.common.action_chains import ActionChains

from crawlers.commenting.protocol import BLOCKED, DEAD, OK
from crawlers.commenting.walks import register
from crawlers.engine import times
from crawlers.engine.counters import parse_count
from crawlers.engine.wall import classify
from crawlers.platforms.xiaohongshu.rows import note_id, with_feed_source
from i18n import stop_reason_label, t

#: One page-side round trip per screen: the whole panel as data.
#:
#: Structural selectors only — ``data-v-*`` attributes are per-deploy build hashes and are never
#: used. ``.parent-comment`` is the measured wrapper; the ``.comment-item:not(.comment-item-sub)``
#: fallback keeps an older layout readable rather than returning an empty panel.
PANEL_JS = r"""
return (function () {
  var root = document.querySelector('.comments-container');
  if (!root) { return {mounted: false}; }
  var text = function (el) { return ((el && el.innerText) || '').replace(/\s+/g, ' ').trim(); };
  var visible = function (el) {
    if (!el) { return false; }
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  function one(card) {
    if (!card) { return null; }
    var linkEl = card.querySelector('.author a, .author-wrapper a, .avatar a[href*="/user/profile/"]');
    var locEl = card.querySelector('.date .location');
    var dateEl = card.querySelector('.date');
    var dateText = '';
    if (dateEl) {
      var spans = dateEl.querySelectorAll('span');
      for (var i = 0; i < spans.length; i++) {
        if (spans[i].classList.contains('location')) { continue; }
        var piece = text(spans[i]);
        if (piece) { dateText = piece; break; }
      }
      if (!dateText) { dateText = text(dateEl); }
    }
    return {
      id: card.getAttribute('id') || '',
      author: text(card.querySelector('.author-wrapper .name, .name')),
      href: linkEl ? (linkEl.getAttribute('href') || '') : '',
      body: text(card.querySelector('.content')),
      date: dateText,
      region: text(locEl),
      likes: text(card.querySelector('.like .count, .like-wrapper .count')),
      replies: text(card.querySelector('.reply .count'))
    };
  }
  var parents = Array.prototype.slice.call(root.querySelectorAll('.parent-comment'));
  var holders = parents.length ? parents : Array.prototype.slice.call(
    root.querySelectorAll('.comment-item:not(.comment-item-sub)')
  );
  var cards = holders.map(function (holder) {
    var own = (holder.classList && holder.classList.contains('comment-item'))
      ? holder
      : holder.querySelector('.comment-item:not(.comment-item-sub)');
    var subs = Array.prototype.slice.call(holder.querySelectorAll('.comment-item-sub'));
    return {
      own: one(own),
      subs: subs.map(one).filter(Boolean),
      has_replies: !!holder.querySelector('.reply-container')
    };
  }).filter(function (card) { return !!card.own; });
  var openers = Array.prototype.slice.call(root.querySelectorAll('.reply-container .show-more')).map(
    function (el) {
      var holder = el.closest('.parent-comment');
      var own = holder ? holder.querySelector('.comment-item:not(.comment-item-sub)') : null;
      return {card: own ? (own.getAttribute('id') || '') : '', text: text(el)};
    }
  );
  return {
    mounted: true,
    total: text(root.querySelector('.total')),
    login_modal: visible(root.querySelector('.login-modal')) || visible(document.querySelector('.login-modal')),
    login_gate: visible(root.querySelector('.comments-login')) || visible(document.querySelector('.comments-login')),
    ended: /THE END|没有更多|到底/.test(text(root.querySelector('.end-container')) || ''),
    cards: cards,
    openers: openers
  };
})();
"""

#: The mounted card ids, in order — the panel's own fingerprint. Scrolling that changes nothing here
#: bought nothing, and that (not a round budget) is what ends the walk.
PANEL_KEY_JS = r"""
return (function () {
  var root = document.querySelector('.comments-container');
  if (!root) { return ''; }
  return Array.prototype.map.call(root.querySelectorAll('.comment-item'), function (el) {
    return el.getAttribute('id') || '';
  }).join('|');
})();
"""

#: The note's own login dialog, dismissed through its own control. Measured: an anonymous panel is
#: covered by ``.reds-mask`` and every click on a 展开 control answers ``element click intercepted``,
#: so the dialog is closed before the panel is read. Nothing is hidden or manipulated — the control
#: the site renders is the one clicked, and a dialog with no close control is left alone.
LOGIN_CLOSE_JS = r"""
return (function () {
  var modal = document.querySelector('.login-modal');
  if (!modal) { return ''; }
  var r = modal.getBoundingClientRect();
  if (!r.width) { return ''; }
  var close = modal.querySelector('[class*="close"], [aria-label*="关闭"], [aria-label*="close"]');
  if (!close) { return 'no-control'; }
  close.click();
  return 'closed';
})();
"""

#: The opener's own words, measured: ``展开 3 条回复`` / ``展开 10 条回复``. Matched on the sentence,
#: never on a build hash, and the count is kept so the site's own number can be reported.
OPENER_RE = re.compile(r'展开\s*(\d+)\s*条回复')

#: How many consecutive screens may add nothing AND leave no thread that grew before the walk believes
#: the panel is done. Patience, not a budget: the panel answers a scroll in ~2 s, and one quiet round is
#: what a slow answer looks like (weibo's ``EMPTY_ROUNDS`` exists for the same measurement). Measured on
#: the 357-comment note: the last screen can land three rounds after the panel looked finished, and
#: stopping one round early cost two top-level comments and a reply.
QUIET_ROUNDS = 3

#: How long one expansion batch is given to mount its replies. Measured: the replies render ~1-2 s
#: after the click; a per-opener wait would multiply that by the number of threads on screen.
EXPAND_SETTLE = 1.8


def parse_xhs_threads(threads, url: str) -> list:
    """Ordered ``{parent key: slot}`` → rows, one per comment.

    **``楼层`` numbers TOP-LEVEL comments only**, 1..N in the order the panel shows them; a reply's
    own ``楼层`` is blank and its ``父楼层`` names the top-level comment it answers. This is the site's
    own notion of a floor (a reply does not get one), it keeps the column unique — a table where two
    rows share a number belongs to no honest reading — and it is what ``reply_graph`` reads: parents
    are the floor map, replies are the edges.

    A parent's **子回复数** is the number of reply rows this walk actually landed, falling back to
    the site's own count when no reply could be opened — so the column never claims replies that are
    not in the table, and never hides the ones the site says exist.
    """
    rows = []
    for floor, slot in enumerate(threads.values(), 1):
        captured = len(slot['subs'])
        rows.append(_row(url, slot['own'], floor=floor, parent_floor='', replies=captured or slot['declared']))
        for sub in slot['subs']:
            rows.append(_row(url, sub, floor='', parent_floor=floor, replies=0))
    return rows


def _row(url: str, card: dict, floor, parent_floor, replies: int) -> dict:
    return {
        '平台': 'xiaohongshu',
        '文章URL': url,
        '评论者': str(card.get('author') or ''),
        '评论者主页': _profile_url(card.get('href')),
        '评论内容': str(card.get('body') or ''),
        # The panel's own date cell is a relative wording for anything recent ("3小时前"): resolved
        # here, because a time series built on the site's words silently loses those rows.
        '评论时间': times.absolute(card.get('date')),
        '评论地区': str(card.get('region') or ''),
        '点赞数': parse_count(card.get('likes')),
        '子回复数': replies,
        '楼层': floor,
        # '' and not 0: a top-level comment has no parent floor, and a zero would read as floor 0.
        # A reply's own 楼层 is blank too — its position IS the 父楼层 it names.
        '父楼层': parent_floor,
        '评论ID': _comment_id(card.get('id')),
    }


def _comment_id(raw) -> str:
    """``id="comment-<hex>"`` → ``<hex>``; anything else is kept as it came, never invented."""
    text = str(raw or '').strip()
    return text[len('comment-') :] if text.startswith('comment-') else text


def _profile_url(href) -> str:
    """The commenter's own page, with the per-visit ``xsec_token`` query dropped.

    Measured: the same author link carries a different ``xsec_token`` on every visit, so keeping the
    query makes one person look like two rows across runs. The path is the identity.
    """
    raw = str(href or '').strip()
    if not raw:
        return ''
    path = raw.split('?', 1)[0].split('#', 1)[0]
    if path.startswith('http'):
        return path
    if path.startswith('/'):
        return f'https://www.xiaohongshu.com{path}'
    return path


def _identity(card: dict) -> str:
    """A comment's key: its site id, or a content key for a row the site left unlabelled."""
    cid = _comment_id(card.get('id'))
    if cid:
        return f'id:{cid}'
    parts = (card.get('author'), card.get('body'), card.get('date'), card.get('region'))
    return 'text:' + '\x1e'.join(str(part or '') for part in parts)


def _absorb(panel: dict, threads: dict) -> int:
    """Fold one screen's cards into the ordered thread map; return how many rows were new.

    Keyed by the site's comment id, so a screen re-read (a panel that re-mounts the same cards after
    a scroll) adds nothing, while two identical bodies from one author stay two rows — the previous
    ``(author, body)`` key collapsed exactly the "谢谢！" chains 楼中楼 is made of.
    """
    added = 0
    for card in panel.get('cards') or []:
        own = card.get('own') if isinstance(card, dict) else None
        if not isinstance(own, dict) or not str(own.get('body') or '').strip():
            continue
        key = _identity(own)
        slot = threads.get(key)
        declared = parse_count(own.get('replies'))
        if slot is None:
            slot = threads[key] = {'own': own, 'subs': [], 'declared': declared}
            added += 1
        elif declared > slot['declared']:
            # A pre-hydration read can answer a smaller number; the largest one seen is the site's.
            slot['declared'] = declared
        known = {_identity(sub) for sub in slot['subs']}
        for sub in card.get('subs') or []:
            if not isinstance(sub, dict) or not str(sub.get('body') or '').strip():
                continue
            sub_key = _identity(sub)
            if sub_key in known:
                continue
            known.add(sub_key)
            slot['subs'].append(sub)
            added += 1
    return added


def _read_panel(session) -> dict:
    with contextlib.suppress(Exception):
        return session.driver.execute_script(PANEL_JS) or {}
    return {}


def _panel_key(session) -> str:
    with contextlib.suppress(Exception):
        return str(session.driver.execute_script(PANEL_KEY_JS) or '')
    return ''


def _dismiss_login(session) -> None:
    """Close the note's own login dialog so the panel underneath can be read and clicked."""
    # The dialog is dismissed through the control the site renders; nothing is hidden by us.
    with contextlib.suppress(Exception):
        session.driver.execute_script(LOGIN_CLOSE_JS)
    session.click_nap(0.6)


def _login_modal_up(session) -> bool:
    with contextlib.suppress(Exception):
        return bool(
            session.driver.execute_script(
                """
                return (function () {
                  var m = document.querySelector('.login-modal');
                  if (!m) { return false; }
                  var r = m.getBoundingClientRect();
                  return r.width > 0 && r.height > 0;
                })();
                """
            )
        )
    return False


def _expand_threads(session, panel: dict, state: dict) -> tuple:
    """Click every 展开 control whose thread still owes replies, and learn which ones are finished.

    A native ``ActionChains`` click, because a synthetic one does not move React's delegated handler
    (douyin's measurement, and this site answered the same way before a session was present).

    **A thread is clicked again on a later round while it still owes replies** — measured 2026-11-10:
    one click reveals a batch (40 new cards over 10 threads) and the control's own words change from
    ``展开 N 条回复`` to ``展开更多回复``, i.e. the site pages a thread out instead of opening it whole.
    What retires a thread is the panel's evidence, not a count of our attempts: a click that adds no
    reply to THAT thread marks it done (``state['done']``). A thread whose mounted replies have already
    reached the site's own ``.reply .count`` is skipped without a click at all.

    Returns ``(clicked, gated)``; ``gated`` means the site answered with its login dialog, which is a
    refusal to report and never to retry.
    """
    mounted: dict = {}
    declared: dict = {}
    for card in panel.get('cards') or []:
        own = card.get('own') or {}
        card_id = _comment_id(own.get('id'))
        if not card_id:
            continue
        mounted[card_id] = len(card.get('subs') or [])
        declared[card_id] = parse_count(own.get('replies'))
    openers = panel.get('openers') or []
    pending = []
    for position, one in enumerate(openers):
        card = _comment_id(one.get('card'))
        if not card:
            continue
        if card in state['done']:
            continue
        # ``展开更多回复`` is the site SAYING there is another page (measured after a batch), so it is
        # clicked regardless of arithmetic — ``.reply .count`` is sometimes a rounded ``10+`` label,
        # and stopping at its face value would hide the 11th reply behind our own reading of it.
        more = '更多' in str(one.get('text') or '')
        if declared.get(card) and mounted.get(card, 0) >= declared[card] and not more:
            # The site's own reply count is met and it is not asking for another page.
            state['done'].add(card)
            continue
        pending.append((position, card))
    if not pending:
        return 0, False
    with contextlib.suppress(Exception):
        elements = session.driver.find_elements('css selector', '.comments-container .reply-container .show-more')
        if len(elements) != len(openers):
            # The panel moved between the read and the click: nothing is clicked blind, because a
            # click on the wrong thread files another comment's replies under the wrong parent.
            return 0, False
        clicked_cards = []
        for position, card in pending:
            element = elements[position]
            with contextlib.suppress(Exception):
                session.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', element)
                ActionChains(session.driver).move_to_element(element).pause(0.1).click().perform()
                clicked_cards.append(card)
        if not clicked_cards:
            return 0, False
        session.expand_nap(EXPAND_SETTLE)
        if _login_modal_up(session):
            # The site answered the whole batch with "log in to see replies" — dismissing it and
            # clicking the rest would only pay for the same dialog again.
            _dismiss_login(session)
            return len(clicked_cards), True
        after = _read_panel(session)
        after_counts = {}
        for card in after.get('cards') or []:
            own = card.get('own') or {}
            card_id = _comment_id(own.get('id'))
            if card_id:
                after_counts[card_id] = len(card.get('subs') or [])
        grew = 0
        for card in clicked_cards:
            if after_counts.get(card, 0) > mounted.get(card, 0):
                grew += 1
                state['fails'].pop(card, None)
                continue
            # This click opened nothing. ONE observation is not proof — the batch's replies can land
            # a moment after the settle (measured: a single 1.8 s wait lost a whole batch and the
            # "tried once" mark then hid 42 replies). So:
            #   * while the panel is still feeding new cards, the thread is NOT retired (the page is
            #     alive and a later click is what lands the replies — measured: retrying every round
            #     reached 139 replies where retiring after one attempt stopped at 97);
            #   * once the panel has gone quiet, two failed attempts retire it for good.
            state['fails'][card] = state['fails'].get(card, 0) + 1
            if state['idle'] and state['fails'][card] >= 2:
                state['done'].add(card)
        # "clicked" means "the panel may have changed", so a click that grew nothing must not keep the
        # walk's quiet counter at zero — that is exactly how a stubborn opener spins forever.
        return grew, False
    return 0, False


def _scroll_panel(session) -> None:
    """Scroll the box that actually feeds the comment list, and only then the note's own scroller.

    Measured 2026-11-10 on the 359-comment note: the old target (``.note-scroller``) moved the note's
    text column and the panel stopped at 30 parents, while the box holding the comments —
    ``.note-container`` — grew 10 cards per scroll (164 → 176 → 186 → 196 over four rounds, its own
    ``scrollHeight`` 23159 → 27730). The rule is zhihu's, and for the same reason: pick the scrollable
    ancestor that holds the MOST cards, so a wrapper that happens to be scrollable cannot trap the walk.
    """
    script = """
    var best = null, most = 0;
    var nodes = document.querySelectorAll('div, section, ul, main');
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.scrollHeight <= n.clientHeight + 40) { continue; }
      var count = n.querySelectorAll('.comment-item').length;
      if (count > most) { most = count; best = n; }
    }
    var box = best || document.querySelector('.note-scroller') || document.scrollingElement || document.body;
    box.scrollTop = box.scrollHeight;
    if (box !== document.body) { window.scrollBy(0, 800); }
    """
    with contextlib.suppress(Exception):
        session.driver.execute_script(script)


def _row_count(threads: dict) -> int:
    return sum(1 + len(slot['subs']) for slot in threads.values())


@register('xiaohongshu')
def walk(session, url: str, limit: int) -> tuple:
    """One note's comments — every 楼中楼 thread the site will open — read off the mounted panel.

    The walk ends on the panel's own evidence, never on a round budget: a screen that adds nothing,
    no thread left to open, and a scroll that changed no mounted card all at once. A fixed number of
    screens used to end this walk quietly, which made “怎么采不满” look like “这条笔记就这么多评论”.
    """
    expected = note_id(url)
    # The site's own web-feed links carry ``xsec_source=pc_feed``; a pasted link that names no
    # source can be served the feed instead of the note (the "stuck on the homepage" shape), so
    # the navigation URL gets that one parameter filled in. The row identity stays the URL the
    # user gave us — only what we ask the site for changes.
    session.get(with_feed_source(url))
    session.arrival_nap(5)
    current = session.driver.current_url or ''
    # One shared classifier decides arrival, not a 600-character body sniff: the URL carries XHS's
    # login redirect, the browser's own error page is `unreachable`, and `login` vs `blocked` are
    # opposite advice (re-save the cookie vs back off). Only the body check used to run, so a real
    # risk page was reported as "cookie expired" and a URL-only login bounce fell through to
    # "no panel → ok, 0 rows".
    title = ''
    with contextlib.suppress(Exception):
        title = session.driver.title or ''
    verdict = classify(current, session.body_head(), title, document_uri=session.document_uri())
    if verdict == 'login':
        session.mark_login_wall()
        return [], BLOCKED
    if verdict == 'unreachable':
        # A browser error page is a network fact, not a risk verdict: naming it as 风控 cooled
        # the EXIT for two hours and told the user their session was blocked. Keep the walk
        # retryable and let the pool record the network reason.
        session.mark_unreachable()
        return [], BLOCKED
    if verdict == 'blocked':
        session.mark_risk_blocked()
        return [], BLOCKED
    shown = note_id(current)
    if expected and not shown and 'xiaohongshu.com' in str(current or '').lower():
        # The link did not open a note AT ALL. Measured shape (docs/crawler_notes.md): a note URL
        # whose ``xsec_token`` has aged out is redirected to the feed (``/explore``), so the browser
        # sits on the site's homepage, no comment panel ever mounts, and the old code walked every
        # remaining link the same way while reporting nothing. That is the "为什么一直停在主页"
        # symptom, and it is a DEAD link rather than an empty note: the site never served the note.
        #
        # Gated on the host: a short link (``xhslink.com``) or a browser still on its own start page
        # has not landed anywhere yet, and that stays on the retryable "no panel" path below rather
        # than convicting a link that may merely still be resolving.
        session.log(t('comment.xhsRedirected', url=url, landed=current or '?'))
        return [], DEAD
    if expected and shown and shown != expected:
        # The link opened ANOTHER note (a dead/aged token lands on the feed or on a substitute).
        # A row nobody asked for is worse than a missing one, so it is DEAD, not BLOCKED: the session
        # is not accused for a link the site could not serve.
        session.log(t('comment.xhsGone', url=url, shown=shown))
        return [], DEAD
    _dismiss_login(session)

    threads: dict = {}
    expand = {'done': set(), 'fails': {}, 'gated': False, 'idle': False}
    panel: dict = {}
    exit_reason = 'no_new'
    key = None
    quiet = 0
    while True:
        panel = _read_panel(session)
        if not panel.get('mounted'):
            if threads:
                # The panel was there and reading it produced rows: what is left is the final answer.
                break
            session.log(t('comment.xhsNoPanel', url=url))
            # "No panel" is not proof the thread is empty: a login redirect or a page that never
            # rendered leaves the cursor on this link so 继续 re-walks it.
            session.mark_unproven(url)
            return [], OK
        if panel.get('login_modal'):
            # A dialog the page raised on its own covers the panel; the site's own control closes it.
            _dismiss_login(session)
        fresh = _absorb(panel, threads)
        if panel.get('login_gate'):
            # The site's own "登录查看全部评论内容" element: a wall, not a note with zero comments.
            session.mark_login_wall()
            rows = parse_xhs_threads(threads, url)
            return (rows[:limit] if limit else rows), BLOCKED
        # "The panel has stopped feeding" — read BEFORE this round's expansion, so the expander knows
        # whether a failed click is final (the list is over) or just early (cards are still mounting).
        expand['idle'] = quiet > 0
        if session.may_stop():
            exit_reason = 'stopped'
            break
        if limit and _row_count(threads) >= limit:
            exit_reason = 'target'
            break
        clicked, gated = (0, False) if expand['gated'] else _expand_threads(session, panel, expand)
        if gated and not expand['gated']:
            expand['gated'] = True
            # A refusal is said out loud the moment it happens: the alternative is a table whose
            # parents each carry one reply and no line explaining the other 150.
            session.log(t('comment.xhsLoginGate', url=url, rows=_row_count(threads)))
        current = _panel_key(session)
        if not fresh and not clicked and key is not None and current == key:
            quiet += 1
            if quiet >= QUIET_ROUNDS:
                # The site's own end marker at the bottom of the panel (`- THE END -`, measured with the
                # box at 33359/34181 px) makes the ending quotable as "this note has no more comments".
                # It still waits the same patience: THE END is about the comment LIST, and a batch of
                # replies clicked a round ago can land after it appears.
                exit_reason = 'end' if panel.get('ended') else 'no_new'
                break
        else:
            quiet = 0
        key = current
        _scroll_panel(session)
        session.scroll_nap(1.2)

    rows = parse_xhs_threads(threads, url)
    if expand['gated']:
        # The site refused the replies with its login dialog. Keep every row already read and report
        # BLOCKED: the node fails by name, the cursor stays here, and 继续 re-walks after a login —
        # instead of filing an "ok, 0 new" table the cursor then steps over.
        return (rows[:limit] if limit else rows), BLOCKED
    declared = parse_count((panel or {}).get('total'))
    # `nested` is the replies the site's own numbers count and this walk never opened, so the gap
    # stays honest whether or not the threads opened — and never double-counts landed reply rows.
    nested = sum(max(slot['declared'] - len(slot['subs']), 0) for slot in threads.values())
    asked = bool(limit and len(rows) >= limit)
    # The site's own `- THE END -`, a reconciled denominator, or the user's own limit is the only
    # evidence that licenses a short table. Without one, a shortfall (or a walk that merely stopped
    # growing / was stopped) is a hole: the cursor is pinned on this link and 继续 re-walks it
    # rather than treating "0 new" as the answer.
    reconciled = bool(declared) and len(rows) + nested >= declared
    licensed = bool((panel or {}).get('ended')) or asked or reconciled
    if declared and len(rows) + nested < declared and not asked:
        session.log(
            t(
                'comment.xhsShort',
                url=url,
                declared=declared,
                rows=len(rows),
                nested=nested,
                gap=declared - len(rows) - nested,
                reason=stop_reason_label(exit_reason),
            )
        )
    elif nested and not asked:
        # The totals reconcile — but only because the site's own reply count covers the replies this
        # walk could not open. A table of 2 rows for a thread of 3 is still short, and saying nothing
        # is the silent under-collect this repo refuses.
        session.log(
            t(
                'comment.xhsNested',
                url=url,
                declared=declared,
                rows=len(rows),
                nested=nested,
                reason=stop_reason_label(exit_reason),
            )
        )
    if not licensed:
        session.mark_unproven(url)
    return (rows[:limit] if limit else rows), OK
