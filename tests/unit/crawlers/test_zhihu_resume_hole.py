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
