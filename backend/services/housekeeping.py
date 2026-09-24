"""Age out the state that would otherwise grow for the life of the disk.

Both stores already know how to trim themselves, but nothing ever called them:
``RUN_KEEP_PER_WORKFLOW`` / ``RUN_KEEP_DAYS`` / ``DATASET_KEEP_DAYS`` only took
effect when a request happened to hit the purge endpoints. Housekeeping closes
that loop — once at startup and then after a finished run, on a time gate so a
burst of short runs does not sweep the database every second.
"""

import logging
import threading
import time

from i18n import t

logger = logging.getLogger(__name__)


class Housekeeping:
    """Time-gated sweep of run records and orphaned stored files."""

    def __init__(self, run_store, dataset_store, interval_seconds: float = 3600, clock=time.time):
        self._run_store = run_store
        self._dataset_store = dataset_store
        self._interval = max(0.0, float(interval_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        # None means "never swept", which is different from "swept at the epoch":
        # a gate that compared against 0 would not open until a full interval had
        # already elapsed since the process started.
        self._last = None

    def run_now(self, exclude_run_id='') -> dict:
        """Sweep unconditionally. Returns what went; never raises on a store
        that cannot answer, because losing housekeeping must not fail a run.

        ``exclude_run_id`` is one id or a sequence of them: a serial run with
        several workflows closes one record per workflow, and the sweep that
        follows protects all of them.
        """
        # Passed through, NOT flattened: ``str(['abc'])`` is the literal "['abc']", which
        # matches no run id and would have the sweep delete the very record it was told
        # to protect. The store owns the one-id-or-many normalisation, in one place.
        exclude = exclude_run_id
        removed_runs = 0
        cache_entries = 0
        seen_keys = 0
        try:
            purged = self._run_store.purge(exclude_run_id=exclude) or {}
            removed_runs = int(purged.get('runs') or 0)
            cache_entries = int(purged.get('cache_entries') or 0)
            seen_keys = int(purged.get('seen_keys') or 0)
        except Exception:
            logger.exception(t('housekeeping.runStoreFailed'))
        removed_files = 0
        try:
            removed_files = int(self._dataset_store.purge_unreferenced() or 0)
        except Exception:
            logger.exception(t('housekeeping.datasetStoreFailed'))
        result = {
            'runs': removed_runs,
            'cache_entries': cache_entries,
            'seen_keys': seen_keys,
            'files': removed_files,
        }
        # Silence is the normal case (a machine already inside its retention
        # window), so only say anything when something actually went.
        if removed_runs or removed_files or cache_entries or seen_keys:
            logger.info(
                t(
                    'housekeeping.done',
                    runs=removed_runs,
                    files=removed_files,
                    cache=cache_entries,
                    seen=seen_keys,
                )
            )
        return result

    def maybe_run(self, exclude_run_id='') -> dict | None:
        """Sweep only once the gate has elapsed. Returns None when skipped."""
        with self._lock:
            now = self._clock()
            if self._last is not None and now - self._last < self._interval:
                return None
            self._last = now
        return self.run_now(exclude_run_id=exclude_run_id)
