"""UI Automation over the 红果 player window — every read best-effort, every refusal named.

Split out of :mod:`crawlers.platforms.hongguo.harvest` (2026-10-27) so that file owns one thing: the
harness that pairs the mitmproxy capture with the walk. This module owns the DRIVER half — the window,
the foreground, the tree walk, the clicks — and it is one of the few places in the backend that is
Windows by nature rather than by accident: ``ctypes.windll.user32.FindWindowW`` is how the player is
found and ``uiautomation`` is how it is read. It is therefore listed in
``tests/unit/crawlers/test_platform_rules.py``'s ``WINDOWS_TABLES``, which is what keeps that exemption a fact
instead of a shrug, and the rest of the backend stays free of both.

Two measured facts shape every read here: a cold WebView2 tree holds ZERO controls (so silence is
never a confirmation), and the ``N / M`` episode counter is on the video page but ABSENT from the tree
once the comment drawer is open. The spine (named nav buttons, the 排行榜 card grid, arrow-key episode
switching) was measured against the real window 2026-10-19 and the drawer against a warm dump
2026-10-20; the per-method notes carry the rest of what each rule cost.
"""

import contextlib
import ctypes
import logging
import re
import time

from crawlers.core.faults import CrawlerStopped
from crawlers.platforms.hongguo.naming import is_expand_control, norm_title, same_drama
from i18n import t

logger = logging.getLogger(__name__)

#: The window class the Wails player registers (measured; also the UIA root's ClassName).
#: Public because the harness asks the same question of the OS before it starts a player of its own.
PLAYER_CLASS = 'wailsWindow'
#: The action-rail comment button: ``💬`` plus the site's own count (``410``, ``5.1万``)
#: — the sidebar's feedback button is ``💬 反馈`` and must not be clicked for comments.
_RAIL_COMMENT_RE = re.compile(r'^💬\s*[\d.]+\s*[万千]?\+?$')
#: What the leaderboard's switcher names its lists — 总榜/必看榜/臻果榜/AI剧 … The client
#: owns this list; the tuple below is only the fallback when its popup refuses.
_BOARD_NAME_RE = re.compile(r'^[\w一-鿿]{1,8}(?:榜|剧)$')
_FALLBACK_BOARDS = ('必看榜', '热播榜', '总榜', '推荐榜', 'AI剧')
#: How close (in px) a ``关闭`` must sit to the ``评论`` header row to be the DRAWER's own close.
#: The measured drawer dump carries a titlebar ``关闭`` (window chrome, y≈197) and a zero-width
#: window ``关闭`` alongside the drawer's (y≈321, same row as ``评论 · 3076`` at y≈326). Clicking
#: the chrome one would quit the player — so the header row is the anchor that tells them apart.
_DRAWER_CLOSE_ROW_TOLERANCE = 60


class TreeColdError(ValueError):
    """The window is there and its UIA tree is not — an environment refusal, not a miss.

    Its own type because the caller must tell "the player's page will not wake" apart from
    "this drama is not in the client's lists": the first is a machine fact the user can fix
    by touching the window, the second is a ranking fact about the site, and only the second
    one is a reason to move on to the next drama. Comparing message text for that would break
    the moment a translation changed.
    """


