"""小红书 links: the one place a note id is read out of a link.

A note link reaches this project in three spellings — ``/explore/<id>``, ``/discovery/item/<id>``
and ``/search_result/<id>`` (what the site's own 复制链接 hands out from a search) — and every one
of them needs the same 16+-hex id. Two callers ask: the search crawl (``_note_row`` keys a note on the
session-independent id, never on the tokenised link) and the comment walk (which refuses to file a
comment under a note the browser left). One regex, one answer, so the two cannot drift.
"""

import re
from urllib.parse import urlparse

_NOTE_RE = re.compile(r'/(?:search_result|explore|discovery/item|item)/([0-9a-f]{16,})')

#: The ``xsec_source`` value a note URL is opened with when it names none.
#:
#: Measured on the site's own 复制链接: a web-feed link arrives as
#: ``…?xsec_token=…&xsec_source=pc_feed``. A link with no source (or an empty one) is not the
#: same request to this site — it can land on the feed instead of the note — so the crawl fills
#: the one value the site itself uses for a note opened from the web. A link that already names
#: a source (``pc_search`` from a search result, ``pc_user`` from a profile) keeps it verbatim:
#: that source is part of what the site issued, not ours to rewrite.
FEED_SOURCE = 'pc_feed'

_SOURCE_RE = re.compile(r'([?&])xsec_source=([^&#]*)')


def note_id(link: str) -> str:
    """The session-independent note id in *link*, or ``''`` when it names none."""
    match = _NOTE_RE.search(str(link or ''))
    return match.group(1) if match else ''


def with_feed_source(link: str) -> str:
    """*link* with ``xsec_source=pc_feed`` filled in when it is missing or empty.

    Only a xiaohongshu URL is touched, and only that one parameter: the rest of the query
    (``xsec_token`` in particular) is passed through character-for-character — re-encoding the
    query would rewrite a signed token. An existing non-empty ``xsec_source`` is kept as it
    came, because the site issued it for the entry point the link was copied from.
    """
    raw = str(link or '').strip()
    if not raw:
        return raw
    host = (urlparse(raw).hostname or '').lower()
    if not (host == 'xiaohongshu.com' or host.endswith('.xiaohongshu.com')):
        return raw
    match = _SOURCE_RE.search(raw)
    if match:
        if match.group(2):
            return raw
        return raw[: match.start(2)] + FEED_SOURCE + raw[match.end(2) :]
    base, hash_sep, fragment = raw.partition('#')
    joiner = '&' if '?' in base else '?'
    return f'{base}{joiner}xsec_source={FEED_SOURCE}{hash_sep}{fragment}'
