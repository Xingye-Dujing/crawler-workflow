"""Task scheduler with thread pool support."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from i18n import t

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes workflow tasks with configurable parallel/serial mode."""

    def __init__(self, max_workers: int = 4, mode: str = 'parallel'):
        self.max_workers = max_workers
        self.mode = mode
        self._stop_event = threading.Event()
        self._pool = None
        self._futures = []

    def run_serial(self, tasks: list[Callable]) -> list[Any]:
        results = []
        for task in tasks:
            if self._stop_event.is_set():
                break
            try:
                results.append(task())
            except Exception as e:
                logger.error(t('executor.task_failed', err=e))
                results.append(None)
        return results

    def run_parallel(self, tasks: list[Callable]) -> list[Any]:
        results = []
        # Local, not `self._pool`: stop() runs on the request thread and used to
        # assign `self._pool = None` here, which made this method's own cleanup
        # raise AttributeError on the thread that was still waiting for results.
        pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self._pool = pool
        futures = [pool.submit(t) for t in tasks]
        self._futures = futures
        try:
            for fut in as_completed(futures):
                if self._stop_event.is_set():
                    break
                try:
                    results.append(fut.result())
                except Exception as e:
                    logger.error(t('executor.task_failed', err=e))
                    results.append(None)
        finally:
            # WAIT. The comment that used to justify `wait=False` was "threads exit
            # naturally once the driver is closed" — true, and beside the point:
            # the caller of this level is the run's own thread, and the moment it
            # returns the run reaches its `finally`, releases the one-at-a-time slot
            # and hands the queue the NEXT run. A task still inside a node at that
            # instant keeps writing into `execution_state` — the console, the node
            # counters, `results` — which by then describes a different run. So this
            # level is over when its threads are over; `/api/workflow/stop` closes
            # the live crawlers, so what is being waited on is a page load, not a
            # whole crawl.
            pool.shutdown(wait=True, cancel_futures=True)
            if self._pool is pool:
                self._pool = None
                self._futures = []
        return results

    def execute(self, task_groups: list[list[Callable]]) -> list[Any]:
        """Execute tasks by level groups. Each level may run in parallel."""
        all_results = []
        for group in task_groups:
            results = self.run_parallel(group) if self.mode == 'parallel' and len(group) > 1 else self.run_serial(group)
            all_results.extend(results)
        return all_results

    def stop(self):
        """Ask the level to end; do not dismantle it.

        Cancelling futures is all this may do from the request thread. The shutdown
        belongs to ``run_parallel``, which is the thread that reads the results and
        the one that must not move on while tasks are still running — shutting down
        (or nulling the handle) from here is what let the run thread walk away from
        its own worker threads.
        """
        self._stop_event.set()
        for fut in self._futures:
            fut.cancel()

    def reset(self):
        self._stop_event.clear()
        self._futures = []
        self._pool = None
