import contextlib
import logging
import math
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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
    as_bool,
    comment_platforms,
    export_stamp,
    flag_or_none,
)
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from nodes import registry as node_registry
from nodes.catalog import QUIET_NODE_TYPES as _QUIET_NODE_TYPES
from nodes.labels import node_label
from scheduling import clock
from sessions.routes import bp as sessions_bp
from state import (
    _completed_lock,
    _push_log,
    _results_snapshot,
    _wf_local,
    add_log,
    execute_lock,
    execution_state,
    reset_console_state,
    set_log_sink,
)
from stores import (
    get_run_store,
    get_workflow_manager,
)
from transport import _local_transport_refusal

from engine.executor import TaskExecutor
from engine.logger import setup_logger
from engine.plan import (
    component_name,
    downstream_closure,
    llm_provider,
    run_mode,
    workflow_needs_llm,
)
from engine.run import run_node_durable
from engine.workflow import WorkflowEngine, effective_workflow
from i18n import audit, normalize, set_lang, t
from services.analysis.pipeline import UnknownOperationError
from services.runs.history import record_execution_history
from services.runs.payload import resume_refusal, workflow_shape_error
from services.runs.queue import (
    drain_queue,
    enqueue_run,
    load_pending_queue,
)
from services.runs.settlement import (
    close_run,
    housekeep,
)
from services.runs.store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_RESTORED,
    NODE_SKIPPED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    RUN_RUNNING,
    RUN_STOPPING,
    fingerprints_for_workflow,
    workflow_fingerprint,
)
from services.workflows.expand import expand_reusable_workflow
from settings_store import get_setting

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

    def unwrap(self):
        """The stream this tee replaced — how a caller takes the tee off without reaching in."""
        return self._original


class _RunLogWriter:
    """Write-through of the live console into the durable per-run log (``run_store.run_log``).

    Installed as ``state``'s log sink only for the window a run is in flight (armed in
    ``_begin_run``, disarmed in the worker's ``finally``), so a message logged outside any
    run never reaches it — otherwise a later cookie/preview ``add_log`` would append to a
    completed record's log. The sink runs *inside* ``_push_log`` while it holds
    ``_completed_lock``, so ``push`` may only touch in-memory state cheaply; it accumulates
    lines and hands the batch to SQLite every ``FLUSH_EVERY`` lines or the moment one is an
    error (so a crash leaves the tail it printed, not a whole run's worth unwritten).

    It must never write the console back (no ``add_log``/``logger`` on failure — the log
    handler forwards here, so a failure log would recurse). A store error keeps the batch for
    the next flush, bounded by a hard cap so a permanently-dead DB cannot grow memory forever.
    """

    FLUSH_EVERY = 200
    HARD_CAP = 2000

    def __init__(self):
        self._buf: list = []
        self._buf_run_id: str | None = None

    def reset(self) -> None:
        """Drop any leftover batch without writing it (a new run, or an armed re-entry).

        Takes ``_completed_lock`` for the whole swap (the same way ``flush`` does): ``push``
        runs under that lock, so replacing ``_buf`` without it let a concurrent push append
        into the list ``reset`` had just swapped out — the durable log of a stopped run lost
        its tail. Neither caller holds the lock, so acquiring it here cannot self-deadlock."""
        with _completed_lock:
            self._buf = []
            self._buf_run_id = None

    def push(self, parts, wf_idx, level) -> None:
        # Runs while the caller holds ``_completed_lock`` (see ``state._push_log``); every
        # mutation below is therefore serialized with every other console writer.
        rid = str(execution_state.get('run_id') or '')
        if not rid:
            return
        if rid != self._buf_run_id and self._buf:
            # Serial split: the previous component's record is closed — flush its lines under
            # ITS id before switching, or they would be re-filed onto the next workflow.
            self._drain()
        self._buf_run_id = rid
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        name = str((execution_state.get('_wf_names') or {}).get(wf_idx, '')) if wf_idx is not None else ''
        lvl = level or 'info'
        for line in parts:
            self._buf.append((stamp, wf_idx, name, lvl, line))
        if lvl == 'error' or len(self._buf) >= self.FLUSH_EVERY:
            self._drain()

    def _drain(self) -> None:
        if not self._buf or not self._buf_run_id:
            self._buf = []
            return
        rid = self._buf_run_id
        batch = self._buf
        try:
            get_run_store().append_log(rid, batch)
            self._buf = []
        except Exception:
            # Keep the batch for a later flush; bound it if the store stays down. No logging
            # here — the console handler forwards back into ``push`` and would recurse.
            self._buf = batch if len(batch) <= self.HARD_CAP else batch[-self.FLUSH_EVERY :]

    def flush(self) -> None:
        with _completed_lock:
            self._drain()


