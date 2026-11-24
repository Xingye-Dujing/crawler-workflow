"""Stop: the verdict is the worker's, the browsers are this module's.

``stop_run`` is what ``/api/workflow/stop`` and the AI's ``workflow_stop`` tool both call. Guard and
writes share ``execute_lock`` with the claim, so a run finishing right now cannot hand the slot to a
queued one and then have ``running=False``/``stopping=True`` land on that brand-new run. The worker
still writes the verdict; this only says "the user stopped it" and closes the browsers it owned —
in its own thread, because a visible Chrome may take its bounded grace to die and the Stop request
must not hang behind it.
"""

import threading

from runtime import account_context
from runtime.state import execute_lock, execution_state, run_is_foreign

from i18n import get_lang, set_lang, t
from services.ingest.lifecycle import close_login_browser
from services.runs.settlement import STOP_QUIT_GRACE, close_active_crawlers, mark_records_stopping


def _reap_login_browser(crawler, lang: str, owner) -> None:
    """Close one browser this run owned, in its own thread and under the account it ran as."""
    token = account_context.bind(owner)
    try:
        set_lang(lang)
        close_login_browser(crawler, quit_timeout=STOP_QUIT_GRACE)
    finally:
        account_context.unbind(token)


def _finish_stop(crawlers, lang: str, owner, stopped_run_id: str) -> None:
    """The side of Stop that may take seconds: reap every browser, then register the verdict."""
    token = account_context.bind(owner)
    try:
        set_lang(lang)
        reapers = [
            threading.Thread(target=_reap_login_browser, args=(crawler, lang, owner), daemon=True)
            for crawler in crawlers
        ]
        for reaper in reapers:
            reaper.start()
        for reaper in reapers:
            reaper.join(STOP_QUIT_GRACE + 12)
        # A browser registered AFTER the snapshot above is still in the registry; nothing else on
        # this path reaches a node that is standing in a page load.
        close_active_crawlers(quit_timeout=STOP_QUIT_GRACE, run_id=stopped_run_id)
    finally:
        account_context.unbind(token)


def stop_run() -> dict:
    """Stop the account's live run; the HTTP route and the AI tool both call THIS function.

    Guard and writes share ``execute_lock`` with ``begin_run``, so a run finishing right now cannot
    hand the slot to a queued one and then have ``running=False``/``stopping=True`` land on that
    brand-new run. The verdict itself is still written by the worker's ``settle``; this only says
    "the user stopped it" and closes the browsers it owned.
    """
    with execute_lock:
        thread = execution_state.get('thread')
        if run_is_foreign():
            return {'status': 409, 'body': {'ok': False, 'error': t('api.foreignRun')}}
        if not execution_state['running'] and not (thread is not None and thread.is_alive()):
            # Nothing running and nothing unwinding: answering as if a stop had been honoured
            # would leave ``stopping`` set, and the NEXT run would read it as "the user stopped me".
            return {'status': 200, 'body': {'ok': True, 'browsers': 0, 'records': [], 'idle': True}}
        if execution_state['executor']:
            execution_state['executor'].stop()
        # Finished rows are checkpointed; this asks the row loop to bail at the next boundary.
        execution_state['cancel_event'].set()
        execution_state['stopping'] = True
        execution_state['running'] = False
        mark_records_stopping()
        crawlers = execution_state['active_crawlers'].take_all()
        # The late sweep closes THIS run's browsers only; the queue may already be starting the
        # next run by the time it runs.
        stopped_run_id = str(execution_state.get('run_id') or '')
        lang = get_lang()
        owner = account_context.current()
        # Clear the handle INSIDE the lock: a drain can hand the slot to a queued run the moment
        # it is released, and clearing it afterwards would erase that run's own stop handle.
        execution_state.pop('current_input', None)
        execution_state['executor'] = None

    # A visible Chrome can take its bounded grace to die; the Stop request must not hang behind it.
    threading.Thread(target=_finish_stop, args=(crawlers, lang, owner, stopped_run_id), daemon=True).start()
    # The console and the node counters stay: stopping is when the user most needs to read what
    # happened. The next run resets both when it claims the slot.
    return {
        'status': 200,
        'body': {'ok': True, 'browsers': len(crawlers), 'records': list(execution_state['open_records'])},
    }
