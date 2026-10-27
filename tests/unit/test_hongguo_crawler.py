"""红果短剧 against a fake driver — the board contract, no browser.

What this pins is what the live probes measured (``docs/crawler_notes.md`` 红果短剧), none
of which a reading of the site suggests:

* the board is read from the document's own loader payload, never from the rendered
  columns, and the payload is **deferred**: the loader key arrives with the document while
  ``content._data`` lands ~2 s later, so the first probe answers "still coming";
* paging follows ``pagination.nextUrl`` verbatim, so a page the site does not serve
  (``?page=6`` carries only ``rank_layout``) can only be reached by a cursor that names it —
  and there it is a **named refusal**, not an empty table;
* 集数 is the length of the payload's ``episodeVids`` (measured equal to the detail page's
  own count), which is why no click and no detail read exist here;
* a short is licensed only by the site's own words: its pager saying "no next page", or a
  payload whose ``isSuccess`` is true over an empty list. A repeated or un-moving pager is
  left ``UNDER_TARGET`` — our loop stopping is not the site running out.
"""

import pytest

import crawl_capabilities as capabilities
import crawlers.core.crawler as base_module
import i18n
from crawlers import hongguo
from crawlers.core.crawler import UNDER_TARGET, Crawler, PageNotArrivedError

pytestmark = pytest.mark.unit

BASE_URL = hongguo.BASE
BOARD_URL = f'{BASE_URL}/rank/hot-drama'


def _work(i, rank, **over):
    """One ``rankList`` entry in the measured shape (probe #10, all four boards)."""
    item = {
        'id': 1000 + i,
        'seriesId': f'series{i}',
        'rank': rank,
        'title': f'作品{i}',
        'cover': f'https://p3-sign.byteimg.com/tos-cn-i-abc/cover{i}.jpeg~tplv-xyz:300:400.image?lk3s=1',
        'href': f'/detail?series_id=series{i}',
        'playHref': f'/player/series{i}',
        'heatText': f'{1000 + i}万热度',
        'statusTags': ['新剧'],
        'scoreText': f'评分9.{i % 10}',
        'favoriteText': f'{10 + i}万收藏',
        'likeText': f'{20 + i}万点赞',
        'tags': ['奇幻', '年代'],
        'description': f'第{i}部作品的简介',
        'episodeVids': [f'v{i}-{k}' for k in range(1, i + 2)],
    }
    item.update(over)
    return item


def _board(rows, page=1, next_url='', is_success=True):
    return {
        'isSuccess': is_success,
        'rankList': rows,
        'pagination': {'pageNum': page, 'totalPages': 5, 'nextUrl': next_url},
    }


def _page_rows(first, last, **over):
    return [_work(i, rank=i, **over) for i in range(first, last + 1)]


class El:
    def __init__(self, text=''):
        self.text = text


class FakeDriver:
    """Serves one loader state per URL, in the site's own two shapes.

    ``pages`` maps a URL to the board it carries. A URL that is not in it answers like the
    page the site does not serve: ``rank_layout`` alone, no ``/page`` key, no board. ``defer``
    makes the first probe answer "the key is here, the data is not yet" — the measured
    sequence right after ``driver.get``.
    """

    def __init__(self, pages, defer=0):
        self.pages = dict(pages)
        self.defer = defer
        self.current_url = ''
        self.title = '红果短剧 - 免费短剧在线观看'
        self.body = ''
        self.visited = []

    def get(self, url):
        self.visited.append(url)
        self.current_url = url

    def execute_script(self, script, *args):
        if script == hongguo._STATE_JS:
            return self._state()
        if script == hongguo._BOARD_JS:
            return self._board()
        return None

    def _board(self):
        if self.defer:
            self.defer -= 1
            return None
        return self.pages.get(self.current_url)

    def _state(self):
        served = self.current_url in self.pages
        keys = ['rank_layout'] + (['rank_hot-drama/page'] if served else [])
        board = self._board()
        if board is None:
            return {
                'state': 'deferred' if served else 'missing',
                'loader_keys': keys,
                'page_key': keys[-1] if served else '',
                'rows': 0,
                'is_success': None,
                'page_num': None,
                'total_pages': None,
                'next_url': '',
            }
        pagination = board.get('pagination') or {}
        return {
            'state': 'ready',
            'loader_keys': keys,
            'page_key': keys[-1],
            'rows': len(board.get('rankList') or []),
            'is_success': board.get('isSuccess') is True,
            'page_num': pagination.get('pageNum'),
            'total_pages': pagination.get('totalPages'),
            'next_url': pagination.get('nextUrl') or '',
        }

    def find_element(self, by, selector):
        return El(self.body)

    def find_elements(self, by, selector):
        return []

    def set_script_timeout(self, seconds):
        pass

    def quit(self):
        pass


