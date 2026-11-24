"""Rank the terms of each topic by relevance (salience)."""

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
    'topic_salience',
    title_key='op.topic_salience',
    category='topic',
    order=300,
    summary='为每主题的词按“总体频率 + 主题内频率”的加权相关度排序，输出显著词表。',
    when_to_use='要画显著词图，或说明每个主题真正有区分度的词（而不是全语料高频词）。',
    when_not_to_use=('要主题距离图用 topic_map；要共现网络用 cooccur。',),
    handler='services.analysis.ops.topic_salience:topic_salience',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='n_topics', type='integer', default=5, minimum=2),
        ParamSpec(name='max_features', type='integer', default=2000, minimum=10),
        ParamSpec(name='topn', type='integer', default=30, minimum=1),
        ParamSpec(name='relevance', type='number', default=1.0, minimum=0, maximum=1),
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
    writes=Writes(
        mode='replace',
        columns=('topic', 'rank', 'term', 'overall_freq', 'within_freq', 'relevance'),
    ),
    panel=(
        COLUMN,
        N_TOPICS,
        TOPIC_METHOD,
        EMBEDDING_MODEL,
        PanelField('topic_topn', 'topn', 'settings.topicTermsTopn', control='number', default=30),
        PanelField('topic_lambda', 'relevance', 'settings.topicLambda', control='number', default=1),
        replace(TOPIC_MAX_FEATURES, hint_key='settings.topicSalienceHint'),
    ),
)
