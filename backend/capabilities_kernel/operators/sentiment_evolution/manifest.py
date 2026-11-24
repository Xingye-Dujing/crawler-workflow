"""Turn a row-level polarity column into a per-period sentiment curve."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, operator_manifest
from capabilities_kernel.operators._panel import COLUMN

MANIFEST = operator_manifest(
    'sentiment_evolution',
    title_key='op.sentiment_evolution',
    category='time',
    order=350,
    summary='按时间列聚合情感标签，输出每期正/中/负占比、总量与可选的情感指数。',
    when_to_use='要画情感演化曲线：时间 × 正负比例 × 强度。',
    when_not_to_use=('要做预测用 forecast；要触发预警用 alert。',),
    handler='services.analysis.ops.sentiment_evolution:sentiment_evolution',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(name='label_col', type='string', default='sentiment', widget='column'),
        ParamSpec(name='positive', type='string', default='positive', widget='text'),
        ParamSpec(name='neutral', type='string', default='neutral', widget='text'),
        ParamSpec(name='negative', type='string', default='negative', widget='text'),
        ParamSpec(name='new_col', type='string', default='sentiment_index', widget='text'),
        ParamSpec(name='score_col', type='string', default='', widget='column'),
        ParamSpec(name='order_col', type='string', default='', widget='column'),
    ),
    panel=(
        COLUMN,
        PanelField('label_col', 'label_col', 'settings.labelColumn', default='sentiment'),
        PanelField('index_new_col', 'new_col', 'settings.newColumn', default='sentiment_index'),
        PanelField('label_positive', 'positive', 'settings.labelPositive', default='positive'),
        PanelField('label_neutral', 'neutral', 'settings.labelNeutral', default='neutral'),
        PanelField('label_negative', 'negative', 'settings.labelNegative', default='negative'),
        PanelField('score_col', 'score_col', 'settings.scoreColumn', default='score'),
        PanelField(
            'evolution_order_col',
            'order_col',
            'settings.evolutionOrderColumn',
            hint_key='settings.evolutionHint',
        ),
    ),
)
