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
3. drives the player through UI Automation — the driver itself is
   :mod:`crawlers.platforms.hongguo.player_ui` (window, foreground, tree walk, clicks), and the
   name rules that decide whether a card or a header is *this* drama are
   :mod:`crawlers.platforms.hongguo.naming`, because those are string rules worth testing with no
   window in existence,
4. parses what the JSONL delivers through :mod:`crawlers.platforms.hongguo.comments`.

The engine caches one harness per (node run, platform), so the stack stays up
across the drama links of one comment node and is reaped in its ``finally``.
"""

import ctypes
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
from core import machine
from core.config import Config
from core.refs import as_bool

import crawl_capabilities as capabilities
from crawlers.commenting.protocol import DEAD, OK
from crawlers.core.crawler import UNDER_TARGET
from crawlers.core.faults import CrawlerStopped
from crawlers.platforms.hongguo import trust
from crawlers.platforms.hongguo.comments import hg_comment_rows, hg_page_title, hg_series_id
from crawlers.platforms.hongguo.naming import norm_title, screen_names
from crawlers.platforms.hongguo.player_ui import PLAYER_CLASS, PlayerUI, TreeColdError
from i18n import t
from settings_store import get_setting

logger = logging.getLogger(__name__)

_ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harvest_addon.py')
#: The web detail page, rebuilt from a bare ``series_id`` so the title can be read from it
#: (``crawlers.platforms.hongguo.crawler.BASE`` is the same host; the harvest does not import that crawler).
_DETAIL_BASE = 'https://hongguoduanju.com/detail'
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
#: How many extra reads the screen gate takes when the header first names a DIFFERENT show.
#: The header prints whatever is on stage and the browse page still names the PREVIOUS drama
#: for a moment after a card click, so one foreign read is not a verdict — the walk re-asks
#: before discarding a drama the user paid to open. A match or a cold tree short-circuits this
#: (no sleeps on the healthy path), so only the rare suspicious case pays the settle.
_SCREEN_SETTLE_READS = 2
_SCREEN_SETTLE_SECONDS = 0.3


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


class HongguoCommentHarness:
    """The browserless comment adapter, dispatched as ``walk('hongguo', url, limit)``.

    Duck-types the two roles ``_execute_comment_node`` caches per platform: the
    *session* (``walk(platform, url, limit) -> (rows, status)``, the same surface
    :class:`~crawlers.commenting.session.CommentSession` offers) and the *crawler*
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
        #: The other drama's ``book_id``, set the first time a page arrives for it mid-walk:
        #: the player's feed sliding off the requested drama is what the identity gate sees.
        self._drift_book = ''
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
        #: The threads the CURRENT drama opened (reset per link; see `walk`).
        self._drama_groups: set[str] = set()
        self._floors_by_cid = {}
        self._next_floor = 1
        self._titles = {}

    # ─── the adapter contract ───

    def walk(self, platform: str, url, limit):
        """One drama — a web detail link, a bare ``series_id`` or a plain 剧名 — walked episode by episode.

        ``platform`` is the routing key the engine asked about; this harness is 红果短剧 and says so
        rather than walking somebody else's link. ``(rows, DEAD)`` answers a target this machine
        cannot serve (no id, no name, no such drama, no traffic at all); a missing player/proxy/cert
        RAISES by name — nobody's empty table may hide an unprepared machine. A target the CLIENT
        will not open is skipped by name and counted in ``skipped_targets`` instead of failing the
        node: the web 热榜 and the player's 排行榜 are two different ranking families
        (measured 2026-10-19), so one drama the client does not list must not cost the
        other nine their comments — and the node still refuses by name at the end.
        """
        if platform and platform != 'hongguo':
            raise ValueError(t('comment.noAdapter', platform=platform, url=str(url or '')))
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
                self._count_unfinished(target)
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
        self._drift_book = ''
        self._ensure_stack()
        opened = self._open_drama(title)
        if opened != 'ok':
            # Skipped, counted, and the node moves to the next drama. `_mark_short` keeps the
            # ledger honest: the walk as a whole did NOT reach what the site counted, so the
            # engine's own gate will refuse the node by name at the end rather than let a
            # nine-drama table settle DONE next to a ten-drama request.
            self._count_unfinished(title)
            self._log(t('crawl.hg.cmt.dramaSkipped' if opened == 'cold' else 'crawl.hg.cmt.dramaNotFound', title=title))
            return [], DEAD
        episodes = int(self.params.get('episode_count') or 10)
        if self._confirm_position(title) == 'drifted':
            # The card answered, but the screen is showing another drama: everything the
            # drawer would fetch next belongs to that show, and the 剧名 column would say
            # otherwise. Checked BEFORE the first page, not after the traffic disagrees.
            self._count_unfinished(title)
            return [], DEAD
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
                if self._drift_book:
                    # The player's feed slid off the requested drama (measured 2026-10-20: after
                    # the first ↓ every page for the rest of the walk belonged to the show the
                    # account had been watching, whose threads run to 2000+ comments). Those rows
                    # are refused by the identity gate rather than stamped with this name, and the
                    # drama is counted: 1 of 5 is not a finished crawl, and the site printed no
                    # total for the episodes never reached, so ``shortfall`` alone cannot say it.
                    self._log(t('crawl.hg.cmt.feedDrifted', title=title, ep=ep, book=self._drift_book))
                    self._count_unfinished(title)
                    if not rows:
                        return [], DEAD
                    break
                self._log(t('crawl.hg.cmt.noTraffic', seconds=wait_s, title=title))
                if not rows:
                    # Counted, not just logged: an uncountable ``([], DEAD)`` let a five-drama
                    # feed whose third drama a popup blocked settle 「正常」 over four, and one
                    # drama fed with no traffic at all settle DONE on an EMPTY table.
                    self._count_unfinished(title)
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
            if ep < episodes:
                # The drawer owns the keyboard while it is open, so a ↓ pressed now would scroll
                # comments, not switch the episode (see close_comments). Hand the key back to the
                # video before advancing.
                self.ui.close_comments()
                if not self.ui.next_episode():
                    licensed = False
                    # Counted, not just licensed-false: the episodes never reached print no site
                    # total, so shortfall stays 0 and the engine's row-vs-total gate would call a
                    # 2-of-10 walk 「正常」 the moment any reply rows pushed the table over the
                    # two harvested episodes' totals. Naming it here is the only thing that makes
                    # a key that stopped landing a refusal rather than a silent yield cut.
                    self._count_unfinished(title)
                    break
                # The key press is not evidence: ↓ walks whatever queue the player holds, so on
                # the last episode it steps into the NEXT drama (measured: after the first ↓,
                # every page for the rest of the walk belonged to the show the account had been
                # watching). The screen says which show is on stage, so ask it before spending
                # another episode's wait on traffic that is not ours.
                if self._confirm_position(title) == 'drifted':
                    licensed = False
                    self._count_unfinished(title)
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

    def _confirm_position(self, want_title) -> str:
        """Ask the player what it is showing: 'ok' or 'drifted'.

        'ok' covers two cases on purpose — the screen names the requested drama, and the tree
        says nothing at all (cold). The second is no evidence, and the walk must not stop on it
        nor claim it as confirmation: the traffic gate underneath is what refuses another
        drama's pages when the screen cannot answer.

        A first read that names ANOTHER show is not a verdict either: the header prints whatever
        is on stage and the browse page keeps naming the previous drama for a moment after the
        card click, so the walk re-asks (asking 停止 between reads) and only concludes 'drifted'
        when the wrong name survives the settle. The false-refuse is the expensive direction —
        it throws away a drama the user already paid to open — whereas a false 'ok' is caught a
        layer down by the traffic gate.
        """
        want_norm = norm_title(want_title)
        self._check_abort()
        have = self.ui.screen_drama_title()
        if not have or screen_names(want_norm, norm_title(have)):
            return 'ok'
        for _ in range(_SCREEN_SETTLE_READS):
            self._check_abort()
            time.sleep(_SCREEN_SETTLE_SECONDS)
            again = self.ui.screen_drama_title()
            if not again or screen_names(want_norm, norm_title(again)):
                return 'ok'  # went cold, or settled onto the requested drama
            have = again
        self._log(t('crawl.hg.cmt.screenMismatch', want=want_title, have=have))
        return 'drifted'

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

    @staticmethod
    def _reply_episode_group(record):
        """The EPISODE group a reply page belongs to, read out of its own body.

        A reply record's ``group_id`` is the PARENT COMMENT id, not the episode (measured:
        the path is ``reply/list/{comment_id}``), so the episode has to come from the
        payload — the parent comment's ``common.group_id``. Reading it is what lets
        ``集序号`` be the episode the thread really is in rather than the one the walk
        happened to be standing on when it clicked 展开.
        """
        data = (record.get('payload') or {}).get('data') or {}
        parent = data.get('comment') if isinstance(data.get('comment'), dict) else {}
        common = parent.get('common') if isinstance(parent.get('common'), dict) else {}
        group = str(common.get('group_id') or '')
        if group:
            return group
        for element in data.get('reply_list') or []:
            body = (element or {}).get('Common') if isinstance((element or {}).get('Common'), dict) else {}
            group = str(body.get('group_id') or '')
            if group:
                return group
        return ''

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
            # A reply record's own ``group_id`` is the PARENT COMMENT id — that is the thread
            # key. The EPISODE has to be read out of the body, or every thread of one episode
            # would merge into a single ledger entry.
            parent_key = str(record.get('group_id') or '')
            group = self._reply_episode_group(record) or parent_key
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
            key = parent or parent_key or f'anon-reply-{len(self._reply_progress)}'
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

    def _await_page(self, _series_id, seconds, allow_repeat=False, stamp=None):
        """Block until a fresh ``comment/list`` page of THIS drama lands in the capture.

        Fresh = a group this walk has not harvested (``allow_repeat`` additionally
        admits a NEWER page of the same group — the drawer's cursor pages). Every
        read batch is BUFFERED first: the record that answers may sit behind a
        reply page or a later episode's page, and an early return must not throw
        those away (the tail offset already passed them). Reply pages go to the
        inbox; a page whose REQUEST names another drama is refused by name — 错剧
        rows in the table are worse than a missing episode.

        *stamp* is the ``(文章URL, 剧名, 集序号)`` of the target whose drawer asked for
        the page, carried onto every reply record the inbox takes on. The walk drains
        the inbox whenever it next looks, which can already be the following drama.

        The reference is the FIRST page's own ``book_id`` — read off the request the player
        sent, because a page's rows usually print ``expand.book_id == "0"``. The web
        ``series_id`` is deliberately NOT compared to it: measured 2026-10-20, one and the
        same drama is ``series_id=7696437705822981182`` on the web page and
        ``book_id=7697823071830297624`` in the client, two separate id spaces, so comparing
        them would refuse every page a LINK-fed walk asked for correctly. *series_id* stays
        in the signature (spelled ``_series_id`` because nothing reads it) because callers pass
        it; the identity answer comes from the traffic.
        """
        deadline = time.time() + max(5, int(seconds))
        while time.time() < deadline:
            self._check_abort()
            self._pending.extend(self._read_records())
            keep, hit = [], None
            for record in self._pending:
                kind = record.get('kind')
                if kind not in ('reply', 'comment'):
                    continue
                # The identity gate runs on BOTH kinds. A child page is asked for by whatever
                # is on screen, so when the feed has drifted it belongs to the wrong drama —
                # and stamping it with ours would put another show's replies in this table.
                book = self._request_book_id(record) or self._payload_book_id(record)
                if book:
                    if self._current_book and book != self._current_book:
                        self._drift_book = book
                        self._log(t('crawl.hg.cmt.groupMismatch', got=book, want=self._current_book))
                        continue
                    self._current_book = book
                if kind == 'reply':
                    if stamp is not None:
                        record['_stamp'] = stamp
                    self._reply_inbox.append(record)
                    continue
                group = str(record.get('group_id') or '')
                if not group:
                    continue
                if group in self._groups_done and not allow_repeat:
                    continue
                if hit is None:
                    hit = record
                else:
                    keep.append(record)
            self._pending = keep
            if hit is not None:
                return hit
            if self._drift_book:
                # A foreign book has already proved the feed left this drama (measured: after the
                # first drift, EVERY later page is theirs). Holding the rest of the window open
                # would wait 90 s on pages the identity gate discards — the walk wants to stop the
                # drama now, not at the deadline.
                return None
            time.sleep(0.5)
        return None

    @staticmethod
    def _request_book_id(record):
        """The drama the PLAYER asked this page about, read off the request it sent.

        Measured 2026-10-20 on a kept capture: EVERY ``comment/list`` and ``reply/list``
        request carries ``business_param.book_id``, while the ROWS of a page belonging to
        another drama print ``expand.book_id == "0"``. So grading the payload alone waves a
        strange drama's thread straight into our table — that run kept 30 rows of book
        ``7615465407347952664`` under the fed 剧名 and stamped them 集序号 1. The request is
        the only field that names the drama on every page, so it is the gate.
        """
        try:
            body = json.loads(record.get('req_body') or '{}')
        except (TypeError, ValueError):
            return ''
        param = body.get('business_param') if isinstance(body.get('business_param'), dict) else {}
        return str(param.get('book_id') or '')

    @staticmethod
    def _payload_book_id(record):
        # The fallback, and only a fallback: a real comment row may carry
        # ``expand.book_id == "0"`` (measured — the drawer's comments of a feed video print
        # 0), so 0 is "the payload does not name the drama", not a mismatch. A reply page has
        # no ``data_list`` at all, so this sees nothing there; ``_request_book_id`` does.
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
        # The SAME predicate the panel greys this mode out with and validation refuses a canvas with
        # (:meth:`crawl_capabilities.mode_blocker`): a node that reaches here has already been paid for,
        # so this line is the last of three answers and must not be a fourth opinion about the platform.
        if not capabilities.requirement_met('windows_desktop'):
            raise ValueError(t('crawl.hg.cmt.needsExtras', missing='Windows desktop (mitmdump + UIA)'))
        missing = [name for name in ('mitmproxy', 'uiautomation') if importlib.util.find_spec(name) is None]
        if missing:
            if machine.is_frozen():
                # The desktop build does not carry this stack (mitmproxy pulls a large tree, and the
                # harvest drives a real desktop window). 「pip install mitmproxy」 is not a thing
                # anybody can do inside an exe, so name the build that can run the node instead.
                raise ValueError(t('crawl.hg.cmt.needsExtrasFrozen', names=' / '.join(missing)))
            raise ValueError(t('crawl.hg.cmt.needsExtras', missing=' / '.join(missing)))
        mitmdump = find_mitmdump()
        if not mitmdump:
            raise ValueError(t('crawl.hg.cmt.noMitmdump', detail='settings mitmdump_path / PATH / venv Scripts'))
        player = find_player()
        if not player:
            raise ValueError(t('crawl.hg.cmt.noPlayer', path=str(get_setting('hongguo_player_path') or '')))
        if ctypes.windll.user32.FindWindowW(PLAYER_CLASS, None):
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
        der = trust.read_der(cer)
        if der is None:
            raise ValueError(t('crawl.hg.cmt.caNotTrusted', command=trust.manual_command(cer)))
        if trust.is_trusted(der):
            return
        command = trust.manual_command(cer)
        if not _bool_setting('harvest_auto_install_ca', True):
            raise ValueError(t('crawl.hg.cmt.caNotTrusted', command=command))
        trust.install(der)
        if not trust.is_trusted(der):
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

    def _count_unfinished(self, target) -> None:
        """Name a drama that was NOT harvested completely, exactly once.

        Several paths reach that verdict for the same drama — no title to search with, the
        client refusing to open it, the screen showing another show, traffic that stopped
        coming, a switch that walked off the drama, and a ↓ that simply stopped landing — and the
        tail refusal prints this list with a count, so a duplicate would report one hole as
        many. Marking short is part of it: the engine's gate reads ``end_reason`` and must not
        see a clean end beside a hole.
        """
        self._mark_short()
        if target not in self.skipped_targets:
            self.skipped_targets.append(target)

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
    raw = get_setting(key)
    return default if raw is None or str(raw).strip() == '' else as_bool(raw, default)
