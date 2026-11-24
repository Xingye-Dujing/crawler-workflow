"""Name each topic with one model call, writing a summary column."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'topic_label',
    title_key='op.topic_label',
    category='topic',
    order=240,
    summary='让本地模型读每主题的特征词与样本文本，写出一句主题概括。',
    when_to_use='主题表只有“词1 词2”时，需要给人读得懂的主题名或摘要。',
    when_not_to_use=('没有可用模型时不要调用：本步按名拒绝，绝不静默换成别的模型。',),
    handler='services.analysis.ops.topic_label:topic_label',
    params=(
        ParamSpec(name='words_col', type='string', default='feature_words', widget='column'),
        ParamSpec(name='samples_col', type='string', default='sample_texts', widget='column'),
        ParamSpec(name='summary_col', type='string', default='主题概括', widget='text'),
        ParamSpec(
            name='on_fail',
            type='string',
            default='abort',
            enum=('abort', 'blank', 'fallback'),
            widget='select',
        ),
        ParamSpec(name='max_topics', type='integer', default=30, minimum=1),
    ),
    reads=Reads(one=('words_col',), nonblank=('summary_col',)),
    writes=Writes(mode='add', add=(('summary_col', '主题概括'),)),
    panel=(
        PanelField('label_words_col', 'words_col', 'settings.labelWordsColumn', default='feature_words'),
        PanelField('label_samples_col', 'samples_col', 'settings.labelSamplesColumn', default='sample_texts'),
        PanelField('label_summary_col', 'summary_col', 'settings.labelSummaryColumn', default='主题概括'),
        PanelField(
            'label_on_fail',
            'on_fail',
            'settings.labelOnFail',
            control='select',
            default='abort',
            options=(
                ('abort', 'settings.labelOnFailAbort'),
                ('blank', 'settings.labelOnFailBlank'),
                ('fallback', 'settings.labelOnFailFallback'),
            ),
        ),
        PanelField(
            'label_max_topics',
            'max_topics',
            'settings.labelMaxTopics',
            control='number',
            default=30,
            hint_key='settings.topicLabelHint',
        ),
    ),
    needs_llm=True,
    labels=(
        ('words_col', 'settings.labelWordsColumn'),
        ('summary_col', 'settings.labelSummaryColumn'),
        ('on_fail', 'settings.labelOnFail'),
    ),
)
