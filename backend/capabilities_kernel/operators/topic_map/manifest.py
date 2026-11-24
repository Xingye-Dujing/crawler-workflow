"""Project topics into two dimensions for the topic distance figure."""

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
    'topic_map',
    title_key='op.topic_map',
    category='topic',
    order=290,
    summary='把主题投射到二维平面（pc1/pc2），并给出每主题的占比与特征词。',
    when_to_use='要画主题距离图（气泡位置=主题距离，大小=占比）。',
    when_not_to_use=('只想看特征词的重要性用 topic_salience。',),
    handler='services.analysis.ops.topic_map:topic_map',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='n_topics', type='integer', default=5, minimum=2),
        ParamSpec(name='max_features', type='integer', default=2000, minimum=10),
        ParamSpec(name='topn', type='integer', default=6, minimum=1),
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
    writes=Writes(mode='replace', columns=('topic', 'pc1', 'pc2', 'prevalence_pct', 'doc_n', 'feature_words')),
    panel=(
        COLUMN,
        N_TOPICS,
        TOPIC_METHOD,
        EMBEDDING_MODEL,
        PanelField('topic_topn', 'topn', 'settings.topicMapTopn', control='number', default=6),
        replace(TOPIC_MAX_FEATURES, hint_key='settings.topicMapHint'),
    ),
)
