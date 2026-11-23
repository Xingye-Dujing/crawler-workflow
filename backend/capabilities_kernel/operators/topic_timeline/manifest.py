"""Follow each topic across lifecycle phases (first/peak/last stage)."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'topic_timeline',
    title_key='op.topic_timeline',
    category='topic',
    order=310,
    summary='跨阶段追踪主题：首次出现、峰值、最后出现的阶段与规模，识别二次爆发。',
    when_to_use='要讲“议题如何随事件推进”的故事，需要每主题的生命周期轨迹。',
    when_not_to_use=('要看阶段之间的主题流动用 topic_flow。',),
    handler='services.analysis.ops.topic_timeline:topic_timeline',
    params=(
        ParamSpec(name='stage_col', type='string', default='stage', widget='column'),
        ParamSpec(name='words_col', type='string', default='feature_words', widget='column'),
        ParamSpec(name='size_col', type='string', default='doc_n', widget='column'),
        ParamSpec(name='topic_col', type='string', default='topic', widget='column'),
        ParamSpec(name='order_col', type='string', default='', widget='column'),
        ParamSpec(name='min_overlap', type='number', default=0.5, minimum=0, maximum=1),
    ),
    reads=Reads(one=('stage_col', 'words_col', 'size_col')),
    writes=Writes(
        mode='replace',
        columns=(
            'topic',
            'topic_words',
            'first_stage',
            'peak_stage',
            'last_stage',
            'stages_present',
            'stage_path',
            'size_total',
            'peak_size',
            'is_secondary',
        ),
    ),
    labels=(
        ('stage_col', 'settings.timelineStageColumn'),
        ('words_col', 'settings.timelineWordsColumn'),
        ('topic_col', 'settings.timelineTopicColumn'),
        ('size_col', 'settings.timelineSizeColumn'),
    ),
)
