"""Douyin crawl against a fake driver — the measured contract, no browser.

Every assertion here encodes a measurement that contradicts the obvious
implementation, which is exactly why it needs to be pinned where it runs on
every change:

* the result list mounts only after the **search bar and its button** drive the
  app's router, and only when the page *says* 为你找到… — a deep link leaves
  three empty ``<ul>``s that read as "no results";
* the 搜索 button sits under a transparent overlay, so the Enter key is a real
  fallback path and not decoration;
* a row's numbers come from the ``data-e2e`` counters that name themselves, and
  the row has **no 播放数 column at all**, because the web player's second number
  is the like count, not plays — a plausible-wrong figure is worse than none;
* comments are DOM-scrolled (douyin's endpoint is signed with ``a_bogus``).
"""

import json

import pytest

import crawlers.base as base_module
from crawlers.base import Crawler
from crawlers.comments import BLOCKED, DEAD, OK, CommentSession, douyin_comment_fields, parse_douyin_comments
from crawlers.engine.counters import parse_count
from crawlers.video import (
    DouyinCrawler,
    _author_from_related,
    _clean_publish,
    douyin_id,
)
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


class SearchBox(El):
    """Douyin's search input is a *controlled* component.

    Measured on the live site: a whole phrase arriving in one ``send_keys`` makes
    its own handler re-route the page, and the text is gone before 搜索 is
    pressed — the crawl then submits an empty query and reports 0 rows for a
    keyword with thousands of videos. Typing one character per event is what the
    widget accepts, so this fake wipes the value on a bulk write and keeps it on
    per-character writes. That is what makes the product's typing loop testable.
    """

    def __init__(self, wipes_on_bulk=True, driver=None):
        super().__init__('')
        self.value = ''
        self.wipes_on_bulk = wipes_on_bulk
        self.driver = driver

    def send_keys(self, text):
        super().send_keys(text)
        if text == '\n':
            # Enter is a real submit path here (the button sits under an overlay).
            if self.driver is not None:
                self.driver.submit_query(self.value)
            return
        if self.wipes_on_bulk and len(text) > 1:
            self.value = ''
            return
        self.value += text


class SubmitButton(El):
    """Pressing 搜索 hands whatever the box holds to the app's own router.

    With the 「保存登录信息」 dialog still up, the click does something else — it
    closes the dialog, takes the words out of the box, and the route never
    changes. That is the observed sequence this fake has to reproduce, because it
    is why the crawler clears the dialog *before* clicking rather than after a
    failed attempt.
    """

    def __init__(self, driver):
        super().__init__('')
        self.driver = driver

    def click(self):
        self.driver.route_attempts += 1
        if self.driver.dialog:
            self.driver.dialog = False
            self.driver.box.value = ''
            return
        self.driver.submit_query(self.driver.box.value)


