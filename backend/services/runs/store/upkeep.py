"""Retention: watermarks, purge and the counts the settings page shows."""

import logging
import time

from core.config import Config

from .identity import UNRESOLVED_RUN_STATUS

logger = logging.getLogger(__name__)


class UpkeepMixin:
    def get_watermark(self, scope: str) -> dict | None:
        rows = self._query('SELECT * FROM source_watermarks WHERE scope = ?', (str(scope or ''),))
        if not rows:
            return None
        row = rows[0]
        return {
            'scope': str(row['scope']),
            'platform': str(row['platform'] or ''),
            'field': str(row['field'] or ''),
            'last_key': str(row['last_key'] or ''),
            'run_id': str(row['run_id'] or ''),
            'updated_at': str(row['updated_at'] or ''),
        }

    def save_watermark(self, scope: str, platform: str, field: str, key: str, run_id: str = '') -> None:
        """Remember the newest item a completed crawl proved it saw."""
        clean_scope = str(scope or '')
        clean_key = str(key or '')
        if not clean_scope or not clean_key:
            return
        self._execute(
            'INSERT INTO source_watermarks (scope, platform, field, last_key, run_id, updated_at)'
            ' VALUES (?, ?, ?, ?, ?, ?)'
            ' ON CONFLICT(scope) DO UPDATE SET platform = excluded.platform, field = excluded.field,'
            ' last_key = excluded.last_key, run_id = excluded.run_id, updated_at = excluded.updated_at',
            (clean_scope, str(platform or ''), str(field or ''), clean_key, str(run_id or ''), self.now()),
        )

    def purge(self, keep_per_workflow: int = None, keep_days: int = None, exclude_run_id=None) -> dict:
        """Age out old runs, in two independent sweeps that ADD.

        ``keep_per_workflow`` spares the most recent N records PER WORKFLOW — but it does NOT
        override the age cutoff: a run older than ``keep_days`` goes whatever its rank, so a
        workflow nobody has run in a year keeps nothing. Reading the count rule as "the newest
        N always stay" would promise retention the sweep does not implement (pinned by
        ``test_age_cutoff_removes_everything_older``). Finished runs go before interrupted ones,
        because an interrupted one may still be worth continuing.

        ``exclude_run_id`` is the run (or, since a serial multi-workflow run closes one record
        per workflow, *runs*) a live thread is still writing — deleting their rows mid-run would
        silently destroy the very state being built.
        """
        exclude = [exclude_run_id] if isinstance(exclude_run_id, str) else list(exclude_run_id or [])
        keep = Config.RUN_KEEP_PER_WORKFLOW if keep_per_workflow is None else int(keep_per_workflow)
        days = Config.RUN_KEEP_DAYS if keep_days is None else int(keep_days)
        cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - max(0, days) * 86400))

        doomed = set()
        # 1. Too old to be worth continuing, whatever its status.
        rows = self._query('SELECT run_id FROM runs WHERE started_at < ?', (cutoff,))
        doomed.update(row['run_id'] for row in rows)
        # 2. Beyond the per-workflow cap. A run that is unfinished in any sense —
        # interrupted, still writing, or stopped but not yet settled — is counted
        # first, so the ones someone may still want to continue survive the trim.
        grouped = {}
        for row in self._query('SELECT workflow_name, run_id, status, seq FROM runs'):
            grouped.setdefault(row['workflow_name'] or '', []).append(dict(row))
        for runs in grouped.values():
            ordered = sorted(runs, key=lambda r: r['seq'], reverse=True)
            unresolved = [r for r in ordered if r['status'] in UNRESOLVED_RUN_STATUS]
            settled = [r for r in ordered if r['status'] not in UNRESOLVED_RUN_STATUS]
            keep_ids = {r['run_id'] for r in (unresolved + settled)[: max(0, keep)]}
            doomed.update(r['run_id'] for r in ordered if r['run_id'] not in keep_ids)
        doomed.difference_update(exclude)

        removed = 0
        for run_id in doomed:
            # Retention destroys the rows, so it must also destroy the promise that
            # pointed at them. ``item_seen`` says "this exact item is already
            # collected", and a later crawl of the same signature honours it —
            # against rows that no longer exist. The user then gets fewer rows than
            # they asked for, from a table they cannot see the gap in, with no way
            # back except 「重新采集」. An explicit run deletion keeps its claims (see
            # ``delete_run``): there the user removed a record while knowing the
            # crawl was already paid for; here the storage decided for them.
            self.delete_run(run_id)
            self.forget_run_items(run_id)
            removed += 1
        # 3. The answer cache is the other thing that grows without bound.
        cache_cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - max(1, days) * 86400))
        cur = self._execute('DELETE FROM llm_cache WHERE created_at < ?', (cache_cutoff,))
        seen_cutoff = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(time.time() - max(1, days) * 86400))
        cur2 = self._execute('DELETE FROM item_seen WHERE created_at < ?', (seen_cutoff,))
        return {
            'runs': removed,
            'cache_entries': cur.rowcount,
            'seen_keys': cur2.rowcount,
        }
