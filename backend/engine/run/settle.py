"""The attempt's verdict: settle the rows FIRST, then count what they say.

An abandoned node only becomes partial/failed inside ``settle_nodes``, so a count taken before that
pass (and from the whole record, so a node deleted from the canvas kept failing every later 继续)
described a different run from the one the user was looking at. These three functions are that
order made explicit, and the rules they encode are ones the console, the record and the browser's
toast must all agree on:

* a node the STOP cut is not a failure — counting it as one blamed the user's own button press on
  their workflow;
* ``failed`` and ``partial`` are the same news for the verdict: one broken node downgrades the run,
  because "completed" over a gap hid it from the resume banner forever;
* skipping a node is neither done nor failed, and the finish line names the count rather than
  quietly subtracting from a ratio nobody can read.
"""

from runtime.state import _completed_lock, execution_state

from i18n import t
from services.runs.store import NODE_FAILED, NODE_PARTIAL, RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED


def settle_attempt(store, created: list, still_running: bool) -> dict:
    """Settle every record this attempt wrote and answer what its rows add up to.

    Returns ``{'statuses', 'attempted', 'stopped', 'broken'}``. ``created`` is one row for a
    parallel or single-workflow run and one per workflow that got its turn in a serial one;
    settling them all and merging the statuses is what lets ONE finish line still speak for the
    canvas. It also files the verdict's two derived numbers (``failed_nodes``, ``outcome``) on
    ``execution_state``, because the status endpoint reads them from there.
    """
    statuses = {}
    for rid in created:
        store.settle_nodes(rid)
        statuses.update(store.node_statuses(rid))
    with _completed_lock:
        attempted = set(execution_state['attempted_nodes'])
        stopped = set(execution_state['stopped_node_ids']) & attempted
    broken = sum(
        1
        for nid, state in statuses.items()
        if nid in attempted and nid not in stopped and state.get('status') in (NODE_FAILED, NODE_PARTIAL)
    )
    with _completed_lock:
        execution_state['failed_nodes'] = broken
        execution_state['outcome'] = 'interrupted' if not still_running else ('failed' if broken else 'completed')
    return {'statuses': statuses, 'attempted': attempted, 'stopped': stopped, 'broken': broken}


def finish_line(stopped: set, broken: int) -> str:
    """The one sentence that says how the run ended, with the numbers that explain it."""
    line = t(
        'run.finished',
        done=execution_state['completed_nodes'],
        total=execution_state['total_nodes'],
    )
    # Starved and lost nodes are named in the same sentence instead of
    # quietly subtracting from a ratio the reader cannot interpret.
    if execution_state['skipped_nodes']:
        line += t('run.finished.skipped', n=execution_state['skipped_nodes'])
    # A stop is not a failure, and counting the nodes it cut as failures made
    # every stopped run read as a broken workflow — the one claim on that line
    # the user caused themselves.
    if stopped:
        line += t('run.finished.stopped', n=len(stopped))
    if broken:
        line += t('run.finished.failed', n=broken)
    return line


def verdict(still_running: bool, broken: int) -> str:
    """The run's own status: a stop outranks a failure, and one broken node outranks "completed"."""
    if not still_running:
        return RUN_INTERRUPTED
    return RUN_FAILED if broken else RUN_COMPLETED
