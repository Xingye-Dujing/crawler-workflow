"""zhihu: a card that raised must not be recorded as read.

``_harvest`` advances ``cursor['scanned']`` per card so a kill costs at most the card in
flight. The exception branch used to advance it too, which turned "this card failed" into
"this card is done": the next round starts at ``cards[scanned:]`` and never looks at that
index again, so one stale element silently dropped a row for the rest of the run.
"""

import pytest

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


def test_a_resumed_board_that_already_holds_the_target_is_not_called_short(monkeypatch, caplog):
    """A 继续 re-reads the whole board, so this attempt emits nothing new. The cap message and
    its ``capped`` end are claims about the SITE, and must be asked of the table's size."""
    import logging

    from crawlers.platforms.zhihu import crawler as zhihu

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
