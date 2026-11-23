"""Match the same topic between consecutive phases (sankey edges)."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'topic_flow',
    title_key='op.topic_flow',
    category='topic',
    order=320,
    summary='按特征词相似度把相邻阶段的主题配对，输出来源/目标、相似度与分歧度的流向边。',
    when_to_use='要画主题流向桑基图，说明“发酵期哪个议题变成了爆发期的什么议题”。',
    when_not_to_use=('只看单个主题的生命周期用 topic_timeline。',),
    handler='services.analysis.ops.topic_flow:topic_flow',
    params=(
        ParamSpec(name='stage_col', type='string', default='stage', widget='column'),
        ParamSpec(name='topic_col', type='string', default='topic', widget='column'),
        ParamSpec(name='words_col', type='string', default='feature_words', widget='column'),
        ParamSpec(name='weights_col', type='string', default='weights', widget='column'),
        ParamSpec(name='order_col', type='string', default='', widget='column'),
        ParamSpec(name='min_similarity', type='number', default=0.5, minimum=0, maximum=1),
        ParamSpec(name='label_col', type='string', default='', widget='column'),
    ),
    reads=Reads(one=('stage_col', 'topic_col', 'weights_col')),
    writes=Writes(
        mode='replace',
        columns=(
            'source',
            'target',
            'source_topic',
            'target_topic',
            'similarity',
            'divergence',
            'from_stage',
            'to_stage',
            'source_words',
            'target_words',
        ),
    ),
    labels=(
        ('stage_col', 'settings.flowStageColumn'),
        ('topic_col', 'settings.flowTopicColumn'),
        ('words_col', 'settings.flowWordsColumn'),
        ('weights_col', 'settings.flowWeightsColumn'),
    ),
)
