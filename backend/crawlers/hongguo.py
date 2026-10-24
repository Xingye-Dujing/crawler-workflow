"""红果短剧 (hongguoduanju.com): its four 热播 boards, read from the page's own payload.

The site is a React router app that ships the finished board inside the document itself
(``window._ROUTER_DATA.loaderData['rank_<slug>/page'].content._data``), so this crawler
reads *data*, never the rendered columns: one payload holds the whole page — 20 works
with title, score, heat, favourites, likes, tags, description and the episode list — and
no click is needed for anything, including 集数 (:attr:`_episode_count`, measured equal
to the detail page's own count).

Four measurements shape the loop, each in ``docs/crawler_notes.md`` 红果短剧:

* **The payload is deferred.** Right after ``driver.get`` the loader key is already there
  but ``content`` has no ``_data`` yet; it fills about two seconds later. So the page is
  asked with :meth:`~crawlers.base.Crawler.wait_for_first_content` and the crawler never
  sleeps a fixed number on faith.
* **A page that will never fill says so immediately.** ``/rank/hot-drama?page=6`` renders
  the layout alone (no ``rank_<slug>/page`` loader key at all, 0 cards) and the browser
  settles there — that is the ``stalled`` evidence, not a reason to sit out the budget.
* **The pager is the site's own.** ``pagination.nextUrl`` is followed verbatim, so the
  URL that produced a page is the URL the cursor records.
* **The boards are anonymous.** No cookie, no account: every board is served to a fresh
  browser, which is why this crawler has no ``login_url`` and no cookie row in the panel.

The crawl is one board per node (the panel's 榜单 select), which keeps each node's rows
one table with one meaning — mixing four boards would need a 榜单 column that exists
only to undo the mixing.
"""

import logging
import re

from i18n import t

from .base import UNDER_TARGET, Crawler, PageNotArrivedError, as_index
from .engine.counters import first_int, has_count, parse_count

logger = logging.getLogger(__name__)

#: Everything the site serves lives here; the payload's own ``href``/``playHref``/
#: ``nextUrl`` come back as absolute or root-relative strings and are completed with it.
BASE = 'https://hongguoduanju.com'

#: The board a node falls back to when its select was left blank (the panel's own default).
DEFAULT_BOARD = 'hot_drama'

#: The four boards in the order the panel offers them: stored value → (route slug, label key).
#: The stored values are what a node holds, so they are identifiers, never the Chinese label.
BOARDS = {
    'hot_drama': ('hot-drama', 'crawl.hg.boardHotDrama'),
    'hot_real_drama': ('hot-real-drama', 'crawl.hg.boardRealDrama'),
    'hot_ai_drama': ('hot-ai-drama', 'crawl.hg.boardAiDrama'),
    'hot_comic_drama': ('hot-comic-drama', 'crawl.hg.boardComicDrama'),
}

#: ``评分9.1`` → 9.1. The label is the only place the score appears.
_RATING_RE = re.compile(r'(\d+(?:\.\d+)?)')

#: One cheap look at the page's loader state. Returns an OBJECT, not a JSON string: a
#: string is what this probe first came back as on this site, and a ``str`` read as a
#: board fails at the caller with ``'str' object has no attribute 'get'`` (probe #11).
_STATE_JS = r"""
var out = {state: 'no_router', loader_keys: [], page_key: '', rows: 0, is_success: null,
           page_num: null, total_pages: null, next_url: ''};
try {
    var data = window._ROUTER_DATA;
    var loaders = data && data.loaderData;
    if (loaders) {
        var keys = Object.keys(loaders);
        out.loader_keys = keys;
        var pages = keys.filter(function (k) { return k.indexOf('/page') > 0; });
        out.state = 'missing';
        if (pages.length) {
            out.page_key = pages[0];
            var content = loaders[pages[0]] && loaders[pages[0]].content;
            var board = content && content._data;
            if (board && typeof board.then !== 'function') {
                var rows = board.rankList || [];
                var pg = board.pagination || {};
                out.state = 'ready';
                out.rows = rows.length;
                out.is_success = board.isSuccess === true;
                out.page_num = pg.pageNum || null;
                out.total_pages = pg.totalPages || null;
                out.next_url = pg.nextUrl || '';
            } else if (board) {
                // The key is there, the data has not landed yet (measured ~2s).
                out.state = 'deferred';
            }
        }
    }
} catch (e) {
    out.state = 'no_router';
}
return out;
"""

