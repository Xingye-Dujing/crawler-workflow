"""红果短剧 comment harvest: the desktop player signs, mitmproxy reads, UIA walks.

Why this shape and not a request builder: the comment endpoint
(``api5-normal-lq.fqnovel.com/novel/commentapi/comment/list/{group_id}/v1/``) is
guarded by the ByteDance family signature (x-medusa/x-helios); measured 2026-10-19,
even a byte-identical replay with a fresh ticket answers ``Code 110001``. The
third-party desktop player (红果短剧.exe, Wails/Go) has already implemented the whole
protocol, honors ``HTTPS_PROXY`` from its environment, and does not pin TLS beyond
the Windows user root store (all three facts in ``docs/crawler_notes.md`` 红果短剧).
So the player is the signer and this module only:

1. starts ``mitmdump`` with :mod:`crawlers.harvest_addon` (narrow filter → JSONL),
2. starts the player WITH the proxy env (refusing by name if an un-proxied player
   is already running — that window belongs to the user and is never killed),
3. drives the player through UI Automation (search the drama, switch episodes),
4. parses what the JSONL delivers through :mod:`crawlers.comments_hongguo`.

The engine caches one harness per (node run, platform), so the stack stays up
across the drama links of one comment node and is reaped in its ``finally``.
"""

import base64
import contextlib
import ctypes
import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid

import requests

from config import Config
from i18n import t
from settings_store import get_setting
from utils.helpers import as_bool

from .base import UNDER_TARGET, CrawlerStopped
from .comments_base import DEAD, OK
from .comments_hongguo import hg_comment_rows, hg_page_title, hg_series_id

logger = logging.getLogger(__name__)

_ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harvest_addon.py')
#: The window class the Wails player registers (measured; also the UIA root's ClassName).
_PLAYER_CLASS = 'wailsWindow'
#: The web detail page, rebuilt from a bare ``series_id`` so the title can be read from it
#: (``crawlers.hongguo.BASE`` is the same host; the harvest does not import that crawler).
_DETAIL_BASE = 'https://hongguoduanju.com/detail'
#: The action-rail comment button: ``💬`` plus the site's own count (``410``, ``5.1万``)
#: — the sidebar's feedback button is ``💬 反馈`` and must not be clicked for comments.
_RAIL_COMMENT_RE = re.compile(r'^💬\s*[\d.]+\s*[万千]?\+?$')
#: A comment's OWN action button is literally ``回复`` (or ``回复 3``); it opens the
#: composer and steals the keyboard focus the drawer scroll needs. Measured on a real
#: run 2026-10-19: the old needle '回复' clicked one of those, the wheel then paged
#: nothing, and a thread the site counted at 698 came home with 20 rows.
_BARE_REPLY_RE = re.compile(r'^回复\s*[\d.]*$')
#: The expand control says BOTH "replies" and "there are more of them to see".
_EXPAND_WORDS = ('展开', '查看', '更多')
#: A card name may legitimately differ from the requested one by a season suffix the
#: other side does not print (「剧名」/「剧名 第二季」) — but never by containment in the
#: middle, which is what put another drama's comments into this table.
_MIN_TITLE_PREFIX = 4
_TITLE_NOISE = re.compile(r'[\s《》「」『』【】()（）·、,，.。!！?？:：\-—]+')
#: What the leaderboard's switcher names its lists — 总榜/必看榜/臻果榜/AI剧 … The client
#: owns this list; the tuple below is only the fallback when its popup refuses.
_BOARD_NAME_RE = re.compile(r'^[\w一-鿿]{1,8}(?:榜|剧)$')
_FALLBACK_BOARDS = ('必看榜', '热播榜', '总榜', '推荐榜', 'AI剧')
#: How many silent scrolls one episode tolerates before the walk calls it a stall. A page
#: that arrives on the third try is the whole point (the first live run lost ~600 comments
#: to a single silent one).
_MAX_STALLS = 3
#: How long a tree that went cold MID-walk gets to answer again, longer than a cold launch:
#: the renderer is already running, it has simply stopped being asked loudly enough.
_COLD_REWAKE_SECONDS = 120
#: How long the walk waits after its last expansion click, before it closes the door on this
#: drama. A reply page in flight is not a page the next drama owns: drained without this grace
#: it lands in the NEXT walk and is stamped with another 剧名's rows.
_REPLY_SETTLE_SECONDS = 2.0


class TreeColdError(ValueError):
    """The window is there and its UIA tree is not — an environment refusal, not a miss.

    Its own type because the caller must tell "the player's page will not wake" apart from
    "this drama is not in the client's lists": the first is a machine fact the user can fix
    by touching the window, the second is a ranking fact about the site, and only the second
    one is a reason to move on to the next drama. Comparing message text for that would break
    the moment a translation changed.
    """


def is_expand_control(name) -> bool:
    """Is this drawer control the 「展开 N 条回复」 link (and NOT a comment's 回复 button)?

    Pure, and pinned by a table test, because the rule cost a whole episode's comments:
    a name must speak of 回复 AND promise MORE of them. ``回复``/``回复 3`` refuse, and so
    does a section header like ``热门回复`` — nothing here opens a composer.
    """
    text = str(name or '').strip()
    if '回复' not in text:
        return False
    if _BARE_REPLY_RE.match(text):
        return False
    return any(word in text for word in _EXPAND_WORDS)


def _norm_title(text) -> str:
    """A drama name compared the way the two pages spell it: no punctuation, no spacing."""
    return _TITLE_NOISE.sub('', str(text or '')).lower()


def _same_drama(want_norm: str, name: str) -> bool:
    """Does this card name the drama the walk asked for?

    Equality after normalisation, or a start-with relation whose shorter side is long
    enough to be a name of its own. The loose containment this replaced matched a short
    card title inside a longer one, and 错剧 rows are a corrupted table rather than a
    smaller one — a missing drama is refused by name instead.

    This is the FALLBACK matcher only: :meth:`PlayerUI._play_for_title` asks for an exact
    card across the whole tree first, because this rule on its own still opens 斗罗大陆 for
    a request that named 斗罗大陆 第二季.
    """
    have = _norm_title(name)
    if not want_norm or not have:
        return False
    if want_norm == have:
        return True
    shorter, longer = sorted((want_norm, have), key=len)
    return len(shorter) >= _MIN_TITLE_PREFIX and longer.startswith(shorter)


def find_player() -> str:
    """The player exe: explicit setting only.

    Deliberately not a disk search: the install directory is the user's choice
    (``D:\\guo-…`` today), a guessed path would harvest against the wrong build,
    and the refusal names the exact setting to fill.
    """
    path = str(get_setting('hongguo_player_path') or '').strip()
    return path if path and os.path.isfile(path) else ''


def find_mitmdump() -> str:
    """mitmdump: explicit setting → PATH → this venv's Scripts (where ``pip install
    mitmproxy`` puts it) → '' (refused by name at the caller)."""
    explicit = str(get_setting('mitmdump_path') or '').strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    found = shutil.which('mitmdump')
    if found:
        return found
    beside = os.path.join(os.path.dirname(sys.executable), 'mitmdump.exe')
    return beside if os.path.isfile(beside) else ''