class FakeDriver:
    """Serves the search page and the video page from fixed fixture maps."""

    def __init__(
        self,
        cards,
        facts=None,
        body='为你找到以下结果',
        video_body=INFO_TEXT,
        missing_box=False,
        comment_items=None,
        comment_count='2099',
        wipes_on_bulk=True,
        router_takes_query=True,
        dialog=False,
    ):
        self.cards = cards
        self.facts = facts if facts is not None else _default_facts()
        self.body = body
        self.video_body = video_body
        self.missing_box = missing_box
        self.wipes_on_bulk = wipes_on_bulk
        self.router_takes_query = router_takes_query
        # Is the 「保存登录信息」 dialog up? The click behaves differently when it is.
        self.dialog = dialog
        self.route_attempts = 0
        self.dismissals = 0
        self.box = SearchBox(wipes_on_bulk=wipes_on_bulk, driver=self)
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
        self.scrolls = 0

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def submit_query(self, query: str):
        """The app's own router: a non-empty query moves to ``/search/<kw>``.

        ``router_takes_query=False`` models the other half of the measured failure
        — the words are in the box but the route never changes.
        """
        if query and self.router_takes_query:
            self.current_url = f'https://www.douyin.com/jingxuan/search/{query}?type=general'
            self.visited.append(self.current_url)

    def find_element(self, by, selector):
        if selector == 'body':
            return El(self.video_body if '/video/' in self.current_url else self.body)
        if selector == DouyinCrawler.SEARCH_INPUT:
            if self.missing_box:
                raise RuntimeError('no such element')
            return self.box
        if selector == DouyinCrawler.SEARCH_BUTTON:
            return SubmitButton(self)
        if selector == '[data-e2e="comment-list"]':
            return El('')
        if selector == '[data-e2e="feed-comment-icon"]':
            return El(self.comment_count)
        raise RuntimeError(f'no element {selector}')

    def find_elements(self, by, selector):
        if selector == DouyinCrawler.CARD_SELECTOR:
            return [El('', {'data-aweme-id': aweme_id}) for aweme_id in self.cards]
        if selector == DouyinCrawler.SEARCH_BUTTON:
            return [SubmitButton(self)]
        if selector == '[data-e2e="comment-item"]':
            return list(self.comment_items)
        return []

    def execute_script(self, script, *args):
        if 'arguments[0].value' in script:
            return getattr(args[0], 'value', '') if args else ''
        if "el.value = ''" in script:
            if args:
                args[0].value = ''
            return None
        if 'innerText' in script and args:
            return getattr(args[0], 'text', '')
        if 'arguments[0].focus' in script:
            return None
        if 'scrollHeight' in script:
            self.scrolls += 1
            return 'container'
        if 'video-player-digg' in script:
            return dict(self.facts)
        return None

    def execute_async_script(self, script, *args):
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


