"""Douyin crawl against a fake driver — the measured contract, no browser.

Every assertion here encodes a measurement that contradicts the obvious
implementation, which is exactly why it needs to be pinned where it runs on
every change:

* a list (the author grid, or the page a hot/arrival check waits on) mounts as
  **skeleton rows** first — no anchor, no text — and fills in seconds later, so
  "cards exist" is not yet "results exist"; the wait is for an anchor, not a node
  count;
* a creator's 作品 grid pages **off its own scrollable container**, because the
  window moves none of it (measured: a window scroll grows the footer's
  recommendations and leaves the grid untouched), so a walk that scrolled the
  window would report the head of the grid as the whole of it;
* a row's numbers come from the ``data-e2e`` counters that name themselves on the
  video page, and the row has **no 播放数 column at all**, because the web player's
  second number is the like count, not plays — a plausible-wrong figure is worse
  than none (a grid card's own bare figure measures equal to that like count);
* comments are DOM-scrolled (douyin's endpoint is signed with ``a_bogus``).
"""

import json
import re

import pytest
from selenium.common.exceptions import TimeoutException

import crawlers.base as base_module
from crawlers.base import UNDER_TARGET, Crawler
from crawlers.comments import BLOCKED, DEAD, OK, CommentSession, douyin_comment_fields, parse_douyin_threads
from crawlers.douyin import (
    DouyinCrawler,
    _author_from_related,
    _clean_publish,
    douyin_id,
    douyin_sec_uid,
)
from crawlers.engine.counters import parse_count
from i18n import stop_reason_label, t
from utils.helpers import platform_for

pytestmark = pytest.mark.unit

ID = '7665683746674183459'
INFO_TEXT = '归墟第十二集 #归墟 #末日 #科幻\n5.9万\n2099\n9241\n7839\n举报\n发布时间：2026-08-04 16:32'
RELATED_TEXT = '泫九粉丝167.0万获赞1157.5万关注短剧 · 归墟第一季07:58播放中第7集'
COMMENT_BLOCK = '\n'.join(
    ['盖世英雄小行者', '...', '作者的脑洞太强大了，这才叫科幻', '1月前·北京', '', '5', '', '分享', '展开1条回复']
)


class El:
    def __init__(self, text='', attrs=None, intercept=False, on_click=None, on_send_keys=None, replies=None):
        self.text = text
        self._attrs = attrs or {}
        self.sent = []
        self.clicked = False
        self._intercept = intercept
        # Overlay emulation: a grid card's click opens the modal, and ESC on the body closes it.
        # Optional so every other El (comment items, counters) is unchanged.
        self._on_click = on_click
        self._on_send_keys = on_send_keys
        # A comment-item that holds a reply thread: ``replies`` are its child comment texts, and they are
        # only exposed once the thread is expanded (``_expanded``). A non-thread item leaves both empty.
        self._replies = list(replies) if replies else None
        self._expanded = False

    def get_attribute(self, name):
        return self._attrs.get(name, '')

    def send_keys(self, value):
        self.sent.append(value)
        if self._on_send_keys:
            self._on_send_keys(value)

    def click(self):
        if self._intercept:
            raise RuntimeError('element click intercepted')
        self.clicked = True
        if self._on_click:
            self._on_click()


