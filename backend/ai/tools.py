"""The verbs the agent may call.

Most tools only read: a dataset, a run, the capability matrix or the docs, and return a bounded
JSON/text result. Writes to application state are **artifacts**: a proposal the user applies
through the app's normal route. That boundary is why an AI mistake cannot delete a run or rewrite
a canvas.

Two groups are the deliberate exception, both off by default and both refused on a cloud host:
``read:code`` (the repository source) needs ``ai_allow_code_context``, and ``read:python`` /
``write:python`` / ``exec:python`` (the account's script workspace) need ``ai_allow_python``.
The permission is checked HERE, at execution time, not only where the turn's schema list is
built — a replayed history can name a tool the current turn does not offer.

``ask_user_question``, ``update_plan`` and ``present_artifact`` are control tools: the runtime
intercepts them and never looks for a handler here.
"""

import re

from core.config import Config
from runtime import account_context
from runtime.settings import get_setting

from ai import scopes
from ai.context import docs_search, project_facts
from ai.errors import AIError
from ai.types import ToolSpec


def _int_arg(value, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    """A model-supplied number as a bounded int; a malformed value takes the default.

    The schema says ``integer``, but a model can still send ``"5 rows"``. Raising ValueError
    escaped the tool event (only ``AIError`` is caught) and left a ``tool_use`` with no result,
    which made every later turn fail the provider's tool-pair validation.
    """
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        # A number with a word after it ("5 rows", "10 行") is what a model actually writes; its
        # leading integer is the value it meant, and refusing it would spend a round for nothing.
        match = re.match(r'\s*([+-]?\d+)', str(value or ''))
        number = int(match.group(1)) if match else int(default)
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def _dataset_frame(dataset_id: str):
    if not dataset_id:
        raise AIError('ai.toolRefused', kind='bad_request', tool='dataset', reason='dataset_id is missing')
    try:
        from runtime.stores import get_dataset_store

        frame = get_dataset_store().get(dataset_id)
    except Exception as exc:  # a store that cannot open is a named refusal, not an empty table
        raise AIError('ai.toolRefused', kind='error', tool='dataset', reason=str(exc)[:200]) from exc
    if frame is None:
        raise AIError('ai.toolRefused', kind='bad_request', tool='dataset', reason=f'no dataset {dataset_id}')
    return frame


def tool_project_facts(_args: dict, _ctx: dict) -> dict:
    return {'facts': project_facts()}


def tool_capabilities(args: dict, _ctx: dict) -> dict:
    import capabilities.registry as capabilities

    payload = capabilities.as_dict()
    platform = str(args.get('platform') or '').strip()
    if platform:
        rows = [row for row in payload.get('platforms', []) if row.get('platform') == platform]
        return {'platforms': rows}
    return {'platforms': payload.get('platforms', []), 'machine': payload.get('machine', {})}


def tool_docs_search(args: dict, _ctx: dict) -> dict:
    query = str(args.get('query') or '').strip()
    return {'results': docs_search(query, limit=5)}


def tool_list_datasets(_args: dict, _ctx: dict) -> dict:
    from runtime.stores import get_dataset_store

    return {'datasets': get_dataset_store().list_datasets(limit=30)}


def tool_dataset_profile(args: dict, _ctx: dict) -> dict:
    frame = _dataset_frame(str(args.get('dataset_id') or _ctx.get('dataset_id') or ''))
    columns = []
    for column in frame.columns:
        series = frame[column]
        columns.append(
            {
                'name': str(column),
                'dtype': str(series.dtype),
                'missing': int(series.isna().sum()),
                'unique': int(series.nunique(dropna=True)),
                'sample': [str(value)[:120] for value in series.dropna().head(2).tolist()],
            }
        )
    return {
        'dataset_id': str(args.get('dataset_id') or _ctx.get('dataset_id') or ''),
        'rows': len(frame),
        'columns': columns,
        'truncated': len(frame.columns) > 80,
        'next': 'Use dataset_peek for a few full rows; page only when the answer needs them.',
    }


def _project_columns(frame, raw) -> list:
    names = []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(',') if part.strip()]
    for item in raw or ():
        name = str(item or '').strip()
        if name and name in frame.columns and name not in names:
            names.append(name)
    return names


def _bounded_cell(value, width: int) -> object:
    if value is None or not isinstance(value, str):
        return value
    return value[:width] + ('…' if len(value) > width else '')


