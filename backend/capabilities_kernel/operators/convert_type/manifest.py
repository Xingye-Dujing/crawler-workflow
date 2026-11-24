"""Convert one column to another dtype."""

from capabilities_kernel.manifest import ParamSpec
from capabilities_kernel.operator import PanelField, Reads, Writes, operator_manifest
from capabilities_kernel.operators._panel import COLUMN

MANIFEST = operator_manifest(
    'convert_type',
    title_key='op.convert_type',
    category='clean',
    order=110,
    summary='把一列转换为文本/整数/小数/布尔/日期时间类型。',
    when_to_use='CSV 里数字被读成文本、时间戳需要变成 datetime 以按时间排序时。',
    when_not_to_use=('只想去空格用 strip_whitespace；要派生日期列用 extract_time。',),
    handler='services.analysis.ops.convert_type:convert_type',
    params=(
        ParamSpec(name='column', type='string', default='', widget='column'),
        ParamSpec(
            name='dtype',
            type='string',
            default='str',
            enum=('str', 'int', 'float', 'bool', 'datetime'),
            widget='select',
        ),
    ),
    reads=Reads(one=('column',)),
    writes=Writes(mode='passthrough'),
    panel=(
        COLUMN,
        PanelField(
            'dtype',
            'dtype',
            'settings.dtype',
            control='select',
            default='str',
            options=tuple((value, '') for value in ('str', 'int', 'float', 'bool', 'datetime')),
        ),
    ),
    labels=(('dtype', 'settings.dtype'),),
)
