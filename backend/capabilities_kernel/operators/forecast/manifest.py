"""Extrapolate a period/value curve forward."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import Reads, Writes, operator_manifest

MANIFEST = operator_manifest(
    'forecast',
    title_key='op.forecast',
    category='time',
    order=360,
    summary='用移动平均、Holt 或 Holt-Winters 对一条曲线外推若干期，并给出区间。',
    when_to_use='情感演化曲线需要往后看几期（预测区间是模型给的，不是事实）。',
    when_not_to_use=('期数不足 min_periods 时按名拒绝，不要用拟合线冒充观测。',),
    handler='services.analysis.ops.forecast:forecast',
    params=(
        ParamSpec(name='column', type='string', default='period', widget='column'),
        ParamSpec(name='value_col', type='string', default='sentiment_index', widget='column'),
        ParamSpec(
            name='method',
            type='string',
            default='moving_average',
            enum=('moving_average', 'holt', 'seasonal_naive', 'holt_winters'),
            widget='select',
        ),
        ParamSpec(name='horizon', type='integer', default=3, minimum=1),
        ParamSpec(name='window', type='integer', default=3, minimum=1),
        ParamSpec(name='alpha', type='number', default=0.5, minimum=0, maximum=1),
        ParamSpec(name='beta', type='number', default=0.3, minimum=0, maximum=1),
        ParamSpec(name='min_periods', type='integer', default=4, minimum=2),
        ParamSpec(name='season', type='integer', default=7, minimum=2),
        ParamSpec(name='gamma', type='number', default=0.35, minimum=0, maximum=1),
    ),
    reads=Reads(one=('column', 'value_col')),
    writes=Writes(mode='replace', columns=('period', 'actual', 'predicted', 'lower', 'upper', 'horizon')),
    labels=(('method', 'settings.forecastMethod'), ('value_col', 'settings.forecastValueColumn')),
)