def tool_dataset_peek(args: dict, _ctx: dict) -> dict:
    """Names, dtypes and a handful of rows — the cheapest answer to most questions.

    The default is five rows and a 120-character cell because crawling tables carry whole posts;
    sending them to a model is the expensive part of this workspace. A caller that truly needs
    more asks for ``dataset_page`` (bounded) or runs a Python script, and the answer says which.
    """
    frame = _dataset_frame(str(args.get('dataset_id') or _ctx.get('dataset_id') or ''))
    limit = _int_arg(args.get('rows'), 5, 1, 20)
    width = _int_arg(args.get('width'), 120, 40, 400)
    wanted = _project_columns(frame, args.get('columns')) or [str(column) for column in frame.columns[:40]]
    head = frame.head(limit)
    rows = [{name: _bounded_cell(row.get(name), width) for name in wanted} for row in head.to_dict('records')]
    return {
        'dataset_id': str(args.get('dataset_id') or _ctx.get('dataset_id') or ''),
        'total_rows': len(frame),
        'shown_rows': len(rows),
        'columns': [{'name': str(column), 'dtype': str(frame[column].dtype)} for column in wanted],
        'rows': rows,
        'omitted_columns': max(0, len(frame.columns) - len(wanted)),
        'next': 'If this is enough, stop. Otherwise ask for specific columns or dataset_page(offset=…).',
    }


def tool_dataset_page(args: dict, _ctx: dict) -> dict:
    frame = _dataset_frame(str(args.get('dataset_id') or _ctx.get('dataset_id') or ''))
    offset = _int_arg(args.get('offset'), 0, 0)
    limit = _int_arg(args.get('limit'), 20, 1, 50)
    width = _int_arg(args.get('width'), 200, 40, 400)
    wanted = _project_columns(frame, args.get('columns')) or [str(column) for column in frame.columns[:40]]
    page = frame.iloc[offset : offset + limit]
    rows = [{name: _bounded_cell(row.get(name), width) for name in wanted} for row in page.to_dict('records')]
    return {
        'dataset_id': str(args.get('dataset_id') or _ctx.get('dataset_id') or ''),
        'offset': offset,
        'limit': limit,
        'total_rows': len(frame),
        'rows': rows,
        'has_more': offset + len(rows) < len(frame),
        'next_offset': offset + len(rows),
    }


def tool_dataset_sample(args: dict, _ctx: dict) -> dict:
    """A bounded page with capped cells.

    It used to read ``frame.head(limit)`` and return whole posts, ignoring the schema's
    ``columns``/``offset`` — a third unbounded read path beside peek and page.
    """
    frame = _dataset_frame(str(args.get('dataset_id') or _ctx.get('dataset_id') or ''))
    offset = _int_arg(args.get('offset'), 0, 0)
    limit = _int_arg(args.get('limit'), 10, 1, 50)
    width = _int_arg(args.get('width'), 200, 40, 400)
    wanted = _project_columns(frame, args.get('columns')) or [str(column) for column in frame.columns[:40]]
    page = frame.iloc[offset : offset + limit]
    rows = [{name: _bounded_cell(row.get(name), width) for name in wanted} for row in page.to_dict('records')]
    return {
        'rows': rows,
        'columns': wanted,
        'offset': offset,
        'total': len(frame),
        'has_more': offset + len(rows) < len(frame),
    }


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


def tool_chart_catalog(_args: dict, _ctx: dict) -> dict:
    from ai import vocabulary
    from services.charts.registry import SPECS

    return {
        'charts': [
            {
                'key': spec.key,
                'family': spec.family,
                'reads': list(spec.reads),
                'echarts_only': spec.echarts_only,
                'latex_buildable': spec.latex_buildable,
            }
            for spec in SPECS
        ],
        'contracts': vocabulary.chart_catalog(),
    }


def tool_analysis_catalog(_args: dict, _ctx: dict) -> dict:
    from ai import vocabulary
    from services.analysis.ops import OPS

    return {'ops': sorted(OPS), 'count': len(OPS), 'contracts': vocabulary.analysis_catalog()}


def tool_list_runs(_args: dict, _ctx: dict) -> dict:
    from runtime.stores import get_run_store

    return {'runs': get_run_store().run_ledger()[:30]}


