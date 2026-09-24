import base64
import contextlib
import ctypes
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import browser_profiles
import pandas as pd
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

import crawl_capabilities as capabilities
from analyzers import (
    AnomalyDetector,
    ContentCleaner,
    CorrelationAnalyzer,
    EmotionAnalyzer,
    KeywordExtractor,
    NamedEntityRecognizer,
    TendencyAnalyzer,
    TextCluster,
    build_training_data,
    get_classifier,
)
from analyzers.llm_client import ABORT_MARK, LLMClient, LLMError, list_free_models, list_ollama_models
from config import Config
from crawlers import cookie_hosts, crawler_class, get_crawler, is_crawlable
from engine.executor import TaskExecutor
from engine.logger import setup_logger
from engine.workflow import WorkflowEngine, node_label
from i18n import audit, normalize, set_lang, t
from services import StatsService
from services.cookie_flow import crawler_hosts, flow_for, normalize_entry_url, retain_for_platform
from services.cookie_manager import CookieManager
from services.data_analysis import DataAnalysisService, UnknownOperationError
from services.dataset_store import SOURCE_ANALYSIS, SOURCE_PASTE, SOURCE_UPLOAD, DatasetStore
from services.execution_history import ExecutionHistoryService
from services.exporter import DataExporter, UnsupportedFormatError
from services.housekeeping import Housekeeping
from services.run_store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_RESTORED,
    NODE_SKIPPED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    RunStore,
    fingerprints_for_workflow,
    workflow_fingerprint,
)
from services.visualizer import ChartConfigError, VisualizationService
from services.workflow_manager import WorkflowManager
from settings_store import all_settings, get_setting, save_settings
from utils.helpers import comment_platforms, platform_for, sanitize_filename, split_urls

#: The comment router's supported platforms, spelled for the console. Read once
#: because the table is a module constant; a test asserts it stays in step.
_COMMENT_PLATFORMS = '/'.join(comment_platforms())

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = Config.SECRET_KEY
CORS(app)


def _upload_limit_mb(default: int = 64) -> int:
    """Read MAX_UPLOAD_MB as a sane number of megabytes (clamped to 1 … 10 GiB).

    The ceiling has to be configurable — a big dataset stays uploadable by
    raising it — but a typo in the environment must not *disable* it, so an
    unparseable, infinite or non-positive value falls back to the default.
    """
    raw = str(os.environ.get('MAX_UPLOAD_MB', '') or '').strip()
    try:
        value = int(float(raw)) if raw else default
    except (TypeError, ValueError, OverflowError):
        value = default
    if not math.isfinite(value):
        value = default
    return min(max(1, value), 10 * 1024)


# Werkzeug parses a POST body into RAM *before* any handler runs, so without a
# ceiling one request of whatever size the client liked (an upload, a giant
# paste) was enough to exhaust the process. Flask rejects an over-long body
# while it streams in, which is also why the 413 handler below exists: the
# default answer is HTML and every caller here parses JSON.
UPLOAD_LIMIT_MB = _upload_limit_mb()
app.config['MAX_CONTENT_LENGTH'] = UPLOAD_LIMIT_MB * 1024 * 1024

logger = setup_logger(
    Config.LOG_DIR,
    max_bytes=Config.LOG_MAX_BYTES,
    backup_count=Config.LOG_BACKUP_COUNT,
)

# Catalogue self-check. A message template carrying a printf placeholder never
# raises — it just prints as a literal "%s" in the console — so surface it here,
# where the offending key is named, instead of leaving it to be spotted later.
for _issue in audit():
    logger.warning(t('misc.i18nAudit', issue=_issue))

# Thread-local storage: tracks which workflow index the current thread belongs to.
# Used by LogBufferHandler, _LogTee, and add_log to route log lines into the
# correct per-workflow buffer (_wf_logs[wf_idx]) in parallel mode.
_wf_local = threading.local()


# Console lines kept in memory. The frontend only ever renders the last 200,
# but the total count has to keep growing so the browser can tell how many it
# has not seen yet (see _push_log).
LOG_KEEP = 5000

# Every message that reaches the console is i18n.t(key, **params) — add_log,
# logging, and print() all funnel through here.


def _push_log(line: str, wf_idx: int = None):
    """Append one console line, keeping the buffer bounded.

    ``_log_total`` counts every line ever produced, not the number retained: the
    status endpoint ships only the tail, so without a running total the browser
    cannot work out the delta and the console silently freezes at 200 lines.

    A payload carrying newlines is split into one entry per physical line. A
    driver's ``Message: …`` block, a site's own multi-line refusal and a
    ``logger.exception`` traceback all arrived as a SINGLE entry, which the browser
    counts as one line while the DOM renders several (``.console-line`` is
    ``white-space: pre-wrap``) — the delta cursor then skipped or repeated real
    content, blank lines came back through this path after the logger handler
    filtered them, and the 200-line tail could be spent by one traceback.
    """
    idx = wf_idx if wf_idx is not None else getattr(_wf_local, 'idx', None)
    parts = [part for part in line.splitlines() if part.strip()]
    if not parts:
        return
    # _completed_lock now guards every reader of the console buffers (status
    # endpoint snapshots them), so the writers hold it too.
    with _completed_lock:
        logs = execution_state['logs']
        logs.extend(parts)
        if len(logs) > LOG_KEEP:
            del logs[:-LOG_KEEP]
        # The total moves by the number of LINES appended, not by the number of
        # add_log calls — that total is what the browser's delta cursor reads.
        execution_state['_log_total'] += len(parts)
        if idx is not None:
            buf = execution_state['_wf_logs'].setdefault(idx, [])
            buf.extend(parts)
            if len(buf) > LOG_KEEP:
                del buf[:-LOG_KEEP]
            execution_state['_wf_log_total'][idx] = execution_state['_wf_log_total'].get(idx, 0) + len(parts)


class LogBufferHandler(logging.Handler):
    """Feed all logger.info/error/warning calls into execution_state['logs'] for the frontend."""

    def emit(self, record):
        if record.name.startswith('werkzeug'):
            return
        msg = self.format(record)
        stripped = msg.strip()
        # Blank lines and '=' banner rows are how a standalone script keeps its
        # terminal output readable. In the UI console they are pure noise the
        # user scrolls past, so the console handler drops them — the file log
        # (root handler's twin) still receives every line.
        if not stripped or (len(set(stripped)) == 1 and stripped[0] in '=-*#─—'):
            return
        _push_log(f'[{time.strftime("%H:%M:%S")}] {msg}')

    def format(self, record):
        return record.getMessage()


_log_handler = LogBufferHandler()
_log_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)


class _LogTee:
    """Fallback: tee print() output into execution_state['logs'] (catches analyzer print() calls)."""

    def __init__(self, original):
        self._original = original

    def write(self, text):
        if text and text != '\n':
            ts = time.strftime('%H:%M:%S')
            for line in text.rstrip('\n').split('\n'):
                msg = line.rstrip()
                if msg:
                    _push_log(f'[{ts}] {msg}')
        self._original.write(text)

    def flush(self):
        self._original.flush()


cookie_manager = CookieManager(Config.COOKIE_DIR)
workflow_manager = WorkflowManager()
history_service = ExecutionHistoryService()


@app.before_request
def _apply_request_lang():
    """Pin the console language for this request/worker thread.

    The UI language rides along as the ``X-Lang`` header (the frontend patches
    fetch once so every call carries it); ``?lang=`` is accepted for manual
    calls. Requests are served by Flask's own thread pool, so this is the only
    place that can set it for the non-workflow endpoints.
    """
    set_lang(request.headers.get('X-Lang') or request.args.get('lang') or 'zh')


# Uploaded, pasted and cleaned files live in the DatasetStore (data/datasets.db)
# rather than in this process. They back the Upload node exactly as the registry
# below used to — a file becomes ordinary rows, and no downstream node knows it
# did not come from a crawl — except that a workflow saved today still finds its
# file tomorrow.
#
# The dictionary is only a read-through cache now: the store is the source of
# truth, so anything registered days ago still resolves.
_dataset_cache = {}
_DATASET_CACHE_MAX = 24
_DATASET_STORE = None
_DATASET_LOCK = threading.Lock()


def get_dataset_store() -> DatasetStore:
    """The single SQLite store behind persisted files, opened on first use."""
    global _DATASET_STORE
    if _DATASET_STORE is None:
        with _DATASET_LOCK:
            if _DATASET_STORE is None:
                _DATASET_STORE = DatasetStore()
    return _DATASET_STORE


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


def _json_safe_records(df: pd.DataFrame, limit: int = None) -> list:
    """Convert a DataFrame slice to JSON-safe records: NaN/NaT become None
    (raw NaN is not valid JSON and breaks JSON.parse() in the browser)."""
    page = df.head(limit) if limit is not None else df
    return page.astype(object).where(pd.notna(page), None).to_dict('records')


def _durable_node_rows(node_id: str, workflow_name: str = '') -> list:
    """Rows this node produced in an earlier run, newest first — or [].

    Previews, charts and exports all resolve a node by id, and
    execution_state['results'] only exists while the process has been running
    without a refresh. Everything since then is in the run store, so asking
    there is what keeps a reopened workflow inspectable instead of blank.

    Asking by id alone is the trap: ``node-2`` exists on every canvas ever
    drawn, so a lookup with no workflow attached to it would happily return a
    stranger's rows — a table that looks correct and belongs to another
    workflow. So an identity is required: the request's own workflow name (what
    the browser is showing, which beats what this process happened to run last),
    or the fingerprint/name the last run recorded. With neither, the answer is
    empty, and the panel says there is nothing recorded.
    """
    store = get_run_store()
    requested = str(workflow_name or '').strip()
    if requested:
        exact = store.latest_rows(node_id, workflow_name=requested)
        if exact[1]:
            return exact[1]
        # ``A + B`` is how a parallel run is recorded; the same canvas filed its
        # earlier runs under ``A`` alone, so both spellings are offered rather than
        # leaving a week-old run's rows unreachable behind one string. Only after the
        # name the browser is showing matched nothing, though: a workflow genuinely
        # called ``R&B`` would otherwise have the ``R`` of somebody else's
        # ``R + B`` offered as a candidate, and a stranger's table under the user's
        # own node name is exactly the false data this function exists to refuse.
        parts = [part.strip() for part in requested.split('+') if part.strip()]
        if not parts or parts == [requested]:
            return []
        return store.latest_rows(node_id, workflow_name=requested, workflow_names=parts)[1]
    fingerprint = execution_state.get('fingerprint') or ''
    ambient = execution_state.get('workflow_name') or ''
    if not fingerprint and not ambient:
        return []
    return store.latest_rows(node_id, fingerprint=fingerprint, workflow_name=ambient)[1]


def _resolve_dataframe(payload: dict) -> pd.DataFrame:
    """Resolve a DataFrame from a request payload that may reference a
    persisted file, a workflow node's result (live *or* recorded), or inline
    records."""
    dataset_id = payload.get('dataset_id')
    if dataset_id:
        df = _load_dataset(dataset_id)
        if df is None:
            raise KeyError(f'Unknown dataset_id: {dataset_id}')
        return df

    node_id = payload.get('node_id')
    if node_id:
        result = execution_state['results'].get(node_id)
        if isinstance(result, list):
            return pd.DataFrame(result)
        # Nothing live: fall back to the rows this node last filed away, which
        # is also the only copy left after a restart.
        rows = _durable_node_rows(node_id, payload.get('workflow_name') or '')
        if rows:
            return pd.DataFrame(rows)
        raise KeyError(f'No tabular result available for node: {node_id}')

    records = payload.get('data')
    if records is not None:
        return pd.DataFrame(records)

    raise KeyError('No data source provided (dataset_id, node_id, or data)')


def _tokenize_dataframe(df: pd.DataFrame, params: dict) -> pd.DataFrame | None:
    """Apply tokenization to a DataFrame and return the result, or None if the
    column is missing."""
    column = params.get('text_column', '')
    if column not in df.columns:
        return None
    output_mode = params.get('output_mode', 'word_freq')
    top_n = params.get('top_n', '')
    kwargs = {}
    if output_mode == 'word_freq' and top_n:
        kwargs['top_n'] = _safe_int(top_n, 120, minimum=1)
    labels, values = VisualizationService.tokenize_frequency(df, column, **kwargs)
    if not labels:
        return pd.DataFrame()
    if output_mode == 'words_only':
        return pd.DataFrame([{'word': w} for w in labels])
    if output_mode == 'csv_line':
        return pd.DataFrame([{'words': ' '.join(labels)}])
    return pd.DataFrame([{'word': w, 'frequency': v} for w, v in zip(labels, values, strict=True)])


execution_state = {
    'running': False,
    'executor': None,
    'thread': None,
    'results': {},
    'logs': [],
    '_log_total': 0,  # lines ever produced (the list itself is capped)
    'total_nodes': 0,
    'completed_nodes': 0,
    # A run is not a binary. Nodes a dead upstream starved (`skipped`) and nodes
    # that died (`failed_nodes`) are neither done nor nothing, and the browser
    # used to guess the difference from `completed < total` — which called a
    # clean run with one skipped node "ended, can continue". `outcome` is the
    # worker's own verdict, published once the run stops.
    'skipped_nodes': 0,
    'failed_nodes': 0,
    # Node ids the CURRENT attempt visited. `runs.db` keeps the status of every
    # node ever run under this run id, including ones the canvas has since
    # deleted, so a verdict read from the whole record can blame today's run for
    # an older shape of the workflow.
    'attempted_nodes': set(),
    'outcome': '',
    'active_crawlers': set(),
    '_wf_logs': {},  # {wf_idx: [log lines]} per-workflow logs for parallel mode
    '_wf_log_total': {},  # {wf_idx: lines ever produced} — see _push_log
    '_wf_names': {},  # {wf_idx: the workflow's user-facing name} for console lines
    '_mode': 'serial',
    'llm': None,  # AI transport config from the settings panel (see /api/workflow/execute)
    'cancel_event': threading.Event(),  # set by Stop; checked between LLM rows
    # Which workflow was last opened, and what shape it has: previews resolve a
    # node from the database when results are gone, and these tell it which
    # workflow's rows count as "this node's".
    'workflow_name': '',
    # Every name node's label in canvas order — the record of a run that executed
    # several workflows carries all of their names, not just the first.
    'workflow_labels': [],
    'fingerprint': '',
    # Set when a crawl is bounced to a login wall mid-run (the cookie likely
    # expired). Surfaced to the browser through /api/workflow/status so it can
    # toast "refresh the cookie and resume" — the partial data is already safe.
    'cookie_expired': False,
}
_completed_lock = threading.Lock()
_execute_lock = threading.Lock()  # serializes the guard-and-claim of a new run


def _results_snapshot() -> dict:
    """A private copy of ``execution_state['results']``, taken under its lock.

    The run publishes a node's rows the moment that node finishes (see the
    ``publish`` callback in ``_llm_run_ctx``), so any read-only endpoint that
    *iterated* the live dict — ``.items()``, ``.keys()`` — could be stepping
    through it while that thread added the next node. Python then aborts the
    request with "RuntimeError: dictionary changed size during iteration".
    Copying under the same lock the writer holds is the cheap fix: the endpoint
    walks a stable snapshot and the run never has to wait for a status poll.
    """
    with _completed_lock:
        return dict(execution_state['results'])


# ─── Durable run state ──────────────────────────────────────────

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


def _housekeep(exclude_run_id: str = '', force: bool = False):
    """Apply the retention settings, containing every failure.

    A cleanup problem must never be what makes a run look failed, so nothing
    here propagates. ``exclude_run_id`` protects the record the caller is still
    writing — dropping its rows mid-run would destroy live state.
    """
    with contextlib.suppress(Exception):
        if force:
            get_housekeeper().run_now(exclude_run_id=exclude_run_id)
        else:
            get_housekeeper().maybe_run(exclude_run_id=exclude_run_id)


def _close_run(ctx: dict, outcome: str):
    """Record how a run ended. Never raises: losing the record must never lose
    the run itself — the rows were already safely in the database, this says
    only whether they are complete."""
    with contextlib.suppress(Exception):
        ctx['store'].settle_nodes(ctx['run_id'])
        ctx['store'].finish_run(ctx['run_id'], outcome)


def _item_scope(ctx: dict, node: dict) -> str:
    """Namespace for "have I crawled this already?".

    The node fingerprint, not the run id: an item collected once under this
    keyword must not be collected again by the next attempt, or by another
    workflow that asks the same question. That is what keeps a resumed crawl
    from handing back duplicates.
    """
    return 'item:' + str((ctx.get('fingerprints') or {}).get(node.get('id') or '', ''))


def _workflow_needs_llm(workflow: dict) -> bool:
    """True when any process node in the payload will actually call a model.

    Cleaner always does; the two classifiers only when they are not running the
    locally trained scikit-learn model; entity recognition only when it was
    switched over to the model, since its rules need nothing. A crawl-and-save
    workflow must not be blocked by a missing API key or an unpicked Ollama tag —
    the frontend makes the same distinction (``nodeNeedsLlm``) before it opens
    the console.
    """
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'process':
            continue
        params = node.get('params') or {}
        op = str(params.get('operation') or node.get('operation') or '')
        if op == 'clean':
            return True
        if op in ('emotion', 'tendency') and str(params.get('mode') or '') != 'ml':
            return True
        # NER is the opposite default: rules first, a model only when asked.
        if op == 'ner' and str(params.get('mode') or '') == 'llm':
            return True
    return False


def _llm_run_ctx(node: dict, op: str, ctx: dict = None) -> dict:
    """Build the per-node run context the LLM analyzers consume.

    The transport (local Ollama vs OpenRouter API), model, key and batching
    all come from the settings panel via the execute request. ``publish``
    makes finished rows visible node-by-node: the node's entry in
    execution_state['results'] updates after every batch, so a crash or a
    stop mid-run leaves the partial table usable instead of gone.

    Every answered row also lands in a *cache keyed by text*, not by row
    index (``RowCache``, in runs.db when a run is being recorded). Re-running
    after a re-crawl — where nothing sits at the same index any more — still
    gets those answers free instead of paying the model twice for the same
    sentence. The JSONL checkpoint stays as the fallback for callers with no
    store. The cache SCOPE is assembled by the row runner itself: it is the
    one place that genuinely knows the prompt builder, the truncation cap and
    the daemon address, all of which change what an answer means.
    """
    cfg = execution_state.get('llm') or {}
    provider = cfg.get('provider') or 'ollama'
    client = LLMClient(
        provider=provider,
        model=cfg.get('model') or '',
        api_key=cfg.get('api_key') or '',
        # Cleaner outputs a full rewritten text; the classifiers answer in a
        # dozen tokens. Capping keeps a chatty model from burning quota.
        max_tokens=2048 if op == 'clean' else 512,
        max_chars=cfg.get('max_chars') or 0,
        timeout=300 if provider == 'ollama' else 120,
        # Daemon address pinned when the run started (设置 → Ollama 服务地址),
        # so a settings save mid-run cannot split one run across two hosts.
        # OpenRouter's address is its endpoint, not a setting.
        host=(cfg.get('ollama_host') or '') if provider == 'ollama' else '',
        # Retries sleep between attempts; Stop used to wait them out in full
        # (backoff + Retry-After + a 300 s daemon timeout could mean minutes).
        # The client now naps on this event instead, so Stop lands between
        # attempts rather than after them.
        cancel_event=execution_state.get('cancel_event'),
    )
    node_id = node.get('id', '')
    # ── live snapshot (AI 调用实时导出) ──
    # A long LLM pass enriches rows in batches; the honest artifact there is
    # 'the table as it stands', so every settled batch rewrites the whole
    # snapshot (atomic tmp+replace — an opened file is never half-written).
    live_writer = None
    if bool((node.get('params') or {}).get('live_export')):
        from services.part_writer import SnapshotWriter, safe_stem

        stem = safe_stem(f'{execution_state.get("workflow_name") or "llm"}-{node_id}')
        lfmt = 'json' if str((node.get('params') or {}).get('format') or 'csv') == 'json' else 'csv'
        live_writer = SnapshotWriter(Config.EXPORT_DIR, stem, lfmt)
        add_log(t('run.live_export', file=os.path.basename(live_writer.path)))

    def publish(df):
        records = df.to_dict('records')
        with _completed_lock:
            execution_state['results'][node_id] = records
        if live_writer is not None:
            try:
                live_writer.write(records)
            except Exception as e:
                # run_llm_rows swallows publish errors; say it out loud here
                # so a read-only export dir does not silently kill the feature.
                add_log(t('run.live_export_failed', err=e))

    run_ctx = {
        'client': client,
        'node_id': node_id,
        'batch_size': cfg.get('batch_size') or 10,
        # API providers tolerate a little concurrency (free tiers are shared
        # and rate-limited); the local daemon serves one request at a time.
        'workers': (cfg.get('workers') or 3) if provider == 'openrouter' else 1,
        'publish': publish,
        'cancel_event': execution_state.get('cancel_event'),
        'checkpoint_dir': Config.LLM_CHECKPOINT_DIR,
    }
    if ctx is not None:
        # Only the store is lent — see the docstring on why the row runner
        # builds the cache scope itself.
        run_ctx['store_for_cache'] = ctx['store']
    return run_ctx


def add_log(msg: str, wf_idx: int = None):
    if not str(msg or '').strip():
        # A blank console row is noise the logger path already filters; stamping it
        # would turn ``''`` into a line carrying nothing but a clock.
        return
    _push_log(f'[{time.strftime("%H:%M:%S")}] {msg}', wf_idx)


def _component_name(sub_engine) -> str:
    """This connected component's own workflow name, from its name node.

    The canvas may hold several workflows in one run, each headed by its own
    name node — recording them all under the *first* name on the canvas
    swallowed every other workflow's label (they all filed as the first
    one's name, or as "untitled" when the label sat in another component).
    """
    for node in sub_engine.nodes.values():
        if node.get('type') != 'name':
            continue
        label = str((node.get('params') or {}).get('workflow_name') or '').strip()
        if label:
            return label
    return ''