class TestSearch:
    def test_the_search_box_is_used_and_the_button_clicked(self, make_crawler):
        crawler, driver = make_crawler(cards=[ID])
        rows = crawler.search('人工智能', target_count=1)
        assert rows and rows[0]['视频ID'] == ID
        # The crawl enters at the page the site would have redirected to: the root
        # costs a full extra SPA render to arrive at /jingxuan anyway.
        assert driver.visited[0] == DouyinCrawler.crawl_entry == 'https://www.douyin.com/jingxuan'

    def test_the_query_is_written_in_one_go_when_the_box_keeps_it(self, make_crawler):
        """The fast path: one write, then proof it landed. Character-by-character
        typing measured ~15 s on a busy page, so it must not be the default."""
        crawler, driver = make_crawler(cards=[ID], wipes_on_bulk=False)
        crawler.search('人工智能', target_count=1)
        assert driver.box.sent == ['人工智能']

    def test_a_wiped_box_is_retyped_and_the_search_still_lands(self, make_crawler):
        """The repair path, and the reason the write is checked at all.

        Douyin's box is a controlled input: with the 「保存登录信息」 mask up, the
        bulk write is wiped by the site's own handler. Reading the value back is
        what turns that from a silent empty query into a retype — the crawl must
        still come back with rows.
        """
        crawler, driver = make_crawler(cards=[ID], wipes_on_bulk=True)
        rows = crawler.search('人工智能', target_count=1)
        assert rows, 'the retry must still deliver rows, not a 0-row crawl'
        assert '人工智能' in driver.box.sent, 'bulk is tried first, every time'
        assert any(len(s) == 1 for s in driver.box.sent), 'then it falls back to per-character'
        assert driver.route_attempts >= 2, 'the click that carried nothing is retried, not accepted'

    def test_an_intercepted_button_falls_back_to_enter(self, make_crawler, monkeypatch):
        """The 搜索 button sits under a transparent overlay on this build, so the
        Enter key is a live path — and the keyword must still reach the box."""
        crawler, driver = make_crawler(cards=[ID])

        class _RefusingButton(El):
            def click(self):
                raise RuntimeError('element click intercepted')

        original = driver.find_element

        def _find(by, selector):
            if selector == DouyinCrawler.SEARCH_BUTTON:
                return _RefusingButton('')
            return original(by, selector)

        monkeypatch.setattr(driver, 'find_element', _find)
        assert crawler.search('人工智能', target_count=1)
        assert driver.box.sent[-1] == '\n', 'Enter must carry the submit after the click fails'
        assert any('/search/人工智能' in url for url in driver.visited)

    def test_the_dialog_is_cleared_before_the_click_so_no_attempt_is_wasted(self, make_crawler):
        """Watched live: typing worked, then the mask appeared, then the 搜索 click
        closed the mask **and emptied the box**, so the first attempt was always
        thrown away and only the second one searched.

        Clearing the dialog before the click — and refilling if the box came back
        empty — makes the first submit count. ``route_attempts`` is the proof: one
        click that worked, instead of two where the first hit a dead page.
        """
        crawler, driver = make_crawler(cards=[ID], dialog=True, wipes_on_bulk=False)
        rows = crawler.search('人工智能', target_count=1)
        assert rows
        assert driver.route_attempts == 1, 'the first submit should have taken'
        assert driver.dismissals == 1, 'the dialog is cleared by us, before the click'

    def test_a_stale_box_read_does_not_stop_a_search_the_router_accepted(self, make_crawler, monkeypatch):
        """The watched failure: the words were in the box, the search ran, and a
        loop that trusted the *read-back* kept clearing and retyping until it gave
        up. The app replaces the header node, which makes the value unreadable —
        that is a read problem, not a missing query, so the URL decides."""
        crawler, driver = make_crawler(cards=[ID], wipes_on_bulk=False)
        monkeypatch.setattr(crawler, '_box_value', lambda box: '')
        rows = crawler.search('人工智能', target_count=1)
        assert rows, 'an unreadable input must not abort a search that landed'
        assert driver.route_attempts == 1, 'no click may be wasted on the way'
        assert driver.box.value == '人工智能'

    def test_a_bulk_write_would_lose_the_query_and_says_so_instead_of_zero_rows(self, make_crawler, monkeypatch):
        """The regression guard for the loop above.

        With the old one-shot ``send_keys`` the box wipes itself, so this asserts
        the *reporting* half of the fix: a query that never got in must fail the
        node loudly, because "0 results" would be a claim about the keyword
        rather than about the page.
        """
        crawler, driver = make_crawler(cards=[ID])

        def bulk_typing(box, keyword, per_character=False):
            box.send_keys(str(keyword))
            return box.value == keyword

        monkeypatch.setattr(crawler, '_type_query', bulk_typing)
        with pytest.raises(RuntimeError) as err:
            crawler.search('人工智能', target_count=2)
        assert '人工智能' in str(err.value)
        assert driver.box.value == ''

    def test_a_query_the_router_never_took_is_not_an_empty_search(self, make_crawler):
        crawler, driver = make_crawler(cards=[ID], router_takes_query=False)
        with pytest.raises(RuntimeError):
            crawler.search('人工智能', target_count=2)
        assert driver.box.value == '人工智能', 'the box kept the words; the route is what failed'

    def test_a_page_that_never_mounts_results_collects_nothing(self, make_crawler):
        crawler, _driver = make_crawler(cards=[ID], body='精选 | 推荐 | 直播')
        assert crawler.search('人工智能', target_count=3) == []

    def test_a_missing_search_box_is_reported_not_silently_empty(self, make_crawler):
        crawler, _driver = make_crawler(cards=[ID], missing_box=True)
        with pytest.raises(RuntimeError):
            crawler.search('人工智能', target_count=3)

    def test_a_captcha_interstitial_refuses_the_run(self, make_crawler):
        """Headless douyin is answered by 验证码中间页 on every navigation; a run
        that ends in an empty table would read as "this keyword has no videos"."""
        crawler, driver = make_crawler(cards=[ID], body='')
        crawler._title = lambda: '验证码中间页'  # type: ignore[method-assign]
        driver.current_url = 'https://www.douyin.com/verify'
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
