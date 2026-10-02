"""Timestamp shapes the sites hand back as text, turned into one readable form.

Mechanics only: it knows *formats*, not a platform. Three families arrive here, all of them
measured on real pages:

* the RFC-822-ish ``Wed Sep 24 15:42:51 +0800 2026`` (the shape ``Date.toString()`` produces
  client-side) — measured on weibo, all 72 comment timestamps and every author-path post in
  ``scratchpad/weibo_*.json`` are that shape;
* the site's own absolute display form, ``2022年01月27日 00:59`` — measured on a weibo search
  export: 30000 of 30000 rows, the only shape in the column;
* the site's own RELATIVE wording, ``3小时前`` / ``昨天 21:30`` / ``2 days ago`` — what every
  one of these sites shows for anything recent.

The first two are exact. The third is not, and until now it was answered by keeping the
site's words (``normalise_rfc822`` returns anything it cannot parse untouched). That is
honest and it is also useless: a time-series built on it silently loses every recent row,
and the collector sees an empty 发布时间 for the posts that matter most. So a relative label
is CONVERTED here, at read time, against the wall clock of the read — and only a closed set
of shapes is recognised, because a permissive parser would write a fabricated time into
发布时间 (the coarsest date cells sometimes hold a topic tag like ``#2025年高考``, which is
why bilibili's author mode leaves unrecognised cells empty — see ``docs/crawler_notes.md``).

Read the two precisions apart, they are not the same claim:

* an OFFSET (``3小时前``, ``2 days ago``) names an instant relative to now, so
  ``now - 3 hours`` is what it says — the clock time survives;
* a NAMED DAY without a clock (``昨天``, ``前天``, ``yesterday``) names a *day*, not an
  instant. Its date is exact and its time of day is unknowable, so it is written as that
  day's ``00:00`` rather than dressed up as a real clock reading.
"""

import re
from datetime import datetime, timedelta

#: The one absolute shape these APIs emit, as ``strptime`` directives.
#: ``%a``/``%b`` are matched against the process's ``LC_TIME`` catalogue, and nothing in this program
#: calls ``setlocale``, so the English abbreviations are what matches — which is exactly what the sites
#: emit. A future ``setlocale(LC_TIME, '')`` would silently stop matching and hand back the raw stamp.
RFC822 = '%a %b %d %H:%M:%S %z %Y'
#: What a normalised timestamp looks like to the user.
READABLE = '%Y-%m-%d %H:%M'

#: The site's own absolute display form: ``2022年01月27日 00:59`` (``00:59`` optional).
CJK_ABSOLUTE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日(?:\s*(\d{1,2}):(\d{2}))?')

#: A named day with an optional clock, Chinese. ``昨天 21:30`` / ``前天21:30`` / ``今天 09:05``.
_CN_DAY = re.compile(r'^(今天|昨天|前天)\s*(?:(\d{1,2}):(\d{2}))?$')
_CN_DAY_OFFSET = {'今天': 0, '昨天': -1, '前天': -2}

#: Offsets, Chinese, largest unit first (``1小时前`` must not be read by a 秒 rule).
_CN_OFFSETS = (
    (re.compile(r'^(\d+)\s*秒前$'), 'seconds'),
    (re.compile(r'^(\d+)\s*分钟前$'), 'minutes'),
    (re.compile(r'^(\d+)\s*小时前$'), 'hours'),
    (re.compile(r'^(\d+)\s*天前$'), 'days'),
    (re.compile(r'^(\d+)\s*周前$'), 'weeks'),
)
#: ``刚刚``/``刚才``: the site's word for "this minute", which is now, to the minute.
_CN_NOW = re.compile(r'^(?:刚刚|刚才|片刻前|就在刚刚)$')

