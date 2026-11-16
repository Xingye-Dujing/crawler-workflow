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
from runtime.settings import get_setting

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
                'monitor',
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
            'present_artifact',
            'Present a workflow draft, analysis plan, chart spec, report, skill draft, plugin manifest or a '
            'run monitor. The user applies it; kind="monitor" payload = {run_id, events, node_ids, statuses, '
            'min_rows, console_contains, outcomes, max_triggers, note}.',
            PRESENT_SCHEMA,
            permission='artifact',
            control=True,
        ),
    )
}


def schemas(allow_code: bool = False, allow_python: bool = False) -> list:
    out = []
    for tool in TOOLS.values():
        if tool.permission == 'read:code' and not allow_code:
            continue
        if tool.permission in ('read:python', 'write:python', 'exec:python') and not allow_python:
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
    return tool.handler(args or {}, ctx or {})