def tool_code_search(args: dict, _ctx: dict) -> dict:
    """A bounded read-only source search; local/desktop snapshot only, never cloud."""
    from ai import environment

    root_text = environment.code_root()
    if not root_text:
        raise AIError('ai.codeCloudRefused', kind='capability')
    query = str(args.get('query') or '').strip()
    if not query:
        raise AIError('ai.toolRefused', kind='bad_request', tool='code_search', reason='query is missing')
    from pathlib import Path

    root = Path(root_text)
    search_root = root / 'backend' if (root / 'backend').is_dir() else root
    hits = []
    for path in list(search_root.rglob('*.py'))[:2000] + list((search_root / 'static' / 'js').rglob('*.js'))[:2000]:
        if 'node_modules' in path.parts or 'vendor' in path.parts or '__pycache__' in path.parts:
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if query not in text:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if query in line:
                hits.append(
                    {
                        'path': str(path.relative_to(search_root)).replace('\\', '/'),
                        'line': line_number,
                        'text': line.strip()[:240],
                    }
                )
                if len(hits) >= 20:
                    return {'hits': hits, 'truncated': True}
    return {'hits': hits, 'truncated': False}


def tool_code_read(args: dict, _ctx: dict) -> dict:
    """One source file (bounded), for a citation or a patch proposal."""
    from ai import environment

    root_text = environment.code_root()
    if not root_text:
        raise AIError('ai.codeCloudRefused', kind='capability')
    from pathlib import Path

    root = Path(root_text)
    relative = str(args.get('path') or '').strip().replace('\\', '/')
    if not relative or '..' in relative.split('/') or relative.startswith('/'):
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool='code_read', reason='path must stay inside the source tree'
        )
    base = root / 'backend' if (root / 'backend').is_dir() else root
    target = (base / relative).resolve()
    if not str(target).startswith(str(base.resolve())) or not target.is_file():
        raise AIError('ai.toolRefused', kind='not_found', tool='code_read', reason=f'no source file {relative}')
    limit = _int_arg(args.get('lines'), 200, 1, 400)
    lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
    return {
        'path': str(target.relative_to(base)).replace('\\', '/'),
        'lines': len(lines),
        'start': 1,
        'content': '\n'.join(lines[:limit]),
        'truncated': len(lines) > limit,
    }


def tool_web_search(args: dict, ctx: dict) -> dict:
    """The standalone DeepSeek Search API, available to the research skill."""
    if str(ctx.get('provider') or '') != 'deepseek':
        raise AIError(
            'ai.capabilityRefused',
            kind='capability',
            provider=ctx.get('provider') or '',
            model=ctx.get('model') or '',
            capability='web_search',
        )
    from ai import files

    return files.search(
        str(ctx.get('api_key') or ''),
        str(args.get('query') or ''),
        count=_int_arg(args.get('count'), 10, 1, 20),
        need_content=bool(args.get('need_content')),
        ori_question=str(args.get('ori_question') or ''),
    )


def tool_web_fetch(args: dict, ctx: dict) -> dict:
    """The standalone DeepSeek Fetch API, available to the research skill."""
    if str(ctx.get('provider') or '') != 'deepseek':
        raise AIError(
            'ai.capabilityRefused',
            kind='capability',
            provider=ctx.get('provider') or '',
            model=ctx.get('model') or '',
            capability='read_url',
        )
    from ai import files

    return files.fetch(str(ctx.get('api_key') or ''), str(args.get('url') or ''))


def _python_ready() -> None:
    if Config.CLOUD_MODE:
        raise AIError('ai.pythonCloud', kind='capability')
    if not get_setting('ai_allow_python'):
        raise AIError('ai.pythonDisabled', kind='capability')


def tool_python_scripts(_args: dict, _ctx: dict) -> dict:
    from services import python_scripts

    return {
        'scripts': [
            {
                'id': item['id'],
                'name': item['name'],
                'description': item['description'],
                'builtin': item['builtin'],
                'version': item['version'],
                'tags': item.get('tags') or [],
            }
            for item in python_scripts.all_scripts()
        ]
    }


def tool_python_script(args: dict, _ctx: dict) -> dict:
    from services import python_scripts

    script = python_scripts.find_script(str(args.get('script_id') or args.get('name') or ''))
    if script is None:
        raise AIError('ai.pythonUnknown', kind='not_found', script=str(args.get('script_id') or ''))
    return {'script': script}


def tool_python_save_script(args: dict, _ctx: dict) -> dict:
    _python_ready()
    from services import python_scripts

    return {'script': python_scripts.save_script(args)}


