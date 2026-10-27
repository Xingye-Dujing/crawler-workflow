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
import time

from core.config import Config
from sessions.cookies import CookieManager

from services.execution_history import ExecutionHistoryService

#: 执行历史 service: one process-wide instance that opens ``data/history.db`` at import (the path
#: is whatever ``Config`` held when ``app`` — which imports this first — was loaded; the test
#: harness redirects it to a throwaway root before importing). Moved out of ``app.py`` so a
#: Blueprint can read it without importing the whole Flask module (a cycle).
history_service = ExecutionHistoryService()

#: Cookie store: one process-wide instance over ``Config.COOKIE_DIR``. Moved out of ``app.py`` so
#: the ``/api/capabilities`` Blueprint can extend the matrix with the live account list without
#: importing the whole Flask module. A store object is only ever used, never rebound (the test
#: harness redirects its directory before import), so every module that imports this name — the
#: cookie routes in ``sessions/routes.py``, the tests that drive them — holds one jar.
cookie_manager = CookieManager(Config.COOKIE_DIR)

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
    # The records THIS attempt opened (one per workflow in a split serial run),
    # cleared when a run claims the slot. The status endpoint reads their node
    # states to paint live spinners; ``owned_records`` outlives the attempt and
    # would keep serving an old run's verdicts as if they were this one's.
    'attempt_records': set(),
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

#: One parked Run request, in the shape ``app._begin_run`` re-dials it: the payload the
#: browser sent, the language to answer in, and the identity the queue lists and mirrors.
#: Named so the queue and its disk mirror agree on one shape instead of each writing
#: ``dict`` and letting every reader guess the keys.
QueueEntry = dict


#: Queued requests live in memory only. A restart drops them, which is the honest
#: behaviour for a list of intentions nobody is here to confirm. The queue is guarded by
#: app's `_queue_lock`; the list itself is only ever appended to / slice-cleared, never
#: rebound.
_RUN_QUEUE: list[QueueEntry] = []

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


def live_run_ids() -> list:
    """Every run id a live thread may still be writing — ONE definition of 「活着」.

    ``execution_state['running']`` is cleared at the TOP of 停止 while the worker keeps
    settling, still holds its browsers and still writes rows for tens of seconds. A route
    that asks only that flag therefore allows exactly the window in which deleting is most
    destructive: the record, its node rows, its export shards and its console log vanish
    under the writer, ``finish_run``'s UPDATE then matches no row (so even the write-failure
    line is lost), and the final flush re-inserts log lines for a run id no ``runs`` row
    owns. It lives here (not ``app.py``) so the export Blueprint can hold the SAME line as
    the run-record routes without importing the whole Flask module (a cycle).
    """
    thread = execution_state.get('thread')
    if not execution_state['running'] and not (thread is not None and thread.is_alive()):
        return []
    ids = [str(rid) for rid in execution_state['open_records']]
    current = str(execution_state.get('run_id') or '')
    if current and current not in ids:
        ids.append(current)
    return ids


def any_run_live() -> bool:
    """Whether SOME run's worker thread could still be writing anything.

    The bulk-clear routes used to ask ``execution_state['running']`` alone — which 停止 clears
    while the worker is mid-settle, so 「清空」 during those tens of seconds deleted the part
    files a streaming node was still merging into the export folder. A bulk wipe has no run id
    to compare, so it asks the one live-run definition above.
    """
    return bool(live_run_ids())


def stop_requested() -> bool:
    """Whether 停止 has been pressed for the run in flight.

    Read ``stopping``, NOT ``not running``. The two look interchangeable and are not:
    a helper or a test that calls an executor function directly has no claim in place
    at all, and for it "nobody is running" is not an answer to "did the user end this
    run" — inferring the second from the first made every such call refuse to work.
    ``stopping`` is set only by the Stop handler and cleared when a run claims the slot.
    """
    return bool(execution_state.get('stopping'))


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


# ─── Console buffer ───
# Every message that reaches the console is i18n.t(key, **params) — add_log, logging, and
# print() all funnel through the two writers below. They live here (not ``app.py``) so the
# executor modules under ``services/`` can log without importing the Flask module (a cycle),
# which is what unblocks moving ``_execute_*_node`` out of ``app.py``.

#: Thread-local storage: tracks which workflow index the current thread belongs to, so
#: ``_push_log`` routes lines into the right per-workflow buffer (``_wf_logs[wf_idx]``) in
#: parallel mode. A worker thread sets ``app._wf_local.idx``; ``app`` imports this object back
#: and never rebinds it, so the same thread's ``_push_log`` reads the value it just wrote.
_wf_local = threading.local()