def _record_execution_history(
    workflow: dict, engine: WorkflowEngine, results: dict, workflow_name: str = '', log_label: str = ''
):
    """After a run completes, snapshot per-node metrics (row counts, and
    emotion/tendency distributions where present) into execution_history so
    /api/history/* can chart trends across runs over time. Best-effort: a
    failure here must never break the workflow run itself.

    The name matters: without it every run was filed as "untitled" and the
    history panel's per-workflow grouping could not distinguish anything.
    """
    try:
        run_id = uuid.uuid4().hex[:12]
        workflow_name = str(workflow_name or (workflow or {}).get('name') or '').strip() or 'untitled'
        ts = history_service.now()
        rows = []
        # One run can have several nodes carrying the same distribution — the
        # emotion process computes it, then the output node exports the very
        # same column, and both used to be recorded. Two identical points at
        # one timestamp drew a doubled tooltip, so per run a (metric, label)
        # pair is recorded once, from the first node that produced it.
        seen_metrics = set()
        for nid, result in results.items():
            if not isinstance(result, list) or not result:
                continue
            node = engine.nodes.get(nid, {})
            ntype = node.get('type', '?')
            rows.append((run_id, workflow_name, nid, ntype, 'rows', 'count', float(len(result)), ts))

            df = pd.DataFrame(result)
            if 'emotion' in df.columns:
                dist = StatsService.emotion_distribution(result)
                for label, value in zip(dist['labels'], dist['values'], strict=True):
                    if ('emotion', label) in seen_metrics:
                        continue
                    seen_metrics.add(('emotion', label))
                    rows.append((run_id, workflow_name, nid, ntype, 'emotion', label, float(value), ts))
            if 'tendency' in df.columns:
                dist = StatsService.tendency_distribution(result)
                for label, value in zip(dist['labels'], dist['values'], strict=True):
                    if ('tendency', label) in seen_metrics:
                        continue
                    seen_metrics.add(('tendency', label))
                    rows.append((run_id, workflow_name, nid, ntype, 'tendency', label, float(value), ts))

        history_service.record_many(rows, log_label=log_label)
    except Exception:
        logger.exception(t('misc.history_failed'))


# ─── API Routes ────────────────────────────────────────────────


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ─── Request validation helpers ────────────────────────────────