_run_log_writer = _RunLogWriter()


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


def _start_next_queued() -> None:
    """Hand the slot to the oldest waiting request, at the end of a run.

    The queue's own work (pop, mirror, put-back, the recursion past a request that can never
    start) is :func:`services.runs.queue.drain_queue`; what stays here is only the injection of
    ``_begin_run`` — the queue cannot import the app, and starting a run is the app's work.

    Called from the finishing thread *after* it released the slot and cleared its own handle:
    the claim also checks thread liveness, so a thread still alive while it unwinds would make
    this call queue the next request behind itself — and nothing would ever start it again.
    """
    drain_queue(_begin_run)


# ─── Scheduled tasks (the clock lives in scheduling/clock.py) ───
#
# The clock, the store and the history are in ``scheduling/clock.py`` / ``scheduling/store.py``,
# which import without Flask. These two functions are the only parts it cannot own: reading the
# canvas a task names, and starting the run its own way. A scheduled fire goes through
# ``_begin_run`` — resolved at CALL time, since the run-start path is defined further down this
# file — so a timer gets the same execution a manual 执行 does: same validations, same claim, and
# the same queue when a run is already going.


def _scheduled_canvas(name: str) -> dict:
    """The saved canvas a scheduled task will run, or the reason it may not run on a timer.

    One answer for two moments: the schedule form refuses a canvas that cannot run unattended
    while the user is still choosing, and the fire refuses it again if the file changed since.
    Both rules are enforced here rather than in the panel, because a hand-written POST would
    otherwise skip them: the file must exist, and its steps must not need a model — a timer has no
    browser request behind it, so there is nowhere for an API key to come from, and a run that
    quietly skipped its analysis would look exactly like one that analysed something.
    """
    if not name:
        return {'workflow': None, 'error': t('sched.workflowRequired')}
    workflow = get_workflow_manager().load(name)
    if not workflow:
        return {'workflow': None, 'error': t('sched.canvasMissing', name=name)}
    # The saved file keeps reusable nodes as groups; this gate asks what a run will
    # actually call, so expand before asking whether a model is needed. (The expanded
    # graph is also what _begin_run receives; there it is already group-free.)
    workflow, reusable_error = expand_reusable_workflow(workflow)
    if reusable_error:
        return {'workflow': None, 'error': reusable_error}
    if workflow_needs_llm(workflow):
        return {'workflow': None, 'error': t('sched.canvasNeedsModel', name=name)}
    return {'workflow': workflow, 'error': ''}


