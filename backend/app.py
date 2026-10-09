import contextlib
import ctypes
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import browser_profiles
import cookie_preflight
import crawl_gate
import pandas as pd
from api.analysis import bp as analysis_bp
from api.browser_profiles import bp as browser_profiles_bp
from api.capabilities import bp as capabilities_bp
from api.config import bp as config_bp
from api.data import bp as data_bp
from api.exports import bp as exports_bp
from api.history import bp as history_bp
from api.http import _bad_body, _bad_param, _json_body, _optional_float, _optional_int, _safe_float, _safe_int
from api.llm import bp as llm_bp
from api.locks import bp as locks_bp
from api.report import bp as report_bp
from api.settings import bp as settings_bp
from api.stats import bp as stats_bp
from api.studio import bp as studio_bp
from api.visualize import bp as visualize_bp
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from profiles import ensure_profile_template
from state import (
    _RUN_QUEUE,
    LOG_KEEP,
    _completed_lock,
    _push_log,
    _results_snapshot,
    _wf_local,
    add_log,
    cookie_manager,
    execution_state,
    history_service,
    reset_console_state,
)
from stores import (
    _apply_dataset_meta,
    get_dataset_store,
    get_housekeeper,
    get_run_store,
)
from transport import _local_transport_refusal

import crawl_capabilities as capabilities
from analyzers import (
    BERT_BATCH,
    AggressionAnalyzer,
    AnomalyDetector,
    ContentCleaner,
    CorrelationAnalyzer,
    EmotionAnalyzer,
    KeywordExtractor,
    NamedEntityRecognizer,
    SentimentAnalyzer,
    TendencyAnalyzer,
    TextCluster,
)
from analyzers.llm_client import ABORT_MARK, LLMClient
from config import Config
from crawlers import cookie_hosts, crawler_class, get_crawler, is_crawlable
from crawlers.base import UNDER_TARGET, CrawlerStopped, DeadDriver, PageNotArrivedError
from engine.executor import TaskExecutor
from engine.logger import setup_logger
from engine.workflow import WorkflowEngine, effective_workflow, node_label
from i18n import audit, get_lang, normalize, set_lang, t
from services import StatsService, latex_compile, lock_store
from services import net_probe as network_probe
from services.cookie_flow import crawler_hosts, flow_for, normalize_entry_url, retain_for_platform
from services.cookie_manager import CookieManager
from services.data_analysis import LLM_OPS, DataAnalysisService, UnknownOperationError
from services.exporter import DataExporter, UnsupportedFormatError
from services.latex_outputs import build_latex_outputs as _latex_outputs
from services.nodes import execute_compile_node as _execute_compile_node
from services.nodes import execute_name_node as _execute_name_node
from services.nodes import execute_resume_node as _execute_resume_node
from services.nodes import execute_tokenize_node as _execute_tokenize_node
from services.nodes import execute_upload_node as _execute_upload_node
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
    fingerprints_for_workflow,
    workflow_fingerprint,
)
from services.visualizer import ChartConfigError, VisualizationService, chart_engine
from services.workflow_manager import WorkflowManager
from settings_store import get_setting
from utils.helpers import (
    as_bool,
    comment_platforms,
    export_stamp,
    platform_for,
    sanitize_filename,
    split_urls,
    window_tag,
)
from utils.helpers import (
    split_columns as _split_columns,
)

#: The comment router's supported platforms, as raw keys. They go into a
#: ``{platforms}`` slot that localizes *and joins* them, so they must arrive as a
#: sequence — a value pre-joined with '/' reached the console verbatim because the
#: localizer only splits on ',', '、' (never '/', which would mangle a quoted path).
#: Read once because the table is a module constant; a test asserts it stays in step.
_COMMENT_PLATFORMS = tuple(comment_platforms())


def _cloud_requested(argv) -> bool:
    """Whether the command line asked for the cloud shape of this app.

    ``python app.py cloud`` (also ``--cloud``) is the line a systemd unit or a shell alias
    writes, so it is honoured next to the ``CRAWLER_CLOUD=1`` environment variable. Setting it
    here rather than before the imports is safe because every reader asks at CALL time — the
    config payload, the forced headless, the hidden Ollama UI — and nothing freezes it while
    this module is still being imported. A future import-time reader would have to move this up.
    """
    return any(str(arg).strip().lower() in ('cloud', '--cloud', 'cloud-mode', '--cloud-mode') for arg in argv)


if _cloud_requested(sys.argv[1:]):
    Config.CLOUD_MODE = True

app = Flask(__name__, static_folder='static', static_url_path='')
app.config['SECRET_KEY'] = Config.SECRET_KEY
CORS(app)


@app.after_request
def _no_store_ui_assets(resp):
    """Revalidate the DOCUMENT on every load. Flask's own static route already
    answers its files with no-cache, but '/' goes through send_from_directory,
    whose default freshness window is 12 hours — a plain refresh can boot
    yesterday's index.html and every fix shipped since runs invisibly. The
    /js/ and /css/ entries keep the promise explicit rather than inherited:
    this is a local single-user tool, one revalidation per asset costs
    nothing, a stale script costs a wrong diagnosis."""
    path = request.path
    if path == '/' or path == '/index.html' or path.startswith('/js/') or path.startswith('/css/'):
        resp.headers['Cache-Control'] = 'no-cache'
    return resp


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

#: What a status read ships when nobody asks otherwise: the tail the console paints.
#: ``_wf_local``, ``LOG_KEEP`` and the log writers (``add_log``/``_push_log``) now live in
#: ``state.py`` and are imported back above, so the executor modules under ``services/`` can
#: log without importing this Flask module. Only the tail default and its clamp stay here.
CONSOLE_TAIL_DEFAULT = 200


def _status_tail(req) -> int:
    """How many console lines this status read carries — ``?tail=``, clamped to the buffer.

    A page polls for the 200 it renders. A page that was just REFRESHED mid-run asks for
    the whole retained buffer instead, because the lines it lost exist only in this
    process's memory: answering it with 200 would replay the recent part of a run whose
    opening the server could still show. A junk value is the default and not an error —
    this is a nicety on a read-only path, and a run in flight must not be answered a 400
    because someone hand-typed a URL.
    """
    try:
        asked = int(str(req.args.get('tail') or '').strip())
    except ValueError:
        return CONSOLE_TAIL_DEFAULT
    return max(1, min(LOG_KEEP, asked))


class LogBufferHandler(logging.Handler):
    """Feed all logger.info/error/warning calls into execution_state['logs'] for the frontend."""

    def emit(self, record):
        # Transport chatter that is none of the user's business. Werkzeug logs every
        # request; urllib3 logs, per chromedriver HTTP call, "Connection pool is full,
        # discarding connection" and "Retrying (Retry(total=…)) after connection broken
        # by NewConnectionError(.../session/...)". Both fire while a browser is being
        # torn down — killing the driver mid-command makes selenium's own pooled client
        # retry the dead port — so a Stop used to spray several scary-looking red lines
        # that described no real failure. A run that genuinely broke still says so once,
        # through the executor's node-failed line, never through these loggers. The file
        # log keeps every word (root handler's twin); only the UI console is filtered.
        if record.name == 'werkzeug' or record.name.startswith('werkzeug.'):
            return
        if record.name == 'urllib3' or record.name.startswith('urllib3.'):
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


# cookie_manager lives in state.py (imported at top) so the capabilities Blueprint can read it.
workflow_manager = WorkflowManager()
# history_service lives in state.py (imported at top) so a Blueprint can read it.


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
# _dataset_cache is imported from state.py (mutated in place, never rebound).
# The dataset singleton, its lock, the read-through cache helpers (_cache_dataset/_register_dataset/
# _load_dataset/_apply_dataset_meta) and get_dataset_store() now live in backend/stores.py. app
# re-imports the three the routes call and keeps `_dataset_cache` (from state) for its own direct
# pop/clear uses; every cache writer and the store creation still share the one `_DATASET_LOCK`.


# The payload→DataFrame resolution web (_durable_node_rows / NoRunDataError /
# _resolve_dataframe / _resolve_payload_dataframe) now lives in backend/api/resolution.py,
# imported back under these names; every app route call site is unchanged.


# ─── Shared process state ───
# The run's mutable state lives in `backend/state.py` (imported above) so the HTTP layer and
# the test harness share ONE object; it is mutated in place and never rebound. `state`
# carries the field-by-field comments; see docs/ARCHITECTURE.md (Refactor step A).
# _completed_lock lives in state.py (imported above) so the snapshot readers share one lock.
_execute_lock = threading.Lock()  # serializes the guard-and-claim of a new run


def stop_requested() -> bool:
    """Whether 停止 has been pressed for the run in flight.

    Read ``stopping``, NOT ``not running``. The two look interchangeable and are not:
    a helper or a test that calls an executor function directly has no claim in place
    at all, and for it "nobody is running" is not an answer to "did the user end this
    run" — inferring the second from the first made every such call refuse to work.
    ``stopping`` is set only by the Stop handler and cleared when a run claims the slot.
    """
    return bool(execution_state.get('stopping'))


def _record_run_file(ctx: dict | None, node_id: str, path_or_name, kind: str) -> None:
    """Register one export file a run produced, so 智能清除 can later name them all.

    Best-effort by contract: a ledger hiccup must never break an export that already succeeded,
    so everything is guarded — no run context (a direct executor call, a panel render outside a
    run) records nothing, and an exception is swallowed after one console line. Outside a run the
    files still exist and are still listed; they simply cannot be attributed to a record, which is
    correct, because no record wrote them.
    """
    if not ctx:
        return
    store = ctx.get('store')
    run_id = ctx.get('run_id')
    if store is None or not run_id:
        return
    try:
        store.record_file(run_id, node_id, path_or_name, kind)
    except Exception as e:
        logger.debug('run-file ledger failed for %s: %s', path_or_name, e)


def _record_export_stamp(store, run_id: str) -> str:
    """The filename component that names one record, read from the record itself.

    Taken from ``started_at`` and not from the clock, because ``PartWriter`` adopts the
    shards an interrupted attempt already flushed by matching its stem as a prefix: a
    component that moved between attempts would leave those parts orphaned beside a
    numbering that restarted at 001. 继续 never refreshes ``started_at`` — the record's
    date is when this work began — which is exactly the stability this needs.
    """
    record = store.get_run(run_id) or {}
    return export_stamp(record.get('started_at'), run_id)


def _note_window(wf_idx, start, end) -> None:
    """Remember that a crawl in this workflow was asked to walk a time window.

    Recorded at the crawl, where the window is stated, for the save node downstream,
    which receives only a table and cannot ask. Blank and unparseable pairs are not
    recorded at all: the crawler refuses those itself, and a half-window must not become
    half a filename.

    What is kept is the formatted tag rather than the two strings as typed, because
    「2026-1-1」 and 「2026-01-01」 are the one stretch, and storing the spellings would
    refuse a file there is nothing ambiguous about.
    """
    tag = window_tag(start, end)
    if not tag:
        return
    found = execution_state['_time_windows'].setdefault(wf_idx, [])
    if tag not in found:
        found.append(tag)


def _window_for_save(wf_idx) -> tuple:
    """``(tag, refusal)`` — the time window this workflow's file can honestly name.

    One window is the case the user asked for. Zero is a workflow that never asked for a
    range, so 「文件名带时间范围」 has nothing to print; two different ranges is a canvas
    whose single file cannot say which of them it holds. Both answer with the sentence
    rather than a guess, because a filename is a name being chosen — and a saved table
    quietly labelled with the wrong month is worse than one that was not written.
    """
    found = execution_state['_time_windows'].get(wf_idx) or []
    if not found:
        return '', t('export.window_none')
    if len(found) > 1:
        return '', t('export.window_many', n=len(found))
    return found[0], ''


# _results_snapshot lives in state.py (imported above) so a read-only Blueprint can take a
# stable copy of execution_state['results'] without importing the whole Flask module.


# ─── Durable run state ──────────────────────────────────────────
# The run ledger + housekeeper singletons, their locks and get_run_store()/get_housekeeper()
# now live in backend/stores.py (imported back near the top). They are reached here through
# those getter names so a test that patches app.get_run_store still intercepts these calls.