class PlayerUI:
    """UI Automation over the player window — every method best-effort.

    The spine (named nav buttons, the 排行榜 card grid, arrow-key episode switching) was measured
    against the real window 2026-10-19, and the comment drawer against a warm dump 2026-10-20.
    Two measured facts shape the reads: a cold WebView2 tree holds ZERO controls (so silence is
    never a confirmation), and the ``N / M`` episode counter is on the video page but ABSENT from
    the tree once the drawer is open — so the walk reads only the ``@剧名`` header off the screen
    and lets the traffic gate (which refuses another book's pages by id) stand underneath it.
    Where a read is generic and the page does not answer, the harvest degrades to what the feed
    already fetched — depth lost, never a crash and never a lie.
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
        if not ctypes.windll.user32.FindWindowW(PLAYER_CLASS, None):
            return None
        auto = self._ensure_library()
        for top in auto.GetRootControl().GetChildren():
            try:
                if (top.ClassName or '') == PLAYER_CLASS:
                    return top
            except Exception:
                continue
        return None

    def _activate(self) -> None:
        """Bring the player to the OS foreground so synthetic input actually lands.

        Measured live (2026-10-20): ``WheelDown``/``SendKeys``/coordinate clicks were silently
        ignored until the user physically clicked the window — the Wails player was not the
        foreground window, and a UIA ``SetFocus`` on the top control does NOT foreground the OS
        window the way synthetic mouse/keyboard input needs. ``BringWindowToTop`` +
        ``SetForegroundWindow`` do. Best-effort: Windows may refuse a background process's
        SetForegroundWindow (focus-stealing prevention); the guarded coordinate click then still
        foregrounds it — which is exactly why the user's manual click made it start scrolling."""
        hwnd = ctypes.windll.user32.FindWindowW(PLAYER_CLASS, None)
        if not hwnd:
            return
        with contextlib.suppress(Exception):
            ctypes.windll.user32.BringWindowToTop(hwnd)
            ctypes.windll.user32.SetForegroundWindow(hwnd)

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

    def _find(self, win, needle, ctype=None):
        """First control whose Name contains *needle* — via the warming full walk."""
        if win is None:
            return None
        for ctrl, kind, name, _rect in self.collect():
            if needle in name and (ctype is None or kind == ctype):
                return ctrl
        return None

    @staticmethod
    def _window_center(rect):
        return ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)

    def _click(self, ctrl) -> bool:
        """Click a control's centre — but ONLY inside the player window, never on the taskbar.

        Measured live (2026-10-20): a bare ``auto.Click(rect centre)`` moves the user's real
        cursor to absolute pixels, and when a control's ``BoundingRectangle`` had gone stale (the
        page navigated after the tree was read) or WebView2 clamped it to an off-window corner,
        that shot landed on whatever is at those pixels — the taskbar's bottom-right clock/tray,
        opening the user's tray and clicking their desktop. The guard below makes that impossible:
        a click is issued only when the point is proven strictly inside the window.

        I first tried UIA ``Invoke`` / ``DoDefaultAction`` as the PRIMARY (no mouse, so it can
        never miss onto another window) — the hang on 找剧 proved the buttons do not respond: the
        navigation ``Invoke`` returns without raising and the WebView2 SPA never moves, so the walk
        waits forever. The coordinate click IS the mechanism that navigates this player; the safety
        is the window-bounds guard, not the pattern. (Re-add Invoke only after it is shown to
        actually navigate a click on a future build.)"""
        try:
            win = self.window()
            if win is None:
                return False
            cx, cy = self._window_center(ctrl.BoundingRectangle)
            left, top, right, bottom = self._window_bounds(win)
            # Strictly inside, and the window itself must have real extent: a rect that fell to a
            # clamped/zero or off-window value can never drive the cursor onto the taskbar corner.
            if not (left < cx < right and top < cy < bottom):
                # A refusal is a developer fact (the click is not taken; the walk degrades and the
                # traffic gate / screen gate carry the user-facing story), so it stays on the debug
                # channel — same as every other UIA best-effort miss in this module.
                logger.debug('hongguo harvest: refused coordinate click outside the player window (%d,%d)', cx, cy)
                return False
            self._ensure_library().Click(cx, cy)
            return True
        except Exception as exc:
            logger.debug('hongguo harvest: click failed: %s', exc)
            return False

    @staticmethod
    def _window_bounds(win):
        rect = win.BoundingRectangle
        return rect.left, rect.top, rect.right, rect.bottom

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
            # Foreground the player before the first synthetic click — a fresh Wails launch does
            # not reliably take the OS foreground itself, and a click/wheel on a non-foreground
            # window is silently dropped (measured 2026-10-20: nothing moved until a manual click).
            self._activate()
            rank = self._find_until('排行榜', 'ButtonControl', seconds=20)
            if rank is None or not self._click(rank):
                return False
            time.sleep(4)
            for label in self._board_labels():
                self._check_stopped()
                # Progress the user can see: without it a drama absent from every board grinds
                # silently through all lists and reads as a frozen window (measured 2026-10-20 —
                # the user asked "why is it stuck on 新剧"). One line per board, then the walk
                # still ends in dramaSkipped/dramaNotFound which names the miss properly.
                self._log(t('crawl.hg.cmt.scanningBoard', label=label, title=title))
                self._pick_board(label)
                for _scroll in range(3):
                    self._check_stopped()
                    items = self.collect()
                    if not items:
                        # The tree was warm enough to reach the board and has since gone cold
                        # (measured: a WebView2 tree re-freezes mid-walk). Grinding the rest of
                        # every board × every scroll would only pay fixed sleeps against nothing
                        # — that was where ~110 s of dead waiting went. Bail now so the caller
                        # re-wakes and re-asks, or names the drama cold.
                        raise TreeColdError(t('crawl.hg.cmt.treeCold'))
                    hit = self._play_for_title(title, items)
                    if hit is not None:
                        self._click(hit)
                        time.sleep(3.0)
                        return True
                    # Re-activate before scrolling: the board's own re-render can drop the window
                    # from the foreground, and a wheel on a non-foreground window scrolls nothing
                    # (the 「滚动几次又不动」 the user saw — until a manual click foregrounded it).
                    self._activate()
                    self._ensure_library().WheelDown(wheelTimes=3, interval=0.12)
                    time.sleep(2.0)
            return False
        except CrawlerStopped:
            # 停止 is not a search that failed. Swallowed here it would file the drama the
            # user stopped on under 「搜不到这部剧」 and name it in the skip refusal.
            raise
        except TreeColdError:
            # A tree that froze mid-walk is an environment fact, not a search miss — it must
            # reach _open_drama's re-wake, not be flattened into the False below (「搜不到这部剧」).
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

    def _play_for_title(self, title: str, items=None):
        """The card of *title*: its ``▶ 播放`` button, else the title control itself.

        An EXACT card wins over a prefix one, asked in a first pass over the whole tree.
        斗罗大陆 and 斗罗大陆 第二季 are two dramas, and the prefix rule alone lets the shorter
        card answer the longer request; the 错剧 guard cannot catch that on a name-fed walk,
        because the reference ``book_id`` is read from the WRONG drama's own first page and
        every later page then agrees with the mistake — and the 剧名 column would stamp the
        requested name onto another drama's rows.

        *items* lets a caller that already walked the tree hand it over (open_drama re-uses
        one ``collect()`` for both the cold check and the match, instead of walking twice).
        """
        if items is None:
            items = self.collect()
        for exact_only in (True, False):
            hit = self._card_for(items, title, exact_only)
            if hit is not None:
                return hit
        return None

    def _card_for(self, items, title: str, exact_only: bool):
        """One pass for *title* over a collected tree; *exact_only* demands the whole name."""
        want = norm_title(title)
        for i, (ctrl, kind, name, rect) in enumerate(items):
            if rect.width() <= 0 or not name:
                continue
            if exact_only:
                if norm_title(name) != want:
                    continue
            elif not same_drama(want, name):
                continue
            if kind == 'ButtonControl' and '播放' in name:
                return ctrl
            for _c2, kind2, name2, rect2 in items[i + 1 :]:
                if kind2 == 'ButtonControl' and '播放' in (name2 or '') and rect2.width() > 0:
                    return _c2
            return ctrl
        return None

    def screen_drama_title(self) -> str:
        """The drama the player prints as being on stage, or '' when the tree says nothing.

        Measured twice over: the 2026-10-19 dumps, and a 2026-10-20 dump taken WHILE the
        comment drawer was open, each carry a ``TextControl`` named ``@剧名``. Whether that name
        carries the season suffix is not consistent (``@…才是真BOSS`` dropped ``第十四季`` while
        ``@捧杀儿子… 第一季`` kept it), so the caller compares with the bidirectional prefix rule
        (:func:`screen_names`), never by equality: equality here would false-refuse a correctly
        opened drama.

        The empty answer means 「the tree did not say」 — a cold tree holds NO controls at all
        (measured: 453 controls after warming, 0 before), OR the page carries more than one
        ``@``-prefixed text (a 弹幕 or a reply that opens with ``@昵称``, which tree order puts
        BEFORE the header) — and either way there is no single answer, so the caller gets silence
        and lets the traffic gate do its job rather than inventing a refusal out of a guess.

        Deliberately absent: the ``N / M`` episode counter. It is on the video page but NOT in
        the tree once the drawer is open (measured in that same dump), so a walk could not read
        its own position from it; ``第N集`` does appear there, but what it numbers was not
        established, and a gate built on a guess would refuse dramas it was harvesting correctly.
        """
        try:
            items = self.collect()
        except Exception as exc:
            # A failed walk is not a cold tree, but the best-effort answer is the same (no
            # evidence) and the caller leans on the traffic gate; this is the developer channel,
            # matching every other UIA read here that degrades rather than crashing.
            logger.debug('hongguo harvest: screen title read failed (not a cold tree): %s', exc)
            return ''
        candidates = []
        for _ctrl, kind, name, rect in items:
            if kind != 'TextControl' or rect.width() <= 0:
                continue
            text = (name or '').strip()
            if text.startswith('@') and len(text) > 2:
                candidates.append(text[1:].strip())
        # Exactly one @-prefixed text is the header. Two is a comment that happens to open with
        # a @mention, and naming the first one would report a stranger's comment as the drama.
        return candidates[0] if len(candidates) == 1 else ''

    def next_episode(self) -> bool:
        """Advance the player to the next episode (the feed answers ↑/↓, measured)."""
        try:
            auto = self._ensure_library()
            win = self.window()
            if win is None:
                return False
            # Foreground first: the {Down} only switches episodes on a window that actually has
            # input focus (measured 2026-10-20 — with the player not foreground, the key was
            # silently dropped and the walk re-read the SAME episode, exactly the 「没变化」 symptom).
            self._activate()
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
            # The wheel/page key is delivered to the foreground window; without this the drawer
            # stopped scrolling the moment focus drifted (measured — user's click resumed it).
            self._activate()
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

    def close_comments(self) -> bool:
        """Close the comment drawer by clicking its OWN 关闭, anchored to the 评论 header row.

        The episode-switch gesture (``滚轮 / ↑↓ 切换``, measured on the video page) belongs to the
        VIDEO, but a key goes to whatever has focus — and the open drawer holds it, so a ``↓``
        pressed with the drawer still up scrolls comments instead of advancing the episode. That is
        the most parsimonious reading of the drift the user saw: after the first ``↓`` every page
        belonged to the account's own feed, because the video never left episode 1. Closing the
        drawer first hands ``↓`` back to the video.

        Safety is the whole design here: the drawer's 关闭 shares the 评论 header row, while the
        WINDOW chrome has its own 关闭 (the titlebar button) that would quit the player, and a
        zero-width window 关闭. The close is chosen ONLY as the 关闭 within one header row of the
        评论 header, so the chrome button is never clicked. No 评论 header (drawer not open) → no-op.
        """
        try:
            items = self.collect()
            header_top = None
            for _ctrl, kind, name, rect in items:
                if kind == 'TextControl' and rect.width() > 0 and (name or '').strip().startswith('评论'):
                    header_top = rect.top
                    break
            if header_top is None:
                return False
            for ctrl, kind, name, rect in items:
                if (
                    kind == 'ButtonControl'
                    and rect.width() > 0
                    and (name or '').strip() == '关闭'
                    and abs(rect.top - header_top) <= _DRAWER_CLOSE_ROW_TOLERANCE
                ):
                    return self._click(ctrl)
            return False
        except Exception as exc:
            logger.debug('hongguo harvest: close_comments failed: %s', exc)
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
