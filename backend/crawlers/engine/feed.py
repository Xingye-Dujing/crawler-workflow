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


def wait_for_change(measure: Callable[[], object], before, timeout: float = 1.5, tick: float = 0.25) -> bool:
    """Poll until ``measure()`` differs from *before* — the settle wait for a list
    that recycles instead of appending.

    A virtualized feed (X's timeline is the measured case: 13-21 ``<article>``
    nodes on screen while 139 distinct tweets passed through in eight scrolls)
    never grows its card count, so "did it get bigger" answers *no* on a list that
    is streaming new content, and a walk built on that returns one screen and calls
    it the end. "Did the window change" is the same question this list can answer.
    """
    for _ in range(max(1, int(timeout / tick))):
        if measure() != before:
            return True
        time.sleep(tick)
        if measure() != before:
            return True
    return False


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
    window: Callable[[], object] | None = None,
) -> FeedResult:
    """Harvest an infinite list until *target* rows, the list runs out, or it stalls.

    ``read_cards`` returns the currently rendered cards (any object; this loop
    never inspects them), ``scrape(card, index)`` turns one into a row or returns
    None for a card that holds nothing, and ``emit(row)`` answers whether the row
    was kept — the sink behind it is what drops a duplicate, which is exactly how
    a resumed crawl that re-reads its last page stays honest.

    ``window`` is how the walk notices that a scroll did anything, for the feeds
    whose card **count** is meaningless. An appending list (zhihu, xiaohongshu)
    needs nothing: more cards appear, the count rises. A virtualized one (X's
    timeline — measured 13-21 nodes on screen, 139 distinct tweets through eight
    scrolls) recycles its nodes, so the count is flat while content streams past,
    and a walk that waits for growth returns one screen and declares the list
    exhausted; it passes ``window=lambda: <identity of the rendered cards>``
    instead and waits for *that* to change.

    ``start`` is where a resumed walk resumes: an *index into the rendered list*,
    not a count of rows, because the two differ as soon as one card is skipped.
    A virtualized list has no stable index, so its crawler resumes by identity
    (the seen-id set it feeds back through ``scrape``) and leaves ``start`` at 0.
    ``mark`` receives the position after every card, so a run killed mid-list
    resumes at the card it died on rather than at the top.
    """
    result = FeedResult(scanned=start)
    watcher = window if window is not None else (lambda: len(read_cards() or []))
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
        first = 0 if window is not None else min(result.scanned, len(cards))
        # With a recycling window there is no offset into "the list" to resume
        # from — position N is a different tweet every round — so every screen is
        # read whole and the caller's identity set is what drops the repeats.
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
        before = watcher()
        scroll()
        # The settle is *waited for*: the renderer needs a moment after the
        # scroll, and a loop that measures immediately sees the old window and
        # calls the list exhausted after one screen. For an appending list the
        # default watcher is its card count, so "changed" and "grew" coincide;
        # for a recycled one it is the window's identity, which changes while
        # the count does not.
        grown = wait_for_change(watcher, before, timeout=settle_wait)
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