def _json_body() -> dict | None:
    """The request's JSON body as an object, or ``None`` when it is unusable.

    Every POST handler here used to open with ``request.get_json()`` (optionally
    ``or {}``). A body that is *valid JSON but not an object* — ``null``,
    ``[1, 2]``, ``"abc"`` — then reached ``data.get(...)`` and raised
    AttributeError, i.e. an HTML 500 for what is a client mistake; and the
    ``silent=True`` variants hid the same mistake behind an empty dict, so the
    handler answered as if the user had sent nothing.

    A request with no body at all keeps meaning "no fields" (``{}``), which is
    what ``or {}`` did and what the frontend relies on for its optional
    payloads. Only a body that *is* there but is not an object is refused.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    # ``get_json`` answers None both for "nothing to parse" and for the literal
    # ``null``, so the raw bytes tell those two apart.
    if not request.is_json or not request.get_data().strip():
        return {}
    return None


def _bad_body():
    """The 400 every route returns for a body :func:`_json_body` refused."""
    return jsonify({'ok': False, 'error': t('api.bodyNotObject')}), 400


def _bad_param(name: str):
    """The 400 for one body field whose type a handler cannot work with."""
    return jsonify({'ok': False, 'error': t('api.paramInvalid', name=name)}), 400


def _resolve_payload_dataframe(data: dict):
    """``(df, None)`` for a usable payload, or ``(None, response)`` for its 400.

    :func:`_resolve_dataframe` reports an unknown reference as a KeyError, which
    every route here already turned into a 400 — but a reference of the wrong
    *shape* (``{"data": 42}``) dies in the pandas constructor with a
    ValueError/TypeError instead, and that escaped as an HTML 500. Both are the
    caller's mistake, so both answer the same way, with the reason.
    """
    try:
        return _resolve_dataframe(data), None
    except (KeyError, TypeError, ValueError) as e:
        return None, (jsonify({'ok': False, 'error': str(e)}), 400)


@app.errorhandler(413)
def _payload_too_large(error):
    """Answer the request-size ceiling in JSON, not with Werkzeug's HTML page.

    ``request.json()`` in the browser throws before the status is ever looked
    at, which turned a clear "too big" into an unparseable response.
    """
    limit_bytes = int(app.config.get('MAX_CONTENT_LENGTH') or 0)
    mb = round(limit_bytes / (1024 * 1024), 2) if limit_bytes > 0 else UPLOAD_LIMIT_MB
    return jsonify({'ok': False, 'error': t('api.payloadTooLarge', limit=mb)}), 413


# ─── Workflow API ──────────────────────────────────────────────


def _workflow_dataset_refs(workflow: dict) -> dict:
    """{node_id: params} for every Upload node that carries a file.

    Saving records these alongside the JSON, so the mapping "this node of this
    workflow reads that file" survives a hand-edited file, a rename, or a job
    that restores only the database.
    """
    refs = {}
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'upload':
            continue
        params = node.get('params') or {}
        if str(params.get('dataset_id') or ''):
            refs[str(node.get('id') or '')] = params
    return refs


def _restore_workflow_datasets(name: str, workflow: dict) -> list:
    """Put every Upload node back in touch with the file it was saved with.

    A reopened workflow should run, not ask for the file again. Where the id
    no longer resolves, the same *file name and row count* is looked up before
    the node is declared empty — re-uploading an unchanged CSV is enough to
    bring the whole workflow back to life. Returns one report entry per Upload
    node so the UI can say exactly which files came back and which did not.
    """
    store = get_dataset_store()
    refs = store.refs_for(name)
    report = []
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'upload':
            continue
        node_id = str(node.get('id') or '')
        params = node.get('params') or {}
        node['params'] = params
        entry = {
            'node_id': node_id,
            'dataset_id': str(params.get('dataset_id') or ''),
            'name': str(params.get('dataset_name') or ''),
            'row_count': _optional_int(params.get('row_count')) or 0,
            'restored': False,
            'rebound': False,
            'missing': False,
        }
        dataset_id = entry['dataset_id'] or str((refs.get(node_id) or {}).get('dataset_id') or '')
        meta = store.meta(dataset_id) if dataset_id else None
        if meta is None and dataset_id:
            # Same name, same size → almost certainly the same file.
            replacement = store.find_replacement(entry['name'], entry['row_count'] or None)
            if replacement:
                meta = store.meta(replacement)
                entry['rebound'] = True
                logger.info(t('ds.rebound', name=entry['name'] or replacement, did=replacement))
        if meta is None:
            # Nothing left to point at: drop the id so the UI asks for a file
            # instead of claiming one is attached.
            params['dataset_id'] = ''
            params['row_count'] = ''
            entry['missing'] = bool(entry['dataset_id'])
            entry['dataset_id'] = ''
            if entry['missing']:
                logger.warning(t('ds.missing', name=entry['name'] or '?'))
        else:
            _apply_dataset_meta(params, meta)
            entry['dataset_id'] = meta['dataset_id']
            entry['restored'] = True
        report.append(entry)
    return report


def _request_workflow_name(raw) -> str | None:
    """Validate the workflow name a *load* or *delete* request asks for.

    ``WorkflowManager.clean_name`` deliberately falls back to ``'untitled'`` for
    anything that cleans down to nothing — right for **save**, where a blank name
    field just labels the file, and wrong for the two routes that address an
    existing file: ``''`` and ``'..'`` both resolved to *untitled*, so a delete
    with an unset name in the browser removed an unrelated workflow (and a load
    opened it). Those two now have to name something that survives cleaning on
    its own merits; the returned stem is what the store is called with.
    """
    if not isinstance(raw, str):
        return None
    name = raw.strip()
    if not name:
        return None
    clean = workflow_manager.clean_name(name)
    if clean == WorkflowManager.DEFAULT_NAME and name != WorkflowManager.DEFAULT_NAME:
        # The name cleaned down to nothing, so the fallback would point at
        # somebody else's file.
        return None
    return clean


@app.route('/api/workflow/save', methods=['POST'])
def save_workflow():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = data.get('name', 'untitled')
    workflow = data.get('workflow', {})
    if not isinstance(workflow, dict):
        return jsonify({'ok': False, 'error': t('api.paramInvalid', name='workflow')}), 400
    try:
        path = workflow_manager.save(name, workflow)
    except OSError as e:
        logger.exception(t('misc.save_workflow_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500
    # The file mapping is part of the save: every Upload node records which
    # stored dataset it reads, so reopening this workflow later finds its file
    # already loaded instead of asking for another upload.
    bound = get_dataset_store().bind(workflow_manager.clean_name(name), _workflow_dataset_refs(workflow))
    if bound:
        logger.info(t('store.datasets_bound', wf=workflow_manager.clean_name(name), n=bound))
    return jsonify({'ok': True, 'path': path, 'datasets': bound})


@app.route('/api/workflow/load', methods=['GET'])
def load_workflow():
    name = _request_workflow_name(request.args.get('name'))
    if name is None:
        return jsonify({'ok': False, 'error': t('api.workflowNameRequired')}), 400
    workflow = workflow_manager.load(name)
    if not workflow:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    # Reconnect the nodes with their files *before* the canvas draws them, so
    # the workflow it returns is the runnable one.
    datasets = _restore_workflow_datasets(name, workflow)
    execution_state['workflow_name'] = str(workflow.get('name') or name or '')
    execution_state['fingerprint'] = workflow_fingerprint(workflow)
    return jsonify({'ok': True, 'workflow': workflow, 'datasets': datasets})


@app.route('/api/workflow/list', methods=['GET'])
def list_workflows():
    return jsonify({'ok': True, 'workflows': workflow_manager.list_workflows()})


@app.route('/api/workflow/delete', methods=['POST'])
def delete_workflow():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = _request_workflow_name(data.get('name', ''))
    if name is None:
        return jsonify({'ok': False, 'error': t('api.workflowNameRequired')}), 400
    workflow_manager.delete(name)
    # The files stay: another workflow may well read the same one, and an
    # orphan is cleaned up later rather than on a deletion the user may undo
    # by saving something else with the same name.
    get_dataset_store().unbind(name)
    return jsonify({'ok': True})


# ─── Execution API ─────────────────────────────────────────────


# ─── Run queue ────────────────────────────────────────────────
# One run at a time is a property of this product, not an accident: the console,
# the crawl browsers, the checkpoint store and the resume cursor all assume a
# single writer. What was missing is somewhere to put the next request while one
# is busy — it used to be refused outright, and the user had to press Run again
# at the right moment.

#: Queued requests live in memory only. A restart drops them, which is the
#: honest behaviour for a list of intentions nobody is here to confirm.
QUEUE_MAX = 8

_RUN_QUEUE: list = []
_queue_lock = threading.Lock()


def _workflow_shape_error(data: dict) -> str:
    """Why this payload cannot become a run, or '' when it can.

    Checked before the slot is claimed, in both the live and the queued path:
    ``WorkflowEngine`` walks ``nodes`` expecting dicts, so a list of strings or a
    ``settings`` that is a number raises AttributeError deep inside the worker —
    which the browser then reads as an HTML error page, and a queued one would
    fail minutes later in a thread nobody is watching.
    """
    workflow = data.get('workflow')
    if workflow is None or workflow == {}:
        return ''  # an empty payload is refused by validate(), with a real message
    if not isinstance(workflow, dict):
        return t('api.workflowShapeInvalid')
    nodes = workflow.get('nodes')
    if nodes is not None and (not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes)):
        return t('api.workflowShapeInvalid')
    settings = workflow.get('settings')
    if settings is not None and not isinstance(settings, dict):
        return t('api.workflowShapeInvalid')
    return ''


def _resume_refusal(data: dict) -> str:
    """Why a 继续 request cannot continue, or '' when it can.

    The run id a resume asks for is the whole point of the feature: it names the
    rows and cursors already paid for. When retention (or the records panel) has
    deleted that run in the meantime, reusing its id starts an *empty* run under
    the same name — which looks exactly like a continue that found nothing, while
    quietly re-crawling and re-paying for every item. So the request is refused
    with the id in the message, and the banner can say so.
    """
    resume_run_id = str(data.get('resume_run_id') or '').strip()
    if not resume_run_id:
        return ''
    try:
        if get_run_store().get_run(resume_run_id):
            return ''
    except Exception:
        # A store that cannot answer is not evidence that the run is gone; the
        # run itself reports the real failure the moment it opens the database.
        return ''
    return t('api.resumeMissing', rid=resume_run_id)


def _enqueue_run(data: dict, lang_header: str) -> dict:
    """Park a request until the running one finishes.

    The payload is checked here, at the moment the user pressed the button, and
    not at drain time: a request that cannot become a run must be refused to the
    browser that sent it, where someone can fix it. Discovered minutes later, in
    another thread, it would only be a missing run.
    """
    if _workflow_shape_error(data):
        return {'status': 400, 'body': {'ok': False, 'error': _workflow_shape_error(data)}}
    workflow = data.get('workflow') or {}
    name = str(data.get('workflow_name') or workflow.get('name') or '').strip()
    with _queue_lock:
        if len(_RUN_QUEUE) >= QUEUE_MAX:
            return {'status': 409, 'body': {'ok': False, 'error': t('api.queueFull', n=QUEUE_MAX)}}
        entry = {
            'id': uuid.uuid4().hex[:12],
            'workflow_name': name,
            'nodes': len(workflow.get('nodes') or []),
            'data': data,
            'lang': lang_header or '',
            'queued_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        _RUN_QUEUE.append(entry)
        position = len(_RUN_QUEUE)
    # ``wf.unnamed`` renders 「未命名工作流{i}」 with the WORKFLOW's index on the canvas;
    # this is a queue POSITION, and feeding one into the other printed 「已排队（第 2
    # 位）：未命名工作流2」 where the 2 happened to be the depth of the queue.
    add_log(t('run.queued', name=name or t('run.queuedUnnamed'), at=position))
    return {
        'status': 200,
        'body': {
            'ok': True,
            'queued': True,
            'queue_id': entry['id'],
            'position': position,
            'message': t('api.queued', at=position),
        },
    }


def queue_snapshot() -> list:
    """The waiting requests, oldest first — without their payloads."""
    with _queue_lock:
        return [{key: entry[key] for key in ('id', 'workflow_name', 'nodes', 'queued_at')} for entry in _RUN_QUEUE]


def cancel_queued(queue_id: str) -> bool:
    """Drop one waiting request by its queue id. True when it is gone."""
    with _queue_lock:
        for position, entry in enumerate(_RUN_QUEUE):
            if entry['id'] == queue_id:
                del _RUN_QUEUE[position]
                return True
    return False


def clear_queue() -> int:
    with _queue_lock:
        count = len(_RUN_QUEUE)
        del _RUN_QUEUE[:]
    return count


def _start_next_queued() -> None:
    """Hand the slot to the oldest waiting request, at the end of a run.

    Called from the finishing thread *after* it released the slot and cleared its
    own handle: the claim also checks thread liveness, so a thread still alive
    while it unwinds would make this call queue the next request behind itself —
    and nothing would ever start it again.
    """
    with _queue_lock:
        entry = _RUN_QUEUE.pop(0) if _RUN_QUEUE else None
    if entry is None:
        return
    try:
        answer = _begin_run(entry['data'], entry['lang'])
    except Exception as e:  # a broken request must not strand the ones behind it
        logger.exception(t('run.queueStartFailed'))
        add_log(t('run.queue_broken', name=entry['workflow_name'] or entry['id'], err=e))
        _start_next_queued()
        return
    body = answer.get('body') or {}
    if answer.get('drop'):
        # Refused at the moment of starting in a way a retry can never fix — the
        # record a 继续 pointed at has been purged while it waited. Without this
        # the entry would be pushed back and refused again after every run.
        add_log(t('run.queue_broken', name=entry['workflow_name'] or entry['id'], err=body.get('error', '')))
        _start_next_queued()
        return
    if answer.get('status') == 200 and body.get('ok') and not body.get('queued'):
        add_log(t('run.queue_started', name=entry['workflow_name'] or entry['id'], rid=body.get('run_id', '')))
        return
    # Someone else took the slot in between (a manual Run press): put the
    # request back at the front rather than drop what the user already asked for.
    with _queue_lock:
        _RUN_QUEUE.insert(0, entry)
        add_log(t('run.queue_waited', name=entry['workflow_name'] or entry['id']))


@app.route('/api/workflow/execute', methods=['POST'])
def execute_workflow():
    """Start a run — or queue the request when a run is already going."""
    data = _json_body()
    if data is None:
        return _bad_body()
    answer = _begin_run(data, request.headers.get('X-Lang') or '')
    return jsonify(answer['body']), answer['status']


@app.route('/api/workflow/queue', methods=['GET'])
def workflow_queue():
    """What is waiting, in the order it will start."""
    return jsonify({'ok': True, 'queue': queue_snapshot(), 'max': QUEUE_MAX})


@app.route('/api/workflow/queue/cancel', methods=['POST'])
def workflow_queue_cancel():
    """Drop one waiting request. The running one is never touched."""
    data = _json_body()
    if data is None:
        return _bad_body()
    queue_id = data.get('id')
    if not isinstance(queue_id, str) or not queue_id.strip():
        return _bad_param('id')
    return jsonify({'ok': True, 'removed': cancel_queued(queue_id.strip())})


@app.route('/api/workflow/queue/clear', methods=['POST'])
def workflow_queue_clear():
    """Empty the queue — 'do not start any of these', not 'stop the run'."""
    return jsonify({'ok': True, 'cleared': clear_queue()})


def _begin_run(data: dict, lang_header: str) -> dict:
    """Claim the run slot and start the worker, or put this request in the queue.

    Split out of the route because the queue drains by calling *this* function
    from the finishing run's own thread: a queued request has to be started the
    same way a live one is — same validations, same claim, same bookkeeping —
    or the queue would be a second, weaker execution path.

    Answers ``{'status': int, 'body': dict}`` instead of a Flask response,
    because the caller is not always a request.
    """
    shape_error = _workflow_shape_error(data)
    if shape_error:
        # Refused before the slot is claimed: a payload the engine cannot walk
        # must not become a failed run record, let alone a queued one that dies
        # in a thread nobody is watching.
        return {'status': 400, 'body': {'ok': False, 'error': shape_error}}
    resume_error = _resume_refusal(data)
    if resume_error:
        # 'drop' tells the queue this entry can never start, so it is discarded
        # rather than pushed back to wait for a run that no longer exists.
        return {'status': 400, 'body': {'ok': False, 'error': resume_error}, 'drop': True}
    # Guard and claim are one critical section. They used to be ~70 lines
    # apart: two concurrent POSTs both passed the check, both started a run
    # thread, and interleaved writes into one console, one store, one crawl.
    with _execute_lock:
        running_thread = execution_state['thread']
        # The previous run's thread may still be unwinding after a Stop (it clears
        # `running` first), so check liveness too — otherwise a quick Stop → Run
        # leaves two threads appending to the same console and results.
        if execution_state['running'] or (running_thread is not None and running_thread.is_alive()):
            if data.get('queue') is False:
                # The explicit "refuse instead of wait" door, kept because the
                # banner's 继续 wants to fail fast, not silently reorder runs.
                return {'status': 400, 'body': {'ok': False, 'error': t('api.alreadyRunning')}}
            return _enqueue_run(data, lang_header)

        # Claim under the same lock that reads it — no second request can slip
        # through while this one is still validating.
        execution_state['running'] = True
        started = False
        try:
            workflow = data.get('workflow', {})
            settings = workflow.get('settings', {})
            mode = settings.get('mode', 'parallel')
            headless = settings.get('headless', True)
            max_workers = _safe_int(settings.get('max_workers'), Config.DEFAULT_MAX_WORKERS, minimum=1, maximum=16)
            # Per-run answer to "use the browser profile this time?" — None means the
            # user was never asked (or the canvas has no same-platform collision), so
            # the stored setting decides. Absence must not read as False: a browser
            # that sends nothing would otherwise switch profiles off for everyone.
            raw_profile = settings.get('use_profile')
            use_profile = None if raw_profile is None else bool(raw_profile)
            # Recorded with the run so the history panel can group by workflow rather
            # than showing every run as "untitled".
            # ── Resumable run identity ─────────────────────────────────
            # Continuing an interrupted run reuses its id, which is what makes the
            # stored rows of the old attempt the rows of the new one: same node rows,
            # same cursor, accumulating instead of duplicated.
            resume_run_id = str(data.get('resume_run_id') or '').strip()
            run_id = resume_run_id or uuid.uuid4().hex[:12]
            execution_state['run_id'] = run_id
            execution_state['resume'] = bool(resume_run_id)
            workflow_name = str(data.get('workflow_name') or workflow.get('name') or '').strip()
            # A name node on the canvas overrides whatever the browser sent: its label
            # is the user-facing category for this run in the Execution History panel.
            # EVERY name node contributes, in canvas order: a run that executes several
            # workflows records them as one run (that is what they are), and labelling it
            # with only the first swallowed the others — the user saw 热门榜 and concluded
            # 周排行榜's record had been lost. The engine's validate() guarantees each
            # label is non-empty before a run is allowed to start.
            labels = []
            for _node in workflow.get('nodes') or []:
                if _node.get('type') != 'name':
                    continue
                _label = str((_node.get('params') or {}).get('workflow_name') or '').strip()
                if _label and _label not in labels:
                    labels.append(_label)
            if labels:
                workflow_name = ' + '.join(labels)
            execution_state['workflow_labels'] = labels
            # Recorded so a preview can find this workflow's rows in the store once the
            # live results are gone (a refresh, a restart) rather than guessing from a
            # node id alone — "node-2" exists in every workflow.
            execution_state['workflow_name'] = workflow_name
            execution_state['fingerprint'] = workflow_fingerprint(workflow)

            # AI transport chosen in the settings panel: 'ollama' (local daemon) or
            # 'openrouter' (API). The key only ever lives in the browser's
            # localStorage; it travels with this request and is kept in memory.
            # Console language for this run. The UI sends it explicitly because the
            # run outlives the request that started it — and thread-locals are not
            # inherited by the worker threads below, so each one re-applies it.
            execution_state['lang'] = normalize(data.get('lang') or lang_header or 'zh')

            llm_cfg = data.get('llm') or {}
            llm = {
                'provider': llm_cfg.get('provider') or 'ollama',
                'model': (llm_cfg.get('model') or '').strip(),
                'api_key': (llm_cfg.get('api_key') or '').strip(),
                'ollama_host': str(get_setting('ollama_host') or ''),
                'batch_size': _safe_int(llm_cfg.get('batch_size'), 10, minimum=1, maximum=100),
                'max_chars': _safe_int(llm_cfg.get('max_chars'), 600, minimum=0, maximum=20000),
                'workers': _safe_int(llm_cfg.get('workers'), 3, minimum=1, maximum=8),
            }
            execution_state['llm'] = llm
            # Per-provider requirements: the key belongs to OpenRouter, the pulled tag
            # to the local daemon — and neither is demanded by a run that never calls
            # a model.
            if _workflow_needs_llm(workflow):
                if llm['provider'] == 'openrouter':
                    if not llm['api_key']:
                        return {'status': 400, 'body': {'ok': False, 'error': t('api.needApiKey')}}
                    if not llm['model']:
                        return {'status': 400, 'body': {'ok': False, 'error': t('api.needModel')}}
                elif not llm['model']:
                    return {'status': 400, 'body': {'ok': False, 'error': t('api.needOllamaModel')}}

            cancel_event = threading.Event()
            execution_state['cancel_event'] = cancel_event
            execution_state['results'] = {}
            execution_state['logs'] = []
            execution_state['_log_total'] = 0
            execution_state['_wf_logs'] = {}
            execution_state['_wf_log_total'] = {}
            execution_state['_wf_names'] = {}
            execution_state['total_nodes'] = 0
            execution_state['completed_nodes'] = 0
            execution_state['skipped_nodes'] = 0
            execution_state['failed_nodes'] = 0
            # Node ids THIS attempt visited. The run record outlives the canvas:
            # nodes deleted between attempts keep their stored status, so any
            # verdict read from the whole record can blame a finished run for a
            # failure that belonged to an older shape of the workflow.
            execution_state['attempted_nodes'] = set()
            execution_state['outcome'] = ''
            execution_state['cookie_expired'] = False
            execution_state['_mode'] = mode
            execution_state['executor'] = TaskExecutor(max_workers=max_workers, mode=mode)
            started = True
        finally:
            if not started:
                # A rejection (already-configured checks, malformed body) gives
                # the claim back — the guard must not lock out every later Run.
                execution_state['running'] = False

    def _wf_display_name(wf_engine, wf_idx: int) -> str:
        """Console name of one component: the user's 工作流命名 label when the
        canvas carries one, else the workflow name the browser sent with the
        run, else a localized placeholder. Never the old positional 'WF1' —
        an index the user cannot map back to a canvas is noise.

        A canvas holding two components and no name node has to be told apart
        somehow: both used to announce themselves with the same single name, so
        the console said the same workflow started twice, and the two console tabs
        carried identical labels. The index is appended only in that case, and
        only while the name is still the fallback.
        """
        named = _component_name(wf_engine)
        if named:
            return named
        fallback = str(execution_state.get('workflow_name') or '').strip() or t('wf.unnamed', i=wf_idx + 1)
        return (
            t('wf.component_indexed', name=fallback, i=wf_idx + 1, n=execution_state.get('wf_count') or 1)
            if (execution_state.get('wf_count') or 1) > 1
            else fallback
        )

    def _run_single_workflow(wf_engine, wf_idx: int, ctx: dict):
        """Execute one workflow (single connected component) level by level,
        with its own isolated wf_input. Returns {nid: result, ...}.

        At each level the input is SNAPSHOTTED so that forked nodes at the
        same level all receive the same parent data (e.g. node-1 → node-2 AND
        node-1 → node-4 → both see node-1's result, not node-2's).

        A node that fails no longer ends the branch. It hands downstream what
        it managed to produce — the rows the model already answered, the items
        the crawler already scraped — which is the whole point of checkpointing
        them, and the console says that is what happened.
        """
        _wf_local.idx = wf_idx
        # Console messages address this workflow by the name the user gave it
        # (its name node) — 'WF0' style indices forced a cross-reference against
        # the canvas for every line.
        wf_name = _wf_display_name(wf_engine, wf_idx)
        with _completed_lock:
            execution_state['_wf_names'][wf_idx] = wf_name
        levels = wf_engine.group_by_level()
        results = {}
        # Every node reads the result of the node wired into it. A level-wide
        # "last transform wins" input is wrong as soon as one workflow holds two
        # data branches: with s1→p1 and s2→p2 both feeding a later node, p1 and
        # p2 would each receive whichever source ran last, so p1 would silently
        # process s2's rows.
        upstream_of = {}
        for conn in wf_engine.connections:
            upstream_of.setdefault(conn['to'], []).append(conn['from'])

        def _node_of(nid: str) -> dict:
            return wf_engine.nodes.get(nid) or {}

        def _inputs_for(nid: str):
            """→ (rows of the first incoming connection, [(parent_id, result), …]).

            The full list travels with the node so a join can use the *second*
            incoming connection as its right-hand table; every other node just
            takes the first one.
            """
            parents = upstream_of.get(nid) or []
            if not parents:
                # A source (crawler or upload) has nothing upstream.
                return [], []
            if len(parents) > 1:
                add_log(
                    t(
                        'wf.multi_input',
                        nid=node_label(_node_of(nid), nid),
                        up=node_label(_node_of(parents[0]), parents[0]),
                        n=len(parents),
                    ),
                    wf_idx=wf_idx,
                )
            pairs = [(pid, results.get(pid)) for pid in parents]
            primary = pairs[0][1]
            # A chart spec (dict) is not tabular input; neither is a node that
            # has not produced a list.
            return (primary if isinstance(primary, list) else []), pairs

        for level in levels:
            if not execution_state['running']:
                break
            for nid in level:
                if not execution_state['running']:
                    break
                node = wf_engine.nodes[nid]
                label = node_label(node, nid)
                with _completed_lock:
                    # Recorded before the node runs: one abandoned mid-crawl must
                    # still be in this attempt's population, or the settle pass in
                    # the finish line would filter the very node it exists to count.
                    execution_state['attempted_nodes'].add(nid)
                primary, upstream = _inputs_for(nid)
                result, status = _run_node_durable(ctx, node, headless, primary, upstream, wf_idx)
                results[nid] = result
                if status == NODE_SKIPPED:
                    # Neither done nor failed: it never got input to work on. The
                    # reason was announced by _run_node_durable; counting it as
                    # done would lie the other way.
                    with _completed_lock:
                        execution_state['skipped_nodes'] += 1
                    continue
                if status == NODE_RESTORED:
                    # 'run.restored' already announced this node in its own
                    # words; counting it as done is right — its rows are in
                    # hand — but a second line calling it 'completed' only
                    # repeats what the user just read.
                    with _completed_lock:
                        execution_state['completed_nodes'] += 1
                    continue
                with _completed_lock:
                    # Failed/partial do NOT count as done: the run's progress
                    # line must say how much actually finished, not how many
                    # nodes were visited. Their story is told by node_failed
                    # and the partial-rows line.
                    if status not in (NODE_FAILED, NODE_PARTIAL):
                        execution_state['completed_nodes'] += 1
                    done = execution_state['completed_nodes']
                    planned = execution_state['total_nodes']
                if status in (NODE_FAILED, NODE_PARTIAL):
                    continue
                if node.get('type') not in _QUIET_NODE_TYPES:
                    add_log(
                        t('wf.node_completed', wf=wf_name, nid=label, done=done, total=planned),
                        wf_idx=wf_idx,
                    )
        return results

    def run():
        # The run thread starts here, not in a request handler — inherit the
        # language the UI asked for, or every line below would come out in the
        # server default.
        set_lang(execution_state.get('lang'))
        sys.stdout = _LogTee(sys.__stdout__)
        # Everything below is recorded against one run row, so whatever leaves
        # this thread early — Stop, an exception, the process dying — leaves
        # behind enough state to continue instead of starting over.
        #
        # Opening the store is INSIDE the try on purpose. runs.db can refuse
        # (disk full, a file that is not a database, a locked connection), and a
        # thread that died before its ``finally`` would leave the application
        # believing a run is still in flight: ``running`` stuck True, the console
        # tee installed over every later request's stdout, and every subsequent
        # Run parked in a queue behind a run that can never finish.
        ctx = None
        outcome = RUN_FAILED
        try:
            store = get_run_store()
            wf_fp = workflow_fingerprint(workflow)
            ctx = {
                'store': store,
                'run_id': run_id,
                'resume': bool(resume_run_id),
                'fingerprints': fingerprints_for_workflow(workflow),
                'statuses': {},
                # The resume-node's "newest unfinished run" fallback must pick from
                # THIS workflow's shape only — node ids repeat across workflows.
                'wf_fp': wf_fp,
                # {node_id: count} of items the incremental ledger refused; the
                # status endpoint mirrors it (shared dict, written by row sinks).
                'skipped_seen': {},
                # None = follow the setting; True/False = what the user chose for
                # this run when the canvas asked them (parallel + same platform).
                'use_profile': use_profile,
            }
            execution_state['skipped_seen'] = ctx['skipped_seen']
            engine = WorkflowEngine(workflow, execution_state['executor'])
            errors = engine.validate()
            if errors:
                for e in errors:
                    add_log(t('wf.validation_error', err=e))
                execution_state['running'] = False
                # Mistakes in the definition, not something to continue later.
                # Announced as its own outcome: nothing ran, so a progress line
                # reading "0/N, can continue" would describe a run that never was.
                outcome = RUN_FAILED
                with _completed_lock:
                    execution_state['outcome'] = 'rejected'
                    execution_state['total_nodes'] = 0
                    execution_state['completed_nodes'] = 0
                add_log(t('run.rejected', n=len(errors)))
                return

            # Split into per-workflow connected components
            components = engine.find_workflows()
            components = engine.sort_workflows(components)
            sub_engines = [engine.extract_subworkflow(c) for c in components]

            wf_count = len(sub_engines)
            execution_state['wf_count'] = wf_count
            execution_state['total_nodes'] = sum(len(se.nodes) for se in sub_engines)
            add_log(t('wf.found', n=wf_count))

            store.start_run(
                run_id,
                workflow_name,
                wf_fp,
                mode=mode,
                headless=headless,
                llm=execution_state['llm'],
                lang=execution_state.get('lang'),
                node_total=execution_state['total_nodes'],
                wf_count=wf_count,
            )
            # Read *after* start_run so nodes left 'running' by the promotion
            # are visible as partial, which is what makes them resumable.
            ctx['statuses'] = store.node_statuses(run_id)
            if resume_run_id:
                previous = store.get_run(run_id) or {}
                saved = sum(int(n.get('row_count') or 0) for n in previous.get('nodes') or [])
                add_log(t('run.resume_from', at=previous.get('started_at') or '?', rows=saved))
            else:
                add_log(t('run.started', rid=run_id))
            if use_profile is False:
                # One line, because the alternative is the user reading a silent
                # deviation: the setting says profiles are on, and this run is
                # deliberately crawling in throwaway browsers instead.
                add_log(t('run.profileOff'))

            if mode == 'serial' or wf_count <= 1:
                # ── Serial: one workflow at a time ──
                all_results = {}
                for wf_idx, se in enumerate(sub_engines):
                    if not execution_state['running']:
                        break
                    # Tagged with its OWN index: this line is printed before
                    # _run_single_workflow sets the thread-local, so it used to be
                    # filed under the *previous* component's tab — workflow A's
                    # console announcing 「开始执行工作流「B」」.
                    add_log(t('wf.starting', name=_wf_display_name(se, wf_idx)), wf_idx=wf_idx)
                    try:
                        results = _run_single_workflow(se, wf_idx, ctx)
                    finally:
                        # Released, not left standing. Serial mode runs in the RUN
                        # thread, so the index of the component that just finished
                        # would otherwise route every later run-level line — the
                        # finish line, 存储不可用, the queue hand-off — into that one
                        # workflow's tab instead of the shared console.
                        _wf_local.idx = None
                    all_results.update(results)
                # update(), not replace(): a branch that died halfway already
                # published its partial rows, and they must survive the merge.
                # Under the readers' lock — /api/stats/* iterates this dict.
                with _completed_lock:
                    execution_state['results'].update(all_results)
                # No "workflow completed" line here: `run.finished` below says the
                # same thing with numbers attached, and two sentences for one fact
                # is two chances for them to disagree (they used to: a stopped run
                # still got told it had completed).
            else:
                # ── Parallel: one thread per workflow ──

                all_results = {}
                wf_lock = threading.Lock()

                def _run_workflow_wrapper(wf_engine, wf_idx):
                    # Pool threads do not inherit the starter's thread-local.
                    set_lang(execution_state.get('lang'))
                    try:
                        results = _run_single_workflow(wf_engine, wf_idx, ctx)
                        with wf_lock:
                            all_results.update(results)
                    except Exception:
                        # One console line per dead workflow. The log handler
                        # forwards every logger call to the console as well, so
                        # logging *and* add_log printed the same sentence twice —
                        # and the logger form is the one that also carries the
                        # traceback to the log file.
                        logger.exception(t('wf.wf_exception', wf=_wf_display_name(wf_engine, wf_idx)))
                    finally:
                        # Same release as the serial path: a pool thread that kept
                        # its index would file anything it logs afterwards —
                        # teardown included — under that one workflow's tab.
                        _wf_local.idx = None

                pool = ThreadPoolExecutor(max_workers=min(wf_count, max_workers))
                futures = [pool.submit(_run_workflow_wrapper, se, i) for i, se in enumerate(sub_engines)]
                # Wait for all to finish (respecting stop)
                for fut in futures:
                    if not execution_state['running']:
                        # Cancel remaining
                        for f in futures:
                            f.cancel()
                        break
                    with contextlib.suppress(Exception):
                        fut.result()
                pool.shutdown(wait=False, cancel_futures=True)

                # Merged whether or not the run finished: update() keeps partial
                # rows from branches that stopped mid-way (a Stop, or a dieing
                # LLM) instead of throwing away what they already produced.
                with wf_lock, _completed_lock:
                    execution_state['results'].update(all_results)
                # No "all workflows completed" line: `run.finished` below is the
                # one sentence that says how the run ended, with its numbers.

            still_running = execution_state['running']
            # Settle FIRST, then read the verdict. A node abandoned mid-crawl only
            # becomes partial/failed inside settle_nodes, and the comment here used to
            # promise the opposite of the code: the count was taken before that pass
            # (and from the whole record, so a node deleted from the canvas kept
            # failing every later 继续). Now the finish line, the stored outcome and
            # the browser's toast all describe the same settled, current attempt.
            store.settle_nodes(run_id)
            statuses = store.node_statuses(run_id)
            with _completed_lock:
                attempted = set(execution_state['attempted_nodes'])
            broken = sum(
                1
                for nid, state in statuses.items()
                if nid in attempted and state.get('status') in (NODE_FAILED, NODE_PARTIAL)
            )
            with _completed_lock:
                execution_state['failed_nodes'] = broken
                execution_state['outcome'] = (
                    'interrupted' if not still_running else ('failed' if broken else 'completed')
                )
            finish_line = t(
                'run.finished',
                done=execution_state['completed_nodes'],
                total=execution_state['total_nodes'],
            )
            # Starved and lost nodes are named in the same sentence instead of
            # quietly subtracting from a ratio the reader cannot interpret.
            if execution_state['skipped_nodes']:
                finish_line += t('run.finished.skipped', n=execution_state['skipped_nodes'])
            if broken:
                finish_line += t('run.finished.failed', n=broken)
            add_log(finish_line)
            if still_running:
                # One history entry per connected component, each under its
                # OWN name-node label — a multi-workflow canvas must land in
                # the history panel as separate named workflows, not all
                # under whichever name node happens to come first.
                for index, se in enumerate(sub_engines):
                    snapshot = _results_snapshot()
                    sub_results = {nid: res for nid, res in snapshot.items() if nid in se.nodes}
                    _record_execution_history(
                        None,
                        se,
                        sub_results,
                        _component_name(se) or workflow_name,
                        log_label=_wf_display_name(se, index),
                    )
            # 'completed' must mean every node really finished. A node that failed
            # or stopped half-way leaves gaps; marking the run complete hid it from
            # the resume banner forever and the 未处理 rows were never filled — the
            # opposite of what checkpoints are for. One broken node downgrades the
            # whole run to 'failed'.
            outcome = RUN_FAILED if broken else RUN_COMPLETED
            if not still_running:
                outcome = RUN_INTERRUPTED

        except Exception:
            # See the parallel branch above: the logger line already reaches the
            # console, so a second add_log was the same sentence twice.
            logger.exception(t('wf.exec_exception'))
            outcome = RUN_INTERRUPTED if not execution_state['running'] else RUN_FAILED
            with _completed_lock:
                execution_state['outcome'] = 'interrupted' if outcome == RUN_INTERRUPTED else 'failed'
        finally:
            execution_state['running'] = False
            # Whatever is left claiming to be running was killed, not finished;
            # the rows it published are what the next attempt resumes from. With
            # no context the store never opened at all, so there is no run row to
            # close — the console line is then the only record that this happened.
            if ctx is None:
                add_log(t('run.store_unavailable'))
                with _completed_lock:
                    execution_state['outcome'] = 'failed'
            else:
                _close_run(ctx, outcome)
            with _completed_lock:
                # Every exit must leave a verdict: the browser stops guessing from
                # `completed < total` and reads this instead, and an empty string
                # would leave the last run's answer standing on screen.
                if not execution_state['outcome']:
                    execution_state['outcome'] = 'interrupted' if outcome == RUN_INTERRUPTED else 'failed'
            # Retention is only real if something applies it. A finished run is
            # the natural moment: the databases are open, no writer is active and
            # the user just proved the machine is in use.
            _housekeep(exclude_run_id=run_id)
            # The tee exists to catch the analyzers' print() output *during* a
            # run; leaving it installed meant every later print — from any
            # request — also showed up in the console panel.
            if isinstance(sys.stdout, _LogTee):
                sys.stdout = sys.stdout._original
            # Release the handle this thread was recognised by, then let the
            # queue have the slot. Both before anything else in this finally can
            # be reordered: _start_next_queued checks liveness through it.
            execution_state['thread'] = None
            _start_next_queued()

    execution_state['thread'] = threading.Thread(target=run, daemon=True)
    execution_state['thread'].start()

    return {'status': 200, 'body': {'ok': True, 'message': 'Workflow started', 'run_id': run_id}}


# ─── Node execution helpers ────────────────────────────────────


def _source_stream(ctx: dict, nid: str, scope: str, label: str = ''):
    """Row sink + cursor sink for one source node.

    Every scraped item goes straight into the database as it is scraped, so a
    kill at item 900 of 1000 still owns those 900 rows; the position goes with
    it so the next attempt can continue instead of starting over.

    *label* is the node's user-facing name, handed down to the store's row-cap
    warning: whoever reads the console named that box, and ``node-7`` is not
    what they called it.

    This sink is deliberately **one write per row**. Buffering N rows per
    transaction would be the obvious optimisation and would cost the feature its
    purpose: with WAL + ``synchronous=NORMAL`` a commit is tens of microseconds,
    while a Selenium page costs seconds, so batching buys nothing measurable and
    throws away up to a batch of rows whenever the run is killed.
    """
    store = ctx['store']
    run_id = ctx['run_id']
    # Per-node tally of items the incremental ledger refused ("already
    # collected under this node fingerprint") — surfaced in the console and in
    # /api/workflow/status so an all-seen re-run is loud, not silent.
    tally = ctx.setdefault('skipped_seen', {})

    def row_sink(item):
        # A sink answers "was this new?" — the crawler drops duplicates itself,
        # which is how a resumed crawl re-reading the same page stays honest.
        kept, _dropped = store.append_rows(run_id, nid, [item], dedupe_scope=scope, label=label)
        if not kept:
            tally[nid] = tally.get(nid, 0) + 1
        return bool(kept)

    def cursor_sink(position):
        store.save_cursor(run_id, nid, position)

    return row_sink, cursor_sink


def _execute_source_node(node: dict, headless: bool, ctx: dict = None):
    """Scrape a platform, one row at a time.

    With a run context the crawler streams into the database instead of
    building a list in memory: rows survive whatever kills the run, and the
    items an earlier attempt already collected are given back to it so it can
    stop scraping early rather than refilling them (and so the duplicates are
    dropped rather than handed downstream twice).
    """
    params = node.get('params', {})
    platform = node.get('platform', params.get('platform', ''))
    if not is_crawlable(platform):
        # Cookie capture and crawling are different capabilities: bilibili and
        # douyin were added to the Cookie panel first, so a saved session exists
        # for a platform nothing can crawl. Refusing here by name beats the
        # alternative — an empty table that looks like an empty search.
        raise ValueError(t('run.notCrawlable', label=node_label(node, str(node.get('id') or '')), platform=platform))
    mode = capabilities.mode_of_node(node)
    # The mode is the whole decision that used to be a chain of platform tests:
    # 评论采集 routes to the shared comment engine, every other mode calls the
    # crawler method the matrix names with the arguments the matrix declares.
    # An unknown mode key reads as the platform's first mode (what the panel
    # shows), so a stale canvas cannot ask for a crawl nothing describes.
    if mode is None:
        raise ValueError(
            t('engine.source_unknown_platform', nid=node_label(node, str(node.get('id') or '')), platform=platform)
        )
    if mode.handler == 'comments':
        # Same engine as the standalone Comment node — which stays valid for the
        # canvases that used to own it.
        return _execute_comment_node(dict(node, type='comment'), headless=headless, ctx=ctx)
    crawl_args = capabilities.crawl_kwargs(mode, params)
    # A mode without a row budget (WeChat's article list) promised no number, so
    # nothing can be missing from it: the cookie-wall check below reads zero as
    # "this crawl ended where it was meant to" instead of inventing a target.
    target_count = crawl_args.get('target_count') or 0

    if headless and getattr(crawler_class(platform), 'never_headless', False):
        # Douyin answers a headless browser with 验证码中间页 on every
        # navigation — measured, not assumed — so the run would end as a
        # mysterious zero-row crawl. The platform declares the requirement on
        # its class and the executor pays for the visible window instead.
        headless = False
        add_log(t('run.forcedVisible', label=node_label(node, str(node.get('id') or '')), platform=platform))

    crawler = get_crawler(
        platform,
        headless=headless,
        cookie_dir=Config.COOKIE_DIR,
        use_profile=(ctx or {}).get('use_profile'),
    )
    # Registered and guarded from here on: everything between buying a browser
    # and using it can still fail — a read-only or missing export directory, a
    # locked runs.db, a cursor that will not parse — and a Chrome that Stop does
    # not know about is a process left on the user's machine forever.
    execution_state['active_crawlers'].add(crawler)
    resume = {}
    nid = str(node.get('id') or '')

    def _merge_parts(partial_rows) -> None:
        """Close the 分批输出 writer and announce the merged file — exactly once.

        Named here rather than inlined below because the crawl can also END BY
        RAISING, and a crawl that refuses to carry on when it hits the wall owed the
        user the same two facts a crawl that returns under-target gives: the file its
        parts merged into, and the cookie diagnosis. Neither line existed for
        zhihu — the platform most likely to bounce us — because both sat after the
        call that raised.
        """
        if writer is None:
            return
        if ctx is None and partial_rows:
            # One-shot path without a run context: nothing flowed through the
            # tee'd sink, so hand the rows to the writer directly.
            writer.add(partial_rows)
        info = writer.finish()
        add_log(
            t(
                'run.progress_file',
                file=os.path.basename(str(info['path'])),
                rows=info['rows'],
                parts=info['parts'],
            )
        )

    try:
        # ── progressive part files (分批输出) ──
        # With part_size>0 every kept row also lands in a numbered part file while
        # the crawl is still running, and the parts merge into one file at the end
        # — the results are openable before the node finishes.
        part_size = _safe_int(params.get('part_size'), 0, minimum=0)
        keep_parts = bool(params.get('keep_parts', False))
        pfmt = 'json' if str(params.get('format') or 'csv') == 'json' else 'csv'
        writer = None
        if part_size > 0:
            from services.part_writer import PartWriter, safe_stem

            stem = safe_stem(f'{execution_state.get("workflow_name") or platform}-src-{nid}')
            writer = PartWriter(Config.EXPORT_DIR, stem, pfmt, part_size, keep_parts)
        if ctx is not None:
            scope = _item_scope(ctx, node)
            if params.get('recrawl') and not ctx.get('resume'):
                # 重新采集 (node setting): release this node's 'already collected'
                # ledger so the same items are collected again — the incremental
                # default would skip every one of them. Never on a resumed run:
                # there the ledger is precisely its dedupe machinery.
                add_log(t('run.recrawl', n=ctx['store'].forget_items(scope)))
            row_sink, cursor_sink = _source_stream(ctx, nid, scope, node_label(node, nid))
            if writer is not None:
                base_sink = row_sink

                def tee_sink(item, _base=base_sink, _w=writer):
                    kept = _base(item)
                    if kept:
                        _w.add([item])
                    return kept

                row_sink = tee_sink

            crawler.set_sink(row_sink)
            crawler.set_cursor_sink(cursor_sink)
            if ctx.get('resume'):
                resume = ctx['store'].get_cursor(ctx['run_id'], nid) or {}
            # Rows saved by an earlier attempt, handed back so `collected()` starts
            # honest: targeting 200 with 180 already saved asks the page for 20.
            saved = ctx['store'].load_rows(ctx['run_id'], nid)
            if saved:
                crawler.seed(saved)
                add_log(t('run.resume_crawl', nid=node_label(node, nid), have=len(saved)))
                if writer is not None and not writer.has_parts:
                    # Rows paid for before batching was switched on (or before any
                    # part survived): the merged file should hold the whole table,
                    # not only what comes after the switch.
                    writer.add(saved)
        # The matrix decided what this crawl is called with; `resume` is the one
        # argument that is not the user's — it is where this run stopped, handed
        # over from the store.
        rows = getattr(crawler, mode.handler)(**crawl_args, resume=resume)
    except BaseException:
        # The crawler gave up (a wall it refuses to walk into, a risk page, a dead
        # session). Publish what that answer means BEFORE the failure travels on:
        # the toast flag, and the merged partial file the row sink already filled.
        # Suppress the bookkeeping's own errors — they must not replace the real one.
        if getattr(crawler, 'login_wall', False):
            execution_state['cookie_expired'] = True
        with contextlib.suppress(Exception):
            _merge_parts(None)
        raise
    finally:
        _close_login_browser(crawler)  # bounded quit + PID-targeted reap, never a global taskkill
        execution_state['active_crawlers'].discard(crawler)
    if ctx is not None:
        skipped = (ctx.get('skipped_seen') or {}).get(nid)
        if skipped:
            # Incremental dedupe made visible: a re-run that already knows
            # every item would otherwise end as '0 results' with no reason.
            add_log(t('run.dedupe_skipped', n=skipped))
            if not rows:
                # …and when EVERY item was skipped, say what happens next —
                # downstream sees an empty table, which reads as a failure
                # unless the console named the two ways out.
                add_log(t('run.dedupe_all_skipped'))
    wall = bool(getattr(crawler, 'login_wall', False))
    _merge_parts(rows)
    if wall:
        if len(rows) < target_count:
            # A long crawl can outlive its cookie: the platform bounces the
            # browser to a login page mid-run. The rows collected before the
            # wall are safe in the store — surface the flag for the toast and
            # say so in the console.
            execution_state['cookie_expired'] = True
            # Under-target is not a finished crawl, so the node must not look
            # like one. Failing it keeps every stored row, marks the RUN failed
            # (the resume banner's trigger), and lets 继续 resume pick the crawl
            # up at the cursor the wall stopped on — refresh the cookie, click
            # continue, get the rest. Marking it done would hide the gap.
            #
            # The message is raised, not also logged here: the executor prints
            # every failure as '节点 X 执行失败：…', which names the node. Both
            # calls made the same sentence appear twice, once without the node.
            raise ValueError(t('run.cookieExpired', platform=platform))
        # Wall met exactly as the target was reached: the session died at the
        # finish line, so there is nothing missing — do not raise a false alarm.
        add_log(t('run.cookieExpiredOk', platform=platform))
    return rows


def _execute_upload_node(node: dict, headless: bool = True):
    """Upload node — the one place a file can enter a workflow.

    It publishes a stored file (``data/datasets.db``) as ordinary rows, so
    every downstream node sees it exactly as it sees a crawl. That is why the
    visualize and tokenize nodes no longer carry their own upload UI: any node
    that needs data connects upstream, and the upstream may be a crawler or a
    file.

    The file is looked up by its id, and failing that by its *name* plus row
    count: re-uploading after a row was lost hands back something usable
    instead of forcing a second edit of the workflow.
    """
    params = node.get('params', {})
    dataset_id = str(params.get('dataset_id') or '')
    if not dataset_id:
        raise ValueError(t('upload.no_file'))

    df = _load_dataset(dataset_id)
    if df is None:
        replacement = get_dataset_store().find_replacement(
            str(params.get('dataset_name') or ''),
            _optional_int(params.get('row_count')),
        )
        if replacement:
            df = _load_dataset(replacement)
            if df is not None:
                dataset_id = replacement
                add_log(t('ds.rebound', name=params.get('dataset_name') or replacement, did=replacement))
    if df is None:
        # Nothing to publish, and pretending otherwise would hand downstream an
        # empty table that looks like a successful run.
        raise ValueError(t('upload.stale'))

    stored = get_dataset_store().meta(dataset_id) or {}
    # The name in storage is authoritative: it is the one every saved workflow
    # knows the file by, and writing it back keeps this node's params usable as
    # a re-binding hint later.
    meta = {
        'dataset_id': dataset_id,
        'name': stored.get('name') or str(params.get('dataset_name') or '') or dataset_id,
        'row_count': len(df),
    }
    _apply_dataset_meta(params, meta)
    add_log(t('upload.loaded', name=params.get('dataset_name') or dataset_id, n=len(df)))
    return _json_safe_records(df)


def _execute_process_node(node: dict, current_input: list, run_ctx: dict = None):
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    # Default matches the frontend canvas default and every crawler's output
    # column; the old 'content' silently mismatched real crawl data.
    text_column = params.get('text_column', '正文')
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    if op == 'clean':
        topic = params.get('topic', '')
        cleaner = ContentCleaner()
        df = cleaner.clean_dataframe(df, text_column=text_column, topic=topic, ctx=run_ctx)
        return df.to_dict('records')

    mode = params.get('mode', 'llm')
    if op == 'emotion':
        analyzer = EmotionAnalyzer(mode=mode)
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'tendency':
        analyzer = TendencyAnalyzer(mode=mode)
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'keyword':
        method = params.get('method', 'tfidf')
        topk = _safe_int(params.get('topk'), 10, minimum=1)
        merge = params.get('merge', 'true') == 'true'
        extractor = KeywordExtractor()
        df = extractor.analyze_dataframe(df, text_column=text_column, method=method, topk=topk, merge=merge)
        return df.to_dict('records')

    if op == 'cluster':
        method = params.get('cluster_method', 'kmeans')
        n_clusters = _safe_int(params.get('n_clusters'), 3, minimum=1)
        eps = _safe_float(params.get('eps'), 0.5)
        min_samples = _safe_int(params.get('min_samples'), 2, minimum=1)
        clusterer = TextCluster()
        df = clusterer.analyze_dataframe(
            df,
            text_column=text_column,
            method=method,
            n_clusters=n_clusters,
            eps=eps,
            min_samples=min_samples,
        )
        return df.to_dict('records')

    if op == 'ner':
        # Its own mode default: the rules need no model, and a workflow saved
        # before the mode selector existed must not start paying for one.
        recognizer = NamedEntityRecognizer(mode=params.get('mode', 'regex'))
        df = recognizer.analyze_dataframe(
            df,
            text_column=text_column,
            entity_types=params.get('entity_types'),
            ctx=run_ctx,
        )
        return df.to_dict('records')

    if op == 'anomaly':
        # _split_columns, not raw .split(','): a list like "a, b" used to keep
        # the leading space and match no column at all, silently.
        columns = _split_columns(params.get('columns')) or None
        contamination = min(max(_safe_float(params.get('contamination'), 0.1), 0.001), 0.5)
        detector = AnomalyDetector()
        df = detector.analyze_dataframe(df, columns=columns, contamination=contamination)
        return df.to_dict('records')

    if op == 'correlation':
        columns = _split_columns(params.get('columns')) or None
        corr_method = params.get('corr_method', 'pearson')
        min_abs = _safe_float(params.get('min_abs'), 0.0)
        analyzer_corr = CorrelationAnalyzer()
        df = analyzer_corr.analyze_dataframe(df, columns=columns, method=corr_method, min_abs=min_abs)
        return df.to_dict('records')

    # An unknown operation is a broken node, not an empty table. Returning [] here
    # settled it DONE: the run went green, every downstream node complained 「上游没有
    # 数据」 about itself, and the single sentence explaining why carried no node name
    # at all — so the user was sent to diagnose the healthy boxes. Raising hands the
    # reason to the executor, which fails THIS node and prints it with its label.
    raise ValueError(t('wf.unknown_process_op', op=op or '(empty)'))


def _execute_output_node(node: dict, current_input: list):
    """Save node: exports the upstream data in the format the user picked,
    then passes the data through for downstream nodes.

    'save_csv' is kept as a back-compat alias for older saved workflows;
    both routes go through the same DataExporter used by the standalone
    /api/export/save endpoint, so behaviour is identical whether the save
    happens inside a workflow or on its own.
    """
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    if op in ('save', 'save_csv'):
        fmt = params.get('format', 'csv' if op == 'save_csv' else None)
        filename = params.get('filename', 'export.csv')
        fmt = fmt or DataExporter.infer_format(filename)
        # Sanitize first, then (re)apply the extension: the other way round a
        # name like ".." lost its extension and landed as a hidden file.
        filename = DataExporter.normalize_filename(sanitize_filename(filename), fmt)
        filepath = os.path.join(Config.EXPORT_DIR, filename)
        try:
            DataExporter.save(df, filepath, fmt=fmt, text_column=params.get('text_column'))
        except UnsupportedFormatError as e:
            # Refused, and the reason travels: the executor prints it as this node's
            # failure with the node's own label. A second add_log here said the same
            # sentence again, unattributed — the version the user could not act on.
            return {'error': str(e)}
        # No "data saved to <path>" line: the exporter has already announced
        # "exported N rows to <path> (fmt)" one line above, and saying the same
        # fact twice in two wordings is two chances to word them differently.

    return current_input


def _safe_int(value, default: int = 0, minimum: int = None, maximum: int = None) -> int:
    """int() for numbers typed into the UI.

    Every settings field arrives as a string, so "abc" used to raise a bare
    ValueError from inside a request handler (HTTP 500) or from a node (opaque
    node failure). A malformed value now falls back to the default.

    ``inf`` / ``nan`` are the same class of mistake and used to escape it:
    ``float('inf')`` parses fine and only ``int()`` then refuses it with an
    OverflowError, which no ``except (TypeError, ValueError)`` catches — so
    ``/api/history/runs?limit=inf`` answered 500. Anything not finite is
    rejected up front, exactly like unparseable text.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    result = int(number)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _safe_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    # inf/nan poison every pandas call downstream instead of failing here, so
    # they are not usable numbers any more than "abc" is.
    return number if math.isfinite(number) else default


