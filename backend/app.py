import logging
import math
import os
import re
import sys
import threading
import time
from urllib.parse import urlsplit

from api.analysis import bp as analysis_bp
from api.biblio import bp as biblio_bp
from api.capabilities import bp as capabilities_bp
from api.config import bp as config_bp
from api.data import bp as data_bp
from api.diagnostics import bp as diagnostics_bp
from api.exports import bp as exports_bp
from api.history import bp as history_bp
from api.http import (
    _bad_body,
    _bad_param,
    _json_body,
    _safe_int,
)
from api.lexicon import bp as lexicon_bp
from api.llm import bp as llm_bp
from api.locks import bp as locks_bp
from api.node_types import bp as node_types_bp
from api.project import bp as project_bp
from api.report import bp as report_bp
from api.reusable import bp as reusable_bp
from api.run_compare import bp as run_compare_bp
from api.runs import bp as runs_bp
from api.schedules import bp as schedules_bp
from api.settings import bp as settings_bp
from api.stats import bp as stats_bp
from api.studio import bp as studio_bp
from api.visualize import bp as visualize_bp
from api.workflow import bp as workflow_bp
from api.workflow_history import bp as workflow_history_bp
from core import machine
from core.config import Config
from core.refs import (
    comment_platforms,
)
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from nodes import registry as node_registry
from nodes.catalog import QUIET_NODE_TYPES as QUIET_NODE_TYPES
from nodes.labels import node_label
from scheduling import clock
from sessions.routes import bp as sessions_bp
from state import (
    _push_log,
    execution_state,
)
from stores import (
    get_run_store,
)

from engine import run as run_engine
from engine.logger import setup_logger
from engine.plan import (
    downstream_closure,
)
from engine.workflow import effective_workflow
from i18n import audit, set_lang, t
from services.runs.queue import (
    load_pending_queue,
)
from services.runs.settlement import (
    housekeep,
)
from services.runs.store import (
    NODE_DONE,
    NODE_RESTORED,
    RUN_RUNNING,
    RUN_STOPPING,
    workflow_fingerprint,
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

# The UI is served by THIS process and every one of its ``fetch`` calls uses a relative
# ``/api/...`` path, so no legitimate request is ever cross-origin. The old ``CORS(app)``
# ran on flask-cors's default ``origins='*'``, which let any page the user visits while the
# server is up READ the unauthenticated ``/api/cookies/status`` (the account list), the run
# history and dataset contents. Restrict the ACAO header to loopback. The pattern is
# end-anchored on purpose: flask-cors matches origins with ``re.match``, which would otherwise
# let ``http://localhost.evil.com`` through the ``localhost`` branch.
_LOOPBACK_ORIGIN = re.compile(r'https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$', re.IGNORECASE)
CORS(app, origins=_LOOPBACK_ORIGIN)


def _origin_is_local(origin: str, server_host: str = '') -> bool:
    """Whether a request's ``Origin`` is this machine, not a page that merely names it.

    Loopback hosts are trusted; so is any origin whose host equals the host the request was
    addressed to (a deliberate ``HOST=`` LAN bind stays usable). The match is on the parsed
    host, never a substring — ``localhost.evil.com`` starts with ``localhost`` but is not it.
    ``server_host`` is passed in rather than read from ``request`` so this stays a pure
    function the tests can drive outside an HTTP context.
    """
    if not origin:
        return True  # a header-less call (curl, test_client, same-origin GET) is not cross-origin
    try:
        netloc = urlsplit(origin).netloc
    except ValueError:
        return False
    origin_host = netloc.rsplit('@', 1)[-1]
    if origin_host.startswith('['):  # IPv6 literal: [::1] or [::1]:5000 — the port is after the ]
        origin_host = origin_host[1:].split(']', 1)[0]
    elif ':' in origin_host:
        origin_host = origin_host.split(':', 1)[0]
    if origin_host in ('127.0.0.1', 'localhost', '::1'):
        return True
    return bool(server_host) and origin_host == server_host.rsplit(':', 1)[0]


@app.before_request
def _reject_foreign_origin():
    """Refuse a cross-origin request outright, not just its read-back.

    Tightening the CORS header only stops a browser from READING a response; a simple
    cross-origin ``POST`` (no custom header, form/JSON body) is still sent and still executed,
    which on this unauthenticated server means a foreign page could run a crawl on the user's
    logged-in accounts or fire ``/api/history/clear``. The ``Origin`` a browser attaches to
    every cross-origin XHR/fetch is the one signal that names the caller, so it is refused here
    with a named 403 rather than silently answered.
    """
    origin = request.headers.get('Origin') or request.headers.get('Referer')
    if origin and not _origin_is_local(origin, request.host):
        return jsonify({'ok': False, 'error': t('api.foreignOriginRefused', origin=origin)}), 403


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


def _level_for_record(record) -> str:
    """Coarse console level for the durable sink: ERROR+/WARNING/INFO.

    Best-effort metadata for the after-the-fact viewer's filter — it never affects the
    live console. A traceback forwarded by ``logger.exception`` arrives at ERROR, so the
    durable log can say "this run had N errors" even after the in-memory tail rolled over.
    """
    if record.levelno >= logging.ERROR:
        return 'error'
    if record.levelno >= logging.WARNING:
        return 'warning'
    return 'info'


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
        _push_log(f'[{time.strftime("%H:%M:%S")}] {msg}', level=_level_for_record(record))

    def format(self, record):
        return record.getMessage()


_log_handler = LogBufferHandler()
_log_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)


