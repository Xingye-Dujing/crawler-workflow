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

from .base import UNDER_TARGET, CrawlerStopped
from .comments_base import DEAD, OK
from .comments_hongguo import hg_comment_rows, hg_page_title, hg_series_id

logger = logging.getLogger(__name__)

_ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harvest_addon.py')
#: The window class the Wails player registers (measured; also the UIA root's ClassName).
_PLAYER_CLASS = 'wailsWindow'


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

    def __init__(self, log=None):
        self._log = log or (lambda _m: None)
        self._auto = None

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
            hit = self._find(self.window(), needle, ctype)
            if hit is not None:
                return hit
            time.sleep(0.5)
        return None

    def _find(self, win, needle, ctype=None, depth=0):
        """First control whose Name contains *needle* (bounded walk), or ``None``."""
        if win is None or depth > 14:
            return None
        try:
            children = win.GetChildren()
        except Exception:
            return None
        for child in children:
            try:
                name = child.Name or ''
                kind = child.ControlTypeName
            except Exception:
                continue
            if needle in name and (ctype is None or kind == ctype):
                return child
            hit = self._find(child, needle, ctype, depth + 1)
            if hit is not None:
                return hit
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
        """Search *title* in the player and open the first matching result."""
        if self.wait_content() is None:
            # The window exists but its DOM never became walkable (measured
            # 2026-10-19: a freshly launched WebView2 can keep a title-bar-only
            # UIA tree indefinitely; the session that saw a full tree had had a
            # human mouse inside it). This is an environment fact the user can
            # fix (touch the window once) — it must be NAMED, never a silent
            # drama-not-found.
            raise ValueError(t('crawl.hg.cmt.treeCold'))
        try:
            tab = self._find_until('找剧', 'ButtonControl', seconds=15)
            if tab is None or not self._click(tab):
                return False
            box = self._find_until('', 'EditControl', seconds=12)
            if box is None:
                return False
            self._click(box)
            box.SendKeys(title)
            time.sleep(0.8)
            box.SendKeys('{Enter}')
            card = self._find_until(title[:6], seconds=15)
            if card is None:
                return False
            opened = self._click(card)
            time.sleep(3.0)
            return opened
        except Exception as exc:
            logger.debug('hongguo harvest: open_drama failed: %s', exc)
            return False

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

    def open_drawer(self) -> bool:
        """Best effort: click the comment entry of the current video."""
        try:
            entry = self._find(self.window(), '评论')
            return bool(entry is not None and self._click(entry))
        except Exception as exc:
            logger.debug('hongguo harvest: open_drawer failed: %s', exc)
            return False

    def scroll_drawer(self) -> bool:
        """Best effort: wheel inside the open drawer (each move buys one cursor page)."""
        try:
            self._ensure_library().WheelDown(wheelIterations=2, waitTime=0.15)
            time.sleep(1.2)
            return True
        except Exception as exc:
            logger.debug('hongguo harvest: scroll_drawer failed: %s', exc)
            return False

    def expand_replies(self) -> bool:
        """Best effort: click a 回复/展开 control so reply/list fires."""
        try:
            win = self.window()
            for needle in ('回复', '展开'):
                ctrl = self._find(win, needle, 'ButtonControl') or self._find(win, needle)
                if ctrl is not None and self._click(ctrl):
                    time.sleep(1.0)
                    return True
            return False
        except Exception as exc:
            logger.debug('hongguo harvest: expand_replies failed: %s', exc)
            return False


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
        self.ui = ui or PlayerUI(self._log)
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
        self._was_short = False
        self.walk_counts = {}
        self._totals_by_group = {}
        self._groups_done = set()
        self._floors_by_cid = {}
        self._next_floor = 1
        self._titles = {}

    # ─── the adapter contract ───

    def crawl_hongguo(self, url, limit):
        """One drama link → its comment rows, walked episode by episode.

        ``limit`` is the node's 评论上限 across this drama (0 = every comment).
        ``(rows, DEAD)`` answers links this machine cannot serve (no id, no title,
        no such drama, no traffic at all); a missing player/proxy/cert RAISES by
        name — nobody's empty table may hide an unprepared machine.
        """
        series_id = hg_series_id(url)
        if not series_id:
            self._log(t('crawl.hg.cmt.titleMissing', url=url))
            return [], DEAD
        title = self._title_for(url)
        if not title:
            self._log(t('crawl.hg.cmt.titleMissing', url=url))
            return [], DEAD
        self._ensure_stack()
        if not self.ui.open_drama(title):
            self._log(t('crawl.hg.cmt.dramaNotFound', title=title))
            return [], DEAD
        episodes = int(self.params.get('episode_count') or 10)
        wait_s = int(self.params.get('harvest_timeout') or 90)
        with_replies = bool(self.params.get('include_replies', True))
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
        for ep in range(1, episodes + 1):
            self._check_abort()
            record = self._await_page(series_id, wait_s)
            if record is None:
                licensed = False
                self._log(t('crawl.hg.cmt.noTraffic', seconds=wait_s, title=title))
                if not rows:
                    return [], DEAD
                break
            page_rows, page_refused, total, has_more = self._harvest(record, url)
            scanned += _entry_count(record)
            refused += page_refused
            rows.extend(page_rows)
            self._log(t('crawl.hg.cmt.episode', n=ep, total=episodes, have=len(page_rows), site_total=total))
            # Past the first page the feed's auto-fetch stops; the drawer is the only
            # door left and it is best-effort (see PlayerUI) — a lost scroll leaves the
            # walk UNDER_TARGET by name, never a claimed 'site_end'.
            while has_more:
                self._check_abort()
                if not (self.ui.open_drawer() and self.ui.scroll_drawer()):
                    licensed = False
                    break
                more = self._await_page(series_id, min(20, wait_s), allow_repeat=True)
                if more is None:
                    licensed = False
                    break
                extra, extra_refused, _total, has_more = self._harvest(more, url)
                scanned += _entry_count(more)
                refused += extra_refused
                rows.extend(extra)
            if with_replies:
                reply_rows, reply_refused = self._harvest_replies(url)
                scanned += len(reply_rows) + reply_refused
                refused += reply_refused
                rows.extend(reply_rows)
            if limit and len(rows) >= limit:
                self._finish('capped', rows, scanned, refused)
                return rows[:limit], OK
            if ep < episodes and not self.ui.next_episode():
                licensed = False
                break
        self._finish('site_end' if licensed else UNDER_TARGET, rows, scanned, refused)
        self._log(t('crawl.hg.cmt.finished', n=len(rows), episodes=episodes))
        return rows, OK

    # ─── the captured pages ───

    def _harvest(self, record, url):
        """Parse one ``comment/list`` record; floors continue across pages/groups."""
        payload = record.get('payload') or {}
        rows, dropped, total, has_more = hg_comment_rows(payload, url, first_floor=self._next_floor)
        group = str(record.get('group_id') or '')
        for row in rows:
            self._floors_by_cid[str(row['评论ID'])] = row['楼层']
        self._next_floor += len(rows)
        if group:
            self._groups_done.add(group)
            # The envelope repeats its own total on every page of the group; count it once.
            self._totals_by_group.setdefault(group, total)
        if dropped:
            self._log(t('crawl.hg.cmt.danmakuSkipped', n=dropped))
        return rows, dropped, total, has_more

    def _harvest_replies(self, url):
        """Fold in every ``reply/list`` page that landed since the last look."""
        rows = []
        refused = 0
        inbox, self._reply_inbox = self._reply_inbox, []
        for record in inbox:
            payload = record.get('payload') or {}
            parent = self._reply_parent_cid(record.get('req_body') or '')
            floor = self._floors_by_cid.get(parent, 0)
            page_rows, dropped, _total, _more = hg_comment_rows(
                payload, url, first_floor=self._next_floor, parent_floor=floor
            )
            self._next_floor += len(page_rows)
            self._log(t('crawl.hg.cmt.replyPage', floor=floor or '?', n=len(page_rows)))
            rows.extend(page_rows)
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

    def _await_page(self, series_id, seconds, allow_repeat=False):
        """Block until a fresh ``comment/list`` for *series_id* lands in the capture.

        Fresh = a group this walk has not harvested (``allow_repeat`` additionally
        admits a NEWER page of the same group — the drawer's cursor pages). Every
        read batch is BUFFERED first: the record that answers may sit behind a
        reply page or a later episode's page, and an early return must not throw
        those away (the tail offset already passed them). Reply pages go to the
        inbox; a page whose payload names another drama is refused by name — 错剧
        rows in the table are worse than a missing episode.
        """
        deadline = time.time() + max(5, int(seconds))
        while time.time() < deadline:
            self._check_abort()
            self._pending.extend(self._read_records())
            keep, hit = [], None
            for record in self._pending:
                kind = record.get('kind')
                if kind == 'reply':
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
                if book and book != series_id:
                    self._log(t('crawl.hg.cmt.groupMismatch', got=book, want=series_id))
                    continue
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
        for item in ((record.get('payload') or {}).get('data') or {}).get('data_list') or []:
            book = ((item or {}).get('comment') or {}).get('expand', {}).get('book_id')
            if book:
                return str(book)
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

    def _finish(self, reason, rows, scanned, refused):
        """Same three-state contract the Crawler base enforces (``note_end``).

        Cumulative across the links of one node run (the engine caches this harness
        per platform and calls it once per drama): once a walk was cut short by
        anything but the site's own end, the node is short, whoever later says
        ``site_end`` about their own episode notwithstanding.
        """
        if reason != UNDER_TARGET and reason not in ('site_end', 'capped', 'empty'):
            raise ValueError(f'hongguo harvest: {reason!r} is not a licensed end')
        if reason == UNDER_TARGET:
            self._was_short = True
        self.end_reason = UNDER_TARGET if self._was_short else reason
        self.target_total = sum(self._totals_by_group.values())
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
