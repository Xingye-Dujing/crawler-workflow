"""The overlay protocol: read one video *inside the profile document*, with no navigation.

Measured 2026-09-30 (``scratchpad/dy_phase0.log``): clicking a
``user-post-list a[href*="/video/<id>"]`` swaps the URL to ``…?modal_id=<id>`` while
``document navigated: False`` — the slide renders its own counters, caption and author in the same
document. That makes it a different job from walking the grid: the grid code answers "how do I get
more cards" and this answers "how do I read this card without spending a page load on it". The cost
difference is the whole reason it exists — a 20-video author walk used to pay 20 navigations and now
pays one, and the walk's ``visited`` assertions are exactly that claim.

Why a mixin and not free functions taking the crawler: nothing here changes name or call site, so the
seams stay exactly where the suite put them. ``tests/integration/test_douyin_crawler.py`` models the
overlay **at the driver** — a click opens its modal state, ESC dismisses it, and the active-slide read
answers the scoped script — which means the real code in this file is what runs in those 93 cases, and
they passed without one test being retargeted. A free-function form would have moved every call in the
walk for no measured gain, and the page-load invariants the fake records (``visited``,
``container_jumps``) would then be reading a walk whose shape nobody had re-checked.
"""

import contextlib
import logging
from collections.abc import Callable

from crawlers.engine import feed
from crawlers.engine.counters import parse_count
from crawlers.platforms.douyin import rows
from i18n import t

logger = logging.getLogger(__name__)


