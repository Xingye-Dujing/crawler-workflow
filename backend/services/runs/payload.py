"""The two guards every run-start payload passes, whether it runs now or waits in the queue.

Both are asked **before** the single run slot is claimed, because a payload that cannot become a
run must be refused to the browser that sent it (where someone can fix it) rather than fail
minutes later in an unwatched thread — and the queued path takes the same two answers, so a
request cannot be legal on the live path and broken on the queue path.
"""

from stores import get_run_store

from i18n import t


def workflow_shape_error(data: dict) -> str:
    """Why this payload cannot become a run, or '' when it can.

    Checked before the slot is claimed, in both the live and the queued path:
    ``WorkflowEngine`` walks ``nodes`` expecting dicts, so a list of strings or a
    ``settings`` that is a number raises AttributeError deep inside the worker —
    which the browser then reads as an HTML error page, and a queued one would
    fail minutes later in a thread nobody is watching.
    """
    workflow = data.get('workflow')
    if workflow is None or workflow == {}:
        return ''  # an empty payload is refused by validate(), with a real message
    if not isinstance(workflow, dict):
        return t('api.workflowShapeInvalid')
    nodes = workflow.get('nodes')
    if nodes is not None and (not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes)):
        return t('api.workflowShapeInvalid')
    # A node's ``params`` is walked by ``.get`` all through the engine and the executor; a
    # truthy non-dict (``params: 'x'``) raised AttributeError inside ``begin_run`` before the
    # slot, and the queued path had no handler for it — an HTML 500, exactly what this guard
    # exists to prevent. Same for ``connections``: ``all_connections`` does not filter, so a
    # list of STRINGS reached ``dangling_connections``' ``c.get`` and threw mid-run.
    for node in nodes if isinstance(nodes, list) else []:
        # A node's ``id`` is a storage key — the engine keys ``WorkflowEngine.nodes`` on ``n['id']``,
        # so a node without one crashed the run thread with a raw KeyError before any record existed
        # (and minutes later in an unwatched queued thread). Refuse it BY NAME here, at the payload
        # boundary, so the user is told a canvas node has no id rather than watching an HTML 500.
        if not isinstance(node.get('id'), str) or not node.get('id').strip():
            return t('api.workflowNodeNoId')
        params = node.get('params')
        if params is not None and not isinstance(params, dict):
            return t('api.workflowShapeInvalid')
    connections = workflow.get('connections')
    if connections is not None and (
        not isinstance(connections, list) or any(not isinstance(conn, dict) for conn in connections)
    ):
        return t('api.workflowShapeInvalid')
    settings = workflow.get('settings')
    if settings is not None and not isinstance(settings, dict):
        return t('api.workflowShapeInvalid')
    return ''


def resume_refusal(data: dict) -> str:
    """Why a 继续 request cannot continue, or '' when it can.

    The run id a resume asks for is the whole point of the feature: it names the
    rows and cursors already paid for. When retention (or the records panel) has
    deleted that run in the meantime, reusing its id starts an *empty* run under
    the same name — which looks exactly like a continue that found nothing, while
    quietly re-crawling and re-paying for every item. So the request is refused
    with the id in the message, and the banner can say so.
    """
    resume_run_id = str(data.get('resume_run_id') or '').strip()
    if not resume_run_id:
        return ''
    try:
        if get_run_store().get_run(resume_run_id):
            return ''
    except Exception:
        # A store that cannot answer is not evidence that the run is gone; the
        # run itself reports the real failure the moment it opens the database.
        return ''
    return t('api.resumeMissing', rid=resume_run_id)