class FakeDriver:
    """Serves the search route and the video page from fixed fixture maps.

    Two measured properties decide its shape:

    * the result list mounts as **skeleton rows** and only later holds anchors, so
      ``fill_after`` keeps the page card-less for that many reads — the case a
      crawler must wait out instead of reporting zero rows;
    * a window scroll pays out a **batch** of new rows, so ``scroll_batches`` is
      what each scroll reveals.
    """

    def __init__(
        self,
        cards,
        facts=None,
        facts_by_id=None,
        video_body=INFO_TEXT,
        comment_items=None,
        comment_pages=None,
        redirects=None,
        moves_on_scroll='',
        comment_count='2099',
        dialog=False,
        fill_after=0,
        scroll_batches=None,
        title='',
        grid=None,
        grid_batches=None,
        works='',
        board=None,
        load_timeout=False,
        document_uri='',
        body=None,
        list_body='',
    ):
        # What the *document* says it is. Measured: after a navigation the browser itself
        # refuses, this is ``chrome-error://chromewebdata`` while ``current_url`` goes on
        # reporting the address that was asked for — so a fake that cannot answer it can
        # never model the one failure mode the crawler has to tell apart.
        self.document_uri = document_uri
        # The whole-page body text, when a test needs the page to say something other than
        # what the video/search fixtures hold (an error page's own words, for instance).
        self.body = body
        # What the RESULT list's body says (the video page's own body is ``video_body``). The list's
        # end-of-line sentence 「暂时没有更多了」 decides whether a walk that stops short is the site out
        # of supply or our scroll failing, so a case has to be able to state it — and ``body`` cannot
        # carry it, because that overrides every page including the detail one.
        self.list_body = list_body
        # A navigation that never settles: measured on a real run (and named by the user
        # watching the window), this is what a slow network looks like from inside the
        # crawler, and the refusal it produces must say so rather than blame the site.
        self.load_timeout = load_timeout
        # What the board's own endpoint answers, asked from inside the loaded page.
        # ``None`` stands for "not JSON at all", which is how a WAF page arrives.
        self.board = board
        self.fetched = []
        self.cards = [] if fill_after else list(cards)
        self._pending = list(cards) if fill_after else []
        self.fill_after = fill_after
        self.scroll_batches = list(scroll_batches or [])
        # What a **fresh load of that document** shows, and how many times each has been loaded.
        # Kept because the walk re-opens its list between passes; a fake that handed the
        # scrolled-to state back on every navigation would let a walk re-read row 57 of a list it
        # never actually paged down again.
        self._first_screen = list(cards)
        self._first_batches = list(self.scroll_batches)
        self._search_loads = 0
        self._reads = 0
        self._profile_loads = 0
        # The author profile's own 作品 grid: the ids mounted in it, the batches a
        # container jump reveals, and the count the page publishes for itself.
        self.grid = list(grid or [])
        self.grid_batches = list(grid_batches or [])
        self._first_grid = list(self.grid)
        self._first_grid_batches = list(self.grid_batches)
        self.works = works
        self.facts = facts if facts is not None else _default_facts()
        # Facts per opened video, so a walk can be shown one page that published nothing but
        # its counter bar and a next page that answered: the measured failure is one row in a
        # batch, not every row.
        self.facts_by_id = dict(facts_by_id or {})
        self.video_body = video_body
        # The page's own ``<title>``, which is where douyin announces the captcha
        # interstitial — no URL pattern says it.
        self.title = title
        # Is the 「保存登录信息」 mask up? It still mounts a few seconds after the
        # page, and dismissal is the cheap case the crawler must handle.
        self.dialog = dialog
        self.dismissals = 0
        # The rows the comment panel holds. A rendered list PERSISTS — every read
        # returns the same rows until a scroll brings more — so the crawler has
        # to stop on "nothing new came back". An empty list here models a video
        # whose panel never filled, which is a failed read, not an empty video.
        self.comment_items = (
            comment_items if comment_items is not None else [El(COMMENT_BLOCK), El('路人\n第二条评论\n3天前·广东\n1')]
        )
        # What the panel holds after each of its own scrolls: ``[screen0, screen1, …]``, the last one
        # repeating. A fixture that always answers the same list can prove dedupe but cannot prove the
        # walk keeps COUNTING once the panel lazy-fills, which is the shape a 2000-comment video has.
        self.comment_pages = list(comment_pages or [])
        # ``{asked_url: served_url}`` — the address the browser ends up on. Empty means every navigation
        # keeps the address it was asked for, which is the shape every other case in this file assumes.
        self.redirects = dict(redirects or {})
        # An address that moves **while the panel is being walked** — the second substitution shape the
        # audit pointed at: the site serves the pasted video, mounts its panel, and only then slides to
        # another one. Without this knob the mid-walk check cannot be expressed at all.
        self.moves_on_scroll = moves_on_scroll
        self.comment_count = comment_count
        self.visited = []
        self.current_url = 'https://www.douyin.com/'
        self.card_reads = 0
        self.scrolls = 0
        # Which surface moved: measured, the profile grid answers only the
        # container jump, so a walk that scrolled the window instead must be
        # distinguishable from one that paged the list.
        self.window_scrolls = 0
        self.container_jumps = 0
        # How many of those moves happened while the driver was standing on a video page —
        # i.e. how much of the walk was paging something that is not the list it came from.
        self.detail_scrolls = 0
        # Overlay state: the author reads through the in-page modal (a card click swaps the URL to
        # ``?modal_id=<id>`` with NO document navigation; ESC dismisses it). Only ``get`` records a
        # visit, so a modal read leaves ``visited`` at the single profile load — which is the whole
        # point the test proves.
        self._modal_id = ''
        self._profile_base = ''

    def _open_modal(self, aweme_id):
        self._modal_id = str(aweme_id)
        self._profile_base = self.current_url
        self.current_url = f'{self._profile_base}?modal_id={aweme_id}'

    def _close_modal(self):
        if self._modal_id:
            self._modal_id = ''
            self.current_url = self._profile_base

    def _modal_facts(self):
        """The ACTIVE slide's fields, mapped onto the names the overlay reader expects."""
        src = dict(self.facts_by_id.get(self._modal_id, self.facts))
        caption = (src.get('info') or '').split('\n')[0].strip()
        # Real ``video-info`` reads ``@作者 · 2025年11月12日 #话题`` — date then hashtags, no prose
        # between — so the publish parse must see that shape, not the caption's leading words.
        return {
            'digg': src.get('digg', ''),
            'comment': src.get('comment', ''),
            'collect': src.get('collect', ''),
            'share': src.get('share', ''),
            'desc': caption,
            'info': '@测试作者 · 2026-08-04 #示例',
            'nickname': '@测试作者',
        }

    def get(self, url):
        self.visited.append(url)
        # The site answers some addresses by showing a DIFFERENT page — measured 2026-09-28: a video id
        # that cannot exist leaves /video/<id> for /jingxuan?modal_id=<some other video>, a different
        # substitute on every visit. A fake that always keeps the asked address cannot express that, and
        # the comment adapter's substitution check would be untestable here.
        self.current_url = self.redirects.get(url, url)
        # A navigation is a document, not a bookmark: a list re-opened later comes back at its
        # first screen and has to be paged down again. The FIRST load is left alone, because
        # that is the scenario a test describes (a page still drawing its skeleton, a page that
        # never hands over a card) rather than a re-open.
        if '/search/' in url:
            self._search_loads += 1
            if self._search_loads > 1:
                self.cards, self.scroll_batches = list(self._first_screen), list(self._first_batches)
                self._pending, self._reads = [], 0
        elif '/user/' in url:
            self._profile_loads += 1
            if self._profile_loads > 1:
                self.grid, self.grid_batches = list(self._first_grid), list(self._first_grid_batches)
        if self.load_timeout:
            # What chromedriver answers when the document is still building at the end
            # of ``page_load_timeout`` — the page is not wrong, it is unfinished.
            raise TimeoutException(f'no such window: navigation timed out for {url}')

    def _mounted_items(self):
        """The comment-item Els currently mounted — virtualisation: a scroll advances the screen."""
        if self.comment_pages:
            screen = min(self.scrolls, len(self.comment_pages) - 1)
            return list(self.comment_pages[screen])
        return list(self.comment_items)

    def _douyin_readings(self):
        """What the panel JS returns: each mounted item as {own, replies}.

        ``own`` keeps the 「展开N条回复」 label while the thread is collapsed (so the parent row reads its
        declared count) and swaps it for 「收起」 once expanded; ``replies`` are non-empty only after the
        native click expanded that item — which is how the fake proves the product reads replies it opened.
        """
        out = []
        for it in self._mounted_items():
            reps = getattr(it, '_replies', None)
            expanded = getattr(it, '_expanded', False)
            own = re.sub(r'展开\s*\d+\s*条回复', '收起', it.text) if (expanded and reps) else it.text
            out.append({'own': own, 'replies': list(reps) if (reps and expanded) else []})
        return out

    def _douyin_openers(self):
        """One button per mounted item that hides a reply thread; state lives on the ITEM (persists across
        rounds), so a thread is tried once and a delete-failed thread (``_expandable=False``) never opens.
        """
        out = []
        for it in self._mounted_items():
            reps = getattr(it, '_replies', None)
            if not reps:
                continue
            label = '收起' if getattr(it, '_expanded', False) else f'展开{len(reps)}条回复'

            def _do_open(x=it):
                x._tries = getattr(x, '_tries', 0) + 1
                if getattr(x, '_expandable', True):
                    x._expanded = True

            opener = El(label, on_click=_do_open)
            opener._parent = it
            out.append(opener)
        return out

    def find_element(self, by, selector):
        if selector == 'body':
            # ESC on the body dismisses the overlay (the modal path); the text it reports is the
            # page body either way.
            text = (
                self.body
                if self.body is not None
                else (self.video_body if '/video/' in self.current_url else self.list_body)
            )
            return El(text, on_send_keys=lambda _v: self._close_modal())
        if selector == '[data-e2e="comment-list"]':
            return El('')
        if selector == '[data-e2e="feed-comment-icon"]':
            return El(self.comment_count)
        if selector == DouyinCrawler.WORK_COUNT:
            return El(self.works)
        raise RuntimeError(f'no element {selector}')

    def find_elements(self, by, selector):
        if selector == DouyinCrawler.CARD_ANCHOR:
            # Counted because a patient wait has to be *interruptible by evidence*: the
            # number of looks this fixture records is how a test proves a provable death
            # was given up on at once rather than waited out to the budget.
            self.card_reads += 1
            if '/video/' in self.current_url:
                # THE POINT. A video page has no result list on it: opening one detail
                # replaced the document, so any read of the search cards from there answers
                # nothing. A fake that ignored the address is how the interleaved walk passed
                # for a whole release while every real run stopped at its first screen (#146).
                return []
            if self.fill_after and self._pending:
                self._reads = getattr(self, '_reads', 0) + 1
                if self._reads >= self.fill_after:
                    self.cards, self._pending = self._pending, []
            return [El('', {'href': f'//www.douyin.com/video/{aweme_id}'}) for aweme_id in self.cards]
        if selector == DouyinCrawler.PROFILE_ANCHOR:
            if '/user/' not in self.current_url:
                return []
            # Each grid card carries a click that opens the overlay on ITS id (the product matches the
            # card by parsed id, not by the first anchor) — this is what lets a wrong-card / neighbour
            # read be caught, and what the author test needs to drive the modal path at all.
            return [
                El(
                    '',
                    {'href': f'https://www.douyin.com/video/{aweme_id}'},
                    on_click=lambda i=str(aweme_id): self._open_modal(i),
                )
                for aweme_id in self.grid
            ]
        if selector == '[data-e2e="comment-item"]':
            # The panel lazy-fills: what it holds is a function of how many times it has been
            # scrolled, so the walk sees screen 2 only after its own scroll moved it.
            return self._mounted_items()
        if selector == 'button':
            return self._douyin_openers()
        return []

    def execute_script(self, script, *args):
        if 'replyContainer' in script:
            # The panel structural read: every mounted comment-item as {own, replies}.
            return self._douyin_readings()
        if 'data-dy-tried' in script and 'setAttribute' in script:
            # The tried-mark: stamp the expander's item once; False if already tried (never re-click).
            parent = getattr(args[0], '_parent', None) if args else None
            if parent is None:
                return True
            if getattr(parent, '_tried', False):
                return False
            parent._tried = True
            return True
        if 'data-dy-tried' in script:
            # The untried check: is there a thread not yet attempted?
            return any(
                getattr(it, '_replies', None) and not getattr(it, '_tried', False) for it in self._mounted_items()
            )
        if 'semi-toast' in script or 'semi-modal' in script:
            # The failure-popup dismissal: the fixture models no blocking dialog, so nothing to clear.
            return 'none'
        if 'feed-video-nickname' in script:
            # The overlay read is scoped to the active slide; it MUST pass feed-active-video as the
            # root. Returning the neighbour's/global facts for any other root is exactly the mix-up
            # the docs warn about, so an un-scoped reader gets nothing rather than wrong data.
            scoped = args and args[0] == DouyinCrawler.ACTIVE_SLIDE
            return self._modal_facts() if (self._modal_id and scoped) else {}
        if 'documentURI' in script:
            return self.document_uri
        if 'innerText' in script and args:
            return getattr(args[0], 'text', '')
        if 'scrollBy' in script:
            self.scrolls += 1
            self.window_scrolls += 1
            if '/video/' in self.current_url:
                # Scrolling a video page reveals that player's recommendations, never more
                # result cards — which is what the walk's second pass must not mistake for a
                # list that kept paying out.
                self.detail_scrolls += 1
                return None
            if self.scroll_batches:
                self.cards = self.cards + self.scroll_batches.pop(0)
            return None
        if 'scrollTop' in script or 'scrollHeight' in script:
            # The comment panel's own scroller (the endpoint is signed, so the
            # panel is walked by DOM), and the profile grid's, which is what
            # ``engine.feed.jump_to_bottom`` hunts for.
            self.scrolls += 1
            if self.moves_on_scroll and self.scrolls == 1:
                self.current_url = self.moves_on_scroll
            if 'scrollerFrom' in script:
                self.container_jumps += 1
                if '/user/' in self.current_url and self.grid_batches:
                    self.grid = self.grid + self.grid_batches.pop(0)
            return 'container'
        if 'video-player-digg' in script:
            asked = douyin_id(self.current_url)
            return dict(self.facts_by_id.get(asked, self.facts))
        return None

    def execute_async_script(self, script, *args):
        # The board's in-page fetch. It has to be told apart from the dismissal script
        # by shape, because both arrive here: the fetch bridge is the only one that
        # names ``fetch(``.
        if 'fetch(' in script:
            self.fetched.append(script)
            return self.board
        # The prompt-dismissal script: it reports 取消 when the dialog is up, and
        # nothing at all when it is not — which is the cheap case.
        if self.dialog:
            self.dialog = False
            self.dismissals += 1
            return json.dumps({'clicked': '取消', 'matched': '是否保存登录信息超过5天', 'seen': ['取消', '保存']})
        return json.dumps({'clicked': None, 'matched': None, 'seen': []})

    def set_script_timeout(self, seconds):
        pass

    def quit(self):
        pass


def _default_facts():
    return {
        'digg': '5.9万',
        'comment': '2099',
        'collect': '9241',
        'share': '7839',
        'info': INFO_TEXT,
        'publish': '发布时间：2026-08-04 16:32',
        'related': RELATED_TEXT,
    }


