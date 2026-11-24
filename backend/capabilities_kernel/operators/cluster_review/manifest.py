"""Review each bibliometric cluster: members, time span and a written summary."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'cluster_review',
    title_key='op.cluster_review',
    category='biblio',
    order=260,
    summary='按文献聚类分组，汇总成员、频次与年份跨度，并让模型写簇综述。',
    when_to_use='知识图谱聚类已生成，需要逐簇的文献计量解读。',
    when_not_to_use=('要给普通文本聚类写摘要用 cluster_label。',),
    handler='services.analysis.ops.cluster_review:cluster_review',
    params=(
        ParamSpec(name='group_col', type='string', default='聚类', widget='column'),
        ParamSpec(name='label_col', type='string', default='聚类标签', widget='column'),
        ParamSpec(name='name_col', type='string', default='节点', widget='column'),
        ParamSpec(name='freq_col', type='string', default='频次', widget='column'),
        ParamSpec(name='first_col', type='string', default='首年', widget='column'),
        ParamSpec(name='last_col', type='string', default='末年', widget='column'),
        ParamSpec(name='summary_col', type='string', default='簇综述', widget='text'),
        ParamSpec(name='members', type='integer', default=12, minimum=1),
        ParamSpec(
            name='on_fail',
            type='string',
            default='abort',
            enum=('abort', 'blank', 'fallback'),
            widget='select',
        ),
        ParamSpec(name='max_groups', type='integer', default=60, minimum=1),
    ),
    reads=Reads(one=('group_col', 'name_col'), nonblank=('summary_col',)),
    writes=Writes(mode='unknown'),
    panel=(
        PanelField('review_group_col', 'group_col', 'settings.reviewGroupColumn', default='聚类'),
        PanelField('review_label_col', 'label_col', 'settings.reviewLabelColumn', default='聚类标签'),
        PanelField('review_name_col', 'name_col', 'settings.reviewNameColumn', default='节点'),
        PanelField('review_freq_col', 'freq_col', 'settings.reviewFreqColumn', default='频次'),
        PanelField('review_summary_col', 'summary_col', 'settings.reviewSummaryColumn', default='簇综述'),
        PanelField(
            'review_on_fail',
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
        PanelField('review_max_groups', 'max_groups', 'settings.clusterMaxGroups', control='number', default=60),
        PanelField(
            'review_members',
            'members',
            'settings.reviewMembers',
            control='number',
            default=12,
            hint_key='settings.clusterReviewHint',
        ),
    ),
    needs_llm=True,
    labels=(
        ('name_col', 'settings.reviewNameColumn'),
        ('on_fail', 'settings.clusterOnFail'),
    ),
)
