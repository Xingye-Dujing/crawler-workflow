"""Scheduled tasks: what to run, when, and what happened last time — ``data/schedules.json``.

A schedule is a UI intent, like a lock, not a property of the canvas it runs. The workflow file
goes on saying whatever it says; "every day at 08:00, this canvas, and last night it was refused"
lives here. One small JSON file under the data root (runtime state: gitignored, beside
``settings.json`` and ``locks.json``), written atomically and guarded by one lock.

The path is computed from ``Config.DATA_DIR`` on every call rather than bound at import, so the
test isolation (which redirects it before ``app`` is imported) lands schedules in the throwaway
root automatically — the same rule ``lock_store`` follows.

What a task's own history is NOT: an input. ``last_run``, ``missed`` and ``history`` are the
record of what the server did, so a request that carries them is ignored rather than believed.
"""

import contextlib
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta

from config import Config
from i18n import normalize as normalize_lang
from i18n import t
from services import cron
from utils.helpers import as_bool

logger = logging.getLogger('schedule_store')

_lock = threading.Lock()

#: How a task's moment is written. Every one of them is the user's own sentence, so the panel
#: offers them as presets and keeps whatever was chosen (never silently rewritten into a cron
#: string the user did not write).
TRIGGER_KINDS = ('daily', 'weekly', 'interval', 'cron')

#: One word per ISO weekday, for the sentence a weekly rule reads as.
_WEEKDAY_KEYS = {
    1: 'sched.weekday1',
    2: 'sched.weekday2',
    3: 'sched.weekday3',
    4: 'sched.weekday4',
    5: 'sched.weekday5',
    6: 'sched.weekday6',
    7: 'sched.weekday7',
}

#: A task keeps its last N events. The full narration of a run lives in the run's own console
#: (``run_log``); this list answers "what happened the last few times" without a second store.
HISTORY_MAX = 20

#: An interval is a period, and its ceiling is a week: anything longer is a daily/weekly rule, which
#: reads as a time of day instead of a number of minutes.
INTERVAL_MAX = 10080


def _path() -> str:
    return os.path.join(Config.DATA_DIR, 'schedules.json')


def _load() -> list:
    """The stored tasks, or an empty list when the file is missing.

    A file that cannot be read is moved aside (never deleted, never silently overwritten): the next
    save would otherwise replace whatever the user had with whatever this process could parse.
    """
    try:
        with open(_path(), encoding='utf-8') as f:
            stored = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        _quarantine()
        return []
    tasks = stored.get('tasks') if isinstance(stored, dict) else stored
    return [task for task in (tasks or []) if isinstance(task, dict)]


def _quarantine() -> None:
    """Keep an unreadable file for the person who wrote it, under a name nothing reads."""
    with contextlib.suppress(OSError):
        os.replace(_path(), _path() + '.corrupt')
    logger.warning(t('sched.storeUnreadable', path=_path()))


def _save(tasks: list) -> None:
    tmp = _path() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'tasks': tasks}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _path())


# ─── Time helpers ───


def stamp(value) -> datetime | None:
    """A stored ISO moment back as an aware datetime, or None when it is not one."""
    text = str(value or '').strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _iso(moment: datetime | None) -> str:
    return moment.isoformat() if moment is not None else ''


def next_fire(task: dict, after: datetime | None = None) -> datetime | None:
    """When this task fires next, or None when its rule never fires again.

    An interval is anchored to its OWN last fire (that is what "every 30 minutes" means), so its
    answer may already be in the past — ``_reanchor`` is what decides that a gone moment is
    recorded and skipped rather than replayed.
    """
    after = after or cron.now()
    trigger = task.get('trigger') or {}
    kind = trigger.get('kind')
    if kind == 'interval':
        base = stamp((task.get('last_run') or {}).get('at')) or stamp(task.get('created_at')) or after
        return base + timedelta(minutes=int(trigger.get('minutes') or 0))
    return _next_cron(task, after)


def _next_cron(task: dict, after: datetime) -> datetime | None:
    expr = trigger_cron(task.get('trigger') or {})
    zone, error = cron.zone_for(task.get('timezone'))
    if not expr or error:
        return None
    try:
        spec = cron.parse(expr)
    except cron.CronError:
        return None
    return cron.next_after(spec, after, zone)


