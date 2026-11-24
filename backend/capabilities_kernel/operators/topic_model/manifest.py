"""Fit LDA or embedding topics over one text column."""

from dataclasses import replace

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import (
    COLUMN,
    EMBEDDING_MODEL,
    N_TOPICS,
    TOPIC_MAX_FEATURES,
    TOPIC_METHOD,
)

MANIFEST = operator_manifest(
    'topic_model',
    title_key='op.topic_model',
    category='topic',
    order=220,
    summary='对一列文本做主题建模（LDA 或句向量聚类），输出主题号、排名、特征词与权重。',
    when_to_use='要看语料由哪些议题构成，并得到每主题的特征词表。',
    when_not_to_use=('要按阶段分别建模用 topic_by_stage；只要词频共现用 cooccur。',),
    handler='services.analysis.ops.topic_model:topic_model',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='n_topics', type='integer', default=5, minimum=2),
        ParamSpec(name='topn', type='integer', default=10, minimum=1),
        ParamSpec(name='max_features', type='integer', default=2000, minimum=10),
        ParamSpec(
            name='method',
            type='string',
            default='auto',
            enum=('lda', 'embedding', 'auto'),
            widget='select',
        ),
        ParamSpec(name='embedding_model', type='string', default='', widget='text'),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='replace', columns=('topic', 'rank', 'keyword', 'weight')),
    panel=(
        COLUMN,
        N_TOPICS,
        TOPIC_METHOD,
        EMBEDDING_MODEL,
        PanelField('topic_topn', 'topn', 'settings.topicTopn', control='number', default=10),
        replace(TOPIC_MAX_FEATURES, hint_key='settings.topicHint'),
    ),
)
