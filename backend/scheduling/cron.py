"""Five-field cron: read it, refuse it, and answer when it fires next — stdlib only, no clock of its own.

The scheduler needs exactly three answers from a clock: does this expression mean anything, when
does it fire next, and does it ever fire at all. The grammar is small enough to own — a library
(``croniter``, APScheduler) would bring a second time-zone story and a second opinion about what a
field may hold — and the semantics are the ones a Linux box really runs (POSIX/Vixie): Sunday is
both ``0`` and ``7``, and a restricted day-of-month and day-of-week are OR'd, not AND'd.

Time zones come from ``zoneinfo`` (stdlib, so Linux reads the system database). An EMPTY zone name
means the server's own local zone and is left to ``datetime`` itself — the one thing that knows the
OS's rules, DST included. A wall-clock moment the zone skips (spring forward) is skipped the same
way the OS skips it; an ambiguous one (fall back) fires on its FIRST pass, once.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from i18n import t

#: The five fields, in the order they are written: 分 时 日 月 周.
FIELDS = ('minute', 'hour', 'day', 'month', 'weekday')

#: What each field may hold. ``weekday`` accepts 7 as well as 0 for Sunday (POSIX) and the 7 is
#: folded onto 0 before anything compares it, so ``0 9 * * 7`` and ``0 9 * * 0`` are one rule.
BOUNDS = {'minute': (0, 59), 'hour': (0, 23), 'day': (1, 31), 'month': (1, 12), 'weekday': (0, 7)}

#: One word per field, so a refusal names WHICH part of the expression it could not read instead of
#: pointing at the whole line. The keys are spelled out (never built with an f-string) because the
#: catalogue's reachability scan reads literals.
_FIELD_KEYS = {
    'minute': 'sched.cronMinute',
    'hour': 'sched.cronHour',
    'day': 'sched.cronDay',
    'month': 'sched.cronMonth',
    'weekday': 'sched.cronWeekday',
}

#: Three-letter names, the only alphabetic spellings a field takes. A full name (``January``) is
#: refused by name like any other unreadable value rather than being guessed at.
_MONTH_NAMES = {
    'jan': 1,
    'feb': 2,
    'mar': 3,
    'apr': 4,
    'may': 5,
    'jun': 6,
    'jul': 7,
    'aug': 8,
    'sep': 9,
    'oct': 10,
    'nov': 11,
    'dec': 12,
}
_WEEKDAY_NAMES = {'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6}
_NAME_KEYS = {'month': _MONTH_NAMES, 'weekday': _WEEKDAY_NAMES}

#: The macros ``crontab(5)`` allows. A line copied out of a crontab file works as typed instead of
#: being refused for having one field, which is the whole reason it exists.
MACROS = {
    '@yearly': '0 0 1 1 *',
    '@annually': '0 0 1 1 *',
    '@monthly': '0 0 1 * *',
    '@weekly': '0 0 * * 0',
    '@daily': '0 0 * * *',
    '@midnight': '0 0 * * *',
    '@hourly': '0 * * * *',
}

#: How far the search walks before concluding an expression never fires. It jumps a month/day/hour
#: at a time rather than minute by minute, so 4000 steps is well over 400 years — far past any rule
#: a person means, and the only specs that reach it are the impossible ones (``0 0 30 2 *``).
_MAX_STEPS = 4000

_DIGITS = re.compile(r'\d+')


class CronError(ValueError):
    """A refused expression, with the reason already worded in the caller's language."""


@dataclass(frozen=True)
class CronSpec:
    """A parsed expression: the values each field allows, and whether that field was ``*``.

    ``day_restricted`` / ``weekday_restricted`` are what make the POSIX OR rule possible — an
    unrestricted field takes no part in choosing the day, while a restricted one may.
    """

    raw: str
    minute: frozenset
    hour: frozenset
    day: frozenset
    month: frozenset
    weekday: frozenset
    day_restricted: bool
    weekday_restricted: bool


def now() -> datetime:
    """The clock, in UTC. One place to read it, so every caller and every test agrees."""
    return datetime.now(UTC)


def parse(expr) -> CronSpec:
    """The expression as a spec, or ``CronError`` naming the field that could not be read."""
    text = ' '.join(str(expr or '').split())
    if not text:
        raise CronError(t('sched.cronBadCount', n=0, expr=''))
    text = MACROS.get(text.lower(), text)
    parts = text.split()
    if len(parts) != len(FIELDS):
        raise CronError(t('sched.cronBadCount', n=len(parts), expr=text))
    values = {}
    restricted = {}
    for name, part in zip(FIELDS, parts, strict=True):
        values[name], restricted[name] = _parse_field(name, part)
    return CronSpec(
        raw=text,
        minute=values['minute'],
        hour=values['hour'],
        day=values['day'],
        month=values['month'],
        weekday=values['weekday'],
        day_restricted=restricted['day'],
        weekday_restricted=restricted['weekday'],
    )