@pytest.fixture
def make_crawler(monkeypatch):
    monkeypatch.setattr(base_module.time, 'sleep', lambda s: None)

    def _make(pages, defer=0):
        driver = FakeDriver(pages, defer=defer)

        def fake_create(self, *args, **kwargs):
            self.driver = driver

        monkeypatch.setattr(Crawler, '_create_driver', fake_create)
        return hongguo.HongguoCrawler(headless=True), driver

    return _make


# ─── one card ───


def test_the_row_carries_every_field_the_payload_has():
    """The column set and the way each figure is read — 万 expanded, 评分 a float, 集数 counted."""
    row = hongguo.HongguoCrawler._row(_work(1, rank=1))
    assert list(row) == [
        '排名',
        '作品名',
        '评分',
        '热度',
        '收藏',
        '点赞',
        '分类',
        '状态标签',
        '集数',
        '简介',
        '作品ID',
        '链接',
        '播放链接',
        '封面',
    ]
    assert row['排名'] == 1
    assert row['作品名'] == '作品1'
    assert row['评分'] == 9.1, 'the score is the number in 评分9.1, not the label'
    assert row['热度'] == 1001 * 10_000, 'the 万 label is a rounded figure and must be expanded'
    assert row['收藏'] == 11 * 10_000
    assert row['点赞'] == 21 * 10_000
    assert row['分类'] == '奇幻 | 年代'
    assert row['状态标签'] == '新剧'
    assert row['集数'] == 2, 'measured: len(episodeVids) is the count the detail page shows'
    assert row['作品ID'] == 'series1'
    assert row['链接'] == f'{BASE_URL}/detail?series_id=series1'
    assert row['播放链接'] == f'{BASE_URL}/player/series1'
    assert row['封面'].startswith('https://')


def test_a_field_the_site_did_not_publish_is_blank_rather_than_a_zero():
    """A fabricated 0 is summed downstream as a real figure; a blank is the site's own silence."""
    row = hongguo.HongguoCrawler._row(
        _work(2, rank=None, scoreText='', heatText='', favoriteText='', likeText='', episodeVids=None)
    )
    assert row['评分'] == ''
    assert row['热度'] == '' and row['收藏'] == '' and row['点赞'] == ''
    assert row['排名'] == ''
    assert row['集数'] == '', 'no episode list is not 0 episodes'
    row = hongguo.HongguoCrawler._row(_work(3, rank=3, episodeVids=[]))
    assert row['集数'] == 0, 'an empty list the site published IS its answer'


def test_the_numeric_tag_one_board_prints_is_kept_verbatim():
    """Measured: ``tags`` carries the literal ``205`` on 21 rows of two boards — the site's own
    unresolved tag id, which is data about the row and not a parse failure to clean up."""
    row = hongguo.HongguoCrawler._row(_work(4, rank=4, tags=['奇幻', '205']))
    assert row['分类'] == '奇幻 | 205'


# ─── the board walk ───


def test_the_board_is_read_from_the_payload_in_one_page_load(make_crawler):
    crawler, driver = make_crawler({BOARD_URL: _board(_page_rows(1, 20), next_url='')})
    rows = crawler.hot(target_count=20, board='hot_drama')
    assert driver.visited == [BOARD_URL], 'page 1 is the bare URL; ?page=1 is the same page'
    assert [row['排名'] for row in rows] == list(range(1, 21))
    assert crawler.end_reason is None, 'the target ended this walk, so nothing is being licensed'


def test_a_deferred_payload_is_waited_for_rather_than_read_as_empty(make_crawler):
    """Measured: right after ``driver.get`` the key is there and ``content._data`` is not."""
    crawler, driver = make_crawler({BOARD_URL: _board(_page_rows(1, 20), next_url='')}, defer=1)
    rows = crawler.hot(target_count=20, board='hot_drama')
    assert len(rows) == 20
    assert driver.visited == [BOARD_URL], 'waiting must not cost a second navigation'


