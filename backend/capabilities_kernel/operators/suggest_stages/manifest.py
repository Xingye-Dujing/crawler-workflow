"""Propose lifecycle phases from the volume curve of a timestamp column."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'suggest_stages',
    title_key='op.suggest_stages',
    category='time',
    order=210,
    summary='按时间列的每日/每窗行数曲线，提议若干个阶段边界（起点、终点、峰值）。',
    when_to_use='不知道该把事件切成几段时，先让数据给出候选边界，再人工确认。',
    when_not_to_use=('已有明确边界时直接 bin_time，不要用建议值覆盖已知事实。',),
    handler='services.analysis.ops.suggest_stages:suggest_stages',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='min_days', type='integer', default=3, minimum=1),
        ParamSpec(name='max_windows', type='integer', default=6, minimum=1),
        ParamSpec(name='peak_ratio', type='number', default=2.0, minimum=1),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(
        mode='replace',
        columns=('序号', '起点', '终点', '天数', '行数', '峰值日', '峰值计数', '依据'),
    ),
)