#: The board itself, as the page's own object. ``null`` while it is absent or still a
#: promise; the state probe above is what distinguishes those cases.
_BOARD_JS = r"""
var data = window._ROUTER_DATA;
var loaders = data && data.loaderData;
if (!loaders) { return null; }
var pages = Object.keys(loaders).filter(function (k) { return k.indexOf('/page') > 0; });
if (!pages.length) { return null; }
var content = loaders[pages[0]] && loaders[pages[0]].content;
var board = content && content._data;
if (!board || typeof board.then === 'function') { return null; }
return board;
"""


def hongguo_board_url(slug: str, page: int) -> str:
    """Page *page* of one board.

    Page 1 carries no parameter on purpose: ``?page=1`` and the bare URL are the same page
    (measured), and the bare URL is the one a user pasting the address bar would hand in.
    """
    base = f'{BASE}/rank/{slug}'
    return base if page <= 1 else f'{base}?page={page}'


def hongguo_board(board) -> tuple[str, str, str]:
    """``(stored value, route slug, label key)`` for one board; an unknown one is refused by name."""
    wanted = str(board or '').strip() or DEFAULT_BOARD
    entry = BOARDS.get(wanted)
    if entry is None:
        raise ValueError(t('crawl.hg.boardUnknown', board=str(board), options='、'.join(BOARDS)))
    slug, label_key = entry
    return wanted, slug, label_key


