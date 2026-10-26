"""Best-effort registration of a file a run produced, in the run→files ledger.

The ledger is what lets 智能清除 name every artifact a workflow left in the export directory.
Callers are nodes and streaming writers that have just succeeded at writing something, so the
registration is deliberately guarded: a ledger hiccup must never break an export that already
exists, and a caller with no run context (a direct executor call, a panel render outside a run)
records nothing — which is correct, because no record wrote it.
"""

import logging

logger = logging.getLogger(__name__)


def record_file(ctx: dict | None, node_id: str, path_or_name, kind: str) -> None:
    """Register one export file a run produced, so 智能清除 can later name them all.

    ``ctx`` carries the run's own ledger (``store`` + ``run_id``); without both there is no
    record to attribute the file to, so nothing is written. Everything is guarded — the file
    still exists and is still listed by the export panel; it simply cannot be attributed.
    """
    if not ctx:
        return
    store = ctx.get('store')
    run_id = ctx.get('run_id')
    if store is None or not run_id:
        return
    try:
        store.record_file(run_id, node_id, path_or_name, kind)
    except Exception as e:
        logger.debug('run-file ledger failed for %s: %s', path_or_name, e)