def _optional_int(value):
    """Like :func:`_safe_int`, but blank or unparseable means "not configured" (None)."""
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number)


def _optional_float(value):
    raw = str(value or '').strip()
    if not raw:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    # ``frac=inf`` reached df.sample as a ValueError, ``frac=nan`` as a silent
    # no-op; both mean "no fraction configured" here.
    return number if math.isfinite(number) else None


def _split_columns(value) -> list:
    if isinstance(value, list):
        return [str(c).strip() for c in value if str(c).strip()]
    return [c.strip() for c in str(value or '').split(',') if c.strip()]


def _normalize_analysis_params(op: str, params: dict) -> dict:
    """The Settings panel stores everything as flat strings (e.g. a
    comma-separated 'columns' field). Translate that into the exact kwargs
    each DataAnalysisService method expects."""
    if op in ('drop_null', 'strip_whitespace', 'select_columns'):
        result = {'columns': _split_columns(params.get('columns'))}
        if op == 'drop_null':
            # ``how`` decides whether one empty cell drops a row or all of them
            # do; the panel had no field for it and the normalizer dropped it, so
            # every "any column is null" choice silently became "all columns".
            result['how'] = params.get('how') or 'any'
        return result
    if op == 'fill_null':
        result = {'columns': _split_columns(params.get('columns')), 'value': params.get('value')}
        method = str(params.get('method') or '').strip()
        if method:
            # Forward/backward fill and a literal value are different operations;
            # an empty method means "use value", which the service already does.
            result['method'] = method
        return result
    if op == 'drop_duplicates':
        return {'columns': _split_columns(params.get('columns')) or None}
    if op == 'filter_rows':
        return {'column': params.get('column', ''), 'op': params.get('op', 'eq'), 'value': params.get('value')}
    if op == 'rename_columns':
        mapping = {}
        if params.get('rename_from'):
            mapping[params['rename_from']] = params.get('rename_to', '')
        return {'mapping': mapping}
    if op == 'convert_type':
        return {'column': params.get('column', ''), 'dtype': params.get('dtype', 'str')}
    if op == 'sort_rows':
        return {'column': params.get('column', ''), 'ascending': params.get('ascending', 'true') == 'true'}
    if op == 'sample_rows':
        result = {'n': _optional_int(params.get('n')), 'frac': _optional_float(params.get('frac'))}
        seed = _optional_int(params.get('seed'))
        if seed is not None:
            result['seed'] = seed
        return result
    if op == 'groupby_agg':
        return {
            'group_col': params.get('group_col', ''),
            'agg_col': params.get('agg_col', ''),
            'agg_func': params.get('agg_func', 'sum'),
        }
    if op == 'join_tables':
        return {
            'how': params.get('join_how', 'left'),
            'left_on': params.get('left_on', ''),
            'right_on': params.get('right_on', ''),
        }
    if op == 'column_calc':
        return {
            'new_col': params.get('new_col', ''),
            'expr': params.get('expr', ''),
        }
    if op == 'bin_column':
        result = {
            'column': params.get('column', ''),
            'new_col': params.get('bin_new_col', ''),
        }
        # ``bins`` is overloaded the way pandas overloads it: a single integer
        # means "this many equal-width buckets" and a comma-separated list means
        # "these exact edges". Both are useful and only one parser can tell them
        # apart, so the distinction lives here rather than in the panel.
        edges = _split_columns(params.get('bins'))
        if len(edges) > 1:
            numbers = [_optional_float(edge) for edge in edges]
            result['bins'] = [number for number in numbers if number is not None]
        else:
            count = _optional_int(params.get('bins'))
            if count:
                result['bins'] = count
        labels = _split_columns(params.get('bin_labels'))
        if labels:
            result['labels'] = labels
        return result
    return {}


def _execute_analysis_node(node: dict, current_input: list, upstream: list = None):
    """Analysis node: runs a deterministic data-cleaning pipeline (null
    handling, de-duplication, filtering, renaming, ...) via
    DataAnalysisService. Supports either a single configured operation
    (as built by the Settings panel) or a full multi-step pipeline stored
    under params['steps'] for advanced use / API callers.

    A ``join_tables`` step merges with the table of the node's *second*
    incoming connection. The old design asked the user to paste an opaque
    12-character dataset id instead — an id produced by the Upload node and
    shown nowhere, so a join silently joined nothing.
    """
    params = node.get('params', {})
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    steps = params.get('steps')
    if not steps:
        op = node.get('operation', params.get('operation', ''))
        steps = [{'op': op, 'params': _normalize_analysis_params(op, params)}] if op else []

    # upstream[0] is the left table (already current_input); anything after it is
    # a candidate right table.
    right_tables = [res for _pid, res in (upstream or [])[1:] if isinstance(res, list) and res]

    for step in steps:
        if step.get('op') == 'join_tables':
            if not right_tables:
                raise UnknownOperationError(t('wf.join_no_right_table'))
            step['params']['other_df'] = pd.DataFrame(right_tables[0])

    # An unknown/c malformed step RAISES straight through: the executor turns it into
    # this node's failure and prints the reason with the node's label — one line,
    # attributed. Swallowing it into an empty list used to make a mistyped filter value
    # look like "the data was already clean": the run went green, the export wrote a
    # header row and nothing else, and downstream nodes reported "no upstream data" for
    # a table that was really refused. Same contract as `/api/analysis/clean`, which
    # answers these with a 400 and this exact message.
    cleaned, report = DataAnalysisService.run_pipeline(df, steps)

    for step in report:
        line = t('wf.analysis_step', op=step['op'], before=step['rows_before'], after=step['rows_after'])
        # A step that dropped nothing deserves saying so; printing "(-0)" looked
        # like a truncated number rather than an outcome.
        line += (
            t('wf.analysis_step_removed', removed=step['rows_removed'])
            if step['rows_removed']
            else t('wf.analysis_step_nochange')
        )
        add_log(line)
    return cleaned.to_dict('records')


def _execute_tokenize_node(node: dict, current_input: list):
    """Tokenize node: segments a free-text column with jieba and outputs
    word-frequency pairs for downstream save or word-cloud nodes.
    Data always comes from the upstream connection — a file reaches it by
    sitting behind an Upload node, not by being configured here."""
    params = node.get('params', {})
    column = params.get('text_column', '')
    output_mode = params.get('output_mode', 'word_freq')
    # Every refusal below RAISES rather than returning []. An empty list settles the
    # node DONE, so the run read green, the export held only a header, and the one
    # sentence that explained it carried no node name — the user had to guess which
    # box was broken. Raising hands the reason to the executor, which fails THIS node
    # and prints the label with it.
    if not column:
        raise ValueError(t('wf.tokenize_no_column'))
    if not current_input:
        raise ValueError(t('wf.tokenize_no_input'))
    df = pd.DataFrame(current_input)
    result_df = _tokenize_dataframe(df, params)
    if result_df is None:
        raise ValueError(t('wf.tokenize_no_col', col=column, cols=list(df.columns)))
    add_log(t('wf.tokenize_done', mode=output_mode, col=column, n=len(result_df)))
    return result_df.to_dict('records')


def _execute_visualize_node(node: dict, current_input: list):
    """Visualize node: builds a chart from the upstream data and returns a
    chart spec dict the frontend renders — either an ECharts option or a
    base64 image — so this node works identically to /api/visualize/render.

    It has no data source of its own on purpose: files enter a workflow
    through the Upload node, so a chart is always "whatever upstream
    produced", crawl or file alike.
    """
    params = node.get('params', {})
    chart_type = params.get('chart_type', 'bar')
    engine = params.get('engine', 'echarts')
    x_field = params.get('x_field')
    y_field = params.get('y_field')
    value_field = params.get('value_field')
    agg = params.get('agg', 'sum')
    title = params.get('title', '')
    tokenize = bool(params.get('tokenize'))
    wordcloud_style = params.get('wordcloud_style')

    if not current_input:
        add_log(t('wf.visualize_no_input'))
        return {'error': t('wf.visualize_no_input')}
    df = pd.DataFrame(current_input)

    try:
        if engine == 'matplotlib':
            image = VisualizationService.render_image(
                df, chart_type, x=x_field, y=y_field, value_field=value_field, agg=agg, title=title
            )
            spec = {'engine': 'matplotlib', 'image': image}
        else:
            kw = {'tokenize': tokenize}
            if wordcloud_style:
                kw['wordcloud_style'] = wordcloud_style
            option = VisualizationService.to_echarts_option(
                df,
                chart_type,
                x=x_field,
                y=y_field,
                value_field=value_field,
                agg=agg,
                title=title,
                **kw,
            )
            spec = {'engine': 'echarts', 'option': option}
    except ChartConfigError as e:
        # The reason travels as the node's own error; the executor prints it once,
        # with the node's label. Printing it here too gave two lines for one
        # failure, the first of them undiagnosable because it named no node.
        return {'error': str(e)}

    add_log(t('wf.visualize_done', chart=chart_type, engine=engine, n=len(df)))
    return spec


