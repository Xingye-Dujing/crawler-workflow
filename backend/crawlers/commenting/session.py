"""The browser half of the comment engine: one session, many articles, resumable per link.

What lives where, and why the split is worth the extra file:

* the per-platform page walks are **not** here — each one lives with its platform in
  ``crawlers/platforms/<id>/comments.py`` and registers itself in ``crawlers/commenting/walks.py``.
  They used to be methods on this class, which made one module the home of seven unrelated sites' DOM
  knowledge (1,183 lines) and made the engine look an adapter up with ``getattr(session, 'crawl_' +
  platform)``, a name built out of a string;
* this file owns what survives from one article to the next — the driver, the log line, the pacing
  knob, the stop predicate — plus the element reads every walk shares, and the dispatch itself.

Design notes the code cannot shout later:

* Column keys deliberately avoid every name in ``run_store._URL_FIELDS`` /
  ``_AUTHOR_FIELDS`` / ``_BODY_FIELDS`` ('文章URL', '评论者', '评论内容').
  The dedupe ledger picks identity from those field lists; a comment has no
  link of its own, so borrowing those names would make every comment of one
  article hash to the same key and silently drop all but the first.
  Its identity comes from ``评论ID`` instead (``run_store._COMMENT_ID_FIELDS``, plus
  ``平台`` so two sites' id spaces cannot meet): the ledger must NOT fall back to the
  whole-row hash here, because a row also carries ``楼层``, which a fresh harness
  numbers from 1 again — a resume would then re-store every comment of a re-walked
  article with invented floors.
* One article can fail for different reasons and they must not blur:
  ``ok`` (rows, maybe zero — zero means 无评论), ``blocked`` (risk-control or
  login wall answered instead of content), ``dead`` (link unreadable/404).
* headless is honoured everywhere, including zhihu's answer/question pages: the
  ``NEVER_HEADLESS`` exception this file used to declare was deleted with #148,
  which gives a headless session a desktop UA and real window metrics (measured:
  知乎评论区伪装无头 5/5 == 可见窗口 5/5). A visible window is what the user asked
  for, never something this module substitutes.
* a walk never reaches through the session into the owning crawler: 风控 is latched with
  :meth:`mark_risk_blocked` and a captcha is asked about with :meth:`is_walled`, because the
  platform module that needs the answer must not have to know that an owner exists at all.
* ``platform_for`` (the article-link → adapter router) lives in core.refs: the engine validator
  needs the same table without importing any crawler.
"""

import contextlib
import time

from crawlers.commenting import walks
from crawlers.commenting.protocol import DEAD, OK
from crawlers.engine import pagefetch
from i18n import t


class CommentSession:
    """One browser session per platform; the node handler owns lifecycle."""

    def __init__(self, driver, log=None, nap=None, abort=None, owner=None):
        self._driver = driver
        # The crawler whose browser this is, when there is one. Held rather than flattened
        # into the snapshot above because 停止 may *replace* the session under the crawl:
        # the reaper installs a :class:`~crawlers.core.faults.DeadDriver` once it has had to kill
        # the process by PID, and a session that read its own stored reference would go on
        # asking a dead chromedriver — 16.3 seconds per command, measured, one retry ladder
        # per row of a walk that is already over.
        self._owner = owner
        self.log = log or (lambda msg: None)
        self.nap = nap or time.sleep
        # "May I stop?" — the same predicate the crawlers carry, because a comment
        # node reads hundreds of pages and the node handler only asks between URLs.
        self._abort = abort

    @property
    def driver(self):
        """The session as it is *now*, not as it was when the walk started."""
        return self._owner.driver if self._owner is not None else self._driver

    def may_stop(self) -> bool:
        return bool(self._abort is not None and self._abort())

    def walk(self, platform: str, url: str, limit: int) -> tuple:
        """Read one article's comments on *platform*, using the walk that platform registered.

        The refusal is named, never empty: the caller used to do ``getattr(session, 'crawl_' +
        platform)`` and had to remember to check the result, and an unlisted link then walked as
        whatever adapter the fallback guessed. A platform with no registered walk raises, because a
        table that answers 「该站点没有评论」 for a site nobody wrote is the worst possible outcome of a
        routing mistake (AGENTS: 具名拒绝).
        """
        walker = walks.walk_for(platform)
        if walker is None:
            raise ValueError(t('comment.noAdapter', platform=platform, url=url))
        return walker(self, url, limit)

    # ─── the reads every walk shares ────────────────────────────────────────────────────────────

    def fetch_in_page(self, url: str, timeout_ms: int = 25000) -> str:
        # The mechanics live in engine.pagefetch (one home for the three page-context
        # fetch shapes); the comment engine wants the raw text so it can read wall
        # wording out of an HTML body a JSON parse would discard.
        return pagefetch.fetch_text(self.driver, url, timeout=timeout_ms / 1000)

    def body_head(self, limit: int = 600) -> str:
        with contextlib.suppress(Exception):
            return self.driver.find_element('css selector', 'body').text[:limit]
        return ''

    def safe_text(self, element) -> str:
        with contextlib.suppress(Exception):
            return (element.text or '').strip()
        return ''

    def find_or_none(self, selector: str):
        try:
            return self.driver.find_element('css selector', selector)
        except Exception:
            return None

    def node_text(self, selector: str) -> str:
        """The text of the first element matching *selector*, or '' when there is none."""
        element = self.find_or_none(selector)
        return self.safe_text(element) if element is not None else ''

    # ─── the owning crawler, asked through the session ──────────────────────────────────────────

    def mark_risk_blocked(self) -> None:
        """Latch 风控 on the crawler that owns this browser, when there is one.

        A security-check page is not a dead cookie and the two need opposite advice (退避重试 vs
        重新保存 Cookie). Only the owner can be accused, and a session with no owner — the live tier
        builds one straight off a browser — simply has nobody to tell.
        """
        if self._owner is not None:
            self._owner.risk_blocked = True

    def is_walled(self) -> bool:
        """Whether the owning crawler sees a wall this page could not show.

        douyin's captcha speaks in the tab TITLE, which ``looks_blocked`` on the body cannot see, so
        the crawler that watches the title is asked rather than guessed about.
        """
        check = getattr(self._owner, '_is_walled', None) if self._owner is not None else None
        return bool(check and check())


__all__ = ['DEAD', 'OK', 'CommentSession']
