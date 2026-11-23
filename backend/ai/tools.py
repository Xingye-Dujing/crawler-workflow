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

import logging
import math
import os
import re
from pathlib import Path

from core.config import Config
from runtime import account_context
from runtime.settings import get_setting

from ai.errors import AIError
from ai.types import ToolSpec

logger = logging.getLogger('ai.tools')


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


def _dataset_rows(dataset_id: str, wanted: int, ctx: dict) -> tuple[int, dict]:
    """Rows this read may return: the free/internal path, or the conversation's grant.

    Every larger row read (``dataset_page``, ``dataset_sample``, a filtered ``dataset_query``) goes
    through here. ``dataset_peek`` does not: five rows are the preview the user already sees.
    """
    from ai import dataset_access

    return dataset_access.consume(str((ctx or {}).get('conversation_id') or ''), dataset_id, wanted)


def tool_request_dataset_access(args: dict, ctx: dict) -> dict:
    """Create the conversation's grant AFTER the user approved this exact call.

    The approval card is the consent (the framework asks because this tool is always-ask), so this
    handler only records the grant it was approved for. It never widens the row budget itself.
    """
    from ai import dataset_access

    dataset_id = str(args.get('dataset_id') or '').strip()
    if not dataset_id:
        raise AIError('ai.datasetEmpty', kind='bad_request')
    conversation_id = str((ctx or {}).get('conversation_id') or '')
    if not conversation_id:
        raise AIError('ai.toolRefused', kind='bad_request', tool='request_dataset_access', reason='no conversation')
    rows = _int_arg(args.get('rows'), 0, 0, None)
    return {'grant': dataset_access.grant(conversation_id, dataset_id, rows)}


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


def tool_ai_coverage(_args: dict, _ctx: dict) -> dict:
    """The generated capability→entry matrix. A missing cell is a product gap, not a prompt issue."""
    from ai import coverage

    return coverage.audit()


def tool_catbus_status(_args: dict, _ctx: dict) -> dict:
    """Report the CatBus toolchain the app itself would use — one detector, two run modes.

    The adapter half comes from the SAME :func:`services.ingest.catbus.probe` the canvas backend
    uses, and the direct-command half from :func:`services.ingest.catbus.direct_cli_status`, which
    applies the same component-source rule. No PATH probe or path precedence is repeated here. The
    verdict is a server answer; the model never inspects paths itself or installs anything.
    """
    from services.ingest import catbus as bridge

    info = bridge.probe()
    status: dict = {
        'available': info.available,
        'reason_key': info.reason_key,
        'node': info.node,
        'node_version': info.node_version,
        'entry': info.entry,
        'platforms': list(info.platforms)[:30],
    }
    if not info.available:
        from i18n import t

        status['message'] = t(info.reason_key, **info.reason_params)
    # The direct CLI facts are the bridge's shared answer, not a second detection here.
    status.update(bridge.direct_cli_status(info.entry, info.node))
    local = status['local_cli']
    if not status['available']:
        status['hint'] = 'The canvas backend is unavailable — report the named reason; do not install.'
    elif status['cli_ok']:
        status['hint'] = 'Both paths are ready: the canvas second backend and direct AI catbus commands.'
    elif local:
        status['hint'] = (
            f'No global catbus CLI, but a local build exists at {local}. Ask the user whether to use '
            'this local build or to install the global CLI (npm i -g catbus-cli). Never install first.'
        )
    else:
        status['hint'] = (
            'No global catbus CLI and no local build found. Ask the user whether to install the global '
            'CLI (npm i -g catbus-cli) or point CATBUS_HOME at a checkout. Never install without consent.'
        )
    return status


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
    dataset_id = str(args.get('dataset_id') or _ctx.get('dataset_id') or '')
    frame = _dataset_frame(dataset_id)
    offset = _int_arg(args.get('offset'), 0, 0)
    limit = _int_arg(args.get('limit'), 20, 1, int(get_setting('ai_dataset_page_rows') or 2000))
    limit, grant = _dataset_rows(dataset_id, limit, _ctx)
    width = _int_arg(args.get('width'), 200, 40, 400)
    wanted = _project_columns(frame, args.get('columns')) or [str(column) for column in frame.columns[:40]]
    page = frame.iloc[offset : offset + limit]
    rows = [{name: _bounded_cell(row.get(name), width) for name in wanted} for row in page.to_dict('records')]
    result = {
        'dataset_id': dataset_id,
        'offset': offset,
        'limit': limit,
        'total_rows': len(frame),
        'rows': rows,
        'has_more': offset + len(rows) < len(frame),
        'next_offset': offset + len(rows),
    }
    if grant:
        result['grant'] = grant
    return result


