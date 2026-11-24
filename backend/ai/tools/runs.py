"""Run tools: read a run, read its console, confirm an edited result, rerun the failed subtree.

The rerun is the one mutating verb here and it has its own rules: it re-reads the SAVED workflow file,
refuses by name when the canvas changed or the run is live, and hands the engine's own refusal to the
user in the workspace's words (the model's next step differs: "the canvas changed" is not "the run
record is missing").
"""

import os

from core.config import Config

from ai.errors import AIError
from ai.tools.shared import _int_arg
from ai.types import ToolSpec


def tool_list_runs(_args: dict, _ctx: dict) -> dict:
    from runtime.stores import get_run_store

    return {'runs': get_run_store().run_ledger()[:30]}


def tool_run_status(args: dict, _ctx: dict) -> dict:
    run_id = str(args.get('run_id') or _ctx.get('run_id') or '')
    if not run_id:
        raise AIError('ai.toolRefused', kind='bad_request', tool='run_status', reason='run_id is missing')
    from runtime.stores import get_run_store

    run_store = get_run_store()
    run = run_store.get_run(run_id)
    if not run:
        raise AIError('ai.toolRefused', kind='bad_request', tool='run_status', reason=f'no run {run_id}')
    return {'run': run, 'nodes': run_store.node_statuses(run_id)}


def tool_run_console(args: dict, _ctx: dict) -> dict:
    run_id = str(args.get('run_id') or _ctx.get('run_id') or '')
    if not run_id:
        raise AIError('ai.toolRefused', kind='bad_request', tool='run_console', reason='run_id is missing')
    from runtime.stores import get_run_store

    limit = _int_arg(args.get('limit'), 80, 1, 200)
    page = get_run_store().read_log(run_id, limit=limit)
    return {'rows': page.get('rows', []), 'has_more': bool(page.get('has_more'))}


def tool_apply_node_result(args: dict, _ctx: dict) -> dict:
    """Generic confirm step for a node-created conversation: save the edit, then rerun downstream."""
    from services.coding import node_results

    run_id = str(args.get('run_id') or '').strip()
    node_id = str(args.get('node_id') or '').strip()
    result = args.get('result')
    if not run_id or not node_id or not isinstance(result, (dict, list)):
        raise AIError(
            'ai.toolRefused',
            kind='bad_request',
            tool='apply_node_result',
            reason='run_id, node_id and a result object or array are required',
        )
    try:
        saved = node_results.save(run_id, node_id, result)
    except ValueError as exc:
        raise AIError('ai.toolRefused', kind='bad_request', tool='apply_node_result', reason=str(exc)) from exc
    return {
        'ok': True,
        'saved': saved,
        'next': 'Call rerun_node on this run and node to replay it and everything downstream.',
    }


def tool_apply_codebook(args: dict, _ctx: dict) -> dict:
    """Save the codebook the user just edited in the trace conversation, as a new version."""
    from services.coding import codebooks

    payload = args.get('codebook')
    if not isinstance(payload, dict):
        raise AIError('ai.toolRefused', kind='bad_request', tool='apply_codebook', reason='codebook is missing')
    try:
        saved = codebooks.save_codebook(payload, codebook_id=str(payload.get('id') or ''))
    except codebooks.CodebookError as exc:
        raise AIError('ai.toolRefused', kind='bad_request', tool='apply_codebook', reason=str(exc)) from exc
    return {
        'ok': True,
        'codebook': saved,
        'next': 'Call rerun_node on the coding node to replay it and everything downstream with this version.',
    }


#: A rerun refusal names the ENGINE's i18n key; the workspace answers its own sentence, because the
#: model's next step differs: "the canvas changed" is not "the run record is missing".
RERUN_REFUSAL_KEYS = {
    'api.rerunFingerprintMismatch': 'ai.rerunCanvasChanged',
    'api.rerunNoNode': 'ai.rerunNoNode',
    'api.rerunNoRun': 'ai.rerunNoRun',
    'api.resumeMissing': 'ai.rerunNoRun',
    'api.rerunRunLive': 'ai.rerunRunLive',
    'api.rerunBusy': 'ai.rerunRunLive',
    'api.rerunNoRows': 'ai.rerunNoRows',
}


def rerun_refusal_message(exc) -> str:
    """The sentence both the agent and the HTTP route tell the user for a refused rerun."""
    from i18n import t

    key = RERUN_REFUSAL_KEYS.get(getattr(exc, 'key', ''))
    return t(key, **exc.params) if key and exc.params else t(key) if key else exc.localized()


def tool_rerun_node(args: dict, _ctx: dict) -> dict:
    """Re-run one failed subtree from the SAVED file; the canvas is never loaded or replaced."""
    from runtime.stores import get_workflow_manager

    from engine.workflow_rerun import RerunRefusalError, rerun_node
    from i18n import get_lang

    run_id = str(args.get('run_id') or '').strip()
    workflow_name = str(args.get('workflow_name') or '').strip()
    node_id = str(args.get('node_id') or '').strip()
    if not (run_id and node_id and workflow_name):
        raise AIError('ai.rerunArgs', kind='bad_request')
    try:
        workflow = get_workflow_manager().load(workflow_name)
    except OSError:
        workflow = None
    if not workflow:
        raise AIError('ai.rerunNoWorkflow', kind='not_found', name=workflow_name)
    try:
        answer = rerun_node(workflow, node_id, run_id, workflow_name=workflow_name, lang=get_lang())
    except RerunRefusalError as exc:
        raise AIError(rerun_refusal_message(exc), kind='bad_request') from exc
    body = answer.get('body') or {}
    if not body.get('ok'):
        raise AIError('ai.rerunNoRun', kind='bad_request')
    return {
        'ok': True,
        'run_id': run_id,
        'node_id': node_id,
        'queued': bool(body.get('queued')),
        'invalidated': list(body.get('invalidated') or []),
    }


