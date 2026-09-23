"""Reading values out of a site's embedded JSON without 40 lines of ``.get``.

The overseas platforms render their pages from a JSON tree that is already in the
document — YouTube ships ``ytInitialData`` / ``ytInitialPlayerResponse``,
douyin once shipped ``_ROUTER_DATA`` — and that tree is where the *exact*
figures live (``viewCount: "23,462,998"``) while the DOM shows a rounded label
(``2346万次观看``). Reaching into it turns a crawl of one navigation plus one
parse into something that needs no clicking and no per-card page visit.

Two shapes cover everything measured so far:

* a dotted path, for the known locations (``videoDetails.title``);
* a whole-tree search for a key, for the renderer nests whose intermediate
  names change between YouTube releases (``continuationItemRenderer`` today,
  something else next quarter) — a path would break, a key search will not.
"""


def get_in(node, path: str, default=None):
    """``get_in(data, 'videoDetails.author')`` — None (or *default*) if any step misses.

    A list index is written as a number segment (``tabs.1.tabRenderer.title``),
    because the alternative is a try/except tower at every call site.
    """
    current = node
    segments = [s for s in str(path or '').split('.') if s]
    if not segments:
        # An empty path asking for the root is a caller bug, and handing back the
        # whole tree would let it travel downstream as if it were a value.
        return default
    for segment in segments:
        if isinstance(current, dict):
            if segment not in current:
                return default
            current = current[segment]
            continue
        if isinstance(current, list):
            if not segment.isdigit():
                return default
            index = int(segment)
            if index >= len(current):
                return default
            current = current[index]
            continue
        return default
    return current if current is not None else default


def collect(node, key: str, _depth: int = 0) -> list:
    """Every value stored under *key* anywhere below *node*, in document order.

    Depth-capped: these trees nest a few dozen levels, and a cyclic object (a
    driver that hands back something surprising) must not hang a crawl.
    """
    out = []
    _walk_collect(node, key, _depth, out)
    return out


def _walk_collect(node, key: str, depth: int, out: list) -> None:
    if depth > 60 or len(out) >= 5000:
        return
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                out.append(value)
            _walk_collect(value, key, depth + 1, out)
    elif isinstance(node, list):
        for item in node:
            _walk_collect(item, key, depth + 1, out)


def first_key(node, key: str, default=None):
    """The first value stored under *key*, or *default*."""
    found = collect(node, key)
    return found[0] if found else default


def runs_text(node) -> str:
    """Flatten a ``{runs: [{text}]}`` / ``{simpleText: ...}`` label to a string.

    YouTube labels come in both shapes depending on the renderer, and the older
    ``content`` field appears on comment bodies; a caller that picked one would
    silently lose a row whenever the site switches.
    """
    if isinstance(node, str):
        return node.strip()
    if not isinstance(node, dict):
        return ''
    if isinstance(node.get('simpleText'), str):
        return node['simpleText'].strip()
    runs = node.get('runs')
    if isinstance(runs, list):
        parts = [str(r.get('text', '')) for r in runs if isinstance(r, dict)]
        return ''.join(parts).strip()
    if isinstance(node.get('content'), str):
        return node['content'].strip()
    return ''