def tool_python_run(args: dict, _ctx: dict) -> dict:
    _python_ready()
    from services import python_runtime, python_scripts

    script = python_scripts.find_script(str(args.get('script_id') or args.get('name') or ''))
    code = str(args.get('code') or (script or {}).get('code') or '')
    if not code:
        raise AIError('ai.pythonUnknown', kind='bad_request', script=str(args.get('script_id') or ''))
    rows = args.get('rows') if isinstance(args.get('rows'), list) else []
    result = python_runtime.run_code(
        code,
        rows,
        args.get('args') if isinstance(args.get('args'), dict) else {},
        timeout=_int_arg(args.get('timeout'), 120, 1, 3600),
        max_rows=_int_arg(args.get('max_rows'), 1000, 1, python_runtime.MAX_OUTPUT_ROWS),
        label=str((script or {}).get('name') or 'inline'),
    )
    # The AI gets the shape and a sample, not the whole table: a node run keeps every row, but a
    # conversation turn only needs to know whether the script worked and what its output looks like.
    sample = result['rows'][: _int_arg(args.get('sample_rows'), 5, 1, 10)]
    if not result.get('wrote_output', True):
        raise AIError('ai.pythonNoOutput', kind='error', script=str((script or {}).get('id') or 'inline'))
    return {
        'rows': len(result['rows']),
        'sample': sample,
        'columns': list(sample[0].keys()) if sample else [],
        'stdout': result['stdout'][-2000:],
        'stderr': result['stderr'][-2000:],
        'duration_ms': result['duration_ms'],
        'interpreter': result['interpreter'],
        'truncated': bool(result.get('truncated')),
    }


def tool_python_files(_args: dict, _ctx: dict) -> dict:
    from services import python_runtime

    return {'workspace': python_runtime.workspace(), 'files': python_runtime.list_files()}


def tool_python_read(args: dict, _ctx: dict) -> dict:
    from services import python_runtime

    return python_runtime.read_file(str(args.get('path') or ''))


def tool_python_write(args: dict, _ctx: dict) -> dict:
    _python_ready()
    from services import python_runtime

    return python_runtime.write_file(str(args.get('path') or ''), str(args.get('content') or ''))


def _files_ready() -> None:
    """The Harness tools exist only where the server can reach the user's machine."""
    from ai import environment

    if Config.CLOUD_MODE or not environment.capabilities()['user_files']:
        raise AIError('ai.workspaceCloud', kind='capability')


#: Tools whose effect is a change on the user's machine or their run records. With
#: ``ai_auto_approve`` off, one of these runs only after the user answered a ``request_approval``
#: question with the EXACT arguments it is about to use (see ``ai.approvals``). ``workspace_set``
#: is deliberately absent: choosing a folder is a setting the panel offers, not a per-call act.
APPROVAL_TOOLS = ('run_cmd', 'workspace_write', 'workspace_import', 'rerun_node')


def require_approval(name: str, args: dict, ctx: dict) -> None:
    """Refuse a mutating call the user has not approved in this conversation.

    The refusal NAMES the tool and tells the model to call ``request_approval`` first; the grant
    is keyed by the exact arguments, so an approval for one command cannot spend itself on another.
    """
    if get_setting('ai_auto_approve'):
        return
    if name in APPROVAL_TOOLS:
        from ai import approvals

        conversation_id = str((ctx or {}).get('conversation_id') or '')
        if approvals.consume(conversation_id, name, args or {}):
            return
    raise AIError('ai.approvalRequired', kind='capability', tool=name)


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


def tool_workflow_schema(_args: dict, _ctx: dict) -> dict:
    """The whole legal vocabulary: node types with seed params, the file shape and the rules."""
    from ai import vocabulary

    return vocabulary.workflow_schema()


def tool_workspace_info(_args: dict, _ctx: dict) -> dict:
    from ai import workspace

    return workspace.describe()


def tool_workspace_set(args: dict, _ctx: dict) -> dict:
    from ai import workspace

    return workspace.set_folder(str(args.get('path') or ''))


def tool_workspace_list(args: dict, _ctx: dict) -> dict:
    from ai import workspace

    return workspace.list_dir(
        str(args.get('path') or ''),
        kind=str(args.get('root') or 'folder'),
        limit=_int_arg(args.get('limit'), 200, 1, 500),
    )


def tool_workspace_read(args: dict, _ctx: dict) -> dict:
    from ai import workspace

    return workspace.read_text(
        str(args.get('path') or ''),
        kind=str(args.get('root') or 'folder'),
        max_bytes=_int_arg(args.get('max_bytes'), workspace.MAX_READ_BYTES, 200, workspace.MAX_READ_BYTES),
    )


def tool_workspace_write(args: dict, _ctx: dict) -> dict:
    _files_ready()
    from ai import workspace

    return workspace.write_text(str(args.get('path') or ''), str(args.get('content') or ''))


