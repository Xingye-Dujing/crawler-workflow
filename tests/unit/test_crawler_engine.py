"""The shared crawl mechanics: counters, JSON trees, wall verdicts, scrolling, paging, dialogs.

These six modules are what the nine platform crawlers are built on, so a bug here
is a bug on every platform at once. They are also the reason the same loop used to
be open-coded three times (and drifted: two copies disagreed about whether a card
the sink refused should still advance the cursor).

No Selenium anywhere: every test drives the loops with lists and callables, which
is the point of the callable-based API.
"""

import json

import pytest

from crawlers.engine import popup
from crawlers.engine.counters import clean, first_int, has_count, parse_count, to_int
from crawlers.engine.feed import wait_for, walk_feed
from crawlers.engine.jsonpath import collect, first_key, get_in, runs_text
from crawlers.engine.pager import walk_pages
from crawlers.engine.wall import looks_like_login_page

pytestmark = pytest.mark.unit

# ─── counters ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('5.9万', 59000),
        ('1千', 1000),
        ('2 亿', 200000000),
        ('1,027,710次观看', 1027710),
        ('2346万次观看', 23460000),
        ('97 views', 97),
        ('1.2w', 12000),
        ('3K', 3000),
        ('12M', 12000000),
        ('分享', 0),
        ('', 0),
        (None, 0),
        (12, 12),
        (0, 0),
        ('  6 条 ', 6),
        # A bool is never a count, but it must not raise either.
        (True, 1),
    ],
)
def test_parse_count_reads_every_label_shape(text, expected):
    assert parse_count(text) == expected


def test_parse_count_takes_the_first_number_of_a_compound_label():
    """``回复 3`` and ``1.5万 播放量 200`` — the leading figure is the one wanted."""
    assert parse_count('1.5万播放量200') == 15000
    assert first_int('23,462,998次观看') == 23462998
    # The rounded label and the exact figure are different questions on purpose.
    assert parse_count('23,462,998次观看') == 23462998


@pytest.mark.parametrize(('text', 'expected'), [('5.9万', True), ('分享', False), ('0', True), (None, False)])
def test_has_count_separates_zero_from_unreadable(text, expected):
    assert has_count(text) is expected


def test_clean_collapses_the_separators_a_rendered_counter_carries():
    assert clean(' 1,027,710\n次 ') == '1027710次'
    assert clean(None) == ''
    assert clean(12.5) == '12.5'


@pytest.mark.parametrize(('value', 'expected'), [(None, 0), ('', 0), ('3', 3), ('1.2万', 12000), ('abc', 0), (True, 1)])
def test_to_int_degrades_instead_of_raising(value, expected):
    assert to_int(value) == expected


def test_to_int_keeps_a_supplied_default():
    assert to_int(None, default=7) == 7
    assert to_int('nonsense', default=-1) == -1


# ─── jsonpath ────────────────────────────────────────────────────────

TREE = {
    'contents': {'tabs': [{'tabRenderer': {'title': {'simpleText': '热门'}}}, {'tabRenderer': {}}]},
    'videoDetails': {'title': '甲', 'viewCount': '123'},
    'deep': {'a': {'videoId': 'x1'}},
    'list': [{'videoId': 'x2'}, {'nested': {'videoId': 'x3'}}],
}


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        ('videoDetails.title', '甲'),
        ('contents.tabs.0.tabRenderer.title.simpleText', '热门'),
        ('contents.tabs.1.tabRenderer.missing', None),
        ('videoDetails.nope', None),
        ('videoDetails.title.deeper', None),
        ('contents.tabs.9.title', None),
        ('', None),
    ],
)
def test_get_in_walks_dicts_and_numeric_list_indexes(path, expected):
    assert get_in(TREE, path) == expected


def test_get_in_can_answer_with_a_default():
    assert get_in(TREE, 'videoDetails.absent', default='') == ''


def test_collect_finds_every_value_under_a_key():
    assert sorted(collect(TREE, 'videoId')) == ['x1', 'x2', 'x3']
    assert first_key(TREE, 'videoId') == 'x1'
    assert first_key(TREE, 'absent', default='none') == 'none'


def test_collect_survives_a_self_referencing_tree():
    """A driver that hands back something surprising must not hang the crawl."""
    node = {'a': {}}
    node['a']['b'] = node
    assert collect(node, 'videoId') == []


