"""小红书 links: the one place a note id is read out of a link.

A note link reaches this project in three spellings — ``/explore/<id>``, ``/discovery/item/<id>``
and ``/search_result/<id>`` (what the site's own 复制链接 hands out from a search) — and every one
of them needs the same 16+-hex id. Two callers ask: the search crawl (``_note_row`` keys a note on the
session-independent id, never on the tokenised link) and the comment walk (which refuses to file a
comment under a note the browser left). One regex, one answer, so the two cannot drift.
"""

import re

_NOTE_RE = re.compile(r'/(?:search_result|explore|discovery/item|item)/([0-9a-f]{16,})')


def note_id(link: str) -> str:
    """The session-independent note id in *link*, or ``''`` when it names none."""
    match = _NOTE_RE.search(str(link or ''))
    return match.group(1) if match else ''
