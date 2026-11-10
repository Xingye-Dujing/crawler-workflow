"""The live console's two write paths: a print() tee and the durable per-run log.

Moved out of ``engine/run.py`` on 2026-10-29. The run start owns *when* these are armed and
disarmed; what they do with a line is a separate answer, and AGENTS keeps its console rules
("the reattach must stay byte-identical with or without a sink", "one failure, one line") beside
this file. Nothing here decides run policy: :class:`RunLogWriter` only mirrors what
``runtime.state._push_log`` already accepted, and :class:`LogTee` only catches stray ``print()``.

Because the writer resolves ``get_run_store`` in THIS module, that is the module a test
patches — ``engine.run_logs``, not ``engine.run``. The names are the same objects the
run start uses; they are only looked up from here.
"""

import threading
import time

from runtime import account_context
from runtime.state import _push_log, execution_state
from runtime.stores import get_run_store


class LogTee:
    """Fallback: tee print() output into execution_state['logs'] (catches analyzer print() calls)."""

    def __init__(self, original):
        self._original = original

    def write(self, text):
        if text and text != '\n':
            ts = time.strftime('%H:%M:%S')
            for line in text.rstrip('\n').split('\n'):
                msg = line.rstrip()
                if msg:
                    _push_log(f'[{ts}] {msg}')
        self._original.write(text)

    def flush(self):
        self._original.flush()

    def unwrap(self):
        """The stream this tee replaced — how a caller takes the tee off without reaching in."""
        return self._original