def test_continuation_tokens_are_read_in_document_order_where_the_api_needs_it():
    """The innertube helper keeps the site's order instead of guessing by length.

    Which is not a rule for *choosing* one: the two measurements recorded in
    ``innertube.pager_tokens`` point opposite ways, so the helper hands over all
    of them and the caller decides — the comment walk by trying, the list pager by
    the markup that marks it.
    """
    from crawlers.engine.innertube import grid_token, pager_tokens

    tree = {
        'a': {'continuationCommand': {'token': 'S' * 78}},
        'b': [{'continuationCommand': {'token': 'L' * 1112}}],
        'c': {'continuationCommand': {'token': ''}},
        'd': {'clickTrackingParams': 'T' * 900},
    }
    assert pager_tokens(tree) == ['S' * 78, 'L' * 1112]
    # Unmarked by ``continuationItemRenderer``, none of them is a list pager.
    assert grid_token(tree) == ''
    marked = {'x': {'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': 'PAGE2'}}}}}
    assert grid_token(marked) == 'PAGE2'


def test_a_pager_is_chosen_by_the_list_it_pages():
    """``pager_of`` — the rule that keeps a comment walk from stalling at page one.

    Measured on a live comment round, which carries three kinds of continuation
    token: two 78-character sort-menu switches that both answer **page one again**,
    one ``continuationItemRenderer`` nested inside every thread that has replies,
    and the list's own pager as the last element of the list. Only the last one
    grows the crawl, so the pager is picked by the list it belongs to and by being
    an element of it — not by length, not by "the first token in the answer".
    """
    from crawlers.engine.innertube import grid_token, pager_of

    def thread(index, reply_pager=''):
        nested = {'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': reply_pager}}}}
        entry = {'commentThreadRenderer': {'comment': {'commentEntityPayload': {'key': f'cid{index}'}}}}
        if reply_pager:
            entry['commentThreadRenderer']['replies'] = {'commentRepliesRenderer': {'subThreads': [nested]}}
        return entry

    round_one = {
        'onResponseReceivedEndpoints': [
            {
                'reloadContinuationItemsCommand': {
                    'continuationItems': [
                        {
                            'commentsHeaderRenderer': {
                                'sortMenu': {
                                    'sortFilterSubMenuRenderer': {
                                        'subMenuItems': [
                                            {'serviceEndpoint': {'continuationCommand': {'token': 'SORT' * 20}}}
                                        ]
                                    }
                                }
                            }
                        }
                    ]
                }
            },
            {
                'reloadContinuationItemsCommand': {
                    'continuationItems': [
                        thread(1, reply_pager='REP' * 30),
                        thread(2),
                        {
                            'continuationItemRenderer': {
                                'continuationEndpoint': {'continuationCommand': {'token': 'PAGE2'}}
                            }
                        },
                    ]
                }
            },
        ]
    }
    assert pager_of(round_one, 'commentThreadRenderer') == 'PAGE2'
    # Nothing in the answer is such a list, so there is no pager — rather than
    # the sort menu's, which would read page one forever.
    assert pager_of(round_one, 'noSuchRenderer') == ''
    # A video list is found the same way; with no such list, grid_token falls back
    # to the longest pager the markup marks.
    tab = {
        'contents': {'a': [{'videoRenderer': {'videoId': 'v'}}]},
        'trailing': {'continuationItemRenderer': {'continuationEndpoint': {'continuationCommand': {'token': 'GRID2'}}}},
    }
    assert grid_token(tab) == 'GRID2'


@pytest.mark.parametrize(
    ('node', 'expected'),
    [
        ({'simpleText': '甲'}, '甲'),
        ({'runs': [{'text': 'a'}, {'text': 'b'}]}, 'ab'),
        ({'content': '评论正文'}, '评论正文'),
        ('裸字符串', '裸字符串'),
        ({'runs': [{'noText': 1}]}, ''),
        (None, ''),
        (42, ''),
    ],
)
def test_runs_text_flattens_every_label_shape(node, expected):
    assert runs_text(node) == expected


# ─── wait_for ────────────────────────────────────────────────────────


def test_wait_for_pays_no_time_when_the_content_is_already_there(monkeypatch):
    from crawlers.engine import feed as feed_module

    slept = []
    monkeypatch.setattr(feed_module.time, 'sleep', lambda s: slept.append(s))
    assert wait_for(lambda: 9, 1) == 9
    assert slept == []


