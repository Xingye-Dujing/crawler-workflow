"""Extrapolate a period/value curve forward."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest

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
    panel=(
        PanelField('forecast_period_col', 'column', 'settings.forecastPeriodColumn', default='period'),
        PanelField('forecast_value_col', 'value_col', 'settings.forecastValueColumn', default='sentiment_index'),
        PanelField(
            'forecast_method',
            'method',
            'settings.forecastMethod',
            control='select',
            default='moving_average',
            options=(
                ('moving_average', 'settings.forecastMethodMa'),
                ('holt', 'settings.forecastMethodHolt'),
                ('seasonal_naive', 'settings.forecastMethodSeasonalNaive'),
                ('holt_winters', 'settings.forecastMethodHoltWinters'),
            ),
        ),
        PanelField('forecast_horizon', 'horizon', 'settings.forecastHorizon', control='number', default=3),
        PanelField('forecast_window', 'window', 'settings.forecastWindow', control='number', default=3),
        PanelField('forecast_season', 'season', 'settings.forecastSeason', control='number', default=7),
        PanelField('forecast_alpha', 'alpha', 'settings.forecastAlpha', control='number', default=0.5),
        PanelField('forecast_beta', 'beta', 'settings.forecastBeta', control='number', default=0.3),
        PanelField('forecast_gamma', 'gamma', 'settings.forecastGamma', control='number', default=0.35),
        PanelField(
            'forecast_min_periods',
            'min_periods',
            'settings.forecastMinPeriods',
            control='number',
            default=4,
            hint_key='settings.forecastHint',
        ),
    ),
    labels=(('method', 'settings.forecastMethod'), ('value_col', 'settings.forecastValueColumn')),
)
