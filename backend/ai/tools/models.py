"""Local-model tools: what this machine can run, and two bounded ways to use one.

``model_infer`` is the workspace's "small job" verb — a few hundred rows through a distilled
classifier, never a dataset or a run — and ``model_rerank`` orders a short candidate list with a
cross-encoder. Both refuse by name: an unregistered model, a task without an analyzer, a family
without an infer path. A model the user named is never silently substituted.
"""

from ai.errors import AIError
from ai.tools.datasets import _dataset_frame
from ai.tools.shared import _int_arg
from ai.types import ToolSpec


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


TOOLS = (
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
)