def test_wait_for_keeps_polling_until_the_target_or_the_budget(monkeypatch):
    from crawlers.engine import feed as feed_module

    monkeypatch.setattr(feed_module.time, 'sleep', lambda s: None)
    ticks = {'n': 0}

    def growing():
        ticks['n'] += 1
        return ticks['n']

    assert wait_for(growing, 3, timeout=1.5, tick=0.5) == 3
    assert wait_for(growing, 100, timeout=1.0, tick=0.5) < 100


# ─── jump_to_bottom ──────────────────────────────────────────────────


class ScrollDriver:
    def __init__(self, raises=False):
        self.calls = []
        self.raises = raises

    def execute_script(self, script, *args):
        self.calls.append((script, args))
        if self.raises:
            raise RuntimeError('dead session')
        return 'container'


def test_jump_to_bottom_hands_the_anchor_to_the_page_as_an_argument():
    """The selector is an argument, never interpolated into the script: the anchors
    that reach here include ones pasted from a user's address bar, and a page
    script built by string concatenation would be an injection point with a
    selector in it. The hunt order is the measured one — the anchor's own
    scrollable ancestor, then the biggest scroller, then the window."""
    from crawlers.engine.feed import jump_to_bottom

    driver = ScrollDriver()
    assert jump_to_bottom(driver, '[data-e2e="user-post-list"]') == 'container'
    script, args = driver.calls[0]
    assert args == ('[data-e2e="user-post-list"]', '')
    assert 'scrollerFrom' in script and 'scrollTop = target.scrollHeight' in script
    assert 'user-post-list' not in script, 'the selector must not be baked into the script'


def test_jump_to_bottom_passes_a_secondary_anchor_before_giving_up_on_the_page():
    """A grid whose own node is a non-scrolling shell needs the second selector
    (the comment panel passes it), and a page with neither still has to move."""
    from crawlers.engine.feed import jump_to_bottom

    driver = ScrollDriver()
    jump_to_bottom(driver, '[data-e2e="comment-list"]', '[data-e2e="comment-item"]')
    assert driver.calls[0][1] == ('[data-e2e="comment-list"]', '[data-e2e="comment-item"]')

    dead = ScrollDriver(raises=True)
    assert jump_to_bottom(dead, '[data-e2e="user-post-list"]') == 'none'


# ─── walk_feed ───────────────────────────────────────────────────────


class Feed:
    """A list that grows (or does not) on command."""

    def __init__(self, cards, grows_by=0):
        self.cards = list(cards)
        self.grows_by = grows_by
        self.scrolled = 0

    def read(self):
        return list(self.cards)

    def scroll(self):
        self.scrolled += 1
        if self.grows_by:
            start = len(self.cards)
            self.cards += [f'c{i}' for i in range(start, start + self.grows_by)]


def harvest(cards=('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'), grows_by=0):
    feed = Feed(cards, grows_by)
    kept = []

    result = walk_feed(
        feed.read,
        lambda card, index: {'v': card, 'i': index},
        lambda row: (kept.append(row), True)[1],
        scroll=feed.scroll,
        target=99,
        collected=lambda: len(kept),
        max_rounds=4,
        stuck_rounds=2,
    )
    return feed, kept, result


def test_walk_feed_scrapes_every_card_in_order():
    _feed, kept, result = harvest()
    assert [row['v'] for row in kept] == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
    assert result.collected == 8


def test_a_card_that_holds_nothing_is_refused_and_the_walk_continues():
    feed = Feed(['a', 'b'])
    kept = []
    result = walk_feed(
        feed.read,
        lambda card, index: None if card == 'a' else {'v': card},
        lambda row: (kept.append(row), True)[1],
        scroll=feed.scroll,
        target=99,
        collected=lambda: len(kept),
        max_rounds=1,
    )
    assert kept == [{'v': 'b'}]
    assert result.refused == 1


def test_a_row_the_sink_refuses_counts_as_a_repeat_not_a_new_item():
    """A resumed crawl re-reads its last page; those rows are already on disk."""
    feed = Feed(['a', 'b'])
    seen = []
    result = walk_feed(
        feed.read,
        lambda card, index: {'v': card},
        lambda row: False,
        scroll=feed.scroll,
        target=99,
        collected=lambda: 0,
        max_rounds=1,
    )
    assert result.kept == 0 and result.refused == 2
    assert seen == []


