"""Task scheduler with thread pool support."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

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
                logger.error('Task failed: %s', e)
                results.append(None)
        return results

    def run_parallel(self, tasks: list[Callable]) -> list[Any]:
        results = []
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self._futures = [self._pool.submit(t) for t in tasks]
        try:
            for fut in as_completed(self._futures):
                if self._stop_event.is_set():
                    break
                try:
                    results.append(fut.result())
                except Exception as e:
                    logger.error('Task failed: %s', e)
                    results.append(None)
        finally:
            # Don't block — running threads will exit naturally once
            # the Selenium driver is closed by stop_workflow.
            self._pool.shutdown(wait=False, cancel_futures=True)
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
        self._stop_event.set()
        for fut in self._futures:
            fut.cancel()
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def reset(self):
        self._stop_event.clear()
        self._futures = []
