"""The live console's two write paths: a print() tee and the durable per-run log.

Moved out of ``engine/run.py`` on 2026-10-29. The run start owns *when* these are armed and
disarmed; what they do with a line is a separate answer, and AGENTS keeps its console rules
("the reattach must stay byte-identical with or without a sink", "one failure, one line") beside
this file. Nothing here decides run policy: :class:`RunLogWriter` only mirrors what
``runtime.state._push_log`` already accepted, and :class:`LogTee` only catches stray ``print()``.

Because the writer resolves ``get_run_store`` and ``_completed_lock`` in THIS module, that is the
module a test patches — ``engine.run_logs``, not ``engine.run``. The names are the same objects the
run start uses; they are only looked up from here.
"""

import time

from runtime.state import _completed_lock, _push_log, execution_state
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
    completed record's log. The sink runs *inside* ``_push_log`` while it holds
    ``_completed_lock``, so ``push`` may only touch in-memory state cheaply; it accumulates
    lines and hands the batch to SQLite every ``FLUSH_EVERY`` lines or the moment one is an
    error (so a crash leaves the tail it printed, not a whole run's worth unwritten).

    It must never write the console back (no ``add_log``/``logger`` on failure — the log
    handler forwards here, so a failure log would recurse). A store error keeps the batch for
    the next flush, bounded by a hard cap so a permanently-dead DB cannot grow memory forever.
    """

    FLUSH_EVERY = 200
    HARD_CAP = 2000

    def __init__(self):
        self._buf: list = []
        self._buf_run_id: str | None = None

    def reset(self) -> None:
        """Drop any leftover batch without writing it (a new run, or an armed re-entry).

        Takes ``_completed_lock`` for the whole swap (the same way ``flush`` does): ``push``
        runs under that lock, so replacing ``_buf`` without it let a concurrent push append
        into the list ``reset`` had just swapped out — the durable log of a stopped run lost
        its tail. Neither caller holds the lock, so acquiring it here cannot self-deadlock."""
        with _completed_lock:
            self._buf = []
            self._buf_run_id = None

    def push(self, parts, wf_idx, level) -> None:
        # Runs while the caller holds ``_completed_lock`` (see ``state._push_log``); every
        # mutation below is therefore serialized with every other console writer.
        rid = str(execution_state.get('run_id') or '')
        if not rid:
            return
        if rid != self._buf_run_id and self._buf:
            # Serial split: the previous component's record is closed — flush its lines under
            # ITS id before switching, or they would be re-filed onto the next workflow.
            self._drain()
        self._buf_run_id = rid
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        name = str((execution_state.get('_wf_names') or {}).get(wf_idx, '')) if wf_idx is not None else ''
        lvl = level or 'info'
        for line in parts:
            self._buf.append((stamp, wf_idx, name, lvl, line))
        if lvl == 'error' or len(self._buf) >= self.FLUSH_EVERY:
            self._drain()

    def _drain(self) -> None:
        if not self._buf or not self._buf_run_id:
            self._buf = []
            return
        rid = self._buf_run_id
        batch = self._buf
        try:
            get_run_store().append_log(rid, batch)
            self._buf = []
        except Exception:
            # Keep the batch for a later flush; bound it if the store stays down. No logging
            # here — the console handler forwards back into ``push`` and would recurse.
            self._buf = batch if len(batch) <= self.HARD_CAP else batch[-self.FLUSH_EVERY :]

    def flush(self) -> None:
        with _completed_lock:
            self._drain()


run_log_writer = RunLogWriter()
