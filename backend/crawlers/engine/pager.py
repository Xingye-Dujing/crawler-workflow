"""Paging that follows the server's cursor instead of a counter the site never promised.

Every platform here pages differently and every one of them has already bitten
once:

* Bilibili's ``next`` is a cursor, not a page number — ``next=0`` answers and
  reports ``cursor.next=2``, and asking for ``next=1`` replays page 0 byte for
  byte. An incrementing loop stored the same 19 comments forever.
* YouTube's continuation tokens are opaque and single-use; the *only* reliable
  way to know there is more is a ``continuationItemRenderer`` in the answer.
* Instagram's ``max_id`` is an end_cursor from the previous page.
* Bilibili's search pager skips page 1 entirely (``&page=1`` renders no cards).

So the loop lives here once: ask, take what is fresh, adopt the cursor the
*answer* carried, and stop on a page that added nothing — which is also what
makes a repeating server-side cursor harmless instead of an infinite loop.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class PageWalk:
    """Outcome of a cursor walk, so the caller can write its own log line."""

    pages: int = 0
    fresh: int = 0
    repeats: int = 0
    stopped_reason: str = ''
    cursor: object = None

    @property
    def drained(self) -> bool:
        """The server stopped handing us anything new (or said it was the end)."""
        return self.stopped_reason in ('no_new', 'end', 'empty_page')


def walk_pages(
    fetch: Callable[[object], object | None],
    extract: Callable[[object], tuple],
    emit: Callable[[object], bool],
    *,
    start_cursor: object = None,
    collected: Callable[[], int],
    target: int,
    max_pages: int = 40,
    seen: set | None = None,
    identity: Callable[[object], object] = lambda item: item,
    polite: Callable[[], None] | None = None,
    alive: Callable[[], bool] | None = None,
) -> PageWalk:
    """Follow a cursor until *target* rows are kept, the list drains, or it dies.

    ``fetch(cursor)`` returns the payload for that cursor (None = the request
    failed); ``extract(payload)`` returns ``(items, next_cursor)`` where
    ``next_cursor`` is **whatever the answer carried** — None means the server
    said it is finished. ``emit(row)`` answers whether the row was new.

    ``seen`` is the caller's job when an item's identity is not its own value:
    a resumed run hands back the ids it already stored so a re-read page cannot
    re-add them, and ``identity`` is how a dict row is reduced to its url/bvid.
    Items are deduped *before* ``emit`` only when ``seen`` is given; otherwise
    the sink decides, which is the right default (it holds the ledger).
    """
    walk = PageWalk(cursor=start_cursor)
    seen = seen
    while walk.pages < max_pages and collected() < target:
        if alive is not None and not alive():
            walk.stopped_reason = walk.stopped_reason or 'stopped'
            break
        payload = fetch(walk.cursor)
        if payload is None:
            # A failed page is not an empty site: keep what is on disk, say why.
            walk.stopped_reason = walk.stopped_reason or 'fetch_failed'
            break
        items, nxt = extract(payload)
        items = list(items or [])
        walk.pages += 1
        if not items:
            walk.stopped_reason = walk.stopped_reason or 'empty_page'
            break
        fresh_here = 0
        for item in items:
            # The target is honoured *within* a page too: a promise of 50 rows
            # must not become 65 because the endpoint answered one page deeper.
            if collected() >= target:
                break
            key = identity(item) if seen is not None else None
            if seen is not None and key in seen:
                walk.repeats += 1
                continue
            if seen is not None:
                seen.add(key)
            if emit(item):
                walk.fresh += 1
                fresh_here += 1
            else:
                walk.repeats += 1
        if collected() >= target:
            walk.stopped_reason = walk.stopped_reason or 'target'
            break
        if nxt is None:
            walk.stopped_reason = walk.stopped_reason or 'end'
            break
        # A page that carried nothing new is the end of the list even when the
        # server still hands out a cursor — this is precisely the bilibili
        # failure mode, where ``next=1`` replayed page 0 and an incrementing
        # loop would have stored the same comments forever.
        if fresh_here == 0:
            walk.stopped_reason = 'no_new'
            break
        walk.cursor = nxt
        if polite is not None:
            polite()
    if not walk.stopped_reason:
        walk.stopped_reason = 'target' if collected() >= target else 'max_pages'
    return walk