def _execute_comment_node(node: dict, headless: bool = True, ctx: dict = None):
    """Comment crawler: article links in, comment rows out, batch by batch.

    Built on the same durable legs as the source crawler — the row ledger
    (already-collected comments are skipped, never re-fetched), the row store
    (resume restores position), and PartWriter (every settled batch hits disk
    as a readable file while the run is still going; a resumed writer adopts
    the parts the crashed run left behind, so kept-elsewhere rows are exactly
    the rows already in those files). zhihu content pages reject headless
    sessions, so this node always drives a visible browser — and says so when
    the run was started in 无头 mode, because a window appearing mid-run with no
    explanation reads as the setting having been ignored.
    """
    from crawlers.comments import BLOCKED, DEAD, OK, CommentSession
    from services.part_writer import PartWriter, safe_stem

    params = node.get('params') or {}
    # A Data Source in comments mode carries the platform the user selected;
    # links from another site must not silently crawl a platform nobody chose.
    # The standalone Comment node has no platform param, so it stays mixed-input.
    want = str(params.get('platform') or '').strip().lower()
    all_urls = split_urls(params.get('urls'))
    urls, dropped, mismatched = [], [], []
    for u in all_urls:
        plat = platform_for(u)
        if not plat:
            dropped.append(u)
        elif want and plat != want:
            mismatched.append(u)
        else:
            urls.append(u)
    if dropped:
        add_log(t('comment.unsupported', n=len(dropped), platforms=_COMMENT_PLATFORMS))
    if mismatched:
        add_log(t('comment.platformMismatch', n=len(mismatched), platform=want))
    if not urls:
        if mismatched:
            raise ValueError(t('comment.allMismatched', platform=want))
        raise ValueError(t('comment.no_urls', platforms=_COMMENT_PLATFORMS))

    limit = _safe_int(params.get('comment_limit'), 0, minimum=0)  # 0 = every comment
    part_size = _safe_int(params.get('part_size'), 0, minimum=0)  # 0 = single final file only
    per_article = bool(params.get('per_article_file'))
    keep_parts = bool(params.get('keep_parts', True))
    fmt = 'json' if str(params.get('format') or 'csv') == 'json' else 'csv'
    nid = str(node.get('id') or '')
    stem_base = safe_stem(f'{execution_state.get("workflow_name") or "comments"}-{nid}')

    row_sink = cursor_sink = None
    resumed_index = 0
    if ctx is not None:
        row_sink, cursor_sink = _source_stream(ctx, nid, _item_scope(ctx, node), node_label(node, nid))
        if ctx.get('resume'):
            from crawlers.base import as_index

            resumed_index = as_index((ctx['store'].get_cursor(ctx['run_id'], nid) or {}).get('url_index'))

    writers = {}
    rows_out = []
    if ctx is not None and ctx.get('resume'):
        # A re-run of this node pays for the missing articles only — but the
        # table it hands downstream must be the WHOLE comment set, so the rows
        # an earlier attempt stored come back into the result list up front.
        # (The ledger refuses them as duplicates, so nothing double-stores.)
        rows_out = list(ctx['store'].load_rows(ctx['run_id'], nid))
    counts = {OK: 0, BLOCKED: 0, DEAD: 0}
    # Which platforms actually answered with a login page, in the order they did.
    blocked_by: list[str] = []
    sessions = {}
    if headless:
        # This node never crawls headless, whatever the run asked for.
        add_log(t('run.forcedVisibleComment', label=node_label(node, nid)))

    def _writer_for(idx: int, url: str) -> PartWriter:
        stem = f'{stem_base}-{idx:02d}' if per_article else stem_base
        if stem not in writers:
            writers[stem] = PartWriter(Config.EXPORT_DIR, stem, fmt, part_size, keep_parts)
        return writers[stem]

    try:
        for idx, url in enumerate(urls, 1):
            if not execution_state['running']:
                break
            if idx <= resumed_index:
                continue
            kind = platform_for(url)
            if kind not in sessions:
                crawler = get_crawler(
                    kind, headless=False, cookie_dir=Config.COOKIE_DIR, use_profile=(ctx or {}).get('use_profile')
                )
                sessions[kind] = (
                    crawler,
                    # The comment engine reports per-URL facts; prefix them so a
                    # line in the shared console says which node it came from.
                    CommentSession(crawler.driver, log=lambda m: add_log(f'{t("comment.prefix")} {m}')),
                )
            _crawler, session = sessions[kind]
            if cursor_sink is not None:
                cursor_sink({'url_index': idx - 1, 'url_total': len(urls)})
            # The adapter is named after the platform the router picked, so adding
            # a platform to ``utils.helpers._COMMENT_DOMAINS`` without writing its
            # ``crawl_<platform>`` is a refusal here rather than the old silent
            # fallback — which handed every unlisted link to the Zhihu reader and
            # reported whatever that came back with as the site's comments.
            adapter = getattr(session, f'crawl_{kind}', None)
            if adapter is None:
                raise ValueError(t('comment.noAdapter', platform=kind, url=url))
            rows, status = adapter(url, limit)
            counts[status] = counts.get(status, 0) + 1
            if status == BLOCKED:
                # Named by what actually walled. The message used to fall back to a
                # hand-written list of four platforms, so a YouTube or X comment run
                # bounced by its own site was reported as 知乎/微博/小红书/哔哩哔哩
                # 的登录态失效 — naming four platforms the user never crawled and
                # leaving the one they did unnamed.
                blocked_by.append(kind)
            writer = _writer_for(idx, url)
            fresh = []
            for row in rows:
                if row_sink is not None:
                    if row_sink(row):  # ledger said new: store it AND publish it
                        fresh.append(row)
                else:
                    fresh.append(row)
            writer.add(fresh)
            rows_out.extend(fresh)
            add_log(t('comment.article', url=url, n=len(fresh), status=t(f'comment.status.{status}')))
    finally:
        for crawler, _session in sessions.values():
            _close_login_browser(crawler)

    files = [writer.finish() for writer in writers.values()]
    blocked_seen = bool(counts.get(BLOCKED))
    if blocked_seen:
        # Same story as the source crawler: a blocked article means the saved
        # cookie likely died — the collected comments are already merged to
        # disk and stored; refresh the cookie and resume for the rest. The
        # line above (comment.done) already reported how many were blocked, so
        # this only raises: the executor prints it once, with the node's name.
        execution_state['cookie_expired'] = True
    add_log(
        t(
            'comment.done',
            urls=len(urls),
            ok=counts.get(OK, 0),
            blocked=counts.get(BLOCKED, 0),
            dead=counts.get(DEAD, 0),
            rows=len(rows_out),
            files=len(files),
        )
    )
    if blocked_seen:
        # Failed (not done) → the run lands in the resume banner and 继续
        # retries exactly the articles the wall refused.
        named = '/'.join(dict.fromkeys(blocked_by))
        raise ValueError(t('run.cookieExpired', platform=named or want or t('run.cookieAnyPlatform')))
    return rows_out


def _execute_resume_node(node: dict, ctx: dict):
    """Adopt a stored node output from an earlier run as this node's rows.

    This is the node you drop in when the original source is no longer
    co-operating — logged out, blocked, expensive — but its rows are already
    paid for and sitting in runs.db. It replaces nothing upstream: whatever it
    produces flows onward exactly as the original node's output would have.
    """
    store = ctx['store']
    params = node.get('params') or {}
    run_id = str(params.get('resume_run_id') or '').strip()
    node_id = str(params.get('resume_node_id') or '').strip()
    limit = _safe_int(params.get('resume_limit'), 0, minimum=0)

    if not run_id:
        # Nothing picked yet: fall back to the newest unfinished run of THIS
        # workflow's shape. Without the fingerprint filter a 'node-2' from an
        # unrelated workflow — the id repeats in every canvas — would be
        # adopted wholesale; and the run currently writing must not feed itself.
        candidates = [
            r
            for r in store.list_resumable(str(ctx.get('wf_fp') or '') or None, limit=5)
            if r.get('run_id') != ctx.get('run_id') and r.get('status') != RUN_RUNNING
        ]
        if not candidates:
            add_log(t('resume.no_run'))
            return []
        run_id = str(candidates[0].get('run_id') or '')

    def _adopted_label(nid: str) -> str:
        """The node being adopted, named the way the console names everything.

        ``node_label`` cannot help here: that node lives in another run's record, not
        on this canvas. But a bare ``node-2`` is just as unreadable, and the row it is
        about to hand over carries the title its own run stored — so the same
        「标题 #id」 form is available, and a run of a dozen nodes can be told apart.
        """
        if not nid:
            return t('resume.unpicked')
        state = store.node_statuses(run_id).get(nid) or {}
        title = str(state.get('title') or '').strip()
        return f'{title} #{nid}' if title and title != nid else nid

    rows = store.load_rows(run_id, node_id) if node_id else []
    if not rows:
        # No node picked (or the pick holds nothing): take the fullest one.
        statuses = store.node_statuses(run_id)
        best = max(statuses.values(), key=lambda n: int(n.get('row_count') or 0), default=None)
        if best and int(best.get('row_count') or 0) > 0:
            node_id = str(best.get('node_id') or '')
            rows = store.load_rows(run_id, node_id)
    if not rows:
        add_log(t('resume.empty', rid=run_id, nid=_adopted_label(node_id)))
        return []
    if limit and len(rows) > limit:
        rows = rows[:limit]
    add_log(t('resume.loaded', rid=run_id, nid=_adopted_label(node_id), n=len(rows)))
    return rows


# Node types that never read the rows their inputs carry. Their data comes
# from somewhere else — the platform crawler, the already-uploaded file, the
# run store, or (for `name`) nowhere at all. The "upstream came up empty →
# skip" rule below must not apply to them, or a whole chain hanging off a
# name node gets silently skipped: the name node produces no rows by design.
_NON_INPUT_NODES = frozenset({'source', 'upload', 'resume', 'name', 'comment'})

#: Node types the console stays quiet about. A 工作流命名 node carries a label and
#: computes nothing; an 上传文件 node re-reads a file the user already pointed at.
#: Announcing "executing node …" and "node … done (2/4)" for those is two lines of
#: noise per node that has no work to report, and on a canvas of mostly-plumbing
#: nodes the lines that *do* matter — a crawl, a failure, a restored node — drowned
#: in them. Only the generic per-node chatter is suppressed: what these nodes say
#: about themselves (which file was loaded, how many rows) and anything that went
#: wrong still reaches the console.
_QUIET_NODE_TYPES = frozenset({'name', 'upload'})


def _run_node_durable(ctx: dict, node: dict, headless: bool, primary: list, upstream: list, wf_idx: int):
    """Run one node with the run store underneath it. Returns (result, status).

    Three things it adds over calling ``_execute_node`` directly:

    1. **Reuse.** A node that finished cleanly on the previous attempt and has
       not been edited since is not run again — its rows are read back. (Source
       nodes are the exception: they always run, because their job this time is
       to go and get *more*.)
    2. **Persistence.** Rows land in the database as they are produced, so the
       work already paid for survives whatever kills the run.
    3. **Loss containment.** A node that dies still owns what it produced, and
       that goes downstream rather than being thrown away with the exception.
    """
    store = ctx['store']
    run_id = ctx['run_id']
    nid = str(node.get('id') or '')
    ntype = str(node.get('type') or '')
    fingerprint = (ctx.get('fingerprints') or {}).get(nid, '')
    stored = (ctx.get('statuses') or {}).get(nid) or {}
    title = str(node.get('title') or node.get('name') or '')
    label = node_label(node, nid)

    reusable = (
        ctx.get('resume')
        # ``restored`` belongs here: a node that only *replayed* its stored rows in
        # the previous attempt is just as settled as one that computed them, and
        # leaving it out made the second 继续 re-execute the whole chain the first
        # 继续 had just restored — the promise of checkpointing lasted one click.
        and stored.get('status') in (NODE_DONE, NODE_RESTORED)
        and stored.get('fingerprint') == fingerprint
        # An EMPTY stored result is deliberately not trusted. Reuse is decided by
        # fingerprint, and a source's fingerprint does not change when it happens
        # to collect more rows, so adopting "0 rows" here would freeze a node whose
        # parent finally delivered: the run would report success over an empty
        # table. Recomputing a 0-row node is at worst one cheap pass; the row
        # ledger still prevents any double-append.
        and int(stored.get('row_count') or 0) > 0
        and ntype != 'source'
    )
    # Rows stored for an *edited* node describe something else, so begin_node
    # drops them and reports it: they are gone, and there is nothing to reuse.
    dropped_stale = store.begin_node(run_id, nid, ntype, title=title, fingerprint=fingerprint)
    if reusable and dropped_stale:
        reusable = False

    if reusable:
        rows = store.load_rows(run_id, nid)
        store.finish_node(run_id, nid, NODE_RESTORED)
        add_log(t('run.restored', nid=label, n=len(rows)), wf_idx=wf_idx)
        return rows, NODE_RESTORED

    if upstream and ntype not in _NON_INPUT_NODES and not any(isinstance(res, list) and res for _pid, res in upstream):
        # Everything this node would work on came up empty — usually because
        # its parent died with nothing. Skipping beats pretending we ran.
        # Types that ignore their inputs entirely are exempt: an empty
        # upstream says nothing about whether *they* can produce rows.
        store.finish_node(run_id, nid, NODE_SKIPPED)
        add_log(t('run.skipped_empty', nid=label), wf_idx=wf_idx)
        return [], NODE_SKIPPED

    try:
        # Announced HERE, after the reuse and empty-upstream decisions above: it
        # used to be printed by the caller before this function decided anything,
        # so a restored or skipped node read "Executing node …" and then, one line
        # later, "restored from the last attempt" / "skipped". '（source）' in a
        # Chinese console reads like a stack trace, so the type speaks in the
        # reader's own words.
        if ntype not in _QUIET_NODE_TYPES:
            ntype_label = t(f'node.{ntype}')
            if ntype_label.startswith('node.'):
                ntype_label = ntype
            add_log(
                t('wf.executing_node', wf=execution_state['_wf_names'].get(wf_idx) or '', nid=label, ntype=ntype_label),
                wf_idx=wf_idx,
            )
        result = _execute_node(node, headless, primary, upstream=upstream, ctx=ctx)
    except Exception as e:
        # What the node already produced: process nodes publish finished rows
        # after every batch, and crawlers stream every item into the store.
        published = execution_state['results'].get(nid)
        rows = published if isinstance(published, list) else []
        if rows and store.row_count(run_id, nid) == 0:
            store.append_rows(run_id, nid, rows, label=label)
        if not rows:
            rows = store.load_rows(run_id, nid)
        status = NODE_PARTIAL if rows else NODE_FAILED
        store.finish_node(run_id, nid, status, error=str(e))
        add_log(
            t(
                'wf.node_failed',
                wf=execution_state['_wf_names'].get(wf_idx) or t('wf.unnamed', i=wf_idx + 1),
                nid=label,
                err=e,
            ),
            wf_idx=wf_idx,
        )
        if rows:
            add_log(t('run.partial_down', nid=label, n=len(rows)), wf_idx=wf_idx)
        else:
            add_log(t('run.failed_down', nid=label), wf_idx=wf_idx)
        return rows, status

    if isinstance(result, dict) and result.get('error'):
        # The output and visualize nodes answer a refused export with
        # ``{'error': …}`` instead of raising, because their downstream must
        # still receive the table. Settling such a node DONE made the run read
        # "completed" while the file or chart the user asked for was never made;
        # FAILED keeps the data flowing and marks the truth.
        message = str(result['error'])
        store.finish_node(run_id, nid, NODE_FAILED, error=message)
        add_log(
            t(
                'wf.node_failed',
                wf=execution_state['_wf_names'].get(wf_idx) or t('wf.unnamed', i=wf_idx + 1),
                nid=label,
                err=message,
            ),
            wf_idx=wf_idx,
        )
        # FAILED keeps the truth in the run record while the node's own answer —
        # the reason, not a half-built spec — stays what the browser reads.
        return result, NODE_FAILED

    if isinstance(result, list) and ntype != 'source':
        # Source rows are already in the store — the sink put every item there
        # as it was scraped, and re-writing them here would only renumber.
        store.replace_rows(run_id, nid, result, label=label)
    if isinstance(result, list) and any(
        isinstance(r, dict) and any(v == ABORT_MARK for v in r.values()) for r in result
    ):
        # A cancelled LLM node returns what it managed to answer; recording it
        # DONE would let resume restore it and the 未处理 gaps would stay
        # forever. PARTIAL keeps the rows but marks the node for a re-run,
        # where the answer cache makes only the missing rows cost anything.
        store.finish_node(run_id, nid, NODE_PARTIAL)
        return result, NODE_PARTIAL
    store.finish_node(run_id, nid, NODE_DONE)
    return result, NODE_DONE


def _execute_name_node(node: dict) -> list:
    """The name node is metadata, not data: its label was already lifted into
    ``workflow_name`` before the run started (so the history panel can group by
    it). It produces no rows — downstream source/upload nodes read nothing
    from their inputs, which is exactly why the node must connect to one."""
    return []


def _execute_node(
    node: dict,
    headless: bool,
    current_input: list,
    run_ctx: dict = None,
    upstream: list = None,
    ctx: dict = None,
):
    """Run one node. ``upstream`` is [(parent_id, result), …] in connection
    order — only the analysis node needs more than the first entry (a join uses
    the second one as its right-hand table)."""
    ntype = node.get('type')
    if ntype == 'name':
        return _execute_name_node(node)
    if ntype == 'comment':
        return _execute_comment_node(node, headless=headless, ctx=ctx)
    if ntype == 'source':
        return _execute_source_node(node, headless, ctx=ctx)
    if ntype == 'upload':
        return _execute_upload_node(node)
    if ntype == 'resume':
        return _execute_resume_node(node, ctx or {'store': get_run_store(), 'run_id': ''})
    if ntype == 'process':
        op = node.get('operation') or node.get('params', {}).get('operation', '')
        return _execute_process_node(node, current_input, run_ctx=run_ctx or _llm_run_ctx(node, op, ctx))
    if ntype == 'analysis':
        return _execute_analysis_node(node, current_input, upstream=upstream)
    if ntype == 'visualize':
        return _execute_visualize_node(node, current_input)
    if ntype == 'tokenize':
        return _execute_tokenize_node(node, current_input)
    if ntype == 'output':
        return _execute_output_node(node, current_input)
    return []


def _close_active_crawlers():
    """Close the login/crawl browsers of live sessions, one at a time.

    Used to run `taskkill /F /IM chromedriver.exe` — which killed every
    chromedriver on the machine, taking down unrelated Selenium apps and test
    runs. Each registered crawler is now quit with a bounded grace, and only a
    driver that ignores it is force-killed — by PID, tree included, so the
    chrome children of *this* session die with it.
    """
    for crawler in list(execution_state['active_crawlers']):
        _close_login_browser(crawler, quit_timeout=3.0)


# ─── Stop / Status API ─────────────────────────────────────────


@app.route('/api/workflow/stop', methods=['POST'])
def stop_workflow():
    if execution_state['executor']:
        execution_state['executor'].stop()
    # Tell any row-by-row LLM loop to bail out at the next row boundary —
    # finished rows are already checkpointed and stay in results.
    execution_state['cancel_event'].set()
    execution_state['running'] = False
    crawlers = list(execution_state['active_crawlers'])
    execution_state['active_crawlers'].clear()
    for c in crawlers:
        with contextlib.suppress(OSError):
            c.close()
    # Clear the console but NOT the results: a stopped run keeps everything it
    # already produced (rows, tables, exports) so nothing paid for is lost.
    #
    # The console is not cleared either, and neither are the node counters.
    # Stopping is the moment someone most wants to read what the run did before
    # it was cut short, and the worker's own finally writes the summary line
    # under those counters — zeroing them here turned every stopped run into
    # "运行结束（0/0 个节点完成）" and wiped the log that explained it. The next
    # run resets both when it claims the slot (_begin_run), which is where a
    # fresh slate belongs.
    execution_state.pop('current_input', None)
    execution_state['executor'] = None
    _close_active_crawlers()
    return jsonify({'ok': True})


@app.route('/api/workflow/status', methods=['GET'])
def workflow_status():
    # Build per-workflow progress lists from _wf_logs keys
    wf_list = []
    mode = execution_state.get('_mode', 'serial')
    with _completed_lock:
        wf_keys = sorted(execution_state['_wf_logs'].keys())
    for wk in wf_keys:
        wf_logs = execution_state['_wf_logs'][wk]
        wf_list.append(
            {
                'id': wk,
                # The console tab bar speaks the workflow's name (set by the
                # 工作流命名 node), not a positional 'WF2' the user cannot map
                # back to a canvas.
                'name': execution_state['_wf_names'].get(wk) or f'#{wk + 1}',
                'logs': wf_logs[-200:],
                # How many lines exist in total, so the browser can compute the
                # delta even after the tail truncation above.
                'total': execution_state['_wf_log_total'].get(wk, len(wf_logs)),
            }
        )

    chart_results = {}
    # One snapshot for both loops below: the run publishes node rows as they
    # finish, and iterating the live dict alongside that raised
    # "dictionary changed size during iteration" (an HTML 500 in the middle of a
    # status poll).
    results = _results_snapshot()
    if not execution_state['running']:
        for nid, data in results.items():
            if isinstance(data, dict) and 'engine' in data:
                chart_results[nid] = data

    return jsonify(
        {
            'running': execution_state['running'],
            'logs': execution_state['logs'][-200:],
            'log_total': execution_state['_log_total'],
            'workflows': wf_list,
            'mode': mode,
            'results': list(results.keys()),
            'total_nodes': execution_state['total_nodes'],
            'completed_nodes': execution_state['completed_nodes'],
            # What the run decided about itself. The browser used to infer
            # "unfinished, offer a continue" from completed < total, which is
            # wrong for a run that skipped a starved node and right for nothing
            # else, and wrong for a definition that never started at all.
            'skipped_nodes': execution_state['skipped_nodes'],
            'failed_nodes': execution_state['failed_nodes'],
            'outcome': execution_state['outcome'],
            'chart_results': chart_results,
            'cookie_expired': bool(execution_state.get('cookie_expired')),
            # The console polls this while a run is live, so the waiting list is
            # shown from the same answer — no second request, no second clock.
            'queue': queue_snapshot(),
        }
    )


