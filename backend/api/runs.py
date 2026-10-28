"""``/api/runs/*``: the run-record panel's whole read/write side.

Twelve routes over the durable ledger — which runs can be continued, the records themselves,
the live status of the run in flight, retention (purge / discard / delete / clear, each of which
must spare what the user pinned), the detail panel, and the two console-log reads. Nothing here
starts a run: ``/api/workflow/execute`` and the orchestration stay in ``app.py``, and the panel
asks ``state`` who is running instead of keeping a second opinion.

The log reads share :func:`_log_filters` on purpose — the JSON page and the ``.log.txt``
download must answer the same ``wf``/``level``/``q`` question, because the download is
「所见即所存」.
"""

import logging

from flask import Blueprint, Response, jsonify, request
from state import execution_state, live_run_ids
from stores import get_run_store

from api.http import _bad_body, _json_body, _safe_int
from engine.workflow import effective_workflow
from i18n import t
from services import lock_store
from services.runs.payload import workflow_shape_error
from services.runs.queue import queue_snapshot
from services.runs.settlement import (
    locked_run_ids,
    prune_orphan_run_locks,
    reject_live_run,
    settle_orphaned_records,
)
from services.runs.store import RUN_RUNNING, workflow_fingerprint

bp = Blueprint('runs', __name__)

logger = logging.getLogger(__name__)


@bp.route('/api/runs/resumable', methods=['POST'])
def runs_resumable():
    """Runs worth offering to resume, for the workflow currently on the canvas.

    Matched on the *structure* (node ids, types and wiring), not the settings:
    tweaking a keyword should still find the interrupted attempt of this same
    workflow. The browser also gets the per-node breakdown it needs to say what
    is already paid for.

    ``all`` flips the question the 断点续跑 node asks: it grafts a stored node's rows
    into a graph that need not resemble the run they came from — adding the resume
    node itself changes the canvas fingerprint — so it lists every run that still
    holds data instead of only this canvas's own interrupted attempt.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    workflow = data.get('workflow') or {}
    if not isinstance(workflow, dict) or not workflow.get('nodes'):
        return jsonify({'ok': True, 'runs': []})
    limit = _safe_int(data.get('limit'), 10, minimum=1, maximum=100)
    # Same repair as the panel's: a record its worker abandoned must become
    # continuable on a page load, not only once somebody opens 运行记录.
    settle_orphaned_records()
    if data.get('all'):
        found = get_run_store().list_resumable(None, limit=limit, include_finished=True)
    else:
        found = get_run_store().list_resumable(workflow_fingerprint(effective_workflow(workflow)), limit=limit)
    # A *live* run is never resumable — offering it invites 重新开始 to discard
    # the run that is still writing right now. Leftover 'running' rows from a
    # dead process were already promoted to 'interrupted' at startup.
    runs = [r for r in found if r.get('status') != RUN_RUNNING]
    return jsonify({'ok': True, 'runs': runs})


@bp.route('/api/runs/for-workflow', methods=['POST'])
def runs_for_workflow():
    """Every recorded run of the workflow currently on the canvas, newest first.

    This is the 运行记录 panel's 当前工作流 tab: unlike ``/resumable`` it keeps
    finished runs (their node outputs are what the canvas loads by default),
    and unlike ``/list`` it refuses to offer runs whose canvas has since been
    rewired. Matching is on structure exactly as a 继续 does — node ids, types
    and wiring — because loading rows under node ids the canvas no longer has
    would put another workflow's table behind the user's box. Editing a
    parameter keeps the identity; adding or removing a node changes it, and
    that run stops being offered rather than quietly mismatching.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    workflow = data.get('workflow') or {}
    empty = {'ok': True, 'runs': [], 'latest_run_id': '', 'workflow_fingerprint': '', 'queue': queue_snapshot()}
    if not isinstance(workflow, dict) or not workflow.get('nodes'):
        return jsonify(empty)
    shape_error = workflow_shape_error({'workflow': workflow})
    if shape_error:
        return jsonify({'ok': False, 'error': shape_error}), 400
    limit = _safe_int(data.get('limit'), 50, minimum=1, maximum=200)
    # Opening this tab is also a moment to repair a record whose worker died in a
    # previous process — same as the resumable list, so both doors agree.
    settle_orphaned_records()
    fingerprint = workflow_fingerprint(effective_workflow(workflow))
    runs = get_run_store().list_resumable(fingerprint, limit=limit, include_finished=True)
    return jsonify(
        {
            'ok': True,
            'runs': runs,
            'latest_run_id': runs[0]['run_id'] if runs else '',
            'workflow_fingerprint': fingerprint,
            'queue': queue_snapshot(),
        }
    )