@pytest.fixture
def make_crawler(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(**kwargs):
        driver = FakeDriver(**kwargs)

        def fake_create(self, *args, **kw):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return DouyinCrawler(headless=True), driver

    return _make


class TestPureHelpers:
    def test_id_from_every_link_shape(self):
        assert douyin_id(f'https://www.douyin.com/video/{ID}') == ID
        assert douyin_id(f'https://www.douyin.com/root/video/{ID}?modal_id={ID}') == ID
        assert douyin_id(f'https://v.douyin.com/x/?modal_id={ID}') == ID
        assert douyin_id(ID) == ID
        assert douyin_id('https://www.douyin.com/jingxuan') == ''
        assert douyin_id('') == ''

    def test_the_overlay_publish_date_accepts_only_a_full_calendar_date(self):
        """The overlay has no dedicated publish node — its date hides inside ``video-info``. Only a
        year-bearing date is trusted; a hashtag, a relative word, or a year-less fragment stays blank
        rather than landing a value that sorts as a timestamp but is not one (the 播放数 rule again)."""
        pub = DouyinCrawler._publish_from_info
        assert pub('@白水 · 2025年11月12日 #镇平五朵山') == '2025年11月12日'
        assert pub('@白水 · 2026-08-04 #tag') == '2026-08-04'
        assert pub('@白水 · #2025年高考 #倒计时100天') == '', 'a hashtag whose digits look like a year'
        assert pub('@白水 · 刚刚') == '' and pub('@白水 · 3天前') == '', 'relative stamps rot once stored'
        assert pub('@白水 · 2月25日 #tag') == '', 'no year is not comparable with the year-bearing rows'
        assert pub('') == '' and pub(None) == ''

    def test_counts_honour_the_chinese_units(self):
        # The parser itself lives in ``crawlers.engine.counters`` (every platform
        # shares it now); these are douyin's own label shapes, kept here so a
        # change to the shared parser that breaks douyin still fails loudly here.
        assert parse_count('5.9万') == 59000 and parse_count('1.8万') == 18000
        assert parse_count('2099') == 2099 and parse_count('1千') == 1000
        assert parse_count('分享') == 0 and parse_count('') == 0 and parse_count(None) == 0 and parse_count(12) == 12

    def test_publish_label_is_stripped(self):
        assert _clean_publish('发布时间：2026-08-04 16:32') == '2026-08-04 16:32'
        assert _clean_publish('2026-08-04') == '2026-08-04'

    def test_author_block_is_split_on_its_labels_not_positions(self):
        author, followers, liked = _author_from_related(RELATED_TEXT)
        assert author == '泫九' and followers == 1670000 and liked == 11575000
        assert _author_from_related('没有这个结构') == ('', 0, 0)

    def test_comment_fields_are_read_by_shape(self):
        author, content, when, region, likes, subs = douyin_comment_fields(COMMENT_BLOCK)
        assert (author, content) == ('盖世英雄小行者', '作者的脑洞太强大了，这才叫科幻')
        assert when == '1月前' and region == '北京' and likes == 5 and subs == 1

    def test_comment_fields_tolerate_a_sparse_block(self):
        author, content, when, region, likes, subs = douyin_comment_fields('路人\n只有一句话')
        assert (author, content, when, likes, subs) == ('路人', '只有一句话', '', 0, 0)
        assert douyin_comment_fields('') == ('', '', '', '', 0, 0)

    def test_a_wrapped_comment_keeps_every_line_and_its_own_numbers(self):
        """A comment that wraps is one comment, not a first line plus a lost tail.

        The text used to be ``lines[1]``, so the second line of a wrapped comment disappeared (「不漏采」
        is the whole purpose of this table) and a number the commenter typed on its own line was read as
        点赞数 by the bare-digit rule — a figure under a plausible column name that nobody on the page
        ever claimed was a like count.
        """
        author, content, when, region, likes, subs = douyin_comment_fields(
            '路人\n第一行\n114514\n第二行\n1天前·广东\n7'
        )
        assert content == '第一行\n114514\n第二行', content
        assert (author, when, region, likes, subs) == ('路人', '1天前', '广东', 7, 0)

    def test_a_timestamp_is_never_filed_as_the_comment_text(self):
        """The block shape that used to write 「1天前·北京」 into 评论内容: the time line is the anchor.

        An author whose name renders empty collapses its line (the docstring's own case), and index-based
        reading then shifted every field up one — the row kept a plausible 楼层 while its text column held
        a timestamp. Nothing is invented in its place: the text stays empty and the caller drops the row,
        which costs a line and does not buy a lie.
        """
        author, content, when, region, likes, subs = douyin_comment_fields('路人\n1天前·北京\n5')
        assert (when, region, likes) == ('1天前', '北京', 5)
        assert content == '', f'the anchor line was filed as the comment: {content!r}'

    def test_douyin_links_route_to_the_douyin_adapter(self):
        assert platform_for(f'https://www.douyin.com/video/{ID}') == 'douyin'
        assert platform_for('https://v.douyin.com/abc/') == 'douyin'
        assert platform_for('https://www.iesdouyin.com/share/video/1') == 'douyin'

    def test_an_author_is_addressed_by_profile_link_or_token_only(self):
        sec = 'MS4wLjABAAAAehSj560Se_lTjmmy0imDx_2qKW_Lj8zS45rbZriU62h5ADwatvOxdaZ8lu_SjOGD'
        assert douyin_sec_uid(f'https://www.douyin.com/user/{sec}') == sec
        assert douyin_sec_uid(f'https://www.douyin.com/user/{sec}?from_tab_name=main') == sec
        assert douyin_sec_uid(f'www.douyin.com/user/{sec}/') == sec
        assert douyin_sec_uid(sec) == sec
        # A display name is what people type first and it addresses nobody; opening
        # a guessed profile would report "this author posted nothing" about a page
        # that belongs to someone else.
        assert douyin_sec_uid('泫九') == ''
        assert douyin_sec_uid('https://www.douyin.com/jingxuan') == ''
        assert douyin_sec_uid('') == ''


class TestVideoDetail:
    """One video page read straight through :meth:`get_detail`.

    These are the row-level facts the *author* and comment paths share (the counters
    that name themselves, the author-by-link fallback, the swapped-page and per-row-wall
    refusals), so they stay pinned after the keyword-search mode was removed — driven by
    the entry point that still exists rather than by a walk through the search list.
    """

    def test_rows_carry_only_the_counters_that_name_themselves(self, make_crawler):
        crawler, _driver = make_crawler(cards=[ID])
        row = crawler.get_detail(f'https://www.douyin.com/video/{ID}')
        assert row['点赞数'] == 59000 and row['评论数'] == 2099
        assert row['收藏数'] == 9241 and row['转发数'] == 7839
        assert row['发布时间'] == '2026-08-04 16:32'
        assert row['作者'] == '泫九' and row['粉丝数'] == 1670000
        assert row['正文'] == '归墟第十二集 #归墟 #末日 #科幻'
        assert row['链接'] == f'https://www.douyin.com/video/{ID}'

    def test_a_page_that_names_its_author_by_link_still_fills_the_column(self, make_crawler):
        """U42: this build names its author on a link and drops the related-video block.

        Measured 2026-09-28 (``backend/test_dy_author.py``): a video page carries
        ``a[href="https://www.douyin.com/user/MS4w…"]`` whose text is the nickname, and
        ``[data-e2e="related-video"]`` — the only place the old reader looked — is **not rendered**.
        So every row stored ``作者=''`` and the nameless-page guard never fired, because the publish
        time is present. A blank column nobody announces is the same failure as a zero nobody notices.

        The two creator totals are asserted as ``''`` on purpose: the page publishes the *words*
        粉丝/获赞 as nav labels and no figure, so 0 would be a count of something nobody counted.
        """
        crawler, _driver = make_crawler(
            cards=[ID],
            facts_by_id={
                ID: {
                    **_default_facts(),
                    'related': '',
                    'author': '泫九',
                }
            },
        )
        row = crawler.get_detail(f'https://www.douyin.com/video/{ID}')
        assert row['作者'] == '泫九', row
        assert row['粉丝数'] == '' and row['获赞数'] == '', f'a missing figure must not be filed as 0: {row}'
        assert row['点赞数'] == 59000, 'the counters that ARE on the page keep reading'

    def test_no_play_count_column_exists_on_douyin(self, make_crawler):
        """Measured: detail-video-info's second number IS the like counter, and
        the web player never shows plays. Publishing 播放数 would be a wrong
        figure wearing a plausible column name."""
        crawler, _driver = make_crawler(cards=[ID])
        row = crawler.get_detail(f'https://www.douyin.com/video/{ID}')
        assert '播放数' not in row

    def test_a_video_that_renders_nothing_is_skipped_not_stored(self, make_crawler):
        crawler, _driver = make_crawler(cards=[ID, '7678996507694094827'], video_body='加载中')
        assert crawler.get_detail(f'https://www.douyin.com/video/{ID}') is None

    def test_a_page_that_published_only_its_counter_bar_is_not_data(self, make_crawler, caplog):
        """Measured live 2026-09-26: the opened video page gave its counter bar and nothing
        else — id, 点赞 300, 评论 11, no author, no 发布时间, no 文案. Counted as a valid row,
        that shape filled a 2-row target with two blank lines, and the live tier caught it as a
        row without a title. Only a *caption-less* video is legitimately text-free, and one of
        those still states its author and its date.
        """
        blank = {**_default_facts(), 'info': '', 'publish': '', 'related': ''}
        crawler, _driver = make_crawler(cards=[ID], facts=blank)
        assert crawler.get_detail(f'https://www.douyin.com/video/{ID}') is None
        assert t('crawl.dy.detailNoIdentity', i=ID) in ' '.join(_lines(caplog)), _lines(caplog)

    def test_a_name_is_not_identity_when_the_page_published_nothing(self, make_crawler, caplog):
        """The 2026-09-28 half of the same measurement: a *named* blank row is still a blank row.

        Live cell A1 filed ``7687166416143123826`` with no 标题, no 正文, no 发布时间 and four zero
        counters, and counted it as 「当前有效数据: 7 条」 — the page was still hydrating, the author reader
        had picked up a recommendation-rail account, and the old guard accepted any row carrying an author
        **or** a date. Probing that same address seconds later returned a caption, an author and a date, so
        the blank was a race, and a race must cost a retry, not a row of the user's target.
        """
        blank = {**_default_facts(), 'info': '', 'publish': '', 'author': '青小鲜三门青蟹 海鲜礼包'}
        crawler, _driver = make_crawler(cards=[ID], facts=blank)
        assert crawler.get_detail(f'https://www.douyin.com/video/{ID}') is None, 'a named blank row is still blank'
        assert t('crawl.dy.detailNoIdentity', i=ID) in ' '.join(_lines(caplog)), _lines(caplog)

    def test_a_detail_page_that_answers_with_another_video_files_nothing(self, make_crawler, caplog):
        """Asked for one video, served another: the row is refused, not filed under the asked link.

        Measured 2026-09-28 on ``7664182466315794939`` (a 图文 id): the browser ended on
        ``/video/7029265830722489634`` — a fully-published, entirely unrelated video — so every field the
        reader would have taken (文案, 发布时间, the four counters, the author) belonged to somebody else.
        The table would have claimed it was the link the list handed over. The user saw this on screen
        before any test did.
        """
        other = '7678996507694094827'
        asked = f'https://www.douyin.com/video/{ID}'
        crawler, _driver = make_crawler(
            cards=[ID],
            redirects={asked: f'https://www.douyin.com/video/{other}'},
        )
        assert crawler.get_detail(asked) is None, 'a swapped page must not be filed under the asked id'
        said = ' '.join(_lines(caplog))
        assert t('crawl.dy.detailSwapped', i=ID, shown=other) in said, said

    def test_a_row_the_captcha_interstitial_refuses_says_so_and_does_not_accuse_the_session(self, make_crawler, caplog):
        """A per-row wall is named as a wall, and it does not latch ``login_wall``.

        Measured 2026-09-28: 15 of 39 detail pages on one keyword were 图文 posts the site answers with
        「验证码中间页」, while the video pages around them round-trip fine. Saying 「没有渲染出数据» about that
        points the repair at the parser; latching the session flag about it would settle the whole node as
        「COOKIE 可能过期」. Both are wrong, and this row is the difference.
        """
        crawler, _driver = make_crawler(cards=[ID], title='验证码中间页', video_body='')
        assert crawler.get_detail(f'https://www.douyin.com/video/{ID}') is None, 'a captcha plate is not a row'
        assert crawler.login_wall is False, 'one refused card must not be read as the session dying'
        said = ' '.join(_lines(caplog))
        assert t('crawl.dy.detailWalled', i=ID) in said, said
        assert t('crawl.dy.detailEmpty', i=ID) not in said, f'the wall was reported as an empty page: {said}'

    def test_a_video_with_no_caption_is_still_one_row(self, make_crawler):
        """The gate is identity, not prose: a clip with no 文案 has nothing to put in that column,
        and refusing those would drop real data over one empty cell."""
        crawler, _driver = make_crawler(cards=[ID], facts={**_default_facts(), 'info': ''})
        row = crawler.get_detail(f'https://www.douyin.com/video/{ID}')
        assert row is not None, 'an author and a publish time make this a row'
        assert row['正文'] == '' and (row['作者'] or '').strip()


SEC = 'MS4wLjABAAAAehSj560Se_lTjmmy0imDx_2qKW_Lj8zS45rbZriU62h5ADwatvOxdaZ8lu_SjOGD'
OTHER = '7678996507694094827'


class TestAuthorProfile:
    """One creator's own 作品 grid, which pages off a container the window cannot move."""

    def test_the_profile_is_opened_once_and_its_grid_is_paged(self, make_crawler):
        crawler, driver = make_crawler(cards=[], grid=[ID], grid_batches=[[OTHER]], works='2')
        rows = crawler.author(SEC, target_count=5)
        assert [str(row['视频ID']) for row in rows] == [ID, OTHER]
        assert driver.visited[0] == DouyinCrawler.PROFILE_ENTRY.format(sec=SEC)
        assert len([u for u in driver.visited if '/user/' in u]) == 1, 'the grid is one navigation, then scrolls'

    def test_the_author_reads_each_row_through_the_overlay_without_a_video_navigation(self, make_crawler):
        """The #1 风控 fix in code: a row is read by clicking its card (same-document overlay at
        ``?modal_id=``) and dismissing with ESC — NO ``/video/<id>`` navigation per row, which is the
        page-load storm that drew the captcha. Fields come from the active slide's own names, and the
        overlay is closed after every row so the next card is clickable."""
        crawler, driver = make_crawler(cards=[], grid=[ID], grid_batches=[[OTHER]], works='2')
        rows = crawler.author(SEC, target_count=2)
        assert [str(r['视频ID']) for r in rows] == [ID, OTHER]
        assert not any('/video/' in u for u in driver.visited), f'author must not navigate to /video: {driver.visited}'
        assert len([u for u in driver.visited if '/user/' in u]) == 1, 'one profile navigation; the rest is clicks'
        first = rows[0]
        # Read off the overlay: caption is 正文, the @-name loses its @, the date is parsed from
        # video-info (coarser than the old page — a date, not a timestamp), and the account totals
        # are NOT in the slide → blank, never a fabricated 0.
        assert first['正文'].startswith('归墟第十二集')
        assert first['作者'] == '测试作者'
        assert first['发布时间'] == '2026-08-04'
        assert first['点赞数'] == 59000 and first['评论数'] == 2099
        assert first['粉丝数'] == '' and first['获赞数'] == '', 'profile published no totals in this fixture'
        assert driver._modal_id == '', 'every row read left the overlay dismissed'

    def _author_shape(self, crawler, monkeypatch, *, modal_deferred, list_end, seeded_rows, walled=False):
        """Drive ``author`` to a fixed end-state: the grid arrived and drained, N rows landed, and
        ``modal_deferred`` cards' overlays would not open. White-box on purpose — the rule under test
        is the end-of-walk decision, so everything before it is stubbed to the measured shape.
        """

        def _walk(*_a, **_k):
            crawler._modal_deferred = modal_deferred
            crawler._list_end_attested = list_end

        for name, value in {
            'open': lambda *_a, **_k: True,
            '_dismiss_prompts': lambda *_a, **_k: None,
            '_published_count': lambda: 145,
            '_wait_for_grid': lambda timeout=None: {'arrived': True, 'waited': 0.0, 'verdict': '', 'gave_up': 0},
            '_is_walled': lambda: walled,
            'may_stop': lambda: False,
            '_open_each': _walk,
        }.items():
            monkeypatch.setattr(crawler, name, value)
        crawler._collected = list(seeded_rows)

    def test_an_author_walk_of_zero_with_all_overlays_deferred_convicts_rather_than_site_end(
        self, make_crawler, monkeypatch
    ):
        """The live-exposed gap: the grid arrived and paged, but NO overlay opened → 0 rows. That is a
        failed read, not the site running out — convict it (``UNDER_TARGET``, resumable) rather than
        let the list's 「没有更多了」 license an empty as ``site_end`` / settle 完成."""
        crawler, _driver = make_crawler(cards=[])
        self._author_shape(crawler, monkeypatch, modal_deferred=12, list_end=True, seeded_rows=[])
        rows = crawler.author(SEC, target_count=12)
        assert rows == [], 'nothing was collected'
        assert crawler.risk_blocked is False, 'no captcha was seen, so this is not 风控 — it is a failed read'
        assert crawler.end_reason == UNDER_TARGET, 'convicted, never whitewashed by the list-end marker'

    def test_a_zero_with_deferred_cards_and_a_captcha_is_risk_not_under_target(self, make_crawler, monkeypatch):
        """Same 0-row shape, but a captcha appeared *during* the walk (clean page open, wall shows
        later): that is 风控 (back off), not a convictable shortfall. Driven by stubbing the open-time
        wall off and the end-time wall on, which is the only way to reach that branch."""
        crawler, _driver = make_crawler(cards=[])
        calls = {'n': 0}

        def _wall_later():
            calls['n'] += 1
            return calls['n'] >= 2  # False at author's page-open check, True by the end decision

        self._author_shape(crawler, monkeypatch, modal_deferred=12, list_end=True, seeded_rows=[])
        monkeypatch.setattr(crawler, '_is_walled', _wall_later)
        rows = crawler.author(SEC, target_count=12)
        assert rows == []
        assert crawler.risk_blocked is True, 'a captcha mid-read is 风控'
        assert crawler.end_reason is None, 'risk is not a licensing/conviction verdict — the gate skips it'

    def test_a_partial_author_walk_with_deferred_cards_is_not_convicted(self, make_crawler, monkeypatch):
        """A crawl that DID collect some rows and merely deferred a few 图文 cards is not a failed
        read — it keeps its ``site_end`` license and must never be convicted or called 风控."""
        crawler, _driver = make_crawler(cards=[])
        seeded = [{'视频ID': ID, '标题': 't'}]
        self._author_shape(crawler, monkeypatch, modal_deferred=3, list_end=True, seeded_rows=seeded)
        rows = crawler.author(SEC, target_count=12)
        assert len(rows) == 1
        assert crawler.risk_blocked is False and crawler.end_reason == 'site_end'

    def test_the_harvest_loop_waits_on_its_own_list_not_on_the_search_route(self, make_crawler, monkeypatch):
        """A remount wait belongs to the list being read, not to whichever route mounted first.

        :meth:`_wait_for_page` is the search route's mount wait — it polls the **search** anchors and is
        prepared to spend ``Config.PAGE_WAIT_TIMEOUT`` doing it. The first version of the empty-screen
        retry called it from the shared harvest loop, so an author grid whose first read came back empty
        would park for minutes on a page that cannot answer it, and the loop re-reads through its own
        ``read_ids`` afterwards anyway: the wait bought nothing even when it returned.
        """
        crawler, _driver = make_crawler(cards=[ID])
        monkeypatch.setattr(
            DouyinCrawler,
            '_wait_for_page',
            lambda self: pytest.fail("the harvest loop borrowed the search route's patient mount wait"),
        )
        # The first read is the empty one; every later read (including the ones the remount wait itself
        # makes) sees the card, which is what the wait is for.
        reads = iter([[], *([[ID]] * 8)])
        pool, drained, screens = crawler._harvest_pool(lambda: list(next(reads)), lambda: False, set(), 1)
        assert pool == [ID], pool
        assert screens == 1, f'the empty read cost a screen: {screens}'

    def test_the_container_is_jumped_because_the_window_moves_nothing_here(self, make_crawler):
        """Measured: a window scroll on a profile page grows the footer's
        recommended-video links (8 → 29) and leaves the 作品 grid untouched, which a
        count-based walk reports as an exhausted list at 57 of 85."""
        crawler, driver = make_crawler(cards=[], grid=[ID], grid_batches=[[OTHER]], works='2')
        crawler.author(SEC, target_count=2)
        assert driver.container_jumps >= 1
        assert driver.window_scrolls == 0, 'the window is the wrong surface on this page'

    def test_the_grid_is_paged_up_before_the_first_video_takes_the_page_away(self, make_crawler):
        """The author walk shares the search walk's failure (#146): its grid is a document too,
        and opening one 作品 replaced it — so a target deeper than the mounted grid was unreachable.
        """
        third = '7684552351918689571'
        crawler, driver = make_crawler(cards=[], grid=[ID, OTHER], grid_batches=[[third]], works='3')

        rows = crawler.author(SEC, target_count=3)

        assert [str(row['视频ID']) for row in rows] == [ID, OTHER, third]
        assert driver.detail_scrolls == 0, 'the grid was paged from a video page, which has none'
        assert driver.window_scrolls == 0, 'and it is still the container that pages a profile, not the window'

    def test_the_numbers_come_from_the_overlay_not_from_the_card(self, make_crawler):
        """The counters are not on the grid card — they come from reading the opened video (now the
        in-page overlay). The overlay names its author on ``feed-video-nickname`` (leading ``@`` lost)
        and its date inside ``video-info`` — coarser than the old ``/video`` page (a date, not a
        timestamp) — and the account 粉丝/获赞 are not on the slide at all, so they come from the profile."""
        crawler, _driver = make_crawler(cards=[], grid=[ID], works='1')
        row = crawler.author(f'https://www.douyin.com/user/{SEC}?from_tab_name=main', target_count=1)[0]
        assert row['点赞数'] == 59000 and row['评论数'] == 2099 and row['收藏数'] == 9241 and row['转发数'] == 7839
        assert row['作者'] == '测试作者' and row['发布时间'] == '2026-08-04'
        assert row['视频ID'] == ID and '播放数' not in row

    def test_a_profile_that_publishes_zero_works_is_an_answer_not_a_failure(self, make_crawler):
        crawler, driver = make_crawler(cards=[], grid=[], grid_batches=[[ID]], works='0')
        assert crawler.author(SEC, target_count=5) == []
        assert driver.container_jumps == 0, 'the page said it holds nothing; there is nothing to page'

    def test_a_grid_that_never_mounts_refuses_and_quotes_its_own_count(self, make_crawler):
        crawler, _driver = make_crawler(cards=[], grid=[], works='85')
        with pytest.raises(RuntimeError) as err:
            crawler.author(SEC, target_count=5)
        assert '85' in str(err.value), 'the refusal has to say the list is missing, not that it is empty'

    def test_a_page_that_shows_no_count_is_not_read_as_an_author_who_never_posted(self, make_crawler):
        """The shared counter parser answers an empty string with 0, and 0 is a
        claim about the author. A profile whose numbers never arrived has to refuse
        as itself, not become "this person has no works"."""
        crawler, _driver = make_crawler(cards=[], grid=[], works='')
        assert crawler._published_count() == -1
        with pytest.raises(RuntimeError) as err:
            crawler.author(SEC, target_count=5)
        assert '作品数' in str(err.value) or 'post count' in str(err.value)

    def test_a_grid_that_works_without_a_count_still_delivers_rows(self, make_crawler):
        """A missing count is the page being shy about a number, not the crawl
        failing: the rows are collected, and the closing line simply has no
        published figure to claim the walk reached."""
        crawler, _driver = make_crawler(cards=[], grid=[ID], works='')
        rows = crawler.author(SEC, target_count=2)
        assert [str(row['视频ID']) for row in rows] == [ID]

    def test_a_captcha_interstitial_refuses_the_run(self, make_crawler):
        crawler, driver = make_crawler(cards=[], grid=[ID], works='1', title='验证码中间页')
        with pytest.raises(RuntimeError) as err:
            crawler.author(SEC, target_count=3)
        assert '验证码' in str(err.value)
        assert driver.visited == [DouyinCrawler.PROFILE_ENTRY.format(sec=SEC)]

    def test_the_budget_stops_the_walk_before_the_next_batch(self, make_crawler):
        crawler, driver = make_crawler(cards=[], grid=[ID, OTHER], grid_batches=[[ID]], works='3')
        rows = crawler.author(SEC, target_count=1)
        assert len(rows) == 1
        assert driver.container_jumps == 0, 'a scroll that waits for rows nobody asked for is wasted time'

    def test_a_resumed_walk_skips_the_videos_it_already_opened(self, make_crawler):
        crawler, driver = make_crawler(cards=[], grid=[ID, OTHER], grid_batches=[[ID]], works='2')
        crawler.seed([{'视频ID': ID, '链接': f'https://www.douyin.com/video/{ID}'}])
        rows = crawler.author(SEC, target_count=3)
        assert [str(row['视频ID']) for row in rows] == [ID, OTHER]
        assert len([u for u in driver.visited if f'/video/{ID}' in u]) == 0, 'a paid-for video is not opened twice'

    def test_something_that_is_not_a_profile_is_refused_before_a_page_opens(self, make_crawler):
        crawler, driver = make_crawler(cards=[])
        for value in ('', '   ', '泫九', f'https://www.douyin.com/video/{ID}'):
            with pytest.raises(ValueError):
                crawler.author(value, target_count=2)
        assert driver.visited == []


class _FakeActionChains:
    """Stand-in for selenium ActionChains: ``perform`` runs the queued click on the element it was moved
    to, which triggers the element's ``on_click`` (the fake's expansion hook). Lets a unit test drive the
    product's real-click path without a browser.
    """

    def __init__(self, driver):
        self._el = None

    def move_to_element(self, el):
        self._el = el
        return self

    def pause(self, *a):
        return self

    def click(self):
        if self._el is not None:
            self._el.click()
        return self

    def perform(self):
        pass


class TestComments:
    def _session(self, driver):
        return CommentSession(driver, log=lambda m: None, nap=lambda s: None)

    def test_the_panel_is_scrolled_and_rows_deduped(self, make_crawler):
        crawler, driver = make_crawler(cards=[])
        session = self._session(driver)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK
        assert [r['评论者'] for r in rows] == ['盖世英雄小行者', '路人']
        assert driver.scrolls >= 1, 'the panel only grows by scrolling its own container'
        assert rows[0]['子回复数'] == 1 and rows[0]['评论地区'] == '北京'
        assert rows[0]['平台'] == 'douyin' and rows[0]['文章URL'].endswith(ID)

    def test_a_reply_thread_is_expanded_and_its_reply_filed_under_the_parent(self, make_crawler, monkeypatch):
        """The reply thread is OPENED with a real click, and its reply becomes a row with 父楼层.

        ``_expand_douyin_reply_threads`` uses ``ActionChains`` because only a native click moves
        douyin's React handler (measured on the profile). A fake ActionChains here performs the click
        on the opener, which marks the thread expanded so the next panel read returns its reply —
        proving the product reads replies it actually opened, not a declared count.
        """

        class FakeActionChains:
            def __init__(self, driver):
                self._el = None

            def move_to_element(self, el):
                self._el = el
                return self

            def pause(self, *a):
                return self

            def click(self):
                if self._el is not None:
                    self._el.click()
                return self

            def perform(self):
                pass

        monkeypatch.setattr('crawlers.comments.ActionChains', _FakeActionChains)
        parent = El('路人甲\n主评论\n1天前·北京\n2\n展开1条回复', replies=['路人乙\n子回复\n1天前·上海\n0'])
        crawler, driver = make_crawler(cards=[], comment_items=[parent], comment_count='0')
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK, status
        assert [r['评论者'] for r in rows] == ['路人甲', '路人乙'], rows
        assert [r['楼层'] for r in rows] == [1, 2]
        assert rows[1]['父楼层'] == 1 and rows[0]['父楼层'] == ''
        # 子回复数 is the captured reply (实际子行数), and the parent keeps its own body — not the reply's.
        assert rows[0]['子回复数'] == 1 and rows[0]['评论内容'] == '主评论'
        assert rows[1]['评论内容'] == '子回复' and rows[1]['评论地区'] == '上海'

    def test_a_failed_expand_is_tried_once_then_skipped_not_retried(self, make_crawler, monkeypatch):
        """A thread that only pops 「评论已删除 / 不可见」 is uncrawlable — tried ONCE, never re-clicked.

        The opener's click does not render replies (``_expandable=False``), the way a deleted/hidden
        comment behaves live. The walk must file only the parent (with its declared 子回复数), not hang or
        re-click — the ``data-dy-tried`` mark guarantees a single attempt, and the untried-exit lets the
        walk finish with that one thread left unopened.
        """
        monkeypatch.setattr('crawlers.comments.ActionChains', _FakeActionChains)
        dead = El('甲\n主评论\n1天前·北京\n0\n展开2条回复', replies=['x', 'y'])
        dead._expandable = False
        crawler, driver = make_crawler(cards=[], comment_items=[dead], comment_count='0')
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK, status
        assert len(rows) == 1, f'a thread that will not open yields only its parent: {rows}'
        assert rows[0]['子回复数'] == 2, "a non-expanded parent keeps the site's declared count, not 0"
        assert rows[0]['父楼层'] == ''
        assert getattr(dead, '_tries', 0) == 1, f'the failed thread was clicked more than once: {dead._tries}'

    def test_a_link_without_an_id_is_dead_and_costs_no_navigation(self, make_crawler):
        crawler, driver = make_crawler(cards=[])
        session = self._session(driver)
        rows, status = session.crawl_douyin('https://www.douyin.com/jingxuan', 5)
        assert rows == [] and status == DEAD
        assert driver.visited == []

    def test_a_panel_that_never_shows_items_is_not_reported_as_success(self, make_crawler):
        """Measured on the live site: the list container mounts before its first
        comment renders. Reading zero rows right then used to return ``ok`` with
        an empty table for a video reporting 6 295 comments — the exact shape of
        false data this project refuses.
        """
        crawler, driver = make_crawler(cards=[], comment_items=[])
        session = self._session(driver)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 40)
        assert rows == []
        assert status == BLOCKED, 'a video with a non-zero counter and no readable list is a failed read'

    def test_a_video_that_really_has_no_comments_is_an_answer(self, make_crawler):
        crawler, driver = make_crawler(cards=[], comment_items=[], comment_count='0')
        session = self._session(driver)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 40)
        assert rows == [] and status == OK

    def test_items_that_yield_no_readable_text_are_a_failure_too(self, make_crawler):
        # The panel is full of nodes; not one of them carries comment text.
        crawler, driver = make_crawler(cards=[], comment_items=[El(''), El('   ')])
        session = self._session(driver)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 40)
        assert rows == [] and status == BLOCKED

    def test_a_blocked_page_never_becomes_an_empty_table(self, make_crawler):
        crawler, driver = make_crawler(cards=[], video_body='当前请求存在异常，暂时限制访问')
        session = self._session(driver)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 5)
        assert rows == [] and status == BLOCKED

    def test_the_floor_number_runs_across_the_panel_not_down_one_screen_at_a_time(self, make_crawler):
        """The panel lazy-fills; 楼层 is a running number over the whole thread.

        ``parse_douyin_threads`` numbers the whole panel, and the walk used to
        hand it one scroll round at a time — so a video read across two screens stored ``1,2,1,2`` and
        nothing in the table said which screen a row came from. Measured shape (live site, 2026-09-28):
        the second screen *contains* the first, because the list is a document, not a page.
        """
        first = [El(COMMENT_BLOCK), El('路人\n第二条评论\n3天前·广东\n1')]
        second = first + [El('第三个人\n第三条内容\n2天前·上海\n4'), El('第四个人\n第四条内容\n1天前·广州\n2')]
        crawler, driver = make_crawler(cards=[], comment_pages=[first, second])
        session = self._session(driver)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK
        assert [row['楼层'] for row in rows] == [1, 2, 3, 4], f'楼层 restarted per screen: {rows}'
        assert len({str(row['评论内容']) for row in rows}) == 4, 'the second screen re-filed the first'

    def test_a_thread_is_walked_to_its_end_not_to_a_round_count(self, make_crawler):
        """No walk carries a budget (AGENTS) — measured against the live site as U43.

        The panel loop used to be ``for _round in range(40)``. On a video whose own counter reads 3388 the
        live walk stopped at 406 rows because its fortieth screen came and went, and returned ``OK``:
        the site never said the thread was over, this file's constant did.
        """
        screens = []
        for total in range(1, 46):
            screens.append([El(f'路人{i}\n第{i}条内容\n1天前·北京\n0') for i in range(total)])
        crawler, driver = make_crawler(cards=[], comment_pages=screens, comment_count='0')
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK
        assert len(rows) == 45, f'the walk stopped at {len(rows)} of 45 screens — a round budget is back'
        assert [row['楼层'] for row in rows] == list(range(1, 46)), '楼层 must run with the screens'

    def test_a_panel_that_ends_short_of_the_counters_number_names_the_gap(self, make_crawler):
        """The gap is said with the site's own denominator, and the nested replies are not stolen from it.

        Measured 2026-09-28: 3388 declared, 406 rows, Σ子回复数 1062 — so a completion test that compared
        rows with 3388 would cry 「还差 2982 条」 on a walk that had read every top-level comment the panel
        gives. The line therefore reports all four figures and compares against ``declared - nested``.
        """
        screens = [[El('路人1\n第一条\n1天前·北京\n0'), El('路人2\n第二条\n1天前·上海\n3\n展开3条回复')]]
        crawler, driver = make_crawler(cards=[], comment_pages=screens, comment_count='99')
        said: list = []
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert len(rows) == 2 and rows[1]['子回复数'] == 3
        # The scroll that grew nothing ended this walk (single screen, so the panel never grew), and the
        # line says so: a gap without its exit reason reads as 「the site has no more」 either way.
        assert t(
            'comment.dyShort',
            url=f'https://www.douyin.com/video/{ID}',
            declared=99,
            rows=2,
            nested=3,
            gap=94,
            reason=stop_reason_label('stuck'),
        ) in ' '.join(said), said

    def test_a_walk_cut_short_by_the_stop_button_blames_the_stop_not_the_site(self, make_crawler):
        """The user's 停止 is a different fact about the same gap, and the line must carry it.

        Measured shape: a 3388-comment thread whose panel is still growing when 停止 arrives. The gap is
        real in both cases, but only one of them says the site ran dry — and the second round of the audit
        found the sentence claiming the panel had stopped producing new rows on a walk that stopped because
        the user pressed the button.
        """
        screens = [
            [El(f'路人{i}\n第{i}条\n1天前·北京\n0') for i in range(1, 4)],
            [El(f'路人{i}\n第{i}条\n1天前·北京\n0') for i in range(4, 7)],
        ]
        crawler, driver = make_crawler(cards=[], comment_pages=screens, comment_count='99')
        said: list = []
        session = CommentSession(driver, log=said.append, nap=lambda s: None, abort=lambda: True)
        rows, _status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert len(rows) == 3
        assert not driver.scrolls, f'the walk scrolled after the stop: {driver.scrolls}'
        assert t(
            'comment.dyShort',
            url=f'https://www.douyin.com/video/{ID}',
            declared=99,
            rows=3,
            nested=0,
            gap=96,
            reason=stop_reason_label('stopped'),
        ) in ' '.join(said), said

    def test_an_ask_that_is_met_does_not_complain_about_the_thread(self, make_crawler):
        """``limit`` is the user's ask: stopping on it is obeying, not a hole in the table."""
        screens = [[El(f'路人{i}\n第{i}条\n1天前·北京\n0') for i in range(1, 6)]]
        crawler, driver = make_crawler(cards=[], comment_pages=screens, comment_count='99')
        said: list = []
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 5)
        assert len(rows) == 5
        assert not any('comment.dyShort' in str(one) or '条未采到' in one or 'not collected' in one for one in said), (
            said
        )

    def test_a_walk_that_reads_everything_says_nothing_about_a_gap(self, make_crawler):
        screens = [[El(f'路人{i}\n第{i}条\n1天前·北京\n0') for i in range(1, 4)]]
        crawler, driver = make_crawler(cards=[], comment_pages=screens, comment_count='3')
        said: list = []
        session = CommentSession(driver, log=said.append, nap=lambda s: None)
        rows, _status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert len(rows) == 3
        assert not any('未采到' in one or 'not collected' in one for one in said), said

    def test_a_video_the_site_swaps_for_another_one_is_dead_not_walled(self, make_crawler):
        """An address the site answers with a DIFFERENT video is a dead link, not a refused session.

        Measured 2026-09-28 on ``7000000000000000001`` (three visits): the browser left
        ``/video/7000000000000000001`` for ``/jingxuan?modal_id=…``, a different substitute each time, and
        the panel never mounted. The old read logged 「该视频计有 1214 条评论」 — the *substitute's* counter —
        as BLOCKED, and the node then accused the user's cookie of expiring in the same run that crawled the
        next link's eight comments. The address is the stable half of that measurement: the 「视频不存在」
        plate appeared on one visit out of three, so it is not what the product may key on.
        """
        asked = 'https://www.douyin.com/video/7000000000000000001'
        shown = 'https://www.douyin.com/jingxuan?modal_id=7668278352603630898'
        crawler, driver = make_crawler(cards=[], comment_items=[], comment_count='1214', redirects={asked: shown})
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(asked, 8)
        assert rows == [] and status == DEAD, f'a substituted page must be DEAD, not a wall: {status!r}'
        assert driver.visited == [asked], f'the substitute was crawled as its own link: {driver.visited}'

    def test_a_real_page_that_mounts_no_panel_is_still_the_blocked_shape(self, make_crawler):
        """The contrast, so the new branch cannot swallow the old one.

        Same address, no panel, no counter: that IS the shape meaning "this session is not getting in",
        and it is what feeds 继续 and the cookie banner.
        """
        crawler, driver = make_crawler(cards=[], video_body='正在加载', comment_items=[], comment_count='')
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 8)
        assert rows == [] and status == BLOCKED, f'no panel and no substitution is a wall: {status!r}'

    def test_a_substitution_is_refused_before_the_panel_is_walked(self, make_crawler):
        """The address test runs ahead of the mount branch, not inside the 「没挂载」 arm.

        The first version of the fix only fired when the panel failed to mount, so a substituted page that
        mounted its own panel happily was still walked — and every comment of the stranger's video would
        have been stored under the link the user pasted. This is that case: items ARE present.
        """
        asked = 'https://www.douyin.com/video/7000000000000000001'
        shown = 'https://www.douyin.com/jingxuan?modal_id=7668278352603630898'
        crawler, driver = make_crawler(cards=[], redirects={asked: shown})
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(asked, 8)
        assert rows == [] and status == DEAD, f'a mounted substitute must not be walked: {status!r}'
        assert driver.scrolls == 0, 'the panel was scrolled before the address was checked'

    def test_a_panel_that_moves_halfway_through_loses_its_rows(self, make_crawler):
        """The other half: the address moves *while* the walk is running.

        Nothing collected after that belongs to the pasted link, so the whole batch is thrown away and the
        link is reported dead — a discarded walk is a re-runnable cost, filed rows under the wrong URL are
        bad data with no way back.
        """
        asked = f'https://www.douyin.com/video/{ID}'
        moved = 'https://www.douyin.com/jingxuan?modal_id=7668278352603630898'
        crawler, driver = make_crawler(cards=[], moves_on_scroll=moved)
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(asked, 40)
        assert rows == [] and status == DEAD, f"the substitute's comments were kept: {status!r} {rows[:1]}"

    def test_a_growing_panel_is_read_by_its_new_tail_not_from_the_top(self, make_crawler, monkeypatch):
        """Removing the 40-round ceiling must not make the walk O(n²).

        Every mounted node used to be read again on every round, so a long thread cost a Selenium round
        trip per already-seen comment per screen. The tail-read is only safe while the panel appends, which
        is what the next test attacks.
        """
        reads: list = []
        monkeypatch.setattr(CommentSession, '_safe_text', lambda self, item: reads.append(item.text[:4]) or item.text)
        screens = []
        for total in range(2, 12):
            screens.append([El(f'路人{i}\n第{i}条内容\n1天前·北京\n0') for i in range(total)])
        crawler, driver = make_crawler(cards=[], comment_pages=screens)
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK and len(rows) == 11, (status, len(rows))
        mounted = sum(len(one) for one in screens)
        assert len(reads) < mounted, (
            f'the walk read {len(reads)} nodes against {mounted} mounted across {len(screens)} screens: '
            'it is re-reading the whole panel every round again'
        )

    def test_a_recycled_panel_is_re_read_from_the_top(self, make_crawler):
        """The case the tail-read may not assume: the panel grew **and changed its head**.

        A virtualized list can add a node at the bottom while dropping one at the top, so the count says
        "keep going" while the cached offset now points past comments nobody parsed. The sentinel is the
        head's own text for exactly that: a changed head restarts the read, and nothing is skipped.
        """
        first = [El(f'路人{i}\n第{i}条内容\n1天前·北京\n0') for i in range(6)]
        recycled = [El(f'路人{i}\n第{i}条内容\n1天前·北京\n0') for i in range(3, 10)]
        crawler, driver = make_crawler(cards=[], comment_pages=[first, recycled, recycled])
        session = CommentSession(driver, log=lambda m: None, nap=lambda s: None)
        rows, status = session.crawl_douyin(f'https://www.douyin.com/video/{ID}', 0)
        assert status == OK
        got = {str(row['评论内容']) for row in rows}
        assert '第8条内容' in got, f'the nodes past the cached offset were skipped: {sorted(got)}'

    def test_identity_columns_stay_out_of_the_dedupe_field_lists(self):
        from services.run_store import _AUTHOR_FIELDS, _BODY_FIELDS, _URL_FIELDS

        url = f'https://www.douyin.com/video/{ID}'
        threads = {
            ('甲', '内容', '1天前'): {
                'author': '甲',
                'content': '内容',
                'when': '1天前',
                'region': '北京',
                'likes': 2,
                'subs': 1,
                'replies': {
                    ('乙', '子回复', '1天前'): {
                        'author': '乙',
                        'content': '子回复',
                        'when': '1天前',
                        'region': '',
                        'likes': 0,
                    }
                },
            }
        }
        rows, nested = parse_douyin_threads(threads, url)
        for row in rows:
            for name in row:
                assert name not in _URL_FIELDS + _AUTHOR_FIELDS + _BODY_FIELDS, name
        # Parent floor 1, its reply floor 2 pointing back at floor 1; the captured reply is the parent's
        # 子回复数 (not the declared), so nothing stays owed and nested is 0.
        assert [r['楼层'] for r in rows] == [1, 2]
        assert rows[0]['父楼层'] == '' and rows[1]['父楼层'] == 1
        assert rows[0]['子回复数'] == 1 and rows[1]['子回复数'] == 0 and nested == 0


