"""zhihu: a card that raised must not be recorded as read.

``_harvest`` advances ``cursor['scanned']`` per card so a kill costs at most the card in
flight. The exception branch used to advance it too, which turned "this card failed" into
"this card is done": the next round starts at ``cards[scanned:]`` and never looks at that
index again, so one stale element silently dropped a row for the rest of the run.

The same tolerance is why a 停止 used to look like a broken platform: 停止 reaps the driver
process, but the cards a round already holds keep talking to the session they were found
through, so every remaining card answered "invalid session id" and was logged as a card this
crawl could not read (measured: 19 stack traces after a stop at card 24 of 43). The stop is
asked of ``may_stop`` per card, exactly where ``feed.walk_feed`` asks it.
"""

import logging

import pytest

from crawlers.core.faults import CrawlerStopped
from crawlers.platforms.zhihu import crawler as zhihu
from crawlers.platforms.zhihu.crawler import ZhihuCrawler

pytestmark = pytest.mark.unit


class _Card:
    def __init__(self, index):
        self.index = index

    def get_attribute(self, name):
        return ''


class _Driver:
    def __init__(self, cards):
        self._cards = cards

    def find_elements(self, *_args, **_kwargs):
        return self._cards


def _crawler(cards, scrape):
    crawler = ZhihuCrawler.__new__(ZhihuCrawler)
    crawler.driver = _Driver(cards)
    crawler._collected = []
    crawler._scrape_card = scrape
    crawler.collected = lambda: len(crawler._collected)
    crawler.emit = lambda item: (crawler._collected.append(item), True)[1]
    marks = []
    crawler.mark_position = lambda **kwargs: marks.append(kwargs)
    return crawler, marks


def test_the_cursor_stops_behind_a_card_that_raised():
    def scrape(card):
        if card.index == 2:
            raise RuntimeError('stale element')
        return {'作者': f'u{card.index}', '正文': 'x'}

    crawler, marks = _crawler([_Card(1), _Card(2), _Card(3)], scrape)
    cursor = {'scanned': 0, 'total': 0}
    crawler._harvest(cursor, 100, {'want': False, 'short': 0, 'misses': 0})

    assert marks == [{'done': 1, 'scanned': 1}], f'the failure must not be recorded as scanned: {marks}'
    assert cursor['scanned'] == 1, 'the next round has to start at the card that failed'


def test_a_clean_round_still_advances_every_card():
    def scrape(card):
        return {'作者': f'u{card.index}', '正文': 'x'}

    crawler, marks = _crawler([_Card(1), _Card(2)], scrape)
    cursor = {'scanned': 0, 'total': 0}
    crawler._harvest(cursor, 100, {'want': False, 'short': 0, 'misses': 0})

    assert cursor['scanned'] == 2
    assert marks == [{'done': 1, 'scanned': 1}, {'done': 2, 'scanned': 2}]


def test_a_stop_inside_a_card_ends_the_round_instead_of_erroring_per_card(caplog):
    """The card in flight answers with a dead session; the rest must never be asked."""
    calls = []

    def scrape(card):
        calls.append(card.index)
        if card.index == 2:
            # Landing here IS what a stop looks like from a card: the reaper killed the driver
            # under this very command, so the refusal is about the session, not about the card.
            crawler._abort = lambda: True
            raise RuntimeError('Message: invalid session id')
        return {'作者': f'u{card.index}', '正文': 'x'}

    crawler, marks = _crawler([_Card(1), _Card(2), _Card(3)], scrape)
    with caplog.at_level(logging.ERROR), pytest.raises(CrawlerStopped):
        crawler._harvest({'scanned': 0, 'total': 0}, 100, {'want': False, 'short': 0, 'misses': 0})

    assert calls == [1, 2], f'the round kept reading cards off a session that was gone: {calls}'
    assert marks == [{'done': 1, 'scanned': 1}], f'only the card that landed is proven: {marks}'
    errors = [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors == [], f'a stop must not be printed as a card failure: {errors}'


def test_a_stop_before_the_first_card_never_touches_the_driver():
    """Stopping between two rounds costs the round, not one dead command per card."""
    calls = []

    def scrape(card):
        calls.append(card.index)
        return {'作者': f'u{card.index}', '正文': 'x'}

    crawler, marks = _crawler([_Card(1), _Card(2)], scrape)
    crawler._abort = lambda: True
    with pytest.raises(CrawlerStopped):
        crawler._harvest({'scanned': 0, 'total': 0}, 100, {'want': False, 'short': 0, 'misses': 0})

    assert not calls and not marks


def test_a_resumed_board_that_already_holds_the_target_is_not_called_short(monkeypatch, caplog):
    """A 继续 re-reads the whole board, so this attempt emits nothing new. The cap message and
    its ``capped`` end are claims about the SITE, and must be asked of the table's size."""

    items = [{'target': {'id': str(index), 'url': f'https://www.zhihu.com/question/{index}'}} for index in range(30)]
    instance = ZhihuCrawler.__new__(ZhihuCrawler)
    instance._collected = [{'链接': item['target']['url']} for item in items]
    instance._sink = None
    instance._cursor = {}
    instance._cursor_sink = None
    instance.driver = None
    instance.requests = []
    instance.login_wall = False
    instance.resume_of = lambda _kwargs: {'done': 0}  # the cursor lagged behind the stored rows
    instance.open = lambda _url: None
    instance.check_login_wall = lambda _url: None
    instance.mark_position = lambda **_kwargs: None
    ends = []
    instance.note_end = ends.append
    monkeypatch.setattr(zhihu.pagefetch, 'fetch_json', lambda *_args, **_kwargs: {'data': items})

    with caplog.at_level(logging.INFO):
        rows = instance.hot(target_count=30)

    assert len(rows) == 30
    assert ends == [], 'a board holding the whole target was licensed as short'
    assert 'hotCapped' not in caplog.text and '只有' not in caplog.text


def test_a_stopped_author_walk_does_not_open_the_second_tab(monkeypatch):
    """``feed.walk_feed`` honours 停止 by *returning*, and ``author`` walks two tabs. The second
    tab's first act is a navigation, so a stop must end the tab loop instead of driving a browser
    the stop thread may already have reaped — and the walk must stay unjudged (no UNDER_TARGET
    conviction), which is the pinned behaviour of ``tests/integration/test_zhihu_author.py``."""
    instance = ZhihuCrawler.__new__(ZhihuCrawler)
    instance._collected = []
    instance.driver = None
    instance.login_wall = False
    instance.risk_blocked = False
    instance.may_stop = lambda: True
    opened = []
    instance.open = opened.append
    ends = []
    instance.note_end = lambda reason, **_kwargs: ends.append(reason)
    instance._author_total = lambda: pytest.fail('a stopped walk has no denominator to read')

    rows = instance.author('zshu-83', target_count=50)

    assert not rows and not opened, f'a stop kept driving the browser: {opened}'
    assert not ends, f'a stop was relabelled: {ends}'
