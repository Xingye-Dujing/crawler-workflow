"""Timestamp shapes the sites hand back as text, turned into one readable form.

Mechanics only: it knows a *format*, not a platform. Several Chinese social APIs stamp their JSON
``created_at`` with the RFC-822-ish ``Wed Sep 24 15:42:51 +0800 2026`` (the shape ``Date.toString()``
produces client-side) — measured on weibo, all 72 comment timestamps and every author-path post in
``scratchpad/weibo_*.json`` are that shape. Shipping it raw into a column the user sorts, charts and
reads next to a ``09月26日 21:00`` label is the defect this ends; the label itself is the site's own
relative wording and stays the site's own wording.

Anything the strict pattern does not match is returned untouched — a relative label is what the site
chose to show, and inventing an absolute time for it would be worse than keeping the site's own words.
"""

from datetime import datetime

#: The one absolute shape these APIs emit, as ``strptime`` directives.
#: ``%a``/``%b`` are matched against the process's ``LC_TIME`` catalogue, and nothing in this program
#: calls ``setlocale``, so the English abbreviations are what matches — which is exactly what the sites
#: emit. A future ``setlocale(LC_TIME, '')`` would silently stop matching and hand back the raw stamp.
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
