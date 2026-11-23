"""Derive a calendar part (day/hour/weekday/month/year) from a timestamp column."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'extract_time',
    title_key='op.extract_time',
    category='time',
    order=190,
    summary='从时间列派生日期、小时、星期、月或年，写成新列。',
    when_to_use='事件研究要按天聚合、看周内节律，或给分阶段准备时间基准列。',
    when_not_to_use=('要按边界切成阶段用 bin_time；只改类型用 convert_type。',),
    handler='services.analysis.ops.extract_time:extract_time',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='new_col', type='string', default='日期', widget='text'),
        ParamSpec(
            name='part',
            type='string',
            default='date',
            enum=('date', 'hour', 'weekday', 'month', 'year'),
            widget='select',
        ),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='add', add=(('new_col', '日期'),)),
)
