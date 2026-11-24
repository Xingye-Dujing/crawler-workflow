"""Rank rows by semantic similarity to a literal query."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN, MODEL

MANIFEST = operator_manifest(
    'similar_to',
    title_key='op.similar_to',
    category='clean',
    order=60,
    summary='用本地句向量找出与给定文字最相似的前 K 行，输出新的相似度表。',
    when_to_use='围绕一个说法找相关评论/帖子，而不是按关键词精确过滤。',
    when_not_to_use=('要删除重复内容用 semantic_dedupe；按列值精确筛选用 filter_rows。',),
    handler='services.analysis.ops.similar_to:similar_to',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='query', type='string', default='', widget='textarea'),
        ParamSpec(name='top_k', type='integer', default=10, minimum=1),
        ParamSpec(name='model', type='string', default='BAAI/bge-small-zh-v1.5', widget='text'),
    ),
    reads=Reads(one=('column',), nonblank=('query',)),
    writes=Writes(mode='replace', columns=('rank', 'row_index', 'text', 'similarity')),
    panel=(
        COLUMN,
        MODEL,
        PanelField('query', 'query', 'settings.queryText'),
        PanelField('top_k', 'top_k', 'settings.topK', control='number', default=10),
    ),
)
