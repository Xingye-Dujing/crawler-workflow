"""Fill empty cells with a literal value or a forward/backward fill."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMNS

MANIFEST = operator_manifest(
    'fill_null',
    title_key='op.fill_null',
    category='clean',
    order=20,
    summary='用固定值或上/下一行的值填补所选列的空单元格。',
    when_to_use='缺失值是“未填写”而不是“不存在”时，保留行并补上占位值。',
    when_not_to_use=('行本身没有意义（缺了关键字段就该丢弃）时用 drop_null。',),
    handler='services.analysis.ops.fill_null:fill_null',
    params=(
        ParamSpec(name='columns', type='array', default=[], widget='column'),
        ParamSpec(name='value', type='string', default='', widget='text'),
        ParamSpec(
            name='method',
            type='string',
            default=None,
            enum=('ffill', 'pad', 'bfill', 'backfill'),
            widget='select',
        ),
    ),
    reads=Reads(some=('columns',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMNS,
        PanelField('value', 'value', 'settings.value'),
        PanelField(
            'method',
            'method',
            'settings.fillMethod',
            control='select',
            default='',
            options=(('', 'settings.fillMethodValue'), ('ffill', ''), ('bfill', '')),
        ),
    ),
    labels=(('method', 'settings.fillMethod'),),
)
