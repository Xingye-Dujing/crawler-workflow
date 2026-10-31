"""The in-process clock: fire scheduled canvases through the server's ONE start path.

The scheduler owns a clock and a history. It does NOT own a way to start a run: ``app.py`` injects
``start_scheduled_run`` (``set_run_starter``), so every scheduled execution goes through
``begin_run`` — the same validations, the same claim, the same queue a manual 执行 uses. A fire
while the server is busy is QUEUED, never refused and never a second, weaker execution path.

Two seams, both wired by ``app.py``:

* ``set_run_starter(fn)`` — turn one task into a run;
* ``set_canvas_source(fn)`` — the saved canvas a task names, or the reason it may not run on a
  timer (no such file, or steps that need a model — a scheduled run has no browser request behind
  it, so there is nowhere for an API key to come from).

Nothing here reads the clock in the thread's own time: ``tick(now)`` takes the moment from its
caller, so a rule can be driven across midnight, a restart or a DST edge without waiting for one.
The thread itself is started by ``app.py`` in the serving process only (never at import, so the
test suite is not run by a background clock it did not ask for).
"""

import logging
import os
import threading
from datetime import datetime

from core.config import Config
from runtime import account_context
from runtime.account_context import Account

from i18n import set_lang, t
from scheduling import cron, store

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread = None
_stop = None
_starter = None
_canvas_source = None
_last_tick = ''
_tick_count = 0
_fire_count = 0


# ─── Seams (wired by app.py) ───


def set_run_starter(fn) -> None:
    """Install the callable that starts a run for a task: ``fn(task, manual) -> {ok, ...}``."""
    global _starter
    _starter = fn


def set_canvas_source(fn) -> None:
    """Install the callable that resolves a canvas name: ``fn(name) -> {workflow, error}``."""
    global _canvas_source
    _canvas_source = fn


def load_canvas(name) -> dict:
    """The saved canvas a task names, or ``{'workflow': None, 'error': why-not}``.

    One answer for two callers: the save endpoint refuses a task whose canvas cannot run on a timer
    while the user is still looking at the form, and the fire path asks again at 03:00 if the file
    changed in between. Same function, so there is never a second opinion about what may run.
    """
    if _canvas_source is None:
        return {'workflow': None, 'error': t('sched.notWired')}
    try:
        answer = _canvas_source(str(name or '')) or {}
    except Exception as e:
        logger.exception(t('sched.canvasReadFailed', name=name))
        return {'workflow': None, 'error': str(e)[:200]}
    if not isinstance(answer, dict):
        return {'workflow': None, 'error': t('sched.notWired')}
    return {'workflow': answer.get('workflow'), 'error': str(answer.get('error') or '')}


# ─── Firing ───


def _scopes() -> list:
    """Every schedule owner the clock must look at (``None`` = the local owner).

    ``schedules.json`` is per-account, so one clock reads each owner's file in that owner's
    context — the same way a request would. A disabled account's timers do not fire.
    """
    from services.accounts.service import accounts_mode, get_account_service

    if not accounts_mode():
        return [None]
    rows = get_account_service().store.list_users()
    scopes = [Account(row['user_id'], row['username'], row['role']) for row in rows if row['status'] == 'active']
    return scopes or [None]


def tick(now: datetime = None) -> list:
    """Fire every task whose moment has arrived. One result per task fired.

    Held under one lock so a tick and a 立即执行 cannot both move the same task's clock, and so two
    ticks (a test's and the thread's) cannot fire one moment twice. A task whose stored moment
    cannot be read is SKIPPED rather than guessed at — re-saving it from the panel repairs it.
    """
    now = now or cron.now()
    results = []
    with _lock:
        for account in _scopes():
            with account_context.use(account):
                for task in store.all_tasks():
                    if not task.get('enabled'):
                        continue
                    due = store.stamp(task.get('next_run'))
                    if due is None or due > now:
                        continue
                    results.append(_fire(task, now))
    _note_tick(now)
    return results


def fire_now(task_id) -> dict:
    """Run one task right now, whatever its own clock says — the panel's 立即执行.

    A manual run is not the schedule: it is written into the task's history, and a cron slot keeps
    its wall clock (the store owns that rule).
    """
    task = store.get_task(task_id)
    if task is None:
        return {'ok': False, 'error': t('sched.taskMissing', id=str(task_id or ''))}
    with _lock:
        result = _fire(task, cron.now(), manual=True)
    return {'ok': result['status'] in ('started', 'queued'), 'result': result, 'error': result.get('note') or ''}


