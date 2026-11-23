"""Sweep the topic count and report coherence (a coherence table, not a topic table)."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'topic_coherence',
    title_key='op.topic_coherence',
    category='topic',
    order=330,
    summary='在给定主题数区间上扫一遍 LDA，输出每个主题数的连贯度，帮助选择主题数。',
    when_to_use='不确定 n_topics 取几时，用连贯度曲线给依据。',
    when_not_to_use=('已有确定主题数就直接 topic_model，不必再扫。',),
    handler='services.analysis.ops.topic_coherence:topic_coherence',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='min_topics', type='integer', default=2, minimum=2),
        ParamSpec(name='max_topics', type='integer', default=8, minimum=2),
        ParamSpec(name='topn', type='integer', default=10, minimum=1),
        ParamSpec(name='max_features', type='integer', default=2000, minimum=10),
        ParamSpec(name='max_documents', type='integer', default=2000, minimum=0),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='unknown'),
)