def trigger_cron(trigger: dict) -> str:
    """The five-field expression a preset means, or the expression itself; '' for an interval.

    Presets expand here rather than at save time so the file keeps the user's own choice (「每天
    08:00」) and still has exactly one arithmetic behind it.
    """
    kind = (trigger or {}).get('kind')
    if kind == 'daily':
        hour, minute = _clock_parts(trigger.get('at'))
        return f'{minute} {hour} * * *'
    if kind == 'weekly':
        hour, minute = _clock_parts(trigger.get('at'))
        weekday = int(trigger.get('weekday') or 1)
        # ISO weekday 7 is Sunday, which cron writes as 0.
        return f'{minute} {hour} * * {0 if weekday == 7 else weekday}'
    if kind == 'cron':
        return ' '.join(str(trigger.get('expr') or '').split())
    return ''


def _clock_parts(at) -> tuple:
    """``'08:30'`` → ``(8, 30)``. Only ever called on a value ``normalize`` already accepted."""
    text = str(at or '')
    hour, _, minute = text.partition(':')
    try:
        return int(hour), int(minute)
    except ValueError:
        return 0, 0


def _reanchor(task: dict, now: datetime) -> datetime | None:
    """The task's next fire, moved into the future; a moment already gone is recorded, not replayed.

    The same rule the restart path applies: a cloud box that was down is not owed a burst of
    catch-up runs. Returns None when the rule never fires again.
    """
    moment = next_fire(task, now)
    if moment is None or moment > now:
        return moment
    _push_miss(task, moment, now)
    trigger = task.get('trigger') or {}
    if trigger.get('kind') == 'interval':
        # An interval is a period, so its anchor is the moment that just passed: start the next
        # one from here rather than from the schedule's stale anchor.
        return now + timedelta(minutes=int(trigger.get('minutes') or 0))
    # A cron rule is strictly-after by construction, so this answer is already in the future.
    return _next_cron(task, now)


def _push_miss(task: dict, moment: datetime, now: datetime) -> None:
    missed = task.setdefault('missed', {'count': 0, 'last_at': ''})
    missed['count'] = int(missed.get('count') or 0) + 1
    missed['last_at'] = _iso(moment)
    task['history'] = (
        [{'at': _iso(now), 'status': 'missed', 'run_id': '', 'note': _iso(moment)}] + list(task.get('history') or [])
    )[:HISTORY_MAX]


# ─── Validation ───


def normalize(raw, existing: dict = None, now: datetime = None) -> tuple:
    """The stored shape for one task, or the name of what is wrong with it.

    ``existing`` is the record being edited: its id and its history survive, so saving the form
    again never re-mints an id (which records and cursors key on) and never erases what ran.
    """
    now = now or cron.now()
    if not isinstance(raw, dict):
        return {}, t('sched.badTask')
    name = str(raw.get('name') or '').strip()
    if not name:
        return {}, t('sched.nameRequired')
    if len(name) > 60:
        return {}, t('sched.nameTooLong', n=60)
    workflow = str(raw.get('workflow') or '').strip()
    if not workflow:
        return {}, t('sched.workflowRequired')
    trigger, error = _normalize_trigger(raw.get('trigger'))
    if error:
        return {}, error
    zone_name = str(raw.get('timezone') or '').strip()
    # The zone OBJECT is not kept: the task stores the name and the clock resolves it at each
    # fire (``cron.zone_for`` beside ``next_run_local``). Asking for it here is how a name
    # ``zoneinfo`` refuses never reaches a stored task.
    _, error = cron.zone_for(zone_name)
    if error:
        return {}, error
    previous = existing or {}
    task = {
        'id': str(previous.get('id') or raw.get('id') or uuid.uuid4().hex[:12]),
        'name': name,
        'workflow': workflow,
        'lang': normalize_lang(raw.get('lang') or previous.get('lang')),
        'enabled': as_bool(raw.get('enabled'), True),
        'trigger': trigger,
        'timezone': zone_name,
        'created_at': str(previous.get('created_at') or raw.get('created_at') or _iso(now)),
        'updated_at': _iso(now),
        'last_run': previous.get('last_run') or {},
        'missed': previous.get('missed') or {'count': 0, 'last_at': ''},
        'history': list(previous.get('history') or []),
        'next_run': str(previous.get('next_run') or ''),
    }
    return task, ''


