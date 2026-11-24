"""The records one attempt writes: which row a component keeps, and how it is closed.

A run's identity is not the canvas's: serial splits one attempt into one record per workflow that
starts, a parallel attempt keeps one row named 'A + B', and a 继续 keeps the row it was pressed on.
These functions are that bookkeeping — ``_component_run`` opens a component's row, the decisions
about WHICH row come from ``engine.run.decide``, ``_close_component_record`` gives it its own
verdict, and the two rerun helpers carry the "重跑节点" subtree to the worker that owns the slot.
"""

import contextlib
import os
import uuid

from core.refs import export_stamp
from runtime import account_context, paths, run_events
from runtime.state import _completed_lock, add_log, execute_lock, execution_state

from engine.run.decide import choose_record, record_belongs
from engine.run.walk import _wf_display_name
from i18n import t
from services.runs.store import NODE_FAILED, NODE_PARTIAL, RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED


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

    Workflow zero takes the id the HTTP response already handed out — but only when the record
    that id names is THIS component's (see ``requested_owns`` below). The others are minted as
    they are reached.

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
    requested_record = store.get_run(run_id) if (resuming and run_id) else None
    if (
        requested_record is not None
        and not any(str(item.get('run_id') or '') == str(run_id) for item in resumable)
        and record_belongs(requested_record, component_ids, wf_fp)
    ):
        # Only the component the record belongs to may add it. The upload workflow in a serial
        # canvas shares the canvas name but has its own nodes; inserting the crawl's row for it
        # made the fallback-by-name adopt a record of another component.
        resumable.insert(0, requested_record)
    adopted_at, earlier = choose_record(
        name, resumable, resuming, requested=run_id, fingerprint=wf_fp, node_ids=component_ids
    )
    if adopted_at is not None:
        resumable.pop(adopted_at)
    # The requested id may only be REUSED by the component that record actually belongs to.
    # ``run_id`` is the record the user pressed 继续 on; when its sibling record was deleted
    # (or aged out) the first component used to keep writing into the OTHER workflow's row —
    # two workflows in one "serial" record, ``node_done`` counted against one component's
    # ``node_total`` (4/3) and the history carrying the same id twice.
    requested_owns = record_belongs(requested_record, component_ids, wf_fp)
    # A PLAIN run's id is the row the claim just opened for the whole attempt, so workflow zero
    # takes it as before; a 继续 may only keep it when that row is this component's.
    takes_requested = wf_idx == 0 and (not resuming or requested_owns)
    rid = str(earlier.get('run_id') or '') or (run_id if takes_requested else uuid.uuid4().hex[:12])
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
            export_dir=paths.active().export_dir,
        )
        group = str((store.get_run(rid) or {}).get('export_group') or '')
        ctx['export_group'] = group
        ctx['export_dir'] = os.path.join(paths.active().export_dir, group) if group else paths.active().export_dir
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
    run_events.publish(
        'run.started',
        run_id=rid,
        # The display name was resolved at the top of this function. ``_wf_local.name`` is only
        # assigned later in ``_run_single_workflow``, so reading it here published an empty
        # workflow on a fresh run — the monitor/event consumer got an id with no name to show.
        workflow=name,
        wf_idx=wf_idx,
        resume=bool(earlier),
    )
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
