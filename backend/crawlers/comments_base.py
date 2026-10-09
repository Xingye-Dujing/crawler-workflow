"""Browser-free helpers shared by every platform's comment parser.

These are the small, dependency-light functions more than one adapter needs:
the three status verdicts a comment crawl can answer with, and four pure text
helpers. The per-platform parsers live in their own ``comments_<platform>.py``
module and import what they need from here; ``comments.py`` re-exports the whole
public surface so the rest of the program can keep importing from one place.
"""

import json
import re
from datetime import datetime, timedelta, timezone

#: One article can fail for different reasons and they must not blur:
#: ``ok`` (rows, maybe zero — zero means 无评论), ``blocked`` (risk-control or
#: login wall answered instead of content), ``dead`` (link unreadable/404).
OK = 'ok'
BLOCKED = 'blocked'
DEAD = 'dead'


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


#: Comment timestamps are Beijing time too (see video_base._stamp); pinning the zone keeps a
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
