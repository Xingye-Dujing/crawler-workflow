"""Summarise each cluster with one model call, reducing the table to one row per cluster."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'cluster_label',
    title_key='op.cluster_label',
    category='topic',
    order=250,
    summary='按聚类列分组，让本地模型为每个簇写摘要，输出每簇一行。',
    when_to_use='已按主题/相似度聚好类，需要给每类一句可读的概括。',
    when_not_to_use=('要保留明细行只在旁边加一列用 topic_label。',),
    handler='services.analysis.ops.cluster_label:cluster_label',
    params=(
        ParamSpec(name='group_col', type='string', default='cluster', widget='column'),
        ParamSpec(name='text_col', type='string', default='正文', widget='column'),
        ParamSpec(name='summary_col', type='string', default='摘要', widget='text'),
        ParamSpec(
            name='on_fail',
            type='string',
            default='abort',
            enum=('abort', 'blank', 'fallback'),
            widget='select',
        ),
        ParamSpec(name='max_groups', type='integer', default=60, minimum=1),
        ParamSpec(name='sample_n', type='integer', default=8, minimum=1),
    ),
    reads=Reads(one=('group_col', 'text_col'), nonblank=('summary_col',)),
    writes=Writes(mode='dynamic'),
    panel=(
        PanelField('cluster_group_col', 'group_col', 'settings.clusterGroupColumn', default='cluster'),
        PanelField('cluster_text_col', 'text_col', 'settings.clusterTextColumn', default='正文'),
        PanelField('cluster_summary_col', 'summary_col', 'settings.clusterSummaryColumn', default='摘要'),
        PanelField(
            'cluster_on_fail',
            'on_fail',
            'settings.clusterOnFail',
            control='select',
            default='abort',
            options=(
                ('abort', 'settings.labelOnFailAbort'),
                ('blank', 'settings.labelOnFailBlank'),
                ('fallback', 'settings.labelOnFailFallback'),
            ),
        ),
        PanelField('cluster_max_groups', 'max_groups', 'settings.clusterMaxGroups', control='number', default=60),
        PanelField(
            'cluster_sample_n',
            'sample_n',
            'settings.clusterSampleN',
            control='number',
            default=8,
            hint_key='settings.clusterLabelHint',
        ),
    ),
    needs_llm=True,
    labels=(
        ('text_col', 'settings.clusterTextColumn'),
        ('on_fail', 'settings.clusterOnFail'),
    ),
)
