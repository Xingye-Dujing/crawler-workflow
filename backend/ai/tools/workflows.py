"""Saved-workflow management, and the export shelf beside it.

Every mutating verb validates BEFORE the write (an unloadable canvas never replaces a working one),
audits one durable line per act, and refuses by name (`workflowNotFound`, `workflowNameTaken`,
`workflowDraftInvalid`). Deletions of a workflow or an exported file are on ``ALWAYS_APPROVAL_TOOLS``:
that switch means "do not ask me about your usual work", not "let a model remove my files".
"""

import logging
import os

from runtime import account_context

from ai.errors import AIError
from ai.types import ToolSpec

logger = logging.getLogger('ai.tools')


def tool_workflow_schema(_args: dict, _ctx: dict) -> dict:
    """The whole legal vocabulary: node types with seed params, the file shape and the rules."""
    from ai import vocabulary

    return vocabulary.workflow_schema()


def tool_workflow_validate(args: dict, _ctx: dict) -> dict:
    from ai import workflow_draft

    payload = args.get('workflow') if isinstance(args.get('workflow'), dict) else args.get('payload')
    if not isinstance(payload, dict):
        raise AIError('ai.toolRefused', kind='bad_request', tool='workflow_validate', reason='workflow is missing')
    return workflow_draft.validate(payload)


def _workflow_manager():
    from runtime.stores import get_workflow_manager

    return get_workflow_manager()


def _audit(action: str, name: str, ctx: dict | None = None) -> None:
    """One durable line per management act.

    The transcript and ``agent_steps`` already carry the call; this log line is what an operator
    reads after the fact, and it names the account because the same checkout can serve several.
    """
    from i18n import t

    logger.info(
        t(
            'ai.auditLog',
            action=action,
            name=name,
            account=account_context.scope_key(),
            conversation=str((ctx or {}).get('conversation_id') or ''),
        )
    )


def _workflow_name(args: dict, tool: str) -> str:
    name = str((args or {}).get('name') or '').strip()
    if not name:
        raise AIError('ai.toolRefused', kind='bad_request', tool=tool, reason='name is missing')
    return name


def tool_workflow_list(_args: dict, _ctx: dict) -> dict:
    rows = _workflow_manager().describe()
    return {'workflows': rows, 'count': len(rows)}


def tool_workflow_read(args: dict, _ctx: dict) -> dict:
    """One saved file in full: the model needs the exact nodes/connections to edit it."""
    name = _workflow_name(args, 'workflow_read')
    manager = _workflow_manager()
    payload = manager.load(name)
    if payload is None:
        raise AIError('ai.workflowNotFound', kind='not_found', name=name)
    nodes = payload.get('nodes') or []
    return {
        'name': manager.clean_name(name),
        'nodes': len(nodes),
        'connections': len(payload.get('connections') or []),
        'workflow': payload,
    }


def tool_workflow_update(args: dict, ctx: dict) -> dict:
    """Overwrite one saved workflow after the engine accepts it.

    Validation runs BEFORE the write, so an unloadable canvas never replaces a working one. The
    approval is the exact-call grant the tool door already requires (``APPROVAL_TOOLS``), because
    "replace this file with this content" is the act the user is allowing.
    """
    from ai import workflow_draft

    name = _workflow_name(args, 'workflow_update')
    payload = args.get('workflow') if isinstance(args.get('workflow'), dict) else None
    if payload is None:
        raise AIError('ai.toolRefused', kind='bad_request', tool='workflow_update', reason='workflow is missing')
    validation = workflow_draft.validate(payload)
    if not validation.get('ok'):
        problems = list(validation.get('structural') or []) + list(validation.get('engine') or [])
        raise AIError('ai.workflowDraftInvalid', kind='bad_request', detail='; '.join(problems)[:800])
    manager = _workflow_manager()
    if not manager.exists(name):
        raise AIError('ai.workflowNotFound', kind='not_found', name=name)
    try:
        path = manager.save(manager.clean_name(name), payload)
    except OSError as exc:
        raise AIError('ai.workflowSaveFailed', kind='error', detail=str(exc)[:200]) from exc
    _audit('workflow_update', name, ctx)
    return {
        'ok': True,
        'name': manager.clean_name(name),
        'path': os.path.basename(path),
        'nodes': len(payload.get('nodes') or []),
    }


