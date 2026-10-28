"""The run's worker half: one node at a time, durably.

This is the code that owns "what does a node do, and what does its result become" — the
executor dispatch (``execute_node``), the checkpointing walk (``run_node_durable``), the
Stop verdict (``settle_node_as_stopped``) and the memory warning (``note_heavy_result``).
It moved out of ``app.py`` because a Blueprint, the scheduler clock and a future CLI all
need to ask the same question, and the layering says nothing below the composition root may
import it: this module imports ``state``/``stores``/``services``/``engine`` and never ``app``.

Why these four are together: they are one decision chain — dispatch the node, store its rows,
grade the outcome. Splitting them across modules is how a Stop and a failure end up with two
different answers about what the node did.
"""

import contextlib
import logging
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from api.http import _safe_int
from core.config import Config
from core.refs import as_bool, export_stamp, flag_or_none
from nodes import registry as node_registry
from nodes.catalog import QUIET_NODE_TYPES
from nodes.context import NodeCall
from nodes.labels import node_label
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
    stop_requested,
)
from stores import get_run_store
from transport import _local_transport_refusal

from analyzers.llm_client import ABORT_MARK
from crawlers.core.faults import CrawlerStopped
from engine.executor import TaskExecutor
from engine.plan import component_name, llm_provider, run_mode, workflow_needs_llm
from engine.workflow import WorkflowEngine, effective_workflow
from i18n import normalize, set_lang, t
from services.analysis.pipeline import UnknownOperationError
from services.runs.history import record_execution_history
from services.runs.payload import resume_refusal, workflow_shape_error
from services.runs.queue import drain_queue, enqueue_run
from services.runs.settlement import close_run, housekeep
from services.runs.store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_RESTORED,
    NODE_SKIPPED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    fingerprints_for_workflow,
    workflow_fingerprint,
)
from services.workflows.expand import expand_reusable_workflow
from settings_store import get_setting

logger = logging.getLogger(__name__)

# Node types that never read the ROWS their inputs carry. Their data comes
# from somewhere else — the platform crawler, the already-uploaded file, the
# run store, (for `name`) nowhere at all, or (for `compile`) a visualize parent's
# LaTeX *dict*, which is not a row table at all. The "upstream came up empty →
# skip" rule below keys on `any parent result is a non-empty list`, so a compile
# hanging off a visualize (a dict) would be skipped as "no rows" — exempting it
# is what lets it read its source. A whole chain off a name node is the other case.
NON_INPUT_NODES = frozenset({'source', 'upload', 'resume', 'name', 'comment', 'compile'})


def settle_node_as_stopped(store, run_id: str, nid: str, label: str, wf_idx: int, err: str = ''):
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


def run_node_durable(
    ctx: dict,
    node: dict,
    headless: bool,
    primary: list,
    upstream: list,
    wf_idx: int,
    platform_of: dict | None = None,
    label_of=None,
):
    """Run one node with the run store underneath it. Returns (result, status).

    Three things it adds over calling ``execute_node`` directly:

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
        and ntype not in NON_INPUT_NODES
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
        if ntype not in QUIET_NODE_TYPES:
            ntype_label = t(f'node.{ntype}')
            if ntype_label.startswith('node.'):
                ntype_label = ntype
            add_log(
                t('wf.executing_node', wf=execution_state['_wf_names'].get(wf_idx) or '', nid=label, ntype=ntype_label),
                wf_idx=wf_idx,
            )
        result = execute_node(
            node, headless, primary, upstream=upstream, ctx=ctx, platform_of=platform_of, label_of=label_of
        )
    except CrawlerStopped:
        return settle_node_as_stopped(store, run_id, nid, label, wf_idx)
    except Exception as e:
        if stop_requested():
            # The browser was killed under a Stop, so what reaches here is a dead
            # session, not a site refusing and not a node that broke. Reported the
            # same way on purpose: a stopped run whose summary blames the user's own
            # button press on their workflow teaches them never to press it.
            return settle_node_as_stopped(store, run_id, nid, label, wf_idx, err=str(e))
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
        note_heavy_result(result, label)
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


def execute_node(
    node: dict,
    headless: bool,
    current_input: list,
    run_ctx: dict = None,
    upstream: list = None,
    ctx: dict = None,
    platform_of: dict | None = None,
    label_of=None,
):
    """Run one node. ``upstream`` is [(parent_id, result), …] in connection
    order — only the analysis node needs more than the first entry (a join uses
    the second one as its right-hand table).

    The executor comes from ``nodes.registry``, where every node type registered itself when the
    plugin package was imported; the catalogue and the registry are pinned against each other by
    ``tests/unit/test_node_plugins.py``.
    """
    ntype = node.get('type')
    executor = node_registry.executor_for(ntype)
    if executor is not None:
        return executor(
            node,
            NodeCall(
                headless=headless,
                current_input=current_input,
                run_ctx=run_ctx,
                upstream=upstream,
                ctx=ctx,
                platform_of=platform_of,
                label_of=label_of,
            ),
        )
    # No plugin claimed this type. ``validate`` refuses an unknown type before a run, so this is
    # defense in depth for a direct caller — but it must still refuse BY NAME: returning [] here
    # would settle the node DONE over an empty table (see AGENTS.md).
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


def note_heavy_result(rows, label: str) -> None:
    """Say out loud how much of this run is being held in memory.

    Deliberately not an error and not a refusal: a large table is often exactly what was
    asked for, and the run is still the user's to finish. What it must not be is invisible
    — an OOM has no node name attached to it.
    """
    if not isinstance(rows, list) or len(rows) < HEAVY_RESULT_ROWS:
        return
    add_log(t('run.heavy_result', nid=label, n=len(rows)))


class LogTee:
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


class RunLogWriter:
    """Write-through of the live console into the durable per-run log (``run_store.run_log``).

    Installed as ``state``'s log sink only for the window a run is in flight (armed in
    ``begin_run``, disarmed in the worker's ``finally``), so a message logged outside any
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


