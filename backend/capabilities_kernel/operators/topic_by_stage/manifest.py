"""Fit one topic model per lifecycle phase."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import (
    COLUMN,
    EMBEDDING_MODEL,
    TOPIC_MAX_FEATURES,
    TOPIC_METHOD,
)

MANIFEST = operator_manifest(
    'topic_by_stage',
    title_key='op.topic_by_stage',
    category='topic',
    order=230,
    summary='按阶段列分别做主题建模，输出阶段、主题、特征词、权重、文档数与困惑度。',
    when_to_use='要比较“发酵期”和“爆发期”的议题差异，就需要每阶段一套主题。',
    when_not_to_use=('不关心阶段差异时用 topic_model；阶段本身要先由 bin_time 生成。',),
    handler='services.analysis.ops.topic_by_stage:topic_by_stage',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='stage_col', type='string', default='阶段', widget='column'),
        ParamSpec(name='order_col', type='string', default='', widget='column'),
        ParamSpec(name='topics', type='array', default=[]),
        ParamSpec(name='topn', type='integer', default=10, minimum=1),
        ParamSpec(name='max_features', type='integer', default=2000, minimum=10),
        ParamSpec(
            name='word_source',
            type='string',
            default='tfidf',
            enum=('tfidf', 'lda'),
            widget='select',
        ),
        ParamSpec(name='sample_n', type='integer', default=5, minimum=1),
        ParamSpec(
            name='method',
            type='string',
            default='auto',
            enum=('lda', 'embedding', 'auto'),
            widget='select',
        ),
        ParamSpec(name='embedding_model', type='string', default='', widget='text'),
    ),
    reads=Reads(one=('column', 'stage_col'), nonblank=('topics',)),
    writes=Writes(
        mode='replace',
        columns=('stage', 'stage_order', 'topic', 'feature_words', 'weights', 'doc_n', 'perplexity', 'sample_texts'),
    ),
    panel=(
        COLUMN,
        PanelField('stage_col', 'stage_col', 'settings.stageColumn', default='阶段'),
        PanelField('stage_order_col', 'order_col', 'settings.stageOrderColumn'),
        PanelField('stage_topic_counts', 'topics', 'settings.stageTopicCounts', default='5,6,4,4,4'),
        PanelField('topic_topn', 'topn', 'settings.topicTopn', control='number', default=10),
        TOPIC_MAX_FEATURES,
        PanelField('topic_sample_n', 'sample_n', 'settings.topicSampleN', control='number', default=5),
        TOPIC_METHOD,
        EMBEDDING_MODEL,
        PanelField(
            'word_source',
            'word_source',
            'settings.topicWordSource',
            control='select',
            default='tfidf',
            options=(('tfidf', 'settings.topicWordSourceTfidf'), ('lda', 'settings.topicWordSourceLda')),
            hint_key='settings.topicStageHint',
        ),
    ),
    labels=(('word_source', 'settings.topicWordSource'),),
)