def _normalize_trigger(raw) -> tuple:
    if not isinstance(raw, dict):
        return {}, t('sched.badTrigger', kind='')
    kind = str(raw.get('kind') or '').strip()
    if kind not in TRIGGER_KINDS:
        return {}, t('sched.badTrigger', kind=kind)
    if kind == 'interval':
        minutes = _number(raw.get('minutes'))
        if minutes is None or minutes < 1 or minutes > INTERVAL_MAX:
            return {}, t('sched.badInterval', value=str(raw.get('minutes') or ''), hi=INTERVAL_MAX)
        return {'kind': 'interval', 'minutes': minutes}, ''
    if kind in ('daily', 'weekly'):
        hour, minute = _clock(raw.get('at'))
        if hour is None:
            return {}, t('sched.badClock', at=str(raw.get('at') or ''))
        clean = {'kind': kind, 'at': f'{hour:02d}:{minute:02d}'}
        if kind == 'weekly':
            weekday = _number(raw.get('weekday'))
            if weekday is None or not 1 <= weekday <= 7:
                return {}, t('sched.badWeekday', value=str(raw.get('weekday') or ''))
            clean['weekday'] = weekday
        return clean, ''
    expr = ' '.join(str(raw.get('expr') or raw.get('cron') or '').split())
    try:
        return {'kind': 'cron', 'expr': cron.parse(expr).raw}, ''
    except cron.CronError as e:
        return {}, str(e)


def _clock(at) -> tuple:
    """``'8:05'`` / ``'08:05'`` → ``(8, 5)``; ``(None, None)`` when it is not a time of day.

    One-digit hours and minutes are zero-padded rather than refused: ``8:5`` means 08:05 to anyone
    who types it, and the stored value is canonical anyway. What IS refused is anything else —
    a bare ``8`` is a number, not a time.
    """
    text = str(at or '').strip()
    hour, sep, minute = text.partition(':')
    if not sep or not hour.isdigit() or not minute.isdigit():
        return None, None
    number = int(hour), int(minute)
    if number[0] > 23 or number[1] > 59:
        return None, None
    return number


def _number(value):
    """An int from a JSON number or a digit string; None for anything else (never a 0 default)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or '').strip()
    return int(text) if text.isdigit() else None


# ─── Reads ───


def all_tasks() -> list:
    with _lock:
        return _load()


def get_task(task_id) -> dict | None:
    wanted = str(task_id or '')
    for task in all_tasks():
        if str(task.get('id')) == wanted:
            return task
    return None


def public(task: dict) -> dict:
    """The row the panel reads: the stored task plus the strings only the server renders.

    What a trigger MEANS and when it fires next are computed once, here, in the task's own zone —
    the browser may well be in another one (a Beijing screen on a UTC cloud box), so a date it
    formats itself would name a moment the schedule does not mean.
    """
    trigger = task.get('trigger') or {}
    return {
        'id': str(task.get('id') or ''),
        'name': str(task.get('name') or ''),
        'workflow': str(task.get('workflow') or ''),
        'lang': str(task.get('lang') or 'zh'),
        'enabled': bool(task.get('enabled')),
        'trigger': dict(trigger),
        'trigger_text': describe_trigger(trigger),
        'timezone': str(task.get('timezone') or ''),
        'timezone_label': zone_label(task.get('timezone')),
        'next_run': str(task.get('next_run') or ''),
        'next_run_local': describe_time(task.get('next_run'), task.get('timezone')),
        'last_run': dict(task.get('last_run') or {}),
        'last_run_local': describe_time((task.get('last_run') or {}).get('at'), task.get('timezone')),
        'missed': dict(task.get('missed') or {'count': 0, 'last_at': ''}),
        'history': list(task.get('history') or []),
        'created_at': str(task.get('created_at') or ''),
        'updated_at': str(task.get('updated_at') or ''),
    }


def public_all() -> list:
    return [public(task) for task in all_tasks()]


def zone_label(name) -> str:
    """The word for the zone a task's clock is read in (blank = this machine's own)."""
    return str(name or '').strip() or t('sched.zoneLocal')


def describe_trigger(trigger: dict) -> str:
    kind = (trigger or {}).get('kind')
    if kind == 'daily':
        return t('sched.everyDay', at=str((trigger or {}).get('at') or ''))
    if kind == 'weekly':
        key = _WEEKDAY_KEYS.get(int((trigger or {}).get('weekday') or 0))
        return t('sched.everyWeek', weekday=t(key) if key else '', at=str((trigger or {}).get('at') or ''))
    if kind == 'interval':
        return t('sched.everyMinutes', n=int((trigger or {}).get('minutes') or 0))
    return t('sched.cronAt', expr=str((trigger or {}).get('expr') or ''))


def describe_time(value, zone_name) -> str:
    """A stored moment in the task's own zone, with the zone named (the screen may be elsewhere)."""
    moment = stamp(value)
    if moment is None:
        return ''
    zone, error = cron.zone_for(zone_name)
    if error:
        return ''
    local = moment.astimezone(zone) if zone is not None else moment.astimezone()
    return f'{local.strftime("%Y-%m-%d %H:%M")} ({zone_label(zone_name)})'