#: Bounded, read-only aggregations a model may ask for. A name outside this table is refused BY
#: NAME: a query tool must never become a code-execution surface. The same table drives the tool
#: schema (so the model cannot invent an op) and the execution-time check (so a replayed history
#: cannot smuggle one in).
DATASET_QUERY_OPS = frozenset(
    {'count', 'sum', 'mean', 'median', 'min', 'max', 'std', 'nunique', 'value_counts', 'groupby', 'filter'}
)
_QUERY_AGG_OPS = frozenset({'count', 'sum', 'mean', 'median', 'min', 'max', 'std', 'nunique'})
_WHERE_OPS = frozenset({'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'contains'})


def _query_number(value) -> object:
    """A pandas/numpy scalar as JSON-safe data, keeping integers integers."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)[:200]
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 6)


def _query_label(value, width: int) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return '(missing)'
    text = str(value)
    return text[:width] + ('…' if len(text) > width else '')


def _query_where(frame, where):
    """Apply an optional, whitelisted filter before any aggregation."""
    if not where:
        return frame
    if not isinstance(where, dict):
        raise AIError('ai.toolRefused', kind='bad_request', tool='dataset_query', reason='where must be an object')
    column = str(where.get('column') or '').strip()
    if column not in frame.columns:
        raise AIError('ai.toolRefused', kind='bad_request', tool='dataset_query', reason=f'no column {column} in where')
    op = str(where.get('op') or 'eq').strip().lower()
    if op not in _WHERE_OPS:
        raise AIError('ai.toolRefused', kind='bad_request', tool='dataset_query', reason=f'unsupported where op {op}')
    value = where.get('value')
    series = frame[column]
    try:
        if op == 'eq':
            mask = series == value
        elif op == 'ne':
            mask = series != value
        elif op == 'gt':
            mask = series > value
        elif op == 'gte':
            mask = series >= value
        elif op == 'lt':
            mask = series < value
        elif op == 'lte':
            mask = series <= value
        else:
            # ``contains`` is a literal substring test, not a regex: a value like ``C++`` or
            # ``[知乎]`` must match those characters, not raise re.error or match other rows.
            mask = series.astype(str).str.contains(str(value), na=False, regex=False)
    except (TypeError, ValueError) as exc:
        raise AIError(
            'ai.toolRefused',
            kind='bad_request',
            tool='dataset_query',
            reason=f'where on {column} failed: {str(exc)[:120]}',
        ) from exc
    return frame[mask.fillna(False)]


def tool_dataset_query(args: dict, _ctx: dict) -> dict:
    """An exact, bounded answer to a quantitative question — no whole-table read, no code.

    ``dataset_peek`` exists to be cheap; it is not an answer to “how many / what is the mean”. This
    tool keeps those questions precise AND cheap: every op is a named pandas aggregation, every
    result is capped, and a missing column or an unknown op is a named refusal instead of a blank.
    """
    import pandas as pd

    dataset_id = str(args.get('dataset_id') or _ctx.get('dataset_id') or '')
    frame = _dataset_frame(dataset_id)
    op = str(args.get('op') or '').strip().lower()
    if op not in DATASET_QUERY_OPS:
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool='dataset_query', reason=f'unsupported op {op or "(empty)"}'
        )
    limit = _int_arg(args.get('limit'), 50, 1, 200)
    width = _int_arg(args.get('width'), 120, 40, 400)
    selected = _query_where(frame, args.get('where'))
    result: dict = {
        'dataset_id': dataset_id,
        'op': op,
        'total_rows': len(frame),
        'matched_rows': len(selected),
    }
    wanted = _project_columns(selected, args.get('columns'))
    if op == 'filter' and not wanted:
        # Like peek/page, a row read defaults to the leading columns; an aggregation still has to
        # name what it measures, so an empty `columns` is refused there.
        wanted = [str(column) for column in selected.columns[:40]]

    if op == 'count':
        result['columns'] = {name: int(selected[name].notna().sum()) for name in wanted}
        result['next'] = 'Report the numbers; do not pull rows just to count them again.'
        return result
    if not wanted:
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool='dataset_query', reason=f'columns is required for {op}'
        )

    if op == 'value_counts':
        if len(wanted) != 1:
            raise AIError(
                'ai.toolRefused',
                kind='bad_request',
                tool='dataset_query',
                reason='value_counts needs exactly one column',
            )
        counts = selected[wanted[0]].value_counts(dropna=False).head(limit)
        rows = [{'value': _query_label(key, width), 'count': int(count)} for key, count in counts.items()]
        result.update(
            {
                'column': wanted[0],
                'rows': rows,
                'truncated': len(counts) < int(selected[wanted[0]].nunique(dropna=False)),
                'next': 'These are exact counts; cite them instead of estimating from a peek.',
            }
        )
        return result

    if op == 'groupby':
        by_columns = _project_columns(selected, args.get('by'))
        if not by_columns:
            raise AIError(
                'ai.toolRefused',
                kind='bad_request',
                tool='dataset_query',
                reason='by must name at least one existing column',
            )
        agg = str(args.get('agg') or 'count').strip().lower()
        if agg not in _QUERY_AGG_OPS:
            raise AIError('ai.toolRefused', kind='bad_request', tool='dataset_query', reason=f'unsupported agg {agg}')
        measures = wanted[:20]
        try:
            grouped = selected.groupby(by_columns, dropna=False)[measures].agg(agg)
        except (TypeError, ValueError, KeyError) as exc:
            raise AIError(
                'ai.toolRefused', kind='bad_request', tool='dataset_query', reason=f'groupby failed: {str(exc)[:120]}'
            ) from exc
        groups = []
        for key, row in grouped.head(limit).iterrows():
            keys = key if isinstance(key, tuple) else (key,)
            entry = {name: _query_label(part, width) for name, part in zip(by_columns, keys, strict=True)}
            entry.update({name: _query_number(row.get(name)) for name in measures})
            groups.append(entry)
        result.update(
            {
                'by': by_columns,
                'agg': agg,
                'groups': groups,
                'truncated': len(grouped) > limit,
                'next': 'These are exact group totals; cite them instead of estimating from a peek.',
            }
        )
        return result

    if op == 'filter':
        limit, grant = _dataset_rows(dataset_id, limit, _ctx)
        columns = wanted[:40]
        page = selected.iloc[:limit]
        rows = [{name: _bounded_cell(row.get(name), width) for name in columns} for row in page.to_dict('records')]
        result.update(
            {
                'columns': columns,
                'rows': rows,
                'omitted_columns': max(0, len(selected.columns) - len(columns)),
                'truncated': len(selected) > limit,
                'next': 'Use an aggregation op for counts and totals; page only when the rows themselves matter.',
            }
        )
        if grant:
            result['grant'] = grant
        return result

    rows = []
    for name in wanted:
        series = selected[name]
        if op == 'count':
            value = int(series.notna().sum())
        elif op == 'nunique':
            value = int(series.nunique(dropna=True))
        else:
            try:
                number = pd.to_numeric(series, errors='coerce')
                value = getattr(number, op)()
            except (TypeError, ValueError, AttributeError) as exc:
                raise AIError(
                    'ai.toolRefused',
                    kind='bad_request',
                    tool='dataset_query',
                    reason=f'{op} on {name} failed: {str(exc)[:120]}',
                ) from exc
        rows.append({'column': name, op: _query_number(value)})
    result.update(
        {
            'columns': rows,
            'next': 'Report these numbers; do not pull the table to recompute them by eye.',
        }
    )
    return result


def tool_dataset_sample(args: dict, _ctx: dict) -> dict:
    """A bounded page with capped cells.

    It used to read ``frame.head(limit)`` and return whole posts, ignoring the schema's
    ``columns``/``offset`` — a third unbounded read path beside peek and page.
    """
    dataset_id = str(args.get('dataset_id') or _ctx.get('dataset_id') or '')
    frame = _dataset_frame(dataset_id)
    offset = _int_arg(args.get('offset'), 0, 0)
    limit = _int_arg(args.get('limit'), 10, 1, int(get_setting('ai_dataset_page_rows') or 2000))
    limit, grant = _dataset_rows(dataset_id, limit, _ctx)
    width = _int_arg(args.get('width'), 200, 40, 400)
    wanted = _project_columns(frame, args.get('columns')) or [str(column) for column in frame.columns[:40]]
    page = frame.iloc[offset : offset + limit]
    rows = [{name: _bounded_cell(row.get(name), width) for name in wanted} for row in page.to_dict('records')]
    result = {
        'rows': rows,
        'columns': wanted,
        'offset': offset,
        'total': len(frame),
        'has_more': offset + len(rows) < len(frame),
    }
    if grant:
        result['grant'] = grant
    return result


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


def tool_models_catalog(args: dict, _ctx: dict) -> dict:
    """The model registry, including what this machine can run and why it cannot run the rest."""
    from services.models import catalog, probe

    task = str(args.get('task') or '').strip()
    rows = catalog.public_rows()
    if task:
        rows = [
            row
            for row in rows
            if task in (row['task'], row['operation']) or task in row['default_for'] or row['family'] == task
        ]
    return {
        'models': rows,
        'count': len(rows),
        'runtime': probe.runtime_state(include_cuda=True),
        'rule': 'Choose the smallest model whose measured quality is within 1 point of the best; '
        'never substitute a different model for one the user named.',
    }


def tool_model_infer(args: dict, _ctx: dict) -> dict:
    """Read a BOUNDED sample with one local model, without writing a dataset or a run.

    This is the workspace's "small job" verb: answer a few rows with a distilled classifier or find
    the nearest neighbours in an embedding model. The whole table belongs in a workflow node; this
    tool never reads more than 200 rows and never returns an entire result table.
    """
    import pandas as pd

    from services.models import catalog
    from services.models.lease import hold

    model_id = str(args.get('model_id') or '').strip()
    try:
        manifest = catalog.runnable_or_refuse(model_id)
    except LookupError as exc:
        raise AIError('ai.toolRefused', kind='bad_request', tool='model_infer', reason=str(exc)) from exc
    limit = _int_arg(args.get('limit'), 50, 1, 200)
    column = str(args.get('column') or '').strip()
    if not column:
        raise AIError('ai.toolRefused', kind='bad_request', tool='model_infer', reason='column is missing')
    inline = args.get('rows')
    if isinstance(inline, list) and inline:
        frame = pd.DataFrame(inline)
    else:
        frame = _dataset_frame(str(args.get('dataset_id') or ''))
    total_rows = len(frame)
    frame = frame.head(limit)
    if column not in frame.columns:
        raise AIError('ai.toolRefused', kind='bad_request', tool='model_infer', reason=f'no column {column}')
    texts = [str(value) for value in frame[column].head(limit).tolist() if str(value).strip()]
    if not texts:
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool='model_infer', reason='no non-empty text in that column'
        )
    if manifest.family != 'text_classification':
        raise AIError(
            'ai.toolRefused',
            kind='capability',
            tool='model_infer',
            reason=f'family {manifest.family} has no infer tool yet; use a workflow node instead',
        )
    with hold(manifest.id):
        answer = _infer_text_classifier(manifest, texts, args)
    return {
        'model_id': manifest.id,
        'model': manifest.name,
        'rows': len(texts),
        'total_rows': total_rows,
        'truncated': total_rows > len(texts),
        **answer,
    }


def _infer_text_classifier(manifest, texts: list[str], args: dict) -> dict:
    """One text-classification pass; the analyzer owns label semantics and runtime printing."""
    from analyzers import EmotionAnalyzer, SentimentAnalyzer, TendencyAnalyzer

    task = manifest.task
    constructors = {
        'sentiment': lambda: SentimentAnalyzer(mode='bert', bert_model=manifest.path),
        'emotion': lambda: EmotionAnalyzer(mode='bert', bert_model=manifest.path),
        'tendency': lambda: TendencyAnalyzer(mode='bert', bert_model=manifest.path),
    }
    if task not in constructors:
        raise AIError(
            'ai.toolRefused',
            kind='capability',
            tool='model_infer',
            reason=f'task {task!r} has no analyzer; registered tasks: {", ".join(constructors)}',
        )
    import pandas as pd

    frame = pd.DataFrame({'text': texts})
    result = constructors[task]().analyze_dataframe(frame, text_column='text')
    label_col = manifest.outputs[0] if manifest.outputs else task
    score_col = manifest.outputs[1] if len(manifest.outputs) > 1 else 'confidence'
    labels = result[label_col].astype(str).tolist() if label_col in result.columns else []
    distribution: dict[str, int] = {}
    for label in labels:
        distribution[label] = distribution.get(label, 0) + 1
    sample = result[[col for col in ('text', label_col, score_col) if col in result.columns]].head(
        _int_arg(args.get('sample_rows'), 5, 1, 20)
    )
    return {
        'distribution': distribution,
        'labels': list(manifest.labels),
        'sample': sample.to_dict(orient='records'),
    }


def tool_model_rerank(args: dict, _ctx: dict) -> dict:
    """Order up to 50 candidate strings by a cross-encoder's relevance to one query."""
    from analyzers.backends.reranker import DEFAULT_MODEL, rerank

    query = str(args.get('query') or '').strip()
    candidates = args.get('candidates')
    if not query or not isinstance(candidates, list) or not candidates:
        raise AIError(
            'ai.toolRefused', kind='bad_request', tool='model_rerank', reason='query and candidates are required'
        )
    rows = [str(item) for item in candidates[:50]]
    try:
        ordered = rerank(
            query,
            rows,
            model_name=str(args.get('model') or DEFAULT_MODEL),
            top_k=_int_arg(args.get('top_k'), 10, 1, 50),
        )
    except Exception as exc:
        raise AIError('ai.toolRefused', kind='error', tool='model_rerank', reason=str(exc)[:200]) from exc
    return {'query': query, 'model': str(args.get('model') or DEFAULT_MODEL), 'results': ordered, 'count': len(ordered)}


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


#: The product's always-offered vocabulary: every turn may read the project, its workflow files,
#: the working folder, propose an apply and ask for dataset rows, whatever skill was chosen.
UNIVERSAL_TOOLS = frozenset(
    {
        'ai_coverage',
        'app_errors',
        'apply_workflow',
        'export_delete',
        'export_list',
        'request_dataset_access',
        'rerun_node',
        'workflow_delete',
        'workflow_export',
        'workflow_list',
        'workflow_read',
        'workflow_rename',
        'workflow_run',
        'workflow_schema',
        'workflow_stop',
        'workflow_update',
        'workflow_validate',
        'workspace_info',
        'workspace_list',
        'workspace_read',
    }
)


#: Tools whose effect is a change on the user's machine or their run records. With
#: ``ai_auto_approve`` off, one of these runs only after the user answered a ``request_approval``
#: question with the EXACT arguments it is about to use (see ``ai.approvals``). ``workspace_set``
#: is deliberately absent: choosing a folder is a setting the panel offers, not a per-call act.
APPROVAL_TOOLS = (
    'run_cmd',
    'workspace_write',
    'workspace_import',
    'request_dataset_access',
    'rerun_node',
    'apply_codebook',
    'apply_node_result',
    'workflow_update',
    'workflow_rename',
    'workflow_delete',
    'workflow_export',
    'workflow_run',
    'export_delete',
)

#: Deletions are never covered by ``ai_auto_approve``: that switch means "do not ask me about your
#: usual work", not "let a model remove my files". A per-call grant is still required here. A
#: dataset grant is the same kind of act: it lets the model read the user's data, so it always
#: asks, even when the model proposed a modest row count.
ALWAYS_APPROVAL_TOOLS = frozenset({'workflow_delete', 'export_delete', 'request_dataset_access'})

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


# ─── Saved workflows: list / read / update / rename / delete / export / run ───


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
                'memory',
                'markdown',
            ],
        },
        'payload': {'type': 'object'},
        'summary': {'type': 'string'},
    },
    'required': ['title', 'kind'],
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
            'ai_coverage',
            'Read the generated capability→AI-entry matrix: workflow nodes, platform modes, analysis '
            'operators, chart types and tools, each with the entry that reaches it and any gap.',
            {'type': 'object', 'properties': {}},
            handler=tool_ai_coverage,
        ),
        ToolSpec(
            'catbus_status',
            'Detect the local CatBus toolchain read-only: the 采析绘 adapter (Node + capabilities) and the '
            'global catbus CLI. Call this before deciding how to crawl; it never installs anything.',
            {'type': 'object', 'properties': {}},
            handler=tool_catbus_status,
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
            'Read a bounded page from a dataset. The account page budget is a setting; prefer '
            'dataset_peek unless you need a specific page.',
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
            'Read a bounded page of a dataset when a peek is not enough. The page budget is a setting; says has_more.',
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
            'request_dataset_access',
            'Ask the user to authorize reading rows of this dataset in this conversation. '
            'dataset_page, dataset_sample and a filtered dataset_query need this grant; dataset_peek '
            'stays free (five rows). rows=0 asks for all rows. The user sees an approval card with '
            'this dataset and row budget before anything is granted.',
            {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string'},
                    'rows': {
                        'type': 'integer',
                        'description': 'Maximum rows to read in this conversation; 0 = all rows.',
                    },
                    'reason': {'type': 'string', 'description': 'Why the rows are needed.'},
                },
                'required': ['dataset_id'],
            },
            permission='ask',
            handler=tool_request_dataset_access,
        ),
        ToolSpec(
            'dataset_query',
            'Answer an EXACT quantitative question about a dataset with one bounded read-only '
            'aggregation: count / sum / mean / median / min / max / std / nunique / value_counts / '
            'groupby / filter. Every result is capped and a missing column or unknown op is refused '
            'by name. Use this instead of guessing a number from the five rows dataset_peek shows.',
            {
                'type': 'object',
                'properties': {
                    'dataset_id': {'type': 'string'},
                    'op': {'type': 'string', 'enum': sorted(DATASET_QUERY_OPS)},
                    'columns': {'type': 'array', 'items': {'type': 'string'}},
                    'by': {'type': 'array', 'items': {'type': 'string'}},
                    'agg': {'type': 'string', 'enum': sorted(_QUERY_AGG_OPS)},
                    'where': {
                        'type': 'object',
                        'description': 'Optional filter: {column, op: eq|ne|gt|gte|lt|lte|contains, value}.',
                        'properties': {
                            'column': {'type': 'string'},
                            'op': {'type': 'string'},
                            'value': {},
                        },
                    },
                    'limit': {'type': 'integer'},
                    'width': {'type': 'integer'},
                },
                'required': ['op'],
            },
            handler=tool_dataset_query,
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
            'models_catalog',
            'Read the registered local models: task, labels, output columns, measured quality and '
            'speed, licence, and whether THIS machine can run each one. Call this before choosing a model.',
            {
                'type': 'object',
                'properties': {
                    'task': {
                        'type': 'string',
                        'description': 'Optional task or family to narrow the list, e.g. sentiment or embedding.',
                    }
                },
            },
            handler=tool_models_catalog,
        ),
        ToolSpec(
            'model_infer',
            'Run ONE local model on up to 200 rows of a dataset (or inline rows). Read-only: no dataset, '
            'run or canvas is written. Returns a label distribution and a small sample, not the whole table.',
            {
                'type': 'object',
                'properties': {
                    'model_id': {'type': 'string', 'description': 'A model id from models_catalog.'},
                    'dataset_id': {'type': 'string'},
                    'rows': {'type': 'array', 'items': {'type': 'object'}},
                    'column': {'type': 'string', 'description': 'The text column to read.'},
                    'limit': {'type': 'integer', 'description': 'Max rows to read; hard cap 200.'},
                    'sample_rows': {'type': 'integer'},
                },
                'required': ['model_id', 'column'],
            },
            handler=tool_model_infer,
            permission='exec:model',
        ),
        ToolSpec(
            'model_rerank',
            'Order up to 50 candidate strings by how well a small cross-encoder matches one query. '
            'Use it after a coarse retrieval, not on a whole table.',
            {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string'},
                    'candidates': {'type': 'array', 'items': {'type': 'string'}},
                    'model': {'type': 'string'},
                    'top_k': {'type': 'integer'},
                },
                'required': ['query', 'candidates'],
            },
            handler=tool_model_rerank,
            permission='exec:model',
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
}