def tool_workflow_rename(args: dict, ctx: dict) -> dict:
    old = _workflow_name(args, 'workflow_rename')
    new = str(args.get('new_name') or '').strip()
    if not new:
        raise AIError('ai.toolRefused', kind='bad_request', tool='workflow_rename', reason='new_name is missing')
    manager = _workflow_manager()
    if not manager.exists(old):
        raise AIError('ai.workflowNotFound', kind='not_found', name=old)
    try:
        renamed = manager.rename(old, new)
    except FileExistsError as exc:
        raise AIError('ai.workflowNameTaken', kind='bad_request', name=manager.clean_name(new)) from exc
    if renamed is None:
        raise AIError('ai.workflowNotFound', kind='not_found', name=old)
    _audit('workflow_rename', f'{old} -> {renamed}', ctx)
    return {'ok': True, 'previous': old, 'name': renamed}


def tool_workflow_delete(args: dict, ctx: dict) -> dict:
    """Delete one saved workflow. Approval is mandatory even with auto-approve on."""
    name = _workflow_name(args, 'workflow_delete')
    manager = _workflow_manager()
    if not manager.exists(name):
        raise AIError('ai.workflowNotFound', kind='not_found', name=name)
    manager.delete(name)
    _audit('workflow_delete', name, ctx)
    return {'ok': True, 'deleted': manager.clean_name(name)}


def tool_workflow_export(args: dict, ctx: dict) -> dict:
    """Write a project bundle (workflow + its datasets/templates) into this account's exports."""
    from runtime import paths

    from services.exports.writer import save_bytes
    from services.workflows.bundle import build_bundle

    name = _workflow_name(args, 'workflow_export')
    manager = _workflow_manager()
    if not manager.exists(name):
        raise AIError('ai.workflowNotFound', kind='not_found', name=name)
    try:
        payload, filename, warnings = build_bundle([name], workflow_manager=manager)
        saved = save_bytes(paths.active().export_dir, filename, payload)
    except AIError:
        raise
    except Exception as exc:
        raise AIError('ai.exportSaveFailed', kind='error', detail=str(exc)[:300]) from exc
    _audit('workflow_export', f'{name} -> {saved["name"]}', ctx)
    return {
        'ok': True,
        'workflow': manager.clean_name(name),
        'export': saved['name'],
        'bytes': saved['size'],
        'warnings': warnings,
    }


def tool_workflow_run(args: dict, ctx: dict) -> dict:
    """Start a SAVED workflow through the schedule's own start path (one begin_run, one slot)."""
    from engine.run_schedule import start_scheduled_run
    from i18n import get_lang

    name = _workflow_name(args, 'workflow_run')
    manager = _workflow_manager()
    if not manager.exists(name):
        raise AIError('ai.workflowNotFound', kind='not_found', name=name)
    answer = start_scheduled_run({'workflow': name, 'name': name, 'lang': get_lang()}, manual=True)
    if not answer.get('ok'):
        raise AIError('ai.workflowRunFailed', kind='error', name=name, detail=str(answer.get('error') or '')[:300])
    _audit('workflow_run', name, ctx)
    return {
        'ok': True,
        'workflow': manager.clean_name(name),
        'run_id': answer.get('run_id') or '',
        'queued': bool(answer.get('queued')),
    }


def tool_workflow_stop(_args: dict, ctx: dict) -> dict:
    """Stop the account's live run through the same function the 停止 button uses."""
    from engine import run as run_engine

    answer = run_engine.stop_run()
    body = answer.get('body') or {}
    if not body.get('ok'):
        raise AIError('ai.workflowStopFailed', kind='bad_request', detail=str(body.get('error') or '')[:300])
    _audit('workflow_stop', 'current run', ctx)
    return body


def tool_export_list(_args: dict, _ctx: dict) -> dict:
    from runtime import paths

    from services.exports.browser import list_exports

    rows = list_exports(paths.active().export_dir, limit=50)
    return {'exports': rows, 'count': len(rows)}