# ─── Writes ───


def save_task(raw, now: datetime = None) -> tuple:
    """Create or update one task, keeping every id that already exists.

    Returns ``(task, '')`` or ``({}, why-not)``. The moment it will next fire is computed here, so
    a rule that never fires is refused now — while the user is looking at the box that wrote it —
    instead of at 03:00 on the machine nobody is watching.
    """
    now = now or cron.now()
    wanted = str((raw or {}).get('id') or '') if isinstance(raw, dict) else ''
    with _lock:
        tasks = _load()
        existing = next((task for task in tasks if str(task.get('id')) == wanted), None) if wanted else None
        task, error = normalize(raw, existing, now)
        if error:
            return {}, error
        moment = _reanchor(task, now)
        if moment is None:
            return {}, t('sched.neverFires', expr=trigger_cron(task.get('trigger') or {}) or task.get('timezone') or '')
        task['next_run'] = _iso(moment)
        tasks = [task if str(item.get('id')) == task['id'] else item for item in tasks]
        if existing is None:
            tasks.append(task)
        _save(tasks)
        return task, ''


def delete_task(task_id) -> bool:
    wanted = str(task_id or '')
    with _lock:
        tasks = _load()
        kept = [task for task in tasks if str(task.get('id')) != wanted]
        if len(kept) == len(tasks):
            return False
        _save(kept)
        return True


def set_enabled(task_id, enabled, now: datetime = None) -> tuple:
    """Switch one task on or off. Switching it ON re-reads the clock, so a task that slept through
    its own moments comes back with a next fire in the future rather than one in the past."""
    now = now or cron.now()
    wanted = str(task_id or '')
    with _lock:
        tasks = _load()
        found = next((task for task in tasks if str(task.get('id')) == wanted), None)
        if found is None:
            return {}, t('sched.taskMissing', id=wanted)
        found['enabled'] = as_bool(enabled, True)
        found['updated_at'] = _iso(now)
        found['next_run'] = _iso(_reanchor(found, now)) if found['enabled'] else ''
        _save(tasks)
        return found, ''


def record_event(
    task_id, status: str, note: str = '', run_id: str = '', at: datetime = None, advance: bool = True
) -> dict | None:
    """One fire (started / queued / refused / error) written into the task's own history.

    ``advance`` is False for a manual 立即执行: a button is not the schedule, so a cron slot keeps
    its wall clock. An interval has no wall clock to keep — its period is anchored to its last fire
    — so it re-anchors either way.
    """
    now = at or cron.now()
    wanted = str(task_id or '')
    with _lock:
        tasks = _load()
        task = next((item for item in tasks if str(item.get('id')) == wanted), None)
        if task is None:
            return None
        entry = {'at': _iso(now), 'status': status, 'run_id': str(run_id or ''), 'note': str(note or '')}
        task['history'] = ([entry] + list(task.get('history') or []))[:HISTORY_MAX]
        task['last_run'] = entry
        task['updated_at'] = _iso(now)
        anchor_moved = (task.get('trigger') or {}).get('kind') == 'interval'
        if task.get('enabled') and (advance or anchor_moved):
            task['next_run'] = _iso(_reanchor(task, now))
        _save(tasks)
        return task


def note_missed(now: datetime = None) -> list:
    """Record every enabled task whose moment passed while nobody was ticking.

    Called once at boot, before the first tick. The moment is COUNTED, never replayed: a server
    that was down for a week does not owe the user seven crawls, and collecting yesterday's board
    twice is not repair. Returns the names of the tasks that missed a moment.
    """
    now = now or cron.now()
    missed = []
    with _lock:
        tasks = _load()
        for task in tasks:
            if not task.get('enabled'):
                continue
            moment = stamp(task.get('next_run'))
            if moment is None or moment > now:
                continue
            _push_miss(task, moment, now)
            task['next_run'] = _iso(_reanchor(task, now))
            task['updated_at'] = _iso(now)
            missed.append(str(task.get('name') or task.get('id') or ''))
        if missed:
            _save(tasks)
        return missed
