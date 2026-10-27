"""Browser-free helpers shared by every platform's comment walk.

These are the small, dependency-light functions more than one adapter needs: the three status
verdicts a comment crawl can answer with, a count reader that never invents a number, and four pure
text helpers. Each platform's own parser and walk live in ``crawlers/platforms/<id>/comments.py``,
which imports what it needs from here; nothing re-exports this surface, so a helper has one name and
one home.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from crawlers.engine.counters import parse_count

#: One article can fail for different reasons and they must not blur:
#: ``ok`` (rows, maybe zero — zero means 无评论), ``blocked`` (risk-control or
#: login wall answered instead of content), ``dead`` (link unreadable/404).
OK = 'ok'
BLOCKED = 'blocked'
DEAD = 'dead'


def as_count(value) -> int:
    """A count the site may send as a number, as digits, or as 「1.2万」 text.

    ``parse_count`` is the engine's one answer for the last shape, so a denominator read from a payload
    goes through it rather than through a second ``int(...)`` that would raise on 「赞」 and be caught,
    hiding the fact that the page never gave a number.
    """
    if isinstance(value, (int, float)):
        return int(value)
    return parse_count(str(value or ''))


def _json_or_none(raw):
    """Parse an endpoint answer, treating anything unparseable as no answer.

    An HTML risk-control page served where JSON was expected is a refusal, not
    malformed data — the caller decides between ``blocked`` and ``dead``.
    """
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _strip_tags(html: str) -> str:
    text = re.sub(r'<[^>]+>', '', html or '')
    return re.sub(r'\s+', ' ', text).strip()


#: Comment timestamps are Beijing time too (see ``crawlers.core.video._stamp``); pinning the zone keeps a
#: crawler on a UTC server from shifting them back eight hours.
_CST = timezone(timedelta(hours=8))


def _stamp(value) -> str:
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return ''
    return datetime.fromtimestamp(seconds, tz=_CST).strftime('%Y-%m-%d %H:%M:%S') if seconds else ''


def _query_value(url: str, name: str) -> str:
    """One query parameter of an article link, without importing urllib per row."""
    match = re.search(rf'[?&]{name}=([^&#]+)', str(url or ''))
    if match:
        return match.group(1)
    # Shorts and lives spell the id in the path, and a link pasted from the share
    # sheet may be nothing but the id.
    match = re.search(r'/(?:shorts|live|embed)/([\w-]{6,20})', str(url or ''))
    if match:
        return match.group(1)
    text = str(url or '').strip()
    return text if re.fullmatch(r'[\w-]{11}', text) else ''
