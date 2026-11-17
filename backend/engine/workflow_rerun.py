"""Re-run one node and its downstream, as a resume of the run that produced them.

This is the body of ``POST /api/workflow/rerun-node``, moved out so a second caller (the AI
workspace's ``rerun_node`` tool and ``POST /api/ai/rerun``) runs the SAME decision: resolve the
run, prove the canvas still matches it, refuse a live run and a node with no stored rows, then
hand the request to the ONE start path (``engine.run.begin_run``, as a resume carrying the subtree
to erase). The route stays a thin caller so the two doors cannot drift apart.

A refusal is raised as :class:`RerunRefusalError` with the i18n key and status the HTTP route already
answered, so the message is byte-identical whichever door asked.
"""

from nodes.labels import node_label
from runtime.state import execution_state
from runtime.stores import get_run_store

from engine import run as run_engine
from engine.plan import downstream_closure
from engine.workflow import effective_workflow
from i18n import t
from services.runs.store import (
    NODE_DONE,
    NODE_RESTORED,
    RUN_RUNNING,
    RUN_STOPPING,
    workflow_fingerprint,
)


class RerunRefusalError(Exception):
    """A rerun this run, canvas or node cannot answer; ``status`` is the HTTP status it used."""

    def __init__(self, key: str, status: int, **params):
        self.key = key
        self.status = status
        self.params = params
        super().__init__(self.localized())

    def localized(self) -> str:
        return t(self.key, **self.params) if self.params else t(self.key)


def rerun_node(
    workflow: dict,
    node_id: str,
    run_id: str = '',
    *,
    workflow_name: str = '',
    lang: str = '',
    llm: dict | None = None,
) -> dict:
    """Wipe the target subtree and resume ``run_id``; answers ``{'status', 'body'}``.

    ``run_id`` blank means "the newest resumable run of this canvas" (the records panel always
    names one; a hand-built call may not). Every refusal happens before anything is touched.
    """
    node_id = str(node_id or '').strip()
    if not node_id:
        raise RerunRefusalError('api.paramInvalid', 400, name='node_id')
    if not isinstance(workflow, dict) or not workflow.get('nodes'):
        raise RerunRefusalError('api.workflowShapeInvalid', 400)

    effective = effective_workflow(workflow)
    fingerprint = workflow_fingerprint(effective)
    store = get_run_store()

    run_id = str(run_id or '').strip()
    if run_id:
        run = store.get_run(run_id)
        if run is None:
            raise RerunRefusalError('api.resumeMissing', 400, rid=run_id)
        if run.get('workflow_fingerprint') != fingerprint:
            # Reusing this run would mix two different workflows' rows under one id; refuse by name.
            raise RerunRefusalError('api.rerunFingerprintMismatch', 409)
    else:
        candidates = store.list_resumable(fingerprint, limit=1, include_finished=True)
        if not candidates:
            raise RerunRefusalError('api.rerunNoRun', 404)
        run_id = candidates[0]['run_id']

    # A run that is still executing is not a rerun target: erasing its subtree would pull the rows
    # out from under a thread that is still writing them, and the 继续 it leaves behind re-crawls and
    # re-pays work that had already landed. Refuse by name, keeping the rows.
    target_run = store.get_run(run_id)
    if target_run is None:
        raise RerunRefusalError('api.rerunNoRun', 404)
    if target_run.get('status') in (RUN_RUNNING, RUN_STOPPING):
        raise RerunRefusalError('api.rerunRunLive', 409)

    target = next((n for n in effective['nodes'] if n.get('id') == node_id), None)
    if target is None:
        raise RerunRefusalError('api.rerunNoNode', 400, node=node_id)
    status = store.get_node_status(run_id, node_id)
    if status not in (NODE_DONE, NODE_RESTORED):
        # The node must have a row to delete. Naming it through the same label the console uses
        # keeps "该节点没有可重跑的结果" attributable to one box on a canvas of many.
        raise RerunRefusalError('api.rerunNoRows', 409, node=node_label(target, node_id))
    # A rerun is never parked, so a slot that is busy now refuses this press rather than queueing a
    # wipe for later: by the time a queued rerun drained, the canvas the user pressed on has moved
    # on and the rows it deletes belong to a decision nobody is watching. (The claim itself is what
    # protects the data — the erase now happens inside the worker, never here.)
    live_thread = execution_state.get('thread')
    if execution_state.get('running') or (live_thread is not None and live_thread.is_alive()):
        raise RerunRefusalError('api.rerunBusy', 409)

    invalidated = downstream_closure(effective, node_id)

    # Replay through the ordinary start path as a resume of that very run.
    # Never park it: a queued rerun would wipe its subtree at drain time, minutes later, when the
    # canvas the user is looking at has moved on — so a busy server refuses this press by name.
    # The erase itself is NOT done here: it travels in the payload and the worker performs it once
    # the slot is genuinely ours (see :func:`engine.run._rerun_request`).
    payload = {
        'workflow': workflow,
        'node_id': node_id,
        'workflow_name': str(workflow_name or workflow.get('name') or ''),
        'resume_run_id': run_id,
        'rerun_invalidate': {'run_id': run_id, 'node_ids': list(invalidated)},
        'queue': False,
    }
    if isinstance(llm, dict) and llm:
        payload['llm'] = llm
    answer = run_engine.begin_run(payload, lang)
    body = dict(answer['body'])
    body['rerun_from'] = node_id
    body['invalidated'] = invalidated
    return {'status': answer['status'], 'body': body}