def pin_console_streams() -> list[str]:
    """Give the console a chance to carry Chinese before anything writes to it; return what changed.

    Called at import, not per request: a stream's encoding is decided when Python opens it, so the answer
    belongs to the process. A container started with no ``LANG`` has an ASCII stdout, and the first Chinese
    log line there raises inside the logging handler — which swallows it, so the line vanishes and the run
    console looks quiet instead of broken.
    """
    changed = []
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, f'__{name}__', None) or getattr(sys, name, None)
        previous = machine.pin_console(stream, name)
        if previous:
            changed.append(f'{name}:{previous}')
            print(t('misc.consoleUtf8', streams=' '.join(changed)))
    return changed


pin_console_streams()


# cookie_manager lives in state.py (imported at top) so the capabilities Blueprint can read it.
# The saved-canvas reader lives in stores.py (imported at top) for the same reason: the workflow
# routes are a Blueprint and the run orchestration is an engine module, and neither may import
# this file to reach a canvas on disk.
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


# _results_snapshot lives in state.py (imported above) so a read-only Blueprint can take a
# stable copy of execution_state['results'] without importing the whole Flask module.


# ─── Durable run state ──────────────────────────────────────────
# The run ledger / dataset store / housekeeper / canvas-manager singletons and their locks live in
# backend/stores.py; ``get_run_store`` is imported back here because a test that patches it must
# still intercept the app-internal calls. What the housekeeper sweeps for is now called from
# ``services.runs.settlement.housekeep``, not from this file.


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
    if name == 'add_log':
        # The console seam. Tests of the run path patch ``app.add_log`` to capture what the run
        # prints, while the modules that print (``engine.run``, the source executor) resolve the
        # name in their own namespace and forward it here at CALL time (``tests/executor_seams.py``
        # and the autouse fixture in ``tests/api/conftest.py``). Nothing in this file logs any
        # more, so answering from ``state`` keeps 「patch app.add_log」 meaning one thing instead of
        # leaving each test to guess which module the line is printed from.
        import state

        return getattr(state, name)
    if name == 'get_crawler':
        # The one crawler-factory seam tests patch (``tests/executor_seams.py`` forwards
        # ``app.get_crawler`` into the source executor at call time, and ~40 pre-split tests
        # patch it here). The cookie routes moved out, so nothing in this file calls it any
        # more; answering from the package keeps a patch on THIS name meaning the same thing
        # without making ``sessions.routes`` import the app module.
        import crawlers

        return getattr(crawlers, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


# ─── API Routes ────────────────────────────────────────────────


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


# ─── Request validation helpers ────────────────────────────────


# _json_body and _bad_body live in api.http now (imported at top) so a Blueprint can use them
# without importing the whole Flask module. _bad_param stays: only app.py routes reach it.


@app.errorhandler(413)
def _payload_too_large(_error):
    """Answer the request-size ceiling in JSON, not with Werkzeug's HTML page.

    ``request.json()`` in the browser throws before the status is ever looked
    at, which turned a clear "too big" into an unparseable response.
    """
    limit_bytes = int(app.config.get('MAX_CONTENT_LENGTH') or 0)
    mb = round(limit_bytes / (1024 * 1024), 2) if limit_bytes > 0 else UPLOAD_LIMIT_MB
    return jsonify({'ok': False, 'error': t('api.payloadTooLarge', limit=mb)}), 413


# ─── Execution API ─────────────────────────────────────────────


# ─── Run queue ────────────────────────────────────────────────
# The queue itself — its list (``state._RUN_QUEUE``), its lock, its db mirror and the refusal at
# the door — is :mod:`services.runs.queue`. What stays here is the one thing that cannot live
# there: handing the slot to the next request means starting a run, which is this file's work.


# ─── Scheduled tasks (the clock lives in scheduling/clock.py) ───
#
# The clock, the store and the history are in ``scheduling/clock.py`` / ``scheduling/store.py``,
# which import without Flask. These two functions are the only parts it cannot own: reading the
# canvas a task names, and starting the run its own way. A scheduled fire goes through
# ``begin_run`` — resolved at CALL time, since the run-start path is defined further down this
# file — so a timer gets the same execution a manual 执行 does: same validations, same claim, and
# the same queue when a run is already going.


clock.set_run_starter(run_engine.start_scheduled_run)
clock.set_canvas_source(run_engine.scheduled_canvas)


@app.route('/api/workflow/execute', methods=['POST'])
def execute_workflow():
    """Start a run — or queue the request when a run is already going."""
    data = _json_body()
    if data is None:
        return _bad_body()
    answer = run_engine.begin_run(data, request.headers.get('X-Lang') or '')
    return jsonify(answer['body']), answer['status']


@app.route('/api/workflow/rerun-node', methods=['POST'])
def workflow_rerun_node():
    """Re-run ONE node and everything downstream of it, reusing the kept upstream rows.

    This is a resume with a targeted wipe: the target subtree's stored results are deleted,
    then the SAME run is started with ``resume_run_id``. The existing reuse predicate then
    finds those nodes with no stored row (so it executes them) while every upstream node
    still holds its ``done``/``restored`` rows (so it is reused, never re-crawled or
    re-paid) — one paste path, one resume path, no second engine."""
    data = _json_body()
    if data is None:
        return _bad_body()
    node_id = data.get('node_id')
    if not isinstance(node_id, str) or not node_id.strip():
        return _bad_param('node_id')
    node_id = node_id.strip()
    workflow = data.get('workflow')
    if not isinstance(workflow, dict) or not workflow.get('nodes'):
        return jsonify({'ok': False, 'error': t('api.workflowShapeInvalid')}), 400

    effective = effective_workflow(workflow)
    fingerprint = workflow_fingerprint(effective)
    store = get_run_store()

    run_id = str(data.get('resume_run_id') or '').strip()
    if run_id:
        run = store.get_run(run_id)
        if run is None:
            return jsonify({'ok': False, 'error': t('api.resumeMissing', rid=run_id)}), 400
        if run.get('workflow_fingerprint') != fingerprint:
            # Reusing this run would mix two different workflows' rows under one id; refuse by name.
            return jsonify({'ok': False, 'error': t('api.rerunFingerprintMismatch')}), 409
    else:
        candidates = store.list_resumable(fingerprint, limit=1, include_finished=True)
        if not candidates:
            return jsonify({'ok': False, 'error': t('api.rerunNoRun')}), 404
        run_id = candidates[0]['run_id']

    # A run that is still executing is not a rerun target. The wipe below deletes this run's stored
    # rows and releases its dedupe claims BEFORE ``begin_run`` can serialize against the live
    # worker (``invalidate_nodes`` runs first, so the single-run queue cannot help); a 继续 would
    # then re-crawl and re-pay a thread that is still writing. Refuse by name, keeping the rows.
    target_run = store.get_run(run_id)
    if target_run is None:
        return jsonify({'ok': False, 'error': t('api.rerunNoRun')}), 404
    if target_run.get('status') in (RUN_RUNNING, RUN_STOPPING):
        return jsonify({'ok': False, 'error': t('api.rerunRunLive')}), 409

    target = next((n for n in effective['nodes'] if n.get('id') == node_id), None)
    if target is None:
        return jsonify({'ok': False, 'error': t('api.rerunNoNode', node=node_id)}), 400
    status = store.get_node_status(run_id, node_id)
    if status not in (NODE_DONE, NODE_RESTORED):
        return jsonify({'ok': False, 'error': t('api.rerunNoRows', node=node_label(target, node_id))}), 409
    # Another run may still be writing. The wipe below deletes this subtree's rows
    # BEFORE the start path can serialize, so refusing here is what keeps those rows
    # from disappearing under a rerun that then has to wait (or is refused) anyway.
    live_thread = execution_state.get('thread')
    if execution_state.get('running') or (live_thread is not None and live_thread.is_alive()):
        return jsonify({'ok': False, 'error': t('api.rerunBusy')}), 409

    invalidated = downstream_closure(effective, node_id)
    store.invalidate_nodes(run_id, invalidated)

    # Replay through the ordinary start path as a resume of the very run we just pruned.
    # Never park it: the wipe above already deleted this subtree's rows, and a queued
    # rerun would leave that hole visible until some other run finishes.
    data['resume_run_id'] = run_id
    data['queue'] = False
    answer = run_engine.begin_run(data, request.headers.get('X-Lang') or '')
    body = dict(answer['body'])
    body['rerun_from'] = node_id
    body['invalidated'] = invalidated
    return jsonify(body), answer['status']


# _local_transport_refusal lives in transport.py (imported at top); the run executor (via
# cloud_refusal_response below) and the /api/llm/* Blueprint both call that one function.


# `_execute_upload_node` is a built-in plugin: backend/nodes/executors/upload.py. It registers itself
# with ``nodes.registry``; dispatch reads that registry, not a module-level alias.


# The numeric-coercion family (_safe_int / _safe_float / _optional_int / _optional_float) lives in
# api.http now (imported at top); every app call site reads the app-level alias unchanged.


# `_split_columns` now lives in core/refs.py (split_columns, imported back under this name).


# `_execute_resume_node` is a built-in plugin: backend/nodes/executors/resume.py. It reads its ledger
# through ctx['store'], not a global; the direct-call fallback lives in that module's ``run`` wrapper.


#: Node types the console stays quiet about. A 工作流命名 node carries a label and
#: computes nothing; an 上传文件 node re-reads a file the user already pointed at.
#: Announcing "executing node …" and "node … done (2/4)" for those is two lines of
#: noise per node that has no work to report, and on a canvas of mostly-plumbing
#: nodes the lines that *do* matter — a crawl, a failure, a restored node — drowned
#: in them. Only the generic per-node chatter is suppressed: what these nodes say
#: about themselves (which file was loaded, how many rows) and anything that went
#: wrong still reaches the console. The set itself lives on each node's plugin
#: (``nodes/catalog.py``), so a quiet type is declared once, not in a second list here.


#: Every node type is a plugin: ``nodes/executors/`` registers its own executor with the same
#: table, so adding a node type never edits this module. See ``docs/refactor_plan.md``.
node_registry.load_builtin_executors()


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
# same services.charts.outputs / services.charts.visualizer that _execute_visualize_node does, so the
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
app.register_blueprint(node_types_bp)
app.register_blueprint(exports_bp)
app.register_blueprint(data_bp)
app.register_blueprint(diagnostics_bp)
app.register_blueprint(lexicon_bp)
app.register_blueprint(studio_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(visualize_bp)
app.register_blueprint(report_bp)


# ─── Cookie API ────────────────────────────────────────────────

# The /api/cookies/* cluster, /api/profiles/delete and the two /api/browser/profiles routes now
# live in ``sessions/routes.py`` (Blueprint ``sessions``); registered here so app-level
# before_request / CORS still wrap them and every URL is unchanged.
app.register_blueprint(sessions_bp)


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


# ─── Scheduled tasks API ───────────────────────────────────────
#
# /api/schedules* lives in api/schedules.py (imported above). It reads the task store and the
# scheduler's two seams, never this module, so it registers like every other Blueprint; the clock
# itself is started by the ``__main__`` block below.
app.register_blueprint(schedules_bp)
#
# /api/biblio/* (the Bibliometrics Workspace's read side) lives in api/biblio.py: it answers
# "which runs hold a bibliometrics node" and "what did that node store" from the durable ledger,
# so the panel holds no second opinion about either.
app.register_blueprint(biblio_bp)
# Canvas snapshots (and the per-workflow layout baseline) live in their own curated store;
# restoring is done by the browser from the snapshot body this Blueprint returns.
app.register_blueprint(workflow_history_bp)
app.register_blueprint(project_bp)
app.register_blueprint(run_compare_bp)
# Reusable-node templates: authored fragments offered by the canvas picker. Nothing here
# executes them; the browser expands on Run and ``begin_run``/``_scheduled_canvas`` expand a
# saved file's group before the engine sees it.
app.register_blueprint(reusable_bp)
# The run-record panel's read/write side (records, retention, the durable console) lives in
# api/runs.py; the ledger itself is ``services/runs/store.py`` and what a dead worker leaves
# behind is ``services/runs/settlement.py``. Registered here so app-level before_request /
# CORS still wrap it and every URL is unchanged.
app.register_blueprint(runs_bp)
# The saved-canvas / queue / stop-status cluster lives in api/workflow.py. What stays here is the
# page, ``/api/workflow/execute`` and ``/api/workflow/rerun-node`` — the two doors that start a run.
app.register_blueprint(workflow_bp)


# ─── Main ──────────────────────────────────────────────────────


def _open_browser(url: str):
    """Open the UI in the default browser once the server is up."""
    if Config.CLOUD_MODE:
        # A server has no browser to hand an address to, and `webbrowser.open` on a headless host either
        # does nothing or hunts for an X display that will never exist. The address is printed instead —
        # that is the only thing a remote operator can act on.
        logger.info(t('misc.cloudNoBrowser', url=url))
        return
    try:
        import webbrowser

        # ``open()`` returns False when there is no browser to hand the URL to — it does not raise.
        # A machine that never registered a browser would otherwise watch the console go quiet after
        # the 「服务已启动」 line, which is the exact silence this project keeps being asked to remove.
        if not webbrowser.open(url):
            logger.warning(t('misc.browserNotFound', url=url))
    except Exception as e:
        # A headless box has no browser to open — warn, never crash the startup.
        logger.warning(t('misc.browser_open_failed', err=e))


def _debug_enabled() -> bool:
    """FLASK_DEBUG as a plain yes/no (anything else, unset included, is no)."""
    return str(os.environ.get('FLASK_DEBUG', '')).strip().lower() in ('1', 'true', 'yes')


# Load the user's jieba domain dictionary once, process-wide, so every tokenizer path
# (keyword, tokenize, topic, ML, word cloud) sees the same words — not just the keyword
# path that used to load it lazily. An empty lexicon writes nothing and is a no-op.
try:
    from services.analysis.lexicon import load_userdict as _load_userdict

    _load_userdict()
except Exception:  # a broken user dict must never stop the server from booting
    logging.getLogger(__name__).warning('user dict load at startup skipped', exc_info=True)


def start_background_services() -> None:
    """Retention, the restored queue and the scheduled-task clock.

    Extracted from ``__main__`` because the frozen launcher imports this module and calls Flask
    itself: ``__main__`` never ran there, so the packaged app served requests with no tick thread
    and the 定时任务 panel truthfully said 「调度线程没有运行——任务已保存，但到点不会执行」.
    Both entry points run this once, in the serving process (under the reloader, only the child).
    """
    # Retention is applied on its own, not only when somebody remembers to
    # click: startup is the other moment nothing is writing.
    housekeep(force=True)
    # A restart must not silently drop the requests the user already parked.
    restored = load_pending_queue()
    if restored:
        logger.info(t('run.queue_restored', n=restored))
    clock.start()


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
    # Retention, the parked queue and the scheduled-task clock. Started in the SERVING process
    # only: with the reloader on this module is imported twice (the watcher and the child), and
    # two clocks would fire one moment twice. The frozen launcher calls the same function for the
    # same reason (see ``start_background_services``).
    if not debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_background_services()
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=debug)
