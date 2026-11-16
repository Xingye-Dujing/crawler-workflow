"""Read-only verbs the agent may call.

A tool never writes application state. It reads a dataset, a run, the capability matrix or the
docs and returns a bounded JSON/text result; a write is an *artifact* rendered as a proposal and
performed by the user through the app's normal route. That boundary is why an AI mistake cannot
delete a run or rewrite a canvas.

``ask_user_question``, ``update_plan`` and ``present_artifact`` are control tools: the runtime
intercepts them and never looks for a handler here.
"""

from core.config import Config

from ai.context import docs_search, project_facts
from ai.errors import AIError
from ai.types import ToolSpec


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
                'sample': [str(value)[:200] for value in series.dropna().head(3).tolist()],
            }
        )
    return {
        'dataset_id': str(args.get('dataset_id') or _ctx.get('dataset_id') or ''),
        'rows': len(frame),
        'columns': columns,
        'truncated': len(frame.columns) > 80,
    }


def tool_dataset_sample(args: dict, _ctx: dict) -> dict:
    frame = _dataset_frame(str(args.get('dataset_id') or _ctx.get('dataset_id') or ''))
    limit = max(1, min(50, int(args.get('limit') or 10)))
    return {
        'rows': frame.head(limit).to_dict('records'),
        'columns': [str(column) for column in frame.columns],
        'total': len(frame),
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

    limit = max(1, min(200, int(args.get('limit') or 80)))
    page = get_run_store().read_log(run_id, limit=limit)
    return {'rows': page.get('rows', []), 'has_more': bool(page.get('has_more'))}


def tool_chart_catalog(_args: dict, _ctx: dict) -> dict:
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
        ]
    }


def tool_analysis_catalog(_args: dict, _ctx: dict) -> dict:
    from services.analysis.ops import OPS

    return {'ops': sorted(OPS), 'count': len(OPS)}


def tool_list_runs(_args: dict, _ctx: dict) -> dict:
    from runtime.stores import get_run_store

    return {'runs': get_run_store().run_ledger()[:30]}


def tool_code_search(args: dict, _ctx: dict) -> dict:
    """A bounded read-only source search; local/admin only, never cloud."""
    if Config.CLOUD_MODE:
        raise AIError('ai.codeCloudRefused', kind='capability')
    query = str(args.get('query') or '').strip()
    if not query:
        raise AIError('ai.toolRefused', kind='bad_request', tool='code_search', reason='query is missing')
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = []
    for path in list(root.rglob('*.py'))[:2000] + list((root / 'static' / 'js').rglob('*.js'))[:2000]:
        if 'node_modules' in path.parts or 'vendor' in path.parts:
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if query not in text:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if query in line:
                hits.append({'path': str(path.relative_to(root)), 'line': line_number, 'text': line.strip()[:240]})
                if len(hits) >= 20:
                    return {'hits': hits, 'truncated': True}
    return {'hits': hits, 'truncated': False}


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
                            },
                            'required': ['label'],
                        },
                    },
                    'multi_select': {'type': 'boolean'},
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
                'markdown',
            ],
        },
        'payload': {'type': 'object'},
        'summary': {'type': 'string'},
    },
    'required': ['title', 'kind'],
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
            'Read up to 50 rows from a dataset.',
            {'type': 'object', 'properties': {'dataset_id': {'type': 'string'}, 'limit': {'type': 'integer'}}},
            handler=tool_dataset_sample,
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
            'Search this checkout’s Python and JavaScript source. Local/desktop only.',
            {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
            permission='read:code',
            handler=tool_code_search,
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
            'present_artifact',
            'Present a workflow draft, analysis plan, chart spec, report, skill draft or plugin manifest. '
            'The user applies it.',
            PRESENT_SCHEMA,
            permission='artifact',
            control=True,
        ),
    )
}


def schemas(allow_code: bool = False) -> list:
    out = []
    for tool in TOOLS.values():
        if tool.permission == 'read:code' and not allow_code:
            continue
        out.append(tool.schema())
    return out


def execute(name: str, args: dict, ctx: dict) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        raise AIError('ai.toolUnknown', kind='bad_request', tool=name)
    if tool.control:
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool=name, reason='control tools are handled by the runtime'
        )
    if tool.handler is None:
        raise AIError('ai.toolRefused', kind='bad_request', tool=name, reason='no handler')
    return tool.handler(args or {}, ctx or {})
