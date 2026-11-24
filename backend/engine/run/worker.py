"""The worker: one run's whole life on its own thread, from store open to queue hand-off.

``_run_worker`` is the body the claim starts. Everything below it is recorded against one run row,
so whatever leaves this thread early — Stop, an exception, the process dying — leaves behind enough
state to continue instead of starting over: the canvas is validated, the rerun's erase happens once
the slot is ours, the components run serially or in a pool, the verdict is settled from the rows,
and the ``finally`` flushes the durable log, releases the stop flag and hands the slot to the queue.

What is NOT here: which row each component writes (``engine.run.records``), the graph walk itself
(``engine.run.walk``), one node's durable settlement (``engine.run.node``), and the claim that
creates this thread (``engine.run.claim``).
"""

import contextlib
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from runtime import account_context, run_events
from runtime.state import (
    _completed_lock,
    _results_snapshot,
    _wf_local,
    add_log,
    execute_lock,
    execution_state,
    set_log_sink,
)
from runtime.stores import get_run_store

from engine.plan import component_name
from engine.run.decide import split_records
from engine.run.records import _close_component_record, _component_run, _invalidate_rerun_nodes, record_export_stamp
from engine.run.settle import finish_line, settle_attempt, verdict
from engine.run.walk import _mark_dead_workflow, _run_single_workflow, _run_workflow_wrapper, _wf_display_name
from engine.run_logs import LogTee, run_log_writer
from engine.workflow import WorkflowEngine, effective_workflow
from i18n import set_lang, t
from services.runs.history import record_execution_history
from services.runs.queue import drain_queue
from services.runs.settlement import close_run, housekeep
from services.runs.store import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_INTERRUPTED,
    fingerprints_for_workflow,
    workflow_fingerprint,
)

logger = logging.getLogger(__name__)


def start_next_queued() -> None:
    """Hand the slot to the oldest waiting request, at the end of a run.

    The queue's own work (pop, mirror, put-back, the recursion past a request that can never
    start) is :func:`services.runs.queue.drain_queue`; what stays here is only the injection of
    ``begin_run`` — the queue cannot import the app, and starting a run is the app's work.

    Called from the finishing thread *after* it released the slot and cleared its own handle:
    the claim also checks thread liveness, so a thread still alive while it unwinds would make
    this call queue the next request behind itself — and nothing would ever start it again.

    ``begin_run`` is resolved on the PACKAGE at call time, never bound here: the drain must reach
    the same ``engine.run.begin_run`` the routes and the clock do, so one patch governs them all.
    """
    from engine import run as run_package

    drain_queue(run_package.begin_run)


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


def _preflight_samples(workflow: dict) -> dict:
    """The stored upstream rows validation may judge, or nothing when they are unreadable.

    A preflight sample is a hint about a previous run; failing to read it may never refuse a run
    that would otherwise start, so the read is guarded and an error is logged (with its traceback)
    without a console line of its own.
    """
    try:
        from services.validation.samples import samples_for

        return samples_for(workflow)
    except Exception:  # a sample is advisory; the run gate keeps its static verdicts
        logger.exception(t('run.preflightSamplesFailed'))
        return {}


def _contract_columns(workflow: dict) -> dict:
    """Each node's table shape for the run gate, or nothing when it cannot be read.

    A recorded schema (``node_schema``) is evidence about a previous run of the same definition;
    failing to read it may never refuse a run that would otherwise start, so the read is guarded
    and logged without a console line of its own.
    """
    try:
        from services.validation.contracts import columns_for

        return columns_for(workflow)
    except Exception:  # the contract is evidence; the run gate keeps its static verdicts
        logger.exception(t('run.schemaReadFailed'))
        return {}


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
            # No record is open yet. ``close_run`` reads this instead of inferring
            # "nothing was opened" from a missing key: an early exit (a canvas
            # ``validate()`` refused) then closes nothing, where the fallback would
            # have re-finished ``ctx['run_id']`` — for a 继续 that id is the adopted
            # record, so a refusal that ran nothing stamped 失败/0-of-N over the
            # interrupted run's own history.
            'open_records': [],
            # {node_id: count} of items the incremental ledger refused; the
            # status endpoint mirrors it (shared dict, written by row sinks).
            'skipped_seen': {},
            # None = follow the setting; True/False = what the user chose for
            # this run when the canvas asked them (parallel + same platform).
            'use_profile': use_profile,
        }
        execution_state['skipped_seen'] = ctx['skipped_seen']
        engine = WorkflowEngine(workflow, execution_state['executor'])
        errors = engine.validate(samples=_preflight_samples(workflow), columns=_contract_columns(workflow))
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
            # buffer; the live console keeps what the user needs to fix the canvas. ``reset``
            # is explicit because ``disarm`` now WRITES whatever is still buffered (the normal
            # end-of-run tail), and a refused run must own no durable line.
            set_log_sink(None)
            run_log_writer.reset()
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
        # A record being resumed that covered the WHOLE canvas (a 并行 attempt) cannot be split
        # into per-workflow rows: its rows are filed under that one id, and a component record
        # refuses a node set it does not own — so every component but the first would start
        # from nothing and re-crawl what the record already holds. This attempt therefore keeps
        # ONE record too: the one the user pressed 继续 on.
        adopted_canvas = store.get_run(resume_run_id) if resume_run_id else None
        split_by_workflow = split_records(mode, wf_count, adopted_canvas)
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
        if not split_by_workflow:
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
        resumable = (
            store.list_resumable(fingerprint=wf_fp, limit=50, include_finished=True) if split_by_workflow else []
        )
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
                    if split_by_workflow
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
                if split_by_workflow:
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
        # Settle FIRST, then read the verdict — ``engine.run.settle`` is that order, and the rules
        # it encodes (a stopped node is not a failure, one broken node downgrades the run) live
        # there with their own tests instead of inside this 400-line body.
        settled = settle_attempt(store, created, still_running)
        stopped = settled['stopped']
        broken = settled['broken']
        add_log(finish_line(stopped, broken))
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
        # 'completed' must mean every node really finished: one broken node downgrades
        # the whole run to 'failed', and a stop outranks both (``engine.run.settle.verdict``).
        outcome = verdict(still_running, broken)

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
            final = {
                'outcome': execution_state['outcome'],
                'done': execution_state['completed_nodes'],
                'total': execution_state['total_nodes'],
                'failed': execution_state['failed_nodes'],
                'skipped': execution_state['skipped_nodes'],
            }
        if ctx is not None:
            # Published BEFORE the desktop popup and the retention sweep: a monitor's reaction
            # should not wait on a slow housekeeping pass, and a failed sweep must not swallow the
            # fact that the run ended. `records` names every row this attempt wrote (serial splits
            # write one per component), so a monitor bound to any of them matches.
            run_events.publish(
                'run.finished',
                run_id=str(execution_state.get('run_id') or ''),
                records=list(created) or [run_id],
                workflow=workflow_name,
                outcome=final['outcome'],
                done=final['done'],
                total=final['total'],
                failed=final['failed'],
                skipped=final['skipped'],
            )
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