#: Offsets, English — the overseas platforms print these. ``an hour ago`` is the same shape
#: as ``1 hour ago`` and is listed rather than special-cased at the call site.
_EN_UNITS = {
    'second': 'seconds',
    'seconds': 'seconds',
    'minute': 'minutes',
    'minutes': 'minutes',
    'hour': 'hours',
    'hours': 'hours',
    'day': 'days',
    'days': 'days',
    'week': 'weeks',
    'weeks': 'weeks',
    'month': 'months',
    'months': 'months',
    'year': 'years',
    'years': 'years',
}
_EN_OFFSET = re.compile(r'^(?:(\d+)|an?|one)\s+(' + '|'.join(_EN_UNITS) + r')\s+ago$', re.IGNORECASE)
_EN_DAY = re.compile(r'^(today|yesterday)$', re.IGNORECASE)
_EN_DAY_OFFSET = {'today': 0, 'yesterday': -1}


def _shift(moment: datetime, unit: str, count: int) -> datetime:
    """``moment`` moved by ``count`` of ``unit``. Calendar units use ``timedelta``'s own
    approximation (30/365 days), which is what a site's "2 months ago" means anyway."""
    if unit == 'months':
        return moment - timedelta(days=30 * count)
    if unit == 'years':
        return moment - timedelta(days=365 * count)
    return moment - timedelta(**{unit: count})


def relative_to_absolute(value, now: datetime = None, fmt: str = READABLE) -> str:
    """A relative label as an absolute stamp, or ``''`` when it is not one we recognise.

    ``''`` rather than the input: this function ANSWERS "what time was this", and a caller
    that gets nothing back is expected to keep whatever it had. Recognising a shape is the
    whole admission test — anything outside the closed set below returns ``''``, so a topic
    tag or a layout string can never be turned into a timestamp.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    moment = now or datetime.now()
    if _CN_NOW.match(text):
        return moment.replace(second=0, microsecond=0).strftime(fmt)
    day = _CN_DAY.match(text)
    if day:
        offset = _CN_DAY_OFFSET[day.group(1)]
        base = (moment + timedelta(days=offset)).replace(second=0, microsecond=0)
        if day.group(2):
            base = base.replace(hour=int(day.group(2)), minute=int(day.group(3)))
        else:
            # A named day carries no clock: its DATE is exact, its time of day is not, so
            # the derived stamp sits at 00:00 instead of pretending to a real reading.
            base = base.replace(hour=0, minute=0)
        return base.strftime(fmt)
    english_day = _EN_DAY.match(text)
    if english_day:
        offset = _EN_DAY_OFFSET[english_day.group(1).lower()]
        base = (moment + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        return base.strftime(fmt)
    for pattern, unit in _CN_OFFSETS:
        found = pattern.match(text)
        if found:
            return _shift(moment, unit, int(found.group(1))).strftime(fmt)
    found = _EN_OFFSET.match(text)
    if found:
        count = int(found.group(1)) if found.group(1) else 1
        return _shift(moment, _EN_UNITS[found.group(2).lower()], count).strftime(fmt)
    return ''


def absolute(value, now: datetime = None, fmt: str = READABLE) -> str:
    """Anything the sites hand back, as an absolute ``YYYY-MM-DD HH:MM`` stamp.

    The one door for a platform module: RFC-822, the site's own CJK display form, and the
    relative wordings all arrive through it, so no platform holds its own opinion about
    which shapes exist. Anything unrecognised is returned UNCHANGED — the site's own words
    are still better than a fabricated time, and a caller that wants to know whether the
    answer is absolute can compare it with :func:`relative_to_absolute`'s empty answer.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.strptime(text, RFC822).strftime(fmt)
    except ValueError:
        pass
    found = CJK_ABSOLUTE.search(text)
    if found:
        year, month, day, hour, minute = found.groups()
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0)).strftime(fmt)
    relative = relative_to_absolute(text, now=now, fmt=fmt)
    return relative or text


def normalise_rfc822(value, fmt: str = READABLE) -> str:
    """``'Wed Sep 24 15:42:51 +0800 2026'`` → ``'2026-09-24 15:42'``; anything else, as it came.

    Kept as its own name because two call sites read the same stamp out of a JSON payload
    and neither should be the one that decides how many shapes exist.
    """
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        return datetime.strptime(text, RFC822).strftime(fmt)
    except ValueError:
        return text