@bp.route('/api/runs/list', methods=['GET'])
def runs_list():
    """Every recorded run, newest first — the run-records panel's backbone.

    Unlike /resumable this is not filtered by the canvas: orphaned runs (the
    workflow has since been rewired or deleted) must stay visible here, or
    they can never be continued or cleaned up.
    """
    limit = _safe_int(request.args.get('limit'), 50, minimum=1, maximum=200)
    store = get_run_store()
    # Asking the store is the moment to repair it: this is the read that happens when
    # somebody opens the panel because a record looks wrong.
    settle_orphaned_records()
    runs = store.list_resumable(limit=limit, include_finished=True)
    # The waiting list rides along: the panel that shows finished runs is where
    # someone looks to see what has not started yet.
    return jsonify({'ok': True, 'runs': runs, 'queue': queue_snapshot()})


@bp.route('/api/runs/status', methods=['GET'])
def runs_status():
    """Live state of the run in flight (its id and how far it got), so a page
    reload mid-run can still offer to continue it afterwards."""
    return jsonify(
        {
            'ok': True,
            'running': bool(execution_state.get('running')),
            'run_id': execution_state.get('run_id') or '',
            'resume': bool(execution_state.get('resume')),
        }
    )


@bp.route('/api/runs/stats', methods=['GET'])
def runs_stats():
    return jsonify({'ok': True, 'stats': get_run_store().stats()})


@bp.route('/api/runs/purge', methods=['POST'])
def runs_purge():
    """Housekeeping. Interrupted runs are the last to go — they are the ones
    somebody may still want to continue. The live run, if any, is exempt, and so
    is every 置顶 record (a manual purge must not silently undo a pin either)."""
    keep: list[str] = []
    keep += live_run_ids()
    keep += sorted(locked_run_ids())
    removed = get_run_store().purge(exclude_run_id=keep)
    prune_orphan_run_locks()
    return jsonify({'ok': True, 'removed': removed})


@bp.route('/api/runs/discard', methods=['POST'])
def runs_discard():
    """Throw away an interrupted run and start the next one from scratch.

    The "already collected" claims go with it: without that, pressing start
    over would silently return fewer rows than asked for, because every item
    the discarded attempt fetched still counts as seen.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    if not run_id:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid='-')}), 400
    store = get_run_store()
    if store.get_run(run_id) is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id)}), 404
    if reject_live_run(run_id):
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 400
    if lock_store.is_locked('runs', run_id):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
    removed = store.delete_run(run_id)
    removed['item_claims'] = store.forget_run_items(run_id)
    return jsonify({'ok': True, 'removed': removed})


@bp.route('/api/runs/delete', methods=['POST'])
def runs_delete():
    """Drop a finished run's copy of the data. Kept separate from discard:
    deleting an old run must not resurrect items as "unseen" for a crawl
    that is still being continued."""
    data = _json_body()
    if data is None:
        return _bad_body()
    run_id = str(data.get('run_id') or '').strip()
    if not run_id:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid='-')}), 400
    if reject_live_run(run_id):
        return jsonify({'ok': False, 'error': t('api.alreadyRunning')}), 400
    if lock_store.is_locked('runs', run_id):
        return jsonify({'ok': False, 'error': t('lock.refuse')}), 409
    removed = get_run_store().delete_run(run_id)
    lock_store.drop('runs', run_id)
    return jsonify({'ok': True, 'removed': removed})


@bp.route('/api/runs/clear', methods=['POST'])
def runs_clear():
    """Empty the run records — the panel's 清空 button.

    Refuses by name without ``confirm``: every other route in this file acts on a single id
    the browser just showed the user, while this one acts on all of them at once, so a stray
    POST (or a mistyped fetch from a console) must not be able to erase a history.

    A run that is live right now keeps its record: ``RunStore.clear_all`` is handed its id,
    because deleting rows a worker is still writing would destroy state mid-flight. What the
    deleted runs claimed as "already crawled" goes with them — see ``clear_all`` for why the
    bulk case releases claims where a single deletion keeps them.
    """
    data = _json_body()
    if data is None:
        return _bad_body()
    if data.get('confirm') is not True:
        return jsonify({'ok': False, 'error': t('api.needConfirm')}), 400
    live = live_run_ids()
    # 清空 spares every run a live thread is still writing AND every locked one — the user
    # pinned those on purpose. A serial pass closes one record per workflow, so this is a set
    # rather than the single id the request thread happens to hold.
    keep = list(live)
    keep.extend(lock_store.all_locks()['runs'])
    removed = get_run_store().clear_all(exclude_run_ids=keep)
    logger.warning(t('run.cleared', runs=removed['runs'], claims=removed['item_claims']))
    return jsonify({'ok': True, 'removed': removed})


@bp.route('/api/runs/<run_id>', methods=['GET'])
def runs_detail(run_id: str):
    """One run, node by node — what the resume node's picker enumerates."""
    run = get_run_store().get_run(run_id)
    if run is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id)}), 404
    return jsonify({'ok': True, 'run': run})