#: Optional write-through sink for the durable per-run console. ``app`` injects a callable
#: at run start (``set_log_sink``) that receives ``(parts, wf_idx, level)`` once per
#: ``_push_log``; it is ``None`` otherwise, so ``state`` never imports the store and the
#: in-memory buffers below stay the single source of truth for the live console. The sink is
#: a pure SIDE EFFECT: it must never change what ``_push_log`` appends or the running totals,
#: because the page-refresh reattach (``?tail=5000`` replay + cursor realign) reads exactly
#: those values. ``app`` owns flushing it.
_log_sink = None


def set_log_sink(fn):
    """Install (or clear, with ``None``) the durable-console sink. See ``_log_sink``."""
    global _log_sink
    _log_sink = fn


#: Console lines kept in memory. The frontend only ever renders the last 200, but the total
#: count has to keep growing so the browser can tell how many it has not seen yet (see
#: ``_push_log``). ``app.py`` imports this back for its ``_status_tail`` clamp.
LOG_KEEP = 5000


def _push_log(line: str, wf_idx: int = None, level: str = None):
    """Append one console line, keeping the buffer bounded.

    ``_log_total`` counts every line ever produced, not the number retained: the
    status endpoint ships only the tail, so without a running total the browser
    cannot work out the delta and the console silently freezes at 200 lines.

    A payload carrying newlines is split into one entry per physical line. A
    driver's ``Message: …`` block, a site's own multi-line refusal and a
    ``logger.exception`` traceback all arrived as a SINGLE entry, which the browser
    counts as one line while the DOM renders several (``.console-line`` is
    ``white-space: pre-wrap``) — the delta cursor then skipped or repeated real
    content, blank lines came back through this path after the logger handler
    filtered them, and the 200-line tail could be spent by one traceback.

    ``level`` (best-effort: ``warning``/``error`` from the logger handler, else
    ``info``) is metadata for the durable sink only — it never affects the in-memory
    buffers or the running totals the live console and the refresh-reattach read.
    """
    idx = wf_idx if wf_idx is not None else getattr(_wf_local, 'idx', None)
    parts = [part for part in line.splitlines() if part.strip()]
    if not parts:
        return
    # _completed_lock now guards every reader of the console buffers (status
    # endpoint snapshots them), so the writers hold it too.
    with _completed_lock:
        logs = execution_state['logs']
        logs.extend(parts)
        if len(logs) > LOG_KEEP:
            del logs[:-LOG_KEEP]
        # The total moves by the number of LINES appended, not by the number of
        # add_log calls — that total is what the browser's delta cursor reads.
        execution_state['_log_total'] += len(parts)
        if idx is not None:
            buf = execution_state['_wf_logs'].setdefault(idx, [])
            buf.extend(parts)
            if len(buf) > LOG_KEEP:
                del buf[:-LOG_KEEP]
            execution_state['_wf_log_total'][idx] = execution_state['_wf_log_total'].get(idx, 0) + len(parts)
        # Write-through to the durable per-run log, taken off the SAME ``parts`` the
        # buffers just consumed. It is a side effect appended after every existing
        # mutation, so a sink that raises cannot corrupt the totals: the live console
        # and the refresh-reattach are already fully updated before this runs.
        if _log_sink is not None:
            _log_sink(list(parts), idx, level)


def add_log(msg: str, wf_idx: int = None, level: str = 'info'):
    if not str(msg or '').strip():
        # A blank console row is noise the logger path already filters; stamping it
        # would turn ``''`` into a line carrying nothing but a clock.
        return
    _push_log(f'[{time.strftime("%H:%M:%S")}] {msg}', wf_idx, level)


def _console_baseline() -> dict:
    """The console and the progress counters, in their between-runs state.

    A factory, not a constant: every value here is mutable-or-counted and must be
    fresh each time, or two runs would append into one shared list.
    """
    return {
        'logs': [],
        '_log_total': 0,
        '_wf_logs': {},
        '_wf_log_total': {},
        '_wf_names': {},
        # A new run must not name its files after the window the last one walked.
        '_time_windows': {},
        'total_nodes': 0,
        'completed_nodes': 0,
        'skipped_nodes': 0,
        'failed_nodes': 0,
    }


def reset_console_state() -> None:
    """Put the console and the progress counters back to their between-runs state.

    One answer for two callers. The run start needs it so a new console never
    inherits the previous run's lines; the test suite needs it because a test can
    reach ``_execute_source_node`` directly — no HTTP request, so no run start —
    and still write narration into the very buffer the next test asserts on. When
    that reset was inline, one crawl-matrix test leaked 25 lines three files
    downstream, where they read as a run nobody had started.
    """
    execution_state.update(_console_baseline())
