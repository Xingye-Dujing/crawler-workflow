"""The claim: the ONE start path for a run, owned by the slot, or parked in the queue.

``begin_run`` validates the canvas shape, expands a reusable group, asks the mode and the provider
by their own refusal doors, and then — under ``execute_lock`` — either refuses, parks the request,
or claims the slot and starts ``_run_worker`` on a thread named ``run``. The queue drains by calling
*this* function, the clock's scheduled fire reaches it by name, and ``/api/workflow/execute`` is its
route, so a queued or scheduled run goes through exactly the same validations and bookkeeping as a
live one.

Two rules hold the stamps below apart. A refused claim owns nothing, so every key it wrote before
the refusal is handed back (``_restore_claim_stamp``) — otherwise account B becomes the owner of
A's finished run. A claim that cleared the previous run's console, preview and counters before a
``Thread.start()`` that then failed must hand them back too (``_run_state_stamp``), or the user is
left reading a blank board for a run whose thread does not exist.
"""

import logging
import threading
import uuid

from core.config import Config
from core.refs import as_bool, flag_or_none
from core.values import safe_int as _safe_int
from runtime import account_context
from runtime.settings import get_setting
from runtime.state import (
    ambient,
    execute_lock,
    execution_state,
    forget_ambient,
    reset_console_state,
    set_ambient,
    set_log_sink,
)
from runtime.transport import _local_transport_refusal

from engine.executor import TaskExecutor
from engine.plan import llm_provider, run_mode, workflow_needs_llm
from engine.run.records import _rerun_request
from engine.run.worker import _run_worker, start_next_queued
from engine.run_logs import run_log_writer
from engine.workflow import effective_workflow
from i18n import normalize, t
from services.analysis.pipeline import UnknownOperationError
from services.runs.payload import resume_refusal, workflow_shape_error
from services.runs.queue import enqueue_run
from services.runs.store import workflow_fingerprint
from services.workflows.expand import expand_reusable_workflow

logger = logging.getLogger(__name__)

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


def cloud_refusal_response(provider: str) -> dict:
    """The 400 body for :func:`_local_transport_refusal`, shaped per caller.

    ``drop`` because a transport this host cannot speak is not something a later run fixes: a parked
    entry would be re-tried after every finish and would starve every entry behind it."""
    return {'status': 400, 'body': {'ok': False, 'error': _local_transport_refusal(provider)}, 'drop': True}


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
        # A thread that cannot start is a permanent refusal, not a busy slot: without ``drop``
        # the queue drains this entry back onto the front after every later run, starving the
        # requests behind it and surviving a restart in the mirror.
        return {'status': 500, 'drop': True, 'body': {'ok': False, 'error': str(start_error)}}

    return {'status': 200, 'body': {'ok': True, 'message': 'Workflow started', 'run_id': run_id}}