@app.route('/api/workflow/processes', methods=['GET'])
def workflow_processes():
    """Return info about active threads/processes for the monitoring panel."""
    threads = []
    for thread in threading.enumerate():
        threads.append(
            {
                'name': thread.name,
                'daemon': thread.daemon,
                'alive': thread.is_alive(),
                'ident': thread.ident,
            }
        )

    executor_alive = (
        execution_state['executor'] is not None and getattr(execution_state['executor'], '_pool', None) is not None
    )
    return jsonify(
        {
            'running': execution_state['running'],
            'threads': threads,
            'executor_pool_alive': executor_alive,
            'active_crawlers': len(execution_state['active_crawlers']),
        }
    )


@app.route('/api/workflow/processes/kill', methods=['POST'])
def kill_process():
    """Force-kill a thread by its ident. MainThread and 'run' thread are protected."""
    data = _json_body()
    if data is None:
        return _bad_body()
    ident = data.get('ident')
    if ident is None:
        return jsonify({'ok': False, 'error': 'Missing thread ident'}), 400

    target = None
    for thread in threading.enumerate():
        if thread.ident == ident:
            target = thread
            break

    if target is None:
        return jsonify({'ok': False, 'error': 'Thread not found'}), 404

    if target.name in ('MainThread', 'run'):
        return jsonify({'ok': False, 'error': f'Cannot kill protected thread: {target.name}'}), 403

    if not target.is_alive():
        return jsonify({'ok': False, 'error': 'Thread is not alive'}), 400

    try:
        ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), ctypes.py_object(SystemExit))
        if ret == 0:
            return jsonify({'ok': False, 'error': 'Invalid thread ID'}), 400
        if ret > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), None)
            return jsonify({'ok': False, 'error': 'Failed to kill thread'}), 500
        return jsonify({'ok': True, 'message': f'Thread "{target.name}" terminated'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ─── Data API (standalone upload / analysis / visualization) ───
#
# These endpoints let Analysis and Visualize work as fully independent
# tools — e.g. upload any CSV/JSON and chart it — without building a
# crawler workflow at all. The same DataAnalysisService/VisualizationService/
# DataExporter classes back both this API and the workflow nodes above, so
# behaviour is identical either way.


@app.route('/api/data/upload', methods=['POST'])
def upload_dataset():
    """Upload a CSV, JSON, TXT or Excel file and register it for analysis/visualization."""
    file = request.files.get('file')
    if not file:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='missing file')}), 400
    filename = file.filename or 'upload'
    name_lower = filename.lower()
    try:
        if name_lower.endswith('.json'):
            df = pd.DataFrame(json.load(file.stream))
        elif name_lower.endswith('.txt'):
            text = file.stream.read().decode('utf-8', errors='replace')
            df = pd.DataFrame({'content': [text]})
        elif name_lower.endswith(('.xlsx', '.xls', '.xlsm')):
            # Spreadsheets are the format a non-technical user's data actually
            # arrives in. Without this branch the file fell through to
            # ``read_csv`` and came back as one column of mojibake — a
            # "successful" import of nonsense.
            df = pd.read_excel(file.stream)
        elif name_lower.endswith(('.csv', '.tsv')):
            # ``sep=None`` would make pandas *sniff* the delimiter, which turns a
            # comma file with a stray tab inside a quoted cell into a different
            # table. Only .tsv asks for a tab; .csv keeps the comma contract the
            # exporter writes.
            df = pd.read_csv(file.stream, sep='\t' if name_lower.endswith('.tsv') else ',')
        else:
            # An extension nobody recognises is refused, not guessed at: reading
            # a Parquet or a PDF as CSV produces a table that is technically
            # valid and completely wrong.
            return jsonify({'ok': False, 'error': t('api.unsupportedUpload', name=filename)}), 400
    except (ValueError, OSError, UnicodeDecodeError, pd.errors.ParserError, ImportError) as e:
        # A corrupt or mis-encoded file is a user-input problem, not a crash.
        # ImportError belongs here too: reading .xlsx needs openpyxl, and a
        # missing engine is a fixable environment gap, not a 500.
        return jsonify({'ok': False, 'error': t('api.parseFailed', err=e)}), 400

    is_txt = name_lower.endswith('.txt')
    try:
        dataset_id = _register_dataset(df, name=filename, source=SOURCE_UPLOAD)
    except ValueError as e:
        # Over the row ceiling: refusing beats storing half a file.
        return jsonify({'ok': False, 'error': t('api.datasetTooBig', err=e)}), 400
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            # The Upload node labels itself with this name, so it must travel
            # back with the id — otherwise a successful upload still reads
            # "no file uploaded yet".
            'name': filename,
            'columns': list(df.columns),
            'row_count': len(df),
            'is_txt': is_txt,
            # False when identical rows were already stored: the UI can then
            # say "already saved" rather than pretending it wrote something new.
            'persisted': True,
            'preview': _json_safe_records(df, 10),
        }
    )


@app.route('/api/data/datasets', methods=['GET'])
def list_datasets():
    """Every stored file, newest first, with the workflows that read it.

    This is how a page that has only its own canvas asks "do my Upload nodes
    still have their files?" — one request, no guessing.
    """
    limit = _safe_int(request.args.get('limit'), 200, minimum=1, maximum=1000)
    datasets = get_dataset_store().list_datasets(limit=limit)
    return jsonify({'ok': True, 'datasets': datasets, 'stats': get_dataset_store().stats()})


@app.route('/api/data/datasets/<dataset_id>', methods=['GET'])
def dataset_detail(dataset_id: str):
    """Metadata (and a short preview) for one stored file."""
    meta = get_dataset_store().meta(dataset_id)
    if meta is None:
        return jsonify({'ok': False, 'error': t('api.datasetMissing', did=dataset_id)}), 404
    df = _load_dataset(dataset_id)
    meta['preview'] = _json_safe_records(df, 10) if df is not None else []
    return jsonify({'ok': True, 'dataset': meta})


@app.route('/api/data/datasets/<dataset_id>', methods=['DELETE'])
def dataset_delete(dataset_id: str):
    """Forget one file and every pointer to it.

    Refused while a saved workflow still reads it: the delete would succeed and
    the workflow would only discover the gap on its next open, as an Upload node
    with no rows and a run that quietly returns 0 results. The panel shows the
    referencing workflows for the same reason.
    """
    store = get_dataset_store()
    refs = store.referenced_by(dataset_id) if store.exists(dataset_id) else []
    force = str(request.args.get('force') or '') in ('1', 'true', 'yes')
    if refs and not force:
        return jsonify({'ok': False, 'error': t('api.datasetInUse', workflows=', '.join(refs)), 'workflows': refs}), 409
    removed = store.delete(dataset_id)
    _dataset_cache.pop(dataset_id, None)
    if not removed:
        return jsonify({'ok': False, 'error': t('api.datasetMissing', did=dataset_id)}), 404
    return jsonify({'ok': True, 'dataset_id': dataset_id})


@app.route('/api/data/datasets/<dataset_id>/rename', methods=['POST'])
def dataset_rename(dataset_id: str):
    """Relabel a stored file. The name is what the list and the Upload node show.

    A rename is not a re-hash: the id is content, so the dataset keeps its
    identity, every workflow pointer stays valid, and no rows are rewritten.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    raw = body.get('name')
    if not isinstance(raw, str):
        return _bad_param('name')
    store = get_dataset_store()
    renamed = store.rename(dataset_id, raw)
    if renamed is None:
        if not store.exists(dataset_id):
            return jsonify({'ok': False, 'error': t('api.datasetMissing', did=dataset_id)}), 404
        # An empty or fully-unusable label is refused rather than stored, because
        # a nameless row in the list is unclickable and unfindable.
        return jsonify({'ok': False, 'error': t('api.datasetNameInvalid', name=raw)}), 400
    return jsonify({'ok': True, 'dataset_id': dataset_id, 'name': renamed})


@app.route('/api/data/paste', methods=['POST'])
def paste_dataset():
    """Register hand-typed/pasted JSON records (array of objects) as a dataset."""
    data = _json_body()
    if data is None:
        return _bad_body()
    records = data.get('data')
    if not isinstance(records, list):
        return jsonify({'ok': False, 'error': t('api.fieldTypeInvalid', name='data')}), 400
    df = pd.DataFrame(records)
    try:
        dataset_id = _register_dataset(df, name=data.get('name', 'pasted'), source=SOURCE_PASTE)
    except ValueError as e:
        return jsonify({'ok': False, 'error': t('api.datasetTooBig', err=e)}), 400
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            'name': data.get('name', 'pasted'),
            'columns': list(df.columns),
            'row_count': len(df),
            'preview': _json_safe_records(df, 10),
        }
    )


@app.route('/api/data/inspect', methods=['POST'])
def inspect_dataset():
    """Return null counts / dtypes / duplicate counts for a dataset."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error
    return jsonify({'ok': True, 'report': DataAnalysisService.inspect(df)})


