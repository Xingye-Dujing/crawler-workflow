"""Dataset reads: peek cheaply, page on a grant, answer a number with one bounded aggregation.

The whole point of this module is BOUNDS. ``dataset_peek`` is the free look the user already sees;
everything larger goes through the conversation's grant (``_dataset_rows``); ``dataset_query`` is a
closed table of read-only aggregations, so a quantitative question never becomes a code-execution
surface. A missing column or an unknown op is refused BY NAME.
"""

import math

from runtime.settings import get_setting

from ai.errors import AIError
from ai.tools.shared import _int_arg
from ai.types import ToolSpec


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


TOOLS = (
    ToolSpec(
        'list_datasets',
        'List the saved datasets in this account, newest first with id and name. Read this to find an '
        'id; do not guess one, and never use it instead of dataset_profile when the question is about columns.',
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
)
