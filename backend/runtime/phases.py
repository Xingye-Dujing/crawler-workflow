"""Per-run phase timings — how long the browser took, the crawl, one comment walk.

A user watching a slow run sees a Chrome window and no console line for a minute; the
question they actually ask is "where did the time go". The live probe answered it with
three lines printed by hand (``browser up 1.2s`` / ``search 2 notes 55.0s`` /
``walk status=ok rows=3 elapsed=11.5s unproven=0``), and that is the shape this buffer
keeps as data so the Console panel can show it:

* ``browser`` — one crawler's Chrome launch (from ``Crawler.__init__``);
* ``crawl``   — a source node's one handler call (search / author / board / detail);
* ``walk``    — one comment link's walk, with the status and row count it settled on.

Owner-scoped like every other run fact: an entry carries the run id and the account that
recorded it, and :func:`snapshot` answers only the caller's own rows. The buffer is a ring
(a panel keeps the last :data:`MAX_ENTRIES`) and process-global on purpose: it is a
diagnostic, never a store — nothing here survives a restart, and no rows or payloads do.
"""

import threading
import time
from collections import deque

from runtime import account_context

#: How many entries the panel can scroll through. A crawl records one per page/link, so
#: this is "the last few hundred events", not a ledger.
MAX_ENTRIES = 200

_lock = threading.Lock()
_entries: deque = deque(maxlen=MAX_ENTRIES)


def reset() -> None:
    """Forget every entry. Test isolation, never a runtime operation."""
    with _lock:
        _entries.clear()


def record(phase: str, seconds: float, label: str = '', **facts) -> dict:
    """Append one phase. *seconds* is measured by the caller with a monotonic clock.

    The run id and the account are stamped here rather than passed by each caller: a
    thread that records a phase is not necessarily the one that owns the run slot, and a
    diagnostic that lands under the wrong account is worse than no diagnostic.
    """
    from runtime.state import execution_state

    owner = account_context.current()
    entry = {
        'phase': str(phase or ''),
        'label': str(label or ''),
        'seconds': round(max(0.0, float(seconds or 0.0)), 3),
        'run_id': str(execution_state.get('run_id') or ''),
        'user_id': owner.user_id if owner is not None else '',
        'at': time.time(),
    }
    entry.update({str(k): v for k, v in facts.items()})
    with _lock:
        _entries.append(entry)
    return dict(entry)


def snapshot(run_id: str = None, user_id: str = None, limit: int = 60) -> list:
    """The last *limit* entries, newest last, filtered by run and account when asked.

    ``run_id=None`` means "any run of this account" — what the panel shows between runs.
    An empty *run_id* is a real value (a crawler built outside a run, e.g. a cookie probe),
    so it is compared, never treated as "no filter".
    """
    with _lock:
        items = [dict(entry) for entry in _entries]
    if run_id is not None:
        items = [entry for entry in items if entry['run_id'] == str(run_id)]
    if user_id is not None:
        items = [entry for entry in items if entry['user_id'] == str(user_id)]
    return items[-max(1, int(limit)) :]
