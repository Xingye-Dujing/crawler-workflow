"""Shared process state that the run pipeline mutates in place.

This lives here — not in ``app.py`` — so the HTTP layer (today the routes in ``app.py``,
tomorrow split into Blueprints) and the test harness can import the ONE object each of them
is about without importing the whole Flask module. ``docs/ARCHITECTURE.md`` (Refactor step A)
explains the sequence this unlocks.

The contract that makes moving these out of ``app.py`` safe: **every value here is mutated in
place and never rebound.** ``app.py`` does ``from state import execution_state, _RUN_QUEUE,
_dataset_cache``, so ``app.execution_state`` stays the very same object the routes, the run
worker, ``tests/conftest.py`` and ``run_wait.py`` all read and write. Rebinding one of these
names (``execution_state = {...}``) would silently detach ``app`` from ``state`` — the leaked-flag
tripwires in the conftest would then be checking a stale object. If a future change must replace
one of these wholesale, mutate it (``clear()``/``update()``/slice-assign) instead of rebinding.
"""

import threading

from services.execution_history import ExecutionHistoryService

#: 执行历史 service: one process-wide instance that opens ``data/history.db`` at import (the path
#: is whatever ``Config`` held when ``app`` — which imports this first — was loaded; the test
#: harness redirects it to a throwaway root before importing). Moved out of ``app.py`` so a
#: Blueprint can read it without importing the whole Flask module (a cycle).
history_service = ExecutionHistoryService()

#: Mutable per-process run state: one run in flight, its console buffer, its outcome counters
#: and the LLM transport. Read ``stopping`` (not ``not running``) for a Stop — see app.stop_requested.
execution_state: dict = {
    'running': False,
    'executor': None,
    'thread': None,
    'results': {},
    'logs': [],
    '_log_total': 0,  # lines ever produced (the list itself is capped)
    'total_nodes': 0,
    'completed_nodes': 0,
    # A run is not a binary. Nodes a dead upstream starved (`skipped`) and nodes
    # that died (`failed_nodes`) are neither done nor nothing, and the browser
    # used to guess the difference from `completed < total` — which called a
    # clean run with one skipped node "ended, can continue". `outcome` is the
    # worker's own verdict, published once the run stops.
    'skipped_nodes': 0,
    'failed_nodes': 0,
    # Nodes cut short by the user's own 停止. Kept apart from `failed_nodes` because a
    # stopped node is not a failure, and blaming one on the workflow is the last thing
    # a run the user ended by hand should say.
    'stopped_node_ids': set(),
    # The run rows a live worker still owns (one per workflow in a serial
    # multi-workflow canvas): 停止 writes to these, and nothing settles a row that
    # is not on this list while its worker may still be running.
    'open_records': [],
    # Every record THIS process opened, kept across runs. It is what lets the panel
    # settle a row its own worker abandoned without ever touching a row another
    # server instance might be writing right now.
    'owned_records': set(),
    # Node ids the CURRENT attempt visited. `runs.db` keeps the status of every
    # node ever run under this run id, including ones the canvas has since
    # deleted, so a verdict read from the whole record can blame today's run for
    # an older shape of the workflow.
    'attempted_nodes': set(),
    'outcome': '',
    'active_crawlers': set(),
    # Set by Stop, cleared when a run claims the slot: it means "the user has asked
    # to stop and the worker has not written its verdict yet".
    'stopping': False,
    '_wf_logs': {},  # {wf_idx: [log lines]} per-workflow logs for parallel mode
    '_wf_log_total': {},  # {wf_idx: lines ever produced} — see _push_log
    '_wf_names': {},  # {wf_idx: the workflow's user-facing name} for console lines
    # {wf_idx: [(start, end)]} of the time windows a crawl node in this workflow was
    # asked to walk. A save node cannot see the crawl it sits downstream of — it gets a
    # table — so this is how 「文件名带时间范围」 can say which window the table is.
    '_time_windows': {},
    '_mode': 'serial',
    'llm': None,  # AI transport config from the settings panel (see /api/workflow/execute)
    'cancel_event': threading.Event(),  # set by Stop; checked between LLM rows
    # Which workflow was last opened, and what shape it has: previews resolve a
    # node from the database when results are gone, and these tell it which
    # workflow's rows count as "this node's".
    'workflow_name': '',
    # Every name node's label in canvas order — the record of a run that executed
    # several workflows carries all of their names, not just the first.
    'workflow_labels': [],
    'fingerprint': '',
    # Set when a crawl is bounced to a login wall mid-run (the cookie likely
    # expired). Surfaced to the browser through /api/workflow/status so it can
    # toast "refresh the cookie and resume" — the partial data is already safe.
    'cookie_expired': False,
}

#: Queued requests live in memory only. A restart drops them, which is the honest
#: behaviour for a list of intentions nobody is here to confirm. The queue is guarded by
#: app's `_queue_lock`; the list itself is only ever appended to / slice-cleared, never
#: rebound.
_RUN_QUEUE: list = []

#: Read-through cache of loaded datasets. The store is the source of truth, so anything
#: registered days ago still resolves even after this empties; entries are inserted, popped
#: and `.clear()`-ed in place.
_dataset_cache: dict = {}

#: Guards every reader and writer of ``execution_state`` (the console buffers and ``results``).
#: A Lock is only ever acquired, never rebound, so ``app.py`` imports it back and its many
#: ``with _completed_lock:`` sites keep sharing the exact object the snapshot below takes.
#: It lives here (not ``app.py``) so a read-only Blueprint can use ``_results_snapshot`` without
#: importing the whole Flask module (a cycle).
_completed_lock = threading.Lock()


def _results_snapshot() -> dict:
    """A private copy of ``execution_state['results']``, taken under ``_completed_lock``.

    The run publishes a node's rows the moment that node finishes, so any read-only endpoint
    that *iterated* the live dict — ``.items()``, ``.keys()`` — could be stepping through it
    while that thread added the next node (``RuntimeError: dictionary changed size during
    iteration``). Copying under the same lock the writer holds is the cheap fix: the endpoint
    walks a stable snapshot and the run never has to wait for a status poll.
    """
    with _completed_lock:
        return dict(execution_state['results'])