def tool_workspace_import(args: dict, _ctx: dict) -> dict:
    """A local table file → a dataset this account owns, parsed by the upload panel's parsers."""
    _files_ready()
    from ai import workspace

    return workspace.import_table(str(args.get('path') or ''), str(args.get('name') or ''))


def tool_run_command(args: dict, _ctx: dict) -> dict:
    _files_ready()
    from ai import workspace

    return workspace.run_command(
        str(args.get('command') or ''),
        cwd=str(args.get('cwd') or ''),
        timeout=_int_arg(args.get('timeout'), 120, 1, workspace.MAX_TIMEOUT),
    )


def tool_workflow_validate(args: dict, _ctx: dict) -> dict:
    from ai import workflow_draft

    payload = args.get('workflow') if isinstance(args.get('workflow'), dict) else args.get('payload')
    if not isinstance(payload, dict):
        raise AIError('ai.toolRefused', kind='bad_request', tool='workflow_validate', reason='workflow is missing')
    return workflow_draft.validate(payload)


def tool_app_errors(args: dict, _ctx: dict) -> dict:
    """The last thing the app said: backend log tail, failed runs and their console lines.

    This is the feedback half of the harness. A run that fails leaves a per-node error and console
    lines in ``runs.db``; a backend bug leaves a traceback in ``logs/app.log``. Both are read here,
    bounded, so the assistant can fix its own proposal without the user copying a stack trace.
    """
    import os

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


ASK_USER_SCHEMA = {
    'type': 'object',
    'properties': {
        'questions': {
            'type': 'array',
            'description': 'Questions to ask before continuing. Ask one at a time unless the choices are independent.',
            'items': {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string', 'description': 'Stable id echoed in the answer.'},
                    'question': {'type': 'string'},
                    'header': {'type': 'string'},
                    'options': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'label': {'type': 'string'},
                                'description': {'type': 'string'},
                                'value': {'type': 'string', 'description': 'Optional stable id echoed back.'},
                            },
                            'required': ['label'],
                        },
                    },
                    'multi_select': {'type': 'boolean'},
                    'kind': {'type': 'string', 'description': 'Optional marker; "approval" renders a danger card.'},
                },
                'required': ['id', 'question'],
            },
        }
    },
    'required': ['questions'],
}

UPDATE_PLAN_SCHEMA = {
    'type': 'object',
    'properties': {
        'steps': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'status': {'type': 'string', 'enum': ['pending', 'running', 'done', 'failed', 'skipped']},
                },
                'required': ['title'],
            },
        }
    },
    'required': ['steps'],
}

PRESENT_SCHEMA = {
    'type': 'object',
    'properties': {
        'title': {'type': 'string'},
        'kind': {
            'type': 'string',
            'enum': [
                'workflow_draft',
                'analysis_plan',
                'chart_spec',
                'report_draft',
                'skill_draft',
                'plugin_manifest',
                'monitor',
                'markdown',
            ],
        },
        'payload': {'type': 'object'},
        'summary': {'type': 'string'},
    },
    'required': ['title', 'kind'],
}


APPLY_WORKFLOW_SCHEMA = {
    'type': 'object',
    'properties': {
        'name': {'type': 'string', 'description': 'Saved workflow name. A clash gets a numeric suffix.'},
        'workflow': {
            'type': 'object',
            'description': 'The workflow file: {nodes:[{id,type,x,y,title,params}], connections:[{from,to}], '
            'settings:{mode,headless,disabledTypes}}. Read workflow_schema first.',
        },
        'run': {'type': 'boolean', 'description': 'Start the run right after it loads. Only when the user asked.'},
        'summary': {'type': 'string'},
    },
    'required': ['workflow'],
}


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

APPROVAL_SCHEMA = {
    'type': 'object',
    'properties': {
        'action': {'type': 'string', 'description': 'The tool name you are about to call.'},
        'summary': {'type': 'string', 'description': 'One sentence the user reads: what it will do.'},
        'detail': {
            'type': 'object',
            'description': 'The EXACT arguments you will pass to that tool, as a JSON object. After approval, '
            'repeat the identical call.',
        },
    },
    'required': ['action', 'summary', 'detail'],
}