class PlayerUI:
    """UI Automation over the player window — every method best-effort.

    The spine (named nav buttons, the ``1 / 9+`` episode counter, arrow-key episode
    switching) was measured against the real window 2026-10-19. The comment
    drawer's controls were NOT yet measured, so opening and scrolling it is
    attempted generically and its failure degrades the harvest to the pages the
    feed already auto-fetches — depth lost, never a crash and never a lie.
    """

    def __init__(self, log=None, abort=None):
        self._log = log or (lambda _m: None)
        # 停止 has to interrupt the WAITING, not only the walking: a cold tree costs
        # ``wait_content(120)`` per retry on top of ``open_drama``'s own budgets, so a node
        # over ten dramas could spend minutes asking nothing. This repo's rule is that every
        # page settles by polling and asks the caller's abort — a slept-through Stop once
        # turned a 2000-comment video into a 5-row crawl that looked like success.
        self._abort = abort or (lambda: False)
        self._auto = None

    def _stopped(self) -> bool:
        return bool(self._abort())

    def _check_stopped(self):
        """Raise, never return None: a Stop that reads as a timeout would be filed as
        「这部剧搜不到」 and the node would name a drama the user simply stopped on."""
        if self._stopped():
            raise CrawlerStopped(t('crawl.stopped'))

    def _ensure_library(self):
        if self._auto is None:
            import uiautomation as auto  # guarded: Windows desktop extra

            self._auto = auto
        return self._auto

    def window(self):
        """The player's top-level window control, or ``None``."""
        if not ctypes.windll.user32.FindWindowW(_PLAYER_CLASS, None):
            return None
        auto = self._ensure_library()
        for top in auto.GetRootControl().GetChildren():
            try:
                if (top.ClassName or '') == _PLAYER_CLASS:
                    return top
            except Exception:
                continue
        return None

    def wait_window(self, seconds: float = 40.0):
        """The window, once it EXISTS — a cold Wails launch needs a few seconds and
        the first probe right after Popen found nothing (measured on the first live
        run: ``open_drama`` raced the splash and refused in 3 s)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self._check_stopped()
            win = self.window()
            if win is not None:
                return win
            time.sleep(0.5)
        return None

    def wait_content(self, seconds: float = 60.0):
        """The window, once its WEB CONTENT is walkable.

        Measured 2026-10-19: a freshly launched WebView2 exposes only the title bar
        for tens of seconds — the DOM's UIA tree is built lazily, and every earlier
        success had happened only after previous walks had warmed it. This polls the
        app's most stable anchor (the 推荐 sidebar button) and re-asks loudly enough
        to wake the renderer; a page that never answers returns None, and the caller
        refuses by name rather than clicking a title bar forever.
        """
        deadline = time.time() + seconds
        while time.time() < deadline:
            self._check_stopped()
            win = self.window()
            if win is not None:
                hit = self._find(win, '推荐', 'ButtonControl')
                if hit is not None:
                    return win
            time.sleep(1.5)
        return None

    def _find_until(self, needle, ctype=None, seconds: float = 10.0):
        """``_find`` re-asked until the page finished rendering, or the budget ends."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            self._check_stopped()
            hit = self._find(self.window(), needle, ctype)
            if hit is not None:
                return hit
            time.sleep(0.5)
        return None

    def collect(self, max_depth: int = 20):
        """Every (control, type, name, rect) of the window's tree, collected WHOLE.

        The whole-tree walk is the wake-up itself: measured 2026-10-19, a partial
        walk that early-returns on the first hit leaves the renderer's UIA tree
        unbuilt (it answers cold, and the next caller sees only the title bar),
        while a complete walk both reads the page and keeps it warm for the next.
        A poisoned branch that raises mid-walk is skipped, not fatal.
        """
        self._ensure_library()
        win = self.window()
        if win is None:
            return []
        items = []

        def walk(c, d):
            if d > max_depth:
                return
            try:
                items.append((c, c.ControlTypeName, c.Name or '', c.BoundingRectangle))
            except Exception:
                return
            try:
                children = c.GetChildren()
            except Exception:
                return
            for ch in children:
                walk(ch, d + 1)

        walk(win, 0)
        return items

    def _find(self, win, needle, ctype=None, depth=0):
        """First control whose Name contains *needle* — via the warming full walk."""
        if win is None:
            return None
        for ctrl, kind, name, _rect in self.collect():
            if needle in name and (ctype is None or kind == ctype):
                return ctrl
        return None

    def _click(self, ctrl) -> bool:
        try:
            rect = ctrl.BoundingRectangle
            self._ensure_library().Click((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
            return True
        except Exception as exc:
            logger.debug('hongguo harvest: UIA click failed: %s', exc)
            return False

    def open_drama(self, title: str) -> bool:
        """Open *title* through the 排行榜 page — the measured navigation.

        Measured 2026-10-19: the 找剧 page has NO search box (it is a browse feed),
        while 排行榜 lists dramas as cards, each with its title text and its own
        ``▶ 播放`` button — clicking there starts the feed AT that drama, exactly
        what the comment harvest needs. WHICH lists that walk may enter is the
        client's own answer (see :meth:`_board_labels`), because the web 热榜 and the
        player's 排行榜 are two different ranking families: a drama the web board ranks
        first sat on the player's 必看榜, and one the client does not list at all simply
        is not findable here — the caller says so by name. The card order is stable in
        the tree (title … then that card's 播放), so the play button is the first one
        AFTER the matched title.
        """
        if self.wait_content() is None:
            # The window exists but its DOM never became walkable (see wait_content)
            # — an environment fact the user can fix, named, never a fake 搜不到剧.
            raise TreeColdError(t('crawl.hg.cmt.treeCold'))
        try:
            rank = self._find_until('排行榜', 'ButtonControl', seconds=20)
            if rank is None or not self._click(rank):
                return False
            time.sleep(4)
            for label in self._board_labels():
                self._check_stopped()
                self._pick_board(label)
                for _scroll in range(3):
                    self._check_stopped()
                    hit = self._play_for_title(title)
                    if hit is not None:
                        self._click(hit)
                        time.sleep(3.0)
                        return True
                    self._ensure_library().WheelDown(wheelTimes=3, interval=0.12)
                    time.sleep(2.0)
            return False
        except CrawlerStopped:
            # 停止 is not a search that failed. Swallowed here it would file the drama the
            # user stopped on under 「搜不到这部剧」 and name it in the skip refusal.
            raise
        except Exception as exc:
            logger.debug('hongguo harvest: open_drama failed: %s', exc)
            return False

    def _board_labels(self) -> list[str]:
        """The board names the player's own switcher offers, in the order it prints them.

        Hard-coding the five lists somebody remembered was a second opinion about a page
        the client owns: it silently stops working the day the app renames 臻果榜 or adds
        a 新剧榜, and the walk then refuses a drama that was on screen the whole time.

        The switcher is opened BEFORE the page is read, and a read taken from the closed
        page is only a fallback. One tab named like a board — or the selected board printed
        without its ▾ — matches the very pattern that recognises the whole list, so trusting
        that read first returned a one-name list, the switcher never opened, and every drama
        sitting on another board was refused as 「搜不到这部剧」: the miss this walk exists to
        fix, reimposed by its own shortcut.
        """
        labels = []
        toggle = self._board_toggle()
        if toggle is not None and self._click(toggle):
            time.sleep(1.5)
            labels = self._visible_boards()
        return labels or self._visible_boards() or list(_FALLBACK_BOARDS)

    def _board_toggle(self):
        """The leaderboard's own 「总榜 ▾」 switcher button, or ``None``."""
        return self._find_until('榜 ▾', 'ButtonControl', seconds=8) or self._find_until(
            '剧 ▾', 'ButtonControl', seconds=3
        )

    def _visible_boards(self) -> list[str]:
        """Every board-name button currently on screen (open popup, or the visible tabs).

        Nothing is truncated: the measured switcher lists eleven names, and dropping the
        tail to save time would silently skip the list a drama actually sits on — which is
        the failure this walk is not allowed to have. The cost is bounded elsewhere (three
        scrolls per list, and the search stops the moment the card is found).
        """
        found = []
        for _ctrl, kind, name, rect in self.collect():
            if kind != 'ButtonControl' or rect.width() <= 0:
                continue
            text = (name or '').strip()
            if _BOARD_NAME_RE.match(text) and text not in found:
                found.append(text)
        return found

    def _pick_board(self, label: str) -> bool:
        """Switch the leaderboard's list to *label*, opening the switcher only if needed."""
        option = self._board_option(label)
        if option is None:
            toggle = self._board_toggle()
            if toggle is None or not self._click(toggle):
                return False
            time.sleep(1.5)
            option = self._board_option(label)
        if option is None:
            return False
        clicked = self._click(option)
        time.sleep(3.5)
        return clicked

    def _board_option(self, label: str):
        """The on-screen button named exactly *label*, or ``None``."""
        for ctrl, kind, name, rect in self.collect():
            if kind == 'ButtonControl' and (name or '').strip() == label and rect.width() > 0:
                return ctrl
        return None

    def _play_for_title(self, title: str):
        """The card of *title*: its ``▶ 播放`` button, else the title control itself.

        An EXACT card wins over a prefix one, asked in a first pass over the whole tree.
        斗罗大陆 and 斗罗大陆 第二季 are two dramas, and the prefix rule alone lets the shorter
        card answer the longer request; the 错剧 guard cannot catch that on a name-fed walk,
        because the reference ``book_id`` is read from the WRONG drama's own first page and
        every later page then agrees with the mistake — and the 剧名 column would stamp the
        requested name onto another drama's rows.
        """
        items = self.collect()
        for exact_only in (True, False):
            hit = self._card_for(items, title, exact_only)
            if hit is not None:
                return hit
        return None

    def _card_for(self, items, title: str, exact_only: bool):
        """One pass for *title* over a collected tree; *exact_only* demands the whole name."""
        want = _norm_title(title)
        for i, (ctrl, kind, name, rect) in enumerate(items):
            if rect.width() <= 0 or not name:
                continue
            if exact_only:
                if _norm_title(name) != want:
                    continue
            elif not _same_drama(want, name):
                continue
            if kind == 'ButtonControl' and '播放' in name:
                return ctrl
            for _c2, kind2, name2, rect2 in items[i + 1 :]:
                if kind2 == 'ButtonControl' and '播放' in (name2 or '') and rect2.width() > 0:
                    return _c2
            return ctrl
        return None

    def next_episode(self) -> bool:
        """Advance the player to the next episode (the feed answers ↑/↓, measured)."""
        try:
            auto = self._ensure_library()
            win = self.window()
            if win is None:
                return False
            with contextlib.suppress(Exception):
                win.SetFocus()
            auto.SendKeys('{Down}')
            time.sleep(1.5)
            return True
        except Exception as exc:
            logger.debug('hongguo harvest: next_episode failed: %s', exc)
            return False

    def scroll_drawer(self, attempt: int = 0) -> bool:
        """One scroll step inside the open drawer, escalating with the attempt number.

        Measured 2026-10-19: after a composer had taken the keyboard the wheel alone
        stopped paging, and the walk read that silence as the end of an 800-comment
        thread. So a stalled page is asked again, louder: attempt 1 clears the focus
        first, attempt 2+ sends the page key the app's own list honours.
        """
        try:
            auto = self._ensure_library()
            if attempt:
                self.dismiss_composer()
            if attempt >= 2:
                auto.SendKeys('{PageDown}{PageDown}')
            else:
                auto.WheelDown(wheelTimes=5 if attempt else 2, interval=0.15)
            time.sleep(1.2)
            return True
        except Exception as exc:
            logger.debug('hongguo harvest: scroll_drawer failed: %s', exc)
            return False

    def dismiss_composer(self) -> None:
        """Press ESC so a reply box that grabbed the keyboard gives it back to the drawer."""
        try:
            self._ensure_library().SendKeys('{Esc}')
            time.sleep(0.4)
        except Exception as exc:
            logger.debug('hongguo harvest: composer dismiss failed: %s', exc)

    def open_comments(self) -> bool:
        """Click the action rail's ``💬 <count>`` button — the measured comment door.

        The feed's background comment prefetch died with a protocol update on
        2026-10-19 (byte-identical player builds, morning yes / afternoon no), and
        the drawer is the trigger that still answers: its button name carries the
        site's OWN comment count (``💬 410``), and opening it fires comment/list.
        The sidebar's ``💬 反馈`` is told apart by the numeric tail.
        """
        try:
            win = self.window()
            if win is None:
                return False
            for ctrl, kind, name, rect in self.collect():
                if kind == 'ButtonControl' and rect.width() > 0 and _RAIL_COMMENT_RE.match(name or ''):
                    return self._click(ctrl)
            return False
        except Exception as exc:
            logger.debug('hongguo harvest: open_comments failed: %s', exc)
            return False

    def expand_replies(self, max_clicks: int = 40) -> int:
        """Expand EVERY 「展开…回复」 the drawer currently shows; returns how many it clicked.

        One click per episode was reply-blind by design: a drawer with 30 threads and
        children under six of them yielded six expansions, and the table then claimed the
        conversation had no replies. So the walk re-reads the tree and clicks the first
        not-yet-clicked expansion until the page offers none (bounded — a control that
        refuses to disappear must not spin here forever), then hands the keyboard back:
        whatever the click opened, the scroll that follows must own the focus.
        """
        clicked = 0
        seen: set[tuple] = set()
        while clicked < max_clicks:
            target = None
            for ctrl, kind, name, rect in self.collect():
                if rect.width() <= 0 or not is_expand_control(name):
                    continue
                key = (kind, str(name).strip(), rect.left, rect.top)
                if key in seen:
                    continue
                target = ctrl
                seen.add(key)
                break
            if target is None:
                break
            if not self._click(target):
                break
            clicked += 1
            time.sleep(1.0)
        self.dismiss_composer()
        if clicked:
            self._log(t('crawl.hg.cmt.repliesExpanded', n=clicked))
        return clicked


class HongguoCommentHarness:
    """The browserless comment adapter the engine dispatches as ``crawl_hongguo``.

    Duck-types the two roles ``_execute_comment_node`` caches per platform: the
    *session* (``crawl_hongguo(url, limit) -> (rows, status)``) and the *crawler*
    (``close()``, and the wall attributes the blocked verdict reads — this stack
    has no cookie of ours to die, so both stay False forever).
    """

    #: No Selenium anywhere: the stop-reaper's ``driver`` read must not crash.
    driver = None
    risk_blocked = False
    login_wall = False

    def __init__(self, params=None, log=None, abort=None, ui=None, capture_path=None):
        self.params = dict(params or {})
        self._log = log or (lambda _m: None)
        self._abort = abort or (lambda: False)
        self.ui = ui or PlayerUI(self._log, self._abort)
        self._capture = capture_path or os.path.join(
            Config.HARVEST_DIR, f'capture-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}.jsonl'
        )
        self._offset = 0
        self._pending = []
        self._reply_inbox = []
        self._proxy = None
        self._player = None
        self._stack_up = False
        # U1 facts the engine reads after the walk, by ATTRIBUTE (never platform name).
        self.end_reason = None
        self.target_total = 0
        #: Rows the SITE counted for a thread this walk did not keep (see ``_finish``).
        self.shortfall = 0
        self._was_short = False
        self.walk_counts = {}
        #: Every drama the client would not open, in the order it refused them. The engine
        #: names them at the end of the node: a feed of ten dramas that harvested six is a
        #: partial table, and 「1 个失败」 without the six names is not an explanation.
        self.skipped_targets: list[str] = []
        self._group_progress = {}
        self._groups_done = set()
        #: One entry per CHILD thread a click expanded, keyed by its parent 评论ID. A
        #: ``reply/list`` page prints its OWN ``total``, and a thread that reported 200
        #: children and answered 20 is a hole no comment group can see — so the reply pages
        #: are counted in the same arithmetic that licenses 「site_end」.
        self._reply_progress: dict[str, dict] = {}
        #: Threads the 评论上限 cut off on purpose. They are kept short by the user's own
        #: request, so they are excluded from the gap rather than convicting a node that did
        #: exactly what the box asked for.
        self._capped_groups: set[str] = set()
        self._capped_reply_keys: set[str] = set()
        #: The reply threads the CURRENT drama expanded (reset per target, like ``_drama_groups``).
        self._drama_reply_keys: set[str] = set()
        #: Threads this drama already named short, so the same gap is not printed twice.
        self._named_groups: set[str] = set()
        #: ``group_id`` → the 1-based episode position the walk was standing on when that
        #: thread first answered. A payload never says which episode it is, and 集序号 is
        #: the column a reader (and any per-episode analysis) needs to group by.
        self._ep_of_group: dict[str, int] = {}
        #: 评论ID of every reply row already taken from the inbox (see `_harvest_replies`).
        self._reply_ids: set[str] = set()
        #: The drama the walk is standing in, as the payload can be asked to confirm it:
        #: the link's ``series_id`` when there was one, else the first book its pages named.
        self._current_series = ''
        self._current_book = ''
        #: The threads the CURRENT drama opened (reset per link; see `crawl_hongguo`).
        self._drama_groups: set[str] = set()
        self._floors_by_cid = {}
        self._next_floor = 1
        self._titles = {}

    # ─── the adapter contract ───

    def crawl_hongguo(self, url, limit):
        """One drama — a web detail link, a bare ``series_id`` or a plain 剧名 — walked episode by episode.

        ``limit`` is the node's 评论上限 across this drama (0 = every comment).
        ``(rows, DEAD)`` answers a target this machine cannot serve (no id, no name, no
        such drama, no traffic at all); a missing player/proxy/cert RAISES by name —
        nobody's empty table may hide an unprepared machine. A target the CLIENT will not
        open is skipped by name and counted in ``skipped_targets`` instead of failing the
        node: the web 热榜 and the player's 排行榜 are two different ranking families
        (measured 2026-10-19), so one drama the client does not list must not cost the
        other nine their comments — and the node still refuses by name at the end.
        """
        target = str(url or '').strip()
        if not target:
            return [], DEAD
        if '://' in target or hg_series_id(target):
            series_id = hg_series_id(target)
            # A bare ``series_id`` is promoted to the link the site itself prints. Asking the
            # page for 「7696063528179878937」 as a URL answers with no title, which used to
            # refuse the one input this docstring advertised as supported.
            article_url = target if '://' in target else f'{_DETAIL_BASE}?series_id={series_id}'
            title = self._title_for(article_url) if series_id else ''
            if not series_id or not title:
                # Skipped AND counted. A bare ``([], DEAD)`` fed neither tail gate, so a node
                # whose target could not even be named settled DONE beside the hole.
                self._mark_short()
                self.skipped_targets.append(target)
                self._log(t('crawl.hg.cmt.titleMissing', url=target))
                return [], DEAD
        else:
            # A 剧名 read from an upstream column (the board's 作品名): the player is then the
            # ONLY authority on which drama this is, which is exactly why the name-fed walk
            # exists — matching a web board row to a client card by hand was how dramas got
            # searched for in lists that never carried them. No web page was opened, so
            # ``文章URL`` stays blank; the name lives in ``剧名``.
            series_id = ''
            title = target
            article_url = ''
        self._current_series = series_id
        self._current_book = ''
        #: The ``group_id``s this one drama opened, so its end-of-walk check reads its own
        #: threads (the harness is reused across a node's links).
        self._drama_groups = set()
        self._drama_reply_keys = set()
        self._named_groups = set()
        self._ensure_stack()
        opened = self._open_drama(title)
        if opened != 'ok':
            # Skipped, counted, and the node moves to the next drama. `_mark_short` keeps the
            # ledger honest: the walk as a whole did NOT reach what the site counted, so the
            # engine's own gate will refuse the node by name at the end rather than let a
            # nine-drama table settle DONE next to a ten-drama request.
            self._mark_short()
            self.skipped_targets.append(title)
            self._log(t('crawl.hg.cmt.dramaSkipped' if opened == 'cold' else 'crawl.hg.cmt.dramaNotFound', title=title))
            return [], DEAD
        episodes = int(self.params.get('episode_count') or 10)
        wait_s = int(self.params.get('harvest_timeout') or 90)
        # Read, never compared: the panel stores this switch as a real boolean, but a hand
        # written or fed canvas can hold the TEXT 'false', which ``bool()`` reads as on — and
        # 「包含子回复」 off would then still click every thread open.
        with_replies = as_bool(self.params.get('include_replies'), True)
        self._log(
            t(
                'crawl.hg.cmt.start',
                title=title,
                episodes=episodes,
                replies=t('crawl.hg.cmt.on' if with_replies else 'crawl.hg.cmt.off'),
            )
        )
        rows = []
        scanned = refused = 0
        licensed = True
        group_of_prog = ''
        for ep in range(1, episodes + 1):
            self._check_abort()
            # The drawer is the trigger (the feed's silent prefetch died with the
            # protocol update); its click also proves the episode is on screen.
            self.ui.open_comments()
            record = self._await_page(series_id, wait_s, stamp=(article_url, title, ep))
            if record is None:
                licensed = False
                self._log(t('crawl.hg.cmt.noTraffic', seconds=wait_s, title=title))
                if not rows:
                    # Counted, not just logged: an uncountable ``([], DEAD)`` let a five-drama
                    # feed whose third drama a popup blocked settle 「正常」 over four, and one
                    # drama fed with no traffic at all settle DONE on an EMPTY table.
                    self._mark_short()
                    self.skipped_targets.append(title)
                    return [], DEAD
                break
            page_rows, page_refused, prog, has_more = self._harvest(record, article_url, title, ep)
            group_of_prog = str(record.get('group_id') or '')
            scanned += _entry_count(record)
            refused += page_refused
            rows.extend(page_rows)
            self._log(t('crawl.hg.cmt.episode', n=ep, total=episodes, have=len(page_rows), site_total=prog['total']))
            # The drawer's own ``total`` is the denominator, not ``has_more``:
            # measured 2026-10-19, page 1 of an 800-comment thread answers
            # ``has_more: false`` (the cursor window is done — the thread is not).
            # So the walk keeps scrolling while the site still counts more rows
            # than this group has; a lost scroll leaves UNDER_TARGET, never a
            # claimed 'site_end'.
            stalled = 0
            while (has_more or prog['kept'] < prog['total']) and not (limit and len(rows) >= limit):
                self._check_abort()
                if not self.ui.scroll_drawer(stalled):
                    licensed = False
                    break
                more = self._await_page(
                    series_id, self._page_wait(wait_s, stalled), allow_repeat=True, stamp=(article_url, title, ep)
                )
                if more is None:
                    # Silence is not the end of the thread: it is a scroll the page did not
                    # honour (a composer had the focus, the pointer was off the drawer). Ask
                    # again, louder, before any of it is read as "no more comments".
                    stalled += 1
                    if stalled >= _MAX_STALLS:
                        licensed = False
                        self._named_groups.add(group_of_prog)
                        self._log(
                            t(
                                'crawl.hg.cmt.episodeShort',
                                title=title,
                                ep=ep,
                                have=prog['kept'],
                                site_total=prog['total'],
                            )
                        )
                        break
                    continue
                stalled = 0
                extra, extra_refused, prog, has_more = self._harvest(more, article_url, title, ep)
                group_of_prog = str(more.get('group_id') or '')
                scanned += _entry_count(more)
                refused += extra_refused
                rows.extend(extra)
            if with_replies:
                # Expand every thread the drawer offers (one click left the table reply-blind
                # and a 30-thread drawer answered six), then drain everything the player
                # fetched — from these clicks, its own prefetch, or a human scrolling.
                self.ui.expand_replies()
                time.sleep(1.5)
                reply_rows, reply_refused = self._harvest_replies(article_url, title, ep)
                scanned += len(reply_rows) + reply_refused
                refused += reply_refused
                rows.extend(reply_rows)
            if limit and len(rows) >= limit:
                self._finish('capped', rows, scanned, refused)
                return rows[:limit], OK
            if ep < episodes and not self.ui.next_episode():
                licensed = False
                break
        if with_replies:
            # One last look before the door closes. Expanding fires up to forty requests and the
            # per-episode grace is short, so a child page can still be in flight after the last
            # episode: drained NOW it belongs to this drama, left in the inbox it would be read
            # at the NEXT drama's episode end and stamped with a 剧名 that never carried it.
            time.sleep(_REPLY_SETTLE_SECONDS)
            late, late_refused = self._harvest_replies(article_url, title, episodes)
            scanned += len(late) + late_refused
            refused += late_refused
            rows.extend(late)
        # 'site_end' demands the arithmetic, not just a quiet loop: every group's kept count
        # must have reached the total the site printed for it, and a group that fell short is
        # named so the user knows which episode is thin rather than hunting a total. Asked of
        # THIS drama's groups only — the harness is cached per platform and one node walks
        # several dramas, and a previous drama's already-named shortfall must not be printed
        # again as if it were this one's.
        for group in self._drama_groups:
            if group in self._named_groups:
                # The stall that ended this thread already said it, with the episode name;
                # printing the same gap twice is the double line this repo bans.
                continue
            prog = self._group_progress.get(group) or {}
            if prog.get('total') and prog['kept'] < prog['total']:
                licensed = False
                self._log(
                    t(
                        'crawl.hg.cmt.groupShort',
                        group=group,
                        ep=self._ep_of_group.get(group, 0) or '?',
                        have=prog['kept'],
                        site_total=prog['total'],
                    )
                )
        # An expanded child thread is graded too: its page printed a total, and a walk that
        # clicked 展开 N 条回复 and collected fewer than N has a hole no comment group can show.
        for key in self._drama_reply_keys:
            prog = self._reply_progress.get(key) or {}
            if prog.get('total') and prog['kept'] < prog['total']:
                licensed = False
                self._log(
                    t(
                        'crawl.hg.cmt.replyShort',
                        floor=prog.get('floor') or '?',
                        have=prog['kept'],
                        site_total=prog['total'],
                    )
                )
        whole = all(kept >= total for total, kept in self._outstanding())
        self._finish('site_end' if (licensed and whole) else UNDER_TARGET, rows, scanned, refused)
        self._log(t('crawl.hg.cmt.finished', n=len(rows), episodes=episodes))
        return rows, OK

    def _open_drama(self, title) -> str:
        """Open *title*, re-waking the tree when it went cold mid-walk: 'ok' / 'notfound' / 'cold'.

        Two facts the first live multi-drama run taught (2026-10-19): the chain of UIA reads
        sometimes needs a second pass, and a WebView2 tree that was warm for drama 1 can be
        cold again by drama 2 — where the old code let that flake FAIL the whole node and nine
        un-harvested dramas rode downstream as one exception. So the cold answer is woken and
        asked again; only a page that stays cold steps aside by name.
        """
        cold = False
        for _attempt in range(2):
            self._check_abort()
            try:
                if self.ui.open_drama(title):
                    return 'ok'
                # The page ANSWERED this time and still had no card: that is a miss, whatever
                # the earlier attempt did.
                cold = False
            except TreeColdError:
                cold = True
                if self.ui.wait_content(seconds=_COLD_REWAKE_SECONDS) is None:
                    return 'cold'
        # A tree that stayed cold through every attempt is named cold: 「搜不到这部剧」 would
        # blame the library for a renderer that never woke, and the user would go looking for a
        # drama that was never the problem.
        return 'cold' if cold else 'notfound'

    @staticmethod
    def _page_wait(wait_s: int, stalled: int) -> int:
        """How long one page may take, growing with the stall count it is answering."""
        return min(60, max(15, wait_s // 2) + 10 * stalled)

    # ─── the captured pages ───

    def _harvest(self, record, url, title='', episode=0):
        """Parse one ``comment/list`` page into the run's rows.

        Pages of one group merge by 评论ID: the feed's prefetch page and the
        drawer's page of the SAME episode both arrive, and a comment counted
        twice is a table that lies about its own size. ``total`` is the group's
        running site-attested denominator; floors continue across everything.
        """
        payload = record.get('payload') or {}
        rows, dropped, total, has_more = hg_comment_rows(
            payload, url, first_floor=self._next_floor, drama_title=title, episode_index=episode
        )
        group = str(record.get('group_id') or '')
        if group and episode:
            # First page of a thread fixes its episode position for the whole run — reply
            # pages carry a group id and no episode number of their own, and 集序号 has to
            # agree between a comment and its children or the grouping is fiction.
            self._ep_of_group.setdefault(group, episode)
            self._drama_groups.add(group)
        prog = self._group_progress.setdefault(
            group or f'anon-{len(self._group_progress)}', {'kept': 0, 'total': 0, 'ids': set()}
        )
        fresh = [r for r in rows if str(r['评论ID']) not in prog['ids']]
        prog['ids'].update(str(r['评论ID']) for r in fresh)
        prog['kept'] += len(fresh)
        if total:
            prog['total'] = max(prog['total'], total)
        for row in fresh:
            self._floors_by_cid[str(row['评论ID'])] = row['楼层']
        self._next_floor += len(fresh)
        if group:
            self._groups_done.add(group)
        if dropped:
            self._log(t('crawl.hg.cmt.danmakuSkipped', n=dropped))
        return fresh, dropped, prog, has_more

    def _harvest_replies(self, url, title='', episode=0):
        """Fold in every ``reply/list`` page that landed since the last look.

        Reply pages are deduped by 评论ID across the WHOLE drama, not merely within one
        page: the walk now expands every thread it can see, and it re-expands on the next
        episode's pass, so the same child list arrives again and again. Doubles would not
        survive the run's own ledger, but they would inflate 楼层 and this node's table on
        the way there.

        Every row is stamped with the drama the PAGE arrived under (``_stamp``, set by
        :meth:`_await_page`), not with the target the walk happens to be standing on when the
        inbox is next drained: a child page that landed late would otherwise be filed under a
        剧名 and 文章URL that never carried it, which is a corrupted table rather than a
        smaller one.

        The page's own ``total`` goes into ``_reply_progress``, keyed by its parent comment:
        a thread the site counts at 200 children and the walk brought home 20 is a gap the
        comment groups cannot express, and ``site_end`` may not be claimed beside it.
        """
        rows = []
        refused = 0
        inbox, self._reply_inbox = self._reply_inbox, []
        for record in inbox:
            payload = record.get('payload') or {}
            parent = self._reply_parent_cid(record.get('req_body') or '')
            floor = self._floors_by_cid.get(parent, 0)
            page_url, page_title, page_ep = record.get('_stamp') or (url, title, episode)
            group = str(record.get('group_id') or '')
            page_rows, dropped, total, _more = hg_comment_rows(
                payload,
                page_url,
                first_floor=self._next_floor,
                parent_floor=floor,
                drama_title=page_title,
                episode_index=self._ep_of_group.get(group) or page_ep,
            )
            fresh = [r for r in page_rows if str(r['评论ID']) not in self._reply_ids]
            self._reply_ids.update(str(r['评论ID']) for r in fresh)
            self._next_floor += len(fresh)
            key = parent or group or f'anon-reply-{len(self._reply_progress)}'
            rprog = self._reply_progress.setdefault(key, {'kept': 0, 'total': 0, 'floor': floor})
            rprog['kept'] += len(fresh)
            if total:
                rprog['total'] = max(rprog['total'], total)
            self._drama_reply_keys.add(key)
            if fresh:
                self._log(t('crawl.hg.cmt.replyPage', floor=floor or '?', n=len(fresh)))
            rows.extend(fresh)
            refused += dropped
        return rows, refused

    @staticmethod
    def _reply_parent_cid(req_body):
        try:
            body = json.loads(req_body or '{}')
        except (TypeError, ValueError):
            return ''
        holders = [body]
        if isinstance(body.get('business_param'), dict):
            holders.append(body['business_param'])
        for key in ('comment_id', 'reply_to_comment_id'):
            for holder in holders:
                if holder.get(key):
                    return str(holder[key])
        return ''

    def _await_page(self, series_id, seconds, allow_repeat=False, stamp=None):
        """Block until a fresh ``comment/list`` for *series_id* lands in the capture.

        Fresh = a group this walk has not harvested (``allow_repeat`` additionally
        admits a NEWER page of the same group — the drawer's cursor pages). Every
        read batch is BUFFERED first: the record that answers may sit behind a
        reply page or a later episode's page, and an early return must not throw
        those away (the tail offset already passed them). Reply pages go to the
        inbox; a page whose payload names another drama is refused by name — 错剧
        rows in the table are worse than a missing episode.

        *stamp* is the ``(文章URL, 剧名, 集序号)`` of the target whose drawer asked for
        the page, carried onto every reply record the inbox takes on. The walk drains
        the inbox whenever it next looks, which can already be the following drama.

        The 错剧 guard has two shapes because the walk has two inputs. A LINK names its
        ``series_id``, so every page must answer to it. A fed 剧名 names nothing the payload
        can be checked against, so the first NON-zero ``book_id`` of this drama becomes its
        reference and any later page belonging to another book is refused — a name-fed walk
        still cannot mix two dramas into one table.
        """
        deadline = time.time() + max(5, int(seconds))
        while time.time() < deadline:
            self._check_abort()
            self._pending.extend(self._read_records())
            keep, hit = [], None
            for record in self._pending:
                kind = record.get('kind')
                if kind == 'reply':
                    if stamp is not None:
                        record['_stamp'] = stamp
                    self._reply_inbox.append(record)
                    continue
                if kind != 'comment':
                    continue
                group = str(record.get('group_id') or '')
                if not group:
                    continue
                if group in self._groups_done and not allow_repeat:
                    continue
                book = self._payload_book_id(record)
                want = series_id or self._current_book
                if book:
                    if want and book != want:
                        self._log(t('crawl.hg.cmt.groupMismatch', got=book, want=want))
                        continue
                    self._current_book = book
                if hit is None:
                    hit = record
                else:
                    keep.append(record)
            self._pending = keep
            if hit is not None:
                return hit
            time.sleep(0.5)
        return None

    @staticmethod
    def _payload_book_id(record):
        # A real comment row may carry ``expand.book_id == "0"`` (measured in the
        # morning capture: the drawer's comments of a feed video print 0), so 0 is
        # "the payload does not name the drama" — not a mismatch. The guard fires
        # only on a NON-zero book that differs from the asked one.
        for item in ((record.get('payload') or {}).get('data') or {}).get('data_list') or []:
            book = str(((item or {}).get('comment') or {}).get('expand', {}).get('book_id') or '')
            if book and book != '0':
                return book
        return ''

    def _read_records(self):
        """Complete JSONL lines appended since the last read (the unit-test seam:
        a test writes the file and this returns them, no process involved)."""
        try:
            with open(self._capture, encoding='utf-8') as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except OSError:
            return []
        records = []
        for line in chunk.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    # ─── the stack ───

    def _ensure_stack(self):
        """mitmdump → CA trust → player, each refused by name. Idempotent per node run."""
        if self._stack_up:
            return
        if Config.CLOUD_MODE or sys.platform != 'win32':
            raise ValueError(t('crawl.hg.cmt.needsExtras', missing='Windows desktop (mitmdump + UIA)'))
        missing = [name for name in ('mitmproxy', 'uiautomation') if importlib.util.find_spec(name) is None]
        if missing:
            raise ValueError(t('crawl.hg.cmt.needsExtras', missing=' / '.join(missing)))
        mitmdump = find_mitmdump()
        if not mitmdump:
            raise ValueError(t('crawl.hg.cmt.noMitmdump', detail='settings mitmdump_path / PATH / venv Scripts'))
        player = find_player()
        if not player:
            raise ValueError(t('crawl.hg.cmt.noPlayer', path=str(get_setting('hongguo_player_path') or '')))
        if ctypes.windll.user32.FindWindowW(_PLAYER_CLASS, None):
            # A player the USER launched carries no proxy env; it can never feed this
            # harvest, and killing a window the user opened is not this tool's right.
            raise ValueError(t('crawl.hg.cmt.playerBusy'))
        port = _int_setting('harvest_proxy_port', 8860)
        self._start_proxy(mitmdump, port)
        try:
            self._ensure_trusted()
            self._start_player(player, port)
        except ValueError:
            self.close()
            raise
        self._stack_up = True

    def _start_proxy(self, mitmdump, port):
        os.makedirs(Config.HARVEST_DIR, exist_ok=True)
        with open(self._capture, 'a', encoding='utf-8'):
            pass
        env = dict(os.environ, CIXI_HG_OUT=self._capture)
        # No confdir override: mitmproxy's OWN default (~/.mitmproxy) is the right
        # home for the CA. A per-run throwaway confdir would mint a fresh CA every
        # harvest and ask the trust store again and again; the CA is a machine fact,
        # like the browser binary, and only the capture file is scratch (below).
        self._proxy = subprocess.Popen(
            [
                mitmdump,
                '-s',
                _ADDON,
                '--listen-host',
                '127.0.0.1',
                '--listen-port',
                str(port),
                '-q',
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            cert_landed = os.path.exists(self._cert_path())
            if cert_landed and self._port_open(port):
                return
            if self._proxy.poll() is not None:
                break
            time.sleep(0.3)
        self.close()
        raise ValueError(t('crawl.hg.cmt.noMitmdump', detail=f'proxy did not come up on 127.0.0.1:{port}'))

    @staticmethod
    def _cert_path() -> str:
        return os.path.join(os.path.expanduser('~'), '.mitmproxy', 'mitmproxy-ca-cert.cer')

    @staticmethod
    def _port_open(port) -> bool:
        with socket.socket() as probe:
            probe.settimeout(0.4)
            return probe.connect_ex(('127.0.0.1', int(port))) == 0

    def _ensure_trusted(self):
        """The mitm CA must sit in the CURRENT USER's root store (measured: the
        player's Go client accepts it there). Auto-install is a setting; without
        it (or when the install fails) the refusal prints the exact command
        instead of touching the trust store by surprise.

        The store is spoken to through crypt32 directly, not through PowerShell
        or certutil: both UI routes were measured to HANG on 2026-10-19 (the first
        ``Import-Certificate`` blocked 60 s with no window anywhere, and every
        later import queued behind its corpse; ``certutil -addstore -user`` is the
        confirmation-DIALOG route). The API is silent, instant, and compares the
        certificate by SHA-1 thumbprint — subject matching would let an OLD mitm CA
        (same ``CN=mitmproxy``, different key) pass the probe while the player's TLS
        then fails against the fresh one.
        """
        cer = self._cert_path()
        der = _read_der(cer)
        if der is None:
            raise ValueError(t('crawl.hg.cmt.caNotTrusted', command=_manual_command(cer)))
        if _cert_trusted(der):
            return
        command = _manual_command(cer)
        if not _bool_setting('harvest_auto_install_ca', True):
            raise ValueError(t('crawl.hg.cmt.caNotTrusted', command=command))
        _cert_install(der)
        if not _cert_trusted(der):
            raise ValueError(t('crawl.hg.cmt.caNotTrusted', command=command))
        self._log(t('crawl.hg.cmt.caInstalled'))

    def _start_player(self, player, port):
        proxy = f'http://127.0.0.1:{port}'
        env = dict(os.environ, HTTP_PROXY=proxy, HTTPS_PROXY=proxy, NO_PROXY='localhost,127.0.0.1')
        self._player = subprocess.Popen(
            [player],
            cwd=os.path.dirname(player),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ─── the walk's bookkeeping ───

    def _title_for(self, url):
        """The drama name from the web detail page's own ``<title>`` (cached per URL)."""
        if url in self._titles:
            return self._titles[url]
        title = ''
        try:
            reply = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            title = hg_page_title(reply.text)
        except Exception as exc:
            logger.debug('hongguo harvest: title fetch failed: %s', exc)
        self._titles[url] = title
        return title

    def _check_abort(self):
        if self._abort():
            raise CrawlerStopped(t('crawl.stopped'))

    def _mark_short(self):
        """Record that this walk did NOT reach what the site counted, without a row table.

        A skipped drama has no funnel to report and no denominator to add, but it does change
        the one answer the engine reads by attribute — ``end_reason``. Going through
        :meth:`_finish` with an empty table would overwrite the cumulative funnel of the
        dramas that DID harvest with zeros, so the short flag is raised here directly.
        """
        self._was_short = True
        self.end_reason = UNDER_TARGET

    def _outstanding(self):
        """Every ``(site-counted, kept)`` pair the walk still owes.

        Both ledgers are asked, because a comment thread and an expanded child thread print
        the same kind of ``total`` and only the first was ever graded: a drama whose every
        episode came home full could still be holding 20 of a 200-child thread. Threads the
        评论上限 cut off on purpose are excluded — the user asked for that shortfall.
        """
        for group, prog in self._group_progress.items():
            if prog['total'] and group not in self._capped_groups:
                yield prog['total'], prog['kept']
        for key, prog in self._reply_progress.items():
            if prog['total'] and key not in self._capped_reply_keys:
                yield prog['total'], prog['kept']

    def _finish(self, reason, rows, scanned, refused):
        """Same three-state contract as the source crawl's ``note_end``.

        ``shortfall`` is part of that contract and the reason it is its own number: the
        engine's gate compares ROWS against the site's total, and reply rows are not in any
        episode's printed ``total`` — so a node that lost 300 comments under one episode and
        harvested 400 children elsewhere would otherwise read as "the row count reached the
        total" and settle DONE.

        Cumulative across the links of one node run (the engine caches this harness per
        platform and calls it once per drama): once a walk was cut short by anything but the
        site's own end, the node is short, whoever later says ``site_end`` about their own
        episode notwithstanding.
        """
        if reason != UNDER_TARGET and reason not in ('site_end', 'capped', 'empty'):
            raise ValueError(f'hongguo harvest: {reason!r} is not a licensed end')
        if reason == UNDER_TARGET:
            self._was_short = True
        if reason == 'capped':
            # Reached by request, not by a lost scroll: file this drama's threads as owed
            # nothing, or the next drama's arithmetic convicts the whole node.
            self._capped_groups |= set(self._drama_groups)
            self._capped_reply_keys |= set(self._drama_reply_keys)
        self.end_reason = UNDER_TARGET if self._was_short else reason
        self.target_total = sum(p['total'] for p in self._group_progress.values()) + sum(
            p['total'] for p in self._reply_progress.values()
        )
        self.shortfall = sum(max(0, total - kept) for total, kept in self._outstanding())
        # The funnel is handed over only when every leg was measured; the engine
        # omits it otherwise rather than printing fake zeros.
        self.walk_counts = {'scanned': scanned, 'kept': len(rows), 'refused': refused}

    # ─── the crawler role ───

    def close(self):
        """Kill what THIS harness started, tree included, once. The user's own
        player was refused long before this point and is never touched."""
        for attr in ('_player', '_proxy'):
            handle = getattr(self, attr)
            setattr(self, attr, None)
            if handle is None:
                continue
            try:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(handle.pid)],
                    capture_output=True,
                    timeout=8,
                    check=False,
                )
            except Exception as exc:
                logger.debug('hongguo harvest: reaping %s failed: %s', getattr(handle, 'pid', '?'), exc)
        try:
            if self._capture and os.path.exists(self._capture):
                os.remove(self._capture)
        except OSError:
            pass
        self._stack_up = False


def _entry_count(record) -> int:
    data = (record.get('payload') or {}).get('data') or {}
    return len(data.get('data_list') or [])


def _int_setting(key, default) -> int:
    try:
        return int(str(get_setting(key) or default))
    except (TypeError, ValueError):
        return default


def _bool_setting(key, default) -> bool:
    from utils.helpers import as_bool

    raw = get_setting(key)
    return default if raw is None or str(raw).strip() == '' else as_bool(raw, default)


def _read_der(cer: str) -> bytes | None:
    """The CA file's DER bytes, or ``None``.

    mitmproxy's ``.cer`` is PEM-armored (measured — ``-----BEGIN CERTIFICATE-----``),
    and crypt32's X509_ASN_ENCODING reader refuses the armor
    (``CertAddEncodedCertificateToStore`` fails on it), so the base64 body is
    unwrapped here once, at the boundary.
    """
    try:
        with open(cer, 'rb') as handle:
            raw = handle.read()
    except OSError:
        return None
    if raw.lstrip().startswith(b'-----BEGIN'):
        try:
            body = raw.split(b'-----BEGIN CERTIFICATE-----', 1)[1].split(b'-----END CERTIFICATE-----', 1)[0]
            return base64.b64decode(body)
        except (ValueError, IndexError):
            return None
    return raw


def _manual_command(cer: str) -> str:
    return f'Import-Certificate -FilePath "{cer}" -CertStoreLocation Cert:\\CurrentUser\\Root'


class _Crypt32:
    """Reading the CURRENT USER's ROOT store through crypt32 — silent, instant.

    Every restype/argtype is pinned because the default ``c_int`` would truncate a
    64-bit ``HCERTSTORE``/``PCCERT_CONTEXT`` pointer (the measured classic: it
    "works" until the handle's high half is non-zero). Writing the store lives in
    :func:`_cert_install` instead — the write hangs this machine in-process.
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes

        class _CertContext(ctypes.Structure):
            _fields_ = [
                ('dwCertEncodingType', wintypes.DWORD),
                ('pbCertEncoded', ctypes.POINTER(ctypes.c_char)),
                ('cbCertEncoded', wintypes.DWORD),
                ('pCertInfo', ctypes.c_void_p),
                ('hCertStore', ctypes.c_void_p),
            ]

        self._CERT_CONTEXT = _CertContext
        crypt32 = ctypes.windll.crypt32
        crypt32.CertOpenSystemStoreW.restype = ctypes.c_void_p
        crypt32.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        crypt32.CertCloseStore.restype = wintypes.BOOL
        crypt32.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        crypt32.CertEnumCertificatesInStore.restype = ctypes.c_void_p
        crypt32.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        crypt32.CertAddEncodedCertificateToStore.restype = wintypes.BOOL
        crypt32.CertAddEncodedCertificateToStore.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_char_p,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
        ]

    def _root(self):
        return self._ctypes.windll.crypt32.CertOpenSystemStoreW(None, 'ROOT')

    def thumbprints(self) -> set:
        """SHA-1 of the DER of every certificate in the user ROOT store.

        The DER is read off the CERT_CONTEXT itself: the ``CERT_HASH_PROP_ID``
        property is only cached for certificates the provider has already hashed
        (measured — one hit out of 79, and a probe that sees one cert calls every
        CA untrusted).
        """
        ctypes = self._ctypes
        crypt32 = ctypes.windll.crypt32
        store = self._root()
        if not store:
            return set()
        found = set()
        try:
            ctx = crypt32.CertEnumCertificatesInStore(store, None)
            while ctx:
                cc = ctypes.cast(ctx, ctypes.POINTER(self._CERT_CONTEXT)).contents
                der = ctypes.string_at(cc.pbCertEncoded, cc.cbCertEncoded)
                found.add(hashlib.sha1(der).digest())
                ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
        finally:
            crypt32.CertCloseStore(store, 0)
        return found


_crypt32 = None


#: The child-process installer: DER on stdin, exit 0 on success. Kept as source
#: bytes so the parent never executes it in-process (see :func:`_cert_install`).
_INSTALL_SNIPPET = b"""
import ctypes, sys
from ctypes import wintypes
der = sys.stdin.buffer.read()
c = ctypes.windll.crypt32
c.CertOpenSystemStoreW.restype = ctypes.c_void_p
c.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
c.CertAddEncodedCertificateToStore.restype = wintypes.BOOL
c.CertAddEncodedCertificateToStore.argtypes = [
    ctypes.c_void_p, wintypes.DWORD, ctypes.c_char_p, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]
c.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
store = c.CertOpenSystemStoreW(None, "ROOT")
if not store:
    sys.exit(2)
ok = c.CertAddEncodedCertificateToStore(store, 0x00000001, der, len(der), 2, None)
c.CertCloseStore(store, 0)
sys.exit(0 if ok else 1)
"""


def _crypt():
    global _crypt32
    if _crypt32 is None:
        _crypt32 = _Crypt32()
    return _crypt32


def _cert_trusted(der: bytes) -> bool:
    if sys.platform != 'win32':
        return False
    try:
        return hashlib.sha1(der).digest() in _crypt().thumbprints()
    except Exception as exc:
        logger.debug('hongguo harvest: trust probe failed: %s', exc)
        return False


def _cert_install(der: bytes, timeout: float = 20.0) -> bool:
    """Add the CA to the user ROOT store — in a CHILD PROCESS with a hard timeout.

    Reading the store is instant; WRITING it was measured to hang this machine
    forever (2026-10-19, both ``Import-Certificate`` and the raw crypt32 call, no
    window anywhere — an antivirus or the store provider itself blocking). An
    in-process call would therefore freeze the whole server on one harvest, and a
    daemon thread that never returns keeps the store lock for the process life.
    A child is killable: on timeout it is terminated, its handle dies with it, and
    the caller refuses by name with the manual command.
    """
    if sys.platform != 'win32':
        return False
    script = os.path.join(Config.HARVEST_DIR, 'hg_ca_install_tmp.py')
    try:
        os.makedirs(Config.HARVEST_DIR, exist_ok=True)
        with open(script, 'wb') as handle:
            handle.write(_INSTALL_SNIPPET)
            handle.write(b'\n')
        done = subprocess.run(
            [sys.executable, script],
            input=der,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        with contextlib.suppress(OSError):
            os.remove(script)
