"""Douyin crawl against a fake driver — the measured contract, no browser.

Every assertion here encodes a measurement that contradicts the obvious
implementation, which is exactly why it needs to be pinned where it runs on
every change:

* the result page is entered through **its own address** (``/search/<kw>?type=video``),
  because the search box and its 搜索 button no longer route anywhere — measured, and
  confirmed by watching the window: the words appear, the click does nothing, Enter
  included. The list also mounts as **skeleton rows** (no anchor, no text) and fills
  in seconds later, so "cards exist" is not yet "results exist";
* the window scrolling is the pager (measured 16 → 26 → 36 cards per scroll), so a
  walk that stopped after one screen would report the head of the list as the search;
* a row's numbers come from the ``data-e2e`` counters that name themselves on the
  video page, and the row has **no 播放数 column at all**, because the web player's
  second number is the like count, not plays — a plausible-wrong figure is worse
  than none (the search card's own bare figure measures equal to that like count);
* comments are DOM-scrolled (douyin's endpoint is signed with ``a_bogus``).
"""

import json

import pytest
from selenium.common.exceptions import TimeoutException

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.comments import BLOCKED, DEAD, OK, CommentSession, douyin_comment_fields, parse_douyin_comments
from crawlers.engine.counters import parse_count
from crawlers.video import (
    DouyinCrawler,
    _author_from_related,
    _clean_publish,
    douyin_id,
    douyin_sec_uid,
)
from i18n import t
from utils.helpers import platform_for

pytestmark = pytest.mark.unit

ID = '7665683746674183459'
INFO_TEXT = '归墟第十二集 #归墟 #末日 #科幻\n5.9万\n2099\n9241\n7839\n举报\n发布时间：2026-08-04 16:32'
RELATED_TEXT = '泫九粉丝167.0万获赞1157.5万关注短剧 · 归墟第一季07:58播放中第7集'
COMMENT_BLOCK = '\n'.join(
    ['盖世英雄小行者', '...', '作者的脑洞太强大了，这才叫科幻', '1月前·北京', '', '5', '', '分享', '展开1条回复']
)


class El:
    def __init__(self, text='', attrs=None, intercept=False):
        self.text = text
        self._attrs = attrs or {}
        self.sent = []
        self.clicked = False
        self._intercept = intercept

    def get_attribute(self, name):
        return self._attrs.get(name, '')

    def send_keys(self, value):
        self.sent.append(value)

    def click(self):
        if self._intercept:
            raise RuntimeError('element click intercepted')
        self.clicked = True


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
        video_body=INFO_TEXT,
        comment_items=None,
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
    ):
        # What the *document* says it is. Measured: after a navigation the browser itself
        # refuses, this is ``chrome-error://chromewebdata`` while ``current_url`` goes on
        # reporting the address that was asked for — so a fake that cannot answer it can
        # never model the one failure mode the crawler has to tell apart.
        self.document_uri = document_uri
        # The whole-page body text, when a test needs the page to say something other than
        # what the video/search fixtures hold (an error page's own words, for instance).
        self.body = body
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
        # The author profile's own 作品 grid: the ids mounted in it, the batches a
        # container jump reveals, and the count the page publishes for itself.
        self.grid = list(grid or [])
        self.grid_batches = list(grid_batches or [])
        self.works = works
        self.facts = facts if facts is not None else _default_facts()
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

    def get(self, url):
        self.visited.append(url)
        self.current_url = url
        if self.load_timeout:
            # What chromedriver answers when the document is still building at the end
            # of ``page_load_timeout`` — the page is not wrong, it is unfinished.
            raise TimeoutException(f'no such window: navigation timed out for {url}')

    def find_element(self, by, selector):
        if selector == 'body':
            if self.body is not None:
                return El(self.body)
            return El(self.video_body if '/video/' in self.current_url else '')
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
            if self.fill_after and self._pending:
                self._reads = getattr(self, '_reads', 0) + 1
                if self._reads >= self.fill_after:
                    self.cards, self._pending = self._pending, []
            return [El('', {'href': f'//www.douyin.com/video/{aweme_id}'}) for aweme_id in self.cards]
        if selector == DouyinCrawler.PROFILE_ANCHOR:
            return [El('', {'href': f'https://www.douyin.com/video/{aweme_id}'}) for aweme_id in self.grid]
        if selector == '[data-e2e="comment-item"]':
            return list(self.comment_items)
        return []

    def execute_script(self, script, *args):
        if 'documentURI' in script:
            return self.document_uri
        if 'innerText' in script and args:
            return getattr(args[0], 'text', '')
        if 'scrollBy' in script:
            self.scrolls += 1
            self.window_scrolls += 1
            if self.scroll_batches:
                self.cards = self.cards + self.scroll_batches.pop(0)
            return None
        if 'scrollTop' in script or 'scrollHeight' in script:
            # The comment panel's own scroller (the endpoint is signed, so the
            # panel is walked by DOM), and the profile grid's, which is what
            # ``engine.feed.jump_to_bottom`` hunts for.
            self.scrolls += 1
            if 'scrollerFrom' in script:
                self.container_jumps += 1
                if self.grid_batches:
                    self.grid = self.grid + self.grid_batches.pop(0)
            return 'container'
        if 'video-player-digg' in script:
            return dict(self.facts)
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


