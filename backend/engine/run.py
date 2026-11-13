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

What is NOT here, because it answers a different question: the console's write paths
(``engine.run_logs`` — the print() tee and the durable per-run log, armed and disarmed by this
module's run window) and the scheduler's seam (``engine.run_schedule`` — may this canvas run
unattended, and what happened when it fired). Both moved out on 2026-10-29 as verbatim copies;
``begin_run`` is still the only path that starts a run, and the queue drains by calling it.

The one rule for what stays INSIDE ``begin_run``: a helper that needs no state from the claim
belongs at module scope, where a test can reach it and a reader can see its inputs. Ten were
lifted out on 2026-10-29 for exactly that reason — first ``_wf_display_name`` (closed over nothing),
``_run_single_workflow`` (one value: ``headless``), ``_continue_record`` (``resumable``,
``resuming``) and ``_close_component_record`` (``ctx``, ``store``), then ``_carries_artifact``,
``_node_of``, ``_inputs_for``, ``_component_run``, ``_run_workflow_wrapper`` and the worker body
itself (``run`` → ``_run_worker``, the claim's eight results as eight parameters); each captured
name became a parameter and the file now nests no function inside a function at all.
``tests/unit/gates/test_run_worker_module_scope.py`` refuses a move back.
"""

import contextlib
import logging
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from api.http import _safe_int
from core.config import Config
from core.refs import as_bool, export_stamp, flag_or_none
from nodes import registry as node_registry
from nodes.catalog import QUIET_NODE_TYPES
from nodes.context import NodeCall
from nodes.labels import node_label
from runtime import account_context
from runtime.settings import get_setting
from runtime.state import (
    _completed_lock,
    _results_snapshot,
    _wf_local,
    add_log,
    ambient,
    execute_lock,
    execution_state,
    forget_ambient,
    reset_console_state,
    set_ambient,
    set_log_sink,
    stop_requested,
)
from runtime.stores import get_run_store
from runtime.transport import _local_transport_refusal

from analyzers.llm_client import ABORT_MARK
from crawlers.core.faults import CrawlerStopped
from engine.executor import TaskExecutor
from engine.plan import component_name, llm_provider, run_mode, workflow_needs_llm
from engine.run_logs import LogTee, run_log_writer
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

logger = logging.getLogger(__name__)

# Node types that never read the ROWS their inputs carry. Their data comes
# from somewhere else — the platform crawler, the already-uploaded file, the
# run store, (for `name`) nowhere at all, or (for `compile`) a visualize parent's
# LaTeX *dict*, which is not a row table at all. The "upstream came up empty →
# skip" rule below keys on `any parent result is a non-empty list`, so a compile
# hanging off a visualize (a dict) would be skipped as "no rows" — exempting it
# is what lets it read its source. A whole chain off a name node is the other case.
NON_INPUT_NODES = frozenset({'source', 'upload', 'resume', 'name', 'comment', 'compile'})


def _settle_published_rows(store, run_id: str, nid: str, label: str):
    """Make the durable node rows agree with the table this attempt actually produced.

    LLM/process nodes publish the whole table on every batch into ``execution_state['results']``
    but never write it to the store; crawlers stream their rows there directly. Settling a
    stopped/failed node must persist the published table before ``finish_node`` reads
    ``row_count`` — otherwise the console says "已保留 N 行" and the record says 0 (or the
    previous attempt's K), so a page reload cannot see the rows the user was told were kept.
    """
    published = execution_state['results'].get(nid)
    if not isinstance(published, list):
        return store.load_rows(run_id, nid)
    stored = store.row_count(run_id, nid)
    if published and len(published) != stored:
        store.replace_rows(run_id, nid, published, label=label)
    return published if published else store.load_rows(run_id, nid)


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
    rows = _settle_published_rows(store, run_id, nid, label)
    store.finish_node(run_id, nid, NODE_PARTIAL, error=err)
    with _completed_lock:
        execution_state['stopped_node_ids'].add(nid)
    add_log(t('run.nodeStopped', nid=label, n=len(rows)), wf_idx=wf_idx)
    return rows, NODE_PARTIAL


def _carries_artifact(res: object) -> bool:
    # A visualize / compile parent hands down a DICT, not rows; that dict IS its product (a chart spec
    # carrying LaTeX, or a staged PDF). "empty upstream" must not read a chart as nothing, or a
    # chart→save(PDF) and a chart→compile would both be skipped before either runs.
    if not isinstance(res, dict) or res.get('error'):
        return False
    return any(key in res for key in ('latex', 'latex_table', 'pdf_file'))


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
        rows = _settle_published_rows(store, run_id, nid, label)
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
    ``tests/unit/analysis/test_node_plugins.py``.
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
    """The 400 body for :func:`_local_transport_refusal`, shaped per caller.

    ``drop`` because a transport this host cannot speak is not something a later run fixes: a parked
    entry would be re-tried after every finish and would starve every entry behind it."""
    return {'status': 400, 'body': {'ok': False, 'error': _local_transport_refusal(provider)}, 'drop': True}


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
    fallback = str(ambient().get('workflow_name') or '').strip() or t('wf.unnamed', i=wf_idx + 1)
    return (
        t('wf.component_indexed', name=fallback, i=wf_idx + 1, n=execution_state.get('wf_count') or 1)
        if (execution_state.get('wf_count') or 1) > 1
        else fallback
    )


def _node_of(wf_engine, nid: str) -> dict:
    return wf_engine.nodes.get(nid) or {}


def _inputs_for(wf_engine, nid: str, upstream_of, results, wf_idx):
    """→ (rows of the first incoming connection, [(parent_id, result), …]).

    The full list travels with the node so a join can use the *second*
    incoming connection as its right-hand table; every other node just
    takes the first one.
    """
    parents = upstream_of.get(nid) or []
    if not parents:
        # A source (crawler or upload) has nothing upstream.
        return [], []
    # ``fuse`` folds every parent and ``verify`` reads exactly two, so for those the
    # "the first is the primary input" sentence would describe a rule they do not have.
    # Every other type takes the first wire and says so, because a silently ignored table
    # is the shape this console line exists to prevent.
    if len(parents) > 1 and _node_of(wf_engine, nid).get('type') not in ('fuse', 'verify'):
        add_log(
            t(
                'wf.multi_input',
                nid=node_label(_node_of(wf_engine, nid), nid),
                up=node_label(_node_of(wf_engine, parents[0]), parents[0]),
                n=len(parents),
            ),
            wf_idx=wf_idx,
        )
    pairs = [(pid, results.get(pid)) for pid in parents]
    primary = pairs[0][1]
    # A chart spec (dict) is not tabular input; neither is a node that
    # has not produced a list.
    return (primary if isinstance(primary, list) else []), pairs


def _run_single_workflow(wf_engine, wf_idx: int, ctx: dict, headless):
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

    for level in levels:
        if _stopping():
            break
        for nid in level:
            if _stopping():
                break
            node = wf_engine.nodes[nid]
            label = node_label(node, nid)
            with _completed_lock:
                # Recorded before the node runs: one abandoned mid-crawl must
                # still be in this attempt's population, or the settle pass in
                # the finish line would filter the very node it exists to count.
                execution_state['attempted_nodes'].add(nid)
            primary, upstream = _inputs_for(wf_engine, nid, upstream_of, results, wf_idx)
            # The output (save) node merges every parent's rows into one table; to make that
            # table say which rows came from which platform (what 跨平台对比 reads), the run
            # loop — the only place holding the whole graph — resolves each parent's platform
            # here. None for every other node type; a non-crawl parent (upload/resume) is '' ,
            # never a guessed platform.
            _platform_of = None
            _labels_of = None
            # The node types that NAME their parents in the console: an output merge quotes
            # the wire it refuses, the two-table steps print which parent fills which role
            # (清单/结果, 筛选/依据), and the verify node does both. A bare `node-2` in a
            # message about WHICH wire to cut or which table is the basis is the one thing
            # the console rule exists to stop.
            if upstream and node.get('type') in ('output', 'verify', 'analysis'):
                _labels_of = {}
                for _pid, _res in upstream:
                    _pn = _node_of(wf_engine, str(_pid))
                    _labels_of[str(_pid)] = node_label(_pn, str(_pid))
                if node.get('type') == 'output':
                    _platform_of = {}
                    for _pid, _res in upstream:
                        _pn = _node_of(wf_engine, str(_pid))
                        _p = _pn.get('platform') or (_pn.get('params') or {}).get('platform') or ''
                        _platform_of[str(_pid)] = str(_p)
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


def _record_has_component(candidate: dict, node_ids: set | None) -> bool:
    """Whether a stored row carries any node of this component (or says nothing about nodes)."""
    if not node_ids:
        return True
    stored = {str(node.get('node_id') or '') for node in candidate.get('nodes') or [] if isinstance(node, dict)}
    return not stored or bool(stored & node_ids)


def _continue_record(
    name: str,
    resumable: list,
    resuming: bool,
    requested: str = '',
    fingerprint: str = '',
    node_ids: set | None = None,
) -> dict:
    """The row this workflow should keep writing, if it is a 继续.

    Only the resume path adopts: the attempt after a 继续 must accumulate
    onto the rows that already exist, so it finds each workflow's own
    unfinished row of this canvas again instead of opening a fresh one per
    press. A plain Run is a new attempt and gets new rows — "one record per
    attempt" is what makes the panel's history mean anything.

    ``requested`` is the id the user pressed 继续 on. It is preferred over the
    newest name match: re-deriving the record from the name alone made a run on an
    OLD interrupted row adopt the newer (even completed) row of the same workflow,
    rewrite its history and leave the chosen row interrupted forever.

    The id may be older than the 50 rows the caller could list. The caller prepends
    the requested row's own record, so this function sees it; the fingerprint is the
    identity that survives a 工作流命名 edit, because the label is not an input.

    Adopting CONSUMES the candidate (it is popped, not re-read): validate only
    asks a name node for a non-empty label, so one canvas may legitimately carry
    two same-named components, and a match that stayed in the list handed BOTH
    the same run_id — the second ``start_run`` upsert reset the first's record
    to running/node_done=0, its verdict overwrote the first's, and the other
    same-named row of the previous attempt was left an orphan nobody adopts.
    """
    if not resuming:
        return {}
    wanted = str(requested or '')
    if wanted:
        for position, candidate in enumerate(resumable):
            same_component = str(candidate.get('workflow_name') or '') == name
            same_canvas = bool(fingerprint) and str(candidate.get('workflow_fingerprint') or '') == fingerprint
            if (
                str(candidate.get('run_id') or '') == wanted
                and (same_component or same_canvas)
                and _record_has_component(candidate, node_ids)
            ):
                return dict(resumable.pop(position))
    for position, candidate in enumerate(resumable):
        candidate_fp = str(candidate.get('workflow_fingerprint') or '')
        if fingerprint and candidate_fp and candidate_fp != fingerprint:
            # A same-named component of another fingerprint is a different record; adopting it
            # put the upload's node on the crawl's row.
            continue
        if not _record_has_component(candidate, node_ids):
            continue
        if str(candidate.get('workflow_name') or '') == name:
            return dict(resumable.pop(position))
    return {}


def _stopping() -> bool:
    """Whether this run has been asked to end, from either of the two places that say so.

    ``execution_state['running']`` is the wall flag the Stop route clears. The run's own
    handle (``execution_state['executor']``) is what ``/api/workflow/stop`` sets, and it used
    to be write-only: nothing read it, so the object looked wired while the loop only ever
    watched the wall flag. Both are asked here — a stop is a stop whichever door it came in.

    Neither can interrupt a node that is already mid-flight (a page load, a BERT batch); that
    is what the crawlers' ``may_stop`` and the analyzers' ``cancel_event`` are for, and the
    Stop route also closes live crawlers directly. What this guarantees is that no FURTHER
    node starts.
    """
    if not execution_state['running']:
        return True
    handle = execution_state.get('executor')
    return bool(handle is not None and getattr(handle, 'stop_requested', False))


def _close_component_record(sub_ctx: dict, ctx: dict, store) -> None:
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
        1 for nid, state in statuses.items() if nid in visited and state.get('status') in (NODE_FAILED, NODE_PARTIAL)
    )
    outcome = RUN_INTERRUPTED if not still_running else (RUN_FAILED if broken else RUN_COMPLETED)
    store.finish_run(rid, outcome, attempted=visited)
    with contextlib.suppress(ValueError):
        ctx['open_records'].remove(rid)


def _component_run(
    wf_idx, sub_engine, ctx, created, resumable, resuming, wf_fp, skipped_str, store, run_id, mode, headless
):
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
    # The requested id is offered to EVERY component and adopted only by the one whose name it
    # carries: the banner can offer a row of a component that is not workflow zero, and a
    # name-only match would otherwise still pick that component's newest row.
    # The requested row may be older than the 50 newest rows the list holds. Fetch it by id so
    # "继续 the row I clicked" never degrades into "resume the newest same-named row" (or a cold
    # start after a pure label edit).
    component_ids = {str(key) for key in sub_engine.nodes}
    if resuming and run_id and not any(str(item.get('run_id') or '') == str(run_id) for item in resumable):
        requested_record = store.get_run(run_id)
        # Only the component the record belongs to may add it. The upload workflow in a serial
        # canvas shares the canvas name but has its own nodes; inserting the crawl's row for it
        # made the fallback-by-name adopt a record of another component.
        recorded_fp = str((requested_record or {}).get('workflow_fingerprint') or '')
        if (
            requested_record
            and (not wf_fp or not recorded_fp or recorded_fp == wf_fp)
            and _record_has_component(requested_record, component_ids)
        ):
            resumable.insert(0, requested_record)
    earlier = _continue_record(name, resumable, resuming, requested=run_id, fingerprint=wf_fp, node_ids=component_ids)
    rid = str(earlier.get('run_id') or '') or (run_id if wf_idx == 0 else uuid.uuid4().hex[:12])
    with execute_lock:
        # Opening the next serial record must be atomic with the bulk-delete routes' "which
        # records are live" read. The worker used to start_run() outside this lock, so a 清空
        # that saw only the previous workflow's id could delete this brand-new row while rows
        # were being written under it.
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
        execution_state.setdefault('record_owners', {})[rid] = account_context.current()
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


def _mark_dead_workflow(ctx: dict, wf_engine, wf_idx: int, exc: Exception) -> None:
    """Persist a workflow-level failure so the run's verdict can see it.

    ``_run_single_workflow`` can raise outside ``run_node_durable`` — a graph walk
    (``group_by_level`` / ``connections`` / ``_inputs_for``) that the canvas shape broke, or a
    stage that could not be built. No node wrote a terminal status in that case, and the run
    verdict is read from those rows: the branch used to settle ``broken=0`` and report 已完成
    while it had produced nothing and offered no 继续.

    Every node of the dead workflow that has not already settled is written as FAILED, and
    added to this attempt's population so the finish line counts it. Nodes that finished
    before the fault keep their own verdict.
    """
    store = (ctx or {}).get('store')
    run_id = (ctx or {}).get('run_id')
    if store is None or not run_id:
        return
    settled = (NODE_DONE, NODE_PARTIAL, NODE_FAILED, NODE_SKIPPED, NODE_RESTORED)
    statuses = store.node_statuses(run_id)
    message = t('wf.wf_exception', wf=_wf_display_name(wf_engine, wf_idx))
    detail = str(exc or '').strip()
    if detail:
        message = f'{message} [{type(exc).__name__}: {detail}]'
    for nid, node in wf_engine.nodes.items():
        nid = str(nid)
        if (statuses.get(nid) or {}).get('status') in settled:
            continue
        store.begin_node(
            run_id,
            nid,
            str(node.get('type') or ''),
            title=str(node.get('title') or node.get('name') or ''),
            fingerprint=((ctx.get('fingerprints') or {}).get(nid) or ''),
            component=wf_idx,
            component_name=getattr(_wf_local, 'name', '') or '',
        )
        store.finish_node(run_id, nid, NODE_FAILED, error=message)
        with _completed_lock:
            execution_state['attempted_nodes'].add(nid)


def _run_workflow_wrapper(wf_engine, wf_idx, ctx, headless, all_results, wf_lock, account=None):
    # Pool threads inherit neither the starter's thread-local nor the account context. Binding
    # the run's own account here is what keeps a parallel workflow's exports, run store, cookie
    # directory and previews inside that account instead of falling back to the system scope.
    account_token = account_context.bind(account)
    # Pool threads do not inherit the starter's thread-local.
    set_lang(execution_state.get('lang'))
    try:
        results = _run_single_workflow(wf_engine, wf_idx, ctx, headless)
        with wf_lock:
            all_results.update(results)
    except Exception as exc:
        # One console line per dead workflow. The log handler
        # forwards every logger call to the console as well, so
        # logging *and* add_log printed the same sentence twice —
        # and the logger form is the one that also carries the
        # traceback to the log file.
        #
        # The verdict is read from the durable node rows, so a branch that died before any node
        # settled must leave a FAILED status behind. Without it the run reported 已完成 with
        # this workflow silently missing and no 继续 banner.
        _mark_dead_workflow(ctx, wf_engine, wf_idx, exc)
        logger.exception(t('wf.wf_exception', wf=_wf_display_name(wf_engine, wf_idx)))
    finally:
        # Same release as the serial path: a pool thread that kept
        # its index would file anything it logs afterwards —
        # teardown included — under that one workflow's tab.
        _wf_local.idx = None
        _wf_local.name = ''
        account_context.unbind(account_token)


def _rerun_request(data: dict, run_id: str):
    """The subtree a “重跑节点” pressed to redo, or ``None``.

    The route computes the closure but must NOT erase it: the wipe deletes stored rows and releases
    this run's dedupe claims, and a run that then lost the slot would leave the rows gone, the
    rerun never run, and a second press refused because the node has no rows any more. The payload
    therefore carries the intent, and the worker performs it once the slot is actually ours.
    """
    raw = data.get('rerun_invalidate')
    if not isinstance(raw, dict):
        return None
    if str(raw.get('run_id') or '').strip() != str(run_id):
        # A mirrored entry restored after a restart, or a stale payload: never erase a run that
        # this request did not name.
        return None
    node_ids = [str(node) for node in (raw.get('node_ids') or ()) if str(node or '')]
    return {'run_id': run_id, 'node_ids': node_ids} if node_ids else None


def _invalidate_rerun_nodes(store, run_id: str, rerun) -> list:
    """Erase the rerun's subtree now that this run owns the slot; answer the ids it removed.

    No console line here: :meth:`invalidate_nodes` already reports how many “已采集” claims it
    handed back, and a second sentence about the same wipe is the noise AGENTS refuses."""
    if not rerun or str(rerun.get('run_id') or '') != str(run_id):
        return []
    store.invalidate_nodes(run_id, rerun['node_ids'])
    return list(rerun['node_ids'])


def _notify_run_outcome(workflow_name: str, outcome: str) -> None:
    """One system notification when a run really ends.

    The window may be minimised for hours, so a finish that only exists in the console is a finish
    nobody sees. A Stop is excluded on purpose (the user just pressed it), and so is a refusal before
    any node ran (``total_nodes == 0``): the panel is already saying that.
    """
    if outcome not in (RUN_COMPLETED, RUN_FAILED):
        return
    from services import desktop

    if not desktop.active():
        return
    total = int(execution_state.get('total_nodes') or 0)
    if not total:
        return
    done = int(execution_state.get('completed_nodes') or 0)
    name = str(workflow_name or '').strip() or t('desktop.untitled')
    if outcome == RUN_COMPLETED:
        desktop.notify(t('desktop.runDoneTitle'), t('desktop.runDoneBody', name=name, done=done, total=total))
        return
    failed = int(execution_state.get('failed_nodes') or 0)
    desktop.notify(
        t('desktop.runFailedTitle'),
        t('desktop.runFailedBody', name=name, failed=failed, done=done, total=total),
    )


def _run_worker(
    workflow, mode, headless, use_profile, run_id, resume_run_id, workflow_name, max_workers, account=None, rerun=None
):
    # The run thread starts here, not in a request handler — inherit the
    # language the UI asked for, or every line below would come out in the
    # server default.
    set_lang(execution_state.get('lang'))
    # Same reason for the identity: a worker thread inherits no context. Binding it here makes
    # every ``get_run_store()`` / path lookup below the owning account's, and the ``finally``
    # restores the thread's previous (empty) context before the slot is handed on.
    account_token = account_context.bind(account)
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
            # No record was opened, so nothing may persist these lines: the durable sink would
            # file them under the claim-stamped run id, and no viewer or retention sweep can ever
            # name that id again (every query walks ``runs``). Take the sink off and drop the
            # buffer; the live console keeps what the user needs to fix the canvas.
            set_log_sink(None)
            run_log_writer.disarm()
            return

        # A rerun's erase happens HERE, after the slot is ours AND after the canvas was accepted —
        # never in the request that queued it, and never before ``validate()``. The erase deletes
        # ``node_rows``, ``node_runs`` and the node's ``item_seen`` claims, so doing it first meant a
        # canvas the engine then refused (a lost login, a bad param) had already destroyed the paid
        # subtree and started nothing (AGENTS: a refused claim owns nothing; a durable mutation
        # follows the claim). Everything below reads node statuses to decide what to reuse, so the
        # pruned subtree still has to be gone before that read.
        _invalidate_rerun_nodes(store, run_id, rerun)

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
            execution_state.setdefault('record_owners', {})[run_id] = account_context.current()
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
        resumable = store.list_resumable(fingerprint=wf_fp, limit=50, include_finished=True) if split_records else []
        resuming = bool(resume_run_id)

        if mode == 'serial' or wf_count <= 1:
            # ── Serial: one workflow at a time ──
            all_results = {}
            for wf_idx, se in enumerate(sub_engines):
                if not execution_state['running']:
                    break
                sub_ctx = (
                    _component_run(
                        wf_idx, se, ctx, created, resumable, resuming, wf_fp, skipped_str, store, run_id, mode, headless
                    )
                    if split_records
                    else ctx
                )
                # Tagged with its OWN index: this line is printed before
                # _run_single_workflow sets the thread-local, so it used to be
                # filed under the *previous* component's tab — workflow A's
                # console announcing “开始执行工作流“B””.
                add_log(t('wf.starting', name=_wf_display_name(se, wf_idx)), wf_idx=wf_idx)
                try:
                    results = _run_single_workflow(se, wf_idx, sub_ctx, headless)
                except Exception as exc:
                    # Same durable verdict as the parallel wrapper: the outer handler marks the
                    # run failed, but without a FAILED node row the resume banner and the
                    # per-node panel would still describe a branch that never produced anything.
                    _mark_dead_workflow(sub_ctx, se, wf_idx, exc)
                    raise
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
                    _close_component_record(sub_ctx, ctx, store)
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

            pool = ThreadPoolExecutor(max_workers=min(wf_count, max_workers))
            futures = [
                pool.submit(_run_workflow_wrapper, se, i, ctx, headless, all_results, wf_lock, account)
                for i, se in enumerate(sub_engines)
            ]
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
            execution_state['outcome'] = 'interrupted' if not still_running else ('failed' if broken else 'completed')
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
                    # The record THIS component wrote: `created` is appended once per component
                    # (serial split) or once for the whole run (parallel/single), and wf_idx is
                    # that same position. Without it 执行历史 invented an id nothing else knew.
                    run_id=created[wf_idx] if wf_idx < len(created) else run_id,
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
        # `stopping` is NOT cleared here. It goes in the final section below, together with the
        # thread handle: the stop route proves "a run is live" and writes its flags under
        # ``execute_lock``, and settling the record takes seconds. Clearing here let a second Stop
        # press re-pin “正在停止” over a run that had already answered, and ``stop_requested()``
        # then handed that stale flag to every later crawl.
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
        # The verdict is final; only now is a system notification true. It sits before the
        # housekeeping below so a slow database sweep cannot delay the popup, and it is a no-op on
        # a host with no desktop shell (a source run, a cloud deploy).
        with contextlib.suppress(Exception):
            _notify_run_outcome(workflow_name, outcome)
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
        # Forget the owner too: a batch that outlives its run must not be filed under a later run.
        # (A batch the failed flush kept carries its own owner in ``_pending``, so this only clears
        # the next batch's default.)
        run_log_writer.disarm()
        # Release the handle this thread was recognised by, then let the queue have the slot. Both
        # before anything else in this finally can be reordered: ``start_next_queued`` checks
        # liveness through it. The stop flag leaves WITH it, inside the claim lock — the stop route
        # proves a run is live and writes its flags under this same lock, so a second 停止 pressed
        # while this thread was still settling cannot re-pin “正在停止” onto a run that has already
        # published its verdict, and ``stop_requested()`` never hands a stale stop to the next crawl.
        with execute_lock:
            execution_state['stopping'] = False
            execution_state['thread'] = None
        # Drop this thread's identity BEFORE the queue hands the slot on: the next request is
        # started under its own owner, never under this run's.
        account_context.unbind(account_token)
        start_next_queued()


#: Marks an ``execution_state`` key the previous claim never wrote (``run_id``/``resume`` are
#: absent until a run actually claims them), so a refusal can hand the key back instead of
#: leaving a ``None`` the readers would then have to tolerate.
_ABSENT = object()

#: What a claim writes BEFORE its last payload refusals (the LLM transport and key/model checks
#: below the run id). A refusal that leaves these stamped hands the previous owner's console,
#: results and canvas identity to the caller that did not start a run — and marks the true owner
#: a foreign one.
_CLAIM_STAMP_KEYS = (
    'run_id',
    'user_id',
    'username',
    'resume',
    'workflow_labels',
    'skipped_workflow_labels',
    'lang',
    'llm',
)


#: The console, result and counter keys a claim CLEARS before it starts its thread. They are
#: not ownership stamps: on a ``Thread.start()`` failure the previous run's finished console and
#: preview must come back, or a start that never happened erases what the user was reading.
_DESTRUCTIVE_CLAIM_KEYS = (
    'results',
    'executor',
    'logs',
    '_log_total',
    '_wf_logs',
    '_wf_log_total',
    '_wf_names',
    '_time_windows',
    'total_nodes',
    'completed_nodes',
    'skipped_nodes',
    'failed_nodes',
)


def _claim_stamp() -> dict:
    """A restoreable copy of the ownership keys a claim is about to write."""
    return {key: execution_state.get(key, _ABSENT) for key in _CLAIM_STAMP_KEYS}


def _run_state_stamp() -> dict:
    """A restoreable copy of the state a claim clears before its worker exists."""
    return {key: execution_state.get(key, _ABSENT) for key in _DESTRUCTIVE_CLAIM_KEYS}


def _restore_run_state(stamp: dict) -> None:
    for key, value in stamp.items():
        if value is _ABSENT:
            execution_state.pop(key, None)
        else:
            execution_state[key] = value


def _restore_claim_stamp(stamp: dict, ambient_before: dict) -> None:
    """Give back every stamp a refused claim touched, so a loser owns nothing."""
    for key, value in stamp.items():
        if value is _ABSENT:
            execution_state.pop(key, None)
        else:
            execution_state[key] = value
    if ambient_before:
        set_ambient(ambient_before.get('workflow_name') or '', ambient_before.get('fingerprint') or '')
        return
    # The caller held no canvas identity before this claim, so it must hold none after: writing
    # an empty pair would leave a key where no key belonged (and the local owner has no such
    # choice — its identity IS the two globals).
    account = account_context.current()
    if account is None:
        set_ambient('', '')
    else:
        forget_ambient(account.user_id)


def begin_run(data: dict, lang_header: str) -> dict:
    """Claim the run slot and start the worker, or put this request in the queue.

    Split out of the route because the queue drains by calling *this* function
    from the finishing run's own thread: a queued request has to be started the
    same way a live one is — same validations, same claim, same bookkeeping —
    or the queue would be a second, weaker execution path.

    Answers ``{'status': int, 'body': dict}`` instead of a Flask response,
    because the caller is not always a request.

    A refusal may carry ``'drop': True``: that is the start path telling the queue this payload can
    never start — a canvas the engine cannot walk, a corrupt reusable group, an unknown mode or
    provider, a transport this host does not speak, a 继续 pointing at a purged record. Re-parking
    one of those is not patience: the drain puts the entry back at the FRONT and returns, so one
    unstartable request starves every request behind it, forever, and survives a restart in the
    mirror. A transient refusal (“另一个运行正在进行”) deliberately has no ``drop``.
    """
    shape_error = workflow_shape_error(data)
    if shape_error:
        # Refused before the slot is claimed: a payload the engine cannot walk
        # must not become a failed run record, let alone a queued one that dies
        # in a thread nobody is watching.
        return {'status': 400, 'body': {'ok': False, 'error': shape_error}, 'drop': True}
    # A saved workflow keeps a reusable node as ONE group (so reopening can render it);
    # a run needs its children. The browser already expands on Run, but a scheduled fire
    # starts from the file and every queued request must see the same graph, so the
    # expansion happens here — before the claim, the mode/fingerprint and the queue.
    workflow, reusable_error = expand_reusable_workflow(data.get('workflow') or {})
    if reusable_error:
        return {'status': 400, 'body': {'ok': False, 'error': reusable_error}, 'drop': True}
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
        return {'status': 400, 'body': {'ok': False, 'error': str(e)}, 'drop': True}
    resume_error = resume_refusal(data)
    if resume_error:
        # 'drop' tells the queue this entry can never start, so it is discarded
        # rather than pushed back to wait for a run that no longer exists.
        return {'status': 400, 'body': {'ok': False, 'error': resume_error}, 'drop': True}
    # Guard and claim are one critical section. They used to be ~70 lines
    # apart: two concurrent POSTs both passed the check, both started a run
    # thread, and interleaved writes into one console, one store, one crawl.
    start_error: Exception | None = None
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
        _stamp_before = _claim_stamp()
        _state_before = _run_state_stamp()
        _ambient_before = ambient()
        try:
            workflow = data.get('workflow', {})
            settings = workflow.get('settings', {})
            mode = run_mode(settings)
            # A cloud host has no display, so headless is not a preference here — the
            # browser would never come up. The panel hides the switch (it is told the
            # server's shape by /api/config), but the run record is written from THIS
            # value, and a record that said “窗口” for a crawl that could only have run
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
            # text 'false' — a draft that says “不用 Profile” in a hand-edited file would have
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
            # Read after the id exists: a rerun names the run whose subtree it wants redone.
            rerun = _rerun_request(data, run_id)
            execution_state['run_id'] = run_id
            # Which account owns the one shared slot. The status/stop/process endpoints compare
            # this with the request's account; the worker below re-binds the same identity, so
            # every store it opens is that account's.
            _owner = account_context.current()
            execution_state['user_id'] = _owner.user_id if _owner is not None else ''
            execution_state['username'] = _owner.username if _owner is not None else ''
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
            # node id alone — "node-2" exists in every workflow. The identity is the
            # caller's own: another account's canvas must never re-key this run.
            set_ambient(workflow_name, workflow_fingerprint(effective))

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
                        return {'status': 400, 'body': {'ok': False, 'error': t('api.needApiKey')}, 'drop': True}
                    if not llm['model']:
                        return {'status': 400, 'body': {'ok': False, 'error': t('api.needModel')}, 'drop': True}
                elif not llm['model']:
                    return {'status': 400, 'body': {'ok': False, 'error': t('api.needOllamaModel')}, 'drop': True}

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
            run_log_writer.arm(_owner)
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
            # Claim AND start in ONE critical section. They used to be two: the handle was
            # published after ``execute_lock`` was released, so a 停止 (or a second Run) landing in
            # that window saw ``running=True`` with ``thread=None``, cleared the flag, and the next
            # Run then claimed the slot — after which this start overwrote
            # ``execution_state['thread']``, leaving TWO workers sharing one console, one results
            # dict and one owner (and a run whose lines were filed under the other's record).
            # ``Thread.start()`` returns as soon as the bootstrap runs, so the lock is held for
            # microseconds rather than for the worker's life.
            #
            # Named 'run' so the process-monitor's kill guard (see ``kill_process``) actually
            # matches: it refuses to inject SystemExit into ('MainThread', 'run'), but an unnamed
            # thread reported as "Thread-N" let a stray click on the live worker raise SystemExit
            # between acquiring a browser and registering it, orphaning a Chrome and holding its
            # profile lock for the full timeout.
            try:
                execution_state['thread'] = threading.Thread(
                    target=_run_worker,
                    args=(
                        workflow,
                        mode,
                        headless,
                        use_profile,
                        run_id,
                        resume_run_id,
                        workflow_name,
                        max_workers,
                        _owner,
                        rerun,
                    ),
                    daemon=True,
                    name='run',
                )
                execution_state['thread'].start()
            except Exception as e:  # a start that throws is a verdict below, never a swallowed error
                start_error = e
            started = True
        finally:
            if not started:
                # A rejection (already-configured checks, malformed body) gives
                # the claim back — the guard must not lock out every later Run.
                execution_state['running'] = False
                # …and gives back what it stamped while validating, too: the run id, the owner
                # and the canvas identity a refusal never earned. Without this, account B whose
                # canvas needs a model it has not configured becomes the owner of A's finished
                # run, reads A's console and results, and A is told its own run is foreign.
                _restore_claim_stamp(_stamp_before, _ambient_before)

    if start_error is not None:
        # A thread that never started never runs its finally, so the claim would stay held:
        # ``running`` stuck True, ``settle_orphaned_records`` (which skips a running slot) never
        # helps, and every later 运行 parks forever. Give the slot back and let the queue drain.
        #
        # Disarm first: this run opened no record, so its start failure belongs to the live console
        # and the file log only — writing it to the durable per-run log would orphan rows under a
        # run id no record will ever list.
        run_log_writer.disarm()
        set_log_sink(None)
        execution_state['thread'] = None
        execution_state['running'] = False
        execution_state['stopping'] = False
        # …and hand back the identity too. The claim stamped run_id/user_id/username/resume/lang/llm
        # before the thread existed, so a thread that never started left every reader of
        # /api/workflow/status answering a run that has no record (and every OTHER account getting
        # ``foreign_run``). AGENTS: a refused claim owns nothing.
        _restore_claim_stamp(_stamp_before, _ambient_before)
        # The previous run's console/preview/counters were cleared before ``start()`` was called;
        # a start that never happened must hand them back, not leave the user reading an empty
        # console and a blank canvas for a run whose thread does not exist.
        _restore_run_state(_state_before)
        # One console line, localized; logger.exception keeps the traceback in the file.
        logger.exception(t('run.start_failed', err=start_error))
        # Below the lock: the drain starts the next request through ``begin_run``, which needs it.
        start_next_queued()
        return {'status': 500, 'body': {'ok': False, 'error': str(start_error)}}

    return {'status': 200, 'body': {'ok': True, 'message': 'Workflow started', 'run_id': run_id}}