def _entry(word='中美元首会谈', sentence='2665423', position=1, hot=12112641, views=64657293, **extra):
    """One board entry, with the keys today's answer really publishes.

    Measured twice on 2026-09-25 (``scratchpad/douyin_hot_static.json``): the list is
    ``word / position / hot_value / view_count / video_count / discuss_video_count /
    sentence_id / event_time``, and the DOM's own anchors read ``/hot/<sentence_id>/<词>``,
    which is what makes the link a link rather than a guess.
    """
    row = {
        'word': word,
        'sentence_id': sentence,
        'position': position,
        'hot_value': hot,
        'view_count': views,
        'video_count': 4,
        'discuss_video_count': 1,
        'event_time': 1790266760,
    }
    row.update(extra)
    return row


def _board(rows):
    return {'status_code': 0, 'data': {'word_list': list(rows)}}


class TestHotBoard:
    """抖音热榜, against the answer shape the endpoint was measured giving.

    What is pinned is the part that was NOT obvious from the board on screen: the crawl
    authors its own URL out of public literals (no signature at all — measured, adding a
    made-up ``webid`` changes nothing and stripping to six params loses every figure),
    it asks ONCE because one answer is the whole board, and a figure the site did not
    publish stays blank instead of becoming a 0 that reads as "counted, nothing".
    """

    def test_the_board_is_asked_from_a_loaded_hot_page(self, make_crawler):
        crawler, driver = make_crawler(cards=['1'], board=_board([_entry()]))
        rows = crawler.hot(target_count=5)
        assert driver.visited == [DouyinCrawler.HOT_ENTRY], driver.visited
        assert len(rows) == 1 and rows[0]['标题'] == '中美元首会谈'

    def test_one_answer_is_the_board_so_nothing_pages_and_nothing_is_revisited(self, make_crawler):
        # 51 entries came back from one call, measured. A second read would replay the
        # same board and a per-topic visit would pay for rows the board already gave.
        # Distinct ``sentence_id``s, because the topic id is what a row is deduped by.
        entries = [_entry(sentence='2665423', position=1), _entry(word='第二条', sentence='2665424', position=2)]
        crawler, driver = make_crawler(cards=['1'], board=_board(entries))
        rows = crawler.hot(target_count=50)
        assert len(rows) == 2
        assert len(driver.fetched) == 1, 'the board was asked more than once'

    def test_the_url_is_built_from_literals_and_carries_no_signature(self):
        lowered = DouyinCrawler.HOT_API.lower()
        for token in ('a_bogus', 'brotli', 'mistoken', 'verifyfp', 'webid', 'fp='):
            assert token not in lowered, f'{token} is not something this crawler can produce'
        # The load-bearing names, each measured: drop any of the first group and the
        # answer loses every 观看数; the endpoint path itself was read off the page.
        for token in ('hot/search/list', 'device_platform=webapp', 'aid=6383', 'detail_list=1', 'source=6'):
            assert token in lowered, token

    def test_the_link_is_the_address_the_board_itself_uses(self, make_crawler):
        crawler, _driver = make_crawler(cards=['1'], board=_board([_entry()]))
        row = crawler.hot(target_count=1)[0]
        assert (
            row['链接'] == 'https://www.douyin.com/hot/2665423/%E4%B8%AD%E7%BE%8E%E5%85%83%E9%A6%96%E4%BC%9A%E8%B0%88'
        )

    def test_a_figure_the_site_did_not_publish_stays_blank_rather_than_becoming_zero(self, make_crawler):
        # The pinned top entry is published with ``position: null`` and — measured in one
        # of the two runs — ``hot_value``/``view_count`` null too. 0 on a board means
        # "the site counted nothing"; blank is the only cell that says "no figure".
        crawler, _driver = make_crawler(
            cards=['1'],
            board=_board([_entry(position=None, hot=None, views=None, video_count=None)]),
        )
        row = crawler.hot(target_count=1)[0]
        assert row['热度'] == '' and row['观看数'] == '' and row['视频数'] == '', row
        assert row['排名'] == 1, 'the entry is first on the board; that much the answer does say'

    def test_no_second_topic_column_is_invented_from_the_same_words(self, make_crawler):
        # weibo publishes ``word`` and a ``#…#`` scheme, so 话题 means something there.
        # Douyin publishes one string; a second column of it would be noise the user
        # reads as data.
        crawler, _driver = make_crawler(cards=['1'], board=_board([_entry()]))
        assert set(crawler.hot(target_count=1)[0]) == {
            '排名',
            '标题',
            '热度',
            '观看数',
            '视频数',
            '讨论视频数',
            '发布时间',
            '链接',
        }

    def test_a_repeated_topic_is_kept_once(self, make_crawler):
        crawler, _driver = make_crawler(cards=['1'], board=_board([_entry(), _entry()]))
        assert len(crawler.hot(target_count=10)) == 1

    def test_the_target_is_a_cap_not_a_padding(self, make_crawler, caplog):
        crawler, _driver = make_crawler(cards=['1'], board=_board([_entry(position=1)]))
        with caplog.at_level('INFO'):
            rows = crawler.hot(target_count=5)
        assert len(rows) == 1
        assert t('crawl.dy.hotCapped', board=1) in _lines(caplog), _lines(caplog)

    def test_an_answer_that_is_not_a_board_is_refused_by_name(self, make_crawler):
        # A WAF page or a dead transport arrives as ``{}`` from the in-page fetch; a
        # risk-control envelope arrives with a status_code. Neither may read as
        # "nothing is hot today".
        crawler, _driver = make_crawler(cards=['1'], board={'status_code': 10, 'status_msg': 'verify'})
        with pytest.raises(RuntimeError) as err:
            crawler.hot(target_count=5)
        assert 'verify' in str(err.value)

    def test_a_non_json_answer_is_refused_too(self, make_crawler):
        crawler, _driver = make_crawler(cards=['1'], board=None)
        with pytest.raises(RuntimeError):
            crawler.hot(target_count=5)

    def test_the_captcha_interstitial_refuses_before_the_endpoint_is_asked(self, make_crawler):
        crawler, driver = make_crawler(
            cards=[],
            title='验证码中间页',
            video_body='当前请求存在异常，暂时限制访问',
            board=_board([_entry()]),
        )
        with pytest.raises(RuntimeError) as err:
            crawler.hot(target_count=5)
        assert t('crawl.dy.hotWall') in str(err.value)
        assert not driver.fetched, 'a walled session was still charged for a read'

    def test_a_board_already_collected_to_the_target_is_not_read_again(self, make_crawler, caplog):
        crawler, driver = make_crawler(cards=['1'], board=_board([_entry(), _entry(position=2)]))
        crawler.emit({'标题': '已有', '链接': 'https://www.douyin.com/hot/1/x'})
        with caplog.at_level('INFO'):
            rows = crawler.hot(target_count=1)
        assert len(rows) == 1
        assert not driver.fetched, 'the endpoint was asked although the target was already stored'
        assert t('crawl.dy.hotTarget', n=1) in ' '.join(_lines(caplog)), _lines(caplog)


