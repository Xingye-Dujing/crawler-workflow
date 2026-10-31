"""The process-wide store singletons — the run ledger, the dataset store, the housekeeper.

These are the three lazily-opened SQLite-backed objects every route and the run worker reach
for. They live in ``runtime/``, not in ``app.py``, for one reason: a Blueprint (or a node executor
under ``nodes/``) must be able to call ``get_run_store()``/``get_dataset_store()`` WITHOUT
importing the whole Flask module, which is a cycle. ``app.py`` imports the three getters back, so
its dispatch and every existing ``app.get_run_store()`` read still resolve — and a test that
patches ``app.get_run_store`` (a function) still intercepts the app-internal bare calls, because
those look the name up in ``app``'s namespace.

The seam that the test harness rebinds is the THREE module globals below (``_RUN_STORE`` /
``_DATASET_STORE`` / ``_HOUSEKEEPER``), not copies of them. ``conftest`` writes these names on
``runtime.stores`` (``stores._RUN_STORE = <fresh tmp store>``) per test, and ``app._RUN_STORE``
reads the same object through ``app``'s ``__getattr__`` delegation. So the injection point and the
readers agree on exactly one place: this module. A write to ``app._RUN_STORE`` would create a
shadowing global in ``app`` and detach the two — which is why every store-object write site targets
``stores``, never ``app``.
"""

import contextlib
import threading

import pandas as pd
from core.config import Config

from runtime import account_context, paths
from runtime.state import _dataset_cache, dataset_cache_key
from services.analysis.lexicon_store import LexiconStore
from services.biblio.store import BiblioStore
from services.datasets.store import SOURCE_UPLOAD, DatasetStore
from services.runs.housekeeping import Housekeeping
from services.runs.store import RunStore
from services.workflows.history import WorkflowHistoryStore
from services.workflows.manager import WorkflowManager

# ─── Per-account scopes ────────────────────────────────────────
#
# The system-scope slots below predate accounts and are deliberately kept as the test harness's
# injection seam (``conftest`` writes ``stores._RUN_STORE`` / ``_DATASET_STORE`` … and a test that
# patches ``app.get_run_store`` still intercepts the bare call). An account gets its own slot in
# this registry instead, because its stores point at ``data/users/<id>/`` and must never be shared
# with the local owner or with another account. Slots are created on first use and closed only by
# ``release_user`` (account deletion/disable) — never by an LRU, which could close a store a live
# run worker is still writing through.