run_log_writer = RunLogWriter()


def record_export_stamp(store, run_id: str) -> str:
    """The filename component that names one record, read from the record itself.

    Taken from ``started_at`` and not from the clock, because ``PartWriter`` adopts the
    shards an interrupted attempt already flushed by matching its stem as a prefix: a
    component that moved between attempts would leave those parts orphaned beside a
    numbering that restarted at 001. 继续 never refreshes ``started_at`` — the record's
    date is when this work began — which is exactly the stability this needs.
    """
    record = store.get_run(run_id) or {}
    return export_stamp(record.get('started_at'), run_id)


def start_next_queued() -> None:
    """Hand the slot to the oldest waiting request, at the end of a run.

    The queue's own work (pop, mirror, put-back, the recursion past a request that can never
    start) is :func:`services.runs.queue.drain_queue`; what stays here is only the injection of
    ``begin_run`` — the queue cannot import the app, and starting a run is the app's work.

    Called from the finishing thread *after* it released the slot and cleared its own handle:
    the claim also checks thread liveness, so a thread still alive while it unwinds would make
    this call queue the next request behind itself — and nothing would ever start it again.
    """
    drain_queue(begin_run)


def cloud_refusal_response(provider: str) -> dict:
    """The 400 body for :func:`_local_transport_refusal`, shaped per caller."""
    return {'status': 400, 'body': {'ok': False, 'error': _local_transport_refusal(provider)}}


def begin_run(data: dict, lang_header: str) -> dict:
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
                    return cloud_refusal_response(llm['provider'])
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
            run_log_writer.reset()
            set_log_sink(run_log_writer.push)
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
                if node.get('type') not in QUIET_NODE_TYPES:
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
        sys.stdout = LogTee(sys.__stdout__)
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
                ctx['export_stamp'] = record_export_stamp(store, run_id)
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
                    export_stamp=record_export_stamp(store, rid),
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
            if isinstance(sys.stdout, LogTee):
                sys.stdout = sys.stdout.unwrap()
            # Flush the run's own trailing console lines to the durable log, then disarm: the
            # sink must go before the slot is handed to the next run, so a queued run's first
            # line never writes into this run's batch. Flushing first loses the finish line —
            # every ``add_log`` up to and including the verdict has already been buffered.
            run_log_writer.flush()
            set_log_sink(None)
            # Release the handle this thread was recognised by, then let the
            # queue have the slot. Both before anything else in this finally can
            # be reordered: start_next_queued checks liveness through it.
            execution_state['thread'] = None
            start_next_queued()

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
        run_log_writer.reset()
        set_log_sink(None)
        execution_state['thread'] = None
        execution_state['running'] = False
        execution_state['stopping'] = False
        # One console line, localized; logger.exception keeps the traceback in the
        # file. add_log of the same text here would print the failure twice.
        logger.exception(t('run.start_failed', err=e))
        start_next_queued()
        return {'status': 500, 'body': {'ok': False, 'error': str(e)}}

    return {'status': 200, 'body': {'ok': True, 'message': 'Workflow started', 'run_id': run_id}}