@app.route('/api/data/preview', methods=['POST'])
def preview_dataset():
    """Paginated tabular preview of any dataset (uploaded, pasted, a
    workflow node's result, or inline data) — backs the generic Data
    Preview panel so users can inspect real rows instead of only JSON/charts."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    limit = _safe_int(data.get('limit'), 50, minimum=1, maximum=500)
    offset = _safe_int(data.get('offset'), 0, minimum=0)
    total = len(df)
    page = df.iloc[offset : offset + limit]
    return jsonify(
        {
            'ok': True,
            'columns': list(df.columns),
            'rows': _json_safe_records(page),
            'total_rows': total,
            'offset': offset,
            'limit': limit,
        }
    )


@app.route('/api/analysis/run', methods=['POST'])
def run_analysis():
    """Run a cleaning pipeline against a dataset (uploaded, pasted, or a
    workflow node's result) without needing to execute a full workflow."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    steps = data.get('steps', [])
    # run_pipeline walks the list and calls ``step.get('op')`` on every element,
    # so a string ("abc" → its characters) or a list holding a bare number is an
    # AttributeError that no ValueError/TypeError wrapper can catch. Shape first,
    # with the reason, because "steps" is the one field the caller cannot guess.
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        return jsonify({'ok': False, 'error': t('api.stepsMustBeObjects')}), 400
    try:
        cleaned, report = DataAnalysisService.run_pipeline(df, steps)
    except (ValueError, TypeError) as e:
        # UnknownOperationError (a ValueError), but also the steps whose
        # parameters only the node executor can supply — join_tables without a
        # second input reaches run_pipeline as a plain TypeError. A caller
        # error is a 400 with a reason, never an HTML 500.
        return jsonify({'ok': False, 'error': str(e)}), 400

    try:
        dataset_id = _register_dataset(cleaned, name='cleaned', source=SOURCE_ANALYSIS)
    except ValueError as e:
        return jsonify({'ok': False, 'error': t('api.datasetTooBig', err=e)}), 400
    return jsonify(
        {
            'ok': True,
            'dataset_id': dataset_id,
            'report': report,
            'row_count': len(cleaned),
            'preview': _json_safe_records(cleaned, 10),
        }
    )


@app.route('/api/analysis/train', methods=['POST'])
def train_ml_model():
    """Train a traditional ML classifier (emotion or tendency) from existing
    LLM-labeled data. Uses the text and label columns specified to fit a
    TF-IDF + LogisticRegression pipeline, then saves the model to disk so
    subsequent runs can use ``mode='ml'`` for fast batch inference."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    model_type = data.get('model_type', 'emotion')
    text_column = data.get('text_column', '正文')
    label_column = data.get('label_column', 'emotion')

    if text_column not in df.columns:
        return jsonify({'ok': False, 'error': t('api.columnMissing', column=text_column)}), 400
    if label_column not in df.columns:
        return jsonify({'ok': False, 'error': t('api.columnMissing', column=label_column)}), 400

    texts, labels = build_training_data(df, text_column, label_column)
    if len(texts) < 10:
        return jsonify({'ok': False, 'error': t('api.needLabeledRows', n=len(texts))}), 400

    classifier = get_classifier(model_type)
    try:
        classifier.fit(texts, labels)
    except ValueError as e:
        # One distinct label (or no usable rows) is a data problem the user can
        # fix — it used to escape as an HTTP 500 from inside sklearn.
        return jsonify({'ok': False, 'error': str(e)}), 400

    unique_labels = sorted(set(labels))
    return jsonify(
        {
            'ok': True,
            'model_type': model_type,
            'trained_on': len(texts),
            'labels': unique_labels,
            'label_count': len(unique_labels),
        }
    )


@app.route('/api/visualize/render', methods=['POST'])
def render_visualization():
    """Render a chart from any registered dataset / workflow result / inline
    data. Works for arbitrary tabular data, not just crawler output."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    chart_type = data.get('chart_type', 'bar')
    engine = data.get('engine', 'echarts')
    x_field = data.get('x_field')
    y_field = data.get('y_field')
    value_field = data.get('value_field')
    agg = data.get('agg', 'sum')
    title = data.get('title', '')
    tokenize = bool(data.get('tokenize'))
    wordcloud_style = data.get('wordcloud_style')

    try:
        if engine == 'matplotlib':
            image = VisualizationService.render_image(
                df, chart_type, x=x_field, y=y_field, value_field=value_field, agg=agg, title=title
            )
            return jsonify({'ok': True, 'engine': 'matplotlib', 'image': image})
        kw = {'tokenize': tokenize}
        if wordcloud_style:
            kw['wordcloud_style'] = wordcloud_style
        option = VisualizationService.to_echarts_option(
            df,
            chart_type,
            x=x_field,
            y=y_field,
            value_field=value_field,
            agg=agg,
            title=title,
            **kw,
        )
        return jsonify({'ok': True, 'engine': 'echarts', 'option': option})
    except ChartConfigError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except (ValueError, KeyError, TypeError) as e:
        # e.g. matplotlib refusing a pie chart of negative values: report it as
        # a bad request instead of letting Flask return an HTML 500 (which the
        # caller cannot even json.parse()).
        logger.warning(t('misc.visualize_failed', err=e))
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/export/save', methods=['POST'])
def export_dataset():
    """Save any dataset (uploaded, pasted, cleaned, or a workflow result)
    to disk in the requested format — independent of a workflow's Save node."""
    data = _json_body()
    if data is None:
        return _bad_body()
    df, error = _resolve_payload_dataframe(data)
    if error is not None:
        return error

    # The exporter calls ``fmt.lower()`` and ``os.path.splitext(filename)`` on
    # what it is handed, so a number in either field raised AttributeError — a
    # 500 for a value the caller could simply have left out. The name is cleaned
    # *before* the format is inferred from its extension, so both calls below see
    # a real string.
    raw_format = data.get('format')
    if raw_format is not None and not isinstance(raw_format, str):
        return _bad_param('format')
    filename = sanitize_filename(data.get('filename', 'export.csv'))
    fmt = raw_format.strip() if isinstance(raw_format, str) else ''
    fmt = fmt or DataExporter.infer_format(filename)
    filename = DataExporter.normalize_filename(filename, fmt)
    filepath = os.path.join(Config.EXPORT_DIR, filename)
    try:
        text_column = data.get('text_column')
        result = DataExporter.save(
            df, filepath, fmt=fmt, text_column=text_column if isinstance(text_column, str) else None
        )
    except UnsupportedFormatError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except (TypeError, ValueError) as e:
        # A writer that cannot handle the frame's contents (an unhashable cell in
        # a json export) is still a request the caller can fix.
        return jsonify({'ok': False, 'error': str(e)}), 400
    except OSError as e:
        logger.exception(t('misc.export_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, **result})


# ─── Export artefacts (read side) ──────────────────────────────

# ``EXPORT_DIR`` was write-only: a run left files on disk and the only way to
# find them again was a file manager. These three routes are the reader, and all
# three resolve a *name* through export_browser, so no request can name a path.


@app.route('/api/exports/list', methods=['GET'])
def exports_list():
    """Every export file, newest first, with the totals for the panel header."""
    from services.export_browser import export_usage, list_exports

    limit = _safe_int(request.args.get('limit'), 200, minimum=1, maximum=500)
    rows = list_exports(Config.EXPORT_DIR, limit=limit)
    usage = export_usage(Config.EXPORT_DIR)
    return jsonify({'ok': True, 'exports': rows, 'directory': Config.EXPORT_DIR, **usage})


@app.route('/api/exports/download', methods=['GET'])
def exports_download():
    """Send one export file by name — never by path.

    An unresolvable name answers 404 the same way whether it was traversal or
    simply absent, because distinguishing them would turn this route into an
    oracle for what exists outside the export directory.
    """
    from flask import send_file

    from services.export_browser import resolve_download_path

    path = resolve_download_path(Config.EXPORT_DIR, request.args.get('name', ''))
    if not path:
        return jsonify({'ok': False, 'error': t('api.exportNotFound', name=request.args.get('name', ''))}), 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route('/api/exports/delete', methods=['POST'])
def exports_delete():
    """Delete exactly one export file. No prefixes, no recursion."""
    from services.export_browser import delete_export_file

    data = _json_body()
    if data is None:
        return _bad_body()
    name = data.get('name')
    if not isinstance(name, str) or not name.strip():
        return _bad_param('name')
    gone = delete_export_file(Config.EXPORT_DIR, name)
    return jsonify({'ok': gone, 'deleted': gone, 'name': os.path.basename(name.strip())})


# ─── One-click report ──────────────────────────────────────────


def _report_nodes(data: dict) -> tuple:
    """The tables a report may describe, as ``(nodes, meta)``.

    Two sources, one shape. With a ``run_id`` the tables come out of the run
    store, so a report can be written for a run that finished hours ago (the
    titles are stored with it). Without one, the last run in this process is
    used and the browser supplies the node titles it has on the canvas — the
    store is not the only thing worth reporting on, and a user who just watched
    a run should not have to find its record first.
    """
    run_id = str(data.get('run_id') or '').strip()
    if run_id:
        store = get_run_store()
        run = store.get_run(run_id)
        if not run:
            return None, t('api.runNotFound', rid=run_id)
        nodes = [
            {
                'id': entry.get('node_id', ''),
                'title': str(entry.get('title') or entry.get('node_id') or ''),
                'rows': store.load_rows(run_id, str(entry.get('node_id') or '')),
            }
            for entry in run.get('nodes') or []
        ]
        meta = {
            'workflow_name': run.get('workflow_name') or '',
            'run_id': run_id,
            'status': run.get('status') or '',
            'started_at': run.get('started_at') or '',
            'finished_at': run.get('finished_at') or '',
        }
        return nodes, meta

    titles = {}
    for entry in data.get('nodes') or []:
        if isinstance(entry, dict) and entry.get('id'):
            titles[str(entry['id'])] = str(entry.get('title') or entry.get('id'))
    nodes = [
        {'id': nid, 'title': titles.get(nid, nid), 'rows': rows}
        for nid, rows in sorted(_results_snapshot().items())
        if isinstance(rows, list)
    ]
    meta = {
        'workflow_name': str(execution_state.get('workflow_name') or ''),
        'run_id': str(execution_state.get('run_id') or ''),
        'status': 'in-memory',
    }
    return nodes, meta


@app.route('/api/report/generate', methods=['POST'])
def report_generate():
    """Write a self-contained HTML report of a run into the export directory.

    It lands there and nowhere else, which is what makes the export panel's
    download and delete buttons work on it without a second set of routes.
    """
    from services.report_service import ReportService, build_conclusion_prompt, summarize

    data = _json_body()
    if data is None:
        return _bad_body()
    title = data.get('title')
    if title is not None and not isinstance(title, str):
        return _bad_param('title')
    include_conclusion = bool(data.get('include_conclusion'))

    nodes, meta = _report_nodes(data)
    if nodes is None:
        return jsonify({'ok': False, 'error': meta}), 404
    if not any(node['rows'] for node in nodes):
        return jsonify({'ok': False, 'error': t('api.reportNoData')}), 400

    conclusion = ''
    if include_conclusion:
        cfg = data.get('llm') or {}
        if not isinstance(cfg, dict):
            return _bad_param('llm')
        provider = str(cfg.get('provider') or 'ollama')
        try:
            client = LLMClient(
                provider=provider,
                model=str(cfg.get('model') or ''),
                api_key=str(cfg.get('api_key') or ''),
                max_tokens=600,
                # A report request is its own call: it must not inherit the stop
                # flag of a run that ended (or is running) in this process.
                cancel_event=None,
                host=(str(cfg.get('ollama_host') or '') if provider == 'ollama' else ''),
            )
            conclusion = client.chat(build_conclusion_prompt(summarize(nodes), normalize(data.get('lang'))))
        except Exception as e:
            # The report is the deliverable; a missing paragraph is a note in it.
            add_log(t('run.reportConclusionFailed', err=e))
            conclusion = ''

    workflow_name = meta.get('workflow_name') or 'workflow'
    report = ReportService(Config.EXPORT_DIR)
    name = (title or '').strip() or workflow_name
    markup = report.build(
        (title or '').strip() or t('report.default_title', name=workflow_name),
        nodes,
        meta,
        conclusion=conclusion,
    )
    try:
        saved = report.save(markup, name)
    except OSError as e:
        add_log(t('run.reportFailed', err=e))
        return jsonify({'ok': False, 'error': str(e)}), 500
    add_log(t('run.reportSaved', name=saved['name'], size=saved['bytes']))
    return jsonify({'ok': True, **saved, 'charts': markup.count('<figure>')})


@app.route('/api/report/view', methods=['GET'])
def report_view():
    """Show one generated report in the browser, without letting it execute.

    A report is built out of text crawled off the internet, and ``.html`` is on
    the export panel's refuse-to-download list precisely because a page served
    from this app's origin can read this app's pages. So it gets its own door:
    only a name carrying the report prefix resolves, and the response forbids
    script and any external resource — the inline styles and the base64 pictures
    the writer itself produced are all that can render.
    """
    from flask import send_file

    from services.export_browser import resolve_report_path

    name = request.args.get('name', '')
    path = resolve_report_path(Config.EXPORT_DIR, name)
    if not path:
        return jsonify({'ok': False, 'error': t('api.exportNotFound', name=name)}), 404
    response = send_file(path, mimetype='text/html', download_name=os.path.basename(path))
    # ``as_attachment`` stays False: the point is to read it here. Handing the
    # name to send_file rather than writing the header by hand is what makes a
    # Chinese report title survivable — Flask encodes it (filename*=UTF-8''…),
    # while a raw non-ASCII header value stops the response halfway and leaves
    # the browser waiting for a document that never arrives.
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


# ─── Stats API ─────────────────────────────────────────────────


@app.route('/api/stats/emotion', methods=['GET'])
def emotion_stats():
    all_data = []
    # The snapshot is the point: these three routes can be polled *during* a run,
    # and iterating the live results dict while the worker publishes the next
    # node aborted the request with "dictionary changed size during iteration".
    for _nid, data in _results_snapshot().items():
        if isinstance(data, list):
            for item in data:
                if 'emotion' in item:
                    all_data.append(item)
    stats_data = StatsService.emotion_distribution(all_data)
    return jsonify({'ok': True, 'stats': stats_data})


@app.route('/api/stats/tendency', methods=['GET'])
def tendency_stats():
    all_data = []
    for _nid, data in _results_snapshot().items():
        if isinstance(data, list):
            for item in data:
                if 'tendency' in item:
                    all_data.append(item)
    stats_data = StatsService.tendency_distribution(all_data)
    return jsonify({'ok': True, 'stats': stats_data})


@app.route('/api/stats/summary', methods=['GET'])
def platform_summary():
    summary = {}
    for nid, data in _results_snapshot().items():
        if isinstance(data, list) and data:
            summary[nid] = {'count': len(data), 'sample_keys': list(data[0].keys()) if data else []}
    return jsonify({'ok': True, 'summary': summary})


# ─── Cookie API ────────────────────────────────────────────────

# One list, so a platform can never be half-wired: status, flows, generation and
# verification all walk the same tuple, which is the crawler registry's order.
# Derived from the cookie store's own list, so a platform added there cannot be
# left out of the panel, the flows or the status endpoint.
COOKIE_PLATFORMS = CookieManager.PLATFORMS


@app.route('/api/cookies/status', methods=['GET'])
def cookie_status():
    status = {platform: cookie_manager.exists(platform) for platform in COOKIE_PLATFORMS}
    return jsonify({'ok': True, 'cookies': status})


@app.route('/api/cookies/flow', methods=['GET'])
def cookie_flow():
    """What each cookie is for and how to get it, for the panel to render.

    The guidance lives in the message catalogue and the host list on the
    crawler, never in the frontend: a translated panel and a per-platform
    "which page do I log in on" answer are the same feature. Only the platforms
    in ``CookieManager.PLATFORMS`` appear here — WeChat is not one of them,
    because its article bodies are served without a session.
    """
    flows = []
    for platform in COOKIE_PLATFORMS:
        cls = crawler_class(platform)
        flows.append(
            flow_for(
                platform,
                allowed_hosts=cookie_hosts(platform),
                login_url=getattr(cls, 'login_url', '') if cls else '',
            )
        )
    return jsonify({'ok': True, 'flows': flows})


@app.route('/api/cookies/save', methods=['POST'])
def save_cookies():
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = data.get('platform', '')
    cookies = data.get('cookies', [])
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        # The platform becomes part of a filename — refuse anything else.
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if not cookies:
        return jsonify({'ok': False, 'error': t('api.cookiesRequired')}), 400
    try:
        # The same rule the login browser follows: cookies from another site do
        # not belong in this platform's file, however they were pasted in.
        kept, dropped = retain_for_platform(cookies, cookie_hosts(platform))
        if dropped:
            add_log(t('cookie.droppedForeign', platform=platform, n=dropped))
        if not kept:
            return jsonify({'ok': False, 'error': t('cookie.allForeign', platform=platform)}), 400
        cookie_manager.save(platform, kept)
        # Console mirror: cookie setup should be traceable like every other
        # state change the panel makes.
        add_log(t('cookie.saved', platform=platform))
        return jsonify({'ok': True, 'message': t('cookie.saved', platform=platform), 'count': len(kept)})
    except (OSError, ValueError) as e:
        logger.exception(t('misc.cookie_save_failed'))
        add_log(f'{t("misc.cookie_save_failed")}: {str(e)[:120]}')
        return jsonify({'ok': False, 'error': str(e)}), 500


_COOKIE_JOB_LOCK = threading.Lock()
_COOKIE_JOB = {
    'active': False,
    # Which single-flight action owns the browser: a login (waits for the user
    # to press Done) or a verification (runs to completion by itself). The panel
    # shows its "Done — I logged in" button only for the first.
    'kind': '',
    'platform': '',
    'phase': '',  # login: starting → waiting → saved | cancelled | error; verify: verifying → verified | error
    'error': '',
    'count': 0,
    'entry': '',  # the URL the browser was actually sent to
    'facts': {},  # verify: what the stored cookie unlocked
    'lines': [],  # verify: those facts, already in the user's language
    'cancel': threading.Event(),
    'confirm': threading.Event(),
}


def _close_login_browser(crawler, quit_timeout: float = 5.0):
    """Close the login browser of THIS session, whatever state it is in.

    Two older behaviours were wrong: quit() was trusted to finish (a window the
    user closed by hand leaves it hanging, keeping the chromedriver process
    alive forever), and /api/workflow/stop answered such cases with a GLOBAL
    `taskkill /IM chromedriver.exe` that also murdered unrelated Selenium
    sessions on the machine. quit() now gets a bounded grace on a side thread;
    if it does not return, exactly this session's driver process tree — the
    chrome children included — is killed.
    """
    if crawler is None:
        return
    pid = None
    with contextlib.suppress(Exception):
        pid = crawler.driver.service.process.pid
    waiter = threading.Thread(target=crawler.close, daemon=True)
    waiter.start()
    waiter.join(quit_timeout)
    if waiter.is_alive() and pid:
        with contextlib.suppress(Exception):
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True,
                timeout=8,
                check=False,
            )


def _cookie_login_worker(platform: str, wait_seconds: int, entry_url: str = ''):
    """Drive one login window from the request thread to its own daemon.

    The request thread used to sleep for the whole wait (up to 600 s), so any
    proxy or tab timeout turned a perfectly good login into a broken fetch and
    an orphaned browser. Progress lives in _COOKIE_JOB now; the panel polls it.

    *entry_url* overrides which page opens: some platforms only plant the
    cookies the crawler needs while sitting on a page the user picks (a note or
    video link), so the panel lets that link be pasted in — validated against
    the crawler's own host list before it is ever opened.
    """
    job = _COOKIE_JOB
    crawler = None
    try:
        # ``for_login`` is the point of this window: a human reads it. The crawler
        # default blocks images to save seconds per navigation, and the QR code a
        # user must scan is an ``<img>`` — with the blocker on, the panel opened a
        # window that could not be completed at all.
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR, for_login=True)
        url = entry_url or crawler.login_url
        if not url:
            raise ValueError(t('api.unsupportedPlatform', platform=platform))
        crawler.driver.get(url)
        job['entry'] = url
        add_log(t('wf.browser_opened', platform=platform, n=wait_seconds))
        add_log(t('cookie.openedEntry', url=url))
        job['phase'] = 'waiting'
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if job['cancel'].is_set():
                job['phase'] = 'cancelled'
                add_log(t('cookie.jobCancelled', platform=platform))
                return
            if job['confirm'].is_set():
                break
            try:
                # Cheap liveness probe: the moment the user closes the window
                # every call raises, and waiting on would just burn the rest
                # of the deadline pretending a login can still happen.
                _ = crawler.driver.window_handles
            except Exception:
                job['phase'] = 'error'
                job['error'] = t('cookie.windowClosed')
                add_log(t('cookie.windowClosed'))
                return
            time.sleep(1.0)
        # Confirmed early, or the deadline passed: capture best-effort either
        # way — people log in and simply forget to press the button.
        # Pull the browser back to the platform's own page first. A login that
        # ended on the identity provider (accounts.google.com, facebook.com)
        # would otherwise be read *there*, which both misses the session the crawl
        # needs and stores someone else's cookies under this platform's name. A
        # dead window raises, which the outer handler reports as it always has.
        crawler.driver.get(crawler.login_url or url)
        cookies, dropped = retain_for_platform(crawler.driver.get_cookies(), crawler_hosts(crawler))
        if dropped:
            add_log(t('cookie.droppedForeign', platform=platform, n=dropped))
        if not cookies:
            job['phase'] = 'error'
            job['error'] = t('cookie.noCookies')
            add_log(t('cookie.noCookies'))
            return
        cookie_manager.save(platform, cookies)
        job['count'] = len(cookies)
        job['phase'] = 'saved'
        add_log(t('wf.cookies_generated', platform=platform, n=len(cookies)))
    except Exception as e:
        logger.exception(t('misc.cookie_gen_failed'))
        job['phase'] = 'error'
        job['error'] = str(e)[:300]
        add_log(f'{t("misc.cookie_gen_failed")}: {str(e)[:120]}')
    finally:
        _close_login_browser(crawler)
        with _COOKIE_JOB_LOCK:
            job['active'] = False


@app.route('/api/cookies/generate', methods=['POST'])
def generate_cookies():
    """Open a login browser as a single-flight background job.

    One login at a time, machine-wide: two windows racing on the same profile
    (or on the user's attention) saved half-cookies and confusion. A second
    request is refused with the platform of the live one.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    wait_seconds = _safe_int(data.get('wait_seconds'), 120, minimum=10, maximum=600)
    # A cookie-only platform still needs a real login page; anything without one
    # would open a browser at about:blank and capture nothing.
    # A link the user pasted, if any. It has to belong to this platform: the
    # browser is driven with their real session, and cookies are saved per
    # platform file — opening some other site here would store that site's
    # session under, say, "zhihu" and the crawl would carry it to Zhihu.
    requested = str(data.get('url') or '').strip()
    entry_url = normalize_entry_url(requested, cookie_hosts(platform))
    entry_rejected = bool(requested) and not entry_url

    with _COOKIE_JOB_LOCK:
        if _COOKIE_JOB['active']:
            return (
                jsonify(
                    {
                        'ok': False,
                        'busy': True,
                        'platform': _COOKIE_JOB['platform'],
                        'error': t('api.cookieBusy', platform=_COOKIE_JOB['platform']),
                    }
                ),
                409,
            )
        _COOKIE_JOB.update(active=True, kind='login', platform=platform, phase='starting', error='', count=0)
        _COOKIE_JOB['entry'] = ''
        _COOKIE_JOB['facts'] = {}
        _COOKIE_JOB['lines'] = []
        _COOKIE_JOB['cancel'].clear()
        _COOKIE_JOB['confirm'].clear()
    threading.Thread(target=_cookie_login_worker, args=(platform, wait_seconds, entry_url), daemon=True).start()
    payload = {'ok': True, 'message': t('cookie.started'), 'entry': entry_url or ''}
    if entry_rejected:
        # Say so instead of quietly opening somewhere else: the user believes
        # they are logging in for one purpose and the browser shows another.
        payload['entry_rejected'] = True
        payload['entry_note'] = t('cookie.entryRejected', platform=platform)
        add_log(payload['entry_note'])
    return jsonify(payload), 202


@app.route('/api/cookies/generate/status', methods=['GET'])
def cookie_generate_status():
    return jsonify(
        {
            'ok': True,
            'active': _COOKIE_JOB['active'],
            'kind': _COOKIE_JOB['kind'],
            'platform': _COOKIE_JOB['platform'],
            'phase': _COOKIE_JOB['phase'],
            'error': _COOKIE_JOB['error'],
            'count': _COOKIE_JOB['count'],
            'entry': _COOKIE_JOB['entry'],
            'facts': _COOKIE_JOB['facts'],
            'lines': _COOKIE_JOB['lines'],
        }
    )


def _verify_lines(platform: str, facts: dict) -> list:
    """Turn one diagnosis into the lines the panel shows."""
    lines = [t('cookie.verify.checkedUrl', url=str(facts.get('url') or ''))]
    lines.append(
        t('cookie.verify.loginWall', platform=platform)
        if facts.get('login_wall')
        else t('cookie.verify.ok', platform=platform)
    )
    return lines


def _cookie_verify_worker(platform: str, url: str):
    """Probe the stored cookie against the live site and report what it unlocks.

    Visible by design: this machine's risk control treats a headless content
    page differently from a real window (Zhihu in particular), and a diagnosis
    that blamed the cookie for a headless block would send the user to log in
    again for nothing.
    """
    job = _COOKIE_JOB
    crawler = None
    try:
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR)
        facts = crawler.diagnose(url)
        lines = _verify_lines(platform, facts)
        with _COOKIE_JOB_LOCK:
            job['facts'] = facts
            job['lines'] = lines
            job['entry'] = str(facts.get('url') or '')
            job['phase'] = 'verified'
        for line in lines:
            add_log(line)
    except Exception as e:
        logger.exception(t('misc.cookie_gen_failed'))
        with _COOKIE_JOB_LOCK:
            job['phase'] = 'error'
            job['error'] = str(e)[:300]
        add_log(t('cookie.verifyFailed', err=str(e)[:120]))
    finally:
        _close_login_browser(crawler)
        with _COOKIE_JOB_LOCK:
            job['active'] = False


@app.route('/api/cookies/verify', methods=['POST'])
def verify_cookies():
    """Ask the platform, with the saved cookie, whether it still lets us in.

    Refused outright when no cookie is stored: opening a browser to discover
    that would only produce a wall that looks like a failed check.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if not cookie_manager.exists(platform):
        return jsonify({'ok': False, 'error': t('cookie.verify.noCookie', platform=platform)}), 400
    requested = str(data.get('url') or '').strip()
    target = normalize_entry_url(requested, cookie_hosts(platform))
    if requested and not target:
        return jsonify({'ok': False, 'error': t('cookie.entryRejected', platform=platform)}), 400

    with _COOKIE_JOB_LOCK:
        if _COOKIE_JOB['active']:
            return (
                jsonify(
                    {
                        'ok': False,
                        'busy': True,
                        'platform': _COOKIE_JOB['platform'],
                        'error': t('api.cookieBusy', platform=_COOKIE_JOB['platform']),
                    }
                ),
                409,
            )
        _COOKIE_JOB.update(active=True, kind='verify', platform=platform, phase='verifying', error='', count=0)
        _COOKIE_JOB['entry'] = ''
        _COOKIE_JOB['facts'] = {}
        _COOKIE_JOB['lines'] = []
        _COOKIE_JOB['cancel'].clear()
        _COOKIE_JOB['confirm'].clear()
    threading.Thread(target=_cookie_verify_worker, args=(platform, target), daemon=True).start()
    return jsonify({'ok': True, 'message': t('cookie.verifying')}), 202


@app.route('/api/cookies/generate/confirm', methods=['POST'])
def cookie_generate_confirm():
    """'I finished logging in' — capture and save the cookies now."""
    with _COOKIE_JOB_LOCK:
        if not _COOKIE_JOB['active'] or _COOKIE_JOB['kind'] != 'login':
            return jsonify({'ok': False, 'error': t('api.noCookieJob')}), 400
        _COOKIE_JOB['confirm'].set()
    return jsonify({'ok': True})


@app.route('/api/cookies/generate/cancel', methods=['POST'])
def cookie_generate_cancel():
    with _COOKIE_JOB_LOCK:
        if not _COOKIE_JOB['active'] or _COOKIE_JOB['kind'] != 'login':
            return jsonify({'ok': False, 'error': t('api.noCookieJob')}), 400
        _COOKIE_JOB['cancel'].set()
    return jsonify({'ok': True})


# ─── Config API ────────────────────────────────────────────────


@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(
        {
            'ollama_model': Config.OLLAMA_MODEL,
            'default_headless': Config.DEFAULT_HEADLESS,
            'max_workers': Config.DEFAULT_MAX_WORKERS,
        }
    )


@app.route('/api/capabilities', methods=['GET'])
def get_capabilities():
    """The crawl matrix, so the browser can build the Data Source panel from it.

    The panel used to hard-code which platforms exist, which of them take links
    instead of a keyword and which fields belong to which mode — a fourth copy of
    a fact the executor already had to know. Labels travel as catalogue keys
    because this payload has no language: the canvas translates it into whichever
    one the user is reading.
    """
    return jsonify(capabilities.as_dict())


# ─── Runtime settings API ──────────────────────────────────────
#
# Machine-local values that used to be hardcoded (chromedriver path, browser
# window, timeouts, Ollama address). Persisted to data/settings.json by the
# settings store; crawlers and LLM calls read them per run, so a save applies
# on the next execution without restarting the server.


@app.route('/api/settings', methods=['GET'])
def get_runtime_settings():
    return jsonify({'ok': True, 'settings': all_settings()})


@app.route('/api/settings', methods=['POST'])
def set_runtime_settings():
    data = _json_body()
    if data is None:
        return _bad_body()
    patch = data.get('settings') if isinstance(data.get('settings'), dict) else data
    values, warnings = save_settings(patch or {})
    return jsonify({'ok': True, 'settings': values, 'warnings': warnings})


# ─── Browser profiles API ──────────────────────────────────────


@app.route('/api/browser/profiles', methods=['GET'])
def get_browser_profiles():
    """One row per platform that has a login session at all.

    WeChat is deliberately absent: its article bodies need no login (there is no
    cookie row for it anywhere in this app), so a browser profile would be a
    directory of nothing — and a row in this table reads as "you should log in here".

    Three things can only be checked from the request side:

    * the payload covers **every platform the cookie panel can sign into**, in matrix
      order (a platform missing here is one whose state the user cannot see);
    * `recommended` is read off the crawl matrix, not from a second list this endpoint
      keeps by hand;
    * a directory is reported as *existing* only after something created it, and as
      *imported* only after a cookie actually went in. Those two booleans are the whole
      guidance sentence in the panel.
    """
    rows = {'ok': True, 'enabled': browser_profiles.is_enabled(), 'root': browser_profiles.root_dir()}
    rows['profiles'] = []
    for cap in capabilities.CAPABILITIES:
        platform = cap.platform
        if not CookieManager.is_supported(platform):
            continue
        saved = os.path.join(Config.COOKIE_DIR, f'{platform}_cookies.json')
        rows['profiles'].append(
            browser_profiles.status(
                platform,
                recommended=cap.profile_recommended,
                has_cookie=os.path.isfile(saved),
            )
        )
    return jsonify(rows)


# ─── AI (LLM) API ──────────────────────────────────────────────
#
# The settings panel picks a transport: the local Ollama daemon or OpenRouter
# (aimed at :free models). The API key never touches disk here — the browser
# keeps it in localStorage and posts it with each request.


@app.route('/api/llm/models', methods=['GET'])
def llm_models():
    """Current OpenRouter catalog filtered to zero-cost models, so the
    dropdown never goes stale the way a hardcoded list would."""
    try:
        models = list_free_models(timeout=15)
        return jsonify({'ok': True, 'models': models})
    except (requests.RequestException, ValueError, KeyError) as e:
        # Offline / catalog changed shape: the panel just shows no models.
        logger.warning(t('api.llmModelsFailed', err=e))
        return jsonify({'ok': False, 'error': t('api.llmModelsFailed', err=e), 'models': []}), 502


@app.route('/api/llm/ollama/models', methods=['GET'])
def llm_ollama_models():
    """Tags the local daemon has pulled, so the AI panel can offer a picker
    instead of demanding a hand-typed model name.

    Kept apart from /api/llm/models (the OpenRouter catalog) on purpose: the
    two providers no longer share a model setting, so they must not share a
    dropdown either.
    """
    host = str(get_setting('ollama_host') or '')
    shown = host or 'http://localhost:11434'
    try:
        models = list_ollama_models(host, timeout=8)
        return jsonify({'ok': True, 'models': models, 'host': shown})
    except (requests.RequestException, ValueError) as e:
        # Daemon not running / wrong address / something else answering on the
        # port: the panel shows the reason *and* the address it tried, which is
        # the whole point of the button.
        logger.warning(t('api.ollamaModelsFailed', host=shown, err=e))
        return jsonify({'ok': False, 'error': t('api.ollamaModelsFailed', host=shown, err=e), 'models': []}), 502


@app.route('/api/llm/test', methods=['POST'])
def llm_test():
    """Tiny round-trip so the user can validate provider/model/key before
    committing to a long row-by-row run."""
    data = _json_body()
    if data is None:
        return _bad_body()
    provider = data.get('provider') or 'ollama'
    client = LLMClient(
        provider=provider,
        model=data.get('model') or '',
        api_key=data.get('api_key') or '',
        max_tokens=16,
        max_chars=0,
        timeout=60 if provider == 'ollama' else 45,
        host=str(get_setting('ollama_host') or '') if provider == 'ollama' else '',
    )
    started = time.time()
    try:
        reply = client.chat('Reply with exactly: OK', max_retries=1)
        latency = int((time.time() - started) * 1000)
        return jsonify(
            {
                'ok': True,
                'latency_ms': latency,
                'reply': reply.strip()[:80],
                'provider': client.label,
                'model': client.model,
                # Which daemon answered — with the local transport the address
                # is half of "why did this fail", so the panel can show it.
                'host': client.host if provider == 'ollama' else '',
            }
        )
    except LLMError as e:
        return jsonify({'ok': False, 'error': str(e), 'kind': e.kind})
    except Exception as e:
        # The test endpoint reports the failure; it never raises.
        return jsonify({'ok': False, 'error': str(e), 'kind': 'error'})


# ─── Clear Dataset Cache API ─────────────────────────────────────


@app.route('/api/data/clear', methods=['POST'])
def clear_datasets():
    """Housekeeping on stored files.

    By default it drops only *orphans* — files no saved workflow points at and
    nobody has read for a while. That used to be a blunt "forget everything",
    which made no sense once a saved workflow came to depend on those files.
    ``?all=1`` really does empty the store, pointers included, for the rare
    case of wanting a clean slate.
    """
    store = get_dataset_store()
    payload = _json_body()
    if payload is None:
        return _bad_body()
    wipe = str(payload.get('all') or request.args.get('all') or '') in ('1', 'true', 'yes')
    if wipe:
        removed = store.clear()
        _dataset_cache.clear()
        logger.warning(t('ds.cleared', n=removed))
        return jsonify({'ok': True, 'removed': removed, 'orphans': 0})

    _dataset_cache.clear()
    removed = store.purge_unreferenced()
    kept = store.stats()
    logger.info(t('ds.purge_result', n=removed, kept=kept['datasets']))
    return jsonify({'ok': True, 'removed': removed, 'kept': kept['datasets']})


# ─── Chart Studio API (embedded ZENVIZ workbench) ─────────────────
#
# The studio runs in a same-origin iframe and authors charts from a workflow
# dataset. These two endpoints close the loop: hand it real rows, and take the
# finished chart back as a file next to the other workflow exports.

STUDIO_MAX_ROWS = 5000
# A chart PNG is a few hundred KB; 20 MB is a generous ceiling that still keeps
# a malformed payload from ballooning the process.
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _first_tabular_result():
    """Return (node_id, DataFrame) for the first node that produced a tabular
    result, or (None, None). Used as a fallback so the Chart Studio still gets
    data when the user picked a node that has not produced output yet."""
    for node_id, result in _results_snapshot().items():
        if isinstance(result, list) and result:
            return node_id, pd.DataFrame(result)
    return None, None


def _merge_unique_names(names: list, used: dict) -> list:
    """Make a frame's column names unique across everything already merged.

    A repeat gets the source's ordinal appended (`freq` → `freq_2`), and that
    again (`freq_2_3`) if even that is taken — the studio binds columns by name,
    so two columns called `freq` would make the second one unreachable.
    """
    out = []
    for raw in names:
        name = str(raw)
        if name not in used:
            used[name] = 1
            out.append(name)
            continue
        # `used[name]` doubles as the ordinal to try next for that name.
        used[name] += 1
        candidate = f'{name}_{used[name]}'
        while candidate in used:
            used[name] += 1
            candidate = f'{name}_{used[name]}'
        used[candidate] = 1
        out.append(candidate)
    return out


def _merge_frames(frames: list, mode: str) -> tuple[pd.DataFrame, str]:
    """Combine several nodes' tables into one. → (DataFrame, mode actually used)

    Both modes place whole tables next to each other, the way you would paste
    them into one sheet — never interleaved. Nothing is matched up by value, so
    the result is always a full rectangle with no half-empty rows:

    rows — put the other table *below*: its rows are appended after the first
           table's, re-using the first table's column names for the columns they
           line up with. Nothing is dropped and nothing is left blank.
    side — put the other table *to the right*: its columns are appended after
           the first table's, row 1 next to row 1. A shorter table just stops
           early.
    """
    if len(frames) < 2:
        return frames[0], 'rows'
    if mode in ('side', 'columns', 'right'):
        parts = []
        used: dict = {}
        for frame in frames:
            part = frame.reset_index(drop=True).copy()
            part.columns = _merge_unique_names(list(part.columns), used)
            parts.append(part)
        return pd.concat(parts, axis=1), 'side'

    # Appending rows. Identical column sets stack by name (the ordinary case:
    # two word-frequency tables joined end to end).
    base = [str(c) for c in frames[0].columns]
    if all([str(c) for c in f.columns] == base for f in frames[1:]):
        return pd.concat(frames, ignore_index=True, sort=False), 'rows'

    # Different schemas: line the tables up by *position* instead, so the second
    # table lands under the first rather than on the empty cells beside it.
    width = max(len(f.columns) for f in frames)
    header = list(base)
    for frame in frames[1:]:
        for idx, col in enumerate(frame.columns):
            if idx >= len(header):
                header.append(str(col))
    header = header[:width]

    rows = []
    for frame in frames:
        for record in frame.itertuples(index=False, name=None):
            row = list(record)
            rows.append(row + [None] * (width - len(row)) if len(row) < width else row)
    return pd.DataFrame(rows, columns=header), 'rows'


def _studio_dataset_merged(data: dict, sources: list):
    """Load several nodes at once and hand the studio a single merged table.

    A source that cannot be served is *skipped*, not fatal: the picker already
    greys those out, so this only happens when the probe went stale (a server
    restart wipes the in-memory results). Every source's fate is reported back so
    the bar can say "2 of 3 loaded" rather than quietly pretending.
    """
    limit = _safe_int(data.get('limit'), STUDIO_MAX_ROWS, minimum=1, maximum=STUDIO_MAX_ROWS)
    mode = str(data.get('merge') or 'concat').lower()
    frames = []
    report = []
    for src in sources[:STUDIO_MAX_SOURCES]:
        src = src if isinstance(src, dict) else {}
        node_id = str(src.get('node_id') or '')
        try:
            df = _resolve_dataframe(src)
            if df is None or df.empty:
                report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_EMPTY})
                continue
            frames.append(df)
            report.append(
                {
                    'node_id': node_id,
                    'ok': True,
                    'rows': len(df),
                    'columns': len(df.columns),
                    'reason': '',
                }
            )
        except KeyError:
            report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_NO_RESULT})
        except Exception:
            logger.exception(t('misc.studio_source_failed'))
            report.append({'node_id': node_id, 'ok': False, 'rows': 0, 'reason': SRC_ERROR})

    if not frames:
        return jsonify(
            {
                'ok': False,
                'code': 'no_result',
                'error': t('api.noSourceTable'),
                'sources': report,
            }
        )

    merged, used_mode = _merge_frames(frames, mode)
    total = len(merged)
    page = merged.iloc[:limit]
    return jsonify(
        {
            'ok': True,
            'columns': [str(c) for c in merged.columns],
            'rows': _json_safe_records(page),
            'total_rows': total,
            'truncated': total > limit,
            'merged': len(frames) > 1,
            'merge_mode': used_mode,
            'sources': report,
            'fallback': None,
        }
    )


