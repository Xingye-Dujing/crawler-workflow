"""``/api/workflow/*``: the canvas door — saved files, the waiting list, and the live console.

Twelve routes. The saved-canvas cluster writes and reads ``data/workflows`` through the store
singleton and keeps a reloaded canvas pointing at the datasets its upload nodes name; the queue
reads are the panel's view of what is parked; the stop/status/processes cluster is what the
console, the node badges and the thread inspector read while a run is in flight.

Two things are deliberately not here. ``/api/workflow/execute`` and ``/api/workflow/rerun-node``
still live in ``app.py`` because starting a run is the orchestration's own work, and
``_start_next_queued`` stays for the same reason — the queue drains by calling *that* function.
Nothing in this module imports ``app``: the run's state comes from :mod:`state`, its records
from :mod:`services.runs`, and the stop verdict is written by the settlement module that owns it.
"""

import ctypes
import logging
import os
import threading

from flask import Blueprint, jsonify, request
from state import (
    LOG_KEEP,
    _completed_lock,
    _results_snapshot,
    execute_lock,
    execution_state,
)
from stores import (
    _apply_dataset_meta,
    get_dataset_store,
    get_run_store,
    get_workflow_history_store,
    get_workflow_manager,
)

from api.http import _bad_body, _bad_param, _json_body, _optional_int
from engine.workflow import effective_workflow
from i18n import get_lang, set_lang, t
from services import lock_store
from services.ingest.lifecycle import close_login_browser as _close_login_browser
from services.runs.queue import (
    QUEUE_MAX,
    cancel_queued,
    clear_queue,
    queue_snapshot,
)
from services.runs.settlement import (
    STOP_QUIT_GRACE,
    close_active_crawlers,
    mark_records_stopping,
)
from services.runs.store import workflow_fingerprint
from services.workflows.manager import WorkflowManager

bp = Blueprint('workflow', __name__)

logger = logging.getLogger(__name__)


#: What a status read ships when nobody asks otherwise: the tail the console paints.
#: The buffer itself (``LOG_KEEP``, ``_wf_local``, ``add_log``/``_push_log``) lives in ``state``
#: and is grown by the run; what is decided here is only how much of it one read may carry.
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
    clean = get_workflow_manager().clean_name(name)
    if clean == WorkflowManager.DEFAULT_NAME and name != WorkflowManager.DEFAULT_NAME:
        # The name cleaned down to nothing, so the fallback would point at
        # somebody else's file.
        return None
    return clean


@bp.route('/api/workflow/save', methods=['POST'])
def save_workflow():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = data.get('name', 'untitled')
    workflow = data.get('workflow', {})
    if not isinstance(workflow, dict):
        return jsonify({'ok': False, 'error': t('api.paramInvalid', name='workflow')}), 400
    try:
        path = get_workflow_manager().save(name, workflow)
    except OSError as e:
        logger.exception(t('misc.save_workflow_failed'))
        return jsonify({'ok': False, 'error': str(e)}), 500
    # The file mapping is part of the save: every Upload node records which
    # stored dataset it reads, so reopening this workflow later finds its file
    # already loaded instead of asking for another upload.
    bound = get_dataset_store().bind(get_workflow_manager().clean_name(name), _workflow_dataset_refs(workflow))
    if bound:
        logger.info(t('store.datasets_bound', wf=get_workflow_manager().clean_name(name), n=bound))
    return jsonify({'ok': True, 'path': path, 'datasets': bound})


@bp.route('/api/workflow/load', methods=['GET'])
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
    workflow = get_workflow_manager().load(name)
    if not workflow:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    # Reconnect the nodes with their files *before* the canvas draws them, so
    # the workflow it returns is the runnable one.
    datasets = _restore_workflow_datasets(name, workflow)
    execution_state['workflow_name'] = str(workflow.get('name') or name or '')
    execution_state['fingerprint'] = workflow_fingerprint(effective_workflow(workflow))
    return jsonify({'ok': True, 'workflow': workflow, 'datasets': datasets})


@bp.route('/api/workflow/list', methods=['GET'])
def list_workflows():
    # Objects, not bare stems: the management panel shows node/dataset counts and
    # a modified time per file, which is what makes 打开/重命名/删除 an informed
    # choice instead of a name-blind file picker.
    return jsonify({'ok': True, 'workflows': get_workflow_manager().describe()})


@bp.route('/api/workflow/rename', methods=['POST'])
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
    if os.path.exists(get_workflow_manager().path_for(new)):
        return jsonify({'ok': False, 'error': t('api.workflowNameTaken', name=new)}), 409
    moved = get_workflow_manager().rename(old, new)
    if moved is None:
        # Unlike delete (idempotent), a rename of a missing file is a lost edit.
        return jsonify({'ok': False, 'error': t('api.workflowMissing', name=old)}), 404
    refs = get_dataset_store().move_workflow(old, new)
    # A layout baseline is keyed by the saved file's stem; leaving it under the old
    # name would silently switch the renamed canvas back to the algorithm.
    get_workflow_history_store().rename_layout(old, new)
    logger.info(t('api.workflowRenamed', old=old, new=new))
    return jsonify({'ok': True, 'name': new, 'path': get_workflow_manager().path_for(new), 'datasets': refs})