class HongguoCrawler(Crawler):
    """红果短剧's boards. Anonymous (no session), and board-only (no keyword mode)."""

    domain = 'hongguoduanju.com'

    # No ``login_url`` and no ``cookie_domains``: every board is served to a fresh browser
    # (measured), so there is no session state here to keep or to lose. The matrix says the
    # same thing on its side (``needs_session=False``), which is what keeps this platform
    # out of the cookie preflight and out of the panel's account list.

    def search(self, keyword=None, **_kwargs):
        """No keyword search exists on this site; the panel offers only its boards."""
        raise ValueError(t('crawl.hg.searchUnsupported', keyword=str(keyword or '')))

    def get_detail(self, url: str) -> dict | None:
        """Refused by name: no mode declares a link crawl, and an unmeasured second reader
        of the same facts (集数 lives in the board payload) is how two tables start
        disagreeing."""
        raise ValueError(t('crawl.hg.noDetail', url=str(url or '')))

    @classmethod
    def browserless_comment_harness(cls, **kwargs):
        """The comment crawl of this platform runs NO browser: it drives the desktop
        player behind our own proxy (:mod:`crawlers.hongguo_harvest`; why the protocol
        is not spoken directly is measured in ``docs/crawler_notes.md`` 红果短剧).

        The comment executor looks this name up on the registry class — one
        declarative attribute, so the executor grows no ``if platform ==`` branch
        and the matrix stays the only answer to what a platform can collect.
        """
        from .hongguo_harvest import HongguoCommentHarness

        return HongguoCommentHarness(**kwargs)

    # ─── the crawl ───

    def hot(self, target_count: int = 50, board: str = 'hot_drama', **kwargs):
        """One 热播 board, paged along the site's own ``nextUrl``.

        ``target_count`` and ``board`` are the matrix's arguments, named as the matrix names
        them. The cursor is ``{'board', 'page', 'page_url', 'done'}``: the page actually read,
        never an id list (:meth:`~crawlers.base.Crawler.seed` supplies the ids on resume).
        """
        board_key, slug, label_key = hongguo_board(board)
        board_label = t(label_key)
        if self.collected() >= target_count:
            logger.info(t('crawl.hg.target_reached', n=target_count))
            return self.results()
        logger.info(t('crawl.hg.start', board=board_label, n=target_count))
        resume = self.resume_of(kwargs)
        page = max(1, as_index(resume.get('page'), 1))
        url = hongguo_board_url(slug, page)
        seen = {str(row.get('作品ID') or '') for row in self.results() if row.get('作品ID')}
        scanned = kept = refused = 0
        stuck = 0
        end = ''
        while self.collected() < target_count:
            settled = self.open(url)
            wait = self.wait_for_first_content(
                has_content=lambda: self._board_state().get('state') == 'ready',
                # Bound as a default: the wait calls this on every tick, and it must read the
                # navigation *this* round settled (B023).
                stalled=lambda page_settled=settled: self._stalled(page_settled),
            )
            state = self._board_state()
            if not wait['arrived']:
                facts = {'waited': wait['waited'], 'verdict': wait['verdict'], 'gave_up': wait['gave_up']}
                if wait['verdict'] == 'unreachable':
                    raise PageNotArrivedError(
                        t('crawl.hg.noPageRefused', url=self._current_url(), detail=self._error_detail()), **facts
                    )
                raise PageNotArrivedError(
                    t(
                        'crawl.hg.noBoard',
                        url=self._current_url(),
                        seconds=round(wait['waited']),
                        keys='、'.join(state.get('loader_keys') or []) or '—',
                    ),
                    **facts,
                )
            payload = self._board_payload()
            rows = payload.get('rankList') or []
            pagination = payload.get('pagination') or {}
            page_num = as_index(state.get('page_num'), page)
            scanned += len(rows)
            fresh = 0
            for item in rows:
                if self.collected() >= target_count:
                    break
                row = self._row(item)
                item_id = str(row['作品ID'] or '')
                if not row['作品名'] or not item_id:
                    # A card with no name or no id is not a work; counted, never emitted as a
                    # blank row. Measured: never happens on these four boards.
                    refused += 1
                    continue
                if item_id in seen:
                    continue
                seen.add(item_id)
                if self.emit(row):
                    kept += 1
                    fresh += 1
                # One row, one position: a resume re-opens the page it was on and the rows
                # already stored are skipped by id above, so no row is paid for twice.
                self.mark_position(board=board_key, page=page_num, page_url=url, done=self.collected())
            logger.info(t('crawl.hg.page', page=page_num, n=len(rows), fresh=fresh, done=self.collected()))
            if not rows:
                # 200 with an explicitly empty rankList is the server's own word, which is the
                # bar ``note_end('empty')`` demands.
                if payload.get('isSuccess') is True:
                    end = 'empty'
                break
            nxt = str(pagination.get('nextUrl') or '')
            if not nxt:
                # The board's own pager says there is no page after this one.
                end = 'site_end'
                logger.info(t('crawl.hg.lastPage', page=page_num, n=self.collected()))
                break
            if nxt == url or nxt == self._current_url():
                # The pager handed back the URL we are already on. Stopping — and NOT
                # licensing it: the site did not say the list had ended.
                logger.info(t('crawl.hg.replay', page=page_num, url=nxt))
                break
            stuck = stuck + 1 if not fresh else 0
            if stuck >= 2:
                # Two pages in a row with nothing new: on a resume this is the page already
                # stored, so one is tolerated; a second one is a pager that stopped moving.
                logger.info(t('crawl.hg.noFresh', page=page_num))
                break
            url = nxt
            self._polite_pause()
        refused_by_the_site = getattr(self, 'login_wall', False) or getattr(self, 'risk_blocked', False)
        if self.collected() < target_count and not refused_by_the_site:
            if end:
                # Only the site's own words license a short: its pager said "no next page", or
                # its payload was explicitly empty. A loop that stopped on a repeated or
                # un-moving page is left UNDER_TARGET, per ``note_end``.
                self.note_end(end, scanned=scanned, kept=kept, refused=refused)
            else:
                self.note_end(UNDER_TARGET, scanned=scanned, kept=kept, refused=refused)
        logger.info(t('crawl.hg.finished', n=self.collected(), total=target_count))
        return self.results()

    # ─── the page, as the page itself reports it ───

    def _board_state(self) -> dict:
        """One cheap read of the loader state (see :data:`_STATE_JS`); ``{}`` when unreadable."""
        try:
            state = self.driver.execute_script(_STATE_JS)
        except Exception as exc:
            logger.debug('hongguo: state probe failed: %s', exc)
            return {}
        return state if isinstance(state, dict) else {}

    def _board_payload(self) -> dict:
        """The board the page carries (see :data:`_BOARD_JS`); ``{}`` when it carries none."""
        try:
            payload = self.driver.execute_script(_BOARD_JS)
        except Exception as exc:
            logger.debug('hongguo: board probe failed: %s', exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _stalled(self, settled: bool) -> bool:
        """Whether the page in flight can no longer be expected to fill.

        The board lives under a per-board loader key (``rank_<slug>/page``). A navigation the
        browser has already settled that carries no such key at all is not a page still
        hydrating — measured, ``?page=6`` renders the layout and nothing else, immediately and
        after settling. Without this the patient wait would sit out its whole budget on a page
        that has already answered.
        """
        state = self._board_state()
        return bool(settled) and state.get('state') == 'missing' and not state.get('page_key')

    # ─── one card ───

    @classmethod
    def _row(cls, item: dict) -> dict:
        """One ``rankList`` entry → the table row. Every field the payload has, and nothing invented."""
        item = item if isinstance(item, dict) else {}
        episodes = item.get('episodeVids')
        return {
            '排名': cls._rank(item.get('rank')),
            '作品名': Crawler.as_text(item.get('title')),
            '评分': cls._rating(item.get('scoreText')),
            '热度': cls._count(item.get('heatText')),
            '收藏': cls._count(item.get('favoriteText')),
            '点赞': cls._count(item.get('likeText')),
            # The site's own tags, in its own order and wording — including the literal ``205``
            # one board prints instead of a name (docs/crawler_notes.md 红果短剧).
            '分类': ' | '.join(tag for tag in (Crawler.as_text(v) for v in item.get('tags') or []) if tag),
            '状态标签': ' | '.join(tag for tag in (Crawler.as_text(v) for v in item.get('statusTags') or []) if tag),
            '集数': len(episodes) if isinstance(episodes, list) else '',
            '简介': Crawler.as_text(item.get('description')),
            '作品ID': Crawler.as_text(item.get('seriesId') or item.get('id')),
            '链接': cls._absolute(item.get('href')),
            '播放链接': cls._absolute(item.get('playHref')),
            '封面': cls._absolute(item.get('cover')),
        }

    @staticmethod
    def _rank(value):
        """The rank the board printed. A board row with no rank is left blank, not given a 0."""
        return first_int(value) if has_count(value) else ''

    @staticmethod
    def _count(label):
        """A figure the site published (万-rounded), or blank when it published none.

        Blank rather than 0 for an absent label: on a board 0 is itself a claim (a work with
        no 收藏), and a fabricated 0 would be summed downstream as one.
        """
        return parse_count(label) if has_count(label) else ''

    @staticmethod
    def _rating(label):
        """``评分9.1`` → 9.1; a work the site did not score stays blank."""
        match = _RATING_RE.search(str(label or ''))
        return float(match.group(1)) if match else ''

    @staticmethod
    def _absolute(url) -> str:
        """The site's own link, completed against the host that served it."""
        text = Crawler.as_text(url)
        if text.startswith('http://') or text.startswith('https://'):
            return text
        if text.startswith('//'):
            return f'https:{text}'
        if text.startswith('/'):
            return BASE + text
        return text