TOOLS = {
    spec.name: spec
    for spec in (
        ToolSpec(
            'project_facts',
            'Read the generated project map: nodes, platforms, analysis operators and chart types.',
            {'type': 'object', 'properties': {}},
            handler=tool_project_facts,
        ),
        ToolSpec(
            'capabilities',
            'Read the crawler capability matrix. Pass a platform to narrow it.',
            {'type': 'object', 'properties': {'platform': {'type': 'string'}}},
            handler=tool_capabilities,
        ),
        ToolSpec(
            'docs_search',
            'Search the repository documentation for a phrase or concept.',
            {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
            handler=tool_docs_search,
        ),
        ToolSpec(
            'list_datasets',
            'List saved datasets in this account.',
            {'type': 'object', 'properties': {}},
            handler=tool_list_datasets,
        ),
        ToolSpec(
            'dataset_profile',
            'Read a dataset schema: row count, dtypes, missing values and samples. Never returns the whole table.',
            {'type': 'object', 'properties': {'dataset_id': {'type': 'string'}}},
            handler=tool_dataset_profile,
        ),
        ToolSpec(
            'dataset_sample',
            'Read up to 50 rows from a dataset. Prefer dataset_peek unless you need a specific page.',
            {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string'},
                    'limit': {'type': 'integer'},
                    'columns': {'type': 'array', 'items': {'type': 'string'}},
                    'offset': {'type': 'integer'},
                },
            },
            handler=tool_dataset_sample,
        ),
        ToolSpec(
            'dataset_peek',
            'Cheapest look at a table: column names/dtypes and a few rows (default 5, cells capped). '
            'Use this first; escalate to dataset_page or a Python script only when the answer needs it.',
            {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string'},
                    'columns': {'type': 'array', 'items': {'type': 'string'}},
                    'rows': {'type': 'integer'},
                    'width': {'type': 'integer'},
                },
            },
            handler=tool_dataset_peek,
        ),
        ToolSpec(
            'dataset_page',
            'Read a bounded page (max 50 rows) of a dataset when a peek is not enough. Says has_more.',
            {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string'},
                    'offset': {'type': 'integer'},
                    'limit': {'type': 'integer'},
                    'columns': {'type': 'array', 'items': {'type': 'string'}},
                    'width': {'type': 'integer'},
                },
            },
            handler=tool_dataset_page,
        ),
        ToolSpec(
            'list_runs',
            'List recent runs in this account.',
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
            'chart_catalog',
            'Read the chart registry and each chart’s required columns.',
            {'type': 'object', 'properties': {}},
            handler=tool_chart_catalog,
        ),
        ToolSpec(
            'analysis_catalog',
            'Read every analysis operator the pipeline knows.',
            {'type': 'object', 'properties': {}},
            handler=tool_analysis_catalog,
        ),
        ToolSpec(
            'code_search',
            'Search this checkout’s Python and JavaScript source. Local/desktop snapshot only.',
            {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
            permission='read:code',
            handler=tool_code_search,
        ),
        ToolSpec(
            'code_read',
            'Read one source file (bounded) for a citation or a patch proposal.',
            {
                'type': 'object',
                'properties': {'path': {'type': 'string'}, 'lines': {'type': 'integer'}},
                'required': ['path'],
            },
            permission='read:code',
            handler=tool_code_read,
        ),
        ToolSpec(
            'web_search',
            'Search the web with the provider’s standalone Search API; returns structured results.',
            {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'count': {'type': 'integer'},
                    'need_content': {'type': 'boolean'},
                },
                'required': ['query'],
            },
            permission='read:web',
            handler=tool_web_search,
        ),
        ToolSpec(
            'web_fetch',
            'Fetch one web page as Markdown with the provider’s standalone Fetch API.',
            {'type': 'object', 'properties': {'url': {'type': 'string'}}, 'required': ['url']},
            permission='read:web',
            handler=tool_web_fetch,
        ),
        ToolSpec(
            'ask_user_question',
            'Ask the user for a decision, a missing fact or a confirmation. Use options; '
            'pause until the human answers.',
            ASK_USER_SCHEMA,
            permission='ask',
            control=True,
        ),
        ToolSpec(
            'update_plan',
            'Publish or update a short plan for a multi-step task. The workspace renders it as a trace.',
            UPDATE_PLAN_SCHEMA,
            permission='plan',
            control=True,
        ),
        ToolSpec(
            'python_scripts',
            'List saved Python scripts (id, name, description, built-in, version). Metadata only.',
            {'type': 'object', 'properties': {}},
            handler=tool_python_scripts,
            permission='read:python',
        ),
        ToolSpec(
            'python_script',
            'Read one saved script in full, including its code, before editing or explaining it.',
            {'type': 'object', 'properties': {'script_id': {'type': 'string'}, 'name': {'type': 'string'}}},
            handler=tool_python_script,
            permission='read:python',
        ),
        ToolSpec(
            'python_save_script',
            'Create or update a reusable script in the account library. id/name/code are required; '
            'code reads CIXI_INPUT JSONL and writes CIXI_OUTPUT JSONL, args come from CIXI_ARGS.',
            {
                'type': 'object',
                'properties': {
                    'id': {'type': 'string'},
                    'name': {'type': 'string'},
                    'description': {'type': 'string'},
                    'code': {'type': 'string'},
                    'inputs': {'type': 'array', 'items': {'type': 'string'}},
                    'outputs': {'type': 'array', 'items': {'type': 'string'}},
                    'tags': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['id', 'name', 'code'],
            },
            handler=tool_python_save_script,
            permission='write:python',
        ),
        ToolSpec(
            'python_run',
            'Run a saved script or inline code on the rows you pass, and return a small sample plus '
            'stdout/stderr — never the whole output table.',
            {
                'type': 'object',
                'properties': {
                    'script_id': {'type': 'string'},
                    'name': {'type': 'string'},
                    'code': {'type': 'string'},
                    'rows': {'type': 'array', 'items': {'type': 'object'}},
                    'args': {'type': 'object'},
                    'timeout': {'type': 'integer'},
                    'max_rows': {'type': 'integer'},
                    'sample_rows': {'type': 'integer'},
                },
            },
            handler=tool_python_run,
            permission='exec:python',
        ),
        ToolSpec(
            'python_files',
            'List files in the account Python workspace (ai_python).',
            {'type': 'object', 'properties': {}},
            handler=tool_python_files,
            permission='read:python',
        ),
        ToolSpec(
            'python_read',
            'Read one file from the account Python workspace.',
            {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']},
            handler=tool_python_read,
            permission='read:python',
        ),
        ToolSpec(
            'python_write',
            'Write a text file in the account Python workspace (path traversal is refused).',
            {
                'type': 'object',
                'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}},
                'required': ['path', 'content'],
            },
            handler=tool_python_write,
            permission='write:python',
        ),
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
            'workspace_info',
            'Read the working folder this account chose, the app root commands default to, and the '
            'allowed executables.',
            {'type': 'object', 'properties': {}},
            handler=tool_workspace_info,
            permission='read:files',
        ),
        ToolSpec(
            'workspace_set',
            'Set this account’s working folder. Absolute path to an existing directory; "" clears it.',
            {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path']},
            handler=tool_workspace_set,
            permission='write:files',
        ),
        ToolSpec(
            'workspace_list',
            'List one directory of the WORKING FOLDER the user chose (the default: root="folder") — '
            'this is what “工作文件夹 / my folder / the project folder” means. Use root="app" ONLY when the '
            'user asks about this program’s own install/repository tree.',
            {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'root': {'type': 'string', 'enum': ['folder', 'app']},
                    'limit': {'type': 'integer'},
                },
            },
            handler=tool_workspace_list,
            permission='read:files',
        ),
        ToolSpec(
            'workspace_read',
            'Read one text file of the WORKING FOLDER the user chose (default root="folder"); '
            'root="app" is this program’s own tree, only when the user asks about the app. '
            'Bounded and reports truncation.',
            {
                'type': 'object',
                'properties': {
                    'path': {'type': 'string'},
                    'root': {'type': 'string', 'enum': ['folder', 'app']},
                    'max_bytes': {'type': 'integer'},
                },
                'required': ['path'],
            },
            handler=tool_workspace_read,
            permission='read:files',
        ),
        ToolSpec(
            'workspace_write',
            'Write a UTF-8 text file inside the working folder (the app tree is read-only).',
            {
                'type': 'object',
                'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}},
                'required': ['path', 'content'],
            },
            handler=tool_workspace_write,
            permission='write:files',
        ),
        ToolSpec(
            'workspace_import',
            'Import a local CSV/TSV/Excel/JSON/bibliographic file from the working folder as a dataset '
            'this account owns. Returns the dataset_id and columns.',
            {
                'type': 'object',
                'properties': {'path': {'type': 'string'}, 'name': {'type': 'string'}},
                'required': ['path'],
            },
            handler=tool_workspace_import,
            permission='write:files',
        ),
        ToolSpec(
            'run_cmd',
            'Run ONE allow-listed executable in the working folder (or the app root when no folder is '
            'chosen). No shell, no pipes, no chaining; args are passed as a list. Returns exit code, '
            'stdout and stderr — use it to run a saved script, git status or a test.',
            {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string'},
                    'cwd': {'type': 'string'},
                    'timeout': {'type': 'integer'},
                },
                'required': ['command'],
            },
            handler=tool_run_command,
            permission='exec:cmd',
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
            'apply_workflow',
            'Validate a workflow draft, SAVE it as this account’s workflow file and load it onto the '
            'canvas (optionally starting a run). Every problem is refused by name before anything loads.',
            APPLY_WORKFLOW_SCHEMA,
            permission='artifact',
            control=True,
        ),
        ToolSpec(
            'present_artifact',
            'Present a workflow draft, analysis plan, chart spec, report, skill draft, plugin manifest or a '
            'run monitor. The user applies it; kind="monitor" payload = {run_id, events, node_ids, statuses, '
            'min_rows, console_contains, outcomes, max_triggers, note}.',
            PRESENT_SCHEMA,
            permission='artifact',
            control=True,
        ),
        ToolSpec(
            'rerun_node',
            'Re-run ONE failed node and everything downstream of it, as a resume of the run that produced it. '
            'It does NOT load or replace the canvas: the SAVED workflow file is read, must still match the run '
            'record, and the kept upstream rows are reused. Refuses by name when the file is missing, the canvas '
            'changed, the node is unknown or the run is live.',
            RERUN_SCHEMA,
            permission='artifact',
            control=True,
        ),
        ToolSpec(
            'request_approval',
            'Ask the user to allow one exact mutating call (run_cmd / workspace_write / workspace_import / '
            'rerun_node) when automatic approval is off. Answer 允许一次 / 本次会话允许 / 拒绝; after an approval, '
            'repeat the identical tool call. Denial or cancel grants nothing.',
            APPROVAL_SCHEMA,
            permission='ask',
            control=True,
        ),
    )
}