def test_the_walk_follows_the_next_link_the_site_gave(make_crawler):
    p2 = f'{BOARD_URL}?page=2'
    p3 = f'{BOARD_URL}?page=3'
    pages = {
        BOARD_URL: _board(_page_rows(1, 20), page=1, next_url=p2),
        p2: _board(_page_rows(21, 40), page=2, next_url=p3),
        p3: _board(_page_rows(41, 60), page=3, next_url=''),
    }
    crawler, driver = make_crawler(pages)
    rows = crawler.hot(target_count=45, board='hot_drama')
    assert driver.visited == [BOARD_URL, p2, p3]
    assert [row['排名'] for row in rows] == list(range(1, 46)), 'ranks continue across pages (measured)'
    assert len({row['作品ID'] for row in rows}) == 45
    assert crawler.end_reason is None


def test_a_resume_opens_the_page_the_cursor_names_and_skips_what_is_stored(make_crawler):
    """The core value: a resumed crawl does not re-pay for the pages it already has, and one
    page that brings nothing new is the stored page — not a reason to stop."""
    p2 = f'{BOARD_URL}?page=2'
    p3 = f'{BOARD_URL}?page=3'
    pages = {
        p2: _board(_page_rows(1, 20), page=2, next_url=p3),
        p3: _board(_page_rows(41, 60), page=3, next_url=''),
    }
    crawler, driver = make_crawler(pages)
    # Seeded exactly as the executor seeds it: the stored rows, not the raw payload entries.
    crawler.seed([hongguo.HongguoCrawler._row(item) for item in _page_rows(1, 20)])
    rows = crawler.hot(target_count=25, board='hot_drama', resume={'page': 2, 'page_url': p2})
    assert driver.visited == [p2, p3], 'page 1 holds nothing this run needs'
    assert len(rows) == 25
    assert [row['作品ID'] for row in rows[-5:]] == [f'series{i}' for i in range(41, 46)]
    assert crawler.end_reason is None


def test_two_pages_in_a_row_with_nothing_new_end_the_walk_under_target(make_crawler):
    """A pager that keeps offering pages while bringing nothing new is OUR loop stopping —
    a soft throttle looks exactly like this, so the short may not be licensed."""
    p2 = f'{BOARD_URL}?page=2'
    p3 = f'{BOARD_URL}?page=3'
    pages = {
        p2: _board(_page_rows(1, 20), page=2, next_url=p3),
        p3: _board(_page_rows(1, 20), page=3, next_url=f'{BOARD_URL}?page=4'),
    }
    crawler, driver = make_crawler(pages)
    crawler.seed([hongguo.HongguoCrawler._row(item) for item in _page_rows(1, 20)])
    rows = crawler.hot(target_count=45, board='hot_drama', resume={'page': 2, 'page_url': p2})
    assert driver.visited == [p2, p3], 'two no-fresh pages are enough; page 4 is not worth asking'
    assert len(rows) == 20
    assert crawler.end_reason == UNDER_TARGET, 'our loop stopping is not the site running out'
    assert crawler.walk_counts == {'scanned': 40, 'kept': 0, 'refused': 0}


def test_a_resume_of_the_stored_last_page_is_licensed_by_the_pagers_own_end(make_crawler):
    """The other side of the same coin: the page brought nothing new AND the site says there
    is no page after it — the list really ended, so the shortfall is out of supply."""
    p2 = f'{BOARD_URL}?page=2'
    crawler, _driver = make_crawler({p2: _board(_page_rows(1, 20), page=2, next_url='')})
    crawler.seed([hongguo.HongguoCrawler._row(item) for item in _page_rows(1, 20)])
    rows = crawler.hot(target_count=45, board='hot_drama', resume={'page': 2, 'page_url': p2})
    assert len(rows) == 20
    assert crawler.end_reason == 'site_end', 'the site attested the end of the list'
    assert crawler.walk_counts == {'scanned': 20, 'kept': 0, 'refused': 0}


def test_a_pager_pointing_back_at_itself_stops_without_licensing_the_short(make_crawler):
    crawler, driver = make_crawler({BOARD_URL: _board(_page_rows(1, 20), next_url=BOARD_URL)})
    rows = crawler.hot(target_count=45, board='hot_drama')
    assert len(rows) == 20
    assert driver.visited == [BOARD_URL], 'the replay URL must not be asked again'
    assert crawler.end_reason == UNDER_TARGET
    assert crawler.walk_counts == {'scanned': 20, 'kept': 20, 'refused': 0}


def test_the_sites_own_last_page_licenses_the_short(make_crawler):
    crawler, _driver = make_crawler({BOARD_URL: _board(_page_rows(1, 20), next_url='')})
    rows = crawler.hot(target_count=45, board='hot_drama')
    assert len(rows) == 20
    assert crawler.end_reason == 'site_end', 'the pager said there is no page after this one'
    assert crawler.walk_counts == {'scanned': 20, 'kept': 20, 'refused': 0}