@bp.route('/api/workflow/delete', methods=['POST'])
def delete_workflow():
    data = _json_body()
    if data is None:
        return _bad_body()
    name = _request_workflow_name(data.get('name', ''))
    if name is None:
        return jsonify({'ok': False, 'error': t('api.workflowNameRequired')}), 400
    if lock_store.is_locked('workflows', name):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
    get_workflow_manager().delete(name)
    lock_store.drop('workflows', name)
    # The files stay: another workflow may well read the same one, and an
    # orphan is cleaned up later rather than on a deletion the user may undo
    # by saving something else with the same name.
    get_dataset_store().unbind(name)
    # The snapshots stay (history is independent of the file), but a deleted canvas's
    # layout pointer must not apply to the next workflow recreated under this name.
    get_workflow_history_store().delete_layout(name)
    return jsonify({'ok': True})


@bp.route('/api/workflow/queue', methods=['GET'])
def workflow_queue():
    """What is waiting, in the order it will start."""
    return jsonify({'ok': True, 'queue': queue_snapshot(), 'max': QUEUE_MAX})


@bp.route('/api/workflow/queue/cancel', methods=['POST'])
def workflow_queue_cancel():
    """Drop one waiting request. The running one is never touched."""
    data = _json_body()
    if data is None:
        return _bad_body()
    queue_id = data.get('id')
    if not isinstance(queue_id, str) or not queue_id.strip():
        return _bad_param('id')
    return jsonify({'ok': True, 'removed': cancel_queued(queue_id.strip())})


@bp.route('/api/workflow/queue/clear', methods=['POST'])
def workflow_queue_clear():
    """Empty the queue — 'do not start any of these', not 'stop the run'."""
    return jsonify({'ok': True, 'cleared': clear_queue()})


# ─── Stop / Status API ─────────────────────────────────────────


@bp.route('/api/workflow/stop', methods=['POST'])
def stop_workflow():
    # Hold the claim lock across the guard-and-write. ``_begin_run`` claims a run under
    # this same lock, so a run finishing right now cannot hand off to a queued one and
    # then have ``running=False``/``stopping=True`` land on that brand-new run — the
    # interleaving that made a stop aimed at run A silently kill run B. The idle check
    # and every state write below are therefore one atomic decision.
    with execute_lock:
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
        mark_records_stopping()
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
        close_active_crawlers(quit_timeout=STOP_QUIT_GRACE)

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


@bp.route('/api/workflow/status', methods=['GET'])
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
    # Per-node verdicts for THIS attempt, so the canvas can paint live spinners and
    # green/red badges without a second poll. Parallel nodes really do run at once,
    # so this is a map, not "the current node": every node holding ``running`` is
    # spinning. Included after the run settles too — the browser's final tick must
    # be able to paint the last verdict, and the next attempt clears the list.
    with _completed_lock:
        attempt_records = [str(rid) for rid in sorted(execution_state.get('attempt_records') or ())]
    if not attempt_records and execution_state.get('run_id'):
        attempt_records = [str(execution_state['run_id'])]
    node_states = {}
    if attempt_records:
        # Badges are an enhancement, not a verdict: a runs.db that cannot open must
        # not turn every console poll into an HTML 500 (the run itself already
        # reports that failure). The map is simply absent until the store answers.
        try:
            store = get_run_store()
            for rid in attempt_records:
                for nid, state in store.node_statuses(rid).items():
                    node_states[str(nid)] = {
                        'status': str(state.get('status') or ''),
                        'row_count': int(state.get('row_count') or 0),
                        'error': str(state.get('error') or ''),
                        'run_id': rid,
                    }
        except Exception as e:
            logger.debug('node_states unavailable: %s', e)
            node_states = {}
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
            'run_ids': attempt_records,
            'node_states': node_states,
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


@bp.route('/api/workflow/processes', methods=['GET'])
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


@bp.route('/api/workflow/processes/kill', methods=['POST'])
def kill_process():
    """Force-kill a thread by its ident. MainThread and 'run' thread are protected."""
    data = _json_body()
    if data is None:
        return _bad_body()
    ident = data.get('ident')
    if ident is None:
        return jsonify({'ok': False, 'error': t('api.killNoIdent')}), 400

    target = None
    for thread in threading.enumerate():
        if thread.ident == ident:
            target = thread
            break

    if target is None:
        return jsonify({'ok': False, 'error': t('api.killNotFound')}), 404

    if target.name in ('MainThread', 'run'):
        return jsonify({'ok': False, 'error': t('api.killProtected', name=target.name)}), 403

    # A live run's crawls execute on the executor's pool threads (parallel mode), not
    # on 'run'. Killing one injects SystemExit between acquiring a browser and
    # registering it, orphaning Chrome and holding its profile lock — the very harm the
    # 'run' guard exists for. While a run is live those threads are off-limits; Stop is
    # the graceful door.
    if execution_state['running'] and target.name.startswith('ThreadPoolExecutor'):
        return jsonify({'ok': False, 'error': t('api.killLiveWorker')}), 403

    if not target.is_alive():
        return jsonify({'ok': False, 'error': t('api.killNotAlive')}), 400

    try:
        ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), ctypes.py_object(SystemExit))
        if ret == 0:
            return jsonify({'ok': False, 'error': t('api.killInvalidId')}), 400
        if ret > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(ident), None)
            return jsonify({'ok': False, 'error': t('api.killFailedGeneric')}), 500
        return jsonify({'ok': True, 'message': t('api.killDone', name=target.name)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
