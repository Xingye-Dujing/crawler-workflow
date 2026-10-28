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

import pandas as pd
from core.config import Config
from state import _dataset_cache

from services.analysis.lexicon_store import LexiconStore
from services.biblio.store import BiblioStore
from services.datasets.store import SOURCE_UPLOAD, DatasetStore
from services.runs.housekeeping import Housekeeping
from services.runs.store import RunStore
from services.workflows.history import WorkflowHistoryStore

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


# ─── Lexicon store ──────────────────────────────────────────────

#: The user-editable word lists (stopwords + jieba domain terms), opened on first use.
_LEXICON_STORE = None
_LEXICON_LOCK = threading.Lock()


def get_lexicon_store() -> LexiconStore:
    """The single store behind the editable lexicons, opened on first use."""
    global _LEXICON_STORE
    if _LEXICON_STORE is None:
        with _LEXICON_LOCK:
            if _LEXICON_STORE is None:
                _LEXICON_STORE = LexiconStore()
    return _LEXICON_STORE


# ─── Bibliometrics projects and snapshots ───────────────────────

#: Named subjects of study and the bibliometrics tables captured from a run.
_BIBLIO_STORE = None
_BIBLIO_LOCK = threading.Lock()


def get_biblio_store() -> BiblioStore:
    """The single store behind the bibliometrics workspace, opened on first use."""
    global _BIBLIO_STORE
    if _BIBLIO_STORE is None:
        with _BIBLIO_LOCK:
            if _BIBLIO_STORE is None:
                _BIBLIO_STORE = BiblioStore()
    return _BIBLIO_STORE


# ─── Canvas history ────────────────────────────────────────────

#: Named whole-canvas snapshots and the per-workflow layout baseline.
_WORKFLOW_HISTORY_STORE = None
_WORKFLOW_HISTORY_LOCK = threading.Lock()


def get_workflow_history_store() -> WorkflowHistoryStore:
    """The single store behind canvas history, opened on first use."""
    global _WORKFLOW_HISTORY_STORE
    if _WORKFLOW_HISTORY_STORE is None:
        with _WORKFLOW_HISTORY_LOCK:
            if _WORKFLOW_HISTORY_STORE is None:
                _WORKFLOW_HISTORY_STORE = WorkflowHistoryStore()
    return _WORKFLOW_HISTORY_STORE


#: The read-through cache of loaded frames (``_dataset_cache``, from ``state``) is bounded so a
#: long session does not hold every file it ever opened; the store stays the source of truth.
_DATASET_CACHE_MAX = 24


def _cache_dataset(dataset_id: str, df: pd.DataFrame):
    """Remember a frame for a while. Bounded, because the store is not."""
    with _DATASET_LOCK:
        _dataset_cache[dataset_id] = df
        while len(_dataset_cache) > _DATASET_CACHE_MAX:
            _dataset_cache.pop(next(iter(_dataset_cache)), None)


def _register_dataset(df: pd.DataFrame, name: str = 'dataset', source: str = SOURCE_UPLOAD) -> str:
    """Persist a frame and return its id.

    Content-addressed, so handing over the same rows twice reuses one copy
    instead of piling up duplicates of a file somebody re-uploads every run.
    """
    meta = get_dataset_store().put(df, name=str(name), source=source)
    _cache_dataset(meta['dataset_id'], df)
    return meta['dataset_id']


def _load_dataset(dataset_id: str) -> pd.DataFrame | None:
    """A persisted frame by id, or None. Cache first, then the database."""
    cached = _dataset_cache.get(dataset_id)
    if cached is not None:
        return cached
    df = get_dataset_store().get(dataset_id)
    if df is not None:
        _cache_dataset(dataset_id, df)
    return df


def _apply_dataset_meta(params: dict, meta: dict):
    """Write what is known about a stored file back into a node's params.

    Keeping name and row count beside the id is what later makes a file whose
    row went missing re-bindable: those two together identify it well enough
    to find the same file again under a new id.
    """
    params['dataset_id'] = meta.get('dataset_id') or ''
    params['dataset_name'] = meta.get('name') or ''
    params['row_count'] = int(meta.get('row_count') or 0)