def test_resumed_walk_starts_at_the_recorded_card_index():
    feed = Feed(['a', 'b', 'c', 'd'])
    kept = []
    walk_feed(
        feed.read,
        lambda card, index: {'v': card, 'i': index},
        kept.append,
        scroll=feed.scroll,
        target=99,
        collected=lambda: len(kept),
        start=2,
        max_rounds=1,
    )
    assert [row['v'] for row in kept] == ['c', 'd']
    assert [row['i'] for row in kept] == [2, 3]


def test_position_is_recorded_after_every_card_so_a_kill_resumes_mid_list():
    feed = Feed(['a', 'b', 'c'])
    marks = []
    walk_feed(
        feed.read,
        lambda card, index: {'v': card},
        lambda row: True,
        scroll=feed.scroll,
        target=99,
        collected=lambda: 0,
        mark=marks.append,
        max_rounds=1,
    )
    assert [m['scanned'] for m in marks] == [1, 2, 3]
    assert all('collected' in m for m in marks)


def test_a_list_that_stops_growing_ends_the_walk_as_stuck():
    """The virtualised lists recycle: the count is proof, and one screen is the answer."""
    feed, _kept, result = harvest(cards=('a', 'b'), grows_by=0)
    assert result.stopped_reason == 'stuck'
    assert result.stuck == 2
    assert feed.scrolled == 2


def test_a_growing_list_is_walked_until_the_target_is_met():
    feed = Feed(['a', 'b'], grows_by=2)
    kept = []
    result = walk_feed(
        feed.read,
        lambda card, index: {'v': card},
        lambda row: (kept.append(row), True)[1],
        scroll=feed.scroll,
        target=5,
        collected=lambda: len(kept),
        max_rounds=6,
    )
    assert result.collected == 5
    assert result.stopped_reason == 'target'


def test_an_empty_read_is_reported_as_no_cards_not_as_an_empty_search():
    feed = Feed([])
    result = walk_feed(
        feed.read,
        lambda card, index: {},
        lambda row: True,
        scroll=feed.scroll,
        target=10,
        collected=lambda: 0,
    )
    assert result.stopped_reason == 'no_cards'
    assert feed.scrolled == 0


def test_the_walk_stops_at_once_when_the_caller_says_the_session_died():
    feed = Feed(['a', 'b'])
    calls = {'n': 0}

    def dying():
        calls['n'] += 1
        return calls['n'] > 1

    result = walk_feed(
        feed.read,
        lambda card, index: {'v': card},
        lambda row: True,
        scroll=feed.scroll,
        target=99,
        collected=lambda: 0,
        stopped=dying,
        max_rounds=5,
    )
    assert result.stopped_reason == 'stopped'
    # One round was already under way when the session died: the walk must not
    # keep scrolling after that, and one scroll is what the first round costs.
    assert feed.scrolled == 1


def test_the_scroller_is_asked_to_settle_before_the_growth_is_measured(monkeypatch):
    """Reading the count the instant after a scroll sees the old number and calls
    the list exhausted — the settle wait is what makes 'stuck' mean stuck."""
    from crawlers.engine import feed as feed_module

    monkeypatch.setattr(feed_module.time, 'sleep', lambda s: None)
    feed = Feed(['a'], grows_by=1)
    kept = []
    walk_feed(
        feed.read,
        lambda card, index: {'v': card},
        lambda row: True,
        scroll=feed.scroll,
        target=4,
        collected=lambda: len(kept),
        settle_wait=1.0,
        max_rounds=6,
    )
    assert feed.scrolled >= 1


# ─── walk_pages ──────────────────────────────────────────────────────


def server(pages, cursor_key='next'):
    """A fake endpoint keyed by the cursor it was handed; returns (items, next)."""

    def fetch(cursor):
        payload = pages.get(cursor if cursor is not None else 'start')
        if payload is None:
            return None
        return payload

    def extract(payload):
        return payload['items'], payload.get('next')

    return fetch, extract


def test_paging_follows_the_cursor_the_answer_carried_not_a_counter():
    """Bilibili measured this: ``next=0`` answers and reports ``cursor.next=2``.

    An incrementing loop would then request ``next=1``, get page 0 back again and
    store the same comments forever.
    """
    pages = {
        'start': {'items': [{'id': 1}, {'id': 2}], 'next': 2},
        2: {'items': [{'id': 3}], 'next': 7},
        7: {'items': [{'id': 4}], 'next': None},
    }
    fetch, extract = server(pages)
    kept = []
    walk = walk_pages(
        fetch,
        extract,
        lambda row: kept.append(row) or True,
        collected=lambda: len(kept),
        target=99,
    )
    assert [row['id'] for row in kept] == [1, 2, 3, 4]
    assert walk.pages == 3 and walk.stopped_reason == 'end'