def tool_app_errors(args: dict, _ctx: dict) -> dict:
    """The last thing the app said: backend log tail, failed runs and their console lines.

    This is the feedback half of the harness. A run that fails leaves a per-node error and console
    lines in ``runs.db``; a backend bug leaves a traceback in ``logs/app.log``. Both are read here,
    bounded, so the assistant can fix its own proposal without the user copying a stack trace.
    """

    limit = _int_arg(args.get('lines'), 80, 10, 300)
    report: dict = {'log_tail': [], 'runs': [], 'log_path': ''}
    try:
        log_path = os.path.join(Config.LOG_DIR, 'app.log')
        report['log_path'] = log_path
        if os.path.isfile(log_path):
            with open(log_path, encoding='utf-8', errors='replace') as handle:
                rows = handle.readlines()[-limit * 3 :]
            report['log_tail'] = [line.rstrip()[-400:] for line in rows if line.strip()][-limit:]
    except OSError as exc:
        report['log_error'] = str(exc)[:200]
    try:
        from runtime.stores import get_run_store

        run_store = get_run_store()
        rows = run_store.run_ledger()[:12]
        for run in rows:
            status = str(run.get('status') or '')
            if status not in ('failed', 'partial', 'stopped', 'error', 'cancelled'):
                continue
            entry = {
                'run_id': run.get('id'),
                'workflow': run.get('workflow_name') or '',
                'status': status,
                'finished_at': run.get('finished_at') or '',
                'nodes': [],
                'console': [],
            }
            try:
                statuses = run_store.node_statuses(str(run.get('id') or ''))
                entry['nodes'] = [
                    {'node': node_id, 'status': node.get('status'), 'error': str(node.get('error') or '')[:300]}
                    for node_id, node in statuses.items()
                    if str(node.get('status') or '') in ('failed', 'partial') or node.get('error')
                ][:12]
                entry['console'] = [
                    str(row.get('line') or '')[:300]
                    for row in (run_store.read_log(str(run.get('id')), limit=20).get('rows') or [])
                ]
            except Exception as exc:  # a run without a console is still a failed run
                entry['console'] = [f'（无法读取控制台：{str(exc)[:120]}）']
            report['runs'].append(entry)
            if len(report['runs']) >= 4:
                break
    except Exception as exc:
        report['runs_error'] = str(exc)[:200]
    return report


RERUN_SCHEMA = {
    'type': 'object',
    'properties': {
        'run_id': {'type': 'string', 'description': 'The failed run whose subtree should run again.'},
        'workflow_name': {
            'type': 'string',
            'description': 'The SAVED workflow file that produced the run. Never load it onto the canvas; the file '
            'must still match the run record.',
        },
        'node_id': {'type': 'string', 'description': 'The failed node; its downstream runs again too.'},
    },
    'required': ['run_id', 'workflow_name', 'node_id'],
}


TOOLS = (
    ToolSpec(
        'list_runs',
        'List the most recent runs in this account with their status and row counts. Use it to find a '
        'run id; for what happened inside one run, read run_status or app_errors instead.',
        {'type': 'object', 'properties': {}},
        handler=tool_list_runs,
    ),
    ToolSpec(
        'run_status',
        'Read one run and its per-node status; use this before diagnosing a failure.',
        {'type': 'object', 'properties': {'run_id': {'type': 'string'}}},
        handler=tool_run_status,
    ),
    ToolSpec(
        'run_console',
        'Read the tail of a run’s durable console.',
        {'type': 'object', 'properties': {'run_id': {'type': 'string'}, 'limit': {'type': 'integer'}}},
        handler=tool_run_console,
    ),
    ToolSpec(
        'apply_node_result',
        'Confirm an edited result from a node-created AI conversation and make it available to '
        'rerun_node. Use only after the user agrees to the edited content.',
        {
            'type': 'object',
            'properties': {
                'run_id': {'type': 'string'},
                'node_id': {'type': 'string'},
                'result': {'oneOf': [{'type': 'object'}, {'type': 'array'}]},
            },
            'required': ['run_id', 'node_id', 'result'],
        },
        handler=tool_apply_node_result,
        permission='write:project',
    ),
    ToolSpec(
        'apply_codebook',
        'Save an edited qualitative codebook as a new version, then rerun the coding node from the run.',
        {'type': 'object', 'properties': {'codebook': {'type': 'object'}}, 'required': ['codebook']},
        handler=tool_apply_codebook,
        permission='write:project',
    ),
    ToolSpec(
        'app_errors',
        'Read the app’s own feedback: the backend log tail and the most recent failed/partial runs '
        'with their node errors and console lines. Use it before diagnosing or re-proposing.',
        {'type': 'object', 'properties': {'lines': {'type': 'integer'}}},
        handler=tool_app_errors,
        permission='read:project',
    ),
    ToolSpec(
        'rerun_node',
        'Re-run ONE failed node and everything downstream of it, as a resume of the run that produced it. '
        'It does NOT load or replace the canvas: the SAVED workflow file is read, must still match the run '
        'record, and the kept upstream rows are reused. Refuses by name when the file is missing, the canvas '
        'changed, the node is unknown or the run is live.',
        RERUN_SCHEMA,
        permission='write:project',
        handler=tool_rerun_node,
    ),
)