class TestSearch:
    def test_the_result_page_is_entered_through_its_own_address(self, make_crawler):
        """The keyword is in the address the crawler asked for, so there is no
        router left to interrogate about which search actually ran.

        Measured 2026-09: the search box still takes the text and its 搜索 button is
        still clickable and does nothing — the address sits on ``/jingxuan`` through
        a click *and* through Enter — while ``/search/<kw>?type=video``, which used to
        be an empty shell, now serves the list.
        """
        crawler, driver = make_crawler(cards=[ID])
        rows = crawler.search('人工智能', target_count=1)
        assert rows and rows[0]['视频ID'] == ID
        assert driver.visited[0] == 'https://www.douyin.com/search/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD?type=video'
        assert all('/jingxuan' not in url for url in driver.visited), 'the box-and-button entry is gone'

    def test_a_list_still_drawing_its_skeleton_is_waited_out(self, make_crawler):
        """The rows exist before their content does.

        Measured: 16 ``<li>`` with no anchor and no text first, and the same 16
        holding video addresses a few seconds later. A walk that counted nodes would
        take the first state for results; the wait is for an anchor, so an undrawn
        page is never mistaken for a keyword that found nothing.
        """
        crawler, driver = make_crawler(cards=[ID, '7665683746674183460'], fill_after=2)
        rows = crawler.search('人工智能', target_count=2)
        assert [row['视频ID'] for row in rows] == [ID, '7665683746674183460']
        assert driver.scrolls == 0, 'the page was waited on rather than scrolled past'

    def test_a_page_that_never_hands_over_a_card_refuses_rather_than_reporting_zero(self, make_crawler):
        """Zero cards is never "no results" on this site.

        Measured: a keyword that cannot exist still came back with 16 related videos,
        because douyin fills the list in rather than showing an empty plate — so an
        empty list is the page failing (blocked, or its own ``502 Bad Gateway``), and
        a 0-row success would be a claim about the user's keyword. The refusal quotes
        what the page said, because "nothing" is not something to act on.
        """
        crawler, driver = make_crawler(cards=[], title='502 Bad Gateway')
        with pytest.raises(RuntimeError) as err:
            crawler.search('人工智能', target_count=3)
        assert '502 Bad Gateway' in str(err.value)
        assert driver.scrolls == 0 and len(driver.visited) == 1, 'nothing was paid for on the way'

    def test_the_mask_is_cleared_on_arrival(self, make_crawler):
        """The 「保存登录信息超过5天」 dialog still mounts seconds after the page and
        covers the list. Only 取消 is ever pressed: the user reports 保存 leads to a
        phone-verification step, so declining is both the safe answer and the one
        that leaves the session alone.
        """
        crawler, driver = make_crawler(cards=[ID], dialog=True)
        assert crawler.search('人工智能', target_count=1)
        assert driver.dismissals == 1, 'the dialog is cleared by us, on arrival'

    def test_scrolling_pays_out_the_next_batch_of_rows(self, make_crawler):
        """Measured: 16 → 26 → 36 cards per window scroll, so the window *is* the
        pager now. A walk that stopped after one screen would hand back the head of
        the list and read as a complete search."""
        crawler, driver = make_crawler(cards=[ID], scroll_batches=[['7665683746674183460', '7665683746674183461']])
        rows = crawler.search('人工智能', target_count=3)
        assert [row['视频ID'] for row in rows] == [ID, '7665683746674183460', '7665683746674183461']
        assert driver.scrolls >= 1

    def test_a_captcha_interstitial_refuses_the_run(self, make_crawler):
        """A run answered by 验证码中间页 has to fail, not come back empty — an empty
        table reads as "this keyword has no videos", which is a claim about the
        data. The wall here lives in the page title, not in any URL pattern — and it
        arrives *after* the navigation settled (measured), so it has to be watched for
        during the mount wait: a single check on arrival walked straight past it into a
        0-row success, which is the bug this now pins."""
        crawler, _driver = make_crawler(cards=[ID], fill_after=99, title='验证码中间页')
        with pytest.raises(RuntimeError) as err:
            crawler.search('人工智能', target_count=3)
        assert '验证码' in str(err.value) or 'captcha' in str(err.value).lower()

    def test_rows_carry_only_the_counters_that_name_themselves(self, make_crawler):
        crawler, _driver = make_crawler(cards=[ID])
        row = crawler.search('人工智能', target_count=1)[0]
        assert row['点赞数'] == 59000 and row['评论数'] == 2099
        assert row['收藏数'] == 9241 and row['转发数'] == 7839
        assert row['发布时间'] == '2026-08-04 16:32'
        assert row['作者'] == '泫九' and row['粉丝数'] == 1670000
        assert row['正文'] == '归墟第十二集 #归墟 #末日 #科幻'
        assert row['链接'] == f'https://www.douyin.com/video/{ID}'

    def test_no_play_count_column_exists_on_douyin(self, make_crawler):
        """Measured: detail-video-info's second number IS the like counter, and
        the web player never shows plays. Publishing 播放数 would be a wrong
        figure wearing a plausible column name."""
        crawler, _driver = make_crawler(cards=[ID])
        row = crawler.search('人工智能', target_count=1)[0]
        assert '播放数' not in row

    def test_target_count_stops_opening_more_videos(self, make_crawler):
        crawler, driver = make_crawler(cards=[ID, '7678996507694094827', '7684552351918689571'])
        rows = crawler.search('人工智能', target_count=1)
        assert len(rows) == 1
        opened = [u for u in driver.visited if '/video/' in u]
        assert len(opened) == 1

    def test_a_video_that_renders_nothing_is_skipped_not_stored(self, make_crawler):
        crawler, _driver = make_crawler(cards=[ID, '7678996507694094827'], video_body='加载中')
        rows = crawler.search('人工智能', target_count=5)
        assert rows == []

    def test_opened_ids_ride_in_the_cursor_for_a_resumed_run(self, make_crawler):
        crawler, driver = make_crawler(cards=[ID, '7678996507694094827'])
        crawler.search('人工智能', target_count=2)
        assert ID in crawler.position['opened']
        reopened, second = make_crawler(cards=[ID, '7678996507694094827'])
        reopened.seed([{'标题': 'already stored', '链接': f'https://www.douyin.com/video/{ID}'}])
        reopened.search('人工智能', target_count=2, resume={'opened': [ID]})
        assert len([u for u in second.visited if f'/video/{ID}' in u]) == 0, 'must not re-open a paid-for video'

    def test_a_resumed_run_walks_past_the_screen_it_already_paid_for(self, make_crawler):
        """The resumed page reopens on the very ids the dead run opened, so "every
        id on screen is known" is that run's *ordinary first round* — not the end of
        the list. Breaking there (which the walk used to do) made 断点续跑 hand back
        the dead run's rows and quietly stop, with the target unmet and no complaint."""
        other = '7678996507694094827'
        crawler, driver = make_crawler(cards=[ID], scroll_batches=[[other]])
        crawler.seed([{'视频ID': ID, '链接': f'https://www.douyin.com/video/{ID}'}])
        rows = crawler.search('人工智能', target_count=2, resume={'opened': [ID]})
        assert driver.window_scrolls >= 1, 'an exhausted-looking first screen must be scrolled, not obeyed'
        assert {str(row['视频ID']) for row in rows} == {ID, other}


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

    def test_the_container_is_jumped_because_the_window_moves_nothing_here(self, make_crawler):
        """Measured: a window scroll on a profile page grows the footer's
        recommended-video links (8 → 29) and leaves the 作品 grid untouched, which a
        count-based walk reports as an exhausted list at 57 of 85."""
        crawler, driver = make_crawler(cards=[], grid=[ID], grid_batches=[[OTHER]], works='2')
        crawler.author(SEC, target_count=2)
        assert driver.container_jumps >= 1
        assert driver.window_scrolls == 0, 'the window is the wrong surface on this page'

    def test_the_numbers_come_from_opening_the_video_not_from_the_card(self, make_crawler):
        crawler, _driver = make_crawler(cards=[], grid=[ID], works='1')
        row = crawler.author(f'https://www.douyin.com/user/{SEC}?from_tab_name=main', target_count=1)[0]
        assert row['点赞数'] == 59000 and row['评论数'] == 2099 and row['收藏数'] == 9241 and row['转发数'] == 7839
        assert row['作者'] == '泫九' and row['发布时间'] == '2026-08-04 16:32'
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

    def test_identity_columns_stay_out_of_the_dedupe_field_lists(self):
        from services.run_store import _AUTHOR_FIELDS, _BODY_FIELDS, _URL_FIELDS

        rows = parse_douyin_comments([(f'https://www.douyin.com/video/{ID}', '甲', '内容', '1天前', '北京', 2, 0)])
        for name in rows[0]:
            assert name not in _URL_FIELDS + _AUTHOR_FIELDS + _BODY_FIELDS, name
        assert rows[0]['楼层'] == 1


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

    def test_a_result_page_still_loading_says_the_network_not_the_site(self, make_crawler):
        crawler, driver = make_crawler(cards=[], load_timeout=True)
        with pytest.raises(RuntimeError) as err:
            crawler.search('美食', target_count=3)
        assert t('crawl.dy.noCardsSlow', url=driver.current_url) in str(err.value)
        # The old sentence did not merely name a cause, it claimed exclusivity
        # (「只可能是…」) and sent the user to re-save a cookie that was fine.
        assert '只可能是' not in str(err.value), str(err.value)

    def test_a_result_page_that_did_finish_but_mounted_nothing_still_quotes_the_page(self, make_crawler):
        # The old sentence is not deleted, only narrowed to the case it was measured on:
        # the navigation completed, the list stayed empty, and douyin does fill even a
        # nonsense keyword — so THAT one really is a block or a broken page.
        crawler, _driver = make_crawler(cards=[], title='502 Bad Gateway')
        with pytest.raises(RuntimeError) as err:
            crawler.search('美食', target_count=3)
        assert '502 Bad Gateway' in str(err.value), str(err.value)
        assert '加载超时' not in str(err.value), str(err.value)
        # The two sentences are told apart by what they may claim: this one may name a
        # cause exclusively, the slow-load one may not.
        assert '只可能是' in str(err.value), str(err.value)

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
        # ``search`` reaches the refusal through ``_open_results``, so it cannot take the
        # return value; the recorded flag is what lets it say the true thing.
        crawler, _driver = make_crawler(cards=[], load_timeout=True)
        crawler.open('https://www.douyin.com/search/x')
        assert crawler.navigation_settled is False
        crawler, _driver = make_crawler(cards=[])
        crawler.open('https://www.douyin.com/search/x')
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
    an ordinary page, that is 「结果页没有给出任何视频卡片」: a sentence about douyin,
    said about this machine.
    """

    def test_a_refusal_names_the_browser_and_leaves_the_session_alone(self, make_crawler):
        crawler, driver = make_crawler(cards=[], document_uri=REFUSED_URI, body=DNS_PAGE)
        with pytest.raises(RuntimeError) as err:
            crawler.search('美食', target_count=3)
        message = str(err.value)
        assert 'ERR_NAME_NOT_RESOLVED' in message, message
        # The two sentences this one must not be confused with: the exclusivity claim
        # (「只可能是被拦截…」) belongs to a page that arrived and stayed empty, and a
        # cookie is not in question when the site never saw the request.
        assert '只可能是' not in message, message
        assert 'Cookie' not in message and '登录' not in message, message
        assert (crawler.unreachable, crawler.login_wall, crawler.risk_blocked) == (True, False, False)
        assert not driver.fetched, 'a refused page was still charged for an in-page read'

    def test_a_provable_death_is_given_up_on_at_once(self, make_crawler):
        """Patience is for a page that may still be coming. This one is not, and the
        number of looks at the list is how a test can tell the two waits apart."""
        crawler, driver = make_crawler(cards=[], document_uri=REFUSED_URI, body=DNS_PAGE)
        with pytest.raises(RuntimeError):
            crawler.search('美食', target_count=3)
        assert driver.card_reads == 1, f'a provable death was waited out for {driver.card_reads} looks'

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
