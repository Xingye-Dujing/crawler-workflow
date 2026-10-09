"""The process-wide store singletons — the run ledger, the dataset store, the housekeeper.

These are the three lazily-opened SQLite-backed objects every route and the run worker reach
for. They live here, not in ``app.py``, for one reason: a Blueprint (or a future executor module
under ``services/``) must be able to call ``get_run_store()``/``get_dataset_store()`` WITHOUT
importing the whole Flask module, which is a cycle. ``app.py`` imports the three getters back, so
its dispatch and every existing ``app.get_run_store()`` read still resolve — and a test that
patches ``app.get_run_store`` (a function) still intercepts the app-internal bare calls, because
those look the name up in ``app``'s namespace.

The seam that the test harness rebinds is the THREE module globals below (``_RUN_STORE`` /
``_DATASET_STORE`` / ``_HOUSEKEEPER``), not copies of them. ``conftest`` writes these names on
``stores`` (``stores._RUN_STORE = <fresh tmp store>``) per test, and ``app._RUN_STORE`` reads the
same object through ``app``'s ``__getattr__`` delegation. So the injection point and the readers
agree on exactly one place: this module. A write to ``app._RUN_STORE`` would create a shadowing
global in ``app`` and detach the two — which is why every store-object write site targets
``stores``, never ``app``.
"""

import threading

from config import Config
from services.dataset_store import DatasetStore
from services.housekeeping import Housekeeping
from services.run_store import RunStore

# ─── Durable run state ──────────────────────────────────────────

#: The resumable-run ledger, opened on first use. The test harness rebinds this per test.
_RUN_STORE = None
_RUN_STORE_LOCK = threading.Lock()


def get_run_store() -> RunStore:
    """The single SQLite store behind resumable runs, opened on first use.

    Deliberately lazy: at import time nothing here is ready, and anything that
    merely imports app.py would otherwise pay for opening a connection and
    running recovery on every start.
    """
    global _RUN_STORE
    if _RUN_STORE is None:
        with _RUN_STORE_LOCK:
            if _RUN_STORE is None:
                _RUN_STORE = RunStore()
    return _RUN_STORE


#: Retention sweep, opened on first use; it holds a handle on both stores below.
_HOUSEKEEPER = None
_HOUSEKEEPER_LOCK = threading.Lock()


def get_housekeeper() -> Housekeeping:
    """Retention sweep for run records and orphaned stored files.

    Lazy for the same reason the stores are: it holds a handle on both, and
    merely importing this module must not open a database.
    """
    global _HOUSEKEEPER
    if _HOUSEKEEPER is None:
        with _HOUSEKEEPER_LOCK:
            if _HOUSEKEEPER is None:
                _HOUSEKEEPER = Housekeeping(
                    get_run_store(),
                    get_dataset_store(),
                    interval_seconds=max(0, int(Config.HOUSEKEEPING_INTERVAL_MINUTES)) * 60,
                )
    return _HOUSEKEEPER


# ─── Dataset store ──────────────────────────────────────────────

#: The store behind every persisted file (uploaded/pasted/cleaned), opened on first use.
_DATASET_STORE = None
#: Guards both this singleton's creation and ``app``'s read-through ``_dataset_cache`` — ``app``
#: imports the very object back so the cache writers and the store creation still share one lock.
_DATASET_LOCK = threading.Lock()


def get_dataset_store() -> DatasetStore:
    """The single SQLite store behind persisted files, opened on first use."""
    global _DATASET_STORE
    if _DATASET_STORE is None:
        with _DATASET_LOCK:
            if _DATASET_STORE is None:
                _DATASET_STORE = DatasetStore()
    return _DATASET_STORE