def tool_export_delete(args: dict, ctx: dict) -> dict:
    """Delete one exported file. Approval is mandatory even with auto-approve on."""
    from runtime import paths

    from services.exports.browser import delete_export_file

    name = str(args.get('name') or '').strip()
    if not name:
        raise AIError('ai.toolRefused', kind='bad_request', tool='export_delete', reason='name is missing')
    if not delete_export_file(paths.active().export_dir, name):
        raise AIError('ai.exportNotFound', kind='not_found', name=name)
    _audit('export_delete', name, ctx)
    return {'ok': True, 'deleted': name}


TOOLS = (
    ToolSpec(
        'workflow_schema',
        'Read the complete legal vocabulary: every node type with its seed parameters, the workflow '
        'file shape and the rules. Call this before writing a workflow draft.',
        {'type': 'object', 'properties': {}},
        handler=tool_workflow_schema,
        permission='read:project',
    ),
    ToolSpec(
        'workflow_validate',
        'Check a workflow draft before presenting it: node types, params shape, wires and the '
        'engine’s own run-time validation. Returns every problem by name.',
        {
            'type': 'object',
            'properties': {'workflow': {'type': 'object'}},
            'required': ['workflow'],
        },
        handler=tool_workflow_validate,
        permission='read:project',
    ),
    ToolSpec(
        'workflow_list',
        'List this account’s saved workflows with node counts, labels, size and a broken flag.',
        {'type': 'object', 'properties': {}},
        handler=tool_workflow_list,
        permission='read:project',
    ),
    ToolSpec(
        'workflow_read',
        'Read one saved workflow file in full (nodes, connections, settings) before editing it.',
        {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        handler=tool_workflow_read,
        permission='read:project',
    ),
    ToolSpec(
        'workflow_update',
        'Replace a saved workflow with a validated draft under the SAME name. Refused if the name '
        'does not exist or the draft is not loadable; asks for approval when auto-approve is off.',
        {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'workflow': {'type': 'object'},
                'summary': {'type': 'string'},
            },
            'required': ['name', 'workflow'],
        },
        handler=tool_workflow_update,
        permission='write:project',
    ),
    ToolSpec(
        'workflow_rename',
        'Rename a saved workflow. A name that already exists is refused, never overwritten.',
        {
            'type': 'object',
            'properties': {'name': {'type': 'string'}, 'new_name': {'type': 'string'}},
            'required': ['name', 'new_name'],
        },
        handler=tool_workflow_rename,
        permission='write:project',
    ),
    ToolSpec(
        'workflow_delete',
        'Delete one saved workflow. ALWAYS asks the user for an approval grant, even with '
        'auto-approve on; the deletion is logged.',
        {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        handler=tool_workflow_delete,
        permission='write:project',
    ),
    ToolSpec(
        'workflow_export',
        'Write a project bundle (the workflow plus the datasets and reusable templates it reads) '
        'into this account’s export directory; returns the downloadable file name.',
        {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        handler=tool_workflow_export,
        permission='write:project',
    ),
    ToolSpec(
        'workflow_run',
        'Start a SAVED workflow through the same start path as a scheduled run. Queues when the '
        'server is busy instead of refusing; returns the run id.',
        {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        handler=tool_workflow_run,
        permission='write:project',
    ),
    ToolSpec(
        'workflow_stop',
        'Stop the account’s live run (or the queued one it is waiting behind). Safe to call when '
        'nothing is running; returns idle=true then. Everything already produced is kept.',
        {'type': 'object', 'properties': {}},
        handler=tool_workflow_stop,
        permission='write:project',
    ),
    ToolSpec(
        'export_list',
        'List the account’s exported files (name, size, modified time).',
        {'type': 'object', 'properties': {}},
        handler=tool_export_list,
        permission='read:project',
    ),
    ToolSpec(
        'export_delete',
        'Delete one exported file by name. ALWAYS asks the user for an approval grant, even with '
        'auto-approve on; the deletion is logged.',
        {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']},
        handler=tool_export_delete,
        permission='write:project',
    ),
)