class RunLogWriter:
    """Write-through of the live console into the durable per-run log (``run_store.run_log``).

    Installed as ``state``'s log sink only for the window a run is in flight (armed in
    ``begin_run``, disarmed in the worker's ``finally``), so a message logged outside any
    run never reaches it — otherwise a later cookie/preview ``add_log`` would append to a
    completed record's log. The sink runs *outside* ``_push_log``'s ``_completed_lock``
    (state.py takes it off the lock on purpose: the drain writes SQLite, and opening a
    store can itself log, which would re-enter a plain Lock and deadlock the run thread),
    so the writer serializes its OWN buffer with its own lock. ``_completed_lock`` is
    only ever taken before ``self._lock`` (a flush caller may hold it); no path here takes
    ``self._lock`` and then asks for ``_completed_lock``, so the two cannot invert. It
    accumulates lines and hands the batch to SQLite every ``FLUSH_EVERY`` lines or the
    moment one is an error (so a crash leaves the tail it printed, not a whole run's
    worth unwritten).

    It must never write the console back (no ``add_log``/``logger`` on failure — the log
    handler forwards here, so a failure log would recurse). A store error keeps the batch for
    the next flush, bounded by a hard cap so a permanently-dead DB cannot grow memory forever.
    A kept batch keeps its RUN ID too: the next run's lines may arrive while the failed write is
    in flight, and a buffer that merged them lost the attribution the whole class exists for.
    """

    FLUSH_EVERY = 200
    HARD_CAP = 2000

    def __init__(self):
        # Reentrant: a store that logs while opening reaches ``push`` on the same thread. No
        # path holds it across the SQLite write (``_drain`` publishes the batch and releases
        # before touching the store), so the recursion cannot duplicate a batch.
        self._lock = threading.RLock()
        self._buf: list = []
        self._buf_run_id: str | None = None
        #: Batches a failed write kept back, each WITH the run it belongs to, oldest first
        #: (``[(run_id, rows)]``). One buffer shared by two runs is what mis-filed a console:
        #: ``_drain`` empties ``_buf`` and then opens SQLite, which is long enough for the next
        #: run to print, so a retry that merged A's failed rows with B's fresh ones had to choose
        #: one id for both — whichever it chose, one run's viewer lied.
        self._pending: list[tuple[str, list]] = []
        #: The account whose run these lines belong to. Resolved at ARM time by the claim (which
        #: runs bound) rather than at flush time by whoever happened to print the 200th line:
        #: the pool threads and the Stop reapers start with NO account context, so resolving it
        #: per flush filed an account's console batch in the checkout-level ``data/runs.db`` and
        #: left a hole in the durable log the account's own page reads back.
        self._account = None

    def arm(self, account) -> None:
        """Open this run's window: remember its owner, and start from an empty batch."""
        self._account = account
        self.reset()

    def reset(self) -> None:
        """Drop any leftover batch without writing it (a new run, or an armed re-entry).

        Takes the writer's own lock for the whole swap (the same way ``flush`` does):
        ``push`` runs OUTSIDE ``_completed_lock`` (see the class docstring), so replacing
        ``_buf`` without it let a concurrent push append into the list ``reset`` had just
        swapped out — the durable log of a stopped run lost its tail.

        ``_pending`` is deliberately NOT dropped: those lines were printed by a run that is
        over, and a later flush still writes them under that run's own id. Discarding them here
        would throw away console output that already happened — the one thing this writer
        promises never to lose.
        """
        with self._lock:
            self._buf = []
            self._buf_run_id = None

    def disarm(self) -> None:
        """Close this run's window: the sink is off, so no owner may be remembered for it."""
        self._account = None
        self.reset()

    def push(self, parts, wf_idx, level) -> None:
        # Called from ``state._push_log`` OUTSIDE ``_completed_lock`` — parallel pool threads,
        # the run thread and request threads all land here concurrently.
        rid = str(execution_state.get('run_id') or '')
        if not rid:
            return
        with self._lock:
            switching = rid != self._buf_run_id and bool(self._buf)
        if switching:
            # Serial split: the previous component's record is closed — flush its lines under
            # ITS id before switching, or they would be re-filed onto the next workflow. Outside
            # the lock: the drain opens SQLite, and store creation can log back into ``push``.
            self._drain()
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        name = str((execution_state.get('_wf_names') or {}).get(wf_idx, '')) if wf_idx is not None else ''
        lvl = level or 'info'
        with self._lock:
            self._buf_run_id = rid
            for line in parts:
                self._buf.append((stamp, wf_idx, name, lvl, line))
            flush_now = lvl == 'error' or len(self._buf) >= self.FLUSH_EVERY
        if flush_now:
            self._drain()

    def _drain(self) -> None:
        # The store lookup is made OUTSIDE the lock: ``get_run_store()`` may CREATE the store,
        # and that creation logs a line (``promote_stale_runs``'s warning) — which the console
        # handler feeds back to ``push`` on this SAME thread. Holding a lock across the lookup
        # deadlocked the run thread and every later flush.
        with self._lock:
            current = (self._buf_run_id, self._buf) if self._buf and self._buf_run_id else None
            carried = self._pending
            # Published (emptied) before the write: a line pushed by the store's own creation
            # must land in the NEXT batch, not be appended to a batch we are about to swap.
            self._buf = []
            self._buf_run_id = None
            self._pending = []
        queue = [*(carried or []), *([current] if current else [])]
        failed: list[tuple[str, list]] = []
        for rid, rows in queue:
            if not rid or not rows:
                continue
            try:
                with account_context.use(self._account):
                    get_run_store().append_log(rid, rows)
            except Exception:
                # Keep this batch WITH its id for a later flush. No logging here — the console
                # handler forwards back into ``push`` and would recurse.
                failed.append((rid, rows))
        if not failed:
            return
        with self._lock:
            # Newest failures go behind anything a concurrent drain already put back, so the log
            # stays in print order per run.
            kept = failed + self._pending
            total = sum(len(rows) for _rid, rows in kept)
            while total > self.HARD_CAP and len(kept) > 1:
                _oldest_id, oldest_rows = kept.pop(0)
                total -= len(oldest_rows)
            if total > self.HARD_CAP and kept:
                # A single batch bigger than the cap: trim its head rather than drop the run.
                rid, rows = kept[0]
                kept[0] = (rid, rows[-self.FLUSH_EVERY :])
            self._pending = kept

    def flush(self) -> None:
        # No outer lock: the drain touches SQLite, and a store that logs while opening re-enters
        # ``push`` on this same thread.
        self._drain()


run_log_writer = RunLogWriter()