def test_a_replaying_server_cursor_ends_the_walk_instead_of_looping():
    pages = {'start': {'items': [{'id': 1}], 'next': 2}, 2: {'items': [{'id': 1}], 'next': 3}}
    fetch, extract = server(pages)
    walk = walk_pages(
        fetch,
        extract,
        lambda row: True,
        collected=lambda: 0,
        target=99,
        seen=set(),
        identity=lambda row: row['id'],
    )
    assert walk.stopped_reason == 'no_new'
    assert walk.pages == 2


def test_a_failed_page_keeps_what_was_already_collected():
    pages = {'start': {'items': [{'id': 1}], 'next': 2}}
    fetch, extract = server(pages)
    kept = [{'id': 1}]
    walk = walk_pages(
        fetch,
        extract,
        lambda row: True,
        collected=lambda: len(kept),
        target=99,
    )
    assert walk.stopped_reason == 'fetch_failed'
    assert walk.fresh == 1


def test_an_empty_page_is_the_end_of_the_list():
    pages = {'start': {'items': [], 'next': 5}}
    fetch, extract = server(pages)
    walk = walk_pages(fetch, extract, lambda row: True, collected=lambda: 0, target=9)
    assert walk.stopped_reason == 'empty_page' and walk.pages == 1


def test_already_seen_ids_are_never_re_emitted():
    pages = {'start': {'items': [{'id': 1}, {'id': 2}], 'next': None}}
    fetch, extract = server(pages)
    kept = []
    walk = walk_pages(
        fetch,
        extract,
        lambda row: kept.append(row['id']) or True,
        collected=lambda: len(kept),
        target=99,
        seen={'1'},
        identity=lambda row: str(row['id']),
    )
    assert kept == [2]
    assert walk.repeats == 1


def test_the_walk_stops_at_the_target_without_reading_a_whole_page_extra():
    pages = {'start': {'items': [{'id': i} for i in range(1, 6)], 'next': 2}, 2: {'items': [{'id': 9}], 'next': None}}
    fetch, extract = server(pages)
    count = {'n': 0}
    walk = walk_pages(
        fetch,
        extract,
        lambda row: (count.update(n=count['n'] + 1), True)[1],
        collected=lambda: count['n'],
        target=3,
    )
    assert count['n'] == 3 and walk.pages == 1 and walk.stopped_reason == 'target'


def test_max_pages_bounds_a_server_that_never_says_stop():
    def fetch(cursor):
        return {'items': [{'id': cursor or 0}], 'next': (cursor or 0) + 1}

    walk = walk_pages(
        fetch,
        lambda payload: (payload['items'], payload['next']),
        lambda row: True,
        collected=lambda: 0,
        target=10_000,
        max_pages=4,
    )
    assert walk.pages == 4 and walk.stopped_reason == 'max_pages'


def test_the_caller_can_stop_the_walk_between_pages():
    pages = {'start': {'items': [{'id': 1}], 'next': 2}, 2: {'items': [{'id': 2}], 'next': None}}
    fetch, extract = server(pages)
    alive = {'n': 0}

    def stop_after_one():
        alive['n'] += 1
        return alive['n'] < 2

    walk = walk_pages(fetch, extract, lambda row: True, collected=lambda: 0, target=9, alive=stop_after_one)
    assert walk.stopped_reason == 'stopped' and walk.pages == 1


def test_polite_is_called_between_pages_not_after_the_last_one():
    pages = {'start': {'items': [{'id': 1}], 'next': None}}
    fetch, extract = server(pages)
    calls = []
    walk_pages(fetch, extract, lambda row: True, collected=lambda: 0, target=9, polite=lambda: calls.append(1))
    assert calls == []


# ─── popup ───────────────────────────────────────────────────────────


