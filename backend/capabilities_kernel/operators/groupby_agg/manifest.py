"""Group rows and aggregate one (or more) value columns."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'groupby_agg',
    title_key='op.groupby_agg',
    category='statistics',
    order=140,
    summary='按一列分组，对另一列求和/均值/计数等，输出每组一行。',
    when_to_use='把明细表变成“每个平台/每天/每个主题一行”的统计表再画图。',
    when_not_to_use=('要保留明细只用 filter_rows；要比较两个平台的整体分布用 compare_platform。',),
    handler='services.analysis.ops.groupby_agg:groupby_agg',
    params=(
        ParamSpec(name='group_col', type='string', default='', widget='column'),
        ParamSpec(name='agg_col', type='string', default='', widget='column'),
        ParamSpec(
            name='agg_func',
            type='string',
            default='sum',
            enum=('sum', 'mean', 'median', 'min', 'max', 'count', 'nunique', 'std', 'var'),
            widget='select',
        ),
        ParamSpec(name='order_col', type='string', default='', widget='column'),
        ParamSpec(name='agg_metrics', type='array', default=[]),
    ),
    reads=Reads(one=('group_col', 'agg_col')),
    writes=Writes(mode='unknown'),
)
