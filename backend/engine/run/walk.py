"""The graph walk: one component's nodes, level by level, in canvas order.

``_run_single_workflow`` is the loop the console talks about — one level at a time, each node's
inputs taken from the connections that reach it, a failed node handing downstream what it managed
to produce. ``_run_workflow_wrapper`` is the same loop for a parallel run's pool thread, which
inherits neither the starter's thread-local nor the account context.

``_stopping`` answers "has this run been asked to end" from both doors (the wall flag and the
run handle); ``_inputs_for`` is the one place that turns connections into ``(primary, upstream)``.
"""

import logging

from nodes.catalog import QUIET_NODE_TYPES
from nodes.labels import node_label
from runtime import account_context, run_events
from runtime.state import _completed_lock, _wf_local, add_log, ambient, execution_state

from engine.plan import component_name
from engine.run.node import _postcheck_node, run_node_durable
from i18n import set_lang, t
from services.runs.store import NODE_DONE, NODE_FAILED, NODE_PARTIAL, NODE_RESTORED, NODE_SKIPPED

logger = logging.getLogger(__name__)


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
            # One event per node attempt, after the store has the terminal status. Monitors match
            # on the status/row count here; the AI reads the full node table through its own
            # read-only tool, so the bus stays a notification channel, not a second data path.
            run_events.publish(
                'node.finished',
                run_id=str(ctx.get('run_id') or ''),
                node_id=nid,
                node_type=str(node.get('type') or ''),
                label=label,
                status=status,
                rows=len(result) if isinstance(result, list) else 0,
                wf_idx=wf_idx,
                workflow=wf_name,
            )
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
            _postcheck_node(node, result, primary, label, wf_idx)
    return results


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