def __getattr__(name):
    """Delegate the three store singletons to ``stores`` (PEP 562 module ``__getattr__``).

    ``_RUN_STORE``/``_DATASET_STORE``/``_HOUSEKEEPER`` are no longer app globals — they are
    rebound per test on ``stores`` by ``conftest``. ``app._RUN_STORE`` still has to answer,
    because ~118 test reads (plus the resume/live harness) reach it as an app attribute, so
    read it through to the live ``stores`` value. A store-object WRITE must target ``stores``
    (see its module docstring); setting ``app._RUN_STORE`` here would shadow this delegation
    and silently detach the reader from the injected store.
    """
    if name in ('_RUN_STORE', '_DATASET_STORE', '_HOUSEKEEPER'):
        import stores

        return getattr(stores, name)
    if name == '_dataset_cache':
        # The dataset read-through cache lives in ``state`` (it moved out with the store
        # helpers); ``conftest`` still empties it as ``app._dataset_cache``, so answer from
        # its real home. ``clear()`` mutates in place — no rebinding, same object.
        import state

        return getattr(state, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def _as_run_ids(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    return [str(v) for v in (value or []) if str(v)]


def _locked_run_ids() -> set[str]:
    """Run ids the user pinned (置顶). Retention — automatic *or* manual — must spare
    them, exactly as 清空/删除 already do; otherwise a lock silently dies to age."""
    return {str(k) for k in (lock_store.all_locks().get('runs') or [])}


def _prune_orphan_run_locks() -> None:
    """Forget 置顶 keys whose run row no longer exists. A record can be removed by a
    path that did not drop its lock; without this, locks.json accumulates dead ids."""
    with contextlib.suppress(Exception):
        existing = get_run_store().run_ids()
        for key in _locked_run_ids():
            if key not in existing:
                lock_store.drop('runs', key)


def _housekeep(exclude_run_id='', force: bool = False):
    """Apply the retention settings, containing every failure.

    A cleanup problem must never be what makes a run look failed, so nothing
    here propagates. ``exclude_run_id`` protects the record the caller is still
    writing — dropping its rows mid-run would destroy live state. It takes a
    sequence too, because a serial multi-workflow run closes one record per
    workflow and all of them are the state that was just built. The automatic
    sweep also spares every 置顶 record (the user's directive: a pin that only
    stopped a manual delete but not the age-based sweep is not a pin)."""
    keep = _as_run_ids(exclude_run_id) + sorted(_locked_run_ids())
    with contextlib.suppress(Exception):
        if force:
            get_housekeeper().run_now(exclude_run_id=keep)
        else:
            get_housekeeper().maybe_run(exclude_run_id=keep)
        # The chart backend is never touched by the runs.db sweep (it keys on its own
        # id), so age its metric rows here — otherwise it grows forever and plots
        # trends for crawls whose data is long gone.
        history_service.purge_older_than(Config.RUN_KEEP_DAYS)
    _prune_orphan_run_locks()


def _close_run(ctx: dict, outcome: str):
    """Record how a run ended.

    Never raises: losing the record must never lose the run itself — the rows were
    already safely in the database, this says only whether they are complete.

    But it does not swallow the failure *silently* either. A row left on 运行中 is read
    back as "still crawling", the resume banner will not offer it, and the only repair
    was restarting the service — measured, and it is why pressing 停止 used to look
    slower than a restart. The console therefore says which record it could not close,
    and `/api/runs/list` settles it on the next panel read (see ``run.reconciled``).

    Serial mode with several workflows opens one record per workflow, and each is
    closed with its own verdict the moment its workflow's turn ends; what is left
    standing here is the record that was still executing when the run exited, and
    the single-record case, where the whole run shares one verdict.
    """
    # ``open_records`` is set as soon as a record is opened, so a run that closed
    # every workflow it started arrives here with an EMPTY list — which means
    # nothing to close, not "close the run's own id" (that row may not exist at
    # all after the split, and re-writing a verdict over a workflow that already
    # got its own would be the worse mistake).
    records = ctx.get('open_records')
    with _completed_lock:
        attempted = set(execution_state['attempted_nodes'])
    for run_id in records if records is not None else [ctx['run_id']]:
        try:
            ctx['store'].settle_nodes(run_id)
            ctx['store'].finish_run(run_id, outcome, attempted=attempted)
        except Exception as e:
            add_log(t('run.recordWriteFailed', rid=run_id, err=e))
    if records is not None:
        records[:] = []


def _item_scope(ctx: dict, node: dict) -> str:
    """Namespace for "have I crawled this already?".

    The node fingerprint, not the run id: an item collected once under this
    keyword must not be collected again by the next attempt, or by another
    workflow that asks the same question. That is what keeps a resumed crawl
    from handing back duplicates.
    """
    return 'item:' + str((ctx.get('fingerprints') or {}).get(node.get('id') or '', ''))


def _op_needs_llm(op: str, params: dict) -> bool:
    """Whether this node's own choice will call a language model.

    Read through the declared default the panel shows (``PROCESS_ENUMS``), because a blank
    field means "not stated", not "not the model": an ``emotion`` node left empty IS an LLM
    run, while an empty ``sentiment`` node is SnowNLP and costs nothing. The test this
    replaces was ``mode != 'ml'``, which charged a row-by-row model pass to every node whose
    mode said something else — and a cloud host then refused the whole run for a missing API
    key that no node in it had asked for.

    ``clean`` used to be listed here as an operation that always calls a model. It has a
    mode of its own now, and its regex mode washes a Weibo comment without asking anyone —
    so the answer comes from that same table instead of from a hard-coded membership, and
    the two can no longer disagree.
    """
    spec = PROCESS_ENUMS.get(op) or {}
    if 'mode' not in spec:
        return False
    default, allowed = spec['mode']
    raw = str(params.get('mode') or '').strip()
    value = raw if raw else default
    # Only the mode that NAMES the model needs one. An unrecognised mode is not treated as
    # a model call either: it is refused BY NAME when the node runs, and answering "a key
    # is required" here would send the user to configure credentials for a definition
    # whose actual problem is a spelling.
    return value == 'llm'


def _workflow_needs_llm(workflow: dict) -> bool:
    """True when any process node in the payload will actually call a model.

    Cleaner always does; the three classifiers and entity recognition only when the node
    picked the model. A crawl-and-save workflow must not be blocked by a missing API key or
    an unpicked Ollama tag — the frontend makes the same distinction (``nodeNeedsLlm``)
    before it opens the console, and both read one table of which mode means which model.
    """
    for node in workflow.get('nodes') or []:
        if not isinstance(node, dict) or node.get('type') != 'process':
            continue
        params = node.get('params') or {}
        op = str(params.get('operation') or node.get('operation') or '')
        if _op_needs_llm(op, params):
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
    # Per-node model override: a node may pick its own Ollama tag, but the
    # transport (provider/host/key) stays run-level. Only Ollama is overridable —
    # an OpenRouter run must not be handed a daemon tag it has no id for — and a
    # blank node model falls back to the run's global model.
    node_model = str((node.get('params') or {}).get('model') or '').strip() if provider == 'ollama' else ''
    client = LLMClient(
        provider=provider,
        model=node_model or (cfg.get('model') or ''),
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
    if as_bool((node.get('params') or {}).get('live_export')):
        from services.part_writer import SnapshotWriter, safe_stem

        stem = safe_stem(f'{execution_state.get("workflow_name") or "llm"}-{node_id}')
        lfmt = 'json' if str((node.get('params') or {}).get('format') or 'csv') == 'json' else 'csv'
        live_writer = SnapshotWriter(Config.EXPORT_DIR, stem, lfmt)
        add_log(t('run.live_export', file=os.path.basename(live_writer.path)))
        # The live file has one fixed name from the moment it is made, so it is registered once
        # here rather than on every batch's rewrite — it is a run artifact and 智能清除 must find it.
        _record_run_file(ctx, node_id, live_writer.path, 'live')

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
        # A run-level, per-node cancellation ledger the executor also reads. The
        # direct analyzers leave 未处理 in their rows for the executor's scan, but
        # NER transforms that marker away; the shared dict (identity survives the
        # analyzer's shallow ``dict(ctx)`` copy) lets the row runner report "this
        # node was stopped mid-way" so no LLM node settles DONE on skipped rows.
        run_ctx['node_id'] = node_id
        run_ctx['cancel_book'] = ctx.setdefault('node_cancelled', {})
    return run_ctx


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


# _json_body and _bad_body live in api.http now (imported at top) so a Blueprint can use them
# without importing the whole Flask module. _bad_param stays: only app.py routes reach it.


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
    if execution_state['running']:
        # Loading overwrites the live run's ambient name and fingerprint (below),
        # so a second tab opening a file mid-run would re-key the record of a
        # crawl that is still writing rows. The panel asks first; this is the
        # loud line that holds even when it does not.
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 409
    workflow = workflow_manager.load(name)
    if not workflow:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    # Reconnect the nodes with their files *before* the canvas draws them, so
    # the workflow it returns is the runnable one.
    datasets = _restore_workflow_datasets(name, workflow)
    execution_state['workflow_name'] = str(workflow.get('name') or name or '')
    execution_state['fingerprint'] = workflow_fingerprint(effective_workflow(workflow))
    return jsonify({'ok': True, 'workflow': workflow, 'datasets': datasets})


@app.route('/api/workflow/list', methods=['GET'])
def list_workflows():
    # Objects, not bare stems: the management panel shows node/dataset counts and
    # a modified time per file, which is what makes 打开/重命名/删除 an informed
    # choice instead of a name-blind file picker.
    return jsonify({'ok': True, 'workflows': workflow_manager.describe()})


@app.route('/api/workflow/rename', methods=['POST'])
def rename_workflow():
    data = _json_body()
    if data is None:
        return _bad_body()
    for field in ('name', 'new_name'):
        if not isinstance(data.get(field), str):
            return _bad_param(field)
    old = _request_workflow_name(data.get('name'))
    new = _request_workflow_name(data.get('new_name'))
    if old is None or new is None:
        return jsonify({'ok': False, 'error': t('api.workflowNameRequired')}), 400
    if old == new:
        return jsonify({'ok': False, 'error': t('api.workflowNameSame')}), 400
    if execution_state['running'] and str(execution_state.get('workflow_name') or '') == old:
        # Renaming the canvas that is mid-run would re-key the record it is
        # writing; the panel refuses first, this holds the line regardless.
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 409
    if os.path.exists(workflow_manager._path_for(new)):
        return jsonify({'ok': False, 'error': t('api.workflowNameTaken', name=new)}), 409
    moved = workflow_manager.rename(old, new)
    if moved is None:
        # Unlike delete (idempotent), a rename of a missing file is a lost edit.
        return jsonify({'ok': False, 'error': t('api.workflowMissing', name=old)}), 404
    refs = get_dataset_store().move_workflow(old, new)
    logger.info(t('api.workflowRenamed', old=old, new=new))
    return jsonify({'ok': True, 'name': new, 'path': workflow_manager._path_for(new), 'datasets': refs})


@app.route('/api/workflow/delete', methods=['POST'])
def delete_workflow():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = _request_workflow_name(data.get('name', ''))
    if name is None:
        return jsonify({'ok': False, 'error': t('api.workflowNameRequired')}), 400
    if lock_store.is_locked('workflows', name):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
    workflow_manager.delete(name)
    lock_store.drop('workflows', name)
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

#: Queued requests live in memory only (see state._RUN_QUEUE). A restart drops them, which is
#: the honest behaviour for a list of intentions nobody is here to confirm.
QUEUE_MAX = 8

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


# _local_transport_refusal lives in transport.py (imported at top); the run executor (via
# _cloud_refusal_response below) and the /api/llm/* Blueprint both call that one function.


def _cloud_refusal_response(provider: str) -> dict:
    """The 400 body for :func:`_local_transport_refusal`, shaped per caller."""
    return {'status': 400, 'body': {'ok': False, 'error': _local_transport_refusal(provider)}}


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
            # A cloud host has no display, so headless is not a preference here — the
            # browser would never come up. The panel hides the switch (it is told the
            # server's shape by /api/config), but the run record is written from THIS
            # value, and a record that said 「窗口」 for a crawl that could only have run
            # headless would be a chip describing a run that never happened.
            headless = True if Config.CLOUD_MODE else settings.get('headless', True)
            # A parallel run holds at most one browser per concurrently-running workflow,
            # so the pool width IS the "max simultaneous browsers" lever. It used to be
            # the hardcoded Config.DEFAULT_MAX_WORKERS for both shapes; it is now a user
            # setting chosen by how this run browses — headless is cheap and can go wide,
            # a windowed run shows real Chrome windows the machine must paint. An explicit
            # per-run max_workers from the request still wins (it is absent today).
            _cap_key = 'max_headless_browsers' if as_bool(headless) else 'max_visible_browsers'
            _cap_default = _safe_int(get_setting(_cap_key), Config.DEFAULT_MAX_WORKERS, minimum=1, maximum=16)
            max_workers = _safe_int(settings.get('max_workers'), _cap_default, minimum=1, maximum=16)
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
            effective = effective_workflow(workflow)
            # Only an ENABLED name node names the run: a workflow whose nodes are switched
            # off is, to this run, not on the canvas (the engine's effective graph drops it),
            # so its label must not appear in the record — and the skipped-name list below is
            # exactly the complement.
            for _node in effective.get('nodes') or []:
                if _node.get('type') != 'name':
                    continue
                _label = str((_node.get('params') or {}).get('workflow_name') or '').strip()
                if _label and _label not in labels:
                    labels.append(_label)
            if labels:
                workflow_name = ' + '.join(labels)
            execution_state['workflow_labels'] = labels
            # The complement of the above over the FULL canvas: a name node the user drew but
            # switched OFF (its own flag, or its whole type) is absent from the effective graph,
            # so its workflow runs nothing and owns no node rows. Naming it on the record is what
            # keeps 跳过 visible — otherwise the run reads as if the canvas had fewer workflows
            # than the user actually built, and a switched-off one looks like it was never there.
            # An unnamed disabled workflow has no label to show and so is not listed (it would
            # only ever be reported as 工作流 N elsewhere, which already reflects the effective set).
            full_labels = []
            for _node in workflow.get('nodes') or []:
                if _node.get('type') != 'name':
                    continue
                _label = str((_node.get('params') or {}).get('workflow_name') or '').strip()
                if _label and _label not in full_labels:
                    full_labels.append(_label)
            execution_state['skipped_workflow_labels'] = [lab for lab in full_labels if lab not in labels]
            # Recorded so a preview can find this workflow's rows in the store once the
            # live results are gone (a refresh, a restart) rather than guessing from a
            # node id alone — "node-2" exists in every workflow.
            execution_state['workflow_name'] = workflow_name
            execution_state['fingerprint'] = workflow_fingerprint(effective)

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
                # Refused BEFORE the requirements below: on a cloud host a missing key is
                # not the problem worth reporting, the transport is. Asking the user for an
                # OpenRouter key while running their local-daemon request against a port
                # nothing listens on is how a run "completes" with no analysis at all.
                if _local_transport_refusal(llm['provider']):
                    return _cloud_refusal_response(llm['provider'])
                if llm['provider'] == 'openrouter':
                    if not llm['api_key']:
                        return {'status': 400, 'body': {'ok': False, 'error': t('api.needApiKey')}}
                    if not llm['model']:
                        return {'status': 400, 'body': {'ok': False, 'error': t('api.needModel')}}
                elif not llm['model']:
                    return {'status': 400, 'body': {'ok': False, 'error': t('api.needOllamaModel')}}

            cancel_event = threading.Event()
            execution_state['cancel_event'] = cancel_event
            # A fresh claim clears the last run's stop: it ended the moment its
            # worker wrote the verdict, and this run must not inherit a "stopping"
            # that would freeze its own Stop detection.
            execution_state['stopping'] = False
            execution_state['results'] = {}
            reset_console_state()
            # Node ids THIS attempt visited. The run record outlives the canvas:
            # nodes deleted between attempts keep their stored status, so any
            # verdict read from the whole record can blame a finished run for a
            # failure that belonged to an older shape of the workflow.
            execution_state['attempted_nodes'] = set()
            execution_state['stopped_node_ids'] = set()
            # The list object the worker's `ctx` will also hold, so 停止 can write to
            # exactly the rows this run owns and a later reconciler can tell an
            # unwinding worker's rows from a dead one's.
            execution_state['open_records'] = []
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
        # the canvas for every line. The same name is what the run record groups
        # its nodes by, so the panel and the console never call one workflow two
        # things; it travels on the thread-local because a node is recorded deep
        # inside this thread's call stack, where no argument carries it.
        wf_name = _wf_display_name(wf_engine, wf_idx)
        _wf_local.name = wf_name
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
        # Bound BEFORE the try: the finally reaches for it on every exit, and a
        # failure before the store opened (a refused runs.db, a Stop caught in
        # the first moments) used to raise UnboundLocalError *inside the
        # finally* — skipping the rest of it: the queue never got the slot back,
        # the log tee stayed over every later request's stdout. A stop that will
        # not finish is exactly the stall this whole path exists to avoid.
        created: list = []
        try:
            store = get_run_store()
            # Structure identity is taken on the effective graph, so it agrees with the key
            # the resume banner matches on (:func:`effective_workflow`) — disabling a node and
            # re-enabling it returns to the same identity, and a disabled node is absent from
            # both this fingerprint and the per-node fingerprints below.
            effective = effective_workflow(workflow)
            wf_fp = workflow_fingerprint(effective)
            ctx = {
                'store': store,
                'run_id': run_id,
                'resume': bool(resume_run_id),
                'fingerprints': fingerprints_for_workflow(effective),
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

            # ─── one record per execution, or one per workflow? ────────────────
            # Serial mode runs the workflows one after another, so a workflow that
            # never got its turn has nothing to record: in serial mode every workflow
            # that STARTS opens its own row and closes it with its own verdict when its
            # turn ends. Parallel mode runs them as one piece of work, so it keeps the
            # single row named 'A + B'. Both spellings store the CANVAS fingerprint,
            # because that is the key the resume banner and /api/runs/resumable match
            # on — separating the records without separating that key is what keeps
            # 继续 findable after the split.
            split_records = mode == 'serial' and wf_count > 1
            # The named workflows the user switched off for this attempt. A disabled workflow is
            # not an effective component, so it opens no row on its own — the record's only trace
            # of it is this list, which is what lets the panel say "X ran, Y was skipped" instead
            # of the canvas silently looking like it had one fewer workflow.
            skipped_str = ' + '.join(execution_state.get('skipped_workflow_labels') or [])
            if skipped_str:
                # Say it out loud: a run of fewer workflows than the canvas drew must name who is
                # sitting this one out, or the user reads a silent omission as a lost record.
                add_log(t('run.skippedWorkflows', names=skipped_str))
            created = []  # rebind the outer pre-name so the finally always sees a list
            # THE SAME list object the claim put in `execution_state`: 停止 reads it from
            # the request thread, so a rebind here would leave it writing to a list
            # nobody is looking at.
            ctx['open_records'] = execution_state['open_records']
            if not split_records:
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
                    skipped_workflows=skipped_str,
                )
                created.append(run_id)
                ctx['open_records'].append(run_id)
                execution_state['owned_records'].add(run_id)
                # Read *after* start_run so nodes left 'running' by the promotion
                # are visible as partial, which is what makes them resumable.
                ctx['statuses'] = store.node_statuses(run_id)
                ctx['export_stamp'] = _record_export_stamp(store, run_id)
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

            # Finished rows count too: 继续 on a row the panel offers is "run this
            # again from its checkpoints", and that has to land on the same row rather
            # than beside it — which is exactly what the single-record case does.
            resumable = (
                store.list_resumable(fingerprint=wf_fp, limit=50, include_finished=True) if split_records else []
            )
            resuming = bool(resume_run_id)

            def _continue_record(name: str) -> dict:
                """The row this workflow should keep writing, if it is a 继续.

                Only the resume path adopts: the attempt after a 继续 must accumulate
                onto the rows that already exist, so it finds each workflow's own
                unfinished row of this canvas again instead of opening a fresh one per
                press. A plain Run is a new attempt and gets new rows — "one record per
                attempt" is what makes the panel's history mean anything.
                """
                if not resuming:
                    return {}
                for candidate in resumable:
                    if str(candidate.get('workflow_name') or '') == name:
                        return dict(candidate)
                return {}

            def _component_run(index, sub_engine):
                """Open this workflow's own record and return the context its nodes run
                under. Called as the turn arrives, which is what makes an unreached
                workflow leave no record at all — the point of the split.

                Workflow zero takes the id the HTTP response already handed out, so the
                browser, the status endpoint and the resume banner all name a row that
                exists. The others are minted as they are reached.
                """
                name = _wf_display_name(sub_engine, index)
                earlier = _continue_record(name)
                rid = str(earlier.get('run_id') or '') or (run_id if index == 0 else uuid.uuid4().hex[:12])
                store.start_run(
                    rid,
                    name,
                    wf_fp,
                    mode=mode,
                    headless=headless,
                    llm=execution_state['llm'],
                    lang=execution_state.get('lang'),
                    node_total=len(sub_engine.nodes),
                    wf_count=1,
                    skipped_workflows=skipped_str if index == 0 else '',
                )
                created.append(rid)
                ctx['open_records'].append(rid)
                execution_state['owned_records'].add(rid)
                # The status endpoint and the resume banner follow the record that is
                # being written RIGHT NOW, so a stop mid-run leaves the panel offering
                # the workflow that was interrupted rather than the first one.
                execution_state['run_id'] = rid
                if earlier:
                    saved = sum(int(n.get('row_count') or 0) for n in earlier.get('nodes') or [])
                    add_log(t('run.resume_from', at=earlier.get('started_at') or '?', rows=saved), wf_idx=index)
                else:
                    add_log(t('run.started', rid=rid), wf_idx=index)
                return dict(
                    ctx,
                    run_id=rid,
                    resume=bool(earlier),
                    # Read after start_run, for the same reason as above: nodes the
                    # promotion left 'running' must read as partial to be resumable.
                    statuses=store.node_statuses(rid),
                    # Per RECORD, not per canvas: in a split run each workflow owns a row,
                    # and its files should carry the minute that row began.
                    export_stamp=_record_export_stamp(store, rid),
                )

            def _close_component_record(sub_engine, sub_ctx: dict) -> None:
                """Give one workflow its own verdict, the moment its turn ends.

                The run-level finish line below can only speak for the whole canvas,
                and after the split there is no whole-canvas row to speak for: each
                workflow's row is closed here, so a canvas whose second workflow was
                stopped while the first finished shows 已完成 and 已中断 side by side
                instead of one verdict smeared over both.
                """
                rid = sub_ctx['run_id']
                store.settle_nodes(rid)
                statuses = store.node_statuses(rid)
                with _completed_lock:
                    visited = set(execution_state['attempted_nodes'])
                    still_running = bool(execution_state['running'])
                broken = sum(
                    1
                    for nid, state in statuses.items()
                    if nid in visited and state.get('status') in (NODE_FAILED, NODE_PARTIAL)
                )
                outcome = RUN_INTERRUPTED if not still_running else (RUN_FAILED if broken else RUN_COMPLETED)
                store.finish_run(rid, outcome, attempted=visited)
                with contextlib.suppress(ValueError):
                    ctx['open_records'].remove(rid)

            if mode == 'serial' or wf_count <= 1:
                # ── Serial: one workflow at a time ──
                all_results = {}
                for wf_idx, se in enumerate(sub_engines):
                    if not execution_state['running']:
                        break
                    sub_ctx = _component_run(wf_idx, se) if split_records else ctx
                    # Tagged with its OWN index: this line is printed before
                    # _run_single_workflow sets the thread-local, so it used to be
                    # filed under the *previous* component's tab — workflow A's
                    # console announcing 「开始执行工作流「B」」.
                    add_log(t('wf.starting', name=_wf_display_name(se, wf_idx)), wf_idx=wf_idx)
                    try:
                        results = _run_single_workflow(se, wf_idx, sub_ctx)
                    finally:
                        # Released, not left standing. Serial mode runs in the RUN
                        # thread, so the index of the component that just finished
                        # would otherwise route every later run-level line — the
                        # finish line, 存储不可用, the queue hand-off — into that one
                        # workflow's tab instead of the shared console, and every
                        # node recorded after it into that one workflow's group.
                        _wf_local.idx = None
                        _wf_local.name = ''
                    if split_records:
                        _close_component_record(se, sub_ctx)
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
                        _wf_local.name = ''

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
                # `wait=True`, and this is the reason the whole branch exists: the run
                # thread that passes this line goes on to clear `running`, settle the
                # record and hand the queue to the NEXT run, whose console, node
                # counters and `results` dict are the same objects these threads are
                # still writing to. `cancel_futures` drops the workflows that never
                # started; the ones that did must finish what they are inside, which
                # `/api/workflow/stop` makes short by closing their crawlers.
                pool.shutdown(wait=True, cancel_futures=True)

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
            # ``created`` is the record this execution actually wrote: one row for a
            # parallel or single-workflow run, one per workflow that got its turn in a
            # serial one. Settling them all and merging the statuses is what lets the
            # single finish line below still speak for the canvas.
            statuses = {}
            for rid in created:
                store.settle_nodes(rid)
                statuses.update(store.node_statuses(rid))
            with _completed_lock:
                attempted = set(execution_state['attempted_nodes'])
                stopped = set(execution_state['stopped_node_ids']) & attempted
            broken = sum(
                1
                for nid, state in statuses.items()
                if nid in attempted and nid not in stopped and state.get('status') in (NODE_FAILED, NODE_PARTIAL)
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
            # A stop is not a failure, and counting the nodes it cut as failures made
            # every stopped run read as a broken workflow — the one claim on that line
            # the user caused themselves.
            if stopped:
                finish_line += t('run.finished.stopped', n=len(stopped))
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
            # The stop is answered as of this line, not "sometime after": `stopping`
            # is what `stop_requested()` reads, and leaving it set for a settled run
            # would make the next helper that calls an executor function directly
            # refuse to work over a run that finished two hours ago.
            execution_state['stopping'] = False
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
            _housekeep(exclude_run_id=list(created) or [run_id])
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

    # Named 'run' so the process-monitor's kill guard (see ``kill_process``) actually
    # matches: it refuses to inject SystemExit into ('MainThread', 'run'), but an
    # unnamed thread reported as "Thread-N" and a stray click on the live run worker
    # could raise SystemExit between acquiring a browser and registering it, orphaning
    # a Chrome and holding its profile lock for the full timeout.
    try:
        execution_state['thread'] = threading.Thread(target=run, daemon=True, name='run')
        execution_state['thread'].start()
    except Exception as e:
        # A thread that never started never runs its finally, so the claim would stay
        # held: ``running`` stuck True, ``_settle_orphaned_records`` (which skips a
        # running slot) never helps, and every later 运行 parks forever. Give the slot
        # back and let the queue drain instead.
        execution_state['thread'] = None
        execution_state['running'] = False
        execution_state['stopping'] = False
        # One console line, localized; logger.exception keeps the traceback in the
        # file. add_log of the same text here would print the failure twice.
        logger.exception(t('run.start_failed', err=e))
        _start_next_queued()
        return {'status': 500, 'body': {'ok': False, 'error': str(e)}}

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


def _is_collision(crawler, resume) -> bool:
    """Whether a refusal reads as "two of our own crawls met at the door".

    Three conditions, each removing a different false alarm: the platform really
    bounced us, nothing was collected (so there is no paid-for work to duplicate and
    no cursor to rewind), and the run still wants its rows (a Stop is not a pause —
    retrying after it would crawl on behind a run already declared over).
    """
    return bool(
        getattr(crawler, 'login_wall', False)
        and not crawler.collected()
        and not resume
        and execution_state['running']
        and Config.WALL_RETRY_BACKOFF > 0
    )


def _backoff_for_retry(crawler, platform: str) -> bool:
    """Say it once, wait out the back-off, and answer whether a retry is still wanted.

    The two flags the previous attempt set are cleared so the retry can report a wall
    of its own. The wait is slice-checked against 停止, not one long ``sleep``: this is
    the one place a stopped run could still be sitting when the user pressed Stop, and
    a sleep that ignores it both delays the run-record verdict by up to
    ``WALL_RETRY_BACKOFF`` and lets the caller open a second browser for a run already
    declared over. False means "the user stopped us — do not retry".
    """
    add_log(t('run.wallRetry', platform=platform, n=int(Config.WALL_RETRY_BACKOFF)))
    cancel = execution_state.get('cancel_event')
    interrupted = False
    deadline = time.monotonic() + float(Config.WALL_RETRY_BACKOFF)
    while time.monotonic() < deadline:
        if not execution_state['running']:
            interrupted = True
            break
        if cancel is not None and cancel.wait(min(0.5, max(0.0, deadline - time.monotonic()))):
            interrupted = True
            break
    # The retry gets a clean slate whether or not the wait was cut short: the flags
    # describe the attempt that just failed.
    crawler.login_wall = False
    crawler.risk_blocked = False
    crawler.unreachable = False
    return not interrupted


def _crawl_with_collision_retry(crawler, handler, crawl_args: dict, resume: dict, platform: str):
    """One trip to the platform, plus the second attempt a collision deserves.

    A wall met before the first row is the shape two same-platform workflows make of
    each other — measured: weibo answers the second session of one account with a
    passport redirect inside the same second. Backing off once and trying again is the
    difference between a red node and a green one.

    A wall met *after* rows were collected is the other event entirely: a cookie dying
    mid-crawl. That one must not be retried here — it settles the node partial, fails
    the run and hands the user the 继续 banner, which is the path that keeps the rows
    already paid for. The wait happens **inside** the platform's turn (see
    ``crawl_gate.hold`` in :func:`_execute_node`), or a retry would queue up behind
    the very workflow it is waiting for.
    """
    try:
        rows = handler(**crawl_args, resume=resume)
    except BaseException:
        if not _is_collision(crawler, resume):
            raise
        if not _backoff_for_retry(crawler, platform):
            raise
        return handler(**crawl_args, resume=resume)
    if not rows and _is_collision(crawler, resume) and _backoff_for_retry(crawler, platform):
        rows = handler(**crawl_args, resume=resume)
    return rows


#: Which sentence each diagnosis answers. ``'slow'`` is deliberately the fall-through:
#: it is the one verdict that admits nothing was found, and a message that named a cause
#: here would be a guess wearing the authority of a probe.
_NET_ADVICE_KEYS = {
    'region': 'net.region',
    'offline': 'net.offline',
    'blocked': 'net.blocked',
    'slow': 'net.slow',
}


def _net_advice(platform: str) -> str:
    """What this machine can say about its own network, in the run's language.

    Asked only after a page went unmatched for the whole patience budget, which is what
    makes the cost defensible: two control hosts and one 2 s throughput sample, on the
    path where the run has already lost minutes. The controls are why this is worth
    asking at all — without a host that *should* answer for comparison, "switch network"
    is a guess, and the user is entitled to know which of the two it is.
    """
    diagnosis = network_probe.diagnose(capabilities.region_of(platform), platform)
    key = _NET_ADVICE_KEYS.get(str(diagnosis.get('verdict')), 'net.slow')
    speed = diagnosis.get('speed_kbps')
    return t(key) + (t('net.speed', speed=speed) if speed else '')


def _page_not_arrived(platform: str, exc: PageNotArrivedError) -> ValueError:
    """Turn one crawler's observation into a line that says what to do next.

    The crawler's own sentence is about a page ("no cards after N seconds at this
    address"); this adds the only fact that sentence cannot carry, which is whether the
    machine running it can reach anything at all. The node label and the 「执行失败」 frame
    come from the executor, so nothing is said twice.

    No advice is appended when the page already explained itself — a login wall, a captcha
    or the browser's own ``net::ERR_…`` token are each a named cause, and a network probe
    on top of one of them would be a second opinion about something already measured.
    """
    advice = ''
    if exc.verdict in ('', 'ok', 'breaker'):
        with contextlib.suppress(Exception):
            # A probe that cannot run must not become the reason a crawl cannot report.
            advice = _net_advice(platform)
    streak = t('run.pageStreak', n=exc.gave_up) if exc.gave_up > 1 else ''
    if not (advice or streak):
        return ValueError(str(exc))
    return ValueError(t('run.pagePending', page=str(exc), streak=streak, advice=advice))


def _feed_parent_rows(upstream: list) -> list | None:
    """The first parent that actually carries a data table, or None.

    ``name → source`` is the labelling pattern this canvas has always had, and a
    name node produces no rows — so "has any wire in" cannot mean "has a feed".
    The feed is the first parent whose result is a non-empty list of dict rows,
    whatever its position in the connection order.
    """
    for _pid, rows in upstream or ():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return rows
    return None


def _column_to_links(rows: list, column: str) -> tuple[list[str], int]:
    """A column read row by row into a link list: (links, skipped-empty-cells).

    Blank/missing cells are counted, not guessed at; a cell holding several links
    is split exactly like the pasted textarea would be (one coercion, ``split_urls``).
    First-occurrence dedupe is what keeps the resume cursor honest: the comment
    engine stores ``url_index`` BY POSITION, so the list a resumed run rebuilds
    from the same parent rows must be identical — and a duplicated link would
    otherwise pay for the same article twice inside one node.
    """
    links: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for row in rows:
        cells = split_urls(row.get(column))
        if not cells:
            skipped += 1
            continue
        for u in cells:
            if u not in seen:
                seen.add(u)
                links.append(u)
    return links, skipped


def _name_parts(params: dict, stamp: str = '') -> str:
    """The filename components a crawl appends to its own name, in order.

    Two facts that used to live only in the node's form: which stretch of the calendar
    the crawl was asked to walk, and (on request) which record is writing these files.
    Empty answers stay empty rather than becoming a stray separator, and the stamp is
    handed in rather than read from the clock — see ``_record_export_stamp`` for the
    prefix a moving stamp would break.
    """
    window = window_tag(params.get('start_time'), params.get('end_time'))
    run = (stamp or '') if as_bool(params.get('part_timestamp')) else ''
    return window + run


def _execute_source_node(node: dict, headless: bool, ctx: dict = None, upstream: list = None):
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
    # A link-list mode fed from an upstream column: the column's values become the
    # field's list here, once, so the comment engine and wechat's article reader
    # crawl exactly the rows the user wired in without either knowing feeding exists.
    # The matrix decides feedability (Field.fed_by) — this executor holds no second
    # opinion about which modes take a feed, and validation already refused the
    # mismatched shapes (wired-without-column, column-without-wire, non-fed mode
    # with a table). Column wins over the pasted list: merging would make the
    # positional url_index cursor unrebuildable on resume, and an article present in
    # both lists would be paid for twice. Operating on copies never writes back —
    # the node's stored params are the user's textarea, not this run's input set.
    feed = capabilities.feed_of(mode)
    parent_rows = _feed_parent_rows(upstream)
    if feed and parent_rows is not None:
        fed_field, col_key = feed[0]
        column = str(params.get(col_key) or '').strip()
        if column:
            if column not in {str(c) for c in parent_rows[0]}:
                # Fail BY NAME at the row source, like validate_step does for a
                # process column: an empty table here would read as "the feed found
                # nothing", not as "the user's column name is wrong".
                raise ValueError(
                    t('source.feed_column_missing', nid=node_label(node, str(node.get('id') or '')), col=column)
                )
            fed, skipped = _column_to_links(parent_rows, column)
            if skipped:
                add_log(t('source.feed_skipped', n=skipped))
            if not fed:
                raise ValueError(t('comment.no_urls', platforms=_COMMENT_PLATFORMS))
            params = dict(params)
            params[fed_field.key] = fed
            node = dict(node, params=params)
    if mode.handler == 'comments':
        # Same engine as the standalone Comment node — which stays valid for the
        # canvases that used to own it.
        return _execute_comment_node(dict(node, type='comment'), headless=headless, ctx=ctx)
    crawl_args = capabilities.crawl_kwargs(mode, params)
    # The account is the executor's own field (like recrawl it stays out of crawl_args):
    # it chooses WHICH session and WHICH browser device the crawl runs as — two accounts
    # of one platform are two devices, so two nodes can crawl in real parallel instead
    # of queueing behind one rate limit. Blank is the historical default account.
    account = str(params.get('account') or '').strip()
    # A mode without a row budget (WeChat's article list) promised no number, so
    # nothing can be missing from it: the cookie-wall check below reads zero as
    # "this crawl ended where it was meant to" instead of inventing a target.
    target_count = crawl_args.get('target_count') or 0

    # No source node forces a visible window any more. Douyin and X used to (a headless browser
    # got a captcha/403), but a headless Chrome now reports a desktop fingerprint instead
    # (base.py, #148) — measured serving real rows on both, and on zhihu's author page — so the
    # run's own 无头/窗口 choice is honoured as asked. The comment engine makes the same choice
    # verbatim now too: a headless Chrome even opens a scroll-only panel (see ``_execute_comment_node``).

    crawler = get_crawler(
        platform,
        headless=headless,
        cookie_dir=Config.COOKIE_DIR,
        use_profile=(ctx or {}).get('use_profile'),
        # `stop_requested`, not "no run is in flight": this predicate is what makes the
        # crawl end at its next row, and an idle server (a test calling the executor
        # directly) is not a user who pressed 停止.
        abort=stop_requested,
        account=account,
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
        _record_run_file(ctx, nid, info['path'], 'merged')
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
        keep_parts = as_bool(params.get('keep_parts'))
        pfmt = 'json' if str(params.get('format') or 'csv') == 'json' else 'csv'
        # A crawl 「按时间」 writes a table for a stated stretch of the calendar, and on
        # disk that fact used to exist nowhere but the node's own form: the file for
        # January and the file for March were both 「微博-src-node-2.csv」, so the second
        # one silently replaced the first and nobody could tell afterwards which month
        # they were reading. The window goes into the name of the parts AND of the file
        # they merge into, because those two are the same stem.
        _note_window(getattr(_wf_local, 'idx', None), params.get('start_time'), params.get('end_time'))
        parts = _name_parts(params, (ctx or {}).get('export_stamp') or '')
        writer = None
        if part_size > 0:
            from services.part_writer import PartWriter, safe_stem

            stem = safe_stem(f'{execution_state.get("workflow_name") or platform}-src-{nid}{parts}')
            # Record each shard as it lands (so an interrupted run's parts are still attributed
            # to the record) — but only when 「保留分片」 is on: with keep_parts off the writer
            # deletes them the moment the merge succeeds, so there is nothing for 智能清除 to find.
            writer = PartWriter(
                Config.EXPORT_DIR,
                stem,
                pfmt,
                part_size,
                keep_parts,
                on_write=(lambda path, kind: _record_run_file(ctx, nid, path, kind)) if keep_parts else None,
            )
        if ctx is not None:
            scope = _item_scope(ctx, node)
            if as_bool(params.get('recrawl')) and not ctx.get('resume'):
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
        rows = _crawl_with_collision_retry(crawler, getattr(crawler, mode.handler), crawl_args, resume, platform)
        if stop_requested():
            # A walk that honours 停止 does not raise: it breaks at its next row and hands
            # back what it collected. So a crawl that finished by *returning* after the
            # button was pressed would settle DONE — the run record saying 运行完成 over a
            # half-collected table, and the 继续 banner never appearing, which is the one
            # outcome a stop must never produce. The rows stand; the node is reported as
            # what it was.
            raise CrawlerStopped(t('crawl.stopped'))
    except PageNotArrivedError as exc:
        # The patience budget ran out with nothing on the page. What the crawler saw is
        # turned into a line that also says what this machine can reach, then the node
        # settles the way any refusal settles: the rows already streamed stay (which is
        # what makes it ``partial`` with a 继续 rather than an empty failure), and the
        # run is failed so the banner appears. Deliberately *not* routed through
        # ``cookie_expired``: an unreachable page says nothing about the session, and
        # sending the user to re-save a cookie they just saved is how this project has
        # burned a user's trust in its messages before.
        if getattr(crawler, 'login_wall', False):
            execution_state['cookie_expired'] = True
        elif getattr(crawler, 'risk_blocked', False):
            # A 验证码/风控 that mounted mid-wait is an *answer*, not a slow page: name it
            # as 风控 so the user backs off instead of retrying into the wall.
            with contextlib.suppress(Exception):
                _merge_parts(None)
            raise ValueError(t('run.riskControlled', platform=platform)) from exc
        with contextlib.suppress(Exception):
            _merge_parts(None)
        raise _page_not_arrived(platform, exc) from exc
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
        # Wall met exactly as the target was reached: the session died at the finish
        # line, so there is nothing missing — do not raise a false alarm.
        add_log(t('run.cookieExpiredOk', platform=platform))
    # A 风控 bounce that left the crawl short is named here — the sibling of U1, and the
    # opposite advice. A login wall says "re-save the cookie"; risk control says the session
    # may be perfectly fine and the ONLY safe move is to back off, so the node FAILS (keeps
    # every row, run marked failed so 继续 appears) with a line that forbids an immediate
    # re-run. Before U1, because a risk short must report 风控, never 采得不足. (A login wall
    # already raised in the block above, so reaching here short with ``wall`` set is impossible —
    # the two refusals are mutually exclusive by control flow, not by an added guard.)
    if target_count and len(rows) < target_count and getattr(crawler, 'risk_blocked', False):
        raise ValueError(t('run.riskControlled', platform=platform))
    # U1: a non-wall, non-risk, non-stopped crawl that came back under its target WITHOUT a
    # site-attested end must not settle clean DONE — that is §6's silent-under-collect, which
    # until now only the test tier's ``classify_verdict`` convicted, never the run itself.
    # ``end_reason`` is ``None`` for a not-yet-migrated handler (stays today's behaviour, no
    # regression while platforms migrate one at a time); a ``LICENSED_ENDS`` word means the SITE
    # said this is all (settles clean); ``UNDER_TARGET`` — and ONLY that — is the convicted
    # short. A loop self-summary cannot reach here as a license: ``Crawler.note_end`` refuses it.
    # A risk bounce is settled by the branch just above (named 风控, back off), so this gate
    # skips when ``risk_blocked`` is set — the two refusals never collide.
    if (
        target_count
        and len(rows) < target_count
        and getattr(crawler, 'end_reason', None) == UNDER_TARGET
        and not getattr(crawler, 'risk_blocked', False)
    ):
        counts = getattr(crawler, 'walk_counts', {}) or {}
        # Attribute the gap only when the funnel is fully measured; a partial one is omitted
        # rather than printed with invented zeros or a raw unfilled {slot}.
        walk = (
            t('run.underTargetWalk', scanned=counts['scanned'], kept=counts['kept'], refused=counts['refused'])
            if {'scanned', 'kept', 'refused'} <= set(counts)
            else ''
        )
        raise ValueError(t('run.underTargetShort', platform=platform, have=len(rows), want=target_count, walk=walk))
    return rows


# `_execute_upload_node` now lives in backend/services/nodes.py (execute_upload_node, imported
# back under this name near the top); dispatch and every call site read the app-level alias.


#: The select-shaped parameter of each analysis-algorithm node, and the spellings that
#: mean something to it. This is the same rule the crawl matrix applies to a ``select``
#: Field and ``DataAnalysisService.STEP_PARAMS`` applies to a cleaning step: a value off
#: the list is refused by name instead of being guessed into another algorithm. Before
#: the table, ``method='TF-IDF'`` ran TextRank (``keyword.py`` compared against one
#: name and treated everything else as the other), ``mode='ML'`` paid for a row-by-row
#: LLM pass the user had just declined (``emotion.py``/``tendency.py`` test only for
#: ``'ml'``), and ``mode='llm'`` on 实体识别 silently ran the rules instead.
#:
#: ``anomaly_method`` and ``topk`` are absent because their own code already refuses or
#: clamps them, and this table guards the sites that had no answer at all.
#:
#: Each entry is ``parameter -> (declared default, the spellings that mean something)``.
#: The default lives here because a blank field is "not stated", and the only safe
#: answer is the one the panel showed — read at the site that uses it, so the string
#: that is checked and the string the analyzer receives cannot be two different things.
PROCESS_ENUMS = {
    # Two ways to wash a table of Weibo comments clean: the model reads one row at a time
    # and judges relevance, or a rule set strips the artifacts a repost leaves behind
    # (转发链, @提及, 话题标签, O网页链接, 展开c) for free and at crawling speed. ``llm`` stays the
    # declared default because that is what a workflow saved before this selector existed
    # was already doing — a blank must not silently change what a stored canvas produces.
    'clean': {'mode': ('llm', ('regex', 'llm'))},
    'emotion': {'mode': ('llm', ('llm', 'ml', 'bert'))},
    'tendency': {'mode': ('llm', ('llm', 'ml', 'bert'))},
    # The traditional methods answer 正面/负面/中性, which is not the five-emotion or the
    # six-tendency label set — hence its own operation rather than a new mode on theirs.
    # SnowNLP is the default because it needs no model, no download and no GPU.
    'sentiment': {'mode': ('snownlp', ('llm', 'ml', 'snownlp', 'bert'))},
    'ner': {'mode': ('regex', ('regex', 'llm'))},
    # The lexicon is the default because it needs no model, costs nothing, and answers the same
    # table every run; ``llm`` is the opt-in that can see the euphemisms a fixed list cannot.
    'aggression': {'mode': ('lexicon', ('lexicon', 'llm'))},
    'keyword': {'method': ('tfidf', ('tfidf', 'textrank', 'tfidf_corpus'))},
    'cluster': {'cluster_method': ('kmeans', ('kmeans', 'kmeans++', 'dbscan'))},
    'correlation': {'corr_method': ('pearson', ('pearson', 'spearman', 'kendall'))},
}

#: The operations whose whole job is to read one text column of the table.
_TEXT_COLUMN_OPS = ('clean', 'emotion', 'tendency', 'sentiment', 'keyword', 'cluster', 'ner', 'aggression')


def enum_param(op: str, params: dict, key: str) -> str:
    """The value a select-shaped process parameter will really be called with.

    ``'TF-IDF'``, ``'ML'`` and ``' tfidf '` are each a name the operation does not
    know, and every site used to answer one of those with a different algorithm:
    ``keyword.py`` compared against ``'tfidf'`` and took TextRank for everything else
    (then stamped the table's ``method`` column with the name that had not run), while
    ``emotion``/``tendency`` tested only for ``'ml'`` and so took the **row-by-row LLM
    pass** for a misspelled request to use the local model. Clustering already refused;
    this is the same contract, applied where the parameter is read.
    """
    default, allowed = PROCESS_ENUMS[op][key]
    raw = params.get(key)
    value = default if raw is None or (isinstance(raw, str) and not raw.strip()) else str(raw).strip().strip()
    if value not in allowed:
        raise UnknownOperationError(t('analysis.bad_option', op=op, param=key, value=value, allowed=', '.join(allowed)))
    return value


def sentiment_thresholds(params: dict) -> tuple:
    """The two polarity cut-offs a sentiment node asked for, refused when they overlap.

    ``pos=0.3, neg=0.7`` is not an aggressive setting: read in order, every row is at once
    positive (score >= 0.3) and negative (score <= 0.7), so the whole column would come
    back 正面 and nothing would say the question was unanswerable. The band is checked
    rather than normalised because a swap is a guess about which number the user meant.
    """
    pos = _safe_float(params.get('pos_threshold'), 0.6)
    neg = _safe_float(params.get('neg_threshold'), 0.4)
    if neg > pos:
        raise UnknownOperationError(t('sentiment.bad_thresholds', pos=pos, neg=neg))
    return pos, neg


def check_process_params(op: str, params: dict, df) -> None:
    """Refuse an algorithm node whose parameters name nothing it can run.

    Every analyzer answers a missing 文本列 by logging 未找到列 and handing back the
    frame **unchanged**, which settles the node DONE: the run went green, the table
    downstream was the input table, and the only sentence saying why was in the log
    file. A node that did nothing is a failure, so the reason is raised here — at the
    one boundary every op passes through, where the node's own label can be attached
    by the executor.
    """
    for key in PROCESS_ENUMS.get(op) or {}:
        enum_param(op, params, key)
    if op == 'sentiment':
        # Asked here as well as where it is used, so a workflow that cannot answer the
        # question fails at the validation boundary the executor already reports by node.
        sentiment_thresholds(params)
    if op in _TEXT_COLUMN_OPS:
        name = str(params.get('text_column') or '正文').strip()
        if name not in [str(col) for col in df.columns]:
            raise UnknownOperationError(t('analysis.step_col_missing', op=op, col=name))


# ─── Multi-model BERT comparison ──────────────────────────────
#: The label/score columns each analyzer writes in bert mode. A multi-model run stacks
#: several models into ONE tidy table and the 模型对比 charts read these names, so this
#: mapping is the input contract between the analysis step and the comparison visualizations
#: — renaming a column here must be reflected on the chart side or it refuses by name.
BERT_RESULT_COLUMNS = {
    'emotion': ('emotion', 'confidence'),
    'tendency': ('tendency', 'tendency_confidence'),
    'sentiment': ('sentiment', 'score'),
}


def _model_registry():
    """The registered models as a list, or [] when absent/broken — the same graceful
    reading `/api/models` uses, so a name lookup can never crash a run."""
    path = os.path.join(Config.DATA_DIR, 'model_registry.json')
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _registry_name(model_path):
    """Friendly NAME for a model path (registry reverse-lookup), else its folder name.
    The 模型 column a comparison chart groups by is a word the user chose, not a path."""
    for m in _model_registry():
        if isinstance(m, dict) and str(m.get('path', '')).strip() == model_path:
            return str(m.get('name') or '').strip() or os.path.basename(model_path)
    return os.path.basename(model_path)


def bert_model_list(params):
    """The model paths an analysis node asked to run.

    ``bert_models`` is a comma-separated list (the ``stack_fields`` shape): split, trimmed,
    de-duplicated and **sorted**, so one model set is one fingerprint no matter the click
    order. When it is empty the node falls back to the single ``bert_model`` field — every
    canvas written before multi-model runs exactly one model as it always did, and only an
    explicit multi-selection changes the output shape.
    """
    raw = str(params.get('bert_models') or '').replace('，', ',')
    seen = []
    for part in (p.strip() for p in raw.split(',')):
        if part and part not in seen:
            seen.append(part)
    if len(seen) > 1:
        return sorted(seen)
    if seen:
        return seen
    single = str(params.get('bert_model') or '').strip()
    return [single] if single else []


def _build_bert_analyzer(op, params, model_path):
    """Construct the one analyzer for (op, model), shared by the single and multi paths so
    the batch_size/threshold validation is identical either way."""
    batch = _safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256)
    if op == 'emotion':
        return EmotionAnalyzer(mode='bert', bert_model=model_path, batch_size=batch)
    if op == 'tendency':
        return TendencyAnalyzer(mode='bert', bert_model=model_path, batch_size=batch)
    if op == 'sentiment':
        pos, neg = sentiment_thresholds(params)
        return SentimentAnalyzer(
            mode='bert', pos_threshold=pos, neg_threshold=neg, bert_model=model_path, batch_size=batch
        )
    raise UnknownOperationError(
        t('analysis.bad_option', op=op, param='operation', value=op, allowed=', '.join(BERT_RESULT_COLUMNS))
    )


def _run_bert_compare(op, params, df, text_column, run_ctx):
    """Run every selected BERT model over the column and return ONE tidy table.

    One row per (original row × model), tagged by 模型 and aligned across models by 原行,
    plus the operation's own label/score columns — the shape the comparison charts read.
    A single model never enters here (it keeps its in-place two-column shape), so fewer
    than two is refused by name rather than silently returning a long table nobody asked
    for. Each model's own analyzer still refuses by name for a missing stack or an unknown
    label, and a row it cannot answer stays blank.
    """
    models = bert_model_list(params)
    if len(models) < 2:
        raise UnknownOperationError(t('analysis.need_multi_models', op=op, n=len(models)))
    label_col, score_col = BERT_RESULT_COLUMNS[op]
    base = df.copy()
    base['原行'] = range(len(base))
    collected = []
    names = []
    for path in models:
        sub = base.copy()
        analyzer = _build_bert_analyzer(op, params, path)
        sub = analyzer.analyze_dataframe(sub, text_column=text_column, ctx=run_ctx)
        name = _registry_name(path)
        sub['模型'] = name
        names.append(name)
        collected.append(sub)
    tidy = pd.concat(collected, ignore_index=True)
    add_log(t('analysis.multi_models_run', op=op, n=len(models), models='、'.join(names)))
    return tidy.to_dict('records')


def _execute_process_node(node: dict, current_input: list, run_ctx: dict = None):
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    # Default matches the frontend canvas default and every crawler's output
    # column; the old 'content' silently mismatched real crawl data. Read through the
    # same blank-means-default rule `check_process_params` validates, so the column it
    # checks is the column the analyzer gets.
    text_column = str(params.get('text_column') or '正文').strip()
    if not current_input:
        return []

    df = pd.DataFrame(current_input)
    check_process_params(op, params, df)

    if op == 'clean':
        topic = params.get('topic', '')
        cleaner = ContentCleaner()
        df = cleaner.clean_dataframe(
            df,
            text_column=text_column,
            topic=topic,
            ctx=run_ctx,
            mode=enum_param(op, params, 'mode'),
        )
        return df.to_dict('records')

    if op == 'emotion':
        if enum_param(op, params, 'mode') == 'bert' and len(bert_model_list(params)) > 1:
            return _run_bert_compare(op, params, df, text_column, run_ctx)
        analyzer = EmotionAnalyzer(
            mode=enum_param(op, params, 'mode'),
            bert_model=str(params.get('bert_model') or '').strip(),
            # Read by the transformer path; validated here for every mode so a stored 0
            # cannot reach the chunking loop and score an empty column while reporting success.
            batch_size=_safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'tendency':
        if enum_param(op, params, 'mode') == 'bert' and len(bert_model_list(params)) > 1:
            return _run_bert_compare(op, params, df, text_column, run_ctx)
        analyzer = TendencyAnalyzer(
            mode=enum_param(op, params, 'mode'),
            bert_model=str(params.get('bert_model') or '').strip(),
            # Read by the transformer path; validated here for every mode so a stored 0
            # cannot reach the chunking loop and score an empty column while reporting success.
            batch_size=_safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'sentiment':
        if enum_param(op, params, 'mode') == 'bert' and len(bert_model_list(params)) > 1:
            return _run_bert_compare(op, params, df, text_column, run_ctx)
        pos, neg = sentiment_thresholds(params)
        analyzer = SentimentAnalyzer(
            mode=enum_param(op, params, 'mode'),
            pos_threshold=pos,
            neg_threshold=neg,
            bert_model=str(params.get('bert_model') or '').strip(),
            # Only the transformer path reads this, but it is validated here for every
            # mode so a stored 0 cannot reach the chunking loop and score nothing.
            batch_size=_safe_int(params.get('batch_size'), BERT_BATCH, minimum=1, maximum=256),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
        return df.to_dict('records')

    if op == 'keyword':
        method = enum_param(op, params, 'method')
        topk = _safe_int(params.get('topk'), 10, minimum=1)
        # ``as_bool``, never ``== 'true'``: real ``True`` is unequal to the text 'true',
        # so a workflow that stored the boolean (an exported file, /api/analysis/run)
        # asking for one merged keyword table silently got the per-row expansion.
        merge = as_bool(params.get('merge'), True)
        # A blank is "no filter" — the behaviour this node always had — so an untouched
        # canvas keeps producing exactly the keywords it used to.
        allow_pos = str(params.get('allow_pos') or '').strip()
        extractor = KeywordExtractor()
        df = extractor.analyze_dataframe(
            df,
            text_column=text_column,
            method=method,
            topk=topk,
            merge=merge,
            allow_pos=allow_pos,
        )
        return df.to_dict('records')

    if op == 'cluster':
        method = enum_param(op, params, 'cluster_method')
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
        recognizer = NamedEntityRecognizer(mode=enum_param(op, params, 'mode'))
        df = recognizer.analyze_dataframe(
            df,
            text_column=text_column,
            entity_types=params.get('entity_types'),
            ctx=run_ctx,
        )
        return df.to_dict('records')

    if op == 'aggression':
        # The paper's own object: how violent the speech is, as opposed to how negative. The
        # lexicon mode is the default (no model, no cost, reproducible), and ``llm`` reuses the
        # shared row-by-row runner, so batching, checkpointing, Stop and 未处理 all arrive with it.
        analyzer = AggressionAnalyzer(
            mode=enum_param(op, params, 'mode'),
            model_name=str(params.get('model') or '').strip(),
        )
        df = analyzer.analyze_dataframe(df, text_column=text_column, ctx=run_ctx)
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
        corr_method = enum_param(op, params, 'corr_method')
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


def _merge_upstream_tables(current_input: list, upstream: list, label: str) -> tuple:
    """Every incoming table as one, or the reason they cannot be one.

    A node with several incoming connections used to take only the FIRST and mention the
    rest in one console line, so wiring three crawls into one save node exported one of
    them and reported success — the shape this project bans everywhere else. The save node
    is the merge point because that is where a user naturally puts it: several batches of
    the same crawl, one file to analyse.

    Two refusals, both about not guessing:

    * a parent whose result is not a table at all — a chart spec or a refusal envelope —
      cannot contribute rows, and skipping it silently would export the others as if the
      canvas had only those;
    * parents whose COLUMN SETS differ are refused rather than passed to ``pd.concat``,
      which answers a mismatch with an outer join: the missing columns come back as NaN
      and the file looks like a complete table with holes in it. A crawler whose columns
      changed between two runs is exactly how that happens, and the reason names the
      columns so the canvas can be fixed.

    A parent with ZERO rows is not a refusal — an empty batch is a real answer, and it is
    reported so the row counts still add up to what was written.
    """
    tables = []
    for pid, result in upstream or ():
        if isinstance(result, list):
            tables.append((str(pid), result))
            continue
        raise ValueError(t('wf.merge_not_tabular', nid=label, up=str(pid)))
    if not tables:
        # No upstream list at all (a direct caller, or a node with no wire): the rows in
        # hand are the whole answer, which is what this node did before merging existed.
        return list(current_input or []), (str(label), len(current_input or []))
    if len(tables) == 1:
        return list(tables[0][1]), (tables[0][0], len(tables[0][1]))

    frames = [(pid, pd.DataFrame(rows)) for pid, rows in tables]
    # The reference columns come from the first frame that HAS any: an empty table answers
    # with no columns at all, and taking its shape as the truth would call every other
    # table's columns "extra".
    reference = next((list(frame.columns) for _pid, frame in frames if len(frame.columns)), [])
    for pid, frame in frames[1:]:
        # A table with ZERO rows has nothing that can disagree — there is no cell to line
        # up — so it is skipped here and contributes nothing to the concatenation. Refusing
        # it would make an honest empty batch look like a misconfigured canvas.
        if len(frame) and set(frame.columns) != set(reference):
            extra = [str(name) for name in frame.columns if name not in reference]
            missing = [str(name) for name in reference if name not in frame.columns]
            raise ValueError(
                t(
                    'wf.merge_columns',
                    nid=label,
                    up=pid,
                    extra=', '.join(extra) or '-',
                    missing=', '.join(missing) or '-',
                )
            )
    merged = pd.concat([frame for _pid, frame in frames], ignore_index=True, sort=False)
    detail = '、'.join(f'{pid} {len(frame)} 行' for pid, frame in frames)
    add_log(t('wf.merge_done', nid=label, n=len(merged), tables=len(frames), detail=detail))
    return merged.to_dict('records'), (str(label), len(merged))


def _pdf_filename(params: dict) -> str:
    """The final PDF file name from an output node's params: sanitized, extension forced to ``.pdf``.

    Deliberately NOT ``DataExporter.normalize_filename`` — that re-applies a *tabular* extension from its
    whitelist and would turn 「report.pdf」 into 「report.csv」. A PDF's name is its own contract.
    """
    base = os.path.splitext(sanitize_filename(params.get('filename', 'export.pdf')))[0]
    name = f'{base}.pdf'
    if as_bool(params.get('filename_timestamp')):
        name = DataExporter.stamp_filename(name, Config.EXPORT_DIR)
    return name


def _output_pdf(node: dict, upstream: list, ctx: dict = None) -> dict:
    """Write the PDF an output node owes when its upstream carries LaTeX (visualize) or an already-compiled
    artifact (compile). Validation guarantees every parent here is one of those two and never mixes them,
    so exactly one source kind is present and ``xelatex`` runs once per chain — never twice.
    """
    params = node.get('params', {})
    docs = []
    staged_pdf = ''
    for _pid, res in upstream or ():
        if not isinstance(res, dict):
            continue
        if 'error' in res:
            # The parent already failed for its OWN named reason; carry that up verbatim rather than
            # inventing a second message for a single failure.
            return {'error': str(res.get('error'))}
        if res.get('pdf_file'):
            staged_pdf = res['pdf_file']
        if res.get('latex'):
            docs.append(res['latex'])
        if res.get('latex_table'):
            docs.append(res['latex_table'])
    filename = _pdf_filename(params)
    if staged_pdf:
        # The compile node already produced this (staged in EXPORT_DIR); finalize it under the user's name.
        staged = os.path.join(Config.EXPORT_DIR, staged_pdf)
        try:
            os.replace(staged, os.path.join(Config.EXPORT_DIR, filename))
        except OSError as e:
            return {'error': t('api.compilePdfFailed', err=e)}
        size = os.path.getsize(os.path.join(Config.EXPORT_DIR, filename))
        add_log(t('run.compileSaved', name=filename, size=size))
        _record_run_file(ctx, str(node.get('id') or ''), filename, 'pdf')
        # The compile node recorded the staged name; the rename made that file this one, so drop
        # the stale row rather than leave 智能清除 pointing at a name that no longer exists.
        if ctx and ctx.get('store'):
            with contextlib.suppress(Exception):
                ctx['store'].forget_file(staged_pdf)
        return {'pdf_file': filename, 'pdf_bytes': size}
    if not docs:
        return {'error': t('wf.compile_no_source')}
    out, name = latex_compile.compile_pdf(latex_compile.compose_tex(docs), filename, Config.EXPORT_DIR)
    if 'error' in out:
        return out
    add_log(t('run.compileSaved', name=name, size=out.get('pdf_bytes', 0)))
    _record_run_file(ctx, str(node.get('id') or ''), name, 'pdf')
    return {'pdf_file': name, 'pdf_bytes': out.get('pdf_bytes', 0)}


def _execute_output_node(node: dict, current_input: list, upstream: list = None, ctx: dict = None):
    """Save node: merges every incoming table, exports it, and passes it downstream.

    'save_csv' is kept as a back-compat alias for older saved workflows;
    both routes go through the same DataExporter used by the standalone
    /api/export/save endpoint, so behaviour is identical whether the save
    happens inside a workflow or on its own.

    It hands ON the merged table rather than the first parent's rows, so a chain of
    analyses may hang off this node and see everything that was written to the file.

    ``ctx`` is the run context (optional): a save written by a run is registered in the
    run→files ledger so 智能清除 can find it; a direct call outside a run writes the file but
    attributes it to no record — which is correct, because none made it.
    """
    params = node.get('params', {})
    op = node.get('operation', params.get('operation', ''))
    # PDF is not a tabular export: when the format is pdf the node compiles the LaTeX its upstream
    # visualize / compile produced (see _output_pdf) and never reaches the row merge below, which would
    # refuse a dict upstream with wf.merge_not_tabular.
    _fmt = str(params.get('format') or DataExporter.infer_format(params.get('filename', '')) or '').lower()
    if op in ('save', 'save_csv') and _fmt == 'pdf':
        return _output_pdf(node, upstream, ctx=ctx)
    if not current_input and not upstream:
        return []

    merged_rows, _ = _merge_upstream_tables(current_input, upstream, node_label(node, node.get('id', '')))
    if not merged_rows:
        return []

    df = pd.DataFrame(merged_rows)

    if op in ('save', 'save_csv'):
        fmt = params.get('format', 'csv' if op == 'save_csv' else None)
        filename = params.get('filename', 'export.csv')
        fmt = fmt or DataExporter.infer_format(filename)
        # Sanitize first, then (re)apply the extension: the other way round a
        # name like ".." lost its extension and landed as a hidden file.
        filename = DataExporter.normalize_filename(sanitize_filename(filename), fmt)
        # The stamp is resolved here and never written back into ``params``,
        # because a run-time value inside a node's parameters would change its
        # fingerprint on every attempt: 继续 could not recognise the node, every
        # LLM cache key would miss and a renamed chain would re-crawl.
        #
        # One limitation this trades away, stated so it is not discovered later:
        # on 继续 an output node whose stored rows still match its fingerprint is
        # *restored*, so this line never runs and no second file appears. Re-running
        # for a new timestamp means re-running the chain it writes out of.
        if as_bool(params.get('filename_time_range')):
            # Which stretch of the calendar this table covers is a fact about the CRAWL,
            # and a save node is handed only rows — so the window is whatever this run's
            # crawl nodes recorded (`_note_window`). Zero of them and two different ones
            # are both refusals stated by name: a file called 「January」 that holds March
            # is worse than a file that was never written, and the name is the thing being
            # chosen here.
            tag, refusal = _window_for_save(getattr(_wf_local, 'idx', None))
            if refusal:
                # A time range in the filename is decoration, never a reason to withhold the
                # file. When the upstream crawl carried no single honest window (none, or two
                # different ones), ignore the checkbox and export under the plain name — the
                # user still gets their data and only the name loses the tag. Refusing here
                # (the old behaviour) threw away the whole result over a label nobody needed.
                add_log(t('export.window_ignored', nid=node_label(node, str(node.get('id') or '')), reason=refusal))
            else:
                filename = DataExporter.tagged_filename(filename, tag)
        if as_bool(params.get('filename_timestamp')):
            filename = DataExporter.stamp_filename(filename, Config.EXPORT_DIR)
        filepath = os.path.join(Config.EXPORT_DIR, filename)
        try:
            DataExporter.save(df, filepath, fmt=fmt, text_column=params.get('text_column'))
        except UnsupportedFormatError as e:
            # Refused, and the reason travels: the executor prints it as this node's
            # failure with the node's own label. A second add_log here said the same
            # sentence again, unattributed — the version the user could not act on.
            return {'error': str(e)}
        _record_run_file(ctx, str(node.get('id') or ''), filename, 'export')
        # No "data saved to <path>" line: the exporter has already announced
        # "exported N rows to <path> (fmt)" one line above, and saying the same
        # fact twice in two wordings is two chances to word them differently.

    return merged_rows


# The numeric-coercion family (_safe_int / _safe_float / _optional_int / _optional_float) lives in
# api.http now (imported at top); every app call site reads the app-level alias unchanged.


# `_split_columns` now lives in utils/helpers.py (split_columns, imported back under this name).


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
        # ``mode`` is passed explicitly rather than left to the method's signature: the
        # stored value is what the user chose, and a bad spelling has to reach
        # ``validate_step`` and be refused by name instead of quietly becoming 'exact'.
        return {
            'columns': _split_columns(params.get('columns')) or None,
            'mode': params.get('mode') or 'exact',
        }
    if op == 'dedupe_similar':
        result = {'column': params.get('column', '')}
        distance = _optional_int(params.get('max_distance'))
        if distance is not None:
            result['max_distance'] = distance
        return result
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
        # Both spellings of a switch are in the saved files: the panel used to store
        # the text 'true'/'false' and a hand-written or exported workflow stores the
        # boolean. Comparing against one of them inverted 升序 into 降序 for the other.
        return {'column': params.get('column', ''), 'ascending': as_bool(params.get('ascending'), True)}
    if op == 'sample_rows':
        result = {'n': _optional_int(params.get('n')), 'frac': _optional_float(params.get('frac'))}
        seed = _optional_int(params.get('seed'))
        if seed is not None:
            result['seed'] = seed
        return result
    if op == 'groupby_agg':
        result = {
            'group_col': params.get('group_col', ''),
            'agg_col': params.get('agg_col', ''),
            'agg_func': params.get('agg_func', 'sum'),
        }
        # Read like ``score_col``: a blank box means "sort the groups by their own name", the
        # behaviour every saved pipeline already relies on, so the key is not sent.
        order_column = str(params.get('group_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        return result
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
    # ── the event-study steps ──
    if op == 'extract_time':
        return {
            'column': params.get('column', ''),
            'new_col': params.get('time_new_col') or '日期',
            'part': params.get('time_part') or 'date',
        }
    if op == 'bin_time':
        # The boundaries and the names are two parallel lists, so both are parsed here and
        # their lengths are checked by the step itself — that check is a refusal with a
        # reason, which is where a mismatched pair belongs.
        result = {
            'column': params.get('column', ''),
            'new_col': params.get('phase_new_col') or '阶段',
            'edges': _split_columns(params.get('phase_edges')),
            'labels': _split_columns(params.get('phase_labels')),
        }
        # Like ``score_col``: a blank box means "no order column", which is the step's own
        # default. The number is what lets 各阶段 tables and charts keep the lifecycle order
        # across the node boundary that erases the categorical.
        order_column = str(params.get('phase_order_col') or '').strip()
        if order_column:
            result['order_new_col'] = order_column
        return result
    if op == 'suggest_stages':
        # Every number here has a declared default in the step, so a blank or a junk box is
        # left to that default instead of reaching the curve as 0 or as a float('inf').
        result = {'column': params.get('column', '')}
        min_days = _optional_int(params.get('stages_min_days'))
        if min_days:
            result['min_days'] = min_days
        max_windows = _optional_int(params.get('stages_max_windows'))
        if max_windows:
            result['max_windows'] = max_windows
        ratio = _optional_float(params.get('stages_peak_ratio'))
        if ratio is not None:
            result['peak_ratio'] = ratio
        return result
    if op == 'topic_by_stage':
        result = {
            'column': params.get('column', ''),
            # The panel leaves this blank to mean the column 按时间划分阶段 writes, which is
            # also the step's own default; the gate must not refuse a box nobody typed in.
            'stage_col': str(params.get('stage_col') or '阶段').strip(),
            'topics': _split_columns(params.get('stage_topic_counts')),
            'topn': _optional_int(params.get('topic_topn')) or 10,
            'word_source': params.get('word_source') or 'tfidf',
            'sample_n': _optional_int(params.get('topic_sample_n')) or 5,
        }
        # Omitted when blank, like ``label_col``: "sort the phases by this time column" is a
        # choice the user makes, and an empty string is not a column to sort by.
        order_column = str(params.get('stage_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return result
    if op == 'topic_map':
        result = {
            'column': params.get('column', ''),
            'n_topics': _optional_int(params.get('n_topics')) or 5,
            'topn': _optional_int(params.get('topic_topn')) or 6,
        }
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return result
    if op == 'topic_salience':
        result = {
            'column': params.get('column', ''),
            'n_topics': _optional_int(params.get('n_topics')) or 5,
            'topn': _optional_int(params.get('topic_topn')) or 30,
        }
        # λ is read as a float and only forwarded when a number was written: 0 is a real answer
        # here (rank by over-representation only), so the ``or`` idiom used for counts would
        # turn the most interesting setting into the default.
        lam = _optional_float(params.get('topic_lambda'))
        if lam is not None:
            result['relevance'] = lam
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return result
    if op == 'topic_model':
        result = {
            'column': params.get('column', ''),
            'n_topics': _optional_int(params.get('n_topics')) or 5,
            'topn': _optional_int(params.get('topic_topn')) or 10,
        }
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return result
    if op == 'topic_timeline':
        # The four column names default to what 分阶段 LDA writes, so an untouched form is the
        # pipeline's own hand-off. The step still refuses when this table does not hold them.
        result = {
            'stage_col': str(params.get('timeline_stage_col') or 'stage').strip(),
            'words_col': str(params.get('timeline_words_col') or 'feature_words').strip(),
            'size_col': str(params.get('timeline_size_col') or 'doc_n').strip(),
            'topic_col': str(params.get('timeline_topic_col') or 'topic').strip(),
        }
        # Blank means "the phases are still ordered as the categorical left them", which is a
        # different answer from "sort them by this column", so it is omitted rather than sent.
        order_column = str(params.get('timeline_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        # 0 is refused by the step (no overlap at all would put every row in its own family),
        # so it is forwarded as the wrong answer it is instead of swallowed by ``or``.
        overlap = _optional_float(params.get('timeline_overlap'))
        if overlap is not None:
            result['min_overlap'] = overlap
        return result
    if op == 'topic_flow':
        result = {
            'stage_col': str(params.get('flow_stage_col') or 'stage').strip(),
            'topic_col': str(params.get('flow_topic_col') or 'topic').strip(),
            'words_col': str(params.get('flow_words_col') or 'feature_words').strip(),
            'weights_col': str(params.get('flow_weights_col') or 'weights').strip(),
            'min_similarity': _optional_float(params.get('flow_min_similarity')) or 0.5,
        }
        order_column = str(params.get('flow_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        # Read like ``score_col``: blank means the sankey keeps drawing bare row labels, and a
        # named column (表 1's 主题概括) is what makes the figure readable.
        label_column = str(params.get('flow_label_col') or '').strip()
        if label_column:
            result['label_col'] = label_column
        return result
    if op == 'topic_coherence':
        result = {
            'column': params.get('column', ''),
            'topn': _optional_int(params.get('topic_topn')) or 10,
        }
        # The sweep's two ends are forwarded whenever a number was written, including a 0: an
        # impossible end is refused by the step with the range in the message, which is truer
        # than quietly raising it to the default the user just overrode.
        for key, source in (
            ('min_topics', 'coherence_min_topics'),
            ('max_topics', 'coherence_max_topics'),
            ('max_documents', 'coherence_max_documents'),
        ):
            number = _optional_int(params.get(source))
            if number is not None:
                result[key] = number
        features = _optional_int(params.get('topic_max_features'))
        if features:
            result['max_features'] = features
        return result
    if op == 'cooccur':
        result = {
            'column': params.get('column', ''),
            'topn': _optional_int(params.get('cooccur_topn')) or 30,
        }
        floor = _optional_int(params.get('cooccur_min_count'))
        if floor is not None:
            result['min_count'] = floor
        # A window of 0 is the whole document, which is the answer the panel's empty box means —
        # so it has to reach the step as 0, not be read as "not configured".
        window = _optional_int(params.get('cooccur_window'))
        if window is not None:
            result['window'] = window
        return result
    if op == 'forecast':
        result = {
            # The panel leaves the period box blank to mean "the column 情感演化曲线 writes",
            # which is also the step's own default.
            'column': str(params.get('forecast_period_col') or 'period').strip(),
            'value_col': str(params.get('forecast_value_col') or 'sentiment_index').strip(),
            'method': params.get('forecast_method') or 'moving_average',
            'horizon': _optional_int(params.get('forecast_horizon')) or 3,
            'window': _optional_int(params.get('forecast_window')) or 3,
            'min_periods': _optional_int(params.get('forecast_min_periods')) or 4,
        }
        # Both smoothing factors are forwarded whenever a number was written: 0 is refused by the
        # step as the degenerate setting it is, and swallowing it into the default would answer a
        # question the user did not ask.
        for key, source in (('alpha', 'forecast_alpha'), ('beta', 'forecast_beta')):
            number = _optional_float(params.get(source))
            if number is not None:
                result[key] = number
        return result
    if op == 'alert':
        result = {
            'column': str(params.get('alert_period_col') or 'period').strip(),
            'index_col': str(params.get('alert_index_col') or 'sentiment_index').strip(),
            'streak': _optional_int(params.get('alert_streak')) or 2,
            'swing': _optional_float(params.get('alert_swing')) or 0.2,
            'heating': _optional_float(params.get('alert_heating')) or 0.15,
            'volume_floor': _optional_float(params.get('alert_volume_floor')) or 0.6,
        }
        # The two optional signals are read exactly like ``score_col`` on 情感演化曲线: a blank
        # box means that half of the rule is not wanted, so the key is not sent and the step's own
        # '' answers. A name that is typed but missing IS refused, by the step.
        for key, source in (('intensity_col', 'alert_intensity_col'), ('volume_col', 'alert_volume_col')):
            value = str(params.get(source) or '').strip()
            if value:
                result[key] = value
        return result
    if op == 'topic_label':
        # Every field falls back to the column 分阶段 LDA writes, so an untouched form is the
        # pipeline's own hand-off rather than a missing parameter; the step still refuses when
        # the table does not actually hold that column.
        return {
            'words_col': str(params.get('label_words_col') or 'feature_words').strip(),
            'summary_col': str(params.get('label_summary_col') or '主题概括').strip(),
            'samples_col': str(params.get('label_samples_col') or 'sample_texts').strip(),
            'on_fail': params.get('label_on_fail') or 'abort',
            'max_topics': _optional_int(params.get('label_max_topics')) or 30,
        }
    if op == 'sentiment_evolution':
        result = {'column': params.get('column', '')}
        label_col = str(params.get('label_col') or '').strip()
        if label_col:
            result['label_col'] = label_col
        # The three label spellings are only passed when the user actually typed one: the
        # step's own defaults are the polarity node's verbs, and an empty string is not a
        # spelling to filter by.
        for key, source in (
            ('positive', 'label_positive'),
            ('neutral', 'label_neutral'),
            ('negative', 'label_negative'),
        ):
            value = str(params.get(source) or '').strip()
            if value:
                result[key] = value
        # Same rule as ``label_col``: a blank 强度 column means "the curve has no intensity
        # line", which is the step's own default. Sending ``score_col=''`` would be the same
        # answer, and sending the literal text of a cleared box would refuse the node for a
        # feature the user never asked for.
        score_column = str(params.get('score_col') or '').strip()
        if score_column:
            result['score_col'] = score_column
        # Read like ``score_col``: blank means "sort the periods by their own name", which is
        # right for days and wrong for Chinese phase labels once the categorical is gone —
        # the number 划分阶段's 阶段序号 writes is what restores the lifecycle order.
        order_column = str(params.get('evolution_order_col') or '').strip()
        if order_column:
            result['order_col'] = order_column
        if str(params.get('index_new_col') or '').strip():
            result['new_col'] = str(params['index_new_col']).strip()
        return result
    return {}


def _execute_analysis_node(node: dict, current_input: list, upstream: list = None, ctx: dict = None):
    """Analysis node: runs a deterministic data-cleaning pipeline (null
    handling, de-duplication, filtering, renaming, ...) via
    DataAnalysisService. Supports either a single configured operation
    (as built by the Settings panel) or a full multi-step pipeline stored
    under params['steps'] for advanced use / API callers.

    A ``join_tables`` step merges with the table of the node's *second*
    incoming connection. The old design asked the user to paste an opaque
    12-character dataset id instead — an id produced by the Upload node and
    shown nowhere, so a join silently joined nothing.

    A step in ``LLM_OPS`` (the 主题概括 labeler) is the one case this node is not
    deterministic, so it borrows the process node's client builder rather than
    inventing a second reading of the LLM settings: the per-node model override,
    the daemon address pinned at run start and the run's Stop event all come from
    there. Refusing for want of a model happens HERE, before any call is paid for.
    """
    params = node.get('params', {})
    if not current_input:
        return []

    df = pd.DataFrame(current_input)

    steps = params.get('steps')
    if isinstance(steps, dict):
        # ``pd.DataFrame`` above turns a dict-shaped ``steps`` into rows and ``.get`` then dies
        # with a TypeError, which the executor reports as an unexplained node failure. The
        # normalizer's door refuses this shape; this door has to as well.
        raise UnknownOperationError(t('wf.analysis_steps_shape'))
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
    # A labelling step is the one thing in this node that cannot answer without the model, so
    # the refusal is issued BEFORE any call is paid for. The client comes from the process
    # node's own builder, because that is where the per-node model override, the daemon address
    # pinned at run start and the run's Stop event are read: a second reader of those settings
    # here would be a second opinion about which model this run is using.
    llm = None
    cancel = None
    if any(str(step.get('op')) in LLM_OPS for step in steps):
        cfg = execution_state.get('llm') or {}
        node_model = str((node.get('params') or {}).get('model') or '').strip()
        if not str(cfg.get('model') or '').strip() and not node_model:
            raise UnknownOperationError(t('wf.analysis_llm_no_model'))
        run_ctx = _llm_run_ctx(node, 'topic_label', ctx)
        llm = run_ctx['client']
        cancel = run_ctx.get('cancel_event')

    # The store is the run ledger's own llm_cache: a summary the model already answered for this
    # exact prompt is replayed instead of paid for again. It is passed beside ``llm`` rather than
    # through params for the same reason the client is — the run record echoes params.
    cleaned, report = DataAnalysisService.run_pipeline(df, steps, llm=llm, cancel=cancel, store=get_run_store())

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


def _execute_visualize_node(node: dict, current_input: list, ctx: dict = None):
    """Visualize node: builds a chart from the upstream data and returns a
    chart spec dict the frontend renders — either an ECharts option or a
    base64 image — so this node works identically to /api/visualize/render.

    It has no data source of its own on purpose: files enter a workflow
    through the Upload node, so a chart is always "whatever upstream
    produced", crawl or file alike.
    """
    params = node.get('params', {})
    chart_type = params.get('chart_type', 'bar')
    x_field = params.get('x_field')
    y_field = params.get('y_field')
    value_field = params.get('value_field')
    agg = params.get('agg', 'sum')
    # The right-hand scale of 双轴折线. Read like ``value_field`` — the service owns the
    # refusal when a type needs it and does not have it.
    y2_field = params.get('y2_field')
    agg2_field = params.get('agg2')
    # The column that NAMES each bubble in the intertopic map (the topic label). Read like
    # ``value_field``: the builder owns the refusal when a type needs it and does not have it.
    label_field = params.get('label_field')
    # The columns a 100% stacked-share figure lays on top of each other (e.g. the sentiment
    # evolution's positive_pct/neutral_pct/negative_pct). Forwarded to both engines.
    stack_fields = params.get('stack_fields')
    # The one word a 关系图 centres on: it + its directly co-occurring words only (an
    # ego-network), not a hover hint. Blank = the full candidate graph. It chooses which
    # rows reach the figure, so it feeds the node fingerprint (never a volatile label).
    center_node = params.get('center_node')
    # The three columns 模型一致率 reads from the tidy multi-model table: which column names a
    # model, which holds its label, and which aligns the same text across models. Forwarded like
    # the other optional fields; the builder owns the refusal when they name a missing column.
    model_field = params.get('model_field')
    agreement_label_field = params.get('agreement_label_field')
    id_field = params.get('id_field')
    # Dated event markers for 折线/柱状/双轴折线. Forwarded to both engines: the matplotlib
    # renderer refuses it by name, which is the honest answer when a figure would lose its dates.
    annotations = params.get('annotations')
    title = params.get('title', '')
    tokenize = as_bool(params.get('tokenize'))
    wordcloud_style = params.get('wordcloud_style')

    if not current_input:
        add_log(t('wf.visualize_no_input'))
        return {'error': t('wf.visualize_no_input')}
    df = pd.DataFrame(current_input)

    try:
        # ``chart_engine`` refuses an off-list renderer by name; branching on the raw
        # value here (as both paths used to) handed 'mpl' / 'Matplotlib' to the browser
        # library and reported it as if the user had chosen it.
        engine = chart_engine(params.get('engine'))
        if engine == 'matplotlib':
            image = VisualizationService.render_image(
                df,
                chart_type,
                x=x_field,
                y=y_field,
                value_field=value_field,
                agg=agg,
                title=title,
                annotations=annotations,
                stack_fields=stack_fields,
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
                y2=y2_field,
                agg2=agg2_field,
                label_field=label_field,
                annotations=annotations,
                title=title,
                stack_fields=stack_fields,
                center_node=center_node,
                model_field=model_field,
                agreement_label_field=agreement_label_field,
                id_field=id_field,
                **kw,
            )
            spec = {'engine': 'echarts', 'option': option}
    except ChartConfigError as e:
        # The reason travels as the node's own error; the executor prints it once,
        # with the node's label. Printing it here too gave two lines for one
        # failure, the first of them undiagnosable because it named no node.
        return {'error': str(e)}

    # Both LaTeX add-ons default ON: a chart a user drops on the canvas also owes them the
    # figure source and the three-line table, since the point of the whole node is a
    # paper-ready figure. Either box can be turned off on its own.
    emit_latex = as_bool(params.get('emit_latex', True))
    emit_latex_table = as_bool(params.get('emit_latex_table', True))
    if emit_latex or emit_latex_table:
        spec.update(
            _latex_outputs(
                df,
                chart_type=chart_type,
                x_field=x_field,
                y_field=y_field,
                value_field=value_field,
                agg=agg,
                y2_field=y2_field,
                agg2_field=agg2_field,
                label_field=label_field,
                stack_fields=stack_fields,
                title=title,
                tokenize=tokenize,
                emit_latex=emit_latex,
                emit_latex_table=emit_latex_table,
                base_name=node.get('title') or node.get('id') or chart_type,
                log=True,
            )
        )
        # The LaTeX add-ons are real files in the export folder (the figure source and the
        # three-line table); the chart itself lives only in the returned spec. Register the
        # written files so a run's paper artifacts are clearable and listed with its record.
        nid = str(node.get('id') or '')
        for _key, _kind in (('latex_file', 'latex'), ('latex_table_file', 'latex_table')):
            if spec.get(_key):
                _record_run_file(ctx, nid, spec[_key], _kind)

    add_log(t('wf.visualize_done', chart=chart_type, engine=engine, n=len(df)))
    return spec


def _filter_comments_by_time(rows: list, params: dict, label: str) -> list:
    """Drop comments whose 评论时间 falls outside an optional [start, end] range.

    This is a TABLE-side filter of comments already crawled, deliberately separate from a
    crawl node's start_time/end_time (which decides how far back to CRAWL). The keys are
    comment_start/comment_end so the two meanings never share a name. A range chooses which
    data is kept, so a half range, an unparseable date or an inverted window is refused BY
    NAME rather than guessed (the same discipline the crawl window uses), and a comment whose
    time cell is blank or unrecognised is dropped and counted — never assigned a year, never
    kept as though it matched. Comparison is by calendar day (normalised), inclusive at both
    ends, matching bin_time.
    """
    start = str(params.get('comment_start') or '').strip()
    end = str(params.get('comment_end') or '').strip()
    if not start and not end:
        return rows
    if not start or not end:
        raise ValueError(t('comment.need_both', nid=label))
    lo = pd.to_datetime(start, errors='coerce')
    hi = pd.to_datetime(end, errors='coerce')
    if pd.isna(lo) or pd.isna(hi):
        raise ValueError(t('comment.bad_date', nid=label))
    if hi < lo:
        raise ValueError(t('comment.bad_range', nid=label))
    if not rows:
        return rows
    from services.data_analysis import _to_datetime

    times = _to_datetime(pd.Series([r.get('评论时间') for r in rows], dtype='object'))
    lo_day, hi_day = lo.normalize(), hi.normalize()
    out, unparsed = [], 0
    for row, valid, day in zip(rows, times.notna(), times.dt.normalize(), strict=True):
        if not valid:
            unparsed += 1  # a blank/unparseable 评论时间 is not a date; it cannot be shown to match
            continue
        if lo_day <= day <= hi_day:
            out.append(row)
    add_log(
        t(
            'comment.time_filtered',
            nid=label,
            start=start,
            end=end,
            kept=len(out),
            dropped=len(rows) - len(out),
        )
    )
    return out


def _execute_comment_node(node: dict, headless: bool = True, ctx: dict = None):
    """Comment crawler: article links in, comment rows out, batch by batch.

    Built on the same durable legs as the source crawler — the row ledger
    (already-collected comments are skipped, never re-fetched), the row store
    (resume restores position), and PartWriter (every settled batch hits disk
    as a readable file while the run is still going; a resumed writer adopts
    the parts the crashed run left behind, so kept-elsewhere rows are exactly
    the rows already in those files). The window is the run's own 无头/窗口 choice,
    honoured verbatim for every link platform: a headless Chrome carries a desktop
    fingerprint (#148) and even scroll-only panels were measured serving the same
    rows headless (zhihu comments 5/5, 2026-09-26), so no comment panel forces a
    window or rewrites the record.
    """
    from crawlers.comments import BLOCKED, DEAD, OK, CommentSession
    from services.part_writer import PartWriter, safe_stem

    params = node.get('params') or {}
    # A Data Source in comments mode carries the platform the user selected;
    # links from another site must not silently crawl a platform nobody chose.
    # The standalone Comment node has no platform param, so it stays mixed-input.
    want = str(params.get('platform') or '').strip().lower()
    # Which saved login (and device) walks these comments; blank is the historical
    # default account. The comment wall is a per-ACCOUNT rate limit — the reason
    # multi-account exists — so this must reach every get_crawler call below.
    account = str(params.get('account') or '').strip()
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
    per_article = as_bool(params.get('per_article_file'))
    keep_parts = as_bool(params.get('keep_parts'), True)
    fmt = 'json' if str(params.get('format') or 'csv') == 'json' else 'csv'
    nid = str(node.get('id') or '')
    # The same two filename components a crawl node writes: a comment table collected for
    # a stated stretch carries the same ambiguity, and a second pass over the same links
    # the same overwrite. A comments mode declares no window today, so only the record
    # stamp ever lands here.
    parts = _name_parts(params, (ctx or {}).get('export_stamp') or '')
    stem_base = safe_stem(f'{execution_state.get("workflow_name") or "comments"}-{nid}{parts}')

    row_sink = cursor_sink = None
    resumed_index = 0
    if ctx is not None:
        if as_bool(params.get('recrawl')) and not ctx.get('resume'):
            # 重新采集 means the same thing here as in a source crawl: the ledger that
            # says "this comment is already stored" is released, so the comments are
            # fetched again. Never on a resumed run — there that ledger *is* the resume
            # machinery, and clearing it would re-buy every comment already paid for.
            add_log(t('run.recrawl', n=ctx['store'].forget_items(_item_scope(ctx, node))))
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
    # Blocked platforms whose owning crawler named 风控 (back off) rather than a dead cookie
    # (re-save); kept per-platform because the two refusals carry opposite advice and a mixed
    # batch must not mislabel the cookie-only ones. ``login_seen`` marks that SOME blocked
    # platform named a login wall — that always defers to the actionable cookie verdict.
    risk_by: list[str] = []
    login_seen = False
    sessions = {}

    def _writer_for(idx: int, url: str) -> PartWriter:
        stem = f'{stem_base}-{idx:02d}' if per_article else stem_base
        if stem not in writers:
            # Same ledger contract as a source crawl: shards are recorded as they land, and only
            # when 「保留分片」 is on (with it off the merge deletes them, so there is nothing to clear).
            writers[stem] = PartWriter(
                Config.EXPORT_DIR,
                stem,
                fmt,
                part_size,
                keep_parts,
                on_write=(lambda path, kind: _record_run_file(ctx, nid, path, kind)) if keep_parts else None,
            )
        return writers[stem]

    try:
        for idx, url in enumerate(urls, 1):
            if not execution_state['running']:
                break
            if idx <= resumed_index:
                continue
            kind = platform_for(url)
            if kind not in sessions:
                # The run's 无头/窗口 choice is honoured verbatim (#148). A headless Chrome now
                # carries a desktop fingerprint, and a *scrolled* comment panel was measured
                # serving the same rows in both shapes (zhihu comments 5/5 headless, real profile,
                # 2026-09-26), so the old rule that forced a window onto scroll-only panels inside a
                # headless run is gone: no comment panel overrides what the user asked for.
                crawler = get_crawler(
                    kind,
                    headless=headless,
                    cookie_dir=Config.COOKIE_DIR,
                    use_profile=(ctx or {}).get('use_profile'),
                    abort=stop_requested,
                    # The node's chosen login walks its comments too: the comment rate
                    # limit is an ACCOUNT limit, which is the whole reason multi-account
                    # exists. Blank = the historical default session.
                    account=account,
                )
                # Registered for the same reason the source node registers its own:
                # a browser 停止 does not know about is a window the user watches keep
                # working — and this loop only asks "may I stop?" between URLs, so one
                # article's page walk could run the whole node out after the Stop.
                sessions[kind] = (
                    crawler,
                    # The comment engine reports per-URL facts; prefix them so a
                    # line in the shared console says which node it came from.
                    CommentSession(
                        crawler.driver,
                        log=lambda m: add_log(f'{t("comment.prefix")} {m}'),
                        abort=stop_requested,
                        # The live attribute, not just its value: see CommentSession.driver.
                        owner=crawler,
                    ),
                )
                # Last, so a refusal while building the session cannot leave a
                # registered browser that nothing here would ever close.
                execution_state['active_crawlers'].add(crawler)
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
                # 风控 and a dead cookie are OPPOSITE advice (back off vs re-save), and only the
                # owning crawler can tell them apart: it latches ``risk_blocked`` on a captcha and
                # ``login_wall`` on a login redirect. A platform that names neither keeps today's
                # bare-cookie verdict, so this changes nothing for them. Tracked PER platform (not
                # one boolean) so a mixed batch can only report 风控 when EVERY blocked platform
                # named it — otherwise the actionable cookie path wins.
                if getattr(_crawler, 'risk_blocked', False) and not getattr(_crawler, 'login_wall', False):
                    risk_by.append(kind)
                if getattr(_crawler, 'login_wall', False):
                    login_seen = True
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
            # Out of the registry first: if 停止 reaches it on its own thread while
            # this one is still unwinding, the two must not both be reaping it.
            execution_state['active_crawlers'].discard(crawler)
            _close_login_browser(crawler)

    files = [writer.finish() for writer in writers.values()]
    for _info in files:
        _record_run_file(ctx, nid, _info['path'], 'merged')
    if stop_requested():
        # The article loop above stops taking URLs once the run is not wanted, and then it
        # *returns* — so without this check a comment node cut short by 停止 settled DONE
        # over a partial table and the run never offered 继续. Everything it did collect is
        # finished into its part files first; what is dropped is the ``comment.done``
        # summary, because the executor's own 被停止 line is the one true sentence here.
        raise CrawlerStopped(t('crawl.stopped'))
    blocked_seen = bool(counts.get(BLOCKED))
    # 风控-only when EVERY blocked platform named 风控 and none named a login wall: then the
    # back-off verdict owns the node and no cookie flag is raised. Any cookie wall, or any blocked
    # platform that named neither refusal, defers to the actionable cookie path unchanged.
    risk_only = blocked_seen and not login_seen and set(blocked_by) <= set(risk_by)
    if blocked_seen and not risk_only:
        # A blocked article whose session did NOT name 风控 is the cookie-death case: raise the
        # toast flag so the user refreshes and resumes. 风控-only is the exception — its session
        # may be fine and re-saving a working cookie is the lie this repo refuses, so the flag
        # stays down and the verdict (below) is the back-off one. Every platform that returns a
        # bare BLOCKED without latching risk keeps the original "any block → cookie" behaviour.
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
    # The source-crawl path names a ledger-skip (``run.dedupe_skipped`` / ``..._all_skipped``) so a re-run
    # that stored nothing is not read as an empty table; the comment node dedupes through the VERY SAME
    # ``row_sink``, which tallies each refused item into ``ctx['skipped_seen'][nid]``. Reading that one tally
    # (never re-deriving it) keeps a single definition with the source path, and it already excludes what this
    # run genuinely stored. Measured live 2026-09-29: a repeat of one video's comments filed nothing, printed
    # 「共 0 条评论」 and named nothing — indistinguishable from a thread that has no comments. Skipped on a
    # resume (there the ledger IS the resume machinery and the result is prefilled); a wall is left to raise
    # its own single line, so a run that both skipped and was blocked is not silenced.
    skipped = (ctx.get('skipped_seen') or {}).get(nid) if ctx is not None else None
    if skipped and not ctx.get('resume'):
        add_log(t('run.dedupe_skipped', n=skipped))
        if not rows_out:
            add_log(t('run.dedupe_all_skipped'))
    if blocked_seen:
        # Failed (not done) → the run lands in the resume banner and 继续
        # retries exactly the articles the wall refused.
        # A sequence, not a '/'.join(): the {platform} slot localizes+joins only
        # list values and comma-joined strings, so a slash string printed raw keys.
        named = list(dict.fromkeys(blocked_by))
        target_word = named or want or t('run.cookieAnyPlatform')
        if risk_only:
            # 风控 the whole batch: name it and tell them to back off, NOT to re-save a
            # cookie — that is the source crawler's rule, applied to the comment node too.
            raise ValueError(t('run.riskControlled', platform=target_word))
        raise ValueError(t('run.cookieExpired', platform=target_word))
    rows_out = _filter_comments_by_time(rows_out, params, node_label(node, str(nid)))
    return rows_out


# `_execute_resume_node` now lives in backend/services/nodes.py (execute_resume_node, imported
# back under this name near the top); it reads its ledger through ctx['store'], not a global.


# Node types that never read the ROWS their inputs carry. Their data comes
# from somewhere else — the platform crawler, the already-uploaded file, the
# run store, (for `name`) nowhere at all, or (for `compile`) a visualize parent's
# LaTeX *dict*, which is not a row table at all. The "upstream came up empty →
# skip" rule below keys on `any parent result is a non-empty list`, so a compile
# hanging off a visualize (a dict) would be skipped as "no rows" — exempting it
# is what lets it read its source. A whole chain off a name node is the other case.
_NON_INPUT_NODES = frozenset({'source', 'upload', 'resume', 'name', 'comment', 'compile'})

#: Node types the console stays quiet about. A 工作流命名 node carries a label and
#: computes nothing; an 上传文件 node re-reads a file the user already pointed at.
#: Announcing "executing node …" and "node … done (2/4)" for those is two lines of
#: noise per node that has no work to report, and on a canvas of mostly-plumbing
#: nodes the lines that *do* matter — a crawl, a failure, a restored node — drowned
#: in them. Only the generic per-node chatter is suppressed: what these nodes say
#: about themselves (which file was loaded, how many rows) and anything that went
#: wrong still reaches the console.
_QUIET_NODE_TYPES = frozenset({'name', 'upload'})


def _settle_node_as_stopped(store, run_id: str, nid: str, label: str, wf_idx: int, err: str = ''):
    """Close one node as "the user stopped the run", whatever raised on its way here.

    Two deaths look identical and mean different things: a crawl that refuses (a wall,
    a bad parameter) is a node that FAILED, while a browser killed under a Stop leaves
    a dead session behind instead of an answer. Only the second is reported here, and
    the row keeps the driver's own text as its ``error`` so the detail view can still
    show what actually happened while the console says the one true sentence.

    `partial` rather than `skipped`: the rows already paid for stand and travel
    downstream, and 继续 must still be able to pick this node up again.
    """
    rows = execution_state['results'].get(nid)
    if not isinstance(rows, list):
        rows = store.load_rows(run_id, nid)
    store.finish_node(run_id, nid, NODE_PARTIAL, error=err)
    with _completed_lock:
        execution_state['stopped_node_ids'].add(nid)
    add_log(t('run.nodeStopped', nid=label, n=len(rows)), wf_idx=wf_idx)
    return rows, NODE_PARTIAL


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
    # The component pair says which workflow of the canvas this node ran in, which
    # is what lets one record of a serial multi-workflow run show its workflows
    # apart. An index alone would be a number the user cannot map back, and a name
    # alone collides the moment two components are unnamed — so both, and both from
    # the same thread-local the console tab routing already uses.
    dropped_stale = store.begin_node(
        run_id,
        nid,
        ntype,
        title=title,
        fingerprint=fingerprint,
        component=getattr(_wf_local, 'idx', None) or 0,
        component_name=getattr(_wf_local, 'name', '') or '',
    )
    if reusable and dropped_stale:
        reusable = False

    if reusable:
        rows = store.load_rows(run_id, nid)
        store.finish_node(run_id, nid, NODE_RESTORED)
        add_log(t('run.restored', nid=label, n=len(rows)), wf_idx=wf_idx)
        return rows, NODE_RESTORED

    def _carries_artifact(res: object) -> bool:
        # A visualize / compile parent hands down a DICT, not rows; that dict IS its product (a chart spec
        # carrying LaTeX, or a staged PDF). "empty upstream" must not read a chart as nothing, or a
        # chart→save(PDF) and a chart→compile would both be skipped before either runs.
        if not isinstance(res, dict) or res.get('error'):
            return False
        return any(key in res for key in ('latex', 'latex_table', 'pdf_file'))

    if (
        upstream
        and ntype not in _NON_INPUT_NODES
        and not any(isinstance(res, list) and res for _pid, res in upstream)
        and not (ntype in ('compile', 'output') and any(_carries_artifact(res) for _pid, res in upstream))
    ):
        # Everything this node would work on came up empty — usually because
        # its parent died with nothing. Skipping beats pretending we ran.
        # Types that ignore their inputs entirely are exempt: an empty
        # upstream says nothing about whether *they* can produce rows.
        store.finish_node(run_id, nid, NODE_SKIPPED)
        add_log(t('run.skipped_empty', nid=label), wf_idx=wf_idx)
        return [], NODE_SKIPPED

    try:
        # A stopped run executes no further node. The graph loops already check
        # ``running`` between levels and between workflows, so this is the narrow case
        # they cannot cover: the Stop arriving after a level has committed to its node
        # list — where the next thing that would happen is buying a fresh browser for
        # a run the user had already ended.
        if stop_requested():
            raise CrawlerStopped(t('crawl.stopped'))
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
    except CrawlerStopped:
        return _settle_node_as_stopped(store, run_id, nid, label, wf_idx)
    except Exception as e:
        if stop_requested():
            # The browser was killed under a Stop, so what reaches here is a dead
            # session, not a site refusing and not a node that broke. Reported the
            # same way on purpose: a stopped run whose summary blames the user's own
            # button press on their workflow teaches them never to press it.
            return _settle_node_as_stopped(store, run_id, nid, label, wf_idx, err=str(e))
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
        _note_heavy_result(result, label)
    # ``node_cancelled`` is the row runner's channel for an LLM node the Stop cut
    # short whose returned rows no longer carry the 未处理 marker (NER explodes it
    # away). pop() reads-and-clears so a node id cannot inherit a stale verdict.
    cancelled = bool(ctx.get('node_cancelled', {}).pop(nid, False)) if ctx else False
    if isinstance(result, list) and (
        cancelled or any(isinstance(r, dict) and any(v == ABORT_MARK for v in r.values()) for r in result)
    ):
        # A cancelled LLM node returns what it managed to answer; recording it
        # DONE would let resume restore it and the 未处理 gaps would stay
        # forever. PARTIAL keeps the rows but marks the node for a re-run,
        # where the answer cache makes only the missing rows cost anything.
        store.finish_node(run_id, nid, NODE_PARTIAL)
        return result, NODE_PARTIAL
    store.finish_node(run_id, nid, NODE_DONE)
    return result, NODE_DONE


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
        # The platform's turn is taken *here*, around the whole node, so the retry
        # inside the crawl runs within it: a retry that released the queue first would
        # collide with the very workflow it had been waiting behind. 评论采集 opens one
        # browser per platform it finds in its links and is not gated yet (stated in
        # the README next to the setting, so it is a known gap rather than a promise).
        platform = node.get('platform') or (node.get('params') or {}).get('platform', '')
        # The lane splits per ACCOUNT (crawl_gate._lane): the measured wall is one
        # SESSION searching twice, so two logins of one platform are two lanes and
        # may crawl at the same moment — which is the whole reason accounts exist here.
        account = str((node.get('params') or {}).get('account') or '').strip()
        # ``upstream`` reaches the source node itself: a link-list mode fed by an
        # upstream column reads the parent table here. Dropping it (the old behaviour)
        # made the wire a lie — the canvas showed a feed and the crawl ran the pasted
        # list nobody asked for.
        with crawl_gate.hold(platform, log=add_log, abort=lambda: not execution_state['running'], account=account):
            return _execute_source_node(node, headless, ctx=ctx, upstream=upstream)
    if ntype == 'upload':
        return _execute_upload_node(node)
    if ntype == 'resume':
        return _execute_resume_node(node, ctx or {'store': get_run_store(), 'run_id': ''})
    if ntype == 'process':
        op = node.get('operation') or node.get('params', {}).get('operation', '')
        return _execute_process_node(node, current_input, run_ctx=run_ctx or _llm_run_ctx(node, op, ctx))
    if ntype == 'analysis':
        return _execute_analysis_node(node, current_input, upstream=upstream, ctx=ctx)
    if ntype == 'visualize':
        return _execute_visualize_node(node, current_input, ctx=ctx)
    if ntype == 'tokenize':
        return _execute_tokenize_node(node, current_input)
    if ntype == 'compile':
        # ``upstream`` is the whole point: a compile node reads the LaTeX a visualize parent produced from
        # the (parent_id, result-dict) pairs, NOT from ``current_input`` (a dict upstream arrives as []).
        return _execute_compile_node(node, current_input, upstream=upstream, ctx=ctx)
    if ntype == 'output':
        # ``upstream`` reaches it so several incoming tables become ONE: a crawl split
        # over several batches is the normal reason a user wires two nodes into a save
        # node, and taking only the first exported one of them as if it were all of them.
        return _execute_output_node(node, current_input, upstream=upstream, ctx=ctx)
    # No branch claimed this type. ``validate`` refuses an unknown type before a run, so
    # this is defense in depth for a direct caller — but it must still refuse BY NAME:
    # returning [] here would settle the node DONE over an empty table (see AGENTS.md).
    raise ValueError(t('engine.unknown_node_type', nid=node_label(node, node.get('id')), type=str(ntype)))


#: Rows above which a node's result is worth mentioning out loud.
#:
#: ``execution_state['results']`` holds EVERY node's rows for the whole run — that is what a
#: preview and a child node read — so the row caps elsewhere do not bound memory at all.
#: ``RUN_MAX_ROWS_PER_NODE`` is a DISK cap (it stops a runaway crawl filling ``runs.db``),
#: and ``DATASET_MAX_ROWS`` caps one uploaded FILE; neither is about what is resident.
#: Measured, the list-of-dicts form costs about 3.1x the equivalent DataFrame (100k rows x
#: 4 columns: 17 MB → 53 MB), so a ten-node pipeline over one large table is where a
#: laptop runs out. This constant is the point at which the run should say so rather than
#: die three nodes later with an anonymous MemoryError.
HEAVY_RESULT_ROWS = 100000


def _note_heavy_result(rows, label: str) -> None:
    """Say out loud how much of this run is being held in memory.

    Deliberately not an error and not a refusal: a large table is often exactly what was
    asked for, and the run is still the user's to finish. What it must not be is invisible
    — an OOM has no node name attached to it.
    """
    if not isinstance(rows, list) or len(rows) < HEAVY_RESULT_ROWS:
        return
    add_log(t('run.heavy_result', nid=label, n=len(rows)))


def _close_active_crawlers(quit_timeout: float = 3.0):
    """Close the login/crawl browsers of live sessions, one at a time.

    Used to run `taskkill /F /IM chromedriver.exe` — which killed every
    chromedriver on the machine, taking down unrelated Selenium apps and test
    runs. Each registered crawler is now quit with a bounded grace, and only a
    driver that ignores it is force-killed — by PID, tree included, so the
    chrome children of *this* session die with it.
    """
    for crawler in list(execution_state['active_crawlers']):
        _close_login_browser(crawler, quit_timeout=quit_timeout)


# ─── Stop / Status API ─────────────────────────────────────────


#: How long a browser gets to close itself before 停止 kills its driver process.
#: Measured, the graceful answer is the fast one when it can be given at all: an idle
#: session quits in well under a second. What it can NEVER do is interrupt a command
#: already running — ``driver.quit()`` is an in-band request that chromedriver queues
#: *behind* the worker's own, so a Stop that waited on it watched the worker finish its
#: 40.0 s page load (or its 30.0 s in-page fetch) first. The kill is what ends a crawl;
#: this is only the grace given to a browser that is already done.
STOP_QUIT_GRACE = 0.8


def _mark_records_stopping() -> None:
    """Flip the records this run owns from 运行中 to 正在停止, on this thread.

    The worker still owes each of them a verdict, and measured, that debt can take
    tens of seconds to pay. A row that reads 运行中 for that long after the button said
    正在停止 is read as "停止 did nothing" — which is the complaint this answers, and
    the reason it is written here rather than left to the unwinding thread.
    ``finish_run`` overwrites it with the real verdict when that thread arrives.
    """
    opened = list(execution_state['open_records'])
    if not opened:
        return
    try:
        store = get_run_store()
    except Exception as e:
        add_log(t('run.recordWriteFailed', rid=' + '.join(opened), err=e))
        return
    for rid in opened:
        try:
            store.mark_stopping(rid)
        except Exception as e:
            add_log(t('run.recordWriteFailed', rid=rid, err=e))


def _settle_orphaned_records() -> int:
    """Settle a record this process opened and then abandoned without a verdict.

    ``promote_stale_runs`` only ever ran at startup, so a row whose write failed (a
    locked runs.db at exactly the wrong moment) or whose daemon thread died with the
    window stayed on 运行中 until the service was restarted. Measured: that restart was
    faster than 停止, which is how this gap was found.

    Two things keep it safe to ask the question of a live server. It is asked under
    ``_execute_lock`` — the same lock that claims a run — so it cannot settle a row a
    run an instant older has just opened; and it is limited to ``owned_records``, the
    ids THIS process wrote, so a second instance's live run is none of its business.
    """
    thread = execution_state.get('thread')
    if execution_state['running'] or (thread is not None and thread.is_alive()):
        return 0
    owned = set(execution_state.get('owned_records') or set())
    if not owned:
        return 0
    with _execute_lock:
        # Re-read inside the lock: a claim that started while we were deciding has
        # now either finished or cannot proceed.
        thread = execution_state.get('thread')
        if execution_state['running'] or (thread is not None and thread.is_alive()):
            return 0
        try:
            promoted = get_run_store().promote_stale_runs(
                only=owned,
                note=t('run.interrupted_by_dead_worker'),
            )
        except Exception:
            # A store we cannot open is a store we cannot settle; the panel says so
            # through its own error, and 运行中 is not a lie worse than no answer.
            return 0
    if promoted:
        # Said out loud because it otherwise looks like the panel decided to lie: a
        # row flips to 已中断 with no run having ended in front of the user.
        add_log(t('run.reconciled', n=len(promoted)))
    return len(promoted)


@app.route('/api/workflow/stop', methods=['POST'])
def stop_workflow():
    # Hold the claim lock across the guard-and-write. ``_begin_run`` claims a run under
    # this same lock, so a run finishing right now cannot hand off to a queued one and
    # then have ``running=False``/``stopping=True`` land on that brand-new run — the
    # interleaving that made a stop aimed at run A silently kill run B. The idle check
    # and every state write below are therefore one atomic decision.
    with _execute_lock:
        thread = execution_state.get('thread')
        if not execution_state['running'] and not (thread is not None and thread.is_alive()):
            # Nothing is running and nothing is unwinding. Answering as if a stop had been
            # honoured would leave `stopping` standing with no run behind it — and
            # `stop_requested()` hands that flag to every crawl, so the next one would
            # answer "the user stopped me" to a button nobody pressed.
            return jsonify({'ok': True, 'browsers': 0, 'records': [], 'idle': True})
        if execution_state['executor']:
            execution_state['executor'].stop()
        # Tell any row-by-row LLM loop to bail out at the next row boundary —
        # finished rows are already checkpointed and stay in results.
        execution_state['cancel_event'].set()
        # The run is over as far as the browser is concerned; the verdict is not. The
        # worker thread still owes `settle`/`finish_run`, and until it pays the record
        # reads "stopping" — not "running", which is what made a stop look ignored, and
        # not an outcome the run has not written yet.
        execution_state['stopping'] = True
        execution_state['running'] = False
        _mark_records_stopping()
        crawlers = list(execution_state['active_crawlers'])
        execution_state['active_crawlers'].clear()
        # A daemon thread starts with a fresh (default) language; capture the request's
        # so every line this stop path prints — including run.browserStuck below — reads
        # in the UI's own language, not Chinese in an English panel.
        lang = get_lang()

    def _reap(c):
        set_lang(lang)
        _close_login_browser(c, quit_timeout=STOP_QUIT_GRACE)

    def _finish_stop():
        set_lang(lang)
        # One thread per browser. Reaping them in series made the LAST crawl of a
        # parallel run wait behind every earlier reap, and the run record cannot be
        # written until all of them are over (`pool.shutdown` waits by design).
        reapers = [threading.Thread(target=_reap, args=(c,), daemon=True) for c in crawlers]
        for r in reapers:
            r.start()
        for r in reapers:
            r.join(STOP_QUIT_GRACE + 12)
        # A browser the worker registered *after* the snapshot above is still in the
        # registry, and nothing else on this path would ever reach it: the node that
        # bought it is standing in a page load, not in its finally.
        _close_active_crawlers(quit_timeout=STOP_QUIT_GRACE)

    # Closing a browser is quick but not instantaneous, and a visible Chrome with a
    # pending dialog can take its bounded grace to die. Doing it inline made the Stop
    # *request* wait on it, so the button, its toast and the run-record refresh all
    # hung behind teardown the user can already see happening. It runs on a side
    # thread now; the crawlers are already out of the registry, so the worker's own
    # finally cannot double-close them, and a browser the stop thread has not reached
    # yet is closed by that finally when the run unwinds.
    threading.Thread(target=_finish_stop, daemon=True).start()
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
    return jsonify({'ok': True, 'browsers': len(crawlers), 'records': list(execution_state['open_records'])})


@app.route('/api/workflow/status', methods=['GET'])
def workflow_status():
    # One atomic snapshot of every console buffer. The tail and its total must be
    # read together (and under the same lock the writers hold): a concurrent
    # _push_log that advanced ``_log_total`` between reading the tail and the total
    # would hand the browser a pair that disagree, and its delta cursor then marks
    # the gap already-seen and silently drops a few lines off the console.
    tail = _status_tail(request)
    mode = execution_state.get('_mode', 'serial')
    with _completed_lock:
        global_logs = execution_state['logs'][-tail:]
        global_total = execution_state['_log_total']
        wf_view = [
            (
                wk,
                execution_state['_wf_logs'][wk][-tail:],
                execution_state['_wf_log_total'].get(wk, len(execution_state['_wf_logs'][wk])),
            )
            for wk in sorted(execution_state['_wf_logs'].keys())
        ]
    wf_list = [
        {
            'id': wk,
            # The console tab bar speaks the workflow's name (set by the
            # 工作流命名 node), not a positional 'WF2' the user cannot map
            # back to a canvas.
            'name': execution_state['_wf_names'].get(wk) or f'#{wk + 1}',
            'logs': logs,
            # How many lines exist in total, so the browser can compute the
            # delta even after the tail truncation above.
            'total': total,
        }
        for wk, logs, total in wf_view
    ]

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

    thread = execution_state.get('thread')
    return jsonify(
        {
            'running': execution_state['running'],
            # A Stop flips `running` off on the request thread, but the worker still
            # owes the record its verdict — and it writes `stopping` into that record
            # itself, so the panel can already show 正在停止. `stopping` here is the
            # same promise for the console: the browser must not print an outcome the
            # run has not written, nor stop reading until the record has landed. The
            # worker's own finally clears it, so it never outlives the run.
            'stopping': bool(execution_state.get('stopping')),
            'settling': bool(not execution_state['running'] and thread is not None and thread.is_alive()),
            'logs': global_logs,
            'log_total': global_total,
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

    # A live run's crawls execute on the executor's pool threads (parallel mode), not
    # on 'run'. Killing one injects SystemExit between acquiring a browser and
    # registering it, orphaning Chrome and holding its profile lock — the very harm the
    # 'run' guard exists for. While a run is live those threads are off-limits; Stop is
    # the graceful door.
    if execution_state['running'] and target.name.startswith('ThreadPoolExecutor'):
        return jsonify({'ok': False, 'error': 'This is a live crawl worker; use Stop rather than killing it'}), 403

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


# The /api/data/{upload,datasets,paste,inspect,preview} handlers (list/detail/delete/rename
# included) now live in backend/api/data.py (Blueprint `data_bp`); see the register below.


# /api/analysis/{run,train} + the _ML_MODEL_TYPES/_ML_LABEL_COLUMNS constants now live in
# backend/api/analysis.py (Blueprint `analysis_bp`); see the register below. The
# frontend-contract test reads those constants from api.analysis. Behaviour unchanged.


# /api/visualize/render (the standalone chart door) now lives in backend/api/visualize.py
# (Blueprint `visualize_bp`); see the app.register_blueprint(visualize_bp) below. It calls the
# same services.latex_outputs / services.visualizer that _execute_visualize_node does, so the
# HTTP preview and the node cannot drift. Path and behaviour are unchanged.


# ─── One-click report ──────────────────────────────────────────

# The /api/report/{generate,view,pdf,studio-images} cluster plus its report-only helpers
# (_report_nodes, _find_chrome) now live in backend/api/report.py (Blueprint `report_bp`); see
# the app.register_blueprint(report_bp) below. The /api/export/save route shares
# backend/api/exports.py with the read side /api/exports/{list,download,delete,clear}; /api/locks
# lives in api/locks.py. Paths and behaviour are unchanged — see the register_blueprint(...) calls.


# ─── Stats API ─────────────────────────────────────────────────


# The /api/stats/* cluster lives in api/stats.py (imported above); registered here so app-level
# before_request / CORS still wrap it and the URLs are unchanged.
app.register_blueprint(stats_bp)
app.register_blueprint(locks_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(data_bp)
app.register_blueprint(studio_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(visualize_bp)
app.register_blueprint(report_bp)


# ─── Cookie API ────────────────────────────────────────────────

# One list, so a platform can never be half-wired: status, flows, generation and
# verification all walk the same tuple, which is the crawler registry's order.
# Derived from the cookie store's own list, so a platform added there cannot be
# left out of the panel, the flows or the status endpoint.
COOKIE_PLATFORMS = CookieManager.PLATFORMS


@app.route('/api/cookies/status', methods=['GET'])
def cookie_status():
    """What the panel is allowed to know about saved logins: which accounts exist, and how fresh.

    ``cookies[platform]`` used to be ``cookie_manager.exists(platform)`` — the BLANK account's
    file only. A user who keeps every login under a name therefore saw 「没有 Cookie」 for a
    platform he crawls with daily, and the status line could not answer the question he was
    actually asking, which is about the account in the box.

    ``rows`` answers it per ``(platform, account)``: how many entries, how many of them will
    not outlive a window, when it was saved, and what that account's own browser directory
    knows. Labels travel as catalogue keys because 默认账号 / 默认账号2 are words this program
    generated, while ``work`` is a word the user typed and must be shown exactly as typed —
    so the row carries ``label_key`` (empty for a typed name) plus its arguments, and the
    browser translates one and prints the other.

    **No cookie value ever leaves this endpoint**, and the sentence is worth stating because
    the panel is the one surface a stranger could stand in front of on a cloud deploy: the
    counts are lengths, the date is a ``stat``, the profile half is one marker file, and the
    directory walk that would cost real time is switched off here (``size=False``) — a
    management row is not worth reading a browser's cache index.
    """
    accounts = {platform: cookie_manager.accounts_in_order(platform) for platform in COOKIE_PLATFORMS}
    rows = []
    for platform, names in accounts.items():
        for account in names:
            path = cookie_manager.path_for(platform, account)
            profile = browser_profiles.status(platform, has_cookie=True, cookie_path=path, account=account, size=False)
            label_key, label_args = cookie_manager.account_label_key(account)
            rows.append(
                {
                    'platform': platform,
                    'account': account,
                    'entry_key': cookie_preflight.entry_key(platform, account),
                    'label_key': label_key or '',
                    'label_args': label_args,
                    'entries': cookie_manager.entry_count(platform, account),
                    'session_only': cookie_manager.session_only_count(platform, account),
                    'saved_at': cookie_manager.saved_at(platform, account),
                    'profiles_on': profile['enabled'],
                    'profile_exists': profile['exists'],
                    'profile_used': bool(profile['used_at']),
                    'profile_imported': profile['imported'],
                    'needs_refresh': profile['needs_refresh'],
                }
            )
    return jsonify(
        {
            'ok': True,
            # 「this platform has a login somewhere」 — not "the blank file exists".
            'cookies': {platform: bool(names) for platform, names in accounts.items()},
            'accounts': accounts,
            'rows': rows,
        }
    )


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


def _flag_or_none(value):
    """A tri-state flag off a JSON body: True, False, or None for "follow the setting".

    Absence has to stay absence. Coercing a missing key to ``False`` turns one
    dialog's answer into a silent global override of a setting the user configured,
    which is the rule :func:`crawlers.get_crawler` documents for ``use_profile``.
    """
    if isinstance(value, bool):
        return value
    text = str(value or '').strip().lower()
    if text == 'true':
        return True
    if text == 'false':
        return False
    return None


@app.route('/api/cookies/preflight', methods=['POST'])
def preflight_cookies():
    """Ask every platform of this canvas, at once, whether its session still gets us in.

    One request for the whole canvas rather than one per platform: the page has to be
    able to name *which* source is dead in the dialog it shows before 执行, and it
    cannot do that if it has to wait on each probe in turn.

    This endpoint answers the question it is asked; it does not decide whether to ask
    it. That is ``cookie_preflight_before_run`` in the browser
    (``_preflightCookies`` in workflow.js), so the panel's own 验证 button, a hand-made
    request and a future caller all get the same facts from the same code.

    ``text`` is rendered here rather than keyed: the sentences live in the backend
    catalogue next to the crawler that decides them, and the panel already treats
    server-side wording as the single source (see ``/api/cookies/flow``).
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    raw = data.get('platforms')
    if raw is None:
        # Absent means "nothing on this canvas crawls anything", which is an answer,
        # not a mistake. A field that is there but is not a list is a different thing
        # and is refused below.
        raw = []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return jsonify({'ok': False, 'error': t('api.platformsRequired')}), 400
    # Each entry is a platform string (the shape before accounts existed, still
    # accepted) or a {platform, account} pair. Only the PLATFORM is knowledge-checked —
    # an account is a filename segment the store validates, and a name nobody saved is
    # answered 「no cookie」 by the probe, not refused at the door. ``check`` normalizes
    # the same way, so the door and the probe never disagree about what an entry is.
    refused = [plat for plat, _acct in (cookie_preflight.entry_of(p) for p in raw) if not cookie_preflight.knows(plat)]
    if refused:
        # The names arrive from the browser and each one would buy a Chrome, so an
        # unrecognised name is refused whole instead of being filtered out quietly — a
        # silent drop reads as "checked and fine" for the platform nobody checked.
        # A name a *crawler* knows but the cookie store does not (WeChat) passes: the
        # gate answers it 「不需要登录」 without opening anything.
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=refused[0])}), 400
    use_profile = _flag_or_none(data.get('use_profile'))
    fresh = _flag_or_none(data.get('fresh')) is True
    results = cookie_preflight.check(raw, use_profile=use_profile, fresh=fresh)
    for verdict in results.values():
        verdict['text'] = cookie_preflight.describe(verdict)
    blocked = [name for name, verdict in results.items() if verdict['blocking']]
    unclear = [name for name, verdict in results.items() if verdict['state'] == cookie_preflight.UNKNOWN]
    return jsonify(
        {
            'ok': True,
            'results': results,
            # Split server-side so the browser cannot invent its own reading of a
            # state it does not know: 「拦下来」 and 「没核得上」 are different answers.
            'blocked': blocked,
            'unclear': unclear,
            'probed': any(v['probed'] for v in results.values()),
        }
    )


#: One plant at a time: two browsers writing the same profile would each report a session
#: count that the other had already overwritten.
_PROFILE_REFRESH_LOCK = threading.Lock()


def _plant_saved_cookie_into_profile(platform: str, account: str) -> str | None:
    """Give this account's own browser the file that was just saved, and say what happened.

    The import-once rule is right for a crawl — planting an older snapshot over a live,
    rotating session is how weibo's ``SUB``/``SUBP`` get thrown away — but a paste in this
    panel is not an older snapshot: it is the newest login the user has, and the browser that
    will do the crawling is the only place it can still be used. Requiring a separate button
    for that made the user re-take a session, watch it get saved, and then get crawled with
    the previous one.

    ``None`` means nothing to do and nothing to say: profiles are switched off, and then every
    crawl is planted from the file in a throwaway browser, so buying one to change nothing would
    cost a browser and claim a thing that did not happen. Anything else gets a sentence, because
    「保存成功」 and 「这次没能进到 Profile」 look identical from a paste box otherwise.

    A profile that has never been opened is *created and planted now*, not left for the first
    crawl: one cookie, one profile, and a login sitting in a file its own browser has never read
    is exactly the state the panel used to leave behind (the directory comes from
    ``profile_dir_for``, which ``get_crawler`` calls before Chrome starts).

    On a cloud host the pristine template is made here first, before that directory exists:
    it is the one thing that has to precede a new account, and this is the one moment the
    user is present to ask for a device. It costs one extra blank browser — once per
    server, never again while the template stands — and on a machine with no
    「浏览器生成」 button that browser is how the directory gets made at all.
    """
    if not browser_profiles.is_enabled():
        return None
    if Config.CLOUD_MODE:
        ensure_profile_template()
    profile = browser_profiles.platform_dir(platform, account)
    if browser_profiles.is_busy(profile) or execution_state['running']:
        # The file is newer than the session in that browser, and `needs_refresh` is what the
        # next crawl reads to decide — so this is a wait, not a lost update.
        return t('cookie.plant.deferred', platform=platform)
    if not _PROFILE_REFRESH_LOCK.acquire(blocking=False):
        return t('cookie.plant.deferred', platform=platform)
    try:
        try:
            crawler = get_crawler(
                platform,
                # The plant is one page load on that site, and a headless Chrome now carries the
                # desktop fingerprint (#148) so every platform — douyin and X included — serves it.
                headless=True,
                cookie_dir=Config.COOKIE_DIR,
                use_profile=True,
                refresh_cookies=True,
                account=account,
            )
        except Exception as e:
            logger.debug('the plant browser for %s did not come up: %s', platform, e)
            return t('cookie.refresh.failed', err=str(e)[:160])
        try:
            planted = int(getattr(crawler, 'cookies_loaded', 0))
        finally:
            _close_login_browser(crawler)
    finally:
        _PROFILE_REFRESH_LOCK.release()
    # The profile now holds a different session than the one the last probe looked at.
    cookie_preflight.invalidate(platform)
    # Measured on a real Chrome: a cookie without an expiry is not written to the profile store
    # at all, so it dies with the window that was opened to plant it. Saying only 「已更新」 would
    # promise a transfer that partly did not happen.
    fading = cookie_manager.session_only_count(platform, account)
    message = t('cookie.refresh.done', platform=platform, n=planted)
    return message + '\n' + t('cookie.refresh.sessionOnly', n=fading) if fading else message


@app.route('/api/cookies/save', methods=['POST'])
def save_cookies():
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = data.get('platform', '')
    cookies = data.get('cookies', [])
    account = str(data.get('account') or '').strip()
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        # The platform becomes part of a filename — refuse anything else.
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        # The account is the OTHER filename segment that comes from a text box.
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
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
        # 留空 = 「一个还没起名字的登录」：第一份是默认账号，第二份是默认账号2, never an overwrite.
        # A second blank paste cannot be told apart from re-pasting the first one (two logins of one
        # platform carry the same cookie *names*, and the value that would tell them apart is the one
        # that rotates), so the only reading that cannot destroy a paid-for login is "this is a new
        # one". Overwriting a specific account is what choosing that account in the box means.
        if not account and cookie_manager.exists(platform):
            account = cookie_manager.next_free_account(platform)
        cookie_manager.save(platform, kept, account)
        # The file this platform would be planted from just changed, so the cached
        # verdict about the previous one has to go with it.
        cookie_preflight.invalidate(platform)
        # No ``add_log`` beside this: ``CookieManager.save`` logs the same sentence and
        # ``LogBufferHandler`` forwards every logger call into the console, so the
        # narration the panel wanted was already there — twice, for one paste.
        # One cookie, one profile: the browser that will crawl with this login takes the
        # new file in now, instead of the user pressing a second button to say so.
        planted = _plant_saved_cookie_into_profile(platform, account)
        # 「已保存」 is not the whole answer any more: a blank name can have become 默认账号2, and
        # the panel has to say which login it just wrote — otherwise the user cannot tell whether
        # the account he meant is the one that changed.
        message = t('cookie.savedAccount', platform=platform, account=cookie_manager.label_of(account))
        return jsonify(
            {
                'ok': True,
                'message': f'{message}\n{planted}' if planted else message,
                'count': len(kept),
                'account': account,
                'account_label': cookie_manager.label_of(account),
                'profile_note': planted or '',
            }
        )
    except (OSError, ValueError) as e:
        # One line for one failure. ``LogBufferHandler`` forwards every logger call to
        # the console (its ``format`` is the message alone, so the traceback still goes
        # only to the log file) — the ``add_log`` beside it printed the same sentence a
        # second time, and the console showed 「保存 Cookie 失败」 twice in a row.
        logger.exception(f'{t("misc.cookie_save_failed")}: {str(e)[:120]}')
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/cookies/rename', methods=['POST'])
def rename_cookie_account():
    """Give a saved login a new label — its cookie file AND that account's browser directory.

    Each refusal names what it refused, because the alternative is a panel that says
    「已重命名」 about a session still filed under the old name. The blank account is refused
    structurally: 默认账号 owns no directory of its own (it IS the platform's), so naming it
    would move the parent of every other account of that platform — and since the user is told
    an account and its profile are one thing, the two halves move together or nothing moves.
    """
    body = _json_body()
    if body is None:
        return _bad_body()
    platform = str(body.get('platform') or '').strip()
    # Folded through the manager's own key, so 「the default account」 has ONE meaning here:
    # a blank from an old caller and the name ``default`` are the same login, and the checks
    # below cannot be stepped around by spelling it the other way.
    account = CookieManager.key(body.get('account'))
    to = CookieManager.key(body.get('to'))
    if not CookieManager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if body.get('to') is None or str(body.get('to')).strip() == '':
        return jsonify({'ok': False, 'error': t('api.cookieRenameEmptyTarget')}), 400
    if not CookieManager.is_account(account) or not CookieManager.is_account(to):
        return jsonify({'ok': False, 'error': t('api.cookieRenameBadName')}), 400
    if account == CookieManager.DEFAULT_ACCOUNT:
        return jsonify({'ok': False, 'error': t('api.cookieRenameDefault')}), 400
    if to == CookieManager.DEFAULT_ACCOUNT:
        # Renaming ONTO the default name would aim a named account at the platform's own
        # file — the same topology problem as renaming the default away from it, seen from
        # the other side, and it must be said rather than quietly overwriting a login.
        return jsonify({'ok': False, 'error': t('api.cookieRenameTaken')}), 409
    if account == to:
        return jsonify({'ok': False, 'error': t('api.cookieRenameSameName')}), 400
    manager = CookieManager(Config.COOKIE_DIR)
    if not manager.exists(platform, account):
        return jsonify({'ok': False, 'error': t('api.cookieRenameNoSource')}), 404
    try:
        # The device first: a profile that will not move (a browser is inside it, or the name
        # is taken) must stop the file too — otherwise the new label is born pointing at a
        # directory that is still called the old one, and the next crawl opens a stranger.
        profile_moved = browser_profiles.rename_account(platform, account, to)
        manager.rename(platform, account, to)
    except ValueError as e:
        return jsonify({'ok': False, 'error': _rename_refusal(e)}), 409
    except OSError as e:
        return jsonify({'ok': False, 'error': t('api.cookieRenameFailed', err=str(e)[:160])}), 500
    # A rename changes which file answers 「does this account have a login」, so a cached
    # verdict about the old name is now a statement about a file that is not there.
    cookie_preflight.invalidate(platform)
    return jsonify(
        {
            'ok': True,
            'platform': platform,
            'account': to,
            'profile_moved': profile_moved,
            # Which of the two sentences, by what actually moved: an account whose browser was
            # never opened has no directory to take along, and 「一起搬过去了」 would be a claim
            # about a device that does not exist.
            'message': t(
                'cookie.renamed' if profile_moved else 'cookie.renamedFileOnly',
                platform=platform,
                old=manager.label_of(account),
                new=manager.label_of(to),
            ),
        }
    )


def _rename_refusal(error: ValueError) -> str:
    """Say which refusal happened, because the three want three different actions.

    Waiting for a crawl, choosing another name and finding the file gone are not one
    「失败」 — and the ValueError text is this module's own (see ``CookieManager.rename`` and
    ``browser_profiles.rename_account``), so matching it is matching code, not a site.
    """
    text = str(error)
    if 'in use' in text:
        return t('api.cookieRenameBusy')
    if 'already exists' in text:
        return t('api.cookieRenameTaken')
    if 'Invalid account' in text or 'cannot be renamed' in text:
        return t('api.cookieRenameBadName')
    return t('api.cookieRenameFailed', err=text[:160])


@app.route('/api/cookies/delete', methods=['POST'])
def delete_cookies():
    """Throw away the saved cookie *file* for one platform.

    The honest scope matters here, and it is why the response carries
    ``profile_holds``: a file is only what a *throwaway* browser is planted from.
    A platform profile that has logged in keeps its own session in
    ``data/chrome_profile/<platform>``, and deleting the snapshot does not sign that
    device out (see :mod:`browser_profiles`, where the file is imported once and
    never planted again). Saying 「已删除，已退出登录」 would send the user to re-login
    over a session that is still live, and hide the case that genuinely needs a
    profile reset.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    account = str(data.get('account') or '').strip()
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
    if not cookie_manager.exists(platform, account):
        # Not a silent success: the panel asked to remove something that is not
        # there, and 「已删除」 would leave the user believing a stale file was replaced.
        return jsonify({'ok': False, 'error': t('cookie.delete.none', platform=platform)}), 404
    try:
        cookie_manager.delete(platform, account)
    except OSError as e:
        logger.exception(t('cookie.delete.failed', err=str(e)[:120]))
        return jsonify({'ok': False, 'error': str(e)}), 500
    cookie_preflight.invalidate(platform)
    holds = bool(browser_profiles.is_enabled() and browser_profiles.is_used(platform, account))
    message = t('cookie.deleted', platform=platform)
    if holds:
        # ``CookieManager.delete`` already logged the deletion, and that line reaches
        # the console as well — so the handler adds only the fact that line cannot
        # carry, instead of narrating the whole answer a second time.
        extra = t('cookie.delete.profileHolds', platform=platform)
        message += '\n' + extra
        add_log(extra)
    return jsonify({'ok': True, 'message': message, 'profile_holds': holds})


@app.route('/api/profiles/delete', methods=['POST'])
def delete_profile():
    """Throw away one account's browser PROFILE directory — the device, not the cookie file.

    This is the counterpart the cookie-delete cannot be: ``delete_cookies`` removes only the
    snapshot a throwaway browser is planted from, and a platform crawled inside its own profile
    keeps its live session in ``data/chrome_profile/<platform>[/<account>]`` — so signing that
    device out needs this separate action. The two stay independent by design: a user may retire
    the saved cookie and keep logging the profile in, or reset the device and keep the file.

    Every refusal names itself, and the **default** account is refused structurally (the panel
    disables it too): its browser data is the platform root that nests every named account, so
    「delete」 there would silently wipe them all — the same reason ``rename_cookie_account``
    refuses to rename it. A live browser holding the directory is refused so a running crawl is
    never pulled out from under.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform') or '').strip()
    account = CookieManager.key(data.get('account'))
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if not CookieManager.is_account(account):
        bad = str(data.get('account') or '')
        return jsonify({'ok': False, 'error': t('api.profileDeleteBadName', account=bad)}), 400
    if account == CookieManager.DEFAULT_ACCOUNT:
        return jsonify({'ok': False, 'error': t('api.profileDeleteDefault', platform=platform)}), 400
    try:
        result = browser_profiles.delete(platform, account)
    except ValueError as e:
        text = str(e)
        if 'in use' in text:
            return jsonify({'ok': False, 'error': t('api.profileDeleteBusy', platform=platform, account=account)}), 409
        return jsonify({'ok': False, 'error': t('api.profileDeleteDefault', platform=platform)}), 400
    except OSError as e:
        logger.exception(t('cookie.delete.failed', err=str(e)[:120]))
        return jsonify({'ok': False, 'error': str(e)}), 500
    if result == 'absent':
        # Not a silent success: the panel asked to remove a device that is not there, and
        # 「已删除」 would report a reset that did not happen.
        return jsonify({'ok': False, 'error': t('cookie.profileDelete.none', platform=platform, account=account)}), 404
    # The device that held a live session is gone, so a cached "does this account have a login"
    # verdict about that profile is now a statement about a browser that no longer exists.
    cookie_preflight.invalidate(platform)
    add_log(t('cookie.profileDeleted', platform=platform, account=account))
    return jsonify(
        {
            'ok': True,
            'platform': platform,
            'account': account,
            'profile_deleted': True,
            'message': t('cookie.profileDeleted', platform=platform, account=account),
        }
    )


_COOKIE_JOB_LOCK = threading.Lock()
_COOKIE_JOB = {
    'active': False,
    # Which single-flight action owns the browser: a login (waits for the user
    # to press Done) or a verification (runs to completion by itself). The panel
    # shows its "Done — I logged in" button only for the first.
    'kind': '',
    'platform': '',
    # The account the live job owns its browser AS — carried so a second request
    # can be refused with the SESSION that is busy, not just the platform.
    'account': '',
    'phase': '',  # login: starting → waiting → saved | cancelled | error; verify: verifying → verified | error
    'error': '',
    'count': 0,
    'entry': '',  # the URL the browser was actually sent to
    'facts': {},  # verify: what the stored cookie unlocked
    'lines': [],  # verify: those facts, already in the user's language
    'cancel': threading.Event(),
    'confirm': threading.Event(),
}


def _stuck_where(thread) -> str:
    """Where a side thread is standing right now — its own top frame, file and line.

    ``sys._current_frames`` is the only thing that can answer this about a thread that is
    not cooperating: the situation is a ``close()`` that never returns, so nothing it logs
    itself will ever be heard. The address of a hang is the difference between "a browser
    is wedged somewhere" and a line a developer can go and read.
    """
    frame = sys._current_frames().get(thread.ident)
    if frame is None:
        return ''
    # The frame ``_current_frames`` returns is the *innermost* one — the call that is not
    # coming back. Alone that is usually a lock or a socket inside somebody else's library,
    # which names the wait but not the crawler waiting, so three callers come along: the
    # first word is what to grep, the rest say whose browser this is.
    frames = []
    while frame is not None and len(frames) < 4:
        code = frame.f_code
        frames.append(f'{code.co_name} at {os.path.basename(code.co_filename)}:{frame.f_lineno}')
        frame = frame.f_back
    return ' ← '.join(frames)


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
    if isinstance(getattr(crawler, 'driver', None), DeadDriver):
        # One browser asked about twice — the stop thread and the worker's own finally both reach
        # this for a parallel run. There is nothing left to close, and the check has to happen
        # before the line below: reading ``driver.service.process.pid`` off a dead session raises
        # ``CrawlerStopped``, which is a ``BaseException`` and so walks straight out of the
        # ``suppress(Exception)`` guarding it, killing the thread on its way to the *next* browser.
        # Its profile is deliberately not released from here either: a lock handed back for a
        # session the worker is still scrolling in lets the next crawl of that platform open a
        # second Chrome on the same directory.
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
            # Replacing the session is what makes 停止 mean now, and it is the only reliable way to
            # do it: the reap frees the command the worker is *inside* (a dead driver resets the
            # socket, measured 1.7 s) but the worker's NEXT command opens a fresh connection to a
            # port nobody holds, and selenium's pool re-sends a failed connect four times —
            # measured 16.3 s each, which is how a mid-walk stop took 29.6 s to settle. See
            # ``crawlers.base.DeadDriver`` for why the refusal is a ``BaseException``.
            crawler.driver = DeadDriver()
    elif waiter.is_alive():
        # No process number to aim a kill at, and no promise this thread ever returns.
        # The harm is specific and has to be said: ``crawler.close()`` is what releases the
        # platform's profile lock, so that directory stays claimed until wherever it is
        # stuck unsticks — the next crawl of this platform waits up to
        # ``Config.PROFILE_LOCK_TIMEOUT`` for it. Silence here reads as "closed", while the
        # user may be looking at the window.
        domain = getattr(crawler, 'domain', '')
        add_log(t('run.browserStuck', platform=domain, seconds=int(Config.PROFILE_LOCK_TIMEOUT)))
        # ``debug`` on purpose: the console line above is the user's, and this one is for
        # whoever reads ``logs/`` — where English is what a person grepping for a hang wants,
        # and a translated frame would put a stack address through the message catalogue.
        logger.debug(
            'the browser of %s could not be closed and has no readable process id; still running at %s',
            domain,
            _stuck_where(waiter),
        )


def _cookie_login_worker(platform: str, wait_seconds: int, entry_url: str = '', lang: str = '', account: str = ''):
    """Drive one login window from the request thread to its own daemon.

    ``set_lang`` is the first thing it does: thread-locals are not inherited, so
    without it every line this worker wrote into the console panel was Chinese
    whatever language the interface was showing — the run worker pins its own
    language, and these two silently did not.

    The request thread used to sleep for the whole wait (up to 600 s), so any
    proxy or tab timeout turned a perfectly good login into a broken fetch and
    an orphaned browser. Progress lives in _COOKIE_JOB now; the panel polls it.

    *entry_url* overrides which page opens: some platforms only plant the
    cookies the crawler needs while sitting on a page the user picks (a note or
    video link), so the panel lets that link be pasted in — validated against
    the crawler's own host list before it is ever opened.

    *account* is which login of the platform this window captures: the browser
    opens that account's profile and the jar is saved to that account's file.
    Blank is the platform's default session — the only one that existed before
    multi-account.
    """
    job = _COOKIE_JOB
    crawler = None
    set_lang(lang)
    try:
        # ``for_login`` is the point of this window: a human reads it. The crawler
        # default blocks images to save seconds per navigation, and the QR code a
        # user must scan is an ``<img>`` — with the blocker on, the panel opened a
        # window that could not be completed at all.
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR, for_login=True, account=account)
        url = entry_url or crawler.login_url
        if not url:
            raise ValueError(t('api.unsupportedPlatform', platform=platform))
        crawler.driver.get(url)
        job['entry'] = url
        # One line for one event, carrying both facts it was split across: which
        # platform's window opened, how long it will wait, and the page it landed on
        # (the entry link is what a user checks when the window shows something
        # unexpected). Two consecutive console lines said one thing each.
        add_log(t('wf.browser_opened', platform=platform, n=wait_seconds, url=url))
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
        cookie_manager.save(platform, cookies, account)
        # This jar was read OUT OF the platform's own profile browser, so the profile is not behind
        # the file: without this line the panel would go on offering 「把 Cookie 更新进 Profile」,
        # a button that here would overwrite a live session with a copy of itself. Only when a
        # profile really exists — a run that chose 本次不用 Profile has no live session to spare.
        if browser_profiles.is_enabled() and browser_profiles.is_used(platform, account):
            browser_profiles.remember_cookie(platform, cookie_manager.path_for(platform, account), account)
        # A capture replaces the session, so any verdict the pre-run gate cached about
        # the old one is now not just stale but wrong in the dangerous direction.
        cookie_preflight.invalidate(platform)
        job['count'] = len(cookies)
        job['phase'] = 'saved'
        add_log(t('wf.cookies_generated', platform=platform, n=len(cookies)))
    except Exception as e:
        job['phase'] = 'error'
        job['error'] = str(e)[:300]
        # One line, one reason: the logger call already reaches the console (see the
        # cookie-save handler above), so the extra add_log said 「生成 Cookie 失败」 twice.
        logger.exception(f'{t("misc.cookie_gen_failed")}: {str(e)[:120]}')
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

    Refused outright on a cloud host: this route opens a window **for a person to log
    into**, and there is nobody at this server's screen. The panel hides the button, but a
    stale tab or a hand-written POST still reaches here, and the answer they get has to
    say why rather than hang on a browser nobody can see.
    """
    if Config.CLOUD_MODE:
        return jsonify({'ok': False, 'error': t('api.cloudNoLoginWindow')}), 400
    data = _json_body()
    if data is None:
        return _bad_body()
    platform = str(data.get('platform', ''))
    account = str(data.get('account') or '').strip()
    if not platform:
        return jsonify({'ok': False, 'error': t('api.platformRequired')}), 400
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        # The window will one day SAVE under this name — it enters a filename.
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
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
                        'account': _COOKIE_JOB['account'],
                        'error': t('api.cookieBusy', platform=_COOKIE_JOB['platform']),
                    }
                ),
                409,
            )
        _COOKIE_JOB.update(
            active=True, kind='login', platform=platform, account=account, phase='starting', error='', count=0
        )
        _COOKIE_JOB['entry'] = ''
        _COOKIE_JOB['facts'] = {}
        _COOKIE_JOB['lines'] = []
        _COOKIE_JOB['cancel'].clear()
        _COOKIE_JOB['confirm'].clear()
    threading.Thread(
        target=_cookie_login_worker, args=(platform, wait_seconds, entry_url, get_lang(), account), daemon=True
    ).start()
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
    """Turn one diagnosis into the lines the panel shows.

    Three answers, not the two this had. ``login_wall`` or 可用 called a risk-control
    page 可用 — the mirror image of the lie the pre-run gate refuses (see
    :mod:`cookie_preflight`): a page that answered with a captcha says nothing about
    the cookie, in either direction.
    """
    state = cookie_preflight.classify_probe(facts)
    lines = [t('cookie.verify.checkedUrl', url=str(facts.get('url') or ''))]
    if facts.get('unreachable'):
        # Before the three states below, and as its own line: 「无法核对」 is true but
        # useless here, because what could not be checked was not the cookie — the page
        # the browser was asked to open never arrived.
        lines.append(t('cookie.verify.unreachable', platform=platform))
    elif state == cookie_preflight.EXPIRED:
        lines.append(t('cookie.verify.loginWall', platform=platform))
    elif state == cookie_preflight.VALID:
        lines.append(t('cookie.verify.ok', platform=platform))
    else:
        lines.append(t('cookie.verify.unclear', platform=platform))
    return lines


def _cookie_verify_worker(platform: str, url: str, lang: str = '', account: str = ''):
    """Probe the stored cookie against the live site and report what it unlocks.

    Visible by design: this machine's risk control treats a headless content
    page differently from a real window (Zhihu in particular), and a diagnosis
    that blamed the cookie for a headless block would send the user to log in
    again for nothing.

    ``lang`` is handed in by the request thread and pinned here for the same
    reason the run worker does it: a daemon thread starts with a fresh thread-local,
    so without this the probe's own lines and its failure were Chinese in an English
    interface.
    """
    job = _COOKIE_JOB
    crawler = None
    set_lang(lang)
    try:
        # Whatever this probe sees is newer than anything the pre-run gate cached, so
        # the stale verdict goes before the browser opens, not after.
        cookie_preflight.invalidate(platform)
        # ``for_login`` because this window is shown to a person, and a person can be
        # sent there by an expired cookie: the probe lands on the login page, whose QR
        # code is an ``<img>``. Blocked, the diagnosis 「cookie 已失效，去登录」 pointed at
        # a window where logging in was impossible.
        crawler = get_crawler(platform, headless=False, cookie_dir=Config.COOKIE_DIR, for_login=True, account=account)
        facts = crawler.diagnose(url)
        facts['risk_blocked'] = bool(getattr(crawler, 'risk_blocked', False))
        lines = _verify_lines(platform, facts)
        with _COOKIE_JOB_LOCK:
            job['facts'] = facts
            job['lines'] = lines
            job['entry'] = str(facts.get('url') or '')
            job['phase'] = 'verified'
        if not url:
            # A manual 验证 on the platform's own page is the same measurement the
            # pre-run gate would pay for, so it refreshes that answer: the user who
            # came here from the block dialog should not have to prove the fix twice.
            # With a pasted entry URL it does not — the verdict is about that page, not
            # about the address the gate would visit.
            cookie_preflight.record(platform, facts, account)
        for line in lines:
            add_log(line)
    except Exception as e:
        # A VERIFICATION failure, so it must not be announced as 「生成 Cookie 失败」 —
        # the user asked no cookie to be generated here, and the line beside it already
        # said 验证失败. One attributed line carries the reason; the logger call is what
        # reaches the console (and the traceback reaches the log file).
        logger.exception(t('cookie.verifyFailed', err=str(e)[:120]))
        with _COOKIE_JOB_LOCK:
            job['phase'] = 'error'
            job['error'] = str(e)[:300]
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
    account = str(data.get('account') or '').strip()
    if not cookie_manager.is_supported(platform):
        return jsonify({'ok': False, 'error': t('api.unsupportedPlatform', platform=platform)}), 400
    if account and not cookie_manager.is_account(account):
        return jsonify({'ok': False, 'error': t('api.badAccount', account=account)}), 400
    if not cookie_manager.exists(platform, account):
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
                        'account': _COOKIE_JOB['account'],
                        'error': t('api.cookieBusy', platform=_COOKIE_JOB['platform']),
                    }
                ),
                409,
            )
        _COOKIE_JOB.update(
            active=True, kind='verify', platform=platform, account=account, phase='verifying', error='', count=0
        )
        _COOKIE_JOB['entry'] = ''
        _COOKIE_JOB['facts'] = {}
        _COOKIE_JOB['lines'] = []
        _COOKIE_JOB['cancel'].clear()
        _COOKIE_JOB['confirm'].clear()
    threading.Thread(target=_cookie_verify_worker, args=(platform, target, get_lang(), account), daemon=True).start()
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


# /api/config and /api/models live in api/config.py (imported above); registered here so app-level
# before_request / CORS still wrap them and the URLs are unchanged. /api/capabilities stays below:
# it extends the matrix with cookie_manager's live account list, so it moves when cookie_manager does.
app.register_blueprint(config_bp)


# /api/capabilities lives in api/capabilities.py (imported above); registered here so app-level
# before_request / CORS still wrap it and the URL is unchanged. It reads state.cookie_manager.
app.register_blueprint(capabilities_bp)


# ─── Runtime settings API ──────────────────────────────────────
#
# Machine-local values that used to be hardcoded (chromedriver path, browser
# window, timeouts, Ollama address). Persisted to data/settings.json by the
# settings store; crawlers and LLM calls read them per run, so a save applies
# on the next execution without restarting the server.


# The /api/settings cluster lives in api/settings.py (imported above); registered here so
# app-level before_request / CORS still wrap it and the URL is unchanged.
app.register_blueprint(settings_bp)


# ─── Browser profiles API ──────────────────────────────────────
#
# The two /api/browser/profiles routes live in api/browser_profiles.py and the shared
# ensure_profile_template lives in profiles.py (both imported at top), so the cookie-save path
# and the route call one function. Registered here; URLs unchanged, app-level before_request /
# CORS still wrap them. Tests that stub the launcher now patch profiles.warm_profile_dir.
app.register_blueprint(browser_profiles_bp)


# ─── AI (LLM) API ──────────────────────────────────────────────
#
# The three /api/llm/* transport endpoints live in api/llm.py (imported above); the shared
# _local_transport_refusal lives in transport.py. Registered here; URLs unchanged, app-level
# before_request / CORS still wrap them.
app.register_blueprint(llm_bp)


# ─── Clear Dataset Cache API ─────────────────────────────────────
# /api/data/clear now lives in backend/api/data.py (Blueprint `data_bp`) with the rest of the
# dataset cluster; registered below. Behaviour unchanged.


# ─── Chart Studio API (embedded ZENVIZ workbench) ─────────────────
# The /api/studio/{dataset,sources,save-image} cluster and its private helpers/constants
# (_first_tabular_result/_merge_unique_names/_merge_frames/_studio_dataset_merged/_column_names/
# _probe_source, STUDIO_*/SRC_*/PROBE_MAX_COLUMNS/MAX_IMAGE_BYTES) now live in
# backend/api/studio.py (Blueprint `studio_bp`); see the register below. Paths/behaviour unchanged.


# ─── Execution History API (time-series comparison across runs) ───


# The /api/history/* cluster lives in api/history.py (imported at top) and is registered here so
# app-level before_request / error handlers / CORS still wrap it, and the URLs are unchanged.
app.register_blueprint(history_bp)


# ─── Resumable runs ────────────────────────────────────────────


@app.route('/api/runs/resumable', methods=['POST'])
def runs_resumable():
    """Runs worth offering to resume, for the workflow currently on the canvas.

    Matched on the *structure* (node ids, types and wiring), not the settings:
    tweaking a keyword should still find the interrupted attempt of this same
    workflow. The browser also gets the per-node breakdown it needs to say what
    is already paid for.

    ``all`` flips the question the 断点续跑 node asks: it grafts a stored node's rows
    into a graph that need not resemble the run they came from — adding the resume
    node itself changes the canvas fingerprint — so it lists every run that still
    holds data instead of only this canvas's own interrupted attempt.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    workflow = data.get('workflow') or {}
    if not isinstance(workflow, dict) or not workflow.get('nodes'):
        return jsonify({'ok': True, 'runs': []})
    limit = _safe_int(data.get('limit'), 10, minimum=1, maximum=100)
    # Same repair as the panel's: a record its worker abandoned must become
    # continuable on a page load, not only once somebody opens 运行记录.
    _settle_orphaned_records()
    if data.get('all'):
        found = get_run_store().list_resumable(None, limit=limit, include_finished=True)
    else:
        found = get_run_store().list_resumable(workflow_fingerprint(effective_workflow(workflow)), limit=limit)
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
    store = get_run_store()
    # Asking the store is the moment to repair it: this is the read that happens when
    # somebody opens the panel because a record looks wrong.
    _settle_orphaned_records()
    runs = store.list_resumable(limit=limit, include_finished=True)
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
    """True when run_id names a run a live thread is still writing.

    Discarding or deleting it mid-flight would pull the rows and cursor out
    from under the writer — the UI's 丢弃/删除 must go through Stop first.

    "Go through Stop" is not the same as "Stop has been honoured": after 停止 the
    worker is still settling, still holding its browsers, and still writing rows, so
    the answer must be yes until its thread is actually gone. Reading only
    ``running`` refused the live run before the Stop and allowed it during the one
    window where deleting it is most destructive.
    """
    if not run_id:
        return False
    thread = execution_state.get('thread')
    live = bool(execution_state['running']) or bool(thread is not None and thread.is_alive())
    if not live:
        return False
    return run_id in {str(r) for r in execution_state['open_records']} or run_id == str(
        execution_state.get('run_id') or ''
    )


@app.route('/api/runs/purge', methods=['POST'])
def runs_purge():
    """Housekeeping. Interrupted runs are the last to go — they are the ones
    somebody may still want to continue. The live run, if any, is exempt, and so
    is every 置顶 record (a manual purge must not silently undo a pin either)."""
    keep: list[str] = []
    if execution_state['running']:
        keep = _as_run_ids(execution_state.get('run_id') or '')
    keep += sorted(_locked_run_ids())
    removed = get_run_store().purge(exclude_run_id=keep)
    _prune_orphan_run_locks()
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
    if lock_store.is_locked('runs', run_id):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
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
    if lock_store.is_locked('runs', run_id):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
    removed = get_run_store().delete_run(run_id)
    lock_store.drop('runs', run_id)
    return jsonify({'ok': True, 'removed': removed})


@app.route('/api/runs/clear', methods=['POST'])
def runs_clear():
    """Empty the run records — the panel's 清空 button.

    Refuses by name without ``confirm``: every other route in this file acts on a single id
    the browser just showed the user, while this one acts on all of them at once, so a stray
    POST (or a mistyped fetch from a console) must not be able to erase a history.

    A run that is live right now keeps its record: ``RunStore.clear_all`` is handed its id,
    because deleting rows a worker is still writing would destroy state mid-flight. What the
    deleted runs claimed as "already crawled" goes with them — see ``clear_all`` for why the
    bulk case releases claims where a single deletion keeps them.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    if data.get('confirm') is not True:
        return jsonify({'ok': False, 'error': t('api.needConfirm')}), 400
    live = str(execution_state.get('run_id') or '') if execution_state['running'] else ''
    # 清空 spares the live run AND every locked one — the user pinned those on purpose.
    keep = [live] if live else []
    keep.extend(lock_store.all_locks()['runs'])
    removed = get_run_store().clear_all(exclude_run_ids=keep)
    logger.warning(t('run.cleared', runs=removed['runs'], claims=removed['item_claims']))
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