def _start_scheduled_run(task: dict, manual: bool) -> dict:
    """Start one scheduled run and say what happened (started / queued / refused).

    ``run_id`` comes back so the task's own history can point at the record: that id is how the
    user opens the console of the fire that just happened.
    """
    loaded = _scheduled_canvas(str(task.get('workflow') or ''))
    if loaded['error']:
        return {'ok': False, 'error': loaded['error']}
    name = str(task.get('name') or '')
    answer = _begin_run(
        {'workflow': loaded['workflow'], 'workflow_name': name, 'lang': task.get('lang') or 'zh'},
        '',
    )
    body = answer.get('body') or {}
    if answer.get('status') != 200 or not body.get('ok'):
        return {'ok': False, 'error': str(body.get('error') or '')}
    queued = bool(body.get('queued'))
    if not queued:
        # Only a run that really started gets a console line. A queued fire has no console of its
        # own yet (the queue narrates when it starts) and a refusal has none at all — that one is
        # recorded in the task's own history, which is where the user looks for it.
        add_log(t('sched.firedManual' if manual else 'sched.fired', name=name))
    return {'ok': True, 'queued': queued, 'run_id': str(body.get('run_id') or ''), 'error': ''}


clock.set_run_starter(_start_scheduled_run)
clock.set_canvas_source(_scheduled_canvas)