class TestSlowNetworkIsNotBlamedOnTheSite:
    """A navigation that never finished is a different complaint from a refusal.

    Measured on a real run and confirmed by the user watching the window: on a bad
    connection douyin's pages simply do not arrive inside ``page_load_timeout``, and
    before this distinction existed the run answered 「只可能是被拦截或页面出错」 —
    sending the user to re-save a cookie that was fine, or to blame a site that was
    merely slow. ``Crawler.open`` already knew the difference; both douyin call sites
    were throwing the answer away.
    """

    def test_a_detail_page_still_loading_is_not_reported_as_having_no_data(self, make_crawler, caplog):
        crawler, _driver = make_crawler(cards=[ID], video_body='', load_timeout=True)
        with caplog.at_level('WARNING'):
            assert crawler.get_detail(f'https://www.douyin.com/video/{ID}') is None
        assert t('crawl.dy.detailSlow', i=ID) in ' '.join(_lines(caplog)), _lines(caplog)
        assert t('crawl.dy.detailEmpty', i=ID) not in ' '.join(_lines(caplog))

    def test_a_detail_page_that_arrived_and_shown_nothing_still_says_no_data(self, make_crawler, caplog):
        crawler, _driver = make_crawler(cards=[ID], video_body='')
        with caplog.at_level('WARNING'):
            assert crawler.get_detail(f'https://www.douyin.com/video/{ID}') is None
        assert t('crawl.dy.detailEmpty', i=ID) in ' '.join(_lines(caplog)), _lines(caplog)

    def test_the_open_verdict_is_recorded_for_the_caller_that_cannot_take_it(self, make_crawler):
        # A walk that opens a page through ``_wait_for_grid`` / ``_wait_for_page`` cannot take
        # ``open``'s return value; the recorded flag is what lets the refusal say the true thing.
        crawler, _driver = make_crawler(cards=[], load_timeout=True)
        crawler.open('https://www.douyin.com/video/x')
        assert crawler.navigation_settled is False
        crawler, _driver = make_crawler(cards=[])
        crawler.open('https://www.douyin.com/video/x')
        assert crawler.navigation_settled is True