def schemas(allow_code: bool = False, allow_python: bool = False, allow_files: bool = False) -> list:
    out = []
    scope = account_context.scope_key()
    for tool in TOOLS.values():
        if not scopes.visible('tools', tool.name, scope):
            # A tool another account installed is not this account's to offer.
            continue
        if tool.permission == 'read:code' and not allow_code:
            continue
        if tool.permission in ('read:python', 'write:python', 'exec:python') and not allow_python:
            continue
        if tool.permission in ('read:files', 'write:files', 'exec:cmd') and not allow_files:
            continue
        out.append(tool.schema())
    return out


def execute(name: str, args: dict, ctx: dict, allowed=None) -> dict:
    """Run one offered tool, refusing anything this turn did not promise or the user disabled.

    ``allowed`` is the set of tool names the turn's schema list contained. The schema list already
    applies the skill allowlist and the two switches; enforcing it again here closes the gap that
    a model (or a replayed ``tool_use``) can call a tool that was never offered.
    """
    tool = TOOLS.get(name)
    if tool is None:
        raise AIError('ai.toolUnknown', kind='bad_request', tool=name)
    if not scopes.visible('tools', name, account_context.scope_key()):
        # Registered by another account's plugin: installing is machine-level, USING is not.
        raise AIError('ai.toolRefused', kind='bad_request', tool=name, reason='not available for this account')
    if allowed is not None and name not in allowed:
        raise AIError('ai.toolRefused', kind='bad_request', tool=name, reason='not offered in this turn')
    if tool.control:
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool=name, reason='control tools are handled by the runtime'
        )
    if tool.handler is None:
        raise AIError('ai.toolRefused', kind='bad_request', tool=name, reason='no handler')
    if tool.permission == 'read:code':
        from ai import environment

        if not (get_setting('ai_allow_code_context') and environment.capabilities()['local_source']):
            raise AIError('ai.codeCloudRefused', kind='capability')
    if tool.permission in ('read:python', 'write:python', 'exec:python'):
        from ai import environment

        if Config.CLOUD_MODE:
            raise AIError('ai.pythonCloud', kind='capability')
        if not (get_setting('ai_allow_python') and environment.capabilities()['code_plugins']):
            raise AIError('ai.pythonDisabled', kind='capability')
    if tool.permission in ('read:files', 'write:files', 'exec:cmd'):
        from ai import environment

        if Config.CLOUD_MODE or not environment.capabilities()['user_files']:
            raise AIError('ai.workspaceCloud', kind='capability')
        # The user's own safety switch: with it off, touching the machine is a request, not an act.
        # The grant is per exact call (``ai.approvals``), never per tool name.
        if tool.permission in ('write:files', 'exec:cmd'):
            require_approval(name, args or {}, ctx or {})
    return tool.handler(args or {}, ctx or {})
