"""Durable run state: what every node produced, where a crawl got to, and what
the model has already answered.

``RunStore`` puts that state in SQLite (``data/runs.db``) as it is produced:

- ``runs``       one row per execution: identity, status, timing.
- ``node_runs``  one row per node per run: status, row count, crawl cursor.
- ``node_rows``  the rows a node produced, in order — the data itself.
- ``item_seen``  fingerprints of crawled items, so a resumed crawl never
                 collects the same post twice.
- ``llm_cache``  answers keyed by (operation, model, column, text). A re-run —
                 even after re-crawling, even in another workflow — gets the
                 same text back for free instead of paying for it again.

The table domains live in sibling mixins (base/ledger/progress/upkeep); the public
names below are the surface every caller and test has always imported from here.
"""

from .base import BaseMixin, RowCache
from .identity import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_PENDING,
    NODE_RESTORED,
    NODE_RUNNING,
    NODE_SKIPPED,
    RESUMABLE_RUN_STATUS,
    RUN_ABANDONED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    RUN_STOPPING,
    UNRESOLVED_RUN_STATUS,
    fingerprints_for_workflow,
    first_text,
    item_key,
    node_fingerprint,
    stable_params,
    workflow_fingerprint,
)
from .ledger import FilesMixin, LogMixin, QueueMixin, RunsMixin
from .progress import NodesMixin, RowsMixin
from .upkeep import UpkeepMixin

__all__ = [
    'NODE_DONE',
    'NODE_FAILED',
    'NODE_PARTIAL',
    'NODE_PENDING',
    'NODE_RESTORED',
    'NODE_RUNNING',
    'NODE_SKIPPED',
    'RESUMABLE_RUN_STATUS',
    'RUN_ABANDONED',
    'RUN_COMPLETED',
    'RUN_FAILED',
    'RUN_INTERRUPTED',
    'RUN_RUNNING',
    'RUN_STOPPING',
    'UNRESOLVED_RUN_STATUS',
    'RowCache',
    'RunStore',
    'first_text',
    'fingerprints_for_workflow',
    'item_key',
    'node_fingerprint',
    'stable_params',
    'workflow_fingerprint',
]


class RunStore(BaseMixin, QueueMixin, RunsMixin, NodesMixin, RowsMixin, FilesMixin, LogMixin, UpkeepMixin):
    """The durable ledger. Every mixin is a table domain; this class is their one name."""