def _parse_field(name: str, text: str) -> tuple:
    """The values one field allows, and whether it was written as ``*``."""
    lo, hi = BOUNDS[name]
    found = set()
    for chunk in text.split(','):
        base, step = chunk, 1
        if '/' in chunk:
            base, _, step_text = chunk.partition('/')
            # A step needs a range to walk: ``*/2`` and ``1-5/2`` mean something, ``3/2`` does not
            # (crons disagree about it, so guessing would be inventing a rule).
            if base.strip() not in ('*', '') and '-' not in base:
                raise CronError(t('sched.cronBadStepBase', field=t(_FIELD_KEYS[name]), value=chunk))
            step = _step(name, step_text, chunk)
        base = base.strip()
        if not base:
            raise CronError(t('sched.cronBadField', field=t(_FIELD_KEYS[name]), value=chunk))
        if base == '*':
            start, end = lo, hi
        elif '-' in base:
            first, _, last = base.partition('-')
            start, end = _value(name, first), _value(name, last)
            if start > end:
                raise CronError(t('sched.cronBadRange', field=t(_FIELD_KEYS[name]), value=chunk))
        else:
            start = end = _value(name, base)
        found.update(range(start, end + 1, step))
    if name == 'weekday' and 7 in found:
        found.discard(7)
        found.add(0)
    return frozenset(found), text.strip() != '*'


def _step(name: str, text: str, chunk: str) -> int:
    raw = text.strip()
    number = int(raw) if _DIGITS.fullmatch(raw) else 0
    if number < 1:
        raise CronError(t('sched.cronBadStep', field=t(_FIELD_KEYS[name]), value=chunk))
    return number


def _value(name: str, text: str) -> int:
    """One number or name as a field value, refused with the bound it broke."""
    raw = text.strip()
    named = (_NAME_KEYS.get(name) or {}).get(raw.lower())
    if named is not None:
        return named
    if not _DIGITS.fullmatch(raw):
        raise CronError(t('sched.cronBadField', field=t(_FIELD_KEYS[name]), value=text.strip()))
    number = int(raw)
    lo, hi = BOUNDS[name]
    if number < lo or number > hi:
        raise CronError(t('sched.cronOutOfRange', field=t(_FIELD_KEYS[name]), value=number, lo=lo, hi=hi))
    return number


def zone_for(name) -> tuple:
    """``(zone, '')`` for a name ``zoneinfo`` knows, ``(None, '')`` for the server's own zone, or
    ``(None, why-not)``.

    A blank name is a real answer, not a missing one: it means "this machine's clock", which is
    what an unconfigured cloud box (UTC) and a desktop in Beijing both really use.
    """
    text = str(name or '').strip()
    if not text:
        return None, ''
    try:
        return ZoneInfo(text), ''
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None, t('sched.badTimezone', name=text)


def next_after(spec: CronSpec, after: datetime, zone=None) -> datetime | None:
    """The first fire strictly after ``after``, or ``None`` when this rule never fires again.

    The search walks the CALENDAR rather than the clock: a month that cannot match jumps to the
    first of the next month, a day to the next midnight, an hour to the next o'clock, and only the
    minute field steps by one. A daily rule therefore costs a handful of steps instead of 1440.
    """
    after = _aware(after)
    ref = _in_zone(after, zone).replace(tzinfo=None)
    candidate = ref.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MAX_STEPS):
        if candidate.month not in spec.month:
            candidate = _first_of_next_month(candidate)
            continue
        if not _day_matches(spec, candidate):
            candidate = (candidate + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if candidate.hour not in spec.hour:
            candidate = (candidate + timedelta(hours=1)).replace(minute=0)
            continue
        if candidate.minute not in spec.minute:
            candidate += timedelta(minutes=1)
            continue
        fire = _localize(candidate, zone)
        if fire is not None and fire > after:
            return fire
        # A wall-clock minute the zone skips, or (at the very first candidate) a moment that the
        # zone's fall-back hour has already passed: step on rather than answer with a past time.
        candidate += timedelta(minutes=1)
    return None


def _aware(value: datetime) -> datetime:
    """A naive datetime is read as UTC — the only assumption that never guesses at a zone."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _in_zone(value: datetime, zone) -> datetime:
    return value.astimezone(zone) if zone is not None else value.astimezone()


def _localize(naive: datetime, zone) -> datetime | None:
    """Attach the zone to a wall-clock time, or answer ``None`` when that wall clock does not exist.

    A spring-forward hour is skipped by the OS itself, so a rule that lands inside it fires at the
    next wall clock that exists. The round trip is what detects it — and it is also why the same
    code path serves both an IANA zone and the machine's own.
    """
    aware = naive.replace(tzinfo=zone) if zone is not None else naive.astimezone()
    # The trip has to go through UTC: ``astimezone`` returns `self` unchanged when the zone object
    # is the one already attached, so converting "back" to the same zone would confirm a wall clock
    # the zone skips (2:30 on a spring-forward morning) as if it existed.
    back = aware.astimezone(UTC).astimezone(aware.tzinfo).replace(tzinfo=None)
    return None if back != naive else aware


def _day_matches(spec: CronSpec, moment: datetime) -> bool:
    """POSIX: when both day fields are restricted, either one matching is enough."""
    day_ok = moment.day in spec.day
    # ``isoweekday`` is Monday=1..Sunday=7; cron's own numbering is Sunday=0..Saturday=6.
    weekday_ok = (moment.isoweekday() % 7) in spec.weekday
    if spec.day_restricted and spec.weekday_restricted:
        return day_ok or weekday_ok
    if spec.day_restricted:
        return day_ok
    if spec.weekday_restricted:
        return weekday_ok
    return True


def _first_of_next_month(moment: datetime) -> datetime:
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return datetime(year, month, 1)