#: A durable log is stored in full, but a single HTTP read is page-boxed so no request can
#: ask the store to materialise a run's whole console at once. The download walks pages of
#: this size; a runaway crawl is bounded by this ceiling so the .txt stays openable.
_LOG_PAGE = 500
_LOG_PAGE_MAX = 2000
_LOG_DOWNLOAD_CAP = 100_000


def _log_filters(req):
    """The shared ``wf``/``level``/``q`` query parameters for both log reads.

    ``wf`` is a per-workflow tab (a parallel run's console splits by tab); an empty value
    means 「全部」 and filters on nothing. Kept in one place so the JSON page and the .txt
    download answer the exact same question — the download is 「所见即所存」.
    """
    wf_raw = str(req.args.get('wf') or '').strip()
    # ``wf`` is a tab ORDINAL (0..N-1). A negative value is not a tab that exists; filtering on
    # it matched nothing and left the viewer showing 「无内容」 for a run that has lines. Read an
    # impossible index as the 「全部」 tab (no filter) rather than a filter that empties the panel.
    wf_idx = int(wf_raw) if wf_raw.isdigit() else None
    level = str(req.args.get('level') or '').strip().lower()
    level = level if level in ('info', 'warning', 'error') else None
    q = str(req.args.get('q') or '').strip() or None
    return wf_idx, level, q


@bp.route('/api/runs/<run_id>/log', methods=['GET'])
def runs_log_page(run_id: str):
    """One page of a run's persisted console, oldest→newest, for the after-the-fact viewer.

    ``before`` walks 「加载更早」 (the smallest seq already shown); ``level``/``wf``/``q``
    narrow it. This reads ONLY the durable ``run_log`` table — it never touches
    ``execution_state`` and cannot affect the live console or the refresh-reattach.
    """
    store = get_run_store()
    if store.get_run(run_id) is None:
        return jsonify({'ok': False, 'error': t('api.runNotFound', rid=run_id)}), 404
    wf_idx, level, q = _log_filters(request)
    limit = _safe_int(request.args.get('limit'), _LOG_PAGE, minimum=1, maximum=_LOG_PAGE_MAX)
    before_raw = str(request.args.get('before') or '').strip()
    before_seq = int(before_raw) if before_raw.lstrip('-').isdigit() else None
    page = store.read_log(run_id, wf_idx=wf_idx, level=level, q=q, before_seq=before_seq, limit=limit)
    return jsonify({'ok': True, **page})


@bp.route('/api/runs/<run_id>/log.txt', methods=['GET'])
def runs_log_download(run_id: str):
    """The whole persisted console as a downloadable ``.txt`` — with the viewer's filters, so
    a download reproduces exactly what the panel shows (「所见即所存」)."""
    store = get_run_store()
    if store.get_run(run_id) is None:
        return t('api.runNotFound', rid=run_id), 404, {'Content-Type': 'text/plain; charset=utf-8'}
    wf_idx, level, q = _log_filters(request)
    # ``read_log`` walks backward (「加载更早」 hands back its smallest seq). So the download
    # reads the newest page, then each strictly-older page, collecting blocks; the oldest
    # page is collected LAST, and flattening the blocks in reverse gives the whole filtered
    # console ascending in one pass (a repeated list prepend here would be quadratic).
    blocks: list[list[str]] = []
    total = 0
    truncated = False
    before_seq = None
    while total < _LOG_DOWNLOAD_CAP:
        page = store.read_log(run_id, wf_idx=wf_idx, level=level, q=q, before_seq=before_seq, limit=_LOG_PAGE_MAX)
        rows = page['rows']
        if not rows:
            break
        blocks.append([r['line'] for r in rows])
        total += len(rows)
        if not page['has_more']:
            break
        before_seq = page['min_seq']
    else:
        truncated = page.get('has_more', False)
    lines = [line for block in reversed(blocks) for line in block][:_LOG_DOWNLOAD_CAP]
    body = '\n'.join(lines)
    if truncated:
        body += '\n' + t('api.runLogTruncated', n=_LOG_DOWNLOAD_CAP) + '\n'
    # The filename is built from a run id we mint as hex; strip anything not alphanumeric so a
    # crafted path segment can never inject a quote or newline into the response header.
    safe_id = ''.join(c for c in run_id if c.isalnum())[:40] or 'run'
    headers = {'Content-Disposition': f'attachment; filename="run-{safe_id}.log"'}
    return Response(body + '\n', mimetype='text/plain; charset=utf-8', headers=headers)
