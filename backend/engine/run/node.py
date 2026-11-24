"""One node, durably: dispatch it, store what it produced, grade the outcome.

This is the code that owns "what does a node do, and what does its result become" — the executor
dispatch (``execute_node``), the checkpointing walk of ONE node (``run_node_durable``), the Stop
verdict (``settle_node_as_stopped``), the memory warning (``note_heavy_result``) and the optional
after-run data check (``_postcheck_node``).

Why these are together: they are one decision chain — dispatch the node, store its rows, grade the
outcome. Splitting them across modules is how a Stop and a failure end up with two different
answers about what the node did.

Nothing here knows about records, components or the queue: the walk that orders nodes is
``engine.run.walk``, the claim that starts a thread is ``engine.run.claim``.
"""

from nodes import registry as node_registry
from nodes.catalog import QUIET_NODE_TYPES
from nodes.context import NodeCall
from nodes.labels import node_label
from runtime.state import _completed_lock, _wf_local, add_log, ambient, execution_state, stop_requested

from analyzers.llm_client import ABORT_MARK
from crawlers.core.faults import CrawlerStopped
from engine.run.asset import lineage_conflict, record_asset
from i18n import t
from services.runs.store import (
    NODE_DONE,
    NODE_FAILED,
    NODE_PARTIAL,
    NODE_RESTORED,
    NODE_SKIPPED,
    schema_of_rows,
)

# Node types that never read the ROWS their inputs carry. Their data comes
# from somewhere else — the platform crawler, the already-uploaded file, the
# run store, (for `name`) nowhere at all, or (for `compile`) a visualize parent's
# LaTeX *dict*, which is not a row table at all. The "upstream came up empty →
# skip" rule below keys on `any parent result is a non-empty list`, so a compile
# hanging off a visualize (a dict) would be skipped as "no rows" — exempting it
# is what lets it read its source. A whole chain off a name node is the other case.
NON_INPUT_NODES = frozenset({'source', 'upload', 'resume', 'name', 'comment', 'compile'})

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
    store.finish_node(run_id, nid, NODE_PARTIAL, error=err, schema=schema_of_rows(rows))
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
        # …and the rows must have been computed from the content that is upstream NOW. The
        # fingerprint says the node was not edited; it cannot say the parent's table is the same
        # one. Only a KNOWN mismatch refuses (see ``engine.run.asset.lineage_conflict``), so an
        # older run keeps the structural rule.
        and not lineage_conflict(store, run_id, nid, upstream)
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

    # An edit explicitly applied from a node-trace conversation (apply_node_result) overrides this
    # node's execution on a rerun of the SAME run. consume() removes the edit so a later rerun
    # executes for real instead of replaying a stale answer forever. This is the read side of
    # services/coding/node_results.save — without it the "confirm the edit, then rerun" promise
    # wrote a file that nobody ever opened.
    from services.coding import node_results

    try:
        applied = node_results.consume(run_id, nid)
    except ValueError:
        applied = None  # an odd node id must never stop the node it belongs to
    if applied is not None and isinstance(applied.get('result'), list):
        rows = applied['result']
        store.replace_rows(run_id, nid, rows, label=label)
        add_log(t('run.applied_trace_result', nid=label, n=len(rows)), wf_idx=wf_idx)
        record_asset(store, ctx, node, nid, rows, upstream)
        store.finish_node(run_id, nid, NODE_DONE, schema=schema_of_rows(rows))
        return rows, NODE_DONE

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
        store.finish_node(run_id, nid, status, error=str(e), schema=schema_of_rows(rows))
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
        record_asset(store, ctx, node, nid, result, upstream)
        store.finish_node(run_id, nid, NODE_PARTIAL, schema=schema_of_rows(result))
        return result, NODE_PARTIAL
    # Close the node's visible LLM trace (a no-op for nodes without one). This is the ONE generic
    # hook: any future LLM-backed node gets a settled trace and the confirm→rerun coordinates.
    from services.llm_trace import finish_node_trace

    finish_node_trace(
        run_id,
        nid,
        {
            # The operation the node actually ran, not its type ('process'/'analysis'). The trace
            # result meta is read by the apply route and the workspace; a type is not an answer.
            'op': str(node.get('operation') or (node.get('params') or {}).get('operation') or ntype or ''),
            'rows': len(result) if isinstance(result, list) else 0,
            'workflow_name': str(ambient().get('workflow_name') or ''),
            'text': t('trace.finished', node=label, rows=len(result) if isinstance(result, list) else 0),
            # A small in/out sample for traditional-model traces: they have no chat loop, so this is
            # the only evidence of what the model actually saw and produced. Bounded in llm_trace.
            'input_rows': primary if isinstance(primary, list) else [],
            'output_rows': result if isinstance(result, list) else [],
        },
    )
    store.finish_node(
        run_id,
        nid,
        NODE_DONE,
        schema=schema_of_rows(result) if isinstance(result, list) else None,
    )
    # The content identity of what this node produced: written last, so a row only ever names a
    # table that the store really holds (see ``engine/run/asset.py``).
    record_asset(store, ctx, node, nid, result, upstream)
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


def note_heavy_result(rows, label: str) -> None:
    """Say out loud how much of this run is being held in memory.

    Deliberately not an error and not a refusal: a large table is often exactly what was
    asked for, and the run is still the user's to finish. What it must not be is invisible
    — an OOM has no node name attached to it.
    """
    if not isinstance(rows, list) or len(rows) < HEAVY_RESULT_ROWS:
        return
    add_log(t('run.heavy_result', nid=label, n=len(rows)))


def _postcheck_node(node: dict, rows, inputs, label: str, wf_idx: int):
    """Run the capability's optional after-run data check and print one line per finding.

    Advisory by design: the node's rows are already produced and stored, so a quality finding never
    changes its status — it turns a silent empty output into a named console line. A broken hook is
    its own named line, never an exception into the run loop.
    """
    from capabilities_kernel.registry import manifest_for_node

    from services.validation.engine import postcheck_problems

    manifest = manifest_for_node(str(node.get('type') or ''))
    if manifest is None or not manifest.postcheck:
        return
    found = postcheck_problems(
        manifest,
        node,
        rows if isinstance(rows, list) else [],
        inputs if isinstance(inputs, list) else [],
    )
    for problem in found:
        add_log(t(problem['message_key'], nid=label, **problem['context']), wf_idx=wf_idx)