@app.route('/api/workflow/execute', methods=['POST'])
def execute_workflow():
    """Start a run — or queue the request when a run is already going."""
    data = _json_body()
    if data is None:
        return _bad_body()
    answer = _begin_run(data, request.headers.get('X-Lang') or '')
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
    # rows and releases its dedupe claims BEFORE ``_begin_run`` can serialize against the live
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
    answer = _begin_run(data, request.headers.get('X-Lang') or '')
    body = dict(answer['body'])
    body['rerun_from'] = node_id
    body['invalidated'] = invalidated
    return jsonify(body), answer['status']


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
    shape_error = workflow_shape_error(data)
    if shape_error:
        # Refused before the slot is claimed: a payload the engine cannot walk
        # must not become a failed run record, let alone a queued one that dies
        # in a thread nobody is watching.
        return {'status': 400, 'body': {'ok': False, 'error': shape_error}}
    # A saved workflow keeps a reusable node as ONE group (so reopening can render it);
    # a run needs its children. The browser already expands on Run, but a scheduled fire
    # starts from the file and every queued request must see the same graph, so the
    # expansion happens here — before the claim, the mode/fingerprint and the queue.
    workflow, reusable_error = expand_reusable_workflow(data.get('workflow') or {})
    if reusable_error:
        return {'status': 400, 'body': {'ok': False, 'error': reusable_error}}
    data = {**data, 'workflow': workflow}
    # The run shape is asked BEFORE the claim too, and it raises rather than answering
    # "parallel" to a token it does not know: the mode decides both how many records this run
    # writes and whether two same-platform crawls may breathe at once on one profile. The
    # transport is asked by the same door — an unknown provider must not fold to a local daemon
    # the record then falsely claims ran.
    try:
        run_mode(((data.get('workflow') or {}).get('settings')) or {})
        llm_provider(data.get('llm') or {})
    except UnknownOperationError as e:
        return {'status': 400, 'body': {'ok': False, 'error': str(e)}}
    resume_error = resume_refusal(data)
    if resume_error:
        # 'drop' tells the queue this entry can never start, so it is discarded
        # rather than pushed back to wait for a run that no longer exists.
        return {'status': 400, 'body': {'ok': False, 'error': resume_error}, 'drop': True}
    # Guard and claim are one critical section. They used to be ~70 lines
    # apart: two concurrent POSTs both passed the check, both started a run
    # thread, and interleaved writes into one console, one store, one crawl.
    with execute_lock:
        running_thread = execution_state['thread']
        # The previous run's thread may still be unwinding after a Stop (it clears
        # `running` first), so check liveness too — otherwise a quick Stop → Run
        # leaves two threads appending to the same console and results.
        if execution_state['running'] or (running_thread is not None and running_thread.is_alive()):
            if data.get('queue') is False:
                # The explicit "refuse instead of wait" door, kept because the
                # banner's 继续 wants to fail fast, not silently reorder runs.
                return {'status': 400, 'body': {'ok': False, 'error': t('api.alreadyRunning')}}
            return enqueue_run(data, lang_header)

        # Claim under the same lock that reads it — no second request can slip
        # through while this one is still validating.
        execution_state['running'] = True
        started = False
        try:
            workflow = data.get('workflow', {})
            settings = workflow.get('settings', {})
            mode = run_mode(settings)
            # A cloud host has no display, so headless is not a preference here — the
            # browser would never come up. The panel hides the switch (it is told the
            # server's shape by /api/config), but the run record is written from THIS
            # value, and a record that said 「窗口」 for a crawl that could only have run
            # headless would be a chip describing a run that never happened.
            headless = True if Config.CLOUD_MODE else as_bool(settings.get('headless'), True)
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
            # Read through the repo's own tri-state reader: ``bool(raw)`` answered True to the
            # text 'false' — a draft that says 「不用 Profile」 in a hand-edited file would have
            # been crawled WITH one, which is the device a wall is measured against.
            use_profile = flag_or_none(settings.get('use_profile'))
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
                'provider': llm_provider(llm_cfg),
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
            if workflow_needs_llm(workflow):
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
            # Arm the durable per-run console for exactly this run's window: from here the
            # sink is this run's writer, and the worker's ``finally`` flushes and disarms it.
            # A run therefore owns every line it prints and no message logged outside a run
            # (a later cookie/preview ``add_log``) can bleed into a finished record's log.
            _run_log_writer.reset()
            set_log_sink(_run_log_writer.push)
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
            execution_state['attempt_records'] = set()
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
        named = component_name(wf_engine)
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
            # ``fuse`` is the one node type where several wires are the feature, not a warning:
            # it folds every parent and logs what each contributed, so the "the first is the
            # primary input" sentence would describe a rule this node deliberately does not have.
            if len(parents) > 1 and _node_of(nid).get('type') != 'fuse':
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
                # The output (save) node merges every parent's rows into one table; to make that
                # table say which rows came from which platform (what 跨平台对比 reads), the run
                # loop — the only place holding the whole graph — resolves each parent's platform
                # here. None for every other node type; a non-crawl parent (upload/resume) is '' ,
                # never a guessed platform.
                _platform_of = None
                _labels_of = None
                if node.get('type') == 'output' and upstream:
                    _platform_of = {}
                    # The same graph reach the merge needs to NAME its parents: its refusals and
                    # its 「已合并」 line quote the parent, and a bare `node-2` in a message about
                    # which WIRE to cut is the one thing the console rule exists to stop.
                    _labels_of = {}
                    for _pid, _res in upstream:
                        _pn = _node_of(str(_pid))
                        _p = _pn.get('platform') or (_pn.get('params') or {}).get('platform') or ''
                        _platform_of[str(_pid)] = str(_p)
                        _labels_of[str(_pid)] = node_label(_pn, str(_pid))
                result, status = run_node_durable(
                    ctx,
                    node,
                    headless,
                    primary,
                    upstream,
                    wf_idx,
                    platform_of=_platform_of,
                    label_of=_labels_of,
                )
                results[nid] = result
                if status == NODE_SKIPPED:
                    # Neither done nor failed: it never got input to work on. The
                    # reason was announced by run_node_durable; counting it as
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
                with _completed_lock:
                    execution_state['attempt_records'].add(run_id)
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

            def _component_run(wf_idx, sub_engine):
                """Open this workflow's own record and return the context its nodes run
                under. Called as the turn arrives, which is what makes an unreached
                workflow leave no record at all — the point of the split.

                Workflow zero takes the id the HTTP response already handed out, so the
                browser, the status endpoint and the resume banner all name a row that
                exists. The others are minted as they are reached.

                ``wf_idx`` is the component's position, the same word the serial loop and
                ``_wf_display_name`` use: naming it ``index`` here shadowed the module's
                ``index()`` route for the whole closure, which is a footgun, not a shortcut.
                """
                name = _wf_display_name(sub_engine, wf_idx)
                earlier = _continue_record(name)
                rid = str(earlier.get('run_id') or '') or (run_id if wf_idx == 0 else uuid.uuid4().hex[:12])
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
                    skipped_workflows=skipped_str if wf_idx == 0 else '',
                )
                created.append(rid)
                ctx['open_records'].append(rid)
                execution_state['owned_records'].add(rid)
                with _completed_lock:
                    execution_state['attempt_records'].add(rid)
                # The status endpoint and the resume banner follow the record that is
                # being written RIGHT NOW, so a stop mid-run leaves the panel offering
                # the workflow that was interrupted rather than the first one.
                execution_state['run_id'] = rid
                if earlier:
                    saved = sum(int(n.get('row_count') or 0) for n in earlier.get('nodes') or [])
                    add_log(t('run.resume_from', at=earlier.get('started_at') or '?', rows=saved), wf_idx=wf_idx)
                else:
                    add_log(t('run.started', rid=rid), wf_idx=wf_idx)
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

            def _close_component_record(sub_ctx: dict) -> None:
                """Give one workflow its own verdict, the moment its turn ends.

                The run-level finish line below can only speak for the whole canvas,
                and after the split there is no whole-canvas row to speak for: each
                workflow's row is closed here, so a canvas whose second workflow was
                stopped while the first finished shows 已完成 and 已中断 side by side
                instead of one verdict smeared over both.

                It takes only the context: the verdict comes from the RECORD's own rows
                (``settle_nodes`` re-reads them), so this never needed the sub-engine.
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
                        _close_component_record(sub_ctx)
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
                for wf_idx, se in enumerate(sub_engines):
                    snapshot = _results_snapshot()
                    sub_results = {nid: res for nid, res in snapshot.items() if nid in se.nodes}
                    record_execution_history(
                        None,
                        se,
                        sub_results,
                        component_name(se) or workflow_name,
                        log_label=_wf_display_name(se, wf_idx),
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
                close_run(ctx, outcome)
            with _completed_lock:
                # Every exit must leave a verdict: the browser stops guessing from
                # `completed < total` and reads this instead, and an empty string
                # would leave the last run's answer standing on screen.
                if not execution_state['outcome']:
                    execution_state['outcome'] = 'interrupted' if outcome == RUN_INTERRUPTED else 'failed'
            # Retention is only real if something applies it. A finished run is
            # the natural moment: the databases are open, no writer is active and
            # the user just proved the machine is in use.
            housekeep(exclude_run_id=list(created) or [run_id])
            # The tee exists to catch the analyzers' print() output *during* a
            # run; leaving it installed meant every later print — from any
            # request — also showed up in the console panel.
            if isinstance(sys.stdout, _LogTee):
                sys.stdout = sys.stdout.unwrap()
            # Flush the run's own trailing console lines to the durable log, then disarm: the
            # sink must go before the slot is handed to the next run, so a queued run's first
            # line never writes into this run's batch. Flushing first loses the finish line —
            # every ``add_log`` up to and including the verdict has already been buffered.
            _run_log_writer.flush()
            set_log_sink(None)
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
        # held: ``running`` stuck True, ``settle_orphaned_records`` (which skips a
        # running slot) never helps, and every later 运行 parks forever. Give the slot
        # back and let the queue drain instead.
        # Disarm first: this run opened no record, so its start failure belongs to the
        # live console and the file log only — writing it to the durable per-run log
        # would orphan rows under a run id no record will ever list.
        _run_log_writer.reset()
        set_log_sink(None)
        execution_state['thread'] = None
        execution_state['running'] = False
        execution_state['stopping'] = False
        # One console line, localized; logger.exception keeps the traceback in the
        # file. add_log of the same text here would print the failure twice.
        logger.exception(t('run.start_failed', err=e))
        _start_next_queued()
        return {'status': 500, 'body': {'ok': False, 'error': str(e)}}

    return {'status': 200, 'body': {'ok': True, 'message': 'Workflow started', 'run_id': run_id}}


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
# executes them; the browser expands on Run and ``_begin_run``/``_scheduled_canvas`` expand a
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