class _UserStores:
    """One account's store objects, opened lazily and guarded by this slot's lock."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._lock = threading.RLock()
        self._run = None
        self._dataset = None
        self._biblio = None
        self._workflow_history = None
        self._workflow_manager = None
        self._housekeeper = None

    def run_store(self) -> RunStore:
        with self._lock:
            if self._run is None:
                self._run = RunStore(paths.for_user(self.user_id).ensure().runs_db)
        return self._run

    def dataset_store(self) -> DatasetStore:
        with self._lock:
            if self._dataset is None:
                self._dataset = DatasetStore(paths.for_user(self.user_id).ensure().datasets_db)
        return self._dataset

    def biblio_store(self) -> BiblioStore:
        with self._lock:
            if self._biblio is None:
                self._biblio = BiblioStore(paths.for_user(self.user_id).ensure().biblio_db)
        return self._biblio

    def workflow_history_store(self) -> WorkflowHistoryStore:
        with self._lock:
            if self._workflow_history is None:
                self._workflow_history = WorkflowHistoryStore(paths.for_user(self.user_id).ensure().workflow_history_db)
        return self._workflow_history

    def workflow_manager(self) -> WorkflowManager:
        with self._lock:
            if self._workflow_manager is None:
                self._workflow_manager = WorkflowManager(paths.for_user(self.user_id).ensure().workflow_dir)
        return self._workflow_manager

    def housekeeper(self) -> Housekeeping:
        with self._lock:
            if self._housekeeper is None:
                self._housekeeper = Housekeeping(
                    self.run_store(),
                    self.dataset_store(),
                    interval_seconds=max(0, int(Config.HOUSEKEEPING_INTERVAL_MINUTES)) * 60,
                )
        return self._housekeeper

    def close(self) -> None:
        with self._lock:
            for store in (self._run, self._dataset, self._biblio, self._workflow_history):
                if store is not None:
                    with contextlib.suppress(Exception):
                        store.close()
            self._run = None
            self._dataset = None
            self._biblio = None
            self._workflow_history = None
            self._workflow_manager = None
            self._housekeeper = None


_USER_STORES: dict[str, _UserStores] = {}
_USER_STORES_LOCK = threading.RLock()


def _user_slot() -> _UserStores | None:
    """The slot of the account this thread speaks for, or ``None`` for the local owner."""
    account = account_context.current()
    if account is None:
        return None
    with _USER_STORES_LOCK:
        slot = _USER_STORES.get(account.user_id)
        if slot is None:
            slot = _UserStores(account.user_id)
            _USER_STORES[account.user_id] = slot
        return slot


def release_user(user_id: str) -> None:
    """Close and forget one account's stores. The caller must have proved no run is live."""
    with _USER_STORES_LOCK:
        slot = _USER_STORES.pop(str(user_id or ''), None)
    if slot is not None:
        slot.close()
    for key in [key for key in _dataset_cache if key[0] == str(user_id or '')]:
        _dataset_cache.pop(key, None)


def user_slots() -> dict:
    """A snapshot of the open per-account slots (diagnostics and tests)."""
    with _USER_STORES_LOCK:
        return dict(_USER_STORES)


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
    slot = _user_slot()
    if slot is not None:
        return slot.run_store()
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
    slot = _user_slot()
    if slot is not None:
        return slot.housekeeper()
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
    slot = _user_slot()
    if slot is not None:
        return slot.dataset_store()
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
    slot = _user_slot()
    if slot is not None:
        return slot.biblio_store()
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
    slot = _user_slot()
    if slot is not None:
        return slot.workflow_history_store()
    global _WORKFLOW_HISTORY_STORE
    if _WORKFLOW_HISTORY_STORE is None:
        with _WORKFLOW_HISTORY_LOCK:
            if _WORKFLOW_HISTORY_STORE is None:
                _WORKFLOW_HISTORY_STORE = WorkflowHistoryStore()
    return _WORKFLOW_HISTORY_STORE


# ─── Saved canvases ────────────────────────────────────────────

#: The directory of saved workflow files. Cached like the stores above, and for the same
#: reason it lives here: the workflow routes are a Blueprint and the run orchestration is an
#: engine module, and neither may import ``app`` to reach a canvas on disk.
_WORKFLOW_MANAGER = None
_WORKFLOW_MANAGER_LOCK = threading.Lock()


def get_workflow_manager() -> WorkflowManager:
    """The single reader/writer of the current scope's workflow directory."""
    slot = _user_slot()
    if slot is not None:
        return slot.workflow_manager()
    global _WORKFLOW_MANAGER
    if _WORKFLOW_MANAGER is None:
        with _WORKFLOW_MANAGER_LOCK:
            if _WORKFLOW_MANAGER is None:
                _WORKFLOW_MANAGER = WorkflowManager()
    return _WORKFLOW_MANAGER


#: The read-through cache of loaded frames (``_dataset_cache``, from ``state``) is bounded so a
#: long session does not hold every file it ever opened; the store stays the source of truth.
_DATASET_CACHE_MAX = 24


def _cache_dataset(dataset_id: str, df: pd.DataFrame):
    """Remember a frame for a while. Bounded, because the store is not."""
    key = dataset_cache_key(dataset_id)
    with _DATASET_LOCK:
        _dataset_cache[key] = df
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
    cached = _dataset_cache.get(dataset_cache_key(dataset_id))
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