@app.route('/api/studio/dataset', methods=['POST'])
def studio_dataset():
    """Full tabular dump of a node's result / uploaded dataset.

    /api/data/preview is deliberately paginated for on-screen browsing; the
    studio needs the whole table in one shot so it can bind columns and series
    itself, so this returns everything up to STUDIO_MAX_ROWS.

    Two request shapes:

      {"node_id": …}                       one node — what the picker sends when
                                           exactly one row is selected
      {"sources": [{…}, {…}], "merge": …}  several nodes, merged into one table

    Node results only exist after a workflow run, and they live in memory, so a
    freshly (re)started server has none. For a single node we fall back to
    whichever node does have data and say so via `fallback`; a merged load never
    does that silently — it reports each source instead.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    sources = data.get('sources')
    if isinstance(sources, list) and sources:
        if len(sources) > 1:
            return _studio_dataset_merged(data, sources)
        src = sources[0] if isinstance(sources[0], dict) else {}
        limit = data.get('limit', STUDIO_MAX_ROWS)
        data = dict(src)
        data.setdefault('limit', limit)

    fallback_note = None
    try:
        df = _resolve_dataframe(data)
    except (KeyError, TypeError, ValueError) as e:
        # KeyError is a reference to a node whose result is gone — the case the
        # fallback below exists for. TypeError/ValueError are a payload of the
        # wrong *shape* (``{"data": 42}``), which used to escape the pandas
        # constructor as an HTML 500 the browser could not parse; both answer
        # with the same ok:false + code the picker already localises.
        fb_id, fb_df = _first_tabular_result()
        if fb_df is None or fb_df.empty:
            return jsonify({'ok': False, 'code': 'no_result', 'error': str(e)})
        df = fb_df
        fallback_note = {'requested': data.get('node_id'), 'used': fb_id}

    limit = _safe_int(data.get('limit'), STUDIO_MAX_ROWS, minimum=1, maximum=STUDIO_MAX_ROWS)
    total = len(df)
    page = df.iloc[:limit]
    return jsonify(
        {
            'ok': True,
            'columns': [str(c) for c in df.columns],
            'rows': _json_safe_records(page),
            'total_rows': total,
            'truncated': total > limit,
            'fallback': fallback_note,
        }
    )


# Why a candidate cannot be served. Stable short codes so the browser can
# localise them; the picker shows a short form inline and the long form as a
# tooltip / toast.
SRC_NO_UPSTREAM = 'no_upstream'
SRC_NO_RESULT = 'no_result'
SRC_STALE_DATASET = 'stale_dataset'
SRC_EMPTY = 'empty'
SRC_ERROR = 'error'
STUDIO_MAX_CANDIDATES = 500
# Column names travel with each probe so the picker can tell the user what is
# inside a node before they combine it; only the first few are ever shown.
PROBE_MAX_COLUMNS = 24
# How many nodes one merged load may combine.
STUDIO_MAX_SOURCES = 50


def _column_names(df) -> list:
    """Column names for the picker's tooltip. Capped: the picker shows a handful
    and the probe runs for every node on the canvas."""
    try:
        return [str(c) for c in list(df.columns)[:PROBE_MAX_COLUMNS]]
    except Exception:
        return []


def _probe_source(payload: dict | None) -> tuple[bool, int, str, list]:
    """Can this payload produce a table right now? → (available, rows, reason,
    columns).

    Deliberately cheap. The picker probes every node on the canvas in one go, so
    for the two common cases — an uploaded dataset and a node's stored run
    result — the row count and column names are read straight off the stored
    DataFrame / list instead of materialising a copy. Only payloads carrying
    inline records have to go through _resolve_dataframe, because those are
    computed rather than stored.
    """
    if not isinstance(payload, dict):
        return False, 0, SRC_NO_UPSTREAM, []

    dataset_id = payload.get('dataset_id')
    if dataset_id:
        df = _load_dataset(dataset_id)
        if df is None:
            return False, 0, SRC_STALE_DATASET, []
        rows = len(df)
        return (True, rows, '', _column_names(df)) if rows else (False, 0, SRC_EMPTY, [])

    node_id = payload.get('node_id')
    if not node_id:
        return False, 0, SRC_NO_UPSTREAM, []
    result = execution_state['results'].get(node_id)
    if isinstance(result, list):
        rows = len(result)
        if not rows:
            return False, 0, SRC_EMPTY, []
        first = result[0]
        cols = list(first.keys()) if isinstance(first, dict) else []
        return True, rows, '', [str(c) for c in cols[:PROBE_MAX_COLUMNS]]

    # Nothing live: fall back to the rows the node last stored, so a probe right
    # after a page refresh answers instead of reporting "no data".
    stored = _durable_node_rows(node_id, payload.get('workflow_name') or '')
    if stored:
        cols = list(stored[0].keys()) if isinstance(stored[0], dict) else []
        return True, len(stored), '', [str(c) for c in cols[:PROBE_MAX_COLUMNS]]

    try:
        df = _resolve_dataframe(payload)
    except KeyError:
        return False, 0, SRC_NO_RESULT, []
    except Exception:
        logger.exception(t('misc.source_probe_failed'))
        return False, 0, SRC_ERROR, []
    rows = 0 if df is None else len(df)
    return (True, rows, '', _column_names(df)) if rows else (False, 0, SRC_EMPTY, [])


@app.route('/api/studio/sources', methods=['POST'])
def studio_sources():
    """Pre-flight for the studio's source picker.

    Every node on the canvas is listed, but only those that can actually hand
    the studio a table are selectable. The browser works out the static dead
    ends itself (a Visualize node with nothing connected has no payload at all);
    this endpoint answers the runtime half — has the node produced a result yet,
    is the uploaded dataset still around — so the user is told *why* a row is
    unselectable before clicking Load instead of after.

    Body: {"candidates": [{"node_id": str, "payload": {...} | null}]}
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    candidates = data.get('candidates')
    if not isinstance(candidates, list):
        return jsonify({'ok': False, 'error': t('api.badRequest', what='candidates list')}), 400

    sources = []
    for item in candidates[:STUDIO_MAX_CANDIDATES]:
        item = item if isinstance(item, dict) else {}
        available, rows, reason, cols = _probe_source(item.get('payload'))
        sources.append(
            {
                'node_id': str(item.get('node_id') or ''),
                'available': available,
                'rows': rows,
                'reason': reason,
                'cols': cols,
            }
        )
    return jsonify({'ok': True, 'sources': sources})


@app.route('/api/studio/save-image', methods=['POST'])
def studio_save_image():
    """Persist a chart rendered in the studio (PNG data URL) into EXPORT_DIR."""
    data = _json_body()
    if data is None:
        return _bad_body()
    image = data.get('image') or ''
    match = re.match(r'^data:image/(png|jpeg|jpg|webp);base64,(.+)$', image, re.DOTALL)
    if not match:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='image data URL')}), 400

    ext = match.group(1)
    if ext == 'jpeg':
        ext = 'jpg'
    try:
        payload = base64.b64decode(match.group(2), validate=False)
    except (ValueError, TypeError) as e:
        return jsonify({'ok': False, 'error': t('api.parseFailed', err=e)}), 400
    if not payload:
        return jsonify({'ok': False, 'error': t('api.badRequest', what='empty image')}), 400
    if len(payload) > MAX_IMAGE_BYTES:
        # A full-canvas chart is a few hundred KB; anything far past the cap is
        # either a mistake or an attempt to exhaust memory.
        return jsonify({'ok': False, 'error': t('api.badRequest', what='image too large')}), 400

    name = data.get('name') or 'studio-chart'
    name = re.sub(r'\.(png|jpe?g|webp)$', '', str(name), flags=re.IGNORECASE)
    filename = sanitize_filename(f'{name}-{uuid.uuid4().hex[:8]}.{ext}')
    filepath = os.path.join(Config.EXPORT_DIR, filename)
    try:
        os.makedirs(Config.EXPORT_DIR, exist_ok=True)
        with open(filepath, 'wb') as fh:
            fh.write(payload)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'Could not write file: {e}'}), 500

    logger.info(t('misc.studio_saved', path=filepath, bytes=len(payload)))
    return jsonify({'ok': True, 'filename': filename, 'path': filepath, 'bytes': len(payload)})


# ─── Execution History API (time-series comparison across runs) ───


@app.route('/api/history/runs', methods=['GET'])
def history_runs():
    limit = _safe_int(request.args.get('limit'), 50, minimum=1, maximum=1000)
    df = history_service.list_runs(limit=limit)
    return jsonify({'ok': True, 'runs': df.to_dict('records'), 'workflow_names': history_service.list_workflow_names()})


@app.route('/api/history/series', methods=['GET'])
def history_series():
    workflow_name = request.args.get('workflow_name') or None
    metric = request.args.get('metric') or None
    node_id = request.args.get('node_id') or None
    limit = _safe_int(request.args.get('limit'), 2000, minimum=1, maximum=20000)
    df = history_service.series(workflow_name=workflow_name, metric=metric, node_id=node_id, limit=limit)
    return jsonify({'ok': True, 'rows': df.to_dict('records')})


@app.route('/api/history/clear', methods=['POST'])
def history_clear():
    history_service.clear()
    return jsonify({'ok': True, 'message': t('history.cleared')})


@app.route('/api/history/delete', methods=['POST'])
def history_delete():
    """Forget one run's recorded metrics, leaving the rest of the history alone.

    «清空历史» was the only door out, so one bad run meant losing the whole
    comparison chart to get rid of it. The answer carries the deleted row count
    because an id that matched nothing is a different truth from a deletion:
    the panel is looking at a list it loaded a moment ago, and a run can have
    been aged out by the retention policy in between.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    if not run_id:
        return jsonify({'ok': False, 'error': t('api.historyNoRunId')}), 400
    deleted = history_service.delete_run(run_id)
    return jsonify({'ok': True, 'deleted': deleted, 'run_id': run_id})


# ─── Resumable runs ────────────────────────────────────────────


@app.route('/api/runs/resumable', methods=['POST'])
def runs_resumable():
    """Runs worth offering to resume, for the workflow currently on the canvas.

    Matched on the *structure* (node ids, types and wiring), not the settings:
    tweaking a keyword should still find the interrupted attempt of this same
    workflow. The browser also gets the per-node breakdown it needs to say what
    is already paid for.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    workflow = data.get('workflow') or {}
    if not isinstance(workflow, dict) or not workflow.get('nodes'):
        return jsonify({'ok': True, 'runs': []})
    limit = _safe_int(data.get('limit'), 10, minimum=1, maximum=100)
    found = get_run_store().list_resumable(workflow_fingerprint(workflow), limit=limit)
    # A *live* run is never resumable — offering it invites 重新开始 to discard
    # the run that is still writing right now. Leftover 'running' rows from a
    # dead process were already promoted to 'interrupted' at startup.
    runs = [r for r in found if r.get('status') != RUN_RUNNING]
    return jsonify({'ok': True, 'runs': runs})


@app.route('/api/runs/list', methods=['GET'])
def runs_list():
    """Every recorded run, newest first — the run-records panel's backbone.

    Unlike /resumable this is not filtered by the canvas: orphaned runs (the
    workflow has since been rewired or deleted) must stay visible here, or
    they can never be continued or cleaned up.
    """
    limit = _safe_int(request.args.get('limit'), 50, minimum=1, maximum=200)
    runs = get_run_store().list_resumable(limit=limit, include_finished=True)
    # The waiting list rides along: the panel that shows finished runs is where
    # someone looks to see what has not started yet.
    return jsonify({'ok': True, 'runs': runs, 'queue': queue_snapshot()})


@app.route('/api/runs/status', methods=['GET'])
def runs_status():
    """Live state of the run in flight (its id and how far it got), so a page
    reload mid-run can still offer to continue it afterwards."""
    return jsonify(
        {
            'ok': True,
            'running': bool(execution_state.get('running')),
            'run_id': execution_state.get('run_id') or '',
            'resume': bool(execution_state.get('resume')),
        }
    )


@app.route('/api/runs/stats', methods=['GET'])
def runs_stats():
    return jsonify({'ok': True, 'stats': get_run_store().stats()})


def _reject_live_run(run_id: str):
    """True when run_id names the run a live thread is still writing.

    Discarding or deleting it mid-flight would pull the rows and cursor out
    from under the writer — the UI's 丢弃/删除 must go through Stop first.
    """
    return bool(run_id) and execution_state['running'] and run_id == str(execution_state.get('run_id') or '')


@app.route('/api/runs/purge', methods=['POST'])
def runs_purge():
    """Housekeeping. Interrupted runs are the last to go — they are the ones
    somebody may still want to continue. The live run, if any, is exempt."""
    exclude = str(execution_state.get('run_id') or '') if execution_state['running'] else ''
    removed = get_run_store().purge(exclude_run_id=exclude)
    return jsonify({'ok': True, 'removed': removed})


@app.route('/api/runs/discard', methods=['POST'])
def runs_discard():
    """Throw away an interrupted run and start the next one from scratch.

    The "already collected" claims go with it: without that, pressing start
    over would silently return fewer rows than asked for, because every item
    the discarded attempt fetched still counts as seen.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    if not run_id:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid='-')}), 400
    store = get_run_store()
    if store.get_run(run_id) is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id)}), 404
    if _reject_live_run(run_id):
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 400
    removed = store.delete_run(run_id)
    removed['item_claims'] = store.forget_run_items(run_id)
    return jsonify({'ok': True, 'removed': removed})


@app.route('/api/runs/delete', methods=['POST'])
def runs_delete():
    """Drop a finished run's copy of the data. Kept separate from discard:
    deleting an old run must not resurrect items as "unseen" for a crawl
    that is still being continued."""
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    if not run_id:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid='-')}), 400
    if _reject_live_run(run_id):
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 400
    removed = get_run_store().delete_run(run_id)
    return jsonify({'ok': True, 'removed': removed})


@app.route('/api/runs/<run_id>', methods=['GET'])
def runs_detail(run_id: str):
    """One run, node by node — what the resume node's picker enumerates."""
    run = get_run_store().get_run(run_id)
    if run is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id)}), 404
    return jsonify({'ok': True, 'run': run})


# ─── Main ──────────────────────────────────────────────────────


def _open_browser(url: str):
    """Open the UI in the default browser once the server is up."""
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception as e:
        # A headless box has no browser to open — warn, never crash the startup.
        logger.warning(t('misc.browser_open_failed', err=e))


def _debug_enabled() -> bool:
    """FLASK_DEBUG as a plain yes/no (anything else, unset included, is no)."""
    return str(os.environ.get('FLASK_DEBUG', '')).strip().lower() in ('1', 'true', 'yes')


if __name__ == '__main__':
    # Local by default: this server drives a browser, holds crawl cookies and can
    # run arbitrary code through the debugger, so it must not reach the LAN unless
    # somebody asks for it with HOST. Debug is off for the same reason — the
    # Werkzeug debugger is a remote code execution path and the reloader runs this
    # module twice — and is opt-in via FLASK_DEBUG.
    port = _safe_int(os.environ.get('PORT'), 5000, minimum=1, maximum=65535)
    host = str(os.environ.get('HOST') or '127.0.0.1')
    debug = _debug_enabled()
    # A wildcard bind is not a URL to visit, so the browser gets the loopback.
    browse_host = '127.0.0.1' if host in ('0.0.0.0', '::') else host
    # Opening the browser is a development convenience only: a server started for
    # real use (debug off) must not spawn a tab on the machine it runs on.
    # With the reloader on, this module runs twice — once in the watcher
    # (WERKZEUG_RUN_MAIN unset) and once in the serving child — so the watcher is
    # the one that opens, which means exactly one tab. The 1.5s delay lets the
    # child bind the port before the browser arrives.
    if debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        threading.Timer(1.5, _open_browser, args=(f'http://{browse_host}:{port}',)).start()
    logger.info(t('misc.server_starting', port=port))
    # Retention is applied on its own, not only when somebody remembers to
    # click: startup is the other moment nothing is writing.
    _housekeep(force=True)
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=debug)
