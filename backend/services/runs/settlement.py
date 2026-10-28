"""Settling run records: what a stopped or abandoned run leaves behind, and who may say so.

Three of these are the difference between an honest panel and a lying one, and each was found by
a measurement, not by reading the code:

* :func:`mark_records_stopping` — 停止 answered the user immediately, but the worker still owed
  every record a verdict and that debt measurably takes tens of seconds; a row reading 运行中
  long after the button said 正在停止 is heard as 「停止没作用」.
* :func:`settle_orphaned_records` — ``promote_stale_runs`` used to run only at startup, so a
  record whose thread died with the window stayed on 运行中 until a restart; measured, the
  restart was faster than 停止, which is how the gap surfaced.
* :func:`reject_live_run` — deleting a run mid-flight pulls the rows and cursor out from under
  its writer. It must answer yes for as long as the worker's thread is alive, not merely while
  ``running`` is set, because after 停止 that is exactly the window where deleting hurts most.

``execute_lock`` lives in :mod:`state`: it is the same lock that claims a run, and a settle that
did not take it could settle a row a run an instant older had just opened.

The two lock-ledger functions are here for the same reason they are asked next to a settle: a
pin whose record is gone is state an abandoned path left behind, and every sweep — automatic or
manual — has to ask the same question about what the user pinned.
"""

import contextlib
import logging

from state import add_log, execute_lock, execution_state, live_run_ids
from stores import get_run_store

from i18n import t
from services import lock_store
from services.ingest.lifecycle import close_login_browser

logger = logging.getLogger(__name__)

#: How long a browser gets to close itself before 停止 kills its driver process.
#: Measured, the graceful answer is the fast one when it can be given at all: an idle
#: session quits in well under a second. What it can NEVER do is interrupt a command
#: already running — ``driver.quit()`` is an in-band request that chromedriver queues
#: *behind* the worker's own, so a Stop that waited on it watched the worker finish its
#: 40.0 s page load (or its 30.0 s in-page fetch) first. The kill is what ends a crawl;
#: this is only the grace given to a browser that is already done.
STOP_QUIT_GRACE = 0.8


def close_active_crawlers(quit_timeout: float = 3.0):
    """Close the login/crawl browsers of live sessions, one at a time.

    Used to run `taskkill /F /IM chromedriver.exe` — which killed every
    chromedriver on the machine, taking down unrelated Selenium apps and test
    runs. Each registered crawler is now quit with a bounded grace, and only a
    driver that ignores it is force-killed — by PID, tree included, so the
    chrome children of *this* session die with it.
    """
    for crawler in list(execution_state['active_crawlers']):
        close_login_browser(crawler, quit_timeout=quit_timeout)


def mark_records_stopping() -> None:
    """Flip the records this run owns from 运行中 to 正在停止, on this thread.

    The worker still owes each of them a verdict, and measured, that debt can take
    tens of seconds to pay. A row that reads 运行中 for that long after the button said
    正在停止 is read as "停止 did nothing" — which is the complaint this answers, and
    the reason it is written here rather than left to the unwinding thread.
    ``finish_run`` overwrites it with the real verdict when that thread arrives.
    """
    opened = list(execution_state['open_records'])
    if not opened:
        return
    try:
        store = get_run_store()
    except Exception as e:
        add_log(t('run.recordWriteFailed', rid=' + '.join(opened), err=e))
        return
    for rid in opened:
        try:
            store.mark_stopping(rid)
        except Exception as e:
            add_log(t('run.recordWriteFailed', rid=rid, err=e))


def settle_orphaned_records() -> int:
    """Settle a record this process opened and then abandoned without a verdict.

    ``promote_stale_runs`` only ever ran at startup, so a row whose write failed (a
    locked runs.db at exactly the wrong moment) or whose daemon thread died with the
    window stayed on 运行中 until the service was restarted. Measured: that restart was
    faster than 停止, which is how this gap was found.

    Two things keep it safe to ask the question of a live server. It is asked under
    ``execute_lock`` — the same lock that claims a run — so it cannot settle a row a
    run an instant older has just opened; and it is limited to ``owned_records``, the
    ids THIS process wrote, so a second instance's live run is none of its business.
    """
    thread = execution_state.get('thread')
    if execution_state['running'] or (thread is not None and thread.is_alive()):
        return 0
    owned = set(execution_state.get('owned_records') or set())
    if not owned:
        return 0
    with execute_lock:
        # Re-read inside the lock: a claim that started while we were deciding has
        # now either finished or cannot proceed.
        thread = execution_state.get('thread')
        if execution_state['running'] or (thread is not None and thread.is_alive()):
            return 0
        try:
            promoted = get_run_store().promote_stale_runs(
                only=owned,
                note=t('run.interrupted_by_dead_worker'),
            )
        except Exception:
            # A store we cannot open is a store we cannot settle; the panel says so
            # through its own error, and 运行中 is not a lie worse than no answer.
            return 0
    if promoted:
        # Said out loud because it otherwise looks like the panel decided to lie: a
        # row flips to 已中断 with no run having ended in front of the user.
        add_log(t('run.reconciled', n=len(promoted)))
    return len(promoted)


def reject_live_run(run_id: str) -> bool:
    """True when run_id names a run a live thread is still writing.

    Discarding or deleting it mid-flight would pull the rows and cursor out
    from under the writer — the UI's 丢弃/删除 must go through Stop first.

    "Go through Stop" is not the same as "Stop has been honoured": after 停止 the
    worker is still settling, still holding its browsers, and still writing rows, so
    the answer must be yes until its thread is actually gone. Reading only
    ``running`` refused the live run before the Stop and allowed it during the one
    window where deleting it is most destructive.
    """
    if not run_id:
        return False
    return str(run_id) in live_run_ids()


def locked_run_ids() -> set[str]:
    """Run ids the user pinned (置顶). Retention — automatic *or* manual — must spare
    them, exactly as 清空/删除 already do; otherwise a lock silently dies to age."""
    return {str(key) for key in (lock_store.all_locks().get('runs') or [])}


def prune_orphan_run_locks() -> None:
    """Forget 置顶 keys whose run row no longer exists. A record can be removed by a
    path that did not drop its lock; without this, locks.json accumulates dead ids."""
    with contextlib.suppress(Exception):
        existing = get_run_store().run_ids()
        for key in locked_run_ids():
            if key not in existing:
                lock_store.drop('runs', key)