class DialogDriver:
    """Stands in for a browser sitting on a page with (or without) a dialog."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.scripts = []
        self.payloads = []
        self.timeouts = []

    def set_script_timeout(self, seconds):
        self.timeouts.append(seconds)

    def execute_async_script(self, script, *args):
        self.scripts.append(script)
        # The payload reaches the page as a Python object (Selenium encodes it),
        # so the double-encoded string form is what must not happen here.
        self.payloads.append(list(args[0]) if args and isinstance(args[0], list) else list(args))
        return self.replies.pop(0) if self.replies else json.dumps({'clicked': None, 'matched': None, 'seen': []})


def test_a_matching_button_is_clicked_and_the_outcome_names_it():
    driver = DialogDriver([json.dumps({'clicked': '是', 'matched': '是否将信息保存到设备', 'seen': ['是', '否']})])
    out = popup.dismiss(driver, (popup.DOUYIN_TRUST_LOGIN,))
    assert out == [{'key': 'douyin_trust_login', 'clicked': '是', 'matched': '是否将信息保存到设备', 'seen': []}]


def test_a_dialog_we_cannot_answer_is_reported_with_what_the_page_offers():
    """A re-skin must say what it now offers, or the fix is a guess."""
    driver = DialogDriver([json.dumps({'clicked': None, 'matched': '打开通知', 'seen': ['开启', '稍后再说']})])
    out = popup.dismiss(driver, (popup.INSTAGRAM_NOTIFICATIONS,))
    assert out[0]['clicked'] == ''
    assert out[0]['seen'] == ['开启', '稍后再说']


def test_a_page_with_no_dialog_costs_two_looks_and_no_click():
    driver = DialogDriver([])
    assert popup.dismiss(driver, (popup.DOUYIN_TRUST_LOGIN,), tries=3, tick=0.001) == []
    assert len(driver.scripts) == 2


def test_a_platform_that_declares_nothing_never_runs_the_script():
    driver = DialogDriver([])
    assert popup.dismiss(driver, ()) == []
    assert driver.scripts == []


def test_the_prompt_spec_reaches_the_page_as_data():
    driver = DialogDriver([json.dumps({'clicked': '以后再说', 'matched': '打开通知'})])
    popup.dismiss(driver, (popup.INSTAGRAM_NOTIFICATIONS,))
    spec = driver.payloads[0][0]
    assert spec['markers'] and '以后再说' in spec['choose']
    assert '打开' in spec['forbid'], '「打开」 opens a native permission prompt no DOM click can close'


def test_the_instagram_answer_is_the_no_and_not_the_yes():
    """Both labels exist on that dialog; only one of them is the user's answer."""
    assert '以后再说' in popup.INSTAGRAM_NOTIFICATIONS.choose
    assert '打开' in popup.INSTAGRAM_NOTIFICATIONS.forbid


def test_the_douyin_dialog_is_declined_never_accepted():
    """Measured wording: 「是否保存登录信息超过5天」 with 「保存」/「取消」.

    保存 is on the forbidden list on purpose: the user reports it walks into a
    phone-verification step, so the crawler declines instead of taking the
    site's offer.
    """
    assert popup.DOUYIN_TRUST_LOGIN.choose == ('取消',)
    assert '保存' in popup.DOUYIN_TRUST_LOGIN.forbid
    assert '是' in popup.DOUYIN_TRUST_LOGIN.forbid
    assert any('保存登录信息' in marker for marker in popup.DOUYIN_TRUST_LOGIN.markers)


def test_the_click_candidates_include_the_elements_douyin_builds_its_buttons_from():
    """That dialog's buttons are divs, so a button-only query finds nothing."""
    assert 'div' in popup.DISMISS_JS and 'span' in popup.DISMISS_JS


def test_a_driver_that_raises_is_not_a_crawl_failure():
    class Broken(DialogDriver):
        def execute_async_script(self, script, *args):
            raise RuntimeError('renderer died')

    assert popup.dismiss(Broken([]), (popup.DOUYIN_TRUST_LOGIN,), tries=1, tick=0.001) == []


@pytest.mark.parametrize('prompt', [popup.DOUYIN_TRUST_LOGIN, popup.INSTAGRAM_NOTIFICATIONS, popup.YOUTUBE_CONSENT])
def test_every_declared_prompt_is_sendable_and_has_an_answer(prompt):
    payload = prompt.as_js()
    assert set(payload) == {'selector', 'markers', 'choose', 'forbid'}
    assert payload['choose'], 'a prompt with no button to press is a wait, not a dismiss'
    assert not set(payload['choose']) & set(payload['forbid']), 'the yes and the no must not be the same word'


def test_the_dialog_probe_and_click_are_one_round_trip():
    """A dialog that auto-dismisses between two calls would be half-handled."""
    assert 'getBoundingClientRect' in popup.DISMISS_JS
    assert popup.DISMISS_JS.count('done(') >= 1
    assert looks_like_login_page('https://x.com/i/flow/login', '') is True
