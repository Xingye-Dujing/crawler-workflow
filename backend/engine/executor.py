"""The per-run stop handle the 停止 button reaches for.

One object, one job: it remembers that the user asked THIS run to end, and the run's own
loops ask it. It is not a thread pool and never was one in practice — ``execute``,
``run_parallel`` and ``run_serial`` were built to run the nodes of one workflow level
concurrently and were never called (the level loop in :meth:`engine.run._run_single_workflow`
is serial; what a ``parallel`` run actually runs concurrently is its WORKFLOWS, one thread
each, in ``engine.run``). Three methods and a ``ThreadPoolExecutor`` therefore sat there
claiming a capability the product does not have, and the one thing the Stop route does —
``execution_state['executor'].stop()`` — wrote to an event no loop ever read, so pressing
停止 during a long BERT/classify/export node answered ``ok`` while that node ran on.

Deleting the pool is not a feature loss: it was unreachable. What is restored is the part
that was supposed to work — the handle is now consulted by the run loop, and
``/api/workflow/processes`` reports it instead of reporting a pool that never existed.
"""

from __future__ import annotations

import threading


class TaskExecutor:
    """The stop signal for one run. Created by ``engine.run``; read by the run's loops."""

    def __init__(self, max_workers: int = 4, mode: str = 'parallel'):
        # Kept for the record (and because ``engine.run`` passes them): the width of the
        # WORKFLOW-level pool, and the mode that pool answers. Neither belongs to this object's
        # job any more, and they are not used to spawn anything here.
        self.max_workers = max_workers
        self.mode = mode
        self._stop_event = threading.Event()

    @property
    def stop_requested(self) -> bool:
        """Whether 停止 has been pressed for this run."""
        return self._stop_event.is_set()

    def stop(self):
        """Ask the run to end at its next checkpoint.

        Called from the request thread. It must not dismantle anything: the run's own thread
        owns its state, and a Stop that nulled handles under it is how a run used to walk away
        from work that was still writing into the console.
        """
        self._stop_event.set()

    def reset(self):
        """A new run gets a clean handle."""
        self._stop_event.clear()
