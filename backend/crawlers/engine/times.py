"""Timestamp shapes the sites hand back as text, turned into one readable form.

Mechanics only: it knows a *format*, not a platform. Several Chinese social APIs stamp their
``created_at`` with the RFC-822-ish ``Wed Sep 24 15:42:51 +0800 2026`` (the shape ``Date.toString()``
produces client-side), while the same field on another row of the same column reads ``09月26日 21:00``.
Two shapes in one column is what this helper exists to end: a chart or a sort over 发布时间/评论时间 cannot
compare an English month name with a Chinese one, and a user reading the table should not have to.

Anything the strict pattern does not match is returned untouched — a relative label is what the site
chose to show, and inventing an absolute time for it would be worse than keeping the site's own words.
"""

from datetime import datetime

#: The one absolute shape these APIs emit, as ``strptime`` directives.
RFC822 = '%a %b %d %H:%M:%S %z %Y'
#: What a normalised timestamp looks like to the user.
READABLE = '%Y-%m-%d %H:%M'


def normalise_rfc822(value, fmt: str = READABLE) -> str:
    """``'Wed Sep 24 15:42:51 +0800 2026'`` → ``'2026-09-24 15:42'``; anything else, as it came."""
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.strptime(text, RFC822).strftime(fmt)
    except ValueError:
        return text