#: One of the three measured error pages Chrome commits for a refused navigation
#: (``backend/test_arrival_evidence.py``); the other two differ only in the token.
REFUSED_URI = 'chrome-error://chromewebdata/'
DNS_PAGE = '无法访问此网站\n\n找不到 www.douyin.com 的服务器 IP 地址\n\nERR_NAME_NOT_RESOLVED'


class TestTheBrowserRefusedThePage:
    """The third empty-page shape, which is neither the site's nor the keyword's fault.

    Measured: a navigation Chrome itself refuses leaves a committed document that calls
    itself ``chrome-error://chromewebdata`` and prints its own token, while the address
    bar — and ``driver.current_url`` — keep showing the URL that was asked for. Read as
    an ordinary page that would blame the platform for this machine's network, so the
    refusal names the browser instead.
    """

    def test_a_refusal_names_the_browser_and_leaves_the_session_alone(self, make_crawler):
        crawler, driver = make_crawler(cards=[], board=None, document_uri=REFUSED_URI, body=DNS_PAGE)
        with pytest.raises(RuntimeError) as err:
            crawler.hot(target_count=3)
        message = str(err.value)
        assert 'ERR_NAME_NOT_RESOLVED' in message, message
        # The two sentences this one must not be confused with: the exclusivity claim
        # (「只可能是被拦截…」) belongs to a page that arrived and stayed empty, and a
        # cookie is not in question when the site never saw the request.
        assert '只可能是' not in message, message
        assert 'Cookie' not in message and '登录' not in message, message
        assert (crawler.unreachable, crawler.login_wall, crawler.risk_blocked) == (True, False, False)
        assert not driver.fetched, 'a refused page was still charged for an in-page read'

    def test_a_hot_board_behind_a_refused_page_is_not_read_as_an_empty_board(self, make_crawler):
        crawler, driver = make_crawler(cards=[], board=None, document_uri=REFUSED_URI, body=DNS_PAGE)
        with pytest.raises(RuntimeError) as err:
            crawler.hot(target_count=5)
        assert 'ERR_NAME_NOT_RESOLVED' in str(err.value), str(err.value)
        assert not driver.fetched, 'the board endpoint was asked from a page that never arrived'

    def test_an_article_that_only_mentions_the_token_is_not_a_death(self, make_crawler):
        """The expensive direction: a page that arrived is a page. The decision reads the
        document's own address, so a development post about connection resets stays
        crawlable even though the token is sitting in its body."""
        crawler, _driver = make_crawler(
            cards=[],
            body='排查 net::ERR_CONNECTION_RESET 的三种原因',
            document_uri='https://www.douyin.com/search/美食',
        )
        crawler.open('https://www.douyin.com/search/美食')
        assert crawler.verdict() == 'ok'
        assert crawler.unreachable is False


def _lines(caplog) -> list:
    return [record.getMessage() for record in caplog.records]