def test_an_empty_list_the_server_attests_is_its_own_empty_and_a_bare_one_is_not(make_crawler):
    attested, _driver = make_crawler({BOARD_URL: _board([], is_success=True)})
    assert attested.hot(target_count=20, board='hot_drama') == []
    assert attested.end_reason == 'empty'

    bare, _driver = make_crawler({BOARD_URL: _board([], is_success=False)})
    assert bare.hot(target_count=20, board='hot_drama') == []
    assert bare.end_reason == UNDER_TARGET, 'an unattested empty is not licensed'


def test_a_card_without_a_name_or_an_id_is_counted_and_not_emitted(make_crawler):
    rows = _page_rows(1, 18) + [_work(19, rank=19, title=''), _work(20, rank=20, seriesId='', id='')]
    crawler, _driver = make_crawler({BOARD_URL: _board(rows, next_url='')})
    out = crawler.hot(target_count=20, board='hot_drama')
    assert len(out) == 18, 'a nameless or id-less card is not a work'
    assert crawler.walk_counts == {'scanned': 20, 'kept': 18, 'refused': 2}
    assert crawler.end_reason == 'site_end', 'the short is licensed by the pager, and its funnel is reported'


def test_the_page_the_site_does_not_serve_is_refused_by_name(make_crawler):
    """``?page=6`` renders the layout alone. A settled navigation with no loader key cannot be
    waited out, and it must not read as "this board is empty" either."""
    crawler, driver = make_crawler({})
    with pytest.raises(PageNotArrivedError) as caught:
        crawler.hot(target_count=5, board='hot_drama', resume={'page': 6, 'page_url': f'{BOARD_URL}?page=6'})
    assert driver.visited == [f'{BOARD_URL}?page=6']
    message = str(caught.value)
    assert f'{BOARD_URL}?page=6' in message, message
    assert 'rank_layout' in message, 'the refusal names what the page did carry'


def test_an_unknown_board_is_refused_by_name_before_a_browser_is_used(make_crawler):
    crawler, driver = make_crawler({BOARD_URL: _board(_page_rows(1, 20))})
    with pytest.raises(ValueError) as caught:
        crawler.hot(target_count=5, board='hot_drama2')
    assert 'hot_drama2' in str(caught.value)
    assert 'hot_comic_drama' in str(caught.value), 'the refusal names the boards that exist'
    assert driver.visited == []


def test_a_blank_board_is_the_panels_default_and_padding_folds_away():
    assert hongguo.hongguo_board('') == ('hot_drama', 'hot-drama', 'crawl.hg.boardHotDrama')
    assert hongguo.hongguo_board(None) == hongguo.hongguo_board(hongguo.DEFAULT_BOARD)
    assert hongguo.hongguo_board('  hot_ai_drama  ') == (
        'hot_ai_drama',
        'hot-ai-drama',
        'crawl.hg.boardAiDrama',
    )


def test_page_one_carries_no_parameter_because_the_site_treats_it_as_the_same_page():
    assert hongguo.hongguo_board_url('hot-drama', 1) == BOARD_URL
    assert hongguo.hongguo_board_url('hot-drama', 0) == BOARD_URL
    assert hongguo.hongguo_board_url('hot-drama', 2) == f'{BOARD_URL}?page=2'


# ─── the panel's side of the same fact ───


def test_the_panel_offers_exactly_the_boards_this_crawler_knows():
    mode = capabilities.mode_for('hongguo', 'hot')
    assert mode.handler == 'hot' and mode.needs_session is False
    field = next(f for f in mode.fields if f.key == 'board')
    assert [value for value, _label in field.options] == list(hongguo.BOARDS), 'same keys, same order'
    assert field.default == hongguo.DEFAULT_BOARD
    # The option *labels* are browser words, owned by ``app.js`` and checked there
    # (``test_frontend_contract.py`` walks every option of every declared select).
    assert len({label for _value, label in field.options}) == len(field.options), 'two boards share one label'


def test_every_board_label_the_crawler_logs_exists_in_both_languages():
    for _value, label in hongguo.BOARDS.values():
        assert label in i18n._ZH and label in i18n._EN, label
    assert 'crawl.hg.boardUnknown' in i18n._ZH and 'crawl.hg.boardUnknown' in i18n._EN
