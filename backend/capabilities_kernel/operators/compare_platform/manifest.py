"""Compare platforms (or any grouping column) with counts and one aggregate."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'compare_platform',
    title_key='op.compare_platform',
    category='statistics',
    order=280,
    summary='按平台列（或任意分组列）统计行数，并可对一列数值求均值/求和。',
    when_to_use='多平台合并后要比较各平台的量与强度。',
    when_not_to_use=('只想看单一平台时用 filter_rows + groupby_agg。',),
    handler='services.analysis.ops.compare_platform:compare_platform',
    params=(
        ParamSpec(name='platform_col', type='string', default='platform', widget='column'),
        ParamSpec(name='value_col', type='string', default='', widget='column'),
        ParamSpec(
            name='agg',
            type='string',
            default='mean',
            enum=('mean', 'sum', 'median', 'min', 'max', 'count'),
            widget='select',
        ),
    ),
    reads=Reads(one=('platform_col',)),
    writes=Writes(mode='dynamic'),
    labels=(
        ('platform_col', 'settings.comparePlatformColumn'),
        ('value_col', 'settings.compareValueColumn'),
    ),
)