def _fire(task: dict, now: datetime, manual: bool = False) -> dict:
    """One attempt: ask the app to start the canvas, then write down what came back."""
    # This is the scheduler's own thread, and a thread-local language is not inherited: pin it from
    # the task, or a line written here would read in whatever language the last request happened to
    # leave behind (the task's language is also the language its run console will narrate in).
    set_lang(task.get('lang') or 'zh')
    name = str(task.get('name') or task.get('id') or '')
    crashed = False
    if _starter is None:
        answer = {'ok': False, 'error': t('sched.notWired')}
    else:
        try:
            answer = _starter(task, bool(manual)) or {}
        except Exception as e:  # a broken starter must not stop the clock for every other task
            logger.exception(t('sched.startFailed', name=name))
            answer = {'ok': False, 'error': str(e)[:200]}
            crashed = True
    if answer.get('ok'):
        status_token = 'queued' if answer.get('queued') else 'started'
        note = str(answer.get('note') or '')
        run_id = str(answer.get('run_id') or '')
    else:
        # A refusal is the executor saying no (a canvas that needs a model, a queue that is full);
        # a crash here is a bug, and the two read differently in the history a user comes back to.
        status_token = 'error' if crashed else 'refused'
        note = str(answer.get('error') or '')
        run_id = ''
    # ``status_token``, not ``status``: the module-level ``status()`` below is the clock
    # endpoint the panel reads, and naming a local after it made this function unable to
    # ask that question. The token is what the history row and 状态 chip carry.
    saved = store.record_event(task.get('id'), status_token, note=note, run_id=run_id, at=now, advance=not manual)
    _count_fire()
    return {
        'id': str(task.get('id') or ''),
        'name': name,
        'status': status_token,
        'note': note,
        'run_id': run_id,
        'manual': bool(manual),
        'next_run': str((saved or {}).get('next_run') or ''),
    }


# ─── The thread ───


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()


def start() -> bool:
    """Start the tick thread. Idempotent; called once, by the process that serves requests.

    Before the first tick, every moment that passed while the server was down is COUNTED
    (``store.note_missed``): a restart records what it missed, it does not replay it.
    """
    global _thread, _stop
    if is_running():
        return False
    for account in _scopes():
        with account_context.use(account):
            for name in store.note_missed():
                logger.info(t('sched.missedLine', name=name))
    _stop = threading.Event()
    _thread = threading.Thread(target=_loop, name='crawler-scheduler', daemon=True)
    _thread.start()
    return True


def stop(timeout: float = 2.0) -> None:
    """Stop the tick thread (tests, and a clean shutdown). Safe to call when it never started."""
    global _thread, _stop
    if _stop is not None:
        _stop.set()
    thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout)
    _thread = None
    _stop = None


def _loop() -> None:
    set_lang('zh')  # a fresh daemon starts at the default; pin it so its own lines are whole
    interval = max(5, int(Config.SCHEDULER_TICK_SECONDS or 20))
    while not _stop.wait(interval):
        try:
            tick()
        except Exception:
            logger.exception(t('sched.tickFailed'))


def _note_tick(now: datetime) -> None:
    global _last_tick, _tick_count
    _last_tick = now.isoformat()
    _tick_count += 1


def _count_fire() -> None:
    global _fire_count
    _fire_count += 1


def status() -> dict:
    """What the panel — and an operator — needs to see that the clock really is running.

    ``now_local`` ships already rendered because the reader is usually not on the machine: a Beijing
    screen watching a UTC box must see the SERVER's wall clock, and a moment the browser formats
    itself would be the browser's zone wearing the server's name.
    """
    now = cron.now()
    return {
        'running': is_running(),
        'wired': _starter is not None,
        'tick_seconds': max(5, int(Config.SCHEDULER_TICK_SECONDS or 20)),
        'last_tick': _last_tick,
        'ticks': _tick_count,
        'fires': _fire_count,
        'now': now.isoformat(),
        'now_local': now.astimezone().strftime('%Y-%m-%d %H:%M'),
        'local_zone': local_zone_name(),
    }


def local_zone_name() -> str:
    """What this machine calls its own zone, with its offset — the default for a task naming none.

    ``TZ`` first, because that is the honest answer on a cloud box and the one an operator sets
    (a UTC box and a Beijing box need different answers for 「每天 08:00」); then whatever the OS
    reports. The offset is appended because an abbreviation is not a location: ``CST`` is both
    China and US Central, and the panel prints this line as the answer to 「留空 = 服务器本地」.
    """
    name = str(os.environ.get('TZ') or '').strip() or (datetime.now().astimezone().tzname() or 'UTC')
    offset = datetime.now().astimezone().strftime('%z')
    return f'{name} UTC{offset[:3]}:{offset[3:]}' if len(offset) == 5 else name