class DouyinOverlayMixin:
    """One video read off the in-page overlay. The host supplies the driver and the selectors.

    The annotations below are the contract with the hosting crawler — declared, not invented: each is
    defined on :class:`~crawlers.platforms.douyin.crawler.DouyinCrawler`, and naming them here is what
    lets a reader (and a static checker) see what this code depends on without opening the other file.
    """

    driver: object
    ACTIVE_SLIDE: str
    ESC_KEY: str
    MODAL_ID_RE: object
    MODAL_WAIT: float
    PROFILE_ANCHOR: str
    VIDEO_HREF: object
    _profile_totals: tuple
    _current_url: Callable[[], str]

    #: Returned by :meth:`_modal_row` when the overlay simply would not open on this card — the id is
    #: left unpaid so a later scroll round may re-surface it, instead of paying a navigation to chase it.
    DEFER = object()

    def _modal_open(self) -> bool:
        """Is an overlay currently up? Active slide node, or a ``?modal_id=`` in the URL."""
        try:
            if self.driver.find_elements('css selector', self.ACTIVE_SLIDE):
                return True
        except Exception:
            return False
        return bool(self._active_modal_id())

    def _close_modal(self) -> bool:
        """Dismiss the overlay with ESC and VERIFY it went — a blind ESC is not "closed".

        Returns whether the overlay is gone. A stuck overlay would cover the next card, so the
        caller needs the true answer rather than hope; ESC is sent, a short bounded re-check polls
        for it, then ESC fires once more before giving up.
        """
        for _ in range(2):
            with contextlib.suppress(Exception):
                self.driver.find_element('css selector', 'body').send_keys(self.ESC_KEY)
            if feed.wait_for(lambda: not self._modal_open(), 1, timeout=3.0, tick=0.5):
                return True
        return not self._modal_open()

    def _find_card(self, aweme_id: str):
        """The profile-grid anchor whose OWN id equals *aweme_id* — matched by parsed id, not a
        substring, so a 19-digit id that merely prefixes another cannot return the wrong card."""
        for el in self.driver.find_elements('css selector', self.PROFILE_ANCHOR):
            with contextlib.suppress(Exception):
                match = self.VIDEO_HREF.search(str(el.get_attribute('href') or ''))
                if match and match.group(1) == str(aweme_id):
                    return el
        return None

    def _open_modal(self, aweme_id: str) -> bool:
        """Click this id's grid card so the overlay opens on it; no navigation to chase a missing card.

        Returns True only when the overlay is showing THIS id and its slide has painted. A card the
        grid has virtualised away is NOT recovered by re-navigating the profile (that is the storm
        this whole change removes) — it returns False, and the caller defers the id to a later round
        where scrolling may re-surface it.
        """
        card = self._find_card(aweme_id)
        if card is None:
            return False
        try:
            self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', card)
            card.click()
        except Exception:
            return False
        # The overlay swaps the URL to modal_id=<id> with no document navigation; wait only as long
        # as a slide should need to paint, and require it be THIS id, never a neighbour.
        return bool(
            feed.wait_for(
                lambda: self._active_modal_id() == str(aweme_id) and self._slide_painted(),
                1,
                timeout=self.MODAL_WAIT,
                tick=0.5,
            )
        )

    def _slide_painted(self) -> bool:
        """The active slide has real content (a caption or a counter) — one read, not two."""
        facts = self._active_facts()
        return bool(facts.get('desc') or facts.get('digg'))

    def _active_modal_id(self) -> str:
        """The id the overlay is currently showing (from ``?modal_id=``), or ''."""
        match = self.MODAL_ID_RE.search(self._current_url() or '')
        return match.group(1) if match else ''

    def _active_facts(self) -> dict:
        """Read the ACTIVE slide only — the neighbour ``feed-item`` is in the DOM and must not mix in.

        Counters carry by their own ``data-e2e`` names exactly as on the standalone page; 正文 comes
        from ``video-desc`` and 作者/发布时间 are parsed from ``video-info`` (``@name · date · #tags``).
        Returns an empty dict when there is no active slide (overlay not open / refused).
        """
        script = """
        var root = document.querySelector(arguments[0]);
        if (!root) { return {}; }
        function t(sel) {
          var el = root.querySelector(sel);
          return el ? (el.innerText || '').trim().replace(/\\s+/g, ' ') : '';
        }
        return {
          digg: t('[data-e2e="video-player-digg"]'),
          comment: t('[data-e2e="feed-comment-icon"]'),
          collect: t('[data-e2e="video-player-collect"]'),
          share: t('[data-e2e="video-player-share"]'),
          desc: t('[data-e2e="video-desc"]'),
          info: t('[data-e2e="video-info"]'),
          nickname: t('[data-e2e="feed-video-nickname"]')
        };
        """
        with contextlib.suppress(Exception):
            found = self.driver.execute_script(script, self.ACTIVE_SLIDE)
            if isinstance(found, dict):
                return found
        return {}

    def _modal_row(self, aweme_id: str) -> dict | None:
        """One row read off the overlay, or :attr:`DEFER` if it would not open (never a navigation).

        An un-clickable card is DEFERRED — the grid virtualises, and the old walk re-navigated the
        profile to chase it, which is exactly the page-load storm this change removes. Opening the
        overlay on THIS id and reading the active slide is the only path here; ``get_detail`` keeps
        the standalone navigation for a single pasted URL, which has no grid to click.
        """
        if not self._open_modal(aweme_id):
            return self.DEFER
        try:
            facts = self._active_facts()
            shown = self._active_modal_id()
            if shown and shown != str(aweme_id):
                # The active slide is a different video than the card we asked for — a wrong row is
                # data, so refuse it; deferring lets the next look try this id again.
                logger.warning(t('crawl.dy.detailSwapped', i=aweme_id, shown=shown))
                return self.DEFER
            text = facts.get('desc') or ''
            publish = rows.publish_from_info(facts.get('info') or '')
            nickname = (facts.get('nickname') or '').lstrip('@').strip()
            followers, liked = self._profile_totals
            if not text and not publish:
                # Identity is the caption or its date — an overlay still hydrating has neither, and an
                # empty row is not data no matter whose counters briefly rendered. CONSUMED (not
                # deferred): a slide that opened and stayed empty is that post having no text, not a
                # stuck card, so re-reading it next round would only spend the budget again.
                logger.warning(t('crawl.dy.detailNoIdentity', i=aweme_id))
                return None
            return {
                # 标题 is the caption on this site (there is no separate video title in the overlay);
                # never ``self._title()`` — that is the PROFILE document's title, not this video's.
                '标题': text[:120],
                '正文': text,
                '作者': nickname,
                '粉丝数': followers,
                '获赞数': liked,
                '发布时间': publish,
                '视频ID': str(aweme_id),
                '点赞数': parse_count(facts.get('digg')),
                '评论数': parse_count(facts.get('comment')),
                '收藏数': parse_count(facts.get('collect')),
                '转发数': parse_count(facts.get('share')),
                '链接': f'https://www.douyin.com/video/{aweme_id}',
            }
        finally:
            self._close_modal()
