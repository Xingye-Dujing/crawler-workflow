"""The scroll-and-harvest walk every infinite list shares.

Zhihu, Xiaohongshu and Weibo each carried their own copy of the same loop: read
the cards, skip the ones a resumed crawl already scanned, scrape one at a time,
hand each row to the sink, record the position, scroll, and give up when the page
stops growing. Three copies meant three ways to drift — and they had already
drifted: two of them disagreed about whether a re-scrape of a card the sink
refused should advance the cursor.

Nothing here touches Selenium. The caller supplies four callables (read the
cards, scrape one, scroll, may we stop?) so the loop itself is unit-testable with
lists, and so a platform with a different card type (an id, an element, a JSON
node) reuses it unchanged.

The settle wait is a *poll*, not a sleep: content that is already on screen costs
one tick, content that is slow still gets its full wait. Fixed sleeps are the
single largest avoidable cost in this project's crawls.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


def wait_for(measure: Callable[[], int], target: int, timeout: float = 1.5, tick: float = 0.25) -> int:
    """Poll *measure* until it returns at least *target*, or *timeout* is spent.

    Bounded by poll count rather than by a clock so the wait stays a pure function
    of the page — and stays instant under a fake driver in tests. Returns the last
    measured value; callers compare, they do not assume the target was reached.
    """
    seen = measure()
    for _ in range(max(1, int(timeout / tick))):
        if seen >= target:
            break
        time.sleep(tick)
        seen = measure()
    return seen


@dataclass
class FeedResult:
    """How a feed walk ended — the caller writes the platform's own log line."""

    collected: int = 0
    rounds: int = 0
    scanned: int = 0
    kept: int = 0
    refused: int = 0
    stuck: int = 0
    stopped_reason: str = ''
    positions: list = field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        """The list stopped growing: asking again would fetch the same cards."""
        return self.stopped_reason == 'stuck'


def walk_feed(
    read_cards: Callable[[], list],
    scrape: Callable[[object, int], dict | None],
    emit: Callable[[dict], bool],
    *,
    scroll: Callable[[], None],
    target: int,
    collected: Callable[[], int],
    start: int = 0,
    mark: Callable[[dict], None] | None = None,
    stopped: Callable[[], bool] | None = None,
    max_rounds: int = 12,
    stuck_rounds: int = 3,
    settle_wait: float = 1.5,
    grow_by: int = 1,
) -> FeedResult:
    """Harvest an infinite list until *target* rows, the list runs out, or it stalls.

    ``read_cards`` returns the currently rendered cards (any object; this loop
    never inspects them), ``scrape(card, index)`` turns one into a row or returns
    None for a card that holds nothing, and ``emit(row)`` answers whether the row
    was kept — the sink behind it is what drops a duplicate, which is exactly how
    a resumed crawl that re-reads its last page stays honest.

    ``start`` is where a resumed walk resumes: an *index into the rendered list*,
    not a count of rows, because the two differ as soon as one card is skipped.
    ``mark`` receives the position after every card, so a run killed mid-list
    resumes at the card it died on rather than at the top.
    """
    result = FeedResult(scanned=start)
    while result.rounds < max_rounds and collected() < target:
        if stopped is not None and stopped():
            result.stopped_reason = result.stopped_reason or 'stopped'
            break
        cards = read_cards() or []
        if not cards:
            # No cards at all is a page problem, not an empty result set: say
            # which, so the caller can tell "this keyword found nothing" apart
            # from "the list never mounted".
            result.stopped_reason = result.stopped_reason or 'no_cards'
            break
        first = min(result.scanned, len(cards))
        for index in range(first, len(cards)):
            if collected() >= target:
                break
            row = scrape(cards[index], index)
            result.scanned = index + 1
            if row is None:
                result.refused += 1
            elif emit(row):
                result.kept += 1
            else:
                result.refused += 1
            position = {'scanned': result.scanned, 'round': result.rounds, 'collected': collected()}
            result.positions.append(position)
            if mark is not None:
                mark(position)
        result.rounds += 1
        if collected() >= target:
            break
        before = len(cards)
        scroll()
        # Growth is *waited for*: the renderer needs a moment after the scroll,
        # and a loop that measures immediately sees the old count and calls the
        # list exhausted after one screen.
        grown = wait_for(lambda: len(read_cards() or []), before + grow_by, timeout=settle_wait) >= before + grow_by
        if grown:
            result.stuck = 0
            continue
        result.stuck += 1
        if result.stuck >= stuck_rounds:
            result.stopped_reason = 'stuck'
            break
    result.collected = collected()
    if not result.stopped_reason:
        result.stopped_reason = 'target' if result.collected >= target else 'rounds'
    return result
